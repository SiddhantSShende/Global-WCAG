"""Normalize XCUITest accessibility-audit issues into canonical Findings.

Every returned audit issue is a real, machine-detected problem → `fail`. The
audit type maps to a WCAG SC (informative — see ios_xcuitest.json). Apple's audit
result doesn't reliably expose element frames through Appium, so evidence is the
full screen where the issue was found (honest — we show the screen and name the
element by Apple's description, and never fabricate a crop we can't locate).
Reuses the generic dedupe/reconcile from the web normalizer.
"""
from __future__ import annotations

import io
import json
from functools import lru_cache

from ...config import settings
from ...models import Confidence, Finding, Impact, Location, Status, TargetType
from ...storage import storage
from ... import wcag
from ..web import normalize as webnorm


@lru_cache
def _map() -> dict:
    data = json.loads((settings.rule_maps_dir / "ios_xcuitest.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _sc_for(audit_type: str) -> str | None:
    m = _map()
    if audit_type in m:
        return m[audit_type]
    # Accept full names like 'XCUIAccessibilityAuditTypeContrast'
    short = audit_type.replace("XCUIAccessibilityAuditType", "")
    short = short[:1].lower() + short[1:]
    return m.get(short)


def _store_screen(job_id: str, png: bytes, finding_id: str) -> str | None:
    if not png:
        return None
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png)).convert("RGB")
        w = settings.screenshot_max_width_px
        if img.width > w:
            img = img.resize((w, int(img.height * w / img.width)))
        buf = io.BytesIO(); img.save(buf, "PNG", optimize=True)
        key = f"{job_id}/pages/{finding_id}.png"
        storage.put_bytes(key, buf.getvalue(), "image/png")
        return key
    except Exception:
        return None


def _remediation(sc: str, rule: str, desc: str) -> str:
    from ...reporting import remediation_kb
    return remediation_kb.get(sc, rule, desc)


def screens_to_findings(job_id: str, screens: list[dict]) -> list[Finding]:
    out: list[Finding] = []
    for screen in screens:
        ref = f"screen[{screen.get('index', 0)}] {screen.get('package', '')}".strip()
        audit = screen.get("audit") or {}
        png = screen.get("screenshot")   # raw PNG bytes from driver.capture
        page_key = _store_screen(job_id, png, f"s{screen.get('index', 0)}") if png else None
        for issue in audit.get("issues", []):
            audit_type = issue.get("type") or issue.get("auditType") or ""
            sc = _sc_for(audit_type)
            if not sc:
                webnorm._record_unmapped("ios-xcuitest", audit_type or "unknown")
                continue
            try:
                crit = wcag.criterion(sc)
            except StopIteration:
                webnorm._record_unmapped("ios-xcuitest", audit_type)
                continue
            desc = issue.get("detailedDescription") or issue.get("compactDescription") or ""
            f = Finding(
                job_id=job_id, target_type=TargetType.ios, target_ref=ref,
                sc_num=sc, sc_name=crit["name"], level=crit["level"],
                principle=crit["principle"], wcag_versions=crit["versions"],
                status=Status.fail, confidence=Confidence.medium, auto_decidable=False,
                engine="ios-xcuitest", engine_rule_id=audit_type,
                engines_agreeing=["ios-xcuitest"], impact=Impact.serious,
                selector=None, html_snippet=None,
                computed={"compact": issue.get("compactDescription", ""), "auditType": audit_type},
                description=desc, remediation=_remediation(sc, audit_type, desc),
                screenshot_key=page_key, page_screenshot_key=page_key,
                locations=[Location(ref=ref, count=1)],
            )
            out.append(f)
    return webnorm.finalize(out)
