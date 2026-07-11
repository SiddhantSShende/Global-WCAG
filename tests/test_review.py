"""Human-review workbench: reviewer verdicts flip rows and stay defensible."""
from backend.app.models import Status
from backend.app.reporting import common


def test_reviewer_pass_flips_semi_criterion_and_attributes():
    reviews = {"1.1.1": {"verdict": "pass", "reviewer": "Jane",
                         "at_technique": "NVDA 2024"}}
    combo = common.build_combo("2.2", "A", [], reviews=reviews, auto_clean=True)
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.1.1")
    assert row["status"] == Status.pass_
    assert row["via_review"] is True
    assert "Jane" in row["note"] and "NVDA 2024" in row["note"]
    # validator must accept a non-auto Pass that came via review
    assert combo["review_stats"]["manually_verified"] >= 1


def test_reviewer_cannot_override_machine_fail(finding_factory):
    findings = [finding_factory("1.4.3", Status.fail)]
    reviews = {"1.4.3": {"verdict": "pass", "reviewer": "Jane"}}
    combo = common.build_combo("2.2", "AA", findings, reviews=reviews, auto_clean=True)
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.4.3")
    assert row["status"] == Status.fail        # a confirmed fail always wins
    assert row["via_review"] is False


def test_reviewer_fail_verdict_records_but_not_via_review():
    reviews = {"1.2.1": {"verdict": "fail", "reviewer": "Jane",
                         "at_technique": "manual"}}
    combo = common.build_combo("2.0", "A", [], reviews=reviews, auto_clean=True)
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.2.1")
    assert row["status"] == Status.fail
    assert row["via_review"] is False          # a fail isn't a "verified pass"


def test_build_combo_accepts_plain_status_reviews():
    combo = common.build_combo("2.2", "A", [], reviews={"1.1.1": Status.pass_},
                               auto_clean=True)
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.1.1")
    assert row["status"] == Status.pass_ and row["via_review"] is True


def test_review_stats_counts_open_and_verified():
    reviews = {"1.1.1": {"verdict": "pass", "reviewer": "r"}}
    combo = common.build_combo("2.2", "AA", [], reviews=reviews, auto_clean=True)
    rs = combo["review_stats"]
    assert rs["manually_verified"] == 1
    assert rs["open_review"] > 0                # most criteria still need review
