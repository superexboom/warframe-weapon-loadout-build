import json
import pytest
from tools.audit_nonmelee_catalog import attempt_status, ranged_companion, dump


@pytest.mark.parametrize('row,status',[({},'generation-failed'),
    ({'ok':True},'manual-missing'),({'ok':True,'manualError':'invalid'},'manual-error'),
    ({'ok':True,'manualKpm':1.,'autoManualPassed':False},'replay-mismatch'),
    ({'ok':True,'manualKpm':1.,'autoManualPassed':True,'manualUnsupported':['loadout-over-capacity']},'invalid-loadout'),
    ({'ok':True,'manualKpm':1.,'autoManualPassed':True},'replay-matched')])
def test_audit_does_not_confuse_generation_and_verified_replay(row,status):
    assert attempt_status(row)==status


def test_only_ranged_companions_enter_nonmelee_denominator():
    assert ranged_companion({'slot':'companion','ancestry':['/Lotus/Weapons/Tenno/LotusLongGun']})
    assert not ranged_companion({'slot':'companion','ancestry':['/Lotus/Types/Game/LotusMeleeWeapon']})


def test_audit_writes_complete_json_and_replaces_previous_atomically(tmp_path):
    p=tmp_path/'results.json'
    dump(p,{'old':True});dump(p,[{'ok':True}])
    assert json.loads(p.read_text())==[{'ok':True}]
    assert not p.with_name('results.json.tmp').exists()


def test_merge_rejects_mixed_versions_and_counts_unfinished_shards(tmp_path):
    from tools.merge_nonmelee_catalog_audit import merge_runs
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    a=dict(path='/a',fingerprint='same',ok=True,replayComplete=True,attempts=[])
    dump(one/'meta.json',dict(fingerprint='same',weapons=['/a'],state='complete'))
    dump(one/'results.json',[a])
    dump(two/'meta.json',dict(fingerprint='same',weapons=['/b'],state='running'))
    result=merge_runs([one,two])['summary']
    assert result['expectedWeapons']==2 and result['weapons']==1
    assert result['missingWeapons']==['/b'] and not result['allLocalReplayComplete']
    assert result['externalComparison']=='not-performed-by-this-audit'
    dump(two/'meta.json',dict(fingerprint='other',weapons=['/b'],state='running'))
    with pytest.raises(ValueError,match='mixed model'):
        merge_runs([one,two])


def test_merge_rejects_stale_rows_and_conflicting_duplicates(tmp_path):
    from tools.merge_nonmelee_catalog_audit import merge_runs
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    for root in [one,two]:dump(root/'meta.json',dict(fingerprint='current',weapons=['/a'],state='complete'))
    dump(one/'results.json',[dict(path='/a',fingerprint='stale',ok=True)])
    with pytest.raises(ValueError,match='row does not belong'):
        merge_runs([one])
    dump(one/'results.json',[dict(path='/a',fingerprint='current',ok=True)])
    dump(two/'results.json',[dict(path='/a',fingerprint='current',ok=False)])
    with pytest.raises(ValueError,match='conflicting duplicate'):
        merge_runs([one,two])


def test_merge_rejects_legacy_evidence_without_version_manifest(tmp_path):
    from tools.merge_nonmelee_catalog_audit import merge_runs
    dump(tmp_path/'results.json',[dict(path='/legacy',ok=True)])
    with pytest.raises(ValueError,match='missing version manifest'):
        merge_runs([tmp_path])


@pytest.mark.parametrize('error,status',[
    ('SimulationError: weapon is not in the portable Riven catalog','catalog-absent'),
    ('SimulationError: weapon has no fire modes','abstract-modular-placeholder'),
    ('SimulationError: fire mode 1 metric sustainedDps is unavailable','mode-metric-unavailable'),
    ('ValueError: unrelated','generation-failed'),
])
def test_attempt_status_classifies_structural_denominator_gaps(error,status):
    assert attempt_status({'ok':False,'error':error})==status


def test_merge_separates_structural_gaps_from_engine_failures(tmp_path):
    from tools.merge_nonmelee_catalog_audit import merge_runs
    root=tmp_path/'r';root.mkdir()
    dump(root/'meta.json',dict(fingerprint='v',weapons=['/a','/b','/c'],state='complete'))
    dump(root/'results.json',[
        dict(path='/a',fingerprint='v',ok=True,replayComplete=True,attempts=[dict(status='replay-matched',ok=True,manualKpm=1.,autoManualPassed=True)]),
        dict(path='/b',fingerprint='v',ok=True,replayComplete=True,attempts=[dict(status='catalog-absent',ok=False)]),
        dict(path='/c',fingerprint='v',ok=True,replayComplete=True,attempts=[dict(status='generation-failed',ok=False)]),
    ])
    s=merge_runs([root])['summary']
    assert s['structuralGaps']==1 and s['engineFailures']==1
    assert s['structuralGapKinds']==[('catalog-absent',1)]


def test_merge_counts_replay_mismatch_even_when_build_generation_succeeded(tmp_path):
    from tools.merge_nonmelee_catalog_audit import merge_runs
    dump(tmp_path/'meta.json',dict(fingerprint='v',weapons=['/a'],state='complete'))
    dump(tmp_path/'results.json',[dict(path='/a',fingerprint='v',ok=True,replayComplete=False,
        attempts=[dict(status='replay-mismatch',ok=True,manualKpm=1.,autoManualPassed=False)])])
    s=merge_runs([tmp_path])['summary']
    assert s['engineFailures']==s['manualReplayFailed']==1
    assert s['attemptsOk']==1 and not s['allLocalReplayComplete']
