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
    "companion-projectile-sequences.json",
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
def test_scoring_dependency_bytes_control_analysis_fingerprint(monkeypatch, dependency):
    read_bytes = Path.read_bytes
    original = read_bytes(dependency)
    baseline = app._analysis_inputs_fingerprint()
    # A valid Python comment / JSON trailing whitespace changes only the
    # virtual read. No scoring source or mechanics data is written to disk.
    replacement = original + (b"\n# fingerprint regression\n" if dependency.suffix == ".py" else b"\n ")
    observed = []

    def replace_dependency_bytes(path):
        if path == dependency:
            observed.append(path)
            return replacement
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", replace_dependency_bytes)
    actual = app._analysis_inputs_fingerprint()
    assert observed, f"analysis fingerprint omitted dependency: {dependency}"
    assert actual != baseline, f"changed dependency did not invalidate analysis: {dependency}"


def test_arena_only_source_edits_reuse_identity_but_real_score_changes_invalidate(monkeypatch):
    import ast
    source_app = Path(app.__file__).resolve()
    source_parallel = Path(app.optimizer.__file__).with_name("parallel.py").resolve()
    read_bytes = Path.read_bytes
    original = {source_app: read_bytes(source_app), source_parallel: read_bytes(source_parallel)}
    baseline = app._analysis_inputs_fingerprint()
    tree = ast.parse(original[source_app].decode("utf-8-sig"))
    arena = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "arena_catalog_payload")
    score = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_manual_resolve_sim_context")
    lines = original[source_app].decode("utf-8-sig").splitlines(keepends=True)

    def inserted(node, statement):
        changed = list(lines)
        changed.insert(node.body[0].lineno - 1, "    " + statement + "\n")
        return "".join(changed).encode("utf-8")

    replacements = {source_app: inserted(arena, "arena_ui_label = 'only arena presentation'")}
    monkeypatch.setattr(Path, "read_bytes", lambda path: replacements.get(path.resolve(), read_bytes(path)))
    assert app._analysis_inputs_fingerprint() == baseline
    replacements[source_app] = inserted(score, "payload = dict(payload, headshotChance=1.0)")
    assert app._analysis_inputs_fingerprint() != baseline
    replacements.clear()
    replacements[source_parallel] = original[source_parallel].replace(b"self.workers <= 1", b"self.workers <= 2")
    assert replacements[source_parallel] != original[source_parallel]
    assert app._analysis_inputs_fingerprint() != baseline
    replacements.clear()
    replacements[source_app] = original[source_app] + b"\nUNREVIEWED_SCORE_GLOBAL = 1\n"
    assert app._analysis_inputs_fingerprint() != baseline
