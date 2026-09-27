"""Regression for the internal event-KPM automatic-build target."""
from __future__ import annotations

import math


def test_build_payload_accepts_internal_kpm_target_without_catalog_metric_pollution(monkeypatch):
    monkeypatch.setenv("WF_ANALYZER_SERIAL", "1")
    import app

    weapon = next(row for row in app.EXPORTS["weapons"] if row.get("nameEn") == "Braton Prime")
    result = app.build_weapon_payload({
        "weapon": weapon["path"],
        "fireMode": 0,
        "metric": "killsPerMinute",
        "profile": "fast",
        "slotCount": 1,
        "minFill": 0,
        "maxFill": 0,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 160,
        "steelPath": True,
    })

    assert result["scoreMetric"] == "killsPerMinute"
    assert math.isfinite(float(result["build"]["objectiveScore"]))
    assert all(row["id"] != "killsPerMinute" for row in app.BUILD_METRICS["gun"])
