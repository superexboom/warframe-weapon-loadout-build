"""Full clip damage scaling with an explicit conservative recharge strategy."""
from copy import deepcopy
import json
from pathlib import Path
from tools import import_tenet_plinx_cycle as imp
from tools.import_native_secondary_payloads import merge_patch
import pytest
import app
from wfarsenal import manual_combat, native_replay, combat_replay
from wfarsenal.damage import Scenario, ModEffect
PATH='/Lotus/Weapons/Corpus/BoardExec/Secondary/CrpBEPlinx/CrpBEPlinxWeapon'
POLICY=dict(cadencePolicy='wait-configured-empty-delay-then-full-recharge',
            chargeSeconds=.80000001,emptyDelaySeconds=3.,regenPerSecond=20.)
TARGET=dict(health=1e9,shield=0.,armour=0.,overguard=0.,baseLevel=1,
            healthType='',armourType='',shieldType='',damageController='custom')

@pytest.fixture
def fixture(monkeypatch):
    ref=deepcopy(manual_combat.reference())
    mode=ref['auditedAttacks'][PATH]['modes']['1']
    mode.update(fullClipCharge=POLICY,radial=dict(damage={'radiation':100.},
        crit_chance=.40000001,crit_multiplier=3.,status_chance=.5,
        impact_delay_seconds=.80000001,takes_condition_overload=False),
        battery=dict(delayEmptySeconds=3.,delayPartialSeconds=.80000001,regenPerSecond=20.))
    monkeypatch.setattr(manual_combat,'reference',lambda:ref)
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==PATH))
    def build(n=10,ms=0.,reload=0.,extra=()):
        fx=[ModEffect('WEAPON_CLIP_MAX','SET',float(n)),ModEffect('WEAPON_CRIT_CHANCE','SET',0.),
            ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',ms),
            ModEffect('WEAPON_RELOAD_SPEED','STACKING_MULTIPLY',reload),*extra]
        fight=manual_combat.prepare(dict(weapon=deepcopy(weapon),fire_mode=1,effects=fx,scenario=Scenario()),[],[])
        stats,radial=fight['resolve']('selected',{},0.)
        return stats,radial,fight
    return build


def test_actual_production_manual_search_and_native_health_batch_agree(monkeypatch):
    from wfarsenal import search_combat
    from wfarsenal.damage import apply_mods
    from collections import OrderedDict
    profile=manual_combat.reference()['auditedAttacks'][PATH]['modes']['1']
    assert profile['fullClipCharge']['cadencePolicy']==POLICY['cadencePolicy']
    assert profile['radial']['forcedProcs']==['PT_RAGDOLL']
    assert profile['radial']['falloff_reduction']==pytest.approx(.40000001)
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==PATH)
    weapon=app.optimizer._select_fire_mode(weapon,1,weapon_type=app.optimizer._weapon_type(None,weapon))[0]
    scenario=Scenario(trigger_policy='emergent')
    effects=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.6,damage_type='DT_ELECTRICITY'),
        ModEffect('WEAPON_PROC_CHANCE','SET',.35),ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',.47),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','ADD',1.)]
    stats=apply_mods(weapon,effects,scenario=scenario)
    app.optimizer._bind_combat_inputs(stats,weapon,(),effects,scenario)
    context=dict(target=dict(health=10000.,shield=0.,overguard=0.,armour=100.,baseLevel=1),
                 level=1,windowSeconds=13.,headshotChance=0.)
    contexts=[app.optimizer._with_health_scale(context,scale) for scale in (1.,.3,2.,.3)]
    monkeypatch.setattr(search_combat,'_REPLAYS',OrderedDict())
    monkeypatch.setattr(native_replay,'ENABLED',False)
    expected=[search_combat.window(stats,c,score_only=True) for c in contexts]
    search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
    monkeypatch.setattr(native_replay,'ENABLED',True)
    before=native_replay.HEALTH_BATCH_STATS['runs'];batched=search_combat.windows(stats,contexts)
    assert batched is not None and native_replay.HEALTH_BATCH_STATS['runs']==before+4
    for actual,reference in zip(batched,expected):
        assert actual['totalWindowDamage']==pytest.approx(reference['totalWindowDamage'],abs=1e-7)
        assert actual['killsPerMinute']==pytest.approx(reference['killsPerMinute'],abs=1e-8)
    assert batched[1]==batched[3]
    fight=manual_combat.prepare(stats._combat_inputs['engine'],[],[])
    base,_=fight['resolve']('selected',{},0.)
    assert base.magazine==base.ammo_cost==15
    calls=[];resolve=fight['resolve']
    def measured(form,stacks,live=0,last=False):
        calls.append(live);return resolve(form,stacks,live,last)
    fight['resolve']=measured
    manual=combat_replay.replay(base,context['target'],attacks_per_second=base.fire_rate,
        window_seconds=13.,level=1,headshot_chance=0.,combat=fight,collect_timeline=False)
    assert any(v>0 and v!=int(v) for v in calls), calls
    assert manual['totalWindowDamage']==pytest.approx(expected[0]['totalWindowDamage'],abs=1e-7)
    search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
    actual=search_combat.window(stats,context,score_only=True)
    assert actual['totalWindowDamage']==pytest.approx(manual['totalWindowDamage'],abs=1e-7)

def test_small_capacity_cannot_skip_declared_wait_using_passive_regen(fixture,monkeypatch):
    st,_,fight=fixture(1)
    monkeypatch.setattr(native_replay,'ENABLED',True);monkeypatch.setattr(native_replay,'SHADOW',True)
    next_direct=.8+1.+3.+1/20.+.8
    def run(window):
        return combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,window_seconds=window,combat=fight,headshot_chance=0.,collect_timeline=False)
    assert run(2.601)['shots']==1
    before=run(next_direct-.001);after=run(next_direct+.801)
    assert before['shots']==1 and before['totalWindowDamage']==pytest.approx(200.)
    assert after['shots']==2 and after['totalWindowDamage']==pytest.approx(400.)
    assert after['recharges']==1 and after['reloads']==0


def test_old_native_core_falls_back_for_full_clip_wait_policy(fixture,monkeypatch):
    from types import SimpleNamespace
    st,_,fight=fixture()
    monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace(ORDINARY_CHARGED_WINDUP=1))
    assert not native_replay.supported(st,dict(combat=fight,collect_timeline=False))


def test_actual_galvanized_co_stacks_keep_static_capacity_and_fractional_scale():
    from wfarsenal.damage import mod_effects
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==PATH)
    mod=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Galvanized Shot')
    scenario=Scenario(trigger_policy='emergent')
    effects=mod_effects(mod,mod['maxRank'],scenario)
    fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=scenario),[(mod,mod['maxRank'],None)],[])
    assert fight['conditionOverload']
    stacks={q['id']:q['maxStacks']*.25 for q in fight['trigger_sources']}
    zero,zr=fight['resolve']('selected',stacks,0.)
    whole,wr=fight['resolve']('selected',stacks,1.)
    part,pr=fight['resolve']('selected',stacks,.5)
    assert zero.magazine==whole.magazine==part.magazine==10
    assert zero.ammo_cost==whole.ammo_cost==part.ammo_cost==10
    assert part.total_damage-zero.total_damage==pytest.approx((whole.total_damage-zero.total_damage)*.5)
    assert pr.total_damage-zr.total_damage==pytest.approx((wr.total_damage-zr.total_damage)*.5)
    assert part.total_damage>=1000


def test_battery_parameters_control_actual_charge_cycle(fixture,monkeypatch):
    fx=[ModEffect('WEAPON_BATTERY_REGEN_RATE','STACKING_MULTIPLY',1.),ModEffect('WEAPON_RELOAD_EMPTY_BATTERY','STACKING_MULTIPLY',.5),ModEffect('WEAPON_RELOAD_TIME','ADD',.25)]
    st,_,fight=fixture(4,reload=.5,extra=fx)
    monkeypatch.setattr(native_replay,'ENABLED',True);monkeypatch.setattr(native_replay,'SHADOW',True)
    next_direct=2*.80000001+1.+(3*1.5+.25)/1.5+4/40.
    def run(window):
        return combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,window_seconds=window,combat=fight,headshot_chance=0.,collect_timeline=False)
    assert run(next_direct-.001)['shots']==1
    after=run(next_direct+.801)
    assert after['shots']==2 and after['totalWindowDamage']==pytest.approx(1600.)


@pytest.fixture
def source(monkeypatch):
    data=json.loads((Path(__file__).parent/'fixtures/tenet_plinx_source.json').read_text())
    objects={imp.WEAPON:data['weapon'],imp.PROJECTILE:data['projectile'],
             **{a:{'OnEnter':deepcopy(data['events'])} for a in imp.ATTACHMENTS}}
    class Packages:
        def resolve(self,p): return deepcopy(objects[p])
        def locate(self,owner,ref): return ref if ref.startswith('/') else owner.rsplit('/',1)[0]+'/'+ref
    monkeypatch.setattr(imp,'source_rows',lambda pkg,paths:[])
    return Packages(), objects, {'path':imp.WEAPON}

def test_source_contract_preserves_single_projectile_and_scoring_boundary(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row)
    charge=out['enginePatchContract']['charge']
    assert charge['rawProjectiles']==1 and charge['damageScale']=='ammoAtChargeStart'
    assert charge['requiresFullClip'] and charge['consumesLoadedCapacity']
    assert out['weapons']=={} and out['pending'][0]['defaultScoringExcluded']
    base={'auditedAttacks':{'preserved':1}}
    assert merge_patch(base,out)==base
    radial=out['operationalPatch']['weapons'][imp.WEAPON]['modes']['1']['radial']
    assert radial['damage']=={'radiation':100.} and radial['forcedProcs']==['PT_RAGDOLL']
    assert radial['falloff_reduction']==pytest.approx(.40000001)
