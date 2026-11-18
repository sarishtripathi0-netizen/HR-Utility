# Sewa Setu 2.0 — HR Utility PoC

The HR Utility answers one question for the Rule Engine: **"In office O, which sanctioned
posts of post P are held at time t by an officer holding function F, is that officer
available, and if none is, who is the Link Officer?"** It also ships a thin IAM stub.

It never stores or names ARTPS roles. No table, column or API uses those words. The Rule
Engine maps posts to roles; this service only knows posts, chairs, people and functions.

**MDM owns the masters; the HR Utility owns the events.** Offices, designations (= posts),
cadres, functions, office-type and designation functions, sanctioned strength (chairs),
Link Officer rules, employees (MDM mints the Employee ID) and holidays come from the MDM PoC
(`http://172.16.5.151:4001`, see MDM `integration.md` "HR Utility contract"). Postings,
function allotments, leave, vacancies, onboarding requests, audit log, events and IAM
sessions are the HR Utility's own records.

## Stack and why

| Choice | Why |
|---|---|
| Python 3.12 | Installed at `%LOCALAPPDATA%\Programs\Python\Python312` (not on PATH in old shells) |
| FastAPI | Typed request/response models, OpenAPI at `/openapi.json` for free |
| SQLAlchemy 2 + SQLite | Single file DB, zero setup; triggers enforce append-only (BR-10) |
| Jinja2 | Server-rendered screens, no JS build step |
| httpx | MDM client (live) and a mock MDM in tests |
| pytest + FastAPI TestClient | Tests hit the real API and the real seed, offline |
| openpyxl, pdfplumber | Read the source workbooks and the Nagaon allotment order |

## Folder structure

```
run.py                      one command: build + bind the seed (if needed), load DB, serve, keep MDM fresh
hr_utility/
  config.py                 Settings: flags, paths, salts, MDM URL (everything configurable)
  db.py                     engine, session, schema, append-only triggers, add-missing-columns migration
  models.py                 mdm_cache_* (read-only MDM copies) + HR tables (posting, function_allotment, ...)
  timeutil.py               UTC storage, Asia/Kolkata display, ?at= parsing
  mdm/client.py             MdmClient interface + record types
  mdm/workforce.py          MDM payloads + local overlay -> records (shared by both clients)
  mdm/http_client.py        HttpMdmClient: live MDM (snapshots, mint, corrections, chair counts, validate)
  mdm/seed_client.py        SeedMdmClient: the same, from data/mdm_snapshot (offline runs and tests)
  mdm/mapping.py            office / holiday / designation mapping; entity types copied and watched
  mdm/sync.py               refresh mdm_cache_*; version check (ensure_fresh)
  domain/                   ALL business rules live here (importable by Rule Engine)
    common.py               errors, intervals, supersede, audit + outbox helpers
    queries.py              as-of lookups, availability, seniority, post aliases, cadre department
    postings.py             BR-01, BR-02, BR-03, declare-vacant, MDM validate before saving
    functions.py            BR-04 (office-type and designation functions), BR-05
    availability.py         BR-06 (+ cancel)
    link_officer.py         BR-07 from MDM link-officer rules + local ARTPS condition
    seat.py                 seat-holders (the core question)
    history.py              BR-08 (holders + working days, MDM holidays)
    onboarding.py           BR-09 + identifier de-duplication + MDM mint
    roster.py, employees.py read models, record views, corrections, audit trail
    chairs.py               add / abolish chairs (MDM sanctioned count)
    usage.py                MDM usage callback (is an MDM record still used by HR?)
    iam.py                  IAM stub (login / switch / revoke)
  api/                      FastAPI routers — thin, no rules; schemas.py = typed bodies/responses + Swagger examples;
                            docs_export.py writes docs/openapi.json, openapi.yaml, swagger.html
  web/                      Jinja screens — thin, no rules
seed/
  build.py                  sources -> data/roster_plan (who sits where, by roster key R-NNNNNN) + load_report.md
  mdm_load.py               roster plan -> MDM (dry run / --execute; idempotent ledger) — done once, 03-11-2026
  mdm_pull.py               MDM -> data/mdm_snapshot (all copied types)
  bind.py                   roster plan + ledger + snapshot -> data/hr_seed (MDM IDs, chairs) + data/local_overlay
  load.py                   load the seed into a fresh DB through the domain layer
  mdm_map.py                mapping rules shared by mdm_load and bind
  parsers.py, names.py      source readers and name/mobile normalisation
data/
  *.xlsx, *.pdf             source files (read-only inputs)
  config/                   mdm.json (URL, scope, display order), link_officer_local.csv (ARTPS condition),
                            demo_function_bundles.csv, and the seed-time inputs that were loaded into MDM
  roster_plan/              what the sources say (input to mdm_load and bind)
  mdm_load/                 plan.json + ledger.json of the writes made to MDM (roster key -> MDM code)
  mdm_snapshot/             MDM as last pulled (what offline runs and tests read)
  local_overlay/            only what MDM does not hold yet (see below)
  hr_seed/                  seeded postings + function allotments under MDM codes
  load_report.md            every judgement made while building and binding the seed
docs/                       api.md (reference), integration.md (for consumers), openapi.json/.yaml, swagger.html
tests/                      BR-01..BR-10, H1..H15, MDM integration (mock MDM), screens, records, API docs
```

## How to run, seed and test

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py -m pip install -r requirements.txt
& $py run.py                 # build + bind seed if missing, create hr_utility.db, serve :8000, sync with MDM
& $py run.py --reset         # rebuild seed + DB (erases everything entered, incl. local stores)
& $py run.py --pull-mdm      # refresh data/mdm_snapshot from MDM, then rebuild
& $py run.py --offline       # never contact MDM (also: HRU_MDM_URL=off)
& $py -m seed.mdm_load       # dry run of a load into MDM (plan.json); --execute writes (ledger makes it re-runnable)
& $py run.py --register-mdm --public-url http://<host>:8000   # register as MDM consumer (only when asked)
& $py -m pytest -q           # all tests (offline; never call MDM)
& $py run.py --offline --export-openapi docs --no-serve   # regenerate docs/ after any API change (a test checks it)
```

UI: http://127.0.0.1:8000/ · OpenAPI: http://127.0.0.1:8000/openapi.json

## Conventions

- Every HR row is effective-dated, half-open `[from, to)`; `to = null` means current.
- Corrections and ends never edit a row: a new row is written and the old one gets
  `superseded_by`. Both are kept. `lineage_id` ties versions together. SQLite triggers
  reject DELETE everywhere and reject UPDATE of anything except `superseded_by`.
- Every write appends to `audit_log` and, where it matters to subscribers, `event_outbox`.
  Events carry `effective_at`; subscribers act when `effective_at <= now`.
- Timestamps are stored as UTC, returned as ISO-8601 in Asia/Kolkata (+05:30). A naive
  `?at=` value is read as IST; a date-only value means 00:00 IST that day.
- Posts are MDM designation codes (`ADC`, `CIRCLE_OFFICER` ...); MDM short names (`AC`, `CO`,
  `DC`) are accepted as aliases. Chairs are `<office>-<designation>-NN` (MDM strength expanded);
  local demo chairs are `<office>-<designation>-DNN`.
- Employee IDs are opaque: MDM mints `EMP-NNNN`; demo officers are local `DEMO-NNNN`.
- Seniority: `year_of_joining` ascending (unknown last), then name ascending.
- Logic lives in `hr_utility/domain`. API and web layers only parse input and render.
- Every endpoint has a `response_model`, a `summary` and a described tag; every request body has a Swagger example
  that succeeds against the seed (DC Nagaon story). `tests/test_api_docs.py` enforces this.
- Demo officers (`is_demo`) are minted locally as `DEMO-NNNN` (`mint_demo`) and never sent to MDM.

## Local overlay (held by the HR Utility until MDM has it)

| What | Where | Why |
|---|---|---|
| 44 demo officers, 10 demo-only chairs | `data/local_overlay/employees.csv`, `chairs.csv` | Synthetic; never sent to MDM |
| ACMR-00ASM (Registrar, President) | `data/local_overlay/offices.csv` | MDM still uses `ACMR_*` for Additional Commissioner (Revenue); the rename to `ACR` is pending |
| Batch year (seniority), DOB, retirement date, demo flag | `employee_extra.csv` + `*.employee_extra.jsonl` | MDM employee has no such fields |
| "Covering ADC/AC must hold ARTPS" | `data/config/link_officer_local.csv` | MDM link-officer-rule has no function field |
| FinAssam code / PAN / Aadhaar hash | `onboarding_request` | MDM mint does not take them; HR de-duplicates on them first |

## Open items (configurable, not decided here)

1. **Sanctioned strength** is MDM's. Where the roster had more officers than MDM's template, the
   load raised MDM's count; it never lowered one. MDM template chairs nobody on the roster holds
   appear as vacant chairs. Real strength: Establishment / Personnel, TBC.
2. **MDM gaps** to raise with the MDM team: `batchYear` (or seniority) on employee; a
   `requiredFunctionCode` on link-officer-rule (ARTPS); the `ACMR` → `ACR` rename, then an
   office for the Assam Council of Medical Registration.
3. **Function reshuffle and pending applications (BR-05)** — Rule Engine's job; not encoded here.
4. **Link Officer**: MDM rules + the local ARTPS condition; covering designations of equal
   priority compete on seniority. "Sub Registrar absent → CO" is a local demo rule. MDM also
   holds rules from its own seed (e.g. ADC → SDO_SADAR priority 2); they never match in the same
   office and are left untouched.
5. **Display order** of chairs: `data/config/mdm.json` `designation_display_order` (rank unused).
6. **Holidays** from MDM: state-wide + the district's LOCAL holidays; RESTRICTED are working days.
7. **Posting start dates in the seed** — sources are snapshots; seeded postings start 13-03-2026.
8. **Working-day attribution on a handover day** — counts for the incoming holder. Confirm.
9. **Aadhaar salt** — `HRU_AADHAAR_SALT`; the dev default must be replaced.
10. **Not yet registered as an MDM consumer** — MDM must reach this machine for `/hr/usage/...`.
    A consumer `hr-service` (another build) exists; this PoC uses `hr-utility-poc`.
11. **Writes made to MDM on 03-11-2026** (decision: "load ours into MDM"): 47 functions, 11 offices
    (10 co-districts + DAO Nalbari), 66 office-type functions, 90 designation functions, 52 chair
    counts, 84 employees minted, 11 Link Officer rules — all listed in `data/mdm_load/ledger.json`.
12. **Seed-time inputs** in `data/config/` (`posts.csv`, `function_codes.csv`, `office_type_functions.csv`,
    `post_function_rules.csv`, `issuing_departments.csv`) only feed the roster plan / MDM load; at
    run time MDM is the source.
