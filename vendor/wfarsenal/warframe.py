"""Small, deterministic Warframe build evaluator.

This module deliberately does not share the weapon damage kernel.  Warframes
need slot/capacity validation and panel/ability scaling, but have no target or
kill simulation in the portable app.  The generated sidecar is the source of
truth; the optional export fallback is only useful for catalog discovery when
the sidecar has not been generated yet.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .simulator import SimulationError, _polarity_adjusted_drain


DEFAULT_CAPACITY = 60
NORMAL_SLOT_COUNT = 8
ARCANE_SLOT_COUNT = 2
SHARD_SLOT_COUNT = 5
ABILITY_SLOT_COUNT = 4


_STAT_ALIASES = {
    "AVATAR_HEALTH_MAX": "health",
    "HEALTH": "health",
    "BASEHEALTH": "health",
    "AVATAR_SHIELD_MAX": "shield",
    "SHIELD": "shield",
    "BASESHIELD": "shield",
    "AVATAR_ARMOUR": "armor",
    "AVATAR_ARMOR": "armor",
    "ARMOUR": "armor",
    "ARMOR": "armor",
    "BASEARMOUR": "armor",
    "BASEARMOR": "armor",
    "AVATAR_POWER_MAX": "energy",
    "AVATAR_MAX_ENERGY": "energy",
    "AVATAR_ENERGY_MAX": "energy",
    "ENERGY": "energy",
    "BASEENERGY": "energy",
    "AVATAR_MOVEMENT_SPEED": "sprint",
    "AVATAR_SPRINT_SPEED": "sprint",
    "SPRINT": "sprint",
    "MOVEMENTSPEED": "sprint",
    "AVATAR_ABILITY_STRENGTH": "abilityStrength",
    "AVATAR_POWER_STRENGTH": "abilityStrength",
    "ABILITY_STRENGTH": "abilityStrength",
    "POWER_STRENGTH": "abilityStrength",
    "AVATAR_ABILITY_DURATION": "abilityDuration",
    "AVATAR_POWER_DURATION": "abilityDuration",
    "ABILITY_DURATION": "abilityDuration",
    "POWER_DURATION": "abilityDuration",
    "AVATAR_ABILITY_RANGE": "abilityRange",
    "AVATAR_POWER_RANGE": "abilityRange",
    "ABILITY_RANGE": "abilityRange",
    "POWER_RANGE": "abilityRange",
    "AVATAR_ABILITY_EFFICIENCY": "abilityEfficiency",
    "AVATAR_POWER_EFFICIENCY": "abilityEfficiency",
    "ABILITY_EFFICIENCY": "abilityEfficiency",
    "POWER_EFFICIENCY": "abilityEfficiency",
    "AVATAR_POWER_RATE": "energyRegen",
    "AVATAR_ENERGY_REGEN": "energyRegen",
    "AVATAR_HEALTH_REGEN": "healthRegen",
    "AVATAR_CASTING_SPEED": "castingSpeed",
    "AVATAR_PARKOUR_BOOST": "parkour",
    "AVATAR_PARKOUR_VELOCITY": "parkour",
}

_BASE_STATS = frozenset({"health", "shield", "armor", "energy", "sprint"})
_ABILITY_STATS = frozenset(
    {"abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency"}
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _token(value: Any) -> str:
    return str(value or "").strip().casefold()


def _path_token(value: Any) -> str:
    return _token(value).replace("\\", "/").rstrip("/")


def _invigoration_restricted(row: Mapping[str, Any], frame: Mapping[str, Any]) -> bool:
    restrictions = row.get("restrictions") or row.get("ineligible") or ()
    if isinstance(restrictions, str):
        restrictions = [restrictions]
    frame_names = {_token(frame.get(key)) for key in ("id", "path", "nameEn", "nameZh", "nameInternal")}
    frame_paths = {
        _path_token(frame.get(key))
        for key in ("id", "path")
        if isinstance(frame.get(key), str) and "/" in str(frame.get(key))
    }
    frame_families = {path.rsplit("/", 1)[0] for path in frame_paths}
    if any(_token(value) in frame_names for value in restrictions if isinstance(value, str)):
        return True
    explicit_paths = row.get("restrictionFramePaths") or ()
    if isinstance(explicit_paths, str):
        explicit_paths = [explicit_paths]
    if any(_path_token(value) in frame_paths for value in explicit_paths if isinstance(value, str)):
        return True

    # UpgradeExceptions names the non-playable *BaseSuit object. The folder is
    # the stable Warframe family identifier and therefore covers Prime variants.
    for value in restrictions:
        path = _path_token(value)
        if path.endswith("basesuit") and "/" in path and path.rsplit("/", 1)[0] in frame_families:
            return True
    families = row.get("restrictionFamilies") or ()
    if isinstance(families, str):
        families = [families]
    return any(_path_token(value) in frame_families for value in families if isinstance(value, str))


def _polarity(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError("polarity tokens must be strings or null")
    value = value.strip().upper()
    if not value or value in {"AP_UNIVERSAL", "AP_NONE", "NONE", "NULL"}:
        return None
    return value


def _empty_catalog(status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "buildLabel": None,
        "status": status,
        "provenance": {},
        "counts": {"warframes": 0, "mods": 0, "arcanes": 0, "helminth": 0, "invigoration": 0, "shards": 0},
        "warframes": [],
        "abilities": [],
        "mods": [],
        "arcanes": [],
        "helminth": [],
        "invigoration": [],
        "shards": [],
        "gaps": [error] if error else [],
    }


def _fallback_catalog(exports: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only discoverable export rows when the generated sidecar is absent."""
    frames: list[dict[str, Any]] = []
    for source in exports.get("warframes") or ():
        if not isinstance(source, Mapping) or not source.get("path"):
            continue
        abilities = []
        for index, ability_path in enumerate(source.get("abilities") or ()):
            if not isinstance(ability_path, str) or not ability_path:
                continue
            abilities.append({"id": ability_path, "path": ability_path, "slot": index, "nameEn": ability_path.rsplit("/", 1)[-1], "nameZh": "", "description": "", "scalars": []})
        frames.append(
            {
                "id": source.get("path"),
                "path": source.get("path"),
                "nameEn": source.get("nameEn") or source.get("nameInternal") or source.get("name"),
                "nameZh": source.get("nameZh") or source.get("nameEn") or source.get("name"),
                "iconAsset": source.get("iconAsset"),
                "portraitAsset": source.get("portraitAsset"),
                "basePanel": {key: source.get(key) for key in ("health", "shield", "armour", "armor") if source.get(key) is not None},
                "rank30Panel": {},
                # A flat ArtifactSlots list has no reliable semantic order.
                "slotPolarities": None,
                "abilities": abilities,
                "passive": source.get("passive") or source.get("passiveTag") or "",
            }
        )
    mods = []
    for source in exports.get("mods") or ():
        compatibility = str(source.get("compatibility") or "")
        support = source.get("support") if isinstance(source.get("support"), Mapping) else {}
        if "PlayerPowerSuit" not in compatibility and not support.get("warframe"):
            continue
        mods.append(dict(source))
    arcanes = []
    for source in exports.get("arcanes") or ():
        if "PlayerPowerSuit" in str(source.get("compatibility") or ""):
            arcanes.append(dict(source))
    result = _empty_catalog("fallback")
    result.update(
        {
            "buildLabel": exports.get("buildLabel"),
            "provenance": {"source": "frozen-export", "slotSemantics": "unavailable"},
            "warframes": frames,
            "mods": mods,
            "arcanes": arcanes,
            "abilities": [ability for frame in frames for ability in frame.get("abilities") or ()],
            "counts": {"warframes": len(frames), "mods": len(mods), "arcanes": len(arcanes), "helminth": 0, "invigoration": 0, "shards": 0},
            "gaps": ["generated sidecar is missing", "warframe slot polarities are unavailable in the flat export"],
        }
    )
    return result


def load_warframe_catalog(path: str | Path, *, fallback: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Load and minimally validate the generated sidecar.

    Missing or malformed data never prevents the weapon application from
    starting.  The returned status is ``missing``/``invalid`` and calculation
    raises a normal ``SimulationError`` until a valid sidecar is installed.
    """
    path = Path(path)
    if not path.is_file():
        return _fallback_catalog(fallback or {}) if fallback else _empty_catalog("missing", f"missing warframe sidecar: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return _empty_catalog("invalid", f"cannot read warframe sidecar: {exc}")
    if not isinstance(payload, Mapping):
        return _empty_catalog("invalid", "warframe sidecar must be a JSON object")
    if payload.get("schemaVersion") != 1:
        return _empty_catalog("invalid", f"unsupported warframe sidecar schemaVersion: {payload.get('schemaVersion')!r}")
    expected_build = fallback.get("buildLabel") if isinstance(fallback, Mapping) else None
    if expected_build is not None and payload.get("buildLabel") != expected_build:
        return _empty_catalog("invalid", f"warframe sidecar buildLabel does not match frozen export: {payload.get('buildLabel')!r} != {expected_build!r}")
    required = ("warframes", "mods", "arcanes", "helminth", "invigoration", "shards")
    if any(not isinstance(payload.get(key), list) for key in required):
        return _empty_catalog("invalid", "warframe sidecar arrays are incomplete")
    result = dict(payload)
    result.setdefault("schemaVersion", 1)
    result.setdefault("status", "ready")
    result.setdefault("provenance", {})
    result.setdefault("abilities", [])
    result.setdefault("modSets", {})
    result.setdefault("gaps", [])
    result["counts"] = {
        key: len(result.get(key) or ())
        for key in ("warframes", "mods", "arcanes", "helminth", "invigoration", "shards")
    }
    return result


def _row_id(row: Mapping[str, Any]) -> str:
    return str(row.get("id") or row.get("path") or row.get("nameInternal") or "").strip()


def _resolve(rows: Sequence[Mapping[str, Any]], query: Any, kind: str) -> Mapping[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise SimulationError(f"{kind} must be a non-empty id/path")
    wanted = query.strip().casefold()
    matches = [
        row
        for row in rows
        if any(_token(row.get(key)) == wanted for key in ("id", "path", "nameEn", "nameZh", "nameInternal"))
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SimulationError(f"{kind} not found: {query}")
    raise SimulationError(f"ambiguous {kind}; use an exact path: {query}")


def _choice(value: Any, kind: str) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return {"path": value}
    if not isinstance(value, Mapping):
        raise SimulationError(f"{kind} must be an object or null")
    return value


def _rank(card: Mapping[str, Any], supplied: Any, label: str) -> int:
    maximum = card.get("maxRank")
    if maximum is None:
        maximum = card.get("rank")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
        maximum = 0
    value = maximum if supplied is None else supplied
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise SimulationError(f"{label}.rank must be an integer from 0 to {maximum}")
    return value


def _card_drain(card: Mapping[str, Any], rank: int, *, slot_kind: str | None = None) -> tuple[int, int]:
    raw_base = card.get("baseDrain")
    if raw_base is None:
        raw_base = card.get("drain")
    if isinstance(raw_base, bool) or not isinstance(raw_base, (int, float)) or not math.isfinite(float(raw_base)):
        raise SimulationError(f"{_row_id(card) or 'MOD'} has no valid baseDrain")
    base = abs(int(raw_base))
    raw = base + rank
    kind = slot_kind or str(card.get("slotKind") or "")
    if kind.casefold() == "aura":
        raw = -raw
    return int(raw), int(base)


def _set_id(card: Mapping[str, Any]) -> str | None:
    value = card.get("modSet") or card.get("setId")
    if isinstance(card.get("set"), Mapping):
        value = card["set"].get("id") or card["set"].get("path") or value
    elif isinstance(card.get("set"), str):
        value = card.get("set")
    value = str(value or "").strip().replace("\\", "/").rstrip("/").casefold()
    return value or None


def _set_multiplier(card: Mapping[str, Any], pieces: int) -> float:
    values = card.get("modSetValues")
    if isinstance(card.get("set"), Mapping):
        values = card["set"].get("values") or card["set"].get("modSetValues") or values
    if not isinstance(values, (list, tuple)) or pieces < 2:
        return 1.0
    index = min(pieces - 2, len(values) - 1)
    value = _number(values[index])
    if value is None:
        return 1.0
    return max(0.0, 1.0 + value)


def _effect_stat(effect: Mapping[str, Any]) -> str | None:
    value = effect.get("stat") or effect.get("upgradeType") or effect.get("upgrade_type") or effect.get("id")
    key = str(value or "").replace("-", "_").replace(" ", "_").upper()
    return _STAT_ALIASES.get(key) or (str(value) if value in _BASE_STATS | _ABILITY_STATS else None)


def _effect_value(effect: Mapping[str, Any], rank: int) -> float | None:
    for key in ("values", "valuesByRank", "valueByRank", "amounts"):
        values = effect.get(key)
        if isinstance(values, (list, tuple)) and values:
            number = _number(values[min(rank, len(values) - 1)])
            if number is not None:
                return number
    per_rank = _number(effect.get("valuePerRank"))
    if per_rank is not None:
        return per_rank * (rank + 1)
    for key in ("value", "amount", "baseValue"):
        number = _number(effect.get(key))
        if number is not None:
            return number
    return None


def _effects(card: Mapping[str, Any], rank: int, *, conditionals: bool, source: str, set_multiplier: float = 1.0) -> Iterable[dict[str, Any]]:
    rows = card.get("effects")
    if isinstance(rows, Mapping):
        rows = [rows]
    for effect in rows or ():
        if not isinstance(effect, Mapping):
            continue
        value = _effect_value(effect, rank)
        stat = _effect_stat(effect)
        if stat is not None and value is not None:
            yield {"stat": stat, "value": value * set_multiplier, "operation": effect.get("operation") or effect.get("mode") or "ADD", "source": source, "label": effect.get("label") or effect.get("upgradeType") or stat}
    if not conditionals:
        return
    condition_rows = card.get("conditionalEffects")
    if isinstance(condition_rows, Mapping):
        condition_rows = [condition_rows]
    for conditional in condition_rows or ():
        if not isinstance(conditional, Mapping):
            continue
        stacks = conditional.get("maxStacks")
        stacks = stacks if isinstance(stacks, int) and stacks > 0 else 1
        nested = conditional.get("effects")
        if isinstance(nested, Mapping):
            nested = [nested]
        for effect in nested or ():
            if not isinstance(effect, Mapping):
                continue
            value = _effect_value(effect, rank)
            stat = _effect_stat(effect)
            if stat is not None and value is not None:
                yield {"stat": stat, "value": value * stacks * set_multiplier, "operation": effect.get("operation") or effect.get("mode") or "ADD", "source": source, "label": effect.get("label") or effect.get("upgradeType") or stat, "conditional": True, "condition": conditional.get("conditionTag") or conditional.get("condition")}


def _is_percent(effect: Mapping[str, Any], value: float) -> bool:
    mode = str(effect.get("mode") or effect.get("operation") or "ADD").upper()
    unit = str(effect.get("unit") or "").casefold()
    if mode in {"ADD_BASE", "FLAT", "SET_BASE"} or unit in {"flat", "points", "absolute"}:
        return False
    if "MULTIPLY" in mode:
        return True
    if unit in {"%", "percent", "percentage"}:
        return True
    # Plain ADD is overloaded by the export. Invigoration health uses a large
    # flat value while legacy percentage rows use fractional values.
    return abs(value) < 1.0


def _panel_seed(frame: Mapping[str, Any]) -> dict[str, float]:
    source = frame.get("rank30Panel") if isinstance(frame.get("rank30Panel"), Mapping) else {}
    if not source:
        source = frame.get("stats") if isinstance(frame.get("stats"), Mapping) else {}
    if not source:
        source = frame.get("basePanel") if isinstance(frame.get("basePanel"), Mapping) else {}
    result = {
        "health": float(_number(source.get("health")) or 0),
        "shield": float(_number(source.get("shield")) or 0),
        "armor": float(_number(source.get("armor")) or _number(source.get("armour")) or 0),
        "energy": float(_number(source.get("energy")) or 0),
        "sprint": float(_number(source.get("sprint")) or _number(source.get("movementSpeed")) or 0),
    }
    return result


def _slot_polarities(frame: Mapping[str, Any], override: Any) -> tuple[str | None, str | None, list[str | None]]:
    source = frame.get("slotPolarities")
    if not isinstance(source, Mapping):
        source = frame.get("polarities") if isinstance(frame.get("polarities"), Mapping) else None
    aura = source.get("aura") if isinstance(source, Mapping) else None
    exilus = source.get("exilus") if isinstance(source, Mapping) else None
    ordinary = source.get("normal") if isinstance(source, Mapping) else None
    if isinstance(override, Mapping):
        aura = override.get("aura", aura)
        exilus = override.get("exilus", exilus)
        ordinary = override.get("normal", override.get("ordinary", ordinary))
    elif isinstance(override, (list, tuple)):
        ordinary = override
    if not isinstance(ordinary, (list, tuple)) or len(ordinary) < NORMAL_SLOT_COUNT:
        raise SimulationError("warframe slot polarity data is incomplete; generate the explicit sidecar first")
    return _polarity(aura), _polarity(exilus), [_polarity(value) for value in ordinary[:NORMAL_SLOT_COUNT]]


def _frame_compatible(card: Mapping[str, Any], frame: Mapping[str, Any]) -> bool:
    explicit = card.get("frameIds") or card.get("warframes") or card.get("compatibleFrames")
    if isinstance(explicit, str):
        explicit = [explicit]
    if isinstance(explicit, (list, tuple)) and explicit:
        def families(value: Any) -> set[str]:
            token = _token(value)
            leaf = token.rsplit("/", 1)[-1]
            return {re.sub(r"[^a-z0-9\u3400-\u9fff]", "", re.sub(r"(?:\s+prime|prime)$", "", part)) for part in (token, leaf) if part}
        names = set().union(*(families(frame.get(key)) for key in ("id", "path", "nameEn", "nameZh", "nameInternal")))
        return any(names.intersection(families(value)) for value in explicit)
    compatibility = card.get("compatibility")
    generic = {"warframe", "normal", "aura", "exilus", "playersuit", "powersuit", "playerpowersuit"}
    if isinstance(compatibility, str) and compatibility and compatibility.casefold() not in generic and "playersuit" not in compatibility.casefold() and "warframe" not in compatibility.casefold():
        # A frame-specific exported compatibility path is allowed only when it
        # actually names this frame; weapon/operator paths are rejected.
        return any(_token(frame.get(key)) in _token(compatibility) for key in ("id", "path", "nameInternal"))
    return True


def _apply_effect(panel: dict[str, dict[str, float]], effect: Mapping[str, Any], active: list[dict[str, Any]]) -> None:
    stat = str(effect.get("stat") or "")
    value = _number(effect.get("value"))
    if value is None or stat not in panel:
        return
    operation = str(effect.get("operation") or "ADD").upper()
    state = panel[stat]
    if operation in {"SET", "SET_BASE"}:
        state["set"] = value
    elif _is_percent(effect, value):
        state["percent"] += value
    else:
        state["flat"] += value
    active.append({key: effect.get(key) for key in ("source", "stat", "value", "label", "conditional", "condition") if effect.get(key) is not None})


class WarframeEngine:
    """Validate and calculate one fixed-rank-30 Warframe build."""

    def __init__(self, catalog: Mapping[str, Any]):
        self.catalog = dict(catalog)
        self.frames = [row for row in self.catalog.get("warframes") or () if isinstance(row, Mapping)]
        self.mods = [row for row in self.catalog.get("mods") or () if isinstance(row, Mapping)]
        self.arcanes = [row for row in self.catalog.get("arcanes") or () if isinstance(row, Mapping)]
        self.helminth = [row for row in self.catalog.get("helminth") or () if isinstance(row, Mapping)]
        self.invigoration = [row for row in self.catalog.get("invigoration") or () if isinstance(row, Mapping)]
        self.shards = [row for row in self.catalog.get("shards") or () if isinstance(row, Mapping)]

    def _resolve_frame(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        query = payload.get("frameId") or payload.get("frame") or payload.get("warframe")
        if not self.frames:
            raise SimulationError("warframe catalog is unavailable; generate data/warframe_build_data.json first")
        return _resolve(self.frames, query, "frameId")

    def _resolve_mod(self, value: Any, kind: str, frame: Mapping[str, Any]) -> tuple[Mapping[str, Any], int, int, str]:
        choice = _choice(value, kind)
        if choice is None:
            raise SimulationError(f"{kind} cannot be null here")
        row = _resolve(self.mods, choice.get("path") or choice.get("id") or choice.get("query"), kind)
        slot_kind = str(row.get("slotKind") or row.get("kind") or row.get("compatibility") or "").casefold()
        aliases = {"normal": {"normal", "warframe", "exilus"}, "aura": {"aura"}, "exilus": {"exilus"}}
        if slot_kind not in aliases.get(kind, {kind}):
            raise SimulationError(f"{kind} requires a {kind} MOD")
        if not _frame_compatible(row, frame):
            raise SimulationError(f"{kind} is not compatible with the selected Warframe")
        rank = _rank(row, choice.get("rank"), kind)
        raw, base = _card_drain(row, rank, slot_kind=slot_kind)
        return row, rank, raw, slot_kind

    def calculate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise SimulationError("warframe request must be a JSON object")
        if self.catalog.get("status") not in {None, "ready"}:
            raise SimulationError("warframe catalog is unavailable; generate the sidecar before calculating")
        if not isinstance(payload.get("applyConditionals", False), bool):
            raise SimulationError("applyConditionals must be a boolean")
        frame = self._resolve_frame(payload)
        aura_pol, exilus_pol, normal_pols = _slot_polarities(frame, payload.get("slotPolarities"))
        selected: list[tuple[Mapping[str, Any], int, int, int | None, str]] = []
        seen: set[str] = set()

        aura_row = aura_rank = aura_raw = None
        if payload.get("aura") is not None:
            aura_row, aura_rank, aura_raw, _ = self._resolve_mod(payload.get("aura"), "aura", frame)
            seen.add(_row_id(aura_row))

        exilus_row = exilus_rank = exilus_raw = None
        if payload.get("exilus") is not None:
            exilus_row, exilus_rank, exilus_raw, _ = self._resolve_mod(payload.get("exilus"), "exilus", frame)
            seen.add(_row_id(exilus_row))

        raw_mods = payload.get("normalMods")
        if raw_mods is None:
            raw_mods = payload.get("mods") or []
        if not isinstance(raw_mods, list) or len(raw_mods) > NORMAL_SLOT_COUNT:
            raise SimulationError(f"normalMods must be an array with at most {NORMAL_SLOT_COUNT} entries")
        occupied: set[int] = set()
        for index, item in enumerate(raw_mods):
            if item is None:
                continue
            row, rank, raw, slot_kind = self._resolve_mod(item, "normal", frame)
            choice = _choice(item, "normalMods") or {}
            slot = choice.get("slot", index)
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < NORMAL_SLOT_COUNT or slot in occupied:
                raise SimulationError(f"normalMods[{index}] has an invalid or duplicate slot")
            path = _row_id(row)
            if path in seen:
                raise SimulationError("the same MOD cannot occupy more than one Warframe slot")
            seen.add(path)
            occupied.add(slot)
            selected.append((row, rank, raw, slot, slot_kind))

        if exilus_row is not None:
            selected.append((exilus_row, int(exilus_rank), int(exilus_raw), NORMAL_SLOT_COUNT, "exilus"))

        capacity = DEFAULT_CAPACITY
        aura_assignment = None
        if aura_row is not None:
            adjusted, relation = _polarity_adjusted_drain(int(aura_raw), aura_row.get("polarity"), aura_pol)
            capacity += -adjusted
            aura_assignment = {"path": _row_id(aura_row), "rank": aura_rank, "rawDrain": aura_raw, "drain": adjusted, "polarityRelation": relation, "slotPolarity": aura_pol}

        assignments: list[dict[str, Any]] = []
        used = 0
        for row, rank, raw, slot, slot_kind in selected:
            slot_pol = exilus_pol if slot == NORMAL_SLOT_COUNT else normal_pols[slot]
            adjusted, relation = _polarity_adjusted_drain(raw, row.get("polarity"), slot_pol)
            used += adjusted
            assignments.append({"path": _row_id(row), "slot": slot, "rank": rank, "rawDrain": raw, "drain": adjusted, "polarityRelation": relation, "slotPolarity": slot_pol, "slotKind": slot_kind})

        raw_arcanes = payload.get("arcanes") or []
        if not isinstance(raw_arcanes, list):
            raise SimulationError("arcanes must be an array")
        if len(raw_arcanes) > ARCANE_SLOT_COUNT:
            raise SimulationError(f"arcanes allow at most {ARCANE_SLOT_COUNT} entries")
        arcane_rows: list[tuple[Mapping[str, Any], int]] = []
        for index, item in enumerate(raw_arcanes):
            if item is None:
                continue
            choice = _choice(item, f"arcanes[{index}]")
            row = _resolve(self.arcanes, choice.get("path") or choice.get("id") or choice.get("query"), f"arcanes[{index}]")
            compatibility = str(row.get("compatibility") or row.get("slotKind") or "")
            if compatibility and not any(token in compatibility.casefold() for token in ("playersuit", "warframe", "powersuit")):
                raise SimulationError("Arcane is not compatible with a Warframe slot")
            path = _row_id(row)
            if path in seen:
                raise SimulationError("the same Arcane/MOD cannot be selected twice")
            seen.add(path)
            arcane_rows.append((row, _rank(row, choice.get("rank"), f"arcanes[{index}]")))

        shard_rows: list[tuple[Mapping[str, Any], int]] = []
        raw_shards = payload.get("shards") or []
        if not isinstance(raw_shards, list):
            raise SimulationError("shards must be an array")
        if len(raw_shards) > SHARD_SLOT_COUNT:
            raise SimulationError(f"shards allow at most {SHARD_SLOT_COUNT} entries")
        for index, item in enumerate(raw_shards):
            if item is None:
                continue
            choice = _choice(item, f"shards[{index}]")
            row = _resolve(self.shards, choice.get("id") or choice.get("path") or choice.get("query"), f"shards[{index}]")
            wanted_tau = choice.get("tau")
            if wanted_tau is not None and not isinstance(wanted_tau, bool):
                raise SimulationError(f"shards[{index}].tau must be a boolean")
            if wanted_tau is not None and bool(row.get("tau")) != bool(wanted_tau):
                raise SimulationError(f"shards[{index}] does not match the requested Tau state")
            shard_rows.append((row, 0))

        active: list[dict[str, Any]] = []
        panel_extras = {"energyRegen", "healthRegen", "castingSpeed", "parkour"}
        panel = {stat: {"flat": 0.0, "percent": 0.0, "set": None} for stat in (*_BASE_STATS, *_ABILITY_STATS, *panel_extras)}
        set_members: list[Mapping[str, Any]] = [row for row, *_ in selected]
        if aura_row is not None:
            set_members.append(aura_row)
        set_counts = Counter(_set_id(row) for row in set_members if _set_id(row))
        set_multipliers: dict[str, float] = {}
        for set_id, pieces in set_counts.items():
            source = next(row for row in set_members if _set_id(row) == set_id)
            set_multipliers[set_id] = _set_multiplier(source, pieces)

        def add_card(row: Mapping[str, Any], rank: int, *, enabled: bool = True) -> None:
            set_id = _set_id(row)
            multiplier = _set_multiplier(row, set_counts.get(set_id, 0)) if set_id else 1.0
            for effect in _effects(row, rank, conditionals=bool(payload.get("applyConditionals")), source=_row_id(row), set_multiplier=multiplier):
                _apply_effect(panel, effect, active)

        if aura_row is not None:
            add_card(aura_row, int(aura_rank))
        for row, rank, _raw, _slot, _kind in selected:
            add_card(row, rank)
        for row, rank in arcane_rows:
            add_card(row, rank)
        for row, _ in shard_rows:
            add_card(row, 0)

        replacement = payload.get("helminthReplacement")
        abilities = [dict(ability) for ability in frame.get("abilities") or () if isinstance(ability, Mapping)]
        if len(abilities) > ABILITY_SLOT_COUNT:
            abilities = abilities[:ABILITY_SLOT_COUNT]
        if replacement is not None:
            if not isinstance(replacement, Mapping):
                raise SimulationError("helminthReplacement must be an object or null")
            slot = replacement.get("slot", replacement.get("index"))
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < ABILITY_SLOT_COUNT:
                raise SimulationError("helminthReplacement.slot must be an integer from 0 to 3")
            query = replacement.get("abilityId") or replacement.get("ability") or replacement.get("id") or replacement.get("path")
            if isinstance(query, Mapping):
                query = query.get("id") or query.get("path")
            ability = dict(_resolve(self.helminth, query, "helminthReplacement"))
            invalid_slots = ability.get("invalidSlots") or ()
            if slot in invalid_slots:
                raise SimulationError("the selected Helminth ability cannot replace that slot")
            altered = ability.get("altered")
            if isinstance(altered, Mapping):
                ability.update(altered)
                ability["altered"] = dict(altered)
            ability["slot"] = slot
            if slot < len(abilities):
                abilities[slot] = ability
            else:
                abilities.extend({} for _ in range(slot - len(abilities) + 1))
                abilities[slot] = ability

        invigoration = payload.get("invigoration")
        invigoration_choices = [] if invigoration is None else (invigoration if isinstance(invigoration, list) else [invigoration])
        if len(invigoration_choices) > 2:
            raise SimulationError("invigoration allows at most 2 effects")
        invigoration_categories: set[str] = set()
        selected_invigorations: list[str] = []
        for index, value in enumerate(invigoration_choices):
            choice = _choice(value, f"invigoration[{index}]")
            row = _resolve(self.invigoration, choice.get("id") or choice.get("path") or choice.get("query"), f"invigoration[{index}]")
            category = str(row.get("category") or "").casefold()
            if category and category in invigoration_categories:
                raise SimulationError("invigoration allows one offensive and one utility effect")
            if category:
                invigoration_categories.add(category)
            if _invigoration_restricted(row, frame):
                raise SimulationError("the selected Invigoration is not compatible with this Warframe")
            for effect in _effects(row, 0, conditionals=False, source=_row_id(row)):
                _apply_effect(panel, effect, active)
            selected_invigorations.append(_row_id(row))

        seed = _panel_seed(frame)
        base_seed = frame.get("basePanel") if isinstance(frame.get("basePanel"), Mapping) else {}
        base_panel = dict(seed)
        final_panel: dict[str, float] = {}
        for stat in _BASE_STATS:
            state = panel[stat]
            rank_zero = _number(base_seed.get(stat))
            if rank_zero is None and stat == "armor":
                rank_zero = _number(base_seed.get("armour"))
            rank_zero = seed[stat] if rank_zero is None else rank_zero
            value = state["set"] if state["set"] is not None else seed[stat] + state["flat"] + rank_zero * state["percent"]
            final_panel[stat] = round(max(0.0, value), 6)
        for stat in _ABILITY_STATS | panel_extras:
            state = panel[stat]
            final_panel[stat] = round(state["flat"] + state["percent"], 6)
        final_panel["abilityStrength"] = round(1.0 + final_panel["abilityStrength"], 6)
        final_panel["abilityDuration"] = round(1.0 + final_panel["abilityDuration"], 6)
        final_panel["abilityRange"] = round(1.0 + final_panel["abilityRange"], 6)
        final_panel["abilityEfficiency"] = round(min(1.75, max(0.0, 1.0 + final_panel["abilityEfficiency"])), 6)
        final_panel["armour"] = final_panel["armor"]
        if final_panel["armor"] > 0:
            final_panel["damageReduction"] = round(final_panel["armor"] / (final_panel["armor"] + 300.0), 6)
            final_panel["ehp"] = round(final_panel["health"] / max(1e-9, 1.0 - final_panel["damageReduction"]), 6)
        else:
            final_panel["damageReduction"] = 0.0
            final_panel["ehp"] = final_panel["health"]

        def scale_ability(ability: Mapping[str, Any]) -> dict[str, Any]:
            row = dict(ability)
            fields = row.get("scalars") or row.get("numericFields") or []
            if isinstance(fields, Mapping):
                fields = [fields]
            scaled = []
            for field in fields:
                if not isinstance(field, Mapping):
                    continue
                values = field.get("rankValues") or field.get("values") or field.get("baseByRank") or field.get("baseValues")
                if isinstance(values, (list, tuple)) and values:
                    base = _number(values[-1])
                else:
                    base = _number(field.get("base") or field.get("value"))
                if base is None and field.get("displayValue") is not None:
                    scaled.append({
                        "id": field.get("id") or field.get("label"),
                        "label": field.get("label") or field.get("id"),
                        "labelZh": field.get("labelZh") or field.get("label") or field.get("id"),
                        "valueTemplate": field.get("valueTemplate") or "{}",
                        "valueKeys": field.get("valueKeys") or [],
                        "valueParts": {},
                        "displayValue": field.get("displayValue"),
                        "unit": field.get("unit") or "",
                        "scale": "none",
                        "modifier": field.get("modifier"),
                        "group": field.get("group"),
                        "variant": field.get("variant"),
                        "displayOrder": field.get("displayOrder"),
                        "isStatic": True,
                        "isEnergy": bool(field.get("isEnergy")),
                        "base": None,
                        "value": None,
                    })
                    continue
                if base is None:
                    continue
                scale = str(field.get("scale") or "none").casefold()
                factor = {"strength": final_panel["abilityStrength"], "duration": final_panel["abilityDuration"], "range": final_panel["abilityRange"], "efficiency": max(0.25, 2.0 - final_panel["abilityEfficiency"]), "drain": max(0.25, (2.0 - final_panel["abilityEfficiency"]) / max(0.01, final_panel["abilityDuration"]))}.get(scale, 1.0)
                base_values = [float(value) for value in values if _number(value) is not None]
                scaled_values = [round(value * factor, 6) for value in base_values]
                parts = field.get("parts") if isinstance(field.get("parts"), Mapping) else {}
                scaled_parts = {key: round(_number(value) * factor, 6) for key, value in parts.items() if _number(value) is not None}
                scaled.append({
                    "id": field.get("id") or field.get("label"),
                    "label": field.get("label") or field.get("id"),
                    "labelZh": field.get("labelZh") or field.get("label") or field.get("id"),
                    "valueTemplate": field.get("valueTemplate") or "{}",
                    "valueKeys": field.get("valueKeys") or list(scaled_parts),
                    "valueParts": scaled_parts,
                    "unit": field.get("unit") or "",
                    "scale": scale,
                    "modifier": field.get("modifier"),
                    "group": field.get("group"),
                    "variant": field.get("variant"),
                    "displayOrder": field.get("displayOrder"),
                    "isStatic": bool(field.get("isStatic", scale == "none")),
                    "isEnergy": bool(field.get("isEnergy")),
                    "base": round(base, 6),
                    "value": round(base * factor, 6),
                    "baseValues": base_values,
                    "values": scaled_values,
                })
            row["scalars"] = scaled
            cost = row.get("energyCost")
            if isinstance(cost, Mapping):
                efficiency_factor = max(0.25, 2.0 - final_panel["abilityEfficiency"])
                channel_factor = max(0.25, efficiency_factor / max(0.01, final_panel["abilityDuration"]))
                resource = str(cost.get("resource") or "energy")
                energy: dict[str, Any] = dict(cost)
                energy["resource"] = resource
                energy["sourceKind"] = cost.get("sourceKind") or "frozen"
                if resource in {"energy", "shield"}:
                    instant_fields = ("activation", "perTarget", "airborneActivation", "perShot", "chargedShot", "perDodge", "reviveMaximum")
                    channel_fields = ("drainPerSecond", "boostedDrainPerSecond", "perAllyPerSecond", "perEnemyPerSecond", "perAbilityPerSecond")
                    for field in instant_fields + channel_fields:
                        value = _number(cost.get(field))
                        if value is None:
                            continue
                        energy["base" + field[0].upper() + field[1:]] = round(value, 6)
                        factor = channel_factor if field in channel_fields else efficiency_factor
                        energy[field] = round(value * factor, 6)
                row["energyCost"] = energy
            return row

        ability_scalars = [scale_ability(ability) for ability in abilities[:ABILITY_SLOT_COUNT]]
        forma = {"aura": 0, "exilus": 0, "normal": 0}
        source_aura, source_exilus, source_normal = _slot_polarities(frame, None)
        if aura_pol != source_aura:
            forma["aura"] = 1
        if exilus_pol != source_exilus:
            forma["exilus"] = 1
        forma["normal"] = sum(a != b for a, b in zip(normal_pols, source_normal))
        return {
            "catalogRevision": self.catalog.get("buildLabel"),
            "frame": {key: frame.get(key) for key in ("id", "path", "nameEn", "nameZh", "iconAsset", "portraitAsset") if frame.get(key) is not None},
            "rank": 30,
            "capacityBreakdown": {"base": DEFAULT_CAPACITY, "auraGain": capacity - DEFAULT_CAPACITY, "used": used, "limit": capacity, "remaining": capacity - used, "valid": used <= capacity, "assignments": assignments, "aura": aura_assignment},
            "formaBreakdown": forma,
            "basePanel": {**base_panel, "armour": base_panel["armor"]},
            "finalPanel": final_panel,
            "abilityScalars": ability_scalars,
            "passive": frame.get("passive") or frame.get("passiveDescription") or "",
            "activeEffects": active,
            "setCounts": {
                key: {
                    "pieces": count,
                    "multiplier": set_multipliers.get(key, 1.0),
                    "cardMultipliers": {
                        _row_id(row): _set_multiplier(row, count)
                        for row in set_members
                        if _set_id(row) == key
                    },
                }
                for key, count in set_counts.items()
            },
            "validation": {"valid": used <= capacity, "errors": ([] if used <= capacity else ["MOD capacity exceeded"]), "warnings": list(self.catalog.get("gaps") or ())},
            "selected": {"aura": _row_id(aura_row) if aura_row else None, "exilus": _row_id(exilus_row) if exilus_row else None, "arcanes": [_row_id(row) for row, _ in arcane_rows], "shards": [_row_id(row) for row, _ in shard_rows], "invigoration": selected_invigorations},
        }


__all__ = ["WarframeEngine", "load_warframe_catalog", "DEFAULT_CAPACITY", "NORMAL_SLOT_COUNT", "ARCANE_SLOT_COUNT", "SHARD_SLOT_COUNT"]
