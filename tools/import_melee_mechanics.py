"""Extract melee mechanics from the client's Packages.bin and animation headers.

Usage:
  python tools/import_melee_mechanics.py --packages-bin <Packages.bin_H> \
      --anim-root <exporter --write-raw output>/Debug --build-label 2026.10.08 \
      [--output data/mechanics/melee-mechanics.json] [--list-anim-dirs]

Packages.bin (Warframe-Exporter-CLI --write-raw --package Misc --internal-path
/Packages.bin) carries per weapon: impact AttackData, crit, attack speed, combo
counter, heavy-attack timing, Slams[] and glaive throw data; per stance (melee
tree): attack sets per combo context, each attack's damage / proc multipliers,
forced procs, combo hits, per-swing overrides and animation; per animation:
normalized event times (StartMeleeSweep, MeleeSlam, ...).

Animation length is not in Packages.bin. The ``_H`` header the exporter writes
for an animation stores 1/duration as the float 12 bytes before "Take 001"
(30 fps whole frames). ``--list-anim-dirs`` prints the folders to extract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "tools"))
from packages_bin import PackagesBin  # noqa: E402
from wfarsenal.ee import parse_ee  # noqa: E402

SCHEMA_VERSION = 1
WEAPONS = ROOT / "data" / "export" / "2026.08.13.13.24" / "weapons.json"
STANCES = ROOT / "data" / "stances.json"
CONTEXTS = ("CC_GROUND", "CC_GROUND_BRANCH_A", "CC_GROUND_BRANCH_B", "CC_GROUND_BRANCH_C",
            "CC_GROUND_HEAVY", "CC_GROUND_HELD_HEAVY", "CC_SLIDING", "CC_AIR", "CC_AIR_RIGHT", "CC_AIR_LEFT")
HIT_EVENTS = ("StartMeleeSweep", "StartMeleeSweepA", "StartMeleeSweepB", "StartMeleeSweepC", "StartMeleeThrust")
END_EVENTS = ("EndMeleeSweep", "EndMeleeThrust")


class Packages:
    def __init__(self, path: Path):
        reader = PackagesBin(path)
        self.entities: dict[str, tuple[str, bytes | None]] = {}
        self._reader = reader
        for entity in reader.iter_entities():
            self.entities[entity.path] = (entity.parent, entity)
        self.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()

    def own(self, path: str) -> dict[str, Any]:
        row = self.entities.get(path)
        if not row or row[1].attr is None:
            return {}
        text = self._reader.decompress(row[1]).decode("utf-8", "replace")
        # Some entities carry whitespace-only lines the notation parser rejects.
        text = text.replace("\x00", "")
        return parse_ee("\n".join(line for line in text.splitlines() if line.strip()))

    def exists(self, path: str) -> bool:
        return path in self.entities

    def parent(self, path: str) -> str:
        row = self.entities.get(path)
        return row[0] if row else ""

    @lru_cache(maxsize=None)
    def resolve(self, path: str) -> dict[str, Any]:
        """Child-first merge over the inheritance chain (structs merge deeply)."""
        parent = self.parent(path)
        base = dict(self.resolve(parent)) if parent and parent != path and self.exists(parent) else {}
        return _merge(base, self.own(path))

    def locate(self, owner: str, name: str) -> str | None:
        """A relative type name resolves against the owner's folder chain."""
        if not name:
            return None
        if name.startswith("/"):
            return name if self.exists(name) else None
        path = owner
        while path:
            candidate = path.rsplit("/", 1)[0] + "/" + name
            if self.exists(candidate):
                return candidate
            for prefix in ("/Lotus/Weapons/Tenno/Melee/",):
                candidate = prefix + name
                if self.exists(candidate):
                    return candidate
            path = self.parent(path)
        return None


def _merge(base: dict[str, Any], child: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _num(value: Any, default: float | None = None) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def anim_entity(packages: Packages, anim: str) -> str | None:
    for candidate in (anim, anim + ".fbx", anim + "_anim.fbx"):
        if packages.exists(candidate):
            return candidate
    return None


def anim_duration(anim_root: Path | None, entity: str | None) -> float | None:
    if anim_root is None or not entity:
        return None
    header = anim_root / (entity.lstrip("/") + "_H")
    if not header.is_file():
        return None
    data = header.read_bytes()
    at = data.find(b"Take 001")
    if at < 16:
        return None
    rate = struct.unpack_from("<f", data, at - 12)[0]
    return round(1.0 / rate, 6) if rate > 0 else None


def anim_header_events(anim_root: Path | None, entity: str | None) -> list[dict[str, Any]]:
    """Events baked into the animation header (u32 length + text after the path)."""
    if anim_root is None or not entity:
        return []
    header = anim_root / (entity.lstrip("/") + "_H")
    if not header.is_file():
        return []
    data = header.read_bytes()
    if len(data) < 24:
        return []
    path_len = struct.unpack_from("<I", data, 20)[0]
    at = 24 + path_len
    if at + 4 > len(data):
        return []
    text_len = struct.unpack_from("<I", data, at)[0]
    if not 0 < text_len < 1 << 20 or at + 4 + text_len > len(data):
        return []
    text = data[at + 4: at + 4 + text_len].decode("utf-8", "replace")
    try:
        return list(parse_ee(text).get("Events") or [])
    except ValueError:
        return []


def attack_row(packages: Packages, path: str, anim_root: Path | None) -> dict[str, Any]:
    raw = packages.resolve(path)
    props = raw.get("AttackProperties") or {}
    base = dict(
        atten=_num(props.get("BaseDamageAtten"), 1.0),
        procAtten=_num(props.get("ProcChanceAtten"), 1.0),
        extraProcs=list(props.get("ExtraProcs") or ()),
        comboHits=_num(props.get("ComboHitsToAdd"), 1.0),
        damagePct={k: v for k, v in (props.get("DamagePctAtten") or {}).items() if v != 1},
    )
    swings = []
    for override in raw.get("PerSwingOverrides") or ():
        if not override.get("overrideAttackProperties"):
            swings.append(None)
            continue
        p = override.get("attackProperties") or {}
        swings.append(dict(
            atten=_num(p.get("BaseDamageAtten"), 1.0), procAtten=_num(p.get("ProcChanceAtten"), 1.0),
            extraProcs=list(p.get("ExtraProcs") or ()), comboHits=_num(p.get("ComboHitsToAdd"), 1.0),
            damagePct={k: v for k, v in (p.get("DamagePctAtten") or {}).items() if v != 1},
        ))
    anim = ((raw.get("Attack") or {}).get("Animation")) or ""
    entity = anim_entity(packages, anim) if anim else None
    # Packages.bin events override the ones baked into the animation file.
    events = ((packages.resolve(entity).get("Events") or []) if entity else []) or anim_header_events(anim_root, entity)
    hits = [e for e in events if e.get("Event") in HIT_EVENTS]
    extra = ((raw.get("Extra") or {}).get("Animation")) or ""
    extra_entity = anim_entity(packages, extra) if extra else None
    return dict(
        **base,
        swings=swings,
        anim=entity or anim or None,
        duration=anim_duration(anim_root, entity),
        hits=[dict(t=_num(e.get("Time")), event=e.get("Event"), param=e.get("Param")) for e in hits],
        # Every gameplay event (sound / effect cues dropped): a weapon's Slams[]
        # entry fires on its TriggeringAnimEvent, inside ground combos too.
        events=[dict(t=_num(e.get("Time")), event=e.get("Event")) for e in events
                if e.get("Event") and not str(e.get("Event")).startswith("SFX")
                and e.get("Event") not in HIT_EVENTS and e.get("Event") not in END_EVENTS],
        extraAction=raw.get("ExtraAction") or None,
        extraAnim=extra_entity or extra or None,
        extraDuration=anim_duration(anim_root, extra_entity),
    )


def tree_row(packages: Packages, path: str) -> dict[str, Any]:
    raw = packages.resolve(path)
    sets = raw.get("EquippedAttackSets") or {}
    contexts = {}
    for context in CONTEXTS:
        attack_set = sets.get(context)
        if attack_set:
            located = packages.locate(path, attack_set) or attack_set
            contexts[context] = [packages.locate(located, a) or a
                                 for a in (packages.resolve(located).get("Attacks") or ())]
    aerial = {k: packages.locate(path, v) or v for k, v in (raw.get("AerialAttacks") or {}).items() if v}
    return dict(contexts=contexts, aerial=aerial,
                followThrough=_num(raw.get("AvatarDamageFalloff")),
                compat=list(raw.get("CompatibilityTags") or ()))


def _behavior(raw: dict[str, Any], kind: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for behavior in raw.get("Behaviors") or ():
        impact = next((v for k, v in behavior.items() if k == f"impact:{kind}"), None)
        if impact is not None:
            state = next((v for k, v in behavior.items() if k.startswith("state:") and isinstance(v, dict)), {})
            fire = next((v for k, v in behavior.items() if k.startswith("fire:") and isinstance(v, dict)), {})
            return impact, state, fire
    return {}, {}, {}


def slam_rows(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for slam in raw.get("Slams") or ():
        attack = slam.get("AttackData") or {}
        rows.append(dict(
            event=slam.get("TriggeringAnimEvent"), radius=_num(slam.get("Radius")),
            radiusMin=_num(slam.get("RadiusMin")), falloff=bool(slam.get("FallOff")),
            falloffMax=_num(slam.get("FallOffMax")), canCrit=bool(slam.get("CanCrit")),
            comboMultiplier=bool(slam.get("CanUseComboMultiplier")),
            weaponAmount=bool(slam.get("UseImpactBehaviorAttackDataAmount")),
            weaponProcChance=bool(slam.get("UseWeaponProcChance")),
            modifiedRadius=bool(slam.get("UseModifiedRadius")),
            attenuation=_num(slam.get("BaseDamageAttenuation"), 1.0),
            damageType=attack.get("Type"), amount=_num(attack.get("Amount")),
            procChance=_num(attack.get("ProcChance")), forcedProcs=list(attack.get("ForcedProcs") or ()),
            currentAttack=bool(slam.get("UseCurrentMeleeAttackForDamage")), aerial=bool(slam.get("IsAerialSlam")),
        ))
    return rows


def glaive_row(packages: Packages, path: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    for behavior in raw.get("Behaviors") or ():
        fire = behavior.get("fire:GlaiveProjectileFireBehavior") or behavior.get("fire:HomingGlaiveFireBehavior")
        if not isinstance(fire, dict):
            continue
        out: dict[str, Any] = {}
        for key, name in (("projectile", fire.get("projectileType")), ("turbo", fire.get("TurboProjectileType"))):
            proj_path = packages.locate(path, name) if name else None
            if not proj_path:
                continue
            proj = packages.resolve(proj_path)
            attack, explosive = proj.get("AttackData") or {}, proj.get("ExplosiveAttack") or {}
            out[key] = dict(
                path=proj_path, amount=_num(attack.get("Amount")), procChance=_num(attack.get("ProcChance")),
                crit=_num(proj.get("CriticalChance")), critMultiplier=_num(proj.get("CriticalMultiplier")),
                types={k: v for k, v in attack.items() if k.startswith("DT_") and v},
                forcedProcs=list(attack.get("ForcedProcs") or ()),
                explosion=_num(explosive.get("Amount")), explosionProcChance=_num(explosive.get("ProcChance")),
                radius=_num(proj.get("DamageRadius")), falloff=_num(proj.get("ExplosionFallOff")),
                heavyRecallAtten=_num(proj.get("HeavyRecallDamageAtten")),
                heavyRecallProcs=list(proj.get("HeavyRecallProcs") or ()),
                speed=_num(proj.get("KinematicInitialSpeed")), maxReflections=_num(proj.get("MaxReflections")),
                autoRecall=_num(proj.get("AutoRecallTimer")), maxLife=_num(proj.get("MaxLife")),
                seekDistance=_num(proj.get("SeekDistance")), minFlightDistance=_num(proj.get("MinFlightDistance")),
            )
        if out:
            return out
    return None


def weapon_row(packages: Packages, path: str) -> dict[str, Any]:
    raw = packages.resolve(path)
    kind = "MeleeImpactBehavior"
    impact, state, _fire = _behavior(raw, kind)
    attack = impact.get("AttackData") or {}
    combo_data = state.get("ComboData") or {}
    tree_name = raw.get("MeleeTreeType") or ""
    tree = packages.locate(path, tree_name) if tree_name else None
    stance = (raw.get("DefaultModOverrides") or {}).get("Stance") or None
    return dict(
        damage=dict(amount=_num(attack.get("Amount")), procChance=_num(attack.get("ProcChance")),
                    types={k: v for k, v in attack.items() if k.startswith("DT_") and v},
                    forcedProcs=list(attack.get("ForcedProcs") or ()),
                    crit=_num(impact.get("criticalHitChance")), critMultiplier=_num(impact.get("criticalHitDamageMultiplier"))),
        attackSpeed=(_num(state.get("fireRate")) or 60.0) / 60.0,
        combo=dict(baseHits=_num(impact.get("BaseHitCount")), tierStep=_num(impact.get("HitReqNextTierOperator")),
                   tierOperation=impact.get("HitReqNextTierOperationType"), cap=_num(impact.get("HitCounterCap")),
                   baseMultiplier=_num(impact.get("BaseHitMultipler")), seconds=_num(impact.get("TimeBetweenHits")),
                   initial=_num(impact.get("InitialHitCounter"))),
        heavy=dict(chargeTime=_num(combo_data.get("HeavyMeleeChargeTime")), disableTime=_num(state.get("MeleeDisableTime")),
                   consumeCombo=state.get("ConsumeComboOnHeavyAttack"), tapTime=_num(state.get("TapTime")),
                   chargeDuration=_num(state.get("ChargeDuration")), hasHeavy=state.get("HasHeavyAttack")),
        slams=slam_rows(raw),
        slamAttack=packages.locate(path, raw.get("SlamMeleeAttack") or "") or raw.get("SlamMeleeAttack"),
        heavySlamAttack=packages.locate(path, raw.get("HeavySlamMeleeAttack") or "") or raw.get("HeavySlamMeleeAttack"),
        slamRadiusClamps=raw.get("SlamRadiusPercentageClamps"),
        fullSlamRadiusHeight=_num(raw.get("FullSlamRadiusHeight")),
        tree=tree, stance=stance,
        glaive=glaive_row(packages, path, raw),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--anim-root", type=Path)
    parser.add_argument("--build-label", required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "mechanics" / "melee-mechanics.json")
    parser.add_argument("--list-anim-dirs", action="store_true")
    args = parser.parse_args()
    packages = Packages(args.packages_bin)
    exports = json.loads(WEAPONS.read_text(encoding="utf-8"))["data"]
    melee = [w for w in exports if w.get("slot") == "melee" and packages.exists(str(w.get("path")))]
    weapons = {w["path"]: weapon_row(packages, w["path"]) for w in melee}
    stance_paths = {row["path"] for row in json.loads(STANCES.read_text(encoding="utf-8"))["stances"]}
    stance_paths |= {row["stance"] for row in weapons.values() if row.get("stance")}
    tree_paths = {row["tree"] for row in weapons.values() if row.get("tree")}
    trees = {p: tree_row(packages, p) for p in sorted(tree_paths | stance_paths) if packages.exists(p)}
    attack_paths = {a for t in trees.values() for attacks in t["contexts"].values() for a in attacks}
    attack_paths |= {a for t in trees.values() for a in t["aerial"].values()}
    attack_paths |= {w[k] for w in weapons.values() for k in ("slamAttack", "heavySlamAttack") if w.get(k)}
    attacks = {p: attack_row(packages, p, args.anim_root) for p in sorted(attack_paths) if packages.exists(p)}
    if args.list_anim_dirs:
        dirs = sorted({a[k].rsplit("/", 1)[0] for a in attacks.values() for k in ("anim", "extraAnim")
                       if a.get(k) and a[k].startswith("/")})
        print("\n".join(dirs))
        return 0
    missing = sorted(p for p, a in attacks.items() if a["anim"] and a["duration"] is None and a["hits"])
    payload = dict(
        schemaVersion=SCHEMA_VERSION, buildLabel=args.build_label,
        sources=dict(packagesBin=args.packages_bin.name, packagesBinSha256=packages.sha256,
                     animHeaders="Warframe-Exporter-CLI --write-raw /Lotus/Animations/... (_H, 1/duration before 'Take 001')"),
        counts=dict(weapons=len(weapons), trees=len(trees), attacks=len(attacks), attacksWithoutDuration=len(missing)),
        weapons=weapons, trees=trees, attacks=attacks,
    )
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(payload["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
