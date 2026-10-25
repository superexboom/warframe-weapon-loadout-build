from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace

import pytest
import app
from wfarsenal import optimizer
from wfarsenal.search_session import SESSION, memoized_search


@pytest.fixture
def captured_analysis(monkeypatch):
    calls = []
    monkeypatch.setattr(app, '_ANALYSIS_RESULTS', OrderedDict())
    monkeypatch.setattr(app, '_persist_analysis_statics_cache', lambda: None)
    monkeypatch.setattr(app, '_refresh_analysis_statics_cache_if_newer', lambda: None)
    def analyze(_directory, request, **kwargs):
        calls.append(deepcopy(request))
        return {'actual': {'value': 1}, 'evaluationTarget': deepcopy(request['benchmarkTarget'])}
    monkeypatch.setattr(optimizer, 'analyze_riven_request', analyze)
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Burston Prime')
    request = dict(weapon=weapon['path'], disposition=1.35, profile='standard', stats=[
        dict(code=c,value=v,negative=n) for c,v,n in
        [('W',313.2,False),('6',125.2,False),('1',163.8,False),('3',91.2,True)]])
    return calls, request


def test_default_target_and_exact_result_cache_preserve_headshots(captured_analysis):
    calls, request = captured_analysis
    for chance in (0., .5, 1.):
        result = app.analyze_payload({**request, 'headshotChance':chance})
        assert result['evaluationTarget']['headshotChance'] == chance
        result['actual']['value'] = 999
        repeated = app.analyze_payload({**request,'headshotChance':chance,'progressToken':'different'})
        assert repeated['responseCache'] == 'exact-request-hit'
        assert repeated['actual']['value'] == 1
    assert len(calls) == 3


def test_result_cache_does_not_cross_roll_profile_or_scenario(captured_analysis):
    calls, request = captured_analysis
    app.analyze_payload(request)
    changed = deepcopy(request)
    changed['stats'][0]['value'] = 300.
    app.analyze_payload(changed)
    app.analyze_payload({**request,'profile':'fast'})
    app.analyze_payload({**request,'scenario':{'incarnonCycle':True}})
    assert len(calls) == 4


@pytest.mark.parametrize('chance',[-1,2,True,float('nan')])
def test_invalid_headshot_context_is_rejected(captured_analysis, chance):
    _, request = captured_analysis
    with pytest.raises(app.SimulationError,match='headshotChance'):
        app.analyze_payload({**request,'headshotChance':chance})


def test_fixed_build_ranking_never_forces_mod_removal_to_meet_budget(monkeypatch):
    cards = tuple(SimpleNamespace(required=False,key=str(i)) for i in range(7))
    sizes = []
    def evaluate(weapon,cards,riven,**kwargs):
        sizes.append(len(cards))
        return SimpleNamespace(cards=cards,score=len(cards))
    monkeypatch.setattr(optimizer,'_evaluate',evaluate)
    result = optimizer._best_fixed({},cards,object(),scenario=optimizer.Scenario(),
                                   metric='sustainedDps',max_keep_cap=3)
    assert len(result.cards) == 7
    assert sizes == [7]


def test_search_memo_is_request_local_and_context_bound():
    calls=[]
    @memoized_search
    def evaluate(value, **kwargs):
        calls.append((value,kwargs))
        return len(calls)
    token=SESSION.set({'searches':OrderedDict(),'memoHits':0})
    try:
        assert evaluate(1,target={'headshotChance':.5}) == 1
        assert evaluate(1,target={'headshotChance':.5}) == 1
        assert evaluate(1,target={'headshotChance':0.}) == 2
        assert SESSION.get()['memoHits'] == 1
    finally:
        SESSION.reset(token)
    assert evaluate(1,target={'headshotChance':.5}) == 3


def test_static_work_is_reported_without_retaining_another_requests_counts():
    from wfarsenal.search_session import session_request, heartbeat

    @session_request
    def analyze(_directory, request):
        assert not SESSION.get().get('negativeWork')
        heartbeat(3)
        SESSION.get()['negativeWork'] = {'fastSearches': 1, 'fastProofs': 1}
        return {'bakeStaticsOnly': True}

    for _ in range(2):
        result = analyze('.', {'_bakeStaticsOnly': True})
        assert result['searchWork']['evaluations'] == 3
        assert result['searchWork']['negative'] == {'fastSearches': 1, 'fastProofs': 1}
        assert SESSION.get() is None


@pytest.mark.parametrize('profile,seconds', [('fast', 8.), ('standard', 15.), ('deep', 45.)])
def test_negative_classification_flag_does_not_disable_the_callers_budget(profile, seconds):
    import math
    from wfarsenal.search_session import session_request

    @session_request
    def analyze(_directory, request):
        state = SESSION.get()
        assert math.isfinite(state['deadline']) and state['phaseSeconds'] == seconds
        return dict(searchStatus={}, skipped=[])

    result = analyze('.', dict(profile=profile, _bakeNegativeClassificationOnly=True))
    assert result['searchWork']['budgetSeconds'] > seconds


def test_phase_heartbeat_is_monotonic_and_exposes_work():
    app._begin_analysis_progress('work-test')
    app._report_analysis_progress('work-test','quality|123')
    app._report_analysis_progress('work-test','actual|124')
    row=app._ANALYZE_PROGRESS['work-test']
    assert row['currentStage'] == 'actual'
    assert row['evaluations'] == 124
    assert row['stageIndex'] == app._ANALYZE_STAGES.index('quality')+1


def test_busy_analysis_returns_immediately_instead_of_silent_queue(captured_analysis):
    _, request = captured_analysis
    assert app.ANALYZE_LOCK.acquire(blocking=False)
    try:
        with pytest.raises(app.SimulationError, match='正在计算其他请求'):
            app.analyze_payload(request)
    finally:
        app.ANALYZE_LOCK.release()
    assert app.analyze_payload(request)['responseCache'] == 'miss'


def test_default_workers_follow_the_core_layout(monkeypatch):
    from wfarsenal import parallel
    monkeypatch.delenv('WF_ANALYZER_SERIAL',raising=False)
    for physical, logical, expected in ((8, 16, 10), (4, 8, 5), (4, 4, 4), (1, 2, 1), (32, 64, 16)):
        monkeypatch.setattr(parallel,'_physical_core_count',lambda physical=physical:physical)
        monkeypatch.setattr(parallel,'logical_core_count',lambda logical=logical:logical)
        assert parallel.default_workers() == expected


def test_session_does_not_replace_engine_input_error():
    with pytest.raises(app.SimulationError,match='request must be a JSON object'):
        optimizer.analyze_riven_request(app.EXPORT_DIR, [])


def test_real_progress_endpoint_preserves_heartbeat_fields():
    import json
    import threading
    import urllib.request
    app._begin_analysis_progress('http-work-test')
    app._report_analysis_progress('http-work-test','optimal|345')
    server=app.create_server(port=0)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        url=f'http://127.0.0.1:{server.server_port}/api/analyze/progress?id=http-work-test'
        with urllib.request.urlopen(url,timeout=5) as response:
            row=json.load(response)
        assert row['currentStage']=='optimal'
        assert row['evaluations']==345
        app._finish_analysis_progress('http-work-test')
        with urllib.request.urlopen(url,timeout=5) as response:
            assert json.load(response)['percent']==100.
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
