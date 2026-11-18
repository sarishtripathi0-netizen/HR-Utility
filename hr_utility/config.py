"""Runtime settings. Every value that is not a settled government fact is configurable here."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _mdm_config() -> dict:
    p = ROOT / "data" / "config" / "mdm.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _default_mdm_url() -> str | None:
    """HRU_MDM_URL overrides data/config/mdm.json; set it to 'off' (or empty) to run on the offline seed only."""
    env = os.environ.get("HRU_MDM_URL")
    if env is not None:
        return None if env.strip().lower() in ("", "off", "none") else env.strip()
    return _mdm_config().get("base_url")


@dataclass
class Settings:
    db_path: Path = ROOT / "hr_utility.db"
    data_dir: Path = ROOT / "data"
    # Where SeedMdmClient keeps employees it mints after the seed (simulates MDM's own store).
    minted_store_path: Path | None = None

    # Live MDM PoC (None = offline: the seed snapshot only).
    mdm_base_url: str | None = field(default_factory=_default_mdm_url)
    mdm_timeout_s: float = 10.0
    mdm_sync_interval_s: int = 300  # background version check; 0 disables it
    mdm_consumer_code: str = field(default_factory=lambda: _mdm_config().get("consumer_code", "hr-utility-poc"))
    mdm_consumer_name: str = field(default_factory=lambda: _mdm_config().get("consumer_name", "HR Utility PoC"))
    # The address MDM can reach this service on (for the usage callback). Needed only to register as a consumer.
    public_url: str | None = field(default_factory=lambda: os.environ.get("HRU_PUBLIC_URL"))

    # Option B (whole-office roster): seat lookups ignore function. Off by default (Option A).
    roster_mode: bool = False

    # The Link Officer comes from data/config/link_officer_rules.csv (hard-coded rules, decided 03-11-2026).

    # BR-09: salted hash of the Aadhaar token. Replace the default outside development.
    aadhaar_salt: str = field(default_factory=lambda: os.environ.get("HRU_AADHAAR_SALT", "dev-only-salt-change-me"))

    def resolved_minted_store(self) -> Path:
        return self.minted_store_path or self.db_path.with_suffix(".minted.jsonl")
