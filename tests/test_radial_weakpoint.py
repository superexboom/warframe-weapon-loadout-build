from copy import deepcopy
from dataclasses import replace, asdict

import pytest
import app
from wfarsenal.damage import (ModdedStats, apply_mods, damage_against,
    damage_against_cached_armour, expected_status_damage, enemy_kill_metrics, enemy_defenses)
from wfarsenal.combat_replay import replay


def target():
    return dict(health=1e9, armour=300, shield=0, overguard=0, level=1,
                factionResistance='RK_NEUTRAL', headshotMultiplier=3.)


def stats(**overrides):
    values=dict(damage_types={'DT_FIRE':100., 'DT_EXPLOSION':100.},
        crit_chance=.4, crit_multiplier=3., status_chance=1., multishot=1.,
        fire_rate=4., magazine=100., reload_time=1., dot_base_damage=200.,
        weakpoint_damage_bonus=3.5, weakpoint_crit_chance_relative=3.5,
        base_crit_chance=.4, headshot_bonus_multiplier=1.3, radial_only=True)
    return ModdedStats(**{**values, **overrides})


@pytest.mark.parametrize('name,mode', [('Simulor',0),('Synoid Simulor',0),
    ('Stug',0),('Stug',1),('Stug',2),('Mutalist Quanta',1),
    ('Castanas',0),('Sancti Castanas',0)])
def test_exported_explosion_preserves_attack_type(name,mode):
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    st=apply_mods(w,[],fire_mode=mode)
    assert st.radial_only
    assert app._benchmark_timeline_stats(asdict(st)).radial_only
    assert damage_against(st,target(),hit_location='head')['perShot'] == pytest.approx(
        damage_against(st,target(),hit_location='body')['perShot'])


@pytest.mark.parametrize('reducer',[damage_against, expected_status_damage, enemy_kill_metrics])
def test_explosion_head_and_body_are_identical_in_all_reducers(reducer):
    st=stats()
    assert reducer(st,target(),hit_location='head') == reducer(st,target(),hit_location='body')


def test_cached_head_proxy_cannot_override_radial_semantics():
    st=stats(); tg=target(); defenses=enemy_defenses(tg)
    cache=dict(hit_multiplier=3.,hit_critical_multiplier=2.,faction_deltas={},
        armour_bypass=set(),shield_bypass=set(),target_faction='')
    original=deepcopy(cache)
    a=damage_against_cached_armour(st,300,defenses,target=tg,_target_cache=cache)
    b=damage_against_cached_armour(st,300,defenses,target=tg,hit_location='body')
    assert a['perShot'] == pytest.approx(b['perShot'])
    assert cache == original
    direct=replace(st,radial_only=False)
    assert damage_against(direct,tg,hit_location='head')['perShot'] > b['perShot']


@pytest.mark.parametrize('charge_on',['headshots','direct_hits'])
def test_radial_events_cannot_trigger_head_buffs_or_incarnon_charge(charge_on):
    st=stats(status_chance=0.)
    sources=[dict(id=k,label=k,kind=k,duration=10,maxStacks=100,perEvent=1)
             for k in ['on-hit','on-crit','on-headshot','on-headshot-kill']]
    combat=dict(resolve=lambda *a:(st,None),cycle=dict(hits=1.,pool=50.,
        enterSeconds=.1,exitSeconds=.1,chargeOn=charge_on))
    result=replay(st,{**target(),'health':1.},attacks_per_second=4.,window_seconds=2.,
        headshot_chance=1.,trigger_sources=sources,combat=combat)
    assert result['killEvents'] > 0
    assert result['transforms'] == 0
    series={r['kind']:r for r in result['triggerSeries']}
    assert series['on-hit']['avgStacks'] > 0
    assert series['on-crit']['avgStacks'] > 0
    assert series['on-headshot']['avgStacks'] == 0
    assert series['on-headshot-kill']['avgStacks'] == 0


def test_live_radial_heat_seed_is_independent_of_headshot_setting():
    st=stats()
    args=dict(attacks_per_second=4.,window_seconds=4.)
    body=replay(st,target(),headshot_chance=0.,**args)
    head=replay(st,target(),headshot_chance=1.,**args)
    assert head['totalWindowDamage']==pytest.approx(body['totalWindowDamage'])
    assert head['dotWindow'] > 0
    assert head['dotWindow']==pytest.approx(body['dotWindow'])


def test_impact_delegate_wins_only_without_real_projectile_damage(tmp_path):
    from wfarsenal.packages import PackageIndex
    from wfarsenal.extract import _resolve_damage
    import json
    path='/Lotus/Weapons/Corpus/Pistols/CrpAirPistol/CrpAirPistolProjectile'
    f=tmp_path/(path.lstrip('/')+'.json');f.parent.mkdir(parents=True)
    projectile=dict(AttackData=dict(Amount=0,Type='DT_IMPACT'),
        DealDamageThroughImpactBehavior=1,CriticalChance=.1,CriticalMultiplier=2.,
        ExplosiveAttack=dict(Amount=50,Type='DT_IMPACT',ProcChance=.25))
    impact=dict(AttackData=dict(Amount=150,Type='DT_IMPACT',ProcChance=0),
                criticalHitChance=0.,criticalHitDamageMultiplier=2.)
    fire=dict(projectileType=path)
    f.write_text(json.dumps(projectile),encoding='utf-8')
    got=_resolve_damage(PackageIndex(tmp_path),'/Lotus/Weapons/Corpus/Pistols/CrpAirPistol/CrpAirPistolArray',fire,impact)
    assert got['source']=='ImpactBehavior'
    assert got['total']==150. and got['critChance']==0.
    assert got['radial']['total']==50.
    # A different mine can inherit the same delegation flag and a bogus impact.
    other=_resolve_damage(PackageIndex(tmp_path),'/Lotus/Weapons/Test/Mine',fire,impact)
    assert other['source']=='ExplosiveAttack' and other['total']==50.
    projectile['AttackData']['Amount']=25
    f.write_text(json.dumps(projectile),encoding='utf-8')
    got=_resolve_damage(PackageIndex(tmp_path),'/Lotus/Weapons/Corpus/Pistols/CrpAirPistol/CrpAirPistolArray',fire,impact)
    assert got['total']==25.
    assert got['critChance']==.1


def test_sonicor_shipped_vector_is_the_native_delegated_impact():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Sonicor')
    st=apply_mods(w,[])
    assert not st.radial_only
    assert st.total_damage==150.
    assert st.crit_chance==st.status_chance==0.
    from wfarsenal.event_profiles import base_profile
    profile=base_profile(w)
    assert profile['radial']['damage']=={'impact':50.}
    assert profile['radial']['takes_multishot'] is True


@pytest.mark.parametrize('multishot',[1.,2.5])
def test_native_forced_electricity_survives_zero_status_and_element_combination(multishot):
    from wfarsenal.damage import expected_status_procs
    st=stats(damage_types={'DT_MAGNETIC':100.},status_chance=0.,
             multishot=multishot,native_forced_procs={'DT_ELECTRICITY':1.})
    assert expected_status_procs(st)=={'DT_ELECTRICITY':multishot}
    assert expected_status_procs(st,forced_procs={'DT_ELECTRICITY':.5})=={
        'DT_ELECTRICITY':multishot+.5}
    r=replay(st,target(),attacks_per_second=4.,window_seconds=2.)
    assert r['dotByType']['DT_ELECTRICITY'] > 0
    from wfarsenal.status_arcanes import encumber_roll
    assert encumber_roll(st,.24)[0] > 0
    assert encumber_roll(replace(st,native_forced_procs={}),.24)[0]==0


def test_forced_status_stays_on_its_own_component():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Simulor')
    assert apply_mods(w,[]).native_forced_procs=={'DT_ELECTRICITY':1.}
    # The mine's midflight blast has no forced electricity. The embed-death
    # alternative does; never merge them before their activation is selected.
    mine=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Castanas')
    assert apply_mods(mine,[]).native_forced_procs=={}
    modified=deepcopy(mine)
    modified['fireModes'][0]['damage'].update(source='EmbedDeathAttack',forcedProcs=['PT_ELECTROCUTION'])
    assert apply_mods(modified,[]).native_forced_procs=={'DT_ELECTRICITY':1.}
