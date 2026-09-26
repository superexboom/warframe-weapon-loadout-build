from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import pytest
import app
from wfarsenal.damage import (Scenario, ModEffect, apply_mods, arcane_effects,
                              expected_status_procs, expected_status_damage)
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload
from tests.test_combat_replay import stats, target

def raw(group, name):
    return next(r for r in app.EXPORTS[group] if r.get('nameEn') == name)

@pytest.mark.parametrize('base',[.05,.2,.5])
def test_crux_is_additive_with_relative_mods_not_flat_chance(base):
    weapon=deepcopy(raw('weapons','Lato'))
    weapon['fireModes'][0]['damage']['procChance']=base
    fx=[ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',.6),
        *arcane_effects(raw('arcanes','Primary Crux'),rank=5,stacks=10)]
    result=apply_mods(weapon,fx)
    assert result.status_chance==pytest.approx(base*(1+.6+3))
    assert result.ammo_cost==pytest.approx(.4)

@pytest.mark.parametrize('ms',[1,2,2.5,3.1])
def test_beam_seeds_weight_each_integer_multishot_roll(ms):
    st=stats(continuous=True,multishot=ms,crit_chance=0)
    normal=expected_status_damage(replace(st,continuous=False),target())
    beam=expected_status_damage(st,target())
    low=int(ms);fraction=ms-low
    second=(1-fraction)*low**2+fraction*(low+1)**2
    assert beam['expectedProcs']['DT_FIRE']==pytest.approx(ms)
    a=beam['dot']['perType']['DT_FIRE']['seedPerSecondPerProc']
    b=normal['dot']['perType']['DT_FIRE']['seedPerSecondPerProc']
    assert a/b==pytest.approx(second/ms)
    independent=replace(st,status_chance=0,independent_proc_chances={'DT_FIRE':.3})
    assert expected_status_procs(independent)['DT_FIRE']==pytest.approx(.3)
    assert expected_status_damage(independent,target())['dot']['perType']['DT_FIRE']['seedPerSecondPerProc']/b==pytest.approx(ms)

def test_beam_hit_buffs_count_one_instance_not_merged_pellets():
    source=dict(id='hit',label='hit',kind='on-hit',maxStacks=100,duration=10,perEvent=1)
    result=replay(stats(multishot=4,continuous=True),target(),attacks_per_second=10,
                  window_seconds=.5,trigger_sources=[source])
    assert result['timeline'][-1]['triggerStacks']['hit']==5

def test_slash_seed_uses_modified_base_and_ignores_physical_share():
    st=stats(damage_types={'DT_SLASH':10,'DT_IMPACT':90},dot_base_damage=100,status_chance=0)
    probe=expected_status_damage(st,target(),forced_procs={'DT_SLASH':1})
    assert probe['dot']['perType']['DT_SLASH']['seedPerSecondPerProc']==pytest.approx(35)
    other=replace(st,damage_types={'DT_SLASH':90,'DT_IMPACT':10})
    assert expected_status_damage(other,target(),forced_procs={'DT_SLASH':1})['dot']['perType']['DT_SLASH']['seedPerSecondPerProc']==pytest.approx(35)

def test_conditional_gunco_arms_after_kill_with_zero_initial_bucket():
    weapon=raw('weapons','Lato');mod=raw('mods','Galvanized Shot')
    from wfarsenal.damage import mod_effects
    sc=Scenario(trigger_policy='emergent')
    effects=mod_effects(mod,mod['maxRank'],sc)
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=sc),[(mod,mod['maxRank'],None)],[])
    assert combat['conditionOverload']
    assert any(s['kind']=='on-kill' for s in combat['trigger_sources'])
    active={s['id']:s['maxStacks'] for s in combat['trigger_sources']}
    zero=combat['resolve']('selected',active,0)[0]
    live=combat['resolve']('selected',active,3)[0]
    assert live.total_damage > zero.total_damage
    assert live.dot_base_damage==pytest.approx(zero.dot_base_damage)

@pytest.mark.parametrize('pool',['overguard','shield'])
def test_magnetic_break_emits_six_pool_based_electric_ticks(pool):
    tg=target();tg[pool]=500
    st=stats(damage_types={'DT_MAGNETIC':100},status_chance=1,fire_rate=1,proc_damage_multiplier=2)
    result=replay(st,tg,attacks_per_second=1,window_seconds=9,level=1)
    events=result['magneticBreaks']
    assert len(events)==1 and events[0]['pool']==pool
    assert events[0]['stacks']==2
    assert events[0]['seedPerTick']==pytest.approx(500*.03*2*4/6)
    assert result['dotByType']['DT_ELECTRICITY']==pytest.approx(500*.03*2*4)

def test_battery_recharge_is_not_a_reload_trigger():
    weapon=raw('weapons','Tenet Cycron');sc=Scenario(trigger_policy='emergent')
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=sc),[],[])
    st=combat['resolve']('selected',{},0)[0]
    assert st.reload_time==pytest.approx(1.5)
    source=dict(id='reload',label='reload',kind='on-reload',maxStacks=100,duration=100,perEvent=1)
    result=replay(st,target(),attacks_per_second=12,window_seconds=30,combat=combat,trigger_sources=[source])
    assert result['recharges']>0 and result['reloads']==0
    assert result['timeline'][-1]['triggerStacks']['reload']==0

def community_cases():
    return [c for c in json.loads((Path(__file__).parent/'fixtures/nonmelee_board_20260926.json').read_text(encoding='utf-8'))['cases'] if not c['catalogBlockers']]

@pytest.mark.parametrize('case',community_cases(),ids=lambda c:c['id'])
def test_community_manual_and_search_share_mechanics(case):
    result=evaluate_payload(case['manualPayload'])
    assert result['manual']>0
    assert result['optimizer']==pytest.approx(result['manual'],rel=1e-9)


def test_enervate_explicit_stack_count_survives_manual_and_search_context():
    a=raw('arcanes','Secondary Enervate');w=raw('weapons','Lato')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=a['path'],rank=5,stacks=12)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    ctx=app._manual_resolve_sim_context(p)
    assert ctx['validated_arcanes'][0]['stacks']==12
    scores=evaluate_payload(p)
    assert scores['optimizer']==pytest.approx(scores['manual'],rel=1e-9)


def test_crux_removal_contribution_uses_the_shared_relative_bucket():
    fixture=community_cases()
    p=next(c['manualPayload'] for c in fixture if c['id']=='baza_prime-116')
    key='__arcane__:'+p['arcanes'][0]['path']
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains'][key]['value']==pytest.approx(without,abs=.001)
    assert gains['baseValue']>without


def test_gas_payload_ignores_component_mods_but_accepts_literal_gas():
    from wfarsenal.damage import _dot_elemental_multipliers
    fx=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',1.65,damage_type='DT_FIRE'),
        ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.6,damage_type='DT_POISON')]
    multipliers=_dot_elemental_multipliers(fx,[])
    assert multipliers['DT_GAS']==1
    assert multipliers['DT_FIRE']==pytest.approx(2.65)
    fx.append(ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',3,damage_type='DT_GAS'))
    assert _dot_elemental_multipliers(fx,[])['DT_GAS']==4
