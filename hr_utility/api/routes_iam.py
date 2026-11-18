"""IAM STUB endpoints. No authentication. Replace with the Officer IAM PoC."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from ..config import Settings
from ..domain import iam
from ..domain.common import InvalidInput
from .deps import at_param, get_session, get_settings
from .schemas import ErrorResponse, IamSessionOut, LoginBody, SwitchBody

router = APIRouter(prefix="/v1/iam", tags=["IAM stub"],
                   responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}})
STUB = "**STUB — no authentication.** "


@router.post("/login", response_model=IamSessionOut, summary="STUB login: lists posts held now, incl. link charges",
             description=STUB + "Returns a session_id; send it as X-Stub-Session on later calls.")
def login(body: LoginBody, at: str | None = None, s: Session = Depends(get_session),
          settings: Settings = Depends(get_settings)):
    return iam.login(s, settings, body.employee_id, at_param(at) if at else None)


@router.post("/switch", response_model=IamSessionOut, summary="STUB: set the active post", description=STUB)
def switch(body: SwitchBody, at: str | None = None, x_stub_session: str | None = Header(None),
           s: Session = Depends(get_session), settings: Settings = Depends(get_settings)):
    sid = body.session_id or x_stub_session
    if not sid:
        raise InvalidInput("Send the session id from /v1/iam/login as X-Stub-Session or session_id")
    return iam.switch(s, settings, sid, body.sanctioned_post_id, at_param(at) if at else None)


@router.get("/sessions/{session_id}", response_model=IamSessionOut,
            summary="STUB: re-check a session; access is revoked once posting.ended / availability.ended applies",
            description=STUB + "?at= simulates the clock for demonstration.")
def check(session_id: str, at: str | None = None, s: Session = Depends(get_session),
          settings: Settings = Depends(get_settings)):
    return iam.check(s, settings, session_id, at_param(at) if at else None)
