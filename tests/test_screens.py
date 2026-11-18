"""Screens (section 8): each renders, states its as-of moment, and shows rule errors in plain English."""
from urllib.parse import urlencode

import pytest

AT = "2026-11-02T11:00"


def post_form(client, path, pairs):
    """Post repeated form fields (checkbox grids) as a urlencoded body."""
    return client.post(path, content=urlencode(pairs), headers={"Content-Type": "application/x-www-form-urlencoded"})


@pytest.mark.parametrize("path", ["/", "/ui/roster", "/ui/seat", "/ui/allotments", "/ui/postings", "/ui/leave", "/ui/history",
                                  "/ui/functions", "/ui/allotments?office_id=AS-CR-298-05"])
def test_every_screen_renders_with_as_of(client, path):
    r = client.get(path)
    assert r.status_code == 200, r.text[:500]
    assert "Asia/Kolkata" in r.text


def test_roster_shows_chairs_badges_and_date(client):
    r = client.get("/ui/roster", params={"office_id": "AS-D-298", "at": AT})
    assert "02-11-2026 11:00 IST" in r.text
    assert "AS-D-298-ADC-01" in r.text and "badge demo" in r.text and "SOCIAL_WELFARE" in r.text


def test_seat_lookup_shows_holders_link_officer_and_rule_step(client):
    holder = client.get("/v1/seat-holders", params={"office_id": "AS-D-298", "post_code": "ADC",
                                                    "function_code": "SOCIAL_WELFARE", "at": AT}).json()["holders"][0]
    client.post("/v1/availability", json={"employee_id": holder["employee_id"], "kind": "LEAVE",
                                          "from_ts": "2026-11-01", "to_ts": "2026-11-06", "entered_by": "t"})
    r = client.get("/ui/seat", params={"go": 1, "office_id": "AS-D-298", "post_code": "ADC",
                                       "function_code": "SOCIAL_WELFARE", "at": AT})
    assert "Link Officer" in r.text and "ARTPS_HOLDER" in r.text and "RESOLVED" in r.text


def test_relieve_without_successor_shows_br03_in_plain_english(client):
    p = client.get("/v1/posts/AS-CR-298-07-CIRCLE_OFFICER-01/holder", params={"at": AT}).json()["holders"][0]
    r = client.post("/ui/postings", data={"action": "relieve", "office_id": "AS-CR-298-07", "posting_id": p["posting_id"],
                                          "at": AT, "entered_by": "ESTB@AS-CR-298-07", "successor_id": "",
                                          "successor_charge": "SUBSTANTIVE", "order_ref": "", "issuing_department": ""})
    assert r.status_code == 200
    assert "BR-03" in r.text and "no one in charge" in r.text


def test_allotment_grid_save_creates_effective_dated_allotment(client):
    office = "AS-D-298"
    roster = client.get(f"/v1/offices/{office}/roster", params={"at": AT}).json()
    cols = ["SOCIAL_WELFARE", "E_GOVERNANCE", "ARTPS"]
    officer = next(h for c in roster["chairs"] for h in c["holders"]
                   if c["post_code"] == "ADC" and not set(h["functions"]) & set(cols))
    everyone = [h for c in roster["chairs"] for h in c["holders"] if not h["holds_all_office_functions"]]
    cells = [f"{h['employee_id']}|{f}" for h in everyone for f in h["functions_allotted"] if f in cols]
    cells.append(f"{officer['employee_id']}|E_GOVERNANCE")
    data = [("office_id", office), ("at", "2026-11-05T09:00"), ("entered_by", "ESTB@AS-D-298"), ("show_all", "0")]
    data += [("col", c) for c in cols] + [("officer", h["employee_id"]) for h in everyone] + [("cell", c) for c in cells]
    r = post_form(client, "/ui/allotments", data)
    assert r.status_code == 200 and "1 allotted, 0 withdrawn" in r.text, r.text[-2000:]
    before = client.get("/v1/function-allotments", params={"office_id": office, "employee_id": officer["employee_id"],
                                                           "at": "2026-11-05T08:59"}).json()["allotments"]
    after = client.get("/v1/function-allotments", params={"office_id": office, "employee_id": officer["employee_id"],
                                                          "at": "2026-11-05T09:00"}).json()["allotments"]
    assert "E_GOVERNANCE" not in [a["function_code"] for a in before]
    assert "E_GOVERNANCE" in [a["function_code"] for a in after]
    assert len(after) == len(before) + 1, "functions outside the visible columns are left alone"


def test_allotment_grid_rejects_wrong_establishment(client):
    r = post_form(client, "/ui/allotments", [("office_id", "AS-D-298"), ("at", AT), ("entered_by", "ESTB@DC_NGN"),
                                             ("show_all", "0")])
    assert "Only the Establishment branch of AS-D-298" in r.text


def test_leave_entry_and_history_screens(client):
    p = client.get("/v1/posts/AS-D-298-ADC-01/holder", params={"at": AT}).json()["holders"][0]
    r = client.post("/ui/leave", data={"office_id": "AS-D-298", "employee_id": p["employee_id"], "kind": "TOUR",
                                       "from_ts": "2026-11-10T09:00", "to_ts": "2026-11-12T18:00", "entered_by": "ESTB@AS-D-298"})
    assert "Recorded tour" in r.text
    r = client.get("/ui/history", params={"sanctioned_post_id": "AS-D-298-ADC-01", "frm": "2026-10-01", "to": "2026-10-31"})
    assert "Working days" in r.text and p["name"] in r.text
