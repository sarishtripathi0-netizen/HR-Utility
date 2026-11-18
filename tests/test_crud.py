"""Record management: list / view / create / correct / end, through the API and the screens. Nothing is deleted."""
from hr_utility.mdm.seed_client import SeedMdmClient

T = "2026-11-02T11:00:00+05:30"
NAL = "AS-D-298"
ESTB = "ESTB@AS-D-298"


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def onboard(client, name, pan):
    return ok(client.post("/v1/onboarding", json={"source": "MANUAL", "name": name, "pan": pan, "submitted_by": ESTB,
                                                  "is_demo": True}))


# ---------------------------------------------------------------- officers

def test_search_and_view_officers(client):
    found = ok(client.get("/v1/employees", params={"q": "Kamal Jeet", "at": T}))["employees"]
    assert [e["name"] for e in found] == ["Kamal Jeet Sarma"] and found[0]["posts"] == ["DC_NGN-ADC-05"]
    in_nal = ok(client.get("/v1/employees", params={"office_id": NAL, "at": T, "include_demo": "false"}))["employees"]
    assert in_nal and not any(e["is_demo"] for e in in_nal)
    d = ok(client.get(f"/v1/employees/{found[0]['employee_id']}", params={"at": T}))
    assert d["postings"][0]["state"] == "CURRENT" and {"ARTPS", "SOCIAL_WELFARE"} <= {f["function_code"] for f in d["function_allotments"]}


def test_correct_officer_record_goes_through_mdm_and_is_audited(client, settings):
    eid = onboard(client, "Corrected Officer (test)", "AAAPF6666F")["employee_id"]
    r = ok(client.put(f"/v1/employees/{eid}", json={"submitted_by": ESTB, "email": "co.test@assam.gov.in", "year_of_joining": 2018}))
    assert r["year_of_joining"] == 2018 and r["email"] == "co.test@assam.gov.in"
    # the correction lives in the MDM stand-in, so it survives a restart
    again = SeedMdmClient(settings.data_dir, settings.resolved_minted_store()).get_employee(eid)
    assert again.year_of_joining == 2018
    audit = ok(client.get("/v1/audit", params={"entity": "mdm_cache_employee", "entity_id": eid}))["entries"]
    assert audit[0]["action"] == "EMPLOYEE_CORRECT"
    assert client.put(f"/v1/employees/{eid}", json={"submitted_by": ESTB, "pan": "ZZZZZ9999Z"}).status_code == 422


# ---------------------------------------------------------------- chairs

def test_add_post_and_abolish_a_chair(client):
    chairs = ok(client.get(f"/v1/offices/{NAL}/chairs", params={"at": T}))["chairs"]
    n_adc = sum(1 for c in chairs if c["post_code"] == "ADC" and not c["derived"])  # MDM strength, not demo chairs
    wrong = client.post(f"/v1/offices/{NAL}/chairs", json={"post_code": "ADC", "entered_by": "ESTB@DC_NGN", "reason": "x"})
    assert wrong.status_code == 409
    new = ok(client.post(f"/v1/offices/{NAL}/chairs", json={"post_code": "ADC", "entered_by": ESTB, "reason": "Sanction order 1"}))
    assert new["sanctioned_post_id"] == f"{NAL}-ADC-{n_adc + 1:02d}" and new["is_active"] and not new["derived"]
    eid = onboard(client, "New ADC (test)", "AAAPG7777G")["employee_id"]
    ok(client.post("/v1/postings", json={"employee_id": eid, "sanctioned_post_id": new["sanctioned_post_id"],
                                         "charge_type": "SUBSTANTIVE", "effective_from": T, "order_ref": "GAD/1",
                                         "issuing_department": "Personnel Department", "entered_by": ESTB}))
    held = client.post(f"/v1/posts/{new['sanctioned_post_id']}/abolish", json={"entered_by": ESTB, "reason": "x"})
    assert held.status_code == 409 and "Relieve the holder" in held.json()["error"]["message"]
    spare = ok(client.post(f"/v1/offices/{NAL}/chairs", json={"post_code": "ASSISTANT_COMMISSIONER", "entered_by": ESTB, "reason": "Sanction 2"}))
    gone = ok(client.post(f"/v1/posts/{spare['sanctioned_post_id']}/abolish", json={"entered_by": ESTB, "reason": "Withdrawn"}))
    assert gone["is_active"] is False
    roster_ids = {c["sanctioned_post_id"] for c in ok(client.get(f"/v1/offices/{NAL}/roster"))["chairs"]}
    assert new["sanctioned_post_id"] in roster_ids and spare["sanctioned_post_id"] not in roster_ids
    kept = ok(client.get(f"/v1/offices/{NAL}/chairs", params={"include_abolished": "true"}))["chairs"]
    assert spare["sanctioned_post_id"] in {c["sanctioned_post_id"] for c in kept}


# ---------------------------------------------------------------- postings and leave

def test_list_and_correct_postings(client):
    rows = ok(client.get("/v1/postings", params={"office_id": NAL, "at": T}))["postings"]
    p = next(r for r in rows if r["sanctioned_post_id"] == f"{NAL}-ADC-01")
    fixed = ok(client.post(f"/v1/postings/{p['posting_id']}/correct",
                           json={"entered_by": ESTB, "order_ref": "GAD/E/2026/45", "note": "order received late"}))
    assert fixed["order_ref"] == "GAD/E/2026/45" and fixed["lineage_id"] == p["lineage_id"] and fixed["id"] != p["posting_id"]
    assert ok(client.get(f"/v1/posts/{NAL}-ADC-01/holder", params={"at": T}))["holders"][0]["order_ref"] == "GAD/E/2026/45"
    r = client.post(f"/v1/postings/{p['posting_id']}/correct", json={"entered_by": ESTB})
    assert r.status_code == 422


def test_cancel_leave(client):
    holder = ok(client.get(f"/v1/posts/{NAL}-ADC-01/holder", params={"at": T}))["holders"][0]
    w = ok(client.post("/v1/availability", json={"employee_id": holder["employee_id"], "kind": "LEAVE",
                                                 "from_ts": "2026-11-01", "to_ts": "2026-11-06", "entered_by": ESTB}))
    assert ok(client.get(f"/v1/posts/{NAL}-ADC-01/holder", params={"at": T}))["holders"][0]["available"] is False
    c = ok(client.post(f"/v1/availability/{w['id']}/cancel", json={"entered_by": ESTB, "reason": "leave withdrawn"}))
    assert c["from_ts"] == c["to_ts"] and c["note"].startswith("CANCELLED")
    assert ok(client.get(f"/v1/posts/{NAL}-ADC-01/holder", params={"at": T}))["holders"][0]["available"] is True
    windows = ok(client.get("/v1/availability", params={"employee_id": holder["employee_id"]}))["windows"]
    assert windows[0]["state"] == "CANCELLED"
    assert client.post(f"/v1/availability/{w['id']}/cancel", json={"entered_by": ESTB, "reason": "again"}).status_code == 422


def test_onboarding_and_audit_lists(client):
    onboard(client, "Listed Officer (test)", "AAAPH8888H")
    assert ok(client.get("/v1/onboarding"))["requests"][0]["name"] == "Listed Officer (test)"
    assert ok(client.get("/v1/audit", params={"limit": 5}))["entries"][0]["action"].startswith("ONBOARDING")


# ---------------------------------------------------------------- screens

def test_record_screens_render(client):
    for path in ("/ui/officers", "/ui/officers?q_=Kamal", "/ui/officers/new", "/ui/officers/EMP-0001",
                 f"/ui/chairs?office_id={NAL}", "/ui/audit", "/ui/audit?entity=posting"):
        r = client.get(path)
        assert r.status_code == 200 and "Asia/Kolkata" in r.text, path


def test_add_officer_screen_mints_then_blocks_duplicates(client):
    form = {"source": "MANUAL", "name": "Screen Officer (test)", "pan": "AAAPJ9999J", "submitted_by": ESTB, "is_demo": "1"}
    r = client.post("/ui/officers/new", data=form)
    assert r.status_code == 200 and "Onboarded: demo officer DEMO-" in r.text and "Screen Officer (test)" in r.text
    r2 = client.post("/ui/officers/new", data={**form, "name": "Same person again"})
    assert "Not added: this person already exists" in r2.text
    r3 = client.post("/ui/officers/new", data={**form, "pan": "", "name": "No ids"})
    assert "Rejected:" in r3.text


def test_chair_and_officer_screens_act(client):
    r = client.post("/ui/chairs/add", data={"office_id": NAL, "post_code": "ASSISTANT_COMMISSIONER", "reason": "Sanction 3", "entered_by": ESTB})
    assert "Chair AS-D-298-ASSISTANT_COMMISSIONER-03 added" in r.text
    eid = onboard(client, "Screen Posting (test)", "AAAPK1111K")["employee_id"]
    r = client.post(f"/ui/officers/{eid}/join", data={"sanctioned_post_id": f"{NAL}-ASSISTANT_COMMISSIONER-03", "charge_type": "SUBSTANTIVE",
                                                      "at": "2026-11-02T11:00", "order_ref": "GAD/2",
                                                      "issuing_department": "Personnel Department", "entered_by": ESTB})
    assert "Posted to AS-D-298-ASSISTANT_COMMISSIONER-03" in r.text
    r = client.post(f"/ui/officers/{eid}/edit", data={"name": "Screen Posting (test)", "cadre": "ACS", "submitted_by": ESTB})
    assert "Record corrected: cadre" in r.text
    r = client.post(f"/ui/officers/{eid}/allot", data={"office_id": NAL, "function_code": "NAZARAT",
                                                       "at": "2026-11-02T11:00", "entered_by": ESTB})
    assert "NAZARAT allotted in AS-D-298" in r.text
