"""Bounded candidate results, before panel construction and event replay."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import os
import pickle
from threading import RLock

from .search_combat import _record_digest
from .record_keys import record_key, pin

ENABLED = os.environ.get("WF_EVALUATION_CACHE", "1") != "0"
MAX_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 8192
_results = OrderedDict()
_cards = OrderedDict()
_bytes = 0
_lock = RLock()
STATS = dict(hits=0, misses=0, stores=0, evictions=0)
MISSING = object()


def _card(card):
    if card is None:
        return None
    # A Riven's key is always __riven__; its effects and actual rolls matter.
    record = _record_digest(card.record) if card.record is not None else None
    shell = _record_digest(card.set_shell) if card.set_shell is not None else None
    triggers = tuple(_record_digest(spec) for spec in card.trigger_specs)
    arcanes = tuple((_record_digest(r), rank, _record_digest(config) if config is not None else None)
                    for r, rank, config in card.event_arcanes)
    identity = (type(card), record_key(vars(card)), record, shell, triggers, arcanes)
    with _lock:
        hit = _cards.get(identity)
        if hit is not None:
            return hit[1]
    wire = (type(card), record, tuple((k, v) for k, v in vars(card).items() if k != "record"))
    digest = hashlib.blake2b(pickle.dumps(wire, protocol=5), digest_size=20).digest()
    with _lock:
        _cards[identity] = (pin(vars(card)), digest)
        while len(_cards) > 4096:
            _cards.popitem(last=False)
    return digest


def key(weapon, cards, riven, *, scenario, metric, passives, slot_limit,
        capacity_limit, special_cards, special_capacity_cost, target_context,
        fixed_riven_index, reorder_elements):
    if not ENABLED:
        return None
    try:
        context = None if target_context is None else tuple(
            (k, _record_digest(v) if k == "target" and isinstance(v, dict) else v)
            for k, v in target_context.items())
        wire = (_record_digest(weapon), tuple(map(_card, cards)), _card(riven), scenario,
                metric, _card(passives), slot_limit, capacity_limit, tuple(map(_card, special_cards)),
                special_capacity_cost, context, fixed_riven_index, reorder_elements)
        return hashlib.blake2b(pickle.dumps(wire, protocol=5), digest_size=20).digest()
    except (TypeError, AttributeError, pickle.PicklingError):
        return None


def get(key):
    if key is None:
        return MISSING
    with _lock:
        value = _results.get(key, MISSING)
        STATS["misses" if value is MISSING else "hits"] += 1
        if value is not MISSING:
            _results.move_to_end(key)
        return value


def put(key, value):
    global _bytes
    if key is None:
        return
    size = len(value[2]) + 256 if value is not None else 256
    if size > MAX_BYTES:
        return
    with _lock:
        previous = _results.pop(key, MISSING)
        if previous is not MISSING:
            _bytes -= len(previous[2]) + 256 if previous is not None else 256
        _results[key] = value
        _bytes += size
        STATS["stores"] += 1
        while _bytes > MAX_BYTES or len(_results) > MAX_ENTRIES:
            _, expired = _results.popitem(last=False)
            _bytes -= len(expired[2]) + 256 if expired is not None else 256
            STATS["evictions"] += 1


def clear():
    global _bytes
    with _lock:
        _results.clear()
        _cards.clear()
        _bytes = 0
        STATS.update(hits=0, misses=0, stores=0, evictions=0)


def snapshot(evaluation, cards):
    """Keep values, never the mutable replay/resolver caches or bound inputs."""
    fields = {k: v for k, v in vars(evaluation.stats).items()
              if k not in {"_combat_inputs", "_combat_scores", "_resolve_cache"}}
    order = tuple(next(i for i, source in enumerate(cards) if card is source)
                  for card in evaluation.cards)
    return (evaluation.score, order, pickle.dumps(fields, protocol=5), evaluation.capacity,
            evaluation.riven_index, evaluation.scenario.victim_status_count)
