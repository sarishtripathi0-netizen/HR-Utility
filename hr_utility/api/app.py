"""FastAPI application factory."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ..config import Settings
from ..db import Database
from ..domain.common import DomainError
from ..mdm.http_client import HttpMdmClient
from ..mdm.mapping import WATCHED_TYPES
from ..mdm.seed_client import SeedMdmClient
from ..mdm.sync import ensure_fresh, sync_state
from ..timeutil import iso_ist
from . import routes_crud, routes_iam, routes_mdm, routes_read, routes_write

log = logging.getLogger(__name__)

DESCRIPTION = """
**Sewa Setu 2.0 — HR Utility (PoC).** Answers: *who sits in which chair, holding which functions, as of any time.*

* Every read accepts `?at=` (ISO-8601; naive = IST; date = 00:00 IST). Default: now.
* Timestamps are returned in Asia/Kolkata (+05:30). Every officer object carries `is_demo`.
* Business-rule refusals return **409** `{"error": {"rule": "BR-xx", "message": "..."}}`.
* Offices, office types, designations and holidays come from the **MDM PoC**; every response carries
  `X-MDM-Source`, `X-MDM-Version` and `X-MDM-Synced-At` (freshness of that copy).
* The IAM endpoints are a **stub** with no authentication.
* Nothing is ever deleted: ends and corrections write a new row and keep the old one (BR-10).

Reference: `docs/api.md` (endpoints with examples) and `docs/integration.md` (how each consumer calls this service).
"""

API_VERSION = "0.3.0"

TAGS = [
    {"name": "Rule Engine", "description": "The core question: who holds post P with function F in office O at time t, "
                                           "are they available, and if not, who is the Link Officer (BR-06, BR-07, BR-08)."},
    {"name": "IAM", "description": "Posts an officer holds at time t (substantive, additional, link charge) — what IAM "
                                   "offers the officer to act as."},
    {"name": "Workflow", "description": "Office roster: every chair, its holders, their functions and availability."},
    {"name": "Establishment", "description": "Writes by the Establishment branch: onboarding (BR-09), joining and relieving "
                                             "(BR-01..03), function allotment (BR-04), leave and tour (BR-06), declare vacant. "
                                             "Refusals return 409 with the rule number."},
    {"name": "Records", "description": "Record management: search and view officers, correct records, chairs (MDM "
                                       "sanctioned count), postings, leave windows, audit log. No deletes — ends are new rows."},
    {"name": "Events", "description": "Outbox of posting.*, charge.*, function.*, availability.*, employee.onboarded events. "
                                      "Poll with `?after=<last id>`; act when `effective_at <= now`."},
    {"name": "IAM stub", "description": "Login / switch post / revoke — a **stub** with no authentication, for demos only."},
    {"name": "MDM integration", "description": "The usage callback MDM calls before deactivating a record, and the "
                                               "freshness of this service's copy of MDM masters."},
]


def build_mdm_client(settings: Settings):
    """The single place that chooses the MDM adapter."""
    if settings.mdm_base_url:
        return HttpMdmClient(settings.mdm_base_url, settings.data_dir, settings.resolved_minted_store(),
                             timeout=settings.mdm_timeout_s, actor=settings.mdm_consumer_code)
    return SeedMdmClient(settings.data_dir, settings.resolved_minted_store())


def check_mdm(app: FastAPI) -> dict:
    with app.state.db.session() as s:
        status = ensure_fresh(s, app.state.mdm, WATCHED_TYPES)
    app.state.mdm_status = status
    log.info("MDM freshness: %s", status)
    return status


def _background_sync(app: FastAPI, stop: threading.Event) -> None:
    while not stop.wait(app.state.settings.mdm_sync_interval_s):
        try:
            check_mdm(app)
        except Exception:  # noqa: BLE001 - never let the sync thread die
            log.exception("background MDM sync failed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    db = Database(settings.db_path)
    db.init()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = threading.Event()
        if isinstance(app.state.mdm, HttpMdmClient):
            check_mdm(app)
            if settings.mdm_sync_interval_s > 0:
                threading.Thread(target=_background_sync, args=(app, stop), daemon=True, name="mdm-sync").start()
        yield
        stop.set()

    app = FastAPI(title="Sewa Setu 2.0 — HR Utility (PoC)", version=API_VERSION, description=DESCRIPTION,
                  openapi_tags=TAGS, lifespan=lifespan,
                  contact={"name": "Sewa Setu 2.0 — HR Utility PoC team"},
                  swagger_ui_parameters={"docExpansion": "none", "defaultModelsExpandDepth": 0, "tryItOutEnabled": True,
                                         "displayRequestDuration": True, "filter": True})
    app.state.settings = settings
    app.state.db = db
    app.state.mdm = build_mdm_client(settings)
    app.state.mdm_status = {"status": "NOT_CHECKED"}

    @app.middleware("http")
    async def _mdm_freshness(request: Request, call_next):
        response = await call_next(request)
        with app.state.db.session() as s:
            st = sync_state(s)
        response.headers["X-MDM-Source"] = st.source if st else "SEED"
        response.headers["X-MDM-Version"] = str(st.applied_version) if st and st.applied_version else "unknown"
        response.headers["X-MDM-Synced-At"] = iso_ist(st.last_synced_at) if st and st.last_synced_at else "never"
        if st and st.last_error:
            response.headers["X-MDM-Stale"] = "true"
        return response

    @app.exception_handler(DomainError)
    async def _domain_error(_: Request, exc: DomainError):
        return JSONResponse(status_code=exc.status, content={"error": exc.to_dict()})

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        msg = "; ".join(f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=422, content={"error": {"rule": None, "message": msg}})

    app.include_router(routes_read.router)
    app.include_router(routes_crud.router)
    app.include_router(routes_write.router)
    app.include_router(routes_iam.router)
    app.include_router(routes_mdm.router)

    from ..web.crud_routes import router as crud_web_router  # noqa: PLC0415 - screens are optional for API-only use
    from ..web.routes import router as web_router  # noqa: PLC0415

    app.include_router(web_router)
    app.include_router(crud_web_router)
    return app
