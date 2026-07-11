#!/usr/bin/env python3
"""
build_wcag_json.py
==================
Source-of-truth builder for the WCAG success-criteria dataset used by the whole
platform. Emits `wcag_criteria.json`.

WHY THIS EXISTS
---------------
Every engine (axe-core, Pa11y/HTML_CodeSniffer, Lighthouse, IBM Equal Access,
Android Accessibility Test Framework, iOS XCUITest audits) reports issues in its
own vocabulary. This file is the canonical registry that all of them are mapped
*onto*. It also encodes the single most important fact for "no fabricated data":

    `testability` = how far an AUTOMATED tool can actually go on this criterion.
        "auto"   -> a machine can detect real violations AND a clean scan is
                    meaningful evidence toward a pass.
        "semi"   -> a machine can detect SOME violations, but a clean scan does
                    NOT prove conformance (needs human confirmation).
        "manual" -> not reliably machine-testable at all; requires human / AT.

The reporting layer NEVER prints "Pass" for a `semi`/`manual` criterion unless a
human reviewer has signed off. Absent that, it prints "Needs Manual Review".

Canonical totals produced (verify at runtime):
    WCAG 2.2 -> 87 SC counting the obsolete 4.1.1 Parsing (86 excluding it).
    Level A = 32 (incl 4.1.1), AA = 24, AAA = 31.
"""
import json
from pathlib import Path

# (num, name, level, added_in, testability, note)
# testability: auto | semi | manual
CRITERIA = [
    # ---------------- Principle 1: Perceivable ----------------
    ("1.1.1", "Non-text Content", "A", "2.0", "semi",
     "Tools detect missing alt/label. Whether alt text is MEANINGFUL is manual."),
    ("1.2.1", "Audio-only and Video-only (Prerecorded)", "A", "2.0", "manual",
     "Requires human review of media alternatives."),
    ("1.2.2", "Captions (Prerecorded)", "A", "2.0", "manual",
     "Tools can flag <video> without <track>; caption quality is manual."),
    ("1.2.3", "Audio Description or Media Alternative (Prerecorded)", "A", "2.0", "manual", ""),
    ("1.2.4", "Captions (Live)", "AA", "2.0", "manual", ""),
    ("1.2.5", "Audio Description (Prerecorded)", "AA", "2.0", "manual", ""),
    ("1.2.6", "Sign Language (Prerecorded)", "AAA", "2.0", "manual", ""),
    ("1.2.7", "Extended Audio Description (Prerecorded)", "AAA", "2.0", "manual", ""),
    ("1.2.8", "Media Alternative (Prerecorded)", "AAA", "2.0", "manual", ""),
    ("1.2.9", "Audio-only (Live)", "AAA", "2.0", "manual", ""),
    ("1.3.1", "Info and Relationships", "A", "2.0", "semi",
     "Tools catch some structural issues (tables, labels, headings) but not all."),
    ("1.3.2", "Meaningful Sequence", "A", "2.0", "semi",
     "DOM order heuristics only; true reading order is manual."),
    ("1.3.3", "Sensory Characteristics", "A", "2.0", "manual", ""),
    ("1.3.4", "Orientation", "AA", "2.1", "semi",
     "Detect orientation lock in CSS/meta; confirm manually."),
    ("1.3.5", "Identify Input Purpose", "AA", "2.1", "semi",
     "Detect missing/invalid autocomplete on known fields."),
    ("1.3.6", "Identify Purpose", "AAA", "2.1", "manual", ""),
    ("1.4.1", "Use of Color", "A", "2.0", "manual",
     "Cannot reliably know if color is the SOLE means of conveying info."),
    ("1.4.2", "Audio Control", "A", "2.0", "semi",
     "Detect autoplay audio; control presence partly manual."),
    ("1.4.3", "Contrast (Minimum)", "AA", "2.0", "auto",
     "Computable from rendered colors. Strong automation."),
    ("1.4.4", "Resize Text", "AA", "2.0", "semi",
     "Detect user-scalable=no / maximum-scale; reflow after zoom is manual."),
    ("1.4.5", "Images of Text", "AA", "2.0", "manual", ""),
    ("1.4.6", "Contrast (Enhanced)", "AAA", "2.0", "auto",
     "Same engine as 1.4.3 with 7:1 / 4.5:1 thresholds."),
    ("1.4.7", "Low or No Background Audio", "AAA", "2.0", "manual", ""),
    ("1.4.8", "Visual Presentation", "AAA", "2.0", "semi",
     "Some sub-checks (line length, justification) detectable; most manual."),
    ("1.4.9", "Images of Text (No Exception)", "AAA", "2.0", "manual", ""),
    ("1.4.10", "Reflow", "AA", "2.1", "semi",
     "Detect horizontal scroll at 320 CSS px; confirm no content loss manually."),
    ("1.4.11", "Non-text Contrast", "AA", "2.1", "semi",
     "UI-component/graphics contrast is hard to isolate automatically."),
    ("1.4.12", "Text Spacing", "AA", "2.1", "semi",
     "Apply text-spacing override, detect clipping/overlap heuristically."),
    ("1.4.13", "Content on Hover or Focus", "AA", "2.1", "manual", ""),
    # ---------------- Principle 2: Operable ----------------
    ("2.1.1", "Keyboard", "A", "2.0", "semi",
     "Detect obvious non-focusable interactive elements; full op is manual."),
    ("2.1.2", "No Keyboard Trap", "A", "2.0", "manual",
     "Requires interactive keyboard traversal to confirm."),
    ("2.1.3", "Keyboard (No Exception)", "AAA", "2.0", "manual", ""),
    ("2.1.4", "Character Key Shortcuts", "A", "2.1", "manual", ""),
    ("2.2.1", "Timing Adjustable", "A", "2.0", "manual", ""),
    ("2.2.2", "Pause, Stop, Hide", "A", "2.0", "semi",
     "Detect auto-updating/marquee/animation; control presence manual."),
    ("2.2.3", "No Timing", "AAA", "2.0", "manual", ""),
    ("2.2.4", "Interruptions", "AAA", "2.0", "manual", ""),
    ("2.2.5", "Re-authenticating", "AAA", "2.0", "manual", ""),
    ("2.2.6", "Timeouts", "AAA", "2.1", "manual", ""),
    ("2.3.1", "Three Flashes or Below Threshold", "A", "2.0", "semi",
     "Frame-analysis of video can flag flashing; embedded/streamed is manual."),
    ("2.3.2", "Three Flashes", "AAA", "2.0", "semi", ""),
    ("2.3.3", "Animation from Interactions", "AAA", "2.1", "manual", ""),
    ("2.4.1", "Bypass Blocks", "A", "2.0", "semi",
     "Detect presence of skip link / landmarks; effectiveness manual."),
    ("2.4.2", "Page Titled", "A", "2.0", "auto",
     "Presence and non-emptiness of <title> is checkable; relevance is semi."),
    ("2.4.3", "Focus Order", "A", "2.0", "semi",
     "Detect positive tabindex / focusable hidden elements; logic is manual."),
    ("2.4.4", "Link Purpose (In Context)", "A", "2.0", "semi",
     "Detect empty/ambiguous link text; 'in context' meaning is manual."),
    ("2.4.5", "Multiple Ways", "AA", "2.0", "manual", ""),
    ("2.4.6", "Headings and Labels", "AA", "2.0", "semi",
     "Detect empty headings/labels; descriptiveness is manual."),
    ("2.4.7", "Focus Visible", "AA", "2.0", "semi",
     "Detect outline:none patterns; visible-focus proof needs interaction."),
    ("2.4.8", "Location", "AAA", "2.0", "manual", ""),
    ("2.4.9", "Link Purpose (Link Only)", "AAA", "2.0", "semi", ""),
    ("2.4.10", "Section Headings", "AAA", "2.0", "manual", ""),
    ("2.4.11", "Focus Not Obscured (Minimum)", "AA", "2.2", "semi",
     "Requires focusing each element and checking overlay occlusion."),
    ("2.4.12", "Focus Not Obscured (Enhanced)", "AAA", "2.2", "semi", ""),
    ("2.4.13", "Focus Appearance", "AAA", "2.2", "semi",
     "Focus indicator size/contrast partly measurable."),
    ("2.5.1", "Pointer Gestures", "A", "2.1", "manual", ""),
    ("2.5.2", "Pointer Cancellation", "A", "2.1", "manual", ""),
    ("2.5.3", "Label in Name", "A", "2.1", "auto",
     "Compare visible label text vs accessible name programmatically."),
    ("2.5.4", "Motion Actuation", "A", "2.1", "manual", ""),
    ("2.5.5", "Target Size (Enhanced)", "AAA", "2.1", "auto",
     "Measure rendered target box vs 44x44 CSS px."),
    ("2.5.6", "Concurrent Input Mechanisms", "AAA", "2.1", "manual", ""),
    ("2.5.7", "Dragging Movements", "AA", "2.2", "manual", ""),
    ("2.5.8", "Target Size (Minimum)", "AA", "2.2", "auto",
     "Measure rendered target box vs 24x24 CSS px + spacing exception."),
    # ---------------- Principle 3: Understandable ----------------
    ("3.1.1", "Language of Page", "A", "2.0", "auto",
     "Presence/validity of <html lang> is checkable."),
    ("3.1.2", "Language of Parts", "AA", "2.0", "semi", ""),
    ("3.1.3", "Unusual Words", "AAA", "2.0", "manual", ""),
    ("3.1.4", "Abbreviations", "AAA", "2.0", "manual", ""),
    ("3.1.5", "Reading Level", "AAA", "2.0", "semi",
     "Readability scoring (Flesch etc.) is an indicator only."),
    ("3.1.6", "Pronunciation", "AAA", "2.0", "manual", ""),
    ("3.2.1", "On Focus", "A", "2.0", "manual", ""),
    ("3.2.2", "On Input", "A", "2.0", "manual", ""),
    ("3.2.3", "Consistent Navigation", "AA", "2.0", "semi",
     "Compare nav across crawled pages for order consistency."),
    ("3.2.4", "Consistent Identification", "AA", "2.0", "semi", ""),
    ("3.2.5", "Change on Request", "AAA", "2.0", "manual", ""),
    ("3.2.6", "Consistent Help", "A", "2.2", "semi",
     "Detect help mechanism presence/position across pages."),
    ("3.3.1", "Error Identification", "A", "2.0", "manual", ""),
    ("3.3.2", "Labels or Instructions", "A", "2.0", "semi",
     "Detect inputs without programmatic label."),
    ("3.3.3", "Error Suggestion", "AA", "2.0", "manual", ""),
    ("3.3.4", "Error Prevention (Legal, Financial, Data)", "AA", "2.0", "manual", ""),
    ("3.3.5", "Help", "AAA", "2.0", "manual", ""),
    ("3.3.6", "Error Prevention (All)", "AAA", "2.0", "manual", ""),
    ("3.3.7", "Redundant Entry", "A", "2.2", "manual", ""),
    ("3.3.8", "Accessible Authentication (Minimum)", "AA", "2.2", "semi",
     "Detect cognitive-function tests (e.g. CAPTCHA) heuristically."),
    ("3.3.9", "Accessible Authentication (Enhanced)", "AAA", "2.2", "semi", ""),
    # ---------------- Principle 4: Robust ----------------
    ("4.1.1", "Parsing (Obsolete in 2.2)", "A", "2.0", "auto",
     "Obsolete in WCAG 2.2 - always passes. Kept for 2.0/2.1 reports."),
    ("4.1.2", "Name, Role, Value", "A", "2.0", "semi",
     "Strong automation for missing names/roles; completeness is manual."),
    ("4.1.3", "Status Messages", "AA", "2.1", "manual", ""),
]

PRINCIPLES = {"1": "Perceivable", "2": "Operable", "3": "Understandable", "4": "Robust"}
GUIDELINES = {
    "1.1": "Text Alternatives", "1.2": "Time-based Media", "1.3": "Adaptable",
    "1.4": "Distinguishable", "2.1": "Keyboard Accessible", "2.2": "Enough Time",
    "2.3": "Seizures and Physical Reactions", "2.4": "Navigable",
    "2.5": "Input Modalities", "3.1": "Readable", "3.2": "Predictable",
    "3.3": "Input Assistance", "4.1": "Compatible",
}

# Which criteria exist in each WCAG version (by earliest version + removals).
# 4.1.1 is present in 2.0/2.1, obsolete (auto-pass) in 2.2.
def versions_for(num: str, added_in: str) -> list[str]:
    order = ["2.0", "2.1", "2.2"]
    start = order.index(added_in)
    return order[start:]

def level_scope(level: str) -> list[str]:
    """Cumulative scope: an AAA report includes A+AA+AAA; AA includes A+AA."""
    return {"A": ["A"], "AA": ["A", "AA"], "AAA": ["A", "AA", "AAA"]}[level]

def build() -> dict:
    records = []
    for num, name, level, added_in, testability, note in CRITERIA:
        parts = num.split(".")
        guideline = f"{parts[0]}.{parts[1]}"
        records.append({
            "id": f"SC{num}",
            "num": num,
            "name": name,
            "level": level,
            "principle_num": parts[0],
            "principle": PRINCIPLES[parts[0]],
            "guideline_num": guideline,
            "guideline": GUIDELINES[guideline],
            "added_in": added_in,
            "versions": versions_for(num, added_in),
            "testability": testability,
            "obsolete_in": "2.2" if num == "4.1.1" else None,
            "understanding_url":
                f"https://www.w3.org/WAI/WCAG22/Understanding/{name.lower().replace(' ', '-').replace('(', '').replace(')', '').replace(',', '')}.html",
            "note": note,
        })
    return {
        "meta": {
            "generator": "build_wcag_json.py",
            "source": "W3C WCAG 2.0/2.1/2.2 Recommendations",
            "testability_legend": {
                "auto": "Machine-decidable; clean result is meaningful evidence.",
                "semi": "Machine finds some violations; clean result is NOT proof of pass.",
                "manual": "Not reliably machine-testable; requires human/AT review.",
            },
        },
        "criteria": records,
    }

def report_scope(data: dict, version: str, level: str) -> list[dict]:
    """Return criteria in scope for a given (version, level) report combo."""
    levels = level_scope(level)
    out = []
    for c in data["criteria"]:
        if version in c["versions"] and c["level"] in levels:
            out.append(c)
    return out

if __name__ == "__main__":
    data = build()
    out = Path(__file__).parent / "wcag_criteria.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # Print verification matrix for the 6 report combinations.
    print(f"Total criteria records: {len(data['criteria'])}")
    print("\nReport-combination scope sizes (criteria evaluated per report):")
    print(f"{'VERSION':<8}{'A':>6}{'AA':>6}{'AAA':>6}")
    for v in ["2.0", "2.1", "2.2"]:
        row = [v]
        for lvl in ["A", "AA", "AAA"]:
            row.append(str(len(report_scope(data, v, lvl))))
        print(f"{row[0]:<8}{row[1]:>6}{row[2]:>6}{row[3]:>6}")

    print("\nTestability distribution:")
    dist: dict[str, int] = {}
    for c in data["criteria"]:
        dist[c["testability"]] = dist.get(c["testability"], 0) + 1
    for k in ("auto", "semi", "manual"):
        print(f"  {k:<7}: {dist.get(k, 0)}")
    print(f"\nWrote {out}")
