"""Roll-dependent fatal negatives (2026-10-16): a malus fatal at its theoretical
roll but not at its lowest roll gets the roll it turns fatal at.

The motivating case is a 3+1 Status Duration window that crosses -100% (Dual
Decurion 87.7-107.2%): faster Heat strip makes it the best malus until
statuses expire between shots, and at -100% they vanish. The bisection must
follow the same two-step judgement as the weapon-level assessment: fixed
build first, re-search only past the fixed-build boundary.
"""
from __future__ import annotations

import pytest

from wfarsenal import optimizer as o

TOP = o._RivenLine("3", "触发时间", 107.24, 87.74, 107.24, True, "%",
                   o._effect_from_code("3", 107.24, negative=True, source="riven:theoretical:3"))
LOW = TOP.value * o.RIVEN_ROLL_LOW / o.RIVEN_ROLL_HIGH


def judge(fixed_cliff, searched_cliff=None):
    """Fixed build fatal past ``fixed_cliff``; the re-search rescues up to ``searched_cliff``."""
    searched_cliff = fixed_cliff if searched_cliff is None else searched_cliff
    calls = {"fixed": 0, "search": 0}

    def fixed_delta(line):
        calls["fixed"] += 1
        assert line.effect is not None and line.effect.value == pytest.approx(-line.value / 100.0)
        return 0.3 if line.value <= fixed_cliff else -0.6

    def fatal_at(line, delta):
        if delta >= -o.FATAL_NEGATIVE_LOSS:
            return False
        calls["search"] += 1
        return line.value > searched_cliff

    return fixed_delta, fatal_at, calls


def test_cliff_on_the_fixed_build_costs_one_re_search():
    fixed_delta, fatal_at, calls = judge(96.37)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert threshold == 96.3  # one decimal, rounded towards the safe side
    assert calls["search"] == 1


def test_re_search_rescues_rolls_past_the_fixed_boundary():
    fixed_delta, fatal_at, calls = judge(93.0, searched_cliff=99.12)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert 99.0 <= threshold <= 99.12
    assert calls["search"] > 1


def test_fatal_across_the_whole_window_has_no_threshold():
    fixed_delta, fatal_at, _ = judge(LOW - 1.0)
    assert o._fatal_roll_threshold(TOP, fixed_delta, fatal_at) is None


def test_lowest_roll_rescued_only_by_the_re_search():
    fixed_delta, fatal_at, _ = judge(LOW - 1.0, searched_cliff=100.0)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert 99.9 <= threshold <= 100.0


def test_existing_legal_builds_rescue_threshold_points_without_research(monkeypatch):
    from types import SimpleNamespace
    card = o._Card("adapted", None, 0, (), (), 0, None)
    monkeypatch.setattr(o, "_card_from_lines", lambda lines: tuple(lines))
    searches = []

    def fixed(weapon, items, **kwargs):
        return [100. if not lines else (80. if lines[-1].value < 93. else 40.) for _, lines in items]

    def optimal(lines):
        return 100. if not lines else (90. if lines[-1].value <= 100. else 50.)

    def search(weapon, pool, lines, **kwargs):
        searches.append(lines)
        return SimpleNamespace(score=optimal(lines), cards=(card,))

    monkeypatch.setattr(o, "_best_fixed_scores", fixed)
    monkeypatch.setattr(o, "_optimize", search)
    monkeypatch.setattr(o, "proxy_seed_best", lambda weapon, pool, lines, best, **kw: best)

    def assess():
        return o._assess_negatives({}, [card], SimpleNamespace(cards=(card,)), [], [(0., TOP)],
            {TOP.code: TOP}, frozenset(), scenario=None, metric="windowedDps", passives=None,
            capacity_limit=60, target_context={}, keep_cap=None)

    monkeypatch.setattr(o, "_evaluate", lambda *args, **kwargs: None)
    reference = assess()
    reference_calls = len(searches)
    searches.clear()
    monkeypatch.setattr(o, "_evaluate", lambda weapon, cards, lines, **kw:
                        SimpleNamespace(score=optimal(lines)))
    result = assess()
    assert result == reference and 99.9 <= result[0]["fatalAbove"] <= 100.
    assert len(searches) < reference_calls
    # Points where the known build remains below the cutoff still search.
    assert any(lines and 100. < lines[-1].value < TOP.value for lines in searches)


def test_static_classification_stops_only_after_a_score_proves_nonfatal(monkeypatch):
    from types import SimpleNamespace
    from wfarsenal.search_session import SESSION
    lines = {code: o._RivenLine(code, code, 100., 80., 100., True, '%', None) for code in ('F', '3', 'D')}
    monkeypatch.setattr(o, '_card_from_lines', lambda lines: tuple(line.code for line in lines))
    monkeypatch.setattr(o, '_best_fixed_scores', lambda weapon, items, **kw:
                        [100. if not card else 40. for _, card in items])
    calls = []
    scores = {(): (90., 100., 100.), ('F',): (70., 80., 90.),
              ('3',): (60., 80., 85.), ('D',): (40., 50., 55.)}

    def optimize(weapon, pool, riven, **kw):
        calls.append((riven, kw['profile']))
        return SimpleNamespace(score=scores[riven][kw['profile'] == 'standard'])

    def proxy(weapon, pool, riven, best, **kw):
        calls.append((riven, 'proxy'))
        return SimpleNamespace(score=scores[riven][2])

    monkeypatch.setattr(o, '_optimize', optimize)
    monkeypatch.setattr(o, 'proxy_seed_best', proxy)

    def assess(only):
        return o._assess_negatives({}, [], SimpleNamespace(cards=()), [], [(0., line) for line in lines.values()],
            lines, frozenset(), scenario=None, metric='windowedDps', passives=None, capacity_limit=60,
            target_context={}, keep_cap=None, classification_only=only)

    full = {row['code']: row for row in assess(False)}
    calls.clear()
    state = {}
    token = SESSION.set(state)
    try:
        short = {row['code']: row for row in assess(True)}
    finally:
        SESSION.reset(token)
    assert calls[:3] == [((), 'fast'), ((), 'standard'), ((), 'proxy')]
    assert (('F',), 'standard') not in calls and (('F',), 'proxy') not in calls
    assert (('3',), 'standard') not in calls and (('3',), 'proxy') in calls
    assert (('D',), 'standard') in calls and (('D',), 'proxy') in calls
    for code in lines:
        assert (short[code]['fatal'], short[code]['fatalAbove']) == (full[code]['fatal'], full[code]['fatalAbove'])
    assert short['F']['reoptimizedDeltaIsLowerBound'] and short['3']['reoptimizedDeltaIsLowerBound']
    assert 'reoptimizedDeltaIsLowerBound' not in short['D']
    assert not any('reoptimizedDeltaIsLowerBound' in row for row in full.values())
    assert state['negativeWork']['fastProofs'] == state['negativeWork']['proxyProofs'] == 1


def test_score_just_below_nonfatal_cutoff_still_runs_every_stage(monkeypatch):
    import math
    from types import SimpleNamespace
    calls = []
    line = o._RivenLine('F', 'F', 100., 80., 100., True, '%', None)
    monkeypatch.setattr(o, '_card_from_lines', lambda lines: bool(lines))
    monkeypatch.setattr(o, '_best_fixed_scores', lambda weapon, items, **kw:
                        [50. if card else 100. for _, card in items])
    below = math.nextafter(65., 0.)

    def optimize(weapon, pool, riven, **kw):
        calls.append((riven, kw['profile']))
        return SimpleNamespace(score=below if riven else 100.)

    def proxy(weapon, pool, riven, best, **kw):
        calls.append((riven, 'proxy'))
        return SimpleNamespace(score=(below if calls.count((True, 'proxy')) == 1 else 70.) if riven else 100.)

    monkeypatch.setattr(o, '_optimize', optimize)
    monkeypatch.setattr(o, 'proxy_seed_best', proxy)
    rows = o._assess_negatives({}, [], SimpleNamespace(cards=()), [], [(0., line)], {'F': line}, frozenset(),
        scenario=None, metric='windowedDps', passives=None, capacity_limit=60, target_context={}, keep_cap=None,
        classification_only=True)
    assert calls[-4:] == [(True, 'fast'), (True, 'proxy'), (True, 'standard'), (True, 'proxy')]
    assert not rows[0]['fatal'] and 'reoptimizedDeltaIsLowerBound' not in rows[0]


def test_static_classification_can_use_the_reference_build_as_a_legal_witness(monkeypatch):
    from types import SimpleNamespace
    card = o._Card('reference', None, 0, (), (), 0, None)
    line = o._RivenLine('F', 'F', 100., 80., 100., True, '%', None)
    monkeypatch.setattr(o, '_card_from_lines', lambda lines: bool(lines))
    monkeypatch.setattr(o, '_best_fixed_scores', lambda weapon, items, **kw: [100., 40.])
    calls = []

    def optimize(weapon, pool, riven, **kw):
        calls.append(riven)
        return SimpleNamespace(score=100., cards=(card,))

    monkeypatch.setattr(o, '_optimize', optimize)
    monkeypatch.setattr(o, 'proxy_seed_best', lambda weapon, pool, riven, best, **kw: best)
    monkeypatch.setattr(o, '_evaluate', lambda weapon, cards, riven, **kw:
                        SimpleNamespace(score=70., cards=cards))
    rows = o._assess_negatives({}, [card], SimpleNamespace(cards=(card,)), [], [(0., line)], {'F': line},
        frozenset(), scenario=None, metric='windowedDps', passives=None, capacity_limit=60,
        target_context={}, keep_cap=None, classification_only=True)
    assert calls == [False, False]
    assert not rows[0]['fatal'] and rows[0]['reoptimizedDeltaIsLowerBound']


def test_proof_uses_the_complete_reference_including_a_stronger_proxy_seed(monkeypatch):
    from types import SimpleNamespace
    line = o._RivenLine('F', 'F', 100., 80., 100., True, '%', None)
    monkeypatch.setattr(o, '_card_from_lines', lambda lines: bool(lines))
    monkeypatch.setattr(o, '_best_fixed_scores', lambda weapon, items, **kw:
                        [50. if card else 100. for _, card in items])
    calls = []

    def optimize(weapon, pool, riven, **kw):
        calls.append((riven, kw['profile']))
        return SimpleNamespace(score=100.)

    monkeypatch.setattr(o, '_optimize', optimize)
    monkeypatch.setattr(o, 'proxy_seed_best', lambda weapon, pool, riven, best, **kw:
                        SimpleNamespace(score=120. if riven else 200.))
    rows = o._assess_negatives({}, [], SimpleNamespace(cards=()), [], [(0., line)], {'F': line},
        frozenset(), scenario=None, metric='windowedDps', passives=None, capacity_limit=60,
        target_context={}, keep_cap=None, classification_only=True)
    assert (True, 'standard') in calls
    assert rows[0]['fatal'] and rows[0]['fatalAbove'] is None
    assert rows[0]['reoptimizedDelta'] == pytest.approx(-.4)
    assert 'reoptimizedDeltaIsLowerBound' not in rows[0]
