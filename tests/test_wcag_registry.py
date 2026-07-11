"""Registry integrity: scope counts must match published WCAG totals."""
from backend.app import wcag

EXPECTED = {
    ("2.0", "A"): 25, ("2.0", "AA"): 38, ("2.0", "AAA"): 61,
    ("2.1", "A"): 30, ("2.1", "AA"): 50, ("2.1", "AAA"): 78,
    ("2.2", "A"): 32, ("2.2", "AA"): 56, ("2.2", "AAA"): 87,
}


def test_scope_counts_match_published_wcag():
    for (ver, lvl), expected in EXPECTED.items():
        assert len(wcag.criteria_in_scope(ver, lvl)) == expected, f"{ver}/{lvl}"


def test_total_registry_is_87():
    assert len(wcag.registry()["criteria"]) == 87


def test_411_obsolete_in_22_only():
    c = wcag.criterion("4.1.1")
    assert wcag.is_obsolete(c, "2.2") is True
    assert wcag.is_obsolete(c, "2.0") is False


def test_active_22_excludes_obsolete():
    s = wcag.scope_summary("2.2", "AAA")
    assert s["total_in_scope"] == 87
    assert s["active_in_scope"] == 86
    assert s["obsolete_count"] == 1


def test_testability_distribution():
    dist = {"auto": 0, "semi": 0, "manual": 0}
    for c in wcag.registry()["criteria"]:
        dist[c["testability"]] += 1
    assert dist == {"auto": 8, "semi": 33, "manual": 46}
