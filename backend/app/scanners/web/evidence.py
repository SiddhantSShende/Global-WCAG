"""Screenshot evidence for confirmed failures.

For each `fail` finding: load its page, draw a highlight box over the offending
element, crop to the element + context, downscale (Pillow), and store. Sets
`screenshot_key` (cropped+highlighted) and `page_screenshot_key` (full context).

Degrades honestly: if Playwright isn't installed or an element can't be located,
the finding keeps `screenshot_key = None` and the report notes evidence was not
captured — it never invents an image.
"""
from __future__ import annotations

import hashlib
import io

from ...config import settings
from ...models import Finding
from ...storage import storage

_MASK_JS = """(selectors) => {
  for (const sel of selectors) {
    for (const n of document.querySelectorAll(sel)) {
      const r = n.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const o = document.createElement('div');
      Object.assign(o.style, {position:'absolute', background:'#000',
        zIndex:2147483646, pointerEvents:'none',
        left:(r.left+window.scrollX)+'px', top:(r.top+window.scrollY)+'px',
        width:r.width+'px', height:r.height+'px'});
      document.body.appendChild(o);
    }
  }
}"""

_HIGHLIGHT_JS = """(sel) => {
  const n = document.querySelector(sel);
  if (!n) return null;
  n.scrollIntoView({block: 'center', inline: 'center'});
  const o = document.createElement('div');
  Object.assign(o.style, {position: 'absolute', outline: '3px solid #e11',
    boxShadow: '0 0 0 3px rgba(238,17,17,.35)', zIndex: 2147483647,
    pointerEvents: 'none'});
  const r = n.getBoundingClientRect();
  Object.assign(o.style, {left: (r.left + window.scrollX) + 'px',
    top: (r.top + window.scrollY) + 'px', width: r.width + 'px',
    height: r.height + 'px'});
  o.setAttribute('data-a11y-highlight', '1');
  document.body.appendChild(o);
  return {x: r.left, y: r.top, w: r.width, h: r.height};
}"""


def _downscale(png: bytes) -> tuple[bytes, str]:
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        maxw = settings.screenshot_max_width_px
        if img.width > maxw:
            h = int(img.height * (maxw / img.width))
            img = img.resize((maxw, h), Image.LANCZOS)
        buf = io.BytesIO()
        if settings.report_image_format.upper() == "JPEG":
            img.convert("RGB").save(buf, "JPEG", quality=settings.report_jpeg_quality, optimize=True)
            return buf.getvalue(), "image/jpeg"
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png"
    except Exception:
        return png, "image/png"


def _clip(box: dict, pad: int, page_w: int, page_h: int) -> dict:
    x = max(0, box["x"] - pad)
    y = max(0, box["y"] - pad)
    w = min(page_w - x, box["w"] + 2 * pad)
    h = min(page_h - y, box["h"] + 2 * pad)
    return {"x": x, "y": y, "width": max(1, w), "height": max(1, h)}


def capture_for_findings(job_id: str, findings: list[Finding],
                         storage_state: str | None = None) -> list[Finding]:
    fails = [f for f in findings if f.status.value == "fail" and f.selector]
    if not fails:
        return findings

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        print("[evidence] Playwright not installed — skipping screenshots "
              "(findings remain valid; report notes evidence unavailable).")
        return findings

    by_url: dict[str, list[Finding]] = {}
    for f in fails:
        ref = f.locations[0].ref if f.locations else f.target_ref
        by_url.setdefault(ref, []).append(f)

    ctx_kwargs = {"viewport": {"width": 1366, "height": 900}}
    if storage_state:
        ctx_kwargs["storage_state"] = storage_state   # authenticated evidence

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        context = browser.new_context(**ctx_kwargs)
        for url, group in by_url.items():
            page = None
            try:
                page = context.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=45000)
                except Exception:
                    page.goto(url, wait_until="domcontentloaded", timeout=45000)

                # PII: mask sensitive fields BEFORE any screenshot is captured.
                if settings.redact_pii and settings.redact_selectors:
                    try:
                        page.evaluate(_MASK_JS, list(settings.redact_selectors))
                    except Exception:
                        pass

                page_png = page.screenshot(full_page=True)
                page_key = f"{job_id}/pages/{hashlib.sha1(url.encode()).hexdigest()}.png"
                data, ctype = _downscale(page_png)
                storage.put_bytes(page_key, data, ctype)

                dims = page.evaluate("() => ({w: document.body.scrollWidth, h: document.body.scrollHeight})")
                for f in group:
                    f.page_screenshot_key = page_key
                    first_sel = (f.selector or "").split(",")[0].strip()
                    try:
                        box = page.evaluate(_HIGHLIGHT_JS, first_sel)
                        if not box or box["w"] < 1 or box["h"] < 1:
                            continue
                        clip = _clip(box, 24, dims["w"], dims["h"])
                        shot = page.screenshot(clip=clip)
                        page.evaluate("() => document.querySelectorAll('[data-a11y-highlight]').forEach(e => e.remove())")
                        key = f"{job_id}/evidence/{f.finding_id}.png"
                        data, ctype = _downscale(shot)
                        storage.put_bytes(key, data, ctype)
                        f.screenshot_key = key
                    except Exception as exc:  # noqa: BLE001
                        print(f"[evidence] {url} :: {first_sel}: {exc}")
                        continue
            except Exception as exc:  # noqa: BLE001
                print(f"[evidence] page failed {url}: {exc}")
            finally:
                if page:
                    page.close()
        browser.close()
    return findings
