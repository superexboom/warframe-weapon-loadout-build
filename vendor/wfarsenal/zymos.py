"""Zymos retained upgrade buckets and explicitly selected guided-contact packets.

Evidence: docs/ranged-implementation-20261030/evidence/zymos-fresh-create-order.md
and .local/delivery/projectile-qualification-20261030/zymos-completion/NOTES.md.
This adapter accepts ordinary enabled registration and a surviving original host.
Trajectory success and temporary source fields are inputs, never inferred from DPS.
"""
from __future__ import annotations

import math
import struct
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from .damage import (ModEffect, ModdedStats, Scenario, _qualifier_rejection,
                     apply_mods_spec)

PREFIX = "/Lotus/Weapons/Infested/Pistols/InfUzi/"
WEAPON = PREFIX + "InfUziWeapon"
PROJECTILE = PREFIX + "InfUziProjectile"
CARRIER = PREFIX + "EmbedDeathKillClusterProj"
CHILD = PREFIX + "EmbedDeathKillGuidedProj"
POLICY = "surviving-original-victim-contact"
ENERVATE = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryCritOnHit"
CRIT_TYPES = frozenset({"WEAPON_CRIT_CHANCE", "WEAPON_CRIT_DAMAGE"})


def _f32(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Zymos source values must be finite")
    return struct.unpack("<f", struct.pack("<f", value))[0]


@dataclass(frozen=True)
class UpgradeValue:
    """Native FloatUpgradedValue buckets; ADD precedes MULTIPLY in its getter."""
    base: float
    add_base: float = 0.
    stacking: float = 0.
    add: float = 0.
    multiply: float = 1.
    set_value: float | None = None
    set_base: float | None = None
    minimum: float | None = None
    maximum: float | None = None

    def query(self, effects: Iterable[ModEffect]) -> "UpgradeValue":
        value = self
        for effect in effects:
            amount, op = _f32(effect.value), effect.operation
            if op == "ADD":
                value = replace(value, add=_f32(value.add + amount))
            elif op == "ADD_BASE":
                value = replace(value, add_base=_f32(value.add_base + amount))
            elif op == "STACKING_MULTIPLY":
                value = replace(value, stacking=_f32(value.stacking + amount))
            elif op == "MULTIPLY":
                value = replace(value, multiply=_f32(value.multiply * amount))
            elif op == "SET":
                value = replace(value, set_value=amount)
            elif op == "SET_BASE":
                value = replace(value, set_base=amount)
            elif op == "MAX":
                value = replace(value, minimum=max(value.minimum if value.minimum is not None else amount, amount))
            elif op == "MIN":
                value = replace(value, maximum=min(value.maximum if value.maximum is not None else amount, amount))
            else:
                raise ValueError(f"Zymos native upgrade operation is unsupported: {op}")
        return value

    def flat(self, amount: float) -> "UpgradeValue":
        return replace(self, add=_f32(self.add + _f32(amount)))

    def get(self) -> float:
        if self.set_value is not None:
            return self.set_value
        base = self.base if self.set_base is None else self.set_base
        value = _f32(_f32(_f32(base + self.add_base) * _f32(1. + self.stacking)) + self.add)
        value = _f32(value * self.multiply)
        if self.minimum is not None:
            value = max(value, self.minimum)
        if self.maximum is not None:
            value = min(value, self.maximum)
        return value


@dataclass(frozen=True)
class SourceContext:
    """Actual ordered +df4 additions, final +ff8 and source damage-query scale.

    Creator context refreshes may add F repeatedly even for the same source.
    Supply only updates surviving the carrier-to-child copy. Child pre-copy
    updates are discarded. A fixed-source context explicitly rules out external
    temporary flat critical buffs; it does not identify Enervate with F or G.
    """
    creator_flat_updates: tuple[float, ...]
    packet_flat_crit: float
    damage_query_scale: float
    label: str
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.label:
            raise ValueError("Zymos source context requires provenance/scope")
        for value in (*self.creator_flat_updates, self.packet_flat_crit, self.damage_query_scale):
            _f32(value)
        if self.damage_query_scale < 0:
            raise ValueError("Zymos damage query scale must be nonnegative")

    @classmethod
    def ordinary_static(cls, *, enervate_active: bool = False,
                        enervate_snapshotted: bool = False) -> "SourceContext":
        # CritOnHit.lua installs enum244 ADD into the ordinary source manager.
        # Its state must therefore appear in the effects at each query time.
        diagnostics = (("zymos-child-enervate-query-snapshot-required",)
                       if enervate_active and not enervate_snapshotted else ())
        return cls((0.,), 0., 1., "ordinary-static-no-external-temporary-flat-crit", diagnostics)


@dataclass(frozen=True)
class ContactPolicy:
    """One stored embed record, original surviving victim, successful contact."""
    arrival_seconds: float
    contacts: int
    name: str = POLICY

    def __post_init__(self):
        if self.name != POLICY:
            raise ValueError("Zymos requires the explicit surviving-original-victim-contact policy")
        if not math.isfinite(self.arrival_seconds) or self.arrival_seconds < 0:
            raise ValueError("Zymos contact arrival must be finite and nonnegative")
        if type(self.contacts) is not int or not 0 <= self.contacts <= 5:
            raise ValueError("Zymos accepted contacts must be an integer from zero to five")

    @classmethod
    def from_state(cls, state: Mapping) -> "ContactPolicy | None":
        overlap = state.get("zymosChildOverlap")
        if overlap in (None, "off"):
            return None
        if overlap != "ideal-contact":
            raise ValueError("Zymos currently supports the explicit ideal-contact body policy")
        if "zymosChildArrivalSeconds" not in state:
            raise ValueError("Zymos contact policy requires zymosChildArrivalSeconds")
        return cls(float(state["zymosChildArrivalSeconds"]), state.get("zymosChildContacts", 5))


@dataclass(frozen=True)
class FireCount:
    count: int
    weight: float


def fire_count_distribution(effective_count: float, *, cached_count: int | None = None,
                            ignored_raw_count: int | None = None) -> tuple[FireCount, ...]:
    """140358430 raw/cached count, or a new floor+Bernoulli current query.

    This is the callback's count, not the parent projectile multiplicity. Pass a
    conditional cached count to retain correlation with an already sampled shot.
    """
    fixed = ignored_raw_count if ignored_raw_count is not None else cached_count
    if fixed is not None:
        if type(fixed) is not int or fixed < 0:
            raise ValueError("Zymos cached/raw fire count must be a nonnegative integer")
        return (FireCount(fixed, 1.),)
    amount = _f32(effective_count)
    if amount < 0:
        raise ValueError("Zymos effective fire count must be nonnegative")
    low = math.floor(amount)
    remainder = amount - low
    return ((FireCount(low, 1. - remainder), FireCount(low + 1, remainder))
            if remainder else (FireCount(low, 1.),))


def _eligible(weapon: Mapping, effects: Iterable[ModEffect], scenario: Scenario) -> tuple[ModEffect, ...]:
    types = {str(p).rstrip("/") for p in (*weapon.get("ancestry", ()), weapon.get("path")) if p}
    result = []
    for effect in effects:
        if effect.valid_type and effect.valid_type.rstrip("/") not in types:
            continue
        # Match the main resolver's qualifier/unsupported filtering. An
        # unrelated unsupported MOD term must not abort a valid parent build.
        if not effect.supported or _qualifier_rejection(effect, weapon, scenario):
            continue
        if effect.upgrade_type == 'RUNTIME_NEXT_SHOT_DAMAGE':
            continue  # Longbow Sharpshot cannot be equipped on this secondary.
        result.append(effect)
    return tuple(result)


@dataclass(frozen=True)
class CarrierSnapshot:
    crit_chance: UpgradeValue
    crit_damage: UpgradeValue
    # Integer B for each conditional callback count; never truncate the mean.
    contact_amounts: tuple[tuple[int, float], ...]
    diagnostics: tuple[str, ...]


def carrier_snapshot(weapon: Mapping, effects: Iterable[ModEffect], *, context: SourceContext,
                     callback_counts: tuple[FireCount, ...], scenario: Scenario | None = None) -> CarrierSnapshot:
    """Take source queries at Lua carrier creation, after ordinary registration."""
    if weapon.get("path") != WEAPON:
        raise ValueError("Zymos source weapon identity changed")
    scenario = scenario or Scenario()
    eligible = _eligible(weapon, effects, scenario)
    cc = UpgradeValue(_f32(.050000001)).query(e for e in eligible if e.upgrade_type == "WEAPON_CRIT_CHANCE")
    cd = UpgradeValue(_f32(2.3)).query(e for e in eligible if e.upgrade_type == "WEAPON_CRIT_DAMAGE")
    for amount in context.creator_flat_updates:
        cc = cc.flat(amount)
    base = UpgradeValue(23.).query(e for e in eligible if e.upgrade_type == "WEAPON_DAMAGE_AMOUNT").get()
    base = _f32(base * _f32(context.damage_query_scale))
    if not callback_counts or abs(sum(c.weight for c in callback_counts) - 1.) > 1e-6:
        raise ValueError("Zymos callback fire-count weights must sum to one")
    amounts = []
    for count in callback_counts:
        if type(count.count) is not int or count.count < 0 or not math.isfinite(count.weight) or count.weight < 0:
            raise ValueError("Zymos callback fire-count cohort is invalid")
        raw = _f32(base * count.count)
        # Native +648 itself can return a negative damage query. A negative
        # copied amount cannot contribute positive outgoing damage; keep the
        # independently positive 333 packet available for such Riven builds.
        amounts.append((max(0, math.trunc(raw)), count.weight))
    return CarrierSnapshot(cc, cd, tuple(amounts), context.diagnostics)


@dataclass(frozen=True)
class ChildPackets:
    weight: float
    contact: ModdedStats
    explosion: ModdedStats
    contacts: int
    arrival_seconds: float
    diagnostics: tuple[str, ...]


def child_packets(snapshot: CarrierSnapshot, weapon: Mapping, effects: Iterable[ModEffect], *,
                  context: SourceContext, policy: ContactPolicy,
                  scenario: Scenario | None = None) -> tuple[ChildPackets, ...]:
    """Materialize ordered contact B then explicit-victim 333 packets per child.

    Replay must preserve victim generation and stop this sequence if its host
    dies. Apply parent multiplicity once outside this conditional cohort. The
    returned stats already have their own source crit/element/faction stages;
    do not mod them again or multiply 333 by the parent's damage bracket.
    """
    if weapon.get("path") != WEAPON:
        raise ValueError("Zymos source weapon identity changed")
    scenario = scenario or Scenario()
    eligible = _eligible(weapon, effects, scenario)
    cc = snapshot.crit_chance.query(e for e in eligible if e.upgrade_type == "WEAPON_CRIT_CHANCE")
    cd = snapshot.crit_damage.query(e for e in eligible if e.upgrade_type == "WEAPON_CRIT_DAMAGE")
    for amount in context.creator_flat_updates:
        cc = cc.flat(amount)
    # 140ede780 merges the existing plan's flat chance after retained copy.
    cc = cc.flat(context.packet_flat_crit)
    diagnostics = tuple(dict.fromkeys((*snapshot.diagnostics, *context.diagnostics)))
    if diagnostics:
        raise ValueError("Zymos source context is not admitted: " + ",".join(diagnostics))
    remaining = tuple(e for e in eligible if e.upgrade_type not in CRIT_TYPES | {
        "WEAPON_DAMAGE_AMOUNT", "WEAPON_FIRE_ITERATIONS"})

    def packet(amount: float, explosion: bool) -> ModdedStats:
        mode = deepcopy(weapon["fireModes"][0])
        mode.update(multishot=1., __radialPart__=True, falloffRange=[0., 0.], falloffMinDamage=1.)
        vector = {"DT_POISON": amount} if explosion else {"DT_PUNCTURE": amount * .5, "DT_SLASH": amount * .5}
        mode["damage"] = {**mode["damage"], "types": vector, "total": amount,
            "shares": {k: v / amount for k, v in vector.items()} if amount else {},
            "source": "ExplosiveAttack" if explosion else "AttackData", "projectile": CHILD,
            "critChance": .05, "critMultiplier": 2.3, "procChance": .30000001 if explosion else 0.,
            "forcedProcs": [] if explosion else ["PT_KNOCKBACK"]}
        record = {**weapon, "fireModes": [mode], "__innateResolved__": True,
                  "__coProfile__": {"behavior": "none"} if explosion else
                      {"behavior": "additive_with_base_damage", "baseFraction": 1., "excludeFlatSources": []}}
        fx = tuple(e for e in remaining if not explosion or e.upgrade_type not in {"WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE", "RUNTIME_COLD_STACK_DAMAGE"})
        forced=max((float(e.runtime_chance or 0.) for e in fx if e.upgrade_type=='RUNTIME_COLD_STACK_DAMAGE'),default=0.) or None
        fx=tuple(replace(e,runtime_chance=0.) if e.upgrade_type=='RUNTIME_COLD_STACK_DAMAGE' else e for e in fx)
        stats, spec = apply_mods_spec(record, fx, scenario=replace(scenario, incarnon_cycle=False))
        stats = replace(stats, crit_chance=cc.get(), crit_multiplier=cd.get()+sum(e.value for e in eligible if e.upgrade_type=="RUNTIME_FINAL_CRIT_DAMAGE"), base_crit_chance=.05,
                        multishot=1., radial_only=True, radial_victim_crit=explosion,
                        weakpoint_damage_bonus=0., weakpoint_crit_chance_bonus=0.,
                        weakpoint_crit_chance_relative=0., headshot_bonus_multiplier=1.,
                        delayed_radial_hit_event=True)
        stats._co_spec = spec
        stats._contact_shiver = not explosion
        stats._contact_shiver_fixed=forced
        stats._zymos_source = (CHILD, "ExplosiveAttack" if explosion else "AttackData")
        return stats

    explosion = packet(333., True)
    return tuple(ChildPackets(weight, packet(amount, False), explosion, policy.contacts,
                              policy.arrival_seconds, diagnostics)
                 for amount, weight in snapshot.contact_amounts if weight > 0.)
