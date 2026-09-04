"""Freeze Kitgun component overrides for the bundled simulator."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


BARREL_ROOTS = (
    "/Lotus/Weapons/SolarisUnited/Secondary/SUModularSecondarySet1/Barrel",
    "/Lotus/Weapons/Infested/Pistols/InfKitGun/Barrels",
)
HANDLE_ROOTS = (
    ("/Lotus/Weapons/SolarisUnited/Primary/SUModularPrimarySet1/Handles", "primary"),
    ("/Lotus/Weapons/SolarisUnited/Secondary/SUModularSecondarySet1/Handle", "secondary"),
    ("/Lotus/Weapons/Infested/Pistols/InfKitGun/Handles/InfPrimaryHandle", "primary"),
    ("/Lotus/Weapons/Infested/Pistols/InfKitGun/Handles/InfSecondaryHandle", "secondary"),
)
CLIP_ROOTS = (
    "/Lotus/Weapons/SolarisUnited/Secondary/SUModularSecondarySet1/Clip",
    "/Lotus/Weapons/Infested/Pistols/InfKitGun/Clips",
)
GUN_TYPES = {
    "SUModularSecondaryBarrelAPart": "GT_SHOTGUN",
    "SUModularSecondaryBarrelBPart": "GT_RIFLE",
    "SUModularSecondaryBarrelCPart": "GT_RIFLE",
    "SUModularSecondaryBarrelDPart": "GT_BEAM",
    "InfModularBarrelBeamPart": "GT_BEAM",
    "InfModularBarrelEggPart": "GT_SHOTGUN",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--build-label", default="2026.08.13.13.24")
    parser.add_argument("--localization", type=Path, required=True)
    parser.add_argument(
        "--wpep-weapons",
        type=Path,
        help="WPEP v2_weapons.json used for the provenance hash",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def localized_names(path: Path) -> dict[str, tuple[str, str]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {
        str(row.get("UniqueName") or row.get("RabbitID")): (
            str(row.get("NameEn") or ""),
            str(row.get("NameZh") or ""),
        )
        for row in rows
        if isinstance(row, Mapping)
    }


def main() -> int:
    args = parse_args()
    sys.path.insert(0, str(args.source_root / "src"))
    from wfarsenal import packages
    from wfarsenal.extract import _attack_data, _damage_block, _sub_behaviour

    index = packages.load(args.source_root / "data" / "raw" / args.build_label)
    names = localized_names(args.localization)

    def identity(path: str) -> dict[str, Any]:
        name_en, name_zh = names.get(path, ("", ""))
        return {"path": path, "nameEn": name_en, "nameZh": name_zh}

    def attack_data(obj: Mapping[str, Any]) -> dict[str, Any] | None:
        result = _attack_data(dict(obj))
        if not result:
            return None
        attack = obj.get("AttackData")
        if isinstance(attack, Mapping) and not result.get("types"):
            damage_type = attack.get("Type")
            if isinstance(damage_type, str) and damage_type.startswith("DT_"):
                result["types"] = {damage_type: result["total"]}
                result["shares"] = {damage_type: 1.0}
        return result

    def projectile(path: str, owner: str) -> tuple[str, Mapping[str, Any]]:
        resolved = path
        if not path.startswith("/"):
            resolved = str(PurePosixPath(owner).parent / path)
        resolved = packages.normalize(resolved)
        obj = dict(index.resolve(resolved))
        raw = index.get(resolved) or {}
        if isinstance(raw.get("AttackData"), Mapping):
            inherited = obj.get("AttackData") or {}
            if "/InfKitGun/Barrels/InfBarrelEgg/" in resolved:
                attack = dict(raw["AttackData"])
                for key in ("Type", "ProcChance", "ForcedProcs"):
                    if key not in attack and key in inherited:
                        attack[key] = inherited[key]
            else:
                attack = dict(inherited)
                attack.update(raw["AttackData"])
            obj["AttackData"] = attack
        return resolved, obj

    def add_explosion(damage: dict[str, Any], obj: Mapping[str, Any]) -> None:
        raw = obj.get("ExplosiveAttack")
        if not isinstance(raw, Mapping) or not raw.get("Amount"):
            return
        radial = _damage_block(dict(raw), amount_key="Amount", proc_key="ProcChance")
        if not radial.get("types"):
            damage_type = raw.get("Type")
            if isinstance(damage_type, str) and damage_type.startswith("DT_"):
                radial["types"] = {damage_type: radial["total"]}
                radial["shares"] = {damage_type: 1.0}
        radial["radius"] = obj.get("DamageRadius")
        radial["falloff"] = obj.get("ExplosionFallOff")
        damage["radial"] = radial

    def mode(owner: str, behavior: Mapping[str, Any], projectile_key: str, index_value: int) -> dict[str, Any] | None:
        fire = _sub_behaviour(dict(behavior), "fire:") or {}
        state = _sub_behaviour(dict(behavior), "state:") or {}
        impact = _sub_behaviour(dict(behavior), "impact:") or {}
        damage: dict[str, Any] | None = None
        has_clusters = False
        projectile_path = fire.get(projectile_key)
        if projectile_key == "chargedProjectileType" and not projectile_path:
            return None
        if isinstance(projectile_path, str) and projectile_path:
            resolved, obj = projectile(projectile_path, owner)
            has_clusters = bool(obj.get("NumClusterProjectiles"))
            damage = attack_data(obj)
            if damage:
                damage["projectile"] = resolved
                damage["flightSpeed"] = obj.get("KinematicInitialSpeed")
                add_explosion(damage, obj)
        if damage is None:
            damage = attack_data(impact) or attack_data(fire)
        if damage is None:
            return None
        unsupported = []
        if impact.get("NumChains") or impact.get("ChainDamageMultiplier"):
            unsupported.append("kitgun-chain-damage-unapplied")
        if has_clusters:
            unsupported.append("kitgun-cluster-damage-unapplied")
        return {
            "index": index_value,
            "trigger": state.get("LocTag"),
            "chargeTime": state.get("ChargeTime") or state.get("chargeTime"),
            "isAlternateFire": bool(state.get("IsAlternateFire")),
            "ammoCost": fire.get("ammoRequirement"),
            "ammoType": fire.get("ammoType"),
            "multishot": 1 if unsupported else fire.get("fireIterations", 1),
            "fireRateRaw": state.get("fireRate"),
            "fireRate": (float(state["fireRate"]) / 60.0) if state.get("fireRate") else None,
            "reloadTime": state.get("reloadTime"),
            "damage": damage,
            "unsupported": unsupported,
        }

    def modes(owner: str, behavior: Mapping[str, Any]) -> list[dict[str, Any]]:
        result = []
        normal = mode(owner, behavior, "projectileType", 0)
        if normal:
            result.append(normal)
        charged = mode(owner, behavior, "chargedProjectileType", len(result))
        if charged:
            result.append(charged)
        return result

    def override_rows(obj: Mapping[str, Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
        return [
            {field[0].lower() + field[1:]: row.get(field) for field in fields if row.get(field) is not None}
            for row in obj.get("Overrides", [])
            if isinstance(row, Mapping)
        ]

    barrels: dict[str, Any] = {}
    for root in BARREL_ROOTS:
        for path in sorted(index.iter_paths(root)):
            leaf = PurePosixPath(path).name
            if leaf not in GUN_TYPES:
                continue
            obj = index.resolve(path)
            record = identity(path)
            record.update(
                {
                    "barrelType": obj.get("BarrelType"),
                    "gunType": obj.get("GunType") or GUN_TYPES[leaf],
                    "compatTags": obj.get("CompatibilityTags") or [],
                    "omegaAttenuation": obj.get("OmegaAttenuation"),
                    "primaryOmegaAttenuation": obj.get("PrimaryOmegaAttenuation")
                    if obj.get("PrimaryOmegaAttenuation") is not None
                    else obj.get("PrimeOmegaAttenuation"),
                    "primeOmegaAttenuation": obj.get("PrimeOmegaAttenuation")
                    if obj.get("PrimeOmegaAttenuation") is not None
                    else obj.get("PrimaryOmegaAttenuation"),
                    "secondaryModes": modes(path, obj.get("BehaviorOverrides") or {}),
                    "primaryModes": modes(path, obj.get("PrimaryBehaviorOverrides") or {}),
                }
            )
            barrels[path] = record

    handles: dict[str, Any] = {}
    for root, slot in HANDLE_ROOTS:
        for path in sorted(index.iter_paths(root)):
            if not path.endswith("Part"):
                continue
            obj = index.resolve(path)
            record = identity(path)
            record.update(
                {
                    "slot": slot,
                    "overrides": override_rows(
                        obj, ("BarrelType", "GunType", "Damage", "FireRate", "TraceDistance")
                    ),
                }
            )
            handles[path] = record

    clips: dict[str, Any] = {}
    for root in CLIP_ROOTS:
        for path in sorted(index.iter_paths(root)):
            if not path.endswith("Part"):
                continue
            obj = index.resolve(path)
            record = identity(path)
            record["overrides"] = override_rows(
                obj,
                (
                    "BarrelType",
                    "GunType",
                    "CritChance",
                    "CritMultiplier",
                    "ProcChance",
                    "MagazineSize",
                    "ReloadTime",
                ),
            )
            clips[path] = record

    wpep_path = args.wpep_weapons
    if wpep_path is None and args.localization.name.casefold() == "v2_weapons.json":
        wpep_path = args.localization
    if wpep_path is None or not wpep_path.is_file():
        raise SystemExit("--wpep-weapons must point to the WPEP v2_weapons.json snapshot")
    payload = {
        "schemaVersion": 1,
        "buildLabel": args.build_label,
        "wpepWeaponsSha256": hashlib.sha256(wpep_path.read_bytes()).hexdigest(),
        "barrels": barrels,
        "handles": handles,
        "clips": clips,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"kitguns: {len(barrels)} barrels, {len(handles)} handles, {len(clips)} clips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
