"""Postings: join (BR-01, BR-02), relieve (BR-03) and declare-vacant."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import FunctionAllotment, Posting, VacancyDeclaration
from ..timeutil import fmt_ist, now_utc
from . import queries as q
from .common import InvalidInput, RuleViolation, describe, emit, insert, overlaps, require, supersede

CHARGE_TYPES = ("SUBSTANTIVE", "ADDITIONAL")
log = logging.getLogger(__name__)


@dataclass
class JoinRequest:
    employee_id: str
    sanctioned_post_id: str
    charge_type: str
    effective_from: datetime
    order_ref: str
    issuing_department: str
    entered_by: str
    effective_to: datetime | None = None
    note: str | None = None


def _event_names(charge_type: str) -> tuple[str, str]:
    return ("posting.started", "posting.ended") if charge_type == "SUBSTANTIVE" else ("charge.started", "charge.ended")


def _payload(p: Posting, s: Session) -> dict:
    sp = q.chair(s, p.sanctioned_post_id)
    return {"posting_id": p.id, "lineage_id": p.lineage_id or p.id, "employee_id": p.employee_id,
            "sanctioned_post_id": p.sanctioned_post_id, "office_id": sp.office_id, "post_code": sp.post_code,
            "charge_type": p.charge_type, "order_ref": p.order_ref, "issuing_department": p.issuing_department}


def check_with_mdm(s: Session, mdm, emp, sp, at: datetime) -> None:
    """MDM's live check before saving a posting: the office, designation and employee must be active in MDM on the
    date. Local records (demo officers, offices MDM lacks) are not sent. If MDM cannot be reached the posting is
    saved on the last copy (it was validated against that copy) and a warning is logged."""
    if mdm is None or not hasattr(mdm, "validate"):
        return
    office = q.office(s, sp.office_id)
    refs = {"designation": [sp.post_code]}
    if not office.provisional:
        refs["office"] = [office.office_id]
    if not emp.employee_id.startswith("DEMO-"):
        refs["employee"] = [emp.employee_id]
    try:
        res = mdm.validate(refs, at.date().isoformat())
    except Exception as e:  # noqa: BLE001 - MDM down: the local copy already checked these codes
        log.warning("MDM validate unavailable (%s); saved against the local copy", e)
        return
    if res and not res.get("valid", True):
        bad = [f"{t} {code}: {state}" for t, codes in res.get("results", {}).items() for code, state in codes.items()
               if state != "OK"]
        raise RuleViolation(f"MDM does not accept this posting on {fmt_ist(at)}: {', '.join(bad)}.", "MDM")


def join(s: Session, req: JoinRequest, actor: str | None = None, mdm=None) -> Posting:
    actor = actor or req.entered_by
    emp = q.employee(s, req.employee_id)
    sp = q.chair(s, req.sanctioned_post_id)
    if not sp.is_active:
        raise RuleViolation(f"{sp.sanctioned_post_id} is abolished; MDM no longer sanctions it.", "MDM")
    check_with_mdm(s, mdm, emp, sp, req.effective_from)
    if req.charge_type not in CHARGE_TYPES:
        raise InvalidInput(f"charge_type must be one of {CHARGE_TYPES}")
    require(req.order_ref, "order_ref is required: every posting cites the transfer order")
    require(req.issuing_department, "issuing_department is required: the cadre-controlling department that issued the order")
    require(req.entered_by, "entered_by is required")
    if req.effective_to is not None and req.effective_to <= req.effective_from:
        raise InvalidInput("effective_to must be after effective_from")

    for other in q.current_postings(s, sanctioned_post_id=sp.sanctioned_post_id):
        if not overlaps(req.effective_from, req.effective_to, other.effective_from, other.effective_to):
            continue
        if other.employee_id == emp.employee_id:
            raise RuleViolation(
                f"{emp.name} already holds {sp.sanctioned_post_id} ({other.charge_type.lower()}) "
                f"for {describe(other.effective_from, other.effective_to)}.", "BR-01")
        if req.charge_type == "SUBSTANTIVE" and other.charge_type == "SUBSTANTIVE":
            holder = q.employee(s, other.employee_id)
            raise RuleViolation(
                f"{sp.sanctioned_post_id} already has a substantive holder, {holder.name}, for "
                f"{describe(other.effective_from, other.effective_to)}. A post has at most one substantive "
                f"holder at any instant: relieve {holder.name} first, or post {emp.name} on additional charge.",
                "BR-01")
    if req.charge_type == "SUBSTANTIVE":
        for other in q.current_postings(s, employee_id=emp.employee_id):
            if other.charge_type == "SUBSTANTIVE" and overlaps(req.effective_from, req.effective_to,
                                                                other.effective_from, other.effective_to):
                raise RuleViolation(
                    f"{emp.name} already holds a substantive posting at {other.sanctioned_post_id} for "
                    f"{describe(other.effective_from, other.effective_to)}. Substantive postings of one officer "
                    f"never overlap: relieve that posting first, or use an additional charge.", "BR-02")

    vac = q.vacancy_at(s, sp.sanctioned_post_id, req.effective_from)
    if vac is not None:
        supersede(s, vac, actor, "VACANCY_CLOSED", to_ts=req.effective_from)

    p = insert(s, Posting(
        employee_id=emp.employee_id, sanctioned_post_id=sp.sanctioned_post_id, charge_type=req.charge_type,
        effective_from=req.effective_from, effective_to=req.effective_to, order_ref=req.order_ref.strip(),
        issuing_department=req.issuing_department.strip(), entered_by=req.entered_by, note=req.note,
        created_at=now_utc(),
    ), actor, "POSTING_JOIN")
    started, ended = _event_names(p.charge_type)
    emit(s, started, _payload(p, s), p.effective_from)
    if p.effective_to is not None:
        emit(s, ended, _payload(p, s), p.effective_to)
    return p


def _close_posting(s: Session, p: Posting, at: datetime, actor: str, action: str, extra: dict | None = None) -> Posting:
    if at <= p.effective_from:
        raise InvalidInput(f"Relieving time {fmt_ist(at)} must be after the posting began ({fmt_ist(p.effective_from)}).")
    if p.effective_to is not None and p.effective_to <= at:
        raise InvalidInput(f"Posting {p.id} already ended at {fmt_ist(p.effective_to)}.")
    new = supersede(s, p, actor, action, effective_to=at)
    emit(s, _event_names(new.charge_type)[1], {**_payload(new, s), **(extra or {})}, at)
    _close_orphan_allotments(s, new, at, actor)
    return new


def _close_orphan_allotments(s: Session, ended: Posting, at: datetime, actor: str) -> None:
    """BR-04 keeps holding: once an officer has no posting left in an office, their functions there end."""
    office_id = q.chair(s, ended.sanctioned_post_id).office_id
    still_there = [p for p in q.current_postings(s, employee_id=ended.employee_id, office_id=office_id)
                   if p.effective_to is None or p.effective_to > at]
    if any(p.effective_from <= at for p in still_there):
        return
    for fa in s.query(FunctionAllotment).filter(
        FunctionAllotment.employee_id == ended.employee_id, FunctionAllotment.office_id == office_id,
        FunctionAllotment.superseded_by.is_(None),
    ).all():
        if fa.effective_to is not None and fa.effective_to <= at:
            continue
        if fa.effective_from >= at:
            new = supersede(s, fa, actor, "FUNCTION_WITHDRAWN_ON_RELIEF", effective_to=fa.effective_from)
        else:
            new = supersede(s, fa, actor, "FUNCTION_WITHDRAWN_ON_RELIEF", effective_to=at)
        emit(s, "function.withdrawn", {"allotment_id": new.id, "employee_id": new.employee_id, "office_id": office_id,
                                       "function_code": new.function_code, "reason": "officer relieved from office"}, at)


@dataclass
class Successor:
    employee_id: str
    charge_type: str
    order_ref: str
    issuing_department: str
    note: str | None = None


def relieve(s: Session, posting_id: int, at: datetime, entered_by: str, successor: Successor | None = None,
            note: str | None = None, mdm=None) -> dict:
    """End a posting. BR-03: a substantive posting ends only if, at the same instant, a successor joins or an
    additional charge on the same post begins. Returns the ended posting and the successor's posting."""
    require(entered_by, "entered_by is required")
    p = q.latest_version(s, Posting, posting_id)
    sp = q.chair(s, p.sanctioned_post_id)
    holder = q.employee(s, p.employee_id)

    if p.charge_type == "SUBSTANTIVE" and successor is None:
        handover = [o for o in q.current_postings(s, sanctioned_post_id=sp.sanctioned_post_id)
                    if o.id != p.id and o.effective_from == at]
        if not handover:
            raise RuleViolation(
                f"Cannot relieve {holder.name} from {sp.sanctioned_post_id} at {fmt_ist(at)}: the post would be left "
                f"with no one in charge. Name a successor who joins at the same time, start an additional charge "
                f"on this post at the same time, or declare the post vacant with a reason.", "BR-03")

    ended = _close_posting(s, p, at, entered_by, "POSTING_RELIEVE", {"relieved_by_successor": successor is not None})
    new = None
    if successor is not None:
        new = join(s, JoinRequest(
            employee_id=successor.employee_id, sanctioned_post_id=sp.sanctioned_post_id,
            charge_type=successor.charge_type, effective_from=at, order_ref=successor.order_ref,
            issuing_department=successor.issuing_department, entered_by=entered_by, note=successor.note,
        ), mdm=mdm)
    return {"ended": ended, "successor": new}


CORRECTABLE = ("order_ref", "issuing_department", "note")


def correct(s: Session, posting_id: int, entered_by: str, **changes) -> Posting:
    """Correct the paperwork on a posting (order reference, issuing department, note). Dates are changed by relieving
    or by a new posting, so the BR-01..03 checks always apply. The old version is kept (BR-10)."""
    require(entered_by, "entered_by is required")
    changes = {k: v for k, v in changes.items() if v is not None}
    bad = set(changes) - set(CORRECTABLE)
    if bad:
        raise InvalidInput(f"cannot correct {sorted(bad)}; relieve the posting or enter a new one instead")
    if not changes:
        raise InvalidInput("nothing to correct")
    for k in ("order_ref", "issuing_department"):
        if k in changes:
            require(changes[k], f"{k} cannot be empty")
            changes[k] = changes[k].strip()
    p = q.latest_version(s, Posting, posting_id)
    return supersede(s, p, entered_by, "POSTING_CORRECT", **changes)


def declare_vacant(s: Session, sanctioned_post_id: str, at: datetime, reason: str, entered_by: str) -> dict:
    """The only exception to BR-03: an explicit, reasoned, audited vacancy."""
    require(reason, "A reason is required to declare a post vacant", "BR-03")
    require(entered_by, "entered_by is required")
    sp = q.chair(s, sanctioned_post_id)
    if q.vacancy_at(s, sp.sanctioned_post_id, at) is not None:
        raise RuleViolation(f"{sp.sanctioned_post_id} is already declared vacant at {fmt_ist(at)}", "BR-03")
    ended = []
    for p in q.postings_at(s, at, sanctioned_post_id=sp.sanctioned_post_id):
        if p.charge_type == "SUBSTANTIVE" and p.effective_from < at:
            ended.append(_close_posting(s, p, at, entered_by, "POSTING_END_DECLARED_VACANT",
                                        {"declared_vacant": True, "vacancy_reason": reason}))
    future = [o for o in q.current_postings(s, sanctioned_post_id=sp.sanctioned_post_id)
              if o.charge_type == "SUBSTANTIVE" and o.effective_from >= at]
    vac = insert(s, VacancyDeclaration(
        sanctioned_post_id=sp.sanctioned_post_id, from_ts=at,
        to_ts=min(o.effective_from for o in future) if future else None,
        reason=reason.strip(), entered_by=entered_by, created_at=now_utc(),
    ), entered_by, "DECLARE_VACANT")
    return {"vacancy": vac, "ended": ended}
