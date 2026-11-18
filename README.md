# Sewa Setu 2.0 — HR Utility (PoC)

Answers one question for the Rule Engine, as of any timestamp:

> In office **O**, which sanctioned posts of post **P** are held by an officer holding function **F**,
> is that officer available, and if none is, who is the **Link Officer** under ARTPS rule 3(1)?

It also ships a thin **IAM stub**, which has no authentication. The HR Utility never stores or names ARTPS roles.

## One-command run

```powershell
python run.py
```

The command builds the seed from `./data` if it is missing, creates `hr_utility.db`, and serves:

* Screens: http://127.0.0.1:8000/
* Swagger UI (try every endpoint, pre-filled examples): http://127.0.0.1:8000/docs, and ReDoc at `/redoc`
* Contract: http://127.0.0.1:8000/openapi.json

## API documentation

| Document | For |
|---|---|
| [docs/api.md](docs/api.md) | Endpoint reference: conventions, errors, every call with a real request and response |
| [docs/integration.md](docs/integration.md) | Rule Engine, IAM, Workflow and MDM teams: what to call, when, and what to rely on |
| [docs/openapi.json](docs/openapi.json), [docs/openapi.yaml](docs/openapi.yaml) | OpenAPI 3.1 contract (import into Postman, code generators) |
| [docs/swagger.html](docs/swagger.html) | Swagger UI with the contract embedded; opens from disk and calls a running server |

Regenerate after an API change with `python run.py --export-openapi docs --no-serve`; `tests/test_api_docs.py` fails
while `docs/` is out of date. On the live server some Swagger examples write to the shared MDM (chairs, employee
corrections, non-demo onboarding); use `python run.py --offline` to experiment.

Other commands:

* `python run.py --reset` rebuilds everything from `./data`.
* `python run.py --pull-mdm` saves a fresh snapshot from the MDM PoC into `data/mdm_snapshot/`, then rebuilds.
* `python run.py --offline` runs without contacting MDM (the seed snapshot only).
* `python -m pytest` runs the tests (offline; they never call MDM).
* First-time setup: `python -m pip install -r requirements.txt`.

On this machine Python is at `%LOCALAPPDATA%\Programs\Python\Python312\python.exe`. Open a new terminal if `python` is not found.

See [CLAUDE.md](CLAUDE.md) for the stack, folder layout, conventions and **open items**.

## Managing records (screens)

| Screen | What you can do |
|---|---|
| **Officers** `/ui/officers` | Search; **Add officer** (submitted to MDM, which blocks duplicates; a demo officer gets a local DEMO-NNNN instead); open an officer to correct the record, post to a chair, relieve, correct posting paperwork, allot or withdraw functions, record or cancel leave, and see their audit trail |
| **Chairs** `/ui/chairs` | See an office's chairs and holders; **add a chair** (Establishment branch, with a reason); **abolish** an empty chair |
| Office roster, Seat lookup, Function allotment, Functions by post, Posting & relieving, Leave entry, Post history | As before |
| **Audit** `/ui/audit` | Every change, filterable by record type, record ID and actor |

Nothing is ever deleted (BR-10). "Delete" means relieve, withdraw, cancel or abolish, and the earlier row is kept.
Officer records and chairs belong to MDM: **Add officer** mints the Employee ID in MDM, a record correction is sent
to MDM, and adding or abolishing a chair changes MDM's sanctioned count (only the highest-numbered chair can be
abolished, because MDM holds strength as a count).

## Seed summary

The roster was built from `List_of_DCs.xlsx`, the Nagaon work-allotment order of 13-03-2026, and the IAS and ACS
gradation lists of August 2026 (`Sewa_Setu_PoC_Linked_Masters.xlsx` as a cross-check). On 03-11-2026 it was
**loaded into the MDM PoC** (84 officers minted, chair counts, functions, Link Officer rules; see
[data/mdm_load/ledger.json](data/mdm_load/ledger.json)), and the HR Utility now reads all masters back from MDM.
Every judgement is listed in [data/load_report.md](data/load_report.md).

| Item | Count |
|---|---|
| Offices | **75** in the five PoC districts from MDM (DC, co-district, circle, agriculture, veterinary, sub-registrar … offices), plus ACMR-00ASM held locally |
| Chairs | **283**: MDM's sanctioned strength expanded to numbered chairs (273), plus 10 local demo-only chairs; 128 are held, the rest are vacant |
| Officers | **128** on the roster: 84 real with MDM Employee IDs (EMP-NNNN), 44 demo held locally (DEMO-NNNN) |
| Function allotments | **201**: 70 real (Nagaon order), 131 demo (e-District holders and demo bundles outside Nagaon) |
| Function codes | **63** in MDM (MDM's 16 plus ours) |
| Holidays | 31 from MDM; working days exclude state-wide holidays and the district's own local holidays, not restricted ones |

**Functions by post** come from MDM: `designation.holdsAllFunctions` (ADC, AC and Lot Mondol are allotted; CO,
CDC, DC and the rest hold every function of their office), office-type functions and designation functions.
Outside Nagaon, real ADCs and ACs carry demo bundles patterned on the Nagaon order
(`data/config/demo_function_bundles.csv`). See the **Functions by post** screen and `GET /v1/function-catalogue`.

The 44 demo officers are:

* 31 demo Sub Registrars, one in each circle office with a CO; the Sub Registrar is the Link Officer for a lone CO.
* 8 demo ADCs, so that every PoC DC office has holders of SOCIAL_WELFARE, E_GOVERNANCE and ARTPS.
* 3 for the department offices, where no names were supplied.
* 2 that fill chairs left by officers listed in two places (Gauripur CO and Rupahi CO).

Demo officers and demo-only chairs are never sent to MDM.

## Test results

`python -m pytest`: **111 passed**, offline: a saved MDM snapshot stands in for MDM, and a mock MDM tests the live adapter.

**Link Officer rules (business decision, 03-11-2026)** replace the rule 3(1) rank ladder. They come from MDM
(`link-officer-rule`, by priority) plus one local condition MDM cannot express yet
(`data/config/link_officer_local.csv`): in DC and co-district offices the covering ADC/AC must hold ARTPS, senior-most if
several (`ARTPS_HOLDER`). Circle office: the other CO where there are two (`SAME_POST`), else the Sub Registrar
(`SUB_REGISTRAR`). A post with no rule returns `NOT_APPLICABLE`. Spec tests H3 and H4 were rewritten to these rules. The acceptance tests (H1–H15) run through the HTTP API against the real seed.

| ID | Scenario | Result |
|---|---|---|
| H1 | Seat lookup, Nalbari DC office, ADC + SOCIAL_WELFARE | PASS |
| H2 | Two ADCs hold SOCIAL_WELFARE: senior-most first | PASS |
| H3 | Sole holder on leave: Link Officer is the ARTPS holder, `ARTPS_HOLDER` (was `EQUAL_RANK_ARTPS`) | PASS |
| H4 | No ADC holding ARTPS present: the AC holding ARTPS, `ARTPS_HOLDER` (was senior-most AC, `NEXT_LOWER_RANK`) | PASS |
| H5 | Nobody present: `NO_LINK_OFFICER` with reason | PASS |
| H6 | Function moved effective day 10: day 9 returns A, day 10 returns B | PASS |
| H7 | Relieve a CO with no successor: rejected (BR-03) | PASS |
| H8 | Relieve with a successor at the same instant: holders before and after are right; events emitted | PASS |
| H9 | Second substantive holder: rejected (BR-01) | PASS |
| H10 | Substantive A + additional B: posts, IAM login, switch; revocation on `charge.ended` and `availability.ended` | PASS |
| H11 | History across a mid-month transfer: exact sub-intervals, working days 12 / 14 | PASS |
| H12 | Same FinAssam code twice: `DUPLICATE`, same Employee ID | PASS |
| H13 | Allot to an officer not posted in the office: rejected (BR-04) | PASS |
| H14 | Co-district with no officer: `NO_HOLDER`, no fallback to the DC office | PASS |
| H15 | No API response, OpenAPI field, table or column named or valued DPS / FAA / SAA | PASS |

Other suites:

* BR-01 to BR-10 unit tests (`tests/test_rules.py`), seed (`test_seed.py`), screens (`test_screens.py`),
  functions by post (`test_functions_by_post.py`), records (`test_crud.py`), and MDM integration
  (`test_mdm_integration.py`: mint, duplicate mobile, demo officers never reach MDM, version check, outage,
  validate, usage callback), and the published contract (`test_api_docs.py`: every operation typed, tagged and
  summarised; every body example succeeds against the seed; `docs/` matches the app).

H11 counts December 2026 working days; MDM's calendar has Christmas (25-12-2026) as a gazetted holiday.

## Frozen API contract

Every read accepts `?at=` (ISO-8601). Naive values are IST, a date-only value means 00:00 IST, and the default is now.
Timestamps come back in Asia/Kolkata (`+05:30`). Every object that names an officer carries `is_demo`.
Rule refusals return **409** `{"error": {"rule": "BR-xx", "message": "..."}}`; bad input returns **422**; an unknown ID returns **404**.

### Read (Rule Engine, IAM, Workflow)

```
GET /v1/seat-holders?office_id=AS-D-298&post_code=ADC&function_code=SOCIAL_WELFARE&at=...
  → { "office_id", "post_code", "function_code", "at",
      "holders": [ { "sanctioned_post_id", "employee_id", "name", "cadre", "year_of_joining",
                     "charge_type", "available", "unavailable_reason", "is_demo" } ],   // seniority order
      "link_officer": null | { "employee_id", "name", "sanctioned_post_id", "rule_step",
                               "deemed_dps_under_rule_3_3": true, "is_demo" },          // only when no holder is available
      "status": "RESOLVED" | "NO_HOLDER" | "NO_LINK_OFFICER", "reason": null | "...", "roster_mode": false }

GET /v1/posts/{sanctioned_post_id}/holder?at=...        status HELD | DECLARED_VACANT | UNHELD, holders, vacancy, link_officer
GET /v1/posts/{sanctioned_post_id}/history?from=...&to=...   holders, exact intervals, working_days (BR-08)
GET /v1/posts/{sanctioned_post_id}/link-officer?at=...  status RESOLVED | NOT_REQUIRED | NO_LINK_OFFICER | NOT_APPLICABLE (BR-07)
GET /v1/employees/{employee_id}/posts?at=...            SUBSTANTIVE, ADDITIONAL and LINK charges (used by IAM)
GET /v1/offices/{office_id}/roster?at=...               every chair, holders, functions, availability, Link Officer
GET /v1/function-allotments?office_id=...&at=...        allotments in force (added for the allotment grid)
GET /v1/function-catalogue?office_type=...              functions of each office type; ALLOTTED vs ALL_OFFICE_FUNCTIONS per post
GET /v1/mdm/status                                      freshness of the MDM copy
GET /v1/employees?q=&office_id=        GET /v1/employees/{id}        PUT /v1/employees/{id}   (correction, via MDM)
GET /v1/offices          GET /v1/offices/{id}/chairs          POST /v1/offices/{id}/chairs   POST /v1/posts/{id}/abolish
GET /v1/postings?office_id=&employee_id=&sanctioned_post_id=   POST /v1/postings/{id}/correct
GET /v1/availability?office_id=&employee_id=                   POST /v1/availability/{id}/cancel
GET /v1/onboarding       GET /v1/audit?entity=&entity_id=&actor=
GET /hr/usage/{entityType}/{code}                       MDM usage callback
GET /v1/events?after=<id>                               outbox events with effective_at
```

`rule_step` names the Link Officer rule that applied: `ARTPS_HOLDER` (a covering post with the ARTPS condition),
`SAME_POST` (another holder of the same post), or the covering designation code (e.g. `SUB_REGISTRAR`). It was
`EQUAL_RANK_ARTPS` / `EQUAL_RANK` / `NEXT_LOWER_RANK` before 03-11-2026.
`post_code` takes an MDM designation code (`ADC`, `CIRCLE_OFFICER`, …) or its MDM short name (`AC`, `CO`, `DC`);
responses always give the designation code.
`unavailable_reason` is one of `LEAVE`, `TOUR`, `TRAINING`, `DEPUTATION` or `NOT_POSTED`.

### Write (Establishment-branch screens)

```
POST /v1/onboarding                                  → { request_id, status: MINTED|DUPLICATE|REJECTED, employee_id, reason, is_demo }
POST /v1/postings                                    join, substantive or additional (BR-01, BR-02); order_ref + issuing_department required
POST /v1/postings/{id}/relieve                       { at, entered_by, successor? } (BR-03)
POST /v1/function-allotments                         { employee_id, office_id, function_code, effective_from, entered_by: "ESTB@<office_id>" } (BR-04)
POST /v1/function-allotments/{id}/withdraw           { at, entered_by }
POST /v1/availability                                { employee_id, kind, from_ts, to_ts, entered_by, supersedes_id? } (BR-06)
POST /v1/posts/{sanctioned_post_id}/declare-vacant   { at, reason, entered_by }
```

**Events:** `posting.started`, `posting.ended`, `charge.started`, `charge.ended`, `function.allotted`,
`function.withdrawn`, `availability.started`, `availability.ended`, `employee.onboarded`.
Each event carries an `effective_at`; subscribers apply it when `effective_at <= now`.

### IAM stub (no authentication)

```
POST /v1/iam/login  {employee_id}                       → session_id, posts held now (incl. LINK charges), active_post_id
POST /v1/iam/switch {sanctioned_post_id}                + header X-Stub-Session (or session_id in body)
GET  /v1/iam/sessions/{session_id}?at=...               re-checks; revoked once posting.ended / charge.ended / availability.ended applies
```

### Acceptance scenarios the contract must keep passing

These are H1–H15 in the table above (spec section 10), implemented in `tests/test_acceptance.py`.

## MDM PoC integration

MDM base URL: `http://172.16.5.151:4001` (`data/config/mdm.json`; override with `HRU_MDM_URL`, or `off`).

| | |
|---|---|
| Copied from MDM (parent-first) | department, cadre, district, office-type, function, office-type-function, designation, office, sanctioned-post, designation-function, link-officer-rule, employee, holiday |
| Written to MDM | `POST /mdm/employees/mint` (onboarding), `PUT /mdm/entities/employee/{code}` (record corrections), sanctioned-post count +1 / −1 (add / abolish a chair), all with `X-User: hr-utility-poc` |
| Live checks | `POST /mdm/validate` (office, designation, employee) before a posting is saved |
| Kept local | demo officers and demo-only chairs, ACMR-00ASM, batch year / DOB / retirement, the ARTPS Link Officer condition, FinAssam / PAN / Aadhaar-hash de-duplication |
| Freshness | `GET /mdm/version` on startup and every 5 minutes; the cache refreshes when any copied type moves |
| MDM down | the last copy keeps serving; responses add `X-MDM-Stale: true`; postings save against the last copy |
| On every response | `X-MDM-Source`, `X-MDM-Version`, `X-MDM-Synced-At`; details at `GET /v1/mdm/status` |
| Usage callback | `GET /hr/usage/{entityType}/{code}` → `{ inUse, details }` (office, district, designation, sanctioned-post, employee, function, cadre) |
| Consumer registration | `python run.py --register-mdm --public-url http://<host>:8000` (code `hr-utility-poc`); **not done yet** |

The one-time load of our roster into MDM (03-11-2026) is `python -m seed.mdm_load --execute`; every write is in
`data/mdm_load/ledger.json`, and re-running it skips what is already done.

## Integration later
* **Rule Engine:** calls `/v1/seat-holders` and `/v1/posts/{id}/link-officer` at submission time. Rule
  logic is importable directly from `hr_utility.domain` if needed.
* **Workflow and IAM:** poll `/v1/events?after=` and call `/v1/employees/{id}/posts`.
