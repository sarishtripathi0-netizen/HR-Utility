"""MDM payloads (live or a saved snapshot) + the local overlay -> HR Utility MDM records.

MDM now owns the workforce masters (employee, cadre, sanctioned-post, function, office-type-function,
designation-function, link-officer-rule). The local overlay holds only what MDM does not have yet:
  data/local_overlay/offices.csv           offices MDM lacks (e.g. ACMR-00ASM)
  data/local_overlay/employees.csv         demo officers (DEMO-NNNN), never sent to MDM
  data/local_overlay/employee_extra.csv    HR-only attributes of MDM employees: batch year (seniority), DOB,
                                           retirement date, demo flag, provenance
  data/local_overlay/chairs.csv            demo-only chairs (beyond MDM's sanctioned strength)
  data/local_overlay/office_type_functions.csv   function lists for local office types
  data/config/link_officer_local.csv       conditions MDM cannot express (ARTPS) and demo rules
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

from .client import (
    CadreRec,
    DesignationFunctionRec,
    EmployeeRec,
    FunctionCodeRec,
    HolidayRec,
    LinkRuleRec,
    MdmDesignationRec,
    OfficeRec,
    OfficeTypeFunctionRec,
    PostFunctionRuleRec,
    PostRec,
    SanctionedPostRec,
)
from .mapping import SNAPSHOT_TYPES as WORKFORCE_TYPES  # noqa: F401 - re-exported for the clients
from .mapping import designation_rec, holiday_rec, office_rec


def _b(v) -> bool:
    return str(v).strip().lower() in ("1", "true", "yes")


def _none(v):
    return v if v not in (None, "") else None


def _int(v):
    return int(v) if v not in (None, "") else None


def _csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if not (next(iter(r.values()), "") or "").startswith("#")]


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def chair_id(office_id: str, post_code: str, seq: int) -> str:
    return f"{office_id}-{post_code}-{seq:02d}"


@dataclass
class Overlay:
    offices: list[OfficeRec] = field(default_factory=list)
    employees: list[EmployeeRec] = field(default_factory=list)
    extra: dict[str, dict] = field(default_factory=dict)          # employee_id -> HR-only attributes
    chairs: list[SanctionedPostRec] = field(default_factory=list)
    office_type_functions: list[OfficeTypeFunctionRec] = field(default_factory=list)
    link_rows: list[dict] = field(default_factory=list)
    scope: tuple[str, ...] = ()
    display_order: tuple[str, ...] = ()


def load_overlay(data_dir: Path, extra_store: Path | None = None) -> Overlay:
    data_dir = Path(data_dir)
    ov = data_dir / "local_overlay"
    cfg = json.loads((data_dir / "config" / "mdm.json").read_text(encoding="utf-8")) \
        if (data_dir / "config" / "mdm.json").exists() else {}
    offices = [OfficeRec(office_id=r["office_id"], name=r["name"], office_type=r["office_type"],
                         district_code=r["district_code"], district_name=_none(r.get("district_name")),
                         parent_office_id=_none(r.get("parent_office_id")), establishment_actor=r["establishment_actor"],
                         provisional=True, source=_none(r.get("source"))) for r in _csv(ov / "offices.csv")]
    employees = [EmployeeRec(employee_id=r["employee_id"], name=r["name"], cadre=_none(r.get("cadre")),
                             year_of_joining=_int(r.get("year_of_joining")), date_of_birth=None, date_of_retirement=None,
                             email=None, mobile=None, finassam_code=None, pan=None, aadhaar_token_hash=None, is_demo=True,
                             source=_none(r.get("source"))) for r in _csv(ov / "employees.csv")]
    extra = {}
    for r in _csv(ov / "employee_extra.csv"):
        extra[r["employee_id"]] = {"year_of_joining": _int(r.get("year_of_joining")),
                                   "date_of_birth": _none(r.get("date_of_birth")),
                                   "date_of_retirement": _none(r.get("date_of_retirement")),
                                   "is_demo": _b(r.get("is_demo")), "source": _none(r.get("source"))}
    for c in _jsonl(extra_store) if extra_store else []:  # corrections of HR-only fields made at run time
        extra.setdefault(c["employee_id"], {}).update(c["changes"])
    chairs = [SanctionedPostRec(sanctioned_post_id=r["sanctioned_post_id"], office_id=r["office_id"],
                                post_code=r["post_code"], seq=int(r["seq"]), derived=True, is_demo=_b(r.get("is_demo")),
                                source=_none(r.get("source"))) for r in _csv(ov / "chairs.csv")]
    otf = [OfficeTypeFunctionRec(r["office_type"], r["function_code"], _b(r.get("is_demo")), _none(r.get("source")))
           for r in _csv(ov / "office_type_functions.csv")]
    return Overlay(offices, employees, extra, chairs, otf, _csv(data_dir / "config" / "link_officer_local.csv"),
                   tuple(cfg.get("district_scope", ())), tuple(cfg.get("designation_display_order", ())))


class Workforce:
    """Maps one set of MDM records (type -> list of payloads) plus the overlay to HR records."""

    def __init__(self, snap: dict[str, list[dict]], overlay: Overlay, chair_deltas: list[dict] | None = None):
        self.snap = snap
        self.ov = overlay
        self.chair_deltas = chair_deltas or []

    def _recs(self, t: str) -> list[dict]:
        return self.snap.get(t, [])

    def office_ids(self) -> set[str]:
        return {o.office_id for o in self.offices()}

    def offices(self) -> list[OfficeRec]:
        scope = set(self.ov.scope)
        out = [office_rec(r) for r in self._recs("office") if not scope or r.get("districtCode") in scope]
        have = {o.office_id for o in out}
        return out + [o for o in self.ov.offices if o.office_id not in have]

    def posts(self) -> list[PostRec]:
        order = {c: i for i, c in enumerate(self.ov.display_order)}
        levels = {"STATE": 1, "DISTRICT": 2, "SUBDIVISION": 3, "CIRCLE": 4, "BLOCK": 5, "VILLAGE": 6, "WARD": 7}
        out = []
        for r in self._recs("designation"):
            rank = (order[r["code"]] + 1) * 10 if r["code"] in order else 1000 + levels.get(r.get("level"), 9) * 10
            out.append(PostRec(post_code=r["code"], name=r["name"], rank_order=rank, source="MDM designation",
                               mdm_designation_code=r["code"], short_name=_none(r.get("shortName"))))
        return out

    def chairs(self) -> list[SanctionedPostRec]:
        """MDM sanctioned strength (office x designation x count) expanded to numbered chairs, plus local chairs."""
        offices = self.office_ids()
        counts: dict[tuple[str, str], tuple[int, bool, str]] = {}
        for r in self._recs("sanctioned-post"):
            if r["officeCode"] in offices:
                counts[(r["officeCode"], r["designationCode"])] = (int(r["sanctionedCount"]), bool(r.get("isActive", True)),
                                                                   r["code"])
        for d in self.chair_deltas:  # offline emulation of add / abolish
            key = (d["office_id"], d["post_code"])
            n, active, code = counts.get(key, (0, True, f"{key[0]}:{key[1]}"))
            counts[key] = (n + d["delta"], active, code)
        out = []
        for (office, post), (n, active, code) in sorted(counts.items()):
            for seq in range(1, n + 1):
                out.append(SanctionedPostRec(sanctioned_post_id=chair_id(office, post, seq), office_id=office,
                                             post_code=post, seq=seq, derived=False, is_demo=False,
                                             source=f"MDM sanctioned-post {code} ({n})", is_active=active))
        have = {c.sanctioned_post_id for c in out}
        return out + [c for c in self.ov.chairs if c.sanctioned_post_id not in have]

    def function_codes(self) -> list[FunctionCodeRec]:
        return [FunctionCodeRec(r["code"], r["name"], r.get("departmentCode") or "MDM", "MDM function")
                for r in self._recs("function")]

    def office_type_functions(self) -> list[OfficeTypeFunctionRec]:
        out = [OfficeTypeFunctionRec(r["officeTypeCode"], r["functionCode"], False, "MDM office-type-function")
               for r in self._recs("office-type-function") if r.get("isActive", True)]
        mdm_types = {r.office_type for r in out}
        return out + [r for r in self.ov.office_type_functions if r.office_type not in mdm_types]

    def post_function_rules(self) -> list[PostFunctionRuleRec]:
        return [PostFunctionRuleRec(r["code"], "ALL_OFFICE_FUNCTIONS" if r.get("holdsAllFunctions", True) else "ALLOTTED",
                                    False, "MDM designation.holdsAllFunctions") for r in self._recs("designation")]

    def designation_functions(self) -> list[DesignationFunctionRec]:
        return [DesignationFunctionRec(r["designationCode"], r["functionCode"], "MDM designation-function")
                for r in self._recs("designation-function") if r.get("isActive", True)]

    def cadres(self) -> list[CadreRec]:
        return [CadreRec(r["code"], r["name"], r.get("departmentCode"), r.get("departmentName"), "MDM cadre")
                for r in self._recs("cadre")]

    def link_rules(self) -> list[LinkRuleRec]:
        conditions = [r for r in self.ov.link_rows if r.get("covering") == "*"]

        def condition(office_type: str, post: str) -> str | None:
            for c in conditions:
                if c["office_type"] == office_type and c["designation"] in ("*", post) and _none(c.get("required_function")):
                    return c["required_function"]
            return None

        out = [LinkRuleRec(r["code"], r["officeTypeCode"], r["designationCode"], r["coveringDesignationCode"],
                           int(r.get("priority") or 1), condition(r["officeTypeCode"], r["designationCode"]),
                           "MDM link-officer-rule") for r in self._recs("link-officer-rule") if r.get("isActive", True)]
        have = {r.code for r in out}
        for r in self.ov.link_rows:
            if r.get("covering") == "*":
                continue
            code = f"{r['office_type']}:{r['designation']}:{r['covering']}"
            if code not in have:
                out.append(LinkRuleRec(code, r["office_type"], r["designation"], r["covering"], int(r.get("priority") or 1),
                                       _none(r.get("required_function")) or condition(r["office_type"], r["designation"]),
                                       f"local: {r.get('basis', '')}"))
        return out

    def employees(self) -> list[EmployeeRec]:
        out = []
        for r in self._recs("employee"):
            x = self.ov.extra.get(r["code"], {})
            doj = _none(r.get("dateOfJoining"))
            out.append(EmployeeRec(
                employee_id=r["code"], name=r["name"], cadre=_none(r.get("cadreCode")),
                year_of_joining=x.get("year_of_joining") or (int(doj[:4]) if doj else None),
                date_of_birth=x.get("date_of_birth"), date_of_retirement=x.get("date_of_retirement"),
                email=_none(r.get("email")), mobile=_none(r.get("mobile")), finassam_code=None, pan=None,
                aadhaar_token_hash=None, is_demo=bool(x.get("is_demo", False)),
                source=x.get("source") or "MDM employee", gender=_none(r.get("gender")), date_of_joining=doj))
        have = {e.employee_id for e in out}
        for e in self.ov.employees:
            if e.employee_id in have:
                continue
            x = self.ov.extra.get(e.employee_id, {})
            out.append(EmployeeRec(**{**e.__dict__, **{k: v for k, v in x.items() if k in EmployeeRec.__dataclass_fields__}}))
        return out

    def holidays(self) -> list[HolidayRec]:
        return [holiday_rec(r) for r in self._recs("holiday")]

    def mdm_designations(self) -> list[MdmDesignationRec]:
        return [designation_rec(r) for r in self._recs("designation")]
