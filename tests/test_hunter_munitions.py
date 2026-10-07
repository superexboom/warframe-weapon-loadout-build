"""Hunter Munitions: a crit-conditioned Slash proc channel (WFSim slash_on_crit)."""
from dataclasses import replace
from pathlib import Path
import json
import pytest
import app
from wfarsenal.damage import (SUPPORTED_WEAPON_UPGRADE_TYPES, apply_mods, mod_effects,
                              crit_proc_probability, crit_tier_seed_distribution,
                              expected_status_procs, expected_status_damage, location_crit_chance)
from wfarsenal.proc_probability import no_status_probability
from wfarsenal.status_arcanes import encumber_roll
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import stats, target

HM = '/Lotus/Upgrades/Mods/Sets/Hunter/PrimaryHunterMunitionsMod'
EVIDENCE = Path(__file__).resolve().parents[1] / 'docs/evidence/hunter-munitions-20261005/cases.json'


def hm(chance=.3, **kw):
    kw.setdefault('damage_types', {'DT_IMPACT': 100.0})
    kw.setdefault('status_chance', 0.0)
    return stats(crit_proc_chances={'DT_SLASH': chance}, **kw)


def slash(result):
    return result['dot']['perType']['DT_SLASH']


@pytest.mark.parametrize('rank,value', [(0, .05), (5, .30)])
def test_catalog_admits_card_and_apply_mods_reads_rank(rank, value):
    assert 'WEAPON_SLASH_PROC_ON_CRIT_CHANCE' in SUPPORTED_WEAPON_UPGRADE_TYPES
    assert HM in app.MANUAL_MODS_BY_PATH
    record = next(m for m in app.EXPORTS['mods'] if m['path'] == HM)
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Baza Prime')
    result = apply_mods(weapon, mod_effects(record, rank))
    assert result.crit_proc_chances == {'DT_SLASH': pytest.approx(value)}
    assert not result.unsupported and not result.skipped


@pytest.mark.parametrize('cc', [0., .25, .8, 1.5])
def test_expected_procs_are_chance_times_crit_probability_per_pellet(cc):
    st = hm(crit_chance=cc, multishot=3.0)
    # No Slash in the vector and no status chance: the roll is its own.
    assert expected_status_procs(st).get('DT_SLASH', 0.) == pytest.approx(3 * .3 * min(cc, 1.))
    plain = replace(st, crit_proc_chances={}, status_chance=.5)
    both = replace(st, status_chance=.5)
    assert expected_status_procs(both)['DT_IMPACT'] == pytest.approx(expected_status_procs(plain)['DT_IMPACT'])


def test_crit_probability_follows_body_part_rules():
    st = hm(crit_chance=.4, bodyshot_crit_multiplier=0.0, base_crit_chance=.2,
            weakpoint_crit_chance_bonus=.1, weakpoint_crit_chance_relative=.5)
    assert location_crit_chance(st, 'body') == 0.0
    assert expected_status_procs(st).get('DT_SLASH', 0.) == 0.0
    assert location_crit_chance(st, 'head') == pytest.approx(.4 + .1 + .2 * .5)
    assert crit_proc_probability(st, 'DT_SLASH', 'head') == pytest.approx(.3 * .6)
    assert crit_proc_probability(replace(st, radial_only=True), 'DT_SLASH', 'head') == pytest.approx(.3 * .4)


def test_weapon_forced_slash_already_covers_the_pellet():
    st = hm(crit_chance=1.0, native_forced_procs={'DT_SLASH': 1.0})
    assert expected_status_procs(st)['DT_SLASH'] == pytest.approx(1.0)


def test_impact_conversion_is_skipped_when_hunter_munitions_procs():
    conversion = {'DT_SLASH': [dict(chance=.5, fireRateThreshold=0., fireRateMultiplier=1.)]}
    st = hm(crit_chance=.5, status_chance=1.0, impact_proc_conversions=conversion)
    p = .3 * .5
    assert expected_status_procs(st)['DT_SLASH'] == pytest.approx(1.0 * .5 * (1 - p) + p)


@pytest.mark.parametrize('cc,seed', [(.25, 3.), (1.0, 3.), (1.5, (3. + 5.) / 2)])
def test_seed_is_crit_multiplier_conditioned_on_crit(cc, seed):
    st = hm(crit_chance=cc, crit_multiplier=3.0)
    row = slash(expected_status_damage(st, target()))
    assert row['seedPerSecondPerProc'] == pytest.approx(.35 * 100 * seed)
    assert row['critConditionedShare'] == 1.0


def test_seed_mixes_ordinary_and_crit_slash_by_count():
    st = hm(crit_chance=.25, crit_multiplier=3.0, status_chance=.4,
            damage_types={'DT_SLASH': 50., 'DT_IMPACT': 50.})
    ordinary, crit = .4 * .5, .3 * .25
    row = slash(expected_status_damage(st, target()))
    assert row['expectedProcs'] == pytest.approx(ordinary + crit)
    average = .75 * 1 + .25 * 3
    expected = (ordinary * average + crit * 3.) / (ordinary + crit)
    assert row['seedPerSecondPerProc'] == pytest.approx(.35 * 100 * expected)
    assert sum(t['weight'] for t in row['seedTiers']) == pytest.approx(1.)


def test_critical_only_seed_distribution_keeps_vigilante_promotion():
    assert crit_tier_seed_distribution(.3, 2., critical_only=True, double_crit_chance=.5) == [
        (pytest.approx(.5), 2.), (pytest.approx(.5), 3.)]
    assert crit_tier_seed_distribution(0., 2., critical_only=True) == []


def test_presence_and_encumber_trigger_see_the_crit_roll():
    st = hm(crit_chance=.5)
    assert no_status_probability(st, 'DT_SLASH') == pytest.approx(1 - .15)
    assert encumber_roll(st, 1.0)[0] == pytest.approx(.15)


def test_replay_ticks_hunter_munitions_bleeds():
    st = hm(crit_chance=1.0, crit_multiplier=3.0)
    with_hm = replay(st, target(), attacks_per_second=10, window_seconds=5)
    without = replay(replace(st, crit_proc_chances={}), target(), attacks_per_second=10, window_seconds=5)
    assert with_hm['procCounts']['DT_SLASH'] == pytest.approx(50 * .3)
    assert without['dotWindow'] == 0.0
    assert with_hm['dotWindow'] > 0.0
    assert with_hm['directWindow'] == pytest.approx(without['directWindow'])


def _benchmark(weapon, mods, level):
    payload = dict(weapon=weapon, fireMode=0, mods=[dict(path=p, rank=None, slot=i) for i, p in enumerate(mods)],
                   arcanes=[], headshotChance=0.0, aiming=True, triggerPolicy='emergent',
                   scenario=dict(distance=0.5), slotPolarities=[None] * 8,
                   enemy=app._BENCHMARK_ENEMY_PATH, level=level, steelPath=True,
                   # WFSim leaves own-shield-break perks out of scope.
                   combatState=dict(selfShieldBreakForced=False))
    return app.simulate_manual_payload(payload)['benchmarkTimeline']['windowDps']


def test_benchmark_gain_matches_recorded_wfsim_reference():
    """tools/validate_hunter_munitions.py, body shots on SP Thrax Centurion 170."""
    evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    rows = evidence['rows']
    checked = 0
    for base, with_hm in zip(rows[::2], rows[1::2]):
        assert with_hm['modPaths'] == base['modPaths'] + [HM]
        if abs(base['localDps'] / base['wfsimDps'] - 1) > .015:
            continue  # baseline disagrees before HM; not an HM comparison.
        local = (_benchmark(base['weaponPath'], with_hm['modPaths'], evidence['level'])
                 / _benchmark(base['weaponPath'], base['modPaths'], evidence['level']))
        assert local == pytest.approx(with_hm['wfsimDps'] / base['wfsimDps'], rel=.015)
        checked += 1
    assert checked >= 12
