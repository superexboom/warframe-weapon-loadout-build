"""Refresh Kitgun / Zaw parts from the client's Packages.bin.

    python tools/refresh_modular_dispositions.py --packages-bin <Packages.bin_H>

The Kitgun Riven (LotusModularPistolRandomModRare) lists every chamber with
its secondary ``Attenuation`` and the primary ``AlternateAttenuations[0]``;
the Zaw Riven (LotusModularMeleeRandomModRare) lists every strike by its
``Tip`` path. kitguns.json gets ``omegaAttenuation`` / ``primaryOmegaAttenuation``
(edited in place, keeping its formatting).

zaws.json was frozen from the wiki with invented part paths (``Head/...``,
``HandleSeven``, ``BalanceCritOne`` do not exist in the client). Every part is
matched to its client entity (strikes by Tip, grips and links by their stats),
the wiki stats are checked against the client, and the file is rewritten keyed
by the client paths; the old path stays as ``legacyPath``. Strikes also get
``omegaAttenuation`` from the Zaw Riven and ``twoHandedDamageFactor`` (the
TwoHanded ``damageAttenuation``, the wiki's two-handed damage factor).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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


ZAW_FOLDER = "/Lotus/Weapons/Ostron/Melee/"
ZAW_DEFAULT_BLADE = ZAW_FOLDER + "LotusWeaponBlade"
ZAW_PART_BASES = {"grips": "/LotusWeaponHilt", "links": "/LotusWeaponWeight"}
# Default melee tree of a strike's hand -> the wiki's weapon class.
ZAW_TREE_CLASSES = {
    "DaggerMeleeTree": "Dagger", "StaffMeleeTree": "Staff", "MacheteMeleeTree": "Machete",
    "PolearmMeleeTree": "Polearm", "RapierMeleeTree": "Rapier", "ScytheMeleeTree": "Scythe",
    "AxeMeleeTree": "Heavy Blade", "HammerMeleeTree": "Hammer", "KatanaMeleeTree": "Nikana",
    "SwordMeleeTree": "Sword",
}
# A weapon without BaseFireRate swings at 60 / min (1.0).
BASE_FIRE_RATE = 60.0


def _upgrades(row: dict) -> dict[str, float]:
    out: dict[str, float] = {}
    for upgrade in row.get("Upgrades") or ():
        if upgrade.get("OperationType") == "ADD":
            out[upgrade["UpgradeType"]] = out.get(upgrade["UpgradeType"], 0.0) + float(upgrade["Value"])
    return out


def _close(a, b, tol=6e-3) -> bool:
    return a is not None and b is not None and math.isclose(float(a), float(b), abs_tol=tol)


def _client_part(packages: Packages, path: str, table: str) -> dict:
    row = packages.resolve(path)
    ups = _upgrades(row)
    if table == "grips":
        return dict(handed="two" if row.get("GripType") == "MELEE_TWO_HAND" else "one",
                    damageBonus=ups.get("WEAPON_MELEE_DAMAGE", 0.0),
                    baseSpeed=float(row.get("BaseFireRate") or BASE_FIRE_RATE) / BASE_FIRE_RATE)
    return dict(speedBonus=ups.get("WEAPON_FIRE_RATE", 0.0) / BASE_FIRE_RATE, damageBonus=ups.get("WEAPON_MELEE_DAMAGE", 0.0),
                critChance=ups.get("WEAPON_CRIT_CHANCE", 0.0), statusChance=ups.get("WEAPON_PROC_CHANCE", 0.0))


def _client_parts(packages: Packages, table: str) -> dict[str, dict]:
    suffix = ZAW_PART_BASES[table]
    return {path: _client_part(packages, path, table) for path, (parent, _entity) in packages.entities.items()
            if path.startswith(ZAW_FOLDER) and parent.startswith(ZAW_FOLDER) and parent.endswith(suffix)
            and "PvP" not in path}


def zaw_hand(packages: Packages, tip: str, hand: str) -> dict:
    """A strike's OneHanded / TwoHanded block; a strike that states no melee
    tree (Mewan, Ooltha one-handed) uses the generic blade's (Sword). The
    per-folder LotusWeaponBlade does not chain to the generic one."""
    row = dict(packages.resolve(tip).get(hand) or {})
    if not row.get("meleeTree"):
        row["meleeTree"] = (packages.resolve(ZAW_DEFAULT_BLADE).get(hand) or {}).get("meleeTree")
    return row


def _check_strike(packages: Packages, tip: str, strike: dict) -> dict:
    row = packages.resolve(tip)
    attack = row.get("AttackData") or {}
    hands = {}
    for key, hand in (("oneHanded", "OneHanded"), ("twoHanded", "TwoHanded")):
        tree = str(zaw_hand(packages, tip, hand).get("meleeTree") or "").rsplit("/", 1)[-1]
        if ZAW_TREE_CLASSES.get(tree) != strike[key]:
            raise SystemExit(f"{strike['nameEn']} {key}: wiki {strike[key]}, client tree {tree}")
        hands[key] = (row.get(hand) or {}).get("damageAttenuation")
    checks = (("damage total", strike["damage"]["total"], attack.get("Amount")),
              ("crit", strike["critChance"], row.get("BaseCritChance")),
              ("crit multiplier", strike["critMultiplier"], row.get("BaseCritMultiplier") or 2.0),
              ("status", strike["procChance"], attack.get("ProcChance")),
              ("speed", strike["speedMod"], _upgrades(row).get("WEAPON_FIRE_RATE", 0.0) / BASE_FIRE_RATE))
    for label, wiki, client in checks:
        if not _close(wiki, client):
            raise SystemExit(f"{strike['nameEn']} {label}: wiki {wiki}, client {client}")
    return dict(twoHandedDamageFactor=float(hands["twoHanded"] or 1.0))


def rebuild_zaws(path: Path, packages: Packages, table: dict[str, tuple[float, float | None]]) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    changes = []
    strikes = {}
    for old_path, strike in data["strikes"].items():
        tip = ZAW_TIPS.get(strike["nameEn"])
        if tip is None or tip not in table:
            raise SystemExit(f"Zaw Riven does not list strike {strike['nameEn']} ({tip})")
        extra = _check_strike(packages, tip, strike)
        legacy = strike.get("legacyPath") or (old_path if old_path != tip else None)
        if strike.get("omegaAttenuation") != table[tip][0]:
            changes.append(f"{strike['nameEn']} omegaAttenuation: {strike.get('omegaAttenuation')} -> {table[tip][0]}")
        row = dict(strike, path=tip, rivenPath=tip, omegaAttenuation=table[tip][0], **extra)
        row.pop("legacyPath", None)
        if legacy:
            row["legacyPath"] = legacy
        strikes[tip] = row
    data["strikes"] = strikes
    for name in ("grips", "links"):
        client = _client_parts(packages, name)
        rows = {}
        for old_path, part in data[name].items():
            wiki = {k: part[k] for k in client[next(iter(client))]}
            matches = [p for p, stats in client.items()
                       if all(_close(wiki[k], stats[k]) if k != "handed" else wiki[k] == stats[k] for k in stats)]
            if len(matches) != 1:
                raise SystemExit(f"{name} {part['nameEn']}: {len(matches)} client parts match {wiki}")
            real = matches[0]
            legacy = part.get("legacyPath") or (old_path if old_path != real else None)
            if real in rows:
                raise SystemExit(f"{name}: {real} matched twice")
            row = dict(part, path=real)
            row.pop("legacyPath", None)
            if legacy:
                row["legacyPath"] = legacy
                changes.append(f"{part['nameEn']} path: {old_path} -> {real}")
            rows[real] = row
        if set(rows) != set(client):
            raise SystemExit(f"{name}: client parts without a wiki row: {sorted(set(client) - set(rows))}")
        data[name] = rows
    data["source"] = ("warframe wiki (Zaw) — hand-frozen 2026-08-23; part paths, two-handed damage "
                      "factors and dispositions from the client Packages.bin")
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return changes


def update_source_lock(root: Path, export_file: Path) -> None:
    lock_path = root / "data/source-lock.json"
    text = lock_path.read_text(encoding="utf-8")
    lock = json.loads(text)
    digest = hashlib.sha256(export_file.read_bytes()).hexdigest()
    rel = "data/export/{build}/" + export_file.name
    old = next((s["sha256"] for s in lock.get("sources") or () if s.get("path") == rel), None)
    if old and old != digest:
        lock_path.write_text(text.replace(old, digest), encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages-bin", required=True, type=Path)
    parser.add_argument("--export-dir", type=Path, default=ROOT / "data/export/2026.08.13.13.24")
    args = parser.parse_args()
    packages = Packages(args.packages_bin)
    changes = refresh_kitguns(args.export_dir / "kitguns.json", riven_dispositions(packages, KITGUN_RIVEN))
    changes += rebuild_zaws(args.export_dir / "zaws.json", packages, riven_dispositions(packages, ZAW_RIVEN))
    for name in ("kitguns.json", "zaws.json"):
        update_source_lock(ROOT, args.export_dir / name)
    print("\n".join(changes) or "no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
