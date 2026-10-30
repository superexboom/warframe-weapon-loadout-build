"""Finite charged Mandonel fields: independent overlap and generation-bound coverage."""
from copy import deepcopy
from collections import OrderedDict
import pytest
from wfarsenal import manual_combat,combat_replay,native_replay
from wfarsenal.damage import Scenario,ModEffect
from tools.import_mandonel_field import WEAPON,candidate_merge,profile
from tests.test_mandonel_field import Packages,row

@pytest.fixture
def prepare(monkeypatch):
 import app
 ref=candidate_merge(manual_combat.reference(),profile(Packages(),row()))
 monkeypatch.setattr(manual_combat,'reference',lambda:ref)
 original=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON))
 def make(ms=1.,rate=.01,extra=(),mode=1):
  w=deepcopy(original);w['magazineSize']=100;w['fireModes'][mode]['magazineSize']=100
  effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
   ModEffect('WEAPON_FIRE_ITERATIONS','SET',ms),ModEffect('WEAPON_FIRE_RATE','SET',rate),*extra]
  fight=manual_combat.prepare(dict(weapon=w,fire_mode=mode,effects=effects,scenario=Scenario()),[],[])
  original_resolve=fight['resolve']
  def resolve(*args):
   st,radial=original_resolve(*args)
   st._charge_time=0.;st._charge_before_fire=False
   return st,radial
  fight['resolve']=resolve
  stats,_=fight['resolve']('selected',{},0.)
  return fight,stats
 return make

def run(prepare,window=7.,health=1e12,enabled=False,**kwargs):
 fight,stats=prepare(**kwargs);before=native_replay.ENABLED;native_replay.ENABLED=enabled
 try:result=combat_replay.replay(stats,dict(health=health,shield=0.,overguard=0.,armour=0.,baseLevel=1),attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=not enabled)
 finally:native_replay.ENABLED=before
 return result,fight,stats

def test_neutral_field_modifier_context_and_mode0_isolation(prepare):
 fight,stats=prepare(ms=7.,extra=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',2.),ModEffect('WEAPON_CRIT_CHANCE','SET',3.),ModEffect('WEAPON_PROC_CHANCE','SET',5.),ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.9,damage_type='DT_FIRE')])
 assert fight['finiteFields'] and not fight['sourceOwnedFields']
 field,rate,duration,initial=stats._finite_fields[0]
 assert field.damage_types=={'DT_RADIATION':50.} and field.multishot==1.
 assert field.crit_chance==0. and field.status_chance==.34999999
 assert (rate,duration,initial)==(5.,7.,2)
 base_fight,base=prepare(mode=0)
 assert not base_fight['finiteFields'] and not hasattr(base,'_finite_fields')
 assert 'finite-field-target-generation-bound-centered-coverage-approximated' in fight['unsupported']

@pytest.mark.parametrize('window,count',[(.01,2),(.2,3),(.20001,3),(.4,4),(6.999,36),(7.,36),(7.1,36)])
def test_inclusive_window_exclusive_expiry(prepare,window,count):
 result,_,_=run(prepare,window=window)
 assert result['shots']==1 and result['finiteFieldActivations']==1
 assert result['finiteFieldPackets']==[count]
 assert result['procCounts']['DT_RADIATION']==pytest.approx(count*.34999999)
 assert all(p['time']<7 for p in result['finiteFieldTrace'])

def test_overlapping_fields_survive_new_shots_and_do_not_scale_with_ms(prepare):
 a,_,_=run(prepare,window=2.1,rate=2.,ms=1.)
 b,_,_=run(prepare,window=2.1,rate=2.,ms=7.)
 assert a['finiteFieldPackets']==b['finiteFieldPackets']
 assert a['finiteFieldActivations']==a['shots']>=4
 assert a['finiteFieldPackets'][0]>2*a['shots']
 # Old field packets remain active after new field spawn (no replacement token).
 assert a['staleComponents']==0

def test_field_coverage_never_transfers_to_new_target_generation(prepare):
 result,_,_=run(prepare,window=2.,rate=2.,health=1.)
 assert result['killEvents']==result['shots']
 assert result['finiteFieldActivations']==result['shots']
 assert result['finiteFieldPackets']==[0]
 assert result['finiteFieldTrace']==[]

@pytest.mark.parametrize('health,ms,rate,window',[(1e12,1.,.01,7.1),(1e12,7.,2.,2.1),(1.,7.,2.,2.),(1850.,1.,.1,4.),(5000.,2.,1.,4.)])
def test_native_shadow_matches_python_window_overlap_and_generation(prepare,monkeypatch,health,ms,rate,window):
 if not getattr(native_replay.wfcore,'INDEPENDENT_FINITE_FIELDS',0):pytest.skip('build finite field native core')
 expected,_,_=run(prepare,health=health,ms=ms,rate=rate,window=window)
 monkeypatch.setattr(native_replay,'SHADOW',True)
 actual,_,_=run(prepare,health=health,ms=ms,rate=rate,window=window,enabled=True)
 for key in ['shots','directWindow','dotWindow','totalWindowDamage','killEvents','finiteFieldPackets','finiteFieldActivations']:
  assert actual[key]==pytest.approx(expected[key]),key
 assert actual['procCounts']==pytest.approx(expected['procCounts'])

def test_old_core_falls_back_for_finite_field_only(prepare,monkeypatch):
 from types import SimpleNamespace
 monkeypatch.setattr(native_replay,'ENABLED',True)
 monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace())
 fight,stats=prepare()
 assert not native_replay.supported(stats,dict(combat=fight,collect_timeline=False))


def test_actual_manual_search_and_native_health_batch_with_candidate_profile(prepare,monkeypatch):
 import app
 from wfarsenal import search_combat
 from wfarsenal.damage import apply_mods
 if not getattr(native_replay.wfcore,'INDEPENDENT_FINITE_FIELDS',0):pytest.skip('build finite core')
 weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
 weapon=app.optimizer._select_fire_mode(weapon,1,weapon_type=app.optimizer._weapon_type(None,weapon))[0]
 scenario=Scenario(trigger_policy='emergent')
 effects=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.6,damage_type='DT_ELECTRICITY'),ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.8)]
 stats=apply_mods(weapon,effects,scenario=scenario)
 app.optimizer._bind_combat_inputs(stats,weapon,(),effects,scenario)
 context=dict(target=dict(health=10000.,shield=0.,overguard=0.,armour=100.,baseLevel=1),level=1,windowSeconds=4.,headshotChance=0.)
 contexts=[app.optimizer._with_health_scale(context,scale) for scale in (1.,.3,2.,.3)]
 monkeypatch.setattr(search_combat,'_REPLAYS',OrderedDict());monkeypatch.setattr(native_replay,'ENABLED',False)
 expected=[search_combat.window(stats,c,score_only=True) for c in contexts]
 search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
 monkeypatch.setattr(native_replay,'ENABLED',True)
 before=native_replay.HEALTH_BATCH_STATS['runs'];batched=search_combat.windows(stats,contexts)
 assert batched is not None and native_replay.HEALTH_BATCH_STATS['runs']==before+4
 for actual,reference in zip(batched,expected):
  assert actual['totalWindowDamage']==pytest.approx(reference['totalWindowDamage'],abs=1e-8)
  assert actual['killsPerMinute']==pytest.approx(reference['killsPerMinute'],abs=1e-8)
 fight=manual_combat.prepare(stats._combat_inputs['engine'],[],[]);base,_=fight['resolve']('selected',{},0.)
 manual=combat_replay.replay(base,context['target'],attacks_per_second=base.fire_rate,window_seconds=4.,level=1,combat=fight,collect_timeline=False)
 assert manual['finiteFieldActivations']>0
 assert manual['totalWindowDamage']==pytest.approx(expected[0]['totalWindowDamage'],abs=1e-8)
 search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
 actual=search_combat.window(stats,context,score_only=True)
 assert actual['totalWindowDamage']==pytest.approx(manual['totalWindowDamage'],abs=1e-8)


def test_old_core_replay_uses_python_and_keeps_finite_field(prepare,monkeypatch):
 from types import SimpleNamespace
 monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace())
 result,_,_=run(prepare,window=.4,enabled=True)
 assert result['finiteFieldPackets']==[4] and result['finiteFieldActivations']==1

def test_mode0_replay_matches_profile_without_finite_field(prepare,monkeypatch):
 expected,_,_=run(prepare,window=2.,mode=0)
 ref=deepcopy(manual_combat.reference());ref['auditedAttacks'][WEAPON].get('modes',{}).pop('1',None)
 monkeypatch.setattr(manual_combat,'reference',lambda:ref)
 actual,_,_=run(prepare,window=2.,mode=0)
 for key in ['shots','directWindow','dotWindow','totalWindowDamage','killEvents','procCounts']:
  assert actual[key]==expected[key]
 assert 'finiteFieldPackets' not in actual

def test_field_kill_invalidates_remaining_original_generation_events(prepare,monkeypatch):
 expected,_,_=run(prepare,window=1.,rate=.01,health=1850.)
 assert expected['killEvents']==1 and expected['finiteFieldPackets']==[1]
 if getattr(native_replay.wfcore,'INDEPENDENT_FINITE_FIELDS',0):
  monkeypatch.setattr(native_replay,'SHADOW',True)
  actual,_,_=run(prepare,window=1.,rate=.01,health=1850.,enabled=True)
  assert actual['finiteFieldPackets']==[1] and actual['killEvents']==1


@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('which',['empowered','encumber'])
def test_neutral_field_status_does_not_trigger_weapon_status_arcanes(monkeypatch,native,which):
 from wfarsenal.status_arcanes import EMPOWERED,ENCUMBER
 import app
 weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
 path=EMPOWERED if which=='empowered' else ENCUMBER
 arcane=next(a for a in app.EXPORTS['arcanes'] if a['path']==path)
 def evaluate(parent_sc):
  effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',parent_sc)]
  c=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=Scenario()),[],[(arcane,5,None)])
  st,_=c['resolve']('selected',{},0.);before=native_replay.STATS['native']
  result=combat_replay.replay(st,dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1),attacks_per_second=st.fire_rate,
   window_seconds=1.501,combat=c,trigger_sources=c['trigger_sources'],collect_timeline=False)
  if native:assert native_replay.STATS['native']>before
  return result
 monkeypatch.setattr(native_replay,'ENABLED',native)
 monkeypatch.setattr(native_replay,'SHADOW',native)
 result=evaluate(0.)
 count=result[which]['expectedInstances' if which=='empowered' else 'expectedExtraProcs']
 assert count==0
 assert result['procCounts']['DT_RADIATION']==pytest.approx(2*.34999999)
 control=evaluate(1.)
 assert control[which]['expectedInstances' if which=='empowered' else 'expectedExtraProcs']>0
