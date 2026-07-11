"""Normalize ATF harness output into canonical Findings (+ node-bounds evidence).

Only ATF ERROR-severity results become `fail` findings (conclusive). WARNING/INFO
are not emitted as fails — the default `needs_manual_review` covers them, plus a
recommended manual TalkBack pass. ATF→WCAG mappings are informative (see
android_atf.json). Reuses the generic dedupe/reconcile from the web normalizer.
"""
from __future__ import annotations

import io
import json
from functools import lru_cache

from ...config import settings
from ...models import Confidence, Finding, Impact, Location, Status, TargetType
from ...storage import storage
from ... import wcag
from ..web import normalize as webnorm   # reuse dedupe/reconcile (engine-agnostic)


@lru_cache
def _map() -> dict:
    path = settings.rule_maps_dir / "android_atf.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _remediation(sc: str, rule: str, desc: str) -> str:
    from ...reporting import remediation_kb
    return remediation_kb.get(sc, rule, desc)


def _crop_and_store(job_id: str, screenshot_local: str | None, bounds: dict | None,
                    finding_id: str) -> tuple[str | None, str | None]:
    """Returns (page_key, evidence_key). Crops to node bounds + highlight box."""
    if not screenshot_local:
        return None, None
    try:
        from PIL import Image, ImageDraw
        img = Image.open(screenshot_local).convert("RGB")
        # full screen (context)
        pbuf = io.BytesIO(); img.save(pbuf, "PNG", optimize=True)
        page_key = f"{job_id}/pages/{finding_id}.png"
        storage.put_bytes(page_key, pbuf.getvalue(), "image/png")
        if not bounds:
            return page_key, None
        d = ImageDraw.Draw(img)
        l, t, r, b = bounds["left"], bounds["top"], bounds["right"], bounds["bottom"]
        d.rectangle([l, t, r, b], outline="#e11", width=4)
        pad = 24
        crop = img.crop((max(0, l - pad), max(0, t - pad),
                         min(img.width, r + pad), min(img.height, b + pad)))
        w = settings.screenshot_max_width_px
        if crop.width > w:
            crop = crop.resize((w, int(crop.height * w / crop.width)))
        cbuf = io.BytesIO(); crop.save(cbuf, "PNG", optimize=True)
        ev_key = f"{job_id}/evidence/{finding_id}.png"
        storage.put_bytes(ev_key, cbuf.getvalue(), "image/png")
        return page_key, ev_key
    except Exception as exc:  # noqa: BLE001
        print(f"[android.evidence] {exc}")
        return None, None


def screens_to_findings(job_id: str, screens: list[dict]) -> list[Finding]:
    rmap = _map()
    out: list[Finding] = []
    for screen in screens:
        ref = f"screen[{screen.get('index', 0)}] {screen.get('package', '')}".strip()
        shot = screen.get("screenshot_local")
        for res in screen.get("results", []):
            if res.get("type") != "ERROR":
                continue
            check = res.get("checkClass", "")
            sc = rmap.get(check)
            if not sc:
                webnorm._record_unmapped("android-atf", check)
                continue
            try:
                crit = wcag.criterion(sc)
            except StopIteration:
                webnorm._record_unmapped("android-atf", check)
                continue
            f = Finding(
                job_id=job_id, target_type=TargetType.android, target_ref=ref,
                sc_num=sc, sc_name=crit["name"], level=crit["level"],
                principle=crit["principle"], wcag_versions=crit["versions"],
                status=Status.fail, confidence=Confidence.medium,
                auto_decidable=False,   # mobile mappings are informative, not auto-Pass
                engine="android-atf", engine_rule_id=check, engines_agreeing=["android-atf"],
                impact=Impact.serious,
                selector=res.get("viewId") or "", html_snippet=None,
                computed={"bounds": res.get("bounds"), "check": check},
                description=res.get("message", ""),
                remediation=_remediation(sc, check, res.get("message", "")),
                locations=[Location(ref=ref, count=1)],
            )
            page_key, ev_key = _crop_and_store(job_id, shot, res.get("bounds"), f.finding_id)
            f.screenshot_key = ev_key
            f.page_screenshot_key = page_key
            out.append(f)
    return webnorm.finalize(out)
