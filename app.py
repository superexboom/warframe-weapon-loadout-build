from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import hashlib
import json
import math
import mimetypes
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import traceback
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit
import webbrowser

from data_sources import export_dir as active_export_dir

ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / "vendor"
EXPORT_DIR = active_export_dir(ROOT)
ENEMY_OVERRIDE_PATH = EXPORT_DIR / "enemy_overrides.json"
INCARNON_STRINGS_PATH = EXPORT_DIR / "incarnon_strings.json"
STANCE_DATA_PATH = ROOT / "data" / "stances.json"
UTILITY_MOD_DATA_PATH = ROOT / "data" / "utility_mods.json"
EXALTED_WEAPON_DATA_PATH = ROOT / "data" / "exalted_weapons.json"
WARFRAME_DATA_PATH = ROOT / "data" / "warframe_build_data.json"
FRONTEND_DIR = ROOT / "frontend"
MAX_REQUEST_BYTES = 128 * 1024
RIVEN_SLOTS = {"primary", "secondary", "melee"}
BUILD_METRICS = {
    "gun": (
        {"id": "sustainedDps", "label": "持续 DPS"},
        {"id": "burstDps", "label": "爆发 DPS"},
        {"id": "shotDamage", "label": "单次伤害"},
    ),
    "melee": (
        {"id": "attackDps", "label": "攻击 DPS"},
        {"id": "heavyDamage", "label": "重击伤害"},
    ),
}
ELEMENT_TARGETS = {
    "heat": ("DT_FIRE", "火焰"),
    "cold": ("DT_FREEZE", "冰冻"),
    "electricity": ("DT_ELECTRICITY", "电击"),
    "toxin": ("DT_POISON", "毒素"),
    "blast": ("DT_EXPLOSION", "爆炸"),
    "radiation": ("DT_RADIATION", "辐射"),
    "gas": ("DT_GAS", "毒气"),
    "magnetic": ("DT_MAGNETIC", "磁力"),
    "viral": ("DT_VIRAL", "病毒"),
    "corrosive": ("DT_CORROSIVE", "腐蚀"),
}

_SIMPLE_ELEMENT_LABELS = {
    "DT_FIRE": "火焰",
    "DT_FREEZE": "冰冻",
    "DT_ELECTRICITY": "电击",
    "DT_POISON": "毒素",
}
_ELEMENT_COMPOUNDS = {
    frozenset(("DT_FIRE", "DT_FREEZE")): "爆炸",
    frozenset(("DT_FIRE", "DT_ELECTRICITY")): "辐射",
    frozenset(("DT_FIRE", "DT_POISON")): "毒气",
    frozenset(("DT_FREEZE", "DT_ELECTRICITY")): "磁力",
    frozenset(("DT_FREEZE", "DT_POISON")): "病毒",
    frozenset(("DT_ELECTRICITY", "DT_POISON")): "腐蚀",
}
_DAMAGE_TYPE_FAILURE_PREFIX = "no capacity-valid build satisfies damage type"


def _weapon_native_simple_elements(weapon: Mapping[str, Any]) -> set[str]:
    """Simple elements baked into the weapon itself (innate / chamber base)."""
    native = {
        str(entry.get("damageType"))
        for entry in weapon.get("innateElements") or ()
        if isinstance(entry, Mapping) and entry.get("damageType") in _SIMPLE_ELEMENT_LABELS
    }
    for mode in weapon.get("fireModes") or ():
        damage = mode.get("damage") if isinstance(mode, Mapping) else None
        if not isinstance(damage, Mapping):
            continue
        for dtype in (damage.get("types") or {}):
            if dtype in _SIMPLE_ELEMENT_LABELS:
                native.add(dtype)
        radial = damage.get("radial")
        if isinstance(radial, Mapping):
            for dtype in (radial.get("types") or {}):
                if dtype in _SIMPLE_ELEMENT_LABELS:
                    native.add(dtype)
    return native


def _translate_damage_type_failure(
    exc: SimulationError,
    weapon: Mapping[str, Any],
    required_damage_type: str | None,
    element_target: Mapping[str, Any] | None,
) -> SimulationError:
    """把求解器的元素约束失败翻译成中文，并解释自带元素吸收目标的情况。"""
    message = str(exc)
    if not message.startswith(_DAMAGE_TYPE_FAILURE_PREFIX) or not required_damage_type:
        return exc
    label = str((element_target or {}).get("label") or required_damage_type)
    if required_damage_type in _SIMPLE_ELEMENT_LABELS:
        for native in sorted(_weapon_native_simple_elements(weapon)):
            if native == required_damage_type:
                continue
            compound = _ELEMENT_COMPOUNDS.get(frozenset((native, required_damage_type)))
            native_label = _SIMPLE_ELEMENT_LABELS[native]
            return SimulationError(
                f"没有满足「{label}」元素要求的可行配装：该武器自带{native_label}伤害会最后参与元素复合，"
                f"{label} Mod 会被强制合成为{compound or '复合元素'}，无法单独保留{label}。"
                f"请改选其他元素目标（如{compound or '复合元素'}）或更换部件/武器。"
            )
    return SimulationError(
        f"没有满足「{label}」元素要求的可行配装：当前容量与槽位约束下无法装入对应的元素 Mod，"
        "请改选其他元素目标，或调整 Forma/槽位。"
    )


INNATE_ELEMENT_MIN = 0.25
INNATE_ELEMENT_MAX = 0.60
INNATE_ELEMENT_DEFAULT = 0.60

sys.path.insert(0, str(VENDOR_DIR))

import wfarsenal.optimizer as optimizer  # noqa: E402
from wfarsenal.damage import (  # noqa: E402
    ModEffectList,
    SUPPORTED_WEAPON_UPGRADE_TYPES,
    _faction_damage_deltas,
    _hit_location_info,
    effective_hit_multiplier,
)
from wfarsenal.optimizer import RIVEN_BASE_VALUES, RIVEN_RULES  # noqa: E402
from wfarsenal.simulator import (  # noqa: E402
    DEFAULT_CAPACITY_LIMIT,
    DEFAULT_LOADOUT_SLOTS,
    Scenario,
    SimulationError,
    _polarity_adjusted_drain,
    _ranked_mod_drain,
    _set_shell_effects,
    load_exports,
    resolve_kitgun_record,
    resolve_zaw_record,
    simulate,
)
from wfarsenal.warframe import (  # noqa: E402
    WarframeEngine,
    load_warframe_catalog,
)


EXPORTS = load_exports(EXPORT_DIR)
WARFRAME_CATALOG = load_warframe_catalog(WARFRAME_DATA_PATH, fallback=EXPORTS)
WARFRAME_ENGINE = WarframeEngine(WARFRAME_CATALOG)
INCARNON_STRINGS = (
    json.loads(INCARNON_STRINGS_PATH.read_text(encoding="utf-8-sig")).get("data", {})
    if INCARNON_STRINGS_PATH.is_file()
    else {}
)


def _sidecar_rows(path: Path, key: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SimulationError(f"cannot read sidecar data {path}: {exc}") from exc
    rows = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise SimulationError(f"invalid {key} rows in {path}")
    return [dict(row) for row in rows]


STANCE_ROWS = _sidecar_rows(STANCE_DATA_PATH, "stances")
UTILITY_MOD_ROWS = _sidecar_rows(UTILITY_MOD_DATA_PATH, "mods")
EXALTED_WEAPON_ROWS = _sidecar_rows(EXALTED_WEAPON_DATA_PATH, "weapons")
STANCE_BY_PATH = {str(row.get("path") or ""): row for row in STANCE_ROWS}
UTILITY_MOD_BY_PATH = {str(row.get("path") or ""): row for row in UTILITY_MOD_ROWS}
UTILITY_MOD_PATHS = set(UTILITY_MOD_BY_PATH)

# 紫卡分析静态结果缓存（基准配装/双路推荐/理论上限，按武器+开火模式 keyed）。
# 推荐候选恒为理论满数值口径，不随单张紫卡变化；底层数据（导出快照或架势
# 表）变动时整个文件作废重算。缓存格式升级时递增版本号即可全量失效。
ANALYSIS_STATICS_CACHE_PATH = ROOT / ".local" / "cache" / "riven-analysis-statics.json"
if getattr(sys, "frozen", False):
    ANALYSIS_STATICS_CACHE_PATH = (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        / "Warframe-Weapon-Loadout-Build" / "cache" / "riven-analysis-statics.json"
    )
ANALYSIS_STATICS_CACHE_VERSION = 2


def _stances_fingerprint() -> str:
    try:
        return hashlib.sha1(STANCE_DATA_PATH.read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def _analysis_inputs_fingerprint() -> str:
    digest = hashlib.sha1()
    for path in (EXPORT_DIR / "weapons.json", EXPORT_DIR / "mods.json", STANCE_DATA_PATH, Path(optimizer.__file__)):
        try:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            return ""
    return digest.hexdigest()[:16]


def _load_analysis_statics_cache() -> dict[str, Any]:
    try:
        payload = json.loads(ANALYSIS_STATICS_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("buildLabel") != EXPORTS.get("buildLabel")
        or payload.get("stances") != _stances_fingerprint()
        or payload.get("inputs") != _analysis_inputs_fingerprint()
        or payload.get("cacheVersion") != ANALYSIS_STATICS_CACHE_VERSION
    ):
        return {}
    entries = payload.get("entries")
    return dict(entries) if isinstance(entries, dict) else {}


ANALYSIS_STATICS_CACHE: dict[str, Any] = _load_analysis_statics_cache()


def _persist_analysis_statics_cache() -> None:
    """缓存有新条目时落盘（原子替换，避免中断写坏）。"""
    if not ANALYSIS_STATICS_CACHE.pop("__dirty__", None):
        return
    payload = {
        "buildLabel": EXPORTS.get("buildLabel"),
        "stances": _stances_fingerprint(),
        "inputs": _analysis_inputs_fingerprint(),
        "cacheVersion": ANALYSIS_STATICS_CACHE_VERSION,
        "entries": {key: value for key, value in ANALYSIS_STATICS_CACHE.items() if isinstance(value, dict)},
    }
    try:
        ANALYSIS_STATICS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ANALYSIS_STATICS_CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(ANALYSIS_STATICS_CACHE_PATH)
    except OSError:
        pass  # 缓存写不进去不影响解算，下次启动重算即可


def _load_enemy_override_payload() -> Mapping[str, Any]:
    """Load the compact raw-export join and its optional source manifest."""
    if not ENEMY_OVERRIDE_PATH.is_file():
        return {}
    try:
        payload = json.loads(ENEMY_OVERRIDE_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SimulationError(f"cannot read enemy override file {ENEMY_OVERRIDE_PATH}: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("buildLabel") != EXPORTS.get("buildLabel"):
        raise SimulationError(f"invalid enemy override payload: {ENEMY_OVERRIDE_PATH}")
    return payload


def _load_enemy_overrides(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    """Extract the compact row map while ignoring non-row source metadata."""
    if not payload:
        return {}
    rows = payload.get("data")
    if not isinstance(rows, Mapping):
        raise SimulationError(f"invalid enemy override rows: {ENEMY_OVERRIDE_PATH}")
    return {
        str(path): row
        for path, row in rows.items()
        if isinstance(path, str) and isinstance(row, Mapping)
}


ENEMY_OVERRIDE_PAYLOAD = _load_enemy_override_payload()
ENEMY_OVERRIDES = _load_enemy_overrides(ENEMY_OVERRIDE_PAYLOAD)

# The simulator resolves targets straight from EXPORTS["enemies"]; graft the
# full overlay onto those rows so level scaling, shields/armour and headshot
# math see the same data the catalog displays.  The overlay is a delta map by
# construction (sync_enemy_overrides.py only emits missing/normalized fields),
# so a straight update keeps raw export values authoritative where present.
for _enemy_row in EXPORTS.get("enemies") or ():
    if not isinstance(_enemy_row, dict):
        continue
    _overlay = ENEMY_OVERRIDES.get(str(_enemy_row.get("path") or ""))
    if isinstance(_overlay, Mapping):
        _enemy_row.update(_overlay)

ENEMY_WIKI_ENHANCEMENTS = (
    dict(ENEMY_OVERRIDE_PAYLOAD.get("wikiEnhancements"))
    if isinstance(ENEMY_OVERRIDE_PAYLOAD.get("wikiEnhancements"), Mapping)
    else {}
)
WIKI_ENHANCEMENTS = ENEMY_WIKI_ENHANCEMENTS
RIVEN_WEAPON_RECORDS_BY_PATH = {
    str(weapon.get("path") or ""): weapon
    for weapon in EXPORTS["weapons"]
    if weapon.get("path") and str(weapon.get("slot") or "") in RIVEN_SLOTS
}

# The export is immutable in this portable build. Reusing it avoids parsing the
# same JSON files for every click.
optimizer.load_exports = lambda _export_dir: EXPORTS

# ponytail: this is a single-user desktop app; use a worker pool if concurrent
# remote clients ever become a real requirement.
ANALYZE_LOCK = threading.Lock()


def _finite_positive(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number > 0 else None


def _innate_element_selection(
    payload: Mapping[str, Any], weapon: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Apply one explicit Kuva/Tenet/Coda roll; never guess its element."""
    candidates = [
        str(value)
        for value in weapon.get("innateElementCandidates") or ()
        if isinstance(value, str) and value
    ]
    raw_element = payload.get("innateElement", payload.get("progenitorElement"))
    if not candidates:
        if raw_element not in (None, ""):
            raise SimulationError("innateElement is only valid for a weapon with exported candidates")
        return dict(weapon), None
    if raw_element in (None, ""):
        raw_element = "DT_FIRE" if "DT_FIRE" in candidates else candidates[0]
    if not isinstance(raw_element, str) or raw_element not in candidates:
        raise SimulationError("innateElement must be one of the selected weapon candidates")
    raw_value = payload.get(
        "innateElementValue",
        payload.get("progenitorBonus", INNATE_ELEMENT_DEFAULT),
    )
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise SimulationError("innateElementValue must be a number between 0.25 and 0.60")
    value = float(raw_value)
    if not math.isfinite(value) or not INNATE_ELEMENT_MIN <= value <= INNATE_ELEMENT_MAX:
        raise SimulationError("innateElementValue must be between 0.25 and 0.60")
    selection = {"damageType": raw_element, "value": value, "percent": value * 100.0}
    return {**weapon, "innateElements": [selection]}, selection


def _innate_catalog_payload(weapon: Mapping[str, Any]) -> dict[str, Any] | None:
    candidates = [str(value) for value in weapon.get("innateElementCandidates") or () if isinstance(value, str) and value]
    if not candidates:
        return None
    return {
        "candidates": candidates,
        "sources": list(weapon.get("innateElementSources") or ()),
        "min": INNATE_ELEMENT_MIN,
        "max": INNATE_ELEMENT_MAX,
        "default": INNATE_ELEMENT_DEFAULT,
    }


def _weapon_issue(weapon: Mapping[str, Any], weapon_type: str) -> str | None:
    try:
        selected, fire_mode = optimizer._select_fire_mode(
            weapon, None, weapon_type=weapon_type
        )
    except (SimulationError, TypeError, ValueError) as exc:
        return str(exc)
    damage = (selected.get("fireModes") or [{}])[0].get("damage") or {}
    if not isinstance(damage, Mapping) or not damage.get("types"):
        return f"fire mode {fire_mode} has no direct damage types"
    return None


def _metric_options(weapon_type: str) -> tuple[dict[str, str], ...]:
    return BUILD_METRICS["melee" if weapon_type in {"melee", "zaw"} else "gun"]


def _variant_group_path(weapon: Mapping[str, Any]) -> str:
    own_path = str(weapon.get("path") or "")
    if not weapon.get("variantType"):
        return own_path
    for path in weapon.get("ancestry") or ():
        path = str(path or "")
        candidate = RIVEN_WEAPON_RECORDS_BY_PATH.get(path)
        if path != own_path and candidate is not None and not candidate.get("variantType"):
            return path
    return own_path


def _metric_availability(
    weapon: Mapping[str, Any], weapon_type: str, fire_mode: int
) -> dict[str, dict[str, Any]]:
    result = {}
    for option in _metric_options(weapon_type):
        metric = option["id"]
        try:
            selected, _ = optimizer._select_fire_mode(
                weapon, fire_mode, weapon_type=weapon_type
            )
            scenario = optimizer._scenario(metric)
            effects = optimizer._effects((), Scenario())
            stats = optimizer.apply_mods(selected, effects, scenario=scenario)
            events = optimizer.evaluate_projectile_events(
                selected, effects, scenario=scenario
            )
            baseline = optimizer._metrics(stats, events)[metric]
        except (SimulationError, TypeError, ValueError) as exc:
            baseline = 0.0
            issue = str(exc)
        else:
            issue = None if _finite_positive(baseline) else (
                f"fire mode {fire_mode} has no positive {metric} baseline"
            )
        result[metric] = {
            "available": issue is None,
            "baseline": baseline if math.isfinite(float(baseline)) else 0.0,
            "issue": issue,
        }
    return result


def _fire_mode_options(
    weapon: Mapping[str, Any], weapon_type: str
) -> list[dict[str, Any]]:
    rows = []
    all_modes = weapon.get("fireModes") or ()
    mode_count = len(all_modes)
    for index, mode in enumerate(all_modes):
        if not isinstance(mode, Mapping):
            continue
        damage = mode.get("damage") if isinstance(mode.get("damage"), Mapping) else {}
        available = bool(damage.get("types"))
        rows.append(
            {
                "index": index,
                "trigger": str(mode.get("trigger") or ""),
                "isAlternateFire": bool(mode.get("isAlternateFire")),
                # 灵化武器的灵化形态恒为最后一个开火模式（导出数据核验），
                # 前端用它做标签与默认选中。
                "isIncarnonForm": bool(weapon.get("isIncarnon"))
                and mode_count > 1
                and index == mode_count - 1,
                "damageTotal": _finite_positive(damage.get("total")),
                "available": available,
                "issue": None if available else f"fire mode {index} has no direct damage types",
                "metricAvailability": _metric_availability(
                    weapon, weapon_type, index
                ) if available else {},
            }
        )
    return rows


INCARNON_UPGRADE_LABELS = {
    "WEAPON_DAMAGE_AMOUNT": "基础伤害",
    "WEAPON_CRIT_CHANCE": "暴击几率",
    "WEAPON_CRIT_DAMAGE": "暴击伤害",
    "WEAPON_PROC_CHANCE": "触发几率",
    "WEAPON_FIRE_RATE": "射速/攻速",
    "WEAPON_RELOAD_SPEED": "装填速度",
    "WEAPON_SPREAD": "散布",
    "WEAPON_RECOIL": "后坐力",
    "WEAPON_PUNCTURE_DEPTH": "穿透",
    "WEAPON_RANGE": "攻击范围",
    # 数据真实键名（此前表里写成了别名，从未命中）：
    "WEAPON_CLIP_MAX": "弹匣容量",
    "WEAPON_FIRE_ITERATIONS": "多重射击",
    "WEAPON_MELEE_COMBO_INITIAL_BONUS": "初始连击",
    "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY": "连击效率",
    "WEAPON_MELEE_COMBO_DURATION_BONUS": "连击持续",
    "WEAPON_MELEE_COMBO_GAIN_EXTRA_CHANCE": "额外连击几率",
    "WEAPON_MELEE_DAMAGE": "近战伤害",
    "WEAPON_MELEE_FINISHER_DAMAGE": "处决伤害",
    "WEAPON_MELEE_HEAVY_CHARGE_SPEED": "重击蓄力速度",
    "WEAPON_MELEE_AVATAR_DAMAGE_FALL_OFF": "近战伤害衰减",
    "WEAPON_AMMO_CONSUME_RATE": "弹药消耗率",
    "WEAPON_AMMO_MAX": "弹药上限",
    "WEAPON_AMMO_POOL_MULTISHOT_DAMAGE": "弹匣末段多重伤害",
    "WEAPON_AUTO_RELOAD_RATE": "自动装填速度",
    "WEAPON_RELOAD_TIME": "装填时间",
    "WEAPON_PROJECTILE_SPEED": "投射物速度",
    "WEAPON_HEADSHOT_MULTIPLIER": "爆头倍率",
    "WEAPON_CRIT_CHANCE_BODY_PART": "弱点部位暴击几率",
    "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE": "对异常目标伤害",
    "WEAPON_DAMAGE_TYPE_BIAS": "伤害类型占比",
    "WEAPON_EXPLOSION_RADIUS": "爆炸半径",
    "WEAPON_PROC_DAMAGE": "异常伤害",
    "WEAPON_PROC_TIME": "异常持续",
    "WEAPON_NOCRIT_CHANCE": "非暴击几率",
    "WEAPON_NOCRIT_DAMAGE": "非暴击伤害",
    "WEAPON_NOISE_REDUCTION": "噪音降低",
    "WEAPON_PARRY_ANGLE": "格挡角度",
    "WEAPON_ZOOM": "变焦",
    "WEAPON_LAST_MULTISHOT": "末发多重射击",
    "WEAPON_LOW_CRIT_DAMAGE": "低暴击伤害加成",
    "WEAPON_LOW_CRIT_VALUE": "低暴击数值加成",
    "WEAPON_VICTIM_CRIT_CHANCE": "目标被暴击几率",
    "WEAPON_VICTIM_CRIT_DAMAGE": "目标被暴击伤害",
    "WEAPON_VICTIM_DAMAGE_AMOUNT": "对目标伤害",
    "WEAPON_SLASH_PROC_ON_IMPACT": "冲击附带切割异常",
    "WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS": "低触发时暴击加成",
    "WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX": "低触发暴击上限",
    "WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER": "蓄力计数倍率",
    "WEAPON_INCARNON_COMBO_REQUIREMENT": "灵化连击需求",
    "AVATAR_SPRINT_SPEED": "冲刺速度",
    "AVATAR_MOVEMENT_SPEED": "移动速度",
    "AVATAR_PARKOUR_BOOST": "跑酷加成",
    "AVATAR_SLIDE_BOOST": "滑行加成",
    "AVATAR_SLIDE_FRICTION": "滑行摩擦",
    "AVATAR_JUMP_HEIGHT": "跳跃高度",
    "AVATAR_AIR_JUMP_HEIGHT": "二段跳高度",
    "AVATAR_NUM_JUMPS": "跳跃次数",
    "AVATAR_HEAL_RATE": "生命恢复",
    "SKILL_ABILITY_UNLOCK": "形态解锁",
    "SKILL_ABILITY_TACTICAL_EFFICIENCY": "技能效率",
}
INCARNON_OPERATION_LABELS = {
    # 数值自带符号（+51 / -0.6），操作符只标注口径，不再叠符号。
    "ADD": "",
    "ADD_BASE": "基础 ",
    "MULTIPLY": "×",
    "STACKING_MULTIPLY": "倍率 ",
}


def _incarnon_effect_text(effect: Mapping[str, Any]) -> str | None:
    upgrade = str(effect.get("upgradeType") or "")
    # NONE 是脚本占位词条（真实效果在 runtimeScripts 里），不渲染进描述；
    # 脚本部分由 unsupported 单独注明。
    if not upgrade or upgrade.upper() == "NONE":
        return None
    label = INCARNON_UPGRADE_LABELS.get(upgrade, upgrade.replace("WEAPON_", "").replace("_", " ").lower())
    value = effect.get("valuePerRank")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        value = effect.get("value")
    # 脚本占位/解锁类词条没有数值属正常，只显示标签，不填「数值未知」噪音。
    op_key = str(effect.get("operation") or "")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 乘算口径（×1.5）不带符号；加算口径（+51）带符号。
        value_text = f"{float(value):g}" if op_key == "MULTIPLY" else f"{float(value):+g}"
    else:
        value_text = ""
    operation = INCARNON_OPERATION_LABELS.get(op_key, "") if value_text else ""
    # 以引擎当前支持表为准（冻结快照的 supported 标记滞后于引擎实现）。
    support = "" if upgrade in SUPPORTED_WEAPON_UPGRADE_TYPES else "（当前不计入）"
    return f"{label} {operation}{value_text}{support}".strip()


def _incarnon_options(weapon: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    incarnon = weapon.get("incarnon")
    adapter_key = optimizer._path_basename(incarnon.get("adapter")) if isinstance(incarnon, Mapping) else ""
    policy = EXPORTS.get("incarnonDefaults") or {}
    strategies = policy.get("strategies") or {} if isinstance(policy, Mapping) else {}
    strategy = next(
        (value for key, value in strategies.items() if str(key).casefold() == adapter_key.casefold() and isinstance(value, Mapping)),
        {},
    )
    route = strategy.get("route") or {} if isinstance(strategy, Mapping) else {}
    for tier in (incarnon.get("tiers") or ()) if isinstance(incarnon, Mapping) else ():
        tier_number = optimizer._tier_number(tier.get("tier")) if isinstance(tier, Mapping) else None
        branches = [branch for branch in (tier.get("branches") or ()) if isinstance(branch, Mapping)] if isinstance(tier, Mapping) else []
        if tier_number not in {2, 3, 4} or not branches:
            continue
        options = []
        for branch in branches:
            effects = [
                text
                for text in (
                    _incarnon_effect_text(effect)
                    for effect in branch.get("effects") or ()
                    if isinstance(effect, Mapping)
                )
                if text
            ]
            for conditional in branch.get("conditionalEffects") or ():
                if not isinstance(conditional, Mapping):
                    continue
                condition = INCARNON_STRINGS.get(str(conditional.get("conditionTag") or ""), "条件生效时")
                effects.extend(
                    f"{condition}：{text}"
                    for effect in conditional.get("effects") or ()
                    if isinstance(effect, Mapping)
                    for text in (_incarnon_effect_text(effect),)
                    if text
                )
            unsupported = []
            if branch.get("conditionalEffects"):
                unsupported.append("含条件效果；未支持的条件部分不会计入")
            if branch.get("runtimeScripts"):
                # 「运行时脚本」= 游戏内由脚本驱动的动态效果（形态切换、叠层联动等），
                # 数据快照无法静态回放，不参与解算但描述照常展示。
                unsupported.append("含游戏内动态脚本效果（如形态/叠层联动）；该部分不参与解算")
            if branch.get("unresolvedReferences"):
                unsupported.append("含未解析引用")
            options.append({
                "id": str(branch.get("id") or branch.get("path") or ""),
                "index": int(branch.get("index") or len(options) + 1),
                "label": str(INCARNON_STRINGS.get(str(branch.get("nameTag") or "")) or branch.get("id") or "未知路线"),
                "description": "；".join(effects) or "该路线的效果由游戏内脚本实现（无静态词条）",
                "unsupported": unsupported,
                "complete": not unsupported and bool(effects),
            })
        rows.append({
            "tier": tier_number,
            "label": f"进化 {tier_number}",
            "recommended": str(route.get(f"tier{tier_number}") or ""),
            "options": options,
        })
    return rows


def _weapon_build_issue(weapon: Mapping[str, Any], weapon_type: str) -> str | None:
    try:
        selected, _ = optimizer._select_fire_mode(
            weapon, None, weapon_type=weapon_type
        )
        candidates, _ = optimizer._candidate_mods(
            EXPORTS,
            selected,
            optimizer._scenario(
                "attackDps" if weapon_type in {"melee", "zaw"} else "sustainedDps"
            ),
        )
    except (SimulationError, TypeError, ValueError) as exc:
        return str(exc)
    return None if candidates else "weapon has no compatible supported MODs"


def _best_stance_combo(stance: Mapping[str, Any]) -> dict[str, Any] | None:
    combos = [
        combo for combo in stance.get("combos") or ()
        if isinstance(combo, Mapping)
        and _finite_positive(combo.get("duration"))
        and _finite_positive(combo.get("dpsMultiplier"))
    ]
    return dict(max(combos, key=lambda combo: float(combo["dpsMultiplier"]))) if combos else None


def _compatible_stances(weapon: Mapping[str, Any]) -> list[dict[str, Any]]:
    tags = {str(tag).casefold() for tag in weapon.get("compatTags") or ()}
    rows = []
    for source in STANCE_ROWS:
        if str(source.get("compatTag") or "").casefold() not in tags:
            continue
        combo = _best_stance_combo(source)
        if combo is None:
            continue
        rows.append({**source, "bestComboData": combo})
    rows.sort(
        key=lambda row: (
            -float(row["bestComboData"]["dpsMultiplier"]),
            str(row.get("nameZh") or row.get("nameEn") or "").casefold(),
        )
    )
    return rows


def _special_slot_polarities(weapon: Mapping[str, Any], weapon_type: str) -> dict[str, str | None]:
    polarities = list(weapon.get("polarities") or ())
    melee = weapon_type in {"melee", "zaw"}
    stance_index = 8 if melee else None
    exilus_index = 9 if melee else 8
    result: dict[str, str | None] = {}
    if stance_index is not None:
        result["stance"] = polarities[stance_index] if len(polarities) > stance_index else None
    result["exilus"] = polarities[exilus_index] if len(polarities) > exilus_index else None
    return result


def _special_slot_override(
    payload: Mapping[str, Any], weapon: Mapping[str, Any], weapon_type: str
) -> dict[str, Any]:
    """Apply explicit Forma polarity overrides for stance/Exilus slots.

    The ordinary slot list stays eight entries; special slots are carried in a
    separate object so the optimizer cannot accidentally treat a stance or
    Exilus polarity as an ordinary MOD slot.
    """
    raw = payload.get("specialSlotPolarities")
    if raw is None:
        return dict(weapon)
    if not isinstance(raw, Mapping):
        raise SimulationError("specialSlotPolarities must be an object")
    if weapon_type not in {"melee", "zaw"} and "stance" in raw:
        raise SimulationError("stance polarity is only valid for melee weapons")
    allowed = {
        "AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_UMBRA", "AP_POWER",
        "AP_WARD", "AP_PRECEPT", "AP_UNIVERSAL", "AP_ANY",
    }
    polarities = list(weapon.get("polarities") or ())
    indexes = {"stance": 8, "exilus": 9} if weapon_type in {"melee", "zaw"} else {"exilus": 8}
    changed = False
    for kind, index in indexes.items():
        if kind not in raw:
            continue
        value = raw.get(kind)
        if value in (None, "", "AP_NONE", "NONE", "NULL"):
            value = "AP_UNIVERSAL"
        if not isinstance(value, str) or value.strip().upper() not in allowed:
            raise SimulationError(f"specialSlotPolarities.{kind} must be a supported polarity token")
        value = value.strip().upper()
        while len(polarities) <= index:
            polarities.append(None)
        if polarities[index] != value:
            polarities[index] = value
            changed = True
    return {**weapon, "polarities": polarities} if changed else dict(weapon)


def _stance_slot_payload(weapon: Mapping[str, Any], weapon_type: str) -> dict[str, Any] | None:
    if weapon_type not in {"melee", "zaw"}:
        return None
    exalted = next(
        (
            row for row in EXALTED_WEAPON_ROWS
            if str(weapon.get("path") or "") == str(row.get("path") or "")
            or str(weapon.get("path") or "") in (row.get("portablePaths") or ())
        ),
        None,
    )
    slot_polarity = _special_slot_polarities(weapon, weapon_type)["stance"]
    if exalted:
        return {
            "locked": True,
            "builtIn": True,
            "path": exalted.get("builtInStancePath") or exalted.get("builtInStance"),
            "nameZh": exalted.get("nameZh") or exalted.get("name"),
            "nameEn": exalted.get("name"),
            "slotPolarity": slot_polarity,
            "capacityGain": 0,
            "dpsMultiplier": 1.0,
            "statusRateMultiplier": 1.0,
        }
    stances = _compatible_stances(weapon)
    if not stances:
        return {
            "locked": False,
            "builtIn": False,
            "path": None,
            "slotPolarity": slot_polarity,
            "capacityGain": 0,
            "dpsMultiplier": 1.0,
            "statusRateMultiplier": 1.0,
            "compatiblePaths": [],
        }
    selected = stances[0]
    rank = int(selected.get("maxRank") or 0)
    raw = _ranked_mod_drain(selected, rank)
    adjusted, relation = _polarity_adjusted_drain(raw, selected.get("polarity"), slot_polarity)
    return {
        "locked": False,
        "builtIn": False,
        "path": selected["path"],
        "slotPolarity": slot_polarity,
        "capacityGain": -adjusted,
        "polarityRelation": relation,
        "dpsMultiplier": selected["bestComboData"]["dpsMultiplier"],
        "statusRateMultiplier": selected["bestComboData"]["statusRateMultiplier"],
        "bestCombo": selected["bestComboData"],
        "compatiblePaths": [stance["path"] for stance in stances],
    }


def _resolve_stance(
    weapon: Mapping[str, Any],
    weapon_type: str,
    requested: Any = None,
) -> dict[str, Any] | None:
    base = _stance_slot_payload(weapon, weapon_type)
    if base is None:
        if requested not in (None, ""):
            raise SimulationError("stancePath is only valid for melee weapons")
        return None
    if base.get("builtIn"):
        if requested not in (None, "", base.get("path")):
            raise SimulationError("exalted weapons use their locked built-in stance")
        return base
    compatible = _compatible_stances(weapon)
    if not compatible:
        return base
    if requested not in (None, ""):
        selected = next(
            (row for row in compatible if row["path"] == requested),
            None,
        )
        if selected is None:
            raise SimulationError("stancePath is not compatible with the selected melee weapon")
    else:
        selected = compatible[0]
    slot_polarity = base.get("slotPolarity")
    rank = int(selected.get("maxRank") or 0)
    adjusted, relation = _polarity_adjusted_drain(
        _ranked_mod_drain(selected, rank), selected.get("polarity"), slot_polarity
    )
    combo = selected["bestComboData"]
    return {
        **selected,
        "rank": rank,
        "locked": False,
        "builtIn": False,
        "slotPolarity": slot_polarity,
        "capacityGain": -adjusted,
        "polarityRelation": relation,
        "dpsMultiplier": float(combo["dpsMultiplier"]),
        "statusRateMultiplier": float(combo["statusRateMultiplier"]),
        "bestCombo": combo,
        "compatiblePaths": [row["path"] for row in compatible],
    }


def _analysis_stance(weapon: Mapping[str, Any], weapon_type: str) -> dict[str, Any] | None:
    """紫卡分析的近战架势：与配装页同口径，默认普攻 DPS 倍率最高的架势。

    分析按无限极化口径解算——架势槽视为已极化匹配（容量收益取匹配值），
    原生极性不匹配时由引擎的极化统计计入「极化 ×N」结果。显赫武器的内置
    架势容量收益恒为 0。
    """
    stance = _resolve_stance(weapon, weapon_type)
    if stance is None:
        return None
    if stance.get("builtIn"):
        return stance
    if not stance.get("path"):
        return None  # 没有兼容架势数据，按无架势口径解算
    selected = STANCE_BY_PATH.get(str(stance.get("path") or ""))
    if selected is None:
        return None
    rank = int(selected.get("maxRank") or 0)
    matched_drain, _ = _polarity_adjusted_drain(
        _ranked_mod_drain(selected, rank), selected.get("polarity"), selected.get("polarity")
    )
    return {**stance, "capacityGain": -matched_drain}


def _utility_matches_weapon(
    row: Mapping[str, Any],
    weapon: Mapping[str, Any],
    catalog_weapon: Mapping[str, Any],
) -> bool:
    kind = str(row.get("slotKind") or "")
    expected = "melee" if catalog_weapon["weaponType"] in {"melee", "zaw"} else str(catalog_weapon["slot"])
    if kind != expected:
        return False
    if not row.get("catalogJoined"):
        return kind == "melee" and row.get("sourceKind") == "tennokai"
    try:
        record = optimizer.resolve_record(EXPORTS["mods"], str(row["path"]), kind="mod")
    except SimulationError:
        return False
    return optimizer._mod_matches_weapon(record, weapon)


def _utility_card_at_rank(
    row: Mapping[str, Any], scenario: Scenario, rank: int
) -> optimizer._Card | None:
    if not row.get("catalogJoined"):
        return None
    record = optimizer.resolve_record(EXPORTS["mods"], str(row["path"]), kind="mod")
    shells = optimizer._set_shells(EXPORTS["mods"])
    card = optimizer._mod_card(
        record,
        scenario,
        allow_empty=True,
        set_shell=shells.get(optimizer._set_key(record.get("modSet"))),
    )
    if card is None:
        return None
    effects = optimizer.mod_effects(
        record, rank, optimizer._steady_state_scenario((record,), scenario)
    )
    return replace(
        card,
        rank=rank,
        effects=tuple(effects),
        skipped=tuple(effects.skipped),
        drain=max(0, int(record.get("baseDrain") or 0) + rank),
    )


def _score_with_special_card(
    weapon: Mapping[str, Any],
    evaluation: optimizer._Evaluation,
    card: optimizer._Card | None,
    *,
    scenario: Scenario,
    metric: str,
    passives: optimizer._Card | None,
    target_context: Mapping[str, Any] | None,
) -> tuple[float, Any, Scenario]:
    cards = [*evaluation.cards]
    if card is not None:
        cards.append(card)
    effect_cards = [passives, *cards] if passives is not None else cards
    effects = optimizer._effects(effect_cards, scenario)
    probe_scenario = replace(scenario, victim_status_count=0)
    probe_stats = optimizer.apply_mods(weapon, effects, scenario=probe_scenario)
    derived_scenario = replace(
        scenario,
        victim_status_count=optimizer.expected_victim_status_count(probe_stats),
    )
    stats = optimizer.apply_mods(weapon, effects, scenario=derived_scenario)
    events = optimizer.evaluate_projectile_events(
        weapon, effects, scenario=derived_scenario
    )
    return optimizer._score(stats, metric, events, target_context), stats, derived_scenario


def _auto_exilus(
    weapon: Mapping[str, Any],
    catalog_weapon: Mapping[str, Any],
    evaluation: optimizer._Evaluation,
    *,
    scenario: Scenario,
    metric: str,
    passives: optimizer._Card | None,
    target_context: Mapping[str, Any] | None,
    capacity_limit: int,
) -> tuple[optimizer._Evaluation, dict[str, Any] | None]:
    slot_polarity = _special_slot_polarities(
        weapon, catalog_weapon["weaponType"]
    )["exilus"]
    choices = []
    for row in CATALOG_UTILITY_MODS:
        if not _utility_matches_weapon(row, weapon, catalog_weapon):
            continue
        max_rank = int(row.get("rank") if row.get("rank") is not None else row.get("maxRank") or 0)
        for rank in dict.fromkeys((max_rank, 0)):
            raw = int(row.get("drain") or 0) - max_rank + rank
            drain, relation = _polarity_adjusted_drain(raw, row.get("polarity"), slot_polarity)
            if evaluation.capacity + drain > capacity_limit:
                continue
            card = _utility_card_at_rank(row, scenario, rank)
            score, stats, derived_scenario = _score_with_special_card(
                weapon,
                evaluation,
                card,
                scenario=scenario,
                metric=metric,
                passives=passives,
                target_context=target_context,
            )
            choices.append((score, relation == "matched", -drain, -rank, str(row.get("path")), row, rank, drain, relation, stats, derived_scenario))
    if not choices:
        return evaluation, None
    # Exilus is a dedicated slot: prefer its matching polarity first, then
    # maximize modeled gain; the rank/drain tie-breakers keep a zero-rank card
    # when leveling it adds no supported primary effect.
    choices.sort(key=lambda item: (item[1], item[0], item[2], item[3], item[4]), reverse=True)
    score, _matched, _drain_key, _rank_key, _path, row, rank, drain, relation, stats, derived_scenario = choices[0]
    return (
        replace(
            evaluation,
            score=score,
            stats=stats,
            capacity=evaluation.capacity + drain,
            scenario=derived_scenario,
        ),
        {
            **row,
            "rank": rank,
            "drain": drain,
            "slotPolarity": slot_polarity,
            "polarityRelation": relation,
        },
    )


def _forma_summary(
    weapon: Mapping[str, Any], cards: tuple[optimizer._Card, ...], stance: Mapping[str, Any] | None
) -> dict[str, int]:
    native = Counter(str(value) for value in list(weapon.get("polarities") or ())[:8])
    regular = 0
    umbra = 0
    for card in cards:
        polarity = str(card.polarity or "")
        if not polarity or polarity == "AP_UNIVERSAL":
            continue
        if native[polarity] > 0:
            native[polarity] -= 1
        elif polarity in {"AP_UMBRA", "AP_ULTIMATE"}:
            umbra += 1
        else:
            regular += 1
    return {
        "regular": regular,
        "umbra": umbra,
        "stance": int(bool(stance and stance.get("polarityRelation") != "matched" and not stance.get("builtIn"))),
    }


# Filled from the immutable export after the main weapon catalog is built.
MANUAL_ENEMIES: list[dict[str, Any]] = []
MANUAL_MODS: list[dict[str, Any]] = []
MANUAL_ARCANES: list[dict[str, Any]] = []


def build_catalog() -> dict[str, Any]:
    weapons: list[dict[str, Any]] = []
    hard_fails: list[dict[str, Any]] = []
    available = 0

    for weapon in EXPORTS["weapons"]:
        slot = str(weapon.get("slot") or "")
        if slot not in RIVEN_SLOTS:
            continue
        weapon_type = optimizer._weapon_type(None, weapon)
        issue = _weapon_issue(weapon, weapon_type)
        build_issue = issue or _weapon_build_issue(weapon, weapon_type)
        hidden_from_build_picker = issue is None and build_issue is not None
        fire_modes = _fire_mode_options(weapon, weapon_type)
        analysis_metric = "attackDps" if weapon_type in {"melee", "zaw"} else "sustainedDps"
        analysis_availability = (
            (fire_modes[0].get("metricAvailability") or {}).get(analysis_metric)
            if fire_modes else None
        )
        analysis_issue = issue or (
            None
            if isinstance(analysis_availability, Mapping)
            and analysis_availability.get("available")
            else str((analysis_availability or {}).get("issue") or "default analysis metric is unavailable")
        )
        disposition = _finite_positive(weapon.get("omegaAttenuation"))
        stance_slot = _stance_slot_payload(weapon, weapon_type)
        special_polarities = _special_slot_polarities(weapon, weapon_type)
        row = {
            "path": str(weapon.get("path") or ""),
            "nameZh": str(weapon.get("nameZh") or ""),
            "nameEn": str(weapon.get("nameEn") or ""),
            "nameInternal": str(weapon.get("nameInternal") or ""),
            "slot": slot,
            "weaponType": weapon_type,
            "ancestry": list(weapon.get("ancestry") or ()),
            "compatTags": list(weapon.get("compatTags") or ()),
            "polarities": list(weapon.get("polarities") or ()),
            "variantType": str(weapon.get("variantType") or "VT_NORMAL"),
            "variantGroupPath": _variant_group_path(weapon),
            "disposition": disposition,
            "fireModes": fire_modes,
            "available": issue is None,
            "issue": issue,
            "analysisAvailable": analysis_issue is None,
            "analysisIssue": analysis_issue,
            "buildAvailable": build_issue is None,
            "buildIssue": build_issue,
            "hiddenFromBuildPicker": hidden_from_build_picker,
            "incarnon": _incarnon_options(weapon),
            "innateElementCandidates": list(weapon.get("innateElementCandidates") or ()),
            "innateElementSources": list(weapon.get("innateElementSources") or ()),
            "innateElement": _innate_catalog_payload(weapon),
            "isExalted": bool(stance_slot and stance_slot.get("builtIn")),
            "specialSlots": {
                "stance": stance_slot,
                "exilus": {
                    "slotPolarity": special_polarities["exilus"],
                    "kind": "melee" if weapon_type in {"melee", "zaw"} else slot,
                },
                "weaponArcane": {"limit": 1},
                "frameArcane": {"limit": 2},
            },
        }
        if issue:
            row["issue"] = issue
            hard_fails.append(
                {
                    "path": row["path"],
                    "nameZh": row["nameZh"],
                    "nameEn": row["nameEn"],
                    "slot": slot,
                    "reason": issue,
                }
            )
        else:
            available += 1
        weapons.append(row)

    weapons.sort(
        key=lambda row: (
            row["slot"],
            (row["nameZh"] or row["nameEn"] or row["nameInternal"]).casefold(),
            row["path"],
        )
    )

    stats_by_type: dict[str, list[dict[str, Any]]] = {}
    for weapon_type, base_values in RIVEN_BASE_VALUES.items():
        rows = []
        for code in base_values:
            rule = RIVEN_RULES.get(code)
            if rule is None:
                continue
            label, upgrade_type, _, _, _, unit, _, can_positive, can_negative = rule
            rows.append(
                {
                    "code": code,
                    "label": label,
                    "baseValue": base_values[code],
                    "unit": unit,
                    "canPositive": can_positive,
                    "canNegative": can_negative,
                    "objectiveSupported": upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES,
                }
            )
        stats_by_type[weapon_type] = rows

    return {
        "buildLabel": EXPORTS["buildLabel"],
        "schemaVersion": EXPORTS["schemaVersion"],
        "manualMods": MANUAL_MODS,
        "enemies": MANUAL_ENEMIES,
        "arcanes": MANUAL_ARCANES,
        "stances": [
            {**row, "bestComboData": _best_stance_combo(row)}
            for row in STANCE_ROWS
            if _best_stance_combo(row) is not None
        ],
        "utilityMods": UTILITY_MOD_ROWS,
        "exaltedWeapons": EXALTED_WEAPON_ROWS,
        "manualCounts": {
            "mods": len(MANUAL_MODS),
            "enemies": len(MANUAL_ENEMIES),
            "arcanes": len(MANUAL_ARCANES),
        },
        "counts": {
            "weapons": len(weapons),
            "available": available,
            "knownHardFails": len(hard_fails),
            "analysisAvailable": sum(weapon["analysisAvailable"] for weapon in weapons),
            "analysisUnavailable": sum(not weapon["analysisAvailable"] for weapon in weapons),
            "buildAvailable": sum(weapon["buildAvailable"] for weapon in weapons),
            "buildUnavailable": sum(not weapon["buildAvailable"] for weapon in weapons),
            "buildPickerWeapons": sum(not weapon["hiddenFromBuildPicker"] for weapon in weapons),
            "buildPickerAvailable": sum(
                weapon["buildAvailable"] and not weapon["hiddenFromBuildPicker"]
                for weapon in weapons
            ),
        },
        "weapons": weapons,
        "statsByType": stats_by_type,
        "knownHardFails": hard_fails,
        "enemyEnhancements": WIKI_ENHANCEMENTS,
            "buildOptions": {
            "metrics": BUILD_METRICS,
            "slotCount": {"min": 1, "max": 8, "default": 8},
            "elementTargets": [
                {"id": key, "damageType": damage_type, "label": label}
                for key, (damage_type, label) in ELEMENT_TARGETS.items()
            ],
            "innateElement": {
                "min": INNATE_ELEMENT_MIN,
                "max": INNATE_ELEMENT_MAX,
                "default": INNATE_ELEMENT_DEFAULT,
            },
            "clearElementValue": None,
            "damageModels": ["panel", "target", "custom"],
            "customDamageModel": True,
            "limitations": [
                "60 capacity, Catalyst and matching Forma are assumed for automatic builds",
                "element target constrains final damage type, not status weighting",
                "enemy resistances, status DOT, Arcanes and Incarnon choices are not optimized",
            ],
        },
    }


CATALOG = build_catalog()
CATALOG_WEAPONS_BY_PATH = {
    weapon["path"]: weapon for weapon in CATALOG["weapons"]
}


def _complete_enemy_rows() -> list[dict[str, Any]]:
    """Return deduplicated targets with explicit defense material fields.

    The old exporter left most material/level fields null even though the raw
    damage controller had them.  ``enemy_overrides.json`` fills those gaps;
    zero pools are represented by ``RK_NONE`` so a target can never silently
    lose its armor/shield semantics.  Dynamic mechanics remain visible as
    ``complete=False`` and are rejected by simulation rather than approximated.
    """
    unique: dict[tuple[Any, ...], tuple[tuple[int, int, int, int, int], dict[str, Any]]] = {}
    for source in EXPORTS.get("enemies") or ():
        if not isinstance(source, Mapping):
            continue
        path = str(source.get("path") or "").strip()
        if not path:
            continue
        overlay = ENEMY_OVERRIDES.get(path)
        enemy: dict[str, Any] = dict(source)
        if isinstance(overlay, Mapping):
            enemy.update(overlay)
        health = enemy.get("health")
        shield = enemy.get("shield")
        armour = enemy.get("armour")
        base_level = enemy.get("baseLevel")
        if (
            isinstance(base_level, bool)
            or not isinstance(base_level, (int, float))
            or not math.isfinite(float(base_level))
        ):
            continue
        if (
            isinstance(health, bool)
            or not isinstance(health, (int, float))
            or not math.isfinite(float(health))
            or health <= 0
        ):
            continue
        if (
            isinstance(shield, bool)
            or not isinstance(shield, (int, float))
            or not math.isfinite(float(shield))
            or shield < 0
        ):
            continue
        if (
            isinstance(armour, bool)
            or not isinstance(armour, (int, float))
            or not math.isfinite(float(armour))
            or armour < 0
        ):
            continue
        health_type = str(enemy.get("healthType") or "").strip()
        armour_type = str(enemy.get("armourType") or enemy.get("armorType") or "").strip()
        shield_type = str(enemy.get("shieldType") or "").strip()
        faction = str(enemy.get("faction") or "").strip()
        faction_resistance = str(enemy.get("factionResistance") or "").strip()
        if not health_type or not armour_type or not shield_type or not faction_resistance:
            continue
        if not enemy.get("damageController"):
            continue
        unsupported: set[str] = set()
        if enemy.get("overguard") or enemy.get("hasOverguard"):
            unsupported.add("enemy-overguard")
        if enemy.get("damageAttenuation") or enemy.get("hasDamageAttenuation") or enemy.get("dynamicDamageResistance"):
            unsupported.add("enemy-damage-attenuation")
        _, hit_direct, _, head_unsupported, _ = _hit_location_info(enemy, "head")
        # 基准等级来源为 default-1（官方快照与 WPEP 均未记录）时，等级缩放曲线
        # 没有可靠的锚点，标记「数值缩放缺失」，由前端归入「数值缺失」默认隐藏。
        scaling_supported = str((enemy.get("defenseSources") or {}).get("baseLevel") or "") != "default-1"
        row: dict[str, Any] = {
            "path": path,
            "nameZh": str(enemy.get("nameZh") or enemy.get("name") or path),
            "nameEn": str(enemy.get("nameEn") or enemy.get("name") or path),
            "nameInternal": str(enemy.get("nameInternal") or ""),
            "faction": faction,
            "factionResistance": faction_resistance,
            "baseLevel": float(base_level),
            "health": float(health),
            "shield": float(shield),
            "armour": float(armour),
            "healthType": health_type,
            "armourType": armour_type,
            "shieldType": shield_type,
            "hasHeadProxy": not head_unsupported,
            "headshotStatus": "supported" if not head_unsupported else "not-applicable",
            "scalingSupported": scaling_supported,
            "complete": not unsupported,
            "unsupported": sorted(unsupported),
        }
        if enemy.get("baseLevelCandidates"):
            row["baseLevelCandidates"] = list(enemy["baseLevelCandidates"])
        if not head_unsupported:
            # 与 wiki「Body Multipliers · Head」同口径：部位系数 × 固定 1.5 爆头系数。
            row["headshotMultiplier"] = round(hit_direct, 4)
        # 与引擎同口径解析派系克制（内嵌 modifiers 优先，否则按 factionResistance 关键字），
        # 前端按它渲染「弱 / 抗」标签，不再猜测。
        faction_modifiers = dict(_faction_damage_deltas(enemy))
        if faction_modifiers:
            row["factionModifiers"] = faction_modifiers
        for key in (
            "factionDamageModifiers",
            "damageController",
            "hitProxies",
            "usesNpcArmourCurve",
            "overguard",
            "hasOverguard",
            "damageAttenuation",
            "hasDamageAttenuation",
            "dynamicDamageResistance",
            "defenseSources",
        ):
            if enemy.get(key) is not None:
                row[key] = enemy[key]
        key = (
            row["faction"].casefold(),
            row["nameZh"].casefold(),
            row["nameEn"].casefold(),
            row["health"],
            row["shield"],
            row["armour"],
            row["healthType"],
            row["armourType"],
            row["shieldType"],
            row["baseLevel"],
        )
        lowered = path.casefold()
        preference = (
            int(not row["complete"]),
            int("leader" in lowered),
            int("ally" in lowered),
            int("/pnw" in lowered),
            len(path),
        )
        current = unique.get(key)
        if current is None or preference < current[0]:
            unique[key] = (preference, row)
    rows = [item[1] for item in unique.values()]
    label_counts = Counter(
        (row["faction"].casefold(), row["nameZh"].casefold()) for row in rows
    )
    for row in rows:
        row["displayName"] = row["nameZh"]
        if label_counts[(row["faction"].casefold(), row["nameZh"].casefold())] > 1:
            row["displayName"] += (
                f" · Lv{row['baseLevel']:g}"
                f" · H{row['health']:g}/S{row['shield']:g}/A{row['armour']:g}"
                f" · {row['path']}"
            )
    rows.sort(key=lambda row: (row["faction"].casefold(), row["nameZh"].casefold(), row["path"]))
    return rows


MANUAL_MOD_ALIASES: dict[str, str] = {}
# Non-canonical tiered variants (Beginner/Intermediate/Expert) keyed by path;
# populated by _manual_mod_rows() alongside MANUAL_MODS.
MANUAL_MOD_VARIANTS: list[dict[str, Any]] = []


def _manual_mod_rows() -> list[dict[str, Any]]:
    rabbit_mods_path = ROOT / ".." / "黑猫4.0-5.0" / "dist" / "WRData" / "data" / "v2_mods.json"
    try:
        rabbit_mods = {
            str(row.get("UniqueName") or ""): row
            for row in json.loads(rabbit_mods_path.read_text(encoding="utf-8"))
            if isinstance(row, Mapping)
        }
    except (OSError, ValueError, TypeError):
        rabbit_mods = {}

    def category(mod: Mapping[str, Any]) -> str:
        if mod.get("slotKind") in {"aura", "exilus", "warframe"}:
            return str(mod.get("slotKind"))
        if mod.get("modSet"):
            return "set"
        effects = mod.get("effects") if isinstance(mod.get("effects"), list) else []
        types = {str(effect.get("upgradeType") or "").upper() for effect in effects if isinstance(effect, Mapping)}
        damage_types = {
            "DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON", "DT_MAGNETIC",
            "DT_RADIATION", "DT_VIRAL", "DT_CORROSIVE", "DT_EXPLOSION", "DT_GAS",
        }
        if any(str(effect.get("damageType") or "").upper() in damage_types for effect in effects if isinstance(effect, Mapping)):
            return "element"
        if types & {"WEAPON_CRIT_CHANCE", "WEAPON_CRIT_DAMAGE", "WEAPON_NOCRIT_DAMAGE"}:
            return "critical"
        if "WEAPON_FIRE_ITERATIONS" in types:
            return "multishot"
        if types & {"WEAPON_PROC_CHANCE", "WEAPON_PROC_DAMAGE", "WEAPON_PROC_TIME", "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"}:
            return "status"
        if "WEAPON_FIRE_RATE" in types:
            return "speed"
        if types & {"WEAPON_RELOAD_SPEED", "WEAPON_CLIP_MAX", "WEAPON_AMMO_MAX"}:
            return "handling"
        if types & {"WEAPON_DAMAGE_AMOUNT", "WEAPON_MELEE_DAMAGE", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "GAMEPLAY_FACTION_DAMAGE"}:
            return "damage"
        return "utility"

    set_shells = {
        str(mod.get("modSet")): mod
        for mod in EXPORTS.get("mods") or ()
        if mod.get("modSet") and isinstance(mod.get("setPieces"), int)
    }

    def _set_shell_supported(shell: Mapping[str, Any] | None) -> bool:
        """Dry-run the simulator's set-shell expansion: skipped notes mean the
        set bonus is condition/runtime based and cannot be simulated."""
        if not shell:
            return False
        try:
            expanded = _set_shell_effects(shell, int(shell.get("setPieces") or 2), Scenario())
        except Exception:
            return False
        return not list(expanded.skipped)

    set_shell_support = {set_id: _set_shell_supported(shell) for set_id, shell in set_shells.items()}
    # The Warframe sidecar freezes the public set shell even when the weapon
    # export only carries a member's ``modSet`` id.  Merge those fields into
    # shared weapon-catalog rows so the UI never loses set text or provenance.
    warframe_sets = WARFRAME_CATALOG.get("modSets") or {}
    if not isinstance(warframe_sets, Mapping):
        warframe_sets = {}

    def _set_meta(mod_set: str) -> Mapping[str, Any]:
        value = warframe_sets.get(mod_set)
        return value if isinstance(value, Mapping) else {}

    def _refresh_effect_support(effect: Mapping[str, Any]) -> Mapping[str, Any]:
        """冻结快照的 supported 标记滞后于引擎（如本次新增的首发伤害词条）；
        展示层以引擎当前支持表为准，避免已支持的词条被误标「不参与解算」。"""
        if (
            isinstance(effect, Mapping)
            and effect.get("supported") is False
            and str(effect.get("upgradeType") or "").upper() in SUPPORTED_WEAPON_UPGRADE_TYPES
        ):
            return {**effect, "supported": True, "supportedBy": ["weapon"]}
        return effect

    rows_by_identity: dict[tuple[str, str], dict[str, Any]] = {}
    source_paths_by_identity: dict[tuple[str, str], list[str]] = {}
    # Every qualifying row keyed by its own path, including the tiered
    # (Beginner/Intermediate/Expert) variants that lose the dedupe below — the
    # solver may legitimately pick those, so the workbench must be able to
    # display and simulate the exact card that was solved.
    all_rows_by_path: dict[str, dict[str, Any]] = {}
    for mod in EXPORTS.get("mods") or ():
        support = mod.get("support") if isinstance(mod.get("support"), Mapping) else {}
        if not mod.get("path") or mod.get("selectable") is False:
            continue
        path = str(mod.get("path"))
        if "/PvPMods/" in path:
            continue
        # Aura/Warframe cards can carry weapon effects, but they are installed
        # on a Warframe and must never appear in the weapon MOD picker.
        compatibility = str(mod.get("compatibility") or "").casefold()
        if "powersuit" in compatibility or "/aura/" in path.casefold():
            continue
        # A mod qualifies when at least one weapon effect is supported. The
        # card-level support.weapon flag is false for Amalgam-style hybrids
        # whose riders (charge speed etc.) are unsupported, so the effect-level
        # check is authoritative; unsupported riders surface as notes.
        effects = mod.get("effects") or []
        has_supported_effect = any(
            isinstance(effect, Mapping)
            and effect.get("supported") is True
            and "weapon" in (effect.get("supportedBy") or ())
            for effect in effects
        )
        fixed_melee_range = str(mod.get("nameEn") or "") == "Primed Reach"
        # 膛室家族（Primed Chamber / 蓄力装填）的 WEAPON_INIT_DAMAGE_MOD「首发
        # 伤害」引擎已建模；冻结快照的 supported 标记滞后，过滤阶段仍需按词条名
        # 豁免收录（展示层的 supported 由 _refresh_effect_support 动态覆写）。
        first_shot_chamber = any(
            isinstance(effect, Mapping)
            and str(effect.get("upgradeType") or "").upper() == "WEAPON_INIT_DAMAGE_MOD"
            for effect in effects
        )
        # 「蓄力装填 Prime」（SniperReloadDamageModExpert）是 DE 数据里从未发布的
        # dev 残留（游戏内蓄力装填的 prime 版就是膛室 Prime），不收录。
        if path == "/Lotus/Upgrades/Mods/Rifle/Expert/SniperReloadDamageModExpert":
            continue
        if not support.get("weapon") and not has_supported_effect and not fixed_melee_range and not first_shot_chamber:
            continue
        if mod.get("supported") is False and not has_supported_effect and not fixed_melee_range and not first_shot_chamber:
            continue
        # SubMods are implementation shells, not selectable cards.  Some
        # exports mark them selectable but still provide no effect payload.
        if not mod.get("effects") and "submod" in path.casefold():
            continue
        mod_set = str(mod.get("modSet") or "")
        shell = set_shells.get(mod_set, {})
        frame_set = _set_meta(mod_set)
        rabbit_mod = rabbit_mods.get(path, {})
        row = {
            "path": path,
            "nameZh": str(mod.get("nameZh") or mod.get("name") or ""),
            "nameEn": str(mod.get("nameEn") or mod.get("name") or ""),
            "nameInternal": str(mod.get("nameInternal") or ""),
            "compatibility": str(mod.get("compatibility") or ""),
            "compatibilityTags": list(mod.get("compatibilityTags") or ()),
            "incompatibilityTags": list(mod.get("incompatibilityTags") or ()),
            "polarity": mod.get("polarity"),
            "rarity": mod.get("rarity") or rabbit_mod.get("Rarity") or "COMMON",
            "maxRank": mod.get("maxRank"),
            "baseDrain": mod.get("baseDrain"),
            "modFamily": mod.get("modFamily"),
            "modSet": mod_set or None,
            "modSetValues": list(mod.get("modSetValues") or ()),
            "setMaxPieces": shell.get("setPieces") or frame_set.get("maxPieces") or mod.get("setMaxPieces"),
            "setName": frame_set.get("name") or mod.get("setName"),
            "setDescription": frame_set.get("description") or mod.get("setDescription"),
            "setDesc": frame_set.get("description") or mod.get("setDesc") or mod.get("setDescription"),
            "setDescriptionTag": frame_set.get("descriptionTag") or mod.get("setDescriptionTag"),
            "setEffects": list(frame_set.get("effects") or mod.get("setEffects") or ()),
            "setStats": list(frame_set.get("setStats") or frame_set.get("effects") or mod.get("setStats") or mod.get("setEffects") or ()),
            "setConditionalEffects": list(frame_set.get("conditionalEffects") or mod.get("setConditionalEffects") or ()),
            "setDisplayValues": dict(frame_set.get("displayValues") or mod.get("setDisplayValues") or {}),
            "setRuntime": dict(frame_set.get("runtime") or mod.get("setRuntime") or {}),
            "setSource": frame_set.get("sourcePath") or mod.get("setSource"),
            "source": frame_set.get("sourcePath") or mod.get("source") or mod.get("setSource"),
            "setSupported": bool(set_shell_support.get(mod_set, False)) if mod_set else None,
            "category": category(mod),
            "slotKind": str(mod.get("slotKind") or "weapon"),
            "type": str(mod.get("type") or mod.get("slotKind") or "weapon"),
            "sourceType": str(mod.get("sourceType") or "Weapon Mod"),
            "sourceCompatibility": str(mod.get("sourceCompatibility") or mod.get("compatibility") or ""),
            "description": str(rabbit_mod.get("Description") or mod.get("description") or ""),
            "unsupportedNotes": [
                str(effect.get("upgradeType") or "")
                for effect in (mod.get("effects") or ())
                if isinstance(effect, Mapping) and _refresh_effect_support(effect).get("supported") is False
            ] or None,
            "effects": [_refresh_effect_support(effect) for effect in (mod.get("effects") or ())],
            "conditionalEffects": list(mod.get("conditionalEffects") or ()),
        }
        identity = (row["nameZh"] or row["nameEn"], row["compatibility"])
        all_rows_by_path[path] = row
        source_paths_by_identity.setdefault(identity, []).append(path)
        current = rows_by_identity.get(identity)
        if current is None:
            rows_by_identity[identity] = row
            continue
        # Beginner / Intermediate / Expert are progression variants, not aliases
        # for the normal card. Prefer the non-tier path whenever it exists.
        tiered = ("/beginner/", "/intermediate/", "/expert/")
        current_key = (int(not any(part in current["path"].casefold() for part in tiered)), int(current.get("maxRank") or -1))
        row_key = (int(not any(part in row["path"].casefold() for part in tiered)), int(row.get("maxRank") or -1))
        if row_key > current_key or (row_key == current_key and row["path"] < current["path"]):
            rows_by_identity[identity] = row
    rows = list(rows_by_identity.values())
    canonical_paths = {row["path"] for row in rows}
    variants = [row for path, row in all_rows_by_path.items() if path not in canonical_paths]
    variants.sort(key=lambda row: (row["nameZh"].casefold(), row["path"]))
    MANUAL_MOD_VARIANTS.clear()
    MANUAL_MOD_VARIANTS.extend(variants)
    MANUAL_MOD_ALIASES.clear()
    for identity, paths in source_paths_by_identity.items():
        canonical = rows_by_identity[identity]["path"]
        for path in paths:
            MANUAL_MOD_ALIASES[path] = canonical
    rows.sort(key=lambda row: (row["nameZh"].casefold(), row["path"]))
    return rows


def _arcane_effect_summary(arcane: Mapping[str, Any]) -> str:
    """Human-readable effect line for the arcane picker."""
    labels = {
        "WEAPON_DAMAGE_AMOUNT": "基伤",
        "WEAPON_MELEE_DAMAGE": "近战基伤",
        "WEAPON_CRIT_CHANCE": "暴击几率",
        "WEAPON_CRIT_DAMAGE": "暴击伤害",
        "WEAPON_PROC_CHANCE": "触发几率",
        "WEAPON_FIRE_ITERATIONS": "多重射击",
        "WEAPON_FIRE_RATE": "射速",
        "WEAPON_MELEE_FIRE_RATE": "攻速",
        "WEAPON_MAGAZINE_CAPACITY": "弹匣",
        "WEAPON_RELOAD_SPEED": "装填速度",
        "WEAPON_PROJECTILE_SPEED": "弹速",
        "WEAPON_RANGE": "攻击范围",
        "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE": "对异常目标伤害",
        "WEAPON_FREEZE_DAMAGE": "冰冻伤害",
        "WEAPON_FIRE_DAMAGE": "火焰伤害",
        "WEAPON_ELECTRICITY_DAMAGE": "电击伤害",
        "WEAPON_POISON_DAMAGE": "毒素伤害",
        "WEAPON_IMPACT_DAMAGE": "冲击伤害",
        "WEAPON_PUNCTURE_DAMAGE": "穿刺伤害",
        "WEAPON_SLASH_DAMAGE": "切割伤害",
        "WEAPON_AREA_OF_EFFECT": "范围伤害",
        "WEAPON_HEADSHOT_DAMAGE": "爆头伤害",
        "WEAPON_FIRST_ATTACK_DAMAGE": "首发伤害",
    }
    out: list[str] = []
    blocks = []
    if isinstance(arcane.get("effects"), list):
        blocks.append(arcane["effects"])
    for conditional in arcane.get("conditionalEffects") or ():
        if isinstance(conditional, Mapping) and isinstance(conditional.get("effects"), list):
            blocks.append(conditional["effects"])
    for effects in blocks:
        for effect in effects:
            if not isinstance(effect, Mapping):
                continue
            upgrade = str(effect.get("upgradeType") or "")
            label = labels.get(upgrade)
            if not label:
                continue
            per_rank = effect.get("valuePerRank")
            rank_scale = 1.0
            if isinstance(per_rank, (int, float)) and not isinstance(per_rank, bool):
                rank_scale = float(per_rank)
            max_rank = arcane.get("maxRank")
            factor = rank_scale * ((int(max_rank) + 1) if isinstance(max_rank, int) and max_rank >= 0 else 1)
            operation = str(effect.get("operation") or "")
            if operation in {"ADD", "STACKING_MULTIPLY"} and factor:
                sign = "+" if factor > 0 else ""
                out.append(f"{sign}{round(factor * 100, 1)}% {label}")
    if out:
        return "；".join(dict.fromkeys(out))
    trigger = arcane.get("trigger") if isinstance(arcane.get("trigger"), Mapping) else {}
    condition = str(trigger.get("conditionTag") or "")
    if condition:
        return str(INCARNON_STRINGS.get(condition) or "")
    return ""


def _localized_condition(condition_tag: Any) -> str:
    """Resolve an exported trigger tag through the bundled Chinese strings."""
    tag = str(condition_tag or "")
    return str(INCARNON_STRINGS.get(tag) or "")


def _manual_arcane_rows() -> list[dict[str, Any]]:
    rows = []
    for arcane in EXPORTS.get("arcanes") or ():
        support = arcane.get("support") if isinstance(arcane.get("support"), Mapping) else {}
        if not arcane.get("path") or not support.get("manualState") or not int(support.get("weaponEffects") or 0):
            continue
        trigger = arcane.get("trigger") if isinstance(arcane.get("trigger"), Mapping) else {}
        compatibility = str(arcane.get("compatibility") or "")
        # Weapon-slot arcanes install on guns; PowerSuit-compatible ones are
        # the Warframe-slot entries the UI offers in the frame arcane slots.
        slot_kind = "warframe" if "PlayerPowerSuit" in compatibility else "weapon"
        effect = _arcane_effect_summary(arcane)
        chance = trigger.get("chance")
        duration = trigger.get("duration")
        stacks = trigger.get("maxStacks")
        condition_zh = _localized_condition(trigger.get("conditionTag"))
        trigger_bits = [condition_zh]
        if isinstance(chance, (int, float)):
            trigger_bits.append(f"{float(chance) * 100:g}%")
        if isinstance(duration, (int, float)):
            trigger_bits.append(f"{float(duration):g}s")
        if isinstance(stacks, int):
            trigger_bits.append(f"最多 {stacks} 层")
        icon = str(arcane.get("icon") or "")
        rows.append({
            "path": str(arcane.get("path")),
            "nameZh": str(arcane.get("nameZh") or arcane.get("nameEn") or ""),
            "nameEn": str(arcane.get("nameEn") or arcane.get("name") or ""),
            "maxRank": arcane.get("maxRank"),
            "rarity": str(arcane.get("rarity") or "COMMON"),
            "icon": icon,
            "iconAsset": f"/assets/arcanes/{Path(icon).name}" if icon else None,
            "compatibility": compatibility,
            "slotKind": slot_kind,
            "trigger": {
                "chance": trigger.get("chance"),
                "duration": trigger.get("duration"),
                "maxStacks": trigger.get("maxStacks"),
                "conditionTag": trigger.get("conditionTag"),
                "conditionZh": condition_zh,
            },
            "complete": bool(support.get("complete")),
            "runtime": bool(arcane.get("runtimeScripts")),
            "effect": effect,
            "description": " · ".join(bit for bit in [effect, *trigger_bits] if bit),
        })
    rows.sort(key=lambda row: (row["nameZh"].casefold(), row["path"]))
    return rows


MANUAL_ENEMIES = _complete_enemy_rows()
_ALL_MANUAL_MODS = _manual_mod_rows()
MANUAL_MODS = [row for row in _ALL_MANUAL_MODS if row["path"] not in UTILITY_MOD_PATHS]
MANUAL_ARCANES = _manual_arcane_rows()
_manual_mod_source = {row["path"]: row for row in _ALL_MANUAL_MODS}
_export_mod_source = {
    str(row.get("path") or ""): row
    for row in EXPORTS.get("mods") or ()
    if isinstance(row, Mapping) and row.get("path")
}


def _utility_catalog_row(row: Mapping[str, Any]) -> dict[str, Any]:
    path = str(row.get("path") or "")
    exported = _export_mod_source.get(path, {})
    mod_set = str(exported.get("modSet") or "")
    set_meta = WARFRAME_CATALOG.get("modSets", {}).get(mod_set, {}) if mod_set else {}
    merged = {**exported, **_manual_mod_source.get(path, {}), **row}
    if mod_set:
        merged.update({
            "modSet": mod_set,
            "modSetValues": list(exported.get("modSetValues") or ()),
            "setMaxPieces": set_meta.get("maxPieces"),
            "setName": set_meta.get("name"),
            "setNameZh": set_meta.get("nameZh"),
            "setDescription": set_meta.get("description"),
            "setDesc": set_meta.get("setDesc") or set_meta.get("description"),
            "setStats": list(set_meta.get("setStats") or set_meta.get("effects") or ()),
            "setConditionalEffects": list(set_meta.get("conditionalEffects") or ()),
            "setDisplayValues": dict(set_meta.get("displayValues") or {}),
            "setRuntime": dict(set_meta.get("runtime") or {}),
            "setSource": set_meta.get("sourcePath"),
        })
    merged["category"] = "set" if mod_set else "exilus"
    merged["type"] = "weapon-exilus"
    merged["sourceType"] = "Weapon Exilus"
    merged["maxRank"] = merged.get("maxRank") if merged.get("maxRank") is not None else merged.get("rank", 0)
    return merged


CATALOG_UTILITY_MODS = [
    _utility_catalog_row(row)
    for row in UTILITY_MOD_ROWS
]
CATALOG["manualMods"] = MANUAL_MODS
# Variant path (Beginner/Intermediate/Expert) -> canonical card path, so the
# workbench can display solver picks that reference tiered variants.
CATALOG["manualModAliases"] = MANUAL_MOD_ALIASES
CATALOG["manualModVariants"] = MANUAL_MOD_VARIANTS
CATALOG["enemies"] = MANUAL_ENEMIES
CATALOG["arcanes"] = MANUAL_ARCANES
CATALOG["utilityMods"] = CATALOG_UTILITY_MODS
CATALOG["modSets"] = dict(WARFRAME_CATALOG.get("modSets") or {})
CATALOG["manualCounts"] = {
    "mods": len(MANUAL_MODS),
    "enemies": len(MANUAL_ENEMIES),
    "arcanes": len(MANUAL_ARCANES),
}


def _kitgun_part_catalog() -> dict[str, Any]:
    """Expose Kitgun chambers / grips / loaders for the assembly UI.

    Chambers carry the riven disposition (omegaAttenuation), their per-slot
    base fire-mode stats and grip/loader override rows so the frontend can
    render hover previews without extra requests.
    """
    kitguns = EXPORTS.get("kitguns") or {}
    out: dict[str, Any] = {}

    def _mode_summary(mode: Mapping[str, Any]) -> dict[str, Any]:
        damage = mode.get("damage") if isinstance(mode.get("damage"), Mapping) else {}
        types = damage.get("types") or {}
        total = damage.get("total")
        radial = damage.get("radial") if isinstance(damage.get("radial"), Mapping) else None
        radial_types = (radial or {}).get("types") or {}
        return {
            "total": total if isinstance(total, (int, float)) else (sum(v for v in types.values() if isinstance(v, (int, float))) or None),
            "types": {str(k): v for k, v in types.items() if isinstance(v, (int, float))},
            "critChance": damage.get("critChance"),
            "critMultiplier": damage.get("critMultiplier"),
            "procChance": damage.get("procChance"),
            "fireRate": mode.get("fireRate"),
            "trigger": mode.get("trigger"),
            "unsupported": [str(u) for u in (mode.get("unsupported") or ())],
            "radial": {
                "total": radial.get("total"),
                "types": {str(k): v for k, v in radial_types.items() if isinstance(v, (int, float))},
                "radius": radial.get("radius"),
                "falloff": radial.get("falloff"),
                "procChance": radial.get("procChance"),
            } if radial else None,
        }

    for key, label in (("barrels", "chambers"), ("handles", "grips"), ("clips", "loaders")):
        rows = kitguns.get(key) or {}
        entries: list[dict[str, Any]] = []
        for path, row in rows.items():
            if not isinstance(row, Mapping):
                continue
            entry: dict[str, Any] = {
                "path": str(row.get("path") or path),
                "nameZh": str(row.get("nameZh") or ""),
                "nameEn": str(row.get("nameEn") or ""),
                "slot": row.get("slot"),
                "gunTypes": sorted({str(o.get("gunType") or "") for o in (row.get("overrides") or ()) if isinstance(o, Mapping)}),
                "disposition": row.get("omegaAttenuation"),
                "primaryDisposition": row.get("primaryOmegaAttenuation"),
                "primaryModes": len(row.get("primaryModes") or []),
                "secondaryModes": len(row.get("secondaryModes") or []),
            }
            if key == "barrels":
                entry["modes"] = {
                    "primary": [_mode_summary(m) for m in (row.get("primaryModes") or ()) if isinstance(m, Mapping)],
                    "secondary": [_mode_summary(m) for m in (row.get("secondaryModes") or ()) if isinstance(m, Mapping)],
                }
            else:
                entry["overrides"] = [
                    {
                        "gunType": str(o.get("gunType") or ""),
                        "barrelType": str(o.get("barrelType") or ""),
                        "damage": o.get("damage"),
                        "fireRate": o.get("fireRate"),
                        "critChance": o.get("critChance"),
                        "critMultiplier": o.get("critMultiplier"),
                        "procChance": o.get("procChance"),
                        "magazineSize": o.get("magazineSize"),
                        "reloadTime": o.get("reloadTime"),
                        "traceDistance": o.get("traceDistance"),
                    }
                    for o in (row.get("overrides") or ())
                    if isinstance(o, Mapping)
                ]
            entries.append(entry)
        out[label] = entries
    return out


def _zaw_part_catalog() -> dict[str, Any]:
    """Expose Zaw strikes / grips / links for the assembly UI."""
    zaws = EXPORTS.get("zaws") or {}
    out: dict[str, Any] = {}

    def _num(value: Any) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return round(float(value), 4)

    for key, label in (("strikes", "strikes"), ("grips", "grips"), ("links", "links")):
        rows = zaws.get(key) or {}
        entries: list[dict[str, Any]] = []
        for path, row in rows.items():
            if not isinstance(row, Mapping):
                continue
            entry: dict[str, Any] = {
                "path": str(row.get("path") or path),
                "nameZh": str(row.get("nameZh") or ""),
                "nameEn": str(row.get("nameEn") or ""),
            }
            if key == "strikes":
                damage = row.get("damage") if isinstance(row.get("damage"), Mapping) else {}
                entry.update({
                    "disposition": row.get("omegaAttenuation"),
                    "oneHanded": row.get("oneHanded"),
                    "twoHanded": row.get("twoHanded"),
                    "damage": {
                        "total": damage.get("total"),
                        "types": {str(k): v for k, v in (damage.get("types") or {}).items() if isinstance(v, (int, float))},
                    },
                    "critChance": row.get("critChance"),
                    "critMultiplier": row.get("critMultiplier"),
                    "procChance": row.get("procChance"),
                    "speedMod": row.get("speedMod"),
                })
            elif key == "grips":
                entry.update({
                    "handed": row.get("handed"),
                    "damageBonus": _num(row.get("damageBonus")),
                    "baseSpeed": _num(row.get("baseSpeed")),
                })
            else:
                entry.update({
                    "speedBonus": _num(row.get("speedBonus")),
                    "critChance": row.get("critChance"),
                    "statusChance": row.get("statusChance"),
                    "damageBonus": _num(row.get("damageBonus")),
                })
            entries.append(entry)
        out[label] = entries
    return out


CATALOG["kitgunParts"] = _kitgun_part_catalog()
CATALOG["zawParts"] = _zaw_part_catalog()


def analyze_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SimulationError("request body must be a JSON object")
    request = dict(payload)
    legacy = request.get("disposition") is None and request.get("sourceWeapon")
    weapon_path = request.get("sourceWeapon") if legacy else request.get("weapon")
    if not isinstance(weapon_path, str) or not weapon_path.strip():
        raise SimulationError("weapon must be an exported weapon path")
    weapon = CATALOG_WEAPONS_BY_PATH.get(weapon_path.strip())
    if weapon is None:
        raise SimulationError("weapon is not in the portable Riven catalog")
    selected_catalog_weapon, innate_selection = _innate_element_selection(request, weapon)
    # 组合枪/组合近战：带齐部件时按装配后的记录分析（与配装路由同口径），
    # 并跳过基体的可用性检查（基体本身不可直接使用）。
    kitgun_parts = _manual_kitgun_parts(request.get("kitgunParts"))
    assembly_ready = len(kitgun_parts) == 3
    if request.get("kitgunParts") is not None and not assembly_ready:
        raise SimulationError("kitgunParts 需要腔体/剑刃、握把、装填器/配重三件齐全")
    if not assembly_ready:
        if not weapon["available"]:
            raise SimulationError(weapon.get("issue") or "weapon is unavailable")
        if not weapon["analysisAvailable"]:
            raise SimulationError(
                weapon.get("analysisIssue") or "weapon analysis is unavailable"
            )

    disposition_value = (
        request.get("sourceDisposition") if legacy else request.get("disposition")
    )
    disposition = _finite_positive(disposition_value)
    if disposition is None or disposition > 2:
        raise SimulationError("disposition must be finite and between 0 and 2")
    raw_stats = request.get("stats")
    if not isinstance(raw_stats, list) or not 2 <= len(raw_stats) <= 4:
        raise SimulationError("portable Riven input requires 2 to 4 stat objects")
    if any(not isinstance(stat, Mapping) for stat in raw_stats):
        raise SimulationError("portable Riven stats must be objects")
    if any(not isinstance(stat.get("negative", False), bool) for stat in raw_stats):
        raise SimulationError("portable Riven stat negative flags must be boolean")
    negative_count = sum(stat.get("negative") is True for stat in raw_stats)
    positive_count = len(raw_stats) - negative_count
    if positive_count not in {2, 3} or negative_count > 1:
        raise SimulationError(
            "portable Riven input requires 2 or 3 positive stats and at most 1 negative stat"
        )

    bases = RIVEN_BASE_VALUES.get(weapon["weaponType"], {})
    normalized_stats = []
    for raw in raw_stats:
        code = str(raw.get("code") or "").strip().upper()
        base = _finite_positive(bases.get(code))
        value = _finite_positive(raw.get("value"))
        if base is None or value is None:
            raise SimulationError(f"Riven stat {code or '?'} has no valid portable range")
        negative = raw.get("negative") is True
        if negative:
            multiplier = 0.757525 if positive_count == 3 else 0.5
        else:
            multiplier = 0.757525 if positive_count == 3 else 1.0
            if negative_count:
                multiplier *= 1.25
        nominal = abs(base * disposition * multiplier)
        low, high = nominal * 0.89, nominal * 1.089
        if value < low - 0.11 or value > high + 0.11:
            raise SimulationError(
                f"Riven stat {code} value {value:g} is outside {low:.1f}-{high:.1f}"
            )
        normalized_stats.append({**raw, "code": code, "low": low, "high": high})
    engine_request = {
        **request,
        "weapon": weapon["path"],
        "disposition": disposition,
        "stats": normalized_stats,
    }
    engine_request.pop("sourceWeapon", None)
    engine_request.pop("sourceDisposition", None)
    engine_request.pop("kitgunParts", None)
    assembled_record = None
    analysis_record = None
    if assembly_ready:
        base_record = optimizer.resolve_record(
            EXPORTS["weapons"], weapon["path"], kind="weapon"
        )
        zaw_rules = EXPORTS.get("zaws") or {}
        zaw_strike_paths = zaw_rules.get("strikes") or {}
        if any(
            str(part).strip().replace("\\", "/").rstrip("/") in zaw_strike_paths
            for part in kitgun_parts
        ):
            assembled_record = resolve_zaw_record(base_record, kitgun_parts, zaw_rules)
        else:
            assembled_record = resolve_kitgun_record(
                base_record, kitgun_parts, EXPORTS["kitguns"]
            )
        analysis_record, _ = _innate_element_selection(request, assembled_record)
    else:
        base_record = optimizer.resolve_record(
            EXPORTS["weapons"], weapon["path"], kind="weapon"
        )
        analysis_record, _ = _innate_element_selection(request, base_record)
    if assembled_record is not None and innate_selection is not None:
        assembled_record = {**assembled_record, "innateElements": [innate_selection]}
        analysis_record = assembled_record
    # 近战/组合近战：架势参与解算（与配装页同口径，默认普攻 DPS 倍率最高的
    # 架势，容量收益计入）；枪械/组合枪无架势。
    analysis_stance = None
    if weapon["weaponType"] in {"melee", "zaw"}:
        stance_record = assembled_record
        if stance_record is None:
            stance_record = optimizer.resolve_record(
                EXPORTS["weapons"], weapon["path"], kind="weapon"
            )
        analysis_stance = _analysis_stance(stance_record, weapon["weaponType"])
    with ANALYZE_LOCK:
        result = optimizer.analyze_riven_request(
            EXPORT_DIR,
            engine_request,
            weapon_record=analysis_record if innate_selection is not None else assembled_record,
            stance=analysis_stance,
            statics_cache=ANALYSIS_STATICS_CACHE,
        )
        _persist_analysis_statics_cache()
    result.pop("projection", None)
    return {
        **result,
        "disposition": disposition,
        "innateElement": innate_selection,
        "innateElementCandidates": list(selected_catalog_weapon.get("innateElementCandidates") or ()),
    }


def _alternate_build_modes(
    weapon: Mapping[str, Any],
    evaluation: Any,
    selected_fire_mode: int,
    scenario: Any,
    passives: Any = None,
) -> list[dict[str, Any]]:
    effects = optimizer._selected_effects(evaluation, None, scenario, passives)
    rows = []
    for index, mode in enumerate(weapon.get("fireModes") or ()):
        if index == selected_fire_mode or not isinstance(mode, Mapping):
            continue
        row: dict[str, Any] = {
            "fireMode": index,
            "trigger": str(mode.get("trigger") or ""),
            "isAlternateFire": bool(mode.get("isAlternateFire")),
        }
        try:
            stats = optimizer.apply_mods(
                weapon, effects, fire_mode=index, scenario=scenario
            )
            events = optimizer.evaluate_projectile_events(
                weapon, effects, fire_mode=index, scenario=scenario
            )
        except (TypeError, ValueError) as exc:
            row.update(available=False, issue=str(exc))
        else:
            row.update(
                available=True,
                metrics=optimizer._metrics(stats, events),
                unsupported=sorted(
                    {
                        *stats.unsupported,
                        *((events or {}).get("unsupported") or ()),
                    }
                ),
                skipped=list(dict.fromkeys(stats.skipped)),
            )
        rows.append(row)
    return rows


def _modded_stats_payload(
    stats: Any, weapon_type: str, stance_multiplier: float = 1.0
) -> dict[str, Any]:
    # Crit-adjusted DPS mirrors the optimizer's _metrics so the live HUD shows
    # 持续/爆发 DPS even in the panel model (where targetDamage is hidden).
    crit = effective_hit_multiplier(
        stats.crit_chance, stats.crit_multiplier, stats.noncrit_damage_multiplier
    )
    result = {
        "damageTypes": dict(stats.damage_types),
        "innateDamageTypes": dict(getattr(stats, "innate_damage_types", {}) or {}),
        "innateElementCandidates": list(getattr(stats, "innate_element_candidates", ()) or ()),
        "totalDamage": stats.total_damage,
        "averageHit": stats.average_hit,
        "sustainedDps": stats.sustained_dps * crit * stance_multiplier,
        "burstDps": stats.burst_dps * crit * stance_multiplier,
        "critChance": stats.crit_chance,
        "critMultiplier": stats.crit_multiplier,
        "statusChance": stats.status_chance,
        "multishot": stats.multishot,
        "fireRate": stats.fire_rate,
        "magazine": stats.magazine,
        "reloadTime": stats.reload_time,
        "spreadMultiplier": stats.spread_multiplier,
        "recoilMultiplier": stats.recoil_multiplier,
        "ammoMaxMultiplier": stats.ammo_max_multiplier,
        # 膛室家族首发加成：bonus>0 时前端展示「首发单发」行。
        "firstShotDamageBonus": stats.first_shot_damage_bonus,
        "firstShotHit": stats.first_shot_hit * stance_multiplier,
    }
    if weapon_type in {"melee", "zaw"}:
        result.update(
            initialCombo=stats.initial_combo,
            comboDuration=stats.combo_duration,
            heavyAttackEfficiency=stats.heavy_attack_efficiency,
            heavyDamage=stats.heavy_damage,
            stanceMultiplier=stance_multiplier,
        )
    return result


def build_weapon_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SimulationError("request body must be a JSON object")
    weapon_path = payload.get("weapon")
    if not isinstance(weapon_path, str) or weapon_path.strip():
        weapon_path = weapon_path.strip() if isinstance(weapon_path, str) else None
    else:
        weapon_path = None
    if not weapon_path:
        raise SimulationError("weapon must be an exported weapon path")
    catalog_weapon = CATALOG_WEAPONS_BY_PATH.get(weapon_path)
    if catalog_weapon is None:
        raise SimulationError("weapon is not in the portable Riven catalog")
    kitgun_parts = _manual_kitgun_parts(payload.get("kitgunParts"))
    assembly_ready = bool(kitgun_parts)
    if not assembly_ready:
        if not catalog_weapon["available"]:
            raise SimulationError(catalog_weapon.get("issue") or "weapon is unavailable")
        if not catalog_weapon["buildAvailable"]:
            raise SimulationError(
                catalog_weapon.get("buildIssue") or "weapon build is unavailable"
            )

    fire_mode = payload.get("fireMode", 0)
    if isinstance(fire_mode, bool) or not isinstance(fire_mode, int):
        raise SimulationError("fireMode must be a non-negative integer")
    slot_count = payload.get("slotCount", payload.get("slots", 8))
    if isinstance(slot_count, bool) or not isinstance(slot_count, int) or not 1 <= slot_count <= 8:
        raise SimulationError("slotCount must be an integer between 1 and 8")

    metric_rows = _metric_options(catalog_weapon["weaponType"])
    allowed_metrics = {row["id"] for row in metric_rows}
    metric = payload.get("metric") or metric_rows[0]["id"]
    if metric not in allowed_metrics:
        raise SimulationError(
            "metric must be one of " + ", ".join(row["id"] for row in metric_rows)
        )

    element_key = payload.get("elementTarget", payload.get("element"))
    if element_key in (None, ""):
        element_key = None
        required_damage_type = None
        element_target = None
    elif not isinstance(element_key, str) or element_key not in ELEMENT_TARGETS:
        raise SimulationError(
            "elementTarget must be empty or one of " + ", ".join(ELEMENT_TARGETS)
        )
    else:
        required_damage_type, label = ELEMENT_TARGETS[element_key]
        element_target = {
            "id": element_key,
            "damageType": required_damage_type,
            "label": label,
        }

    weapon_record = optimizer.resolve_record(
        EXPORTS["weapons"], catalog_weapon["path"], kind="weapon"
    )
    weapon_record = _special_slot_override(payload, weapon_record, catalog_weapon["weaponType"])
    if assembly_ready:
        zaw_rules = EXPORTS.get("zaws") or {}
        zaw_strike_paths = zaw_rules.get("strikes") or {}
        if any(
            str(part).strip().replace("\\", "/").rstrip("/") in zaw_strike_paths
            for part in kitgun_parts
        ):
            weapon_record = resolve_zaw_record(weapon_record, kitgun_parts, zaw_rules)
        else:
            weapon_record = resolve_kitgun_record(
                weapon_record, kitgun_parts, EXPORTS["kitguns"]
            )
        selected_weapon = weapon_record
        selected_fire_mode = 0
    else:
        selected_weapon, selected_fire_mode = optimizer._select_fire_mode(
            weapon_record, fire_mode, weapon_type=catalog_weapon["weaponType"]
        )
    # Assembly can rebuild the record (and its polarities), so apply the
    # explicit special-slot Forma once more to the final selected mode.
    selected_weapon = _special_slot_override(
        payload, selected_weapon, catalog_weapon["weaponType"]
    )
    selected_weapon, innate_selection = _innate_element_selection(payload, selected_weapon)
    if innate_selection is not None:
        weapon_record = {**weapon_record, "innateElements": [innate_selection]}
    if catalog_weapon.get("isExalted"):
        selected_weapon = {**selected_weapon, "isExalted": True}
    catalog_mode = next(
        (
            mode
            for mode in catalog_weapon["fireModes"]
            if mode["index"] == selected_fire_mode
        ),
        None,
    )
    if not assembly_ready:
        availability = (
            (catalog_mode.get("metricAvailability") or {}).get(metric)
            if catalog_mode is not None
            else None
        )
        if not isinstance(availability, Mapping) or not availability.get("available"):
            raise SimulationError(
                str((availability or {}).get("issue") or (
                    f"fire mode {selected_fire_mode} metric {metric} is unavailable"
                ))
            )
    damage = (selected_weapon.get("fireModes") or [{}])[0].get("damage") or {}
    if not isinstance(damage, Mapping) or not damage.get("types"):
        raise SimulationError(f"fire mode {selected_fire_mode} has no direct damage types")

    scenario = optimizer._scenario(metric)
    stance = _resolve_stance(
        selected_weapon, catalog_weapon["weaponType"], payload.get("stancePath")
    )
    stance_multiplier = float((stance or {}).get("dpsMultiplier") or 1.0)
    status_rate_multiplier = float((stance or {}).get("statusRateMultiplier") or 1.0)
    capacity_limit = 60 + int((stance or {}).get("capacityGain") or 0)
    incarnon_card, incarnon_choices, incarnon_unsupported, incarnon_policy = optimizer._incarnon_card(
        selected_weapon,
        payload.get("incarnonChoices"),
        scenario=scenario,
        metric=optimizer._objective_metric(metric),
        policy=EXPORTS.get("incarnonDefaults"),
        build_label=EXPORTS["buildLabel"],
    )
    candidates, rejected_mods = optimizer._candidate_mods(
        EXPORTS, selected_weapon, scenario
    )
    candidates = [
        card
        for card in candidates
        if card.record is None
        or (
            str(card.record.get("path") or "") in MANUAL_MODS_BY_PATH
            and str(card.record.get("path") or "") not in UTILITY_MOD_PATHS
        )
    ]
    enemy_path = payload.get("enemy")
    if not isinstance(enemy_path, str) or enemy_path not in MANUAL_ENEMIES_BY_PATH:
        enemy_path = MANUAL_ENEMIES[0]["path"]
    target = MANUAL_ENEMIES_BY_PATH[enemy_path]
    if str(payload.get("damageModel") or "target").casefold() == "custom":
        target = _custom_enemy_snapshot(
            payload.get("defenseSnapshot") or payload.get("customDefense")
        )
    level = _manual_int(payload.get("level", 160), "level")
    armour_strip = _manual_number(
        payload.get("armourStrip", 0.0), "armourStrip", low=0.0, high=1.0
    )
    elemental_strip = _manual_number(
        payload.get("elementalArmourStrip", 0.0),
        "elementalArmourStrip",
        low=0.0,
        high=1.0,
    )
    steel_path = payload.get("steelPath", False)
    if not isinstance(steel_path, bool):
        raise SimulationError("steelPath must be a boolean")
    enemy_enhancements, _ = _manual_enemy_enhancements(
        payload, steel_path=steel_path
    )
    target_context = {
        "target": target,
        "level": level,
        "armour_strip": armour_strip,
        "elemental_armour_strip": elemental_strip,
        "steel_path": steel_path,
        "enemy_enhancements": enemy_enhancements,
        "hit_location": "body",
        "stanceMultiplier": stance_multiplier,
        "statusRateMultiplier": status_rate_multiplier,
    }
    objective = optimizer._objective_metric(metric)
    dual_route = objective in {"sustainedDps", "attackDps"}
    with ANALYZE_LOCK:
        try:
            direct = optimizer._optimize(
                selected_weapon,
                candidates,
                None,
                scenario=scenario,
                metric="targetSustainedDps" if dual_route else objective,
                passives=incarnon_card,
                slot_count=slot_count,
                capacity_limit=capacity_limit,
                required_damage_type=required_damage_type,
                target_context=target_context if dual_route else None,
            )
        except SimulationError as exc:
            raise _translate_damage_type_failure(
                exc, selected_weapon, required_damage_type, element_target
            ) from exc
        if not getattr(direct, "cards", None) or not _finite_positive(getattr(direct, "score", None)):
            raise SimulationError(
                f"optimizer returned no usable MOD build for fire mode {selected_fire_mode} metric {metric}"
            )
        status = None
        if dual_route:
            crit_types = {
                "WEAPON_CRIT_CHANCE",
                "WEAPON_CRIT_DAMAGE",
                "WEAPON_DOUBLE_CRIT_CHANCE",
            }
            status_candidates = [
                card
                for card in candidates
                if card.required
                or not any(effect.upgrade_type in crit_types for effect in card.effects)
            ]
            try:
                status = optimizer._optimize(
                    selected_weapon,
                    status_candidates,
                    None,
                    scenario=scenario,
                    metric="statusSustainedDps",
                    passives=incarnon_card,
                    slot_count=slot_count,
                    capacity_limit=capacity_limit,
                    required_damage_type=required_damage_type,
                    target_context=target_context,
                )
            except SimulationError as exc:
                raise _translate_damage_type_failure(
                    exc, selected_weapon, required_damage_type, element_target
                ) from exc
        direct, direct_exilus = _auto_exilus(
            selected_weapon,
            catalog_weapon,
            direct,
            scenario=scenario,
            metric="targetSustainedDps" if dual_route else objective,
            passives=incarnon_card,
            target_context=target_context if dual_route else None,
            capacity_limit=capacity_limit,
        )
        status_exilus = None
        if status is not None:
            status, status_exilus = _auto_exilus(
                selected_weapon,
                catalog_weapon,
                status,
                scenario=scenario,
                metric="statusSustainedDps",
                passives=incarnon_card,
                target_context=target_context,
                capacity_limit=capacity_limit,
            )
        direct_total = (
            optimizer._score(
                direct.stats,
                "statusSustainedDps",
                target_context=target_context,
            )
            if dual_route
            else direct.score
        )
        status_total = status.score if status is not None else None
        evaluation = status if status_total is not None and status_total > direct_total else direct
        build_archetype = "status" if evaluation is status else "direct"
        selected_exilus = status_exilus if evaluation is status else direct_exilus
        if not evaluation.cards or not _finite_positive(evaluation.score):
            raise SimulationError(
                f"optimizer returned no usable MOD build for fire mode {selected_fire_mode} metric {metric}"
            )
        build = optimizer._build_payload(selected_weapon, evaluation, None, incarnon_card)
        evaluated_metrics = optimizer._metrics(evaluation.stats)
        for key in ("shotDamage", "burstDps", "sustainedDps", "attackDps"):
            build[key] = evaluated_metrics[key]
        build["damageTypes"] = dict(evaluation.stats.damage_types)
        build["archetype"] = build_archetype
        build["objectiveDps"] = status_total if evaluation is status else direct_total
        build["stance"] = stance
        build["exilus"] = selected_exilus
        build["forma"] = _forma_summary(selected_weapon, evaluation.cards, stance)
        alternate_modes = _alternate_build_modes(
            weapon_record, evaluation, selected_fire_mode, scenario, incarnon_card
        )

    skipped = [
        f"optimizer-assumption: {slot_count} ordinary slots, {capacity_limit} capacity after stance, Catalyst and matching ordinary-slot Forma",
        "optimizer-objective: direct and no-crit status sustained routes compared against the selected target",
        f"optimizer-search: beam width 24, shortlist 56, {len(candidates)} candidate mods, {rejected_mods} unsupported mods rejected",
    ]
    if element_target:
        skipped.append(
            f"optimizer-element-target: final build must contain {required_damage_type}"
        )
    skipped.extend(evaluation.stats.skipped)
    return {
        "buildLabel": EXPORTS["buildLabel"],
        "schemaVersion": EXPORTS["schemaVersion"],
        "weapon": optimizer.record_identity(weapon_record),
        "weaponType": catalog_weapon["weaponType"],
        "fireMode": selected_fire_mode,
        "metric": metric,
        "buildArchetype": build_archetype,
        "archetypeComparison": {
            "direct": direct_total,
            "status": status_total,
            "selected": build_archetype,
        },
        "slotCount": slot_count,
        "elementTarget": element_target,
        "innateElement": innate_selection,
        "innateElementCandidates": list(catalog_weapon.get("innateElementCandidates") or ()),
        "incarnonChoices": incarnon_choices,
        "incarnonPolicy": incarnon_policy,
        "stance": stance,
        "exilus": selected_exilus,
        "specialSlotPolarities": _special_slot_polarities(
            selected_weapon, catalog_weapon["weaponType"]
        ),
        "forma": build["forma"],
        "capacity": evaluation.capacity,
        "capacityLimit": capacity_limit,
        "build": build,
        "moddedStats": _modded_stats_payload(
            evaluation.stats, catalog_weapon["weaponType"], stance_multiplier
        ),
        "alternateModes": alternate_modes,
        "unsupported": sorted(set(build.get("unsupported") or ()) | set(incarnon_unsupported)),
        "skipped": list(dict.fromkeys(skipped)),
        "limitations": CATALOG["buildOptions"]["limitations"],
    }


MANUAL_ENEMIES_BY_PATH = {row["path"]: row for row in MANUAL_ENEMIES}
MANUAL_MODS_BY_PATH = {row["path"]: row for row in MANUAL_MODS}
for alias, canonical in MANUAL_MOD_ALIASES.items():
    if canonical in MANUAL_MODS_BY_PATH:
        MANUAL_MODS_BY_PATH.setdefault(alias, MANUAL_MODS_BY_PATH[canonical])
# Tiered variants resolve to their OWN row (real maxRank/drain), overriding the
# alias-to-canonical mapping above so validation matches what the kernel sims.
MANUAL_MODS_BY_PATH.update({
    row["path"]: row for row in MANUAL_MOD_VARIANTS
    if row["path"] not in UTILITY_MOD_PATHS
})
UTILITY_MODS_BY_PATH = {row["path"]: row for row in CATALOG_UTILITY_MODS}
MANUAL_ARCANES_BY_PATH = {row["path"]: row for row in MANUAL_ARCANES}


# External damage buffs beyond Arcanes — wiki-verified (wiki.warframe.com) and
# cross-checked against Riven-Mirror's BuffList categories. All entries are
# weapon-relevant multipliers; ability-strength-only buffs are intentionally
# excluded (they do not affect weapon damage directly).
# bucket: engine multiplier bucket the buff feeds.
#   faction        -> GAMEPLAY_FACTION_DAMAGE "" row (multiplicative)
#   total          -> WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE (final damage)
#   base           -> WEAPON_DAMAGE_AMOUNT (additive base-damage bucket)
#   element-fire/cold/electricity/toxin/radiation/corrosive -> element add
#   crit-chance / crit-damage / status / multishot / fire-rate / reload / magazine
EXTERNAL_BUFFS: dict[str, dict[str, Any]] = {
    # 乘法总伤类
    "roar": {"label": "战吼 Roar（Rhino/Helminth）", "bucket": "faction", "baseValue": 0.5, "note": "派系乘区，受强度；wiki: 100×(1+0.5×(1+0.3))"},
    "eclipse": {"label": "黯然失色 Eclipse 光照（Mirage）", "bucket": "total", "baseValue": 2.0, "note": "+200% 终伤（受强度）"},
    "molecular-prime": {"label": "分子填充 Molecular Prime（Nova）", "bucket": "total", "baseValue": 1.0, "note": "双倍伤害（固定）"},
    "void-strike": {"label": "虚空重击 Void Strike（Madurai）", "bucket": "total", "baseValue": 12.0, "note": "8 充能 ×12.5%/层（默认按时间窗）"},
    "unairu-wisp": {"label": "Unairu 虚灵（4 层）", "bucket": "total", "baseValue": 1.0, "note": "+100%（4×25%）"},
    "arbitration": {"label": "仲裁无人机加成", "bucket": "total", "baseValue": 3.0, "note": "+300% 强度类终伤"},
    # 加法基伤类
    "base-damage": {"label": "通用基伤加成", "bucket": "base", "baseValue": 1.0, "note": "与基伤 mod 同乘区"},
    "vex-armor": {"label": "怨怒护甲 Vex Armor（Chroma）", "bucket": "base", "baseValue": 2.75, "note": "+275%（受强度）"},
    "shooting-gallery": {"label": "靶场 Shooting Gallery（Mesa）", "bucket": "base", "baseValue": 0.25, "note": "+25%（受强度）"},
    "mallet": {"label": "强音增幅 Mallet（Octavia 放大）", "bucket": "base", "baseValue": 2.0, "note": "+200%（受强度）"},
    "metamorphosis": {"label": "昼夜交替 Metamorphosis（Equinox）", "bucket": "base", "baseValue": 0.25, "note": "+25%（受强度）"},
    "vigoruous-swap": {"label": "强力切换 Vigorous Swap", "bucket": "base", "baseValue": 1.65, "note": "11 层 +15%/层"},
    "dead-eye": {"label": "死亡之眼 Dead Eye（集团光环）", "bucket": "base", "baseValue": 0.525, "note": "+52.5% 基伤（乘区同基伤）"},
    # 附加元素类
    "fireball-frenzy": {"label": "狂热火球 Fireball Frenzy（Ember 集团）", "bucket": "element-fire", "baseValue": 1.0, "note": "+100% 火焰（受强度）"},
    "flash-accelerant": {"label": "闪耀助燃 Flash Accelerant（Ember 集团）", "bucket": "element-fire", "baseValue": 0.5, "note": "+50% 火焰（受强度）"},
    "freeze-force": {"label": "寒冰之力 Freeze Force（Frost 集团）", "bucket": "element-cold", "baseValue": 1.0, "note": "+100% 冰冻（受强度）"},
    "shock-trooper": {"label": "电击奇兵 Shock Trooper（Volt 集团）", "bucket": "element-electricity", "baseValue": 1.0, "note": "+100% 电击（受强度）"},
    "smite-infusion": {"label": "惩击洗礼 Smite Infusion（Oberon 集团）", "bucket": "element-radiation", "baseValue": 1.0, "note": "+100% 辐射（受强度）"},
    "venom-dose": {"label": "猛毒附加 Venom Dose（Saryn 集团）", "bucket": "element-corrosive", "baseValue": 1.0, "note": "+100% 腐蚀（受强度）"},
    # 暴击/触发/多重/射速
    "crit-chance": {"label": "通用暴击加成", "bucket": "crit-chance", "baseValue": 1.0, "note": "暴击几率加成"},
    "covenant": {"label": "庇佑圣约 Covenant（Harrow）", "bucket": "crit-chance", "baseValue": 0.5, "note": "+50% 暴击（满层）"},
    "crit-damage": {"label": "通用暴伤加成", "bucket": "crit-damage", "baseValue": 1.0, "note": "暴击伤害加成"},
    "status": {"label": "通用触发加成", "bucket": "status", "baseValue": 1.0, "note": "触发几率加成"},
    "multishot": {"label": "通用多重加成", "bucket": "multishot", "baseValue": 1.0, "note": "多重射击加成"},
    "fire-rate": {"label": "通用射速加成", "bucket": "fire-rate", "baseValue": 1.0, "note": "射速/攻速加成"},
    "warcry": {"label": "咆哮 Warcry（Valkyr 近战）", "bucket": "fire-rate", "baseValue": 0.5, "note": "+50% 攻速（受强度）"},
    "reload": {"label": "通用装填加成", "bucket": "reload", "baseValue": 1.0, "note": "装填速度加成"},
    "magazine": {"label": "通用弹匣加成", "bucket": "magazine", "baseValue": 1.0, "note": "弹匣容量加成"},
}

_ELEMENT_BUCKETS = {
    "element-fire": "DT_FIRE",
    "element-cold": "DT_FREEZE",
    "element-electricity": "DT_ELECTRICITY",
    "element-toxin": "DT_POISON",
    "element-radiation": "DT_RADIATION",
    "element-corrosive": "DT_CORROSIVE",
}
_BUCKET_UPGRADE = {
    "total": "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE",
    "base": "WEAPON_DAMAGE_AMOUNT",
    "crit-chance": "WEAPON_CRIT_CHANCE",
    "crit-damage": "WEAPON_CRIT_DAMAGE",
    "status": "WEAPON_PROC_CHANCE",
    "multishot": "WEAPON_FIRE_ITERATIONS",
    "fire-rate": "WEAPON_FIRE_RATE",
    "reload": "WEAPON_RELOAD_SPEED",
    "magazine": "WEAPON_CLIP_MAX",
}


def _external_buff_effects(entries: Any) -> Any:
    """Translate requested external buffs into engine ModEffects."""
    from wfarsenal.damage import ModEffect, ModEffectList

    if entries is None:
        return None
    if not isinstance(entries, list) or len(entries) > 12:
        raise SimulationError("externalBuffs must be an array with at most 12 entries")
    effects: list[ModEffect] = []
    for index, item in enumerate(entries):
        if not isinstance(item, Mapping):
            raise SimulationError(f"externalBuffs[{index}] must be an object")
        buff_id = str(item.get("id") or "")
        spec = EXTERNAL_BUFFS.get(buff_id)
        if spec is None:
            raise SimulationError(f"externalBuffs[{index}].id is not a known buff")
        value = _manual_number(item.get("value", spec["baseValue"]), f"externalBuffs[{index}].value", low=0.0, high=50.0)
        bucket = spec["bucket"]
        if bucket == "faction":
            effects.append(ModEffect(upgrade_type="GAMEPLAY_FACTION_DAMAGE", operation="STACKING_MULTIPLY", value=value, source_path=f"external:{buff_id}"))
        elif bucket in _ELEMENT_BUCKETS:
            effects.append(ModEffect(upgrade_type="WEAPON_PERCENT_BASE_DAMAGE_ADDED", operation="STACKING_MULTIPLY", value=value, damage_type=_ELEMENT_BUCKETS[bucket], source_path=f"external:{buff_id}"))
        else:
            upgrade = _BUCKET_UPGRADE.get(bucket)
            if upgrade:
                effects.append(ModEffect(upgrade_type=upgrade, operation="STACKING_MULTIPLY", value=value, source_path=f"external:{buff_id}"))
    if not effects:
        return None
    return ModEffectList(effects)


def _manual_number(value: Any, label: str, *, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SimulationError(f"{label} must be a finite number")
    value = float(value)
    if low is not None and value < low or high is not None and value > high:
        raise SimulationError(f"{label} must be between {low:g} and {high:g}")
    return value


def _manual_int(value: Any, label: str, *, low: int = 0, high: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < low or high is not None and value > high:
        suffix = f" and at most {high}" if high is not None else ""
        raise SimulationError(f"{label} must be an integer at least {low}{suffix}")
    return value


def _custom_enemy_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SimulationError("defenseSnapshot must be an object")

    def amount(key: str, *, minimum: float) -> float:
        raw = value.get(key, 0.0)
        return _manual_number(raw, f"defenseSnapshot.{key}", low=minimum)

    health = amount("health", minimum=0.000001)
    armour = amount("armour", minimum=0.0)
    if "armor" in value and "armour" not in value:
        armour = amount("armor", minimum=0.0)
    shield = amount("shield", minimum=0.0)
    health_type = str(value.get("healthType") or "").strip()
    armour_type = str(value.get("armourType") or value.get("armorType") or "").strip()
    shield_type = str(value.get("shieldType") or "").strip()
    base_level = _manual_int(value.get("baseLevel", 0), "defenseSnapshot.baseLevel", high=9999)
    if not health_type:
        raise SimulationError("defenseSnapshot.healthType is required")
    if not armour_type:
        raise SimulationError("defenseSnapshot.armorType is required (use RK_NONE when armor is zero)")
    if not shield_type:
        raise SimulationError("defenseSnapshot.shieldType is required (use RK_NONE when shield is zero)")
    return {
        "path": "__custom_enemy__",
        "name": "Custom defense snapshot",
        "nameZh": "自定义防御快照",
        "nameEn": "Custom defense snapshot",
        "baseLevel": base_level,
        "health": health,
        "shield": shield,
        "armour": armour,
        "healthType": health_type,
        "armourType": armour_type,
        "shieldType": shield_type,
        "factionResistance": str(value.get("factionResistance") or "RK_GRINEER_FACTION"),
        "damageController": "custom",
        "hitProxies": [{"bone": "GAME_C1_HEAD", "damageAtten": 1.0}],
    }


def _manual_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise SimulationError(f"{label} must be a boolean")
    return value


def _manual_enemy_enhancements(
    payload: Mapping[str, Any], *, steel_path: bool
) -> tuple[dict[str, Any], list[str]]:
    """Validate sourced static enemy enhancement switches for the shared reducer."""
    raw = payload.get("enemyEnhancements", payload.get("enhancements"))
    if raw is None:
        return {"eximus": False, "archimedea": False, "empowered": False, "playerCount": None, "magneticStacks": 0}, []
    if not isinstance(raw, Mapping):
        raise SimulationError("enemyEnhancements must be an object")
    allowed = {"eximus", "archimedea", "empowered", "playerCount", "magneticStacks", "steelPath"}
    unknown = sorted(str(key) for key in raw if str(key) not in allowed)
    if unknown:
        raise SimulationError(f"enemyEnhancements contains unsupported keys: {', '.join(unknown)}")
    selected: dict[str, Any] = {}
    for key in ("eximus", "archimedea", "empowered"):
        selected[key] = _manual_bool(raw.get(key, False), f"enemyEnhancements.{key}")
    if "steelPath" in raw:
        nested_steel_path = _manual_bool(raw["steelPath"], "enemyEnhancements.steelPath")
        if nested_steel_path != steel_path:
            raise SimulationError("enemyEnhancements.steelPath must match steelPath")
    player_count = raw.get("playerCount")
    if player_count is None:
        player_count = 1 if selected["empowered"] else None
    else:
        player_count = _manual_int(player_count, "enemyEnhancements.playerCount", low=1, high=4)
    selected["playerCount"] = player_count if selected["empowered"] else None
    selected["magneticStacks"] = _manual_int(raw.get("magneticStacks", 0), "enemyEnhancements.magneticStacks", high=10)
    support = WIKI_ENHANCEMENTS.get("support")
    support = support if isinstance(support, Mapping) else {}
    unsupported = [
        f"enemy-enhancement-{key}-manifest-only"
        for key in ("archimedea", "empowered", "eximus")
        if selected[key] and not support.get(key)
    ]
    if raw.get("steelPath") is True:
        selected["steelPath"] = True
    return selected, sorted(set(unsupported))


def _mix_numeric(left: Any, right: Any, weight: float) -> Any:
    if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        return float(left) * (1.0 - weight) + float(right) * weight
    # One side missing (e.g. a status type only present in the body sim) must
    # scale the surviving side instead of being dropped or kept unscaled.
    if right is None and isinstance(left, (int, float)) and not isinstance(left, bool):
        return float(left) * (1.0 - weight)
    if left is None and isinstance(right, (int, float)) and not isinstance(right, bool):
        return float(right) * weight
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        keys = set(left) | set(right)
        return {key: _mix_numeric(left.get(key), right.get(key), weight) for key in keys}
    if isinstance(left, list) and isinstance(right, list):
        return [_mix_numeric(a, b, weight) for a, b in zip(left, right)] if len(left) == len(right) else left
    return right if weight >= 0.5 else left


def _probability_payload(stats: Mapping[str, Any]) -> dict[str, Any]:
    def number(*keys: str, default: float = 0.0) -> float:
        for key in keys:
            value = stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return default

    multishot = max(number("multishot", default=1.0), 0.0)
    crit = max(number("critChance", "crit_chance"), 0.0)
    m_floor = math.floor(multishot)
    m_frac = multishot - m_floor
    c_floor = math.floor(crit)
    c_frac = crit - c_floor
    shots = [(m_floor, 1.0 - m_frac)]
    if m_frac > 1e-9:
        shots.append((m_floor + 1, m_frac))
    tiers = [(c_floor, 1.0 - c_frac)]
    if c_frac > 1e-9:
        tiers.append((c_floor + 1, c_frac))
    rows = []
    total = max(number("totalDamage", "total_damage"), 0.0)
    falloff = max(number("falloffMultiplier", "falloff_multiplier", default=1.0), 0.0)
    crit_multiplier = max(number("critMultiplier", "crit_multiplier", default=1.0), 1.0)
    noncrit_multiplier = max(number("noncritDamageMultiplier", "noncrit_damage_multiplier", default=1.0), 0.0)
    double_crit = min(max(number("doubleCritChance", "double_crit_chance"), 0.0), 1.0)
    tier_rows: list[tuple[int, float]] = []
    for tier, tier_probability in tiers:
        promotion = double_crit if tier > 0 else 0.0
        tier_rows.append((tier, tier_probability * (1.0 - promotion)))
        if promotion:
            tier_rows.append((tier + 1, tier_probability * promotion))
    for count, shot_probability in shots:
        for tier, crit_probability in tier_rows:
            probability = shot_probability * crit_probability
            hit_multiplier = (
                noncrit_multiplier
                if tier == 0
                else 1.0 + tier * (crit_multiplier - 1.0)
            )
            rows.append({
                "multishot": count,
                "critTier": tier,
                "probability": probability,
                "relativeDamage": hit_multiplier * count,
                "damage": total * falloff * hit_multiplier * count,
            })
    return {
        "multishot": {"value": multishot, "floor": m_floor, "ceil": m_floor + (1 if m_frac else 0)},
        "crit": {"value": crit, "floor": c_floor, "ceil": c_floor + (1 if c_frac else 0)},
        "outcomes": rows,
        "probabilitySum": sum(row["probability"] for row in rows),
    }


def _manual_arcane_trigger_kind(arcane: Mapping[str, Any]) -> str | None:
    trigger = arcane.get("trigger")
    if not isinstance(trigger, Mapping):
        return None
    parts = [str(trigger.get("conditionTag") or "")]
    conditions = trigger.get("conditions")
    if isinstance(conditions, (list, tuple)):
        parts.extend(str(item) for item in conditions)
    text = " ".join(parts).casefold()
    if "headshot" in text:
        return "headshot"
    if "crit" in text:
        return "crit"
    if "onhit" in text or "on_hit" in text:
        return "hit"
    return None


def _manual_arcane_rate(
    kind: str, stats: Mapping[str, Any], headshot_chance: float
) -> float:
    hits = max(float(stats.get("fire_rate") or 0.0), 0.0) * max(
        float(stats.get("multishot") or 1.0), 0.0
    )
    if kind == "crit":
        return hits * min(max(float(stats.get("crit_chance") or 0.0), 0.0), 1.0)
    if kind == "headshot":
        return hits * headshot_chance
    return hits


def _prepare_manual_arcanes(
    raw_arcanes: list[Mapping[str, Any]],
    weapon_record: Mapping[str, Any],
    *,
    event_stats: Mapping[str, Any] | None = None,
    headshot_chance: float = 0.0,
    elapsed: float | None = None,
) -> tuple[Any, list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    """Resolve one manual Arcane state through the optimizer's existing adapter."""
    normalized: list[dict[str, Any]] = []
    inferred: dict[str, float] = {}
    unsupported: list[str] = []
    for index, item in enumerate(raw_arcanes):
        query = str(item.get("path") or item.get("query") or "").strip()
        row = dict(item)
        row["query"] = query
        if "triggerRate" not in row and "stacks" not in row and "uptime" not in row:
            arcane = optimizer.resolve_record(EXPORTS["arcanes"], query, kind="arcane")
            kind = _manual_arcane_trigger_kind(arcane)
            if kind and event_stats is not None:
                rate = _manual_arcane_rate(kind, event_stats, headshot_chance)
                row["triggerRate"] = rate
                inferred[query.casefold()] = rate
            elif kind is None and not arcane.get("effects"):
                unsupported.append(f"arcane-state-{index}-trigger-rate-required")
        normalized.append(row)

    card, states, adapter_unsupported = optimizer._arcane_card(
        EXPORTS.get("arcanes") or (),
        normalized,
        weapon_record,
        elapsed=elapsed,
    )
    unsupported.extend(adapter_unsupported)
    for state in states:
        rate = inferred.get(str(state.get("query") or "").casefold())
        if rate is not None:
            state["triggerRate"] = rate
            state["triggerSource"] = "derived-from-manual-stats"
    return card, states, sorted(set(unsupported)), normalized


def _manual_passive_effects(card: Any) -> Any:
    if card is None:
        return ()
    return ModEffectList(card.effects, skipped=card.skipped)


def _manual_kitgun_parts(value: Any) -> tuple[str, ...]:
    """Validate optional Kitgun assembly parts (chamber, grip, loader)."""
    if value is None:
        return ()
    if not isinstance(value, list) or not 1 <= len(value) <= 3:
        raise SimulationError("kitgunParts must be an array of 1-3 component paths")
    parts = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise SimulationError(f"kitgunParts[{index}] must be a non-empty path string")
        parts.append(item.strip())
    return tuple(parts)


def _manual_resolve_sim_context(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve the shared simulation context for manual payloads.

    Parses and validates weapon / enemy / scenario / arcanes / incarnon once
    and returns the `common` kwargs plus the resolved passive effects and
    metadata, so callers (simulate / mod-gains variants) can rerun the kernel
    with alternate `mods` without repeating the whole HTTP-layer pipeline.
    """
    weapon_path = payload.get("weapon")
    if not isinstance(weapon_path, str) or weapon_path.strip() not in CATALOG_WEAPONS_BY_PATH:
        raise SimulationError("weapon must be an exported portable weapon path")
    weapon = CATALOG_WEAPONS_BY_PATH[weapon_path.strip()]
    selected_catalog_weapon = _special_slot_override(
        payload, weapon, weapon["weaponType"]
    )
    _selected_catalog_weapon, innate_selection = _innate_element_selection(
        payload, selected_catalog_weapon
    )
    has_kitgun_parts = isinstance(payload.get("kitgunParts"), list) and len(payload["kitgunParts"]) >= 1
    if not weapon["available"] and not has_kitgun_parts:
        raise SimulationError(weapon.get("issue") or "weapon is unavailable")
    damage_model = str(payload.get("damageModel") or "target").strip().casefold()
    if damage_model not in {"panel", "target", "custom"}:
        raise SimulationError("damageModel must be panel, target, or custom")
    enemy_path = payload.get("enemy")
    if isinstance(enemy_path, str) and enemy_path.strip() in MANUAL_ENEMIES_BY_PATH:
        enemy_path = enemy_path.strip()
    elif damage_model == "target":
        raise SimulationError("enemy must be one of the complete offline target records")
    else:
        enemy_path = MANUAL_ENEMIES[0]["path"]
    enemy = MANUAL_ENEMIES_BY_PATH[enemy_path]
    if enemy.get("complete") is False:
        reasons = ", ".join(str(value) for value in enemy.get("unsupported") or ())
        raise SimulationError(
            f"enemy target is unavailable in the frozen damage model{(': ' + reasons) if reasons else ''}"
        )
    # 基准等级无官方记录（default-1 兜底）的目标仍然可以解算，但缩放锚点不可靠，
    # 在诊断里显式标注，与选择器里的「数值缩放缺失」徽标同口径。
    enemy_value_unsupported: list[str] = []
    if (
        damage_model == "target"
        and str((enemy.get("defenseSources") or {}).get("baseLevel") or "") == "default-1"
    ):
        enemy_value_unsupported.append("enemy-base-level-unverified")
    defense_snapshot = None
    if damage_model == "custom":
        defense_snapshot = _custom_enemy_snapshot(
            payload.get("defenseSnapshot") or payload.get("customDefense")
        )
    fire_mode = _manual_int(payload.get("fireMode", 0), "fireMode")
    kitgun_parts = _manual_kitgun_parts(payload.get("kitgunParts"))
    # Kitgun base records carry empty fireModes — the modes come from the
    # chamber after assembly, so the pre-assembly bound check is skipped.
    if not kitgun_parts and fire_mode >= len(weapon.get("fireModes") or ()):
        raise SimulationError("fireMode is outside the weapon fire-mode list")
    raw_mods = payload.get("mods", [])
    if not isinstance(raw_mods, list) or len(raw_mods) > 8:
        raise SimulationError("mods must be an array with at most 8 entries")
    slot_count = _manual_int(
        payload.get("slotCount", DEFAULT_LOADOUT_SLOTS),
        "slotCount",
        low=1,
        high=8,
    )
    if len(raw_mods) > slot_count:
        raise SimulationError(
            f"mods has {len(raw_mods)} entries but slotCount is {slot_count}"
        )
    raw_slot_polarities = payload.get("slotPolarities")
    if raw_slot_polarities is not None:
        if not isinstance(raw_slot_polarities, list):
            raise SimulationError("slotPolarities must be an array when supplied")
        if len(raw_slot_polarities) < slot_count or any(
            value is not None and (not isinstance(value, str) or not value.strip())
            for value in raw_slot_polarities[:slot_count]
        ):
            raise SimulationError(
                "slotPolarities must contain one polarity token (or null) per selected slot"
            )
        slot_polarities = raw_slot_polarities
    else:
        slot_polarities = None
    mods = _manual_normalize_mods(raw_mods, slot_count)
    level = _manual_int(payload.get("level", 160), "level")
    armour_strip = _manual_number(payload.get("armourStrip", 0.0), "armourStrip", low=0.0, high=1.0)
    elemental_strip = _manual_number(payload.get("elementalArmourStrip", 0.0), "elementalArmourStrip", low=0.0, high=1.0)
    steel_path = payload.get("steelPath", False)
    if not isinstance(steel_path, bool):
        raise SimulationError("steelPath must be a boolean")
    enemy_enhancements, _enhancement_unsupported = _manual_enemy_enhancements(
        payload, steel_path=steel_path
    )
    headshot_chance = _manual_number(payload.get("headshotChance", 0.0), "headshotChance", low=0.0, high=1.0)
    if headshot_chance and not enemy.get("hasHeadProxy"):
        raise SimulationError("headshotChance requires an enemy with a verified head proxy")
    scenario_raw = payload.get("scenario") if isinstance(payload.get("scenario"), Mapping) else {}
    if "conditionalStacks" in payload or "conditionalStacks" in scenario_raw:
        raise SimulationError("conditionalStacks is derived from equipped MODs and cannot be overridden")
    scenario = Scenario(
        aiming=_manual_bool(scenario_raw.get("aiming", payload.get("aiming", False)), "aiming"),
        heavy_attack=_manual_bool(scenario_raw.get("heavyAttack", payload.get("heavyAttack", False)), "heavyAttack"),
        combo_tier=_manual_int(scenario_raw.get("comboTier", payload.get("comboTier", 0)), "comboTier", high=11),
        victim_status_count=0,
        conditional_stacks={},
        distance=_manual_number(scenario_raw["distance"], "distance", low=0.0) if scenario_raw.get("distance") is not None else None,
        cloaked=_manual_bool(scenario_raw.get("cloaked", False), "cloaked"),
        nearest_enemy_distance=_manual_number(scenario_raw["nearestEnemyDistance"], "nearestEnemyDistance", low=0.0) if scenario_raw.get("nearestEnemyDistance") is not None else None,
    )
    weapon_record = optimizer.resolve_record(EXPORTS["weapons"], weapon_path.strip(), kind="weapon")
    weapon_record = _special_slot_override(payload, weapon_record, weapon["weaponType"])
    # Kitgun bases have no fire modes of their own; the engine assembles the
    # chamber's modes from kitgun_parts, so mode selection is deferred.
    selected_weapon = weapon_record
    if not kitgun_parts:
        selected_weapon, _ = optimizer._select_fire_mode(
            weapon_record, fire_mode, weapon_type=weapon["weaponType"]
        )
    selected_weapon = _special_slot_override(payload, selected_weapon, weapon["weaponType"])
    if weapon.get("isExalted"):
        selected_weapon = {**selected_weapon, "isExalted": True}
    # Zaw 架势跟随组装后的武器类别（剑刃 + 握把决定），基体自身没有架势兼容标签，
    # 因此这里用组装后的记录解析架势；内核仍通过 kitgun_parts 自行组装。
    stance_source = selected_weapon
    if kitgun_parts and weapon["weaponType"] in {"melee", "zaw"}:
        zaw_rules = EXPORTS.get("zaws") or {}
        zaw_strike_paths = zaw_rules.get("strikes") or {}
        if any(
            str(part).strip().replace("\\", "/").rstrip("/") in zaw_strike_paths
            for part in kitgun_parts
        ):
            stance_source = resolve_zaw_record(weapon_record, kitgun_parts, zaw_rules)
    stance = _resolve_stance(
        stance_source, weapon["weaponType"], payload.get("stancePath")
    )
    stance_multiplier = float((stance or {}).get("dpsMultiplier") or 1.0)
    status_rate_multiplier = float((stance or {}).get("statusRateMultiplier") or 1.0)
    capacity_limit = DEFAULT_CAPACITY_LIMIT + int((stance or {}).get("capacityGain") or 0)
    exilus_raw = payload.get("exilus")
    exilus = None
    exilus_mod = None
    if exilus_raw is not None:
        if not isinstance(exilus_raw, Mapping):
            raise SimulationError("exilus must be an object when supplied")
        exilus_path = exilus_raw.get("path") or exilus_raw.get("query")
        if not isinstance(exilus_path, str) or exilus_path not in UTILITY_MODS_BY_PATH:
            raise SimulationError("exilus must use a supported utility MOD path")
        utility = UTILITY_MODS_BY_PATH[exilus_path]
        if not _utility_matches_weapon(utility, selected_weapon, weapon):
            raise SimulationError("exilus is not compatible with the selected weapon")
        max_rank = int(utility.get("rank") if utility.get("rank") is not None else utility.get("maxRank") or 0)
        exilus_rank = _manual_int(exilus_raw.get("rank", max_rank), "exilus.rank", high=max_rank)
        raw_drain = int(utility.get("drain") or 0) - max_rank + exilus_rank
        exilus_slot_polarity = _special_slot_polarities(
            selected_weapon, weapon["weaponType"]
        )["exilus"]
        exilus_drain, exilus_relation = _polarity_adjusted_drain(
            raw_drain, utility.get("polarity"), exilus_slot_polarity
        )
        exilus = {
            **utility,
            "rank": exilus_rank,
            "drain": exilus_drain,
            "slotPolarity": exilus_slot_polarity,
            "polarityRelation": exilus_relation,
        }
        if utility.get("catalogJoined"):
            exilus_mod = {"path": exilus_path, "rank": exilus_rank, "slot": slot_count}
    metric = str(payload.get("metric") or (
        "attackDps" if weapon["weaponType"] in {"melee", "zaw"} else "sustainedDps"
    ))
    incarnon_card, _choices, _incarnon_unsupported, _policy = optimizer._incarnon_card(
        selected_weapon,
        payload.get("incarnonChoices"),
        scenario=scenario,
        metric=optimizer._objective_metric(metric),
        policy=EXPORTS.get("incarnonDefaults"),
        build_label=EXPORTS["buildLabel"],
    )
    forced_procs = payload.get("forcedProcs", {})
    if not isinstance(forced_procs, Mapping):
        raise SimulationError("forcedProcs must be an object")
    forced = {str(key): _manual_number(value, f"forcedProcs[{key}]", low=0.0) for key, value in forced_procs.items()}
    raw_arcanes = payload.get("arcanes", [])
    if not isinstance(raw_arcanes, list) or len(raw_arcanes) > 3:
        raise SimulationError("arcanes must be an array with at most 3 entries")
    validated_arcanes: list[dict[str, Any]] = []
    arcane_counts = Counter()
    seen_arcanes: set[str] = set()
    for index, item in enumerate(raw_arcanes):
        if not isinstance(item, Mapping):
            raise SimulationError(f"arcanes[{index}] must be an object")
        query = item.get("path") or item.get("query")
        if not isinstance(query, str) or query.strip() not in MANUAL_ARCANES_BY_PATH:
            raise SimulationError("arcanes must use a supported offline Arcane path")
        path = query.strip()
        if path in seen_arcanes:
            raise SimulationError("the same Arcane cannot occupy more than one slot")
        seen_arcanes.add(path)
        arcane_meta = MANUAL_ARCANES_BY_PATH[path]
        slot_kind = str(arcane_meta.get("slotKind") or "weapon")
        arcane_counts[slot_kind] += 1
        if arcane_counts["weapon"] > 1 or arcane_counts["warframe"] > 2:
            raise SimulationError("arcanes allow at most 1 weapon and 2 warframe entries")
        arcane_record = optimizer.resolve_record(EXPORTS["arcanes"], path, kind="arcane")
        if not optimizer._arcane_matches_weapon(arcane_record, selected_weapon):
            raise SimulationError("Arcane is not compatible with the selected weapon")
        max_rank = arcane_meta.get("maxRank")
        rank = _manual_int(item.get("rank", max_rank or 0), f"arcanes[{index}].rank")
        if isinstance(max_rank, int) and rank > max_rank:
            raise SimulationError(f"arcanes[{index}].rank exceeds maxRank {max_rank}")
        if "triggerRate" in item:
            raise SimulationError("Arcane triggerRate is derived and cannot be overridden")
        arcane_row: dict[str, Any] = {"path": path, "rank": rank}
        # 武器页赋能开关（强制触发 / 限定层数）以手动 stacks/uptime 透传给引擎；
        # 未携带时保持现状，由 _prepare_manual_arcanes 按面板推导触发期望。
        stacks_override = item.get("stacks")
        if stacks_override is not None:
            if (
                isinstance(stacks_override, bool)
                or not isinstance(stacks_override, int)
                or stacks_override < 0
            ):
                raise SimulationError(f"arcanes[{index}].stacks must be a non-negative integer")
            trigger_meta = arcane_meta.get("trigger") if isinstance(arcane_meta.get("trigger"), Mapping) else {}
            stack_cap = trigger_meta.get("maxStacks")
            stack_cap = stack_cap if isinstance(stack_cap, int) and stack_cap > 0 else 1
            arcane_row["stacks"] = min(stacks_override, stack_cap)
        uptime_override = item.get("uptime")
        if uptime_override is not None:
            if (
                isinstance(uptime_override, bool)
                or not isinstance(uptime_override, (int, float))
                or not math.isfinite(float(uptime_override))
                or not 0 <= float(uptime_override) <= 1
            ):
                raise SimulationError(f"arcanes[{index}].uptime must be a number between 0 and 1")
            arcane_row["uptime"] = float(uptime_override)
        validated_arcanes.append(arcane_row)

    kernel_mods = [*mods, *([exilus_mod] if exilus_mod else [])]
    kernel_slot_count = slot_count + int(exilus_mod is not None)
    kernel_slot_polarities = slot_polarities
    if exilus_mod is not None:
        ordinary_polarities = list(slot_polarities) if slot_polarities is not None else list(selected_weapon.get("polarities") or ())[:slot_count]
        kernel_slot_polarities = [
            *ordinary_polarities[:slot_count],
            _special_slot_polarities(selected_weapon, weapon["weaponType"])["exilus"],
        ]

    common = {
        "export_dir": EXPORT_DIR,
        "weapon": weapon_path.strip(),
        "kitgun_parts": kitgun_parts,
        "enemy": enemy_path.strip(),
        "mods": kernel_mods,
        "fire_mode": fire_mode,
        "scenario": scenario,
        "level": level,
        "armour_strip": armour_strip,
        "elemental_armour_strip": elemental_strip,
        "steel_path": steel_path,
        "enemy_enhancements": enemy_enhancements,
        "forced_procs": forced,
        "status_rate_multiplier": status_rate_multiplier,
        "damage_rate_multiplier": stance_multiplier,
        "validate_loadout_slots": True,
        "slot_count": kernel_slot_count,
        "capacity_limit": capacity_limit,
        "slot_polarities": kernel_slot_polarities,
    }
    weapon_override: dict[str, Any] = {}
    if innate_selection is not None:
        weapon_override["innateElements"] = [innate_selection]
    if isinstance(payload.get("specialSlotPolarities"), Mapping) and payload.get("specialSlotPolarities"):
        weapon_override["polarities"] = list(selected_weapon.get("polarities") or ())
    if weapon_override:
        common["weapon_override"] = weapon_override
    if defense_snapshot is not None:
        common["enemy_override"] = defense_snapshot

    def build_passives(event_stats: Mapping[str, Any] | None, skip_riven: bool = False):
        needs = any(
            "triggerRate" not in item
            and "stacks" not in item
            and "uptime" not in item
            and _manual_arcane_trigger_kind(
                optimizer.resolve_record(EXPORTS["arcanes"], item["path"], kind="arcane")
            )
            for item in validated_arcanes
        )
        resolved_event_stats = event_stats
        if needs and resolved_event_stats is None:
            with ANALYZE_LOCK:
                resolved_event_stats = simulate(**common, hit_location="body")["moddedStats"]
        arcane_card, states, arc_unsupported, normalized = _prepare_manual_arcanes(
            validated_arcanes,
            weapon_record,
            event_stats=resolved_event_stats,
            headshot_chance=headshot_chance,
        )
        passives = _manual_passive_effects(optimizer._merge_passives(incarnon_card, arcane_card))
        riven_stats = payload.get("riven")
        if not skip_riven and isinstance(riven_stats, Mapping) and isinstance(riven_stats.get("stats"), list):
            riven_effects = optimizer.synthetic_riven_effects(riven_stats["stats"])
            passives = ModEffectList([*passives, *riven_effects], skipped=[*list(getattr(passives, "skipped", ())), *list(riven_effects.skipped)])
        external = _external_buff_effects(payload.get("externalBuffs"))
        if external is not None:
            passives = ModEffectList([*passives, *external], skipped=list(getattr(passives, "skipped", ())))
        return {
            "passive_effects": passives,
            "arcane_states": states,
            "arcane_unsupported": arc_unsupported,
            "normalized_arcanes": normalized,
            "event_stats": resolved_event_stats,
        }

    return {
        "common": common,
        "weapon": weapon,
        "weapon_path": weapon_path.strip(),
        "damage_model": damage_model,
        "metric": metric,
        "headshot_chance": headshot_chance,
        "validated_arcanes": validated_arcanes,
        "build_passives": build_passives,
        "raw_mods": raw_mods,
        "slot_count": slot_count,
        "weapon_record": weapon_record,
        "innate_element": innate_selection,
        "incarnon_card": incarnon_card,
        "incarnon_choices": _choices,
        "incarnon_unsupported": _incarnon_unsupported,
        "incarnon_policy": _policy,
        "enemy_enhancements": enemy_enhancements,
        "enhancement_unsupported": _enhancement_unsupported,
        "enemy_value_unsupported": enemy_value_unsupported,
        "stance": stance,
        "stance_multiplier": stance_multiplier,
        "capacity_limit": capacity_limit,
        "exilus": exilus,
        "exilus_unvalidated_drain": exilus["drain"] if exilus and not exilus_mod else 0,
        "mod_states": [
            {
                **(MANUAL_MODS_BY_PATH.get(item.get("path")) or {}),
                "rank": item.get("rank") if item.get("rank") is not None else (MANUAL_MODS_BY_PATH.get(item.get("path")) or {}).get("maxRank", 0),
                **({"slot": item["slot"]} if "slot" in item else {}),
            }
            for item in mods
        ],
    }


def _kill_timeline(
    result: Mapping[str, Any],
    max_seconds: float = 30.0,
    stance: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Conservative hit/combo timeline with reloads and status ramp-up."""
    target_damage = result.get("targetDamage")
    stats = result.get("moddedStats") or {}
    if not isinstance(target_damage, Mapping):
        return None
    per_shot = target_damage.get("perShot")
    fire_rate = stats.get("fireRate") or stats.get("fire_rate")
    if not isinstance(per_shot, (int, float)) or not isinstance(fire_rate, (int, float)) or per_shot <= 0 or fire_rate <= 0:
        return None
    dot_dps = float(result.get("dotSustainedDps") or 0.0)
    status_snapshot = result.get("statusSustained") or {}
    non_dot_dps = float(status_snapshot.get("procNonDotDps") or 0.0)
    status_dps = dot_dps + non_dot_dps
    ramp_seconds = max(float(result.get("statusRampSeconds") or 0.0), 0.0)
    health = target_damage.get("health")
    shield = target_damage.get("shield")
    if not isinstance(health, (int, float)) or health <= 0:
        return None
    shield = shield if isinstance(shield, (int, float)) else 0.0
    overguard = target_damage.get("overguard")
    overguard = overguard if isinstance(overguard, (int, float)) else 0.0
    total_hp = health + shield + overguard

    magazine = stats.get("magazine")
    reload_time = stats.get("reloadTime") or stats.get("reload_time")
    has_cycle = isinstance(magazine, (int, float)) and magazine > 0 and isinstance(reload_time, (int, float)) and reload_time > 0
    combo = (stance or {}).get("bestCombo") if isinstance(stance, Mapping) else None
    combo_duration = (combo or {}).get("duration") if isinstance(combo, Mapping) else None
    combo_multiplier = (combo or {}).get("totalMultiplier") if isinstance(combo, Mapping) else None
    if (
        isinstance(combo_duration, (int, float))
        and combo_duration > 0
        and isinstance(combo_multiplier, (int, float))
        and combo_multiplier > 0
    ):
        interval = float(combo_duration) / float(fire_rate)
        event_damage = float(per_shot) * float(combo_multiplier)
        event_label = "combo"
    else:
        interval = 1.0 / float(fire_rate)
        event_damage = float(per_shot)
        event_label = "attack"
    if has_cycle:
        sustained_rate = float(magazine) / (
            float(magazine) * interval + float(reload_time)
        )
    else:
        sustained_rate = 1.0 / interval
    base_direct_dps = event_damage * sustained_rate
    steady_direct_dps = result.get("steadyDirectDps")
    direct_multiplier = (
        max(float(steady_direct_dps) / base_direct_dps, 0.0)
        if isinstance(steady_direct_dps, (int, float)) and base_direct_dps > 0.0
        else 1.0
    )

    # Exact firing schedule (cumulative time axis, reload gap after each mag).
    schedule: list[float] = [0.0]
    cursor = 0.0
    magazine_int = max(1, int(magazine)) if has_cycle else None
    shot_index = 0
    while cursor <= max_seconds + interval and len(schedule) < 4000:
        cursor += interval
        shot_index += 1
        schedule.append(cursor)
        if has_cycle and shot_index % magazine_int == 0:
            cursor += float(reload_time)

    step = max(interval / 5.0, 0.005)
    points: list[dict[str, Any]] = []
    remaining = total_hp
    killed_at = None
    magnetic_break_applied = False
    magnetic_break_damage = max(float(result.get("magneticBreakPotential") or 0.0), 0.0)
    magnetic_pool = str(status_snapshot.get("activePool") or "")
    magnetic_break_threshold = health + shield if magnetic_pool == "overguard" else health
    shots = 0
    next_shot_time = schedule[0] if schedule else None
    elapsed = -step
    points.append({"time": 0.0, "remaining": round(remaining, 3), "shots": 0, "cumulative": 0.0})
    while elapsed < max_seconds:
        elapsed = round(elapsed + step, 6)
        if elapsed <= 0:
            continue
        progress = min(elapsed / ramp_seconds, 1.0) if ramp_seconds > 0.0 else 1.0
        blast_progress = (
            0.0
            if elapsed < 1.5
            else min((elapsed - 1.5) / max(ramp_seconds - 1.5, step), 1.0)
            if ramp_seconds > 1.5
            else 1.0
        )
        damage = (dot_dps * progress + non_dot_dps * blast_progress) * step
        current_direct_multiplier = 1.0 + (direct_multiplier - 1.0) * progress
        while next_shot_time is not None and next_shot_time <= elapsed:
            if killed_at is not None:
                break
            damage += event_damage * current_direct_multiplier
            shots += 1
            next_shot_time = schedule[shots] if shots < len(schedule) else None
        if killed_at is None:
            remaining -= damage
            if (
                not magnetic_break_applied
                and magnetic_break_damage > 0.0
                and magnetic_pool in {"shield", "overguard"}
                and remaining <= magnetic_break_threshold
            ):
                remaining -= magnetic_break_damage
                magnetic_break_applied = True
            if remaining <= 0:
                killed_at = elapsed
                remaining = 0.0
        points.append({
            "time": round(elapsed, 4),
            "remaining": round(max(remaining, 0.0), 3),
            "shots": shots,
            "cumulative": round(total_hp - max(remaining, 0.0), 3),
        })
        if killed_at is not None and elapsed - killed_at >= max(interval, step * 4):
            break
    return {
        "model": "attack-or-combo-with-reload-and-status-ramp",
        "perShot": round(float(per_shot), 3),
        "eventDamage": round(event_damage, 3),
        "eventLabel": event_label,
        "fireRate": round(float(fire_rate), 3),
        "statusDps": round(status_dps, 3),
        "steadyDirectMultiplier": round(direct_multiplier, 6),
        "statusRampSeconds": round(ramp_seconds, 4),
        "magneticBreakDamage": round(magnetic_break_damage, 3),
        "magneticBreakApplied": magnetic_break_applied,
        "targetHp": round(total_hp, 3),
        "health": round(health, 3),
        "shield": round(shield, 3),
        "overguard": round(overguard, 3),
        "magazine": magazine if has_cycle else None,
        "reloadTime": round(float(reload_time), 3) if has_cycle else None,
        "killTime": round(killed_at, 4) if killed_at is not None else None,
        "shotsToKill": shots if killed_at is not None else None,
        "step": round(step, 4),
        "points": points,
    }


def _manual_normalize_mods(raw_mods: list[Any], slot_count: int) -> list[dict[str, Any]]:
    """Normalize raw mod entries into kernel-ready path/rank/slot dicts."""
    mods: list[dict[str, Any]] = []
    for index, item in enumerate(raw_mods):
        if not isinstance(item, Mapping):
            raise SimulationError(f"mods[{index}] must be an object")
        path = item.get("path") or item.get("query")
        if not isinstance(path, str) or path.strip() not in MANUAL_MODS_BY_PATH:
            raise SimulationError(f"mods[{index}].path is not a supported weapon MOD")
        mod = MANUAL_MODS_BY_PATH[path.strip()]
        rank = item.get("rank")
        if rank is not None:
            rank = _manual_int(rank, f"mods[{index}].rank")
            max_rank = mod.get("maxRank")
            if isinstance(max_rank, int) and rank > max_rank:
                raise SimulationError(f"mods[{index}].rank exceeds maxRank {max_rank}")
        normalized_mod: dict[str, Any] = {"path": path.strip(), "rank": rank}
        if "slot" in item:
            normalized_mod["slot"] = _manual_int(item.get("slot"), f"mods[{index}].slot", high=slot_count - 1)
        if item.get("setPieces") is not None:
            raise SimulationError("setPieces is derived from equipped MODs")
        mods.append(normalized_mod)
    return mods


def simulate_manual_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise SimulationError("request body must be a JSON object")
    ctx = _manual_resolve_sim_context(payload)
    common = dict(ctx["common"])
    weapon = ctx["weapon"]
    damage_model = ctx["damage_model"]
    metric = ctx["metric"]
    headshot_chance = ctx["headshot_chance"]
    raw_mods = ctx["raw_mods"]
    slot_count = ctx["slot_count"]

    passive_pack = ctx["build_passives"](None)
    passive_effects = passive_pack["passive_effects"]
    arcane_states = passive_pack["arcane_states"]
    arcane_unsupported = passive_pack["arcane_unsupported"]
    normalized_arcanes = passive_pack["normalized_arcanes"]
    event_stats = passive_pack["event_stats"]
    incarnon_card = ctx["incarnon_card"]
    incarnon_choices = ctx["incarnon_choices"]
    incarnon_unsupported = ctx["incarnon_unsupported"]
    incarnon_policy = ctx["incarnon_policy"]
    enemy_enhancements = ctx["enemy_enhancements"]
    enhancement_unsupported = ctx["enhancement_unsupported"]
    mod_states = ctx["mod_states"]
    weapon_record = ctx["weapon_record"]
    validated_arcanes = ctx["validated_arcanes"]
    stance = ctx["stance"]
    stance_multiplier = ctx["stance_multiplier"]
    exilus = ctx["exilus"]
    with ANALYZE_LOCK:
        body = simulate(**common, hit_location="body", passive_effects=passive_effects)
        head = (
            simulate(**common, hit_location="head", passive_effects=passive_effects)
            if headshot_chance
            else None
        )
    result = body if not headshot_chance else {**body, "targetDamage": _mix_numeric(body["targetDamage"], head["targetDamage"], headshot_chance), "killMetrics": _mix_numeric(body["killMetrics"], head["killMetrics"], headshot_chance), "statusProcs": _mix_numeric(body["statusProcs"], head["statusProcs"], headshot_chance), "statusDamage": _mix_numeric(body["statusDamage"], head["statusDamage"], headshot_chance), "statusSustained": _mix_numeric(body["statusSustained"], head["statusSustained"], headshot_chance), "dot": _mix_numeric(body["dot"], head["dot"], headshot_chance), "headshotMix": {"chance": headshot_chance, "body": body["targetDamage"], "head": head["targetDamage"]}}
    if damage_model == "panel":
        # The panel model hides target-specific numbers, but the DoT profile is
        # still computed against the reference target — keep it so the status
        # breakdown stays informative (it is labelled in the UI).
        result = {
            **result,
            "targetDamage": None,
            "killMetrics": None,
        }
    # Crit-adjust the DPS fields so panel-model HUD/面板 numbers match the
    # optimizer's crit-weighted convention (kernel returns raw sustained/burst).
    modded_stats = result.get("moddedStats")
    if isinstance(modded_stats, dict):
        crit_factor = effective_hit_multiplier(
            modded_stats.get("critChance"),
            modded_stats.get("critMultiplier"),
            modded_stats.get("noncritDamageMultiplier"),
        )
        for dps_key in ("sustainedDps", "burstDps"):
            if isinstance(modded_stats.get(dps_key), (int, float)):
                modded_stats[dps_key] = modded_stats[dps_key] * crit_factor * stance_multiplier
        modded_stats["stanceMultiplier"] = stance_multiplier
        status_sustained = result.get("statusSustained") or {}
        result["steadyDirectDps"] = float(status_sustained.get("directDps") or 0.0)
        result["dotSustainedDps"] = float(status_sustained.get("dotDps") or 0.0)
        result["nonDotStatusSustainedDps"] = float(status_sustained.get("nonDotDps") or 0.0)
        result["statusSustainedDps"] = float(status_sustained.get("statusDps") or 0.0)
        result["totalSustainedDps"] = float(status_sustained.get("totalDps") or 0.0)
        result["statusRampSeconds"] = float(status_sustained.get("steadyStateSeconds") or 0.0)
        result["magneticBreakPotential"] = float(status_sustained.get("magneticBreakPotential") or 0.0)
    if isinstance(result.get("targetDamage"), dict) and isinstance(result["targetDamage"].get("dps"), (int, float)):
        result["targetDamage"]["dps"] *= stance_multiplier
    kernel_mod_states = {
        str(item.get("path") or ""): item
        for item in result.get("selection", {}).get("mods") or ()
        if isinstance(item, Mapping)
    }
    mod_states = [
        {
            **item,
            **{
                key: kernel_mod_states[str(item.get("path") or "")][key]
                for key in ("setPieces", "displayEffects", "steadyStacks")
                if str(item.get("path") or "") in kernel_mod_states
                and key in kernel_mod_states[str(item.get("path") or "")]
            },
        }
        for item in mod_states
    ]
    result["selection"]["mods"] = mod_states
    result["selection"]["slotCount"] = slot_count
    result["selection"]["arcanes"] = arcane_states
    result["selection"]["stance"] = stance
    result["selection"]["exilus"] = exilus
    result["damageModel"] = damage_model
    if damage_model in {"target", "custom"}:
        kill_timeline = _kill_timeline(result, stance=stance)
        if kill_timeline is not None:
            result["killTimeline"] = kill_timeline
    result["enemyEnhancements"] = enemy_enhancements
    result["probability"] = _probability_payload(result["moddedStats"])
    result["arcanes"] = arcane_states
    result["stance"] = stance
    result["exilus"] = exilus
    result["specialSlotPolarities"] = _special_slot_polarities(
        weapon_record, weapon["weaponType"]
    )
    result["innateElement"] = ctx.get("innate_element")
    result["innateElementCandidates"] = list(weapon.get("innateElementCandidates") or ())
    result["incarnonChoices"] = incarnon_choices
    result["incarnonPolicy"] = incarnon_policy
    result["unsupported"] = sorted(
        set(result.get("unsupported") or ())
        | set(arcane_unsupported)
        | set(incarnon_unsupported)
        | set(enhancement_unsupported)
        | set(ctx.get("enemy_value_unsupported") or ())
    )
    result["diagnostics"] = {
        "unsupported": list(result.get("unsupported") or ()),
        "skipped": list(result.get("skipped") or ()),
        "capacity": result.get("loadoutValidation", {}).get("capacity"),
        "polarity": result.get("loadoutValidation", {}).get("polarity"),
        "enemyEnhancements": enemy_enhancements,
        "wikiEnhancements": {
            "schema": WIKI_ENHANCEMENTS.get("schema"),
            "status": WIKI_ENHANCEMENTS.get("overguard", {}).get("status", "manifest-only") if isinstance(WIKI_ENHANCEMENTS.get("overguard"), Mapping) else "manifest-only",
            "unsupported": list(WIKI_ENHANCEMENTS.get("unsupported") or ()),
        },
    }
    extra_exilus_drain = int(ctx.get("exilus_unvalidated_drain") or 0)
    if extra_exilus_drain:
        validation = result["loadoutValidation"]
        validation["capacity"] = int(validation.get("capacity") or 0) + extra_exilus_drain
        validation["remaining"] = int(validation.get("capacityLimit") or ctx["capacity_limit"]) - validation["capacity"]
        validation["valid"] = validation["remaining"] >= 0
    result["capacity"] = result["loadoutValidation"].get("capacity")
    result["capacityLimit"] = result["loadoutValidation"].get(
        "capacityLimit", DEFAULT_CAPACITY_LIMIT
    )
    if damage_model == "panel":
        result["diagnostics"]["skipped"] = [
            *result["diagnostics"]["skipped"],
            "panel-model-target-defenses-not-applied",
        ]

    timeline_seconds = None
    if normalized_arcanes:
        killed_at = (result.get("killTimeline") or {}).get("killTime")
        timeline_seconds = min(float(killed_at), 30.0) if isinstance(killed_at, (int, float)) and killed_at > 0 else 30.0
    if timeline_seconds is not None:
        if event_stats is None:
            event_stats = body["moddedStats"]
        with ANALYZE_LOCK:
            baseline_snapshot = simulate(
                **common,
                hit_location="body",
                passive_effects=_manual_passive_effects(incarnon_card),
            )
        baseline_dps = float(
            (baseline_snapshot.get("statusSustained") or {}).get("totalDps")
            or baseline_snapshot.get("moddedStats", {}).get("sustained_dps")
            or baseline_snapshot.get("moddedStats", {}).get("sustainedDps")
            or 0.0
        )
        points: list[dict[str, Any]] = []
        for index in range(41):
            elapsed = timeline_seconds * index / 40.0
            timeline_card, timeline_states, timeline_bad, _ = _prepare_manual_arcanes(
                validated_arcanes,
                weapon_record,
                event_stats=event_stats,
                headshot_chance=headshot_chance,
                elapsed=elapsed,
            )
            with ANALYZE_LOCK:
                timeline_passives = optimizer._merge_passives(incarnon_card, timeline_card)
                snapshot = simulate(
                    **common,
                    hit_location="body",
                    passive_effects=_manual_passive_effects(timeline_passives),
                )
            dps = float(
                (snapshot.get("statusSustained") or {}).get("totalDps")
                or snapshot.get("moddedStats", {}).get("sustained_dps")
                or snapshot.get("moddedStats", {}).get("sustainedDps")
                or 0.0
            )
            points.append(
                {
                    "time": elapsed,
                    "expectedDps": dps,
                    "dps": dps,
                    "baselineDps": baseline_dps,
                    "gainPercent": ((dps / baseline_dps - 1.0) * 100.0) if baseline_dps > 0 else 0.0,
                    "expectedStacks": [float(state.get("expectedStacks") or 0.0) for state in timeline_states],
                    "uptime": [float(state.get("expectedUptime") or 0.0) for state in timeline_states],
                    "arcanes": [
                        {
                            "query": state.get("query"),
                            "expectedStacks": state.get("expectedStacks", 0.0),
                            "uptime": state.get("expectedUptime", 0.0),
                        }
                        for state in timeline_states
                    ],
                    "unsupported": list(timeline_bad),
                }
            )
        result["timeline"] = {
            "model": "manual-expected-target-dps",
            "durationSeconds": timeline_seconds,
            "points": points,
            "assumptions": [
                "on-hit/on-crit/on-headshot rates use the selected modded stats",
                "triggerRate uses the exported chance and duration Poisson approximation",
                "target defenses and status ticks are held at each snapshot",
            ],
        }
    return result


def _mod_gains_metric_value(result: Mapping[str, Any], metric: str) -> float:
    stats = result.get("moddedStats") or {}
    target = result.get("targetDamage") or {}
    if metric in {"sustainedDps", "sustained_dps"}:
        value = target.get("dps") or stats.get("sustainedDps") or stats.get("sustained_dps")
    elif metric in {"burstDps", "burst_dps"}:
        value = stats.get("burstDps") or stats.get("burst_dps")
    elif metric in {"attackDps", "attack_dps"}:
        value = target.get("dps") or stats.get("attackDps") or stats.get("attack_dps")
    elif metric in {"heavyAttackDps", "heavy_attack_dps"}:
        value = stats.get("heavyAttackDps") or stats.get("heavy_attack_dps")
    elif metric in {"shotDamage", "perShot"}:
        value = target.get("perShot") or stats.get("shotDamage") or stats.get("averageHit") or stats.get("average_hit")
    elif metric in {"heavyDamage", "heavy_damage"}:
        value = stats.get("heavyDamage") or stats.get("heavy_damage")
    else:
        value = stats.get(metric) or target.get(metric)
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return float(number) if number is not None and math.isfinite(float(number)) else 0.0


_MOD_GAINS_CACHE: dict[str, Any] = {}
_MOD_GAINS_CACHE_LIMIT = 24


def mod_gains_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Per-candidate real simulation gain, relative to the current loadout.

    Accepts the same body as /api/simulate plus:
      candidates: array of mod paths (max 80, capped silently)
      targetSlot: 0-based slot the candidate would occupy
      mode: "candidate" (default) — swap candidate into targetSlot vs baseline;
            "equipped" — drop each listed candidate (already equipped) and
            measure the loss, so the UI can badge equipped cards with their
            real contribution to THIS loadout.
    Returns {path: gainPercent} for each candidate that stays computable.
    """
    if not isinstance(payload, Mapping):
        raise SimulationError("payload must be an object")
    candidates_raw = payload.get("candidates", [])
    if not isinstance(candidates_raw, list) or not candidates_raw:
        raise SimulationError("candidates must be a non-empty array of MOD paths")
    candidates: list[str] = []
    seen: set[str] = set()
    for item in candidates_raw[:80]:
        if not isinstance(item, str):
            continue
        path = item.strip()
        # "__riven__" is the synthetic equipped-Riven candidate in equipped mode.
        if path == "__riven__":
            if path not in seen:
                seen.add(path)
                candidates.append(path)
            continue
        if path not in MANUAL_MODS_BY_PATH:
            continue
        if path not in seen:
            seen.add(path)
            candidates.append(path)
    if not candidates:
        raise SimulationError("candidates contains no supported MOD paths")
    target_slot = _manual_int(payload.get("targetSlot", 0), "targetSlot", low=0, high=7)
    mode = str(payload.get("mode") or "candidate")

    # Session cache: identical (weapon, mods, scenario, candidates, slot, mode)
    # payloads skip re-simulation entirely — the picker re-queries on open and
    # on every category/search change with a mostly stable candidate list.
    cache_key = json.dumps(
        {
            "weapon": payload.get("weapon"),
            "fireMode": payload.get("fireMode"),
            "metric": payload.get("metric"),
            "mods": sorted(
                (
                    {"path": item.get("path"), "rank": item.get("rank"), "slot": item.get("slot")}
                    for item in (payload.get("mods") or [])
                    if isinstance(item, Mapping)
                ),
                key=lambda item: (item.get("slot") is None, item.get("slot"), item.get("path")),
            ),
            "enemy": payload.get("enemy"),
            "level": payload.get("level"),
            "steelPath": payload.get("steelPath"),
            "armourStrip": payload.get("armourStrip"),
            "headshotChance": payload.get("headshotChance"),
            "scenario": payload.get("scenario"),
            "incarnonChoices": payload.get("incarnonChoices"),
            "arcanes": payload.get("arcanes"),
            "targetSlot": target_slot,
            "mode": mode,
            "candidates": sorted(candidates),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    cached = _MOD_GAINS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Resolve the shared simulation context once; every variant then re-runs
    # only the kernel with swapped mods (the pipeline parse, incarnon resolution
    # and arcane event-stat derivation happen a single time).
    probe = dict(payload)
    probe.pop("timelineSeconds", None)
    ctx = _manual_resolve_sim_context(probe)
    common = dict(ctx["common"])
    metric = str(ctx["metric"] or "sustainedDps")
    passive_pack = ctx["build_passives"](None)
    passive_effects = passive_pack["passive_effects"]
    with ANALYZE_LOCK:
        base_kernel = simulate(**common, hit_location="body", passive_effects=passive_effects)
    base_value = _mod_gains_metric_value(base_kernel, metric)

    mods_list = [dict(item) for item in ctx["raw_mods"] if isinstance(item, Mapping)]
    base_riven = payload.get("riven") if isinstance(payload.get("riven"), Mapping) else None
    gains: dict[str, Any] = {}
    for path in candidates:
        variant_passives = passive_effects
        if mode == "equipped":
            variant_mods = [dict(item) for item in mods_list if item.get("path") != path]
            if path == "__riven__":
                # measure the equipped Riven's contribution by removing it
                if base_riven is None:
                    gains[path] = {"gainPercent": None, "reason": "no-riven-equipped"}
                    continue
                variant_passives = ctx["build_passives"](None, skip_riven=True)["passive_effects"]
        else:
            if path == "__riven__":
                gains[path] = {"gainPercent": None, "reason": "riven-candidate-not-supported-in-swap-mode"}
                continue
            variant_mods = []
            replaced = False
            for item in mods_list:
                slot = item.get("slot")
                if slot == target_slot:
                    variant_mods.append({"path": path, "slot": target_slot, "rank": MANUAL_MODS_BY_PATH[path].get("maxRank") or 0})
                    replaced = True
                else:
                    variant_mods.append(dict(item))
            if not replaced:
                variant_mods.append({"path": path, "slot": target_slot, "rank": MANUAL_MODS_BY_PATH[path].get("maxRank") or 0})
        try:
            normalized = _manual_normalize_mods(variant_mods, ctx["slot_count"])
        except (SimulationError, TypeError, ValueError):
            gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
            continue
        variant_common = {**common, "mods": normalized}
        try:
            with ANALYZE_LOCK:
                variant_result = simulate(**variant_common, hit_location="body", passive_effects=variant_passives)
            value = _mod_gains_metric_value(variant_result, metric)
        except (SimulationError, TypeError, ValueError):
            gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
            continue
        if mode == "equipped":
            # contribution of the equipped card = how much removing it costs
            if base_value > 0:
                gain = (value / base_value - 1.0) * 100.0
            else:
                gain = 0.0 if value <= 0 else 100.0
        else:
            gain = ((value / base_value - 1.0) * 100.0) if base_value > 0 else (0.0 if value <= 0 else 100.0)
        gains[path] = {
            "gainPercent": round(gain, 2),
            "value": round(value, 3),
            "baseValue": round(base_value, 3),
            "metric": metric,
        }
    result = {
        "buildLabel": EXPORTS.get("buildLabel"),
        "metric": metric,
        "mode": mode,
        "targetSlot": target_slot,
        "baseValue": round(base_value, 3),
        "gains": gains,
    }
    if len(_MOD_GAINS_CACHE) >= _MOD_GAINS_CACHE_LIMIT:
        _MOD_GAINS_CACHE.pop(next(iter(_MOD_GAINS_CACHE)))
    _MOD_GAINS_CACHE[cache_key] = result
    return result


class PortableHandler(BaseHTTPRequestHandler):
    server_version = "Warframe-Weapon-Loadout-Build/2"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/health":
            self._send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "buildLabel": CATALOG["buildLabel"],
                    "schemaVersion": CATALOG["schemaVersion"],
                },
            )
            return
        if path == "/api/catalog":
            self._send_json(HTTPStatus.OK, CATALOG, cache="no-cache")
            return
        if path == "/api/warframe/catalog":
            self._send_json(HTTPStatus.OK, WARFRAME_CATALOG, cache="no-cache")
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        analyzers = {
            "/api/analyze": analyze_payload,
            "/api/build": build_weapon_payload,
            "/api/simulate": simulate_manual_payload,
            "/api/mod-gains": mod_gains_payload,
            "/api/warframe/calculate": WARFRAME_ENGINE.calculate,
        }
        analyze = analyzers.get(path)
        if analyze is None:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "endpoint not found")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_length", "invalid Content-Length")
            return
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._send_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "request_too_large",
                f"JSON body must be between 1 and {MAX_REQUEST_BYTES} bytes",
            )
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, "invalid_json", str(exc))
            return
        try:
            result = analyze(payload)
        except SimulationError as exc:
            extra = {"candidates": exc.candidates} if exc.candidates else None
            self._send_error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_request",
                str(exc),
                extra,
            )
            return
        except (TypeError, ValueError) as exc:
            self._send_error(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "invalid_request",
                str(exc),
            )
            return
        except Exception:
            traceback.print_exc()
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "internal_error",
                "analysis failed unexpectedly",
            )
            return
        self._send_json(HTTPStatus.OK, result, cache="no-store")

    def _serve_static(self, request_path: str) -> None:
        static_root = FRONTEND_DIR
        if request_path == "/":
            relative = Path("index.html")
        elif request_path in {"/app.css", "/app.js"}:
            relative = Path(request_path.removeprefix("/"))
        elif request_path.startswith("/assets/"):
            relative = Path(unquote(request_path.removeprefix("/")))
        elif request_path in {
            "/docs/README.md", "/docs/README.en.md", "/docs/LICENSE", "/docs/THIRD_PARTY_NOTICES.md",
        }:
            static_root = ROOT
            relative = Path(request_path.removeprefix("/docs/"))
        else:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
            return

        frontend_root = static_root.resolve()
        target = (static_root / relative).resolve()
        try:
            target.relative_to(frontend_root)
        except ValueError:
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
            return
        if not target.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "not_found", "resource not found")
            return
        try:
            body = target.read_bytes()
        except OSError:
            self._send_error(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "static_read_failed",
                "resource could not be read",
            )
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if static_root == ROOT:
            content_type = "text/plain"
        if content_type.startswith("text/") or content_type in {
            "application/javascript",
            "application/json",
            "image/svg+xml",
        }:
            content_type += "; charset=utf-8"
        # 静态素材一律 no-cache + Last-Modified 协商：本地工具素材经常被重烘焙替换，
        # 之前 assets 用 max-age=3600 且无验证器，改动后浏览器继续用旧缓存（mod 框体
        # 马赛克事故）。no-cache 让每次加载都问一句，未变则 304，流量开销可忽略。
        mtime = target.stat().st_mtime
        ims = self.headers.get("If-Modified-Since")
        if ims:
            try:
                from email.utils import parsedate_to_datetime

                if parsedate_to_datetime(ims).timestamp() >= int(mtime):
                    self.send_response(HTTPStatus.NOT_MODIFIED)
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    return
            except (TypeError, ValueError, OverflowError):
                pass
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Last-Modified", self.date_time_string(mtime))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(
        self,
        status: HTTPStatus,
        code: str,
        message: str,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if extra:
            error.update(extra)
        self._send_json(status, {"error": error}, cache="no-store")

    def _send_json(
        self,
        status: HTTPStatus,
        payload: Any,
        *,
        cache: str = "no-store",
    ) -> None:
        body = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), PortableHandler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Warframe loadout build server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port must be between 0 and 65535")

    try:
        server = create_server(args.host, args.port)
    except OSError as exc:
        print(f"Cannot start server on {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"Warframe & Weapon Loadout Build is running at {url}")
    print(f"Documentation: {url}docs/README.md")
    print(f"License: {url}docs/LICENSE | Notices: {url}docs/THIRD_PARTY_NOTICES.md")
    if not args.no_browser:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
