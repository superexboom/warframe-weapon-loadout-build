"""Full clip damage scaling with an explicit conservative recharge strategy."""
from copy import deepcopy
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

@pytest.mark.parametrize('n',[1,2,5,10,15])
def test_scale_uses_modified_capacity_without_changing_multishot(fixture,n):
    st,radial,fight=fixture(n)
    assert sum(st.damage_types.values())==pytest.approx(100*n)
    assert sum(radial.damage_types.values())==pytest.approx(100*n)
    assert st.multishot==radial.multishot==1.
    assert st.ammo_cost==n and st._requires_full_ammo and st._charge_before_fire
    assert st._charge_time==pytest.approx(.8) and st.reload_time==pytest.approx(3+n/20)
    assert not fight['chargeVolley'] and fight['fullClipCharge']==POLICY

@pytest.mark.parametrize('reload',[0.,.5,1.])
def test_reload_speed_shortens_wait_delay_not_refill(fixture,reload):
    st,_,_=fixture(reload=reload)
    assert st.reload_time==pytest.approx(3/(1+reload)+.5)

@pytest.mark.parametrize('op',['ADD_BASE','SET_BASE'])
def test_flat_damage_builds_are_explicitly_rejected(fixture,op):
    with pytest.raises(ValueError,match='flat-add-native-damage-provider'):
        fixture(extra=[ModEffect('WEAPON_DAMAGE_AMOUNT',op,50.)])

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('n,ms',[(1,0.),(10,0.),(15,1.)])
def test_real_preparation_and_replay_match_source_packets(fixture,monkeypatch,n,ms,native):
    st,_,fight=fixture(n,ms=ms)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    before=native_replay.STATS['native']
    def run(t):
        return combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,
            window_seconds=t,combat=fight,headshot_chance=0.,collect_timeline=not native)
    assert run(.799)['shots']==0
    result=run(1.601)
    assert result['shots']==1
    assert result['totalWindowDamage']==pytest.approx(200*n*(1+ms))
    assert result['fullClipCharge']==POLICY
    if native: assert native_replay.STATS['native']>before

@pytest.mark.parametrize('capacity,expected',[(10.49,10),(10.5,11),(14.7,15)])
def test_native_capacity_rounds_half_up_before_charge_scaling(fixture,capacity,expected):
    st,radial,_=fixture(capacity)
    assert st.magazine==st.ammo_cost==expected
    assert sum(st.damage_types.values())==pytest.approx(expected*100.)
    assert sum(radial.damage_types.values())==pytest.approx(expected*100.)

@pytest.mark.parametrize('native',[False,True])
def test_repeated_cycles_wait_then_fully_recharge_and_keep_ammo_cost(fixture,monkeypatch,native):
    st,_,fight=fixture(10)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    result=combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,
        window_seconds=6.901,combat=fight,headshot_chance=0.,collect_timeline=not native)
    assert result['shots']==2 and result['totalWindowDamage']==pytest.approx(4000.)
    assert result['recharges']==1 and result['reloads']==0

@pytest.mark.parametrize('live',[.25,.5,1.25,2.75])
def test_fractional_live_co_rebuild_preserves_n_and_magazine(fixture,live):
    effect=ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','ADD',1.)
    single,_,one=fixture(1,extra=[effect])
    full,_,ten=fixture(10,extra=[effect])
    a,ar=one['resolve']('selected',{'unused-dynamic-source':.4},live)
    b,br=ten['resolve']('selected',{'unused-dynamic-source':.4},live)
    assert sum(b.damage_types.values())==pytest.approx(sum(a.damage_types.values())*10)
    assert sum(br.damage_types.values())==pytest.approx(sum(ar.damage_types.values())*10)
    assert sum(b.damage_types.values())==pytest.approx(1000*(1+live))
    assert b.magazine==b.ammo_cost==10 and b.multishot==1
    assert b._co_spec is None and br._co_spec is None
    assert manual_combat.live_variant(ten['resolve']('selected',{},1.),.5,1) is None


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

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('n',[1,2,4,10])
def test_small_capacities_cannot_skip_declared_wait_using_passive_regen(fixture,monkeypatch,n,native):
    st,_,fight=fixture(n)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    next_direct=.8+1.+3.+n/20.+.8
    def run(window):
        return combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,
            window_seconds=window,combat=fight,headshot_chance=0.,collect_timeline=not native)
    assert run(2.601)['shots']==1
    before=run(next_direct-.001)
    assert before['shots']==1 and before['totalWindowDamage']==pytest.approx(200*n)
    after=run(next_direct+.801)
    assert after['shots']==2 and after['totalWindowDamage']==pytest.approx(400*n)
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
    fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=scenario),
        [(mod,mod['maxRank'],None)],[])
    assert fight['conditionOverload']
    for level in [0.,.25,1.]:
        stacks={q['id']:q['maxStacks']*level for q in fight['trigger_sources']}
        zero,_=fight['resolve']('selected',stacks,0.)
        whole,_=fight['resolve']('selected',stacks,1.)
        part,_=fight['resolve']('selected',stacks,.5)
        assert zero.magazine==whole.magazine==part.magazine==10
        assert zero.ammo_cost==whole.ammo_cost==part.ammo_cost==10
        assert part.total_damage-zero.total_damage==pytest.approx((whole.total_damage-zero.total_damage)*.5)
        assert part.total_damage>=1000

@pytest.mark.parametrize('empty_scale,reload_add,reload_speed,regen_scale',[
    (0.,0.,0.,0.),(.5,.25,.5,1.),(1.,1.,1.,-.5),(0.,0.,-1.5,0.)])
def test_native_battery_query_buckets_apply_in_source_order(fixture,empty_scale,reload_add,reload_speed,regen_scale):
    fx=[ModEffect('WEAPON_RELOAD_EMPTY_BATTERY','STACKING_MULTIPLY',empty_scale),
        ModEffect('WEAPON_RELOAD_TIME','ADD',reload_add),
        ModEffect('WEAPON_BATTERY_REGEN_RATE','STACKING_MULTIPLY',regen_scale)]
    st,_,_=fixture(reload=reload_speed,extra=fx)
    delay=(3*(1+empty_scale)+reload_add)/max(1+reload_speed,.01)
    regen=20*(1+regen_scale)
    assert st.reload_time==pytest.approx(delay+10/regen)
    assert st._full_clip_charge['resolvedEmptyDelaySeconds']==pytest.approx(delay)
    assert st._full_clip_charge['resolvedRegenPerSecond']==pytest.approx(regen)


def test_battery_parameter_for_other_weapon_type_is_not_applied(fixture):
    effect=ModEffect('WEAPON_BATTERY_REGEN_RATE','STACKING_MULTIPLY',9.,valid_type='/DifferentWeapon')
    st,_,_=fixture(extra=[effect])
    assert st.reload_time==pytest.approx(3.5)


def test_nonpositive_regen_cannot_silently_produce_finite_recharge(fixture):
    with pytest.raises(ValueError,match='nonpositive-battery-regen'):
        fixture(extra=[ModEffect('WEAPON_BATTERY_REGEN_RATE','SET',0.)])

@pytest.mark.parametrize('native',[False,True])
def test_battery_parameter_build_matches_replay_cadence(fixture,monkeypatch,native):
    fx=[ModEffect('WEAPON_BATTERY_REGEN_RATE','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_RELOAD_EMPTY_BATTERY','STACKING_MULTIPLY',.5),
        ModEffect('WEAPON_RELOAD_TIME','ADD',.25)]
    st,_,fight=fixture(4,reload=.5,extra=fx)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    next_direct=2*.80000001+1.+(3*1.5+.25)/1.5+4/40.
    def run(window):
        return combat_replay.replay(st,TARGET,attacks_per_second=st.fire_rate,
            window_seconds=window,combat=fight,headshot_chance=0.,collect_timeline=not native)
    assert run(next_direct-.001)['shots']==1
    after=run(next_direct+.801)
    assert after['shots']==2 and after['totalWindowDamage']==pytest.approx(1600.)
