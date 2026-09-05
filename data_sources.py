from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "data" / "source-lock.json"


def load_source_lock(root: Path = ROOT) -> dict[str, Any]:
    path = root / "data" / "source-lock.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not payload.get("activeBuild"):
        raise ValueError(f"invalid data source lock: {path}")
    return payload


def active_build(root: Path = ROOT, lock: dict[str, Any] | None = None) -> str:
    build = str((lock if lock is not None else load_source_lock(root))["activeBuild"])
    override = os.environ.get("WF_RIVEN_BUILD")
    if override and override != build:
        raise ValueError("WF_RIVEN_BUILD cannot mix exports with another snapshot; activate a complete snapshot")
    return validate_build(build)


def validate_build(build: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", build) or ".." in build:
        raise ValueError("build must be a single version label without path separators")
    return build


def dataset_root(root: Path = ROOT, lock: dict[str, Any] | None = None) -> Path:
    root = root.resolve()
    lock = lock if lock is not None else load_source_lock(root)
    snapshot = lock.get("snapshotRoot")
    if not snapshot:
        return root
    path = (root / str(snapshot)).resolve()
    snapshots = (root / "data" / "snapshots").resolve()
    if not path.is_relative_to(snapshots) or path == snapshots or not path.is_dir():
        raise ValueError("snapshotRoot must name an existing directory under data/snapshots")
    return path


def export_dir(root: Path = ROOT, build: str | None = None) -> Path:
    lock = load_source_lock(root)
    return dataset_root(root, lock) / "data" / "export" / validate_build(build or active_build(root, lock))


def resolve_source_path(template: str, *, root: Path = ROOT, build: str | None = None) -> Path:
    value = str(template).replace("{build}", build or active_build(root))
    return (root / value).resolve()


def provenance_path(path: str | Path, *, root: Path = ROOT) -> str:
    resolved = Path(path).resolve()
    for base in (root.resolve(), root.resolve().parent):
        try:
            return resolved.relative_to(base).as_posix()
        except ValueError:
            pass
    return resolved.name
