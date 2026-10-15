"""Shared loadout event scoring for optimizer candidates and final checks."""
from __future__ import annotations
import hashlib
import json
import math
import pickle
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace


class ResolveCache(dict):
    """Resolved stats of one loadout, shared by its replays; never pickled."""

    def __reduce__(self):
        return (ResolveCache, ())


def bind(stats, weapon, cards, effects, scenario, passives):
    modes = weapon.get("__baseFireModes__") or weapon.get("fireModes") or []
    selected = int(weapon.get("__selectedFireMode__", 0))
    full_weapon = {**weapon, "fireModes": modes}
    stats._combat_inputs = {
        "cards": tuple(cards),
        "engine": dict(weapon=full_weapon, effects=effects, scenario=scenario, fire_mode=selected),
        "mods": [(c.record, c.rank, None) for c in cards if c.record and c.record.get("path")],
        "arcanes": list(passives.event_arcanes) if passives else [],
        "choices": dict(passives.incarnon_choices) if passives else {},
    }
    stats._combat_scores = {}
    stats._resolve_cache = ResolveCache()


# Replays of identical loadouts in identical contexts, across stats objects
# (the same build is re-derived by every analysis of one weapon).
_REPLAYS = OrderedDict()
_REPLAYS_MAX = 4096
_UNHASHED = {"_combat_inputs", "_combat_scores", "_resolve_cache"}


# Content digests of weapon and MOD records, by record_keys.record_key:
# bind() copies a weapon as {**weapon, "fireModes": ...} for every loadout and
# the values are shared. Entries pin the values, so the ids stay valid.
_RECORD_DIGESTS: dict = {}


def _record_digest(record):
    from .record_keys import pin, record_key
    key = record_key(record)
    hit = _RECORD_DIGESTS.get(key)
    if hit is not None:
        return hit[1]
    digest = hashlib.blake2b(pickle.dumps(record, protocol=5), digest_size=20).digest()
    if len(_RECORD_DIGESTS) >= 4096:
        _RECORD_DIGESTS.clear()
    _RECORD_DIGESTS[key] = (pin(record), digest)
    return digest


def _replay_key(stats, data, context_key):
    """Digest of everything a window replay reads; equal digests, equal replays."""
    fields = stats.__dataclass_fields__
    extras = sorted((k, repr(v)) for k, v in vars(stats).items() if k not in fields and k not in _UNHASHED)
    engine = data["engine"]
    engine_key = (_record_digest(engine["weapon"]), engine["effects"], engine["scenario"], engine["fire_mode"])
    mods = [(_record_digest(record), rank, extra) for record, rank, extra in data["mods"]]
    blob = pickle.dumps((repr(stats), extras, engine_key, mods, data["arcanes"],
                         data["choices"], context_key), protocol=5)
    return hashlib.blake2b(blob, digest_size=20).digest()


def window(stats, context):
    from .manual_combat import prepare
    from .combat_replay import replay
    data = stats._combat_inputs
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    cache = stats._combat_scores
    if key in cache:
        return cache[key]
    shared = _replay_key(stats, data, key)
    result = _REPLAYS.get(shared)
    if result is not None:
        # Concurrent searches of one request share this cache (loadout_search).
        try:
            _REPLAYS.move_to_end(shared)
        except KeyError:
            pass
        for reason in result.get("unsupported") or []:
            if reason not in stats.unsupported:
                stats.unsupported.append(reason)
        cache[key] = result
        return result
    target = context.get("target") or {}
    scenario = data["engine"]["scenario"]
    enhancements = context.get("enemy_enhancements") or {}
    combat = prepare(
        data["engine"], data["mods"], data["arcanes"],
        cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == "assumed_max",
        incarnon_choices=data["choices"], affinity_target=target, level=context.get("level"),
        eximus=bool(enhancements.get("eximus")), resolve_cache=getattr(stats, "_resolve_cache", None),
    )
    result = replay(
        stats, target, combat=combat, trigger_sources=combat["trigger_sources"],
        attacks_per_second=stats.sustained_attack_rate,
        window_seconds=float(context.get("windowSeconds") or 30.0),
        headshot_chance=float(context.get("headshotChance", 1.0 if context.get("hit_location") == "head" else 0.0)),
        status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
        damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
        level=context.get("level"), armour_strip=float(context.get("armour_strip") or 0.0),
        elemental_armour_strip=float(context.get("elemental_armour_strip") or 0.0),
        steel_path=bool(context.get("steel_path")), enemy_enhancements=enhancements,
        forced_procs=context.get("forcedProcs"),
        kill_branches=context.get("killBranches"),
        collect_timeline=False,
    )
    for reason in result.get("unsupported") or []:
        if reason not in stats.unsupported:
            stats.unsupported.append(reason)
    cache[key] = result
    _REPLAYS[shared] = result
    while len(_REPLAYS) > _REPLAYS_MAX:
        try:
            _REPLAYS.popitem(last=False)
        except KeyError:
            break
    return result


def body_ttk_health(stats, context, seconds):
    """(health scale, relative spread) of a target that dies at each time.

    The target state before it dies does not depend on its total health, so
    one replay on an unkillable copy gives the cumulative health damage D(t)
    of one life; a target of health D(T) dies at T (body shots, times from
    the first damage event). The spread is the relative standard deviation
    of D(T) from per-hit randomness (crit tiers, proc counts).
    """
    from .manual_combat import prepare
    from .combat_replay import replay
    data = stats._combat_inputs
    target = context.get("target") or {}
    scenario = data["engine"]["scenario"]
    enhancements = dict(context.get("enemy_enhancements") or {})
    enhancements["healthScale"] = 1e9
    combat = prepare(
        data["engine"], data["mods"], data["arcanes"],
        cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == "assumed_max",
        incarnon_choices=data["choices"], affinity_target=target, level=context.get("level"),
        eximus=bool(enhancements.get("eximus")), resolve_cache=getattr(stats, "_resolve_cache", None),
    )
    curve = []
    result = replay(
        stats, target, combat=combat, trigger_sources=combat["trigger_sources"],
        attacks_per_second=stats.sustained_attack_rate, window_seconds=max(seconds) + 2.0, headshot_chance=0.0,
        status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
        damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
        level=context.get("level"), armour_strip=float(context.get("armour_strip") or 0.0),
        elemental_armour_strip=float(context.get("elemental_armour_strip") or 0.0),
        steel_path=bool(context.get("steel_path")), enemy_enhancements=enhancements,
        forced_procs=context.get("forcedProcs"), collect_timeline=False, life_curve=curve,
    )
    unit_health = float(result.get("targetTotalEhp") or 0.0) / 1e9  # health at healthScale 1
    if not curve or unit_health <= 0:
        return None
    curve.sort(key=lambda row: row[0])
    start = curve[0][0]
    out = []
    for limit in seconds:
        rows = [row for row in curve if row[0] - start <= limit + 1e-9]
        dealt = sum(row[1] for row in rows)
        spread = math.sqrt(sum(row[2] for row in rows)) / dealt if dealt > 0 else 0.0
        out.append((dealt / unit_health, spread))
    return out
