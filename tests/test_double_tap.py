from copy import deepcopy

import pytest
import app
from wfarsenal.consecutive_hits import ConsecutiveHits
from wfarsenal.runtime_adapters import double_tap_configuration
from wfarsenal.damage import Scenario,ModEffect,mod_effects
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def card():
    return next(m for m in app.EXPORTS['mods'] if m['nameEn']=='Double Tap')


@pytest.mark.parametrize('rank,bonus,cap,duration',[(0,.05,80,.5),(1,.1,40,1.),(2,.15,26,1.5),(3,.2,20,2.)])
def test_double_tap_uses_native_rank_scaled_cap_and_duration(rank,bonus,cap,duration):
    assert double_tap_configuration(card(),rank)==pytest.approx(dict(perHit=bonus,maximum=cap,duration=duration))
    effects=mod_effects(card(),rank)
    assert effects and not effects.skipped


def test_three_pellet_worked_example_and_expiry():
    state=ConsecutiveHits(.2,20,2)
    assert [state.shot(t,3) for t in (0,.5,1.)]==pytest.approx([1.4,2.,2.6])
    assert state.shot(3.1,1)==1.
    assert state.shot(3.2,0)==1. and state.hits==0


def test_form_snapshots_suspend_only_the_other_forms_remaining_clock():
    state=ConsecutiveHits(.2,20,2)
    state.shot(0.,4)
    state.swap(1.)
    assert state.shot(20.,2)==pytest.approx(1.2)
    state.swap(20.5)
    assert state.shot(20.6,1)==pytest.approx(1.8)
    state.swap(20.7)
    assert state.shot(21.,2)==pytest.approx(1.6)


@pytest.mark.parametrize('mode,first,second,radial_only',[(0,1.4,2.,False),(1,2.,3.2,True)])
def test_shared_replay_counts_the_current_projectiles_and_buffs_only_incarnon_radial(mode,first,second,radial_only):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Latron Prime'))
    weapon['isIncarnonForm']=bool(mode)
    effects=[*mod_effects(card(),3),ModEffect('WEAPON_FIRE_ITERATIONS','SET',3.)]
    combat=prepare(dict(weapon=weapon,fire_mode=mode,scenario=Scenario(),effects=effects),[(card(),3,None)],[])
    stats,_=combat['resolve']('selected',{},0)
    result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=.5,combat=combat)
    rows=result['doubleTap']['events']
    assert rows[0]['multiplier']==pytest.approx(first)
    assert rows[1]['multiplier']==pytest.approx(second)
    assert rows[0]['radialOnly']==radial_only


def test_unknown_script_parameters_do_not_receive_double_tap_semantics():
    changed=deepcopy(card())
    changed['runtimeScripts']['apply']['_multTimeWindow']=2
    assert double_tap_configuration(changed,3) is None


def test_pve_double_tap_is_in_optimizer_pool_but_other_conclave_cards_stay_out():
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Latron Prime')
    selected,_=app.optimizer._select_fire_mode(weapon,0,weapon_type='rifle')
    candidates,_=app.optimizer._candidate_mods(app.EXPORTS,selected,Scenario())
    pvp=[c for c in candidates if '/PvPMods/' in c.record.get('path','')]
    assert [c.record['path'] for c in pvp]==[card()['path']]


def test_equipped_mod_contribution_uses_the_runtime_model():
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Latron Prime')
    payload=dict(weapon=weapon['path'],fireMode=0,mods=[dict(path=card()['path'],rank=3,slot=0)],
                 enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1.,aiming=True,
                 mode='equipped',candidates=[card()['path']],metric='killsPerMinute',slotPolarities=['AP_ATTACK']+[None]*7)
    result=app.mod_gains_payload(payload)
    gain=result['gains'][card()['path']]
    assert gain['gainPercent'] is not None and gain['gainPercent']<0
