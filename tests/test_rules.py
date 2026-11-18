"""Unit tests for BR-01 .. BR-10, at the domain layer."""
import json

import pytest
from sqlalchemy import select, text

from hr_utility.config import Settings
from hr_utility.domain import availability, functions, history, link_officer, onboarding, postings, seat
from hr_utility.domain import queries as q
from hr_utility.domain.common import RuleViolation
from hr_utility.mdm.seed_client import SeedMdmClient
from hr_utility.models import FunctionAllotment, MdmEmployee, OnboardingRequest, Posting
from tests.conftest import emp_id, ist

T = ist(2026, 11, 2, 11, 0)
ESTB_NAL = "ESTB@AS-D-298"


def holder(s, sp_id, t=T, charge="SUBSTANTIVE"):
    return next(p for p in q.postings_at(s, t, sanctioned_post_id=sp_id) if p.charge_type == charge)


def join(s, employee_id, sp_id, at, charge="ADDITIONAL"):
    return postings.join(s, postings.JoinRequest(employee_id, sp_id, charge, at, "ORDER/TEST/1", "Personnel Department", "tester"))


def leave(s, employee_id, frm=ist(2026, 11, 1), to=ist(2026, 11, 6)):
    return availability.record(s, employee_id, "LEAVE", frm, to, "tester")


def nal_adcs(s, t=T):
    return [holder(s, c.sanctioned_post_id, t).employee_id for c in q.chairs_in_office(s, "AS-D-298") if c.post_code == "ADC"]


# ---------------------------------------------------------------- BR-01

def test_br01_one_substantive_holder_per_post(db):
    with db.session() as s:
        other = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        with pytest.raises(RuleViolation) as e:
            join(s, other, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "SUBSTANTIVE")
        assert e.value.rule in ("BR-01", "BR-02")


def test_br01_additional_charges_may_coexist(db):
    with db.session() as s:
        a = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        b = holder(s, "AS-CR-298-04-CIRCLE_OFFICER-01").employee_id
        join(s, a, "AS-CR-298-05-CIRCLE_OFFICER-01", T)
        join(s, b, "AS-CR-298-05-CIRCLE_OFFICER-01", T)
        assert len(q.postings_at(s, T, sanctioned_post_id="AS-CR-298-05-CIRCLE_OFFICER-01")) == 3


# ---------------------------------------------------------------- BR-02

def test_br02_substantive_postings_never_overlap(db):
    with db.session() as s:
        postings.declare_vacant(s, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "Holder retired", "ESTB@AS-CR-298-05")
        busy = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        with pytest.raises(RuleViolation) as e:
            join(s, busy, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "SUBSTANTIVE")
        assert e.value.rule == "BR-02"


def test_br02_any_number_of_additional_charges(db):
    with db.session() as s:
        busy = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        for sp in ("AS-CR-298-05-CIRCLE_OFFICER-01", "AS-CR-298-04-CIRCLE_OFFICER-01", "AS-CR-298-06-CIRCLE_OFFICER-01"):
            join(s, busy, sp, T)
        assert len(q.postings_at(s, T, employee_id=busy)) == 4


# ---------------------------------------------------------------- BR-03

def test_br03_relieve_without_successor_is_rejected(db):
    with db.session() as s:
        p = holder(s, "AS-CR-298-05-CIRCLE_OFFICER-01")
        with pytest.raises(RuleViolation) as e:
            postings.relieve(s, p.id, T, "tester")
        assert e.value.rule == "BR-03" and "no one in charge" in e.value.message


def test_br03_relieve_with_additional_charge_starting_same_instant(db):
    with db.session() as s:
        p = holder(s, "AS-CR-298-05-CIRCLE_OFFICER-01")
        cover = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        join(s, cover, "AS-CR-298-05-CIRCLE_OFFICER-01", T)
        res = postings.relieve(s, p.id, T, "tester")
        assert res["ended"].effective_to == T
        assert [x.employee_id for x in q.postings_at(s, T, sanctioned_post_id="AS-CR-298-05-CIRCLE_OFFICER-01")] == [cover]


def test_br03_additional_charge_can_end_freely(db):
    with db.session() as s:
        cover = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        add = join(s, cover, "AS-CR-298-05-CIRCLE_OFFICER-01", ist(2026, 11, 1))
        postings.relieve(s, add.id, T, "tester")
        assert len(q.postings_at(s, T, sanctioned_post_id="AS-CR-298-05-CIRCLE_OFFICER-01")) == 1


def test_br03_vacancy_needs_reason_and_is_audited(db):
    with db.session() as s:
        with pytest.raises(Exception):
            postings.declare_vacant(s, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "  ", "ESTB@AS-CR-298-05")
    with db.session() as s:
        res = postings.declare_vacant(s, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "Officer suspended", "ESTB@AS-CR-298-05")
        assert res["ended"] and q.postings_at(s, T, sanctioned_post_id="AS-CR-298-05-CIRCLE_OFFICER-01") == []
        assert q.vacancy_at(s, "AS-CR-298-05-CIRCLE_OFFICER-01", T).reason == "Officer suspended"
        actions = [r[0] for r in s.execute(text("SELECT action FROM audit_log ORDER BY id DESC LIMIT 3"))]
        assert "DECLARE_VACANT" in actions


# ---------------------------------------------------------------- BR-04

def test_br04_only_officers_posted_in_the_office(db):
    with db.session() as s:
        outsider = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        with pytest.raises(RuleViolation) as e:
            functions.allot(s, outsider, "AS-D-298", "SOCIAL_WELFARE", T, ESTB_NAL)
        assert e.value.rule == "BR-04" and "does not hold a posting in AS-D-298" in e.value.message


def test_br04_posting_must_cover_whole_period(db):
    with db.session() as s:
        cover = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        join(s, cover, "AS-D-298-ASSISTANT_COMMISSIONER-01", T)
        with pytest.raises(RuleViolation):
            functions.allot(s, cover, "AS-D-298", "NAZARAT", ist(2026, 10, 1), ESTB_NAL)
        functions.allot(s, cover, "AS-D-298", "NAZARAT", T, ESTB_NAL)


def test_br04_function_code_must_exist_in_mdm(db):
    with db.session() as s:
        adc = nal_adcs(s)[0]
        with pytest.raises(RuleViolation) as e:
            functions.allot(s, adc, "AS-D-298", "NOT_A_FUNCTION", T, ESTB_NAL)
        assert "does not exist in the MDM" in e.value.message


def test_br04_only_establishment_branch_of_that_office(db):
    with db.session() as s:
        adc = nal_adcs(s)[0]
        with pytest.raises(RuleViolation) as e:
            functions.allot(s, adc, "AS-D-298", "NAZARAT", T, "ESTB@DC_NGN")
        assert "Only the Establishment branch of AS-D-298" in e.value.message


def test_br04_relieving_ends_functions_in_that_office(db):
    with db.session() as s:
        sw = emp_id(s, "Demo Officer NAL-1")
        chair = q.postings_at(s, T, employee_id=sw)[0]
        successor = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        postings.relieve(s, chair.id, T, "tester", postings.Successor(successor, "ADDITIONAL", "ORDER/2", "Personnel Department"))
        assert q.functions_at(s, sw, "AS-D-298", T) == []
        assert "SOCIAL_WELFARE" in q.functions_at(s, sw, "AS-D-298", ist(2026, 11, 1))


# ---------------------------------------------------------------- BR-05

def test_br05_reshuffle_is_effective_dated(db):
    with db.session() as s:
        a = emp_id(s, "Demo Officer NAL-1")
        b = nal_adcs(s)[0]
        day10 = ist(2026, 11, 10)
        fa = s.scalars(select(FunctionAllotment).where(FunctionAllotment.employee_id == a,
                                                       FunctionAllotment.function_code == "SOCIAL_WELFARE")).one()
        functions.withdraw(s, fa.id, day10, ESTB_NAL)
        functions.allot(s, b, "AS-D-298", "SOCIAL_WELFARE", day10, ESTB_NAL)
        settings = Settings()
        before = seat.seat_holders(s, settings, "AS-D-298", "ADC", "SOCIAL_WELFARE", ist(2026, 11, 9, 23, 59))
        after = seat.seat_holders(s, settings, "AS-D-298", "ADC", "SOCIAL_WELFARE", day10)
        assert [h["employee_id"] for h in before["holders"]] == [a]
        assert [h["employee_id"] for h in after["holders"]] == [b]


# ---------------------------------------------------------------- BR-06

def test_br06_same_kind_windows_must_not_overlap(db):
    with db.session() as s:
        e = nal_adcs(s)[0]
        leave(s, e)
        with pytest.raises(RuleViolation) as err:
            leave(s, e, ist(2026, 11, 5), ist(2026, 11, 9))
        assert err.value.rule == "BR-06"
        availability.record(s, e, "TOUR", ist(2026, 11, 5), ist(2026, 11, 9), "tester")


def test_br06_available_means_posted_and_not_away(db):
    with db.session() as s:
        e = nal_adcs(s)[0]
        assert q.availability_at(s, e, T) == (True, None)
        leave(s, e)
        assert q.availability_at(s, e, T) == (False, "LEAVE")
        assert q.availability_at(s, e, ist(2026, 11, 6)) == (True, None)
        assert q.availability_at(s, e, ist(2026, 1, 1)) == (False, "NOT_POSTED")


def test_br06_correction_supersedes_and_keeps_both(db):
    with db.session() as s:
        e = nal_adcs(s)[0]
        a = leave(s, e)
        b = availability.record(s, e, "LEAVE", ist(2026, 11, 1), ist(2026, 11, 4), "tester", supersedes_id=a.id)
        assert s.get(type(a), a.id).superseded_by == b.id
        assert q.availability_at(s, e, ist(2026, 11, 5)) == (True, None)


# ---------------------------------------------------------------- BR-07

def test_br07_dc_office_link_is_the_artps_holder(db):
    with db.session() as s:
        sw = emp_id(s, "Demo Officer NAL-1")
        leave(s, sw)
        res = link_officer.resolve(s, Settings(), q.postings_at(s, T, employee_id=sw)[0].sanctioned_post_id, T)
        assert res.status == "RESOLVED" and res.rule_step == "ARTPS_HOLDER"
        assert res.employee.name == "Demo Officer NAL-2"
        assert res.link_officer()["deemed_dps_under_rule_3_3"] is True


def test_br07_artps_holder_can_be_an_ac(db):
    with db.session() as s:
        kamal = emp_id(s, "Kamal Jeet Sarma")  # ADC holding ARTPS in Nagaon; the other holder is an AC
        leave(s, kamal)
        res = link_officer.resolve(s, Settings(), q.postings_at(s, T, employee_id=kamal)[0].sanctioned_post_id, T)
        assert res.rule_step == "ARTPS_HOLDER" and res.via_post.post_code == "ASSISTANT_COMMISSIONER"
        assert "ARTPS" in q.functions_at(s, res.employee.employee_id, "DC_NGN", T)


def test_br07_senior_most_artps_holder_wins(db):
    with db.session() as s:
        ac = holder(s, "AS-D-298-ASSISTANT_COMMISSIONER-01").employee_id
        functions.allot(s, ac, "AS-D-298", "ARTPS", ist(2026, 11, 1), ESTB_NAL)  # AC (batch 2022) vs demo ADC (no year)
        leave(s, emp_id(s, "Demo Officer NAL-1"))
        res = link_officer.resolve(s, Settings(), q.postings_at(s, T, employee_id=emp_id(s, "Demo Officer NAL-1"))[0]
                                   .sanctioned_post_id, T)
        assert res.employee.employee_id == ac, "the AC has a known batch year, so is senior to the demo ADC"


def test_br07_nobody_holding_artps_means_no_link_officer(db):
    with db.session() as s:
        for e in nal_adcs(s):  # includes the only ARTPS holder
            leave(s, e)
        res = link_officer.resolve(s, Settings(), "AS-D-298-ADC-01", T)
        assert res.status == "NO_LINK_OFFICER" and "No Link Officer is guessed" in res.reason
        dc = holder(s, "AS-D-298-DISTRICT_COMMISSIONER-01").employee_id
        assert q.availability_at(s, dc, T)[0] is True and "ARTPS" in q.functions_at(s, dc, "AS-D-298", T)
        assert res.employee is None, "the DC holds ARTPS by post but is not an ADC/AC, so never the Link Officer"


def test_br07_single_co_circle_link_is_the_sub_registrar(db):
    with db.session() as s:
        leave(s, holder(s, "AS-CR-298-05-CIRCLE_OFFICER-01").employee_id)
        res = link_officer.resolve(s, Settings(), "AS-CR-298-05-CIRCLE_OFFICER-01", T)
        assert res.rule_step == "SUB_REGISTRAR" and res.via_post.post_code == "SUB_REGISTRAR" and res.employee.is_demo


def test_br07_two_co_circle_link_is_the_other_co(db):
    with db.session() as s:
        cos = [c.sanctioned_post_id for c in q.chairs_in_office(s, "CO_GUWAHATI") if c.post_code == "CIRCLE_OFFICER"]
        assert len(cos) == 2
        leave(s, holder(s, cos[0]).employee_id)
        res = link_officer.resolve(s, Settings(), cos[0], T)
        assert res.rule_step == "SAME_POST" and res.via_post.sanctioned_post_id == cos[1]


def test_br07_post_without_a_rule_is_not_applicable(db):
    with db.session() as s:
        leave(s, holder(s, "ACMR-00ASM-REGISTRAR-D01").employee_id)  # ACMR has no rule (not in MDM yet)
        res = link_officer.resolve(s, Settings(), "ACMR-00ASM-REGISTRAR-D01", T)
        assert res.status == "NOT_APPLICABLE" and "No Link Officer rule covers post REGISTRAR" in res.reason


# ---------------------------------------------------------------- BR-08

def test_br08_history_sub_intervals_and_working_days(db):
    with db.session() as s:
        p = holder(s, "AS-CR-298-05-CIRCLE_OFFICER-01")
        incoming = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        handover = ist(2026, 12, 15, 10, 0)
        postings.relieve(s, p.id, handover, "tester", postings.Successor(incoming, "ADDITIONAL", "ORDER/3", "Personnel Department"))
        h = history.post_history(s, "AS-CR-298-05-CIRCLE_OFFICER-01", ist(2026, 12, 1), ist(2027, 1, 1))
        by = {x["employee_id"]: x for x in h["holders"]}
        assert by[p.employee_id]["working_days"] == 12  # 1-14 Dec less Sundays 6, 13
        assert by[incoming]["working_days"] == 14       # 15-31 Dec less Sundays 20, 27 and test holiday 25
        assert by[incoming]["charge_type"] == "ADDITIONAL"
        assert by[p.employee_id]["intervals"] == [{"from": "2026-12-01T00:00:00+05:30", "to": "2026-12-15T10:00:00+05:30"}]


# ---------------------------------------------------------------- BR-09

def test_br09_only_salted_hash_of_aadhaar_is_stored(db, settings):
    mdm = SeedMdmClient(settings.data_dir, settings.resolved_minted_store())
    token = "123412341234"
    with db.session() as s:
        req = onboarding.onboard(s, settings, mdm, onboarding.OnboardingInput(
            source="MANUAL", name="Test Contractual Officer", submitted_by="ESTB@AS-D-298", aadhaar_token=token, is_demo=True))
        assert req.status == "MINTED"
        dump = json.dumps([list(r) for r in s.execute(text("SELECT * FROM onboarding_request"))])
        audit = json.dumps([list(r) for r in s.execute(text("SELECT before_json, after_json FROM audit_log"))])
        assert token not in dump and token not in audit
        assert req.aadhaar_token_hash == onboarding.hash_aadhaar_token(token, settings.aadhaar_salt)
        assert req.aadhaar_token_hash != onboarding.hash_aadhaar_token(token, "another-salt")
    assert token not in settings.resolved_minted_store().read_text(encoding="utf-8")


def test_br09_demo_officers_are_flagged(db):
    with db.session() as s:
        demo = s.scalars(select(MdmEmployee).where(MdmEmployee.name.like("Demo Officer%"))).all()
        assert demo and all(e.is_demo for e in demo)
        out = seat.seat_holders(s, Settings(), "AS-D-298", "ADC", "SOCIAL_WELFARE", T)
        assert out["holders"][0]["is_demo"] is True


# ---------------------------------------------------------------- BR-10

def test_br10_no_hard_deletes(db, settings):
    with db.session() as s:  # make sure every table has a row for the trigger to guard
        leave(s, nal_adcs(s)[0])
        postings.declare_vacant(s, "AS-CR-298-05-CIRCLE_OFFICER-01", T, "test", "ESTB@AS-CR-298-05")
        onboarding.onboard(s, settings, SeedMdmClient(settings.data_dir, settings.resolved_minted_store()),
                           onboarding.OnboardingInput(source="MANUAL", name="X", submitted_by="t", pan="ABCDE1234F", is_demo=True))
    with db.session() as s:
        for table in ("posting", "function_allotment", "availability", "vacancy_declaration", "audit_log",
                      "event_outbox", "onboarding_request"):
            with pytest.raises(Exception, match="BR-10"):
                s.execute(text(f"DELETE FROM {table}"))
            s.rollback()


def test_br10_rows_are_not_edited_in_place(db):
    with db.session() as s:
        with pytest.raises(Exception, match="BR-10"):
            s.execute(text("UPDATE posting SET employee_id = 'EMP-999999' WHERE id = 1"))
        s.rollback()
        with pytest.raises(Exception, match="BR-10"):
            s.execute(text("UPDATE audit_log SET actor = 'x' WHERE id = 1"))
        s.rollback()


def test_br10_correction_keeps_old_and_new_rows(db):
    with db.session() as s:
        p = holder(s, "AS-CR-298-05-CIRCLE_OFFICER-01")
        cover = holder(s, "AS-CR-298-07-CIRCLE_OFFICER-01").employee_id
        res = postings.relieve(s, p.id, T, "tester", postings.Successor(cover, "ADDITIONAL", "ORDER/4", "Personnel Department"))
        old = s.get(Posting, p.id)
        assert old.superseded_by == res["ended"].id and old.effective_to is None
        assert res["ended"].effective_to == T and (res["ended"].lineage_id or res["ended"].id) == (p.lineage_id or p.id)
