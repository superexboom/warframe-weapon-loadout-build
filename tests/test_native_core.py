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
