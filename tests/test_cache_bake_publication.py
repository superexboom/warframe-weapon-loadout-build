import json
from pathlib import Path
import importlib.util

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
