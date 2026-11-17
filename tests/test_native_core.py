"""The native core matches the Python reference bit for bit.

Randomized operation sequences drive the Python class and its native port side
by side; every observable value must be identical (==, not approx). Skipped
when the library is not built (tools/build_native.py).
"""
import math
import random

import pytest

wfcore = pytest.importorskip("wfarsenal.wfcore")
from wfarsenal import proc_probability as pp  # noqa: E402


def _values(rng, n):
    kinds = [lambda: rng.uniform(-1e6, 1e6), lambda: rng.uniform(-1, 1), lambda: rng.uniform(0, 1e-9),
             lambda: rng.choice([0.0, -0.0, 1.0, 0.1, 0.2, 0.3]), lambda: rng.uniform(1e15, 1e17)]
    return [rng.choice(kinds)() for _ in range(n)]


def test_sum_matches_cpython():
    rng = random.Random(7)
    for _ in range(20000):
        values = _values(rng, rng.randint(0, 12))
        assert wfcore.py_sum(values) == sum(values) or (math.isnan(sum(values)) and math.isnan(wfcore.py_sum(values)))


def test_c_math_matches_cpython():
    rng = random.Random(11)
    for _ in range(20000):
        x = rng.uniform(1e-12, 50)
        assert wfcore.c_math("log", x, 0) == math.log(x)
        assert wfcore.c_math("expm1", -x, 0) == math.expm1(-x)
        z = rng.uniform(-8, 8)
        assert wfcore.c_math("erfc", z, 0) == math.erfc(z)
        base, exponent = rng.uniform(0, 1), rng.choice([rng.randint(0, 20), rng.uniform(0, 30)])
        assert wfcore.c_math("pow", base, exponent) == base ** exponent


def _heat_ops(rng, steps):
    t = 0.0
    scale = rng.choice([1.0, 1.0, 0.5, 1.5])
    for _ in range(steps):
        t += rng.choice([0.0, rng.uniform(0, 0.2), rng.uniform(0, 1.5), rng.uniform(0, 4)])
        if rng.random() < 0.08:
            scale = rng.choice([1.0, 0.5, 1.5, 2.0])
        op = rng.random()
        if op < 0.55:
            absence = rng.choice([0.0, 1.0, rng.random(), rng.random() ** 8])
            yield ("add", t, absence, rng.uniform(0, 3), rng.uniform(0, 500), rng.choice([6.0, 6.0 * scale, 3.0]), scale)
        elif op < 0.75:
            yield ("expire", t)
        elif op < 0.97:
            yield ("strip", t - rng.choice([0.0, 0.0, rng.uniform(0, 0.3)]))
        else:
            yield ("reset",)


def test_heat_chains_match_python():
    rng = random.Random(3)
    for run in range(400):
        ref, nat = pp.HeatChains(), wfcore.HeatChains()
        for op in _heat_ops(rng, rng.randint(5, 200)):
            name, args = op[0], op[1:]
            a = getattr(ref, name)(*args)
            b = getattr(nat, name)(*args)
            assert a == b, (run, op)
            assert (ref.active(), ref.alive(), ref.count(), ref.seed()) == (nat.active(), nat.alive(), nat.count(), nat.seed()), (run, op)


def test_capped_pool_matches_python():
    rng = random.Random(5)
    for run in range(500):
        cap = rng.choice([4, 5, 10])
        ref, nat = pp.CappedPool(cap), wfcore.CappedPool(cap)
        t = 0.0
        for _ in range(rng.randint(1, 120)):
            t += rng.choice([0.0, rng.uniform(0, 0.5), rng.uniform(0, 4)])
            op = rng.random()
            if op < 0.5:
                args = (t + rng.choice([6.0, 8.0, 10.0, rng.uniform(0.5, 12)]), rng.choice([0.0, 1.0, rng.random()]),
                        rng.choice([0.0, rng.uniform(0, 3), rng.uniform(0, 0.2)]))
                assert ref.add(*args) == nat.add(*args)
            elif op < 0.7:
                ref.expire(t), nat.expire(t)
            elif op < 0.98:
                assert ref.stats() == nat.stats() and ref.distribution() == nat.distribution(), run
            else:
                ref.reset(), nat.reset()
            assert bool(ref) == bool(nat) and ref.version == nat.version


def test_status_presence_matches_python():
    rng = random.Random(9)
    for run in range(500):
        ref, nat = pp.StatusPresence(), wfcore.StatusPresence()
        t = 0.0
        for _ in range(rng.randint(1, 150)):
            t += rng.uniform(0, 1)
            if rng.random() < 0.6:
                args = (t + rng.uniform(0, 10), rng.choice([0.0, 1.0, 1.2, rng.random(), rng.random() ** 20]))
                ref.add(*args), nat.add(*args)
            else:
                assert ref.probability(t) == nat.probability(t), run


def test_kill_attribution_matches_python():
    rng = random.Random(13)
    for run in range(500):
        period = rng.choice([1.0, 0.5, 0.1])
        interval = rng.choice([None, 0.25, 1.0])
        ref, nat = pp.KillAttribution(period, interval=interval), wfcore.KillAttribution(period, interval)
        t = 0.0
        for _ in range(rng.randint(1, 300)):
            t += rng.choice([0.0, rng.uniform(0, 0.3), 1.0])
            op = rng.random()
            if op < 0.8:
                args = (t, rng.choice([0.0, rng.uniform(0, 500)]), rng.choice([0.0, rng.uniform(0, 900)]),
                        rng.choice([0.0, rng.uniform(0, 2), -0.1]), rng.choice([0.0, rng.random(), 1.0]),
                        rng.random() < 0.5)
                ref.add(*args), nat.add(*args)
            elif op < 0.97:
                args = (t, rng.uniform(0, 2000), rng.choice([None, t + rng.uniform(0, 3)]))
                try:
                    expected = ref.crossing(*args)
                except IndexError:
                    with pytest.raises(IndexError):
                        nat.crossing(*args)
                    continue
                assert nat.crossing(*args) == expected, (run, args)
            else:
                ref.reset(), nat.reset()


def test_capped_stack_add_matches_python():
    rng = random.Random(17)
    for run in range(3000):
        dists = [[rng.random() for _ in range(rng.randint(1, 11))] for _ in range(rng.randint(0, 6))]
        absence, count, cap = rng.choice([0.0, 1.0, rng.random()]), rng.choice([0.0, rng.uniform(0, 4)]), 10
        items = [{"dist": list(d)} for d in dists]
        instance = {}
        added = pp.capped_stack_add(items, absence, count, instance, cap)
        nat_added, nat_dists = wfcore.capped_stack_add_dists(dists, absence, count, cap)
        assert added == nat_added, run
        assert [item["dist"] for item in items] == nat_dists, run


def test_arena_spatial_bvh_nearest_all_hits_and_segment_bounds():
    from wfarsenal.arena_scene import TriangleBVH
    from tools.import_arena_scene import _triangulate_nav_polygon, _ZeroAreaNavFace

    # Source collinear face is isolated with original IDs; a bowtie whose
    # Newell normal cancels is still a format error, never quarantined.
    with pytest.raises(_ZeroAreaNavFace) as defect:
        _triangulate_nav_polygon([(0., 0., 0.), (1., 0., 0.), (2., 0., 0.)],
                                 [(0, 1), (1, 2), (2, 0)], 4953)
    assert defect.value.source_face == 4953 and defect.value.ring == [0, 1, 2]
    with pytest.raises(ValueError) as crossing:
        _triangulate_nav_polygon([(0., 0., 0.), (2., 0., 2.), (0., 0., 2.), (2., 0., 0.)],
                                 [(0, 1), (1, 2), (2, 3), (3, 0)], 4954)
    assert not isinstance(crossing.value, _ZeroAreaNavFace)
    from wfarsenal.arena_scene import ArenaScene
    raw={"nav":{"vertices":[[-3.,0.,-3.],[3.,0.,-3.],[0.,0.,3.]],
                "triangles":[[0,1,2]],"nodePositions":[[0.,0.,0.]],"nativePortals":[]},
         "collision":{"vertices":[[-3.,0.,-3.],[3.,0.,-3.],[0.,0.,3.]],"triangles":[[0,1,2]]},
         "start":{"face":0,"position":[0.,0.,0.]},"spawns":[]}
    standing_scene=ArenaScene(raw,native=False)
    assert standing_scene.validate_standing([0.,.05,0.],0)["position"]==[0.,0.,0.]
    assert standing_scene.metrics=={"rays":0,"blocked":0,"pathSearches":0}
    for position,face in [([0.,4.,0.],0),([8.,0.,0.],0)]:
        with pytest.raises(ValueError):standing_scene.validate_standing(position,face)
    vertices = [(-2., 0., -2.), (2., 0., -2.), (0., 0., 2.),
                (-2., 3., -2.), (2., 3., -2.), (0., 3., 2.)]
    reference = TriangleBVH(vertices, [(0, 1, 2), (3, 4, 5)], native=False)
    native = wfcore.SpatialIndex(vertices, [(0, 1, 2), (3, 4, 5)])
    for origin, direction, limit in [((0., 5., 0.), (0., -2., 0.), 10.),
                                     ((0., 1., 0.), (0., 1., 0.), 1.5),
                                     ((0., 1., 0.), (0., 1., 0.), 3.),
                                     ((10., 1., 0.), (0., -1., 0.), 5.)]:
        expected = reference.raycast(origin, direction, limit)
        actual = native.raycast(origin, direction, limit)
        assert actual == (None if expected is None else (expected.distance, expected.triangle))
        assert native.all_hits(origin, direction, limit) == [(h.distance, h.triangle) for h in reference.all_hits(origin, direction, limit)]
    assert native.raycast_batch([((0., 5., 0.), (0., -1., 0.), 10.)]) == [(2., 1)]

    # Native graph keeps directed edge indices and Python heap(cost,node) ties;
    # sparse shared key IDs disable all matching edges, in either direction.
    graph = wfcore.PathGraph(5, [(0, 2, 1., 9), (0, 1, 1., 8),
                                 (2, 3, 1., 7), (1, 3, 1., 7),
                                 (0, 3, 2. + 5e-9, 10)])
    distances, previous, indices = graph.search(0, False, [])
    assert distances[:3] == [0., 1., 1.] and math.isinf(distances[4])
    assert previous[3] == 0 and indices[3] == 4  # epsilon prevents tiny update
    reverse = graph.search(3, True, [7, 10, 1_000_000])
    assert reverse[0][3] == 0. and math.isinf(reverse[0][0])
    tied = wfcore.PathGraph(4, [(0, 2, 1., 0), (0, 1, 1., 1),
                                (2, 3, 1., 2), (1, 3, 1., 3)])
    assert tied.search(0, False, [])[1][3] == 1
    assert tied.search(3, True, [])[2][0] == 1
