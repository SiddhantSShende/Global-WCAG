"""WCAG registry service — the ONE place a criterion's status is decided.

`derive_status` encodes the anti-fabrication contract. No other code in the
platform may set a criterion-level status. If you find yourself writing status
logic elsewhere, route it through here instead.
"""
from __future__ import annotations

import json
from functools import lru_cache

from .config import settings
from .models import Confidence, Finding, Status


@lru_cache
def registry() -> dict:
    return json.loads(settings.wcag_json.read_text(encoding="utf-8"))


def _level_scope(level: str) -> set[str]:
    """Cumulative: an AAA report includes A+AA+AAA; AA includes A+AA."""
    return {"A": {"A"}, "AA": {"A", "AA"}, "AAA": {"A", "AA", "AAA"}}[level]


def criteria_in_scope(version: str, level: str) -> list[dict]:
    lv = _level_scope(level)
    return [
        c for c in registry()["criteria"]
        if version in c["versions"] and c["level"] in lv
    ]


def criterion(sc_num: str) -> dict:
    return next(c for c in registry()["criteria"] if c["num"] == sc_num)


def is_obsolete(crit: dict, version: str) -> bool:
    """4.1.1 Parsing is obsolete in 2.2 — never a real Pass/Fail there."""
    return crit.get("obsolete_in") == version


def derive_status(
    crit: dict,
    findings: list[Finding],
    reviewer_verdict: Status | None = None,
    auto_clean: bool = True,
) -> tuple[Status, Confidence]:
    """The single source of truth for a criterion's row status.

    ANTI-FABRICATION RULES:
      1. Any confirmed `fail` finding wins immediately.
      2. A human reviewer's verdict is authoritative (the ONLY path to a
         non-`auto` Pass).
      3. An `auto` criterion with no violation is a real Pass — but ONLY if the
         engines that decide it ran cleanly (`auto_clean`). If any engine
         errored/timed out (`auto_clean=False`), we cannot certify it, so it
         becomes `needs_manual_review` (fail-closed), never a silent Pass.
      4. Everything else (semi/manual with no confirmed violation) is
         `needs_manual_review` — we simply don't know.

    `auto_clean` is supplied by the combo builder from the job's EngineRun log.
    """
    mine = [f for f in findings if f.sc_num == crit["num"]]
    fails = [f for f in mine if f.status == Status.fail]

    if fails:
        return Status.fail, Confidence.high

    if reviewer_verdict is not None:
        return reviewer_verdict, Confidence.high

    if crit["testability"] == "auto":
        if auto_clean:
            return Status.pass_, Confidence.high
        # engine error on an auto criterion -> cannot certify
        return Status.needs_manual_review, Confidence.low

    # semi / manual with no confirmed violation -> unknown
    return Status.needs_manual_review, Confidence.low


def scope_summary(version: str, level: str) -> dict:
    """Coverage stats for a combo's executive-summary table, honestly counting
    the obsolete 4.1.1 out of the 2.2 denominator."""
    crits = criteria_in_scope(version, level)
    active = [c for c in crits if not is_obsolete(c, version)]
    return {
        "version": version,
        "level": level,
        "total_in_scope": len(crits),
        "active_in_scope": len(active),
        "obsolete_count": len(crits) - len(active),
        "auto": sum(1 for c in active if c["testability"] == "auto"),
        "semi": sum(1 for c in active if c["testability"] == "semi"),
        "manual": sum(1 for c in active if c["testability"] == "manual"),
    }
