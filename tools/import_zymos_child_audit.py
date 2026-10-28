"""Retain proven Zymos child declarations and unresolved consumer diagnostics.

This importer adds no child damage and no global trigger veto. The admitted
script/native evidence proves five-child spawn branches and projectile notice
suppression, not spawn multiplicity, inherited damage or status/kill eligibility.
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
        branchCombination="unresolved-do-not-sum", childCountSetter="0x141b454b0 -> mNumClusterProjectiles+0x1730",
        childDeclarations=dict(attack=deepcopy(child["ExplosiveAttack"]),
            criticalChance=child.get("CriticalChance"), criticalMultiplier=child.get("CriticalMultiplier"),
            SendEvents=child["SendEvents"], DamageUpgradeTypes=child["DamageUpgradeTypes"],
            ClusterSetsChildrenDamageInfo=carrier["ClusterSetsChildrenDamageInfo"]),
        provenNoticeConsumers=["0x1407eb9b2", "0x14093a39e", "0x14098be19", "0x1410e32a9"],
        unresolved=["shared-embed-metadata-spawn-exclusivity", "child-target-selection",
                    "parent-to-child-damage-snapshot", "critical-and-mod-upgrade-routing",
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
