"""All companion Riven requests must use the same actor policy as builds."""
from copy import deepcopy
import pytest
import app
from tests.test_riven_disposition_20261023 import _engine_request


COMPANIONS=[w for w in app.CATALOG['weapons'] if w.get('weaponType')=='companion'
            and w.get('available') and w.get('analysisAvailable')]


@pytest.mark.parametrize('weapon',COMPANIONS,ids=lambda w:w['nameEn'])
@pytest.mark.parametrize('player_stacks',[False,True])
def test_riven_entry_pins_companion_actor_policy_before_optimizer(weapon,player_stacks):
    family=app.optimizer._riven_type(None,weapon);bases=app.RIVEN_BASE_VALUES[family]
    codes=[code for code in ('D','K','S','0','1') if code in bases][:2]
    payload=dict(weapon=weapon['path'],disposition=1.2,profile='ultra',aiming=True,headshotChance=1.,
        companionPlayerStacks=player_stacks,benchmarkTarget=dict(enemy=app._BENCHMARK_ENEMY_PATH,
        level=170,headshotChance=1.,hitLocation='head'),stats=[dict(code=c,value=bases[c]*1.2,negative=False) for c in codes])
    original=deepcopy(payload);request=_engine_request(payload)
    assert request['headshotChance']==0. and not request['aiming']
    assert request['benchmarkTarget']['headshotChance']==0.
    assert request['benchmarkTarget']['hitLocation']=='body'
    scenario=app.optimizer._requested_scenario(request,'killsPerMinute')
    assert scenario.combat_state['companion'] is True
    assert scenario.combat_state['companionPlayerStacks'] is player_stacks
    assert payload==original


def test_new_companion_mechanics_dependencies_invalidate_statics(monkeypatch):
    from pathlib import Path
    before=app._analysis_inputs_fingerprint();read=Path.read_bytes
    for name in ('companion.py','sentinel.py','sentinels.json','player-only-conditions.json'):
        def changed(path):
            raw=read(path)
            return raw+b' ' if path.name==name else raw
        with monkeypatch.context() as patch:
            patch.setattr(Path,'read_bytes',changed)
            assert app._analysis_inputs_fingerprint()!=before,name
