"""Function allotment by the Establishment branch (BR-04) and effective-dated reshuffles (BR-05).

BR-05: an allotment takes effect from its effective_from and as-of queries answer accordingly.
Where pending applications go after a reshuffle is the Rule Engine's concern; nothing here routes.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FunctionAllotment
from ..timeutil import fmt_ist, now_utc
from . import queries as q
from .common import (
    InvalidInput,
    RuleViolation,
    describe,
    emit,
    insert,
    interval_within,
    merge_intervals,
    overlaps,
    require,
    supersede,
)


def _check_establishment(office, entered_by: str) -> None:
    require(entered_by, "entered_by is required", "BR-04")
    if entered_by.strip() != office.establishment_actor:
        raise RuleViolation(
            f"Only the Establishment branch of {office.office_id} ({office.establishment_actor}) may allot or "
            f"withdraw functions in that office; this entry came from '{entered_by}'.", "BR-04")


def _payload(fa: FunctionAllotment) -> dict:
    return {"allotment_id": fa.id, "lineage_id": fa.lineage_id or fa.id, "employee_id": fa.employee_id,
            "office_id": fa.office_id, "function_code": fa.function_code}


def allot(s: Session, employee_id: str, office_id: str, function_code: str, effective_from: datetime,
          entered_by: str, effective_to: datetime | None = None, *, is_demo: bool = False,
          source_ref: str | None = None, actor: str | None = None) -> FunctionAllotment:
    office = q.office(s, office_id)
    emp = q.employee(s, employee_id)
    _check_establishment(office, entered_by)
    if q.function_code(s, function_code) is None:
        raise RuleViolation(f"Function code '{function_code}' does not exist in the MDM code list.", "BR-04")
    valid_here = q.office_type_functions(s, office.office_type)
    if valid_here and function_code not in valid_here:
        raise RuleViolation(
            f"Function '{function_code}' is not on the function list of a {office.office_type} "
            f"({office.office_id}), so it cannot be allotted there.", "BR-04")
    if effective_to is not None and effective_to <= effective_from:
        raise InvalidInput("effective_to must be after effective_from")

    held = merge_intervals((p.effective_from, p.effective_to)
                           for p in q.current_postings(s, employee_id=emp.employee_id, office_id=office.office_id))
    if not interval_within(effective_from, effective_to, held):
        posted = "; ".join(describe(a, b) for a, b in held) or "never"
        raise RuleViolation(
            f"{emp.name} does not hold a posting in {office.office_id} for the whole period "
            f"{describe(effective_from, effective_to)} (posted there: {posted}). A function can only be allotted "
            f"to an officer posted in that office.", "BR-04")

    allotted_posts = {q.chair(s, p.sanctioned_post_id).post_code
                      for p in q.postings_at(s, effective_from, employee_id=emp.employee_id, office_id=office.office_id)}
    allotted_posts = {p for p in allotted_posts if q.post_function_mode(s, p) != q.ALL_OFFICE_FUNCTIONS}
    allowed = {f for p in allotted_posts for f in q.allottable_functions(s, p)}
    if allowed and function_code not in allowed:
        raise RuleViolation(
            f"Function '{function_code}' is not among the functions MDM allows for "
            f"{', '.join(sorted(allotted_posts))} (designation functions).", "BR-04")

    if q.holds_all_office_functions(s, emp.employee_id, office.office_id, effective_from):
        raise RuleViolation(
            f"{emp.name} already holds every function of {office.office_id} by virtue of their post; "
            f"no allotment is needed.", "BR-04")

    for other in s.scalars(select(FunctionAllotment).where(
        FunctionAllotment.employee_id == emp.employee_id, FunctionAllotment.office_id == office.office_id,
        FunctionAllotment.function_code == function_code, FunctionAllotment.superseded_by.is_(None),
    )):
        if overlaps(effective_from, effective_to, other.effective_from, other.effective_to):
            raise RuleViolation(
                f"{emp.name} already holds {function_code} in {office.office_id} for "
                f"{describe(other.effective_from, other.effective_to)}.", "BR-04")

    fa = insert(s, FunctionAllotment(
        employee_id=emp.employee_id, office_id=office.office_id, function_code=function_code,
        effective_from=effective_from, effective_to=effective_to, entered_by=entered_by.strip(),
        is_demo=is_demo, source_ref=source_ref, created_at=now_utc(),
    ), actor or entered_by, "FUNCTION_ALLOT")
    emit(s, "function.allotted", _payload(fa), fa.effective_from)
    if fa.effective_to is not None:
        emit(s, "function.withdrawn", _payload(fa), fa.effective_to)
    return fa


def withdraw(s: Session, allotment_id: int, at: datetime, entered_by: str) -> FunctionAllotment:
    fa = q.latest_version(s, FunctionAllotment, allotment_id)
    _check_establishment(q.office(s, fa.office_id), entered_by)
    if at < fa.effective_from:
        raise InvalidInput(f"Withdrawal at {fmt_ist(at)} is before the allotment began ({fmt_ist(fa.effective_from)}).")
    if fa.effective_to is not None and fa.effective_to <= at:
        raise InvalidInput(f"Allotment {fa.id} already ended at {fmt_ist(fa.effective_to)}.")
    new = supersede(s, fa, entered_by, "FUNCTION_WITHDRAW", effective_to=at)
    emit(s, "function.withdrawn", _payload(new), at)
    return new


def set_office_functions(s: Session, office_id: str, at: datetime, entered_by: str,
                         wanted: dict[str, set[str]]) -> dict:
    """The allotment grid: make each listed officer hold exactly the wanted functions from `at`.
    Unchecked boxes withdraw at `at`; newly checked boxes allot from `at` (open-ended)."""
    office = q.office(s, office_id)
    _check_establishment(office, entered_by)
    added, withdrawn = [], []
    for employee_id, codes in wanted.items():
        current = {fa.function_code: fa for fa in q.allotments_at(s, office_id, at) if fa.employee_id == employee_id}
        for code, fa in current.items():
            if code not in codes:
                if fa.effective_from == at:
                    raise RuleViolation(f"{code} for {employee_id} starts exactly at {fmt_ist(at)}; withdraw it by id instead.", "BR-05")
                withdrawn.append(withdraw(s, fa.id, at, entered_by))
        for code in sorted(codes - set(current)):
            added.append(allot(s, employee_id, office_id, code, at, entered_by))
    return {"added": added, "withdrawn": withdrawn}
