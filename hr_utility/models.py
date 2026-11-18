"""Tables. mdm_cache_* are read-only copies of MDM data; everything else is owned by the HR Utility.

All HR-owned rows are effective-dated and append-only: an end or a correction writes a new row
and sets superseded_by on the old one (BR-10). lineage_id ties the versions of one record together.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite, always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime reached the database; convert with timeutil.to_utc first")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- MDM cache (read-only copies)

class MdmOffice(Base):
    __tablename__ = "mdm_cache_office"
    office_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    office_type: Mapped[str] = mapped_column(String)
    district_code: Mapped[str] = mapped_column(String)
    district_name: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_office_id: Mapped[str | None] = mapped_column(String, nullable=True)
    establishment_actor: Mapped[str] = mapped_column(String)
    provisional: Mapped[bool] = mapped_column(Boolean, default=False)
    external_ref: Mapped[str | None] = mapped_column(String, nullable=True)  # cross-walk to other code lists
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mdm_id: Mapped[str | None] = mapped_column(String, nullable=True)  # MDM UUID (same id as MDM, per its guide)


class MdmPost(Base):
    __tablename__ = "mdm_cache_post"
    post_code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    rank_order: Mapped[int] = mapped_column(Integer)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    mdm_designation_code: Mapped[str | None] = mapped_column(String, nullable=True)
    short_name: Mapped[str | None] = mapped_column(String, nullable=True)  # MDM shortName, accepted as an alias


class MdmCadre(Base):
    __tablename__ = "mdm_cache_cadre"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    department_code: Mapped[str | None] = mapped_column(String, nullable=True)  # controlling department
    department_name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmDesignationFunction(Base):
    """For a post that does not hold all office functions: the functions it may be allotted."""

    __tablename__ = "mdm_cache_designation_function"
    post_code: Mapped[str] = mapped_column(String, primary_key=True)
    function_code: Mapped[str] = mapped_column(String, primary_key=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmLinkOfficerRule(Base):
    __tablename__ = "mdm_cache_link_officer_rule"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    office_type: Mapped[str] = mapped_column(String, index=True)
    post_code: Mapped[str] = mapped_column(String)  # absent designation, or "*"
    covering_post_code: Mapped[str] = mapped_column(String)
    priority: Mapped[int] = mapped_column(Integer, default=1)
    required_function: Mapped[str | None] = mapped_column(String, nullable=True)  # local condition (ARTPS)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmDesignation(Base):
    __tablename__ = "mdm_cache_designation"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    level: Mapped[str | None] = mapped_column(String, nullable=True)
    department_code: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    mdm_id: Mapped[str | None] = mapped_column(String, nullable=True)


class MdmSyncState(Base):
    """Freshness of the MDM copy (one row). versions_json holds MDM's per-entity versions last applied."""

    __tablename__ = "mdm_sync_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # SEED (offline snapshot) | the MDM base URL
    applied_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    versions_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmSanctionedPost(Base):
    __tablename__ = "mdm_cache_sanctioned_post"
    sanctioned_post_id: Mapped[str] = mapped_column(String, primary_key=True)
    office_id: Mapped[str] = mapped_column(ForeignKey("mdm_cache_office.office_id"), index=True)
    post_code: Mapped[str] = mapped_column(ForeignKey("mdm_cache_post.post_code"))
    seq: Mapped[int] = mapped_column(Integer)
    derived: Mapped[bool] = mapped_column(Boolean, default=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)  # False = abolished (kept for history)


class MdmFunctionCode(Base):
    __tablename__ = "mdm_cache_function_code"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    category: Mapped[str] = mapped_column(String)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmOfficeTypeFunction(Base):
    """Which functions exist in a type of office (the list an allotment must come from)."""

    __tablename__ = "mdm_cache_office_type_function"
    office_type: Mapped[str] = mapped_column(String, primary_key=True)
    function_code: Mapped[str] = mapped_column(String, primary_key=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmPostFunctionRule(Base):
    """How a post holds functions: ALLOTTED (by the Establishment branch) or ALL_OFFICE_FUNCTIONS (by being posted)."""

    __tablename__ = "mdm_cache_post_function_rule"
    post_code: Mapped[str] = mapped_column(String, primary_key=True)
    mode: Mapped[str] = mapped_column(String)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


class MdmEmployee(Base):
    __tablename__ = "mdm_cache_employee"
    employee_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    cadre: Mapped[str | None] = mapped_column(String, nullable=True)
    year_of_joining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_retirement: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    mobile: Mapped[str | None] = mapped_column(String, nullable=True)
    finassam_code: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    pan: Mapped[str | None] = mapped_column(String, nullable=True)
    aadhaar_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    gender: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_joining: Mapped[str | None] = mapped_column(String, nullable=True)


class MdmHoliday(Base):
    __tablename__ = "mdm_cache_holiday"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    holiday_date: Mapped[str] = mapped_column(String, index=True)  # ISO date, IST calendar
    name: Mapped[str] = mapped_column(String)
    holiday_type: Mapped[str | None] = mapped_column(String, nullable=True)   # GAZETTED | RESTRICTED | LOCAL
    district_code: Mapped[str | None] = mapped_column(String, nullable=True)  # LOCAL holidays only
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------- HR Utility (owned, append-only)

class OnboardingRequest(Base):
    __tablename__ = "onboarding_request"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String)  # FINASSAM | MANUAL
    finassam_code: Mapped[str | None] = mapped_column(String, nullable=True)
    pan: Mapped[str | None] = mapped_column(String, nullable=True)
    aadhaar_token_hash: Mapped[str | None] = mapped_column(String, nullable=True)  # BR-09: never the token
    name: Mapped[str] = mapped_column(String)
    cadre: Mapped[str | None] = mapped_column(String, nullable=True)
    year_of_joining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_of_birth: Mapped[str | None] = mapped_column(String, nullable=True)
    date_of_retirement: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    mobile: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_by: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)  # PENDING | MINTED | DUPLICATE | REJECTED
    employee_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Posting(Base):
    __tablename__ = "posting"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lineage_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    employee_id: Mapped[str] = mapped_column(String, index=True)
    sanctioned_post_id: Mapped[str] = mapped_column(String, index=True)
    charge_type: Mapped[str] = mapped_column(String)  # SUBSTANTIVE | ADDITIONAL
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    order_ref: Mapped[str] = mapped_column(String)
    issuing_department: Mapped[str] = mapped_column(String)
    entered_by: Mapped[str] = mapped_column(String)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class FunctionAllotment(Base):
    __tablename__ = "function_allotment"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lineage_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    employee_id: Mapped[str] = mapped_column(String, index=True)
    office_id: Mapped[str] = mapped_column(String, index=True)
    function_code: Mapped[str] = mapped_column(String)
    effective_from: Mapped[datetime] = mapped_column(UTCDateTime)
    effective_to: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    entered_by: Mapped[str] = mapped_column(String)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    source_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Availability(Base):
    """A window in which the employee is NOT available (leave, tour, training, deputation)."""

    __tablename__ = "availability"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lineage_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    employee_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)  # LEAVE | TOUR | TRAINING | DEPUTATION
    from_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    to_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    entered_by: Mapped[str] = mapped_column(String)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class VacancyDeclaration(Base):
    """BR-03 exception: an explicit, reasoned declaration that a chair is vacant."""

    __tablename__ = "vacancy_declaration"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lineage_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    sanctioned_post_id: Mapped[str] = mapped_column(String, index=True)
    from_ts: Mapped[datetime] = mapped_column(UTCDateTime)
    to_ts: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    reason: Mapped[str] = mapped_column(Text)
    entered_by: Mapped[str] = mapped_column(String)
    superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    entity: Mapped[str] = mapped_column(String)
    entity_id: Mapped[str] = mapped_column(String)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class EventOutbox(Base):
    __tablename__ = "event_outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    type: Mapped[str] = mapped_column(String)
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime)  # when subscribers should apply it
    payload_json: Mapped[str] = mapped_column(Text)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)


class IamSession(Base):
    """IAM STUB ONLY. No authentication; tracks the active post of a logged-in officer."""

    __tablename__ = "iam_session"
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    employee_id: Mapped[str] = mapped_column(String)
    active_post_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
