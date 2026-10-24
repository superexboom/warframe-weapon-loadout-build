"""A melee status reads the modified base, melee damage mods included (2026-10-24).

The wiki's status formula and WFSim's ModifiedBase put Pressure Point-like
cards (and a melee Riven's damage) in the base a Slash / Heat / Toxin /
Electricity tick reads: Primed Pressure Point makes a bleed x2.65 there. The
2026-10-01 basis left the melee bracket out, so no melee DoT scaled with them.
Condition Overload stays out, as before.
"""
import pytest

import app
from wfarsenal.damage import Scenario, apply_mods, mod_effects

PRIMED_PRESSURE_POINT = "/Lotus/Upgrades/Mods/Melee/Expert/WeaponMeleeDamageModExpert"
CONDITION_OVERLOAD = "/Lotus/Upgrades/Mods/Melee/WeaponDamageIfVictimProcActive"
SERRATION = "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod"


def _weapon(name):
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)


def _effects(path):
    return list(mod_effects(next(m for m in app.EXPORTS["mods"] if m["path"] == path)))


def test_melee_damage_mods_reach_the_status_base():
    glaive = _weapon("Glaive Prime")
    bare = apply_mods(glaive, [], scenario=Scenario())
    ppp = apply_mods(glaive, _effects(PRIMED_PRESSURE_POINT), scenario=Scenario())
    assert sum(ppp.damage_types.values()) == pytest.approx(2.65 * sum(bare.damage_types.values()))
    assert ppp.dot_base_damage == pytest.approx(2.65 * bare.dot_base_damage)


def test_condition_overload_stays_out_of_the_status_base():
    glaive = _weapon("Glaive Prime")
    bare = apply_mods(glaive, [], scenario=Scenario(victim_status_count=3))
    co = apply_mods(glaive, _effects(CONDITION_OVERLOAD), scenario=Scenario(victim_status_count=3))
    assert sum(co.damage_types.values()) > 2.0 * sum(bare.damage_types.values())
    assert co.dot_base_damage == pytest.approx(bare.dot_base_damage)


def test_a_gun_keeps_its_status_base():
    rifle = _weapon("Braton Prime")
    bare = apply_mods(rifle, [], scenario=Scenario())
    serration = apply_mods(rifle, _effects(SERRATION), scenario=Scenario())
    assert serration.dot_base_damage == pytest.approx(2.65 * bare.dot_base_damage)
    # A melee card never reaches a gun's base.
    assert apply_mods(rifle, _effects(PRIMED_PRESSURE_POINT), scenario=Scenario()).dot_base_damage == pytest.approx(
        bare.dot_base_damage)


def test_a_bleed_scales_with_pressure_point_in_the_replay():
    # Glaive Prime's throw is mostly bleed: the whole window follows the card.
    glaive = _weapon("Glaive Prime")
    payload = dict(weapon=glaive["path"], arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                   headshotChance=0.0, triggerPolicy="emergent", combatState=dict(meleeRoute="glaive"))
    bare = app.simulate_manual_payload(dict(payload, mods=[]))["benchmarkTimeline"]["totalWindowDamage"]
    ppp = app.simulate_manual_payload(dict(payload, mods=[dict(path=PRIMED_PRESSURE_POINT, rank=10, slot=0)]))
    assert ppp["benchmarkTimeline"]["totalWindowDamage"] == pytest.approx(2.65 * bare, rel=0.01)
