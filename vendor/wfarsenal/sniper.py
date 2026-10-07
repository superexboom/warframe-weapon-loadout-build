"""Sniper Shot Combo counter and zoom buffs.

Data: data/mechanics/sniper-mechanics.json (tools/import_sniper_mechanics.py),
read from the game packages' SniperImpactBehavior and ZoomLevels and
cross-checked against WFSim's weapon YAML. Semantics follow WFSim
engine/src/model/weapon.rs SniperCombo, fight/run.rs combo_at and
fight/pellet.rs: the multiplier is read before the hit is counted, every
landing direct pellet counts once, and the count drops by one per decay
period without a landing hit.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ZOOM_SOURCE = 'zoom:'


@lru_cache(maxsize=1)
def reference():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return json.loads((root / "data/mechanics/sniper-mechanics.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"weapons": {}}


def entry(weapon):
    return (reference().get("weapons") or {}).get(str(weapon.get("path") or ""))


def _incarnon(weapon, fire_mode):
    modes = weapon.get("fireModes") or ()
    mode = modes[fire_mode] if 0 <= fire_mode < len(modes) else {}
    return bool(weapon.get("isIncarnonForm") or mode.get("isIncarnonForm"))


def zoom_effects(weapon, fire_mode, scenario):
    """The top zoom level's buffs as engine effects, or () when not scoped.

    A sniper rifle is evaluated scoped (its combo and zoom are only paid
    scoped in); any other weapon's aim bonus follows ``scenario.aiming``.
    Incarnon forms get none, as in WFSim.
    """
    from .damage import ModEffect
    row = entry(weapon)
    zoom = (row or {}).get("zoom") or {}
    if not zoom.get("effects") or _incarnon(weapon, fire_mode):
        return ()
    if zoom.get("aimGated") and not getattr(scenario, "aiming", False):
        return ()
    source = ZOOM_SOURCE + str(weapon.get("path"))
    return tuple(ModEffect(e["upgradeType"], e["operation"], float(e["value"]),
                           damage_type=e.get("damageType"), source_path=source)
                 for e in zoom["effects"])


def combo_spec(weapon):
    combo = (entry(weapon) or {}).get("combo")
    if not combo:
        return None
    return dict(min=int(combo["min"]), tierBonus=float(combo["tierBonus"]),
                tierFactor=float(combo["tierFactor"]), seconds=float(combo["seconds"]))


def multiplier(spec, hits):
    """1 below the minimum, then +tierBonus per tier (min, min*3, min*9, ...)."""
    hits = math.floor(hits + 1e-9)
    if spec["min"] <= 0 or hits < spec["min"]:
        return 1.0
    threshold, value = spec["min"], 1.0 + spec["tierBonus"]
    while hits >= threshold * spec["tierFactor"]:
        threshold *= spec["tierFactor"]
        value += spec["tierBonus"]
    return value


@dataclass
class ShotCombo:
    spec: dict
    count: float = 0.
    last_hit: float = 0.

    def at(self, t):
        seconds = self.spec["seconds"]
        if seconds <= 0:
            return self.count
        lost = math.floor((t - self.last_hit) / seconds + 1e-9)
        return max(0., self.count - lost) if lost > 0 else self.count

    def shot(self, t, pellets):
        """Mean multiplier over this shot's landing pellets, then count them.

        Pellet i of the shot reads the count after the i pellets before it;
        a fractional pellet count is the expected mix of floor/ceil pellets.
        """
        now = self.at(t)
        pellets = max(float(pellets), 0.)
        whole = math.floor(pellets)
        part = pellets - whole
        total = sum(multiplier(self.spec, now + i) for i in range(whole))
        total += part * multiplier(self.spec, now + whole)
        factor = total / pellets if pellets > 0 else multiplier(self.spec, now)
        if pellets > 0:
            self.count, self.last_hit = now + pellets, t
        return factor
