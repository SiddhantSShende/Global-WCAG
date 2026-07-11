"""The contradiction validator must ABORT (raise) on any fabrication."""
import pytest

from backend.app import wcag
from backend.app.models import Status
from backend.app.reporting import common


def test_build_combo_passes_clean(finding_factory):
    findings = [finding_factory("1.4.3", Status.fail)]
    combo = common.build_combo("2.2", "AA", findings, auto_clean=True)
    # 1.4.3 must be Fail, and no exception was raised (validator passed).
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.4.3")
    assert row["status"] == Status.fail
    assert combo["issues"], "the fail finding should surface as an issue"


def test_validate_raises_on_pass_with_fail(finding_factory):
    findings = [finding_factory("1.4.3", Status.fail)]
    combo = {
        "version": "2.2", "level": "AA",
        "rows": [{"crit": wcag.criterion("1.4.3"), "status": Status.pass_,
                  "via_review": False, "note": "", "issue_refs": []}],
        "issues": [],
    }
    with pytest.raises(AssertionError):
        common.validate(combo, findings)


def test_validate_raises_on_nonauto_pass_without_review():
    combo = {
        "version": "2.2", "level": "AA",
        "rows": [{"crit": wcag.criterion("1.1.1"), "status": Status.pass_,
                  "via_review": False, "note": "", "issue_refs": []}],
        "issues": [],
    }
    with pytest.raises(AssertionError):
        common.validate(combo, [])


def test_validate_raises_on_occurrence_mismatch(finding_factory):
    f = finding_factory("1.4.3", Status.fail, occurrences=5)
    f.locations[0].count = 2   # 5 != 2 -> contradiction
    combo = {"version": "2.2", "level": "AA", "rows": [], "issues": [f]}
    with pytest.raises(AssertionError):
        common.validate(combo, [f])


def test_obsolete_411_never_pass_in_22():
    combo = {
        "version": "2.2", "level": "A",
        "rows": [{"crit": wcag.criterion("4.1.1"), "status": Status.pass_,
                  "via_review": False, "note": "", "issue_refs": []}],
        "issues": [],
    }
    with pytest.raises(AssertionError):
        common.validate(combo, [])
