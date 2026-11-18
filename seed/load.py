"""Load the generated seed into a fresh database, through the domain layer (so every rule and audit applies)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from hr_utility.config import Settings
from hr_utility.db import Database
from hr_utility.domain import functions, postings
from hr_utility.mdm.seed_client import SeedMdmClient
from hr_utility.mdm.sync import record_sync, refresh_cache
from hr_utility.timeutil import parse_at

SEED_ACTOR = "SEED-LOADER"


def _rows(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load(settings: Settings) -> dict:
    if settings.db_path.exists():
        raise FileExistsError(f"{settings.db_path} exists; delete it or run `python run.py --reset`")
    db = Database(settings.db_path)
    db.init()
    client = SeedMdmClient(settings.data_dir, settings.resolved_minted_store())
    hr = settings.data_dir / "hr_seed"
    with db.session() as s:
        counts = refresh_cache(s, client)
        snap = settings.data_dir / "mdm_snapshot" / "version.json"
        if snap.exists():  # freshness = the MDM snapshot the seed was built from
            record_sync(s, "SNAPSHOT", json.loads(snap.read_text(encoding="utf-8")), synced=True)
        n_post = n_fn = 0
        for r in _rows(hr / "postings.csv"):
            postings.join(s, postings.JoinRequest(
                employee_id=r["employee_id"], sanctioned_post_id=r["sanctioned_post_id"], charge_type=r["charge_type"],
                effective_from=parse_at(r["effective_from"]), order_ref=r["order_ref"],
                issuing_department=r["issuing_department"], entered_by=SEED_ACTOR, note=r["note"] or None,
            ))
            n_post += 1
        for r in _rows(hr / "function_allotments.csv"):
            functions.allot(s, r["employee_id"], r["office_id"], r["function_code"], parse_at(r["effective_from"]),
                            entered_by=f"ESTB@{r['office_id']}", is_demo=r["is_demo"] == "True",
                            source_ref=r["source_ref"], actor=f"{SEED_ACTOR} for ESTB@{r['office_id']}")
            n_fn += 1
    return {**counts, "posting": n_post, "function_allotment": n_fn}
