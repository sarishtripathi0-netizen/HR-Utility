"""Read endpoints for the Rule Engine, IAM and Workflow. Every one accepts ?at= (default: now)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..domain import history, link_officer, roster, seat
from ..domain import queries as q
from ..models import EventOutbox, MdmEmployee
from ..timeutil import iso_ist
from .deps import allot_out, at_param, get_session, get_settings
from .schemas import (
    AllotmentsResponse,
    ChairResponse,
    EmployeePostsResponse,
    ErrorResponse,
    EventsResponse,
    FunctionCatalogueResponse,
    HistoryResponse,
    LinkOfficerResponse,
    RosterResponse,
    SeatHoldersResponse,
)

router = APIRouter(prefix="/v1", responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
AT = Query(None, description="ISO-8601 timestamp or date; naive values are IST; default now",
           examples=["2026-11-04T10:00:00+05:30"])
CHAIR = Path(description="Chair ID `<office>-<designation>-NN`", examples=["DC_NGN-ADC-05"])
OFFICE = Path(description="MDM office code", examples=["DC_NGN"])


@router.get("/seat-holders", response_model=SeatHoldersResponse, tags=["Rule Engine"],
            summary="Who holds post P with function F in office O at time t, and the Link Officer if none is available")
def seat_holders(office_id: str = Query(description="MDM office code", examples=["DC_NGN"]),
                 post_code: str = Query(description="MDM designation code or short name", examples=["ADC"]),
                 function_code: str | None = Query(None, description="Required unless roster mode is on",
                                                   examples=["SOCIAL_WELFARE"]),
                 at: str | None = AT,
                 s: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    return seat.seat_holders(s, settings, office_id, post_code, function_code, at_param(at))


@router.get("/posts/{sanctioned_post_id}/holder", response_model=ChairResponse, tags=["Rule Engine"],
            summary="Holder(s) of one chair at time t, with availability and vacancy")
def post_holder(sanctioned_post_id: str = CHAIR, at: str | None = AT, s: Session = Depends(get_session),
                settings: Settings = Depends(get_settings)):
    return roster.chair_holder(s, settings, sanctioned_post_id, at_param(at))


@router.get("/posts/{sanctioned_post_id}/history", response_model=HistoryResponse, response_model_by_alias=True,
            tags=["Rule Engine"], summary="BR-08: holders, sub-intervals and working days over [from, to]")
def post_history(sanctioned_post_id: str = CHAIR,
                 from_: str | None = Query(None, alias="from", description="Start (a date means 00:00 IST)",
                                           examples=["2026-10-01"]),
                 to: str | None = Query(None, description="End (a date is inclusive: up to 24:00 IST that day)",
                                        examples=["2026-10-31"]),
                 s: Session = Depends(get_session)):
    frm = at_param(from_, name="from")
    end = at_param(to, end_of_day=True, name="to")
    return history.post_history(s, sanctioned_post_id, frm, end)


@router.get("/posts/{sanctioned_post_id}/link-officer", response_model=LinkOfficerResponse, tags=["Rule Engine"],
            summary="BR-07: Link Officer under rule 3(1) for this chair at time t")
def post_link_officer(sanctioned_post_id: str = CHAIR, at: str | None = AT, s: Session = Depends(get_session),
                      settings: Settings = Depends(get_settings)):
    t = at_param(at)
    res = link_officer.resolve(s, settings, sanctioned_post_id, t)
    return {"sanctioned_post_id": sanctioned_post_id, "at": iso_ist(t), "status": res.status,
            "link_officer": res.link_officer(), "reason": res.reason, "absent_holders": res.absent}


@router.get("/employees/{employee_id}/posts", response_model=EmployeePostsResponse, tags=["IAM"],
            summary="Substantive, additional and link charges held at time t")
def employee_posts(employee_id: str = Path(examples=["EMP-0065"]), at: str | None = AT, s: Session = Depends(get_session),
                   settings: Settings = Depends(get_settings)):
    return roster.employee_posts(s, settings, employee_id, at_param(at))


@router.get("/offices/{office_id}/roster", response_model=RosterResponse, tags=["Workflow"],
            summary="Every chair of an office at time t: holders, functions, availability")
def office_roster(office_id: str = OFFICE, at: str | None = AT, s: Session = Depends(get_session),
                  settings: Settings = Depends(get_settings)):
    return roster.office_roster(s, settings, office_id, at_param(at))


@router.get("/function-allotments", response_model=AllotmentsResponse, tags=["Establishment"],
            summary="Function allotments in force in an office at time t")
def list_allotments(office_id: str = Query(examples=["DC_NGN"]), employee_id: str | None = None, at: str | None = AT,
                    s: Session = Depends(get_session)):
    t = at_param(at)
    q.office(s, office_id)
    rows = [fa for fa in q.allotments_at(s, office_id, t) if employee_id is None or fa.employee_id == employee_id]
    rows.sort(key=lambda fa: (fa.employee_id, fa.function_code))
    return {"office_id": office_id, "at": iso_ist(t), "allotments": [allot_out(s, fa) for fa in rows]}


@router.get("/function-catalogue", response_model=FunctionCatalogueResponse, tags=["Establishment"],
            summary="Functions of each office type, and whether each post holds them by allotment or by being posted")
def function_catalogue(office_type: str | None = Query(None, examples=["DC_OFFICE"]), s: Session = Depends(get_session)):
    return roster.function_catalogue(s, office_type)


@router.get("/events", response_model=EventsResponse, tags=["Events"],
            summary="Outbox events after the given id (posting.*, charge.*, function.*, availability.*, employee.onboarded)")
def events(after: int = 0, limit: int = Query(500, le=5000), s: Session = Depends(get_session)):
    rows = list(s.scalars(select(EventOutbox).where(EventOutbox.id > after).order_by(EventOutbox.id).limit(limit)))
    out = []
    for ev in rows:
        payload = json.loads(ev.payload_json)
        if "employee_id" in payload and "is_demo" not in payload:
            emp = s.get(MdmEmployee, payload["employee_id"])
            payload["is_demo"] = bool(emp.is_demo) if emp else False
        out.append({"id": ev.id, "ts": iso_ist(ev.ts), "type": ev.type, "effective_at": iso_ist(ev.effective_at),
                    "payload": payload, "delivered": True})
        if not ev.delivered:
            ev.delivered = True
    return {"events": out, "next_after": rows[-1].id if rows else after}
