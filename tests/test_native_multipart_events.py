"""Native multipart attack regression: events, mode identity, shared scoring."""
from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, damage_against
from wfarsenal.event_profiles import base_profile
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload
from tests.test_combat_replay import target


def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)


def resolve(name, mode=0, effects=()):
    c = prepare(dict(weapon=weapon(name), fire_mode=mode, effects=effects,
                     scenario=Scenario(distance=10.)), [], [])
    st, part = c['resolve']('selected', {})
    return c, st, (part, *part._additional_radials) if part else ()


@pytest.mark.parametrize('name,mode,direct,parts,delays', [
    ('Ogris', 0, 100, [600], [0]),
    ('Lenz', 0, 50, [10, 660], [0, 1.3]),
    ('Prisma Lenz', 0, 56, [10, 740], [0, 1.3]),
    ('Stahlta', 1, 600, [1200], [.36000001]),
])
def test_native_parts_keep_vectors_delays_multishot_and_radial_identity(name, mode, direct, parts, delays):
    _, st, radial = resolve(name, mode, [ModEffect('WEAPON_FIRE_ITERATIONS', 'ADD', 1.2)])
    assert st.total_damage == pytest.approx(direct)
    assert st.multishot == pytest.approx(2.2)
    assert [p.total_damage for p in radial] == pytest.approx(parts)
    assert [p._impact_delay for p in radial] == pytest.approx(delays)
    for p in radial:
        assert p.multishot == st.multishot and p.radial_only
        assert damage_against(p, target(), hit_location='head')['perShot'] == damage_against(p, target(), hit_location='body')['perShot']
    assert 'projectile-component-damage-unapplied' not in st.unsupported


def test_stahlta_profile_only_applies_to_exact_selected_projectile_mode():
    w = weapon('Stahlta')
    assert not base_profile(w, 0).get('radials')
    assert not resolve('Stahlta', 0)[2]
    selected, _ = app.optimizer._select_fire_mode(w, 1, weapon_type='rifle')
    assert base_profile(selected)['radials'] == base_profile(w, 1)['radials']
    wrong = deepcopy(selected)
    wrong['fireModes'][0]['damage']['projectile'] = '/unverified-projectile'
    # The audited explosion needs the projectile; the native charge is the
    # mode's state behaviour (tools/import_charge_profiles.py) and stays.
    assert base_profile(wrong) == {'charge': {'seconds': 1.6, 'source': 'native-ChargeTime', 'scalesWithFireRate': True}}


@pytest.mark.parametrize('name,mode,delay,before_damage,after_damage', [
    ('Lenz', 0, 1.3, 60., 720.),
    ('Prisma Lenz', 0, 1.3, 66., 806.),
    ('Stahlta', 1, .36000001, 600., 1800.),
])
def test_initial_and_delayed_parts_use_distinct_timeline_events(name, mode, delay, before_damage, after_damage):
    c, st, parts = resolve(name, mode)
    for p in (st, *parts):
        p.crit_chance = p.status_chance = 0.
        p.fire_rate = .001
    # Hold one trigger pull; do not alter the actual projectile event payload.
    if hasattr(st, '_bow_draw'): st._bow_draw = 1000.
    c['resolve'] = lambda *args: (st, parts[0])
    before = replay(st, target(), combat=c, window_seconds=delay-.00001, attacks_per_second=.001)
    after = replay(st, target(), combat=c, window_seconds=delay+.00001, attacks_per_second=.001)
    assert before['shots'] == after['shots'] == 1
    assert before['directWindow'] == pytest.approx(before_damage)
    assert after['directWindow'] == pytest.approx(after_damage)


def test_lenz_initial_cold_is_forced_even_with_zero_natural_status():
    c, st, parts = resolve('Lenz', effects=[ModEffect('WEAPON_PROC_CHANCE', 'SET', 0.)])
    assert parts[0].native_forced_procs == {'DT_FREEZE': 1.}
    assert parts[1].native_forced_procs == {}
    r = replay(st, target(), combat=c, window_seconds=.1, attacks_per_second=1.)
    assert r['timeline'][-1]['stacks']['cold'] >= 1


def test_delayed_collapse_does_not_jump_to_enemy_replacing_initial_blast_victim():
    c, st, parts = resolve('Lenz')
    for p in (st, *parts): p.crit_chance = p.status_chance = 0.
    st._bow_draw = 1000.
    c['resolve'] = lambda *args: (st, parts[0])
    r = replay(st, target(hp=55), combat=c, window_seconds=1.31, attacks_per_second=.001)
    assert r['killEvents'] == 1
    assert r['directWindow'] == 55


@pytest.mark.parametrize('name,mode', [('Ogris',0),('Lenz',0),('Prisma Lenz',0),('Stahlta',0),('Stahlta',1)])
def test_multipart_manual_and_search_use_same_event_chain(name, mode):
    mods = [next(m for m in app.EXPORTS['mods'] if m.get('nameEn') == n and '/Expert/' not in m['path'])
            for n in ['Serration', 'Split Chamber', 'Thermite Rounds']]
    p = dict(weapon=weapon(name)['path'], fireMode=mode, mods=[dict(path=m['path'],rank=m['maxRank'],slot=i) for i,m in enumerate(mods)],
             slotPolarities=[m['polarity'] for m in mods]+[None]*5, arcanes=[],
             enemy=app._BENCHMARK_ENEMY_PATH, level=9999, steelPath=True,
             headshotChance=1., aiming=True, scenario={'distance':10.}, triggerPolicy='emergent')
    r = evaluate_payload(p)
    assert r['manual'] == pytest.approx(r['optimizer'], rel=1e-10)


def test_stahlta_multishot_contribution_uses_delayed_radial_events():
    mod = next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Split Chamber' and '/Expert/' not in m['path'])
    p=dict(weapon=weapon('Stahlta')['path'],fireMode=1,mods=[dict(path=mod['path'],rank=mod['maxRank'],slot=0)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,
           headshotChance=1.,aiming=True,scenario={'distance':10.})
    result=app.mod_gains_payload({**p,'mode':'equipped','candidates':[mod['path']]})
    plain=app.simulate_manual_payload({**p,'mods':[]})['benchmarkTimeline']['killsPerMinute']
    assert result['gains'][mod['path']]['value']==pytest.approx(plain,abs=.001)
    assert result['baseValue']>plain


@pytest.mark.parametrize('name,mode,charge,rate', [('Ogris',0,.30000001,1.5),('Stahlta',1,1.6,.666667)])
@pytest.mark.parametrize('rate_bonus',[0.,1.,-.5])
def test_charge_and_refire_are_both_paid_and_scale_with_fire_rate(name,mode,charge,rate,rate_bonus):
    c,st,parts=resolve(name,mode,[ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',rate_bonus)])
    assert st._charge_time==pytest.approx(charge/(1+rate_bonus))
    interval=(charge+1/rate)/(1+rate_bonus)
    c['resolve']=lambda *args:(st,parts[0])
    before=replay(st,target(),combat=c,window_seconds=interval-1e-5,attacks_per_second=rate)
    after=replay(st,target(),combat=c,window_seconds=interval+1e-5,attacks_per_second=rate)
    assert before['shots']==1 and after['shots']==2


def test_prisma_lenz_uses_native_point_eight_second_draw():
    _,st,_=resolve('Prisma Lenz')
    assert st._bow_draw==pytest.approx(.80000001)
    evidence=base_profile(weapon('Prisma Lenz'))['chargeEvidence']
    assert evidence['referenceSeconds']==1.2


# A modded magazine rounds to the nearest whole round (wiki Magazine Warp: a one-round
# Tonkor under Primed Magazine Warp holds 2), never below one.
@pytest.mark.parametrize('bonus,rounds',[(-1.,1.),(-.5,1.),(.4,1.),(.49,1.),(.5,2.),(.99,2.),(1.,2.)])
def test_fractional_magazine_bonus_rounds_to_the_nearest_round(bonus,rounds):
    c,st,parts=resolve('Lenz',effects=[ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',bonus)])
    assert st.magazine==rounds
    baseline=resolve('Lenz')[1]
    if rounds==1.:
        a=replay(st,target(),combat=c,window_seconds=10.,attacks_per_second=1.)
        bc,_,_=resolve('Lenz')
        b=replay(baseline,target(),combat=bc,window_seconds=10.,attacks_per_second=1.)
        assert a['shots']==b['shots'] and a['reloads']==b['reloads']


def test_unprofiled_empty_alternate_mode_stays_a_data_gap():
    assert base_profile({'path':'/unknown','fireModes':[{'damage':None}]})=={}
    w=weapon('Coda Bassocyst')
    assert base_profile(w,1)=={}


def test_talons_pure_radial_uses_one_blast_and_auxiliary_melee_is_not_rankable():
    import app
    from wfarsenal.manual_combat import prepare
    from wfarsenal.damage import Scenario
    from wfarsenal.combat_replay import replay
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Talons')
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(distance=10)),[],[])
    st,radial=c['resolve']('selected',{})
    assert st.radial_only and st.total_damage==pytest.approx(250.)
    assert radial is None
    assert st.native_forced_procs=={'DT_PUNCTURE':1.}
    result=replay(st, target(), combat=c, attacks_per_second=st.fire_rate, window_seconds=1.)
    assert result['directWindow']>0 and result['shots']>=1
    with pytest.raises(app.SimulationError, match="auxiliary melee"):
        app.build_weapon_payload(dict(weapon=w['path'],fireMode=1,metric='killsPerMinute',profile='fast'))


def test_talons_extractor_selects_embedded_attack_without_breaking_contact_projectiles(monkeypatch):
    from wfarsenal import extract
    path='/Lotus/Weapons/Tenno/ThrowingWeapons/U18ThrowingKnives/U18throwingknives'
    mine={'AttackData':{'Amount':0},'Embed':1,'CriticalChance':.22,'CriticalMultiplier':2,
          'ExplosiveAttack':{'Amount':120},
          'EmbedDeathAttack':{'Amount':250,'Type':'DT_EXPLOSION','ForcedProcs':['PT_FRAILTY','PT_RAGDOLL']}}
    monkeypatch.setattr(extract,'_resolve_weapon_reference',lambda *args:(path+'Projectile',mine))
    result=extract._resolve_damage(None,path,{'projectileType':'p'}, {})
    assert result['types']=={'DT_EXPLOSION':250}
    assert result['radial']['source']=='EmbedDeathAttack'
    assert result['radial']['total']==250
    assert len(result['components'])==2
    assert result['critChance']==.22 and result['procChance']==0
    other=extract._resolve_damage(None,'/unverified',{'projectileType':'p'}, {})
    assert other['source']=='ExplosiveAttack' and other['total']==120
    mine['AttackData']={'Amount':10,'Type':'DT_IMPACT'}
    direct=extract._resolve_damage(None,path,{'projectileType':'p'}, {})
    assert direct['types']=={'DT_IMPACT':10}
    assert direct['radial']['source']=='ExplosiveAttack'

def test_talons_export_radial_alias_matches_primary_and_keeps_airborne_evidence():
    d=weapon('Talons')['fireModes'][0]['damage']
    assert d['radial']['source']==d['source']=='EmbedDeathAttack'
    assert d['radial']['types']==d['types']=={'DT_EXPLOSION':250}
    assert d['components'][0]['source']=='ExplosiveAttack'
    assert d['components'][0]['total']==120
