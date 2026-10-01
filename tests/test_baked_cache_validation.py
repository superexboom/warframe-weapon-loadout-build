import json

from tools.validate_baked_statics import validate


def sample():
    entries={json.dumps({'weapon':p,'profile':p,'fireMode':0}):dict(contextHash='a'*20,evaluationTarget={},scoreStatus='ok')
             for p in ('fast','standard')}
    cache=dict(inputs='current',cacheVersion=14,entries=entries)
    reports={p:dict(status='complete',inputs='current',cacheVersion=14,expectedShards=1,failures=[])
             for p in ('fast','standard')}
    return cache,reports


def test_both_profiles_need_current_contexts_and_complete_coverage():
    cache,reports=sample()
    assert validate(cache,'current',14,reports)['passed']
    reports['standard']['expectedShards']=2
    result=validate(cache,'current',14,reports)
    assert not result['passed'] and 'standard:missing-covered-modes' in result['errors']


def test_old_identity_or_invalid_numeric_payload_cannot_pass():
    cache,reports=sample()
    cache['inputs']='old'
    next(iter(cache['entries'].values()))['counts']={'score':float('nan')}
    result=validate(cache,'current',14,reports)
    assert not result['passed'] and any(x.startswith('nonfinite:') for x in result['errors'])


def test_unpublished_standard_shards_are_not_a_published_cache():
    cache,reports=sample()
    reports['standard']['status']='shards-complete'
    assert 'standard:not-completely-published' in validate(cache,'current',14,reports)['errors']


def test_multiple_contexts_for_one_mode_cannot_hide_missing_modes():
    cache,reports=sample()
    duplicate=json.dumps({'weapon':'fast','profile':'fast','fireMode':0,'benchmark':{'level':171}})
    cache['entries'][duplicate]=dict(contextHash='a'*20,evaluationTarget={},scoreStatus='ok')
    reports['fast']['expectedShards']=2
    result=validate(cache,'current',14,reports)
    assert result['coverage']['fast']==1
    assert 'fast:missing-covered-modes' in result['errors']


def test_published_context_hash_and_target_must_match_current_shard():
    cache,reports=sample()
    expected=json.loads(json.dumps(cache['entries']))
    value=next(iter(cache['entries'].values()))
    value['contextHash']='b'*20
    value['evaluationTarget']={'level':9999}
    result=validate(cache,'current',14,reports,expected_entries=expected)
    assert not result['passed']
    assert any(e.startswith('source-context-hash-mismatch:') for e in result['errors'])
    assert any(e.startswith('source-evaluation-target-mismatch:') for e in result['errors'])


def test_wrong_mode_cannot_replace_an_expected_mode_at_same_coverage():
    cache,reports=sample()
    expected=json.loads(json.dumps(cache['entries']))
    original=next(key for key in cache['entries'] if json.loads(key)['profile']=='fast')
    value=cache['entries'].pop(original)
    context=json.loads(original)
    context['fireMode']=1
    cache['entries'][json.dumps(context)]=value
    result=validate(cache,'current',14,reports,expected_entries=expected)
    assert result['coverage']['fast']==1
    assert 'fast:missing-expected-modes' in result['errors']


def test_invalid_key_and_arbitrary_context_hash_are_rejected():
    cache,reports=sample()
    next(iter(cache['entries'].values()))['contextHash']='arbitrary'
    cache['entries']['[]']={}
    result=validate(cache,'current',14,reports)
    assert any(e.startswith('invalid-context-hash:') for e in result['errors'])
    assert 'invalid-cache-key:[]' in result['errors']


def test_partial_and_lower_bound_statuses_remain_visible_and_valid():
    cache,reports=sample()
    for value,status in zip(cache['entries'].values(),('unresolved-model-partial','unresolved-lower-bound')):
        value['scoreStatus']=status
    result=validate(cache,'current',14,reports,expected_entries=cache['entries'])
    assert result['passed']
    assert result['verifiedSourceContexts']==2
    assert result['scoreStatuses']=={'unresolved-model-partial':1,'unresolved-lower-bound':1}
