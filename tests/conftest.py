"""Test fixtures: build the seed from ./data once per session (into a temp copy), load a template DB once,
and give every test its own copy of that DB."""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from hr_utility.config import Settings
from hr_utility.db import Database
from hr_utility.models import MdmEmployee
from hr_utility.timeutil import IST, UTC
from seed.bind import bind
from seed.build import build
from seed.load import load

REPO_DATA = Path(__file__).resolve().parent.parent / "data"
# BR-08 / H11 count working days in December 2026. MDM's calendar has Christmas (25-12-2026) as a gazetted
# holiday; if a snapshot ever lacks it, a synthetic test-only row stands in so the expected counts still hold.
TEST_HOLIDAY_DATE = "2026-12-25"


def ist(y, m, d, hh=0, mm=0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST).astimezone(UTC)


@pytest.fixture(scope="session")
def seed_dir(tmp_path_factory) -> Path:
    data = tmp_path_factory.mktemp("data")
    for f in REPO_DATA.iterdir():
        if f.is_file() and f.suffix.lower() in (".xlsx", ".pdf"):
            shutil.copy(f, data / f.name)
    for d in ("config", "mdm_snapshot", "mdm_load"):  # the MDM snapshot + load ledger make the tests offline
        shutil.copytree(REPO_DATA / d, data / d)
    build(data)
    bind(data)
    hol = data / "mdm_snapshot" / "holiday.json"
    body = json.loads(hol.read_text(encoding="utf-8"))
    if TEST_HOLIDAY_DATE not in {r["date"] for r in body["records"]}:
        body["records"].append({"code": f"TEST-{TEST_HOLIDAY_DATE}", "date": TEST_HOLIDAY_DATE, "name": "TEST HOLIDAY",
                                "holidayType": "GAZETTED", "districtCode": None, "isActive": True})
        hol.write_text(json.dumps(body), encoding="utf-8")
    return data


@pytest.fixture(scope="session")
def template_db(seed_dir, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("template") / "template.db"
    load(Settings(db_path=path, data_dir=seed_dir, minted_store_path=path.with_suffix(".minted.jsonl"), mdm_base_url=None))
    return path


@pytest.fixture
def settings(template_db, seed_dir, tmp_path) -> Settings:
    db_path = tmp_path / "hr.db"
    shutil.copy(template_db, db_path)
    return Settings(db_path=db_path, data_dir=seed_dir, minted_store_path=tmp_path / "minted.jsonl", mdm_base_url=None)


@pytest.fixture
def db(settings) -> Database:
    d = Database(settings.db_path)
    yield d
    d.engine.dispose()


@pytest.fixture
def client(settings):
    from fastapi.testclient import TestClient

    from hr_utility.api.app import create_app

    app = create_app(settings)
    with TestClient(app) as c:
        yield c
    app.state.db.engine.dispose()


def emp_id(s, name: str) -> str:
    return s.scalars(select(MdmEmployee.employee_id).where(MdmEmployee.name == name)).one()
