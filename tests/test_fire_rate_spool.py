"""Fire-rate spin-up (WFSim attack.sustained_fire_rate) in the event replay."""
from pathlib import Path
import json
import pytest
import app
from wfarsenal.damage import Scenario, apply_mods
from wfarsenal.event_profiles import FIRE_RATE_SPOOL_PROFILES, SPOOL_PROFILES, base_profile
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target

PRISMA_GORGON = '/Lotus/Weapons/Grineer/LongGuns/VoidTraderGorgon/VTGorgon'
EVIDENCE = Path(__file__).resolve().parent / 'fixtures/hunter_munitions_cases_20261005.json'


def weapon(path):
    return next(w for w in app.EXPORTS['weapons'] if w['path'] == path)


def run(path, window):
    w = weapon(path)
    st = apply_mods(w, [])
    combat = prepare(dict(weapon=w, fire_mode=0, effects=[], scenario=Scenario()), [], [])
    return st, replay(st, target(), attacks_per_second=st.fire_rate, window_seconds=window, combat=combat)


def test_profiles_bind_to_matching_base_attack_only():
    w = weapon(PRISMA_GORGON)
    assert base_profile(w, 0)['fireRateSpool'] == {'start': .2, 'end': 1., 'overShots': 6.}
    assert 'fireRateSpool' not in base_profile({**w, '__selectedFireMode__': 1}, 1)
    assert not set(FIRE_RATE_SPOOL_PROFILES) & set(SPOOL_PROFILES)
    for path, profile in FIRE_RATE_SPOOL_PROFILES.items():
        assert base_profile(weapon(path), 0).get('fireRateSpool') == profile['fireRateSpool'], path


def test_rate_ramps_per_shot_and_restarts_after_reload():
    st, result = run(PRISMA_GORGON, 15.)
    rates = [row['fireRate'] for row in result['spoolTrace']]
    assert rates[:8] == pytest.approx([st.fire_rate * (.2 + .8 * min(n / 6, 1.)) for n in range(8)])
    magazine = int(st.magazine)
    assert rates[magazine] == pytest.approx(st.fire_rate * .2)
    assert 'fire-rate-spool-resets-on-any-pause' in result['limitations']


def test_spin_up_costs_the_ramp_time_per_magazine():
    st, result = run(PRISMA_GORGON, 15.)
    first = [row['time'] for row in result['spoolTrace']][:int(st.magazine)]
    ramp = sum(1 / (st.fire_rate * (.2 + .8 * n / 6)) for n in range(6))
    assert first[-1] == pytest.approx(ramp + (int(st.magazine) - 7) / st.fire_rate)


def test_benchmark_baselines_match_recorded_wfsim_reference():
    """tools/validate_hunter_munitions.py rows for spin-up weapons, body shots, SP Thrax 170."""
    from tests.test_hunter_munitions import _benchmark
    evidence = json.loads(EVIDENCE.read_text(encoding='utf-8'))
    rows = [r for r in evidence['rows'] if not r['hunterMunitions'] and r['weaponPath'] in FIRE_RATE_SPOOL_PROFILES
            and r['weapon'] != 'coda_bubonico']  # battery recharge differs; see the evidence notes
    assert len(rows) >= 8
    for row in rows:
        assert row['evolutions'] or not row['incarnonChoices']
        local = _benchmark(row['weaponPath'], row['modPaths'], evidence['level'])
        assert local == pytest.approx(row['wfsimDps'], rel=.015), row['weapon']
