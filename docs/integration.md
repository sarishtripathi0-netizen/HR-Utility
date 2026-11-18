# Integrating with the HR Utility

This page is for the Rule Engine, IAM, Workflow and MDM teams. It covers what to call, when to call it, and what to
rely on. The endpoint reference with examples is [api.md](api.md); the machine-readable contract is
[openapi.json](openapi.json) / [openapi.yaml](openapi.yaml) (OpenAPI 3.1).

## What the HR Utility is responsible for

| It owns | It reads from MDM (does not own) | It never does |
|---|---|---|
| Postings and additional charges, function allotments, leave / tour / training / deputation, vacancy declarations, onboarding requests, audit log, event outbox, IAM stub sessions | Offices, office types, designations (= posts), cadres, functions, office-type functions, designation functions, sanctioned strength (chairs), Link Officer rules, employees, holidays | Store or name application roles (who is the approving or appellate authority for a service). That mapping belongs to the Rule Engine; the HR Utility knows only posts, chairs, people and functions |

MDM is at `http://172.16.5.151:4001`. The HR Utility checks MDM's version at start-up and every 5 minutes. It refreshes
its copy when the version moves. If MDM is down, it keeps answering from the last copy and sets `X-MDM-Stale: true`.

## Rule Engine

**The one call to make when an application needs an officer:**

```
GET /v1/seat-holders?office_id=<office>&post_code=<designation>&function_code=<function>&at=<time>
```

- **Send `at`.** Re-evaluating an old application should ask about the time it was filed or acted on, not now.
  All reads are time-travel reads.
- **Read `status` first.**
  - `RESOLVED`: use `holders` where `available: true`; if there are none, use `link_officer`.
  - `NO_LINK_OFFICER`: nobody is available and no rule matched. Route to manual handling; `reason` says why.
  - `NOT_APPLICABLE`: no Link Officer rule exists for that office type and post.
- **Several holders can be available**, for example two ADCs who both hold the function. The order is seniority:
  year of joining ascending, then name. How to choose among them (load, round robin) is the Rule Engine's decision.
- `link_officer.rule_step` explains the choice:
  - `ARTPS_HOLDER`: an ADC or AC holding ARTPS in a DC or co-district office;
  - `SAME_POST`: another holder of the same post;
  - a designation code such as `SUB_REGISTRAR`: a circle with a single CO.

  `deemed_dps_under_rule_3_3` is a flag from the frozen contract; mapping it to a role is your decision.
- `post_code` accepts MDM short names (`CO`, `AC`, `DC`) as aliases.
- **Days-limit calculations:** `GET /v1/posts/{chair}/history?from=&to=` gives each holder's sub-intervals and
  working days. Sundays and MDM holidays (state-wide plus the district's local ones) are excluded. A handover day
  counts for the incoming holder (open item 8, to confirm).
- **Reshuffling pending applications** when functions move (BR-05) is not done here. Subscribe to
  `function.allotted` / `function.withdrawn` and `posting.*` (below) and re-route on your side.

## IAM

- **After login, list what the officer may act as:** `GET /v1/employees/{employee_id}/posts?at=`. Substantive and
  additional charges are listed, and so are Link Officer charges (with `rule_step` and `covering_for`) while the
  covered officer is away.
- **Revoke access on events.** Revoke when `posting.ended` or `charge.ended` applies to the active post. For a link
  charge, also revoke on `availability.ended` for the covered officer, because they are back.
- The `/v1/iam/*` endpoints are a **stub without authentication**. They show the expected behaviour (login, switch
  post, revocation on events) and must be replaced by the Officer IAM.

## Workflow and dashboards

- `GET /v1/offices/{office_id}/roster?at=` returns every chair in an office with holders, functions, availability,
  vacancy and the Link Officer where one applies. It is one call per screen.
- `GET /v1/offices/{office_id}/chairs` and `GET /v1/postings?office_id=` give the record views.

## Event subscribers

```
GET /v1/events?after=<last id you processed>&limit=500
```

1. Keep the last `id` you processed, and poll from it. Ids are increasing and never reused; events are never edited
   or removed.
2. **Act only when `effective_at <= now`.** An order entered today can take effect next week. Keep future events and
   act on them when their time comes.
3. Payloads carry `employee_id`, `sanctioned_post_id`, `office_id`, `post_code`, `charge_type`, `lineage_id` and
   `is_demo`. Skip or segregate `is_demo: true` in production.

| Type | Typical consumer action |
|---|---|
| `posting.started` / `posting.ended` | IAM grants or revokes; the Rule Engine re-routes pending work |
| `charge.started` / `charge.ended` | Same, for additional charges |
| `function.allotted` / `function.withdrawn` | The Rule Engine re-routes applications for that function (BR-05) |
| `availability.started` / `availability.ended` | The Rule Engine switches to or from the Link Officer; IAM grants or revokes link charges |
| `employee.onboarded` | Create the IAM account |

## MDM

- **Usage callback.** Before deactivating a record, MDM can ask the HR Utility whether the record is still used:
  `GET /hr/usage/{entity_type}/{code}` returns `{"inUse": bool, "details": {...}}`. A record is in use while
  officers are posted, or functions allotted, under it. Supported types: office, district, designation,
  sanctioned-post, employee, function, cadre, holiday.
- **Consumer registration** is not done yet (open item 10). It needs an address MDM can reach, then:
  `python run.py --register-mdm --public-url http://<host>:8000`. The consumer code is `hr-utility-poc`; the
  existing `hr-service` consumer belongs to another build and is left alone.
- **Writes the HR Utility makes to MDM.** Every write carries headers `X-User: hr-utility-poc` and
  `X-Change-Reason`.

  | HR action | MDM call |
  |---|---|
  | Onboarding (non-demo) | `POST /mdm/employees/mint` (identifiers such as PAN and Aadhaar are not sent) |
  | Correcting an officer's name, gender, cadre, date of joining, email or mobile | `PUT /mdm/entities/employee/{code}` |
  | Adding or abolishing a chair | the sanctioned-post count, plus or minus 1 |
  | Before saving a posting | `POST /mdm/validate` |

- **What MDM does not hold yet**, kept locally until it does:
  - batch year (seniority), DOB and retirement date on employee;
  - a required function (ARTPS) on link-officer-rule;
  - the Assam Council of Medical Registration office, pending MDM's `ACMR` → `ACR` rename;
  - demo officers and chairs.

## Reliability notes

- Reads never call MDM synchronously: they read the local copy, so MDM latency or outage does not slow them.
  Posting writes do call `POST /mdm/validate` first. If MDM is unreachable, the write goes ahead and is logged.
- Every response states the MDM version it reflects (`X-MDM-Version`). Log it with Rule Engine decisions so a
  decision can be explained later.
- Errors have one shape: `{"error": {"rule": "BR-xx" | null, "message": "..."}}`. A 409 is a business refusal.
  Show the message to the user; it says what to do instead.

## Running it

```powershell
$py = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $py run.py                 # live MDM, http://127.0.0.1:8000  (Swagger UI: /docs, ReDoc: /redoc)
& $py run.py --offline       # MDM snapshot only; safe for experiments
& $py run.py --export-openapi docs --no-serve   # regenerate docs/openapi.json, openapi.yaml, swagger.html
```

To reach it from another machine, start it with `--host 0.0.0.0`. Callers then use `http://<this machine>:8000`.
Re-export with `--public-url` so the documents list that server.
