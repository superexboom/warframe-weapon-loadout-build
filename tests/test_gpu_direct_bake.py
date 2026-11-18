"""Offline bake tables and the historical bounded direct-stream contract."""
import math
import struct

import pytest

from wfarsenal import native_replay


def test_direct_stream_never_drops_a_real_weapons_status(monkeypatch):
    import app
    from wfarsenal import optimizer as o, search_combat
    from wfarsenal.damage import ModEffect, Scenario
    from tools.gpu_bake.backend import DirectBatch

    core = native_replay.wfcore
    if not hasattr(core, 'direct_bake_stream'):
        pytest.skip('native direct-stream support required')
    original, streams = core.trajectory, []
    def capture(config, helper):
        try:
            streams.append(core.direct_bake_stream(config, helper))
        except core.NativeUnsupported:
            streams.append(None)
        return original(config, helper)
    monkeypatch.setattr(core, 'trajectory', capture)
    raw = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Lato')
    weapon = o._select_fire_mode(raw, 0, weapon_type='pistol')[0]
    scenario = Scenario(trigger_policy='emergent')
    context = dict(target=dict(health=3000., armour=200., baseLevel=1), level=1, windowSeconds=30., headshotChance=0.)
    monkeypatch.setattr(search_combat, '_REPLAYS', search_combat._REPLAYS.__class__())
    for effects in ([], [ModEffect('WEAPON_PROC_CHANCE', 'STACKING_MULTIPLY', -1.)]):
        stats = o.apply_mods(weapon, effects, scenario=scenario)
        o._bind_combat_inputs(stats, weapon, (), effects, scenario)
        result = search_combat.window(stats, context, score_only=True)
        stream = streams.pop()
        if effects:
            assert DirectBatch.cpu([stream])[0] == tuple(result[k] for k in ('killsPerMinute', 'windowDps', 'totalWindowDamage'))
        else:
            assert stream is None


def test_capped_pool_prefix_table_is_exact_across_pool_lifetimes():
    core = native_replay.wfcore
    if not hasattr(core, 'bake_pool_capture'):
        pytest.skip('GPU pool table native support required')

    a, b = (.63, .42), (.25, 1.4)
    near_a = (math.nextafter(a[0], 1.), a[1])

    def run():
        pool = core.CappedPool(10.)
        snapshots = []

        def record():
            snapshots.append((bool(pool), pool.version, struct.pack('<13d', *pool.distribution(), *pool.stats())))

        record()
        assert not pool.add(.3, 1., 0.)
        record()
        for end, key in [(1., a), (4., a), (4.5, a), (5., a), (6., b), (7., a)]:
            assert pool.add(end, *key)
            record()
        pool.expire(2.)
        record()
        for end in (8., 9.):
            assert pool.add(end, *b)
            record()
        pool.expire(10.)
        record()
        assert not pool
        for end, key in [(11., a), (12., near_a), (13., a)]:
            assert pool.add(end, *key)
            record()
        pool.reset()
        record()
        return snapshots

    core.bake_pool_stop()
    try:
        without_table = run()
        core.bake_pool_capture(2)
        assert run() == without_table
        keys = core.bake_pool_pending()
        assert keys == [a, b]
        assert core.bake_pool_pending() == []
        core.bake_pool_stop()
        core.bake_pool_install(keys, 3, core.bake_pool_reference(keys, 3))
        assert run() == without_table
        assert core.bake_pool_stats() == dict(hits=6, misses=5, keys=2)
    finally:
        core.bake_pool_stop()
