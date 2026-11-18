"""Record-management screens: officers, chairs, and the audit trail. Thin: each form calls hr_utility.domain and
redirects back with a message (post/redirect/get), so refreshing never repeats an action."""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from ..domain import availability, chairs, employees, functions, onboarding, postings
from ..domain import queries as q
from ..domain.common import DomainError
from ..models import MdmPost, MdmSanctionedPost
from ..timeutil import fmt_ist, now_utc, parse_at
from .routes import DEFAULT_OFFICE, _ctx, _form, _render

router = APIRouter(include_in_schema=False)


def _back(url: str, msg: str | None = None, err: str | None = None, **params) -> RedirectResponse:
    qs = {k: v for k, v in {**params, "msg": msg, "err": err}.items() if v}
    return RedirectResponse(f"{url}?{urlencode(qs)}" if qs else url, status_code=303)


def _err(e: Exception) -> str:
    if isinstance(e, DomainError):
        return f"{e.rule + ': ' if e.rule else ''}{e.message}"
    if isinstance(e, KeyError):
        return f"Missing field: {e}"
    return f"Invalid input: {e}"


def _run(request: Request, action):
    """Run one domain action in its own transaction; return (result, error message)."""
    try:
        with request.app.state.db.session() as s:
            return action(s), None
    except (DomainError, KeyError, ValueError) as e:
        return None, _err(e)


def _opt(v: str | None):
    return v.strip() if v and v.strip() else None


# ---------------------------------------------------------------- officers

@router.get("/ui/officers", response_class=HTMLResponse)
def officers_page(request: Request, q_: str | None = None, office_id: str | None = None, demo: int = 1):
    with request.app.state.db.session() as s:
        t = now_utc()
        rows = employees.search(s, t, q_, office_id or None, include_demo=bool(demo))
        return _render(request, "officers.html", _ctx(request, s, t, rows=rows, text=q_ or "", office_id=office_id or "",
                                                      demo=demo, requests=employees.onboarding_list(s, 20)))


@router.get("/ui/officers/new", response_class=HTMLResponse)
def officer_new_page(request: Request):
    with request.app.state.db.session() as s:
        return _render(request, "officer_new.html", _ctx(request, s, now_utc(), form={}))


@router.post("/ui/officers/new", response_class=HTMLResponse)
async def officer_new_submit(request: Request):
    f = await _form(request)
    if _opt(f.get("year_of_joining")) and not f["year_of_joining"].strip().isdigit():
        with request.app.state.db.session() as s:
            return _render(request, "officer_new.html", _ctx(request, s, now_utc(), form=f,
                                                             error="Year of joining must be a year, e.g. 2019."))
    inp = onboarding.OnboardingInput(
        source=f.get("source", "MANUAL"), name=f.get("name", ""), submitted_by=f.get("submitted_by", ""),
        finassam_code=_opt(f.get("finassam_code")), pan=_opt(f.get("pan")), aadhaar_token=_opt(f.get("aadhaar_token")),
        cadre=_opt(f.get("cadre")), year_of_joining=int(f["year_of_joining"]) if _opt(f.get("year_of_joining")) else None,
        date_of_birth=_opt(f.get("date_of_birth")), date_of_retirement=_opt(f.get("date_of_retirement")),
        email=_opt(f.get("email")), mobile=_opt(f.get("mobile")), is_demo=f.get("is_demo") == "1",
        gender=_opt(f.get("gender")), date_of_joining=_opt(f.get("date_of_joining")))
    req, error = _run(request, lambda s: onboarding.onboard(s, request.app.state.settings, request.app.state.mdm, inp))
    if req is not None and req.status == "MINTED":
        minted = f"demo officer {req.employee_id} (local, not sent to MDM)" if req.is_demo else f"MDM minted {req.employee_id}"
        return _back(f"/ui/officers/{req.employee_id}", msg=f"Onboarded: {minted}. Now post the officer to a chair.")
    if req is not None and req.status == "DUPLICATE":
        return _back(f"/ui/officers/{req.employee_id}", err=f"Not added: this person already exists as {req.employee_id} "
                                                              f"({req.reason}).")
    with request.app.state.db.session() as s:
        f.pop("aadhaar_token", None)  # never echoed back
        reason = error if req is None else f"Rejected: {req.reason}"
        return _render(request, "officer_new.html", _ctx(request, s, now_utc(), form=f, error=reason))


@router.get("/ui/officers/{employee_id}", response_class=HTMLResponse)
def officer_page(request: Request, employee_id: str):
    with request.app.state.db.session() as s:
        t = now_utc()
        try:
            data = employees.detail(s, employee_id, t)
        except DomainError as e:
            return _back("/ui/officers", err=e.message)
        offices = sorted({p["office_id"] for p in data["postings"] if p["state"] != "ENDED"})
        chair_ids = list(s.scalars(select(MdmSanctionedPost.sanctioned_post_id).where(MdmSanctionedPost.is_active.is_(True))
                                   .order_by(MdmSanctionedPost.sanctioned_post_id)))
        fn_by_office = {o: q.office_type_functions(s, q.office(s, o).office_type) for o in offices}
        estb = {o: q.office(s, o).establishment_actor for o in offices}
        return _render(request, "officer.html", _ctx(request, s, t, d=data, e=data["employee"], chair_ids=chair_ids,
                                                     current_offices=offices, fn_by_office=fn_by_office, estb=estb,
                                                     audit_rows=employees.employee_audit(s, employee_id, 60)))


@router.post("/ui/officers/{employee_id}/edit")
async def officer_edit(request: Request, employee_id: str):
    f = await _form(request)
    current, err = _run(request, lambda s: employees.detail(s, employee_id, now_utc())["employee"])
    if err:
        return _back("/ui/officers", err=err)
    # Send only the fields the user actually changed.
    changes = {k: _opt(f.get(k)) for k in employees.CORRECTABLE
               if _opt(f.get(k)) is not None and _opt(f.get(k)) != str(current.get(k) or "")}
    if "year_of_joining" in changes:
        if not changes["year_of_joining"].isdigit():
            return _back(f"/ui/officers/{employee_id}", err="Year of joining must be a year, e.g. 2019.")
        changes["year_of_joining"] = int(changes["year_of_joining"])
    _, err = _run(request, lambda s: employees.correct(s, request.app.state.mdm, employee_id, changes,
                                                       f.get("submitted_by", "")))
    return _back(f"/ui/officers/{employee_id}", msg=None if err else f"Record corrected: {', '.join(changes)}.", err=err)


@router.post("/ui/officers/{employee_id}/join")
async def officer_join(request: Request, employee_id: str):
    f = await _form(request)
    p, err = _run(request, lambda s: postings.join(s, postings.JoinRequest(
        employee_id=employee_id, sanctioned_post_id=f["sanctioned_post_id"].strip(), charge_type=f["charge_type"],
        effective_from=parse_at(f["at"]), order_ref=f.get("order_ref", ""),
        issuing_department=f.get("issuing_department", ""), entered_by=f.get("entered_by", "")),
        mdm=request.app.state.mdm))
    return _back(f"/ui/officers/{employee_id}", err=err,
                 msg=None if err else f"Posted to {p.sanctioned_post_id} ({p.charge_type.lower()}) from {fmt_ist(p.effective_from)}.")


@router.post("/ui/officers/{employee_id}/postings/{posting_id}/relieve")
async def officer_relieve(request: Request, employee_id: str, posting_id: int):
    f = await _form(request)
    succ = None
    if _opt(f.get("successor_id")):
        succ = postings.Successor(f["successor_id"].strip(), f.get("successor_charge", "SUBSTANTIVE"),
                                  f.get("order_ref", ""), f.get("issuing_department", ""))
    res, err = _run(request, lambda s: postings.relieve(s, posting_id, parse_at(f["at"]), f.get("entered_by", ""), succ,
                                                        mdm=request.app.state.mdm))
    msg = None if err else f"Relieved at {fmt_ist(res['ended'].effective_to)}." + (
        f" {res['successor'].employee_id} took over." if res["successor"] else "")
    return _back(f"/ui/officers/{employee_id}", msg=msg, err=err)


@router.post("/ui/officers/{employee_id}/postings/{posting_id}/correct")
async def officer_correct_posting(request: Request, employee_id: str, posting_id: int):
    f = await _form(request)
    _, err = _run(request, lambda s: postings.correct(s, posting_id, f.get("entered_by", ""), order_ref=_opt(f.get("order_ref")),
                                                      issuing_department=_opt(f.get("issuing_department")),
                                                      note=_opt(f.get("note"))))
    return _back(f"/ui/officers/{employee_id}", msg=None if err else "Posting paperwork corrected (old version kept).", err=err)


@router.post("/ui/officers/{employee_id}/allot")
async def officer_allot(request: Request, employee_id: str):
    f = await _form(request)
    fa, err = _run(request, lambda s: functions.allot(s, employee_id, f["office_id"], f["function_code"], parse_at(f["at"]),
                                                      f.get("entered_by", "")))
    return _back(f"/ui/officers/{employee_id}", err=err,
                 msg=None if err else f"{fa.function_code} allotted in {fa.office_id} from {fmt_ist(fa.effective_from)}.")


@router.post("/ui/officers/{employee_id}/allotments/{allotment_id}/withdraw")
async def officer_withdraw(request: Request, employee_id: str, allotment_id: int):
    f = await _form(request)
    fa, err = _run(request, lambda s: functions.withdraw(s, allotment_id, parse_at(f["at"]), f.get("entered_by", "")))
    return _back(f"/ui/officers/{employee_id}", err=err,
                 msg=None if err else f"{fa.function_code} withdrawn from {fmt_ist(fa.effective_to)}.")


@router.post("/ui/officers/{employee_id}/leave")
async def officer_leave(request: Request, employee_id: str):
    f = await _form(request)
    a, err = _run(request, lambda s: availability.record(s, employee_id, f["kind"], parse_at(f["from_ts"]),
                                                         parse_at(f["to_ts"]) if _opt(f.get("to_ts")) else None,
                                                         f.get("entered_by", ""), _opt(f.get("note"))))
    return _back(f"/ui/officers/{employee_id}", err=err, msg=None if err else f"{a.kind.title()} recorded.")


@router.post("/ui/officers/{employee_id}/leave/{availability_id}/cancel")
async def officer_leave_cancel(request: Request, employee_id: str, availability_id: int):
    f = await _form(request)
    _, err = _run(request, lambda s: availability.cancel(s, availability_id, f.get("entered_by", ""), f.get("reason", "")))
    return _back(f"/ui/officers/{employee_id}", err=err, msg=None if err else "Entry cancelled (kept on record).")


# ---------------------------------------------------------------- chairs

@router.get("/ui/chairs", response_class=HTMLResponse)
def chairs_page(request: Request, office_id: str = DEFAULT_OFFICE, abolished: int = 0):
    with request.app.state.db.session() as s:
        t = now_utc()
        try:
            rows = employees.chair_list(s, office_id, t, include_abolished=bool(abolished))
            office = q.office(s, office_id)
        except DomainError as e:
            return _back("/ui/chairs", err=e.message)
        posts = list(s.scalars(select(MdmPost).order_by(MdmPost.rank_order, MdmPost.post_code)))
        return _render(request, "chairs.html", _ctx(request, s, t, office_id=office_id, office=office, rows=rows,
                                                    posts=posts, abolished=abolished))


@router.post("/ui/chairs/add")
async def chairs_add(request: Request):
    f = await _form(request)
    sp, err = _run(request, lambda s: chairs.add_chair(s, request.app.state.mdm, f["office_id"], f["post_code"],
                                                       f.get("entered_by", ""), f.get("reason", "")))
    return _back("/ui/chairs", office_id=f.get("office_id"), err=err,
                 msg=None if err else f"Chair {sp.sanctioned_post_id} added. Post an officer to it from the officer's page.")


@router.post("/ui/chairs/{sanctioned_post_id}/abolish")
async def chairs_abolish(request: Request, sanctioned_post_id: str):
    f = await _form(request)
    sp, err = _run(request, lambda s: chairs.abolish_chair(s, request.app.state.mdm, sanctioned_post_id,
                                                           f.get("entered_by", ""), f.get("reason", "")))
    return _back("/ui/chairs", office_id=f.get("office_id"), err=err,
                 msg=None if err else f"Chair {sanctioned_post_id} abolished (kept on record).")


# ---------------------------------------------------------------- audit

@router.get("/ui/audit", response_class=HTMLResponse)
def audit_page(request: Request, entity: str | None = None, entity_id: str | None = None, actor: str | None = None):
    with request.app.state.db.session() as s:
        rows = employees.audit_trail(s, entity or None, entity_id or None, actor or None, 300)
        return _render(request, "audit.html", _ctx(request, s, now_utc(), rows=rows, entity=entity or "",
                                                   entity_id=entity_id or "", actor=actor or ""))
