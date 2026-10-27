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
