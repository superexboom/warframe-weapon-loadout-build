"""Operator Focus 3.0+ & Tauron Ultimates combat bridge & preview evaluator.

Loads ``data/mechanics/focus-catalog.json`` (extracted from client Packages.bin,
Languages.bin, and Luau bytecode) and evaluates all 50 standard nodes + 25 Tauron
Ultimate branch nodes, parent-chain unlock rules, cross-school Way-Bound unbinding,
Focus Point investment, and deterministic ``combatBridge`` modifiers for Weapon,
Warframe, Realistic Ability Rotation, and 3D Arena calculations.
"""

from __future__ import annotations

import copy
from functools import lru_cache
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from .simulator import SimulationError


SCHOOL_IDS = ("madurai", "vazarin", "naramon", "unairu", "zenurik")
TRIGGER_MODES = ("passive", "cycle", "peak")

PRIMARY_WEAPON_TYPE = "/Lotus/Weapons/Tenno/LotusLongGun"
SECONDARY_WEAPON_TYPE = "/Lotus/Weapons/Tenno/Pistol/LotusPistol"
MELEE_WEAPON_TYPE = "/Lotus/Types/Game/LotusMeleeWeapon"
GUN_WEAPON_TYPES = [PRIMARY_WEAPON_TYPE, SECONDARY_WEAPON_TYPE]

# Strictly Operator/Amp-only nodes verified in Luau bytecode (must NEVER apply to Warframe/weapons).
OPERATOR_AMP_ONLY_NODE_IDS = frozenset({
    "madurai_contamination_wave",
    "madurai_distilled_contamination",
    "naramon_amp_spike",
    "unairu_unairu_wisp",
})

# Naramon nodes requiring explicit multi-step Operator setup (slam / lift wave + 4 hits / finisher).
NARAMON_HEAVY_PRECONDITION_IDS = frozenset({
    "naramon_opening_slam",
    "naramon_void_levitation",
    "naramon_lethal_levitation",
    "naramon_killers_rush",
    "naramon_sling_stun",
})

# Client-verified Tauron Ultimate metadata keyed by internalTag.
_TAURON_RELEVANCE_BY_TAG: dict[str, dict[str, Any]] = {
    "AttackUltimate": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["enemy_crowd"],
        "notesZh": "召唤狂勇巨弓向空中齐射爆炸箭雨，持续 4/5/6/7 秒。",
    },
    "AttackUltimateStrength": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["warframe_abilities"],
        "notesZh": "Tauron 打击每首次命中一名敌人 +2%/3%/4%/5% 技能强度，最高 +20%/30%/40%/50%（加算），持续 30 秒。",
        "modifiers": [
            {
                "stat": "ability_strength",
                "engineUpgradeType": "AVATAR_ABILITY_STRENGTH",
                "operationType": "ADD",
                "stackingBucket": "ability_strength_additive",
                "appliesTo": "warframe_abilities",
                "valuesByRank": [0.20, 0.30, 0.40, 0.50],
            }
        ],
    },
    "AttackUltimateCooldown": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["warframe_weapons"],
        "notesZh": "造成伤害时追射爆炸箭矢（冷却 0.50/0.45/0.40/0.35 秒），持续 30 秒。",
    },
    "AttackUltimateDouble": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["warframe_weapons"],
        "notesZh": "箭雨额外锁定 10m 内 1/2/3/4 名敌人。",
    },
    "AttackUltimateRadius": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["warframe_weapons"],
        "notesZh": "箭雨爆炸半径扩大至 3.5/4.0/4.5/5.0 米。",
    },
    "DefenseUltimate": {
        "category": "enemy_debuff",
        "isConditional": True,
        "targets": ["enemy_crowd", "warframe_weapons", "warframe_abilities"],
        "notesZh": "义决漩涡持续 20 秒，将对漩涡内敌人造成的 20%/30%/40%/50% 伤害共享传导给漩涡内所有其他敌人。",
        "modifiers": [
            {
                "stat": "vortex_shared_damage_fraction",
                "operationType": "ADD",
                "appliesTo": "enemy_defenses",
                "valuesByRank": [0.20, 0.30, 0.40, 0.50],
            }
        ],
    },
    "DefenseUltimateDuration": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["enemy_crowd"],
        "notesZh": "延长义决漩涡持续时间至 25/30/35/40 秒。",
    },
    "DefenseUltimateHeal": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["warframe"],
        "notesZh": "漩涡内每秒恢复 100/150/200/250 生命值。",
        "modifiers": [
            {
                "stat": "health_regen_per_sec",
                "operationType": "ADD",
                "appliesTo": "warframe",
                "valuesByRank": [100.0, 150.0, 200.0, 250.0],
            }
        ],
    },
    "DefenseUltimateElemental": {
        "category": "enemy_debuff",
        "isConditional": True,
        "targets": ["enemy_shields", "warframe_weapons"],
        "notesZh": "裂隙水域：漩涡每秒剥离敌人 10%/15%/20%/25% 超宏防护。",
        "modifiers": [
            {
                "stat": "overguard_strip_per_sec",
                "operationType": "ADD",
                "appliesTo": "enemy_defenses",
                "valuesByRank": [0.10, 0.15, 0.20, 0.25],
            }
        ],
    },
    "DefenseUltimateProcVuln": {
        "category": "enemy_debuff",
        "isConditional": True,
        "targets": ["enemy_crowd", "warframe_weapons", "warframe_abilities"],
        "notesZh": "侵蚀急流：对漩涡内敌人施加 +25%/50%/75%/100% 异常状态几率易伤。",
        "modifiers": [
            {
                "stat": "status_chance_vulnerability",
                "operationType": "STACKING_MULTIPLY",
                "appliesTo": "enemy_defenses",
                "valuesByRank": [0.25, 0.50, 0.75, 1.00],
            }
        ],
    },
    "TacticUltimate": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "断命斩击每命中一名敌人提供 +2/+4/+6/+8 近战连击计数。",
    },
    "TacticUltimateSize": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "断命斩击范围扩大 +20%/40%/60%/80%。",
    },
    "TacticUltimateNumber": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "幻影之刃：为经验共享范围内队友召唤 1/2/3/4 把近战幻影，30 秒内随近战挥砍同步攻击 10m 内敌人并叠加连击。",
        "modifiers": [
            {
                "stat": "spectral_blades_count",
                "operationType": "ADD",
                "appliesTo": "melee_weapons",
                "valuesByRank": [1, 2, 3, 4],
            }
        ],
    },
    "TacticUltimateRange": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "流动打击：幻影之刃索敌范围提升至 14/18/22/26 米。",
    },
    "TacticUltimateDouble": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "饥饿之刃：幻影之刃有 25%/50%/75%/100% 几率造成二次连击命中。",
    },
    "WardUltimate": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["enemy_crowd"],
        "notesZh": "坚毅巨锤震地冲击波。",
    },
    "WardUltimateArmor": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["warframe"],
        "notesZh": "温和祝福：生成 2/3/4/5 枚护甲微粒，每枚提供 450 临时护甲（满阶最高 +2250 固定护甲）。",
        "modifiers": [
            {
                "stat": "warframe_and_operator_armor",
                "engineUpgradeType": "AVATAR_ARMOUR",
                "operationType": "ADD",
                "stackingBucket": "flat_final_armor_additive",
                "appliesTo": "warframe_and_operator",
                "valuesByRank": [900.0, 1350.0, 1800.0, 2250.0],
            }
        ],
    },
    "WardUltimateChance": {
        "category": "energy_economy",
        "isConditional": True,
        "targets": ["warframe_energy"],
        "notesZh": "撕裂馈赠：冲击波额外生成 2/3/4/5 枚通用球与弹药。",
    },
    "WardUltimateSlam": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["melee_weapons"],
        "notesZh": "震荡冲击：接下来 1/2/3/4 次空中近战震地释放坚毅冲击波。",
    },
    "WardUltimateRange": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["enemy_crowd"],
        "notesZh": "冲击波范围扩大。",
    },
    "PowerUltimate": {
        "category": "energy_economy",
        "isConditional": True,
        "targets": ["warframe_energy"],
        "notesZh": "落书光束穿透的敌人在 10 秒内被击杀有 25%/50%/75%/100% 几率掉落能量球。",
        "modifiers": [
            {
                "stat": "kill_energy_orb_chance",
                "operationType": "ADD",
                "appliesTo": "warframe_energy",
                "valuesByRank": [0.25, 0.50, 0.75, 1.00],
            }
        ],
    },
    "PowerUltimateNumber": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["warframe", "warframe_abilities", "warframe_energy"],
        "notesZh": "幻影书页：生成 1/2/3/4 页书页，每页提供 +10% 技能强度、+10% 技能持续、+10% 施放速度与 +100 额外能量。",
        "modifiers": [
            {
                "stat": "spectral_pages_count",
                "operationType": "ADD",
                "appliesTo": "warframe_abilities",
                "valuesByRank": [1, 2, 3, 4],
            }
        ],
    },
    "PowerUltimateBuff": {
        "category": "warframe_buff",
        "isConditional": True,
        "targets": ["warframe_abilities"],
        "notesZh": "无限能量：幻影书页提供的强度、持续与施放速度增益额外放大 +25%/30%/35%/40%（满阶 4 页合计 +56% 强度/持续/施放速度与 +400 能量）。",
        "modifiers": [
            {
                "stat": "spectral_pages_multiplier_bonus",
                "operationType": "MULTIPLY",
                "appliesTo": "warframe_abilities",
                "valuesByRank": [0.25, 0.30, 0.35, 0.40],
            }
        ],
    },
    "PowerUltimateDuration": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["warframe_abilities"],
        "notesZh": "延长幻影书页持续时间。",
    },
    "PowerUltimateWidth": {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["enemy_crowd"],
        "notesZh": "扩大落书光束宽度。",
    },
}


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().casefold()).strip("_")
    return cleaned or "node"


def _mechanics_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "data" / "mechanics"


def _normalize_ultimate_node(school_id: str, raw_node: Mapping[str, Any]) -> dict[str, Any]:
    node = dict(raw_node)
    tag = str(node.get("internalTag") or "").strip()
    nid = str(node.get("id") or "").strip()
    if not nid:
        nid = f"{school_id}_ult_{_slugify(node.get('nameEn') or tag)}"
    max_rank = int(node.get("maxRank") or 3)
    descs_by_rank = node.get("descriptionsByRank") if isinstance(node.get("descriptionsByRank"), list) else []
    descs_zh = list(node.get("descriptionsZh") or [str(d.get("zh") or d.get("en") or "") for d in descs_by_rank if isinstance(d, Mapping)])
    base_cost = int(node.get("baseFocusPointCost") or 60000)
    fp = dict(node["focusPoints"]) if isinstance(node.get("focusPoints"), Mapping) else {
        "unlockFocusPoints": base_cost,
        "costsByRank": [base_cost * (r + 1) for r in range(max_rank + 1)],
    }
    rel = dict(node["combatRelevance"]) if isinstance(node.get("combatRelevance"), Mapping) else dict(_TAURON_RELEVANCE_BY_TAG.get(tag) or {
        "category": "tauron_ultimate",
        "isConditional": True,
        "targets": ["operator"],
        "notesZh": "",
    })
    node.update({
        "id": nid,
        "schoolId": school_id,
        "maxRank": max_rank,
        "isRoot": False,
        "isWayBound": False,
        "isTauronUltimate": True,
        "activationType": str(node.get("activationType") or "tauron_strike"),
        "triggerDetail": "tauron_ultimate_strike",
        "descriptionsZh": descs_zh,
        "focusPoints": fp,
        "combatRelevance": rel,
    })
    return node


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    path = _mechanics_dir() / "focus-catalog.json"
    if not path.is_file():
        raise SimulationError(f"focus catalog missing: {path}")
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    schools_out: list[dict[str, Any]] = []
    for school in raw.get("schools") or ():
        if not isinstance(school, Mapping):
            continue
        sc = dict(school)
        sid = str(sc.get("id") or "").strip().casefold()
        ult_raw = sc.get("ultimateBranchNodes") or ()
        sc["ultimateBranchNodes"] = [
            _normalize_ultimate_node(sid, u)
            for u in ult_raw
            if isinstance(u, Mapping)
        ]
        schools_out.append(sc)
    raw["schools"] = schools_out
    return raw


def get_focus_catalog() -> dict[str, Any]:
    return copy.deepcopy(catalog())


def _index_catalog(
    cat: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    schools_by_id: dict[str, Mapping[str, Any]] = {}
    nodes_by_id: dict[str, Mapping[str, Any]] = {}
    nodes_by_path: dict[str, Mapping[str, Any]] = {}
    for school in cat.get("schools") or ():
        if not isinstance(school, Mapping):
            continue
        sid = str(school.get("id") or "").strip().casefold()
        if not sid:
            continue
        schools_by_id[sid] = school
        all_school_nodes = [
            *(school.get("nodes") or ()),
            *(school.get("ultimateBranchNodes") or ()),
        ]
        for node in all_school_nodes:
            if not isinstance(node, Mapping):
                continue
            nid = str(node.get("id") or "").strip()
            npath = str(node.get("path") or "").strip()
            ntag = str(node.get("internalTag") or "").strip()
            if nid:
                nodes_by_id[nid] = node
            if ntag and ntag not in nodes_by_id:
                nodes_by_id[ntag] = node
            if npath:
                nodes_by_path[npath] = node
    return schools_by_id, nodes_by_id, nodes_by_path


def _resolve_node_state(
    school: Mapping[str, Any],
    raw_school_cfg: Mapping[str, Any] | None,
    *,
    default_maxed: bool = False,
    default_tauron_maxed: bool = False,
) -> dict[str, dict[str, Any]]:
    raw_nodes: Mapping[str, Any] = {}
    if isinstance(raw_school_cfg, Mapping):
        src = raw_school_cfg.get("nodes") if isinstance(raw_school_cfg.get("nodes"), Mapping) else raw_school_cfg
        if isinstance(src, Mapping):
            raw_nodes = src

    nodes = [
        n
        for n in (*(school.get("nodes") or ()), *(school.get("ultimateBranchNodes") or ()))
        if isinstance(n, Mapping)
    ]
    out: dict[str, dict[str, Any]] = {}

    for node in nodes:
        nid = str(node.get("id") or "")
        npath = str(node.get("path") or "")
        ntag = str(node.get("internalTag") or "")
        max_rank = int(node.get("maxRank") or 3)
        is_root = bool(node.get("isRoot"))
        is_ult = bool(node.get("isTauronUltimate"))
        use_default_max = default_tauron_maxed if is_ult else default_maxed

        entry = raw_nodes.get(nid)
        if entry is None and npath:
            entry = raw_nodes.get(npath)
        if entry is None and ntag:
            entry = raw_nodes.get(ntag)

        if isinstance(entry, Mapping):
            unlocked = bool(entry.get("unlocked", True if is_root else False))
            rank = max(0, min(max_rank, int(entry.get("rank", max_rank if use_default_max else 0))))
            enabled = bool(entry.get("enabled", True))
            unbound = bool(entry.get("unbound", False))
        elif isinstance(entry, int) and not isinstance(entry, bool):
            unlocked = entry >= 0
            rank = max(0, min(max_rank, int(entry)))
            enabled = unlocked
            unbound = False
        else:
            unlocked = True if (is_root or use_default_max) else False
            rank = max_rank if use_default_max else 0
            enabled = unlocked
            unbound = False

        if is_root and raw_school_cfg is not None and bool(raw_school_cfg.get("schoolUnlocked", True)):
            unlocked = True

        out[nid] = {
            "id": nid,
            "path": npath,
            "parentPath": node.get("parentPath"),
            "isRoot": is_root,
            "isWayBound": bool(node.get("isWayBound")),
            "isTauronUltimate": is_ult,
            "unlocked": unlocked,
            "rank": rank if unlocked else 0,
            "maxRank": max_rank,
            "enabled": enabled and unlocked,
            "unbound": unbound and bool(node.get("isWayBound")) and unlocked and rank >= max_rank,
        }

    # Enforce parent-chain reachability across both standard and Tauron nodes.
    id_by_path = {str(n.get("path") or ""): str(n.get("id") or "") for n in nodes}
    changed = True
    while changed:
        changed = False
        for _nid, st in out.items():
            if not st["unlocked"] or st["isRoot"]:
                continue
            parent_path = str(st.get("parentPath") or "")
            parent_id = id_by_path.get(parent_path)
            if parent_id and not out[parent_id]["unlocked"]:
                st["unlocked"] = False
                st["enabled"] = False
                st["rank"] = 0
                st["unbound"] = False
                changed = True
            elif parent_id and not out[parent_id]["enabled"] and st["enabled"]:
                st["enabled"] = False
                changed = True

    return out


def _node_focus_cost(node: Mapping[str, Any], st: Mapping[str, Any]) -> tuple[int, int]:
    if not st.get("unlocked"):
        return 0, 0
    fp = node.get("focusPoints") if isinstance(node.get("focusPoints"), Mapping) else {}
    costs = fp.get("costsByRank") if isinstance(fp.get("costsByRank"), list) else []
    rank = int(st.get("rank") or 0)
    spent = sum(int(costs[idx]) for idx in range(min(rank + 1, len(costs))))
    shards = 0
    if st.get("unbound") and node.get("isWayBound"):
        unbind = fp.get("unbindCost")
        if isinstance(unbind, Mapping):
            spent += int(unbind.get("focusPoints") or 750000)
            shards += int(unbind.get("brilliantEidolonShards") or 1)
        elif isinstance(unbind, int):
            spent += unbind
            shards += 1
        else:
            spent += 750000
            shards += 1
    return spent, shards


def _format_modifier_value(stat: str, val: Any, op: str) -> str:
    if isinstance(val, (int, float)):
        fval = float(val)
        if "flat" in stat or stat in {
            "warframe_and_operator_armor",
            "energy_per_second",
            "combo_decay_per_step",
            "free_cast_cooldown_sec",
            "health_regen_per_sec",
            "spectral_blades_count",
            "spectral_pages_count",
        }:
            return f"{fval:g}"
        if abs(fval) <= 20.0 and (
            "STACKING_MULTIPLY" in op
            or "ADD" in op
            or "bonus" in stat
            or "strip" in stat
            or "chance" in stat
            or "speed" in stat
            or "efficiency" in stat
            or "strength" in stat
            or "damage" in stat
            or "multiplier" in stat
            or "vulnerability" in stat
        ):
            sign = "+" if fval >= 0 else ""
            return f"{sign}{round(fval * 100, 2):g}%"
        return f"{fval:g}"
    return str(val)


def _rank_val(seq: list[float] | tuple[float, ...], rank: int) -> float:
    return float(seq[max(0, min(int(rank), len(seq) - 1))])


def _compile_combat_bridge(
    *,
    active_school: str,
    act_states: Mapping[str, Mapping[str, Any]],
    trigger_mode: str,
    enable_naramon_preconditions: bool,
    enable_tauron_strike: bool,
    active_triggers_raw: Mapping[str, Any],
    void_strike_energy_pct: float = 1.0,
) -> dict[str, Any]:
    """Compile exact client-verified combat modifiers from active Focus states."""
    weapon_effects_spec: list[dict[str, Any]] = []
    warframe_mods = {
        "abilityStrengthAdd": 0.0,
        "abilityDurationAdd": 0.0,
        "castingSpeedAdd": 0.0,
        "flatArmorAdd": 0.0,
        "flatEnergyBonus": 0.0,
        "shieldRechargeRateAdd": 0.0,
        "shieldRechargeDelayAdd": 0.0,
        "healthRegenPerSec": 0.0,
        "affinityRadiusBonusM": 0.0,
        "knockdownImmune": False,
    }
    energy_econ = {
        "wellspringEnergyPerSec": 0.0,
        "energyPulseBonusFraction": 0.0,
        "innerMightCooldownSec": 0.0,
        "tauronKillEnergyOrbChance": 0.0,
    }
    melee_combo = {
        "powerSpikeDecayStep": None,
        "extraComboChanceAdd": 0.0,
        "spectralBladesCount": 0,
        "spectralBladesRangeM": 0.0,
        "spectralBladesDoubleChance": 0.0,
    }
    enemy_debuffs = {
        "armorStripFraction": 0.0,
        "shieldStripFraction": 0.0,
        "overguardStripPerSec": 0.0,
        "statusChanceVulnerability": 0.0,
        "slowFraction": 0.0,
        "liftedStatus": False,
        "finisherVulnerability": 0.0,
        "vortexSharedDamageFraction": 0.0,
    }
    summary_pills: list[str] = []
    transference_cycles_per_min = 0.0

    def _node_rank(nid: str) -> int | None:
        st = act_states.get(nid)
        if not st or not st.get("enabled"):
            return None
        return int(st.get("rank") or 0)

    def _cond_factor(nid: str, *, cycle_factor: float = 1.0, cycle_period_sec: float = 20.0, is_naramon_heavy: bool = False) -> float:
        if nid in OPERATOR_AMP_ONLY_NODE_IDS:
            return 0.0
        if nid in active_triggers_raw:
            return 1.0 if bool(active_triggers_raw[nid]) else 0.0
        if trigger_mode == "passive":
            return 0.0
        if is_naramon_heavy and not enable_naramon_preconditions:
            return 0.0
        if trigger_mode == "peak":
            return 1.0
        # trigger_mode == "cycle"
        nonlocal transference_cycles_per_min
        if cycle_period_sec > 0.0:
            transference_cycles_per_min = max(transference_cycles_per_min, 60.0 / cycle_period_sec)
        return max(0.0, min(1.0, float(cycle_factor)))

    # ── 1. Unconditional Always-On Passives (active in all 3 modes) ────────────
    if active_school == "madurai":
        rk = _node_rank("madurai_phoenix_talons")
        if rk is not None:
            val = _rank_val((0.05, 0.10, 0.20, 0.30), rk)
            for dt in ("DT_IMPACT", "DT_PUNCTURE", "DT_SLASH"):
                weapon_effects_spec.append({
                    "upgradeType": "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
                    "operation": "STACKING_MULTIPLY",
                    "value": val,
                    "damageType": dt,
                    "source": "focus:madurai_phoenix_talons",
                    "labelZh": "不死鸟之爪物理伤害",
                })
            summary_pills.append(f"不死鸟之爪 +{round(val * 100):g}%物理")

        rk = _node_rank("madurai_power_transfer")
        if rk is not None:
            dur = _rank_val((5.0, 10.0, 15.0, 20.0), rk)
            fac = _cond_factor("madurai_power_transfer", cycle_factor=min(1.0, dur / 20.0), cycle_period_sec=20.0)
            if fac > 0.0:
                val = round(_rank_val((0.20, 0.30, 0.40, 0.50), rk) * fac, 6)
                warframe_mods["castingSpeedAdd"] += val
                summary_pills.append(f"力量转移 +{round(val * 100):g}%施放速度")

        rk = _node_rank("madurai_sling_strength")
        if rk is not None and _node_rank("madurai_chained_sling") is not None:
            dur = _rank_val((5.0, 10.0, 15.0, 20.0), rk)
            fac = _cond_factor("madurai_sling_strength", cycle_factor=min(1.0, dur / 20.0), cycle_period_sec=20.0)
            if fac > 0.0:
                val = round(_rank_val((0.10, 0.20, 0.30, 0.40), rk) * fac, 6)
                warframe_mods["abilityStrengthAdd"] += val
                summary_pills.append(f"充能弹射 +{round(val * 100):g}%强度")

        rk = _node_rank("madurai_void_strike")
        if rk is not None:
            dur = _rank_val((5.0, 6.0, 7.0, 8.0), rk)
            cd = _rank_val((70.0, 60.0, 50.0, 40.0), rk)
            duty = dur / (dur + cd)
            fac = _cond_factor("madurai_void_strike", cycle_factor=duty, cycle_period_sec=dur + cd)
            if fac > 0.0:
                peak_bonus = _rank_val((4.0, 6.0, 8.0, 10.0), rk) * max(0.0, min(1.0, void_strike_energy_pct))
                eff_bonus = round(peak_bonus * fac, 6)
                if eff_bonus > 0.0:
                    weapon_effects_spec.extend([
                        {
                            "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                            "operation": "STACKING_MULTIPLY",
                            "value": eff_bonus,
                            "validTypes": GUN_WEAPON_TYPES,
                            "source": "focus:madurai_void_strike",
                            "labelZh": "虚空重击基础伤害",
                        },
                        {
                            "upgradeType": "WEAPON_MELEE_DAMAGE",
                            "operation": "STACKING_MULTIPLY",
                            "value": eff_bonus,
                            "validTypes": [MELEE_WEAPON_TYPE],
                            "source": "focus:madurai_void_strike",
                            "labelZh": "虚空重击近战伤害",
                        },
                    ])
                    mode_tag = "峰值" if trigger_mode == "peak" else f"周期折算{round(fac * 100)}%"
                    summary_pills.append(f"虚空重击 +{round(eff_bonus * 100):g}%基伤({mode_tag})")

                rk_fuel = _node_rank("madurai_void_fuel")
                if rk_fuel is not None:
                    eff_ammo = round(_rank_val((0.10, 0.20, 0.30, 0.40), rk_fuel) * fac, 6)
                    if eff_ammo > 0.0:
                        weapon_effects_spec.append({
                            "upgradeType": "WEAPON_AMMO_CONSUME_RATE",
                            "operation": "STACKING_MULTIPLY",
                            "value": -eff_ammo,
                            "validTypes": GUN_WEAPON_TYPES,
                            "source": "focus:madurai_void_fuel",
                            "labelZh": "虚空燃料弹药效率",
                        })

    elif active_school == "naramon":
        rk = _node_rank("naramon_power_spike")
        if rk is not None:
            step = int(_rank_val((20, 15, 10, 5), rk))
            melee_combo["powerSpikeDecayStep"] = step
            summary_pills.append(f"力量激增(连击仅衰减{step})")

        rk_open = _node_rank("naramon_opening_slam")
        if rk_open is not None:
            dur = _rank_val((5.0, 10.0, 15.0, 20.0), rk_open)
            fac = _cond_factor("naramon_opening_slam", cycle_factor=min(1.0, dur / 20.0), cycle_period_sec=20.0, is_naramon_heavy=True)
            if fac > 0.0:
                val = round(1.0 * fac, 6)
                melee_combo["extraComboChanceAdd"] += val
                weapon_effects_spec.append({
                    "upgradeType": "WEAPON_MELEE_COMBO_GAIN_EXTRA_CHANCE",
                    "operation": "ADD",
                    "value": val,
                    "validTypes": [MELEE_WEAPON_TYPE],
                    "source": "focus:naramon_opening_slam",
                    "labelZh": "旗开得胜双倍连击",
                })
                summary_pills.append(f"旗开得胜 +{round(val * 100):g}%连击获取")

        rk_lift = _node_rank("naramon_void_levitation")
        if rk_lift is not None:
            fac_lift = _cond_factor("naramon_void_levitation", cycle_factor=1.0, cycle_period_sec=40.0, is_naramon_heavy=True)
            if fac_lift > 0.0:
                enemy_debuffs["liftedStatus"] = True
                rk_lethal = _node_rank("naramon_lethal_levitation")
                if rk_lethal is not None:
                    dur = _rank_val((30.0, 40.0, 50.0, 60.0), rk_lethal)
                    fac_ll = _cond_factor("naramon_lethal_levitation", cycle_factor=min(1.0, dur / 45.0), cycle_period_sec=45.0, is_naramon_heavy=True)
                    if fac_ll > 0.0:
                        val = round(_rank_val((0.80, 1.20, 1.60, 2.00), rk_lethal) * fac_ll, 6)
                        weapon_effects_spec.extend([
                            {
                                "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                                "operation": "STACKING_MULTIPLY",
                                "value": val,
                                "validTypes": GUN_WEAPON_TYPES,
                                "source": "focus:naramon_lethal_levitation",
                                "labelZh": "致命悬浮武器伤害",
                            },
                            {
                                "upgradeType": "WEAPON_MELEE_DAMAGE",
                                "operation": "STACKING_MULTIPLY",
                                "value": val,
                                "validTypes": [MELEE_WEAPON_TYPE],
                                "source": "focus:naramon_lethal_levitation",
                                "labelZh": "致命悬浮近战伤害",
                            },
                        ])
                        summary_pills.append(f"致命悬浮 +{round(val * 100):g}%基伤")

        rk_kr = _node_rank("naramon_killers_rush")
        if rk_kr is not None:
            dur = _rank_val((10.0, 20.0, 30.0, 40.0), rk_kr)
            fac = _cond_factor("naramon_killers_rush", cycle_factor=min(1.0, dur / 40.0), cycle_period_sec=40.0, is_naramon_heavy=True)
            if fac > 0.0:
                val = round(_rank_val((0.20, 0.30, 0.40, 0.50), rk_kr) * fac, 6)
                weapon_effects_spec.append({
                    "upgradeType": "WEAPON_CRIT_CHANCE",
                    "operation": "STACKING_MULTIPLY",
                    "value": val,
                    "validTypes": [MELEE_WEAPON_TYPE],
                    "source": "focus:naramon_killers_rush",
                    "labelZh": "杀手猛突近战暴率",
                })
                summary_pills.append(f"杀手猛突 +{round(val * 100):g}%近战暴率")

        rk_stun = _node_rank("naramon_sling_stun")
        if rk_stun is not None:
            fac = _cond_factor("naramon_sling_stun", cycle_factor=1.0, cycle_period_sec=30.0, is_naramon_heavy=True)
            if fac > 0.0:
                enemy_debuffs["finisherVulnerability"] = round(_rank_val((0.15, 0.20, 0.25, 0.30), rk_stun) * fac, 6)

    elif active_school == "unairu":
        rk = _node_rank("unairu_stone_skin")
        if rk is not None:
            arm = _rank_val((50.0, 100.0, 150.0, 200.0), rk)
            warframe_mods["flatArmorAdd"] += arm
            summary_pills.append(f"石化外肤 +{int(arm)}护甲")

        rk_poise = _node_rank("unairu_poise")
        if rk_poise is not None:
            dur = _rank_val((10.0, 20.0, 30.0, 40.0), rk_poise)
            if _cond_factor("unairu_poise", cycle_factor=min(1.0, dur / 40.0), cycle_period_sec=40.0) > 0.0:
                warframe_mods["knockdownImmune"] = True
                summary_pills.append("不动如山(免击倒)")

        rk_cs = _node_rank("unairu_caustic_strike")
        if rk_cs is not None:
            fac = _cond_factor("unairu_caustic_strike", cycle_factor=1.0, cycle_period_sec=25.0)
            if fac > 0.0:
                strip = round(_rank_val((0.40, 0.60, 0.80, 1.00), rk_cs) * fac, 6)
                enemy_debuffs["armorStripFraction"] = max(enemy_debuffs["armorStripFraction"], strip)
                summary_pills.append(f"侵蚀打击 -{round(strip * 100):g}%护甲")

        rk_mf = _node_rank("unairu_magnetic_flare")
        if rk_mf is not None:
            dur = _rank_val((12.0, 18.0, 24.0, 30.0), rk_mf)
            fac = _cond_factor("unairu_magnetic_flare", cycle_factor=min(1.0, dur / 30.0), cycle_period_sec=30.0)
            if fac > 0.0:
                enemy_debuffs["shieldStripFraction"] = max(enemy_debuffs["shieldStripFraction"], round(1.0 * fac, 6))
                summary_pills.append(f"磁耀力场 -{round(100 * fac):g}%护盾")

    elif active_school == "zenurik":
        rk_ep = _node_rank("zenurik_energy_pulse")
        if rk_ep is not None:
            frac = _rank_val((0.20, 0.30, 0.40, 0.50), rk_ep)
            energy_econ["energyPulseBonusFraction"] = frac
            summary_pills.append(f"激能脉冲 +{round(frac * 100):g}%蓝球续航")

        rk_im = _node_rank("zenurik_inner_might")
        if rk_im is not None:
            cd = _rank_val((90.0, 80.0, 70.0, 60.0), rk_im)
            energy_econ["innerMightCooldownSec"] = cd
            summary_pills.append(f"内在之力 {int(cd)}s免蓝施放")

        rk_ws = _node_rank("zenurik_wellspring")
        if rk_ws is not None:
            dur = _rank_val((20.0, 22.0, 25.0, 30.0), rk_ws)
            fac = _cond_factor("zenurik_wellspring", cycle_factor=min(1.0, dur / 30.0), cycle_period_sec=30.0)
            if fac > 0.0:
                eps = round(_rank_val((3.0, 4.0, 4.0, 5.0), rk_ws) * fac, 6)
                energy_econ["wellspringEnergyPerSec"] += eps
                summary_pills.append(f"能量源泉 +{eps:g}能量/s")
                rk_hws = _node_rank("zenurik_hardened_wellspring")
                if rk_hws is not None:
                    fac_h = _cond_factor("zenurik_hardened_wellspring", cycle_factor=min(1.0, (dur + 8.0) / 30.0), cycle_period_sec=30.0)
                    if fac_h > 0.0:
                        s_add = round(_rank_val((0.12, 0.15, 0.18, 0.20), rk_hws) * fac_h, 6)
                        warframe_mods["abilityStrengthAdd"] += s_add
                        summary_pills.append(f"淬炼泉源 +{round(s_add * 100):g}%强度")

        rk_td = _node_rank("zenurik_temporal_drag")
        if rk_td is not None:
            dur = _rank_val((4.0, 6.0, 8.0, 10.0), rk_td)
            fac = _cond_factor("zenurik_temporal_drag", cycle_factor=min(1.0, dur / 12.0), cycle_period_sec=12.0)
            if fac > 0.0:
                enemy_debuffs["slowFraction"] = round(_rank_val((0.50, 0.60, 0.70, 0.80), rk_td) * fac, 6)
                rk_ts = _node_rank("zenurik_temporal_shot")
                if rk_ts is not None:
                    fac_ts = _cond_factor("zenurik_temporal_shot", cycle_factor=min(1.0, dur / 12.0), cycle_period_sec=12.0)
                    if fac_ts > 0.0:
                        hs_val = round(_rank_val((0.40, 0.60, 0.80, 1.00), rk_ts) * fac_ts, 6)
                        weapon_effects_spec.append({
                            "upgradeType": "WEAPON_HEADSHOT_MULTIPLIER",
                            "operation": "STACKING_MULTIPLY",
                            "value": hs_val,
                            "source": "focus:zenurik_temporal_shot",
                            "labelZh": "时准射击精准爆头倍率",
                        })
                        summary_pills.append(f"时准射击 +{round(hs_val * 100):g}%爆头倍率")

    elif active_school == "vazarin":
        rk_mu = _node_rank("vazarin_mending_unity")
        if rk_mu is not None:
            rad = _rank_val((10.0, 15.0, 20.0, 25.0), rk_mu)
            warframe_mods["affinityRadiusBonusM"] += rad
            summary_pills.append(f"愈合团结 +{int(rad)}m经验半径")

        rk_sr = _node_rank("vazarin_squad_regen")
        if rk_sr is not None:
            dur = _rank_val((30.0, 40.0, 50.0, 60.0), rk_sr)
            fac = _cond_factor("vazarin_squad_regen", cycle_factor=min(1.0, dur / 60.0), cycle_period_sec=60.0)
            if fac > 0.0:
                hp_s = round(_rank_val((20.0, 30.0, 40.0, 50.0), rk_sr) * fac, 6)
                warframe_mods["healthRegenPerSec"] += hp_s
                summary_pills.append(f"小队再生 +{hp_s:g}生命/s")

        rk_gb = _node_rank("vazarin_guardian_break")
        if rk_gb is not None and _node_rank("vazarin_guardian_shell") is not None:
            dur = _rank_val((6.0, 8.0, 10.0, 12.0), rk_gb)
            fac = _cond_factor("vazarin_guardian_break", cycle_factor=min(1.0, dur / 20.0), cycle_period_sec=20.0)
            if fac > 0.0:
                warframe_mods["shieldRechargeRateAdd"] += round(_rank_val((0.90, 1.10, 1.30, 1.50), rk_gb) * fac, 6)
                warframe_mods["shieldRechargeDelayAdd"] += round(_rank_val((-0.20, -0.40, -0.60, -0.80), rk_gb) * fac, 6)
                summary_pills.append("庇护碎裂(回盾加速)")

    # ── 2. Tauron Ultimate Branch Nodes (gated by enable_tauron_strike) ───────
    if enable_tauron_strike and trigger_mode in {"cycle", "peak"}:
        tauron_fac = 1.0 if trigger_mode == "peak" else 0.50
        if active_school == "madurai":
            rk_op = _node_rank("madurai_ult_overwhelming_power")
            if rk_op is not None:
                s_add = round(_rank_val((0.20, 0.30, 0.40, 0.50), rk_op) * tauron_fac, 6)
                warframe_mods["abilityStrengthAdd"] += s_add
                summary_pills.append(f"Tauron压倒性力量 +{round(s_add * 100):g}%强度")
        elif active_school == "zenurik":
            rk_lorak = _node_rank("zenurik_ult_lorak_tauron_strike")
            if rk_lorak is not None:
                energy_econ["tauronKillEnergyOrbChance"] = round(_rank_val((0.25, 0.50, 0.75, 1.00), rk_lorak) * tauron_fac, 6)
            rk_sp = _node_rank("zenurik_ult_spectral_pages")
            if rk_sp is not None:
                pages = _rank_val((1.0, 2.0, 3.0, 4.0), rk_sp)
                rk_be = _node_rank("zenurik_ult_boundless_energy")
                be_mult = 1.0 + (_rank_val((0.25, 0.30, 0.35, 0.40), rk_be) if rk_be is not None else 0.0)
                stat_add = round(0.10 * pages * be_mult * tauron_fac, 6)
                e_add = round(100.0 * pages * tauron_fac, 3)
                warframe_mods["abilityStrengthAdd"] += stat_add
                warframe_mods["abilityDurationAdd"] += stat_add
                warframe_mods["castingSpeedAdd"] += stat_add
                warframe_mods["flatEnergyBonus"] += e_add
                summary_pills.append(f"Tauron幻影书页 +{round(stat_add * 100):g}%强度/持续 +{int(e_add)}能量")
        elif active_school == "unairu":
            rk_tb = _node_rank("unairu_ult_tempered_benison")
            if rk_tb is not None:
                arm_add = round(_rank_val((900.0, 1350.0, 1800.0, 2250.0), rk_tb) * tauron_fac, 3)
                warframe_mods["flatArmorAdd"] += arm_add
                summary_pills.append(f"Tauron温和祝福 +{int(arm_add)}护甲")
        elif active_school == "vazarin":
            rk_nidri = _node_rank("vazarin_ult_nidri_tauron_strike")
            if rk_nidri is not None:
                enemy_debuffs["vortexSharedDamageFraction"] = round(_rank_val((0.20, 0.30, 0.40, 0.50), rk_nidri) * tauron_fac, 6)
            rk_rw = _node_rank("vazarin_ult_rift_waters")
            if rk_rw is not None:
                enemy_debuffs["overguardStripPerSec"] = round(_rank_val((0.10, 0.15, 0.20, 0.25), rk_rw) * tauron_fac, 6)
            rk_er = _node_rank("vazarin_ult_eroding_rapids")
            if rk_er is not None:
                sc_v = round(_rank_val((0.25, 0.50, 0.75, 1.00), rk_er) * tauron_fac, 6)
                enemy_debuffs["statusChanceVulnerability"] = sc_v
                weapon_effects_spec.append({
                    "upgradeType": "WEAPON_PROC_CHANCE",
                    "operation": "STACKING_MULTIPLY",
                    "value": sc_v,
                    "source": "focus:vazarin_ult_eroding_rapids",
                    "labelZh": "侵蚀急流异常易伤",
                })
                summary_pills.append(f"Tauron侵蚀急流 +{round(sc_v * 100):g}%触发易伤")
            rk_dc = _node_rank("vazarin_ult_deathless_currents")
            if rk_dc is not None:
                warframe_mods["healthRegenPerSec"] += round(_rank_val((100.0, 150.0, 200.0, 250.0), rk_dc) * tauron_fac, 6)
        elif active_school == "naramon":
            rk_sb = _node_rank("naramon_ult_spectral_blades")
            if rk_sb is not None:
                cnt = int(_rank_val((1, 2, 3, 4), rk_sb))
                rk_fs = _node_rank("naramon_ult_flowing_strikes")
                rng = _rank_val((14.0, 18.0, 22.0, 26.0), rk_fs) if rk_fs is not None else 10.0
                rk_hb = _node_rank("naramon_ult_hungering_blades")
                dbl = _rank_val((0.25, 0.50, 0.75, 1.00), rk_hb) if rk_hb is not None else 0.0
                melee_combo["spectralBladesCount"] = cnt
                melee_combo["spectralBladesRangeM"] = rng
                melee_combo["spectralBladesDoubleChance"] = dbl
                summary_pills.append(f"Tauron幻影之刃 ×{cnt}({rng:g}m)")

    pause_per_cycle_sec = 0.65 if (trigger_mode == "cycle" and transference_cycles_per_min > 0.0) else 0.0
    pause_fraction = min(0.15, (transference_cycles_per_min * pause_per_cycle_sec) / 60.0)
    firing_duty_mult = round(max(0.85, 1.0 - pause_fraction), 6)

    for k in list(warframe_mods):
        if isinstance(warframe_mods[k], float):
            warframe_mods[k] = round(warframe_mods[k], 6)
    for k in list(energy_econ):
        if isinstance(energy_econ[k], float):
            energy_econ[k] = round(energy_econ[k], 6)

    return {
        "triggerMode": trigger_mode,
        "enableNaramonPreconditions": enable_naramon_preconditions,
        "enableTauronStrike": enable_tauron_strike,
        "transferencePausePerCycleSec": pause_per_cycle_sec,
        "firingDutyMultiplier": firing_duty_mult,
        "weaponEffectsSpec": weapon_effects_spec,
        "warframeModifiers": warframe_mods,
        "energyEconomy": energy_econ,
        "meleeCombo": melee_combo,
        "enemyDebuffs": enemy_debuffs,
        "summaryPills": summary_pills,
    }


def evaluate_focus(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Evaluate Operator Focus configuration and return UI state + active combatBridge."""
    cat = catalog()
    schools_by_id, nodes_by_id, nodes_by_path = _index_catalog(cat)
    req = payload if isinstance(payload, Mapping) else {}
    nested_cfg = req.get("config") if isinstance(req.get("config"), Mapping) else req

    active_school = str(nested_cfg.get("activeSchool") or req.get("activeSchool") or "madurai").strip().casefold()
    if active_school not in schools_by_id:
        raise SimulationError(f"unknown focus school: {active_school}")

    raw_mode = str(req.get("triggerMode") or nested_cfg.get("triggerMode") or "passive").strip().casefold()
    trigger_mode = raw_mode if raw_mode in TRIGGER_MODES else "passive"
    enable_naramon = bool(req.get("enableNaramonPreconditions", nested_cfg.get("enableNaramonPreconditions", False)))
    enable_tauron = bool(req.get("enableTauronStrike", nested_cfg.get("enableTauronStrike", False)))
    default_maxed = bool(req.get("defaultMaxed", nested_cfg.get("defaultMaxed", False)))
    default_tauron_maxed = bool(req.get("defaultTauronMaxed", nested_cfg.get("defaultTauronMaxed", enable_tauron)))
    vs_energy_pct = float(req.get("voidStrikeEnergyPct", nested_cfg.get("voidStrikeEnergyPct", 1.0)) or 1.0)

    raw_schools = nested_cfg.get("schools") if isinstance(nested_cfg.get("schools"), Mapping) else {}
    raw_unbound = set()
    ub_src = nested_cfg.get("unboundWayBounds") if "unboundWayBounds" in nested_cfg else req.get("unboundWayBounds")
    if isinstance(ub_src, (list, tuple, set)):
        for item in ub_src:
            s = str(item or "").strip()
            if s:
                raw_unbound.add(s)

    active_triggers_raw = (
        nested_cfg.get("activeTriggers")
        if isinstance(nested_cfg.get("activeTriggers"), Mapping)
        else (req.get("activeTriggers") if isinstance(req.get("activeTriggers"), Mapping) else {})
    )

    evaluated_schools: dict[str, Any] = {}
    total_focus_all = 0
    total_shards_all = 0
    cross_waybounds_available: list[dict[str, Any]] = []

    for sid in SCHOOL_IDS:
        school = schools_by_id[sid]
        scfg = raw_schools.get(sid) if isinstance(raw_schools, Mapping) and isinstance(raw_schools.get(sid), Mapping) else None
        if scfg is None and sid == active_school:
            scfg = {"schoolUnlocked": True}
        node_states = _resolve_node_state(
            school,
            scfg,
            default_maxed=default_maxed,
            default_tauron_maxed=(default_tauron_maxed and sid == active_school),
        )

        school_focus = 0
        school_shards = 0
        unlocked_count = 0
        maxed_count = 0
        tauron_unlocked_count = 0
        all_school_nodes = [*(school.get("nodes") or ()), *(school.get("ultimateBranchNodes") or ())]
        for node in all_school_nodes:
            nid = str(node.get("id") or "")
            npath = str(node.get("path") or "")
            st = node_states[nid]
            if (nid in raw_unbound or npath in raw_unbound) and st["isWayBound"] and st["unlocked"] and st["rank"] >= st["maxRank"]:
                st["unbound"] = True
            spent, sh = _node_focus_cost(node, st)
            st["focusSpent"] = spent
            st["shardsSpent"] = sh
            school_focus += spent
            school_shards += sh
            if st["unlocked"]:
                if st.get("isTauronUltimate"):
                    tauron_unlocked_count += 1
                else:
                    unlocked_count += 1
                    if st["rank"] >= st["maxRank"]:
                        maxed_count += 1
            if st["isWayBound"]:
                descs = node.get("descriptionsZh") or [""]
                desc_zh = descs[min(st["rank"], len(descs) - 1)]
                cross_waybounds_available.append({
                    "id": nid,
                    "path": npath,
                    "schoolId": sid,
                    "schoolName": school.get("nameEn"),
                    "nameZh": node.get("nameZh"),
                    "nameEn": node.get("nameEn"),
                    "iconAsset": node.get("iconAsset"),
                    "unlockedInHome": st["unlocked"],
                    "rank": st["rank"],
                    "maxRank": st["maxRank"],
                    "unbound": st["unbound"],
                    "active": (sid == active_school and st["enabled"]) or (sid != active_school and st["unbound"]),
                    "descriptionZh": desc_zh,
                })

        total_focus_all += school_focus
        total_shards_all += school_shards
        evaluated_schools[sid] = {
            "id": sid,
            "nameEn": school.get("nameEn"),
            "nameZh": school.get("nameZh"),
            "unlockedCount": unlocked_count,
            "maxedCount": maxed_count,
            "tauronUnlockedCount": tauron_unlocked_count,
            "focusSpent": school_focus,
            "shardsSpent": school_shards,
            "nodes": node_states,
        }

    act_school_rec = schools_by_id[active_school]
    act_states = evaluated_schools[active_school]["nodes"]

    passive_buffs: list[dict[str, Any]] = []
    conditional_buffs: list[dict[str, Any]] = []
    weapon_relevant: list[dict[str, Any]] = []
    warframe_relevant: list[dict[str, Any]] = []
    operator_only_notes: list[dict[str, Any]] = []

    active_node_pool = [
        *(act_school_rec.get("nodes") or ()),
        *((act_school_rec.get("ultimateBranchNodes") or ()) if enable_tauron else ()),
    ]
    for node in active_node_pool:
        nid = str(node.get("id") or "")
        st = act_states.get(nid)
        if not st or not st["enabled"]:
            continue
        rank = int(st["rank"])
        descs_zh = node.get("descriptionsZh") or []
        desc_zh = descs_zh[min(rank, len(descs_zh) - 1)] if descs_zh else ""
        rel = node.get("combatRelevance") if isinstance(node.get("combatRelevance"), Mapping) else {}
        is_cond = bool(rel.get("isConditional", node.get("activationType") != "passive"))
        if nid in OPERATOR_AMP_ONLY_NODE_IDS:
            default_active = False
        elif not is_cond:
            default_active = True
        elif trigger_mode == "passive":
            default_active = False
        elif nid in NARAMON_HEAVY_PRECONDITION_IDS:
            default_active = enable_naramon
        else:
            default_active = True
        trigger_on = bool(active_triggers_raw.get(nid, default_active)) and nid not in OPERATOR_AMP_ONLY_NODE_IDS

        mods_out = []
        for mod in rel.get("modifiers") or ():
            if not isinstance(mod, Mapping):
                continue
            vals = mod.get("valuesByRank") or []
            cur_val = vals[min(rank, len(vals) - 1)] if vals else None
            stat_name = str(mod.get("stat") or "")
            op_name = str(mod.get("operationType") or "")
            mods_out.append({
                "stat": stat_name,
                "engineUpgradeType": mod.get("engineUpgradeType"),
                "operationType": op_name,
                "stackingBucket": mod.get("stackingBucket"),
                "appliesTo": mod.get("appliesTo"),
                "value": cur_val,
                "formattedValue": _format_modifier_value(stat_name, cur_val, op_name),
            })

        entry = {
            "id": nid,
            "path": node.get("path"),
            "schoolId": active_school,
            "nameZh": node.get("nameZh"),
            "nameEn": node.get("nameEn"),
            "iconAsset": node.get("iconAsset"),
            "rank": rank,
            "maxRank": st["maxRank"],
            "activationType": node.get("activationType"),
            "triggerDetail": node.get("triggerDetail"),
            "isWayBound": st["isWayBound"],
            "isTauronUltimate": bool(st.get("isTauronUltimate")),
            "isConditional": is_cond,
            "previewEnabled": trigger_on,
            "descriptionZh": desc_zh,
            "notesZh": rel.get("notesZh") or "",
            "category": rel.get("category") or "operator",
            "targets": list(rel.get("targets") or ()),
            "modifiers": mods_out,
        }

        if is_cond:
            conditional_buffs.append(entry)
        else:
            passive_buffs.append(entry)

        targets = set(rel.get("targets") or ())
        if nid in OPERATOR_AMP_ONLY_NODE_IDS:
            operator_only_notes.append(entry)
        elif targets & {"warframe_weapons", "melee_weapons", "all_weapons", "primary_weapons", "secondary_weapons"}:
            weapon_relevant.append(entry)
        elif targets & {"warframe", "warframe_abilities", "warframe_energy", "enemy_armor", "enemy_shields", "enemy_crowd"} or str(rel.get("category") or "") in {"warframe_buff", "energy_economy", "enemy_debuff"}:
            warframe_relevant.append(entry)
        else:
            operator_only_notes.append(entry)

    for wb in cross_waybounds_available:
        if wb["schoolId"] != active_school and wb["unbound"]:
            wb_node = nodes_by_id.get(wb["id"]) or nodes_by_path.get(wb["path"]) or {}
            passive_buffs.append({
                "id": wb["id"],
                "path": wb["path"],
                "schoolId": wb["schoolId"],
                "nameZh": wb["nameZh"],
                "nameEn": wb["nameEn"],
                "iconAsset": wb["iconAsset"],
                "rank": wb["rank"],
                "maxRank": wb["maxRank"],
                "activationType": "way_bound_unbound",
                "triggerDetail": "cross_school_way_bound",
                "isWayBound": True,
                "isTauronUltimate": False,
                "isConditional": False,
                "previewEnabled": True,
                "descriptionZh": wb["descriptionZh"],
                "notesZh": (wb_node.get("combatRelevance") or {}).get("notesZh") or "跨专精解绑被动（作用于指挥官与增幅器本体）",
                "category": "way_bound",
                "targets": ["operator", "operator_amp"],
                "modifiers": [],
            })

    combat_bridge = _compile_combat_bridge(
        active_school=active_school,
        act_states=act_states,
        trigger_mode=trigger_mode,
        enable_naramon_preconditions=enable_naramon,
        enable_tauron_strike=enable_tauron,
        active_triggers_raw=active_triggers_raw,
        void_strike_energy_pct=vs_energy_pct,
    )

    return {
        "integrationStatus": "active_combat_bridge",
        "integrationNoteZh": "指挥官专精协同桥接已就绪：开启专精参与计算后，按所选触发口径同步计入武器配装、战甲面板、技能循环与 3D 靶场结算。",
        "activeSchool": active_school,
        "triggerMode": trigger_mode,
        "enableNaramonPreconditions": enable_naramon,
        "enableTauronStrike": enable_tauron,
        "activeSchoolMeta": {
            "id": active_school,
            "nameEn": act_school_rec.get("nameEn"),
            "nameZh": act_school_rec.get("nameZh"),
            "descriptionZh": act_school_rec.get("descriptionZh"),
            "theme": act_school_rec.get("theme"),
            "iconAssets": act_school_rec.get("iconAssets"),
        },
        "investment": {
            "activeSchoolFocusPoints": evaluated_schools[active_school]["focusSpent"],
            "totalFocusPoints": total_focus_all,
            "brilliantEidolonShards": total_shards_all,
            "unboundWayBoundCount": sum(1 for w in cross_waybounds_available if w["unbound"]),
        },
        "schools": evaluated_schools,
        "wayBounds": cross_waybounds_available,
        "buffPreview": {
            "passiveBuffs": passive_buffs,
            "conditionalBuffs": conditional_buffs,
            "weaponRelevant": weapon_relevant,
            "warframeAndEnergyRelevant": warframe_relevant,
            "operatorOnly": operator_only_notes,
        },
        "combatBridge": combat_bridge,
    }


__all__ = [
    "SCHOOL_IDS",
    "TRIGGER_MODES",
    "OPERATOR_AMP_ONLY_NODE_IDS",
    "NARAMON_HEAVY_PRECONDITION_IDS",
    "catalog",
    "get_focus_catalog",
    "evaluate_focus",
]
