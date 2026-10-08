"""Melee attacks as discrete hits (data/mechanics/melee-mechanics.json).

An attack plays one animation; every sweep event in it lands one hit. A hit's
damage / status multipliers, forced procs and combo hits come from the attack's
AttackProperties unless the matching PerSwingOverrides entry overrides them.
Event times are normalized to the animation, whose length is in seconds at 1.0
attack speed.
"""

from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

HIT_EVENTS = ("StartMeleeSweep", "StartMeleeSweepA", "StartMeleeSweepB", "StartMeleeSweepC", "StartMeleeThrust")


@lru_cache(maxsize=1)
def reference() -> dict[str, Any]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return json.loads((root / "data/mechanics/melee-mechanics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"weapons": {}, "trees": {}, "attacks": {}}


# Slams[] entries that are visual only (1 m ground contact flash) or fire on
# the dedicated slam / heavy-slam attacks rather than inside a combo.
_COSMETIC_SLAMS = frozenset({"GroundAttackEffect"})


def attack_hits(attack: Mapping[str, Any], slams: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One row per landed hit, in time order.

    Sweep hits carry the attack's (or the per-swing override's) properties. An
    animation event that matches one of the weapon's Slams[] triggers adds a
    radial hit with that slam's attenuation (``kind == 'slam'``).
    """
    events = list(attack.get("hits") or ())
    swings = list(attack.get("swings") or ())
    count = max(len(events), 1)
    rows = []
    for index in range(count):
        override = swings[index] if index < len(swings) else None
        props = override or attack
        rows.append(dict(
            kind="sweep",
            t=float(events[index]["t"]) if index < len(events) and events[index].get("t") is not None else 0.5,
            atten=float(props.get("atten", 1.0)),
            procAtten=float(props.get("procAtten", 1.0)),
            extraProcs=list(props.get("extraProcs") or ()),
            comboHits=float(props.get("comboHits", 1.0)),
            damagePct=dict(props.get("damagePct") or {}),
        ))
    for event in attack.get("events") or ():
        slam = (slams or {}).get(event.get("event"))
        if slam is None or event.get("event") in _COSMETIC_SLAMS:
            continue
        rows.append(dict(
            kind="slam", slam=event.get("event"), t=float(event.get("t") or 0.0),
            atten=float(slam.get("attenuation") or 1.0), procAtten=1.0,
            extraProcs=list(slam.get("forcedProcs") or ()), comboHits=1.0, damagePct={},
        ))
    rows.sort(key=lambda row: row["t"])
    return rows


def weapon_slams(weapon_path: str) -> dict[str, Mapping[str, Any]]:
    rows = (reference().get("weapons") or {}).get(weapon_path, {}).get("slams") or ()
    return {row["event"]: row for row in rows if row.get("event")}


# -- Attack routes ------------------------------------------------------------
#
# A route is a loop of segments: ``fixed`` seconds (movement, wind-up, flight;
# attack speed does not shorten them) plus ``anim`` seconds at 1.0 attack speed,
# then optionally one hit. The replay lands a hit, then waits the segments up
# to the next hit.

ROUTES = ("combo", "slam", "slamBullet", "glaive")
COMBO_CONTEXTS = ("CC_GROUND", "CC_GROUND_BRANCH_A", "CC_GROUND_BRANCH_B", "CC_GROUND_BRANCH_C")
# TennoWalkAttribs: JumpHeight 5, AdditionalGravity -9 (on top of 9.8);
# TennoClimbController.BulletJumpSpeed 2.5; PlayerMeleeWeapon
# FullSlamRadiusHeight 10. The plunge after a slam input has no speed in the
# data; it is taken as a free fall from the apex (conservative).
GRAVITY = 9.8 + 9.0
JUMP_HEIGHT = 5.0
BULLET_JUMP_SPEED = 2.5
BULLET_SLAM_HEIGHT = 10.0
GLAIVE_DEFAULT_DISTANCE = 10.0
# 77 weapons carry HeavyMeleeChargeTime 2.0 where their class siblings carry
# 0.35-1.25; 2.0 is read as unset and the class value is used instead.
UNSET_CHARGE_TIME = 2.0


def default_route(weapon: Mapping[str, Any]) -> str:
    """Bot policy: hammers slam from a vertical bullet jump, glaives heavy-throw and
    detonate, others combo."""
    tags = {str(t).upper() for t in weapon.get("compatTags") or ()}
    row = (reference().get("weapons") or {}).get(str(weapon.get("path")), {})
    if "GLAIVES_STANCE" in tags and row.get("glaive"):
        return "glaive"
    if "HAMMERS_STANCE" in tags:
        return "slamBullet"
    return "combo"


def jump_times(route: str) -> tuple[float, float, float]:
    """(rise seconds, fall seconds, slam height) for the slam routes."""
    if route == "slamBullet":
        v0 = BULLET_JUMP_SPEED * math.sqrt(2.0 * GRAVITY * JUMP_HEIGHT)
        height = BULLET_SLAM_HEIGHT
        rise = (v0 - math.sqrt(max(v0 * v0 - 2.0 * GRAVITY * height, 0.0))) / GRAVITY
    else:
        height = JUMP_HEIGHT
        rise = math.sqrt(2.0 * height / GRAVITY)
    return rise, math.sqrt(2.0 * height / GRAVITY), height


def _wait_fraction(attack: Mapping[str, Any]) -> float | None:
    waits = [float(e["t"]) for e in attack.get("events") or ()
             if str(e.get("event", "")).startswith("WaitStart") and e.get("t") is not None]
    return min(waits) if waits else None


def _combo_segments(attacks, slams):
    segments = []
    for index, attack in enumerate(attacks):
        duration = float(attack.get("duration") or 0.5)
        wait = _wait_fraction(attack)
        end = duration * wait if wait is not None and index < len(attacks) - 1 else duration
        previous = 0.0
        for hit in attack_hits(attack, slams):
            at = min(max(hit["t"], 0.0) * duration, end)
            hit = dict(hit, canCrit=True)
            if hit["kind"] == "slam":
                hit.update(radial=True, canCrit=False, slam=True)
            segments.append(dict(fixed=0.0, anim=max(at - previous, 0.0), hit=hit))
            previous = max(previous, at)
        segments.append(dict(fixed=0.0, anim=max(end - previous, 0.0), hit=None))
    return segments


def loop_rate(segments, attack_speed=1.0):
    seconds = sum(s["fixed"] + s["anim"] / attack_speed for s in segments)
    weight = sum(s["hit"]["atten"] for s in segments if s.get("hit"))
    return weight / seconds if seconds > 0 else 0.0


def _stance_tree(ref, row, stance):
    trees = ref.get("trees") or {}
    for path in (stance, row.get("stance"), row.get("tree")):
        if path and path in trees and any(trees[path]["contexts"].get(c) for c in COMBO_CONTEXTS):
            return path, trees[path]
    return None, None


def class_charge_time(ref, row):
    value = (row.get("heavy") or {}).get("chargeTime")
    if value is not None and abs(value - UNSET_CHARGE_TIME) > 1e-6:
        return float(value), False
    tree = row.get("tree")
    siblings = sorted(float(w["heavy"]["chargeTime"]) for w in (ref.get("weapons") or {}).values()
                      if w.get("tree") == tree and (w.get("heavy") or {}).get("chargeTime") is not None
                      and abs(w["heavy"]["chargeTime"] - UNSET_CHARGE_TIME) > 1e-6)
    return (siblings[len(siblings) // 2] if siblings else 0.7), True


def build_schedule(weapon: Mapping[str, Any], route: str | None = None, *, stance: str | None = None,
                   combo: str | None = None, target_distance: float | None = None) -> dict[str, Any] | None:
    """The hit loop of one melee route, or None when the weapon has no data."""
    ref = reference()
    row = (ref.get("weapons") or {}).get(str(weapon.get("path") or ""))
    if not row:
        return None
    route = route or default_route(weapon)
    attacks = ref.get("attacks") or {}
    slams = {s["event"]: s for s in row.get("slams") or () if s.get("event")}
    notes: list[str] = []
    melee_damage = row.get("damage") or {}
    melee_amount = float(melee_damage.get("amount") or 0.0)
    if route == "glaive" and not row.get("glaive"):
        notes.append("melee-route-glaive-unavailable-using-combo")
        route = "combo"
    if route in ("slam", "slamBullet") and not (slams.get("HeavySlam") or slams.get("MeleeSlam")):
        notes.append("melee-route-slam-unavailable-using-combo")
        route = "combo"
    tree_path, tree = _stance_tree(ref, row, stance)
    common = dict(stance=tree_path, notes=notes, comboSpec=row.get("combo") or {},
                  meleeCrit=(melee_damage.get("crit"), melee_damage.get("critMultiplier")))
    if route == "combo":
        if tree is None:
            return None
        options = []
        for context in ([combo] if combo in COMBO_CONTEXTS else COMBO_CONTEXTS):
            chain = [attacks[p] for p in tree["contexts"].get(context) or () if p in attacks]
            if chain:
                segments = _combo_segments(chain, slams)
                options.append((loop_rate(segments), context, segments))
        if not options:
            return None
        _rate, context, segments = max(options, key=lambda item: item[0])
        return dict(common, route="combo", combo=context, segments=segments, label=context)
    if route in ("slam", "slamBullet"):
        heavy = slams.get("HeavySlam")
        slam = heavy or slams["MeleeSlam"]
        direct_path = row.get("heavySlamAttack") if heavy else row.get("slamAttack")
        direct = float((attacks.get(direct_path) or {}).get("atten") or (3.0 if heavy else 2.0))
        aerial = (tree or {}).get("aerial") or {}
        strike = attacks.get(aerial.get("BP_CROUCH") or "") or {}
        strike_seconds = float(strike.get("duration") or 1.0) * (_wait_fraction(strike) or 1.0)
        rise, fall, height = jump_times(route)
        notes.append(f"slam-cycle: rise {rise:.2f}s + free-fall {fall:.2f}s from {height:g} m (plunge speed not in data)")
        segments = [
            dict(fixed=rise + fall, anim=0.0, hit=dict(
                kind="slamDirect", t=0.0, atten=direct, procAtten=1.0, extraProcs=[], comboHits=1.0,
                damagePct={}, canCrit=True, heavy=bool(heavy), slam=True, comboMultiplier=bool(heavy))),
            dict(fixed=0.0, anim=0.0, hit=dict(
                kind="slamRadial", t=0.0, atten=float(slam.get("attenuation") or 1.0), procAtten=1.0,
                extraProcs=list(slam.get("forcedProcs") or ()), comboHits=0.0, damagePct={},
                canCrit=bool(slam.get("canCrit")), radial=True, slam=True, heavy=bool(heavy),
                damageType=slam.get("damageType"), comboMultiplier=bool(slam.get("comboMultiplier")),
                consumesCombo=bool(heavy))),
            dict(fixed=0.0, anim=strike_seconds, hit=None),
        ]
        return dict(common, route=route, segments=segments, label="heavy-slam" if heavy else "slam",
                    slamHeight=height)
    glaive = row["glaive"]
    proj = glaive.get("turbo") or glaive.get("projectile")
    charge, guessed = class_charge_time(ref, row)
    if guessed:
        notes.append("heavy-wind-up-from-class")
    distance = GLAIVE_DEFAULT_DISTANCE if target_distance is None else float(target_distance)
    flight = distance / float(proj.get("speed") or 55.0)
    heavy_set = (tree or {}).get("contexts", {}).get("CC_GROUND_HEAVY") or ()
    throw = attacks.get(heavy_set[0]) if heavy_set else None
    throw_seconds = float((throw or {}).get("duration") or 0.7)
    scale = float(proj.get("amount") or 0.0) / melee_amount if melee_amount else 1.0
    explosion = float(proj.get("explosion") or 0.0) * float(proj.get("heavyRecallAtten") or 1.0)
    notes.append(f"glaive-cycle: wind-up {charge:g}s + throw {throw_seconds:.2f}s + flight {flight:.2f}s ({distance:g} m)")
    melee_proc = float(melee_damage.get("procChance") or 0.0)
    base = dict(procAtten=float(proj.get("procChance") or 0.0) / melee_proc if melee_proc else 1.0,
                critChance=proj.get("crit"), critMultiplier=proj.get("critMultiplier"), damagePct={},
                heavy=True, projectile=True)
    segments = [
        dict(fixed=charge, anim=throw_seconds, hit=None, chargeScaled=True),
        dict(fixed=flight, anim=0.0, hit=dict(
            base, kind="glaiveDirect", t=0.0, atten=scale, canCrit=True, comboHits=1.0,
            extraProcs=list(proj.get("forcedProcs") or ()), comboMultiplier=False)),
        dict(fixed=0.0, anim=0.0, hit=dict(
            base, kind="glaiveExplosion", t=0.0, atten=explosion / melee_amount if melee_amount else 1.0,
            canCrit=True, radial=True, damageType="DT_EXPLOSION", comboHits=0.0,
            extraProcs=list(proj.get("heavyRecallProcs") or ()), comboMultiplier=True)),
    ]
    return dict(common, route="glaive", segments=segments, label="heavy-throw-detonate")


def combo_multiplier(spec: Mapping[str, Any], count: float) -> float:
    """1x below the first tier, then +1x per tier (wiki: 2x to 12x)."""
    first = float(spec.get("baseHits") or 20.0)
    step = float(spec.get("tierStep") or first)
    cap = float(spec.get("cap") or 220.0)
    count = min(max(float(count), 0.0), cap)
    if count < first:
        return 1.0
    return float(spec.get("baseMultiplier") or 1.0) + 1.0 + math.floor((count - first) / step + 1e-9)


def combo_tier(spec: Mapping[str, Any], count: float) -> int:
    return int(round(combo_multiplier(spec, count) - 1.0))


class Loop:
    """Walks a route's segments; ``next`` returns (hit, seconds until it lands)."""

    def __init__(self, schedule: Mapping[str, Any]):
        self.segments = list(schedule["segments"])
        self.index = 0

    def next(self, attack_speed: float, charge_speed: float = 1.0) -> tuple[dict[str, Any], float]:
        waited = 0.0
        for _ in range(len(self.segments) + 1):
            segment = self.segments[self.index]
            self.index = (self.index + 1) % len(self.segments)
            fixed = segment["fixed"] / charge_speed if segment.get("chargeScaled") else segment["fixed"]
            waited += fixed + segment["anim"] / max(attack_speed, 1e-9)
            if segment.get("hit"):
                return segment["hit"], waited
        raise ValueError("melee route has no hits")


_PROC_TYPES = {"PT_KNOCKBACK": "DT_IMPACT", "PT_FRAILTY": "DT_PUNCTURE", "PT_BLEEDING": "DT_SLASH",
               "PT_IMMOLATION": "DT_FIRE", "PT_CHILLED": "DT_FREEZE", "PT_ELECTROCUTION": "DT_ELECTRICITY",
               "PT_POISONED": "DT_POISON", "PT_FLASHBANG": "DT_EXPLOSION", "PT_RAD_TOX": "DT_RADIATION",
               "PT_ASPHYXIATION": "DT_GAS", "PT_MAGNETIZED": "DT_MAGNETIC", "PT_INFECTED": "DT_VIRAL",
               "PT_CAUSTIC_BURN": "DT_CORROSIVE"}
_PHYSICAL = ("DT_IMPACT", "DT_PUNCTURE", "DT_SLASH")


def apply_hit(stats, hit: Mapping[str, Any], *, melee_crit, heavy_multiplier: float = 1.0):
    """This hit's stats: damage / status multipliers, forced procs, crit.

    Crowd-control procs (stagger, knockdown, lift, ragdoll) are not status
    effects and are dropped; Knockback counts as an Impact proc as elsewhere.
    """
    from dataclasses import replace
    factor = float(hit.get("atten", 1.0))
    if hit.get("slam"):
        factor *= float(getattr(stats, "slam_damage_ratio", 1.0) or 1.0)
    if hit.get("comboMultiplier"):
        factor *= heavy_multiplier
    pct = hit.get("damagePct") or {}
    damage = {k: v * factor * float(pct.get(k, 1.0)) for k, v in stats.damage_types.items()}
    target = hit.get("damageType")
    if target and target not in ("DT_PHYSICAL", "DT_ANY"):
        # Slam / glaive radial damage: the weapon's physical base becomes one
        # type; elemental mod damage stays (wiki: radial scales with mods).
        moved = sum(damage.pop(k, 0.0) for k in _PHYSICAL)
        damage[target] = damage.get(target, 0.0) + moved
    crit_chance, crit_multiplier = stats.crit_chance, stats.crit_multiplier
    base_chance, base_multiplier = melee_crit
    if hit.get("critChance") is not None and base_chance:
        crit_chance *= float(hit["critChance"]) / float(base_chance)
    if hit.get("critMultiplier") is not None and base_multiplier:
        crit_multiplier *= float(hit["critMultiplier"]) / float(base_multiplier)
    if not hit.get("canCrit", True):
        crit_chance = 0.0
    forced = dict(stats.native_forced_procs or {})
    for proc in hit.get("extraProcs") or ():
        dtype = _PROC_TYPES.get(proc)
        if dtype:
            forced[dtype] = forced.get(dtype, 0.0) + 1.0
    return replace(
        stats,
        damage_types=damage,
        dot_base_damage=stats.dot_base_damage * factor if stats.dot_base_damage is not None else None,
        crit_chance=crit_chance,
        crit_multiplier=crit_multiplier,
        status_chance=stats.status_chance * float(hit.get("procAtten", 1.0)),
        native_forced_procs=forced,
        multishot=1.0,
        radial_only=bool(hit.get("radial")),
    )


_COMBO_NAMES = {"CC_GROUND": "中立", "CC_GROUND_BRANCH_A": "前进", "CC_GROUND_BRANCH_B": "前进格挡",
                "CC_GROUND_BRANCH_C": "格挡"}


def route_note(schedule: Mapping[str, Any], stance_name: str | None = None) -> str:
    """The calculation note line for the route actually replayed."""
    route = schedule.get("route")
    hits = [s["hit"] for s in schedule.get("segments") or () if s.get("hit")]
    seconds = sum(s["fixed"] + s["anim"] for s in schedule.get("segments") or ())
    if route == "combo":
        stance = stance_name or str(schedule.get("stance") or "").rsplit("/", 1)[-1] or "无架势"
        return (f"攻击路线：轻击连段（{stance} · {_COMBO_NAMES.get(schedule.get('combo'), schedule.get('combo'))}连段，"
                f"{len(hits)} 击 / 总倍率 {sum(h['atten'] for h in hits):g}，1.0 攻速下 {seconds:.2f} 秒一轮）；"
                "逐次命中，连击数从初始连击逐击累加，嗜血类效果按实时档位")
    if route in ("slam", "slamBullet"):
        direct, radial = hits[0], hits[1]
        jump = "原地跳到最高点" if route == "slam" else "垂直子弹跳"
        kind = "重击震地" if direct.get("heavy") else "震地"
        return (f"攻击路线：{kind}（{jump}，{schedule.get('slamHeight', 0):g} 米，1.0 攻速下 {seconds:.2f} 秒一轮）；"
                f"直击 ×{direct['atten']:g} + 范围 ×{radial['atten']:g}（{radial.get('damageType')}，不暴击，靶在中心）"
                + ("，重击按初始连击倍率" if direct.get("heavy") else ""))
    if route == "glaive":
        return (f"攻击路线：蓄力重投 + 立即引爆（1.0 攻速下 {seconds:.2f} 秒一轮）；投掷直击 ×{hits[0]['atten']:.2f} + "
                f"爆炸 ×{hits[1]['atten']:.2f}（爆炸按初始连击倍率）")
    return "攻击路线：" + str(route)
