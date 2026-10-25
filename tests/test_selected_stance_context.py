"""The chosen stance must reach both search and manual hit schedules."""
import json
from pathlib import Path

import pytest
import app


@pytest.mark.parametrize('tree', ['KatanaCmbOneMeleeTree', 'KatanaCmbTwoMeleeTree', 'KatanaCmbThreeMeleeTree'])
def test_selected_stance_matches_manual_replay_for_the_same_fixed_build(tree):
    payload = json.loads((Path(__file__).parent / 'fixtures/selected_stance_nikana.json').read_text(encoding='utf-8'))
    payload['stancePath'] = '/Lotus/Weapons/Tenno/Melee/MeleeTrees/' + tree
    build = app.build_weapon_payload(payload, fixed_mods=payload['mods'])
    manual = app.simulate_manual_payload(payload)
    assert build['evaluationScenario']['combatState']['meleeStance'] == payload['stancePath']
    assert build['build']['objectiveScore'] == pytest.approx(manual['benchmarkTimeline']['killsPerMinute'], rel=1e-10)


def test_unmodeled_tennokai_is_disclosed_and_does_not_crash_fixed_builds():
    payload = json.loads((Path(__file__).parent / 'fixtures/selected_stance_nikana.json').read_text(encoding='utf-8'))
    payload['exilus'] = dict(path='/Lotus/Upgrades/EmpoweredHeavyMelee/FocusedAttack', rank=3)
    payload['specialSlotPolarities']['exilus'] = 'AP_ANY'
    build = app.build_weapon_payload(payload, fixed_mods=payload['mods'])
    manual = app.simulate_manual_payload(payload)
    without = app.simulate_manual_payload(dict(payload, exilus=None))
    assert 'tennokai-opportunities-not-modeled' in build['unsupported']
    assert 'tennokai-opportunities-not-modeled' in manual['unsupported']
    assert manual['benchmarkTimeline']['killsPerMinute'] == without['benchmarkTimeline']['killsPerMinute']
    assert build['build']['objectiveScore'] == pytest.approx(manual['benchmarkTimeline']['killsPerMinute'], rel=1e-10)
