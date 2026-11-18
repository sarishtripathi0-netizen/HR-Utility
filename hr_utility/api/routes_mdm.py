"""MDM integration endpoints: the usage callback MDM calls before deactivating a record, and sync status."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..domain.usage import usage
from ..mdm.mapping import SNAPSHOT_TYPES
from ..mdm.sync import sync_state
from ..timeutil import iso_ist
from .deps import get_session
from .schemas import MdmStatusResponse, UsageResponse

router = APIRouter(tags=["MDM integration"])


@router.get("/hr/usage/{entity_type}/{code}", response_model=UsageResponse,
            summary="MDM usage callback: is this MDM record still used by HR?",
            description="Called by MDM before it deactivates a record. `inUse` is true while officers are posted, or "
                        "functions allotted, under it. Supported: office, district, designation, sanctioned-post, "
                        "employee, function, cadre, holiday.")
def mdm_usage(entity_type: str, code: str, s: Session = Depends(get_session)):
    return usage(s, entity_type, code)


@router.get("/v1/mdm/status", response_model=MdmStatusResponse, summary="Freshness of the HR Utility's copy of MDM data")
def mdm_status(request: Request, s: Session = Depends(get_session)):
    st = sync_state(s)
    mdm = request.app.state.mdm
    return {
        "mode": "LIVE" if getattr(mdm, "base_url", None) else "OFFLINE_SEED",
        "base_url": getattr(mdm, "base_url", None),
        "source": st.source if st else None,
        "applied_version": st.applied_version if st else None,
        "entity_versions": json.loads(st.versions_json) if st and st.versions_json else {},
        "last_checked_at": iso_ist(st.last_checked_at) if st else None,
        "last_synced_at": iso_ist(st.last_synced_at) if st else None,
        "last_error": st.last_error if st else None,
        "last_check": request.app.state.mdm_status,
        "consumer_code": request.app.state.settings.mdm_consumer_code,
        "copied_from_mdm": list(SNAPSHOT_TYPES),
        "local_until_mdm_has_them": ["demo officers and demo-only chairs", "ACMR-00ASM (Registrar office)",
                                     "batch year, DOB, retirement date, demo flag",
                                     "Link Officer ARTPS condition", "FinAssam / PAN / Aadhaar-hash de-duplication"],
    }
