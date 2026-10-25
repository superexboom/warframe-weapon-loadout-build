"""Replay caches: equal loadouts share a replay, and caches never ride in pickles."""
import copy
import pickle
from dataclasses import replace
import pytest

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


@pytest.fixture
def candidate_cache(monkeypatch):
    from wfarsenal import evaluation_cache
    evaluation_cache.clear()
    monkeypatch.setattr(evaluation_cache, "ENABLED", True)
    yield evaluation_cache
    evaluation_cache.clear()


def _candidate_inputs():
    from wfarsenal import optimizer as o
    from wfarsenal.damage import Scenario, ModEffect
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Lato")
    weapon = o._select_fire_mode(weapon, 0, weapon_type="pistol")[0]
    card = o._Card("damage", None, 0, (ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", .5),),
                   (), 4, "AP_ATTACK")
    context = dict(target=dict(health=5000, shield=0, armour=0, baseLevel=1), level=1,
                   windowSeconds=3, headshotChance=0)
    return weapon, card, dict(scenario=Scenario(trigger_policy="emergent"),
                             metric="killsPerMinute", target_context=context)


def test_candidate_hit_skips_scoring_and_returns_independent_values(candidate_cache, monkeypatch):
    from wfarsenal import optimizer as o
    weapon, card, kwargs = _candidate_inputs()
    score, calls = o._score, []

    def counted(*args, **kw):
        calls.append(1)
        return score(*args, **kw)

    monkeypatch.setattr(o, "_score", counted)
    first = o._evaluate(weapon, (card,), None, **kwargs)
    fresh_card = replace(card)
    second = o._evaluate(weapon, (fresh_card,), None, **kwargs)
    assert len(calls) == 1 and candidate_cache.STATS["hits"] == 1
    assert second.score == first.score and second.stats.damage_types == first.stats.damage_types
    assert second.cards[0] is fresh_card
    first.stats.damage_types.clear()
    first.stats.unsupported.append("another target")
    assert second.stats.damage_types and "another target" not in second.stats.unsupported
    third = o._evaluate(weapon, (card,), None, **kwargs)
    assert third.stats.damage_types == second.stats.damage_types
    assert not third.stats._combat_scores and not third.stats._resolve_cache


def test_candidate_cache_separates_rolls_contexts_and_legality(candidate_cache, monkeypatch):
    from wfarsenal import optimizer as o
    weapon, card, kwargs = _candidate_inputs()
    riven = replace(card, key="__riven__", drain=18)
    combinations = [
        (riven, kwargs),
        (replace(riven, effects=(replace(riven.effects[0], value=.6),)), kwargs),
        (riven, dict(kwargs, target_context=dict(kwargs["target_context"], headshotChance=1))),
        (riven, dict(kwargs, target_context=dict(kwargs["target_context"], windowSeconds=2))),
        (riven, dict(kwargs, scenario=replace(kwargs["scenario"], aiming=True))),
        (riven, dict(kwargs, capacity_limit=2)),
        (riven, dict(kwargs, fixed_riven_index=0)),
    ]
    for actual, context in combinations:
        candidate_cache.ENABLED = False
        reference = o._evaluate(weapon, (card,), actual, **context)
        candidate_cache.ENABLED = True
        for _ in range(2):
            found = o._evaluate(weapon, (card,), actual, **context)
            assert (found is None) == (reference is None)
            if found is not None:
                assert (found.score, found.capacity, found.riven_index, found.stats.damage_types) == (
                    reference.score, reference.capacity, reference.riven_index, reference.stats.damage_types)
    assert candidate_cache.STATS["hits"] == len(combinations)


def test_candidate_hit_still_honours_cancellation(candidate_cache):
    from wfarsenal import optimizer as o, search_session
    weapon, card, kwargs = _candidate_inputs()
    o._evaluate(weapon, (card,), None, **kwargs)
    token = search_session.CANCEL.set(lambda: True)
    try:
        with pytest.raises(search_session.SearchCancelled):
            o._evaluate(weapon, (card,), None, **kwargs)
    finally:
        search_session.CANCEL.reset(token)


def test_candidate_cache_evicts_by_value_bytes(candidate_cache, monkeypatch):
    monkeypatch.setattr(candidate_cache, "MAX_BYTES", 700)
    value = (0., (), b"value" * 20, 0, None, 0)
    candidate_cache.put("old", value)
    candidate_cache.put("new", value)
    assert candidate_cache.get("old") is candidate_cache.MISSING
    assert candidate_cache.get("new") == value
    assert candidate_cache.STATS["evictions"] == 1


@pytest.mark.parametrize("name", ["Lato", "Torid", "Burston Prime", "Knell Prime", "Nikana Prime", "Glaive Prime", "Onos"])
def test_score_only_replay_matches_full_and_keeps_report_cache_separate(name, monkeypatch):
    from wfarsenal import optimizer as o, native_replay, search_combat
    from wfarsenal.damage import Scenario, ModEffect
    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    family = o._weapon_type(None, weapon)
    weapon = o._select_fire_mode(weapon, 0, weapon_type=family)[0]
    scenario = Scenario(trigger_policy="emergent")
    effects = [ModEffect("WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", .6)]
    engine = dict(weapon=weapon, fire_mode=0, scenario=scenario, effects=effects)
    target = dict(health=10000, shield=0, armour=100, baseLevel=1)
    context = dict(target=target, level=1, windowSeconds=3, headshotChance=.5)
    stats = o.apply_mods(weapon, effects, scenario=scenario)

    def run(score_only):
        combat = prepare(engine, [], [])
        return replay(stats, target, combat=combat, trigger_sources=combat['trigger_sources'],
                      attacks_per_second=stats.sustained_attack_rate, window_seconds=3,
                      headshot_chance=.5, level=1, collect_timeline=False, score_only=score_only)

    full = run(False)
    for native in (True, False):
        monkeypatch.setattr(native_replay, "ENABLED", native and native_replay.wfcore is not None)
        lean = run(True)
        for field in ("killsPerMinute", "windowDps", "totalWindowDamage", "unsupported"):
            assert lean[field] == full[field], (name, native, field)
    o._bind_combat_inputs(stats, weapon, [], effects, scenario)
    lean = search_combat.window(stats, context, score_only=True)
    complete = search_combat.window(stats, context)
    assert "directEventLedger" not in lean and "directEventLedger" in complete
    assert lean["killsPerMinute"] == complete["killsPerMinute"]
