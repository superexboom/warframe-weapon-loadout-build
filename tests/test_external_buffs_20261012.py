"""External buffs and the build page's element target (2026-10-12).

- Abilities read "<Warframe> · <技能>", auras their mod name, from the
  localized catalog; every row says what it raises.
- Eclipse / Molecular Prime are a final multiplier on the hit and its
  statuses (the old untyped post-combine bucket only scaled physical damage).
- Warcry / Wrathful Advance only reach melee, Metamorphosis only guns, the
  amps their weapon class; a family keeps its strongest member.
- Toxic Lash / Resupply / Xata's Whisper fire Extra Hits; Covenant and
  Wrathful Advance add crit after mods; Corrosive Projection and Shield
  Disruption act on the enemy, from 1-4 squad members.
- Stored configurations keep working (renamed ids map over, retired dropped).
- An element target the beam misses is found by seeding its components.
"""
import pytest

import app
from wfarsenal import optimizer
from wfarsenal.damage import ModEffect, enemy_defenses
from wfarsenal.simulator import SimulationError

WEAPONS = {w.get("nameEn"): w for w in app.EXPORTS["weapons"]}


def _stats(name, buffs):
    payload = dict(weapon=WEAPONS[name]["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                   externalBuffs=buffs)
    return app.simulate_manual_payload(payload)["moddedStats"]


def test_labels_name_the_warframe_and_what_is_raised():
    rows = {row["id"]: row for row in app.CATALOG["buildOptions"]["externalBuffs"]}
    assert rows["roar"]["label"] == "Rhino · 战吼"
    assert rows["roar-helminth"]["label"] == "Helminth · 战吼（注入）"
    assert rows["fireball-frenzy"]["label"] == "Ember · 狂热火球（火球强化）"
    assert rows["rifle-amp"]["label"] == "步枪增幅" and rows["rifle-amp"]["squad"]
    assert rows["warcry"]["effects"] == [{"label": "近战攻速", "scale": 1.0, "applies": ["/Lotus/Types/Game/LotusMeleeWeapon"]}]
    for row in rows.values():
        assert row["detail"] and all(effect["label"] for effect in row["effects"])
        assert not any(word in row["label"] for word in ("Roar", "Eclipse", "Warcry", "Amp"))


def test_eclipse_is_a_final_multiplier_on_hits_and_statuses():
    plain = _stats("Boltor Prime", [])
    eclipse = _stats("Boltor Prime", [{"id": "eclipse", "strength": 1.0}])
    assert sum(eclipse["damage_types"].values()) == pytest.approx(3 * sum(plain["damage_types"].values()))
    assert eclipse["dot_base_damage"] == pytest.approx(3 * plain["dot_base_damage"])
    prime = _stats("Boltor Prime", [{"id": "molecular-prime", "strength": 3.0}])  # fixed, strength ignored
    assert sum(prime["damage_types"].values()) == pytest.approx(2 * sum(plain["damage_types"].values()))


def test_buffs_reach_only_their_weapons():
    boltor, nikana = WEAPONS["Boltor Prime"], WEAPONS["Nikana Prime"]
    assert _stats("Boltor Prime", [{"id": "warcry"}])["fire_rate"] == pytest.approx(_stats("Boltor Prime", [])["fire_rate"])
    melee_plain = _stats("Nikana Prime", [])["fire_rate"]
    assert _stats("Nikana Prime", [{"id": "warcry"}])["fire_rate"] == pytest.approx(melee_plain * 1.5)
    rifle = app._external_buff_effects([{"id": "rifle-amp", "count": 2}], boltor)
    assert [e.valid_type for e in rifle] == ["/Lotus/Weapons/Tenno/Rifle/LotusRifle"]
    assert rifle[0].value == pytest.approx(0.54)
    assert _stats("Boltor Prime", [{"id": "pistol-amp"}])["damage_types"] == _stats("Boltor Prime", [])["damage_types"]
    crit = _stats("Nikana Prime", [{"id": "wrathful-advance"}])["crit_chance"] - _stats("Nikana Prime", [])["crit_chance"]
    assert crit == pytest.approx(2.0)
    assert _stats("Boltor Prime", [{"id": "wrathful-advance"}])["crit_chance"] == pytest.approx(_stats("Boltor Prime", [])["crit_chance"])
    assert app._external_buff_effects([{"id": "toxic-lash"}], nikana)[0].value == pytest.approx(0.6)


def test_a_family_keeps_its_strongest_member():
    effects = app._external_buff_effects([{"id": "roar", "strength": 1.0}, {"id": "roar-helminth", "strength": 2.0}])
    assert [(e.upgrade_type, round(e.value, 3)) for e in effects] == [("GAMEPLAY_FACTION_DAMAGE", 0.6)]


def test_covenant_adds_crit_after_mods_and_four_times_on_weak_points():
    plain, covenant = _stats("Boltor Prime", []), _stats("Boltor Prime", [{"id": "covenant"}])
    assert covenant["crit_chance"] - plain["crit_chance"] == pytest.approx(0.5)
    assert covenant["weakpoint_crit_chance_bonus"] == pytest.approx(1.5)


def test_extra_hits_and_their_forced_statuses():
    lash = _stats("Boltor Prime", [{"id": "toxic-lash"}])
    assert [(t, round(v, 3), f) for t, v, f in lash["extra_hits"]] == [("DT_POISON", 0.3, True)]
    assert lash["native_forced_procs"].get("DT_POISON") == pytest.approx(1.0)
    resupply = app._external_buff_effects([{"id": "resupply", "element": "DT_CORROSIVE"}], WEAPONS["Rubico Prime"])
    assert resupply[0].damage_type == "DT_CORROSIVE" and resupply[0].value == pytest.approx(0.5)
    xata = _stats("Boltor Prime", [{"id": "xatas-whisper"}])
    assert not xata["native_forced_procs"].get("DT_VOID")
    payload = dict(weapon=WEAPONS["Boltor Prime"]["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True)
    plain = app.simulate_manual_payload(payload)["benchmarkTimeline"]["killsPerMinute"]
    lashed = app.simulate_manual_payload(dict(payload, externalBuffs=[{"id": "toxic-lash"}]))["benchmarkTimeline"]["killsPerMinute"]
    assert lashed > plain * 1.3


def test_squad_auras_on_the_enemy():
    merged = app._external_enemy_enhancements([{"id": "corrosive-projection", "count": 2}, {"id": "shield-disruption", "count": 4}], {})
    assert merged["auraArmourReduction"] == pytest.approx(0.36)
    assert merged["auraShieldReduction"] == pytest.approx(0.72)
    drift = app._external_enemy_enhancements([{"id": "corrosive-projection", "count": 4}, {"id": "coaction-drift"}], {})
    assert drift["auraArmourReduction"] == pytest.approx(0.72 * 1.15)
    enemy = optimizer.resolve_record(app.EXPORTS["enemies"], app._BENCHMARK_ENEMY_PATH, kind="enemy")
    bare = enemy_defenses(enemy, level=100)
    stripped = enemy_defenses(enemy, level=100, enemy_enhancements=merged)
    assert stripped["armour"] == pytest.approx(bare["armour"] * 0.64)


def test_stored_configurations_keep_working():
    assert app._external_buff_effects([{"id": "mallet", "value": 2.0}])[0].value == pytest.approx(2.0)
    assert app._external_buff_effects([{"id": "unairu-wisp", "value": 1.0}]) is None
    assert app._external_buff_effects([{"id": "roar", "value": 0.5}])[0].value == pytest.approx(0.5)
    with pytest.raises(SimulationError):
        app._external_buff_effects([{"id": "no-such-buff"}])


def _card(key, dtype=None, value=0.9, drain=7):
    effects = (ModEffect(upgrade_type="WEAPON_PERCENT_BASE_DAMAGE_ADDED", operation="STACKING_MULTIPLY", value=value,
                         damage_type=dtype),) if dtype else ()
    return optimizer._Card(key=key, record=None, rank=0, effects=effects, skipped=(), drain=drain, polarity=None)


def test_element_target_seeds_its_components(monkeypatch):
    cards = [_card("serration"), _card("cryo", "DT_FREEZE"), _card("cryo-cheap", "DT_FREEZE", 0.6, 4),
             _card("clip", "DT_POISON"), _card("storm", "DT_ELECTRICITY")]
    calls = []

    def fake(weapon, candidates, riven, *, required_damage_type=None, required_mod_keys=None, **kwargs):
        calls.append(tuple(required_mod_keys or ()))
        if {"cryo", "clip"} <= set(required_mod_keys or ()):
            return "viral build"
        raise SimulationError(f"no capacity-valid build satisfies damage type {required_damage_type}")

    monkeypatch.setattr(optimizer, "_optimize", fake)
    assert optimizer.optimize_for_element({}, cards, None, required_damage_type="DT_VIRAL") == "viral build"
    assert calls == [(), ("cryo", "clip")]
    calls.clear()
    with pytest.raises(SimulationError, match="DT_MAGNETIC"):
        optimizer.optimize_for_element({}, cards[:1], None, required_damage_type="DT_MAGNETIC")
    assert calls == [()]
