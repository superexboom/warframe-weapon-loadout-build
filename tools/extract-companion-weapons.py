"""Extract companion (sentinel/MOA/Hound) weapon fire modes into the frozen export.

The compact export pipeline (vendor/wfarsenal/extract.py) reads each weapon's
``Behaviors`` list and picks ONE damage source per behaviour entry: a referenced
``projectileType`` first, else the impact behaviour's inline ``AttackData``.
For companion weapons that heuristic misses real data in two ways:

* **Sequence projectiles (Deconstructor family).**  The Glaive fire behaviour
  has ``projectileType=""`` but an advancing ``projectileSequenceList`` of three
  projectiles (Front/Rear/Mid), each carrying its own ``AttackData`` (160/160/160
  split into pure Impact/Puncture/Slash for Deconstructor Prime).  The old export
  silently fell through to the impact placeholder (total 10, crit 0) — the wiki
  panel is 160 per projectile with 25% status per hit.
* **Impact-level crit fields.**  Impact behaviours spell crit
  ``criticalHitChance``/``criticalHitDamageMultiplier`` and those are read
  correctly for hitscan companions, but the *projectile* crit spelling
  (``CriticalChance``/``CriticalMultiplier``) was applied even when the
  projectile has no crit fields of its own while the weapon's impact does
  (Cryotra: projectile crit is a placeholder 0.1/1.75 while the impact carries
  the real 0.25/2.5 — the wiki panel shows 25%/2.5x for the direct hit).
  Conversely the projectile's missing ``ProcChance`` (Prime Laser Rifle) left
  status at 0.0 where the impact carries 0.1.

This script rebuilds every companion row's ``fireModes[0].damage`` from the raw
dump with a companion-specific precedence, records the sequence structure for
the Deconstructor glaives, and preserves every other exported field (localized
names, polarities, disposition, mastery, compatTags, ...).

Merge safety: another worker edits weapons.json concurrently (archguns).  The
corrected rows are first written to ``.local/tmp-companion-merge.json``; a
separate apply step re-reads weapons.json, patches ONLY rows matched by path
(and appends genuinely new rows), then writes atomically.  One retry on a
mid-flight change of the file keeps the read-modify-write race window small.

Extraction precedence per behaviour entry (companion-specific):

1. ``projectileSequenceList`` + ``advanceProjectileSequenceOnFire`` — every
   sequence member's ``AttackData`` is recorded; the mode's primary damage
   block uses the FIRST member (matches the wiki's per-attack view of the
   rotation), and ``sequenceProjectiles`` lists all members with paths.
2. ``projectileType`` — the projectile's ``AttackData`` when it has an
   ``Amount``, falling back to the impact's inline ``AttackData`` when the
   projectile is a shell only (Cryotra's grenade carries forced procs and its
   real numbers live on the impact).
3. Impact inline ``AttackData`` (hitscan companions, beams).

Crit/status resolution: the damage source object wins for the fields it
actually defines; missing fields fall back to the impact behaviour (which is
the weapon-authoritative record for crit stats), then to the projectile.

Deconstructor / Deconstructor Prime are GLAIVE (melee-judged) companion
weapons: GlaiveProjectileFireBehavior + SlamMeleeAttack/HeavySlamMeleeAttack +
Parry fields on the weapon root (inherited from LotusMeleeWeapon).  Their rows
gain ``isMeleeJudged: true`` and a ``meleeFields`` block recording that
structure (slam attack paths, parry angle, empowered-melee chance).  Slam
damage itself is intentionally NOT modelled.

Usage (from the repo root):

    python -X utf8 tools/extract-companion-weapons.py            # build + write merge file
    python -X utf8 tools/extract-companion-weapons.py --apply    # apply merge into weapons.json
    python -X utf8 tools/extract-companion-weapons.py --summary  # before/after table only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

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
MERGE_FILE = REPO / ".local" / "tmp-companion-merge.json"

DAMAGE_TYPES = extract_mod.DAMAGE_TYPES

# Fields this script owns on a companion row.  Everything else is carried over
# from the existing export verbatim.
_OWNED_ROW_FIELDS = {"fireModes"}
# Fields this script owns inside a rebuilt mode.  Unknown extra keys emitted by
# the old pipeline for a mode (e.g. projectile event layers) are rebuilt too,
# because the damage source may change; they are regenerated, not copied.
_SEQ_TRIGGER_FALLBACK = ""


def load_index(raw_dir: Path) -> packages_mod.PackageIndex:
    """Open the raw dump, wiring inheritance from the raw Packages.bin."""
    parents: dict[str, str] = {}
    for entity in iter_entities(raw_dir / "Packages.bin"):
        parents[entity.path] = entity.parent
    return packages_mod.PackageIndex(raw_dir / "packages", parents=parents)


def sub_behaviour(entry: Mapping[str, Any], prefix: str) -> dict[str, Any] | None:
    """Payload of the ``prefix:``-namespaced sub-behaviour, if present."""
    for key, value in entry.items():
        if key.startswith(prefix) and key != f"{prefix}Type" and isinstance(value, dict):
            return value
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _resolve_ref(
    index: packages_mod.PackageIndex, owner_path: str, reference: Any
) -> tuple[str | None, dict[str, Any]]:
    """Resolve a behaviour reference (absolute or sibling-relative)."""
    if not isinstance(reference, str) or not reference:
        return None, {}
    return extract_mod._resolve_weapon_reference(index, owner_path, reference)


def _has_amount(attack: Any) -> bool:
    return isinstance(attack, Mapping) and isinstance(attack.get("Amount"), (int, float))


def _damage_block(source: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize an AttackData-shaped dict into the export damage block shape.

    Companion rule (per the task contract): ``Amount`` IS the total; the
    ``DT_*`` values are shares of it.  Two encodings exist — fractions
    (DT ≤ 1, e.g. 0.55/0.45) and weights (DT > 1, e.g. Helstrum's 5.5/4.5
    against Amount 9) — and both normalize by their sum, so the emitted
    ``types`` always sum to ``Amount``.  A bare ``Type`` with no DT values
    means 100% of that type.
    """
    attack = source.get("AttackData") if "AttackData" in source else source
    if not _has_amount(attack):
        return None
    total = float(attack["Amount"])
    explicit_type = attack.get("Type")
    raw = {
        dt: float(attack[dt])
        for dt in DAMAGE_TYPES
        if isinstance(attack.get(dt), (int, float)) and attack[dt]
    }
    if not raw and isinstance(explicit_type, str) and explicit_type in DAMAGE_TYPES:
        raw = {explicit_type: 1.0}
    if not raw:
        # No type information at all: keep the total but no per-type split.
        return {"total": total, "procChance": attack.get("ProcChance", 0.0), "shares": {}, "types": {}}
    if all(value <= 1.0 for value in raw.values()):
        # Fraction encoding: the DT values are shares of Amount (the classic
        # representation; used as-is so unchanged weapons stay byte-identical
        # with the rest of the frozen export).
        shares = raw
    else:
        # Weight encoding (e.g. Helstrum 5.5/4.5 against Amount 9): normalize
        # by the weight sum so the emitted types sum to Amount.
        weight = sum(raw.values()) or 1.0
        shares = {dt: value / weight for dt, value in raw.items()}
    return {
        "total": total,
        "procChance": attack.get("ProcChance", 0.0),
        "shares": {dt: round(share, 6) for dt, share in shares.items()},
        "types": {dt: round(total * share, 6) for dt, share in shares.items()},
        **({"forcedProcs": list(attack["ForcedProcs"])} if attack.get("ForcedProcs") else {}),
    }


def _crit_from(obj: Mapping[str, Any]) -> tuple[float | None, float | None]:
    """Read crit chance/multiplier accepting both spellings."""
    chance = _number(obj.get("CriticalChance"))
    if chance is None:
        chance = _number(obj.get("criticalHitChance"))
    mult = _number(obj.get("CriticalMultiplier"))
    if mult is None:
        mult = _number(obj.get("criticalHitDamageMultiplier"))
    return chance, mult


def _proc_from(obj: Mapping[str, Any]) -> float | None:
    attack = obj.get("AttackData") if isinstance(obj.get("AttackData"), Mapping) else obj
    return _number(attack.get("ProcChance"))


def build_mode(
    index: packages_mod.PackageIndex,
    weapon_path: str,
    weapon: Mapping[str, Any],
    position: int,
) -> dict[str, Any] | None:
    """Rebuild one fire mode from a companion weapon's Behaviors entry."""
    behaviours = weapon.get("Behaviors")
    if not isinstance(behaviours, list):
        return None
    entry = behaviours[position] if position < len(behaviours) else None
    if not isinstance(entry, Mapping):
        return None
    fire = sub_behaviour(entry, "fire:") or {}
    state = sub_behaviour(entry, "state:") or {}
    impact = sub_behaviour(entry, "impact:") or {}

    mode: dict[str, Any] = {"index": position}

    # -- state: timing / trigger ------------------------------------------------
    if state:
        mode["trigger"] = state.get("LocTag") or ""
        mode["fireRate"] = extract_mod._per_second(state.get("fireRate"))
        mode["fireRateRaw"] = state.get("fireRate")
        mode["reloadTime"] = state.get("reloadTime")
        mode["isAlternateFire"] = bool(state.get("IsAlternateFire"))
        mode["chargeTime"] = state.get("ChargeTime", state.get("chargeTime"))
        for burst_key in ("NumShots", "BurstCount"):
            if isinstance(state.get(burst_key), (int, float)) and state[burst_key] > 1:
                mode["burstCount"] = int(state[burst_key])
        if isinstance(state.get("BurstDelay"), (int, float)) and state["BurstDelay"] > 0:
            mode["burstDelay"] = state["BurstDelay"]
        if isinstance(state.get("MaxNumProjectiles"), (int, float)) and state["MaxNumProjectiles"] > 0:
            mode["maxProjectiles"] = int(state["MaxNumProjectiles"])

    # -- fire: ammo / multishot -------------------------------------------------
    if fire:
        mode["multishot"] = fire.get("fireIterations", 1)
        mode["ammoCost"] = fire.get("ammoRequirement")
        mode["ammoType"] = fire.get("ammoType")

    # -- damage source resolution ------------------------------------------------
    sequence: list[dict[str, Any]] = []
    sequence_names = [
        name for name in (fire.get("projectileSequenceList") or ()) if isinstance(name, str) and name
    ]
    advance = bool(fire.get("advanceProjectileSequenceOnFire"))
    primary_source: Mapping[str, Any] | None = None
    crit_source: Mapping[str, Any] | None = None
    primary_path: str | None = None
    primary_label: str | None = None

    projectile_path, projectile = _resolve_ref(index, weapon_path, fire.get("projectileType"))

    if sequence_names and advance and projectile_path is None:
        # Deconstructor family: rotating sequence projectiles carry the damage.
        for name in sequence_names:
            seq_path, seq_obj = _resolve_ref(index, weapon_path, name)
            if not seq_obj:
                continue
            block = _damage_block(seq_obj) or {}
            # Crit for sequence projectiles: the glaive projectile carries no
            # crit fields and the impact's are an inherited placeholder (0/2x
            # from LotusGlaiveWeaponBase) — the in-game panel shows 0%/1.0x.
            # Only a crit value actually defined on the projectile (or a
            # NON-placeholder on the impact, i.e. a nonzero chance) is used.
            chance, mult = _crit_from(seq_obj)
            if chance is None:
                impact_chance = _number(impact.get("criticalHitChance"))
                if impact_chance:
                    chance = impact_chance
            if mult is None:
                impact_mult = _number(impact.get("criticalHitDamageMultiplier"))
                if impact_mult and chance is not None:
                    mult = impact_mult
            block["critChance"] = chance if chance is not None else 0.0
            block["critMultiplier"] = mult if mult is not None else 1.0
            sequence.append(
                {
                    "path": seq_path,
                    "name": name,
                    "damage": block or None,
                }
            )
        first = sequence[0]["damage"] if sequence else None
        if first:
            primary_source = sequence[0]
            primary_path = sequence[0]["path"]
            primary_label = "sequence"
            damage = dict(first)
            damage["sequenceProjectiles"] = [
                {k: v for k, v in item.items() if k != "damage"} for item in sequence
            ]
            damage["sequenceDamage"] = [item["damage"] for item in sequence]
    elif projectile and _has_amount(projectile.get("AttackData")):
        # Real numbers on the referenced projectile (Laser Rifle family).
        primary_source = projectile
        crit_source = projectile
        primary_path = projectile_path
        primary_label = "projectile"
        damage = _damage_block(projectile) or {}
    else:
        # Impact inline (hitscan/beams) or projectile shell with impact numbers
        # (Cryotra's grenade has no Amount; the impact carries the total and
        # ProcChance while the projectile keeps the crit stats).
        primary_label = "impact"
        primary_path = projectile_path if projectile else None
        crit_source = projectile if projectile else impact
        damage = _damage_block(impact) or _damage_block(fire) or {}

    if not damage:
        return None

    # -- crit / status / projectile metadata with impact fallback ----------------
    if primary_label != "sequence":
        chance, mult = _crit_from(crit_source) if crit_source else (None, None)
        if chance is None:
            chance = _number(impact.get("criticalHitChance"))
        if mult is None:
            mult = _number(impact.get("criticalHitDamageMultiplier"))
        damage["critChance"] = chance if chance is not None else 0.0
        damage["critMultiplier"] = mult if mult is not None else 1.0
        proc = _proc_from(primary_source) if primary_source else None
        if proc is None:
            proc = _proc_from(impact)
        if proc is not None:
            damage["procChance"] = proc

    if projectile_path and primary_label == "projectile":
        damage["projectile"] = projectile_path
    if projectile and primary_label in {"projectile", "impact"}:
        # Keep the key present (null when the projectile defines no speed) so
        # the mode schema stays stable for consumers of the frozen export.
        damage["flightSpeed"] = projectile.get("KinematicInitialSpeed")

    # Secondary projectile attacks (embed explosions etc.) stay visible.
    if primary_label != "sequence" and projectile:
        components = extract_mod._projectile_damage_components(projectile)
        if components:
            damage["components"] = components
            damage["radial"] = components[0]

    if isinstance(impact.get("damageFallOff"), list) and impact["damageFallOff"]:
        mode["falloffRange"] = impact["damageFallOff"]
        mode["falloffMinDamage"] = impact.get("damageFallOffMinDamage")

    mode["damage"] = damage
    return mode


def _has_glaive_fire_behaviour(weapon: Mapping[str, Any]) -> bool:
    """True when any fire behaviour is a GlaiveProjectileFireBehavior.

    That is the signature of the Deconstructor family: thrown-glaive companion
    weapons judged by the melee ruleset.  Hound melee weapons use a different
    behaviour (WeaponMeleeRadiusFireBehavior) and are intentionally not
    flagged — only the glaive structure carries the slam/parry fields the
    export records.
    """
    for entry in weapon.get("Behaviors") or ():
        if not isinstance(entry, Mapping):
            continue
        for key in entry:
            if key.startswith("fire:") and key != "fire:Type" and "Glaive" in key:
                return True
    return False


def melee_fields(weapon: Mapping[str, Any]) -> dict[str, Any] | None:
    """Record the glaive (melee-judged) structure for Deconstructor weapons."""
    if not _has_glaive_fire_behaviour(weapon):
        return None
    slam = weapon.get("SlamMeleeAttack")
    heavy_slam = weapon.get("HeavySlamMeleeAttack")
    parry = weapon.get("ParryAngle")
    empowered = weapon.get("BaseEmpoweredMeleeChance")
    if slam is None and heavy_slam is None and parry is None and empowered is None:
        return None

    def basename(value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]

    fields: dict[str, Any] = {
        "slamAttack": basename(slam),
        "heavySlamAttack": basename(heavy_slam),
        "parryAngle": parry,
        "empoweredMeleeChance": empowered,
    }
    if weapon.get("EmpoweredMeleeChancePerCombo") is not None:
        fields["empoweredMeleeChancePerCombo"] = weapon.get("EmpoweredMeleeChancePerCombo")
    return fields


def companion_rows(
    index: packages_mod.PackageIndex, export_rows: list[dict[str, Any]]
) -> list[tuple[dict[str, Any], Mapping[str, Any]]]:
    """Pair each companion export row with its resolved raw weapon."""
    out = []
    for row in export_rows:
        if row.get("slot") != "companion":
            continue
        weapon = index.resolve(row["path"])
        if weapon:
            out.append((row, weapon))
    return out


def rebuild(
    index: packages_mod.PackageIndex, export_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Rebuild every companion row; returns the new rows (path-keyed)."""
    new_rows = []
    for existing, weapon in companion_rows(index, export_rows):
        row = {key: value for key, value in existing.items() if key not in _OWNED_ROW_FIELDS}
        modes = []
        behaviours = weapon.get("Behaviors")
        count = len(behaviours) if isinstance(behaviours, list) else 0
        for position in range(count):
            mode = build_mode(index, existing["path"], weapon, position)
            if mode is not None:
                modes.append(mode)
        row["fireModes"] = modes
        melee = melee_fields(weapon)
        if melee:
            row["isMeleeJudged"] = True
            row["meleeFields"] = melee
        else:
            row.pop("isMeleeJudged", None)
            row.pop("meleeFields", None)
        new_rows.append(row)
    return new_rows


def apply_merge(export_path: Path, merge_rows: list[dict[str, Any]]) -> tuple[int, int]:
    """Patch weapons.json rows by path; append rows not yet present.

    Returns (patched, appended).  Retries once when the file changes between
    the read and the write (archgun agent finishing concurrently).
    """
    import time

    for attempt in range(2):
        stat_before = export_path.stat()
        payload = json.loads(export_path.read_text(encoding="utf-8"))
        rows = payload["data"]
        by_path = {row.get("path"): row for row in rows}
        patched = appended = 0
        for new_row in merge_rows:
            path = new_row.get("path")
            if path in by_path:
                by_path[path] = new_row
                patched += 1
            else:
                by_path[path] = new_row
                appended += 1
        stat_after = export_path.stat()
        if (stat_before.st_mtime_ns, stat_before.st_size) == (stat_after.st_mtime_ns, stat_after.st_size):
            payload["data"] = sorted(by_path.values(), key=lambda row: str(row.get("path") or ""))
            payload["count"] = len(payload["data"])
            tmp = export_path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True),
                encoding="utf-8",
            )
            tmp.replace(export_path)
            return patched, appended
        print(f"[race] weapons.json changed mid-merge (attempt {attempt + 1}); retrying")
        time.sleep(0.5)
    raise RuntimeError("weapons.json kept changing during merge; run --apply again")


def fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def summary(
    old_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]]
) -> str:
    old_by_path = {r["path"]: r for r in old_rows}
    lines = []
    header = (
        f"{'weapon':<26} {'old total':>9} {'new total':>9} "
        f"{'old crit':>9} {'new crit':>9}  note"
    )
    lines.append(header)
    lines.append("-" * len(header))
    for new in sorted(new_rows, key=lambda r: str(r.get("nameEn") or r.get("name"))):
        path = new["path"]
        old = old_by_path.get(path)
        name = str(new.get("nameEn") or new.get("name") or path.rsplit("/", 1)[-1])

        def mode_total(row: dict[str, Any] | None) -> Any:
            if not row:
                return "-"
            modes = row.get("fireModes") or []
            if not modes:
                return "-"
            d = (modes[0] or {}).get("damage") or {}
            return d.get("total", "-")

        def mode_crit(row: dict[str, Any] | None) -> Any:
            if not row:
                return "-"
            modes = row.get("fireModes") or []
            if not modes:
                return "-"
            d = (modes[0] or {}).get("damage") or {}
            return d.get("critChance", "-")

        note = ""
        if new.get("isMeleeJudged"):
            note = "glaive sequence (melee-judged)"
        elif old is None:
            note = "NEW"
        lines.append(
            f"{name[:26]:<26} {fmt(mode_total(old)):>9} {fmt(mode_total(new)):>9} "
            f"{fmt(mode_crit(old)):>9} {fmt(mode_crit(new)):>9}  {note}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW, help="raw dump dir with packages/ + Packages.bin")
    parser.add_argument("--export", type=Path, default=DEFAULT_EXPORT, help="frozen weapons.json to merge into")
    parser.add_argument("--apply", action="store_true", help="apply the merge file into weapons.json")
    parser.add_argument("--summary", action="store_true", help="print the before/after table only")
    parser.add_argument("--dry-run", action="store_true", help="build the merge file but do not suggest applying")
    args = parser.parse_args(argv)

    index = load_index(args.raw)
    payload = json.loads(args.export.read_text(encoding="utf-8"))
    rows = payload["data"]
    old_companions = [r for r in rows if r.get("slot") == "companion"]
    print(f"raw dump: {args.raw}")
    print(f"export rows: {len(rows)}; companion rows: {len(old_companions)}")

    new_rows = rebuild(index, rows)
    print(f"rebuilt companion rows: {len(new_rows)}")

    print(summary(old_companions, new_rows))

    if args.summary:
        return 0

    MERGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MERGE_FILE.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "source": str(args.raw),
                "rows": new_rows,
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\nmerge file written: {MERGE_FILE} ({len(new_rows)} rows)")

    if args.apply and not args.dry_run:
        patched, appended = apply_merge(args.export, new_rows)
        print(f"applied: {patched} patched, {appended} appended")
    elif not args.dry_run:
        print("apply with: python -X utf8 tools/extract-companion-weapons.py --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
