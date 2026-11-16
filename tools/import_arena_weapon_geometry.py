"""Export weapon spatial fields from a pinned, current Packages.bin (no game execution)."""

from __future__ import annotations
import argparse, gzip, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_melee_mechanics import Packages

FIRE_FIELDS = (
    "traceDistance",
    "tracePunctureDepth",
    "InfinitePunctureDepth",
    "PunchthroughIgnoresAvatars",
    "OnlyHitEnitiesOnce",
    "TraceRadius",
    "Radius",
    "RadialChecksCover",
    "RadialMinCoverDistance",
    "MaxTraceDistanceTime",
    "RetractTime",
    "MultiBeam",
    "projectileType",
    "chargedProjectileType",
    "projectileImpulse",
    "projectileUpImpulse",
    "ApplyFlightSpeedToLaunchImpulse",
    "chargeSpeedMult",
)
PROJECTILE_FIELDS = (
    "KinematicInitialSpeed",
    "KinematicMaxSpeed",
    "KinematicAcceleration",
    "KinematicGravity",
    "MaxLife",
    "DamageRadius",
    "ExplosionFallOff",
    "PunctureDepth",
    "InfinitePunctureDepth",
    "DieOnCollision",
    "DestroyOnCollision",
    "ExplodeOnCollision",
    "IgnoreOwner",
    "IgnoreHeadshotBonus",
    "CheckCover",
    "RadialChecksCover",
    "RadialMinCoverDistance",
    "BounceCount",
    "MaxBounces",
    "ClusterProjectiles",
    "NumClusterProjectiles",
    "ClusterDirection",
    "ClusterArc",
    "ClusterArcShift",
    "MaxLifeVariance",
    "KinematicNoise",
    "KinematicNoiseRate",
    "ExplosionIgnoreCover",
    "ExplosionCoverMinDistance",
    "EmbedTime",
    "EmbedDamageRadius",
    "KinematicGravityMultiplier",
    "KinematicRestitution",
    "KinematicRestitutionParallel",
    "OnProjectileDeathScript",
    "OnProjectileContactScript",
    "OnProjectileStackedScript",
    "StackingDamageRange",
    "StackingDamage",
    "StackRadius",
    "StackingRadius",
    "MaxProjectileStack",
    "AttachAtStack",
    "TimeBetweenAttacks",
    "MaxTargetsPerAttack",
    "MaxChainDepth",
    "ChainDamageMultiplier",
    "ChainDistance",
    "ExplodeOnLifeExpired",
    "EmbedDamageRadius",
)
CHAIN_FIELDS = (
    "NumChains",
    "SequentialChains",
    "ChainDistance",
    "ChainDamageMultiplier",
    "StopChainOnParry",
    "ChainableTypes",
)


def export(packages_path, weapon_path, output):
    p = Packages(packages_path)
    weapons = json.loads(weapon_path.read_text(encoding="utf-8"))
    weapons = weapons.get("data", []) if isinstance(weapons, dict) else weapons
    result = {}
    skipped = []
    for weapon in weapons:
        if weapon.get("slot") not in (
            "primary",
            "secondary",
            "arch_gun",
        ) and weapon.get("productCategory") not in ("LongGuns", "Pistols", "SpaceGuns"):
            continue
        path = weapon["path"]
        if not p.exists(path):
            continue
        try:
            source = p.resolve(path)
        except ValueError as exc:
            skipped.append({"path": path, "reason": str(exc)})
            continue
        behaviors = source.get("Behaviors") or []
        modes = {}
        for index, behavior in enumerate(behaviors):
            fire = next(
                (
                    v
                    for k, v in behavior.items()
                    if k.startswith("fire:") and isinstance(v, dict)
                ),
                None,
            )
            if fire is None:
                continue
            fire_type = behavior.get("fire:Type", "")
            projectile = p.locate(path, fire.get("projectileType") or "")
            row = {
                "nativeFireType": fire_type,
                "fire": {k: fire[k] for k in FIRE_FIELDS if k in fire},
                "projectilePath": projectile,
            }
            if projectile:
                try:
                    proj = p.resolve(projectile)
                except ValueError as exc:
                    skipped.append({"path": projectile, "reason": str(exc)})
                    proj = {}
                row["projectile"] = {k: proj[k] for k in PROJECTILE_FIELDS if k in proj}
                child = p.locate(projectile, proj.get("ClusterProjectiles") or "")
                if not child:
                    script = proj.get("OnProjectileDeathScript") or {}
                    child = p.locate(
                        projectile, script.get("_secondaryProjectile") or ""
                    )
                if child:
                    child_source = p.resolve(child)
                    row["clusterChild"] = {
                        "path": child,
                        "fields": {
                            k: child_source[k]
                            for k in PROJECTILE_FIELDS
                            if k in child_source
                        },
                    }
            impact = next(
                (
                    v
                    for k, v in behavior.items()
                    if k.startswith("impact:") and isinstance(v, dict)
                ),
                {},
            )
            if impact.get("NumChains", 0):
                row["chain"] = {k: impact[k] for k in CHAIN_FIELDS if k in impact}
            modes[str(index)] = row
        if modes:
            result[path] = modes
    # Audited adapters can supply additional source projectile types absent from the
    # old canonical fire-mode list (Grimoire alt, Nox, reload grenades).
    projectile_records = {}
    reference = json.loads(
        (ROOT / "data/mechanics/combat-reference.json").read_text(encoding="utf-8")
    )

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key
                    in (
                        "projectile",
                        "nativeSource",
                        "nativeChild",
                        "child",
                        "carrier",
                        "path",
                    )
                    and isinstance(item, str)
                    and item.startswith("/")
                    and p.exists(item)
                ):
                    if item not in projectile_records:
                        try:
                            resolved = p.resolve(item)
                            if any(
                                k in resolved
                                for k in (
                                    "KinematicInitialSpeed",
                                    "MaxLife",
                                    "DamageRadius",
                                )
                            ):
                                projectile_records[item] = {
                                    k: resolved[k]
                                    for k in PROJECTILE_FIELDS
                                    if k in resolved
                                }
                        except ValueError:
                            pass
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(reference)
    collect(
        json.loads(
            (ROOT / "data/mechanics/weapon-passives.json").read_text(encoding="utf-8")
        )
    )
    record = {
        "schemaVersion": 1,
        "projectileRecords": projectile_records,
        "gameBuild": "2026.10.28.09.54",
        "sourcePackagesSha256": p.sha256,
        "sourceWeaponsSha256": hashlib.sha256(weapon_path.read_bytes()).hexdigest(),
        "weapons": result,
        "skipped": skipped,
        "notes": [
            "Raw authored fields; native units/physics semantics are separate from serialization.",
            "Spatial source is independently versioned from the frozen base weapon dataset.",
            "Missing range/penetration remains unknown; runtime must diagnose any configured fallback.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode()
    output.write_bytes(gzip.compress(data, mtime=0))
    print(
        json.dumps(
            {
                "weapons": len(result),
                "modes": sum(len(m) for m in result.values()),
                "skipped": len(skipped),
                "bytes": output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--packages", type=Path, required=True)
    a.add_argument(
        "--weapons",
        type=Path,
        default=ROOT / "data/export/2026.08.13.13.24/weapons.json",
    )
    a.add_argument(
        "--output", type=Path, default=ROOT / "data/arena/weapon-geometry.json.gz"
    )
    args = a.parse_args()
    export(args.packages, args.weapons, args.output)
