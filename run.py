"""One command: build the seed if needed, load the database if needed, and serve the API + screens.

    python run.py                 serve on http://127.0.0.1:8000 (builds seed + DB on first run) and keep the
                                  MDM copy fresh from the MDM PoC in data/config/mdm.json
    python run.py --reset         rebuild the seed from ./data and start from a fresh database
    python run.py --pull-mdm      save a fresh MDM snapshot to data/mdm_snapshot/, then rebuild (implies --reset)
    (first time only: python -m seed.mdm_load --execute   sends the roster to MDM; MDM mints the Employee IDs)
    python run.py --offline       do not contact MDM (serve the seed snapshot only)
    python run.py --no-serve      prepare only
    python run.py --export-openapi docs   write docs/openapi.json, openapi.yaml, swagger.html (then serves unless --no-serve)
    python run.py --register-mdm --public-url http://<this-machine>:8000
                                  register this service as an MDM consumer (MDM calls <public-url>/hr/usage/...)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hr_utility.config import Settings


def main() -> int:
    ap = argparse.ArgumentParser(description="Sewa Setu 2.0 HR Utility PoC")
    ap.add_argument("--reset", action="store_true", help="rebuild seed and database from ./data")
    ap.add_argument("--pull-mdm", action="store_true", help="refresh data/mdm_snapshot from MDM, then rebuild")
    ap.add_argument("--offline", action="store_true", help="do not contact MDM")
    ap.add_argument("--no-serve", action="store_true", help="prepare seed and database, then exit")
    ap.add_argument("--export-openapi", metavar="DIR", help="write openapi.json, openapi.yaml and swagger.html to DIR")
    ap.add_argument("--register-mdm", action="store_true", help="register as an MDM consumer, then continue")
    ap.add_argument("--public-url", help="address MDM can reach this service on (for --register-mdm)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    settings = Settings()
    if args.offline:
        settings.mdm_base_url = None
    if args.pull_mdm:
        if not settings.mdm_base_url:
            print("--pull-mdm needs an MDM URL (data/config/mdm.json or HRU_MDM_URL)")
            return 2
        from seed.mdm_pull import pull

        print(json.dumps(pull(settings.mdm_base_url, settings.data_dir / "mdm_snapshot"), indent=2))
        args.reset = True
    if args.reset:
        from hr_utility.mdm.seed_client import SeedMdmClient

        # The DB plus the MDM stand-in's stores (minted employees, corrections, chairs added or abolished).
        for p in (settings.db_path, *SeedMdmClient.store_paths(settings.resolved_minted_store())):
            if p.exists():
                p.unlink()
    if args.reset or not (settings.data_dir / "hr_seed" / "postings.csv").exists():
        from seed.bind import BindError, bind
        from seed.build import build

        print("Building the roster plan from ./data ...")
        print(json.dumps(build(settings.data_dir), indent=2))
        print("Binding it to MDM codes (Employee IDs, chairs) ...")
        try:
            print(json.dumps(bind(settings.data_dir), indent=2))
        except BindError as e:
            print(f"Cannot bind to MDM: {e}")
            return 2
        print(f"Load report: {settings.data_dir / 'load_report.md'}")
    if not settings.db_path.exists():
        from seed.load import load

        print("Loading database ...")
        print(json.dumps(load(settings), indent=2))

    from hr_utility.api.app import create_app

    app = create_app(settings)
    if args.export_openapi:
        from hr_utility.api.docs_export import export

        for path in export(app, Path(args.export_openapi), args.public_url or settings.public_url):
            print(f"written: {path}")
    if args.register_mdm:
        public = args.public_url or settings.public_url
        if not (settings.mdm_base_url and public):
            print("--register-mdm needs an MDM URL and --public-url (an address MDM can reach)")
            return 2
        res = app.state.mdm.register_consumer(settings.mdm_consumer_code, settings.mdm_consumer_name,
                                              f"{public.rstrip('/')}/hr/usage", actor=settings.mdm_consumer_code)
        print("Registered with MDM:", json.dumps(res))
    if args.no_serve:
        return 0

    import uvicorn

    mode = f"MDM live: {settings.mdm_base_url}" if settings.mdm_base_url else "MDM offline (seed snapshot)"
    print(f"HR Utility on http://{args.host}:{args.port}/  ({mode}; API docs: /docs)")
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
