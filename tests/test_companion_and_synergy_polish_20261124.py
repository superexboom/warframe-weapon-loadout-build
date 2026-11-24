from __future__ import annotations

import pytest

import app
from wfarsenal.simulator import SimulationError


MIRAGE_PRIME = "/Lotus/Powersuits/Harlequin/MiragePrime"
NAUTILUS_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/NautilusPrimeSentinelPowerSuit"
VERGLAS_PRIME = "/Lotus/Types/Sentinels/SentinelWeapons/SentinelFreezeRayPrimeRifle"
PANZER_VULPAPHYLA = "/Lotus/Types/Friendly/Pets/CreaturePets/ArmoredInfestedCatbrowPetPowerSuit"


def test_companion_catalog_exposes_disposition_riven_type_and_moa_melee() -> None:
    cat = app.companion_catalog_payload()
    weapons = {row["path"]: row for row in cat["companionWeapons"]}
    verglas_p = weapons[VERGLAS_PRIME]
    assert verglas_p["disposition"] > 0.0
    assert verglas_p["rivenType"] == "rifle"
    assert "ancestry" in verglas_p

    moa_melee = weapons["/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/MoaPetMeleeWeapon"]
    assert moa_melee["isVirtualMoaMelee"] is True


def test_verglas_prime_user_screenshot_loadout_clamps_negative_crit_and_returns_composition() -> None:
    """Reproduce the exact Verglas Prime + Nautilus Prime + Mirage Prime build from user screenshot."""
    cat = app.companion_catalog_payload()
    body_by_zh = {row["nameZh"]: row for row in cat["bodyMods"] if row.get("nameZh")}
    body_names = [
        "突击模式",
        "双影连结",
        "防线封锁",
        "吸取",
        "传染连结",
        "强固连结",
        "过热射击",
        "加速充能",
        "精算蓄能",
        "领袖 Prime",
    ]
    body_mods = [
        {"path": body_by_zh[name]["path"], "rank": int(body_by_zh[name]["maxRank"]), "slot": idx}
        for idx, name in enumerate(body_names)
        if name in body_by_zh
    ]
    assert len(body_mods) >= 8

    weap_by_zh = {
        row["nameZh"]: row
        for row in app.MANUAL_MODS
        if row.get("nameZh") and "Rifle" in str(row.get("path") or "")
    }
    weapon_names = ["致命火力", "白霜弹头", "地狱火", "野火", "铝热焊弹", "分裂膛室", "步枪元素师"]
    weapon_mods = [
        {"path": weap_by_zh[name]["path"], "rank": int(weap_by_zh[name]["maxRank"]), "slot": idx}
        for idx, name in enumerate(weapon_names)
    ]

    payload = {
        "companion": {
            "path": NAUTILUS_PRIME,
            "reactor": True,
            "mods": body_mods,
            "options": {"firedUp": True},
        },
        "weapon": {
            "path": VERGLAS_PRIME,
            "reactor": True,
            "companionPlayerStacks": True,
            "mods": weapon_mods,
            "riven": {
                "slot": 7,
                "polarity": "AP_ATTACK",
                "stats": [
                    {"code": "D", "value": 204.2, "negative": False},
                    {"code": "8", "value": 111.4, "negative": False},
                    {"code": "SD", "value": 111.4, "negative": False},
                    {"code": "0", "value": 121.5, "negative": True},
                ],
            },
        },
        "warframeLink": {
            "enabled": True,
            "frameId": MIRAGE_PRIME,
            "configName": "A",
            "config": {
                "normalMods": [
                    {"path": "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModC", "rank": 10},
                    {"path": "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModA", "rank": 10},
                    {"path": "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityEfficiencyModExpert", "rank": 10},
                ],
            },
        },
        "target": {
            "level": 170,
            "steelPath": True,
        },
    }
    res = app.companion_evaluate_payload(payload)
    wp = res["weapon"]
    # -121.5% CC on Verglas Prime must clamp cleanly to 0.0%, never -3.0% (-0.0301).
    assert wp["critChance"] == 0.0
    assert wp["perProjectileDamage"] == pytest.approx(516.7, abs=0.5)
    assert wp["totalDamage"] == pytest.approx(wp["perProjectileDamage"] * wp["multishot"], abs=0.5)
    assert wp["averageHit"] > 0.0
    assert wp["burstDps"] > 0.0
    assert wp["sustainedDps"] > 0.0
    assert wp["dotDps"] > 0.0
    assert wp["totalSustainedDps"] == pytest.approx(wp["sustainedDps"] + wp["dotDps"], abs=1e-2)
    assert wp["statusDamageMultiplier"] > 2.5

    comp = wp["damageComposition"]
    assert len(comp) == 2
    dtypes = {row["damageType"]: row for row in comp}
    assert set(dtypes.keys()) == {"DT_FIRE", "DT_VIRAL"}
    assert pytest.approx(sum(row["share"] for row in comp), abs=1e-4) == 1.0
    assert dtypes["DT_FIRE"]["procsPerSecond"] > 5.0
    assert wp["targetEvaluation"]["totalTargetDps"] > 0.0
    assert wp["targetEvaluation"]["sustainedDotDps"] > 0.0
    # Reinforced Bond active at 1,225 shield with Mirage Prime + Calculated Redirection
    assert res["stats"]["shield"]["modded"] >= 1200
    assert res["playerBridge"]["reinforcedBond"]["staticActive"] is True


def test_companion_optimize_weapon_route_for_robotic_and_beast_claws() -> None:
    rob_opt = app.companion_optimize_weapon_payload({
        "companion": {"path": NAUTILUS_PRIME, "reactor": True},
        "weapon": {
            "path": VERGLAS_PRIME,
            "reactor": True,
            "riven": {
                "slot": 7,
                "polarity": "AP_ATTACK",
                "stats": [
                    {"code": "0", "value": 95.0, "negative": False},
                    {"code": "8", "value": 60.0, "negative": False},
                ],
            },
        },
        "goal": "tenaciousBond",
        "elementTarget": "viral",
    })
    assert len(rob_opt["mods"]) > 0
    assert rob_opt["evaluation"]["weapon"]["critChance"] > 0.5
    assert "DT_VIRAL" in rob_opt["evaluation"]["weapon"]["damageTypes"]
    assert rob_opt["evaluation"]["weapon"]["capacity"]["valid"] is True

    claw_opt = app.companion_optimize_weapon_payload({
        "companion": {"path": PANZER_VULPAPHYLA, "reactor": True},
        "weapon": {"reactor": True},
        "primaryWeaponStats": {"critChance": 1.0, "statusChance": 1.0},
        "goal": "dps",
        "elementTarget": "viral",
    })
    assert len(claw_opt["mods"]) > 0
    assert claw_opt["posture"] is not None
    assert claw_opt["evaluation"]["weapon"]["totalSustainedDps"] > 0.0
    assert claw_opt["evaluation"]["weapon"]["capacity"]["valid"] is True


def test_warframe_mirage_prime_intensify_family_exclusivity_and_primed_streamline() -> None:
    # Primed Streamline alone on Mirage Prime calculates cleanly without errors
    ok_res = app.warframe_calculate_payload({
        "frameId": MIRAGE_PRIME,
        "normalMods": [
            {"path": "/Lotus/Upgrades/Mods/Warframe/Expert/AvatarAbilityEfficiencyModExpert", "rank": 10, "slot": 0},
            {"path": "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModC", "rank": 10, "slot": 1},
        ],
    })
    assert not ok_res["validation"]["errors"]

    # Co-equipping Umbral Intensify + Precision Intensify triggers validation error or SimulationError
    try:
        bad_res = app.warframe_calculate_payload({
            "frameId": MIRAGE_PRIME,
            "normalMods": [
                {"path": "/Lotus/Upgrades/Mods/Sets/Umbra/WarframeUmbraModC", "rank": 10, "slot": 0},
                {"path": "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityFourStrengthMod", "rank": 5, "slot": 1},
            ],
        })
        assert any("互斥" in e or "incompatible" in e.lower() or "同系列" in e for e in bad_res["validation"]["errors"])
    except SimulationError:
        pass
