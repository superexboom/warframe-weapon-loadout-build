"""Refresh Kitgun / Zaw Riven dispositions from the client's Packages.bin.

    python tools/refresh_modular_dispositions.py --packages-bin <Packages.bin_H>

The Kitgun Riven (LotusModularPistolRandomModRare) lists every chamber with
its secondary ``Attenuation`` and the primary ``AlternateAttenuations[0]``;
the Zaw Riven (LotusModularMeleeRandomModRare) lists every strike by its
``Tip`` path. kitguns.json gets ``omegaAttenuation`` / ``primaryOmegaAttenuation``;
zaws.json (wiki-frozen, keyed by ``Head`` paths) gets ``omegaAttenuation``
and ``rivenPath``, the Tip path the game and the Bot identify the strike by.
Both files are edited in place, keeping their formatting.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from import_melee_mechanics import Packages  # noqa: E402

KITGUN_RIVEN = "/Lotus/Upgrades/Mods/Randomized/LotusModularPistolRandomModRare"
ZAW_RIVEN = "/Lotus/Upgrades/Mods/Randomized/LotusModularMeleeRandomModRare"
# zaws.json strike (English name) -> the strike's Tip path in the client. The
# Tip entity carries the same AttackData amount and crit as the wiki strike.
ZAW_TIPS = {
    "Balla": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipOne",
    "Ooltha": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipTwo",
    "Mewan": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipThree",
    "Cyath": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipFour",
    "Dehtat": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipFive",
    "Kronsh": "/Lotus/Weapons/Ostron/Melee/ModularMelee01/Tip/TipSix",
    "Sepfahn": "/Lotus/Weapons/Ostron/Melee/ModularMelee02/Tip/TipNine",
    "Rabvee": "/Lotus/Weapons/Ostron/Melee/ModularMelee02/Tip/TipTen",
    "Dokrahm": "/Lotus/Weapons/Ostron/Melee/ModularMelee02/Tip/TipEleven",
    "Plague Kripath": "/Lotus/Weapons/Ostron/Melee/ModularMeleeInfested/Tips/InfestedTipOne",
    "Plague Keewar": "/Lotus/Weapons/Ostron/Melee/ModularMeleeInfested/Tips/InfestedTipTwo",
}


def riven_dispositions(packages: Packages, riven: str) -> dict[str, tuple[float, float | None]]:
    """ItemType -> (attenuation, alternate attenuation or None)."""
    out: dict[str, tuple[float, float | None]] = {}

    def walk(node):
        if isinstance(node, dict):
            if "ItemType" in node and "Attenuation" in node:
                alternate = node.get("AlternateAttenuations") or [None]
                out[str(node["ItemType"])] = (float(node["Attenuation"]), alternate[0] and float(alternate[0]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(packages.resolve(riven))
    if not out:
        raise SystemExit(f"{riven} lists no dispositions")
    return out


def refresh_kitguns(path: Path, table: dict[str, tuple[float, float | None]]) -> list[str]:
    data = json.loads(path.read_bytes().decode("utf-8"))
    changes = []
    for barrel_path, barrel in data["barrels"].items():
        if barrel_path not in table:
            raise SystemExit(f"Kitgun Riven does not list chamber {barrel_path}")
        secondary, primary = table[barrel_path]
        for key, value in (("omegaAttenuation", secondary), ("primaryOmegaAttenuation", primary)):
            if value is not None and barrel.get(key) != value:
                changes.append(f"{barrel['nameEn']} {key}: {barrel.get(key)} -> {value}")
                barrel[key] = value
    # The committed file is exactly this dump with LF; source-lock hashes bytes.
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    return changes


def refresh_zaws(path: Path, table: dict[str, tuple[float, float | None]]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    changes = []
    for strike_path, strike in data["strikes"].items():
        tip = ZAW_TIPS.get(strike["nameEn"])
        if tip is None or tip not in table:
            raise SystemExit(f"Zaw Riven does not list strike {strike['nameEn']} ({tip})")
        value = table[tip][0]
        start = text.index(json.dumps(strike_path) + ":")
        end = text.find('\n    "/', start + 1)
        end = len(text) if end < 0 else end
        block = text[start:end]
        updated = re.sub(r'("omegaAttenuation": )[-0-9.eE]+', lambda m: m.group(1) + repr(value), block, count=1)
        if '"rivenPath"' in updated:
            updated = re.sub(r'("rivenPath": )"[^"]*"', lambda m: m.group(1) + json.dumps(tip), updated, count=1)
        else:
            updated = re.sub(r'(\n(\s+)"path": "[^"]*",)', lambda m: f'{m.group(1)}\n{m.group(2)}"rivenPath": {json.dumps(tip)},',
                             updated, count=1)
        if updated != block:
            if strike.get("omegaAttenuation") != value:
                changes.append(f"{strike['nameEn']} omegaAttenuation: {strike.get('omegaAttenuation')} -> {value}")
            text = text[:start] + updated + text[end:]
    reloaded = json.loads(text)
    for strike in reloaded["strikes"].values():
        assert strike["rivenPath"] == ZAW_TIPS[strike["nameEn"]], strike["nameEn"]
        assert strike["omegaAttenuation"] == table[strike["rivenPath"]][0], strike["nameEn"]
    path.write_text(text, encoding="utf-8", newline="")
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages-bin", required=True, type=Path)
    parser.add_argument("--export-dir", type=Path, default=ROOT / "data/export/2026.08.13.13.24")
    args = parser.parse_args()
    packages = Packages(args.packages_bin)
    changes = refresh_kitguns(args.export_dir / "kitguns.json", riven_dispositions(packages, KITGUN_RIVEN))
    changes += refresh_zaws(args.export_dir / "zaws.json", riven_dispositions(packages, ZAW_RIVEN))
    print("\n".join(changes) or "no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
