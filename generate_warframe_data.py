from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from data_sources import active_build, export_dir as active_export_dir, load_source_lock, provenance_path

ROOT = Path(__file__).resolve().parent
BUILD = active_build(ROOT)
EXPORT_DIR = active_export_dir(ROOT)
OUTPUT = ROOT / "data" / "warframe_build_data.json"
OVERFRAME_ABILITY_STATS = ROOT / "data" / "overframe_abilitystats.json"
ASSET_ROOT = ROOT / "frontend" / "assets" / "warframes"
PVP_RE = re.compile(r"pvp|conclave", re.I)
# ``Warframe Mod`` is also used by the upstream item mirror for a handful of
# cards that are installed on melee weapons or Parazons.  Keep those records
# out of the Warframe catalogue even when their historical folder is under
# ``Upgrades/Mods/Warframe``.
NON_WARFRAME_COMPAT_NAMES = {
    "melee",
    "parazon",
    "archgun",
    "archmelee",
    "sentinel",
    "companion",
    "kubrow",
    "kavat",
    "operator",
    "necramech",
}
POLARITIES = {
    "madurai": "AP_ATTACK",
    "vazarin": "AP_DEFENSE",
    "naramon": "AP_TACTIC",
    "zenurik": "AP_POWER",
    "unairu": "AP_WARD",
    "umbra": "AP_UMBRA",
    "penjaga": "AP_PRECEPT",
}
STAT_ALIASES = {
    "AVATAR_HEALTH_MAX": "health",
    "AVATAR_SHIELD_MAX": "shield",
    "AVATAR_ARMOUR": "armor",
    "AVATAR_ARMOR": "armor",
    "AVATAR_POWER_MAX": "energy",
    "AVATAR_ENERGY_MAX": "energy",
    "AVATAR_SPRINT_SPEED": "sprint",
    "AVATAR_MOVEMENT_SPEED": "sprint",
    "AVATAR_ABILITY_STRENGTH": "abilityStrength",
    "AVATAR_POWER_STRENGTH": "abilityStrength",
    "AVATAR_ABILITY_DURATION": "abilityDuration",
    "AVATAR_POWER_DURATION": "abilityDuration",
    "AVATAR_ABILITY_RANGE": "abilityRange",
    "AVATAR_POWER_RANGE": "abilityRange",
    "AVATAR_ABILITY_EFFICIENCY": "abilityEfficiency",
    "AVATAR_POWER_EFFICIENCY": "abilityEfficiency",
    "AVATAR_POWER_RATE": "energyRegen",
    "AVATAR_ENERGY_REGEN": "energyRegen",
    "AVATAR_HEALTH_REGEN": "healthRegen",
    "AVATAR_CASTING_SPEED": "castingSpeed",
    "AVATAR_PARKOUR_VELOCITY": "parkour",
    "AVATAR_PARKOUR_BOOST": "parkour",
}
SHARD_COLORS = {
    "BLUE": "blue",
    "GREEN": "green",
    "ORANGE": "orange",
    "PURPLE": "purple",
    "RED": "red",
    "YELLOW": "yellow",
}
SHARD_NAMES_ZH = {
    "blue": "碧蓝执刑官源力石",
    "green": "翠绿执刑官源力石",
    "orange": "琥珀执刑官源力石",
    "purple": "紫红执刑官源力石",
    "red": "绯红执刑官源力石",
    "yellow": "金黄执刑官源力石",
}

# Public set labels/descriptions are language records, not the internal
# ``EmptyArtifact`` shell name.  Keep the mapping here so every member card
# receives the same complete metadata even when its shell row is filtered.
SET_SHELL_TEXT = {
    "AmarSetMod": ("/Lotus/Language/Mods/AmarSetMod", "/Lotus/Language/Upgrades/AmarSetBonus"),
    "AshenSetMod": ("/Lotus/Language/Mods/AshenSetModName", "/Lotus/Language/Upgrades/HeavyAttackMovementBonusDesc"),
    "AugurSetMod": (None, "/Lotus/Language/Upgrades/WarframeAugurSetDesc"),
    "BonebladeSetMod": ("/Lotus/Language/Mods/BonebladeSetModName", "/Lotus/Language/Upgrades/BonebladeSetDesc"),
    "BorealSetMod": ("/Lotus/Language/Mods/BorealSetMod", "/Lotus/Language/Upgrades/BorealSetBonus"),
    "FemurSetMod": ("/Lotus/Language/Mods/FemurSetModName", "/Lotus/Language/Upgrades/LiftedEnemiesExplodeImpactDamageDesc"),
    "GladiatorSetMod": ("/Lotus/Language/Mods/MeleeGladiatorSetModName", "/Lotus/Language/Upgrades/WarframeGladiatorSetDesc"),
    "HawkSetMod": (None, "/Lotus/Language/Mods/HawkSetPassiveDesc"),
    "HunterSetMod": (None, "/Lotus/Language/Upgrades/WarframeHunterSetDesc"),
    "MechaSetMod": (None, "/Lotus/Language/Upgrades/MechaModSetBonus"),
    "NiraSetMod": ("/Lotus/Language/Mods/NiraSetMod", "/Lotus/Language/Upgrades/NiraSetBonus"),
    "RaptorSetMod": (None, "/Lotus/Language/Mods/RaptorSetModPassiveDesc"),
    "SacrificeSetMod": (None, "/Lotus/Language/Mods/WarframeUmbraModSetDesc"),
    "SpiderSetMod": (None, "/Lotus/Language/Mods/SpiderSetModPassiveDesc"),
    "StrainSetMod": (None, "/Lotus/Language/Upgrades/StrainModSetBonus"),
    "SynthSetMod": ("/Lotus/Language/Mods/SynthSetModName", "/Lotus/Language/Upgrades/SynthModSetBonus"),
    "TekSetMod": (None, "/Lotus/Language/Upgrades/TekModSetBonus"),
    "UmbraSetMod": (None, "/Lotus/Language/Mods/WarframeUmbraModSetDesc"),
    "VigilanteSetMod": (None, "/Lotus/Language/Upgrades/WarframeVigilanteSetDesc"),
}

SET_SHELL_NAMES = {
    "AmarSetMod": "欺谋狼主 Mod 组合加成",
    "AshenSetMod": "肉碾虫 Mod 组合加成",
    "AugurSetMod": "预言 Mod 组合加成",
    "BonebladeSetMod": "喉骨刃者 Mod 组合加成",
    "BorealSetMod": "诡文枭主 Mod 组合加成",
    "FemurSetMod": "重岩者 Mod 组合加成",
    "GladiatorSetMod": "角斗士 Mod 组合加成",
    "HawkSetMod": "空飞 Mod 组合加成",
    "HunterSetMod": "猎人 Mod 组合加成",
    "MechaSetMod": "Mecha Mod 组合加成",
    "NiraSetMod": "混沌蛇主 Mod 组合加成",
    "RaptorSetMod": "跃动 Mod 组合加成",
    "SacrificeSetMod": "牺牲 Mod 组合加成",
    "SpiderSetMod": "质子 Mod 组合加成",
    "StrainSetMod": "Strain Mod 组合加成",
    "SynthSetMod": "合成 Mod 组合加成",
    "TekSetMod": "技法 Mod 组合加成",
    "UmbraSetMod": "暗影 Mod 组合加成",
    "VigilanteSetMod": "私法 Mod 组合加成",
}

# Values shown beside the untouched in-game set description.  These are the
# published per-piece tables from the frozen Wiki snapshot; they are display
# data only and are deliberately kept separate from the simulator effects.
SET_DISPLAY_VALUES = {
    "AmarSetMod": {"RANGE": [10, 20, 30]},
    "AshenSetMod": {"STAT1": [10, 20, 30], "STAT2": [2, 4, 6]},
    "AugurSetMod": {"STAT1": [40, 80, 120, 160, 200, 240]},
    "BonebladeSetMod": {"STAT1": [3, 6, 9], "STAT2": [25, 50, 75], "STAT3": [3, 3, 3], "STAT4": [12, 9, 6]},
    "BorealSetMod": {"val": [20, 40, 60]},
    "FemurSetMod": {"STAT1": [10, 20, 30], "STAT2": [4, 8, 12], "DURATION": [6, 12, 18]},
    "GladiatorSetMod": {"STAT1": [10, 20, 30, 40, 50, 60]},
    "HawkSetMod": {"val": [3, 6, 9]},
    "HunterSetMod": {"STAT1": [25, 50, 75, 100, 125, 150]},
    "MechaSetMod": {"COOLDOWN": [60, 45, 30, 15], "DURATION": [3, 6, 9, 12], "RANGE": [7.5, 15, 22.5, 30]},
    "NiraSetMod": {"val": [150, 300, 450]},
    "RaptorSetMod": {"val": [33.4, 66.8, 100]},
    "SacrificeSetMod": {},
    "SpiderSetMod": {"val": [16.7, 33.4, 50]},
    "StrainSetMod": {"COOLDOWN": [25, 25, 25, 25], "COUNT": [2, 4, 6, 8], "DELAY": [25, 25, 25, 25]},
    "SynthSetMod": {"val": [5, 10, 15, 20]},
    "TekSetMod": {"COOLDOWN": [60, 45, 30, 15], "RADIUS": [3, 6, 9, 12], "DAMAGE": [50, 100, 150, 200]},
    "UmbraSetMod": {},
    "VigilanteSetMod": {"STAT1": [5, 10, 15, 20, 25, 30]},
}

_WIKI_PREFIX = "https___wiki_warframe_com_w_"
_WIKI_HASH_RE = re.compile(r"_[0-9a-f]{8,}$", re.I)
_WIKI_NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?|\.\d+)"
_WIKI_VECTOR_RE = re.compile(rf"{_WIKI_NUMBER}(?:\s*/\s*{_WIKI_NUMBER}){{3}}")


def _wiki_key(value: Any) -> str:
    """Normalize wiki titles and ability names for conservative matching."""
    text = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _decode_wiki_stem(stem: str) -> str:
    if stem.startswith(_WIKI_PREFIX):
        stem = stem[len(_WIKI_PREFIX) :]
    stem = _WIKI_HASH_RE.sub("", stem)
    # The crawler's filename sanitizer writes ASCII code points for common
    # punctuation (27 is apostrophe, 26 is ampersand, 2f is slash).
    for code, value in (("27", "'"), ("26", "&"), ("2f", "/"), ("20", " "), ("28", "("), ("29", ")")):
        stem = re.sub(rf"_{code}(?=\w|$)", value, stem, flags=re.I)
    return stem.replace("_", " ")


class WikiAbilityIndex:
    """Small, read-only index over the recovered Wiki JSON snapshot.

    The cleaner emits both per-ability pages (``Shuriken``) and frame pages
    with transcluded ability tables (``Ash/Abilities``).  We index filenames
    first and load only matching JSON files, keeping generation deterministic
    and avoiding a runtime dependency on the crawler directory.
    """

    def __init__(self, root: Path | None):
        self.root = root if root and root.is_dir() else None
        self._paths: dict[str, list[Path]] = {}
        self._frames: list[dict[str, Any]] | None = None
        self._cache: dict[str, dict[str, Any] | None] = {}
        if self.root:
            for path in self.root.glob("*.json"):
                key = _wiki_key(_decode_wiki_stem(path.stem))
                if key:
                    self._paths.setdefault(key, []).append(path)

    @staticmethod
    def _load(path: Path) -> dict[str, Any] | None:
        try:
            value = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _frame_pages(self) -> list[dict[str, Any]]:
        if self._frames is not None:
            return self._frames
        self._frames = []
        if not self.root:
            return self._frames
        for path in self.root.glob("*_*Abilities_*.json"):
            page = self._load(path)
            if not page:
                continue
            title = str(page.get("title") or "")
            if title.endswith("/Abilities") and "/Passive" not in title:
                page = {**page, "_snapshotPath": str(path)}
                self._frames.append(page)
        return self._frames

    def lookup(self, name: str) -> dict[str, Any] | None:
        key = _wiki_key(name)
        if not key:
            return None
        if key in self._cache:
            return self._cache[key]
        candidates = []
        for path in self._paths.get(key, []):
            page = self._load(path)
            if not page:
                continue
            title = str(page.get("title") or "")
            # Prefer an exact article over a quotes/passive/sub-page variant.
            score = 0
            if _wiki_key(title.rsplit("/", 1)[-1]) == key:
                score += 10
            if title.endswith("/Abilities"):
                score -= 3
            score += min(len(str(page.get("text") or "")), 10000) / 100000
            candidates.append((score, page, path))
        if candidates:
            _score, page, path = max(candidates, key=lambda item: item[0])
            result = {**page, "_snapshotPath": str(path)}
            self._cache[key] = result
            return result
        # A few direct articles are stubs in the recovered snapshot.  Their
        # frame page still contains the transcluded rank table; retain that as
        # an explicit, lower-confidence source instead of dropping the skill.
        needle = _wiki_key(name)
        for page in self._frame_pages():
            text = str(page.get("text") or "")
            if needle in _wiki_key(text) and ("/" in text or re.search(r"\d", text)):
                result = {**page, "_snapshotPath": page.get("_snapshotPath"), "_fallbackFor": name}
                self._cache[key] = result
                return result
        self._cache[key] = None
        return None

    def page(self, title: str) -> dict[str, Any] | None:
        """Resolve a page by its complete public title.

        ``lookup`` intentionally prefers short exact article names.  The
        native Helminth table is an aggregate page, so expose a separate
        title lookup to avoid accidentally selecting a same-named MOD page.
        """
        key = _wiki_key(title)
        if not key:
            return None
        requested_title = str(title or "").strip().casefold()
        candidates: list[tuple[int, dict[str, Any], Path]] = []
        for path in self._paths.get(key, []):
            page = self._load(path)
            if not page:
                continue
            page_title = str(page.get("title") or "").strip()
            # Prefer the exact public title before punctuation-insensitive
            # matches (for example, ``Fire Walker`` over ``Firewalker``).
            score = 100 if page_title.casefold() == requested_title else 0
            score += 10 if _wiki_key(page_title) == key else 0
            score += min(len(str(page.get("text") or "")), 10000) / 100000
            candidates.append((score, page, path))
        if not candidates:
            return None
        _score, value, path = max(candidates, key=lambda item: item[0])
        return {**value, "_snapshotPath": str(path)}

    def evidence(self, page: dict[str, Any] | None, *, name: str) -> dict[str, Any]:
        title = str((page or {}).get("title") or name)
        text = str((page or {}).get("text") or "")
        snapshot = (page or {}).get("_snapshotPath") or self.root
        evidence: dict[str, Any] = {
            "kind": "wiki",
            "url": "https://wiki.warframe.com/w/" + title.replace(" ", "_"),
            "title": title,
            "snapshotPath": provenance_path(snapshot) if snapshot else "",
        }
        if text:
            evidence["fragmentHash"] = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]
        if page and page.get("_fallbackFor"):
            evidence["fallbackFor"] = page["_fallbackFor"]
        return evidence


def _number_value(token: str) -> int | float:
    value = float(token.replace(",", ""))
    return int(value) if value.is_integer() else value


def _scalar_id(label: str, index: int) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", label.casefold()).strip("_")
    return value or f"wiki_value_{index}"


def _scalar_label_zh(label: str, index: int) -> str:
    """Translate the public field qualifier; never collapse distinct rows to numbered placeholders."""
    text = re.sub(r"\s+", " ", str(label or "")).strip().casefold()
    exact = {
        "damage": "技能伤害", "base damage": "基础伤害", "alternate base damage": "替代模式基础伤害",
        "initial damage": "初始伤害", "initial hit damage": "初始命中伤害", "main damage": "主要伤害",
        "damage per second": "每秒伤害", "damage/second": "每秒伤害", "damage/sec": "每秒伤害", "damage / s": "每秒伤害",
        "duration": "技能持续时间", "range": "技能范围", "radius": "技能半径", "cast range": "施放范围",
        "health": "生命值", "shield": "护盾", "armor": "护甲", "armour": "护甲",
        "status chance": "触发几率", "status duration": "触发持续时间", "critical chance": "暴击几率",
        "critical multiplier": "暴击倍率", "damage multiplier": "伤害倍率", "damage bonus": "伤害加成",
        "number of charges": "充能次数", "max targets": "最大目标数", "affected enemies": "影响敌人数",
        "energy cost": "能量消耗", "base energy drain": "基础持续耗能", "energy drain": "持续耗能",
    }
    if text in exact:
        return exact[text]
    phrases = (
        ("damage on direct hit per javelin", "每把标枪直接命中伤害"),
        ("damage on explosion per javelin", "每把标枪爆炸伤害"),
        ("damage on direct hit", "直接命中伤害"),
        ("damage on explosion", "爆炸伤害"),
        ("contact damage", "接触伤害"), ("collapse damage", "坍缩伤害"),
        ("damage per status effect", "每种异常状态额外伤害"),
        ("damage per pulse", "每次脉冲伤害"), ("damage per tick", "每跳伤害"),
        ("damage per shot", "每发伤害"), ("damage per hit", "每次命中伤害"),
        ("damage per second", "每秒伤害"), ("damage per sec", "每秒伤害"),
        ("imbued elemental damage", "注入元素伤害"), ("explosion damage", "爆炸伤害"),
        ("damage reduction", "伤害减免"), ("damage vulnerability", "伤害易伤"),
        ("health restore", "生命恢复"), ("health restored", "恢复生命值"),
        ("health per", "生命恢复量"), ("shield restore", "护盾恢复"),
        ("armor reduction", "护甲削减"), ("armour reduction", "护甲削减"),
        ("armor strip", "护甲削减"), ("defense reduction", "防御削减"),
        ("critical damage", "暴击伤害"), ("critical chance", "暴击几率"),
        ("status chance", "触发几率"), ("status duration", "触发持续时间"),
        ("energy drain", "持续耗能"), ("energy cost", "能量消耗"),
        ("duration", "持续时间"), ("lifespan", "持续时间"), ("invulnerability time", "无敌时间"),
        ("cooldown", "冷却时间"), ("radius", "半径"), ("range", "范围"), ("distance", "距离"),
        ("speed", "速度"), ("velocity", "速度"), ("angle", "角度"),
        ("charges", "充能次数"), ("targets", "目标数"), ("enemies", "敌人数"),
        ("arrows", "箭矢数量"), ("bolts", "投射物数量"), ("chance", "几率"),
        ("multiplier", "倍率"), ("bonus", "加成"), ("slow", "减速"),
    )
    for needle, translated in phrases:
        if needle in text:
            qualifier = ""
            if "base " in text and not translated.startswith("基础"):
                qualifier = "基础"
            if "initial " in text and not translated.startswith("初始"):
                qualifier = "初始"
            if "maximum" in text or text.startswith("max "):
                qualifier = "最大"
            if "minimum" in text or text.startswith("min "):
                qualifier = "最低"
            return qualifier + translated
    if "damage" in text:
        if "/s" in text or " per " in text or "per second" in text or "per sec" in text:
            return "增强每秒伤害" if "boosted" in text else "每秒伤害"
        if "projectile" in text:
            return "投射物伤害"
        if "pillar" in text:
            return "柱体伤害"
        if "beam" in text:
            return "光束伤害"
        if "boosted" in text:
            return "增强伤害"
        if "initial" in text:
            return "初始伤害"
        return "伤害"
    if "hitpoint" in text and ("drain" in text or "restore" in text):
        return "生命汲取/恢复"
    if "width" in text:
        return "宽度"
    if text.endswith(" percentage") or "percentage" in text:
        return "效果比例"
    return "技能参数"


_OVERFRAME_LABEL_PHRASES = {
    "boosted energy drain": "强化持续耗能",
    "energy drain per enemy": "每名敌人持续耗能",
    "energy drain per ability": "每个技能持续耗能",
    "energy drain": "持续耗能",
    "energy cost": "能量消耗",
    "damage per second": "每秒伤害",
    "damage / s": "伤害/秒",
    "damage/s": "伤害/秒",
    "damage per tick": "每跳伤害",
    "damage per hit": "每次命中伤害",
    "damage on hit": "命中伤害",
    "damage on impact": "冲击伤害",
    "damage on explosion": "爆炸伤害",
    "number of beams": "光束数量",
    "number of shurikens": "手里剑数量",
    "overshield points per pickup": "每次拾取过载护盾",
    "stored damage decay/sec": "储存伤害衰减/秒",
    "ability strength bonus": "技能强度加成",
    "ability duration": "技能持续时间",
    "ability range": "技能范围",
    "critical damage multiplier": "暴击伤害倍率",
    "damage vulnerability": "伤害易伤",
    "damage reduction": "伤害减免",
    "expansion distance per sec": "每秒扩散距离",
    "stagger on hit": "命中时击退/眩晕",
    "health and shield restore": "生命/护盾恢复",
    "health and shield restoration": "生命/护盾恢复",
    "shields to armor conversion": "护盾转护甲比例",
    "sprint speed bonus": "冲刺速度加成",
    "parkour velocity bonus": "跑酷速度加成",
    "strength bonus": "技能强度加成",
    "bonus duration": "增益持续时间",
    "damage copied": "复制伤害",
    "energy orb drop interval": "能量球掉落间隔",
    "hack chance": "自动破解几率",
    "chance duration": "几率持续时间",
    "shields restored": "恢复护盾",
    "health restored": "恢复生命值",
    "damage and shield restoration": "伤害与护盾恢复",
    "shield points per second": "每秒护盾恢复",
    "slash damage on hit": "切割命中伤害",
    "auto-target radius": "自动锁敌半径",
    "targeting range": "锁敌范围",
    "homing angle": "追踪角度",
    "finisher damage": "处决伤害",
    "energy refund on finisher kill": "处决击杀能量返还",
    "energy discount on blade storm target": "剑刃风暴目标能量折扣",
    "number of hits per mark": "每个标记命中次数",
    "number of shadow clones": "影分身数量",
    "invisible mark discount": "隐身标记能量折扣",
    "energy discount for teleport on marked enemy": "标记敌人瞬移能量折扣",
    "true damage": "真实伤害",
    "damage vulnerability": "伤害易伤",
    "damage vulnerability debuff": "伤害易伤减益",
    "status effects transfer": "异常状态转移",
    "reflected damage and status": "反射伤害与异常",
    "ally buff charge": "友军增益充能",
}

_OVERFRAME_LABEL_WORDS = {
    "base": "基础", "boosted": "强化", "initial": "初始", "final": "最终", "maximum": "最大", "max": "最大", "minimum": "最低", "min": "最低",
    "damage": "伤害", "blast": "爆炸", "impact": "冲击", "puncture": "穿刺", "slash": "切割", "heat": "火焰", "cold": "冰冻", "toxin": "毒素", "electricity": "电击", "radiation": "辐射", "corrosive": "腐蚀", "viral": "病毒", "magnetic": "磁力", "true": "真实",
    "pillar": "柱体", "projectile": "投射物", "beam": "光束", "ray": "射线", "wave": "波", "pulse": "脉冲", "ring": "环", "area": "区域", "field": "领域", "cone": "锥形", "radius": "半径", "range": "范围", "distance": "距离", "length": "长度", "width": "宽度", "height": "高度",
    "duration": "持续时间", "lifespan": "持续时间", "lifetime": "持续时间", "time": "时间", "interval": "间隔", "delay": "延迟", "cooldown": "冷却时间", "speed": "速度", "velocity": "速度", "rate": "速率", "growth": "增长", "increase": "增加", "decrease": "降低",
    "number": "数量", "count": "数量", "beams": "光束", "charges": "充能次数", "targets": "目标数", "target": "目标", "enemies": "敌人数", "enemy": "敌人", "allies": "友军", "ally": "友军", "hits": "命中次数", "hit": "命中", "stacks": "层数", "stack": "层数", "status": "异常", "chance": "几率", "critical": "暴击", "crit": "暴击", "multiplier": "倍率", "bonus": "加成", "buff": "增益", "debuff": "减益", "vulnerability": "易伤", "reduction": "削减", "restore": "恢复", "restoration": "恢复", "heal": "治疗", "health": "生命值", "shield": "护盾", "shields": "护盾", "armor": "护甲", "armour": "护甲", "energy": "能量", "power": "能量", "orb": "球体", "pickup": "拾取", "drop": "掉落", "kill": "击杀", "cast": "施放", "attack": "攻击", "melee": "近战", "weapon": "武器", "movement": "移动", "move": "移动", "jump": "跳跃", "dodge": "闪避", "stun": "眩晕", "blind": "致盲", "freeze": "冻结", "slow": "减速", "knockdown": "击倒", "range": "范围", "angle": "角度", "travel": "移动", "flight": "飞行", "throw": "投掷", "spawn": "生成", "initial": "初始", "final": "最终", "active": "激活", "passive": "被动", "duration": "持续时间", "self": "自身", "ally": "友军", "link": "连接", "chain": "连锁", "transfer": "转移", "conversion": "转化", "redirection": "转移", "decay": "衰减", "stored": "储存", "per": "每", "on": "时", "to": "至", "from": "来自", "for": "对", "with": "带有", "and": "与", "or": "或", "of": "的", "the": "", "of": "的", "on": "时",
    "mote": "晶体", "reservoir": "储能池", "reservoirs": "储能池", "overshield": "过载护盾", "overguard": "超宏防护", "finisher": "处决", "javelin": "标枪", "javelins": "标枪", "dagger": "匕首", "spore": "孢子", "spores": "孢子", "tornado": "龙卷风", "tornadoes": "龙卷风", "mirror": "镜像", "mirrors": "镜像", "pillar": "柱体", "thrall": "奴仆", "thralls": "奴仆", "shadow": "影分身", "shadows": "影分身", "well": "死亡之井", "death": "死亡", "sol": "太阳", "gate": "闸门", "rift": "裂隙", "probe": "探头", "probes": "探头", "vial": "药瓶", "vials": "药瓶", "residue": "残留", "explosion": "爆炸", "explosive": "爆炸", "contact": "接触", "direct": "直接", "indirect": "间接", "radial": "范围", "area": "区域", "splash": "溅射", "falloff": "衰减", "ramp-up": "递增", "ramp": "递增", "cap": "上限", "limit": "上限", "threshold": "阈值", "radius": "半径", "range": "范围", "speed": "速度", "cost": "消耗", "drain": "耗能", "restore": "恢复", "gain": "获得", "loss": "损失", "chance": "几率", "percentage": "百分比", "percent": "百分比", "bonus": "加成", "penalty": "惩罚", "penalties": "惩罚", "duration": "持续时间", "seconds": "秒", "second": "秒", "per second": "每秒", "per hit": "每次命中", "per kill": "每次击杀", "per enemy": "每名敌人", "per target": "每个目标", "hp": "生命值", "sp": "护盾", "ep": "能量", "m/s": "米/秒", "rev/sec": "转/秒", "deg": "度", "million": "百万", "times": "次", "uses": "使用次数", "use": "使用", "marks": "标记", "mark": "标记", "beam": "光束", "beams": "光束", "sweep": "扫掠", "rotation": "旋转", "stored": "储存", "decay": "衰减", "per": "每", "on": "时", "while": "期间", "during": "期间", "can": "可", "cannot": "不可", "when": "当", "after": "后", "before": "前", "above": "高于", "below": "低于", "grounded": "在地面", "airborne": "在空中", "charged": "蓄力", "charge": "蓄力", "full": "满", "empty": "空", "enemy": "敌人", "enemies": "敌人", "ally": "友军", "allies": "友军", "player": "玩家", "players": "玩家", "primary": "主要", "secondary": "次要", "alternate": "替代", "alt": "替代", "mode": "模式", "form": "形态", "normal": "普通", "boost": "强化", "effect": "效果", "effects": "效果", "type": "类型", "types": "类型", "random": "随机", "universal": "通用", "ammo": "弹药", "reload": "装填", "magazine": "弹匣", "critical": "暴击", "chance": "几率", "status": "异常", "proc": "触发", "procs": "触发", "immunity": "免疫", "invulnerability": "无敌", "invisible": "隐身", "invisibility": "隐身", "resistance": "抗性", "damage": "伤害", "vulnerability": "易伤", "strength": "强度", "duration": "持续时间", "range": "范围", "efficiency": "效率", "ability": "技能", "abilities": "技能", "weapon": "武器", "weapons": "武器", "body": "身体", "head": "头部", "headshot": "爆头", "weakpoint": "弱点", "health": "生命值", "shield": "护盾", "armor": "护甲", "armour": "护甲", "energy": "能量", "power": "能量", "movement": "移动", "speed": "速度", "attack": "攻击", "attacks": "攻击", "hit": "命中", "hits": "命中", "shot": "射击", "shots": "射击", "projectile": "投射物", "projectiles": "投射物", "duration": "持续时间", "radius": "半径", "range": "范围", "distance": "距离", "length": "长度", "width": "宽度", "height": "高度", "angle": "角度", "area": "区域", "field": "领域", "cone": "锥形", "wave": "波", "pulse": "脉冲", "blast": "爆炸", "impact": "冲击", "slash": "切割", "puncture": "穿刺", "heat": "火焰", "cold": "冰冻", "toxin": "毒素", "electricity": "电击", "radiation": "辐射", "corrosive": "腐蚀", "viral": "病毒", "magnetic": "磁力", "void": "虚空", "true": "真实", "damage": "伤害", "bonus": "加成", "multiplier": "倍率", "slow": "减速", "stun": "眩晕", "blind": "致盲", "freeze": "冻结", "sleep": "睡眠", "knockdown": "击倒", "pull": "牵引", "push": "推动", "attract": "吸引", "seek": "追踪", "targeting": "锁敌", "target": "目标", "targets": "目标", "link": "连接", "chain": "连锁", "spread": "扩散", "radius": "半径", "range": "范围", "duration": "持续时间", "time": "时间", "interval": "间隔", "delay": "延迟", "cooldown": "冷却时间", "speed": "速度", "velocity": "速度", "rate": "速率", "growth": "增长", "increase": "增加", "decrease": "降低", "number": "数量", "count": "数量", "limit": "上限", "maximum": "最大", "minimum": "最低", "initial": "初始", "final": "最终", "base": "基础", "boosted": "强化", "extra": "额外", "additional": "额外", "stored": "储存", "decay": "衰减", "conversion": "转化", "restore": "恢复", "gain": "获得", "drop": "掉落", "pickup": "拾取", "kill": "击杀", "cast": "施放", "on": "时", "per": "每", "of": "的", "to": "至", "from": "来自", "for": "对", "with": "带有", "and": "与", "or": "或", "the": "", "a": "", "an": "", "on": "时", "in": "中", "at": "在", "by": "由", "as": "作为", "into": "为", "against": "对", "through": "穿过", "during": "期间", "while": "期间", "without": "无", "cannot": "不可", "can": "可", "only": "仅", "per": "每", "rev": "转", "sec": "秒", "s": "秒", "m": "米", "x": "倍", "deg": "度",
}

_OVERFRAME_LABEL_WORDS.update({
    "auto": "自动", "targeted": "锁定", "targeting": "锁敌", "homing": "追踪", "seeking": "追踪", "propagation": "传播", "offering": "奉献", "pounce": "扑击", "knockback": "击退", "vacuum": "吸引", "weak": "弱点", "point": "点", "break": "破裂", "shatter": "碎裂", "stone": "岩石", "swallow": "吞噬", "maw": "巨口", "offering": "奉献", "roll": "翻滚", "petrified": "石化", "rolling": "滚动", "rumbler": "石巨人", "rubble": "碎石", "fury": "狂怒", "scorn": "蔑视", "catenach": "锁链", "vythelas": "维瑟拉斯", "gulphagor": "苦魔", "kaithe": "凯驰", "conculyst": "Conculyst", "redline": "红线", "sol": "太阳之门", "gate": "闸门", "damage/s": "伤害/秒", "per": "每", "initial": "初始", "extra": "额外", "additional": "额外", "stored": "储存", "enemy": "敌人", "enemies": "敌人", "ally": "友军", "allies": "友军", "beam": "光束", "beams": "光束", "area": "区域", "range": "范围", "radius": "半径", "duration": "持续时间", "speed": "速度", "chance": "几率", "damage": "伤害", "health": "生命值", "shield": "护盾", "energy": "能量", "armor": "护甲", "armour": "护甲", "ability": "技能", "weapon": "武器", "status": "异常", "critical": "暴击", "multiplier": "倍率", "bonus": "加成", "buff": "增益", "debuff": "减益", "cooldown": "冷却时间", "interval": "间隔", "delay": "延迟", "duration": "持续时间", "time": "时间", "count": "数量", "number": "数量", "limit": "上限", "maximum": "最大", "minimum": "最低", "target": "目标", "targets": "目标", "hit": "命中", "hits": "命中", "shot": "射击", "shots": "射击", "per hit": "每次命中", "per enemy": "每名敌人", "per target": "每个目标", "per kill": "每次击杀", "on kill": "击杀时", "on hit": "命中时", "on cast": "施放时", "while active": "激活期间", "during": "期间", "after": "后", "before": "前", "from": "来自", "to": "至", "of": "的", "and": "与", "or": "或", "with": "带有", "for": "对", "in": "在", "on": "时", "by": "由", "against": "对", "through": "穿过", "true": "真实", "physical": "物理", "damage": "伤害", "restore": "恢复", "restored": "恢复", "regeneration": "恢复", "regen": "恢复", "conversion": "转化", "redirection": "转移", "decay": "衰减", "falloff": "衰减", "growth": "增长", "increase": "增加", "decrease": "降低", "reduction": "削减", "vulnerability": "易伤", "immunity": "免疫", "invulnerability": "无敌", "invisible": "隐身", "resistance": "抗性", "resupply": "补给", "package": "补给包", "packages": "补给包", "ammo": "弹药", "magazine": "弹匣", "reload": "装填", "fire": "火焰", "electric": "电击", "electricity": "电击", "cold": "冰冻", "heat": "火焰", "toxin": "毒素", "viral": "病毒", "corrosive": "腐蚀", "radiation": "辐射", "magnetic": "磁力", "impact": "冲击", "puncture": "穿刺", "slash": "切割", "blast": "爆炸", "explosion": "爆炸", "explosive": "爆炸", "contact": "接触", "direct": "直接", "indirect": "间接", "radial": "范围", "splash": "溅射", "field": "领域", "wave": "波", "pulse": "脉冲", "ring": "环", "cone": "锥形", "chain": "连锁", "link": "连接", "spread": "扩散", "transfer": "转移", "pull": "牵引", "push": "推动", "attract": "吸引", "seek": "追踪", "stun": "眩晕", "blind": "致盲", "freeze": "冻结", "slow": "减速", "sleep": "睡眠", "knockdown": "击倒", "charge": "充能", "charges": "充能次数", "stack": "层数", "stacks": "层数", "mark": "标记", "marks": "标记", "drop": "掉落", "pickup": "拾取", "kill": "击杀", "cast": "施放", "attack": "攻击", "movement": "移动", "move": "移动", "jump": "跳跃", "dodge": "闪避", "flight": "飞行", "throw": "投掷", "spawn": "生成", "lifetime": "持续时间", "lifespan": "持续时间", "health": "生命值", "shield": "护盾", "energy": "能量", "power": "能量", "hp": "生命值", "sp": "护盾", "ep": "能量", "m/s": "米/秒", "rev/sec": "转/秒", "deg": "度", "million": "百万", "uses": "使用次数", "use": "使用", "range": "范围", "duration": "持续时间", "radius": "半径", "speed": "速度", "angle": "角度", "width": "宽度", "length": "长度", "height": "高度", "rate": "速率", "threshold": "阈值", "cap": "上限", "limit": "上限", "effect": "效果", "effects": "效果", "type": "类型", "types": "类型", "random": "随机", "universal": "通用", "primary": "主要", "secondary": "次要", "alternate": "替代", "alt": "替代", "mode": "模式", "form": "形态", "normal": "普通", "boost": "强化", "boosted": "强化", "full": "满", "empty": "空", "passive": "被动", "active": "激活", "body": "身体", "head": "头部", "headshot": "爆头", "weakpoint": "弱点", "direct": "直接", "base": "基础", "initial": "初始", "final": "最终", "extra": "额外", "bonus": "加成", "penalty": "惩罚", "critical": "暴击", "crit": "暴击", "chance": "几率", "status": "异常", "proc": "触发", "procs": "触发", "resistance": "抗性", "damage": "伤害", "vulnerability": "易伤", "strength": "强度", "efficiency": "效率", "ability": "技能", "abilities": "技能", "weapon": "武器", "weapons": "武器", "projectile": "投射物", "projectiles": "投射物", "radius": "半径", "range": "范围", "duration": "持续时间", "distance": "距离", "length": "长度", "width": "宽度", "height": "高度", "angle": "角度", "area": "区域", "field": "领域", "cone": "锥形", "wave": "波", "pulse": "脉冲", "blast": "爆炸", "impact": "冲击", "slash": "切割", "puncture": "穿刺", "heat": "火焰", "cold": "冰冻", "toxin": "毒素", "electricity": "电击", "radiation": "辐射", "corrosive": "腐蚀", "viral": "病毒", "magnetic": "磁力", "void": "虚空", "true": "真实", "damage": "伤害", "bonus": "加成", "multiplier": "倍率", "slow": "减速", "stun": "眩晕", "blind": "致盲", "freeze": "冻结", "sleep": "睡眠", "knockdown": "击倒", "pull": "牵引", "push": "推动", "attract": "吸引", "seek": "追踪", "targeting": "锁敌", "target": "目标", "targets": "目标", "link": "连接", "chain": "连锁", "spread": "扩散", "range": "范围", "duration": "持续时间", "time": "时间", "interval": "间隔", "delay": "延迟", "cooldown": "冷却时间", "speed": "速度", "velocity": "速度", "rate": "速率", "growth": "增长", "increase": "增加", "decrease": "降低", "number": "数量", "count": "数量", "limit": "上限", "maximum": "最大", "minimum": "最低", "initial": "初始", "final": "最终", "base": "基础", "boosted": "强化", "extra": "额外", "additional": "额外", "stored": "储存", "decay": "衰减", "conversion": "转化", "restore": "恢复", "gain": "获得", "drop": "掉落", "pickup": "拾取", "kill": "击杀", "cast": "施放", "on": "时", "per": "每", "of": "的", "to": "至", "from": "来自", "for": "对", "with": "带有", "and": "与", "or": "或", "the": "", "a": "", "an": "", "on": "时", "in": "中", "at": "在", "by": "由", "as": "作为", "into": "为", "against": "对", "through": "穿过", "during": "期间", "while": "期间", "without": "无", "cannot": "不可", "can": "可", "only": "仅", "rev": "转", "sec": "秒", "s": "秒", "m": "米", "x": "倍", "deg": "度",
})
_OVERFRAME_LABEL_WORDS.update({"conculyst": "征服者", "auto": "自动", "target": "目标", "radius": "半径", "duration": "持续时间", "range": "范围", "damage": "伤害", "speed": "速度", "chance": "几率", "number": "数量", "of": "的", "on": "时", "per": "每", "stored": "储存", "decay": "衰减", "beam": "光束", "beams": "光束", "sweep": "扫掠", "rotation": "旋转", "rev": "转", "sec": "秒"})
_OVERFRAME_LABEL_WORDS.update({"gel": "凝胶", "mist": "薄雾", "reach": "覆盖距离", "particles": "粒子", "fov": "视野角", "combo": "连击", "window": "窗口", "parallel": "平行", "walls": "墙体", "gap": "间距", "ec": "效果数值", "razorfly": "剃刀飞虫", "drones": "无人机", "holograms": "幻影", "lasers": "光束", "midair": "空中", "hop": "跳跃", "brush": "笔触", "stroke": "笔触", "layers": "层数", "aura": "光环", "nullification": "无效化", "threads": "丝线", "formed": "生成", "spacing": "间距", "bounces": "弹跳次数", "rewind": "回溯", "countdown": "倒计时", "ax": "最大", "webs": "蛛网", "page": "页面", "fragments": "碎片", "daggers": "匕首", "tentacles": "触手", "arrows": "箭矢", "lifesteal": "生命偷取", "life": "生命", "steal": "偷取", "firing": "射击", "arc": "弧度", "decoy": "诱饵", "healing": "治疗", "ricochets": "弹射次数", "sentient": "夜灵", "damage": "伤害", "heal": "治疗", "rate": "速率", "speed": "速度", "duration": "持续时间", "range": "范围", "radius": "半径", "chance": "几率", "number": "数量", "count": "数量", "target": "目标", "targets": "目标", "enemy": "敌人", "enemies": "敌人", "ally": "友军", "allies": "友军", "attack": "攻击", "hit": "命中", "hits": "命中", "shot": "射击", "shots": "射击", "status": "异常", "critical": "暴击", "bonus": "加成", "multiplier": "倍率", "reduction": "削减", "vulnerability": "易伤", "restore": "恢复", "conversion": "转化", "cooldown": "冷却时间", "interval": "间隔", "delay": "延迟", "velocity": "速度", "length": "长度", "width": "宽度", "height": "高度", "angle": "角度", "field": "领域", "area": "区域", "wave": "波", "pulse": "脉冲", "blast": "爆炸", "impact": "冲击", "slash": "切割", "puncture": "穿刺", "heat": "火焰", "cold": "冰冻", "toxin": "毒素", "electricity": "电击", "radiation": "辐射", "corrosive": "腐蚀", "viral": "病毒", "magnetic": "磁力", "void": "虚空", "true": "真实", "physical": "物理", "direct": "直接", "indirect": "间接", "primary": "主要", "secondary": "次要", "alternate": "替代", "mode": "模式", "form": "形态", "normal": "普通", "boosted": "强化", "base": "基础", "initial": "初始", "final": "最终", "extra": "额外", "additional": "额外", "stored": "储存", "decay": "衰减", "per": "每", "on": "时", "of": "的", "to": "至", "from": "来自", "for": "对", "with": "带有", "and": "与", "or": "或", "the": "", "a": "", "an": "", "in": "在", "at": "在", "by": "由", "as": "作为", "into": "为", "against": "对", "through": "穿过", "during": "期间", "while": "期间", "without": "无", "cannot": "不可", "can": "可", "only": "仅", "rev": "转", "sec": "秒", "s": "秒", "m": "米", "x": "倍", "deg": "度"})


def _overframe_label_zh(label: str) -> str:
    """Translate Overframe's field label while retaining its placeholders."""
    text = re.sub(r"\s+", " ", str(label or "")).strip().replace("бу", "°")
    lowered = text.casefold()
    # A few export labels contain a repeated qualifier (for example
    # ``Damage damage``) or an English noun missing from the compact word map.
    # Keep these as explicit, user-facing names instead of emitting the old
    # ``数量的``/duplicated-word artifacts.
    exact = {
        "number of probes": "探头数量",
        "number of uses": "使用次数",
        "damage damage": "伤害",
        "number of rumblers": "石巨人数量",
        "damage damage reduction": "伤害减免",
        "duration empowered duration": "强化持续时间",
        "number of targets per stun": "每次眩晕目标数",
        "number of sickles": "镰刀数量",
        "damage phantom wrath damage stored per damage instance": "幻影之怒每次伤害储存值",
        "duration invulnerable time": "无敌时间",
        "number of kaithes": "凯驰数量",
        "range range": "范围",
        "duration duration": "持续时间",
        "max number of lanterns": "最大灯笼数量",
        "number of ricochets": "弹射次数",
        "number of mirrors": "镜像数量",
        "number of shields": "护盾数量",
        "number of charges": "充能次数",
        "number of javelins": "标枪数量",
        "number of maggots": "蛆虫数量",
        "duration object lifetime": "物体存续时间",
        "number of bolts": "投射物数量",
        "number of vertices": "顶点数量",
        "duration scuttler duration": "爬行者持续时间",
        "damage lash damage": "鞭击伤害",
        "damage lash damage per dagger hit": "每把匕首命中鞭击伤害",
        "damage damage redirection": "伤害转移",
        "defense reduction": "防御削减",
        "healing": "治疗量",
        "number of streams": "流束数量",
        "number of motes": "晶体数量",
        "number of tornadoes": "龙卷风数量",
        "number of statuses for extra time: ≥": "额外时间所需异常数：≥",
        "number of targets": "目标数量",
        "number of blades": "刀刃数量",
        "recast energy discount": "重新施放能量折扣",
        "energy convert": "能量转化比例",
        "enthrall energy discount": "奴役能量折扣",
    }
    if lowered in exact:
        return exact[lowered]
    for source, target in sorted(_OVERFRAME_LABEL_PHRASES.items(), key=lambda item: len(item[0]), reverse=True):
        lowered = lowered.replace(source, target)
    # Keep punctuation/placeholders, translate remaining English words.
    def word(match: re.Match[str]) -> str:
        word_value = match.group(0)
        return _OVERFRAME_LABEL_WORDS.get(word_value.casefold(), "")
    translated = re.sub(r"[A-Za-z][A-Za-z']*", word, lowered)
    translated = re.sub(r"\s+", " ", translated).strip(" :,-")
    translated = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", translated)
    translated = translated.replace(" · ", "·")
    translated = translated.replace("扫掠 区域", "扫掠范围").replace("异常 几率", "异常触发几率").replace("强化 异常 几率", "强化异常触发几率").replace("强化 伤害/秒", "强化伤害/秒").replace("光束 半径", "光束半径").replace("光束数量", "光束数量")
    translated = translated.replace("弹药 效率", "弹药效率").replace("生命值 与 护盾 恢复", "生命/护盾恢复").replace("生命值 恢复", "恢复生命值").replace("护盾 恢复", "恢复护盾").replace("护盾 至 护甲 转化", "护盾转护甲比例").replace("距离 每 秒", "每秒扩散距离").replace("时 命中", "命中时").replace("加成 持续时间", "增益持续时间").replace("速度 加成", "速度加成").replace("强度 加成", "技能强度加成").replace("爆炸 范围", "爆炸范围").replace("施放 范围", "施放范围").replace("最大 目标", "最大目标数").replace("标记 持续时间", "标记持续时间").replace("最大 伤害", "最大伤害").replace("几率 持续时间", "几率持续时间").replace("锥形 角度", "锥形角度").replace("异常 效果", "异常效果").replace("太阳之门 闸门", "太阳之门").replace("强化 光束半径", "强化光束半径").replace("旋转 速度 转/秒", "旋转速度（转/秒）").replace("强化 异常触发几率", "强化异常触发几率").replace("扫掠区域", "扫掠范围").replace("异常几率", "异常触发几率").replace("强化异常几率", "强化异常触发几率").replace("治疗 时间", "每秒治疗").replace("治疗时间", "每秒治疗").replace("速度 速度", "速度")
    translated = re.sub(r"最大目标(?!数)", "最大目标数", translated).replace("旋转速度转/秒", "旋转速度（转/秒）")
    translated = re.sub(r"\bper\s*sec(?:ond)?\b|/\s*s\b|/\s*S\b", "/秒", translated, flags=re.I)
    translated = re.sub(r"\bsec(?:ond)?s?\b", "秒", translated, flags=re.I)
    translated = re.sub(r"\bmeter(?:s)?\b", "米", translated, flags=re.I)
    translated = re.sub(r"\s+([:/%°])", r"\1", translated)
    translated = re.sub(r"([:/%°])\s+", r"\1", translated)
    # Remove adjacent duplicate Chinese qualifiers introduced by labels such
    # as ``Range Range`` while preserving meaningful separated occurrences.
    for token in ("伤害", "持续时间", "范围", "半径", "数量", "速度", "时间", "能量"):
        translated = translated.replace(token + token, token)
    return translated or "未分类字段"


def _load_overframe_ability_stats() -> dict[str, list[dict[str, Any]]]:
    if not OVERFRAME_ABILITY_STATS.is_file():
        return {}
    try:
        payload = load(OVERFRAME_ABILITY_STATS)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


_OVERFRAME_ABILITY_STATS_CACHE: dict[str, list[dict[str, Any]]] | None = None
_OVERFRAME_ABILITY_STATS_HASH: str | None = None
_OVERFRAME_ID_ALIASES = {
    "/Lotus/Powersuits/SiriusOrion/Abilities/OrionScytheAbility": "/Lotus/Powersuits/SiriusOrion/Abilities/SiriusScytheAbility",
    "/Lotus/Powersuits/SiriusOrion/Abilities/OrionBuffAbility": "/Lotus/Powersuits/SiriusOrion/Abilities/SiriusBuffAbility",
    "/Lotus/Powersuits/SiriusOrion/Abilities/OrionVortexAbility": "/Lotus/Powersuits/SiriusOrion/Abilities/SiriusFieldAbility",
    "/Lotus/Powersuits/SiriusOrion/Abilities/OrionUltimateAbility": "/Lotus/Powersuits/SiriusOrion/Abilities/SiriusOrionUltimateAbility",
}


def overframe_ability_stats(unique_name: str) -> list[dict[str, Any]]:
    global _OVERFRAME_ABILITY_STATS_CACHE
    if _OVERFRAME_ABILITY_STATS_CACHE is None:
        _OVERFRAME_ABILITY_STATS_CACHE = _load_overframe_ability_stats()
    rows = _OVERFRAME_ABILITY_STATS_CACHE.get(unique_name) or _OVERFRAME_ABILITY_STATS_CACHE.get(_OVERFRAME_ID_ALIASES.get(unique_name, "")) or []
    return [row for row in rows if isinstance(row, dict)]


def overframe_ability_evidence(unique_name: str) -> dict[str, Any] | None:
    rows = overframe_ability_stats(unique_name)
    if not rows:
        return None
    global _OVERFRAME_ABILITY_STATS_HASH
    if _OVERFRAME_ABILITY_STATS_HASH is None and OVERFRAME_ABILITY_STATS.is_file():
        _OVERFRAME_ABILITY_STATS_HASH = hashlib.sha256(OVERFRAME_ABILITY_STATS.read_bytes()).hexdigest()
    return {
        "kind": "overframe-abilitystats",
        "url": next((source.get("url") for source in load_source_lock(ROOT).get("sources") or [] if source.get("id") == "overframe-abilitystats"), ""),
        "path": "data/overframe_abilitystats.json",
        "fieldCount": len(rows),
        "sha256": _OVERFRAME_ABILITY_STATS_HASH,
    }


def _modifier_scale(modifier: Any) -> str:
    value = str(modifier or "").upper()
    return {
        "AVATAR_ABILITY_STRENGTH": "strength",
        "AVATAR_ABILITY_DURATION": "duration",
        "AVATAR_ABILITY_RANGE": "range",
        "AVATAR_ABILITY_EFFICIENCY": "efficiency",
        "ENERGY_DRAIN": "drain",
    }.get(value, "none")


def _overframe_field(label: str, values: dict[str, Any], modifier: Any, group: str | None, display_order: int) -> dict[str, Any]:
    keys = [key for key in values if isinstance(values.get(key), (int, float)) and not isinstance(values.get(key), bool)]
    parts = {key: values[key] for key in keys}
    raw_label = str(label or "").replace("бу", "°")
    placeholders = list(re.finditer(r"\|([^|]+)\|", raw_label))
    if placeholders:
        prefix = raw_label[:placeholders[0].start()].strip(" :,-")
        suffix = raw_label[placeholders[-1].end():].strip(" :,-")
        unit_match = re.match(r"^(%|x|m/s|m|s|/s|°|HP|SP|EP)\s*", suffix, re.I)
        unit = unit_match.group(1) if unit_match else ""
        if unit_match:
            suffix = suffix[unit_match.end():].strip(" :,-")
        label_template = " ".join(part for part in (prefix, suffix) if part).strip(" :,-")
        if not label_template:
            label_template = re.sub(r"\|[^|]+\|", "", raw_label).strip(" :,-")
        separators = re.sub(r"\|[^|]+\|", "", raw_label[placeholders[0].start():placeholders[-1].end()])
        separator = "-" if "-" in separators else "/" if "/" in separators else " / " if len(placeholders) > 1 else ""
        value_template = separator.join("{}" for _ in placeholders) + unit
    else:
        label_template = raw_label.strip(" :,-")
        value_template = "{}"
        unit_match = re.search(r"(%|x|m/s|m|s|/s|°|HP|SP|EP)\s*$", raw_label, re.I)
        unit = unit_match.group(1) if unit_match else ""
    if not label_template:
        label_template = "技能数值"
    label_zh = _overframe_label_zh(label_template)
    return {
        "id": f"{_scalar_id(label_template, display_order)}_{display_order}",
        "label": label_template,
        "labelEn": label_template,
        "labelZh": label_zh,
        "valueTemplate": value_template,
        "valueKeys": keys,
        "parts": parts,
        "values": [parts[keys[0]]] if keys else [],
        "rankCount": 1,
        "base": parts[keys[0]] if keys else None,
        "unit": unit,
        "scale": _modifier_scale(modifier),
        "modifier": modifier,
        "group": _overframe_label_zh(group) if group else None,
        "variant": group,
        "displayOrder": display_order,
        "isStatic": str(modifier or "").upper() == "NONE",
        "isEnergy": "energy cost" in str(label).casefold() or "energy drain" in str(label).casefold(),
        "sourceKind": "overframe-abilitystats",
    }


def _overframe_fields(unique_name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    group: str | None = None
    for order, entry in enumerate(overframe_ability_stats(unique_name)):
        label = str(entry.get("Label") or "").strip()
        values = entry.get("Values")
        if not label:
            continue
        if not isinstance(values, dict) or not any(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values.values()):
            group = label
            groups.append({"labelEn": label, "labelZh": _overframe_label_zh(label), "displayOrder": order})
            continue
        fields.append(_overframe_field(label, values, entry.get("Modifier"), group, order))
    return fields, groups


def _label_tokens(value: Any) -> set[str]:
    return {token for token in re.findall(r"[a-z][a-z0-9]+", str(value or "").casefold()) if token not in {"the", "of", "and", "per", "on", "to", "for", "with", "a", "an"}}


def _normalize_legacy_field_labels(existing: list[dict[str, Any]], context_name: str = "") -> list[dict[str, Any]]:
    merged = [dict(field) for field in existing if isinstance(field, dict)]
    context_name = re.sub(r"\bSentient\b", "夜灵", str(context_name or ""), flags=re.I)
    used_labels: dict[str, int] = {}
    generic_labels = {"技能参数", "伤害", "持续时间", "范围", "半径", "数量", "速度", "几率", "加成", "倍率"}
    for field in merged:
        label = str(field.get("labelZh") or "").strip()
        source = str(field.get("label") or field.get("id") or "技能数值").replace("_", " ")
        if re.search(r"[A-Za-z]", source) or not label or label in generic_labels:
            label = _overframe_label_zh(source)
        # Keep repeated labels distinguishable even when they come from
        # separately sourced Wiki rows (for example two different heals).
        if label == "治疗量":
            field_label = str(field.get("label") or field.get("id") or "").casefold()
            if "heal" in field_label or "restor" in field_label:
                label = "治疗量"
        broad_label = label.removeprefix("技能")
        if label in generic_labels or broad_label in {"伤害", "持续时间", "范围", "半径", "数量", "速度", "几率", "加成", "倍率", "参数"} or label == "未分类字段":
            label = f"{context_name} · {label}" if context_name else f"字段 · {label}"
        count = used_labels.get(label, 0)
        used_labels[label] = count + 1
        if count:
            label = f"{label}（第{count + 1}项）"
        field["labelZh"] = label
    return merged


def _merge_overframe_fields(unique_name: str, existing: list[dict[str, Any]], context_name: str = "") -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    over_fields, groups = _overframe_fields(unique_name)
    if not over_fields:
        return _normalize_legacy_field_labels(existing, context_name), groups
    old = [field for field in existing if isinstance(field, dict)]
    used: set[int] = set()
    merged: list[dict[str, Any]] = []
    for field in over_fields:
        base = field.get("base")
        tokens = _label_tokens(field.get("label"))
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        for index, candidate in enumerate(old):
            if index in used:
                continue
            candidate_base = candidate.get("base")
            overlap = len(tokens & _label_tokens(candidate.get("label") or candidate.get("id")))
            distance = abs(float(candidate_base) - float(base)) if isinstance(candidate_base, (int, float)) and isinstance(base, (int, float)) else 999999
            score = overlap * 100.0 - min(distance / max(1.0, abs(float(base or 1))), 20.0)
            candidates.append((score, index, candidate))
        candidate = max(candidates, default=None, key=lambda item: item[0])
        if candidate and candidate[0] >= 30:
            used.add(candidate[1])
            rank_values = candidate[2].get("values") or candidate[2].get("baseValues") or []
            if not isinstance(rank_values, list):
                rank_values = []
            if rank_values and isinstance(base, (int, float)) and abs(float(rank_values[-1]) - float(base)) <= max(1.0, abs(float(base)) * 0.03):
                field["rankValues"] = rank_values
                field["rankCount"] = len(rank_values)
            else:
                field["rankValues"] = [base] * 4 if isinstance(base, (int, float)) else []
                field["rankCount"] = 4 if field["rankValues"] else 0
        else:
            field["rankValues"] = [base] * 4 if isinstance(base, (int, float)) else []
            field["rankCount"] = 4 if field["rankValues"] else 0
        merged.append(field)
    # Keep explicit Wiki Misc/audited rows that Overframe does not expose. They
    # carry a separate provenance and are the static mechanics users still
    # need (caps, cooldowns, pickup values, etc.); discard only old duplicate
    # table rows that caused generic label inflation.
    next_order = max((int(field.get("displayOrder") or 0) for field in merged), default=0) + 1
    extras = []
    for index, field in enumerate(old):
        if index in used or field.get("sourceKind") not in {"wiki-misc", "wiki-audited"}:
            continue
        old_tokens = _label_tokens(field.get("label") or field.get("id"))
        old_base = field.get("base")
        duplicate = any(
            old_tokens and len(old_tokens & _label_tokens(item.get("label") or item.get("id"))) >= max(1, min(2, len(old_tokens)))
            and (not isinstance(old_base, (int, float)) or not isinstance(item.get("base"), (int, float)) or abs(float(old_base) - float(item.get("base"))) <= max(1.0, abs(float(old_base)) * 0.03))
            and str(field.get("unit") or "") == str(item.get("unit") or "")
            for item in merged
        )
        if duplicate:
            continue
        extra = dict(field)
        extra["displayOrder"] = next_order
        next_order += 1
        extras.append(extra)
    merged.extend(extras)
    merged.sort(key=lambda field: int(field.get("displayOrder") or 0))
    normalized = _normalize_legacy_field_labels(merged, context_name)
    return normalized, groups


def _merge_overframe_energy_cost(cost: dict[str, Any] | None, fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    result = dict(cost or {})
    for field in fields:
        label = str(field.get("label") or "").casefold()
        base = field.get("base")
        if not isinstance(base, (int, float)):
            continue
        if "energy cost" in label and "drain" not in label and base > 0:
            result["activation"] = base
            result["resource"] = "energy"
        elif "boosted energy drain" in label:
            result["boostedDrainPerSecond"] = base
            result["resource"] = "energy"
        elif "energy drain" in label:
            if "per enemy" in label:
                result["perEnemyPerSecond"] = base
            elif "per ability" in label:
                result["perAbilityPerSecond"] = base
            else:
                result["drainPerSecond"] = base
            result["resource"] = "energy"
    return result or None


def _overframe_field_values(field: dict[str, Any]) -> list[float | int]:
    parts = field.get("parts") if isinstance(field.get("parts"), dict) else {}
    keys = field.get("valueKeys") if isinstance(field.get("valueKeys"), list) else list(parts)
    return [parts[key] for key in keys if isinstance(parts.get(key), (int, float)) and not isinstance(parts.get(key), bool)]


def _promote_overframe_fields(unique_name: str, existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Use Overframe's complete field rows as the canonical display schema."""
    over_fields, groups = _overframe_fields(unique_name)
    if not over_fields:
        return _merge_overframe_fields(unique_name, existing)
    promoted: list[dict[str, Any]] = []
    for field in over_fields:
        values = _overframe_field_values(field)
        if not values:
            continue
        rank = next((candidate for candidate in existing if candidate.get("id") == field.get("id")), None)
        rank_values = rank.get("values") if isinstance(rank, dict) else None
        if not isinstance(rank_values, list) or not rank_values:
            rank_values = [values[0]] * 4
        field["values"] = values
        field["rankValues"] = rank_values
        field["base"] = values[0]
        field["rankCount"] = len(rank_values)
        # Overframe's Values are already rank-30 values; preserve the original
        # four-rank vector only when it agrees at the final rank.
        if isinstance(rank_values[-1], (int, float)) and abs(float(rank_values[-1]) - float(values[0])) <= max(1.0, abs(float(values[0])) * 0.03):
            field["base"] = rank_values[-1]
        promoted.append(field)
    return promoted, groups


_ABILITY_WIKI_TITLES = {
    "/Lotus/Powersuits/Bard/Abilities/BardAmplifyAbility": "Amp (Ability)",
    "/Lotus/Powersuits/Nezha/Abilities/NezhaTrailAbility": "Fire Walker",
}

# A few legacy ability cards are not present at the same path as their power
# package. Keep the official global-client tags explicit instead of falling
# back to the English item text.
_ABILITY_LOCALIZATION_OVERRIDES = {
    "/Lotus/Powersuits/Mag/Abilities/ShieldRegenAbility": (
        "/Lotus/Language/Suits/ShieldRegenAbilityName",
        "/Lotus/Language/Suits/ShieldRegenAbilityDesc",
    ),
    "/Lotus/Powersuits/Saryn/Abilities/ExplosiveDissolveAbility": (
        "/Lotus/Language/Suits/ExplosiveDissolveAbilityName",
        "/Lotus/Language/Suits/ExplosiveDissolveAbilityDesc",
    ),
    "/Lotus/Powersuits/Trinity/Abilities/EnergyVampireAbility": (
        "/Lotus/Language/Suits/EnergyVampireAbilityName",
        "/Lotus/Language/Suits/EnergyVampireAbilityDesc",
    ),
    "/Lotus/Powersuits/Trinity/Abilities/LinkAbility": (
        "/Lotus/Language/Suits/LinkAbilityName",
        "/Lotus/Language/Suits/LinkAbilityDesc",
    ),
    "/Lotus/Powersuits/Trinity/Abilities/BlessingAbility": (
        "/Lotus/Language/Suits/BlessingAbilityName",
        "/Lotus/Language/Suits/BlessingAbilityDesc",
    ),
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraSlashDashNewAbility": (
        "/Lotus/Language/Suits/SlashDashAbilityName",
        "/Lotus/Language/Suits/SlashDashAbilityDesc",
    ),
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraRadialJavelinAbility": (
        "/Lotus/Language/Suits/RadialJavelinAbilityName",
        "/Lotus/Language/Suits/RadialJavelinAbilityDesc",
    ),
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraSwordOfDoomAbility": (
        "/Lotus/Language/Suits/SwordOfDoomAbilityName",
        "/Lotus/Language/Suits/SwordOfDoomAbilityDesc",
    ),
}

_ABILITY_SCALAR_ALIASES = {
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraSlashDashNewAbility": "/Lotus/Powersuits/Excalibur/Abilities/SlashDashNewAbility",
}

# Audited rows for abilities whose Wiki pages do not expose a conventional
# four-rank infobox vector. Values remain tied to the frozen Wiki/Packages
# evidence attached by ability_data; special mechanics stay in official text.
_ABILITY_SCALAR_SPECS = {
    "/Lotus/Powersuits/Bard/Abilities/BardAmplifyAbility": (
        ("minimum_damage_amplification", "minimum damage amplification", "最低伤害增幅", [10, 15, 20, 25], "%", "strength"),
        ("maximum_damage_amplification", "maximum damage amplification", "最高伤害增幅", [125, 150, 175, 200], "%", "strength"),
        ("duration", "duration", "持续时间", [30, 30, 30, 30], "s", "duration"),
        ("radius", "radius", "半径", [8, 10, 12, 14], "m", "range"),
        ("mallet_amplification", "Mallet amplification", "槌音增幅", [200, 200, 200, 200], "%", "strength"),
    ),
    "/Lotus/Powersuits/Cowgirl/Abilities/GunFuAbility": (
        ("damage_bonus", "damage bonus", "伤害加成", [100, 115, 133, 150], "%", "strength"),
        ("regulators_base_damage", "Regulators base damage", "监察者双枪基础伤害", [50, 50, 50, 50], "", "none"),
        ("maximum_charge_bonus", "maximum charge bonus", "满蓄力额外伤害", [150, 150, 150, 150], "%", "strength"),
        ("minimum_field_of_view", "minimum field of view", "最小视野角", [15, 15, 15, 15], "deg", "range"),
        ("range", "range", "射程", [50, 50, 50, 50], "m", "none"),
    ),
    "/Lotus/Powersuits/DemonFrame/Abilities/DemonFrameHealAbility": (
        ("healing", "healing", "治疗量", [35, 40, 45, 50], "%", "strength"),
        ("gulphagor_damage", "Gulphagor damage per hit", "苦魔每跳伤害", [750, 750, 750, 750], "", "strength"),
        ("health_orb_effect", "health orb effect", "生命球效果", [300, 300, 300, 300], "%", "none"),
        ("energy_orb_effect", "energy orb effect", "能量球效果", [100, 100, 100, 100], "%", "none"),
        ("field_damage", "field damage per 0.5 seconds", "领域每跳伤害", [200, 200, 200, 200], "", "strength"),
        ("field_duration", "field duration", "领域持续时间", [10, 10, 10, 10], "s", "duration"),
        ("field_radius", "field radius", "领域半径", [4, 4, 4, 4], "m", "range"),
    ),
    "/Lotus/Powersuits/Ember/Abilities/EmberImmolationAbility": (
        ("initial_damage_reduction", "initial damage reduction", "初始伤害减免", [10, 20, 30, 40], "%", "strength"),
        ("maximum_heat_damage_reduction", "maximum heat damage reduction", "满热量伤害减免", [50, 65, 75, 85], "%", "strength"),
        ("damage_reduction_cap", "damage reduction cap", "伤害减免硬上限", [90, 90, 90, 90], "%", "none"),
        ("energy_drain_growth", "energy drain growth", "每秒耗能增长", [0.4, 0.4, 0.4, 0.4], "E/s2", "efficiency"),
    ),
    "/Lotus/Powersuits/Excalibur/Abilities/SlashDashNewAbility": (
        ("targeting_range", "targeting range", "初始锁敌范围", [20, 20, 20, 20], "m", "range"),
        ("chain_range", "chain range", "连锁范围", [7, 7, 7, 7], "m", "range"),
        ("free_dash_speed", "free dash speed", "非锁定突进速度", [36, 36, 36, 36], "m/s", "none"),
        ("targeted_dash_speed", "targeted dash speed", "锁定突进速度", [75, 75, 75, 75], "m/s", "none"),
        ("free_dash_duration", "free dash duration", "非锁定突进时间", [0.87, 0.87, 0.87, 0.87], "s", "none"),
    ),
    "/Lotus/Powersuits/Frumentarius/Abilities/FrumentariusAmmoAbility": (
        ("extra_hit_chance", "extra hit chance", "普通武器额外命中几率", [10, 15, 20, 25], "%", "none"),
        ("sniper_extra_hit_chance", "sniper extra hit chance", "狙击武器额外命中几率", [20, 30, 40, 50], "%", "none"),
        ("package_count", "package count", "补给包数量", [2, 2, 2, 2], "", "none"),
        ("maximum_packages", "maximum packages", "场上补给包上限", [6, 6, 6, 6], "", "none"),
    ),
    "/Lotus/Powersuits/Frumentarius/Abilities/FrumentariusSniperAbility": (
        ("damage_multiplier", "damage multiplier", "伤害倍率", [1, 1.08, 1.16, 1.25], "x", "strength"),
        ("ricochet_range", "ricochet range", "弹射范围", [10, 10, 10, 10], "m", "range"),
        ("ricochets", "ricochets", "弹射次数", [4, 4, 4, 4], "", "none"),
        ("ricochet_falloff", "ricochet falloff", "每次弹射衰减", [20, 20, 20, 20], "%", "none"),
        ("primary_base_damage", "primary base damage", "主射基础伤害", [255, 255, 255, 255], "", "none"),
        ("alternate_base_damage", "alternate base damage", "副射基础伤害", [20, 20, 20, 20], "", "none"),
    ),
    "/Lotus/Powersuits/Inkblot/Abilities/InkSketchAbility": (
        ("spawn_damage", "spawn damage", "生成伤害", [250, 250, 250, 250], "", "strength"),
        ("despawn_damage", "despawn damage", "消失伤害", [250, 250, 250, 250], "", "strength"),
        ("lifetime", "lifetime", "持续时间", [20, 20, 20, 20], "s", "duration"),
        ("ink_radius", "Inkblot radius", "墨蚀半径", [4, 4, 4, 4], "m", "range"),
        ("spawn_range", "spawn range", "生成距离", [50, 50, 50, 50], "m", "range"),
    ),
    "/Lotus/Powersuits/Khora/Abilities/KhoraKavatAbility": (
        ("movement_speed_multiplier", "movement speed multiplier", "移动速度倍率", [1.05, 1.1, 1.12, 1.15], "x", "strength"),
        ("snare_damage", "Snare damage", "擒捕伤害", [350, 350, 350, 350], "", "strength"),
        ("snare_hits", "Snare hits", "擒捕攻击次数", [5, 5, 5, 5], "", "none"),
        ("healing_per_second", "healing per second", "每秒治疗", [50, 50, 50, 50], "/s", "strength"),
    ),
    "/Lotus/Powersuits/Nezha/Abilities/NezhaTrailAbility": (
        ("damage_per_second", "damage per second", "每秒伤害", [50, 100, 150, 200], "/s", "strength"),
        ("teleport_explosion_damage", "teleport explosion damage", "传送爆炸伤害", [500, 750, 1000, 1250], "", "strength"),
        ("buff_duration", "buff duration", "增益持续时间", [15, 20, 25, 30], "s", "duration"),
        ("trail_duration", "trail duration", "火痕持续时间", [5, 6, 7.5, 10], "s", "duration"),
        ("explosion_radius", "explosion radius", "爆炸半径", [3, 4, 5, 6], "m", "range"),
    ),
    "/Lotus/Powersuits/Pacifist/Abilities/PacifistDodgeAbility": (
        ("evasion_angle", "evasion angle", "闪避角度", [120, 130, 150, 180], "deg", "range"),
        ("evasion_chance", "evasion chance", "闪避率", [100, 100, 100, 100], "%", "none"),
        ("recovery_delay", "recovery delay", "恢复延迟", [0.2, 0.2, 0.2, 0.2], "s", "none"),
        ("restraint_erosion", "restraint erosion per attack", "每次攻击克制侵蚀", [1.2, 1.2, 1.2, 1.2], "%", "none"),
    ),
    "/Lotus/Powersuits/Ranger/Abilities/RangerQuiverAbility": (
        ("cloak_duration", "Cloak Arrow duration", "隐蔽之箭持续时间", [12, 12, 12, 12], "s", "duration"),
        ("cloak_radius", "Cloak Arrow radius", "隐蔽之箭半径", [2.5, 2.5, 2.5, 2.5], "m", "range"),
        ("maximum_cloak_arrows", "maximum Cloak Arrows", "隐蔽之箭上限", [3, 3, 3, 3], "", "none"),
    ),
    "/Lotus/Powersuits/Ranger/Abilities/RangerControlAbility": (
        ("maximum_damage_multiplier", "maximum damage multiplier", "最高伤害倍率", [2, 3, 4, 5], "x", "strength"),
        ("damage_growth_per_second", "damage growth per second", "每秒伤害倍率增长", [0.25, 0.5, 0.75, 1], "x/s", "duration"),
        ("base_energy_drain", "base energy drain", "基础持续耗能", [3, 3, 3, 3], "E/s", "efficiency"),
        ("energy_drain_growth", "energy drain growth", "每秒耗能增长", [2, 2, 2, 2], "E/s2", "efficiency"),
    ),
    "/Lotus/Powersuits/Temple/Abilities/TempleGuitarAbility": (
        ("damage_multiplier", "damage multiplier", "伤害倍率", [1, 1.08, 1.15, 1.25], "x", "strength"),
        ("lizzie_base_damage", "Lizzie base damage", "丽兹基础伤害", [85, 85, 85, 85], "", "none"),
        ("critical_chance", "critical chance", "暴击几率", [35, 35, 35, 35], "%", "none"),
        ("critical_multiplier", "critical multiplier", "暴击倍率", [2.3, 2.3, 2.3, 2.3], "x", "none"),
        ("status_chance", "status chance", "触发几率", [35, 35, 35, 35], "%", "none"),
        ("range", "range", "射程", [10, 10, 10, 10], "m", "none"),
        ("sound_wave_damage", "sound wave damage", "声波基础伤害", [100, 100, 100, 100], "", "none"),
    ),
    "/Lotus/Powersuits/PowersuitAbilities/HelminthHackAbility": (
        ("energy_cost", "energy cost", "能量消耗", [25, 25, 25, 25], "E", "efficiency"),
        ("automatic_hack_chance", "automatic hack chance", "下一次自动破解几率", [100, 100, 100, 100], "%", "none"),
    ),
    "/Lotus/Powersuits/PowersuitAbilities/HelminthTreasureAbility": (
        ("search_range", "search range", "探测范围", [200, 200, 200, 200], "m", "range"),
        ("spark_duration", "spark duration", "火花持续时间", [5, 5, 5, 5], "s", "none"),
        ("cooldown", "cooldown", "冷却时间", [20, 20, 20, 20], "s", "none"),
        ("energy_cost", "energy cost", "能量消耗", [50, 50, 50, 50], "E", "efficiency"),
    ),
}


def _documented_ability_scalars(unique_name: str) -> list[dict[str, Any]]:
    key = _ABILITY_SCALAR_ALIASES.get(unique_name, unique_name)
    return [
        {
            "id": scalar_id,
            "label": label_en,
            "labelEn": label_en,
            "labelZh": label_zh,
            "values": values,
            "rankCount": len(values),
            "base": values[-1],
            "unit": unit,
            "scale": scale,
            "sourceKind": "wiki-audited",
        }
        for scalar_id, label_en, label_zh, values, unit, scale in _ABILITY_SCALAR_SPECS.get(key, ())
    ]


def _scalar_scale(label: str, context: str, unit: str) -> str:
    # Classify from the field label and the small context immediately adjacent
    # to its vector.  Looking at the whole wiki line makes a damage vector pick
    # up a later unrelated ``radius``/``range`` field.
    text = f"{label} {context}".casefold()
    label_text = label.casefold()
    # Explicit field labels win over neighbouring table annotations.  For
    # example ``strength bonus`` is followed by an unrelated ``bonus
    # duration`` marker in the same infobox cell.
    if any(word in label_text for word in ("damage", "health", "shield", "armor", "armour", "heal", "strength", "bonus")):
        if not any(word in label_text for word in ("status chance", "critical chance", "crit chance")):
            return "strength"
    if unit == "s" or any(word in text for word in ("duration", "buff time", "debuff time", "seconds", "second")):
        return "duration"
    if any(word in text for word in ("range", "radius", "distance", "area", "length", "width", "radius")) or unit == "m":
        return "range"
    if any(word in text for word in ("efficiency", "energy cost", "energy drain")):
        return "efficiency"
    if any(word in text for word in ("damage", "health", "shield", "armor", "armour", "heal", "overguard", "strength", "vulnerability", "restor", "bonus")):
        if not any(word in text for word in ("status chance", "critical chance", "crit chance")):
            return "strength"
    return "none"


def _scalar_unit(label: str, line: str, tail: str) -> str:
    text = f"{label} {line} {tail}".casefold()
    if "%" in tail or "%" in label:
        return "%"
    if re.search(r"(?:^|\s)x(?:\s|$)", tail.casefold()) or re.search(r"\bx\b", label.casefold()):
        return "x"
    if re.search(r"(?:per\s+(?:sec(?:ond)?s?)|/(?:s|sec(?:ond)?s?))\b", text):
        if any(word in label.casefold() for word in ("distance", "speed", "velocity", "range", "radius", "length", "width")):
            return "m/s"
        return "/s"
    if re.search(r"(?:^|\s)(?:s|sec|secs|second|seconds)(?:\b|$)", text):
        return "s"
    if re.search(r"(?:^|\s)(?:m|meter|meters)(?:\b|$)", text):
        return "m"
    return ""


def parse_wiki_scalars(page: dict[str, Any] | None, name: str, index: WikiAbilityIndex | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse only explicit four-rank vectors; never infer missing ranks.

    Infobox/stat-table rows are preferred over prose because ability articles
    repeat the same values in their explanation paragraphs.  If a page has no
    table vector, a second pass over prose still preserves an explicit value
    rather than silently dropping the skill.
    """
    if not page:
        return [], ["wiki article unavailable in frozen snapshot"]
    text = str(page.get("text") or "")
    scalars: list[dict[str, Any]] = []
    seen: set[tuple[tuple[int | float, ...], str, str]] = set()
    lines = text.splitlines()
    table_lines = [line for line in lines if "|" in line or "misc:" in line.casefold()]
    passes = (table_lines, lines) if table_lines else (lines,)
    for current_lines in passes:
      if scalars:
          break
      for line in current_lines:
        if not "/" in line or not re.search(r"\d", line):
            continue
        # Wiki tables sometimes repeat the unit after each rank value
        # (``35% / 40% / 45% / 50%``). Normalize only the first three unit
        # suffixes so the final suffix still drives unit classification.
        line = re.sub(r"(?<=\d)\s*(%|m/s|m|s|x|°|HP|SP|EP)(?=\s*/)", "", line, flags=re.I)
        # Introduction/version prose can share an infobox row with the actual
        # rank vector (for example Shuriken's damage); only reject lines whose
        # vectors are clearly unrelated metadata.
        if any(token in line.casefold() for token in ("http://", "https://", "patch history", "rank |")):
            continue
        matches = list(_WIKI_VECTOR_RE.finditer(line))
        for position, match in enumerate(matches):
            raw_values = [piece.strip() for piece in re.split(r"\s*/\s*", match.group(0))]
            if len(raw_values) != 4:
                continue
            try:
                values = tuple(_number_value(piece) for piece in raw_values)
            except (TypeError, ValueError):
                continue
            after = line[match.end() :]
            next_match = _WIKI_VECTOR_RE.search(after)
            tail = after[: next_match.start()] if next_match else after
            labels = re.findall(r"\(([^()]{1,100})\)", tail)
            label = re.sub(r"\s+", " ", labels[0] if labels else tail).strip(" :|,-")
            if not label:
                before = line[max(0, match.start() - 70) : match.start()]
                label = re.sub(r"\s+", " ", before).strip(" :|,-")
            # Strip markdown/table noise while retaining the official field
            # wording for display and audit.
            label = re.sub(r"^[^A-Za-z%]{0,12}", "", label).strip()
            if len(label) > 80 or re.fullmatch(r"(?:s|m|%|x)", label, flags=re.I):
                label = ""
            # Restrict units to the immediate field tail; a later stat on the
            # same table row must not change this vector's classification.
            context = tail[:120]
            unit = _scalar_unit(label, context, context)
            label = label or ({"s": "duration", "m": "range", "%": "percentage"}.get(unit) or f"value {position + 1}")
            key = (values, _scalar_id(label, position), unit)
            if key in seen:
                continue
            seen.add(key)
            scalars.append({
                "id": _scalar_id(label, position),
                "label": label,
                "labelEn": label,
                "labelZh": _scalar_label_zh(label, position),
                "values": list(values),
                "rankCount": 4,
                "base": values[-1],
                "unit": unit,
                "scale": _scalar_scale(label, context, unit),
                "sourceKind": "wiki",
            })
    if scalars:
        return scalars, []
    return [], ["wiki article has no explicit four-rank numeric vector"]


def parse_wiki_misc_fields(page: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Keep explicit static ``Misc:`` values that are outside rank tables."""
    if not page:
        return []
    text = str(page.get("text") or "")
    segments = [
        line.split("Misc:", 1)[1] if "Misc:" in line else line
        for line in text.splitlines()
        if (re.search(r"Misc:", line, re.I) or re.match(r"\s*\|\s*:", line))
    ]
    result: list[dict[str, Any]] = []
    order = 0
    value_pattern = rf"(?:{_WIKI_NUMBER}(?:\s*/\s*{_WIKI_NUMBER}){{0,3}}|∞|N/A|\?)"
    # A common status-stack form has two values followed by one element list.
    stack_pattern = re.compile(rf"(?P<values>{_WIKI_NUMBER})\s+status\s+stacks?\s*/\s*(?P<second>{_WIKI_NUMBER})\s+status\s+stacks?\s*\((?P<label>[^()]*)\)", re.I)
    item_pattern = re.compile(rf"(?P<values>{value_pattern})\s*(?P<unit>%|m/s|m|s|x|°|HP|SP|EP)?\s*\((?P<label>[^()]{{2,160}})\)", re.I)
    for segment in segments:
        segment = re.sub(r"(?<=\d)\s*(%|m/s|m|s|x|°|HP|SP|EP)(?=\s*/)", "", segment, flags=re.I)
        consumed: list[tuple[int, int]] = []
        for match in stack_pattern.finditer(segment):
            values = [float(match.group("values")), float(match.group("second"))]
            label = match.group("label").strip()
            if not re.search(r"[A-Za-z]{3,}", label) or len(re.sub(r"\W", "", label)) < 4:
                label = "异常状态新增层数"
            result.append({
                "id": f"wiki_misc_{_scalar_id(label, order)}_{order}", "label": label, "labelEn": label,
                "labelZh": _overframe_label_zh(label) or "异常状态新增层数", "valueTemplate": "{} / {}", "valueKeys": ["val1", "val2"],
                "parts": {"val1": values[0], "val2": values[1]}, "values": values, "rankValues": values,
                "rankCount": 2, "base": values[-1], "unit": "", "scale": "none", "modifier": "NONE",
                "displayOrder": 1000 + order, "isStatic": True, "sourceKind": "wiki-misc",
            })
            consumed.append(match.span())
            order += 1
        for match in item_pattern.finditer(segment):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            raw_values = match.group("values")
            label = re.sub(r"\s+", " ", match.group("label")).strip(" :|,-")
            if not label or re.search(r"(?:introduced|update\s+\d|rank\s*\|)", label, re.I):
                continue
            unit = match.group("unit") or ""
            display_value = None
            if raw_values in {"∞", "N/A", "?"}:
                values: list[int | float] = []
                display_value = raw_values
            else:
                try:
                    values = [_number_value(piece.strip()) for piece in re.split(r"\s*/\s*", raw_values)]
                except (TypeError, ValueError):
                    continue
            result.append({
                "id": f"wiki_misc_{_scalar_id(label, order)}_{order}", "label": label, "labelEn": label,
                "labelZh": _overframe_label_zh(label), "valueTemplate": ("{}" if len(values) <= 1 else " / ".join("{}" for _ in values)) + unit,
                "valueKeys": [f"val{index + 1}" for index in range(len(values))],
                "parts": {f"val{index + 1}": value for index, value in enumerate(values)},
                "values": values, "rankValues": values if len(values) == 4 else ([values[-1]] * 4 if values else []),
                "rankCount": 4 if values else 0, "base": values[-1] if values else None, "unit": unit,
                "scale": "none", "modifier": "NONE", "displayOrder": 1000 + order, "isStatic": True,
                "displayValue": display_value, "sourceKind": "wiki-misc",
            })
            order += 1
    return result


def merge_ability_fields(primary: list[dict[str, Any]], extras: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = list(primary)
    seen = {(str(row.get("label") or "").casefold(), row.get("base"), row.get("unit")) for row in result if isinstance(row, dict)}
    for row in extras:
        key = (str(row.get("label") or "").casefold(), row.get("base"), row.get("unit"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def parse_helminth_aggregate_scalars(page: dict[str, Any] | None, ordinal: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse one native ability row from the frozen aggregate Helminth table.

    The table is ordered exactly as the 13 native recipes.  Splitting on the
    explicit ``Subsumable to Helminth`` marker keeps values from neighbouring
    abilities from leaking into one another, while retaining the original
    line text for provenance/debugging.
    """
    if not page:
        return [], ["Helminth aggregate article unavailable in frozen snapshot"]
    text = str(page.get("text") or "")
    # The cleaner stores a markdown row as ``| Subsumable ...`` without a
    # leading newline in a few snapshots; anchor only at the row boundary.
    blocks = re.split(r"(?:^|\n)\s*\|\s*Subsumable to Helminth[^\n]*", text, flags=re.I)
    if ordinal < 0 or ordinal >= len(blocks) - 1:
        return [], [f"native Helminth table ordinal {ordinal} is unavailable"]
    block = blocks[ordinal]
    # The first block includes the article heading; each later block begins
    # immediately after the previous marker.  Feed it through the same strict
    # four-value parser used by direct skill pages.
    return parse_wiki_scalars({"title": page.get("title"), "text": block}, f"Helminth native {ordinal}")


def package_ability_evidence(raw_root: Path, unique_name: str) -> dict[str, Any]:
    path = raw_path(raw_root, unique_name)
    evidence: dict[str, Any] = {
        "kind": "packages",
        "path": "/" + path.relative_to(raw_root).with_suffix("").as_posix() if path.is_relative_to(raw_root) else unique_name,
        "available": path.is_file(),
    }
    if not path.is_file():
        return evidence
    try:
        payload = load(path)
    except (OSError, UnicodeError, json.JSONDecodeError):
        evidence["available"] = False
        return evidence
    fields: list[str] = []
    if isinstance(payload.get("EnergyRequiredToActivate"), (int, float)):
        fields.append("EnergyRequiredToActivate")
    script = payload.get("Script")
    if isinstance(script, dict):
        for key, value in script.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                fields.append(f"Script.{key}")
    if fields:
        evidence["numericFields"] = fields[:32]
    if payload.get("UniquePowerIdentifier"):
        evidence["uniquePowerIdentifier"] = payload["UniquePowerIdentifier"]
    return evidence


def ability_energy_cost(raw_root: Path, unique_name: str, page: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Read explicit activation/drain costs without guessing dynamic resources."""
    audited = _ABILITY_COST_SPECS.get(unique_name)
    if audited:
        result = {key: value for key, value in audited.items() if key != "activation" or float(value) > 0}
        return {**result, "sourceKind": "wiki-audited"}
    raw = raw_json(raw_root, unique_name)
    activation = raw.get("EnergyRequiredToActivate")
    drain = raw.get("EnergyConsumptionOverTime")
    activation = float(activation) if isinstance(activation, (int, float)) else None
    drain = float(drain) if isinstance(drain, (int, float)) else None
    text = str((page or {}).get("text") or "")
    # Prose is safer than a broad infobox scan: it normally names the cost
    # directly and avoids mistaking an energy-orb reward for cast cost.
    if activation is None or activation <= 0:
        match = re.search(r"(?:expends?|consumes?|costs?)\s+(\d+(?:\.\d+)?)\s*(?:\u003c[^>]+\u003e\s*)?(?:energy|power)\b", text, re.I)
        if match:
            activation = float(match.group(1))
    if drain is None or drain <= 0:
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:energy|power)\s*(?:per|/)\s*(?:second|sec|s)\b", text, re.I)
        if match:
            drain = float(match.group(1))
    if activation is not None and activation <= 0:
        activation = None
    if drain is not None and drain <= 0:
        drain = None
    if activation is None and drain is None:
        return None
    result: dict[str, Any] = {}
    if activation is not None:
        result["activation"] = int(activation) if activation.is_integer() else activation
    if drain is not None:
        result["drainPerSecond"] = int(drain) if drain.is_integer() else drain
    result["resource"] = "energy"
    result["sourceKind"] = "packages" if raw.get("EnergyRequiredToActivate") or raw.get("EnergyConsumptionOverTime") else "wiki"
    return result


def ability_wiki_page(display_name: str, unique_name: str, wiki: WikiAbilityIndex | None) -> dict[str, Any] | None:
    if not wiki:
        return None
    title = _ABILITY_WIKI_TITLES.get(unique_name, display_name)
    return wiki.page(title) if unique_name in _ABILITY_WIKI_TITLES else wiki.lookup(title)


def ability_data(raw_root: Path, unique_name: str, display_name: str, wiki: WikiAbilityIndex | None) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], list[str]]:
    page = ability_wiki_page(display_name, unique_name, wiki)
    scalars = _documented_ability_scalars(unique_name)
    unresolved = []
    if not scalars:
        scalars, unresolved = parse_wiki_scalars(page, display_name, wiki)
    scalars = merge_ability_fields(scalars, parse_wiki_misc_fields(page))
    evidence = [package_ability_evidence(raw_root, unique_name)]
    if page and wiki:
        evidence.insert(0, wiki.evidence(page, name=display_name))
    if scalars:
        # The parser only accepts explicit rank vectors.  Dynamic/conditional
        # mechanics stay visible as a diagnostic instead of being guessed.
        support = "partial" if unresolved else "full"
        return scalars, support, evidence, unresolved
    package = evidence[-1]
    if package.get("numericFields"):
        unresolved = [*unresolved, "package constants are not rank-scaled player-facing values"]
        return [], "text-only", evidence, unresolved
    return [], "text-only", evidence, unresolved or ["no structured numeric source in frozen snapshot"]


def helminth_override_data(raw_root: Path, ability_path: str, display_name: str, wiki: WikiAbilityIndex | None, *, ordinal: int | None = None) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]], list[str], str | None]:
    """Collect native or overridden Helminth values with explicit provenance."""
    page = wiki.lookup(display_name) if wiki else None
    scalars = _documented_ability_scalars(ability_path)
    unresolved = []
    if not scalars:
        scalars, unresolved = parse_wiki_scalars(page, display_name, wiki)
    scalars = merge_ability_fields(scalars, parse_wiki_misc_fields(page))
    evidence: list[dict[str, Any]] = []
    if page and wiki:
        evidence.append(wiki.evidence(page, name=display_name))
    # Native direct articles for a few abilities are represented by unrelated
    # augment pages in the pilot snapshot.  Fall back to the ordered aggregate
    # table only when the direct page has no rank vector.
    aggregate_name = "Helminth/Unique Abilities"
    aggregate = wiki.page(aggregate_name) if wiki else None
    if not scalars and ordinal is not None and aggregate:
        aggregate_scalars, aggregate_unresolved = parse_helminth_aggregate_scalars(aggregate, ordinal)
        if aggregate_scalars:
            scalars = aggregate_scalars
            unresolved = aggregate_unresolved
            evidence.insert(0, wiki.evidence(aggregate, name=aggregate_name))
            scalars = merge_ability_fields(scalars, parse_wiki_misc_fields(page))
    evidence.append(package_ability_evidence(raw_root, ability_path))
    if scalars:
        return scalars, "full", evidence, unresolved, (str(page.get("title")) if page else aggregate_name)
    package = evidence[-1]
    if package.get("numericFields"):
        unresolved = [*unresolved, "package constants are not rank-scaled player-facing values"]
    return [], "text-only", evidence, unresolved or ["no structured numeric source in frozen snapshot"], (str(page.get("title")) if page else None)


HELMINTH_WIKI_NAMES = {
    "HelminthStrength": "Empower",
    "HelminthSpeed": "Infested Mobility",
    "HelminthCompanion": "Master's Summons",
    "HelminthShields": "Rebuild Shields",
    "HelminthHack": "Perspicacity",
    "HelminthEfficiency": "Energized Munitions",
    "HelminthStun": "Marked For Death",
    "HelminthStatus": "Expedite Suffering",
    "HelminthShieldArmor": "Parasitic Armor",
    "HelminthProcBlock": "Hideous Resistance",
    # Public article is Energy Transfer; Energy Siphon is a MOD and must not
    # be used as the native Helminth fallback source.
    "HelminthEnergyShare": "Energy Transfer",
    "HelminthMaxStatus": "Sickening Pulse",
    "HelminthTreasure": "Golden Instinct",
}

# Order of the native entries in ``Helminth/Unique Abilities``.  Recipe files
# are alphabetically sorted and therefore cannot be used as the table ordinal.
HELMINTH_NATIVE_ORDER = {
    "HelminthStrength": 0,
    "HelminthSpeed": 1,
    "HelminthCompanion": 2,
    "HelminthShields": 3,
    "HelminthHack": 4,
    "HelminthEfficiency": 5,
    "HelminthStun": 6,
    "HelminthStatus": 7,
    "HelminthShieldArmor": 8,
    "HelminthProcBlock": 9,
    "HelminthEnergyShare": 10,
    "HelminthMaxStatus": 11,
    "HelminthTreasure": 12,
}

# Audited non-standard costs from the frozen Wiki pages. Package value ``0``
# is overloaded for cooldowns, alternate resources and per-target costs, so it
# must never be presented as "free" without this public gameplay context.
_ABILITY_COST_SPECS = {
    "/Lotus/Powersuits/Alchemist/Abilities/AlchemistSerpentAbility": {"resource": "cooldown", "cooldownSeconds": 8},
    "/Lotus/Powersuits/Alchemist/Abilities/AlchemistVialAbility": {"resource": "cooldown", "cooldownSeconds": 5},
    "/Lotus/Powersuits/Alchemist/Abilities/AlchemistTransmuteAbility": {"resource": "cooldown", "cooldownSeconds": 10},
    "/Lotus/Powersuits/Alchemist/Abilities/AlchemistDistillAbility": {"resource": "cooldown", "cooldownSeconds": 30},
    "/Lotus/Powersuits/BrokenFrame/Abilities/BrokenRotAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/Devourer/Abilities/DevourerBowlAbility": {"resource": "energy", "activation": 0, "drainPerSecond": 3, "noteZh": "空腹时持续消耗"},
    "/Lotus/Powersuits/Ember/Abilities/EmberInfernoAbility": {"resource": "energy", "perTarget": 10, "targetCap": 10},
    "/Lotus/Powersuits/Garuda/Abilities/GarudaBloodAbility": {"resource": "health", "maximumHealthPercent": 50, "minimumRemaining": 2},
    "/Lotus/Powersuits/Infestation/Abilities/InfestLinkAbility": {"resource": "mutation", "stacks": 1},
    "/Lotus/Powersuits/Infestation/Abilities/InfestPodsAbility": {"resource": "mutation", "stacks": 3},
    "/Lotus/Powersuits/IronFrame/Abilities/IronFrameBlastAbility": {"resource": "shield", "activation": 50, "perShot": 100, "chargedShot": 200},
    "/Lotus/Powersuits/IronFrame/Abilities/IronFrameStripAbility": {"resource": "shield", "activation": 150},
    "/Lotus/Powersuits/IronFrame/Abilities/IronFrameAuraAbility": {"resource": "shield", "activation": 250, "perAllyPerSecond": 5, "perEnemyPerSecond": 25},
    "/Lotus/Powersuits/IronFrame/Abilities/IronFrameEruptionAbility": {"resource": "shield", "activation": 100, "drainPerSecond": 25, "perEnemyPerSecond": 25, "perDodge": 50},
    "/Lotus/Powersuits/Khora/Abilities/KhoraKavatAbility": {"resource": "energy", "activation": 25, "reviveMaximum": 50, "noteZh": "切换姿态不消耗能量；复活消耗随剩余复活时间变化"},
    "/Lotus/Powersuits/Magician/Abilities/BanishAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/MonkeyKing/Abilities/MonkeyCloudAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/Ninja/Abilities/TeleportToAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/Ninja/Abilities/NinjaStormAbility": {"resource": "energy", "perTarget": 12, "discountPercent": 50, "noteZh": "隐身时每个标记的消耗减半"},
    "/Lotus/Powersuits/Pacifist/Abilities/PacifistFistAbility": {"resource": "restraint", "restoreOnActivationPercent": 4, "restorePerSecondPercent": 0.8},
    "/Lotus/Powersuits/Priest/Abilities/PriestRavageAbility": {"resource": "energy", "activation": 25, "variableChannel": True},
    "/Lotus/Powersuits/Sandman/Abilities/SandmanStormAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/Sandman/Abilities/SandmanArmorAbility": {"resource": "health", "perChargePercent": 25, "maximumTotal": 2500, "minimumRemaining": 2},
    "/Lotus/Powersuits/Tengu/Abilities/TailWindAbility": {"resource": "energy", "activation": 25, "airborneActivation": 12.5},
    "/Lotus/Powersuits/Wisp/Abilities/WispReservoirAbility": {"resource": "energy", "activation": 25},
    "/Lotus/Powersuits/Wraith/Abilities/WraithReaperAbility": {"resource": "deathWell", "requiredPercent": 75, "drainPerSecondPercent": 1},
}


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the frozen Warframe build sidecar")
    parser.add_argument("--build", default=BUILD)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True)
    parser.add_argument("--localization", type=Path, required=True)
    parser.add_argument("--rabbit-assets", type=Path, required=True)
    parser.add_argument("--rabbit-mods", type=Path, required=True)
    parser.add_argument("--wiki", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    result = parser.parse_args()
    result.export_dir = result.export_dir or ROOT / "data" / "export" / result.build
    return result


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(path: Path) -> list[dict[str, Any]]:
    payload = load(path)
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return payload if isinstance(payload, list) else []


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def raw_path(root: Path, unique_name: str) -> Path:
    return root.joinpath(*PurePosixPath(unique_name.lstrip("/")).parts).with_suffix(".json")


def raw_json(root: Path, unique_name: str) -> dict[str, Any]:
    path = raw_path(root, unique_name)
    return load(path) if path.is_file() else {}


def localized(localization: dict[str, str], tag: Any, fallback: str = "") -> str:
    tag = str(tag or "").strip()
    if tag and not tag.startswith("[HC]"):
        return str(localization.get(tag) or fallback or "").strip()
    return str(fallback or tag).strip()


def clean_official_text(value: Any) -> str:
    """Remove renderer markers while retaining the official wording.

    Languages.bin uses angle-bracket tokens for color/ordering hints (for
    example ``<LOWER_IS_BETTER>`` and ``<DT_FIRE_COLOR>``).  They are not
    part of the card text and leaking them to the UI produces literal engine
    diagnostics.  Pipe placeholders such as ``|STAT1|`` are intentionally
    retained: they carry an official value slot which is filled separately by
    the set-effect renderer.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    # Remove angle-bracket renderer markers while retaining their payload.
    # ``<DT_FIRE_COLOR>`` and ``<LOWER_IS_BETTER>`` are both non-semantic
    # display hints; the official Chinese words/numbers around them remain.
    text = re.sub(r"</?[A-Za-z][^>]*>", "", text)
    text = text.replace("|OPEN_COLOR|", "").replace("|CLOSE_COLOR|", "")
    return text.strip()


def localized_global_frame_name(localization: dict[str, str], tag: Any, fallback: str = "") -> str:
    """Resolve a global-client frame name while retaining a usable fallback.

    The international language cache intentionally leaves many frame names as
    their canonical English names (for example ``Ash``), so an English value
    here is a successful localization, not a missing translation.
    """
    return localized(localization, tag, fallback)


def localized_stats(i18n: dict[str, Any], path: str, fallback: Iterable[dict[str, Any]]) -> list[list[str]]:
    entry = i18n.get(path) if isinstance(i18n.get(path), dict) else {}
    zh = entry.get("zh") if isinstance(entry.get("zh"), dict) else {}
    levels = zh.get("levelStats") if isinstance(zh.get("levelStats"), list) else fallback
    def clean(line: Any) -> str:
        value = str(line or "").strip()
        # A few frozen zh levelStats rows accidentally concatenate the English
        # sentence after a complete Chinese sentence. Keep official Chinese
        # text and remove only that trailing fallback fragment.
        value = re.sub(r"(?<=[\u3002\uff01\uff1f])\s*[A-Z][A-Za-z][^\r\n]*$", "", value).strip()
        return clean_official_text(value)
    return [[clean(line) for line in level.get("stats") or []] for level in levels or [] if isinstance(level, dict)]


def render_effect_text(template: str, effects: Iterable[dict[str, Any]]) -> str:
    values = []
    for effect in effects:
        value = effect.get("value")
        if not isinstance(value, (int, float)):
            continue
        if effect.get("displayAsPercent"):
            value *= 100
        values.append(f"{value:g}")
    index = 0
    def replace(_match: re.Match[str]) -> str:
        nonlocal index
        value = values[min(index, len(values) - 1)] if values else ""
        index += 1
        return value
    return re.sub(r"\|val\d*\|", replace, str(template or ""), flags=re.I).replace("|OPEN_COLOR|", "").replace("|CLOSE_COLOR|", "").strip()


def polarity(value: Any) -> str | None:
    if isinstance(value, list):
        value = next((item for item in reversed(value) if str(item).casefold() in POLARITIES), None)
    value = str(value or "").strip()
    if not value or value.upper() in {"AP_NONE", "AP_UNIVERSAL", "NONE"}:
        return None
    return POLARITIES.get(value.casefold(), value.upper())


def explicit_frame_slots(source: dict[str, Any], item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split the collector's documented Warframe slot vector and audit its semantics."""
    vector = source.get("polarities")
    if not isinstance(vector, list) or len(vector) < 12:
        raise RuntimeError(f"{source.get('path') or source.get('nameEn')} has no complete 12-slot polarity vector")
    normal = [polarity(value) for value in vector[:8]]
    aura = polarity(vector[8])
    exilus = polarity(vector[9])
    def comparable_item_polarity(value: Any) -> str | None:
        values = value if isinstance(value, list) else [value]
        known = [entry for entry in values if str(entry or "").casefold() in POLARITIES]
        return polarity(known) if known else None

    item_aura = comparable_item_polarity(item.get("aura"))
    item_exilus = comparable_item_polarity(item.get("exilusPolarity"))
    if (item_aura is not None and item_aura != aura) or (item_exilus is not None and item_exilus != exilus):
        raise RuntimeError(
            f"{source.get('path')} slot semantics disagree with WarframeItems: "
            f"collector=({aura!r},{exilus!r}) items=({item_aura!r},{item_exilus!r})"
        )
    return (
        {"aura": aura, "exilus": exilus, "normal": normal},
        {
            "path": source.get("path"),
            "source": source.get("_slotVectorSource") or "frozen-export.warframes[].polarities",
            "semantics": {"normal": [0, 8], "aura": 8, "exilus": 9, "reserved": [10, 12]},
            "validatedAgainst": "warframe-items aura/exilusPolarity" if item_aura is not None or item_exilus is not None else "unavailable",
        },
    )


def provenance(meta: dict[str, Any]) -> dict[str, Any]:
    result = {
        "sourceRevision": meta["buildLabel"],
        "sourceUrl": meta["sourceUrl"],
        "fetchedAt": meta["fetchedAt"],
        "officialExportVersion": meta["buildLabel"],
        "parserHash": meta["parserHash"],
        "localizationHash": meta["localizationHash"],
    }
    if meta.get("localizationSource"):
        result["localizationSource"] = meta["localizationSource"]
    return result


def effect_rows(raw: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for effect in raw or ():
        if not isinstance(effect, dict):
            continue
        upgrade_type = effect.get("UpgradeType") or effect.get("upgradeType")
        row = {
            "upgradeType": upgrade_type,
            "stat": STAT_ALIASES.get(str(upgrade_type or "")),
            "operation": effect.get("OperationType") or effect.get("operation") or "ADD",
        }
        if isinstance(effect.get("Value"), (int, float)):
            row["value"] = effect["Value"]
        if isinstance(effect.get("valuePerRank"), (int, float)):
            row["valuePerRank"] = effect["valuePerRank"]
        if effect.get("LocTag"):
            row["descriptionTag"] = effect["LocTag"]
        if effect.get("DisplayAsPercent") is not None:
            row["displayAsPercent"] = bool(effect["DisplayAsPercent"])
        result.append({key: value for key, value in row.items() if value is not None})
    return result


def set_shell_metadata(
    mod_set: str | None,
    shells: dict[str, dict[str, Any]],
    localization: dict[str, str],
) -> dict[str, Any]:
    """Flatten one exported set shell onto every selectable member card.

    The simulator still consumes the original ``modSet``/``modSetValues``
    fields.  These extra fields are display-only and make the complete set
    effect available even when the non-selectable shell is filtered out.
    """
    key = str(mod_set or "").strip()
    shell = shells.get(key)
    if not key or not shell:
        return {}
    effects = list(shell.get("effects") or ())
    conditional = list(shell.get("conditionalEffects") or ())
    runtime = deepcopy(shell.get("runtimeScripts") or {})
    desc_tag = shell.get("setDescriptionTag")
    desc = clean_official_text(localized(localization, desc_tag, "")) if desc_tag else ""
    name_tag = shell.get("setNameTag")
    name = clean_official_text(localized(localization, name_tag, "")) if name_tag else ""
    stats: list[dict[str, Any]] = []
    for effect in effects:
        if not isinstance(effect, dict):
            continue
        row = {key: value for key, value in effect.items() if key in {"upgradeType", "stat", "operation", "value", "valuePerRank", "displayAsPercent", "descriptionTag"}}
        if row.get("upgradeType") == "NONE" and not row.get("descriptionTag"):
            # Runtime-only shell placeholder, never a user-facing effect.
            continue
        stats.append(row)
    for cond in conditional:
        if not isinstance(cond, dict):
            continue
        for effect in cond.get("effects") or ():
            if not isinstance(effect, dict):
                continue
            row = {key: value for key, value in effect.items() if key in {"upgradeType", "stat", "operation", "value", "valuePerRank", "displayAsPercent", "descriptionTag"}}
            if cond.get("maxStacks") is not None:
                row["maxStacks"] = cond.get("maxStacks")
            if cond.get("duration") is not None:
                row["duration"] = cond.get("duration")
            if row.get("upgradeType") == "NONE" and not row.get("descriptionTag"):
                continue
            stats.append(row)
    # ``setStats`` is display data; omit shell placeholders with no actual
    # stat, while retaining the full conditional payload separately.
    stats = [row for row in stats if str(row.get("upgradeType") or "").upper() != "NONE" or row.get("descriptionTag")]
    # Preserve the shell's full conditional payload for consumers that need to
    # show/diagnose a non-numeric set bonus, while filtering only the synthetic
    # empty ``NONE`` row from the concise display summary above.
    # A shell with no public name (the game uses ``EmptyArtifact`` internally)
    # still needs a stable user-facing label.  Prefer the language dump and
    # fall back to the first member family supplied by the generator.
    fallback_name = str(shell.get("setNameFallback") or SET_SHELL_NAMES.get(str(mod_set or "")) or "").strip()
    if not name:
        name = fallback_name or str(shell.get("nameZh") or "").strip()
        if name in {"未融合过的神器", "MechaSetMod", "StrainSetMod", "TekSetMod"}:
            name = ""
    return {
        "setMaxPieces": shell.get("setPieces"),
        "setName": name or None,
        "setDescription": desc or None,
        "setDesc": desc or None,
        "setDescriptionTag": desc_tag or None,
        "setNameTag": name_tag or None,
        "setEffects": stats,
        "setStats": stats,
        "setConditionalEffects": conditional,
        "setDisplayValues": deepcopy(SET_DISPLAY_VALUES.get(key) or {}),
        "setRuntime": runtime,
        "setSource": shell.get("path") or shell.get("nameInternal"),
        "source": shell.get("path") or shell.get("nameInternal"),
    }


def _compact_set_effect(effect: dict[str, Any], *, condition: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep only serializable, user-relevant shell effect fields."""
    keys = {"upgradeType", "stat", "operation", "value", "valuePerRank", "displayAsPercent", "descriptionTag"}
    row = {key: effect.get(key) for key in keys if effect.get(key) is not None}
    if condition:
        for key in ("maxStacks", "duration"):
            if condition.get(key) is not None:
                row[key] = condition[key]
    return row


def _set_shell_text_tags(set_id: str) -> tuple[str | None, str | None]:
    """Return (name tag, description tag) for the public set entry."""
    return SET_SHELL_TEXT.get(set_id, (None, None))


def build_mod_set_catalog(export_mods: list[dict[str, Any]], localization: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Freeze every set shell once so both Warframe and weapon rows can use it."""
    result: dict[str, dict[str, Any]] = {}
    for source in export_mods:
        set_id = str(source.get("modSet") or "").strip()
        if not set_id or not isinstance(source.get("setPieces"), int):
            continue
        name_tag, description_tag = _set_shell_text_tags(set_id)
        effects = [_compact_set_effect(effect) for effect in source.get("effects") or () if isinstance(effect, dict)]
        conditional = []
        for cond in source.get("conditionalEffects") or ():
            if not isinstance(cond, dict):
                continue
            for effect in cond.get("effects") or ():
                if isinstance(effect, dict):
                    conditional.append(_compact_set_effect(effect, condition=cond))
        effects = [row for row in effects if str(row.get("upgradeType") or "").upper() != "NONE" or row.get("descriptionTag")]
        conditional = [row for row in conditional if str(row.get("upgradeType") or "").upper() != "NONE" or row.get("descriptionTag")]
        # Keep the complete shell payload, including runtime/conditional data;
        # the UI can show it even when the numeric engine intentionally skips it.
        result[set_id] = {
            "id": set_id,
            "nameEn": SET_SHELL_NAMES.get(set_id) or source.get("nameEn") or set_id,
            "nameZh": SET_SHELL_NAMES.get(set_id) or clean_official_text(source.get("nameZh")) or set_id,
            "maxPieces": source.get("setPieces"),
            "nameTag": name_tag,
            "descriptionTag": description_tag,
            "name": clean_official_text(localized(localization, name_tag, "")) if name_tag else SET_SHELL_NAMES.get(set_id),
            "description": clean_official_text(localized(localization, description_tag, "")) if description_tag else "",
            "effects": effects,
            "conditionalEffects": conditional,
            "displayValues": deepcopy(SET_DISPLAY_VALUES.get(set_id) or {}),
            "runtime": deepcopy(source.get("runtimeScripts") or {}),
            "sourcePath": source.get("path") or source.get("nameInternal"),
            "modSetValues": list(source.get("modSetValues") or ()),
        }
        result[set_id]["setDesc"] = result[set_id]["description"]
        result[set_id]["setStats"] = result[set_id]["effects"]
        result[set_id]["source"] = result[set_id]["sourcePath"]
    return result


def copy_asset(source: Path, target: Path, missing: list[str]) -> str | None:
    if not source.is_file():
        missing.append(str(source))
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return "/" + target.relative_to(ROOT / "frontend").as_posix()


def copy_item_asset(image_root: Path, name: Any, target_dir: Path, missing: list[str]) -> str | None:
    name = Path(str(name or "")).name
    if not name:
        return None
    return copy_asset(image_root / name, target_dir / name, missing)


def rank_growth(raw_root: Path, frame_path: str) -> tuple[dict[str, float], str]:
    frame_file = raw_path(raw_root, frame_path)
    candidates = [frame_file]
    if frame_file.parent.is_dir():
        candidates.extend(sorted(frame_file.parent.glob("*BaseSuit.json")))
    candidates.append(raw_path(raw_root, "/Lotus/Types/Game/PowerSuits/PlayerPowerSuit"))
    for candidate in candidates:
        if not candidate.is_file():
            continue
        payload = load(candidate)
        upgrades = payload.get("LevelUpgrades")
        if not isinstance(upgrades, list) or not upgrades:
            continue
        growth: dict[str, float] = {}
        for upgrade in upgrades:
            stat = STAT_ALIASES.get(str(upgrade.get("UpgradeType") or ""))
            value = upgrade.get("Value")
            if stat and isinstance(value, (int, float)):
                growth[stat] = growth.get(stat, 0.0) + float(value)
        return growth, "/" + candidate.relative_to(raw_root).with_suffix("").as_posix()
    return {}, ""


def ability_record(raw_root: Path, image_root: Path, localization: dict[str, str], item: dict[str, Any], slot: int, meta: dict[str, Any], missing: list[str], wiki: WikiAbilityIndex | None = None) -> dict[str, Any]:
    unique_name = str(item.get("uniqueName") or "")
    store = raw_json(raw_root, "/Lotus/StoreItems" + unique_name.removeprefix("/Lotus"))
    raw = raw_json(raw_root, unique_name)
    override_name_tag, override_desc_tag = _ABILITY_LOCALIZATION_OVERRIDES.get(unique_name, (None, None))
    name_tag = store.get("LocalizeTag") or raw.get("LocalizeTag") or override_name_tag
    desc_tag = store.get("LocalizeDescTag") or raw.get("LocalizeDescTag") or override_desc_tag
    icon_name = item.get("imageName") or Path(str(store.get("Icon") or "")).name
    icon = copy_item_asset(image_root, icon_name, ASSET_ROOT / "abilities", missing)
    display_name = str(item.get("name") or Path(unique_name).name)
    scalars, support_level, source_evidence, unresolved = ability_data(raw_root, unique_name, display_name, wiki)
    scalars, scalar_groups = _merge_overframe_fields(unique_name, scalars, localized(localization, name_tag, display_name))
    overframe_evidence = overframe_ability_evidence(unique_name)
    if overframe_evidence:
        source_evidence.append(overframe_evidence)
    energy_cost = _merge_overframe_energy_cost(ability_energy_cost(raw_root, unique_name, ability_wiki_page(display_name, unique_name, wiki)), scalars)
    row = {
        "id": unique_name,
        "path": unique_name,
        "slot": slot,
        "nameEn": item.get("name") or Path(unique_name).name,
        "nameZh": localized(localization, name_tag, item.get("name") or ""),
        "description": localized(localization, desc_tag, item.get("description") or ""),
        "descriptionEn": item.get("description") or "",
        "nameTag": name_tag,
        "descriptionTag": desc_tag,
        "iconAsset": icon,
        "energyCost": energy_cost,
        "scalars": scalars,
        "scalarGroups": scalar_groups,
        "supportLevel": support_level,
        "sourceEvidence": source_evidence,
        "unresolvedFields": unresolved,
        "validForCalculation": bool(scalars),
        **provenance(meta),
    }
    return row


def fill_ability_localization(abilities: list[dict[str, Any]]) -> None:
    localized_by_name = {
        str(row.get("nameEn") or "").casefold(): row
        for row in abilities
        if re.search(r"[\u3400-\u9fff]", str(row.get("nameZh") or ""))
        and re.search(r"[\u3400-\u9fff]", str(row.get("description") or ""))
    }
    for row in abilities:
        source = localized_by_name.get(str(row.get("nameEn") or "").casefold())
        if not source:
            continue
        changed = False
        if not re.search(r"[\u3400-\u9fff]", str(row.get("nameZh") or "")):
            row["nameZh"] = source["nameZh"]
            changed = True
        if not re.search(r"[\u3400-\u9fff]", str(row.get("description") or "")):
            row["description"] = source["description"]
            changed = True
        if changed:
            row["localizationFallbackSource"] = source["id"]


def canonicalize_abilities(abilities: list[dict[str, Any]]) -> dict[str, Any]:
    """Inherit the richest frozen scalar record across duplicate frame rows.

    Prime/variant frames reference the same ability path, while localization
    mirrors occasionally make one row less complete than another.  Keep every
    frame reference but make the canonical source and any inherited values
    explicit for auditability.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in abilities:
        key = str(row.get("id") or row.get("path") or "")
        groups.setdefault(key, []).append(row)
    inherited = 0
    wiki_backed = 0
    package_backed = 0
    text_only = 0
    unresolved = 0
    for key, rows_for_id in groups.items():
        canonical = max(
            rows_for_id,
            key=lambda row: (
                len(row.get("scalars") or ()),
                1 if row.get("supportLevel") == "full" else 0,
                len(row.get("sourceEvidence") or ()),
            ),
        )
        canonical_source = str(canonical.get("id") or key)
        for row in rows_for_id:
            row["canonicalId"] = key
            row["canonicalSource"] = canonical_source
            if not row.get("scalars") and canonical.get("scalars"):
                row["scalars"] = deepcopy(canonical["scalars"])
                row["supportLevel"] = canonical.get("supportLevel") or "partial"
                row["validForCalculation"] = True
                inherited += 1
                evidence = list(row.get("sourceEvidence") or [])
                evidence.append({"kind": "inherited", "sourceAbilityId": canonical_source})
                row["sourceEvidence"] = evidence
                row["unresolvedFields"] = list(canonical.get("unresolvedFields") or ())
            if not row.get("energyCost") and canonical.get("energyCost"):
                row["energyCost"] = deepcopy(canonical["energyCost"])
            if not row.get("scalarGroups") and canonical.get("scalarGroups"):
                row["scalarGroups"] = deepcopy(canonical["scalarGroups"])
        if any((row.get("scalars") or ()) for row in rows_for_id):
            wiki_backed += 1
        else:
            text_only += 1
        unresolved += sum(1 for row in rows_for_id if row.get("unresolvedFields"))
        if any(any(str(e.get("kind")) == "packages" and e.get("available") for e in row.get("sourceEvidence") or ()) for row in rows_for_id):
            package_backed += 1
    return {
        "uniqueIds": len(groups),
        "rowCount": len(abilities),
        "inheritedRows": inherited,
        "structuredIds": wiki_backed,
        "textOnlyIds": text_only,
        "packageBackedIds": package_backed,
        "rowsWithUnresolvedFields": unresolved,
    }


def _ensure_ability_contract(rows: Iterable[dict[str, Any]]) -> None:
    """Normalize records consumed by both the API and the picker UI."""
    for row in rows:
        row.setdefault("scalars", [])
        row.setdefault("supportLevel", "full" if row.get("scalars") else "text-only")
        row.setdefault("sourceEvidence", [])
        row.setdefault("unresolvedFields", [])
        row.setdefault("energyCost", None)
        row.setdefault("scalarGroups", [])
        row["validForCalculation"] = bool(row.get("scalars"))


def build_frames(export_frames: list[dict[str, Any]], item_frames: list[dict[str, Any]], raw_root: Path, image_root: Path, localization: dict[str, str], meta: dict[str, Any], missing: list[str], wiki: WikiAbilityIndex | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    by_path = {row.get("uniqueName"): row for row in item_frames if row.get("type") == "Warframe" and row.get("category") == "Warframes"}
    export_by_path = {row.get("path"): row for row in export_frames}
    source_rejected = []
    selected = []
    for source in export_frames:
        path = str(source.get("path") or "")
        item = by_path.get(path)
        reason = None
        if not item:
            reason = "unmatched NPC/template/DarkExcalibur"
        elif "/EntratiMech/" in path:
            reason = "EntratiMech is not a Warframe"
        if reason:
            source_rejected.append({"path": path, "name": source.get("nameEn"), "reason": reason})
        else:
            selected.append((source, item))
    # The frozen suit collector currently exports Sirius but misses the playable
    # Orion half.  WarframeItems is a frozen source from the same build family.
    for item in item_frames:
        path = str(item.get("uniqueName") or "")
        if path not in export_by_path and path == "/Lotus/Powersuits/SiriusOrion/OrionSuit":
            sibling = export_by_path["/Lotus/Powersuits/SiriusOrion/SiriusSuit"]
            base_suit = raw_json(raw_root, "/Lotus/Powersuits/SiriusOrion/OrionBaseSuit")
            source = {
                **sibling,
                "path": path,
                "nameEn": item.get("name"),
                "name": "OrionSuit",
                "nameInternal": "OrionSuit",
                "polarities": list(base_suit.get("ArtifactSlots") or []),
                "_slotVectorSource": "raw-package:/Lotus/Powersuits/SiriusOrion/OrionBaseSuit.ArtifactSlots",
            }
            selected.append((source, item))
    abilities: list[dict[str, Any]] = []
    frames = []
    slot_semantics_audit = []
    for source, item in selected:
        slots, slot_audit = explicit_frame_slots(source, item)
        normal = slots["normal"]
        aura = slots["aura"]
        exilus = slots["exilus"]
        slot_semantics_audit.append(slot_audit)
        growth, growth_source = rank_growth(raw_root, source["path"])
        base = {
            "health": float(source.get("health") or item.get("health") or 0),
            "shield": float(source.get("shield") or item.get("shield") or 0),
            "armor": float(source.get("armour") or source.get("armor") or item.get("armor") or 0),
            "energy": float(item.get("power") or 0),
            "sprint": float(item.get("sprintSpeed") or item.get("sprint") or 1),
        }
        rank30 = {key: round(value + float(growth.get(key, 0)), 6) for key, value in base.items()}
        frame_abilities = [ability_record(raw_root, image_root, localization, ability, index, meta, missing, wiki) for index, ability in enumerate((item.get("abilities") or [])[:4])]
        abilities.extend(frame_abilities)
        portrait = copy_item_asset(image_root, item.get("imageName"), ASSET_ROOT / "portraits", missing)
        frame = {
            "id": source["path"],
            "path": source["path"],
            "nameEn": item.get("name") or source.get("nameEn"),
            "nameZh": localized(localization, source.get("nameTag"), item.get("name") or source.get("nameEn") or ""),
            "description": localized(localization, source.get("descTag"), item.get("description") or ""),
            "descriptionEn": item.get("description") or "",
            "basePanel": base,
            "rank30Panel": rank30,
            "rankGrowth": growth,
            "rankGrowthSource": growth_source,
            "slotPolarities": {"aura": aura, "exilus": exilus, "normal": normal},
            "slotPolaritySource": slot_audit["source"],
            "auraPolarity": aura,
            "exilusPolarity": exilus,
            "abilities": frame_abilities,
            "passive": localized(localization, source.get("passiveTag"), item.get("passiveDescription") or ""),
            "passiveEn": item.get("passiveDescription") or "",
            "portraitAsset": portrait,
            "iconAsset": portrait,
            "masteryReq": source.get("masteryReq") or item.get("masteryReq") or 0,
            **provenance(meta),
        }
        frames.append(frame)
    fill_ability_localization(abilities)
    ability_coverage = canonicalize_abilities(abilities)
    _ensure_ability_contract(abilities)
    frames.sort(key=lambda row: str(row.get("nameEn") or ""))
    return frames, abilities, {
        "sourceCount": len(export_frames),
        "sourceRejected": source_rejected,
        "slotPolarityMismatches": [],
        "slotSemantics": {
            "source": "frozen-export.warframes[].polarities",
            "normal": [0, 8],
            "aura": 8,
            "exilus": 9,
            "reserved": [10, 12],
            "validatedFrameCount": len(slot_semantics_audit),
            "sourceExceptions": [row for row in slot_semantics_audit if row["source"] != "frozen-export.warframes[].polarities"],
            "crossCheckUnavailable": [row["path"] for row in slot_semantics_audit if row["validatedAgainst"] == "unavailable"],
        },
        "abilityCoverage": ability_coverage,
    }


def mod_pve(raw_root: Path, item: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    raw = raw_json(raw_root, item["uniqueName"])
    if not raw or raw.get("AvailableOnPve") == 0 or raw.get("AvailableOnPvp") == 1 or PVP_RE.search(item["uniqueName"]):
        return False, raw
    if any(PVP_RE.search(str(drop.get("location") or "")) for drop in item.get("drops") or []):
        return False, raw
    return True, raw


def warframe_mod_compatibility(item: dict[str, Any], raw: dict[str, Any]) -> tuple[bool, str, str]:
    """Return whether a mirror row is a real Warframe card.

    The upstream ``Mods.json`` bucket is historical and contains a few cards
    whose install target is a melee weapon or Parazon.  Prefer the raw package
    compatibility path, then use ``compatName`` for tiered rows whose package
    payload is intentionally empty.  The original values are returned for
    provenance and diagnostics.
    """
    compat_name = str(item.get("compatName") or "").strip()
    raw_compat = str(raw.get("ItemCompatibility") or "").strip()
    lowered_name = compat_name.casefold()
    lowered_raw = raw_compat.casefold()
    if lowered_name in NON_WARFRAME_COMPAT_NAMES:
        return False, compat_name, raw_compat
    if "/weapons/" in lowered_raw or any(token in lowered_raw for token in ("/parazon", "hackingdevice", "playermeleeweapon")):
        return False, compat_name, raw_compat
    return True, compat_name, raw_compat


def warframe_mod_is_exilus(item: dict[str, Any], raw: dict[str, Any]) -> bool:
    """Use both mirrors: tiered package rows often omit ``IsUtility``."""
    return bool(item.get("isExilus") or item.get("isUtility") or raw.get("IsUtility"))


def warframe_mod_is_augment(source: dict[str, Any], raw: dict[str, Any]) -> bool:
    """Combine the two authoritative flags.

    The frozen export carries the correct ``false`` value for ordinary cards,
    while raw packages carry the positive flag for frame-specific ability
    augments that are not represented in that export's support pass.
    """
    return bool(source.get("isAugment") or raw.get("IsAbilityAugment"))


def build_mods(export_mods: list[dict[str, Any]], item_mods: list[dict[str, Any]], raw_root: Path, image_root: Path, localization: dict[str, str], i18n: dict[str, Any], rabbit_assets: Path, rabbit_mods: dict[str, dict[str, Any]], meta: dict[str, Any], missing: list[str], set_catalog: dict[str, dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    export_by_path = {row.get("path"): row for row in export_mods}
    shells: dict[str, list[dict[str, Any]]] = {}
    for source in export_mods:
        shells.setdefault(str(source.get("nameEn") or "").casefold(), []).append(source)
    # The portable export keeps shell rows in the same array as members, but
    # member rows intentionally omit shell fields such as setPieces. Index by
    # the stable modSet identifier and retain the shell's official text/effects.
    shell_by_id: dict[str, dict[str, Any]] = {}
    for source in export_mods:
        set_id = str(source.get("modSet") or "").strip()
        if not set_id or not isinstance(source.get("setPieces"), int):
            continue
        shell_by_id[set_id] = dict(source)
        # Export shell rows expose setPieces but not always a path suitable
        # for provenance. Keep the member-family path when available.
        shell_by_id[set_id].setdefault("setSource", source.get("path"))
        shell_by_id[set_id]["setDescriptionTag"] = next(
            (effect.get("descriptionTag") for effect in source.get("effects") or ()
             if isinstance(effect, dict) and effect.get("descriptionTag")),
            None,
        )
        if not shell_by_id[set_id]["setDescriptionTag"]:
            for cond in source.get("conditionalEffects") or ():
                if not isinstance(cond, dict):
                    continue
                shell_by_id[set_id]["setDescriptionTag"] = next(
                    (effect.get("descriptionTag") for effect in cond.get("effects") or ()
                     if isinstance(effect, dict) and effect.get("descriptionTag")),
                    None,
                )
                if shell_by_id[set_id]["setDescriptionTag"]:
                    break
        shell_by_id[set_id]["setNameTag"] = source.get("nameTag") if source.get("nameTag") != "/Lotus/Language/Items/EmptyArtifact" else None
    result = []
    set_catalog = set_catalog or build_mod_set_catalog(export_mods, localization)
    for item in item_mods:
        if item.get("type") != "Warframe Mod" or item.get("compatName") == "Shade":
            continue
        ok, raw = mod_pve(raw_root, item)
        if not ok:
            continue
        is_frame_card, compat_name, raw_compat = warframe_mod_compatibility(item, raw)
        if not is_frame_card:
            continue
        source = dict(export_by_path.get(item["uniqueName"]) or {})
        source.setdefault("path", item["uniqueName"])
        source.setdefault("nameEn", item.get("name"))
        source.setdefault("maxRank", item.get("fusionLimit") or 0)
        source.setdefault("baseDrain", item.get("baseDrain"))
        source.setdefault("polarity", polarity(item.get("polarity")))
        source.setdefault("rarity", str(item.get("rarity") or "COMMON").upper())
        if not source.get("effects"):
            source["effects"] = effect_rows(raw.get("Upgrades") or [])
        source.setdefault("conditionalEffects", [])
        for shell in shells.get(str(item.get("name") or "").casefold(), []):
            if shell.get("path") != source["path"] and shell.get("conditionalEffects"):
                source["conditionalEffects"] = [*source["conditionalEffects"], *shell["conditionalEffects"]]
        aura = compat_name.casefold() == "aura" or bool(item.get("isAura")) or float(item.get("baseDrain") or 0) < 0 or "/aura/" in item["uniqueName"].casefold()
        exilus = not aura and warframe_mod_is_exilus(item, raw)
        slot_kind = "aura" if aura else ("exilus" if exilus else "warframe")
        category = slot_kind
        name_tag = raw.get("LocalizeTag") or source.get("nameTag")
        name_zh = localized(localization, name_tag, item.get("name") or "")
        descriptions = localized_stats(i18n, item["uniqueName"], item.get("levelStats") or [])
        english = [[clean_official_text(line) for line in level.get("stats") or []] for level in item.get("levelStats") or []]
        rabbit = rabbit_mods.get(item["uniqueName"]) or {}
        icon = str(rabbit.get("Icon") or "").lstrip("/")
        image = copy_asset(rabbit_assets / Path(*PurePosixPath(icon).parts), ROOT / "frontend" / "assets" / "mods" / "art" / Path(*PurePosixPath(icon).parts), missing) if icon else None
        if image:
            image = image.replace("/assets/mods/art/", "/assets/mods/art/")
        else:
            image = copy_item_asset(image_root, item.get("imageName"), ASSET_ROOT / "mods", missing)
        compatible = []
        if compat_name and compat_name.casefold() not in {"warframe", "aura"}:
            compatible = [compat_name]
        compatibility_type = "frame-specific" if compatible else "warframe"
        compatibility_tags = list(source.get("compatibilityTags") or ())
        for tag in ("WARFRAME", category.upper()):
            if tag not in compatibility_tags:
                compatibility_tags.append(tag)
        # Keep the raw target visible to diagnostics without making the
        # simulator depend on a mirror-specific spelling.
        source_type = "Warframe Aura" if aura else ("Warframe Exilus" if exilus else "Warframe Mod")
        # ``compatibleFrames`` is the actual install target; use explicit
        # semantic fields rather than leaking the upstream generic type label.
        source_compatibility = compat_name or "WARFRAME"
        if aura:
            source_compatibility = "AURA"
        set_id = str(source.get("modSet") or "") or None
        if set_id and set_id in shell_by_id:
            set_name_tag, description_tag = _set_shell_text_tags(set_id)
            shell_by_id[set_id]["setNameTag"] = set_name_tag or shell_by_id[set_id].get("setNameTag")
            shell_by_id[set_id]["setDescriptionTag"] = description_tag or shell_by_id[set_id].get("setDescriptionTag")
            shell_by_id[set_id]["setNameFallback"] = localized(localization, set_name_tag, "") if set_name_tag else ""
        set_fields = set_shell_metadata(set_id, shell_by_id, localization)
        if set_id and set_id in set_catalog:
            catalog_set = set_catalog[set_id]
            set_fields.update({
                "setMaxPieces": catalog_set.get("maxPieces"),
                "setName": catalog_set.get("name"),
                "setNameZh": catalog_set.get("nameZh"),
                "setDescription": catalog_set.get("description") or None,
                "setDesc": catalog_set.get("setDesc") or catalog_set.get("description") or None,
                "setDescriptionTag": catalog_set.get("descriptionTag"),
                "setEffects": catalog_set.get("effects") or [],
                "setStats": catalog_set.get("setStats") or catalog_set.get("effects") or [],
                "setConditionalEffects": catalog_set.get("conditionalEffects") or [],
                "setDisplayValues": catalog_set.get("displayValues") or {},
                "setRuntime": catalog_set.get("runtime") or {},
                "setSource": catalog_set.get("sourcePath"),
                "source": catalog_set.get("sourcePath"),
                "setModSetValues": catalog_set.get("modSetValues") or [],
            })
        result.append({
            **source,
            "id": source["path"],
            "nameZh": name_zh,
            "nameTag": name_tag,
            "slotKind": slot_kind,
            "type": category,
            "category": category,
            "sourceType": source_type,
            "sourceCategory": str(item.get("category") or "Mods"),
            "compatibilityType": compatibility_type,
            "sourceCompatibility": source_compatibility,
            "rawItemCompatibility": raw_compat or None,
            "compatibilityTags": compatibility_tags,
            # A few frozen export rows omit rarity; keep the card contract
            # total so the frontend can always choose a rarity frame.
            "rarity": str(item.get("rarity") or source.get("rarity") or raw.get("Rarity") or "COMMON").upper(),
            "compatibility": "PlayerPowerSuit" if not compatible else compat_name,
            "compatibleFrames": compatible,
            "isAugment": warframe_mod_is_augment(source, raw),
            "effectsZhByRank": descriptions,
            "effectsZh": descriptions[-1] if descriptions else [],
            "description": clean_official_text("\n".join(descriptions[-1]) if descriptions else ""),
            "descriptionEn": clean_official_text("\n".join(english[-1]) if english else ""),
            "art": image,
            "iconAsset": image,
            "validForCalculation": True,
            **set_fields,
            **provenance(meta),
        })
    result.sort(key=lambda row: (row["slotKind"], str(row.get("nameEn") or "")))
    return result


def build_arcanes(export_arcanes: list[dict[str, Any]], item_arcanes: list[dict[str, Any]], image_root: Path, localization: dict[str, str], i18n: dict[str, Any], meta: dict[str, Any], missing: list[str]) -> list[dict[str, Any]]:
    source_by_name: dict[str, list[dict[str, Any]]] = {}
    for source in export_arcanes:
        if "PlayerPowerSuit" in str(source.get("compatibility") or ""):
            source_by_name.setdefault(str(source.get("nameEn") or "").casefold(), []).append(source)
    result = []
    # Internal listener rows (for example Arcane Steadfast's four ability
    # listeners) duplicate one player-facing item. Keep the canonical row
    # carrying levelStats and discard listener-only duplicates.
    canonical_items: dict[str, dict[str, Any]] = {}
    for item in item_arcanes:
        if item.get("type") != "Warframe Arcane":
            continue
        key = str(item.get("name") or item.get("uniqueName") or "").casefold()
        previous = canonical_items.get(key)
        score = (2 if item.get("levelStats") else 0) + (0 if str(item.get("uniqueName") or "").endswith("Listener") else 1)
        old_score = ((2 if previous.get("levelStats") else 0) + (0 if str(previous.get("uniqueName") or "").endswith("Listener") else 1)) if previous else -1
        if previous is None or score > old_score:
            canonical_items[key] = item
    for item in canonical_items.values():
        candidates = source_by_name.get(str(item.get("name") or "").casefold(), [])
        source = max(candidates, key=lambda row: len(row.get("effects") or []) + len(row.get("conditionalEffects") or []), default={})
        descriptions = localized_stats(i18n, item["uniqueName"], item.get("levelStats") or [])
        english = [[str(line) for line in level.get("stats") or []] for level in item.get("levelStats") or []]
        icon = copy_item_asset(image_root, item.get("imageName"), ROOT / "frontend" / "assets" / "arcanes", missing)
        result.append({
            **source,
            "id": item["uniqueName"],
            "path": item["uniqueName"],
            "nameEn": item.get("name"),
            "nameZh": localized(localization, source.get("nameTag"), ((i18n.get(item["uniqueName"]) or {}).get("zh") or {}).get("name") or item.get("name")),
            "description": "\n".join(descriptions[-1]) if descriptions else "",
            "descriptionEn": "\n".join(english[-1]) if english else "",
            "effectsZhByRank": descriptions,
            "maxRank": item.get("fusionLimit") or source.get("maxRank") or 0,
            "rarity": str(item.get("rarity") or source.get("rarity") or "COMMON").upper(),
            "compatibility": "PlayerPowerSuit",
            "slotKind": "warframe",
            "iconAsset": icon,
            "validForCalculation": bool(source.get("effects") or source.get("conditionalEffects")),
            **provenance(meta),
        })
    result.sort(key=lambda row: str(row.get("nameEn") or ""))
    return result


def build_helminth(raw_root: Path, image_root: Path, localization: dict[str, str], meta: dict[str, Any], missing: list[str], wiki: WikiAbilityIndex | None = None, abilities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    recipes = raw_root.joinpath(*PurePosixPath("Lotus/Types/Recipes/AbilityOverrides").parts)
    result = []
    canonical = {}
    for ability in abilities or ():
        key = str(ability.get("id") or ability.get("path") or "")
        if key and (key not in canonical or len(ability.get("scalars") or ()) > len(canonical[key].get("scalars") or ())):
            canonical[key] = ability
    for recipe_file in sorted(recipes.glob("*Blueprint.json")):
        if recipe_file.name == "BaseAbilityOverrideBlueprint.json":
            continue
        recipe = load(recipe_file)
        result_path = recipe.get("ResultItem")
        store = raw_json(raw_root, result_path) if result_path else {}
        ability_path = store.get("TypeName")
        icon_name = Path(str(store.get("Icon") or "")).name
        icon = copy_item_asset(image_root, icon_name, ASSET_ROOT / "abilities", missing)
        name_tag = store.get("LocalizeTag")
        desc_tag = store.get("LocalizeDescTag")
        native = recipe_file.name.startswith("Helminth")
        origin = next((x.get("ItemType") for x in recipe.get("SecretIngredients") or [] if "/Powersuits/" in str(x.get("ItemType") or "") and "/Types/" not in str(x.get("ItemType") or "")), None)
        internal_name = Path(str(ability_path or recipe_file.stem)).name.replace("Ability", "")
        display_name = localized(localization, name_tag, internal_name) or internal_name
        # Subsumed skills use the source frame ability's structured values. The
        # Helminth description is kept from the override tag, while the
        # inheritance edge remains explicit in sourceEvidence.
        source_ability = canonical.get(str(ability_path or ""))
        if source_ability and not native:
            scalars = deepcopy(source_ability.get("scalars") or [])
            scalar_groups = deepcopy(source_ability.get("scalarGroups") or [])
            energy_cost = deepcopy(source_ability.get("energyCost"))
            support_level = source_ability.get("supportLevel") or ("full" if scalars else "text-only")
            source_evidence = list(source_ability.get("sourceEvidence") or [])
            source_evidence.append({"kind": "inherited", "sourceAbilityId": str(source_ability.get("id") or ability_path)})
            unresolved = list(source_ability.get("unresolvedFields") or ())
            scalar_source = "inherited"
        else:
            scalars, support_level, source_evidence, unresolved, scalar_source = helminth_override_data(
                raw_root,
                str(ability_path or result_path or ""),
                HELMINTH_WIKI_NAMES.get(internal_name, display_name) if native else display_name,
                wiki,
                ordinal=HELMINTH_NATIVE_ORDER.get(internal_name) if native else None,
            )
            scalars, scalar_groups = _merge_overframe_fields(str(ability_path or result_path or ""), scalars, display_name)
            energy_cost = ability_energy_cost(raw_root, str(ability_path or result_path or ""), wiki.lookup(HELMINTH_WIKI_NAMES.get(internal_name, display_name)) if wiki and native else (wiki.lookup(display_name) if wiki else None))
            energy_cost = _merge_overframe_energy_cost(energy_cost, scalars)
            overframe_evidence = overframe_ability_evidence(str(ability_path or result_path or ""))
            if overframe_evidence:
                source_evidence.append(overframe_evidence)
        raw_ability = raw_json(raw_root, str(ability_path or "")) if ability_path else {}
        override_tag = raw_ability.get("HelminthOverrideDescTag")
        override_description = localized(localization, override_tag, "") if override_tag else ""
        altered: dict[str, Any] = {}
        if ability_path == "/Lotus/Powersuits/DemonFrame/Abilities/DemonFrameHealAbility":
            scalars = [{
                "id": "healing",
                "label": "healing",
                "labelEn": "healing",
                "labelZh": "治疗量",
                "values": [24, 28, 31, 35],
                "rankCount": 4,
                "base": 35,
                "unit": "%",
                "scale": "strength",
                "sourceKind": "wiki-audited-helminth",
            }]
            support_level = "partial"
            scalar_source = "wiki-altered"
            altered = {"scalars": deepcopy(scalars)}
        if ability_path == "/Lotus/Powersuits/Nezha/Abilities/NezhaTrailAbility" and not override_description:
            override_description = "移植后保留火焰路径数值，但不包含与炽热飞轮传送爆炸的联动。"
        result.append({
            "id": ability_path or result_path,
            "path": ability_path or result_path,
            "recipePath": "/" + recipe_file.relative_to(raw_root).with_suffix("").as_posix(),
            "originFrame": origin,
            "kind": "native" if native else "subsumed",
            "nameEn": Path(str(ability_path or recipe_file.stem)).name.replace("Ability", ""),
            "nameZh": display_name,
            "description": localized(localization, desc_tag, ""),
            "nameTag": name_tag,
            "descriptionTag": desc_tag,
            "iconAsset": icon,
            "energyCost": energy_cost,
            "scalars": scalars,
            "scalarGroups": scalar_groups,
            "supportLevel": support_level,
            "sourceEvidence": source_evidence,
            "unresolvedFields": unresolved,
            "scalarSource": scalar_source,
            "altered": altered,
            "alteredDescription": override_description,
            "alteredSupportLevel": "text-only" if override_description else "none",
            "validForCalculation": bool(scalars),
            **provenance(meta),
        })
    _ensure_ability_contract(result)
    return result


def build_invigorations(raw_root: Path, localization: dict[str, str], meta: dict[str, Any], frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest = raw_json(raw_root, "/Lotus/Upgrades/Invigorations/PrimaryHelminthManifest")
    frame_paths_by_family: dict[str, list[str]] = {}
    for frame in frames:
        frame_path = str(frame.get("path") or frame.get("id") or "")
        if "/" in frame_path:
            frame_paths_by_family.setdefault(str(PurePosixPath(frame_path).parent), []).append(frame_path)
    restrictions: dict[str, list[str]] = {}
    for exception in manifest.get("UpgradeExceptions") or []:
        frame = str(exception.get("ItemType") or "")
        for upgrade in exception.get("InvalidUpgradeTypes") or []:
            restrictions.setdefault(str(upgrade), []).append(frame)
    result = []
    for category, key in (("offensive", "WeightedOffensiveUpgrades"), ("utility", "WeightedDefensiveUpgrades")):
        for weighted in manifest.get(key) or []:
            relative = str(weighted.get("ItemType") or "")
            unique_name = "/Lotus/Upgrades/Invigorations/" + relative
            raw = raw_json(raw_root, unique_name)
            effects = effect_rows(raw.get("Upgrades") or [])
            descriptions = [render_effect_text(localized(localization, effect.get("descriptionTag"), effect.get("upgradeType") or ""), [effect]) for effect in effects]
            raw_restrictions = sorted(set(restrictions.get(relative, [])))
            restriction_families = sorted({
                str(PurePosixPath(value).parent)
                for value in raw_restrictions
                if PurePosixPath(value).name.casefold().endswith("basesuit")
            })
            restriction_frame_paths = sorted({
                frame_path
                for family in restriction_families
                for frame_path in frame_paths_by_family.get(family, [])
            })
            result.append({
                "id": unique_name,
                "path": unique_name,
                "nameEn": Path(relative).name.replace("OffensiveInvigoration", "").replace("UtilityInvigoration", ""),
                "nameZh": " / ".join(descriptions) or Path(relative).name,
                "description": "\n".join(descriptions),
                "category": category,
                "weight": weighted.get("Weight"),
                "effects": effects,
                "restrictions": raw_restrictions,
                "restrictionFamilies": restriction_families,
                "restrictionFramePaths": restriction_frame_paths,
                # Empty/static offers remain visible but cannot be applied by
                # the numeric evaluator until an authoritative effect vector
                # exists.
                "validForCalculation": bool(effects) and all(effect.get("stat") for effect in effects),
                **provenance(meta),
            })
    return result


def shard_icon_name(crystal_type: str) -> str:
    name = Path(crystal_type).name
    mapping = {
        "ArchonCrystalAmar": "ArchonShardAmar.png",
        "ArchonCrystalAmarMythic": "ArchonShardAmarMythicGlow.png",
        "ArchonCrystalBoreal": "ArchonShardBoreal.png",
        "ArchonCrystalBorealMythic": "ArchonShardBorealMythicGlow.png",
        "ArchonCrystalNira": "ArchonShardNira.png",
        "ArchonCrystalNiraMythic": "ArchonShardNiraMythicGlow.png",
        "ArchonCrystalGreen": "ArchonShardGreen.png",
        "ArchonCrystalGreenMythic": "ArchonShardMythicGreenGlow.png",
        "ArchonCrystalOrange": "ArchonShardOrange.png",
        "ArchonCrystalOrangeMythic": "ArchonShardOrangeMythicGlow.png",
        "ArchonCrystalViolet": "ArchonShardViolet.png",
        "ArchonCrystalVioletMythic": "ArchonShardVioletMythicGlow.png",
    }
    return mapping.get(name, name + ".png")


def shard_body_icon_name(crystal_type: str) -> str:
    """Return the normal crystal body for both normal and Tau variants."""
    name = Path(crystal_type).name.removesuffix("Mythic")
    return shard_icon_name(name)


def shard_glow_icon_name(crystal_type: str) -> str | None:
    """Return only the Tau overlay; normal crystals have no overlay."""
    name = Path(crystal_type).name
    return shard_icon_name(name) if name.endswith("Mythic") else None


def build_shards(raw_root: Path, image_root: Path, localization: dict[str, str], meta: dict[str, Any], missing: list[str]) -> list[dict[str, Any]]:
    manifest = raw_json(raw_root, "/Lotus/Upgrades/Invigorations/PrimaryHelminthManifest")
    result = []
    icon_cache: dict[str, str | None] = {}
    for key, crystal in (manifest.get("ArchonCrystalUpgrades") or {}).items():
        match = re.match(r"ACC_([A-Z]+)(?:_(MYTHIC))?$", key)
        if not match:
            continue
        color = SHARD_COLORS[match.group(1)]
        tau = bool(match.group(2))
        crystal_type = str(crystal.get("CrystalType") or "")
        body_name = shard_body_icon_name(crystal_type)
        glow_name = shard_glow_icon_name(crystal_type)
        for asset_name in (body_name, glow_name):
            if asset_name and asset_name not in icon_cache:
                icon_cache[asset_name] = copy_item_asset(image_root, asset_name, ASSET_ROOT / "shards", missing)
        body_asset = icon_cache.get(body_name)
        glow_asset = icon_cache.get(glow_name) if glow_name else None
        for upgrade in crystal.get("UpgradeTypes") or []:
            unique_name = "/Lotus/Upgrades/Invigorations/" + str(upgrade)
            raw = raw_json(raw_root, unique_name)
            effects = effect_rows(raw.get("Upgrades") or [])
            description = str(raw.get("LocalizeTag") or "").removeprefix("[HC]").strip()
            localized_effects = [render_effect_text(localized(localization, effect.get("descriptionTag"), ""), [effect]) for effect in effects]
            if any(localized_effects):
                description = " / ".join(value for value in localized_effects if value)
            name = SHARD_NAMES_ZH[color] + (" (Tau)" if tau else "")
            display_description = re.sub(r"<[^>]+>", "", description).strip()
            result.append({
                "id": unique_name,
                "path": unique_name,
                "crystalType": crystal_type,
                "perkId": Path(str(upgrade)).name,
                "color": color,
                "tau": tau,
                "variant": "tau" if tau else "normal",
                "nameEn": Path(str(upgrade)).name,
                "nameZh": f"{name} · {display_description}",
                "description": description,
                "effects": effects,
                "iconAsset": body_asset,
                "baseIconAsset": body_asset,
                "glowIconAsset": glow_asset,
                "validForCalculation": all(effect.get("stat") for effect in effects),
                **provenance(meta),
            })
    return result


def main() -> int:
    options = args()
    if not OVERFRAME_ABILITY_STATS.is_file():
        raise RuntimeError(f"required frozen Overframe ability stats missing: {OVERFRAME_ABILITY_STATS}")
    manifest = load(options.export_dir / "manifest.json")
    if manifest.get("buildLabel") != options.build:
        raise RuntimeError(f"export build mismatch: {manifest.get('buildLabel')} != {options.build}")
    localization = load(options.localization)
    wiki = WikiAbilityIndex(options.wiki)
    parser_hash = sha256(Path(__file__).resolve())
    meta = {
        "buildLabel": manifest["buildLabel"],
        "sourceUrl": f"frozen://data/export/{options.build} + input://packages + input://languages",
        "fetchedAt": manifest.get("generatedAtUtc") or datetime.now(timezone.utc).isoformat(),
        "parserHash": parser_hash,
        "localizationHash": sha256(options.localization),
        "localizationSource": "input://languages-zh",
        "wikiSnapshot": provenance_path(options.wiki) if wiki.root else None,
        "overframeAbilityStats": {
            "path": provenance_path(OVERFRAME_ABILITY_STATS),
            "url": next((source.get("url") for source in load_source_lock(ROOT).get("sources") or [] if source.get("id") == "overframe-abilitystats"), ""),
            "sha256": hashlib.sha256(OVERFRAME_ABILITY_STATS.read_bytes()).hexdigest() if OVERFRAME_ABILITY_STATS.is_file() else None,
        },
    }
    item_json = options.items / "json"
    image_root = options.items / "img"
    i18n = load(item_json / "i18n.json")
    rabbit_metadata = options.rabbit_mods
    rabbit_mods = {str(row.get("RabbitID") or ""): row for row in load(rabbit_metadata)}
    missing: list[str] = []
    frames, abilities, audit = build_frames(rows(options.export_dir / "warframes.json"), rows(item_json / "Warframes.json"), options.raw, image_root, localization, meta, missing, wiki)
    set_catalog = build_mod_set_catalog(rows(options.export_dir / "mods.json"), localization)
    mods = build_mods(rows(options.export_dir / "mods.json"), rows(item_json / "Mods.json"), options.raw, image_root, localization, i18n, options.rabbit_assets, rabbit_mods, meta, missing, set_catalog)
    arcanes = build_arcanes(rows(options.export_dir / "arcanes.json"), rows(item_json / "Arcanes.json"), image_root, localization, i18n, meta, missing)
    helminth = build_helminth(options.raw, image_root, localization, meta, missing, wiki, abilities)
    invigoration = build_invigorations(options.raw, localization, meta, frames)
    shards = build_shards(options.raw, image_root, localization, meta, missing)
    gaps = []
    if not wiki.root:
        gaps.append("Wiki frozen snapshot unavailable; ability rows retain package evidence and fail closed for missing rank vectors")
    ability_rows = abilities + helminth
    if any(not row.get("scalars") or row.get("unresolvedFields") for row in ability_rows):
        gaps.append("部分技能仍缺少可验证的等级向量；保留官方描述并拒绝猜值")
    payload = {
        "schemaVersion": 1,
        "buildLabel": manifest["buildLabel"],
        "status": "ready",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "provenance": {**provenance(meta), "frozenSourceCounts": manifest.get("counts"), "runtimeExternalDependencies": [], "wikiSnapshot": provenance_path(options.wiki) if wiki.root else None, "overframeAbilityStats": meta.get("overframeAbilityStats")},
        "counts": {"warframes": len(frames), "abilities": len(abilities), "mods": len(mods), "arcanes": len(arcanes), "helminth": len(helminth), "helminthSubsumed": sum(row["kind"] == "subsumed" for row in helminth), "helminthNative": sum(row["kind"] == "native" for row in helminth), "invigoration": len(invigoration), "shards": len(shards), "shardIcons": len({asset for row in shards for asset in (row.get("baseIconAsset"), row.get("glowIconAsset")) if asset})},
        "warframes": frames,
        "abilities": abilities,
        "mods": mods,
        "modSets": set_catalog,
        "arcanes": arcanes,
        "helminth": helminth,
        "invigoration": invigoration,
        "shards": shards,
        "audit": {**audit, "missingAssetCount": len(set(missing)), "missingAssets": sorted(set(missing))},
        "gaps": gaps,
    }
    if not frames or not helminth or not invigoration or not shards:
        raise RuntimeError(f"empty authoritative dataset: frames={len(frames)}, helminth={len(helminth)}, invigoration={len(invigoration)}, shards={len(shards)}")
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(options.output), "counts": payload["counts"], "rejected": len(audit["sourceRejected"]), "polarityMismatches": len(audit["slotPolarityMismatches"]), "missingAssets": payload["audit"]["missingAssetCount"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



