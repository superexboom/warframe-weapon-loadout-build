import json

from tools.validate_baked_statics import validate


def sample():
    entries={json.dumps({'weapon':p,'profile':p}):dict(contextHash='context-'+p,evaluationTarget={},scoreStatus='ok')
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
