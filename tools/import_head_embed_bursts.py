"""Add head-only embed bursts to data/mechanics/combat-reference.json.

    python tools/import_head_embed_bursts.py --packages-bin <Packages.bin_H>

A projectile with ``Embed`` and ``ValidEmbedPart: HEAD`` sticks only in a
head and, ``EmbedTime`` later, lands its ``EmbedDeathAttack`` (Zymos: 953
Toxin, 50% status, 1.1 s). tools/import_projectile_components.py imports only
the radial WFSim models (the 61 Toxin explosion), so the burst is appended
here as a second radial with ``headOnly``: the replay scales it by the shot's
head share. Child spores are a separate unresolved event lane: current Font
contains InfUziWeapon.lua with OnRadialDamage and OnDeath spawn branches.
The carrier requests five children, but inheritance, spawn exclusivity and
target selection need independent native consumer proof. Do not discard them
merely because the embedded victim died, or add an unconditional five hits.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from import_melee_mechanics import Packages  # noqa: E402

DT = {"DT_POISON": "toxin", "DT_FIRE": "heat", "DT_FREEZE": "cold", "DT_ELECTRICITY": "electricity",
      "DT_EXPLOSION": "blast", "DT_RADIATION": "radiation", "DT_GAS": "gas", "DT_VIRAL": "viral",
      "DT_CORROSIVE": "corrosive", "DT_MAGNETIC": "magnetic"}
WHOLE_BODY = ("", "ANY", "ANY_PART")


def burst(packages: Packages, projectile: str, multishot: float) -> dict | None:
    raw = packages.resolve(projectile)
    attack = raw.get("EmbedDeathAttack") or {}
    if not raw.get("Embed") or str(raw.get("ValidEmbedPart") or "") in WHOLE_BODY or not attack.get("Amount"):
        return None
    times = [float(t) for t in raw.get("EmbedTime") or ()]
    element = DT.get(str(attack.get("Type") or ""))
    if not times or element is None:
        raise SystemExit(f"{projectile}: embed delay or damage type missing")
    return dict(
        damage={element: float(attack["Amount"])}, radius_m=raw.get("DamageRadius"), falloff_start_m=0.0,
        falloff_reduction=raw.get("ExplosionFallOff", 0.0), crit_chance=raw.get("CriticalChance"),
        crit_multiplier=raw.get("CriticalMultiplier"), status_chance=float(attack.get("ProcChance", 0.0)) / multishot,
        forced_procs=[], takes_multishot=True, takes_blast_radius_mods=True,
        impact_delay_seconds=(min(times) + max(times)) / 2, headOnly=True,
        nativeSource=projectile, nativeField="EmbedDeathAttack", damageTypeSource="native-explicit",
        multishotSource="one embed per projectile", embedPart=raw.get("ValidEmbedPart"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--export", type=Path, default=ROOT / "data/export/2026.08.13.13.24/weapons.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/combat-reference.json")
    args = parser.parse_args()
    packages = Packages(args.packages_bin)
    weapons = json.loads(args.export.read_text(encoding="utf-8"))["data"]
    reference = json.loads(args.output.read_text(encoding="utf-8"))
    audited = reference["auditedAttacks"]
    added = []
    for weapon in weapons:
        entry = audited.get(weapon["path"])
        if not entry or "fireMode" not in entry or "radials" not in entry:
            continue
        mode = weapon["fireModes"][entry["fireMode"]]
        projectile = (mode.get("damage") or {}).get("projectile")
        component = burst(packages, projectile, float(mode.get("multishot") or 1)) if projectile and packages.exists(projectile) else None
        if component is None:
            continue
        radials = [r for r in entry["radials"] if not r.get("headOnly")]
        entry["radials"] = [*radials, component]
        added.append(f"{weapon['nameEn']}: {component['damage']} after {component['impact_delay_seconds']:g}s on {component['embedPart']}")
    args.output.write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(added) or "nothing to add")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
