"""Weapon innate passives (DefaultUpgrades) from data/mechanics/weapon-passives.json."""
import pytest

import app
from wfarsenal import combat_replay, native_replay
from wfarsenal.damage import ModEffectList, Scenario, _apply_mods_spec_py, apply_mods, with_innate
from wfarsenal.event_profiles import weapon_passives
from wfarsenal.manual_combat import prepare

# A body that dies quickly, with a head proxy, so kill and headshot events run.
TARGET = dict(health=3000., shield=0., armour=0., overguard=0., baseLevel=1, healthType='', armourType='',
              shieldType='', factionResistance='RK_GRINEER_FACTION', damageController='custom',
              hitProxies=[{'bone': 'GAME_C1_HEAD', 'damageAtten': 1.0}])


def _weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)


def _replay(name, head, reference=False, window=10., timeline=False, decay=None):
    """``reference``: the Python loop (branches included) instead of the native one."""
    w = _weapon(name)
    scenario = Scenario(trigger_policy='emergent')
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
    if decay:
        combat['trigger_sources'] = [{**q, 'decay': decay} if q['decay'] == 'union' else q
                                     for q in combat['trigger_sources']]
    stats = apply_mods(w, [], scenario=scenario)
    native = native_replay.ENABLED
    native_replay.ENABLED = native and not reference
    try:
        return combat, combat_replay.replay(
            stats, TARGET, attacks_per_second=stats.sustained_attack_rate, window_seconds=window, combat=combat,
            trigger_sources=combat['trigger_sources'], collect_timeline=timeline, headshot_chance=head)
    finally:
        native_replay.ENABLED = native


@pytest.mark.parametrize('name,bonus', [('Kuva Chakkhurr', 1.5), ('Synapse', 1.2), ('Cernos Prime', 1.5)])
def test_always_on_headshot_passives(name, bonus):
    # GrnKuvaLichRifleInnateUpgrade +50% / InfestedRifleInnateUpgrade +20% (STACKING_MULTIPLY),
    # CernosPrimeInnateMod x1.5 (MULTIPLY).
    assert apply_mods(_weapon(name), []).headshot_bonus_multiplier == pytest.approx(bonus)


def test_aim_gates_follow_the_package_modifiers():
    # AK47WeaponInnateMod: aimed headshots +400% crit chance (ValidModifiers PM_AIM),
    # hip fire -75% ammo use (InvalidModifiers PM_AIM).
    hip = apply_mods(_weapon('AX-52'), [], scenario=Scenario(aiming=False))
    aimed = apply_mods(_weapon('AX-52'), [], scenario=Scenario(aiming=True))
    assert hip.ammo_cost == pytest.approx(.25) and hip.weakpoint_crit_chance_relative == 0
    assert aimed.ammo_cost == 1 and aimed.weakpoint_crit_chance_relative == pytest.approx(4.)


def test_cedo_status_bonus_belongs_to_the_primary_fire():
    # TnAlchemistShotgunInnateMod: +60% per status type, ValidType the shotgun itself (not the glaive).
    def ratio(mode):
        lit = apply_mods(_weapon('Cedo'), [], fire_mode=mode, scenario=Scenario(victim_status_count=3))
        bare = apply_mods(_weapon('Cedo'), [], fire_mode=mode, scenario=Scenario(victim_status_count=0))
        return lit.total_damage / bare.total_damage
    assert ratio(0) == pytest.approx(1 + .6 * 3, rel=1e-6)
    assert ratio(1) == pytest.approx(1.)


def test_innate_terms_join_once_whichever_core_runs():
    w = _weapon('Kuva Chakkhurr')
    once = with_innate(w, ModEffectList([]), 0)
    assert with_innate(w, once, 0) is once
    reference, _ = _apply_mods_spec_py(w, ModEffectList([]))
    assert apply_mods(w, []).headshot_bonus_multiplier == reference.headshot_bonus_multiplier


def test_knell_infinite_ammo_blends_by_presence_and_crit_lands_on_the_finished_multiplier():
    w = _weapon('Knell')
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario(trigger_policy='emergent')), [], [])
    ammo, crit = [q['id'] for q in combat['trigger_sources']]
    bare, _ = combat['resolve']('selected', {}, 0)
    part, _ = combat['resolve']('selected', {ammo: .4, crit: 1.2}, 0)
    full, _ = combat['resolve']('selected', {ammo: 1., crit: 3.}, 0)
    # SET 0 at a 0.4 presence is 0.4 of a free shot, not a free shot.
    assert (bare.ammo_cost, part.ammo_cost, full.ammo_cost) == pytest.approx((1., .6, 0.))
    # 2 x (1 + Crit Damage Mods) + 0.5 x Stacks (wiki; WFSim death_knell_weakpoint_stacks).
    assert full.crit_multiplier - bare.crit_multiplier == pytest.approx(1.5)
    assert full.status_chance - bare.status_chance == pytest.approx(.6)


@pytest.mark.parametrize('reference', [False, True])
def test_knell_chains_headshots_on_its_one_round(reference):
    # A free shot fires on an empty magazine (WFSim rolls::can_fire), so headshots never reload.
    _, heads = _replay('Knell', 1., reference)
    _, body = _replay('Knell', 0., reference)
    assert heads['reloads'] == 0 and heads['shots'] > 30
    assert body['reloads'] == body['shots'] or body['reloads'] == body['shots'] - 1


@pytest.mark.parametrize('reference', [False, True])
def test_knell_partial_headshots_chain_through_branches(reference):
    # Empty with the buff up at probability p: a branch settles it (free shots go
    # on, or a reload), so the chain grows smoothly with the headshot share.
    dps = [_replay('Knell', head, reference, window=30.)[1]['totalWindowDamage'] for head in (0., .1, .5, 1.)]
    assert dps == sorted(dps) and dps[1] > 1.3 * dps[0] and dps[2] > .8 * dps[3]
    _, half = _replay('Knell', .5, reference, window=30.)
    assert half['killBranches']['count'] == combat_replay.KILL_BRANCHES


def test_union_matches_reset_on_whole_events_and_stops_saturating_on_shares():
    # Knell's infinite ammo: one headshot a shot at a 100% share is a whole event.
    whole = [_replay('Knell', 1., decay=d, window=30.)[1]['totalWindowDamage'] for d in ('reset', 'union')]
    assert whole[0] == whole[1]
    # Magnus Prime 4%: a capped sum climbs to 1 and stays; the union does not.
    summed = _replay('Magnus Prime', 0., decay='reset', window=30., timeline=True)[1]['triggerSeries'][0]['avgStacks']
    union = _replay('Magnus Prime', 0., window=30., timeline=True)[1]['triggerSeries'][0]['avgStacks']
    assert union < .7 * summed


@pytest.mark.parametrize('reference', [False, True])
def test_magnus_prime_low_chance_rolls_hold_as_a_union(reference):
    # PrimeMagnusInnateUpgrade: 4% per hit, 4 s infinite ammo. Summed expected
    # stacks would sit at 1 under sustained fire; the union stays below it.
    combat, run = _replay('Magnus Prime', 0., reference, timeline=True)
    source = combat['trigger_sources'][0]
    assert source['decay'] == 'union' and source['perEvent'] == pytest.approx(.04)
    series = run['triggerSeries'][0]
    assert 0. < series['avgStacks'] < .9


def test_union_is_the_chance_any_live_roll_holds():
    assert combat_replay._union([(1., .04)] * 25) == pytest.approx(1 - .96 ** 25)
    assert combat_replay._union([]) == 0.


def test_cannot_reproc_buffs_only_start_from_their_idle_share():
    # PrimeAthodaiInnateMod CanReproc 0: per-stack expiries, renewal scaled by the idle share.
    combat, run = _replay('Athodai Prime', 1., timeline=True)
    source = combat['trigger_sources'][0]
    assert source['noRefresh'] and source['decay'] == 'per-stack' and source['kind'] == 'on-headshot-kill'
    assert max(run['triggerSeries'][0]['series']) <= 1. + 1e-9


def test_every_innate_record_is_modelled_or_left_out_with_a_reason():
    data = weapon_passives()
    kinds = {'on-headshot', 'on-hit', 'on-proc', 'proc-DT_GAS', 'on-burst-headshot', 'on-headshot-kill',
             'on-reload-empty', 'on-reload-complete', 'on-melee-heavy-hit', 'on-combo-tier-increase',
             'on-melee-kill', 'on-melee-heavy-kill'}
    for path, entry in data.items():
        for row in entry.get('innate') or ():
            assert row.get('effects') or row.get('conditionalEffects'), path
            for condition in row.get('conditionalEffects') or ():
                assert condition['eventKind'] in kinds and condition['effects'], (path, row['name'])
    import json
    from pathlib import Path
    raw = json.loads((Path(app.__file__).parent / 'data/mechanics/weapon-passives.json').read_text(encoding='utf-8'))
    assert raw['excluded'] and all(v['reason'] and v['weapons'] for v in raw['excluded'].values())


def test_sagek_prime_crits_arm_a_set_status_chance():
    # GrnOrokinPistol.lua: a critical hit arms the next shot with 6%; it reads 500% status chance.
    w = _weapon('Sagek Prime')
    damage = w['fireModes'][0]['damage']
    armed = 0.059999999 * min(1.0, damage['critChance'])
    stats = apply_mods(w, [])
    assert stats.status_chance == pytest.approx(damage['procChance'] + armed * (5 - damage['procChance']))
    reference, _ = _apply_mods_spec_py(w, ModEffectList([]))
    assert reference.status_chance == stats.status_chance
    assert apply_mods(_weapon('Lex'), []).status_chance == pytest.approx(_weapon('Lex')['fireModes'][0]['damage']['procChance'])


@pytest.mark.parametrize('reference', [False, True])
@pytest.mark.parametrize('name,blast', [('Catabolyst', 1997.), ('Coda Catabolyst', 658.)])
def test_catabolyst_reload_throws_its_grenade(name, blast, reference):
    # InfBeamPistol.lua: a reload from empty throws the big grenade (contact + blast),
    # landing halfway through the reload (WFSim catabolyst.yaml).
    w = _weapon(name)
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario(trigger_policy='emergent')), [], [])
    stats, _ = combat['resolve']('selected', {}, 0)
    contact, explosion = stats._reload_projectiles['empty']
    assert contact.damage_types == {'DT_IMPACT': 11.0} and explosion.damage_types == {'DT_CORROSIVE': blast}
    assert explosion.radial_only and explosion.multishot == 1 and not explosion.continuous
    target = dict(TARGET, health=3e5)
    native = native_replay.ENABLED
    native_replay.ENABLED = native and not reference
    try:
        run = combat_replay.replay(stats, target, attacks_per_second=stats.sustained_attack_rate, window_seconds=30.,
                                   combat=combat, trigger_sources=combat['trigger_sources'], collect_timeline=False)
    finally:
        native_replay.ENABLED = native
    assert run['reloads'] >= 3 and run['delayedAttackEvents'] == 2 * run['reloads']


@pytest.mark.parametrize('statuses', [0, 1, 3, 5])
def test_galariak_prime_final_crit_per_status_type(statuses):
    # GrnDrillScytheInnateUpgrade: +10% final crit chance per status type on the target.
    w = _weapon('Galariak Prime')
    base = w['fireModes'][0]['damage']['critChance']
    scenario = Scenario(victim_status_count=statuses)
    native = apply_mods(w, [], scenario=scenario)
    reference, _ = _apply_mods_spec_py(w, ModEffectList([]), scenario=scenario)
    assert native.crit_chance == reference.crit_chance == pytest.approx(base + .1 * statuses)


def test_a_fractional_live_status_count_scales_per_status_crit():
    # The resolver scales the per-status term by the live share instead of rounding up.
    w = _weapon('Galariak Prime')
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario(trigger_policy='emergent')), [], [])
    base = w['fireModes'][0]['damage']['critChance']
    assert combat['resolve']('selected', {}, 2.5)[0].crit_chance == pytest.approx(base + .25)


def test_innate_terms_follow_the_selected_mode_not_index_zero():
    # Cedo's +60% per status belongs to the shotgun: the optimizer's one-mode
    # record of the glaive throw (__selectedFireMode__ 1) must not read it.
    w = _weapon('Cedo')
    glaive = {**w, 'fireModes': [w['fireModes'][1]], '__selectedFireMode__': 1}
    lit = apply_mods(glaive, [], scenario=Scenario(victim_status_count=3)).total_damage
    assert lit == pytest.approx(apply_mods(glaive, [], scenario=Scenario(victim_status_count=0)).total_damage)


def _melee(name, route, reference=False, health=3e5, passive=True):
    w = _weapon(name)
    scenario = Scenario(trigger_policy='emergent', combat_state={'meleeRoute': route})
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
    if not passive:
        for q in combat['trigger_sources']:
            q['perEvent'] = 0.0
    stats = apply_mods(w, [], scenario=scenario)
    native = native_replay.ENABLED
    native_replay.ENABLED = native and not reference
    try:
        return combat, combat_replay.replay(stats, dict(TARGET, health=health), attacks_per_second=stats.sustained_attack_rate,
                                            window_seconds=30., combat=combat, trigger_sources=combat['trigger_sources'],
                                            collect_timeline=True)
    finally:
        native_replay.ENABLED = native


def test_ekhein_heavy_hits_grant_its_buff_only_on_a_heavy_route():
    # EntSphereHammerInnateMod: OnMeleeHeavyHit, +80% melee damage and +20% attack speed for 8 s.
    _, slam = _melee('Ekhein', 'slam')
    _, combo = _melee('Ekhein', 'combo')
    assert slam['triggerSeries'][0]['uptime'] > .8
    assert combo['triggerSeries'][0]['uptime'] == 0


def test_tonkkatt_stacks_heat_on_each_combo_tier_gained():
    # GrnChainSawTonfa.lua: +4% Heat per tier gained, 15 s, 30 at most; a combo reset clears it.
    combat, run = _melee('Tonkkatt', 'combo')
    source = combat['trigger_sources'][0]
    assert source['kind'] == 'on-combo-tier-increase' and source['maxStacks'] == 30
    assert source['resetOn'] == ['on-combo-tier-reset']
    series = run['triggerSeries'][0]['series']
    assert max(series) >= 5 and max(series) <= 30


def test_amanata_die_reads_its_expected_face():
    # ShrineMaidenNaginata.lua: one face always up, each 1/6, the sixth holds every term.
    w = _weapon('Amanata')
    damage = w['fireModes'][0]['damage']
    stats = apply_mods(w, [])
    assert stats.crit_chance == pytest.approx(damage['critChance'] + .4 / 3, rel=1e-6)
    assert stats.status_chance == pytest.approx(damage['procChance'] + .3 / 3, rel=1e-6)


def _damage(name, route, reference=False, health=3e5, passive=True):
    return _melee(name, route, reference, health, passive)[1]['totalWindowDamage']


@pytest.mark.parametrize('reference', [False, True])
def test_pennant_heavy_kills_speed_it_up_for_a_combo_scaled_time(reference):
    # TnRailjackGreatKatanaWeapon.lua: +50% attack speed after a heavy-attack kill,
    # 2 s + 4 s per combo multiplier above 1x; CanReproc 0.
    # 600 HP: each heavy slam kills, and the buff speeds the recovery right after it.
    combat, run = _melee('Pennant', 'slamBullet', reference, health=600.)
    source = combat['trigger_sources'][0]
    assert source['kind'] == 'on-melee-heavy-kill' and source['noRefresh']
    assert (source['duration'], source['durationPerTier']) == (2., 4.)
    assert run['triggerSeries'][0]['uptime'] > 0
    assert _damage('Pennant', 'slamBullet', reference, 600.) > 1.1 * _damage('Pennant', 'slamBullet', reference, 600., False)
    # A combo route has no heavy attack, so no heavy kill.
    assert _melee('Pennant', 'combo', reference, health=600.)[1]['triggerSeries'][0]['uptime'] == 0


@pytest.mark.parametrize('reference', [False, True])
def test_dorrclave_ten_kills_arm_ten_attacks(reference):
    # TnDagathBladeWhip.lua: _numKillsToTrigger 10, then _numAttacks 10 at +100% status chance.
    combat, run = _melee('Dorrclave', 'combo', reference, health=3000.)
    source = combat['trigger_sources'][0]
    assert (source['requiredCount'], source['charges'], source['consumeOn']) == (10, 10., 'on-melee-attack')
    assert 0. < run['triggerSeries'][0]['uptime'] < 1.
    assert _damage('Dorrclave', 'combo', reference, 3000.) > _damage('Dorrclave', 'combo', reference, 3000., False)


@pytest.mark.parametrize('reference', [False, True])
def test_arca_titron_kills_charge_the_next_slam(reference):
    # CorpusHammerWeapon.lua: +250% (5 at most) per melee kill, spent by the next slam.
    combat, _ = _melee('Arca Titron', 'slamBullet', reference, health=6000.)
    source = combat['trigger_sources'][0]
    assert (source['maxStacks'], source['lockOn'], source['consumeOn']) == (5., 'on-melee-slam-start', 'on-melee-slam')
    assert _damage('Arca Titron', 'slamBullet', reference, 6000.) > 1.5 * _damage('Arca Titron', 'slamBullet', reference, 6000., False)
    # No slam on the combo route: the passive never arms.
    combo, run = _melee('Arca Titron', 'combo', reference, health=6000.)
    assert combo['trigger_sources'][0]['perEvent'] == 0 and run['triggerSeries'][0]['uptime'] == 0


def test_melee_passives_match_between_cores():
    for name, route, health in (('Pennant', 'slamBullet', 600.), ('Dorrclave', 'combo', 3000.),
                                ('Arca Titron', 'slamBullet', 6000.)):
        assert _damage(name, route, False, health) == _damage(name, route, True, health), name


def test_reconifex_reloads_perfectly_into_heat_rounds():
    # TnBeltFedRifle.lua: every reload perfect, ending at PerfectReloadRange[0]; the loaded magazine fires Heat.
    w = _weapon('Reconifex')
    assert apply_mods(w, []).reload_time == pytest.approx(w['fireModes'][0]['reloadTime'] * .22, rel=1e-6)
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario(trigger_policy='emergent')), [], [])
    source = combat['trigger_sources'][0]
    assert source['kind'] == 'on-reload-complete' and source['duration'] == 0


def test_vinquibus_halves_hold_each_others_buff():
    # UpgradeOnRifleHeadshot.lua, held on (user 2026-10-24): the rifle never spends ammo, the bayonet +250%.
    assert apply_mods(_weapon('Vinquibus'), []).ammo_cost == 0
    melee = _weapon('Vinquibus (Melee)')
    assert apply_mods(melee, []).total_damage == pytest.approx(3.5 * melee['fireModes'][0]['damage']['total'], rel=1e-6)


def test_venato_prime_statuses_also_apply_tau():
    # ProcsOnHit.lua PT_SENTIENT: +10% status chance received per Tau stack, 10 at most, 8 s each.
    combat = prepare(dict(weapon=_weapon('Venato Prime'), fire_mode=0, effects=[],
                          scenario=Scenario(trigger_policy='emergent')), [], [])
    source = combat['trigger_sources'][0]
    assert (source['kind'], source['maxStacks'], source['duration'], source['decay']) == ('on-proc', 10., 8., 'per-stack')


def test_typed_status_duration_and_stack_cap():
    # Slaytra: +100% Bleed duration (ValidProcTypes PT_BLEEDING); Evensong: +2 Puncture stacks.
    from wfarsenal.damage import proc_duration_scale, proc_stack_cap
    slaytra = apply_mods(_weapon('Slaytra'), [])
    assert proc_duration_scale(slaytra, 'DT_SLASH') == pytest.approx(2 * proc_duration_scale(slaytra, 'DT_FIRE'))
    reference, _ = _apply_mods_spec_py(_weapon('Slaytra'), ModEffectList([]))
    assert reference.proc_duration_types == slaytra.proc_duration_types
    evensong = apply_mods(_weapon('Evensong'), [])
    assert proc_stack_cap(evensong, 'DT_PUNCTURE', 5.) == 7. and proc_stack_cap(evensong, 'DT_SLASH', 5.) == 5.
    assert (_replay('Slaytra', 0., window=20.)[1]['totalWindowDamage']
            == _replay('Slaytra', 0., True, window=20.)[1]['totalWindowDamage'])


def test_custom_defense_has_a_standard_head():
    # GrineerHead: DamageAtten 2 (3x with the fixed 1.5x) and CriticalMultiplier 2.
    target = app._custom_enemy_snapshot(dict(health=1e7, healthType='RK_NONE', armourType='RK_NONE', shieldType='RK_NONE'))
    assert target['hitProxies'] == [{'bone': 'GAME_C1_HEAD', 'part': 'HEAD', 'damageAtten': 2., 'criticalMultiplier': 2.}]
    w = _weapon('Lex')
    scenario = Scenario(trigger_policy='emergent')
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
    stats = apply_mods(w, [], scenario=scenario)

    def direct(body, head):
        return combat_replay.replay(stats, body, attacks_per_second=stats.sustained_attack_rate, window_seconds=10.,
                                    combat=combat, trigger_sources=combat['trigger_sources'],
                                    headshot_chance=head)['directWindow']
    plain = dict(target, hitProxies=[{'bone': 'GAME_C1_HEAD', 'part': 'HEAD', 'damageAtten': 2.}])
    assert direct(plain, 1.) == pytest.approx(3 * direct(plain, 0.))
    # A head crit doubles: 1 + c(2CD - 1) against 1 + c(CD - 1); Puncture's crit chance adds a little more.
    c, cd = stats.crit_chance, stats.crit_multiplier
    assert direct(target, 1.) / direct(target, 0.) >= 3 * (1 + c * (2 * cd - 1)) / (1 + c * (cd - 1))


@pytest.mark.parametrize('reference', [False, True])
def test_enkaus_ink_held_on_spends_no_ammo_and_dissolves_below_35_percent(reference):
    # TnInkRifle.lua with every target ink-stained (held on, as Vinquibus's
    # cross-slot buffs): primary fire costs nothing, a target dies at 35% health.
    w = _weapon('Enkaus')
    scenario = Scenario(trigger_policy='emergent')
    assert apply_mods(w, [], fire_mode=0).ammo_cost == 0 and apply_mods(w, [], fire_mode=1).ammo_cost == 15
    stats = apply_mods(w, [], scenario=scenario)
    runs = []
    for execute in (True, False):
        combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=scenario), [], [])
        assert combat['executeBelow'] == .35
        if not execute:
            combat['executeBelow'] = 0.
        native = native_replay.ENABLED
        native_replay.ENABLED = native and not reference
        try:
            runs.append(combat_replay.replay(stats, dict(TARGET, health=2e4), attacks_per_second=stats.sustained_attack_rate,
                                             window_seconds=30., combat=combat, trigger_sources=combat['trigger_sources']))
        finally:
            native_replay.ENABLED = native
    inked, plain = runs
    assert inked['reloads'] == 0
    assert inked['killsInWindow'] == pytest.approx(plain['killsInWindow'] / .65, rel=.05)
    assert prepare(dict(weapon=w, fire_mode=1, effects=[], scenario=scenario), [], [])['executeBelow'] == 0
