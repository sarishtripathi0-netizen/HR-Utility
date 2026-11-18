"""MDM PoC integration: everything MDM owns (offices, designations, cadres, functions, chairs, Link Officer rules,
employees, holidays) is read from MDM; HR events stay in the HR Utility. Offline: an httpx MockTransport serves the
saved MDM snapshot."""
import copy
import json

import httpx
import pytest

from hr_utility.mdm.http_client import HttpMdmClient
from hr_utility.mdm.mapping import WATCHED_TYPES
from hr_utility.mdm.sync import ensure_fresh, sync_state
from hr_utility.models import MdmEmployee, MdmOffice, MdmSanctionedPost

T = "2026-11-02T11:00:00+05:30"


class FakeMdm:
    """Serves data/mdm_snapshot/*.json like the MDM PoC; records writes; can bump versions or go offline."""

    def __init__(self, snap_dir):
        self.version = json.loads((snap_dir / "version.json").read_text(encoding="utf-8"))
        self.snaps = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in snap_dir.glob("*.json") if p.stem != "version"}
        self.down = False
        self.writes = []

    def bump(self, entity_type):
        self.version = {**self.version, "global": self.version["global"] + 1,
                        "entities": {**self.version["entities"], entity_type: self.version["entities"][entity_type] + 1}}

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("MDM unreachable", request=request)
        path = request.url.path
        if request.method != "GET":
            body = json.loads(request.content or b"{}")
            self.writes.append((request.method, path, body, request.headers.get("x-user")))
            if path == "/mdm/employees/mint":
                people = self.snaps["employee"]["records"]
                if body.get("mobile") and any(e.get("mobile") == body["mobile"] for e in people):
                    return httpx.Response(409, json={"message": "mobile already belongs to an employee"})
                code = f"EMP-{len(people) + 1000:04d}"
                people.append({"code": code, **body, "isActive": True})
                self.bump("employee")
                return httpx.Response(201, json={"version": self.version["global"], "record": {"code": code, **body}})
            if path == "/mdm/validate":
                results = {t: {c: "OK" for c in codes} for t, codes in body["refs"].items()}
                return httpx.Response(200, json={"valid": True, "results": results})
            return httpx.Response(200, json={"version": self.version["global"], "record": body})
        if path == "/mdm/version":
            return httpx.Response(200, json=self.version)
        if path.startswith("/mdm/snapshot/"):
            return httpx.Response(200, json=self.snaps[path.rsplit("/", 1)[1]])
        if path.startswith("/mdm/entities/sanctioned-post/"):
            code = path.rsplit("/", 1)[1]
            rec = next((r for r in self.snaps["sanctioned-post"]["records"] if r["code"] == code), None)
            return httpx.Response(200, json=rec) if rec else httpx.Response(404, json={})
        return httpx.Response(404, json={"message": "not faked"})


@pytest.fixture
def fake(seed_dir):
    return FakeMdm(seed_dir / "mdm_snapshot")


@pytest.fixture
def live(fake, settings):
    return HttpMdmClient("http://mdm.test", settings.data_dir, settings.resolved_minted_store(),
                         transport=httpx.MockTransport(fake.handler))


def test_offices_and_people_carry_mdm_codes(db):
    with db.session() as s:
        nal = s.get(MdmOffice, "AS-D-298")
        assert nal.office_type == "DC_OFFICE" and not nal.provisional and nal.mdm_id and nal.district_code == "D-298"
        assert not s.get(MdmOffice, "SDO_KMM-JAL").provisional, "co-districts now come from MDM"
        assert s.get(MdmOffice, "ACMR-00ASM").provisional, "ACMR stays local until MDM's ACR rename"
        kamal = s.query(MdmEmployee).filter(MdmEmployee.name == "Kamal Jeet Sarma").one()
        assert kamal.employee_id.startswith("EMP-") and len(kamal.employee_id) == 8 and kamal.year_of_joining == 2019
        assert all(e.employee_id.startswith("DEMO-") for e in s.query(MdmEmployee).filter(MdmEmployee.is_demo.is_(True)))


def test_chairs_are_mdm_strength_expanded(db):
    with db.session() as s:
        ngn_adc = [c for c in s.query(MdmSanctionedPost).filter(MdmSanctionedPost.office_id == "DC_NGN",
                                                                  MdmSanctionedPost.post_code == "ADC")]
        assert sorted(c.sanctioned_post_id for c in ngn_adc) == [f"DC_NGN-ADC-{i:02d}" for i in range(1, 7)]
        demo = s.query(MdmSanctionedPost).filter(MdmSanctionedPost.sanctioned_post_id == "AS-D-298-ADC-D01").one()
        assert demo.derived and demo.is_demo, "demo-only chairs are local and in their own series"


def test_working_days_use_mdm_holiday_rules(client):
    h = client.get("/v1/posts/AS-D-298-ADC-01/history", params={"from": "2026-11-01", "to": "2026-11-30"}).json()
    assert "2026-11-09" in h["holidays_in_interval"]      # gazetted Diwali: office closed
    assert "2026-11-24" not in h["holidays_in_interval"]  # restricted: a working day
    assert "2026-11-05" not in h["holidays_in_interval"]  # local to Karbi Anglong, not Nalbari


def test_live_client_matches_the_offline_copy(live, db):
    offices = {o.office_id: o for o in live.list_offices()}
    assert offices["DC_NGN"].office_type == "DC_OFFICE" and "ACMR-00ASM" in offices
    cadres = {c.code: c for c in live.list_cadres()}
    assert cadres["ALRS"].department_code == "RDM"
    modes = {r.post_code: r.mode for r in live.list_post_function_rules()}
    assert modes["ADC"] == "ALLOTTED" and modes["CIRCLE_OFFICER"] == "ALL_OFFICE_FUNCTIONS"
    rules = [r for r in live.list_link_rules() if r.office_type == "DC_OFFICE" and r.post_code == "ADC"]
    assert {r.covering_post_code for r in rules if r.priority == 1} >= {"ADC", "ASSISTANT_COMMISSIONER"}
    assert all(r.required_function == "ARTPS" for r in rules), "the local ARTPS condition is attached"
    with db.session() as s:
        cached = {c.sanctioned_post_id for c in s.query(MdmSanctionedPost)}
    assert {c.sanctioned_post_id for c in live.list_sanctioned_posts()} <= cached


def test_mint_goes_to_mdm_and_duplicate_mobile_is_reported(live, fake, db, settings):
    from hr_utility.domain import onboarding

    with db.session() as s:
        req = onboarding.onboard(s, settings, live, onboarding.OnboardingInput(
            source="MANUAL", name="Live Mint (test)", submitted_by="t", pan="AAAPL1234L", mobile="9876543210",
            gender="FEMALE", year_of_joining=2021))
        assert req.status == "MINTED" and req.employee_id.startswith("EMP-1")
        assert fake.writes[-1][1] == "/mdm/employees/mint" and fake.writes[-1][3] == "hr-utility-poc"
        assert "pan" not in fake.writes[-1][2], "identifiers stay in the HR Utility"
        again = onboarding.onboard(s, settings, live, onboarding.OnboardingInput(
            source="MANUAL", name="Same mobile", submitted_by="t", pan="AAAPM5678M", mobile="9876543210"))
        assert again.status == "DUPLICATE" and again.employee_id == req.employee_id
    assert live.get_employee(req.employee_id).year_of_joining == 2021, "HR-only batch year kept locally"


def test_demo_onboarding_never_reaches_mdm(live, fake, db, settings):
    from hr_utility.domain import onboarding

    with db.session() as s:
        req = onboarding.onboard(s, settings, live, onboarding.OnboardingInput(
            source="MANUAL", name="Demo Trial (test)", submitted_by="t", pan="AAAPD0001D", mobile="9000000001",
            gender="MALE", is_demo=True))
        assert req.status == "MINTED" and req.employee_id.startswith("DEMO-")
    assert not fake.writes, "a demo officer is minted locally, never in MDM"
    emp = live.get_employee(req.employee_id)
    assert emp.is_demo and emp.mobile == "9000000001"
    assert int(req.employee_id[5:]) > 44, "numbered after the seeded demo officers"


def test_version_check_refreshes_only_when_mdm_moves(db, live, fake):
    with db.session() as s:
        assert ensure_fresh(s, live, WATCHED_TYPES)["status"] == "REFRESHED"
    with db.session() as s:
        assert ensure_fresh(s, live, WATCHED_TYPES)["status"] == "FRESH"
    renamed = copy.deepcopy(fake.snaps["office"])
    for r in renamed["records"]:
        if r["code"] == "DC_NGN":
            r["name"] = "Office of the District Commissioner, Nagaon (renamed in MDM)"
    fake.snaps["office"] = renamed
    fake.bump("office")
    live._cache = None
    with db.session() as s:
        res = ensure_fresh(s, live, WATCHED_TYPES)
        assert res["status"] == "REFRESHED" and res["moved"] == ["office"]
    with db.session() as s:
        assert s.get(MdmOffice, "DC_NGN").name.endswith("(renamed in MDM)")


def test_mdm_outage_keeps_serving_the_last_copy(db, live, fake, client):
    with db.session() as s:
        ensure_fresh(s, live, WATCHED_TYPES)
    fake.down = True
    live._cache = None
    with db.session() as s:
        assert ensure_fresh(s, live, WATCHED_TYPES)["status"] == "STALE"
        assert "unreachable" in sync_state(s).last_error
    r = client.get("/v1/seat-holders", params={"office_id": "AS-D-298", "post_code": "ADC", "function_code": "ARTPS"})
    assert r.status_code == 200 and r.json()["status"] == "RESOLVED"
    assert r.headers["X-MDM-Stale"] == "true" and r.headers["X-MDM-Source"] == "http://mdm.test"


def test_posting_is_checked_with_mdm(client):
    holder = client.get("/v1/posts/AS-CR-298-05-CIRCLE_OFFICER-01/holder", params={"at": T}).json()["holders"][0]
    r = client.post("/v1/postings", json={"employee_id": holder["employee_id"], "sanctioned_post_id": "AS-CR-298-07-CIRCLE_OFFICER-01",
                                          "charge_type": "ADDITIONAL", "effective_from": T, "order_ref": "X/1",
                                          "issuing_department": "Revenue & Disaster Management Department",
                                          "entered_by": "t"})
    assert r.status_code == 200  # office, designation and employee all OK in MDM (emulated offline)


def test_post_code_aliases_and_responses_carry_mdm_freshness(client):
    r = client.get("/v1/seat-holders", params={"office_id": "AS-CR-298-05", "post_code": "CO", "function_code": "REVENUE"})
    assert r.json()["post_code"] == "CIRCLE_OFFICER" and r.json()["status"] == "RESOLVED"
    assert r.headers["X-MDM-Source"] == "SNAPSHOT" and r.headers["X-MDM-Version"].isdigit()


def test_usage_callback_for_mdm(client):
    def use(t, c):
        return client.get(f"/hr/usage/{t}/{c}").json()

    assert use("office", "AS-D-298")["inUse"] is True
    assert use("office", "SDO_D-298-SDR")["inUse"] is False
    assert use("designation", "CIRCLE_OFFICER")["inUse"] is True
    assert use("sanctioned-post", "DC_NGN:ADC")["inUse"] is True
    assert use("function", "ARTPS")["inUse"] is True
    assert use("cadre", "ACS")["inUse"] is True
    kamal = client.get("/v1/employees", params={"q": "Kamal Jeet"}).json()["employees"][0]["employee_id"]
    assert use("employee", kamal)["inUse"] is True
    assert use("holiday", "2026-12-25")["inUse"] is False
