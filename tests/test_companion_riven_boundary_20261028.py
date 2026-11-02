"""All companion Riven requests must use the same actor policy as builds."""
from copy import deepcopy
import pytest
import app
from tests.test_riven_disposition_20261023 import _engine_request


# One actual weapon per Riven family; variants use the same boundary branch.
COMPANIONS=[w for w in app.CATALOG['weapons']
            if w.get('nameEn') in {'Artax', 'Sweeper', 'Burst Laser', 'Deconstructor'}]


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

    source = next(w for w in app.EXPORTS['weapons'] if w['path'] == weapon['path'])
    for negative in (False, True):
        legal = app.optimizer._riven_allowed_codes(app.EXPORTS['rivenTemplates'], family, source, negative=negative)
        candidates, _ = app.optimizer._candidate_lines(family, 1.2, (), negative=negative, allowed_codes=legal)
        assert not {'H', 'M', 'Z', 'N', 'X', 'U', 'B', 'Q'} & {line.code for line in candidates}
        assert {'0', '1'} <= legal  # supported combat stats remain available
    forbidden = 'X' if family == 'melee' else 'H'
    malformed = deepcopy(payload)
    for stat in malformed['stats']:
        stat['value'] = bases[stat['code']] * 1.2 * 1.2375
    malformed['stats'].append(dict(code=forbidden, value=20., negative=True))
    with pytest.raises(app.SimulationError, match='not allowed'):
        _engine_request(malformed)


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
