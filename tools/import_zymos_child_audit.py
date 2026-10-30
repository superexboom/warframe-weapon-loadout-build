"""Refresh the source contract for the ordered, opt-in Zymos child adapter.

Source consumers and construction order are audited independently of the
selected flight/coverage policy. Default geometry adds no child damage.
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
RETIRED_WARNINGS = {"zymos-child-spawn-and-targeting-unmodeled",
                    "zymos-child-damage-inheritance-and-event-routing-unverified"}
WARNINGS = ["zymos-child-external-source-context-defaults"]


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
    return dict(status="ordered-source-adapter-with-explicit-contact-policy", carrier=CARRIER, child=CHILD,
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
            scope="contact retains SCRIPT5; explicit explosion victim is overwritten by c24 PROJECTILE2; surrounding scene retains SCRIPT5"),
        provenNoticeConsumers=["0x1407eb9b2", "0x14093a39e", "0x14098be19", "0x1410e32a9"],
        criticalTransfer=dict(consumer="0x141219c80 -> 0x14140ab20 / 0x140848e20",
            upgradeManager="0x1401413d0 -> inventory+0x408 -> UpgradeManager+0xc0 / 0x1418c1aa0",
            retainedBuckets="Projectile ctor FloatUpgradedValue vtable0x1420a3d48 +8 returns1; do not flatten before copying",
            merge="0x141a1aeb0 -> 0x140d12e30; STACKING_MULTIPLY adds into retained bucket, MULTIPLY multiplies",
            getter="0x14123df60",
            radialPlanCopy="0x140f36198 ->0x140ede780 copies538/570 buckets; prior plan chance enters ADD bucket and prior multiplier enters MULTIPLY bucket",
            verification="tools/verify_projectile_crit_transfer.py; 24 original-byte control cases",
            example=dict(base=.05,stackingBonus=1.2,afterOneQuery=.11,afterTwoQueries=.17),
            scope="two surviving ordinary queries after normal registration/reset; Enervate is a timed ordinary244 ADD query, not contextual df4/ff8"),
        orderedAdapter=dict(module="wfarsenal.zymos", sharedRecordChildCount=5,
            copiedContactAmount="int(current primary damage query * fresh callback fire count)",
            callbackFireCount="140d4f1ea clears fire+64 before return; delayed callback uses fresh floor+Bernoulli",
            sourceQueries="carrier callback then child creation after next update; retained CC/CD buckets",
            enervate="CritOnHit enum244 ADD; inventory+440/+408 share UpgradeManager[c88]",
            packets=[dict(field="AttackData", hitType="DHT_SCRIPT",co="same current packet once",victimCrit=False),
                     dict(field="ExplosiveAttack",amount=333,hitType="DHT_PROJECTILE",co=False,victimCrit=True)],
            geometry="explicit surviving-original-victim body contacts; arrival and frame duration are scenario inputs"),
        unresolved=["actual-trajectory-contact-and-head-geometry", "external-creator-and-avatar-context-defaults"])


def merge(reference, evidence):
    result = deepcopy(reference)
    entry = result["auditedAttacks"][WEAPON]
    if entry.get("projectile") != PROJECTILE or entry.get("directTotal") != 23.:
        raise ValueError("Zymos runtime profile identity changed")
    entry["childSpawnAudit"] = evidence
    entry["unmodeled"] = list(dict.fromkeys([*(n for n in entry.get("unmodeled",[]) if n not in RETIRED_WARNINGS), *WARNINGS]))
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
