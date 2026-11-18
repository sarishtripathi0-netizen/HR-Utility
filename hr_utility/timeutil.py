"""Time handling: store UTC, display Asia/Kolkata, parse ?at= values."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

# Asia/Kolkata has had a fixed +05:30 offset with no DST since 1945, so a fixed offset is exact
# and avoids depending on the tzdata package on Windows.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")
UTC = timezone.utc


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_utc(dt: datetime) -> datetime:
    """Naive datetimes are read as IST (the users' wall clock)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(UTC)


def to_ist(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(IST)


def iso_ist(dt: datetime | None) -> str | None:
    d = to_ist(dt)
    return d.isoformat() if d else None


def fmt_ist(dt: datetime | None) -> str:
    d = to_ist(dt)
    return d.strftime("%d-%m-%Y %H:%M IST") if d else "—"


def parse_at(value: str | None, *, end_of_day: bool = False) -> datetime:
    """Parse an ISO timestamp or date. Missing means now. A date means 00:00 IST that day,
    or 00:00 IST the next day when end_of_day is set (an inclusive end date)."""
    if value is None or str(value).strip() == "":
        return now_utc()
    v = str(value).strip()
    if " " in v and "T" not in v:
        v = v.replace(" ", "T", 1)
    if "T" in v and " " in v:  # an un-encoded "+05:30" arrives as " 05:30"
        v = v.replace(" ", "+")
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    if len(v) == 10:
        d = date.fromisoformat(v)
        if end_of_day:
            d = d + timedelta(days=1)
        return datetime.combine(d, time(0, 0), IST).astimezone(UTC)
    return to_utc(datetime.fromisoformat(v))


def ist_date(dt: datetime) -> date:
    return to_ist(dt).date()


def ist_midnight(d: date) -> datetime:
    return datetime.combine(d, time(0, 0), IST).astimezone(UTC)
