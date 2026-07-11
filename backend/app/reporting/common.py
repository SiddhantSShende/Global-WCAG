"""Scope findings to one (version, level) combo and validate before a report ships.

`build_combo` derives every in-scope criterion's row status via the single
`wcag.derive_status` function, collects the confirmed issues, and computes the
coverage + severity tables. `validate` is the mandatory pre-report gate — if any
row would contradict the anti-fabrication contract, it raises and the build
aborts. A contradictory report never reaches a user.
"""
from __future__ import annotations

from .. import wcag
from ..models import Finding, Status

_STATUS_LABEL = {
    Status.fail: "Fail",
    Status.partial: "Partial",
    Status.pass_: "Pass",
    Status.needs_manual_review: "Needs Manual Review",
    Status.not_applicable: "Not Applicable",
}


def _extract_review(rv) -> tuple[Status | None, str | None, str | None]:
    """Accept a plain Status or a rich {verdict, reviewer, at_technique} record."""
    if rv is None:
        return None, None, None
    if isinstance(rv, Status):
        return rv, None, None
    if isinstance(rv, dict):
        v = rv.get("verdict")
        verdict = Status(v) if isinstance(v, str) else v
        return verdict, rv.get("reviewer"), rv.get("at_technique")
    return rv, None, None


def build_combo(version: str, level: str, findings: list[Finding],
                reviews: dict | None = None,
                auto_clean: bool = True) -> dict:
    reviews = reviews or {}
    rows: list[dict] = []
    issues: list[Finding] = []

    for crit in wcag.criteria_in_scope(version, level):
        num = crit["num"]
        if wcag.is_obsolete(crit, version):
            rows.append({"crit": crit, "status": Status.not_applicable,
                         "confidence": None, "via_review": False,
                         "note": "Obsolete in WCAG 2.2 — not evaluated.",
                         "issue_refs": []})
            continue

        verdict, reviewer, at = _extract_review(reviews.get(num))
        status, conf = wcag.derive_status(crit, findings, verdict, auto_clean)
        crit_fails = [f for f in findings if f.sc_num == num and f.status == Status.fail]
        if status == Status.fail:
            issues.extend(crit_fails)

        via_review = verdict is not None and status != Status.fail
        if via_review:
            who = reviewer or "reviewer"
            note = f"Manually verified by {who}" + (f" using {at}" if at else "")
        elif status == Status.needs_manual_review:
            note = ("Not machine-decidable at a level that proves conformance — "
                    "requires human / assistive-technology review."
                    if crit["testability"] != "auto" else
                    "An engine errored on this auto criterion — cannot certify a pass.")
        else:
            note = ""

        rows.append({
            "crit": crit, "status": status, "confidence": conf,
            "via_review": via_review, "note": note,
            "issue_refs": [f.finding_id for f in crit_fails],
        })

    combo = {
        "version": version, "level": level,
        "rows": rows,
        "issues": _unique(issues),
        "coverage": wcag.scope_summary(version, level),
        "counts": _status_counts(rows),
        "severity": _severity_tally(issues),
        "review_stats": {
            "manually_verified": sum(1 for r in rows if r["via_review"]),
            "open_review": sum(1 for r in rows if r["status"] == Status.needs_manual_review),
        },
    }
    validate(combo, findings)
    return combo


def _unique(findings: list[Finding]) -> list[Finding]:
    seen, out = set(), []
    for f in findings:
        if f.finding_id not in seen:
            seen.add(f.finding_id)
            out.append(f)
    return out


def _status_counts(rows: list[dict]) -> dict:
    counts = {label: 0 for label in _STATUS_LABEL.values()}
    for r in rows:
        counts[_STATUS_LABEL[r["status"]]] += 1
    return counts


def _severity_tally(issues: list[Finding]) -> dict:
    tally = {"blocker": 0, "serious": 0, "moderate": 0, "minor": 0}
    for f in _unique(issues):
        tally[f.impact.value] += 1
    return tally


def validate(combo: dict, findings: list[Finding]) -> None:
    """Mandatory contradiction gate — raises AssertionError to abort the build."""
    for row in combo["rows"]:
        c, st = row["crit"], row["status"]
        fails = [f for f in findings if f.sc_num == c["num"] and f.status == Status.fail]
        assert not (st == Status.pass_ and fails), (
            f"CONTRADICTION: {c['num']} marked Pass but has {len(fails)} fail finding(s)")
        assert not (st == Status.pass_ and c["testability"] != "auto" and not row["via_review"]), (
            f"CONTRADICTION: {c['num']} Pass but not auto-testable and not reviewer-signed")
        assert not (st == Status.pass_ and wcag.is_obsolete(c, combo["version"])), (
            f"CONTRADICTION: obsolete {c['num']} cannot be Pass in {combo['version']}")

    for f in combo["issues"]:
        total = sum(loc.count for loc in f.locations)
        assert f.occurrences == total, (
            f"CONTRADICTION: {f.sc_num} occurrences={f.occurrences} != sum(locations)={total}")


def status_label(status: Status) -> str:
    return _STATUS_LABEL[status]
