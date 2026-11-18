"""Seed builder and loader (step 2)."""
from sqlalchemy import func, select

from hr_utility.domain import queries as q
from hr_utility.models import AuditLog, EventOutbox, FunctionAllotment, MdmEmployee, MdmOffice, MdmSanctionedPost, Posting
from tests.conftest import ist

POC_DC_OFFICES = ["AS-D-298", "DC_KMM", "AS-D-285", "AS-D-302", "DC_NGN"]
T = ist(2026, 11, 2, 11, 0)


def test_offices_include_poc_districts_and_department_offices(db):
    with db.session() as s:
        ids = set(s.scalars(select(MdmOffice.office_id)))
    assert set(POC_DC_OFFICES) <= ids
    assert {"DAO_D-298", "ACMR-00ASM"} <= ids


def test_chairs_come_from_mdm_and_hold_at_most_one_substantive_holder(db):
    with db.session() as s:
        chairs = list(s.scalars(select(MdmSanctionedPost)))
        mdm = [c for c in chairs if not c.derived]
        local = [c for c in chairs if c.derived]
        assert mdm and all("MDM sanctioned-post" in c.source for c in mdm)
        assert local and all(c.is_demo for c in local), "only demo-only chairs are local"
        held = 0
        for c in chairs:
            subs = [p for p in q.postings_at(s, T, sanctioned_post_id=c.sanctioned_post_id) if p.charge_type == "SUBSTANTIVE"]
            assert len(subs) <= 1, c.sanctioned_post_id
            held += len(subs)
        assert held == s.scalar(select(func.count()).select_from(Posting)), "every seeded posting sits in a chair"


def test_chair_numbering_follows_seniority(db):
    with db.session() as s:
        holders = []
        for c in q.chairs_in_office(s, "AS-D-298"):
            if c.post_code == "ADC" and not c.derived:
                p = q.postings_at(s, T, sanctioned_post_id=c.sanctioned_post_id)[0]
                holders.append(q.employee(s, p.employee_id))
        assert len(holders) == 6 and holders == sorted(holders, key=q.seniority_key)


def test_every_poc_dc_office_has_e_district_function_holders(db):
    with db.session() as s:
        for office_id in POC_DC_OFFICES:
            held = {fa.function_code for fa in q.allotments_at(s, office_id, T)}
            assert {"SOCIAL_WELFARE", "E_GOVERNANCE", "ARTPS"} <= held, office_id


def test_demo_allotments_are_flagged(db):
    with db.session() as s:
        demo_fa = list(s.scalars(select(FunctionAllotment).where(FunctionAllotment.is_demo.is_(True))))
        assert demo_fa and all(fa.source_ref and fa.source_ref.startswith("DEMO") for fa in demo_fa)
        nagaon_demo = [fa for fa in demo_fa if fa.office_id == "DC_NGN"]
        assert nagaon_demo == [], "Nagaon has a real allotment order and needs no demo allotments"
        # Each e-District function the spec requires stays with exactly one (demo) officer per DC office.
        for office_id in ("AS-D-298", "DC_KMM", "AS-D-285", "AS-D-302"):
            for fn in ("SOCIAL_WELFARE", "E_GOVERNANCE", "ARTPS"):
                holders = {fa.employee_id for fa in q.allotments_at(s, office_id, T) if fa.function_code == fn}
                assert len(holders) == 1 and q.employee(s, holders.pop()).is_demo, (office_id, fn)


def test_real_adcs_and_acs_get_demo_bundles_outside_nagaon(db):
    with db.session() as s:
        for c in q.chairs_in_office(s, "AS-D-298"):
            held = q.postings_at(s, T, sanctioned_post_id=c.sanctioned_post_id)
            if c.post_code not in ("ADC", "ASSISTANT_COMMISSIONER") or not held:
                continue  # MDM sanctions chairs nobody on the roster holds yet
            assert q.allotted_functions_at(s, held[0].employee_id, "AS-D-298", T), c.sanctioned_post_id


def test_seed_went_through_audit_and_outbox(db):
    with db.session() as s:
        n_post = s.scalar(select(func.count()).select_from(Posting))
        assert s.scalar(select(func.count()).select_from(AuditLog)) >= n_post
        assert s.scalar(select(func.count()).select_from(EventOutbox).where(EventOutbox.type == "posting.started")) == n_post


def test_load_report_lists_inconsistencies(seed_dir):
    text = (seed_dir / "load_report.md").read_text(encoding="utf-8")
    for heading in ("Officer listed in two offices", "Shared mobile numbers", "Name variants merged",
                    "Missing inputs", "Demo officers for function coverage"):
        assert heading in text


def test_circle_offices_are_mdm_offices(db):
    with db.session() as s:
        circles = list(s.scalars(select(MdmOffice).where(MdmOffice.office_type == "CIRCLE_OFFICE")))
        assert len(circles) == 32 and all(o.mdm_id and not o.provisional for o in circles)


def test_circle_without_officer_answers_no_holder(client):
    out = client.get("/v1/seat-holders", params={"office_id": "AS-CR-297-08", "post_code": "CIRCLE_OFFICER",
                                                 "function_code": "REVENUE"}).json()
    assert out["status"] == "NO_HOLDER" and out["holders"] == [] and out["link_officer"] is None
    roster = client.get("/v1/offices/AS-CR-297-08/roster").json()
    assert roster["chairs"] and all(c["holders"] == [] for c in roster["chairs"]), "MDM sanctions chairs; nobody sits in them"


def test_acmr_office_named_from_department_code(db):
    with db.session() as s:
        assert s.get(MdmOffice, "ACMR-00ASM").name == "Assam Council of Medical Registration (state office)"


def test_synthetic_officer_directory_is_not_imported(db):
    with db.session() as s:
        emails = [e for e in s.scalars(select(MdmEmployee.email)) if e]
    assert not [e for e in emails if e.startswith(("kabita.chetia", "himangshu.changmai"))]


def test_employee_ids_come_from_mdm_and_demo_officers_stay_local(db):
    with db.session() as s:
        people = list(s.scalars(select(MdmEmployee)))
    real = [e for e in people if not e.is_demo]
    demo = [e for e in people if e.is_demo]
    assert len(demo) == 44 and all(e.employee_id.startswith("DEMO-") for e in demo)
    assert len(real) >= 84 and all(e.employee_id.startswith("EMP-") for e in real), "MDM mints every real ID"
