from tools.audit_ranged_calibration import mode_status,source_kinds,summarize
import pytest

def test_empty_and_auxiliary_modes_remain_in_denominator():
    assert mode_status({'behaviorKind':'auxiliary-melee'})=='auxiliary-melee-excluded'
    assert mode_status({})=='missing-damage-data'
    assert mode_status({'damage':{'types':{}}})=='no-positive-direct-payload'

def test_native_and_reference_sources_are_independent_not_full_correctness():
    assert source_kinds({'source':'data/weapons/primary/foo.yaml'})==['community-reference-declared']
    assert source_kinds({'nativeSources':[{'path':'/game','sha256':'a'}],'source':'data/weapons/primary/foo.yaml'})==['community-reference-declared','native-static-declared']
    assert source_kinds({'packageBuild':'some-build'})==[]

def test_count_weapon_gaps_once_and_modes_and_reasons_separately():
    rows=[dict(path='/w',modes=[dict(mode=0,status='evaluable',gaps=['unmodeled-A','unverified-B']),dict(mode=1,status='evaluable',gaps=['unmodeled-A'])]),dict(path='/x',modes=[dict(mode=0,status='evaluable',gaps=[])])]
    result=summarize(rows)
    assert result['weaponRecords']==2 and result['evaluableModes']==3
    assert result['weaponsWithExplicitGaps']==1 and result['evaluableModesWithExplicitGaps']==2
    assert result['modesWithNoReportedGap']==1
    assert result['fullGameplayCalibration']=='not-established-by-this-inventory'
    assert result['reasons'][0]==dict(reason='unmodeled-A',weapons=1,modes=2)

def test_duplicate_mode_ids_cannot_report_full_coverage():
    with pytest.raises(ValueError,match='duplicate'):
        summarize([dict(path='/w',modes=[dict(mode=0,status='evaluable'),dict(mode=0,status='evaluable')])])


def test_other_mode_native_provenance_does_not_certify_primary():
    assert source_kinds({'source':'data/weapons/main.yaml',
        'modes':{'1':{'nativeSources':[{'path':'/alt','sha256':'a'}]}}}) == ['community-reference-declared']
