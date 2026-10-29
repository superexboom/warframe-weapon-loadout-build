"""Retain proven Zymos child declarations and unresolved consumer diagnostics.

This importer adds no child damage and no global trigger veto. The admitted
script/native evidence proves shared metadata consumption, five-child candidate
branches and modifier-bucket transfer, not target coverage or final gameplay DPS.
"""
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

PREFIX = "/Lotus/Weapons/Infested/Pistols/InfUzi/"
WEAPON = PREFIX + "InfUziWeapon"
PROJECTILE = PREFIX + "InfUziProjectile"
CARRIER = PREFIX + "EmbedDeathKillClusterProj"
CHILD = PREFIX + "EmbedDeathKillGuidedProj"
SCRIPT = "/Lotus/Scripts/WeaponAttachments/InfUziWeapon.lua"
SCRIPT_SHA256 = "47a343ce7d22c4948178bb11067b2532e082729b310853438a64c647ad1e7751"
WARNINGS = ["zymos-child-spawn-and-targeting-unmodeled",
            "zymos-child-damage-inheritance-and-event-routing-unverified"]


def child_audit(packages):
    parent, carrier, child = (packages.resolve(path) for path in (PROJECTILE, CARRIER, CHILD))
    for key, function in (("EmbedDeathAttackHitScript", "OnRadialDamage"),
                          ("OnProjectileDeathScript", "OnDeath")):
        callback = parent.get(key) or {}
        if (callback.get("Script"), callback.get("Function"), callback.get("_projectileType")) != (
                SCRIPT, function, "EmbedDeathKillClusterProj"):
            raise ValueError("Zymos child callback contract changed")
    if (parent.get("ValidEmbedPart") != "HEAD"
            or carrier.get("ClusterProjectiles") != "EmbedDeathKillGuidedProj"
            or carrier.get("ClusterSetsChildrenDamageInfo") != 1
            or child.get("SendEvents") != 0 or child.get("DamageUpgradeTypes") != []
            or (child.get("ExplosiveAttack") or {}).get("Amount") != 333
            or (child.get("ExplosiveAttack") or {}).get("Type") != "DT_POISON"):
        raise ValueError("Zymos child declaration contract changed")
    return dict(status="partial-consumer-audit-no-added-damage", carrier=CARRIER, child=CHILD,
        script=SCRIPT, scriptSha256=SCRIPT_SHA256, packagesBinSha256=PACKAGE_SHA256,
        clientSha256=CLIENT_SHA256,
        callbackBranches=[dict(callback="OnRadialDamage", prototype=3, requestedChildCount=5),
                          dict(callback="OnDeath", prototype=4, requestedChildCount=5)],
        branchCombination="shared-record-consumed-once-do-not-sum",
        metadataConsumption=dict(lookupPrototype=1,lookupPc=[12,40],removePc=[43,48],
            sharedClosure="P7 pc13/17 capture same P1; both branches remove before spawning",
            scope="one stored host embed record cannot authorize both five-child requests; multiple independent records and failed callbacks remain separate"),
        childCountSetter="0x141b454b0 -> mNumClusterProjectiles+0x1730",
        childDeclarations=dict(attack=deepcopy(child["ExplosiveAttack"]),
            criticalChance=child.get("CriticalChance"), criticalMultiplier=child.get("CriticalMultiplier"),
            SendEvents=child["SendEvents"], DamageUpgradeTypes=child["DamageUpgradeTypes"],
            ClusterSetsChildrenDamageInfo=carrier["ClusterSetsChildrenDamageInfo"]),
        scriptHitClassification=dict(flag="Projectile+0x15b1 set by InfUzi P3/P4 Lua atom44bcd6fd ->0x1419850a0",
            inherited="0x14121a561 copies carrier flag to child",
            consumer="0x141234988..0x141234998 overrides radial plan hit type with DHT_SCRIPT=5",
            scope="classification only; does not establish head, CO or Arcane notification eligibility"),
        provenNoticeConsumers=["0x1407eb9b2", "0x14093a39e", "0x14098be19", "0x1410e32a9"],
        criticalTransfer=dict(consumer="0x141219c80 -> 0x14140ab20 / 0x140848e20",
            upgradeManager="0x1401413d0 -> inventory+0x408 -> UpgradeManager+0xc0 / 0x1418c1aa0",
            retainedBuckets="Projectile ctor FloatUpgradedValue vtable0x1420a3d48 +8 returns1; do not flatten before copying",
            merge="0x141a1aeb0 -> 0x140d12e30; STACKING_MULTIPLY adds into retained bucket, MULTIPLY multiplies",
            getter="0x14123df60",
            radialPlanCopy="0x140f36198 ->0x140ede780 copies538/570 buckets; prior plan chance enters ADD bucket and prior multiplier enters MULTIPLY bucket",
            verification="tools/verify_projectile_crit_transfer.py; 24 original-byte control cases",
            example=dict(base=.05,stackingBonus=1.2,afterOneQuery=.11,afterTwoQueries=.17),
            scope="transfer primitive only; complete carrier creation/query count and subsequent victim-side crit transforms not closed"),
        unresolved=["child-target-selection",
                    "complete-carrier-creation-and-damage-snapshot", "final-critical-query-count-and-victim-side-transforms",
                    "status-and-kill-event-consumers"])


def merge(reference, evidence):
    result = deepcopy(reference)
    entry = result["auditedAttacks"][WEAPON]
    if entry.get("projectile") != PROJECTILE or entry.get("directTotal") != 23.:
        raise ValueError("Zymos runtime profile identity changed")
    entry["childSpawnAudit"] = evidence
    entry["unmodeled"] = list(dict.fromkeys([*(entry.get("unmodeled") or []), *WARNINGS]))
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--packages-bin", type=Path, required=True)
    ap.add_argument("--client-exe", type=Path, required=True)
    ap.add_argument("--script-body", type=Path, required=True)
    ap.add_argument("--output", type=Path, default=ROOT / "data/mechanics/combat-reference.json")
    args = ap.parse_args()
    for path, expected in ((args.client_exe, CLIENT_SHA256), (args.script_body, SCRIPT_SHA256)):
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("source changed; repeat native/script consumer audit")
    evidence = child_audit(AuditedPackages(args.packages_bin))
    reference = json.loads(args.output.read_text(encoding="utf-8"))
    args.output.write_text(json.dumps(merge(reference, evidence), ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps(dict(weapon=WEAPON, addedDamage=0, warnings=WARNINGS)))


if __name__ == "__main__":
    main()
