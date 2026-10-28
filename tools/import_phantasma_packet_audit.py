"""Record Phantasma's unreplayed parent packet without guessing final CO/head events."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_companion_projectile_sequences import AuditedPackages, CLIENT_SHA256, PACKAGE_SHA256
PAIRS = (
    ("/Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/RevenantShotgun",
     "/Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/AltFireClusterProj"),
    ("/Lotus/Weapons/Tenno/LongGuns/PrimePhantasma/PhantasmaPrimeShotgun",
     "/Lotus/Weapons/Tenno/LongGuns/PrimePhantasma/PrimeAltFireClusterProj"),
)
WARNINGS = ["phantasma-parent-explosion-and-children-unmodeled",
            "phantasma-explosion-co-and-head-event-routing-unverified"]


def audit(packages, projectile):
    raw = packages.resolve(projectile)
    contact, blast = raw.get("AttackData") or {}, raw.get("ExplosiveAttack") or {}
    if (contact.get("Amount") != 15 or contact.get("Type") != "DT_IMPACT"
            or blast.get("Amount") != 73 or blast.get("Type") != "DT_RADIATION"
            or blast.get("HitType") != "DHT_PROJECTILE"):
        raise ValueError("Phantasma packet source changed")
    return dict(status="partial-native-consumer-no-added-damage", sourceHitType="DHT_PROJECTILE",
        parentExplosion=deepcopy(blast), clientSha256=CLIENT_SHA256, packagesBinSha256=PACKAGE_SHA256,
        nativeSource=projectile, nativeField="ExplosiveAttack",
        packetTypeConsumer="0x141234988 -> 0x140bc28b0: explicit type2 preserved",
        headDamageSuppression="0x140bc29fc sets packet+0x25c; 0x141482db7 consumes separately",
        unresolved=["weapon-parent-handle-lifecycle", "region-recipient-hook-exclusivity",
                    "exactly-once-co-upgrade-context", "head-crit-and-head-kill-qualification",
                    "child-payload-and-target-selection"],
        noPermissionInference="raw HitType does not authorize CO or all weakpoint events")


def merge(reference, exports, packages):
    result = deepcopy(reference)
    for path, projectile in PAIRS:
        row = next(w for w in exports if w["path"] == path)
        mode = row["fireModes"][1]
        if (mode.get("damage", {}).get("projectile") != projectile
                or mode["damage"].get("types") != {"DT_IMPACT": 15.}):
            raise ValueError("Phantasma export identity changed")
        entry = result["auditedAttacks"].setdefault(path, {}).setdefault("modes", {}).setdefault("1", {})
        if any(entry.get(k) for k in ("radial", "radials", "clusters")):
            raise ValueError("Phantasma now has a runtime packet profile; re-evaluate obsolete missing-payload warning")
        entry.update(name=row["nameEn"], fireMode=1, directTotal=15., projectile=projectile,
                     packetAudit=audit(packages, projectile))
        entry["unmodeled"] = list(dict.fromkeys([*(entry.get("unmodeled") or []), *WARNINGS]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--client-exe", type=Path, required=True)
    parser.add_argument("--export", type=Path, default=ROOT / "data/export/2026.08.13.13.24/weapons.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/combat-reference.json")
    args = parser.parse_args()
    if hashlib.sha256(args.client_exe.read_bytes()).hexdigest() != CLIENT_SHA256:
        raise ValueError("client changed; repeat native packet consumer audit")
    packages = AuditedPackages(args.packages_bin)
    result = merge(json.loads(args.output.read_bytes()), json.loads(args.export.read_bytes())["data"], packages)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(dict(weapons=len(PAIRS), addedDamage=0, warnings=WARNINGS)))


if __name__ == "__main__":
    main()
