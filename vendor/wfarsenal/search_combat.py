"""Shared loadout event scoring for optimizer candidates and final checks."""
from __future__ import annotations
import hashlib
import math
import pickle
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import replace
from functools import lru_cache
from operator import itemgetter


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
        "combat_extras_json": str(getattr(passives, "combat_extras_json", "") or "") if passives else "",
    }
    stats._combat_scores = {}
    stats._resolve_cache = ResolveCache()


# Replays of identical loadouts in identical contexts, across stats objects
# (the same build is re-derived by every analysis of one weapon).
_REPLAYS = OrderedDict()
_REPLAYS_MAX = 4096
_UNHASHED = {"_combat_inputs", "_combat_scores", "_resolve_cache"}
_field_getter = lru_cache(maxsize=16)(itemgetter)


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


def _loadout_digest(stats, data):
    """Digest the loadout once for a batch of independently keyed target contexts."""
    fields = stats.__dataclass_fields__
    values = vars(stats)
    extras = sorted((k, v) for k, v in values.items() if k not in fields and k not in _UNHASHED)
    engine = data["engine"]
    engine_key = (_record_digest(engine["weapon"]), engine["effects"], engine["scenario"], engine["fire_mode"])
    mods = [(_record_digest(record), rank, extra) for record, rank, extra in data["mods"]]
    extras_json = data.get("combat_extras_json") or ""
    tail = (engine_key, mods, data["arcanes"], data["choices"], extras_json) if extras_json else (engine_key, mods, data["arcanes"], data["choices"])
    try:
        try:
            declared = (_field_getter(*fields)(values) if len(fields) > 1
                        else tuple(getattr(stats, name) for name in fields))
        except KeyError:  # Older or custom stats may leave class defaults out of __dict__.
            declared = tuple(getattr(stats, name) for name in fields)
        blob = pickle.dumps((type(stats), declared, extras, *tail), protocol=5)
    except (TypeError, pickle.PicklingError):
        # Extension attributes may only expose their value through repr.
        blob = pickle.dumps((repr(stats), [(k, repr(v)) for k, v in extras], *tail), protocol=5)
    return hashlib.blake2b(blob, digest_size=20).digest()


@lru_cache(maxsize=128)
def _context_digest(context_key):
    if isinstance(context_key, str):
        context_key = context_key.encode('utf-8', 'surrogatepass')
    return hashlib.blake2b(context_key, digest_size=20).digest()


def _context_snapshot(context):
    # Compare the current values, including nested types and iteration order.
    return pickle.dumps(context, protocol=5)


def _replay_key(stats, data, context_key):
    return _loadout_digest(stats, data), _context_digest(context_key)


def window(stats, context, *, score_only=False):
    from . import native_replay
    from .manual_combat import prepare
    from .combat_replay import replay
    from .search_session import check_cancelled
    check_cancelled()
    data = stats._combat_inputs
    try:
        context_key = None if native_replay.SHADOW else _context_snapshot(context)
    except (TypeError, AttributeError, pickle.PicklingError):
        context_key = None
    cache = stats._combat_scores
    shared = None
    result = None
    if context_key is not None:
        loadout, context_key = _replay_key(stats, data, context_key)
        key = (loadout, context_key, score_only)
        if score_only and (loadout, context_key, False) in cache:
            return cache[loadout, context_key, False]
        if key in cache:
            return cache[key]
        shared = (score_only, (loadout, context_key))
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
    extras = None
    if data.get("combat_extras_json"):
        import json as _json
        extras = _json.loads(data["combat_extras_json"])
    combat = prepare(
        data["engine"], data["mods"], data["arcanes"],
        cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == "assumed_max",
        incarnon_choices=data["choices"], affinity_target=target, level=context.get("level"),
        eximus=bool(enhancements.get("eximus")), resolve_cache=getattr(stats, "_resolve_cache", None),
        combat_extras=extras,
    )
    rot_duty = float((extras or {}).get("abilityRotationDutyCycle") or 1.0)
    result = replay(
        stats, target, combat=combat, trigger_sources=combat["trigger_sources"],
        attacks_per_second=stats.sustained_attack_rate * max(0.05, min(1.0, rot_duty)),
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
    if shared is not None:
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
    if not data or 'engine' not in data or data.get('combat_extras_json'):
        return None
    check_cancelled()
    first = contexts[0]
    def common_target(context):
        return {**context, 'enemy_enhancements': {k: v for k, v in (context.get('enemy_enhancements') or {}).items()
                                                  if k != 'healthScale'}}
    base = common_target(first)
    base_signature = None
    for context in contexts[1:]:
        # Hardness nodes are shallow copies of one target. For independently supplied
        # contexts retain the original type-sensitive check (including nested values).
        other = common_target(context)
        copied = (base.keys() == other.keys() and all(other[k] is v for k, v in base.items() if k != 'enemy_enhancements')
                  and base['enemy_enhancements'].keys() == other['enemy_enhancements'].keys()
                  and all(other['enemy_enhancements'][k] is v for k, v in base['enemy_enhancements'].items()))
        if not copied:
            try:
                if base_signature is None:
                    base_signature = _context_snapshot(base)
                matches = _context_snapshot(other) == base_signature
            except (TypeError, AttributeError, pickle.PicklingError):
                return None
            if not matches:
                return None
    cache = stats._combat_scores
    rows, pending = [None] * len(contexts), []
    loadout = _loadout_digest(stats, data)
    for i, context in enumerate(contexts):
        try:
            key = _context_digest(_context_snapshot(context))
        except (TypeError, AttributeError, pickle.PicklingError):
            return None
        value = cache.get((loadout, key, False)) or cache.get((loadout, key, True))
        shared = None
        if value is None:
            shared = (True, (loadout, key))
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
            cache[loadout, key, True] = result
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
    extras = None
    if data.get("combat_extras_json"):
        import json as _json
        extras = _json.loads(data["combat_extras_json"])
    combat = prepare(
        data["engine"], data["mods"], data["arcanes"],
        cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == "assumed_max",
        incarnon_choices=data["choices"], affinity_target=target, level=context.get("level"),
        eximus=bool(enhancements.get("eximus")), resolve_cache=getattr(stats, "_resolve_cache", None),
        combat_extras=extras,
    )
    curve = []
    rot_duty = float((extras or {}).get("abilityRotationDutyCycle") or 1.0)
    result = replay(
        stats, target, combat=combat, trigger_sources=combat["trigger_sources"],
        attacks_per_second=stats.sustained_attack_rate * max(0.05, min(1.0, rot_duty)), window_seconds=max(seconds) + 2.0, headshot_chance=0.0,
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
