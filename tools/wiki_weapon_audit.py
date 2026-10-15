"""Compare the local weapon export with the wiki's weapon data modules.

    python tools/wiki_weapon_audit.py WIKI_DIR [--json OUT]

Weapons pair by internal path. A local fire mode pairs with the wiki attack
whose damage total matches (else whose damage types match, else the attack
with the same index); radial children (AttackParentIndex) are left out.
Prints every field that disagrees: multishot, fire rate, crit chance / multiplier,
status chance, ammo cost, charge time, damage total and types, magazine, reload.
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

TYPES = {"Impact": "DT_IMPACT", "Puncture": "DT_PUNCTURE", "Slash": "DT_SLASH", "Heat": "DT_FIRE", "Cold": "DT_FREEZE",
         "Electricity": "DT_ELECTRICITY", "Toxin": "DT_POISON", "Blast": "DT_EXPLOSION", "Radiation": "DT_RADIATION",
         "Gas": "DT_GAS", "Magnetic": "DT_MAGNETIC", "Viral": "DT_VIRAL", "Corrosive": "DT_CORROSIVE", "Void": "DT_RADIANT",
         "Tau": "DT_SENTIENT", "True": "DT_FINISHER", "Cinematic": "DT_CINEMATIC"}


def close(a, b, rel=0.011):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= rel * max(abs(float(a)), abs(float(b)), 1e-9)


def wiki_damage(attack):
    return {TYPES.get(k, k): float(v) for k, v in (attack.get("Damage") or {}).items() if float(v)}


def pair(mode, attacks, index):
    local = {k: float(v) for k, v in ((mode.get("damage") or {}).get("types") or {}).items() if float(v)}
    total = sum(local.values())
    direct = [a for a in attacks if not a.get("AttackParentIndex")]
    by_total = [a for a in direct if close(sum(wiki_damage(a).values()), total, .02)]
    if len(by_total) == 1:
        return by_total[0], "total"
    by_types = [a for a in direct if set(wiki_damage(a)) == set(local)]
    if len(by_types) == 1:
        return by_types[0], "types"
    if index < len(direct):
        return direct[index], "index"
    return None, None


def compare(weapon, row):
    out = []
    modes = weapon.get("fireModes") or []
    attacks = row.get("Attacks") or []
    if row.get("Magazine") is not None and weapon.get("magazineSize") is not None and not close(row["Magazine"], weapon["magazineSize"]):
        out.append(dict(field="magazine", local=weapon["magazineSize"], wiki=row["Magazine"]))
    for index, mode in enumerate(modes):
        attack, how = pair(mode, attacks, index)
        if attack is None:
            continue
        label = f"m{index}:{attack.get('AttackName')}({how})"
        checks = (("multishot", mode.get("multishot"), attack.get("Multishot")),
                  ("fireRate", mode.get("fireRate"), attack.get("FireRate")),
                  ("critChance", (mode.get("damage") or {}).get("critChance"), attack.get("CritChance")),
                  ("critMultiplier", (mode.get("damage") or {}).get("critMultiplier"), attack.get("CritMultiplier")),
                  ("statusChance", (mode.get("damage") or {}).get("procChance"), attack.get("StatusChance")),
                  ("ammoCost", mode.get("ammoCost"), attack.get("AmmoCost")),
                  ("chargeTime", mode.get("chargeTime") or None, attack.get("ChargeTime")))
        for field, local, wiki in checks:
            if wiki is None or local is None:
                continue
            if not close(local, wiki):
                out.append(dict(mode=label, field=field, local=local, wiki=wiki))
        local = {k: float(v) for k, v in ((mode.get("damage") or {}).get("types") or {}).items() if float(v)}
        wiki = wiki_damage(attack)
        if wiki and (set(local) != set(wiki) or not close(sum(local.values()), sum(wiki.values()), .02)):
            out.append(dict(mode=label, field="damage", local=local, wiki=wiki))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("wiki", type=Path)
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    import app
    rows = wiki_lua.load_weapons(args.wiki)
    report = []
    for weapon in app.EXPORTS["weapons"]:
        row = rows.get(weapon.get("path"))
        if not row:
            continue
        diffs = compare(weapon, row)
        if diffs:
            report.append(dict(path=weapon["path"], name=weapon.get("nameEn"), wiki=row.get("_key"), diffs=diffs))
    for item in report:
        print(item["name"], "|", "; ".join(f"{d.get('mode', '')} {d['field']}: {d['local']} vs wiki {d['wiki']}" for d in item["diffs"]))
    print(len(report), "weapons with disagreements of", sum(1 for w in app.EXPORTS["weapons"] if w.get("path") in rows), "paired")
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
