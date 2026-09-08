"""API models for the stateless degree-audit analyzer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RequirementStatus = Literal["complete", "in_progress", "remaining"]
RequirementKind = Literal["course", "elective", "milestone", "gpa", "project"]
CourseStatus = Literal["complete", "in_progress", "not_completed"]
PlannedCourseStatus = Literal["planned", "in_progress", "personal", "premed", "milestone"]


class CourseRecord(BaseModel):
    code: str
    term: str
    campus: str = ""
    subject: str
    number: str
    credits: float
    grade: str
    title: str = ""
    status: CourseStatus


class Requirement(BaseModel):
    id: str
    major: str
    section: str
    name: str
    kind: RequirementKind = "course"
    status: RequirementStatus
    credits_required: float = 0.0
    credits_earned: float = 0.0
    credits_in_progress: float = 0.0
    credits_remaining: float = 0.0
    course_options: list[str] = Field(default_factory=list)
    courses_completed: list[str] = Field(default_factory=list)
    courses_in_progress: list[str] = Field(default_factory=list)
    criteria: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)
    source_text: str = ""
    confidence: float = 1.0
    # Set when a documented course equivalence clears this requirement even
    # though DARS still lists it. Holds the attribution, never a bare flag.
    satisfied_by: str = ""
    source_label: str = ""
    source_pages: list[int] = Field(default_factory=list)
    parent_id: str | None = None
    logic: Literal["all", "any", "unknown"] = "unknown"
    minimum_grade: str = ""
    needs_review: bool = False


class AuditSummary(BaseModel):
    earned_hours: float | None = None
    in_progress_hours: float = 0.0
    gpa: float | None = None
    catalog_year: str | None = None
    complete_requirements: int = 0
    in_progress_requirements: int = 0
    remaining_requirements: int = 0
    remaining_specific_credits: float = 0.0


class MajorAudit(BaseModel):
    program_code: str = ""
    prepared_on: str = ""
    campus: str = ""
    name: str
    source_file: str
    official_majors: list[str] = Field(default_factory=list)
    summary: AuditSummary
    requirements: list[Requirement]
    warnings: list[str] = Field(default_factory=list)


class OverlapOpportunity(BaseModel):
    course_code: str
    majors: list[str]
    requirement_ids: list[str]
    requirement_names: list[str]
    potential_credits: float
    reason: str


class Recommendation(BaseModel):
    course_code: str
    subject: str = ""
    catalog_number: str = ""
    majors: list[str]
    requirement_ids: list[str]
    requirement_names: list[str]
    credits: float
    priority: int
    reason: str
    alternatives: list[str] = Field(default_factory=list)
    class_search_url: str


class PlannedCourse(BaseModel):
    id: str
    code: str
    subject: str = ""
    catalog_number: str = ""
    label: str
    credits: float
    majors: list[str]
    requirement_ids: list[str]
    is_placeholder: bool = False
    status: PlannedCourseStatus = "planned"
    movable: bool = True
    prerequisites: list[str] = Field(default_factory=list)
    corequisites: list[str] = Field(default_factory=list)
    # Approved courses this slot can be filled with, when it is a placeholder.
    # Carried on the course itself so the picker in the map has them without
    # having to rejoin against the requirement list.
    alternatives: list[str] = Field(default_factory=list)
    # General Studies codes this course also carries, per the major map.
    attributes: list[str] = Field(default_factory=list)
    # Ids of advisory notes that argue with, or qualify, this course.
    advisories: list[str] = Field(default_factory=list)
    # Plain-language reason this class is in the plan, used by the printed PDF.
    justification: str = ""
    # Named source that fixed this course to its term, when one did.
    sequenced_by: str = ""
    class_search_url: str = ""
    # Set when a saved placeholder choice named this course by hand.
    resolved_from_placeholder: bool = False
    note: str = ""


class SemesterPlan(BaseModel):
    term: str
    term_code: str = ""
    courses: list[PlannedCourse] = Field(default_factory=list)
    total_credits: float = 0.0
    credit_limit: int = 30
    #: Load-bearing classes this term may hold, counted separately from credits.
    #: A term can sit under its credit ceiling and still be too many separate
    #: courses to carry, and quarter-credit modules must not crowd out real ones.
    course_limit: int = 6
    min_credits: int = 13
    is_mcat_term: bool = False
    is_in_progress: bool = False
    # The holding area at the end of the map for work that did not fit any term.
    # Not a real term: it has no ceiling, no floor, and counts toward nothing.
    is_unplaced: bool = False
    note: str = ""


class PlanPace(BaseModel):
    """What the student's stated graduation target demands of each term.

    The graduation term is chosen, not predicted, so the question worth
    answering is whether the ceiling they picked actually gets them there.
    """

    outstanding_credits: float = 0.0
    open_terms: int = 0
    #: Credits per term needed to finish everything by the stated target.
    required_per_term: float = 0.0
    credit_ceiling: int = 0
    unplaced_credits: float = 0.0
    feasible: bool = True


class PlanResult(BaseModel):
    start_term: str
    graduation_term: str
    semesters: list[SemesterPlan]
    planned_credits: float
    min_credits: int = 13
    applied_decisions: int = 0
    unplanned_requirements: list[str] = Field(default_factory=list)
    pace: PlanPace = Field(default_factory=PlanPace)
    warnings: list[str] = Field(default_factory=list)


class AdvisoryNote(BaseModel):
    """A major-map rule DARS cannot express, or expresses differently."""

    id: str
    program: str
    severity: Literal["applied", "confirm", "sequencing", "cap"]
    courses: list[str] = Field(default_factory=list)
    source: str
    title: str
    detail: str


class PremedRequirement(BaseModel):
    id: str
    name: str
    detail: str
    status: RequirementStatus
    required: bool = True
    completed_courses: list[str] = Field(default_factory=list)
    in_progress_courses: list[str] = Field(default_factory=list)
    remaining_courses: list[str] = Field(default_factory=list)
    note: str = ""


class PremedSummary(BaseModel):
    framework: str
    complete_count: int = 0
    in_progress_count: int = 0
    remaining_count: int = 0
    requirements: list[PremedRequirement]
    sources: list[dict[str, str]] = Field(default_factory=list)


class GraduationCheck(BaseModel):
    id: str
    label: str
    status: Literal["pass", "note", "gap"]
    detail: str
    evidence: list[str] = Field(default_factory=list)


class GraduationReadiness(BaseModel):
    status: Literal["on_track", "on_track_with_notes", "blocked"]
    graduation_term: str = ""
    pass_count: int = 0
    note_count: int = 0
    gap_count: int = 0
    checks: list[GraduationCheck] = Field(default_factory=list)


class AnalysisResponse(BaseModel):
    audits: list[MajorAudit]
    readiness: GraduationReadiness
    completed_courses: list[CourseRecord]
    in_progress_courses: list[CourseRecord]
    overlaps: list[OverlapOpportunity]
    recommendations: list[Recommendation]
    premed: PremedSummary
    plan: PlanResult
    advisories: list[AdvisoryNote] = Field(default_factory=list)
    scenario_id: int | None = None
    warnings: list[str] = Field(default_factory=list)
    processing_ms: int


class DemoResponse(BaseModel):
    available: bool
    files: list[str] = Field(default_factory=list)


class AuditRecord(BaseModel):
    """One DARS export discovered in the local audit folder."""

    filename: str
    program_code: str
    program_name: str
    prepared_on: str | None = None
    prepared_on_label: str = ""
    catalog_year: str = ""
    dated_from: str = ""
    is_latest: bool = False


class Placement(BaseModel):
    """A course moved to a specific term by hand."""

    course_id: str
    course_code: str = ""
    term: str
    credits: float = 0.0
    locked: bool = False


class PlaceholderChoice(BaseModel):
    """A real course chosen to fill a planning placeholder slot."""

    slot_id: str
    course_code: str
    requirement_id: str = ""
    note: str = ""


class TermSetting(BaseModel):
    """Per-term planning choices the student made by hand."""

    term: str
    credit_limit: int = Field(ge=1, le=40)
    is_mcat_term: bool = False
    note: str = ""


class CustomCourse(BaseModel):
    """A class the student added to the map that no audit asked for."""

    course_id: str
    code: str = ""
    label: str
    credits: float = Field(default=3.0, ge=0, le=12)
    term: str
    majors: list[str] = Field(default_factory=list)
    note: str = ""


class PlanState(BaseModel):
    """The whole editable state of a semester map, saved in one request."""

    placements: list[Placement] = Field(default_factory=list)
    placeholders: list[PlaceholderChoice] = Field(default_factory=list)
    term_settings: list[TermSetting] = Field(default_factory=list)
    custom_courses: list[CustomCourse] = Field(default_factory=list)
    removed_course_ids: list[str] = Field(default_factory=list)


class PlanSummary(BaseModel):
    """At-a-glance metadata for one saved permutation.

    Derived from a result by ``backend.plan_summary.summarize`` and stored beside
    it, so the permutations dashboard can compare plans without loading any of
    their results — a saved result runs to megabytes.
    """

    schema_version: int = 1
    graduation_term: str = ""
    start_term: str = ""
    term_count: int = 0
    planned_credits: float = 0.0
    course_count: int = 0
    placeholder_count: int = 0
    unplaced_count: int = 0
    heaviest_term_credits: float = 0.0
    lightest_term_credits: float = 0.0
    programs: list[str] = Field(default_factory=list)
    readiness_status: str = ""
    gap_count: int = 0
    warning_count: int = 0
    premed: bool = False
    mcat_terms: list[str] = Field(default_factory=list)
    mcat_credit_ceiling: int = 0
    mcat_course_ceiling: int = 0
    credits_per_term: int = 0
    min_credits: int = 0
    include_summer: bool = False
    personal_rules: dict[str, bool] = Field(default_factory=dict)


class AuditSnapshot(BaseModel):
    program_code: str
    program_name: str = ""
    prepared_on: str | None = None
    source_filename: str


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    passphrase: str = Field(min_length=1, max_length=1024)


class VerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    passphrase: str = Field(min_length=1, max_length=1024)


class AccountSummary(BaseModel):
    """What the browser is told about the signed-in account. Never the hash."""

    id: int
    email: str
    created_at: str
    verified: bool


class AuthSession(BaseModel):
    account: AccountSummary
    token: str
    expires_at: str
    # Set when a pre-account saved plan was handed to this new account.
    adopted_scenarios: int = 0
    message: str = ""


class RegisterResult(BaseModel):
    """Registration either finishes or waits on an emailed code."""

    status: Literal["registered", "verification_sent"]
    email: str
    message: str
    # Present only when no verification was required.
    session: AuthSession | None = None


class AuthStatus(BaseModel):
    """What the sign-in screen needs before anything is typed."""

    signed_in: bool
    account: AccountSummary | None = None
    accounts_exist: bool = False
    email_verification: bool = False
    min_passphrase_length: int = 12


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    start_term: str = "Fall 2026"
    graduation_term: str = "Spring 2029"
    options: dict[str, Any] = Field(default_factory=dict)


class ScenarioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_term: str | None = None
    graduation_term: str | None = None
    options: dict[str, Any] | None = None


class ScenarioSummary(BaseModel):
    id: int
    name: str
    created_at: str
    updated_at: str
    start_term: str
    graduation_term: str
    options: dict[str, Any] = Field(default_factory=dict)


class Scenario(ScenarioSummary):
    placements: list[Placement] = Field(default_factory=list)
    placeholders: list[PlaceholderChoice] = Field(default_factory=list)
    term_settings: list[TermSetting] = Field(default_factory=list)
    custom_courses: list[CustomCourse] = Field(default_factory=list)
    removed_course_ids: list[str] = Field(default_factory=list)
    audits: list[AuditSnapshot] = Field(default_factory=list)
    stale_audit_warnings: list[str] = Field(default_factory=list)


class AuditInventoryResponse(BaseModel):
    folder: str
    audits: list[AuditRecord] = Field(default_factory=list)
    latest: list[AuditRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
