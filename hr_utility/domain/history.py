"""BR-08: who held a chair over an interval, with exact sub-intervals and working days per holder.

Working days exclude Sundays and MDM holidays (IST calendar): state-wide holidays, and LOCAL holidays of the
office's own district. RESTRICTED (optional) holidays count as working days. A day is counted for every IST date d with
date(start) <= d < date(end) of the holder's sub-interval, so the day of a mid-day handover counts for the
incoming holder (open item 13 in CLAUDE.md).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import MdmHoliday
from ..timeutil import ist_date, iso_ist
from . import queries as q
from .common import InvalidInput, merge_intervals


def holidays(s: Session, district_code: str | None = None) -> set[date]:
    """Days the office is closed: state-wide holidays plus LOCAL ones for this district. RESTRICTED (optional)
    holidays are working days."""
    out = set()
    for h in s.scalars(select(MdmHoliday).where(MdmHoliday.is_active.is_(True))):
        if (h.holiday_type or "").upper() == "RESTRICTED":
            continue
        if h.district_code and h.district_code != district_code:
            continue
        out.add(date.fromisoformat(h.holiday_date))
    return out


def working_dates(start: datetime, end: datetime, hols: set[date]) -> set[date]:
    out = set()
    d, last = ist_date(start), ist_date(end)
    while d < last:
        if d.weekday() != 6 and d not in hols:
            out.add(d)
        d += timedelta(days=1)
    return out


def post_history(s: Session, sanctioned_post_id: str, frm: datetime, to: datetime) -> dict:
    if to <= frm:
        raise InvalidInput("'to' must be after 'from'")
    sp = q.chair(s, sanctioned_post_id)
    hols = holidays(s, q.office(s, sp.office_id).district_code)
    groups: dict[tuple[str, str], list[tuple[datetime, datetime]]] = {}
    for p in q.current_postings(s, sanctioned_post_id=sp.sanctioned_post_id):
        a = max(p.effective_from, frm)
        b = min(p.effective_to, to) if p.effective_to else to
        if a < b:
            groups.setdefault((p.employee_id, p.charge_type), []).append((a, b))

    holders = []
    for (eid, charge), spans in groups.items():
        spans = merge_intervals(spans)
        days = set()
        for a, b in spans:
            days |= working_dates(a, b, hols)
        emp = q.employee(s, eid)
        holders.append({
            **q.employee_view(emp), "charge_type": charge,
            "intervals": [{"from": iso_ist(a), "to": iso_ist(b)} for a, b in spans],
            "working_days": len(days),
        })
    holders.sort(key=lambda h: (h["intervals"][0]["from"], h["charge_type"] != "SUBSTANTIVE"))

    covered = merge_intervals((a, b) for spans in groups.values() for a, b in spans)
    gaps, cursor = [], frm
    for a, b in covered:
        if a > cursor:
            gaps.append({"from": iso_ist(cursor), "to": iso_ist(a)})
        cursor = max(cursor, b)
    if cursor < to:
        gaps.append({"from": iso_ist(cursor), "to": iso_ist(to)})

    return {
        "sanctioned_post_id": sp.sanctioned_post_id, "office_id": sp.office_id, "post_code": sp.post_code,
        "from": iso_ist(frm), "to": iso_ist(to), "holders": holders, "unheld_intervals": gaps,
        "working_days_in_interval": len(working_dates(frm, to, hols)),
        "working_day_rule": "Sundays and MDM holidays (state-wide, plus local ones for this district; restricted holidays "
                            "are working days) excluded; IST calendar days; a handover day counts for the incoming holder.",
        "holidays_in_interval": sorted(d.isoformat() for d in hols if ist_date(frm) <= d < ist_date(to)),
    }
