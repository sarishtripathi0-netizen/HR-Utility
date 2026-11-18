"""Request and response models: the frozen integration contract published at /openapi.json.

Timestamps are ISO-8601 strings in Asia/Kolkata (+05:30). Every object that names an officer carries is_demo.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChargeType = Literal["SUBSTANTIVE", "ADDITIONAL"]
# The Link Officer rule that selected the officer, from data/config/link_officer_rules.csv:
# ARTPS_HOLDER (DC / co-district office), OTHER_CO and SUB_REGISTRAR (circle office), CIRCLE_OFFICER, or a code
# added with a new row.
RuleStep = str


class ErrorBody(BaseModel):
    rule: str | None = Field(None, description="Business rule that refused the request, e.g. BR-03")
    message: str


class ErrorResponse(BaseModel):
    error: ErrorBody


# ---------------------------------------------------------------- reads

class SeatHolder(BaseModel):
    sanctioned_post_id: str
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    charge_type: ChargeType
    available: bool
    unavailable_reason: str | None = Field(None, description="LEAVE | TOUR | TRAINING | DEPUTATION | NOT_POSTED")
    is_demo: bool


class LinkOfficer(BaseModel):
    employee_id: str
    name: str
    sanctioned_post_id: str = Field(description="The chair through which the Link Officer qualifies")
    rule_step: RuleStep
    deemed_dps_under_rule_3_3: bool = Field(True, title="Deemed under rule 3(3)")
    is_demo: bool


class SeatHoldersResponse(BaseModel):
    office_id: str
    post_code: str
    function_code: str | None
    at: str
    holders: list[SeatHolder] = Field(description="Seniority order: year_of_joining ascending, then name")
    link_officer: LinkOfficer | None = Field(description="Set only when no holder is available")
    status: Literal["RESOLVED", "NO_HOLDER", "NO_LINK_OFFICER"]
    reason: str | None
    roster_mode: bool = Field(False, description="True when Option B (ignore function) is configured")


class ChairHolder(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    posting_id: int
    charge_type: ChargeType
    since: str
    until: str | None
    order_ref: str
    issuing_department: str
    available: bool
    unavailable_reason: str | None
    unavailable_until: str | None
    functions: list[str] = Field(description="Every function held in this office: allotted plus held by post")
    functions_allotted: list[str] = Field(description="Functions from function_allotment rows only")
    holds_all_office_functions: bool = Field(description="True when the post holds every function of the office "
                                                         "(e.g. Circle Officer)")


class Vacancy(BaseModel):
    since: str
    reason: str
    entered_by: str


class ChairResponse(BaseModel):
    sanctioned_post_id: str
    office_id: str
    post_code: str
    rank_order: int
    derived: bool
    at: str
    status: Literal["HELD", "DECLARED_VACANT", "UNHELD"]
    holders: list[ChairHolder]
    vacancy: Vacancy | None
    link_officer: LinkOfficer | None
    link_status: str | None = None
    link_reason: str | None = None


class AbsentHolder(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    unavailable_reason: str | None


class LinkOfficerResponse(BaseModel):
    sanctioned_post_id: str
    at: str
    status: Literal["RESOLVED", "NOT_REQUIRED", "NO_LINK_OFFICER", "NOT_APPLICABLE"]
    link_officer: LinkOfficer | None
    reason: str | None
    absent_holders: list[AbsentHolder]


class Interval(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str


class HistoryHolder(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    charge_type: ChargeType
    intervals: list[Interval]
    working_days: int


class HistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    sanctioned_post_id: str
    office_id: str
    post_code: str
    from_: str = Field(alias="from")
    to: str
    holders: list[HistoryHolder]
    unheld_intervals: list[Interval]
    working_days_in_interval: int
    working_day_rule: str
    holidays_in_interval: list[str]


class CoveredHolder(BaseModel):
    employee_id: str
    name: str
    unavailable_reason: str | None
    is_demo: bool


class EmployeePost(BaseModel):
    sanctioned_post_id: str
    office_id: str
    post_code: str
    charge_type: Literal["SUBSTANTIVE", "ADDITIONAL", "LINK"]
    posting_id: int | None = None
    since: str | None = None
    until: str | None = None
    rule_step: RuleStep | None = None
    deemed_dps_under_rule_3_3: bool | None = Field(None, title="Deemed under rule 3(3)")
    covering_for: list[CoveredHolder] | None = None


class EmployeePostsResponse(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    at: str
    available: bool
    unavailable_reason: str | None
    posts: list[EmployeePost]


class RosterResponse(BaseModel):
    office_id: str
    name: str
    office_type: str
    district_code: str
    district_name: str | None
    parent_office_id: str | None
    provisional_id: bool
    external_ref: str | None = Field(None, description="Cross-walk to another code list, e.g. a Geo Master circle code")
    establishment_actor: str
    at: str
    chairs: list[ChairResponse]


class CatalogueFunction(BaseModel):
    function_code: str
    name: str
    category: str | None
    is_demo: bool


class OfficeTypeFunctions(BaseModel):
    office_type: str
    functions: list[CatalogueFunction]


class PostFunctionRule(BaseModel):
    post_code: str
    post_name: str
    rank_order: int
    mode: Literal["ALLOTTED", "ALL_OFFICE_FUNCTIONS"]
    is_demo: bool
    basis: str | None


class FunctionCatalogueResponse(BaseModel):
    office_types: list[OfficeTypeFunctions]
    post_rules: list[PostFunctionRule]


class Event(BaseModel):
    id: int
    ts: str
    type: str
    effective_at: str
    payload: dict[str, Any]
    delivered: bool


class EventsResponse(BaseModel):
    events: list[Event]
    next_after: int


# ---------------------------------------------------------------- writes

class OnboardingBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'source': 'MANUAL', 'name': 'Rupjyoti Bora', 'gender': 'MALE', 'cadre': 'ACS', 'year_of_joining': 2024, 'date_of_joining': '2024-07-01', 'mobile': '9435011223', 'email': 'rupjyoti.bora@example.in', 'pan': 'ABCPB1234K', 'submitted_by': 'ESTB@DC_NGN', 'is_demo': True}]})
    source: Literal["FINASSAM", "MANUAL"]
    name: str
    submitted_by: str
    finassam_code: str | None = None
    pan: str | None = None
    aadhaar_token: str | None = Field(None, description="Hashed with a salt on arrival; never stored (BR-09)")
    cadre: str | None = None
    year_of_joining: int | None = None
    date_of_birth: str | None = None
    date_of_retirement: str | None = None
    email: str | None = None
    mobile: str | None = Field(None, description="10 digits; MDM rejects a mobile already on record (DUPLICATE)")
    is_demo: bool = False
    gender: Literal["MALE", "FEMALE", "OTHER"] | None = None
    date_of_joining: str | None = Field(None, description="ISO date; sent to MDM")


class OnboardingResponse(BaseModel):
    request_id: int
    status: Literal["PENDING", "MINTED", "DUPLICATE", "REJECTED"]
    employee_id: str | None
    reason: str | None
    is_demo: bool


class PostingBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'employee_id': 'EMP-0062', 'sanctioned_post_id': 'DC_NGN-SETTLEMENT_OFFICER-01', 'charge_type': 'ADDITIONAL', 'effective_from': '2026-11-04T10:00:00+05:30', 'order_ref': 'PERS/E/2026/112', 'issuing_department': 'Personnel Department', 'entered_by': 'ESTB@DC_NGN'}]})
    employee_id: str
    sanctioned_post_id: str
    charge_type: ChargeType
    effective_from: str
    effective_to: str | None = None
    order_ref: str = Field(description="Transfer order reference")
    issuing_department: str = Field(description="Cadre-controlling department that issued the order")
    entered_by: str
    note: str | None = None


class PostingOut(BaseModel):
    id: int
    lineage_id: int
    employee_id: str
    is_demo: bool
    sanctioned_post_id: str
    charge_type: ChargeType
    effective_from: str
    effective_to: str | None
    order_ref: str
    issuing_department: str
    entered_by: str
    note: str | None


class SuccessorBody(BaseModel):
    employee_id: str
    charge_type: ChargeType
    order_ref: str
    issuing_department: str
    note: str | None = None


class RelieveBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'at': '2026-11-20T10:00:00+05:30', 'entered_by': 'ESTB@DC_NGN'}]})
    at: str
    entered_by: str
    successor: SuccessorBody | None = Field(None, description="Joins the same post at the same instant (BR-03)")


class RelieveOut(BaseModel):
    ended: PostingOut
    successor: PostingOut | None


class AllotBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'employee_id': 'EMP-0065', 'office_id': 'DC_NGN', 'function_code': 'CENSUS', 'effective_from': '2026-11-04T10:00:00+05:30', 'entered_by': 'ESTB@DC_NGN'}]})
    employee_id: str
    office_id: str
    function_code: str
    effective_from: str
    effective_to: str | None = None
    entered_by: str = Field(description="Must be the Establishment branch of office_id, e.g. ESTB@DCO-27NAL")


class AllotOut(BaseModel):
    id: int
    lineage_id: int
    employee_id: str
    is_demo: bool = Field(description="True for demo allotments or demo officers")
    office_id: str
    function_code: str
    effective_from: str
    effective_to: str | None
    entered_by: str


class AllotmentsResponse(BaseModel):
    office_id: str
    at: str
    allotments: list[AllotOut]


class WithdrawBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'at': '2026-11-10T00:00:00+05:30', 'entered_by': 'ESTB@DC_NGN'}]})
    at: str
    entered_by: str


class AvailabilityBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'employee_id': 'EMP-0065', 'kind': 'LEAVE', 'from_ts': '2026-11-10', 'to_ts': '2026-11-15', 'entered_by': 'ESTB@DC_NGN', 'note': 'earned leave'}]})
    employee_id: str
    kind: Literal["LEAVE", "TOUR", "TRAINING", "DEPUTATION"]
    from_ts: str
    to_ts: str | None = None
    entered_by: str
    note: str | None = None
    supersedes_id: int | None = Field(None, description="Correct an earlier window; both rows are kept (BR-10)")


class AvailabilityOut(BaseModel):
    id: int
    lineage_id: int
    employee_id: str
    is_demo: bool
    kind: str
    from_ts: str
    to_ts: str | None
    entered_by: str
    note: str | None


class VacantBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'at': '2026-11-04T10:00:00+05:30', 'reason': 'Officer retired; no posting order yet', 'entered_by': 'ESTB@DC_NGN'}]})
    at: str
    reason: str
    entered_by: str


class VacantOut(BaseModel):
    vacancy_id: int
    sanctioned_post_id: str
    since: str
    until: str | None
    reason: str
    entered_by: str
    ended: list[PostingOut]


# ---------------------------------------------------------------- records (list / view / correct)

class _Period(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str | None = Field(None, alias="from", description="Start, ISO-8601 IST")
    to: str | None = Field(None, description="End (exclusive), ISO-8601 IST; null = open")


class EmployeeSummary(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    email: str | None
    mobile: str | None
    posts: list[str] = Field(description="Chairs held at `at`")
    available: bool
    unavailable_reason: str | None


class EmployeeListResponse(BaseModel):
    at: str
    employees: list[EmployeeSummary] = Field(description="Seniority order")


class EmployeeRecord(BaseModel):
    employee_id: str
    name: str
    gender: str | None
    cadre: str | None
    date_of_joining: str | None
    year_of_joining: int | None = Field(description="Batch year; drives seniority (HR-held until MDM has it)")
    date_of_birth: str | None
    date_of_retirement: str | None
    email: str | None
    mobile: str | None
    finassam_code: str | None
    pan: str | None
    issuing_department: str | None = Field(description="Cadre-controlling department (MDM cadre)")
    has_aadhaar_hash: bool
    is_demo: bool
    source: str | None


class EmployeePosting(_Period):
    posting_id: int
    sanctioned_post_id: str
    office_id: str
    post_code: str
    charge_type: ChargeType
    order_ref: str
    issuing_department: str
    note: str | None
    state: Literal["CURRENT", "FUTURE", "ENDED"]


class EmployeeAllotment(_Period):
    allotment_id: int
    office_id: str
    function_code: str
    is_demo: bool
    current: bool


class EmployeeWindow(_Period):
    availability_id: int
    kind: str
    note: str | None
    entered_by: str
    cancelled: bool


class EmployeeOnboarding(BaseModel):
    request_id: int
    status: str
    source: str
    submitted_by: str
    created_at: str
    reason: str | None


class EmployeeDetailResponse(BaseModel):
    employee: EmployeeRecord
    at: str
    available: bool
    unavailable_reason: str | None
    postings: list[EmployeePosting]
    function_allotments: list[EmployeeAllotment]
    availability: list[EmployeeWindow]
    onboarding: list[EmployeeOnboarding]


class EmployeeCorrectBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"submitted_by": "ESTB@DC_NGN", "email": "kamal.sarma@assam.gov.in", "year_of_joining": 2019}]})
    submitted_by: str
    name: str | None = None
    gender: Literal["MALE", "FEMALE", "OTHER"] | None = None
    date_of_joining: str | None = None
    cadre: str | None = None
    year_of_joining: int | None = None
    date_of_birth: str | None = None
    date_of_retirement: str | None = None
    email: str | None = None
    mobile: str | None = None


class EmployeeCorrected(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    email: str | None
    mobile: str | None


class OnboardingRequestRow(BaseModel):
    request_id: int
    source: str
    name: str
    status: str
    employee_id: str | None
    submitted_by: str
    reason: str | None
    is_demo: bool
    created_at: str


class OnboardingListResponse(BaseModel):
    requests: list[OnboardingRequestRow]


class OfficeRow(BaseModel):
    office_id: str
    name: str
    office_type: str
    district_code: str
    district_name: str | None
    parent_office_id: str | None
    provisional: bool = Field(description="True = not in MDM (held locally)")
    is_active: bool
    establishment_actor: str


class OfficeListResponse(BaseModel):
    offices: list[OfficeRow]


class ChairHolderBrief(BaseModel):
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    is_demo: bool
    posting_id: int
    charge_type: ChargeType


class ChairOut(BaseModel):
    sanctioned_post_id: str
    office_id: str
    post_code: str
    seq: int
    derived: bool = Field(description="True = local demo chair (not MDM sanctioned strength)")
    is_demo: bool
    is_active: bool = Field(description="False = abolished (kept for history)")
    source: str | None


class ChairRow(ChairOut):
    holders: list[ChairHolderBrief]
    vacancy: bool = Field(description="A vacancy declaration is in force")


class ChairListResponse(BaseModel):
    office_id: str
    chairs: list[ChairRow]


class ChairCreateBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"post_code": "ADC", "entered_by": "ESTB@DC_NGN", "reason": "GAD sanction order 45/2026"}]})
    post_code: str = Field(description="MDM designation code or short name")
    entered_by: str = Field(description="Establishment branch of the office, e.g. ESTB@AS-D-298")
    reason: str = Field(description="Sanction order or other basis for the new chair")


class ReasonBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{'entered_by': 'ESTB@DC_NGN', 'reason': 'Leave withdrawn'}]})
    entered_by: str
    reason: str


class PostingRow(_Period):
    posting_id: int
    lineage_id: int
    employee_id: str
    name: str
    is_demo: bool
    sanctioned_post_id: str
    charge_type: ChargeType
    order_ref: str
    issuing_department: str
    entered_by: str
    note: str | None
    state: Literal["CURRENT", "FUTURE", "ENDED"]


class PostingListResponse(BaseModel):
    postings: list[PostingRow]


class PostingCorrectBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [
        {"entered_by": "ESTB@DC_NGN", "order_ref": "PERS/E/2026/112-A", "note": "order copy received"}]})
    entered_by: str
    order_ref: str | None = None
    issuing_department: str | None = None
    note: str | None = None


class WindowRow(_Period):
    availability_id: int
    employee_id: str
    name: str
    is_demo: bool
    kind: str
    note: str | None
    entered_by: str
    state: Literal["CURRENT", "FUTURE", "ENDED", "CANCELLED"]


class AvailabilityListResponse(BaseModel):
    windows: list[WindowRow]


class AuditEntry(BaseModel):
    id: int
    ts: str
    actor: str
    action: str
    entity: str
    entity_id: str
    before_json: str | None = Field(description="JSON of the row before the change")
    after_json: str | None = Field(description="JSON of the row after the change")


class AuditListResponse(BaseModel):
    entries: list[AuditEntry]


# ---------------------------------------------------------------- MDM integration

class UsageResponse(BaseModel):
    """Shape required by MDM integration.md ("Usage endpoint you must expose")."""

    inUse: bool
    details: dict[str, Any]


class MdmStatusResponse(BaseModel):
    mode: Literal["LIVE", "OFFLINE_SEED"]
    base_url: str | None
    source: str | None = Field(description="Where the copy came from: the MDM URL, or SNAPSHOT")
    applied_version: int | None
    entity_versions: dict[str, Any]
    last_checked_at: str | None
    last_synced_at: str | None
    last_error: str | None
    last_check: dict[str, Any]
    consumer_code: str
    copied_from_mdm: list[str]
    local_until_mdm_has_them: list[str]


# ---------------------------------------------------------------- IAM stub

class LoginBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"employee_id": "EMP-0065"}]})
    employee_id: str


class SwitchBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"sanctioned_post_id": "DC_NGN-ADC-05"}]})
    sanctioned_post_id: str
    session_id: str | None = Field(None, description="Or send the X-Stub-Session header returned by login")


class IamSessionOut(BaseModel):
    stub: bool = True
    notice: str
    session_id: str
    employee_id: str
    is_demo: bool
    at: str
    active_post_id: str | None
    revoked: bool
    revoked_at: str | None
    revoke_reason: str | None
    posts: list[EmployeePost]
