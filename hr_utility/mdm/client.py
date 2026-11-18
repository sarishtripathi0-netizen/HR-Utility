"""The MDM boundary. The HR Utility only ever talks to MDM through this interface.

HttpMdmClient reads the live MDM PoC; SeedMdmClient reads a saved MDM snapshot (data/mdm_snapshot) for offline
runs and tests. Both map MDM payloads through hr_utility.mdm.workforce, so they return identical records. Nothing
outside hr_utility/mdm knows which one is in use.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OfficeRec:
    office_id: str
    name: str
    office_type: str
    district_code: str
    district_name: str | None
    parent_office_id: str | None
    establishment_actor: str
    provisional: bool  # True = not in MDM (held locally until MDM adds it)
    source: str | None = None
    external_ref: str | None = None
    is_active: bool = True
    mdm_id: str | None = None  # MDM UUID when the office comes from MDM


@dataclass(frozen=True)
class PostRec:
    """A post = an MDM designation (e.g. ADC, CIRCLE_OFFICER). rank_order is display order only."""

    post_code: str
    name: str
    rank_order: int
    source: str | None = None
    mdm_designation_code: str | None = None
    short_name: str | None = None  # MDM shortName (DC, AC, CO, Co-DC ...), accepted as an alias in queries


@dataclass(frozen=True)
class MdmDesignationRec:
    code: str
    name: str
    level: str | None
    department_code: str | None
    is_active: bool = True
    mdm_id: str | None = None


@dataclass(frozen=True)
class SanctionedPostRec:
    """One chair. MDM holds strength as a count per office x designation; it is expanded to chairs -01..-NN."""

    sanctioned_post_id: str
    office_id: str
    post_code: str
    seq: int
    derived: bool
    is_demo: bool
    source: str | None = None
    is_active: bool = True  # False once the chair is abolished (kept for history)


@dataclass(frozen=True)
class FunctionCodeRec:
    code: str
    name: str
    category: str
    source: str | None = None


@dataclass(frozen=True)
class OfficeTypeFunctionRec:
    office_type: str
    function_code: str
    is_demo: bool
    source: str | None = None


@dataclass(frozen=True)
class PostFunctionRuleRec:
    post_code: str
    mode: str  # ALLOTTED | ALL_OFFICE_FUNCTIONS (from MDM designation.holdsAllFunctions)
    is_demo: bool
    source: str | None = None


@dataclass(frozen=True)
class DesignationFunctionRec:
    """For a post that does not hold all office functions: a function it may be allotted (MDM designation-function)."""

    post_code: str
    function_code: str
    source: str | None = None


@dataclass(frozen=True)
class CadreRec:
    code: str
    name: str
    department_code: str | None
    department_name: str | None
    source: str | None = None


@dataclass(frozen=True)
class LinkRuleRec:
    """Who covers a post when its holder is away (MDM link-officer-rule, plus local conditions MDM cannot express)."""

    code: str
    office_type: str
    post_code: str           # the absent designation, or "*" (local rules only)
    covering_post_code: str
    priority: int
    required_function: str | None = None  # local condition, e.g. ARTPS
    source: str | None = None


@dataclass(frozen=True)
class DesignationRec:
    """Post + function, no location (e.g. ADC – Social Welfare)."""

    post_code: str
    function_code: str
    name: str


@dataclass(frozen=True)
class EmployeeRec:
    employee_id: str
    name: str
    cadre: str | None
    year_of_joining: int | None
    date_of_birth: str | None
    date_of_retirement: str | None
    email: str | None
    mobile: str | None
    finassam_code: str | None
    pan: str | None
    aadhaar_token_hash: str | None
    is_demo: bool
    source: str | None = None
    gender: str | None = None
    date_of_joining: str | None = None


@dataclass(frozen=True)
class HolidayRec:
    holiday_date: str  # ISO date
    name: str
    source: str | None = None
    code: str | None = None           # MDM code; defaults to the date
    holiday_type: str | None = None   # GAZETTED | RESTRICTED | LOCAL
    district_code: str | None = None  # set for district-only (LOCAL) holidays
    is_active: bool = True


@dataclass(frozen=True)
class MintPayload:
    """What the HR Utility submits to MDM. Identifiers (FinAssam code, PAN, Aadhaar hash) are checked by HR first
    and kept with the onboarding request; MDM's mint takes name, gender, mobile, email, cadre and date of joining."""

    name: str
    cadre: str | None = None
    year_of_joining: int | None = None
    date_of_birth: str | None = None
    date_of_retirement: str | None = None
    email: str | None = None
    mobile: str | None = None
    finassam_code: str | None = None
    pan: str | None = None
    aadhaar_token_hash: str | None = None
    is_demo: bool = False
    source: str | None = None
    gender: str | None = None
    date_of_joining: str | None = None


@dataclass(frozen=True)
class MintResult:
    employee_id: str | None
    duplicate: bool  # True when an existing person matched (their ID, if known, is returned)
    matched_on: str | None = None  # MOBILE | EMAIL | ... as reported by MDM
    message: str | None = None


class MdmClient(Protocol):
    def list_offices(self) -> list[OfficeRec]: ...
    def list_posts(self) -> list[PostRec]: ...
    def list_sanctioned_posts(self) -> list[SanctionedPostRec]: ...
    def list_function_codes(self) -> list[FunctionCodeRec]: ...
    def list_office_type_functions(self) -> list[OfficeTypeFunctionRec]: ...
    def list_post_function_rules(self) -> list[PostFunctionRuleRec]: ...
    def list_designation_functions(self) -> list[DesignationFunctionRec]: ...
    def list_cadres(self) -> list[CadreRec]: ...
    def list_link_rules(self) -> list[LinkRuleRec]: ...
    def list_designations(self) -> list[DesignationRec]: ...
    def list_mdm_designations(self) -> list[MdmDesignationRec]: ...
    def list_employees(self) -> list[EmployeeRec]: ...
    def get_employee(self, employee_id: str) -> EmployeeRec | None: ...
    def list_holidays(self) -> list[HolidayRec]: ...

    def mint_employee(self, payload: MintPayload) -> MintResult:
        """MDM allocates the Employee ID; a duplicate mobile or email is reported as a duplicate."""
        ...

    def mint_demo(self, payload: MintPayload) -> MintResult:
        """A synthetic officer: local DEMO-NNNN ID, never sent to MDM."""
        ...

    def update_employee(self, employee_id: str, changes: dict, actor: str) -> EmployeeRec:
        """Correct the golden record (MDM fields in MDM; HR-only fields such as year of joining locally)."""
        ...

    def add_sanctioned_post(self, office_id: str, post_code: str, source: str) -> SanctionedPostRec:
        """Raise the sanctioned strength of office x post by one; returns the new chair."""
        ...

    def abolish_sanctioned_post(self, sanctioned_post_id: str, reason: str) -> SanctionedPostRec:
        """Lower the strength by one; only the highest-numbered chair can go. It stays on record, inactive."""
        ...

    def validate(self, refs: dict[str, list[str]], as_on: str | None = None) -> dict | None:
        """MDM's live check (OK / NOT_FOUND / INACTIVE / NOT_EFFECTIVE per code); None when not available."""
        ...
