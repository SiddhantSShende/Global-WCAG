#!/usr/bin/env python3
"""
ingest_wcag.py — FACTS layer of the WCAG registry.
===================================================
Produces `wcag_facts.json`: the *authoritative* facts about each WCAG success
criterion (number, name, conformance level, version applicability, principle /
guideline, Understanding URL). These are W3C facts — NOT our opinion.

Provenance model (see the build plan, Part C — "no fabricated data"):
  • FACTS (this file)        — what each criterion IS. Sourced from the W3C
                               Recommendations. A vetted snapshot lives in
                               `build_wcag_json.py`; `--fetch` cross-checks the
                               snapshot's counts against the live W3C TR pages.
  • ENRICHMENT (enrich_testability.py) — how far a MACHINE can go on each
                               criterion (auto/semi/manual). That is OUR
                               editorial engineering judgment and is labelled
                               as such in the output — never presented as W3C's.

Run order:  python ingest_wcag.py [--fetch]   →   python enrich_testability.py

`--fetch` downloads the three W3C TR pages and verifies that the number of
success criteria we ship matches the live standard. It NEVER silently rewrites
field text from scraped HTML (that would need a reviewed, machine-readable
mapping — flagged [re-verify] in the plan); it only validates counts and warns
on drift, so a network blip can't corrupt the registry.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

# The vetted snapshot of facts (also our historical builder). We import the raw
# criteria tuples and shared maps so there is a single source of record.
from build_wcag_json import (  # noqa: E402
    CRITERIA,
    GUIDELINES,
    PRINCIPLES,
    versions_for,
    level_scope,
)

# Authoritative W3C sources for the facts (for provenance + `--fetch` checks).
# [re-verify] exact machine-readable endpoints when refreshing; the TR pages
# below are the normative human-readable Recommendations.
W3C_SOURCES = {
    "2.0": "https://www.w3.org/TR/WCAG20/",
    "2.1": "https://www.w3.org/TR/WCAG21/",
    "2.2": "https://www.w3.org/TR/WCAG22/",
    "guidelines_repo": "https://github.com/w3c/wcag/tree/main/guidelines",
    "quickref": "https://www.w3.org/WAI/WCAG22/quickref/",
}

# Published, well-known cumulative scope sizes per (version, level). Level counts
# are cumulative (AAA includes A+AA). The 2.2 numbers RETAIN the obsolete 4.1.1
# (so 2.2/AAA == 87); the active-standard 2.2 total excluding 4.1.1 is 86.
EXPECTED_SCOPE = {
    ("2.0", "A"): 25, ("2.0", "AA"): 38, ("2.0", "AAA"): 61,
    ("2.1", "A"): 30, ("2.1", "AA"): 50, ("2.1", "AAA"): 78,
    ("2.2", "A"): 32, ("2.2", "AA"): 56, ("2.2", "AAA"): 87,
}
# Active WCAG 2.2 counts once the obsolete 4.1.1 Parsing is removed.
ACTIVE_2_2 = {"A": 31, "AA": 55, "AAA": 86}


def build_facts() -> dict:
    """Facts-only records (no testability, no remediation)."""
    records = []
    for num, name, level, added_in, _testability, _note in CRITERIA:
        p, g, _ = num.split(".")
        guideline = f"{p}.{g}"
        slug = (
            name.lower()
            .replace(" ", "-").replace("(", "").replace(")", "").replace(",", "")
        )
        records.append({
            "id": f"SC{num}",
            "num": num,
            "name": name,
            "level": level,
            "principle_num": p,
            "principle": PRINCIPLES[p],
            "guideline_num": guideline,
            "guideline": GUIDELINES[guideline],
            "added_in": added_in,
            "versions": versions_for(num, added_in),
            "obsolete_in": "2.2" if num == "4.1.1" else None,
            "understanding_url": f"https://www.w3.org/WAI/WCAG22/Understanding/{slug}.html",
        })
    return {
        "meta": {
            "layer": "facts",
            "provenance": "W3C WCAG 2.0/2.1/2.2 Recommendations",
            "sources": W3C_SOURCES,
            "note": "Facts only. Testability + remediation are added by "
                    "enrich_testability.py and are this project's editorial "
                    "judgment, not W3C's.",
        },
        "criteria": records,
    }


def scope_size(data: dict, version: str, level: str) -> int:
    levels = set(level_scope(level))
    return sum(
        1 for c in data["criteria"]
        if version in c["versions"] and c["level"] in levels
    )


def verify_counts(data: dict) -> list[str]:
    """Assert our shipped facts match published WCAG scope sizes."""
    errors = []
    for (ver, lvl), expected in EXPECTED_SCOPE.items():
        got = scope_size(data, ver, lvl)
        if got != expected:
            errors.append(f"scope({ver},{lvl}) = {got}, expected {expected}")
    # Active 2.2 (excluding obsolete 4.1.1)
    active = {c["num"] for c in data["criteria"]
              if "2.2" in c["versions"] and c["num"] != "4.1.1"}
    if len(active) != ACTIVE_2_2["AAA"]:
        errors.append(f"active 2.2 total = {len(active)}, expected {ACTIVE_2_2['AAA']}")
    return errors


def fetch_live_sc_counts() -> dict[str, int]:
    """Best-effort: download W3C TR pages and count distinct success criteria.
    Returns {} on any network failure (caller warns, does not fail the build)."""
    counts: dict[str, int] = {}
    sc_re = re.compile(r"\b([1-4]\.\d{1,2}\.\d{1,2})\b")
    for ver in ("2.0", "2.1", "2.2"):
        try:
            req = urllib.request.Request(
                W3C_SOURCES[ver], headers={"User-Agent": "a11y-audit-ingest/1.0"}
            )
            html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
            counts[ver] = len(set(sc_re.findall(html)))
        except Exception as exc:  # noqa: BLE001 — network is optional
            print(f"  [warn] could not fetch W3C {ver}: {exc}", file=sys.stderr)
    return counts


def main() -> int:
    # Windows consoles default to cp1252; force UTF-8 so status glyphs print.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    data = build_facts()

    errors = verify_counts(data)
    if errors:
        print("FACTS VERIFICATION FAILED (snapshot drifted from published WCAG):")
        for e in errors:
            print(f"  ✗ {e}")
        return 1
    print(f"✔ Facts verified: {len(data['criteria'])} criteria; "
          "scope sizes match published WCAG (2.0=61, 2.1=78, 2.2=86 active + "
          "retained-obsolete 4.1.1 = 87).")

    if "--fetch" in sys.argv:
        print("Cross-checking against live W3C TR pages…")
        live = fetch_live_sc_counts()
        # Live pages list every SC that ever applied to that version, so compare
        # to the union of criteria per version (retaining obsolete for coverage).
        for ver in ("2.0", "2.1", "2.2"):
            if ver not in live:
                continue
            ours = sum(1 for c in data["criteria"] if ver in c["versions"])
            mark = "≈" if abs(live[ver] - ours) <= 2 else "✗"
            print(f"  {mark} {ver}: live≈{live[ver]} SC mentioned, registry={ours}")
        print("  (live count is heuristic — SC numbers are also cross-referenced "
              "in prose; field text remains from the vetted snapshot [re-verify]).")

    out = HERE / "wcag_facts.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
