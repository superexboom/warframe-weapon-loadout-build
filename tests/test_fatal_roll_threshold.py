"""Roll-dependent fatal negatives (2026-10-16): a malus fatal at its theoretical
roll but not at its lowest roll gets the roll it turns fatal at.

The motivating case is a 3+1 Status Duration window that crosses -100% (Dual
Decurion 87.7-107.2%): faster Heat strip makes it the best malus until
statuses expire between shots, and at -100% they vanish. The bisection must
follow the same two-step judgement as the weapon-level assessment: fixed
build first, re-search only past the fixed-build boundary.
"""
from __future__ import annotations

import pytest

from wfarsenal import optimizer as o

TOP = o._RivenLine("3", "触发时间", 107.24, 87.74, 107.24, True, "%",
                   o._effect_from_code("3", 107.24, negative=True, source="riven:theoretical:3"))
LOW = TOP.value * o.RIVEN_ROLL_LOW / o.RIVEN_ROLL_HIGH


def judge(fixed_cliff, searched_cliff=None):
    """Fixed build fatal past ``fixed_cliff``; the re-search rescues up to ``searched_cliff``."""
    searched_cliff = fixed_cliff if searched_cliff is None else searched_cliff
    calls = {"fixed": 0, "search": 0}

    def fixed_delta(line):
        calls["fixed"] += 1
        assert line.effect is not None and line.effect.value == pytest.approx(-line.value / 100.0)
        return 0.3 if line.value <= fixed_cliff else -0.6

    def fatal_at(line, delta):
        if delta >= -o.FATAL_NEGATIVE_LOSS:
            return False
        calls["search"] += 1
        return line.value > searched_cliff

    return fixed_delta, fatal_at, calls


def test_cliff_on_the_fixed_build_costs_one_re_search():
    fixed_delta, fatal_at, calls = judge(96.37)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert threshold == 96.3  # one decimal, rounded towards the safe side
    assert calls["search"] == 1


def test_re_search_rescues_rolls_past_the_fixed_boundary():
    fixed_delta, fatal_at, calls = judge(93.0, searched_cliff=99.12)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert 99.0 <= threshold <= 99.12
    assert calls["search"] > 1


def test_fatal_across_the_whole_window_has_no_threshold():
    fixed_delta, fatal_at, _ = judge(LOW - 1.0)
    assert o._fatal_roll_threshold(TOP, fixed_delta, fatal_at) is None


def test_lowest_roll_rescued_only_by_the_re_search():
    fixed_delta, fatal_at, _ = judge(LOW - 1.0, searched_cliff=100.0)
    threshold = o._fatal_roll_threshold(TOP, fixed_delta, fatal_at)
    assert 99.9 <= threshold <= 100.0
