"""Companion actor rules must survive every request shape and input boundary."""
from copy import deepcopy
import pytest
import app
from wfarsenal import companion, manual_combat
from wfarsenal.simulator import SimulationError


def test_companion_target_cannot_reenable_headshots_and_inputs_stay_immutable():
    payload = dict(headshotChance=1., hitLocation="head", aiming=True,
                   benchmarkTarget=dict(enemy="/target", headshotChance=1., hitLocation="head"),
                   scenario=dict(aiming=True, combatState={}), weaponArcane="/arcane", autoArcane=True)
    original = deepcopy(payload)
    result = companion.companion_payload(payload, dict(slot="companion"))
    assert result["headshotChance"] == 0. and result["hitLocation"] == "body"
    assert result["benchmarkTarget"] == dict(enemy="/target", headshotChance=0., hitLocation="body")
    assert not result["aiming"] and not result["scenario"]["aiming"]
    assert "weaponArcane" not in result and "autoArcane" not in result
    assert payload == original


def test_nested_state_wins_and_companion_player_switch_survives_serialization():
    result = companion.companion_payload(dict(combatState=dict(energyPool=500.),
        scenario=dict(combatState=dict(companionPlayerStacks=True))), dict(slot="companion"))
    state = app.optimizer._requested_scenario(result, "killsPerMinute").combat_state
    assert state == dict(companion=True, companionPlayerStacks=True)
    assert companion.player_stacks(app.optimizer._requested_scenario(result, "killsPerMinute")) is True


@pytest.mark.parametrize("payload", [dict(scenario=3), dict(combatState=[]),
    dict(scenario=dict(combatState=False)), dict(companionPlayerStacks="false")])
def test_invalid_companion_context_is_a_public_validation_error(payload):
    with pytest.raises(SimulationError):companion.companion_payload(payload, dict(slot="companion"))


def test_player_kill_galvanized_stacks_are_not_generated_by_companion_kills():
    raw = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Deth Machine Rifle")
    weapon = app.optimizer._select_fire_mode(raw, 0, weapon_type="rifle")[0]
    chamber = next(m for m in app.EXPORTS["mods"] if m.get("nameEn") == "Galvanized Chamber")
    for enabled in (False, True):
        payload = companion.companion_payload(dict(companionPlayerStacks=enabled), raw)
        scenario = app.optimizer._requested_scenario(payload, "killsPerMinute")
        combat = manual_combat.prepare(dict(weapon=weapon, scenario=scenario, fire_mode=0, effects=[]),
                                       [(chamber, chamber["maxRank"], 0)], [])
        sources = combat["trigger_sources"]
        if enabled:
            assert len(sources) == 1 and sources[0]["initialStacks"] == 5.
            assert sources[0]["perEvent"] == 0. and sources[0]["simulationMode"] == "fixed"
        else:
            assert sources == []


def test_non_companion_request_is_not_rewritten():
    payload = dict(headshotChance=1., aiming=True, weaponArcane="/arcane")
    assert companion.companion_payload(payload, dict(slot="primary")) is payload



def _fired_up_combat(name, *, enabled=True, assumed=False, extra=()):
    from wfarsenal import sentinel
    raw = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    body = dict(path="/Lotus/Types/Sentinels/SentinelPowersuits/DethCubePowerSuit", mods=[
        dict(path=sentinel.FIRED_UP, rank=5),
        dict(path="/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack", rank=5)],
        options=dict(firedUp=enabled))
    effects, _ = sentinel.weapon_effects(body, raw)
    effects.extend(extra)
    scenario = app.optimizer._requested_scenario(dict(combatState=dict(companion=True),
        triggerPolicy="assumed_max" if assumed else "emergent"), "killsPerMinute")
    stats = app.optimizer.apply_mods(raw, effects, scenario=scenario)
    engine = dict(weapon=raw, scenario=scenario, fire_mode=0, effects=effects)
    combat = manual_combat.prepare(engine, [], [], assumed=assumed)
    return stats, combat


def _replay_fired(name, *, native, window=8., enabled=True, assumed=False, extra=()):
    from wfarsenal import native_replay, combat_replay
    stats, combat = _fired_up_combat(name, enabled=enabled, assumed=assumed, extra=extra)
    target = dict(health=1e12, shield=0., armour=0., baseLevel=1)
    options = dict(attacks_per_second=stats.sustained_attack_rate, window_seconds=window,
                   level=1, combat=combat, trigger_sources=combat["trigger_sources"], collect_timeline=True)
    if native:
        return native_replay.trajectory(stats, target, **options)
    return combat_replay._reference_trajectory(stats, target, **options)


def test_fired_up_first_hit_is_cold_and_hits_refresh_to_script_cap():
    stats, combat = _fired_up_combat("Deth Machine Rifle")
    source = combat["trigger_sources"][0]
    key = source["id"]
    assert source["initialStacks"] == 0.
    assert "sentinel-fired-up-expiry-resume-unverified" in combat["unsupported"]
    empty, _ = combat["resolve"]("selected", {})
    first, _ = combat["resolve"]("selected", {key:source["perEvent"]})
    full, _ = combat["resolve"]("selected", {key:source["maxStacks"]})
    assert not empty.damage_types.get("DT_FIRE", 0.)
    assert first.damage_types["DT_FIRE"] == pytest.approx(15. * .0083999997 * 6)
    assert full.damage_types["DT_FIRE"] == pytest.approx(15. * .168 * 6)
    result = _replay_fired("Deth Machine Rifle", native=False)
    assert result["timeline"][0]["triggerStacks"][key] < source["maxStacks"]
    assert result["timeline"][-1]["triggerStacks"][key] == source["maxStacks"]


def test_slow_vulklok_loses_fired_up_before_each_next_hit():
    actual = _replay_fired("Vulklok", native=False)
    bare = _replay_fired("Vulklok", native=False, enabled=False)
    key = next(iter(actual["timeline"][0]["triggerStacks"]))
    assert max(row["triggerStacks"][key] for row in actual["timeline"]) == pytest.approx(.0083999997 * 6)
    assert any(row["triggerStacks"][key] == 0. for row in actual["timeline"] if 5.1 < row["time"] < 6.6)
    assert actual["totalWindowDamage"] == bare["totalWindowDamage"]
    assert _replay_fired("Vulklok", native=False, assumed=True)["totalWindowDamage"] != bare["totalWindowDamage"]


@pytest.mark.parametrize("name", ["Vulklok", "Deth Machine Rifle", "Stinger"])
def test_fired_up_native_reference_parity(name):
    from wfarsenal import native_replay
    if not native_replay.ENABLED:pytest.skip("native core unavailable")
    actual = _replay_fired(name, native=True)
    expected = _replay_fired(name, native=False)
    for key in ("killsPerMinute", "totalWindowDamage", "directWindow", "dotWindow", "shots", "reloads", "unsupported"):
        assert actual[key] == expected[key], (name, key)


@pytest.mark.parametrize("name,expected", [
    ("Cryotra", {"cryotra-field-host-death-and-spatial-persistence-unverified", "cryotra-field-overlap-unverified"}),
    ("Deconstructor", {"companion-projectile-damage-sequence-unmodeled"}),
    ("Deconstructor Prime", {"companion-projectile-damage-sequence-unmodeled"})])
def test_known_missing_companion_damage_is_visible_in_real_simulation(name, expected):
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    result = app.simulate_manual_payload(dict(weapon=weapon["path"], enemy=app._BENCHMARK_ENEMY_PATH,
                                               level=100, windowSeconds=3., mods=[]))
    assert expected <= set(result["benchmarkTimeline"]["unsupported"])
