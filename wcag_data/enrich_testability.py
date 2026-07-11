#!/usr/bin/env python3
"""
enrich_testability.py — ENRICHMENT layer of the WCAG registry.
==============================================================
Reads `wcag_facts.json` (the W3C facts, produced by ingest_wcag.py) and merges
our editorial **testability** classification onto each criterion, emitting the
runtime registry `wcag_criteria.json`.

`testability` = how far an AUTOMATED tool can honestly go on this criterion:
    "auto"   → a machine can decide it AND a clean scan is meaningful evidence
               toward a pass.
    "semi"   → a machine finds SOME violations, but a clean scan does NOT prove
               conformance (needs human confirmation).
    "manual" → not reliably machine-testable; requires a human / assistive-tech.

This classification is THIS PROJECT'S engineering judgment (seeded from the
vetted builder) — it is explicitly NOT part of the W3C standard, and the output
`meta` says so. It exists to power the anti-fabrication rule in
`backend/app/wcag.py:derive_status` (the reporting layer never prints "Pass" for
a `semi`/`manual` criterion unless a human reviewer signs off).

Run:  python ingest_wcag.py  &&  python enrich_testability.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from build_wcag_json import CRITERIA  # vetted source of the testability tags  # noqa: E402

# {sc_num: (testability, note)} — our enrichment, extracted from the seed.
TESTABILITY: dict[str, tuple[str, str]] = {
    num: (testability, note) for num, _n, _l, _v, testability, note in CRITERIA
}

TESTABILITY_LEGEND = {
    "auto": "Machine-decidable; a clean result is meaningful evidence toward a pass.",
    "semi": "Machine finds some violations; a clean result is NOT proof of a pass.",
    "manual": "Not reliably machine-testable; requires human / assistive-tech review.",
}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    facts_path = HERE / "wcag_facts.json"
    if not facts_path.exists():
        print("ERROR: wcag_facts.json not found. Run `python ingest_wcag.py` first.")
        return 1

    facts = json.loads(facts_path.read_text(encoding="utf-8"))

    missing = [c["num"] for c in facts["criteria"] if c["num"] not in TESTABILITY]
    if missing:
        print(f"ERROR: no testability tag for: {missing}")
        return 1

    for c in facts["criteria"]:
        tag, note = TESTABILITY[c["num"]]
        if tag not in TESTABILITY_LEGEND:
            print(f"ERROR: {c['num']} has unknown testability '{tag}'")
            return 1
        c["testability"] = tag
        c["note"] = note

    registry = {
        "meta": {
            "generator": "ingest_wcag.py + enrich_testability.py",
            "facts_provenance": "W3C WCAG 2.0/2.1/2.2 Recommendations",
            "testability_provenance": (
                "EDITORIAL — this project's engineering judgment on machine "
                "testability. NOT part of the W3C standard. Review with a "
                "qualified accessibility specialist."
            ),
            "testability_legend": TESTABILITY_LEGEND,
            "obsolete_note": "4.1.1 Parsing is obsolete in WCAG 2.2 — retained "
                             "here for 2.0/2.1 reports and rendered as "
                             "'Obsolete — not evaluated' in 2.2 coverage tables.",
        },
        "criteria": facts["criteria"],
    }

    # Distribution sanity print.
    dist: dict[str, int] = {}
    for c in registry["criteria"]:
        dist[c["testability"]] = dist.get(c["testability"], 0) + 1

    out = HERE / "wcag_criteria.json"
    out.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✔ Enriched {len(registry['criteria'])} criteria "
          f"(auto={dist.get('auto',0)}, semi={dist.get('semi',0)}, "
          f"manual={dist.get('manual',0)}).")
    print(f"Wrote {out}  (read-only at runtime)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
