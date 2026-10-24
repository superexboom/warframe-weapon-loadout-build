"""List MOD trigger conditions that only the player's own attacks can fire.

    python tools/import_player_only_conditions.py --packages <raw build dir>

A condition challenge (``/Lotus/Upgrades/CosmeticEnhancers/Events/*``) with
``DamageSources = [/Lotus/Types/Player/TennoAvatar]`` counts kills / hits made
by the player avatar only. Companion weapons attack through the sentinel's
own avatar, so these never fire from a companion's attacks; Galvanized stacks
on a companion weapon come from the player's kills with that weapon class
(``DamageSourceObjects``). Writes data/mechanics/player-only-conditions.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from wfarsenal.packages import load  # noqa: E402

PLAYER = "/Lotus/Types/Player/TennoAvatar"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--mods", type=Path, default=ROOT / "data/export/2026.08.13.13.24/mods.json")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/player-only-conditions.json")
    args = parser.parse_args()
    packages = load(args.packages)
    raw = json.loads(args.mods.read_text(encoding="utf-8"))
    mods = raw["data"] if isinstance(raw, dict) else raw
    used = sorted({c for mod in mods for block in mod.get("conditionalEffects") or () for c in block.get("conditions") or ()})
    conditions = {}
    for path in used:
        if not packages.exists(path):
            continue
        row = packages.resolve(path)
        if row.get("DamageSources") == [PLAYER]:
            conditions[path] = {"weaponClass": list(row.get("DamageSourceObjects") or ())}
    args.output.write_text(json.dumps({
        "source": "Packages.bin GenericChallenge DamageSources == [TennoAvatar]",
        "packages": args.packages.name,
        "conditions": conditions,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(conditions)} player-only conditions of {len(used)} used")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
