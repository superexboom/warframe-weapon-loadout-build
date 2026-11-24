"""Cross-entity Synergy Coordinator (Warframe + Companion -> Player Weapon).

Bridges ``WarframeEngine.calculate`` and ``companion_loadout.evaluate_companion``
into the Panel Solver, 1D Kill/Window Replay, Riven/Build Optimizer, and Arena
context while keeping a zero-allocation neutral fast path when unlinked.
"""

from __future__ import annotations

import copy
from functools import lru_cache
import gzip
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import companion_loadout
from . import exalted as exalted_weapons
from .damage import (
    ModEffect,
    ModEffectList,
    Scenario,
    apply_mods,
    scenario_with,
)
from .simulator import SimulationError


PRIMARY_FROSTBITE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/PrimaryCritDmgAndMultishotOnColdProc"
CASCADIA_FLARE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryDamageOnHeatProc"
SECONDARY_SHIVER_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryExtraDamagePerFreezeStack"
SECONDARY_FORTIFIER_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryDamageToOverguard"

ARCANE_AVENGER_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/CritChanceOnDamage"
ARCANE_GUARDIAN_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/ArmourOnDamage"
ARCANE_TRUCULENCE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/RadialViralAttackOnOverguardGain"
ARCANE_HOT_SHOT_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/AbilityHeatProcsGiveCritChance"
ARCANE_CREPUSCULAR_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Utility/AbilityStrengthAndCritDamageWhenInvisible"
ARCANE_ARACHNE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Utility/GolemArcaneBonusDamageOnWallLatch"
ARCANE_BATTERY_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/MaxEnergyForArmor"
MOLT_EFFICIENCY_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Zariman/WarframeOnShieldUptimePowerDuration"

SNIPER_ANCESTRY = "/Lotus/Weapons/Tenno/Rifle/LotusSniperRifle"
MELEE_ANCESTRY = "/Lotus/Types/Game/LotusMeleeWeapon"

_ABILITY_FAMILIES: dict[str, str] = {
    "roar": "roar",
    "roar-helminth": "roar",
    "eclipse": "eclipse",
    "eclipse-helminth": "eclipse",
    "nourish": "nourish",
    "nourish-helminth": "nourish",
    "warcry": "warcry",
    "warcry-helminth": "warcry",
    "wrathful-advance": "wrathful",
    "wrathful-advance-helminth": "wrathful",
    "sentient-wrath": "sentient-wrath",
    "sentient-wrath-helminth": "sentient-wrath",
    "webbed-embrace": "webbed-embrace",
    "webbed-embrace-helminth": "webbed-embrace",
}

_SHIELD_RESTORING_ABILITIES = frozenset({
    "pillage",
    "condemn",
    "rebuild-shields",
    "covenant",
    "crush",
    "polarize",
    "blessing",
    "proteas-grenade-fan",
})

_OVERGUARD_ABILITIES = frozenset({
    "iron-skin",
    "icy-avalanche",
    "intrepid-stand",
    "recompense",
    "light-verse",
    "triumph",
})

_INVISIBILITY_ABILITIES = frozenset({
    "evade",
    "prowl",
    "invisibility",
    "smoke-screen",
    "metronome",
})

_FACTION_FALLBACK_KEYS: dict[str, str] = {
    "grineer": "Grineer",
    "rk_grineer_faction": "Grineer",
    "kuva grineer": "Grineer",
    "corpus": "Corpus",
    "rk_corpus_faction": "Corpus",
    "corpus amalgam": "Corpus",
    "infested": "Infested",
    "rk_infested_faction": "Infested",
    "infestation": "Infested",
    "deimos infested": "Infested",
    "techrot": "Infested",
    "orokin": "Orokin",
    "corrupted": "Orokin",
    "rk_corrupted_faction": "Orokin",
    "sentient": "Sentient",
    "rk_sentient_faction": "Sentient",
    "narmer": "Grineer",
    "murmur": "Murmur",
    "rk_murmur_faction": "Murmur",
    "scaldra": "Grineer",
}


def _root_dir() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


@lru_cache(maxsize=1)
def _load_enemy_attacks() -> dict[str, Any]:
    path = _root_dir() / "data" / "arena" / "enemy-attacks.json.gz"
    if not path.is_file():
        return {}
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        return dict(data) if isinstance(data, Mapping) else {}
    except (OSError, ValueError):
        return {}


def _exalted_has_extended_synergy(payload: Mapping[str, Any], weapon: Mapping[str, Any] | None) -> bool:
    if weapon is None or not (weapon.get("exalted") or weapon.get("isExalted")):
        return False
    link = payload.get("exaltedFrame")
    if not isinstance(link, Mapping):
        return False
    if link.get("activeAbilities") or link.get("damageTriggerMode"):
        return True
    cfg = link.get("config")
    if not isinstance(cfg, Mapping):
        return False
    if cfg.get("shards") or cfg.get("invigoration") or cfg.get("activeAbilities"):
        return True
    # Check if installed Warframe mods carry weapon-relevant set pieces (e.g. Gladiator / Vigilante).
    for row in (cfg.get("aura"), cfg.get("exilus"), *(cfg.get("normalMods") or ())):
        if isinstance(row, Mapping):
            p = str(row.get("path") or row.get("id") or "")
            if "/Sets/" in p:
                return True
    return False


def has_synergy_links(payload: Mapping[str, Any], weapon: Mapping[str, Any] | None = None) -> bool:
    """Zero-allocation check: True only when cross-entity synergy is active."""
    if not isinstance(payload, Mapping):
        return False
    wf_link = payload.get("warframeLink")
    if isinstance(wf_link, Mapping) and wf_link.get("enabled") is True:
        return True
    comp_link = payload.get("companionLink")
    if isinstance(comp_link, Mapping) and comp_link.get("enabled") is True:
        return True
    return _exalted_has_extended_synergy(payload, weapon)


def _interp_piecewise(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    if not xs or not ys or len(xs) != len(ys):
        return 1.0
    if x <= float(xs[0]):
        return float(ys[0])
    if x >= float(xs[-1]):
        return float(ys[-1])
    for i in range(len(xs) - 1):
        x0, x1 = float(xs[i]), float(xs[i + 1])
        y0, y1 = float(ys[i]), float(ys[i + 1])
        if x0 <= x <= x1:
            t = (x - x0) / max(x1 - x0, 1e-9)
            return y0 + t * (y1 - y0)
    return float(ys[-1])


def _eval_level_curve(curves: Mapping[str, Any], curve_name: str, level: int, base_level: int = 1) -> float:
    diff = max(0, int(level) - max(1, int(base_level)))
    if diff <= 0:
        return 1.0
    spec = curves.get(curve_name) if isinstance(curves, Mapping) else None
    if isinstance(spec, Sequence) and spec:
        idx = min(diff, len(spec) - 1)
        val = spec[idx]
        if isinstance(val, (int, float)):
            return max(1.0, float(val))
    # Standard Warframe enemy damage S-curve fallback.
    t1 = min(1.0, max(0.0, (diff - 70.0) / 10.0))
    smooth = t1 * t1 * (3.0 - 2.0 * t1)
    low = 1.0 + 0.015 * (diff ** 1.55)
    high = 1.0 + 0.015 * (70.0 ** 1.55) + 0.045 * max(0.0, diff - 70.0)
    return (1.0 - smooth) * low + smooth * high


def _resolve_enemy_attack_profile(
    ea: Mapping[str, Any],
    enemy_record: Mapping[str, Any] | None,
    enemy_path: str | None,
) -> dict[str, Any] | None:
    if not ea:
        return None
    enemies_map = ea.get("enemies") if isinstance(ea.get("enemies"), Mapping) else {}
    avatars_map = ea.get("avatars") if isinstance(ea.get("avatars"), Mapping) else {}
    fallbacks = ea.get("factionFallbacks") if isinstance(ea.get("factionFallbacks"), Mapping) else {}
    p = str(enemy_path or (enemy_record or {}).get("path") or "").strip()
    if p and p in enemies_map and isinstance(enemies_map[p], Mapping):
        return dict(enemies_map[p])
    if p and p in avatars_map and isinstance(avatars_map[p], Mapping):
        return dict(avatars_map[p])
    for key in ("faction", "factionResistance"):
        raw_fac = str((enemy_record or {}).get(key) or "").strip().casefold()
        mapped = _FACTION_FALLBACK_KEYS.get(raw_fac)
        if mapped and mapped in fallbacks and isinstance(fallbacks[mapped], Mapping):
            return dict(fallbacks[mapped])
        for fb_k, fb_v in fallbacks.items():
            if fb_k.casefold() == raw_fac and isinstance(fb_v, Mapping):
                return dict(fb_v)
    if "Grineer" in fallbacks and isinstance(fallbacks["Grineer"], Mapping):
        return dict(fallbacks["Grineer"])
    return next((dict(v) for v in enemies_map.values() if isinstance(v, Mapping)), None)


def evaluate_incoming_survivability(
    *,
    panel: Mapping[str, Any],
    survivability: Mapping[str, Any],
    enemy_record: Mapping[str, Any] | None,
    enemy_path: str | None,
    level: int,
    distance: float | None,
    eximus: bool,
    damage_trigger_mode: str,
    has_overshield_source: bool,
    overguard_active: bool = False,
) -> dict[str, Any]:
    """Compute incoming enemy hit rate, Tenno shield uptime, and on-damaged uptimes."""
    ea = _load_enemy_attacks()
    prof = _resolve_enemy_attack_profile(ea, enemy_record, enemy_path)
    shield_rules = ea.get("tennoShieldRules") if isinstance(ea.get("tennoShieldRules"), Mapping) else {}

    max_shield = max(0.0, float(panel.get("shield") or 0.0))
    has_shields = max_shield > 0.0
    catalyzing = bool(survivability.get("catalyzingShields"))
    max_overshield = 0.0 if (catalyzing or not has_shields) else float(shield_rules.get("maxOvershield") or 1200.0)
    steady_overshield = max_overshield if (has_overshield_source and not catalyzing and has_shields) else 0.0

    self_damage_on_kill = float(survivability.get("selfDamageOnKill") or 0.0)
    if overguard_active:
        self_damage_on_kill = 0.0

    r_hit = 0.0
    enemy_dps = 0.0
    if prof is not None:
        fire_rate = max(0.0, float(prof.get("fireRate") or 0.0))
        pellets = max(1, int(prof.get("pellets") or 1))
        bt = prof.get("burstTime") or (0.0, 0.0)
        bp = prof.get("burstPauseTime") or (0.0, 0.0)
        mean_bt = 0.5 * (float(bt[0]) + float(bt[1])) if len(bt) >= 2 else 0.0
        mean_bp = 0.5 * (float(bp[0]) + float(bp[1])) if len(bp) >= 2 else 0.0
        if mean_bt > 0.0 and mean_bp > 0.0:
            burst_duty = mean_bt / (mean_bt + mean_bp)
        else:
            at = prof.get("attackSegment") or (0.0, 0.0)
            wt = prof.get("waitSegment") or (0.0, 0.0)
            mean_at = 0.5 * (float(at[0]) + float(at[1])) if len(at) >= 2 else 0.0
            mean_wt = 0.5 * (float(wt[0]) + float(wt[1])) if len(wt) >= 2 else 0.0
            burst_duty = mean_at / (mean_at + mean_wt) if (mean_at > 0.0 and mean_wt > 0.0) else 1.0

        clip_size = int(prof.get("clipSize") or 0)
        reload_time = max(0.0, float(prof.get("reloadTime") or 0.0))
        if clip_size > 0 and reload_time > 0.0 and fire_rate > 0.0:
            mag_time = (clip_size / fire_rate) / max(burst_duty, 1e-6)
            reload_duty = mag_time / (mag_time + reload_time)
        else:
            reload_duty = 1.0

        aim_name = str(prof.get("aimGraph") or "medium")
        aim_graphs = ea.get("aimGraphs") if isinstance(ea.get("aimGraphs"), Mapping) else {}
        graph = aim_graphs.get(aim_name) if isinstance(aim_graphs.get(aim_name), Mapping) else None
        is_melee_enemy = str(prof.get("mode") or "") == "melee" or aim_name == "melee"
        eff_dist = float(distance) if isinstance(distance, (int, float)) else (2.0 if is_melee_enemy else 12.0)
        aim_acc = (
            _interp_piecewise(graph.get("distance") or (), graph.get("accuracy") or (), eff_dist)
            if graph is not None
            else 0.8
        )
        bh = prof.get("baseHitChance") or (0.75, 0.75)
        base_hit = 0.5 * (float(bh[0]) + float(bh[1])) if len(bh) >= 2 else 0.75

        lvl_acc = 1.0
        for row in ea.get("levelAccuracyScale") or ():
            if isinstance(row, Mapping) and int(level) <= int(row.get("maxLevel") or 0):
                lvl_acc = float(row.get("scale") or 1.0)
                break

        evasion = min(0.95, max(0.0, float(survivability.get("evasion") or 0.0)))
        hit_prob = min(1.0, max(0.0, aim_acc * base_hit * lvl_acc)) * (1.0 - evasion)
        r_shots = fire_rate * burst_duty * reload_duty
        r_hit = r_shots * pellets * hit_prob

        pellet_dmg = max(0.0, float(prof.get("pelletDamage") or prof.get("baseDamage") or 0.0))
        base_lvl = int((enemy_record or {}).get("baseLevel") or 1)
        curve_mult = _eval_level_curve(ea.get("levelCurves") or {}, str(prof.get("damageCurve") or "scurve"), level, base_lvl)
        eximus_mult = float(ea.get("eximusDamageMultiplier") or 2.0) if eximus else 1.0
        enemy_dps = r_hit * pellet_dmg * curve_mult * eximus_mult

    # Tenno shield uptime & gate cycle.
    gate_sec = float(survivability.get("shieldGateSeconds") or 0.0)
    depleted_delay = max(0.2, float(survivability.get("shieldDepletedDelay") or 4.0))
    recharge_rate = max(0.0, float(survivability.get("shieldRechargeRate") or 0.0))
    energy_to_shield = float(survivability.get("energyToShieldRatio") or 0.0)
    shield_dmg_mult = float(shield_rules.get("shieldDamageMult") or 0.5)
    adaptation_dr = 0.5 * float(survivability.get("adaptationMaxDr") or 0.0)
    eff_shield_dps = enemy_dps * shield_dmg_mult * (1.0 - adaptation_dr)

    if not has_shields:
        shield_uptime = 0.0
    elif damage_trigger_mode in {"assumed", "off"} or eff_shield_dps <= 1e-6:
        shield_uptime = 1.0
    else:
        pool_shield = max_shield + steady_overshield
        up_sec = pool_shield / eff_shield_dps + gate_sec
        down_sec = 0.35 if (energy_to_shield > 0.0 or has_overshield_source) else depleted_delay
        shield_uptime = min(1.0, max(0.15, up_sec / max(up_sec + down_sec, 1e-6)))

    if damage_trigger_mode == "assumed":
        avenger_uptime = 1.0
        guardian_uptime = 1.0
    elif damage_trigger_mode == "off":
        avenger_uptime = 0.0
        guardian_uptime = 0.0
    else:
        # AI incoming hits + Combat Discipline self-damage on kill (~0.5 kills/s steady conservative floor).
        r_dmg = r_hit + (0.5 if self_damage_on_kill > 0.0 else 0.0)
        avenger_uptime = (1.0 - (1.0 - 0.21) ** (r_dmg * 12.0)) if r_dmg > 0.0 else 0.0
        guardian_uptime = (1.0 - (1.0 - 0.15) ** (r_dmg * 20.0)) if r_dmg > 0.0 else 0.0

    armor = max(0.0, float(panel.get("armor") or 0.0))
    armor_dr = armor / (armor + 300.0) if armor > 0.0 else 0.0
    cap_dps = survivability.get("damageCapPerSecond")
    health_dps = enemy_dps * (1.0 - armor_dr) * (1.0 - adaptation_dr)
    if isinstance(cap_dps, (int, float)) and cap_dps > 0:
        health_dps = min(health_dps, float(cap_dps))

    return {
        "damageTriggerMode": damage_trigger_mode,
        "incomingHitRate": round(r_hit, 6),
        "incomingRawDps": round(enemy_dps, 3),
        "incomingHealthDps": round(health_dps, 3),
        "shieldUptime": round(shield_uptime, 6),
        "shieldGateSeconds": round(gate_sec, 4),
        "rechargeRate": round(recharge_rate, 3),
        "steadyOvershield": round(steady_overshield, 3),
        "selfDamageOnKill": round(self_damage_on_kill, 3),
        "avengerUptime": round(avenger_uptime, 6),
        "guardianUptime": round(guardian_uptime, 6),
        "enemyAttackMode": (prof or {}).get("mode"),
    }


def _normalize_warframe_config(wf_link: Mapping[str, Any]) -> dict[str, Any]:
    nested = wf_link.get("config")
    cfg = dict(nested) if isinstance(nested, Mapping) else {}
    for key in (
        "frameId",
        "id",
        "path",
        "parentConfig",
        "aura",
        "exilus",
        "normalMods",
        "mods",
        "polarities",
        "arcanes",
        "shards",
        "helminth",
        "invigoration",
        "applyConditionals",
    ):
        if key not in cfg and key in wf_link:
            cfg[key] = wf_link[key]
    return cfg


def _normalize_companion_configs(comp_link: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    nested = comp_link.get("config")
    source = nested if isinstance(nested, Mapping) else comp_link
    raw_body = source.get("companion")
    if isinstance(raw_body, Mapping):
        body_cfg = dict(raw_body)
    else:
        body_cfg = {
            k: v
            for k, v in source.items()
            if k not in {"enabled", "weapon", "companionWeapon", "primaryWeapon", "primaryWeaponStats"}
        }
    raw_weapon = source.get("weapon") if "weapon" in source else source.get("companionWeapon")
    if raw_weapon is None and "weapon" in comp_link and isinstance(comp_link.get("weapon"), Mapping):
        raw_weapon = comp_link["weapon"]
    weapon_cfg = dict(raw_weapon) if isinstance(raw_weapon, Mapping) and (raw_weapon.get("path") or raw_weapon.get("id")) else None
    return body_cfg, weapon_cfg


def _companion_needs_primary_probe(body_cfg: Mapping[str, Any], weapon_cfg: Mapping[str, Any] | None) -> bool:
    comp_id = str(body_cfg.get("path") or body_cfg.get("id") or "")
    if not comp_id:
        return False
    cat = companion_loadout.catalog()
    row = next(
        (c for c in cat.get("companions") or () if c.get("path") == comp_id or c.get("id") == comp_id),
        None,
    )
    if row is None or row.get("category") != "beast":
        return False
    if not isinstance(weapon_cfg, Mapping):
        return False
    for m in weapon_cfg.get("mods") or ():
        if isinstance(m, Mapping):
            mp = str(m.get("path") or m.get("id") or "")
            if mp in {
                "/Lotus/Upgrades/Mods/Sets/Hunter/CompanionHunterSynergyMod",
                "/Lotus/Upgrades/Mods/Sets/Mecha/KubrowMechaOverdriveMod",
                "CompanionHunterSynergyMod",
                "KubrowMechaOverdriveMod",
                "companionhuntersynergymod",
                "kubrowmechaoverdrivemod",
            }:
                return True
    return True


def _spec_to_mod_effects(
    fx: Mapping[str, Any],
    *,
    weapon: Mapping[str, Any],
    chosen_element: str | None = None,
    source_override: str | None = None,
) -> tuple[list[ModEffect], dict[str, float]]:
    ut = str(fx.get("upgradeType") or "")
    op = str(fx.get("operation") or "STACKING_MULTIPLY")
    val = float(fx.get("value") or 0.0)
    if not ut or abs(val) <= 1e-12:
        return [], {}

    ancestry = {
        str(p).rstrip("/")
        for p in (*tuple(weapon.get("ancestry") or ()), weapon.get("path"))
        if p
    }
    is_melee = MELEE_ANCESTRY in ancestry or weapon.get("slot") in {"melee", "arch_melee"}
    is_sniper = SNIPER_ANCESTRY in ancestry

    if fx.get("meleeScale") and is_melee:
        val *= float(fx["meleeScale"])
    if fx.get("sniperScale") and is_sniper:
        val *= float(fx["sniperScale"])

    dtype = fx.get("damageType")
    if dtype == "SELECT":
        dtype = chosen_element
    dtype_str = str(dtype) if isinstance(dtype, str) and dtype and dtype != "DT_ANY" else None

    valid_types = fx.get("validTypes")
    if not valid_types and fx.get("validType"):
        valid_types = [fx["validType"]]
    vtypes: Sequence[str | None] = list(valid_types) if isinstance(valid_types, (list, tuple)) and valid_types else (None,)

    valid_proc_types = tuple(str(x) for x in (fx.get("validProcTypes") or ()) if x)
    source = source_override or str(fx.get("source") or "synergy")
    forced_procs: dict[str, float] = {}

    out: list[ModEffect] = []
    for vt in vtypes:
        if ut == "RUNTIME_EXTRA_HIT":
            if not dtype_str:
                continue
            rc = 1.0 if fx.get("forcedProc") else (float(fx["runtimeChance"]) if fx.get("runtimeChance") is not None else None)
            eff = ModEffect(
                upgrade_type="RUNTIME_EXTRA_HIT",
                operation="ADD",
                value=val,
                damage_type=dtype_str,
                valid_type=str(vt) if vt else None,
                source_path=source,
                runtime_chance=rc,
            )
            if eff.supported:
                out.append(eff)
            continue

        eff = ModEffect(
            upgrade_type=ut,
            operation=op,
            value=val,
            damage_type=dtype_str,
            valid_type=str(vt) if vt else None,
            valid_proc_types=valid_proc_types,
            source_path=source,
        )
        if eff.supported:
            out.append(eff)
            if fx.get("forcedProc") and dtype_str:
                # Only apply forcedProc if validType matches this weapon.
                if not vt or str(vt).rstrip("/") in ancestry:
                    forced_procs[dtype_str] = max(forced_procs.get(dtype_str, 0.0), 1.0)
    return out, forced_procs


def _weapon_has_heat(
    weapon: Mapping[str, Any],
    mods: Sequence[Mapping[str, Any]] | None,
    riven: Mapping[str, Any] | None,
    innate_selection: Mapping[str, Any] | None,
    extra_effects: Sequence[ModEffect],
    forced_procs: Mapping[str, float],
    exports: Mapping[str, Any],
) -> bool:
    for mode in weapon.get("fireModes") or ():
        dmg = (mode or {}).get("damage") if isinstance(mode, Mapping) else None
        if isinstance(dmg, Mapping) and float((dmg.get("types") or {}).get("DT_FIRE") or 0.0) > 0.0:
            return True
    if isinstance(innate_selection, Mapping) and innate_selection.get("damageType") == "DT_FIRE":
        return True
    for row in weapon.get("innateElements") or ():
        if isinstance(row, Mapping) and row.get("damageType") == "DT_FIRE":
            return True
    if float(forced_procs.get("DT_FIRE") or 0.0) > 0.0:
        return True
    for eff in extra_effects:
        if eff.damage_type == "DT_FIRE" and eff.value > 0.0:
            return True
    mods_by_path = {str(m.get("path") or ""): m for m in (exports.get("mods") or ()) if isinstance(m, Mapping)}
    for item in mods or ():
        if not isinstance(item, Mapping):
            continue
        rec = mods_by_path.get(str(item.get("path") or ""))
        if not rec:
            continue
        for fx in rec.get("effects") or ():
            if isinstance(fx, Mapping) and fx.get("damageType") == "DT_FIRE" and float(fx.get("valuePerRank") or fx.get("value") or 0.0) > 0.0:
                return True
    if isinstance(riven, Mapping):
        for st in riven.get("stats") or ():
            if isinstance(st, Mapping) and str(st.get("code") or "").upper() == "H" and not st.get("negative"):
                return True
    return False


def _probe_primary_weapon_stats(
    weapon: Mapping[str, Any],
    mods: Sequence[Mapping[str, Any]] | None,
    riven_effects: Sequence[ModEffect],
    passive_effects: Sequence[ModEffect],
    external_set_mods: Sequence[Mapping[str, Any]],
    scenario: Scenario,
    fire_mode: int,
    exports: Mapping[str, Any],
) -> dict[str, float]:
    from . import optimizer

    mod_effects: list[ModEffect] = []
    mods_by_path = {str(m.get("path") or ""): m for m in (exports.get("mods") or ()) if isinstance(m, Mapping)}
    for item in mods or ():
        if not isinstance(item, Mapping):
            continue
        rec = mods_by_path.get(str(item.get("path") or ""))
        if rec is None:
            continue
        max_rank = int(rec.get("maxRank") or 0)
        rank = int(item["rank"]) if isinstance(item.get("rank"), int) and not isinstance(item.get("rank"), bool) else max_rank
        rank = min(max(0, rank), max_rank)
        card = optimizer._mod_card(rec, scenario, allow_empty=True, rank=rank)
        mod_effects.extend(card.effects)
    # Include Vigilante / Hunter set shell effects if applicable.
    all_fx = ModEffectList([*mod_effects, *riven_effects, *passive_effects])
    stats = apply_mods(weapon, all_fx, fire_mode=0, scenario=scenario_with(scenario, victim_status_count=0))
    return {
        "critChance": float(stats.crit_chance),
        "statusChance": float(stats.status_chance),
    }


def build_companion_assister_spec(
    comp_eval: Mapping[str, Any],
    *,
    distance: float | None = None,
) -> dict[str, Any] | None:
    """Build a JSON-serializable 1D replay companion assister schedule."""
    attack_profile = comp_eval.get("attackProfile")
    if not isinstance(attack_profile, Mapping) or not attack_profile.get("canAttack"):
        return None
    weapon_res = comp_eval.get("weapon")
    if not isinstance(weapon_res, Mapping):
        return None
    max_rng = float(attack_profile.get("effectiveMaxRange") or 0.0)
    if isinstance(distance, (int, float)) and max_rng > 0.0 and float(distance) > max_rng + 1e-6:
        return None

    fire_rate = max(0.0, float(weapon_res.get("fireRate") or 0.0))
    if fire_rate <= 0.0:
        return None

    ai_prof = attack_profile.get("aiProfile") if isinstance(attack_profile.get("aiProfile"), Mapping) else {}
    duty = max(0.05, min(1.0, float(ai_prof.get("aiDutyCycle") or 1.0)))
    clone_mult = max(1, int(attack_profile.get("cloneMultiplier") or 1))

    procs_per_shot = {
        str(k): float(v) * clone_mult
        for k, v in (weapon_res.get("expectedProcsPerShot") or {}).items()
        if float(v) > 0.0
    }
    dmg_types = {
        str(k): float(v) * clone_mult
        for k, v in (weapon_res.get("damageTypes") or {}).items()
        if float(v) > 0.0
    }
    radial_dmg = weapon_res.get("radialDamageTypes")
    if isinstance(radial_dmg, Mapping):
        for k, v in radial_dmg.items():
            if float(v) > 0.0:
                dmg_types[str(k)] = dmg_types.get(str(k), 0.0) + float(v) * clone_mult

    manifold = ((comp_eval.get("playerBridge") or {}).get("manifoldBond") or {})
    manifold_precepts: list[dict[str, Any]] = []
    for p in attack_profile.get("offensivePrecepts") or ():
        if not isinstance(p, Mapping):
            continue
        cd = float(p.get("cooldown") or 0.0)
        if cd <= 0.0:
            continue
        p_rng = float(p.get("attackRange") or 0.0)
        if isinstance(distance, (int, float)) and p_rng > 0.0 and float(distance) > p_rng + 1e-6:
            continue
        forced = str(p.get("forcedProc") or "")
        m_types = [str(dt) for dt in (p.get("manifoldStatusTypes") or ()) if dt]
        precept_procs: dict[str, float] = {}
        if forced:
            precept_procs[forced] = 1.0
        for dt in m_types:
            precept_procs[dt] = max(precept_procs.get(dt, 0.0), 1.0)
        p_dmg = float(p.get("damage") or 0.0)
        p_dtype = str(p.get("damageType") or "DT_ELECTRICITY")
        if precept_procs or p_dmg > 0.0:
            manifold_precepts.append({
                "id": str(p.get("id") or p.get("path") or "precept"),
                "cooldown": round(max(1.0, cd), 6),
                "killCooldownReduction": float(manifold.get("cooldownReduction") or 0.0) if manifold.get("equipped") else 0.0,
                "damage": round(p_dmg, 6),
                "damageType": p_dtype,
                "procs": precept_procs,
            })

    wpath_str = str(weapon_res.get("path") or "")
    is_continuous = any(tok in wpath_str for tok in ("FreezeRay", "SentLaser", "Phantasma", "Cycron", "HeliosLaser", "Tazicor"))
    mag_val = weapon_res.get("magazine")
    return {
        "weaponPath": wpath_str,
        "interval": round(1.0 / (fire_rate * duty), 6),
        "fireRate": round(fire_rate, 6),
        "dutyCycle": round(duty, 6),
        "cloneMultiplier": clone_mult,
        "magazine": float(mag_val) if isinstance(mag_val, (int, float)) and mag_val > 0 else 0.0,
        "reloadTime": max(0.0, float(weapon_res.get("reloadTime") or 0.0)),
        "continuous": is_continuous,
        "multishot": max(0.0, float(weapon_res.get("multishot") or 1.0)),
        "critChance": max(0.0, float(weapon_res.get("critChance") or 0.0)),
        "critMultiplier": max(1.0, float(weapon_res.get("critMultiplier") or 1.0)),
        "noncritDamageMultiplier": 1.0,
        "doubleCritChance": 0.0,
        "statusChance": max(0.0, float(weapon_res.get("statusChance") or 0.0)),
        "damageTypes": {k: round(v, 6) for k, v in dmg_types.items()},
        "dotBaseDamage": None,
        "procsPerShot": {k: round(v, 6) for k, v in procs_per_shot.items()},
        "procDurationMultiplier": 1.0,
        "procDamageMultiplier": 1.0,
        "dotElementalMultipliers": {},
        "factionDamageMultipliers": {},
        "armorStripOnHit": round(float(weapon_res.get("armorStripOnHit") or 0.0), 6),
        "shiveringContagion": bool(weapon_res.get("shiveringContagionEquipped")),
        "manifoldPrecepts": manifold_precepts,
    }


def resolve_synergy(
    payload: Mapping[str, Any],
    *,
    weapon: Mapping[str, Any],
    warframe_engine: Any,
    exports: Mapping[str, Any],
    external_buff_specs: Mapping[str, Mapping[str, Any]] | None = None,
    enemy_record: Mapping[str, Any] | None = None,
    enemy_path: str | None = None,
    level: int = 160,
    distance: float | None = None,
    eximus: bool = False,
    mods: Sequence[Mapping[str, Any]] | None = None,
    riven: Mapping[str, Any] | None = None,
    riven_effects: Sequence[ModEffect] = (),
    innate_selection: Mapping[str, Any] | None = None,
    base_combat_state: Mapping[str, Any] | None = None,
    explicit_combat_keys: Iterable[str] = (),
    forced_procs: Mapping[str, float] | None = None,
) -> dict[str, Any] | None:
    """Resolve cross-entity Warframe + Companion synergy into solver & replay inputs."""
    if not has_synergy_links(payload, weapon):
        return None

    wf_link_raw = payload.get("warframeLink")
    wf_enabled = isinstance(wf_link_raw, Mapping) and wf_link_raw.get("enabled") is True
    comp_link_raw = payload.get("companionLink")
    comp_enabled = isinstance(comp_link_raw, Mapping) and comp_link_raw.get("enabled") is True

    exalted_legacy_upgrade = (not wf_enabled) and _exalted_has_extended_synergy(payload, weapon)
    wf_source: Mapping[str, Any] | None = None
    if wf_enabled and isinstance(wf_link_raw, Mapping):
        wf_source = wf_link_raw
    elif exalted_legacy_upgrade and isinstance(payload.get("exaltedFrame"), Mapping):
        wf_source = payload["exaltedFrame"]

    damage_trigger_mode = "ai"
    if isinstance(wf_source, Mapping) and wf_source.get("damageTriggerMode") is not None:
        damage_trigger_mode = str(wf_source.get("damageTriggerMode")).strip().casefold()
    elif payload.get("damageTriggerMode") is not None:
        damage_trigger_mode = str(payload.get("damageTriggerMode")).strip().casefold()
    if damage_trigger_mode not in {"ai", "assumed", "off"}:
        raise SimulationError("damageTriggerMode must be 'ai', 'assumed', or 'off'")

    explicit_keys = set(explicit_combat_keys)
    raw_top_cs = payload.get("combatState")
    if isinstance(raw_top_cs, Mapping):
        explicit_keys.update(str(k) for k in raw_top_cs.keys())
    raw_scen = payload.get("scenario")
    if isinstance(raw_scen, Mapping) and isinstance(raw_scen.get("combatState"), Mapping):
        explicit_keys.update(str(k) for k in raw_scen["combatState"].keys())

    combat_state: dict[str, Any] = dict(base_combat_state or {})
    synergy_effects: list[ModEffect] = []
    extra_forced_procs: dict[str, float] = dict(forced_procs or {})
    external_set_mods: list[dict[str, Any]] = []
    seen_set_paths: set[str] = set()
    aura_enemy_patch: dict[str, float] = {}
    armour_strip_floor = 0.0
    panel_priming_stacks: dict[str, float] = {}
    panel_warframe_arcanes: list[dict[str, Any]] = []
    replay_warframe_arcanes: list[dict[str, Any]] = []
    combat_extras: dict[str, Any] = {}
    notes: list[str] = []

    manual_buffs = payload.get("externalBuffs") if isinstance(payload.get("externalBuffs"), list) else []
    manual_buff_ids: set[str] = set()
    manual_buff_values: dict[str, float] = {}
    manual_buff_families: dict[str, float] = {}
    manual_drift = 0.0
    for entry in manual_buffs:
        if isinstance(entry, Mapping) and str(entry.get("id") or "") == "coaction-drift":
            manual_drift = float(entry["value"]) if entry.get("value") is not None else 0.15
    for entry in manual_buffs:
        if not isinstance(entry, Mapping):
            continue
        bid = str(entry.get("id") or "")
        if not bid or bid == "coaction-drift":
            continue
        manual_buff_ids.add(bid)
        spec = (external_buff_specs or {}).get(bid)
        if isinstance(spec, Mapping):
            if entry.get("value") is not None:
                val = float(entry["value"])
            elif spec.get("squad"):
                val = float(spec.get("base") or 0.0) * float(entry.get("count", 1))
            elif spec.get("strength"):
                val = float(spec.get("base") or 0.0) * float(entry.get("strength", 1.0))
            else:
                val = float(spec.get("base") or 0.0)
            if spec.get("group") == "aura":
                val *= 1.0 + manual_drift
            manual_buff_values[bid] = max(manual_buff_values.get(bid, 0.0), val)
            if spec.get("family"):
                fam = str(spec["family"])
                manual_buff_families[fam] = max(manual_buff_families.get(fam, 0.0), val)

    manual_arcane_paths = {
        str(item.get("path") or item.get("query") or "").strip()
        for item in (payload.get("arcanes") or ())
        if isinstance(item, Mapping)
    }
    has_fortifier = SECONDARY_FORTIFIER_PATH in manual_arcane_paths

    wf_calc_result: dict[str, Any] | None = None
    wf_panel_for_companion: dict[str, Any] | None = None
    surv_eval: dict[str, Any] | None = None
    corrosive_cap_bonus = 0
    topaz_pending_specs: list[Mapping[str, Any]] = []
    active_ability_summaries: list[dict[str, Any]] = []
    active_ability_ids_used: list[str] = []

    if wf_source is not None:
        wf_cfg = _normalize_warframe_config(wf_source)
        if not wf_cfg.get("frameId") and not wf_cfg.get("id") and not wf_cfg.get("path"):
            # Exalted weapons infer their default Warframe if frameId was omitted.
            ex_meta = exalted_weapons.meta(weapon)
            if ex_meta and ex_meta.get("framePaths"):
                wf_cfg["frameId"] = ex_meta["framePaths"][0]
            else:
                raise SimulationError("warframeLink requires frameId in config")

        wf_calc_result = warframe_engine.calculate({**wf_cfg, "applyConditionals": True})
        wb = wf_calc_result["weaponBridge"]
        panel = dict(wb["panel"])
        surv = dict(wb["survivability"])

        raw_active_abilities = wf_source.get("activeAbilities")
        if raw_active_abilities is not None and not isinstance(raw_active_abilities, (list, tuple)):
            raise SimulationError("warframeLink.activeAbilities must be an array of ability IDs")
        requested_ability_tokens: set[str] | None = (
            {str(x).strip() for x in raw_active_abilities if str(x).strip()}
            if raw_active_abilities is not None
            else None
        )
        raw_ability_elements = wf_source.get("abilityElements")
        ability_elements = dict(raw_ability_elements) if isinstance(raw_ability_elements, Mapping) else {}

        has_overshield_ability = bool(
            requested_ability_tokens and (requested_ability_tokens & _SHIELD_RESTORING_ABILITIES)
        )
        has_overshield_source = float(surv.get("energyToShieldRatio") or 0.0) > 0.0 or has_overshield_ability
        overguard_active = has_fortifier or bool(
            (requested_ability_tokens and (requested_ability_tokens & _OVERGUARD_ABILITIES))
            or wf_source.get("overguardActive") is True
        )

        surv_eval = evaluate_incoming_survivability(
            panel=panel,
            survivability=surv,
            enemy_record=enemy_record,
            enemy_path=enemy_path,
            level=level,
            distance=distance,
            eximus=eximus,
            damage_trigger_mode=damage_trigger_mode,
            has_overshield_source=has_overshield_source,
            overguard_active=overguard_active,
        )

        # If damageTriggerMode != "assumed" and conditional Warframe arcanes (Guardian / Molt Efficiency)
        # are equipped, interpolate armor / energy / duration by their AI/off uptimes.
        has_guardian = any(a.get("path") == ARCANE_GUARDIAN_PATH for a in wb.get("arcanes") or ())
        has_molt_eff = any(a.get("path") == MOLT_EFFICIENCY_PATH for a in (wf_cfg.get("arcanes") or ()) if isinstance(a, Mapping))
        if damage_trigger_mode != "assumed" and (has_guardian or has_molt_eff):
            uncond_res = warframe_engine.calculate({**wf_cfg, "applyConditionals": False})
            uncond_wb = uncond_res["weaponBridge"]
            uncond_panel = uncond_wb["panel"]
            g_up = float(surv_eval["guardianUptime"])
            s_up = float(surv_eval["shieldUptime"])
            panel["armor"] = round(
                float(uncond_panel["armor"]) + (float(panel["armor"]) - float(uncond_panel["armor"])) * g_up,
                6,
            )
            panel["energy"] = round(
                float(uncond_panel["energy"]) + (float(panel["energy"]) - float(uncond_panel["energy"])) * g_up,
                6,
            )
            panel["abilityDuration"] = round(
                float(uncond_panel["abilityDuration"])
                + (float(panel["abilityDuration"]) - float(uncond_panel["abilityDuration"])) * s_up,
                6,
            )
            # Refresh shards if energy crossed the >500 Violet Shard threshold.
            if (float(panel["energy"]) > 500.0) != bool(wb["shards"].get("violetMeleeCritDoubled")):
                wb = uncond_wb

        wf_panel_for_companion = {
            "health": float(panel["health"]),
            "shield": float(panel["shield"]),
            "armor": float(panel["armor"]),
        }

        # Auto-populate weapon combat_state (preserving explicit user overrides).
        eff_shield_for_panel = (
            float(panel["shield"]) * float(surv_eval["shieldUptime"])
            if damage_trigger_mode == "ai" and float(surv_eval["incomingRawDps"]) > 0.0
            else float(panel["shield"])
        )
        steady_overshield = float(surv_eval["steadyOvershield"])
        auto_cs: dict[str, Any] = {
            "frameHealth": float(panel["health"]),
            "frameShield": round(eff_shield_for_panel, 3),
            "frameOvershield": round(steady_overshield, 3),
            "frameArmor": float(panel["armor"]),
            "energyPool": float(panel["energy"]),
            "sprintMultiplier": float(panel["sprint"]),
            "overshields": steady_overshield > 0.0,
        }
        if requested_ability_tokens and (requested_ability_tokens & _INVISIBILITY_ABILITIES):
            auto_cs["cloaked"] = True
        if damage_trigger_mode == "ai":
            r_hit = float(surv_eval["incomingHitRate"])
            if r_hit > 1e-6:
                interval = round(1.0 / r_hit, 6)
                auto_cs["selfDamageHitAt"] = interval
                auto_cs["selfDamageHitInterval"] = interval
            if float(surv_eval["selfDamageOnKill"]) > 0.0:
                auto_cs["selfDamageOnKill"] = float(surv_eval["selfDamageOnKill"])
                combat_extras["selfDamageOnKill"] = float(surv_eval["selfDamageOnKill"])

        for k, v in auto_cs.items():
            if k not in explicit_keys:
                combat_state[k] = v

        # 1) Archon Shards
        shards = wb["shards"]
        corrosive_cap_bonus = int(shards.get("corrosiveMaxStacksBonus") or 0)
        for fx in shards.get("effectsSpec") or ():
            if fx.get("condition") == "onHeatStatusKill":
                topaz_pending_specs.append(fx)
                continue
            built, fp = _spec_to_mod_effects(fx, weapon=weapon)
            synergy_effects.extend(built)
            extra_forced_procs.update(fp)

        # 2) Helminth Invigorations
        for fx in wb["invigorations"].get("effectsSpec") or ():
            built, fp = _spec_to_mod_effects(fx, weapon=weapon)
            synergy_effects.extend(built)
            extra_forced_procs.update(fp)

        # 3) Aura (deduplicate against manual externalBuffs, keeping the stronger value)
        aura = wb["aura"]
        aura_buff_id = aura.get("buffId")
        if not exalted_legacy_upgrade:
            manual_aura_val = float(manual_buff_values.get(str(aura_buff_id or "")) or 0.0)
            if aura_buff_id in {"corrosive-projection", "shield-disruption"}:
                wf_aura_val = float(aura.get("value") or 0.0)
                excess = wf_aura_val - manual_aura_val
                if excess > 1e-6:
                    target_key = "auraArmourReduction" if aura_buff_id == "corrosive-projection" else "auraShieldReduction"
                    aura_enemy_patch[target_key] = excess
            else:
                for fx in aura.get("effectsSpec") or ():
                    if fx.get("condition") == "PM_HEAVY_MELEE":
                        eff = ModEffect(
                            upgrade_type=str(fx["upgradeType"]),
                            operation=str(fx.get("operation") or "STACKING_MULTIPLY"),
                            value=float(fx["value"]),
                            valid_type=MELEE_ANCESTRY,
                            valid_modifiers=("PM_HEAVY_MELEE",),
                            source_path=str(fx.get("source") or "aura:empowered-blades"),
                        )
                        if eff.supported:
                            synergy_effects.append(eff)
                        continue
                    fx_use = fx
                    if aura_buff_id and aura_buff_id in manual_buff_ids:
                        excess = float(fx.get("value") or 0.0) - manual_aura_val
                        if excess <= 1e-6:
                            continue
                        fx_use = {**fx, "value": round(excess, 6)}
                    built, fp = _spec_to_mod_effects(fx_use, weapon=weapon)
                    synergy_effects.extend(built)
                    extra_forced_procs.update(fp)

        # 4) Active Warframe Abilities & Equipped Augments
        for ab in wb.get("availableAbilities") or ():
            ab_id = str(ab.get("id") or "")
            ab_path = str(ab.get("abilityPath") or "")
            mod_path = str(ab.get("modPath") or "")
            is_passive_augment = bool(ab.get("isAugment") and ab.get("abilityPath") is None)
            if requested_ability_tokens is None:
                is_active = is_passive_augment
            else:
                is_active = bool({ab_id, ab_path, mod_path} & requested_ability_tokens) or (
                    is_passive_augment and wf_source.get("disablePassiveAugments") is not True
                    and (ab_id in requested_ability_tokens or not requested_ability_tokens)
                )
                if requested_ability_tokens and is_passive_augment and ab_id not in requested_ability_tokens:
                    # Passive augments (Valence Formation, Biting Frost) stay active when equipped unless explicitly disabled.
                    is_active = True
            if not is_active:
                continue

            # Deduplicate against manual externalBuffs by id or shared ability family (keep the stronger value).
            same_id_val = float(manual_buff_values.get(ab_id) or 0.0)
            fam = _ABILITY_FAMILIES.get(ab_id)
            fam_val = float(manual_buff_families.get(fam) or 0.0) if fam else 0.0
            manual_overlap = max(same_id_val, fam_val)
            if manual_overlap > 0.0:
                ab_primary_val = max((abs(float(f.get("value") or 0.0)) for f in ab.get("effectsSpec") or ()), default=0.0)
                if manual_overlap >= ab_primary_val - 1e-6:
                    continue
                notes.append(f"synergy-ability-superseded-manual-family:{fam or ab_id}")

            chosen_elem = None
            if ab.get("requiresElementChoice"):
                opts = list(ab.get("elementOptions") or ())
                req_elem = str(ability_elements.get(ab_id) or wf_source.get("element") or "")
                chosen_elem = req_elem if req_elem in opts else (opts[0] if opts else None)

            applied_any = False
            for fx in ab.get("effectsSpec") or ():
                ut = str(fx.get("upgradeType") or "")
                if ut == "ENEMY_DEFENSE_STRIP":
                    strip_val = min(1.0, max(0.0, float(fx.get("value") or 0.0)))
                    if fx.get("perSecond"):
                        # Steady 5s gaze exposure -> full strip at >=20% per second.
                        strip_val = min(1.0, strip_val * 5.0)
                    if fx.get("stripsArmor"):
                        armour_strip_floor = max(armour_strip_floor, strip_val)
                    if fx.get("stripsShield"):
                        aura_enemy_patch["auraShieldReduction"] = max(
                            aura_enemy_patch.get("auraShieldReduction", 0.0), strip_val
                        )
                    applied_any = True
                    continue
                # Scale Redline if Molt Efficiency duration was adjusted in AI mode.
                fx_use = fx
                if str(fx.get("scale") or "") == "duration" and float(wb["panel"]["abilityDuration"]) > 0:
                    ratio = float(panel["abilityDuration"]) / float(wb["panel"]["abilityDuration"])
                    if abs(ratio - 1.0) > 1e-6:
                        fx_use = {**fx, "value": round(float(fx["value"]) * ratio, 6)}
                if manual_overlap > 0.0 and fx_use.get("operation") == "STACKING_MULTIPLY":
                    fx_use = {**fx_use, "value": round(max(0.0, float(fx_use["value"]) - manual_overlap), 6)}
                built, fp = _spec_to_mod_effects(
                    fx_use,
                    weapon=weapon,
                    chosen_element=chosen_elem,
                    source_override=f"warframe:{ab_id}",
                )
                if built:
                    synergy_effects.extend(built)
                    extra_forced_procs.update(fp)
                    applied_any = True
            if applied_any:
                active_ability_ids_used.append(ab_id)
                active_ability_summaries.append({
                    "id": ab_id,
                    "nameZh": ab.get("nameZh") or ab.get("nameEn"),
                    "nameEn": ab.get("nameEn"),
                    "isAugment": bool(ab.get("isAugment")),
                    "isHelminth": bool(ab.get("isHelminth")),
                    "element": chosen_elem,
                    "summaryZh": ab.get("summaryZh"),
                })

        # Direct Warframe mod bonuses (Nira slam bonus, plus Vigorous Swap / Holster Amp when onEquip toggled).
        on_equip_active = bool(
            wf_source.get("onEquip") is True
            or (requested_ability_tokens and ("vigorous-swap" in requested_ability_tokens or "on-equip" in requested_ability_tokens))
        )
        for fx in wb.get("modBonuses", {}).get("effectsSpec") or ():
            cond = fx.get("condition")
            if cond == "onEquip" and (not on_equip_active or "vigorous-swap" in manual_buff_ids):
                continue
            if cond in {"inTekZone", "onMechaMarkedTarget"} and not wf_source.get(cond):
                continue
            built, fp = _spec_to_mod_effects(fx, weapon=weapon)
            synergy_effects.extend(built)
            extra_forced_procs.update(fp)

        # 5) Warframe Set Mods
        for entry in wb.get("setModPaths") or ():
            p = str(entry.get("path") or "").strip()
            if p and p not in seen_set_paths:
                seen_set_paths.add(p)
                external_set_mods.append(dict(entry))

        # 6) Equipped Warframe Arcanes
        if not exalted_legacy_upgrade:
            arcanes_export_by_path = {
                str(a.get("path") or ""): a for a in (exports.get("arcanes") or ()) if isinstance(a, Mapping)
            }
            for arc in wb.get("arcanes") or ():
                apath = str(arc.get("path") or "").strip()
                arank = int(arc.get("rank") or 0)
                if not apath or apath in manual_arcane_paths:
                    continue
                tkind = str(arc.get("triggerKind") or "")
                if apath == ARCANE_AVENGER_PATH:
                    av_up = float(surv_eval["avengerUptime"])
                    if damage_trigger_mode == "assumed":
                        row = {"path": apath, "rank": arank, "stacks": 1, "uptime": 1.0}
                        panel_warframe_arcanes.append(row)
                        replay_warframe_arcanes.append(dict(row))
                    elif damage_trigger_mode == "off":
                        row = {"path": apath, "rank": arank, "stacks": 0, "uptime": 0.0}
                        panel_warframe_arcanes.append(row)
                        replay_warframe_arcanes.append(dict(row))
                    else:
                        panel_warframe_arcanes.append({
                            "path": apath,
                            "rank": arank,
                            "stacks": 1 if av_up > 0.0 else 0,
                            "uptime": round(av_up, 6),
                        })
                        # Replay simulates OnDamageCondition live via selfDamageHitInterval + Combat Discipline!
                        replay_warframe_arcanes.append({"path": apath, "rank": arank})
                    continue

                if apath == ARCANE_TRUCULENCE_PATH:
                    if overguard_active or damage_trigger_mode == "assumed":
                        viral_stacks = float((arc.get("effectsSpec") or [{}])[0].get("value") or 10.0)
                        panel_priming_stacks["DT_VIRAL"] = max(panel_priming_stacks.get("DT_VIRAL", 0.0), min(10.0, viral_stacks))
                    continue

                if apath == ARCANE_CREPUSCULAR_PATH:
                    if "arcane-crepuscular" in manual_buff_ids:
                        continue
                    if combat_state.get("cloaked") is True or damage_trigger_mode == "assumed":
                        for fx in arc.get("effectsSpec") or ():
                            built, _ = _spec_to_mod_effects(fx, weapon=weapon, source_override=apath)
                            synergy_effects.extend(built)
                    continue

                if apath == ARCANE_HOT_SHOT_PATH:
                    hs_stacks = wf_source.get("hotShotStacks")
                    has_ability_heat = any(
                        a.get("id") in {"fireball-frenzy", "rippers-wail"}
                        or (a.get("id") in {"thermal-transfer", "resupply", "valence-formation"} and a.get("element") == "DT_FIRE")
                        for a in active_ability_summaries
                    )
                    if isinstance(hs_stacks, int) and not isinstance(hs_stacks, bool) and hs_stacks > 0:
                        eff_stacks = min(50, hs_stacks)
                    elif has_ability_heat or damage_trigger_mode == "assumed":
                        eff_stacks = 50
                    else:
                        eff_stacks = 0
                    if eff_stacks > 0:
                        per_st = 0.01 * (arank + 1)
                        synergy_effects.append(
                            ModEffect("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", per_st * eff_stacks, source_path=apath)
                        )
                    continue

                if apath == ARCANE_ARACHNE_PATH:
                    if combat_state.get("wallLatch") is True or damage_trigger_mode == "assumed":
                        for fx in arc.get("effectsSpec") or ():
                            built, _ = _spec_to_mod_effects(fx, weapon=weapon, source_override=apath)
                            synergy_effects.extend(built)
                    continue

                # Standard weapon-event Warframe arcanes (Rage, Precision, Fury, Strike, Velocity, Acceleration, Tempo, Momentum, Rise, Awakening, Pistoleer, Chargers).
                exp_rec = arcanes_export_by_path.get(apath)
                if exp_rec is not None and arc.get("weaponRelevant"):
                    from . import optimizer

                    if optimizer._arcane_matches_weapon(exp_rec, weapon):
                        row = {"path": apath, "rank": arank}
                        if damage_trigger_mode == "assumed":
                            trig = exp_rec.get("trigger") if isinstance(exp_rec.get("trigger"), Mapping) else {}
                            cap_st = trig.get("maxStacks")
                            row_panel = {
                                "path": apath,
                                "rank": arank,
                                "stacks": int(cap_st) if isinstance(cap_st, int) and cap_st > 0 else 1,
                                "uptime": 1.0,
                            }
                            panel_warframe_arcanes.append(row_panel)
                        else:
                            panel_warframe_arcanes.append(row)
                        replay_warframe_arcanes.append(dict(row))

    # 7) Companion Link Resolution (Two-Pass for Hunter Synergy!)
    comp_eval: dict[str, Any] | None = None
    companion_cold_rate = 0.0
    companion_heat_rate = 0.0
    if comp_enabled and isinstance(comp_link_raw, Mapping):
        comp_body_cfg, comp_weapon_cfg = _normalize_companion_configs(comp_link_raw)
        if not comp_body_cfg.get("path") and not comp_body_cfg.get("id"):
            raise SimulationError("companionLink requires companion path or id")

        primary_probe: dict[str, float] | None = None
        raw_pstats = comp_link_raw.get("primaryWeaponStats")
        if isinstance(raw_pstats, Mapping):
            primary_probe = {
                "critChance": float(raw_pstats.get("critChance") or 0.0),
                "statusChance": float(raw_pstats.get("statusChance") or 0.0),
            }
        elif _companion_needs_primary_probe(comp_body_cfg, comp_weapon_cfg):
            if str(weapon.get("slot") or "") == "primary":
                probe_scen = Scenario(combat_state=combat_state)
                primary_probe = _probe_primary_weapon_stats(
                    weapon,
                    mods,
                    riven_effects,
                    synergy_effects,
                    external_set_mods,
                    probe_scen,
                    0,
                    exports,
                )
            elif isinstance(comp_link_raw.get("primaryWeapon"), Mapping):
                pw_payload = comp_link_raw["primaryWeapon"]
                pw_path = str(pw_payload.get("weapon") or pw_payload.get("path") or "").strip()
                pw_rec = next(
                    (w for w in (exports.get("weapons") or ()) if isinstance(w, Mapping) and w.get("path") == pw_path),
                    None,
                )
                if pw_rec is not None:
                    primary_probe = _probe_primary_weapon_stats(
                        pw_rec,
                        pw_payload.get("mods") if isinstance(pw_payload.get("mods"), list) else (),
                        (),
                        synergy_effects,
                        external_set_mods,
                        Scenario(combat_state=combat_state),
                        0,
                        exports,
                    )

        comp_eval = companion_loadout.evaluate_companion(
            comp_body_cfg,
            comp_weapon_cfg,
            warframe_panel=wf_panel_for_companion,
            primary_weapon_stats=primary_probe,
            exports=exports,
        )

        # Player weapon buffs from Bond / Precept mods (Tenacious Bond, Reinforced Bond, Cat's Eye, Ambush, Anabolic Pollination).
        comp_player_fx = companion_loadout.player_weapon_mod_effects(comp_eval)
        synergy_effects.extend(comp_player_fx)

        # Non-duplicate set pieces across Companion Body + Companion Weapon / Beast Claws.
        for entry in (comp_eval.get("playerBridge") or {}).get("setModPaths") or ():
            p = str(entry.get("path") or "").strip()
            if p and p not in seen_set_paths:
                seen_set_paths.add(p)
                external_set_mods.append(dict(entry))

        # Dynamic Reinforced Bond reload overshield accumulation when 0 < maxShield < 1200.
        rb = (comp_eval.get("playerBridge") or {}).get("reinforcedBond") or {}
        reloads_needed = rb.get("reloadsNeededForThreshold")
        comp_opts_raw = comp_body_cfg.get("options") if isinstance(comp_body_cfg.get("options"), Mapping) else {}
        if (
            rb.get("equipped")
            and not rb.get("staticActive")
            and comp_opts_raw.get("reinforcedBondAssumeOvershield") is not True
            and isinstance(reloads_needed, int)
            and reloads_needed >= 1
        ):
            combat_extras["reinforcedBondReloads"] = {
                "reloadsNeeded": reloads_needed,
                "fireRateBonus": float(rb.get("fireRateBonus") or 0.60),
            }

        # Robotic active priming & 1D Replay assister (Beasts have canAttack == False -> zero active attacks/priming!).
        attack_prof = comp_eval.get("attackProfile") or {}
        priming = comp_eval.get("primingSummary") or {}
        if attack_prof.get("canAttack"):
            max_rng = float(attack_prof.get("effectiveMaxRange") or 0.0)
            in_range = not (isinstance(distance, (int, float)) and max_rng > 0.0 and float(distance) > max_rng + 1e-6)
            if in_range:
                for dt, st_cnt in (priming.get("steadyPrimingStacks") or {}).items():
                    cnt = float(st_cnt or 0.0)
                    if cnt <= 0.0:
                        continue
                    if dt == "DT_CORROSIVE" and corrosive_cap_bonus > 0:
                        # Companion steady priming also benefits from target Corrosive stack cap raised by Emerald Shards.
                        comp_rate = float(((comp_eval.get("weapon") or {}).get("sustainedProcsPerSecond") or {}).get("DT_CORROSIVE") or 0.0)
                        duty = float(((attack_prof.get("aiProfile") or {}).get("aiDutyCycle")) or 1.0)
                        clones = int(attack_prof.get("cloneMultiplier") or 1)
                        if comp_rate > 0.0:
                            cnt = min(10.0 + corrosive_cap_bonus, comp_rate * duty * clones * 8.0)
                    panel_priming_stacks[str(dt)] = max(panel_priming_stacks.get(str(dt), 0.0), round(cnt, 6))

                companion_cold_rate = float(priming.get("coldProcsPerSecond") or 0.0)
                companion_heat_rate = float(priming.get("heatProcsPerSecond") or 0.0)
                if companion_cold_rate > 0.0 and "primedColdStacks" not in explicit_keys:
                    combat_state["primedColdStacks"] = min(10.0, float(panel_priming_stacks.get("DT_FREEZE") or 0.0))
                if companion_heat_rate > 0.0 and "primedHeatStacks" not in explicit_keys:
                    combat_state["primedHeatStacks"] = float(panel_priming_stacks.get("DT_FIRE") or 0.0)

                assister = build_companion_assister_spec(comp_eval, distance=distance)
                if assister is not None:
                    combat_extras["companionAssister"] = assister

    # Topaz Secondary Crit Shard resolution: active when Heat is on player weapon, active abilities, or companion!
    if topaz_pending_specs:
        comp_has_heat = (
            float(panel_priming_stacks.get("DT_FIRE") or 0.0) > 0.0
            or "DT_FIRE" in (((comp_eval or {}).get("weapon") or {}).get("positiveDamageTypes") or ())
        )
        heat_present = comp_has_heat or _weapon_has_heat(
            weapon, mods, riven, innate_selection, synergy_effects, extra_forced_procs, exports
        )
        if heat_present:
            for fx in topaz_pending_specs:
                built, _ = _spec_to_mod_effects(fx, weapon=weapon)
                synergy_effects.extend(built)

    summary = build_synergy_summary(
        wf_calc_result=wf_calc_result,
        surv_eval=surv_eval,
        active_ability_summaries=active_ability_summaries,
        comp_eval=comp_eval,
        external_set_mods=external_set_mods,
        panel_priming_stacks=panel_priming_stacks,
        companion_cold_rate=companion_cold_rate,
        companion_heat_rate=companion_heat_rate,
    )

    return {
        "effects": ModEffectList(synergy_effects),
        "combat_state": combat_state,
        "external_set_mods": external_set_mods,
        "aura_enemy_patch": aura_enemy_patch,
        "armour_strip_floor": armour_strip_floor,
        "forced_procs": extra_forced_procs,
        "panel_priming_stacks": panel_priming_stacks,
        "panel_warframe_arcanes": panel_warframe_arcanes,
        "replay_warframe_arcanes": replay_warframe_arcanes,
        "companion_cold_procs_per_sec": companion_cold_rate,
        "companion_heat_procs_per_sec": companion_heat_rate,
        "combat_extras": combat_extras,
        "warframe_result": wf_calc_result,
        "companion_result": comp_eval,
        "active_ability_ids": active_ability_ids_used,
        "survivability": surv_eval,
        "notes": notes,
        "summary": summary,
    }


def apply_companion_arcane_priming(
    arcanes: Sequence[Mapping[str, Any]],
    *,
    cold_procs_per_sec: float = 0.0,
    heat_procs_per_sec: float = 0.0,
) -> list[dict[str, Any]]:
    """Inject steady-state Companion Cold/Heat stacks into unforced Primary Frostbite / Cascadia Flare for Panel Solver."""
    if cold_procs_per_sec <= 0.0 and heat_procs_per_sec <= 0.0:
        return [dict(item) for item in arcanes]
    out: list[dict[str, Any]] = []
    for item in arcanes:
        row = dict(item)
        path = str(row.get("path") or row.get("query") or "").strip()
        unforced = "stacks" not in row and "uptime" not in row and "triggerRate" not in row
        if unforced and path == PRIMARY_FROSTBITE_PATH and cold_procs_per_sec > 0.0:
            target = min(40.0, cold_procs_per_sec * 12.0)
            whole = min(40, max(1, int(math.ceil(target - 1e-9))))
            row["stacks"] = whole
            row["uptime"] = min(1.0, target / whole)
        elif unforced and path == CASCADIA_FLARE_PATH and heat_procs_per_sec > 0.0:
            target = min(40.0, heat_procs_per_sec * 10.0)
            whole = min(40, max(1, int(math.ceil(target - 1e-9))))
            row["stacks"] = whole
            row["uptime"] = min(1.0, target / whole)
        out.append(row)
    return out


def merge_warframe_arcanes(
    manual_arcanes: Sequence[Mapping[str, Any]],
    synergy_arcanes: Sequence[Mapping[str, Any]],
    arcanes_by_path: Mapping[str, Mapping[str, Any]],
    *,
    warframe_link_enabled: bool = False,
) -> list[dict[str, Any]]:
    """Resolve effective arcanes: when warframeLink is active, shield weapon-page Warframe arcanes to prevent double counting."""
    if warframe_link_enabled:
        out = [
            dict(item)
            for item in manual_arcanes
            if str((arcanes_by_path.get(str(item.get("path") or item.get("query") or "").strip()) or {}).get("slotKind") or "weapon") != "warframe"
        ]
    else:
        out = [dict(item) for item in manual_arcanes]
    seen = {str(item.get("path") or item.get("query") or "").strip() for item in out}
    wf_count = sum(
        1
        for item in out
        if str((arcanes_by_path.get(str(item.get("path") or "")) or {}).get("slotKind") or "weapon") == "warframe"
    )
    for row in synergy_arcanes:
        path = str(row.get("path") or "").strip()
        if not path or path in seen or wf_count >= 2:
            continue
        seen.add(path)
        wf_count += 1
        out.append(dict(row))
    return out


def build_synergy_summary(
    *,
    wf_calc_result: Mapping[str, Any] | None,
    surv_eval: Mapping[str, Any] | None,
    active_ability_summaries: Sequence[Mapping[str, Any]],
    comp_eval: Mapping[str, Any] | None,
    external_set_mods: Sequence[Mapping[str, Any]],
    panel_priming_stacks: Mapping[str, float],
    companion_cold_rate: float,
    companion_heat_rate: float,
) -> dict[str, Any]:
    wf_summary: dict[str, Any] | None = None
    if wf_calc_result is not None:
        wb = wf_calc_result["weaponBridge"]
        wf_summary = {
            "frame": wb.get("frame"),
            "panel": wb.get("panel"),
            "shards": wb.get("shards", {}).get("summary") or [],
            "invigorations": wb.get("invigorations", {}).get("summary") or [],
            "aura": {
                k: wb["aura"].get(k)
                for k in ("path", "nameZh", "nameEn", "buffId", "value", "hasCoactionDrift")
            },
            "activeAbilities": list(active_ability_summaries),
            "arcanes": [
                {
                    "path": a.get("path"),
                    "nameZh": a.get("nameZh") or a.get("nameEn"),
                    "nameEn": a.get("nameEn"),
                    "rank": a.get("rank"),
                    "triggerKind": a.get("triggerKind"),
                    "weaponRelevant": a.get("weaponRelevant"),
                }
                for a in (wb.get("arcanes") or ())
            ],
            "survivability": surv_eval,
        }

    comp_summary: dict[str, Any] | None = None
    if comp_eval is not None:
        pb = comp_eval.get("playerBridge") or {}
        comp_summary = {
            "companion": comp_eval.get("companion"),
            "stats": comp_eval.get("stats"),
            "panel": comp_eval.get("stats"),
            "weapon": (
                {
                    k: comp_eval["weapon"].get(k)
                    for k in ("kind", "path", "nameZh", "nameEn", "critChance", "critMultiplier", "statusChance", "totalDamage")
                }
                if isinstance(comp_eval.get("weapon"), Mapping)
                else None
            ),
            "attackProfile": {
                k: (comp_eval.get("attackProfile") or {}).get(k)
                for k in ("category", "canAttack", "attackMode", "effectiveMaxRange", "cloneMultiplier")
            },
            "tenaciousBond": pb.get("tenaciousBond"),
            "reinforcedBond": pb.get("reinforcedBond"),
            "manifoldBond": pb.get("manifoldBond"),
            "primingStacks": dict(panel_priming_stacks),
            "coldProcsPerSecond": round(companion_cold_rate, 4),
            "heatProcsPerSecond": round(companion_heat_rate, 4),
        }

    # Summarize cross-entity set piece counts by normalized alias.
    set_counts: dict[str, int] = {}
    for entry in external_set_mods:
        alias = str(entry.get("setAlias") or entry.get("setId") or "")
        if alias:
            set_counts[alias] = set_counts.get(alias, 0) + 1

    return {
        "warframe": wf_summary,
        "companion": comp_summary,
        "externalSetPieceCounts": set_counts,
        "externalSetMods": list(external_set_mods),
        "primingStacks": dict(panel_priming_stacks),
    }


def build_arena_contexts(
    *,
    payload: Mapping[str, Any],
    loadout: Mapping[str, Any],
    scenario: Mapping[str, Any],
    synergy_data: Mapping[str, Any] | None,
    common: Mapping[str, Any],
    exports: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Build (warframeContext, companionContext) for app._arena_context."""
    wf_link = payload.get("warframeLink") if isinstance(payload.get("warframeLink"), Mapping) else loadout.get("warframeLink")
    comp_link = payload.get("companionLink") if isinstance(payload.get("companionLink"), Mapping) else loadout.get("companionLink")
    wf_enabled = isinstance(wf_link, Mapping) and wf_link.get("enabled") is True
    comp_enabled = isinstance(comp_link, Mapping) and comp_link.get("enabled") is True

    wf_ctx: dict[str, Any] | None = None
    if wf_enabled and synergy_data is not None and isinstance(synergy_data.get("warframe_result"), Mapping):
        wf_res = synergy_data["warframe_result"]
        raw_immortal = wf_link.get("immortalBenchmark")
        if raw_immortal is None:
            immortal_flag = not bool(scenario.get("strictSurvival", False))
        else:
            immortal_flag = bool(raw_immortal)
        req_active = wf_link.get("activeAbilities")
        active_list = (
            [str(x) for x in req_active if str(x).strip()]
            if isinstance(req_active, (list, tuple))
            else list(synergy_data.get("active_ability_ids") or ())
        )
        wf_ctx = {
            **wf_res,
            "activeAbilities": active_list,
            "immortalBenchmark": immortal_flag,
        }

    comp_ctx: dict[str, Any] | None = None
    if comp_enabled and synergy_data is not None and isinstance(synergy_data.get("companion_result"), Mapping):
        comp_eval = synergy_data["companion_result"]
        wmeta = comp_eval.get("weapon") if isinstance(comp_eval.get("weapon"), Mapping) else None
        comp_wp_rec = None
        comp_mod_recs: list[tuple[Mapping[str, Any], int, Any]] = []
        if wmeta is not None and wmeta.get("kind") == "robotic_weapon" and wmeta.get("path"):
            wpath = str(wmeta["path"])
            if wpath.casefold() in companion_loadout.MOA_MELEE_WEAPON_ALIASES:
                he_rank = 5
                for sl in comp_eval.get("slots") or ():
                    if isinstance(sl, Mapping) and sl.get("path") == companion_loadout.HARD_ENGAGE_PATH:
                        he_rank = int(sl.get("rank", 5))
                comp_wp_rec = companion_loadout._moa_melee_weapon_record(he_rank)
            else:
                comp_wp_rec = companion_loadout.resolve_record(exports.get("weapons") or (), wpath, kind="weapon")
            for sl in wmeta.get("slots") or ():
                if isinstance(sl, Mapping) and sl.get("path") and sl["path"] != "__riven__":
                    mrec = companion_loadout.resolve_record(exports.get("mods") or (), str(sl["path"]), kind="mod")
                    comp_mod_recs.append((mrec, int(sl.get("rank", mrec.get("maxRank") or 0)), None))
        base_enh = dict(common.get("enemy_enhancements") or {})
        base_enh.pop("primingStacks", None)
        comp_opts = {
            "level": common.get("level"),
            "armour_strip": common.get("armour_strip"),
            "elemental_armour_strip": common.get("elemental_armour_strip"),
            "steel_path": common.get("steel_path"),
            "enemy_enhancements": base_enh,
        }
        comp_ctx = {
            "evaluation": comp_eval,
            "weaponRecord": comp_wp_rec,
            "weaponModRecords": comp_mod_recs,
            "weaponSimOptions": comp_opts,
        }

    return wf_ctx, comp_ctx


__all__ = [
    "has_synergy_links",
    "resolve_synergy",
    "evaluate_incoming_survivability",
    "build_companion_assister_spec",
    "apply_companion_arcane_priming",
    "merge_warframe_arcanes",
    "build_synergy_summary",
    "build_arena_contexts",
]
