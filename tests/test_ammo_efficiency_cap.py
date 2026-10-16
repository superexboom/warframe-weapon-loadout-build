"""Ammo Efficiency is capped at 75% (2026-10-16 hotfix; Bot maintainer patch 5fa4ba89).

After every source, Primary Compression included, a trigger costs at least a
quarter of its native ammo, so reloads stay. Infinite-ammo states and the
selected Incarnon pool are separate mechanics. Each case runs on the native
core and on the Python reference.
"""
import pytest

from wfarsenal import damage, mods_native
from wfarsenal.combat_replay import replay
from wfarsenal.damage import ModEffect, Scenario, apply_mods


def weapon(ammo_cost=1):
    return {
        "name": "Ammo efficiency regression", "slot": "primary", "magazineSize": 10,
        "fireModes": [{"fireRate": 10, "ammoCost": ammo_cost, "reloadTime": 2,
                       "damage": {"types": {"DT_IMPACT": 100}, "critChance": 0,
                                  "critMultiplier": 2, "procChance": 0}}],
    }


def efficiency(value):
    return ModEffect("WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", -value)


@pytest.fixture(params=["native", "reference"])
def engine(request, monkeypatch):
    if request.param == "native" and not mods_native.ENABLED:
        pytest.skip("native core not built")
    if request.param == "reference":
        monkeypatch.setattr(mods_native, "ENABLED", False)
    return request.param


@pytest.mark.parametrize("cost", (1, 2, 10))
def test_cap_and_lower_values_scale_with_native_ammo_cost(engine, cost):
    for bonus, expected in ((0, cost), (.5, cost / 2), (.75, cost / 4), (.9, cost / 4), (1, cost / 4), (1.25, cost / 4)):
        assert apply_mods(weapon(cost), [efficiency(bonus)]).ammo_cost == pytest.approx(expected)
    assert apply_mods(weapon(cost), [efficiency(-.5)]).ammo_cost == cost * 1.5


def test_cap_applies_after_multiple_sources(engine):
    assert apply_mods(weapon(), [efficiency(.5), efficiency(.5)]).ammo_cost == .25


def test_cap_includes_primary_compression(engine):
    gun = weapon()
    gun["__compressionProfile__"] = {"radius": 10}
    compression = ModEffect("RUNTIME_PRIMARY_COMPRESSION", "ADD", 0, runtime_chance=.1)
    for effects in ([compression], [efficiency(.5), compression]):
        assert apply_mods(gun, effects, scenario=Scenario(aiming=True)).ammo_cost == .25
    assert apply_mods(gun, [compression], scenario=Scenario(aiming=False)).ammo_cost == 1


def test_native_and_reference_agree_bit_for_bit():
    if not mods_native.ENABLED:
        pytest.skip("native core not built")
    for cost in (1, 2, 3, 10):
        for bonus in (0, .3, .74, .75, .76, .9, 1, 1.25, -.5):
            native = damage.apply_mods_spec(weapon(cost), [efficiency(bonus)])[0].ammo_cost
            reference = damage._apply_mods_spec_py(weapon(cost), [efficiency(bonus)])[0].ammo_cost
            assert native.hex() == reference.hex(), (cost, bonus)


def test_efficiency_retains_reload_downtime_without_changing_burst_damage(engine):
    baseline = apply_mods(weapon(), [])
    for bonus in (.75, 1, 1.25):
        stats = apply_mods(weapon(), [efficiency(bonus)])
        # 40 shots at 10/s, then a 2 s reload: 4000 damage per 6 s.
        assert stats.sustained_dps == pytest.approx(4000 / 6)
        assert stats.sustained_attack_rate == pytest.approx(40 / 6)
        assert stats.burst_dps == baseline.burst_dps


def test_replay_reloads_at_the_cap_and_keeps_infinite_ammo_separate(engine):
    stats = apply_mods(weapon(), [efficiency(1)])
    ordinary = replay(stats, {"health": 1e9}, attacks_per_second=10, window_seconds=5,
                      combat={"weaponSlot": "primary"})
    infinite = replay(stats, {"health": 1e9}, attacks_per_second=10, window_seconds=5,
                      combat={"weaponSlot": "primary", "infiniteAmmo": True})
    assert ordinary["reloads"] == 1
    assert infinite["reloads"] == 0
    assert ordinary["shots"] < infinite["shots"]


def test_selected_incarnon_pool_does_not_use_ordinary_efficiency(engine):
    results = [replay(apply_mods(weapon(), [efficiency(bonus)]), {"health": 1e9}, attacks_per_second=10,
                      window_seconds=5, combat={"selectedIncarnon": True}) for bonus in (0, .75, 1)]
    assert all(r["reloads"] == results[0]["reloads"] and r["shots"] == results[0]["shots"] for r in results)
