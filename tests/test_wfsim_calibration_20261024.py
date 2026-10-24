"""2026-10-24 calibrations taken from WFSim 4af28da691 (measurements and wiki rules)."""
import pytest

import app


def _sim(name, mods=(), **extra):
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    # Names pick the full card over a Flawed / Beginner namesake (Fast Hands has both).
    by_name = {}
    for m in sorted(app.MANUAL_MODS_BY_PATH.values(), key=lambda m: m.get("maxRank") or 0):
        by_name[m.get("nameEn")] = m
    rows = [dict(path=by_name[n]["path"], rank=by_name[n].get("maxRank") or 0, slot=i) for i, n in enumerate(mods)]
    return app.simulate_manual_payload(dict(weapon=weapon["path"], mods=rows, enemy=app._BENCHMARK_ENEMY_PATH,
                                            level=170, steelPath=True, headshotChance=0., **extra))


@pytest.mark.parametrize("name,mod,rounds", [("Tonkor", "Primed Magazine Warp", 2.0), ("Tonkor", "Magazine Warp", 1.0),
                                             ("Vectis", "Primed Magazine Warp", 2.0)])
def test_a_modded_magazine_rounds_to_the_nearest_round(name, mod, rounds):
    # wiki Magazine Warp: a one-round Tonkor under Primed Magazine Warp holds 2 (1 x 1.55); +30% stays 1.
    assert _sim(name, [mod])["moddedStats"]["magazine"] == rounds


def test_haalvu_empty_battery_plays_its_two_second_animation():
    # WFSim M121: fired dry, 2 s before it fires again; the refill (0.5 s + 150 / 300 s) runs inside it.
    assert _sim("Haalvu")["moddedStats"]["reloadTime"] == pytest.approx(2.0)
    # Reload speed shortens the animation only, never below the 1 s refill.
    hands = app.MANUAL_MODS_BY_PATH["/Lotus/Upgrades/Mods/Rifle/WeaponReloadSpeedMod"]
    speed = sum(e["valuePerRank"] for e in hands["effects"] if e["upgradeType"] == "WEAPON_RELOAD_SPEED") * (hands["maxRank"] + 1)
    assert _sim("Haalvu", ["Fast Hands"])["moddedStats"]["reloadTime"] == pytest.approx(max(2.0 / (1 + speed), 1.0))


def test_gotva_prime_status_arms_a_set_crit():
    # GrnOrokinRifleRedCrit.lua: a status-applying pellet arms the next with 15%; it reads 300% crit chance.
    bare = _sim("Gotva Prime")["moddedStats"]
    armed = 0.15000001 * min(1.0, bare["statusChance"])
    assert bare["critChance"] == pytest.approx(0.23 + armed * (3.0 - 0.23))
    # Only the weapon that carries the script: another rifle keeps its exported chance.
    other = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Grakata")
    assert _sim("Grakata")["moddedStats"]["critChance"] == pytest.approx(other["fireModes"][0]["damage"]["critChance"])
