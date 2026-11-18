"""Write endpoints used by Establishment-branch screens. Rule violations return 409 with the rule id."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import Settings
from ..domain import availability, functions, onboarding, postings
from ..timeutil import iso_ist
from .deps import allot_out, at_param, availability_out, get_mdm, get_session, get_settings, posting_out, required_ts
from .schemas import (
    AllotBody,
    AllotOut,
    AvailabilityBody,
    AvailabilityOut,
    ErrorResponse,
    OnboardingBody,
    OnboardingResponse,
    PostingBody,
    PostingOut,
    RelieveBody,
    RelieveOut,
    VacantBody,
    VacantOut,
    WithdrawBody,
)

router = APIRouter(prefix="/v1", tags=["Establishment"],
                   responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})


@router.post("/onboarding", response_model=OnboardingResponse,
             summary="Submit a new employee to MDM; returns MINTED, DUPLICATE or REJECTED with the Employee ID")
def onboard(body: OnboardingBody, s: Session = Depends(get_session), settings: Settings = Depends(get_settings),
            mdm=Depends(get_mdm)):
    req = onboarding.onboard(s, settings, mdm, onboarding.OnboardingInput(**body.model_dump()))
    return {"request_id": req.id, "status": req.status, "employee_id": req.employee_id, "reason": req.reason,
            "is_demo": bool(req.is_demo)}


@router.post("/postings", response_model=PostingOut,
             summary="Join: substantive or additional charge (BR-01, BR-02; checked live with MDM)")
def join(body: PostingBody, s: Session = Depends(get_session), mdm=Depends(get_mdm)):
    p = postings.join(s, postings.JoinRequest(
        employee_id=body.employee_id, sanctioned_post_id=body.sanctioned_post_id, charge_type=body.charge_type,
        effective_from=required_ts(body.effective_from, "effective_from"),
        effective_to=at_param(body.effective_to, name="effective_to") if body.effective_to else None,
        order_ref=body.order_ref, issuing_department=body.issuing_department, entered_by=body.entered_by,
        note=body.note), mdm=mdm)
    return posting_out(s, p)


@router.post("/postings/{posting_id}/relieve", response_model=RelieveOut,
             summary="End a posting; a substantive one needs a successor or same-instant additional charge (BR-03)")
def relieve(posting_id: int, body: RelieveBody, s: Session = Depends(get_session), mdm=Depends(get_mdm)):
    succ = postings.Successor(**body.successor.model_dump()) if body.successor else None
    res = postings.relieve(s, posting_id, required_ts(body.at, "at"), body.entered_by, succ, mdm=mdm)
    return {"ended": posting_out(s, res["ended"]), "successor": posting_out(s, res["successor"]) if res["successor"] else None}


@router.post("/function-allotments", response_model=AllotOut, summary="Allot a function (BR-04)")
def allot(body: AllotBody, s: Session = Depends(get_session)):
    fa = functions.allot(s, body.employee_id, body.office_id, body.function_code,
                         required_ts(body.effective_from, "effective_from"), body.entered_by,
                         at_param(body.effective_to, name="effective_to") if body.effective_to else None)
    return allot_out(s, fa)


@router.post("/function-allotments/{allotment_id}/withdraw", response_model=AllotOut,
             summary="Withdraw a function allotment from time t (the allotment row is kept, BR-10)")
def withdraw(allotment_id: int, body: WithdrawBody, s: Session = Depends(get_session)):
    return allot_out(s, functions.withdraw(s, allotment_id, required_ts(body.at, "at"), body.entered_by))


@router.post("/availability", response_model=AvailabilityOut, summary="Leave, tour, training or deputation (BR-06)")
def add_availability(body: AvailabilityBody, s: Session = Depends(get_session)):
    a = availability.record(s, body.employee_id, body.kind, required_ts(body.from_ts, "from_ts"),
                            at_param(body.to_ts, name="to_ts") if body.to_ts else None, body.entered_by, body.note,
                            body.supersedes_id)
    return availability_out(s, a)


@router.post("/posts/{sanctioned_post_id}/declare-vacant", response_model=VacantOut,
             summary="The only exception to BR-03: an explicit, reasoned vacancy")
def declare_vacant(sanctioned_post_id: str, body: VacantBody, s: Session = Depends(get_session)):
    res = postings.declare_vacant(s, sanctioned_post_id, required_ts(body.at, "at"), body.reason, body.entered_by)
    v = res["vacancy"]
    return {"vacancy_id": v.id, "sanctioned_post_id": v.sanctioned_post_id, "since": iso_ist(v.from_ts),
            "until": iso_ist(v.to_ts), "reason": v.reason, "entered_by": v.entered_by,
            "ended": [posting_out(s, p) for p in res["ended"]]}
