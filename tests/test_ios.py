"""iOS XCUITest audit normalization + mapping integrity."""
import json

from backend.app import wcag
from backend.app.models import Status, TargetType
from backend.app.scanners.ios import normalize as inorm
from backend.app.scanners.ios import audit as iaudit


def test_audit_issue_becomes_fail_finding():
    screens = [{
        "index": 0, "package": "com.example.app", "screenshot": None,
        "audit": {"status": "violations", "issues": [
            {"type": "XCUIAccessibilityAuditTypeContrast",
             "detailedDescription": "Contrast 2.4:1 is below the recommended ratio",
             "compactDescription": "Low contrast"},
            {"type": "XCUIAccessibilityAuditTypeTrait",
             "detailedDescription": "Element has an incorrect trait",
             "compactDescription": "Trait"},
            {"type": "XCUIAccessibilityAuditTypeSomethingUnknown",
             "detailedDescription": "x", "compactDescription": "x"},
        ]},
    }]
    inorm.webnorm.unmapped_rules.clear()
    findings = inorm.screens_to_findings("job-i", screens)

    scs = sorted(f.sc_num for f in findings)
    assert scs == ["1.4.3", "4.1.2"]              # contrast + trait mapped
    assert all(f.status == Status.fail for f in findings)
    assert all(f.target_type == TargetType.ios for f in findings)
    assert any("SomethingUnknown" in k for k in inorm.webnorm.unmapped_rules)


def test_short_and_full_type_names_both_map():
    assert inorm._sc_for("contrast") == "1.4.3"
    assert inorm._sc_for("XCUIAccessibilityAuditTypeContrast") == "1.4.3"
    assert inorm._sc_for("XCUIAccessibilityAuditTypeHitRegion") == "2.5.8"


def test_all_audit_types_map_to_real_criteria():
    m = json.load(open("wcag_data/rule_maps/ios_xcuitest.json", encoding="utf-8"))
    keys = [k for k in m if not k.startswith("_")]
    assert len(keys) == 7
    for k in keys:
        wcag.criterion(m[k])


def test_audit_module_requests_seven_types():
    assert len(iaudit.AUDIT_TYPES) == 7
    assert all(t.startswith("XCUIAccessibilityAuditType") for t in iaudit.AUDIT_TYPES)
