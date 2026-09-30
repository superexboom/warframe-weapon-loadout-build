from dataclasses import replace
import pytest
import app
from wfarsenal import optimizer


def test_nested_scenario_is_authoritative_and_zero_false_are_preserved():
    sc=optimizer._requested_scenario({'aiming':True,'distance':10,'scenario':{'aiming':False,'distance':0.,'cloaked':True,'nearestEnemyDistance':3.,'comboTier':2,'triggerPolicy':'assumed_max'}},'killsPerMinute')
    assert sc.aiming is False and sc.distance==0.0 and sc.cloaked
    assert sc.nearest_enemy_distance==3.0 and sc.combo_tier==2 and sc.trigger_policy=='assumed_max'
    assert optimizer._default_analysis_scenario(sc,'killsPerMinute') is False
    default=optimizer._requested_scenario({'aiming':False,'incarnonCycle':False},'killsPerMinute')
    assert optimizer._default_analysis_scenario(default,'killsPerMinute') is True


def test_analysis_scenario_rejects_invalid_nested_values():
    with pytest.raises(app.SimulationError,match='scenario must be an object'):
        optimizer._requested_scenario({'scenario':[]},'killsPerMinute')
    with pytest.raises(app.SimulationError,match='aiming must be a boolean'):
        optimizer._requested_scenario({'scenario':{'aiming':1}},'killsPerMinute')
    with pytest.raises(app.SimulationError,match='distance must be'):
        optimizer._requested_scenario({'scenario':{'distance':-1}},'killsPerMinute')
    with pytest.raises(app.SimulationError,match='conditionalStacks'):
        optimizer._requested_scenario({'scenario':{'conditionalStacks':{}}},'killsPerMinute')


def test_analysis_context_hash_includes_nested_scenario():
    base=dict(weapon='/w',fireMode=0,metric='killsPerMinute',profile='fast',scenario={'aiming':False,'distance':0.,'cloaked':False,'nearestEnemyDistance':None,'comboTier':0})
    changed={**base,'scenario':{**base['scenario'],'distance':10.}}
    assert optimizer._evaluation_context_hash(base)!=optimizer._evaluation_context_hash(changed)
    assert optimizer._default_analysis_scenario(optimizer._requested_scenario(changed,'killsPerMinute'),'killsPerMinute') is False


def test_build_evaluation_scenario_preserves_extended_fields(monkeypatch):
    from wfarsenal import optimizer
    scenario=optimizer._requested_scenario({'scenario':{'distance':10.,'cloaked':True,'nearestEnemyDistance':3.,'comboTier':2}},'killsPerMinute')
    fields=optimizer._scenario_context(scenario)
    assert fields=={'aiming':False,'incarnonCycle':False,'heavyAttack':False,'triggerPolicy':'emergent','distance':10.,'cloaked':True,'nearestEnemyDistance':3.,'comboTier':2,
                    'detonationDelaySeconds':0., 'detonationBatchSize':1}
