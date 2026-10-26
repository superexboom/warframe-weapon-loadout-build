"""Model the Vectis Incarnon orb in data/mechanics/combat-reference.json.

    python tools/import_vectis_incarnon_orb.py --packages <raw build dir>

The Incarnon Form projectile (OnProjectileStoppedScript VectisIncarnon.lua)
lands its direct hit, then embeds an orb whose ``EmbedAttack`` hits at once.
On a body shot the orb stays ``EmbedTime`` (2.5 s) and hits twice more; on a
headshot it instead explodes ``_growthDuration`` (0.4 s) later with two
simultaneous ``ExplosiveAttack`` hits. WFSim's direct measurements M117/M118
place the later body hits at 1 and 2 seconds, and the head explosions inherit
the shot's additive headshot bracket without the victim's head multiplier.
The script creates a separate growing projectile; its explosion remains
scheduled when the original victim dies.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from wfarsenal.packages import load  # noqa: E402

WEAPONS = ("/Lotus/Weapons/Tenno/LongGuns/PrimeVectis/PrimeVectisRifle", "/Lotus/Weapons/Tenno/Rifle/TennoSniperRifle")
SCRIPT = "VectisIncarnon.lua"


def part(raw: dict, field: str, radius: str, falloff: str, **extra) -> dict:
    attack = raw[field]
    return dict(
        takes_condition_overload=False, takes_multishot=True,
        damage={attack["Type"]: float(attack["Amount"])}, radius=raw.get(radius), falloff=raw.get(falloff, 0.0),
        crit_chance=raw.get("CriticalChance"), crit_multiplier=raw.get("CriticalMultiplier"),
        status_chance=float(attack.get("ProcChance", 0.0)), forcedProcs=list(attack.get("ForcedProcs") or ()),
        nativeField=field, **extra,
    )


def orb(raw: dict) -> list[dict]:
    script = raw.get("OnProjectileStoppedScript") or {}
    if script.get("Script") != SCRIPT or not raw.get("Embed"):
        raise SystemExit(f"not a {SCRIPT} projectile")
    embed = lambda **extra: part(raw, "EmbedAttack", "EmbedDamageRadius", "EmbedFallOff", **extra)
    return [
        embed(hit="embed"),
        embed(hit="embed-body-tick", bodyOnly=True, impact_delay_seconds=1.0),
        embed(hit="embed-body-tick", bodyOnly=True, impact_delay_seconds=2.0),
        part(raw, "ExplosiveAttack", "DamageRadius", "ExplosionFallOff", hit="headshot-explosion", headOnly=True,
             count=2, impact_delay_seconds=float(script["_growthDuration"]),
             snapshotHeadshotMultiplier=True, persistAfterKill=True),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--export", type=Path, default=ROOT / "data/export/2026.08.13.13.24/weapons.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/combat-reference.json")
    args = parser.parse_args()
    packages = load(args.packages)
    weapons = {w["path"]: w for w in json.loads(args.export.read_text(encoding="utf-8"))["data"]}
    reference = json.loads(args.output.read_text(encoding="utf-8"))
    for path in WEAPONS:
        index, mode = next((i, m) for i, m in enumerate(weapons[path]["fireModes"]) if m.get("isIncarnonForm"))
        projectile = mode["damage"]["projectile"]
        entry = reference["auditedAttacks"][path]["modes"][str(index)]
        if entry.get("projectile") != projectile:
            raise SystemExit(f"{path}: audited projectile {entry.get('projectile')} != {projectile}")
        entry.pop("radial", None)
        entry["radials"] = orb(packages.resolve(projectile))
        print(path, [(r["hit"], r["damage"], r.get("count", 1), r.get("impact_delay_seconds", 0)) for r in entry["radials"]])
    args.output.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
