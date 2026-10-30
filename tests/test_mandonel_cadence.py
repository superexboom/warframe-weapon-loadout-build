"""Mandonel full-charge route pays windup before every shot, including first."""
from copy import copy,deepcopy
from types import SimpleNamespace
import pytest
import app
from wfarsenal import combat_replay,manual_combat,native_replay,extract
from wfarsenal.damage import Scenario,ModEffect
WEAPON='/Lotus/Weapons/Tenno/Archwing/Primary/TnConcreteArchgun/TnConcreteArchgunWeapon'
TARGET=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)

def fight(mode=1,effects=()):
 w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON))
 return manual_combat.prepare(dict(weapon=w,fire_mode=mode,effects=list(effects),scenario=Scenario()),[],[])

def run(c,window,native=False,target=TARGET):
 st,_=c['resolve']('selected',{},0.)
 old=native_replay.ENABLED;native_replay.ENABLED=native
 before=native_replay.STATS['native']
 try:r=combat_replay.replay(st,target,attacks_per_second=st.fire_rate,window_seconds=window,combat=c,trigger_sources=c['trigger_sources'],collect_timeline=False)
 finally:native_replay.ENABLED=old
 if native:assert native_replay.STATS['native']>before
 return r

def test_production_charge_and_recovery_obey_distinct_modifiers(monkeypatch):
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight(effects=[ModEffect('WEAPON_CHARGE_RATE','STACKING_MULTIPLY',1.),ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',1.)])
 st,_=c['resolve']('selected',{},0.)
 assert st._charge_time==pytest.approx(.75) and st.fire_rate==pytest.approx(4.)
 assert run(c,.749,True)['shots']==0
 assert run(c,.751,True)['shots']==1
 assert run(c,1.749,True)['shots']==1
 assert run(c,1.751,True)['shots']==2
 assert run(fight(0),.01,True)['shots']==1


def test_reload_and_target_death_do_not_grant_free_charge(monkeypatch):
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight();resolve=c['resolve']
 def modified(*args):
  st,radial=resolve(*args);st=copy(st);st.magazine=1.;st.reload_time=1.;return st,radial
 c['resolve']=modified
 before=run(c,4.499,True,dict(TARGET,health=1.))
 after=run(c,4.501,True,dict(TARGET,health=1.))
 assert before['shots']==before['killEvents']==1
 assert after['shots']==after['killEvents']==2

def test_charge_completion_reads_expired_buff(monkeypatch):
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight();resolve=c['resolve'];c['trigger_sources']=[dict(id='temporary',label='fixture',kind='unused',initialStacks=1.,initialDuration=.7,duration=.7,perEvent=0.,maxStacks=1.,decay='reset')]
 def modified(form,stacks,*args):
  st,radial=resolve(form,stacks,*args);st=copy(st);st.crit_chance=0.;st.status_chance=0.;st.multishot=1.;st.native_forced_procs={};st.damage_types={'DT_IMPACT':100.+900.*stacks.get('temporary',0.)};return st,None
 c['resolve']=modified
 observed=run(c,1.501,True)['directWindow']
 c['trigger_sources']=[]
 assert observed==pytest.approx(run(c,1.501,True)['directWindow'])

def test_old_native_core_falls_back(monkeypatch):
 c=fight();st,_=c['resolve']('selected',{},0.)
 monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace(INDEPENDENT_FINITE_FIELDS=1))
 assert not native_replay.supported(st,dict(combat=c,collect_timeline=False))

def behaviors():
    return [{'state:Type':'/Lotus/Types/Game/LotusSwappingChargedStateBehavior','state:LotusSwappingChargedStateBehavior':dict(ChargeTime=1.5,MinChargeRatio=0,SwapOnFire=1,SwapAfterFire=0,ChargedBehavior=1,CacheFullCharge=0,fireRate=180,LocTag='/Lotus/Language/Menu/Loadout_TriggerCharge')},
            {'state:Type':'/EE/Types/Game/WeaponChargeBeamStateBehavior','state:WeaponChargeBeamStateBehavior':dict(ChargeTime=0,fireRate=120,LocTag='/Lotus/Language/Menu/Loadout_TriggerCharge')}]


def test_extraction_separates_local_state_time_from_effective_release_charge(monkeypatch):
    monkeypatch.setattr(extract,'_resolve_damage',lambda *_:dict(types={'DT_IMPACT':10.}))
    monkeypatch.setattr(extract,'_native_event_declarations',lambda *_:{})
    monkeypatch.setattr(extract,'_extract_projectile_events',lambda *_:{})
    states=behaviors();before=deepcopy(states)
    modes=extract._extract_fire_modes(None,'/fixture',{'Behaviors':states})
    assert states==before
    assert [m['chargeTime'] for m in modes]==[0.,1.5]
    assert [m['nativeLocalChargeTime'] for m in modes]==[1.5,0]
    assert [m['nativeChargeSourceBehavior'] for m in modes]==[0,0]
    assert [m['index'] for m in modes]==[0,1]
