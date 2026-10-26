"""Melee hit schedule (melee-mechanics.json, melee_sequence, replay).

- stance attacks match the wiki stance table (multiplier totals and hits);
- combo multiplier 1x below 20 hits, then +1x per 20 (12x at 220);
- animation time scales with attack speed, movement / wind-up does not;
- the replay counts the combo, so Blood Rush has value;
- slam and glaive routes, and the analysis cache key carries the route.
"""
import json

import pytest

import app
from wfarsenal import melee_sequence as ms
from wfarsenal import optimizer
from tools.check_melee_stances import compare

MODS = json.loads((app.ROOT / "data/export/2026.08.13.13.24/mods.json").read_text(encoding="utf-8"))["data"]


def _weapon(name):
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)


def _mod(name):
    return next(m["path"] for m in MODS if m.get("nameEn") == name and m.get("selectable")
                and ("/Melee/" in m["path"] or "/Sets/" in m["path"]))


def _kpm(name, mods, **extra):
    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == name)
    payload = dict(weapon=weapon["path"], mods=[dict(path=_mod(m), slot=i) for i, m in enumerate(mods)],
                   enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True, headshotChance=0.5, **extra)
    return app.simulate_manual_payload(payload)["benchmarkTimeline"]


def test_stance_attacks_match_the_wiki_table():
    mechanics = ms.reference()
    stances = json.loads((app.ROOT / "data/stances.json").read_text(encoding="utf-8"))
    rows = [r for r in compare(mechanics, stances, app.EXPORTS["weapons"]) if r["status"] == "ok"]
    exact = [r for r in rows if abs(r["total"][0] - r["total"][1]) < 1e-6 and r["hits"][0] == r["hits"][1]]
    assert len(exact) / len(rows) >= 0.88
    neutral = next(r for r in rows if r["stance"] == "Decisive Judgement" and r["kind"] == "Neutral")
    assert neutral["total"] == (14.0, 14.0) and neutral["hits"] == (5, 5.0)


def test_combo_multiplier_tiers():
    spec = dict(baseHits=20, tierStep=20, cap=220, baseMultiplier=1)
    assert [ms.combo_multiplier(spec, n) for n in (0, 19, 20, 39, 40, 220, 400)] == [1, 1, 2, 2, 3, 12, 12]


def test_attack_speed_scales_animation_not_movement():
    schedule = ms.build_schedule(_weapon("Fragor Prime"), "slam")
    loop = ms.Loop(schedule)
    _, first = loop.next(1.0)
    loop = ms.Loop(schedule)
    _, fast = loop.next(2.0)
    assert first == pytest.approx(fast)  # the first hit waits only for the jump
    whole = sum(s["fixed"] + s["anim"] for s in schedule["segments"])
    doubled = sum(s["fixed"] + s["anim"] / 2.0 for s in schedule["segments"])
    assert doubled < whole


def test_default_routes_follow_the_bot_policy():
    assert ms.default_route(_weapon("Fragor Prime")) == "slamBullet"
    assert ms.default_route(_weapon("Glaive Prime")) == "glaive"
    assert ms.default_route(_weapon("Nikana Prime")) == "combo"
    glaive = ms.build_schedule(_weapon("Glaive Prime"))
    explosion = [s["hit"] for s in glaive["segments"] if s.get("hit")][-1]
    assert explosion["damageType"] == "DT_EXPLOSION" and explosion["comboMultiplier"]


def test_blood_rush_follows_the_live_combo_counter():
    build = ["Primed Reach", "Primed Fever Strike", "North Wind", "Condition Overload", "Primed Pressure Point", "Organ Shatter"]
    without = _kpm("Nikana Prime", build)
    with_rush = _kpm("Nikana Prime", [*build, "Blood Rush"])
    assert with_rush["melee"]["route"] == "combo"
    assert with_rush["killsPerMinute"] > without["killsPerMinute"] * 1.2


def test_heavy_slam_uses_the_initial_combo():
    build = ["Primed Reach", "Primed Fever Strike", "North Wind", "Primed Pressure Point"]
    plain = _kpm("Fragor Prime", build)
    charged = _kpm("Fragor Prime", [*build, "Corrupt Charge"])
    assert plain["melee"]["label"] == "heavy-slam"
    assert charged["killsPerMinute"] > plain["killsPerMinute"]


def test_melee_route_is_part_of_the_statics_cache_key():
    common = ("/w", (), 0, "viral", "fast", 1.0, 60, "killsPerMinute")
    slam = optimizer._statics_cache_key(*common, {"enemy": "/e", "melee": {"route": "slam"}})
    combo = optimizer._statics_cache_key(*common, {"enemy": "/e", "melee": {"route": "combo"}})
    assert slam != combo


def test_melee_incarnon_flat_base_damage_is_not_a_multiplier():
    from wfarsenal.damage import ModEffect, apply_mods
    weapon = _weapon("Magistar")
    flat = apply_mods(weapon, [ModEffect("WEAPON_MELEE_DAMAGE", "ADD_BASE", 100.0)])
    bare = apply_mods(weapon, [])
    assert sum(flat.damage_types.values()) == pytest.approx(sum(bare.damage_types.values()) + 100.0)


def test_homing_glaive_has_the_glaive_route():
    assert ms.default_route(_weapon("Orvius")) == "glaive"


@pytest.mark.parametrize("name,route,required", [
    ("Fragor Prime", None, False), ("Magistar", "combo", False),
    ("Glaive Prime", None, False), ("Nikana Prime", None, True),
])
def test_reach_reservation_excludes_hammers_and_glaive_throws(name, route, required):
    from wfarsenal.damage import Scenario
    scenario = Scenario(combat_state={"meleeRoute": route} if route else {})
    cards, _ = optimizer._candidate_mods(app.EXPORTS, _weapon(name), scenario)
    reserved = [c for c in cards if c.required and c.record.get("nameEn") == "Primed Reach"]
    assert bool(reserved) is required


def test_assembled_hammer_does_not_reserve_reach():
    from wfarsenal.damage import Scenario
    from wfarsenal.simulator import resolve_zaw_record
    zaw = app.EXPORTS["zaws"]
    parts = [next(path for path, row in zaw[table].items() if row["nameEn"] == name)
             for table, name in (("strikes", "Rabvee"), ("grips", "Shtung"), ("links", "Jai"))]
    base = next(w for w in app.EXPORTS["weapons"] if w["path"].endswith("/LotusModularWeapon"))
    weapon = resolve_zaw_record(base, parts, zaw)
    cards, _ = optimizer._candidate_mods(app.EXPORTS, weapon, Scenario())
    assert not any(c.required and c.record.get("nameEn") == "Primed Reach" for c in cards)
