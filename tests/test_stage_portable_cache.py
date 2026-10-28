import json
from pathlib import Path

import pytest
from tools import stage_portable_cache as staging


def fixture(tmp_path, monkeypatch):
    root, destination = tmp_path / 'source', tmp_path / 'staged'
    modules = root / 'vendor/wfarsenal'
    modules.mkdir(parents=True)
    for name in ('__init__.py', 'optimizer.py', 'damage.py'):
        (modules / name).write_text('# runtime source\n')
    (modules / 'wfcore.pyd.old-test').write_bytes(b'old binary')
    for name in ('app.py', 'data_sources.py', 'enemy_assets.py'):
        (root / name).write_text('# app source\n')
    (root / 'data').mkdir()
    (root / 'data/source-lock.json').write_text('{}')
    (destination / 'data').mkdir(parents=True)
    (destination / 'data/source-lock.json').write_text('{}')
    metadata = dict(inputs='current', stances='stance', buildLabel='build', cacheVersion=26)
    monkeypatch.setattr(staging, '_metadata', lambda path: dict(metadata))
    cache = root / '.local/cache/riven-analysis-statics.json'
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps(dict(metadata, entries={'weapon': {'contextHash': 'context'}})))
    return root, destination, cache


def test_staging_carries_matching_cache_and_only_source_identity_files(tmp_path, monkeypatch):
    root, destination, cache = fixture(tmp_path, monkeypatch)
    result = staging.stage(root, destination, require_cache=True)
    assert result['cacheEntries'] == 1
    assert (destination / 'data/riven-analysis-statics.json').read_bytes() == cache.read_bytes()
    assert (destination / 'app.py').read_bytes() == (root / 'app.py').read_bytes()
    assert sorted(p.name for p in (destination / 'wfarsenal').iterdir()) == ['__init__.py', 'damage.py', 'optimizer.py']


def test_staging_never_keeps_a_stale_seed_when_identity_changes(tmp_path, monkeypatch):
    root, destination, cache = fixture(tmp_path, monkeypatch)
    staging.stage(root, destination, require_cache=True)
    data = json.loads(cache.read_text()); data['inputs'] = 'old'
    cache.write_text(json.dumps(data))
    assert staging.stage(root, destination)['cacheEntries'] == 0
    assert not (destination / 'data/riven-analysis-statics.json').exists()
    with pytest.raises(ValueError, match='matching'):
        staging.stage(root, destination, require_cache=True)


def test_staging_refuses_the_source_checkout_as_its_destination(tmp_path, monkeypatch):
    root, destination, cache = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match='separately staged'):
        staging.stage(root, root)


def test_unchanged_lock_preserves_exact_identity_bytes(tmp_path, monkeypatch):
    root, destination, cache = fixture(tmp_path, monkeypatch)
    original = b'{"activeBuild":"build", "policy":{"same":true}}\r\n'
    (root / 'data/source-lock.json').write_bytes(original)
    (destination / 'data/source-lock.json').write_text(json.dumps(json.loads(original), indent=2))
    staging.stage(root, destination, require_cache=True)
    assert (destination / 'data/source-lock.json').read_bytes() == original


def test_different_snapshot_lock_is_never_replaced(tmp_path, monkeypatch):
    root, destination, cache = fixture(tmp_path, monkeypatch)
    staged = b'{"snapshotRoot":"data/snapshots/next"}'
    (destination / 'data/source-lock.json').write_bytes(staged)
    staging.stage(root, destination, require_cache=True)
    assert (destination / 'data/source-lock.json').read_bytes() == staged
