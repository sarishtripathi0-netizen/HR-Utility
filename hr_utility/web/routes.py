"""Server-rendered screens for the Establishment branch and for testing the core question.

Screens hold no rules: they parse a form, call hr_utility.domain, and render the result or the rule's message.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from ..domain import availability, functions, history, postings, roster, seat
from ..domain import queries as q
from ..domain.common import DomainError
from ..mdm.sync import sync_state
from ..models import Availability, FunctionAllotment, MdmFunctionCode, MdmOffice, MdmPost, MdmSanctionedPost
from ..timeutil import fmt_ist, now_utc, parse_at, to_ist

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["ist"] = lambda v: fmt_ist(parse_at(v)) if isinstance(v, str) else fmt_ist(v)

CORE_FUNCTIONS = ["SOCIAL_WELFARE", "E_GOVERNANCE", "HEALTH_FW", "ARTPS", "NAZARAT", "MAGISTRACY", "ACCOUNTS",
                  "REVENUE", "ELECTION", "DISASTER_MGMT"]
# Screen defaults (MDM codes): Nalbari DC office, Nalbari revenue circle office, a Nalbari ADC chair.
DEFAULT_OFFICE = "AS-D-298"
DEFAULT_CIRCLE_OFFICE = "AS-CR-298-05"
DEFAULT_CHAIR = "AS-D-298-ADC-01"


def _local(dt) -> str:
    return to_ist(dt).strftime("%Y-%m-%dT%H:%M")


def _when(value: str | None, default=None):
    if value:
        return parse_at(value)
    return default or now_utc()


def _ctx(request: Request, s, at, **kw) -> dict:
    offices = list(s.scalars(select(MdmOffice).order_by(MdmOffice.office_type.desc(), MdmOffice.office_id)))
    st = sync_state(s)
    mdm = {"source": st.source if st else "SEED", "version": st.applied_version if st else None,
           "synced": fmt_ist(st.last_synced_at) if st and st.last_synced_at else "never",
           "stale": bool(st and st.last_error), "error": st.last_error if st else None}
    # Messages carried across a redirect (post/redirect/get) arrive as ?msg= / ?err=.
    kw["message"] = kw.get("message") or request.query_params.get("msg")
    kw["error"] = kw.get("error") or request.query_params.get("err")
    return {"request": request, "offices": offices, "at": at, "at_local": _local(at), "at_label": fmt_ist(at),
            "settings": request.app.state.settings, "mdm": mdm, **kw}


def _render(request: Request, name: str, ctx: dict) -> HTMLResponse:
    return templates.TemplateResponse(request, name, ctx)


async def _form(request: Request) -> dict:
    return {k: v for k, v in (await request.form()).multi_items()}


@router.get("/", response_class=HTMLResponse)
def home(request: Request):
    with request.app.state.db.session() as s:
        return _render(request, "home.html", _ctx(request, s, now_utc()))


@router.get("/ui/roster", response_class=HTMLResponse)
def roster_page(request: Request, office_id: str = DEFAULT_OFFICE, at: str | None = None):
    with request.app.state.db.session() as s:
        t = _when(at)
        data, error = None, None
        try:
            data = roster.office_roster(s, request.app.state.settings, office_id, t)
        except DomainError as e:
            error = e.message
        return _render(request, "roster.html", _ctx(request, s, t, office_id=office_id, data=data, error=error))


@router.api_route("/ui/seat", methods=["GET"], response_class=HTMLResponse)
def seat_page(request: Request, office_id: str = DEFAULT_OFFICE, post_code: str = "ADC",
              function_code: str = "SOCIAL_WELFARE", at: str | None = None, go: str | None = None):
    with request.app.state.db.session() as s:
        t = _when(at)
        result, error = None, None
        if go:
            try:
                result = seat.seat_holders(s, request.app.state.settings, office_id, post_code, function_code, t)
            except DomainError as e:
                error = e.message
        posts = list(s.scalars(select(MdmPost).order_by(MdmPost.rank_order, MdmPost.post_code)))
        fns = list(s.scalars(select(MdmFunctionCode).order_by(MdmFunctionCode.category, MdmFunctionCode.code)))
        return _render(request, "seat.html", _ctx(request, s, t, office_id=office_id, post_code=post_code,
                                                  function_code=function_code, posts=posts, fns=fns,
                                                  result=result, error=error))


@router.get("/ui/functions", response_class=HTMLResponse)
def functions_page(request: Request):
    with request.app.state.db.session() as s:
        cat = roster.function_catalogue(s)
        bundles = list(s.scalars(select(FunctionAllotment).where(FunctionAllotment.is_demo.is_(True),
                                                                 FunctionAllotment.superseded_by.is_(None))))
        per_office: dict[str, int] = {}
        for b in bundles:
            per_office[b.office_id] = per_office.get(b.office_id, 0) + 1
        return _render(request, "functions.html", _ctx(request, s, now_utc(), cat=cat, demo_counts=per_office))


@router.get("/ui/history", response_class=HTMLResponse)
def history_page(request: Request, sanctioned_post_id: str = DEFAULT_CHAIR, frm: str | None = None,
                 to: str | None = None):
    with request.app.state.db.session() as s:
        start = parse_at(frm) if frm else parse_at((to_ist(now_utc()) - timedelta(days=30)).date().isoformat())
        end = parse_at(to, end_of_day=True) if to else parse_at(to_ist(now_utc()).date().isoformat(), end_of_day=True)
        result, error = None, None
        try:
            result = history.post_history(s, sanctioned_post_id, start, end)
        except DomainError as e:
            error = e.message
        chairs = list(s.scalars(select(MdmSanctionedPost.sanctioned_post_id).order_by(MdmSanctionedPost.sanctioned_post_id)))
        return _render(request, "history.html", _ctx(
            request, s, end, chairs=chairs, sanctioned_post_id=sanctioned_post_id, result=result, error=error,
            frm=to_ist(start).date().isoformat(), to=(to_ist(end) - timedelta(days=1)).date().isoformat()))


# ---------------------------------------------------------------- allotment grid

def _grid(request: Request, s, office_id: str, t, show_all: bool, **extra):
    data = roster.office_roster(s, request.app.state.settings, office_id, t)
    officers, seen = [], set()
    for c in data["chairs"]:
        for h in c["holders"]:
            if h["employee_id"] not in seen:
                seen.add(h["employee_id"])
                officers.append({**h, "chair": c["sanctioned_post_id"]})
    codes = q.office_type_functions(s, data["office_type"]) or \
        [r.code for r in s.scalars(select(MdmFunctionCode).order_by(MdmFunctionCode.code))]
    held = {f for o in officers if not o["holds_all_office_functions"] for f in o["functions_allotted"]}
    if show_all or data["office_type"] != "DC_OFFICE":
        cols = codes
    else:
        cols = [c for c in CORE_FUNCTIONS if c in codes] + sorted(held - set(CORE_FUNCTIONS))
    return _ctx(request, s, t, office_id=office_id, data=data, officers=officers, cols=cols, show_all=show_all, **extra)


@router.get("/ui/allotments", response_class=HTMLResponse)
def allotments_page(request: Request, office_id: str = DEFAULT_OFFICE, at: str | None = None, show_all: int = 0):
    with request.app.state.db.session() as s:
        return _render(request, "allotments.html", _grid(request, s, office_id, _when(at), bool(show_all)))


@router.post("/ui/allotments", response_class=HTMLResponse)
async def allotments_save(request: Request):
    form = await request.form()
    office_id, t = form["office_id"], parse_at(form["at"])
    wanted: dict[str, set[str]] = {e: set() for e in form.getlist("officer")}
    for cell in form.getlist("cell"):
        emp, code = cell.split("|", 1)
        wanted.setdefault(emp, set()).add(code)
    visible = set(form.getlist("col"))
    db = request.app.state.db
    message, error = None, None
    try:
        with db.session() as s:
            current = {fa.employee_id: set() for fa in q.allotments_at(s, office_id, t)}
            for fa in q.allotments_at(s, office_id, t):
                current[fa.employee_id].add(fa.function_code)
            # Columns not shown on the grid are left exactly as they are.
            merged = {e: (codes | (current.get(e, set()) - visible)) for e, codes in wanted.items()}
            res = functions.set_office_functions(s, office_id, t, form["entered_by"], merged)
            message = (f"Saved, effective {fmt_ist(t)}: {len(res['added'])} allotted, {len(res['withdrawn'])} withdrawn. "
                       "Earlier dates are unchanged.")
    except DomainError as e:
        error = f"{e.rule + ': ' if e.rule else ''}{e.message}"
    with db.session() as s:
        return _render(request, "allotments.html", _grid(request, s, office_id, t, form.get("show_all") == "1",
                                                         message=message, error=error))


# ---------------------------------------------------------------- postings and relieving

def _postings_ctx(request, s, office_id, t, **extra):
    data = roster.office_roster(s, request.app.state.settings, office_id, t)
    chairs = [c.sanctioned_post_id for c in q.chairs_in_office(s, office_id)]
    return _ctx(request, s, t, office_id=office_id, data=data, chairs=chairs, **extra)


@router.get("/ui/postings", response_class=HTMLResponse)
def postings_page(request: Request, office_id: str = DEFAULT_CIRCLE_OFFICE, at: str | None = None):
    with request.app.state.db.session() as s:
        return _render(request, "postings.html", _postings_ctx(request, s, office_id, _when(at)))


@router.post("/ui/postings", response_class=HTMLResponse)
async def postings_submit(request: Request):
    f = await _form(request)
    db = request.app.state.db
    office_id = f["office_id"]
    t = parse_at(f.get("at") or None)
    message, error = None, None
    try:
        with db.session() as s:
            if f["action"] == "join":
                p = postings.join(s, postings.JoinRequest(
                    employee_id=f["employee_id"].strip(), sanctioned_post_id=f["sanctioned_post_id"],
                    charge_type=f["charge_type"], effective_from=t, order_ref=f["order_ref"],
                    issuing_department=f["issuing_department"], entered_by=f["entered_by"]), mdm=request.app.state.mdm)
                message = f"{p.employee_id} joined {p.sanctioned_post_id} ({p.charge_type.lower()}) from {fmt_ist(t)}."
            elif f["action"] == "relieve":
                succ = None
                if f.get("successor_id", "").strip():
                    succ = postings.Successor(f["successor_id"].strip(), f["successor_charge"], f["order_ref"],
                                              f["issuing_department"])
                res = postings.relieve(s, int(f["posting_id"]), t, f["entered_by"], succ, mdm=request.app.state.mdm)
                message = f"Relieved at {fmt_ist(t)}." + (f" {res['successor'].employee_id} took over." if res["successor"] else "")
            elif f["action"] == "vacant":
                postings.declare_vacant(s, f["sanctioned_post_id"], t, f.get("reason", ""), f["entered_by"])
                message = f"{f['sanctioned_post_id']} declared vacant from {fmt_ist(t)}."
    except DomainError as e:
        error = f"{e.rule + ': ' if e.rule else ''}{e.message}"
    except (KeyError, ValueError) as e:
        error = f"Missing or invalid field: {e}"
    with db.session() as s:
        return _render(request, "postings.html", _postings_ctx(request, s, office_id, t, message=message, error=error, form=f))


# ---------------------------------------------------------------- leave entry

def _leave_ctx(request, s, office_id, t, **extra):
    data = roster.office_roster(s, request.app.state.settings, office_id, t)
    people = {h["employee_id"]: h for c in data["chairs"] for h in c["holders"]}
    windows = list(s.scalars(select(Availability).where(Availability.employee_id.in_(list(people)),
                                                        Availability.superseded_by.is_(None))
                             .order_by(Availability.from_ts.desc())))
    return _ctx(request, s, t, office_id=office_id, people=people, windows=windows, **extra)


@router.get("/ui/leave", response_class=HTMLResponse)
def leave_page(request: Request, office_id: str = DEFAULT_OFFICE, at: str | None = None):
    with request.app.state.db.session() as s:
        return _render(request, "leave.html", _leave_ctx(request, s, office_id, _when(at)))


@router.post("/ui/leave", response_class=HTMLResponse)
async def leave_submit(request: Request):
    f = await _form(request)
    db = request.app.state.db
    message, error = None, None
    try:
        with db.session() as s:
            a = availability.record(s, f["employee_id"], f["kind"], parse_at(f["from_ts"]),
                                    parse_at(f["to_ts"]) if f.get("to_ts") else None, f["entered_by"], f.get("note") or None)
            message = f"Recorded {a.kind.lower()} for {a.employee_id}: {fmt_ist(a.from_ts)} to {fmt_ist(a.to_ts)}."
    except DomainError as e:
        error = f"{e.rule + ': ' if e.rule else ''}{e.message}"
    except (KeyError, ValueError) as e:
        error = f"Missing or invalid field: {e}"
    with db.session() as s:
        return _render(request, "leave.html", _leave_ctx(request, s, f["office_id"], now_utc(), message=message, error=error))
