"""Engine normalizers, dedupe, and cross-engine reconciliation."""
from backend.app.models import Confidence, Status
from backend.app.scanners.web import normalize

AXE_RESULT = {
    "violations": [{
        "id": "color-contrast", "impact": "serious",
        "help": "Elements must have sufficient color contrast",
        "nodes": [{
            "target": ["main > a.link"], "html": "<a class='link'>x</a>",
            "any": [{"id": "color-contrast", "data": {"contrastRatio": 2.3,
                     "fgColor": "#aaaaaa", "bgColor": "#ffffff"}}],
            "all": [], "none": [],
        }],
    }]
}

PA11Y_RESULT = {
    "issues": [{
        "type": "error",
        "code": "WCAG2AAA.Principle1.Guideline1_4.1_4_6.G18.Fail",
        "selector": "main > a.link", "context": "<a class='link'>x</a>",
        "message": "This element has insufficient contrast.",
    }]
}


def test_axe_maps_contrast_to_143():
    findings = normalize.axe_to_findings("job", "https://ex.com", AXE_RESULT)
    assert len(findings) == 1
    f = findings[0]
    assert f.sc_num == "1.4.3" and f.status == Status.fail
    assert f.engine == "axe-core"
    assert f.computed["color-contrast"]["contrastRatio"] == 2.3


def test_pa11y_parses_sc_from_htmlcs_code():
    findings = normalize.pa11y_to_findings("job", "https://ex.com", PA11Y_RESULT)
    assert len(findings) == 1
    assert findings[0].sc_num == "1.4.6"   # AAA contrast, parsed from the code


def test_unmapped_rule_is_recorded_not_dropped():
    normalize.unmapped_rules.clear()
    weird = {"violations": [{"id": "totally-made-up-rule", "impact": "minor",
                             "help": "x", "nodes": [{"target": ["p"], "html": "<p>"}]}]}
    out = normalize.axe_to_findings("job", "https://ex.com", weird)
    assert out == []
    assert any("totally-made-up-rule" in k for k in normalize.unmapped_rules)


def test_dedupe_rolls_up_occurrences():
    f1 = normalize.axe_to_findings("job", "https://ex.com/a", AXE_RESULT)[0]
    f2 = normalize.axe_to_findings("job", "https://ex.com/b", AXE_RESULT)[0]
    merged = normalize.dedupe([f1, f2])
    assert len(merged) == 1
    assert merged[0].occurrences == 2
    assert sum(loc.count for loc in merged[0].locations) == 2


def test_reconcile_marks_agreement_high_confidence():
    axe_f = normalize.axe_to_findings("job", "https://ex.com", AXE_RESULT)[0]
    # Simulate IBM reporting the same SC + selector.
    ibm_f = axe_f.model_copy(update={"engine": "ibm-equal-access",
                                     "engines_agreeing": ["ibm-equal-access"],
                                     "confidence": Confidence.medium})
    out = normalize.reconcile([axe_f, ibm_f])
    assert len(out) == 1
    assert set(out[0].engines_agreeing) == {"axe-core", "ibm-equal-access"}
    assert out[0].confidence == Confidence.high
