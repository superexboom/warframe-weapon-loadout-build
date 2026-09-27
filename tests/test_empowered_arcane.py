from copy import deepcopy
from dataclasses import replace
import pytest
import app
from tests.test_combat_replay import stats, target
from wfarsenal.combat_replay import replay
from wfarsenal.damage import arcane_effects, apply_mods
from wfarsenal.status_arcanes import EMPOWERED, ENCUMBER, configuration
from tools.audit_optimizer_events import evaluate_payload


def raw(path=EMPOWERED):
    return next(a for a in app.EXPORTS['arcanes'] if a['path']==path)


def run(st=None, *, rank=5, tg=None, combat=None, **kw):
    st=st or stats(damage_types={'DT_IMPACT':100},crit_chance=0,status_chance=1,fire_rate=1)
    return replay(st,tg or target(),attacks_per_second=st.fire_rate,window_seconds=.1,
        combat={'empowered':configuration(raw(),rank),**(combat or {})},**kw)


@pytest.mark.parametrize('rank,amount',list(enumerate([250,350,450,550,650,750])))
def test_exact_native_rank_table_and_no_fake_base_damage(rank,amount):
    assert configuration(raw(),rank)['damage']==amount
    assert arcane_effects(raw(),rank=rank)==[]
    result=run(rank=rank)
    assert result['arcaneWindow']==amount
    assert result['directWindow']==100
    assert result['totalWindowDamage']==100+amount
    assert result['timeline'][0]['directDps']==pytest.approx((100+amount)/.1)
    bad=deepcopy(raw());bad['runtimeScripts']['apply']['_damageAmounts'][rank]+=1
    assert configuration(bad,rank) is None
    bad=deepcopy(raw());bad['conditionalEffects'][0]['conditions']=['OnHitCondition']
    assert configuration(bad,rank) is None


@pytest.mark.parametrize('change',[
    {'damage_types':{'DT_IMPACT':10000}}, {'crit_chance':4,'crit_multiplier':10},
    {'falloff_multiplier':.1}, {'weakpoint_damage_bonus':100,'weakpoint_crit_chance_bonus':100},
    {'proc_damage_multiplier':10}, {'noncrit_damage_multiplier':21},
    {'proc_duration_multiplier':0},
])
def test_flat_instance_does_not_inherit_weapon_damage_multipliers(change):
    st=stats(damage_types={'DT_IMPACT':100},crit_chance=0,status_chance=1,fire_rate=1)
    assert run(replace(st,**change),headshot_chance=1)['arcaneWindow']==750


def test_each_status_and_projectile_count_once_without_proc_recursion():
    st=stats(damage_types={'DT_IMPACT':100},crit_chance=0,status_chance=2.5,multishot=3,fire_rate=1)
    r=run(st)
    assert r['empowered']['expectedInstances']==pytest.approx(7.5)
    assert r['arcaneWindow']==pytest.approx(750*7.5)
    assert sum(r['procCounts'].values())==pytest.approx(7.5)
    assert run(st,status_rate_multiplier=.5)['arcaneWindow']==pytest.approx(750*3.75)


def test_faction_multiplier_applies_once_and_toxin_keeps_shield_bypass():
    st=stats(damage_types={'DT_POISON':100},crit_chance=0,status_chance=1,fire_rate=1,
             faction_damage_multipliers={'':1.5,'FC_GRINEER':1.3})
    r=run(st,tg={**target(),'shield':1e5,'faction':'FC_GRINEER'})
    assert r['arcaneWindow']==pytest.approx(750*1.5*1.3)
    assert r['timeline'][0]['shield']==1e5
    assert r['empowered']['damageByType']['DT_POISON']==r['arcaneWindow']


def test_flat_slash_does_not_bypass_armour_like_a_bleed_tick():
    st=stats(damage_types={'DT_SLASH':100},crit_chance=0,status_chance=1,fire_rate=1)
    r=run(st,tg={**target(),'armour':2700})
    assert r['arcaneWindow']==pytest.approx(75)
    assert r['dotWindow']==0


def test_derived_encumber_script_procs_do_not_reenter_weapon_trigger():
    r=run(combat={'encumber':configuration(raw(ENCUMBER),5)})
    assert r['encumber']['expectedExtraProcs']>0
    assert r['empowered']['expectedInstances']==1
    assert set(r['empowered']['damageByType'])=={'DT_IMPACT'}


def test_extra_hit_kill_cannot_leak_remaining_procs_radial_or_field_to_respawn():
    st=stats(damage_types={'DT_IMPACT':1},crit_chance=0,status_chance=0,fire_rate=1)
    child=replace(st,damage_types={'DT_FIRE':10000})
    st._lingering=(child,1,3)
    source=dict(id='head-kill',label='head-kill',kind='on-headshot-kill',maxStacks=10)
    r=run(st,tg=target(hp=500),combat={'resolve':lambda *args:(st,child)},
          forced_procs={'DT_IMPACT':1,'DT_PUNCTURE':1},headshot_chance=1,trigger_sources=[source])
    assert r['killEvents']==1
    assert r['empowered']['expectedInstances']==1
    assert r['procCounts'].get('DT_PUNCTURE',0)==0
    assert r['staleComponents']>=1
    assert r['triggerSeries'][0]['avgStacks']==0
    assert r['timeline'][0]['health']==500


@pytest.mark.parametrize('name',['Kompressa','Aksomati Prime','Kuva Twin Stubbas','Sonicor'])
def test_manual_optimizer_catalog_and_explicit_disabled_state(name):
    assert app.MANUAL_ARCANES_BY_PATH[EMPOWERED]['eventModel']=='empowered'
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=EMPOWERED,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=160,steelPath=True,headshotChance=1,
           aiming=True,triggerPolicy='emergent')
    r=evaluate_payload(p)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    assert not any('arcane-state' in x for x in r['manualUnsupported'])
    plain=app.simulate_manual_payload({**p,'arcanes':[]})
    disabled=app.simulate_manual_payload({**p,'arcanes':[dict(path=EMPOWERED,rank=5,stacks=0)]})
    assert disabled['benchmarkTimeline']['killsPerMinute']==plain['benchmarkTimeline']['killsPerMinute']
    assert disabled['benchmarkTimeline']['empowered']['expectedInstances']==0


def test_equipped_contribution_removes_actual_event_damage():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Kompressa')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=EMPOWERED,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=160,steelPath=True,headshotChance=0,
           aiming=True,triggerPolicy='emergent')
    key='__arcane__:'+EMPOWERED
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains'][key]['value']==pytest.approx(without,abs=.001)
    assert gains['baseValue']>without
