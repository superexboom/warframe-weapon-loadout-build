from __future__ import annotations

import json
import os
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


def active_build(root: Path = ROOT) -> str:
    return os.environ.get("WF_RIVEN_BUILD") or str(load_source_lock(root)["activeBuild"])


def export_dir(root: Path = ROOT, build: str | None = None) -> Path:
    return root / "data" / "export" / (build or active_build(root))


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
