"""End-to-end report generation: build_combo -> real .docx and .xlsx files."""
from backend.app.models import Status
from backend.app.reporting import common, docx_report, xlsx_report

META = {
    "target_ref": "https://ex.com", "target_type": "web",
    "scan_date": "2026-07-11T12:00:00+00:00", "auditor_org": "Test Auditor",
    "discovery": {"subfinder": 3, "crt.sh": 5}, "hosts_live": ["https://ex.com"],
    "hosts_out_of_scope": [], "pages_crawled": 12, "pages_scanned": 4,
    "templates": 3, "sampling": {}, "engines": {"axe-core": {"clean": 3, "violations": 1, "error": 0}},
    "auto_clean": True, "tool_versions": {"node": "installed"},
}


def test_build_combo_and_reports(finding_factory, tmp_path):
    findings = [finding_factory("1.4.3", Status.fail),
                finding_factory("1.1.1", Status.fail, selector="img#logo")]
    combo = common.build_combo("2.2", "AA", findings, auto_clean=True)

    # 1.4.3 (auto) is Fail; 1.4.6 (auto, no violation) should Pass in AAA only.
    row_143 = next(r for r in combo["rows"] if r["crit"]["num"] == "1.4.3")
    assert row_143["status"] == Status.fail
    assert combo["counts"]["Fail"] >= 1
    assert combo["counts"]["Needs Manual Review"] > 0   # honesty: many unproven

    docx_path = tmp_path / "r.docx"
    xlsx_path = tmp_path / "r.xlsx"
    docx_report.build_docx(combo, META, str(docx_path))
    xlsx_report.build_xlsx(combo, META, str(xlsx_path))

    assert docx_path.exists() and docx_path.stat().st_size > 5000
    assert xlsx_path.exists() and xlsx_path.stat().st_size > 3000


def test_auto_criterion_passes_only_in_scope(finding_factory):
    # 1.4.6 is AAA auto. In an AA report it's out of scope; in AAA + clean it Passes.
    aa = common.build_combo("2.2", "AA", [], auto_clean=True)
    assert not any(r["crit"]["num"] == "1.4.6" for r in aa["rows"])
    aaa = common.build_combo("2.2", "AAA", [], auto_clean=True)
    row = next(r for r in aaa["rows"] if r["crit"]["num"] == "1.4.6")
    assert row["status"] == Status.pass_


def test_engine_error_blocks_auto_pass():
    # With auto_clean=False, even a clean auto criterion is Needs Manual Review.
    combo = common.build_combo("2.2", "AAA", [], auto_clean=False)
    row = next(r for r in combo["rows"] if r["crit"]["num"] == "1.4.3")
    assert row["status"] == Status.needs_manual_review
