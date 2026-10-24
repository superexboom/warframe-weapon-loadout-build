"""2026-10-21: companion weapons fire under AI control.

Their AI aims at the torso and never aims down sights, and Galvanized
conditions (DamageSources = TennoAvatar) only count the player's kills, so a
companion's Galvanized stacks are a switch: full (player kills with that
weapon class) or none. Robotic weapons cannot equip Arcanes.
"""
from __future__ import annotations

import app

DETH = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Deth Machine Rifle")
CHAMBER = next(m for m in app.MANUAL_MODS if m.get("nameEn") == "Galvanized Chamber")
ARGON = next(m for m in app.MANUAL_MODS if m.get("nameEn") == "Argon Scope")


def _sim(mods, **extra):
    payload = dict(weapon=DETH["path"], enemy=app._BENCHMARK_ENEMY_PATH, level=100, steelPath=False,
                   mods=[dict(path=m["path"], rank=m["maxRank"], slot=i) for i, m in enumerate(mods)], **extra)
    return app.simulate_manual_payload(payload)


def test_galvanized_stacks_follow_the_player_kill_switch():
    off = _sim([CHAMBER], triggerPolicy="assumed_max")
    on = _sim([CHAMBER], triggerPolicy="assumed_max", companionPlayerStacks=True)
    # +80% permanent; five kill stacks of +30% only with the switch.
    assert round(off["moddedStats"]["multishot"], 3) == 1.8
    assert round(on["moddedStats"]["multishot"], 3) == 3.3
    assert on["benchmarkTimeline"]["killsPerMinute"] > off["benchmarkTimeline"]["killsPerMinute"]


def test_headshots_aiming_and_arcanes_are_ignored():
    scope = _sim([ARGON], headshotChance=1.0, aiming=True)
    bare = _sim([])
    assert scope["moddedStats"]["critChance"] == bare["moddedStats"]["critChance"]
    assert scope["benchmarkTimeline"]["killsPerMinute"] == bare["benchmarkTimeline"]["killsPerMinute"]


DETHCUBE = "/Lotus/Types/Sentinels/SentinelPowersuits/DethCubePowerSuit"
FIRED_UP = "/Lotus/Upgrades/Mods/Sentinel/SentinelOverheatDamageMod"
ASSAULT = "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack"
VITALITY = "/Lotus/Upgrades/Mods/Sentinel/SentinelHealthMaxMod"


def test_sentinel_body_stats_and_capacity():
    panel = app.sentinel_evaluate_payload({"sentinel": {"path": DETHCUBE, "mods": [
        {"path": VITALITY, "rank": 10, "slot": 1}, {"path": ASSAULT, "rank": 5, "slot": 0}]}})
    assert panel["stats"]["health"]["base"] == 560 * 3.5
    assert round(panel["stats"]["health"]["modded"] / panel["stats"]["health"]["base"], 3) == 3.5  # +250%
    assert panel["attackPrecept"] and panel["capacity"]["total"] == 60


def test_fired_up_reaches_the_companion_weapon():
    sentinel = {"path": DETHCUBE, "mods": [{"path": ASSAULT, "rank": 5, "slot": 0}, {"path": FIRED_UP, "rank": 5, "slot": 1}]}
    bare = _sim([])
    fired = _sim([], sentinel=sentinel)
    heat = fired["moddedStats"]["damageTypes"].get("DT_FIRE", 0)
    assert heat > 0 and fired["benchmarkTimeline"]["killsPerMinute"] > bare["benchmarkTimeline"]["killsPerMinute"]
    off = _sim([], sentinel={**sentinel, "options": {"firedUp": False}})
    assert not off["moddedStats"]["damageTypes"].get("DT_FIRE")


def test_link_mods_and_foreign_precepts_are_rejected():
    import pytest
    from wfarsenal.simulator import SimulationError
    with pytest.raises(SimulationError):
        app.sentinel_evaluate_payload({"sentinel": {"path": DETHCUBE, "mods": [
            {"path": "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkHealthMaxMod", "rank": 10}]}})
    with pytest.raises(SimulationError):  # Ghost is Shade's precept
        app.sentinel_evaluate_payload({"sentinel": {"path": DETHCUBE, "mods": [
            {"path": "/Lotus/Types/Sentinels/SentinelPrecepts/Ghost", "rank": 5}]}})


def test_sentinel_slots_take_forma_polarities():
    def drain(polarities):
        panel = app.sentinel_evaluate_payload({"sentinel": {"path": DETHCUBE, "polarities": polarities, "mods": [
            {"path": VITALITY, "rank": 10, "slot": 1}]}})
        return panel["slots"][0]["drain"], panel["formaCount"]
    native, _ = drain(None)
    vitality = app.sentinel_body.data()["mods"][VITALITY]["polarity"]
    other = next(p for p in ("AP_ATTACK", "AP_DEFENSE", "AP_TACTIC") if p != vitality)
    assert drain([None, vitality]) == (-(-native // 2), 1)
    assert drain([None, other]) == (-(-native * 5 // 4), 1)
    assert drain([None, "AP_ANY"])[0] == -(-native // 2)
    # Forma a native Penjaga slot back to no polarity.
    assert drain(["AP_UNIVERSAL"]) == (native, 1)


def test_fired_up_combines_after_the_installed_mods_in_build_and_manual():
    # Mods in slot order, then runtime buffs (Fired Up heat), innate elements
    # last: Stormbringer + Fired Up = Radiation, Stinger's innate Toxin stays.
    stinger = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Stinger")
    storm = next(m for m in app.MANUAL_MODS if m.get("nameEn") == "Stormbringer")
    sentinel = {"path": DETHCUBE, "mods": [{"path": ASSAULT, "rank": 5, "slot": 0}, {"path": FIRED_UP, "rank": 5, "slot": 1}]}
    manual = app.simulate_manual_payload(dict(weapon=stinger["path"], enemy=app._BENCHMARK_ENEMY_PATH, level=100,
                                              mods=[dict(path=storm["path"], rank=storm["maxRank"], slot=0)], sentinel=sentinel))
    built = app.build_weapon_payload({"weapon": stinger["path"], "profile": "fast", "slotCount": 1,
                                      "requiredMods": [storm["path"]], "sentinel": sentinel})
    types = {k for k, v in manual["moddedStats"]["damageTypes"].items() if v > 0}
    assert types == {"DT_RADIATION", "DT_POISON"}
    assert built["moddedStats"]["damageTypes"] == manual["moddedStats"]["damageTypes"]


def test_exalted_variants_group_with_their_own_weapon():
    rows = app.CATALOG["weapons"]
    by_group = {}
    for row in rows:
        by_group.setdefault(row.get("variantGroupPath") or row["path"], []).append(row)
    for group in by_group.values():
        assert len({bool(row.get("exalted")) for row in group}) == 1
    names = {row["nameEn"]: row for row in rows}
    assert names["Exalted Prime Blade"]["variantGroupPath"] == names["Exalted Blade"]["path"]
    # Abstract bases (LotusLongGun, LotusPistol ...) never become a version group.
    assert all(not group.startswith(("/Lotus/Weapons/Tenno/LotusLongGun", "/Lotus/Weapons/Tenno/Pistol/LotusPistol"))
               for group in by_group if len(by_group[group]) > 1)
