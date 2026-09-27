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
