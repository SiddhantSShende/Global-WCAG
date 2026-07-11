"""PII redaction for authenticated-scan artifacts.

Two layers:
  • redact_text  — masks emails, card-like numbers, long digit runs, and bearer
                   tokens in evidence snippets/descriptions.
  • redact_image — blacks out given bounding boxes in a screenshot (e.g. fields
                   matched by settings.redact_selectors).

Redaction is on by default (settings.redact_pii) and matters most for
authenticated scans that can capture personal data. The JS that masks sensitive
form fields *before* the screenshot is taken lives in evidence.py.
"""
from __future__ import annotations

import io
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_LONGNUM = re.compile(r"\b\d{7,}\b")
_BEARER = re.compile(r"(?i)\b(bearer|token|apikey|api_key|authorization)\b[=:]\s*\S+")


def redact_text(text: str | None) -> str:
    if not text:
        return text or ""
    text = _EMAIL.sub("[redacted-email]", text)
    text = _CARD.sub("[redacted-number]", text)
    text = _BEARER.sub(r"\1=[redacted]", text)
    text = _LONGNUM.sub("[redacted-number]", text)
    return text


def redact_image(png: bytes, boxes: list[dict]) -> bytes:
    """Black out each box {left,top,right,bottom} in the PNG. Returns PNG bytes."""
    if not boxes:
        return png
    try:
        from PIL import Image, ImageDraw
        img = Image.open(io.BytesIO(png)).convert("RGB")
        d = ImageDraw.Draw(img)
        for b in boxes:
            d.rectangle([b["left"], b["top"], b["right"], b["bottom"]], fill="#000000")
        out = io.BytesIO(); img.save(out, "PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return png
