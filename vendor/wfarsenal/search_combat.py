"""Shared loadout event scoring for optimizer candidates and final checks."""
from __future__ import annotations
import json
from collections.abc import Mapping
from dataclasses import replace


def bind(stats, weapon, cards, effects, scenario, passives):
    modes = weapon.get("__baseFireModes__") or weapon.get("fireModes") or []
    selected = int(weapon.get("__selectedFireMode__", 0))
    full_weapon = {**weapon, "fireModes": modes}
    stats._combat_inputs = {
        "cards": tuple(cards),
        "engine": dict(weapon=full_weapon, effects=effects, scenario=scenario, fire_mode=selected),
        "mods": [(c.record, c.rank, None) for c in cards if c.record and c.record.get("path")],
        "arcanes": list(passives.event_arcanes) if passives else [],
        "choices": dict(passives.incarnon_choices) if passives else {},
    }
    stats._combat_scores = {}


def window(stats, context):
    from .manual_combat import prepare
    from .combat_replay import replay
    data = stats._combat_inputs
    key = json.dumps(context, sort_keys=True, ensure_ascii=False, default=str)
    cache = stats._combat_scores
    if key in cache:
        return cache[key]
    target = context.get("target") or {}
    scenario = data["engine"]["scenario"]
    enhancements = context.get("enemy_enhancements") or {}
    combat = prepare(
        data["engine"], data["mods"], data["arcanes"],
        cycle_enabled=scenario.incarnon_cycle, assumed=scenario.trigger_policy == "assumed_max",
        incarnon_choices=data["choices"], affinity_target=target, level=context.get("level"),
        eximus=bool(enhancements.get("eximus")),
    )
    result = replay(
        stats, target, combat=combat, trigger_sources=combat["trigger_sources"],
        attacks_per_second=stats.sustained_attack_rate,
        window_seconds=float(context.get("windowSeconds") or 30.0),
        headshot_chance=float(context.get("headshotChance", 1.0 if context.get("hit_location") == "head" else 0.0)),
        status_rate_multiplier=float(context.get("statusRateMultiplier") or 1.0),
        damage_rate_multiplier=float(context.get("stanceMultiplier") or 1.0),
        level=context.get("level"), armour_strip=float(context.get("armour_strip") or 0.0),
        elemental_armour_strip=float(context.get("elemental_armour_strip") or 0.0),
        steel_path=bool(context.get("steel_path")), enemy_enhancements=enhancements,
        forced_procs=context.get("forcedProcs"),
        collect_timeline=False,
    )
    for reason in result.get("unsupported") or []:
        if reason not in stats.unsupported:
            stats.unsupported.append(reason)
    cache[key] = result
    return result
