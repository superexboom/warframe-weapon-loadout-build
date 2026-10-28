"""Runtime goldens from the native Angstrum launch/packet closure.

The deterministic fixture retains real preparation/private charge fields while
removing crit/status and fixing refire/reload. Golden damage is 450*N*N before
geometry, resistance and crit; this is an admitted all-hit simulation scenario.
"""
from copy import copy, deepcopy
from types import SimpleNamespace

import pytest
import app
from wfarsenal import combat_replay, native_replay
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare

TARGET = dict(health=1e8, shield=0., armour=0., overguard=0., baseLevel=1,
              healthType="", armourType="", shieldType="", damageController="custom")


def _fixture(n, *, base=.5, multishot=1., ammo_cost=1., first=0., initial_loaded=None, cycle=False, bleed=False):
    name = "Angstrum" if base == .5 else "Prisma Angstrum"
    weapon = deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name))
    combat = prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    real_resolve = combat['resolve']

    def resolve(form, stacks, live_types=0, last_round=False):
        direct, radial = real_resolve('selected',stacks,live_types,last_round)
        direct=copy(direct);radial=copy(radial)
        for part in (direct,radial):
            part.crit_chance=0.;part.status_chance=0.
            part.multishot=multishot*float(stacks.get('__chargeVolleyRounds',1.))
            part.fire_rate=2.;part.magazine=float(n);part.reload_time=1.;part.ammo_cost=ammo_cost
            part.first_shot_damage_bonus=0.;part.faction_damage_multipliers={}
            if initial_loaded is not None and stacks.get('half-magazine',0.):
                part.magazine=float(initial_loaded)
        direct.damage_types={'DT_EXPLOSION':200.};radial.damage_types={'DT_EXPLOSION':250.}
        direct.first_shot_damage_bonus=first
        if bleed:
            direct.native_forced_procs={'DT_SLASH':1.}
        direct._charge_time=base
        assert direct._charge_volley
        if form=='incarnon':
            direct.damage_types={'DT_EXPLOSION':10.};direct.magazine=2.;direct.ammo_cost=1.
            direct.multishot=1.;direct.first_shot_damage_bonus=0.
            direct.__dict__.pop('_charge_volley',None);direct._charge_time=0.
            return direct,None
        return direct,radial

    combat['resolve']=resolve;combat['trigger_sources']=[];combat['chargeVolley']=True
    if initial_loaded is not None:
        combat['trigger_sources']=[dict(id='half-magazine',label='Capacity change fixture',kind='unused',
            initialStacks=1.,initialDuration=.1,duration=.1,perEvent=0.,maxStacks=1.,decay='reset')]
    combat['cycle']=dict(hits=3.,enterSeconds=.1,exitSeconds=.1,chargeOn='direct_hits',pool=2.) if cycle else None
    stats,_=resolve('base' if cycle else 'selected',{'half-magazine':1.} if initial_loaded is not None else {},0.)
    if initial_loaded is not None:
        stats=copy(stats);stats.magazine=float(initial_loaded)
    return stats,combat


def _run(n, *, native, window, timeline=False, target=None, **kwargs):
    stats,combat=_fixture(n,**kwargs)
    enabled=native_replay.ENABLED;native_replay.ENABLED=native
    before=native_replay.STATS['native']
    try:
        run=combat_replay.replay(stats,target or TARGET,attacks_per_second=stats.sustained_attack_rate,
                                 window_seconds=window,combat=combat,trigger_sources=combat['trigger_sources'],
                                 collect_timeline=timeline,headshot_chance=0.)
    finally:
        native_replay.ENABLED=enabled
    if native and not timeline:
        assert native_replay.STATS['native']>before
    return run


@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('base',[.5,.2])
@pytest.mark.parametrize('n,damage',[(1,450.),(2,1800.),(3,4050.),(4,7200.),(6,16200.)])
def test_full_magazine_volley_waits_before_first_damage_and_scales_twice(native,base,n,damage):
    assert getattr(native_replay.wfcore,'MAGAZINE_CHARGE_VOLLEY',0)
    pending=_run(n,native=native,base=base,window=n*base-.001)
    assert pending['shots']==0 and pending['totalWindowDamage']==0.
    done=_run(n,native=native,base=base,window=n*base+.001,timeline=not native)
    assert done['shots']==1 and done['totalWindowDamage']==pytest.approx(damage)
    if not native:
        event=done['chargeVolley']['events'][0]
        assert event==dict(time=round(n*base,6),loadedRounds=float(n),chargeSeconds=n*base,
                           projectiles=float(n),perProjectileDamageScale=float(n),ammoCost=float(n))
        assert done['timeline'][-1]['ammo']==0.


@pytest.mark.parametrize('native',[False,True])
def test_extra_multishot_applies_once_to_450_n_squared(native):
    result=_run(3,native=native,multishot=2.2,window=1.501,timeline=not native)
    assert result['totalWindowDamage']==pytest.approx(8910.)
    if not native:
        event=result['chargeVolley']['events'][0]
        assert event['projectiles']==pytest.approx(6.6)
        assert event['ammoCost']==3.
        assert result['timeline'][-1]['ammo']==0.


@pytest.mark.parametrize('native',[False,True])
def test_first_shot_damage_preserves_private_zero_postcharge_and_radial_identity(native):
    result=_run(3,native=native,first=1.,window=4.501,timeline=not native)
    # Direct200*2 +radial250, N^2=9; repeated after normal.5refire+1reload+1.5charge.
    assert result['shots']==2
    assert result['totalWindowDamage']==pytest.approx(11700.)
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[1.5,4.5]
        assert [e['ammoCost'] for e in result['chargeVolley']['events']]==[3.,3.]


@pytest.mark.parametrize('native',[False,True])
def test_partial_magazine_uses_loaded_rounds_not_modified_capacity(native):
    result=_run(4,native=native,initial_loaded=2,window=4.501,timeline=not native)
    # First2rounds take1sec/pay1800; reload fills4, secondtakes2sec/pay7200.
    assert result['shots']==2
    assert result['totalWindowDamage']==pytest.approx(9000.)
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[1.,4.5]
        assert [e['loadedRounds'] for e in result['chargeVolley']['events']]==[2.,4.]


@pytest.mark.parametrize('native',[False,True])
def test_ammo_efficiency_keeps_remaining_rounds_for_next_charge(native):
    result=_run(4,native=native,ammo_cost=.5,window=3.501,timeline=not native)
    # Fourrounds spend2; at2.5remaining2take1sec. No reload betweenvolley1/2.
    assert result['shots']==2 and result['reloads']==0
    assert result['totalWindowDamage']==pytest.approx(9000.)
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[2.,3.5]
        assert [e['ammoCost'] for e in result['chargeVolley']['events']]==[2.,1.]


@pytest.mark.parametrize('native',[False,True])
def test_incarnon_cycle_has_no_magazine_charge_and_returns_cleanly(native):
    result=_run(3,native=native,cycle=True,window=7.01,timeline=not native)
    # .5refire+.1enter aftereachbase; alternate2shots at2.1/2.6,
    # .5refire+.1exit, nextbasecharge3.2->4.7. Sixshots=2*4050+4*10.
    assert result['transforms']==4 and result['reloads']==0
    assert result['shots']==6
    assert result['totalWindowDamage']==8150.
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[1.5,4.7]
        assert all(e['loadedRounds']==3. for e in result['chargeVolley']['events'])


@pytest.mark.parametrize('native',[False,True])
def test_target_death_does_not_reset_next_volley_charge(native):
    result=_run(3,native=native,window=4.501,target=dict(TARGET,health=100.),timeline=not native)
    assert result['shots']==2
    assert result['firstKillTime']==pytest.approx(1.5)
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[1.5,4.5]


def test_old_core_without_volley_feature_is_rejected(monkeypatch):
    stats,combat=_fixture(3)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'wfcore',SimpleNamespace())
    assert not native_replay.supported(stats,dict(combat=combat,collect_timeline=False))


@pytest.mark.parametrize('native',[False,True])
def test_bleed_kill_during_second_charge_keeps_pending_completion(native):
    result=_run(3,native=native,window=4.501,target=dict(TARGET,health=5000.),
                timeline=not native,bleed=True)
    assert result['shots']==2
    assert result['firstKillTime']==pytest.approx(3.5)
    if not native:
        assert [e['time'] for e in result['chargeVolley']['events']]==[1.5,4.5]


@pytest.mark.parametrize('name,base',[('Angstrum',.5),('Prisma Angstrum',.2)])
def test_real_profile_charge_duration_scales_with_fire_rate_and_magazine(name,base):
    from wfarsenal.damage import ModEffect
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name))
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[
        ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',1.)],scenario=Scenario()),[],[])
    direct,radial=combat['resolve']('selected',{},0.)
    assert direct._charge_time==pytest.approx(base/2.)
    assert direct.magazine==6.
    assert direct._charge_volley and radial is not None


@pytest.mark.parametrize('name',['Angstrum','Prisma Angstrum'])
def test_real_incarnon_mode_has_no_volley_private_marker(name):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name))
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=Scenario()),[],[])
    direct,_=combat['resolve']('selected',{},0.)
    assert not getattr(direct,'_charge_volley',None)


@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('operation,value,spawn,damage',[
    ('ADD',1.,4.,5400.),
    ('SET',2.,2.,2700.),
    ('STACKING_MULTIPLY',1.2,6.6,8910.),
])
def test_actual_modded_spawn_count_uses_charged_base_before_mod_operation(
        native,operation,value,spawn,damage,monkeypatch):
    from wfarsenal.damage import ModEffect,apply_mods
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Angstrum'))
    effects=[ModEffect('WEAPON_FIRE_ITERATIONS',operation,value)]
    scenario=Scenario()
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=scenario),[],[])
    original=combat['resolve']
    seen=[]
    def resolve(form,stacks,live_types=0,last_round=False):
        direct,radial=original(form,stacks,live_types,last_round)
        if stacks.get('__chargeVolleyRounds'):
            seen.append((stacks['__chargeVolleyRounds'],direct.multishot,radial.multishot))
        direct,radial=copy(direct),copy(radial)
        direct.crit_chance=radial.crit_chance=0.
        direct.status_chance=radial.status_chance=0.
        return direct,radial
    combat['resolve']=resolve
    stats=apply_mods(weapon,effects,scenario=scenario)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    before=native_replay.STATS['native']
    result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.sustained_attack_rate,
                               window_seconds=1.501,combat=combat,trigger_sources=[],
                               collect_timeline=not native,headshot_chance=0.)
    assert result['shots']==1
    assert result['totalWindowDamage']==pytest.approx(damage)
    assert seen and seen[-1]==pytest.approx((3.,spawn,spawn))
    if native:
        assert native_replay.STATS['native']>before
    else:
        event=result['chargeVolley']['events'][0]
        assert event['projectiles']==pytest.approx(spawn)
        assert event['ammoCost']==3.


def test_real_angstrum_kill_attribution_resume_is_next_landed_volley(monkeypatch):
    from wfarsenal.damage import apply_mods
    from wfarsenal.proc_probability import KillAttribution
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Angstrum'))
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    original=combat['resolve']
    def resolve(*args):
        direct,radial=original(*args);direct,radial=copy(direct),copy(radial)
        direct.crit_chance=radial.crit_chance=0.
        direct.status_chance=radial.status_chance=0.
        return direct,radial
    combat['resolve']=resolve
    crossings=[];crossing=KillAttribution.crossing
    def capture(self,time,remaining,resume=None):
        crossings.append((time,resume))
        return crossing(self,time,remaining,resume)
    monkeypatch.setattr(KillAttribution,'crossing',capture)
    monkeypatch.setattr(native_replay,'ENABLED',False)
    stats=apply_mods(weapon,[],scenario=Scenario())
    result=combat_replay.replay(stats,dict(TARGET,health=100.),
                               attacks_per_second=stats.sustained_attack_rate,
                               window_seconds=1.501,combat=combat,trigger_sources=[],
                               collect_timeline=True,headshot_chance=0.)
    assert result['shots']==1 and crossings
    # Current lands1.5; refire.5 +reload2.5 +nextcharge1.5 ->nextlands6.0.
    assert crossings[0]==pytest.approx((1.5,6.0))


@pytest.mark.parametrize('n',[1,3,6])
@pytest.mark.parametrize('status_add,direct_sc,radial_sc',[
    (0.,.25999999,.10000000149011612),
    (.1,.35999999,.20000000149011612),
])
@pytest.mark.parametrize('ms_operation,ms_value',[
    ('ADD',1.),('SET',2.),('STACKING_MULTIPLY',1.2),
])
def test_prisma_per_projectile_status_keeps_raw_one_iteration_denominator(
        n,status_add,direct_sc,radial_sc,ms_operation,ms_value):
    from wfarsenal.damage import ModEffect
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Prisma Angstrum'))
    effects=[ModEffect('WEAPON_PROC_CHANCE','ADD',status_add),
             ModEffect('WEAPON_FIRE_ITERATIONS',ms_operation,ms_value)]
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=Scenario()),[],[])
    direct,radial=combat['resolve']('selected',{'__chargeVolleyRounds':float(n)},0.)
    # Direct is explicit .25999999; radial inherits native float32 .1.
    # The raw normalization denominator remains1 despite charged/modded spawns.
    assert direct.status_chance==pytest.approx(direct_sc,rel=1e-12,abs=1e-12)
    assert radial.status_chance==pytest.approx(radial_sc,rel=1e-12,abs=1e-12)
    assert direct.status_chance!=pytest.approx(radial.status_chance)
    expected_spawn=(n+1. if ms_operation=='ADD' else 2. if ms_operation=='SET' else n*2.2)
    assert direct.multishot==pytest.approx(expected_spawn)
    assert radial.multishot==pytest.approx(expected_spawn)
