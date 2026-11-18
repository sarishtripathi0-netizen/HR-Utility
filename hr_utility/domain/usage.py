"""Usage report for MDM (integration.md, 'Usage endpoint you must expose'): before MDM deactivates a record it
asks each consumer whether the record is still in use. The HR Utility uses offices (chairs, postings,
allotments), designations (through the posts mapped to them) and districts (through offices)."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import FunctionAllotment, MdmEmployee, MdmOffice, MdmPost, MdmSanctionedPost, Posting
from ..timeutil import now_utc


def _office_usage(s: Session, office_ids: list[str]) -> dict:
    if not office_ids:
        return {"chairs": 0, "current_postings": 0, "current_allotments": 0}
    t = now_utc()
    chairs = s.scalar(select(func.count()).select_from(MdmSanctionedPost).where(MdmSanctionedPost.office_id.in_(office_ids)))
    postings = s.scalar(select(func.count()).select_from(Posting)
                        .join(MdmSanctionedPost, MdmSanctionedPost.sanctioned_post_id == Posting.sanctioned_post_id)
                        .where(MdmSanctionedPost.office_id.in_(office_ids), Posting.superseded_by.is_(None),
                               (Posting.effective_to.is_(None)) | (Posting.effective_to > t)))
    allotments = s.scalar(select(func.count()).select_from(FunctionAllotment).where(
        FunctionAllotment.office_id.in_(office_ids), FunctionAllotment.superseded_by.is_(None),
        (FunctionAllotment.effective_to.is_(None)) | (FunctionAllotment.effective_to > t)))
    return {"chairs": chairs, "current_postings": postings, "current_allotments": allotments}


def _in_use(d: dict) -> bool:
    """HR uses a record when people are posted or functions are allotted under it. Chairs alone are MDM's own data."""
    return bool(d["current_postings"] or d["current_allotments"])


def usage(s: Session, entity_type: str, code: str) -> dict:
    if entity_type == "office":
        d = _office_usage(s, [code])
        return {"inUse": _in_use(d), "details": d}
    if entity_type == "district":
        offices = list(s.scalars(select(MdmOffice.office_id).where(MdmOffice.district_code == code)))
        d = _office_usage(s, offices)
        return {"inUse": _in_use(d), "details": {"offices": len(offices), **d}}
    if entity_type == "designation":
        posts = list(s.scalars(select(MdmPost.post_code).where(MdmPost.mdm_designation_code == code)))
        chairs = list(s.scalars(select(MdmSanctionedPost.sanctioned_post_id).where(MdmSanctionedPost.post_code.in_(posts)))) \
            if posts else []
        held = s.scalar(select(func.count()).select_from(Posting).where(
            Posting.sanctioned_post_id.in_(chairs), Posting.superseded_by.is_(None),
            (Posting.effective_to.is_(None)) | (Posting.effective_to > now_utc()))) if chairs else 0
        return {"inUse": held > 0, "details": {"hr_posts": posts, "chairs": len(chairs), "current_postings": held}}
    if entity_type == "employee":
        t = now_utc()
        live = s.scalar(select(func.count()).select_from(Posting).where(
            Posting.employee_id == code, Posting.superseded_by.is_(None),
            (Posting.effective_to.is_(None)) | (Posting.effective_to > t)))
        return {"inUse": live > 0, "details": {"current_or_future_postings": live}}
    if entity_type == "sanctioned-post":  # MDM code <office>:<designation>
        office, _, post = code.partition(":")
        chairs = [c for c in s.scalars(select(MdmSanctionedPost.sanctioned_post_id).where(
            MdmSanctionedPost.office_id == office, MdmSanctionedPost.post_code == post))]
        d = _office_usage(s, [office]) if chairs else {"chairs": 0, "current_postings": 0, "current_allotments": 0}
        held = s.scalar(select(func.count()).select_from(Posting).where(
            Posting.sanctioned_post_id.in_(chairs), Posting.superseded_by.is_(None),
            (Posting.effective_to.is_(None)) | (Posting.effective_to > now_utc()))) if chairs else 0
        return {"inUse": held > 0, "details": {"chairs": len(chairs), "held_chairs": held, "office": d}}
    if entity_type == "function":
        n = s.scalar(select(func.count()).select_from(FunctionAllotment).where(
            FunctionAllotment.function_code == code, FunctionAllotment.superseded_by.is_(None),
            (FunctionAllotment.effective_to.is_(None)) | (FunctionAllotment.effective_to > now_utc())))
        return {"inUse": n > 0, "details": {"current_allotments": n}}
    if entity_type == "cadre":
        n = s.scalar(select(func.count()).select_from(MdmEmployee).where(MdmEmployee.cadre == code))
        return {"inUse": n > 0, "details": {"employees": n}}
    if entity_type == "holiday":
        return {"inUse": False, "details": {"note": "holidays are read for working-day counts only"}}
    return {"inUse": False, "details": {"note": f"the HR Utility does not copy {entity_type}"}}
