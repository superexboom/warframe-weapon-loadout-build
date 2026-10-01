from copy import deepcopy
import pytest
import app
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def test_mutalist_quanta_orb_stack_and_shield_damage_radial_are_explicit():
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta'))
    scenario=Scenario(trigger_policy='emergent',combat_state={'projectileMode':'isolated','orbAbsorbedDamage':300.,'orbAbsorbedDamageType':'DT_FIRE'})
    mod=next(m for m in app.EXPORTS['mods'] if m['path']=='/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/InfCrpShockSwarmRifleArbitrationMod')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=scenario),[(mod,5,None)],[])
    stats,_=combat['resolve']('selected',{},0)
    result=replay(stats,target(1e12),attacks_per_second=.5,window_seconds=10.,combat=combat)
    events=result['projectileEvents']
    assert any(e['kind']=='orbRadial' and e['damageScale']==1. for e in events)
    assert stats._stackable[1]['orbRadial'].damage_types=={'DT_FIRE':600.}
    assert result['projectileLifecycle']['explosions']==1


def test_mutalist_quanta_without_absorbed_damage_fails_closed_with_trace():
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta'))
    scenario=Scenario(trigger_policy='emergent',combat_state={'projectileMode':'isolated'})
    mod=next(m for m in app.EXPORTS['mods'] if m['path']=='/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/InfCrpShockSwarmRifleArbitrationMod')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=scenario),[(mod,5,None)],[])
    stats,_=combat['resolve']('selected',{},0)
    result=replay(stats,target(1e12),attacks_per_second=.5,window_seconds=10.,combat=combat)
    assert any(e['kind']=='orb-radial-unresolved' for e in result['projectileEvents'])


def test_bursting_mass_absorbed_packet_needs_mod_and_does_not_take_weapon_mods_twice():
    from wfarsenal.damage import ModEffect
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta'))
    scenario=Scenario(combat_state={'orbAbsorbedDamage':300.,'orbAbsorbedDamageType':'DT_FIRE'})
    effects=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',10.)]
    mod=next(m for m in app.EXPORTS['mods'] if m['path']=='/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/InfCrpShockSwarmRifleArbitrationMod')
    for cards,amount in [([],None),([(mod,0,None)],150.),([(mod,5,None)],600.)]:
        combat=prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=scenario),cards,[])
        stats,_=combat['resolve']('selected',{},0)
        part=stats._stackable[1].get('orbRadial')
        assert (part.total_damage if part else None)==amount


def test_mq_shield_applies_native_post_coalescing_damage_and_first_crit_damage():
    from wfarsenal.damage import ModEffect,apply_mods
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta')
    effects=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
             ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',1.,damage_type='DT_FIRE')]
    bare=apply_mods(weapon,effects)
    passed=apply_mods(weapon,effects,scenario=Scenario(combat_state={'orbPasses':1}))
    assert passed.damage_types['DT_FIRE']==pytest.approx(33.)
    assert passed.damage_types['DT_ELECTRICITY']==pytest.approx(33.)
    assert 'DT_RADIATION' not in passed.damage_types
    assert passed.crit_chance==pytest.approx(.275)
    assert passed.crit_multiplier==pytest.approx(bare.crit_multiplier*1.25)
    assert passed.victim_full_crit_chance==0
    twice=apply_mods(weapon,effects,scenario=Scenario(combat_state={'orbPasses':2}))
    assert twice.crit_chance==pytest.approx(.525)
    assert twice.crit_multiplier==passed.crit_multiplier
    assert twice.damage_types['DT_ELECTRICITY']==pytest.approx(43.56)


def test_mq_merged_proxy_and_special_proxy_are_distinct_native_records():
    from wfarsenal.damage import apply_mods
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta')
    merged=apply_mods(weapon,[],scenario=Scenario(combat_state={'orbPasses':1,'orbStacks':2}))
    assert merged.damage_types['DT_ELECTRICITY']==pytest.approx(60.5)
    special=apply_mods(weapon,[],scenario=Scenario(combat_state={'orbPasses':1,'orbStacks':3,'orbSpecialShield':True}))
    assert special.damage_types['DT_ELECTRICITY']==pytest.approx(54.45)
    assert special.damage_types['DT_RADIATION']==pytest.approx(21.78)
    assert special.crit_chance==pytest.approx(.525)
    radial=apply_mods(weapon,[],fire_mode=1,scenario=Scenario(combat_state={'orbPasses':1,'orbStacks':3}))
    assert 'DT_ELECTRICITY' not in radial.damage_types


def test_absorbed_damage_vector_is_immutable_pickleable_and_preserves_types():
    import pickle
    original={'DT_FIRE':200.,'DT_VIRAL':100.}
    scenario=Scenario(combat_state={'orbAbsorbedDamageTypes':original})
    original['DT_FIRE']=999.
    scenario=pickle.loads(pickle.dumps(scenario))
    assert dict(scenario.combat_state['orbAbsorbedDamageTypes'])=={'DT_FIRE':200.,'DT_VIRAL':100.}
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mutalist Quanta')
    mod=next(m for m in app.EXPORTS['mods'] if m['nameEn']=='Bursting Mass')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=scenario),[(mod,5,None)],[])
    st,_=combat['resolve']('selected',{},0)
    assert st._stackable[1]['orbRadial'].damage_types=={'DT_FIRE':400.,'DT_VIRAL':200.}
