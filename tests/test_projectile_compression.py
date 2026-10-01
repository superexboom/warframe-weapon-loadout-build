from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import (apply_mods, mod_effects, arcane_effects, ModEffect,
    ModEffectList, Scenario, damage_against)
from wfarsenal.manual_combat import prepare
from wfarsenal.runtime_adapters import resolve_runtime_adapter, compression_configuration, COMPRESSION_PATH
from wfarsenal.combat_replay import replay


def weapon(name):return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
def compression():return next(a for a in app.EXPORTS['arcanes'] if a['path']==COMPRESSION_PATH)


@pytest.mark.parametrize('rank',[0,5])
def test_compression_radius_rank_ads_co_and_ammo_are_shared(rank):
    w=weapon('Kuva Ogris');sc=Scenario(aiming=True,victim_status_count=3)
    fx=[ModEffect('WEAPON_DAMAGE_AMOUNT','ADD',1.65),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','ADD',.4),
        ModEffect('WEAPON_EXPLOSION_RADIUS','STACKING_MULTIPLY',.44)]
    bonus=arcane_effects(compression(),rank=rank)
    ordinary=apply_mods(w,fx,scenario=sc)
    active=apply_mods(w,[*fx,*bonus],scenario=sc)
    meters=7.9*1.44*.8
    multiplier=1+meters*(.5+rank*.1)
    assert active.total_damage/ordinary.total_damage==pytest.approx((2.65*multiplier+1.2)/(2.65+1.2))
    assert active.dot_base_damage/ordinary.dot_base_damage==pytest.approx(multiplier)
    assert active.ammo_cost==pytest.approx(max(0,1-meters*(.03+rank*.005)))
    hip=apply_mods(w,[*fx,*bonus],scenario=replace(sc,aiming=False))
    assert hip.total_damage==pytest.approx(ordinary.total_damage)
    assert hip.ammo_cost==ordinary.ammo_cost
    assert apply_mods(w,[*fx,*arcane_effects(compression(),rank=rank,uptime=0)],scenario=sc).total_damage==ordinary.total_damage


def test_unknown_compression_weapon_never_guesses_a_multiplier():
    w=weapon('Braton Prime');fx=arcane_effects(compression(),rank=5)
    plain=apply_mods(w,[],scenario=Scenario(aiming=True))
    active=apply_mods(w,fx,scenario=Scenario(aiming=True))
    assert active.total_damage==plain.total_damage
    assert 'primary-compression-weapon-profile-unverified' in active.unsupported
    malformed=deepcopy(compression())
    malformed['runtimeScripts']['apply']['_damageMultPerMeterLostBase']=99
    assert compression_configuration(malformed,5) is None
    assert not arcane_effects(malformed,rank=5)


def test_compression_adds_profile_joins_base_bucket():
    w=weapon('Kuva Ogris')
    w={**w,'__compressionProfile__':dict(radius=5.,stacking='adds')}
    fx=[ModEffect('WEAPON_DAMAGE_AMOUNT','ADD',1.),*arcane_effects(compression(),rank=5)]
    a=apply_mods(w,fx,scenario=Scenario(aiming=True))
    assert a.total_damage==pytest.approx(27.*6.)
    assert a.dot_base_damage==pytest.approx(27.*6.)


@pytest.mark.parametrize('name,base',[('Semi-Rifle Cannonade',.4),('Semi-Shotgun Cannonade',.4),('Semi-Pistol Cannonade',.5)])
def test_cannonade_keeps_damage_and_locks_positive_and_negative_rate(name,base):
    m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==name)
    assert resolve_runtime_adapter(m,5).kind=='lock_fire_rate'
    fx=mod_effects(m,5)
    w=weapon('Latron Prime')
    for rate in [-.2,.6]:
        st=apply_mods(w,[*fx,ModEffect('WEAPON_FIRE_RATE','ADD',rate)])
        assert st.fire_rate==w['fireModes'][0]['fireRate']
        assert st.total_damage==pytest.approx(sum(w['fireModes'][0]['damage']['types'].values())*(1+base*6),rel=1e-6)
    changed=deepcopy(m);changed['runtimeScripts']['apply']['Function']='Unknown'
    assert resolve_runtime_adapter(changed,5) is None
    assert not mod_effects(changed,5)


def test_cannonade_native_compatibility_is_not_replaced_by_reference_trigger_label():
    m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Semi-Rifle Cannonade')
    from wfarsenal.simulator import _mod_matches_weapon
    assert _mod_matches_weapon(m,weapon('Kuva Ogris'))
    assert not _mod_matches_weapon(m,weapon('Penta'))
    assert not _mod_matches_weapon(m,weapon('Braton Prime'))


def test_arming_distance_gates_radial_but_not_direct_and_unknown_is_visible():
    w=weapon('Acceltra Prime')
    for distance in [0.,5.99,6.,12.,None]:
        sc=Scenario(distance=distance)
        combat=prepare(dict(weapon=w,effects=[],scenario=sc,fire_mode=0),[],[])
        direct,radial=combat['resolve']('selected',{},0)
        assert direct.total_damage==44.
        assert (radial is not None)==(distance is None or distance>=6.)
        if radial:
            assert radial.radial_only
            assert radial.total_damage==pytest.approx(53.)
        assert ('radial-arming-distance-assumed-armed' in combat['unsupported'])==(distance is None)


def test_fractional_ammo_debt_survives_reload():
    from test_combat_replay import stats,target
    st=stats(magazine=5.,ammo_cost=.4,fire_rate=1.,reload_time=.001,status_chance=0.)
    c=dict(resolve=lambda *a:(st,None))
    r=replay(st,target(),attacks_per_second=1.,window_seconds=25.01,combat=c,time_step=.01)
    # Two magazines buy 25 shots, not two freshly rounded-up 13-shot clips.
    assert r['reloads']==2
    assert r['shots']==26
    last=r['timeline'][-1]
    assert last['ammo']==pytest.approx(4.6)


@pytest.mark.parametrize('name', ['Kuva Ogris','Zarr','Acceltra Prime','Sonicor'])
@pytest.mark.parametrize('aiming', [True,False])
def test_compression_manual_optimizer_same_effects(name,aiming):
    from tools.audit_optimizer_events import evaluate_payload
    w=weapon(name)
    arcs=[] if name=='Sonicor' else [dict(path=COMPRESSION_PATH,rank=5)]
    p=dict(weapon=w['path'],fireMode=0,mods=[],arcanes=arcs,
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,
           headshotChance=1.,aiming=aiming,scenario={'distance':10.})
    if name=='Kuva Ogris':p.update(innateElement='DT_MAGNETIC',innateElementValue=.6)
    result=evaluate_payload(p)
    assert result['optimizer']==pytest.approx(result['manual'],rel=1e-9)


def test_radial_does_not_collect_puncture_critical_chance():
    from test_combat_replay import stats,target
    st=stats(damage_types={'DT_PUNCTURE':100.},crit_chance=0.,status_chance=1.,
             multishot=1.,radial_only=True)
    plain=replace(st,status_chance=0.)
    opts=dict(attacks_per_second=10.,window_seconds=2.)
    a=replay(st,target(),**opts);b=replay(plain,target(),**opts)
    assert a['directWindow']==pytest.approx(b['directWindow'])
    direct=replay(replace(st,radial_only=False),target(),**opts)
    assert direct['directWindow'] > a['directWindow']


def test_compression_reports_the_ads_gate_without_false_missing_warnings():
    w=weapon('Kuva Ogris');a=compression();sc=Scenario(aiming=True)
    p=dict(path=a['path'],rank=5)
    card,states,bad,_=app._prepare_manual_arcanes([p],w)
    assert not any('trigger-rate-required' in x for x in bad)
    state=states[0]
    assert state['applied'] and state['active']
    assert state['triggerCondition']=='aiming' and state['conditionRequired']
    assert state['damagePerMeter']==1.
    assert state['ammoEfficiencyPerMeter']==pytest.approx(.055)
    combat=prepare(dict(weapon=w,fire_mode=0,scenario=sc,effects=card.effects),[],[(a,5,p)])
    assert not any('runtime-condition-unmodeled' in x for x in combat['unsupported'])
    _,states,_,_=app._prepare_manual_arcanes([{**p,'stacks':0}],w)
    assert not states[0]['active'] and states[0]['expectedUptime']==0.

def test_compression_removal_contribution_uses_the_corrected_model():
    w=weapon('Kuva Ogris');a=compression()
    p=dict(weapon=w['path'],fireMode=0,mods=[],arcanes=[dict(path=a['path'],rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1.,
           aiming=True,scenario={'distance':10.},innateElement='DT_MAGNETIC',innateElementValue=.6)
    key='__arcane__:'+a['path']
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains'][key]['value']==pytest.approx(without,abs=.001)
    assert gains['baseValue']>without


@pytest.mark.parametrize('field',[{'distance':10.},{'scenario':{'distance':10.}},
    {'distance':1.,'scenario':{'distance':10.}},{'distance':10.,'scenario':{'distance':0.}},
    {'distance':10.,'scenario':{'distance':None}}])
def test_actual_build_and_manual_replay_accept_the_same_distance(field,monkeypatch):
    monkeypatch.setenv('WF_ANALYZER_SERIAL','1')
    w=weapon('Sonicor')
    p=dict(weapon=w['path'],fireMode=0,mods=[],metric='killsPerMinute',profile='fast',
        slotCount=1,minFill=0,maxFill=0,enemy=app._BENCHMARK_ENEMY_PATH,
        level=9999,steelPath=True,headshotChance=1.,aiming=True,**field)
    built=app.build_weapon_payload(p)
    exilus=built.get('exilus')
    manual=app.simulate_manual_payload({**p,'exilus':{'path':exilus['path'],'rank':exilus['rank']} if exilus else None})
    assert built['build']['objectiveScore']==pytest.approx(manual['benchmarkTimeline']['killsPerMinute'],rel=1e-9)


def test_search_preserves_nested_combat_conditions(monkeypatch):
    w=weapon('Sonicor');seen=[]
    class Captured(Exception):pass
    def capture(exports,weapon,scenario):
        seen.append(scenario);raise Captured()
    monkeypatch.setattr(app.optimizer,'_candidate_mods',capture)
    p=dict(weapon=w['path'],fireMode=0,metric='killsPerMinute',aiming=True,
        scenario=dict(aiming=False,distance=0.,cloaked=True,nearestEnemyDistance=3.,comboTier=2))
    with pytest.raises(Captured):app.build_weapon_payload(p)
    sc=seen[0]
    assert not sc.aiming and sc.distance==0. and sc.cloaked
    assert sc.nearest_enemy_distance==3. and sc.combo_tier==2


@pytest.mark.parametrize('name,radius',[('Simulor',4.),('Synoid Simulor',5.)])
def test_pure_radial_compression_has_no_duplicate_blast_or_head_trigger(name,radius):
    w=weapon(name);sc=Scenario(aiming=True,trigger_policy='emergent')
    fx=arcane_effects(compression(),rank=5)
    combat=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[],[(compression(),5,{})])
    st,extra=combat['resolve']('selected',{},0)
    assert extra is None and st.radial_only
    plain=apply_mods(w,[],scenario=sc)
    assert st.total_damage==pytest.approx(plain.total_damage*(1+.8*radius))
    assert st.ammo_cost==pytest.approx(1-.055*.8*radius)
    assert 'orb-merging-and-singularity-unmodeled' not in combat['unsupported']
    assert 'primary-compression-weapon-profile-unverified' not in st.unsupported
