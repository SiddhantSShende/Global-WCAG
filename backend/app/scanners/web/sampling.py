"""Template-based sampling.

Accessibility defects recur per *template* (every product page shares the same
markup), so scanning all 10,000 near-identical pages wastes compute and bloats
the report. We cluster discovered URLs by structural template and audit a few
representatives per template — and record exactly what was sampled in the
report's methodology (honesty > false completeness).
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from ...config import settings

_NUM = re.compile(r"^\d+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX = re.compile(r"^[0-9a-f]{12,}$", re.I)
_DATE = re.compile(r"^\d{4}([-/]\d{2}){0,2}$")
_SLUGNUM = re.compile(r"\d")


def _segment_token(seg: str) -> str:
    if not seg:
        return ""
    if _NUM.match(seg):
        return "{id}"
    if _UUID.match(seg):
        return "{uuid}"
    if _HEX.match(seg):
        return "{hash}"
    if _DATE.match(seg):
        return "{date}"
    # long slug with digits (e.g. product-12345-name) -> collapse
    if len(seg) > 24 and _SLUGNUM.search(seg):
        return "{slug}"
    return seg


def template_key(url: str) -> str:
    p = urlparse(url)
    segs = [s for s in p.path.split("/") if s != ""]
    tokens = [_segment_token(s) for s in segs]
    return f"{p.netloc}/" + "/".join(tokens)


def cluster_and_sample(urls: list[str], per_template: int | None = None) -> dict:
    """Returns {'sampled': [urls], 'templates': {key: {'count': n, 'examples': [...]}}}."""
    per_template = per_template or settings.pages_per_template
    groups: dict[str, list[str]] = {}
    for u in urls:
        groups.setdefault(template_key(u), []).append(u)

    sampled: list[str] = []
    templates: dict[str, dict] = {}
    for key, members in sorted(groups.items()):
        reps = members[:per_template]
        sampled.extend(reps)
        templates[key] = {"count": len(members), "sampled": len(reps),
                          "examples": reps}
    return {"sampled": sampled, "templates": templates,
            "total_urls": len(urls), "total_templates": len(groups)}
