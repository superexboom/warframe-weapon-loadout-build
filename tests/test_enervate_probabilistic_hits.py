"""Rare proc events cannot deterministically suppress the next crit reset."""
from collections import defaultdict
import json, math
from pathlib import Path
import pytest
import app
from wfarsenal.enervate import EnervateState, configuration, PATH
from wfarsenal import combat_replay, native_replay


def state():
    record=next(a for a in app.EXPORTS['arcanes'] if a['path']==PATH)
    return EnervateState(configuration(record,0))


def test_rare_hit_only_consumes_cooldown_in_the_branch_where_it_happens():
    s=state()
    s.advance(0.,event_probability=.01)
    s.advance(.01,{0:1.,1:1.})
    assert s.states==pytest.approx({(1,0):.01,(0,0):.99})
    assert s.resets==pytest.approx(.99)
    assert s.hits==pytest.approx(1.)


def test_probability_clocks_match_independent_exhaustive_event_tree():
    s=state();branches=[(0,0,-math.inf,1.)]
    events=[(0.,.2,False),(.01,1.,True),(.04,.3,False),(.055,1.,True),(.08,.7,False)]
    for time,probability,crit in events:
        s.advance(time,{k:float(crit) for k in s.marginal()},event_probability=probability)
        following=[]
        for stacks,big,last,mass in branches:
            if time-last < 1/30-1e-9:
                following.append((stacks,big,last,mass));continue
            if probability<1:following.append((stacks,big,last,mass*(1-probability)))
            following.append((0 if crit else stacks+1,0,time,mass*probability))
        branches=following
        expected=defaultdict(float)
        for stacks,big,last,mass in branches:expected[stacks,big]+=mass
        assert s.states==pytest.approx(dict(expected),abs=1e-14)
    assert sum(s.states.values())==pytest.approx(1.)


def test_zero_probability_hit_does_not_modify_state_or_clock():
    s=state();s.advance(0.)
    before=(dict(s.states),s.last,s.hits,s.resets)
    s.advance(.04,event_probability=0.)
    assert (s.states,s.last,s.hits,s.resets)==before


def test_old_native_core_falls_back_for_correct_enervate_semantics(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace(ABI=1))
    monkeypatch.setattr(native_replay,'ENABLED',True)
    assert native_replay.supported(None,dict(collect_timeline=False,
        combat=dict(resolve=lambda:None,enervate=dict(resetAfter=6)))) is False


def test_real_blast_build_native_python_and_display_agree(monkeypatch):
    payload=json.loads((Path(__file__).parent/'fixtures/enervate_blast_cycron.json').read_text(encoding='utf-8'))
    display=app.simulate_manual_payload(payload)['benchmarkTimeline']
    assert 2. < display['killsPerMinute'] < 3.  # Before: 20.1088 from phantom cooldown hits.
    original=combat_replay.replay
    def native(*args,**kw):
        return original(*args,**dict(kw,collect_timeline=False))
    monkeypatch.setattr(combat_replay,'replay',native)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    calculated=app.simulate_manual_payload(payload)['benchmarkTimeline']
    assert native_replay.STATS['native']>before
    for key in ['killsPerMinute','totalWindowDamage','shots','reloads']:
        assert calculated[key]==display[key]
