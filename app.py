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
import time
import traceback
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from data_sources import active_build, dataset_root, load_source_lock

ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / "vendor"
SOURCE_LOCK = load_source_lock(ROOT)
DATASET_ROOT = dataset_root(ROOT, SOURCE_LOCK)
EXPORT_DIR = DATASET_ROOT / "data" / "export" / active_build(ROOT, SOURCE_LOCK)
ENEMY_OVERRIDE_PATH = EXPORT_DIR / "enemy_overrides.json"
INCARNON_STRINGS_PATH = EXPORT_DIR / "incarnon_strings.json"
STANCE_DATA_PATH = DATASET_ROOT / "data" / "stances.json"
UTILITY_MOD_DATA_PATH = DATASET_ROOT / "data" / "utility_mods.json"
EXALTED_WEAPON_DATA_PATH = DATASET_ROOT / "data" / "exalted_weapons.json"
WEAPON_MECHANICS_OVERRIDE_PATH = ROOT / "data" / "weapon_mechanics_overrides.json"
WARFRAME_DATA_PATH = DATASET_ROOT / "data" / "warframe_build_data.json"
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


def _load_weapon_mechanics_overrides() -> dict[str, Any]:
    try:
        payload = json.loads(WEAPON_MECHANICS_OVERRIDE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": 1, "mods": {}, "weapons": {}}
    if not isinstance(payload, Mapping):
        return {"schemaVersion": 1, "mods": {}, "weapons": {}}
    return {
        "schemaVersion": payload.get("schemaVersion", 1),
        "buildLabel": payload.get("buildLabel"),
        "mods": dict(payload.get("mods") or {}),
        "weapons": dict(payload.get("weapons") or {}),
    }


WEAPON_MECHANICS_OVERRIDES = _load_weapon_mechanics_overrides()


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


# ---------------------------------------------------------------------------
# 冻结导出快照的运行时数据修正。
# 导出管道需要原始游戏包才能重跑；以下已知数据异常（缺失的 fireRate、
# 暗黑分合剑的双形态面板）在加载后直接补丁，避免整条数据管道重算。
# ---------------------------------------------------------------------------

# 蓄力触发但导出里 fireRate 缺失（state 行为未带 fireRate 字段）的武器：
# 兜底为游戏内攻速（兰卡 1.0/s——导出唯一缺失该字段的蓄力武器）。
_CHARGE_FIRE_RATE_FIXUPS: dict[str, float] = {
    "/Lotus/Weapons/ClanTech/Energy/Railgun": 1.0,  # Lanka 兰卡
}


def _patch_export_weapons(exports: dict[str, Any]) -> None:
    for weapon in exports.get("weapons") or ():
        if not isinstance(weapon, dict):
            continue
        path = str(weapon.get("path") or "")
        for mode in weapon.get("fireModes") or ():
            if not isinstance(mode, dict):
                continue
            trigger = str(mode.get("trigger") or "")
            fire_rate = mode.get("fireRate")
            raw = mode.get("fireRateRaw")
            missing = (fire_rate is None or not isinstance(fire_rate, (int, float)) or isinstance(fire_rate, bool) or fire_rate <= 0) and (
                raw is None or not isinstance(raw, (int, float)) or isinstance(raw, bool) or raw <= 0
            )
            if not missing or "Charge" not in trigger:
                continue
            fixed = _CHARGE_FIRE_RATE_FIXUPS.get(path)
            if fixed is None:
                continue
            mode["fireRate"] = fixed
            mode["fireRateRaw"] = round(fixed * 60.0, 3)


_patch_export_weapons(EXPORTS)


# ---------------------------------------------------------------------------
# 暗黑分合剑（Dark Split-Sword）：唯一随架势切换武器类别的特殊武器。
# 冻结导出只给出基体（fireModes 为空 → 一直灰置）。按 wiki 实测面板拆成
# 「巨刃形态」与「双剑形态」两条独立记录：架势兼容标签按形态限定，倾向
# 沿用基体（1.30），面板取自 wiki（2026-08 知识快照）。
# ---------------------------------------------------------------------------
_DARK_SPLIT_SWORD_PATH = "/Lotus/Weapons/Tenno/Melee/Swords/DarkSword/DarkSwordDaggerHybridWeapon"

# (形态后缀, 中文名, 架势标签, 伤害构成, 攻速, 暴击率, 暴伤, 触发率)
_DARK_SPLIT_FORMS: list[tuple[str, str, str, dict[str, float], float, float, float, float]] = [
    (
        "HeavyBlade",
        "暗黑分合剑 · 巨刃形态",
        "HEAVY_BLADE_STANCE",
        {"DT_PUNCTURE": 78.0, "DT_SLASH": 52.0, "DT_RADIATION": 100.0},
        0.917,
        0.15,
        2.0,
        0.25,
    ),
    (
        "DualSwords",
        "暗黑分合剑 · 双剑形态",
        "DUAL_SWORDS_STANCE",
        {"DT_PUNCTURE": 56.0, "DT_SLASH": 28.0, "DT_RADIATION": 32.0},
        1.17,
        0.25,
        2.5,
        0.15,
    ),
]


def _dark_split_forms(base: dict[str, Any]) -> list[dict[str, Any]]:
    forms: list[dict[str, Any]] = []
    total_damage_base = float(base.get("omegaAttenuation") or 1.3)
    for suffix, name_zh, stance_tag, types, fire_rate, crit, crit_mult, proc in _DARK_SPLIT_FORMS:
        total = sum(types.values())
        path = f"{_DARK_SPLIT_SWORD_PATH}#{suffix}"
        # 普通近战武器的祖先链（普通近战 MOD 的 compatibility 都锚在这几层）；
        # 基体导出的族谱只含 HybridWeapon 根，不带 PlayerMeleeWeapon 链。
        ancestry = [
            path,
            _DARK_SPLIT_SWORD_PATH,
            "/Lotus/Weapons/Tenno/Melee/PlayerMeleeWeapon",
            "/Lotus/Types/Game/LotusMeleeWeapon",
        ]
        form = {
            **{k: v for k, v in base.items() if k not in ("fireModes", "compatTags", "name", "nameZh", "nameEn", "nameInternal", "nameTag", "ancestry")},
            "path": path,
            "ancestry": ancestry,
            "name": f"DarkSwordDaggerHybridWeapon{suffix}",
            "nameInternal": f"DarkSwordDaggerHybridWeapon{suffix}",
            "nameZh": name_zh,
            "nameEn": f"Dark Split-Sword ({suffix})",
            # 紫卡倾向沿用基体；族谱锚回基体路径，倾向继承逻辑仍按 1.30 生效。
            "omegaAttenuation": total_damage_base,
            "compatTags": [stance_tag],
            "fireModes": [
                {
                    "ammoCost": 0,
                    "ammoType": "",
                    "chargeTime": None,
                    "damage": {
                        "critChance": crit,
                        "critMultiplier": crit_mult,
                        "procChance": proc,
                        "shares": {key: value / total for key, value in types.items()},
                        "total": total,
                        "types": dict(types),
                    },
                    "falloffMinDamage": 1,
                    "falloffRange": [0, 0],
                    "fireRate": fire_rate,
                    "fireRateRaw": round(fire_rate * 60.0, 3),
                    "index": 0,
                    "isAlternateFire": False,
                    "multishot": 1,
                    "reloadTime": 1,
                    "trigger": "",
                }
            ],
        }
        forms.append(form)
    return forms


def _patch_dark_split_sword(exports: dict[str, Any]) -> None:
    weapons = exports.get("weapons")
    if not isinstance(weapons, list):
        return
    base = next(
        (
            row
            for row in weapons
            if isinstance(row, dict) and str(row.get("path") or "") == _DARK_SPLIT_SWORD_PATH
        ),
        None,
    )
    if base is None or base.get("fireModes"):
        # 基体缺失（导出剔除）或未来导出已自带形态数据时无需补丁。
        return
    # 基体保留在导出里供紫卡倾向/家族识别，但形态记录才是可用武器。
    for form in _dark_split_forms(base):
        weapons.append(form)


_patch_dark_split_sword(EXPORTS)
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


# ---------------------------------------------------------------------------
# 功能槽（Exilus）武器 MOD 补全：冻结的 utility_mods.json 只收录游戏包里
# 显式带 IsUtility=1 标记的卡，Prime 版本与部分变体（导出标记缺失）不在其中。
# 以下路径全部存在于便携导出（可装备、效果已建模），按导出记录补进功能槽。
# ---------------------------------------------------------------------------
_UTILITY_MOD_FIXUP_PATHS: tuple[str, ...] = (
    # 步枪（主要武器）功能槽
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponRecoilReductionModExpert",          # 稳定 Prime
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponPunctureDepthModExpert",            # 弹头导引 Prime
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponRifleConvertAmmoModExpert",         # 步枪弹药转换 Prime
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponSnipersConvertAmmoModExpert",       # 狙击枪弹药转换 Prime
    "/Lotus/Upgrades/Mods/Rifle/WeaponPunctureDepthMod",                         # 弹头导引
    "/Lotus/Upgrades/Mods/Rifle/WeaponZoomFovMod",                               # 鹰眼
    # 手枪（次要武器）功能槽
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponRecoilReductionModExpert",         # 稳定枪手 Prime
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolConvertAmmoModExpert",       # 手枪弹药转换 Prime
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPunctureDepthModExpert",           # 弹头导引 Prime
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolZoomFovModExpert",           # 隼目 Prime
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponPistolConvertAmmoModIntermediate",  # 手枪弹药转换
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponPistolZoomFovModIntermediate",      # 隼目
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponRecoilReductionModIntermediate",    # 稳定枪手
    "/Lotus/Upgrades/Mods/Pistol/Event/AmbulasEvent/Expert/SecondaryExplosionRadiusModExpert",  # 猛烈爆发 Prime
    "/Lotus/Upgrades/Mods/Pistol/Event/AmbulasEvent/SecondaryExplosionRadiusMod",  # 猛烈爆发
    "/Lotus/Upgrades/Mods/Pistol/Event/AkstilettoEfficiencyWhileAirborneMod",    # 无尽弹雨
    "/Lotus/Upgrades/Mods/Pistol/WeaponPunctureDepthMod",                        # 弹头导引
    "/Lotus/Upgrades/Mods/Pistol/WeaponPistolZoomFovMod",                        # 隼目
    # 霰弹枪（主要武器）功能槽
    "/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponShotgunConvertAmmoModExpert",     # 霰弹枪弹药转换 Prime
    "/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponPunctureDepthModExpert",          # 穿透力 Prime
    "/Lotus/Upgrades/Mods/Shotgun/Intermediate/WeaponShotgunConvertAmmoModIntermediate",   # 霰弹枪弹药转换
    "/Lotus/Upgrades/Mods/Shotgun/Beginner/WeaponPunctureDepthModBeginner",      # 穿透力
    "/Lotus/Upgrades/Mods/Shotgun/WeaponPunctureDepthMod",                       # 穿透力
    "/Lotus/Upgrades/Mods/Shotgun/WeaponProjectileSpeedSPMod",                   # 镀层 致死加速
    # 近战功能槽
    "/Lotus/Upgrades/Mods/Sets/Raptor/RaptorModC",                               # 跃动 冲击
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteOffenseMod",            # 私法 进攻
)

# 资源索引（frontend/assets/mods/index.json）：补丁卡的卡面美术在导出里没有
# icon 字段，按路径从资源索引解析（Prime 版本与普通版共用同一张卡面）。
_MOD_ART_INDEX: dict[str, str] = {}
try:
    _mod_art_payload = json.loads(
        (ROOT / "frontend" / "assets" / "mods" / "index.json").read_text(encoding="utf-8-sig")
    )
    for _path, _entry in (_mod_art_payload.get("mods") or {}).items():
        if isinstance(_entry, Mapping) and _entry.get("art"):
            _MOD_ART_INDEX[str(_path)] = str(_entry["art"])
except (OSError, UnicodeError, json.JSONDecodeError):
    _MOD_ART_INDEX = {}

# 补丁卡的游戏内官方卡面路径（从本地 2D 素材包拷入 frontend/assets/mods/art/；
# Prime 版与普通版共用同一张官方卡面）。文件不存在时自动跳过。
_UTILITY_FIXUP_ICONS: dict[str, str] = {
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponRecoilReductionModExpert": "/Lotus/Interface/Cards/Images/Rifle/RifleRecoilReductionMod.png",
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponPunctureDepthModExpert": "/Lotus/Interface/Cards/Images/Rifle/RiflePunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Rifle/WeaponPunctureDepthMod": "/Lotus/Interface/Cards/Images/Rifle/RiflePunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Rifle/WeaponZoomFovMod": "/Lotus/Interface/Cards/Images/Rifle/RifleZoomMod.png",
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponRifleConvertAmmoModExpert": "/Lotus/Interface/Cards/Images/Rifle/RifleAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Rifle/Expert/WeaponSnipersConvertAmmoModExpert": "/Lotus/Interface/Cards/Images/Rifle/SniperAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponRecoilReductionModExpert": "/Lotus/Interface/Cards/Images/Pistol/PistolRecoilReductionMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponRecoilReductionModIntermediate": "/Lotus/Interface/Cards/Images/Pistol/PistolRecoilReductionMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPunctureDepthModExpert": "/Lotus/Interface/Cards/Images/Pistol/PistolPunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Pistol/WeaponPunctureDepthMod": "/Lotus/Interface/Cards/Images/Pistol/PistolPunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolZoomFovModExpert": "/Lotus/Interface/Cards/Images/Pistol/PistolZoomMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponPistolZoomFovModIntermediate": "/Lotus/Interface/Cards/Images/Pistol/PistolZoomMod.png",
    "/Lotus/Upgrades/Mods/Pistol/WeaponPistolZoomFovMod": "/Lotus/Interface/Cards/Images/Pistol/PistolZoomMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponPistolConvertAmmoModExpert": "/Lotus/Interface/Cards/Images/Pistol/PistolAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Intermediate/WeaponPistolConvertAmmoModIntermediate": "/Lotus/Interface/Cards/Images/Pistol/PistolAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Event/AkstilettoEfficiencyWhileAirborneMod": "/Lotus/Interface/Cards/Images/Pistol/PistolAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Event/AmbulasEvent/Expert/SecondaryExplosionRadiusModExpert": "/Lotus/Interface/Cards/Images/Unique/SecondaryFirestormMod.png",
    "/Lotus/Upgrades/Mods/Pistol/Event/AmbulasEvent/SecondaryExplosionRadiusMod": "/Lotus/Interface/Cards/Images/Unique/SecondaryFirestormMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponShotgunConvertAmmoModExpert": "/Lotus/Interface/Cards/Images/Shotgun/ShotgunAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/Intermediate/WeaponShotgunConvertAmmoModIntermediate": "/Lotus/Interface/Cards/Images/Shotgun/ShotgunAmmoMutatorMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/Expert/WeaponPunctureDepthModExpert": "/Lotus/Interface/Cards/Images/Shotgun/ShotgunPunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/Beginner/WeaponPunctureDepthModBeginner": "/Lotus/Interface/Cards/Images/Shotgun/ShotgunPunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/WeaponPunctureDepthMod": "/Lotus/Interface/Cards/Images/Shotgun/ShotgunPunctureDepthMod.png",
    "/Lotus/Upgrades/Mods/Shotgun/WeaponProjectileSpeedSPMod": "/Lotus/Interface/Cards/Images/Shotgun/Galvanized/WeaponProjectileSpeedSPMod.png",
    "/Lotus/Upgrades/Mods/Sets/Raptor/RaptorModC": "/Lotus/Interface/Cards/Images/Parkour/ImpactParkourTwoMod.png",
    "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteOffenseMod": "/Lotus/Interface/Cards/Images/Sets/Vigilante/VigilanteOffense.png",
}


def _resolve_fixup_icon_asset(path: str) -> str | None:
    """Resolve the card art for one fixup mod (art index, then explicit icon map)."""
    art = _MOD_ART_INDEX.get(path)
    if art:
        return art
    icon = _UTILITY_FIXUP_ICONS.get(path)
    if not icon:
        return None
    asset = "/assets/mods/art/" + icon.lstrip("/")
    if (ROOT / "frontend" / "assets" / "mods" / "art" / icon.lstrip("/")).is_file():
        return asset
    return None

# 通用效果类型 → 中文标签（用于补丁卡的逐级描述生成，与 modEffectLabel 同口径）。
_UTILITY_EFFECT_LABELS = {
    "WEAPON_RECOIL": "后坐力",
    "WEAPON_PUNCTURE_DEPTH": "穿透力",
    "WEAPON_CONVERT_AMMO": "弹药转换",
    "WEAPON_ZOOM": "变焦",
    "WEAPON_EXPLOSION_RADIUS": "爆炸范围",
    "WEAPON_PROJECTILE_SPEED": "弹速",
    "WEAPON_AMMO_CONSUME_RATE": "弹药消耗",
    "WEAPON_RANGE": "攻击范围",
    "WEAPON_AMMO_MAX": "弹药上限",
    "WEAPON_CLIP_MAX": "弹匣容量",
}


def _utility_effect_lines_by_rank(mod: Mapping[str, Any]) -> list[list[str]] | None:
    """从导出效果生成逐级中文描述（rank R = valuePerRank × (R+1)）。"""
    effects = [e for e in (mod.get("effects") or ()) if isinstance(e, Mapping)]
    lines: list[list[str]] | None = None
    for effect in effects:
        upgrade = str(effect.get("upgradeType") or "")
        label = _UTILITY_EFFECT_LABELS.get(upgrade)
        if not label:
            continue
        per_rank = effect.get("valuePerRank")
        if not isinstance(per_rank, (int, float)) or isinstance(per_rank, bool):
            continue
        value = float(per_rank)
        max_rank = int(mod.get("maxRank") or 0)
        per_level = [value * (rank + 1) for rank in range(max_rank + 1)]
        if lines is None:
            lines = [[] for _ in per_level]
        for rank, amount in enumerate(per_level):
            text = (
                f"{amount:+.1%} {label}".replace(".0%", "%")
                if abs(amount) <= 10
                else f"{amount:+.1f} {label}"
            )
            lines[rank].append(text)
    return lines


def _slot_kind_from_mod_path(path: str, compatibility: str = "") -> str | None:
    # compatibility（基类引用）优先：套装卡在 /Mods/Sets/ 下但分属不同槽位，
    # 基类锚点才是权威口径（PlayerMeleeWeapon=近战、LotusLongGun=主武器…）。
    compat = str(compatibility or "").rstrip("/").casefold()
    if compat.endswith("playermeleeweapon"):
        return "melee"
    if compat.endswith(("lotuslonggun", "lotusshotgun", "lotusbow")):
        return "primary"
    if compat.endswith(("lotuspistol", "lotusshortgun")):
        return "secondary"
    parts = [p for p in path.split("/") if p]
    if "EmpoweredHeavyMelee" in parts:
        return "melee"
    try:
        family = parts[parts.index("Mods") + 1]
    except (ValueError, IndexError):
        return None
    if family == "Melee":
        return "melee"
    if family in {"Rifle", "Shotgun"}:
        return "primary"
    if family == "Pistol":
        return "secondary"
    return None


def _patch_utility_mod_rows() -> None:
    export_by_path = {
        str(row.get("path") or ""): row
        for row in EXPORTS.get("mods") or ()
        if isinstance(row, Mapping) and row.get("path")
    }
    for path in _UTILITY_MOD_FIXUP_PATHS:
        if path in UTILITY_MOD_BY_PATH:
            continue
        mod = export_by_path.get(path)
        if mod is None or mod.get("selectable") is not True:
            continue
        slot_kind = _slot_kind_from_mod_path(
            path, str(mod.get("compatibility") or "")
        )
        if slot_kind is None:
            continue
        rank = int(mod.get("maxRank") or 0)
        base_drain = int(mod.get("baseDrain") or 0)
        # 卡面：导出记录缺 icon 字段——资源索引/官方卡面映射按路径解析
        # （Prime 与普通版共用同一张官方卡面）。
        icon_asset = _resolve_fixup_icon_asset(path)
        if not icon_asset and mod.get("icon"):
            icon_asset = f"/assets/mods/art/{str(mod.get('icon') or '').lstrip('/')}"
        # 描述：逐级效果行按 valuePerRank × (R+1) 生成；满级行做静态描述。
        by_rank = _utility_effect_lines_by_rank(mod)
        description = "；".join(by_rank[-1]) if by_rank else str(mod.get("description") or "")
        row = {
            "path": path,
            "nameEn": str(mod.get("nameEn") or ""),
            "nameZh": str(mod.get("nameZh") or ""),
            "slotKind": slot_kind,
            "exilus": True,
            "polarity": mod.get("polarity"),
            "rarity": str(mod.get("rarity") or "COMMON"),
            "description": description,
            "effectsZh": by_rank[-1] if by_rank else None,
            "effectsZhByRank": by_rank,
            "effects": list(mod.get("effects") or ()),
            "conditionalEffects": list(mod.get("conditionalEffects") or ()),
            "drain": max(0, base_drain + rank),
            "rank": rank,
            "icon": str(mod.get("icon") or ""),
            "iconAsset": icon_asset,
            "sourceKind": "export-fixup",
            "catalogJoined": True,
        }
        UTILITY_MOD_ROWS.append(row)
        UTILITY_MOD_BY_PATH[path] = row
    UTILITY_MOD_PATHS.clear()
    UTILITY_MOD_PATHS.update(UTILITY_MOD_BY_PATH)


_patch_utility_mod_rows()

# 紫卡分析静态结果缓存（基准配装/双路推荐/理论上限，按武器+开火模式 keyed）。
# 推荐候选恒为理论满数值口径，不随单张紫卡变化；底层数据（导出快照或架势
# 表）变动时整个文件作废重算。缓存格式升级时递增版本号即可全量失效。
ANALYSIS_STATICS_CACHE_PATH = ROOT / ".local" / "cache" / "riven-analysis-statics.json"
if getattr(sys, "frozen", False):
    ANALYSIS_STATICS_CACHE_PATH = (
        Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        / "Warframe-Weapon-Loadout-Build" / "cache" / "riven-analysis-statics.json"
    )
ANALYSIS_STATICS_CACHE_VERSION = 8


def _stances_fingerprint() -> str:
    try:
        return hashlib.sha1(STANCE_DATA_PATH.read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def _analysis_inputs_fingerprint() -> str:
    digest = hashlib.sha1()
    digest.update(
        str(
            SOURCE_LOCK.get("snapshotId")
            or SOURCE_LOCK.get("snapshotRoot")
            or SOURCE_LOCK.get("activeBuild")
            or "legacy"
        ).encode("utf-8")
    )
    # A baked optimizer result depends on the reducer and every input that can
    # change target damage, not only on the two catalog files used to build the
    # candidate pool.  Keep this list explicit so a local engine/data patch
    # invalidates old statics instead of silently serving stale recommendations.
    # ── F13（审计修复）：
    #  - app.py 自身负责运行时武器/敌人补丁、目标参数与分析入口行为
    #    （_load_enemy_overrides / analyze_payload 的 benchmarkTarget 默认值），
    #    它变更时缓存必须失效，不能当成无关展示层。
    #  - combat_events.py 目前主要影响诊断，但其输出的事件版本
    #    （eventModel/directEventLedger）与校准记录已依赖它；一旦升级为
    #    权威事件源更不能遗漏。
    engine_paths = (
        EXPORT_DIR / "weapons.json",
        EXPORT_DIR / "mods.json",
        EXPORT_DIR / "enemies.json",
        EXPORT_DIR / "enemy_overrides.json",
        EXPORT_DIR / "riven_templates.json",
        EXPORT_DIR / "incarnon_defaults.json",
        ROOT / "data" / "source-lock.json",
        # The mechanics override sidecar currently feeds only the manual
        # simulation/audit path (fail-closed diagnostics); it is not consumed
        # by the static optimizer candidate set yet, so changing its notes
        # must not invalidate an otherwise identical baked static cache.
        STANCE_DATA_PATH,
        Path(optimizer.__file__),
        Path(optimizer.__file__).with_name("damage.py"),
        Path(optimizer.__file__).with_name("simulator.py"),
        Path(optimizer.__file__).with_name("projectile_events.py"),
        Path(optimizer.__file__).with_name("runtime_adapters.py"),
        Path(optimizer.__file__).with_name("combat_events.py"),
        Path(__file__),  # app.py — 运行时补丁与分析入口语义
    )
    for path in engine_paths:
        try:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        except OSError:
            # F13：文件读取失败不得回退成空指纹——空指纹会与「另一个同样
            # 读不到文件的进程」碰撞，让两份语义不同的缓存互相命中。缺失
            # 依赖必须让缓存不可用：抛出由调用方决定加载空缓存。
            raise SimulationError(
                f"analysis input dependency unreadable: {path}"
            ) from None
    return digest.hexdigest()[:16]


def _load_analysis_statics_cache() -> dict[str, Any]:
    try:
        payload = json.loads(ANALYSIS_STATICS_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    try:
        inputs_fingerprint = _analysis_inputs_fingerprint()
    except SimulationError:
        # F13：依赖缺失 → 缓存整体不可用（加载空表），不把空指纹当正常版本。
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("buildLabel") != EXPORTS.get("buildLabel")
        or payload.get("stances") != _stances_fingerprint()
        or payload.get("inputs") != inputs_fingerprint
        or payload.get("cacheVersion") != ANALYSIS_STATICS_CACHE_VERSION
    ):
        return {}
    entries = payload.get("entries")
    return dict(entries) if isinstance(entries, dict) else {}


ANALYSIS_STATICS_CACHE: dict[str, Any] = _load_analysis_statics_cache()


def _persist_analysis_statics_cache() -> None:
    """缓存有新条目时落盘（原子替换，避免中断写坏）。

    F14（审计修复）：持久化现在受 `_ANALYSIS_STATICS_PERSISTENCE` 开关控制。
    烘焙 worker 通过 ``_disable_analysis_statics_persistence()`` 上下文把
    共享主缓存的写路径整体关闭——worker 进程内的 ``analyze_payload()`` 不再
    能间接把条目写进共享缓存文件（旧行为：worker 调用
    ``app.analyze_payload`` → ``_persist_analysis_statics_cache()`` 无条件
    落盘，绕过了「只写分片」的注释承诺）。只有父进程在显式合并阶段重新
    打开持久化，单次写入主缓存。
    """
    if not ANALYSIS_STATICS_PERSISTENCE.enabled:
        return
    if not ANALYSIS_STATICS_CACHE.pop("__dirty__", None):
        return
    try:
        inputs_fingerprint = _analysis_inputs_fingerprint()
    except SimulationError:
        # 依赖缺失时既不能读旧缓存也不能写入新缓存：放弃本次持久化，
        # 下次启动（依赖恢复后）自然整体失效重算。
        return
    payload = {
        "buildLabel": EXPORTS.get("buildLabel"),
        "stances": _stances_fingerprint(),
        "inputs": inputs_fingerprint,
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


class _AnalysisStaticsPersistence:
    """进程内开关：共享主缓存持久化是否可用（F14）。

    默认开启（正常请求路径行为不变）。烘焙 worker 在进程入口处进入
    ``_disable_analysis_statics_persistence()`` 上下文，此后该进程内所有
    ``_persist_analysis_statics_cache()`` 调用都是 no-op。这不是线程锁——
    worker 是独立进程，开关生命周期与进程一致。
    """

    def __init__(self) -> None:
        self.enabled = True

    def __enter__(self) -> "_AnalysisStaticsPersistence":
        self.enabled = False
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.enabled = True


ANALYSIS_STATICS_PERSISTENCE = _AnalysisStaticsPersistence()


def _disable_analysis_statics_persistence() -> _AnalysisStaticsPersistence:
    """Disable the shared persistence guard (F14) and return it.

    This flips the PROCESS-WIDE ``ANALYSIS_STATICS_PERSISTENCE`` flag off and
    returns that same object, so every ``_persist_analysis_statics_cache()``
    call in this process becomes a no-op.  Bake workers call this once at
    process start::

        guard = app._disable_analysis_statics_persistence()
        ... run all app.analyze_payload() calls ...
        # nothing is persisted by this process

    The parent process never calls this; it performs the single merge write.
    """
    ANALYSIS_STATICS_PERSISTENCE.enabled = False
    return ANALYSIS_STATICS_PERSISTENCE


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

# ── 分析进度注册表（前端进度条数据源）───────────────────────────────────
# 长分析（deep 档 1-3 分钟）期间前端轮询 /api/analyze/progress?id=<token>
# 读取阶段心跳，区分「还在跑」与「卡死」。注册表条目在完成后保留 10 分钟
# 供迟到查询，随后惰性清理。
_ANALYZE_STAGES = ("baseline", "calibration", "actual", "recommendation", "quality", "payload")
_ANALYZE_PROGRESS: dict[str, dict[str, Any]] = {}
_ANALYZE_PROGRESS_LOCK = threading.Lock()
_ANALYZE_PROGRESS_TTL = 600.0


def _progress_token_for(payload: Mapping[str, Any]) -> str | None:
    """请求声明的进度令牌（前端生成，随 payload 传入）。"""
    token = payload.get("progressToken")
    if isinstance(token, str) and 1 <= len(token) <= 64:
        return token
    return None


def _report_analysis_progress(token: str, stage: str) -> None:
    now = time.time()
    with _ANALYZE_PROGRESS_LOCK:
        entry = _ANALYZE_PROGRESS.get(token)
        if entry is None:
            return
        stages = list(entry.get("stages") or [])
        if stage not in stages:
            stages.append(stage)
        entry["stages"] = stages
        entry["stageIndex"] = _ANALYZE_STAGES.index(stage) + 1 if stage in _ANALYZE_STAGES else len(stages)
        entry["lastBeat"] = now


def _begin_analysis_progress(token: str) -> None:
    now = time.time()
    with _ANALYZE_PROGRESS_LOCK:
        # 惰性清理过期条目。
        expired = [
            key for key, row in _ANALYZE_PROGRESS.items()
            if row.get("done") and now - float(row.get("finishedAt") or 0) > _ANALYZE_PROGRESS_TTL
        ]
        for key in expired:
            _ANALYZE_PROGRESS.pop(key, None)
        _ANALYZE_PROGRESS[token] = {
            "stages": [],
            "stageIndex": 0,
            "startedAt": now,
            "lastBeat": now,
            "done": False,
            "error": None,
        }


def _finish_analysis_progress(token: str, error: str | None = None) -> None:
    with _ANALYZE_PROGRESS_LOCK:
        entry = _ANALYZE_PROGRESS.get(token)
        if entry is None:
            return
        entry["done"] = True
        entry["error"] = error
        entry["finishedAt"] = time.time()


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


def _riven_code_label(code: str) -> str:
    """词条码的中文标签（融合配方 hover 用；未知码回退码本身）。"""
    rule = RIVEN_RULES.get(code)
    return str(rule[0]) if rule else code


def _fusion_stat_codes(weapon_type: str) -> frozenset[str]:
    """该武器类型的融合词条码集合（riven_templates.fusionRecipes 的
    result 集合）。融合词条仅正面、每卡限 1 条——分析入口用它做
    fail-closed 校验。"""
    templates = EXPORTS.get("rivenTemplates")
    recipes = (
        templates.get("fusionRecipes")
        if isinstance(templates, Mapping)
        else None
    ) or []
    return frozenset(
        str(recipe.get("result"))
        for recipe in recipes
        if isinstance(recipe, Mapping)
        and str(recipe.get("weaponType") or "") == weapon_type
        and recipe.get("result")
    )


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
    # ── 灵化 SubUpgrade（条件性子词条）描述渲染 ────────────────────────
    # 主进化的 SubUpgrades 子词条（装填叠层/弹药效率等）带条件元数据；
    # 渲染时标注触发条件，避免与无条件主词条混淆（螺钉 2-2 描述错误
    # 的根源：子词条此前未导出，描述只剩主词条一半）。
    sub_prefix = ""
    if effect.get("isSubUpgrade"):
        chance = effect.get("UpgradeChance")
        duration = effect.get("UpgradeDuration")
        stacks = effect.get("MaxConditionalStacks")
        gate_bits = []
        if isinstance(chance, (int, float)) and not isinstance(chance, bool):
            gate_bits.append(f"{float(chance) * 100:g}% 几率")
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            gate_bits.append(f"{float(duration):g}s")
        if isinstance(stacks, (int, float)) and not isinstance(stacks, bool):
            gate_bits.append(f"最多 {stacks:g} 层")
        sub_prefix = f"[条件{'，'.join(gate_bits)}] " if gate_bits else "[条件] "
    # 以引擎当前支持表为准（冻结快照的 supported 标记滞后于引擎实现）。
    support = "" if upgrade in SUPPORTED_WEAPON_UPGRADE_TYPES else "（当前不计入）"
    if effect.get("isSubUpgrade"):
        support = "（条件触发，当前不计入）"
    return f"{sub_prefix}{label} {operation}{value_text}{support}".strip()


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
    # ── 无收益不选（2026-09-24 用户反馈）─────────────────────────────────
    # 工具池大量卡没有已建模词条（NONE 占位/空 effects）——全员与基准
    # 持平时，旧实现靠平局兜底选一张（观感=「随机选的没用卡」）。改为：
    # 最优选择的分数必须严格高于基准（容差 1e-9）才装备；否则留空。
    if score <= evaluation.score + 1e-9:
        return evaluation, None
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
        # 空战武器（地面口径，arch_gun）2026-09-24 起进入配装目录（单开
        # 分类「Archwing」）；紫卡分析仍只覆盖 primary/secondary/melee。
        if slot not in RIVEN_SLOTS and slot != "arch_gun":
            continue
        # 暗黑分合剑基体已被两个形态记录取代（巨刃/双剑），基体不再出现在
        # 任何选择器里——它自身没有开火模式，永远灰置只会造成困惑。
        if str(weapon.get("path") or "") == _DARK_SPLIT_SWORD_PATH:
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
    # ── 融合配方（词条融合 Advanced Traits，2026.09.22）──────────────────
    # riven_templates.json 的 fusionRecipes: [{weaponType, result, primary,
    # secondary, ...}]。目录构建时为每个武器类型建立 result->recipe 的
    # 查找表，前端词条渲染用它在金框 hover 中显示合成路径。
    _fusion_recipes = (
        (EXPORTS.get("rivenTemplates") or {}).get("fusionRecipes")
        if isinstance(EXPORTS.get("rivenTemplates"), Mapping)
        else None
    ) or []
    _recipes_by_type: dict[str, dict[str, Any]] = {}
    for recipe in _fusion_recipes:
        if not isinstance(recipe, Mapping):
            continue
        wtype = str(recipe.get("weaponType") or "")
        result = str(recipe.get("result") or "")
        if wtype and result and result not in _recipes_by_type.setdefault(wtype, {}):
            _recipes_by_type[wtype][result] = recipe
    for weapon_type, base_values in RIVEN_BASE_VALUES.items():
        rows = []
        # 该类型可融合获得的词条（有配方的类型才有融合词条；无配方类型
        # 的融合码从下拉里整体剔除——既不能洗出也不能融合）。
        type_fusable = _recipes_by_type.get(weapon_type) or {}
        for code in base_values:
            rule = RIVEN_RULES.get(code)
            if rule is None:
                continue
            if code in optimizer._FUSION_LINE_CODES and code not in type_fusable:
                continue
            label, upgrade_type, _, _, _, unit, _, can_positive, can_negative = rule
            recipe = type_fusable.get(code)
            rows.append(
                {
                    "code": code,
                    "label": label,
                    "baseValue": base_values[code],
                    "unit": unit,
                    "canPositive": can_positive,
                    "canNegative": can_negative,
                    "objectiveSupported": upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES,
                    # 融合词条元数据（有配方的词条只能通过融合获得）。
                    **(
                        {
                            "isFusion": True,
                            "fusionRecipe": {
                                "primary": recipe.get("primary"),
                                "primaryLabel": _riven_code_label(
                                    str(recipe.get("primary") or "")
                                ),
                                "secondary": recipe.get("secondary"),
                                "secondaryLabel": _riven_code_label(
                                    str(recipe.get("secondary") or "")
                                ),
                            },
                        }
                        if recipe is not None
                        else {}
                    ),
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
        # 天生超宏已有数值（wiki 补丁）且 > 0 时不再是缺口——引擎按等级曲线
        # 缩放；只有 hasOverguard 标记而无数值（数据缺失）才保持 unsupported。
        innate_overguard = enemy.get("overguard")
        has_numeric_overguard = (
            isinstance(innate_overguard, (int, float))
            and not isinstance(innate_overguard, bool)
            and float(innate_overguard) > 0
        )
        if (enemy.get("overguard") or enemy.get("hasOverguard")) and not has_numeric_overguard:
            unsupported.add("enemy-overguard")
            row_note_overguard = "missing-value"
        elif has_numeric_overguard:
            row_note_overguard = "innate-scaled"
        else:
            row_note_overguard = None
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
        if row_note_overguard:
            # 选择器展示用：天生超宏（已按等级缩放）或数值缺失。
            row["overguardNote"] = row_note_overguard
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
            # A small number of PvE augments live under the historical PvPMods
            # namespace.  Keep only explicitly audited mechanic overrides in
            # the picker; their simulation remains fail-closed until an event
            # ledger implementation exists.
            if path not in WEAPON_MECHANICS_OVERRIDES.get("mods", {}):
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
        # 冻结快照的 supported 标记滞后于引擎（首发伤害、弱点家族词条都
        # 属于此类）——以引擎当前支持表为准做准入判断，展示层再按
        # _refresh_effect_support 动态覆写标记。
        effects = mod.get("effects") or []
        def _effect_supported(effect: Any) -> bool:
            if not isinstance(effect, Mapping):
                return False
            if effect.get("supported") is True:
                return "weapon" in (effect.get("supportedBy") or ()) or not effect.get("supportedBy")
            # stale marker: the engine's current support table is authoritative.
            return str(effect.get("upgradeType") or "").upper() in SUPPORTED_WEAPON_UPGRADE_TYPES
        has_supported_effect = any(_effect_supported(effect) for effect in effects)
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
        mechanic_override = WEAPON_MECHANICS_OVERRIDES.get("mods", {}).get(path)
        if (
            not support.get("weapon")
            and not has_supported_effect
            and not fixed_melee_range
            and not first_shot_chamber
            and not mechanic_override
        ):
            continue
        if (
            mod.get("supported") is False
            and not has_supported_effect
            and not fixed_melee_range
            and not first_shot_chamber
            and not mechanic_override
        ):
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
            "mechanicOverride": mechanic_override,
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


def _arcane_effect_summary(
    arcane: Mapping[str, Any], rank: int | None = None
) -> str:
    """Human-readable effect line for the arcane picker.

    ``rank`` scales the value line to a specific rank (default: max rank).
    """
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
    max_rank = arcane.get("maxRank")
    max_rank_int = int(max_rank) if isinstance(max_rank, int) and max_rank >= 0 else 0
    # Rank R carries (R + 1) steps of valuePerRank (rank 0 = one step).
    steps = (
        max(0, min(int(rank), max_rank_int)) + 1
        if isinstance(rank, int)
        else (max_rank_int + 1 if max_rank_int >= 0 else 1)
    )
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
            factor = rank_scale * steps
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
        max_rank = arcane.get("maxRank")
        max_rank_int = int(max_rank) if isinstance(max_rank, int) and max_rank >= 0 else 0
        # 逐级效果行：赋能槽位等级步进时前端直接取对应行展示，
        # 与解算使用的 rank 保持同一口径（rank R = R+1 步 valuePerRank）。
        effects_by_rank: list[list[str]] = []
        for rank in range(max_rank_int + 1):
            line = _arcane_effect_summary(arcane, rank)
            effects_by_rank.append([line] if line else [])
        rows.append({
            "path": str(arcane.get("path")),
            "nameZh": str(arcane.get("nameZh") or arcane.get("nameEn") or ""),
            "nameEn": str(arcane.get("nameEn") or arcane.get("name") or ""),
            "maxRank": max_rank,
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
            "effectsZhByRank": effects_by_rank,
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


# 标准解算靶（用户指定的统一口径）：170 级钢铁之路、卓越者（超宏护盾）、
# 凶魂百夫长（Duviri 派系——不属于任何有派系增伤卡的派系，无特殊护盾，
# 仅弱虚空伤害而武器不可携带虚空），0 削甲 0 爯头，30 秒窗口按击杀数（KPM）
# 排序配卡。分析页与配装页的自动求解都用这套基准。
_BENCHMARK_ENEMY_PATH = "/Lotus/Types/Enemies/Duviri/Avatars/DuviriMeleeAvatar"
_BENCHMARK_LEVEL = 170
_BENCHMARK_WINDOW_SECONDS = 30.0


def _benchmark_target_context(stance_multiplier: float = 1.0, status_rate_multiplier: float = 1.0) -> dict[str, Any]:
    enemy = MANUAL_ENEMIES_BY_PATH.get(_BENCHMARK_ENEMY_PATH)
    if enemy is None:
        return {}
    return {
        "target": enemy,
        "level": _BENCHMARK_LEVEL,
        "armour_strip": 0.0,
        "elemental_armour_strip": 0.0,
        "steel_path": True,
        "enemy_enhancements": {"eximus": True},
        "hit_location": "body",
        "windowSeconds": _BENCHMARK_WINDOW_SECONDS,
        "stanceMultiplier": stance_multiplier,
        "statusRateMultiplier": status_rate_multiplier,
    }


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
    # ── 融合词条规则（游戏规则，2026-09-24 用户确认）────────────────────
    # 融合词条（Advanced Traits）仅正面、每卡限 1 条。fail-closed 校验：
    # 负面融合词条直接拒绝；正面融合词条超过 1 条直接拒绝。
    # 类型可用性：本 build 融合配方只对部分武器类型发布（rifle 有 18 条
    # MergeOptions；pistol/shotgun/archgun/melee 为空/缺失）——无配方类型
    # 的融合词条不可能获得，直接拒绝。
    _fusion_codes = _fusion_stat_codes(weapon["weaponType"])
    fusion_lines = [
        s for s in raw_stats
        if str(s.get("code") or "").strip().upper() in _fusion_codes
    ]
    for stat in fusion_lines:
        if stat.get("negative") is True:
            raise SimulationError(
                f"融合词条 {stat.get('code')} 不能作为负面词条（仅正面）"
            )
    if len(fusion_lines) > 1:
        raise SimulationError(
            f"融合词条每卡限 1 条（当前 {len(fusion_lines)} 条）"
        )
    for stat in raw_stats:
        _code = str(stat.get("code") or "").strip().upper()
        if _code in optimizer._FUSION_LINE_CODES and _code not in _fusion_codes:
            raise SimulationError(
                f"融合词条 {_code} 对 {weapon['weaponType']} 类型不可用"
                "（该类型本版本没有融合配方）"
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
        "profile": _solve_profile(request.get("profile")),
    }
    # A Kuva/Tenet/Coda weapon receives a deterministic default progenitor
    # element when the user did not choose one.  Mark that narrow case so the
    # static analyzer may bake it; explicit element/value selections remain
    # request-specific and continue to bypass the shared cache.
    if (
        innate_selection is not None
        and not assembly_ready
        and request.get("innateElement") in (None, "")
        and request.get("progenitorElement") in (None, "")
        and request.get("innateElementValue") in (None, "")
        and request.get("progenitorBonus") in (None, "")
    ):
        engine_request["_cacheDefaultInnate"] = True
    engine_request.pop("sourceWeapon", None)
    engine_request.pop("sourceDisposition", None)
    engine_request.pop("kitgunParts", None)
    engine_request.pop("progressToken", None)  # HTTP 进度令牌不进引擎层
    # 标准配装靶（用户指定）：170 级钢铁之路、卓越者（超宏护盾）、凶魂百夫长，
    # 0 削甲 0 爆头，30 秒窗口击杀数（KPM）为优化目标。该目标不属于任何有
    # 派系增伤加成的派系、无特殊护盾，仅弱虚空伤害（武器不可携带）——
    # 目标中立且数值可靠，适合作为默认解算口径。
    if not isinstance(engine_request.get("benchmarkTarget"), Mapping):
        engine_request["benchmarkTarget"] = {
            "enemy": _BENCHMARK_ENEMY_PATH,
            "level": 170,
            "steelPath": True,
            "eximus": True,
            "windowSeconds": 30.0,
            "armourStrip": 0.0,
            "headshotChance": 0.0,
        }
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
    # 进度令牌：前端在 payload 里声明 progressToken 时注册进度心跳，
    # analyze_riven_request 的阶段边界回调更新注册表，前端轮询读取。
    progress_token = _progress_token_for(payload)
    if progress_token is not None:
        _begin_analysis_progress(progress_token)

    def _stage_hook(stage: str) -> None:
        if progress_token is not None:
            _report_analysis_progress(progress_token, stage)

    try:
        with ANALYZE_LOCK:
            result = optimizer.analyze_riven_request(
                EXPORT_DIR,
                engine_request,
                weapon_record=analysis_record if innate_selection is not None else assembled_record,
                stance=analysis_stance,
                statics_cache=ANALYSIS_STATICS_CACHE,
                progress_hook=_stage_hook,
            )
            _persist_analysis_statics_cache()
    except BaseException as exc:
        if progress_token is not None:
            _finish_analysis_progress(progress_token, str(exc) or type(exc).__name__)
        raise
    if progress_token is not None:
        _finish_analysis_progress(progress_token)
    result.pop("projection", None)
    weapon_mechanics = WEAPON_MECHANICS_OVERRIDES.get("weapons", {}).get(
        str((result.get("weapon") or {}).get("path") or weapon.get("path") or "")
    )
    if isinstance(weapon_mechanics, Mapping):
        # Sidecar metadata is descriptive and fail-closed: it explains which
        # direct/radial/field part is absent without inventing a compensation
        # multiplier or changing the cached score behind the optimizer's back.
        result["weaponMechanics"] = dict(weapon_mechanics)
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
        # CO emergent 回放所需：面板预乘的 CO 因子与假定层数。
        "statusConditionDamageMultiplier": stats.status_condition_damage_multiplier,
        "coAssumedCount": getattr(stats, "co_assumed_count", 0.0),
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


def build_weapon_payload(
    payload: Any, *, return_engine_context: bool = False
) -> dict[str, Any]:
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

    # 灵化循环口径开关（2026-09-24 用户口径分离）：
    #   incarnonCycle=true  — 真实循环（池耗尽回基础形态充能再灵化；
    #                         导出无充能时长，用基础形态装填时长保守折算）。
    #   缺省/false          — 常驻灵化（170 充能池近似零装填；紫卡分析
    #                         维持此口径）。
    incarnon_cycle_flag = payload.get("incarnonCycle") is True
    scenario = optimizer._scenario(metric, incarnon_cycle=incarnon_cycle_flag)
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
            # 派系增伤卡（净化/灭亡/驱逐 XX）按指定目标的派系弱点定向加成——
            # 配装页维持目标中立口径，禁止优化器选入（与分析页同规则）。
            and str(card.record.get("path") or "") not in FACTION_DAMAGE_MOD_PATHS
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
    # 解算档位（与紫卡分析共用）：fast/standard/deep，标准档为默认。
    profile = _solve_profile(payload.get("profile"))
    # ── 搜索约束（wfsim 优化器 scope 模型）────────────────────────────
    # requiredMods/forbiddenMods（mod path 数组）与 minFill/maxFill。
    def _mod_paths(value: Any, label: str) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise SimulationError(f"{label} must be an array of non-empty MOD paths")
        paths = [item.strip() for item in value]
        unknown = [p for p in paths if p not in MANUAL_MODS_BY_PATH]
        if unknown:
            raise SimulationError(
                f"{label} contains unsupported MOD paths: " + ", ".join(unknown[:5])
            )
        return paths

    required_mod_paths = _mod_paths(payload.get("requiredMods"), "requiredMods")
    forbidden_mod_paths = _mod_paths(payload.get("forbiddenMods"), "forbiddenMods")
    both = set(required_mod_paths) & set(forbidden_mod_paths)
    if both:
        raise SimulationError(
            "mods cannot be both required and forbidden: " + ", ".join(sorted(both))
        )

    def _fill(value: Any, label: str) -> int | None:
        if value is None:
            return None
        return _manual_int(value, label, low=0, high=8)

    min_fill = _fill(payload.get("minFill"), "minFill")
    max_fill = _fill(payload.get("maxFill"), "maxFill")
    if min_fill is not None and max_fill is not None and min_fill > max_fill:
        raise SimulationError("minFill must not exceed maxFill")
    # 约束映射到引擎 card key：候选池里的卡带 record.path。
    candidates_by_path: dict[str, Any] = {}
    for card in candidates:
        record_path = str((card.record or {}).get("path") or "")
        if record_path:
            candidates_by_path.setdefault(record_path, card.key)
    missing_required = [p for p in required_mod_paths if p not in candidates_by_path]
    if missing_required:
        raise SimulationError(
            "requiredMods are not in this weapon's candidate pool: "
            + ", ".join(missing_required[:5])
        )
    required_keys = [candidates_by_path[p] for p in required_mod_paths]
    forbidden_keys = [candidates_by_path[p] for p in forbidden_mod_paths if p in candidates_by_path]
    # ── 赋能纳入优化（assumed-max 100% 触发口径）──────────────────────
    # 配好的武器赋能走 passive 通道参与「填充最优」：与手动解算同一条
    # _prepare_manual_arcanes 路径（触发期望按无事件 stats 推导，即满层
    # 口径），评估开销为零（passive 合并一次，不随候选组合重算）。
    optimize_arcanes = payload.get("optimizeWithArcanes")
    optimize_with_arcanes = (
        bool(optimize_arcanes)
        if isinstance(optimize_arcanes, bool)
        else True  # 默认纳入：用户已配置的赋能就是本次解算语境的一部分
    )
    arcane_passives = incarnon_card
    arcane_unsupported_opt: list[str] = []
    if optimize_with_arcanes:
        raw_arcanes = payload.get("arcanes")
        validated: list[dict[str, Any]] = []
        if isinstance(raw_arcanes, list):
            arcane_slot_count = {"weapon": 0, "warframe": 0}
            seen_paths: set[str] = set()
            for item in raw_arcanes[:3]:
                if not isinstance(item, Mapping):
                    continue
                path = str(item.get("path") or "").strip()
                if not path or path not in MANUAL_ARCANES_BY_PATH or path in seen_paths:
                    continue
                meta = MANUAL_ARCANES_BY_PATH[path]
                kind = "weapon" if str(meta.get("slotKind") or "weapon") == "weapon" else "warframe"
                if arcane_slot_count[kind] >= (1 if kind == "weapon" else 2):
                    continue
                arcane_slot_count[kind] += 1
                seen_paths.add(path)
                record = optimizer.resolve_record(EXPORTS["arcanes"], path, kind="arcane")
                if not optimizer._arcane_matches_weapon(record, selected_weapon):
                    continue
                max_rank = meta.get("maxRank")
                rank = item.get("rank")
                if isinstance(rank, int) and not isinstance(rank, bool) and isinstance(max_rank, int):
                    rank = min(rank, max_rank)
                else:
                    rank = max_rank or 0
                validated.append({"path": path, "rank": rank})
        if validated:
            try:
                # assumed-max 口径（wfsim StackPolicy::AssumedMax 的移植）：
                # stacks = 该赋能触发器的 maxStacks（满层）、uptime 1.0。
                # _prepare_manual_arcanes 按 per-arcane 触发器解析真实层数上限，
                # 而不是拍 1 层。
                assumed_rows = []
                for item in validated:
                    record = optimizer.resolve_record(
                        EXPORTS["arcanes"], item["path"], kind="arcane"
                    )
                    trigger = record.get("trigger") if isinstance(record.get("trigger"), Mapping) else {}
                    max_stacks = trigger.get("maxStacks")
                    assumed_rows.append(
                        {
                            "query": item["path"],
                            "rank": item["rank"],
                            "stacks": int(max_stacks) if isinstance(max_stacks, int) and max_stacks > 0 else 1,
                            "uptime": 1.0,
                        }
                    )
                arcane_card, _states, arcane_unsupported_opt, _normalized = _prepare_manual_arcanes(
                    assumed_rows,
                    selected_weapon,
                    event_stats=None,
                    headshot_chance=0.0,
                )
                if arcane_card is not None:
                    arcane_passives = optimizer._merge_passives(incarnon_card, arcane_card)
            except (SimulationError, TypeError, ValueError):
                arcane_passives = incarnon_card
                arcane_unsupported_opt = ["optimize-arcanes-merge-failed-using-incarnon-only"]
    # 标准靶 KPM 口径（与分析页统一，用户指定的解算基准）：170 级钢铁之路
    # 卓越者超宏凶魂百夫长，30 秒窗口击杀数。流派不钳制（实战双修口径）。
    # 流派钳制已移除（用户确认实战即双修混搭）：全量池单次求解。
    # 标准靶 KPM 口径（与分析页统一）：170 级钢铁之路卓越者超宏凶魂百夫长，
    # 30 秒窗口击杀数——触发从零层爬升、护甲/超宏/等级缩放全部参与。
    benchmark_context = _benchmark_target_context(
        stance_multiplier=stance_multiplier,
        status_rate_multiplier=status_rate_multiplier,
    )
    with ANALYZE_LOCK:
        try:
            evaluation = optimizer._optimize(
                selected_weapon,
                candidates,
                None,
                scenario=scenario,
                metric="killsPerMinute" if dual_route else objective,
                passives=arcane_passives,
                slot_count=slot_count,
                capacity_limit=capacity_limit,
                required_damage_type=required_damage_type,
                target_context=benchmark_context if dual_route else None,
                profile=profile,
                required_mod_keys=required_keys,
                forbidden_mod_keys=forbidden_keys,
                min_fill=min_fill,
                max_fill=max_fill,
            )
        except SimulationError as exc:
            raise _translate_damage_type_failure(
                exc, selected_weapon, required_damage_type, element_target
            ) from exc
        if not getattr(evaluation, "cards", None) and (min_fill is None or min_fill > 0):
            # 数量下限为 0 时「裸枪」是合法解（cards 可为空）；分数为小数 KPM
            # 亦合法，只要有限且非负。
            raise SimulationError(
                f"optimizer returned no usable MOD build for fire mode {selected_fire_mode} metric {metric}"
            )
        score_value = getattr(evaluation, "score", None)
        if (
            isinstance(score_value, bool)
            or not isinstance(score_value, (int, float))
            or not math.isfinite(float(score_value))
            or float(score_value) < 0
        ):
            raise SimulationError(
                f"optimizer returned no usable MOD build for fire mode {selected_fire_mode} metric {metric}"
            )
        evaluation, selected_exilus = _auto_exilus(
            selected_weapon,
            catalog_weapon,
            evaluation,
            scenario=scenario,
            metric="killsPerMinute" if dual_route else objective,
            passives=arcane_passives,
            target_context=benchmark_context if dual_route else None,
            capacity_limit=capacity_limit,
        )
        build_archetype = "hybrid"
        if not evaluation.cards and (min_fill is None or min_fill > 0):
            raise SimulationError(
                f"optimizer returned no usable MOD build for fire mode {selected_fire_mode} metric {metric}"
            )
        build = optimizer._build_payload(selected_weapon, evaluation, None, arcane_passives)
        evaluated_metrics = optimizer._metrics(evaluation.stats)
        for key in ("shotDamage", "burstDps", "sustainedDps", "attackDps"):
            build[key] = evaluated_metrics[key]
        build["damageTypes"] = dict(evaluation.stats.damage_types)
        build["archetype"] = build_archetype
        build["objectiveDps"] = evaluation.score
        # 与分析页同名字段：解算目标的原始分数（KPM 口径 = 标准靶每分钟击杀数）。
        build["objectiveScore"] = evaluation.score
        build["stance"] = stance
        build["exilus"] = selected_exilus
        build["forma"] = _forma_summary(selected_weapon, evaluation.cards, stance)
        alternate_modes = _alternate_build_modes(
            weapon_record, evaluation, selected_fire_mode, scenario, incarnon_card
        )

    skipped = [
        f"optimizer-assumption: {slot_count} ordinary slots, {capacity_limit} capacity after stance, Catalyst and matching ordinary-slot Forma",
        "optimizer-objective: 标准靶 KPM（170 级钢铁之路卓越者超宏凶魂百夫长，30s 击杀数）；触发从零层爬升、护甲/超宏/等级缩放全部参与，流派不钳制（实战双修口径）",
        (
            f"optimizer-profile: {_PROFILE_LABELS[profile]}档"
            + (
                "（beam 12/32，无爬山）" if profile == "fast"
                else "（beam 24/40，3 轮爬山）" if profile == "standard"
                else "（beam 24/56，12 轮全邻域爬山）"
            )
        ),
        f"optimizer-search: profile {profile}, {len(candidates)} candidate mods, {rejected_mods} unsupported mods rejected",
    ]
    if required_mod_paths or forbidden_mod_paths or min_fill is not None or max_fill is not None:
        scope_bits = []
        if required_mod_paths:
            names = [str(MANUAL_MODS_BY_PATH[p].get("nameZh") or p) for p in required_mod_paths]
            scope_bits.append(f"必选 {'、'.join(names)}")
        if forbidden_mod_paths:
            names = [str(MANUAL_MODS_BY_PATH[p].get("nameZh") or p) for p in forbidden_mod_paths]
            scope_bits.append(f"禁选 {'、'.join(names)}")
        if min_fill is not None or max_fill is not None:
            scope_bits.append(
                f"数量 {min_fill if min_fill is not None else 0}–{max_fill if max_fill is not None else slot_count}"
            )
        skipped.append("optimizer-scope: " + " · ".join(scope_bits))
    if optimize_with_arcanes and arcane_passives is not incarnon_card:
        skipped.append(
            "optimizer-arcanes: 已配置的武器赋能按满层（100% 触发）口径参与本次解算"
        )
    skipped.extend(arcane_unsupported_opt)
    if element_target:
        skipped.append(
            f"optimizer-element-target: final build must contain {required_damage_type}"
        )
    skipped.extend(evaluation.stats.skipped)
    result = {
        "buildLabel": EXPORTS["buildLabel"],
        "schemaVersion": EXPORTS["schemaVersion"],
        "weapon": optimizer.record_identity(weapon_record),
        "weaponType": catalog_weapon["weaponType"],
        "fireMode": selected_fire_mode,
        "metric": metric,
        "buildArchetype": build_archetype,
        "archetypeComparison": None,
        "slotCount": slot_count,
        "elementTarget": element_target,
        "innateElement": innate_selection,
        "innateElementCandidates": list(catalog_weapon.get("innateElementCandidates") or ()),
        "incarnonChoices": incarnon_choices,
        "incarnonPolicy": incarnon_policy,
        "stance": stance,
        "exilus": selected_exilus,
        "optimizeWithArcanes": optimize_with_arcanes,
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
        "profile": profile,
        "limitations": CATALOG["buildOptions"]["limitations"],
    }
    if return_engine_context:
        # 最优紫卡求解路由复用：baseline evaluation + 求解器需要的全部语境。
        engine_context = {
            "evaluation": evaluation,
            "weapon": selected_weapon,
            "catalogWeapon": catalog_weapon,
            "scenario": scenario,
            "metric": "killsPerMinute" if dual_route else objective,
            "passives": arcane_passives,
            "capacityLimit": capacity_limit,
            "benchmarkContext": benchmark_context if dual_route else None,
            "weaponType": catalog_weapon["weaponType"],
            "stanceMultiplier": stance_multiplier,
            "candidates": candidates,
        }
        return result, engine_context
    return result


# 最优紫卡求解的时长档位（用户可调预算）：anytime 算法在预算内单调改进，
# 时间耗尽即返回当前 top10。
_RECOMMEND_BUDGET_SECONDS = (10.0, 20.0, 30.0, 60.0)


def recommend_riven_payload(payload: Any) -> dict[str, Any]:
    """最优紫卡词条求解（anytime 预算驱动，top-10）。

    接受与 /api/build 相同的武器/敌人/约束语境（前端直接复用配装表单
    payload），另加：
      budgetSeconds: 求解预算 10/20/30/60 秒（默认 10）
      topLimit:      返回组合数上限（默认 10，1-20）

    流程：先按当前语境解出「无紫卡最优配装」作为基准（与填充最优同一条
    _optimize 路径），再在基准配装上搜索 KPM 最高的紫卡词条组合（2-3 正
    + 0-1 负，理论满数值口径）。每个组合的分数是「该紫卡下基准配装子集
    的最优 KPM」——与用户手上这张卡的评分同口径。
    """
    if not isinstance(payload, Mapping):
        raise SimulationError("request body must be a JSON object")
    budget_raw = payload.get("budgetSeconds", 10.0)
    if isinstance(budget_raw, bool) or not isinstance(budget_raw, (int, float)):
        raise SimulationError("budgetSeconds must be a number")
    budget = float(budget_raw)
    if budget not in _RECOMMEND_BUDGET_SECONDS:
        raise SimulationError(
            "budgetSeconds must be one of " + ", ".join(str(int(v)) for v in _RECOMMEND_BUDGET_SECONDS)
        )
    top_limit = _manual_int(payload.get("topLimit", 10), "topLimit", low=1, high=20)

    # 基准解算：与 /api/build 同路径（无紫卡最优配装）。求解语境里的
    # 必选/禁选/数量约束全部参与——最优紫卡是在「当前限制下的最优配装」
    # 之上定义的。
    build_result, engine = build_weapon_payload(payload, return_engine_context=True)
    weapon_record = engine["weapon"]
    weapon_type = engine["weaponType"]
    baseline = engine["evaluation"]
    benchmark_context = engine["benchmarkContext"]
    # 评分靶自适应（与分析页同口径）：基准配装已秒杀饱和（KPM ≥ 重爬
    # 平衡点）时，求解语境升到 Lv9999——饱和平台上所有组合 tie 同一
    # KPM，求解器失去排序信号。KPM 展示值不受影响。
    # The window model advances in 250 ms slices, so one settled kill per
    # slice is 240 KPM.  Using 120 here promoted ordinary fast weapons to the
    # Lv9999 fallback too early and flattened the Riven search signal.
    _SOLVE_SATURATION_KPM = 240.0
    if (
        benchmark_context is not None
        and benchmark_context.get("level") != 9999
        and baseline.score >= _SOLVE_SATURATION_KPM
    ):
        benchmark_context = dict(benchmark_context, level=9999)
        baseline = optimizer._optimize(
            weapon_record,
            engine["candidates"],
            None,
            scenario=engine["scenario"],
            metric=engine["metric"],
            passives=engine["passives"],
            target_context=benchmark_context,
            profile="fast",
        )
    disposition = _finite_positive(weapon_record.get("omegaAttenuation")) or 1.0
    template_bases = optimizer._template_bases(
        EXPORTS.get("rivenTemplates") or {}, weapon_type
    )
    positive_candidates, _ = optimizer._candidate_lines(
        weapon_type, disposition, (), negative=False, bases=template_bases
    )
    negative_candidates, _ = optimizer._candidate_lines(
        weapon_type, disposition, (), negative=True, bases=template_bases
    )
    with ANALYZE_LOCK:
        recommendation = optimizer.recommend_optimal_riven(
            weapon_record,
            baseline,
            positive_candidates,
            negative_candidates,
            scenario=engine["scenario"],
            metric=engine["metric"],
            passives=engine["passives"],
            capacity_limit=engine["capacityLimit"],
            target_context=benchmark_context,
            budget_seconds=budget,
            top_limit=top_limit,
        )
    recommendation["weapon"] = optimizer.record_identity(weapon_record)
    recommendation["weaponType"] = weapon_type
    recommendation["disposition"] = disposition
    recommendation["baselineBuild"] = {
        "mods": build_result["build"]["mods"],
        "objectiveScore": build_result["build"]["objectiveScore"],
        "capacity": build_result["capacity"],
    }
    recommendation["metric"] = engine["metric"]
    recommendation["skipped"] = [
        f"recommend-budget: {int(budget)} 秒 anytime 预算（粗排 → beam 组合 → 精排，时间耗尽返回当前最优）",
        f"recommend-candidates: {len(positive_candidates)} 正面 / {len(negative_candidates)} 负面词条（理论满数值口径）",
        "recommend-basis: 每个组合的分数 = 该紫卡下基准配装子集的最优 KPM（与配装页解算同口径）",
    ]
    return recommendation


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
# 派系增伤卡（净化/灭亡/驱逐/牺牲 XX Prime 等，GAMEPLAY_FACTION_DAMAGE 词条）：
# 按指定目标的派系弱点定向加成。武器配装页维持目标中立口径——优化器候选池
# 与配装页选择器都不收录（手动模拟请求如显式传入则照常解算）。
FACTION_DAMAGE_MOD_PATHS = frozenset(
    row["path"]
    for row in (*MANUAL_MODS, *MANUAL_MOD_VARIANTS)
    if any(
        isinstance(effect, Mapping)
        and str(effect.get("upgradeType") or "").upper() == "GAMEPLAY_FACTION_DAMAGE"
        for effect in (row.get("effects") or ())
    )
)
# 目录行打标（引用同一 dict，打标对已下发的 manualMods 同样生效）：
# 前端配装页选择器按 factionDamage 标记过滤派系增伤卡。
for _row in (*MANUAL_MODS, *MANUAL_MOD_VARIANTS):
    if _row["path"] in FACTION_DAMAGE_MOD_PATHS:
        _row["factionDamage"] = True


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


# 解算档位（用户可调，避免干等）：fast/standard/deep。
_PROFILE_LABELS = {
    "fast": "快速",
    "standard": "标准",
    "deep": "深度",
}


def _solve_profile(value: Any, default: str = "standard") -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    profile = str(value).strip().casefold()
    if profile not in _PROFILE_LABELS:
        raise SimulationError(
            "profile must be one of fast, standard, deep"
        )
    return profile


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
    # 弱点命中触发（2026.09.22 更名：原 HeadshotCondition 系统性改为
    # WeakPointHitCondition——IsWeakpoint.lua 任意弱点部位 ≥0.5）。
    if "weakpoint" in text and ("hit" in text or "kill" in text):
        return "hit"
    if "crit" in text:
        return "crit"
    if "onhit" in text or "on_hit" in text:
        return "hit"
    if "onkill" in text or "on_kill" in text or "killcondition" in text:
        # on-kill 触发率同样随射速/多重/伤害变化（每秒击杀 = 命中 × 击杀率），
        # 与 on-hit 同一公式族（_manual_arcane_rate 的 hit 分支）。
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


# 自定义紫卡固定极性候选（常规六系，与游戏内紫卡极化范围一致）。
_RIVEN_FIXED_POLARITIES = {"AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_POWER", "AP_WARD", "AP_PRECEPT"}


def _manual_riven_slot_drain(
    payload: Mapping[str, Any], slot_polarities: Any
) -> int:
    """Capacity cost of the equipped custom Riven (18 base, polarity-scaled).

    The Riven's effects ride the passive channel (never in the kernel mod list),
    so the loadout validation never saw its drain — this reproduces the frontend
    workbench semantics: fixed Riven polarity vs. slot polarity (match halve,
    mismatch ×1.25, un-polarized slot full cost).
    """
    riven = payload.get("riven")
    if not isinstance(riven, Mapping) or not isinstance(riven.get("stats"), list):
        return 0
    base = 18
    polarity = str(riven.get("polarity") or "")
    slot = riven.get("slot")
    if polarity not in _RIVEN_FIXED_POLARITIES or not isinstance(slot, int) or slot < 0:
        return base
    slot_pol = None
    if isinstance(slot_polarities, list) and slot < len(slot_polarities):
        slot_pol = slot_polarities[slot]
    slot_pol = str(slot_pol or "")
    if not slot_pol or slot_pol in {"AP_UNIVERSAL", "AP_NONE", "NONE"}:
        return base
    if slot_pol == "AP_ANY" or slot_pol == polarity:
        return math.ceil(base / 2)
    return math.ceil(base * 1.25)


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
        # 灵化循环口径开关（缺省常驻灵化——紫卡分析维持常驻口径）。
        incarnon_cycle=_manual_bool(
            scenario_raw.get("incarnonCycle", payload.get("incarnonCycle", False)),
            "incarnonCycle",
        ),
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
    exilus_incompatible = False
    if exilus_raw is not None:
        if not isinstance(exilus_raw, Mapping):
            raise SimulationError("exilus must be an object when supplied")
        exilus_path = exilus_raw.get("path") or exilus_raw.get("query")
        if not isinstance(exilus_path, str) or exilus_path not in UTILITY_MODS_BY_PATH:
            raise SimulationError("exilus must use a supported utility MOD path")
        utility = UTILITY_MODS_BY_PATH[exilus_path]
        if not _utility_matches_weapon(utility, selected_weapon, weapon):
            # 前端选择器与旧存档可能仍携带不兼容的功能槽卡（如仅限回旋镖
            # 家族的「旋风」）。这类卡基本不影响伤害解算：按「不计入」降级
            # 处理并在诊断里注明，而不是让整个解算失败。
            exilus_incompatible = True
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
        # 不兼容卡不进内核（它对当前武器根本装不上），容量也按未装备计。
        if not exilus_incompatible and utility.get("catalogJoined"):
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

    mechanic_unsupported = [
        f"weapon-mod-mechanic-unmodeled:{path}"
        for path in (
            str(item.get("path") or "")
            for item in mods
            if isinstance(item, Mapping)
        )
        if path in WEAPON_MECHANICS_OVERRIDES.get("mods", {})
        and WEAPON_MECHANICS_OVERRIDES["mods"][path].get("status") in {
            "event-unmodeled",
            "unsupported",
        }
    ]
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
        "exilus_unvalidated_drain": exilus["drain"] if exilus and not exilus_mod and not exilus_incompatible else 0,
        "exilus_incompatible": exilus_incompatible,
        # 自定义紫卡槽的容量消耗（18 基础，按固定极性 × 槽位极性比对缩放）：
        # 紫卡效果走 passive 通道不进内核，容量校验在这里单独补上。
        "riven_slot_drain": _manual_riven_slot_drain(payload, slot_polarities),
        # 原始 riven payload（赋能贡献移除路径需要原样重建 passive 栈）。
        "riven_payload": payload.get("riven") if isinstance(payload.get("riven"), Mapping) else None,
        "mod_states": [
            {
                **(MANUAL_MODS_BY_PATH.get(item.get("path")) or {}),
                "rank": item.get("rank") if item.get("rank") is not None else (MANUAL_MODS_BY_PATH.get(item.get("path")) or {}).get("maxRank", 0),
                **({"slot": item["slot"]} if "slot" in item else {}),
            }
            for item in mods
        ],
        "mechanic_unsupported": mechanic_unsupported,
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


def _mod_exclusive_family(row: Mapping[str, Any]) -> str:
    """互斥家族键：modFamily + 武器兼容类别。镀层/普通/Prime 同名卡共享
    modFamily 且兼容同一武器家族（如镀层步枪才能与步枪才能），一张只能带一张；
    跨武器类别的同名家族（膛线=步枪 / 抵近射击=霰弹枪）互不冲突。
    """
    family = str(
        row.get("modFamily")
        or row.get("nameTag")
        or row.get("nameEn")
        or row.get("nameInternal")
        or row.get("path")
        or ""
    ).casefold()
    compatibility = str(row.get("compatibility") or "").casefold()
    return f"{family}#{compatibility}"


def _manual_normalize_mods(raw_mods: list[Any], slot_count: int) -> list[dict[str, Any]]:
    """Normalize raw mod entries into kernel-ready path/rank/slot dicts."""
    mods: list[dict[str, Any]] = []
    seen_families: dict[str, str] = {}
    for index, item in enumerate(raw_mods):
        if not isinstance(item, Mapping):
            raise SimulationError(f"mods[{index}] must be an object")
        path = item.get("path") or item.get("query")
        if not isinstance(path, str) or path.strip() not in MANUAL_MODS_BY_PATH:
            raise SimulationError(f"mods[{index}].path is not a supported weapon MOD")
        mod = MANUAL_MODS_BY_PATH[path.strip()]
        # 同名互斥：镀层/普通/Prime 版本共享 modFamily（如镀层步枪才能与步枪
        # 才能），同一配装只允许一张；冲突直接报错（与游戏内行为一致）。
        family = _mod_exclusive_family(mod)
        if family:
            previous = seen_families.get(family)
            if previous is not None and previous != str(path.strip()):
                raise SimulationError(
                    f"mods[{index}] 与 {previous} 属于同一 MOD 家族（镀层/普通/Prime "
                    f"同名卡互斥），一张配装只能携带一张"
                )
            seen_families[family] = str(path.strip())
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


def _collect_trigger_sources(ctx: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Pack equipped Arcanes + Galvanized MODs + Incarnon on-kill effects
    into trigger-source specs for the windowed model's emergent simulation.

    Each source: {id, label, kind, perEvent, maxStacks, duration}. The kind
    maps to the windowed model's event model (on-kill = kill count, on-hit
    = fire rate). Duration 0 = no decay (permanent while fighting).
    """
    sources: list[dict[str, Any]] = []

    # 1. Weapon/Warframe Arcanes with trigger stacks（state 字段是扁平的：
    #    maxStacks / durationSeconds / triggerCondition 等，不是嵌套 trigger dict）。
    for state in ctx.get("build_passives")(None).get("arcane_states") or ():
        if not isinstance(state, Mapping):
            continue
        max_stacks = state.get("maxStacks")
        if not isinstance(max_stacks, (int, float)) or max_stacks <= 1:
            continue
        condition_text = " ".join(
            str(x) for x in (state.get("triggerCondition"), state.get("triggerSource"))
        ).casefold()
        if "kill" in condition_text:
            kind = "on-kill"
        elif "headshot" in condition_text:
            kind = "on-hit"
        elif "crit" in condition_text:
            kind = "on-crit"
        elif "hit" in condition_text:
            kind = "on-hit"
        else:
            kind = "on-kill"  # 默认按 on-kill（多数武器赋能是击杀触发）
        sources.append({
            "id": str(state.get("path") or state.get("query") or f"arcane-{len(sources)}"),
            "label": str(state.get("nameZh") or state.get("nameEn") or "赋能"),
            "kind": kind,
            "perEvent": 1.0,
            "maxStacks": float(max_stacks),
            "duration": float(state.get("durationSeconds") or 0.0),
        })

    # 2. Galvanized MODs（on-kill conditionalEffects with maxStacks）。
    for mod_state in ctx.get("mod_states") or ():
        if not isinstance(mod_state, Mapping):
            continue
        for conditional in mod_state.get("conditionalEffects") or ():
            if not isinstance(conditional, Mapping):
                continue
            max_stacks = conditional.get("maxStacks")
            if not isinstance(max_stacks, (int, float)) or max_stacks <= 1:
                continue
            condition_text = " ".join(
                str(x) for x in (
                    conditional.get("conditionTag"),
                    *(conditional.get("conditions") or []),
                )
            ).casefold()
            if "kill" in condition_text:
                kind = "on-kill"
            elif "hit" in condition_text:
                kind = "on-hit"
            else:
                continue
            sources.append({
                "id": str(mod_state.get("path") or f"mod-{len(sources)}"),
                "label": str(mod_state.get("nameZh") or mod_state.get("nameEn") or "镀层"),
                "kind": kind,
                "perEvent": 1.0,
                "maxStacks": float(max_stacks),
                "duration": float(conditional.get("duration") or 20.0),
            })

    # 3. Incarnon on-kill evolutions（tier 进化里带 killcondition 的分支）。
    for effect in (ctx.get("incarnon_card").effects if ctx.get("incarnon_card") else ()) or ():
        source_path = str(getattr(effect, "source_path", "") or "")
        if "kill" not in source_path.casefold():
            continue
        sources.append({
            "id": source_path or f"incarnon-{len(sources)}",
            "label": "灵化 On-Kill",
            "kind": "on-kill",
            "perEvent": 1.0,
            "maxStacks": 1.0,
            "duration": 0.0,
        })

    # 4. Incarnon 条件 SubUpgrade 子词条（事件化叠层，如 Boltor 猩红序曲
    #    「每层 +2 伤害，最多 4 层，持续 5s」）。_incarnon_card 把这些子
    #    词条从面板通道排除（fail-closed）并打包成 trigger_specs；这里
    #    合并进窗口模型的触发源列表——层数折线图与赋能/镀层同一渲染通道。
    incarnon_card = ctx.get("incarnon_card")
    if incarnon_card is not None:
        for spec in getattr(incarnon_card, "trigger_specs", ()) or ():
            if not isinstance(spec, Mapping):
                continue
            entry = {
                "id": str(spec.get("id") or f"incarnon-sub-{len(sources)}"),
                "label": str(spec.get("label") or "灵化叠层"),
                "kind": str(spec.get("kind") or "on-hit"),
                "perEvent": float(spec.get("perEvent") or 1.0),
                "maxStacks": float(spec.get("maxStacks") or 1.0),
                "duration": float(spec.get("duration") or 0.0),
            }
            if isinstance(spec.get("damagePerStack"), (int, float)) and not isinstance(spec.get("damagePerStack"), bool):
                entry["damagePerStack"] = float(spec["damagePerStack"])
            sources.append(entry)

    return sources


def _benchmark_timeline_stats(modded: Mapping[str, Any]):
    """Rebuild a ModdedStats-like view from the serialized moddedStats dict.

    The windowed replay needs the dataclass fields (total_damage, crit etc.);
    simulate responses carry the serialized camelCase dict.  Only the fields
    the stepped model reads are mapped — anything missing falls back to the
    class defaults, which the replay tolerates (unknown fields simply do not
    amplify).
    """
    from wfarsenal.damage import ModdedStats

    def _num(*keys, default=0.0):
        for key in keys:
            value = modded.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return default

    damage_types = modded.get("damageTypes") or modded.get("damage_types") or {}
    if isinstance(damage_types, Mapping):
        damage_types = {str(k): float(v) for k, v in damage_types.items() if isinstance(v, (int, float))}
    else:
        damage_types = {}
    # CO（对触发目标增伤）回放重建：序列化 dict 不带 co_bucket（ModEffect
    # 不可 JSON 化），用 statusConditionDamageMultiplier（面板预乘的 CO 因子）
    # 与 coAssumedCount 反推 —— 窗口模型需要剥离预乘并按每步活层数重算。
    co_assumed = float(modded.get("coAssumedCount") or 0.0)
    co_factor = float(modded.get("statusConditionDamageMultiplier") or 1.0)
    co_bucket = []
    if co_assumed > 0 and co_factor > 1.0:
        # 近似重建一张 CO 效果：per-type 加成 = (factor - 1) / assumed。
        from wfarsenal.damage import ModEffect
        co_bucket = [
            ModEffect(
                upgrade_type="WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE",
                operation="STACKING_MULTIPLY",
                value=(co_factor - 1.0) / co_assumed,
                damage_type="DT_ANY",
                supported=True,
            )
        ]
    return ModdedStats(
        damage_types=damage_types,
        crit_chance=_num("critChance", "crit_chance"),
        crit_multiplier=_num("critMultiplier", "crit_multiplier", default=1.0) or 1.0,
        status_chance=_num("statusChance", "status_chance"),
        multishot=_num("multishot", default=1.0) or 1.0,
        fire_rate=_num("fireRate", "fire_rate", default=1.0) or 1.0,
        magazine=_num("magazine"),
        reload_time=_num("reloadTime", "reload_time"),
        proc_damage_multiplier=_num("procDamageMultiplier", "proc_damage_multiplier", default=1.0) or 1.0,
        proc_duration_multiplier=_num("procDurationMultiplier", "proc_duration_multiplier", default=1.0) or 1.0,
        co_bucket=co_bucket,
        co_assumed_count=co_assumed,
    )


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
    # API 口径分层（R2）：响应各数字块的模型来源标注，消费者不再需要猜。
    #   panel     — moddedStats（Arsenal 面板口径，暴击期望未乘）
    #   expected  — targetDamage/statusProcs（单击期望，暴击已乘）
    #   steady    — statusSustained* / dotSustainedDps 等闭式稳态（触发满层假设）
    #   windowed  — benchmarkTimeline（步进窗口：零层启动、逐 tick 活护甲/池）
    result["modelLayers"] = {
        "moddedStats": "panel",
        "targetDamage": "expected",
        "statusProcs": "expected",
        "statusSustained": "steady",
        "statusSustainedDps": "steady",
        "dotSustainedDps": "steady",
        "nonDotStatusSustainedDps": "steady",
        "steadyDirectDps": "steady",
        "totalSustainedDps": "steady",
        "killTimeline": "steady",
        "benchmarkTimeline": "windowed",
    }
    if ctx.get("exilus_incompatible") and exilus is not None:
        # 不兼容功能槽卡：解算照常完成，但注明该卡未计入（不参与伤害与容量）。
        note = (
            f"exilus-mod-not-compatible-with-weapon: "
            f"{exilus.get('nameZh') or exilus.get('nameEn') or exilus.get('path')}"
        )
        result["unsupported"] = sorted(
            set(result.get("unsupported") or ()) | {note}
        )
        result["skipped"] = list(
            dict.fromkeys([*(result.get("skipped") or ()), note])
        )
        if isinstance(exilus, dict):
            exilus = {**exilus, "incompatible": True}
        result["exilus"] = exilus
        result["selection"]["exilus"] = exilus
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
        | set(ctx.get("mechanic_unsupported") or ())
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
    riven_slot_drain = int(ctx.get("riven_slot_drain") or 0)
    extra_drain = extra_exilus_drain + riven_slot_drain
    if extra_drain:
        validation = result["loadoutValidation"]
        validation["capacity"] = int(validation.get("capacity") or 0) + extra_drain
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
    # 战斗演算 KPM 窗口时间线（回放数据源）：用当前配装在**用户选择的
    # 目标条件**（敌人/等级/钢铁之路/强化）上重放一次窗口步进模型，把每步
    # 的池余量/层数/DPS 分量下发给前端回放视图。此前固定 170 级标准靶，
    # 用户改敌人/等级时 KPM 不动 —— 现在跟随实际选择；无有效敌人时回退
    # 标准靶。
    try:
        _sr_mult = float(common.get("status_rate_multiplier") or 1.0)
        _dmg_mult = float(common.get("damage_rate_multiplier") or 1.0)
        # 用户选择的敌人（target 模型）；panel/custom 回退标准靶。
        _replay_enemy = (
            common.get("enemy_override")
            if isinstance(common.get("enemy_override"), Mapping)
            else next(
                (
                    row
                    for row in (EXPORTS.get("enemies") or ())
                    if isinstance(row, Mapping)
                    and str(row.get("path") or "") == str(common.get("enemy") or "")
                ),
                None,
            )
        )
        if isinstance(_replay_enemy, Mapping) and _replay_enemy.get("health"):
            _replay_ctx = {
                "target": _replay_enemy,
                "level": common.get("level"),
                "steel_path": bool(common.get("steel_path")),
                "enemy_enhancements": common.get("enemy_enhancements"),
            }
        else:
            _fallback = _benchmark_target_context(
                stance_multiplier=_dmg_mult,
                status_rate_multiplier=_sr_mult,
            )
            _replay_ctx = {
                "target": _fallback.get("target"),
                "level": _BENCHMARK_LEVEL,
                "steel_path": True,
                "enemy_enhancements": {"eximus": True},
            }
        if _replay_ctx.get("target") is not None:
            modded = result.get("moddedStats") or {}
            if isinstance(modded, Mapping) and modded.get("sustainedDps"):
                replay_stats = _benchmark_timeline_stats(modded)
                # 触发源打包：已配赋能 + 镀层 MOD + 灵化 on-kill 进化的层数
                # 规格，窗口模型按 emergent 模拟爬升并输出覆盖率折线。
                _trigger_sources = _collect_trigger_sources(ctx)
                _policy = str(payload.get("triggerPolicy") or "emergent")
                windowed = optimizer.windowed_status_damage(
                    replay_stats,
                    _replay_ctx["target"],
                    attacks_per_second=replay_stats.sustained_attack_rate,
                    window_seconds=_BENCHMARK_WINDOW_SECONDS,
                    level=_replay_ctx["level"],
                    steel_path=_replay_ctx["steel_path"],
                    enemy_enhancements=_replay_ctx["enemy_enhancements"],
                    status_rate_multiplier=_sr_mult,
                    damage_rate_multiplier=_dmg_mult,
                    trigger_sources=_trigger_sources if _policy == "emergent" else None,
                )
                result["benchmarkTimeline"] = {
                    "model": windowed.get("model"),
                    "windowSeconds": windowed.get("windowSeconds"),
                    "killsPerMinute": windowed.get("killsPerMinute"),
                    "killsInWindow": windowed.get("killsInWindow"),
                    "targetTotalEhp": windowed.get("targetTotalEhp"),
                    "points": windowed.get("timeline") or [],
                    "stacks": windowed.get("averagedStacks") or {},
                    "triggerSeries": windowed.get("triggerSeries") or [],
                    "triggerPolicy": _policy,
                    # 演算条件回显：前端标注本次 KPM 用的敌人/等级。
                    "context": {
                        "enemyPath": _replay_ctx["target"].get("path"),
                        "enemyName": _replay_ctx["target"].get("nameZh")
                        or _replay_ctx["target"].get("nameEn"),
                        "level": _replay_ctx["level"],
                        "steelPath": _replay_ctx["steel_path"],
                        "enhancements": _replay_ctx["enemy_enhancements"],
                    },
                }
    except (SimulationError, TypeError, ValueError):
        # 回放是增强数据；主解算结果不受影响。
        pass
    return result


def _mod_gains_metric_value(result: Mapping[str, Any], metric: str) -> float:
    stats = result.get("moddedStats") or {}
    target = result.get("targetDamage") or {}
    if metric in {"sustainedDps", "sustained_dps"}:
        # The loadout picker historically used direct target DPS here, which
        # made status-only cards (Elementalist/Duo mods) appear to contribute
        # exactly 0%.  When the kernel has a status ledger, compare the full
        # sustained total (direct + DoT + non-DoT) and fall back to panel DPS
        # only for models that do not expose that ledger.
        value = (
            result.get("totalSustainedDps")
            or (result.get("statusSustained") or {}).get("totalDps")
            or target.get("dps")
            or stats.get("sustainedDps")
            or stats.get("sustained_dps")
        )
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
    elif metric in {"statusSustainedDps", "status_sustained_dps", "totalSustainedDps"}:
        value = (
            result.get("totalSustainedDps")
            or result.get("statusSustainedDps")
            or (result.get("statusSustained") or {}).get("totalDps")
        )
    else:
        value = stats.get(metric) or target.get(metric)
    number = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return float(number) if number is not None and math.isfinite(float(number)) else 0.0


_MOD_GAINS_CACHE: dict[str, Any] = {}
_MOD_GAINS_CACHE_LIMIT = 24


def _build_passives_without_arcane(
    ctx: Mapping[str, Any],
    kept_arcanes: Sequence[Mapping[str, Any]],
    common: Mapping[str, Any],
) -> Any:
    """Passive effects with ONE arcane removed (equipped-mode contribution).

    Rebuilds the incarnon + remaining-arcanes + riven + external-buff passive
    stack on the same reducer path the full context uses, so the removed
    arcane's contribution is measured against an otherwise identical loadout.
    """
    event_stats = None
    needs = any(
        "triggerRate" not in item
        and "stacks" not in item
        and "uptime" not in item
        and _manual_arcane_trigger_kind(
            optimizer.resolve_record(EXPORTS["arcanes"], item["path"], kind="arcane")
        )
        for item in kept_arcanes
    )
    if needs:
        with ANALYZE_LOCK:
            event_stats = simulate(**common, hit_location="body")["moddedStats"]
    arcane_card, _states, _unsupported, _normalized = _prepare_manual_arcanes(
        list(kept_arcanes),
        ctx["weapon_record"],
        event_stats=event_stats,
        headshot_chance=ctx["headshot_chance"],
    )
    passives = _manual_passive_effects(
        optimizer._merge_passives(ctx["incarnon_card"], arcane_card)
    )
    riven_stats = ctx.get("riven_payload")
    if isinstance(riven_stats, Mapping) and isinstance(riven_stats.get("stats"), list):
        riven_effects = optimizer.synthetic_riven_effects(riven_stats["stats"])
        passives = ModEffectList(
            [*passives, *riven_effects],
            skipped=[*list(getattr(passives, "skipped", ())), *list(riven_effects.skipped)],
        )
    return passives


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
        # "__arcane__:<path>" measures one equipped Arcane's contribution
        # (equipped mode only): remove it from the passive channel and
        # re-simulate. Ranks come from the request's arcanes[] entries.
        if path.startswith("__arcane__:"):
            arcane_path = path.split(":", 1)[1]
            if arcane_path in MANUAL_ARCANES_BY_PATH and path not in seen:
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
    # ── F12（审计修复）：缓存键必须覆盖「实际被模拟消费」的完整请求语义。
    # 旧键手工维护字段清单，漏掉了 payload.riven——下面的计算明确读取并
    # 使用实际紫卡（build_passives 会注入 riven_effects），因此只改紫卡
    # 数值而其余字段不变的两次请求会命中同一个会话缓存键，返回旧结果。
    # 现改为：显式把规范化后的紫卡（含词条码、数值、正负与顺序）纳入键，
    # 并把「其余已入键字段」维持原样，避免行为漂移。
    _riven_cache_value = payload.get("riven") if isinstance(payload.get("riven"), Mapping) else None
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
            # 实际紫卡参与模拟：键必须随之变化（F12 回归 C02 的对象）。
            "riven": (
                {
                    "stats": [
                        {
                            "code": str(stat.get("code") or ""),
                            "value": stat.get("value"),
                            "negative": bool(stat.get("negative")),
                        }
                        for stat in (_riven_cache_value.get("stats") or [])
                        if isinstance(stat, Mapping)
                    ],
                }
                if _riven_cache_value is not None
                else None
            ),
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

    # Resolve the shared simulation context once; the kernel re-runs per
    # variant.  The arcane trigger-rate derivation, however, MUST be redone
    # per variant: a fire-rate or multishot card changes the hit rate that
    # _prepare_manual_arcanes reads, and reusing the baseline's rate measurably
    # over-reports the swap gain (measured: 射速卡 +34% on Primary Merciless).
    # build_passives(event_stats) derives rates from ONE simulate() pass over
    # the variant's own mod list, so each variant pays one extra cheap kernel
    # call only when a trigger-derived arcane is present.
    probe = dict(payload)
    probe.pop("timelineSeconds", None)
    ctx = _manual_resolve_sim_context(probe)
    common = dict(ctx["common"])
    metric = str(ctx["metric"] or "sustainedDps")
    passive_pack = ctx["build_passives"](None)
    passive_effects = passive_pack["passive_effects"]
    has_trigger_arcanes = any(
        "triggerRate" not in item
        and "stacks" not in item
        and "uptime" not in item
        and _manual_arcane_trigger_kind(
            optimizer.resolve_record(EXPORTS["arcanes"], item["path"], kind="arcane")
        )
        for item in ctx["validated_arcanes"]
    )
    with ANALYZE_LOCK:
        base_kernel = simulate(**common, hit_location="body", passive_effects=passive_effects)
    base_value = _mod_gains_metric_value(base_kernel, metric)

    mods_list = [dict(item) for item in ctx["raw_mods"] if isinstance(item, Mapping)]
    base_riven = payload.get("riven") if isinstance(payload.get("riven"), Mapping) else None
    gains: dict[str, Any] = {}

    def _variant_passives(variant_mods: list[dict[str, Any]], skip_riven: bool) -> Any:
        """Passive effects for one variant, re-deriving arcane trigger rates.

        Only pays the extra probe simulate() when a trigger-derived arcane is
        actually equipped; otherwise the shared baseline passives are reused
        (identical numbers, zero extra cost).
        """
        if not has_trigger_arcanes:
            return ctx["build_passives"](None, skip_riven=skip_riven)["passive_effects"]
        variant_common = {**common, "mods": variant_mods}
        # The probe pass must run WITHOUT passives (the arcane card itself is
        # what we are deriving) — plain ctx passives are fine to omit here
        # because event_stats only reads panel-level fire rate / multishot /
        # crit chance, which the mod list alone determines.
        with ANALYZE_LOCK:
            event_stats = simulate(**variant_common, hit_location="body")["moddedStats"]
        return ctx["build_passives"](event_stats, skip_riven=skip_riven)["passive_effects"]

    for path in candidates:
        arcane_removal = path.startswith("__arcane__:")
        mechanic_override = WEAPON_MECHANICS_OVERRIDES.get("mods", {}).get(path)
        # F16：sidecar schema v2 的统一口径——"event-unmodeled"（旧）与
        # "unsupported"（新）都走 fail-closed（返回空收益而非假收益）。
        # "conditional-supported" 表示数据已理解；若 simulatorImplemented
        # 仍为 false（机制已知但引擎未实现事件模拟），同样 fail-closed。
        if isinstance(mechanic_override, Mapping) and (
            mechanic_override.get("status") in {"event-unmodeled", "unsupported"}
            or (
                mechanic_override.get("status") == "conditional-supported"
                and mechanic_override.get("simulatorImplemented") is False
            )
        ):
            gains[path] = {
                "gainPercent": None,
                "reason": "event-mechanic-unmodeled",
                "mechanicId": mechanic_override.get("mechanicId"),
                "notes": list(mechanic_override.get("notes") or ()),
            }
            continue
        if mode == "equipped":
            variant_mods = [dict(item) for item in mods_list]
            if arcane_removal:
                # 赋能贡献：从 passive 通道移除该赋能（其余保持）。
                arcane_path = path.split(":", 1)[1]
                kept_arcanes = [
                    dict(item) for item in ctx["validated_arcanes"]
                    if item.get("path") != arcane_path
                ]
                if len(kept_arcanes) == len(ctx["validated_arcanes"]):
                    gains[path] = {"gainPercent": None, "reason": "arcane-not-equipped"}
                    continue
                try:
                    variant_passives = _build_passives_without_arcane(ctx, kept_arcanes, common)
                except (SimulationError, TypeError, ValueError):
                    gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
                    continue
            elif path == "__riven__":
                # measure the equipped Riven's contribution by removing it
                if base_riven is None:
                    gains[path] = {"gainPercent": None, "reason": "no-riven-equipped"}
                    continue
                try:
                    variant_passives = _variant_passives(variant_mods, skip_riven=True)
                except (SimulationError, TypeError, ValueError):
                    gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
                    continue
            else:
                # equipped MOD contribution: arcane rates shift too when a
                # fire-rate/multishot card is removed.
                variant_mods = [dict(item) for item in mods_list if item.get("path") != path]
                try:
                    variant_passives = _variant_passives(variant_mods, skip_riven=False)
                except (SimulationError, TypeError, ValueError):
                    gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
                    continue
        else:
            if path == "__riven__" or arcane_removal:
                gains[path] = {"gainPercent": None, "reason": "equipped-only-candidate"}
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
                variant_passives = _variant_passives(variant_mods, skip_riven=False)
            except (SimulationError, TypeError, ValueError):
                gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
                continue
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
            # ── 超容量仍显示贡献（2026-09-24 用户口径）────────────────────
            # 容量只标记「这张卡当前装不下」，不是「这张卡没价值」——贡献
            # 数值照算照显示（选择器/对比视图按 gain 排序时超容量卡也能
            # 参与比较），前端用 over-capacity 标记提示装配受限。
            loadout_validation = variant_result.get("loadoutValidation") or {}
            over_capacity = (
                mode != "equipped" and loadout_validation.get("valid") is False
            )
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
                **(
                    {
                        "reason": "over-capacity",
                        "capacity": loadout_validation.get("capacity"),
                        "capacityLimit": loadout_validation.get("capacityLimit"),
                    }
                    if over_capacity
                    else {}
                ),
            }
        except (SimulationError, TypeError, ValueError):
            gains[path] = {"gainPercent": None, "reason": "variant-not-computable"}
            continue
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
        # 分析进度轮询：?id=<progressToken>（analyze 期间前端每 500ms 查询）。
        if path == "/api/analyze/progress":
            query = parse_qs(urlsplit(self.path).query)
            token = (query.get("id") or [""])[0]
            with _ANALYZE_PROGRESS_LOCK:
                entry = _ANALYZE_PROGRESS.get(token)
                if entry is not None:
                    entry = dict(entry)
            if entry is None:
                self._send_error(HTTPStatus.NOT_FOUND, "unknown_token", "no progress entry for this token")
                return
            now = time.time()
            elapsed = max(now - float(entry.get("startedAt") or now), 0.0)
            since_beat = max(now - float(entry.get("lastBeat") or now), 0.0)
            total_stages = len(_ANALYZE_STAGES)
            stage_index = int(entry.get("stageIndex") or 0)
            self._send_json(
                HTTPStatus.OK,
                {
                    "token": token,
                    "stages": list(entry.get("stages") or []),
                    "stageIndex": stage_index,
                    "totalStages": total_stages,
                    "percent": round(min(stage_index / total_stages, 1.0) * 100, 1),
                    "elapsedSeconds": round(elapsed, 1),
                    "secondsSinceBeat": round(since_beat, 1),
                    "done": bool(entry.get("done")),
                    "error": entry.get("error"),
                },
                cache="no-cache",
            )
            return
        self._serve_static(path)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        analyzers = {
            "/api/analyze": analyze_payload,
            "/api/build": build_weapon_payload,
            "/api/simulate": simulate_manual_payload,
            "/api/mod-gains": mod_gains_payload,
            "/api/recommend-riven": recommend_riven_payload,
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
            static_root = DATASET_ROOT / "frontend"
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
