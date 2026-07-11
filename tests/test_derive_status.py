"""The anti-fabrication core: derive_status must never invent a Pass."""
from backend.app import wcag
from backend.app.models import Status


def test_auto_clean_no_violation_is_pass():
    st, conf = wcag.derive_status(wcag.criterion("1.4.3"), [], auto_clean=True)
    assert st == Status.pass_ and conf.value == "high"


def test_auto_with_engine_error_is_needs_review():
    st, _ = wcag.derive_status(wcag.criterion("1.4.3"), [], auto_clean=False)
    assert st == Status.needs_manual_review


def test_confirmed_fail_wins(finding_factory):
    st, _ = wcag.derive_status(wcag.criterion("1.4.3"),
                               [finding_factory("1.4.3", Status.fail)], auto_clean=True)
    assert st == Status.fail


def test_semi_without_violation_is_needs_review():
    st, _ = wcag.derive_status(wcag.criterion("1.1.1"), [])
    assert st == Status.needs_manual_review


def test_manual_is_needs_review():
    st, _ = wcag.derive_status(wcag.criterion("1.2.1"), [])
    assert st == Status.needs_manual_review


def test_reviewer_can_pass_a_semi_criterion():
    st, _ = wcag.derive_status(wcag.criterion("1.1.1"), [], reviewer_verdict=Status.pass_)
    assert st == Status.pass_


def test_fail_beats_reviewer_pass(finding_factory):
    # A confirmed machine fail cannot be overridden to Pass.
    st, _ = wcag.derive_status(wcag.criterion("1.4.3"),
                               [finding_factory("1.4.3", Status.fail)],
                               reviewer_verdict=Status.pass_)
    assert st == Status.fail
