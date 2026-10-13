"""Native sustained-status scores against the Python reference (2026-10-13).

``optimizer._score`` ranks the element-seed searches by
``sustained_status_damage(...)["totalDps" / "directDps"]``; wfcore computes
the two numbers in the reference's order. Every value must match to the bit
across armour, shields, Overguard (Eximus), faction, head hits, strips and
stance rates. The full check is ``tools/verify_apply_mods.py verify-status``.
"""
import pytest

import app
from wfarsenal import damage, status_native

pytestmark = pytest.mark.skipif(not status_native.ENABLED, reason="native core not built")

ENEMIES = app.EXPORTS["enemies"]


def _enemy(predicate):
    return next(e for e in ENEMIES if predicate(e))


TARGETS = [
    (next(e for e in ENEMIES if e.get("path") == app._BENCHMARK_ENEMY_PATH), dict(level=170, steel_path=True)),
    (_enemy(lambda e: e.get("armour") and not e.get("shield") and e.get("factionResistance") == "RK_GRINEER_FACTION"),
     dict(level=100, armour_strip=0.5, elemental_armour_strip=0.3, hit_location="head")),
    (_enemy(lambda e: e.get("shield") and not e.get("armour")),
     dict(level=150, enemy_enhancements={"eximus": True, "magneticStacks": 3})),
    (_enemy(lambda e: e.get("shield") and e.get("armour")), dict(level=60)),
]


@pytest.mark.parametrize("name,mods", [
    ("Hek", ["Point Blank", "Hell's Chamber", "Shotgun Spazz", "Toxic Barrage", "Charged Shell"]),
    ("Lex Prime", ["Hornet Strike", "Barrel Diffusion", "Lethal Torrent", "Hollow Point", "Pistol Pestilence"]),
    ("Nikana Prime", ["Primed Pressure Point", "Blood Rush", "Weeping Wounds", "Condition Overload", "Fever Strike"]),
    ("Ignis Wraith", ["Serration", "Split Chamber", "Hellfire", "Infected Clip", "Hammer Shot"]),
])
def test_scores_match_the_reference(name, mods):
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    records = {row.get("nameEn"): row for row in app.EXPORTS["mods"]}
    effects = damage.ModEffectList()
    for mod in mods:
        if mod in records:
            effects.extend(damage.mod_effects(records[mod]))
    stats = damage.apply_mods(weapon, effects)
    for target, kwargs in TARGETS:
        for srm, drm in ((1.0, 1.0), (0.75, 1.3)):
            reference = damage.sustained_status_damage(
                stats, target, attacks_per_second=stats.sustained_attack_rate, status_rate_multiplier=srm,
                damage_rate_multiplier=drm, **kwargs)
            for total, field in ((True, "totalDps"), (False, "directDps")):
                value = status_native.score(stats, target, kwargs, status_rate_multiplier=srm,
                                            damage_rate_multiplier=drm, total=total)
                assert value.hex() == float(reference[field]).hex(), (name, target.get("nameEn"), kwargs, field)


def test_a_target_changed_in_place_is_not_served_from_the_cache():
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Hek")
    stats = damage.apply_mods(weapon, [])
    target = dict(_enemy(lambda e: e.get("armour") and not e.get("shield")))
    first = status_native.score(stats, target, dict(level=100), status_rate_multiplier=1.0,
                                damage_rate_multiplier=1.0, total=True)
    target["armour"] = float(target["armour"]) * 4
    second = status_native.score(stats, target, dict(level=100), status_rate_multiplier=1.0,
                                 damage_rate_multiplier=1.0, total=True)
    reference = damage.sustained_status_damage(stats, target, attacks_per_second=stats.sustained_attack_rate,
                                               level=100)["totalDps"]
    assert second != first and second.hex() == float(reference).hex()
