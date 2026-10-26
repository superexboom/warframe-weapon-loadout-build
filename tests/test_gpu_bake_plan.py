import pytest
from tools.gpu_bake_plan import estimate,admission
from tools.audit_gpu_bake import classify


def probe(**overrides):
    args=dict(scope='bake',full_candidate_kernel=True,exact=True,resources_ok=True,
              candidates=2048,cpu_seconds=.1,gpu_seconds=.03,prepare_seconds=.02,
              transfer_seconds=.005,check_seconds=.005,queue_seconds=0.)
    args.update(overrides);return admission(**args)


def test_microkernel_cannot_publish_full_cache():
    assert probe(full_candidate_kernel=False)['backend']=='cpu'
    assert probe(exact=False)['backend']=='cpu'
    assert probe(resources_ok=False)['backend']=='cpu'
    assert probe(scope='interactive')['backend']=='cpu'


def test_admission_counts_preparation_validation_and_queue_wait():
    assert probe()['backend']=='gpu'
    assert probe(queue_seconds=.1)['backend']=='cpu'
    assert probe(prepare_seconds=.1)['backend']=='cpu'
    assert probe(cpu_seconds=.01)['backend']=='cpu'


def test_amdahl_does_not_apply_kernel_speedup_to_whole_bake():
    r=estimate(240.,.5,.5,4.,.02)
    assert r['offloadShare']==.25
    assert r['serializedMinutes']==pytest.approx(199.8)
    assert r['idealOverlapMinutes']==pytest.approx(184.8)
    assert estimate(240,0,.5,100)['serializedMinutes']==240
    with pytest.raises(ValueError):estimate(240,1.1,.5,4.)


def test_context_features_not_weapon_names_control_cost_tier():
    assert classify({})[0]=='fixed-form-candidate'
    assert classify({'conditionOverload':True})[0]=='finite-buff-preparation-required'
    assert classify({'auditShapes':['clusters']})[0]=='stateful-cpu-first'
    assert classify({'cycle':{'pool':45}})[0]=='stateful-cpu-first'


@pytest.mark.parametrize('overrides',[{'min_gain':float('nan')},{'gpu_seconds':-1.},
                                      {'cpu_seconds':float('inf')},{'candidates':True}])
def test_invalid_probe_never_admits(overrides):
    assert probe(**overrides)['backend']=='cpu'
