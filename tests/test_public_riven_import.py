from copy import deepcopy
from pathlib import Path
import json
import pytest
from tools.compare_archgun_board_builds import public_riven_spec,resolved_riven_payload,exact_record


def row():
    return dict(mods=['mod','riven'],riven=dict(bonuses=['critical_damage','damage_to_grineer','multishot'],
                                              malus='zoom',rolls=[1.1,1.1,1.1,.9]))


def resolved():
    return json.loads((Path(__file__).parent/'fixtures/spectra_public_riven_resolved_20260927.json').read_text(encoding='utf-8'))


def test_resolved_values_preserve_faction_delta_sign_and_slot():
    p=resolved_riven_payload(public_riven_spec(row()),resolved(),7,'pistol')
    assert p['slot']==7
    assert [x['code'] for x in p['stats']]==['1','G','S','H']
    assert [x['negative'] for x in p['stats']]==[False,False,False,True]
    assert [x['value'] for x in p['stats']]==pytest.approx([134.57812230843751,67.28906115421875,178.98890625,78.39787323825001])
    assert p['stats'][1]['value']!=pytest.approx(resolved()['stats'][1]['shown']*100)


@pytest.mark.parametrize('rolls',[[1.1,1.1,1.1],[1.1,1.1,1.1,True],[1.1,1.1,1.1,1.2]])
def test_missing_or_out_of_range_rolls_are_not_defaulted(rolls):
    r=row();r['riven']['rolls']=rolls
    with pytest.raises(ValueError,match='invalid public riven'):public_riven_spec(r)


def test_reference_omissions_and_unknown_ids_fail_closed():
    spec=public_riven_spec(row());r=resolved();r['stats'].pop()
    with pytest.raises(ValueError,match='omitted or reordered'):resolved_riven_payload(spec,r,7,'pistol')
    r=resolved();r['stats'][0]['id']='unknown';spec['bonuses'][0]['id']='unknown'
    with pytest.raises(ValueError,match='unmapped exact'):resolved_riven_payload(spec,r,7,'pistol')


def test_declared_internal_path_cannot_be_replaced_by_same_display_name():
    with pytest.raises(ValueError,match='identity'):
        exact_record(dict(id='wrong',internal_name='/wrong',name='Same'),[dict(path='/different',nameEn='Same')])
