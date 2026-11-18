"""The core question: which chairs of post P in office O are held at t by an officer holding function F,
is that officer available, and if none is, who is the Link Officer?

A seat (designation x office) never falls back to another office here; that is the Rule Engine's job.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..config import Settings
from ..timeutil import fmt_ist, iso_ist
from . import link_officer
from . import queries as q
from .common import NotFound


def seat_holders(s: Session, settings: Settings, office_id: str, post_code: str, function_code: str | None,
                 t: datetime) -> dict:
    office = q.office(s, office_id)
    post_code = q.post(s, post_code).post_code  # accepts MDM short names (AC, CO, DC ...)
    if not settings.roster_mode:
        if not function_code:
            raise NotFound("function_code is required (allocation by function, Option A)")
        if q.function_code(s, function_code) is None:
            raise NotFound(f"Function code {function_code} is not in MDM")

    holders = []
    for p in q.postings_at(s, t, office_id=office.office_id):
        chair = q.chair(s, p.sanctioned_post_id)
        if chair.post_code != post_code:
            continue
        if not settings.roster_mode and not q.holds_function(s, p.employee_id, office.office_id, function_code, t):
            continue
        emp = q.employee(s, p.employee_id)
        available, why = q.availability_at(s, emp.employee_id, t)
        holders.append((emp, chair, p, available, why))
    holders.sort(key=lambda h: (q.seniority_key(h[0]), h[1].sanctioned_post_id))

    out = {
        "office_id": office.office_id, "post_code": post_code, "function_code": function_code, "at": iso_ist(t),
        "holders": [{
            "sanctioned_post_id": chair.sanctioned_post_id, "employee_id": emp.employee_id, "name": emp.name,
            "cadre": emp.cadre, "year_of_joining": emp.year_of_joining, "charge_type": p.charge_type,
            "available": available, "unavailable_reason": why, "is_demo": bool(emp.is_demo),
        } for emp, chair, p, available, why in holders],
        "link_officer": None, "status": "RESOLVED", "reason": None,
        "roster_mode": settings.roster_mode,
    }
    if not holders:
        what = f"holds post {post_code}" if settings.roster_mode else f"of post {post_code} holds function {function_code}"
        out["status"] = "NO_HOLDER"
        out["reason"] = f"No officer {what} in {office.office_id} at {fmt_ist(t)}."
        return out
    if any(h[3] for h in holders):
        return out

    first_chair = holders[0][1]
    res = link_officer.resolve(s, settings, first_chair.sanctioned_post_id, t,
                               absent_employee_ids={h[0].employee_id for h in holders})
    if res.status == "RESOLVED":
        out["link_officer"] = res.link_officer()
    else:
        out["status"] = "NO_LINK_OFFICER"
        out["reason"] = f"Every holder is unavailable. {res.reason}"
    return out
