"""Onboarding: the HR Utility is the front door; MDM mints the Employee ID (POST /mdm/employees/mint).

De-duplication happens in two places:
 - the HR Utility checks the identifiers it collects (FinAssam code, PAN, salted Aadhaar hash) against earlier
   onboarding requests: MDM's mint does not take these identifiers;
 - MDM rejects a mobile or email that already belongs to an employee; that is reported as DUPLICATE too.
BR-09: only a salted hash of the Aadhaar token is ever stored; the token itself is discarded here and never sent.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..mdm.client import MdmClient, MintPayload
from ..mdm.sync import cache_employee
from ..models import OnboardingRequest
from ..timeutil import now_utc
from .common import InvalidInput, audit, emit, insert, row_dict

SOURCES = ("FINASSAM", "MANUAL")
GENDERS = ("MALE", "FEMALE", "OTHER")


def hash_aadhaar_token(token: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{token.strip()}".encode("utf-8")).hexdigest()


@dataclass
class OnboardingInput:
    source: str
    name: str
    submitted_by: str
    finassam_code: str | None = None
    pan: str | None = None
    aadhaar_token: str | None = None
    cadre: str | None = None
    year_of_joining: int | None = None
    date_of_birth: str | None = None
    date_of_retirement: str | None = None
    email: str | None = None
    mobile: str | None = None
    is_demo: bool = False
    gender: str | None = None
    date_of_joining: str | None = None


def _rejection(inp: OnboardingInput) -> str | None:
    if inp.source not in SOURCES:
        return f"source must be one of {SOURCES}"
    if not (inp.name or "").strip():
        return "name is required"
    if not (inp.submitted_by or "").strip():
        return "submitted_by is required"
    if inp.source == "FINASSAM" and not (inp.finassam_code or "").strip():
        return "a FINASSAM submission must carry the FinAssam employee code"
    if not any((inp.finassam_code, inp.pan, inp.aadhaar_token)):
        return "at least one identifier (FinAssam code, PAN or Aadhaar token) is needed for de-duplication"
    if inp.gender and inp.gender not in GENDERS:
        return f"gender must be one of {GENDERS}"
    if inp.mobile and not (inp.mobile.isdigit() and len(inp.mobile) == 10):
        return "mobile must be 10 digits"
    return None


def _earlier_match(s: Session, req: OnboardingRequest) -> tuple[str, str] | None:
    """An earlier request that resolved to an Employee ID with the same FinAssam code, PAN or Aadhaar hash."""
    for label, col in (("FinAssam code", OnboardingRequest.finassam_code), ("PAN", OnboardingRequest.pan),
                       ("Aadhaar token", OnboardingRequest.aadhaar_token_hash)):
        value = getattr(req, col.key)
        if not value:
            continue
        hit = s.scalars(select(OnboardingRequest).where(col == value, OnboardingRequest.id != req.id,
                                                        OnboardingRequest.employee_id.is_not(None))
                        .order_by(OnboardingRequest.id)).first()
        if hit:
            return hit.employee_id, label
    return None


def onboard(s: Session, settings: Settings, mdm: MdmClient, inp: OnboardingInput) -> OnboardingRequest:
    if inp.source not in SOURCES:
        raise InvalidInput(f"source must be one of {SOURCES}")
    token_hash = hash_aadhaar_token(inp.aadhaar_token, settings.aadhaar_salt) if inp.aadhaar_token else None
    req = insert(s, OnboardingRequest(
        source=inp.source, finassam_code=(inp.finassam_code or "").strip() or None,
        pan=(inp.pan or "").strip().upper() or None, aadhaar_token_hash=token_hash, name=(inp.name or "").strip(),
        cadre=inp.cadre, year_of_joining=inp.year_of_joining, date_of_birth=inp.date_of_birth,
        date_of_retirement=inp.date_of_retirement, email=inp.email, mobile=inp.mobile,
        submitted_by=inp.submitted_by or "", status="PENDING", is_demo=inp.is_demo, created_at=now_utc(),
    ), inp.submitted_by or "unknown", "ONBOARDING_SUBMIT")
    before = row_dict(req)

    why = _rejection(inp)
    earlier = None if why else _earlier_match(s, req)
    if why:
        req.status, req.reason = "REJECTED", why
    elif earlier:
        req.employee_id = earlier[0]
        req.status, req.reason = "DUPLICATE", f"matched an earlier onboarding on {earlier[1]}"
    else:
        mint = mdm.mint_demo if req.is_demo else mdm.mint_employee  # demo officers never go to MDM
        result = mint(MintPayload(
            name=req.name, cadre=req.cadre, year_of_joining=req.year_of_joining, date_of_birth=req.date_of_birth,
            date_of_retirement=req.date_of_retirement, email=req.email, mobile=req.mobile, is_demo=req.is_demo,
            gender=inp.gender, date_of_joining=inp.date_of_joining, source=f"onboarding_request {req.id} ({req.source})",
        ))
        req.employee_id = result.employee_id
        if result.duplicate:
            req.status = "DUPLICATE"
            req.reason = f"MDM: {result.matched_on or 'duplicate'} already belongs to {result.employee_id or 'an employee'}"
        else:
            req.status = "MINTED"
            rec = mdm.get_employee(result.employee_id)
            if rec is not None:
                cache_employee(s, rec)
    s.flush()
    audit(s, inp.submitted_by or "unknown", f"ONBOARDING_{req.status}", "onboarding_request", req.id, before, row_dict(req))
    if req.status == "MINTED":
        emit(s, "employee.onboarded", {"employee_id": req.employee_id, "onboarding_request_id": req.id,
                                       "source": req.source, "is_demo": bool(req.is_demo)}, req.created_at)
    return req
