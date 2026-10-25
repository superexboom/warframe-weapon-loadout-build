"""Search, replay and contribution requests use the same explicit duration."""
import pytest
import app


def payload(**extra):
    weapon = next(w for w in app.CATALOG['weapons'] if w.get('nameEn') == 'Braton Prime')
    mod = next(m for m in app.EXPORTS['mods'] if m.get('nameEn') == 'Serration' and m['path'] in app.MANUAL_MODS_BY_PATH)
    return dict(weapon=weapon['path'], fireMode=0, mode='auto', profile='fast',
                mods=[dict(path=mod['path'], rank=mod['maxRank'], slot=0)],
                enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                headshotChance=0., triggerPolicy='emergent', **extra)


@pytest.mark.parametrize('seconds', [1., 30., 180.])
def test_fixed_build_search_and_manual_replay_share_the_requested_window(seconds):
    p = payload(windowSeconds=seconds)
    build = app.build_weapon_payload(p, fixed_mods=p['mods'])
    manual = app.simulate_manual_payload(dict(p, incarnonChoices=build['incarnonChoices']))
    assert build['evaluationContext']['windowSeconds'] == seconds
    assert manual['benchmarkTimeline']['windowSeconds'] == seconds
    assert build['build']['objectiveScore'] == pytest.approx(manual['benchmarkTimeline']['killsPerMinute'], rel=1e-12)


@pytest.mark.parametrize('value', [True, False, 0, -1, 601, float('inf'), float('nan'), '180'])
def test_invalid_windows_are_rejected(value):
    with pytest.raises(app.SimulationError, match='windowSeconds'):
        app._manual_resolve_sim_context(payload(windowSeconds=value))


def test_existing_requests_keep_the_thirty_second_window():
    assert app._manual_resolve_sim_context(payload())['window_seconds'] == 30.
