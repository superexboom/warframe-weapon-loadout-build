"""Riven scoring and automatic weapon builds over one frozen export.

Riven values on the wire are the max-rank numbers printed on the card.  This
module converts them into :class:`ModEffect` objects and sends ordinary mods,
the actual Riven, and the recommended Riven through the same damage reducer.
The search is deliberately a bounded beam search: exports do not contain every
mutual-exclusion rule needed for an exact combinatorial solver.
"""

from __future__ import annotations

import itertools
import hashlib
import json
import math
import os
import pickle
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence
from .search_session import SESSION, session_request, memoized_search, heartbeat, phase_deadline, expired

# Scored no-Riven baselines per exact inputs (see analyze_riven_request._reconstruct).
_BASELINE_EVALUATIONS: OrderedDict = OrderedDict()

from .damage import (
    BASE_ELEMENTS,
    MELEE_SLOTS,
    ModEffect,
    ModEffectList,
    Scenario,
    SUPPORTED_WEAPON_UPGRADE_TYPES,
    apply_mods,
    arcane_effects,
    effective_hit_multiplier,
    enemy_defenses,
    expected_victim_status_count,
    _qualifier_rejection,
    sustained_status_damage,
    windowed_status_damage,
    mod_effects,
)
from .projectile_events import evaluate_projectile_events
from .simulator import (
    SimulationError,
    _buff_set_multiplier,
    _mod_matches_weapon,
    _set_key,
    _set_shell_effects,
    _set_shells,
    _steady_state_scenario,
    load_exports,
    record_identity,
    resolve_record,
)


RIVEN_TEMPLATE_BUILD = "2026.08.13.13.24"


# 偏好复合元素映射（与 app.py ELEMENT_TARGETS 同口径）：elementTarget 键
# → 最终配装必须包含的伤害类型。分析页的「偏好元素」选择器使用。
_ELEMENT_TARGET_TYPES = {
    "heat": "DT_FIRE",
    "cold": "DT_FREEZE",
    "electricity": "DT_ELECTRICITY",
    "toxin": "DT_POISON",
    "blast": "DT_EXPLOSION",
    "radiation": "DT_RADIATION",
    "gas": "DT_GAS",
    "magnetic": "DT_MAGNETIC",
    "viral": "DT_VIRAL",
    "corrosive": "DT_CORROSIVE",
}


# Values are max-rank, disposition-1 card values recovered from the current
# 2026.08.13.13.24 Randomized/*RandomModRare templates (raw Value * 90).
# Flat stats (metres, seconds and initial combo) remain flat rather than percent.
RIVEN_BASE_VALUES: dict[str, dict[str, float]] = {
    "rifle": {
        "0": 149.994, "1": 119.997, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.997, "9": 119.997, "A": 119.997,
        "C": 45.0, "D": 164.9997, "F": 49.995, "G": 45.0,
        "H": 59.994, "I": 45.0, "L": 49.995, "M": 49.95,
        "P": 2.7, "R": 60.03, "S": 90.0, "V": 90.0, "Z": 90.0,
        # 融合词条：见 FUSION_SERVER_BASES（服务器实际取值，_template_bases 合并）。
    },
    "shotgun": {
        "0": 90.0, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.997, "9": 119.997, "A": 119.997,
        "C": 45.0, "D": 164.7, "F": 49.995, "G": 45.0,
        "I": 45.0, "L": 49.995, "M": 90.0, "P": 2.7,
        "R": 90.0, "S": 119.7, "V": 90.0, "Z": 90.0,
        # 融合词条：见 FUSION_SERVER_BASES（服务器实际取值，_template_bases 合并）。
    },
    "pistol": {
        "0": 149.994, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.997, "9": 119.997, "A": 119.997,
        "C": 45.0, "D": 219.6, "F": 49.995, "G": 45.0,
        "H": 80.1, "I": 45.0, "L": 49.995, "M": 90.0,
        "P": 2.7, "R": 74.7, "S": 119.7, "V": 90.0, "Z": 90.0,
        # 融合词条：见 FUSION_SERVER_BASES（服务器实际取值，_template_bases 合并）。
    },
    "archgun": {
        "0": 99.9, "1": 80.1, "2": 60.3, "3": 99.99,
        "4": 119.7, "5": 119.7, "6": 119.7, "7": 119.7,
        "8": 90.0, "9": 90.0, "A": 90.0,
        "C": 45.0, "D": 99.9, "F": 99.9, "G": 45.0,
        "H": 59.994, "L": 60.3, "M": 99.9, "P": 2.7,
        "R": 60.03, "S": 60.3, "Z": 90.0,
        # 融合词条：见 FUSION_SERVER_BASES（服务器实际取值，_template_bases 合并）。
    },
    "melee": {
        "0": 180.0, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.7, "9": 119.7, "A": 119.7,
        "B": 24.5016, "C": 45.0, "E": 120.006, "G": 45.0,
        "I": 45.0, "J": 54.9, "K": 164.7, "N": 8.1,
        "O": 58.77, "Q": 104.85, "T": 1.9422, "U": 73.44,
        "X": 119.7,
        # 近战融合词条（模板 base90：重击伤害/蓄力速度/震地 1.197，格挡角度 8.1；
        # 2026.10.08 起近战也有状态伤害、复合元素 90 与新派系 45）。
        "HC": 119.7, "PA": 8.1, "SL": 119.7, "HD": 119.7, "SD": 90.0,
        "GA": 90.0, "CO": 90.0, "VI": 90.0, "RA": 90.0, "BL": 90.0, "MA": 90.0,
        "FO": 45.0, "FT": 45.0, "FS": 45.0,
    },
}


# code: (label, upgrade type, operation, damage type, symbol filter, unit,
#        effect direction for a beneficial line, can buff, can curse)
RIVEN_RULES: dict[str, tuple[str, str, str, str | None, str | None, str, float, bool, bool]] = {
    "0": ("暴击几率", "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "1": ("暴击伤害", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "2": ("触发几率", "WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "3": ("触发时间", "WEAPON_PROC_TIME", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "4": ("火焰伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FIRE", None, "percent", 1, True, False),
    "5": ("冰冻伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FREEZE", None, "percent", 1, True, False),
    "6": ("毒素伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_POISON", None, "percent", 1, True, False),
    "7": ("电击伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_ELECTRICITY", None, "percent", 1, True, False),
    "8": ("冲击伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_IMPACT", None, "percent", 1, True, True),
    "9": ("穿刺伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_PUNCTURE", None, "percent", 1, True, True),
    "A": ("切割伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_SLASH", None, "percent", 1, True, True),
    "B": ("初始连击", "WEAPON_MELEE_COMBO_INITIAL_BONUS", "ADD", None, None, "flat", 1, True, False),
    "C": ("对Corpus伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Corpus", "percent", 1, True, True),
    "D": ("基础伤害", "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    # The current reducer cannot express the CC_SLIDING symbol condition, so E
    # is accepted and diagnosed but never used as unconditional crit chance.
    "E": ("滑行攻击时暴击率", "WEAPON_CRIT_CHANCE_SLIDE", "STACKING_MULTIPLY", None, "CC_SLIDING", "percent", 1, True, True),
    "F": ("装填速度", "WEAPON_RELOAD_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "G": ("对Grineer伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Grineer", "percent", 1, True, True),
    "H": ("变焦", "WEAPON_ZOOM", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "I": ("对Infested伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1, True, True),
    "J": ("攻击速度", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "K": ("近战伤害", "WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "L": ("弹匣容量", "WEAPON_CLIP_MAX", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "M": ("弹药最大值", "WEAPON_AMMO_MAX", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "N": ("连击持续时间", "WEAPON_MELEE_COMBO_DURATION_BONUS", "ADD", None, None, "flat", 1, True, True),
    "O": ("额外连击数几率", "WEAPON_MELEE_COMBO_GAIN_EXTRA_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "P": ("穿透", "WEAPON_PUNCTURE_DEPTH", "ADD", None, None, "flat", 1, True, False),
    "Q": ("额外连击数", "WEAPON_MELEE_COMBO_GAIN_MISS_CHANCE", "ADD", None, None, "percent", -1, False, True),
    "R": ("射速", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "S": ("多重射击", "WEAPON_FIRE_ITERATIONS", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "T": ("攻击范围", "WEAPON_RANGE", "ADD", None, None, "flat", 1, True, True),
    "U": ("重击效率", "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY", "ADD", None, None, "percent", 1, True, True),
    "V": ("投射物速度", "WEAPON_PROJECTILE_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    "X": ("处决伤害", "WEAPON_MELEE_FINISHER_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1, True, True),
    # A beneficial recoil line is printed as a negative percentage.
    "Z": ("武器后坐力", "WEAPON_RECOIL", "STACKING_MULTIPLY", None, None, "percent", -1, True, True),
    # ── 词条融合新词条（2026.09.22，Advanced Traits）─────────────────
    # 数值来自 new_riven_stats.json（base90 = 0.9 倾向基准显示值）。
    # 弱点家族乘区已引擎裁决：弱点伤害是独立乘区（弱命中 ×(1+bonus)）、
    # 弱点暴击与基础暴击同链加算——见 weakpoint-multiplier-re.json。
    # 融合词条游戏规则（用户确认 2026-09-24）：仅正面、每卡限 1 条——
    # can_negative 一律 False（提取数据的 CanBeCurse 标志是融合原料的
    # 旧口径，不适用于融合结果词条）。
    "W": ("弱点伤害", "WEAPON_DAMAGE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "Y": ("弱点暴击几率", "WEAPON_CRIT_CHANCE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    # 双字符码避免与既有单字母冲突（wire 上 code.upper() 去重）。
    "GA": ("毒气伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_GAS", None, "percent", 1, True, False),
    "CO": ("腐蚀伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_CORROSIVE", None, "percent", 1, True, False),
    "VI": ("病毒伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_VIRAL", None, "percent", 1, True, False),
    "RA": ("辐射伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_RADIATION", None, "percent", 1, True, False),
    "BL": ("爆炸伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_EXPLOSION", None, "percent", 1, True, False),
    "MA": ("磁力伤害", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_MAGNETIC", None, "percent", 1, True, False),
    "SD": ("状态伤害", "WEAPON_PROC_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "AE": ("弹药效率", "WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", None, None, "percent", -1, True, False),
    "HR": ("收枪自动装填", "WEAPON_AUTO_RELOAD_RATE", "ADD", None, None, "percent", 1, True, False),
    "FO": ("对Orokin伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1, True, False),
    "FT": ("对Techrot伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Techrot", "percent", 1, True, False),
    "FS": ("对Scaldra伤害", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Scaldra", "percent", 1, True, False),
    # 近战专属融合词条（base90: 蓄力速度 1.197、格挡角度 8.1、震地伤害 1.197）。
    "HD": ("重击伤害", "WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "HC": ("重击蓄力速度", "WEAPON_MELEE_HEAVY_CHARGE_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
    "PA": ("格挡角度", "WEAPON_PARRY_ANGLE", "ADD", None, None, "flat", 1, True, False),
    "SL": ("震地伤害", "WEAPON_MELEE_SLAM_DAMAGE_BONUS", "STACKING_MULTIPLY", None, None, "percent", 1, True, False),
}

# ── 融合词条码集合（仅正面、每卡限 1 条——游戏规则，2026-09-24 确认）──
# 推荐器的组合枚举（_recommend_positive 头部组合、recommend_optimal_riven
# 的 beam 组合）用它过滤：任何含 2+ 融合词条的组合非法，直接跳过。
from .melee_sequence import build_schedule, route_note
from .riven_fusion import FUSION_CODES as _FUSION_LINE_CODES, available_codes as _available_fusion_codes



def _combo_allows_fusion(lines: Sequence[Any]) -> bool:
    """组合是否满足「融合词条每卡限 1 条」（负融合词条已被候选层排除）。"""
    return sum(
        1
        for line in lines
        if str(getattr(line, "code", "")) in _FUSION_LINE_CODES
    ) <= 1


def _template_bases(payload: Mapping[str, Any], weapon_type: str) -> dict[str, float]:
    """Recover display-scale base values from the current RandomModRare export."""
    templates = payload.get("templates") if isinstance(payload, Mapping) else None
    if not isinstance(templates, list):
        return {}
    candidates = [row for row in templates if isinstance(row, Mapping) and row.get("weaponType") == weapon_type]
    if weapon_type == "melee":
        candidates.sort(key=lambda row: str(row.get("id") or "") != "PlayerMeleeWeaponRandomModRare")
    elif weapon_type == "pistol":
        candidates.sort(key=lambda row: str(row.get("id") or "") != "LotusPistolRandomModRare")
    if not candidates:
        return {}
    result: dict[str, float] = {}
    for stat in candidates[0].get("stats") or ():
        if not isinstance(stat, Mapping):
            continue
        upgrades = stat.get("upgrades") or ()
        if stat.get('tag') == 'WeaponCritChanceMod' and len(upgrades) == 2:
            # Melee repeats the same scalar for its heavy-attack-only bonus.
            # Read the unqualified normal value; the wire rule adds the heavy
            # qualifier separately and must not lose melee crit candidates.
            upgrades = [u for u in upgrades if isinstance(u, Mapping) and not u.get('validModifiers')]
        if len(upgrades) != 1 or not isinstance(upgrades[0], Mapping):
            continue
        upgrade = upgrades[0]
        matches = []
        for code, rule in RIVEN_RULES.items():
            _label, upgrade_type, operation, damage_type, symbol_filter, unit, *_rest = rule
            if tuple(upgrade.get("validModifiers") or ()) != (("PM_HEAVY_MELEE",) if code == "HD" else ()):
                continue
            if upgrade_type != upgrade.get("upgradeType") or operation != upgrade.get("operation"):
                continue
            raw_damage = upgrade.get("damageType")
            raw_symbol = upgrade.get("symbolFilter") or None
            if damage_type and damage_type != raw_damage:
                continue
            if not damage_type and raw_damage not in (None, "", "DT_ANY"):
                continue
            if symbol_filter and symbol_filter != raw_symbol:
                continue
            if not symbol_filter and raw_symbol and not (code == 'HR' and raw_symbol == 'Holstered'):
                continue
            matches.append((code, unit))
        raw_value = upgrade.get("rawValue")
        if len(matches) != 1 or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        code, unit = matches[0]
        result[code] = abs(float(raw_value)) * (90.0 if unit == "flat" else 9000.0)
    # Rivens are rolled by the server. Until 2026.10.08 the client template
    # disagreed with observed rolls for some spliced traits (a Dual Toxocyst
    # Weakpoint roll of 310% needs base 225, the old pistol template said 90);
    # the 10.08 templates match. Server-observed bases still win.
    result.update({code: value for code, value in FUSION_SERVER_BASES.get(weapon_type, {}).items()
                   if code in result or code in RIVEN_BASE_VALUES.get(weapon_type, {})})
    return result


# Spliced (fusion) trait bases as rolled by the server, in display percent
# (wiki Riven Mods; the 2026.10.08 client templates agree). Same for every gun
# type; melee values come from the template and are not overridden.
_GUN_FUSION_BASES = {
    "W": 225.0, "Y": 247.5, "AE": 45.0, "HR": 90.0, "SD": 90.0,
    "GA": 90.0, "CO": 90.0, "VI": 90.0, "RA": 90.0, "BL": 90.0, "MA": 90.0,
    "FO": 45.0, "FT": 45.0, "FS": 45.0,
}
FUSION_SERVER_BASES: dict[str, dict[str, float]] = {
    "rifle": dict(_GUN_FUSION_BASES),
    "shotgun": dict(_GUN_FUSION_BASES),
    "pistol": dict(_GUN_FUSION_BASES),
    "archgun": {code: value for code, value in _GUN_FUSION_BASES.items() if code != "HR"},
}
for _type, _bases in FUSION_SERVER_BASES.items():
    RIVEN_BASE_VALUES[_type].update(_bases)

# Filled only with weapon-specific choices that have been verified against the
# current export.  Missing entries are selected from static branches by the
# requested objective, rather than inheriting a stale four-year-old table.
DEFAULT_INCARNON_CHOICES: dict[str, dict[str, str]] = {}


@dataclass(frozen=True)
class _RivenLine:
    code: str
    label: str
    value: float
    low: float
    high: float
    negative: bool
    unit: str
    effect: ModEffect | None


@dataclass(frozen=True)
class _Card:
    key: str
    record: Mapping[str, Any] | None
    rank: int
    effects: tuple[ModEffect, ...]
    skipped: tuple[str, ...]
    drain: int
    polarity: str | None
    riven_lines: tuple[_RivenLine, ...] = ()
    required: bool = False
    set_shell: Mapping[str, Any] | None = None
    # 灵化卡专属：条件 SubUpgrade 子词条的触发规格（事件化叠层语义）。
    # 结构与 app 层 trigger_sources 一致：
    # {id, label, kind, perEvent, maxStacks, duration, effects: [原始 effect 行]}。
    trigger_specs: tuple[Mapping[str, Any], ...] = ()
    event_arcanes: tuple[tuple[Mapping[str, Any], int, Mapping[str, Any]], ...] = ()
    incarnon_choices: tuple[tuple[str, str], ...] = ()


@dataclass
class _Evaluation:
    score: float
    cards: tuple[_Card, ...]
    stats: Any
    capacity: int
    riven_index: int | None
    scenario: Scenario


def _number(label: str, value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationError(f"{label} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise SimulationError(f"{label} must be a finite number")
    return value


_KITGUN_BASE_PREFIXES = ("/lotus/weapons/solarisunited/primary/lotusmodularprimary",
                         "/lotus/weapons/solarisunited/secondary/lotusmodularsecondary")


def _riven_type(requested: Any, weapon: Mapping[str, Any]) -> str:
    """Riven family for stat bases, templates and fusion traits.

    Every Kitgun, primary or secondary, takes the one Kitgun Riven
    (LotusModularPistolRandomModRare: pistol stats; a primary Kitgun only
    swaps in the chamber's alternate disposition). Mechanics keep
    ``_weapon_type``.
    """
    path = str(weapon.get("path") or "").casefold()
    if weapon.get("kitgunParts") or path.startswith(_KITGUN_BASE_PREFIXES):
        return "pistol"
    return _weapon_type(requested, weapon)


def _weapon_type(requested: Any, weapon: Mapping[str, Any]) -> str:
    value = str(requested or "").strip().casefold()
    slot = str(weapon.get("slot") or "").casefold()
    if value == "kitgun":
        return "pistol" if slot == "secondary" else "rifle"
    aliases = {
        "zaw": "melee", "secondary": "pistol",
        "primary": "rifle", "archwing": "archgun", "arch-gun": "archgun",
        "archmelee": "melee", "arch-melee": "melee", "spacemelee": "melee",
        "space-melee": "melee",
    }
    value = aliases.get(value, value)
    if value in RIVEN_BASE_VALUES:
        return value
    ancestry = " ".join(map(str, weapon.get("ancestry") or ())).casefold()
    if slot in {"melee", "arch_melee", "space_melee", "archmelee", "spacemelee"}:
        return "melee"
    if "shotgun" in ancestry:
        return "shotgun"
    if slot == "companion":
        if "/lotus/weapons/tenno/melee/playermeleeweapon" in ancestry:
            return "melee"
        if "/lotus/weapons/tenno/pistol/lotuspistol" in ancestry:
            return "pistol"
    if slot == "secondary":
        return "pistol"
    if "archwing" in ancestry or "archgun" in ancestry:
        return "archgun"
    return "rifle"


def _effect_from_code(
    code: str,
    value: float,
    *,
    negative: bool,
    source: str,
) -> ModEffect | None:
    rule = RIVEN_RULES.get(code)
    if rule is None:
        return None
    _, upgrade_type, operation, damage_type, symbol_filter, unit, direction, _, _ = rule
    normalized = value / 100.0 if unit == "percent" else value
    normalized *= direction * (-1.0 if negative else 1.0)
    return ModEffect(
        upgrade_type=upgrade_type,
        operation=operation,
        value=normalized,
        damage_type=damage_type,
        symbol_filter=symbol_filter,
        supported=upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES,
        source_path=source,
        valid_modifiers=("PM_HEAVY_MELEE",) if code == "HD" else (),
    )


def synthetic_riven_effects(
    stats: Iterable[Mapping[str, Any] | ModEffect],
) -> ModEffectList:
    """Create effects from normalized records or card-display Riven code records.

    A record with ``upgradeType`` supplies an already-normalized internal value.
    A record with ``code`` supplies a max-rank card-display value (usually percent).
    Unknown codes survive as a fail-closed ``skipped`` diagnostic.
    """
    effects = ModEffectList()
    for index, stat in enumerate(stats):
        if isinstance(stat, ModEffect):
            effects.append(stat)
            continue
        if not isinstance(stat, Mapping):
            raise SimulationError(f"riven stat {index} must be an object")
        code = str(stat.get("code") or "").strip().upper()
        if code:
            value = abs(_number(f"riven stat {code} value", stat.get("value")))
            effect = _effect_from_code(
                code,
                value,
                negative=bool(stat.get("negative")),
                source=f"riven:{code}",
            )
            if effect is None:
                effects.skipped.append(f"riven:{code}: unsupported[unknown-code]")
            else:
                effects.append(effect)
            continue
        upgrade_type = str(
            stat.get("upgradeType") or stat.get("upgrade_type") or ""
        ).strip()
        if not upgrade_type:
            effects.skipped.append(f"riven:{index}: unsupported[missing-upgrade-type]")
            continue
        value = _number(f"riven stat {index} value", stat.get("value"))
        effects.append(
            ModEffect(
                upgrade_type=upgrade_type,
                operation=str(stat.get("operation") or "STACKING_MULTIPLY"),
                value=value,
                damage_type=stat.get("damageType") or stat.get("damage_type"),
                symbol_filter=stat.get("symbolFilter") or stat.get("symbol_filter"),
                supported=upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES,
                source_path=str(stat.get("sourcePath") or f"riven:{index}"),
            )
        )
    return effects


def _wire_lines(stats: Any, scale: float = 1.0) -> tuple[list[_RivenLine], list[str]]:
    if not isinstance(stats, list):
        raise SimulationError("riven request stats must be an array")
    if not stats:
        raise SimulationError("riven request stats must contain at least one stat")
    if len(stats) > 4:
        raise SimulationError("riven supports at most three positive stats and one negative stat")
    lines: list[_RivenLine] = []
    unsupported: list[str] = []
    seen: set[str] = set()
    negative_count = 0
    for index, raw in enumerate(stats):
        if not isinstance(raw, Mapping):
            unsupported.append(f"riven-stat-{index}-not-an-object")
            continue
        code = str(raw.get("code") or "").strip().upper()
        if not code:
            unsupported.append(f"riven-stat-{index}-missing-code")
            continue
        if code in seen:
            unsupported.append(f"riven-stat-{code}-duplicate")
            continue
        seen.add(code)
        rule = RIVEN_RULES.get(code)
        negative_raw = raw.get("negative", False)
        if not isinstance(negative_raw, bool):
            raise SimulationError(f"riven stat {code} negative must be boolean")
        negative = negative_raw
        if rule is not None:
            can_roll = rule[8] if negative else rule[7]
            if not can_roll:
                role = "negative" if negative else "positive"
                raise SimulationError(f"riven stat {code} cannot be rolled as {role}")
        raw_value = _number(f"riven stat {code} value", raw.get("value"))
        raw_low = _number(f"riven stat {code} low", raw.get("low"))
        raw_high = _number(f"riven stat {code} high", raw.get("high"))
        if raw_value < 0 or raw_low < 0 or raw_high < 0:
            raise SimulationError(
                f"riven stat {code} values must be finite and non-negative"
            )
        if raw_low and raw_high and raw_low > raw_high:
            raise SimulationError(f"riven stat {code} low value exceeds high value")
        value, low, high = (
            raw_value * scale,
            raw_low * scale,
            raw_high * scale,
        )
        if not all(math.isfinite(item) for item in (value, low, high)):
            raise SimulationError(
                f"riven stat {code} projected values must be finite"
            )
        label = str(raw.get("label") or (rule[0] if rule else code))
        if negative:
            negative_count += 1
        effect = _effect_from_code(
            code, value, negative=negative, source=f"riven:{code}"
        )
        if effect is None:
            unsupported.append(f"riven-stat-{code}-unknown")
        elif not effect.supported:
            unsupported.append(f"riven-stat-{code}-{effect.upgrade_type}-not-evaluated")
        lines.append(
            _RivenLine(
                code, label, value, low, high, negative,
                str(raw.get("unit") or (rule[5] if rule else "")), effect,
            )
        )
    if negative_count > 1 or len(stats) - negative_count > 3:
        raise SimulationError("riven supports at most three positive stats and one negative stat")
    return lines, unsupported


def _card_from_lines(lines: Sequence[_RivenLine]) -> _Card:
    effects = tuple(line.effect for line in lines if line.effect is not None)
    skipped = tuple(
        f"riven:{line.code}: unsupported[no-handler]"
        for line in lines
        if line.effect is None or not line.effect.supported
    )
    return _Card(
        key="__riven__",
        record=None,
        rank=8,
        effects=effects,
        skipped=skipped,
        drain=18,
        polarity="AP_ATTACK",
        riven_lines=tuple(lines),
    )


def _combo_tier_card(mod: Mapping[str, Any]) -> bool:
    """Blood Rush / Weeping Wounds: empty at a static combo tier, but the melee
    hit schedule raises their stacks with the live combo counter."""
    return any(
        any(str(c).endswith("/OnComboTierCondition") for c in conditional.get("conditions") or ())
        and any(e.get("upgradeType") in SUPPORTED_WEAPON_UPGRADE_TYPES for e in conditional.get("effects") or ())
        for conditional in mod.get("conditionalEffects") or ()
        if isinstance(conditional, Mapping)
    )


def _mod_card(
    mod: Mapping[str, Any],
    scenario: Scenario,
    *,
    required: bool = False,
    allow_empty: bool = False,
    set_shell: Mapping[str, Any] | None = None,
    rank: int | None = None,
) -> _Card | None:
    rank = int(mod.get("maxRank") or 0) if rank is None else rank
    effects = mod_effects(mod, rank, _steady_state_scenario((mod,), scenario))
    active = tuple(
        effect
        for effect in effects
        if effect.supported and effect.upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES
    )
    if not active and not allow_empty and not _combo_tier_card(mod):
        return None
    drain = max(0, int(mod.get("baseDrain") or 0) + rank)
    return _Card(
        key=str(mod.get("path") or mod.get("nameInternal") or mod.get("nameEn")),
        record=mod,
        rank=rank,
        effects=tuple(effects),
        skipped=tuple(effects.skipped),
        drain=drain,
        polarity=mod.get("polarity") or None,
        required=required,
        set_shell=set_shell,
    )


def _candidate_mods(
    exports: Mapping[str, Any], weapon: Mapping[str, Any], scenario: Scenario
) -> tuple[list[_Card], int]:
    cards: list[_Card] = []
    rejected = 0
    shells = _set_shells(exports["mods"])
    reach: Mapping[str, Any] | None = None
    from .runtime_adapters import double_tap_configuration
    for mod in exports["mods"]:
        path = str(mod.get("path") or "")
        # 「蓄力装填 Prime」（SniperReloadDamageModExpert）与开发者版「压迫点」
        # （WeaponMeleeDamageOnHeavyKillMod，记录级 supported=false、基础词条为空、
        # 只有 0.5s 的蓄力击杀条件词条）都是 DE 数据里从未发布的 dev 残留，
        # 不进候选池，与 app._manual_mod_rows 的收录口径一致；否则同名占位卡会
        # 顶掉真正的压迫点，且前端素材库没有它的卡面/容量数据。
        if path in {
            "/Lotus/Upgrades/Mods/Rifle/Expert/SniperReloadDamageModExpert",
            "/Lotus/Upgrades/Mods/Melee/WeaponMeleeDamageOnHeavyKillMod",
        }:
            continue
        if (
            mod.get("selectable") is not True
            or not mod.get("compatibility")
            or ("/PvPMods/" in path and not double_tap_configuration(mod,int(mod.get('maxRank') or 0)))
            or not _mod_matches_weapon(mod, weapon)
        ):
            continue
        if mod.get("nameEn") == "Primed Reach":
            reach = mod
        card = _mod_card(
            mod,
            scenario,
            set_shell=shells.get(_set_key(mod.get("modSet"))),
        )
        if card is None:
            rejected += 1
        else:
            cards.append(card)
    if (
        _weapon_type(None, weapon) == "melee"
        and not weapon.get("isExalted")
        and reach is not None
    ):
        required_reach = _mod_card(
            reach, scenario, required=True, allow_empty=True
        )
        if required_reach is not None:
            cards.append(required_reach)
    cards.sort(key=lambda card: card.key)
    return cards, rejected


def _tier_number(value: Any) -> int | None:
    raw = str(value or "").strip().casefold()
    if raw.startswith("tier"):
        raw = raw[4:]
    try:
        number = int(raw)
    except ValueError:
        return None
    return number if number > 0 else None


def _select_fire_mode(
    weapon: Mapping[str, Any], requested: Any, *, weapon_type: str
) -> tuple[Mapping[str, Any], int]:
    modes = weapon.get("fireModes") or ()
    if not isinstance(modes, (list, tuple)) or not modes:
        raise SimulationError("weapon has no fire modes")
    if requested is None:
        index = 0
    else:
        if isinstance(requested, bool) or not isinstance(requested, int):
            raise SimulationError("fireMode must be a non-negative integer")
        index = requested
    if index < 0 or index >= len(modes):
        raise SimulationError(
            f"fireMode {index} is out of range for {len(modes)} fire modes"
        )
    if (modes[index].get('behaviorKind') == 'auxiliary-melee'
            and weapon.get('slot') in ('primary','secondary','arch_gun')):
        raise SimulationError(f"fire mode {index} is auxiliary melee, outside nonmelee scope")
    selected = {**weapon, "fireModes": [modes[index]], "__selectedFireMode__": index, "__baseFireModes__": list(modes)}
    # 灵化循环口径（Scenario.incarnon_cycle）需要基础形态的装填时长折算
    # 充能——保留完整模式列表供 apply_mods 读取。
    if weapon.get("isIncarnon"):
        selected["__baseFireModes__"] = list(modes)
    from .event_profiles import is_incarnon_mode
    selected['isIncarnonForm'] = is_incarnon_mode(weapon,index)
    return selected, index


def _path_basename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _branch_effects(branch: Mapping[str, Any]) -> tuple[list[ModEffect], list[str]]:
    from .runtime_adapters import miter_charge_aoe
    if miter_charge_aoe(branch):
        return [ModEffect('RUNTIME_MITER_CHARGE_AOE','ADD',1.,source_path=branch['path'])], []
    from .runtime_adapters import onos_crits_for_hits
    if onos_crits_for_hits(branch):
        return [ModEffect('RUNTIME_ONOS_CRITS_FOR_HITS','ADD',.05,source_path=branch['path'])], []
    from .runtime_adapters import reserve_ammo_refund
    if reserve_ammo_refund(branch):
        return [ModEffect('RUNTIME_RESERVE_AMMO_REFUND','ADD',0.,source_path=branch['path'])], []
    from .runtime_adapters import latron_puncture_strip
    if latron_puncture_strip(branch):
        return [ModEffect('RUNTIME_PUNCTURE_ARMOR_STRIP','ADD',.2,source_path=branch['path'])], []
    from .runtime_adapters import ammo_restore_configuration
    if ammo_restore_configuration(branch):
        return [ModEffect('RUNTIME_MAGAZINE_RESTORE','ADD',1.,source_path=branch['path'])], []
    if branch.get('path')=='/Lotus/Upgrades/Evolutions/Shotgun/EvoShotgunShellReloadToggle':
        from .runtime_adapters import verified_incarnon_condition
        if any(verified_incarnon_condition(branch,c) for c in branch.get('conditionalEffects') or []):
            return [ModEffect('RUNTIME_RELOAD_PROJECTILE_TOGGLE','ADD',1.,source_path=branch['path'])], []
    from .runtime_adapters import verified_torid_field_duration, incarnon_stat_conversion
    if verified_torid_field_duration(branch):
        # This perk is consumed by the shared event resolver, never as a stat buff.
        return [], []
    conversion = incarnon_stat_conversion(branch)
    if conversion:
        return [ModEffect('RUNTIME_INCARNON_STAT_CONVERSION', 'ADD', conversion['fraction'],
                          source_path=branch.get('path'), runtime_kind=conversion['source'],
                          runtime_damage_type=conversion['target'], runtime_threshold=conversion['maximum'])], []
    source = str(branch.get("path") or branch.get("id") or "incarnon")
    effects: list[ModEffect] = []
    unsupported: list[str] = []
    from .runtime_adapters import verified_incarnon_condition
    from .manual_combat import condition_kind
    modeled_sources = set()
    for condition in branch.get('conditionalEffects') or ():
        source_path = str(condition.get('sourcePath') or source)
        if verified_incarnon_condition(branch, condition):
            modeled_sources.add(source_path)
            continue
        kind = condition.get('eventKind') or condition_kind(condition)
        terms = condition.get('effects') or ()
        # Empty-condition terminal magazine gates are still event modeled by
        # manual_combat.resolve (Final Fusillade). Do not report them as a
        # missing conditional block merely because the export has no tag.
        if (not kind and terms and any(e.get('upgradeType') == 'WEAPON_LAST_MULTISHOT'
                                      for e in terms if isinstance(e, Mapping))):
            modeled_sources.add(source_path)
            continue
        # Conditional evolution terms with an identified replay event are
        # consumed by manual_combat.prepare; keep them out of the static
        # panel without falsely reporting them as absent. Unknown/empty
        # condition blocks remain fail-closed and visible.
        if kind and terms and all(ModEffect.from_export(e, 0).supported for e in terms):
            modeled_sources.add(source_path)
    # Flattened child effects repeat the condition block. Never make them passive.
    conditional_sources = {str(c.get('sourcePath') or source)
                           for c in branch.get('conditionalEffects') or () if c.get('effects')}
    for raw in branch.get("effects") or ():
        if not isinstance(raw, Mapping):
            continue
        if raw.get('upgradeType')=='NONE' and any(verified_incarnon_condition(branch,c) for c in branch.get('conditionalEffects') or []):
            continue
        if str(raw.get('sourcePath') or source) in conditional_sources:
            condition = next((c for c in branch.get('conditionalEffects') or () if str(c.get('sourcePath') or source)==str(raw.get('sourcePath') or source)),None)
            from .runtime_adapters import passive_incarnon_condition
            if condition and ((not condition.get('conditions') and not condition.get('runtimeScripts'))
                              or passive_incarnon_condition(condition)):
                effect = ModEffect.from_export(raw,0,source_path=source)
                if effect.supported:
                    effects.append(effect)
                    modeled_sources.add(str(raw.get('sourcePath') or source))
                    continue
            if str(raw.get('sourcePath') or source) not in modeled_sources:
                unsupported.append(f'incarnon-{branch.get("id")}-conditional-source-excluded')
            continue
        gate = _incarnon_expected_weight(str(raw.get("sourcePath") or source))
        if gate == "headshot_only":
            # Ammo efficiency that lands only on headshots earns nothing under
            # the headshot=0 benchmark (and the sim's body-aim fights).
            unsupported.append(
                f"incarnon-{branch.get('id')}-headshot-gate-excluded-no-aim"
            )
            continue
        if gate == "no_crit_no_proc":
            # "+X% on hits that neither crit nor status" (Evolution V family).
            # Under the optimistic panel/optimizer view the build is assumed to
            # be critting, which this perk's gate excludes — mirroring wfsim's
            # AssumedMax treatment of mutually-exclusive gates it contributes
            # its expected value only in the emergent simulation, so the panel
            # drops it (docs/MECHANICS.md §Incarnon evolutions).
            unsupported.append(
                f"incarnon-{branch.get('id')}-no-crit-no-proc-gate-excluded-from-panel"
            )
            continue
        # ── 灵化进化 SubUpgrade（子词条）语义分层 ─────────────────────────
        # 主进化文件的 SubUpgrades 子词条分两类（引擎语义按 gate 元数据区分）：
        #   1) 无条件常驻（无 UpgradeDuration/MaxConditionalStacks，如
        #      BoltorEvoTier1ASubMod 的穿透+4/散布-40%）——游戏内就是常驻
        #      属性，直接进面板。
        #   2) 条件叠层（带 UpgradeChance/UpgradeDuration/MaxConditionalStacks，
        #      如 BoltorEvoTier1BSubMod 的「装填时每秒+2伤害，最多4层，
        #      持续5s」）——事件/条件触发，绝不按常驻进面板（用户报告的
        #      「触发类按常驻算」问题的通用防线）；条件语义由
        #      trigger_specs 事件模拟承载（见 _incarnon_trigger_sources）。
        if raw.get("isSubUpgrade"):
            has_gate = (
                raw.get("UpgradeDuration") is not None
                or raw.get("MaxConditionalStacks") is not None
                or (
                    isinstance(raw.get("UpgradeChance"), (int, float))
                    and not isinstance(raw.get("UpgradeChance"), bool)
                    and float(raw.get("UpgradeChance")) < 1.0
                )
            )
            if has_gate:
                unsupported.append(
                    f"incarnon-{branch.get('id')}-sub-upgrade-conditional-excluded"
                    f"({'UpgradeChance' if raw.get('UpgradeChance') is not None else 'conditional'}"
                    f":{str(raw.get('sourcePath') or '').rsplit('/', 1)[-1]})"
                )
                continue
            # 无条件子词条：fall through 按常驻词条处理。
        effect = ModEffect.from_export(raw, 0, source_path=source)
        if effect.supported:
            effects.append(effect)
        else:
            unsupported.append(
                f"incarnon-{branch.get('id')}-{effect.upgrade_type}-not-evaluated"
            )
    if any(str(c.get('sourcePath') or source) not in modeled_sources
           for c in branch.get('conditionalEffects') or ()):
        unsupported.append(f"incarnon-{branch.get('id')}-conditional-effects-not-applied")
    if branch.get("runtimeScripts") and not any(verified_incarnon_condition(branch, c) for c in branch.get('conditionalEffects') or ()):
        unsupported.append(f"incarnon-{branch.get('id')}-runtime-scripts-not-applied")
    if branch.get("unresolvedReferences"):
        unsupported.append(f"incarnon-{branch.get('id')}-unresolved-references")
    return effects, unsupported


def _branch_trigger_specs(branch: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Export only identified events; a duration alone does not imply on-hit."""
    from .manual_combat import condition_kind
    from .runtime_adapters import verified_incarnon_condition
    specs=[]
    for condition in branch.get('conditionalEffects') or []:
        verified=verified_incarnon_condition(branch, condition)
        if verified:condition=verified
        if condition.get('runtimeScripts'):continue
        kind=condition.get('eventKind') or condition_kind(condition)
        if not kind:continue
        source=str(condition.get('sourcePath') or branch.get('path') or '')
        terms=condition.get('effects') or []
        spec={'id':'incarnon-'+str(branch.get('id'))+'-'+source.rsplit('/',1)[-1],
              'label':'灵化·'+str(branch.get('id')),'kind':kind,
              'perEvent':float(condition.get('chance') or 1.),
              'maxStacks':float(condition.get('maxStacks') or 1.),
              'duration':float(condition.get('duration') or 0.)}
        if condition.get('resetOn'):
            spec['resetOn']=list(condition['resetOn'])
        if condition.get('conditionText'):
            spec['conditionText']=condition['conditionText']
        damage=sum(float(e.get('valuePerRank') or 0.) for e in terms if e.get('upgradeType')=='WEAPON_DAMAGE_AMOUNT')
        if damage:spec['damagePerStack']=damage
        specs.append(spec)
    return specs


def _incarnon_actor_effects(branch, scenario, weapon):
    from .runtime_adapters import verified_incarnon_condition, incarnon_actor_stacks
    effects = []
    for raw in branch.get('conditionalEffects') or ():
        condition = verified_incarnon_condition(branch,raw)
        if not condition or not (condition.get('actorGate') or condition.get('energyGate')):
            continue
        stacks = (min(float(condition.get('maxStacks') or 1),
                      math.floor(scenario.combat_state.get('energySpent',0)/condition['energyGate']))
                  if condition.get('energyGate') else incarnon_actor_stacks(condition,scenario,weapon))
        if stacks<=0:
            continue
        for term in condition.get('effects') or ():
            effect = ModEffect.from_export(term,0,source_path=condition.get('sourcePath') or branch.get('path'))
            if effect.supported:
                effects.append(replace(effect,value=effect.value*stacks))
    return effects


# Incarnon evolution perks whose exported effect rows are UNCONDITIONAL but the
# in-game perk is gated on a hit condition (wfsim docs/MECHANICS.md §Incarnon
# evolutions, AGPL-3.0 — see THIRD_PARTY_NOTICES.md).  The export carries no
# condition marker, so the gate is recognised by sourcePath and the effect is
# re-weighted to its expected share of hits.
#
#   EvoPistolDamageOnNoCritAndNoProcHit — "Evolution V: +400% damage on hits
#     that neither crit nor status" → expected weight = (1-cc)·(1-sc).
#   EvoPistolAmmoEfficiencyOnHeadshot — ammo efficiency only lands on
#     headshots → a no-aim benchmark (headshot=0) earns nothing.
_INCARNON_NO_CRIT_NO_PROC_SOURCES = {
    "/Lotus/Upgrades/Evolutions/Pistol/EvoPistolDamageOnNoCritAndNoProcHit",
}
_INCARNON_HEADSHOT_ONLY_SOURCES = {
    "/Lotus/Upgrades/Evolutions/Pistol/EvoPistolAmmoEfficiencyOnHeadshot",
    "/Lotus/Upgrades/Evolutions/Rifle/EvoRifleAmmoEfficiencyOnHeadshot",
}


def _incarnon_expected_weight(source: str) -> str | None:
    """Classify one evolution effect's hit-gate for expected-value weighting."""
    if source in _INCARNON_NO_CRIT_NO_PROC_SOURCES:
        return "no_crit_no_proc"
    if source in _INCARNON_HEADSHOT_ONLY_SOURCES:
        return "headshot_only"
    return None


def _incarnon_card(
    weapon: Mapping[str, Any],
    requested: Any,
    *,
    scenario: Scenario,
    metric: str,
    policy: Mapping[str, Any] | None = None,
    build_label: str | None = None,
) -> tuple[_Card | None, dict[str, str], list[str], dict[str, Any]]:
    incarnon = weapon.get("incarnon") or {}
    tiers = incarnon.get("tiers") or () if isinstance(incarnon, Mapping) else ()
    tier_rows = tiers if isinstance(tiers, list) else []
    requested_map = requested if isinstance(requested, Mapping) else {}
    normalized: dict[int, str] = {}
    for key, value in requested_map.items():
        tier = _tier_number(key)
        if tier is None or not str(value).strip():
            continue
        if tier in normalized:
            raise SimulationError(f"duplicate incarnon tier choice: tier{tier}")
        normalized[tier] = str(value).strip()

    # An explicit route is a user/account state, not a hint.  Reject choices for
    # absent or fixed tiers before the automatic policy/objective fallback runs.
    available_tiers: set[int] = set()
    for raw_tier in tier_rows:
        if not isinstance(raw_tier, Mapping):
            continue
        tier = _tier_number(raw_tier.get("tier"))
        branches = [
            branch
            for branch in (raw_tier.get("branches") or ())
            if isinstance(branch, Mapping)
        ]
        if tier in {2, 3, 4, 5} and (
            raw_tier.get("selectable") is True or len(branches) > 1
        ):
            available_tiers.add(tier)
    unavailable = sorted(set(normalized) - available_tiers)
    if unavailable:
        raise SimulationError(
            "incarnon tier choice unavailable for this weapon: "
            + ", ".join(f"tier{tier}" for tier in unavailable)
        )
    if not tier_rows:
        return None, {}, [], {}
    defaults = DEFAULT_INCARNON_CHOICES.get(str(weapon.get("path") or ""), {})
    selected_effects: list[ModEffect] = []
    selected_triggers: list[dict[str, Any]] = []
    selected: dict[str, str] = {}
    unsupported: list[str] = []
    policy_route: Mapping[str, Any] = {}
    policy_meta: dict[str, Any] = {}
    policy_used: list[str] = []

    if policy:
        adapter = str(incarnon.get("adapter") or "")
        adapter_key = _path_basename(adapter)
        policy_meta = {
            "adapter": adapter,
            "strategyKey": adapter_key,
            "sampledAt": policy.get("sampledAt"),
            "gameBuild": policy.get("gameBuild"),
            "matched": False,
        }
        if policy.get("gameBuild") != build_label:
            policy_meta["reason"] = "build-mismatch"
            unsupported.append("incarnon-policy-build-mismatch")
        elif not adapter_key:
            policy_meta["reason"] = "weapon-adapter-missing"
            unsupported.append("incarnon-policy-adapter-missing")
        else:
            strategies = policy.get("strategies") or {}
            match = next(
                (
                    (key, value)
                    for key, value in strategies.items()
                    if str(key).casefold() == adapter_key.casefold()
                    and isinstance(value, Mapping)
                ),
                None,
            )
            if match is None:
                policy_meta["reason"] = "strategy-not-found"
                unsupported.append(f"incarnon-policy-{adapter_key}-not-found")
            else:
                strategy_key, strategy = match
                route = strategy.get("route") or {}
                if isinstance(route, Mapping):
                    policy_route = route
                policy_meta.update(
                    {
                        "strategyKey": str(strategy_key),
                        "objective": strategy.get("objective"),
                        "confidence": strategy.get("confidence"),
                        "sources": strategy.get("sources")
                        or [
                            f"{str(policy.get('sourceBase')).rstrip('/')}/{build['id']}/"
                            for build in strategy.get("builds") or ()
                            if isinstance(build, Mapping) and build.get("id") is not None
                        ]
                        + ([str(policy.get("regionalSource"))] if policy.get("regionalSource") else []),
                        "builds": strategy.get("builds") or [],
                        "alternatives": strategy.get("alternatives") or [],
                        "sourceKind": policy.get("sourceKind") or "whole-build-votes",
                        "selectionMode": "community-default",
                        "matched": True,
                    }
                )

    for raw_tier in tier_rows:
        if not isinstance(raw_tier, Mapping):
            continue
        tier = _tier_number(raw_tier.get("tier"))
        if tier == 1:
            for fixed in raw_tier.get('branches') or ():
                selected_effects.extend(_incarnon_actor_effects(fixed,scenario,weapon))
            continue
        branches = [
            branch for branch in (raw_tier.get("branches") or ())
            if isinstance(branch, Mapping)
        ]
        if tier is None or not branches:
            continue
        policy_choice = policy_route.get(f"tier{tier}") or policy_route.get(str(tier))
        wanted = (
            normalized.get(tier)
            or policy_choice
            or defaults.get(f"tier{tier}")
            or defaults.get(str(tier))
        )
        branch = next(
            (
                item for item in branches
                if wanted
                and wanted in {
                    str(item.get("id") or ""),
                    str(item.get("path") or ""),
                }
            ),
            None,
        )
        # Keep the offline/UI contract friendly: `tier2=1` means the first
        # visible branch, while exports and policy use stable `2-1` IDs.
        if branch is None and wanted:
            try:
                branch_index = int(str(wanted).strip())
            except (TypeError, ValueError):
                branch_index = 0
            if branch_index > 0:
                branch = next(
                    (
                        item
                        for position, item in enumerate(branches, start=1)
                        if int(item.get("index") or position) == branch_index
                    ),
                    None,
                )
        if wanted and branch is None:
            # An explicit UI choice must never silently turn into an automatic
            # choice: the response would otherwise score a different build.
            if normalized.get(tier):
                raise SimulationError(
                    f"incarnon tier {tier} choice {wanted!r} was not found"
                )
            unsupported.append(f"incarnon-tier{tier}-choice-{wanted}-not-found")

        if branch is None:
            best_score = -math.inf
            for candidate in branches:
                candidate_effects, _ = _branch_effects(candidate)
                candidate_effects.extend(_incarnon_actor_effects(candidate,scenario,weapon))
                trial = ModEffectList([*selected_effects, *candidate_effects])
                try:
                    stats = apply_mods(weapon, trial, scenario=scenario)
                    events = evaluate_projectile_events(
                        weapon, trial, scenario=scenario
                    )
                    candidate_score = _score(stats, metric, events)
                    if weapon.get('slot') in {'primary','secondary','arch_gun'} and metric not in {'shotDamage','perShot','burstDps'}:
                        from .manual_combat import prepare
                        from .combat_replay import replay
                        modes=weapon.get('__baseFireModes__') or weapon.get('fireModes') or []
                        full_weapon={**weapon,'fireModes':modes,'incarnon':{**incarnon,'tiers':[t for t in tier_rows if _tier_number(t.get('tier'))<=tier]}}
                        route={**selected,f'tier{tier}':str(candidate.get('id') or candidate['path'])}
                        combat=prepare(dict(weapon=full_weapon,effects=trial,scenario=scenario,
                                            fire_mode=weapon.get('__selectedFireMode__',0)),[],[],
                                       cycle_enabled=scenario.incarnon_cycle,assumed=False,incarnon_choices=route)
                        replayed=replay(stats,dict(health=1e12,shield=0.,armour=0.,overguard=0.,baseLevel=1),
                                        attacks_per_second=stats.sustained_attack_rate,window_seconds=30.,
                                        combat=combat,trigger_sources=combat['trigger_sources'],collect_timeline=False)
                        candidate_score=(replayed['directWindow']+replayed['dotWindow']+replayed['nonDotWindow'])/30.
                except (TypeError, ValueError):
                    candidate_score = -math.inf
                if branch is None or candidate_score > best_score:
                    best_score, branch = candidate_score, candidate
            mode='event' if weapon.get('slot') in {'primary','secondary','arch_gun'} and metric not in {'shotDamage','perShot','burstDps'} else 'static'
            unsupported.append(f"incarnon-tier{tier}-auto-selected-{mode}-objective")

        assert branch is not None
        branch_effects, branch_unsupported = _branch_effects(branch)
        branch_effects.extend(_incarnon_actor_effects(branch,scenario,weapon))
        selected_effects.extend(branch_effects)
        unsupported.extend(branch_unsupported)
        # 条件 SubUpgrade 子词条 → 触发规格（事件化叠层，进 trigger_specs）。
        branch_triggers = _branch_trigger_specs(branch)
        selected_triggers.extend(branch_triggers)
        selected[f"tier{tier}"] = str(branch.get("id") or branch.get("path") or "")
        if policy_choice and not normalized.get(tier) and selected[f"tier{tier}"] == policy_choice:
            policy_used.append(f"tier{tier}")

    if policy_meta:
        policy_meta["appliedTiers"] = policy_used

    if not selected_effects and not selected:
        return None, selected, unsupported, policy_meta
    return (
        _Card(
            key="__incarnon__",
            record=None,
            rank=0,
            effects=tuple(selected_effects),
            skipped=(),
            drain=0,
            polarity=None,
            trigger_specs=tuple(selected_triggers),
            incarnon_choices=tuple(selected.items()),
        ),
        selected,
        unsupported,
        policy_meta,
    )


def _arcane_matches_weapon(
    arcane: Mapping[str, Any], weapon: Mapping[str, Any]
) -> bool:
    """Allow frame-owned Arcanes when the export declares weapon effects.

    Several weapon buffs are installed on ``PowerSuits/PlayerPowerSuit`` in
    the game data (Avenger, Fury, Rage, etc.).  The authoritative
    ``support.weaponEffects`` count distinguishes those from frame-only
    effects; ``validType`` and upgrade qualifiers are still enforced later by
    ``apply_mods``.
    """
    if arcane.get("equipmentType") == "Kitgun Arcane":
        ancestry = " ".join(str(p) for p in weapon.get("ancestry") or ()).casefold()
        if "modular" not in ancestry and not weapon.get("kitgunParts"):
            return False
    from .damage import archgun_arcane_type_applies
    if archgun_arcane_type_applies(weapon, arcane.get("path"), arcane.get("compatibility")):
        return True
    if _mod_matches_weapon(arcane, weapon):
        return True
    if not _frame_owned_arcane(arcane):
        return False
    support = arcane.get("support")
    if not isinstance(support, Mapping):
        return False
    try:
        return int(support.get("weaponEffects") or 0) > 0
    except (TypeError, ValueError):
        return False


def _frame_owned_arcane(arcane: Mapping[str, Any]) -> bool:
    compatibility = str(arcane.get("compatibility") or "").replace("\\", "/")
    return compatibility.strip("/").casefold().endswith("powersuits/playerpowersuit")


def _expected_capped_poisson(mean: float, limit: int) -> float:
    """Expected ``min(Poisson(mean), limit)`` without external dependencies."""
    if mean <= 0 or limit <= 0:
        return 0.0
    probability = math.exp(-mean)
    cumulative = probability
    expected = 0.0
    for count in range(1, limit + 1):
        expected += max(0.0, 1.0 - cumulative)
        probability *= mean / count
        cumulative = min(1.0, cumulative + probability)
    return min(float(limit), expected)


def _expected_arcane_state(
    arcane: Mapping[str, Any], event_rate: float, elapsed: float | None
) -> tuple[int, float, float, float, dict[str, Any]]:
    trigger = arcane.get("trigger")
    if not isinstance(trigger, Mapping):
        raise SimulationError(
            f"arcane {arcane.get('nameEn') or arcane.get('path') or '?'} "
            "has no exported trigger model"
        )
    chance = _number("arcane trigger chance", trigger.get("chance"), 1.0)
    duration = _number("arcane trigger duration", trigger.get("duration"), 0.0)
    if not 0 <= chance <= 1:
        raise SimulationError("arcane trigger chance must be between zero and one")
    if duration <= 0:
        raise SimulationError("arcane trigger duration must be positive")
    if trigger.get("durationScalesWithRank"):
        raise SimulationError("rank-scaled Arcane trigger duration is not evaluated")
    maximum = trigger.get("maxStacks")
    if maximum is None:
        limit = 1
    elif isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
        raise SimulationError("arcane max stacks must be a positive integer")
    else:
        limit = maximum

    window = duration if elapsed is None else min(duration, max(0.0, elapsed))
    mean = event_rate * chance * window
    active_uptime = 1.0 - math.exp(-mean) if mean else 0.0
    expected_stacks = _expected_capped_poisson(mean, limit)
    applied_stacks = math.ceil(expected_stacks) if expected_stacks else 0
    effect_uptime = expected_stacks / applied_stacks if applied_stacks else 0.0
    # conditionTag 为空时回退 conditions 数组（Primary Crux 家族的
    # OnWeakpointHitCondition 只出现在 conditions 里）。
    condition_bits = [str(trigger.get("conditionTag") or "")]
    trigger_conditions = trigger.get("conditions")
    if isinstance(trigger_conditions, (list, tuple)):
        condition_bits.extend(str(item) for item in trigger_conditions)
    return applied_stacks, effect_uptime, expected_stacks, active_uptime, {
        "triggerChance": chance,
        "durationSeconds": duration,
        "maxStacks": limit,
        "stackMode": str(trigger.get("stackMode") or ""),
        "triggerCondition": " ".join(bit for bit in condition_bits if bit),
    }


def _arcane_card(
    records: Sequence[Mapping[str, Any]],
    requested: Any,
    weapon: Mapping[str, Any],
    *,
    elapsed: float | None = None,
    default_heavy_state: bool = False,
) -> tuple[_Card | None, list[dict[str, Any]], list[str]]:
    if requested is None:
        return None, [], []
    if not isinstance(requested, list):
        raise SimulationError("arcanes must be an array")

    combined: list[ModEffect] = []
    skipped: list[str] = []
    states: list[dict[str, Any]] = []
    unsupported: list[str] = []
    event_arcanes = []
    weapon_arcane_count = 0
    frame_arcane_count = 0
    queries: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(requested):
        if not isinstance(raw, Mapping):
            raise SimulationError(f"arcane state {index} must be an object")
        query_raw = raw.get("query") or raw.get("path")
        if not isinstance(query_raw, str) or not query_raw.strip():
            raise SimulationError(f"arcane state {index} query is empty")
        query = query_raw.strip()
        query_key = query.casefold()
        if query_key in seen:
            raise SimulationError(f"duplicate arcane query: {query!r}")
        seen.add(query_key)
        queries.append(query)

    for index, (raw, query) in enumerate(zip(requested, queries)):
        requested_rank = raw.get("rank")
        if requested_rank is not None and (
            isinstance(requested_rank, bool)
            or not isinstance(requested_rank, int)
            or requested_rank < 0
        ):
            raise SimulationError(f"arcane {query!r} rank must be non-negative")
        wire_rank = requested_rank if requested_rank is not None else 0
        requested_stacks = raw.get("stacks", 0)
        if (
            isinstance(requested_stacks, bool)
            or not isinstance(requested_stacks, int)
            or requested_stacks < 0
        ):
            raise SimulationError(f"arcane {query!r} stacks must be non-negative")
        wire_stacks = requested_stacks
        requested_uptime = raw.get("uptime", 1.0)
        if (
            isinstance(requested_uptime, bool)
            or not isinstance(requested_uptime, (int, float))
            or not math.isfinite(float(requested_uptime))
            or not 0 <= float(requested_uptime) <= 1
        ):
            raise SimulationError(
                f"arcane {query!r} uptime must be finite and between zero and one"
            )
        wire_uptime = float(requested_uptime)
        requested_rate = raw.get("triggerRate")
        if requested_rate is not None:
            if "stacks" in raw or "uptime" in raw:
                raise SimulationError(
                    f"arcane {query!r} triggerRate cannot be combined with stacks or uptime"
                )
            requested_rate = _number(
                f"arcane {query!r} trigger rate", requested_rate
            )
            if requested_rate < 0:
                raise SimulationError(
                    f"arcane {query!r} trigger rate must be non-negative"
                )
        state: dict[str, Any] = {
            "query": query,
            "rank": wire_rank,
            "stacks": wire_stacks,
            "uptime": wire_uptime,
            "mode": "expected" if requested_rate is not None else "manual",
            "triggerRate": requested_rate or 0.0,
            "expectedStacks": wire_stacks * wire_uptime,
            "expectedUptime": wire_uptime if wire_stacks else 0.0,
            "active": False,
            "effectCount": 0,
            "applied": False,
        }
        states.append(state)
        if not records:
            raise SimulationError(
                f"arcane {query!r} cannot be resolved: arcane export is unavailable"
            )
        try:
            arcane = resolve_record(records, query, kind="arcane")
        except SimulationError:
            raise SimulationError(f"arcane {query!r} was not found")

        state.update(record_identity(arcane))
        max_rank = arcane.get("maxRank")
        if (
            requested_rank is not None
            and isinstance(max_rank, int)
            and requested_rank > max_rank
        ):
            raise SimulationError(
                f"arcane {query!r} ranks to {max_rank}, got rank {requested_rank}"
            )
        if requested_rank is None:
            state["rank"] = max_rank if max_rank is not None else 0
        from .enervate import configuration
        enervate_spec = configuration(arcane, int(state['rank']))
        trigger = arcane.get("trigger")
        if enervate_spec:
            trigger = {**(trigger or {}), 'duration': None, 'maxStacks': None}
        if isinstance(trigger, Mapping):
            # conditionTag 为空时回退 conditions 数组（同 _expected_trigger_state）。
            _cond_bits = [str(trigger.get("conditionTag") or "")]
            _trigger_conditions = trigger.get("conditions")
            if isinstance(_trigger_conditions, (list, tuple)):
                _cond_bits.extend(str(item) for item in _trigger_conditions)
            state.update(
                {
                    "triggerChance": _number(
                        "arcane trigger chance", trigger.get("chance"), 1.0
                    ),
                    "durationSeconds": _number(
                        "arcane trigger duration", trigger.get("duration"), 0.0
                    ),
                    "maxStacks": int(trigger.get("maxStacks") or 1),
                    "stackMode": str(trigger.get("stackMode") or ""),
                    "triggerCondition": " ".join(bit for bit in _cond_bits if bit),
                }
            )
        implicit_heavy_state = (
            default_heavy_state and not enervate_spec
            and requested_rate is None
            and "stacks" not in raw
            and "uptime" not in raw
        )
        if implicit_heavy_state:
            limits = [
                int(conditional.get("maxStacks") or 1)
                for conditional in arcane.get("conditionalEffects") or ()
                if isinstance(conditional, Mapping)
                and isinstance(conditional.get("maxStacks", 1), int)
                and not isinstance(conditional.get("maxStacks", 1), bool)
            ]
            wire_stacks = int(
                (trigger.get("maxStacks") if isinstance(trigger, Mapping) else 0)
                or (max(limits) if limits else 0)
            )
            wire_uptime = 1.0
            state.update(
                {
                    "stacks": wire_stacks,
                    "uptime": wire_uptime,
                    "mode": "manual-default-max",
                    "expectedStacks": float(wire_stacks),
                    "expectedUptime": 1.0 if wire_stacks else 0.0,
                    "maxStacks": wire_stacks,
                }
            )
        if not _arcane_matches_weapon(arcane, weapon):
            unsupported.append(f"arcane-state-{index}-incompatible-with-weapon")
            continue
        if _frame_owned_arcane(arcane):
            frame_arcane_count += 1
            if frame_arcane_count > 2:
                raise SimulationError("at most two frame-owned Arcanes may be selected")
        else:
            weapon_arcane_count += 1
            if weapon_arcane_count > (2 if weapon.get("slot") == "arch_gun" else 1):
                raise SimulationError("weapon Arcane slot limit exceeded")
        if arcane.get("unresolvedReferences"):
            unsupported.append(f"arcane-state-{index}-has-unresolved-references")
            continue
        effect_stacks = wire_stacks
        effect_uptime = wire_uptime
        if requested_rate is not None and not enervate_spec:
            (
                effect_stacks,
                effect_uptime,
                expected_stacks,
                expected_uptime,
                trigger_state,
            ) = _expected_arcane_state(arcane, requested_rate, elapsed)
            state.update(trigger_state)
            state["stacks"] = effect_stacks
            state["uptime"] = expected_uptime
            state["expectedStacks"] = expected_stacks
            state["expectedUptime"] = expected_uptime
        from .runtime_adapters import compression_configuration
        compression_spec = compression_configuration(arcane, int(state['rank']))
        if compression_spec and raw.get('stacks') == 0:
            effect_uptime = 0.0
        try:
            effects = arcane_effects(
                arcane,
                rank=raw.get("rank"),
                stacks=effect_stacks,
                uptime=effect_uptime,
            )
        except (TypeError, ValueError) as exc:
            state["error"] = str(exc)
            unsupported.append(f"arcane-state-{index}-invalid-not-applied")
            continue
        from .status_arcanes import configuration as status_configuration
        status_spec = status_configuration(arcane, int(state['rank']))
        if status_spec:
            status_uptime = 0.0 if raw.get('stacks') == 0 else wire_uptime
            state.update(active=status_uptime>0, applied=True, effectCount=1, mode='events',
                         eventModel=status_spec['kind'], expectedUptime=status_uptime)
            state.pop('error', None)
        if enervate_spec:
            state.update(durationSeconds=None,maxStacks=None,stackMode='joint-probability-reset',
                         mode='explicit-fixed' if 'stacks' in raw else 'events',
                         resetAfter=enervate_spec['resetAfter'])
        event_arcanes.append((arcane, int(state["rank"]), dict(raw)))
        supported_effects = [effect for effect in effects if effect.supported]
        unsupported_effects = [effect for effect in effects if not effect.supported]
        if effects.skipped:
            skipped.extend(effects.skipped)
        if unsupported_effects:
            unsupported.append(f"arcane-state-{index}-unsupported-effects-skipped")
        if effects.skipped:
            unsupported.append(f"arcane-state-{index}-runtime-effects-skipped")
        if supported_effects:
            combined.extend(supported_effects)
            state["active"] = bool(state["expectedStacks"]) or bool(enervate_spec)
            state["applied"] = True
            state["effectCount"] = len(supported_effects)
            if compression_spec:
                # Actual ADS and per-attack profile gates resolve downstream.
                state.update(mode='conditional', triggerCondition='aiming',
                    eventModel='primary-compression', active=effect_uptime > 0,
                    expectedUptime=effect_uptime, conditionRequired=True,
                    triggerDescription='While aiming: lose 80% of the audited attack radius; continuous damage and ammo-efficiency bonuses per metre lost. Unknown profiles are excluded.',
                    damagePerMeter=compression_spec['damagePerMeter'],
                    ammoEfficiencyPerMeter=compression_spec['ammoPerMeter'])
        elif not status_spec:
            from .manual_combat import modeled_event_kinds
            event_kinds = modeled_event_kinds(arcane, int(state['rank']))
            if event_kinds:
                # Zero starting stacks do not mean the event effect is missing.
                explicit = 'stacks' in raw or 'uptime' in raw
                state.update(
                    applied=True, active=bool(state['expectedStacks']),
                    mode='explicit-fixed' if explicit else 'events',
                    eventModel='conditional-effects', eventKinds=event_kinds,
                )
            else:
                state['error'] = 'no supported static effect'
                unsupported.append(f'arcane-state-{index}-no-supported-effects')

    card = None
    if combined or skipped or event_arcanes:
        card = _Card(
            key="__arcanes__",
            event_arcanes=tuple(event_arcanes),
            record=None,
            rank=0,
            effects=tuple(combined),
            skipped=tuple(skipped),
            drain=0,
            polarity=None,
        )
    return card, states, unsupported


def _merge_passives(*cards: _Card | None) -> _Card | None:
    active = [card for card in cards if card is not None]
    if not active:
        return None
    return _Card(
        key="__passives__",
        trigger_specs=tuple(t for c in active for t in c.trigger_specs),
        event_arcanes=tuple(r for c in active for r in c.event_arcanes),
        incarnon_choices=tuple(x for c in active for x in c.incarnon_choices),
        record=None,
        rank=0,
        effects=tuple(effect for card in active for effect in card.effects),
        skipped=tuple(reason for card in active for reason in card.skipped),
        drain=0,
        polarity=None,
    )


def _effects(cards: Sequence[_Card], scenario: Scenario) -> ModEffectList:
    result = ModEffectList()
    set_counts: dict[str, int] = {}
    set_shells: dict[str, Mapping[str, Any]] = {}
    for card in cards:
        if card.record is None:
            continue
        set_id = _set_key(card.record.get("modSet"))
        if set_id:
            set_counts[set_id] = set_counts.get(set_id, 0) + 1
            if card.set_shell is not None:
                set_shells[set_id] = card.set_shell
    for card in cards:
        current = ModEffectList(card.effects, skipped=card.skipped)
        if card.record is not None:
            set_id = _set_key(card.record.get("modSet"))
            pieces = set_counts.get(set_id, 0)
            if pieces and card.record.get("modSetValues"):
                multiplier = _buff_set_multiplier(card.record, pieces)
                if multiplier != 1.0:
                    current = ModEffectList(
                        (replace(effect, value=effect.value * multiplier) for effect in current),
                        skipped=current.skipped,
                    )
        result.extend(current)
        result.skipped.extend(current.skipped)
    for set_id, pieces in set_counts.items():
        shell = set_shells.get(set_id)
        if shell is not None:
            expanded = _set_shell_effects(shell, pieces, scenario)
            result.extend(expanded)
            result.skipped.extend(expanded.skipped)
    return result


def _capacity(cards: Sequence[_Card]) -> int:
    # The theoretical build assumes a Catalyst and enough Forma to match every
    # equipped polarity.  This is the only account-independent capacity model.
    return sum(
        math.ceil(card.drain / 2)
        if card.polarity and card.polarity != "AP_UNIVERSAL"
        else card.drain
        for card in cards
    )


def _forma_summary(
    weapon: Mapping[str, Any],
    cards: Sequence[_Card],
    riven: _Card | None = None,
    stance: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    """无限极化口径下该配装需要投入的极化次数。

    逐槽消耗武器原生极性：MOD 极性没有原生槽可占即需一次极化；紫卡按
    Madurai 计；Umbra 系极性单独统计（需要 Umbra Forma）；架势槽原生极性
    与所选架势不匹配时计一次（架势不占普通槽，但槽位本身可以极化）。
    """
    native: dict[str, int] = {}
    for value in list(weapon.get("polarities") or ())[:8]:
        key = str(value)
        native[key] = native.get(key, 0) + 1
    regular = 0
    umbra = 0
    ordered = list(cards)
    if riven is not None:
        ordered.append(riven)
    for card in ordered:
        polarity = str(card.polarity or "")
        if not polarity or polarity == "AP_UNIVERSAL":
            continue
        if native.get(polarity, 0) > 0:
            native[polarity] -= 1
        elif polarity in {"AP_UMBRA", "AP_ULTIMATE"}:
            umbra += 1
        else:
            regular += 1
    stance_count = int(
        bool(
            stance
            and stance.get("path")
            and not stance.get("builtIn")
            and stance.get("polarityRelation") != "matched"
        )
    )
    total = regular + umbra + stance_count
    return {"regular": regular, "umbra": umbra, "stance": stance_count, "total": total}


def _mod_family(card: _Card) -> str:
    if card.record is None:
        return card.key
    return str(
        card.record.get("modFamily")
        or card.record.get("nameTag")
        or card.record.get("nameEn")
        or card.record.get("nameInternal")
        or card.key
    ).casefold()


def _metrics(
    stats: Any, projectile_events: Mapping[str, Any] | None = None
) -> dict[str, float]:
    crit = effective_hit_multiplier(
        stats.crit_chance, stats.crit_multiplier, stats.noncrit_damage_multiplier
    )
    shot = stats.average_hit * stats.multishot
    result = {
        "shotDamage": shot,
        "burstDps": stats.burst_dps * crit,
        "sustainedDps": stats.sustained_dps * crit,
        "attackDps": shot * stats.fire_rate,
        "heavyDamage": (
            float(stats.heavy_damage)
            if stats.heavy_damage is not None
            else stats.average_hit * stats.fire_rate
        ),
    }
    safe_hit = (
        ((projectile_events or {}).get("totals") or {})
        .get("averageHit", {})
        .get("minimum", 0.0)
    )
    if isinstance(safe_hit, (int, float)) and not isinstance(safe_hit, bool) and safe_hit > 0:
        safe_hit = float(safe_hit)
        burst = safe_hit * stats.fire_rate
        if stats.magazine and stats.fire_rate:
            shots = stats.magazine
            cycle = shots / stats.fire_rate + (stats.reload_time or 0.0)
            sustained = safe_hit * shots / cycle if cycle else 0.0
        else:
            sustained = burst
        result.update(
            shotDamage=safe_hit,
            burstDps=burst,
            sustainedDps=sustained,
            attackDps=burst,
        )
    result["heavyAttackDps"] = result["heavyDamage"]
    return result


def _bind_combat_inputs(stats, weapon, cards, effects, scenario, passives=None):
    """Keep the loadout with its stats across beam, Riven and ablation scoring.

    Plain data is picklable by search workers. Runtime resolver closures are
    built only inside the event evaluation; public stat serialization is unchanged.
    """
    from .search_combat import bind
    bind(stats, weapon, cards, effects, scenario, passives)
    return stats


def _event_window(stats, context):
    from .search_combat import window
    return window(stats, context)


def _score(
    stats: Any,
    metric: str,
    projectile_events: Mapping[str, Any] | None = None,
    target_context: Mapping[str, Any] | None = None,
) -> float:
    if metric in {"targetSustainedDps", "statusSustainedDps"}:
        context = target_context or {}
        target = context.get("target")
        target = target if isinstance(target, Mapping) else {}
        target_kwargs = {
            key: context[key]
            for key in (
                "level",
                "armour_strip",
                "elemental_armour_strip",
                "steel_path",
                "enemy_enhancements",
                "hit_location",
            )
            if key in context
        }
        status = sustained_status_damage(
            stats,
            target,
            attacks_per_second=stats.sustained_attack_rate,
            status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
            damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
            **target_kwargs,
        )
        return float(
            status["totalDps"]
            if metric == "statusSustainedDps"
            else status["directDps"]
        )
    if metric in {"windowedDps", "windowedTotalDamage", "killsPerMinute"}:
        # Event-window scores use the caller's complete target and scenario.
        # Bound loadouts share prepare/replay with manual builds; unbound legacy
        # panel callers retain their original fallback. KPM is the window rate.
        context = target_context or {}
        nodes = context.get("hardnessNodes")
        if nodes:
            # Hardness-integrated score: the geometric mean over target-health
            # nodes (log-uniform hardness), so a 10% gain on any node counts the
            # same and KPM / window-DPS rankings coincide.
            # Per-hit randomness is a random target health: damage + noise >=
            # health is damage >= health - noise. Each node averages two
            # health points at +-1 baseline spread (2-point Gauss-Hermite),
            # which turns shots-to-kill steps into a monotone ramp.
            single = {key: value for key, value in context.items() if key != "hardnessNodes"}
            total = weights = 0.0
            for node in nodes:
                scale, spread = float(node["healthScale"]), float(node.get("healthSpread") or 0.0)
                points = (scale * (1.0 - spread), scale * (1.0 + spread)) if spread > 0 else (scale,)
                value = sum(_score(stats, metric, projectile_events, _with_health_scale(single, point))
                            for point in points) / len(points)
                total += float(node["weight"]) * math.log(max(value, 1e-12))
                weights += float(node["weight"])
            return math.exp(total / weights)
        target = context.get("target")
        target = target if isinstance(target, Mapping) else None
        windowed = _event_window(stats, context) if hasattr(stats, "_combat_inputs") else windowed_status_damage(
            stats,
            target,
            attacks_per_second=stats.sustained_attack_rate,
            window_seconds=float(context.get("windowSeconds") or 5.0),
            headshot_chance=float(context.get('headshotChance') or (1.0 if context.get('hit_location') == 'head' else 0.0)),
            status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
            damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
            level=context.get("level"),
            armour_strip=float(context.get("armour_strip") or 0.0),
            elemental_armour_strip=float(context.get("elemental_armour_strip") or 0.0),
            steel_path=bool(context.get("steel_path")),
            enemy_enhancements=context.get("enemy_enhancements"),
            collect_timeline=False,
        )
        if metric == "killsPerMinute":
            return float(windowed["killsPerMinute"])
        return float(
            windowed["windowDps"]
            if metric == "windowedDps"
            else windowed["totalWindowDamage"]
        )
    return _metrics(stats, projectile_events)[
        "heavyDamage" if metric == "heavyAttackDps" else metric
    ]


# Target calibration is intentionally independent from the historical KPM
# ceiling.  The event ledger can now settle multiple deaths inside one coarse
# integration slice, so pressure is detected from event timing/coverage rather
# than from a magic 120/240 value.
TARGET_CALIBRATION_VERSION = "hardness-integrated-v1"
TARGET_CALIBRATION_MAX_ITERATIONS = 5
TARGET_CALIBRATION_MIN_FIRST_KILL_SECONDS = 1.0
# Target hardness is integrated, not chosen. Hardness is the time the weapon's
# no-Riven baseline needs to kill with body shots, log-uniform over this range
# (seconds), with a 3-point Gauss-Legendre rule in log space: 1.4 / 4.5 /
# 14.3 s. Status ramps and strips are time-based, so a time coordinate is fair
# to beams and snipers alike; integrating over it also averages out
# shots-to-kill steps. Body shots for every headshot rate: 0% and 100%
# analyses of a weapon share one target set.
HARDNESS_TTK_RANGE = (1.0, 20.0)
# Relative health spread (the baseline's damage noise at the node time) is
# capped so a node never reaches a non-positive health.
HEALTH_SPREAD_CAP = 0.5
_GAUSS_LEGENDRE_3 = ((-math.sqrt(0.6), 5.0 / 18.0), (0.0, 8.0 / 18.0), (math.sqrt(0.6), 5.0 / 18.0))
# Weak-point-kill feedback branches for the fast/ultra profiles.
FAST_KILL_BRANCHES = 4
# Element seeds: the greedy beam fixes one element pairing early, so viral
# and corrosive builds are also searched from their two component MODs.
ELEMENT_SEEDS = {"DT_VIRAL": ("DT_FREEZE", "DT_POISON"), "DT_CORROSIVE": ("DT_ELECTRICITY", "DT_POISON")}
# Every element target the build page offers, by the mods that make it. The
# analysis' own seed list above stays the two it always searched.
ELEMENT_TARGET_PARTS = {
    "DT_EXPLOSION": ("DT_FIRE", "DT_FREEZE"),
    "DT_RADIATION": ("DT_FIRE", "DT_ELECTRICITY"),
    "DT_GAS": ("DT_FIRE", "DT_POISON"),
    "DT_MAGNETIC": ("DT_FREEZE", "DT_ELECTRICITY"),
    "DT_VIRAL": ("DT_FREEZE", "DT_POISON"),
    "DT_CORROSIVE": ("DT_ELECTRICITY", "DT_POISON"),
}


def optimize_for_element(
    weapon: Mapping[str, Any],
    candidates: Sequence[_Card],
    riven: _Card | None,
    *,
    required_damage_type: str | None = None,
    **kwargs: Any,
) -> _Evaluation:
    """``_optimize`` with an element target that a narrow beam can miss.

    The beam ranks single cards and keeps the best partial builds, so a pure
    two-element pair (Boltor Prime + viral: nothing cold ranks well alone) may
    never survive to be combined. Before calling the target infeasible, seed
    one mod of each component -- the strongest, then the cheapest for tight
    capacity -- and search again.
    """
    try:
        return _optimize(weapon, candidates, riven, required_damage_type=required_damage_type, **kwargs)
    except SimulationError as exc:
        if not required_damage_type or f"damage type {required_damage_type}" not in str(exc):
            raise
        failure = exc
    required = list(kwargs.pop("required_mod_keys", None) or ())
    forbidden = set(kwargs.get("forbidden_mod_keys") or ())
    parts = ELEMENT_TARGET_PARTS.get(required_damage_type, (required_damage_type,))
    tried = set()
    for prefer in ("strongest", "cheapest"):
        seeded = list(required)
        for part in parts:
            options = [
                (sum(float(e.value) for e in card.effects if e.damage_type == part), card)
                for card in candidates
                if card.key not in forbidden and card.key not in seeded
                and any(e.damage_type == part and e.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED"
                        for e in card.effects)
            ]
            if not options:
                break
            if prefer == "strongest":
                _, card = max(options, key=lambda item: (item[0], -item[1].drain, item[1].key))
            else:
                _, card = min(options, key=lambda item: (item[1].drain, -item[0], item[1].key))
            seeded.append(card.key)
        else:
            if tuple(seeded) in tried:
                continue
            tried.add(tuple(seeded))
            try:
                return _optimize(weapon, candidates, riven, required_damage_type=required_damage_type,
                                 required_mod_keys=seeded, **kwargs)
            except SimulationError:
                # The unseeded search already ran; a seed that does not fit
                # (slots, capacity, a family clash) just is not the answer.
                continue
    raise failure


def _with_health_scale(context: Mapping[str, Any], scale: float) -> dict[str, Any]:
    enhancements = dict(context.get("enemy_enhancements") or {})
    enhancements["healthScale"] = float(scale)
    return dict(context, enemy_enhancements=enhancements)


def _hardness_times() -> list[tuple[float, float]]:
    low, high = (math.log(value) for value in HARDNESS_TTK_RANGE)
    middle, half = (low + high) / 2.0, (high - low) / 2.0
    return [(math.exp(middle + x * half), weight) for x, weight in _GAUSS_LEGENDRE_3]


def _hardness_nodes(stats: Any, context: Mapping[str, Any]) -> list[dict[str, float]] | None:
    """Health-scale nodes that ``stats`` kills in the node times (body shots)."""
    if not hasattr(stats, "_combat_inputs"):
        return None
    from .search_combat import body_ttk_health
    times = _hardness_times()
    rows = body_ttk_health(stats, context, [t for t, _ in times])
    if not rows or any(not math.isfinite(s) or s <= 0 for s, _ in rows):
        return None
    return [dict(ttkSeconds=round(t, 3), healthScale=float(s), weight=w,
                 healthSpread=min(HEALTH_SPREAD_CAP, max(0.0, float(spread))))
            for (t, w), (s, spread) in zip(times, rows)]


def _valid_hardness_nodes(nodes: Any) -> bool:
    return (isinstance(nodes, list) and len(nodes) == len(_GAUSS_LEGENDRE_3) and all(
        isinstance(n, Mapping) and isinstance(n.get("healthScale"), (int, float)) and n["healthScale"] > 0
        and isinstance(n.get("weight"), (int, float)) for n in nodes))


def _center_context(context: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Single-target search context at the middle hardness node."""
    single = {key: value for key, value in context.items() if key != "hardnessNodes"}
    return _with_health_scale(single, float(nodes[len(nodes) // 2]["healthScale"]))


def _window_pressure_probe(
    stats: Any,
    target_context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Run the cheap event-ledger probe used by automatic target calibration."""
    context = target_context or {}
    target = context.get("target")
    if not isinstance(target, Mapping):
        return None
    result = _event_window(stats, context) if hasattr(stats, "_combat_inputs") else windowed_status_damage(
        stats,
        target,
        attacks_per_second=stats.sustained_attack_rate,
        window_seconds=float(context.get("windowSeconds") or 30.0),
        headshot_chance=float(context.get('headshotChance') or (1.0 if context.get('hit_location') == 'head' else 0.0)),
        status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
        damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
        level=context.get("level"),
        armour_strip=float(context.get("armour_strip") or 0.0),
        elemental_armour_strip=float(context.get("elemental_armour_strip") or 0.0),
        steel_path=bool(context.get("steel_path")),
        enemy_enhancements=context.get("enemy_enhancements"),
        collect_timeline=False,
    )
    step = max(float(result.get("timeStep") or 0.25), 0.05)
    first = result.get("firstKillTime")
    interval = result.get("minKillInterval")
    max_per_step = int(result.get("maxKillsPerStep") or 0)
    ledger = result.get("directEventLedger")
    attack_period = (
        1.0 / float(result.get("attacksPerSecond") or 0.0)
        if float(result.get("attacksPerSecond") or 0.0) > 0.0
        else None
    )
    # A target is pressure-insufficient when the first kill is effectively
    # instantaneous, or when the continuous interval is finer than the grid
    # while the direct event ledger says the weapon cannot produce events that
    # quickly.  ``maxKillsPerStep`` is retained as an observability field only:
    # multiple legitimate attack events in one coarse slice are not themselves
    # a simulation error.
    reasons: list[str] = []
    if isinstance(first, (int, float)) and first < TARGET_CALIBRATION_MIN_FIRST_KILL_SECONDS:
        reasons.append("first-kill-below-pressure-floor")
    resolution_floor = max(step * 1.5, 0.2)
    if (
        isinstance(interval, (int, float))
        and interval < resolution_floor
        and isinstance(attack_period, (int, float))
        and attack_period > resolution_floor
    ):
        reasons.append("kill-interval-near-integration-resolution")
    event_ledger_status = (
        str(ledger.get("status")) if isinstance(ledger, Mapping) else "missing"
    )
    result["pressureReasons"] = reasons
    result["pressureInsufficient"] = bool(reasons)
    result["calibrationStep"] = step
    result["pressureDiagnostics"] = {
        "maxKillsPerStep": max_per_step,
        "attackPeriod": attack_period,
        "resolutionFloor": resolution_floor,
        "eventLedgerStatus": event_ledger_status,
        "multipleKillsPerStepIsDiagnosticOnly": True,
    }
    return result


def _next_calibration_level(level: Any) -> int | None:
    """Return the next deterministic pressure-test level, capped at 9999."""
    try:
        current = max(1, int(level))
    except (TypeError, ValueError):
        return None
    if current >= 9999:
        return None
    return min(9999, max(current + 1, int(math.ceil(current * 1.75))))


def _card_elements(card: _Card) -> list[str]:
    return [effect.damage_type for effect in card.effects
            if getattr(effect, "damage_type", None) in BASE_ELEMENTS and effect.value > 0]


def _element_orders(cards: Sequence[_Card]) -> list[tuple[_Card, ...]]:
    """One card order per distinct element pairing, the given order first.

    MOD base elements combine pairwise in order of first appearance (native
    elements always follow), so with three or more MOD elements the same set
    can yield e.g. Viral + Heat or Blast + Toxin. A greedy build order fixes
    one pairing; permute only the element cards among their own slots.
    """
    slots = [index for index, card in enumerate(cards) if _card_elements(card)]
    if len(slots) < 3:
        return [tuple(cards)]
    original = tuple(cards)
    key = _pairing_key(original)
    if not key[1]:  # fewer than three distinct elements: one pairing only
        return [original]
    orders = {key: original}
    for permutation in itertools.permutations([cards[index] for index in slots]):
        ordered = list(cards)
        for index, card in zip(slots, permutation):
            ordered[index] = card
        orders.setdefault(_pairing_key(ordered), tuple(ordered))
    return list(orders.values())


def _pairing_key(cards: Sequence[_Card]) -> tuple:
    sequence: list[str] = []
    for damage_type in (t for card in cards for t in _card_elements(card)):
        if damage_type not in sequence:
            sequence.append(damage_type)
    return (frozenset(sequence[:2]), frozenset(sequence[2:4]))


def _evaluate(
    weapon: Mapping[str, Any],
    cards: Sequence[_Card],
    riven: _Card | None,
    *,
    scenario: Scenario,
    metric: str,
    passives: _Card | None = None,
    slot_limit: int = 8,
    capacity_limit: int = 60,
    special_cards: Sequence[_Card] = (),
    special_capacity_cost: int = 0,
    target_context: Mapping[str, Any] | None = None,
    fixed_riven_index: int | None = None,
    reorder_elements: bool = True,
) -> _Evaluation | None:
    heartbeat(1)
    if len(cards) + (1 if riven else 0) > slot_limit:
        return None
    positions: Iterable[int | None] = (None,)
    if riven is not None and fixed_riven_index is not None:
        positions = (fixed_riven_index,)
    elif riven is not None:
        polarity_sensitive = False  # all cards use matching Forma in this model
        element_sensitive = any(
            effect.damage_type in BASE_ELEMENTS for effect in riven.effects
        )
        if element_sensitive:
            # 元素 coalesce 只在「元素边界」处不同：基伤/暴击/触发卡不改变
            # 元素合并顺序，把紫卡插在它们前后是等价的（每步全量重算的
            # apply_mods + 窗口模型给出相同结果）。等价类 =「riven 排在
            # 第 k 张元素卡之前」（k = 0..n），位置代表取每张元素卡的
            # index + 末尾，把每评估 ~9 次重复计算压到 ~元素卡数+1 次。
            def _is_element_card(card: _Card) -> bool:
                return any(
                    getattr(effect, "damage_type", None) in BASE_ELEMENTS
                    for effect in card.effects
                )

            element_indexes = [
                index for index, card in enumerate(cards) if _is_element_card(card)
            ]
            positions = (*element_indexes, len(cards))
        elif polarity_sensitive:
            positions = range(len(cards) + 1)
        else:
            positions = (len(cards),)
    best: _Evaluation | None = None
    orders = _element_orders(cards) if reorder_elements else [tuple(cards)]
    for position, card_order in itertools.product(positions, orders):
        ordered = list(card_order)
        if riven is not None and position is not None:
            ordered.insert(position, riven)
        capacity = _capacity(ordered) + special_capacity_cost
        if capacity > capacity_limit:
            continue
        all_cards = [*ordered, *special_cards]
        effect_cards = [passives, *all_cards] if passives is not None else all_cards
        effects = _effects(effect_cards, scenario)
        probe_scenario = replace(scenario, victim_status_count=0)
        probe_stats = apply_mods(weapon, effects, scenario=probe_scenario)
        derived_scenario = replace(
            scenario,
            victim_status_count=expected_victim_status_count(probe_stats),
        )
        stats = apply_mods(weapon, effects, scenario=derived_scenario)
        projectile_events = evaluate_projectile_events(
            weapon, effects, scenario=derived_scenario
        )
        _bind_combat_inputs(stats, weapon, all_cards, effects, derived_scenario, passives)
        current = _Evaluation(
            score=_score(stats, metric, projectile_events, target_context),
            cards=tuple(card_order),
            stats=stats,
            capacity=capacity,
            riven_index=position if riven is not None else None,
            scenario=derived_scenario,
        )
        if best is None or current.score > best.score:
            best = current
    return best


@memoized_search
def _optimize(
    weapon: Mapping[str, Any],
    candidates: Sequence[_Card],
    riven: _Card | None,
    *,
    scenario: Scenario,
    metric: str,
    passives: _Card | None = None,
    beam_width: int = 24,
    shortlist: int = 56,
    slot_count: int = 8,
    capacity_limit: int = 60,
    required_damage_type: str | None = None,
    target_context: Mapping[str, Any] | None = None,
    profile: str = "standard",
    required_mod_keys: Sequence[str] | None = None,
    forbidden_mod_keys: Sequence[str] | None = None,
    min_fill: int | None = None,
    max_fill: int | None = None,
    seed_cards: Sequence[_Card] | None = None,
) -> _Evaluation:
    # 解算档位（用户可调，平衡深度与等待时间）：
    #   fast     — beam 12/32，不做爬山。适合快速预览；可能漏掉冷门协同组合。
    #   standard — beam 24/40 + 至多 3 轮爬山（默认）。
    #   deep     — beam 24/56 + 12 轮全邻域爬山 + riven floor 修正（原完整口径）。
    #
    # 搜索约束（wfsim 优化器 scope 模型的移植，见 docs/OPTIMIZER.md）：
    #   required_mod_keys — 必选卡（候选标 required，与架势/剑风同通道）。
    #   forbidden_mod_keys — 禁选卡（从候选池剔除）。
    #   min_fill/max_fill — 配卡数量范围（含必选与紫卡槽）；空范围（0）= 裸枪。
    profile = str(profile or "standard").strip().casefold()
    if profile == "ultra":
        profile = "fast"
    if profile not in {"fast", "standard", "deep"}:
        raise SimulationError(
            "profile must be one of fast, standard, deep"
        )
    if profile == "fast":
        beam_width = min(beam_width, 12)
        shortlist = min(shortlist, 32)
    elif profile == "standard":
        beam_width = min(beam_width, 24)
        shortlist = min(shortlist, 40)
    climb_rounds = {"fast": 0, "standard": 3, "deep": 12}[profile]
    deadline = phase_deadline()
    if isinstance(slot_count, bool) or not isinstance(slot_count, int) or not 1 <= slot_count <= 8:
        raise SimulationError("slot_count must be an integer between 1 and 8")
    if isinstance(capacity_limit, bool) or not isinstance(capacity_limit, int) or capacity_limit < 0:
        raise SimulationError("capacity_limit must be a non-negative integer")
    required_cards = tuple(card for card in candidates if card.required)
    # ── 搜索约束：必选/禁选/数量范围（在家族去重前应用）────────────────
    forbidden = {str(key) for key in (forbidden_mod_keys or ()) if str(key)}
    if forbidden:
        candidates = tuple(
            card for card in candidates if card.key not in forbidden
        )
    extra_required = [
        card for card in candidates
        if card.key in {str(key) for key in (required_mod_keys or ()) if str(key)}
        and not card.required
    ]
    if len(extra_required) != len({card.key for card in extra_required}):
        raise SimulationError("required_mod_keys contains duplicates")
    missing_required = (
        {str(key) for key in (required_mod_keys or ()) if str(key)}
        - {card.key for card in candidates}
    )
    if missing_required:
        raise SimulationError(
            "required mods not in candidate pool: " + ", ".join(sorted(missing_required))
        )
    if min_fill is not None or max_fill is not None:
        base_fill = len(required_cards) + len(extra_required) + (1 if riven else 0)
        # ── F07（审计修复）：未设置的边界不再默认 slot_count——
        # 「只给 max_fill」应意味着下界 0（旧实现把 lo 默认成 8，与
        # max_fill<8 的任何请求冲突直接报错）。
        lo = 0 if min_fill is None else min(max(int(min_fill), 0), slot_count)
        hi = slot_count if max_fill is None else min(max(int(max_fill), 0), slot_count)
        if lo > hi:
            raise SimulationError("min_fill must not exceed max_fill")
        if base_fill > hi:
            raise SimulationError(
                f"required cards ({base_fill}) exceed max_fill ({hi})"
            )
        fill_floor = max(0, lo - base_fill)
        optional_ceiling = max(0, hi - base_fill)
    else:
        fill_floor = 0
        optional_ceiling = slot_count
    required_cards = tuple(required_cards) + tuple(extra_required)
    # ── F07（审计修复）：用户必选卡物化为 required=True ──────────────────
    # 爬山的 Swap/Drop 阶段按 card.required 判定可移除集合；不标记的话
    # beam 之后的局部搜索可能把用户必选卡删掉。
    required_cards = _mark_required_cards(required_cards, required_mod_keys or ())
    candidates = tuple(
        card for card in candidates
        if not card.required and card.key not in {c.key for c in extra_required}
    )
    # Collapse only verified equivalent optional identities, after applying
    # the user's exact required/forbidden paths. Explicit choices stay intact.
    available_keys={c.key for c in (*candidates,*required_cards)}
    candidates=tuple(c for c in candidates
                     if (c.record or {}).get('optimizerDuplicateOf') not in available_keys)

    limit = min(
        slot_count - len(required_cards) - (1 if riven else 0),
        optional_ceiling,
    )
    if limit < 0:
        raise SimulationError("required MODs do not fit the selected slot count")
    empty = _evaluate(
        weapon,
        required_cards,
        riven,
        scenario=scenario,
        metric=metric,
        passives=passives,
        slot_limit=slot_count,
        capacity_limit=capacity_limit,
        target_context=target_context,
    )
    if empty is None:
        raise SimulationError("Riven does not fit the assumed 60-capacity build")

    def eligible(value: _Evaluation) -> bool:
        return required_damage_type is None or (
            value.stats.damage_types.get(required_damage_type, 0.0) > 0
        )

    ranked: list[tuple[float, _Card]] = []
    # ── 单卡排名并行化（~200 次独立评估；物理核 worker 池）────────────
    _rank_jobs = [(*required_cards, card) for card in candidates]
    _rank_scores: list[float | None] = []
    from wfarsenal import parallel as _parallel

    _wire_scenario = (
        scenario
        if isinstance(scenario.conditional_stacks, dict)
        else replace(scenario, conditional_stacks=dict(scenario.conditional_stacks))
    )
    _pool_ctx = {
        "weapon": weapon,
        "scenario": _wire_scenario,
        "metric": metric,
        "passives": passives,
        "slot_limit": slot_count,
        "capacity_limit": capacity_limit,
        "target_context": target_context,
    }
    _pool_exec = _parallel.get_pool()
    if _pool_exec is not None and len(_rank_jobs) >= 8:
        _futures = [
            _pool_exec.submit(_parallel._score_job, (cards, riven, _pool_ctx))
            for cards in _rank_jobs
        ]
        _rank_scores = [fut.result() for fut in _futures]
    for cards, score in zip(_rank_jobs, _rank_scores):
        if score is not None:
            ranked.append((score, cards[-1]))
    if not _rank_scores:
        for cards in _rank_jobs:
            evaluated = _evaluate(
                weapon,
                cards,
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                slot_limit=slot_count,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            if evaluated is not None:
                ranked.append((evaluated.score, cards[-1]))
    ranked.sort(key=lambda item: (-item[0], item[1].key))
    pool: list[_Card] = []
    families: set[str] = set()
    for _, card in ranked:
        family = _mod_family(card)
        if family in families:
            continue
        families.add(family)
        pool.append(card)
        if len(pool) >= shortlist:
            break

    beam: list[tuple[tuple[int, ...], _Evaluation]] = [((), empty)]
    best = empty if eligible(empty) else None
    # ── F15/S06（审计修复）：多起点——贪心种子先入 incumbent ─────────────
    # beam 的层序选择是贪心的，但单层 beam 剪枝可能中途淘汰后续才显出协
    # 同的路径。用「逐张取当前最优单卡」的贪心序列作第二个起点：它覆盖
    # beam 剪枝漏掉的显见组合，且成本 O(limit × pool)。同时保证高档位
    # 不劣于贪心口径（S07 的实际下界）。
    greedy_cards: list[_Card] = []
    greedy_used_families: set[str] = set()
    for _ in range(limit):
        greedy_pick: _Card | None = None
        for card in pool:
            if card.key in {c.key for c in greedy_cards}:
                continue
            if _mod_family(card) in greedy_used_families:
                continue
            greedy_pick = card
            break
        if greedy_pick is None:
            break
        candidate_cards = (*required_cards, *greedy_cards, greedy_pick)
        if validate_build(
            candidate_cards,
            riven,
            slot_count=slot_count,
            capacity_limit=capacity_limit,
            required_mod_keys=required_mod_keys,
            forbidden_mod_keys=forbidden_mod_keys,
            min_fill=min_fill,
            max_fill=max_fill,
        ) is not None:
            break
        greedy_cards.append(greedy_pick)
        greedy_used_families.add(_mod_family(greedy_pick))
    if greedy_cards:
        greedy_eval = _evaluate(
            weapon,
            (*required_cards, *greedy_cards),
            riven,
            scenario=scenario,
            metric=metric,
            passives=passives,
            slot_limit=slot_count,
            capacity_limit=capacity_limit,
            target_context=target_context,
        )
        if greedy_eval is not None and eligible(greedy_eval) and (
            best is None or greedy_eval.score > best.score
        ):
            best = greedy_eval
    # ── baseline 种子（携带紫卡的实际/最优搜索下界保证）─────────────────
    # 紫卡占容量（~18）会改变 beam 的可行组合空间：fast/standard 档的剪枝
    # 可能把「无紫卡时的最优配装家族」整体淘汰，导致 actual < baseline 的
    # 假象（用户报告：加了紫卡评分反而崩）。把 baseline 的选卡作为种子
    # 直接评估（按容量逐张保留，装不下就丢），确保带紫卡搜索不劣于
    # 「baseline 配装去掉最贵的一张」这个自然下界。
    if seed_cards:
        candidate_pool_keys = {card.key for card in pool}
        seed_kept: list[_Card] = []
        for card in seed_cards:
            if card.required or card.key in candidate_pool_keys or any(
                c.key == card.key for c in required_cards
            ):
                if validate_build(
                    (*required_cards, *seed_kept, card),
                    riven,
                    slot_count=slot_count,
                    capacity_limit=capacity_limit,
                    required_mod_keys=required_mod_keys,
                    forbidden_mod_keys=forbidden_mod_keys,
                    min_fill=min_fill,
                    max_fill=max_fill,
                ) is None:
                    seed_kept.append(card)
        if seed_kept:
            seed_eval = _evaluate(
                weapon,
                (*required_cards, *seed_kept),
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                slot_limit=slot_count,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            if seed_eval is not None and eligible(seed_eval) and (
                best is None or seed_eval.score > best.score
            ):
                best = seed_eval
    # One beam layer reaches the same MOD set from several parents, each time
    # in a different slot order (AB+C, AC+B, BC+A: about half of a layer).
    # _evaluate tries every element pairing, so without an elemental Riven
    # the order does not change the score: replay each set once and share it.
    # An elemental Riven is placed relative to the element cards' order, so
    # there the order stays part of the key.
    order_free = riven is None or not any(effect.damage_type in BASE_ELEMENTS for effect in riven.effects)

    def score_key(cards: Sequence[_Card]) -> tuple[str, ...]:
        keys = tuple(card.key for card in cards)
        return tuple(sorted(keys)) if order_free else keys

    layer_scores: dict[tuple[str, ...], float | None] = {}
    for _ in range(limit):
        expanded: list[tuple[tuple[int, ...], _Evaluation]] = []
        if expired(deadline):
            break
        # ── 并行层扩展（物理核进程池；串行回退=1 核或 WF_ANALYZER_SERIAL）──
        # 每层数百次独立评估分发到 worker；worker 只回 score（避免 stats
        # 的深 pickle），beam 幸存者与 incumbent 在父进程串行重评估以附上
        # 完整 stats（确定性纯函数，~15 次/层）。
        layer_jobs: list[tuple[tuple[int, ...], tuple[tuple[int, ...], ...]]] = []
        for selected, _previous in beam:
            used = set(selected)
            used_families = {_mod_family(pool[index]) for index in selected}
            for index in range(len(pool)):
                if index in used or _mod_family(pool[index]) in used_families:
                    continue
                layer_jobs.append(
                    ((*selected, index), (*required_cards, *(
                        pool[item] for item in (*selected, index)
                    )))
                )
        scores: list[float | None] = []
        if layer_jobs:
            todo: dict[tuple[str, ...], tuple[_Card, ...]] = {}
            for _sel, cards in layer_jobs:
                todo.setdefault(score_key(cards), cards)
            unique = list(todo.items())
            if _pool_exec is not None and len(unique) >= 8:
                # Keep only a bounded batch in flight. A deadline must not
                # leave thousands of queued replay jobs running after return.
                for offset in range(0, len(unique), 16):
                    if expired(deadline):
                        break
                    batch = unique[offset:offset + 16]
                    futures = [_pool_exec.submit(_parallel._score_job,
                               (cards, riven, _pool_ctx)) for _key, cards in batch]
                    for (key, _cards), future in zip(batch, futures):
                        layer_scores[key] = future.result()
                    heartbeat(len(batch))
            else:
                for key, cards in unique:
                    if expired(deadline):
                        break
                    evaluated = _evaluate(
                        weapon,
                        cards,
                        riven,
                        scenario=scenario,
                        metric=metric,
                        passives=passives,
                        slot_limit=slot_count,
                        capacity_limit=capacity_limit,
                        target_context=target_context,
                    )
                    layer_scores[key] = None if evaluated is None else evaluated.score
            for _sel, cards in layer_jobs:
                key = score_key(cards)
                if key not in layer_scores:
                    break  # the budget ran out: the rest of the layer is unscored
                scores.append(layer_scores[key])
            layer_scores.clear()
        scored: list[tuple[tuple[int, ...], float]] = [
            (sel, score)
            for (sel, _cards), score in zip(layer_jobs, scores)
            if score is not None
        ]
        scored.sort(key=lambda item: (-item[1], tuple(pool[i].key for i in item[0])))
        # Beam 幸存者 + 全局最优候选在父进程重评估附 stats。
        for sel, _score in scored[: beam_width + 1]:
            evaluated = _evaluate(
                weapon,
                (*required_cards, *(pool[item] for item in sel)),
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                slot_limit=slot_count,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            if evaluated is not None:
                expanded.append((sel, evaluated))
        if not expanded:
            break
        expanded.sort(
            key=lambda item: (
                -item[1].score,
                tuple(pool[index].key for index in item[0]),
            )
        )
        beam = expanded[:beam_width]
        for _, evaluated in expanded:
            if eligible(evaluated) and (best is None or evaluated.score > best.score):
                best = evaluated
    if best is None:
        raise SimulationError(
            f"no capacity-valid build satisfies damage type {required_damage_type}"
        )
    # 数量下限（min_fill）：beam 结束时若可选卡不足 fill_floor（相对必选+紫卡
    # 之外的槽位），逐张补当前最优（保持容量合法；池已空则说明候选不足）。
    if fill_floor > 0:
        target_total = fill_floor + len(required_cards) + (1 if riven else 0)
        while len(best.cards) + (1 if riven else 0) < target_total:
            used_keys = {card.key for card in best.cards}
            used_families = {_mod_family(card) for card in best.cards}
            added = False
            for card in pool:
                if card.key in used_keys or _mod_family(card) in used_families:
                    continue
                filled = _evaluate(
                    weapon,
                    (*best.cards, card),
                    riven,
                    scenario=scenario,
                    metric=metric,
                    passives=passives,
                    slot_limit=slot_count,
                    capacity_limit=capacity_limit,
                    target_context=target_context,
                )
                if filled is not None and eligible(filled):
                    best = filled
                    added = True
                    break
            if not added:
                break
    # ── Full 1-swap neighbourhood hill-climb (wfsim optimizer/search.rs) ──────
    # After the beam pass the best build is locally refined by enumerating the
    # COMPLETE single-mod neighbourhood: swap one equipped card for one pool
    # card, add one, drop one — every candidate evaluated, keep the best,
    # repeat until no single move improves.  Measured by wfsim over its shipped
    # pools this reaches rank 1 with regret 0.000% where random mutation needs
    # 3000 evaluations for rank 10, because a beam's shortlist ordering is
    # greedy while a swap sees past it (the 8th-best card for the empty build
    # may be the best partner for the 7 already chosen).
    # ── F15（审计修复）：有序构建规范化去重 ──────────────────────────────
    # 元素合成顺序有意义（项目口径）：同一组卡不同顺序不是等价构建。
    # 旧实现 sig = tuple(sorted(card.key ...)) 把集合相同的顺序全部折叠，
    # 爬山会跳过「同卡不同序」的真实候选。现在 sig 保留卡序（tuple 原序），
    # 交换动作把新卡放进被移除卡的槽位（不再一律追加到末尾）。
    seen_keys: set[tuple[str, ...]] = {tuple(card.key for card in best.cards)}
    improved = True
    climb_guard = 0

    def _constraint_violation(candidate_cards: Sequence[_Card]) -> str | None:
        """F07：邻域变动的统一约束验证（必选/禁选/数量/容量）。"""
        return validate_build(
            candidate_cards,
            riven,
            slot_count=slot_count,
            capacity_limit=capacity_limit,
            required_mod_keys=required_mod_keys,
            forbidden_mod_keys=forbidden_mod_keys,
            min_fill=min_fill,
            max_fill=max_fill,
        )

    while improved and climb_guard < climb_rounds and not expired(deadline):
        improved = False
        climb_guard += 1
        base_cards = list(best.cards)
        base_optional = [c for c in base_cards if not c.required]
        best_score = best.score
        # Swap: replace one optional card with one pool card.  F15：新卡放进
        # 被移除卡的槽位（保持元素边界，不追加到末尾）。
        for drop_pos, dropped in enumerate(base_optional):
            for card in pool:
                if expired(deadline):
                    break
                if card.key in {c.key for c in base_cards}:
                    continue
                if _mod_family(card) in {
                    _mod_family(c) for c in base_cards if c.key != dropped.key
                }:
                    continue
                drop_index = base_cards.index(dropped)
                candidate_cards = list(base_cards)
                candidate_cards[drop_index] = card
                if _constraint_violation(candidate_cards):
                    continue
                sig = tuple(c.key for c in candidate_cards)
                if sig in seen_keys:
                    continue
                seen_keys.add(sig)
                evaluated = _evaluate(
                    weapon,
                    tuple(candidate_cards),
                    riven,
                    scenario=scenario,
                    metric=metric,
                    passives=passives,
                    slot_limit=slot_count,
                    capacity_limit=capacity_limit,
                    target_context=target_context,
                )
                if evaluated is not None and eligible(evaluated) and evaluated.score > best_score + 1e-9:
                    best, best_score = evaluated, evaluated.score
                    improved = True
        # Add: one more pool card while slots AND max_fill remain.
        # ── F07（审计修复）：Add 同时检查 slot_count 与 max_fill（旧实现
        # 只查 slot_count，beam 阶段的数量上限会被爬山的 Add 绕过）。
        if len(best.cards) + (1 if riven else 0) < slot_count and (
            max_fill is None
            or len(best.cards) + (1 if riven else 0) < int(max_fill)
        ):
            used_keys = {c.key for c in best.cards}
            used_families = {_mod_family(c) for c in best.cards}
            for card in pool:
                if card.key in used_keys or _mod_family(card) in used_families:
                    continue
                if _constraint_violation((*best.cards, card)):
                    continue
                sig = tuple(c.key for c in (*best.cards, card))
                if sig in seen_keys:
                    continue
                seen_keys.add(sig)
                evaluated = _evaluate(
                    weapon,
                    (*best.cards, card),
                    riven,
                    scenario=scenario,
                    metric=metric,
                    passives=passives,
                    slot_limit=slot_count,
                    capacity_limit=capacity_limit,
                    target_context=target_context,
                )
                if evaluated is not None and eligible(evaluated) and evaluated.score > best_score + 1e-9:
                    best, best_score = evaluated, evaluated.score
                    improved = True
                    break
        # Drop: remove one optional card (frees capacity for nothing — only
        # keeps builds whose score genuinely improves, e.g. set-bonus traps).
        # ── F07（审计修复）：Drop 检查 min_fill（数量下限不被绕过）。
        for dropped in base_optional:
            candidate_cards = [c for c in best.cards if c.key != dropped.key]
            if not candidate_cards:
                continue
            if _constraint_violation(candidate_cards):
                continue
            sig = tuple(c.key for c in candidate_cards)
            if sig in seen_keys:
                continue
            seen_keys.add(sig)
            evaluated = _evaluate(
                weapon,
                tuple(candidate_cards),
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                slot_limit=slot_count,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            if evaluated is not None and eligible(evaluated) and evaluated.score > best_score + 1e-9:
                best, best_score = evaluated, evaluated.score
                improved = True
        # ── F15（双槽交换，deep 档）───────────────────────────────────────
        # 成对协同替换：两个新卡必须一起换入才优于现状的组合（元素边界/容
        # 量再分配）是单卡邻域的盲区。仅在 deep 档执行（成本 O(n²) 评估，
        # 每轮最多 24 个最优对，预算受 climb_rounds 约束）。
        if profile == "deep" and len(base_optional) >= 2:
            pair_budget = 24
            pair_candidates: list[tuple[float, list[_Card]]] = []
            for first_pos in range(len(base_optional)):
                for second_pos in range(first_pos + 1, len(base_optional)):
                    dropped_a = base_optional[first_pos]
                    dropped_b = base_optional[second_pos]
                    for card_a in pool:
                        if card_a.key in {c.key for c in base_cards}:
                            continue
                        for card_b in pool:
                            if card_b.key in {c.key for c in base_cards} or card_b.key == card_a.key:
                                continue
                            if card_a.key == card_b.key:
                                continue
                            kept = [c for c in base_cards if c.key not in {dropped_a.key, dropped_b.key}]
                            candidate_cards = [*kept, card_a, card_b]
                            if _constraint_violation(candidate_cards):
                                continue
                            sig = tuple(c.key for c in candidate_cards)
                            if sig in seen_keys:
                                continue
                            seen_keys.add(sig)
                            evaluated = _evaluate(
                                weapon,
                                tuple(candidate_cards),
                                riven,
                                scenario=scenario,
                                metric=metric,
                                passives=passives,
                                slot_limit=slot_count,
                                capacity_limit=capacity_limit,
                                target_context=target_context,
                            )
                            if evaluated is not None and eligible(evaluated):
                                pair_candidates.append((evaluated.score, candidate_cards))
                                if len(pair_candidates) >= pair_budget * 8:
                                    break
                        if len(pair_candidates) >= pair_budget * 8:
                            break
                    if len(pair_candidates) >= pair_budget * 8:
                        break
                if len(pair_candidates) >= pair_budget * 8:
                    break
            pair_candidates.sort(key=lambda item: (-item[0], tuple(c.key for c in item[1])))
            for score_value, candidate_cards in pair_candidates[:pair_budget]:
                if score_value > best_score + 1e-9:
                    evaluated = _evaluate(
                        weapon,
                        tuple(candidate_cards),
                        riven,
                        scenario=scenario,
                        metric=metric,
                        passives=passives,
                        slot_limit=slot_count,
                        capacity_limit=capacity_limit,
                        target_context=target_context,
                    )
                    if evaluated is not None and eligible(evaluated) and evaluated.score > best_score + 1e-9:
                        best, best_score = evaluated, evaluated.score
                        improved = True
                        break
    # Fill otherwise-neutral slots as long as the loadout remains legal.  The
    # damage score alone cannot distinguish an empty slot from a useful utility
    # card whose modeled contribution is zero (range, ammo mutation, etc.).
    # 用户显式给出配卡数量范围时不做中性填充——尊重 min/max 语义。
    if (
        min_fill is None
        and max_fill is None
        and len(best.cards) + (1 if riven else 0) < slot_count
    ):
        used_keys = {card.key for card in best.cards}
        used_families = {_mod_family(card) for card in best.cards}
        for card in pool:
            family = _mod_family(card)
            if card.key in used_keys or family in used_families:
                continue
            filled = _evaluate(
                weapon,
                (*best.cards, card),
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                slot_limit=slot_count,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            if filled is None or not eligible(filled) or filled.score < best.score:
                continue
            best = filled
            used_keys.add(card.key)
            used_families.add(family)
            if len(best.cards) + (1 if riven else 0) >= slot_count:
                break
    # ── F07（审计修复）：最终输出统一验证。任何阶段的旁路（缓存候选、
    # beam、爬山、中性填充、floor）到这里都会被同一验证器拦截——不可行
    # 的构建宁可报错也不返回。
    final_violation = _constraint_violation(best.cards)
    if final_violation is not None:
        raise SimulationError(
            f"optimizer produced an infeasible build ({final_violation})"
        )
    return best


@memoized_search
def _best_fixed(
    weapon: Mapping[str, Any],
    base_cards: Sequence[_Card],
    riven: _Card,
    *,
    scenario: Scenario,
    metric: str,
    passives: _Card | None = None,
    capacity_limit: int = 60,
    target_context: Mapping[str, Any] | None = None,
    max_keep_cap: int | None = None,
    preserve_base: bool = False,
) -> _Evaluation:
    required = tuple(card for card in base_cards if card.required)
    optional = tuple(card for card in base_cards if not card.required)
    max_keep = min(len(optional), 7 - len(required))
    preserved = None
    if preserve_base:
        preserved = _evaluate(
            weapon, base_cards, riven, scenario=scenario, metric=metric,
            passives=passives, capacity_limit=capacity_limit,
            target_context=target_context,
        )
    # A search budget cannot mean forcibly deleting equipped mods. Start at
    # the largest legal subset (usually only 1 or 8 candidates), preserving
    # the available build and avoiding C(8,5) repeated replay explosions.
    for keep in range(max_keep, -1, -1):
        evaluated = [
            value
            for indexes in itertools.combinations(range(len(optional)), keep)
            if (value := _evaluate(
                weapon,
                (*required, *(optional[index] for index in indexes)),
                riven,
                scenario=scenario,
                metric=metric,
                passives=passives,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )) is not None
        ]
        if evaluated:
            candidate = max(evaluated, key=lambda value: value.score)
            if preserved is None:
                return candidate
            return max((preserved, candidate), key=lambda value: value.score)
    if preserved is not None:
        return preserved
    raise SimulationError("no capacity-valid build can equip the Riven")


def validate_build(
    cards: Sequence[_Card],
    riven: _Card | None,
    *,
    slot_count: int,
    capacity_limit: int,
    required_mod_keys: Sequence[str] | None = None,
    forbidden_mod_keys: Sequence[str] | None = None,
    min_fill: int | None = None,
    max_fill: int | None = None,
) -> str | None:
    """F07（审计修复）：统一可行域校验器。

    检查一份配卡（不含紫卡本体）是否满足请求的全部搜索约束：
    必选卡在场、禁选卡不在场、配卡数量范围（含紫卡与必选）、槽位与
    容量上限。返回 ``None`` 表示合法；返回字符串为拒绝原因。

    所有搜索阶段（种子、缓存候选、邻域变动、floor 修正、最终输出）
    都应通过同一验证器，约束不再依赖临时卡对象的 ``required`` 布尔
    标记（旧实现里用户必选卡进 ``required_cards`` 后没有标
    ``required=True``，爬山 Drop/Swap 仍可能把它当可移除卡删掉）。
    """
    keys = [card.key for card in cards]
    key_set = set(keys)
    if len(key_set) != len(keys):
        return "duplicate-mod"
    total = len(cards) + (1 if riven is not None else 0)
    if total > slot_count:
        return f"slot-count-{total}>{slot_count}"
    required = {str(key) for key in (required_mod_keys or ()) if str(key)}
    missing = required - key_set
    if missing:
        return "missing-required:" + ",".join(sorted(missing))
    forbidden = {str(key) for key in (forbidden_mod_keys or ()) if str(key)}
    present_forbidden = key_set & forbidden
    if present_forbidden:
        return "forbidden-mod:" + ",".join(sorted(present_forbidden))
    if min_fill is not None and total < int(min_fill):
        return f"under-min-fill-{total}<{int(min_fill)}"
    if max_fill is not None and total > int(max_fill):
        return f"over-max-fill-{total}>{int(max_fill)}"
    capacity = _capacity(list(cards) + ([riven] if riven is not None else []))
    if capacity > capacity_limit:
        return f"over-capacity-{capacity}>{capacity_limit}"
    return None


def _mark_required_cards(
    cards: Sequence[_Card], required_keys: Sequence[str]
) -> tuple[_Card, ...]:
    """F07：把用户必选卡物化为 ``required=True`` 的卡对象。

    爬山的 Swap/Drop 阶段按 ``card.required`` 判定可移除集合；用户必选
    卡必须进入该标记通道，否则 beam 之后的局部搜索可能把它删掉（旧
    实现的旁路之一）。返回新元组，不修改原卡对象。
    """
    required = {str(key) for key in required_keys if str(key)}
    if not required:
        return tuple(cards)
    return tuple(
        replace(card, required=True) if card.key in required else card
        for card in cards
    )


def theoretical_structure_scale(
    positive_count: int, has_negative: bool, *, negative: bool = False
) -> float:
    """紫卡词条结构的理论数值系数（官方 wiki 口径，与 app 层校验一致）。

    正面词条：2 正 = 1.0；3 正 = 0.757525；带 1 负面再 ×1.25。
    负面词条：3 正结构 = 0.757525；2 正结构 = 0.5（负面系数是独立档位，
    不等于正面系数 ×1.25——wiki 公式里负面按自己的档位取值）。
    """
    if negative:
        return 0.757525 if positive_count == 3 else 0.5
    scale = 0.757525 if positive_count == 3 else 1.0
    if has_negative:
        scale *= 1.25
    return scale


def _structure_full_roll_factor() -> float:
    """理论满值相对 nominal 的上浮系数（wiki：nominal × 1.089 为满值）。"""
    return 1.089


def _fusion_codes_from_templates(
    templates: Mapping[str, Any], weapon_type: str
) -> frozenset[str]:
    """Read advanced-trait availability; recipe completeness is separate."""
    return _available_fusion_codes(templates, weapon_type)



def _candidate_lines(
    weapon_type: str,
    disposition: float,
    actual: Sequence[_RivenLine],
    *,
    negative: bool,
    bases: Mapping[str, float] | None = None,
    structure_scale: float | None = None,
    available_fusion_codes: frozenset[str] | None = None,
) -> tuple[list[_RivenLine], bool]:
    bases = dict(bases or RIVEN_BASE_VALUES[weapon_type])
    ratios = []
    for line in actual:
        base = bases.get(line.code)
        if line.negative == negative and base and disposition > 0 and line.high > 0:
            ratios.append(line.high / (base * disposition))
    calibrated = bool(ratios)
    if structure_scale is not None:
        # 显式结构系数（理论口径）：3+1 求解/上限计算用，不依赖实际紫卡
        # 的 roll 指纹校准。×1.089 满值上浮（wiki：nominal × 1.089）。
        roll_scale = float(structure_scale) * _structure_full_roll_factor()
    elif ratios:
        roll_scale = median(ratios)
    else:
        positive_count = sum(not line.negative for line in actual)
        has_curse = any(line.negative for line in actual)
        # Widely used nominal structure factors; the response marks this fallback
        # as heuristic because the randomized fingerprint formula is not decoded.
        roll_scale = (
            theoretical_structure_scale(
                positive_count or 2, has_curse, negative=negative
            )
            * _structure_full_roll_factor()
        )

    lines: list[_RivenLine] = []
    # Candidate availability follows advanced-trait templates, not recipe coverage.
    for code, base in bases.items():
        rule = RIVEN_RULES.get(code)
        if rule is None:
            continue
        can_roll = rule[8] if negative else rule[7]
        if not can_roll:
            continue
        if (
            code in _FUSION_LINE_CODES
            and available_fusion_codes is not None
            and code not in available_fusion_codes
        ):
            continue
        value = base * disposition * roll_scale
        effect = _effect_from_code(
            code, value, negative=negative, source=f"riven:theoretical:{code}"
        )
        lines.append(
            _RivenLine(
                code=code,
                label=rule[0],
                value=value,
                low=0.0,
                high=value,
                negative=negative,
                unit=rule[5],
                effect=effect,
            )
        )
    return lines, calibrated


def _neutral_negative_codes(weapon: Mapping[str, Any]) -> frozenset[str]:
    """Negative affixes that are neutral under the current scoring model.

    These are deliberately model-scoped: zoom, reserve ammo, recoil and the
    slide-crit gate are not represented by the single-target damage reducer.
    They must be preferred over damage-reducing negatives when a Riven solver
    is choosing a 3+1 structure, but they are not claimed to be universally
    harmless in every live gameplay situation.
    """
    slot = str(weapon.get("slot") or "").casefold()
    if slot in MELEE_SLOTS:
        return frozenset({"X", "E"})
    return frozenset({"Z", "H", "M", "E"})


def _recommend_positive(
    weapon: Mapping[str, Any],
    baseline: _Evaluation,
    candidates: Sequence[_RivenLine],
    count: int,
    *,
    scenario: Scenario,
    metric: str,
    passives: _Card | None = None,
    capacity_limit: int = 60,
    target_context: Mapping[str, Any] | None = None,
    profile: str = "deep",
    extra_bases: Sequence[Sequence[_Card]] = (),
) -> tuple[list[_RivenLine], _Evaluation, list[dict[str, Any]]]:
    # 档位缩水（wfsim 优化器预算思想的移植）：
    #   fast     — 单词条粗排后直接取头部组合，跳过组合枚举与边际贡献分层，
    #               tiers 退化为按单词条粗排分数归一化（仍然给出 T0–T3 标签）。
    #   standard — 单词条粗排 + 头部组合枚举（shortlist 8）+ 边际贡献，
    #               _best_fixed 的子集枚举上限压到 5（2^5=32 而非 2^7=128）。
    #   deep     — 完整口径（现状）。
    # No wall-clock cutoff: these rankings are weapon-level statics shared by
    # every card, so they must not depend on machine load.
    deadline = float("inf")
    keep_cap = {"fast": 3, "standard": 5, "deep": None}[profile]
    # Archetype bases: a stat is worth what the build that uses it best makes
    # of it. Scoring every line on the no-Riven optimum alone undervalues
    # stats that would flip the build (status on a direct base, or reverse).
    bases: list[tuple[_Card, ...]] = [tuple(baseline.cards)]
    for extra in extra_bases:
        if tuple(extra) not in bases:
            bases.append(tuple(extra))

    def fit(riven_card: _Card) -> _Evaluation:
        best: _Evaluation | None = None
        for base in bases:
            try:
                result = _best_fixed(
                    weapon, base, riven_card, scenario=scenario, metric=metric,
                    passives=passives, capacity_limit=capacity_limit,
                    target_context=target_context, max_keep_cap=keep_cap,
                )
            except SimulationError:
                continue
            if best is None or result.score > best.score:
                best = result
        if best is None:
            raise SimulationError("no capacity-valid build can equip the Riven")
        return best

    # ── 单词条粗排并行化（每词条一次 _best_fixed 的子集枚举——40+ 次
    # 独立的重量评估；物理核 worker 池，串行回退）──────────────────────
    _supported_lines = [
        line for line in candidates
        if line.effect is not None and line.effect.supported
    ]
    _line_scores: list[float | None] | None = None
    from wfarsenal import parallel as _parallel

    _wire_scenario = (
        scenario
        if isinstance(scenario.conditional_stacks, dict)
        else replace(scenario, conditional_stacks=dict(scenario.conditional_stacks))
    )
    _pool_ctx = {
        "weapon": weapon,
        "scenario": _wire_scenario,
        "metric": metric,
        "passives": passives,
        "slot_limit": 8,
        "capacity_limit": capacity_limit,
        "target_context": target_context,
    }
    _pool_exec = _parallel.get_pool()
    if _pool_exec is not None and len(_supported_lines) >= 4:
        _futures = {
            line.code: [
                _pool_exec.submit(
                    _parallel._best_fixed_job,
                    (base, _card_from_lines([line]), keep_cap, _pool_ctx),
                )
                for base in bases
            ]
            for line in _supported_lines
        }
        _line_scores = []
        for line in _supported_lines:
            values = [value for value in (future.result() for future in _futures[line.code]) if value is not None]
            _line_scores.append(max(values) if values else None)

    ranked: list[tuple[float, _RivenLine]] = []
    if _line_scores is not None:
        for line, score in zip(_supported_lines, _line_scores):
            if score is not None:
                ranked.append((score, line))
    else:
        for line in _supported_lines:
            try:
                result = fit(_card_from_lines([line]))
            except SimulationError:
                # 与并行口径一致：单词条无可行配装时跳过（worker 侧
                # 捕获后返回 None）。
                continue
            ranked.append((result.score, line))
    ranked.sort(key=lambda item: (-item[0], item[1].code))
    shortlist = [line for _, line in ranked[: max(8, count)]]
    if len(shortlist) < count:
        raise SimulationError("not enough supported Riven stats for this weapon")
    best_lines: tuple[_RivenLine, ...] | None = None
    best_result: _Evaluation | None = None
    if profile == "fast":
        # 头部组合 = 粗排前 count 名直接组合，不枚举 C(8,count)。
        # 融合词条每卡限 1 条：跳过第二条及以后的融合词条顺延取非融合。
        fast_combo: list[_RivenLine] = []
        fusion_used = False
        for line in shortlist:
            if len(fast_combo) >= count:
                break
            if line.code in _FUSION_LINE_CODES:
                if fusion_used:
                    continue
                fusion_used = True
            fast_combo.append(line)
        best_lines = tuple(fast_combo)
        best_result = fit(_card_from_lines(best_lines))
    else:
        for combo in itertools.combinations(shortlist, count):
            if best_result is not None and expired(deadline):
                break
            # 融合词条每卡限 1 条（游戏规则）：含 2+ 融合的组合非法。
            if not _combo_allows_fusion(combo):
                continue
            result = fit(_card_from_lines(combo))
            if best_result is None or result.score > best_result.score:
                best_lines, best_result = combo, result
    assert best_lines is not None and best_result is not None

    # Score each affix in a full-card context. A one-line Riven can lose to the
    # mod slot it replaces even when that affix is valuable on a complete card.
    # 快速档跳过边际贡献阶段：单词条粗排已有分数，直接归一化出分层。
    marginal: list[tuple[float, _RivenLine]] = []
    if profile == "fast" or expired(deadline):
        # 单词条分数相对「同一基装配紫卡（空词条组）」归一化：粗排口径，
        # 分层只作参考（无组合上下文），但零组合枚举成本。
        bare_base = fit(_card_from_lines([]))
        for score, line in ranked:
            gain = _percent_gain(score, bare_base.score)
            if gain > 0:
                marginal.append((gain, line))
        marginal.sort(key=lambda item: (-item[0], item[1].code))
    else:
        anchor_results: dict[tuple[str, ...], _Evaluation] = {}
        for _, line in ranked:
            anchor = tuple(item for item in best_lines if item.code != line.code)[: count - 1]
            if len(anchor) < count - 1:
                anchor = tuple(best_lines[: count - 1])
            anchor_key = tuple(item.code for item in anchor)
            without = anchor_results.get(anchor_key)
            if without is None:
                without = fit(_card_from_lines(anchor))
                anchor_results[anchor_key] = without
            with_line = fit(_card_from_lines((*anchor, line)))
            gain = _percent_gain(with_line.score, without.score)
            if gain > 0:
                marginal.append((gain, line))
        marginal.sort(key=lambda item: (-item[0], item[1].code))
    best_gain = marginal[0][0] if marginal else 0.0
    tiers: list[dict[str, Any]] = []
    for tier, ceiling, floor in (
        ("T0", math.inf, 80.0),
        ("T1", 80.0, 60.0),
        ("T2", 60.0, 40.0),
        ("T3", 40.0, 0.0),
    ):
        stats = []
        for gain, line in marginal:
            score = gain / best_gain * 100.0
            if floor <= score < ceiling:
                stats.append(
                    {"code": line.code, "label": line.label, "gain": gain, "score": score}
                )
                if len(stats) == 3:
                    break
        if stats:
            tiers.append({"tier": tier, "stats": stats})
    return list(best_lines), best_result, tiers


# ── 最优紫卡词条求解（anytime 预算驱动）────────────────────────────────
# 用户在配装页紫卡构建器请求「计算最优」：在当前武器/基准配装的语境下，
# 搜出 KPM 最高的紫卡词条组合（2-3 正 + 0-1 负，理论满数值口径），
# 返回 top-N。预算由调用方传入（用户选 10/20/30/60 秒），算法分三阶段
# 单调改进，时间耗尽即返回当前最优——结果完整性随预算增加而提高。

def _riven_combo_key(lines: Sequence[_RivenLine]) -> tuple[str, ...]:
    return tuple(sorted(('-' if line.negative else '+') + line.code for line in lines))


def recommend_optimal_riven(
    weapon: Mapping[str, Any],
    baseline: _Evaluation,
    positive_candidates: Sequence[_RivenLine],
    negative_candidates: Sequence[_RivenLine],
    *,
    scenario: Scenario,
    metric: str,
    passives: _Card | None = None,
    capacity_limit: int = 60,
    target_context: Mapping[str, Any] | None = None,
    budget_seconds: float = 10.0,
    top_limit: int = 10,
    slot_count: int = 8,
    min_fill: int | None = None,
    max_fill: int | None = None,
    required_damage_type: str | None = None,
    special_cards: Sequence[_Card] = (),
    special_capacity_cost: int = 0,
) -> dict[str, Any]:
    from .riven_recommendation import recommend
    return recommend(weapon, baseline, positive_candidates, negative_candidates,
        scenario=scenario, metric=metric, passives=passives, capacity_limit=capacity_limit,
        target_context=target_context, budget_seconds=budget_seconds, top_limit=top_limit,
        slot_count=slot_count, min_fill=min_fill, max_fill=max_fill,
        required_damage_type=required_damage_type, special_cards=special_cards,
        special_capacity_cost=special_capacity_cost)


def _metric(requested: Any, weapon_type: str) -> tuple[str, str | None]:
    raw = str(requested or "").strip()
    aliases = {
        "": "attackDps" if weapon_type == "melee" else "sustainedDps",
        "sustained": "sustainedDps",
        "sustained_dps": "sustainedDps",
        "burst": "burstDps",
        "burst_dps": "burstDps",
        "shot": "shotDamage",
        "normal": "attackDps",
        "heavy": "heavyAttackDps",
        "heavy_attack": "heavyAttackDps",
    }
    metric = aliases.get(raw.casefold(), raw)
    allowed = {
        "shotDamage",
        "burstDps",
        "sustainedDps",
        "attackDps",
        "heavyAttackDps",
        "heavyDamage",
    }
    if metric not in allowed:
        fallback = "attackDps" if weapon_type == "melee" else "sustainedDps"
        return fallback, f"unknown-metric-{raw}-using-{fallback}"
    if weapon_type != "melee" and metric in {
        "attackDps",
        "heavyAttackDps",
        "heavyDamage",
    }:
        return "sustainedDps", f"metric-{metric}-requires-melee"
    return metric, None


def _objective_metric(metric: str) -> str:
    return "heavyDamage" if metric in {"heavyAttackDps", "heavyDamage"} else metric


def _scenario(metric: str, *, incarnon_cycle: bool = False, aiming: bool = False) -> Scenario:
    return Scenario(
        heavy_attack=metric in {"heavyAttackDps", "heavyDamage"},
        incarnon_cycle=incarnon_cycle,
        aiming=aiming,
        trigger_policy="emergent",
    )


def _requested_scenario(request: Mapping[str, Any], metric: str) -> Scenario:
    """Shared public request parser for builds, manual replay and Riven analysis.

    Nested explicit values win, including false/0/null. Distance remains damage
    falloff/arming input; deferred spread is never consulted here.
    """
    nested = request.get('scenario')
    if nested is not None and not isinstance(nested, Mapping):
        raise SimulationError('scenario must be an object')
    nested = nested or {}
    if 'conditionalStacks' in request or 'conditionalStacks' in nested:
        raise SimulationError('conditionalStacks is derived from equipped MODs and cannot be overridden')
    def value(key, default=None):
        return nested.get(key, request.get(key, default))
    def boolean(key):
        raw = value(key, False)
        if not isinstance(raw, bool):
            raise SimulationError(f'{key} must be a boolean')
        return raw
    def distance(key):
        raw = value(key)
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw < 0:
            raise SimulationError(f'{key} must be a finite non-negative number')
        return float(raw)
    combo = value('comboTier', 0)
    if isinstance(combo, bool) or not isinstance(combo, int) or not 0 <= combo <= 11:
        raise SimulationError('comboTier must be an integer between 0 and 11')
    policy = str(value('triggerPolicy', 'emergent') or 'emergent')
    if policy not in {'emergent', 'assumed_max'}:
        raise SimulationError('triggerPolicy must be emergent or assumed_max')
    delay = distance('detonationDelaySeconds')
    batch = value('detonationBatchSize', 1)
    if isinstance(batch, bool) or not isinstance(batch, int) or not 1 <= batch <= 8:
        raise SimulationError('detonationBatchSize must be an integer between 1 and 8')
    try:
        return Scenario(aiming=boolean('aiming'), incarnon_cycle=boolean('incarnonCycle'),
            heavy_attack=boolean('heavyAttack') or _scenario(metric).heavy_attack,
            distance=distance('distance'), nearest_enemy_distance=distance('nearestEnemyDistance'),
            cloaked=boolean('cloaked'), combo_tier=combo, trigger_policy=policy,
            detonation_delay_seconds=delay or 0., detonation_batch_size=batch,
            combat_state=value('combatState',{}))
    except (TypeError,ValueError) as exc:
        raise SimulationError(str(exc)) from exc


def _scenario_context(scenario: Scenario) -> dict[str, Any]:
    return dict(aiming=scenario.aiming, incarnonCycle=scenario.incarnon_cycle,
                heavyAttack=scenario.heavy_attack, triggerPolicy=scenario.trigger_policy,
                distance=scenario.distance, cloaked=scenario.cloaked,
                nearestEnemyDistance=scenario.nearest_enemy_distance, comboTier=scenario.combo_tier,
                detonationDelaySeconds=scenario.detonation_delay_seconds,
                detonationBatchSize=scenario.detonation_batch_size,
                combatState=dict(scenario.combat_state))


def _default_analysis_scenario(scenario: Scenario, metric: str) -> bool:
    # Existing baked statics describe only this state. Non-default scenarios must
    # not read them, including the fallback that only changes enemy level.
    # Melee route / stance keys are part of the cache key (benchmark "melee").
    state = {k: v for k, v in scenario.combat_state.items() if not str(k).startswith("melee")}
    return _scenario_context(replace(scenario, combat_state=state)) == _scenario_context(_scenario(metric))


def _percent_gain(value: float, baseline: float) -> float:
    return (value / baseline - 1.0) * 100.0 if baseline > 0 else 0.0


def _statics_weapon_identity(weapon: Mapping[str, Any]) -> str:
    """Cache identity of a weapon record: an assembled Kitgun / Zaw adds its parts.

    Assemblies share their base record's path (every Zaw is LotusModularWeapon),
    so the path alone would let one assembly read another's baked statics.
    """
    path = str(weapon.get("path") or "")
    parts = weapon.get("kitgunParts") or weapon.get("zawParts")
    if not parts:
        return path
    return path + "#" + "+".join(sorted(str(part) for part in parts))


def _statics_cache_key(
    weapon_path: Any,
    innate_elements: Any,
    fire_mode: int,
    element_target: str,
    profile: str,
    disposition: float,
    capacity_limit: int,
    metric: str,
    benchmark: Mapping[str, Any] | None,
    *,
    scoring_level: int | None = None,
) -> str:
    """Return a canonical key for one complete static-analysis context.

    The old key omitted disposition and several target toggles.  That allowed
    a result baked for one target/weapon context to be reused for another one
    whenever the first few textual fields happened to match.
    """
    raw = benchmark if isinstance(benchmark, Mapping) else {}
    benchmark_key = {
        "enemy": raw.get("enemy") or raw.get("path") or "-",
        "level": scoring_level if scoring_level is not None else raw.get("level"),
        "steelPath": bool(raw.get("steelPath")),
        "eximus": bool(raw.get("eximus")),
        "archimedea": bool(raw.get("archimedea")),
        "empowered": bool(raw.get("empowered")),
        "armourStrip": raw.get("armourStrip", 0.0),
        "elementalArmourStrip": raw.get("elementalArmourStrip", 0.0),
        "headshotChance": raw.get("headshotChance", 0.0),
        "hitLocation": raw.get("hitLocation", "body"),
        "stanceMultiplier": raw.get("stanceMultiplier", 1.0),
        "statusRateMultiplier": raw.get("statusRateMultiplier", 1.0),
        "heavyAttack": bool(raw.get("heavyAttack")),
        "windowSeconds": raw.get("windowSeconds", 30.0),
        "enemyEnhancements": raw.get("enemyEnhancements"),
        "playerCount": raw.get("playerCount", 1),
        "eventScoringVersion": "loadout-events-v1",
    }
    if raw.get("scenario"):
        # Only non-default (preset) scenarios carry this, so default-scenario
        # keys and existing caches are unchanged.
        benchmark_key["scenario"] = raw["scenario"]
    if raw.get("melee"):
        benchmark_key["melee"] = raw["melee"]
    return json.dumps(
        {
            "weapon": str(weapon_path or ""),
            "fireMode": int(fire_mode),
            "innateElements": innate_elements or (),
            "elementTarget": element_target or "-",
            "profile": profile,
            "disposition": round(float(disposition), 8),
            "capacityLimit": int(capacity_limit),
            "metric": metric,
            "calibrationVersion": TARGET_CALIBRATION_VERSION,
            "benchmark": benchmark_key,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _evaluation_context_hash(context: Mapping[str, Any]) -> str:
    """Hash the complete immutable context used for baseline/actual/bestFound."""
    payload = json.dumps(
        context,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def _quality(line: _RivenLine) -> float:
    if line.high <= line.low:
        return 0.0
    quality = (line.value - line.low) / (line.high - line.low) * 100.0
    if line.negative:
        quality = 100.0 - quality
    return max(0.0, min(100.0, quality))


def _grade(score: float) -> str:
    for threshold, grade in (
        (90, "EX"),
        (80, "S+"),
        (70, "S"),
        (60, "A"),
        (50, "B"),
        (40, "C"),
        (30, "D"),
        (20, "E"),
    ):
        if score >= threshold:
            return grade
    return "F"


def _apply_selected(
    weapon: Mapping[str, Any],
    evaluation: _Evaluation,
    riven: _Card | None,
    scenario: Scenario,
    passives: _Card | None = None,
) -> Any:
    return apply_mods(
        weapon,
        _selected_effects(evaluation, riven, scenario, passives),
        scenario=scenario,
    )


def _selected_effects(
    evaluation: _Evaluation,
    riven: _Card | None,
    scenario: Scenario,
    passives: _Card | None = None,
) -> ModEffectList:
    ordered = list(evaluation.cards)
    if riven is not None:
        ordered.insert(evaluation.riven_index if evaluation.riven_index is not None else len(ordered), riven)
    resolved: list[_Card] = [passives] if passives is not None else []
    for card in ordered:
        if card.record is not None:
            current = mod_effects(
                card.record,
                card.rank,
                _steady_state_scenario((card.record,), scenario),
            )
            card = replace(
                card,
                effects=tuple(current),
                skipped=tuple(current.skipped),
            )
        resolved.append(card)
    return _effects(resolved, scenario)


def _alternate_mode_payloads(
    weapon: Mapping[str, Any],
    evaluation: _Evaluation,
    riven: _Card | None,
    passives: _Card | None = None,
    *,
    selected_fire_mode: int = 0,
) -> list[dict[str, Any]]:
    from .event_profiles import is_incarnon_mode
    if _weapon_type(None, weapon) == "melee":
        return []
    effects = _selected_effects(evaluation, riven, Scenario(), passives)
    result: list[dict[str, Any]] = []
    all_modes = weapon.get("fireModes") or ()
    mode_count = len(all_modes)
    for index, mode in enumerate(all_modes):
        if index == selected_fire_mode:
            continue
        if not isinstance(mode, Mapping) or not mode.get("trigger"):
            continue
        payload: dict[str, Any] = {
            "fireMode": index,
            "trigger": mode.get("trigger"),
            "isAlternateFire": bool(mode.get("isAlternateFire")),
            "isIncarnonForm": is_incarnon_mode(weapon,index),
        }
        unsupported: list[str] = []
        events: dict[str, Any] | None = None
        try:
            events = evaluate_projectile_events(
                weapon, effects, fire_mode=index, scenario=Scenario()
            )
        except (TypeError, ValueError) as exc:
            unsupported.append(f"alternate-fire-mode-{index}-events-unavailable: {exc}")
        try:
            stats = apply_mods(weapon, effects, fire_mode=index)
        except (TypeError, ValueError) as exc:
            unsupported.append(f"alternate-fire-mode-{index}-stats-unavailable: {exc}")
        else:
            metrics = _metrics(stats, events)
            payload.update(
                shotDamage=metrics["shotDamage"],
                burstDps=metrics["burstDps"],
                sustainedDps=metrics["sustainedDps"],
                attackDps=metrics["attackDps"],
            )
            unsupported.extend(stats.unsupported)
        if events is not None:
            payload["projectileEvents"] = events
            safe_hit = (
                (events.get("totals") or {})
                .get("averageHit", {})
                .get("minimum", 0.0)
            )
            if (
                "shotDamage" not in payload
                and isinstance(safe_hit, (int, float))
                and not isinstance(safe_hit, bool)
                and safe_hit > 0
            ):
                payload["shotDamage"] = float(safe_hit)
            if safe_hit:
                payload["damageBasis"] = "projectileEvents.minimum"
        if unsupported:
            payload["unsupported"] = sorted(set(unsupported))
        if any(
            key in payload
            for key in ("shotDamage", "burstDps", "sustainedDps", "attackDps")
        ):
            result.append(payload)
    return result


def _build_payload(
    weapon: Mapping[str, Any],
    evaluation: _Evaluation,
    riven: _Card | None,
    passives: _Card | None = None,
) -> dict[str, Any]:
    normal_scenario = replace(evaluation.scenario, heavy_attack=False)
    normal_effects = _selected_effects(
        evaluation, riven, normal_scenario, passives
    )
    normal = apply_mods(weapon, normal_effects, scenario=normal_scenario)
    projectile_events = evaluate_projectile_events(
        weapon, normal_effects, scenario=normal_scenario
    )
    heavy = _apply_selected(
        weapon,
        evaluation,
        riven,
        replace(evaluation.scenario, heavy_attack=True),
        passives,
    )
    normal_metrics = _metrics(normal, projectile_events)
    heavy_metrics = _metrics(heavy)
    mods = []
    set_counts: dict[str, int] = {}
    for card in evaluation.cards:
        if card.record is not None and (set_id := _set_key(card.record.get("modSet"))):
            set_counts[set_id] = set_counts.get(set_id, 0) + 1
    for card_index, card in enumerate(evaluation.cards):
        assert card.record is not None
        set_id = _set_key(card.record.get("modSet"))
        pieces = set_counts.get(set_id, 0)
        display_effects = []
        multiplier = _buff_set_multiplier(card.record, pieces) if pieces else 1.0
        for effect in card.effects:
            if not effect.supported or _qualifier_rejection(effect, weapon, normal_scenario):
                continue
            value = effect.value * multiplier
            if effect.upgrade_type == "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE":
                value *= evaluation.scenario.victim_status_count
            display_effects.append(
                {
                    "upgradeType": effect.upgrade_type,
                    "damageType": effect.damage_type,
                    "operation": effect.operation,
                    "value": value,
                }
            )
        steady_stacks = []
        for conditional in card.record.get("conditionalEffects") or ():
            if not isinstance(conditional, Mapping):
                continue
            tag = str(conditional.get("conditionTag") or "")
            max_stacks = conditional.get("maxStacks")
            if "killcondition" in tag.casefold() and isinstance(max_stacks, int):
                steady_stacks.append({"conditionTag": tag, "stacks": max_stacks})
        mods.append(
            {
                **record_identity(card.record),
                "rank": card.rank,
                "slot": card_index + int(riven is not None and card_index >= evaluation.riven_index),
                "maxRank": card.record.get("maxRank"),
                "compatibility": card.record.get("compatibility"),
                "compatibilityTags": list(card.record.get("compatibilityTags") or ()),
                "compatible": True,
                "displayEffects": display_effects,
                **({"setPieces": pieces} if set_id else {}),
                **({"steadyStacks": steady_stacks} if steady_stacks else {}),
            }
        )
    safe_event_hit = (
        ((projectile_events or {}).get("totals") or {})
        .get("averageHit", {})
        .get("minimum", 0.0)
    )
    unsupported_set = {
        *normal.unsupported,
        *heavy.unsupported,
        *evaluation.stats.unsupported,
        *((projectile_events or {}).get("unsupported") or ()),
    }
    if isinstance(safe_event_hit, (int, float)) and safe_event_hit > 0:
        unsupported_set.discard("projectile-component-damage-unapplied")
    unsupported = sorted(unsupported_set)
    heavy_route = weapon.get("heavyAttack")
    heavy_support = (
        dict(heavy_route.get("support") or {})
        if isinstance(heavy_route, Mapping)
        and isinstance(heavy_route.get("support"), Mapping)
        else None
    )
    if heavy_support is not None and unsupported:
        # Route metadata is static, while these reasons are build/effect specific.
        # Keep them together so offline consumers can explain a partial snapshot.
        heavy_support["reasons"] = list(
            dict.fromkeys(
                [*(heavy_support.get("reasons") or ()), *unsupported]
            )
        )
    result = {
        "mods": mods,
        "includesRiven": riven is not None,
        "victimStatusCount": evaluation.scenario.victim_status_count,
        "shotDamage": normal_metrics["shotDamage"],
        "burstDps": normal_metrics["burstDps"],
        "sustainedDps": normal_metrics["sustainedDps"],
        "attackDps": normal_metrics["attackDps"],
        "heavyDamage": heavy_metrics["heavyDamage"],
        "heavyComponents": heavy.heavy_components,
        "heavySupport": heavy_support,
        # Legacy wire field. New callers should use heavyDamage.
        "heavyAttackDps": heavy_metrics["heavyDamage"],
        "unsupported": unsupported,
    }
    if riven is not None:
        result['riven'] = {
            'slot':evaluation.riven_index,
            'polarity': riven.polarity,
            'stats':[{'code':line.code,'value':line.value,'negative':line.negative} for line in riven.riven_lines],
        }
        result["rivenLines"] = [
            {
                "code": line.code,
                "label": line.label,
                "value": line.value,
                "low": line.low,
                "high": line.high,
                "negative": line.negative,
                "unit": line.unit,
            }
            for line in riven.riven_lines
        ]
    if projectile_events is not None:
        result["projectileEvents"] = projectile_events
        if isinstance(safe_event_hit, (int, float)) and safe_event_hit > 0:
            result["damageBasis"] = "projectileEvents.minimum"
    return result


def _requested_timeline_seconds(request: Mapping[str, Any]) -> float | None:
    value = request.get("timelineSeconds")
    if value is None:
        arcanes = request.get("arcanes")
        if not isinstance(arcanes, list) or not any(
            isinstance(item, Mapping) and item.get("triggerRate") is not None
            for item in arcanes
        ):
            return None
        return 10.0
    seconds = _number("timeline seconds", value)
    if not 0 < seconds <= 300:
        raise SimulationError("timeline seconds must be greater than zero and at most 300")
    return seconds


def _arcane_timeline(
    records: Sequence[Mapping[str, Any]],
    requested_arcanes: Any,
    weapon: Mapping[str, Any],
    incarnon: _Card | None,
    baseline: _Evaluation,
    actual: _Evaluation,
    optimal: _Evaluation,
    actual_riven: _Card,
    optimal_riven: _Card,
    *,
    scenario: Scenario,
    metric: str,
    seconds: float,
) -> dict[str, Any]:
    point_count = 41
    step = seconds / (point_count - 1)
    cumulative = [0.0, 0.0, 0.0]
    previous: list[float] | None = None
    points: list[dict[str, Any]] = []
    for index in range(point_count):
        elapsed = seconds if index == point_count - 1 else index * step
        arcane, states, _ = _arcane_card(
            records, requested_arcanes, weapon, elapsed=elapsed
        )
        passives = _merge_passives(incarnon, arcane)
        values = []
        for evaluation, riven in (
            (baseline, None),
            (actual, actual_riven),
            (optimal, optimal_riven),
        ):
            effects = _selected_effects(evaluation, riven, scenario, passives)
            stats = apply_mods(weapon, effects, scenario=scenario)
            events = evaluate_projectile_events(
                weapon, effects, scenario=scenario
            )
            values.append(_score(stats, metric, events))
        if previous is not None:
            for value_index in range(3):
                cumulative[value_index] += (
                    previous[value_index] + values[value_index]
                ) * step / 2.0
        previous = values
        points.append(
            {
                "time": elapsed,
                "baselineDps": values[0],
                "actualDps": values[1],
                "optimalDps": values[2],
                "baselineDamage": cumulative[0],
                "actualDamage": cumulative[1],
                "optimalDamage": cumulative[2],
                "arcanes": [
                    {
                        "query": state["query"],
                        "expectedStacks": state["expectedStacks"],
                        "uptime": state["expectedUptime"],
                    }
                    for state in states
                ],
            }
        )
    return {
        "model": "expected-objective-dps-envelope",
        "durationSeconds": seconds,
        "points": points,
        "assumptions": [
            "trigger events follow a Poisson process at each supplied triggerRate",
            "Arcane stack expiry uses a capped duration-window approximation",
            "selected mods stay fixed at the steady-state optimum",
            "individual shots, reload gaps, target defenses and status ticks are not scheduled",
        ],
    }


@session_request
def analyze_riven_request(
    export_dir: str | Path,
    request: Mapping[str, Any],
    weapon_record: Mapping[str, Any] | None = None,
    stance: Mapping[str, Any] | None = None,
    statics_cache: dict[str, Any] | None = None,
    progress_hook: Any = None,
) -> dict[str, Any]:
    """Score one wire-format Riven and return baseline/actual/optimal builds.

    面板口径（不挂固定目标，避免派系歧视卡扭曲配卡与词条推荐）：枪械主指标
    为目标中立的「触发+直伤合计持续 DPS」，并给出「触发 / 直伤」双路推荐
    词条（8 槽预留紫卡位，两条路线都是含紫卡口径，用于比较同一张紫卡下
    触发配卡还是直伤配卡伤害更高）；近战/组合近战默认使用普通攻击 DPS
    倍率最高的架势（容量收益计入解算），投掷重击维持重击口径。
    weapon_record 可传入预先装配好的组合枪/组合近战记录，缺省按路径解析；
    stance 传入与配装页同口径的架势信息；statics_cache 为按武器缓存的静态
    解算结果（基准配装/双路推荐/理论上限），组合装配、显式灵化/赋能与时间线
    请求不读不写缓存。

    progress_hook(stage: str)：阶段边界回调（"baseline" / "calibration" /
    "actual" / "recommendation" / "optimal" / "quality" / "payload"），
    供 HTTP 层向前端报告分析进度；None 时零开销。
    """
    def _progress(stage: str) -> None:
        if SESSION.get() is not None:
            SESSION.get()['stage'] = stage
        if progress_hook is not None:
            try:
                progress_hook(stage)
            except Exception:
                # 进度上报绝不影响解算。
                pass

    if not isinstance(request, Mapping):
        raise SimulationError("riven request must be a JSON object")
    record_overridden = weapon_record is not None
    exports = load_exports(export_dir)
    weapon_query = str(request.get("weapon") or "").strip()
    if weapon_record is None and not weapon_query:
        raise SimulationError("riven request weapon is empty")
    if weapon_record is not None and not isinstance(weapon_record, Mapping):
        raise SimulationError("weapon record override must be an object")
    weapon_record = (
        dict(weapon_record)
        if weapon_record is not None
        else resolve_record(exports["weapons"], weapon_query, kind="weapon")
    )
    requested_type = request.get("weaponType")
    if requested_type not in (None, "") and not isinstance(requested_type, str):
        raise SimulationError("weaponType must be a string")
    weapon_type = _weapon_type(request.get("weaponType"), weapon_record)
    inferred_type = _weapon_type(None, weapon_record)
    statics_weapon = _statics_weapon_identity(weapon_record)
    riven_type = _riven_type(request.get("weaponType"), weapon_record)
    if requested_type not in (None, "") and weapon_type != inferred_type:
        raise SimulationError(
            f"weaponType {weapon_type} does not match exported weapon type {inferred_type}"
        )
    requested_choices = request.get("incarnonChoices")
    if requested_choices is not None:
        if not isinstance(requested_choices, Mapping):
            raise SimulationError("incarnonChoices must be an object")
        for key, value in requested_choices.items():
            tier = _tier_number(key)
            if tier not in {2, 3, 4, 5}:
                raise SimulationError(
                    f"incarnon choice tier {key!r} must select Evo II, III, IV or V"
                )
            if not isinstance(value, str) or not value.strip():
                raise SimulationError("incarnon choices require non-empty string values")
    requested_fire_mode = request.get("fireMode")
    if requested_fire_mode is not None:
        _select_fire_mode(
            weapon_record, requested_fire_mode, weapon_type=weapon_type
        )
    # 灵化武器的主用形态是灵化形态（导出中恒为最后一个开火模式），
    # 分析与配卡默认挂灵化形态，与黑猫口径一致；显式 fireMode 可覆盖。
    _available_modes = weapon_record.get("fireModes") or ()
    default_fire_mode = (
        len(_available_modes) - 1
        if requested_fire_mode is None
        and weapon_record.get("isIncarnon")
        and len(_available_modes) > 1
        else 0
    )
    weapon, fire_mode = _select_fire_mode(
        weapon_record,
        requested_fire_mode if requested_fire_mode is not None else default_fire_mode,
        weapon_type=weapon_type,
    )
    heavy_route = weapon.get("heavyAttack")
    throw_components = [
        component
        for component in (
            heavy_route.get("components") or ()
            if isinstance(heavy_route, Mapping)
            else ()
        )
        if isinstance(component, Mapping)
        and component.get("kind") in {"projectileDirect", "heavyRecall"}
    ]
    throwable = (
        weapon_type == "melee"
        and isinstance(heavy_route, Mapping)
        and heavy_route.get("kind") == "projectileRecall"
        and {"projectileDirect", "heavyRecall"}
        <= {component.get("kind") for component in throw_components}
    )
    if throwable:
        weapon = {
            **weapon,
            "heavyAttack": {**heavy_route, "components": throw_components},
        }
    # 标准靶 KPM 口径（近战与枪械统一）：170 级钢铁之路卓越者超宏凶魂百夫长，
    # 30 秒窗口击杀数。近战按攻击路线逐次命中回放（melee_sequence）：
    # 战刃走「蓄力重投 + 引爆」，不再用单发重投伤害。
    metric = "killsPerMinute"
    requested_metric, requested_metric_warning = _metric(
        request.get("metric"), weapon_type
    )
    metric_warning = requested_metric_warning
    if (
        request.get("metric") not in (None, "")
        and _objective_metric(requested_metric) != metric
    ):
        metric_warning = (
            f"requested-metric-{request.get('metric')}-ignored-using-{metric}"
        )
    objective_metric = metric
    scenario = _requested_scenario(request, metric)
    # 偏好复合元素（elementTarget）：软约束——最终配装必须包含该元素
    # （与配装页的元素限制同一套伤害类型映射）。空值/未知值保持无约束。
    element_target_raw = str(request.get("elementTarget") or "").strip()
    required_damage_type: str | None = None
    if element_target_raw:
        required_damage_type = _ELEMENT_TARGET_TYPES.get(element_target_raw)
        if required_damage_type is None:
            raise SimulationError(
                "elementTarget must be empty or one of "
                + ", ".join(_ELEMENT_TARGET_TYPES)
            )
    # 架势（近战/组合近战，与配装页同口径）：默认普通攻击 DPS 倍率最高的架势；
    # 容量收益计入解算（无限极化口径下按匹配极性计），倍率是全局常数、只影响
    # 展示数值，不改变配卡排序。投掷重击口径下架势倍率不适用（容量仍计入）。
    stance_info = stance if isinstance(stance, Mapping) and weapon_type == "melee" else None
    stance_capacity = (
        max(0, int(stance_info.get("capacityGain") or 0)) if stance_info else 0
    )
    capacity_limit = 60 + stance_capacity
    stance_multiplier = (
        float(stance_info.get("dpsMultiplier") or 1.0)
        if stance_info and not throwable
        else 1.0
    )
    status_rate_multiplier = float(stance_info.get("statusRateMultiplier") or 1.0) if stance_info else 1.0
    melee_context: dict[str, Any] | None = None
    melee_schedule: dict[str, Any] | None = None
    if weapon_type == "melee":
        # Melee hit schedule: the stance and route travel with the scenario;
        # the replay uses discrete hits and ignores the stance multipliers.
        state = dict(scenario.combat_state)
        if stance_info and stance_info.get("path"):
            state.setdefault("meleeStance", str(stance_info["path"]))
        from .melee_sequence import ROUTES as _MELEE_ROUTES
        if request.get("meleeRoute") and str(request["meleeRoute"]) not in _MELEE_ROUTES:
            raise SimulationError("meleeRoute must be one of " + ", ".join(_MELEE_ROUTES))
        for key in ("meleeRoute", "meleeCombo"):
            if request.get(key):
                state[key] = str(request[key])
        scenario = replace(scenario, combat_state=state)
        melee_schedule = build_schedule(weapon, state.get("meleeRoute"), stance=state.get("meleeStance"),
                                        combo=state.get("meleeCombo"), target_distance=state.get("meleeTargetDistance"))
        if melee_schedule:
            melee_context = {"route": melee_schedule["route"], "label": melee_schedule.get("label"),
                             "stance": melee_schedule.get("stance"), "combo": melee_schedule.get("combo")}
            stance_multiplier = status_rate_multiplier = 1.0
    # 标准靶上下文（KPM 口径）：app 层注入 benchmarkTarget（enemy/level/
    # steelPath/eximus/windowSeconds），引擎解出真实目标记录参与窗口解算。
    benchmark = request.get("benchmarkTarget")
    benchmark_context: dict[str, Any] | None = None
    if isinstance(benchmark, Mapping):
        benchmark_enemy = benchmark.get("enemy") or benchmark.get("path")
        resolved_enemy = None
        if isinstance(benchmark_enemy, str) and benchmark_enemy.strip():
            try:
                resolved_enemy = resolve_record(
                    exports.get("enemies") or (), benchmark_enemy.strip(), kind="enemy"
                )
            except SimulationError:
                resolved_enemy = None
        if resolved_enemy is not None:
            benchmark_context = {
                "target": resolved_enemy,
                "level": benchmark.get("level"),
                "armour_strip": float(benchmark.get("armourStrip") or 0.0),
                "elemental_armour_strip": float(benchmark.get("elementalArmourStrip") or 0.0),
                "steel_path": bool(benchmark.get("steelPath")),
                "enemy_enhancements": (
                    benchmark.get("enemyEnhancements") or {k: benchmark[k] for k in ("eximus", "archimedea", "empowered", "playerCount") if k in benchmark}
                ),
                "hit_location": str(benchmark.get("hitLocation") or "body"),
                "headshotChance": float(benchmark.get("headshotChance") or 0.0),
                "windowSeconds": float(benchmark.get("windowSeconds") or 30.0),
                "stanceMultiplier": stance_multiplier,
                "statusRateMultiplier": status_rate_multiplier,
            }
    requested_target_payload = (
        dict(benchmark) if isinstance(benchmark, Mapping) else None
    )
    target_calibration: dict[str, Any] = {
        "version": TARGET_CALIBRATION_VERSION,
        "status": "not-applicable" if benchmark_context is None else "pending",
        "requestedLevel": (
            requested_target_payload.get("level")
            if requested_target_payload is not None
            else None
        ),
        "evaluationLevel": (
            benchmark_context.get("level") if benchmark_context is not None else None
        ),
        "iterations": [],
        "maxIterations": TARGET_CALIBRATION_MAX_ITERATIONS,
    }
    # 解算档位（profile）：fast/standard/deep，控制 beam 宽度、候选池与
    # 爬山轮数；也作为静态缓存 key 的一部分（不同档位的推荐/上限不同）。
    profile_raw = str(request.get("profile") or "standard").strip().casefold()
    if profile_raw not in {"ultra", "fast", "standard", "deep"}:
        raise SimulationError("profile must be one of ultra, fast, standard, deep")
    # ultra 与 fast 共用搜索参数与武器静态缓存；只跳过推荐/负面词条的新计算
    # （有缓存才显示），并改用面板近似 + 元素起点 + 回放复核的有限搜索。
    ultra = profile_raw == "ultra"
    profile = "fast" if ultra else profile_raw
    if benchmark_context is not None and profile == "fast":
        # 4 条分层分支：KPM 平均误差 0.25%，耗时为 16 条的 1/3（见
        # docs/RIVEN-ANALYSIS-REWORK-2026-10-05-floor.md 击杀反馈分支数）。
        benchmark_context["killBranches"] = FAST_KILL_BRANCHES

    # ── 搜索约束（wfsim 优化器 scope 模型）────────────────────────────
    # requiredMods/forbiddenMods：必选/禁选卡（引擎 card key 或 mod path）。
    # minFill/maxFill：配卡数量范围（0-8，含紫卡与必选卡；显式 0 = 裸枪基线）。
    # 显式约束存在时绕过静态缓存（缓存是「无约束最优」口径）。
    def _constraint_keys(value: Any, label: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, (list, tuple)) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise SimulationError(f"{label} must be an array of non-empty strings")
        return [str(item).strip() for item in value]

    search_required_keys = _constraint_keys(request.get("requiredMods"), "requiredMods")
    search_forbidden_keys = _constraint_keys(request.get("forbiddenMods"), "forbiddenMods")
    overlap = set(search_required_keys) & set(search_forbidden_keys)
    if overlap:
        raise SimulationError(
            "mods cannot be both required and forbidden: " + ", ".join(sorted(overlap))
        )

    def _fill_bound(value: Any, label: str) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 8:
            raise SimulationError(f"{label} must be an integer between 0 and 8")
        return value

    search_min_fill = _fill_bound(request.get("minFill"), "minFill")
    search_max_fill = _fill_bound(request.get("maxFill"), "maxFill")
    if (
        search_min_fill is not None
        and search_max_fill is not None
        and search_min_fill > search_max_fill
    ):
        raise SimulationError("minFill must not exceed maxFill")
    has_search_constraints = bool(
        search_required_keys or search_forbidden_keys
        or search_min_fill is not None or search_max_fill is not None
    )

    timeline_seconds = _requested_timeline_seconds(request)
    heavy_default_state = weapon_type == "melee" and isinstance(
        weapon.get("heavyAttack"), Mapping
    )
    if timeline_seconds is not None and (
        heavy_default_state or objective_metric == "heavyDamage"
    ):
        raise SimulationError(
            "timeline seconds are not supported for single heavy/throw damage"
        )
    if timeline_seconds is not None and objective_metric == "shotDamage":
        raise SimulationError("an Arcane timeline requires a DPS metric")
    source_disposition_raw = request.get("sourceDisposition")
    source_disposition = None
    if source_disposition_raw is not None:
        source_disposition = _number(
            "riven source disposition", source_disposition_raw
        )
        if source_disposition <= 0:
            raise SimulationError(
                "riven source disposition must be finite and positive"
            )

    disposition = _number("riven disposition", request.get("disposition"), 0.0)
    if disposition < 0:
        raise SimulationError("riven disposition must be finite and non-negative")
    if disposition <= 0:
        exported_disposition = _number(
            "weapon omegaAttenuation", weapon.get("omegaAttenuation"), 0.0
        )
        if exported_disposition > 0:
            disposition = exported_disposition
        elif source_disposition is not None:
            raise SimulationError(
                "target weapon disposition is required for Riven projection"
            )
        else:
            disposition = 1.0

    disposition_scale = (
        disposition / source_disposition
        if source_disposition is not None
        else 1.0
    )
    if not math.isfinite(disposition_scale):
        raise SimulationError("riven disposition scale must be finite")
    actual_lines, riven_unsupported = _wire_lines(
        request.get("stats"), disposition_scale
    )
    # A missing handler means the card is only partially represented.  Do not
    # turn that partial card into an apparently authoritative score.
    fatal_riven_unsupported = [
        item for item in riven_unsupported if not item.endswith("-not-evaluated")
    ]
    if fatal_riven_unsupported:
        raise SimulationError(
            "unsupported Riven stat(s): " + ", ".join(fatal_riven_unsupported)
        )
    # Known utility properties may be valid card lines even when the selected
    # objective cannot express their effect; preserve the score with a visible
    # diagnostic instead of silently treating them as damage.
    unsupported: list[str] = list(riven_unsupported)
    # skipped（口径说明诊断）提前初始化：评分靶自适应等中途模块会追加。
    skipped_early: list[str] = []
    if not actual_lines:
        unsupported.append("riven-request-has-no-usable-stats")
    if not weapon.get("omegaAttenuation") and request.get("disposition") in (None, 0):
        unsupported.append("riven-disposition-missing-using-1.0")
    if metric_warning:
        unsupported.append(metric_warning)
    template_bases = _template_bases(exports.get("rivenTemplates") or {}, riven_type)
    template_build = str((exports.get("rivenTemplates") or {}).get("buildLabel") or RIVEN_TEMPLATE_BUILD)
    if not template_bases and exports["buildLabel"] != RIVEN_TEMPLATE_BUILD:
        unsupported.append(
            f"riven-template-values-pinned-to-{RIVEN_TEMPLATE_BUILD}"
        )
    if any(line.code in {"C", "G", "I"} for line in actual_lines):
        unsupported.append("faction-riven-stats-excluded-from-target-neutral-objective")
    if required_damage_type:
        skipped_hint = (
            f"element-target: 偏好复合元素约束已生效（最终配装必须包含 "
            f"{required_damage_type}）"
        )
    else:
        skipped_hint = ""

    incarnon_card, resolved_choices, incarnon_unsupported, incarnon_policy = _incarnon_card(
        weapon,
        request.get("incarnonChoices"),
        scenario=scenario,
        metric=objective_metric,
        policy=exports.get("incarnonDefaults"),
        build_label=exports["buildLabel"],
    )
    unsupported.extend(incarnon_unsupported)
    arcane_card, arcane_states, arcane_unsupported = _arcane_card(
        exports.get("arcanes") or (),
        request.get("arcanes"),
        weapon,
        default_heavy_state=heavy_default_state,
    )
    unsupported.extend(arcane_unsupported)
    passives = _merge_passives(incarnon_card, arcane_card)

    mod_pool, rejected_mods = _candidate_mods(exports, weapon, scenario)

    # 流派钳制已移除（用户确认实战就是双修混搭，只是细节不同）：全量池
    # 单次求解，词条推荐与配装均为算法最优，不再区分触发/直伤流派。

    # 静态解算结果缓存：基准配装、双路推荐与理论上限都不随单张紫卡的数值
    # 变化（推荐候选恒为理论满数值口径），仅依赖武器/开火模式/倾向/容量上限
    # 与默认灵化策略；组合装配、显式灵化/赋能、时间线请求与显式搜索约束
    # （必选/禁选/数量范围）绕过缓存——缓存是「无约束最优」口径。
    # Standard/deep previously selected the final displayed builds by DPS in
    # a second full pass. Rank on that final metric from the start instead;
    # KPM remains a separately measured combat KPI for these same builds.
    ranking_metric = ('windowedDps' if objective_metric == 'killsPerMinute'
                      and benchmark_context is not None and profile != 'fast'
                      else objective_metric)
    cacheable = (
        statics_cache is not None
        and (not record_overridden or bool(request.get("_cacheDefaultInnate"))
             # A default-element Kitgun / Zaw assembly caches under its parts.
             or (bool(request.get("_cacheAssembly")) and statics_weapon != weapon_record.get("path")))
        and request.get("incarnonChoices") is None
        and request.get("arcanes") is None
        # A fixed caller preset (the Bot) may cache its own scenario; the
        # scenario then joins the cache key below.
        and (_default_analysis_scenario(scenario, metric) or bool(request.get("_cacheScenario")))
        and timeline_seconds is None
        and not has_search_constraints
    )
    _bm = dict(request.get("benchmarkTarget")) if isinstance(request.get("benchmarkTarget"), Mapping) else {}
    _bm.update(
        {
            "hitLocation": "body",
            "stanceMultiplier": stance_multiplier,
            "statusRateMultiplier": status_rate_multiplier,
            "heavyAttack": bool(scenario.heavy_attack),
        }
    )
    if not _default_analysis_scenario(scenario, metric):
        _bm["scenario"] = _scenario_context(scenario)
    if melee_context:
        _bm["melee"] = melee_context
    cache_key = _statics_cache_key(
        statics_weapon,
        weapon.get("innateElements"),
        fire_mode,
        element_target_raw,
        profile,
        disposition,
        capacity_limit,
        ranking_metric,
        _bm,
    )
    statics: dict[str, Any] | None = None
    if cacheable:
        candidate_entry = statics_cache.get(cache_key)
        if (
            isinstance(candidate_entry, dict)
            and candidate_entry.get("disposition") == disposition
            and candidate_entry.get("metric") == ranking_metric
            and candidate_entry.get("capacityLimit") == capacity_limit
        ):
            statics = candidate_entry
        fallback_disposition = request.get("_cacheDisposition")
        if statics is None and ultra and isinstance(fallback_disposition, (int, float)) and fallback_disposition > 0:
            # Read-only callers (the Bot) may keep a card's own disposition yet
            # read the entry baked at the catalog disposition: the baseline and
            # hardness nodes do not depend on it and the recommendation ranking
            # hardly does. Nothing is written back under this key.
            fallback_key = _statics_cache_key(
                statics_weapon, weapon.get("innateElements"), fire_mode, element_target_raw, profile,
                float(fallback_disposition), capacity_limit, ranking_metric, _bm,
            )
            fallback_entry = statics_cache.get(fallback_key)
            if (
                isinstance(fallback_entry, dict)
                and fallback_entry.get("metric") == ranking_metric
                and fallback_entry.get("capacityLimit") == capacity_limit
            ):
                statics = fallback_entry
                skipped_early.append(
                    f"cache: 读取按目录倾向 {float(fallback_disposition):g} 烘焙的武器缓存（本卡倾向 {disposition:g}）"
                )
        if statics is None:
            # 升靶缓存命中：同武器曾因秒杀饱和升级评分靶（缓存键已迁移到
            # #bm{scoringLevel}）。本请求的 benchmark level 落后于记录时，
            # 直接沿用升级后的等级（同武器所有请求一致），从概念键取回。
            # ── F11（审计修复）：回退查找必须匹配「除等级外的全部战斗上
            # 下文」。旧实现只比 weapon/mode/profile/metric/capacity/
            # disposition + 4 个派生字段——敌人、窗口、钢铁之路、卓越者、
            # 削甲、爆头率任一不同都会命中同一旧条目，把别的场景的数值
            # （quality 缓存）直接复用到本场景。现在整个 benchmark 子键
            # （除 level）必须逐字段相等。
            def _benchmark_matches_except_level(
                key_benchmark: Any,
            ) -> bool:
                if not isinstance(key_benchmark, Mapping):
                    return False
                expected = dict(_bm)
                for field, value in expected.items():
                    if field == "level":
                        continue
                    if key_benchmark.get(field) != value:
                        return False
                # 反向：缓存键里多出的 benchmark 字段（旧版本写入的
                # archimedea/empowered 等）也必须与本请求的默认值一致，
                # 否则视为不同场景。本请求未提供的字段按 _bm 的默认口径
                # 比较（缺失 = 与 None/默认不等即拒绝，宁缺勿错）。
                for field in (
                    "enemy", "steelPath", "eximus", "archimedea", "empowered",
                    "armourStrip", "elementalArmourStrip", "headshotChance",
                    "hitLocation", "stanceMultiplier", "statusRateMultiplier",
                    "heavyAttack", "windowSeconds",
                ):
                    if field in key_benchmark and field not in expected:
                        return False
                return True

            cached_level = None
            for key, entry in statics_cache.items():
                if not isinstance(key, str) or not isinstance(entry, dict):
                    continue
                try:
                    parsed_key = json.loads(key)
                except (TypeError, ValueError):
                    continue
                if (
                    isinstance(parsed_key, dict)
                    and parsed_key.get("weapon") == statics_weapon
                    and parsed_key.get("innateElements") == list(weapon.get("innateElements") or ())
                    and parsed_key.get("fireMode") == fire_mode
                    and parsed_key.get("elementTarget") == (element_target_raw or "-")
                    and parsed_key.get("profile") == profile
                    and parsed_key.get("metric") == ranking_metric
                    and parsed_key.get("capacityLimit") == capacity_limit
                    and parsed_key.get("disposition") == round(float(disposition), 8)
                    and _benchmark_matches_except_level(parsed_key.get("benchmark"))
                    and isinstance(entry.get("scoringLevel"), int)
                ):
                    cached_level = entry["scoringLevel"]
                    statics = entry
                    break
            if (
                statics is not None
                and cached_level is not None
                and benchmark_context is not None
                and benchmark_context.get("level") != cached_level
            ):
                benchmark_context = dict(benchmark_context, level=cached_level)
    if ultra:
        # 超快档只读快速档的武器缓存、从不回写：近似搜索得到的基线与倍率
        # 不能污染快速档；缓存缺失时推荐与负面词条直接留空。
        statics = json.loads(json.dumps(statics)) if statics is not None else None
    elif cacheable and statics is None:
        statics = {}
        statics_cache[cache_key] = statics
    pool_by_key = {card.key: card for card in mod_pool}

    def _reconstruct(
        card_keys: Any, riven_card: _Card | None
    ) -> _Evaluation | None:
        if (
            not isinstance(card_keys, list)
            or any(not isinstance(key, str) for key in card_keys)
            or any(key not in pool_by_key for key in card_keys)
        ):
            return None
        evaluate = lambda: _evaluate(
            weapon,
            tuple(pool_by_key[key] for key in card_keys),
            riven_card,
            scenario=scenario,
            metric=ranking_metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=benchmark_context,
            reorder_elements=False,  # stored in its evaluated (best) order
        )
        if riven_card is not None:
            return evaluate()
        # The cached no-Riven baseline is re-scored by every request of the
        # weapon; keep the scored build per exact inputs for the process.
        try:
            key = hashlib.sha256(pickle.dumps((statics_weapon, tuple(card_keys), replace(scenario, conditional_stacks=dict(scenario.conditional_stacks)),
                                               ranking_metric, passives, capacity_limit, benchmark_context), protocol=5)).digest()
        except (TypeError, pickle.PicklingError, AttributeError):
            return evaluate()
        if key in _BASELINE_EVALUATIONS:
            _BASELINE_EVALUATIONS.move_to_end(key)
            return _BASELINE_EVALUATIONS[key]
        result = evaluate()
        _BASELINE_EVALUATIONS[key] = result
        while len(_BASELINE_EVALUATIONS) > 64:
            _BASELINE_EVALUATIONS.popitem(last=False)
        return result

    def _optimize_with_element_fallback(
        weapon: Mapping[str, Any],
        candidates: Sequence[_Card],
        riven: _Card | None,
        **kwargs: Any,
    ) -> _Evaluation:
        # 偏好元素约束下无可行配装时（元素 mod 与容量/家族互斥冲突），回退到
        # 无约束解算并记录诊断——默认「腐蚀」对部分武器（如自带元素武器、
        # 近战）不可达，不应让整个分析失败。
        if not required_damage_type:
            return _optimize(weapon, candidates, riven, **kwargs)
        try:
            return _optimize(
                weapon, candidates, riven, required_damage_type=required_damage_type, **kwargs
            )
        except SimulationError as exc:
            if f"damage type {required_damage_type}" not in str(exc):
                raise
        # A narrow beam ranks by score and may never keep a pure two-element
        # combination (melee fast profile + viral); seed the strongest mod of
        # each component, as the ultra seeds do, before giving up.
        parts = ELEMENT_SEEDS.get(required_damage_type, ())
        seeded = list(kwargs.get("required_mod_keys") or ())
        forbidden = set(kwargs.get("forbidden_mod_keys") or ())
        for part in parts:
            options = [(sum(float(e.value) for e in c.effects if e.damage_type == part), c.key)
                       for c in candidates if any(e.damage_type == part for e in c.effects)
                       and c.key not in forbidden and c.key not in seeded]
            if options:
                seeded.append(max(options)[1])
        if parts and len(seeded) > len(kwargs.get("required_mod_keys") or ()):
            try:
                return _optimize(weapon, candidates, riven, required_damage_type=required_damage_type,
                                 **dict(kwargs, required_mod_keys=seeded))
            except SimulationError as exc:
                if f"damage type {required_damage_type}" not in str(exc):
                    raise
        unsupported.append(
            f"element-target-infeasible-{required_damage_type}-using-unconstrained"
        )
        return _optimize(weapon, candidates, riven, **kwargs)

    def _optimize_archetype(
        weapon: Mapping[str, Any],
        riven: _Card | None,
        **kwargs: Any,
    ) -> _Evaluation:
        """全量池单次求解（流派钳制已按用户要求移除：实战即双修混搭）。

        ``__escalated_context``（可选）：评分靶升级时覆盖 benchmark_context
        （自适应等级逻辑用；正常调用不传）。
        """
        escalated = kwargs.pop("__escalated_context", None)
        context = escalated if escalated is not None else search_context
        common = dict(target_context=context, profile=profile, forbidden_mod_keys=search_forbidden_keys,
                      min_fill=search_min_fill, max_fill=search_max_fill)
        results = []
        if not ultra:
            results.append(_optimize_with_element_fallback(
                weapon, mod_pool, riven, required_mod_keys=search_required_keys, **common, **kwargs))
        seeds: tuple[tuple[str | None, tuple[str, ...]], ...] = ((None, ()), *ELEMENT_SEEDS.items())
        if required_damage_type:
            if not ultra:
                return _rescore(results[0], riven, kwargs)
            # Ultra with a fixed element (the Bot's viral policy): only that
            # element's seed; the open seed is the fallback when infeasible.
            seeds = ((required_damage_type, ELEMENT_SEEDS.get(required_damage_type, ())),)
        # Element seeds (open / viral / corrosive): searched on the cheap panel
        # proxy, then re-scored with the real metric. They can only add
        # candidates; the replay decides. Every profile runs all three, so a
        # deeper profile never ends below the ultra one.
        proxy = dict(kwargs, metric="statusSustainedDps", beam_width=4, shortlist=24)
        for element, parts in seeds:
            seeded = list(search_required_keys)
            for part in parts:
                options = [(sum(float(e.value) for e in c.effects if e.damage_type == part), c.key)
                           for c in mod_pool if any(e.damage_type == part for e in c.effects)
                           and c.key not in search_forbidden_keys]
                if options:
                    seeded.append(max(options)[1])
            try:
                found = _optimize(weapon, mod_pool, riven, required_mod_keys=seeded, required_damage_type=element,
                                  **common, **proxy)
            except SimulationError:
                continue
            cards = tuple(pool_by_key.get(card.key, card) for card in found.cards)
            # Ultra ranks the seeds with the Riven last and places it only
            # in the winner (an element Riven multiplies replays by the
            # element boundaries).
            scored = _evaluate(weapon, cards, riven, scenario=kwargs["scenario"], metric=kwargs["metric"],
                               passives=kwargs.get("passives"), capacity_limit=kwargs.get("capacity_limit", 60),
                               target_context=context, fixed_riven_index=len(cards) if ultra and riven is not None else None)
            if scored is not None:
                results.append(scored)
        if not results and required_damage_type and ultra:
            unsupported.append(f"element-target-infeasible-{required_damage_type}-using-unconstrained")
            found = _optimize(weapon, mod_pool, riven, required_mod_keys=list(search_required_keys), **common, **proxy)
            scored = _evaluate(weapon, tuple(pool_by_key.get(c.key, c) for c in found.cards), riven,
                               scenario=kwargs["scenario"], metric=kwargs["metric"], passives=kwargs.get("passives"),
                               capacity_limit=kwargs.get("capacity_limit", 60), target_context=context,
                               fixed_riven_index=len(found.cards) if riven is not None else None)
            if scored is not None:
                results.append(scored)
        if not results:
            raise SimulationError("no capacity-valid build found")
        best = max(results, key=lambda result: result.score)
        if ultra and riven is not None:
            best = _evaluate(weapon, best.cards, riven, scenario=kwargs["scenario"], metric=kwargs["metric"],
                             passives=kwargs.get("passives"), capacity_limit=kwargs.get("capacity_limit", 60),
                             target_context=context) or best
        return _rescore(best, riven, kwargs)

    def _rescore(result: _Evaluation, riven: _Card | None, kwargs: Mapping[str, Any]) -> _Evaluation:
        # Searches run on the middle hardness node; the chosen build is scored
        # on all nodes like every displayed number.
        if benchmark_context is None or not benchmark_context.get("hardnessNodes"):
            return result
        scored = _evaluate(weapon, result.cards, riven, scenario=kwargs["scenario"], metric=kwargs["metric"],
                           passives=kwargs.get("passives"), capacity_limit=kwargs.get("capacity_limit", 60),
                           target_context=benchmark_context, fixed_riven_index=result.riven_index,
                           reorder_elements=False)
        return scored or result

    def _apply_riven_floor_profiled(result: _Evaluation, riven_card: _Card, *, floor_metric: str | None = None) -> _Evaluation:
        # riven floor 修正（「无紫卡最优 − 最弱卡 + 紫卡」下限）在所有档位保留：
        # 它只花 ~9 次评估，却能挡住「窄 beam 剪掉显见路径导致带紫卡反而更差」
        # 的假性负收益（快速档 beam 12 实测出现 -5% 假性负收益）。真正按档位
        # 缩的是爬山轮数与 _best_fixed 的子集枚举。
        return _apply_riven_floor(result, riven_card, floor_metric=floor_metric)

    _progress("baseline")
    # ── 硬度积分靶（hardness-integrated）──────────────────────────────
    # 不挑单一血量：以本武器无紫卡基线身体命中的击杀时间 T ∈ [1, 20] s（对数
    # 均匀，三点高斯积分 1.4/4.5/14.3 s）换算三个血量节点；评分 = 三节点多击杀回放 KPM 的
    # 几何平均；搜索只用中心节点。节点随武器缓存，提交的紫卡永不改变靶子；
    # 身体命中计数，0% 与 100% 弱点共用同一组节点。
    fixed_target = (benchmark_context is not None and objective_metric == "killsPerMinute")
    raw_context = benchmark_context
    search_context = benchmark_context
    hardness_nodes = statics.get("hardnessNodes") if statics else None
    nodes_cached = fixed_target and _valid_hardness_nodes(hardness_nodes)
    if nodes_cached:
        search_context = _center_context(raw_context, hardness_nodes)
        benchmark_context = dict(raw_context, hardnessNodes=hardness_nodes)
    baseline = _reconstruct(statics.get("baselineCards"), None) if statics else None
    baseline_fresh = baseline is None
    if baseline_fresh and ultra:
        # 面板近似的无紫卡基线偏弱，实际增益只是估算；读到快速档缓存后才可比。
        unsupported.append("ultra-profile-baseline-approximate")
    if baseline_fresh:
        baseline = _optimize_archetype(
            weapon,
            None,
            scenario=scenario,
            metric=ranking_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )
    if fixed_target and not nodes_cached:
        hardness_nodes = _hardness_nodes(baseline.stats, raw_context)
        if hardness_nodes is None:
            unsupported.append("hardness-nodes-unavailable-single-target")
        else:
            searched_scale = float((search_context.get("enemy_enhancements") or {}).get("healthScale") or 1.0)
            search_context = _center_context(raw_context, hardness_nodes)
            center = float(hardness_nodes[len(hardness_nodes) // 2]["healthScale"])
            if abs(math.log(center / searched_scale)) > math.log(2.0) and not ultra:
                # The build was chosen on a target of very different hardness;
                # choose it again on the middle node and re-derive the nodes.
                baseline = _optimize_archetype(
                    weapon, None, scenario=scenario, metric=ranking_metric,
                    passives=passives, capacity_limit=capacity_limit,
                )
                hardness_nodes = _hardness_nodes(baseline.stats, raw_context) or hardness_nodes
                search_context = _center_context(raw_context, hardness_nodes)
            benchmark_context = dict(raw_context, hardnessNodes=hardness_nodes)
            # Same build, scored on all nodes like every later build.
            baseline = _reconstruct([card.key for card in baseline.cards], None) or baseline
            if statics is not None:
                statics["hardnessNodes"] = hardness_nodes
    if fixed_target and benchmark_context.get("hardnessNodes"):
        target_calibration.update(
            status="hardness-integrated",
            evaluationLevel=benchmark_context.get("level"),
            hardnessNodes=benchmark_context["hardnessNodes"],
            ttkRange=list(HARDNESS_TTK_RANGE),
            ttkBasis="no-riven-baseline-body-shot-ttk",
            aggregation="geometric-mean-kpm",
            searchHealthScale=(search_context.get("enemy_enhancements") or {}).get("healthScale", 1.0),
        )

    def _apply_riven_floor(result: _Evaluation, riven_card: _Card, *, floor_metric: str | None = None) -> _Evaluation:
        # 梁搜索在强制含紫卡时可能中途剪掉「无紫卡最优 − 最弱卡 + 紫卡」这条
        # 显而易见的路径（部分配装在前几层协同未成形就被淘汰）。用它做下限，
        # 避免「带紫卡反而比不带差」的假性负收益。required 卡（剑风 Prime）
        # 不可被下限路径移除——floor 只从非必需卡中减一张。
        # ── F07（审计修复）：floor 路径同样过统一可行域验证（必选卡必须
        # 保留、数量范围不得越界）。旧实现只查容量，riven-floor 可以把用户
        # 必选卡换掉或把配卡数压到 min_fill 之下。
        # ── 容量修复（2026-09-24）：紫卡 18 耗经常要求丢 2 张卡（8 张满配
        # 60 耗 + 18 超限）；旧 floor 只枚举单卡丢弃，装不下就整条 floor
        # 失效——actual 于是回退到 beam 的劣解（用户报告的 actual < baseline
        # 崩坏）。先按容量贪心保留（按卡序丢最贵），再补单卡丢弃枚举。
        required_keys = {
            card.key for card in baseline.cards if card.required
        }
        droppable = [
            card
            for card in baseline.cards
            if card.key not in required_keys
        ]
        floor_candidates: list[tuple[_Card, ...]] = []
        # 容量贪心：从 baseline 全卡开始，装不下就按「最贵优先丢」直到可装。
        kept_greedy = list(baseline.cards)
        guard = 0
        while (
            validate_build(
                tuple(kept_greedy),
                riven_card,
                slot_count=8,  # analyze_riven_request 固定 8 槽口径
                capacity_limit=capacity_limit,
                required_mod_keys=search_required_keys,
                forbidden_mod_keys=search_forbidden_keys,
                min_fill=search_min_fill,
                max_fill=search_max_fill,
            ) is not None
            and kept_greedy
            and guard < 8
        ):
            # 丢最贵的一张可丢卡。
            droppable_here = [c for c in kept_greedy if c.key not in required_keys]
            if not droppable_here:
                break
            most_expensive = max(droppable_here, key=lambda c: c.drain)
            kept_greedy.remove(most_expensive)
            guard += 1
        if kept_greedy and validate_build(
            tuple(kept_greedy),
            riven_card,
            slot_count=8,
            capacity_limit=capacity_limit,
            required_mod_keys=search_required_keys,
            forbidden_mod_keys=search_forbidden_keys,
            min_fill=search_min_fill,
            max_fill=search_max_fill,
        ) is None:
            floor_candidates.append(tuple(kept_greedy))
        # 单卡丢弃枚举（保留旧口径；droppable 非空时）。
        for drop_card in droppable:
            kept = tuple(
                card for card in baseline.cards if card.key != drop_card.key
            )
            floor_candidates.append(kept)
        floor_candidates.append(tuple(baseline.cards))
        floor: _Evaluation | None = None
        for kept in floor_candidates:
            if validate_build(
                kept,
                riven_card,
                slot_count=8,  # analyze_riven_request 固定 8 槽口径
                capacity_limit=capacity_limit,
                required_mod_keys=search_required_keys,
                forbidden_mod_keys=search_forbidden_keys,
                min_fill=search_min_fill,
                max_fill=search_max_fill,
            ) is not None:
                continue
            evaluated = _evaluate(
                weapon,
                kept,
                riven_card,
                scenario=scenario,
                metric=floor_metric or ranking_metric,
                passives=passives,
                capacity_limit=capacity_limit,
                target_context=search_context,
                reorder_elements=False,  # the baseline's element order is already chosen
                fixed_riven_index=len(kept) if ultra else None,  # ultra: place the Riven in the winner only
            )
            if evaluated is not None and (floor is None or evaluated.score > floor.score):
                floor = evaluated
        if floor is not None and ultra:
            floor = _evaluate(weapon, floor.cards, riven_card, scenario=scenario, metric=floor_metric or ranking_metric,
                              passives=passives, capacity_limit=capacity_limit, target_context=search_context,
                              reorder_elements=False) or floor
        if floor is not None and search_context is not benchmark_context:
            # Candidates compete on the middle node; the winner is scored on all.
            floor = _evaluate(weapon, floor.cards, riven_card, scenario=scenario,
                              metric=floor_metric or ranking_metric, passives=passives,
                              capacity_limit=capacity_limit, target_context=benchmark_context,
                              fixed_riven_index=floor.riven_index, reorder_elements=False) or floor
        if floor is not None and floor.score > result.score:
            return floor
        return result

    _progress("actual")
    actual_card = _card_from_lines(actual_lines)
    actual = _apply_riven_floor_profiled(
        _optimize_archetype(
            weapon,
            actual_card,
            scenario=scenario,
            metric=ranking_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        ),
        actual_card,
    )

    # Reverse floor (ultra without a cached baseline only): the actual build
    # without its Riven, the slot refilled, is a no-Riven build too; when it
    # beats the approximate baseline it is used for the gain, so actualGain is
    # not inflated by a weak baseline. Cached baselines stay fixed per weapon:
    # every card of a weapon is measured against the same baseline.
    gain_baseline = baseline
    if ultra and baseline_fresh and not search_required_keys and not search_forbidden_keys and search_min_fill is None and search_max_fill is None:
        kept = tuple(pool_by_key.get(card.key, card) for card in actual.cards)
        families = {_mod_family(card) for card in kept}
        fillers = [card for card in mod_pool if card.key not in {c.key for c in kept} and _mod_family(card) not in families]
        panel = []
        for card in fillers:
            probe = _evaluate(weapon, (*kept, card), None, scenario=scenario, metric="statusSustainedDps",
                              passives=passives, capacity_limit=capacity_limit, target_context=search_context,
                              reorder_elements=False)
            if probe is not None:
                panel.append((probe.score, card.key, card))
        candidates = [kept] + [(*kept, card) for _, _, card in sorted(panel, key=lambda x: (-x[0], x[1]))[:6]]
        best = None
        for cards in candidates:
            evaluated = _evaluate(weapon, cards, None, scenario=scenario, metric=ranking_metric, passives=passives,
                                  capacity_limit=capacity_limit, target_context=search_context,
                                  reorder_elements=False)
            if evaluated is not None and (best is None or evaluated.score > best.score):
                best = evaluated
        if best is not None:
            best = _reconstruct([card.key for card in best.cards], None) or best
            if best.score > baseline.score * (1.0 + 1e-9):
                gain_baseline = best
                unsupported.append("baseline-raised-by-reverse-floor")

    _fusable = _fusion_codes_from_templates(
        exports.get("rivenTemplates") or {}, riven_type
    )
    positive_candidates, _ = _candidate_lines(
        riven_type, disposition, (), negative=False, bases=template_bases,
        available_fusion_codes=_fusable,
    )
    candidate_by_code = {line.code: line for line in positive_candidates}
    negative_candidates, _ = _candidate_lines(
        riven_type, disposition, (), negative=True, bases=template_bases,
        available_fusion_codes=_fusable,
    )
    negative_by_code = {line.code: line for line in negative_candidates}

    _progress("recommendation")

    def _archetype_bases() -> list[tuple[_Card, ...]]:
        """Full builds around a representative crit card and status card.

        Cached per weapon with the other statics; independent of the card
        being analysed.
        """
        cached = statics.get("archetypeBases") if statics else None
        if isinstance(cached, dict):
            rebuilt = [tuple(pool_by_key[key] for key in keys) for keys in cached.values()
                       if isinstance(keys, list) and all(key in pool_by_key for key in keys)]
            if len(rebuilt) == len(cached):
                return rebuilt
        filler = "S" if "S" in candidate_by_code else "D"
        elements = [code for code in ("4", "5", "6", "7") if code in candidate_by_code]
        element = None
        if elements:
            def element_value(code: str) -> float:
                try:
                    return _best_fixed(weapon, baseline.cards, _card_from_lines([candidate_by_code[code]]),
                                       scenario=scenario, metric=ranking_metric, passives=passives,
                                       capacity_limit=capacity_limit, target_context=search_context,
                                       max_keep_cap={"fast": 3, "standard": 5, "deep": None}[profile]).score
                except SimulationError:
                    return -math.inf
            element = max(elements, key=element_value)
        archetypes = {"crit": ["0", "1", filler], "status": ["2", element or "D", filler]}
        built: dict[str, list[str]] = {}
        result: list[tuple[_Card, ...]] = []
        for name, codes in archetypes.items():
            lines = [candidate_by_code[code] for code in dict.fromkeys(codes) if code in candidate_by_code]
            if len(lines) < 2:
                continue
            try:
                evaluation = _optimize_archetype(weapon, _card_from_lines(lines), scenario=scenario,
                                                 metric=ranking_metric, passives=passives,
                                                 capacity_limit=capacity_limit)
            except SimulationError:
                continue
            built[name] = [card.key for card in evaluation.cards]
            result.append(tuple(evaluation.cards))
        if statics is not None:
            statics["archetypeBases"] = built
        return result
    positive_count = sum(not line.negative for line in actual_lines)
    if positive_count not in {2, 3}:
        positive_count = 3
        unsupported.append("partial-riven-positive-count-using-three-stat-optimum")
    count_key = str(positive_count)
    bundle: dict[str, Any] | None = None
    if statics is not None and isinstance(statics.get("counts"), dict):
        cached_bundle = statics["counts"].get(count_key)
        if isinstance(cached_bundle, dict):
            bundle = cached_bundle
    cached_recommended = (
        [
            candidate_by_code[code]
            for code in bundle.get("recommended") or ()
            if code in candidate_by_code
        ]
        if bundle is not None
        else None
    )
    recommended_fresh = not (
        cached_recommended is not None
        and len(cached_recommended) == positive_count
        and isinstance(bundle.get("tiers"), list)
    )
    if recommended_fresh and ultra:
        # 超快档不做推荐搜索：没有快速档缓存时推荐留空。
        recommended, recommended_result, recommended_tiers = [], None, []
        recommended_fresh = False
        unsupported.append("ultra-profile-recommendation-not-cached")
    elif recommended_fresh:
        recommended, recommended_result, recommended_tiers = _recommend_positive(
            weapon,
            baseline,
            positive_candidates,
            positive_count,
            scenario=scenario,
            metric=ranking_metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=search_context,
            profile=profile,
            extra_bases=_archetype_bases(),
        )
    else:
        recommended = cached_recommended
        recommended_result = None
        recommended_tiers = bundle["tiers"]

    # 双路推荐已移除（用户确认实战即双修混搭）：推荐词条就是算法在当前
    # KPM 口径下的最优组合，不再区分触发/直伤流派。保留 recommendedRoutes
    # 字段为空以兼容旧前端。

    # ── 负面词条排序：无伤负面 + 已建模负面统一评估 ─────────────────────
    # 无伤负面（当前 KPM 口径零影响）：枪械 Z 后坐力/H 变焦/M 弹药上限/
    # E 滑行暴击，近战 X 处决/N 连击持续/U 重击效率（普攻口径）。
    # 已建模负面（真实影响，可为正收益——如膛室 Prime 配负弹匣）：
    # L 弹匣/3 触发时间/F 装填/R 射速等——全部参与排序，让求解器自己
    # 找到「代价最小/收益最大」的负面（不再人工限定中立池）。
    neutral_negative_codes = _neutral_negative_codes(weapon)
    negative_keep_cap = {"fast": 3, "standard": 5, "deep": None}[profile]
    negative_ranked: list[tuple[float, _RivenLine]] = []
    from .riven_recommendation import negative_rolls
    ranked_positive, _ = _candidate_lines(riven_type,disposition,(),negative=False,bases=template_bases,
        structure_scale=theoretical_structure_scale(positive_count,True),available_fusion_codes=_fusable)
    ranked_negative, _ = _candidate_lines(riven_type,disposition,(),negative=True,bases=template_bases,
        structure_scale=theoretical_structure_scale(positive_count,True,negative=True),available_fusion_codes=_fusable)
    positive_map = {line.code:line for line in ranked_positive}
    negative_seed = [positive_map[line.code] for line in recommended]
    negative_map = {line.code: line for line in ranked_negative}
    cached_negative = (bundle or {}).get("negative") if not recommended_fresh else None
    negative_fresh = not isinstance(cached_negative, list)
    if negative_fresh and ultra:
        unsupported.append("ultra-profile-negative-ranking-not-cached")
    for line in (negative_rolls(ranked_negative) if negative_fresh and not ultra else ()):
        if line.code in {p.code for p in negative_seed}:
            continue
        if line.code not in neutral_negative_codes and (line.effect is None or not line.effect.supported):
            continue
        result = _best_fixed(
            weapon,
            baseline.cards,
            _card_from_lines([*negative_seed, line]),
            scenario=scenario,
            metric=ranking_metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=search_context,
            max_keep_cap=negative_keep_cap,
        )
        negative_ranked.append((result.score, line))
    negative_ranked.sort(key=lambda item: (-item[0],item[1].code not in neutral_negative_codes,item[1].code))
    recommended_negative = []
    for _,line in negative_ranked:
        if line.code not in {l.code for l in recommended_negative}:recommended_negative.append(line)
        if len(recommended_negative)==3:break
    if not negative_fresh:
        recommended_negative = [negative_map[code] for code in cached_negative if code in negative_map]
    negative_fresh = negative_fresh and not ultra
    if not recommended_negative and "ultra-profile-negative-ranking-not-cached" not in unsupported:
        unsupported.append("no-objective-neutral-supported-negative-stat")

    # All final builds, recommendations and ablations share the ranking metric.
    # KPM is measured separately for display; never repeat the entire search
    # solely to change the quality unit after it already selected these builds.
    _progress("quality")
    # Recommendations and negatives above used the searched baseline (card
    # independent, cached); gain and the displayed baseline use the stronger.
    searched_baseline, baseline = baseline, gain_baseline
    score_metric = ranking_metric
    quality_scores = {"baseline":baseline.score, "actual":actual.score}
    quality_detail_cache: dict[str, float] = {}
    quality_cache_hit = False
    if score_metric != objective_metric:
        skipped_early.append("评分与配装从一开始使用同靶窗口 DPS；KPM 为同一配装的独立战斗指标，无重复复评搜索")

    # 回写静态缓存（仅本次新算的部分；高数值/当前紫卡反超修正不影响缓存）。
    if cacheable and not ultra and statics is not None and (
        baseline_fresh or recommended_fresh or negative_fresh
    ):
        statics["disposition"] = disposition
        statics["metric"] = ranking_metric
        statics["capacityLimit"] = capacity_limit
        if baseline_fresh:
            statics["baselineCards"] = [card.key for card in searched_baseline.cards]
        counts = statics.get("counts")
        if not isinstance(counts, dict):
            counts = {}
            statics["counts"] = counts
        write_bundle = counts.get(count_key)
        if not isinstance(write_bundle, dict):
            write_bundle = {}
            counts[count_key] = write_bundle
        if recommended_fresh:
            write_bundle["recommended"] = [line.code for line in recommended]
            write_bundle["tiers"] = recommended_tiers
        if negative_fresh:
            write_bundle["negative"] = [line.code for line in recommended_negative]
        statics_cache["__dirty__"] = True

    # 不再计算「理论上限」与 0–100 评分（上限本身是近似搜索，其误差会传给
    # 所有评分）。保留：相对无紫卡基线的实际增益、逐词条贡献与推荐词条排序。
    actual_gain = _percent_gain(quality_scores["actual"], quality_scores["baseline"])

    recommended_codes = {line.code for line in recommended}
    negative_codes = {line.code for line in recommended_negative}
    details = []
    fatal_negative: list[str] = []
    details_keep_cap = {"fast": 3, "standard": 5, "deep": None}[profile]
    reoptimized_contributions = bool(request.get("includeReoptimizedContributions"))
    ablation_scores: dict[str, float] = {}
    # Ultra: stat contributions compare the build with and without each stat
    # on the middle hardness node only (one replay each instead of a full
    # node integration); the relative change is what is shown.
    ablation_context = benchmark_context
    ablation_reference = quality_scores["actual"]
    if ultra and search_context is not benchmark_context:
        ablation_context = search_context
        center = _evaluate(weapon, actual.cards, actual_card, scenario=scenario, metric=score_metric, passives=passives,
                           capacity_limit=capacity_limit, target_context=search_context,
                           fixed_riven_index=actual.riven_index, reorder_elements=False)
        if center is not None:
            ablation_reference = center.score
            unsupported.append("ultra-profile-contributions-center-node")
        else:
            ablation_context = benchmark_context
    if score_metric == objective_metric and os.environ.get("WF_ANALYZER_SERIAL") != "1":
        from wfarsenal import parallel as _parallel
        _pool = _parallel.get_pool()
        if _pool is not None:
            _ctx = {"weapon": weapon, "scenario": scenario, "metric": objective_metric,
                    "passives": passives, "slot_limit": 8, "capacity_limit": capacity_limit,
                    "target_context": ablation_context, "fixed_riven_index": actual.riven_index,
                    "reorder_elements": False}
            _jobs = {}
            for _line in actual_lines:
                if _line.code in {'W','Y'} and benchmark_context is not None and not float(benchmark_context.get('headshotChance') or 0.):
                    continue
                _without = _card_from_lines([item for item in actual_lines if item.code != _line.code])
                _jobs[_line.code] = _pool.submit(_parallel._score_job, (actual.cards, _without, _ctx))
            for _code, _future in _jobs.items():
                _value = _future.result()
                if _value is not None:
                    ablation_scores[_code] = float(_value)
    for line in actual_lines:
        if reoptimized_contributions and score_metric != objective_metric and line.code in quality_detail_cache:
            delta = quality_detail_cache[line.code]
        elif reoptimized_contributions:
            without = _card_from_lines(
                [item for item in actual_lines if item.code != line.code]
            )
            removed = _best_fixed(
                weapon,
                actual.cards,
                without,
                scenario=scenario,
                metric=score_metric,
                passives=passives,
                capacity_limit=capacity_limit,
                target_context=benchmark_context,
                max_keep_cap=details_keep_cap,
                preserve_base=True,
            )
            removed_score = removed.score
            if score_metric != objective_metric:
                removed_score = _score(
                    removed.stats,
                    score_metric,
                    target_context=benchmark_context,
                )
            delta = _percent_gain(quality_scores["actual"], removed_score)
        else:
            # Fixed-build ablation is the default contribution contract. The
            # second "remove then re-optimize" search is opt-in because it is
            # the dominant source of multi-minute first requests.
            delta = None
            if score_metric != objective_metric:
                quality_detail_cache[line.code] = delta
        # ── F08（审计修复）：词条贡献拆成两个明确口径 ─────────────────────
        # ablationDelta —— 固定配卡消融：保持其他卡、槽位顺序、数值、目标
        #   和指标完全不变，只把该词条从紫卡里移除后重放同一配卡。这是
        #   「同一配卡移除此词条后的目标伤害变化」的字面合同。
        # delta（保留字段，含义=重优化收益）—— 移除词条后允许重新搜配卡
        #   （_best_fixed 子集枚举）的收益上限。用户需要区分「词条本身的
        #   价值」与「删词条+换卡后的联合收益」。
        # 旧实现只返回 delta 但解释文案写成消融口径——零作用词条可能因
        #   子集重优化删掉其他 MOD 而显示巨大「贡献」。
        without_line = _card_from_lines([item for item in actual_lines if item.code != line.code])
        if line.code in ablation_scores:
            ablated_score = ablation_scores[line.code]
            ablated = True
        else:
            ablated = _evaluate(
                weapon, actual.cards, without_line, scenario=scenario,
                metric=score_metric, passives=passives,
                capacity_limit=capacity_limit, target_context=ablation_context,
                fixed_riven_index=actual.riven_index, reorder_elements=False,
            )
            ablated_score = ablated.score if ablated is not None else None
        if ablated_score is not None:
            if score_metric != objective_metric:
                ablated_score = _score(
                    ablated.stats if hasattr(ablated, 'stats') else actual.stats,
                    score_metric,
                    target_context=benchmark_context,
                )
            ablation_delta = _percent_gain(ablation_reference, ablated_score)
        else:
            ablation_delta = None
        inactive_reason = None
        condition = None
        if line.code in {'W','Y'}:
            condition = '弱点命中时'
            if benchmark_context is not None and float(benchmark_context.get('headshotChance') or 0.) == 0.:
                inactive_reason = '当前评价靶弱点命中率为 0%'
        elif line.code == 'HR':
            condition = '武器收起时自动装填'
            inactive_reason = '当前持续持枪，没有收起装填事件'
        fatal = line.negative and (
            (ablation_delta if ablation_delta is not None else delta or 0.0) < -5.0
        )
        if (
            fatal
            and line.effect is not None
            and line.effect.upgrade_type == "WEAPON_CLIP_MAX"
            and float(getattr(actual.stats, "magazine", 0.0) or 0.0) >= 1.0
        ):
            # 弹匣负面只有在压到连一次完整开火循环都维持不了（弹匣 <1）时才
            # 算致命；否则只是可量化的 DPS 折损（details 里仍给出数值）。
            # 小弹匣武器（如守望者 Prime，弹匣 2）配合首发伤害 MOD 时社区
            # 口径（黑猫）不把负弹匣列为致命。
            fatal = False
        if fatal:
            fatal_negative.append(line.label)
        details.append(
            {
                "code": line.code,
                "label": line.label,
                "value": line.value,
                "low": line.low,
                "high": line.high,
                "quality": _quality(line),
                # F08：主口径改为固定配卡消融（字面合同：同一配卡移除此
                # 词条）；重优化收益单独成字段。delta 保留为消融口径以
                # 兼容旧前端，reoptimizedDelta 是「删词条后重搜配卡」的
                # 联合收益上限。
                "delta": ablation_delta if ablation_delta is not None else delta,
                "ablationDelta": ablation_delta,
                "reoptimizedDelta": delta,
                "contributionMetric": score_metric,
                "condition": condition,
                "inactiveReason": inactive_reason,
                "contributionStatus": 'inactive' if inactive_reason else ('computed' if ablation_delta is not None else 'unavailable'),
                "recommended": (
                    line.code in negative_codes if line.negative else line.code in recommended_codes
                ),
                "fatalNegative": fatal,
                "explanation": (
                    "消融口径（delta/ablationDelta）：同一配卡、同一目标与指标下"
                    "移除此词条后的变化；重优化口径（reoptimizedDelta）：移除词条"
                    "并允许重选普通 MOD 后的变化。负值代表该词条拖低目标指标"
                ),
            }
        )

    evaluation_target = None
    if benchmark_context is not None:
        target_record = benchmark_context.get("target")
        evaluation_target = {
            "enemyPath": target_record.get("path") if isinstance(target_record, Mapping) else None,
            "enemyName": (
                (target_record.get("nameEn") or target_record.get("name"))
                if isinstance(target_record, Mapping)
                else None
            ),
            "level": benchmark_context.get("level"),
            "steelPath": bool(benchmark_context.get("steel_path")),
            "enemyEnhancements": benchmark_context.get("enemy_enhancements"),
            "armourStrip": benchmark_context.get("armour_strip", 0.0),
            "elementalArmourStrip": benchmark_context.get("elemental_armour_strip", 0.0),
            "hitLocation": benchmark_context.get("hit_location", "body"),
            "headshotChance": benchmark_context.get("headshotChance", 0.0),
            "windowSeconds": benchmark_context.get("windowSeconds"),
        }
    context_payload = {
        "version": TARGET_CALIBRATION_VERSION,
        "buildLabel": exports.get("buildLabel"),
        "weapon": weapon.get("path"),
        "fireMode": fire_mode,
        "weaponType": weapon_type,
        "innateElements": weapon.get("innateElements") or (),
        "requestedTarget": requested_target_payload,
        "evaluationTarget": evaluation_target,
        "objectiveMetric": objective_metric,
        "scoreMetric": score_metric,
        "profile": profile_raw,
        "capacityLimit": capacity_limit,
        "disposition": disposition,
        "scenario": {
            **_scenario_context(scenario),
            "throwable": throwable,
            "incarnonChoices": resolved_choices,
            "arcanes": request.get("arcanes"),
        },
        "stance": (
            {
                "path": stance_info.get("path"),
                "dpsMultiplier": stance_multiplier,
                "statusRateMultiplier": status_rate_multiplier,
                "capacityGain": stance_capacity,
            }
            if stance_info
            else None
        ),
        "targetCalibration": {
            'version':TARGET_CALIBRATION_VERSION,
            'status':target_calibration.get('status'),
            'requestedLevel':target_calibration.get('requestedLevel'),
            'evaluationLevel':target_calibration.get('evaluationLevel'),
        },
    }
    context_hash = _evaluation_context_hash(context_payload)
    # ── F10（审计修复）：三轴状态合同统一 ──────────────────────────────
    # targetCalibrated 只在真正完成压力校准时为 true——capped-saturated
    # （到达等级上限仍饱和）与 post-search-saturated（赢家仍饱和）都不算
    # 已校准；skipped-by-request 也不算。旧实现把 capped-saturated 也标
    # true，且 targetStatus 把「跳过校准」也显示成 calibrated。
    calibration_status = str(target_calibration.get("status") or "")
    search_quality = {
        "objectiveMetric": objective_metric,
        "scoreMetric": score_metric,
        "fallbackReason": (
            "continuous-ranking-from-start" if score_metric != objective_metric else None
        ),
        "targetCalibrated": calibration_status == "calibrated",
        "targetCalibrationStatus": calibration_status or None,
        "qualityCalibrated": (
            not bool(request.get("_bakeStaticsOnly"))
            and score_metric != objective_metric
        ),
        "qualityCacheHit": quality_cache_hit,
        "profile": profile_raw,
        "bakeStaticsOnly": bool(request.get("_bakeStaticsOnly")),
    }
    optimality_status = {
        "baseline": "heuristic",
        "recommended": "heuristic",
        "scope": "beam-and-hill-climb",
    }
    model_uncertainty_tokens = (
        "radial-or-field",
        "projectile-component",
        "event-mechanic",
        "runtime",
        "conditional",
        "not-applied",
        "not-evaluated",
        "unmodeled",
    )
    model_uncertainty_reasons = sorted(
        {
            str(item)
            for build in (baseline, actual)
            for item in getattr(build.stats, "unsupported", ())
            if any(token in str(item).casefold() for token in model_uncertainty_tokens)
        }
    )
    if model_uncertainty_reasons:
        unsupported.append("analysis-model-partial")
    # targetStatus：区分 not-applicable（无靶）/ calibrated（压力验证通过）/
    # saturated-unresolved（饱和未解）/ skipped（请求跳过校准）。
    target_status = "not-applicable" if benchmark_context is None else (calibration_status or "fixed")
    model_status = (
        "partial"
        if any(
            token in str(item).casefold()
            for item in unsupported
            for token in (
                "unmodeled",
                "unavailable",
                "unsupported",
                "partial",
                "not-applied",
                "not-evaluated",
                "unresolved",
            )
        )
        else "modeled"
    )
    search_status = {
        "profile": profile_raw,
        "metric": ranking_metric,
        "scope": optimality_status["scope"],
        "status": "heuristic-best-found",
    }
    if cacheable and not ultra and statics is not None:
        statics["contextHash"] = context_hash
        statics["evaluationTarget"] = evaluation_target
        statics["targetCalibration"] = target_calibration
        statics["scoreMetric"] = score_metric
        statics["qualityCalibrated"] = bool(search_quality["qualityCalibrated"])
        statics_cache["__dirty__"] = True

    skipped = [
        # 评分靶自适应等中途模块的口径说明前置（skip 语义：非缺陷的口径注记）。
        *skipped_early,
        f"optimizer-assumption: 8 slots, {capacity_limit} capacity, Catalyst and matching Forma",
        (
            "optimizer-objective: expected heavy/throw damage; target resistances and status DOT excluded"
            if throwable
            else (
                "optimizer-objective: 面板普通攻击 DPS；派系歧视与敌方抗性不参与"
                if weapon_type == "melee"
                else (
                    f"靶子：Lv{evaluation_target.get('level') if evaluation_target else '?'} "
                    f"{'钢铁之路' if evaluation_target and evaluation_target.get('steelPath') else ''}凶魂百夫长"
                    "（去掉天生超宏，护甲 2700 参与）；"
                    f"弱点命中 {float(benchmark_context.get('headshotChance') or 0.0) * 100:.0f}%，其余为身体命中；"
                    "血量按本武器无紫卡基线的身体命中击杀时间取三个硬度节点"
                    + (
                        "（" + " / ".join(f"{node['ttkSeconds']:.1f}s" for node in target_calibration.get("hardnessNodes") or ()) + "）"
                        if target_calibration.get("hardnessNodes")
                        else f"（{HARDNESS_TTK_RANGE[0]:g}–{HARDNESS_TTK_RANGE[1]:g}s 区间）"
                    )
                    + f"，每个节点 {float(benchmark_context.get('windowSeconds') or 30.0):g}s 窗口回放，KPM 取加权几何平均并计入血量展布；"
                    "异常从零层叠起；同一武器的所有紫卡共用这组靶，增益可直接比较"
                    if benchmark_context is not None
                    else "optimizer-objective: 面板口径 · 触发按期望堆叠计入持续 DPS；不挂固定目标，派系歧视与敌方抗性不参与"
                )
            )
        ),
        (
            "灵化路线："
            + (f"使用灵化形态（模式 {fire_mode + 1}）" if fire_mode != 0 else "使用本体形态（模式 1）")
            + (
                "；进化 " + " / ".join(value for _, value in sorted(resolved_choices.items()))
                + ("（显式指定）" if request.get("incarnonChoices") else "（按武器默认策略选取，可在配装页改选）")
                if resolved_choices
                else ""
            )
            + "；灵化形态按常驻计算，“自身护盾 / 超宏击破”类进化效果按强制生效"
            if resolved_choices or weapon.get("isIncarnonForm")
            else (
                f"开火模式：使用模式 {fire_mode + 1}，其余模式仅展示"
            )
        ),
        *([route_note(melee_schedule, (stance_info or {}).get("nameZh") or (stance_info or {}).get("nameEn")
                      if melee_schedule and stance_info and stance_info.get("path") == melee_schedule.get("stance") else None)]
          if melee_context else []),
        "mod-family exclusivity checked by exported nameTag and weapon compatibility tags; account-specific conflicts are not exported",
        f"Riven template values recovered from frozen build {template_build}",
        "recommended Riven stats use theoretical max-roll values from the active frozen build",
        (
            "optimizer-profile: 快速档（beam 12/32，无爬山；词条分层为粗排口径）"
            if profile == "fast"
            else (
                "optimizer-profile: 标准档（beam 24/40，3 轮爬山）"
                if profile == "standard"
                else "optimizer-profile: 深度档（beam 24/56，12 轮全邻域爬山）"
            )
        ),
        f"optimizer-search: profile {profile}, {len(mod_pool)} candidate mods, {rejected_mods} unsupported mods rejected",
        *(
            [
                "optimizer-scope: 必选 "
                f"{len(search_required_keys)} 张 · 禁选 {len(search_forbidden_keys)} 张"
                + (
                    f" · 数量范围 {search_min_fill if search_min_fill is not None else 0}"
                    f"–{search_max_fill if search_max_fill is not None else 8}"
                    if search_min_fill is not None or search_max_fill is not None
                    else ""
                )
            ]
            if has_search_constraints
            else []
        ),
        *([skipped_hint] if skipped_hint else []),
        (
            f"target: {target_calibration.get('status')} · Lv{target_calibration.get('evaluationLevel')} · "
            "ttk " + "/".join(f"{node['ttkSeconds']:g}s" for node in target_calibration.get("hardnessNodes") or ())
            + " · health x" + "/".join(f"{node['healthScale']:.3g}" for node in target_calibration.get("hardnessNodes") or ())
        ),
    ]
    if stance_info:
        stance_name = (
            str(stance_info.get("nameZh") or stance_info.get("nameEn") or "")
            or _path_basename(str(stance_info.get("path") or ""))
        )
        skipped.append(
            f"optimizer-stance: 近战分析默认使用普攻 DPS 倍率最高的架势 {stance_name}"
            f"（×{stance_multiplier:.2f}，容量 +{stance_capacity}），其余架势不参与"
        )
    if heavy_default_state and not weapon.get("heavyAttack", {}).get("components"):
        unsupported.append("heavy-attack-route-unavailable-using-fire-mode-fallback")
        # Keep the historical diagnostic token for clients that surfaced it.
        unsupported.append("heavy-attack-dps-uses-normal-fire-mode-timing-and-no-heavy-multiplier")
    elif metric == "heavyAttackDps" and not heavy_default_state:
        unsupported.append("heavy-attack-dps-uses-normal-fire-mode-timing-and-no-heavy-multiplier")
    for build in (baseline, actual):
        unsupported.extend(build.stats.unsupported)
        skipped.extend(build.stats.skipped)
    timeline = None
    if timeline_seconds is not None:
        timeline = _arcane_timeline(
            exports.get("arcanes") or (),
            request.get("arcanes"),
            weapon,
            incarnon_card,
            baseline,
            actual,
            actual,
            actual_card,
            actual_card,
            scenario=scenario,
            metric=objective_metric,
            seconds=timeline_seconds,
        )
        skipped.append(
            "arcane timeline is an expected DPS envelope, not an enemy hit/status event replay"
        )
    _progress("payload")
    baseline_payload = _build_payload(weapon, baseline, None, passives)
    actual_payload = _build_payload(weapon, actual, actual_card, passives)
    # 无限极化口径的极化次数（只展示结果，不可调节）；近战带架势时按架势
    # 倍率放大普通攻击展示数值（与配装页 HUD 口径一致，重击不受架势影响）。
    for payload, evaluation, riven_card in (
        (baseline_payload, baseline, None),
        (actual_payload, actual, actual_card),
    ):
        payload["forma"] = _forma_summary(weapon, evaluation.cards, riven_card, stance_info)
        # 解算目标的原始分数（KPM 口径下即标准靶每分钟击杀数）：前端头条
        # 直接读取，不再从提升百分比反推。
        payload["objectiveScore"] = _score(evaluation.stats, objective_metric,
                                            target_context=benchmark_context)
        payload['objectiveMetric'] = objective_metric
        payload['optimizationMetric'] = ranking_metric
        payload['scoringMetric'] = score_metric
        payload['scoringScore'] = quality_scores['baseline' if evaluation is baseline else 'actual']
        if stance_multiplier != 1.0:
            for key in ("attackDps", "burstDps", "sustainedDps"):
                value = payload.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    payload[key] = value * stance_multiplier
    alternate_modes = _alternate_mode_payloads(
        weapon_record, actual, actual_card, passives, selected_fire_mode=fire_mode
    )
    if alternate_modes:
        actual_payload["alternateModes"] = alternate_modes
    if actual_payload.get("damageBasis") == "projectileEvents.minimum":
        unsupported = [
            item
            for item in unsupported
            if item != "projectile-component-damage-unapplied"
        ]
        skipped = [
            item
            for item in skipped
            if "unsupported[projectile-component-damage-unapplied]" not in item
        ]
    unsupported.extend(actual_payload.get("unsupported") or ())
    # Build-level diagnostics (including known radial/field and projectile
    # omissions) are appended only after payload construction, so finalize the
    # model status here instead of allowing a partial weapon to look modeled.
    model_status = (
        "partial"
        if any(
            token in str(item).casefold()
            for item in unsupported
            for token in (
                "unmodeled",
                "unavailable",
                "unsupported",
                "partial",
                "not-applied",
                "not-evaluated",
                "unresolved",
            )
        )
        else "modeled"
    )
    result = {
        "buildLabel": exports["buildLabel"],
        "schemaVersion": exports["schemaVersion"],
        "weapon": record_identity(weapon),
        "fireMode": fire_mode,
        "metric": metric,
        "scoreMetric": score_metric,
        "contextHash": context_hash,
        "evaluationScenario": _scenario_context(scenario),
        "requestedTarget": requested_target_payload,
        "evaluationTarget": evaluation_target,
        "targetCalibration": target_calibration,
        "searchQuality": search_quality,
        "modelStatus": model_status,
        "targetStatus": target_status,
        "searchStatus": search_status,
        "optimalityStatus": optimality_status,
        "scoringValues": {
            "baseline": quality_scores["baseline"],
            "actual": quality_scores["actual"],
        },
        "actualGain": actual_gain,
        "details": details,
        "recommendedPositive": [line.label for line in recommended],
        "recommendedPositiveTiers": recommended_tiers,
        "recommendedRoutes": None,
        "recommendedNegative": [line.label for line in recommended_negative],
        "fatalNegative": fatal_negative,
        "baseline": baseline_payload,
        "actual": actual_payload,
        "incarnonChoices": resolved_choices,
        "incarnonPolicy": incarnon_policy,
        "arcaneStates": arcane_states,
        "stance": (
            {
                "path": stance_info.get("path"),
                "nameZh": stance_info.get("nameZh") or stance_info.get("nameEn"),
                "dpsMultiplier": stance_multiplier,
                "capacityGain": stance_capacity,
                "builtIn": bool(stance_info.get("builtIn")),
            }
            if stance_info
            else None
        ),
        "unsupported": sorted(set(unsupported)),
        "skipped": list(dict.fromkeys(skipped)),
        "profile": profile_raw,
    }
    if timeline is not None:
        result["timeline"] = timeline
    if source_disposition is not None:
        result["projection"] = {
            "sourceDisposition": source_disposition,
            "targetDisposition": disposition,
            "scale": disposition_scale,
        }
    return result
