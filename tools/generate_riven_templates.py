from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_sources import provenance_path  # noqa: E402


SCHEMA_VERSION = 1


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract auditable Riven dispositions and stat templates from Packages"
    )
    parser.add_argument("--build", required=True)
    parser.add_argument("--raw-packages", type=Path, required=True)
    parser.add_argument("--localization", type=Path, required=True)
    parser.add_argument("--weapons", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _localization_rows(payload: Any) -> dict[str, str]:
    if isinstance(payload, Mapping):
        source = payload.get("data", payload)
        if isinstance(source, Mapping):
            return {
                str(key): str(value)
                for key, value in source.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    raise ValueError("localization must be a JSON object or an object with a data map")


def _weapon_rows(payload: Any, build: str) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or payload.get("buildLabel") != build:
        raise ValueError(f"weapons buildLabel does not match --build {build}")
    rows = payload.get("data")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ValueError("weapons must contain a data array")
    return [dict(row) for row in rows]


def _template_kind(stem: str) -> str:
    folded = stem.casefold()
    for token, kind in (
        ("archgun", "archgun"),
        ("shotgun", "shotgun"),
        ("pistol", "pistol"),
        ("melee", "melee"),
        ("rifle", "rifle"),
    ):
        if token in folded:
            return kind
    return "unknown"


def _localized(localization: Mapping[str, str], tag: Any) -> str | None:
    return localization.get(str(tag)) if isinstance(tag, str) and tag else None


def _upgrade_rows(entry: Mapping[str, Any], localization: Mapping[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in entry.get("Upgrades") or ():
        if not isinstance(item, Mapping):
            continue
        upgrade = item.get("Upgrade") if isinstance(item.get("Upgrade"), Mapping) else {}
        schema = item.get("Schema") if isinstance(item.get("Schema"), Mapping) else {}
        loc_tag = schema.get("LocTag")
        rows.append(
            {
                "upgradeType": upgrade.get("UpgradeType"),
                "operation": upgrade.get("OperationType"),
                "rawValue": upgrade.get("Value"),
                "damageType": upgrade.get("DamageType"),
                "symbolFilter": upgrade.get("SymbolFilter"),
                "validModifiers": list(upgrade.get("ValidModifiers") or ()),
                "validPostures": list(upgrade.get("ValidPostures") or ()),
                "validProcTypes": list(upgrade.get("ValidProcTypes") or ()),
                "validType": upgrade.get("ValidType"),
                "locTag": loc_tag,
                "localizedText": _localized(localization, loc_tag),
                "displayAsMultiplier": schema.get("DisplayAsMultiplier"),
                "displayAsPercent": schema.get("DisplayAsPercent"),
                "smallerIsBetter": schema.get("SmallerIsBetter"),
            }
        )
    return rows


def build_payload(
    build: str,
    raw_packages: Path,
    localization_path: Path,
    weapons_path: Path,
) -> dict[str, Any]:
    localization = _localization_rows(_load(localization_path))
    weapons = _weapon_rows(_load(weapons_path), build)
    weapons_by_path = {str(row.get("path")): row for row in weapons if row.get("path")}
    source_dir = raw_packages / "Lotus" / "Upgrades" / "Mods" / "Randomized"
    sources = sorted(source_dir.glob("*RandomModRare.json"))
    if not sources:
        raise ValueError(f"no *RandomModRare.json files under {source_dir}")

    templates: list[dict[str, Any]] = []
    duplicate_paths: dict[str, list[str]] = {}
    disposition_owners: dict[str, list[str]] = {}
    omega_mismatches: list[dict[str, Any]] = []
    missing_weapon_paths: list[str] = []
    localization_tags: set[str] = set()

    for source in sources:
        raw = _load(source)
        if not isinstance(raw, Mapping):
            raise ValueError(f"template is not an object: {source}")
        template_path = "/" + source.relative_to(raw_packages).with_suffix("").as_posix()
        dispositions: list[dict[str, Any]] = []
        for item in raw.get("ItemCompatibilities") or ():
            if not isinstance(item, Mapping) or not item.get("ItemType"):
                continue
            weapon_path = str(item["ItemType"])
            disposition = item.get("Attenuation")
            weapon = weapons_by_path.get(weapon_path)
            weapon_omega = weapon.get("omegaAttenuation") if weapon else None
            if weapon is None:
                omega_status = "weapon-not-exported"
                missing_weapon_paths.append(weapon_path)
            elif not isinstance(weapon_omega, (int, float)):
                omega_status = "weapon-omega-missing"
            elif isinstance(disposition, (int, float)) and math.isclose(
                float(disposition), float(weapon_omega), rel_tol=0.0, abs_tol=1e-5
            ):
                omega_status = "match"
            else:
                omega_status = "mismatch"
            if weapon is not None and omega_status != "match":
                omega_mismatches.append(
                    {
                        "path": weapon_path,
                        "template": template_path,
                        "templateAttenuation": disposition,
                        "weaponOmegaAttenuation": weapon_omega,
                    }
                )
            disposition_owners.setdefault(weapon_path, []).append(template_path)
            dispositions.append(
                {
                    "path": weapon_path,
                    "attenuation": disposition,
                    "rarity": item.get("Rarity"),
                    "weapon": (
                        {
                            "nameInternal": weapon.get("nameInternal"),
                            "nameEn": weapon.get("nameEn"),
                            "nameZh": weapon.get("nameZh"),
                            "slot": weapon.get("slot"),
                            "omegaAttenuation": weapon_omega,
                        }
                        if weapon
                        else None
                    ),
                    "omegaStatus": omega_status,
                }
            )

        stats: list[dict[str, Any]] = []
        for entry in raw.get("UpgradeEntries") or ():
            if not isinstance(entry, Mapping):
                continue
            prefix_tag = entry.get("LocalizePrefixTag")
            suffix_tag = entry.get("LocalizeSuffixTag")
            localization_tags.update(
                str(tag) for tag in (prefix_tag, suffix_tag) if isinstance(tag, str) and tag
            )
            upgrades = _upgrade_rows(entry, localization)
            localization_tags.update(
                str(row["locTag"])
                for row in upgrades
                if isinstance(row.get("locTag"), str) and row["locTag"]
            )
            stats.append(
                {
                    "tag": entry.get("Tag"),
                    "prefixTag": prefix_tag,
                    "prefix": _localized(localization, prefix_tag),
                    "suffixTag": suffix_tag,
                    "suffix": _localized(localization, suffix_tag),
                    "canBeBuff": bool(entry.get("CanBeBuff")),
                    "canBeCurse": bool(entry.get("CanBeCurse")),
                    "rarity": entry.get("Rarity"),
                    "compatibilityTags": list(entry.get("CompatibilityTags") or ()),
                    "buffRestrictions": list(entry.get("BuffRestrictions") or ()),
                    "curseRestrictions": list(entry.get("CurseRestrictions") or ()),
                    "icon": entry.get("Icon"),
                    "upgrades": upgrades,
                }
            )

        name_tag = raw.get("LocalizeTag")
        description_tag = raw.get("LocalizeDescTag")
        localization_tags.update(
            str(tag)
            for tag in (name_tag, description_tag)
            if isinstance(tag, str) and tag
        )
        templates.append(
            {
                "id": source.stem,
                "weaponType": _template_kind(source.stem),
                "sourcePath": template_path,
                "sourceSha256": _sha256(source),
                "itemCompatibility": raw.get("ItemCompatibility"),
                "nameTag": name_tag,
                "name": _localized(localization, name_tag),
                "descriptionTag": description_tag,
                "description": _localized(localization, description_tag),
                "dispositions": dispositions,
                "stats": stats,
            }
        )

    duplicate_paths = {
        path: owners for path, owners in disposition_owners.items() if len(owners) > 1
    }
    missing_localization = sorted(tag for tag in localization_tags if tag not in localization)
    all_dispositions = [row for template in templates for row in template["dispositions"]]
    all_stats = [row for template in templates for row in template["stats"]]
    all_upgrades = [row for stat in all_stats for row in stat["upgrades"]]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "buildLabel": build,
        "sources": {
            "rawPackages": provenance_path(raw_packages),
            "localization": {
                "path": provenance_path(localization_path),
                "sha256": _sha256(localization_path),
            },
            "weapons": {
                "path": provenance_path(weapons_path),
                "sha256": _sha256(weapons_path),
            },
        },
        "counts": {
            "templates": len(templates),
            "dispositions": len(all_dispositions),
            "uniqueDispositionPaths": len(disposition_owners),
            "joinedWeapons": sum(row["weapon"] is not None for row in all_dispositions),
            "matchingWeaponOmega": sum(row["omegaStatus"] == "match" for row in all_dispositions),
            "omegaMismatches": len(omega_mismatches),
            "missingWeaponPaths": len(set(missing_weapon_paths)),
            "statEntries": len(all_stats),
            "upgradeRows": len(all_upgrades),
            "localizedTags": len(localization_tags) - len(missing_localization),
            "missingLocalizationTags": len(missing_localization),
        },
        "templates": templates,
        "audit": {
            "duplicateDispositionPaths": duplicate_paths,
            "omegaMismatches": omega_mismatches,
            "missingWeaponPaths": sorted(set(missing_weapon_paths)),
            "missingLocalizationTags": missing_localization,
        },
    }


def main() -> int:
    args = _args()
    try:
        payload = build_payload(
            args.build,
            args.raw_packages,
            args.localization,
            args.weapons,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
