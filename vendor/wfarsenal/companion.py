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
    player = payload.get("companionPlayerStacks") is True
    out = {key: value for key, value in payload.items() if key not in _ARCANE_KEYS}
    out["headshotChance"] = 0.0
    out["aiming"] = False
    nested = payload.get("scenario")
    state = dict((nested or {}).get("combatState") or payload.get("combatState") or {})
    state.update(companion=True, companionPlayerStacks=player)
    if isinstance(nested, Mapping):
        out["scenario"] = {**nested, "aiming": False, "combatState": state}
    else:
        out["combatState"] = state
    return out
