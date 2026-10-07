from copy import deepcopy

import pytest
import app
from wfarsenal.damage import Scenario,damage_against,expected_status_damage
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def setup(name,choices,state=None):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name))
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent',combat_state=state or {})),[],[],incarnon_choices=choices)
    return weapon,combat,combat['resolve']('selected',{q['id']:q.get('initialStacks',0) for q in combat['trigger_sources']},0)[0]


def test_furis_instant_headshot_reload_keeps_the_base_clip_loaded():
    _,combat,stats=setup('Furis',{'tier3':'3-3'})
    assert combat['magazineRestore']==dict(kind='on-headshot',fraction=1.)
    for heads,expected in [(0.,True),(1.,False)]:
        result=replay(stats,target(),attacks_per_second=stats.fire_rate,window_seconds=20.,headshot_chance=heads,combat=combat)
        assert (result['reloads']>0) is expected


def test_gorgon_empty_reload_growth_refills_only_added_magazine_capacity():
    _,combat,stats=setup('Gorgon',{'tier3':'3-1'})
    assert combat['refillMagazineGrowth']
    # 60 s: three empty reloads complete even with the Gorgon's fire-rate spin-up.
    result=replay(stats,target(),attacks_per_second=stats.fire_rate,window_seconds=60.,combat=combat,trigger_sources=combat['trigger_sources'])
    sources=result['triggerSeries']
    assert max(sources[0]['series'])==3
    source=combat['trigger_sources'][0]
    full,_=combat['resolve']('selected',{source['id']:3},0)
    assert full.magazine==stats.magazine+45


def test_equip_buff_requires_player_switch_and_expires():
    _,combat,stats=setup('Kunai',{'tier4':'4-1'},{'equipFromPrimaryAt':1.})
    source=combat['trigger_sources'][0]
    assert source['kind']=='on-equip-from-primary' and source['duration']==4
    result=replay(stats,target(),attacks_per_second=stats.fire_rate,window_seconds=6.,combat=combat,trigger_sources=combat['trigger_sources'])
    series=result['triggerSeries'][0]['series']
    assert series[0]==0 and max(series)==1 and series[-1]==0
    _,quiet,stats=setup('Kunai',{'tier4':'4-1'})
    result=replay(stats,target(),attacks_per_second=stats.fire_rate,window_seconds=6.,combat=quiet,trigger_sources=quiet['trigger_sources'])
    assert max(result['triggerSeries'][0]['series'])==0


def test_no_nearby_enemy_bonus_is_multishot_and_keeps_permanent_flat_damage():
    rows=[]
    for state in [{},{'nearbyEnemies':0,'nearbyRadius':5},{'nearbyEnemies':1,'nearbyRadius':5}]:
        w,combat,stats=setup('Vectis',{'tier2':'2-2'},state)
        branch=next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-2')
        permanent,unsupported=app.optimizer._branch_effects(branch)
        assert any(e.upgrade_type=='WEAPON_DAMAGE_AMOUNT' and e.value==75 for e in permanent)
        assert not unsupported
        rows.append(stats.multishot)
    assert rows==pytest.approx([1.,1.25,1.])


def branch_combat(name,choices,state=None,mode=0):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name))
    from wfarsenal.event_profiles import is_incarnon_mode
    weapon['isIncarnonForm']=is_incarnon_mode(weapon,mode)
    effects=[]
    for tier in weapon['incarnon']['tiers']:
        for branch in tier['branches']:
            if choices.get('tier'+str(tier['tier']))==branch['id']:
                effects.extend(app.optimizer._branch_effects(branch)[0])
    combat=prepare(dict(weapon=weapon,fire_mode=mode,effects=effects,scenario=Scenario(combat_state=state or {})),[],[],incarnon_choices=choices)
    return weapon,combat,combat['resolve']('selected',{q['id']:q.get('initialStacks',0) for q in combat['trigger_sources']},0)[0]


@pytest.mark.parametrize('name',['Sicarus','Sicarus Prime'])
def test_kings_gambit_cancels_body_crits_and_only_adds_weakpoint_cc(name):
    _,combat,stats=branch_combat(name,{'tier2':'2-2'})
    assert stats.bodyshot_crit_multiplier==0
    assert stats.weakpoint_crit_chance_relative==1.5
    plain=deepcopy(stats)
    plain.crit_chance=0
    plain.bodyshot_crit_multiplier=1
    assert damage_against(stats,target(),hit_location='body')['perShot']==pytest.approx(
        damage_against(plain,target(),hit_location='body')['perShot'])
    boosted=deepcopy(stats)
    boosted.crit_chance+=stats.base_crit_chance*1.5
    boosted.weakpoint_crit_chance_relative=0
    assert damage_against(stats,target(),hit_location='head')['perShot']==pytest.approx(
        damage_against(boosted,target(),hit_location='head')['perShot'])
    assert expected_status_damage(stats,target(),hit_location='body')['dot']['total']==pytest.approx(
        expected_status_damage(plain,target(),hit_location='body')['dot']['total'])


def test_lato_refill_needs_kills_and_does_not_generate_reload_events():
    _,combat,stats=branch_combat('Lato',{'tier3':'3-3'})
    assert combat['magazineRestore']==dict(kind='on-kill',fraction=1.,chance=.5)
    dead=replay(stats,target(1.),attacks_per_second=stats.fire_rate,window_seconds=20,combat=combat)
    alive=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=20,combat=combat)
    assert dead['reloads']==0 and alive['reloads']>0


def test_bronco_efficiency_requires_the_native_nearby_enemy_count():
    costs=[]
    for count in (0,5,6):
        _,_,stats=branch_combat('Bronco Prime',{'tier4':'4-1'},{'nearbyEnemies':count,'nearbyRadius':6})
        costs.append(stats.ammo_cost)
    assert costs==pytest.approx([1.,1.,.2])


def test_sybaris_status_addition_is_only_active_in_incarnon_form():
    _,combat,_=branch_combat('Sybaris Prime',{'tier4':'4-1'},mode=1)
    stats,_=combat['resolve']('base',{},0)
    alternate,_=combat['resolve']('incarnon',{},0)
    baseline,_,base=branch_combat('Sybaris Prime',{})
    from wfarsenal.damage import apply_mods
    base_inc=apply_mods({**baseline,'fireModes':[baseline['fireModes'][1]]},[])
    assert stats.status_chance-base.status_chance==pytest.approx(.08)
    assert alternate.status_chance-base_inc.status_chance==pytest.approx(.23)


def test_sybaris_two_round_burst_buffs_next_burst_and_resets_on_reload():
    _,combat,stats=branch_combat('Sybaris Prime',{'tier4':'4-2'})
    assert combat['baseBurst']['count']==2
    result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=6,combat=combat,trigger_sources=combat['trigger_sources'])
    first=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=.01,combat=combat,trigger_sources=combat['trigger_sources'])
    assert max(first['triggerSeries'][0]['series'])==0
    assert max(result['triggerSeries'][0]['series'])==4


@pytest.mark.parametrize('name,choice',[('Torid',{'tier2':'2-1'}),('Dread',{'tier2':'2-1'})])
def test_already_modeled_passives_do_not_report_missing_event_gates(name,choice):
    _,combat,_=branch_combat(name,choice)
    assert not any('event-condition-unmodeled' in n for n in combat['unsupported'])


def test_two_headshots_require_two_events_in_the_native_time_window():
    _,combat,stats=branch_combat('Phenmor',{'tier5':'5-3'})
    source=combat['trigger_sources'][0]
    assert source['requiredCount']==2 and source['requiredTime']==2
    results=[]
    for rate in (.4,1.):
        slow=deepcopy(stats)
        slow.fire_rate=rate
        rows=replay(slow,target(1e12),attacks_per_second=rate,window_seconds=1.01,headshot_chance=1,
            combat={},trigger_sources=combat['trigger_sources'])
        results.append(max(rows['triggerSeries'][0]['series']))
    assert results==[0,1]


def test_ability_multishot_is_never_granted_without_actor_input():
    for state,expected in [({},1.),({'abilityUses':20},2.)]:
        _,combat,stats=branch_combat('Dual Toxocyst',{'tier2':'2-2'},state)
        assert stats.multishot==pytest.approx(expected)
        assert combat['trigger_sources'][0]['kind']=='on-warframe-ability'
    _,combat,stats=branch_combat('Dual Toxocyst',{'tier2':'2-2'},{'abilityUseAt':.1,'abilityUseInterval':.1})
    result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=1.,combat=combat,trigger_sources=combat['trigger_sources'])
    assert max(result['triggerSeries'][0]['series'])==10


def test_stormburst_only_reads_preexisting_electricity_and_expires_stacks():
    _,combat,stats=branch_combat('Furis',{'tier2':'2-2'})
    source=combat['trigger_sources'][0]
    assert source['victimProcType']=='DT_ELECTRICITY' and source['decay']=='per-stack'
    quiet=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=4.,combat=combat,trigger_sources=combat['trigger_sources'])
    assert max(quiet['triggerSeries'][0]['series'])==0
    stats.damage_types={'DT_ELECTRICITY':100.}
    stats.status_chance=1.
    electric=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=4.,combat={},trigger_sources=[source])
    # The production resolver keeps the victim state before each actual shot.
    assert electric['procCounts']['DT_ELECTRICITY']>0


def test_miter_storm_adds_a_separate_radial_and_pays_fixed_extra_hold():
    _,combat,stats=branch_combat('Miter',{'tier4':'4-1'})
    _,plain,base=branch_combat('Miter',{})
    st,radial=combat['resolve']('selected',{},0)
    assert base.total_damage==pytest.approx(500.)
    assert st.total_damage==pytest.approx(500.)
    assert radial.total_damage==pytest.approx(1400.)
    assert radial.radial_only and radial.headshot_bonus_multiplier==1
    assert st._charge_time-base._charge_time==1
    assert st.trigger_interval-base.trigger_interval==1
    assert not combat['unsupported']


def test_zylok_burst_headshots_require_both_shots_and_exclude_incarnon():
    _,combat,stats=branch_combat('Zylok',{'tier2':'2-1'})
    assert combat['baseBurst']['count']==2
    for heads,expected in [(0.,0.),(1.,3.)]:
        result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=5.,headshot_chance=heads,
                      combat=combat,trigger_sources=combat['trigger_sources'])
        assert max(result['triggerSeries'][0]['series'])==expected


def test_zylok_incarnon_radial_has_own_payload_and_ignores_multishot():
    _,combat,stats=branch_combat('Zylok',{},mode=1)
    st,radial=combat['resolve']('selected',{},0)
    assert st.total_damage==pytest.approx(400.) and st._charge_time==pytest.approx(.6)
    assert radial.total_damage==pytest.approx(600.) and radial.multishot==1
    assert not any('radial-payload-unmodeled' in n for n in combat['unsupported'])


@pytest.mark.parametrize('name,total,delay',[('Laetum',300.,0.),('Gorgon',725.,1.08),
    ('Prisma Gorgon',700.,.77),('Synoid Gammacor',800.,1.2),('Strun Prime',200.,0.),('Despair',160.,.4)])
def test_native_incarnon_radial_packets_have_their_own_damage_and_clock(name,total,delay):
    _,combat,stats=branch_combat(name,{},mode=1)
    st,radial=combat['resolve']('selected',{},0)
    assert radial.total_damage==pytest.approx(total)
    assert getattr(radial,'_impact_delay',0.)==pytest.approx(delay)
    assert not any('radial-payload-unmodeled' in n for n in combat['unsupported'])
    before=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=.01,
                  combat=combat)
    after=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=2.,combat=combat)
    if delay:
        assert before['delayedAttackEvents']==0 and after['delayedAttackEvents']>0


def test_all_nonmelee_incarnon_branches_expose_their_calculation_status():
    unresolved=[]
    for weapon in app.EXPORTS['weapons']:
        if weapon.get('slot')=='melee':
            continue
        for tier in app._incarnon_options(weapon):
            for option in tier['options']:
                if any(d.get('modeled') is False for d in option['details']):
                    unresolved.append((weapon['path'],option['id']))
    assert unresolved==[]
