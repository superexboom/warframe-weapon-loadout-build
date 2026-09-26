"""Read the Packages.bin dump and resolve type-object inheritance.

The dump produced by ``Warframe-Exporter-CLI --dump-pkgs`` mirrors the game's
internal path layout, one JSON file per type object. Each object only carries the
attributes it overrides; the rest live further up the inheritance chain. Stats for
a single weapon are therefore spread across several files -- Excalibur's health and
shields sit on ``/Lotus/Powersuits/Excalibur/Excalibur`` while its armour sits on
``/Lotus/Powersuits/Excalibur/ExcaliburBaseSuit``.

This module flattens that: :meth:`PackageIndex.resolve` walks an object's ancestry
and merges attributes child-first, so the most derived value wins.
"""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


class PackageError(Exception):
    """Raised when the dump is missing or structurally unusable."""


@dataclass
class PackageIndex:
    """Lazily-loaded, path-addressable view over a Packages.bin dump.

    Args:
        root: Directory that ``--dump-pkgs`` wrote to; contains ``Lotus/``, ``EE/``.
        parents: ``{path: parent path}`` recovered from the raw Packages.bin by
            :mod:`wfarsenal.parenttable`. The dump itself omits parent references, so
            without this the index can only see each object's own overrides.
    """

    root: Path
    parents: dict[str, str] = field(default_factory=dict)
    _cache: dict[str, dict[str, Any] | None] = field(default_factory=dict, repr=False)
    _resolved: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        if not self.root.is_dir():
            raise PackageError(f"dump root not found: {self.root}")

    # -- raw access ----------------------------------------------------------------

    def _path_to_file(self, path: str) -> Path:
        return self.root / (path.lstrip("/") + ".json")

    def get(self, path: str) -> dict[str, Any] | None:
        """Return one object's own attributes, or None if it has no dumped data.

        Objects that exist purely as directory nodes have no attribute data and are
        absent from the dump; that is normal and not an error.
        """
        path = normalize(path)
        if path in self._cache:
            return self._cache[path]

        file = self._path_to_file(path)
        obj: dict[str, Any] | None = None
        if file.is_file():
            try:
                with file.open(encoding="utf-8") as fh:
                    loaded = json.load(fh)
                # A handful of entries decode to a bare string rather than an object.
                obj = loaded if isinstance(loaded, dict) else None
            except (json.JSONDecodeError, OSError):
                obj = None

        elif file.with_suffix(".txt").is_file():
            from .ee import parse_ee
            obj = parse_ee(file.with_suffix(".txt").read_text(encoding="utf-8-sig"))

        self._cache[path] = obj
        return obj

    def exists(self, path: str) -> bool:
        return self.get(path) is not None

    # -- inheritance ---------------------------------------------------------------

    def parent_of(self, path: str) -> str | None:
        """Return the absolute path of ``path``'s parent type, if any."""
        parent = self.parents.get(normalize(path))
        return normalize(parent) if parent else None

    def ancestry(self, path: str) -> list[str]:
        """Return ``[path, parent, grandparent, ...]``, most-derived first.

        Cycles are truncated rather than raising; malformed chains in the dump should
        degrade to partial data, not abort a whole export.
        """
        chain: list[str] = []
        seen: set[str] = set()
        current: str | None = normalize(path)
        while current and current not in seen:
            seen.add(current)
            chain.append(current)
            current = self.parent_of(current)
        return chain

    def resolve(self, path: str) -> dict[str, Any]:
        """Return ``path``'s attributes merged across its full inheritance chain.

        Child values override ancestor values. Nested dicts are merged recursively so
        a subclass overriding one field of a struct does not discard its siblings.
        Lists are treated as atomic -- the engine replaces them wholesale.
        """
        path = normalize(path)
        if path in self._resolved:
            return self._resolved[path]

        merged: dict[str, Any] = {}
        # Walk ancestors first (least derived), letting each descendant overwrite.
        for ancestor in reversed(self.ancestry(path)):
            obj = self.get(ancestor)
            if obj:
                _deep_merge(merged, obj)

        self._resolved[path] = merged
        return merged

    # -- enumeration ---------------------------------------------------------------

    def iter_paths(self, prefix: str = "/") -> Iterator[str]:
        """Yield internal paths of every dumped object under ``prefix``."""
        base = self.root / prefix.strip("/")
        if not base.exists():
            return
        for file in base.rglob("*.json"):
            yield "/" + file.relative_to(self.root).with_suffix("").as_posix()


def load(build_dir: str | Path) -> PackageIndex:
    """Open the dump for one build, wiring in its inheritance table.

    Args:
        build_dir: A ``data/raw/<BuildLabel>`` directory produced by ``dump_all.ps1``.

    Raises:
        PackageError: If the dump or the raw Packages.bin needed for parent
            resolution is missing.
    """
    from wfarsenal import parenttable

    build = Path(build_dir)
    packages = build / "packages"
    raw = build / "Packages.bin"

    if not raw.is_file():
        raise PackageError(
            f"{raw} not found; inheritance cannot be resolved without the raw "
            "Packages.bin (re-run dump_all.ps1)"
        )

    return PackageIndex(root=packages, parents=parenttable.parse(raw))


def normalize(path: str) -> str:
    """Normalize an internal path to a leading slash and no trailing slash."""
    path = path.strip()
    if not path.startswith("/"):
        path = "/" + path
    return path.rstrip("/") or "/"


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Recursively merge ``src`` into ``dst`` in place; ``src`` wins on conflict."""
    for key, value in src.items():
        existing = dst.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            _deep_merge(existing, value)
        else:
            dst[key] = deepcopy(value)
