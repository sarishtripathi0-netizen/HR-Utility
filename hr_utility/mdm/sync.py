"""Copy MDM data into the read-only mdm_cache_* tables, and keep that copy fresh. Works with any MdmClient."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    MdmCadre,
    MdmDesignation,
    MdmDesignationFunction,
    MdmEmployee,
    MdmFunctionCode,
    MdmHoliday,
    MdmLinkOfficerRule,
    MdmOffice,
    MdmOfficeTypeFunction,
    MdmPost,
    MdmPostFunctionRule,
    MdmSanctionedPost,
    MdmSyncState,
)
from ..timeutil import now_utc
from .client import EmployeeRec, MdmClient

log = logging.getLogger(__name__)


def refresh_cache(s: Session, client: MdmClient) -> dict[str, int]:
    """Upsert every MDM record into the cache. Rows are never deleted: a chair MDM no longer sanctions stays with
    is_active false, so postings to it keep their history."""
    counts = {}
    holidays = [replace(h, code=h.code or h.holiday_date) for h in client.list_holidays()]
    rules = client.list_link_rules()
    chairs = client.list_sanctioned_posts()
    for model, records in (
        (MdmOffice, client.list_offices()),
        (MdmPost, client.list_posts()),
        (MdmFunctionCode, client.list_function_codes()),
        (MdmOfficeTypeFunction, client.list_office_type_functions()),
        (MdmPostFunctionRule, client.list_post_function_rules()),
        (MdmDesignationFunction, client.list_designation_functions()),
        (MdmCadre, client.list_cadres()),
        (MdmDesignation, client.list_mdm_designations()),
        (MdmSanctionedPost, chairs),
        (MdmEmployee, client.list_employees()),
        (MdmHoliday, holidays),
    ):
        for rec in records:
            s.merge(model(**asdict(rec)))
        counts[model.__tablename__] = len(records)
    for rec in rules:
        s.merge(MdmLinkOfficerRule(code=rec.code, office_type=rec.office_type, post_code=rec.post_code,
                                   covering_post_code=rec.covering_post_code, priority=rec.priority,
                                   required_function=rec.required_function, source=rec.source))
    counts["mdm_cache_link_officer_rule"] = len(rules)
    live_rules = {r.code for r in rules}
    for row in s.scalars(select(MdmLinkOfficerRule)):  # a rule MDM dropped no longer applies
        if row.code not in live_rules:
            s.delete(row)
    live = {c.sanctioned_post_id for c in chairs}
    for row in s.scalars(select(MdmSanctionedPost).where(MdmSanctionedPost.is_active.is_(True))):
        if row.sanctioned_post_id not in live:
            row.is_active = False
    s.flush()
    return counts


def cache_employee(s: Session, rec: EmployeeRec) -> MdmEmployee:
    row = s.merge(MdmEmployee(**asdict(rec)))
    s.flush()
    return row


def sync_state(s: Session) -> MdmSyncState | None:
    return s.get(MdmSyncState, 1)


def record_sync(s: Session, source: str, versions: dict | None, error: str | None = None, synced: bool = False) -> MdmSyncState:
    st = sync_state(s) or MdmSyncState(id=1, source=source)
    st.source = source
    st.last_checked_at = now_utc()
    st.last_error = error
    if versions is not None and synced:
        st.applied_version = versions.get("global")
        st.versions_json = json.dumps(versions.get("entities", {}))
        st.last_synced_at = st.last_checked_at
    s.merge(st)
    s.flush()
    return st


def ensure_fresh(s: Session, client, watched: tuple[str, ...]) -> dict:
    """The MDM guide's version check: compare MDM's per-entity versions with what was applied; refresh the cache
    when any watched type moved. If MDM is unreachable, keep serving the last copy and record the error."""
    source = getattr(client, "base_url", "SEED")
    if not hasattr(client, "version"):
        return {"status": "LOCAL_ONLY"}
    try:
        remote = client.version()
    except Exception as e:  # noqa: BLE001 - any transport failure means "stale but usable"
        log.warning("MDM version check failed: %s", e)
        record_sync(s, source, None, error=f"{type(e).__name__}: {e}")
        return {"status": "STALE", "error": str(e)}
    st = sync_state(s)
    applied = json.loads(st.versions_json) if st and st.versions_json else {}
    moved = [t for t in watched if remote.get("entities", {}).get(t) != applied.get(t)]
    if not moved and st and st.source == source:
        record_sync(s, source, remote)
        return {"status": "FRESH", "version": remote.get("global")}
    try:
        counts = refresh_cache(s, client)
    except Exception as e:  # noqa: BLE001
        log.warning("MDM refresh failed: %s", e)
        record_sync(s, source, None, error=f"{type(e).__name__}: {e}")
        return {"status": "STALE", "error": str(e)}
    record_sync(s, source, remote, synced=True)
    return {"status": "REFRESHED", "version": remote.get("global"), "moved": moved, "counts": counts}
