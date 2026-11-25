"""Client-verified Warframe Defense Map Nuke & Exalted Combo Evaluator.

 Evaluates:
 1. Universal 1~4 slot ability range circles in meters (with LoS classification)
    for all Warframes, with exact multi-ring geometry for Defense Nuke setups.
 2. Pseudo-Exalted & Exalted weapon stat bridges for Gara (``GaraShankWeapon``),
    Khora (``KhoraWhipclawWeapon``), and Mesa (``SlingerPistols``).
 3. Exact multi-step combo timing, energy cost/regen balance (including
    ``Brightbonnet + Arbucep`` 200% empowerment), direct + DoT damage (including
    Rhino ``Roar`` ``(1 + Roar)^2`` ability DoT double-dip, Nova ``Molecular Prime``
    ``2.0x``, Dante ``Pageflight`` DoT vulnerability), permanent armor strip,
    and Normal / Steel Path Defense wave clear estimates across 16 flagship setups.
"""

from __future__ import annotations

from functools import lru_cache
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .damage import ModEffect, ModEffectList, apply_mods, enemy_defenses
from .simulator import SimulationError


def _mechanics_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "data" / "mechanics"


@lru_cache(maxsize=1)
def nuke_specs() -> dict[str, Any]:
    path = _mechanics_dir() / "defense-nuke-specs.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _path_token(val: Any) -> str:
    return str(val or "").strip().replace("\\", "/").rstrip("/").casefold()


# Authoritative per-ability base radius (meters) & LoS rules for major nuke/support abilities.
# Tuple: (base_radius_m, scales_with_range, los_mode, label_override_zh)
_KNOWN_ABILITY_RADII: dict[str, tuple[float, bool, str, str | None]] = {
    "/lotus/powersuits/glass/abilities/glassshankability": (12.0, True, "NONE", "琉璃碎击挥砍"),
    "/lotus/powersuits/glass/abilities/glassringability": (17.0, True, "NONE", "广域玻璃化炸墙(最小外径)"),
    "/lotus/powersuits/cowgirl/abilities/gunfuability": (50.0, False, "CAMERA_LOS", "和平使者锁定射程"),
    "/lotus/powersuits/cowgirl/abilities/russianrouletteability": (16.0, True, "NONE", "靶场控制"),
    "/lotus/powersuits/harlequin/abilities/harlequinobjectchangeability": (40.0, True, "NONE", "戏法转化范围"),
    "/lotus/powersuits/harlequin/abilities/prismability": (30.0, True, "RAYCAST_LOS", "棱镜激光索敌"),
    "/lotus/powersuits/harlequin/abilities/prism": (30.0, True, "RAYCAST_LOS", "棱镜激光索敌"),
    "/lotus/powersuits/yinyang/abilities/yinyangburstability": (18.0, True, "NONE", "致残突袭光环"),
    "/lotus/powersuits/yinyang/abilities/yinyangauraability": (16.0, True, "NONE", "激怒光环"),
    "/lotus/powersuits/khora/abilities/khoracrackability": (5.0, True, "RAYCAST_LOS", "长鞭利爪爆炸"),
    "/lotus/powersuits/khora/abilities/khoratwirlability": (10.0, True, "RAYCAST_LOS", "束缚陷阱聚怪"),
    "/lotus/powersuits/khora/abilities/khoracageability": (10.0, True, "NONE", "绞杀穹顶抓取"),
    "/lotus/powersuits/saryn/abilities/poisonability": (16.0, True, "NONE", "毒性孢子传染"),
    "/lotus/powersuits/saryn/abilities/explosivedissolveability": (20.0, True, "NONE", "瘴气清场"),
    "/lotus/powersuits/volt/abilities/overloadability": (20.0, True, "NONE", "电能释放扩散"),
    "/lotus/powersuits/runner/abilities/runnertransferability": (12.0, True, "NONE", "热能抽离力场"),
    "/lotus/powersuits/wraith/abilities/wraithreapability": (8.0, True, "NONE", "收割暗影"),
    "/lotus/powersuits/wraith/abilities/wraithsowability": (16.0, True, "NONE", "播种范围"),
    "/lotus/powersuits/wraith/abilities/wraithgloomability": (16.0, True, "NONE", "惨淡减速圈"),
    "/lotus/powersuits/pagemaster/abilities/pagemasterdeathability": (20.0, True, "RAYCAST_LOS", "暗黑诗篇扇形"),
    "/lotus/powersuits/pagemaster/abilities/pagemasterfinalchapterability": (30.0, True, "RAYCAST_LOS", "终章：悲剧引爆"),
    "/lotus/powersuits/gyre/abilities/gyresphereability": (12.0, True, "RAYCAST_LOS", "电弧球聚怪"),
    "/lotus/powersuits/gyre/abilities/gyreoverchargedability": (10.0, True, "RAYCAST_LOS", "旋流连锁电击"),
    "/lotus/powersuits/frost/abilities/avalancheability": (15.0, True, "NONE", "雪崩冻结剥甲"),
    "/lotus/powersuits/ember/abilities/fireblastability": (25.0, True, "RAYCAST_LOS", "火焰冲击剥甲"),
    "/lotus/powersuits/ember/abilities/emberinfernoability": (25.0, True, "CAMERA_LOS", "地狱烈焰陨石"),
    "/lotus/powersuits/mag/abilities/shieldregenability": (37.5, False, "NONE", "极化脉冲总扩散"),
    "/lotus/powersuits/mag/abilities/crushability": (18.0, True, "NONE", "粉碎磁暴"),
    "/lotus/powersuits/nezha/abilities/nezhaspearability": (19.0, True, "NONE", "圣火尖枪穿刺"),
    "/lotus/powersuits/nokko/abilities/nokkopowershroomability": (15.0, True, "NONE", "亮帽菇脉冲"),
    "/lotus/powersuits/nokko/abilities/nokkobouncingshroomability": (12.0, True, "NONE", "孢弹菇弹跳"),
    "/lotus/powersuits/antimatter/abilities/molecularprimeability": (35.0, False, "NONE", "分子填充扩散"),
    "/lotus/powersuits/rhino/abilities/rhinoroarability": (25.0, True, "NONE", "战吼增益半径"),
    "/lotus/powersuits/devourer/abilities/devourerconsumeability": (25.0, True, "NONE", "消化滋养半径"),
}

_LOS_LABELS_ZH = {
    "NONE": "无视视线穿墙",
    "RAYCAST_LOS": "需射线视线",
    "CAMERA_LOS": "需镜头视野",
}


def _equipped_mod_tokens(warframe_result: Mapping[str, Any], payload: Mapping[str, Any] | None = None) -> dict[str, int]:
    """Return {_path_token(mod_path): rank} for installed Warframe mods."""
    out: dict[str, int] = {}
    assigns = ((warframe_result.get("capacityBreakdown") or {}).get("assignments")) or ()
    for row in assigns:
        if isinstance(row, Mapping) and row.get("path"):
            out[_path_token(row["path"])] = int(row.get("rank") or 0)
    if isinstance(payload, Mapping):
        for key in ("aura", "exilus"):
            v = payload.get(key)
            if isinstance(v, Mapping) and (v.get("path") or v.get("id")):
                out[_path_token(v.get("path") or v.get("id"))] = int(v.get("rank") or 3)
            elif isinstance(v, str) and v.strip():
                out[_path_token(v)] = 3
        for m in (payload.get("normalMods") or payload.get("mods") or ()):
            if isinstance(m, Mapping) and (m.get("path") or m.get("id")):
                out[_path_token(m.get("path") or m.get("id"))] = int(m.get("rank") or 3)
    return out


def extract_warframe_ability_ranges(
    warframe_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    *,
    melee_reach_bonus_m: float = 0.0,
) -> list[dict[str, Any]]:
    """Extract 1~4 ability radii in meters for 3D Arena ground rings & Warframe preview."""
    panel = warframe_result.get("finalPanel") or (warframe_result.get("weaponBridge") or {}).get("panel") or {}
    range_mult = max(0.10, float(panel.get("abilityRange") or 1.0))
    dur_mult = max(0.10, float(panel.get("abilityDuration") or 1.0))
    mod_tokens = _equipped_mod_tokens(warframe_result, payload)
    scalars_list = warframe_result.get("abilityScalars") or ()
    out: list[dict[str, Any]] = []

    for idx, ab in enumerate(scalars_list[:4]):
        if not isinstance(ab, Mapping):
            continue
        slot_num = idx + 1
        apath = str(ab.get("path") or ab.get("id") or "").strip()
        ptok = _path_token(apath)
        name_zh = str(ab.get("nameZh") or ab.get("nameEn") or f"{slot_num}技能")
        known = _KNOWN_ABILITY_RADII.get(ptok)

        radius_m: float | None = None
        secondary_radius_m: float | None = None
        secondary_label_zh: str | None = None
        los_mode = "NONE"
        label_zh = name_zh

        if ptok == "/lotus/powersuits/glass/abilities/glassringability":
            # Gara 4 Mass Vitrify: inner minimum wall (2m * R)..max wall ((2 + 9*D)*R), shatter outer = R_wall + 15m * R
            min_shatter = round(17.0 * range_mult, 2)
            max_shatter = round((17.0 + 9.0 * dur_mult) * range_mult, 2)
            radius_m = min_shatter
            secondary_radius_m = max_shatter
            label_zh = "炸墙快爆外径"
            secondary_label_zh = "满扩炸墙外径"
            los_mode = "NONE"
        elif ptok == "/lotus/powersuits/khora/abilities/khoracrackability":
            radius_m = round(min(10.0, 5.0 * range_mult) + max(0.0, float(melee_reach_bonus_m)), 2)
            secondary_radius_m = round(10.0 * range_mult, 2)
            label_zh = "长鞭爆炸半径"
            secondary_label_zh = "挥鞭射程"
            los_mode = "RAYCAST_LOS"
        elif ptok == "/lotus/powersuits/harlequin/abilities/harlequinobjectchangeability":
            has_leg = "/lotus/powersuits/harlequin/objectchangeaugmentcard" in mod_tokens
            if has_leg:
                radius_m = round(40.0 * range_mult, 2)
                secondary_radius_m = 15.0
                label_zh = "拾取转化半径(穿墙)"
                secondary_label_zh = "掉落宝石爆炸(15m受掩体遮挡)"
                los_mode = "NONE"
            else:
                radius_m = round(8.0 * range_mult, 2)
                secondary_radius_m = round(4.0 * range_mult, 2)
                label_zh = "诱敌主宝石爆炸"
                secondary_label_zh = "镜厅分身小宝石爆炸(50%)"
                los_mode = "RAYCAST_LOS"
        elif ptok == "/lotus/powersuits/nezha/abilities/nezhaspearability":
            has_retrib = "/lotus/powersuits/nezha/nezhaspearaugmenttwocard" in mod_tokens
            radius_m = round((9.5 if has_retrib else 19.0) * range_mult, 2)
            label_zh = "神圣报应尖枪" if has_retrib else "圣火尖枪"
            los_mode = "NONE"
        elif ptok == "/lotus/powersuits/mag/abilities/shieldregenability":
            radius_m = round(8.0 * range_mult + 29.5 * dur_mult, 2)
            label_zh = "极化脉冲扩散"
            los_mode = "NONE"
        elif ptok == "/lotus/powersuits/antimatter/abilities/molecularprimeability":
            radius_m = round(5.0 + 5.0 * (6.0 * dur_mult), 2)
            label_zh = "分子填充波面"
            los_mode = "NONE"
        elif known is not None:
            base_r, scales_r, los_mode, ovr_label = known
            radius_m = round(base_r * (range_mult if scales_r else 1.0), 2)
            if ovr_label:
                label_zh = ovr_label
        else:
            # Generic fallback: scan ability scalars for range/radius meter fields
            for sc in ab.get("scalars") or ():
                if not isinstance(sc, Mapping):
                    continue
                unit = str(sc.get("unit") or "").strip().casefold()
                lbl = str(sc.get("label") or sc.get("labelZh") or sc.get("id") or "").casefold()
                val = sc.get("value")
                if isinstance(val, (int, float)) and float(val) > 0.5:
                    if unit in {"m", "米"} or sc.get("scale") == "range" or any(w in lbl for w in ("radius", "range", "范围", "半径", "距离")):
                        if float(val) <= 150.0:
                            radius_m = round(float(val), 2)
                            break

        if radius_m is not None and radius_m > 0.5:
            row_out: dict[str, Any] = {
                "slot": slot_num,
                "id": str(ab.get("id") or apath or f"slot-{slot_num}"),
                "abilityPath": apath,
                "nameZh": name_zh,
                "labelZh": label_zh,
                "radiusM": radius_m,
                "moddedRadiusM": radius_m,
                "losRequired": los_mode != "NONE",
                "ignoresLoS": los_mode == "NONE",
                "losMode": los_mode,
                "losLabelZh": _LOS_LABELS_ZH.get(los_mode, "无视视线"),
            }
            if secondary_radius_m is not None and abs(secondary_radius_m - radius_m) > 0.2:
                row_out["secondaryRadiusM"] = secondary_radius_m
                row_out["secondaryLabelZh"] = secondary_label_zh
            out.append(row_out)

    return out


def resolve_exalted_nuke_stats(
    kind: str,
    *,
    warframe_result: Mapping[str, Any],
    exalted_build: Mapping[str, Any] | None = None,
    exports: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve pseudo-exalted / exalted weapon multipliers for Gara, Khora, or Mesa."""
    wb = warframe_result.get("weaponBridge") or {}
    panel = wb.get("panel") or warframe_result.get("finalPanel") or {}
    strength = max(0.10, float(panel.get("abilityStrength") or 1.0))

    # Extract Warframe-side melee/secondary bonuses (Steel Charge, Pistol Amp, Arcane Fury, Velocity, Precision, Crimson/Violet Shards)
    aura_id = str((wb.get("aura") or {}).get("buffId") or "")
    aura_val = float((wb.get("aura") or {}).get("value") or 0.0)
    steel_charge = aura_val if aura_id == "steel-charge" else 0.0
    pistol_amp = aura_val if aura_id == "pistol-amp" else 0.0

    wf_fury = 0.0
    wf_strike = 0.0
    wf_velocity = 0.0
    wf_precision = 0.0
    wf_avenger_flat_cc = 0.0
    for arc in wb.get("arcanes") or ():
        ap = _path_token(arc.get("path"))
        rk = int(arc.get("rank") or 0)
        if ap.endswith("/meleedamageoncrit"):
            wf_fury += 0.30 * (rk + 1)
        elif ap.endswith("/meleespeedonhit"):
            wf_strike += 0.10 * (rk + 1)
        elif ap.endswith("/pistolspeedoncrit"):
            wf_velocity += 0.20 * (rk + 1)
        elif ap.endswith("/pistoldamageonheadshot"):
            wf_precision += 0.50 * (rk + 1)
        elif ap.endswith("/critchanceondamage"):
            wf_avenger_flat_cc += 0.075 * (rk + 1)

    shards = wb.get("shards") or {}
    violet_melee_cd = float(shards.get("meleeCritDamage") or 0.0)
    topaz_sec_cc = float(shards.get("secondaryCritChance") or 0.0) + float(shards.get("topazSecondaryCritMax") or 0.0)

    # Parse optional user-supplied exalted weapon loadout, else use realistic meta defaults
    cfg = exalted_build if isinstance(exalted_build, Mapping) else {}
    has_custom_mods = isinstance(cfg.get("mods"), list) and len(cfg["mods"]) > 0

    if kind in {"gara_lash", "khora_whip"}:
        # Pseudo-Exalted Melee (GaraShankWeapon / KhoraWhipclawWeapon)
        if has_custom_mods and exports is not None:
            mods_by_p = {str(m.get("path") or ""): m for m in (exports.get("mods") or ()) if isinstance(m, Mapping)}
            base_dmg_add = 0.0
            elem_add = 0.0
            cc_add = 0.0
            cd_add = 0.0
            sc_add = 0.0
            reach_m = 0.0
            init_combo_pts = 0.0
            exposure_bonus = 0.0
            for item in cfg.get("mods") or ():
                if not isinstance(item, Mapping):
                    continue
                mrec = mods_by_p.get(str(item.get("path") or ""))
                if not mrec:
                    continue
                mx_r = int(mrec.get("maxRank") or 0)
                rk = max(0, min(mx_r, int(item.get("rank", mx_r))))
                for fx in mrec.get("effects") or ():
                    ut = str(fx.get("upgradeType") or "")
                    v = float(fx.get("valuePerRank") or 0.0) * (rk + 1)
                    if ut in {"WEAPON_MELEE_DAMAGE", "WEAPON_DAMAGE_AMOUNT"}:
                        base_dmg_add += v
                    elif ut in {"WEAPON_PERCENT_BASE_DAMAGE_ADDED", "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"}:
                        if str(fx.get("damageType") or "") not in {"DT_IMPACT", "DT_PUNCTURE", "DT_SLASH"}:
                            elem_add += v
                    elif ut == "WEAPON_CRIT_CHANCE":
                        cc_add += v
                    elif ut == "WEAPON_CRIT_DAMAGE":
                        cd_add += v
                    elif ut == "WEAPON_PROC_CHANCE":
                        sc_add += v
                    elif ut == "WEAPON_RANGE":
                        reach_m += v
                    elif ut == "WEAPON_MELEE_COMBO_INITIAL_BONUS":
                        init_combo_pts += v
            for arc_item in cfg.get("arcanes") or ():
                if isinstance(arc_item, Mapping) and "exposure" in str(arc_item.get("path") or "").casefold():
                    ark = int(arc_item.get("rank", 5))
                    exposure_bonus = 0.40 * (ark + 1)  # +240% Corrosive at R5
            combo_mult = float(cfg.get("comboMultiplier") or max(1.0, min(12.0, 1.0 + math.floor(init_combo_pts / 20.0))))
        else:
            # Standard meta pseudo-exalted setup: Primed Pressure Point (+165%) + Spoiled Strike (+100%)
            # + 2x 90% Elemental (+180%) + Melee Exposure R5 (+240% Corrosive) + Organ Shatter/Gladiator Might (+150% CD)
            # + Blood Rush / Sacrificial Steel + Primed Reach (+3.0m for Khora) + 6x Galvanized Reflex / 12x combo
            base_dmg_add = 2.65
            elem_add = 1.80
            exposure_bonus = 2.40
            cc_add = 4.40 if kind == "khora_whip" else 0.0
            cd_add = 1.50 if kind == "khora_whip" else 0.0
            sc_add = 1.20 if kind == "khora_whip" else 0.0
            reach_m = 3.0 if kind == "khora_whip" else 0.0
            combo_mult = float(cfg.get("comboMultiplier") or (8.0 if kind == "gara_lash" else 12.0))

        total_base_mult = 1.0 + base_dmg_add + steel_charge + wf_fury
        total_elem_mult = 1.0 + elem_add + exposure_bonus
        base_cc = 0.25 if kind == "khora_whip" else 0.20
        base_cd = 2.0
        final_cc = base_cc * (1.0 + cc_add) + wf_avenger_flat_cc
        final_cd = base_cd * (1.0 + cd_add + violet_melee_cd)
        crit_factor = 1.0 + max(0.0, final_cc) * max(0.0, final_cd - 1.0)
        return {
            "source": "equipped" if has_custom_mods else "meta_default",
            "baseDamageMultiplier": round(total_base_mult, 4),
            "elementalMultiplier": round(total_elem_mult, 4),
            "meleeExposureCorrosive": round(exposure_bonus, 4),
            "comboMultiplier": round(combo_mult, 2),
            "critChance": round(final_cc, 4),
            "critMultiplier": round(final_cd, 4),
            "critFactor": round(crit_factor, 4),
            "statusChance": round((0.25 if kind == "khora_whip" else 0.30) * (1.0 + sc_add), 4),
            "reachBonusM": round(reach_m, 2),
        }

    # Mesa Regulators (SlingerPistols / PrimeSlingerPistols)
    if has_custom_mods and exports is not None:
        mods_by_p = {str(m.get("path") or ""): m for m in (exports.get("mods") or ()) if isinstance(m, Mapping)}
        base_dmg_add = 0.0
        elem_add = 0.0
        ms_add = 0.0
        fr_add = 0.0
        cc_add = 0.0
        cd_add = 0.0
        sc_add = 0.0
        for item in cfg.get("mods") or ():
            if not isinstance(item, Mapping):
                continue
            mrec = mods_by_p.get(str(item.get("path") or ""))
            if not mrec:
                continue
            mx_r = int(mrec.get("maxRank") or 0)
            rk = max(0, min(mx_r, int(item.get("rank", mx_r))))
            for fx in mrec.get("effects") or ():
                ut = str(fx.get("upgradeType") or "")
                v = float(fx.get("valuePerRank") or 0.0) * (rk + 1)
                if ut == "WEAPON_DAMAGE_AMOUNT":
                    base_dmg_add += v
                elif ut in {"WEAPON_PERCENT_BASE_DAMAGE_ADDED", "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"}:
                    if str(fx.get("damageType") or "") not in {"DT_IMPACT", "DT_PUNCTURE", "DT_SLASH"}:
                        elem_add += v
                elif ut == "WEAPON_FIRE_ITERATIONS":
                    ms_add += v
                elif ut == "WEAPON_FIRE_RATE":
                    fr_add += v
                elif ut == "WEAPON_CRIT_CHANCE":
                    cc_add += v
                elif ut == "WEAPON_CRIT_DAMAGE":
                    cd_add += v
                elif ut == "WEAPON_PROC_CHANCE":
                    sc_add += v
    else:
        # Standard Regulators Prime build: Galvanized Diffusion (+230% MS), Lethal Torrent (+60% FR/+60% MS),
        # Anemic Agility (+90% FR / -15% Dmg), Primed Pistol Gambit (+187% CC), Primed Target Cracker (+110% CD),
        # Primed Heated Charge + Viral (+285% Elem), Cascadia Flare (+480% Dmg)
        base_dmg_add = 4.65
        elem_add = 2.85
        ms_add = 2.90
        fr_add = 1.50
        cc_add = 1.87
        cd_add = 1.10
        sc_add = 1.20

    # Peacemaker +1.50 * Strength is additive with Hornet Strike / Cascadia Flare!
    reg_base_mult = 1.0 + 1.50 * strength + base_dmg_add + pistol_amp + wf_precision
    reg_elem_mult = 1.0 + elem_add
    reg_ms = 1.0 + ms_add
    reg_fr_mult = max(0.20, 1.0 + fr_add + wf_velocity)
    final_cc = 0.25 * (1.0 + cc_add + topaz_sec_cc) + wf_avenger_flat_cc
    final_cd = 3.0 * (1.0 + cd_add)
    crit_factor = 1.0 + max(0.0, final_cc) * max(0.0, final_cd - 1.0)
    return {
        "source": "equipped" if has_custom_mods else "meta_default",
        "baseDamageMultiplier": round(reg_base_mult, 4),
        "elementalMultiplier": round(reg_elem_mult, 4),
        "multishot": round(reg_ms, 4),
        "fireRateMultiplier": round(reg_fr_mult, 4),
        "maxShotsPerSec": round(14.8 * reg_fr_mult, 2),
        "critChance": round(final_cc, 4),
        "critMultiplier": round(final_cd, 4),
        "critFactor": round(crit_factor, 4),
        "statusChance": round(0.10 * (1.0 + sc_add), 4),
    }


def list_warframe_nuke_setups(
    warframe_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return all candidate Defense Nuke playstyles for this Warframe, validating Helminth slot availability."""
    frame_info = warframe_result.get("frame") or {}
    fpath = _path_token(frame_info.get("path") or frame_info.get("id"))
    fname = str(frame_info.get("nameEn") or "").strip().casefold()
    mod_tokens = _equipped_mod_tokens(warframe_result, payload)
    ab_paths = {
        _path_token(ab.get("path") or ab.get("id"))
        for ab in (warframe_result.get("abilityScalars") or ())
        if isinstance(ab, Mapping)
    }

    routes: list[dict[str, Any]] = []

    def _add_route(setup_id: str, label_zh: str, available: bool, missing_reason_zh: str, *, recommended: bool = False) -> None:
        routes.append({
            "setupId": setup_id,
            "labelZh": label_zh,
            "shortLabelZh": label_zh,
            "available": bool(available),
            "unavailableReasonZh": "" if available else missing_reason_zh,
            "recommended": bool(recommended and available),
        })

    if "/glass/" in fpath or "gara" in fname:
        has_1 = "/lotus/powersuits/glass/abilities/glassshankability" in ab_paths
        has_4 = "/lotus/powersuits/glass/abilities/glassringability" in ab_paths
        miss = "1 技能［琉璃碎击］" if not has_1 else ("4 技能［广域玻璃化］" if not has_4 else "")
        _add_route("gara_shatter_storm", "4+1 广域玻璃化炸环", has_1 and has_4, f"已通过 Helminth 替换 {miss}，无法完成炸环连招", recommended=True)
    elif "/cowgirl/" in fpath or "mesa" in fname:
        has_4 = "/lotus/powersuits/cowgirl/abilities/gunfuability" in ab_paths
        _add_route("mesa_peacemaker", "4 和平使者显赫双枪", has_4, "已通过 Helminth 替换 4 技能［和平使者］", recommended=True)
    elif "/harlequin/" in fpath or "mirage" in fname:
        has_2 = "/lotus/powersuits/harlequin/abilities/harlequinobjectchangeability" in ab_paths
        has_4 = any(k in ab_paths for k in ("/lotus/powersuits/harlequin/abilities/prism", "/lotus/powersuits/harlequin/abilities/prismability"))
        has_leg = "/lotus/powersuits/harlequin/objectchangeaugmentcard" in mod_tokens
        has_pg = "/lotus/powersuits/harlequin/prismpvpaugmentcard" in mod_tokens
        pref_leg = has_2 and (has_leg or not has_4)
        pref_prism = has_4 and not pref_leg
        _add_route(
            "mirage_legerdemain",
            "路线A：2 戏法 / 爆炸戏法 (+1 镜厅小宝石)" if not has_leg else "路线A：2 爆炸戏法 + 1 镜厅小宝石 [已装集团卡]",
            has_2,
            "已通过 Helminth 替换 2 技能［戏法］，无法使用宝石地雷路线",
            recommended=pref_leg,
        )
        _add_route(
            "mirage_prism",
            "路线B：4 棱镜激光 (+3 日蚀叠伤)" if not has_pg else "路线B：4 棱镜护卫跟随 (+3 日蚀叠伤) [已装集团卡]",
            has_4,
            "已通过 Helminth 替换 4 技能［棱镜］，无法使用棱镜激光路线",
            recommended=pref_prism,
        )
    elif "/yinyang/" in fpath or "equinox" in fname:
        if "night" not in str(frame_info.get("formKind") or "").casefold():
            has_4 = "/lotus/powersuits/yinyang/abilities/yinyangburstability" in ab_paths
            _add_route("equinox_day_maim", "白昼 4 致残突袭蓄伤核爆", has_4, "已通过 Helminth 替换 4 技能［致残突袭］", recommended=True)
    elif "/khora/" in fpath or "khora" in fname:
        has_1 = "/lotus/powersuits/khora/abilities/khoracrackability" in ab_paths
        _add_route("khora_whipclaw", "4 绞杀穹顶 + 1 长鞭利爪传导", has_1, "已通过 Helminth 替换 1 技能［长鞭利爪］", recommended=True)
    elif "/saryn/" in fpath or "saryn" in fname:
        has_4 = "/lotus/powersuits/saryn/abilities/explosivedissolveability" in ab_paths
        _add_route("saryn_spores_miasma", "1 毒性孢子 + 4 瘴气传染", has_4, "已通过 Helminth 替换 4 技能［瘴气］", recommended=True)
    elif "/wraith/" in fpath or "sevagoth" in fname:
        has_1 = "/lotus/powersuits/wraith/abilities/wraithreapability" in ab_paths
        has_2 = "/lotus/powersuits/wraith/abilities/wraithsowability" in ab_paths
        miss = "1 技能［收割］" if not has_1 else ("2 技能［播种］" if not has_2 else "")
        _add_route("sevagoth_sow_reap", "2 播种 + 1 收割真实百分比连锁", has_1 and has_2, f"已通过 Helminth 替换 {miss}，无法触发播种收割引爆", recommended=True)
    elif "/pagemaster/" in fpath or "dante" in fname:
        has_3 = "/lotus/powersuits/pagemaster/abilities/pagemasterdeathability" in ab_paths
        has_4 = "/lotus/powersuits/pagemaster/abilities/pagemasterfinalchapterability" in ab_paths
        miss = "3 技能［暗黑诗篇］" if not has_3 else ("4 技能［终章］" if not has_4 else "")
        _add_route("dante_tragedy", "3x2 暗黑诗篇 + 4 终章：悲剧浓缩", has_3 and has_4, f"已通过 Helminth 替换 {miss}，无法合成终章：悲剧", recommended=True)
    elif "/gyre/" in fpath or "gyre" in fname:
        has_4 = "/lotus/powersuits/gyre/abilities/gyreoverchargedability" in ab_paths
        _add_route("gyre_rotorswell", "3 阴极优雅 + 4 旋流连锁电击", has_4, "已通过 Helminth 替换 4 技能［旋流］", recommended=True)
    elif "/frost/" in fpath or "frost" in fname:
        has_4 = "/lotus/powersuits/frost/abilities/avalancheability" in ab_paths
        _add_route("frost_avalanche", "4 雪崩满削甲冻结清场", has_4, "已通过 Helminth 替换 4 技能［雪崩］", recommended=True)
    elif "/ember/" in fpath or "ember" in fname:
        has_4 = "/lotus/powersuits/ember/abilities/emberinfernoability" in ab_paths
        _add_route("ember_inferno", "3 火焰冲击削甲 + 4 地狱烈焰陨石", has_4, "已通过 Helminth 替换 4 技能［地狱烈焰］", recommended=True)
    elif "/mag/" in fpath or fname in {"mag", "mag prime"}:
        has_4 = "/lotus/powersuits/mag/abilities/crushability" in ab_paths
        _add_route("mag_crush", "4 粉碎削甲 + 3 极化脉冲破盾", has_4, "已通过 Helminth 替换 4 技能［粉碎］", recommended=True)
    elif "/volt/" in fpath or "volt" in fname:
        has_4 = "/lotus/powersuits/volt/abilities/overloadability" in ab_paths
        _add_route("volt_discharge", "4 电能释放特斯拉互电", has_4, "已通过 Helminth 替换 4 技能［电能释放］", recommended=True)
    elif "/nezha/" in fpath or "nezha" in fname:
        has_4 = "/lotus/powersuits/nezha/abilities/nezhaspearability" in ab_paths
        _add_route("nezha_divine_retribution", "4 圣火尖枪［神圣报应］浓缩", has_4, "已通过 Helminth 替换 4 技能［圣火尖枪］", recommended=True)
    elif "/nokko/" in fpath or "nokko" in fname:
        has_4 = any(
            k in ab_paths
            for k in (
                "/lotus/powersuits/nokko/abilities/nokkolaunchability",
                "/lotus/powersuits/nokko/abilities/nokkobouncingshroomability",
            )
        )
        _add_route("nokko_sporespring", "2 亮帽菇 + 4 孢弹菇弹跳", has_4, "已通过 Helminth 替换 4 技能［孢弹菇］", recommended=True)
    elif "/runner/" in fpath or "gauss" in fname:
        has_3 = "/lotus/powersuits/runner/abilities/runnertransferability" in ab_paths
        _add_route("thermal_sunder_nuke", "3 热能抽离叠火拍冰核爆", has_3, "已通过 Helminth 替换 3 技能［热能抽离］", recommended=True)

    # Any non-Gauss Warframe that infused Helminth Thermal Sunder ALSO gets Thermal Sunder as a selectable route!
    if "/runner/" not in fpath and "gauss" not in fname and "/lotus/powersuits/runner/abilities/runnertransferability" in ab_paths:
        any_native_rec = any(r["recommended"] for r in routes)
        _add_route(
            "thermal_sunder_nuke",
            "Helminth 注入：热能抽离叠火拍冰",
            True,
            "",
            recommended=not any_native_rec,
        )

    return routes


def detect_nuke_setup_id(
    warframe_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    *,
    requested_setup_id: str | None = None,
) -> str | None:
    """Resolve the active Defense Nuke setupId, honoring explicit user route selection when valid."""
    routes = list_warframe_nuke_setups(warframe_result, payload)
    if not routes:
        return None
    req = str(requested_setup_id or "").strip()
    if not req and isinstance(payload, Mapping):
        req = str(
            payload.get("nukeSetupId")
            or ((payload.get("config") or {}).get("nukeSetupId") if isinstance(payload.get("config"), Mapping) else "")
            or ""
        ).strip()
    if req:
        for r in routes:
            if r["setupId"] == req and r["available"]:
                return req
    for r in routes:
        if r["available"] and r.get("recommended"):
            return str(r["setupId"])
    for r in routes:
        if r["available"]:
            return str(r["setupId"])
    return None


def evaluate_warframe_nuke_preview(
    warframe_result: Mapping[str, Any],
    payload: Mapping[str, Any] | None = None,
    *,
    exports: Mapping[str, Any] | None = None,
    requested_setup_id: str | None = None,
) -> dict[str, Any]:
    """Compute complete Defense Map Nuke preview & ability range rings for a Warframe build."""
    wb = warframe_result.get("weaponBridge") or {}
    panel = wb.get("panel") or warframe_result.get("finalPanel") or {}
    econ = wb.get("energyEconomy") or {}
    squad = warframe_result.get("squadBuffSummary") or wb.get("squadBuffSummary") or {}
    focus_bridge = warframe_result.get("focusBridge") or wb.get("focusBridge") or {}
    mod_tokens = _equipped_mod_tokens(warframe_result, payload)

    strength = max(0.10, float(panel.get("abilityStrength") or 1.0))
    four_strength = max(0.10, float(panel.get("abilityFourStrength") or strength))
    duration = max(0.10, float(panel.get("abilityDuration") or 1.0))
    range_mult = max(0.10, float(panel.get("abilityRange") or 1.0))
    eff = float(panel.get("abilityEfficiency") or 1.0)
    uncapped_eff = float(panel.get("uncappedAbilityEfficiency") or eff)
    eff_factor = max(0.25, 2.0 - eff)
    chan_factor = max(0.25, (2.0 - uncapped_eff) / duration)
    cast_speed_mult = max(0.10, 1.0 + float(panel.get("castingSpeed") or 0.0))

    available_setups = list_warframe_nuke_setups(warframe_result, payload)
    setup_id = detect_nuke_setup_id(warframe_result, payload, requested_setup_id=requested_setup_id)
    exalted_build = (payload or {}).get("exaltedWeaponBuild") if isinstance(payload, Mapping) else None
    ex_stats: dict[str, Any] | None = None
    melee_reach = 0.0
    if setup_id == "gara_shatter_storm":
        ex_stats = resolve_exalted_nuke_stats("gara_lash", warframe_result=warframe_result, exalted_build=exalted_build, exports=exports)
    elif setup_id == "khora_whipclaw":
        ex_stats = resolve_exalted_nuke_stats("khora_whip", warframe_result=warframe_result, exalted_build=exalted_build, exports=exports)
        melee_reach = float(ex_stats.get("reachBonusM") or 0.0)
    elif setup_id == "mesa_peacemaker":
        ex_stats = resolve_exalted_nuke_stats("mesa_regulators", warframe_result=warframe_result, exalted_build=exalted_build, exports=exports)

    ability_ranges = extract_warframe_ability_ranges(warframe_result, payload, melee_reach_bonus_m=melee_reach)

    # Self or Squad Roar & Vulnerability multipliers
    ab_paths = {
        _path_token(ab.get("path") or ab.get("id")): idx
        for idx, ab in enumerate(warframe_result.get("abilityScalars") or ())
        if isinstance(ab, Mapping)
    }
    helminth_slot = ((payload or {}).get("helminthReplacement") or {}).get("slot") if isinstance((payload or {}).get("helminthReplacement"), Mapping) else None
    roar_bonus = float(squad.get("roarBonus") or 0.0)
    if "/lotus/powersuits/rhino/abilities/rhinoroarability" in ab_paths:
        r_slot = ab_paths["/lotus/powersuits/rhino/abilities/rhinoroarability"]
        r_str = four_strength if r_slot == 3 else strength
        is_helm_r = helminth_slot == r_slot or "/rhino/" not in _path_token((warframe_result.get("frame") or {}).get("path"))
        roar_bonus = max(roar_bonus, (0.30 if is_helm_r else 0.50) * r_str)

    vuln_mult = float(squad.get("abilityVulnerabilityMultiplier") or 1.0)
    pageflight_dot_vuln = float(squad.get("abilityStatusDamageVulnerability") or 0.0)
    roar_direct = 1.0 + roar_bonus
    roar_dot_double = (1.0 + roar_bonus) ** 2

    # Self Brightbonnet energy/s if equipped on this Warframe!
    arbucep = bool(warframe_result.get("arbucepEmpowered", False))
    nourish_mult = float(econ.get("squadNourishMultiplier") or 1.0)
    if "/lotus/powersuits/devourer/abilities/devourerconsumeability" in ab_paths:
        n_slot = ab_paths["/lotus/powersuits/devourer/abilities/devourerconsumeability"]
        n_str = four_strength if n_slot == 3 else strength
        is_helm_n = helminth_slot == n_slot or "/devourer/" not in _path_token((warframe_result.get("frame") or {}).get("path"))
        nourish_mult = max(nourish_mult, 1.0 + (0.60 if is_helm_n else 1.00) * n_str)

    self_bb_eps = 0.0
    if "/lotus/powersuits/nokko/abilities/nokkopowershroomability" in ab_paths:
        b_slot = ab_paths["/lotus/powersuits/nokko/abilities/nokkopowershroomability"]
        b_str = four_strength if b_slot == 3 else strength
        is_helm_b = helminth_slot == b_slot or "/nokko/" not in _path_token((warframe_result.get("frame") or {}).get("path"))
        pulse_e = (10.0 if is_helm_b else 15.0) * b_str
        iv = (100.0 / 75.0) if arbucep else (100.0 / 35.0)
        shrooms = 2 if arbucep else 1
        self_bb_eps = shrooms * pulse_e / iv

    steady_energy_in_per_sec = (
        float(econ.get("passiveEnergyRegen") or 0.0)
        + max(self_bb_eps, float(econ.get("squadBrightbonnetEnergyPerSec") or 0.0))
    ) * nourish_mult

    # Base armor strip from Aura + Unairu Focus
    aura_arm_red = min(
        1.0,
        (float((wb.get("aura") or {}).get("value") or 0.0) if (wb.get("aura") or {}).get("buffId") == "corrosive-projection" else 0.0)
        + float(squad.get("auraArmorReduction") or 0.0),
    )
    focus_arm_strip = float(((focus_bridge.get("enemyDebuffs") or {}).get("armorStripFraction")) or 0.0)

    if setup_id is None:
        disabled_reasons = [r["unavailableReasonZh"] for r in available_setups if r.get("unavailableReasonZh")]
        return {
            "supported": False,
            "supportedNuke": False,
            "availableSetups": available_setups,
            "hasMultipleSetups": len(available_setups) > 1,
            "abilityRanges": ability_ranges,
            "steadyEnergyRegenPerSec": round(steady_energy_in_per_sec, 2),
            "notesZh": (
                "；".join(disabled_reasons)
                if disabled_reasons
                else "当前战甲未内置专属防御地图炮连招模板；可在 3D 靶场开启地面范围圈观测增益半径，或通过 Helminth 注入［热能抽离］解锁范围清场。"
            ),
        }

    # Evaluate the matched nuke combo!
    nuke: dict[str, Any] = {
        "id": setup_id,
        "setupId": setup_id,
        "selectedSetupId": setup_id,
        "availableSetups": available_setups,
        "hasMultipleSetups": len(available_setups) > 1,
        "supported": True,
        "supportedNuke": True,
        "abilityRanges": ability_ranges,
        "exaltedStats": ex_stats,
        "arbucepEmpowered": arbucep,
        "roarBonus": round(roar_bonus, 4),
        "vulnerabilityMultiplier": round(vuln_mult, 4),
        "steadyEnergyRegenPerSec": round(steady_energy_in_per_sec, 2),
    }

    build_checks: list[dict[str, str]] = []
    radius_summary_zh = ""
    has_energize = any(
        _path_token(a.get("path")).endswith("golemarcaneradialenergyonenergypickup")
        for a in (wb.get("arcanes") or ())
    )
    has_zenurik = str(focus_bridge.get("activeSchool") or "").casefold() == "zenurik"

    direct_dmg = 0.0
    dot_dmg = 0.0
    damage_type_zh = "混合技能伤害"
    ignores_los = True
    primary_radius_m = 20.0 * range_mult
    combo_sec = 1.5
    combo_energy = 75.0 * eff_factor
    ability_armor_strip = focus_arm_strip
    bypasses_armor = False

    if setup_id == "gara_shatter_storm":
        assert ex_stats is not None
        t_exp = 0.6
        r_wall = (2.0 + 3.0 * t_exp) * range_mult
        primary_radius_m = r_wall + 15.0 * range_mult
        max_shatter_m = (17.0 + 9.0 * duration) * range_mult
        combo_sec = (1.2 + 0.7) / cast_speed_mult + t_exp
        combo_energy = (75.0 + 25.0) * eff_factor + 3.5 * chan_factor * t_exp
        vit_vuln = 1.0 + 0.50 * four_strength
        lash_scaled = 400.0 * strength * float(ex_stats["baseDamageMultiplier"]) * float(ex_stats["elementalMultiplier"]) * float(ex_stats["comboMultiplier"])
        direct_dmg = (800.0 * four_strength + lash_scaled) * roar_direct * vuln_mult * vit_vuln
        damage_type_zh = "穿刺/切割 + 伪显赫元素(含近战暴露腐蚀)"
        ignores_los = True
        radius_summary_zh = f"快爆外径 {primary_radius_m:.1f}m / 满扩外径 {max_shatter_m:.1f}m (360°穿墙)"
        has_splinter = "/lotus/powersuits/glass/abilities/glassshatterability" in ab_paths or "/lotus/powersuits/glass/abilities/glasssplinterability" in ab_paths
        build_checks.append({"status": "ok", "textZh": "1 技能［琉璃碎击］与 4 技能［广域玻璃化］均已保留"})
        build_checks.append({
            "status": "info",
            "textZh": (
                "1 技能伪显赫面板当前采用内置满配模板（压迫点Prime/腐坏打击/双90元素/近战暴露8x连击）；武器配装页的步枪/副手仅用于破仲裁无人机与补刀"
                if ex_stats.get("source") == "meta_default"
                else "已读取自定义伪显赫配卡"
            ),
        })
        if has_splinter:
            build_checks.append({"status": "ok", "textZh": "2 技能［碎裂风暴］已保留：3D 靶场首轮清场后能量充裕时会自动开启并叠入每次炸环 50% 伤害"})
        nuke.update({
            "titleZh": "Gara - 4+1 广域玻璃化碎环核爆",
            "comboSequenceZh": "4 广域玻璃化按场上怪距动态扩环定型 -> 1 琉璃碎击从环外引爆（360° 无视墙体掩体 0 距离衰减）",
            "notesZh": f"快爆外径 {primary_radius_m:.1f}m（满扩可达 {max_shatter_m:.1f}m），伪显赫连击 {ex_stats['comboMultiplier']}x，玻璃化易伤 +{round(50 * four_strength)}%。",
        })

    elif setup_id == "mesa_peacemaker":
        assert ex_stats is not None
        primary_radius_m = 50.0
        ignores_los = False
        combo_sec = 0.5 / cast_speed_mult + 1.5
        combo_energy = 25.0 * eff_factor + 15.0 * chan_factor * combo_sec
        per_shot = 50.0 * 2.50 * float(ex_stats["baseDamageMultiplier"]) * float(ex_stats["elementalMultiplier"]) * float(ex_stats["multishot"]) * float(ex_stats["critFactor"]) * roar_direct * vuln_mult
        shots_per_target = max(2.0, float(ex_stats["maxShotsPerSec"]) * 0.25)
        direct_dmg = per_shot * shots_per_target
        dot_dmg = direct_dmg * 0.35 * roar_direct * (1.0 + pageflight_dot_vuln)
        damage_type_zh = "显赫双枪直伤 + 火焰/病毒异常"
        radius_summary_zh = "固定 50.0m 镜头视线锁定（不受技能范围影响）"
        build_checks.append({
            "status": "info",
            "textZh": "显赫双枪［监察者］当前按满配射速双暴热浪模板核算；在 3D 靶场遇到仲裁无人机时会自动收枪切主/副武器点掉无人机后再开 4",
        })
        nuke.update({
            "titleZh": "Mesa - 4 和平使者显赫自瞄清场",
            "comboSequenceZh": "自动站上可达低遮挡高台 -> 开启增益技能 -> 4 和平使者 50m 视线内高速点杀（波间自动停火省蓝）",
            "notesZh": f"固定 50m 视线锁躯干（不受范围卡影响），满转射速 {ex_stats['maxShotsPerSec']}/s，满预热单发期望 {round(per_shot):,}。",
        })

    elif setup_id == "mirage_legerdemain":
        has_leg = "/lotus/powersuits/harlequin/objectchangeaugmentcard" in mod_tokens
        has_hom = "/lotus/powersuits/harlequin/abilities/illusionability" in ab_paths
        has_eclipse = "/lotus/powersuits/harlequin/abilities/lightability" in ab_paths
        conv_r = 40.0 * range_mult
        main_jewel_r = 8.0 * range_mult
        clone_jewel_r = 4.0 * range_mult  # packageWeakMultiplier = 0.50
        primary_radius_m = conv_r if has_leg else main_jewel_r
        combo_sec = 0.8 / cast_speed_mult
        combo_energy = 50.0 * eff_factor

        # 1+2 Native Jewel + 4 Hall of Mirrors Mini-Jewels (packageWeakMultiplier = 0.50 -> 50% dmg & radius)
        main_jewel_dmg = 200.0 * strength
        clone_jewels_total = (4.0 * 200.0 * 0.50 * strength) if has_hom else 0.0
        jewel_pack_dmg = (main_jewel_dmg + clone_jewels_total * 0.65) * roar_direct * vuln_mult

        if has_leg:
            gem_cluster_dmg = 3.0 * 1000.0 * strength * 0.70 * roar_direct * vuln_mult
            direct_dmg = gem_cluster_dmg + jewel_pack_dmg
            dot_dmg = gem_cluster_dmg * 0.50 * roar_direct * (1.0 + pageflight_dot_vuln)
            damage_type_zh = "掉落转化冰/火/电宝石(100%异常) + 诱敌主副宝石爆炸(DT_EXPLOSION)"
            radius_summary_zh = (
                f"拾取转化 {conv_r:.1f}m(穿墙) / 掉落宝石爆炸 15.0m(固定) / 诱敌主宝石 {main_jewel_r:.1f}m"
                + (f" + 镜厅小宝石 {clone_jewel_r:.1f}m×4" if has_hom else "")
            )
            build_checks.append({"status": "ok", "textZh": "已装配集团卡［爆炸戏法］：击杀掉落的血蓝球与主副弹药盒可转化为固定 15m / 60s 跨波宝石地雷"})
        else:
            direct_dmg = jewel_pack_dmg
            dot_dmg = 0.0
            damage_type_zh = "原生诱敌主宝石 + 镜厅分身小宝石爆炸(DT_EXPLOSION)"
            radius_summary_zh = f"诱敌主宝石爆炸 {main_jewel_r:.1f}m" + (
                f" + 镜厅小宝石 {clone_jewel_r:.1f}m×4 (距主宝石6m)" if has_hom else ""
            )
            build_checks.append({
                "status": "warn",
                "textZh": "当前未装配集团卡［爆炸戏法］：仅生效原生 2 戏法诱敌宝石（20s），无法将地面掉落物转化为 60s 元素地雷海！请在配卡槽装入［爆炸戏法］",
            })

        if has_hom:
            build_checks.append({
                "status": "ok",
                "textZh": f"1 技能［镜厅］已保留：施放 2 技能时 4 个分身在 6m 外额外生成 4 颗小宝石（单颗伤害 {round(100 * strength)} / 爆炸 {clone_jewel_r:.1f}m / 诱敌 {6.0 * range_mult:.1f}m，均为本体 50% 效能）",
            })
        else:
            build_checks.append({
                "status": "warn",
                "textZh": "1 技能［镜厅］已被 Helminth 替换：施放 2 技能时仅生成 1 颗主宝石，失去 4 颗分身小宝石与幻影枪械铺垫",
            })

        ignores_los = False
        active_buff_prefix = " + ".join(
            [x for x in ("1 镜厅" if has_hom else "", "3 黯然失色" if has_eclipse else "") if x]
        )
        nuke.update({
            "hasLegerdemainAugment": has_leg,
            "hasHallOfMirrorsSynergy": has_hom,
            "titleZh": (
                f"Mirage - 2 爆炸戏法{' + 1 镜厅主副宝石' if has_hom else ''}跨波地雷流"
                if has_leg
                else f"Mirage - 2 戏法诱敌宝石{' + 1 镜厅四分身小宝石' if has_hom else ''}（未装爆炸戏法）"
            ),
            "comboSequenceZh": (
                (f"开启 {active_buff_prefix} -> " if active_buff_prefix else "")
                + (
                    "枪械或诱敌主副宝石先拿首杀产出地面血蓝球与非重弹药盒 -> 按需施放 2 戏法（生成 1 主"
                    + ("+4 分身小宝石" if has_hom else "宝石")
                    + "，并将掉落物转化为 60s 跨波宝石，快到期或有新掉落才重施放刷新）"
                    if has_leg
                    else f"施放 2 戏法在敌群路径投掷 1 颗主宝石（{round(main_jewel_dmg)} 爆炸）"
                    + (f" + 4 颗 50% 效能镜厅分身小宝石（各 {round(100 * strength)} 爆炸）" if has_hom else "")
                )
            ),
            "notesZh": (
                f"注意区分三种半径：转化扫描 {conv_r:.1f}m 穿墙但本身无伤害；掉落转化宝石固定 15.0m 爆炸（1000×强度={round(1000 * strength)}，内置 60s 跨波留存，受静态掩体遮挡）；"
                f"每次施放同时投掷 20s 诱敌主宝石（{main_jewel_r:.1f}m）"
                + (f"与 4 颗分身小宝石（6m 外环绕、{clone_jewel_r:.1f}m 半径、50% 伤害与范围折扣）。" if has_hom else "。")
                if has_leg
                else f"当前未带［爆炸戏法］，仅靠 20s 诱敌主宝石（{main_jewel_r:.1f}m）"
                + (f"与 4 颗 50% 效能镜厅分身小宝石（{clone_jewel_r:.1f}m）" if has_hom else "")
                + "输出；装入［爆炸戏法］后可解锁掉落物转 60s 跨波地雷。"
            ),
            "losLabelZh": "转化穿墙 / 宝石爆炸受掩体视线判定" if has_leg else "诱敌与爆炸均受视线判定",
        })

    elif setup_id == "mirage_prism":
        has_pg = "/lotus/powersuits/harlequin/prismpvpaugmentcard" in mod_tokens
        has_eclipse = "/lotus/powersuits/harlequin/abilities/lightability" in ab_paths
        ramp_rate = 0.50 if has_eclipse else 0.25
        primary_radius_m = 30.0 * range_mult
        ignores_los = False
        active_dur = (4.0 if has_pg else 6.0) * duration
        combo_sec = (0.67 + 2.57) / cast_speed_mult if has_eclipse else 2.57 / cast_speed_mult
        combo_energy = (25.0 if has_eclipse else 0.0) * eff_factor + 50.0 * eff_factor + 10.0 * chan_factor * min(4.0, active_dur)
        mean_ramp_mult = 1.0 + ramp_rate * 40.0
        direct_dmg = 6.0 * 250.0 * four_strength * mean_ramp_mult * roar_direct * vuln_mult
        damage_type_zh = "辐射激光递增扫射"
        radius_summary_zh = f"20 道激光索敌半径 {primary_radius_m:.1f}m (需射线视线)"
        build_checks.append({
            "status": "ok" if has_pg else "info",
            "textZh": (
                f"已装配集团卡［棱镜护卫］：棱镜锁定在头顶跟随 {active_dur:.1f}s，不再乱弹撞墙"
                if has_pg
                else f"未装［棱镜护卫］：按常规投掷棱镜持续 {active_dur:.1f}s 结算；日常跑图或防撞墙可选装［棱镜护卫］"
            ),
        })
        build_checks.append({
            "status": "ok" if has_eclipse else "warn",
            "textZh": (
                "3 技能［黯然失色］已保留：光明形态使棱镜每次激光命中的叠伤速率从 +25% 翻倍至 +50%"
                if has_eclipse
                else "3 技能［黯然失色］已被替换：棱镜每命中叠伤速率维持基础 +25%（无光明翻倍）"
            ),
        })
        nuke.update({
            "titleZh": f"Mirage - {'4 棱镜护卫头顶跟随' if has_pg else '4 棱镜激光扫射'}{' + 3 日蚀翻倍叠伤' if has_eclipse else ''}",
            "comboSequenceZh": f"{'维持 3 黯然失色(光明使棱镜每跳叠伤翻倍至+50%) -> ' if has_eclipse else ''}4 棱镜{'［棱镜护卫跟随］' if has_pg else ''}（持续期间 10/s 基础通道耗蓝）",
            "notesZh": f"20 道 {primary_radius_m:.1f}m 视线激光每 0.5s 齐射；3D 靶场会自动优选可达高台减少掩体挡线。",
        })

    elif setup_id == "equinox_day_maim":
        primary_radius_m = 18.0 * range_mult
        combo_sec = (1.8 + 1.0) / cast_speed_mult + 2.5
        combo_energy = 50.0 * eff_factor + 3.5 * chan_factor * 2.5
        entry_slash = 150.0 * four_strength * roar_direct * vuln_mult
        entry_bleed = entry_slash * 0.35 * 6.0 * roar_direct * (1.0 + pageflight_dot_vuln)
        direct_dmg = entry_slash
        dot_dmg = entry_bleed
        damage_type_zh = "进圈强制切割流血 + 75%敌方血盾蓄池穿墙核爆"
        ignores_los = True
        radius_summary_zh = f"致残光环与穿墙引爆 {primary_radius_m:.1f}m (随距离 1 - d/R 线性衰减)"
        build_checks.append({"status": "ok", "textZh": "白昼形态 4 技能［致残突袭］已就绪：3D 靶场中必须先由武器或流血击杀圈内敌人蓄池，攒够斩杀线后才二段引爆，蓄伤池可跨波保留"})
        nuke.update({
            "titleZh": "Equinox 白昼 - 4 致残突袭蓄池穿墙核爆",
            "comboSequenceZh": "开启 4 致残突袭（3.5/s 基础耗蓝，进圈挂切割）-> 枪械点杀 2~3 名敌人蓄入 75% 最大血盾 -> 攒满斩杀线二段 4 穿墙引爆",
            "notesZh": f"半径 {primary_radius_m:.1f}m 穿墙，引爆按 1 - d/R 线性距离衰减；蓄池按敌方最大血盾比例成长，无惧高等级膨胀。",
            "scalesWithEnemyMaxHp": True,
            "poolConversionRatio": 0.75,
        })

    elif setup_id == "khora_whipclaw":
        assert ex_stats is not None
        has_accum = "/lotus/powersuits/khora/khoracrackaugmentcard" in mod_tokens
        has_dome = "/lotus/powersuits/khora/abilities/khoracageability" in ab_paths
        accum_bonus = 3.50 if has_accum else 0.0
        eff_whip_str = strength + accum_bonus
        whip_r = min(10.0, 5.0 * range_mult) + float(ex_stats["reachBonusM"])
        dome_r = 10.0 * range_mult
        primary_radius_m = max(whip_r, dome_r if has_dome else whip_r)
        combo_sec = 1.1 / cast_speed_mult
        combo_energy = 25.0 * eff_factor
        whip_hit = 150.0 * eff_whip_str * float(ex_stats["baseDamageMultiplier"]) * float(ex_stats["elementalMultiplier"]) * float(ex_stats["comboMultiplier"]) * float(ex_stats["critFactor"]) * roar_direct * vuln_mult
        direct_dmg = whip_hit * (1.5 if has_dome else 1.0)
        dot_dmg = direct_dmg * 0.35 * roar_direct * (1.0 + pageflight_dot_vuln)
        damage_type_zh = "伪显赫暴击IPS+元素" + ("（穹顶50%无视视线传导）" if has_dome else "")
        ignores_los = False
        radius_summary_zh = f"鞭爆 {whip_r:.1f}m(视线)" + (f" / 绞杀穹顶抓取 {dome_r:.1f}m(穿墙传导)" if has_dome else "")
        build_checks.append({
            "status": "ok" if has_accum else "warn",
            "textZh": "已装配集团卡［积聚长鞭］（最高叠 +350% 鞭爪伤害）" if has_accum else "未装配集团卡［积聚长鞭］：建议装入以获得最高 +350% 伤害叠层",
        })
        build_checks.append({
            "status": "info",
            "textZh": "1 技能伪显赫长鞭采用内置满暴 12x 连击剑风模板；武器配装页的远程武器仅负责点射无人机与远距补刀",
        })
        nuke.update({
            "hasAccumulatingWhipclaw": has_accum,
            "titleZh": f"Khora - {'4 绞杀穹顶 + ' if has_dome else ''}1 长鞭利爪传导清场",
            "comboSequenceZh": f"{'跨波维持 4 绞杀穹顶抓怪 -> ' if has_dome else ''}1 长鞭利爪抽击视线目标（穹顶内全体敌人无视视线分摊 50% 伤害并享 2 倍易伤）",
            "notesZh": f"鞭爆半径 {whip_r:.1f}m（剑风 +{ex_stats['reachBonusM']}m 可突破 10m 范围上限）" + (f"，穹顶抓取 {dome_r:.1f}m。" if has_dome else "。"),
        })

    elif setup_id == "saryn_spores_miasma":
        primary_radius_m = 20.0 * range_mult
        spores_r = 16.0 * range_mult
        has_spores = "/lotus/powersuits/saryn/abilities/poisonability" in ab_paths
        has_lash = "/lotus/powersuits/saryn/abilities/weaponpoisonability" in ab_paths or "/lotus/powersuits/saryn/abilities/toxiclashability" in ab_paths
        combo_sec = ((0.8 if has_spores else 0.0) + 1.3333) / cast_speed_mult
        combo_energy = ((25.0 if has_spores else 0.0) + 75.0) * eff_factor
        ticks = math.floor(6.0 * duration) + 1
        spores_mult = 4.0 if has_spores else 1.0
        miasma_total = ticks * 150.0 * four_strength * spores_mult * 1.85 * roar_direct * vuln_mult
        spores_6s = (3.0 * 24.0 * strength * 6.0 * roar_direct * vuln_mult) if has_spores else 0.0
        direct_dmg = miasma_total
        dot_dmg = spores_6s
        ability_armor_strip = max(ability_armor_strip, 0.80 if has_spores else 0.0)
        damage_type_zh = "腐蚀孢子削甲 + 4倍病毒瘴气穿墙清场" if has_spores else "病毒瘴气穿墙持续伤害"
        ignores_los = True
        radius_summary_zh = f"瘴气 {primary_radius_m:.1f}m(穿墙)" + (f" / 孢子传染 {spores_r:.1f}m(穿墙)" if has_spores else "")
        build_checks.append({
            "status": "ok" if has_spores else "warn",
            "textZh": "1 技能［毒性孢子］已保留：瘴气对染疫目标造成 4 倍伤害并在阵亡时穿墙扩散孢子" if has_spores else "1 技能［毒性孢子］已被替换：瘴气失去 4 倍染疫乘区与腐蚀削甲！",
        })
        nuke.update({
            "titleZh": "Saryn - 1 毒性孢子 + 4 瘴气传染清场",
            "comboSequenceZh": (
                f"场上无染疫目标时补 1 毒性孢子{'（配 3 剧毒鞭笞开火引爆传染）' if has_lash else ''} -> 4 瘴气对染疫目标结算 4 倍病毒伤害并助推孢子穿墙扩散"
                if has_spores
                else "4 瘴气范围病毒持续清场"
            ),
            "notesZh": f"瘴气 {primary_radius_m:.1f}m / 孢子扩散 {spores_r:.1f}m 均穿墙；场上无感染敌人时孢子层数会自然衰减。",
        })

    elif setup_id == "sevagoth_sow_reap":
        primary_radius_m = 16.0 * range_mult
        combo_sec = (1.0333 + 0.80) / cast_speed_mult
        combo_energy = (50.0 + 25.0) * eff_factor
        reap_vuln = 1.0 + 0.50 * strength
        true_hp_pct = 0.25 * reap_vuln * roar_direct * (vuln_mult if vuln_mult > 1.0 else 1.0)
        direct_dmg = 250.0 * strength * roar_direct * vuln_mult * reap_vuln
        bypasses_armor = True
        damage_type_zh = f"真实生命百分比引爆（单次直扣 {min(100.0, true_hp_pct * 100):.1f}% 生命）+ 爆炸连锁"
        ignores_los = True
        radius_summary_zh = f"播种标记与引爆 {primary_radius_m:.1f}m (穿墙)"
        has_dark_prop = "/lotus/powersuits/wraith/wraithsowaugmentcard" in mod_tokens
        has_shadow_haze = "/lotus/powersuits/wraith/wraithreapaugmentcard" in mod_tokens
        build_checks.append({
            "status": "ok" if (has_dark_prop and has_shadow_haze) else "info",
            "textZh": (
                "已配齐双集团卡［黑暗传播 + 暗影迷雾］"
                if (has_dark_prop and has_shadow_haze)
                else "建议同时装配［黑暗传播 + 暗影迷雾］双集团卡实现全自动连锁传染；超宏护盾敌人需枪械破超宏或补刀"
            ),
        })
        nuke.update({
            "titleZh": "Sevagoth - 2 播种 + 1 收割真实百分比核爆",
            "comboSequenceZh": "2 播种穿墙挂标 -> 1 收割引爆（25% 真实生命伤害乘收割易伤与战吼，满阈值无视等级秒杀无超宏目标）",
            "notesZh": f"当前面板单轮直扣敌人 {true_hp_pct * 100:.1f}% 生命值（达到 100% 即无视护甲与等级直接斩杀无超宏普通敌人）。",
            "trueHpPercentPerCombo": round(true_hp_pct, 4),
        })

    elif setup_id == "thermal_sunder_nuke":
        is_native_gauss = "/runner/" in _path_token((warframe_result.get("frame") or {}).get("path"))
        primary_radius_m = 12.0 * range_mult
        combo_sec = (0.7 * 3.0) / cast_speed_mult
        combo_energy = (50.0 * 3.0) * eff_factor
        base_heat = (1200.0 if is_native_gauss else 900.0) * strength * roar_direct * vuln_mult
        hit1_dot_dps = base_heat * 0.50 * roar_direct * (1.0 + pageflight_dot_vuln)
        hit2_dmg = base_heat + hit1_dot_dps
        hit2_dot_dps = min(base_heat * 10.0 if not is_native_gauss else 1e9, hit2_dmg * 0.50 * roar_direct * (1.0 + pageflight_dot_vuln))
        condense_blast = (hit1_dot_dps + hit2_dot_dps) * 6.0 + 0.5 * base_heat
        direct_dmg = base_heat + hit2_dmg + condense_blast
        if is_native_gauss:
            ability_armor_strip = 1.0
        damage_type_zh = "指数叠火 + 冰火骤冷浓缩爆炸"
        ignores_los = True
        radius_summary_zh = f"热能抽离力场 {primary_radius_m:.1f}m (360°穿墙)"
        build_checks.append({
            "status": "ok" if is_native_gauss else "info",
            "textZh": (
                "Gauss 原生热能抽离：无 10 倍火异常封顶，且满赤限拍冰自带 100% 永久削甲"
                if is_native_gauss
                else "Helminth 注入版热能抽离：火异常叠层受基础伤害 10 倍封顶，且无原生赤限削甲，高甲钢路建议配腐蚀投射或削甲手段"
            ),
        })
        nuke.update({
            "titleZh": f"{'Gauss 原生' if is_native_gauss else 'Helminth 注入'} - 热能抽离叠火拍冰核爆",
            "comboSequenceZh": "热能抽离火形态 × 2（叠火焰异常）-> 冰形态（一次性浓缩剩余火焰异常瞬爆爆炸伤害）",
            "notesZh": f"半径 {primary_radius_m:.1f}m 穿墙无冷却，三连施放耗蓝 {round(combo_energy)}，需充足回能支撑。",
        })

    elif setup_id == "dante_tragedy":
        dv_r = 20.0 * range_mult
        primary_radius_m = 30.0 * range_mult
        ignores_los = False
        combo_sec = (1.4333 * 2.0 + 2.50) / cast_speed_mult
        combo_energy = (25.0 * 2.0 + 50.0) * eff_factor
        dv_hit = 2.0 * 2500.0 * strength * roar_direct * vuln_mult
        rem_bleed = 4.0 * 6.0 * 0.35 * 1250.0 * strength * roar_dot_double * vuln_mult * (1.0 + pageflight_dot_vuln)
        tragedy_condense = min(1e9, 6500.0 * four_strength * roar_direct * vuln_mult + rem_bleed * 3.0 * four_strength * roar_direct)
        direct_dmg = dv_hit + tragedy_condense
        bypasses_armor = True
        damage_type_zh = "强制切割流血 × 3.0×强度悲剧浓缩引爆"
        radius_summary_zh = f"3 暗黑诗篇挂流血 {dv_r:.1f}m(需视线) / 4 悲剧结算 {primary_radius_m:.1f}m"
        build_checks.append({"status": "ok", "textZh": "3 技能［暗黑诗篇］受射线视线限制：3D 靶场驻守或固定站桩时会自动优选低遮挡高台扩大挂流血覆盖面"})
        nuke.update({
            "titleZh": "Dante - 3+3+4 暗黑诗篇 + 终章：悲剧浓缩核爆",
            "comboSequenceZh": "3 暗黑诗篇 × 2（对视线内目标挂强制切割流血）-> 4 终章：悲剧（以 3.0×强度倍率一次性浓缩结算剩余流血/火/毒异常）",
            "notesZh": f"暗黑诗篇 {dv_r:.1f}m 需视线命中，终章：悲剧 {primary_radius_m:.1f}m 浓缩结算。",
        })

    elif setup_id == "volt_discharge":
        primary_radius_m = 20.0 * range_mult
        coil_r = 8.0 * range_mult
        combo_sec = 2.0 / cast_speed_mult
        combo_energy = 100.0 * eff_factor
        cluster_n = 5
        direct_dmg = cluster_n * 1200.0 * four_strength * min(6.0, 6.0 * duration) * roar_direct * vuln_mult
        damage_type_zh = "多目标特斯拉线圈互电（群怪密度乘算）"
        ignores_los = True
        radius_summary_zh = f"释放扩散 {primary_radius_m:.1f}m(穿墙) / 线圈互电 {coil_r:.1f}m"
        build_checks.append({"status": "info", "textZh": "机制提示：落单目标前 4.5s 不会自电受伤，3D 靶场建议选「地图炮 + 枪械补刀」由武器收掉零散残敌"})
        nuke.update({
            "titleZh": "Volt - 4 电能释放特斯拉互电清场",
            "comboSequenceZh": "敌群达 3 人以上施放 4 电能释放（穿墙化作特斯拉线圈互电清群）-> 落单残敌交由枪械补刀",
            "notesZh": f"释放半径 {primary_radius_m:.1f}m / 邻体互电半径 {coil_r:.1f}m 穿墙，怪物越密集互电总伤越高。",
        })

    elif setup_id == "gyre_rotorswell":
        primary_radius_m = 10.0 * range_mult
        ignores_los = False
        has_grace = "/lotus/powersuits/gyre/abilities/gyreenergizedability" in ab_paths or "/lotus/powersuits/gyre/abilities/gyrecathodeability" in ab_paths
        has_cc_aug = "/lotus/powersuits/gyre/gyrecathodeaugmentcard" in mod_tokens
        combo_sec = (1.6333 + 1.30) / cast_speed_mult
        combo_energy = (75.0 + 100.0) * eff_factor
        crit_m = 1.0 + min(3.0, 0.50 * strength + 1.50) * 1.0
        direct_dmg = 4.0 * 1500.0 * four_strength * crit_m * roar_direct * vuln_mult
        dot_dmg = direct_dmg * 0.50 * roar_direct * (1.0 + pageflight_dot_vuln)
        damage_type_zh = "技能红暴连锁电击 + 电击异常"
        radius_summary_zh = f"旋流与阴极电流放电 {primary_radius_m:.1f}m (连锁受视线判定)"
        build_checks.append({
            "status": "ok" if has_cc_aug else "warn",
            "textZh": "已装配集团卡［阴极电流］：击杀瞬发连锁电弧并同步延长 4 技能持续时间" if has_cc_aug else "建议装入集团卡［阴极电流］解锁击杀延长 4 技能与高伤连锁电弧",
        })
        nuke.update({
            "titleZh": "Gyre - 3 阴极优雅 + 4 旋流击杀续时连锁流",
            "comboSequenceZh": "开局开启 3 阴极优雅 + 4 旋流 -> 依靠武器与电弧击杀自动延长双技能持续（无需频繁重按施放）",
            "notesZh": f"放电半径 {primary_radius_m:.1f}m，自带 +{1.5 * strength:.1f}/s 回蓝，持续期内击杀自动续杯（上限 60s / 40s）。",
        })

    elif setup_id == "frost_avalanche":
        primary_radius_m = 15.0 * range_mult
        av_cast_mult = min(1.50, cast_speed_mult)
        combo_sec = 2.6667 / av_cast_mult
        combo_energy = 100.0 * eff_factor
        ability_armor_strip = min(1.0, max(ability_armor_strip, 0.60 * four_strength))
        has_biting = "/lotus/powersuits/frost/frostpassiveaugmentcard" in mod_tokens
        bf_mult = (1.0 + 2.0 * (3.0 - 1.0)) if has_biting else 1.0
        direct_dmg = (1500.0 + 400.0) * four_strength * bf_mult * roar_direct * vuln_mult
        damage_type_zh = "先永久削甲再结算冰冻爆破"
        ignores_los = True
        radius_summary_zh = f"雪崩冻结削甲 {primary_radius_m:.1f}m(穿墙) / 冰碎 {4.5 * range_mult:.1f}m"
        build_checks.append({
            "status": "ok" if ability_armor_strip >= 0.999 else "warn",
            "textZh": f"当前雪崩单发永久削甲 {round(ability_armor_strip * 100)}%" + ("（已达 100% 满削甲阈值）" if ability_armor_strip >= 0.999 else "（堆至 167% 技能强度即可单发 100% 永久削甲）"),
        })
        nuke.update({
            "titleZh": "Frost - 4 雪崩瞬冻满削甲穿墙清场",
            "comboSequenceZh": "4 雪崩（施放速度上限 1.5x；先剥离护甲并冻结，再结算冰冻伤害与阵亡冰碎爆破）",
            "notesZh": f"半径 {primary_radius_m:.1f}m 穿墙，{'已启用［刺骨寒霜］双暴加成' if has_biting else '可选配［刺骨寒霜］与［冰封护甲］提升暴击与超宏生存'}。",
        })

    elif setup_id == "ember_inferno":
        primary_radius_m = 25.0 * range_mult
        has_fb = "/lotus/powersuits/ember/abilities/fireblastability" in ab_paths
        ignores_los = False
        combo_sec = ((0.6333 if has_fb else 0.0) + 1.1333) / cast_speed_mult
        combo_energy = ((50.0 if has_fb else 0.0) + 100.0) * eff_factor
        ability_armor_strip = 1.0 if has_fb else ability_armor_strip
        direct_dmg = 2500.0 * four_strength * roar_direct * vuln_mult
        dot_dmg = (0.50 * direct_dmg * 6.0 + 700.0 * four_strength * 5.0) * roar_direct * (1.0 + pageflight_dot_vuln)
        damage_type_zh = ("火焰冲击削甲 + " if has_fb else "") + "陨石直击与火环持续灼烧"
        radius_summary_zh = f"陨石索敌 {primary_radius_m:.1f}m (需视线，耗蓝上限 10 目标)"
        build_checks.append({
            "status": "ok" if has_fb else "warn",
            "textZh": "3 技能［火焰冲击］已保留：遇到有护甲目标会先剥甲再落火陨" if has_fb else "3 技能［火焰冲击］已被替换：失去原生范围剥甲",
        })
        nuke.update({
            "titleZh": "Ember - 3 火焰冲击削甲 + 4 地狱烈焰火环清场",
            "comboSequenceZh": f"{'对有甲敌群先放 3 火焰冲击剥甲 -> ' if has_fb else ''}4 地狱烈焰（按实际目标数扣蓝，封顶 10 目标；已挂火环目标不重复乱砸）",
            "notesZh": f"视线索敌半径 {primary_radius_m:.1f}m，火环持续 {15.0 * duration:.1f}s 灼烧。",
        })

    elif setup_id == "mag_crush":
        primary_radius_m = 18.0 * range_mult
        has_frac = "/lotus/powersuits/mag/crushaugmentcard" in mod_tokens
        crush_speed = max(0.10, cast_speed_mult + (0.50 if has_frac else 0.0))
        combo_sec = 2.8667 / crush_speed
        combo_energy = 100.0 * eff_factor
        if has_frac:
            ability_armor_strip = min(1.0, max(ability_armor_strip, 0.75 * four_strength))
        direct_dmg = 1500.0 * four_strength * roar_direct * vuln_mult
        damage_type_zh = "穿墙磁暴粉碎" + (" + 碎裂粉碎永久削甲" if has_frac else "")
        ignores_los = True
        radius_summary_zh = f"粉碎半径 {primary_radius_m:.1f}m (360°穿墙)"
        build_checks.append({
            "status": "ok" if has_frac else "warn",
            "textZh": f"已装［碎裂粉碎］（+50%施放速度，单发永久削甲 {round(ability_armor_strip * 100)}%）" if has_frac else "建议装配集团卡［碎裂粉碎］（134% 强度即可单发永久满削甲并提速 50%）",
        })
        nuke.update({
            "titleZh": "Mag - 4 粉碎穿墙破盾削甲清场",
            "comboSequenceZh": "4 粉碎（穿墙三段磁力伤害并恢复过载护盾，配碎裂粉碎先剥除护甲）",
            "notesZh": f"半径 {primary_radius_m:.1f}m 穿墙，适合 Corpus 与剥甲后混合派系清波。",
        })

    elif setup_id == "nezha_divine_retribution":
        has_retrib = "/lotus/powersuits/nezha/nezhaspearaugmenttwocard" in mod_tokens
        primary_radius_m = (9.5 if has_retrib else 19.0) * range_mult
        combo_sec = (0.85 + 0.75) / cast_speed_mult + 0.5
        combo_energy = 100.0 * eff_factor
        impale_dmg = 1200.0 * four_strength * roar_direct * vuln_mult
        spread_dot = (4500.0 * four_strength * 1.5 * four_strength * roar_dot_double * vuln_mult) if has_retrib else 0.0
        direct_dmg = impale_dmg + spread_dot
        bypasses_armor = has_retrib
        damage_type_zh = "神圣报应传导切割/火/毒浓缩引爆" if has_retrib else "圣火尖枪穿刺控制（未装神圣报应）"
        ignores_los = True
        radius_summary_zh = f"尖枪控制与引爆 {primary_radius_m:.1f}m (穿墙，{'集团卡已折算 0.5x 基础半径' if has_retrib else '原版半径'})"
        build_checks.append({
            "status": "ok" if has_retrib else "warn",
            "textZh": "已装配集团卡［神圣报应］：穿刺联动扩散异常并在二段砸地时按 1.5×强度浓缩结算" if has_retrib else "当前未装［神圣报应］：仅生效基础尖枪控制直伤，请装入［神圣报应］解锁异常传染浓缩核爆！",
        })
        nuke.update({
            "titleZh": "Nezha - 4 圣火尖枪［神圣报应］异常浓缩流",
            "comboSequenceZh": "一段 4 穿墙穿刺控场 -> 武器挂异常自动联动传导 -> 二段 4 拍地浓缩结算剩余持续伤害",
            "notesZh": f"当前有效尖枪半径 {primary_radius_m:.1f}m 穿墙，建议选「地图炮 + 枪械补刀」配合高触发武器铺异常。",
        })

    else:  # nokko_sporespring
        primary_radius_m = 12.0 * range_mult
        combo_sec = 1.0 / cast_speed_mult
        combo_energy = 100.0 * eff_factor
        direct_dmg = 4.0 * 1200.0 * four_strength * roar_direct * vuln_mult
        dot_dmg = direct_dmg * 0.50 * 6.0 * roar_direct * (1.0 + pageflight_dot_vuln)
        damage_type_zh = "3段弹跳毒气/毒素孢子爆炸"
        ignores_los = True
        radius_summary_zh = f"孢弹菇索敌与弹跳爆炸 {primary_radius_m:.1f}m (穿墙)"
        build_checks.append({
            "status": "ok" if arbucep else "info",
            "textZh": "已勾选［蕈菇 200% 强化］：2 技能亮帽菇回蓝与强度加成翻倍" if arbucep else "可勾选上方［携带空战武器蕈菇激活亮帽菇 200%］进一步翻倍回能与强度",
        })
        nuke.update({
            "titleZh": "Nokko - 2 亮帽菇 + 4 孢弹菇多段弹跳流",
            "comboSequenceZh": "技能循环自动维持 2 亮帽菇回能加攻强 -> 4 孢弹菇向敌群连续弹跳 3 次爆散毒气与毒素异常",
            "notesZh": f"单跳波及半径 {primary_radius_m:.1f}m，2 技能由循环器自动维护不重复扣蓝。",
        })

    if self_bb_eps > 0.0:
        build_checks.append({
            "status": "ok",
            "textZh": f"回能就绪：已配置［亮帽菇{' + 蕈菇200%' if arbucep else ''}］稳定提供 +{steady_energy_in_per_sec:.1f}/s 能量回复",
        })
    elif has_energize or has_zenurik:
        build_checks.append({
            "status": "ok",
            "textZh": f"回能辅助：已启用{'［赋能·充沛］' if has_energize else ''}{' + ' if (has_energize and has_zenurik) else ''}{'［Zenurik 专精］' if has_zenurik else ''}支撑多波续航",
        })
    else:
        build_checks.append({
            "status": "warn",
            "textZh": "续航提示：当前未检测到亮帽菇移植、赋能充沛或 Zenurik 专精，长波次高频施放可能出现缺蓝等待",
        })

    nuke["buildChecks"] = build_checks
    nuke["radiusSummaryZh"] = radius_summary_zh
    nuke["workflowGuideZh"] = [
        "1. 多玩法切换：若当前战甲存在多套流派（如 Mirage 的「2 爆炸戏法+1 镜厅小宝石」与「4 棱镜激光」，或注入了热能抽离），可直接在上方路线按钮或 3D 靶场左侧切换。",
        "2. 技能分工：增益/回能技能（如镜厅、黯然失色、亮帽菇）由战甲技能循环自动维持；主清技能由地图炮状态机按战场条件（掉落物数量、敌群密度、视线）智能施放。",
        "3. 靶场实测：下方波次耗时仅为无地形木桩理论斩杀估算；点击「前往 3D 靶场」可在真实地图高台视野、掩体遮挡、掉落物坐标与枪械补刀下完整回放。",
    ]

    total_combo_dmg = direct_dmg + dot_dmg
    eff_arm_strip = min(1.0, max(ability_armor_strip, aura_arm_red))

    # Compute 1D Normal Defense (Lv 30) & Steel Path Defense (Lv 130, 2.5x HP/Shield/Armor) wave estimates
    def _wave_est(level: int, sp: bool) -> dict[str, Any]:
        # Standard Grineer Lancer / Elite Lancer representative wave unit
        synth_enemy = {
            "health": 100.0,
            "shield": 0.0,
            "armour": 100.0,
            "baseLevel": 1,
            "faction": "RK_GRINEER_FACTION",
        }
        defs = enemy_defenses(
            synth_enemy,
            level=level,
            armour_strip=eff_arm_strip,
            steel_path=sp,
            enemy_enhancements={"auraArmourReduction": aura_arm_red},
        )
        hp = float(defs.get("health") or 1.0)
        arm = 0.0 if bypasses_armor else float(defs.get("armour") or defs.get("armor") or 0.0)
        dr = min(0.90, arm / (arm + 300.0)) if arm > 0.0 else 0.0
        eff_hp = hp / max(0.10, 1.0 - dr)

        if nuke.get("scalesWithEnemyMaxHp"):
            # Equinox Maim: 2 fodder kills fund 1.5x enemy max HP Slash burst!
            casts_needed = 1
        elif nuke.get("trueHpPercentPerCombo"):
            pct = max(0.05, float(nuke["trueHpPercentPerCombo"]))
            casts_needed = max(1, math.ceil(1.0 / pct))
        else:
            casts_needed = max(1, math.ceil(eff_hp / max(1.0, total_combo_dmg)))

        # Spawn travel + LoS coverage factor in a 4p Defense wave (~36 enemies, 2 spawn batches)
        spawn_batches = 2 if not sp else 3
        straggler_ratio = 0.08 if ignores_los else 0.18
        if sp:
            # Eximus Overguard stragglers handled by hybrid gun cleanup
            straggler_ratio = min(0.35, straggler_ratio + 0.07)
        est_wave_sec = round(spawn_batches * max(4.5, casts_needed * combo_sec + 2.5), 1)
        return {
            "level": level,
            "steelPath": sp,
            "targetEffectiveHp": round(eff_hp, 1),
            "combosPerBatch": casts_needed,
            "estimatedWaveClearSec": est_wave_sec,
            "abilityKillShareEstimate": round(1.0 - straggler_ratio, 3),
            "gunCleanupShareEstimate": round(straggler_ratio, 3),
        }

    energy_drain_rate = combo_energy / max(0.5, combo_sec)
    nuke.update({
        "primaryRadiusM": round(primary_radius_m, 2),
        "ignoresLoS": ignores_los,
        "losLabelZh": nuke.get("losLabelZh") or ("无视视线穿墙" if ignores_los else "受掩体/镜头视野限制"),
        "damageTypeZh": damage_type_zh,
        "comboTimingSec": round(combo_sec, 2),
        "comboEnergyCost": round(combo_energy, 1),
        "comboEnergyPerSec": round(energy_drain_rate, 2),
        "energySelfSustaining": steady_energy_in_per_sec + 3.5 >= energy_drain_rate * 0.65,
        "effectiveArmorStrip": round(eff_arm_strip, 4),
        "directDamagePerCombo": round(direct_dmg, 1),
        "dotDamagePerCombo": round(dot_dmg, 1),
        "totalDamagePerCombo": round(total_combo_dmg, 1),
        "normalDefenseWave": _wave_est(30, False),
        "steelPathDefenseWave": _wave_est(130, True),
    })
    return nuke


__all__ = [
    "nuke_specs",
    "extract_warframe_ability_ranges",
    "resolve_exalted_nuke_stats",
    "list_warframe_nuke_setups",
    "detect_nuke_setup_id",
    "evaluate_warframe_nuke_preview",
]
