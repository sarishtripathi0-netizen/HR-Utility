"""Acceptance tests H1..H15 (spec section 10), exercised through the HTTP API against the real seed."""
import re

import pytest

T = "2026-11-02T11:00:00+05:30"
NAL = "AS-D-298"
ESTB_NAL = "ESTB@AS-D-298"


# ---------------------------------------------------------------- helpers

def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def seat(client, office=NAL, post="ADC", fn="SOCIAL_WELFARE", at=T):
    return ok(client.get("/v1/seat-holders", params={"office_id": office, "post_code": post, "function_code": fn, "at": at}))


def roster(client, office=NAL, at=T):
    return ok(client.get(f"/v1/offices/{office}/roster", params={"at": at}))


def holders_of(client, office, post, at=T):
    return [c["holders"][0] for c in roster(client, office, at)["chairs"] if c["post_code"] == post and c["holders"]]


def officer(client, name, office=NAL):
    return next(h for c in roster(client, office)["chairs"] for h in c["holders"] if h["name"] == name)


def chair_holder(client, sp, at=T):
    return ok(client.get(f"/v1/posts/{sp}/holder", params={"at": at}))


def put_on_leave(client, employee_id, frm="2026-11-01T00:00:00+05:30", to="2026-11-06T00:00:00+05:30"):
    return ok(client.post("/v1/availability", json={"employee_id": employee_id, "kind": "LEAVE", "from_ts": frm,
                                                   "to_ts": to, "entered_by": ESTB_NAL}))


def onboard(client, name, **ids):
    body = {"source": "MANUAL", "name": name, "submitted_by": ESTB_NAL, "is_demo": True, **ids}
    return ok(client.post("/v1/onboarding", json=body))


def seniority(h):
    return (h["year_of_joining"] is None, h["year_of_joining"] or 0, h["name"].lower())


# ---------------------------------------------------------------- H1 .. H15

def test_h1_seat_lookup_nalbari_adc_social_welfare(client):
    out = seat(client)
    expected = [h for h in holders_of(client, NAL, "ADC") if "SOCIAL_WELFARE" in h["functions"]]
    assert out["status"] == "RESOLVED" and out["link_officer"] is None
    assert [h["employee_id"] for h in out["holders"]] == [h["employee_id"] for h in sorted(expected, key=seniority)]
    assert len(out["holders"]) >= 1 and all(h["sanctioned_post_id"].startswith("AS-D-298-ADC-") for h in out["holders"])


def test_h2_two_adcs_hold_social_welfare_senior_most_first(client):
    first = seat(client)["holders"][0]
    other = next(h for h in holders_of(client, NAL, "ADC")
                 if "SOCIAL_WELFARE" not in h["functions"] and h["year_of_joining"] is not None)
    ok(client.post("/v1/function-allotments", json={"employee_id": other["employee_id"], "office_id": NAL,
                                                    "function_code": "SOCIAL_WELFARE",
                                                    "effective_from": "2026-11-01T00:00:00+05:30", "entered_by": ESTB_NAL}))
    out = seat(client)
    assert {h["employee_id"] for h in out["holders"]} == {first["employee_id"], other["employee_id"]}
    assert out["holders"] == sorted(out["holders"], key=seniority)
    assert out["holders"][0]["employee_id"] == other["employee_id"]  # has a batch year; the demo officer has none


def test_h3_sole_holder_on_leave_link_is_the_artps_holder(client):
    # Spec H3 expected EQUAL_RANK_ARTPS; the business decision of 03-11-2026 names the step ARTPS_HOLDER.
    sole = seat(client)["holders"]
    assert len(sole) == 1
    put_on_leave(client, sole[0]["employee_id"])
    out = seat(client)
    assert out["holders"][0]["available"] is False and out["holders"][0]["unavailable_reason"] == "LEAVE"
    lo = out["link_officer"]
    artps = [h for h in holders_of(client, NAL, "ADC") if "ARTPS" in h["functions"]]
    assert lo["employee_id"] in {h["employee_id"] for h in artps}
    assert lo["rule_step"] == "ARTPS_HOLDER" and lo["deemed_dps_under_rule_3_3"] is True
    assert out["status"] == "RESOLVED"


def test_h4_no_adc_holding_artps_present_link_is_the_ac_holding_it(client):
    # Spec H4 expected the senior-most AC by rank (NEXT_LOWER_RANK). Under the 03-11-2026 rules the Link Officer
    # is whichever ADC/AC holds ARTPS, so the AC qualifies only once ARTPS is allotted to them.
    ac = holders_of(client, NAL, "ASSISTANT_COMMISSIONER")[0]
    ok(client.post("/v1/function-allotments", json={"employee_id": ac["employee_id"], "office_id": NAL,
                                                    "function_code": "ARTPS", "effective_from": "2026-11-01T00:00:00+05:30",
                                                    "entered_by": ESTB_NAL}))
    for h in holders_of(client, NAL, "ADC"):
        put_on_leave(client, h["employee_id"])
    out = seat(client)
    assert out["link_officer"]["rule_step"] == "ARTPS_HOLDER"
    assert out["link_officer"]["employee_id"] == ac["employee_id"]
    assert out["link_officer"]["sanctioned_post_id"].startswith("AS-D-298-ASSISTANT_COMMISSIONER-")


def test_lone_circle_officer_on_leave_link_is_the_sub_registrar(client):
    co = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    put_on_leave(client, co["employee_id"])
    out = seat(client, office="AS-CR-298-07", post="CIRCLE_OFFICER", fn="REVENUE")
    assert out["status"] == "RESOLVED" and out["link_officer"]["rule_step"] == "SUB_REGISTRAR"
    assert out["link_officer"]["sanctioned_post_id"] == "AS-CR-298-07-SUB_REGISTRAR-01" and out["link_officer"]["is_demo"]


def test_h5_nobody_else_present_no_link_officer(client):
    everyone = {h["employee_id"] for c in roster(client)["chairs"] for h in c["holders"]}
    for e in everyone:
        put_on_leave(client, e)
    out = seat(client)
    assert out["status"] == "NO_LINK_OFFICER" and out["link_officer"] is None
    assert out["reason"] and "No Link Officer is guessed" in out["reason"]


def test_h6_function_moves_on_day_10(client):
    a = seat(client)["holders"][0]
    b = next(h for h in holders_of(client, NAL, "ADC") if "SOCIAL_WELFARE" not in h["functions"])
    allots = ok(client.get("/v1/function-allotments", params={"office_id": NAL, "employee_id": a["employee_id"], "at": T}))
    sw = next(x for x in allots["allotments"] if x["function_code"] == "SOCIAL_WELFARE")
    day10 = "2026-11-10T00:00:00+05:30"
    ok(client.post(f"/v1/function-allotments/{sw['id']}/withdraw", json={"at": day10, "entered_by": ESTB_NAL}))
    ok(client.post("/v1/function-allotments", json={"employee_id": b["employee_id"], "office_id": NAL,
                                                    "function_code": "SOCIAL_WELFARE", "effective_from": day10,
                                                    "entered_by": ESTB_NAL}))
    day9 = seat(client, at="2026-11-09T12:00:00+05:30")
    on10 = seat(client, at=day10)
    assert [h["employee_id"] for h in day9["holders"]] == [a["employee_id"]]
    assert [h["employee_id"] for h in on10["holders"]] == [b["employee_id"]]


def test_h7_relieve_co_without_successor_rejected(client):
    p = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    r = client.post(f"/v1/postings/{p['posting_id']}/relieve", json={"at": T, "entered_by": "ESTB@AS-CR-298-07"})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["rule"] == "BR-03"
    assert "no one in charge" in err["message"] and "successor" in err["message"]
    assert chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]["employee_id"] == p["employee_id"]


def test_h8_relieve_with_successor_same_instant(client):
    old = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    new = onboard(client, "Successor Circle Officer (test)", pan="AAAPA1111A")
    after = ok(client.get("/v1/events", params={"after": 0, "limit": 5000}))["next_after"]
    handover = "2026-11-02T10:00:00+05:30"
    res = ok(client.post(f"/v1/postings/{old['posting_id']}/relieve", json={
        "at": handover, "entered_by": "ESTB@AS-CR-298-07",
        "successor": {"employee_id": new["employee_id"], "charge_type": "SUBSTANTIVE",
                      "order_ref": "REV/TEST/2026/1", "issuing_department": "Revenue & Disaster Management Department"}}))
    assert res["ended"]["effective_to"] == handover and res["successor"]["effective_from"] == handover
    assert chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01", "2026-11-02T09:59:00+05:30")["holders"][0]["employee_id"] == old["employee_id"]
    now = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01", handover)["holders"]
    assert [h["employee_id"] for h in now] == [new["employee_id"]]
    events = ok(client.get("/v1/events", params={"after": after}))["events"]
    kinds = {(e["type"], e["payload"]["employee_id"]) for e in events}
    assert ("posting.ended", old["employee_id"]) in kinds
    assert ("posting.started", new["employee_id"]) in kinds
    assert all(e["effective_at"] == handover for e in events if e["type"].startswith("posting."))


def test_h9_second_substantive_holder_rejected(client):
    new = onboard(client, "Second Holder (test)", pan="AAAPB2222B")
    r = client.post("/v1/postings", json={"employee_id": new["employee_id"], "sanctioned_post_id": "AS-CR-298-07-CIRCLE_OFFICER-01",
                                          "charge_type": "SUBSTANTIVE", "effective_from": T, "order_ref": "X/1",
                                          "issuing_department": "Revenue & Disaster Management Department",
                                          "entered_by": "ESTB@AS-CR-298-07"})
    assert r.status_code == 409 and r.json()["error"]["rule"] == "BR-01"
    assert "at most one substantive holder" in r.json()["error"]["message"]


def test_h10_substantive_plus_additional_charge_and_iam(client):
    a = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    ok(client.post("/v1/postings", json={"employee_id": a["employee_id"], "sanctioned_post_id": "AS-CR-298-05-CIRCLE_OFFICER-01",
                                         "charge_type": "ADDITIONAL", "effective_from": T, "order_ref": "DC/NAL/ADDL/1",
                                         "issuing_department": "Revenue & Disaster Management Department",
                                         "entered_by": "ESTB@AS-CR-298-05"}))
    at = "2026-11-02T12:00:00+05:30"
    posts = ok(client.get(f"/v1/employees/{a['employee_id']}/posts", params={"at": at}))["posts"]
    assert {(p["sanctioned_post_id"], p["charge_type"]) for p in posts} >= {
        ("AS-CR-298-07-CIRCLE_OFFICER-01", "SUBSTANTIVE"), ("AS-CR-298-05-CIRCLE_OFFICER-01", "ADDITIONAL")}
    login = ok(client.post("/v1/iam/login", params={"at": at}, json={"employee_id": a["employee_id"]}))
    assert login["stub"] is True and login["active_post_id"] == "AS-CR-298-07-CIRCLE_OFFICER-01"
    assert {p["sanctioned_post_id"] for p in login["posts"]} >= {"AS-CR-298-07-CIRCLE_OFFICER-01", "AS-CR-298-05-CIRCLE_OFFICER-01"}
    sw = ok(client.post("/v1/iam/switch", params={"at": at}, headers={"X-Stub-Session": login["session_id"]},
                        json={"sanctioned_post_id": "AS-CR-298-05-CIRCLE_OFFICER-01"}))
    assert sw["active_post_id"] == "AS-CR-298-05-CIRCLE_OFFICER-01"
    bad = client.post("/v1/iam/switch", params={"at": at}, headers={"X-Stub-Session": login["session_id"]},
                      json={"sanctioned_post_id": "AS-D-298-DISTRICT_COMMISSIONER-01"})
    assert bad.status_code == 409


def test_h10_iam_revokes_when_posting_ended_applies(client):
    a = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    add = ok(client.post("/v1/postings", json={"employee_id": a["employee_id"], "sanctioned_post_id": "AS-CR-298-05-CIRCLE_OFFICER-01",
                                               "charge_type": "ADDITIONAL", "effective_from": T, "order_ref": "X/2",
                                               "issuing_department": "Personnel Department", "entered_by": "t"}))
    at = "2026-11-02T12:00:00+05:30"
    sid = ok(client.post("/v1/iam/login", params={"at": at}, json={"employee_id": a["employee_id"]}))["session_id"]
    ok(client.post("/v1/iam/switch", params={"at": at}, json={"sanctioned_post_id": "AS-CR-298-05-CIRCLE_OFFICER-01", "session_id": sid}))
    ok(client.post(f"/v1/postings/{add['id']}/relieve", json={"at": "2026-11-03T10:00:00+05:30", "entered_by": "t"}))
    still = ok(client.get(f"/v1/iam/sessions/{sid}", params={"at": "2026-11-03T09:59:00+05:30"}))
    assert still["revoked"] is False
    gone = ok(client.get(f"/v1/iam/sessions/{sid}", params={"at": "2026-11-03T10:00:00+05:30"}))
    assert gone["revoked"] is True and "charge.ended" in gone["revoke_reason"]


def test_h10_iam_link_charge_revoked_when_availability_ended_applies(client):
    sole = seat(client)["holders"][0]
    put_on_leave(client, sole["employee_id"])
    lo = seat(client)["link_officer"]
    at = "2026-11-03T10:00:00+05:30"
    login = ok(client.post("/v1/iam/login", params={"at": at}, json={"employee_id": lo["employee_id"]}))
    link = next(p for p in login["posts"] if p["charge_type"] == "LINK" and p["sanctioned_post_id"] == sole["sanctioned_post_id"])
    assert link["rule_step"] == "ARTPS_HOLDER" and link["covering_for"][0]["employee_id"] == sole["employee_id"]
    ok(client.post("/v1/iam/switch", params={"at": at}, json={"sanctioned_post_id": link["sanctioned_post_id"],
                                                              "session_id": login["session_id"]}))
    back = ok(client.get(f"/v1/iam/sessions/{login['session_id']}", params={"at": "2026-11-06T00:00:00+05:30"}))
    assert back["revoked"] is True and "availability.ended" in back["revoke_reason"]


def test_h11_post_history_across_mid_month_transfer(client):
    old = chair_holder(client, "AS-CR-298-05-CIRCLE_OFFICER-01")["holders"][0]
    new = onboard(client, "Incoming Circle Officer (test)", pan="AAAPC3333C")
    ok(client.post(f"/v1/postings/{old['posting_id']}/relieve", json={
        "at": "2026-12-15T10:00:00+05:30", "entered_by": "ESTB@AS-CR-298-05",
        "successor": {"employee_id": new["employee_id"], "charge_type": "SUBSTANTIVE", "order_ref": "REV/TEST/2",
                      "issuing_department": "Revenue & Disaster Management Department"}}))
    h = ok(client.get("/v1/posts/AS-CR-298-05-CIRCLE_OFFICER-01/history", params={"from": "2026-12-01", "to": "2026-12-31"}))
    by = {x["employee_id"]: x for x in h["holders"]}
    assert set(by) == {old["employee_id"], new["employee_id"]}
    assert by[old["employee_id"]]["intervals"] == [{"from": "2026-12-01T00:00:00+05:30", "to": "2026-12-15T10:00:00+05:30"}]
    assert by[new["employee_id"]]["intervals"] == [{"from": "2026-12-15T10:00:00+05:30", "to": "2027-01-01T00:00:00+05:30"}]
    # Dec 2026: Sundays 6, 13, 20, 27; synthetic test holiday 25 Dec. Handover day (15th) counts for the incoming holder.
    assert by[old["employee_id"]]["working_days"] == 12
    assert by[new["employee_id"]]["working_days"] == 14
    assert h["holidays_in_interval"] == ["2026-12-25"] and h["unheld_intervals"] == []


def test_h12_onboard_same_person_twice_is_duplicate(client):
    first = onboard(client, "Contractual Officer (test)", finassam_code="FA-TEST-0001")
    second = onboard(client, "Contractual Officer, again (test)", finassam_code="FA-TEST-0001")
    assert first["status"] == "MINTED" and re.fullmatch(r"DEMO-\d{4}", first["employee_id"]), "demo: local ID"
    assert second["status"] == "DUPLICATE" and second["employee_id"] == first["employee_id"]


def test_h13_allot_function_to_officer_not_posted_in_office(client):
    outsider = chair_holder(client, "AS-CR-298-07-CIRCLE_OFFICER-01")["holders"][0]
    r = client.post("/v1/function-allotments", json={"employee_id": outsider["employee_id"], "office_id": NAL,
                                                     "function_code": "SOCIAL_WELFARE", "effective_from": T,
                                                     "entered_by": ESTB_NAL})
    assert r.status_code == 409 and r.json()["error"]["rule"] == "BR-04"


def test_h14_co_district_without_officer_returns_no_holder(client):
    cdc = chair_holder(client, "SDO_D-285-BILASI-CO_DISTRICT_COMMISSIONER-01")
    ok(client.post("/v1/posts/SDO_D-285-BILASI-CO_DISTRICT_COMMISSIONER-01/declare-vacant",
                   json={"at": "2026-11-01T00:00:00+05:30", "reason": "Test: no CDC posted", "entered_by": "ESTB@SDO_D-285-BILASI"}))
    assert chair_holder(client, "SDO_D-285-BILASI-CO_DISTRICT_COMMISSIONER-01")["status"] == "DECLARED_VACANT"
    for fn in ("SOCIAL_WELFARE", "ARTPS"):
        out = seat(client, office="SDO_D-285-BILASI", post="CO_DISTRICT_COMMISSIONER", fn=fn)
        assert out["status"] == "NO_HOLDER" and out["holders"] == [] and out["link_officer"] is None
        assert out["office_id"] == "SDO_D-285-BILASI"
    dc_office_people = {h["employee_id"] for c in roster(client, "AS-D-285")["chairs"] for h in c["holders"]}
    assert cdc["holders"][0]["employee_id"] not in dc_office_people


FORBIDDEN = {"DPS", "FAA", "SAA"}
MANDATED_KEYS = {"deemed_dps_under_rule_3_3"}  # spec section 6, BR-07 (e)


def _scan(obj, path="$"):
    bad = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in MANDATED_KEYS and (k.upper() in FORBIDDEN or set(k.upper().split("_")) & FORBIDDEN):
                bad.append(f"{path}.{k} (key)")
            bad += _scan(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad += _scan(v, f"{path}[{i}]")
    elif isinstance(obj, str) and re.search(r"\b(DPS|FAA|SAA)\b", obj, re.I):
        bad.append(f"{path} = {obj[:80]!r}")
    return bad


def test_h15_no_api_response_names_roles(client, db):
    responses = []
    put_on_leave(client, seat(client)["holders"][0]["employee_id"])
    responses.append(seat(client))
    responses.append(seat(client, office="DC_NGN", fn="ARTPS"))
    responses.append(seat(client, office="SDO_D-285-BILASI", post="CO_DISTRICT_COMMISSIONER"))
    for office in ("AS-D-298", "DC_NGN", "AS-D-285", "DC_KMM", "AS-D-302", "DAO_D-298", "ACMR-00ASM", "SDO_D-285-BILASI"):
        r = roster(client, office)
        responses.append(r)
        for c in r["chairs"]:
            responses.append(ok(client.get(f"/v1/posts/{c['sanctioned_post_id']}/link-officer", params={"at": T})))
            for h in c["holders"]:
                responses.append(ok(client.get(f"/v1/employees/{h['employee_id']}/posts", params={"at": T})))
    responses.append(ok(client.get("/v1/posts/AS-D-298-ADC-01/history", params={"from": "2026-03-01", "to": "2026-12-31"})))
    responses.append(ok(client.get("/v1/function-allotments", params={"office_id": "DC_NGN", "at": T})))
    responses.append(onboard(client, "Scan Officer (test)", pan="AAAPD4444D"))
    responses.append(ok(client.post("/v1/iam/login", json={"employee_id": "EMP-0001"})))
    responses.append(ok(client.get("/v1/events", params={"after": 0, "limit": 5000})))
    responses.append(ok(client.get("/openapi.json")))
    errors = [client.post("/v1/postings/1/relieve", json={"at": T, "entered_by": "x"}).json()]
    bad = [b for r in responses + errors for b in _scan(r)]
    assert bad == [], bad[:10]
    from sqlalchemy import text
    with db.session() as s:
        tables = [r[0] for r in s.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))]
        cols = [c[1] for t in tables for c in s.execute(text(f"PRAGMA table_info({t})"))]
    assert not [n for n in tables + cols if set(n.upper().split("_")) & FORBIDDEN]


def test_openapi_is_published(client):
    spec = ok(client.get("/openapi.json"))
    for path in ("/v1/seat-holders", "/v1/posts/{sanctioned_post_id}/holder", "/v1/posts/{sanctioned_post_id}/history",
                 "/v1/posts/{sanctioned_post_id}/link-officer", "/v1/employees/{employee_id}/posts",
                 "/v1/offices/{office_id}/roster", "/v1/onboarding", "/v1/postings", "/v1/postings/{posting_id}/relieve",
                 "/v1/function-allotments", "/v1/function-allotments/{allotment_id}/withdraw", "/v1/availability",
                 "/v1/posts/{sanctioned_post_id}/declare-vacant", "/v1/events", "/v1/iam/login", "/v1/iam/switch"):
        assert path in spec["paths"], path


@pytest.mark.parametrize("bad_at", ["yesterday", "2026-13-45"])
def test_bad_at_is_a_clear_422(client, bad_at):
    r = client.get("/v1/seat-holders", params={"office_id": NAL, "post_code": "ADC", "function_code": "ARTPS", "at": bad_at})
    assert r.status_code == 422 and "ISO-8601" in r.json()["error"]["message"]
