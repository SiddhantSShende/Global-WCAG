"""Canonical Pydantic schema — the contract every engine maps onto.

The report builder only ever sees `Finding` objects; it never knows or cares
whether they came from axe, Pa11y, Lighthouse, IBM, Android ATF, or iOS XCUITest.
(SQLAlchemy persistence mirrors these in `db.py`.)
"""
from __future__ import annotations

import uuid
from enum import Enum

from pydantic import BaseModel, Field


class TargetType(str, Enum):
    web = "web"
    android = "android"
    ios = "ios"


class Status(str, Enum):
    fail = "fail"
    partial = "partial"
    needs_manual_review = "needs_manual_review"
    pass_ = "pass"
    not_applicable = "not_applicable"


class Impact(str, Enum):
    blocker = "blocker"
    serious = "serious"
    moderate = "moderate"
    minor = "minor"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class EngineStatus(str, Enum):
    """Per the fail-closed rule: a missing/errored engine can never yield a Pass."""
    clean = "clean"          # ran, found no violation for its rules
    violations = "violations"  # ran, found violations
    error = "error"          # crashed / timed out / tool missing


class Location(BaseModel):
    ref: str                 # url or screen id
    count: int = 1


class Finding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    target_type: TargetType
    target_ref: str = ""

    # ── WCAG mapping (from the registry) ──
    sc_num: str
    sc_name: str
    level: str
    principle: str
    wcag_versions: list[str]

    # ── Verdict — the anti-fabrication core ──
    status: Status
    confidence: Confidence
    auto_decidable: bool

    # ── Provenance ──
    engine: str
    engine_rule_id: str
    engines_agreeing: list[str] = []     # populated during reconciliation
    impact: Impact

    # ── Evidence ──
    selector: str | None = None
    html_snippet: str | None = None
    computed: dict = {}                  # real measured values (contrast, sizes…)
    screenshot_key: str | None = None    # cropped + highlighted
    page_screenshot_key: str | None = None
    occurrences: int = 1
    locations: list[Location] = []

    description: str = ""                 # from engine rule metadata (not invented)
    remediation: str = ""                 # from the fixed remediation KB
    raw_engine_payload_key: str | None = None


class EngineRun(BaseModel):
    """Records that an engine actually ran on a page, and how it went.
    Drives fail-closed auto-Pass logic (no clean run -> no Pass)."""
    engine: str
    ref: str                             # page url / screen id
    status: EngineStatus
    version: str = ""
    error: str | None = None


class Review(BaseModel):
    review_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_id: str
    sc_num: str
    reviewer: str
    verdict: Status                      # pass | fail | partial | not_applicable
    rationale: str                       # required — why
    evidence_keys: list[str] = []
    at_technique: str | None = None      # e.g. "NVDA 2024.x", "VoiceOver iOS 17"
    created_at: str = ""


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    target_type: TargetType
    target_ref: str
    status: str = "queued"               # queued|running|review|building|done|error
    step: str = ""                       # human-readable current step
    created_by: str = "system"
    created_at: str = ""

    # ── Web scope / authorization ──
    authorized: bool = False             # legal attestation (required for web)
    scope_allowlist: list[str] = []      # hosts we're allowed to touch
    allow_active: bool = False           # active DNS brute-force opt-in

    # ── Target-specific inputs (mobile: app path/ref, credentials, login steps,
    #    device profile). Credentials should come from the vault in production;
    #    kept here transiently for MVP and purged after the job. ──
    inputs: dict = {}

    # ── Reproducibility ──
    engine_versions: dict = {}

    # ── Results ──
    report_keys: list[str] = []          # object-store keys of generated reports
    report_meta: dict = {}               # scan meta, persisted so reports can rebuild
    error_detail: str | None = None
