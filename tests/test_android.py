"""Android ATF normalization + mapping integrity."""
import io
import json

from backend.app import wcag
from backend.app.models import Status, TargetType
from backend.app.scanners.android import normalize as anorm


def _png(tmp_path):
    from PIL import Image
    p = tmp_path / "screen_0.png"
    Image.new("RGB", (400, 600), "#ffffff").save(p)
    return str(p)


def test_error_result_becomes_fail_finding(tmp_path):
    screens = [{
        "index": 0, "package": "com.example.app",
        "screenshot_local": _png(tmp_path),
        "results": [
            {"checkClass": "TextContrastCheck", "type": "ERROR",
             "message": "Text contrast 2.1:1 is insufficient",
             "viewId": "com.example:id/label",
             "bounds": {"left": 20, "top": 30, "right": 200, "bottom": 80}},
            {"checkClass": "TouchTargetSizeCheck", "type": "WARNING",
             "message": "Target may be small", "viewId": "", "bounds": None},
            {"checkClass": "TotallyMadeUpCheck", "type": "ERROR",
             "message": "x", "viewId": "", "bounds": None},
        ],
    }]
    anorm.webnorm.unmapped_rules.clear()
    findings = anorm.screens_to_findings("job-a", screens)

    # Only the mapped ERROR becomes a finding; WARNING skipped; unmapped recorded.
    assert len(findings) == 1
    f = findings[0]
    assert f.sc_num == "1.4.3" and f.status == Status.fail
    assert f.engine == "android-atf" and f.target_type == TargetType.android
    assert f.screenshot_key and f.page_screenshot_key   # evidence cropped + stored
    assert any("TotallyMadeUpCheck" in k for k in anorm.webnorm.unmapped_rules)


def test_no_screenshot_still_produces_finding_without_evidence():
    screens = [{"index": 0, "package": "com.x", "screenshot_local": None,
                "results": [{"checkClass": "SpeakableTextPresentCheck", "type": "ERROR",
                             "message": "Missing content description", "viewId": "id/img",
                             "bounds": None}]}]
    findings = anorm.screens_to_findings("job-b", screens)
    assert len(findings) == 1
    assert findings[0].sc_num == "1.1.1"
    assert findings[0].screenshot_key is None   # honest: no fabricated image


def test_all_atf_checks_map_to_real_criteria():
    m = json.load(open("wcag_data/rule_maps/android_atf.json", encoding="utf-8"))
    checks = [k for k in m if not k.startswith("_")]
    assert len(checks) == 14
    for check in checks:
        wcag.criterion(m[check])   # raises if not a real criterion
