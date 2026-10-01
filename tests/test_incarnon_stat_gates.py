from copy import deepcopy

import pytest
import app
from wfarsenal.damage import Scenario,ModEffect,apply_mods,quantize_base_crit_damage
from wfarsenal.event_profiles import co_profile


def weapon(name,mode=0):
    full = deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name))
    return app.optimizer._select_fire_mode(full,mode,weapon_type=app.optimizer._weapon_type(None,full))[0]


@pytest.mark.parametrize('name,mode,ratio',[('Arca Plasmor',0,2.),('Fulmin',0,2.),('Fulmin',1,1.5)])
def test_gunco_behavior_is_per_attack(name,mode,ratio):
    w = weapon(name,mode)
    mods = [ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.)]
    base = apply_mods(w,mods)
    live = apply_mods(w,[*mods,ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',1.)],
                      scenario=Scenario(victim_status_count=1))
    assert live.total_damage/base.total_damage==pytest.approx(ratio)


def test_gunco_does_not_use_excluded_incarnon_flat_base():
    w = weapon('Torid',1)
    source = co_profile(w)['excludeFlatSources'][0]
    effects = [ModEffect('WEAPON_DAMAGE_AMOUNT','ADD_BASE',51.,source_path=source),
               ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.)]
    base = apply_mods(w,effects)
    live = apply_mods(w,[*effects,ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',1.)],scenario=Scenario(victim_status_count=1))
    assert base.total_damage==pytest.approx(204.)
    assert live.total_damage==pytest.approx(255.)


def test_anti_status_crit_damage_reads_distinct_types_and_is_flat_after_mods():
    w = weapon('Phenmor')
    fx = [ModEffect('WEAPON_CRIT_DAMAGE','STACKING_MULTIPLY',1.),
          ModEffect('WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX','SET',3.),
          ModEffect('WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS','ADD',1.)]
    values = [apply_mods(w,fx,scenario=Scenario(victim_status_count=n)).crit_multiplier for n in (0,2,3)]
    base = apply_mods(w,fx[:1]).crit_multiplier
    assert values==pytest.approx([base+1,base+1,base])


def test_prelude_crit_multiplier_rechecks_modded_threshold_and_base_bonus():
    w = weapon('Furis',1)
    fx = [ModEffect('WEAPON_LOW_CRIT_VALUE','SET_BASE',.4),ModEffect('WEAPON_LOW_CRIT_DAMAGE','ADD_BASE',3.),
          ModEffect('WEAPON_CRIT_DAMAGE','STACKING_MULTIPLY',1.)]
    below = apply_mods(w,fx)
    above = apply_mods(w,[*fx,ModEffect('WEAPON_CRIT_CHANCE','STACKING_MULTIPLY',1.)])
    base = w['fireModes'][0]['damage']['critMultiplier']
    assert below.crit_multiplier==pytest.approx(quantize_base_crit_damage(base+3)*2)
    assert above.crit_multiplier==pytest.approx(quantize_base_crit_damage(base)*2)


def test_multishot_bonus_only_amplifies_generated_projectiles():
    w = weapon('Braton Prime',1)
    bonus = ModEffect('WEAPON_AMMO_POOL_MULTISHOT_DAMAGE','STACKING_MULTIPLY',.54)
    assert apply_mods(w,[bonus]).total_damage==apply_mods(w,[]).total_damage
    fx = [ModEffect('WEAPON_FIRE_ITERATIONS','ADD',2.)]
    base = apply_mods(w,fx)
    live = apply_mods(w,[*fx,bonus])
    assert live.total_damage*live.multishot/(base.total_damage*base.multishot)==pytest.approx((1.+2*1.54)/3)
    assert live.ammo_pool_multishot_cost==2


@pytest.mark.parametrize('name,mode,total',[('Dread',1,400.),('Paris Prime',1,520.),('Miter',0,250.),('Corvas',0,80.),('Velocitus',0,3200.)])
def test_charge_projectile_is_authoritative_and_archguns_stay_on_ground(name,mode,total):
    w = weapon(name,mode)
    assert sum(w['fireModes'][0]['damage']['types'].values())==pytest.approx(total,abs=.01)
    if name=='Corvas':
        assert w['fireModeSource']=='HeavyBehaviors' and w['fireModes'][0]['multishot']==11


def test_projectile_speed_changes_falloff_without_a_spread_model():
    w = weapon('Arca Plasmor')
    scenario = Scenario(distance=15.)
    base = apply_mods(w,[],scenario=scenario)
    doubled = apply_mods(w,[ModEffect('WEAPON_PROJECTILE_SPEED','STACKING_MULTIPLY',1.)],scenario=scenario)
    assert doubled.projectile_speed_multiplier==2.
    assert doubled.falloff_multiplier>=base.falloff_multiplier
    assert doubled.total_damage==base.total_damage
    assert doubled.spread_min_deg is None


def test_archgun_charge_rate_is_separate_from_fire_rate():
    from wfarsenal.manual_combat import prepare
    w = weapon('Velocitus')
    def stats(fx):
        combat = prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=Scenario()),[],[])
        return combat['resolve']('selected',{},0)[0]
    bare = stats([])
    fast_fire = stats([ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',1.)])
    fast_charge = stats([ModEffect('WEAPON_CHARGE_RATE','STACKING_MULTIPLY',1.)])
    assert fast_fire._charge_time==bare._charge_time
    assert fast_fire.fire_rate==pytest.approx(bare.fire_rate*2)
    assert fast_charge._charge_time==pytest.approx(bare._charge_time/2)
    assert fast_charge.fire_rate==bare.fire_rate


def test_corvas_ground_full_charge_reads_trace_damage_multiplier_once():
    from wfarsenal.manual_combat import prepare
    w=weapon('Corvas')
    assert w['fireModes'][0]['chargeDamageMultiplier']==2
    combat=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    stats,_=combat['resolve']('selected',{},0)
    assert stats.total_damage==pytest.approx(160.)
    assert stats.multishot==11 and stats._charge_time==.5


def test_archgun_aiming_crit_modifiers_are_applied_once():
    w=weapon('Corvas')
    bare=apply_mods(w,[],scenario=Scenario(aiming=True))
    fx=[ModEffect('WEAPON_CRIT_CHANCE','STACKING_MULTIPLY',5.,valid_modifiers=('PM_AIM',)),
        ModEffect('WEAPON_CRIT_DAMAGE','STACKING_MULTIPLY',5.,valid_modifiers=('PM_AIM',))]
    aimed=apply_mods(w,fx,scenario=Scenario(aiming=True))
    hip=apply_mods(w,fx,scenario=Scenario(aiming=False))
    assert aimed.crit_chance==pytest.approx(bare.crit_chance*6)
    assert aimed.crit_multiplier==pytest.approx(bare.crit_multiplier*6)
    assert hip.crit_chance==bare.crit_chance and hip.crit_multiplier==bare.crit_multiplier
