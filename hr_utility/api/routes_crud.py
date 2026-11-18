"""Record management (list, view, create, correct, end) for the Establishment branch. Nothing is ever deleted
(BR-10): 'delete' is relieve / withdraw / cancel / abolish, and the earlier row is kept."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import availability, chairs, employees, postings
from ..domain import queries as q
from ..models import MdmOffice
from ..timeutil import iso_ist
from .deps import at_param, availability_out, get_mdm, get_session, posting_out
from .schemas import (
    AuditListResponse,
    AvailabilityListResponse,
    AvailabilityOut,
    ChairCreateBody,
    ChairListResponse,
    ChairOut,
    EmployeeCorrectBody,
    EmployeeCorrected,
    EmployeeDetailResponse,
    EmployeeListResponse,
    ErrorResponse,
    OfficeListResponse,
    OnboardingListResponse,
    PostingCorrectBody,
    PostingListResponse,
    PostingOut,
    ReasonBody,
)

router = APIRouter(prefix="/v1", tags=["Records"],
                   responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
AT = Query(None, description="ISO-8601 timestamp or date; naive = IST; default now", examples=["2026-11-04T10:00:00+05:30"])


# ---------------------------------------------------------------- officers

@router.get("/employees", response_model=EmployeeListResponse,
            summary="Search officers (name, ID, email, mobile; optionally by office)")
def list_employees(q_: str | None = Query(None, alias="q", examples=["Kamal"]),
                   office_id: str | None = Query(None, examples=["DC_NGN"]), include_demo: bool = True,
                   at: str | None = AT, s: Session = Depends(get_session)):
    t = at_param(at)
    return {"at": iso_ist(t), "employees": employees.search(s, t, q_, office_id, include_demo)}


@router.get("/employees/{employee_id}", response_model=EmployeeDetailResponse,
            summary="One officer: record, postings, functions, leave, onboarding")
def get_employee(employee_id: str, at: str | None = AT, s: Session = Depends(get_session)):
    return employees.detail(s, employee_id, at_param(at))


@router.put("/employees/{employee_id}", response_model=EmployeeCorrected,
            summary="Correct the officer's record (MDM fields sent to MDM; identifiers excluded)")
def correct_employee(employee_id: str, body: EmployeeCorrectBody, s: Session = Depends(get_session), mdm=Depends(get_mdm)):
    changes = body.model_dump(exclude={"submitted_by"})
    row = employees.correct(s, mdm, employee_id, changes, body.submitted_by)
    return {**q.employee_view(row), "email": row.email, "mobile": row.mobile}


@router.get("/onboarding", response_model=OnboardingListResponse, summary="Onboarding requests, newest first")
def list_onboarding(limit: int = Query(200, le=2000), s: Session = Depends(get_session)):
    return {"requests": employees.onboarding_list(s, limit)}


# ---------------------------------------------------------------- offices and chairs

@router.get("/offices", response_model=OfficeListResponse, summary="Offices (MDM copy plus any held locally)")
def list_offices(office_type: str | None = Query(None, examples=["DC_OFFICE"]),
                 district_code: str | None = Query(None, examples=["NGN"]), s: Session = Depends(get_session)):
    query = select(MdmOffice).order_by(MdmOffice.office_type, MdmOffice.office_id)
    if office_type:
        query = query.where(MdmOffice.office_type == office_type)
    if district_code:
        query = query.where(MdmOffice.district_code == district_code)
    return {"offices": [{"office_id": o.office_id, "name": o.name, "office_type": o.office_type,
                         "district_code": o.district_code, "district_name": o.district_name,
                         "parent_office_id": o.parent_office_id, "provisional": bool(o.provisional),
                         "is_active": bool(o.is_active), "establishment_actor": o.establishment_actor}
                        for o in s.scalars(query)]}


@router.get("/offices/{office_id}/chairs", response_model=ChairListResponse,
            summary="Chairs of an office with their holders at time t")
def list_chairs(office_id: str, include_abolished: bool = False, at: str | None = AT, s: Session = Depends(get_session)):
    return {"office_id": office_id, "chairs": employees.chair_list(s, office_id, at_param(at), include_abolished)}


@router.post("/offices/{office_id}/chairs", response_model=ChairOut,
             summary="Add a chair: raises MDM's sanctioned count for office x post by one (Establishment branch)")
def add_chair(office_id: str, body: ChairCreateBody, s: Session = Depends(get_session), mdm=Depends(get_mdm)):
    return employees.asdict_row(chairs.add_chair(s, mdm, office_id, body.post_code, body.entered_by, body.reason))


@router.post("/posts/{sanctioned_post_id}/abolish", response_model=ChairOut,
             summary="Abolish the highest-numbered empty chair: lowers MDM's count (kept on record)")
def abolish_chair(sanctioned_post_id: str, body: ReasonBody, s: Session = Depends(get_session), mdm=Depends(get_mdm)):
    return employees.asdict_row(chairs.abolish_chair(s, mdm, sanctioned_post_id, body.entered_by, body.reason))


# ---------------------------------------------------------------- postings and leave

@router.get("/postings", response_model=PostingListResponse,
            summary="Postings by office, officer or chair (current, future and ended)")
def list_postings(office_id: str | None = Query(None, examples=["DC_NGN"]), employee_id: str | None = None,
                  sanctioned_post_id: str | None = None, include_ended: bool = True, at: str | None = AT,
                  s: Session = Depends(get_session)):
    return {"postings": employees.posting_list(s, at_param(at), office_id, employee_id, sanctioned_post_id, include_ended)}


@router.post("/postings/{posting_id}/correct", response_model=PostingOut,
             summary="Correct order reference, issuing department or note (the old version is kept)")
def correct_posting(posting_id: int, body: PostingCorrectBody, s: Session = Depends(get_session)):
    p = postings.correct(s, posting_id, body.entered_by, order_ref=body.order_ref,
                         issuing_department=body.issuing_department, note=body.note)
    return posting_out(s, p)


@router.get("/availability", response_model=AvailabilityListResponse,
            summary="Leave / tour / training / deputation windows by office or officer")
def list_availability(office_id: str | None = None, employee_id: str | None = None, at: str | None = AT,
                      s: Session = Depends(get_session)):
    return {"windows": employees.availability_list(s, at_param(at), office_id, employee_id)}


@router.post("/availability/{availability_id}/cancel", response_model=AvailabilityOut,
             summary="Cancel a window (it collapses to nothing; both rows are kept)")
def cancel_availability(availability_id: int, body: ReasonBody, s: Session = Depends(get_session)):
    return availability_out(s, availability.cancel(s, availability_id, body.entered_by, body.reason))


# ---------------------------------------------------------------- audit

@router.get("/audit", response_model=AuditListResponse, summary="Append-only audit log, newest first")
def list_audit(entity: str | None = Query(None, examples=["posting"]), entity_id: str | None = None,
               actor: str | None = None, limit: int = Query(200, le=2000), s: Session = Depends(get_session)):
    return {"entries": employees.audit_trail(s, entity, entity_id, actor, limit)}
