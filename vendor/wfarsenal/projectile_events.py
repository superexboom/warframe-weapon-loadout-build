"""Bounded evaluation for complex projectile events.

This is deliberately not a timeline. It applies the existing weapon damage reducer
to each statically known event, reports safe count bounds, and leaves Lua/native
transitions excluded from aggregate totals.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Mapping

from .damage import ModEffect, ModEffectList, Scenario, apply_mods, damage_against
from .event_profiles import base_profile


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

    # The bounded preview uses the same verified projectile identity as the
    # timeline. Generic ExplosiveAttack fields alone do not imply area-direct.
    stackable = base_profile(weapon, fire_mode).get("stackable") or {}
    stug_main_events = {
        str(raw.get("id")): raw for raw in raw_events
        if isinstance(raw, Mapping) and _stug_main_event(raw, stackable, (mode.get("damage") or {}).get("projectile"))
    }
    stug_explosion = next((raw for raw in stug_main_events.values()
                           if raw.get("kind") == "explosion"), None)
    for raw in raw_events:
        if not isinstance(raw, Mapping):
            continue
        result = _event_identity(raw)
        unsupported.update(raw.get("unsupported") or ())
        damage = raw.get("damage")
        if isinstance(damage, Mapping) and damage.get("types"):
            main_blob = str(raw.get("id")) in stug_main_events
            event_effects = selected_effects
            if main_blob and not stackable["explosion"].get("takesConditionOverload"):
                event_effects = ModEffectList(
                    [effect for effect in selected_effects
                     if effect.upgrade_type != "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"],
                    skipped=selected_effects.skipped,
                )
            stats = apply_mods(
                _event_weapon(weapon, mode, damage),
                event_effects,
                scenario=scenario,
            )
            if main_blob:
                # M127/native lifecycle: the parent blast is an area direct
                # event; target head-location damage is suppressed, while its
                # separate head bonus/crit bracket stays available. Children
                # remain radial and never inherit this classification.
                stats = replace(stats, radial_only=False, area_direct=True,
                                weakpoint_damage_bonus=0.0)
                result["hitClassification"] = "area-direct"
                if raw.get("kind") == "embedDeath" and stug_explosion is not None:
                    # ExplosiveAttack and EmbedDeathAttack are alternative
                    # destruction paths of this one parent blob, not two hits.
                    result["aggregate"] = False
                    result["alternativeOf"] = stug_explosion["id"]
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



def _stug_main_event(event: Mapping[str, Any], profile: Mapping[str, Any], projectile: Any) -> bool:
    """Apply an audited exception only to its matched parent damage payload."""
    if (profile.get("kind") != "stug" or event.get("kind") not in {"explosion", "embedDeath"}
            or not projectile or event.get("projectile") != projectile):
        return False
    damage = event.get("damage")
    component = profile.get("explosion")
    return (isinstance(damage, Mapping) and isinstance(component, Mapping)
            and damage.get("types") == component.get("damage"))


def _event_weapon(
    weapon: Mapping[str, Any], mode: Mapping[str, Any], damage: Mapping[str, Any]
) -> dict[str, Any]:
    event_mode = {
        key: mode.get(key)
        for key in ("fireRate", "reloadTime", "falloffRange", "falloffMinDamage", "nativeIgnoreFireIterations")
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


_QUANTA_CUBES = {
    "/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifle":
        ("/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifleProjectile", 100.0),
    "/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/QuantaVandal":
        ("/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifleProjectile", 100.0),
    "/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEQuanta/CrpBEQuanta":
        ("/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEQuanta/CrpBEQuantaProjectile", 180.0),
}


def quanta_strategy(weapon, fire_mode=0, combat_state=None):
    """Exact-source opt-in for launching a cube and paying a primary pulse.

    This contract supplies integration metadata; the replay must reserve the
    primary action and remove enemy contact/beam damage. Cubes must avoid enemy
    contact until shot and overlap the selected enemy at their terminal event.
    Ordinary contact remains the default. Native source: Packages 00ca8221 and
    EXE eec0dbd7, Projectile receiver 1401c2190 / selector 14160c5a0.
    """
    if (combat_state or {}).get("quantaStrategy") != "shoot":
        return None
    identity = _QUANTA_CUBES.get(weapon.get("path"))
    modes = weapon.get("fireModes") or ()
    if identity is None or weapon.get("isIncarnonForm") or not 0 <= fire_mode < len(modes):
        return None
    index = weapon.get("__selectedFireMode__", fire_mode)
    mode = modes[fire_mode]
    damage = mode.get("damage") or {}
    projectile, total = identity
    if (index != 1 or damage.get("projectile") != projectile
            or damage.get("types") != {"DT_ELECTRICITY": total}
            or mode.get("ammoCost") != 10):
        return None
    original = weapon.get("__baseFireModes__") or modes
    if not original or original[0].get("trigger") != "/Lotus/Language/Menu/Loadout_TriggerContinous":
        return None
    return dict(kind="quanta-paid-primary", nativeSource=projectile,
                nativeField="ExplosiveAttack", launchMode=1, primaryMode=0,
                damageMultiplier=4.0, radiusMultiplier=12.0, radiusMeters=6.0,
                settleSeconds=0.25, meanDeathDelaySeconds=0.1125,
                nativeDeathDelayRange=(0.075, 0.15),
                chainDeathDelaySeconds=0.1125,
                enemyContactDamage=False, enemyPrimaryBeamDamage=False,
                coverage="standoff-volley-with-one-seed-and-sibling-chain-overlap",
                unsupported=("quanta-standoff-cube-and-chain-overlap-assumed",
                             "quanta-paid-primary-one-pulse-hit-assumed",
                             "quanta-shot-native-delay-approximated-by-mean"))


def quanta_strategy_cycle(strategy, launch_stats, primary_stats):
    """Cost one full primary quantum using both modes' actual modded stats.

    Reserve settle + primary period + native mean terminal delay sequentially;
    do not shorten it by replacing the alternate's own cadence. The caller
    applies normal ammo-efficiency/infinite-ammo rules and full-ammo gating.
    """
    import math
    if not strategy or strategy.get("kind") != "quanta-paid-primary":
        return None
    launch_rate = float(launch_stats.fire_rate)
    primary_rate = float(primary_stats.fire_rate)
    costs = (float(launch_stats.ammo_cost), float(primary_stats.ammo_cost))
    if (not all(math.isfinite(value) and value >= 0 for value in costs)
            or not all(math.isfinite(rate) and rate > 0 for rate in (launch_rate, primary_rate))):
        raise ValueError("Quanta strategy requires finite positive mode rates and nonnegative ammo costs")
    primary_period = 1.0 / primary_rate
    impact_delay = strategy["settleSeconds"] + primary_period + strategy["meanDeathDelaySeconds"]
    return dict(launchAmmoCost=costs[0], primaryAmmoCost=costs[1],
                ammoCost=sum(costs), primaryPeriodSeconds=primary_period,
                impactDelaySeconds=impact_delay,
                cycleSeconds=max(1.0 / launch_rate, impact_delay))
