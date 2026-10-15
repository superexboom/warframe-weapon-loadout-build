"""Write data/wiki_weapon_overrides.json: wiki weapon numbers that win over the export.

    python tools/wiki_lua.py fetch .local/wiki-modules
    python tools/import_wiki_weapon_stats.py .local/wiki-modules

Source order, for every field two sources disagree on: in-game measurement,
then the wiki (``Module:Weapons/data/*``, the weapon's own page over overview
tables), then DE's export / the client packages. The export misses what the
game derives at runtime: a projectile with no ProcChance of its own falls back
to the weapon's (export: 0), and a beam's ``fireIterations`` is one short of
the beams the arsenal shows (Phantasma 5 vs 6, Phage 6 vs 7).

Only confident pairs are written: the wiki attack whose damage total matches
the local mode (or, for the reviewed list, whose damage types match). Fields
the two sources state in different conventions are converted: the export's
multi-pellet status chance is per shot, the wiki's per pellet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wiki_lua  # noqa: E402
from wiki_weapon_audit import close, pair, wiki_damage  # noqa: E402

OUTPUT = ROOT / "data" / "wiki_weapon_overrides.json"

# Reviewed conflicts (2026-10-16): path -> (mode index, fields from the wiki, why).
REVIEWED = {
    "/Lotus/Weapons/Tenno/LongGuns/RevenantShotgun/RevenantShotgun": (0, ("multishot",), "6 beams in game (wiki, user check); packages fireIterations 5"),
    "/Lotus/Weapons/Tenno/LongGuns/PrimePhantasma/PhantasmaPrimeShotgun": (0, ("multishot",), "6 beams (wiki); packages 5"),
    "/Lotus/Weapons/Infested/LongGuns/Tentacluster/InfestedShotgun": (0, ("multishot",), "7 beams (wiki); packages 6"),
    "/Lotus/Weapons/Tenno/LongGuns/GyreRifle/GyreRifleWeapon": (0, ("damage",), "projectile GyrRifleWaveProj: 62 Electricity, 30% status"),
    "/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWeapon": (0, ("damage",), "Electricity projectile (wiki)"),
    "/Lotus/Weapons/Tenno/LongGuns/SapientPrimary/SapientPrimaryWeapon": (0, ("damage",), "rocket impact 35 (wiki); export 26"),
}


def _paths_by_name(weapons, names):
    return {w["nameEn"]: w["path"] for w in weapons if w.get("nameEn") in names}


def build(wiki_dir: Path) -> dict:
    import app

    rows = wiki_lua.load_weapons(wiki_dir)
    revisions_path = wiki_dir / "revisions.json"
    revisions = json.loads(revisions_path.read_text(encoding="utf-8")) if revisions_path.is_file() else {}
    weapons: dict[str, dict] = {}

    def put(weapon, index, fields, attack, why):
        entry = weapons.setdefault(weapon["path"], dict(name=weapon.get("nameEn"), modes={}))
        mode_entry = entry["modes"].setdefault(str(index), dict(wikiAttack=attack.get("AttackName"), notes=[]))
        mode_entry.update(fields)
        mode_entry["notes"].append(why)

    # Reviewed list, resolved by path (falls back to the English name when a
    # path moved between builds).
    reviewed = dict(REVIEWED)
    for weapon in app.EXPORTS["weapons"]:
        path = weapon.get("path")
        if path not in reviewed:
            continue
        index, fields, why = reviewed[path]
        row = rows.get(path)
        modes = weapon.get("fireModes") or []
        if not row or index >= len(modes):
            continue
        mode = modes[index]
        attack, how = pair(mode, row.get("Attacks") or [], index)
        if attack is None or how == "index":
            raise SystemExit(f"{weapon.get('nameEn')}: no confident wiki attack for mode {index}")
        damage = mode.get("damage") or {}
        out = {}
        if "multishot" in fields:
            local_ms = float(mode.get("multishot") or 1)
            wiki_ms = float(attack.get("Multishot") or 1)
            per_pellet = float(damage.get("procChance") or 0) / (local_ms if local_ms > 1 else 1)
            out.update(multishot=wiki_ms, procChance=round(per_pellet * wiki_ms, 9))
        if "damage" in fields:
            types = wiki_damage(attack)
            out.update(damageTypes=types)
            if attack.get("StatusChance") is not None:
                ms = float(attack.get("Multishot") or 1)
                out.update(procChance=float(attack["StatusChance"]) * (ms if ms > 1 else 1))
        put(weapon, index, out, attack, why)
    # Rule: the projectile has no ProcChance of its own and the game uses the
    # weapon's; the export wrote 0. Every confident pair where the wiki states one.
    for weapon in app.EXPORTS["weapons"]:
        row = rows.get(weapon.get("path"))
        if not row:
            continue
        for index, mode in enumerate(weapon.get("fireModes") or []):
            damage = mode.get("damage") or {}
            if float(damage.get("procChance") or 0) != 0 or float(damage.get("total") or 0) <= 10:
                continue
            attack, how = pair(mode, row.get("Attacks") or [], index)
            if attack is None or how != "total" or not attack.get("StatusChance"):
                continue
            ms = float(mode.get("multishot") or 1)
            put(weapon, index, dict(procChance=float(attack["StatusChance"]) * (ms if ms > 1 else 1)), attack,
                "export ProcChance 0 (projectile without its own); wiki status chance")
    return dict(
        source="wiki.warframe.com Module:Weapons/data/* via api.php",
        revisions=revisions,
        rule="measurement > wiki > export; fields converted to the export's conventions (status per shot)",
        weapons=dict(sorted(weapons.items())),
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("wiki", type=Path)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()
    data = build(args.wiki)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for path, entry in data["weapons"].items():
        print(entry["name"], {k: {f: v for f, v in m.items() if f not in ("notes", "wikiAttack")} for k, m in entry["modes"].items()})
    print(len(data["weapons"]), "weapons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
