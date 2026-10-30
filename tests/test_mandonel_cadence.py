"""Mandonel full-charge route pays windup before every shot, including first."""
from copy import copy,deepcopy
from types import SimpleNamespace
import pytest
import app
from wfarsenal import combat_replay,manual_combat,native_replay
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

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('mode,window,shots',[(0,.01,1),(0,4.,12),(1,1.499,0),(1,1.501,1),(1,3.499,1),(1,3.501,2),(1,4.,2)])
def test_production_first_and_repeat(native,mode,window,shots):
 if native and not getattr(native_replay.wfcore,'ORDINARY_CHARGED_WINDUP',0):pytest.skip('build ordinary charged core')
 assert run(fight(mode),window,native)['shots']==shots

def test_charge_rate_only_scales_charge_and_fire_rate_only_recovery():
 for up,charge,rate in [('WEAPON_CHARGE_RATE',.75,2.),('WEAPON_FIRE_RATE',1.5,4.)]:
  c=fight(effects=[ModEffect(up,'STACKING_MULTIPLY',1.)]);st,_=c['resolve']('selected',{},0.)
  assert st._charge_time==pytest.approx(charge) and st.fire_rate==pytest.approx(rate)
  assert run(c,charge-.001)['shots']==0
  assert run(c,charge+.001)['shots']==1

@pytest.mark.parametrize('native',[False,True])
def test_reload_and_target_death_do_not_grant_free_charge(native,monkeypatch):
 if native and not getattr(native_replay.wfcore,'ORDINARY_CHARGED_WINDUP',0):pytest.skip('build ordinary charged core')
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight();resolve=c['resolve']
 def modified(*args):
  st,radial=resolve(*args);st=copy(st);st.magazine=1.;st.reload_time=1.;return st,radial
 c['resolve']=modified
 for window,shots in [(1.501,1),(4.499,1),(4.501,2)]:
  r=run(c,window,native,dict(TARGET,health=1.));assert r['shots']==shots
  assert r['killEvents']==shots

@pytest.mark.parametrize('native',[False,True])
def test_charge_completion_reads_expired_buff(native,monkeypatch):
 if native and not getattr(native_replay.wfcore,'ORDINARY_CHARGED_WINDUP',0):pytest.skip('build ordinary charged core')
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight();resolve=c['resolve'];c['trigger_sources']=[dict(id='temporary',label='fixture',kind='unused',initialStacks=1.,initialDuration=.7,duration=.7,perEvent=0.,maxStacks=1.,decay='reset')]
 def modified(form,stacks,*args):
  st,radial=resolve(form,stacks,*args);st=copy(st);st.crit_chance=0.;st.status_chance=0.;st.multishot=1.;st.native_forced_procs={};st.damage_types={'DT_IMPACT':100.+900.*stacks.get('temporary',0.)};return st,None
 c['resolve']=modified
 observed=run(c,1.501,native)['directWindow']
 c['trigger_sources']=[]
 assert observed==pytest.approx(run(c,1.501,native)['directWindow'])

def test_old_native_core_falls_back(monkeypatch):
 c=fight();st,_=c['resolve']('selected',{},0.)
 monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace(INDEPENDENT_FINITE_FIELDS=1))
 assert not native_replay.supported(st,dict(combat=c,collect_timeline=False))

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('health,is_field_kill',[(1850.,True),(1.,False)])
def test_neutral_field_kill_has_no_unproven_weapon_trigger_credit(native,health,is_field_kill,monkeypatch):
 if native and not getattr(native_replay.wfcore,'NEUTRAL_FINITE_FIELD_SOURCE',0):pytest.skip('build neutral source core')
 monkeypatch.setattr(native_replay,'SHADOW',True)
 c=fight(effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)])
 c['trigger_sources']=[dict(id='killProbe',label='kill probe',kind='on-kill',initialStacks=0.,duration=10.,perEvent=1.,maxStacks=5.,decay='reset')]
 resolve=c['resolve'];seen=[]
 def observe(form,stacks,*args):
  seen.append(stacks.get('killProbe',0.));return resolve(form,stacks,*args)
 c['resolve']=observe
 result=run(c,3.501,native,dict(TARGET,health=health))
 assert result['killEvents']>=1
 assert bool(max(seen)) is not is_field_kill

@pytest.mark.parametrize('mismatch',['index','trigger','fireRate'])
def test_charge_mapping_rejects_changed_mode_identity(mismatch):
 from wfarsenal.event_profiles import native_charge
 w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON))
 w['fireModes'][1][mismatch]={'index':99,'trigger':'changed','fireRate':9.}[mismatch]
 assert native_charge(w,1) is None
