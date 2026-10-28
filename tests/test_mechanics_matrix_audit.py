from tools.audit_mechanics_matrix import summarize


def valid():
    return dict(expectedWeapons=1,expectedCases=1,expectedIdentities=[('/weapon',0,'case')],identity={'inputs':'a'},rows=[
        dict(path='/weapon',inputsStable=True,fingerprint='a',modes=[dict(mode=0,case='case',passed=True,nativeUsed=True)])])


def test_only_complete_stable_native_reference_matrix_passes():
    assert summarize(valid())['passed']


def test_worker_exception_and_missing_cases_never_count_as_success():
    result=valid();result['rows']=[dict(error='child crashed',modes=[])]
    summary=summarize(result)
    assert not summary['passed'] and summary['workerErrors']==1 and not summary['coverageComplete']


def test_source_mutation_or_score_difference_fails_report():
    result=valid();result['rows'][0]['fingerprint']='new'
    assert not summarize(result)['passed']
    result=valid();result['rows'][0]['modes'][0]['passed']=False
    assert not summarize(result)['passed']


def test_wrong_case_fallback_and_empty_matrix_are_not_full_native_coverage():
    result=valid();result['rows'][0]['modes'][0]['case']='other'
    assert not summarize(result)['passed'] and summarize(result)['missing']
    result=valid();result['rows'][0]['modes'][0]['nativeUsed']=False
    assert not summarize(result)['passed']
    result=valid();result.update(expectedWeapons=0,expectedCases=0,rows=[],expectedIdentities=[])
    assert not summarize(result)['passed']
