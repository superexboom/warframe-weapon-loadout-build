from __future__ import annotations

"""Build the compact enemy-defense overlay used by the offline portable app.

The frozen wfarsenal export contains the translated avatar rows, while the
Warframe public-export-plus snapshot carries the values that the old exporter
failed to resolve (base level, damage-controller pools and faction keyword).
This script joins those two records and writes only the fields needed by the
portable simulator; the large raw snapshot never ships with the package.
"""

import argparse
import json
from pathlib import Path
from typing import Any, Mapping
import urllib.parse

from data_sources import export_dir as active_export_dir

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = active_export_dir(ROOT)


def _wiki_slug(name: str) -> str:
    """Mirror the wiki-knowledge raw cache filename slug (URL-encoded, '_' style)."""
    return urllib.parse.quote(name.replace(" ", "_"), safe="").replace("%", "_").casefold()


def _load_wiki_head_index(path: Path | None) -> dict[str, float]:
    """Optional gap-filler: slug -> total headshot multiplier from the scraped wiki
    enemy pages ("Body Multipliers · Head: N.Nx").  The wiki value is the final
    multiplier (part factor x fixed 1.5 headshot factor), so it maps onto the
    engine's compact ``headshotMultiplier`` form directly."""
    if path is None or not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, float] = {}
    for slug, row in raw.items():
        if not isinstance(row, Mapping) or row.get("disambig"):
            continue
        value = row.get("head")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        result[str(slug).casefold()] = float(value)
    return result

FACTION_RESISTANCE = {
    "Grineer": "RK_GRINEER_FACTION",
    "Corpus": "RK_CORPUS_FACTION",
    "Narmer": "RK_NARMER_FACTION",
    "Infestation": "RK_INFESTED_FACTION",
    "Infested": "RK_INFESTED_FACTION",
    "Techrot": "RK_PROTOINFESTED_FACTION",
    "Sentient": "RK_SENTIENT_FACTION",
    "Orokin": "RK_OROKIN_FACTION",
    "Orokin Empire": "RK_OROKIN_EMPIRE_FACTION",
    "OrokinEmpire": "RK_OROKIN_EMPIRE_FACTION",
    "Scaldra": "RK_LASRIA_FACTION",
    "MITW": "RK_MITW_FACTION",
    "Duviri": "RK_ZARIMAN_FACTION",
    "TENNO": "RK_NEUTRAL",
}

# Compact, source-backed enhancement metadata. The vendor reducer carries the
# static formulas (Eximus base-stat curves, Overguard smoothstep, Empowered
# player-count multipliers, Archimedea overguard fraction, Steel Path 2.5x) and
# the product now exposes the toggles, so support flags are True; the remaining
# unsupported list stays informational for mechanics the engine still refuses
# to fabricate.  test_enemy_enhancements.py pins that contract, so keep it in
# sync.  Keeping it at the overlay root avoids copying the same constants into
# 1,861 rows.
WIKI_ENHANCEMENTS = {
    "schema": "warframe-wiki-enemy-enhancements-v1",
    "retrieved": "2026-08-21",
    "sources": {
        "enemyData": "https://wiki.warframe.com/w/Module:Enemies/data",
        "levelScaling": "https://wiki.warframe.com/w/Enemy_Level_Scaling",
        "overguard": "https://wiki.warframe.com/w/Overguard",
        "magnetic": "https://wiki.warframe.com/w/Damage/Magnetic_Damage",
        "eximus": "https://wiki.warframe.com/w/Eximus",
        "deepArchimedea": "https://wiki.warframe.com/w/Deep_Archimedea",
        "factions": "https://wiki.warframe.com/w/Factions",
    },
    "overguard": {
        "eximusBase": 12.0,
        "levelScale": {
            "f1": {"offset": 1.0, "coefficient": 0.0015, "exponent": 4.0},
            "f2": {"offset": 1.0, "coefficient": 260.0, "exponent": 0.9},
            "transition": {"lower": 45.0, "upper": 50.0, "blend": "smoothstep"},
        },
        "voidDamageMultiplier": 1.5,
        "archimedeaOverguardFraction": 0.5,
        "magneticMultiplier": {"firstStack": 2.0, "perAdditionalStack": 0.25, "maximum": 4.25},
        "status": "implemented-static-snapshot",
    },
    "eximus": {
        "baseOverguard": 12.0,
        "status": "implemented-static-snapshot",
    },
    "archimedea": {
        "mode": "Bolstered Belligerents",
        "overguardFractionOfMaxHealth": 0.5,
        "status": "implemented-static-snapshot",
    },
    "steelPath": {
        "shieldMultiplier": 2.5,
        "armorMultiplier": 1.0,
        "status": "implemented-static-snapshot",
    },
    "empowered": {
        "playerCountHealthShieldMultipliers": {
            "1": 2.5,
            "2": 3.0,
            "3": 3.5,
            "4": 4.0,
        },
        "status": "implemented-static-snapshot",
    },
    "support": {
        "eximus": True,
        "overguard": True,
        "archimedea": True,
        "steelPath": True,
        "empowered": True,
    },
    "unsupported": [
        "positive-overguard-per-unit",
        "overguard-electric-break-effects",
        "eximus-special-variant",
        "dynamic-boss-attenuation",
        "shield-recharge-and-gating",
    ],
}


def _load(path: Path) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _join_base_levels(agents: Mapping[str, Any]) -> dict[str, list[float]]:
    result: dict[str, list[float]] = {}
    for agent in agents.values():
        if not isinstance(agent, Mapping):
            continue
        level = _number(agent.get("baseLevel"))
        avatars = agent.get("avatarTypes")
        if level is None or not isinstance(avatars, Mapping):
            continue
        for avatar_path in avatars.values():
            if not isinstance(avatar_path, str) or not avatar_path:
                continue
            result.setdefault(avatar_path, []).append(level)
    return result


def _overguard_paths(agents: Mapping[str, Any]) -> set[str]:
    """Return avatar paths whose agent explicitly carries an Overguard aura."""
    result: set[str] = set()
    for agent in agents.values():
        if not isinstance(agent, Mapping):
            continue
        items = agent.get("items")
        if not isinstance(items, list) or not any(
            isinstance(item, Mapping) and "overguard" in str(item.get("type") or "").casefold()
            for item in items
        ):
            continue
        avatars = agent.get("avatarTypes")
        if isinstance(avatars, Mapping):
            result.update(
                str(value)
                for value in avatars.values()
                if isinstance(value, str) and value
            )
    return result


def _proxy_rows(row: Mapping[str, Any], controller: Mapping[str, Any], proxies: Mapping[str, Any]) -> list[dict[str, Any]]:
    current = row.get("hitProxies")
    source = current if isinstance(current, list) and current else controller.get("hitProxies")
    if not isinstance(source, list):
        return []
    result: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, Mapping):
            continue
        merged = dict(item)
        proxy_type = merged.get("type")
        detail = proxies.get(proxy_type) if isinstance(proxy_type, str) else None
        if isinstance(detail, Mapping):
            for key in ("damageAtten", "criticalMultiplier", "criticalChance", "weakness"):
                if merged.get(key) is None and detail.get(key) is not None:
                    merged[key] = detail[key]
        bone = str(merged.get("bone") or "").upper()
        proxy_name = str(proxy_type or "").upper()
        if merged.get("part") is None and ("HEAD" in bone or "HEAD" in proxy_name):
            merged["part"] = "HEAD"
        result.append(merged)
    return result


def _infer_health_type(faction: str, path: str, row: Mapping[str, Any]) -> tuple[str, str]:
    existing = str(row.get("healthType") or "").strip()
    if existing:
        return existing, "export"
    lower = f"{faction} {path}".casefold()
    if faction in {"Corpus", "Sentient"} or "corpus" in lower:
        return "RK_ROBOTIC", "faction-inference"
    if faction in {"Infestation", "Infested", "Techrot"} or "infest" in lower:
        return "RK_INFESTED_FLESH", "faction-inference"
    if faction in {"Grineer", "Narmer", "Orokin", "Orokin Empire", "OrokinEmpire", "Scaldra"}:
        return "RK_CLONED_FLESH", "faction-inference"
    return "RK_FLESH", "neutral-inference"


def _infer_armour_type(faction: str, path: str, armour: float, row: Mapping[str, Any]) -> tuple[str, str]:
    if armour <= 0:
        return "RK_NONE", "zero-pool"
    existing = str(row.get("armourType") or "").strip()
    if existing:
        return existing, "export"
    lower = f"{faction} {path}".casefold()
    health_type = str(row.get("healthType") or "")
    if faction in {"Infestation", "Infested", "Techrot"} or health_type == "RK_FOSSILIZED" or "infest" in lower:
        return "RK_INFESTED_ARMOUR", "faction-inference"
    if armour >= 400 or any(token in lower for token in ("bombard", "heavy", "nox", "napalm")):
        return "RK_HULKING_ARMOR", "faction-inference"
    return "RK_ARMOR", "faction-inference"


def _infer_shield_type(faction: str, path: str, shield: float, row: Mapping[str, Any]) -> tuple[str, str]:
    if shield <= 0:
        return "RK_NONE", "zero-pool"
    existing = str(row.get("shieldType") or "").strip()
    if existing:
        return existing, "export"
    lower = f"{faction} {path}".casefold()
    if faction == "Sentient":
        return "RK_SENTIENT_SHIELD", "faction-inference"
    if faction == "TENNO":
        return "RK_TENNO_SHIELD", "faction-inference"
    if shield >= 1000 or "heavyshield" in lower or "heavy_shield" in lower:
        return "RK_HEAVY_SHIELD", "pool-inference"
    return "RK_SHIELD", "faction-inference"


def build(raw_path: Path, export_dir: Path = EXPORT_DIR, wiki_head_index: dict[str, float] | None = None) -> dict[str, Any]:
    export = _load(export_dir / "enemies.json")
    raw = _load(raw_path)
    rows = export.get("data") if isinstance(export.get("data"), list) else []
    avatars = raw.get("avatars") if isinstance(raw.get("avatars"), Mapping) else {}
    controllers = raw.get("damageControllers") if isinstance(raw.get("damageControllers"), Mapping) else {}
    proxies = raw.get("hitProxies") if isinstance(raw.get("hitProxies"), Mapping) else {}
    agents = raw.get("agents") if isinstance(raw.get("agents"), Mapping) else {}
    base_levels = _join_base_levels(agents)
    overguard_paths = _overguard_paths(agents)
    overlays: dict[str, dict[str, Any]] = {}
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        path = str(raw_row.get("path") or "").strip()
        if not path:
            continue
        avatar = avatars.get(path) if isinstance(avatars, Mapping) else None
        avatar = avatar if isinstance(avatar, Mapping) else {}
        controller_path = str(raw_row.get("damageController") or "")
        # The frozen export often stores a suffix-truncated controller path
        # (e.g. "/AreaCasterAcolyteDamageController") that never resolves in the
        # WPEP map; fall back to the avatar's full path so hit proxies and
        # defense pools join correctly.
        if controller_path not in controllers:
            controller_path = str(avatar.get("damageController") or controller_path or "")
        controller = controllers.get(controller_path) if isinstance(controllers, Mapping) else None
        controller = controller if isinstance(controller, Mapping) else {}
        health = _number(raw_row.get("health"))
        if not health or health <= 0:
            health = _number(avatar.get("health")) or 0.0
        shield = _number(raw_row.get("shield"))
        raw_shield = _number(controller.get("shield"))
        if (shield is None or shield <= 0) and raw_shield is not None and raw_shield > 0:
            shield = raw_shield
        shield = max(0.0, shield or 0.0)
        armour = _number(raw_row.get("armour"))
        raw_armour = _number(controller.get("armor"))
        if (armour is None or armour <= 0) and raw_armour is not None and raw_armour > 0:
            armour = raw_armour
        armour = max(0.0, armour or 0.0)
        faction = str(raw_row.get("faction") or avatar.get("faction") or "")
        resistance = str(raw_row.get("factionResistance") or avatar.get("factionResistanceKeyword") or "")
        if not resistance:
            resistance = FACTION_RESISTANCE.get(faction, "RK_NEUTRAL")
        candidates = sorted(set(base_levels.get(path, [])))
        base_level = _number(raw_row.get("baseLevel"))
        if base_level is None:
            base_level = candidates[0] if len(candidates) == 1 else 1.0
        health_type, health_source = _infer_health_type(faction, path, raw_row)
        # Use the inferred health type when selecting an armor material.  The raw
        # row may omit healthType even though the faction is unambiguous.
        armour_row = dict(raw_row)
        armour_row["healthType"] = health_type
        armour_type, armour_source = _infer_armour_type(faction, path, armour, armour_row)
        shield_type, shield_source = _infer_shield_type(faction, path, shield, raw_row)
        # Keep this overlay small: only missing/normalized fields are emitted.
        # Existing export values remain authoritative when they are already set.
        payload: dict[str, Any] = {}
        sources: dict[str, str] = {}
        if _number(raw_row.get("baseLevel")) is None:
            payload["baseLevel"] = base_level
            sources["baseLevel"] = "agent" if len(candidates) == 1 else "default-1"
        if not _number(raw_row.get("health")) or _number(raw_row.get("health")) <= 0:
            payload["health"] = health
            sources["health"] = "avatar"
        current_shield = _number(raw_row.get("shield"))
        if (current_shield is None or current_shield <= 0) and shield > 0:
            payload["shield"] = shield
            sources["shield"] = "damage-controller"
        current_armour = _number(raw_row.get("armour"))
        if (current_armour is None or current_armour <= 0) and armour > 0:
            payload["armour"] = armour
            sources["armour"] = "damage-controller"
        if not str(raw_row.get("healthType") or "").strip():
            payload["healthType"] = health_type
            sources["healthType"] = health_source
        if not str(raw_row.get("armourType") or "").strip() or armour <= 0:
            payload["armourType"] = armour_type
            sources["armourType"] = armour_source
        if not str(raw_row.get("shieldType") or "").strip() or shield <= 0:
            payload["shieldType"] = shield_type
            sources["shieldType"] = shield_source
        if not str(raw_row.get("factionResistance") or "").strip():
            payload["factionResistance"] = resistance
            sources["factionResistance"] = "avatar" if avatar.get("factionResistanceKeyword") else "faction-inference"
        if not str(raw_row.get("damageController") or "").strip() and controller_path:
            payload["damageController"] = controller_path
        # 护甲缩放按 wiki《Enemy Level Scaling》是全敌人通用规则（生命/护甲/护盾
        # 均随等级缩放）。冻结导出里的 usesNpcArmourCurve=False 与重复行自相矛盾
        # （同名单位真假并存），属导出伪迹而非逐单位真实开关，统一归一化为 True。
        if raw_row.get("usesNpcArmourCurve") is not True:
            payload["usesNpcArmourCurve"] = True
            sources["usesNpcArmourCurve"] = "wiki-universal-armour-curve"
        hit_proxies = _proxy_rows(raw_row, controller, proxies)
        if hit_proxies and not isinstance(raw_row.get("hitProxies"), list):
            payload["hitProxies"] = hit_proxies
        # Wiki gap-fill: rows whose export chain carries no HEAD proxy at all
        # (vehicles aside, some niche units) can still carry the wiki's verified
        # "Body Multipliers - Head" value as the compact headshotMultiplier form.
        merged_proxies = payload.get("hitProxies") if isinstance(payload.get("hitProxies"), list) else raw_row.get("hitProxies")
        head_supported = isinstance(merged_proxies, list) and any(
            isinstance(item, Mapping) and (
                str(item.get("part") or "").upper() == "HEAD"
                or "HEAD" in str(item.get("bone") or "").upper()
                or "HEAD" in str(item.get("type") or "").upper()
            )
            for item in merged_proxies
        )
        if not head_supported:
            wiki_heads = wiki_head_index or {}
            name_en = str(raw_row.get("nameEn") or raw_row.get("name") or "")
            wiki_value = wiki_heads.get(_wiki_slug(name_en)) if name_en else None
            if wiki_value is not None and _number(raw_row.get("headshotMultiplier")) is None:
                payload["headshotMultiplier"] = wiki_value
                sources["headshotMultiplier"] = "wiki"
        if raw_row.get("overguard") is not None or raw_row.get("hasOverguard"):
            payload["overguard"] = raw_row.get("overguard")
            payload["hasOverguard"] = bool(raw_row.get("hasOverguard") or raw_row.get("overguard"))
        elif path in overguard_paths:
            payload["hasOverguard"] = True
            payload["overguard"] = 0.0
        if raw_row.get("damageAttenuation") is not None or raw_row.get("hasDamageAttenuation") or raw_row.get("dynamicDamageResistance"):
            for key in ("damageAttenuation", "hasDamageAttenuation", "dynamicDamageResistance"):
                if raw_row.get(key) is not None:
                    payload[key] = raw_row[key]
        if sources:
            payload["defenseSources"] = sources
        overlays[path] = payload
    return {
        "buildLabel": export.get("buildLabel"),
        "schemaVersion": 2,
        "generatedFrom": {
            "source": "Warframe public export plus / ExportEnemies.json",
            "sourceUrl": "https://github.com/WFCD/warframe-public-export-plus",
            "wikiSources": WIKI_ENHANCEMENTS["sources"],
            "note": "Zero defense pools use RK_NONE; inferred material/faction fields are marked in defenseSources. Hit proxies (incl. HEAD) join through the avatar's full damage-controller path; units with no export HEAD proxy may carry the wiki 'Body Multipliers - Head' total as headshotMultiplier (defenseSources=wiki). Static Eximus, Overguard, Archimedea and Empowered snapshots are applied by the shared reducer; dynamic attenuation/regen remain unsupported.",
        },
        "wikiEnhancements": WIKI_ENHANCEMENTS,
        "count": len(overlays),
        "data": overlays,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--wiki-head-index",
        type=Path,
        default=None,
        help="Optional JSON map of wiki slug -> total headshot multiplier (from the scraped wiki corpus) used to gap-fill units whose export chain has no HEAD proxy",
    )
    args = parser.parse_args()
    output = args.output or args.export_dir / "enemy_overrides.json"
    payload = build(args.raw, export_dir=args.export_dir, wiki_head_index=_load_wiki_head_index(args.wiki_head_index))
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    wiki_filled = sum(1 for row in payload["data"].values() if row.get("headshotMultiplier") is not None)
    print(f"wrote {payload['count']} enemy overrides to {output} (wiki headshot gap-fill: {wiki_filled})")


if __name__ == "__main__":
    main()
