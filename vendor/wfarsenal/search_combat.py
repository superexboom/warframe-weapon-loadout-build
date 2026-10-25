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
    extras = sorted((k, v) for k, v in vars(stats).items() if k not in fields and k not in _UNHASHED)
    engine = data["engine"]
    engine_key = (_record_digest(engine["weapon"]), engine["effects"], engine["scenario"], engine["fire_mode"])
    mods = [(_record_digest(record), rank, extra) for record, rank, extra in data["mods"]]
    tail = (engine_key, mods, data["arcanes"], data["choices"], context_key)
    try:
        blob = pickle.dumps((type(stats), tuple(getattr(stats, name) for name in fields), extras, *tail), protocol=5)
    except (TypeError, pickle.PicklingError):
        # Extension attributes may only expose their value through repr.
        blob = pickle.dumps((repr(stats), [(k, repr(v)) for k, v in extras], *tail), protocol=5)
    return hashlib.blake2b(blob, digest_size=20).digest()


def window(stats, context, *, score_only=False):
    from .manual_combat import prepare
    from .combat_replay import replay
    data = stats._combat_inputs
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    cache = stats._combat_scores
    if score_only and (key, False) in cache:
        return cache[key, False]
    context_key = key
    key = (key, score_only)
    if key in cache:
        return cache[key]
    shared = (score_only, _replay_key(stats, data, context_key))
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
        score_only=score_only,
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


def windows(stats, contexts):
    """Score one loadout on health-only variants, or request the scalar path.

    Batched rows have independent clocks, targets and trigger state. Weak-kill
    branching and shadow comparisons keep their existing scalar protocol.
    """
    from . import native_replay
    from .manual_combat import prepare
    from .search_session import check_cancelled
    if (not contexts or len(contexts) > 64 or not native_replay.ENABLED or not native_replay.HEALTH_BATCH
            or native_replay.SHADOW or not hasattr(native_replay.wfcore, 'trajectory_health_batch')):
        return None
    data = getattr(stats, '_combat_inputs', None)
    if not data or 'engine' not in data:
        return None
    check_cancelled()
    signatures = []
    for context in contexts:
        other = {**context, 'enemy_enhancements': {k: v for k, v in (context.get('enemy_enhancements') or {}).items()
                                                 if k != 'healthScale'}}
        signatures.append(json.dumps(other, sort_keys=True, ensure_ascii=False, default=str))
    if any(signature != signatures[0] for signature in signatures[1:]):
        return None
    cache = stats._combat_scores
    rows, pending = [None] * len(contexts), []
    for i, context in enumerate(contexts):
        key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
        value = cache.get((key, False)) or cache.get((key, True))
        shared = None
        if value is None:
            shared = (True, _replay_key(stats, data, key))
            value = _REPLAYS.get(shared)
        if value is not None:
            rows[i] = value
        else:
            pending.append((i, key, shared, context))
    if pending:
        context = pending[0][3]
        scenario = data['engine']['scenario']
        target = context.get('target') or {}
        enhancements = context.get('enemy_enhancements') or {}
        combat = prepare(data['engine'], data['mods'], data['arcanes'],
            cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == 'assumed_max',
            incarnon_choices=data['choices'], affinity_target=target, level=context.get('level'),
            eximus=bool(enhancements.get('eximus')), resolve_cache=getattr(stats, '_resolve_cache', None))
        restore = combat.get('magazineRestore') or {}
        if (restore.get('kind') == 'on-headshot-kill'
                or any((q.get('kind') == 'on-headshot-kill' or q.get('freeAmmo')) and q.get('perEvent', 1.) != 0
                       for q in combat['trigger_sources'])):
            return None
        options = dict(combat=combat, trigger_sources=combat['trigger_sources'],
            attacks_per_second=stats.sustained_attack_rate,
            window_seconds=float(context.get('windowSeconds') or 30.),
            headshot_chance=float(context.get('headshotChance', 1. if context.get('hit_location') == 'head' else 0.)),
            status_rate_multiplier=float(context.get('statusRateMultiplier') or 1.),
            damage_rate_multiplier=float(context.get('stanceMultiplier') or 1.), level=context.get('level'),
            armour_strip=float(context.get('armour_strip') or 0.),
            elemental_armour_strip=float(context.get('elemental_armour_strip') or 0.),
            steel_path=bool(context.get('steel_path')), enemy_enhancements=enhancements,
            forced_procs=context.get('forcedProcs'), collect_timeline=False, score_only=True)
        if not native_replay.supported(stats, options):
            return None
        results = native_replay.trajectory(stats, target,
            health_targets=[row[3].get('enemy_enhancements') for row in pending], **options)
        if results is None:
            return None
        for (i, key, shared, _), result in zip(pending, results):
            rows[i] = result
            cache[key, True] = result
            _REPLAYS[shared] = result
        while len(_REPLAYS) > _REPLAYS_MAX:
            try:
                _REPLAYS.popitem(last=False)
            except KeyError:
                break
    for row in rows:
        for reason in row.get('unsupported') or ():
            if reason not in stats.unsupported:
                stats.unsupported.append(reason)
    return rows


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
