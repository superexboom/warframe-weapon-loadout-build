"""A charged kill-gated alternate waits before damage, without double paying windup."""
from copy import copy
from types import SimpleNamespace
import pytest
import app
from wfarsenal import combat_replay, native_replay
from wfarsenal.damage import Scenario, ModEffect
from wfarsenal.manual_combat import prepare

TARGET = dict(health=5., shield=0., overguard=0., armour=0., baseLevel=1)


def fixture(*, temporary=False, no_kills=False):
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Battacor')
    fight = prepare(dict(weapon=weapon, fire_mode=1, effects=[
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.), ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=Scenario()), [], [])
    original = fight['resolve']
    def resolve(form, stacks, live_types=0, last_round=False):
        direct, _ = original(form, stacks, live_types, last_round)
        direct = copy(direct)
        direct.fire_rate=2.;direct.magazine=60.;direct.reload_time=1.;direct.multishot=1.
        direct.ammo_cost=1.;direct.native_forced_procs={}
        direct._charge_time = .4 if form != 'base' else 0.
        direct.damage_types={'DT_IMPACT': (100.+900.*stacks.get('temporary',0.)) if form!='base' else 10.}
        return direct, None
    fight['resolve']=resolve;fight['baseBurst']=None;fight['incarnonBurst']=None
    fight['baseFireRate']=fight['incarnonFireRate']=2.
    fight['trigger_sources']=[dict(id='temporary', label='temporary fixture', kind='unused',
        initialStacks=1.,initialDuration=.7,duration=.7,perEvent=0.,maxStacks=1.,decay='reset')] if temporary else []
    st,_=resolve('base',{},0.)
    target={**TARGET,'health':1e9} if no_kills else TARGET
    return st,fight,target


def run(native, window, **kwargs):
    st,fight,target=fixture(**kwargs)
    old=native_replay.ENABLED;native_replay.ENABLED=native
    before=native_replay.STATS['native']
    try:
        result=combat_replay.replay(st,target,attacks_per_second=2.,window_seconds=window,
            combat=fight,trigger_sources=fight['trigger_sources'],collect_timeline=False)
    finally:
        native_replay.ENABLED=old
    if native:assert native_replay.STATS['native']>before
    return result


@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('window,shots',[(.499,1),(.501,1),(.899,1),(.901,2),(1.399,2),(1.401,3),(2.299,3),(2.301,4)])
def test_first_alt_waits_and_primary_resume_does_not_pay_charge_twice(native,window,shots):
    assert run(native,window)['shots']==shots


@pytest.mark.parametrize('native',[False,True])
def test_no_kill_cannot_start_alternate_charge(native):
    result=run(native,2.,no_kills=True)
    assert result['transforms']==0
    assert result['shots']==4


def test_native_charge_duration_tracks_fire_rate_before_switch():
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    for bonus,expected in [(0.,.40000001),(1.,.200000005)]:
        combat=prepare(dict(weapon=weapon,fire_mode=1,
            effects=[ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',bonus)],scenario=Scenario()),[],[])
        stats,_=combat['resolve']('selected',{},0.)
        assert stats._charge_time==pytest.approx(expected)
        assert combat['cycle']['chargeBeforeFire']


def test_pending_charge_survives_target_death_and_buff_expiry_at_event_time(monkeypatch):
    # Resolver observes the actual shot instant .9; the temporary buff expired
    # at .7 while charging. This is our explicit completion-snapshot policy,
    # not a claim that untraced native temporary buffs all snapshot identically.
    monkeypatch.setattr(native_replay,'ENABLED',False)
    st,fight,target=fixture(temporary=True)
    original=fight['resolve'];calls=[]
    def resolve(form,stacks,*args):
        calls.append((form,stacks.get('temporary',0.)))
        return original(form,stacks,*args)
    fight['resolve']=resolve
    result=combat_replay.replay(st,target,attacks_per_second=2.,window_seconds=.901,
        combat=fight,trigger_sources=fight['trigger_sources'],collect_timeline=False)
    assert result['shots']==2
    assert ('incarnon',1.) in calls and ('incarnon',0.) in calls
    assert result['killEvents']==2


def test_native_python_state_machine_parity_and_old_core_fallback(monkeypatch):
    assert getattr(native_replay.wfcore,'KILL_CHARGED_WINDUP',0)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    assert run(True,4.,temporary=True)['shots']>3
    st,fight,_=fixture()
    monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace(RELOAD_SCALED_TRANSFORMS=1))
    assert not native_replay.supported(st,dict(combat=fight,collect_timeline=False))


@pytest.mark.parametrize('charges',[1,2,3])
def test_banked_charge_threshold_and_post_modifier_damage_scale(charges,monkeypatch):
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
        ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.)],
        scenario=Scenario(combat_state={'battacorCharges':charges})),[],[])
    assert combat['cycle']['hits']==charges
    assert combat['cycle'].get('damageScale',1.)==charges
    # Controlled repeatable trigger fixture. The first direct primary kills
    # one10000HP victim every.5s; alternate begins after N kills and.4s windup.
    original=combat['resolve']
    def resolve(form,*args):
        st,radial=original(form,*args)
        st=copy(st);st.fire_rate=2.;st._charge_time=.4 if form!='base' else 0.
        st.multishot=1.;st.native_forced_procs={};st.status_chance=0.;st.crit_chance=0.
        if form=='base':
            st.damage_types={'DT_IMPACT':20000.};st.dot_base_damage=20000.
        else:
            radial=copy(radial);radial.native_forced_procs={};radial.status_chance=0.;radial.crit_chance=0.
        return st,radial
    combat['resolve']=resolve;combat['baseBurst']=None;combat['incarnonBurst']=None
    combat['baseFireRate']=2.;combat['incarnonFireRate']=2.
    st,_=resolve('base',{},0.);monkeypatch.setattr(native_replay,'ENABLED',True);monkeypatch.setattr(native_replay,'SHADOW',True)
    before=combat_replay.replay(st,{**TARGET,'health':10000.},attacks_per_second=2.,window_seconds=charges*.5+.399,combat=combat,collect_timeline=False)
    assert before['shots']==charges
    # Life curve captures an unclipped direct packet; inspect native/Python
    # parity separately on statuses where damage scaling feeds proc seeds.
    direct,radial=resolve('incarnon',{},0.)
    assert direct.total_damage==pytest.approx(416.)
    assert radial.total_damage==pytest.approx(416.)
    result=combat_replay.replay(st,{**TARGET,'health':10000.},attacks_per_second=2.,window_seconds=charges*.5+.401,combat=combat,collect_timeline=False)
    assert result['shots']==charges+1
    assert result['directWindow']==pytest.approx(charges*10000.+832.*charges)


@pytest.mark.parametrize('value',[0,4,-1,1.5,True,'3',float('nan')])
def test_invalid_banked_charge_count_is_rejected(value):
    from wfarsenal.simulator import SimulationError
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    with pytest.raises((TypeError,ValueError,SimulationError),match='battacorCharges'):
        prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=Scenario(combat_state={'battacorCharges':value})),[],[])


@pytest.mark.parametrize('charges',[2,3])
def test_real_banked_modes_match_native_with_statuses_and_fractional_co(charges,monkeypatch):
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    fight=prepare(dict(weapon=weapon,fire_mode=1,effects=[
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.8),
        ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.9,damage_type='DT_FIRE'),
        ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',1.2)],
        scenario=Scenario(combat_state={'battacorCharges':charges})),[],[])
    st,_=fight['resolve']('base',{},0.);monkeypatch.setattr(native_replay,'SHADOW',True)
    result=combat_replay.replay(st,{**TARGET,'health':120.},attacks_per_second=st.fire_rate,
        window_seconds=8.,combat=fight,collect_timeline=False)
    assert result['transforms']>0


def test_banked_charge_strategy_round_trips_and_separates_evaluation_context():
    from wfarsenal.optimizer import _requested_scenario, _scenario_context
    one=_requested_scenario({'combatState':{'battacorCharges':1}},'killsPerMinute')
    three=_requested_scenario({'combatState':{'battacorCharges':3}},'killsPerMinute')
    assert _scenario_context(one)['combatState']['battacorCharges']==1
    assert _scenario_context(three)['combatState']['battacorCharges']==3
    assert _scenario_context(one)!=_scenario_context(three)


def test_real_battacor_hit_radial_co_uses_same_charge_scale_as_source():
    from wfarsenal.damage import co_variant
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    fight=prepare(dict(weapon=weapon,fire_mode=1,effects=[
        ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.8)],
        scenario=Scenario(combat_state={'battacorCharges':3})),[],[])
    _direct,radial=fight['resolve']('selected',{},0.)
    assert radial.total_damage==pytest.approx(416.)
    spec=copy(radial._co_spec);spec.victim_status_count=1
    assert co_variant(radial,spec,radial.co_bucket).total_damage==pytest.approx(208.*2.8)
    assert not radial._co_spec.gunco_independent
    assert radial.delayed_radial_hit_event and not radial.radial_victim_crit
    # Charge multiplies both the packet and its CO query base outside resolve.
    scale=fight['cycle']['damageScale']
    assert scale==3
    assert co_variant(radial,spec,radial.co_bucket).total_damage*scale==pytest.approx(208.*3*2.8)


def test_alternate_heat_and_toxin_keep_source_mode_after_primary_resumes(monkeypatch):
    # Actual Battacor source records, with a controlled first primary kill.
    # Alt Heat/Toxin kills after returning to base must not grant PRIMARY_KILL.
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Battacor')
    fight=prepare(dict(weapon=weapon,fire_mode=1,effects=[
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=Scenario()),[],[])
    original=fight['resolve']
    fight['cycle']={**fight['cycle'],'sourceModeKillChargeTrue':True}
    def resolve(form,stacks,*args):
        st,_=original(form,stacks,*args);st=copy(st)
        st.damage_types={'DT_FIRE':70.} if form!='base' else {'DT_IMPACT':1. if stacks.get('done') else 1000.}
        st.fire_rate=2.;st.magazine=60.;st.multishot=1.;st.reload_time=1.
        st.crit_chance=0.;st.status_chance=0.;st._charge_time=.4 if form!='base' else 0.
        st.native_forced_procs={'DT_FIRE':1.,'DT_POISON':1.} if form!='base' else {}
        return st,None
    fight['resolve']=resolve;fight['baseBurst']=fight['incarnonBurst']=None
    fight['baseFireRate']=fight['incarnonFireRate']=2.
    fight['trigger_sources']=[dict(id='done',label='first kill',kind='on-kill',maxStacks=1.,
        perEvent=1.,duration=100.,initialStacks=0.,decay='reset')]
    monkeypatch.setattr(native_replay,'ENABLED',False)
    st,_=resolve('base',{},0.)
    trace=combat_replay.replay(st,{**TARGET,'health':100.},attacks_per_second=2.,
        window_seconds=4.,combat=fight,trigger_sources=fight['trigger_sources'],collect_timeline=True)
    assert trace['killEvents']==2 and trace['transforms']==2
    assert trace['dotWindow']>0 and trace['timeline'][-1]['gauge']==0.
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    compact=combat_replay.replay(st,{**TARGET,'health':100.},attacks_per_second=2.,
        window_seconds=4.,combat=fight,trigger_sources=fight['trigger_sources'],collect_timeline=False)
    assert native_replay.STATS['native']>before
    for key in ('directWindow','dotWindow','shots','killEvents','transforms'):
        assert trace[key]==pytest.approx(compact[key])
