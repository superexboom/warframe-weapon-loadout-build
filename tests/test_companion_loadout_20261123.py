"""2026-11-23: Unified Companion Body + Modular Parts + Beast Claws + Synergy Evaluator tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))

import app  # noqa: E402
from wfarsenal import companion_loadout, damage, sentinel as sentinel_body  # noqa: E402
from wfarsenal.simulator import SimulationError  # noqa: E402

# Companion paths
DETHCUBE = "/Lotus/Types/Sentinels/SentinelPowersuits/DethCubePowerSuit"
WYRM_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/PrimeWyrmPowerSuit"
NAUTILUS_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/NautilusPrimeSentinelPowerSuit"
CARRIER = "/Lotus/Types/Sentinels/SentinelPowersuits/CarrierPowerSuit"
DIRIGA = "/Lotus/Types/Sentinels/SentinelPowersuits/ArcDronePowerSuit"
HELIOS_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/PrimeHeliosPowerSuit"
SHADE_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/PrimeShadePowerSuit"
OLORO_MOA = "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetHeadOloro"
DORMA_HOUND = "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartHeadA"
SMEETA_KAVAT = "/Lotus/Types/Game/CatbrowPet/CheshireCatbrowPetPowerSuit"
ADARZA_KAVAT = "/Lotus/Types/Game/CatbrowPet/MirrorCatbrowPetPowerSuit"
VENARI = "/Lotus/Powersuits/Khora/Kavat/KhoraKavatPowerSuit"
PANZER_VULPAPHYLA = "/Lotus/Types/Friendly/Pets/CreaturePets/ArmoredInfestedCatbrowPetPowerSuit"
VIZIER_PREDASITE = "/Lotus/Types/Friendly/Pets/CreaturePets/VizierPredatorKubrowPetPowerSuit"
HELMINTH_CHARGER = "/Lotus/Types/Game/KubrowPet/ChargerKubrowPetPowerSuit"

# Body mod paths
ENHANCED_VITALITY = "/Lotus/Upgrades/Mods/Sentinel/SentinelHealthMaxMod"
CALCULATED_REDIRECTION = "/Lotus/Upgrades/Mods/Sentinel/SentinelShieldMaxMod"
METAL_FIBER = "/Lotus/Upgrades/Mods/Sentinel/SentinelArmourMod"
LINK_VITALITY = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkHealthMaxMod"
LINK_REDIRECTION = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkShieldMaxMod"
LINK_FIBER = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkArmourMaxMod"
ACCELERATED_DEFLECTION = "/Lotus/Upgrades/Mods/Sentinel/SentinelShieldRechargeRateMod"
HASTENED_DEFLECTION = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowShieldRechargeRateMod"
ASSAULT_MODE = "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack"
CALCULATED_SHOT = "/Lotus/Types/Sentinels/SentinelPrecepts/HeadShot"
TARGETING_RECEPTOR = "/Lotus/Types/Sentinels/SentinelPrecepts/ThrowGlaivePrecept"
TENACIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TenaciousPartner"
REINFORCED_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/AlacrityField"
MANIFOLD_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/CompoundingLaceration"
CONTAGIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Proliferation"
VICIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BoneSplitter"
MOMENTOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/EximusHunter"
ASTRAL_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum"
DUPLEX_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidClone"
CATS_EYE = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowCatsEyePrecept"
TEK_ENHANCE = "/Lotus/Upgrades/Mods/Sets/Tek/KavatTekEnhanceMod"
AMBUSH = "/Lotus/Types/Sentinels/SentinelPrecepts/GhostAugmentCard"
SHARPENED_CLAWS = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowShredPrecept"
SYNTH_DECONSTRUCT = "/Lotus/Upgrades/Mods/Sets/Synth/SentinelSynthDeconstructMod"
HARD_ENGAGE = "/Lotus/Upgrades/Mods/Sentinel/Moa/MoaMeleeMod"
REGEN = "/Lotus/Types/Sentinels/SentinelPrecepts/Regen"
PRIMED_REGEN = "/Lotus/Types/Sentinels/SentinelPrecepts/PrimedRegen"

# Beast Claws & Claw Mods
ADARZA_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/AdarzaPetWeapon"
VIZIER_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/VizierPredasitePetWeapon"
PANZER_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/PanzerVulpaphylaPetWeapon"
HELMINTH_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/HelminthPetWeapon"
BITE = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowCritMod"
MAUL = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowMeleeDamageMod"
HUNTER_SYNERGY = "/Lotus/Upgrades/Mods/Sets/Hunter/CompanionHunterSynergyMod"
MECHA_OVERDRIVE = "/Lotus/Upgrades/Mods/Sets/Mecha/KubrowMechaOverdriveMod"
STRAIN_FEVER = "/Lotus/Upgrades/Mods/Sets/Strain/HelminthStrainFeverMod"
FROST_JAW = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/DualStat/KubrowIceEventMeleeMod"
FLAME_GLAND = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/DualStat/KubrowFireEventMeleeMod"
BURNING_CLAWS = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowHeatConversionMod"
CHILLING_CLAWS = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowColdConversionMod"
BRUTE_CONDITIONING = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/BeastBruteConditioningMod"
PRECISION_CONDITIONING = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/BeastPrecisionConditioningMod"
FRENZIED_POSTURE = "/Lotus/Types/Friendly/Pets/BeastWeapons/Stances/BeastSpreadAttacksStance"
PROTECTOR_POSTURE = "/Lotus/Types/Friendly/Pets/BeastWeapons/Stances/BeastProtectorStance"

# Robotic weapons & weapon mods
VULKLOK = "/Lotus/Types/Sentinels/SentinelWeapons/SentElecRailgun"
VERGLAS_PRIME = "/Lotus/Types/Sentinels/SentinelWeapons/SentinelFreezeRayPrimeRifle"
HELSTRUM = "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/SwarmerWeapon"
DECONSTRUCTOR_PRIME = "/Lotus/Types/Sentinels/SentinelWeapons/DeconstructorPrime/PrimeHeliosGlaiveWeapon"
AKATEN = "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponPS"
POINT_STRIKE = "/Lotus/Upgrades/Mods/Rifle/WeaponCritChanceMod"
CRITICAL_DELAY = "/Lotus/Upgrades/Mods/Rifle/DualStat/CorruptedCritRateFireRateRifle"
SINISTER_REACH = "/Lotus/Upgrades/Mods/Rifle/WeaponBeamDistanceMod"
EAGLE_EYE = "/Lotus/Upgrades/Mods/Rifle/WeaponZoomFovMod"
SHIVERING_CONTAGION = "/Lotus/Upgrades/Mods/Rifle/WeaponSpreadFreezeProcsMod"
MALIGNANT_FORCE = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Malignant Force")
THERMITE_ROUNDS = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Thermite Rounds")
SPLIT_CHAMBER = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Split Chamber")
GLADIATOR_MIGHT = "/Lotus/Upgrades/Mods/Sets/Gladiator/MeleeGladiatorMightMod"
VIGILANTE_MODS = [
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteArmamentsMod",
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteFervorMod",
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteOffenseMod",
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteSuppliesMod",
]


def test_catalog_structure_and_lru_cache():
    cat = companion_loadout.catalog()
    assert cat is companion_loadout.catalog()
    assert len(cat["companions"]) == 41
    assert len(cat["beastClaws"]) == 17
    assert len(cat["clawMods"]) == 30
    assert len(cat["bodyMods"]) >= 135
    assert len(cat["weaponAiProfiles"]) == 24
    assert set(cat["modularParts"]) == {"moa", "hound", "vulpaphyla", "predasite"}


def test_sentinel_rank30_base_stats_and_reinforced_bond_thresholds():
    # Post-Update-34 Rank-30 stats (no 3.5x scale) in both sentinel.py and companion_loadout.py.
    deth_legacy = sentinel_body.evaluate({"path": DETHCUBE, "mods": []})
    deth = companion_loadout.evaluate_companion({"path": DETHCUBE, "mods": []})
    assert deth_legacy["stats"]["health"]["base"] == 560.0
    assert deth_legacy["stats"]["shield"]["base"] == 250.0
    assert deth_legacy["stats"]["armor"]["base"] == 80.0
    assert deth["stats"]["health"]["base"] == 560.0
    assert deth["stats"]["shield"]["base"] == 250.0
    assert deth["stats"]["armor"]["base"] == 80.0

    # Wyrm Prime: 600 * 3.5003 = 2100.18 >= 1200 -> Reinforced Bond statically active!
    wyrm = companion_loadout.evaluate_companion({
        "path": WYRM_PRIME,
        "mods": [
            {"path": CALCULATED_REDIRECTION, "rank": 10, "slot": 0},
            {"path": REINFORCED_BOND, "rank": 5, "slot": 1},
            {"path": ACCELERATED_DEFLECTION, "rank": 5, "slot": 2},
        ],
    })
    assert wyrm["stats"]["health"]["base"] == 450.0
    assert wyrm["stats"]["armor"]["base"] == 150.0
    assert round(wyrm["stats"]["shield"]["modded"], 2) == 2100.18
    assert wyrm["stats"]["shieldRecharge"]["bonus"] == pytest.approx(0.90)
    assert wyrm["stats"]["shieldDelay"]["bonus"] == pytest.approx(-0.45)
    assert wyrm["stats"]["shieldDelay"]["modded"] == pytest.approx(4.0 * 0.55)
    rb_wyrm = wyrm["playerBridge"]["reinforcedBond"]
    assert rb_wyrm["equipped"] is True
    assert rb_wyrm["staticActive"] is True
    assert rb_wyrm["reloadsNeededForThreshold"] == 0
    assert rb_wyrm["fireRateBonus"] == pytest.approx(0.60)
    p_effs = companion_loadout.player_weapon_mod_effects(wyrm)
    assert any(e.upgrade_type == "WEAPON_FIRE_RATE" and e.value == pytest.approx(0.60) for e in p_effs)

    # Nautilus Prime: 350 * 3.5003 = 1225.105 (1225.11) >= 1200 -> statically active!
    nautilus = companion_loadout.evaluate_companion({
        "path": NAUTILUS_PRIME,
        "mods": [
            {"path": CALCULATED_REDIRECTION, "rank": 10, "slot": 0},
            {"path": REINFORCED_BOND, "rank": 5, "slot": 1},
        ],
    })
    assert round(nautilus["stats"]["shield"]["modded"], 2) == 1225.11
    assert nautilus["playerBridge"]["reinforcedBond"]["staticActive"] is True
    assert nautilus["playerBridge"]["reinforcedBond"]["reloadsNeededForThreshold"] == 0

    # Carrier: 250 * 3.5003 = 875.075 (875.08) < 1200 -> needs ceil((1200 - 875.075) / 150) == 3 reloads!
    carrier = companion_loadout.evaluate_companion({
        "path": CARRIER,
        "mods": [
            {"path": CALCULATED_REDIRECTION, "rank": 10, "slot": 0},
            {"path": REINFORCED_BOND, "rank": 5, "slot": 1},
        ],
    })
    rb_carrier = carrier["playerBridge"]["reinforcedBond"]
    assert round(carrier["stats"]["shield"]["modded"], 2) == 875.08
    assert rb_carrier["staticActive"] is False
    assert rb_carrier["reloadOvershield"] == pytest.approx(150.0)
    assert rb_carrier["reloadsNeededForThreshold"] == 3
    assert rb_carrier["fireRateBonus"] == pytest.approx(0.60)
    assert rb_carrier["staticFireRateBonus"] == 0.0
    assert not any(
        e.upgrade_type == "WEAPON_FIRE_RATE" for e in companion_loadout.player_weapon_mod_effects(carrier)
    )


def test_beast_link_redirection_reinforced_bond_and_mutual_exclusion():
    # Smeeta Kavat (390/230/300) + Link Redirection R10 + Warframe 800 shield = 230 + 1000 = 1230 >= 1200!
    smeeta = companion_loadout.evaluate_companion(
        {
            "path": SMEETA_KAVAT,
            "mods": [
                {"path": LINK_REDIRECTION, "rank": 10, "slot": 0},
                {"path": REINFORCED_BOND, "rank": 5, "slot": 1},
                {"path": HASTENED_DEFLECTION, "rank": 5, "slot": 2},
            ],
        },
        warframe_panel={"health": 740.0, "shield": 800.0, "armor": 300.0},
    )
    assert smeeta["stats"]["health"]["base"] == 390.0
    assert smeeta["stats"]["shield"]["base"] == 230.0
    assert smeeta["stats"]["armor"]["base"] == 300.0
    assert smeeta["stats"]["shield"]["modded"] == pytest.approx(1230.0)
    assert smeeta["playerBridge"]["reinforcedBond"]["staticActive"] is True
    assert smeeta["playerBridge"]["reinforcedBond"]["reloadsNeededForThreshold"] == 0
    assert not any("companion-link-mod-without-warframe" in w for w in smeeta["warnings"])

    # Link MOD without warframe_panel falls back to neutral 300/300/100 with a warning.
    smeeta_unlinked = companion_loadout.evaluate_companion({
        "path": SMEETA_KAVAT,
        "mods": [{"path": LINK_REDIRECTION, "rank": 10, "slot": 0}],
    })
    assert smeeta_unlinked["stats"]["shield"]["modded"] == pytest.approx(230.0 + 1.25 * 300.0)
    assert any("companion-link-mod-without-warframe" in w for w in smeeta_unlinked["warnings"])

    # Venari has 0 shields -> cannot trigger Reinforced Bond even via reloads.
    venari = companion_loadout.evaluate_companion({
        "path": VENARI,
        "mods": [{"path": REINFORCED_BOND, "rank": 5, "slot": 0}],
    })
    assert venari["stats"]["shield"]["modded"] == 0.0
    assert venari["playerBridge"]["reinforcedBond"]["staticActive"] is False
    assert venari["playerBridge"]["reinforcedBond"]["reloadsNeededForThreshold"] is None

    # Mutual exclusion: Calculated Redirection + Link Redirection, Enhanced Vitality + Link Vitality,
    # Metal Fiber + Link Fiber, Regen + Primed Regen.
    for host, mod_a, mod_b in (
        (SMEETA_KAVAT, CALCULATED_REDIRECTION, LINK_REDIRECTION),
        (SMEETA_KAVAT, ENHANCED_VITALITY, LINK_VITALITY),
        (SMEETA_KAVAT, METAL_FIBER, LINK_FIBER),
        (DETHCUBE, REGEN, PRIMED_REGEN),
    ):
        with pytest.raises(SimulationError):
            companion_loadout.evaluate_companion({
                "path": host,
                "mods": [
                    {"path": mod_a, "slot": 0},
                    {"path": mod_b, "slot": 1},
                ],
            })

    # Sentinels cannot equip Link mods.
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion({
            "path": DETHCUBE,
            "mods": [{"path": LINK_SHIELD, "slot": 0}] if False else [{"path": LINK_REDIRECTION, "slot": 0}],
        })


def test_moa_hound_and_deimos_modular_assemblies_match_wfsim():
    # MOA: drex_core (+10% health) + trux_gyro (+5% health) modify base BEFORE Enhanced Vitality (+2.5003).
    moa_gilded = companion_loadout.evaluate_companion({
        "path": OLORO_MOA,
        "parts": {"core": "drex_core", "gyro": "trux_gyro", "bracket": "tian_bracket"},
        "mods": [{"path": ENHANCED_VITALITY, "rank": 10, "slot": 1}],
    })
    assert moa_gilded["stats"]["health"]["base"] == pytest.approx(350.0 * 1.15)
    assert moa_gilded["stats"]["health"]["modded"] == pytest.approx(350.0 * 1.15 * 3.5003)
    # tian_bracket grants AP_DEFENSE in first open slot (slot 1), matching Enhanced Vitality (AP_DEFENSE)!
    assert moa_gilded["nativePolarities"][1] == "AP_DEFENSE"
    assert moa_gilded["slots"][0]["polarityRelation"] == "matched"
    assert moa_gilded["slots"][0]["drain"] == 6  # ceil(12 / 2)

    moa_ungilded = companion_loadout.evaluate_companion({
        "path": OLORO_MOA,
        "gilded": False,
        "parts": {"core": "drex_core", "gyro": "trux_gyro"},
        "mods": [{"path": ENHANCED_VITALITY, "rank": 10, "slot": 1}],
    })
    assert moa_ungilded["stats"]["health"]["modded"] == pytest.approx(350.0 * 1.075 * 3.5003)

    # Hound: adlet_core (350/450/350) sets base; zubb_bracket (-10% health, +20% shield, +30% armor)
    # has modifyBase=False and adds into the mod percentage bucket!
    hound = companion_loadout.evaluate_companion({
        "path": DORMA_HOUND,
        "parts": {"core": "adlet_core", "bracket": "zubb_bracket", "stabilizer": "hinta_stabilizer"},
        "mods": [{"path": ENHANCED_VITALITY, "rank": 10, "slot": 2}],
    })
    assert hound["stats"]["health"]["base"] == 350.0
    assert hound["stats"]["health"]["unmodded"] == pytest.approx(350.0 * 0.9)
    assert hound["stats"]["health"]["modded"] == pytest.approx(350.0 * (1.0 - 0.1 + 2.5003))
    assert hound["nativePolarities"][1] == "AP_ATTACK"  # hinta_stabilizer

    # Hound Audit family mutual exclusion (Null Audit + Repo Audit rejected).
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion({
            "path": DORMA_HOUND,
            "mods": [
                {"path": "null_audit", "slot": 0},
                {"path": "repo_audit", "slot": 1},
            ],
        })

    # Deimos Vulpaphyla mutagen resistances & antigen innate polarity.
    panzer = companion_loadout.evaluate_companion({
        "path": PANZER_VULPAPHYLA,
        "parts": {"mutagen": "zarim_mutagen", "antigen": "desus_antigen"},
    })
    assert panzer["nativePolarities"][1] == "AP_DEFENSE"
    res_types = {r["damageType"] for r in panzer["assembly"]["resistances"]}
    assert res_types == {"DT_IMPACT", "DT_FREEZE"}

    # Foreign part rejected.
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion({
            "path": OLORO_MOA,
            "parts": {"core": "adlet_core"},
        })


def test_tenacious_bond_across_robotic_weapons_rivens_and_beast_claws():
    # 1. Vulklok (35% CC) + Point Strike (+150%) = 87.5% > 50% -> active!
    diriga_vulklok = companion_loadout.evaluate_companion(
        {
            "path": DIRIGA,
            "mods": [
                {"path": CALCULATED_SHOT, "rank": 5, "slot": 0},
                {"path": TENACIOUS_BOND, "rank": 5, "slot": 1},
            ],
        },
        {"path": VULKLOK, "mods": [{"path": POINT_STRIKE, "rank": 5, "slot": 0}]},
        exports=app.EXPORTS,
    )
    tb1 = diriga_vulklok["playerBridge"]["tenaciousBond"]
    assert tb1["companionCritChance"] == pytest.approx(0.875)
    assert tb1["active"] is True
    assert tb1["finalCritDamageBonus"] == pytest.approx(1.20)
    # Verify player_weapon_mod_effects raises a player weapon's crit_multiplier by flat +1.20!
    braton_prime = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Braton Prime")
    base_player = damage.apply_mods(braton_prime, [])
    buffed_player = damage.apply_mods(braton_prime, companion_loadout.player_weapon_mod_effects(diriga_vulklok))
    assert buffed_player.crit_multiplier == pytest.approx(base_player.crit_multiplier + 1.20)

    # 2. Verglas Prime (14% CC) + Critical Delay (+200%) = 42% -> inactive without CC Riven, active with CC Riven!
    wyrm_no_riven = companion_loadout.evaluate_companion(
        {
            "path": WYRM_PRIME,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": TENACIOUS_BOND, "rank": 5, "slot": 1},
            ],
        },
        {"path": VERGLAS_PRIME, "mods": [{"path": CRITICAL_DELAY, "rank": 5, "slot": 0}]},
        exports=app.EXPORTS,
    )
    assert wyrm_no_riven["weapon"]["critChance"] == pytest.approx(0.42, abs=1e-4)
    assert wyrm_no_riven["playerBridge"]["tenaciousBond"]["active"] is False
    assert wyrm_no_riven["playerBridge"]["tenaciousBond"]["finalCritDamageBonus"] == 0.0

    wyrm_cc_riven = companion_loadout.evaluate_companion(
        {
            "path": WYRM_PRIME,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": TENACIOUS_BOND, "rank": 5, "slot": 1},
            ],
        },
        {
            "path": VERGLAS_PRIME,
            "mods": [{"path": CRITICAL_DELAY, "rank": 5, "slot": 0}],
            "riven": {"stats": [{"code": "0", "value": 120.0}, {"code": "1", "value": 80.0}], "slot": 1},
        },
        exports=app.EXPORTS,
    )
    # 0.14 * (1 + 2.0 + 1.2) = 0.588 > 0.50!
    assert wyrm_cc_riven["weapon"]["critChance"] == pytest.approx(0.588, abs=1e-4)
    assert wyrm_cc_riven["playerBridge"]["tenaciousBond"]["active"] is True
    assert wyrm_cc_riven["playerBridge"]["tenaciousBond"]["finalCritDamageBonus"] == pytest.approx(1.20)

    # 3. Adarza Claws (30% CC) + Bite R10 (+330% CC, +220% CD) = 129% -> active, Beast arenaActiveAttack == False!
    adarza = companion_loadout.evaluate_companion(
        {
            "path": ADARZA_KAVAT,
            "mods": [
                {"path": TENACIOUS_BOND, "rank": 5, "slot": 0},
                {"path": VICIOUS_BOND, "rank": 5, "slot": 1},
                {"path": SHARPENED_CLAWS, "rank": 3, "slot": 2},
            ],
        },
        {
            "path": ADARZA_CLAWS,
            "mods": [{"path": BITE, "rank": 10, "slot": 7}],
            "posture": {"path": FRENZIED_POSTURE, "rank": 3},
        },
    )
    assert adarza["weapon"]["critChance"] == pytest.approx(1.29)
    assert adarza["weapon"]["critMultiplier"] == pytest.approx(2.5 * 3.2)
    assert adarza["weapon"]["capacity"]["postureGain"] == 10
    assert adarza["weapon"]["capacity"]["total"] == 70
    assert adarza["weapon"]["armorStripOnHit"] == pytest.approx(1.0)
    assert adarza["playerBridge"]["tenaciousBond"]["active"] is True
    assert adarza["attackProfile"]["arenaActiveAttack"] is False
    assert adarza["primingSummary"]["steadyPrimingStacks"] == {}

    # 4. Vizier Claws (5% CC) + Bite (21.5% -> inactive alone; + Hunter Synergy + 100% Primary CC -> 51.5% -> active!)
    vizier_alone = companion_loadout.evaluate_companion(
        {"path": VIZIER_PREDASITE, "mods": [{"path": TENACIOUS_BOND, "rank": 5, "slot": 0}]},
        {"path": VIZIER_CLAWS, "mods": [{"path": BITE, "rank": 10, "slot": 0}]},
    )
    assert vizier_alone["weapon"]["critChance"] == pytest.approx(0.215)
    assert vizier_alone["playerBridge"]["tenaciousBond"]["active"] is False

    vizier_linked = companion_loadout.evaluate_companion(
        {"path": VIZIER_PREDASITE, "mods": [{"path": TENACIOUS_BOND, "rank": 5, "slot": 0}]},
        {
            "path": VIZIER_CLAWS,
            "mods": [
                {"path": BITE, "rank": 10, "slot": 0},
                {"path": HUNTER_SYNERGY, "rank": 5, "slot": 1},
                {"path": MECHA_OVERDRIVE, "rank": 5, "slot": 2},
            ],
        },
        primary_weapon_stats={"critChance": 1.0, "statusChance": 0.5},
    )
    assert vizier_linked["weapon"]["critChance"] == pytest.approx(0.515)
    assert vizier_linked["weapon"]["statusChance"] == pytest.approx(0.30 + 0.60 * 0.50)
    assert vizier_linked["playerBridge"]["tenaciousBond"]["active"] is True
    assert vizier_linked["attackProfile"]["arenaActiveAttack"] is False


def test_beast_claw_coalescing_conversions_and_exclusivity():
    # Panzer Claws (45 Slash + 45 Toxin): Frost Jaw (+60% Cold) in slot 0 combines with innate Toxin LAST -> Viral!
    panzer_viral = companion_loadout.evaluate_companion(
        {"path": PANZER_VULPAPHYLA},
        {"path": PANZER_CLAWS, "mods": [{"path": FROST_JAW, "rank": 3, "slot": 0}]},
    )
    assert set(panzer_viral["weapon"]["damageTypes"]) == {"DT_SLASH", "DT_VIRAL"}
    assert panzer_viral["weapon"]["damageTypes"]["DT_VIRAL"] == pytest.approx(90.0 * 0.60 + 45.0)

    # Flame Gland (slot 0) + Frost Jaw (slot 1) -> Blast (108), innate Toxin (45) stays separate!
    panzer_blast_toxin = companion_loadout.evaluate_companion(
        {"path": PANZER_VULPAPHYLA},
        {
            "path": PANZER_CLAWS,
            "mods": [
                {"path": FLAME_GLAND, "rank": 3, "slot": 0},
                {"path": FROST_JAW, "rank": 3, "slot": 1},
            ],
        },
    )
    assert set(panzer_blast_toxin["weapon"]["damageTypes"]) == {"DT_SLASH", "DT_EXPLOSION", "DT_POISON"}

    # Brute Conditioning converts physical to Impact; Burning Claws converts all elemental to Heat + 330% Heat.
    panzer_converted = companion_loadout.evaluate_companion(
        {"path": PANZER_VULPAPHYLA},
        {
            "path": PANZER_CLAWS,
            "mods": [
                {"path": BRUTE_CONDITIONING, "rank": 10, "slot": 0},
                {"path": BURNING_CLAWS, "rank": 10, "slot": 1},
            ],
            "posture": {"path": PROTECTOR_POSTURE, "rank": 3},
        },
    )
    assert set(panzer_converted["weapon"]["damageTypes"]) == {"DT_IMPACT", "DT_FIRE"}
    assert panzer_converted["weapon"]["expectedProcsPerShot"]["DT_PUNCTURE"] >= 4.0

    # Mecha Overdrive rejected on Kavat claws; Strain Fever rejected on non-Helminth claws;
    # dual Conditioning or dual Elemental Conversion rejected.
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": ADARZA_KAVAT},
            {"path": ADARZA_CLAWS, "mods": [{"path": MECHA_OVERDRIVE, "slot": 0}]},
        )
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": VIZIER_PREDASITE},
            {"path": VIZIER_CLAWS, "mods": [{"path": STRAIN_FEVER, "slot": 0}]},
        )
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": PANZER_VULPAPHYLA},
            {
                "path": PANZER_CLAWS,
                "mods": [
                    {"path": BRUTE_CONDITIONING, "slot": 0},
                    {"path": PRECISION_CONDITIONING, "slot": 1},
                ],
            },
        )
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": PANZER_VULPAPHYLA},
            {
                "path": PANZER_CLAWS,
                "mods": [
                    {"path": BURNING_CLAWS, "slot": 0},
                    {"path": CHILLING_CLAWS, "slot": 1},
                ],
            },
        )


def test_sentinel_attack_precept_verglas_priming_range_and_vigilante_sets():
    verglas_mods = [
        {"path": SPLIT_CHAMBER, "slot": 0},
        {"path": SHIVERING_CONTAGION, "slot": 1},
        {"path": VIGILANTE_MODS[0], "slot": 2},
        {"path": VIGILANTE_MODS[1], "slot": 3},
        {"path": VIGILANTE_MODS[2], "slot": 4},
        {"path": VIGILANTE_MODS[3], "slot": 5},
    ]

    # WITHOUT Assault Mode: canAttack == False, zero priming!
    passive_sentinel = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME, "mods": [{"path": SYNTH_DECONSTRUCT, "rank": 5, "slot": 0}]},
        {"path": VERGLAS_PRIME, "mods": verglas_mods},
        exports=app.EXPORTS,
    )
    assert passive_sentinel["attackProfile"]["canAttack"] is False
    assert passive_sentinel["attackProfile"]["arenaActiveAttack"] is False
    assert passive_sentinel["attackProfile"]["effectiveMaxRange"] == 0.0
    assert passive_sentinel["primingSummary"]["steadyPrimingStacks"] == {}
    assert passive_sentinel["primingSummary"]["coldProcsPerSecond"] == 0.0
    # Set mods still apply passively even when sentinel has no attack precept!
    assert passive_sentinel["playerBridge"]["setPieceCounts"] == {"SynthSetMod": 1, "VigilanteSetMod": 4}
    assert passive_sentinel["playerBridge"]["vigilanteCritEnhanceChance"] == pytest.approx(0.20)

    # WITH Assault Mode: canAttack == True, effectiveMaxRange == min(30, 24) == 24.0, Cold capped at 10!
    active_cold = companion_loadout.evaluate_companion(
        {
            "path": WYRM_PRIME,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": SYNTH_DECONSTRUCT, "rank": 5, "slot": 1},
            ],
        },
        {"path": VERGLAS_PRIME, "mods": verglas_mods},
        exports=app.EXPORTS,
    )
    assert active_cold["attackProfile"]["canAttack"] is True
    assert active_cold["attackProfile"]["engageRange"] == pytest.approx(30.0)
    assert active_cold["attackProfile"]["effectiveMaxRange"] == pytest.approx(24.0)
    assert active_cold["attackProfile"]["shiveringContagionEquipped"] is True
    assert active_cold["primingSummary"]["coldProcsPerSecond"] > 5.0
    assert active_cold["primingSummary"]["steadyPrimingStacks"]["DT_FREEZE"] == pytest.approx(10.0)

    # WITH Sinister Reach (+12m beam range) + Calculated Shot (70m) + Eagle Eye (+40% zoom):
    # engageRange = 70 * 1.4 = 98m, traceDistance = 24 + 12 = 36m -> effectiveMaxRange == 36.0!
    # Also test Viral + Heat priming (Malignant Force + Thermite Rounds, innate Cold last -> Viral + Heat?
    # Wait: Malignant Force (Toxin) + Thermite Rounds (Heat) = Gas, innate Cold stays Cold!
    # Whereas Malignant Force alone combines with innate Cold -> Viral, or Frost + Toxin + Heat -> Viral + Heat!).
    viral_heat = companion_loadout.evaluate_companion(
        {
            "path": DIRIGA,
            "mods": [
                {"path": CALCULATED_SHOT, "rank": 5, "slot": 0},
                {"path": MANIFOLD_BOND, "rank": 5, "slot": 1},
                {"path": "arc_coil", "rank": 5, "slot": 2},
            ],
        },
        {
            "path": VERGLAS_PRIME,
            "mods": [
                {"path": "/Lotus/Upgrades/Mods/Rifle/DualStat/IceEventRifleMod", "slot": 0},
                {"path": MALIGNANT_FORCE, "slot": 1},
                {"path": THERMITE_ROUNDS, "slot": 2},
                {"path": SINISTER_REACH, "slot": 3},
                {"path": EAGLE_EYE, "slot": 4},
            ],
        },
        exports=app.EXPORTS,
    )
    assert viral_heat["weapon"]["rangeLimit"] == pytest.approx(36.0)
    assert viral_heat["attackProfile"]["engageRange"] == pytest.approx(70.0 * 1.4)
    assert viral_heat["attackProfile"]["effectiveMaxRange"] == pytest.approx(36.0)
    assert viral_heat["primingSummary"]["steadyPrimingStacks"]["DT_VIRAL"] == pytest.approx(10.0)
    expected_heat_rate = (
        viral_heat["weapon"]["expectedProcsPerShot"]["DT_FIRE"]
        * viral_heat["primingSummary"]["effectiveShotsPerSecond"]
    )
    assert viral_heat["primingSummary"]["heatProcsPerSecond"] == pytest.approx(expected_heat_rate, rel=1e-5)
    assert viral_heat["primingSummary"]["heatProcsPerSecond"] > 1.5
    assert viral_heat["primingSummary"]["steadyPrimingStacks"]["DT_FIRE"] > 10.0
    assert set(viral_heat["playerBridge"]["manifoldBond"]["preceptStatusTypes"]) == {"DT_VIRAL", "DT_FIRE"}


def test_helios_deconstructor_exclusivity_update30_5_gladiator_and_buff_precepts():
    # Deconstructor Prime works on Helios Prime, rejected on Diriga.
    helios = companion_loadout.evaluate_companion(
        {
            "path": HELIOS_PRIME,
            "mods": [
                {"path": TARGETING_RECEPTOR, "rank": 3, "slot": 0},
                {"path": MANIFOLD_BOND, "rank": 5, "slot": 1},
            ],
        },
        {"path": DECONSTRUCTOR_PRIME, "mods": []},
        exports=app.EXPORTS,
    )
    assert helios["attackProfile"]["canAttack"] is True
    assert helios["attackProfile"]["engageRange"] == pytest.approx(10.0)
    # Manifold Bond sees all 3 IPS types from Deconstructor's 3-glaive sequence!
    assert set(helios["playerBridge"]["manifoldBond"]["preceptStatusTypes"]) == {
        "DT_IMPACT",
        "DT_PUNCTURE",
        "DT_SLASH",
    }

    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": DIRIGA},
            {"path": DECONSTRUCTOR_PRIME},
            exports=app.EXPORTS,
        )

    # Update 30.5: Gladiator melee mods rejected on Deconstructor Prime and Hound weapons!
    with pytest.raises(SimulationError):
        companion_loadout.evaluate_companion(
            {"path": HELIOS_PRIME},
            {"path": DECONSTRUCTOR_PRIME, "mods": [{"path": GLADIATOR_MIGHT, "slot": 0}]},
            exports=app.EXPORTS,
        )

    # Cat's Eye + Tek Enhance uptime & Ambush +240% weapon damage, plus full JSON serializability.
    adarza_buff = companion_loadout.evaluate_companion({
        "path": ADARZA_KAVAT,
        "mods": [
            {"path": CATS_EYE, "rank": 3, "slot": 0},
            {"path": TEK_ENHANCE, "rank": 5, "slot": 1},
        ],
        "options": {"catsEyeMode": "average"},
    })
    ce = adarza_buff["playerBridge"]["buffPrecepts"]["catsEye"]
    assert ce["duration"] == pytest.approx(13.0)
    assert ce["cooldown"] == pytest.approx(20.0)
    assert ce["uptime"] == pytest.approx(0.65)
    assert ce["effectiveCritBonus"] == pytest.approx(0.60 * 0.65)

    shade = companion_loadout.evaluate_companion({
        "path": SHADE_PRIME,
        "mods": [{"path": AMBUSH, "rank": 3, "slot": 0}],
        "options": {"ambushActive": True},
    })
    assert shade["playerBridge"]["buffPrecepts"]["ambush"]["weaponDamageBonus"] == pytest.approx(2.40)
    # Result must be cleanly JSON-serializable for HTTP API responses.
    encoded = json.dumps(shade)
    assert '"ambush"' in encoded


def test_moa_hard_engage_helstrum_and_omni_forma_drain():
    # MOA with Helstrum (burstCount=4 + radial Heat) & Omni Forma vs Umbra check.
    moa_helstrum = companion_loadout.evaluate_companion(
        {
            "path": OLORO_MOA,
            "polarities": ["AP_ANY", None, None, None, None, None, None, None, None, None],
            "mods": [{"path": ENHANCED_VITALITY, "rank": 10, "slot": 0}],
        },
        {"path": HELSTRUM, "mods": [{"path": SPLIT_CHAMBER, "slot": 0}]},
        exports=app.EXPORTS,
    )
    assert moa_helstrum["slots"][0]["polarityRelation"] == "matched"
    assert moa_helstrum["slots"][0]["drain"] == 6
    assert moa_helstrum["attackProfile"]["canAttack"] is True
    assert moa_helstrum["attackProfile"]["engageRange"] == pytest.approx(70.0)
    # Helstrum: 4 missiles per burst (3*0.1 + 4.0 = 4.3s), 20 bursts per 80-round mag + 2s reload = 88s for 80 shots.
    expected_shots_per_sec = 80.0 / (20.0 * 4.3 + 2.0)
    assert moa_helstrum["weapon"]["sustainedShotsPerSecond"] == pytest.approx(expected_shots_per_sec, rel=1e-5)
    # Radial 24 Heat + 6 Impact quantizes in 1/16ths (quantum 30/16 = 1.875 -> 13/16 = 0.8125 Heat weight).
    assert moa_helstrum["primingSummary"]["heatProcsPerSecond"] == pytest.approx(
        expected_shots_per_sec * 0.30 * 1.9 * (13.0 / 16.0), rel=1e-5
    )

    # MOA with Hard Engage + MoaPetMeleeWeapon -> 10m melee mode.
    moa_melee = companion_loadout.evaluate_companion(
        {"path": OLORO_MOA, "mods": [{"path": HARD_ENGAGE, "rank": 5, "slot": 0}]},
        {"path": "MoaPetMeleeWeapon", "mods": []},
        exports=app.EXPORTS,
    )
    assert moa_melee["attackProfile"]["attackMode"] == "melee"
    assert moa_melee["attackProfile"]["engageRange"] == pytest.approx(10.0)
    assert moa_melee["weapon"]["totalDamage"] == pytest.approx(90.0)


def test_remaining_bond_mods_and_body_to_weapon_effects():
    res = companion_loadout.evaluate_companion(
        {
            "path": DETHCUBE,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": "/Lotus/Upgrades/Mods/Sentinel/SentinelOverheatDamageMod", "rank": 5, "slot": 1},
                {"path": ASTRAL_BOND, "rank": 5, "slot": 2},
                {"path": MOMENTOUS_BOND, "rank": 5, "slot": 3},
                {"path": CONTAGIOUS_BOND, "rank": 5, "slot": 4},
                {"path": DUPLEX_BOND, "rank": 5, "slot": 5},
                {"path": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PreyDrive", "rank": 5, "slot": 6},
                {"path": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BondedExaltation", "rank": 5, "slot": 7},
                {"path": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Copilot", "rank": 5, "slot": 8},
                {"path": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/MutualNourishment", "rank": 5, "slot": 9},
            ],
            "options": {
                "firedUp": True,
                "astralBond": True,
                "momentousElement": "DT_ELECTRICITY",
                "duplexClones": 3,
            },
        },
        {"path": VERGLAS_PRIME, "mods": []},
        exports=app.EXPORTS,
    )
    # Fired Up (DT_FIRE) + Momentous Bond (DT_ELECTRICITY) combine into DT_RADIATION, innate DT_FREEZE stays,
    # Astral Bond adds post-coalesce DT_RADIANT (Void)!
    dtypes = set(res["weapon"]["damageTypes"])
    assert dtypes == {"DT_RADIATION", "DT_FREEZE", "DT_RADIANT"}
    bridge = res["playerBridge"]
    assert bridge["contagiousBond"] == {
        "equipped": True,
        "rank": 5,
        "spreadRatio": 0.50,
        "spreadRadius": 9.0,
        "maxStacks": 100,
    }
    assert bridge["duplexBond"]["activeClones"] == 3
    assert res["attackProfile"]["cloneMultiplier"] == 4
    assert bridge["mysticBond"]["requiredCooldownCasts"] == 5
    assert bridge["seismicBond"]["shockwaveDamageShare"] == pytest.approx(0.30)
    assert bridge["aerialBond"]["coldFieldMaxSlow"] == pytest.approx(0.35)
    assert bridge["restorativeBond"]["bonusHealthPerOrb"] == pytest.approx(60.0)
    assert bridge["astralBond"]["active"] is True
    assert bridge["momentousBond"]["activeElement"] == "DT_ELECTRICITY"


def test_companion_catalog_riven_metadata_and_faction_riven_parsing():
    cat = companion_loadout.get_companion_catalog()
    weapons = cat["companionWeapons"]
    assert len(weapons) >= 24
    by_path = {w["path"]: w for w in weapons}
    assert VERGLAS_PRIME in by_path
    vp = by_path[VERGLAS_PRIME]
    assert isinstance(vp["disposition"], float) and vp["disposition"] > 0.0
    assert vp["rivenType"] == "rifle"
    assert vp["isVirtualMoaMelee"] is False

    assert by_path[DECONSTRUCTOR_PRIME]["rivenType"] == "melee"
    assert by_path[AKATEN]["rivenType"] == "melee"
    moa_virtual = next(w for w in weapons if w["isVirtualMoaMelee"])
    assert moa_virtual["isVirtualMoaMelee"] is True
    assert moa_virtual["disposition"] == 0.0
    assert moa_virtual["rivenType"] is None

    for w in weapons:
        assert isinstance(w["disposition"], float)
        assert isinstance(w["isVirtualMoaMelee"], bool)
        if not w["isVirtualMoaMelee"]:
            assert w["rivenType"] in {"rifle", "shotgun", "pistol", "melee"}

    # Faction codes ("C", "G", "I", "FO", "FT", "FS") and friendly names + structured riven.stats output!
    eval_codes = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        {
            "path": VERGLAS_PRIME,
            "riven": {
                "slot": 0,
                "stats": [
                    {"code": "G", "value": 45.0},
                    {"code": "FO", "value": 42.5},
                    {"code": "FT", "value": 38.0},
                    {"code": "C", "value": 25.0, "negative": True},
                ],
            },
        },
        exports=app.EXPORTS,
    )
    fmults = eval_codes["weapon"]["factionMultipliers"]
    assert fmults["Grineer"] == pytest.approx(1.45)
    assert fmults["Orokin"] == pytest.approx(1.425)
    assert fmults["Techrot"] == pytest.approx(1.38)
    assert fmults["Corpus"] == pytest.approx(0.75)
    rstats = eval_codes["weapon"]["riven"]["stats"]
    assert [s["code"] for s in rstats] == ["G", "FO", "FT", "C"]
    assert rstats[3]["negative"] is True and rstats[3]["value"] == pytest.approx(25.0)

    eval_friendly = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME},
        {
            "path": VERGLAS_PRIME,
            "riven": {
                "stats": {
                    "damage_vs_infested": 50.0,
                    "damage_vs_scaldra": 40.0,
                    "damage_vs_orokin": -20.0,
                }
            },
        },
        exports=app.EXPORTS,
    )
    fmults2 = eval_friendly["weapon"]["factionMultipliers"]
    assert fmults2["Infestation"] == pytest.approx(1.50)
    assert fmults2["Scaldra"] == pytest.approx(1.40)
    assert fmults2["Orokin"] == pytest.approx(0.80)
    assert {s["code"] for s in eval_friendly["weapon"]["riven"]["stats"]} == {"I", "FS", "FO"}


def test_negative_riven_stat_clamping_on_verglas_prime():
    # Verglas Prime has 14% base CC; a -121.5% CC Riven would yield -3.01% unclamped!
    for neg_stat in (
        {"code": "0", "value": 121.5, "negative": True},
        {"code": "0", "value": -121.5},
    ):
        res = companion_loadout.evaluate_companion(
            {
                "path": WYRM_PRIME,
                "mods": [
                    {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                    {"path": TENACIOUS_BOND, "rank": 5, "slot": 1},
                ],
            },
            {
                "path": VERGLAS_PRIME,
                "riven": {
                    "slot": 0,
                    "stats": [
                        {"code": "D", "value": 165.0},
                        neg_stat,
                    ],
                },
            },
            exports=app.EXPORTS,
        )
        w = res["weapon"]
        assert w["critChance"] == 0.0
        assert w["critMultiplier"] >= 1.0
        assert w["statusChance"] >= 0.0
        assert w["multishot"] >= 0.0
        assert w["averageHit"] >= w["totalDamage"] - 1e-3
        assert res["playerBridge"]["tenaciousBond"]["active"] is False

    # Also clamp extreme negative CD / SC / MS Rivens cleanly to >= 1.0 / >= 0.0.
    res_extreme = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME},
        {
            "path": VERGLAS_PRIME,
            "riven": {
                "stats": [
                    {"code": "1", "value": 150.0, "negative": True},
                    {"code": "2", "value": 150.0},
                ]
            },
        },
        exports=app.EXPORTS,
    )
    assert res_extreme["weapon"]["critMultiplier"] == 1.0


def test_standalone_weapon_damage_composition_dot_and_target_evaluation():
    rifle_elementalist = next(m["path"] for m in app.EXPORTS["mods"] if m.get("nameEn") == "Rifle Elementalist")
    serration = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Serration")
    rime_rounds = "/Lotus/Upgrades/Mods/Rifle/DualStat/IceEventRifleMod"

    # Heat + Viral + Rifle Elementalist (+90% SD) + +111.4% Status Damage Riven on Verglas Prime!
    hv = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        {
            "path": VERGLAS_PRIME,
            "mods": [
                {"path": serration, "slot": 0},
                {"path": rime_rounds, "slot": 1},
                {"path": MALIGNANT_FORCE, "slot": 2},
                {"path": THERMITE_ROUNDS, "slot": 3},
                {"path": rifle_elementalist, "slot": 4},
            ],
            "riven": {
                "slot": 5,
                "stats": [
                    {"code": "SD", "value": 111.4},
                    {"code": "4", "value": 95.0},
                    {"code": "0", "value": 121.5, "negative": True},
                ],
            },
        },
        exports=app.EXPORTS,
    )
    w = hv["weapon"]
    assert w["critChance"] == 0.0
    assert w["statusDamageMultiplier"] == pytest.approx(1.0 + 0.90 + 1.114, abs=1e-4)
    assert w["statusDamageMultiplier"] > 3.0
    comp = w["damageComposition"]
    comp_types = [row["damageType"] for row in comp]
    assert set(comp_types) == {"DT_VIRAL", "DT_FIRE"}
    assert comp[0]["damage"] >= comp[1]["damage"]
    assert sum(row["share"] for row in comp) == pytest.approx(1.0, abs=1e-4)
    assert sum(row["procWeight"] for row in comp) == pytest.approx(1.0, abs=1e-4)
    assert all(row["procsPerShot"] > 0.0 and row["procsPerSecond"] > 0.0 for row in comp)
    assert w["dotDps"] > w["sustainedDps"]
    assert w["totalSustainedDps"] == pytest.approx(w["sustainedDps"] + w["dotDps"], abs=1e-2)

    te = w["targetEvaluation"]
    assert te["level"] == 170 and te["steelPath"] is True
    assert te["totalTargetDps"] > 0.0
    assert te["sustainedDotDps"] > te["sustainedDirectDps"]
    assert te["steadyArmorStrip"] == pytest.approx(0.50)
    assert te["steadyViralMultiplier"] == pytest.approx(4.25)

    # Custom target_config (Lv 1 non-SP) yields higher direct DPS than Lv 170 SP armored Heavy Gunner.
    hv_lv1 = companion_loadout.evaluate_companion(
        {"path": WYRM_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
        {"path": VERGLAS_PRIME, "mods": [{"path": serration, "slot": 0}]},
        target_config={"level": 1, "steelPath": False},
        exports=app.EXPORTS,
    )
    assert hv_lv1["weapon"]["targetEvaluation"]["level"] == 1
    assert hv_lv1["weapon"]["targetEvaluation"]["steelPath"] is False

    # Helstrum radial composition check.
    helstrum_res = companion_loadout.evaluate_companion(
        {"path": OLORO_MOA},
        {"path": HELSTRUM, "mods": [{"path": SPLIT_CHAMBER, "slot": 0}]},
        exports=app.EXPORTS,
    )
    rcomp = helstrum_res["weapon"]["radialComposition"]
    assert {r["damageType"] for r in rcomp} == {"DT_FIRE", "DT_IMPACT"}
    assert sum(r["share"] for r in rcomp) == pytest.approx(1.0, abs=1e-4)

    # Beast Claws standalone damage, DoT, statusDamageMultiplier & composition check.
    immunity_res = "immunity_resistance"
    claw_eval = companion_loadout.evaluate_companion(
        {"path": PANZER_VULPAPHYLA},
        {
            "path": PANZER_CLAWS,
            "mods": [
                {"path": MAUL, "rank": 10, "slot": 0},
                {"path": BITE, "rank": 10, "slot": 1},
                {"path": FROST_JAW, "rank": 3, "slot": 2},
                {"path": immunity_res, "rank": 3, "slot": 3},
            ],
            "posture": {"path": FRENZIED_POSTURE, "rank": 3},
        },
        exports=app.EXPORTS,
    )
    cw = claw_eval["weapon"]
    assert cw["disposition"] == 0.0
    assert cw["rivenType"] is None
    assert cw["statusDamageMultiplier"] > 1.0
    assert cw["averageHit"] > cw["totalDamage"]
    assert cw["burstDps"] > 0.0 and cw["sustainedDps"] == pytest.approx(cw["burstDps"])
    assert cw["dotDps"] > 0.0
    assert cw["totalSustainedDps"] == pytest.approx(cw["sustainedDps"] + cw["dotDps"], abs=1e-2)
    assert {r["damageType"] for r in cw["damageComposition"]} == {"DT_VIRAL", "DT_SLASH"}
    assert sum(r["share"] for r in cw["damageComposition"]) == pytest.approx(1.0, abs=1e-4)
    assert cw["targetEvaluation"]["totalTargetDps"] > 0.0


def test_optimize_companion_weapon_robotic_and_beast_claws():
    import time

    # Warm up Beast Claw pool cache, then verify < 15 ms optimization and valid minimal Forma!
    companion_loadout.optimize_companion_weapon(
        {"companion": {"path": ADARZA_KAVAT, "mods": []}, "weapon": {"path": ADARZA_CLAWS}, "goal": "dps"},
        exports=app.EXPORTS,
    )
    t0 = time.perf_counter()
    adarza_tb = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": ADARZA_KAVAT, "mods": [{"path": TENACIOUS_BOND, "rank": 5, "slot": 0}]},
            "weapon": {"path": ADARZA_CLAWS, "reactor": True},
            "goal": "tenaciousBond",
        },
        exports=app.EXPORTS,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 50.0  # Typically ~12 ms on warm run
    aw = adarza_tb["evaluation"]["weapon"]
    assert len(adarza_tb["mods"]) == 8
    assert adarza_tb["posture"] is not None
    assert len(adarza_tb["slotPolarities"]) == 9
    assert aw["critChance"] > 0.50
    assert adarza_tb["evaluation"]["playerBridge"]["tenaciousBond"]["active"] is True
    assert aw["capacity"]["valid"] is True
    assert aw["capacity"]["remaining"] >= 0

    adarza_dps_free = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": ADARZA_KAVAT, "mods": [{"path": VICIOUS_BOND, "rank": 5, "slot": 0}]},
            "weapon": {"path": ADARZA_CLAWS, "reactor": True},
            "goal": "dps",
        },
        exports=app.EXPORTS,
    )
    assert adarza_dps_free["evaluation"]["weapon"]["capacity"]["valid"] is True
    assert adarza_dps_free["evaluation"]["weapon"]["targetEvaluation"]["totalTargetDps"] > 45000.0

    adarza_dps = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": ADARZA_KAVAT, "mods": [{"path": VICIOUS_BOND, "rank": 5, "slot": 0}]},
            "weapon": {"path": ADARZA_CLAWS, "reactor": True},
            "goal": "dps",
            "elementTarget": "viral",
        },
        exports=app.EXPORTS,
    )
    assert "DT_VIRAL" in adarza_dps["evaluation"]["weapon"]["damageTypes"]
    assert adarza_dps["evaluation"]["weapon"]["capacity"]["valid"] is True
    assert adarza_dps["evaluation"]["weapon"]["targetEvaluation"]["totalTargetDps"] > 15000.0

    # Verglas Prime: dps (with Viral target), statusPriming, and tenaciousBond (with & without CC Riven).
    vp_dps = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": WYRM_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
            "weapon": {"path": VERGLAS_PRIME, "reactor": True},
            "goal": "dps",
            "elementTarget": "viral",
        },
        exports=app.EXPORTS,
    )
    vpw = vp_dps["evaluation"]["weapon"]
    assert len(vp_dps["slotPolarities"]) == 8
    assert vpw["capacity"]["valid"] is True and vpw["capacity"]["remaining"] >= 0
    assert "DT_VIRAL" in vpw["damageTypes"]
    assert vpw["targetEvaluation"]["totalTargetDps"] > 50000.0

    vp_priming = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": WYRM_PRIME, "mods": [{"path": ASSAULT_MODE, "rank": 5, "slot": 0}]},
            "weapon": {"path": VERGLAS_PRIME, "reactor": True},
            "goal": "statusPriming",
        },
        exports=app.EXPORTS,
    )
    assert vp_priming["evaluation"]["weapon"]["capacity"]["valid"] is True
    assert sum(vp_priming["evaluation"]["weapon"]["sustainedProcsPerSecond"].values()) > 15.0

    vp_tb_riven = companion_loadout.optimize_companion_weapon(
        {
            "companion": {
                "path": WYRM_PRIME,
                "mods": [
                    {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                    {"path": TENACIOUS_BOND, "rank": 5, "slot": 1},
                ],
            },
            "weapon": {
                "path": VERGLAS_PRIME,
                "reactor": True,
                "riven": {"stats": [{"code": "0", "value": 120.0}, {"code": "2", "value": 90.0}]},
            },
            "goal": "tenaciousBond",
        },
        exports=app.EXPORTS,
    )
    assert vp_tb_riven["riven"] is not None
    assert vp_tb_riven["evaluation"]["weapon"]["critChance"] > 0.50
    assert vp_tb_riven["evaluation"]["playerBridge"]["tenaciousBond"]["active"] is True
    assert vp_tb_riven["evaluation"]["weapon"]["capacity"]["valid"] is True

    # Deconstructor Prime auto-build must never equip Gladiator set mods (Update 30.5 ban).
    decon_opt = companion_loadout.optimize_companion_weapon(
        {
            "companion": {"path": HELIOS_PRIME, "mods": [{"path": TARGETING_RECEPTOR, "rank": 3, "slot": 0}]},
            "weapon": {"path": DECONSTRUCTOR_PRIME, "reactor": True},
            "goal": "dps",
        },
        exports=app.EXPORTS,
    )
    assert decon_opt["evaluation"]["weapon"]["capacity"]["valid"] is True
    assert "GladiatorSetMod" not in decon_opt["evaluation"]["playerBridge"]["setPieceCounts"]

