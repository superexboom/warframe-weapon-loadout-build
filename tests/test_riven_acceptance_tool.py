from copy import deepcopy

import pytest

from tools.audit_riven_analysis_context import case_reusable, cycle_coverage_passed, request_for


@pytest.mark.parametrize('headshots',[0.,1.])
def test_headshot_probability_reaches_the_evaluation_target(headshots):
    scenario={'incarnonCycle':True,'headshotChance':headshots}
    request=request_for('Felarx',scenario)
    assert request['benchmarkTarget']['headshotChance']==headshots
    assert scenario=={'incarnonCycle':True,'headshotChance':headshots}
    assert request_for('Felarx',{})['benchmarkTarget']['headshotChance']==0.


def test_equal_scores_without_transforms_do_not_cover_the_requested_cycle():
    request=request_for('Felarx',{'incarnonCycle':True,'headshotChance':1.})
    replays={key:{'passed':True,'transforms':0} for key in ('baseline','actual','optimal')}
    assert not cycle_coverage_passed('Felarx',request,replays)
    replays['baseline']['transforms']=1
    replays['actual']['transforms']=1
    assert not cycle_coverage_passed('Felarx',request,replays)
    replays['optimal']['transforms']=1
    assert cycle_coverage_passed('Felarx',request,replays)
    misbound=deepcopy(request)
    misbound['benchmarkTarget']['headshotChance']=0.
    assert not cycle_coverage_passed('Felarx',misbound,replays)
    assert cycle_coverage_passed('Felarx',request_for('Felarx',{}),{})


def test_same_fingerprint_cannot_reuse_another_requested_context():
    request=request_for('Felarx',{'incarnonCycle':True,'headshotChance':1.})
    row={'name':'Felarx','request':deepcopy(request),'inputFingerprint':'current','passed':True,
         'replays':{key:{'transforms':1} for key in ('baseline','actual','optimal')}}
    assert case_reusable(row,request,'current')
    assert not case_reusable(row,request,'old')
    row['request']['benchmarkTarget']['headshotChance']=0.
    assert not case_reusable(row,request,'current')
    row['request']=deepcopy(request)
    row['replays']['actual']['transforms']=0
    assert not case_reusable(row,request,'current')
