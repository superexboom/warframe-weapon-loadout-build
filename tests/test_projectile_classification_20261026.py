"""Measured blob classifications, per-event flat base and transform timing."""
from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, damage_against, quantize_base_crit_damage
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay
from tests.test_combat_replay import target


def stug(mode, *, flat=300., damage=2.2, head_bonus=.3, extra=()):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Stug'))
    weapon['isIncarnonForm']=mode==2
    fx=[ModEffect('WEAPON_DAMAGE_AMOUNT','ADD_BASE',flat),
        ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',damage),
        ModEffect('WEAPON_HEADSHOT_MULTIPLIER','ADD',head_bonus),*extra]
    combat=prepare(dict(weapon=weapon,fire_mode=mode,effects=fx,scenario=Scenario()),[],[])
    stats,_=combat['resolve']('selected',{},0)
    return stats,combat


@pytest.mark.parametrize('mode,stack,embed,blast',[(0,1,972.8,1200.),(0,2,985.6,1440.),
                                                 (0,4,1011.2,1920.),(2,1,1120.,1600.),(2,2,1280.,2240.)])
def test_m127_stack_bonus_does_not_multiply_evolution_flat_base(monkeypatch,mode,stack,embed,blast):
    monkeypatch.setattr(native_replay,'SHADOW',True)
    stats,combat=stug(mode,head_bonus=0.)
    stats.multishot=stack
    for part in stats._stackable[1].values():part.crit_chance=part.status_chance=0.
    stats.fire_rate=.1
    combat['resolve']=lambda *_:(stats,None)
    combat['projectileState']={'stugChildHits':0}
    result=replay(stats,target(),attacks_per_second=.1,window_seconds=1.51,combat=combat,collect_timeline=False)
    assert result['directWindow']==pytest.approx(2*embed+blast)


def test_m127_main_blast_has_head_bonus_and_headcrit_but_no_head_location_or_weak_damage():
    stats,_=stug(0)
    part=stats._stackable[1]['explosion']
    head=target(hitProxies=[dict(part='HEAD',damageAtten=2.,criticalMultiplier=2.)])
    for tier,expected in [(0,1560.),(1,4681.142857142857),(2,7802.285714285715)]:
        p=replace(part,crit_chance=float(tier),weakpoint_damage_bonus=3.5)
        assert damage_against(p,head,hit_location='head')['perShot']==pytest.approx(expected)
    tick=replace(stats._stackable[1]['embed'],crit_chance=0.)
    assert damage_against(tick,head,hit_location='head')['perShot']==pytest.approx(972.8)


@pytest.mark.parametrize('mode',[0,1,2])
def test_main_blast_keeps_weakpoint_crit_and_rejects_gunco_payload(mode):
    extra=[ModEffect('WEAPON_CRIT_CHANCE_BODY_PART','STACKING_MULTIPLY',3.5,symbol_filter='HEAD'),
           ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',1.2)]
    stats,combat=stug(mode,extra=extra)
    lit,_=combat['resolve']('selected',{},3)
    assert lit.damage_types==stats.damage_types
    assert lit._stackable[1]['explosion'].damage_types==stats._stackable[1]['explosion'].damage_types
    main=stats._stackable[1]['explosion']
    assert main.area_direct and not main.radial_only
    assert main.weakpoint_crit_chance_relative==pytest.approx(3.5)
    assert all(p.weakpoint_crit_chance_relative==0 for k,p in stats._stackable[1].items() if k!='explosion')


def test_stug_corpse_keeps_fuse_and_ticks(monkeypatch):
    from tests.test_stackable_projectiles import setup
    monkeypatch.setattr(native_replay,'SHADOW',True)
    stats,combat=setup('Stug',rate=.1)
    result=replay(stats,target(1.),attacks_per_second=.1,window_seconds=1.51,combat=combat,collect_timeline=False)
    assert result['killEvents']==3  # creation, attached tick, main explosion


@pytest.mark.parametrize('native',[False,True])
def test_incarnon_transform_uses_reload_speed_bucket(monkeypatch,native):
    from wfarsenal import mods_native
    monkeypatch.setattr(native_replay,'ENABLED',native)
    monkeypatch.setattr(mods_native,'ENABLED',native)
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Vectis Prime'))
    weapon['isIncarnonForm']=True
    fx=[ModEffect('WEAPON_RELOAD_SPEED','STACKING_MULTIPLY',.6),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',4.)]
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=fx,scenario=Scenario(aiming=True,incarnon_cycle=True)),[],[],cycle_enabled=True)
    stats,_=combat['resolve']('base',{},0)
    assert stats.transform_time_scale==pytest.approx(.625)
    result=replay(stats,target(),attacks_per_second=stats.fire_rate,window_seconds=1.1,combat=combat,headshot_chance=1.)
    events=result['sniperCombo']['events']
    assert events[1]['time']==pytest.approx(1/stats.fire_rate+combat['cycle']['enterSeconds']*.625)


@pytest.mark.parametrize('dtype,ratio',[('DT_ELECTRICITY',1.3**2),('DT_GAS',1.3**2),('DT_FIRE',1.3)])
def test_deadhead_second_head_bracket_is_already_in_status_seed(dtype,ratio):
    from tests.test_combat_replay import stats
    from wfarsenal.damage import expected_dot_damage
    plain=stats(damage_types={dtype:160.},headshot_bonus_multiplier=1.)
    bonus=replace(plain,headshot_bonus_multiplier=1.3)
    foe=target(hitProxies=[dict(part='HEAD',damageAtten=2.,criticalMultiplier=2.)])
    seed=lambda s:expected_dot_damage(s,foe,hit_location='head')['perType'][dtype]['seedPerSecondPerProc']
    assert seed(bonus)/seed(plain)==pytest.approx(ratio)


def test_old_status_core_refuses_area_direct_stats(monkeypatch):
    from wfarsenal import status_native
    stats,_=stug(0)
    monkeypatch.setattr(status_native,'wfcore',object())
    with pytest.raises(status_native.Unsupported,match='area direct'):
        status_native.score(stats._stackable[1]['explosion'],target(),{},
                            status_rate_multiplier=1.,damage_rate_multiplier=1.,total=True)


def test_area_direct_sustained_score_matches_reference(monkeypatch):
    from wfarsenal import status_native
    monkeypatch.setattr(status_native,'SHADOW',True)
    stats,_=stug(0)
    foe=target(hitProxies=[dict(part='HEAD',damageAtten=2.,criticalMultiplier=2.)])
    status_native.score(stats._stackable[1]['explosion'],foe,dict(hit_location='head'),
                        status_rate_multiplier=1.,damage_rate_multiplier=1.,total=True)
