"""Run Apple's XCUITest accessibility audit via Appium (iOS 17+/Xcode 15+).

`mobile: performAccessibilityAudit` wraps XCTest's
`XCUIApplication.performAccessibilityAudit(for:)`. It returns a list of issues,
each with a detailed + compact description and the audit type. We request all 7
documented audit types.
"""
from __future__ import annotations

AUDIT_TYPES = [
    "XCUIAccessibilityAuditTypeContrast",
    "XCUIAccessibilityAuditTypeElementDetection",
    "XCUIAccessibilityAuditTypeHitRegion",
    "XCUIAccessibilityAuditTypeSufficientElementDescription",
    "XCUIAccessibilityAuditTypeDynamicType",
    "XCUIAccessibilityAuditTypeTextClipped",
    "XCUIAccessibilityAuditTypeTrait",
]


def run_for_current(driver, audit_types: list[str] | None = None) -> dict:
    """Returns {'status': 'clean'|'violations'|'error', 'issues': [...], 'error': str|None}."""
    try:
        result = driver.execute_script(
            "mobile: performAccessibilityAudit",
            {"auditTypes": audit_types or AUDIT_TYPES},
        )
        issues = result if isinstance(result, list) else (result or {}).get("issues", [])
        return {"status": "violations" if issues else "clean",
                "issues": issues or [], "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "issues": [], "error": str(exc)[:400]}
