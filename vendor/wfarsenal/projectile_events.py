"""Bounded evaluation for complex projectile events.

This is deliberately not a timeline. It applies the existing weapon damage reducer
to each statically known event, reports safe count bounds, and leaves Lua/native
transitions excluded from aggregate totals.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .damage import ModEffect, ModEffectList, Scenario, apply_mods, damage_against


def evaluate_projectile_events(
    weapon: Mapping[str, Any],
    effects: Iterable[ModEffect],
    *,
    fire_mode: int = 0,
    scenario: Scenario | None = None,
    target: Mapping[str, Any] | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    enemy_enhancements: Mapping[str, Any] | None = None,
    hit_location: str = "body",
) -> dict[str, Any] | None:
    """Evaluate exported projectile events without guessing event timing.

    ``minimum``/``maximum`` include only events marked safe for aggregation by the
    extractor. Script-derived alternatives are still evaluated when their static
    multiplier is known, but remain under ``excluded`` until their transition is
    verified.
    """
    modes = weapon.get("fireModes") or ()
    if fire_mode >= len(modes):
        raise ValueError(f"fire mode {fire_mode} is out of range")
    mode = modes[fire_mode]
    raw_events = mode.get("projectileEvents") or ()
    if not raw_events:
        return None

    scenario = scenario or Scenario()
    selected_effects = ModEffectList(
        list(effects), skipped=getattr(effects, "skipped", ())
    )
    evaluated: list[dict[str, Any]] = []
    raw_results: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
    by_source: dict[str, dict[str, Any]] = {}
    support = mode.get("projectileEventSupport") or {}
    unsupported = set(support.get("unsupported") or ())
    runtime_adapters = [
        dict(adapter)
        for adapter in support.get("runtimeAdapters") or ()
        if isinstance(adapter, Mapping)
    ]
    derived_events = [
        dict(event)
        for event in (mode.get("projectileDerivedEvents") or mode.get("derivedEvents") or ())
        if isinstance(event, Mapping)
    ]
    for adapter in runtime_adapters:
        unsupported.update(adapter.get("unsupported") or ())
    for event in derived_events:
        unsupported.update(event.get("unsupported") or ())

    for raw in raw_events:
        if not isinstance(raw, Mapping):
            continue
        result = _event_identity(raw)
        unsupported.update(raw.get("unsupported") or ())
        damage = raw.get("damage")
        if isinstance(damage, Mapping) and damage.get("types"):
            stats = apply_mods(
                _event_weapon(weapon, mode, damage),
                selected_effects,
                scenario=scenario,
            )
            copies = stats.multishot
            per_occurrence: dict[str, Any] = {
                "moddedDamage": stats.total_damage,
                "averageHit": stats.average_hit,
                "copyMultiplier": copies,
            }
            target_hit: float | None = None
            if target is not None:
                target_result = damage_against(
                    stats,
                    target,
                    level=level,
                    armour_strip=armour_strip,
                    elemental_armour_strip=elemental_armour_strip,
                    steel_path=steel_path,
                    enemy_enhancements=enemy_enhancements,
                    hit_location=hit_location,
                )
                per_occurrence["targetPerHit"] = target_result["perHit"]
                target_hit = float(target_result["perHit"])
                unsupported.update(target_result.get("unsupported") or ())
            result["perOccurrence"] = per_occurrence
            result["contribution"] = _contribution(
                raw,
                modded=stats.total_damage * copies,
                average=stats.average_hit * copies,
                target=target_hit * copies if target_hit is not None else None,
            )
            unsupported.update(stats.unsupported)
            source = damage.get("source")
            if isinstance(source, str) and source:
                by_source[source] = result
        evaluated.append(result)
        raw_results.append((raw, result))

    for raw, result in raw_results:
        if raw.get("kind") != "scriptRadial":
            continue
        source = by_source.get(str(raw.get("baseSource") or ""))
        multipliers = raw.get("multiplierRange")
        if not source or not isinstance(multipliers, list) or len(multipliers) != 2:
            unsupported.add("script-radial-base-unresolved")
            continue
        per = source["perOccurrence"]
        low, high = sorted(float(value) for value in multipliers)
        result["derivedFrom"] = raw.get("baseSource")
        result["perOccurrenceRange"] = {
            "moddedDamage": [per["moddedDamage"] * low, per["moddedDamage"] * high],
            "averageHit": [per["averageHit"] * low, per["averageHit"] * high],
        }
        if "targetPerHit" in per:
            result["perOccurrenceRange"]["targetPerHit"] = [
                per["targetPerHit"] * low,
                per["targetPerHit"] * high,
            ]

    totals = {
        metric: _sum_contributions(evaluated, metric)
        for metric in ("moddedDamage", "averageHit", "targetDamage")
    }
    if target is None:
        totals.pop("targetDamage")
    excluded = [
        event["id"]
        for event in evaluated
        if not event.get("aggregate", False)
    ]
    excluded.extend(
        str(event["id"])
        for event in derived_events
        if event.get("id") is not None
    )
    partial = bool(unsupported or excluded) or any(
        event.get("countRange", [0, 0])[0] != event.get("countRange", [0, 0])[1]
        for event in evaluated
        if event.get("aggregate", False)
    )
    return {
        "status": "partial" if partial else "exact",
        "state": dict(mode.get("projectileEventState") or {}),
        "events": evaluated,
        "runtimeAdapters": runtime_adapters,
        "derivedEvents": derived_events,
        "totals": totals,
        "excluded": excluded,
        "unsupported": sorted(unsupported),
    }


def _event_weapon(
    weapon: Mapping[str, Any], mode: Mapping[str, Any], damage: Mapping[str, Any]
) -> dict[str, Any]:
    event_mode = {
        key: mode.get(key)
        for key in ("fireRate", "reloadTime", "falloffRange", "falloffMinDamage")
        if mode.get(key) is not None
    }
    event_mode["multishot"] = 1
    event_mode["damage"] = {
        key: value for key, value in damage.items() if key != "components"
    }
    return {**weapon, "fireModes": [event_mode]}


def _event_identity(event: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: event.get(key)
        for key in (
            "id",
            "kind",
            "trigger",
            "projectile",
            "countRange",
            "aggregate",
            "support",
            "damageRange",
            "range",
            "radius",
            "multipliers",
            "multiplierRange",
            "baseSource",
            "conditionText",
        )
        if event.get(key) is not None
    }
    result["unsupported"] = list(event.get("unsupported") or ())
    return result


def _contribution(
    event: Mapping[str, Any],
    *,
    modded: float,
    average: float,
    target: float | None,
) -> dict[str, Any]:
    counts = event.get("countRange") or (0, 0)
    low, high = sorted((float(counts[0]), float(counts[1])))
    contribution: dict[str, Any] = {
        "moddedDamage": [modded * low, modded * high],
        "averageHit": [average * low, average * high],
    }
    if target is not None:
        contribution["targetDamage"] = [target * low, target * high]
    return contribution


def _sum_contributions(
    events: Iterable[Mapping[str, Any]], metric: str
) -> dict[str, float]:
    minimum = maximum = known = 0.0
    for event in events:
        if not event.get("aggregate", False):
            continue
        values = (event.get("contribution") or {}).get(metric)
        if not isinstance(values, list) or len(values) != 2:
            continue
        low, high = float(values[0]), float(values[1])
        minimum += low
        maximum += high
        if low == high:
            known += low
    return {"known": known, "minimum": minimum, "maximum": maximum}
