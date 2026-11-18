"""IAM STUB — not real authentication. Anyone can log in as any employee_id.

It shows the contract the Officer IAM PoC will honour: access attaches to the sanctioned post, never the
person; a session lists the posts held now (incl. link charges under BR-07); and access to a post is revoked
the moment a posting.ended or availability.ended event applies (checked on every call).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import EventOutbox, IamSession
from ..timeutil import fmt_ist, iso_ist, now_utc
from . import queries as q
from .common import NotFound, RuleViolation, audit, row_dict
from .roster import employee_posts

STUB_NOTICE = "IAM STUB: no authentication is performed. Do not use outside the PoC."


def _session(s: Session, session_id: str) -> IamSession:
    row = s.get(IamSession, session_id)
    if row is None:
        raise NotFound(f"IAM session {session_id} not found")
    return row


def _revoking_event(s: Session, employee_id: str, sanctioned_post_id: str, t: datetime) -> str:
    """Name the applied event that removed this post from the session, for the revoke reason."""
    holders = {p.employee_id for p in q.postings_at(s, t, sanctioned_post_id=sanctioned_post_id)}
    for ev in s.scalars(select(EventOutbox).where(EventOutbox.type.in_(("posting.ended", "charge.ended", "availability.ended")),
                                                  EventOutbox.effective_at <= t).order_by(EventOutbox.effective_at.desc(),
                                                                                         EventOutbox.id.desc())):
        payload = json.loads(ev.payload_json)
        if payload.get("sanctioned_post_id") == sanctioned_post_id and payload.get("employee_id") == employee_id:
            return f"{ev.type} (event {ev.id})"
        if ev.type == "availability.ended" and payload.get("employee_id") in holders:
            return f"availability.ended (event {ev.id}: the officer being covered is back)"
    return "the post is no longer held"


def view(s: Session, settings: Settings, row: IamSession, t: datetime) -> dict:
    posts = employee_posts(s, settings, row.employee_id, t) if row.revoked_at is None else None
    return {
        "stub": True, "notice": STUB_NOTICE, "session_id": row.session_id, "employee_id": row.employee_id,
        "is_demo": bool(q.employee(s, row.employee_id).is_demo), "at": iso_ist(t),
        "active_post_id": row.active_post_id, "revoked": row.revoked_at is not None,
        "revoked_at": iso_ist(row.revoked_at), "revoke_reason": row.revoke_reason,
        "posts": posts["posts"] if posts else [],
    }


def check(s: Session, settings: Settings, session_id: str, t: datetime | None = None) -> dict:
    """Re-evaluate the session at t (now by default): revoke if the active post is no longer held."""
    t = t or now_utc()
    row = _session(s, session_id)
    if row.revoked_at is None and row.active_post_id:
        held = {p["sanctioned_post_id"] for p in employee_posts(s, settings, row.employee_id, t)["posts"]}
        if row.active_post_id not in held:
            before = row_dict(row)
            row.revoked_at = t
            row.revoke_reason = (f"Access to {row.active_post_id} revoked at {fmt_ist(t)}: "
                                 f"{_revoking_event(s, row.employee_id, row.active_post_id, t)} applied.")
            s.flush()
            audit(s, "IAM-STUB", "IAM_REVOKE", "iam_session", row.session_id, before, row_dict(row))
    return view(s, settings, row, t)


def login(s: Session, settings: Settings, employee_id: str, t: datetime | None = None) -> dict:
    t = t or now_utc()
    q.employee(s, employee_id)
    posts = employee_posts(s, settings, employee_id, t)["posts"]
    row = IamSession(session_id=str(uuid.uuid4()), employee_id=employee_id,
                     active_post_id=posts[0]["sanctioned_post_id"] if posts else None, created_at=t)
    s.add(row)
    s.flush()
    audit(s, employee_id, "IAM_LOGIN", "iam_session", row.session_id, None, row_dict(row))
    return view(s, settings, row, t)


def switch(s: Session, settings: Settings, session_id: str, sanctioned_post_id: str, t: datetime | None = None) -> dict:
    t = t or now_utc()
    check(s, settings, session_id, t)
    row = _session(s, session_id)
    if row.revoked_at is not None:
        raise RuleViolation(f"Session revoked; log in again. {row.revoke_reason}")
    held = {p["sanctioned_post_id"] for p in employee_posts(s, settings, row.employee_id, t)["posts"]}
    if sanctioned_post_id not in held:
        raise RuleViolation(f"{row.employee_id} does not hold {sanctioned_post_id} at {fmt_ist(t)} "
                            f"(held: {', '.join(sorted(held)) or 'none'}).")
    before = row_dict(row)
    row.active_post_id = sanctioned_post_id
    s.flush()
    audit(s, row.employee_id, "IAM_SWITCH", "iam_session", row.session_id, before, row_dict(row))
    return view(s, settings, row, t)
