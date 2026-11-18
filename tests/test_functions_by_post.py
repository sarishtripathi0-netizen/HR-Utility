"""Functions by post: ALLOTTED posts (ADC, AC) vs posts that hold every function of their office (CO, CDC, DC, ...)."""
T = "2026-11-02T11:00:00+05:30"


def ok(resp):
    assert resp.status_code == 200, resp.text
    return resp.json()


def seat(client, office, post, fn, at=T):
    return ok(client.get("/v1/seat-holders", params={"office_id": office, "post_code": post, "function_code": fn, "at": at}))


def test_catalogue_lists_office_functions_and_post_modes(client):
    cat = ok(client.get("/v1/function-catalogue"))
    modes = {r["post_code"]: r["mode"] for r in cat["post_rules"]}
    assert modes["ADC"] == modes["ASSISTANT_COMMISSIONER"] == "ALLOTTED"
    assert modes["CIRCLE_OFFICER"] == modes["CO_DISTRICT_COMMISSIONER"] == modes["DISTRICT_COMMISSIONER"] == "ALL_OFFICE_FUNCTIONS"
    circle = next(o for o in cat["office_types"] if o["office_type"] == "CIRCLE_OFFICE")
    assert {"REVENUE", "LAND_RECORDS", "MUTATION"} <= {f["function_code"] for f in circle["functions"]}


def test_circle_officer_holds_every_circle_function_without_allotments(client):
    co = ok(client.get("/v1/posts/AS-CR-298-05-CIRCLE_OFFICER-01/holder", params={"at": T}))["holders"][0]
    assert co["holds_all_office_functions"] is True and co["functions_allotted"] == []
    cat = ok(client.get("/v1/function-catalogue", params={"office_type": "CIRCLE_OFFICE"}))
    for f in cat["office_types"][0]["functions"]:
        out = seat(client, "AS-CR-298-05", "CIRCLE_OFFICER", f["function_code"])
        assert out["status"] == "RESOLVED" and [h["employee_id"] for h in out["holders"]] == [co["employee_id"]]


def test_successor_circle_officer_inherits_functions_on_transfer(client):
    old = ok(client.get("/v1/posts/AS-CR-298-05-CIRCLE_OFFICER-01/holder", params={"at": T}))["holders"][0]
    new = ok(client.post("/v1/onboarding", json={"source": "MANUAL", "name": "New CO (test)", "pan": "AAAPE5555E",
                                                 "submitted_by": "t", "is_demo": True}))
    ok(client.post(f"/v1/postings/{old['posting_id']}/relieve", json={
        "at": T, "entered_by": "ESTB@AS-CR-298-05",
        "successor": {"employee_id": new["employee_id"], "charge_type": "SUBSTANTIVE", "order_ref": "REV/T/9",
                      "issuing_department": "Revenue & Disaster Management Department"}}))
    out = seat(client, "AS-CR-298-05", "CIRCLE_OFFICER", "MUTATION")
    assert [h["employee_id"] for h in out["holders"]] == [new["employee_id"]]
    before = seat(client, "AS-CR-298-05", "CIRCLE_OFFICER", "MUTATION", at="2026-11-02T10:59:00+05:30")
    assert [h["employee_id"] for h in before["holders"]] == [old["employee_id"]]


def test_allotting_to_an_all_functions_post_is_refused(client):
    co = ok(client.get("/v1/posts/AS-CR-298-05-CIRCLE_OFFICER-01/holder", params={"at": T}))["holders"][0]
    r = client.post("/v1/function-allotments", json={"employee_id": co["employee_id"], "office_id": "AS-CR-298-05",
                                                     "function_code": "REVENUE", "effective_from": T,
                                                     "entered_by": "ESTB@AS-CR-298-05"})
    assert r.status_code == 409 and "by virtue of their post" in r.json()["error"]["message"]


def test_function_must_be_on_the_office_type_list(client):
    adc = ok(client.get("/v1/posts/AS-D-298-ADC-01/holder", params={"at": T}))["holders"][0]
    r = client.post("/v1/function-allotments", json={"employee_id": adc["employee_id"], "office_id": "AS-D-298",
                                                     "function_code": "MEDICAL_REGISTRATION", "effective_from": T,
                                                     "entered_by": "ESTB@AS-D-298"})
    assert r.status_code == 409 and r.json()["error"]["rule"] == "BR-04"
    assert "not on the function list of a DC_OFFICE" in r.json()["error"]["message"]


def test_adc_holds_only_allotted_functions(client):
    adc = ok(client.get("/v1/posts/AS-D-298-ADC-01/holder", params={"at": T}))["holders"][0]
    assert adc["holds_all_office_functions"] is False
    assert adc["functions"] == adc["functions_allotted"] and adc["functions"]
    assert "SOCIAL_WELFARE" not in adc["functions"]


def test_cdc_and_dc_hold_every_function_of_their_office(client):
    cdc = seat(client, "SDO_D-285-BILASI", "CO_DISTRICT_COMMISSIONER", "SOCIAL_WELFARE")
    assert cdc["status"] == "RESOLVED" and cdc["holders"][0]["sanctioned_post_id"] == "SDO_D-285-BILASI-CO_DISTRICT_COMMISSIONER-01"
    dc = seat(client, "AS-D-298", "DISTRICT_COMMISSIONER", "ARTPS")
    assert dc["status"] == "RESOLVED" and dc["holders"][0]["sanctioned_post_id"] == "AS-D-298-DISTRICT_COMMISSIONER-01"
