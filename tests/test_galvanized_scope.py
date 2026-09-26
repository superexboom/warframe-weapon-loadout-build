"""GunCO boosts direct damage but does not enter status damage seeds.
Compare independently evaluated scenarios, not a manually divided copy."""
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import Scenario, apply_mods, mod_effects, expected_status_damage

def stats_pair():
    o=app.optimizer
    w=o.resolve_record(app.EXPORTS['weapons'],'/Lotus/Weapons/Tenno/Melee/Axe/AxeWeapon',kind='weapon')
    w,_=o._select_fire_mode(w,0,weapon_type='melee')
    m=o.resolve_record(app.EXPORTS['mods'],'/Lotus/Upgrades/Mods/Melee/WeaponDamageIfVictimProcActive',kind='mod')
    fx=mod_effects(m,rank=m['maxRank'])
    return (apply_mods(w,fx,scenario=Scenario(victim_status_count=0)),
            apply_mods(w,fx,scenario=Scenario(victim_status_count=6)))

def test_co_scales_direct_vector():
    base,boosted=stats_pair()
    assert boosted.total_damage > base.total_damage*1.05

def test_status_seeds_exclude_co_without_manual_rollback():
    base,boosted=stats_pair()
    assert boosted.dot_base_damage==pytest.approx(base.dot_base_damage)
    for st in (base,boosted):
        st.status_chance=0
    def seed(st):
        p=expected_status_damage(st,{},forced_procs={'DT_SLASH':1,'DT_FIRE':1})
        return {k:r['seedPerSecondPerProc'] for k,r in p['dot']['perType'].items()}
    assert seed(base)==pytest.approx(seed(boosted))
