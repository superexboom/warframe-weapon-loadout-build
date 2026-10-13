"""The engine's shared compute pool and its scheduler.

One pool of worker processes serves every request in the process: the riven
analysis' beam layers and rankings, the build page's searches, MOD gains.
Requests no longer own workers; they hand jobs to the scheduler, which keeps
exactly ``workers`` jobs running and starts the next one by priority:

- 0: interactive (build page, manual simulation, MOD gains),
- 1: riven analysis,
- 2: background work.

A request's priority is the ``PRIORITY`` context variable of the thread that
submits; within one priority jobs run first-come first-served. Results come
back by job index, so an answer never depends on how many workers ran it or
what else was running (WFSim's evaluate_batch does the same).

The worker count and whether workers run below normal priority are the user's
setting (``configure``; the app's global settings panel). A change takes
effect for new jobs: running jobs finish on the old processes.

Worker processes are stateless: a job carries its whole argument tuple.
``WF_ANALYZER_SERIAL=1`` (or one worker) runs everything in the caller.
"""
from __future__ import annotations

import heapq
import itertools
import os
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextvars import ContextVar
from typing import Any, Callable

PRIORITY: ContextVar[int] = ContextVar("engine_priority", default=1)
INTERACTIVE, ANALYSIS, BACKGROUND = 0, 1, 2


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


def logical_core_count() -> int:
    return os.cpu_count() or 1


def default_workers() -> int:
    """Physical cores minus one (the parent keeps a core for orchestration),
    at most 7: workers plus parent stay within eight computations unless the
    user raises it in the settings."""
    return max(1, min(_physical_core_count() - 1, 7))


def _worker_init(slot_counter, pin: bool, low_priority: bool) -> None:
    """Pin to a distinct physical core (when the pool fits on them) and drop
    below normal priority, so other programs on the machine come first."""
    try:
        import psutil  # type: ignore

        proc = psutil.Process()
        if low_priority:
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
        if pin:
            with slot_counter.get_lock():
                slot = slot_counter.value
                slot_counter.value += 1
            # Windows SMT: logical 0..physical-1 are the first hyperthread of
            # each physical core, so slot k sits alone on core k.
            proc.cpu_affinity([slot % _physical_core_count()])
    except Exception:
        pass  # psutil missing or unsupported: unpinned, normal priority.


class _Scheduler:
    """Keeps ``workers`` jobs on the process pool, next one by priority.

    Only the dispatcher thread touches the pool: completion callbacks (which
    the pool runs on its own management thread) just record the result and
    wake the dispatcher. Calling back into a pool from its management thread
    could deadlock or rebuild a pool from inside the one that is breaking.
    A broken pool (a worker process died) fails the jobs it held and is
    replaced for later ones; a job is never retried.
    """

    def __init__(self) -> None:
        self._lock = threading.Condition(threading.RLock())
        self._queue: list = []
        self._order = itertools.count()
        self._running = 0
        self._executor: ProcessPoolExecutor | None = None
        self._dispatcher: threading.Thread | None = None
        self.workers = default_workers()
        self.low_priority = True
        env = os.environ.get("WF_ENGINE_WORKERS", "")
        if env.isdigit():
            self.workers = max(1, int(env))

    # ── settings ────────────────────────────────────────────────────────
    def configure(self, workers: int | None = None, low_priority: bool | None = None) -> None:
        with self._lock:
            changed = False
            if workers is not None:
                workers = max(1, min(int(workers), logical_core_count()))
                changed |= workers != self.workers
                self.workers = workers
            if low_priority is not None and bool(low_priority) != self.low_priority:
                self.low_priority = bool(low_priority)
                changed = True
            if changed and self._executor is not None:
                # Running jobs finish on the old processes; new ones start
                # on a pool built with the new setting.
                self._executor.shutdown(wait=False, cancel_futures=False)
                self._executor = None
            self._lock.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"workers": self.workers, "lowPriority": self.low_priority,
                    "defaultWorkers": default_workers(), "physicalCores": _physical_core_count(),
                    "logicalCores": logical_core_count(), "running": self._running, "queued": len(self._queue)}

    def serial(self) -> bool:
        return os.environ.get("WF_ANALYZER_SERIAL") == "1" or self.workers <= 1

    # ── jobs ────────────────────────────────────────────────────────────
    def _ensure(self) -> ProcessPoolExecutor:
        if self._executor is None:
            import multiprocessing

            pin = self.workers <= _physical_core_count()
            counter = multiprocessing.Value("i", 0)
            self._executor = ProcessPoolExecutor(max_workers=self.workers, initializer=_worker_init,
                                                 initargs=(counter, pin, self.low_priority))
        return self._executor

    def submit(self, fn: Callable, arg: Any, priority: int | None = None) -> Future:
        outer: Future = Future()
        with self._lock:
            level = PRIORITY.get() if priority is None else priority
            heapq.heappush(self._queue, (level, next(self._order), fn, arg, outer))
            if self._dispatcher is None or not self._dispatcher.is_alive():
                self._dispatcher = threading.Thread(target=self._dispatch, name="engine-scheduler", daemon=True)
                self._dispatcher.start()
            self._lock.notify_all()
        return outer

    def _dispatch(self) -> None:
        while True:
            with self._lock:
                while not (self._queue and self._running < self.workers):
                    if not self._queue and not self._running:
                        # Idle: let the thread end; the next submit starts one.
                        if not self._lock.wait(timeout=30.0) and not self._queue:
                            self._dispatcher = None
                            return
                    else:
                        self._lock.wait()
                _level, _n, fn, arg, outer = heapq.heappop(self._queue)
                if not outer.set_running_or_notify_cancel():
                    continue
                self._running += 1
                try:
                    executor = self._ensure()
                except Exception as exc:
                    self._running -= 1
                    outer.set_exception(exc)
                    continue
            try:
                inner = executor.submit(fn, arg)
            except Exception as exc:  # broken or shut-down pool: replace it
                with self._lock:
                    self._running -= 1
                    if self._executor is executor:
                        self._executor = None
                outer.set_exception(exc)
                continue
            inner.add_done_callback(lambda done, outer=outer, executor=executor: self._finish(outer, done, executor))

    def _finish(self, outer: Future, inner: Future, executor: ProcessPoolExecutor) -> None:
        # Runs on the pool's own thread: record and wake, never touch the pool.
        try:
            outer.set_result(inner.result())
        except BaseException as exc:  # the job's own exception, or the pool's
            if isinstance(exc, BrokenProcessPool):
                with self._lock:
                    if self._executor is executor:
                        self._executor = None
            outer.set_exception(exc)
        with self._lock:
            self._running -= 1
            self._lock.notify_all()

    def shutdown(self) -> None:
        with self._lock:
            for _level, _n, _fn, _arg, outer in self._queue:
                outer.cancel()
            self._queue.clear()
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None
            self._lock.notify_all()


SCHEDULER = _Scheduler()


class _PoolFacade:
    """``pool.submit(fn, arg)`` for the engine's existing call sites."""

    def submit(self, fn: Callable, arg: Any) -> Future:
        return SCHEDULER.submit(fn, arg)


def worker_count() -> int:
    """Number of parallel evaluation workers (1 = serial)."""
    return 1 if SCHEDULER.serial() else SCHEDULER.workers


def get_pool(context: dict[str, Any] | None = None) -> _PoolFacade | None:
    """The shared scheduler, or None when the engine runs serially."""
    return None if SCHEDULER.serial() else _PoolFacade()


def configure(workers: int | None = None, low_priority: bool | None = None) -> None:
    SCHEDULER.configure(workers, low_priority)


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
            future.cancel()  # queued jobs of a cancelled request never start
    return results


# ── shared job context ──────────────────────────────────────────────────
# A batch's jobs share one context (weapon record, scenario, passives,
# target), ~33 KB pickled. Sending it inside every job cost more than the
# replays it carried; a SharedContext is pickled once in the parent and each
# worker decodes a given one once, then reuses the same object -- which also
# lets the worker's identity-keyed caches hit across the batch.
_SHARED: "OrderedDict[bytes, dict]" = None  # type: ignore[assignment]
_SHARED_MAX = 16


class SharedContext(dict):
    """A job context that pickles as (digest, frozen bytes)."""

    __slots__ = ("_wire",)

    def __reduce__(self):
        wire = getattr(self, "_wire", None)
        if wire is None:
            import hashlib
            import pickle

            blob = pickle.dumps(dict(self), protocol=pickle.HIGHEST_PROTOCOL)
            wire = (hashlib.blake2b(blob, digest_size=16).digest(), blob)
            self._wire = wire
        return (_shared_context, wire)


def _shared_context(key: bytes, blob: bytes) -> dict:
    global _SHARED
    from collections import OrderedDict
    import pickle

    if _SHARED is None:
        _SHARED = OrderedDict()
    ctx = _SHARED.get(key)
    if ctx is None:
        ctx = pickle.loads(blob)
        _SHARED[key] = ctx
        while len(_SHARED) > _SHARED_MAX:
            _SHARED.popitem(last=False)
    else:
        _SHARED.move_to_end(key)
    return ctx


def shared(context: dict) -> SharedContext:
    """``context`` for a batch of pool jobs; it must not change afterwards."""
    return SharedContext(context)


def shutdown_pool() -> None:
    """Tear the pool down (tests / process exit)."""
    SCHEDULER.shutdown()


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
