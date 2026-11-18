"""Load the HR Utility's real data into the MDM PoC (decision 03-11-2026: "A. Load ours into MDM").

    python -m seed.mdm_load              dry run: write data/mdm_load/plan.json and print a summary
    python -m seed.mdm_load --execute    perform the writes (idempotent; data/mdm_load/ledger.json)

Source: the generated seed (data/mdm_seed, data/hr_seed). Only real data is sent; demo officers and demo-only
chairs stay in the HR Utility. Every write carries X-User and X-Change-Reason. MDM never hard-deletes and never
reuses an Employee ID, so the ledger records every completed write and a re-run skips it.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import httpx

from hr_utility.mdm.mapping import load_mdm_config, snapshot_records

from .mdm_map import DESIGNATION, FUNCTION_ALIAS, OFFICE_TYPE, chair_goes_to_mdm

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PLAN = DATA / "roster_plan"
OUT = DATA / "mdm_load"
ACTOR = "hr-utility-poc"
REASON = "HR Utility PoC: load HR roster data into MDM (decision 03-11-2026, option A)"

# Co-district names that the sources abbreviate.
UNIT_NAME = {"New Ghy": "New Guwahati"}
# The parts of the hard-coded Link Officer rules MDM can express (ARTPS condition stays in the HR Utility).
LINK_RULES = (
    [("DC_OFFICE", d, c, 1) for d in ("DISTRICT_COMMISSIONER", "ADC", "ASSISTANT_COMMISSIONER")
     for c in ("ADC", "ASSISTANT_COMMISSIONER")]
    + [("SUBDIV_OFFICE", d, c, 1) for d in ("CO_DISTRICT_COMMISSIONER", "ADC", "ASSISTANT_COMMISSIONER")
       for c in ("ADC", "ASSISTANT_COMMISSIONER")]
    + [("CIRCLE_OFFICE", "CIRCLE_OFFICER", "CIRCLE_OFFICER", 1), ("CIRCLE_OFFICE", "CIRCLE_OFFICER", "SUB_REGISTRAR", 2)]
)


def _csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


class Loader:
    TYPES = ("function", "office", "office-type-function", "designation-function", "sanctioned-post",
             "link-officer-rule", "employee", "cadre", "designation")

    def __init__(self, base_url: str, timeout: float = 30.0, snapshot_dir: Path | None = None):
        """snapshot_dir: plan from saved snapshots (dry run while MDM is unreachable). Execution always reads live."""
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout,
                                 headers={"X-User": ACTOR, "X-Change-Reason": REASON})
        OUT.mkdir(parents=True, exist_ok=True)
        self.ledger_path = OUT / "ledger.json"
        self.ledger = json.loads(self.ledger_path.read_text(encoding="utf-8")) if self.ledger_path.exists() else {}
        if snapshot_dir:
            self.mdm = {t: snapshot_records(json.loads((snapshot_dir / f"{t}.json").read_text(encoding="utf-8")))
                        for t in self.TYPES}
        else:
            self.mdm = {t: snapshot_records(self._get(f"/mdm/snapshot/{t}", includeInactive="true")) for t in self.TYPES}
        self.codes = {t: {r["code"]: r for r in recs} for t, recs in self.mdm.items()}

    def _get(self, path, **params):
        r = self.http.get(path, params=params or None)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------ plan

    def plan(self) -> list[dict]:
        seed = PLAN
        offices = {o["office_id"]: o for o in _csv(seed / "offices.csv")}
        chairs = _csv(seed / "sanctioned_posts.csv")
        employees = _csv(seed / "employees.csv")
        fns = {f["code"]: f for f in _csv(seed / "function_codes.csv")}
        otf = _csv(seed / "office_type_functions.csv")
        items: list[dict] = []

        def add(kind, key, method, path, body, note=""):
            items.append({"kind": kind, "key": key, "method": method, "path": path, "body": body, "note": note,
                          "done": key in self.ledger})

        # 1. functions
        for code, f in fns.items():
            if code in FUNCTION_ALIAS or code in self.codes["function"]:
                continue
            add("function", f"function:{code}", "POST", "/mdm/entities/function", {"code": code, "name": f["name"]})

        # 2. offices MDM lacks (co-districts, District Agriculture Office Nalbari); ACMR waits for MDM's ACR rename
        office_map = {}
        for oid, o in offices.items():
            mdm_type = OFFICE_TYPE.get(o["office_type"], o["office_type"])
            if not _b(o["provisional"]) or mdm_type is None:
                continue
            if mdm_type == "SUBDIV_OFFICE":
                unit = UNIT_NAME.get(o["name"].split(",", 1)[1].strip(), o["name"].split(",", 1)[1].strip())
                code = f"SDO_{o['district_code']}-{re.sub(r'[^A-Z]', '', unit.upper())[:3]}"
                body = {"code": code, "name": f"Co-District Office, {unit}", "officeTypeCode": "SUBDIV_OFFICE",
                        "departmentCode": "GAD", "districtCode": o["district_code"],
                        "parentOfficeCode": o["parent_office_id"] or None}
            elif mdm_type == "DISTRICT_AGRICULTURE_OFFICE":
                code = f"DAO_{o['district_code']}"
                body = {"code": code, "name": f"District Agriculture Office, {o['district_name']}",
                        "officeTypeCode": mdm_type, "departmentCode": "AGRI", "districtCode": o["district_code"]}
            else:
                continue
            office_map[oid] = code
            if code not in self.codes["office"]:
                add("office", f"office:{code}", "POST", "/mdm/entities/office",
                    {k: v for k, v in body.items() if v is not None}, note=f"was provisional {oid}")

        # 3. office-type functions
        for row in otf:
            mdm_type = OFFICE_TYPE.get(row["office_type"], row["office_type"])
            if mdm_type is None:
                continue
            for fn in FUNCTION_ALIAS.get(row["function_code"], [row["function_code"]]):
                code = f"{mdm_type}:{fn}"
                if code not in self.codes["office-type-function"]:
                    add("office-type-function", f"otf:{code}", "POST", "/mdm/entities/office-type-function",
                        {"officeTypeCode": mdm_type, "functionCode": fn})

        # 4. designation functions: what an ADC / AC may be allotted (DC office and co-district lists)
        allottable = sorted({fn for row in otf if row["office_type"] in ("DC_OFFICE", "SUBDIV_OFFICE")
                             for fn in FUNCTION_ALIAS.get(row["function_code"], [row["function_code"]])})
        for desig in ("ADC", "ASSISTANT_COMMISSIONER"):
            for fn in allottable:
                code = f"{desig}:{fn}"
                if code not in self.codes["designation-function"]:
                    add("designation-function", f"df:{code}", "POST", "/mdm/entities/designation-function",
                        {"designationCode": desig, "functionCode": fn})

        # 5. sanctioned strength: chairs of the real roster (demo-only chairs and ACMR stay local)
        need = Counter()
        for c in chairs:
            if not chair_goes_to_mdm(c):
                continue
            office = office_map.get(c["office_id"], c["office_id"])
            if office not in self.codes["office"] and office not in office_map.values():
                continue
            need[(office, DESIGNATION[c["post_code"]])] += 1
        for (office, desig), n in sorted(need.items()):
            code = f"{office}:{desig}"
            have = self.codes["sanctioned-post"].get(code)
            if have is None:
                add("sanctioned-post", f"sp:{code}:{n}", "POST", "/mdm/entities/sanctioned-post",
                    {"officeCode": office, "designationCode": desig, "sanctionedCount": n})
            elif int(have["sanctionedCount"]) < n:
                add("sanctioned-post", f"sp:{code}:{n}", "PUT", f"/mdm/entities/sanctioned-post/{code}",
                    {"sanctionedCount": n}, note=f"MDM had {have['sanctionedCount']}")

        # 6. employees: the real officers (minted; MDM issues the codes)
        cadres = set(self.codes["cadre"])
        used_mobiles = {e.get("mobile") for e in self.mdm["employee"] if e.get("mobile")}
        used_emails = {(e.get("email") or "").lower() for e in self.mdm["employee"] if e.get("email")}
        for e in employees:
            if _b(e["is_demo"]):
                continue
            body = {"name": e["name"]}
            mob = e.get("mobile") or ""
            if re.fullmatch(r"[6-9]\d{9}", mob) and mob not in used_mobiles:
                body["mobile"] = mob
                used_mobiles.add(mob)
            em = (e.get("email") or "").lower()
            if em and "@" in em and em not in used_emails:
                body["email"] = em
                used_emails.add(em)
            if e.get("cadre") in cadres:
                body["cadreCode"] = e["cadre"]
            note = "" if "mobile" in body or not mob else f"mobile {mob} not sent (invalid or already used)"
            add("employee", f"employee:{e['employee_id']}", "POST", "/mdm/employees/mint", body, note=note)

        # 7. link-officer rules MDM can express
        for ot, d, c, prio in LINK_RULES:
            code = f"{ot}:{d}:{c}"
            if code not in self.codes["link-officer-rule"]:
                add("link-officer-rule", f"lor:{code}", "POST", "/mdm/entities/link-officer-rule",
                    {"officeTypeCode": ot, "designationCode": d, "coveringDesignationCode": c, "priority": prio})

        (OUT / "plan.json").write_text(json.dumps({"office_map": office_map, "items": items}, indent=2), encoding="utf-8")
        return items

    # ------------------------------------------------------------ execute

    def execute(self, items: list[dict]) -> dict:
        done, failed = 0, []
        for it in items:
            if it["key"] in self.ledger:
                continue
            r = self.http.request(it["method"], it["path"], json=it["body"])
            if r.status_code in (200, 201):
                rec = r.json().get("record", {})
                self.ledger[it["key"]] = {"code": rec.get("code"), "version": r.json().get("version")}
                self.ledger_path.write_text(json.dumps(self.ledger, indent=2), encoding="utf-8")  # after every write
                done += 1
            else:
                failed.append({"key": it["key"], "status": r.status_code, "body": r.text[:400]})
        (OUT / "failures.json").write_text(json.dumps(failed, indent=2), encoding="utf-8")
        return {"written": done, "failed": len(failed)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--base-url", default=None)
    ap.add_argument("--snapshot-dir", type=Path, default=None, help="plan from saved snapshots (dry run only)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.execute and args.snapshot_dir:
        print("--execute always reads MDM live; drop --snapshot-dir")
        return 2
    loader = Loader(args.base_url or load_mdm_config(DATA)["base_url"], snapshot_dir=args.snapshot_dir)
    items = loader.plan()
    by_kind = defaultdict(lambda: [0, 0])
    for it in items:
        by_kind[it["kind"]][1 if it["done"] else 0] += 1
    print(json.dumps({k: {"to_write": v[0], "already_done": v[1]} for k, v in by_kind.items()}, indent=2))
    notes = [f"{it['key']}: {it['note']}" for it in items if it["note"]]
    if notes:
        print("Notes:\n  " + "\n  ".join(notes))
    if args.execute:
        print(json.dumps(loader.execute(items), indent=2))
    else:
        print(f"Dry run only. Plan: {OUT / 'plan.json'}. Run with --execute to write to MDM.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
