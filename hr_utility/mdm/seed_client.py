"""SeedMdmClient: the MDM PoC as it was when data/mdm_snapshot/ was saved, for offline runs and tests.

It reads the same MDM payloads HttpMdmClient reads live and maps them through hr_utility.mdm.workforce, so both
return identical records. Writes are emulated the way MDM performs them (minting EMP-NNNN with a duplicate check
on mobile / email, sanctioned-strength counts, record corrections) and kept in JSON-lines files beside the DB.
HR-only attributes (batch year, DOB, retirement date, demo flag) are kept locally in both modes.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

from .client import (
    CadreRec,
    DesignationFunctionRec,
    DesignationRec,
    EmployeeRec,
    FunctionCodeRec,
    HolidayRec,
    LinkRuleRec,
    MdmDesignationRec,
    MintPayload,
    MintResult,
    OfficeRec,
    OfficeTypeFunctionRec,
    PostFunctionRuleRec,
    PostRec,
    SanctionedPostRec,
)
from .mapping import snapshot_records
from .workforce import WORKFORCE_TYPES, Workforce, _jsonl, chair_id, load_overlay

# MDM employee fields (HR name -> MDM payload key) and the HR-only ones kept locally.
MDM_EMPLOYEE_FIELDS = {"name": "name", "gender": "gender", "mobile": "mobile", "email": "email", "cadre": "cadreCode",
                       "date_of_joining": "dateOfJoining"}
HR_EMPLOYEE_FIELDS = ("year_of_joining", "date_of_birth", "date_of_retirement", "is_demo")


DEMO_PREFIX = "DEMO-"


class ChairError(ValueError):
    pass


class WorkforceClient:
    """MdmClient read methods shared by the offline and live clients; subclasses provide _snapshot()."""

    def __init__(self, data_dir: Path, minted_store: Path):
        self.data_dir = Path(data_dir)
        self.minted_store, self.chairs_store, self.corrections_store, self.extra_store = self.store_paths(minted_store)
        self._lock = threading.Lock()

    @staticmethod
    def store_paths(minted_store: Path) -> tuple[Path, Path, Path, Path]:
        """(minted employees, chair count changes, employee corrections, HR-only employee attributes)."""
        minted = Path(minted_store)
        base = minted.name[: -len("minted.jsonl")] if minted.name.endswith("minted.jsonl") else minted.name + "."
        return (minted, minted.with_name(base + "chairs.jsonl"), minted.with_name(base + "employee_corrections.jsonl"),
                minted.with_name(base + "employee_extra.jsonl"))

    @staticmethod
    def _append(path: Path, obj: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")

    def _snapshot(self) -> dict[str, list[dict]]:
        raise NotImplementedError

    def _chair_deltas(self) -> list[dict]:
        return []

    def _wf(self) -> Workforce:
        ov = load_overlay(self.data_dir, self.extra_store)
        ov.employees += [EmployeeRec(employee_id=e["code"], name=e["name"], cadre=e.get("cadreCode"), year_of_joining=None,
                                     date_of_birth=None, date_of_retirement=None, email=e.get("email"),
                                     mobile=e.get("mobile"), finassam_code=None, pan=None, aadhaar_token_hash=None,
                                     is_demo=True, source="HR Utility demo onboarding", gender=e.get("gender"),
                                     date_of_joining=e.get("dateOfJoining"))
                         for e in _jsonl(self.minted_store) if e["code"].startswith(DEMO_PREFIX)]
        return Workforce(self._snapshot(), ov, self._chair_deltas())

    # read side
    def list_offices(self) -> list[OfficeRec]:
        return self._wf().offices()

    def list_posts(self) -> list[PostRec]:
        return self._wf().posts()

    def list_sanctioned_posts(self) -> list[SanctionedPostRec]:
        return self._wf().chairs()

    def list_function_codes(self) -> list[FunctionCodeRec]:
        return self._wf().function_codes()

    def list_office_type_functions(self) -> list[OfficeTypeFunctionRec]:
        return self._wf().office_type_functions()

    def list_post_function_rules(self) -> list[PostFunctionRuleRec]:
        return self._wf().post_function_rules()

    def list_designation_functions(self) -> list[DesignationFunctionRec]:
        return self._wf().designation_functions()

    def list_cadres(self) -> list[CadreRec]:
        return self._wf().cadres()

    def list_link_rules(self) -> list[LinkRuleRec]:
        return self._wf().link_rules()

    def list_designations(self) -> list[DesignationRec]:
        wf = self._wf()
        return [DesignationRec(p.post_code, f.code, f"{p.post_code} – {f.name}") for p in wf.posts() for f in wf.function_codes()]

    def list_mdm_designations(self) -> list[MdmDesignationRec]:
        return self._wf().mdm_designations()

    def list_employees(self) -> list[EmployeeRec]:
        return self._wf().employees()

    def get_employee(self, employee_id: str) -> EmployeeRec | None:
        return next((e for e in self.list_employees() if e.employee_id == employee_id), None)

    def list_holidays(self) -> list[HolidayRec]:
        return self._wf().holidays()

    # shared write helpers
    def _save_hr_fields(self, employee_id: str, values: dict, actor: str) -> None:
        hr = {k: v for k, v in values.items() if k in HR_EMPLOYEE_FIELDS and v is not None}
        if hr:
            self._append(self.extra_store, {"employee_id": employee_id, "changes": hr, "by": actor})

    def _duplicate(self, payload: MintPayload) -> MintResult | None:
        """Mobile or email already held by an employee (MDM's own uniqueness rule)."""
        for key, value in (("MOBILE", payload.mobile), ("EMAIL", payload.email)):
            hit = next((e for e in self.list_employees()
                        if value and (getattr(e, key.lower()) or "").lower() == value.lower()), None)
            if hit:
                return MintResult(hit.employee_id, duplicate=True, matched_on=key,
                                  message=f"{key.lower()} already belongs to {hit.employee_id}")
        return None

    def mint_demo(self, payload: MintPayload) -> MintResult:
        """Demo officers are never sent to MDM: the HR Utility gives them the next local DEMO-NNNN."""
        with self._lock:
            dup = self._duplicate(payload)
            if dup:
                return dup
            nums = [int(m.group(1)) for e in self.list_employees() if (m := re.fullmatch(r"DEMO-(\d+)", e.employee_id))]
            code = f"{DEMO_PREFIX}{max(nums, default=0) + 1:04d}"
            self._append(self.minted_store, {"code": code, "name": payload.name, "gender": payload.gender,
                                             "mobile": payload.mobile, "email": payload.email, "cadreCode": payload.cadre,
                                             "dateOfJoining": payload.date_of_joining, "isActive": True})
            self._save_hr_fields(code, {**payload.__dict__, "is_demo": True}, payload.source or "mint")
            return MintResult(code, duplicate=False)

    def _is_local_employee(self, employee_id: str) -> bool:
        return employee_id.startswith(DEMO_PREFIX) or any(e.employee_id == employee_id
                                                          for e in load_overlay(self.data_dir).employees)

    def _top_chair(self, sanctioned_post_id: str) -> SanctionedPostRec:
        chairs = [c for c in self.list_sanctioned_posts() if c.is_active]
        chair = next((c for c in chairs if c.sanctioned_post_id == sanctioned_post_id), None)
        if chair is None:
            raise ChairError(f"{sanctioned_post_id} is not an active MDM chair")
        if chair.derived:
            raise ChairError(f"{sanctioned_post_id} is a local demo chair, not part of MDM's sanctioned strength")
        top = max(c.seq for c in chairs if c.office_id == chair.office_id and c.post_code == chair.post_code)
        if chair.seq != top:
            raise ChairError(f"MDM holds strength as a count, so only the highest-numbered chair can be abolished "
                             f"({chair_id(chair.office_id, chair.post_code, top)})")
        return chair


class SeedMdmClient(WorkforceClient):
    def __init__(self, data_dir: Path, minted_store: Path):
        super().__init__(data_dir, minted_store)
        self.snap_dir = self.data_dir / "mdm_snapshot"
        if not (self.snap_dir / "office.json").exists():
            raise FileNotFoundError(f"{self.snap_dir} not found; run `python -m seed.mdm_pull` first")
        self._base: dict[str, list[dict]] | None = None

    def _snapshot(self) -> dict[str, list[dict]]:
        if self._base is None:
            self._base = {t: snapshot_records(json.loads((self.snap_dir / f"{t}.json").read_text(encoding="utf-8")))
                          if (self.snap_dir / f"{t}.json").exists() else [] for t in WORKFORCE_TYPES}
        snap = dict(self._base)
        employees = {e["code"]: dict(e) for e in snap.get("employee", [])}
        for e in _jsonl(self.minted_store):
            if not e["code"].startswith(DEMO_PREFIX):  # demo officers are local, not part of the MDM emulation
                employees[e["code"]] = e
        for c in _jsonl(self.corrections_store):
            if c["employee_id"] in employees:
                employees[c["employee_id"]].update(c["changes"])
        snap["employee"] = list(employees.values())
        return snap

    def _chair_deltas(self) -> list[dict]:
        return _jsonl(self.chairs_store)

    def mint_employee(self, payload: MintPayload) -> MintResult:
        with self._lock:
            people = self._snapshot()["employee"]
            for key, value in (("MOBILE", payload.mobile), ("EMAIL", (payload.email or "").lower() or None)):
                if not value:
                    continue
                attr = key.lower()
                hit = next((e for e in people if (e.get(attr) or "").lower() == value.lower()), None)
                if hit:
                    return MintResult(hit["code"], duplicate=True, matched_on=key,
                                      message=f"{key.lower()} already belongs to {hit['code']}")
            nums = [int(m.group(1)) for e in people if (m := re.fullmatch(r"EMP-(\d+)", e["code"]))]
            code = f"EMP-{max(nums, default=0) + 1:04d}"
            self._append(self.minted_store, {"code": code, "name": payload.name, "gender": payload.gender,
                                             "mobile": payload.mobile, "email": payload.email, "cadreCode": payload.cadre,
                                             "dateOfJoining": payload.date_of_joining, "isActive": True})
            self._save_hr_fields(code, payload.__dict__, payload.source or "mint")
            return MintResult(code, duplicate=False)

    def update_employee(self, employee_id: str, changes: dict, actor: str) -> EmployeeRec:
        with self._lock:
            if self.get_employee(employee_id) is None:
                raise KeyError(employee_id)
            if self._is_local_employee(employee_id):
                self._append(self.extra_store, {"employee_id": employee_id, "changes": changes, "by": actor})
            else:
                mdm = {MDM_EMPLOYEE_FIELDS[k]: v for k, v in changes.items() if k in MDM_EMPLOYEE_FIELDS}
                if mdm:
                    self._append(self.corrections_store, {"employee_id": employee_id, "changes": mdm, "by": actor})
                self._save_hr_fields(employee_id, changes, actor)
        return self.get_employee(employee_id)

    def add_sanctioned_post(self, office_id: str, post_code: str, source: str) -> SanctionedPostRec:
        with self._lock:
            self._append(self.chairs_store, {"office_id": office_id, "post_code": post_code, "delta": 1, "source": source})
            n = max(c.seq for c in self.list_sanctioned_posts()
                    if c.office_id == office_id and c.post_code == post_code and not c.derived)
            return next(c for c in self.list_sanctioned_posts() if c.sanctioned_post_id == chair_id(office_id, post_code, n))

    def abolish_sanctioned_post(self, sanctioned_post_id: str, reason: str) -> SanctionedPostRec:
        with self._lock:
            chair = self._top_chair(sanctioned_post_id)
            self._append(self.chairs_store, {"office_id": chair.office_id, "post_code": chair.post_code, "delta": -1,
                                             "reason": reason})
            return SanctionedPostRec(**{**chair.__dict__, "is_active": False})

    def validate(self, refs: dict[str, list[str]], as_on: str | None = None) -> dict:
        snap = self._snapshot()
        results, valid = {}, True
        for t, codes in refs.items():
            recs = {r["code"]: r for r in snap.get(t, [])}
            results[t] = {}
            for c in codes:
                state = "NOT_FOUND" if c not in recs else ("OK" if recs[c].get("isActive", True) else "INACTIVE")
                results[t][c] = state
                valid = valid and state == "OK"
        return {"valid": valid, "asOn": as_on, "mdmVersion": None, "results": results, "emulated": True}
