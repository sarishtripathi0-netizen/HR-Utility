"""Officers: search, the full record of one officer, and corrections to the golden record (via MDM)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..mdm.client import MdmClient
from ..mdm.sync import cache_employee
from ..models import AuditLog, Availability, FunctionAllotment, MdmEmployee, MdmSanctionedPost, OnboardingRequest, Posting
from ..timeutil import iso_ist
from . import queries as q
from .common import InvalidInput, NotFound, audit, covers, row_dict

# MDM fields (name, gender, mobile, email, cadre, date of joining) are corrected in MDM; year of joining, DOB and
# retirement date are HR-held until MDM has them.
CORRECTABLE = ("name", "gender", "cadre", "date_of_joining", "year_of_joining", "date_of_birth", "date_of_retirement",
               "email", "mobile")


def search(s: Session, t: datetime, text: str | None = None, office_id: str | None = None,
           include_demo: bool = True, limit: int = 200) -> list[dict]:
    query = select(MdmEmployee)
    if text:
        like = f"%{text.strip()}%"
        query = query.where(or_(MdmEmployee.name.ilike(like), MdmEmployee.employee_id.ilike(like),
                                MdmEmployee.email.ilike(like), MdmEmployee.mobile.ilike(like)))
    if not include_demo:
        query = query.where(MdmEmployee.is_demo.is_(False))
    if office_id:
        ids = {p.employee_id for p in q.postings_at(s, t, office_id=office_id)}
        query = query.where(MdmEmployee.employee_id.in_(ids))
    out = []
    for e in sorted(s.scalars(query), key=q.seniority_key)[:limit]:
        posts = [p.sanctioned_post_id for p in q.postings_at(s, t, employee_id=e.employee_id)]
        available, why = q.availability_at(s, e.employee_id, t)
        out.append({**q.employee_view(e), "email": e.email, "mobile": e.mobile, "posts": posts,
                    "available": available, "unavailable_reason": why})
    return out


def _period(row, frm: str, to: str) -> dict:
    return {"from": iso_ist(getattr(row, frm)), "to": iso_ist(getattr(row, to))}


def detail(s: Session, employee_id: str, t: datetime) -> dict:
    e = q.employee(s, employee_id)
    postings = []
    for p in q.current_postings(s, employee_id=e.employee_id):
        sp = q.chair(s, p.sanctioned_post_id)
        state = "CURRENT" if covers(p.effective_from, p.effective_to, t) else ("FUTURE" if p.effective_from > t else "ENDED")
        postings.append({"posting_id": p.id, "sanctioned_post_id": p.sanctioned_post_id, "office_id": sp.office_id,
                         "post_code": sp.post_code, "charge_type": p.charge_type, **_period(p, "effective_from", "effective_to"),
                         "order_ref": p.order_ref, "issuing_department": p.issuing_department, "note": p.note,
                         "state": state})
    allotments = [{"allotment_id": fa.id, "office_id": fa.office_id, "function_code": fa.function_code,
                   **_period(fa, "effective_from", "effective_to"), "is_demo": bool(fa.is_demo),
                   "current": covers(fa.effective_from, fa.effective_to, t)}
                  for fa in s.scalars(select(FunctionAllotment).where(FunctionAllotment.employee_id == e.employee_id,
                                                                      FunctionAllotment.superseded_by.is_(None))
                                      .order_by(FunctionAllotment.office_id, FunctionAllotment.function_code))]
    windows = [{"availability_id": a.id, "kind": a.kind, **_period(a, "from_ts", "to_ts"), "note": a.note,
                "entered_by": a.entered_by, "cancelled": a.to_ts is not None and a.to_ts <= a.from_ts}
               for a in s.scalars(select(Availability).where(Availability.employee_id == e.employee_id,
                                                             Availability.superseded_by.is_(None))
                                  .order_by(Availability.from_ts.desc()))]
    onboarding = [{"request_id": r.id, "status": r.status, "source": r.source, "submitted_by": r.submitted_by,
                   "created_at": iso_ist(r.created_at), "reason": r.reason}
                  for r in s.scalars(select(OnboardingRequest).where(OnboardingRequest.employee_id == e.employee_id))]
    available, why = q.availability_at(s, e.employee_id, t)
    return {"employee": {**{k: getattr(e, k) for k in ("employee_id", "name", "gender", "cadre", "date_of_joining",
                                                      "year_of_joining", "date_of_birth", "date_of_retirement", "email",
                                                      "mobile", "finassam_code", "pan")},
                         "issuing_department": q.cadre_department(s, e.cadre),
                         "has_aadhaar_hash": bool(e.aadhaar_token_hash), "is_demo": bool(e.is_demo), "source": e.source},
            "at": iso_ist(t), "available": available, "unavailable_reason": why,
            "postings": postings, "function_allotments": allotments, "availability": windows, "onboarding": onboarding}


def correct(s: Session, mdm: MdmClient, employee_id: str, changes: dict, actor: str) -> MdmEmployee:
    """Correct the golden record through MDM, then refresh the local copy. Identifiers are not editable here."""
    if not actor or not actor.strip():
        raise InvalidInput("submitted_by is required")
    changes = {k: v for k, v in changes.items() if v is not None}
    bad = set(changes) - set(CORRECTABLE)
    if bad:
        raise InvalidInput(f"cannot change {sorted(bad)} here; identifiers are corrected in MDM")
    if not changes:
        raise InvalidInput("nothing to change")
    if "name" in changes and not str(changes["name"]).strip():
        raise InvalidInput("name cannot be empty")
    before = row_dict(q.employee(s, employee_id))
    try:
        rec = mdm.update_employee(employee_id, changes, actor)
    except KeyError:
        raise NotFound(f"Employee {employee_id} is not in MDM") from None
    except ValueError as e:
        raise InvalidInput(str(e)) from None
    row = cache_employee(s, rec)
    audit(s, actor, "EMPLOYEE_CORRECT", "mdm_cache_employee", employee_id, before, row_dict(row))
    return row


def audit_trail(s: Session, entity: str | None = None, entity_id: str | None = None, actor: str | None = None,
                limit: int = 200) -> list[dict]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if entity:
        query = query.where(AuditLog.entity == entity)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)
    if actor:
        query = query.where(AuditLog.actor == actor)
    return [{"id": a.id, "ts": iso_ist(a.ts), "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id, "before_json": a.before_json, "after_json": a.after_json} for a in s.scalars(query)]


def employee_audit(s: Session, employee_id: str, limit: int = 200) -> list[dict]:
    """Audit rows about this officer: their record, postings, allotments and leave."""
    ids = {("mdm_cache_employee", employee_id)}
    for model, entity in ((Posting, "posting"), (FunctionAllotment, "function_allotment"), (Availability, "availability")):
        for rid in s.scalars(select(model.id).where(model.employee_id == employee_id)):
            ids.add((entity, str(rid)))
    rows = s.scalars(select(AuditLog).where(AuditLog.entity.in_({e for e, _ in ids})).order_by(AuditLog.id.desc()))
    out = [a for a in rows if (a.entity, a.entity_id) in ids][:limit]
    return [{"id": a.id, "ts": iso_ist(a.ts), "actor": a.actor, "action": a.action, "entity": a.entity,
             "entity_id": a.entity_id} for a in out]


def chair_list(s: Session, office_id: str, t: datetime, include_abolished: bool = False) -> list[dict]:
    q.office(s, office_id)
    query = select(MdmSanctionedPost).where(MdmSanctionedPost.office_id == office_id)
    if not include_abolished:
        query = query.where(MdmSanctionedPost.is_active.is_(True))
    out = []
    for sp in sorted(s.scalars(query), key=lambda c: (q.post(s, c.post_code).rank_order, c.post_code, c.seq)):
        holders = [{**q.employee_view(q.employee(s, p.employee_id)), "posting_id": p.id, "charge_type": p.charge_type}
                   for p in q.postings_at(s, t, sanctioned_post_id=sp.sanctioned_post_id)]
        out.append({**asdict_row(sp), "holders": holders,
                    "vacancy": bool(q.vacancy_at(s, sp.sanctioned_post_id, t))})
    return out


def asdict_row(sp: MdmSanctionedPost) -> dict:
    return {"sanctioned_post_id": sp.sanctioned_post_id, "office_id": sp.office_id, "post_code": sp.post_code,
            "seq": sp.seq, "derived": bool(sp.derived), "is_demo": bool(sp.is_demo), "is_active": bool(sp.is_active),
            "source": sp.source}


def posting_list(s: Session, t: datetime, office_id: str | None = None, employee_id: str | None = None,
                 sanctioned_post_id: str | None = None, include_ended: bool = True) -> list[dict]:
    out = []
    for p in q.current_postings(s, office_id=office_id, employee_id=employee_id, sanctioned_post_id=sanctioned_post_id):
        state = "CURRENT" if covers(p.effective_from, p.effective_to, t) else ("FUTURE" if p.effective_from > t else "ENDED")
        if state == "ENDED" and not include_ended:
            continue
        e = q.employee(s, p.employee_id)
        out.append({"posting_id": p.id, "lineage_id": p.lineage_id or p.id, "employee_id": e.employee_id, "name": e.name,
                    "is_demo": bool(e.is_demo), "sanctioned_post_id": p.sanctioned_post_id, "charge_type": p.charge_type,
                    **_period(p, "effective_from", "effective_to"), "order_ref": p.order_ref,
                    "issuing_department": p.issuing_department, "entered_by": p.entered_by, "note": p.note, "state": state})
    order = {"CURRENT": 0, "FUTURE": 1, "ENDED": 2}
    return sorted(out, key=lambda r: (order[r["state"]], r["sanctioned_post_id"], r["from"] or ""))


def availability_list(s: Session, t: datetime, office_id: str | None = None, employee_id: str | None = None) -> list[dict]:
    ids = None
    if office_id:
        ids = {p.employee_id for p in q.postings_at(s, t, office_id=office_id)}
    query = select(Availability).where(Availability.superseded_by.is_(None)).order_by(Availability.from_ts.desc())
    if employee_id:
        query = query.where(Availability.employee_id == employee_id)
    elif ids is not None:
        query = query.where(Availability.employee_id.in_(ids))
    out = []
    for a in s.scalars(query):
        e = q.employee(s, a.employee_id)
        cancelled = a.to_ts is not None and a.to_ts <= a.from_ts
        out.append({"availability_id": a.id, "employee_id": e.employee_id, "name": e.name, "is_demo": bool(e.is_demo),
                    "kind": a.kind, **_period(a, "from_ts", "to_ts"), "note": a.note, "entered_by": a.entered_by,
                    "state": "CANCELLED" if cancelled else ("CURRENT" if covers(a.from_ts, a.to_ts, t)
                                                            else ("FUTURE" if a.from_ts > t else "ENDED"))})
    return out


def onboarding_list(s: Session, limit: int = 200) -> list[dict]:
    return [{"request_id": r.id, "source": r.source, "name": r.name, "status": r.status, "employee_id": r.employee_id,
             "submitted_by": r.submitted_by, "reason": r.reason, "is_demo": bool(r.is_demo), "created_at": iso_ist(r.created_at)}
            for r in s.scalars(select(OnboardingRequest).order_by(OnboardingRequest.id.desc()).limit(limit))]
