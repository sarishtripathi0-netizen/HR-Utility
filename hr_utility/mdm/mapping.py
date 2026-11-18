"""Mapping MDM PoC payloads to the HR Utility's MDM record types. Shared by the seed builder (offline snapshots)
and HttpMdmClient (live), so both produce identical cache rows."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .client import HolidayRec, MdmDesignationRec, OfficeRec

# Entity types the HR Utility copies from MDM, parent-first (MDM integration guide, "HR Utility contract").
SNAPSHOT_TYPES = ("department", "cadre", "district", "office-type", "function", "office-type-function", "designation",
                  "office", "sanctioned-post", "designation-function", "link-officer-rule", "employee", "holiday")
# Types whose version change triggers a cache refresh.
WATCHED_TYPES = ("cadre", "district", "office-type", "function", "office-type-function", "designation", "office",
                 "sanctioned-post", "designation-function", "link-officer-rule", "employee", "holiday")


def load_mdm_config(data_dir: Path) -> dict:
    path = Path(data_dir) / "config" / "mdm.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def office_unit_name(name: str, cfg: dict) -> str:
    """'Office of the Circle Officer, Tihu' -> 'Tihu'; 'Azara Revenue Circle Office' -> 'Azara'."""
    s = name.strip()
    for p in cfg.get("office_name_prefixes", []):
        if s.lower().startswith(p.lower()):
            s = s[len(p):]
    for suf in cfg.get("office_name_suffixes", []):
        if s.lower().endswith(suf.lower()):
            s = s[: -len(suf)]
    return re.sub(r"\s+", " ", s).strip(" ,")


def office_rec(r: dict, external_ref: str | None = None) -> OfficeRec:
    code = r["code"]
    return OfficeRec(
        office_id=code, name=r["name"], office_type=r["officeTypeCode"], district_code=r.get("districtCode") or "",
        district_name=r.get("districtName"), parent_office_id=r.get("parentOfficeCode"),
        establishment_actor=f"ESTB@{code}", provisional=False,
        source=f"MDM office {code} (mdmVersion {r.get('mdmVersion')})", external_ref=external_ref,
        is_active=bool(r.get("isActive", True)), mdm_id=r.get("id"),
    )


def holiday_rec(r: dict) -> HolidayRec:
    return HolidayRec(holiday_date=r["date"], name=r["name"], source=f"MDM holiday {r['code']}", code=r["code"],
                      holiday_type=r.get("holidayType"), district_code=r.get("districtCode"),
                      is_active=bool(r.get("isActive", True)))


def designation_rec(r: dict) -> MdmDesignationRec:
    return MdmDesignationRec(code=r["code"], name=r["name"], level=r.get("level"),
                             department_code=r.get("departmentCode"), is_active=bool(r.get("isActive", True)),
                             mdm_id=r.get("id"))


def snapshot_records(body: dict) -> list[dict]:
    return body.get("records", body.get("items", []))
