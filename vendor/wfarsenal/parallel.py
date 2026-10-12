"""Parallel beam evaluation for the riven analyzer.

The beam layer expansion evaluates hundreds of independent card
combinations per layer (fast: ~384, deep: ~1400), each running the full
mod pipeline + windowed scoring (~10-100ms). On an 8-physical-core host
that is a several-fold wall-clock win.

Design:
- A module-level persistent ProcessPoolExecutor (created lazily on first
  use). The per-search constant context (weapon / scenario / metric /
  passives / limits / target) travels ONCE through the initializer and
  lives in each worker; job payloads carry only the card combination.
- Workers score ONLY: the parent re-evaluates the surviving beam rows
  and the incumbent after each layer to attach full stats (deterministic
  pure function, ~15 sequential evals per layer).
- Worker processes pin to DISTINCT PHYSICAL CORES (Windows SMT: logical
  0..N-1 are the first hyperthreads). Two workers on sibling
  hyperthreads of one physical core fight for the same execution units —
  the classic "running on adjacent threads" misconfiguration the user
  observed. Affinity is best-effort: unsupported platforms run unpinned.
- WF_ANALYZER_SERIAL=1 forces the serial path (parity testing).
"""
from __future__ import annotations

import os
from typing import Any

from concurrent.futures import ProcessPoolExecutor

_POOL: ProcessPoolExecutor | None = None
_POOL_WORKERS = 0
_WORKER_CONTEXT: dict[str, Any] | None = None


def _physical_core_count() -> int:
    count = os.cpu_count() or 1
    try:
        import psutil  # type: ignore

        physical = psutil.cpu_count(logical=False)
        if isinstance(physical, int) and physical > 0:
            return physical
    except Exception:
        pass
    # Heuristic fallback: AMD Zen / modern Intel expose all first
    # hyperthreads before the siblings (logical 0..n-1 = physical cores).
    return max(count // 2, 1)


def _pin_worker(seed: int, physical: int) -> None:
    """Pin this worker process to one physical core (best effort).

    Windows SMT convention: logical CPUs 0..physical-1 are the first
    hyperthread of each physical core. seed % physical picks a stable
    slot so distinct pids land on distinct physical cores; collisions
    merely degrade to two workers sharing a core — never to the
    SMT-sibling misconfiguration.
    """
    try:
        import psutil  # type: ignore

        proc = psutil.Process()
        proc.cpu_affinity([seed % physical])
    except Exception:
        # psutil missing or affinity unsupported: run unpinned.
        pass


def _worker_init(context: dict[str, Any] | None = None) -> None:
    """Per-worker initializer: capture the shared scoring context and pin
    this process to a distinct physical core.

    Windows spawn re-imports this module per worker, so a module counter
    would restart at 0 in every process — pid-modulo is the practical
    distinct-slot source.
    """
    global _POOL_WORKERS, _WORKER_CONTEXT
    _POOL_WORKERS = _physical_core_count()
    _WORKER_CONTEXT = context
    _pin_worker(os.getpid(), _POOL_WORKERS)


def worker_count() -> int:
    """Number of parallel evaluation workers (physical cores, 1 = serial)."""
    if os.environ.get("WF_ANALYZER_SERIAL") == "1":
        return 1
    # Interactive analysis and background cache work share the same user
    # machine. Keep one global ceiling so a live request cannot fan out across
    # every physical core behind the cache worker limit.
    # The parent also replays surviving candidates. Reserve its CPU slot so
    # workers plus parent stay within the user's total eight-computation cap.
    return min(_physical_core_count(), 7)


def get_pool(context: dict[str, Any] | None = None) -> ProcessPoolExecutor | None:
    """The persistent evaluation pool, or None when serial (1 core).

    Workers are STATELESS: each job carries its full argument tuple
    (weapon/cards/riven/scenario/metric/passives/limits/target), so the
    pool survives context changes (KPM->DPS metric switches, target level
    escalation) without worker respawns. The initializer only pins
    physical cores.
    """
    global _POOL
    if os.environ.get("WF_ANALYZER_SERIAL") == "1":
        return None
    workers = worker_count()
    if workers <= 1:
        return None
    if _POOL is None:
        _POOL = ProcessPoolExecutor(
            max_workers=workers,
            initializer=_worker_init,
            initargs=(context,),
        )
    return _POOL


def map_jobs(fn, jobs: list) -> list:
    """Run ``fn`` over ``jobs`` on the pool (serially without one), in order.

    Each entry is the job's value or the exception it raised. A request that a
    newer one superseded stops between results and drops the rest.
    """
    from .search_session import check_cancelled

    pool = get_pool() if len(jobs) > 1 else None
    results: list = []
    if pool is None:
        for job in jobs:
            check_cancelled()
            try:
                results.append(fn(job))
            except Exception as exc:  # reported per job, like a future's
                results.append(exc)
        return results
    futures = [pool.submit(fn, job) for job in jobs]
    try:
        for future in futures:
            check_cancelled()
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(exc)
    finally:
        for future in futures:
            future.cancel()  # no-op once finished
    return results


def _gain_replay_job(args: tuple) -> float:
    """One MOD-gain measurement: prepare the loadout's combat and replay the
    benchmark window. The parent resolves the stats (it holds the app's
    records); the replay -- most of the cost -- runs here."""
    from .combat_replay import replay
    from .manual_combat import prepare

    prepare_args, prepare_kwargs, stats, enemy, replay_kwargs = args
    combat = prepare(*prepare_args, **prepare_kwargs)
    return replay(stats, enemy, combat=combat, trigger_sources=combat["trigger_sources"],
                  **replay_kwargs)["killsPerMinute"]


def shutdown_pool() -> None:
    """Tear the pool down (tests / process exit)."""
    global _POOL
    if _POOL is not None:
        _POOL.shutdown(wait=False, cancel_futures=True)
        _POOL = None


def _score_job(args: tuple) -> float | None:
    """Score one card combination; return the score or None if invalid.

    args = (cards, riven, context) where context is the shared dict
    (weapon/scenario/metric/passives/limits/target); passing it per job
    keeps workers stateless across context switches (no respawn cost).
    Legacy 9-tuples are still accepted.
    """
    from wfarsenal import optimizer as _opt

    if len(args) == 3 and isinstance(args[2], dict) and "weapon" in args[2]:
        cards, riven, ctx = args
        evaluated = _opt._evaluate(
            ctx["weapon"],
            cards,
            riven,
            scenario=ctx["scenario"],
            metric=ctx["metric"],
            passives=ctx["passives"],
            slot_limit=ctx.get("slot_limit", 8),
            capacity_limit=ctx["capacity_limit"],
            target_context=ctx["target_context"],
            fixed_riven_index=ctx.get("fixed_riven_index"),
            reorder_elements=ctx.get("reorder_elements", True),
        )
        return None if evaluated is None else evaluated.score
    (
        weapon,
        cards,
        riven,
        scenario,
        metric,
        passives,
        slot_limit,
        capacity_limit,
        target_context,
    ) = args
    evaluated = _opt._evaluate(
        weapon,
        cards,
        riven,
        scenario=scenario,
        metric=metric,
        passives=passives,
        slot_limit=slot_limit,
        capacity_limit=capacity_limit,
        target_context=target_context,
    )
    return None if evaluated is None else evaluated.score


def _best_fixed_job(args: tuple) -> float | None:
    """Worker-side _best_fixed: full subset search for one riven line.

    args = (base_cards, riven, keep_cap, context); context is the shared
    dict (weapon/scenario/metric/passives/capacity/target). Returns the
    best score or None when nothing fits.
    """
    from wfarsenal import optimizer as _opt

    base_cards, riven, keep_cap, ctx = args
    try:
        result = _opt._best_fixed(
            ctx["weapon"],
            base_cards,
            riven,
            scenario=ctx["scenario"],
            metric=ctx["metric"],
            passives=ctx["passives"],
            capacity_limit=ctx["capacity_limit"],
            target_context=ctx["target_context"],
            max_keep_cap=keep_cap,
        )
        return result.score
    except Exception:
        return None
