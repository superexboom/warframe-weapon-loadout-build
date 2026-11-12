"""The final result must revisit family variants and preserve user constraints."""
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario


def card(key, family=None, required=False, drain=0):
    return o._Card(key, {'modFamily': family or key}, 0, (), (), drain, None, required=required)


def evaluation(cards, score, element=True):
    return SimpleNamespace(cards=tuple(cards), score=score,
                           stats=SimpleNamespace(damage_types={'DT_VIRAL': 1} if element else {}))


def run(monkeypatch, pool, initial, scores, **kwargs):
    def evaluate(_weapon, cards, _riven, **_):
        value = scores.get(tuple(c.key for c in cards), 0.)
        return evaluation(cards, value)
    monkeypatch.setattr(o, '_evaluate', evaluate)
    return o.refine_final_build({}, pool, kwargs.pop('riven', None), initial,
        scenario=Scenario(), metric='killsPerMinute', target_context={'windowSeconds': 30}, **kwargs)


def test_fast_restores_better_completed_build_family_variant(monkeypatch):
    ordinary, galvanized, partner = card('ordinary', 'diffusion'), card('galvanized', 'diffusion'), card('partner')
    old = evaluation((ordinary, partner), 10)
    found = run(monkeypatch, (ordinary, galvanized, partner), old,
                {('galvanized', 'partner'): 14}, profile='fast')
    assert found.score == 14
    assert old.cards == (ordinary, partner) and old.score == 10


def test_standard_reaches_independent_small_pool_optimum(monkeypatch):
    a, b, c = card('a'), card('b'), card('c')
    scores = {('a',): 4, ('b',): 2, ('c',): 1,
              ('a', 'b'): 10, ('a', 'c'): 12, ('b', 'c'): 6}
    found = run(monkeypatch, (a, b, c), evaluation((a, b), 10), scores, slot_count=2)
    assert found.score == max(scores.values())


def test_constraints_hold_after_proxy_and_family_replacement(monkeypatch):
    a, b, forbidden = card('a', 'family'), card('b'), card('forbidden', 'family')
    expensive = card('expensive', drain=99)
    old = evaluation((a, b), 10)
    found = run(monkeypatch, (a, b, forbidden, expensive), old,
                {('forbidden', 'b'): 30, ('expensive', 'b'): 40, ('a',): 50},
                required_mod_keys=['a'], forbidden_mod_keys=['forbidden'], min_fill=2, max_fill=2,
                capacity_limit=60)
    assert found is old


def test_explicit_required_and_implicit_required_are_preserved(monkeypatch):
    a, b, c = card('a', required=True), card('b'), card('c')
    old = evaluation((a, b), 10)
    found = run(monkeypatch, (a, b, c), old, {('c', 'b'): 100, ('a', 'c'): 20},
                required_mod_keys=['b'], slot_count=2)
    assert found is old


def test_element_contract_survives_local_improvement(monkeypatch):
    evaluate = o._evaluate
    a, b = card('a'), card('b')
    old = evaluation((a,), 10)
    monkeypatch.setattr(o, '_evaluate', lambda _w, cards, _r, **_: evaluation(cards, 20, element=False))
    found = o.refine_final_build({}, (a, b), None, old, scenario=Scenario(), metric='killsPerMinute',
                               target_context={'windowSeconds': 30}, required_damage_type='DT_VIRAL', slot_count=1)
    assert found is old
    found = o.refine_final_build({}, (a, b), None, old, scenario=Scenario(), metric='killsPerMinute',
                               target_context={'windowSeconds': 30}, required_damage_type='DT_VIRAL', slot_count=1,
                               profile='ultra', max_evaluations=3, max_rounds=2, full_neighbourhood=True)
    assert found is old
    # Cold, Heat, then a Toxin Riven is Blast+Toxin; an earlier Riven is Viral+Heat.
    # A higher illegal score must not hide the legal insertion point.
    import app
    from wfarsenal.damage import ModEffect
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Braton Prime')
    mods = [next(m for m in app.EXPORTS['mods'] if m.get('nameEn') == name)
            for name in ('Cryo Rounds', 'Hellfire')]
    installed = tuple(o._mod_card(m, Scenario()) for m in mods)
    toxin = o._Card('riven', None, 8, (ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED', 'ADD', .9, damage_type='DT_POISON'),), (), 9, None)
    monkeypatch.setattr(o, '_score', lambda stats, _metric, *_args, **_: 100. if stats.damage_types.get('DT_EXPLOSION') else 10.)
    value = evaluate(weapon, installed, toxin, scenario=Scenario(), metric='attackDps',
                     reorder_elements=False, required_damage_type='DT_VIRAL')
    assert value.score == 10. and value.riven_index < 2
    assert value.stats.damage_types.get('DT_VIRAL', 0.) > 0.


def test_deep_pair_search_crosses_a_valley_standard_cannot(monkeypatch):
    a,b,c,d=(card(k) for k in ['a','b','c','d'])
    scores={('a','b'):10.,('c','b'):9.,('a','d'):9.,('c','d'):20.}
    old=evaluation((a,b),10.)
    standard=run(monkeypatch,(a,b,c,d),old,scores,profile='standard',slot_count=2,min_fill=2)
    deep=run(monkeypatch,(a,b,c,d),old,scores,profile='deep',slot_count=2,min_fill=2)
    assert standard.score==10. and deep.score==max(scores.values())


def test_warm_riven_seeds_cover_capacity_pairs_and_bounded_slot_search(monkeypatch):
    # Two removals are needed; the best pair can differ from the most costly.
    cards = tuple(card(key, drain=drain) for key, drain in zip('ABCDEFGH', [8,8,8,8,7,7,7,7]))
    riven = card('riven', drain=9)
    seeds = o._riven_seed_subsets(cards, riven, capacity_limit=60)
    assert len(seeds) == 28
    assert any(tuple(c.key for c in seed) == tuple('ABCDEF') for seed in seeds)
    calls = []
    def evaluate(_weapon, candidate, _riven, **_):
        calls.append(tuple(c.key for c in candidate))
        return evaluation(candidate, 20. if calls[-1] == ('A', 'C') else 0.)
    monkeypatch.setattr(o, '_evaluate', evaluate)
    a, b, c = (card(k) for k in 'ABC')
    old = evaluation((a, b), 10.)
    found = o.refine_final_build({}, (a, b, c), None, old, scenario=Scenario(), metric='killsPerMinute',
        target_context={'windowSeconds':30}, profile='ultra', slot_count=2, full_neighbourhood=True,
        max_evaluations=4, max_rounds=2)
    assert len(calls) <= 4 and found.score == 20.


def test_real_laetum_family_variant_matches_independently_replayed_board():
    import app
    fixture = json.loads((Path(__file__).parent / 'fixtures/final_refinement_laetum.json').read_text(encoding='utf-8'))
    payload = fixture['payload']
    _, context = app.build_weapon_payload(payload, fixed_mods=payload['mods'], return_engine_context=True)
    old = context['evaluation']
    found = o.refine_final_build(context['weapon'], context['candidates'], None, old,
        scenario=context['scenario'], metric=context['metric'], passives=context['passives'],
        capacity_limit=context['capacityLimit'], target_context=context['benchmarkContext'], profile='fast')
    board = app.simulate_manual_payload(dict(payload, mods=fixture['board_mods']))
    assert found.score == pytest.approx(board['benchmarkTimeline']['killsPerMinute'], rel=1e-12)
    assert found.score > old.score * 1.2
    assert any(c.record.get('nameEn') == 'Galvanized Diffusion' for c in found.cards)
