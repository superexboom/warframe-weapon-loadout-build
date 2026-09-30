from copy import deepcopy
from dataclasses import replace
import json,math
from pathlib import Path
import pytest
import app
from wfarsenal.damage import ModEffect,Scenario,apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.event_profiles import base_profile
from tests.test_combat_replay import stats,target
from tools.audit_optimizer_events import evaluate_payload

def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)


def test_deferred_math_retained_but_not_referenced_by_production():
    from wfarsenal.deferred_spread import spread_hit_probability,resolved_angles
    st=stats(spread_min_deg=10)
    assert spread_hit_probability(st,10)==pytest.approx(math.degrees(math.asin(.25/9.75))/10)
    from wfarsenal.deferred_spread import encumber_roll_with_misses
    assert encumber_roll_with_misses(stats(multishot=2,status_chance=1),.24,hit_probability=.5)[0]==pytest.approx(1-(1-.12)**2)
    profiles=json.loads((app.ROOT/'data/mechanics/deferred-spread-profiles.json').read_bytes())['profiles']
    profile=profiles[weapon('Baza Prime')['path']]
    assert resolved_angles(profile,[ModEffect('WEAPON_SPREAD','ADD',2)],aiming=True)==(3.,3.5)

@pytest.mark.parametrize('name',['Baza Prime','Akstiletto Prime','Supra Vandal','Hema'])
@pytest.mark.parametrize('aiming',[False,True])
def test_spread_only_effects_do_not_change_replay_damage_procs_or_triggers(name,aiming):
    sc=Scenario(aiming=aiming,distance=10,trigger_policy='emergent');w=weapon(name)
    def run(effects):
        c=prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=sc),[],[])
        st,_=c['resolve']('selected',{})
        assert st.spread_min_deg is None and st.spread_max_deg is None
        return replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=4,headshot_chance=1)
    a=run([]);b=run([ModEffect('WEAPON_SPREAD','ADD',50),ModEffect('WEAPON_SPREAD','STACKING_MULTIPLY',5)])
    for key in ('totalWindowDamage','procCounts','shots','reloads','killsPerMinute'):assert a[key]==b[key]
    assert 'spread' not in b and 'spread-hit-loss-not-modeled' in b['limitations']

def test_even_injected_old_geometry_fields_do_not_thin_events():
    st=stats(fire_rate=2);kw=dict(attacks_per_second=2,window_seconds=3,combat={'distance':100})
    a=replay(st,target(),**kw);b=replay(replace(st,spread_min_deg=80,spread_max_deg=90),target(),**kw)
    assert a['totalWindowDamage']==b['totalWindowDamage'] and a['procCounts']==b['procCounts']

@pytest.mark.parametrize('name,card',[('Baza Prime','Heavy Caliber'),('Akstiletto Prime','Magnum Force')])
def test_manual_optimizer_contribution_share_non_spread_model(name,card):
    m=next(m for m in app.MANUAL_MODS if m.get('nameEn')==card)
    p=dict(weapon=weapon(name)['path'],fireMode=0,metric='killsPerMinute',mods=[dict(path=m['path'],rank=m['maxRank'],slot=0)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,scenario={'distance':10},triggerPolicy='emergent')
    r=evaluate_payload(p);assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    g=app.mod_gains_payload({**p,'mode':'equipped','candidates':[m['path']]})
    without=app.simulate_manual_payload({**p,'mods':[]})['benchmarkTimeline']['killsPerMinute']
    assert g['gains'][m['path']]['value']==pytest.approx(without,abs=.001)
    assert 'spread' not in app.simulate_manual_payload(p)['benchmarkTimeline']


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


@pytest.mark.parametrize('rate_bonus,edge',[(0,.4),(1,.2)])
def test_hema_native_burst_has_three_paid_rounds_before_next_pull(rate_bonus,edge):
    w=weapon('Hema');sc=Scenario(aiming=True,distance=10)
    fx=[ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',rate_bonus),ModEffect('WEAPON_CRIT_CHANCE','SET',0),ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    c=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[],[])
    st,_=c['resolve']('selected',{})
    assert c['baseBurst']=={'count':3,'delay_seconds':.1}
    assert st.spread_min_deg is None and st.spread_max_deg is None
    before=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=edge-.001,combat=c)
    after=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=edge+.001,combat=c)
    assert before['shots']==3 and after['shots']==4
    assert before['timeline'][-1]['ammo']==st.magazine-3
    assert 'hema-player-health-cost-not-modeled' in after['unsupported']

def test_hema_burst_profile_does_not_apply_to_different_damage_identity():
    w=deepcopy(weapon('Hema'));w['fireModes'][0]['damage']['types']={'DT_VIRAL':52.}
    assert not base_profile(w)
