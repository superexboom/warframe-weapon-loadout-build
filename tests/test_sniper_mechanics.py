from copy import deepcopy

import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.sniper import ShotCombo, combo_spec, multiplier, reference
from tests.test_combat_replay import target


def weapon(name):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn'] == name))


VITAL_SENSE = ModEffect('WEAPON_CRIT_DAMAGE', 'STACKING_MULTIPLY', 1.2)


def test_combo_ladder_is_wfsims_table():
    # WFSim engine/src/data/weapons/tests/sniper.rs, the wiki's Vectis Prime table.
    vp = dict(min=5, tierBonus=.5, tierFactor=3., seconds=2.)
    for hits, want in [(0, 1.), (4, 1.), (5, 1.5), (14, 1.5), (15, 2.), (44, 2.), (45, 2.5),
                       (135, 3.), (405, 3.5), (1215, 4.)]:
        assert multiplier(vp, hits) == pytest.approx(want), hits
    v = dict(min=1, tierBonus=.5, tierFactor=3., seconds=2.)
    assert [multiplier(v, h) for h in (0, 1, 3, 9)] == pytest.approx([1., 1.5, 2., 2.5])
    assert multiplier(v, 59049) == pytest.approx(6.5)  # 3^10: a floor(log3) would land one short


def test_counter_reads_before_counting_and_decays_one_per_window():
    combo = ShotCombo(dict(min=1, tierBonus=.5, tierFactor=3., seconds=2.))
    assert [combo.shot(t, 1) for t in (0., .5, 1., 1.5)] == pytest.approx([1., 1.5, 1.5, 2.])
    assert combo.count == 4
    assert combo.at(3.49) == 4 and combo.at(3.5) == 3 and combo.at(9.5) == 0
    # Two pellets in one shot: the second reads the count after the first.
    combo = ShotCombo(dict(min=1, tierBonus=.5, tierFactor=3., seconds=2.))
    assert combo.shot(0., 2) == pytest.approx((1. + 1.5) / 2)
    assert combo.count == 2
    lanka = ShotCombo(combo_spec(weapon('Lanka')))
    lanka.shot(0., 1)
    assert lanka.at(5.9) == 1 and lanka.at(6.) == 0


def test_data_comes_from_game_packages_and_matches_wfsim():
    doc = reference()
    rows = doc['weapons']
    assert doc['packageBuild'] == doc['exportBuild'] == app.EXPORTS['buildLabel']
    for path, row in rows.items():
        assert not (row.get('wfsim') or {}).get('disagrees'), (row['name'], row['wfsim'])
        if row['source'] == 'game-packages':
            assert row['packageSources'] and all(s['sha256'] for s in row['packageSources']), row['name']
    by_name = {r['name']: r for r in rows.values()}
    assert by_name['Rubico Prime']['combo']['min'] == 1
    assert by_name['Vectis Prime']['combo']['min'] == 5
    assert by_name['Lanka']['combo']['seconds'] == 6.
    assert by_name['Lanka']['zoom']['effects'] == [dict(upgradeType='WEAPON_CRIT_CHANCE', operation='ADD',
                                                        value=.5, damageType='DT_ANY')]
    # A zoom that trades stats is not a buff; the Vesper's aim bonus has no package row.
    assert by_name['Komorex']['zoom']['excluded'] == 'zoom-stat-trade-unmodeled'
    assert by_name['Vesper 77']['source'] == 'wfsim-yaml' and by_name['Vesper 77']['zoom']['aimGated']


def test_scope_crit_joins_the_mod_bucket_and_only_the_base_form():
    rubico = apply_mods(weapon('Rubico Prime'), [VITAL_SENSE], scenario=Scenario())
    assert rubico.crit_multiplier == pytest.approx(3. * (1 + 1.2 + .5), rel=1e-3)
    lanka = apply_mods(weapon('Lanka'), [], scenario=Scenario())
    assert lanka.crit_chance == pytest.approx(.25 + .5)
    vectis = weapon('Vectis Prime')
    assert apply_mods(vectis, [], fire_mode=0).headshot_bonus_multiplier == pytest.approx(1.6)
    incarnon = apply_mods(vectis, [VITAL_SENSE], fire_mode=1)
    assert incarnon.headshot_bonus_multiplier == pytest.approx(1.)
    assert incarnon.crit_multiplier == pytest.approx(
        apply_mods({**vectis, 'path': 'no-scope'}, [VITAL_SENSE], fire_mode=1).crit_multiplier)
    vesper = weapon('Vesper 77')
    hip = apply_mods(vesper, [], scenario=Scenario(aiming=False)).crit_multiplier
    aimed = apply_mods(vesper, [], scenario=Scenario(aiming=True)).crit_multiplier
    assert aimed / hip == pytest.approx(1.4, rel=1e-3)


def test_scope_bonus_is_not_applied_twice_when_effects_are_reused():
    w = weapon('Rubico Prime')
    once = apply_mods(w, [VITAL_SENSE])
    from wfarsenal.sniper import zoom_effects
    assert apply_mods(w, [VITAL_SENSE, *zoom_effects(w, 0, Scenario())]).crit_multiplier == pytest.approx(once.crit_multiplier)


def _run(w, mode=0, combo=True, status=1.):
    combat = prepare(dict(weapon=w, fire_mode=mode, scenario=Scenario(), effects=[]), [], [])
    if not combo:
        combat['sniperCombo'] = None
    stats, _ = combat['resolve']('selected', {}, 0)
    return replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=10., combat=combat,
                  status_rate_multiplier=status)


def test_combo_multiplies_each_direct_hit_by_the_count_before_it():
    # No procs, so every shot's unscaled damage is identical.
    w = weapon('Rubico Prime')
    on, off = _run(w, status=0.), _run(w, combo=False, status=0.)
    factors = [e['multiplier'] for e in on['sniperCombo']['events']]
    assert factors[:4] == pytest.approx([1., 1.5, 1.5, 2.])
    assert on['directWindow'] / off['directWindow'] == pytest.approx(sum(factors) / len(factors), rel=1e-9)
    assert off['sniperCombo'] is None


def test_combo_does_not_reach_the_status_payload():
    w = weapon('Rubico Prime')
    on, off = _run(w), _run(w, combo=False)
    assert on['directWindow'] > 1.5 * off['directWindow']
    assert on['dotWindow'] == pytest.approx(off['dotWindow'])


def test_incarnon_form_neither_builds_nor_pays_the_combo():
    w = weapon('Vectis Prime')
    w['isIncarnonForm'] = True
    result = _run(w, mode=1)
    assert result['sniperCombo']['events'] == []


def test_shared_paths_carry_the_combo_spec():
    w = weapon('Vectis Prime')
    combat = prepare(dict(weapon=w, fire_mode=0, scenario=Scenario(), effects=[]), [], [])
    assert combat['sniperCombo'] == dict(min=5, tierBonus=.5, tierFactor=3., seconds=2.)
    assert prepare(dict(weapon=weapon('Braton Prime'), fire_mode=0, scenario=Scenario(), effects=[]),
                   [], [])['sniperCombo'] is None


@pytest.mark.parametrize('name', ['Perigale', 'Perigale Prime'])
def test_perigale_fires_native_four_round_bursts(name):
    # Native WeaponBurstStateBehavior: NumShots 4, BurstDelay 0.04, then 1/fireRate.
    # WFSim /api/log: hits at 0, .04, .08, .12, then .62.
    w = weapon(name)
    from wfarsenal.manual_combat import reference as combat_reference
    profile = combat_reference()['cadenceProfiles'][w['path']]
    assert profile['burst'] == dict(count=4, delay_seconds=pytest.approx(.04))
    assert profile['nativeSources'] and profile['referenceId'] == name.lower().replace(' ', '_')
    combat = prepare(dict(weapon=w, fire_mode=0, scenario=Scenario(), effects=[]), [], [])
    assert combat['baseBurst']['count'] == 4
    stats, _ = combat['resolve']('selected', {}, 0)
    run = lambda window: replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=window,
                                combat=combat, status_rate_multiplier=0.)
    assert run(.619)['shots'] == 4 and run(.621)['shots'] == 5
    times = [e['time'] for e in run(.621)['sniperCombo']['events']]
    assert times == pytest.approx([0., .04, .08, .12, .62], abs=1e-6)
