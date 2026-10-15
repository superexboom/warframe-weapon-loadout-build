"""Automatic weapon-Arcane and Incarnon-route choice for the build page.

Both are a discrete choice ``c`` on top of the MOD search ``b``: maximise
``f(c, b)``. A full MOD search per choice costs ``|C|`` searches (an Incarnon
weapon has 18 or 81 routes). Instead:

1. **screen** -- ``f(c, b0)`` for every choice on the incumbent build ``b0``:
   one replay each, all of them in parallel;
2. **refine** -- a full MOD search for a short list of choices, seeded with the
   incumbent so that it never ends below the screen;
3. **re-screen** every choice on the refined winner and refine any that beats
   it. Each step can only raise the score (block-coordinate ascent over the
   choice and the build).

Routes also need *diversity*: an evolution that changes the weapon (a
different Incarnon attack) can screen far below the default on a build made
for the default, and still win once the MODs follow it. Every branch of
every tier therefore sends its best-screened route to the refine stage, and
routes whose screens are identical on two different builds (their branches
differ only in effects the engine does not model) are searched once.

Measured 2026-10-14 (standard profile): screening every compatible Arcane and
refining the best two found the per-Arcane exhaustive optimum on 14 weapons
under both trigger policies; branch representatives plus the top three
routes (6-9 searches) found the best route on 8 Incarnon weapons, where the
default route left 2%-98% on the table.
"""
from __future__ import annotations

import contextvars
import itertools
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

EPS = 1e-9
# Independent searches (route scouts, finals, Arcane refines) CAN run at once
# (WF_CONCURRENT_SEARCHES > 1): results are taken in call order and the caches
# they share are keyed by content. Off by default: the searches of one request
# share its interactive time budget, so running them together can cut a search
# short where it would have finished alone (seen 2026-10-16 on a Burston
# re-search), and the measured gain was only 2-10%.
CONCURRENT_SEARCHES = max(1, int(os.environ.get("WF_CONCURRENT_SEARCHES", "1") or 1))


def _concurrently(calls: Sequence[Callable[[], Any]]) -> list[Any]:
    """``[call() for call in calls]``, run on up to CONCURRENT_SEARCHES threads.

    Context variables (search session, cancellation, pool priority) carry
    over to each thread; the first exception is re-raised in call order.
    """
    if len(calls) <= 1 or CONCURRENT_SEARCHES <= 1:
        return [call() for call in calls]
    with ThreadPoolExecutor(max_workers=min(len(calls), CONCURRENT_SEARCHES)) as pool:
        futures = [pool.submit(contextvars.copy_context().run, call) for call in calls]
        return [future.result() for future in futures]


@dataclass
class Choice:
    """One option: its request-level identity and the passives it implies."""

    key: str
    data: Any
    passives: Any


@dataclass
class Outcome:
    evaluation: Any
    choice: Choice | None
    rows: list[dict[str, Any]] = field(default_factory=list)
    searches: int = 0
    seconds: float = 0.0


def screen_scores(
    weapon: Mapping[str, Any],
    cards: Sequence[Any],
    riven: Any,
    passives_list: Sequence[Any],
    *,
    scenario: Any,
    metric: str,
    capacity_limit: int,
    slot_limit: int,
    target_context: Mapping[str, Any] | None,
) -> list[float | None]:
    """``_evaluate(cards).score`` under each passives card, on the pool."""
    from . import optimizer, parallel

    wire = scenario if isinstance(scenario.conditional_stacks, dict) else replace(
        scenario, conditional_stacks=dict(scenario.conditional_stacks))
    jobs = []
    for passives in passives_list:
        ctx = parallel.shared(dict(weapon=weapon, scenario=wire, metric=metric, passives=passives,
                                   slot_limit=slot_limit, capacity_limit=capacity_limit,
                                   target_context=target_context))
        jobs.append((tuple(cards), riven, ctx))
    if parallel.get_pool() is None:
        results = []
        for cards_, riven_, ctx in jobs:
            evaluated = optimizer._evaluate(weapon, cards_, riven_, scenario=scenario, metric=metric,
                                            passives=ctx["passives"], slot_limit=slot_limit,
                                            capacity_limit=capacity_limit, target_context=target_context)
            results.append(None if evaluated is None else evaluated.score)
        return results
    return [value if isinstance(value, (int, float)) else None
            for value in parallel.map_jobs(parallel._score_job, jobs)]


def pick_arcane(
    choices: Sequence[Choice],
    base: Any,
    *,
    screen: Callable[[Sequence[Any], Sequence[Any]], list[float | None]],
    search: Callable[[Any, Sequence[Any]], Any],
    refine: int = 2,
) -> Outcome:
    """The best weapon Arcane for the build ``base`` was searched without one.

    ``refine`` = 2: on 14 weapons under both trigger policies the per-Arcane
    optimum was always among the two best screens.
    """
    started = time.perf_counter()
    outcome = Outcome(evaluation=base, choice=None)
    if not choices:
        return outcome
    first = screen(base.cards, [c.passives for c in choices])
    rows = {c.key: dict(key=c.key, screen=s) for c, s in zip(choices, first)}
    ranked = sorted((i for i, s in enumerate(first) if s is not None and s > base.score + EPS),
                    key=lambda i: (-first[i], i))
    refined: set[int] = set()

    def take(index: int, found: Any) -> None:
        outcome.searches += 1
        refined.add(index)
        rows[choices[index].key]["refined"] = found.score
        if found.score > outcome.evaluation.score + EPS:
            outcome.evaluation, outcome.choice = found, choices[index]

    def run(index: int, seed: Sequence[Any]) -> None:
        take(index, search(choices[index].passives, seed))

    first_refines = ranked[:refine]
    for index, found in zip(first_refines, _concurrently(
            [lambda i=i: search(choices[i].passives, base.cards) for i in first_refines])):
        take(index, found)
    # Another Arcane may beat the winner on the winner's own build.
    for _round in range(2):
        if outcome.choice is None:
            break
        again = screen(outcome.evaluation.cards, [c.passives for c in choices])
        challengers = sorted((i for i, s in enumerate(again)
                              if i not in refined and s is not None and s > outcome.evaluation.score + EPS),
                             key=lambda i: (-again[i], i))
        if not challengers:
            break
        run(challengers[0], outcome.evaluation.cards)
    outcome.rows = sorted(rows.values(), key=lambda r: -(r.get("refined") or r["screen"] or 0.0))
    outcome.seconds = time.perf_counter() - started
    return outcome


def route_choices(weapon: Mapping[str, Any], tier_number: Callable[[Any], int | None]) -> list[dict[str, str]]:
    """Every full Incarnon route (one branch per selectable tier)."""
    tiers = []
    for row in (weapon.get("incarnon") or {}).get("tiers") or ():
        if not isinstance(row, Mapping):
            continue
        tier = tier_number(row.get("tier"))
        branches = [b for b in (row.get("branches") or ()) if isinstance(b, Mapping)]
        if tier in (2, 3, 4, 5) and (row.get("selectable") is True or len(branches) > 1):
            tiers.append([(f"tier{tier}", str(b.get("id") or b.get("path") or "")) for b in branches])
    return [dict(combo) for combo in itertools.product(*tiers)] if tiers else []


def pick_route(
    choices: Sequence[Choice],
    default_key: str | None,
    base: Any,
    *,
    screen: Callable[[Sequence[Any], Sequence[Any]], list[float | None]],
    search_fast: Callable[[Any, Sequence[Any]], Any],
    search_final: Callable[[Any, Sequence[Any]], Any],
    shortlist: int = 3,
    finalists: int = 2,
    final_margin: float = 0.03,
) -> Outcome:
    """The best Incarnon route; ``base`` was searched on ``default_key``.

    ``base`` is a level-1 (scout) result: the default route competes in the
    final like every other route. A second finalist is searched only when its
    scout score is within ``final_margin`` of the best one.
    """
    started = time.perf_counter()
    outcome = Outcome(evaluation=base, choice=next((c for c in choices if c.key == default_key), None))
    if len(choices) < 2:
        return outcome
    passives = [c.passives for c in choices]
    on_base = screen(base.cards, passives)
    on_bare = screen((), passives)
    # Routes that screen identically on two different builds are searched once.
    classes: dict[tuple, list[int]] = {}
    for index, (a, b) in enumerate(zip(on_base, on_bare)):
        if a is None:
            continue
        classes.setdefault((round(a, 9), None if b is None else round(b, 9)), []).append(index)
    representatives = []
    members_of: dict[int, list[int]] = {}
    rows: dict[str, dict[str, Any]] = {}
    for members in classes.values():
        preferred = next((i for i in members if choices[i].key == default_key), members[0])
        representatives.append(preferred)
        members_of[preferred] = members
        rows[choices[preferred].key] = dict(key=choices[preferred].key, route=choices[preferred].data,
                                            screen=on_base[preferred], equivalent=len(members))
    representatives.sort()
    default_index = next((i for i, c in enumerate(choices) if c.key == default_key), None)
    if default_index is not None and default_key not in rows:
        rows[default_key] = dict(key=default_key, route=choices[default_index].data,
                                 screen=on_base[default_index], equivalent=1)
    # Diversity: every branch's best-screened route, plus the overall best.
    picks: list[int] = []
    branches = sorted({(tier, value) for i in representatives for tier, value in choices[i].data.items()})
    for tier, value in branches:
        holders = [i for i in representatives if choices[i].data.get(tier) == value]
        if holders:
            picks.append(max(holders, key=lambda i: (on_base[i], -i)))
    picks.extend(sorted(representatives, key=lambda i: (-on_base[i], i))[:shortlist])
    picks = [i for i in dict.fromkeys(picks) if i != default_index]
    # Level 1: a cheap search per pick; level 2: the full search for the best few.
    first: dict[int, Any] = {}
    if default_index is not None:
        first[default_index] = base
        rows[default_key]["fast"] = base.score
    for index, found in zip(picks, _concurrently(
            [lambda i=i: search_fast(choices[i].passives, base.cards) for i in picks])):
        first[index] = found
        outcome.searches += 1
        rows[choices[index].key]["fast"] = found.score
    # Equivalence was read off two builds; check it on each scouted build too.
    # A member that screens differently there is not equivalent: scout it.
    for index in list(first):
        members = [m for m in members_of.get(index, ()) if m != index]
        if not members:
            continue
        again = screen(first[index].cards, [choices[m].passives for m in [index, *members]])
        for member, value in zip(members, again[1:]):
            if value is None or again[0] is None or round(value, 9) == round(again[0], 9):
                continue
            first[member] = search_fast(choices[member].passives, base.cards)
            outcome.searches += 1
            representatives.append(member)
            rows[choices[member].key] = dict(key=choices[member].key, route=choices[member].data,
                                             screen=on_base[member], equivalent=1, fast=first[member].score)
    ranked_first = sorted(first, key=lambda i: (-first[i].score, i))
    top_scout = first[ranked_first[0]].score
    finals = [i for i in ranked_first[:finalists] if first[i].score >= top_scout * (1.0 - final_margin)]
    # The default route always gets the full search: switching the option on
    # can then never end below the result without it.
    if default_index is not None and default_index not in finals:
        finals.append(default_index)
    for index in first:
        if first[index].score > outcome.evaluation.score + EPS:
            outcome.evaluation, outcome.choice = first[index], choices[index]
    searched: set[int] = set()

    def take(index: int, found: Any) -> None:
        outcome.searches += 1
        searched.add(index)
        rows[choices[index].key]["refined"] = found.score
        if found.score > outcome.evaluation.score + EPS:
            outcome.evaluation, outcome.choice = found, choices[index]

    def run(index: int, seed: Sequence[Any]) -> None:
        take(index, search_final(choices[index].passives, seed))

    if search_fast is search_final:
        # One profile: the level-1 searches are the final ones.
        for index, found in first.items():
            searched.add(index)
            rows[choices[index].key]["refined"] = found.score
            if found.score > outcome.evaluation.score + EPS:
                outcome.evaluation, outcome.choice = found, choices[index]
    else:
        # Unseeded for the default route: exactly the search the option
        # replaces, so its result is a floor.
        seeds = [None if index == default_index else first[index].cards for index in finals]
        for index, found in zip(finals, _concurrently(
                [lambda i=i, seed=seed: search_final(choices[i].passives, seed) for i, seed in zip(finals, seeds)])):
            take(index, found)
    for _round in range(2):
        again = screen(outcome.evaluation.cards, [choices[i].passives for i in representatives])
        challengers = sorted((i for i, s in zip(representatives, again)
                              if i not in searched and s is not None and s > outcome.evaluation.score + EPS),
                             key=lambda i: (-again[representatives.index(i)], i))
        if not challengers:
            break
        run(challengers[0], outcome.evaluation.cards)
    outcome.rows = sorted(rows.values(), key=lambda r: -(r.get("refined") or r.get("fast") or r["screen"] or 0.0))
    outcome.seconds = time.perf_counter() - started
    return outcome


def pick_route_fixed(choices: Sequence[Choice], default_key: str | None, cards: Sequence[Any], base_score: float,
                     *, screen: Callable[[Sequence[Any], Sequence[Any]], list[float | None]]) -> tuple[Choice | None, list]:
    """Equipped MODs: the route is the only choice, so the screen is exact."""
    scores = screen(cards, [c.passives for c in choices])
    best = next((c for c in choices if c.key == default_key), None)
    best_score = base_score
    for choice, score in zip(choices, scores):
        if score is not None and score > best_score + EPS:
            best, best_score = choice, score
    rows = sorted((dict(key=c.key, route=c.data, screen=s) for c, s in zip(choices, scores)),
                  key=lambda r: -(r["screen"] or 0.0))
    return best, rows
