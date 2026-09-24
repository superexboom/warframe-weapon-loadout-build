"""Extract archgun (Archwing primary) GROUND fire modes into the frozen export.

The compact export pipeline (vendor/wfarsenal/extract.py) reads each weapon's
``Behaviors`` list.  Archguns carry two parallel behaviour sets:

* ``Behaviors`` — the Archwing/space loadout (projectile speeds, space ammo).
* ``HeavyBehaviors`` — the ground "Heavy Weapon" loadout players actually use
  in atmosphere (different damage tables, crit, fire rate and ammo).

The frozen ``data/export/<build>/weapons.json`` therefore contains archgun rows
whose ``fireModes`` are the SPACE modes.  This script re-derives every archgun
row from the raw Packages.bin dump and rewrites it with the GROUND modes plus
the ground ammo pool (``HeavyAmmoClipSize``/``HeavyAmmoCapacity``), preserving
all other exported fields (localized names, polarities, disposition, mastery,
incarnon data, innate elements).

Scope (user requirement: 地面数据 ONLY / 空战数据不管):

* SpaceGuns (arch_gun, 20 rows) — ground modes replace space modes.
* SpaceMelee (arch_melee, 8 rows) — no ground state, pruned from the export
  (``--keep-arch-melee`` restores the old behaviour of leaving them alone).

Merge pattern follows .local/tmp_rebuild_incarnon.py: load the raw dump with
``wfarsenal.packages.PackageIndex`` + the parent table from Packages.bin,
rebuild only the archgun rows, then atomically replace weapons.json.

Usage (from the repo root):

    python -X utf8 tools/extract-archwing-ground.py
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor"))

import wfarsenal.extract as extract_mod  # noqa: E402
from wfarsenal import packages as packages_mod  # noqa: E402
from wfarsenal.parenttable import iter_entities  # noqa: E402

DEFAULT_RAW = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\wf-arsenal\data\raw"
    r"\2026.08.19.11.06"
)
DEFAULT_EXPORT = REPO / "data" / "export" / "2026.08.13.13.24" / "weapons.json"

# Fields a rewritten archgun row carries over from the existing export verbatim:
# everything except the fields this script owns.
_OWNED_FIELDS = {
    "fireModes",
    "fireModeSource",
    "magazineSize",
    "ammoMax",
    "productCategory",
}


def load_index(raw_dir: Path) -> packages_mod.PackageIndex:
    """Open the raw dump, wiring inheritance from the raw Packages.bin."""
    parents: dict[str, str] = {}
    for entity in iter_entities(raw_dir / "Packages.bin"):
        parents[entity.path] = entity.parent
    return packages_mod.PackageIndex(raw_dir / "packages", parents=parents)


def archgun_store_items(
    index: packages_mod.PackageIndex,
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Return ``(type_path, store_item, resolved_weapon)`` for every SpaceGuns item."""
    store = extract_mod._collect_store_items(index)
    result = []
    for type_name, item in store.items():
        weapon = index.resolve(type_name)
        if not weapon:
            continue
        category = item.get("ProductCategory") or weapon.get("ProductCategory", "")
        if category == "SpaceGuns":
            result.append((type_name, item, weapon))
    result.sort(key=lambda row: row[0])
    return result


def ground_summary(mode: dict[str, Any]) -> tuple[float | None, float, float, float, str]:
    """Return (total damage, crit chance, crit mult, status, trigger tail) for the table."""
    damage = mode.get("damage") if isinstance(mode.get("damage"), dict) else {}
    total = damage.get("total")
    trigger = str(mode.get("trigger") or "")
    trigger_label = trigger.rsplit("/", 1)[-1].replace("Loadout_Trigger", "")
    return (
        float(total) if isinstance(total, (int, float)) else None,
        float(damage.get("critChance") or 0.0),
        float(damage.get("critMultiplier") or 0.0),
        float(damage.get("procChance") or 0.0),
        trigger_label,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW, help="raw dump dir with packages/ + Packages.bin")
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT, help="frozen weapons.json to merge into")
    parser.add_argument("--dry-run", action="store_true", help="print the summary table without writing")
    parser.add_argument(
        "--keep-arch-melee",
        action="store_true",
        help="keep the SpaceMelee (arch_melee) rows instead of pruning them",
    )
    args = parser.parse_args(argv)

    index = load_index(args.raw)
    items = archgun_store_items(index)
    print(f"raw dump: {args.raw}")
    print(f"SpaceGuns store items: {len(items)}")

    payload = json.loads(args.export.read_text(encoding="utf-8"))
    rows = payload["data"]
    rows_by_path = {row.get("path"): row for row in rows}
    print(f"frozen weapons: {len(rows)}")

    rebuilt = 0
    pruned = 0
    failed: list[tuple[str, str]] = []
    table: list[dict[str, Any]] = []
    for type_name, item, weapon in items:
        existing = rows_by_path.get(type_name)
        if existing is None:
            failed.append((type_name, "no row in frozen export"))
            continue
        ground = extract_mod._extract_archgun_ground_modes(index, type_name, weapon)
        if ground is None:
            failed.append((type_name, "no ground fire modes resolved"))
            continue
        modes, source = ground
        row = {
            key: value
            for key, value in existing.items()
            if key not in _OWNED_FIELDS
        }
        row["productCategory"] = item.get("ProductCategory") or weapon.get("ProductCategory")
        row["fireModes"] = modes
        row["fireModeSource"] = source
        row["magazineSize"] = weapon.get("HeavyAmmoClipSize") or weapon.get("AmmoClipSize")
        row["ammoMax"] = weapon.get("HeavyAmmoCapacity")
        rows_by_path[type_name] = row
        rebuilt += 1

        primary = modes[0]
        total, crit, crit_mult, status, trigger_label = ground_summary(primary)
        table.append(
            {
                "nameEn": existing.get("nameEn") or existing.get("name"),
                "nameZh": existing.get("nameZh"),
                "modes": len(modes),
                "total": total,
                "crit": crit,
                "critMult": crit_mult,
                "status": status,
                "fireRate": primary.get("fireRate"),
                "trigger": trigger_label,
                "magazine": row["magazineSize"],
                "ammoMax": row["ammoMax"],
                "source": source,
            }
        )

    if not args.keep_arch_melee:
        # SpaceMelee has no ground (Heavy Weapon) state — the ground-only scope
        # does not want these rows at all.
        arch_melee_paths = [
            path
            for path, row in rows_by_path.items()
            if str(row.get("slot") or "") == "arch_melee"
        ]
        for path in arch_melee_paths:
            del rows_by_path[path]
            pruned += 1
        if arch_melee_paths:
            print(f"pruned {pruned} arch_melee rows (no ground state)")

    if failed:
        print("\nfailed extractions:")
        for path, reason in failed:
            print(f"  {path}: {reason}")

    # Summary table: name, damage total, crit, fire rate, trigger per weapon.
    print(f"\n{'weapon':<24} {'modes':>5} {'dmg':>8} {'crit':>6} {'x':>5} {'status':>7} {'rate/s':>7} {'mag':>5} {'ammo':>5}  trigger/source")
    for entry in table:
        name = str(entry["nameEn"] or "?")
        total = f"{entry['total']:.1f}" if entry["total"] is not None else "?"
        rate = f"{entry['fireRate']:.2f}" if isinstance(entry["fireRate"], (int, float)) else "?"
        print(
            f"{name[:24]:<24} {entry['modes']:>5} {total:>8} {entry['crit']:>6.2f} "
            f"{entry['critMult']:>5.2f} {entry['status']:>7.2f} {rate:>7} "
            f"{str(entry['magazine']):>5} {str(entry['ammoMax']):>5}  {entry['trigger']}/{entry['source']}"
        )

    if args.dry_run:
        print(f"\n[dry-run] would rewrite {rebuilt} archgun rows, prune {pruned} arch_melee rows in {args.export}")
        return 0

    payload["data"] = sorted(rows_by_path.values(), key=lambda row: str(row.get("path") or ""))
    payload["count"] = len(payload["data"])
    tmp = args.export.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(args.export)
    print(f"\nrewrote {rebuilt} archgun rows, pruned {pruned} arch_melee rows in {args.export} (total rows: {payload['count']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
