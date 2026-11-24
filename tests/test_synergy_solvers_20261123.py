"""2026-11-23: Stage 3 Cross-Entity Synergy Bridge tests across Panel Solver,
1D Kill/Window Replay, Native wfcore Shadow Parity, Optimizer, HTTP Endpoints,
and Arena Context contracts.
"""

from __future__ import annotations

from http.client import HTTPConnection
import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))

import app  # noqa: E402
from wfarsenal import (  # noqa: E402
    arcane_runtime,
    combat_replay,
    companion_loadout,
    damage,
    mods_native,
    native_replay,
    optimizer,
    simulator,
    synergy,
)


WEAPONS_BY_EN = {w.get("nameEn"): w for w in app.EXPORTS["weapons"] if isinstance(w, dict)}
MODS_BY_EN = {m.get("nameEn"): m for m in app.MANUAL_MODS if isinstance(m, dict)}
ARCANES_BY_EN = {a.get("nameEn"): a for a in app.EXPORTS["arcanes"] if isinstance(a, dict)}
WF_MODS_BY_EN = {m.get("nameEn"): m for m in app.WARFRAME_ENGINE.mods if isinstance(m, dict)}
WF_ARCANES_BY_EN = {a.get("nameEn"): a for a in app.WARFRAME_ENGINE.arcanes if isinstance(a, dict)}

EXCALIBUR = "/Lotus/Powersuits/Excalibur/Excalibur"
RHINO = "/Lotus/Powersuits/Rhino/Rhino"
EMBER = "/Lotus/Powersuits/Ember/Ember"
CYTE_09 = "/Lotus/Powersuits/Frumentarius/Frumentarius"
LAVOS = "/Lotus/Powersuits/Alchemist/Alchemist"
EXALTED_BLADE = "/Lotus/Powersuits/Excalibur/DoomSword"

NAUTILUS_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/NautilusPrimeSentinelPowerSuit"
WYRM_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/PrimeWyrmPowerSuit"
DIRIGA = "/Lotus/Types/Sentinels/SentinelPowersuits/ArcDronePowerSuit"
ADARZA_KAVAT = "/Lotus/Types/Game/CatbrowPet/MirrorCatbrowPetPowerSuit"
ADARZA_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/AdarzaPetWeapon"
VERGLAS_PRIME = "/Lotus/Types/Sentinels/SentinelWeapons/SentinelFreezeRayPrimeRifle"

ASSAULT_MODE = "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack"
ARC_COIL = "/Lotus/Types/Sentinels/SentinelPrecepts/ArcTrap"
TENACIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TenaciousPartner"
REINFORCED_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/AlacrityField"
MANIFOLD_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/CompoundingLaceration"
HUNTER_SYNERGY = "/Lotus/Upgrades/Mods/Sets/Hunter/CompanionHunterSynergyMod"
LINK_REDIRECTION = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkShieldMaxMod"


def _shard_path(base_leaf: str, *, tau: bool = False) -> str:
    target_leaf = f"{base_leaf}Mythic" if tau else base_leaf
    for row in app.WARFRAME_ENGINE.shards:
        p = str(row.get("path") or "")
        if p.endswith("/" + target_leaf):
            return p
    raise KeyError(target_leaf)


# ---------------------------------------------------------------------------
# 1. Neutral Fast Path & Non-Combining Elemental Augments & Extra Hit Panel
# ---------------------------------------------------------------------------


def test_neutral_fast_path_returns_none_and_omits_synergy_summary():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    payload = {
        "weapon": boltor["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "warframeLink": {"enabled": False, "frameId": EXCALIBUR},
        "companionLink": {"enabled": False, "path": NAUTILUS_PRIME},
    }
    assert synergy.has_synergy_links(payload, boltor) is False
    assert (
        synergy.resolve_synergy(
            payload,
            weapon=boltor,
            warframe_engine=app.WARFRAME_ENGINE,
            exports=app.EXPORTS,
        )
        is None
    )
    res = app.simulate_manual_payload(payload)
    assert "synergySummary" not in res


def test_external_buff_elemental_augments_do_not_coalesce_with_weapon_elements():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    infected_clip = MODS_BY_EN["Infected Clip"]["path"]

    for buff_id, expected_dt in (
        ("fireball-frenzy", "DT_FIRE"),
        ("freeze-force", "DT_FREEZE"),
        ("shock-trooper", "DT_ELECTRICITY"),
    ):
        res = app.simulate_manual_payload({
            "weapon": boltor["path"],
            "mods": [{"path": infected_clip, "rank": 5, "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "externalBuffs": [{"id": buff_id, "strength": 1.0}],
        })
        dtypes = res["moddedStats"]["damageTypes"]
        # Weapon Toxin stays Toxin and augment element stays independent (no Gas/Viral/Corrosive combination!).
        assert dtypes.get("DT_POISON", 0.0) > 0.0
        assert dtypes.get(expected_dt, 0.0) > 0.0
        for combined in ("DT_GAS", "DT_VIRAL", "DT_CORROSIVE"):
            assert dtypes.get(combined, 0.0) == pytest.approx(0.0)


def test_static_panel_extra_hit_direct_damage_and_xata_headshot_double_dip():
    tg = {
        "health": 10000.0,
        "shield": 0.0,
        "overguard": 0.0,
        "armour": 0.0,
        "baseLevel": 1,
        "faction": "Grineer",
        "factionResistance": "RK_NEUTRAL",
        "headshotMultiplier": 3.0,
        "hitProxies": [{"bone": "HEAD", "part": "HEAD", "damageAtten": 2.0, "criticalMultiplier": 1.0}],
    }
    plain_st = damage.ModdedStats(
        damage_types={"DT_IMPACT": 100.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=0.0,
        multishot=1.0,
        fire_rate=2.0,
        magazine=10.0,
        reload_time=1.0,
    )
    lash_st = damage.ModdedStats(
        damage_types={"DT_IMPACT": 100.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=0.0,
        multishot=1.0,
        fire_rate=2.0,
        magazine=10.0,
        reload_time=1.0,
        extra_hits=(("DT_POISON", 0.30, True),),
        faction_damage_multipliers={"": 1.5},
    )
    xata_st = damage.ModdedStats(
        damage_types={"DT_IMPACT": 100.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=0.0,
        multishot=1.0,
        fire_rate=2.0,
        magazine=10.0,
        reload_time=1.0,
        extra_hits=(("DT_VOID", 0.26, False),),
    )

    # Plain body = 100, head = 300 (damageAtten 2.0 * 1.5 = 3.0).
    d_plain_head = damage.damage_against(plain_st, tg, level=1, hit_location="head")
    assert d_plain_head["perHit"] == pytest.approx(300.0)
    assert d_plain_head["extraHitPerHit"] == pytest.approx(0.0)

    # Toxic Lash with 1.5x faction: main head hit = 300 * 1.5 = 450; extra hit = 450 * 0.3 * 1.5 (faction again, no 2nd head mult) = 202.5.
    d_lash_head = damage.damage_against(lash_st, tg, level=1, hit_location="head")
    assert d_lash_head["extraHitPerHit"] == pytest.approx(450.0 * 0.30 * 1.5)
    assert d_lash_head["perHit"] == pytest.approx(450.0 + 450.0 * 0.30 * 1.5)

    # Xata's Whisper on head: main head hit = 300; Void extra hit applies head multiplier a second time -> 300 * 0.26 * 3.0 = 234!
    d_xata_head = damage.damage_against(xata_st, tg, level=1, hit_location="head")
    assert d_xata_head["extraHitPerHit"] == pytest.approx(234.0)
    assert d_xata_head["perHit"] == pytest.approx(534.0)

    # Xata's Whisper against Overguard gets Void 1.5x Overguard vulnerability!
    og_tg = {**tg, "overguard": 5000.0}
    d_xata_og = damage.damage_against(xata_st, og_tg, level=1, hit_location="body")
    assert d_xata_og["extraHitPerHit"] == pytest.approx(100.0 * 0.26 * 1.5)


# ---------------------------------------------------------------------------
# 2. Melee Retaliation Overshield, Secondary Shiver Primed Cold, Melee Crescendo
# ---------------------------------------------------------------------------


def test_retaliation_overshield_shiver_primed_cold_and_crescendo():
    ret_rec = ARCANES_BY_EN["Melee Retaliation"]
    ret_spec = arcane_runtime.configuration(ret_rec, 5)
    assert ret_spec is not None
    # Neutral backward compatibility: 800 shield, no overshield -> 4 * 0.30 = 1.20
    st0, up0 = arcane_runtime.default_state(ret_spec, {"frameShield": 800.0}, 0.0)
    assert ret_spec["build"](st0, up0)[0].value == pytest.approx(1.20)
    # With 1200 overshield -> 4 * 0.30 + 6 * 0.15 = 2.10
    st1, up1 = arcane_runtime.default_state(ret_spec, {"frameShield": 800.0, "frameOvershield": 1200.0}, 0.0)
    assert ret_spec["build"](st1, up1)[0].value == pytest.approx(2.10)
    # Capped at 4.20
    st_cap, up_cap = arcane_runtime.default_state(ret_spec, {"frameShield": 3000.0, "frameOvershield": 1200.0}, 0.0)
    assert ret_spec["build"](st_cap, up_cap)[0].value == pytest.approx(4.20)

    # Secondary Shiver reflects primedColdStacks when > 0 and stays 0 when neutral
    shiver_rec = ARCANES_BY_EN["Secondary Shiver"]
    shiver_spec = arcane_runtime.configuration(shiver_rec, 5)
    assert shiver_spec is not None
    assert arcane_runtime.default_state(shiver_spec, {}, 0.0) == (0, 1.0)
    s_whole, s_up = arcane_runtime.default_state(shiver_spec, {"primedColdStacks": 7.5}, 0.0)
    assert shiver_spec["build"](s_whole, s_up)[0].runtime_chance == pytest.approx(7.5)

    # Melee Crescendo grants up to +220 initial combo (12x) when forced
    cresc_rec = ARCANES_BY_EN["Melee Crescendo"]
    cresc_spec = arcane_runtime.configuration(cresc_rec, 5)
    assert cresc_spec is not None
    assert cresc_spec["build"](cresc_spec["maxStacks"], 1.0)[0].value == pytest.approx(220.0)
    nikana = WEAPONS_BY_EN["Nikana Prime"]
    sim_cresc = app.simulate_manual_payload({
        "weapon": nikana["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [{"path": cresc_rec["path"], "rank": 5, "stacks": 40}],
    })
    assert sim_cresc["moddedStats"]["initial_combo"] >= 220.0


# ---------------------------------------------------------------------------
# 3. Emerald Archon Shard Corrosive 14-Stack 100% Strip & Toxin Status Damage
#    with Native wfcore Shadow Parity
# ---------------------------------------------------------------------------


def test_emerald_shard_corrosive_14_full_strip_and_toxin_dot_native_shadow(monkeypatch):
    monkeypatch.setattr(mods_native, "SHADOW", True)
    monkeypatch.setattr(native_replay, "SHADOW", True)

    boltor = WEAPONS_BY_EN["Boltor Prime"]
    # Pure Toxin + Slash weapon build to test typed Toxin status damage isolation in both Python and Rust wfcore!
    toxin_shard_fx = damage.ModEffect(
        upgrade_type="WEAPON_PROC_DAMAGE",
        operation="STACKING_MULTIPLY",
        value=0.45,
        damage_type="DT_POISON",
        valid_proc_types=("PT_POISON",),
        source_path="shard:toxinStatusDamage",
    )
    corrosive_cap_fx = damage.ModEffect(
        upgrade_type="RUNTIME_TYPED_PROC_MAX_STACK",
        operation="ADD",
        value=4.0,
        damage_type="DT_CORROSIVE",
        source_path="shard:corrosiveMaxStacksBonus",
    )
    add_toxin = damage.ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "STACKING_MULTIPLY", 1.0, damage_type="DT_POISON")
    add_fire = damage.ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "STACKING_MULTIPLY", 1.0, damage_type="DT_FIRE")
    add_sc = damage.ModEffect("WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", 3.0)

    st_base = damage.apply_mods(boltor, [add_toxin, add_fire, add_sc], scenario=damage.Scenario())
    st_emerald = damage.apply_mods(
        boltor, [add_toxin, add_fire, add_sc, toxin_shard_fx, corrosive_cap_fx], scenario=damage.Scenario()
    )
    assert st_emerald.proc_damage_types == {"DT_POISON": pytest.approx(1.45)}
    assert damage.proc_stack_cap(st_emerald, "DT_CORROSIVE", 10.0) == pytest.approx(14.0)

    armored_tg = {
        "health": 1e9,
        "shield": 0.0,
        "overguard": 0.0,
        "armour": 2700.0,
        "armourType": "RK_FERRITE_ARMOR",
        "healthType": "RK_CLONED_FLESH",
        "shieldType": "RK_NONE",
        "baseLevel": 1,
        "faction": "Grineer",
        "factionResistance": "RK_NEUTRAL",
    }
    b_dot = damage.expected_status_damage(st_base, {**armored_tg, "armour": 0.0}, level=1)["dot"]["perType"]
    e_dot = damage.expected_status_damage(st_emerald, {**armored_tg, "armour": 0.0}, level=1)["dot"]["perType"]
    assert e_dot["DT_POISON"]["perProc"] == pytest.approx(b_dot["DT_POISON"]["perProc"] * 1.45, rel=1e-5)
    assert e_dot["DT_FIRE"]["perProc"] == pytest.approx(b_dot["DT_FIRE"]["perProc"], rel=1e-5)

    # Verify native_replay runs cleanly in SHADOW mode on typed Toxin DoT + 14-stack Corrosive strip!
    corr_fx = [
        damage.ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", 1.0, damage_type="DT_POISON"),
        damage.ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", 1.0, damage_type="DT_ELECTRICITY"),
        damage.ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "STACKING_MULTIPLY", 0.6, damage_type="DT_POISON"),
        damage.ModEffect("WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", 8.0),
        damage.ModEffect("WEAPON_FIRE_RATE", "STACKING_MULTIPLY", 2.0),
    ]
    st_10 = damage.apply_mods(boltor, corr_fx, scenario=damage.Scenario())
    st_14 = damage.apply_mods(boltor, [*corr_fx, corrosive_cap_fx, toxin_shard_fx], scenario=damage.Scenario())
    before_native = native_replay.STATS["native"]
    rep_10 = combat_replay.replay(
        st_10,
        armored_tg,
        attacks_per_second=st_10.fire_rate,
        window_seconds=8.0,
        collect_timeline=False,
        combat={"resolve": lambda *_: (st_10, None)},
    )
    rep_14 = combat_replay.replay(
        st_14,
        armored_tg,
        attacks_per_second=st_14.fire_rate,
        window_seconds=8.0,
        collect_timeline=False,
        combat={"resolve": lambda *_: (st_14, None)},
    )
    assert native_replay.STATS["native"] >= before_native + 2
    # 14 Corrosive stacks achieve 100% full armor strip vs 80% strip (540 remaining armor = 40.25% U36 DR) at 10 stacks!
    assert rep_14["directWindow"] > rep_10["directWindow"] * 1.55
    assert rep_14["dotWindow"] > rep_10["dotWindow"] * 1.60


# ---------------------------------------------------------------------------
# 4. External Target Status Priming & Cross-Entity Non-Duplicate Set Counting
# ---------------------------------------------------------------------------


def test_external_priming_stacks_and_condition_overload_union():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    galv_apt = MODS_BY_EN["Galvanized Aptitude"]["path"]
    corrupted_hg = "/Lotus/Types/Enemies/Orokin/OrokinHeavyFemaleAvatar"

    base = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=corrupted_hg,
        mods=[{"path": galv_apt, "rank": 10}],
        level=170,
        steel_path=True,
        scenario=damage.Scenario(trigger_policy="assumed_max"),
    )
    primed = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=corrupted_hg,
        mods=[{"path": galv_apt, "rank": 10}],
        level=170,
        steel_path=True,
        enemy_enhancements={
            "primingStacks": {
                "DT_VIRAL": 10.0,
                "DT_CORROSIVE": 10.0,
                "DT_FREEZE": 10.0,
                "DT_PUNCTURE": 5.0,
            }
        },
        scenario=damage.Scenario(trigger_policy="assumed_max"),
    )
    # Boltor Prime has Puncture + Impact (2 types); adding Viral + Corrosive + Freeze raises CO victim status count from 2 to 5!
    assert primed["selection"]["scenario"]["victimStatusCount"] == base["selection"]["scenario"]["victimStatusCount"] + 3
    assert primed["targetDamage"]["perShot"] > base["targetDamage"]["perShot"] * 12.0

    # Against Overguard (Thrax Centurion), Magnetic priming multiplies Overguard damage by up to 4.25x!
    og_base = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=app._BENCHMARK_ENEMY_PATH,
        mods=[],
        level=170,
        steel_path=True,
    )
    og_mag = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=app._BENCHMARK_ENEMY_PATH,
        mods=[],
        level=170,
        steel_path=True,
        enemy_enhancements={"primingStacks": {"DT_MAGNETIC": 10.0}},
    )
    assert og_mag["targetDamage"]["perShot"] == pytest.approx(og_base["targetDamage"]["perShot"] * 4.25, rel=1e-5)


def test_cross_entity_set_pieces_zero_card_weapon_and_duplicate_deduplication():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    vig_arm = "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteArmamentsMod"
    vig_ferv = "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteFervorMod"
    vig_off = "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteOffenseMod"
    vig_sup = "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteSuppliesMod"
    vig_pur = "/Lotus/Upgrades/Mods/Sets/Vigilante/WarframeVigilantePursuitMod"
    vig_vig = "/Lotus/Upgrades/Mods/Sets/Vigilante/WarframeVigilanteVigorMod"

    ext_six = [
        {"path": p, "setId": "VigilanteSetMod"}
        for p in (vig_arm, vig_ferv, vig_off, vig_sup, vig_pur, vig_vig)
    ]
    # 0 Vigilante mods on Primary weapon, 6 unique pieces across Companion + Warframe -> +30% doubleCritChance!
    zero_card_res = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=app._BENCHMARK_ENEMY_PATH,
        mods=[],
        external_set_mods=ext_six,
    )
    assert zero_card_res["moddedStats"]["doubleCritChance"] == pytest.approx(0.30)

    # Duplicate Vigilante Armaments on both weapon and companion must NOT double-count (1 + 1 duplicate = 1 piece = 5%, not 10%!).
    dup_res = simulator.simulate(
        export_dir=app.EXPORT_DIR,
        weapon=boltor["path"],
        enemy=app._BENCHMARK_ENEMY_PATH,
        mods=[{"path": vig_arm, "rank": 5}],
        external_set_mods=[{"path": vig_arm, "setId": "VigilanteSetMod"}],
    )
    assert dup_res["moddedStats"]["doubleCritChance"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# 5. Warframe Synergy, DamageTriggerMode (ai / assumed / off), Combat Discipline
# ---------------------------------------------------------------------------


def test_warframe_synergy_shards_abilities_dedup_and_damage_trigger_modes():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    bulwark = ARCANES_BY_EN["Primary Bulwark"]["path"]
    avenger_path = WF_ARCANES_BY_EN["Arcane Avenger"]["path"]
    guardian_path = WF_ARCANES_BY_EN["Arcane Guardian"]["path"]
    combat_disc = WF_MODS_BY_EN["Combat Discipline"]["path"]
    rifle_amp = WF_MODS_BY_EN["Rifle Amp"]["path"]
    coaction = WF_MODS_BY_EN["Coaction Drift"]["path"]
    blind_rage = WF_MODS_BY_EN["Blind Rage"]["path"]

    def run_mode(mode: str, extra_buffs=None):
        return app.simulate_manual_payload({
            "weapon": boltor["path"],
            "mods": [],
            "arcanes": [{"path": bulwark, "rank": 5}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 170,
            "steelPath": True,
            "triggerPolicy": "emergent",
            "externalBuffs": extra_buffs or [],
            "warframeLink": {
                "enabled": True,
                "damageTriggerMode": mode,
                "activeAbilities": ["roar"],
                "config": {
                    "frameId": RHINO,
                    "aura": {"path": rifle_amp, "rank": 5},
                    "normalMods": [
                        {"path": coaction, "rank": 5, "slot": 0},
                        {"path": blind_rage, "rank": 10, "slot": 1},
                    ],
                    "arcanes": [
                        {"path": avenger_path, "rank": 5},
                        {"path": guardian_path, "rank": 5},
                    ],
                    "shards": [
                        {"path": _shard_path("ArchonCrystalUpgradeWarframeElectricDamage", tau=True), "tau": True},
                        {"path": _shard_path("ArchonCrystalUpgradePrimaryStatusChance", tau=True), "tau": True},
                    ],
                },
            },
        })

    off_res = run_mode("off")
    ai_res = run_mode("ai")
    assumed_res = run_mode("assumed")

    # Off < AI < Assumed for both Arcane Avenger crit chance and Arcane Guardian -> Primary Bulwark base damage!
    cc_off = off_res["moddedStats"]["critChance"]
    cc_ai = ai_res["moddedStats"]["critChance"]
    cc_assumed = assumed_res["moddedStats"]["critChance"]
    assert cc_off < cc_ai < cc_assumed
    assert cc_assumed - cc_off == pytest.approx(0.45)

    dmg_off = off_res["moddedStats"]["totalDamage"]
    dmg_ai = ai_res["moddedStats"]["totalDamage"]
    dmg_assumed = assumed_res["moddedStats"]["totalDamage"]
    assert dmg_off < dmg_ai < dmg_assumed

    # Deduplication: checking Rifle Amp and weaker Roar in manual externalBuffs must NOT double-stack!
    dedup_res = run_mode("assumed", extra_buffs=[{"id": "rifle-amp", "count": 1}, {"id": "roar-helminth", "strength": 1.0}])
    assert dedup_res["moddedStats"]["totalDamage"] == pytest.approx(dmg_assumed, rel=1e-4)

    # Combat Discipline self-damage on kill triggers Arcane Avenger in 1D Replay even when enemy hit rate is 0 (distance=500m)!
    cd_replay = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [{"path": MODS_BY_EN["Serration"]["path"], "rank": 10, "slot": 0}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 1,
        "distance": 200.0,
        "windowSeconds": 10.0,
        "triggerPolicy": "emergent",
        "warframeLink": {
            "enabled": True,
            "damageTriggerMode": "ai",
            "config": {
                "frameId": RHINO,
                "aura": {"path": combat_disc, "rank": 5},
                "arcanes": [{"path": avenger_path, "rank": 5}],
            },
        },
    })
    av_series = [
        s for s in cd_replay["benchmarkTimeline"]["triggerSeries"]
        if "CritChanceOnDamage" in str(s.get("id") or "")
    ]
    assert av_series and max(av_series[0]["series"]) > 0.0


def test_exalted_blade_receives_shards_invigoration_and_gladiator_set_from_warframe():
    glad_might = WF_MODS_BY_EN["Gladiator Resolve"]["path"]
    melee_invig = next(
        i["path"] for i in app.WARFRAME_ENGINE.invigoration if i["path"].endswith("/OffensiveInvigorationMeleeDamage")
    )
    plain = app.simulate_manual_payload({"weapon": EXALTED_BLADE, "mods": [], "enemy": app._BENCHMARK_ENEMY_PATH})
    linked = app.simulate_manual_payload({
        "weapon": EXALTED_BLADE,
        "mods": [],
        "comboTier": 11,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": {
            "enabled": True,
            "config": {
                "frameId": EXCALIBUR,
                "normalMods": [{"path": glad_might, "rank": 5, "slot": 0}],
                "shards": [{"path": _shard_path("ArchonCrystalUpgradeMeleeCritDamage", tau=True), "tau": True}],
                "invigoration": [melee_invig],
            },
        },
    })
    assert linked["moddedStats"]["totalDamage"] == pytest.approx(plain["moddedStats"]["totalDamage"] * 3.5)
    assert linked["moddedStats"]["critMultiplier"] > plain["moddedStats"]["critMultiplier"]
    assert linked["moddedStats"]["critChance"] > plain["moddedStats"]["critChance"]
    assert linked["synergySummary"]["externalSetPieceCounts"]["GladiatorSetMod"] == 1


# ---------------------------------------------------------------------------
# 6. Companion Synergy: Two-Pass Hunter Synergy -> Tenacious Bond, Beast No-Attack,
#    Dynamic Reinforced Bond Reloads, and Robotic Priming + Assister
# ---------------------------------------------------------------------------


def test_beast_two_pass_hunter_synergy_tenacious_bond_and_zero_active_attacks():
    rubico = WEAPONS_BY_EN["Rubico Prime"]
    crit_delay = MODS_BY_EN["Critical Delay"]["path"]

    comp_link = {
        "enabled": True,
        "companion": {
            "path": ADARZA_KAVAT,
            "mods": [{"path": TENACIOUS_BOND, "rank": 5, "slot": 0}],
        },
        "weapon": {
            "path": ADARZA_CLAWS,
            "mods": [{"path": HUNTER_SYNERGY, "rank": 5, "slot": 0}],
        },
    }

    # Pass 1 without Critical Delay: Rubico base CC 38% * 0.30 = +11.4% -> Adarza Claws 30% + 11.4% = 41.4% (< 50%) -> NO Tenacious Bond!
    unmodded = app.simulate_manual_payload({
        "weapon": rubico["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "companionLink": comp_link,
    })
    assert unmodded["synergySummary"]["companion"]["tenaciousBond"]["active"] is False
    assert unmodded["moddedStats"]["critMultiplier"] == pytest.approx(3.0, abs=1e-3)
    # Beast must never emit active priming or attacks!
    assert unmodded["synergySummary"]["companion"]["attackProfile"]["canAttack"] is False
    assert unmodded["synergySummary"]["primingStacks"] == {}

    # With Critical Delay (+200% CC -> Rubico 114% CC * 0.30 = +34.2% -> Adarza Claws 64.2% > 50%!) -> Tenacious Bond (+1.2x final CD)!
    modded = app.simulate_manual_payload({
        "weapon": rubico["path"],
        "mods": [{"path": crit_delay, "rank": 5, "slot": 0}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "companionLink": comp_link,
    })
    assert modded["synergySummary"]["companion"]["tenaciousBond"]["active"] is True
    assert modded["moddedStats"]["critMultiplier"] == pytest.approx(
        unmodded["moddedStats"]["critMultiplier"] + 1.2, rel=1e-5
    )


def test_dynamic_reinforced_bond_activates_after_reload_overshields_in_replay():
    # Wyrm Prime rank-30 shield is < 1200 without Calculated Redirection; reloads grant +150 overshields each until >= 1200!
    rubico = WEAPONS_BY_EN["Rubico Prime"]
    comp_link = {
        "enabled": True,
        "companion": {
            "path": WYRM_PRIME,
            "mods": [{"path": REINFORCED_BOND, "rank": 5, "slot": 0}],
        },
    }
    res = app.simulate_manual_payload({
        "weapon": rubico["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 170,
        "steelPath": True,
        "windowSeconds": 25.0,
        "triggerPolicy": "emergent",
        "companionLink": comp_link,
    })
    rb_info = res["synergySummary"]["companion"]["reinforcedBond"]
    assert rb_info["equipped"] is True and rb_info["staticActive"] is False
    assert rb_info["reloadsNeededForThreshold"] >= 1
    # Static panel does NOT get +60% fire rate prematurely, while 1D replay activates __reinforcedBond after enough reloads!
    plain = app.simulate_manual_payload({
        "weapon": rubico["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 170,
        "steelPath": True,
        "windowSeconds": 25.0,
        "triggerPolicy": "emergent",
    })
    assert res["moddedStats"]["fireRate"] == pytest.approx(plain["moddedStats"]["fireRate"])
    rb_series = [s for s in res["benchmarkTimeline"]["triggerSeries"] if s.get("id") == "__reinforcedBond"]
    assert rb_series and max(rb_series[0]["series"]) == pytest.approx(1.0)
    assert res["benchmarkTimeline"]["shots"] > plain["benchmarkTimeline"]["shots"]


def test_robotic_verglas_priming_feeds_frostbite_shiver_flare_and_replay_assister():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    lex = WEAPONS_BY_EN["Lex Prime"]
    frostbite = ARCANES_BY_EN["Primary Frostbite"]["path"]
    shiver = ARCANES_BY_EN["Secondary Shiver"]["path"]
    flare = ARCANES_BY_EN["Cascadia Flare"]["path"]
    blight = ARCANES_BY_EN["Primary Blight"]["path"]
    thermite = MODS_BY_EN["Thermite Rounds"]["path"]
    malignant = MODS_BY_EN["Malignant Force"]["path"]
    rime = MODS_BY_EN["Rime Rounds"]["path"]
    split_chamber = MODS_BY_EN["Split Chamber"]["path"]

    # Verglas Prime has innate Cold; adding Thermite Rounds creates Blast unless ordered:
    # Rime Rounds (Cold) alone keeps pure Cold; Malignant + Thermite makes Gas + innate Cold -> Cold + Gas!
    cold_heat_verglas = {
        "enabled": True,
        "companion": {
            "path": DIRIGA,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": ARC_COIL, "rank": 5, "slot": 1},
                {"path": MANIFOLD_BOND, "rank": 5, "slot": 2},
            ],
        },
        "weapon": {
            "path": VERGLAS_PRIME,
            "mods": [
                {"path": rime, "rank": 3, "slot": 0},
                {"path": split_chamber, "rank": 5, "slot": 1},
            ],
        },
    }

    # 1) Primary Frostbite + Blight on pure-physical Boltor Prime with Cold-priming Verglas:
    #    Frostbite stacks on BOTH Panel and 1D Replay, while Primary Blight stays at 0!
    plain_boltor = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "arcanes": [{"path": frostbite, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 10.0,
        "triggerPolicy": "emergent",
    })
    linked_boltor = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "arcanes": [{"path": frostbite, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 10.0,
        "triggerPolicy": "emergent",
        "companionLink": cold_heat_verglas,
    })
    assert linked_boltor["moddedStats"]["multishot"] > plain_boltor["moddedStats"]["multishot"]
    assert linked_boltor["moddedStats"]["critMultiplier"] > plain_boltor["moddedStats"]["critMultiplier"]
    fb_series = [s for s in linked_boltor["benchmarkTimeline"]["triggerSeries"] if "PrimaryCritDmgAndMultishotOnColdProc" in str(s.get("id") or "")]
    assert fb_series and max(fb_series[0]["series"]) > 10.0

    # Verify Toxin companion weapon does NOT trigger player-only Primary Blight in replay!
    vulklok_toxin = {
        "enabled": True,
        "companion": {"path": DIRIGA, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        "weapon": {
            "path": "/Lotus/Types/Sentinels/SentinelWeapons/LaserRifle",
            "mods": [{"path": malignant, "rank": 3, "slot": 0}],
        },
    }
    blight_check = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "arcanes": [{"path": blight, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 8.0,
        "triggerPolicy": "emergent",
        "companionLink": vulklok_toxin,
    })
    blight_series = [s for s in blight_check["benchmarkTimeline"]["triggerSeries"] if "Blight" in str(s.get("id") or "") or "Toxin" in str(s.get("id") or "")]
    if blight_series:
        assert max(blight_series[0]["series"]) == pytest.approx(0.0)

    # 2) Secondary Shiver on Lex Prime reflects primedColdStacks on Panel + live Cold in Replay!
    shiver_lex = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "arcanes": [{"path": shiver, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 8.0,
        "triggerPolicy": "emergent",
        "companionLink": cold_heat_verglas,
    })
    plain_lex = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "arcanes": [{"path": shiver, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 8.0,
        "triggerPolicy": "emergent",
    })
    assert shiver_lex["moddedStats"]["totalDamage"] > plain_lex["moddedStats"]["totalDamage"] * 3.0
    assert shiver_lex["benchmarkTimeline"]["windowDps"] > plain_lex["benchmarkTimeline"]["windowDps"] * 2.0

    # 3) Cascadia Flare on Lex Prime with Heat Deth Machine Rifle Prime companion!
    heat_laser = {
        "enabled": True,
        "companion": {"path": DIRIGA, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        "weapon": {
            "path": "/Lotus/Types/Sentinels/SentinelWeapons/PrimeDethMachineRifle",
            "mods": [{"path": thermite, "rank": 3, "slot": 0}, {"path": split_chamber, "rank": 5, "slot": 1}],
        },
    }
    flare_lex = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "arcanes": [{"path": flare, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 10.0,
        "triggerPolicy": "emergent",
        "companionLink": heat_laser,
    })
    plain_flare = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "arcanes": [{"path": flare, "rank": 5}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
        "windowSeconds": 10.0,
        "triggerPolicy": "emergent",
    })
    assert flare_lex["moddedStats"]["totalDamage"] > plain_flare["moddedStats"]["totalDamage"]
    flare_series = [s for s in flare_lex["benchmarkTimeline"]["triggerSeries"] if "SecondaryDamageOnHeatProc" in str(s.get("id") or "")]
    assert flare_series and max(flare_series[0]["series"]) > 3.0


# ---------------------------------------------------------------------------
# 7. HTTP Endpoints (/api/companion/*, /api/build, /api/analyze cacheable=False)
#    and Arena Catalog / _arena_context Contracts
# ---------------------------------------------------------------------------


def test_http_companion_endpoints_build_analyze_cache_gate_and_arena_context():
    server = app.create_server("127.0.0.1", 0)
    host, port = server.server_address[:2]
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection(host, port, timeout=30)

        # 1) GET /api/companion/catalog
        conn.request("GET", "/api/companion/catalog")
        resp = conn.getresponse()
        cat_body = json.loads(resp.read().decode("utf-8"))
        assert resp.status == 200
        assert len(cat_body["companions"]) == 41
        assert len(cat_body["companionWeapons"]) > 15
        assert all(w["slot"] == "companion" for w in cat_body["companionWeapons"])

        # 2) POST /api/companion/evaluate with linked Warframe + Primary weapon (Hunter Synergy -> Tenacious Bond)
        rubico = WEAPONS_BY_EN["Rubico Prime"]
        crit_delay = MODS_BY_EN["Critical Delay"]["path"]
        eval_req = {
            "companion": {
                "path": ADARZA_KAVAT,
                "mods": [
                    {"path": TENACIOUS_BOND, "rank": 5, "slot": 0},
                    {"path": LINK_REDIRECTION, "rank": 10, "slot": 1},
                ],
            },
            "weapon": {
                "path": ADARZA_CLAWS,
                "mods": [{"path": HUNTER_SYNERGY, "rank": 5, "slot": 0}],
            },
            "warframeLink": {"enabled": True, "config": {"frameId": RHINO}},
            "primaryWeapon": {
                "weapon": rubico["path"],
                "mods": [{"path": crit_delay, "rank": 5, "slot": 0}],
            },
        }
        conn.request(
            "POST",
            "/api/companion/evaluate",
            body=json.dumps(eval_req).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp2 = conn.getresponse()
        eval_body = json.loads(resp2.read().decode("utf-8"))
        assert resp2.status == 200
        assert eval_body["playerBridge"]["tenaciousBond"]["active"] is True
        assert eval_body["stats"]["shield"]["modded"] > 400.0  # Link Redirection from Rhino!
        assert eval_body["stats"]["shield"]["linkBonus"] > 300.0
        conn.close()
    finally:
        server.shutdown()
        server.server_close()

    # 3) /api/build with Warframe + Companion link returns synergySummary & boosts score
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    build_plain = app.build_weapon_payload({"weapon": boltor["path"], "profile": "fast", "maxFill": 2})
    build_linked = app.build_weapon_payload({
        "weapon": boltor["path"],
        "profile": "fast",
        "maxFill": 2,
        "warframeLink": {
            "enabled": True,
            "activeAbilities": ["roar"],
            "config": {"frameId": RHINO},
        },
        "companionLink": {
            "enabled": True,
            "companion": {"path": NAUTILUS_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
            "weapon": {
                "path": VERGLAS_PRIME,
                "mods": [
                    {"path": "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteArmamentsMod", "rank": 5, "slot": 0},
                    {"path": "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteFervorMod", "rank": 5, "slot": 1},
                ],
            },
        },
    })
    assert "synergySummary" in build_linked
    assert build_linked["build"]["objectiveScore"] > build_plain["build"]["objectiveScore"]

    # 4) /api/analyze (optimizer.analyze_riven_request) strictly sets cacheable = False when linked!
    fake_cache: dict = {}
    analyze_res = optimizer.analyze_riven_request(
        app.EXPORT_DIR,
        {
            "weapon": boltor["path"],
            "profile": "ultra",
            "disposition": float(boltor.get("omegaAttenuation") or 1.2),
            "stats": [
                {"code": "D", "value": 150.0, "negative": False},
                {"code": "S", "value": 90.0, "negative": False},
            ],
            "warframeLink": {"enabled": True, "activeAbilities": ["roar"], "config": {"frameId": RHINO}},
        },
        statics_cache=fake_cache,
    )
    assert fake_cache == {}  # Strictly uncached when warframeLink/companionLink is enabled!
    assert analyze_res["synergySummary"]["warframe"]["frame"]["id"] == RHINO

    # 5) Arena Catalog & _arena_context contract
    arena_cat = app.arena_catalog_payload()
    assert arena_cat["defaultWarframePortrait"] == "/assets/warframes/portraits/Excalibur.png"
    assert all("imageAsset" in e and "imageStatus" in e for e in arena_cat["enemies"])

    neutral_arena = app._arena_context({
        "scenario": {"enemy": app._BENCHMARK_ENEMY_PATH, "level": 140},
        "loadout": {"weapon": boltor["path"], "mods": []},
    })
    assert neutral_arena["warframeContext"] is None
    assert neutral_arena["companionContext"] is None
    assert isinstance(neutral_arena["enemyVisuals"], dict) and len(neutral_arena["enemyVisuals"]) > 0

    linked_arena = app._arena_context({
        "scenario": {"enemy": app._BENCHMARK_ENEMY_PATH, "level": 140},
        "loadout": {
            "weapon": boltor["path"],
            "mods": [],
            "warframeLink": {
                "enabled": True,
                "activeAbilities": ["roar"],
                "config": {"frameId": RHINO},
            },
            "companionLink": {
                "enabled": True,
                "companion": {"path": NAUTILUS_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
                "weapon": {"path": VERGLAS_PRIME, "mods": []},
            },
        },
    })
    assert linked_arena["warframeContext"] is not None
    assert linked_arena["warframeContext"]["activeAbilities"] == ["roar"]
    assert linked_arena["warframeContext"]["immortalBenchmark"] is True
    assert linked_arena["companionContext"] is not None
    assert linked_arena["companionContext"]["evaluation"]["companion"]["path"] == NAUTILUS_PRIME
    assert linked_arena["companionContext"]["weaponRecord"]["path"] == VERGLAS_PRIME
    assert isinstance(linked_arena["companionContext"]["weaponModRecords"], list)
    assert isinstance(linked_arena["companionContext"]["weaponSimOptions"], dict)


def test_topaz_violet_shards_and_mod_gains_part_values_recommend_synergy():
    lex = WEAPONS_BY_EN["Lex Prime"]
    nikana = WEAPONS_BY_EN["Nikana Prime"]
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    thermite = MODS_BY_EN["Thermite Rounds"]["path"]
    serration = MODS_BY_EN["Serration"]["path"]
    split_chamber = MODS_BY_EN["Split Chamber"]["path"]
    primed_flow = WF_MODS_BY_EN["Primed Flow"]["path"]
    volt_prime = "/Lotus/Powersuits/Volt/VoltPrime"

    # 1) Topaz Secondary CC Shard: inactive without Heat, active when linked Robotic Companion primes Heat!
    topaz_shard = {"path": _shard_path("ArchonCrystalUpgradeWeaponCritBoostFromHeat", tau=True), "tau": True}
    lex_no_heat = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": {
            "enabled": True,
            "config": {"frameId": RHINO, "shards": [topaz_shard]},
        },
    })
    lex_comp_heat = app.simulate_manual_payload({
        "weapon": lex["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": {
            "enabled": True,
            "config": {"frameId": RHINO, "shards": [topaz_shard]},
        },
        "companionLink": {
            "enabled": True,
            "companion": {"path": DIRIGA, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
            "weapon": {
                "path": "/Lotus/Types/Sentinels/SentinelWeapons/PrimeDethMachineRifle",
                "mods": [{"path": thermite, "rank": 3, "slot": 0}],
            },
        },
    })
    assert lex_comp_heat["moddedStats"]["critChance"] > lex_no_heat["moddedStats"]["critChance"]

    # 2) Violet Melee Crit Damage Shard: doubles when Warframe energy > 500!
    violet_cd = {"path": _shard_path("ArchonCrystalUpgradeWarframeCritDamageBoost", tau=True), "tau": True}
    nik_base = app.simulate_manual_payload({"weapon": nikana["path"], "mods": [], "enemy": app._BENCHMARK_ENEMY_PATH})
    nik_low_e = app.simulate_manual_payload({
        "weapon": nikana["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": {"enabled": True, "config": {"frameId": RHINO, "shards": [violet_cd]}},
    })
    nik_high_e = app.simulate_manual_payload({
        "weapon": nikana["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": {
            "enabled": True,
            "config": {
                "frameId": volt_prime,
                "normalMods": [{"path": primed_flow, "rank": 10, "slot": 0}],
                "shards": [violet_cd],
            },
        },
    })
    gain_low = nik_low_e["moddedStats"]["critMultiplier"] - nik_base["moddedStats"]["critMultiplier"]
    gain_high = nik_high_e["moddedStats"]["critMultiplier"] - nik_base["moddedStats"]["critMultiplier"]
    assert gain_low > 0.0
    assert gain_high == pytest.approx(gain_low * 2.0, rel=1e-4)

    # 3) mod_gains_payload, part_values_payload, and recommend_riven_payload respect warframeLink & companionLink!
    wf_link = {"enabled": True, "activeAbilities": ["roar"], "config": {"frameId": RHINO}}
    comp_link = {
        "enabled": True,
        "companion": {"path": NAUTILUS_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        "weapon": {"path": VERGLAS_PRIME, "mods": []},
    }
    gains_res = app.mod_gains_payload({
        "weapon": boltor["path"],
        "mods": [],
        "candidates": [serration],
        "targetSlot": 0,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": wf_link,
        "companionLink": comp_link,
    })
    assert gains_res["gains"][serration]["gainPercent"] > 50.0

    parts_res = app.part_values_payload({
        "weapon": boltor["path"],
        "mods": [
            {"path": serration, "rank": 10, "slot": 0},
            {"path": split_chamber, "rank": 5, "slot": 1},
        ],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "warframeLink": wf_link,
        "companionLink": comp_link,
    })
    assert parts_res["fullValue"] > parts_res["emptyValue"] * 2.0

    rec_res = app.recommend_riven_payload({
        "weapon": boltor["path"],
        "mods": [
            {"path": serration, "rank": 10, "slot": 0},
            {"path": split_chamber, "rank": 5, "slot": 1},
        ],
        "budgetSeconds": 10,
        "topLimit": 3,
        "warframeLink": wf_link,
        "companionLink": comp_link,
    })
    assert rec_res["synergySummary"]["warframe"]["frame"]["id"] == RHINO
    assert len(rec_res["combos"]) >= 1


def test_native_synergy_replay_shadow_parity_and_health_batch(monkeypatch):
    assert getattr(native_replay.wfcore, "NATIVE_SYNERGY_REPLAY", 0) >= 1
    monkeypatch.setattr(native_replay, "SHADOW", True)

    from wfarsenal import manual_combat

    boltor = WEAPONS_BY_EN["Boltor Prime"]
    frostbite = ARCANES_BY_EN["Primary Frostbite"]
    avenger_wf = WF_ARCANES_BY_EN["Arcane Avenger"]
    avenger_rec = next(a for a in app.EXPORTS["arcanes"] if a.get("path") == avenger_wf["path"])
    fortifier_rec = ARCANES_BY_EN["Secondary Fortifier"]

    corrupted_hg = next(
        e for e in app.EXPORTS["enemies"] if e.get("path") == "/Lotus/Types/Enemies/Orokin/OrokinHeavyFemaleAvatar"
    )
    thrax = next(e for e in app.EXPORTS["enemies"] if e.get("path") == app._BENCHMARK_ENEMY_PATH)

    # 1) Combined companionAssister + reinforcedBondReloads + selfDamageOnKill on native fast path (collect_timeline=False, SHADOW=1)
    assister_spec = {
        "weaponPath": VERGLAS_PRIME,
        "interval": 0.12,
        "fireRate": 12.0,
        "dutyCycle": 0.85,
        "cloneMultiplier": 1,
        "magazine": 8.0,
        "reloadTime": 1.2,
        "continuous": True,
        "multishot": 2.3,
        "critChance": 0.40,
        "critMultiplier": 2.4,
        "noncritDamageMultiplier": 1.0,
        "doubleCritChance": 0.10,
        "statusChance": 0.85,
        "damageTypes": {"DT_FREEZE": 45.0, "DT_FIRE": 35.0, "DT_POISON": 20.0},
        "dotBaseDamage": None,
        "procsPerShot": {"DT_FREEZE": 0.95, "DT_FIRE": 0.65, "DT_POISON": 0.35},
        "procDurationMultiplier": 1.0,
        "procDamageMultiplier": 1.0,
        "dotElementalMultipliers": {},
        "factionDamageMultipliers": {},
        "armorStripOnHit": 0.15,
        "shiveringContagion": False,
        "manifoldPrecepts": [
            {
                "id": "ArcTrap",
                "cooldown": 3.0,
                "killCooldownReduction": 3.0,
                "damage": 250.0,
                "damageType": "DT_ELECTRICITY",
                "procs": {"DT_ELECTRICITY": 1.0, "DT_FREEZE": 1.0, "DT_VIRAL": 1.0},
            }
        ],
    }
    combat_extras = {
        "companionAssister": assister_spec,
        "reinforcedBondReloads": {"reloadsNeeded": 1, "fireRateBonus": 0.60},
        "selfDamageOnKill": 10.0,
    }
    scen = damage.Scenario(
        trigger_policy="emergent",
        combat_state={"selfDamageOnKill": 10.0},
    )
    serration_rec = MODS_BY_EN["Serration"]
    galv_apt_rec = MODS_BY_EN["Galvanized Aptitude"]
    base_effects = [
        *optimizer._mod_card(serration_rec, scen, allow_empty=True, rank=10).effects,
        *optimizer._mod_card(galv_apt_rec, scen, allow_empty=True, rank=10).effects,
    ]
    engine_ctx = {
        "weapon": boltor,
        "fire_mode": 0,
        "scenario": scen,
        "effects": base_effects,
        "combat_extras": combat_extras,
    }
    mod_tuples = [(serration_rec, 10, None), (galv_apt_rec, 10, None)]
    arc_tuples = [(frostbite, 5, None), (avenger_rec, 5, None), (fortifier_rec, 5, None)]

    combat_cfg = manual_combat.prepare(
        engine_ctx,
        mod_tuples,
        arc_tuples,
        cycle_enabled=False,
        assumed=False,
        incarnon_choices=None,
        affinity_target=corrupted_hg,
        level=120,
        eximus=False,
    )
    st_initial, _ = combat_cfg["resolve"]("selected", {q["id"]: q.get("initialStacks", 0.0) for q in combat_cfg["trigger_sources"]}, 0)

    before_native = native_replay.STATS["native"]
    before_fallback = native_replay.STATS["fallback"]

    for target_enemy, lvl in ((corrupted_hg, 110), (thrax, 120)):
        rep = combat_replay.replay(
            st_initial,
            target_enemy,
            attacks_per_second=st_initial.fire_rate,
            window_seconds=12.0,
            level=lvl,
            steel_path=True,
            trigger_sources=combat_cfg["trigger_sources"],
            collect_timeline=False,
            combat=combat_cfg,
        )
        assert rep["killsPerMinute"] > 0.0
        assert rep["reloads"] >= 1

    # 2) primingStacks (without companionAssister) on native fast path across kills & Overguard/Freeze caps
    priming_combat = manual_combat.prepare(
        {**engine_ctx, "combat_extras": {"reinforcedBondReloads": {"reloadsNeeded": 1, "fireRateBonus": 0.60}, "selfDamageOnKill": 10.0}},
        mod_tuples,
        [(avenger_rec, 5, None)],
        cycle_enabled=False,
        assumed=False,
        incarnon_choices=None,
        affinity_target=corrupted_hg,
        level=110,
        eximus=False,
    )
    st_primed, _ = priming_combat["resolve"]("selected", {q["id"]: q.get("initialStacks", 0.0) for q in priming_combat["trigger_sources"]}, 0)
    priming_enh = {
        "primingStacks": {
            "DT_VIRAL": 10.0,
            "DT_CORROSIVE": 10.0,
            "DT_MAGNETIC": 10.0,
            "DT_FREEZE": 10.0,
            "DT_PUNCTURE": 5.0,
            "DT_ELECTRICITY": 3.0,
        }
    }
    for target_enemy, lvl in ((corrupted_hg, 110), (thrax, 120)):
        rep_p = combat_replay.replay(
            st_primed,
            target_enemy,
            attacks_per_second=st_primed.fire_rate,
            window_seconds=10.0,
            level=lvl,
            steel_path=True,
            enemy_enhancements=priming_enh,
            trigger_sources=priming_combat["trigger_sources"],
            collect_timeline=False,
            combat=priming_combat,
        )
        assert rep_p["killsPerMinute"] > 0.0

    assert native_replay.STATS["native"] >= before_native + 4
    assert native_replay.STATS["fallback"] == before_fallback

    # 3) Verify trajectory_health_batch (fork_with_caches) resets companion, RB reloads, and primingStacks across targets
    import copy as _copy

    scales = [{"healthScale": 0.5, **priming_enh}, {"healthScale": 1.0, **priming_enh}, {"healthScale": 2.5, **priming_enh}]
    batch_primed = native_replay.trajectory(
        st_primed,
        corrupted_hg,
        attacks_per_second=st_primed.fire_rate,
        window_seconds=10.0,
        level=110,
        steel_path=True,
        enemy_enhancements=scales[0],
        trigger_sources=_copy.deepcopy(priming_combat["trigger_sources"]),
        collect_timeline=False,
        score_only=True,
        combat=dict(priming_combat),
        health_targets=scales,
    )
    assert batch_primed is not None and len(batch_primed) == 3
    for enh_item, got_row in zip(scales, batch_primed):
        ref_row = combat_replay._reference_trajectory(
            st_primed,
            corrupted_hg,
            attacks_per_second=st_primed.fire_rate,
            window_seconds=10.0,
            level=110,
            steel_path=True,
            enemy_enhancements=enh_item,
            trigger_sources=_copy.deepcopy(priming_combat["trigger_sources"]),
            collect_timeline=False,
            combat=dict(priming_combat),
        )
        assert got_row["killsPerMinute"] == ref_row["killsPerMinute"]
        assert got_row["totalWindowDamage"] == ref_row["totalWindowDamage"]

    comp_scales = [{"healthScale": 0.5}, {"healthScale": 1.0}, {"healthScale": 2.5}]
    batch_comp = native_replay.trajectory(
        st_initial,
        corrupted_hg,
        attacks_per_second=st_initial.fire_rate,
        window_seconds=12.0,
        level=110,
        steel_path=True,
        enemy_enhancements=comp_scales[0],
        trigger_sources=_copy.deepcopy(combat_cfg["trigger_sources"]),
        collect_timeline=False,
        score_only=True,
        combat=dict(combat_cfg),
        health_targets=comp_scales,
    )
    assert batch_comp is not None and len(batch_comp) == 3
    for enh_item, got_row in zip(comp_scales, batch_comp):
        ref_row = combat_replay._reference_trajectory(
            st_initial,
            corrupted_hg,
            attacks_per_second=st_initial.fire_rate,
            window_seconds=12.0,
            level=110,
            steel_path=True,
            enemy_enhancements=enh_item,
            trigger_sources=_copy.deepcopy(combat_cfg["trigger_sources"]),
            collect_timeline=False,
            combat=dict(combat_cfg),
        )
        assert got_row["killsPerMinute"] == ref_row["killsPerMinute"]
        assert got_row["totalWindowDamage"] == ref_row["totalWindowDamage"]


def test_warframe_link_shields_manual_weapon_page_warframe_arcanes():
    boltor = WEAPONS_BY_EN["Boltor Prime"]
    merciless = ARCANES_BY_EN["Primary Merciless"]["path"]
    accel = ARCANES_BY_EN["Arcane Acceleration"]["path"]
    rage = ARCANES_BY_EN["Arcane Rage"]["path"]

    wf_empty = {
        "enabled": True,
        "frameId": "Excalibur",
        "configName": "A",
        "config": {"arcanes": []},
        "damageTriggerMode": "assumed",
    }

    sim_clean = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [{"path": merciless, "rank": 5, "forceProc": True}],
        "warframeLink": wf_empty,
    })
    sim_stale_manual_wf_arcanes = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [
            {"path": merciless, "rank": 5, "forceProc": True},
            {"path": accel, "rank": 5, "forceProc": True},
            {"path": rage, "rank": 5, "forceProc": True},
        ],
        "warframeLink": wf_empty,
    })
    # Manual Warframe arcanes must be shielded when warframeLink is enabled, while Primary Merciless stays active.
    assert sim_stale_manual_wf_arcanes["moddedStats"]["fireRate"] == pytest.approx(
        sim_clean["moddedStats"]["fireRate"]
    )
    assert sim_stale_manual_wf_arcanes["moddedStats"]["totalDamage"] == pytest.approx(
        sim_clean["moddedStats"]["totalDamage"]
    )
    assert sim_stale_manual_wf_arcanes["benchmarkTimeline"]["windowDps"] == pytest.approx(
        sim_clean["benchmarkTimeline"]["windowDps"]
    )

    # Optimizer (/api/build) also strips stale manual Warframe arcanes when warframeLink is enabled.
    build_clean = app.build_weapon_payload({
        "weapon": boltor["path"],
        "profile": "fast",
        "maxFill": 1,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [{"path": merciless, "rank": 5, "forceProc": True}],
        "warframeLink": wf_empty,
    })
    build_stale = app.build_weapon_payload({
        "weapon": boltor["path"],
        "profile": "fast",
        "maxFill": 1,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [
            {"path": merciless, "rank": 5, "forceProc": True},
            {"path": accel, "rank": 5, "forceProc": True},
        ],
        "warframeLink": wf_empty,
    })
    assert build_stale["build"]["objectiveScore"] == pytest.approx(build_clean["build"]["objectiveScore"])

    # When ONLY companionLink is enabled (warframeLink disabled), weapon-page Warframe arcanes stay active!
    comp_only = {
        "enabled": True,
        "companionId": NAUTILUS_PRIME,
        "configName": "A",
        "weaponConfigName": "A",
        "config": {
            "companion": {"path": NAUTILUS_PRIME, "reactor": True, "mods": []},
            "weapon": None,
        },
    }
    sim_comp_no_wf_arc = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [{"path": merciless, "rank": 5, "forceProc": True}],
        "companionLink": comp_only,
    })
    sim_comp_with_wf_arc = app.simulate_manual_payload({
        "weapon": boltor["path"],
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "arcanes": [
            {"path": merciless, "rank": 5, "forceProc": True},
            {"path": accel, "rank": 5, "forceProc": True},
        ],
        "companionLink": comp_only,
    })
    assert sim_comp_with_wf_arc["moddedStats"]["fireRate"] > sim_comp_no_wf_arc["moddedStats"]["fireRate"] * 1.5


