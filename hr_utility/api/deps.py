"""Request plumbing shared by routers: sessions, settings, ?at= parsing, row serialisers."""
from __future__ import annotations

from datetime import datetime

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..domain import queries as q
from ..domain.common import InvalidInput
from ..timeutil import iso_ist, parse_at


def get_session(request: Request):
    with request.app.state.db.session() as s:
        yield s


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_mdm(request: Request):
    return request.app.state.mdm


def at_param(value: str | None, *, end_of_day: bool = False, name: str = "at") -> datetime:
    try:
        return parse_at(value, end_of_day=end_of_day)
    except ValueError as e:
        raise InvalidInput(f"'{name}' must be an ISO-8601 date or timestamp, got '{value}' ({e})")


def required_ts(value: str | None, name: str) -> datetime:
    if value is None or not str(value).strip():
        raise InvalidInput(f"'{name}' is required")
    return at_param(value, name=name)


def posting_out(s: Session, p) -> dict:
    return {"id": p.id, "lineage_id": p.lineage_id or p.id, "employee_id": p.employee_id,
            "is_demo": bool(q.employee(s, p.employee_id).is_demo), "sanctioned_post_id": p.sanctioned_post_id,
            "charge_type": p.charge_type, "effective_from": iso_ist(p.effective_from),
            "effective_to": iso_ist(p.effective_to), "order_ref": p.order_ref,
            "issuing_department": p.issuing_department, "entered_by": p.entered_by, "note": p.note}


def allot_out(s: Session, fa) -> dict:
    return {"id": fa.id, "lineage_id": fa.lineage_id or fa.id, "employee_id": fa.employee_id,
            "is_demo": bool(fa.is_demo or q.employee(s, fa.employee_id).is_demo), "office_id": fa.office_id,
            "function_code": fa.function_code, "effective_from": iso_ist(fa.effective_from),
            "effective_to": iso_ist(fa.effective_to), "entered_by": fa.entered_by}


def availability_out(s: Session, a) -> dict:
    return {"id": a.id, "lineage_id": a.lineage_id or a.id, "employee_id": a.employee_id,
            "is_demo": bool(q.employee(s, a.employee_id).is_demo), "kind": a.kind, "from_ts": iso_ist(a.from_ts),
            "to_ts": iso_ist(a.to_ts), "entered_by": a.entered_by, "note": a.note}
