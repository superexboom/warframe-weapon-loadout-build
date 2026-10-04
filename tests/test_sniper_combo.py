import json
from copy import deepcopy
from pathlib import Path

import pytest
import app
from wfarsenal import sniper_combo
from wfarsenal.sniper_combo import ShotCombo, multiplier
from wfarsenal.damage import Scenario, apply_mods, mod_effects
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target
from tools.audit_optimizer_events import evaluate_payload

FIXTURE = Path(__file__).with_name('fixtures') / 'sniper_combo_wfsim_20261004.json'


def weapon(name):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn'] == name))


MODS = {'Vital Sense': '/Lotus/Upgrades/Mods/Rifle/WeaponCritDamageMod',
        'Point Strike': '/Lotus/Upgrades/Mods/Rifle/WeaponCritChanceMod',
        'Hellfire': '/Lotus/Upgrades/Mods/Rifle/WeaponFireDamageMod'}


def mod(name):
    record = next(m for m in app.EXPORTS['mods'] if m['path'] == MODS[name])
    return record, record['maxRank']


def effects(*names):
    return [e for name in names for e in mod_effects(*mod(name))]


def test_ladder_is_wfsim_and_the_wiki_table():
    # WFSim engine/src/data/weapons/tests/sniper.rs, Vectis Prime (minimum 5).
    for hits, want in [(0, 1.), (4, 1.), (5, 1.5), (14, 1.5), (15, 2.), (44, 2.), (45, 2.5),
                       (135, 3.), (405, 3.5), (1215, 4.)]:
        assert multiplier(5, hits) == want
    assert [multiplier(1, h) for h in (0, 1, 3, 9)] == [1., 1.5, 2., 2.5]
    assert multiplier(1, 3 ** 10) == 6.5  # walked, not log3


def test_counter_reads_before_counting_and_decays_one_per_period():
    combo = ShotCombo(1, 2.)
    assert [combo.shot(t, 1) for t in (0., .3, .6, .9, 1.2)] == [1., 1.5, 1.5, 2., 2.]
    assert combo.at(1.2 + 1.99) == {5: 1.}
    assert combo.at(1.2 + 2.) == {4: 1.}  # loses one, does not reset
    assert combo.at(1.2 + 4.1) == {3: 1.}
    # Fractional multishot: one sure pellet and a 90% second one, read in order.
    combo = ShotCombo(1, 2.)
    assert combo.shot(0., 1.9) == pytest.approx((1. + .9 * 1.5) / 1.9)
    assert combo.counts == pytest.approx({1: .1, 2: .9})
    # A pull that lands nothing empties the counter (WFSim fight/after.rs).
    combo = ShotCombo(1, 2.)
    combo.shot(0., 1)
    combo.shot(.5, 0.)
    assert combo.counts == {0: 1.}


def test_profiles_carry_wfsim_provenance_and_native_paths():
    rows = sniper_combo.profiles()
    paths = {w['path'] for w in app.EXPORTS['weapons']}
    assert rows and set(rows) <= paths
    for row in rows.values():
        assert row['referenceCommit'] and row['referenceSource'].startswith('data/weapons/')
        assert len(row['referenceSha256']) == 64
    by_id = {row['referenceId']: row for row in rows.values()}
    assert by_id['rubico_prime']['sniperCombo'] == {'min': 1, 'seconds': 2.}
    assert by_id['rubico_prime']['scope']['critMultiplier'] == .5
    assert by_id['vectis_prime']['sniperCombo']['min'] == 5
    assert by_id['vectis_prime']['scope']['headshotDamage'] == .6
    assert by_id['lanka']['sniperCombo'] == {'min': 2, 'seconds': 6.}
    assert by_id['lanka']['scope']['critChancePostMod'] == .5


def test_scope_crit_damage_is_an_additive_bucket_term_while_aiming():
    rubico = weapon('Rubico Prime')
    vital = effects('Vital Sense')
    hip = apply_mods(rubico, vital, scenario=Scenario())
    ads = apply_mods(rubico, vital, scenario=Scenario(aiming=True))
    assert hip.crit_multiplier == pytest.approx(3. * (1 + 1.2), rel=1e-3)
    assert ads.crit_multiplier == pytest.approx(3. * (1 + 1.2 + .5), rel=1e-3)
    assert ads.crit_chance == hip.crit_chance


def test_lanka_scope_is_flat_crit_chance_after_mods():
    lanka = weapon('Lanka')
    strike = effects('Point Strike')
    hip = apply_mods(lanka, strike, scenario=Scenario())
    ads = apply_mods(lanka, strike, scenario=Scenario(aiming=True))
    assert ads.crit_chance == pytest.approx(hip.crit_chance + .5)
    assert ads.victim_full_crit_chance == pytest.approx(hip.victim_full_crit_chance)


def test_scope_and_counter_stay_off_the_incarnon_form_and_the_hip():
    vectis = weapon('Vectis Prime')
    assert apply_mods(vectis, [], scenario=Scenario(aiming=True)).headshot_bonus_multiplier == pytest.approx(1.6)
    incarnon = {**vectis, 'isIncarnonForm': True}
    assert apply_mods(incarnon, [], fire_mode=1, scenario=Scenario(aiming=True)).headshot_bonus_multiplier == 1.
    combat = prepare(dict(weapon=incarnon, fire_mode=1, scenario=Scenario(aiming=True), effects=[]), [], [])
    assert combat['sniperCombo'] == {'minimum': 5, 'seconds': 2.}
    stats, _ = combat['resolve']('selected', {}, 0)
    result = replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=3., combat=combat)
    assert result['sniperCombo']['events'] == []
    hip = prepare(dict(weapon=vectis, fire_mode=0, scenario=Scenario(), effects=[]), [], [])
    assert hip['sniperCombo'] is None


def test_replay_pays_hits_through_reload_and_never_status_damage():
    rubico = weapon('Rubico Prime')
    fx = effects('Hellfire')
    combat = prepare(dict(weapon=rubico, fire_mode=0, scenario=Scenario(aiming=True), effects=fx),
                     [(*mod('Hellfire'), None)], [])
    stats, _ = combat['resolve']('selected', {}, 0)
    on = replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=6., combat=combat)
    rows = on['sniperCombo']['events']
    assert [r['multiplier'] for r in rows[:5]] == [1., 1.5, 1.5, 2., 2.]
    # 1/fire rate + a 2 s reload costs exactly one count.
    assert rows[5]['expectedCount'] == pytest.approx(4.)
    off = replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=6.,
                 combat={**combat, 'sniperCombo': None})
    assert on['shots'] == off['shots']
    assert on['directWindow'] > 1.5 * off['directWindow']
    assert on['dotWindow'] == pytest.approx(off['dotWindow'])


def fixture_cases():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))['cases']


@pytest.mark.parametrize('case', fixture_cases(), ids=lambda c: f"{c['weapon']}-L{c['level']}-{'ads' if c['aiming'] else 'hip'}")
def test_manual_kpm_matches_pinned_wfsim(case):
    result = app.simulate_manual_payload(case['payload'])
    stats = result['moddedStats']
    assert stats['critChance'] == pytest.approx(case['referencePanel']['critChance'], rel=1e-3)
    assert stats['critMultiplier'] == pytest.approx(case['referencePanel']['critMultiplier'], rel=1e-3)
    assert result['benchmarkTimeline']['killsPerMinute'] == pytest.approx(case['referenceKpm'], rel=.015)


def test_optimizer_scoring_shares_the_counter_with_manual_replay():
    case = next(c for c in fixture_cases() if c['weapon'] == 'rubico_prime' and c['aiming'] and c['level'] == 9999)
    result = evaluate_payload(case['payload'])
    assert result['optimizer'] == pytest.approx(result['manual'], rel=1e-9)
    assert result['manual'] == pytest.approx(case['referenceKpm'], rel=.015)
