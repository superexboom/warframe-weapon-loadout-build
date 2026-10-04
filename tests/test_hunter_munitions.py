"""Hunter Munitions: a crit-conditioned Slash channel (WFSim pellet.rs slash_on_crit)."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

import app
from wfarsenal.combat_replay import replay
from wfarsenal.damage import (
    SUPPORTED_WEAPON_UPGRADE_TYPES,
    ModEffect,
    ModEffectList,
    Scenario,
    apply_mods,
    critical_tier_seed_distribution,
    crit_proc_probabilities,
    expected_dot_damage,
    expected_status_procs,
    mod_effects,
)
from wfarsenal.manual_combat import prepare
from wfarsenal.proc_probability import no_status_probability
from wfarsenal.status_arcanes import encumber_roll

HUNTER = '/Lotus/Upgrades/Mods/Sets/Hunter/PrimaryHunterMunitionsMod'
FIXTURE = Path(__file__).parent / 'fixtures' / 'hunter_munitions_reference_20261004.json'


def raw(group, name):
    return next(x for x in app.EXPORTS[group] if x.get('nameEn') == name)


def by_path(group, path):
    return next(x for x in app.EXPORTS[group] if x.get('path') == path)


def wp(name):
    w = raw('weapons', name)
    return app.optimizer._select_fire_mode(w, 0, weapon_type=app.optimizer._weapon_type(None, w))[0]


def hunter(rank=5):
    return list(mod_effects(by_path('mods', HUNTER), rank))


def neutral():
    return dict(health=1.0, armour=0.0, shield=0.0, faction='', hitProxies=[], factionResistance='RK_NEUTRAL')


def crit_rifle(cc=0.4, cd=3.0, sc=0.0, **extra):
    st = apply_mods(wp('Soma Prime'), hunter())
    return replace(st, crit_chance=cc, crit_multiplier=cd, status_chance=sc, **extra)


def test_hunter_munitions_is_admitted_to_catalog_and_optimizer():
    assert 'WEAPON_SLASH_PROC_ON_CRIT_CHANCE' in SUPPORTED_WEAPON_UPGRADE_TYPES
    row = app.MANUAL_MODS_BY_PATH[HUNTER]
    assert [e['supported'] for e in row['effects']] == [True]
    w = wp('Soma Prime')
    cards, _ = app.optimizer._candidate_mods(app.EXPORTS, w, app.optimizer._scenario('sustainedDps'))
    assert any(HUNTER in str(card.key) for card in cards)


def test_rank_scaling_and_apply_mods_channel():
    assert [e.value for e in hunter(0)] == pytest.approx([0.05])
    assert [e.value for e in hunter(5)] == pytest.approx([0.30])
    st = apply_mods(wp('Soma Prime'), hunter())
    assert st.crit_proc_chances == pytest.approx({'DT_SLASH': 0.30})
    assert not st.unsupported and not [s for s in st.skipped if 'Hunter' in s]
    # It is its own channel: no status chance, no damage weights, no crit.
    base = apply_mods(wp('Soma Prime'), [])
    assert (st.status_chance, st.crit_chance, st.damage_types) == (base.status_chance, base.crit_chance, base.damage_types)


def test_expected_procs_are_chance_times_location_crit_probability():
    st = crit_rifle(cc=0.4, sc=0.0, multishot=2.0)
    # Independent of status chance and of the weapon's damage vector.
    assert expected_status_procs(st) == pytest.approx({'DT_SLASH': 2 * 0.3 * 0.4})
    impact_only = replace(st, damage_types={'DT_IMPACT': 10.0})
    assert expected_status_procs(impact_only) == pytest.approx({'DT_SLASH': 2 * 0.3 * 0.4})
    # Body shots scale by the TORSO body-part crit; weak points add their bonuses.
    body = replace(st, bodyshot_crit_multiplier=1.5)
    assert expected_status_procs(body)['DT_SLASH'] == pytest.approx(2 * 0.3 * 0.6)
    weak = replace(st, weakpoint_crit_chance_bonus=0.2, base_crit_chance=0.2, weakpoint_crit_chance_relative=0.5)
    assert expected_status_procs(weak, weakpoint=True)['DT_SLASH'] == pytest.approx(2 * 0.3 * 0.7)
    assert expected_status_procs(weak)['DT_SLASH'] == pytest.approx(2 * 0.3 * 0.4)
    # Crit chance above 100% caps P(crit tier >= 1) at one.
    assert expected_status_procs(replace(st, crit_chance=2.5))['DT_SLASH'] == pytest.approx(2 * 0.3)
    assert expected_status_procs(replace(st, crit_chance=0.0)) == {}
    # A beam merges multishot into one damage instance, one roll.
    assert expected_status_procs(replace(st, continuous=True))['DT_SLASH'] == pytest.approx(0.3 * 0.4)


def test_forced_slash_suppresses_the_roll():
    st = crit_rifle()
    assert crit_proc_probabilities(st, forced_procs={'DT_SLASH': 1.0}) == {}
    assert crit_proc_probabilities(replace(st, native_forced_procs={'DT_SLASH': 1.0})) == {}
    assert expected_status_procs(st, forced_procs={'DT_SLASH': 1.0})['DT_SLASH'] == pytest.approx(1.0)


def test_conditional_crit_seed_distribution():
    def flat(*args, **kwargs):
        return [x for pair in critical_tier_seed_distribution(*args, **kwargs) for x in pair]
    assert flat(0.4, 3.0) == pytest.approx([1.0, 3.0])
    assert flat(1.5, 3.0) == pytest.approx([0.5, 3.0, 0.5, 5.0])
    # Vigilante promotion only moves crits up a tier.
    assert flat(0.4, 3.0, double_crit_chance=0.25) == pytest.approx([0.75, 3.0, 0.25, 5.0])
    assert flat(0.0, 3.0) == []


def test_dot_seed_uses_crit_multiplier_given_crit_not_hit_average():
    st = crit_rifle(cc=0.4, cd=3.0, sc=0.0)
    base = st.dot_base_damage if st.dot_base_damage is not None else st.total_damage
    row = expected_dot_damage(st, neutral(), level=1, hit_location='body')['perType']['DT_SLASH']
    assert row['expectedProcs'] == pytest.approx(st.multishot * 0.3 * 0.4)
    # E[M | crit] = 3.0; the all-hit average 0.6 + 0.4 * 3 = 1.8 would be wrong.
    assert row['seedPerSecondPerProc'] == pytest.approx(0.35 * base * 3.0)
    assert row['critMultiplier'] == pytest.approx(3.0)


def test_mixed_row_is_count_weighted_between_natural_and_crit_procs():
    st = crit_rifle(cc=0.4, cd=3.0, sc=0.5, damage_types={'DT_SLASH': 1.0})
    base = st.dot_base_damage if st.dot_base_damage is not None else st.total_damage
    row = expected_dot_damage(st, neutral(), level=1, hit_location='body')['perType']['DT_SLASH']
    natural, crit = st.multishot * 0.5, st.multishot * 0.3 * 0.4
    assert row['expectedProcs'] == pytest.approx(natural + crit)
    seed = 0.35 * base * (natural * 1.8 + crit * 3.0) / (natural + crit)
    assert row['seedPerSecondPerProc'] == pytest.approx(seed)
    plain = expected_dot_damage(replace(st, crit_proc_chances={}), neutral(), level=1, hit_location='body')
    assert plain['perType']['DT_SLASH']['seedPerSecondPerProc'] == pytest.approx(0.35 * base * 1.8)


def test_presence_and_encumber_see_the_crit_channel():
    st = crit_rifle(cc=0.4, sc=0.0, multishot=1.0)
    assert no_status_probability(st, 'DT_SLASH') == pytest.approx(1 - 0.3 * 0.4)
    assert no_status_probability(replace(st, crit_proc_chances={}), 'DT_SLASH') == pytest.approx(1.0)
    assert encumber_roll(st, 0.24)[0] == pytest.approx(0.24 * 0.3 * 0.4)


def test_replay_applies_crit_slash_through_shared_path():
    st = crit_rifle(cc=0.4, cd=3.0, sc=0.0)
    target = dict(health=1e12, shield=0, armour=0, overguard=0, baseLevel=1, faction='')
    with_hm = replay(st, target, attacks_per_second=5, window_seconds=6)
    without = replay(replace(st, crit_proc_chances={}), target, attacks_per_second=5, window_seconds=6)
    assert with_hm['procCounts']['DT_SLASH'] == pytest.approx(with_hm['shots'] * st.multishot * 0.3 * 0.4)
    assert 'DT_SLASH' not in without['procCounts']
    assert with_hm['dotWindow'] > 0 and without['dotWindow'] == 0
    assert with_hm['directWindow'] == pytest.approx(without['directWindow'])


def _local(case, mods):
    engine = {}
    target_path = app._BENCHMARK_ENEMY_PATH  # Thrax Centurion
    kernel = [dict(path=p, rank=by_path('mods', p)['maxRank'], slot=i) for i, p in enumerate(mods)]
    result = app.simulate(export_dir=app.EXPORT_DIR, weapon=case['weaponPath'], mods=kernel, slot_count=8,
                          fire_mode=0, enemy=target_path, level=170, steel_path=True,
                          scenario=Scenario(aiming=True, trigger_policy='emergent', distance=0.5),
                          passive_effects=ModEffectList([]), engine_context_sink=engine)
    stats = app._benchmark_timeline_stats(result['moddedStats'])
    target = app.MANUAL_ENEMIES_BY_PATH[target_path]
    cards = [(by_path('mods', k['path']), k['rank'], None) for k in kernel]
    combat = prepare(engine, cards, [], assumed=False, affinity_target=target, level=170)
    window = replay(stats, target, attacks_per_second=stats.sustained_attack_rate, window_seconds=30.0,
                    level=170, steel_path=True, headshot_chance=0.0,
                    trigger_sources=combat['trigger_sources'], combat=combat)
    assert not result.get('unsupported')
    return dict(total=window['totalWindowDamage'], slash=window['dotByType'].get('DT_CINEMATIC', 0.0))


@pytest.mark.parametrize('case', json.loads(FIXTURE.read_text(encoding='utf-8'))['cases'], ids=lambda c: c['weapon'])
def test_hunter_munitions_delta_matches_wfsim_reference(case):
    app._disable_analysis_statics_persistence()
    without = _local(case, case['mods'])
    with_hm = _local(case, case['mods'] + [case['hunterMunitions']])
    ref = case['reference']
    local_delta = with_hm['total'] / without['total'] - 1
    ref_delta = ref['with']['total'] / ref['without']['total'] - 1
    # Validated 2026-10-04: within 0.8 percentage points on all three rifles.
    assert local_delta == pytest.approx(ref_delta, abs=0.015)
    added = with_hm['slash'] - without['slash']
    assert added == pytest.approx(ref['with']['slash'] - ref['without']['slash'], rel=0.06)
