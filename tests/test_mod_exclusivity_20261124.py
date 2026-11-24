"""2026-11-24: Authoritative Packages.bin Mod family exclusivity & cross-slot tests."""

from __future__ import annotations

import itertools
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
from wfarsenal import companion_loadout, optimizer, sentinel, simulator  # noqa: E402
from wfarsenal.damage import Scenario  # noqa: E402
from wfarsenal.mod_families import (  # noqa: E402
    authoritative_mod_family,
    canonical_mod_family,
    equipment_additional_bases,
    is_unreleased_warframe_mod,
)
from wfarsenal.simulator import SimulationError  # noqa: E402

# Warframes
EXCALIBUR = "/Lotus/Powersuits/Excalibur/Excalibur"
TITANIA = "/Lotus/Powersuits/Fairy/Fairy"
NIDUS = "/Lotus/Powersuits/Infestation/Infestation"
JADE = "/Lotus/Powersuits/Choir/Choir"

# Warframe Mods
INTENSIFY = "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityStrengthMod"
UMBRAL_INTENSIFY = "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModC"
ARCHON_INTENSIFY = "/Lotus/Upgrades/Mods/Warframe/Kahl/KahlAvatarAbilityStrengthMod"
PRECISION_INTENSIFY = "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityFourStrengthMod"
UNRELEASED_EXPERT_INTENSIFY = "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityStrengthModExpert"
BEGINNER_INTENSIFY = "/Lotus/Upgrades/Mods/Warframe/Beginner/AvatarAbilityStrengthModBeginner"

VITALITY = "/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod"
UMBRAL_VITALITY = "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModA"
ARCHON_VITALITY = "/Lotus/Upgrades/Mods/Warframe/Kahl/KahlAvatarHealthMaxMod"
PARASITIC_VITALITY = "/Lotus/Powersuits/Infestation/InfestLinkAugmentCard"

STREAMLINE = "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityEfficiencyMod"
PRIMED_STREAMLINE = "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityEfficiencyModExpert"
FLEETING_EXPERTISE = "/Lotus/Upgrades/Mods/Warframe/DualStat/CorruptedEfficiencyDurationWarframe"

AVIATOR = "/Lotus/Upgrades/Mods/Warframe/AvatarDamageReductionInAir"
IRONCLAD_FLIGHT = "/Lotus/Powersuits/Fairy/FairyDisablePassiveMod"
RAZORWING_BLITZ = "/Lotus/Powersuits/Fairy/FairyFlightAugmentCard"

BRIEF_RESPITE = "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestAbilityToShieldsAuraMod"
GROWING_POWER = "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestCritToAbilityAuraMod"
CORROSIVE_PROJECTION = "/Lotus/Upgrades/Mods/Aura/EnemyArmorReductionAuraMod"

# Weapons & Weapon Mods
SECURA_PENTA = next(w["path"] for w in app.CATALOG["weapons"] if w["nameEn"] == "Secura Penta")
BOLTOR = next(w["path"] for w in app.CATALOG["weapons"] if w["nameEn"] == "Boltor" and w["buildAvailable"])
CEDO = "/Lotus/Weapons/Tenno/LongGuns/TnAlchemistShotgun/TnAlchemistShotgun"
DREAD = "/Lotus/Weapons/Tenno/Bows/StalkerBow"
HIKOU_PRIME = "/Lotus/Weapons/Tenno/ThrowingWeapons/PrimeThrowingStar/PrimeHikou"
SKANA = "/Lotus/Weapons/Tenno/Melee/LongSword/LongSword"
GRIMOIRE = "/Lotus/Weapons/Tenno/Grimoire/TnGrimoire"
NOCTUA = "/Lotus/Powersuits/Pagemaster/ExaltedBook"
ENEMY = app.CATALOG["enemies"][0]["path"]

SPLIT_CHAMBER = "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsMod"
GALVANIZED_CHAMBER = "/Lotus/Upgrades/Mods/Rifle/WeaponFireIterationsSPMod"
SERRATION = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Serration")
AMALGAM_SERRATION = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Amalgam Serration")

BARREL_DIFFUSION = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Barrel Diffusion")
GALVANIZED_DIFFUSION = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Galvanized Diffusion")
AMALGAM_BARREL_DIFFUSION = "/Lotus/Upgrades/Mods/DualSource/Pistol/MultishotDodgeMod"

FURY = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Fury")
PRIMED_FURY = "/Lotus/Upgrades/Mods/Melee/Expert/WeaponFireRateModExpert"
BERSERKER_FURY = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Berserker Fury")
QUICKENING = "/Lotus/Upgrades/Mods/Melee/Channel/ChannelFireRateMod"

FATAL_ACCELERATION = "/Lotus/Upgrades/Mods/Shotgun/WeaponProjectileSpeedMod"
GALVANIZED_ACCELERATION = "/Lotus/Upgrades/Mods/Shotgun/WeaponProjectileSpeedSPMod"

THUNDERBOLT = "/Lotus/Upgrades/Mods/Rifle/BowExplosionChanceMod"
MENDING_SHOT = "/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/ShootPickUpRifleMod"
CONCEALED_EXPLOSIVES = "/Lotus/Upgrades/Mods/Pistol/ThrowingExplosionChanceMod"
ENERGIZING_SHOT = "/Lotus/Upgrades/Mods/Pistol/Event/ShootPickUpPistolMod"
NAPALM_GRENADES = next(m["path"] for m in app.MANUAL_MODS if m.get("nameEn") == "Napalm Grenades")
TETHER_GRENADES = next(m["path"] for m in app.CATALOG_UTILITY_MODS if m.get("nameEn") == "Tether Grenades")

XATA_INVOCATION = "/Lotus/Upgrades/Grimoire/XataStrikeMod"
RIS_INVOCATION = "/Lotus/Upgrades/Grimoire/RisStrikeMod"
FASS_CANTICLE = "/Lotus/Upgrades/Grimoire/FassAuraMod"
JAHU_CANTICLE = "/Lotus/Upgrades/Grimoire/JahuAuraMod"

# Companions & Sentinels
SMEETA_KAVAT = "/Lotus/Types/Game/CatbrowPet/CheshireCatbrowPetPowerSuit"
DETHCUBE = "/Lotus/Types/Sentinels/SentinelPowersuits/DethCubePowerSuit"
LOYAL_RETRIEVER = "/Lotus/Types/Sentinels/SentinelPrecepts/BeastLoyalRetriever"
PROSPEROUS_RETRIEVER = "/Lotus/Types/Sentinels/SentinelPrecepts/BeastCreditDoublingMod"
RESOURCEFUL_RETRIEVER = "/Lotus/Types/Sentinels/SentinelPrecepts/BeastResourceDoublingMod"
REGEN = "/Lotus/Types/Sentinels/SentinelPrecepts/Regen"
PRIMED_REGEN = "/Lotus/Types/Sentinels/SentinelPrecepts/PrimedRegen"


def test_warframe_mod_families_and_unreleased_picker_flags():
    engine = app.WARFRAME_ENGINE

    # 1. Intensify family: Intensify / Umbral / Archon / Precision all share AvatarAbilityStrengthMod.
    intensify_group = (INTENSIFY, UMBRAL_INTENSIFY, ARCHON_INTENSIFY, PRECISION_INTENSIFY)
    for mod_path in intensify_group:
        assert canonical_mod_family(mod_path) == "/lotus/upgrades/mods/warframe/avatarabilitystrengthmod"
        assert authoritative_mod_family(mod_path) == "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityStrengthMod"

    for m1, m2 in itertools.combinations(intensify_group, 2):
        with pytest.raises(SimulationError, match="modFamily"):
            engine.calculate({
                "frameId": EXCALIBUR,
                "normalMods": [{"path": m1, "slot": 0}, {"path": m2, "slot": 1}],
            })

    # 2. Vitality family: Vitality / Umbral / Archon / Parasitic Vitality all share AvatarHealthMaxMod.
    vitality_group = (VITALITY, UMBRAL_VITALITY, ARCHON_VITALITY, PARASITIC_VITALITY)
    for mod_path in vitality_group:
        assert canonical_mod_family(mod_path) == "/lotus/upgrades/mods/warframe/avatarhealthmaxmod"

    for m1, m2 in itertools.combinations(vitality_group, 2):
        with pytest.raises(SimulationError, match="modFamily"):
            engine.calculate({
                "frameId": NIDUS,
                "normalMods": [{"path": m1, "slot": 0}, {"path": m2, "slot": 1}],
            })

    # 3. Streamline + Fleeting Expertise have distinct families and stack cleanly.
    assert canonical_mod_family(STREAMLINE) != canonical_mod_family(FLEETING_EXPERTISE)
    eff_res = engine.calculate({
        "frameId": EXCALIBUR,
        "normalMods": [
            {"path": STREAMLINE, "rank": 5, "slot": 0},
            {"path": FLEETING_EXPERTISE, "rank": 5, "slot": 1},
        ],
    })
    assert eff_res["validation"]["valid"] is True
    assert eff_res["finalPanel"]["abilityEfficiency"] == pytest.approx(1.75)

    # 4. Titania: Aviator + Ironclad Flight conflict (both normal+normal and exilus+normal),
    #    whereas Razorwing Blitz + Ironclad Flight are allowed together!
    assert canonical_mod_family(AVIATOR) == canonical_mod_family(IRONCLAD_FLIGHT)
    assert canonical_mod_family(RAZORWING_BLITZ) != canonical_mod_family(IRONCLAD_FLIGHT)

    with pytest.raises(SimulationError, match="modFamily"):
        engine.calculate({
            "frameId": TITANIA,
            "exilus": {"path": AVIATOR, "rank": 3},
            "normalMods": [{"path": IRONCLAD_FLIGHT, "rank": 0, "slot": 0}],
        })
    with pytest.raises(SimulationError, match="modFamily"):
        engine.calculate({
            "frameId": TITANIA,
            "exilus": {"path": IRONCLAD_FLIGHT, "rank": 0},
            "normalMods": [{"path": AVIATOR, "rank": 3, "slot": 0}],
        })

    titania_ok = engine.calculate({
        "frameId": TITANIA,
        "exilus": {"path": IRONCLAD_FLIGHT, "rank": 0},
        "normalMods": [{"path": RAZORWING_BLITZ, "rank": 3, "slot": 0}],
    })
    assert titania_ok["validation"]["valid"] is True

    # 5. Jade AdditionalBaseModTypes: Auras share LotusAuraUpgrade normally, but separate on Jade (Choir).
    assert canonical_mod_family(BRIEF_RESPITE, equip_path=EXCALIBUR) == "/lotus/types/game/lotusauraupgrade"
    assert canonical_mod_family(GROWING_POWER, equip_path=EXCALIBUR) == "/lotus/types/game/lotusauraupgrade"
    assert canonical_mod_family(BRIEF_RESPITE, equip_path=JADE) == BRIEF_RESPITE.lower()
    assert canonical_mod_family(GROWING_POWER, equip_path=JADE) == GROWING_POWER.lower()
    assert canonical_mod_family(CORROSIVE_PROJECTION, equip_path=JADE) == CORROSIVE_PROJECTION.lower()

    # 6. Unreleased Expert/Beginner Warframe placeholder mods marked hiddenFromPicker, Primed Streamline kept!
    wf_mods_by_path = {m["path"]: m for m in app.WARFRAME_CATALOG["mods"]}
    assert is_unreleased_warframe_mod(UNRELEASED_EXPERT_INTENSIFY) is True
    assert is_unreleased_warframe_mod(BEGINNER_INTENSIFY) is True
    assert wf_mods_by_path[UNRELEASED_EXPERT_INTENSIFY].get("hiddenFromPicker") is True
    assert wf_mods_by_path[BEGINNER_INTENSIFY].get("hiddenFromPicker") is True

    assert is_unreleased_warframe_mod(PRIMED_STREAMLINE) is False
    assert not wf_mods_by_path[PRIMED_STREAMLINE].get("hiddenFromPicker")
    for m in app.WARFRAME_CATALOG["mods"]:
        if str(m.get("nameEn") or "").startswith("Primed "):
            assert not m.get("hiddenFromPicker"), f"{m['nameEn']} ({m['path']}) must not be hidden"

    # Saved configs referencing hidden placeholder mods still calculate cleanly.
    legacy_calc = engine.calculate({
        "frameId": EXCALIBUR,
        "normalMods": [{"path": UNRELEASED_EXPERT_INTENSIFY, "rank": 5, "slot": 0}],
    })
    assert legacy_calc["validation"]["valid"] is True


def test_weapon_normal_mod_families_and_tennokai_independence():
    # Split Chamber + Galvanized Chamber rejected
    assert canonical_mod_family(SPLIT_CHAMBER) == canonical_mod_family(GALVANIZED_CHAMBER)
    with pytest.raises(SimulationError):
        app.simulate_manual_payload({
            "weapon": BOLTOR,
            "enemy": ENEMY,
            "mods": [
                {"path": SPLIT_CHAMBER, "slot": 0},
                {"path": GALVANIZED_CHAMBER, "slot": 1},
            ],
        })

    # Serration + Amalgam Serration rejected
    assert canonical_mod_family(SERRATION) == canonical_mod_family(AMALGAM_SERRATION)
    with pytest.raises(SimulationError):
        app.simulate_manual_payload({
            "weapon": BOLTOR,
            "enemy": ENEMY,
            "mods": [
                {"path": SERRATION, "slot": 0},
                {"path": AMALGAM_SERRATION, "slot": 1},
            ],
        })

    # Barrel Diffusion + Galvanized Diffusion + Amalgam Barrel Diffusion share family
    assert (
        canonical_mod_family(BARREL_DIFFUSION)
        == canonical_mod_family(GALVANIZED_DIFFUSION)
        == canonical_mod_family(AMALGAM_BARREL_DIFFUSION)
    )

    # Melee: Fury + Berserker Fury rejected; Primed Fury + Quickening allowed!
    assert (
        canonical_mod_family(FURY)
        == canonical_mod_family(PRIMED_FURY)
        == canonical_mod_family(BERSERKER_FURY)
    )
    assert canonical_mod_family(PRIMED_FURY) != canonical_mod_family(QUICKENING)

    with pytest.raises(SimulationError):
        app.simulate_manual_payload({
            "weapon": SKANA,
            "enemy": ENEMY,
            "mods": [
                {"path": FURY, "slot": 0},
                {"path": BERSERKER_FURY, "slot": 1},
            ],
        })

    melee_ok = app.simulate_manual_payload({
        "weapon": SKANA,
        "enemy": ENEMY,
        "slotPolarities": ["AP_ATTACK", "AP_ATTACK", None, None, None, None, None, None],
        "mods": [
            {"path": PRIMED_FURY, "slot": 0},
            {"path": QUICKENING, "slot": 1},
        ],
    })
    assert melee_ok["loadoutValidation"]["valid"] is True

    # Tennokai mods stop right before BaseEmpoweredHeavyMeleeMod -> distinct modFamily == path
    tennokai_rows = [
        m for m in app.CATALOG["utilityMods"]
        if "/EmpoweredHeavyMelee/" in str(m.get("path") or "")
    ]
    assert len(tennokai_rows) >= 5
    for row in tennokai_rows:
        assert row["modFamily"] == row["path"]
        assert canonical_mod_family(row["path"]) == row["path"].lower()


def test_cross_slot_exilus_and_normal_mod_exclusivity_in_simulate_build_and_recommend_riven():
    # 1. Fatal Acceleration (Exilus) + Galvanized Acceleration (normal) share WeaponProjectileSpeedMod
    assert canonical_mod_family(FATAL_ACCELERATION) == canonical_mod_family(GALVANIZED_ACCELERATION)
    assert canonical_mod_family(THUNDERBOLT) == canonical_mod_family(MENDING_SHOT)
    assert canonical_mod_family(CONCEALED_EXPLOSIVES) == canonical_mod_family(ENERGIZING_SHOT)

    # Galvanized Acceleration alone in normal slots is valid; adding Fatal Acceleration in Exilus conflicts!
    cedo_single = app.simulate_manual_payload({
        "weapon": CEDO,
        "enemy": ENEMY,
        "mods": [{"path": GALVANIZED_ACCELERATION, "slot": 0}],
    })
    assert cedo_single["loadoutValidation"]["valid"] is True

    with pytest.raises(SimulationError):
        app.simulate_manual_payload({
            "weapon": CEDO,
            "enemy": ENEMY,
            "mods": [{"path": GALVANIZED_ACCELERATION, "slot": 0}],
            "exilus": {"path": FATAL_ACCELERATION, "rank": 3},
        })
    with pytest.raises(SimulationError):
        app.simulate_manual_payload({
            "weapon": SECURA_PENTA,
            "enemy": ENEMY,
            "mods": [{"path": NAPALM_GRENADES, "slot": 0}],
            "exilus": {"path": TETHER_GRENADES},
        })

    # Thunderbolt + Mending Shot and Concealed Explosives + Energizing Shot conflict in validate_loadout & _evaluate
    dread_rec = optimizer.resolve_record(app.EXPORTS["weapons"], DREAD, kind="weapon")
    hikou_rec = optimizer.resolve_record(app.EXPORTS["weapons"], HIKOU_PRIME, kind="weapon")
    with pytest.raises(SimulationError, match="modFamily"):
        simulator.validate_loadout(
            dread_rec,
            [
                {"path": THUNDERBOLT, "baseDrain": 6, "maxRank": 3, "rank": 3, "polarity": "AP_ATTACK", "slot": 0},
                {"path": MENDING_SHOT, "baseDrain": 2, "maxRank": 0, "rank": 0, "polarity": "AP_DEFENSE", "slot": 1},
            ],
        )
    with pytest.raises(SimulationError, match="modFamily"):
        simulator.validate_loadout(
            hikou_rec,
            [
                {"path": CONCEALED_EXPLOSIVES, "baseDrain": 6, "maxRank": 3, "rank": 3, "polarity": "AP_ATTACK", "slot": 0},
                {"path": ENERGIZING_SHOT, "baseDrain": 2, "maxRank": 0, "rank": 0, "polarity": "AP_ATTACK", "slot": 1},
            ],
        )

    # 2. /api/build: explicitly requiring Galvanized Acceleration while locking Fatal Acceleration in Exilus raises SimulationError
    with pytest.raises(SimulationError):
        app.build_weapon_payload({
            "weapon": CEDO,
            "profile": "fast",
            "requiredMods": [GALVANIZED_ACCELERATION],
            "exilus": {"path": FATAL_ACCELERATION, "rank": 3},
        })

    # 3. /api/build: when Fatal Acceleration is locked in Exilus, auto-optimizer never picks Galvanized Acceleration in normal slots
    built_with_exilus = app.build_weapon_payload({
        "weapon": CEDO,
        "profile": "fast",
        "exilus": {"path": FATAL_ACCELERATION, "rank": 3},
    })
    picked_paths = {m["path"] for m in built_with_exilus["build"]["mods"]}
    assert GALVANIZED_ACCELERATION not in picked_paths
    assert built_with_exilus["exilus"]["path"] == FATAL_ACCELERATION

    # 4. /api/build: when Galvanized Acceleration is in normal slots, _auto_exilus never picks Fatal Acceleration
    built_with_galv = app.build_weapon_payload({
        "weapon": CEDO,
        "profile": "fast",
        "requiredMods": [GALVANIZED_ACCELERATION],
    })
    assert GALVANIZED_ACCELERATION in {m["path"] for m in built_with_galv["build"]["mods"]}
    if built_with_galv.get("exilus"):
        assert built_with_galv["exilus"]["path"] != FATAL_ACCELERATION

    # 5. /api/recommend-riven: respects locked Exilus family and never collides in recommended builds
    rec = app.recommend_riven_payload({
        "weapon": CEDO,
        "budget": 1.0,
        "topLimit": 3,
        "exilus": {"path": FATAL_ACCELERATION, "rank": 3},
    })
    assert rec["combos"]
    for combo in rec["combos"]:
        combo_paths = {m["path"] for m in combo["build"]["mods"]}
        assert GALVANIZED_ACCELERATION not in combo_paths


def test_grimoire_vs_noctua_invocation_and_canticle_exclusivity():
    # Normal Grimoire restricts to 1 Invocation (BaseStrikeMod) + 1 Canticle (BaseAuraMod)
    assert canonical_mod_family(XATA_INVOCATION, equip_path=GRIMOIRE) == "/lotus/upgrades/grimoire/basestrikemod"
    assert canonical_mod_family(RIS_INVOCATION, equip_path=GRIMOIRE) == "/lotus/upgrades/grimoire/basestrikemod"
    assert canonical_mod_family(FASS_CANTICLE, equip_path=GRIMOIRE) == "/lotus/upgrades/grimoire/baseauramod"
    assert canonical_mod_family(JAHU_CANTICLE, equip_path=GRIMOIRE) == "/lotus/upgrades/grimoire/baseauramod"

    # Dante's Noctua (ExaltedBook) adds BaseStrikeMod & BaseAuraMod as additional generic bases -> distinct per-mod families!
    assert canonical_mod_family(XATA_INVOCATION, equip_path=NOCTUA) == XATA_INVOCATION.lower()
    assert canonical_mod_family(RIS_INVOCATION, equip_path=NOCTUA) == RIS_INVOCATION.lower()
    assert canonical_mod_family(FASS_CANTICLE, equip_path=NOCTUA) == FASS_CANTICLE.lower()
    assert canonical_mod_family(JAHU_CANTICLE, equip_path=NOCTUA) == JAHU_CANTICLE.lower()

    grimoire_rec = optimizer.resolve_record(app.EXPORTS["weapons"], GRIMOIRE, kind="weapon")
    noctua_rec = optimizer.resolve_record(app.EXPORTS["weapons"], NOCTUA, kind="weapon")

    xata_dict = {"path": XATA_INVOCATION, "baseDrain": 4, "maxRank": 3, "rank": 3, "polarity": "AP_TACTIC", "slot": 0}
    ris_dict = {"path": RIS_INVOCATION, "baseDrain": 4, "maxRank": 3, "rank": 3, "polarity": "AP_ATTACK", "slot": 1}
    fass_dict = {"path": FASS_CANTICLE, "baseDrain": 4, "maxRank": 3, "rank": 3, "polarity": "AP_DEFENSE", "slot": 1}

    # simulator.validate_loadout: Grimoire rejects 2 Invocations, allows 1 Invocation + 1 Canticle; Noctua allows 2 Invocations
    with pytest.raises(SimulationError, match="modFamily"):
        simulator.validate_loadout(grimoire_rec, [xata_dict, ris_dict])

    grim_mixed = simulator.validate_loadout(grimoire_rec, [xata_dict, fass_dict])
    assert grim_mixed["valid"] is True

    noctua_dual = simulator.validate_loadout(noctua_rec, [xata_dict, ris_dict])
    assert noctua_dual["valid"] is True

    # optimizer._evaluate: Grimoire returns None on 2 Invocations, Noctua evaluates cleanly
    grim_mode, _ = optimizer._select_fire_mode(grimoire_rec, 0, weapon_type="secondary")
    noct_mode, _ = optimizer._select_fire_mode(noctua_rec, 0, weapon_type="secondary")
    xata_card = optimizer._Card(key=XATA_INVOCATION, record=xata_dict, rank=3, effects=(), skipped=(), drain=7, polarity="AP_TACTIC")
    ris_card = optimizer._Card(key=RIS_INVOCATION, record=ris_dict, rank=3, effects=(), skipped=(), drain=7, polarity="AP_ATTACK")

    assert optimizer._evaluate(grim_mode, (xata_card, ris_card), None, scenario=Scenario(), metric="sustainedDps") is None
    noct_eval = optimizer._evaluate(noct_mode, (xata_card, ris_card), None, scenario=Scenario(), metric="sustainedDps")
    assert noct_eval is not None


def test_companion_retrievers_sentinel_regen_and_catalog_mod_families():
    # 1. Companions catalog: Loyal / Prosperous / Resourceful Retriever all share BeastLoyalRetriever
    comp_cat = json.loads((ROOT / "data/mechanics/companions-catalog.json").read_text(encoding="utf-8"))
    body_by_path = {m["path"]: m for m in comp_cat["bodyMods"]}
    for ret_path in (LOYAL_RETRIEVER, PROSPEROUS_RETRIEVER, RESOURCEFUL_RETRIEVER):
        assert body_by_path[ret_path]["family"] == LOYAL_RETRIEVER

    # All bodyMods and clawMods carry authoritative /Lotus/... family paths
    for row in (*comp_cat["bodyMods"], *comp_cat["clawMods"]):
        assert isinstance(row.get("family"), str) and row["family"].startswith("/Lotus/")

    # Equipping any two Retrievers on a Beast raises SimulationError
    for r1, r2 in itertools.combinations((LOYAL_RETRIEVER, PROSPEROUS_RETRIEVER, RESOURCEFUL_RETRIEVER), 2):
        with pytest.raises(SimulationError):
            companion_loadout.evaluate_companion({
                "path": SMEETA_KAVAT,
                "mods": [{"path": r1, "slot": 0}, {"path": r2, "slot": 1}],
            })

    # 2. Sentinel: Regen + Primed Regen share /Lotus/Types/Sentinels/SentinelPrecepts/Regen and conflict in sentinel.py
    sent_cat = sentinel.catalog()
    sent_mods = {m["path"]: m for m in sent_cat["mods"]}
    assert sent_mods[REGEN]["modFamily"] == REGEN
    assert sent_mods[PRIMED_REGEN]["modFamily"] == REGEN

    with pytest.raises(SimulationError, match="modFamily"):
        sentinel.evaluate({
            "path": DETHCUBE,
            "mods": [
                {"path": REGEN, "slot": 0},
                {"path": PRIMED_REGEN, "slot": 1},
            ],
        })

    # 3. Every catalog surface exposes clean authoritative modFamily (never suffixed with #compatibility)
    for group_name, rows in (
        ("manualMods", app.CATALOG["manualMods"]),
        ("manualModVariants", app.CATALOG["manualModVariants"]),
        ("utilityMods", app.CATALOG["utilityMods"]),
        ("warframeMods", app.WARFRAME_CATALOG["mods"]),
        ("sentinelMods", sent_cat["mods"]),
    ):
        assert rows, f"{group_name} is empty"
        for row in rows:
            fam = row.get("modFamily")
            assert isinstance(fam, str) and fam.startswith("/Lotus/") and "#" not in fam, (
                f"{group_name} row {row.get('path')} has invalid modFamily={fam!r}"
            )

    extra_bases = equipment_additional_bases()
    assert app.CATALOG["buildOptions"]["equipmentAdditionalBases"] == extra_bases
    assert app.WARFRAME_CATALOG["equipmentAdditionalBases"] == extra_bases
    assert NOCTUA in extra_bases
    assert JADE in extra_bases
