"""Bind the roster plan to MDM: write the HR seed under MDM's codes, plus the local overlay.

    python -m seed.bind

Inputs: data/roster_plan (from seed.build), data/mdm_load/ledger.json + plan.json (from seed.mdm_load --execute),
and data/mdm_snapshot (MDM after the load, from seed.mdm_pull). Outputs:
  data/hr_seed/postings.csv, function_allotments.csv   HR events, by MDM Employee ID and chair
  data/local_overlay/*.csv                             what MDM does not hold (see hr_utility.mdm.workforce)
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from hr_utility.mdm.mapping import snapshot_records
from hr_utility.mdm.workforce import chair_id

from .mdm_map import DESIGNATION, FUNCTION_ALIAS, OFFICE_TYPE, chair_goes_to_mdm

ROOT = Path(__file__).resolve().parent.parent


def _csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


class BindError(RuntimeError):
    pass


def bind(data_dir: Path) -> dict:
    data = Path(data_dir)
    plan_dir, snap_dir = data / "roster_plan", data / "mdm_snapshot"
    ledger_path, plan_path = data / "mdm_load" / "ledger.json", data / "mdm_load" / "plan.json"
    if not ledger_path.exists():
        raise BindError("No MDM load ledger: run `python -m seed.mdm_load --execute`, then `python -m seed.mdm_pull`.")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    office_map = json.loads(plan_path.read_text(encoding="utf-8")).get("office_map", {}) if plan_path.exists() else {}
    snap = {t: snapshot_records(json.loads((snap_dir / f"{t}.json").read_text(encoding="utf-8")))
            for t in ("office", "sanctioned-post", "employee")}
    mdm_offices = {o["code"] for o in snap["office"]}
    mdm_people = {e["code"] for e in snap["employee"]}
    strength = {(r["officeCode"], r["designationCode"]): int(r["sanctionedCount"]) for r in snap["sanctioned-post"]}

    offices = {o["office_id"]: o for o in _csv(plan_dir / "offices.csv")}
    people = _csv(plan_dir / "employees.csv")
    chairs = _csv(plan_dir / "sanctioned_posts.csv")
    report: dict[str, list[str]] = defaultdict(list)

    # people: real -> the Employee ID MDM minted; demo -> DEMO-NNNN (never sent to MDM)
    person, demo_n = {}, 0
    overlay_people, extra = [], []
    for p in people:
        if _b(p["is_demo"]):
            demo_n += 1
            person[p["employee_id"]] = f"DEMO-{demo_n:04d}"
            overlay_people.append({**p, "employee_id": person[p["employee_id"]]})
            continue
        minted = ledger.get(f"employee:{p['employee_id']}", {}).get("code")
        if not minted or minted not in mdm_people:
            raise BindError(f"{p['employee_id']} {p['name']} has no MDM Employee ID in the ledger/snapshot; "
                            f"re-run seed.mdm_load --execute and seed.mdm_pull")
        person[p["employee_id"]] = minted
        extra.append({"employee_id": minted, "year_of_joining": p["year_of_joining"], "date_of_birth": p["date_of_birth"],
                      "date_of_retirement": p["date_of_retirement"], "is_demo": False,
                      "source": f"roster {p['employee_id']}: {p['source']}"})

    # chairs: MDM chairs numbered in seniority order within MDM's strength; demo-only chairs follow, locally
    chair_map, local_chairs = {}, []
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in chairs:
        office = office_map.get(c["office_id"], c["office_id"])
        groups[(office, DESIGNATION[c["post_code"]])].append(c)
    for (office, post), group in groups.items():
        group.sort(key=lambda c: int(c["seq"]))
        to_mdm = [c for c in group if chair_goes_to_mdm(c) and office in mdm_offices]
        local = [c for c in group if c not in to_mdm]
        n = strength.get((office, post), 0)
        if len(to_mdm) > n:
            raise BindError(f"{office}:{post} has {len(to_mdm)} roster chairs but MDM sanctions {n}; re-run the load")
        for k, c in enumerate(to_mdm, start=1):
            chair_map[c["sanctioned_post_id"]] = chair_id(office, post, k)
        for j, c in enumerate(local, start=1):
            # Own series (-D01 ...) so a chair MDM sanctions later (-07 ...) never collides with a demo chair.
            new = f"{office}-{post}-D{j:02d}"
            chair_map[c["sanctioned_post_id"]] = new
            local_chairs.append({"sanctioned_post_id": new, "office_id": office, "post_code": post, "seq": 900 + j,
                                 "is_demo": True, "source": f"local demo chair ({c['source']})"})
            report["Local demo chairs (beyond MDM's sanctioned strength)"].append(new)

    postings = []
    for r in _csv(plan_dir / "postings.csv"):
        postings.append({**r, "employee_id": person[r["employee_id"]], "sanctioned_post_id": chair_map[r["sanctioned_post_id"]]})
    allotments = []
    for r in _csv(plan_dir / "function_allotments.csv"):
        for fn in FUNCTION_ALIAS.get(r["function_code"], [r["function_code"]]):
            allotments.append({**r, "employee_id": person[r["employee_id"]], "function_code": fn,
                               "office_id": office_map.get(r["office_id"], r["office_id"])})

    local_offices = [o for oid, o in offices.items() if office_map.get(oid, oid) not in mdm_offices]
    for o in local_offices:
        report["Offices kept locally (not in MDM)"].append(f"{o['office_id']} {o['name']}")
    local_types = {OFFICE_TYPE.get(o["office_type"], o["office_type"]) or o["office_type"] for o in local_offices}
    otf = [r for r in _csv(plan_dir / "office_type_functions.csv") if r["office_type"] in local_types]

    hr, ov = data / "hr_seed", data / "local_overlay"
    _write(hr / "postings.csv", ["employee_id", "sanctioned_post_id", "charge_type", "effective_from", "order_ref",
                                 "issuing_department", "note"], postings)
    _write(hr / "function_allotments.csv", ["employee_id", "office_id", "function_code", "effective_from", "is_demo",
                                            "source_ref"], allotments)
    _write(ov / "offices.csv", ["office_id", "name", "office_type", "district_code", "district_name", "parent_office_id",
                                "establishment_actor", "source"], local_offices)
    _write(ov / "employees.csv", ["employee_id", "name", "cadre", "year_of_joining", "source"], overlay_people)
    _write(ov / "employee_extra.csv", ["employee_id", "year_of_joining", "date_of_birth", "date_of_retirement", "is_demo",
                                       "source"], extra)
    _write(ov / "chairs.csv", ["sanctioned_post_id", "office_id", "post_code", "seq", "is_demo", "source"], local_chairs)
    _write(ov / "office_type_functions.csv", ["office_type", "function_code", "is_demo", "source"], otf)

    lines = ["", "## Bound to MDM (seed.bind)", "",
             f"- {len(extra)} real officers carry MDM Employee IDs; {len(overlay_people)} demo officers stay local (DEMO-NNNN).",
             f"- {len(postings)} postings and {len(allotments)} function allotments re-keyed to MDM IDs and chairs."]
    for section, items in report.items():
        lines += [f"- {section}: {', '.join(items)}"]
    with open(data / "load_report.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return {"real_officers": len(extra), "demo_officers": len(overlay_people), "postings": len(postings),
            "allotments": len(allotments), "local_chairs": len(local_chairs), "local_offices": len(local_offices)}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(bind(ROOT / "data"), indent=2))
