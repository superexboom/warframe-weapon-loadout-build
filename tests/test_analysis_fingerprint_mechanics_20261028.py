"""Scoring adapters and mechanics records must invalidate baked analysis."""
from pathlib import Path

import pytest
import app


SCORING_ADAPTERS = (
    "native_replay.py",
    "mods_native.py",
    "status_native.py",
    "companion.py",
    "sentinel.py",
)
MECHANICS_RECORDS = (
    "sentinels.json",
    "player-only-conditions.json",
    "burst-profiles.json",
    "charge-profiles.json",
    "shell-reload-profiles.json",
    "reload-after-shot.json",
    "kill-charge-profiles.json",
    "infinite-conditions.json",
)
DEPENDENCIES = tuple(
    Path(app.optimizer.__file__).with_name(name) for name in SCORING_ADAPTERS
) + tuple(app.ROOT / "data" / "mechanics" / name for name in MECHANICS_RECORDS)


@pytest.mark.parametrize("dependency", DEPENDENCIES, ids=lambda path: path.name)
@pytest.mark.parametrize("changed", (False, True), ids=("same-bytes", "changed-bytes"))
def test_scoring_dependency_bytes_control_analysis_fingerprint(monkeypatch, dependency, changed):
    read_bytes = Path.read_bytes
    original = read_bytes(dependency)
    baseline = app._analysis_inputs_fingerprint()
    # A valid Python comment / JSON trailing whitespace changes only the
    # virtual read. No scoring source or mechanics data is written to disk.
    replacement = original
    if changed:
        replacement += b"\n# fingerprint regression\n" if dependency.suffix == ".py" else b"\n "
    observed = []

    def replace_dependency_bytes(path):
        if path == dependency:
            observed.append(path)
            return replacement
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", replace_dependency_bytes)
    actual = app._analysis_inputs_fingerprint()
    assert observed, f"analysis fingerprint omitted dependency: {dependency}"
    if changed:
        assert actual != baseline, f"changed dependency did not invalidate analysis: {dependency}"
    else:
        assert actual == baseline, f"identical dependency bytes changed analysis identity: {dependency}"
