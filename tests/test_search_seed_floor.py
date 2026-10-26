"""Known legal scouts survive later shortlists, family collapse and fill rules."""
from types import SimpleNamespace
import pytest
from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario


def card(key, family=None):
    return o._Card(key, dict(modFamily=family or key), 0, (), (), 0, None)


@pytest.mark.parametrize('min_fill', [None, 2])
def test_seed_outside_shortlist_remains_a_floor(monkeypatch, min_fill):
    a, b, c = card('a', 'family'), card('b', 'family'), card('c')
    def score(_weapon, cards, _riven, **kwargs):
        keys = {c.key for c in cards}
        value = 1000 if keys == {'b', 'c'} else sum({'a':10, 'b':8, 'c':1}[k] for k in keys)
        return o._Evaluation(value, tuple(cards), SimpleNamespace(damage_types={}), 0, None, Scenario())
    monkeypatch.setattr(o, '_evaluate', score)
    monkeypatch.setattr('wfarsenal.parallel.get_pool', lambda: None)
    found = o._optimize({}, (a, b, c), None, scenario=Scenario(), metric='sustainedDps',
                        beam_width=1, shortlist=1, slot_count=2, seed_cards=(b,c),
                        profile='fast', min_fill=min_fill)
    assert found.score == 1000 and {c.key for c in found.cards} == {'b','c'}


def test_seed_does_not_duplicate_required_or_admit_forbidden_cards(monkeypatch):
    a, b, c = card('a'), card('b'), card('c')
    evaluated = []
    def score(_weapon, cards, _riven, **kwargs):
        keys = [c.key for c in cards]
        assert len(keys) == len(set(keys)) and 'c' not in keys
        evaluated.append(keys)
        return o._Evaluation(len(cards), tuple(cards), SimpleNamespace(damage_types={}), 0, None, Scenario())
    monkeypatch.setattr(o, '_evaluate', score)
    monkeypatch.setattr('wfarsenal.parallel.get_pool', lambda: None)
    found = o._optimize({}, (a,b,c), None, scenario=Scenario(), metric='sustainedDps',
        profile='fast', slot_count=2, seed_cards=(a,c,b), required_mod_keys=['a'], forbidden_mod_keys=['c'])
    assert {c.key for c in found.cards} == {'a','b'}
    assert any(keys == ['a','b'] for keys in evaluated)
