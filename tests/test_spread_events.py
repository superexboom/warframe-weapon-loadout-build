from copy import deepcopy
from dataclasses import replace
import math
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, apply_mods, mod_effects, spread_hit_probability
from wfarsenal.event_profiles import base_profile
from wfarsenal.combat_replay import replay
from wfarsenal.manual_combat import prepare
from wfarsenal.status_arcanes import encumber_roll
from tests.test_combat_replay import stats,target
from tools.audit_optimizer_events import evaluate_payload

def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)

@pytest.mark.parametrize('distance',[None,0,.25,.5])
def test_contact_and_unspecified_distance_preserve_all_hit(distance):
    assert spread_hit_probability(stats(spread_min_deg=15),distance)==1

def test_uniform_angle_geometry_and_zero_spread():
    st=stats(spread_min_deg=10)
    expected=math.degrees(math.asin(.25/9.75))/10
    assert spread_hit_probability(st,10)==pytest.approx(expected)
    assert spread_hit_probability(st,30)<expected
    assert spread_hit_probability(replace(st,spread_min_deg=0),100)==1

@pytest.mark.parametrize('name,card,base,delta',[('Baza Prime','Heavy Caliber',1.,2.97000011),('Akstiletto Prime','Magnum Force',1.5,5.5)])
def test_native_spread_add_is_degrees_and_rank_scales(name,card,base,delta):
    w=weapon(name);m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==card)
    for rank in (0,m['maxRank']):
        sc=Scenario(aiming=True,distance=10)
        st=apply_mods(w,mod_effects(m,rank,sc),scenario=sc)
        assert st.spread_min_deg==pytest.approx(base+delta*(rank+1)/(m['maxRank']+1))
        if rank>0:assert spread_hit_probability(st,10)<1

def test_aim_hip_and_operations_respect_native_qualifiers():
    w=weapon('Baza Prime')
    fx=[ModEffect('WEAPON_SPREAD','STACKING_MULTIPLY',.5),ModEffect('WEAPON_SPREAD','ADD',2),ModEffect('WEAPON_SPREAD','ADD',100,valid_type='/another-weapon')]
    assert apply_mods(w,fx,scenario=Scenario(aiming=True)).spread_min_deg==pytest.approx(3.5)
    assert apply_mods(w,fx,scenario=Scenario(aiming=False)).spread_min_deg==pytest.approx(5.)
    assert apply_mods(w,[ModEffect('WEAPON_SPREAD','SET',-1)],scenario=Scenario(aiming=True)).spread_min_deg==0

def test_profiles_reject_other_form_mode_and_changed_damage():
    w=deepcopy(weapon('Baza Prime'))
    assert base_profile(w).get('spreadAim')
    assert not base_profile({**w,'isIncarnonForm':True})
    assert not base_profile({**w,'__selectedFireMode__':1})
    w['fireModes'][0]['damage']['types']={'DT_IMPACT':999}
    assert not base_profile(w)
    assert not base_profile(weapon('Lenz')).get('spreadAim')

def test_misses_thin_damage_and_procs_once_without_reducing_ammo_or_fire_events():
    st=stats(damage_types={'DT_SLASH':100.},status_chance=1,spread_min_deg=10,fire_rate=2,magazine=2)
    sources=[dict(id=k,label=k,kind=k,maxStacks=10000,perEvent=1,duration=30) for k in ('on-fire','on-hit','on-headshot')]
    def run(distance):
        return replay(st,target(),attacks_per_second=2,window_seconds=5,headshot_chance=0,combat={'resolve':lambda *a:(st,None),'distance':distance},trigger_sources=sources)
    all_hit=run(0);spread=run(10);p=spread_hit_probability(st,10)
    assert all_hit['shots']==spread['shots'] and all_hit['reloads']==spread['reloads']>0
    assert spread['directWindow']==pytest.approx(all_hit['directWindow']*p)
    assert spread['dotWindow']==pytest.approx(all_hit['dotWindow']*p)
    assert spread['procCounts']['DT_SLASH']==pytest.approx(all_hit['procCounts']['DT_SLASH']*p)
    a=all_hit['timeline'][-1]['triggerStacks'];b=spread['timeline'][-1]['triggerStacks']
    assert a['on-fire']==b['on-fire']==all_hit['shots']
    assert b['on-hit']==pytest.approx(a['on-hit']*p)

@pytest.mark.parametrize('ms',[1,2,2.5,4])
@pytest.mark.parametrize('landing',[0,.2,.8,1])
def test_encumber_multishot_landing_occurs_before_one_success_cap(ms,landing):
    st=stats(status_chance=.8,multishot=ms)
    n=int(ms);f=ms-n;q=1-.24*.8*landing
    expected=1-((1-f)*q**n+f*q**(n+1))
    assert encumber_roll(st,.24,hit_probability=landing)[0]==pytest.approx(expected)

def test_encumber_single_forced_proc_and_merged_beam_share_landing():
    st=stats(status_chance=0,multishot=3)
    assert encumber_roll(st,.24,{'DT_IMPACT':1},hit_probability=.2)[0]==pytest.approx(.24*.2)
    assert encumber_roll(replace(st,continuous=True,status_chance=1),.24,hit_probability=.2)==pytest.approx((.24*.2,3))

@pytest.mark.parametrize('name,card',[('Baza Prime','Heavy Caliber'),('Akstiletto Prime','Magnum Force')])
def test_manual_optimizer_and_contribution_share_distance_and_spread(name,card):
    w=weapon(name);m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==card)
    p=dict(weapon=w['path'],fireMode=0,mods=[dict(path=m['path'],rank=m['maxRank'],slot=0)],enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent',slotPolarities=[m['polarity']]+[None]*7,scenario={'distance':10})
    r=evaluate_payload(p)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    actual=app.simulate_manual_payload(p)
    assert actual['benchmarkTimeline']['spread']['initialHitProbability']<1
    assert 'spread-bloom-not-modeled' in actual['benchmarkTimeline']['limitations']
    without=app.simulate_manual_payload({**p,'mods':[]})['benchmarkTimeline']['killsPerMinute']
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[m['path']]})
    assert gains['gains'][m['path']]['value']==pytest.approx(without,abs=.001)

def test_missing_distance_is_visible_and_talons_missing_native_status_uses_provenance():
    w=weapon('Baza Prime');c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    assert 'spread-distance-unspecified-assumed-all-hit' in c['unsupported']
    t=deepcopy(weapon('Talons'));t['fireModes'][0]['damage']['procChance']=0
    assert apply_mods(t,[]).status_chance==pytest.approx(.1)
    t['path']='/unknown'
    assert apply_mods(t,[]).status_chance==0


def test_tiberon_native_three_round_clock_is_used():
    w=weapon('Tiberon');c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(distance=10,aiming=True)),[],[])
    st,_=c['resolve']('selected',{})
    assert c['baseBurst']['count']==3
    assert c['baseBurst']['delay_seconds']==pytest.approx(.06)
    st=replace(st,crit_chance=0,status_chance=0,fire_rate=20/3)
    c['resolve']=lambda *a:(st,None)
    r=replay(st,target(),attacks_per_second=20/3,window_seconds=.269,combat=c)
    assert r['shots']==3
    r=replay(st,target(),attacks_per_second=20/3,window_seconds=.271,combat=c)
    assert r['shots']==4
    c['baseBurst']=None
    flat=replay(st,target(),attacks_per_second=20/3,window_seconds=.271,combat=c)
    assert flat['shots']==2
