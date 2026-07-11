"""Fixed remediation knowledge base.

Remediation text is TEMPLATED from this KB keyed by success criterion (with
optional rule-level overrides) — it is NEVER invented by a language model. An
LLM may only rephrase this fixed text; it may not add findings, numbers, or
steps. Unknown criteria fall back to a generic pointer to the W3C Understanding
document (no fabricated specifics).
"""
from __future__ import annotations

from .. import wcag

# sc_num -> remediation guidance (concise, actionable, standards-based).
_KB: dict[str, str] = {
    "1.1.1": "Provide a meaningful text alternative for every non-text element. "
             "Add descriptive alt text to informative images; use alt=\"\" for "
             "purely decorative images; give form image buttons and icon-only "
             "controls an accessible name.",
    "1.2.1": "Provide a text or audio-description alternative for pre-recorded "
             "audio-only and video-only media.",
    "1.2.2": "Add synchronized captions to all pre-recorded audio in video via a "
             "<track kind=\"captions\"> or an equivalent captioning mechanism.",
    "1.3.1": "Convey structure programmatically: use real headings (h1–h6), lists, "
             "and table markup with <th> + scope/headers so relationships are "
             "exposed to assistive technology, not just visual styling.",
    "1.3.5": "Add correct autocomplete attributes to inputs that collect the "
             "user's own information (e.g. autocomplete=\"email\", \"name\").",
    "1.4.1": "Do not rely on color alone to convey information (e.g. error state, "
             "required fields, links in body text) — add text, icons, or "
             "underlines as a second cue.",
    "1.4.2": "Give the user a way to pause, stop, or mute any audio that plays "
             "automatically for more than 3 seconds.",
    "1.4.3": "Increase text/background contrast to at least 4.5:1 (3:1 for large "
             "text ≥18pt or 14pt bold). Adjust the foreground or background color "
             "to meet the ratio reported in the evidence.",
    "1.4.4": "Do not disable zoom. Remove user-scalable=no and maximum-scale from "
             "the viewport meta so text can be resized up to 200% without loss.",
    "1.4.6": "For AAA, raise text/background contrast to at least 7:1 (4.5:1 for "
             "large text).",
    "1.4.11": "Ensure UI components and meaningful graphics have at least 3:1 "
              "contrast against adjacent colors.",
    "1.4.12": "Ensure content still works when users override text spacing "
              "(line-height 1.5, paragraph 2×, letter 0.12em, word 0.16em) — avoid "
              "fixed heights that clip text.",
    "2.1.1": "Make all functionality operable by keyboard. Ensure custom controls "
             "are focusable and respond to Enter/Space; don't trap focus.",
    "2.2.2": "Provide a mechanism to pause, stop, or hide moving, blinking, or "
             "auto-updating content that starts automatically and lasts >5s.",
    "2.4.1": "Provide a skip-to-content link and/or ARIA landmarks so keyboard and "
             "screen-reader users can bypass repeated blocks.",
    "2.4.2": "Give every page a unique, descriptive <title> that identifies its "
             "topic or purpose.",
    "2.4.3": "Ensure focus order follows a logical, meaningful sequence; avoid "
             "positive tabindex values.",
    "2.4.4": "Make link text describe its destination in context; replace generic "
             "text like \"click here\" / \"read more\" or add an accessible name.",
    "2.5.8": "Ensure interactive targets are at least 24×24 CSS px (44×44 for AAA), "
             "or provide sufficient spacing between smaller targets.",
    "3.1.1": "Set the page's primary language with a valid <html lang=\"…\"> value.",
    "3.1.2": "Mark up passages in a different language with a lang attribute on the "
             "containing element.",
    "3.3.2": "Provide visible labels or instructions for every form control; "
             "associate them programmatically with <label for> or aria-label.",
    "4.1.1": "(Obsolete in WCAG 2.2.) For 2.0/2.1: ensure elements have complete "
             "start/end tags and unique IDs.",
    "4.1.2": "Give every UI component a correct name, role, and value: use native "
             "elements or correct ARIA roles/states, and ensure custom widgets "
             "expose their accessible name and state.",
    "4.1.3": "Expose important status messages to assistive technology using "
             "aria-live regions or appropriate roles (status/alert).",
}


def get(sc_num: str, rule_id: str = "", description: str = "") -> str:
    if sc_num in _KB:
        return _KB[sc_num]
    try:
        crit = wcag.criterion(sc_num)
        return (f"Remediate per WCAG {sc_num} ({crit['name']}). "
                f"See W3C Understanding: {crit['understanding_url']}")
    except StopIteration:
        return "Review the flagged element against the applicable WCAG criterion."
