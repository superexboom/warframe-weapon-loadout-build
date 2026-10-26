"""The optimizer's sustained-status scores on the native core.

``optimizer._score`` ranks the element-seed searches by
``sustained_status_damage(...)["totalDps"]`` (``statusSustainedDps``) or
``["directDps"]`` (``targetSustainedDps``). ``wfcore.sustained_status``
computes those two numbers in the reference's order; the target-side inputs
that do not depend on the build are prepared here once per target context.

``WF_NATIVE=0`` / ``WF_NATIVE_STATUS=0`` keep the Python reference;
``WF_NATIVE_SHADOW=1`` runs both on every call and raises on a difference.
"""
from __future__ import annotations

import os
from typing import Any, Mapping

try:  # pragma: no cover - exercised when the native core is built
    from . import wfcore
except ImportError:  # pragma: no cover
    wfcore = None

ENABLED = (wfcore is not None and hasattr(wfcore, "SustainedTarget") and os.environ.get("WF_NATIVE") != "0"
           and os.environ.get("WF_NATIVE_STATUS") != "0")
SHADOW = os.environ.get("WF_NATIVE_SHADOW") == "1"

# By target (record_keys.record_key, the entry pins its values) and the
# target arguments. A plain dict emptied when full: request threads share it.
_TARGETS: dict = {}


class Unsupported(Exception):
    """This call stays on the Python reference."""


def _arguments(target_kwargs: Mapping[str, Any]) -> tuple:
    enhancements = target_kwargs.get("enemy_enhancements")
    return (target_kwargs.get("level"), target_kwargs.get("armour_strip", 0.0),
            target_kwargs.get("elemental_armour_strip", 0.0), target_kwargs.get("steel_path", False),
            target_kwargs.get("hit_location"),
            None if enhancements is None else tuple(sorted(enhancements.items())))


def _target(target: Mapping[str, Any], target_kwargs: Mapping[str, Any]):
    from .record_keys import pin, record_key

    try:
        key = (record_key(target), _arguments(target_kwargs))
        hash(key)
    except (AttributeError, TypeError) as exc:
        raise Unsupported("unhashable target arguments") from exc
    hit = _TARGETS.get(key)
    if hit is not None:
        return hit[1]
    from .damage import (
        DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES, DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES, _damage_type_set,
        _enemy_enhancement_options, _faction_damage_deltas, _hit_location_info, _normalise_hit_location,
        _scaled_armour, enemy_defenses, faction_bracket,
    )

    level = target_kwargs.get("level")
    armour_strip = target_kwargs.get("armour_strip", 0.0)
    elemental = target_kwargs.get("elemental_armour_strip", 0.0)
    enhancements = target_kwargs.get("enemy_enhancements")
    try:
        defenses = enemy_defenses(target, level=level, steel_path=target_kwargs.get("steel_path", False),
                                  armour_strip=armour_strip, elemental_armour_strip=elemental,
                                  enemy_enhancements=enhancements)
        aura = float(_enemy_enhancement_options(enhancements)["auraArmourReduction"])
        armour_base = _scaled_armour(target, level, multiplier=1.0)

        def location(name):
            where, hit_multiplier, critical_multiplier, _unsupported, _metadata = _hit_location_info(target, name)
            return (float(hit_multiplier), float(critical_multiplier), _normalise_hit_location(where) == "head")

        body = location("body")
        located = location(target_kwargs.get("hit_location"))
    except Exception as exc:  # the reference raises its own error for these
        raise Unsupported(str(exc)) from exc
    # The armour the native side derives must be the reference's own.
    armour = armour_base
    armour *= 1.0 - float(armour_strip)
    armour *= 1.0 - float(elemental)
    armour *= 1.0 - aura
    if armour != defenses["armour"]:
        raise Unsupported("armour derivation differs")
    core = wfcore.SustainedTarget(dict(
        armourBase=float(armour_base), armourStrip=float(armour_strip), auraArmourReduction=aura,
        elementalArmourStrip=float(elemental), overguard=float(defenses.get("overguard") or 0.0),
        shield=float(defenses["shield"]), magneticStacks=int(defenses.get("magneticStacks") or 0),
        shielded=bool(target.get("shield")),
        factionDeltas=[(str(k), float(v)) for k, v in _faction_damage_deltas(target).items()],
        armourBypass=sorted(_damage_type_set(target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES)),
        shieldBypass=sorted(_damage_type_set(target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES)),
        targetFaction=str(target.get("faction") or ""), factionBracket=faction_bracket(target), body=body, located=located,
        existingMagnetic=int((enhancements or {}).get("magneticStacks") or 0),
    ))
    if len(_TARGETS) >= 256:
        _TARGETS.clear()
    _TARGETS[key] = (pin(target), core)
    return core


def score(stats, target: Mapping[str, Any], target_kwargs: Mapping[str, Any], *,
          status_rate_multiplier: float, damage_rate_multiplier: float, total: bool) -> float:
    """``sustained_status_damage(...)["totalDps" if total else "directDps"]``."""
    if not isinstance(target, Mapping):
        raise Unsupported("no target")
    if getattr(stats,'ignore_headshot_bonus',False) and not getattr(wfcore,'IGNORE_HEADSHOT_BONUS',0):
        raise Unsupported('core predates native projectile headshot rules')
    if getattr(stats, 'area_direct', False) and not getattr(wfcore, 'STUG_AREA_DIRECT', 0):
        raise Unsupported('core predates area direct hit classification')
    core = _target(target, target_kwargs)
    value = wfcore.sustained_status(core, stats, float(stats.sustained_attack_rate), float(status_rate_multiplier),
                                    float(damage_rate_multiplier), total)
    if SHADOW:
        from .damage import sustained_status_damage

        reference = float(sustained_status_damage(
            stats, target, attacks_per_second=stats.sustained_attack_rate,
            status_rate_multiplier=status_rate_multiplier, damage_rate_multiplier=damage_rate_multiplier,
            **target_kwargs,
        )["totalDps" if total else "directDps"])
        if reference.hex() != value.hex():
            raise AssertionError(f"native sustained status differs: {reference!r} != {value!r}")
    return value
