from copy import deepcopy
from dataclasses import replace
import math
import pytest
import app
from tests.test_combat_replay import stats,target
from wfarsenal.combat_replay import replay
from wfarsenal.status_arcanes import configuration,encumber_roll,ENCUMBER,FORTIFIER,STATUS_POOL
from tools.audit_optimizer_events import evaluate_payload

def raw(path):return next(r for r in app.EXPORTS['arcanes'] if r['path']==path)

@pytest.mark.parametrize('rank',range(6))
def test_rank_and_signature(rank):
    assert configuration(raw(ENCUMBER),rank)['chance']==pytest.approx(.04*(rank+1))
    assert configuration(raw(FORTIFIER),rank)['multiplier']==3+rank
    bad=deepcopy(raw(FORTIFIER));bad['runtimeScripts']['apply']['_overguardSteal']=.1
    assert configuration(bad,rank) is None

@pytest.mark.parametrize('sc',[0,.1,.8,1,2.5])
@pytest.mark.parametrize('ms',[1,2,2.5,4])
def test_encumber_integer_multishot_and_cap(sc,ms):
    st=stats(status_chance=sc,multishot=ms)
    n=int(ms);f=ms-n;q=1-.24*min(sc,1)
    p,seed=encumber_roll(st,.24)
    assert p==pytest.approx(1-((1-f)*q**n+f*q**(n+1)))
    assert 0<=p<=1 and seed==1

def test_encumber_beam_is_one_merged_instance():
    st=stats(status_chance=.5,multishot=2.5,continuous=True)
    assert encumber_roll(st,.24)==pytest.approx((.24,2.5))
    assert encumber_roll(replace(st,status_chance=0),.24)[0]==0
    assert encumber_roll(replace(st,status_chance=0),.24,{'DT_IMPACT':1})[0]==pytest.approx(.24)

def test_fortifier_only_overguard_actual_drain_and_no_spill_buff():
    st=stats(damage_types={'DT_IMPACT':100},status_chance=0,crit_chance=0,fire_rate=1)
    tg=target();tg['overguard']=400
    r=replay(st,tg,attacks_per_second=1,window_seconds=.1,combat={'fortifier':configuration(raw(FORTIFIER),5)})
    assert r['fortifier']['overguardDamage']==pytest.approx(400)
    assert r['fortifier']['selfOverguard']==pytest.approx(4)
    assert r['directWindow']==pytest.approx(450)
    tg['overguard']=0
    a=replay(st,tg,attacks_per_second=1,window_seconds=.1)
    b=replay(st,tg,attacks_per_second=1,window_seconds=.1,combat={'fortifier':configuration(raw(FORTIFIER),5)})
    assert a['directWindow']==pytest.approx(b['directWindow'])

def test_fortifier_dot_once_and_self_cap():
    tg=target();tg['overguard']=1e12
    st=stats(damage_types={'DT_SLASH':100},status_chance=1,crit_chance=0,fire_rate=1)
    a=replay(st,tg,attacks_per_second=1,window_seconds=5)
    b=replay(st,tg,attacks_per_second=1,window_seconds=5,combat={'fortifier':configuration(raw(FORTIFIER),5)})
    assert b['dotWindow']==pytest.approx(a['dotWindow']*8)
    huge=replace(st,damage_types={'DT_IMPACT':1e8},status_chance=0)
    c=replay(huge,tg,attacks_per_second=1,window_seconds=.1,combat={'fortifier':configuration(raw(FORTIFIER),5)})
    assert c['fortifier']['selfOverguard']==15000

def test_encumber_shared_instant_budget_and_no_recursion():
    st=stats(status_chance=1,multishot=2,crit_chance=0)
    combat={'encumber':configuration(raw(ENCUMBER),5),'resolve':lambda *args:(st,st)}
    r=replay(st,target(),attacks_per_second=1,window_seconds=.1,combat=combat)
    expected=1-.76**4
    assert r['encumber']['expectedExtraProcs']==pytest.approx(expected)
    assert r['procCounts']['DT_POISON']==pytest.approx(expected/13)
    assert r['procCounts']['DT_FIRE']==pytest.approx(4+expected/13)

@pytest.mark.parametrize('name,path',[('Aksomati Prime',ENCUMBER),('Tenet Cycron',FORTIFIER)])
def test_manual_optimizer_and_catalog(name,path):
    assert path in app.MANUAL_ARCANES_BY_PATH
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    payload=dict(weapon=w['path'],fireMode=0,mods=[],arcanes=[dict(path=path,rank=5)],
                 enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,
                 headshotChance=1,aiming=True,triggerPolicy='emergent',slotPolarities=[None]*8)
    r=evaluate_payload(payload)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    assert not any('arcane-state' in reason for reason in r['manualUnsupported'])

@pytest.mark.parametrize('path',[ENCUMBER,FORTIFIER])
def test_arcane_contribution_same_event_path(path):
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Aksomati Prime')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=path,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    key='__arcane__:'+path
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains'][key]['value']==pytest.approx(without,abs=.001)
    assert gains['baseValue']>without

def test_encumber_zero_uptime_is_equivalent_to_removal():
    st=stats(status_chance=1,fire_rate=1)
    a=replay(st,target(),attacks_per_second=1,window_seconds=3,combat={'encumber':{**configuration(raw(ENCUMBER),5),'uptime':0}})
    b=replay(st,target(),attacks_per_second=1,window_seconds=3,combat={'unused':True})
    assert a['procCounts']==b['procCounts']
    assert a['totalWindowDamage']==pytest.approx(b['totalWindowDamage'])

@pytest.mark.parametrize('name,base,status',[('Kohm',30,.75),('Kuva Kohm',20,.9)])
def test_spooling_raw_fields_reach_panel_and_events(name,base,status):
    from wfarsenal.damage import Scenario,apply_mods
    from wfarsenal.manual_combat import prepare
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    st=apply_mods(w,[])
    assert st.total_damage==pytest.approx(base)
    assert st.multishot==12
    assert st.status_chance==pytest.approx(status/12)
    assert st.ammo_cost==4
    combat=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    result=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=8,combat=combat)
    trace=result['spoolTrace']
    assert [r['pellets'] for r in trace[:12]]==list(range(1,13))
    assert trace[0]['ammoCost']==1 and trace[11]['ammoCost']==4
    assert trace[0]['fireRate']==pytest.approx(st.fire_rate*.2)
    assert trace[8]['fireRate']==pytest.approx(st.fire_rate)

def test_shotgun_galvanized_kill_conditions():
    from wfarsenal.damage import Scenario,mod_effects
    from wfarsenal.manual_combat import prepare
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Kohm')
    mods=[next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==n) for n in ('Galvanized Hell','Galvanized Savvy')]
    sc=Scenario(trigger_policy='emergent')
    effects=[e for m in mods for e in mod_effects(m,m['maxRank'],sc)]
    c=prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=sc),[(m,m['maxRank'],None) for m in mods],[])
    assert not c['unsupported']
    assert len(c['trigger_sources'])==2
    assert all(x['kind']=='on-kill' for x in c['trigger_sources'])
    base=c['resolve']('selected',{},3)[0]
    live=c['resolve']('selected',{q['id']:q['maxStacks'] for q in c['trigger_sources']},3)[0]
    assert live.multishot>base.multishot and live.total_damage>base.total_damage

@pytest.mark.parametrize('name,wpname',[('Repeater Clip','Kohm'),('Pressurized Magazine','Lato'),('Spring-Loaded Chamber','Braton Prime')])
def test_reload_rate_buff_begins_on_completion_with_rank_duration(name,wpname):
    from wfarsenal.damage import Scenario,mod_effects,apply_mods
    from wfarsenal.manual_combat import prepare
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==wpname))
    w['magazineSize']=1;w['fireModes'][0]['reloadTime']=2
    w['fireModes'][0]['fireRate']=5
    m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==name)
    sc=Scenario(aiming=True,trigger_policy='emergent')
    fx=mod_effects(m,m['maxRank'],sc)
    c=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[(m,m['maxRank'],None)],[])
    q=c['trigger_sources'][0]
    assert q['duration']==9 and q['kind']=='on-reload-complete'
    r=replay(apply_mods(w,fx,scenario=sc),target(),attacks_per_second=5,window_seconds=4,combat=c,trigger_sources=c['trigger_sources'])
    assert all(p['triggerStacks'][q['id']]==0 for p in r['timeline'] if p['time']<2)
    assert any(p['triggerStacks'][q['id']]>0 for p in r['timeline'] if p['time']>3)

def test_encumber_fractional_status_presence_does_not_grant_thirteen_full_types():
    from wfarsenal.damage import Scenario,mod_effects
    from wfarsenal.manual_combat import prepare
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Lato')
    m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Galvanized Shot')
    sc=Scenario(trigger_policy='emergent');fx=mod_effects(m,m['maxRank'],sc)
    c=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[(m,m['maxRank'],None)],[])
    stacks={q['id']:q['maxStacks'] for q in c['trigger_sources']}
    a=c['resolve']('selected',stacks,0)[0]
    b=c['resolve']('selected',stacks,.1)[0]
    d=c['resolve']('selected',stacks,1)[0]
    assert b.total_damage-a.total_damage==pytest.approx((d.total_damage-a.total_damage)*.1)
    assert a.dot_base_damage==b.dot_base_damage==d.dot_base_damage

def _board_cases():
    from pathlib import Path
    import json
    return json.loads((Path(__file__).parent/'fixtures/status_arcane_board_20260926.json').read_text(encoding='utf-8'))['cases']

@pytest.mark.parametrize('case',_board_cases(),ids=lambda c:c['id'])
def test_complete_community_builds_use_shared_score(case):
    p=case['manualPayload'];r=evaluate_payload(p)
    assert r['manual']>0
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-9)
    assert not any('arcane-state' in reason for reason in r['manualUnsupported'])

@pytest.mark.parametrize('path',[ENCUMBER,FORTIFIER])
def test_explicit_zero_stacks_disables_event_arcane(path):
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Aksomati Prime')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=path,rank=5,stacks=0)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    with_zero=app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert with_zero==pytest.approx(without,rel=1e-10)
    assert evaluate_payload(p)['optimizer']==pytest.approx(without,rel=1e-10)


@pytest.mark.parametrize('name,pellets,status,ratio', [
    ('Kohm',12,.75,8/15),('Kuva Kohm',12,.9,1/10),
    ('Kohmak',5,.69,5/15),('Twin Kohmak',5,.69,5/15),
])
def test_spooling_falloff_preserves_raw_ratio(name,pellets,status,ratio):
    from wfarsenal.damage import Scenario,apply_mods
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    before=deepcopy(w)
    near=apply_mods(w,[],scenario=Scenario(distance=0))
    far=apply_mods(w,[],scenario=Scenario(distance=100))
    assert near.multishot==pellets
    assert near.status_chance==pytest.approx(status/pellets)
    assert far.falloff_multiplier==pytest.approx(ratio)
    assert far.total_damage==near.total_damage
    assert w==before

def test_slow_held_trigger_does_not_reset_spool_as_idle():
    from wfarsenal.damage import Scenario,apply_mods
    from wfarsenal.manual_combat import prepare
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Kohm'))
    w['fireModes'][0]['fireRate']=.5
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    st=apply_mods(w,[])
    result=replay(st,target(),attacks_per_second=.5,window_seconds=20,combat=c)
    assert [p['pellets'] for p in result['spoolTrace']]==[1,2,3]

def test_known_event_diagnostic_does_not_hide_unknown_trigger_or_script():
    from wfarsenal.manual_combat import modeled_event_kinds
    flare=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Cascadia Flare')
    assert modeled_event_kinds(flare,5)==('proc-DT_FIRE',)
    changed=deepcopy(flare)
    changed['conditionalEffects'][0]['runtimeScripts']={'apply':'unverified.lua'}
    assert modeled_event_kinds(changed,5)==()
    changed=deepcopy(flare)
    changed['conditionalEffects'][0]['conditions']=['UnknownCondition']
    assert modeled_event_kinds(changed,5)==()
    changed=deepcopy(flare)
    changed['conditionalEffects'][0]['effects'][0]['upgradeType']='UNVERIFIED_UPGRADE'
    assert modeled_event_kinds(changed,5)==()
