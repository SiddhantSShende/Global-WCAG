"""Test config: force local artifact storage (no S3/boto3 needed) and provide
a small factory for synthetic findings."""
import os
import sys
from pathlib import Path

os.environ.setdefault("A11Y_STORAGE", "local")

# Ensure repo root is importable when pytest is invoked from elsewhere.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Standalone SQLite DB so db-touching tests (RBAC/audit) run without Postgres.
(ROOT / "artifacts").mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL",
                      f"sqlite:///{(ROOT / 'artifacts' / 'test.db').as_posix()}")

import pytest  # noqa: E402

from backend.app import wcag  # noqa: E402
from backend.app.models import (  # noqa: E402
    Confidence, Finding, Impact, Location, Status, TargetType,
)


def make_finding(sc_num: str, status: Status = Status.fail,
                 occurrences: int = 1, engine: str = "axe-core",
                 selector: str = "main > a.link", screenshot_key=None) -> Finding:
    c = wcag.criterion(sc_num)
    return Finding(
        job_id="job-test", target_type=TargetType.web, target_ref="https://ex.com",
        sc_num=sc_num, sc_name=c["name"], level=c["level"], principle=c["principle"],
        wcag_versions=c["versions"], status=status,
        confidence=Confidence.high, auto_decidable=(c["testability"] == "auto"),
        engine=engine, engine_rule_id="color-contrast", engines_agreeing=[engine],
        impact=Impact.serious, selector=selector, html_snippet="<a>x</a>",
        computed={"contrast_ratio": 2.3}, screenshot_key=screenshot_key,
        occurrences=occurrences,
        locations=[Location(ref="https://ex.com", count=occurrences)],
        description="Insufficient contrast", remediation="Increase contrast.",
    )


@pytest.fixture
def finding_factory():
    return make_finding
