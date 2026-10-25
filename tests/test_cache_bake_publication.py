import json
from pathlib import Path
import importlib.util
import xml.etree.ElementTree as ET

import pytest

import app


def test_python_checkout_line_endings_do_not_change_cache_identity(monkeypatch):
    from pathlib import Path
    read = Path.read_bytes
    fingerprint = app._analysis_inputs_fingerprint()
    def windows_lines(path):
        data = read(path)
        return data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n') if path.suffix=='.py' else data
    monkeypatch.setattr(Path,'read_bytes',windows_lines)
    assert app._analysis_inputs_fingerprint()==fingerprint


def test_frozen_runtime_merges_matching_baked_cache_and_local_updates(monkeypatch, tmp_path):
    bundled, local = tmp_path / 'bundled.json', tmp_path / 'local.json'
    base = dict(buildLabel=app.EXPORTS['buildLabel'], stances=app._stances_fingerprint(),
                inputs=app._analysis_inputs_fingerprint(), cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION)
    bundled.write_text(json.dumps(dict(base, entries={'bundled': {'value': 1}, 'both': {'value': 1}})))
    local.write_text(json.dumps(dict(base, entries={'local': {'value': 2}, 'both': {'value': 2}})))
    monkeypatch.setattr(app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(app, 'BUNDLED_ANALYSIS_STATICS_CACHE_PATH', bundled)
    monkeypatch.setattr(app, 'ANALYSIS_STATICS_CACHE_PATH', local)
    assert app._load_analysis_statics_cache() == {
        'bundled': {'value': 1}, 'local': {'value': 2}, 'both': {'value': 2}}
    local.write_text(json.dumps(dict(base, inputs='old', entries={'stale': {}})))
    assert app._load_analysis_statics_cache() == {'bundled': {'value': 1}, 'both': {'value': 1}}
    bundled.write_text(json.dumps(dict(base, inputs='old', entries={'also-stale': {}})))
    assert app._load_analysis_statics_cache() == {}


def test_bundled_cache_cannot_bypass_missing_engine_identity(monkeypatch, tmp_path):
    monkeypatch.setattr(app.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(app, '_analysis_inputs_fingerprint', lambda: (_ for _ in ()).throw(app.SimulationError('missing')))
    assert app._load_analysis_statics_cache() == {}


def test_live_process_preserves_entries_published_by_a_bake(monkeypatch,tmp_path):
    path=tmp_path/'cache.json'
    fingerprint=app._analysis_inputs_fingerprint()
    disk=dict(buildLabel=app.EXPORTS['buildLabel'],stances=app._stances_fingerprint(),
              inputs=fingerprint,cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
              entries={'baked':{'contextHash':'baked-context'}})
    path.write_text(json.dumps(disk),encoding='utf-8')
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE_PATH',path)
    monkeypatch.setattr(app,'ANALYSIS_STATICS_RUNTIME_INPUTS',fingerprint)
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE',{'live':{'contextHash':'live-context'},'__dirty__':True})
    monkeypatch.setattr(app.ANALYSIS_STATICS_PERSISTENCE,'enabled',True)
    app._persist_analysis_statics_cache()
    assert set(json.loads(path.read_text(encoding='utf-8'))['entries'])=={'baked','live'}


def test_old_loaded_engine_cannot_overwrite_new_fingerprint_cache(monkeypatch,tmp_path):
    path=tmp_path/'cache.json'
    path.write_text('{"published":"new-engine"}',encoding='utf-8')
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE_PATH',path)
    monkeypatch.setattr(app,'ANALYSIS_STATICS_RUNTIME_INPUTS','old-loaded-engine')
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE',{'old':{},'__dirty__':True})
    monkeypatch.setattr(app.ANALYSIS_STATICS_PERSISTENCE,'enabled',True)
    app._persist_analysis_statics_cache()
    assert json.loads(path.read_text(encoding='utf-8'))=={'published':'new-engine'}


def test_bake_excludes_inherited_ranged_melee_and_zero_damage_modes():
    spec=importlib.util.spec_from_file_location('bake_publication',app.ROOT/'tools/bake-analysis-statics.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    weapon=dict(slot='secondary',fireModes=[
        {'damage':{'types':{'DT_EXPLOSION':250.}}},
        {'behaviorKind':'auxiliary-melee','damage':{'types':{'DT_IMPACT':40.}}},
        {'damage':{'types':{'DT_IMPACT':0.}}}])
    assert module._supported_bake_modes(weapon)==[0]


def test_bake_workers_default_to_the_compute_pool_and_stay_within_the_machine(monkeypatch,tmp_path):
    from tools.run_riven_acceptance_bake import MAX_BAKE_WORKERS
    from wfarsenal import parallel
    spec=importlib.util.spec_from_file_location('bake_worker_limit',app.ROOT/'tools/bake-analysis-statics.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,'_catalog_weapons',lambda:[])
    monkeypatch.setattr(module,'SHARD_ROOT',tmp_path)
    cases=(([],min(parallel.default_workers(),MAX_BAKE_WORKERS)),
           (['--workers',str(MAX_BAKE_WORKERS+48)],MAX_BAKE_WORKERS),(['--workers','3'],3))
    for requested,expected in cases:
        report=tmp_path/'plan.json'
        monkeypatch.setattr(module.sys,'argv',['bake','--dry-run','--report',str(report),*requested])
        assert module.main()==0
        assert json.loads(report.read_text())['workers']==expected
    monkeypatch.setattr(module.sys,'argv',['bake','--workers','0','--dry-run'])
    with pytest.raises(SystemExit):
        module.main()


def test_several_profiles_need_one_report_per_profile(monkeypatch,tmp_path):
    spec=importlib.util.spec_from_file_location('bake_profiles',app.ROOT/'tools/bake-analysis-statics.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module,'_catalog_weapons',lambda:[])
    monkeypatch.setattr(module,'SHARD_ROOT',tmp_path)
    monkeypatch.setattr(module.sys,'argv',['bake','--dry-run','--profile','fast,standard','--report',str(tmp_path/'plan.json')])
    with pytest.raises(SystemExit):
        module.main()
    monkeypatch.setattr(module.sys,'argv',['bake','--dry-run','--profile','fast,standard','--report',str(tmp_path/'{profile}.json')])
    assert module.main()==0
    assert {json.loads((tmp_path/f'{p}.json').read_text())['profile'] for p in ('fast','standard')}=={'fast','standard'}


def test_default_parallel_pool_stays_within_the_machine():
    from wfarsenal.parallel import default_workers, logical_core_count
    assert 1 <= default_workers() <= min(logical_core_count(), 16)


def test_delivery_resume_requires_current_successful_regression(tmp_path):
    from tools.run_completion_delivery import cached_regression
    report=dict(inputs='current',cacheVersion=14,jobs={'regression':dict(status='complete',exitCode=0)})
    status_path=tmp_path/'delivery-status.json'
    status_path.write_text(json.dumps(report))
    suite=ET.Element('testsuite',tests='10',failures='0',errors='0')
    xml_path=tmp_path/'regression.xml'
    ET.ElementTree(suite).write(xml_path)
    assert cached_regression(tmp_path,'current',14)['reused']
    assert cached_regression(tmp_path,'old',14) is None
    assert cached_regression(tmp_path,'current',13) is None
    suite.set('failures','1')
    ET.ElementTree(suite).write(xml_path)
    assert cached_regression(tmp_path,'current',14) is None


def test_live_engine_refreshes_a_newer_published_cache(monkeypatch,tmp_path):
    cache_path=tmp_path/'cache.json'
    fingerprint=app._analysis_inputs_fingerprint()
    payload=dict(buildLabel=app.EXPORTS['buildLabel'],stances=app._stances_fingerprint(),
                 inputs=fingerprint,cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                 entries={'new':{'contextHash':'a'*20}})
    cache_path.write_text(json.dumps(payload),encoding='utf-8')
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE_PATH',cache_path)
    monkeypatch.setattr(app,'ANALYSIS_STATICS_CACHE_MTIME_NS',0)
    app.ANALYSIS_STATICS_CACHE.clear()
    app._refresh_analysis_statics_cache_if_newer()
    assert 'new' in app.ANALYSIS_STATICS_CACHE
