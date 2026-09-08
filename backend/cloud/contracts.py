from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator
from backend.models import PlanState

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_max_length=500)

class PersonalRules(StrictModel):
    finance_sequence: bool = False
    finance_equivalence: bool = False
    # Legacy alias for a dance commitment, kept so saved preferences still load.
    # New plans use `recurring_commitment`; this maps onto it in the engine.
    dance: bool = False

class RecurringCommitment(StrictModel):
    """A standing class taken every term until the degree is finished.

    A weekly dance class, a language conversation section, a studio, an ensemble
    — coursework that is not a graduation requirement but that the student
    intends to keep taking. It is not tied to any programme, which is the point:
    a STEM student protecting one non-technical class a term needs the same
    thing a dance minor does.

    It runs *until graduation*, never past it. Modelling it as an ordinary unit
    made it occupy every term in the planning window, and because the window
    defaults to twenty-four terms the plan then claimed a 2038 graduation for a
    student finishing in 2029.
    """
    enabled: bool = False
    label: str = Field(default='Dance class', min_length=1, max_length=60)
    code: str = Field(default='DCE', min_length=1, max_length=12)
    credits: float = Field(default=2.0, ge=0, le=6)
    include_summer: bool = False

class Preferences(StrictModel):
    premed: bool = False
    start_term: str = ''
    graduation_term: str = ''
    credits_per_term: int = Field(default=15, ge=1, le=30)
    min_credits: int = Field(default=0, ge=0, le=30)
    include_summer: bool = False
    term_credit_limits: dict[str, int] = Field(default_factory=dict, max_length=36)
    term_course_limits: dict[str, int] = Field(default_factory=dict, max_length=36)
    mcat_terms: list[str] = Field(default_factory=list, max_length=6)
    # How heavy the exam term should be. Asked for when pre-med is ticked, and
    # used exactly as given: how much study one person needs alongside coursework
    # is not something this planner can decide for them.
    mcat_credit_ceiling: int = Field(default=12, ge=1, le=30)
    mcat_course_ceiling: int = Field(default=4, ge=1, le=12)
    course_ceiling: int = Field(default=0, ge=0, le=12)
    personal_rules: PersonalRules = Field(default_factory=PersonalRules)
    recurring_commitment: RecurringCommitment = Field(default_factory=RecurringCommitment)

    @model_validator(mode='after')
    def validate_terms(self):
        def term(value):
            if not re.fullmatch(r'(Spring|Summer|Fall) 20\d{2}', value):
                raise ValueError('Use a term such as Fall 2026.')
            season, year = value.split()
            return int(year)*3 + ['Spring','Summer','Fall'].index(season)
        if self.min_credits > self.credits_per_term:
            raise ValueError('The credit minimum exceeds the ceiling.')
        if self.start_term: term(self.start_term)
        if self.graduation_term:
            end = term(self.graduation_term)
            if self.start_term and not 0 <= end-term(self.start_term) <= 36:
                raise ValueError('Use a planning window of no more than twelve years.')
        for name, limit in self.term_credit_limits.items():
            term(name)
            if isinstance(limit, bool) or not self.min_credits <= limit <= 30 or limit < 1:
                raise ValueError('Invalid term credit limit.')
        for name, limit in self.term_course_limits.items():
            term(name)
            if isinstance(limit, bool) or not 1 <= limit <= 12:
                raise ValueError('Invalid term class limit.')
        for name in self.mcat_terms: term(name)
        if not self.premed and self.mcat_terms:
            raise ValueError('Select pre-med before specifying MCAT terms.')
        return self

class FileSpec(StrictModel):
    # Original filenames are deliberately not accepted or stored.
    size: int = Field(ge=5, le=25*1024*1024)

class UploadRequest(StrictModel):
    files: list[FileSpec] = Field(min_length=1, max_length=8)
    preferences: Preferences = Field(default_factory=Preferences)
    consent: Literal[True]
    @model_validator(mode='after')
    def total_size(self):
        if sum(f.size for f in self.files) > 100*1024*1024:
            raise ValueError('Upload no more than 100 MB in one batch.')
        return self

class StartAnalysis(StrictModel):
    job_id: UUID

class SavePlan(StrictModel):
    revision: int = Field(ge=1)
    state: PlanState
    name: str | None = Field(default=None, min_length=1, max_length=120)
    @model_validator(mode='after')
    def bound_state(self):
        import math
        s=self.state
        if max(len(s.placements),len(s.placeholders),len(s.custom_courses),len(s.removed_course_ids))>1500 or len(s.term_settings)>36:
            raise ValueError('Too many saved edits.')
        for placement in s.placements:
            if not math.isfinite(placement.credits) or not 0<=placement.credits<=12: raise ValueError('Invalid credits.')
        for setting in s.term_settings:
            if setting.credit_limit>30: raise ValueError('Maximum supported credit limit is 30.')
        if len(s.model_dump_json())>524288: raise ValueError('Too much saved state.')
        return self


class CreatePlan(StrictModel):
    audit_id: UUID
    name: str = Field(default='My semester map', min_length=1, max_length=120)
    preferences: Preferences

class ProfileUpdate(StrictModel):
    preferences: Preferences

class JobSummary(StrictModel):
    id: UUID
    status: Literal['awaiting_upload','queued','processing','completed','failed','cancelled']
    created_at: datetime
    error: str | None = None
    plan_id: UUID | None = None
    stage: str | None = None
    progress: int = 0

class UploadTicket(StrictModel):
    # Storage signs an upload by putting a JWT in the query string, which runs
    # these URLs to roughly 650 characters — past StrictModel's global 500-char
    # guard, so serialising the ticket raised ResponseValidationError and no
    # upload could ever start. The guard stays everywhere else; here the
    # destination is already constrained by the origin check that builds it.
    model_config = ConfigDict(extra='forbid', str_max_length=2000)
    job_id: UUID
    uploads: list[dict[str, str]]
