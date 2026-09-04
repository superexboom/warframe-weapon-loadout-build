"""Riven scoring and automatic weapon builds over one frozen export.

Riven values on the wire are the max-rank numbers printed on the card.  This
module converts them into :class:`ModEffect` objects and sends ordinary mods,
the actual Riven, and the recommended Riven through the same damage reducer.
The search is deliberately a bounded beam search: exports do not contain every
mutual-exclusion rule needed for an exact combinatorial solver.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from .damage import (
    BASE_ELEMENTS,
    ModEffect,
    ModEffectList,
    Scenario,
    SUPPORTED_WEAPON_UPGRADE_TYPES,
    apply_mods,
    arcane_effects,
    effective_hit_multiplier,
    expected_victim_status_count,
    _qualifier_rejection,
    sustained_status_damage,
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
    },
    "shotgun": {
        "0": 90.0, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.997, "9": 119.997, "A": 119.997,
        "C": 45.0, "D": 164.7, "F": 49.995, "G": 45.0,
        "I": 45.0, "L": 49.995, "M": 90.0, "P": 2.7,
        "R": 90.0, "S": 119.7, "V": 90.0, "Z": 90.0,
    },
    "pistol": {
        "0": 149.994, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.997, "9": 119.997, "A": 119.997,
        "C": 45.0, "D": 219.6, "F": 49.995, "G": 45.0,
        "H": 80.1, "I": 45.0, "L": 49.995, "M": 90.0,
        "P": 2.7, "R": 74.7, "S": 119.7, "V": 90.0, "Z": 90.0,
    },
    "archgun": {
        "0": 99.9, "1": 80.1, "2": 60.3, "3": 99.99,
        "4": 119.7, "5": 119.7, "6": 119.7, "7": 119.7,
        "8": 90.0, "9": 90.0, "A": 90.0,
        "C": 45.0, "D": 99.9, "F": 99.9, "G": 45.0,
        "H": 59.994, "L": 60.3, "M": 99.9, "P": 2.7,
        "R": 60.03, "S": 60.3, "Z": 90.0,
    },
    "melee": {
        "0": 180.0, "1": 90.0, "2": 90.0, "3": 99.99,
        "4": 90.0, "5": 90.0, "6": 90.0, "7": 90.0,
        "8": 119.7, "9": 119.7, "A": 119.7,
        "B": 24.5016, "C": 45.0, "E": 120.006, "G": 45.0,
        "I": 45.0, "J": 54.9, "K": 164.7, "N": 8.1,
        "O": 58.77, "Q": 104.85, "T": 1.9422, "U": 73.44,
        "X": 119.7,
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
}


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
        if len(upgrades) != 1 or not isinstance(upgrades[0], Mapping):
            continue
        upgrade = upgrades[0]
        matches = []
        for code, rule in RIVEN_RULES.items():
            _label, upgrade_type, operation, damage_type, symbol_filter, unit, *_rest = rule
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
            if not symbol_filter and raw_symbol:
                continue
            matches.append((code, unit))
        raw_value = upgrade.get("rawValue")
        if len(matches) != 1 or isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            continue
        code, unit = matches[0]
        result[code] = abs(float(raw_value)) * (90.0 if unit == "flat" else 9000.0)
    return result

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


def _mod_card(
    mod: Mapping[str, Any],
    scenario: Scenario,
    *,
    required: bool = False,
    allow_empty: bool = False,
    set_shell: Mapping[str, Any] | None = None,
) -> _Card | None:
    rank = int(mod.get("maxRank") or 0)
    effects = mod_effects(mod, rank, _steady_state_scenario((mod,), scenario))
    active = tuple(
        effect
        for effect in effects
        if effect.supported and effect.upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES
    )
    if not active and not allow_empty:
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
            or "/PvPMods/" in path
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
    return {**weapon, "fireModes": [modes[index]]}, index


def _path_basename(value: Any) -> str:
    return str(value or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def _branch_effects(branch: Mapping[str, Any]) -> tuple[list[ModEffect], list[str]]:
    source = str(branch.get("path") or branch.get("id") or "incarnon")
    effects: list[ModEffect] = []
    unsupported: list[str] = []
    for raw in branch.get("effects") or ():
        if not isinstance(raw, Mapping):
            continue
        effect = ModEffect.from_export(raw, 0, source_path=source)
        if effect.supported:
            effects.append(effect)
        else:
            unsupported.append(
                f"incarnon-{branch.get('id')}-{effect.upgrade_type}-not-evaluated"
            )
    if branch.get("conditionalEffects"):
        unsupported.append(f"incarnon-{branch.get('id')}-conditional-effects-not-applied")
    if branch.get("runtimeScripts"):
        unsupported.append(f"incarnon-{branch.get('id')}-runtime-scripts-not-applied")
    if branch.get("unresolvedReferences"):
        unsupported.append(f"incarnon-{branch.get('id')}-unresolved-references")
    return effects, unsupported


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
        if tier in {2, 3, 4} and (
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
        # Tier 1 is the fixed Incarnon-form unlock (not a UI branch choice).
        # The selected fire mode already represents that form; applying its
        # runtime unlock again would only create false unsupported warnings.
        if tier == 1:
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
                trial = ModEffectList([*selected_effects, *candidate_effects])
                try:
                    stats = apply_mods(weapon, trial, scenario=scenario)
                    events = evaluate_projectile_events(
                        weapon, trial, scenario=scenario
                    )
                    candidate_score = _score(stats, metric, events)
                except (TypeError, ValueError):
                    candidate_score = -math.inf
                if branch is None or candidate_score > best_score:
                    best_score, branch = candidate_score, candidate
            unsupported.append(f"incarnon-tier{tier}-auto-selected-static-objective")

        assert branch is not None
        branch_effects, branch_unsupported = _branch_effects(branch)
        selected_effects.extend(branch_effects)
        unsupported.extend(branch_unsupported)
        selected[f"tier{tier}"] = str(branch.get("id") or branch.get("path") or "")
        if policy_choice and not normalized.get(tier) and selected[f"tier{tier}"] == policy_choice:
            policy_used.append(f"tier{tier}")

    if policy_meta:
        policy_meta["appliedTiers"] = policy_used

    if not selected_effects:
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
    return applied_stacks, effect_uptime, expected_stacks, active_uptime, {
        "triggerChance": chance,
        "durationSeconds": duration,
        "maxStacks": limit,
        "stackMode": str(trigger.get("stackMode") or ""),
        "triggerCondition": str(trigger.get("conditionTag") or ""),
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
    weapon_arcane_count = 0
    frame_arcane_count = 0
    queries: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(requested):
        if not isinstance(raw, Mapping):
            raise SimulationError(f"arcane state {index} must be an object")
        query_raw = raw.get("query")
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
        trigger = arcane.get("trigger")
        if isinstance(trigger, Mapping):
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
                    "triggerCondition": str(trigger.get("conditionTag") or ""),
                }
            )
        implicit_heavy_state = (
            default_heavy_state
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
            if weapon_arcane_count > 1:
                raise SimulationError("at most one weapon Arcane may be selected")
        if arcane.get("unresolvedReferences"):
            unsupported.append(f"arcane-state-{index}-has-unresolved-references")
            continue
        effect_stacks = wire_stacks
        effect_uptime = wire_uptime
        if requested_rate is not None:
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
            state["active"] = bool(state["expectedStacks"])
            state["applied"] = True
            state["effectCount"] = len(supported_effects)
        else:
            state["error"] = "no supported static effect"
            unsupported.append(f"arcane-state-{index}-no-supported-effects")

    card = None
    if combined or skipped:
        card = _Card(
            key="__arcanes__",
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
    return _metrics(stats, projectile_events)[
        "heavyDamage" if metric == "heavyAttackDps" else metric
    ]


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
    target_context: Mapping[str, Any] | None = None,
) -> _Evaluation | None:
    if len(cards) + (1 if riven else 0) > slot_limit:
        return None
    positions: Iterable[int | None] = (None,)
    if riven is not None:
        polarity_sensitive = False  # all cards use matching Forma in this model
        element_sensitive = any(
            effect.damage_type in BASE_ELEMENTS for effect in riven.effects
        )
        positions = range(len(cards) + 1) if element_sensitive or polarity_sensitive else (len(cards),)
    best: _Evaluation | None = None
    for position in positions:
        ordered = list(cards)
        if riven is not None and position is not None:
            ordered.insert(position, riven)
        capacity = _capacity(ordered)
        if capacity > capacity_limit:
            continue
        effect_cards = [passives, *ordered] if passives is not None else ordered
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
        current = _Evaluation(
            score=_score(stats, metric, projectile_events, target_context),
            cards=tuple(cards),
            stats=stats,
            capacity=capacity,
            riven_index=position if riven is not None else None,
            scenario=derived_scenario,
        )
        if best is None or current.score > best.score:
            best = current
    return best


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
) -> _Evaluation:
    if isinstance(slot_count, bool) or not isinstance(slot_count, int) or not 1 <= slot_count <= 8:
        raise SimulationError("slot_count must be an integer between 1 and 8")
    if isinstance(capacity_limit, bool) or not isinstance(capacity_limit, int) or capacity_limit < 0:
        raise SimulationError("capacity_limit must be a non-negative integer")
    required_cards = tuple(card for card in candidates if card.required)
    candidates = tuple(card for card in candidates if not card.required)
    limit = slot_count - len(required_cards) - (1 if riven else 0)
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
    for card in candidates:
        evaluated = _evaluate(
            weapon,
            (*required_cards, card),
            riven,
            scenario=scenario,
            metric=metric,
            passives=passives,
            slot_limit=slot_count,
            capacity_limit=capacity_limit,
            target_context=target_context,
        )
        if evaluated is not None:
            ranked.append((evaluated.score, card))
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
    for _ in range(limit):
        expanded: list[tuple[tuple[int, ...], _Evaluation]] = []
        for selected, _previous in beam:
            used = set(selected)
            used_families = {_mod_family(pool[index]) for index in selected}
            for index in range(len(pool)):
                if index in used or _mod_family(pool[index]) in used_families:
                    continue
                next_selected = (*selected, index)
                evaluated = _evaluate(
                    weapon,
                    (*required_cards, *(pool[item] for item in next_selected)),
                    riven,
                    scenario=scenario,
                    metric=metric,
                    passives=passives,
                    slot_limit=slot_count,
                    capacity_limit=capacity_limit,
                    target_context=target_context,
                )
                if evaluated is not None:
                    expanded.append((next_selected, evaluated))
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
    # Fill otherwise-neutral slots as long as the loadout remains legal.  The
    # damage score alone cannot distinguish an empty slot from a useful utility
    # card whose modeled contribution is zero (range, ammo mutation, etc.).
    if len(best.cards) + (1 if riven else 0) < slot_count:
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
            if filled is None or not eligible(filled):
                continue
            best = filled
            used_keys.add(card.key)
            used_families.add(family)
            if len(best.cards) + (1 if riven else 0) >= slot_count:
                break
    return best


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
) -> _Evaluation:
    required = tuple(card for card in base_cards if card.required)
    optional = tuple(card for card in base_cards if not card.required)
    max_keep = min(len(optional), 7 - len(required))
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
            return max(evaluated, key=lambda value: value.score)
    raise SimulationError("no capacity-valid build can equip the Riven")


def _candidate_lines(
    weapon_type: str,
    disposition: float,
    actual: Sequence[_RivenLine],
    *,
    negative: bool,
    bases: Mapping[str, float] | None = None,
) -> tuple[list[_RivenLine], bool]:
    bases = dict(bases or RIVEN_BASE_VALUES[weapon_type])
    ratios = []
    for line in actual:
        base = bases.get(line.code)
        if line.negative == negative and base and disposition > 0 and line.high > 0:
            ratios.append(line.high / (base * disposition))
    calibrated = bool(ratios)
    if ratios:
        roll_scale = median(ratios)
    else:
        positive_count = sum(not line.negative for line in actual)
        has_curse = any(line.negative for line in actual)
        # Widely used nominal structure factors; the response marks this fallback
        # as heuristic because the randomized fingerprint formula is not decoded.
        roll_scale = (0.75 if positive_count >= 3 else 1.0) * (1.25 if has_curse else 1.0) * 1.1

    lines: list[_RivenLine] = []
    for code, base in bases.items():
        rule = RIVEN_RULES.get(code)
        if rule is None:
            continue
        can_roll = rule[8] if negative else rule[7]
        if not can_roll:
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
) -> tuple[list[_RivenLine], _Evaluation, list[dict[str, Any]]]:
    ranked: list[tuple[float, _RivenLine]] = []
    for line in candidates:
        if line.effect is None or not line.effect.supported:
            continue
        result = _best_fixed(
            weapon,
            baseline.cards,
            _card_from_lines([line]),
            scenario=scenario,
            metric=metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=target_context,
        )
        ranked.append((result.score, line))
    ranked.sort(key=lambda item: (-item[0], item[1].code))
    shortlist = [line for _, line in ranked[: max(8, count)]]
    if len(shortlist) < count:
        raise SimulationError("not enough supported Riven stats for this weapon")
    best_lines: tuple[_RivenLine, ...] | None = None
    best_result: _Evaluation | None = None
    for combo in itertools.combinations(shortlist, count):
        result = _best_fixed(
            weapon,
            baseline.cards,
            _card_from_lines(combo),
            scenario=scenario,
            metric=metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=target_context,
        )
        if best_result is None or result.score > best_result.score:
            best_lines, best_result = combo, result
    assert best_lines is not None and best_result is not None

    # Score each affix in a full-card context. A one-line Riven can lose to the
    # mod slot it replaces even when that affix is valuable on a complete card.
    marginal: list[tuple[float, _RivenLine]] = []
    anchor_results: dict[tuple[str, ...], _Evaluation] = {}
    for _, line in ranked:
        anchor = tuple(item for item in best_lines if item.code != line.code)[: count - 1]
        if len(anchor) < count - 1:
            anchor = tuple(best_lines[: count - 1])
        anchor_key = tuple(item.code for item in anchor)
        without = anchor_results.get(anchor_key)
        if without is None:
            without = _best_fixed(
                weapon,
                baseline.cards,
                _card_from_lines(anchor),
                scenario=scenario,
                metric=metric,
                passives=passives,
                capacity_limit=capacity_limit,
                target_context=target_context,
            )
            anchor_results[anchor_key] = without
        with_line = _best_fixed(
            weapon,
            baseline.cards,
            _card_from_lines((*anchor, line)),
            scenario=scenario,
            metric=metric,
            passives=passives,
            capacity_limit=capacity_limit,
            target_context=target_context,
        )
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


def _scenario(metric: str) -> Scenario:
    return Scenario(heavy_attack=metric in {"heavyAttackDps", "heavyDamage"})


def _percent_gain(value: float, baseline: float) -> float:
    return (value / baseline - 1.0) * 100.0 if baseline > 0 else 0.0


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
            "isIncarnonForm": bool(weapon.get("isIncarnon"))
            and mode_count > 1
            and index == mode_count - 1,
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
    for card in evaluation.cards:
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
                "maxRank": card.record.get("maxRank"),
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


def analyze_riven_request(
    export_dir: str | Path,
    request: Mapping[str, Any],
    weapon_record: Mapping[str, Any] | None = None,
    stance: Mapping[str, Any] | None = None,
    statics_cache: dict[str, Any] | None = None,
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
    """
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
            if tier not in {2, 3, 4}:
                raise SimulationError(
                    f"incarnon choice tier {key!r} must select Evo II, III or IV"
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
    metric = (
        "heavyDamage"
        if throwable
        else (
            "attackDps"
            if weapon_type == "melee"
            else "statusSustainedDps"
        )
    )
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
    scenario = _scenario(metric)
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
    if not actual_lines:
        unsupported.append("riven-request-has-no-usable-stats")
    if not weapon.get("omegaAttenuation") and request.get("disposition") in (None, 0):
        unsupported.append("riven-disposition-missing-using-1.0")
    if metric_warning:
        unsupported.append(metric_warning)
    template_bases = _template_bases(exports.get("rivenTemplates") or {}, weapon_type)
    template_build = str((exports.get("rivenTemplates") or {}).get("buildLabel") or RIVEN_TEMPLATE_BUILD)
    if not template_bases and exports["buildLabel"] != RIVEN_TEMPLATE_BUILD:
        unsupported.append(
            f"riven-template-values-pinned-to-{RIVEN_TEMPLATE_BUILD}"
        )
    if any(line.code in {"C", "G", "I"} for line in actual_lines):
        unsupported.append("faction-riven-stats-excluded-from-target-neutral-objective")

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

    # 静态解算结果缓存：基准配装、双路推荐与理论上限都不随单张紫卡的数值
    # 变化（推荐候选恒为理论满数值口径），仅依赖武器/开火模式/倾向/容量上限
    # 与默认灵化策略；组合装配、显式灵化/赋能、时间线请求绕过缓存，与黑猫
    # bot 的「推荐预计算、数据变动后重算」口径一致。
    cacheable = (
        statics_cache is not None
        and not record_overridden
        and request.get("incarnonChoices") is None
        and request.get("arcanes") is None
        and timeline_seconds is None
    )
    cache_key = f"{weapon.get('path')}#mode{fire_mode}"
    statics: dict[str, Any] | None = None
    if cacheable:
        candidate_entry = statics_cache.get(cache_key)
        if (
            isinstance(candidate_entry, dict)
            and candidate_entry.get("disposition") == disposition
            and candidate_entry.get("metric") == objective_metric
            and candidate_entry.get("capacityLimit") == capacity_limit
        ):
            statics = candidate_entry
    if cacheable and statics is None:
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
        return _evaluate(
            weapon,
            tuple(pool_by_key[key] for key in card_keys),
            riven_card,
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )

    baseline = _reconstruct(statics.get("baselineCards"), None) if statics else None
    baseline_fresh = baseline is None
    if baseline_fresh:
        baseline = _optimize(
            weapon,
            mod_pool,
            None,
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )

    def _apply_riven_floor(result: _Evaluation, riven_card: _Card) -> _Evaluation:
        # 梁搜索在强制含紫卡时可能中途剪掉「无紫卡最优 − 最弱卡 + 紫卡」这条
        # 显而易见的路径（部分配装在前几层协同未成形就被淘汰）。用它做下限，
        # 避免「带紫卡反而比不带差」的假性负收益。
        floor: _Evaluation | None = None
        for drop in range(len(baseline.cards) + 1):
            kept = tuple(
                card for index, card in enumerate(baseline.cards) if index != drop
            )
            evaluated = _evaluate(
                weapon,
                kept,
                riven_card,
                scenario=scenario,
                metric=objective_metric,
                passives=passives,
                capacity_limit=capacity_limit,
            )
            if evaluated is not None and (floor is None or evaluated.score > floor.score):
                floor = evaluated
        if floor is not None and floor.score > result.score:
            return floor
        return result

    actual_card = _card_from_lines(actual_lines)
    actual = _apply_riven_floor(
        _optimize(
            weapon,
            mod_pool,
            actual_card,
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        ),
        actual_card,
    )

    positive_candidates, _ = _candidate_lines(
        weapon_type, disposition, (), negative=False, bases=template_bases
    )
    candidate_by_code = {line.code: line for line in positive_candidates}
    negative_candidates, _ = _candidate_lines(
        weapon_type, disposition, (), negative=True, bases=template_bases
    )
    negative_by_code = {line.code: line for line in negative_candidates}
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
    if recommended_fresh:
        recommended, recommended_result, recommended_tiers = _recommend_positive(
            weapon,
            baseline,
            positive_candidates,
            positive_count,
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )
    else:
        recommended = cached_recommended
        recommended_result = None
        recommended_tiers = bundle["tiers"]

    # 双路推荐（枪械）：触发 / 直伤两组推荐词条，两条路线都是「8 槽预留
    # 紫卡位」的含紫卡口径——回答「这张紫卡填什么词条、以及同一张紫卡下配
    # 触发还是配直伤伤害更高」；近战与投掷重击维持单组。
    dual_routes = weapon_type != "melee" and not throwable
    recommended_routes: dict[str, Any] | None = None
    fresh_route_baselines: dict[str, list[str]] = {}
    routes_fresh = False
    if dual_routes:
        recommended_routes = {}
        cached_routes = bundle.get("routes") if bundle is not None else None
        for route_key, route_metric in (
            ("status", objective_metric),
            ("direct", "sustainedDps"),
        ):
            cached_route = (
                cached_routes.get(route_key)
                if isinstance(cached_routes, dict)
                else None
            )
            if (
                isinstance(cached_route, dict)
                and isinstance(cached_route.get("tiers"), list)
                and isinstance(cached_route.get("score"), (int, float))
                and not isinstance(cached_route.get("score"), bool)
            ):
                recommended_routes[route_key] = {
                    "tiers": cached_route["tiers"],
                    "score": float(cached_route["score"]),
                }
                continue
            routes_fresh = True
            if route_metric == objective_metric:
                if recommended_result is not None:
                    # 主推荐与触发路线同参同解，直接复用，避免冷路径重复穷举。
                    recommended_routes[route_key] = {
                        "tiers": recommended_tiers,
                        "score": recommended_result.score,
                    }
                    continue
                route_baseline = baseline
            else:
                route_baseline = None
                cached_route_baseline = statics.get("routesBaseline") if statics else None
                if isinstance(cached_route_baseline, dict):
                    route_baseline = _reconstruct(cached_route_baseline.get(route_key), None)
                if route_baseline is None:
                    route_baseline = _optimize(
                        weapon,
                        mod_pool,
                        None,
                        scenario=scenario,
                        metric=route_metric,
                        passives=passives,
                        capacity_limit=capacity_limit,
                    )
                    fresh_route_baselines[route_key] = [
                        card.key for card in route_baseline.cards
                    ]
            _route_lines, route_best, route_tiers = _recommend_positive(
                weapon,
                route_baseline,
                positive_candidates,
                positive_count,
                scenario=scenario,
                metric=route_metric,
                passives=passives,
                capacity_limit=capacity_limit,
            )
            recommended_routes[route_key] = {
                "tiers": route_tiers,
                "score": route_best.score,
            }

    negative_ranked: list[tuple[float, _RivenLine]] = []
    # These lines are deliberately objective-neutral in the default snapshots:
    # reserve ammo/recoil for guns and finisher damage for normal/heavy melee.
    neutral_negative_codes = {"M", "Z"} if weapon_type != "melee" else {"X"}
    for line in negative_candidates:
        if (
            line.code not in neutral_negative_codes
            or line.effect is None
            or not line.effect.supported
        ):
            continue
        result = _best_fixed(
            weapon,
            baseline.cards,
            _card_from_lines([*recommended, line]),
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )
        negative_ranked.append((result.score, line))
    negative_ranked.sort(key=lambda item: (-item[0], item[1].code))
    recommended_negative = [line for _, line in negative_ranked[:3]]
    if not recommended_negative:
        unsupported.append("no-objective-neutral-supported-negative-stat")

    has_negative = any(line.negative for line in actual_lines)
    optimal_lines = list(recommended)
    if has_negative and recommended_negative:
        optimal_lines.append(recommended_negative[0])
    optimal_card = _card_from_lines(optimal_lines)
    opt_slot = "optimalNeg" if has_negative else "optimalClean"
    cached_optimal = bundle.get(opt_slot) if bundle is not None else None
    optimal = None
    if (
        isinstance(cached_optimal, dict)
        and list(cached_optimal.get("riven") or []) == [line.code for line in optimal_lines]
    ):
        optimal = _reconstruct(cached_optimal.get("cards"), optimal_card)
    optimal_fresh = optimal is None
    if optimal_fresh:
        optimal = _apply_riven_floor(
            _optimize(
                weapon,
                mod_pool,
                optimal_card,
                scenario=scenario,
                metric=objective_metric,
                passives=passives,
                capacity_limit=capacity_limit,
            ),
            optimal_card,
        )

    # 回写静态缓存（仅本次新算的部分；高数值/当前紫卡反超修正不影响缓存）。
    if cacheable and statics is not None and (
        baseline_fresh or recommended_fresh or routes_fresh or optimal_fresh
    ):
        statics["disposition"] = disposition
        statics["metric"] = objective_metric
        statics["capacityLimit"] = capacity_limit
        if baseline_fresh:
            statics["baselineCards"] = [card.key for card in baseline.cards]
        if fresh_route_baselines:
            routes_baseline = statics.setdefault("routesBaseline", {})
            if isinstance(routes_baseline, dict):
                routes_baseline.update(fresh_route_baselines)
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
        if dual_routes and routes_fresh and recommended_routes is not None:
            write_bundle["routes"] = recommended_routes
        if optimal_fresh:
            write_bundle[opt_slot] = {
                "cards": [card.key for card in optimal.cards],
                "riven": [line.code for line in optimal_lines],
            }
        statics_cache["__dirty__"] = True

    # The current roll at its published high bounds is a hard lower bound for a
    # theoretical optimum.  This catches beam-shortlist misses without assigning
    # hand-written weights to stat names.
    high_actual = [
        candidate_by_code[line.code]
        for line in actual_lines
        if not line.negative and line.code in candidate_by_code
    ]
    # 满数值卡与理论上限卡同构（正词条集合一致）时跳过重复解算——含元素词条
    # 的紫卡这次解算要枚举元素摆放位置，是目前最贵的单次调用；词条集合级分数
    # 也进缓存，同集合不再重算。
    if len(high_actual) == positive_count and {line.code for line in high_actual} != {
        line.code for line in recommended
    }:
        high_key = (
            "|".join(sorted(line.code for line in high_actual))
            + ("!neg" if has_negative and recommended_negative else "")
        )
        high_lines = list(high_actual)
        if has_negative and recommended_negative:
            high_lines.append(recommended_negative[0])
        high_card = _card_from_lines(high_lines)
        cached_high = None
        if bundle is not None and isinstance(bundle.get("high"), dict):
            candidate_high = bundle["high"].get(high_key)
            if (
                isinstance(candidate_high, Mapping)
                and isinstance(candidate_high.get("score"), (int, float))
                and not isinstance(candidate_high.get("score"), bool)
            ):
                cached_high = candidate_high
        high_result = None
        recompute_high = cached_high is None
        if cached_high is not None:
            if float(cached_high["score"]) > optimal.score:
                # 缓存的满数值配卡曾反超上限：直接重建，零解算反超。
                high_result = _reconstruct(cached_high.get("cards"), high_card)
                recompute_high = high_result is None  # 缓存配卡失效时重算
        if recompute_high:
            high_result = _apply_riven_floor(
                _optimize(
                    weapon,
                    mod_pool,
                    high_card,
                    scenario=scenario,
                    metric=objective_metric,
                    passives=passives,
                    capacity_limit=capacity_limit,
                ),
                high_card,
            )
            if cacheable and statics is not None:
                counts = statics.get("counts")
                if isinstance(counts, dict):
                    write_bundle = counts.get(count_key)
                    if isinstance(write_bundle, dict):
                        write_bundle.setdefault("high", {})[high_key] = {
                            "score": high_result.score,
                            "cards": [card.key for card in high_result.cards],
                        }
                        statics_cache["__dirty__"] = True
        if high_result is not None and high_result.score > optimal.score:
            recommended = high_actual
            optimal_lines, optimal_card, optimal = high_lines, high_card, high_result
    if actual.score > optimal.score:
        unsupported.append("optimizer-optimum-lower-bound-used-actual-riven")
        optimal_lines, optimal_card, optimal = list(actual_lines), actual_card, actual
        recommended = [line for line in actual_lines if not line.negative]

    actual_gain = _percent_gain(actual.score, baseline.score)
    optimal_gain = _percent_gain(optimal.score, baseline.score)
    score = 0.0
    if optimal.score > baseline.score:
        score = max(
            0.0,
            min(100.0, (actual.score - baseline.score) / (optimal.score - baseline.score) * 100.0),
        )
    qualities = [_quality(line) for line in actual_lines if line.high > line.low]
    roll_quality = sum(qualities) / len(qualities) if qualities else 0.0

    recommended_codes = {line.code for line in recommended}
    negative_codes = {line.code for line in recommended_negative}
    details = []
    fatal_negative: list[str] = []
    for line in actual_lines:
        without = _card_from_lines([item for item in actual_lines if item.code != line.code])
        removed = _best_fixed(
            weapon,
            actual.cards,
            without,
            scenario=scenario,
            metric=objective_metric,
            passives=passives,
            capacity_limit=capacity_limit,
        )
        delta = _percent_gain(actual.score, removed.score)
        fatal = line.negative and delta < -5.0
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
                "delta": delta,
                "recommended": (
                    line.code in negative_codes if line.negative else line.code in recommended_codes
                ),
                "fatalNegative": fatal,
                "explanation": (
                    "同一配卡移除此词条后的目标伤害变化；负值代表该词条拖低目标指标"
                ),
            }
        )

    skipped = [
        f"optimizer-assumption: 8 slots, {capacity_limit} capacity, Catalyst and matching Forma",
        (
            "optimizer-objective: expected heavy/throw damage; target resistances and status DOT excluded"
            if throwable
            else (
                "optimizer-objective: 面板普通攻击 DPS；派系歧视与敌方抗性不参与"
                if weapon_type == "melee"
                else "optimizer-objective: 面板口径 · 触发按期望堆叠计入持续 DPS；不挂固定目标，派系歧视与敌方抗性不参与"
            )
        ),
        (
            f"optimizer-fire-mode: 灵化武器默认使用灵化形态（模式 {fire_mode + 1}），其余模式仅展示"
            if fire_mode != 0
            else "optimizer-fire-mode: primary mode 0 only; alternate modes are display-only"
        ),
        "mod-family exclusivity checked by exported nameTag and weapon compatibility tags; account-specific conflicts are not exported",
        f"Riven template values recovered from frozen build {template_build}",
        "recommended Riven stats use theoretical max-roll values from the active frozen build",
        f"optimizer-search: beam width 24, shortlist 56, {len(mod_pool)} candidate mods, {rejected_mods} unsupported mods rejected",
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
    for build in (baseline, actual, optimal):
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
            optimal,
            actual_card,
            optimal_card,
            scenario=scenario,
            metric=objective_metric,
            seconds=timeline_seconds,
        )
        skipped.append(
            "arcane timeline is an expected DPS envelope, not an enemy hit/status event replay"
        )
    baseline_payload = _build_payload(weapon, baseline, None, passives)
    actual_payload = _build_payload(weapon, actual, actual_card, passives)
    optimal_payload = _build_payload(weapon, optimal, optimal_card, passives)
    # 无限极化口径的极化次数（只展示结果，不可调节）；近战带架势时按架势
    # 倍率放大普通攻击展示数值（与配装页 HUD 口径一致，重击不受架势影响）。
    for payload, evaluation, riven_card in (
        (baseline_payload, baseline, None),
        (actual_payload, actual, actual_card),
        (optimal_payload, optimal, optimal_card),
    ):
        payload["forma"] = _forma_summary(weapon, evaluation.cards, riven_card, stance_info)
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
    result = {
        "buildLabel": exports["buildLabel"],
        "schemaVersion": exports["schemaVersion"],
        "weapon": record_identity(weapon),
        "fireMode": fire_mode,
        "metric": metric,
        "score": score,
        "grade": _grade(score),
        "actualGain": actual_gain,
        "optimalGain": optimal_gain,
        "rollQuality": roll_quality,
        "details": details,
        "recommendedPositive": [line.label for line in recommended],
        "recommendedPositiveTiers": recommended_tiers,
        "recommendedRoutes": recommended_routes,
        "recommendedNegative": [line.label for line in recommended_negative],
        "fatalNegative": fatal_negative,
        "baseline": baseline_payload,
        "actual": actual_payload,
        "optimal": optimal_payload,
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
