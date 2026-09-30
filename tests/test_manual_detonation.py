import pickle
from dataclasses import replace

import pytest
import app
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target
from tools.audit_optimizer_events import evaluate_payload


def talons():
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Talons')


def model(delay=0., batch=1, multishot=1.):
    sc = Scenario(detonation_delay_seconds=delay, detonation_batch_size=batch, trigger_policy='emergent')
    c = prepare(dict(weapon=talons(), fire_mode=0, effects=[], scenario=sc), [], [])
    st, _ = c['resolve']('selected', {})
    st = replace(st, crit_chance=0., status_chance=0., multishot=multishot)
    c['resolve'] = lambda *args: (st, None)
    return st, c


def run(window, **kw):
    st, c = model(**kw)
    return replay(st, target(), attacks_per_second=st.fire_rate, window_seconds=window, combat=c)


def test_wait_pays_ammo_but_does_not_damage_or_proc_before_detonation():
    before = run(.99, delay=1.)
    after = run(1.01, delay=1.)
    assert before['shots'] == 1 and before['totalWindowDamage'] == 0.
    assert not before['procCounts']
    assert before['manualDetonation']['pendingMines'] == 1.
    assert after['totalWindowDamage'] == pytest.approx(250.)
    assert after['manualDetonation']['events'][0]['time'] == 1.
    assert after['procCounts']['DT_PUNCTURE'] == 1.


def test_batch_trigger_occurs_after_last_throw_and_keeps_individual_status_events():
    assert run(1.29, delay=1., batch=2)['totalWindowDamage'] == 0.
    after = run(1.31, delay=1., batch=2)
    assert after['totalWindowDamage'] == pytest.approx(500.)
    event = after['manualDetonation']['events'][0]
    assert event['time'] == pytest.approx(1.3, abs=1e-6)
    assert event['expectedMines'] == 2.
    assert after['procCounts']['DT_PUNCTURE'] == 2.


def test_a_batch_cannot_damage_the_replacement_for_a_killed_target():
    st, c = model(delay=1., batch=2)
    result = replay(st, target(250.), attacks_per_second=st.fire_rate, window_seconds=1.31, combat=c)
    assert result['killEvents'] == 1 and result['totalWindowDamage'] == 250.
    assert result['manualDetonation']['events'][0]['staleMines'] == 1.


def test_projectile_capacity_forces_an_earlier_batch_without_extra_ammo_or_damage():
    result = run(2., delay=.5, batch=4, multishot=3.)
    assert result['manualDetonation']['events'][0]['expectedMines'] == 6.
    assert max(point['deployedMines'] for point in result['timeline']) <= 8.
    assert all(event['expectedMines'] <= 8. for event in result['manualDetonation']['events'])


def test_nondefault_cadence_is_in_the_shared_context_and_survives_worker_pickle():
    from wfarsenal import optimizer
    sc = optimizer._requested_scenario({'scenario':{'detonationBatchSize':2, 'detonationDelaySeconds':.5}}, 'killsPerMinute')
    assert pickle.loads(pickle.dumps(sc)) == sc
    assert not optimizer._default_analysis_scenario(sc, 'killsPerMinute')
    for params in ({'detonationBatchSize':0}, {'detonationBatchSize':True}, {'detonationDelaySeconds':-1.}):
        with pytest.raises(app.SimulationError):
            optimizer._requested_scenario({'scenario':params}, 'killsPerMinute')


def test_optimizer_manual_and_mod_removal_share_the_waiting_events():
    mod = next(m for m in app.MANUAL_MODS if m.get('nameEn') == 'Barrel Diffusion')
    request = dict(weapon=talons()['path'], fireMode=0, metric='killsPerMinute',
                   mods=[dict(path=mod['path'], rank=mod['maxRank'], slot=0)],
                   enemy=app._BENCHMARK_ENEMY_PATH, level=9999, steelPath=True,
                   scenario={'detonationDelaySeconds':.5, 'detonationBatchSize':2}, triggerPolicy='emergent')
    compared = evaluate_payload(request)
    assert compared['manual'] == pytest.approx(compared['optimizer'], rel=1e-10)
    removed = app.mod_gains_payload({**request, 'mode':'equipped', 'candidates':[mod['path']]})
    manual = app.simulate_manual_payload({**request, 'mods':[]})['benchmarkTimeline']['killsPerMinute']
    assert removed['gains'][mod['path']]['value'] == pytest.approx(manual, abs=.001)
    timeline=app.simulate_manual_payload(request)['benchmarkTimeline']
    assert timeline['manualDetonation']['delaySeconds']==.5
    assert timeline['manualDetonation']['batchSize']==2


def test_nested_trigger_policy_controls_manual_sources_as_well_as_scenario_parser():
    mod=next(m for m in app.MANUAL_MODS if m.get('nameEn')=='Galvanized Diffusion')
    request=dict(weapon=talons()['path'],fireMode=0,metric='killsPerMinute',
                 mods=[dict(path=mod['path'],rank=mod['maxRank'],slot=0)],
                 enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,
                 triggerPolicy='emergent',scenario={'triggerPolicy':'assumed_max'})
    result=app.simulate_manual_payload(request)
    assert result['benchmarkTimeline']['triggerPolicy']=='assumed_max'
    compared=evaluate_payload(request)
    assert compared['manual']==pytest.approx(compared['optimizer'],rel=1e-10)
