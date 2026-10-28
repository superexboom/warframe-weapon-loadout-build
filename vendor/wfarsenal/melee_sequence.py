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
import struct
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .record_keys import pin, record_key

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


def _damaging_slam(slam: Mapping[str, Any] | None) -> bool:
    """A Slams[] entry that reaches a body: fist / sparring punch and kick
    effects, shield-bash and glaive-catch effects have a 0 m radius."""
    if slam is None or slam.get("event") in _COSMETIC_SLAMS:
        return False
    radius = slam.get("radius")
    return radius is None or float(radius) > 0


def attack_hits(attack: Mapping[str, Any], slams: Mapping[str, Mapping[str, Any]] | None = None) -> list[dict[str, Any]]:
    """One row per landed hit, in time order.

    Sweep hits carry the attack's (or the per-swing override's) properties. An
    animation event that matches one of the weapon's Slams[] triggers adds a
    radial hit with that slam's attenuation (``kind == 'slam'``). An attack
    with no sweep event lands one hit at mid-animation: a gunblade shot is the
    attack's hit plus the shot's blast (the wiki's stance totals count both).
    """
    events = list(attack.get("hits") or ())
    swings = list(attack.get("swings") or ())
    slam_events = [e for e in attack.get("events") or () if _damaging_slam((slams or {}).get(e.get("event")))]
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
    for event in slam_events:
        slam = slams[event["event"]]
        rows.append(dict(
            kind="slam", slam=event.get("event"), t=float(event.get("t") or 0.0),
            atten=float(slam.get("attenuation") or 1.0), procAtten=1.0,
            extraProcs=list(slam.get("forcedProcs") or ()), comboHits=1.0, damagePct={},
        ))
    rows.sort(key=lambda row: row["t"])
    return rows


def weapon_row(weapon: Mapping[str, Any]) -> dict[str, Any] | None:
    """The weapon's melee-mechanics row. An assembled Zaw takes its melee tree
    and Slams[] from its strike's one- or two-handed block; a hybrid's form
    (Dark Split-Sword) reads its own entity (``meleePath``)."""
    ref = reference()
    row = (ref.get("weapons") or {}).get(str(weapon.get("meleePath") or weapon.get("path") or ""))
    strike = weapon.get("zawStrike")
    if row and strike:
        hand = ((ref.get("zaws") or {}).get(str(strike)) or {}).get(str(weapon.get("zawHanded") or ""))
        if hand:
            row = dict(row, tree=hand.get("tree"), slams=list(hand.get("slams") or ()))
    return row


# -- Attack routes ------------------------------------------------------------
#
# A route is a loop of segments: ``fixed`` seconds (movement, wind-up, flight;
# attack speed does not shorten them) plus ``anim`` seconds at 1.0 attack speed,
# then optionally one hit. The replay lands a hit, then waits the segments up
# to the next hit.

ROUTES = ("combo", "slam", "slamBullet", "slamContinuous", "glaive")
# User-specified cancel cadence, not a recovered animation duration.
CONTINUOUS_SLAM_INTERVAL = 0.2
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


def is_hammer(weapon: Mapping[str, Any]) -> bool:
    tags = {str(t).upper() for t in weapon.get("compatTags") or ()}
    return ("HAMMERS_STANCE" in tags or
            str((weapon_row(weapon) or {}).get("tree", "")).endswith("/HammerMeleeTree"))


def default_route(weapon: Mapping[str, Any]) -> str:
    """Bot policy: hammers slam from a vertical bullet jump, glaives heavy-throw and
    detonate, others combo."""
    tags = {str(t).upper() for t in weapon.get("compatTags") or ()}
    row = weapon_row(weapon) or {}
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


# Schedules by weapon record and route arguments. A schedule depends on them and
# the reference tables only, and every prepare of a melee loadout asks for it
# (0.4 ms, a tenth of a melee bake); callers only read it. Entries pin the
# record's values (record_keys).
_SCHEDULES: dict = {}
_SCHEDULES_MAX = 256


def build_schedule(weapon: Mapping[str, Any], route: str | None = None, *, stance: str | None = None,
                   combo: str | None = None, target_distance: float | None = None) -> dict[str, Any] | None:
    """The hit loop of one melee route, or None when the weapon has no data."""
    key = (record_key(weapon), route, stance, combo, repr(target_distance))
    hit = _SCHEDULES.get(key)
    if hit is not None:
        return hit[1]
    schedule = _build_schedule(weapon, route, stance=stance, combo=combo, target_distance=target_distance)
    if len(_SCHEDULES) >= _SCHEDULES_MAX:
        _SCHEDULES.clear()
    _SCHEDULES[key] = (pin(weapon), schedule)
    return schedule


def _build_schedule(weapon, route, *, stance, combo, target_distance):
    ref = reference()
    row = weapon_row(weapon)
    if not row:
        return None
    if weapon.get("exaltedCast"):
        # Whipclaw / Shattered Lash / Landslide / Blade Storm: the melee tree is
        # a placeholder; one cast is one hit (exalted.cast_schedule).
        from .exalted import cast_schedule
        melee_damage = row.get("damage") or {}
        schedule = cast_schedule(weapon, row.get("combo") or {})
        if schedule:
            return dict(schedule, stance=None, notes=["exalted-cast-loop"], comboSpec=row.get("combo") or {},
                        meleeCrit=(melee_damage.get("crit"), melee_damage.get("critMultiplier")))
    route = route or default_route(weapon)
    if route == "slamContinuous" and not is_hammer(weapon):
        raise ValueError("continuous slam requires a hammer weapon")
    attacks = ref.get("attacks") or {}
    slams = {s["event"]: s for s in row.get("slams") or () if s.get("event")}
    notes: list[str] = []
    if (row.get('combo') or {}).get('recoveryPerSecond') is None:
        notes.append('melee-initial-combo-recovery-rate-unverified')
    notes.append('melee-combo-recovery-event-integration-and-impact-consumption')
    melee_damage = row.get("damage") or {}
    melee_amount = float(melee_damage.get("amount") or 0.0)
    if route == "glaive" and not row.get("glaive"):
        notes.append("melee-route-glaive-unavailable-using-combo")
        route = "combo"
    if route in ("slam", "slamBullet", "slamContinuous") and not (slams.get("HeavySlam") or slams.get("MeleeSlam")):
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
    if route in ("slam", "slamBullet", "slamContinuous"):
        heavy = slams.get("HeavySlam")
        slam = heavy or slams["MeleeSlam"]
        direct_path = row.get("heavySlamAttack") if heavy else row.get("slamAttack")
        direct = float((attacks.get(direct_path) or {}).get("atten") or (3.0 if heavy else 2.0))
        aerial = (tree or {}).get("aerial") or {}
        strike = attacks.get(aerial.get("BP_CROUCH") or "") or {}
        strike_seconds = float(strike.get("duration") or 1.0) * (_wait_fraction(strike) or 1.0)
        if route == "slamContinuous":
            # The requested minimum-height cancel loop pays one fixed period
            # between impacts. Attack-speed MODs do not shorten this contract.
            rise, fall, height = CONTINUOUS_SLAM_INTERVAL, 0.0, 0.0
            strike_seconds = 0.0
            notes.append("continuous-slam-user-cadence-0.2s-minimum-height-no-recovery")
        else:
            rise, fall, height = jump_times(route)
        if route != "slamContinuous":
            notes.append(f"slam-cycle: rise {rise:.2f}s + free-fall {fall:.2f}s from {height:g} m (plunge speed not in data)")
        # One area strike, the slam attack's own DamageAtten (SlamAoE 2,
        # HeavySlamAoE 3: wiki Melee "Slam attacks deal 2x weapon damage (3x
        # for Heavy Slams)", Arca Titron's heavy slam 1,080 = 3 x 360) in the
        # Slams[] row's element and procs, the target at its centre. The row's
        # own BaseDamageAttenuation (HeavySlam 3.5-5 by class) matches no
        # published figure and is not applied. It crits: weapon pages list a
        # heavy slam crit chance. A heavy slam spends the counter it reads.
        segments = [
            dict(fixed=rise + fall, anim=0.0, hit=dict(
                kind="slam", t=0.0, atten=direct, procAtten=1.0, extraProcs=list(slam.get("forcedProcs") or ()),
                comboHits=0.0 if heavy else 1.0, damagePct={}, canCrit=True, radial=True, slam=True,
                heavy=bool(heavy), damageType=slam.get("damageType"), comboMultiplier=bool(heavy),
                consumesCombo=bool(heavy), slamStart=True, slamEnd=True)),
            dict(fixed=0.0, anim=strike_seconds, hit=None),
        ]
        return dict(common, route=route, segments=segments, label="heavy-slam" if heavy else "slam",
                    slamHeight=height)
    glaive = row["glaive"]
    proj = glaive.get("turbo") or glaive.get("projectile")
    # The charged throw winds up for the glaive's ChargeDuration (1.2 s, the
    # wiki's heavy wind-up); HeavyMeleeChargeTime belongs to a stance heavy
    # glaives do not have (HasHeavyAttack 0). Wind-up cards shorten it.
    charge_duration = (row.get("heavy") or {}).get("chargeDuration")
    if charge_duration:
        charge, guessed = float(charge_duration), False
    else:
        charge, guessed = class_charge_time(ref, row)
    if guessed:
        notes.append("heavy-wind-up-from-class")
    distance = GLAIVE_DEFAULT_DISTANCE if target_distance is None else float(target_distance)
    flight = distance / float(proj.get("speed") or 55.0)
    heavy_set = (tree or {}).get("contexts", {}).get("CC_GROUND_HEAVY") or ()
    throw = attacks.get(heavy_set[0]) if heavy_set else None
    throw_seconds = float((throw or {}).get("duration") or 0.7)
    scale = float(proj.get("amount") or 0.0) / melee_amount if melee_amount else 1.0
    blast = float(proj.get("explosion") or 0.0)
    explosion = blast * float(proj.get("heavyRecallAtten") or 1.0)
    notes.append(f"glaive-cycle: wind-up {charge:g}s + throw {throw_seconds:.2f}s + flight {flight:.2f}s ({distance:g} m)")
    melee_proc = float(melee_damage.get("procChance") or 0.0)

    def proc_atten(chance):
        return float(chance or 0.0) / melee_proc if melee_proc else 1.0

    base = dict(critChance=proj.get("crit"), critMultiplier=proj.get("critMultiplier"), damagePct={},
                projectile=True)
    blast_proc = proc_atten(proj.get("explosionProcChance", proj.get("procChance")))
    segments = [
        dict(fixed=charge, anim=throw_seconds, hit=None, chargeScaled=True),
        # The strike is not a heavy attack: a combo point and Condition
        # Overload, no counter, no heavy-attack card (wiki Killing Blow:
        # "does not increase the thrown weapon's own damage"); Power Throw's
        # consecutive-throw damage is its alone. Whirlwind shortens the flight.
        dict(fixed=flight, anim=0.0, flightScaled=True, hit=dict(
            base, kind="glaiveDirect", t=0.0, atten=scale, canCrit=True, comboHits=1.0,
            procAtten=proc_atten(proj.get("procChance")),
            extraProcs=list(proj.get("forcedProcs") or ()), comboMultiplier=False, heavy=False, throw=True)),
        # Volatile Rebound / Quick Return: the bounce off the struck body sets
        # off the projectile's own explosion, half the detonation (wiki: "50%
        # of Heavy Attack damage"), at the build's chance; no counter, no
        # heavy-attack card, no forced procs. The detonation still follows.
        dict(fixed=0.0, anim=0.0, hit=dict(
            base, kind="glaiveBounce", t=0.0, atten=blast / melee_amount if melee_amount else 1.0,
            canCrit=True, radial=True, damageType="DT_EXPLOSION", comboHits=0.0, procAtten=blast_proc,
            extraProcs=[], comboMultiplier=False, heavy=False, bounce=True, noConditionOverload=True)),
        # The detonation is a heavy attack: it reads the counter and spends
        # it; Condition Overload does not reach it (wiki, Glaive Prime).
        dict(fixed=0.0, anim=0.0, hit=dict(
            base, kind="glaiveExplosion", t=0.0, atten=explosion / melee_amount if melee_amount else 1.0,
            canCrit=True, radial=True, damageType="DT_EXPLOSION", comboHits=0.0, procAtten=blast_proc,
            extraProcs=list(proj.get("heavyRecallProcs") or ()), comboMultiplier=True, heavy=True,
            consumesCombo=True, noConditionOverload=True)),
    ]
    return dict(common, route="glaive", segments=segments, label="heavy-throw-detonate")


def initial_combo_floor(initial: float, cap: float = 220.0) -> float:
    # Native upgrade result converts from float32 to unsigned integer by truncation.
    return float(min(math.floor(_float32(max(0.0, initial))), cap))


def recover_initial_combo(count: float, initial: float, elapsed: float, rate: float) -> float:
    """Native update tail: fractional linear recovery to the initial floor.

    Packages supply the per-weapon rate; the consumer has no post-heavy delay.
    Integrate elapsed time without inventing a frame rate for the event replay.
    """
    initial = max(0.0, float(initial))
    if count >= initial:
        return count
    return min(initial, count + max(0.0, elapsed) * max(0.0, rate))


def _float32(value: float) -> float:
    return struct.unpack('<f', struct.pack('<f', value))[0]


def combo_counter(count: float) -> int:
    return math.floor(_float32(_float32(max(0.0,count)) + 0.5))


def consume_combo(count: float, efficiency: float) -> float:
    """Heavy attack spends integer points; zero efficiency clears the fraction.

    0x1416b81d0 -> getter floor(C+0.5), floor(rounded*(1-eff)) -> subtract.
    It never clamps the remainder to InitialHitCounter.
    """
    retained = _float32(min(max(float(efficiency), 0.0), 0.9))
    cost = _float32(1.0-retained)
    if cost >= 1.0:
        return 0.0
    spent = math.floor(_float32(combo_counter(count) * cost))
    return max(0.0, _float32(_float32(count)-spent))


def combo_multiplier(spec: Mapping[str, Any], count: float) -> float:
    """1x below the first tier, then +1x per tier (wiki: 2x to 12x)."""
    first = float(spec.get("baseHits") or 20.0)
    step = float(spec.get("tierStep") or first)
    cap = float(spec.get("cap") or 220.0)
    count = min(combo_counter(float(count)), cap)
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

    def next(self, attack_speed: float, charge_speed: float = 1.0,
             projectile_speed: float = 1.0) -> tuple[dict[str, Any], float]:
        waited = 0.0
        for _ in range(len(self.segments) + 1):
            segment = self.segments[self.index]
            self.index = (self.index + 1) % len(self.segments)
            fixed = segment["fixed"] / charge_speed if segment.get("chargeScaled") else segment["fixed"]
            if segment.get("flightScaled"):
                fixed = segment["fixed"] / max(projectile_speed, 1e-9)
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
    throw_bonus = float(getattr(stats, "throw_damage_bonus", 0.0) or 0.0)
    if hit.get("throw") and throw_bonus:
        # Power Throw: weapon damage on the throw alone, in the base bracket
        # beside the other weapon-damage terms (wiki: multiplicative to
        # Pressure Point, additive with universal weapon bonuses).
        factor *= 1.0 + throw_bonus / (float(getattr(stats, "base_damage_bracket", 1.0)) or 1.0)
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
        # A Volatile bounce explosion lands at the build's bounce chance.
        multishot=(min(1.0, max(0.0, float(getattr(stats, "reflection_explosion_chance", 0.0))))
                   if hit.get("bounce") else 1.0),
        radial_only=bool(hit.get("radial")),
    )


_DAMAGE_NAMES = {"DT_IMPACT": "冲击", "DT_PUNCTURE": "穿刺", "DT_SLASH": "切割", "DT_FIRE": "火焰",
                 "DT_FREEZE": "冰冻", "DT_ELECTRICITY": "电击", "DT_POISON": "毒素", "DT_EXPLOSION": "爆炸",
                 "DT_RADIATION": "辐射", "DT_GAS": "毒气", "DT_MAGNETIC": "磁力", "DT_VIRAL": "病毒",
                 "DT_CORROSIVE": "腐蚀", "DT_RADIANT": "虚空"}
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
    if route in ("slam", "slamBullet", "slamContinuous"):
        slam = hits[0]
        if route == "slamContinuous":
            return (f"攻击路线：连续震地（最低跳跃高度、取消后摇，按 {CONTINUOUS_SLAM_INTERVAL:g} 秒一次）；"
                    f"一次范围打击 ×{slam['atten']:g}（靶在最小范围中心），每击使用当时已恢复的连击并消耗；"
                    "频率采用用户给定操作条件，不受攻击速度缩短")
        jump = "原地跳到最高点" if route == "slam" else "垂直子弹跳"
        kind = "重击震地" if slam.get("heavy") else "震地"
        return (f"攻击路线：{kind}（{jump}，{schedule.get('slamHeight', 0):g} 米，1.0 攻速下 {seconds:.2f} 秒一轮）；"
                f"一次范围打击 ×{slam['atten']:g}（{_DAMAGE_NAMES.get(slam.get('damageType'), slam.get('damageType'))}，可暴击，靶在中心）"
                + ("，按攻击时的连击倍率并消耗连击" if slam.get("heavy") else ""))
    if route == "glaive":
        by_kind = {h["kind"]: h for h in hits}
        return (f"攻击路线：蓄力重投 + 立即引爆（1.0 攻速下 {seconds:.2f} 秒一轮）；投掷直击 ×{by_kind['glaiveDirect']['atten']:.2f} + "
                f"引爆 ×{by_kind['glaiveExplosion']['atten']:.2f}（重击，按攻击时的连击倍率并消耗连击，不吃异况超量）"
                f"；易爆弹跳 / 易爆速返的弹跳爆炸 ×{by_kind['glaiveBounce']['atten']:.2f} 按弹跳爆炸几率")
    return "攻击路线：" + str(route)
