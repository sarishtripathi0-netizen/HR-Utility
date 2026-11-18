"""Availability windows: leave, tour, training, deputation (BR-06)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Availability
from ..timeutil import now_utc
from . import queries as q
from .common import InvalidInput, RuleViolation, describe, emit, insert, overlaps, require, supersede

KINDS = ("LEAVE", "TOUR", "TRAINING", "DEPUTATION")


def _payload(a: Availability) -> dict:
    return {"availability_id": a.id, "lineage_id": a.lineage_id or a.id, "employee_id": a.employee_id, "kind": a.kind}


def record(s: Session, employee_id: str, kind: str, from_ts: datetime, to_ts: datetime | None, entered_by: str,
           note: str | None = None, supersedes_id: int | None = None) -> Availability:
    """Record a window in which the officer is away. A correction passes supersedes_id; both rows are kept."""
    emp = q.employee(s, employee_id)
    require(entered_by, "entered_by is required")
    if kind not in KINDS:
        raise InvalidInput(f"kind must be one of {KINDS}")
    if to_ts is not None and to_ts <= from_ts:
        raise InvalidInput("to_ts must be after from_ts")
    old = q.latest_version(s, Availability, supersedes_id) if supersedes_id else None
    if old is not None and old.employee_id != emp.employee_id:
        raise InvalidInput("A correction must be for the same employee")

    for other in s.scalars(select(Availability).where(
        Availability.employee_id == emp.employee_id, Availability.kind == kind, Availability.superseded_by.is_(None),
    )):
        if old is not None and other.id == old.id:
            continue
        if overlaps(from_ts, to_ts, other.from_ts, other.to_ts):
            raise RuleViolation(
                f"{emp.name} already has a {kind.lower()} window for {describe(other.from_ts, other.to_ts)}; windows of "
                f"the same kind must not overlap. Correct that entry instead.", "BR-06")

    a = insert(s, Availability(employee_id=emp.employee_id, kind=kind, from_ts=from_ts, to_ts=to_ts,
                               entered_by=entered_by, note=note, lineage_id=(old.lineage_id or old.id) if old else None,
                               created_at=now_utc()), entered_by, "AVAILABILITY_CORRECT" if old else "AVAILABILITY_ADD")
    if old is not None:
        old.superseded_by = a.id
        s.flush()
    emit(s, "availability.started", _payload(a), a.from_ts)
    if a.to_ts is not None:
        emit(s, "availability.ended", _payload(a), a.to_ts)
    return a


def cancel(s: Session, availability_id: int, entered_by: str, reason: str) -> Availability:
    """Cancel a window entered in error or withdrawn: it collapses to nothing (to_ts = from_ts). Both rows are kept."""
    require(entered_by, "entered_by is required")
    require(reason, "A reason is required to cancel a leave / tour / training / deputation entry")
    a = q.latest_version(s, Availability, availability_id)
    if a.to_ts is not None and a.to_ts <= a.from_ts:
        raise InvalidInput(f"{a.kind.lower()} entry {a.id} is already cancelled")
    new = supersede(s, a, entered_by, "AVAILABILITY_CANCEL", to_ts=a.from_ts,
                    note=f"CANCELLED: {reason.strip()}" + (f" (was: {a.note})" if a.note else ""))
    emit(s, "availability.ended", {**_payload(new), "cancelled": True}, max(a.from_ts, now_utc()))
    return new
