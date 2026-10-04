"""Sniper Shot Combo Counter and scope zoom bonuses.

The game export carries neither mechanic, so the per-weapon numbers come from
``data/mechanics/sniper-profiles.json`` (imported from WFSim weapon YAML by
``tools/import_sniper_profiles.py``, provenance per row). Semantics mirror WFSim
engine/src/model/weapon.rs ``SniperCombo`` and fight/run.rs ``combo_at``:

* thresholds are ``min * 3**k`` and the multiplier ``1.5 + 0.5k``; below the
  minimum the counter pays nothing;
* each landing direct pellet reads the counter as it stood, then adds one, so
  the hit that reaches the minimum arms it rather than spends it;
* the counter loses one per ``seconds`` without a landing hit (it does not
  reset), and a shot that lands nothing empties it;
* both the counter and the scope exist only while aiming, and only on the
  base form (no source says either survives an Incarnon transform).

The replay is expected-value, so a fractional multishot leaves the integer
counter uncertain; it is tracked as a distribution over counts.
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def profiles():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    path = root / "data/mechanics/sniper-profiles.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("weapons") or {}


def profile(weapon):
    return profiles().get(str((weapon or {}).get("path") or "")) or {}


def scope_effects(weapon, fire_mode=0):
    """Aim-gated scope terms as ordinary bucket effects, plus the Lanka's
    post-mod flat crit chance (which is not a bucket term)."""
    from .damage import ModEffect

    mode = ((weapon.get("fireModes") or [{}])[fire_mode:fire_mode + 1] or [{}])[0]
    scope = profile(weapon).get("scope")
    if not scope or weapon.get("isIncarnonForm") or mode.get("isIncarnonForm"):
        return [], 0.0
    source = "scope:" + str(weapon.get("path"))
    # "These zoom buffs ... generally stack additively with similar buffs from
    # mods" (wiki Sniper Rifle via WFSim build/loadout/resolve.rs).
    effects = [
        ModEffect(kind, "STACKING_MULTIPLY", float(scope[key]), source_path=source)
        for kind, key in (
            ("WEAPON_CRIT_DAMAGE", "critMultiplier"),
            ("WEAPON_CRIT_CHANCE", "critChance"),
            ("WEAPON_HEADSHOT_MULTIPLIER", "headshotDamage"),
        )
        if scope.get(key)
    ]
    return effects, float(scope.get("critChancePostMod") or 0.0)


def combat_configuration(weapon, scenario):
    """The replay's counter spec, or None when this fight cannot build one."""
    combo = profile(weapon).get("sniperCombo")
    if not combo or not scenario.aiming:
        return None
    return {"minimum": int(combo["min"]), "seconds": float(combo["seconds"])}


def multiplier(minimum, hits):
    # Walked, not log3: a power of three must land on its own tier.
    if minimum <= 0 or hits < minimum:
        return 1.0
    threshold, value = minimum, 1.5
    while hits >= threshold * 3:
        threshold *= 3
        value += 0.5
    return value


class ShotCombo:
    def __init__(self, minimum, seconds):
        self.minimum = int(minimum)
        self.seconds = float(seconds)
        self.counts = {0: 1.0}
        self.last_hit = 0.0

    def at(self, time):
        lost = math.floor(max(0.0, time - self.last_hit) / self.seconds + 1e-9) if self.seconds > 0 else 0
        if lost <= 0:
            return dict(self.counts)
        out = {}
        for count, weight in self.counts.items():
            key = max(0, count - lost)
            out[key] = out.get(key, 0.0) + weight
        return out

    def expected(self, time):
        return sum(count * weight for count, weight in self.at(time).items())

    def shot(self, time, pellets):
        """Count one trigger pull of ``pellets`` expected landing pellets and
        return the mean per-pellet multiplier it was paid at."""
        pellets = max(float(pellets), 0.0)
        whole = math.floor(pellets + 1e-9)
        part = max(0.0, pellets - whole)
        if part < 1e-9:
            part = 0.0
        before = self.at(time)
        paid = 0.0
        after = {}
        for count, weight in before.items():
            paid += weight * (sum(multiplier(self.minimum, count + i) for i in range(whole))
                              + part * multiplier(self.minimum, count + whole))
            for landed, chance in ((whole, 1.0 - part), (whole + 1, part)):
                if chance <= 0.0:
                    continue
                key = count + landed if landed else 0
                after[key] = after.get(key, 0.0) + weight * chance
        self.counts = after
        self.last_hit = time
        return paid / pellets if pellets > 0 else 1.0
