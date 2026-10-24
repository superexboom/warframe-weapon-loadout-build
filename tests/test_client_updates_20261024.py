"""2026-10-24 client: ammo-efficiency values replayed onto the pinned export (data/mechanics/client-updates.json)."""
import copy

import pytest

import app
from wfarsenal import client_updates


def _branch(weapon, suffix):
    w = next(x for x in app.EXPORTS["weapons"] if x.get("nameEn") == weapon)
    return next(b for t in w["incarnon"]["tiers"] for b in t["branches"] if b["path"].endswith(suffix))


def _ammo(branch):
    return [(e["operation"], e["valuePerRank"]) for c in branch["conditionalEffects"] for e in c["effects"]
            if e["upgradeType"] == "WEAPON_AMMO_CONSUME_RATE"]


def test_crimson_overture_is_three_stacks_of_25_percent_on_every_boltor():
    for name, suffix in (("Boltor", "BoltorEvoTier1B"), ("Boltor Prime", "PrimeBoltorEvoTier1B"), ("Telos Boltor", "TelosBoltorEvoTier1B"),
                         ("Dera", "DeraEvoTier1A"), ("Dera Vandal", "VandalDeraEvoTier1A")):
        branch = _branch(name, suffix)
        assert _ammo(branch) == [("STACKING_MULTIPLY", -0.25)], name
        assert [c["maxStacks"] for c in branch["conditionalEffects"]] == [3], name


def test_infinite_ammo_is_a_set_zero_and_skips_the_efficiency_cap():
    assert _ammo(_branch("Vasto Prime", "PrimeVastoEvoTier3C")) == [("SET", 0)]
    assert _ammo(_branch("Bronco", "BroncoEvoTier3A")) == [("STACKING_MULTIPLY", -0.75)]
    from wfarsenal.damage import ModEffect, _capped_ammo_cost
    assert _capped_ammo_cost(1.0, [ModEffect("WEAPON_AMMO_CONSUME_RATE", "SET", 0.0)], 0.0) == 0.0
    assert _capped_ammo_cost(1.0, [ModEffect("WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", -1.0)], 0.0) == pytest.approx(0.25)
    vasto = next(x for x in app.CATALOG["weapons"] if x.get("nameEn") == "Vasto")
    option = next(o for t in vasto["incarnon"] for o in t["options"] if o["id"] == "4-3")
    assert "无限弹药" in option["description"]


def test_vasto_headshots_never_reload_under_its_evolution():
    vasto = next(x for x in app.EXPORTS["weapons"] if x.get("nameEn") == "Vasto Prime")
    tl = app.simulate_manual_payload(dict(weapon=vasto["path"], fireMode=0, mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170,
                                          steelPath=True, headshotChance=1.0, triggerPolicy="emergent",
                                          incarnonChoices={"2": "2-1", "3": "3-1", "4": "4-3"}))["benchmarkTimeline"]
    assert tl["reloads"] == 0 and tl["shots"] > 0


def test_arcane_pistoleer_grants_infinite_ammo_every_time():
    card = next(x for x in app.CATALOG["arcanes"] if x.get("nameEn") == "Arcane Pistoleer")
    assert card["trigger"]["chance"] == 1 and "无限弹药" in card["effect"]


def test_a_record_holding_another_value_stops_the_load():
    exports = {"weapons": copy.deepcopy([w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Bronco"])}
    branch = next(b for t in exports["weapons"][0]["incarnon"]["tiers"] for b in t["branches"] if b["path"].endswith("BroncoEvoTier3A"))
    for c in branch["conditionalEffects"]:
        for e in c["effects"]:
            e["valuePerRank"] = -0.5
    patch = next(p for p in client_updates.patches()["patches"] if p["id"] == "bronco-3a")
    with pytest.raises(ValueError, match="expected STACKING_MULTIPLY"):
        client_updates._apply(patch, branch)
