"""Extract native NPC combat & weapon attack profiles from Packages.bin_H.

Output:
  - data/arena/enemy-attacks.json.gz

Covers:
  1. All runnable and cataloged agents & resolvedAvatarPath entries (STANDARD + EXIMUS)
     in data/arena/enemy-specs.json.gz, plus reverse-matched avatars in data/export/*/enemies.json.
  2. Faction-level fallback archetypes (Grineer, Corpus, Infested, Orokin, Murmur,
     Scaldra, Techrot, Sentient, Narmer, plus enemies.json faction aliases) so any
     MANUAL_ENEMIES target in Arena or 1D Kill Replay resolves cleanly.
  3. Global combat rules from LotusDifficultyTable, *LotusDifficultyTable, NpcAimGraphs,
     NpcAccuracyMods, and TennoDamageController.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "tools"))

from build_companion_catalog import PKG_DAMAGE_KEYS, SmartPackages  # noqa: E402

SCHEMA_VERSION = 1
EXPORT_BUILD = "2026.08.13.13.24"
PACKAGES_BUILD = "2026.10.28.09.54"

DEFAULT_PACKAGES = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\research\arbitration-arena-20261116\artifacts\original\Debug\Packages.bin_H"
)
DEFAULT_ENEMY_SPECS = ROOT / "data" / "arena" / "enemy-specs.json.gz"
DEFAULT_ENEMIES_EXPORT = ROOT / "data" / "export" / EXPORT_BUILD / "enemies.json"
DEFAULT_ENEMY_OVERRIDES = ROOT / "data" / "export" / EXPORT_BUILD / "enemy_overrides.json"
DEFAULT_OUTPUT = ROOT / "data" / "arena" / "enemy-attacks.json.gz"

SCURVE_FACTIONS = {
    "grineer",
    "corpus",
    "scaldra",
    "techrot",
    "narmer",
    "narmerveil",
    "anarch",
}
CLASSIC_FACTIONS = {
    "infested",
    "infestation",
    "orokin",
    "orokin empire",
    "orokinempire",
    "murmur",
    "mitw",
    "sentient",
    "stalker",
    "duviri",
}

RANGED_BEHAVIOR_NAMES = {
    "AttackFromCoverTactic",
    "AttackFromTheOpenBehavior",
    "LotusAttackFromTheOpenBehavior",
    "HoverAttackBehavior",
    "BipedRobotShootBehavior",
    "ControlledShootBehavior",
    "CustomShootBehavior",
    "RangedAttackBehavior",
    "StationaryShootBehavior",
    "TurretAttackBehavior",
    "FlyByAttackBehavior",
    "SentientShootBehavior",
}
MELEE_BEHAVIOR_NAMES = {
    "MeleeTactic",
    "MeleeContinousBehavior",
    "InfestedMeleeBehavior",
    "ChargeMeleeBehavior",
    "KubrowPetCombatBehavior",
    "LeapMeleeBehavior",
    "SentientMeleeBehavior",
    "SuicideAttackBehavior",
}
NON_ATTACKING_AGENT_FRAGMENTS = (
    "ShieldDroneAgent",
    "GasShieldDroneAgent",
    "OrokinShieldDroneAgent",
    "StasisDrone",
    "HealingAncientDrone",
    "ShieldOspreyAgent",
    "PurgatoryGhost",
)


def _rf(val: Any, digits: int = 6) -> float:
    return round(float(val), digits)


def _pair(val: Any, default: tuple[float, float]) -> list[float]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        try:
            a = float(val[0])
            b = float(val[1])
            return [_rf(min(a, b)), _rf(max(a, b))]
        except (TypeError, ValueError):
            pass
    return [_rf(default[0]), _rf(default[1])]


def _classify_damage_curve(faction: str | None, agent_path: str = "", avatar_path: str = "") -> str:
    fac = (faction or "").strip().lower()
    if fac in SCURVE_FACTIONS:
        return "scurve"
    if fac in CLASSIC_FACTIONS:
        return "classic"
    joined = f"{agent_path} {avatar_path}".lower()
    if any(
        k in joined
        for k in (
            "/grineer/",
            "/corpus/",
            "/lasrian/",
            "/wf1999lasrian/",
            "/scaldra/",
            "/techrot/",
            "/wf1999infested/",
            "/1999/",
            "/narmer/",
        )
    ):
        return "scurve"
    if any(
        k in joined
        for k in ("/infested/", "/orokin/", "/mitw/", "/maninthewall/", "/murmur/", "/sentient/", "/corrupted/")
    ):
        return "classic"
    return "scurve"


def _classify_aim_graph(raw_graph: str | None, mode: str, optimal_max: float) -> str:
    if mode != "ranged":
        return "melee"
    name = (raw_graph or "").rsplit("/", 1)[-1].lower()
    if any(k in name for k in ("short", "lowaccuracy")):
        return "short"
    if any(k in name for k in ("long", "sniper")):
        return "long"
    if any(k in name for k in ("medium", "standard", "amalgam", "champion", "allhit")):
        return "medium"
    if optimal_max <= 18.0:
        return "short"
    if optimal_max >= 45.0:
        return "long"
    return "medium"


def _extract_damage_weights(attack_data: dict[str, Any]) -> tuple[float, dict[str, float], float]:
    if not isinstance(attack_data, dict):
        return 0.0, {}, 0.0
    amount = float(attack_data.get("Amount") or 0.0)
    proc = float(attack_data.get("ProcChance") or 0.0)
    proc = max(0.0, min(1.0, proc))
    raw_types = {
        dt: float(attack_data[dt])
        for dt in PKG_DAMAGE_KEYS
        if isinstance(attack_data.get(dt), (int, float)) and float(attack_data[dt]) > 0.0
    }
    if not raw_types:
        explicit = attack_data.get("Type")
        if isinstance(explicit, str) and explicit in PKG_DAMAGE_KEYS:
            raw_types = {explicit: 1.0}
        elif amount > 0.0:
            raw_types = {"DT_IMPACT": 1.0}
    total_w = sum(raw_types.values())
    if total_w <= 0.0 or amount <= 0.0:
        return max(0.0, amount), {}, proc
    weights = {dt: _rf(v / total_w) for dt, v in raw_types.items()}
    # Ensure exact sum == 1.0 on largest component
    diff = round(1.0 - sum(weights.values()), 6)
    if diff != 0.0 and weights:
        top_dt = max(weights, key=lambda k: weights[k])
        weights[top_dt] = _rf(weights[top_dt] + diff)
    return amount, weights, proc


def _find_agent_weapons(pkgs: SmartPackages, agent_path: str, weapon_overrides: list[str] | None = None) -> list[tuple[str, int, str]]:
    """Return ordered candidate (hand, force_equip, weapon_path) tuples with Behaviors."""
    candidates: list[tuple[int, str, int, str]] = []
    seen: set[str] = set()

    for ov in weapon_overrides or ():
        wp = pkgs.locate(agent_path, str(ov)) if isinstance(ov, str) else None
        if wp and wp not in seen and "Behaviors" in pkgs.resolve(wp):
            seen.add(wp)
            candidates.append((-1, "OVERRIDE", 1, wp))

    for depth, anc in enumerate(pkgs.ancestry(agent_path)):
        own = pkgs.own(anc)
        for inv_key in ("NewAdditionalInventory", "AdditionalInventory", "Inventory"):
            inv = own.get(inv_key)
            if not isinstance(inv, list):
                continue
            for item in inv:
                if not isinstance(item, dict) or not item.get("item"):
                    continue
                wp = pkgs.locate(anc, str(item["item"]))
                if not wp or wp in seen:
                    continue
                rw = pkgs.resolve(wp)
                if "Behaviors" not in rw:
                    continue
                seen.add(wp)
                hand = str(item.get("hand") or "MAIN_HAND")
                force = int(item.get("forceEquip", 1) or 0)
                candidates.append((depth, hand, force, wp))

        for key in ("RangedWeaponType", "WeaponType", "DefaultWeapon", "MeleeWeaponType", "MainhandWeapon"):
            ref = own.get(key)
            if isinstance(ref, str) and ref:
                wp = pkgs.locate(anc, ref)
                if wp and wp not in seen and "Behaviors" in pkgs.resolve(wp):
                    seen.add(wp)
                    candidates.append((depth, key, 1, wp))

    def _priority(row: tuple[int, str, int, str]) -> tuple[int, int, int]:
        depth, hand, force, wp = row
        low = wp.lower()
        is_aux = "grenade" in low or "/shield/" in low or hand in ("EXTRA1", "OFF_HAND")
        is_dummy_drone = force == 0 and "superdronerifle" in low
        return (2 if is_dummy_drone else (1 if is_aux else 0), depth, 0 if force else 1)

    candidates.sort(key=_priority)
    return [(hand, force, wp) for _depth, hand, force, wp in candidates]


def _none_profile(damage_curve: str, weapon_path: str = "") -> dict[str, Any]:
    return {
        "mode": "none",
        "weaponPath": weapon_path,
        "baseDamage": 0.0,
        "damageTypes": {},
        "statusChance": 0.0,
        "fireRate": 0.0,
        "pellets": 1,
        "burstCount": 1,
        "burstDelay": 0.0,
        "burstTime": [0.0, 0.0],
        "burstPauseTime": [0.0, 0.0],
        "attackSegment": [0.0, 0.0],
        "waitSegment": [1.0, 2.0],
        "clipSize": 0,
        "reloadTime": 0.0,
        "projectileSpeed": 0.0,
        "aoeRadius": 0.0,
        "optimalRange": [0.0, 0.0],
        "maxRange": 0.0,
        "meleeRange": 0.0,
        "aimGraph": "melee",
        "baseHitChance": [0.0, 0.0],
        "damageCurve": damage_curve,
    }


def extract_agent_attack_profile(
    pkgs: SmartPackages,
    agent_path: str,
    *,
    avatar_path: str = "",
    faction: str | None = None,
    weapon_overrides: list[str] | None = None,
) -> dict[str, Any]:
    damage_curve = _classify_damage_curve(faction, agent_path, avatar_path)
    if not pkgs.exists(agent_path):
        return _none_profile(damage_curve)

    agent_row = pkgs.resolve(agent_path)
    agent_name = agent_path.rsplit("/", 1)[-1]
    behavior_db = [
        b.rsplit("/", 1)[-1] for b in (agent_row.get("BehaviorDatabase") or ()) if isinstance(b, str)
    ]
    has_ranged_tactic = any(b in RANGED_BEHAVIOR_NAMES for b in behavior_db) or any(
        k in agent_row for k in ("AttackFromCoverTactic", "AttackFromTheOpenBehavior", "LotusAttackFromTheOpenBehavior", "HoverAttackBehavior")
    )
    has_melee_tactic = any(b in MELEE_BEHAVIOR_NAMES for b in behavior_db) or any(
        k in agent_row for k in ("MeleeTactic", "KubrowPetCombatBehavior")
    )

    if any(frag in agent_name for frag in NON_ATTACKING_AGENT_FRAGMENTS):
        return _none_profile(damage_curve)

    candidates = _find_agent_weapons(pkgs, agent_path, weapon_overrides)
    if not candidates:
        return _none_profile(damage_curve)

    hand, force_equip, weapon_path = candidates[0]
    if force_equip == 0 and "SuperDroneRifle" in weapon_path and "HoverAttackBehavior" not in behavior_db:
        return _none_profile(damage_curve)

    weapon_row = pkgs.resolve(weapon_path)
    behs = weapon_row.get("Behaviors") or []
    if not behs or not isinstance(behs[0], dict):
        return _none_profile(damage_curve, weapon_path)

    b0 = behs[0]
    fire_type = str(b0.get("fire:Type") or "")
    state_type = str(b0.get("state:Type") or "")
    impact_type = str(b0.get("impact:Type") or "")
    fire = next((v for k, v in b0.items() if k.startswith("fire:") and isinstance(v, dict)), {})
    state = next((v for k, v in b0.items() if k.startswith("state:") and isinstance(v, dict)), {})
    impact = next((v for k, v in b0.items() if k.startswith("impact:") and isinstance(v, dict)), {})

    is_melee_weapon = (
        "Melee" in fire_type
        or "Melee" in state_type
        or "TentacleSweep" in fire_type
        or bool(fire.get("IsMeleeBehavior"))
    )
    mode = "melee" if is_melee_weapon else "ranged"

    # Projectile lookup (for projectile damage, flight speed, and AoE explosion radius)
    proj_ref = fire.get("chargedProjectileType") or fire.get("projectileType")
    proj_path = pkgs.locate(weapon_path, str(proj_ref)) if isinstance(proj_ref, str) and proj_ref else None
    proj = pkgs.resolve(proj_path) if proj_path else {}

    proj_ad = proj.get("AttackData") if isinstance(proj.get("AttackData"), dict) else None
    imp_ad = impact.get("AttackData") if isinstance(impact.get("AttackData"), dict) else None
    fire_ad = fire.get("AttackData") if isinstance(fire.get("AttackData"), dict) else None
    chosen_ad = (proj_ad if (proj_ad and isinstance(proj_ad.get("Amount"), (int, float))) else imp_ad) or fire_ad or {}
    raw_amount, damage_types, status_chance = _extract_damage_weights(chosen_ad)
    if status_chance == 0.0 and imp_ad and isinstance(imp_ad.get("ProcChance"), (int, float)):
        status_chance = max(0.0, min(1.0, float(imp_ad["ProcChance"])))

    pellets = max(1, int(fire.get("fireIterations") or 1))
    if fire_type == "/Lotus/Types/Game/LotusWeaponProjectileFireBehavior" and fire.get("IgnoreFireIterations") == 1:
        pellets = 1

    raw_rpm = float(state.get("fireRate") or 60.0)
    raw_sps = max(0.05, raw_rpm / 60.0)
    charge_time = float(state.get("ChargeTime") or state.get("chargeTime") or 0.0)

    # Continuous pre-rework beams store DPS in Amount (e.g. AICrpLaserRifle Flux Rifle = 75 DPS, SuperMoaBeam = 75 DPS).
    is_legacy_continuous = "Continuous" in state_type or "Continuous" in impact_type
    if is_legacy_continuous:
        fire_rate = 10.0
        base_damage = _rf(raw_amount / fire_rate)
        status_chance = _rf(1.0 - ((1.0 - status_chance) ** (1.0 / fire_rate)))
        pellets = 1
    else:
        if charge_time > 0.0:
            fire_rate = _rf(1.0 / (charge_time + (1.0 / raw_sps)))
        else:
            fire_rate = _rf(min(30.0, raw_sps))
        base_damage = _rf(raw_amount * pellets)

    burst_count = max(1, int(state.get("numShots") or state.get("NumShots") or 1))
    raw_bdelay = state.get("burstDelay") if state.get("burstDelay") is not None else state.get("BurstDelay")
    burst_delay = _rf(raw_bdelay if isinstance(raw_bdelay, (int, float)) and raw_bdelay > 0 else (1.0 / raw_sps if burst_count > 1 else 0.0))

    ai = fire.get("AiUsageInfo") or {}
    prefs = ai.get("preferences") or {}
    fp = prefs.get("firingPreferences") or {}
    burst_time = _pair(fp.get("burstTime"), (0.0, 0.0))
    burst_pause = _pair(fp.get("burstPauseTime"), (0.0, 0.0))

    # Agent attack/wait segments
    open_beh = (
        agent_row.get("LotusAttackFromTheOpenBehavior")
        or agent_row.get("AttackFromTheOpenBehavior")
        or {}
    )
    cover_beh = agent_row.get("AttackFromCoverTactic") or {}
    hover_beh = agent_row.get("HoverAttackBehavior") or {}
    biped_beh = agent_row.get("BipedRobotShootBehavior") or {}

    if mode == "melee":
        attack_seg = [1.0, 2.0]
        wait_seg = [0.0, 0.4]
    elif hover_beh.get("FireDuration"):
        attack_seg = _pair(hover_beh.get("FireDuration"), (3.0, 4.0))
        wait_seg = _pair(hover_beh.get("WaitDuration"), (2.0, 3.0))
    else:
        shoot_t = open_beh.get("ShootTime") or cover_beh.get("ShootTime")
        wait_t = biped_beh.get("WaitTime") or open_beh.get("WaitTime") or cover_beh.get("WaitTime")
        attack_seg = _pair(shoot_t, (1.5, 3.0))
        wait_seg = _pair(wait_t, (0.5, 1.5))

    if mode == "melee":
        clip_size = 0
        reload_time = 0.0
    else:
        raw_clip = weapon_row.get("AmmoClipSize")
        clip_size = int(raw_clip) if isinstance(raw_clip, (int, float)) and raw_clip > 0 else 30
        raw_reload = state.get("reloadTime")
        reload_time = _rf(raw_reload) if isinstance(raw_reload, (int, float)) and raw_reload > 0 else 2.0

    proj_speed = 0.0
    if mode == "ranged" and proj_path:
        spd = proj.get("KinematicInitialSpeed") or proj.get("Speed")
        if isinstance(spd, (int, float)) and spd > 0:
            proj_speed = _rf(spd)

    dmg_rad = proj.get("DamageRadius") if proj_path else None
    aoe_radius = _rf(dmg_rad) if isinstance(dmg_rad, (int, float)) and dmg_rad >= 1.0 else 0.0

    # Melee range & optimal/max range
    melee_tactic = agent_row.get("MeleeTactic") or {}
    kubrow_combat = (agent_row.get("KubrowPetCombatBehavior") or {}).get("MeleeContinousBehavior") or {}
    swing_rng = kubrow_combat.get("SwingAttackRange") or melee_tactic.get("AttackRange")
    melee_range = 2.5
    if isinstance(swing_rng, list) and len(swing_rng) >= 2 and isinstance(swing_rng[1], (int, float)) and swing_rng[1] > 0:
        melee_range = _rf(swing_rng[1])
    elif isinstance(swing_rng, (int, float)) and swing_rng > 0:
        melee_range = _rf(swing_rng)

    if mode == "melee":
        optimal_range = [0.0, melee_range]
        max_range = melee_range
        aim_graph = "melee"
        base_hit_chance = [1.0, 1.0]
    else:
        des_range = ai.get("desiredAttackRange") or (agent_row.get("KeepIdealDistanceBehavior") or {}).get("IdealDistance")
        optimal_range = _pair(des_range, (5.0, 25.0))
        aim_graph = _classify_aim_graph(ai.get("aimGraph"), mode, optimal_range[1])
        graph_cap = {"short": 25.0, "medium": 45.0, "long": 100.0}[aim_graph]
        trace_dist = fire.get("traceDistance")
        if ("Beam" in fire_type or is_legacy_continuous) and isinstance(trace_dist, (int, float)) and 0 < trace_dist < 200:
            max_range = _rf(trace_dist)
            optimal_range = [_rf(min(optimal_range[0], max_range * 0.5)), _rf(min(optimal_range[1], max_range))]
        else:
            max_range = _rf(max(optimal_range[1], graph_cap))
        base_hit_chance = _pair(agent_row.get("BaseHitChance"), (0.65, 1.0))

    return {
        "mode": mode,
        "weaponPath": weapon_path,
        "baseDamage": base_damage,
        "pelletDamage": _rf(base_damage / pellets) if pellets > 0 else 0.0,
        "damageTypes": damage_types,
        "statusChance": _rf(status_chance),
        "fireRate": fire_rate,
        "pellets": pellets,
        "burstCount": burst_count,
        "burstDelay": burst_delay,
        "burstTime": burst_time,
        "burstPauseTime": burst_pause,
        "attackSegment": attack_seg,
        "waitSegment": wait_seg,
        "clipSize": clip_size,
        "reloadTime": reload_time,
        "projectileSpeed": proj_speed,
        "aoeRadius": aoe_radius,
        "optimalRange": optimal_range,
        "maxRange": max_range,
        "meleeRange": melee_range,
        "aimGraph": aim_graph,
        "baseHitChance": base_hit_chance,
        "damageCurve": damage_curve,
    }


FACTION_FALLBACK_AGENTS: dict[str, tuple[str, str]] = {
    "Grineer": ("/Lotus/Types/Enemies/Grineer/AIWeek/RifleLancer", "Grineer"),
    "Corpus": ("/Lotus/Types/Enemies/Corpus/GasCity/GasRifleSpacemanAgent", "Corpus"),
    "Infested": ("/Lotus/Types/Enemies/Infested/AiWeek/Quadrupeds/Quadruped", "Infested"),
    "Orokin": ("/Lotus/Types/Enemies/Orokin/OrokinRifleLancer", "Orokin"),
    "Murmur": ("/Lotus/Types/Enemies/ManInTheWall/Octopede/Leg/BipedalLegs/MITWOctopedeBipedalLegsAgent", "Murmur"),
    "Scaldra": ("/Lotus/Types/Enemies/WF1999Lasrian/LasrianRifleLancer/LasrianLancer1999Agent", "Scaldra"),
    "Techrot": ("/Lotus/Types/Enemies/WF1999Infested/InfestedJugulus/TechrotBoneBladeAgent", "Techrot"),
    "Sentient": ("/Lotus/Types/Enemies/Sentients/Aerolyst/SentientAerolystAgent", "Sentient"),
    "Narmer": ("/Lotus/Types/Enemies/Corpus/Narmer/KahlNarmerShipMoaDeraAgent", "Narmer"),
}

FACTION_ALIASES: dict[str, str] = {
    "Infestation": "Infested",
    "MITW": "Murmur",
    "Orokin Empire": "Orokin",
    "OrokinEmpire": "Orokin",
    "NarmerVeil": "Narmer",
    "Anarch": "Grineer",
    "Stalker": "Orokin",
    "Duviri": "Orokin",
    "Tenno": "Orokin",
    "Red Veil": "Grineer",
    "Default": "Grineer",
}


def _find_best_agent_by_keywords(pkgs: SmartPackages, must_contain: tuple[str, ...]) -> str | None:
    matches = [
        p
        for p in sorted(pkgs.entities)
        if p.startswith("/Lotus/Types/Enemies/")
        and all(kw.lower() in p.lower() for kw in must_contain)
        and "Avatar" not in p.rsplit("/", 1)[-1]
        and "Controller" not in p.rsplit("/", 1)[-1]
    ]
    for cand in matches:
        if _find_agent_weapons(pkgs, cand):
            return cand
    return None


def build_global_rules(pkgs: SmartPackages) -> dict[str, Any]:
    short_g = pkgs.resolve("/EE/Types/Npc/WeaponAimGraphs/ShortAimGraph")
    med_g = pkgs.resolve("/EE/Types/Npc/WeaponAimGraphs/MediumAimGraph")
    long_g = pkgs.resolve("/EE/Types/Npc/WeaponAimGraphs/LongAimGraph")
    acc_mods = pkgs.resolve("/EE/Types/Npc/NpcAccuracyMods")
    tdc = pkgs.resolve("/Lotus/Types/Player/TennoDamageController")

    return {
        "levelCurves": {
            "scurve": {
                "kind": "smoothstep_blend",
                "blendRange": [1.0, 25.0],
                "lowMultiplier": 0.015,
                "lowExponent": 1.75,
                "highMultiplier": 0.0075,
                "highExponent": 1.55,
            },
            "classic": {
                "kind": "power",
                "multiplier": 0.015,
                "exponent": 1.55,
            },
        },
        "eximusDamageMultiplier": 1.2,
        "aimGraphs": {
            "short": {
                "distance": [_rf(x) for x in (short_g.get("Distance") or [0.5, 2.0, 10.0, 20.0])],
                "accuracy": [_rf(x) for x in (short_g.get("Accuracy") or [0.30, 1.0, 1.0, 0.0])],
            },
            "medium": {
                "distance": [_rf(x) for x in (med_g.get("Distance") or [2.0, 5.0, 15.0, 40.0])],
                "accuracy": [_rf(x) for x in (med_g.get("Accuracy") or [0.30, 0.80, 0.80, 0.0])],
            },
            "long": {
                "distance": [_rf(x) for x in (long_g.get("Distance") or [5.0, 20.0, 35.0, 100.0])],
                "accuracy": [_rf(x) for x in (long_g.get("Accuracy") or [0.0, 0.90, 0.90, 0.0])],
            },
            "melee": {
                "distance": [0.0, 3.0, 4.0, 5.0],
                "accuracy": [1.0, 1.0, 0.0, 0.0],
            },
        },
        "levelAccuracyScale": [
            {"maxLevel": 15, "scale": 0.45},
            {"maxLevel": 25, "scale": 0.60},
            {"maxLevel": 40, "scale": 0.70},
            {"maxLevel": 60, "scale": 0.85},
            {"maxLevel": 75, "scale": 1.00},
        ],
        "npcAccuracyMods": {
            "dodgeAirAdjust": _rf(acc_mods.get("DodgeAirAdjust", 0.60)),
            "velocityRange": [_rf(x) for x in (acc_mods.get("VelocityAdjustRange") or [8.25, 12.0])],
            "velocityMaxAdjust": _rf(acc_mods.get("VelocityMaxAdjust", 0.50)),
            "slideAdjust": _rf(acc_mods.get("SlideAdjust", 0.30)),
            "cloakAdjust": _rf(acc_mods.get("CloakAdjust", 0.30)),
            "wallrunAdjust": _rf(acc_mods.get("WallrunAdjust", 0.45)),
            "crouchAdjust": _rf(acc_mods.get("CrouchAdjust", 0.05)),
            "dodgeDamageMultiplier": 0.25,
        },
        "tennoShieldRules": {
            "shieldDamageMult": 0.5,
            "gateMin": _rf(tdc.get("ShieldGateDuration", 0.33), 2),
            "gateMax": 2.50,
            "gateFullShield": _rf(tdc.get("ShieldValueForFullShieldGateDuration", 1150.0), 1),
            "gateExp": _rf(tdc.get("ShieldGateTimerCurveExponent", 0.65), 2),
            "catalyzingShieldsFullGate": 1.33,
            "overguardGate": _rf(tdc.get("OverguardDepletedImmunityDuration", 0.50), 2),
            "rechargeBase": _rf(tdc.get("ShieldRechargeRate", 15.0), 2),
            "rechargePct": _rf(tdc.get("ShieldRechargePercent", 0.05), 4),
            "delayPartial": _rf(tdc.get("ShieldRechargeDelay", 1.0), 2),
            "delayDepleted": 4.0,
            "delayMinMult": 0.20,
            "maxOvershield": _rf(tdc.get("MaxOvershield", 1200.0), 1),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    parser.add_argument("--enemy-specs", type=Path, default=DEFAULT_ENEMY_SPECS)
    parser.add_argument("--enemies-export", type=Path, default=DEFAULT_ENEMIES_EXPORT)
    parser.add_argument("--enemy-overrides", type=Path, default=DEFAULT_ENEMY_OVERRIDES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pkgs = SmartPackages(args.packages)
    specs_payload = json.load(gzip.open(args.enemy_specs, "rt", encoding="utf-8"))
    enemies_export = json.loads(args.enemies_export.read_text(encoding="utf-8"))["data"]
    overrides = json.loads(args.enemy_overrides.read_text(encoding="utf-8"))
    if isinstance(overrides, dict) and "data" in overrides:
        overrides = overrides["data"]
    faction_by_avatar = {
        e["path"]: str((overrides.get(e["path"]) or {}).get("faction") or e.get("faction") or "")
        for e in enemies_export
    }

    agents_map: dict[str, dict[str, Any]] = {}
    avatars_map: dict[str, dict[str, Any]] = {}

    # 1. Extract all agents and resolved avatars from enemy-specs.json.gz
    for spec in specs_payload.get("specs") or ():
        for entry in spec.get("enemies") or ():
            ag = entry.get("agent")
            av = entry.get("resolvedAvatarPath") or ""
            if not ag:
                continue
            std_var = (entry.get("avatarVariants") or {}).get("STANDARD") or {}
            fac = std_var.get("frozenFaction") or faction_by_avatar.get(av) or ""
            if ag not in agents_map:
                agents_map[ag] = extract_agent_attack_profile(
                    pkgs,
                    ag,
                    avatar_path=av,
                    faction=fac,
                    weapon_overrides=entry.get("weaponOverrides"),
                )
            prof = agents_map[ag]
            if av and av not in avatars_map:
                avatars_map[av] = dict(prof)
            for var in (entry.get("avatarVariants") or {}).values():
                if isinstance(var, dict) and var.get("resolvedAvatarPath"):
                    vpath = var["resolvedAvatarPath"]
                    if vpath not in avatars_map:
                        avatars_map[vpath] = dict(prof)

    # 2. Reverse-index all NPC agents in Packages.bin_H to match MANUAL_ENEMIES avatars directly
    export_avatar_set = set(faction_by_avatar)
    for ent_path in sorted(pkgs.entities):
        if not ent_path.startswith("/Lotus/Types/Enemies/"):
            continue
        if "Agent" not in ent_path and "/Avatars/" in ent_path:
            continue
        own = pkgs.own(ent_path)
        av_types = own.get("AvatarTypes")
        if not isinstance(av_types, dict):
            continue
        for raw_av in av_types.values():
            if not isinstance(raw_av, str) or not raw_av:
                continue
            resolved_av = pkgs.locate(ent_path, raw_av)
            if resolved_av and resolved_av in export_avatar_set and resolved_av not in avatars_map:
                fac = faction_by_avatar.get(resolved_av) or ""
                avatars_map[resolved_av] = extract_agent_attack_profile(
                    pkgs, ent_path, avatar_path=resolved_av, faction=fac
                )

    # 3. Build faction-level fallback archetypes
    fallback_keyword_search = {
        "Grineer": ("Grineer", "RifleLancer"),
        "Corpus": ("Corpus", "GasRifleSpacemanAgent"),
        "Infested": ("Infested", "Quadruped"),
        "Orokin": ("Orokin", "RifleLancer"),
        "Murmur": ("MITW", "Agent"),
        "Scaldra": ("Lasrian", "Agent"),
        "Techrot": ("Techrot", "Agent"),
        "Sentient": ("Sentients", "Battalyst"),
        "Narmer": ("Narmer", "Lancer"),
    }
    faction_fallbacks: dict[str, dict[str, Any]] = {}
    for canonical, (pref_agent, fac_name) in FACTION_FALLBACK_AGENTS.items():
        ag = pref_agent if (pkgs.exists(pref_agent) and _find_agent_weapons(pkgs, pref_agent)) else None
        if not ag:
            ag = _find_best_agent_by_keywords(pkgs, fallback_keyword_search[canonical])
        if not ag and canonical == "Techrot":
            ag = _find_best_agent_by_keywords(pkgs, ("1999", "Infested", "Agent"))
        if not ag and canonical == "Scaldra":
            ag = _find_best_agent_by_keywords(pkgs, ("1999", "Agent"))
        if not ag and canonical == "Sentient":
            ag = _find_best_agent_by_keywords(pkgs, ("Sentients", "Agent"))
        if not ag:
            # Ultimate safety fallback to Grineer/Infested archetype with faction's curve
            base_key = "Infested" if canonical in ("Techrot", "Murmur") else "Grineer"
            prof = dict(faction_fallbacks[base_key])
            prof["damageCurve"] = _classify_damage_curve(fac_name)
        else:
            prof = extract_agent_attack_profile(pkgs, ag, faction=fac_name)
            if prof["mode"] == "none":
                prof = dict(faction_fallbacks.get("Grineer") or _none_profile(_classify_damage_curve(fac_name)))
                prof["damageCurve"] = _classify_damage_curve(fac_name)
        faction_fallbacks[canonical] = prof

    for alias, target in FACTION_ALIASES.items():
        faction_fallbacks[alias] = dict(faction_fallbacks[target])

    enemies_merged = {**avatars_map, **agents_map}
    rules = build_global_rules(pkgs)

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "buildLabel": PACKAGES_BUILD,
        "frozenEnemyBuild": EXPORT_BUILD,
        "packagesSha256": pkgs.sha256,
        "counts": {
            "agents": len(agents_map),
            "avatars": len(avatars_map),
            "enemiesMerged": len(enemies_merged),
            "factionFallbacks": len(faction_fallbacks),
            "rangedAgents": sum(1 for v in agents_map.values() if v["mode"] == "ranged"),
            "meleeAgents": sum(1 for v in agents_map.values() if v["mode"] == "melee"),
            "noneAgents": sum(1 for v in agents_map.values() if v["mode"] == "none"),
        },
        **rules,
        "rules": rules,
        "agents": agents_map,
        "avatars": avatars_map,
        "enemies": enemies_merged,
        "factionFallbacks": faction_fallbacks,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(payload, fh, ensure_ascii=False, separators=(",", ":"))
    print(json.dumps(payload["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
