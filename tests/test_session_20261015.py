"""2026-10-15: minimal Forma, Shapley part values, native kill branches, concurrent searches."""
from __future__ import annotations

import itertools
import math
import threading
import time

import pytest

from wfarsenal import loadout_search
from wfarsenal import optimizer as o

I = o.FormaItem


# ── minimal Forma ─────────────────────────────────────────────────────────

def _brute_force(slots, items, limit):
    """Fewest Forma over every placement that keeps the elemental order."""
    best = None
    n = len(slots)
    for perm in itertools.permutations(range(n), len(items)):
        elemental = [perm[i] for i, item in enumerate(items) if item.elemental]
        if elemental != sorted(elemental):
            continue
        cost = [(o._slot_drain(item.drain, item.polarity, slots[perm[i]]),
                 o._slot_drain(item.drain, item.polarity, item.polarity)) for i, item in enumerate(items)]
        for mask in range(1 << len(items)):
            used = sum(c[1] if mask >> i & 1 else c[0] for i, c in enumerate(cost))
            formas = sum(1 for i in range(len(items)) if mask >> i & 1 and cost[i][1] != cost[i][0])
            if used <= limit and (best is None or formas < best):
                best = formas
    return best


def test_forma_plan_moves_a_card_onto_a_native_slot_instead_of_a_forma():
    plan = o.forma_plan(["AP_ATTACK", None, None],
                        [I(0, "AP_DEFENSE", 10), I(1, "AP_ATTACK", 10), I(2, "AP_TACTIC", 10)], limit=25)
    assert plan["fits"] and plan["formas"] == 0 and plan["placement"][0] == 1


def test_forma_plan_keeps_elemental_order_and_fixed_cards():
    items = [I(0, "AP_DEFENSE", 16, elemental=True), I(1, "AP_ATTACK", 9), I(2, "AP_TACTIC", 11, elemental=True)]
    plan = o.forma_plan(["AP_TACTIC", None, "AP_DEFENSE"], items, limit=30)
    elemental = [plan["placement"].index(i) for i in (0, 2)]
    assert elemental == sorted(elemental)
    still = o.forma_plan(["AP_TACTIC", None, "AP_DEFENSE"], items, limit=30, allow_move=False)
    assert still["placement"] == [0, 1, 2] and still["moves"] == 0


def test_forma_plan_matches_brute_force_on_random_loadouts():
    import random
    rng = random.Random(15)
    polarities = ["AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", None]
    for _ in range(60):
        n = rng.randint(3, 6)
        slots = [rng.choice(polarities) for _ in range(n)]
        items = [I(i, rng.choice(polarities[:3]), rng.randint(4, 16), elemental=rng.random() < .3)
                 for i in range(rng.randint(2, n))]
        limit = rng.randint(20, 60)
        plan = o.forma_plan(slots, items, limit=limit)
        truth = _brute_force(slots, items, limit)
        if truth is None:
            assert not plan["fits"]
        else:
            assert plan["fits"] and plan["formas"] == truth


def test_forma_plan_stance_forma_counts_only_when_needed():
    items = [I(i, "AP_ATTACK", 14) for i in range(8)]
    # 8 x 7 = 56 matched; 60 + 10 capacity is enough without touching the stance slot.
    plan = o.forma_plan(["AP_ATTACK"] * 8, items, limit=70, extras=[[(0, 0, 0), (1, 0, -10)]])
    assert plan["extras"] == [0] and plan["formas"] == 0
    # Unpolarized slots: the stance Forma (+10 capacity) beats a ninth slot Forma.
    plan = o.forma_plan([None] * 8, items, limit=62, extras=[[(0, 0, 0), (1, 0, -10)]])
    assert plan["fits"]
    assert plan["formas"] == _forma_count_with_extra([None] * 8, items, 62, -10)


def _forma_count_with_extra(slots, items, limit, delta):
    plain = _brute_force(slots, items, limit)
    extra = _brute_force(slots, items, limit - delta)
    candidates = [x for x in (plain, None if extra is None else extra + 1) if x is not None]
    return min(candidates)


# ── Shapley ───────────────────────────────────────────────────────────────

def test_shapley_is_exact_for_an_additive_game_and_sums_to_the_total():
    import app

    weights = [3.0, 5.0, 7.0]
    values = [sum(w for i, w in enumerate(weights) if mask >> i & 1) for mask in range(8)]
    phi, pairs = app._shapley(values, 3)
    assert phi == pytest.approx(weights)
    assert all(abs(v) < 1e-12 for v in pairs.values())
    # A synergy term shows up as a positive interaction of exactly that pair.
    values = [v + (4.0 if mask & 0b011 == 0b011 else 0.0) for mask, v in enumerate(values)]
    phi, pairs = app._shapley(values, 3)
    assert sum(phi) == pytest.approx(values[-1] - values[0])
    assert pairs[(0, 1)] == pytest.approx(4.0) and abs(pairs[(0, 2)]) < 1e-12


def test_part_values_endpoint_multipliers_multiply_up_to_the_whole_build():
    import app

    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == "Lex Prime")
    mods = ["/Lotus/Upgrades/Mods/Pistol/WeaponDamageAmountMod", "/Lotus/Upgrades/Mods/Pistol/WeaponFireIterationsMod",
            "/Lotus/Upgrades/Mods/Pistol/WeaponCritChanceMod"]
    mods = [dict(path=p, rank=app.MANUAL_MODS_BY_PATH[p]["maxRank"], slot=i) for i, p in enumerate(mods)
            if p in app.MANUAL_MODS_BY_PATH]
    payload = dict(weapon=weapon["path"], mods=mods, enemy=app._BENCHMARK_ENEMY_PATH, damageModel="target",
                   level=60, steelPath=False, slotPolarities=[None] * 8)
    result = app.part_values_payload(payload)
    assert result["evaluations"] == 2 ** len(mods)
    if result["scale"] == "log":
        product = math.prod(row["multiplier"] for row in result["parts"])
        assert product == pytest.approx(result["fullValue"] / result["emptyValue"], rel=1e-9)


# ── native kill branches (Deadhead) ───────────────────────────────────────

def test_kill_branch_draws_are_native_and_identical_to_the_reference():
    pytest.importorskip("wfarsenal.wfcore")
    from wfarsenal import combat_replay, native_replay

    probe = combat_replay._KillProbe()
    branch = combat_replay._KillBranch(.25)
    assert native_replay.supported(None, dict(collect_timeline=False, weak_draw=probe,
                                              combat=dict(resolve=lambda *_: None)))
    # The Python draw sequence the native loop reproduces.
    copy = combat_replay._KillBranch(.25)
    draws = [copy(.4) for _ in range(6)]
    assert draws == [1.0 if (.25 + i * combat_replay._GOLDEN) % 1. < .4 else 0.0 for i in range(6)]
    assert branch.native_spec() == dict(probe=False, offset=.25, golden=combat_replay._GOLDEN)


# ── concurrent searches ───────────────────────────────────────────────────

def test_concurrent_searches_keep_call_order_and_context():
    import contextvars

    marker = contextvars.ContextVar("marker", default=None)
    token = marker.set("request")
    try:
        seen = []

        def call(i):
            time.sleep(.01 * (5 - i))
            seen.append(threading.current_thread().name)
            return (i, marker.get())

        results = loadout_search._concurrently([lambda i=i: call(i) for i in range(5)])
    finally:
        marker.reset(token)
    assert results == [(i, "request") for i in range(5)]
    with pytest.raises(ZeroDivisionError):
        loadout_search._concurrently([lambda: 1, lambda: 1 / 0])
