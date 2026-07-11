#!/usr/bin/env python3
"""Generate illustrative reports OFFLINE (no network, no engines).

Builds the full report matrix from a small set of realistic synthetic findings —
including a Pillow-rendered highlighted screenshot so the evidence-embedding path
is exercised — so you can open a populated .docx/.xlsx and see the exact format.

NOTE: this is a FORMAT DEMO. The findings are clearly synthetic; a real audit
comes from scripts/run_local_scan.py or the API. Nothing here is passed off as a
real scan.

Usage:  python scripts/demo_report.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("A11Y_STORAGE", "local")
os.environ.setdefault("PYTHONUTF8", "1")

from backend.app.config import settings  # noqa: E402
from backend.app.models import (  # noqa: E402
    Confidence, Finding, Impact, Location, Status, TargetType,
)
from backend.app.reporting import common, docx_report, xlsx_report  # noqa: E402
from backend.app.storage import storage  # noqa: E402
from backend.app import wcag  # noqa: E402

JOB = "demo"


def _fake_screenshot(text: str, ratio: str) -> str:
    """Render a highlighted 'element' screenshot so the report embeds a real image."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (760, 240), "#ffffff")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 740, 220], outline="#dddddd", width=1)
    d.text((40, 40), "DEMO PAGE (synthetic evidence)", fill="#333333")
    d.rectangle([40, 90, 420, 150], outline="#e11", width=3)   # highlight box
    d.text((52, 110), text, fill="#a5a5a5")
    d.text((40, 170), f"measured contrast {ratio}", fill="#333333")
    buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
    key = f"{JOB}/evidence/{abs(hash(text)) % 10000}.png"
    storage.put_bytes(key, buf.getvalue(), "image/png")
    return key


def _finding(sc, rule, impact, selector, desc, computed, shot=None) -> Finding:
    c = wcag.criterion(sc)
    return Finding(
        job_id=JOB, target_type=TargetType.web, target_ref="https://demo.example.com",
        sc_num=sc, sc_name=c["name"], level=c["level"], principle=c["principle"],
        wcag_versions=c["versions"], status=Status.fail, confidence=Confidence.high,
        auto_decidable=(c["testability"] == "auto"), engine="axe-core",
        engine_rule_id=rule, engines_agreeing=["axe-core", "ibm-equal-access"],
        impact=impact, selector=selector, html_snippet="<a class='x'>Read more</a>",
        computed=computed, screenshot_key=shot, occurrences=2,
        locations=[Location(ref="https://demo.example.com", count=1),
                   Location(ref="https://demo.example.com/pricing", count=1)],
        description=desc, remediation="",  # filled by KB below
    )


def build() -> None:
    from backend.app.reporting import remediation_kb
    findings = [
        _finding("1.4.3", "color-contrast", Impact.serious, "main a.link",
                 "Elements must have sufficient color contrast",
                 {"contrast_ratio": 2.32, "fg": "#a5a5a5", "bg": "#ffffff", "required": 4.5},
                 _fake_screenshot("low-contrast link text", "2.32:1")),
        _finding("1.1.1", "image-alt", Impact.serious, "img#hero",
                 "Images must have alternate text", {"alt": "missing"}),
        _finding("2.4.4", "link-name", Impact.moderate, "a.more",
                 "Links must have discernible text", {"text": "empty"}),
        _finding("4.1.2", "button-name", Impact.serious, "button.icon",
                 "Buttons must have discernible text", {"name": "missing"}),
        _finding("3.1.1", "html-has-lang", Impact.moderate, "html",
                 "<html> element must have a lang attribute", {"lang": "missing"}),
    ]
    for f in findings:
        f.remediation = remediation_kb.get(f.sc_num, f.engine_rule_id, f.description)

    meta = {
        "target_ref": "https://demo.example.com", "target_type": "web",
        "scan_date": "2026-07-11T12:00:00+00:00",
        "auditor_org": "Accessibility Compliance Audit Platform (DEMO)",
        "discovery": {"subfinder": 4, "certspotter": 6, "crt.sh": 9},
        "hosts_live": ["https://demo.example.com"], "hosts_out_of_scope": [],
        "pages_crawled": 42, "pages_scanned": 8, "templates": 5, "sampling": {},
        "engines": {"axe-core": {"clean": 6, "violations": 2, "error": 0},
                    "pa11y": {"clean": 7, "violations": 1, "error": 0},
                    "lighthouse": {"clean": 8, "violations": 0, "error": 0},
                    "ibm-equal-access": {"clean": 6, "violations": 2, "error": 0}},
        "auto_clean": True, "unmapped_rules": {},
        "tool_versions": {"axe-core": "4.10", "pa11y": "8.0", "lighthouse": "12.2",
                          "ibm-equal-access": "3.1", "node": "installed"},
    }

    out = settings.artifacts_dir / JOB / "reports"
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for version, level in settings.report_matrix:
        combo = common.build_combo(version, level, findings, auto_clean=True)
        base = f"WCAG_{version}_{level}"
        docx_report.build_docx(combo, meta, str(out / f"{base}.docx"))
        xlsx_report.build_xlsx(combo, meta, str(out / f"{base}.xlsx"))
        made.append(base)
        print(f"  built {base}: {combo['counts']['Fail']} fail, "
              f"{combo['counts']['Needs Manual Review']} needs-review, "
              f"{combo['counts']['Pass']} pass")
    print(f"\n{len(made)} combos × 2 formats = {len(made) * 2} files in {out}")


if __name__ == "__main__":
    build()
