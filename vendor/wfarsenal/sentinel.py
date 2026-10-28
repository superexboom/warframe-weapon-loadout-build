"""Robotic sentinel bodies: stats, MOD capacity and the MODs that reach the weapon.

Data: data/mechanics/sentinels.json (tools/import_sentinels.py). The sentinel
body is never auto-built; its MODs are user-picked. What this module returns:

* ``stats`` -- rank-30 health / shield / armour (wiki Sentinel Base/Max tables:
  max = 3.5x base) times the body MODs (Enhanced Vitality, Calculated
  Redirection, Metal Fiber, Accelerated Deflection ...);
* ``weaponEffects`` -- engine ModEffects for the companion weapon from the body
  MODs that change its damage, each from its own script parameters
  (``*PerRank`` values count rank + 1 levels):

  - Fired Up (FiredUp.lua OnHit): +Heat per hit up to its script cap,
    reset after the script's no-hit duration. The static panel previews the
    cap; manual_combat turns the marker into an event buff starting empty
    (unless the caller explicitly selects assumed_max);
  - Astral Bond (VoidVinculum.lua ApplyUpgrade): +damage and +Void for 10 s
    after Operator damage -- switch ``astralBond`` (default off);
  - Momentous Bond (EximusHunter.lua): +a random element for 30 s after an
    Eximus kill -- ``momentousElement`` names the element (default off).

Everything else on the body (precepts, Bonds that act on the Warframe, Link
MODs sentinels cannot use) is listed, not modelled: docs table in
BATCH-2026-10-21.md.
"""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .damage import ModEffect, ModEffectList
from .simulator import SimulationError

MAX_RANK_SCALE = 3.5
CAPACITY = 30
REACTOR_CAPACITY = 60
SLOT_COUNT = 10
# wiki Sentinel: "Cannot use Link Vitality, Link Redirection, or Link Fiber."
SENTINEL_BLOCKED = frozenset({
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkArmourMaxMod",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkHealthMaxMod",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowLinkShieldMaxMod",
})
FIRED_UP = "/Lotus/Upgrades/Mods/Sentinel/SentinelOverheatDamageMod"
ASTRAL_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum"
MOMENTOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/EximusHunter"
# Precepts that make the sentinel fire its weapon (wiki: "By default,
# sentinels do not attack enemies unless an attack precept like Assault Mode
# is installed").
ATTACK_PRECEPTS = frozenset({
    "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack",      # Assault Mode
    "/Lotus/Types/Sentinels/SentinelPrecepts/HeadShot",            # Calculated Shot (Diriga)
    "/Lotus/Types/Sentinels/SentinelPrecepts/Thumper",             # Thumper (Djinn)
    "/Lotus/Types/Sentinels/SentinelPrecepts/ThrowGlaivePrecept",  # Targeting Receptor (Helios)
})
ELEMENTS = ("DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON")
STAT_UPGRADES = {
    "AVATAR_HEALTH_MAX": "health",
    "AVATAR_SHIELD_MAX": "shield",
    "AVATAR_ARMOUR": "armor",
    "AVATAR_SHIELD_RECHARGE_RATE": "shieldRecharge",
    "AVATAR_SHIELD_RECHARGE_DELAY": "shieldDelay",
}


@lru_cache(maxsize=1)
def data() -> dict[str, Any]:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    raw = json.loads((root / "data/mechanics/sentinels.json").read_text(encoding="utf-8"))
    mods = [m for m in raw["mods"] if m["path"] not in SENTINEL_BLOCKED]
    return {
        "sentinels": {s["path"]: s for s in raw["sentinels"]},
        "mods": {m["path"]: m for m in mods},
    }


def _script(mod: Mapping[str, Any], function: str) -> dict[str, float]:
    return next((b["params"] for b in mod.get("scripts") or () if b["function"] == function), {})


def weapon_role(path: str) -> str | None:
    """How a body MOD reaches the weapon: 'modelled' / None (not at all)."""
    return "modelled" if path in (FIRED_UP, ASTRAL_BOND, MOMENTOUS_BOND) else None


def catalog() -> dict[str, Any]:
    """Picker rows for the frontend."""
    rows = data()
    return {
        "sentinels": [
            {k: s[k] for k in ("path", "nameEn", "nameZh", "portrait", "prime", "health", "shield", "armor", "slots",
                               "defaultWeapon", "incompatibleWeapons", "defaultPrecepts")}
            for s in rows["sentinels"].values()
        ],
        "mods": [
            {**{k: m[k] for k in ("path", "nameEn", "nameZh", "kind", "exclusiveTo", "rarity", "polarity", "baseDrain",
                                  "maxRank", "art", "levelStatsEn", "levelStatsZh", "modSet")},
             "attack": m["path"] in ATTACK_PRECEPTS, "weaponRole": weapon_role(m["path"])}
            for m in rows["mods"].values()
        ],
        "capacity": {"base": CAPACITY, "reactor": REACTOR_CAPACITY, "slots": SLOT_COUNT, "maxRankScale": MAX_RANK_SCALE},
    }


def weapon_compatible(sentinel: Mapping[str, Any], weapon: Mapping[str, Any]) -> bool:
    family = {str(p) for p in (weapon.get("path"), *(weapon.get("ancestry") or ())) if p}
    return not family & set(sentinel.get("incompatibleWeapons") or ())


FORMA_POLARITIES = ("AP_UNIVERSAL", "AP_ATTACK", "AP_DEFENSE", "AP_TACTIC", "AP_POWER", "AP_WARD", "AP_PRECEPT", "AP_UMBRA", "AP_ANY")


def _native(sentinel: Mapping[str, Any], index: int) -> str | None:
    slots = sentinel.get("slots") or ()
    return slots[index] if index < len(slots) else None


def _drain(mod: Mapping[str, Any], rank: int, slot_polarity: str | None) -> int:
    drain = int(mod.get("baseDrain") or 0) + rank
    if not slot_polarity or not mod.get("polarity") or "AP_UNIVERSAL" in (slot_polarity, mod["polarity"]):
        return drain
    if slot_polarity == mod["polarity"] or "AP_ANY" in (slot_polarity, mod["polarity"]):
        return math.ceil(drain / 2)
    return math.ceil(drain * 1.25)


def _request(request: Any) -> tuple[Mapping[str, Any], list[tuple[Mapping[str, Any], int, int]], dict[str, Any]]:
    if not isinstance(request, Mapping):
        raise SimulationError("sentinel must be an object")
    rows = data()
    sentinel = rows["sentinels"].get(str(request.get("path") or ""))
    if sentinel is None:
        raise SimulationError("sentinel.path is not a known robotic sentinel")
    raw = request.get("mods") or []
    if not isinstance(raw, list) or len(raw) > SLOT_COUNT:
        raise SimulationError(f"sentinel.mods must be an array of at most {SLOT_COUNT} entries")
    mods, seen = [], set()
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise SimulationError(f"sentinel.mods[{index}] must be an object")
        mod = rows["mods"].get(str(item.get("path") or ""))
        if mod is None:
            raise SimulationError(f"sentinel.mods[{index}] is not a sentinel MOD")
        if mod["exclusiveTo"] and sentinel["path"] not in mod["exclusiveTo"]:
            raise SimulationError(f"{mod['nameZh']} 是其他守护的专属 MOD")
        if mod["path"] in seen:
            raise SimulationError(f"{mod['nameZh']} 不能重复装备")
        seen.add(mod["path"])
        rank = item.get("rank", mod["maxRank"])
        if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= mod["maxRank"]:
            raise SimulationError(f"sentinel.mods[{index}].rank must be 0-{mod['maxRank']}")
        slot = item.get("slot", index)
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < SLOT_COUNT:
            raise SimulationError(f"sentinel.mods[{index}].slot must be 0-{SLOT_COUNT - 1}")
        mods.append((mod, rank, slot))
    if len({slot for _, _, slot in mods}) != len(mods):
        raise SimulationError("sentinel.mods slots must be unique")
    options = request.get("options") if isinstance(request.get("options"), Mapping) else {}
    return sentinel, mods, {**options, "slotPolarities": _slot_polarities(sentinel, request.get("polarities"))}


def _slot_polarities(sentinel: Mapping[str, Any], raw: Any) -> list[str | None]:
    """Native slot polarities with the user's forma overrides (null entry = keep native)."""
    native = [*(sentinel.get("slots") or ())][:SLOT_COUNT]
    native += [None] * (SLOT_COUNT - len(native))
    if raw is None:
        return native
    if not isinstance(raw, list) or len(raw) > SLOT_COUNT:
        raise SimulationError(f"sentinel.polarities must be an array of at most {SLOT_COUNT} entries")
    result = list(native)
    for index, value in enumerate(raw):
        if value is None:
            continue
        if value not in FORMA_POLARITIES:
            raise SimulationError(f"sentinel.polarities[{index}] is not a polarity")
        result[index] = None if value == "AP_UNIVERSAL" else value
    return result


def weapon_effects(request: Any, weapon: Mapping[str, Any]) -> tuple[ModEffectList, list[str]]:
    """ModEffects the body MODs add to the companion weapon, plus notes."""
    sentinel, mods, options = _request(request)
    notes = []
    if not weapon_compatible(sentinel, weapon):
        raise SimulationError(f"{sentinel['nameZh']} 不能装备这把武器")
    if not any(mod["path"] in ATTACK_PRECEPTS for mod, _, _ in mods):
        notes.append("sentinel-no-attack-precept: 没有装备攻击类守护 MOD（如突击模式），游戏中守护不会开火")
    effects = []
    for mod, rank, _slot in mods:
        levels = rank + 1
        source = f"sentinel:{mod['path']}"
        if mod["path"] == FIRED_UP and options.get("firedUp", True) is not False:
            params = _script(mod, "OnHit")
            cap = params.get("_maxDamagePctPerLevel", 0.0) * levels
            per_hit = params.get("_damagePctPerHitPerLevel", 0.0) * levels
            duration = params.get("_duration", 0.0)
            if min(cap, per_hit, duration) <= 0.0:
                notes.append("sentinel-fired-up-script-parameters-unavailable")
                continue
            effects.append(ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", cap,
                                     damage_type="DT_FIRE", source_path=source,
                                     runtime_kind="sentinel-fired-up", runtime_chance=per_hit,
                                     runtime_threshold=duration, runtime_multiplier=cap))
            notes.append("sentinel-fired-up-panel-shows-cap; replay-starts-empty-and-resets-after-no-hit-duration")
        elif mod["path"] == ASTRAL_BOND and options.get("astralBond") is True:
            params = _script(mod, "ApplyUpgrade")
            effects.append(ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", params.get("_damagePctPerRank", 0.0) * levels,
                                     source_path=source))
            effects.append(ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "STACKING_MULTIPLY",
                                     params.get("_voidDamagePctPerRank", 0.0) * levels, damage_type="DT_RADIANT",
                                     source_path=source))
        elif mod["path"] == MOMENTOUS_BOND and options.get("momentousElement") in ELEMENTS:
            params = _script(mod, "ApplyEximusHunter")
            effects.append(ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY",
                                     params.get("_bonusDamagePerRank", 0.0) * levels,
                                     damage_type=options["momentousElement"], source_path=source))
    return ModEffectList(effects), notes


def evaluate(request: Any, *, reactor: bool = True) -> dict[str, Any]:
    """Body panel: rank-30 stats, MOD bonuses, capacity per slot."""
    sentinel, mods, options = _request(request)
    polarities = options["slotPolarities"]
    base = {key: float(sentinel[key]) * MAX_RANK_SCALE for key in ("health", "shield", "armor")}
    bonus = {"health": 0.0, "shield": 0.0, "armor": 0.0, "shieldRecharge": 0.0, "shieldDelay": 0.0}
    capacity = REACTOR_CAPACITY if reactor else CAPACITY
    used, slots = 0, []
    for mod, rank, slot in mods:
        polarity = polarities[slot]
        drain = _drain(mod, rank, polarity)
        used += drain
        slots.append({"slot": slot, "path": mod["path"], "rank": rank, "drain": drain, "slotPolarity": polarity})
        for upgrade in mod.get("upgrades") or ():
            key = STAT_UPGRADES.get(upgrade["type"])
            if key and upgrade["operation"] == "STACKING_MULTIPLY":
                bonus[key] += float(upgrade["value"]) * (rank + 1)
    stats = {key: {"base": value, "modded": value * (1.0 + bonus[key])} for key, value in base.items()}
    stats["shieldRecharge"] = {"base": 0.0, "modded": bonus["shieldRecharge"]}
    stats["shieldDelay"] = {"base": 0.0, "modded": bonus["shieldDelay"]}
    return {
        "sentinel": sentinel["path"],
        "stats": stats,
        "capacity": {"used": used, "total": capacity},
        "slots": slots,
        "slotPolarities": polarities,
        "formaCount": sum(1 for index, value in enumerate(polarities) if value != _native(sentinel, index)),
        "attackPrecept": any(mod["path"] in ATTACK_PRECEPTS for mod, _, _ in mods),
        "weaponMods": [mod["path"] for mod, _, _ in mods if weapon_role(mod["path"])],
    }
