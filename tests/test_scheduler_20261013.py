"""Shared compute pool and the global compute setting (2026-10-13).

- One scheduler serves every request; it keeps ``workers`` jobs running and
  starts the next by priority (build page before analysis), first come first
  served within a priority.
- The worker count and low priority are the user's setting, validated and
  saved by /api/settings; a change applies to new jobs.
"""
import json
import time

import pytest

import app
from wfarsenal import parallel


def test_interactive_jobs_jump_the_queue():
    scheduler = parallel._Scheduler()
    scheduler.configure(workers=1, low_priority=False)
    try:
        order = []
        blocker = scheduler.submit(time.sleep, 1.0, priority=parallel.ANALYSIS)
        queued = [scheduler.submit(abs, -n, priority=level)
                  for n, level in ((1, parallel.ANALYSIS), (2, parallel.ANALYSIS), (3, parallel.INTERACTIVE))]
        for future in queued:
            future.add_done_callback(lambda done: order.append(done.result()))
        blocker.result(timeout=60)
        assert [f.result(timeout=60) for f in queued] == [1, 2, 3]
        assert order == [3, 1, 2]
    finally:
        scheduler.shutdown()


def test_a_new_worker_count_applies_to_new_jobs():
    scheduler = parallel._Scheduler()
    scheduler.configure(workers=2, low_priority=True)
    try:
        assert [scheduler.submit(abs, -n).result(timeout=60) for n in range(4)] == [0, 1, 2, 3]
        scheduler.configure(workers=1)
        assert scheduler.snapshot()["workers"] == 1
        assert scheduler.submit(abs, -7).result(timeout=60) == 7
    finally:
        scheduler.shutdown()


def test_a_dead_worker_fails_its_jobs_and_the_pool_recovers():
    """A worker process that dies breaks its pool: its jobs report
    BrokenProcessPool promptly (they used to wait forever) and later jobs run
    on a fresh pool."""
    import os
    from concurrent.futures.process import BrokenProcessPool

    scheduler = parallel._Scheduler()
    scheduler.configure(workers=2, low_priority=False)
    try:
        crashed = scheduler.submit(os._exit, 3)
        with pytest.raises(BrokenProcessPool):
            crashed.result(timeout=60)
        assert scheduler.submit(abs, -5).result(timeout=60) == 5
        assert scheduler.snapshot()["running"] == 0
    finally:
        scheduler.shutdown()


def test_settings_are_validated_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ENGINE_SETTINGS_PATH", tmp_path / "engine-settings.json")
    before = parallel.SCHEDULER.snapshot()
    try:
        result = app.update_engine_settings({"compute": {"workers": 2, "lowPriority": False}})
        assert result["compute"]["workers"] == 2 and result["compute"]["lowPriority"] is False
        saved = json.loads((tmp_path / "engine-settings.json").read_text(encoding="utf-8"))
        assert saved == {"compute": {"workers": 2, "lowPriority": False}}
        for bad in ({"compute": {"workers": 0}}, {"compute": {"workers": True}}, {"compute": {"lowPriority": 1}},
                    {"compute": {"workers": parallel.logical_core_count() + 1}}, {}):
            with pytest.raises(ValueError):
                app.update_engine_settings(bad)
        snapshot = app.engine_settings()["compute"]
        assert snapshot["defaultWorkers"] == parallel.default_workers()
        assert snapshot["logicalCores"] >= snapshot["physicalCores"] >= 1
    finally:
        parallel.configure(before["workers"], before["lowPriority"])
