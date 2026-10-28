"""Companion (sentinel / MOA / hound) weapon rules.

A companion fires through its own avatar under AI control:

* every companion weapon's AI aims at the torso (``AiUsageInfo.preferences
  .aimAtPart = TORSO``) and never aims down sights, so headshot and aiming
  conditions never fire;
* trigger conditions with ``DamageSources = [TennoAvatar]``
  (data/mechanics/player-only-conditions.json) count the player's own kills
  and hits only. Galvanized stacks on a companion weapon therefore come from
  the player's kills with that weapon class, never from the companion: the
  ``companionPlayerStacks`` switch assumes them full, off assumes none;
* robotic weapons cannot equip Arcanes (wiki Arcane_Enhancement, Sentinel).
"""
from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

_ARCANE_KEYS = ("arcanes", "weaponArcane", "weaponArcane2", "frameArcanes", "autoArcane")


@lru_cache(maxsize=1)
def player_only_conditions() -> frozenset[str]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    data = json.loads((root / "data/mechanics/player-only-conditions.json").read_text(encoding="utf-8"))
    return frozenset(data["conditions"])


def is_companion(weapon: Mapping[str, Any]) -> bool:
    return weapon.get("slot") == "companion" or weapon.get("weaponType") == "companion"


def player_only(conditional: Mapping[str, Any]) -> bool:
    known = player_only_conditions()
    return any(str(c) in known for c in conditional.get("conditions") or ())


def kill_condition(conditional: Mapping[str, Any]) -> bool:
    return any("kill" in str(c).rsplit("/", 1)[-1].casefold() for c in conditional.get("conditions") or ())


def player_stacks(scenario: Any) -> bool | None:
    """None outside a companion weapon; else whether player kills feed its stacks."""
    state = getattr(scenario, "combat_state", None) or {}
    if not state.get("companion"):
        return None
    return bool(state.get("companionPlayerStacks"))


def companion_payload(payload: Mapping[str, Any], weapon: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pin a request for a companion weapon to what its AI can actually do."""
    if not is_companion(weapon):
        return payload
    from .simulator import SimulationError

    nested = payload.get("scenario")
    if nested is not None and not isinstance(nested, Mapping):
        raise SimulationError("scenario must be an object")
    scenario = nested or {}
    # Match the shared parser: an explicit nested value, including {}, wins.
    raw_state = scenario.get("combatState", payload.get("combatState", {}))
    if not isinstance(raw_state, Mapping):
        raise SimulationError("combatState must be an object")
    state = dict(raw_state)
    player = scenario.get("companionPlayerStacks",
                          payload.get("companionPlayerStacks", state.get("companionPlayerStacks", False)))
    if not isinstance(player, bool):
        raise SimulationError("companionPlayerStacks must be a boolean")
    out = {key: value for key, value in payload.items() if key not in _ARCANE_KEYS}
    out.update(headshotChance=0.0, hitLocation="body", aiming=False, companionPlayerStacks=player)
    state.update(companion=True, companionPlayerStacks=player)
    if isinstance(nested, Mapping):
        out["scenario"] = {**nested, "aiming": False, "combatState": state}
    else:
        out["combatState"] = state
    # Riven callers can supply their own target. It must not bypass the same
    # torso-only restriction applied to build/manual requests.
    target = payload.get("benchmarkTarget")
    if isinstance(target, Mapping):
        out["benchmarkTarget"] = {**target, "headshotChance": 0.0, "hitLocation": "body"}
    return out


def unresolved_weapon_mechanics(weapon: Mapping[str, Any]) -> list[str]:
    """Verified native/export omissions, kept visible until event timing is known."""
    if not is_companion(weapon):
        return []
    path = str(weapon.get("path") or "")
    result = []
    if path == "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/CryoxionWeapon":
        from .event_profiles import base_profile
        selected = int(weapon.get('__selectedFireMode__', 0))
        mode = (weapon.get('fireModes') or [{}])[0 if len(weapon.get('fireModes') or []) == 1 else selected]
        damage = mode.get('damage') or {}
        profile = base_profile(weapon, 0 if len(weapon.get('fireModes') or []) == 1 else selected)
        if not profile.get('lingering'):
            result.append('cryotra-cold-field-unmodeled')
        if (damage.get('projectile') != '/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/CryoxionProjectile'
                or 'PT_CHILLED' not in (damage.get('forcedProcs') or [])):
            result.append('cryotra-projectile-forced-cold-unmodeled')
    if any((mode.get("damage") or {}).get("sequenceDamage")
           for mode in weapon.get("fireModes") or () if isinstance(mode, Mapping)):
        result.append("companion-projectile-damage-sequence-unmodeled")
    return result
