"""Replay caches: equal loadouts share a replay, and caches never ride in pickles."""
import copy
import pickle
from dataclasses import replace

import app
from wfarsenal.damage import apply_mods
from wfarsenal.search_combat import ResolveCache, _replay_key


def _stats(name):
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    return apply_mods(weapon, [])


def test_resolve_cache_is_not_pickled():
    cache = ResolveCache({("base", ()): "stats"})
    assert pickle.loads(pickle.dumps(cache)) == {}


def test_replay_key_follows_every_stat_and_context():
    stats = _stats("Soma Prime")
    data = dict(engine=dict(weapon={"path": "/w"}, effects=[], scenario=None, fire_mode=0),
                mods=[], arcanes=[], choices={})
    key = _replay_key(stats, data, '{"level": 170}')
    assert _replay_key(copy.copy(stats), data, '{"level": 170}') == key
    assert _replay_key(replace(stats, crit_chance=stats.crit_chance + 0.01), data, '{"level": 170}') != key
    assert _replay_key(stats, data, '{"level": 100}') != key
    assert _replay_key(stats, dict(data, choices={"tier2": "b"}), '{"level": 170}') != key
