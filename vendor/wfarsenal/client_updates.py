"""Client changes after the pinned export build (data/mechanics/client-updates.json).

The export stays the 2026.08.13 build; a game update that only moves a few
values is replayed onto the loaded records here, beside the uniform Riven
disposition. Every patch states the value it expects before the change: a
record already holding the new value is left alone, and one holding anything
else stops the load, so a re-export cannot be patched twice or silently.
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator, Mapping


@lru_cache(maxsize=1)
def patches() -> Mapping[str, Any]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        data = json.loads((root / "data/mechanics/client-updates.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"patches": []}
    return data if isinstance(data, Mapping) else {"patches": []}


def _same(a: Any, b: Any) -> bool:
    return (isinstance(a, (int, float)) and not isinstance(a, bool) and isinstance(b, (int, float))
            and math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-9))


def _records(exports: Mapping[str, Any], kind: str, paths: set[str]) -> Iterator[dict[str, Any]]:
    if kind == "incarnon":
        for weapon in exports.get("weapons") or ():
            for tier in (weapon.get("incarnon") or {}).get("tiers") or () if isinstance(weapon, Mapping) else ():
                for branch in tier.get("branches") or ():
                    if isinstance(branch, dict) and branch.get("path") in paths:
                        yield branch
    elif kind == "arcane":
        for row in exports.get("arcanes") or ():
            if isinstance(row, dict) and row.get("path") in paths:
                yield row


def _effect_lists(record: Mapping[str, Any]) -> Iterator[list[dict[str, Any]]]:
    yield record.get("effects") or []
    for conditional in record.get("conditionalEffects") or ():
        if isinstance(conditional, Mapping):
            yield conditional.get("effects") or []


def _apply(patch: Mapping[str, Any], record: dict[str, Any]) -> None:
    where = f"client update {patch['id']}: {record.get('path')}"
    for rule in patch.get("effects") or ():
        (old_op, old_value), (new_op, new_value) = rule["from"], rule["to"]
        hits = 0
        for effects in _effect_lists(record):
            for effect in effects:
                if not isinstance(effect, dict) or effect.get("upgradeType") != rule["upgradeType"]:
                    continue
                op, value = effect.get("operation"), effect.get("valuePerRank")
                if op == old_op and _same(value, old_value):
                    effect["operation"], effect["valuePerRank"] = new_op, new_value
                    if patch.get("locTag"):
                        effect["locTag"] = patch["locTag"]
                elif not (op == new_op and _same(value, new_value)):
                    raise ValueError(f"{where}: {rule['upgradeType']} is {op} {value}, expected {old_op} {old_value}")
                hits += 1
        if not hits:
            raise ValueError(f"{where}: no {rule['upgradeType']} effect")
    if patch.get("maxStacks"):
        old_stacks, new_stacks = patch["maxStacks"]
        for conditional in record.get("conditionalEffects") or ():
            stacks = conditional.get("maxStacks") if isinstance(conditional, dict) else None
            if stacks == old_stacks:
                conditional["maxStacks"] = new_stacks
            elif stacks != new_stacks:
                raise ValueError(f"{where}: maxStacks {stacks}, expected {old_stacks} or {new_stacks}")
    if patch.get("conditionTag"):
        for conditional in [*(record.get("conditionalEffects") or ()), record.get("trigger")]:
            if isinstance(conditional, dict):
                conditional["conditionTag"] = patch["conditionTag"]
    trigger = record.get("trigger")
    for field, (old, new) in (patch.get("trigger") or {}).items():
        if not isinstance(trigger, dict) or not (_same(trigger.get(field), old) or _same(trigger.get(field), new)):
            raise ValueError(f"{where}: trigger {field} {None if trigger is None else trigger.get(field)}, expected {old}")
        trigger[field] = new
    for field in ("effectsZhByRank", "effectsEnByRank"):
        if patch.get(field):
            record[field] = [list(lines) for lines in patch[field]]


def apply_exports(exports: dict[str, Any]) -> dict[str, Any]:
    """Rewrite loaded export records in place to the live client's values."""
    applied = []
    for patch in patches().get("patches") or ():
        paths = set(patch.get("paths") or ())
        found = {record.get("path") for record in _records(exports, patch.get("kind"), paths)}
        for record in _records(exports, patch.get("kind"), paths):
            _apply(patch, record)
        missing = paths - found
        if missing:
            raise ValueError(f"client update {patch['id']}: no exported record for {sorted(missing)}")
        applied.append(patch["id"])
    exports["clientUpdates"] = {**(patches().get("client") or {}), "applied": applied}
    return exports
