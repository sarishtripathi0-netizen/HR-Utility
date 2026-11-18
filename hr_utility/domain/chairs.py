"""Chairs (sanctioned posts): add and abolish. Sanctioned strength is MDM's (a count per office x designation):
adding a chair raises the count by one in MDM; abolishing lowers it, so only the highest-numbered chair can go.
The Establishment branch of the office is the only one allowed to ask."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from ..mdm.client import MdmClient
from ..models import MdmSanctionedPost
from ..timeutil import fmt_ist, now_utc
from . import queries as q
from .common import InvalidInput, RuleViolation, audit, describe, require, row_dict


def _check_establishment(office, entered_by: str) -> None:
    require(entered_by, "entered_by is required")
    if entered_by.strip() != office.establishment_actor:
        raise RuleViolation(f"Only the Establishment branch of {office.office_id} ({office.establishment_actor}) may add "
                            f"or abolish chairs in that office; this entry came from '{entered_by}'.", "ESTABLISHMENT")


def add_chair(s: Session, mdm: MdmClient, office_id: str, post_code: str, entered_by: str, reason: str) -> MdmSanctionedPost:
    office = q.office(s, office_id)
    post = q.post(s, post_code)
    _check_establishment(office, entered_by)
    require(reason, "A reason (e.g. the sanction order) is required to add a chair")
    if office.provisional:
        raise RuleViolation(f"{office.office_id} is not in MDM, so MDM cannot hold its sanctioned strength yet.", "MDM")
    try:
        rec = mdm.add_sanctioned_post(office.office_id, post.post_code,
                                      source=f"added by {entered_by} on {fmt_ist(now_utc())}: {reason.strip()}")
    except ValueError as e:
        raise RuleViolation(str(e), "MDM") from None
    row = s.merge(MdmSanctionedPost(sanctioned_post_id=rec.sanctioned_post_id, office_id=rec.office_id,
                                    post_code=rec.post_code, seq=rec.seq, derived=rec.derived, is_demo=rec.is_demo,
                                    source=rec.source, is_active=True))
    s.flush()
    audit(s, entered_by, "CHAIR_ADD", "mdm_cache_sanctioned_post", row.sanctioned_post_id, None, row_dict(row))
    return row


def abolish_chair(s: Session, mdm: MdmClient, sanctioned_post_id: str, entered_by: str, reason: str,
                  at: datetime | None = None) -> MdmSanctionedPost:
    """Abolish a chair nobody holds now or later. The chair and its history stay on record."""
    sp = q.chair(s, sanctioned_post_id)
    _check_establishment(q.office(s, sp.office_id), entered_by)
    require(reason, "A reason is required to abolish a chair")
    if not sp.is_active:
        raise InvalidInput(f"{sp.sanctioned_post_id} is already abolished")
    at = at or now_utc()
    live = [p for p in q.current_postings(s, sanctioned_post_id=sp.sanctioned_post_id)
            if p.effective_to is None or p.effective_to > at]
    if live:
        p = live[0]
        raise RuleViolation(f"{sp.sanctioned_post_id} is held by {q.employee(s, p.employee_id).name} for "
                            f"{describe(p.effective_from, p.effective_to)}. Relieve the holder before abolishing the chair.",
                            "BR-03")
    before = row_dict(sp)
    try:
        mdm.abolish_sanctioned_post(sp.sanctioned_post_id, reason.strip())
    except ValueError as e:
        raise RuleViolation(str(e), "MDM") from None
    sp.is_active = False
    sp.source = f"{sp.source or ''}; abolished by {entered_by} on {fmt_ist(at)}: {reason.strip()}"
    s.flush()
    audit(s, entered_by, "CHAIR_ABOLISH", "mdm_cache_sanctioned_post", sp.sanctioned_post_id, before, row_dict(sp))
    return sp
