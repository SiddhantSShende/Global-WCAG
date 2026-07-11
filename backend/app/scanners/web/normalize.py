"""Turn each engine's raw output into canonical `Finding`s, then dedupe and
reconcile across engines.

Rules:
  • Only DEFINITE violations become `fail` findings. Ambiguous signals
    (axe `incomplete`, IBM `potentialviolation`) are counted but never emitted
    as a Pass or a Fail — the default `needs_manual_review` covers them.
  • A rule that maps to no registered SC is LOGGED (counter), never silently
    dropped into a report.
  • Reconciliation across engines: same (sc, selector) hit by ≥2 engines →
    confidence `high` and `engines_agreeing` lists them. A lone engine → keep,
    confidence per §4. Engine silence never upgrades another engine's fail.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from ...config import settings
from ...models import Confidence, Finding, Impact, Location, Status, TargetType
from ... import wcag

# ── rule maps ────────────────────────────────────────────────────────────────

@lru_cache
def _rule_map(engine_file: str) -> dict:
    path = settings.rule_maps_dir / engine_file
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


unmapped_rules: dict[str, int] = {}


def _record_unmapped(engine: str, rule_id: str) -> None:
    unmapped_rules[f"{engine}:{rule_id}"] = unmapped_rules.get(f"{engine}:{rule_id}", 0) + 1


# ── helpers ──────────────────────────────────────────────────────────────────

_HTMLCS_SC = re.compile(r"Guideline\d+_\d+\.(\d+_\d+_\d+)")
_AXE_IMPACT = {"critical": Impact.blocker, "serious": Impact.serious,
               "moderate": Impact.moderate, "minor": Impact.minor, None: Impact.moderate}


def _sc_registered(sc_num: str) -> dict | None:
    try:
        return wcag.criterion(sc_num)
    except StopIteration:
        return None


def _remediation(sc_num: str, rule_id: str, description: str) -> str:
    try:
        from ...reporting import remediation_kb
        return remediation_kb.get(sc_num, rule_id, description)
    except Exception:
        crit = _sc_registered(sc_num)
        url = crit["understanding_url"] if crit else ""
        return (f"Review WCAG {sc_num} and remediate the flagged elements. "
                f"See W3C Understanding: {url}")


def _mk(job_id: str, url: str, sc_num: str, engine: str, rule_id: str,
        impact: Impact, selector: str | None, snippet: str | None,
        computed: dict, description: str) -> Finding | None:
    crit = _sc_registered(sc_num)
    if crit is None:
        _record_unmapped(engine, rule_id)
        return None
    if settings.redact_pii:
        from ..redact import redact_text
        snippet = redact_text(snippet)
        description = redact_text(description)
    return Finding(
        job_id=job_id, target_type=TargetType.web, target_ref=url,
        sc_num=sc_num, sc_name=crit["name"], level=crit["level"],
        principle=crit["principle"], wcag_versions=crit["versions"],
        status=Status.fail,
        confidence=Confidence.high if crit["testability"] == "auto" else Confidence.medium,
        auto_decidable=(crit["testability"] == "auto"),
        engine=engine, engine_rule_id=rule_id, engines_agreeing=[engine],
        impact=impact,
        selector=selector, html_snippet=(snippet or "")[:600],
        computed=computed, description=description,
        remediation=_remediation(sc_num, rule_id, description),
        locations=[Location(ref=url, count=1)],
    )


# ── per-engine normalizers ───────────────────────────────────────────────────

def axe_to_findings(job_id: str, url: str, data: dict) -> list[Finding]:
    rmap = _rule_map("axe.json")
    out = []
    for v in (data or {}).get("violations", []):
        sc = rmap.get(v["id"])
        if not sc:
            _record_unmapped("axe-core", v["id"])
            continue
        impact = _AXE_IMPACT.get(v.get("impact"), Impact.moderate)
        for node in v.get("nodes", []):
            computed = {}
            for chk in node.get("any", []) + node.get("all", []) + node.get("none", []):
                if chk.get("data"):
                    computed[chk.get("id", "data")] = chk["data"]
            f = _mk(job_id, url, sc, "axe-core", v["id"], impact,
                    ", ".join(node.get("target", [])), node.get("html", ""),
                    computed, v.get("help", ""))
            if f:
                out.append(f)
    return out


def pa11y_to_findings(job_id: str, url: str, data: dict) -> list[Finding]:
    overrides = _rule_map("pa11y.json")
    out = []
    for issue in (data or {}).get("issues", []):
        if issue.get("type") != "error":
            continue
        code = issue.get("code", "")
        sc = overrides.get(code)
        if not sc:
            m = _HTMLCS_SC.search(code)
            sc = m.group(1).replace("_", ".") if m else None
        if not sc:
            _record_unmapped("pa11y", code)
            continue
        f = _mk(job_id, url, sc, "pa11y", code, Impact.serious,
                issue.get("selector"), issue.get("context"),
                {"code": code}, issue.get("message", ""))
        if f:
            out.append(f)
    return out


def lighthouse_to_findings(job_id: str, url: str, data: dict) -> list[Finding]:
    rmap = _rule_map("lighthouse.json")
    out = []
    for audit_id, a in (data or {}).get("audits", {}).items():
        if a.get("score") != 0:
            continue
        if a.get("scoreDisplayMode") in ("notApplicable", "informative", "manual"):
            continue
        sc = rmap.get(audit_id)
        if not sc:
            _record_unmapped("lighthouse", audit_id)
            continue
        items = (a.get("details") or {}).get("items", []) or [{}]
        for it in items:
            node = it.get("node", {}) if isinstance(it, dict) else {}
            f = _mk(job_id, url, sc, "lighthouse", audit_id, Impact.serious,
                    node.get("selector"), node.get("snippet"),
                    {"title": a.get("title", "")}, a.get("title", ""))
            if f:
                out.append(f)
    return out


def ibm_to_findings(job_id: str, url: str, data: dict) -> list[Finding]:
    rmap = _rule_map("ibm.json")
    out = []
    for r in (data or {}).get("results", []):
        if r.get("level") != "violation":
            continue
        rule_id = r.get("ruleId", "") or r.get("reasonId", "")
        sc = rmap.get(rule_id)
        if not sc:
            _record_unmapped("ibm-equal-access", rule_id)
            continue
        path = r.get("path", {})
        selector = path.get("dom") if isinstance(path, dict) else None
        f = _mk(job_id, url, sc, "ibm-equal-access", rule_id, Impact.serious,
                selector, r.get("snippet"), {"messageId": r.get("messageArgs")},
                r.get("message", ""))
        if f:
            out.append(f)
    return out


_NORMALIZERS = {
    "axe-core": axe_to_findings,
    "pa11y": pa11y_to_findings,
    "lighthouse": lighthouse_to_findings,
    "ibm-equal-access": ibm_to_findings,
}


def normalize_page(job_id: str, url: str, raw: dict) -> list[Finding]:
    out = []
    for engine, data in raw.items():
        if data is None:
            continue
        fn = _NORMALIZERS.get(engine)
        if fn:
            out.append(fn(job_id, url, data))
    return [f for sub in out for f in sub]


# ── dedupe + reconcile ───────────────────────────────────────────────────────

_SEL_NTH = re.compile(r":nth-child\(\d+\)")


def _norm_selector(sel: str | None) -> str:
    if not sel:
        return ""
    return _SEL_NTH.sub(":nth-child(n)", sel).strip().lower()


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Merge same (sc, engine_rule, selector) across pages → occurrences/locations."""
    bucket: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.sc_num, f.engine, f.engine_rule_id, _norm_selector(f.selector))
        if key in bucket:
            b = bucket[key]
            b.occurrences += 1
            ref = f.locations[0].ref if f.locations else f.target_ref
            for loc in b.locations:
                if loc.ref == ref:
                    loc.count += 1
                    break
            else:
                b.locations.append(Location(ref=ref, count=1))
        else:
            f.occurrences = 1
            bucket[key] = f
    return list(bucket.values())


def reconcile(findings: list[Finding]) -> list[Finding]:
    """Merge across engines by (sc, selector). Agreement → confidence high."""
    bucket: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.sc_num, _norm_selector(f.selector))
        if key in bucket:
            b = bucket[key]
            if f.engine not in b.engines_agreeing:
                b.engines_agreeing.append(f.engine)
            b.occurrences += f.occurrences
            for loc in f.locations:
                for bl in b.locations:
                    if bl.ref == loc.ref:
                        bl.count += loc.count
                        break
                else:
                    b.locations.append(Location(ref=loc.ref, count=loc.count))
            # Prefer the richest evidence / worst impact.
            if _impact_rank(f.impact) > _impact_rank(b.impact):
                b.impact = f.impact
            if not b.computed and f.computed:
                b.computed = f.computed
        else:
            bucket[key] = f
    for b in bucket.values():
        if len(b.engines_agreeing) >= 2:
            b.confidence = Confidence.high
    return list(bucket.values())


def _impact_rank(i: Impact) -> int:
    return {Impact.blocker: 3, Impact.serious: 2, Impact.moderate: 1, Impact.minor: 0}[i]


def finalize(findings: list[Finding]) -> list[Finding]:
    """Full pipeline: dedupe within engine, then reconcile across engines."""
    return reconcile(dedupe(findings))
