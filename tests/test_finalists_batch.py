"""Final-objective selection and independently initialized native health runs."""
import math
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import app
from wfarsenal import optimizer as o, search_combat, native_replay
from wfarsenal.damage import Scenario, ModEffect


def test_finalists_are_ranked_on_all_nodes_not_the_middle_node():
    # Exhaust the independent four-build fixture. The centre winner loses
    # on the geometric mean; the third seed is the unique final winner.
    scores = {"centre": (2., 100., 2.), "balanced": (35., 35., 35.),
              "seed": (40., 34., 40.), "weak": (1., 2., 1.)}
    weights = (5 / 18, 8 / 18, 5 / 18)
    truth = {name: math.exp(sum(w * math.log(v) for w, v in zip(weights, values)))
             for name, values in scores.items()}
    candidates = [SimpleNamespace(cards=(SimpleNamespace(key=name, rank=5),), riven_index=None,
                                  score=values[1]) for name, values in scores.items()]
    assert max(candidates, key=lambda row: row.score).cards[0].key == 'centre'
    calls = []

    def rescore(candidate):
        key = candidate.cards[0].key
        calls.append(key)
        return SimpleNamespace(cards=candidate.cards, score=truth[key])

    result = o._best_finalist([*candidates, candidates[0]], rescore)
    assert result.cards[0].key == max(truth, key=truth.get) == 'seed'
    assert len(calls) == len(scores)


def test_real_lato_finalists_recover_the_better_three_node_build(monkeypatch):
    fixture = json.loads((Path(__file__).parent / 'fixtures/finalists_lato.json').read_text(encoding='utf-8'))
    weapon = o.resolve_record(app.EXPORTS['weapons'], fixture['weapon'], kind='weapon')
    weapon = o._select_fire_mode(weapon, fixture['fireMode'], weapon_type=o._weapon_type(None, weapon))[0]
    scenario = o._requested_scenario({}, 'killsPerMinute')
    pool, _ = o._candidate_mods(app.EXPORTS, weapon, scenario)
    by_key = {card.key: card for card in pool}
    riven = o._card_from_lines(o._wire_lines(fixture['stats'])[0])
    passives, _, _, _ = o._incarnon_card(weapon, fixture['incarnonChoices'], scenario=scenario,
        metric='killsPerMinute', policy=app.EXPORTS.get('incarnonDefaults'), build_label=app.EXPORTS['buildLabel'])
    target = fixture['target']
    context = dict(target=o.resolve_record(app.EXPORTS['enemies'], target['enemyPath'], kind='enemy'),
        level=target['level'], steel_path=target['steelPath'], enemy_enhancements=target['enemyEnhancements'],
        headshotChance=target['headshotChance'], windowSeconds=target['windowSeconds'],
        hardnessNodes=fixture['hardnessNodes'], killBranches=4)
    candidates = [SimpleNamespace(cards=tuple(by_key[k] for k in row['cards']),
                                 riven_index=row['riven_index'], score=row['centre'])
                  for row in fixture['finalists']]
    # Independent flat measurement of every finalist through the scalar fight;
    # no beam/seed selection or batch protocol participates in the reference.
    monkeypatch.setattr(native_replay, 'HEALTH_BATCH', False)

    def score(candidate):
        return o._evaluate(weapon, candidate.cards, riven, scenario=scenario, metric='killsPerMinute',
            passives=passives, target_context=context, fixed_riven_index=candidate.riven_index,
            reorder_elements=False)

    flat = [score(candidate) for candidate in candidates]
    old = score(max(candidates, key=lambda candidate: candidate.score))
    result = o._best_finalist(candidates, score)
    assert result.score == max(row.score for row in flat)
    assert result.score > old.score * 1.02
    assert any(card.record and card.record.get('nameEn') == 'Primed Convulsion' for card in result.cards)


def _bound(name, mode=0, *, cycle=False):
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
    weapon = o._select_fire_mode(weapon, mode, weapon_type=o._weapon_type(None, weapon))[0]
    scenario = Scenario(trigger_policy='emergent', incarnon_cycle=cycle)
    effects = [ModEffect('WEAPON_PROC_CHANCE', 'STACKING_MULTIPLY', 1.),
               ModEffect('WEAPON_FIRE_DAMAGE', 'ADD', .6, damage_type='DT_FIRE')]
    stats = o.apply_mods(weapon, effects, scenario=scenario)
    o._bind_combat_inputs(stats, weapon, (), effects, scenario)
    return stats


@pytest.fixture(autouse=True)
def isolated_replays(monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(search_combat, '_REPLAYS', OrderedDict())


@pytest.mark.parametrize('name,mode', [('Lato', 0), ('Torid', 0), ('Kuva Zarr', 0),
    ('Burston Prime', 1), ('Nikana Prime', 0), ('Glaive Prime', 0), ('Onos', 0), ('Stug', 0)])
@pytest.mark.parametrize('shield,overguard', [(0., 0.), (300., 0.), (300., 800.)])
def test_native_health_batch_equals_scalar_runs_and_does_not_carry_state(name, mode, shield, overguard):
    if not native_replay.ENABLED or not hasattr(native_replay.wfcore, 'trajectory_health_batch'):
        pytest.skip('native batch library not built')
    stats = _bound(name, mode)
    context = dict(target=dict(health=3000., shield=shield, overguard=overguard, armour=200., baseLevel=1),
                   level=1, windowSeconds=4., headshotChance=.5)
    contexts = [o._with_health_scale(context, scale) for scale in (1., .2, 3., .2)]
    reference = [search_combat.window(stats, c, score_only=True) for c in contexts]
    search_combat._REPLAYS.clear()
    stats._combat_scores.clear()
    stats._resolve_cache.clear()
    count = native_replay.HEALTH_BATCH_STATS['runs']
    batched = search_combat.windows(stats, contexts)
    assert batched is not None
    assert native_replay.HEALTH_BATCH_STATS['runs'] == count + len(contexts)
    for actual, expected in zip(batched, reference):
        for key in ('killsPerMinute', 'windowDps', 'totalWindowDamage', 'unsupported'):
            assert actual[key] == expected[key], (name, mode, key, actual[key], expected[key])
    assert batched[1] == batched[3]
    assert search_combat.windows(stats, contexts) == batched
    assert native_replay.HEALTH_BATCH_STATS['runs'] == count + len(contexts)


def test_batch_refuses_other_fight_changes_and_scalar_remains_available():
    stats = _bound('Lato')
    context = dict(target=dict(health=1000, shield=0, armour=0, baseLevel=1), level=1, windowSeconds=2.)
    assert search_combat.windows(stats, [context, dict(context, headshotChance=1.)]) is None
    assert search_combat.window(stats, context, score_only=True)['killsPerMinute'] >= 0


@pytest.mark.parametrize('name,mod_names,arcane_name,cycle', [
    ('Soma Prime', ['Serration', 'Galvanized Chamber'], 'Primary Merciless', False),
    ('Laetum', ['Hornet Strike', 'Galvanized Diffusion'], 'Secondary Enervate', False),
    ('Boltor Prime', ['Serration', 'Galvanized Chamber'], None, True),
])
def test_native_batch_resets_dynamic_mod_arcane_and_cycle_state(name, mod_names, arcane_name, cycle):
    if not native_replay.ENABLED or not hasattr(native_replay.wfcore, 'trajectory_health_batch'):
        pytest.skip('native batch library not built')
    raw = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
    mode = 1 if cycle else 0
    weapon = o._select_fire_mode(raw, mode, weapon_type=o._weapon_type(None, raw))[0]
    scenario = Scenario(trigger_policy='emergent', incarnon_cycle=cycle)
    pool, _ = o._candidate_mods(app.EXPORTS, weapon, scenario)
    cards = [next(c for c in pool if c.record and c.record.get('nameEn') == mod_name) for mod_name in mod_names]
    passives = None
    if arcane_name:
        arcane = next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn') == arcane_name)
        passives, _, _ = o._arcane_card(app.EXPORTS['arcanes'], [{'query': arcane['path']}], weapon)
    effects = o._effects([*cards, passives] if passives else cards, scenario)
    stats = o.apply_mods(weapon, effects, scenario=scenario)
    o._bind_combat_inputs(stats, weapon, cards, effects, scenario, passives)
    context = dict(target=dict(health=500, shield=100, armour=100, baseLevel=1), level=1,
                   windowSeconds=12., headshotChance=.5)
    contexts = [o._with_health_scale(context, scale) for scale in (.3, 3., .3)]
    expected = [search_combat.window(stats, c, score_only=True) for c in contexts]
    search_combat._REPLAYS.clear()
    stats._combat_scores.clear()
    stats._resolve_cache.clear()
    actual = search_combat.windows(stats, contexts)
    assert actual is not None
    for a, e in zip(actual, expected):
        for key in ('killsPerMinute', 'windowDps', 'totalWindowDamage', 'unsupported'):
            assert a[key] == e[key], (name, key)
    assert actual[0] == actual[2]


def test_older_native_library_and_shadow_mode_use_the_scalar_protocol(monkeypatch):
    stats = _bound('Lato')
    contexts = [dict(target=dict(health=1000, shield=0, armour=0, baseLevel=1), level=1, windowSeconds=2.)]
    monkeypatch.setattr(native_replay, 'SHADOW', True)
    assert search_combat.windows(stats, contexts) is None
    monkeypatch.setattr(native_replay, 'SHADOW', False)
    monkeypatch.setattr(native_replay, 'wfcore', SimpleNamespace())
    assert search_combat.windows(stats, contexts) is None


def test_batch_keeps_weak_kill_feedback_on_the_scalar_path(monkeypatch):
    from wfarsenal import manual_combat
    original = manual_combat.prepare

    def prepare(*args, **kwargs):
        result = original(*args, **kwargs)
        result['magazineRestore'] = dict(kind='on-headshot-kill')
        return result

    monkeypatch.setattr(manual_combat, 'prepare', prepare)
    context = dict(target=dict(health=1000, shield=0, armour=0, baseLevel=1), level=1, windowSeconds=2.)
    assert search_combat.windows(_bound('Lato'), [context, o._with_health_scale(context, 2.)]) is None


def test_aggregated_scores_match_scalar_path_and_resume_with_mixed_cache_hits(monkeypatch):
    context = dict(target=dict(health=3000, shield=100, armour=200, baseLevel=1), level=1,
        windowSeconds=4., headshotChance=.5,
        hardnessNodes=[dict(healthScale=s, healthSpread=.2, weight=w)
                       for s, w in [(1., 5 / 18), (4., 8 / 18), (16., 5 / 18)]])
    for metric in ('killsPerMinute', 'windowedDps', 'windowedTotalDamage'):
        monkeypatch.setattr(native_replay, 'HEALTH_BATCH', False)
        reference = o._score(_bound('Lato'), metric, target_context=context)
        search_combat._REPLAYS.clear()
        stats = _bound('Lato')
        single = {k: v for k, v in context.items() if k != 'hardnessNodes'}
        search_combat.window(stats, o._with_health_scale(single, .8), score_only=True)
        monkeypatch.setattr(native_replay, 'HEALTH_BATCH', True)
        assert o._score(stats, metric, target_context=context) == reference
