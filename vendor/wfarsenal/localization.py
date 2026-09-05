"""Version-aware localization catalogs for exported arsenal records."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


class LocalizationError(ValueError):
    """Raised when a localization source cannot be parsed safely."""


class LocalizationConflictError(LocalizationError):
    """Raised when one tag has two different values in the same catalog."""


@dataclass(frozen=True)
class LocalizationCatalog:
    """An immutable tag-to-text map plus provenance metadata."""

    _values: Mapping[str, str]
    source: str
    content_hash: str
    version: str | None = None
    _input_path: str | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        source = _stable_source_label(self.source)
        content_hash = _checked_hash(self.content_hash)
        version = self.version.strip() if isinstance(self.version, str) else self.version
        if version == "":
            version = None
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "content_hash", content_hash)

    @classmethod
    def from_file(
        cls,
        path: str | Path,
        *,
        source: str | None = None,
        version: str | None = None,
    ) -> "LocalizationCatalog":
        """Load a UTF-8 JSON catalog and record its SHA-256 provenance."""
        path = Path(path)
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except OSError as exc:
            raise LocalizationError(f"cannot read localization file {path}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise LocalizationError(f"localization file is not UTF-8: {path}") from exc

        return cls.from_json(
            text,
            source=source or path.name,
            version=version,
            content_hash=hashlib.sha256(raw).hexdigest(),
            _input_path=str(path.resolve()),
        )

    @classmethod
    def from_json(
        cls,
        text: str,
        *,
        source: str | None = None,
        version: str | None = None,
        content_hash: str | None = None,
        _input_path: str | None = None,
    ) -> "LocalizationCatalog":
        """Parse either WPEP's ``[{id,value}]`` form or a simple JSON object."""
        raw = text.encode("utf-8")
        actual_hash = hashlib.sha256(raw).hexdigest()
        if content_hash is not None and _checked_hash(content_hash) != actual_hash:
            raise LocalizationError("localization content hash does not match JSON text")
        try:
            payload = json.loads(text, object_pairs_hook=_checked_object)
        except json.JSONDecodeError as exc:
            where = f" in {source}" if source else ""
            raise LocalizationError(
                f"invalid localization JSON{where}: line {exc.lineno}, column {exc.colno}"
            ) from exc
        return cls.from_data(
            payload,
            source=source or "inline-json",
            version=version,
            content_hash=actual_hash,
            _input_path=_input_path,
            _content_hash_verified=True,
        )

    @classmethod
    def from_data(
        cls,
        payload: Any,
        *,
        source: str | None = None,
        version: str | None = None,
        content_hash: str | None = None,
        _input_path: str | None = None,
        _content_hash_verified: bool = False,
    ) -> "LocalizationCatalog":
        """Build a catalog from decoded list or dict data."""
        if _content_hash_verified:
            actual_hash = _checked_hash(content_hash)
        else:
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            actual_hash = hashlib.sha256(canonical).hexdigest()
            if content_hash is not None and _checked_hash(content_hash) != actual_hash:
                raise LocalizationError("localization content hash does not match decoded data")
        values: dict[str, str] = {}
        if isinstance(payload, dict):
            rows = payload.items()
        elif isinstance(payload, list):
            rows = _list_rows(payload)
        else:
            raise LocalizationError(
                "localization root must be an object or a list of {id, value} rows"
            )

        for key, value in rows:
            if not isinstance(key, str) or not isinstance(value, str):
                raise LocalizationError("localization ids and values must be strings")
            key = key.strip()
            if not key or not value.strip():
                continue
            previous = values.get(key)
            if previous is not None and previous != value:
                raise LocalizationConflictError(
                    f"localization tag {key!r} has conflicting values: "
                    f"{previous!r} != {value!r}"
                )
            values[key] = value

        return cls(
            MappingProxyType(values),
            source=source or "inline-data",
            version=version,
            content_hash=actual_hash,
            _input_path=_input_path,
        )

    def lookup(self, tag: str | None) -> str | None:
        """Return the exact localized value, or ``None`` when the tag is unknown."""
        if not isinstance(tag, str) or not tag:
            return None
        return self._values.get(tag)

    @property
    def metadata(self) -> dict[str, str | None]:
        """Return source provenance in a serialization-friendly shape."""
        return {
            "source": self.source,
            "version": self.version,
            "hash": self.content_hash,
        }

    @property
    def input_path(self) -> Path | None:
        """Return the local parsed file for validation, never for stable export."""
        return Path(self._input_path) if self._input_path else None

    def __len__(self) -> int:
        return len(self._values)


def apply_localizations(
    record: Mapping[str, Any], catalogs: Mapping[str, LocalizationCatalog]
) -> dict[str, Any]:
    """Copy a record and attach localized names without replacing legacy ``name``."""
    localized = dict(record)
    internal = record.get("nameInternal") or record.get("name")
    localized["nameInternal"] = internal
    tag = record.get("nameTag")

    for language, catalog in normalize_catalogs(catalogs).items():
        suffix = _language_suffix(language)
        localized[f"name{suffix}"] = catalog.lookup(tag) or internal
    return localized


def normalize_language_key(language: str) -> str:
    """Return one stable BCP47-like key and reject punctuation-only names."""
    if not isinstance(language, str):
        raise LocalizationError("catalog language keys must be strings")
    parts = re.findall(r"[A-Za-z0-9]+", language)
    if not parts:
        raise LocalizationError(f"invalid catalog language key: {language!r}")
    return "-".join(part.lower() for part in parts)


def normalize_catalogs(
    catalogs: Mapping[str, LocalizationCatalog],
) -> dict[str, LocalizationCatalog]:
    """Canonicalize locale keys and fail closed when aliases collide."""
    normalized: dict[str, LocalizationCatalog] = {}
    original: dict[str, str] = {}
    for language, catalog in catalogs.items():
        key = normalize_language_key(language)
        if key in normalized:
            raise LocalizationConflictError(
                f"catalog language keys {original[key]!r} and {language!r} "
                f"both normalize to {key!r}"
            )
        normalized[key] = catalog
        original[key] = language
    return normalized


def _checked_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Preserve same-value duplicate keys and reject conflicting JSON object keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result and result[key] != value:
            raise LocalizationConflictError(
                f"JSON object key {key!r} has conflicting duplicate values"
            )
        result[key] = value
    return result


def _list_rows(payload: list[Any]) -> list[tuple[Any, Any]]:
    rows: list[tuple[Any, Any]] = []
    for index, row in enumerate(payload):
        if row is None or row == {}:
            continue
        if not isinstance(row, dict):
            raise LocalizationError(f"localization row {index} must be an object")
        if "id" not in row or "value" not in row:
            raise LocalizationError(
                f"localization row {index} must contain both 'id' and 'value'"
            )
        rows.append((row["id"], row["value"]))
    return rows


def _language_suffix(language: str) -> str:
    parts = normalize_language_key(language).split("-")
    return "".join(part[:1].upper() + part[1:] for part in parts)


def _stable_source_label(source: str) -> str:
    if not isinstance(source, str) or not source.strip():
        raise LocalizationError("localization provenance source must be non-empty")
    label = source.strip()
    if "/" in label or "\\" in label:
        label = re.split(r"[/\\]+", label)[-1]
    if not label:
        raise LocalizationError("localization provenance source must be non-empty")
    return label


def _checked_hash(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
        raise LocalizationError("localization provenance hash must be a SHA-256 hex digest")
    return value.lower()


__all__ = [
    "LocalizationCatalog",
    "LocalizationConflictError",
    "LocalizationError",
    "apply_localizations",
    "normalize_catalogs",
    "normalize_language_key",
]
