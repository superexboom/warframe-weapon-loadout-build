"""Features moved into the native replay (2026-10-13) match the reference.

Shadow mode runs the native replay and the Python reference side by side and
raises ShadowMismatch on the first differing field. Skipped when the native
library is not built (tools/build_native.py).
"""
from copy import deepcopy

import pytest

import app
from wfarsenal.combat_replay import replay
from wfarsenal.damage import ModEffect, Scenario, mod_effects
from wfarsenal.manual_combat import prepare
from tests.test_combat_replay import target

pytest.importorskip("wfarsenal.wfcore")
from wfarsenal import native_replay  # noqa: E402


@pytest.fixture
def shadow(monkeypatch):
    monkeypatch.setattr(native_replay, "SHADOW", True)
    native_replay.STATS.update(native=0, fallback=0)
    yield native_replay.STATS


def _double_tap():
    return next(m for m in app.EXPORTS["mods"] if m["nameEn"] == "Double Tap")


@pytest.mark.parametrize("mode", [0, 1])
def test_double_tap(shadow, mode):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == "Latron Prime"))
    weapon["isIncarnonForm"] = bool(mode)
    effects = [*mod_effects(_double_tap(), 3), ModEffect("WEAPON_FIRE_ITERATIONS", "SET", 3.)]
    combat = prepare(dict(weapon=weapon, fire_mode=mode, scenario=Scenario(), effects=effects),
                     [(_double_tap(), 3, None)], [])
    stats, _ = combat["resolve"]("selected", {}, 0)
    result = replay(stats, target(1e6), attacks_per_second=stats.fire_rate, window_seconds=8.,
                    combat=combat, collect_timeline=False)
    assert result["doubleTap"]["maximum"] == 20
    assert shadow["native"] == 1


ARCANES = {
    "fortifier": "/Lotus/Upgrades/CosmeticEnhancers/Offensive/OverguardSteal",
    "empowered": "/Lotus/Upgrades/CosmeticEnhancers/Zariman/SecondaryOnStatusProcBonusDamage",
    "cryogenic": "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryColdOnPuncture",
    "encumber": "/Lotus/Upgrades/CosmeticEnhancers/Utility/ExtraProcOnProc",
    "enervate": "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryCritOnHit",
}


@pytest.mark.parametrize("kind", sorted(ARCANES))
def test_status_arcanes(shadow, kind):
    record = next(a for a in app.EXPORTS["arcanes"] if a.get("path") == ARCANES[kind])
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == "Lato"))
    effects = [ModEffect("WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", 1.2),
               ModEffect("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", 2.0),
               ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", 0.9, damage_type="DT_POISON")]
    combat = prepare(dict(weapon=weapon, fire_mode=0, scenario=Scenario(), effects=effects), [], [(record, 5, None)])
    assert combat.get(kind)
    stats, _ = combat["resolve"]("selected", {}, 0)
    enemy = target(5e4)
    if kind == "fortifier":
        enemy["overguard"] = 2e4
    replay(stats, enemy, attacks_per_second=stats.fire_rate, window_seconds=12., combat=combat,
           trigger_sources=combat["trigger_sources"], headshot_chance=0.3, collect_timeline=False)
    assert shadow["native"] == 1


@pytest.mark.parametrize("ms", [1, 2.5])
def test_torid_field_duration_on_empty_reload(shadow, ms):
    from tests.test_torid_reload_fields import combat as torid_combat, simple_combat
    c, st = simple_combat(ms=ms)
    result = replay(st, target(), combat=c, attacks_per_second=1, window_seconds=12.9, collect_timeline=False)
    assert result["fieldDuration"]["boostedShots"] >= 1
    full = torid_combat()
    assert full.get("fieldDurationOnEmptyReload")
    stats, _ = full["resolve"]("selected", {}, 0)
    replay(stats, target(1e7), attacks_per_second=stats.fire_rate, window_seconds=20., combat=full,
           trigger_sources=full["trigger_sources"], collect_timeline=False)
    assert shadow["native"] == 2


@pytest.mark.parametrize("name", ["Braton", "Burston", "Strun", "Furis"])
def test_incarnon_cycle(shadow, name):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == name))
    weapon["isIncarnonForm"] = True
    combat = prepare(dict(weapon=weapon, fire_mode=1, effects=[], scenario=Scenario(incarnon_cycle=True)),
                     [], [], cycle_enabled=True)
    assert combat.get("cycle")
    stats, _ = combat["resolve"]("base", {}, 0)
    result = replay(stats, target(1e7), attacks_per_second=stats.fire_rate, window_seconds=40., combat=combat,
                    trigger_sources=combat["trigger_sources"], headshot_chance=0.5, collect_timeline=False)
    assert result["transforms"] >= 1
    assert shadow["native"] == 1


@pytest.mark.parametrize("name", ["Trumna", "Mausolon"])
def test_kill_charged_alternate(shadow, name):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == name))
    combat = prepare(dict(weapon=weapon, fire_mode=1, effects=[], scenario=Scenario()), [], [])
    assert combat["cycle"]["chargeOn"] == "kills"
    stats, _ = combat["resolve"]("base", {}, 0)
    result = replay(stats, target(300.0), attacks_per_second=stats.fire_rate, window_seconds=30., combat=combat,
                    trigger_sources=combat["trigger_sources"], collect_timeline=False)
    assert result["transforms"] >= 1
    assert shadow["native"] == 1


@pytest.mark.parametrize("name,mode", [("Talons", 0), ("Aegrit", 0), ("Alternox", 1)])
def test_manual_detonation(shadow, name, mode):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == name))
    combat = prepare(dict(weapon=weapon, fire_mode=mode, effects=[], scenario=Scenario()), [], [])
    assert combat.get("manualDetonation")
    stats, _ = combat["resolve"]("selected", {}, 0)
    result = replay(stats, target(2e4), attacks_per_second=stats.fire_rate, window_seconds=30., combat=combat,
                    trigger_sources=combat["trigger_sources"], collect_timeline=False)
    assert result["manualDetonation"]["detonations"] >= 1
    assert shadow["native"] == 1


@pytest.mark.parametrize("name,mode,state", [
    ("Simulor", 0, {}),
    ("Simulor", 0, {"projectileMode": "manual", "detonateAfterShots": 3, "detonationWaitSeconds": 0.5}),
    ("Simulor", 0, {"projectileMode": "isolated"}),
    ("Stug", 0, {"stugChildHits": 2, "stugBounceHits": 1, "stugBounceDelaySeconds": 0.3}),
    ("Stug", 1, {"stugChildHits": 3}),
    ("Stug", 2, {"stugChildHits": 2, "stugBounceHits": 2, "stugBounceDelaySeconds": 0.3}),
    ("Stug", 2, {"stugChildHits": 5, "stugChildDetonateSeconds": 1.5}),
    ("Mutalist Quanta", 1, {}),
])
def test_stackable_projectiles(shadow, name, mode, state):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == name))
    combat = prepare(dict(weapon=weapon, fire_mode=mode, effects=[], scenario=Scenario(combat_state=state)), [], [])
    stats, _ = combat["resolve"]("selected", {}, 0)
    assert getattr(stats, "_stackable", None)
    result = replay(stats, target(5e4), attacks_per_second=stats.fire_rate, window_seconds=20., combat=combat,
                    trigger_sources=combat["trigger_sources"], collect_timeline=False)
    assert result["projectileLifecycle"]["deployed"] > 0
    assert shadow["native"] == 1


@pytest.mark.parametrize("mode,incarnon,crits,cycle", [
    (1, False, False, False), (1, True, False, False), (2, True, True, False), (1, True, True, True),
])
def test_onos(shadow, mode, incarnon, crits, cycle):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == "Onos"))
    weapon["isIncarnonForm"] = incarnon
    combat = prepare(dict(weapon=weapon, fire_mode=mode, effects=[], scenario=Scenario(incarnon_cycle=cycle)),
                     [], [], cycle_enabled=cycle)
    assert combat.get("onosCharge")
    if crits:
        combat["onosCrits"] = {"perHit": .05, "maximum": 50}  # the replay's crit-stack clock
    stats, _ = combat["resolve"]("base" if combat.get("cycle") else "selected", {}, 0)
    result = replay(stats, target(1e5), attacks_per_second=stats.fire_rate, window_seconds=25., combat=combat,
                    trigger_sources=combat["trigger_sources"], collect_timeline=False)
    assert result["onosSequence"]["alignmentShots"]
    assert shadow["native"] == 1


def test_life_curve(shadow):
    weapon = deepcopy(next(w for w in app.EXPORTS["weapons"] if w["nameEn"] == "Hek"))
    combat = prepare(dict(weapon=weapon, fire_mode=0, effects=[], scenario=Scenario()), [], [])
    stats, _ = combat["resolve"]("selected", {}, 0)
    curve = []
    replay(stats, target(1e9), attacks_per_second=stats.fire_rate, window_seconds=12., combat=combat,
           trigger_sources=combat["trigger_sources"], collect_timeline=False, life_curve=curve)
    assert curve and {row[3] for row in curve} >= {"direct"}
    assert shadow["native"] == 1
