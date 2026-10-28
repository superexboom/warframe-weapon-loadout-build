"""Import native-audited Deconstructor projectile launch lanes from Packages.bin.

python tools/import_companion_projectile_sequences.py --packages-bin <Packages.bin_H> \
    --client-exe <Warframe.x64.exe> --build-label 2026.10.22.13.12
The source gate belongs to the native sequence consumer audit; new client builds
need an independent consumer review before changing the accepted hashes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_melee_mechanics import Packages
from packages_bin import PackagesBin

PACKAGE_SHA256 = "00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06"
CLIENT_SHA256 = "eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d"
WEAPONS = (
    "/Lotus/Types/Sentinels/SentinelWeapons/SentGlaiveWeapon",
    "/Lotus/Types/Sentinels/SentinelWeapons/DeconstructorPrime/PrimeHeliosGlaiveWeapon",
)
UNVERIFIED = [
    "companion-projectile-bounce-return-timing-unverified",
    "companion-active-projectile-refire-limit-unmodeled",
]


class AuditedPackages(Packages):
    """Hash-pinned directory offsets from the full-exhaustion source audit.

    The generic old-build reader can misidentify this client header. These
    offsets are admitted only after the complete package SHA256 gate passes.
    """
    def __init__(self, path):
        data = path.read_bytes()
        self.sha256 = hashlib.sha256(data).hexdigest()
        if self.sha256 != PACKAGE_SHA256:
            raise ValueError("Packages.bin changed; re-audit projectile lane contract before import")
        reader = PackagesBin.__new__(PackagesBin)
        reader.path, reader.data = path, memoryview(data)
        u32 = lambda at: struct.unpack_from("<I", data, at)[0]
        reader.flags_at, reader.flags_len = 2313, u32(2309)
        reader.size_at, reader.size_len = 86990, u32(86986)
        reader.dict_size = u32(reader.size_at)
        reader.zstd_at, reader.zstd_len = 328449, u32(328445)
        reader.entity_count = u32(reader.zstd_at + reader.zstd_len)
        reader.dir_at = 21456046
        assert reader.entity_count == 468745 and reader.dict_size == 1048576
        reader._init_decompressor()
        self._reader = reader
        self.entities = {e.path: (e.parent, e) for e in reader.iter_entities()}
        assert len(self.entities) == 468744


def weapon_sequence(packages, path):
    raw = packages.resolve(path)
    mode = raw["Behaviors"][0]
    fire = mode["fire:GlaiveProjectileFireBehavior"]
    state = mode["state:WeaponGrenadeStateBehavior"]
    if fire.get("advanceProjectileSequenceOnFire") != 1 or fire.get("chargedProjectileSequenceList"):
        raise ValueError(f"{path}: native-audited normal sequence contract changed")
    projectiles = fire["projectileSequenceList"]
    if len(projectiles) != 3:
        raise ValueError(f"{path}: expected three native-audited lanes")
    lanes = []
    for index, name in enumerate(projectiles):
        projectile = packages.locate(path, name)
        if not projectile:
            raise ValueError(f"{path}: unresolved sequence projectile {name}")
        part = packages.resolve(projectile)
        attack = part["AttackData"]
        kind = attack["Type"]
        if kind != ("DT_IMPACT", "DT_PUNCTURE", "DT_SLASH")[index]:
            raise ValueError(f"{projectile}: audited IPS order changed")
        if part.get("DealDamageThroughImpactBehavior") != 1:
            raise ValueError(f"{projectile}: damage consumer changed")
        lanes.append(dict(projectile=projectile, damageTypes={kind: float(attack["Amount"])},
                          procChance=float(attack["ProcChance"]),
                          forcedProcs=list(attack.get("ForcedProcs") or [])))
    return dict(initialIndex=0, advanceOn="projectile-spawn",
                pelletCountPolicy="integer-floor-plus-Bernoulli-extra", lanes=lanes,
                fireIterations=int(fire["fireIterations"]),
                unverified=list(UNVERIFIED),
                sourceFields=dict(projectileSequenceList=list(projectiles),
                                  advanceProjectileSequenceOnFire=True,
                                  trackProjectiles=bool(state["TrackProjectiles"]),
                                  maxActiveProjectiles=int(state["MaxNumProjectiles"]),
                                  resetRefireWhenActiveProjectiles=bool(state["ResetRefireWhenActiveProjectiles"])))


def extract(packages_path, client_path, build_label):
    if hashlib.sha256(client_path.read_bytes()).hexdigest() != CLIENT_SHA256:
        raise ValueError("native client changed; re-audit sequence consumers before import")
    packages = AuditedPackages(packages_path)
    if packages.sha256 != PACKAGE_SHA256:
        raise ValueError("Packages.bin changed; re-audit projectile lane contract before import")
    return dict(schemaVersion=1, buildLabel=build_label,
                sources=dict(packagesBinSha256=packages.sha256, clientSha256=CLIENT_SHA256,
                             fireConsumer="0x14126d1f0", selectThenAdvance="0x14126e0e4..0x14126e13f",
                             sequenceGetter="0x141809340", initialIndex="0x140fd516f",
                             actualSpawnCount="0x140f75d20", moddedSpawnCount="0x1416a5ed0",
                             evidence="companion-followthrough native static audit 2026-10-28"),
                weapons={path: {"modes": {"0": weapon_sequence(packages, path)}} for path in WEAPONS})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--client-exe", type=Path, required=True)
    parser.add_argument("--build-label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/companion-projectile-sequences.json")
    args = parser.parse_args()
    payload = extract(args.packages_bin, args.client_exe, args.build_label)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8", newline="\n")
    print(json.dumps({"weapons": len(payload["weapons"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
