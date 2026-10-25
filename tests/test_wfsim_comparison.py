"""Reference conversions preserve exact records and reject ambiguous identity."""
import pytest
import hashlib
import json
from types import SimpleNamespace

from tools.compare_wfsim_boards import record_of, reverse_id
from tools.compare_archgun_board_builds import public_evolutions
from tools.fetch_wfsim_runtime import extract_data_pack


def test_board_riven_record_retains_roll_order_and_does_not_alias_source():
    row = dict(mods=['a', 'riven', 'b'], arcanes=['arcane'], exilus='utility@1',
               riven=dict(bonuses=['heat', 'critical_damage'], malus='status_duration', rolls=[1.1, 1.03, .9]))
    record = record_of('weapon', row)
    assert record['riven_pos'] == ['heat', 'critical_damage']
    assert record['riven_rolls'] == [1.1, 1.03, .9]
    assert record['riven_neg'] == 'status_duration'
    record['mods'].clear()
    record['riven_rolls'][0] = 0
    assert row['mods'] == ['a', 'riven', 'b'] and row['riven']['rolls'][0] == 1.1


def test_reverse_identity_never_picks_arbitrary_alias():
    assert reverse_id('path', {'path': ['exact']}) == 'exact'
    for table in ({}, {'path': ['one', 'two']}):
        with pytest.raises(ValueError, match='ambiguous or missing'):
            reverse_id('path', table)


def routes():
    return dict(incarnon=dict(tiers=[dict(tier=3, branches=[
        dict(id='3-1', path='branch1', sources=[dict(icon='/OldIcon')]),
        dict(id='3-2', path='branch2', sources=[dict(icon='/AnotherIcon')]),
    ])]))


def test_declared_evolution_position_handles_renamed_icons():
    definition = dict(weapon='weapon', tier=3, position_in_tier=2, icon='/RenamedIcon')
    choices, proof = public_evolutions(routes(), 'weapon', ['evolution'], {'evolution': definition})
    assert choices == {'tier3': '3-2'}
    assert proof[0]['method'] == 'declared-tier-position'
    assert proof[0]['native'] == 'branch2'


def test_conflicting_evolution_icon_and_position_fail_closed():
    definition = dict(weapon='weapon', tier=3, position_in_tier=2, icon='/OldIcon')
    with pytest.raises(ValueError, match='conflicting'):
        public_evolutions(routes(), 'weapon', ['evolution'], {'evolution': definition})


def pack(tmp_path, files):
    raw = json.dumps(dict(pack='data', format=1, files=files)).encode()
    name = 'pack.data.' + hashlib.sha256(raw).hexdigest()[:12] + '.json'
    parent = tmp_path / 'site/pkg'
    parent.mkdir(parents=True)
    (parent / name).write_bytes(raw)
    return dict(packs=[name], data_format=1)


def test_extract_verified_reference_pack(tmp_path):
    release = pack(tmp_path, {'weapons/example.yaml': 'id: example\n'})
    assert extract_data_pack(tmp_path, release) == 1
    assert (tmp_path / 'data/weapons/example.yaml').read_text() == 'id: example\n'


@pytest.mark.parametrize('path', ['../escape.yaml', 'C:/escape.yaml', '..\\escape.yaml'])
def test_reference_pack_rejects_escaping_paths(tmp_path, path):
    release = pack(tmp_path, {path: 'id: invalid'})
    with pytest.raises(ValueError, match='invalid data-pack'):
        extract_data_pack(tmp_path, release)


def test_reference_pack_rejects_changed_bytes(tmp_path):
    release = pack(tmp_path, {'weapons/example.yaml': 'id: example'})
    (tmp_path / 'site/pkg' / release['packs'][0]).write_text('{}')
    with pytest.raises(ValueError, match='hash mismatch'):
        extract_data_pack(tmp_path, release)


def test_failed_worker_cannot_reuse_an_old_complete_result(tmp_path, monkeypatch):
    from tools import compare_wfsim_boards as comparison
    output = tmp_path / 'comparison'
    comparison.write(output / 'manifest.json', dict(cases=['example'], inputs='current'))
    comparison.write(output / 'cases/example.json', dict(prepared_hash='same'))
    old = dict(status='complete', inputs='current', runs=1, comparison_version=comparison.COMPARISON_VERSION,
               case=dict(prepared_hash='same'))
    comparison.write(output / 'results/example.json', old)
    monkeypatch.setattr(comparison.sys, 'argv', ['compare', 'run', '--runtime', str(tmp_path),
                                              '--output', str(output), '--runs', '2', '--workers', '1'])
    monkeypatch.setattr(comparison.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(SystemExit) as error:
        comparison.main()
    assert error.value.code == 1
    assert comparison.read(output / 'results/example.json')['status'] == 'error'
    archived = list((output / 'results').glob('example.previous-*.json'))
    assert len(archived) == 1 and comparison.read(archived[0]) == old


def test_cross_window_diagnoses_search_model_and_horizon_separately(tmp_path):
    from tools import compare_wfsim_boards as comparison
    ids = ['window', 'model', 'search']
    comparison.write(tmp_path / 'manifest.json', dict(cases=ids, inputs='current', profile='fast',
        windowSeconds=30, skipped=[], release=dict(engine='engine', data='data')))
    for identity in ids:
        local_board, local_ours = (12., 10.) if identity == 'search' else (10., 12.)
        case = dict(id=identity, prepared_hash='same', weapon=identity, mode='base', has_riven=False,
                    board=dict(score=10.), request=dict(mods=['reference']))
        comparison.write(tmp_path / 'cases' / (identity + '.json'), case)
        source = tmp_path / 'results' / (identity + '.json')
        comparison.write(source, dict(status='complete', case=case, local_seconds=1., local_cpu=1.,
            board_local=dict(benchmarkTimeline=dict(killsPerMinute=local_board)),
            ours_local=dict(benchmarkTimeline=dict(killsPerMinute=local_ours)),
            build=dict(build=dict(objectiveScore=local_ours)),
            board_reference=dict(duration=30, score=5., score_se=.01),
            ours_reference=dict(duration=30, score=6., score_se=.01),
            ours_reference_request=dict(mods=['ours'])))
        comparison.write(tmp_path / 'cross-180' / source.name, dict(status='complete',
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            board_local=10. if identity == 'model' else 12.,
            ours_local=12. if identity == 'model' else 10.,
            board_reference=dict(score=30., score_se=.01), ours_reference=dict(score=20., score_se=.01)))
    comparison.summarize(tmp_path)
    rows = comparison.read(tmp_path / 'summary.json')['official_window_replay']['rows']
    assert {r['id']:r['diagnosis'] for r in rows} == {
        'window':'window-objective-difference', 'model':'model-ranking-gap', 'search':'search-miss'}
