"""Cache keys for engine records (weapons, targets, MOD records).

Callers copy records shallowly (``{**weapon, "fireModes": ...}``) and some
change top-level fields in place (a test sets ``target["overguard"]`` between
replays), so a key is the record's field names and the identity of each value:
copies that share their values share a key, and a field set to anything else
changes it. A cache entry keeps ``pin(record)`` -- the values themselves -- so
no keyed value can be freed and its id reused by a new one. Nested data (fire
modes, hit proxies) is catalog data that is rebuilt, never edited in place.
"""
from __future__ import annotations

from typing import Any, Mapping


def record_key(record: Mapping[str, Any]) -> tuple:
    return (tuple(record), tuple(map(id, record.values())))


def pin(record: Mapping[str, Any]) -> tuple:
    """What a cache entry keyed by :func:`record_key` must hold."""
    return tuple(record.values())
