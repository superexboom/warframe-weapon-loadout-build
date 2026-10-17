"""2026-10-17: the Riven analysis screens the Incarnon route of the submitted card's build.

The default route is picked before the analysis sees the Riven (community policy, or tier
by tier on the bare weapon). Laetum's default Evo V is Overwhelming Attrition (5-3, additive
base damage that wants crits to leave some hits uncritical); with a negative Critical Chance
Riven, Devouring Attrition (5-1, a separate non-critical multiplier) wins and the build drops
its crit MODs.
"""
from __future__ import annotations

import pytest

import app
from wfarsenal import optimizer as o

LAETUM = "/Lotus/Weapons/Tenno/Zariman/Pistols/HeavyPistol/ZarimanHeavyPistol"


def _weapon(path):
    return next(w for w in app.EXPORTS["weapons"] if w.get("path") == path)


def test_neutral_branches_are_not_screened():
    assert o._route_neutral_branch({"effects": [{"upgradeType": "WEAPON_RECOIL", "operation": "STACKING_MULTIPLY",
                                                  "valuePerRank": -0.4, "damageType": "DT_ANY"}]})
    assert o._route_neutral_branch({"effects": [{"upgradeType": "AVATAR_MOVEMENT_SPEED", "operation": "STACKING_MULTIPLY",
                                                  "valuePerRank": 0.5, "damageType": "DT_ANY"}]})
    assert not o._route_neutral_branch({"effects": [{"upgradeType": "WEAPON_FIRE_RATE", "operation": "STACKING_MULTIPLY",
                                                      "valuePerRank": 0.2, "damageType": "DT_ANY"}]})
    # A conditional source is replayed as an event: never pruned unseen.
    assert not o._route_neutral_branch({"effects": [{"upgradeType": "NONE", "operation": "ADD", "valuePerRank": 0}],
                                        "sources": [{"conditionalEffects": [{"effects": []}]}]})


def test_laetum_route_options_keep_score_relevant_branches():
    route = {"tier2": "2-2", "tier3": "3-1", "tier4": "4-1", "tier5": "5-3"}
    options = dict(o._route_options(_weapon(LAETUM), route))
    # Evo II: recoil and aim-movement cannot change a score; fire rate stays alone.
    assert "tier2" not in options
    assert options["tier5"][0] == "5-3" and set(options["tier5"]) == {"5-1", "5-2", "5-3"}
    assert options["tier4"][0] == "4-1" and "4-3" in options["tier4"] and "4-2" not in options["tier4"]


@pytest.fixture
def isolated_analysis(monkeypatch):
    monkeypatch.setattr(app, "_ANALYSIS_RESULTS", type(app._ANALYSIS_RESULTS)())
    monkeypatch.setattr(app, "_persist_analysis_statics_cache", lambda: None)


def _laetum_payload(**extra):
    weapon = app.CATALOG_WEAPONS_BY_PATH[LAETUM]
    bases = app.RIVEN_BASE_VALUES[o._riven_type(None, weapon)]

    def high(code, negative):
        return round(o.riven_stat_window(bases[code], weapon["disposition"], 3, 1, negative=negative)[2], 1)
    stats = [dict(code="D", value=high("D", False), negative=False),
             dict(code="VI", value=high("VI", False), negative=False),
             dict(code="S", value=high("S", False), negative=False),
             dict(code="0", value=high("0", True), negative=True)]
    return dict(weapon=LAETUM, disposition=weapon["disposition"], stats=stats, profile="fast", headshotChance=1.0, **extra)


def test_negative_crit_riven_moves_laetum_to_devouring_attrition(isolated_analysis):
    result = app.analyze_payload(_laetum_payload())
    screen = result["incarnonRouteScreen"]
    assert screen["defaultRoute"]["tier5"] == "5-3" and screen["adopted"]
    assert result["incarnonChoices"]["tier5"] == "5-1"
    assert result["actual"]["incarnonChoices"] == result["incarnonChoices"]
    # The no-Riven build is weaker on 5-1, so the gain keeps the default baseline.
    assert not screen["baselineRaised"] and result["baseline"]["incarnonChoices"]["tier5"] == "5-3"
    crit = next(row for row in result["details"] if row["code"] == "0")
    assert crit["delta"] > 0
    assert not {"Primed Pistol Gambit", "Primed Target Cracker"} & {m["nameEn"] for m in result["actual"]["mods"]}


def test_explicit_route_is_not_screened(isolated_analysis):
    route = {"tier2": "2-2", "tier3": "3-1", "tier4": "4-1", "tier5": "5-3"}
    result = app.analyze_payload(_laetum_payload(incarnonChoices=route))
    assert result["incarnonRouteScreen"] is None
    assert result["incarnonChoices"] == route and result["baselineIncarnonChoices"] == route
