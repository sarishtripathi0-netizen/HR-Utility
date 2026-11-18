"""Shared domain plumbing: errors, effective-dated intervals, supersede, audit and outbox."""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Iterable

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..models import AuditLog, EventOutbox
from ..timeutil import iso_ist, now_utc


class DomainError(Exception):
    status = 400

    def __init__(self, message: str, rule: str | None = None):
        super().__init__(message)
        self.message = message
        self.rule = rule

    def to_dict(self) -> dict:
        return {"rule": self.rule, "message": self.message}


class RuleViolation(DomainError):
    """A business rule (BR-xx) refused the change."""

    status = 409


class NotFound(DomainError):
    status = 404


class InvalidInput(DomainError):
    status = 422


# ---------------------------------------------------------------- intervals, half-open [from, to)

def covers(frm: datetime, to: datetime | None, t: datetime) -> bool:
    return frm <= t and (to is None or t < to)


def overlaps(a_from: datetime, a_to: datetime | None, b_from: datetime, b_to: datetime | None) -> bool:
    return (b_to is None or a_from < b_to) and (a_to is None or b_from < a_to)


def merge_intervals(items: Iterable[tuple[datetime, datetime | None]]) -> list[tuple[datetime, datetime | None]]:
    out: list[list] = []
    for frm, to in sorted(items, key=lambda x: x[0]):
        if out and (out[-1][1] is None or frm <= out[-1][1]):
            if out[-1][1] is not None and (to is None or to > out[-1][1]):
                out[-1][1] = to
        else:
            out.append([frm, to])
    return [(a, b) for a, b in out]


def interval_within(frm: datetime, to: datetime | None, union: list[tuple[datetime, datetime | None]]) -> bool:
    """True if [frm, to) lies inside one interval of an already-merged union."""
    for a, b in union:
        if a <= frm and (b is None or (to is not None and to <= b)):
            return True
    return False


def describe(frm: datetime, to: datetime | None) -> str:
    from ..timeutil import fmt_ist

    return f"{fmt_ist(frm)} to {fmt_ist(to) if to else 'open'}"


# ---------------------------------------------------------------- append-only writes

def row_dict(row) -> dict:
    out = {}
    for attr in inspect(row).mapper.column_attrs:
        v = getattr(row, attr.key)
        if isinstance(v, datetime):
            v = iso_ist(v)
        elif isinstance(v, date):
            v = v.isoformat()
        out[attr.key] = v
    return out


def audit(s: Session, actor: str, action: str, entity: str, entity_id: Any, before: dict | None, after: dict | None) -> None:
    s.add(AuditLog(ts=now_utc(), actor=actor, action=action, entity=entity, entity_id=str(entity_id),
                   before_json=json.dumps(before, default=str) if before is not None else None,
                   after_json=json.dumps(after, default=str) if after is not None else None))


def emit(s: Session, type_: str, payload: dict, effective_at: datetime) -> None:
    payload = {**payload, "effective_at": iso_ist(effective_at)}
    s.add(EventOutbox(ts=now_utc(), type=type_, effective_at=effective_at,
                      payload_json=json.dumps(payload, default=str), delivered=False))


def insert(s: Session, row, actor: str, action: str) -> Any:
    """A new record starts its own lineage (lineage_id null = 'my own id'); versions copy it."""
    s.add(row)
    s.flush()
    audit(s, actor, action, row.__tablename__, row.id, None, row_dict(row))
    return row


def lineage_of(row) -> int:
    return row.lineage_id or row.id


def supersede(s: Session, old, actor: str, action: str, **changes):
    """BR-10: never edit; write the corrected version and point the old row at it."""
    if old.superseded_by is not None:
        raise RuleViolation(f"{old.__tablename__} {old.id} was already superseded by {old.superseded_by}", "BR-10")
    data = {k: v for k, v in row_dict_raw(old).items() if k not in ("id", "superseded_by", "created_at")}
    data["lineage_id"] = lineage_of(old)
    data.update(changes)
    new = type(old)(**data, created_at=now_utc())
    s.add(new)
    s.flush()
    old.superseded_by = new.id
    s.flush()
    audit(s, actor, action, old.__tablename__, new.id, row_dict(old), row_dict(new))
    return new


def row_dict_raw(row) -> dict:
    return {attr.key: getattr(row, attr.key) for attr in inspect(row).mapper.column_attrs}


def require(value, message: str, rule: str | None = None):
    if value is None or (isinstance(value, str) and not value.strip()):
        raise InvalidInput(message, rule)
    return value
