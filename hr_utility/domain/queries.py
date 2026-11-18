"""As-of lookups. Superseded rows are never visible to these queries."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from ..models import (
    MdmCadre,
    MdmDesignationFunction,
    Availability,
    FunctionAllotment,
    MdmEmployee,
    MdmFunctionCode,
    MdmOffice,
    MdmOfficeTypeFunction,
    MdmPost,
    MdmPostFunctionRule,
    MdmSanctionedPost,
    Posting,
    VacancyDeclaration,
)
from .common import NotFound


def _active(model, frm_col, to_col, t: datetime):
    return and_(model.superseded_by.is_(None), frm_col <= t, or_(to_col.is_(None), to_col > t))


# ---------------------------------------------------------------- MDM cache lookups

def office(s: Session, office_id: str) -> MdmOffice:
    o = s.get(MdmOffice, office_id)
    if o is None:
        raise NotFound(f"Office {office_id} is not in MDM")
    return o


def post(s: Session, post_code: str) -> MdmPost:
    """A post is an MDM designation. Its MDM short name (DC, AC, CO, Co-DC ...) is accepted as an alias."""
    p = s.get(MdmPost, post_code)
    if p is None:
        hits = list(s.scalars(select(MdmPost).where(MdmPost.short_name.ilike(post_code))))
        if len(hits) == 1:
            return hits[0]
        raise NotFound(f"Post {post_code} is not an MDM designation")
    return p


def cadre_department(s: Session, cadre_code: str | None) -> str | None:
    """The cadre-controlling department (MDM cadre): who issues transfer orders for this officer."""
    c = s.get(MdmCadre, cadre_code) if cadre_code else None
    return c.department_name if c else None


def allottable_functions(s: Session, post_code: str) -> list[str]:
    """Functions a post may be allotted (MDM designation-function). Empty = no restriction recorded."""
    return sorted(s.scalars(select(MdmDesignationFunction.function_code).where(MdmDesignationFunction.post_code == post_code)))


def chair(s: Session, sanctioned_post_id: str) -> MdmSanctionedPost:
    c = s.get(MdmSanctionedPost, sanctioned_post_id)
    if c is None:
        raise NotFound(f"Sanctioned post {sanctioned_post_id} is not in MDM")
    return c


def employee(s: Session, employee_id: str) -> MdmEmployee:
    e = s.get(MdmEmployee, employee_id)
    if e is None:
        raise NotFound(f"Employee {employee_id} is not in MDM")
    return e


def function_code(s: Session, code: str) -> MdmFunctionCode | None:
    return s.get(MdmFunctionCode, code)


def rank_of_chair(s: Session, sp: MdmSanctionedPost) -> int:
    return post(s, sp.post_code).rank_order


def chairs_in_office(s: Session, office_id: str, include_abolished: bool = False) -> list[MdmSanctionedPost]:
    query = (select(MdmSanctionedPost, MdmPost.rank_order)
             .join(MdmPost, MdmPost.post_code == MdmSanctionedPost.post_code)
             .where(MdmSanctionedPost.office_id == office_id))
    if not include_abolished:
        query = query.where(MdmSanctionedPost.is_active.is_(True))
    rows = s.execute(query).all()
    return [r[0] for r in sorted(rows, key=lambda r: (r[1], r[0].post_code, r[0].seq))]


# ---------------------------------------------------------------- postings

def postings_at(s: Session, t: datetime, *, office_id: str | None = None, sanctioned_post_id: str | None = None,
                employee_id: str | None = None) -> list[Posting]:
    q = select(Posting).where(_active(Posting, Posting.effective_from, Posting.effective_to, t))
    if sanctioned_post_id:
        q = q.where(Posting.sanctioned_post_id == sanctioned_post_id)
    if employee_id:
        q = q.where(Posting.employee_id == employee_id)
    if office_id:
        q = q.join(MdmSanctionedPost, MdmSanctionedPost.sanctioned_post_id == Posting.sanctioned_post_id).where(
            MdmSanctionedPost.office_id == office_id)
    rows = list(s.scalars(q))
    return sorted(rows, key=lambda p: (p.charge_type != "SUBSTANTIVE", p.id))


def current_postings(s: Session, *, employee_id: str | None = None, sanctioned_post_id: str | None = None,
                     office_id: str | None = None) -> list[Posting]:
    """Every live (non-superseded) posting version, any period."""
    q = select(Posting).where(Posting.superseded_by.is_(None))
    if employee_id:
        q = q.where(Posting.employee_id == employee_id)
    if sanctioned_post_id:
        q = q.where(Posting.sanctioned_post_id == sanctioned_post_id)
    if office_id:
        q = q.join(MdmSanctionedPost, MdmSanctionedPost.sanctioned_post_id == Posting.sanctioned_post_id).where(
            MdmSanctionedPost.office_id == office_id)
    return list(s.scalars(q.order_by(Posting.effective_from, Posting.id)))


def latest_version(s: Session, model, record_id: int):
    """Resolve any version id of a record to its live version."""
    row = s.get(model, record_id)
    if row is None:
        raise NotFound(f"{model.__tablename__} {record_id} not found")
    lineage = row.lineage_id or row.id
    live = s.scalars(select(model).where(model.superseded_by.is_(None),
                                         or_(model.lineage_id == lineage, model.id == lineage))).first()
    if live is None:
        raise NotFound(f"{model.__tablename__} {record_id} has no live version")
    return live


# ---------------------------------------------------------------- availability (BR-06)

def absence_at(s: Session, employee_id: str, t: datetime) -> Availability | None:
    return s.scalars(select(Availability).where(
        Availability.employee_id == employee_id,
        _active(Availability, Availability.from_ts, Availability.to_ts, t),
    ).order_by(Availability.from_ts)).first()


def availability_at(s: Session, employee_id: str, t: datetime) -> tuple[bool, str | None]:
    """Available at t = holds a posting at t and no availability window covers t."""
    if not postings_at(s, t, employee_id=employee_id):
        return False, "NOT_POSTED"
    window = absence_at(s, employee_id, t)
    if window is not None:
        return False, window.kind
    return True, None


# ---------------------------------------------------------------- functions

ALL_OFFICE_FUNCTIONS = "ALL_OFFICE_FUNCTIONS"


def office_type_functions(s: Session, office_type: str) -> list[str]:
    return sorted(s.scalars(select(MdmOfficeTypeFunction.function_code).where(
        MdmOfficeTypeFunction.office_type == office_type)))


def post_function_mode(s: Session, post_code: str) -> str:
    rule = s.get(MdmPostFunctionRule, post_code)
    return rule.mode if rule else "ALLOTTED"


def allotted_functions_at(s: Session, employee_id: str, office_id: str, t: datetime) -> list[str]:
    rows = s.scalars(select(FunctionAllotment.function_code).where(
        FunctionAllotment.employee_id == employee_id,
        FunctionAllotment.office_id == office_id,
        _active(FunctionAllotment, FunctionAllotment.effective_from, FunctionAllotment.effective_to, t),
    ))
    return sorted(set(rows))


def holds_all_office_functions(s: Session, employee_id: str, office_id: str, t: datetime) -> bool:
    """True if, at t, the employee holds a post in this office whose rule is ALL_OFFICE_FUNCTIONS
    (e.g. the Circle Officer of a circle office)."""
    return any(post_function_mode(s, chair(s, p.sanctioned_post_id).post_code) == ALL_OFFICE_FUNCTIONS
               for p in postings_at(s, t, employee_id=employee_id, office_id=office_id))


def functions_at(s: Session, employee_id: str, office_id: str, t: datetime) -> list[str]:
    """Allotted functions plus, for ALL_OFFICE_FUNCTIONS posts, every function of the office type."""
    fns = set(allotted_functions_at(s, employee_id, office_id, t))
    if holds_all_office_functions(s, employee_id, office_id, t):
        fns |= set(office_type_functions(s, office(s, office_id).office_type))
    return sorted(fns)


def holds_function(s: Session, employee_id: str, office_id: str, function: str, t: datetime) -> bool:
    return function in functions_at(s, employee_id, office_id, t)


def allotments_at(s: Session, office_id: str, t: datetime) -> list[FunctionAllotment]:
    return list(s.scalars(select(FunctionAllotment).where(
        FunctionAllotment.office_id == office_id,
        _active(FunctionAllotment, FunctionAllotment.effective_from, FunctionAllotment.effective_to, t),
    )))


# ---------------------------------------------------------------- vacancy

def vacancy_at(s: Session, sanctioned_post_id: str, t: datetime) -> VacancyDeclaration | None:
    return s.scalars(select(VacancyDeclaration).where(
        VacancyDeclaration.sanctioned_post_id == sanctioned_post_id,
        _active(VacancyDeclaration, VacancyDeclaration.from_ts, VacancyDeclaration.to_ts, t),
    )).first()


# ---------------------------------------------------------------- seniority

def seniority_key(e: MdmEmployee) -> tuple:
    """year_of_joining ascending (unknown last), then name ascending."""
    return (e.year_of_joining is None, e.year_of_joining or 0, (e.name or "").lower(), e.employee_id)


def employee_view(e: MdmEmployee) -> dict:
    return {"employee_id": e.employee_id, "name": e.name, "cadre": e.cadre,
            "year_of_joining": e.year_of_joining, "is_demo": bool(e.is_demo)}
