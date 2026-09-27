from copy import deepcopy
from dataclasses import replace
import pytest
import app
from tests.test_combat_replay import target
from wfarsenal.damage import Scenario, ModEffect, damage_against
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload


def combat(name,fx=()):
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    c=prepare(dict(weapon=w,fire_mode=0,effects=list(fx),scenario=Scenario(distance=.5)),[],[])
    return w,c,*c['resolve']('selected',{},0)


@pytest.mark.parametrize('name,base,radial,ms,sc',[('Kompressa',2,42,4,.3),('Cyanex',50,41,1,.32)])
@pytest.mark.parametrize('bonus',[0,1.2])
def test_native_projectile_counts_and_radial_status_units(name,base,radial,ms,sc,bonus):
    w,c,st,part=combat(name,[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',bonus)])
    assert st.total_damage==pytest.approx(base)
    assert part.total_damage==pytest.approx(radial)
    assert st.multishot==pytest.approx(ms*(1+bonus))
    assert part.multishot==st.multishot
    assert st.status_chance==pytest.approx(sc)
    assert part.status_chance==pytest.approx(sc)
    assert part.radial_only
    assert damage_against(part,target(),hit_location='head')['perShot']==damage_against(part,target(),hit_location='body')['perShot']
    if name=='Cyanex':assert part.total_damage!=100 # dormant EmbedDeathAttack


def test_kompressa_radial_occurs_after_embedding_delay_not_on_contact():
    w,c,st,part=combat('Kompressa')
    st.crit_chance=part.crit_chance=0
    st.status_chance=part.status_chance=0
    st.fire_rate=.01
    c['resolve']=lambda *args:(st,part)
    before=replay(st,target(),attacks_per_second=.01,window_seconds=.699,combat=c)
    after=replay(st,target(),attacks_per_second=.01,window_seconds=.701,combat=c)
    assert before['directWindow']==8
    assert after['directWindow']==176
    assert before['shots']==after['shots']==1


def test_delayed_projectile_cannot_damage_a_different_target_generation():
    w,c,st,part=combat('Kompressa')
    st.crit_chance=part.crit_chance=0
    st.status_chance=part.status_chance=0
    st.fire_rate=10
    c['resolve']=lambda *args:(st,part)
    delayed=replay(st,target(hp=20),attacks_per_second=10,window_seconds=.71,combat=c)
    c['resolve']=lambda *args:(st,None)
    direct=replay(st,target(hp=20),attacks_per_second=10,window_seconds=.71,combat=c)
    assert delayed['killEvents']==direct['killEvents']==2
    assert delayed['directWindow']==direct['directWindow']


@pytest.mark.parametrize('name',['Kompressa','Cyanex'])
def test_native_parts_are_in_manual_and_optimizer_with_empowered(name):
    from wfarsenal.status_arcanes import EMPOWERED
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    p=dict(weapon=w['path'],fireMode=0,mods=[],arcanes=[dict(path=EMPOWERED,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,
           headshotChance=1,aiming=True,scenario={'distance':.5},triggerPolicy='emergent')
    r=evaluate_payload(p)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    assert 'projectile-component-damage-unapplied' not in r['unsupported']
