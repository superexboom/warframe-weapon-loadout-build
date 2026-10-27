"""The bake must load the selected Bot bundle and retain its fixed preset."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/bake-analysis-statics.py"


def fake_bundle(tmp_path):
    bundle = tmp_path / "bundle"
    src = bundle / "src"
    src.mkdir(parents=True)
    (src / "app.py").write_text("""
CATALOG = {'weapons': []}
ANALYSIS_STATICS_CACHE_VERSION = 901
def _analysis_inputs_fingerprint():
    return 'selected-bot-runtime'
""", encoding="utf-8")
    (src / "bot_riven.py").write_text("import app\n", encoding="utf-8")
    engine = src / "wfarsenal"
    engine.mkdir()
    (engine / "__init__.py").write_text("", encoding="utf-8")
    (engine / "parallel.py").write_text("def default_workers(): return 1\n", encoding="utf-8")
    return bundle


def test_bot_dry_run_uses_bundle_identity_not_portable(tmp_path):
    bundle = fake_bundle(tmp_path)
    report = tmp_path / "report.json"
    result = subprocess.run([sys.executable, str(SCRIPT), "--bot-bundle", str(bundle),
                             "--profile", "fast", "--dry-run", "--report", str(report),
                             "--shard-dir", str(tmp_path / "shards")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    payload = json.loads(report.read_text())
    assert payload["inputs"] == "selected-bot-runtime"
    assert payload["cacheVersion"] == 901
    assert payload["positiveCounts"] == [3, 2]
    assert payload["gpuEnabled"] is False
    assert Path(payload["botBundle"]) == bundle


@pytest.mark.parametrize("options", [["--profile", "standard"], ["--profile", "fast", "--fire-modes"]])
def test_bot_does_not_silently_bake_a_different_online_preset(tmp_path, options):
    bundle = fake_bundle(tmp_path)
    result = subprocess.run([sys.executable, str(SCRIPT), "--bot-bundle", str(bundle),
                             "--dry-run", *options], capture_output=True, text=True)
    assert result.returncode == 2
    assert "Bot baking requires" in result.stderr


def test_primary_kitgun_bake_trigger_uses_pistol_riven_family(monkeypatch, tmp_path):
    import importlib.util
    import app
    spec = importlib.util.spec_from_file_location("kitgun_bake", SCRIPT)
    bake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bake)
    path = "/Lotus/Weapons/SolarisUnited/Primary/LotusModularPrimary"
    captured = []
    monkeypatch.setattr(app, "ANALYSIS_STATICS_CACHE", {})
    from types import SimpleNamespace
    monkeypatch.setattr(app, "_disable_analysis_statics_persistence", lambda: SimpleNamespace(enabled=False))
    def analyze(payload):
        captured.append(payload)
        app.ANALYSIS_STATICS_CACHE["test"] = {"valid": True}
        return {}
    monkeypatch.setattr(app, "analyze_payload", analyze)
    outcomes = bake._shard_worker((path, 0, [("fast", str(tmp_path / "shard.json"))], (3, 2)))
    assert outcomes[0]["ok"]
    assert len(captured) == 2
    for payload in captured:
        count = len(payload["stats"])
        for stat in payload["stats"]:
            base = app.RIVEN_BASE_VALUES["pistol"][stat["code"]]
            _, low, high = app.optimizer.riven_stat_window(base, payload["disposition"], count, 0)
            assert low - .11 <= stat["value"] <= high + .11


def test_modern_bot_requires_its_owned_complete_bake(tmp_path):
    bundle = fake_bundle(tmp_path)
    (bundle / "src/bot_riven.py").write_text("import app\nBAKE_PROFILE = 'deep'\n", encoding="utf-8")
    result = subprocess.run([sys.executable, str(SCRIPT), "--bot-bundle", str(bundle),
                             "--profile", "fast", "--dry-run"], capture_output=True, text=True)
    assert result.returncode == 2
    assert "owned deep bake" in result.stderr
