from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any

from data_sources import active_build

ROOT = Path(__file__).resolve().parent
BUILD = active_build(ROOT)
COMBO_KINDS = ("Neutral", "Forward", "Forward Block", "Block")

# Verified against the compatTags present in the frozen portable weapons export.
WEAPON_TYPE_TO_COMPAT_TAG = {
    "Assault Saw": "BLADESAW_STANCE",
    "Bayonet": "BAYONET",
    "Blade and Whip": "BLADE_AND_WHIP_STANCE",
    "Claws": "CLAWS_STANCE_STANCE",
    "Dagger": "DAGGERS_STANCE",
    "Dual Daggers": "DUAL_DAGGERS_STANCE",
    "Dual Nikanas": "DUAL_KATANAS_STANCE",
    "Dual Swords": "DUAL_SWORDS_STANCE",
    "Fist": "FIST_STANCE",
    "Glaive": "GLAIVES_STANCE",
    "Gunblade": "GUNBLADE_STANCE",
    "Hammer": "HAMMERS_STANCE",
    "Heavy Blade": "HEAVY_BLADE_STANCE",
    "Heavy Scythe": "HEAVY SCYTHE_STANCE",
    "Machete": "MACHETES_STANCE",
    "Nikana": "NIKANAS_STANCE",
    "Nunchaku": "NUNCHAKU_STANCE",
    "Polearm": "POLEARMS_STANCE",
    "Rapier": "RAPIER_STANCE",
    "Scythe": "SCYTHES_STANCE",
    "Sparring": "SPARRING_STANCE",
    "Staff": "STAVES_STANCE",
    "Sword": "SWORDS_STANCE",
    "Sword and Shield": "SWORDS_AND_SHIELD_STANCE",
    "Tonfa": "TONFA_STANCE",
    "Two-Handed Nikana": "LONG_KATANA_STANCE",
    "Warfan": "WARFAN_STANCE",
    "Whip": "WHIPS_STANCE",
}


def _args() -> argparse.Namespace:
    documents = ROOT.parent
    reverse_root = documents / "WF_Rever"
    parser = argparse.ArgumentParser(description="Generate portable stance and slot data")
    parser.add_argument("--build", default=BUILD)
    parser.add_argument(
        "--wiki-stances", type=Path, default=ROOT / "data" / "sources" / "wiki" / "stance_data_2026-08-23.lua"
    )
    parser.add_argument(
        "--rabbit-mods",
        type=Path,
        default=documents / "\u9ed1\u732b4.0-5.0" / "dist" / "WRData" / "data" / "v2_mods.json",
    )
    parser.add_argument(
        "--rabbit-weapons",
        type=Path,
        default=documents / "\u9ed1\u732b4.0-5.0" / "dist" / "WRData" / "data" / "v2_weapons.json",
    )
    parser.add_argument(
        "--warframe-items",
        type=Path,
        default=(
            reverse_root
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-items"
            / "data"
            / "json"
            / "Mods.json"
        ),
    )
    parser.add_argument(
        "--item-i18n",
        type=Path,
        default=(
            reverse_root
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-items"
            / "data"
            / "json"
            / "i18n.json"
        ),
    )
    parser.add_argument(
        "--languages",
        type=Path,
        default=(
            reverse_root
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-languages-bin-data"
        ),
    )
    parser.add_argument(
        "--raw-packages", type=Path,
    )
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data")
    result = parser.parse_args()
    result.raw_packages = result.raw_packages or reverse_root / "wf-arsenal" / "data" / "raw" / result.build / "packages"
    result.export_dir = result.export_dir or ROOT / "data" / "export" / result.build
    return result


def _load_export(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError(f"expected an array export: {path}")
    return rows


def _rabbit_rows(path: Path) -> list[dict[str, Any]]:
    """Read the useful flat rows from the legacy, partially corrupt JSON file."""
    rows: list[dict[str, Any]] = []
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line == "\t{":
            current = []
            continue
        if current is None:
            continue
        if line in {"\t},", "\t}"}:
            row: dict[str, Any] = {}
            for item in current:
                match = re.match(r'^\s*"([^"]+)"\s*:\s*(.*?)\s*,?$', item)
                if not match:
                    continue
                key, value = match.groups()
                try:
                    row[key] = json.loads(value)
                except json.JSONDecodeError:
                    continue
            if row:
                rows.append(row)
            current = None
            continue
        current.append(line)
    return rows


_TOKEN = re.compile(
    r"\s+|--[^\r\n]*|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|"
    r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z0-9_]*|[][{}=,;]"
)


class _LuaTableParser:
    def __init__(self, source: str) -> None:
        marker = "local StanceData ="
        start = source.index(marker) + len(marker)
        self.tokens = [
            token
            for token in _TOKEN.findall(source[start:])
            if not token.isspace() and not token.startswith("--")
        ]
        self.index = 0

    def _peek(self, offset: int = 0) -> str:
        return self.tokens[self.index + offset]

    def _take(self, expected: str | None = None) -> str:
        token = self._peek()
        if expected is not None and token != expected:
            raise ValueError(f"expected {expected!r}, got {token!r} at token {self.index}")
        self.index += 1
        return token

    def parse(self) -> dict[str, Any]:
        value = self._value()
        if not isinstance(value, dict):
            raise ValueError("StanceData root is not a mapping")
        return value

    def _value(self) -> Any:
        token = self._peek()
        if token == "{":
            return self._table()
        self._take()
        if token[0] in {'"', "'"}:
            return ast.literal_eval(token)
        if re.fullmatch(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", token):
            return float(token) if any(char in token for char in ".eE") else int(token)
        if token == "true":
            return True
        if token == "false":
            return False
        if token == "nil":
            return None
        return token

    def _table(self) -> Any:
        self._take("{")
        keyed: dict[Any, Any] = {}
        values: list[Any] = []
        while self._peek() != "}":
            if self._peek() == "[":
                self._take("[")
                key = self._value()
                self._take("]")
                self._take("=")
                keyed[key] = self._value()
            elif self._peek(1) == "=":
                key = self._take()
                self._take("=")
                keyed[key] = self._value()
            else:
                values.append(self._value())
            if self._peek() in {",", ";"}:
                self._take()
        self._take("}")
        if keyed and values:
            for offset, value in enumerate(values, 1):
                keyed.setdefault(offset, value)
            return keyed
        return keyed or values


def _as_numbers(value: Any) -> list[float]:
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, list) and all(isinstance(item, (int, float)) for item in value):
        return [float(item) for item in value]
    return []


def _combo_row(kind: str, combo: dict[str, Any]) -> dict[str, Any] | None:
    total = 0.0
    hit_count = 0.0
    attacks = combo.get("Attacks")
    if not isinstance(attacks, list):
        return None
    for attack in attacks:
        if not isinstance(attack, dict):
            continue
        damage = _as_numbers(attack.get("Dmg"))
        hits = _as_numbers(attack.get("Hits")) or [1.0] * len(damage)
        if len(damage) != len(hits):
            raise ValueError(f"{kind}: Dmg/Hits length mismatch")
        total += sum(dmg * hit for dmg, hit in zip(damage, hits)) / 100.0
        hit_count += sum(hits)
    duration = combo.get("Duration")
    duration_value = float(duration) if isinstance(duration, (int, float)) and duration > 0 else None
    return {
        "kind": kind,
        "name": combo.get("Name"),
        "totalMultiplier": round(total, 6),
        "hitCount": round(hit_count, 6),
        "duration": duration_value,
        "dpsMultiplier": round(total / duration_value, 6) if duration_value else None,
        "statusRateMultiplier": round(hit_count / duration_value, 6)
        if duration_value
        else None,
    }


def _stance_payload(
    build: str,
    wiki_path: Path,
    rabbit_rows: list[dict[str, Any]],
    item_rows: list[dict[str, Any]],
    weapons: list[dict[str, Any]],
    packages: Path,
    zh: dict[str, str],
) -> dict[str, Any]:
    wiki = _LuaTableParser(wiki_path.read_text(encoding="utf-8")).parse()
    rabbit_by_name = {
        str(row.get("NameEn")): row for row in rabbit_rows if row.get("Type") == "STANCE"
    }
    items_by_path = {str(row.get("uniqueName")): row for row in item_rows if row.get("uniqueName")}
    available_tags = {
        str(tag)
        for weapon in weapons
        if weapon.get("slot") == "melee"
        for tag in (weapon.get("compatTags") or [])
    }
    bad_mapping = sorted(set(WEAPON_TYPE_TO_COMPAT_TAG.values()) - available_tags)
    if bad_mapping:
        raise ValueError(f"stance mappings absent from portable compatTags: {bad_mapping}")

    stances: list[dict[str, Any]] = []
    exclusions = {"ConclaveOnly": 0, "StancelessStance": 0, "UniqueToWeapon": 0}
    gaps: list[dict[str, str]] = []
    compat_name_to_tag: dict[str, str] = {}
    for name, stance in wiki.items():
        if not isinstance(stance, dict) or name == "__Legend":
            continue
        excluded = next((key for key in exclusions if stance.get(key) is True), None)
        if excluded:
            exclusions[excluded] += 1
            continue
        weapon_type = str(stance.get("WeaponType") or "")
        compat_tag = WEAPON_TYPE_TO_COMPAT_TAG.get(weapon_type)
        if not compat_tag:
            gaps.append({"name": str(name), "reason": f"unmapped weaponType: {weapon_type}"})
            continue
        meta = rabbit_by_name.get(str(name))
        if not meta:
            gaps.append({"name": str(name), "reason": "missing v2_mods stance metadata"})
            continue
        path = str(meta.get("UniqueName") or "")
        item = items_by_path.get(path) or {}
        compat_name = str(item.get("compatName") or weapon_type)
        previous = compat_name_to_tag.setdefault(compat_name, compat_tag)
        if previous != compat_tag:
            raise ValueError(f"ambiguous compatName mapping: {compat_name}")

        combos = []
        for kind in COMBO_KINDS:
            combo = stance.get(kind)
            row = _combo_row(kind, combo) if isinstance(combo, dict) else None
            if row is not None:
                combos.append(row)
        ranked = [row for row in combos if row["dpsMultiplier"] is not None]
        best = max(ranked, key=lambda row: (row["dpsMultiplier"], row["totalMultiplier"])) if ranked else None
        icon = str(meta.get("Icon") or "")
        raw_path = packages / (path.lstrip("/") + ".json")
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.is_file() else {}
        name_zh = zh.get(str(raw.get("LocalizeTag") or "")) or meta.get("NameZh")
        # 架势描述优先用官方本地化（LocalizeDescTag），兔子源偶发只剩英文原文。
        description_zh = zh.get(str(raw.get("LocalizeDescTag") or "")) or meta.get("Description")
        stances.append(
            {
                "nameEn": str(name),
                "nameZh": name_zh,
                "path": path,
                "icon": icon,
                "iconAsset": "/assets/stances/art/" + icon.lstrip("/") if icon else None,
                "polarity": meta.get("Polarity"),
                "rarity": meta.get("Rarity"),
                "description": description_zh,
                "baseDrain": meta.get("BaseDrain"),
                "maxRank": meta.get("FusionLimit"),
                "weaponType": weapon_type,
                "compatName": compat_name,
                "compatTag": compat_tag,
                "combos": combos,
                "bestCombo": best["kind"] if best else None,
            }
        )

    stances.sort(key=lambda row: (row["weaponType"], row["nameEn"]))
    return {
        "schemaVersion": 1,
        "buildLabel": build,
        "sources": [wiki_path.name, "v2_mods.json", "warframe-items Mods.json", "Languages.bin zh.json"],
        "counts": {
            "stances": len(stances),
            "combos": sum(len(row["combos"]) for row in stances),
            "missingDurations": sum(
                combo["duration"] is None for row in stances for combo in row["combos"]
            ),
            "gaps": len(gaps),
        },
        "excluded": exclusions,
        "compatMappings": {
            "weaponTypeToCompatTag": WEAPON_TYPE_TO_COMPAT_TAG,
            "compatNameToCompatTag": dict(sorted(compat_name_to_tag.items())),
        },
        "stances": stances,
        "gaps": gaps,
    }


def _package_path(packages: Path, source: Path) -> str:
    return "/" + source.relative_to(packages).with_suffix("").as_posix()


def _slot_kind(path: str, raw: dict[str, Any], meta: dict[str, Any]) -> str | None:
    compatibility = str(raw.get("ItemCompatibility") or "").lower()
    mod_type = str(meta.get("Type") or "").upper()
    if path.startswith("/Lotus/Upgrades/EmpoweredHeavyMelee/") or "/Mods/Melee/" in path:
        return "melee"
    if "/Mods/Pistol/" in path or mod_type == "SECONDARY" or "pistol" in compatibility:
        return "secondary"
    if (
        "/Mods/Rifle/" in path
        or "/Mods/Shotgun/" in path
        or mod_type == "PRIMARY"
        or any(value in compatibility for value in ("longgun", "shotgun", "bow"))
    ):
        return "primary"
    if "/Mods/Warframe/" in path or "powersuit" in compatibility or mod_type == "WARFRAME":
        return "warframe"
    return None


def _utility_payload(
    build: str,
    packages: Path,
    portable_mods: list[dict[str, Any]],
    rabbit_rows: list[dict[str, Any]],
    item_rows: list[dict[str, Any]],
    en: dict[str, str],
    zh: dict[str, str],
    i18n: dict[str, Any] | None = None,
) -> dict[str, Any]:
    portable = {str(row.get("path")): row for row in portable_mods if row.get("path")}
    rabbit = {str(row.get("UniqueName")): row for row in rabbit_rows if row.get("UniqueName")}
    items = {str(row.get("uniqueName")): row for row in item_rows if row.get("uniqueName")}
    candidates: dict[str, tuple[Path, dict[str, Any], str]] = {}
    mods_root = packages / "Lotus" / "Upgrades" / "Mods"
    for source in mods_root.rglob("*.json"):
        raw = json.loads(source.read_text(encoding="utf-8"))
        if raw.get("IsUtility") == 1:
            path = _package_path(packages, source)
            candidates[path] = (source, raw, "isUtility")

    tennokai_root = packages / "Lotus" / "Upgrades" / "EmpoweredHeavyMelee"
    for source in tennokai_root.glob("*.json"):
        path = _package_path(packages, source)
        if path not in rabbit or source.stem.endswith(("SubMod", "OnEquip")) or source.stem == "TennokaiBaseMod":
            continue
        candidates[path] = (source, json.loads(source.read_text(encoding="utf-8")), "tennokai")

    records = []
    skipped: list[dict[str, str]] = []
    for path, (_source, raw, source_kind) in sorted(candidates.items()):
        if "/PvPMods/" in path:
            continue
        mod = portable.get(path)
        meta = rabbit.get(path) or {}
        if source_kind == "isUtility" and mod is None:
            skipped.append({"path": path, "reason": "not present in portable mods export"})
            continue
        if mod is not None and mod.get("selectable") is not True:
            skipped.append({"path": path, "reason": "not selectable in portable mods export"})
            continue
        rank = int((mod or {}).get("maxRank") if mod is not None else meta.get("FusionLimit") or 0)
        base_drain = int((mod or {}).get("baseDrain") if mod is not None else meta.get("BaseDrain") or 0)
        slot_kind = _slot_kind(path, raw, meta)
        if slot_kind is None:
            skipped.append({"path": path, "reason": "unclassified slot kind"})
            continue
        icon = str(meta.get("Icon") or raw.get("Icon") or "")
        localize_tag = str(raw.get("LocalizeTag") or "")
        item = items.get(path) or {}
        level_stats = item.get("levelStats") if isinstance(item.get("levelStats"), list) else []
        localized_item = (i18n or {}).get(path, {}).get("zh") or {}
        localized_stats = localized_item.get("levelStats") if isinstance(localized_item.get("levelStats"), list) else []
        effects_zh_by_rank = [row.get("stats") or [] for row in localized_stats if isinstance(row, dict)]
        rank_stats = effects_zh_by_rank[min(rank, len(effects_zh_by_rank) - 1)] if effects_zh_by_rank else (level_stats[min(rank, len(level_stats) - 1)].get("stats") if level_stats else [])
        description = "；".join(str(value) for value in (rank_stats or ()) if value)
        if not description:
            localized = []
            for upgrade in raw.get("Upgrades") or ():
                if not isinstance(upgrade, dict):
                    continue
                template = zh.get(str(upgrade.get("LocTag") or ""))
                value = upgrade.get("Value")
                if template and isinstance(value, (int, float)):
                    localized.append(template.replace("|val|", f"{abs(value) * (rank + 1) * 100:g}"))
            description = "；".join(localized)
        records.append(
            {
                "path": path,
                "nameEn": en.get(localize_tag) or (mod or {}).get("nameEn") or meta.get("NameEn"),
                "nameZh": zh.get(localize_tag) or meta.get("NameZh") or (mod or {}).get("nameZh"),
                "slotKind": slot_kind,
                "exilus": True,
                "polarity": (mod or {}).get("polarity") or meta.get("Polarity") or raw.get("ArtifactPolarity"),
                "rarity": (mod or {}).get("rarity") or meta.get("Rarity") or raw.get("Rarity"),
                "description": description or meta.get("Description") or (mod or {}).get("description") or "",
                "effectsZh": effects_zh_by_rank[-1] if effects_zh_by_rank else None,
                "effectsZhByRank": effects_zh_by_rank or None,
                "effects": list((mod or {}).get("effects") or ()),
                "conditionalEffects": list((mod or {}).get("conditionalEffects") or ()),
                "drain": max(0, base_drain + rank),
                "rank": rank,
                "icon": icon,
                "iconAsset": "/assets/mods/art/" + icon.lstrip("/") if icon else None,
                "sourceKind": source_kind,
                "catalogJoined": mod is not None,
            }
        )
    return {
        "schemaVersion": 1,
        "buildLabel": build,
        "drainSemantics": "maximum-rank capacity cost; rank is the maximum rank",
        "counts": {
            "mods": len(records),
            "isUtility": sum(row["sourceKind"] == "isUtility" for row in records),
            "tennokai": sum(row["sourceKind"] == "tennokai" for row in records),
            "catalogJoined": sum(row["catalogJoined"] for row in records),
            "skipped": len(skipped),
        },
        "mods": records,
        "skipped": skipped,
    }


def _exalted_payload(
    build: str,
    packages: Path,
    portable_weapons: list[dict[str, Any]],
    rabbit_weapons: list[dict[str, Any]],
    languages: Path,
    wiki_path: Path,
) -> dict[str, Any]:
    en = json.loads((languages / "en.json").read_text(encoding="utf-8"))
    zh = json.loads((languages / "zh.json").read_text(encoding="utf-8"))
    wiki = _LuaTableParser(wiki_path.read_text(encoding="utf-8")).parse()
    rabbit_by_path = {
        str(row.get("UniqueName")): row for row in rabbit_weapons if row.get("UniqueName")
    }

    def descends_from(path: str, ancestor: str) -> bool:
        seen: set[str] = set()
        current = path
        while current and current not in seen:
            if current == ancestor:
                return True
            seen.add(current)
            current = str((rabbit_by_path.get(current) or {}).get("Parent") or "")
        return False

    records: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    resolved_owner: dict[str, str] = {}
    root = packages / "Lotus" / "Powersuits"
    for source in root.rglob("*.json"):
        raw = json.loads(source.read_text(encoding="utf-8"))
        built_in = raw.get("MeleeTreeType")
        if not isinstance(built_in, str) or not built_in:
            continue
        source_path = _package_path(packages, source)
        tag = str(raw.get("LocalizeTag") or "")
        compat_tags = [str(value) for value in (raw.get("CompatibilityTags") or [])]
        actual_weapons = sorted(
            (
                row
                for path, row in rabbit_by_path.items()
                if descends_from(path, source_path)
            ),
            key=lambda row: str(row.get("UniqueName")),
        )
        if not actual_weapons:
            unresolved.append(
                {
                    "sourcePath": source_path,
                    "name": en.get(tag) or source.stem,
                    "nameZh": zh.get(tag) or en.get(tag) or source.stem,
                    "builtInStancePath": built_in,
                    "compatTags": compat_tags,
                    "noExternalStance": True,
                    "reason": (
                        "no v2_weapons row descends from this Powersuits source path, and the "
                        "portable weapons export has no exact path or ancestry match"
                    ),
                }
            )
            continue

        direct = [row for row in actual_weapons if row.get("UniqueName") == source_path]
        normal = [row for row in actual_weapons if row.get("VariantType") == "VT_NORMAL"]
        canonical = direct[0] if len(direct) == 1 else normal[0] if len(normal) == 1 else None
        canonical_name = str((canonical or {}).get("NameEn") or "")
        stance_matches = sorted(
            str(name)
            for name, stance in wiki.items()
            if isinstance(stance, dict)
            and canonical_name
            and (str(name) == canonical_name or stance.get("WeaponType") == canonical_name)
        )
        built_in_name = stance_matches[0] if len(stance_matches) == 1 else None

        for actual in actual_weapons:
            path = str(actual.get("UniqueName"))
            previous_owner = resolved_owner.setdefault(path, source_path)
            if previous_owner != source_path:
                raise ValueError(
                    f"ambiguous Powersuits ancestry for {path}: {previous_owner}, {source_path}"
                )
            portable_paths = sorted(
                str(weapon.get("path"))
                for weapon in portable_weapons
                if weapon.get("path") == path or path in (weapon.get("ancestry") or [])
            )
            if len(portable_paths) == 1:
                portable_resolution = {
                    "status": "resolved",
                    "reason": "exact weapon path or ancestry match",
                }
            elif portable_paths:
                portable_resolution = {
                    "status": "ambiguous",
                    "reason": "multiple portable weapon paths match this actual weapon path",
                }
            else:
                portable_resolution = {
                    "status": "unresolved",
                    "reason": (
                        "portable weapons export has no exact path or ancestry match for this "
                        "actual weapon path"
                    ),
                }
            records.append(
                {
                    "path": path,
                    "name": actual.get("NameEn"),
                    "nameEn": actual.get("NameEn"),
                    "nameZh": actual.get("NameZh"),
                    "sourcePath": source_path,
                    "source": "v2_weapons Parent chain from Packages.bin:" + source_path,
                    "builtInStancePath": built_in,
                    "builtInStanceName": built_in_name,
                    "builtInStance": built_in,
                    "compatTags": compat_tags,
                    "noExternalStance": True,
                    "variantType": actual.get("VariantType"),
                    "icon": actual.get("Icon") or raw.get("Icon"),
                    "portablePath": portable_paths[0] if len(portable_paths) == 1 else None,
                    "portablePaths": portable_paths,
                    "portableResolution": portable_resolution,
                    "resolutionSource": "blackcat-v2-weapons-parent-chain",
                }
            )
    records.sort(key=lambda row: row["path"])
    unresolved.sort(key=lambda row: row["sourcePath"])
    source_roots = len({row["sourcePath"] for row in records}) + len(unresolved)
    return {
        "schemaVersion": 2,
        "buildLabel": build,
        "detection": (
            "direct MeleeTreeType Powersuits roots resolved through exact v2_weapons Parent "
            "ancestry; portable joins require exact path or ancestry evidence"
        ),
        "counts": {
            "sourceRoots": source_roots,
            "weapons": len(records),
            "resolvedRoots": source_roots - len(unresolved),
            "unresolvedRoots": len(unresolved),
            "portableJoins": sum(row["portableResolution"]["status"] == "resolved" for row in records),
            "portableUnresolved": sum(
                row["portableResolution"]["status"] == "unresolved" for row in records
            ),
            "builtInStanceNames": sum(bool(row["builtInStanceName"]) for row in records),
        },
        "weapons": records,
        "unresolved": unresolved,
    }


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _args()
    required = (
        args.wiki_stances,
        args.rabbit_mods,
        args.rabbit_weapons,
        args.warframe_items,
        args.raw_packages,
        args.export_dir / "weapons.json",
        args.export_dir / "mods.json",
        args.languages / "en.json",
        args.languages / "zh.json",
    )
    for path in required:
        if not path.exists():
            raise SystemExit(f"required source not found: {path}")

    rabbit_rows = _rabbit_rows(args.rabbit_mods)
    rabbit_weapons = _load_export(args.rabbit_weapons)
    weapons = _load_export(args.export_dir / "weapons.json")
    mods = _load_export(args.export_dir / "mods.json")
    item_rows = json.loads(args.warframe_items.read_text(encoding="utf-8"))
    i18n = json.loads(args.item_i18n.read_text(encoding="utf-8")) if args.item_i18n.is_file() else {}
    en = json.loads((args.languages / "en.json").read_text(encoding="utf-8"))
    zh = json.loads((args.languages / "zh.json").read_text(encoding="utf-8"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "stances.json": _stance_payload(
            args.build, args.wiki_stances, rabbit_rows, item_rows, weapons, args.raw_packages, zh
        ),
        "utility_mods.json": _utility_payload(args.build, args.raw_packages, mods, rabbit_rows, item_rows, en, zh, i18n),
        "exalted_weapons.json": _exalted_payload(
            args.build, args.raw_packages, weapons, rabbit_weapons, args.languages, args.wiki_stances
        ),
    }
    for name, payload in payloads.items():
        _write(args.output_dir / name, payload)
        print(name, json.dumps(payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
