"""Read models: the holder of a chair, an office roster, and every post an employee holds (incl. link charges)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import MdmFunctionCode, MdmOfficeTypeFunction, MdmPost, MdmPostFunctionRule
from ..timeutil import iso_ist
from . import link_officer
from . import queries as q


def _holder_entry(s: Session, p, office_id: str, t: datetime) -> dict:
    emp = q.employee(s, p.employee_id)
    available, why = q.availability_at(s, emp.employee_id, t)
    window = q.absence_at(s, emp.employee_id, t)
    return {
        **q.employee_view(emp), "posting_id": p.id, "charge_type": p.charge_type,
        "since": iso_ist(p.effective_from), "until": iso_ist(p.effective_to), "order_ref": p.order_ref,
        "issuing_department": p.issuing_department, "available": available, "unavailable_reason": why,
        "unavailable_until": iso_ist(window.to_ts) if window else None,
        "functions": q.functions_at(s, emp.employee_id, office_id, t),
        "functions_allotted": q.allotted_functions_at(s, emp.employee_id, office_id, t),
        "holds_all_office_functions": q.holds_all_office_functions(s, emp.employee_id, office_id, t),
    }


def function_catalogue(s: Session, office_type: str | None = None) -> dict:
    """Which functions exist in each office type, and how each post holds them. MDM reference data."""
    names = {f.code: f for f in s.scalars(select(MdmFunctionCode))}
    by_type: dict[str, list] = {}
    for row in s.scalars(select(MdmOfficeTypeFunction).order_by(MdmOfficeTypeFunction.office_type,
                                                                 MdmOfficeTypeFunction.function_code)):
        if office_type and row.office_type != office_type:
            continue
        f = names.get(row.function_code)
        by_type.setdefault(row.office_type, []).append({
            "function_code": row.function_code, "name": f.name if f else row.function_code,
            "category": f.category if f else None, "is_demo": bool(row.is_demo)})
    rules = []
    for p in s.scalars(select(MdmPost).order_by(MdmPost.rank_order, MdmPost.post_code)):
        rule = s.get(MdmPostFunctionRule, p.post_code)
        rules.append({"post_code": p.post_code, "post_name": p.name, "rank_order": p.rank_order,
                      "mode": rule.mode if rule else "ALLOTTED", "is_demo": bool(rule.is_demo) if rule else False,
                      "basis": rule.source if rule else "no rule configured; functions are allotted"})
    return {"office_types": [{"office_type": k, "functions": v} for k, v in by_type.items()], "post_rules": rules}


def chair_holder(s: Session, settings: Settings, sanctioned_post_id: str, t: datetime, with_link: bool = True) -> dict:
    sp = q.chair(s, sanctioned_post_id)
    holders = [_holder_entry(s, p, sp.office_id, t) for p in q.postings_at(s, t, sanctioned_post_id=sp.sanctioned_post_id)]
    vac = q.vacancy_at(s, sp.sanctioned_post_id, t)
    out = {
        "sanctioned_post_id": sp.sanctioned_post_id, "office_id": sp.office_id, "post_code": sp.post_code,
        "rank_order": q.rank_of_chair(s, sp), "derived": bool(sp.derived), "at": iso_ist(t),
        "status": "HELD" if holders else ("DECLARED_VACANT" if vac else "UNHELD"),
        "holders": holders,
        "vacancy": {"since": iso_ist(vac.from_ts), "reason": vac.reason, "entered_by": vac.entered_by} if vac else None,
        "link_officer": None,
    }
    if with_link and not any(h["available"] for h in holders):
        res = link_officer.resolve(s, settings, sp.sanctioned_post_id, t)
        out["link_officer"] = res.link_officer()
        out["link_status"] = res.status
        out["link_reason"] = res.reason
    return out


def office_roster(s: Session, settings: Settings, office_id: str, t: datetime) -> dict:
    office = q.office(s, office_id)
    chairs = [chair_holder(s, settings, c.sanctioned_post_id, t) for c in q.chairs_in_office(s, office.office_id)]
    return {
        "office_id": office.office_id, "name": office.name, "office_type": office.office_type,
        "district_code": office.district_code, "district_name": office.district_name,
        "parent_office_id": office.parent_office_id, "provisional_id": bool(office.provisional),
        "external_ref": office.external_ref,
        "establishment_actor": office.establishment_actor, "at": iso_ist(t), "chairs": chairs,
    }


def employee_posts(s: Session, settings: Settings, employee_id: str, t: datetime) -> dict:
    """Substantive and additional charges held at t, plus link charges resolved under BR-07. Used by IAM."""
    emp = q.employee(s, employee_id)
    available, why = q.availability_at(s, emp.employee_id, t)
    posts = []
    offices = set()
    for p in q.postings_at(s, t, employee_id=emp.employee_id):
        sp = q.chair(s, p.sanctioned_post_id)
        offices.add(sp.office_id)
        posts.append({"sanctioned_post_id": sp.sanctioned_post_id, "office_id": sp.office_id, "post_code": sp.post_code,
                      "charge_type": p.charge_type, "posting_id": p.id, "since": iso_ist(p.effective_from),
                      "until": iso_ist(p.effective_to)})
    held = {x["sanctioned_post_id"] for x in posts}
    if available:
        for office_id in sorted(offices):
            for chair in q.chairs_in_office(s, office_id):
                if chair.sanctioned_post_id in held:
                    continue
                res = link_officer.resolve(s, settings, chair.sanctioned_post_id, t)
                if res.status == "RESOLVED" and res.employee.employee_id == emp.employee_id:
                    posts.append({"sanctioned_post_id": chair.sanctioned_post_id, "office_id": office_id,
                                  "post_code": chair.post_code, "charge_type": "LINK", "rule_step": res.rule_step,
                                  "deemed_dps_under_rule_3_3": True,
                                  "covering_for": [{"employee_id": a["employee_id"], "name": a["name"],
                                                    "unavailable_reason": a["unavailable_reason"], "is_demo": a["is_demo"]}
                                                   for a in res.absent]})
    order = {"SUBSTANTIVE": 0, "ADDITIONAL": 1, "LINK": 2}
    posts.sort(key=lambda x: (order[x["charge_type"]], x["sanctioned_post_id"]))
    return {**q.employee_view(emp), "at": iso_ist(t), "available": available, "unavailable_reason": why, "posts": posts}
