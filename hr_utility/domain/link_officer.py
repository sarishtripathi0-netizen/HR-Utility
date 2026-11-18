"""BR-07: the Link Officer, from MDM's link-officer rules plus the local ARTPS condition (decision 03-11-2026).

MDM says, per office type and absent designation, which designations cover it and in what priority. The HR
Utility decides who covers on the day: rules are tried by priority; within one priority every officer posted in the
same office, available, holding a covering designation (and the required function, where a condition applies) is a
candidate, and the senior-most wins. In practice:
 - DC and co-district office: the ADC/AC holding ARTPS, senior-most if several (ARTPS_HOLDER);
 - circle office: the other Circle Officer (SAME_POST), else the Sub Registrar of the circle office (SUB_REGISTRAR).
No rule for the post: NOT_APPLICABLE. Rules apply but nobody qualifies: NO_LINK_OFFICER with the reason. Never guess.
The output names the rule step and sets deemed_dps_under_rule_3_3 = true.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import MdmEmployee, MdmLinkOfficerRule, MdmSanctionedPost
from ..timeutil import fmt_ist
from . import queries as q


@dataclass
class LinkResult:
    status: str  # RESOLVED | NOT_REQUIRED | NO_LINK_OFFICER | NOT_APPLICABLE
    sanctioned_post_id: str
    at: datetime
    employee: MdmEmployee | None = None
    via_post: MdmSanctionedPost | None = None
    rule_step: str | None = None
    reason: str | None = None
    absent: list[dict] = field(default_factory=list)

    def link_officer(self) -> dict | None:
        if self.status != "RESOLVED":
            return None
        return {"employee_id": self.employee.employee_id, "name": self.employee.name,
                "sanctioned_post_id": self.via_post.sanctioned_post_id, "rule_step": self.rule_step,
                "deemed_dps_under_rule_3_3": True, "is_demo": bool(self.employee.is_demo)}


def rules_for(s: Session, office_type: str, post_code: str) -> list[MdmLinkOfficerRule]:
    rows = s.scalars(select(MdmLinkOfficerRule).where(MdmLinkOfficerRule.office_type == office_type,
                                                      MdmLinkOfficerRule.post_code.in_((post_code, "*"))))
    return sorted(rows, key=lambda r: (r.priority, r.post_code == "*", r.code))


def _step(rule: MdmLinkOfficerRule, absent_post: str) -> str:
    if rule.required_function:
        return f"{rule.required_function}_HOLDER"
    return "SAME_POST" if rule.covering_post_code == absent_post else rule.covering_post_code


def resolve(s: Session, settings: Settings, sanctioned_post_id: str, t: datetime,
            absent_employee_ids: set[str] | None = None) -> LinkResult:
    """Resolve the Link Officer for a chair. If absent_employee_ids is given (seat lookup), those officers are
    treated as the absent holders; otherwise the chair's own holders are checked for availability."""
    sp = q.chair(s, sanctioned_post_id)
    office = q.office(s, sp.office_id)
    rules = rules_for(s, office.office_type, sp.post_code)
    if not rules:
        return LinkResult("NOT_APPLICABLE", sp.sanctioned_post_id, t,
                          reason=f"No Link Officer rule covers post {sp.post_code} in a {office.office_type} "
                                 f"(MDM link-officer-rule, or data/config/link_officer_local.csv).")

    if absent_employee_ids is None:
        absent_employee_ids = set()
        for p in q.postings_at(s, t, sanctioned_post_id=sp.sanctioned_post_id):
            ok, _ = q.availability_at(s, p.employee_id, t)
            if ok:
                return LinkResult("NOT_REQUIRED", sp.sanctioned_post_id, t,
                                  reason=f"{q.employee(s, p.employee_id).name} holds the post and is available.")
            absent_employee_ids.add(p.employee_id)
    absent = []
    for eid in sorted(absent_employee_ids):
        _, why = q.availability_at(s, eid, t)
        absent.append({**q.employee_view(q.employee(s, eid)), "unavailable_reason": why})

    # Everyone posted in O at t, available, and not an absent holder: their chairs in O.
    present: dict[str, list[tuple[MdmSanctionedPost, str]]] = {}
    for p in q.postings_at(s, t, office_id=office.office_id):
        if p.employee_id in absent_employee_ids:
            continue
        present.setdefault(p.employee_id, []).append((q.chair(s, p.sanctioned_post_id), p.charge_type))
    present = {eid: chairs for eid, chairs in present.items() if q.availability_at(s, eid, t)[0]}

    tried = []
    for priority, group in groupby(rules, key=lambda r: r.priority):
        group = list(group)
        pool = []
        for eid, chairs in present.items():
            for rule in group:
                fitting = [c for c in chairs if c[0].post_code == rule.covering_post_code]
                if not fitting:
                    continue
                if rule.required_function and not q.holds_function(s, eid, office.office_id, rule.required_function, t):
                    continue
                chair = sorted(fitting, key=lambda c: (c[1] != "SUBSTANTIVE", c[0].sanctioned_post_id))[0][0]
                pool.append((q.employee(s, eid), chair, rule))
                break
        if pool:
            emp, chair, rule = sorted(pool, key=lambda x: q.seniority_key(x[0]))[0]
            return LinkResult("RESOLVED", sp.sanctioned_post_id, t, emp, chair, _step(rule, sp.post_code), absent=absent)
        tried.append(f"priority {priority}: " + " or ".join(
            f"{r.covering_post_code}{' holding ' + r.required_function if r.required_function else ''}" for r in group))

    who = ", ".join(f"{a['name']} ({a['unavailable_reason']})" for a in absent) or "no holder"
    return LinkResult(
        "NO_LINK_OFFICER", sp.sanctioned_post_id, t, absent=absent,
        reason=(f"Nobody in {office.office_id} qualifies at {fmt_ist(t)} ({'; '.join(tried)}). "
                f"Absent: {who}. No Link Officer is guessed."))
