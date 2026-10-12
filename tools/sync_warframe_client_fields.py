"""Check the warframe sidecar against the client and fix what disagrees.

Two fields are read straight from each suit's Packages.bin entity:

- rank-30 growth: the ADD_BASE sums of its LevelUpgrades (health, shield,
  energy, armour). The sidecar derived growth from the generic PlayerPowerSuit
  (+100 / +100 / +50), which is wrong for Yareli (no growth at all in the
  sidecar; the client and the wiki give 370 / 555 / 300) and Sevagoth (+50
  shields instead of +100);
- slot polarities: ArtifactSlots, slots 0-7 normal, 8 aura, 9 exilus,
  universal shown as empty. Rows added by hand (Citrine Prime) carried the raw
  list in the wrong places.

Usage:
    python tools/sync_warframe_client_fields.py --packages-bin <Packages.bin_H> [--check]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "data" / "warframe_build_data.json"
GROWTH = {"AVATAR_HEALTH_MAX": "health", "AVATAR_SHIELD_MAX": "shield", "AVATAR_POWER_MAX": "energy", "AVATAR_ARMOUR": "armor"}


def client_polarities(slots: list[str]) -> dict:
    def polarity(value: str) -> str | None:
        return None if value == "AP_UNIVERSAL" else value

    return {"aura": polarity(slots[8]), "exilus": polarity(slots[9]), "normal": [polarity(value) for value in slots[:8]]}


def main() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from import_melee_mechanics import Packages

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="report only")
    args = parser.parse_args()
    packages = Packages(args.packages_bin)
    data = json.loads(SIDECAR.read_text(encoding="utf-8-sig"))
    changes = []
    for frame in data["warframes"]:
        if not packages.exists(frame["path"]):
            continue
        suit = packages.resolve(frame["path"])
        growth = collections.Counter()
        for upgrade in suit.get("LevelUpgrades") or []:
            if upgrade.get("UpgradeType") in GROWTH and upgrade.get("OperationType") == "ADD_BASE":
                growth[GROWTH[upgrade["UpgradeType"]]] += upgrade["Value"]
        base, rank30 = frame["basePanel"], frame["rank30Panel"]
        for stat in ("health", "shield", "energy", "armor"):
            if base.get(stat) is None or rank30.get(stat) is None:
                continue
            expected = float(base[stat]) + growth.get(stat, 0)
            if abs(float(rank30[stat]) - expected) > 1e-6:
                changes.append(f"{frame['nameEn']}: rank-30 {stat} {rank30[stat]} -> {expected:g}")
                rank30[stat] = expected
                frame.setdefault("rankGrowth", {})[stat] = growth.get(stat, 0)
                frame["rankGrowthSource"] = frame["path"] + " LevelUpgrades"
        slots = suit.get("ArtifactSlots") or []
        if len(slots) >= 10:
            expected_slots = client_polarities(slots)
            if frame.get("slotPolarities") != expected_slots:
                changes.append(f"{frame['nameEn']}: polarities {frame.get('slotPolarities')} -> {expected_slots}")
                frame["slotPolarities"] = expected_slots
                frame["auraPolarity"] = expected_slots["aura"]
                frame["exilusPolarity"] = expected_slots["exilus"]
                frame["slotPolaritySource"] = "client Packages.bin ArtifactSlots"
    print("\n".join(changes) or "sidecar agrees with the client")
    if changes and not args.check:
        # The sidecar's own format: 1-space indent, CRLF, no trailing newline.
        SIDECAR.write_bytes(json.dumps(data, ensure_ascii=False, indent=1).replace("\n", "\r\n").encode("utf-8"))
    return 1 if changes and args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
