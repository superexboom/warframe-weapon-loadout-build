"""Cache keys for engine records (weapons, targets, MOD records).

Callers copy records shallowly (``{**weapon, "fireModes": ...}``) and some
change top-level fields in place (a test sets ``target["overguard"]`` between
replays), so a key reads top-level scalars by value and nested containers by
identity: nested data (fire modes, hit proxies) is catalog data that is
rebuilt, never edited. A cache entry must hold the record so the ids it keyed
on stay valid.
"""
from __future__ import annotations

from typing import Any, Mapping

_SCALARS = frozenset({str, int, float, bool, type(None)})


def shallow_key(record: Mapping[str, Any]) -> tuple:
    return tuple((key, 0, value) if type(value) in _SCALARS else (key, 1, id(value))
                 for key, value in record.items())
