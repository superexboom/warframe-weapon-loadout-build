"""A glaive's heavy throw and detonation, its own mods, and heavy hits on a hit schedule."""
from dataclasses import replace

import pytest

import app
from wfarsenal import combat_replay, native_replay, optimizer
from wfarsenal.damage import Scenario, apply_mods, mod_effects, _apply_mods_spec_py, ModEffectList
from wfarsenal.manual_combat import prepare
from wfarsenal.melee_sequence import apply_hit, build_schedule

TARGET = dict(health=3e5, shield=0., armour=0., overguard=0., baseLevel=1, healthType='', armourType='',
              shieldType='', factionResistance='RK_GRINEER_FACTION', damageController='custom',
              hitProxies=[{'bone': 'GAME_C1_HEAD', 'damageAtten': 1.0}])


def _weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)


def _mod(path_end):
    return next(m for m in app.EXPORTS['mods'] if m['path'].endswith(path_end) and m.get('selectable'))


POWER_THROW = '/Melee/WeaponGlaivePowerthrowMod'
WHIRLWIND = '/Melee/WeaponGlaiveSpeedMod'
VOLATILE_QUICK_RETURN = 'WeaponGlaiveExplodingReflectionDecreaseMod'
VOLATILE_REBOUND = 'WeaponGlaiveExplodingReflectionIncreaseMod'
KILLING_BLOW = 'WeaponMeleeHeavyDamageMod'
CONDITION_OVERLOAD = '/Melee/WeaponDamageIfVictimProcActive'


def _run(name='Glaive Prime', mods=(), reference=False, route=None, window=30., timeline=False):
    w = _weapon(name)
    records = [(_mod(p), int(_mod(p).get('maxRank') or 0)) for p in mods]
    effects = [e for m, r in records for e in mod_effects(m, r)]
    scenario = Scenario(trigger_policy='emergent', combat_state={'meleeRoute': route} if route else {})
    combat = prepare(dict(weapon=w, fire_mode=0, effects=effects, scenario=scenario),
                     [(m, r, None) for m, r in records], [])
    stats = apply_mods(w, effects, scenario=scenario)
    native = native_replay.ENABLED
    native_replay.ENABLED = native and not reference
    try:
        return combat, combat_replay.replay(stats, TARGET, attacks_per_second=stats.sustained_attack_rate,
                                            window_seconds=window, combat=combat,
                                            trigger_sources=combat['trigger_sources'], collect_timeline=timeline)
    finally:
        native_replay.ENABLED = native


def _damage(*args, **kwargs):
    return _run(*args, **kwargs)[1]['totalWindowDamage']


def test_a_heavy_hit_on_a_schedule_keeps_the_ordinary_base():
    # The hit carries its own scale (heavy slam x5, detonation x7.2); the
    # heavy flag only turns on heavy-attack cards, it must not also swap the
    # base for the x6 heavy-attack record.
    for name, route in (('Fragor', 'slamBullet'), ('Glaive Prime', None)):
        w = _weapon(name)
        scenario = Scenario(trigger_policy='emergent', combat_state={'meleeRoute': route} if route else {})
        combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
        normal, _ = combat['resolve']('selected', {}, 0)
        heavy, _ = combat['resolve']('selected', {'__heavy': True}, 0)
        assert heavy.total_damage == normal.total_damage, name
    killing_blow = _mod(KILLING_BLOW)
    combat = prepare(dict(weapon=_weapon('Fragor'), fire_mode=0, effects=list(mod_effects(killing_blow, 5)),
                          scenario=Scenario(trigger_policy='emergent')), [(killing_blow, 5, None)], [])
    normal, _ = combat['resolve']('selected', {}, 0)
    heavy, _ = combat['resolve']('selected', {'__heavy': True}, 0)
    assert heavy.total_damage == pytest.approx(2.2 * normal.total_damage)   # Killing Blow +120%, heavy only


def test_the_throw_cycle_follows_the_package():
    schedule = build_schedule(_weapon('Glaive Prime'))
    charge, strike, bounce, detonation = schedule['segments']
    # ChargeDuration 1.2 s (wiki heavy wind-up), not the stance tree's 0.7 s.
    assert charge['fixed'] == pytest.approx(1.2) and charge['chargeScaled']
    assert strike['flightScaled'] and strike['hit']['kind'] == 'glaiveDirect'
    assert not strike['hit']['heavy'] and strike['hit']['throw'] and strike['hit']['comboHits'] == 1
    assert bounce['hit']['bounce'] and not bounce['hit']['heavy'] and not bounce['hit']['extraProcs']
    assert bounce['hit']['atten'] * 2 == pytest.approx(detonation['hit']['atten'])   # 50% of the detonation
    assert detonation['hit']['heavy'] and detonation['hit']['consumesCombo'] and detonation['hit']['noConditionOverload']


def test_hits_of_one_throw_carry_the_packaged_damage():
    w = _weapon('Glaive Prime')
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario(trigger_policy='emergent')), [], [])
    stats, _ = combat['resolve']('selected', {'__heavy': True}, 0)
    melee = combat['melee']
    hits = {s['hit']['kind']: apply_hit(stats, s['hit'], melee_crit=melee['meleeCrit'])
            for s in melee['segments'] if s.get('hit')}
    # Charged Throw 360, Recall Explosion 1184, Bounce Explosion 592 (wiki / WFSim module rows).
    assert hits['glaiveDirect'].total_damage == pytest.approx(360.)
    assert hits['glaiveExplosion'].total_damage == pytest.approx(1184.)
    assert hits['glaiveBounce'].total_damage == pytest.approx(592.) and hits['glaiveBounce'].multishot == 0.


def test_volatile_cards_set_off_the_bounce_explosion():
    # +25% a rank, 100% at rank 3 (wiki); both cores read the stat alike.
    w = _weapon('Glaive Prime')
    for path in (VOLATILE_QUICK_RETURN, VOLATILE_REBOUND):
        effects = list(mod_effects(_mod(path), 3))
        assert apply_mods(w, effects).reflection_explosion_chance == 1.
        reference, _ = _apply_mods_spec_py(w, ModEffectList(effects))
        assert reference.reflection_explosion_chance == 1.
    _, bare = _run(timeline=True)
    _, volatile = _run(mods=(VOLATILE_QUICK_RETURN,), timeline=True)
    kinds = lambda run: {e['kind'] for e in run['melee']['events']}
    assert 'glaiveBounce' not in kinds(bare) and 'glaiveBounce' in kinds(volatile)
    assert volatile['totalWindowDamage'] > 1.05 * bare['totalWindowDamage']


def test_whirlwind_shortens_the_flight():
    _, bare = _run()
    _, fast = _run(mods=(WHIRLWIND,))
    assert fast['shots'] > bare['shots'] and fast['totalWindowDamage'] > bare['totalWindowDamage']


def test_killing_blow_speeds_the_wind_up_and_pays_the_detonation_only():
    w = _weapon('Glaive Prime')
    killing_blow = _mod(KILLING_BLOW)
    combat = prepare(dict(weapon=w, fire_mode=0, effects=list(mod_effects(killing_blow, 5)),
                          scenario=Scenario(trigger_policy='emergent')), [(killing_blow, 5, None)], [])
    melee = combat['melee']
    strike, _bounce, detonation = [s['hit'] for s in melee['segments'] if s.get('hit')]
    plain, _ = combat['resolve']('selected', {}, 0)
    heavy, _ = combat['resolve']('selected', {'__heavy': True}, 0)
    assert apply_hit(plain, strike, melee_crit=melee['meleeCrit']).total_damage == pytest.approx(360.)
    assert apply_hit(heavy, detonation, melee_crit=melee['meleeCrit']).total_damage == pytest.approx(1184. * 2.2)
    assert _run(mods=(KILLING_BLOW,))[1]['shots'] > _run()[1]['shots']


def test_power_throw_stacks_on_consecutive_throws_and_pays_the_strike_alone():
    # +100% a consecutive throw at rank 5, three stacks; a loop buffers every throw.
    combat, run = _run(mods=(POWER_THROW,), timeline=True)
    source = next(q for q in combat['trigger_sources'] if q['kind'] == 'on-glaive-throw')
    assert source['maxStacks'] == 3 and source['duration'] == 0
    assert max(run['triggerSeries'][0]['series']) == 3
    stats, _ = combat['resolve']('selected', {source['id']: 3.}, 0)
    assert stats.throw_damage_bonus == pytest.approx(3., rel=1e-4)
    melee = combat['melee']
    strike, _bounce, detonation = [s['hit'] for s in melee['segments'] if s.get('hit')]
    assert apply_hit(stats, strike, melee_crit=melee['meleeCrit']).total_damage == pytest.approx(4 * 360., rel=1e-4)
    assert apply_hit(stats, detonation, melee_crit=melee['meleeCrit']).total_damage == pytest.approx(1184.)
    # Its own bracket: multiplicative with Pressure Point (+120% melee damage).
    pressure = _mod('/Melee/WeaponMeleeDamageMod')
    records = [(pressure, 5, None), (_mod(POWER_THROW), 5, None)]
    effects = [e for m, r, _ in records for e in mod_effects(m, r)]
    both = prepare(dict(weapon=_weapon('Glaive Prime'), fire_mode=0, effects=effects,
                        scenario=Scenario(trigger_policy='emergent')), records, [])
    stats, _ = both['resolve']('selected', {next(q['id'] for q in both['trigger_sources']
                                                 if q['kind'] == 'on-glaive-throw'): 3.}, 0)
    assert apply_hit(stats, strike, melee_crit=melee['meleeCrit']).total_damage == pytest.approx(2.2 * 4 * 360., rel=1e-4)


def test_condition_overload_stays_off_the_explosions():
    w = _weapon('Glaive Prime')
    co = _mod(CONDITION_OVERLOAD)
    combat = prepare(dict(weapon=w, fire_mode=0, effects=list(mod_effects(co, 5)),
                          scenario=Scenario(trigger_policy='emergent')), [(co, 5, None)], [])
    lit, _ = combat['resolve']('selected', {}, 2)
    blast, _ = combat['resolve']('selected', {'__heavy': True, '__noCO': True}, 2)
    bare, _ = combat['resolve']('selected', {}, 0)
    assert lit.total_damage > bare.total_damage and blast.total_damage == bare.total_damage


def test_glaive_mods_match_between_cores():
    for mods in ((), (POWER_THROW, WHIRLWIND, VOLATILE_QUICK_RETURN, KILLING_BLOW, CONDITION_OVERLOAD)):
        assert _damage(mods=mods) == _damage(mods=mods, reference=True), mods


def test_a_glaive_carries_astral_twilight():
    # The throw reads no stance; WFSim fixes Astral Twilight on every glaive.
    glaives = [w for w in app.EXPORTS['weapons'] if 'GLAIVES_STANCE' in {str(t).upper() for t in w.get('compatTags') or ()}]
    assert len(glaives) >= 12
    for w in glaives:
        assert app._compatible_stances(w)[0]['nameEn'] == 'Astral Twilight', w['nameEn']
        assert app._resolve_stance(w, 'melee')['path'] == app._GLAIVE_STANCE_PATH
    # Elsewhere the best light-attack loop still leads.
    from wfarsenal.melee_sequence import loop_rate
    nikana = _weapon('Nikana Prime')
    rates = [loop_rate(build_schedule(nikana, 'combo', stance=s['path'])['segments']) for s in app._compatible_stances(nikana)]
    assert rates == sorted(rates, reverse=True)


def test_reach_is_not_forced_onto_a_throw():
    # Reach widens the glaive's hitbox, never its flight (wiki Glaive).
    weapon, _ = optimizer._select_fire_mode(_weapon('Glaive Prime'), None, weapon_type='melee')
    throw, _ = optimizer._candidate_mods(app.EXPORTS, weapon, optimizer._scenario('killsPerMinute'))
    combo, _ = optimizer._candidate_mods(app.EXPORTS, weapon, replace(optimizer._scenario('killsPerMinute'),
                                                                      combat_state={'meleeRoute': 'combo'}))
    assert not any(card.required for card in throw) and any(card.required for card in combo)
    assert any(card.record and card.record['path'].endswith(POWER_THROW) for card in throw)


@pytest.mark.parametrize('name,heavy_slam', [('Arca Titron', 1080.), ('War', 750.), ('Fragor', 600.)])
def test_a_slam_is_one_area_hit_at_the_slam_attack_multiplier(name, heavy_slam):
    # wiki Melee: "Slam attacks deal 2x weapon damage (3x for Heavy Slams)"; weapon
    # pages list Arca Titron 1,080 and War 750. HeavySlamAoE's DamageAtten 3, not the
    # Slams[] row's class-dependent BaseDamageAttenuation (x5 on these).
    w = _weapon(name)
    scenario = Scenario(trigger_policy='emergent', combat_state={'meleeRoute': 'slamBullet'})
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
    melee = combat['melee']
    hits = [s['hit'] for s in melee['segments'] if s.get('hit')]
    assert len(hits) == 1 and hits[0]['canCrit'] and hits[0]['slamStart'] and hits[0]['slamEnd']
    stats, _ = combat['resolve']('selected', {'__heavy': True}, 0)
    assert apply_hit(stats, hits[0], melee_crit=melee['meleeCrit']).total_damage == pytest.approx(heavy_slam)
