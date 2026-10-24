"""Riven disposition source.

Since 2026-10-23 every Riven weapon shares one disposition
(data/mechanics/riven-disposition.json, mode "uniform"). The exported
per-weapon values stay on each record as ``legacyOmegaAttenuation`` /
``legacyPrimaryOmegaAttenuation`` so mode "legacy" or a later per-weapon
table can bring them back without a new export.
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

_FIELDS = ("omegaAttenuation", "primaryOmegaAttenuation", "primeOmegaAttenuation")


@lru_cache(maxsize=1)
def setting() -> Mapping[str, Any]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        data = json.loads((root / "data/mechanics/riven-disposition.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"mode": "legacy"}
    return data if isinstance(data, Mapping) else {"mode": "legacy"}


def uniform_value() -> float | None:
    data = setting()
    if data.get("mode") != "uniform":
        return None
    value = data.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _positive(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def apply_record(record: dict[str, Any], value: float) -> dict[str, Any]:
    for field in _FIELDS:
        if field in record and _positive(record[field]):
            legacy = "legacy" + field[0].upper() + field[1:]
            record.setdefault(legacy, record[field])
            record[field] = value
    return record


def apply_exports(exports: dict[str, Any]) -> dict[str, Any]:
    """Rewrite loaded export records in place to the uniform disposition."""
    value = uniform_value()
    if value is None:
        return exports
    for row in exports.get("weapons") or ():
        if isinstance(row, dict):
            apply_record(row, value)
    for key, groups in (("kitguns", ("barrels",)), ("zaws", ("strikes",))):
        payload = exports.get(key)
        if not isinstance(payload, Mapping):
            continue
        for group in groups:
            for row in (payload.get(group) or {}).values():
                if isinstance(row, dict):
                    apply_record(row, value)
    templates = exports.get("rivenTemplates")
    if isinstance(templates, Mapping):
        for template in templates.get("templates") or ():
            for row in (template.get("dispositions") or ()) if isinstance(template, Mapping) else ():
                if isinstance(row, dict) and _positive(row.get("attenuation")):
                    row.setdefault("legacyAttenuation", row["attenuation"])
                    row["attenuation"] = value
    exports["rivenDisposition"] = {"mode": "uniform", "value": value, "effective": setting().get("effective")}
    return exports
