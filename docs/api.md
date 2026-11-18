# HR Utility API — reference

Sewa Setu 2.0 HR Utility (PoC), API version **0.3.0**.

The HR Utility answers one question for the Rule Engine: **in office O, which chairs of post P are held at time t by
an officer holding function F; is that officer available; and if none is, who is the Link Officer?** Around that it
keeps the HR events: postings, function allotments, leave and tour, vacancies, onboarding, an audit log and an event
outbox.

| | |
|---|---|
| Base URL (local) | `http://127.0.0.1:8000` |
| Swagger UI (live, "Try it out") | `http://127.0.0.1:8000/docs` |
| ReDoc | `http://127.0.0.1:8000/redoc` |
| OpenAPI 3.1 | `http://127.0.0.1:8000/openapi.json`, or the files [openapi.json](openapi.json) and [openapi.yaml](openapi.yaml) |
| Offline Swagger | [swagger.html](swagger.html): the spec is embedded; open it in a browser and point "Try it out" at a running server |
| How each consumer should call it | [integration.md](integration.md) |

All examples below are real responses from the seeded data (DC Nagaon, `DC_NGN`), captured on 04-11-2026.
Long lists are cut to two items (`"... n more"`), and mobile numbers are masked.

---

## 1. Conventions

**Time.** Every read takes `?at=` (ISO-8601). A value with no offset is read as IST. A date alone means 00:00 IST that
day. Default: now. Every timestamp in a response is ISO-8601 in Asia/Kolkata (`+05:30`). Stored values are UTC.

**Intervals** are half-open, `[from, to)`. `to: null` means current. A leave window `from_ts 2026-11-10, to_ts
2026-11-15` covers 10–14 November; the officer is back at 00:00 IST on the 15th.

**Nothing is deleted (BR-10).** Relieve, withdraw, cancel and abolish write a new row and keep the old one.
Corrections do too: the response carries a new `id` with the same `lineage_id`. The database rejects DELETE, and it
rejects UPDATE of anything except the `superseded_by` link.

**Identifiers**

| Thing | Form | Example |
|---|---|---|
| Office | MDM office code | `DC_NGN`, `AS-D-298`, `AS-CR-298-07` |
| Post | MDM designation code; MDM short names are accepted as aliases | `ADC`, `CIRCLE_OFFICER` (alias `CO`), `ASSISTANT_COMMISSIONER` (alias `AC`) |
| Chair (sanctioned post) | `<office>-<designation>-NN`, from MDM's sanctioned count. Local demo-only chairs use `-DNN` | `DC_NGN-ADC-05`, `AS-D-298-ADC-D01` |
| Officer | `EMP-NNNN`, minted by MDM. Demo officers are local `DEMO-NNNN` | `EMP-0065` |
| Function | MDM function code | `ARTPS`, `SOCIAL_WELFARE` |

**Demo data.** Every officer object carries `is_demo`. Demo officers and demo chairs never reach MDM.

**MDM freshness headers.** Every response carries these:

| Header | Meaning |
|---|---|
| `X-MDM-Source` | `http://172.16.5.151:4001` (live) or `SNAPSHOT` (offline copy) |
| `X-MDM-Version` | MDM global version the local copy reflects, e.g. `39019` |
| `X-MDM-Synced-At` | when that copy was taken |
| `X-MDM-Stale` | `true` only if the last check with MDM failed; the service keeps answering from its last copy |

**Errors.** Every error has one shape: `{"error": {"rule": "BR-xx" | null, "message": "..."}}`.

| Status | When | Example |
|---|---|---|
| 404 | Unknown office, chair, officer or record | `{"error": {"rule": null, "message": "Sanctioned post NOPE-01 is not in MDM"}}` |
| 409 | A business rule refuses the write | `{"error": {"rule": "BR-01", "message": "DC_NGN-ADC-07 already has a substantive holder, ..."}}` |
| 422 | Malformed input | `{"error": {"rule": null, "message": "'at' must be an ISO-8601 date or timestamp, got 'yesterday' ..."}}` |

**Business rules referred to below**

| Rule | Meaning |
|---|---|
| BR-01 | A chair has at most one substantive holder at any instant |
| BR-02 | One officer holds at most one substantive post at a time; additional charges are separate |
| BR-03 | A chair is never left with no one in charge unless it is declared vacant with a reason |
| BR-04 | A function can be allotted only if MDM lists it for the office type and for the post |
| BR-06 | Leave, tour, training or deputation makes an officer unavailable for that window |
| BR-07 | Link Officer: when no holder is available, a covering officer per MDM's link-officer rules |
| BR-08 | History: who held a chair over an interval, with working days |
| BR-09 | Onboarding: de-duplicate on FinAssam code, PAN or Aadhaar token hash, then MDM mints the ID; the Aadhaar token is never stored |
| BR-10 | Append-only |

**Writes need `entered_by`** (or `submitted_by`). It must name the office's Establishment branch (`ESTB@<office>`)
where the rule asks for it, for example to add or abolish chairs. Authentication is out of scope for the PoC.

---

## 2. Endpoints at a glance

| Tag | Method and path | Purpose |
|---|---|---|
| Rule Engine | `GET /v1/seat-holders` | **The core question:** holders of post P with function F in office O at t, and the Link Officer if none is available |
| | `GET /v1/posts/{chair}/holder` | One chair at t: holder(s), functions, availability, vacancy |
| | `GET /v1/posts/{chair}/link-officer` | BR-07 Link Officer for one chair at t |
| | `GET /v1/posts/{chair}/history` | BR-08 holders and working days over `[from, to]` |
| IAM | `GET /v1/employees/{id}/posts` | Posts an officer holds at t (substantive, additional, link charge) |
| Workflow | `GET /v1/offices/{office}/roster` | Every chair in an office at t |
| Establishment | `POST /v1/onboarding` | BR-09 onboard a new officer (MDM mints the ID) |
| | `POST /v1/postings` | Join a chair (BR-01, BR-02) |
| | `POST /v1/postings/{id}/relieve` | Relieve (BR-03), optionally naming a successor |
| | `POST /v1/posts/{chair}/declare-vacant` | The reasoned exception to BR-03 |
| | `GET`/`POST /v1/function-allotments` | Allotments in force / allot a function (BR-04) |
| | `POST /v1/function-allotments/{id}/withdraw` | End an allotment |
| | `POST /v1/availability` | Leave, tour, training, deputation (BR-06) |
| | `GET /v1/function-catalogue` | Functions per office type; which posts hold them by allotment and which by being posted |
| Records | `GET /v1/employees`, `GET`/`PUT /v1/employees/{id}` | Search, view and correct officers |
| | `GET /v1/onboarding` | Onboarding requests |
| | `GET /v1/offices`, `GET`/`POST /v1/offices/{office}/chairs` | Offices; chairs, and adding a chair |
| | `POST /v1/posts/{chair}/abolish` | Abolish the highest-numbered empty chair |
| | `GET /v1/postings`, `POST /v1/postings/{id}/correct` | Posting records; correct an order reference |
| | `GET /v1/availability`, `POST /v1/availability/{id}/cancel` | Leave windows; cancel one |
| | `GET /v1/audit` | Append-only audit log |
| Events | `GET /v1/events?after=` | Outbox for subscribers |
| IAM stub | `POST /v1/iam/login`, `POST /v1/iam/switch`, `GET /v1/iam/sessions/{id}` | Demo-only sessions (no authentication) |
| MDM integration | `GET /hr/usage/{type}/{code}` | MDM's usage callback |
| | `GET /v1/mdm/status` | Freshness of the local MDM copy |

---

## 3. Rule Engine

### GET /v1/seat-holders — the core question

| Parameter | Required | Meaning |
|---|---|---|
| `office_id` | yes | MDM office code |
| `post_code` | yes | MDM designation code or short name |
| `function_code` | yes, unless roster mode is on | The function the application needs |
| `at` | no | Time of the question |

`status` is one of these:

- `RESOLVED`: an available holder exists, or a Link Officer was found.
- `NO_LINK_OFFICER`: no holder is available and no rule produced anyone. `reason` says why; nobody is guessed.
- `NOT_APPLICABLE`: no Link Officer rule exists for this office type and post.

`GET /v1/seat-holders?office_id=DC_NGN&post_code=ADC&function_code=SOCIAL_WELFARE&at=2026-11-04T10:00:00+05:30`

```json
{
  "office_id": "DC_NGN", "post_code": "ADC", "function_code": "SOCIAL_WELFARE",
  "at": "2026-11-04T10:00:00+05:30",
  "holders": [
    {"sanctioned_post_id": "DC_NGN-ADC-05", "employee_id": "EMP-0065", "name": "Kamal Jeet Sarma",
     "cadre": "ACS", "year_of_joining": 2019, "charge_type": "SUBSTANTIVE",
     "available": true, "unavailable_reason": null, "is_demo": false}
  ],
  "link_officer": null, "status": "RESOLVED", "reason": null, "roster_mode": false
}
```

On 12-11-2026 the same officer is on leave, so the Link Officer is resolved. In a DC office this is an ADC or AC who
holds ARTPS; ties go to the senior officer.

`GET /v1/seat-holders?office_id=DC_NGN&post_code=ADC&function_code=SOCIAL_WELFARE&at=2026-11-12`

```json
{
  "office_id": "DC_NGN", "post_code": "ADC", "function_code": "SOCIAL_WELFARE",
  "at": "2026-11-12T00:00:00+05:30",
  "holders": [
    {"sanctioned_post_id": "DC_NGN-ADC-05", "employee_id": "EMP-0065", "name": "Kamal Jeet Sarma",
     "cadre": "ACS", "year_of_joining": 2019, "charge_type": "SUBSTANTIVE",
     "available": false, "unavailable_reason": "LEAVE", "is_demo": false}
  ],
  "link_officer": {"employee_id": "EMP-0071", "name": "Sikha Nath",
                   "sanctioned_post_id": "DC_NGN-ASSISTANT_COMMISSIONER-06",
                   "rule_step": "ARTPS_HOLDER", "deemed_dps_under_rule_3_3": true, "is_demo": false},
  "status": "RESOLVED", "reason": null, "roster_mode": false
}
```

`rule_step` names the Link Officer rule that matched:

| `rule_step` | Who covers |
|---|---|
| `ARTPS_HOLDER` | An ADC or AC who holds ARTPS, in a DC or co-district office |
| `SAME_POST` | Another holder of the same post in the office |
| a designation code, e.g. `SUB_REGISTRAR` | That designation, e.g. a circle with a single CO |

`deemed_dps_under_rule_3_3` is the field name fixed by the frozen API contract. The HR Utility does not assign
roles; the Rule Engine decides what the flag means.

### GET /v1/posts/{sanctioned_post_id}/holder

`GET /v1/posts/DC_NGN-ADC-05/holder?at=2026-11-04T10:00:00+05:30`

```json
{
  "sanctioned_post_id": "DC_NGN-ADC-05", "office_id": "DC_NGN", "post_code": "ADC", "rank_order": 20,
  "derived": false, "at": "2026-11-04T10:00:00+05:30", "status": "HELD",
  "holders": [
    {"employee_id": "EMP-0065", "name": "Kamal Jeet Sarma", "cadre": "ACS", "year_of_joining": 2019,
     "is_demo": false, "posting_id": 106, "charge_type": "SUBSTANTIVE",
     "since": "2026-03-13T00:00:00+05:30", "until": null,
     "order_ref": "SEED-SNAPSHOT (not an order): Officers_Workallotment_13_03_26.pdf Sl 8",
     "issuing_department": "Personnel Department",
     "available": true, "unavailable_reason": null, "unavailable_until": null,
     "functions": ["ARTPS", "HEALTH_FW", "... 3 more"],
     "functions_allotted": ["ARTPS", "HEALTH_FW", "... 3 more"],
     "holds_all_office_functions": false}
  ],
  "vacancy": null, "link_officer": null, "link_status": null, "link_reason": null
}
```

`holds_all_office_functions` is true for posts MDM marks `holdsAllFunctions` (DC, Circle Officer). Such an officer
holds every function of the office by being posted there; nothing is allotted to them.

### GET /v1/posts/{sanctioned_post_id}/link-officer

`GET /v1/posts/DC_NGN-ADC-05/link-officer?at=2026-11-12`

```json
{
  "sanctioned_post_id": "DC_NGN-ADC-05", "at": "2026-11-12T00:00:00+05:30", "status": "RESOLVED",
  "link_officer": {"employee_id": "EMP-0071", "name": "Sikha Nath",
                   "sanctioned_post_id": "DC_NGN-ASSISTANT_COMMISSIONER-06",
                   "rule_step": "ARTPS_HOLDER", "deemed_dps_under_rule_3_3": true, "is_demo": false},
  "reason": null,
  "absent_holders": [{"employee_id": "EMP-0065", "name": "Kamal Jeet Sarma", "cadre": "ACS",
                      "year_of_joining": 2019, "is_demo": false, "unavailable_reason": "LEAVE"}]
}
```

### GET /v1/posts/{sanctioned_post_id}/history — BR-08

`from` and `to` are dates or timestamps. A date in `to` is inclusive, up to 24:00 IST that day. Working days
exclude:

- Sundays;
- MDM's state-wide holidays;
- MDM's LOCAL holidays for the office's district.

RESTRICTED holidays are working days. A handover day counts for the incoming holder.

`GET /v1/posts/DC_NGN-ADC-05/history?from=2026-03-13&to=2026-03-31`

```json
{
  "sanctioned_post_id": "DC_NGN-ADC-05", "office_id": "DC_NGN", "post_code": "ADC",
  "from": "2026-03-13T00:00:00+05:30", "to": "2026-04-01T00:00:00+05:30",
  "holders": [
    {"employee_id": "EMP-0065", "name": "Kamal Jeet Sarma", "cadre": "ACS", "year_of_joining": 2019,
     "is_demo": false, "charge_type": "SUBSTANTIVE",
     "intervals": [{"from": "2026-03-13T00:00:00+05:30", "to": "2026-04-01T00:00:00+05:30"}],
     "working_days": 15}
  ],
  "unheld_intervals": [], "working_days_in_interval": 15,
  "working_day_rule": "Sundays and MDM holidays (state-wide, plus local ones for this district; restricted holidays are working days) excluded; IST calendar days; a handover day counts for the incoming holder.",
  "holidays_in_interval": ["2026-03-20"]
}
```

---

## 4. IAM and Workflow reads

### GET /v1/employees/{employee_id}/posts

These are the posts IAM should offer the officer to act as. Link charges appear with `rule_step` and `covering_for`.

`GET /v1/employees/EMP-0065/posts?at=2026-11-04T10:00:00+05:30`

```json
{
  "employee_id": "EMP-0065", "name": "Kamal Jeet Sarma", "cadre": "ACS", "year_of_joining": 2019,
  "is_demo": false, "at": "2026-11-04T10:00:00+05:30", "available": true, "unavailable_reason": null,
  "posts": [
    {"sanctioned_post_id": "DC_NGN-ADC-05", "office_id": "DC_NGN", "post_code": "ADC",
     "charge_type": "SUBSTANTIVE", "posting_id": 106, "since": "2026-03-13T00:00:00+05:30", "until": null,
     "rule_step": null, "deemed_dps_under_rule_3_3": null, "covering_for": null}
  ]
}
```

### GET /v1/offices/{office_id}/roster

This returns the office header plus every chair, in the same shape as `/posts/{chair}/holder`. Chairs follow MDM's
display order.

`GET /v1/offices/DC_NGN/roster?at=2026-11-04T10:00:00+05:30` (18 chairs; first shown)

```json
{
  "office_id": "DC_NGN", "name": "Office of the District Commissioner, Nagaon", "office_type": "DC_OFFICE",
  "district_code": "NGN", "district_name": "Nagaon", "parent_office_id": "DIVCOM_CA", "provisional_id": false,
  "external_ref": null, "establishment_actor": "ESTB@DC_NGN", "at": "2026-11-04T10:00:00+05:30",
  "chairs": [
    {"sanctioned_post_id": "DC_NGN-DISTRICT_COMMISSIONER-01", "post_code": "DISTRICT_COMMISSIONER",
     "status": "HELD",
     "holders": [{"employee_id": "EMP-0010", "name": "Devasish Sharma", "cadre": "IAS", "charge_type": "SUBSTANTIVE",
                  "functions": ["AADHAAR", "... 49 more"], "functions_allotted": [],
                  "holds_all_office_functions": true, "available": true}],
     "vacancy": null},
    "... 17 more"
  ]
}
```

(Some chair fields are left out above; they match `/posts/{chair}/holder`.)

---

## 5. Establishment writes

All writes return 200 with the row written. A refusal returns 409 with the rule number.

### POST /v1/onboarding — BR-09

At least one identifier is needed for de-duplication: `finassam_code`, `pan`, or `aadhaar_token`. The Aadhaar token
is only hashed with a salt; it is never stored or sent.

Steps:

1. The HR Utility checks earlier requests for the same FinAssam code, PAN or Aadhaar hash.
2. If none matches, MDM mints the `EMP-NNNN` ID. MDM reports a mobile or email it already holds as a duplicate.
3. With `is_demo: true`, the officer gets a local `DEMO-NNNN` and **nothing is sent to MDM**. The Swagger example
   uses this, so "Try it out" never writes to the shared MDM.

```json
POST /v1/onboarding
{"source": "MANUAL", "name": "Rupjyoti Bora", "gender": "MALE", "cadre": "ACS", "year_of_joining": 2024,
 "date_of_joining": "2024-07-01", "mobile": "9435011223", "email": "rupjyoti.bora@example.in",
 "pan": "ABCPB1234K", "submitted_by": "ESTB@DC_NGN", "is_demo": false}

200 {"request_id": 1, "status": "MINTED", "employee_id": "EMP-0091", "reason": null, "is_demo": false}
```

The same PAN sent again is not minted twice:

```json
200 {"request_id": 2, "status": "DUPLICATE", "employee_id": "EMP-0091",
     "reason": "matched an earlier onboarding on PAN", "is_demo": false}
```

`status` is one of `MINTED`, `DUPLICATE` (with the existing `employee_id`) or `REJECTED` (with `reason`). Every
request is kept: see `GET /v1/onboarding`.

### POST /v1/postings — join (BR-01, BR-02)

`charge_type` is `SUBSTANTIVE` or `ADDITIONAL`. `order_ref` and `issuing_department` are required. Before saving, the
office, the designation and the officer are checked with MDM (`POST /mdm/validate`); demo officers are not sent.

```json
POST /v1/postings
{"employee_id": "EMP-0091", "sanctioned_post_id": "DC_NGN-ADC-07", "charge_type": "SUBSTANTIVE",
 "effective_from": "2026-11-04T10:00:00+05:30", "order_ref": "PERS/E/2026/112",
 "issuing_department": "Personnel Department", "entered_by": "ESTB@DC_NGN"}

200 {"id": 129, "lineage_id": 129, "employee_id": "EMP-0091", "is_demo": false,
     "sanctioned_post_id": "DC_NGN-ADC-07", "charge_type": "SUBSTANTIVE",
     "effective_from": "2026-11-04T10:00:00+05:30", "effective_to": null,
     "order_ref": "PERS/E/2026/112", "issuing_department": "Personnel Department",
     "entered_by": "ESTB@DC_NGN", "note": null}
```

A second substantive holder is refused:

```json
409 {"error": {"rule": "BR-01", "message": "DC_NGN-ADC-07 already has a substantive holder, Rupjyoti Bora, for 04-11-2026 10:00 IST to open. A post has at most one substantive holder at any instant: relieve Rupjyoti Bora first, or post Jitu Kumar Barman on additional charge."}}
```

### POST /v1/postings/{posting_id}/relieve — BR-03

Relieving the only person in charge is refused. Name a `successor` who joins at the same instant, start an additional
charge at that instant, or declare the post vacant.

```json
POST /v1/postings/130/relieve
{"at": "2026-12-01T10:00:00+05:30", "entered_by": "ESTB@DC_NGN"}

409 {"error": {"rule": "BR-03", "message": "Cannot relieve Rupjyoti Bora from DC_NGN-ADC-07 at 01-12-2026 10:00 IST: the post would be left with no one in charge. Name a successor who joins at the same time, start an additional charge on this post at the same time, or declare the post vacant with a reason."}}
```

```json
POST /v1/postings/130/relieve
{"at": "2026-12-01T10:00:00+05:30", "entered_by": "ESTB@DC_NGN",
 "successor": {"employee_id": "EMP-0062", "charge_type": "ADDITIONAL",
               "order_ref": "PERS/E/2026/140", "issuing_department": "Personnel Department"}}

200 {"ended":     {"id": 131, "lineage_id": 129, "employee_id": "EMP-0091", "charge_type": "SUBSTANTIVE",
                   "effective_from": "2026-11-04T10:00:00+05:30", "effective_to": "2026-12-01T10:00:00+05:30", "...": "..."},
     "successor": {"id": 132, "lineage_id": 132, "employee_id": "EMP-0062", "charge_type": "ADDITIONAL",
                   "effective_from": "2026-12-01T10:00:00+05:30", "effective_to": null, "...": "..."}}
```

Use the **current** version's id. After a correction (below), the posting's id changes and `lineage_id` stays.

### POST /v1/posts/{sanctioned_post_id}/declare-vacant

This is the only way to leave a chair with no one in charge. It needs a reason. A substantive posting running at
`at` is ended, and its posting record is returned in `ended`.

```json
POST /v1/posts/DC_NGN-SETTLEMENT_OFFICER-01/declare-vacant
{"at": "2026-11-04T10:00:00+05:30", "reason": "Officer retired; no posting order yet", "entered_by": "ESTB@DC_NGN"}

200 {"vacancy_id": 1, "sanctioned_post_id": "DC_NGN-SETTLEMENT_OFFICER-01",
     "since": "2026-11-04T10:00:00+05:30", "until": null,
     "reason": "Officer retired; no posting order yet", "entered_by": "ESTB@DC_NGN", "ended": []}
```

The vacancy closes when the next substantive holder joins.

### POST /v1/function-allotments — BR-04; withdraw

The function must be in MDM's list for the office type (office-type-function) and for the post
(designation-function). Posts that hold all office functions cannot be allotted functions.

```json
POST /v1/function-allotments
{"employee_id": "EMP-0091", "office_id": "DC_NGN", "function_code": "SOCIAL_WELFARE",
 "effective_from": "2026-11-04T10:00:00+05:30", "entered_by": "ESTB@DC_NGN"}

200 {"id": 202, "lineage_id": 202, "employee_id": "EMP-0091", "is_demo": false, "office_id": "DC_NGN",
     "function_code": "SOCIAL_WELFARE", "effective_from": "2026-11-04T10:00:00+05:30", "effective_to": null,
     "entered_by": "ESTB@DC_NGN"}
```

```json
409 {"error": {"rule": "BR-04", "message": "Function code 'NO_SUCH_FN' does not exist in the MDM code list."}}
```

```json
POST /v1/function-allotments/202/withdraw
{"at": "2026-11-20T00:00:00+05:30", "entered_by": "ESTB@DC_NGN"}

200 {"id": 203, "lineage_id": 202, "function_code": "SOCIAL_WELFARE",
     "effective_from": "2026-11-04T10:00:00+05:30", "effective_to": "2026-11-20T00:00:00+05:30", "...": "..."}
```

`GET /v1/function-allotments?office_id=DC_NGN&employee_id=EMP-0065` lists the allotments in force at `at`.

### POST /v1/availability — BR-06

`kind` is one of `LEAVE`, `TOUR`, `TRAINING`, `DEPUTATION`.

```json
POST /v1/availability
{"employee_id": "EMP-0065", "kind": "LEAVE", "from_ts": "2026-11-10", "to_ts": "2026-11-15",
 "entered_by": "ESTB@DC_NGN", "note": "earned leave"}

200 {"id": 1, "lineage_id": 1, "employee_id": "EMP-0065", "is_demo": false, "kind": "LEAVE",
     "from_ts": "2026-11-10T00:00:00+05:30", "to_ts": "2026-11-15T00:00:00+05:30",
     "entered_by": "ESTB@DC_NGN", "note": "earned leave"}
```

Cancel with `POST /v1/availability/{id}/cancel` `{"entered_by": "...", "reason": "..."}`. The window collapses to
nothing, and both rows are kept.

### GET /v1/function-catalogue

This shows the functions of each office type (from MDM) and how each post holds them. `mode` is `ALLOTTED` or
`ALL_OFFICE_FUNCTIONS`, from MDM `designation.holdsAllFunctions`.

```json
{"office_types": [{"office_type": "DC_OFFICE", "functions": [
    {"function_code": "AADHAAR", "name": "Nodal Officer AADHAAR", "category": "MDM", "is_demo": false}, "... 49 more"]}],
 "post_rules": [
    {"post_code": "DISTRICT_COMMISSIONER", "post_name": "District Commissioner", "rank_order": 10,
     "mode": "ALL_OFFICE_FUNCTIONS", "is_demo": false, "basis": "MDM designation.holdsAllFunctions"},
    {"post_code": "ADC", "post_name": "Additional District Commissioner", "rank_order": 20,
     "mode": "ALLOTTED", "is_demo": false, "basis": "MDM designation.holdsAllFunctions"}, "... 35 more"]}
```

---

## 6. Records (the Establishment branch's screens use these)

| Call | Notes |
|---|---|
| `GET /v1/employees?q=Kamal&office_id=&include_demo=true` | Search by name, ID, email or mobile. Each result lists the posts held at `at` and availability |
| `GET /v1/employees/EMP-0065` | Record + postings + function allotments + leave windows + onboarding request. Identifiers appear only as `has_aadhaar_hash` |
| `PUT /v1/employees/EMP-0065` | Correct name, gender, cadre, date of joining, email, mobile (sent to MDM), or year of joining, DOB, retirement (kept by the HR Utility). Identifiers cannot be changed here |
| `GET /v1/onboarding?limit=200` | Every onboarding request, newest first, with its outcome |
| `GET /v1/offices?office_type=DC_OFFICE&district_code=NGN` | MDM offices in scope, plus the local ones (`provisional: true`) |
| `GET /v1/offices/DC_NGN/chairs?include_abolished=false` | Chairs with their holders at `at` |
| `POST /v1/offices/DC_NGN/chairs` | **Raises MDM's sanctioned count** for office × post by one. Only `ESTB@<office>` may do this |
| `POST /v1/posts/{chair}/abolish` | Lowers MDM's count. Only the highest-numbered chair, and only if it is empty; the record is kept |
| `GET /v1/postings?office_id=&employee_id=&sanctioned_post_id=&include_ended=true` | `state` is `CURRENT`, `FUTURE` or `ENDED` |
| `POST /v1/postings/{id}/correct` | Order reference, issuing department or note. Returns the new version |
| `GET /v1/availability?office_id=&employee_id=` | Leave windows; `state` is `CURRENT`, `FUTURE` or `ENDED` |
| `GET /v1/audit?entity=posting&entity_id=&actor=&limit=` | Every write, with `before_json` and `after_json` |

```json
PUT /v1/employees/EMP-0065
{"submitted_by": "ESTB@DC_NGN", "email": "kamal.sarma@assam.gov.in"}

200 {"employee_id": "EMP-0065", "name": "Kamal Jeet Sarma", "cadre": "ACS", "year_of_joining": 2019,
     "is_demo": false, "email": "kamal.sarma@assam.gov.in", "mobile": "80999XXXXX"}
```

```json
POST /v1/offices/DC_NGN/chairs
{"post_code": "ADC", "entered_by": "ESTB@DC_NGN", "reason": "GAD sanction order 45/2026"}

200 {"sanctioned_post_id": "DC_NGN-ADC-07", "office_id": "DC_NGN", "post_code": "ADC", "seq": 7, "derived": false,
     "is_demo": false, "is_active": true, "source": "MDM sanctioned-post DC_NGN:ADC (7)"}
```

```json
POST /v1/posts/DC_NGN-DEALING_ASSISTANT-02/abolish
{"entered_by": "ESTB@DC_NGN", "reason": "Post surrendered"}

200 {"sanctioned_post_id": "DC_NGN-DEALING_ASSISTANT-02", "is_active": false,
     "source": "MDM sanctioned-post DC_NGN:DEALING_ASSISTANT (2); abolished by ESTB@DC_NGN on 04-11-2026 10:56 IST: Post surrendered", "...": "..."}
```

---

## 7. Events

`GET /v1/events?after=<last id seen>&limit=500` returns outbox events in id order. Store the last `id` and poll
from it. Act on an event only when `effective_at <= now`: a posting entered today can take effect next week.

| Type | Raised when |
|---|---|
| `posting.started` / `posting.ended` | A substantive posting starts or ends (relieve, declare vacant) |
| `charge.started` / `charge.ended` | An additional charge starts or ends |
| `function.allotted` / `function.withdrawn` | A function allotment starts or ends |
| `availability.started` / `availability.ended` | A leave, tour, training or deputation window starts or ends (`effective_at` = the window's edges; a cancellation moves the end) |
| `employee.onboarded` | An onboarding request was minted |

```json
{"events": [
  {"id": 3, "ts": "2026-11-04T10:57:23.987551+05:30", "type": "posting.started",
   "effective_at": "2026-03-13T00:00:00+05:30",
   "payload": {"posting_id": 3, "lineage_id": 3, "employee_id": "EMP-0031",
               "sanctioned_post_id": "AS-CR-285-01-CIRCLE_OFFICER-01", "office_id": "AS-CR-285-01",
               "post_code": "CIRCLE_OFFICER", "charge_type": "SUBSTANTIVE",
               "order_ref": "SEED-SNAPSHOT (not an order): List_of_DCs.xlsx COs!row5.1",
               "issuing_department": "Revenue & Disaster Management Department",
               "effective_at": "2026-03-13T00:00:00+05:30", "is_demo": false},
   "delivered": true}
]}
```

---

## 8. IAM stub (demo only, no authentication)

| Call | Body | Result |
|---|---|---|
| `POST /v1/iam/login` | `{"employee_id": "EMP-0065"}` | A session listing the posts held now; `active_post_id` is the substantive post |
| `POST /v1/iam/switch` | `{"sanctioned_post_id": "DC_NGN-ADC-05", "session_id": "..."}` (or header `X-Stub-Session`) | Sets the active post; refused if the officer does not hold it |
| `GET /v1/iam/sessions/{id}?at=` | — | Re-checks the session at `at` (default now). Once the active post is no longer held, `revoked: true` and `revoke_reason` names the event. That happens after `posting.ended` or `charge.ended`, or after `availability.ended` for a link charge, because the covered officer is back |

```json
{"stub": true, "notice": "IAM STUB: no authentication is performed. Do not use outside the PoC.",
 "session_id": "34b1b10d-8c70-4f28-8a2e-8a8d382698df", "employee_id": "EMP-0065", "is_demo": false,
 "at": "2026-11-04T10:57:25.580922+05:30", "active_post_id": "DC_NGN-ADC-05",
 "revoked": false, "revoked_at": null, "revoke_reason": null,
 "posts": [{"sanctioned_post_id": "DC_NGN-ADC-05", "office_id": "DC_NGN", "post_code": "ADC",
            "charge_type": "SUBSTANTIVE", "posting_id": 106, "since": "2026-03-13T00:00:00+05:30", "until": null,
            "rule_step": null, "deemed_dps_under_rule_3_3": null, "covering_for": null}]}
```

---

## 9. MDM integration

### GET /hr/usage/{entity_type}/{code}

MDM calls this before it deactivates a record. The response shape is the one MDM `integration.md` requires.
`inUse` is true while officers are posted under the record or functions are allotted under it. Supported types:
`office`, `district`, `designation`, `sanctioned-post`, `employee`, `function`, `cadre`, `holiday` (never in use).

```json
GET /hr/usage/office/DC_NGN
200 {"inUse": true, "details": {"chairs": 19, "current_postings": 16, "current_allotments": 71}}

GET /hr/usage/holiday/ANY
200 {"inUse": false, "details": {"note": "holidays are read for working-day counts only"}}
```

### GET /v1/mdm/status

```json
{"mode": "LIVE", "base_url": "http://172.16.5.151:4001", "source": "http://172.16.5.151:4001",
 "applied_version": 39019, "entity_versions": {"office": 38716, "employee": 39008, "...": "..."},
 "last_checked_at": "...", "last_synced_at": "...", "last_error": null,
 "last_check": {"status": "FRESH", "version": 39019}, "consumer_code": "hr-utility-poc",
 "copied_from_mdm": ["department", "cadre", "district", "office-type", "function", "office-type-function",
                     "designation", "office", "sanctioned-post", "designation-function", "link-officer-rule",
                     "employee", "holiday"],
 "local_until_mdm_has_them": ["demo officers and demo-only chairs", "ACMR-00ASM (Registrar office)",
                              "batch year, DOB, retirement date, demo flag", "Link Officer ARTPS condition",
                              "FinAssam / PAN / Aadhaar-hash de-duplication"]}
```

`last_check.status` takes one of four values:

- `FRESH`: MDM has not moved.
- `REFRESHED`: the version moved and the local copy was reloaded.
- `STALE`: MDM is unreachable, so the service keeps serving the last copy.
- `LOCAL_ONLY`: offline mode.

Offline (`run.py --offline`, or tests), `mode` is `OFFLINE_SEED` and `source` is `SNAPSHOT`.

---

## 10. Trying it in Swagger

1. Start the server: `python run.py` (live MDM) or `python run.py --offline` (no MDM contact).
2. Open `http://127.0.0.1:8000/docs`. Every endpoint is pre-filled with an example that works on the seed. Run the
   Establishment examples in this order: onboarding → postings → postings/{id}/correct → relieve →
   function-allotments → withdraw → availability → cancel.
3. **On the live server, some examples write to the shared MDM:**
   - adding or abolishing a chair changes MDM's sanctioned count;
   - `PUT /v1/employees/{id}` changes MDM's employee record;
   - onboarding with `is_demo: false` mints a real Employee ID.

   Use `--offline` for experiments.
4. To publish the documents again after an API change: `python run.py --export-openapi docs --no-serve` (add
   `--public-url http://<host>:8000` to list that server too). `tests/test_api_docs.py` fails while `docs/` is out
   of date.
