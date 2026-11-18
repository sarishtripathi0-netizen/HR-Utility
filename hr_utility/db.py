"""Engine, sessions, schema and the append-only guards (BR-10)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

# Tables owned by the HR Utility. No row is ever deleted; only superseded_by may change.
VERSIONED_TABLES = {
    "posting": "superseded_by",
    "function_allotment": "superseded_by",
    "availability": "superseded_by",
    "vacancy_declaration": "superseded_by",
}
# Workflow status columns that may move forward (the row itself is never removed).
STATUS_TABLES = {
    "onboarding_request": ("status", "employee_id", "reason"),
    "event_outbox": ("delivered",),
    "iam_session": ("active_post_id", "revoked_at", "revoke_reason"),
}
APPEND_ONLY_TABLES = ("audit_log",)


def make_engine(db_path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", future=True, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def _columns(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]


def _add_missing_columns(conn) -> None:
    """Columns added to a model after a database was created are added in place (data is never dropped).
    Version triggers are recreated afterwards so they cover the new columns."""
    for table in Base.metadata.sorted_tables:
        have = set(_columns(conn, table.name))
        for col in table.columns:
            if col.name in have:
                continue
            default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
            ddl = f"ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(conn.dialect)}"
            if default is not None:
                ddl += f" DEFAULT {int(default) if isinstance(default, bool) else repr(default)}"
            conn.execute(text(ddl))
            conn.execute(text(f"DROP TRIGGER IF EXISTS {table.name}_frozen"))


def init_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        _add_missing_columns(conn)
    with engine.begin() as conn:
        owned = list(VERSIONED_TABLES) + list(STATUS_TABLES) + list(APPEND_ONLY_TABLES)
        for table in owned:
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_delete BEFORE DELETE ON {table} "
                f"BEGIN SELECT RAISE(ABORT, 'BR-10: rows in {table} are never deleted'); END"
            ))
        for table, mutable in list(VERSIONED_TABLES.items()) + list(STATUS_TABLES.items()):
            mutable_cols = {mutable} if isinstance(mutable, str) else set(mutable)
            frozen = [c for c in _columns(conn, table) if c not in mutable_cols]
            cond = " OR ".join(f"OLD.{c} IS NOT NEW.{c}" for c in frozen)
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS {table}_frozen BEFORE UPDATE ON {table} "
                f"WHEN {cond} BEGIN SELECT RAISE(ABORT, 'BR-10: write a superseding row instead of editing {table}'); END"
            ))
        for table in APPEND_ONLY_TABLES:
            conn.execute(text(
                f"CREATE TRIGGER IF NOT EXISTS {table}_no_update BEFORE UPDATE ON {table} "
                f"BEGIN SELECT RAISE(ABORT, 'BR-10: {table} is append-only'); END"
            ))


class Database:
    def __init__(self, db_path: Path | str):
        self.engine = make_engine(db_path)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, future=True)

    def init(self) -> None:
        init_schema(self.engine)

    @contextmanager
    def session(self):
        s: Session = self.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()
