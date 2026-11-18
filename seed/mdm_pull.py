"""Save MDM snapshots to data/mdm_snapshot/ so the seed (and the tests) are reproducible offline.

    python -m seed.mdm_pull                       uses data/config/mdm.json base_url
    python -m seed.mdm_pull --base-url http://172.16.5.151:4001
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from hr_utility.mdm.mapping import SNAPSHOT_TYPES, load_mdm_config

ROOT = Path(__file__).resolve().parent.parent


def pull(base_url: str, out_dir: Path, timeout: float = 60.0) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout) as c:
        version = c.get("/mdm/version")
        version.raise_for_status()
        (out_dir / "version.json").write_text(json.dumps(version.json(), indent=2), encoding="utf-8")
        for t in SNAPSHOT_TYPES:
            r = c.get(f"/mdm/snapshot/{t}", params={"includeInactive": "true"})
            r.raise_for_status()
            body = r.json()
            (out_dir / f"{t}.json").write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")
            counts[t] = body.get("count", len(body.get("records", [])))
    return {"base_url": base_url, "version": version.json().get("global"), "counts": counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=None)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    base = args.base_url or load_mdm_config(ROOT / "data")["base_url"]
    print(json.dumps(pull(base, ROOT / "data" / "mdm_snapshot"), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
