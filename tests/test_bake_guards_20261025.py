"""2026-10-25 (before the Bot rebake): part records keep their prep, runaway replays stop."""
from __future__ import annotations

import pytest

import app
from wfarsenal import optimizer as o


def _weapon(path):
    record = o.resolve_record(app.EXPORTS["weapons"], path, kind="weapon")
    return o._select_fire_mode(record, 0, weapon_type=o._weapon_type(None, record))[0]


def _combat(weapon):
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    return prepare(dict(weapon=weapon, fire_mode=0, effects=[], scenario=Scenario(trigger_policy="emergent")), [], [])


def test_a_part_record_is_built_once_and_keeps_its_prep(monkeypatch):
    # Kuva Zarr's cluster bomblets: rebuilt on every resolve, each part record
    # was a new weapon to mods_native's prep cache (99% misses on Braton Prime).
    from wfarsenal import mods_native
    if not mods_native.ENABLED:
        pytest.skip("native core not built")
    weapon = _weapon("/Lotus/Weapons/Grineer/KuvaLich/LongGuns/Zarr/KuvaZarr")
    first, first_radial = _combat(weapon)["resolve"]("selected", {})
    assert first_radial is not None and first_radial._additional_radials
    built = []
    build = mods_native._build
    monkeypatch.setattr(mods_native, "_build", lambda *args: built.append(args[1]) or build(*args))
    again, again_radial = _combat(weapon)["resolve"]("selected", {})
    assert built == []
    parts = [first_radial, *first_radial._additional_radials]
    for a, b in zip(parts, [again_radial, *again_radial._additional_radials]):
        assert (a.damage_types, a.crit_chance, a.status_chance) == (b.damage_types, b.crit_chance, b.status_chance)


def _replay(weapon):
    from wfarsenal.combat_replay import replay
    combat = _combat(weapon)
    stats, _ = combat["resolve"]("selected", {})
    target = dict(health=1e12, shield=0, armour=0, overguard=0, baseLevel=1, faction="")
    return replay(stats, target, attacks_per_second=stats.sustained_attack_rate, window_seconds=30, combat=combat,
                  collect_timeline=False)


def test_a_replay_past_the_event_limit_is_an_error(monkeypatch):
    from wfarsenal import combat_replay, native_replay
    from wfarsenal.simulator import SimulationError
    monkeypatch.setattr(native_replay, "ENABLED", False)
    monkeypatch.setattr(combat_replay, "REPLAY_EVENT_LIMIT", 50)
    with pytest.raises(SimulationError, match="exceeded 50 events"):
        _replay(_weapon("/Lotus/Weapons/Tenno/Rifle/BratonPrime"))


def test_the_native_event_limit_is_an_error_not_a_reference_fallback(monkeypatch):
    from wfarsenal import native_replay
    from wfarsenal.simulator import SimulationError
    if not native_replay.ENABLED:
        pytest.skip("native core not built")
    wfcore = native_replay.wfcore
    assert issubclass(wfcore.ReplayRunaway, Exception)

    def runaway(config, helper):
        raise wfcore.ReplayRunaway("replay exceeded 10000000 events")

    monkeypatch.setattr(wfcore, "trajectory", runaway)
    fallback = native_replay.STATS["fallback"]
    with pytest.raises(SimulationError, match="exceeded 10000000 events"):
        _replay(_weapon("/Lotus/Weapons/Tenno/Rifle/BratonPrime"))
    assert native_replay.STATS["fallback"] == fallback
