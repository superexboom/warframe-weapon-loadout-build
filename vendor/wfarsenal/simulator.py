"""Offline weapon loadout simulation over one frozen export directory."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .damage import (
    ModEffect,
    ModEffectList,
    Scenario,
    _scale_effect,
    apply_mods,
    damage_against,
    enemy_kill_metrics,
    expected_status_damage,
    expected_victim_status_count,
    sustained_status_damage,
    mod_effects,
)
from .projectile_events import evaluate_projectile_events
from .catalog_releases import released_mod_catalog


EXPORT_NAMES = ("weapons", "warframes", "mods", "enemies")
LOOKUP_FIELDS = ("nameEn", "nameZh", "nameInternal", "name")

# Zaw strikes export the resulting melee weapon class per handedness; the class
# maps to the stance compatibility tag normal melee weapons carry in
# ``compatTags`` (e.g. a Nikana-class zaw accepts NIKANAS_STANCE stances).
ZAW_CLASS_STANCE_TAGS = {
    "Dagger": "DAGGERS_STANCE",
    "Hammer": "HAMMERS_STANCE",
    "Heavy Blade": "HEAVY_BLADE_STANCE",
    "Machete": "MACHETES_STANCE",
    "Nikana": "NIKANAS_STANCE",
    "Polearm": "POLEARMS_STANCE",
    "Rapier": "RAPIER_STANCE",
    "Scythe": "SCYTHES_STANCE",
    "Staff": "STAVES_STANCE",
    "Sword": "SWORDS_STANCE",
}

# Weapon exports contain ten ArtifactSlots for most guns/melee weapons: eight
# normal MOD slots followed by exilus slots.  The portable builder only installs
# normal weapon MODs, so capacity validation consumes the first ``slot_count``
# entries and never invents a Forma polarity.
DEFAULT_LOADOUT_SLOTS = 8
DEFAULT_CAPACITY_LIMIT = 60


class SimulationError(ValueError):
    """Expected, user-fixable loadout or export error."""

    def __init__(self, message: str, *, candidates: Sequence[Mapping[str, Any]] = ()):
        super().__init__(message)
        self.candidates = [record_identity(row) for row in candidates]


def record_identity(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable identity fields without copying a full export record."""
    return {
        key: record.get(key)
        for key in ("path", "nameInternal", "nameEn", "nameZh")
        if record.get(key) is not None
    }


_EXPORT_CACHE: dict[str, dict[str, Any]] = {}


def load_exports(export_dir: str | Path) -> dict[str, Any]:
    """Load one frozen build plus optional datasets used by richer callers.

    Frozen exports are immutable per directory, so results are memoized —
    batch callers (per-mod gain sweeps) reuse the parsed payloads instead of
    re-reading and re-decoding megabytes of JSON per kernel invocation.
    """
    root = Path(export_dir).resolve()
    cache_key = str(root)
    cached = _EXPORT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    result = _load_exports_uncached(root)
    if len(_EXPORT_CACHE) > 8:
        _EXPORT_CACHE.clear()
    _EXPORT_CACHE[cache_key] = result
    return result


def _load_exports_uncached(root: Path) -> dict[str, Any]:
    payloads: dict[str, Mapping[str, Any]] = {}
    for name in EXPORT_NAMES:
        path = root / f"{name}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise SimulationError(f"missing export file: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file: {path}: {exc}") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
            raise SimulationError(f"invalid export payload: {path}")
        payloads[name] = payload

    builds = {payload.get("buildLabel") for payload in payloads.values()}
    schemas = {payload.get("schemaVersion") for payload in payloads.values()}
    if len(builds) != 1 or None in builds:
        raise SimulationError(f"export build labels do not match: {sorted(map(str, builds))}")
    if len(schemas) != 1 or None in schemas:
        raise SimulationError(f"export schema versions do not match: {sorted(map(str, schemas))}")
    build_label = next(iter(builds))
    schema_version = next(iter(schemas))
    kitguns: Mapping[str, Any] = {}
    kitgun_path = root / "kitguns.json"
    if kitgun_path.is_file():
        try:
            loaded = json.loads(kitgun_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file {kitgun_path}: {exc}") from exc
        if not isinstance(loaded, Mapping) or loaded.get("buildLabel") != build_label:
            raise SimulationError(f"invalid Kitgun export payload: {kitgun_path}")
        kitguns = loaded

    zaws: Mapping[str, Any] = {}
    zaw_path = root / "zaws.json"
    if zaw_path.is_file():
        try:
            loaded = json.loads(zaw_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file {zaw_path}: {exc}") from exc
        if not isinstance(loaded, Mapping):
            raise SimulationError(f"invalid Zaw export payload: {zaw_path}")
        zaws = loaded

    arcanes: list[Mapping[str, Any]] = []
    arcane_path = root / "arcanes.json"
    if arcane_path.is_file():
        try:
            loaded = json.loads(arcane_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file {arcane_path}: {exc}") from exc
        if (
            not isinstance(loaded, Mapping)
            or not isinstance(loaded.get("data"), list)
            or loaded.get("buildLabel") != build_label
            or loaded.get("schemaVersion") != schema_version
        ):
            raise SimulationError(f"invalid Arcane export payload: {arcane_path}")
        arcanes = loaded["data"]

    incarnon_defaults: Mapping[str, Any] = {}
    defaults_path = root / "incarnon_defaults.json"
    if defaults_path.is_file():
        try:
            loaded = json.loads(defaults_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file {defaults_path}: {exc}") from exc
        if (
            not isinstance(loaded, Mapping)
            or not isinstance(loaded.get("sampledAt"), str)
            or not isinstance(loaded.get("gameBuild"), str)
            or not isinstance(loaded.get("strategies"), Mapping)
        ):
            raise SimulationError(f"invalid Incarnon defaults payload: {defaults_path}")
        incarnon_defaults = loaded
    riven_templates: Mapping[str, Any] = {}
    templates_path = root / "riven_templates.json"
    if templates_path.is_file():
        try:
            loaded = json.loads(templates_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SimulationError(f"cannot read export file {templates_path}: {exc}") from exc
        if not isinstance(loaded, Mapping) or loaded.get("buildLabel") != build_label:
            raise SimulationError(f"invalid Riven template payload: {templates_path}")
        riven_templates = loaded
    return {
        "path": str(root.resolve()),
        "buildLabel": build_label,
        "schemaVersion": schema_version,
        "kitguns": kitguns,
        "zaws": zaws,
        "arcanes": arcanes,
        "incarnonDefaults": incarnon_defaults,
        "rivenTemplates": riven_templates,
        **{name: payloads[name]["data"] for name in EXPORT_NAMES},
        'mods': released_mod_catalog(payloads['mods']['data']),
    }


_RESOLVE_CACHE: dict[tuple[int, str, str], Mapping[str, Any] | None] = {}
_RESOLVE_CACHE_LIMIT = 8192


def resolve_record(
    records: Sequence[Mapping[str, Any]], query: str, *, kind: str
) -> Mapping[str, Any]:
    """Resolve an exact path or a unique localized/internal name."""
    query = query.strip()
    if not query:
        raise SimulationError(f"{kind} query must not be empty")
    folded = query.casefold()
    # Frozen record sequences are reused across kernel calls in the same
    # process; memoize the (sequence identity, query) resolution so per-mod
    # gain sweeps skip the O(rows x fields) linear scan.
    cache_key = (id(records), kind, folded)
    cached = _RESOLVE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    matches = [
        row
        for row in records
        if str(row.get("path") or "").casefold() == folded
        or any(str(row.get(field) or "").casefold() == folded for field in LOOKUP_FIELDS)
    ]
    # A row can match several fields but appears once because the predicate is boolean.
    if len(matches) == 1:
        if len(_RESOLVE_CACHE) >= _RESOLVE_CACHE_LIMIT:
            _RESOLVE_CACHE.clear()
        _RESOLVE_CACHE[cache_key] = matches[0]
        return matches[0]
    if not matches:
        raise SimulationError(
            f"{kind} not found by exact path/nameEn/nameZh/nameInternal: {query!r}"
        )
    raise SimulationError(
        f"ambiguous {kind} query {query!r}; use an exact path",
        candidates=matches,
    )


def _kitgun_override(
    component: Mapping[str, Any], barrel_type: str, gun_type: str
) -> Mapping[str, Any]:
    for row in component.get("overrides") or ():
        if (
            isinstance(row, Mapping)
            and row.get("barrelType") == barrel_type
            and row.get("gunType") == gun_type
        ):
            return row
    raise SimulationError(f"Kitgun component has no {barrel_type}/{gun_type} override")


def _apply_kitgun_damage_delta(damage: dict[str, Any], delta: float) -> None:
    types = damage.get("types") or {}
    if not isinstance(types, Mapping) or not types:
        damage["total"] = 0.0
        damage["types"] = {}
        damage["shares"] = {}
        return
    per_type = delta / len(types)
    adjusted = {
        damage_type: round(max(0.0, float(amount) + per_type), 6)
        for damage_type, amount in types.items()
    }
    adjusted = {damage_type: amount for damage_type, amount in adjusted.items() if amount}
    total = sum(adjusted.values())
    damage["total"] = total
    damage["types"] = adjusted
    damage["shares"] = {
        damage_type: amount / total for damage_type, amount in adjusted.items()
    } if total else {}


def resolve_kitgun_record(
    base: Mapping[str, Any], parts: Sequence[str], rules: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Assemble one Kitgun from frozen chamber, grip and loader overrides."""
    if not rules:
        raise SimulationError("Kitgun component export is missing")
    normalized = {
        str(part).strip().replace("\\", "/").rstrip("/"): str(part).strip()
        for part in parts
        if str(part).strip()
    }
    barrels = rules.get("barrels") or {}
    handles = rules.get("handles") or {}
    clips = rules.get("clips") or {}
    barrel = next((barrels[path] for path in normalized if path in barrels), None)
    handle = next((handles[path] for path in normalized if path in handles), None)
    clip = next((clips[path] for path in normalized if path in clips), None)
    if not all(isinstance(row, Mapping) for row in (barrel, handle, clip)):
        raise SimulationError("Kitgun requires one known chamber, grip and loader")
    if len(normalized) != 3:
        raise SimulationError("Kitgun requires exactly three component paths")

    slot = str(base.get("slot") or "")
    if handle.get("slot") != slot or slot not in {"primary", "secondary"}:
        raise SimulationError(f"Kitgun grip does not match {slot or 'unknown'} weapon slot")
    barrel_type = str(barrel.get("barrelType") or "")
    gun_type = str(barrel.get("gunType") or "")
    handle_override = _kitgun_override(handle, barrel_type, gun_type)
    clip_override = _kitgun_override(clip, barrel_type, gun_type)
    source_modes = barrel.get(f"{slot}Modes") or ()
    if not source_modes:
        raise SimulationError(f"Kitgun chamber has no {slot} fire mode")

    record = deepcopy(dict(base))
    record["name"] = str(barrel.get("nameEn") or "Kitgun").replace(" ", "") + "Kitgun"
    record["nameInternal"] = record["name"]
    record["nameEn"] = f"{barrel.get('nameEn') or 'Kitgun'} Kitgun"
    record["nameZh"] = f"{barrel.get('nameZh') or '组合枪'} 组合枪"
    record["magazineSize"] = clip_override.get("magazineSize")
    record["omegaAttenuation"] = (
        barrel.get("primaryOmegaAttenuation")
        if slot == "primary" and barrel.get("primaryOmegaAttenuation") is not None
        else barrel.get("omegaAttenuation")
    )
    record["compatTags"] = sorted(
        set(record.get("compatTags") or ()) | set(barrel.get("compatTags") or ())
    )
    record["kitgunParts"] = list(normalized)
    record["kitgunUnsupported"] = []
    record["fireModes"] = []
    damage_delta = float(handle_override.get("damage") or 0.0)
    for index, source in enumerate(source_modes):
        mode = deepcopy(dict(source))
        mode["index"] = index
        mode["fireRateRaw"] = handle_override.get("fireRate")
        mode["fireRate"] = float(handle_override.get("fireRate") or 0.0) / 60.0
        mode["reloadTime"] = clip_override.get("reloadTime")
        if handle_override.get("traceDistance"):
            mode["traceDistance"] = handle_override["traceDistance"]
        damage = mode.get("damage")
        if not isinstance(damage, dict):
            raise SimulationError("Kitgun chamber fire mode has no direct damage")
        _apply_kitgun_damage_delta(damage, damage_delta)
        radial = damage.get("radial")
        if isinstance(radial, dict):
            _apply_kitgun_damage_delta(radial, damage_delta)
        if not damage.get("types") and isinstance(radial, Mapping) and radial.get("total"):
            raise SimulationError("radial-only Kitgun damage is not supported")
        damage["critChance"] = clip_override.get("critChance")
        damage["critMultiplier"] = clip_override.get("critMultiplier")
        damage["procChance"] = clip_override.get("procChance")
        record["kitgunUnsupported"].extend(source.get("unsupported") or ())
        if damage.get("radial"):
            record["kitgunUnsupported"].append("kitgun-radial-damage-unapplied")
        record["fireModes"].append(mode)
    record["kitgunUnsupported"] = sorted(set(record["kitgunUnsupported"]))
    return record


def _zaw_legacy_paths(rules: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(row["legacyPath"]): real
        for table in ("strikes", "grips", "links")
        for real, row in (rules.get(table) or {}).items()
        if isinstance(row, Mapping) and row.get("legacyPath")
    }


def zaw_part_paths(parts: Sequence[Any], rules: Mapping[str, Any]) -> list[str]:
    """Zaw parts as client paths. A selection saved before the parts were
    matched to the client (wiki-frozen paths, ``legacyPath``) is recognised by
    its strike and read as a whole in the old paths: the old grip paths
    HandleOne..HandleSix name other grips in the client."""
    paths = [str(p).strip().replace("\\", "/").rstrip("/") for p in parts if str(p).strip()]
    legacy = _zaw_legacy_paths(rules)
    strikes = rules.get("strikes") or {}
    if any(path in legacy and legacy[path] in strikes for path in paths):
        return [legacy.get(path, path) for path in paths]
    return paths


def is_zaw_assembly(parts: Sequence[Any], rules: Mapping[str, Any]) -> bool:
    strikes = (rules or {}).get("strikes") or {}
    return any(path in strikes for path in zaw_part_paths(parts, rules or {}))


def resolve_zaw_record(
    base: Mapping[str, Any], parts: Sequence[str], rules: Mapping[str, Any]
) -> Mapping[str, Any]:
    """Assemble one Zaw from frozen strike, grip and link rows.

    Damage model (wiki-verified): every part contributes a flat damage bonus
    to the strike's base total, and a two-handed Zaw multiplies it by the
    strike's two-handed damage factor; attack speed is the grip's base speed
    plus the strike's and link's speed modifiers; crit/status add the link's
    additive share. The grip's handedness picks the 1H/2H weapon class from
    the strike.
    """
    if not rules:
        raise SimulationError("Zaw component export is missing")
    normalized = {path: path for path in zaw_part_paths(parts, rules)}
    strikes = rules.get("strikes") or {}
    grips = rules.get("grips") or {}
    links = rules.get("links") or {}
    strike = next((strikes[path] for path in normalized if path in strikes), None)
    grip = next((grips[path] for path in normalized if path in grips), None)
    link = next((links[path] for path in normalized if path in links), None)
    if not all(isinstance(row, Mapping) for row in (strike, grip, link)):
        raise SimulationError("Zaw requires one known strike, grip and link")
    if len(normalized) != 3:
        raise SimulationError("Zaw requires exactly three component paths")

    record = deepcopy(dict(base))
    record["name"] = str(strike.get("nameEn") or "Zaw").replace(" ", "") + "Zaw"
    record["nameInternal"] = record["name"]
    record["nameEn"] = f"{strike.get('nameEn') or 'Zaw'} Zaw"
    record["nameZh"] = f"{strike.get('nameZh') or 'Zaw'} 组合近战"
    record["omegaAttenuation"] = strike.get("omegaAttenuation")
    record["zawParts"] = list(normalized)

    handed = "two" if str(grip.get("handed") or "two") == "two" else "one"
    # The 1H/2H weapon class lives on the strike, not the grip; reading it from
    # the grip silently degraded every zaw to the Sword fallback.
    weapon_class = str((strike.get("twoHanded" if handed == "two" else "oneHanded")) or "Sword")
    record["zawWeaponClass"] = weapon_class
    record["zawHanded"] = handed
    record["zawStrike"] = next(path for path in normalized if path in strikes)
    stance_tag = ZAW_CLASS_STANCE_TAGS.get(weapon_class)
    if stance_tag:
        record["compatTags"] = sorted(
            set(record.get("compatTags") or ()) | {stance_tag}
        )

    strike_damage = strike.get("damage") if isinstance(strike.get("damage"), Mapping) else {}
    base_total = float(strike_damage.get("total") or 0.0)
    flat_bonus = (
        float(grip.get("damageBonus") or 0.0) + float(link.get("damageBonus") or 0.0)
    )
    speed = (
        float(grip.get("baseSpeed") or 0.917)
        + float(strike.get("speedMod") or 0.0)
        + float(link.get("speedBonus") or 0.0)
    )
    crit_chance = float(strike.get("critChance") or 0.0) + float(link.get("critChance") or 0.0)
    crit_multiplier = float(strike.get("critMultiplier") or 2.0)
    proc_chance = float(strike.get("procChance") or 0.0) + float(link.get("statusChance") or 0.0)
    factor = float(strike.get("twoHandedDamageFactor") or 1.0) if handed == "two" else 1.0
    total = max(0.0, (base_total + flat_bonus) * factor)
    strike_types = {
        str(dtype): max(0.0, float(amount))
        for dtype, amount in (strike_damage.get("types") or {}).items()
        if isinstance(amount, (int, float))
    }
    if (flat_bonus or factor != 1.0) and strike_types:
        scale = total / max(sum(strike_types.values()), 1e-9)
        strike_types = {dtype: amount * scale for dtype, amount in strike_types.items()}

    mode = {
        "ammoCost": 0,
        "ammoType": "",
        "chargeTime": None,
        "damage": {
            "critChance": max(0.0, crit_chance),
            "critMultiplier": max(1.0, crit_multiplier),
            "procChance": max(0.0, min(proc_chance, 1.0)),
            "shares": {
                dtype: amount / total for dtype, amount in strike_types.items()
            } if total else {},
            "total": total,
            "types": {dtype: round(amount, 4) for dtype, amount in strike_types.items()},
        },
        "falloffMinDamage": 1,
        "falloffRange": [0, 0],
        "fireRate": max(0.05, round(speed, 6)),
        "fireRateRaw": round(max(0.05, speed) * 60.0, 3),
        "index": 0,
        "isAlternateFire": False,
        "multishot": 1,
        "reloadTime": 1,
        "trigger": "",
    }
    record["fireModes"] = [mode]
    record["kitgunUnsupported"] = []
    return record


def _mod_matches_weapon(
    mod: Mapping[str, Any], weapon: Mapping[str, Any]
) -> bool:
    """Check the exported equipment base type and engine compatibility tags."""
    compatibility = mod.get("compatibility")
    if isinstance(compatibility, str) and compatibility:
        ancestry = {
            str(path).rstrip("/").casefold()
            for path in (*tuple(weapon.get("ancestry") or ()), weapon.get("path"))
            if path
        }
        if compatibility.rstrip("/").casefold() not in ancestry:
            return False
    weapon_tags = {
        str(tag).casefold() for tag in weapon.get("compatTags") or () if tag
    }
    required = {
        str(tag).casefold() for tag in mod.get("compatibilityTags") or () if tag
    }
    blocked = {
        str(tag).casefold() for tag in mod.get("incompatibilityTags") or () if tag
    }
    return (not required or bool(required & weapon_tags)) and not (blocked & weapon_tags)


def _steady_state_scenario(
    mods: Iterable[Mapping[str, Any]], scenario: Scenario
) -> Scenario:
    """Fill only exported kill-triggered MOD stacks for sustained snapshots."""
    stacks = dict(scenario.conditional_stacks)
    for mod in mods:
        for conditional in mod.get("conditionalEffects") or ():
            if not isinstance(conditional, Mapping):
                continue
            condition_text = " ".join(
                str(value or "")
                for value in (
                    conditional.get("conditionTag"),
                    conditional.get("sourcePath"),
                    *(conditional.get("conditions") or ()),
                )
            ).casefold()
            if "killcondition" not in condition_text:
                continue
            maximum = conditional.get("maxStacks")
            maximum = maximum if isinstance(maximum, int) and maximum > 0 else 1
            for key in (
                conditional.get("sourcePath"),
                conditional.get("conditionTag"),
            ):
                if isinstance(key, str) and key:
                    stacks.setdefault(key, maximum)
    return replace(scenario, conditional_stacks=stacks)


def _polarity_key(value: Any) -> str | None:
    """Normalize an exported or caller-supplied polarity token."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError("polarity tokens must be strings or null")
    token = str(value).strip().upper()
    # In the export enum AP_UNIVERSAL is the ordinary unpolarized slot/card
    # sentinel (not a free half-drain slot).  AP_ANY is kept distinct for a
    # future true universal polarity if the game begins exporting one.
    if not token or token in {"AP_UNIVERSAL", "AP_NONE", "NONE", "NULL"}:
        return None
    if token == "AP_ANY":
        return "AP_ANY"
    return token


def _ranked_mod_drain(mod: Mapping[str, Any], rank: int | None) -> int:
    """Return signed rank-scaled drain; auras/stances grant capacity."""
    base = mod.get("baseDrain")
    if isinstance(base, bool) or not isinstance(base, int):
        raise SimulationError(
            f"{mod.get('path') or mod.get('nameEn') or '?'} has no valid baseDrain"
        )
    if rank is None:
        rank = mod.get("maxRank")
        if rank is None:
            rank = 0
    if isinstance(rank, bool) or not isinstance(rank, int) or rank < 0:
        raise SimulationError("mod rank must be a non-negative integer")
    max_rank = mod.get("maxRank")
    if isinstance(max_rank, int) and not isinstance(max_rank, bool) and rank > max_rank:
        raise SimulationError(
            f"{mod.get('nameEn') or mod.get('path') or '?'} ranks to {max_rank}, got rank {rank}"
        )
    # Exported aura/stance base drains are negative.  Their capacity gain grows
    # with rank in the negative direction; ordinary cards grow positively.
    return (-1 if base < 0 else 1) * (abs(base) + rank)


def _polarity_adjusted_drain(raw_drain: int, mod_polarity: Any, slot_polarity: Any) -> tuple[int, str]:
    """Apply Warframe's matching/mismatching slot multiplier with integer rounding."""
    mod_key = _polarity_key(mod_polarity)
    slot_key = _polarity_key(slot_polarity)
    if not mod_key or not slot_key:
        relation = "unpolarized"
        multiplier = 1.0
    elif mod_key == "AP_ANY" or slot_key == "AP_ANY" or mod_key == slot_key:
        relation = "matched"
        multiplier = 0.5 if raw_drain >= 0 else 2.0
    else:
        relation = "mismatched"
        multiplier = 1.25 if raw_drain >= 0 else 0.5
    adjusted = math.ceil(abs(raw_drain) * multiplier)
    return (-adjusted if raw_drain < 0 else adjusted), relation


def validate_loadout(
    weapon: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    *,
    slot_count: int = DEFAULT_LOADOUT_SLOTS,
    capacity_limit: int = DEFAULT_CAPACITY_LIMIT,
    slot_polarities: Sequence[Any] | None = None,
) -> dict[str, Any]:
    """Validate slots, rank-scaled drain and exported slot polarities.

    ``slot_polarities`` is an explicit caller override (for a future Forma UI).
    Without it, the frozen weapon export is authoritative.  Missing or short
    polarity data is an error instead of silently assuming matching Forma.
    """
    if isinstance(slot_count, bool) or not isinstance(slot_count, int) or not 1 <= slot_count <= 9:
        raise SimulationError("slot_count must be an integer between 1 and 9")
    if isinstance(capacity_limit, bool) or not isinstance(capacity_limit, int) or capacity_limit < 0:
        raise SimulationError("capacity_limit must be a non-negative integer")
    if len(cards) > slot_count:
        raise SimulationError(
            f"loadout has {len(cards)} MODs but only {slot_count} slots are available"
        )
    source = slot_polarities if slot_polarities is not None else weapon.get("polarities")
    if not isinstance(source, (list, tuple)) or len(source) < slot_count:
        raise SimulationError(
            "weapon slot polarity data is incomplete; capacity validation refuses to assume Forma"
        )
    normalized_slots = [_polarity_key(value) for value in source[:slot_count]]
    assignments: list[dict[str, Any]] = []
    used = 0
    seen_slots: set[int] = set()
    for index, mod in enumerate(cards):
        slot = mod.get("slot", index)
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < slot_count:
            raise SimulationError(f"loadout MOD {index} has an invalid slot index")
        if slot in seen_slots:
            raise SimulationError(f"loadout slot {slot} is assigned more than once")
        seen_slots.add(slot)
        rank = mod.get("rank")
        raw_drain = _ranked_mod_drain(mod, rank)
        effective, relation = _polarity_adjusted_drain(
            raw_drain,
            mod.get("polarity"),
            normalized_slots[slot],
        )
        used += effective
        assignments.append(
            {
                "slot": slot,
                "path": mod.get("path"),
                "rank": mod.get("rank") if mod.get("rank") is not None else mod.get("maxRank", 0),
                "baseDrain": mod.get("baseDrain"),
                "rawDrain": raw_drain,
                "drain": effective,
                "modPolarity": _polarity_key(mod.get("polarity")),
                "slotPolarity": normalized_slots[slot],
                "polarityRelation": relation,
            }
        )
    return {
        "status": "checked",
        "valid": used <= capacity_limit,
        "capacity": used,
        "capacityLimit": capacity_limit,
        "remaining": capacity_limit - used,
        "slotCount": slot_count,
        "polaritySource": "payload" if slot_polarities is not None else "export",
        "slotPolarities": normalized_slots,
        "assignments": assignments,
    }


def _set_key(value: Any) -> str:
    """Normalize an exported set/member identifier."""
    return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()


def _set_shells(mods: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Index exported non-selectable set shells by their member ``modSet`` id."""
    shells: dict[str, Mapping[str, Any]] = {}
    for mod in mods:
        set_id = _set_key(mod.get("modSet"))
        if not set_id or mod.get("setPieces") is None:
            continue
        # Set shells are exported as non-selectable records without a weapon
        # compatibility path.  Keep the predicate narrow so a future member record
        # carrying metadata cannot shadow its shell.
        if mod.get("selectable") is False or (
            not mod.get("selectable") and not mod.get("compatibility")
        ):
            shells[set_id] = mod
    return shells


def _effective_set_pieces(
    mod: Mapping[str, Any],
    *,
    selected_count: int,
    shell: Mapping[str, Any] | None,
) -> tuple[int, str | None]:
    set_id = _set_key(mod.get("modSet"))
    maximum = shell.get("setPieces") if shell else None
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 0:
        maximum = None
    pieces = max(0, selected_count)
    if maximum is not None and pieces > maximum:
        return maximum, f"{set_id}: setPieces clamped {pieces}->{maximum}"
    return pieces, None


def _buff_set_multiplier(mod: Mapping[str, Any], pieces: int) -> float:
    """Apply the exported BuffSet member curve (e.g. Sacrificial 1.25x at 2)."""
    values = mod.get("modSetValues")
    if not isinstance(values, (list, tuple)) or pieces < 2:
        return 1.0
    index = min(pieces - 2, len(values) - 1)
    if index < 0:
        return 1.0
    value = values[index]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SimulationError(f"{mod.get('path') or '?'} has invalid modSetValues")
    multiplier = 1.0 + float(value)
    if multiplier < 0.0:
        raise SimulationError(f"{mod.get('path') or '?'} has a negative set multiplier")
    return multiplier


def _set_shell_effects(
    shell: Mapping[str, Any], pieces: int, scenario: Scenario
) -> ModEffectList:
    """Expand one structured shell at rank zero and scale it by active pieces."""
    source = shell.get("path") or shell.get("nameInternal") or "set-shell"
    if pieces <= 0:
        return ModEffectList()
    if shell.get("buffSet"):
        # BuffSet members carry the verified ModSetValues curve.  The shell's
        # placeholder NONE effects are not a second bonus.
        if shell.get("runtimeScripts"):
            return ModEffectList(
                [
                    ModEffect(
                        upgrade_type="SET_SHELL_UNSUPPORTED",
                        operation="ADD",
                        value=0.0,
                        supported=False,
                        source_path=str(source),
                    )
                ],
                skipped=[f"{source}: unsupported[set-shell-runtime-script]"],
            )
        return ModEffectList()
    expanded = mod_effects(shell, 0, scenario)
    result = ModEffectList(
        (_scale_effect(effect, pieces) for effect in expanded),
        skipped=expanded.skipped,
    )
    if shell.get("runtimeScripts") or any(
        isinstance(condition, Mapping) and condition.get("runtimeScripts")
        for condition in shell.get("conditionalEffects") or ()
    ):
        result.append(
            ModEffect(
                upgrade_type="SET_SHELL_UNSUPPORTED",
                operation="ADD",
                value=0.0,
                supported=False,
                source_path=str(source),
            )
        )
        result.skipped.append(f"{source}: unsupported[set-shell-runtime-script]")
    return result


def simulate(
    export_dir: str | Path,
    *,
    weapon: str,
    kitgun_parts: Sequence[str] = (),
    enemy: str,
    enemy_override: Mapping[str, Any] | None = None,
    mods: Sequence[tuple[str, int | None] | tuple[str, int | None, int]] = (),
    set_pieces: Mapping[str, int] | None = None,
    validate_loadout_slots: bool = False,
    slot_count: int = DEFAULT_LOADOUT_SLOTS,
    capacity_limit: int = DEFAULT_CAPACITY_LIMIT,
    slot_polarities: Sequence[Any] | None = None,
    fire_mode: int = 0,
    scenario: Scenario | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    enemy_enhancements: Mapping[str, Any] | None = None,
    hit_location: str | None = None,
    forced_procs: Mapping[str, float] | None = None,
    passive_effects: Iterable[Any] = (),
    status_rate_multiplier: float = 1.0,
    damage_rate_multiplier: float = 1.0,
    weapon_override: Mapping[str, Any] | None = None,
    engine_context_sink: dict | None = None,
    riven_slot: int | None = None,
) -> dict[str, Any]:
    """Resolve a loadout and return one deterministic JSON-compatible result."""
    if isinstance(fire_mode, bool) or not isinstance(fire_mode, int) or fire_mode < 0:
        raise SimulationError("fire_mode must be a non-negative integer")
    if not isinstance(validate_loadout_slots, bool):
        raise SimulationError("validate_loadout_slots must be a boolean")
    if level is not None and (
        isinstance(level, bool) or not isinstance(level, int) or level < 0
    ):
        raise SimulationError("level must be a non-negative integer")
    if isinstance(armour_strip, bool) or not isinstance(armour_strip, (int, float)):
        raise SimulationError("armour_strip must be a number between 0 and 1")
    armour_strip = float(armour_strip)
    if not math.isfinite(armour_strip) or not 0.0 <= armour_strip <= 1.0:
        raise SimulationError("armour_strip must be a number between 0 and 1")
    if isinstance(elemental_armour_strip, bool) or not isinstance(elemental_armour_strip, (int, float)):
        raise SimulationError("elemental_armour_strip must be a number between 0 and 1")
    elemental_armour_strip = float(elemental_armour_strip)
    if not math.isfinite(elemental_armour_strip) or not 0.0 <= elemental_armour_strip <= 1.0:
        raise SimulationError("elemental_armour_strip must be a number between 0 and 1")
    if not isinstance(steel_path, bool):
        raise SimulationError("steel_path must be a boolean")
    for label, value in (
        ("status_rate_multiplier", status_rate_multiplier),
        ("damage_rate_multiplier", damage_rate_multiplier),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise SimulationError(f"{label} must be a non-negative finite number")
    if hit_location is not None and not isinstance(hit_location, str):
        raise SimulationError("hit_location must be 'body' or 'head'")
    normalized_hit_location = (hit_location or "body").strip().casefold().replace("-", "_")
    if normalized_hit_location in {"torso", "body_hit"}:
        normalized_hit_location = "body"
    elif normalized_hit_location in {"headshot", "head_hit", "headshot_hit", "weakpoint", "weak_point"}:
        normalized_hit_location = "head"
    if normalized_hit_location not in {"body", "head"}:
        raise SimulationError("hit_location must be 'body' or 'head'")

    exports = load_exports(export_dir)
    weapon_record = resolve_record(exports["weapons"], weapon, kind="weapon")
    if kitgun_parts:
        zaw_rules = exports.get("zaws") or {}
        if is_zaw_assembly(kitgun_parts, zaw_rules):
            weapon_record = resolve_zaw_record(weapon_record, kitgun_parts, zaw_rules)
        else:
            weapon_record = resolve_kitgun_record(
                weapon_record, kitgun_parts, exports["kitguns"]
            )
    if weapon_override is not None:
        if not isinstance(weapon_override, Mapping):
            raise SimulationError("weapon_override must be an object")
        weapon_record = {**weapon_record, **weapon_override}
    # ── 灵化形态标记（与 optimizer._select_fire_mode 同口径）──────────────
    # apply_mods 按 isIncarnonForm 决定充能池口径（常驻灵化零装填 / 循环
    # 折算装填）。simulate 路径此前不标记——灵化形态一直按裸 reloadTime
    # 解算持续 DPS，与基准 KPM 口径（零装填）不一致（KPM 与 sim 对不上
    # 的原因之一，2026-09-24 修复）。保留完整 fireModes（apply_mods 按
    # fire_mode 下标取模式），另存 __baseFireModes__ 供循环口径读取
    # 基础形态装填。
    _modes = weapon_record.get("fireModes") or []
    from .event_profiles import is_incarnon_mode
    if is_incarnon_mode(weapon_record,fire_mode):
        weapon_record = {
            **weapon_record,
            "isIncarnonForm": True,
            "__baseFireModes__": list(_modes),
        }
    if enemy_override is not None:
        if not isinstance(enemy_override, Mapping):
            raise SimulationError("enemy_override must be an object")
        enemy_record = dict(enemy_override)
        enemy_record.setdefault("path", "__custom_enemy__")
        enemy_record.setdefault("name", "Custom defense snapshot")
        enemy_record.setdefault("nameEn", "Custom defense snapshot")
        enemy_record.setdefault("nameZh", "自定义防御快照")
    else:
        enemy_record = resolve_record(exports["enemies"], enemy, kind="enemy")
    scenario = scenario or Scenario()

    if set_pieces:
        raise SimulationError("set_pieces is derived from equipped MODs and cannot be overridden")
    shells = _set_shells(exports["mods"])
    selected_mods: list[dict[str, Any]] = []
    selected_cards: list[dict[str, Any]] = []
    effects = ModEffectList()
    resolved_mods: list[tuple[Mapping[str, Any], str, int | None, bool, int | None]] = []
    selected_counts: dict[str, int] = {}
    for spec in mods:
        if isinstance(spec, Mapping):
            query = spec.get("path") or spec.get("query")
            rank = spec.get("rank")
            if spec.get("setPieces") is not None:
                raise SimulationError("setPieces is derived from equipped MODs")
            slot = spec.get("slot")
        elif isinstance(spec, (tuple, list)) and len(spec) == 2:
            query, rank = spec[0], spec[1]
            slot = None
        else:
            raise SimulationError("mods entries must be QUERY/RANK tuples or objects")
        if not isinstance(query, str):
            raise SimulationError("mod query must be a string")
        mod = resolve_record(exports["mods"], query, kind="mod")
        compatible = _mod_matches_weapon(mod, weapon_record)
        set_id = _set_key(mod.get("modSet"))
        if compatible and set_id:
            selected_counts[set_id] = selected_counts.get(set_id, 0) + 1
        if slot is not None and (isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < slot_count):
            raise SimulationError("mod slot must be an integer inside slot_count")
        resolved_mods.append((mod, query, rank, compatible, slot))

    scenario = _steady_state_scenario(
        (mod for mod, _query, _rank, compatible, _slot in resolved_mods if compatible),
        scenario,
    )

    active_set_pieces: dict[str, int] = {}
    set_diagnostics: list[str] = []
    riven_effect_index = None
    for mod, query, rank, compatible, slot in resolved_mods:
        if riven_slot is not None and riven_effect_index is None and (slot if slot is not None else len(selected_mods)) >= riven_slot:
            riven_effect_index = len(effects)
        set_id = _set_key(mod.get("modSet"))
        shell = shells.get(set_id) if set_id else None
        pieces = 0
        if set_id and compatible:
            pieces, clamp_note = _effective_set_pieces(
                mod,
                selected_count=selected_counts.get(set_id, 0),
                shell=shell,
            )
            if set_id in active_set_pieces and active_set_pieces[set_id] != pieces:
                raise SimulationError(f"conflicting setPieces for {mod.get('modSet')}")
            active_set_pieces[set_id] = pieces
            if clamp_note:
                set_diagnostics.append(clamp_note)
        try:
            current = mod_effects(mod, rank, scenario)
        except (TypeError, ValueError) as exc:
            raise SimulationError(f"invalid rank for {query!r}: {exc}") from exc
        if compatible:
            if mod.get("modSetValues") and (shell is None or shell.get("buffSet")):
                multiplier = _buff_set_multiplier(mod, pieces)
                if multiplier != 1.0:
                    current = ModEffectList(
                        (_scale_effect(effect, multiplier) for effect in current),
                        skipped=current.skipped,
                    )
            effects.extend(current)
            effects.skipped.extend(current.skipped)
        else:
            effects.skipped.append(
                f"{mod.get('path') or query}: compatibility "
                f"{mod.get('compatibility')} does not match weapon"
            )
        applied_rank = rank
        if applied_rank is None:
            applied_rank = mod.get("maxRank")
            if applied_rank is None:
                applied_rank = 0
        selected_mods.append(
            {
                **record_identity(mod),
                "rank": applied_rank,
                "maxRank": mod.get("maxRank"),
                "compatible": compatible,
                **({"modSet": mod.get("modSet")} if mod.get("modSet") else {}),
                **({"setPieces": pieces} if set_id else {}),
                "displayEffects": [
                    {
                        "upgradeType": effect.upgrade_type,
                        "damageType": effect.damage_type,
                        "operation": effect.operation,
                        "value": effect.value,
                    }
                    for effect in current
                    if effect.supported
                ],
                **({
                    "steadyStacks": [
                        {
                            "conditionTag": str(conditional.get("conditionTag") or ""),
                            "stacks": conditional["maxStacks"],
                        }
                        for conditional in mod.get("conditionalEffects") or ()
                        if isinstance(conditional, Mapping)
                        and isinstance(conditional.get("maxStacks"), int)
                        and "killcondition" in str(conditional.get("conditionTag") or "").casefold()
                    ]
                } if any(
                    isinstance(conditional, Mapping)
                    and isinstance(conditional.get("maxStacks"), int)
                    and "killcondition" in str(conditional.get("conditionTag") or "").casefold()
                    for conditional in mod.get("conditionalEffects") or ()
                ) else {}),
                **({"slot": slot} if slot is not None else {}),
            }
        )
        selected_cards.append(
            {
                **dict(mod),
                "rank": applied_rank,
                **({"slot": slot} if slot is not None else {}),
            }
        )

    loadout_validation: dict[str, Any] = {
        "compatibility": "checked-from-export-ancestry",
        "capacity": "not-evaluated",
        "polarity": "not-evaluated",
    }
    if validate_loadout_slots:
        loadout_validation = validate_loadout(
            weapon_record,
            selected_cards,
            slot_count=slot_count,
            capacity_limit=capacity_limit,
            slot_polarities=slot_polarities,
        )
        loadout_validation["compatibility"] = "checked-from-export-ancestry"
        loadout_validation["polarity"] = "checked"
        loadout_validation["polarityDetails"] = {
            "status": "checked",
            "source": loadout_validation["polaritySource"],
            "slots": loadout_validation["slotPolarities"],
        }

    # Structured set shells are synthetic effects; runtime-script shells remain
    # explicit unsupported diagnostics instead of being guessed.
    for set_id, pieces in active_set_pieces.items():
        shell = shells.get(set_id)
        if shell:
            shell_effects = _set_shell_effects(shell, pieces, scenario)
            effects.extend(shell_effects)
            effects.skipped.extend(shell_effects.skipped)
    effects.skipped.extend(set_diagnostics)

    # Arcanes/Incarnon passives are already normalized ModEffects by their
    # adapter.  Keep them on this same reducer path instead of maintaining a
    # second damage implementation in the HTTP layer.
    passive_list = list(passive_effects)
    if riven_slot is not None:
        riven_terms = [e for e in passive_list if str(e.source_path or '').startswith('riven:')]
        passive_list = [e for e in passive_list if not str(e.source_path or '').startswith('riven:')]
        at = riven_effect_index if riven_effect_index is not None else len(effects)
        effects[at:at] = riven_terms
    effects.extend(passive_list)
    effects.skipped.extend(getattr(passive_effects, "skipped", ()))

    try:
        probe_scenario = replace(scenario, victim_status_count=0)
        probe_stats = apply_mods(
            weapon_record, effects, fire_mode=fire_mode, scenario=probe_scenario
        )
        scenario = replace(
            scenario,
            victim_status_count=expected_victim_status_count(
                probe_stats, forced_procs=forced_procs
            ),
        )
        stats = apply_mods(
            weapon_record, effects, fire_mode=fire_mode, scenario=scenario
        )
        if engine_context_sink is not None:
            engine_context_sink.update(weapon=weapon_record, effects=effects, scenario=scenario, fire_mode=fire_mode)
        target_damage = damage_against(
            stats,
            enemy_record,
            level=level,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            hit_location=normalized_hit_location,
        )
        kill_metrics = enemy_kill_metrics(
            stats,
            enemy_record,
            level=level,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            hit_location=normalized_hit_location,
        )
        status_damage = expected_status_damage(
            stats,
            enemy_record,
            forced_procs=forced_procs,
            level=level,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            hit_location=normalized_hit_location,
        )
        status = status_damage["expectedProcs"]
        dot = status_damage["dot"]
        status_sustained = sustained_status_damage(
            stats,
            enemy_record,
            attacks_per_second=stats.sustained_attack_rate,
            status_rate_multiplier=float(status_rate_multiplier),
            damage_rate_multiplier=float(damage_rate_multiplier),
            forced_procs=forced_procs,
            level=level,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            hit_location=normalized_hit_location,
        )
        projectile_events = evaluate_projectile_events(
            weapon_record,
            effects,
            fire_mode=fire_mode,
            scenario=scenario,
            target=enemy_record,
            level=level,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            hit_location=normalized_hit_location,
        )
    except (TypeError, ValueError) as exc:
        raise SimulationError(str(exc)) from exc

    modded = asdict(stats)
    modded.update(
        {
            # wiki/面板口径的「总伤害」：每弹丸伤害 × 弹丸数（Hek 75×7=525，
            # 与 wiki「Total Damage 525」一致）。perProjectileDamage 保留每弹丸
            # 值供触发/DoT 管线内部消费（期望计算仍按 per-pellet×multishot）。
            "totalDamage": stats.total_damage * max(stats.multishot, 1.0),
            "perProjectileDamage": stats.total_damage,
            "averageHit": stats.average_hit * max(stats.multishot, 1.0),
            "burstDps": stats.burst_dps,
            "sustainedDps": stats.sustained_dps,
            "damageTypes": dict(stats.damage_types),
            "innateDamageTypes": dict(stats.innate_damage_types),
            "innateElementCandidates": list(stats.innate_element_candidates),
            "critChance": stats.crit_chance,
            "critMultiplier": stats.crit_multiplier,
            "statusChance": stats.status_chance,
            "fireRate": stats.fire_rate,
            "reloadTime": stats.reload_time,
            "falloffMultiplier": stats.falloff_multiplier,
            "noncritDamageMultiplier": stats.noncrit_damage_multiplier,
            "doubleCritChance": stats.double_crit_chance,
            # 膛室家族首发加成（最终伤害乘区，弹匣第一发）。
            "firstShotDamageBonus": stats.first_shot_damage_bonus,
            "firstShotHit": stats.first_shot_hit,
            # CO emergent 回放：面板预乘的 CO 因子与假定层数（窗口模型剥离
            # 预乘并按每步实际活异常类型数重算）。
            "statusConditionDamageMultiplier": stats.status_condition_damage_multiplier,
            "coAssumedCount": getattr(stats, "co_assumed_count", 0.0),
        }
    )
    unsupported = sorted(
        {
            *stats.unsupported,
            *target_damage.get("unsupported", ()),
            *kill_metrics.get("unsupported", ()),
            *status_damage.get("unsupported", ()),
            *(projectile_events or {}).get("unsupported", ()),
            *weapon_record.get("kitgunUnsupported", ()),
            *(() if not validate_loadout_slots or loadout_validation.get("valid") else ("loadout-over-capacity",)),
        }
    )
    return {
        "buildLabel": exports["buildLabel"],
        "schemaVersion": exports["schemaVersion"],
        "exportDir": exports["path"],
        "selection": {
            "weapon": record_identity(weapon_record),
            "kitgunParts": list(kitgun_parts),
            "mods": selected_mods,
            "setPieces": dict(active_set_pieces),
            "enemy": record_identity(enemy_record),
            "fireMode": fire_mode,
            "scenario": {
                "aiming": scenario.aiming,
                "heavyAttack": scenario.heavy_attack,
                "comboTier": scenario.combo_tier,
                "victimStatusCount": scenario.victim_status_count,
                "conditionalStacks": dict(scenario.conditional_stacks),
                "distance": scenario.distance,
                "cloaked": scenario.cloaked,
                "nearestEnemyDistance": scenario.nearest_enemy_distance,
                "headshot": normalized_hit_location == "head",
                "hitLocation": normalized_hit_location,
            },
            "targetLevel": level,
            "armourStrip": armour_strip,
            "elementalArmourStrip": elemental_armour_strip,
            "steelPath": steel_path,
            "enemyEnhancements": dict(enemy_enhancements or {}),
        },
        "loadoutValidation": {
            **loadout_validation,
        },
        "moddedStats": modded,
        "targetDamage": target_damage,
        "killMetrics": kill_metrics,
        "statusProcs": status,
        "statusDamage": status_damage,
        "statusSustained": status_sustained,
        "dot": dot,
        **({"projectileEvents": projectile_events} if projectile_events else {}),
        "unsupported": unsupported,
        "skipped": stats.skipped,
    }


def _latest_export_dir() -> Path:
    root = Path(__file__).resolve().parents[2] / "data" / "export"
    candidates = [
        path
        for path in root.iterdir()
        if path.is_dir()
        and all((path / f"{name}.json").is_file() for name in EXPORT_NAMES)
    ] if root.is_dir() else []
    if not candidates:
        raise SimulationError(f"no complete export directory under {root}")
    return sorted(candidates, key=lambda path: path.name)[-1]


def _split_assignment(value: str, *, label: str) -> tuple[str, str]:
    key, separator, raw = value.rpartition("=")
    if not separator or not key or not raw:
        raise argparse.ArgumentTypeError(f"{label} must use NAME=VALUE")
    return key, raw


def _mod_spec(value: str) -> tuple[str, int | None]:
    query, separator, raw_rank = value.rpartition("=")
    if not separator:
        return value, None
    if not query or not raw_rank:
        raise argparse.ArgumentTypeError("mod must use QUERY or QUERY=RANK")
    try:
        return query, int(raw_rank)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("mod rank must be an integer") from exc


def _int_assignment(value: str) -> tuple[str, int]:
    key, raw = _split_assignment(value, label="condition")
    try:
        return key, int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("condition stack must be an integer") from exc


def _float_assignment(value: str) -> tuple[str, float]:
    key, raw = _split_assignment(value, label="forced proc")
    try:
        return key, float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("forced proc count must be a number") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Simulate one weapon loadout against one enemy from frozen exports."
    )
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument("--weapon", help="exact path or unique name")
    parser.add_argument("--enemy", help="exact path or unique name")
    parser.add_argument(
        "--riven-request",
        help="compact JSON request for baseline/actual/optimal Riven analysis",
    )
    parser.add_argument(
        "--kitgun-part",
        action="append",
        default=[],
        metavar="PART_PATH",
        help="repeatable component path for a verified modular Kitgun",
    )
    parser.add_argument(
        "--mod",
        action="append",
        default=[],
        type=_mod_spec,
        metavar="QUERY[=RANK]",
        help="repeatable; omitted rank means max rank",
    )
    parser.add_argument("--fire-mode", type=int, default=0)
    parser.add_argument("--distance", type=float)
    parser.add_argument(
        "--cloaked",
        action="store_true",
        help="enable explicit PM_CLOAK effects (for example Spectral Serration)",
    )
    parser.add_argument(
        "--nearest-enemy-distance",
        type=float,
        help="nearest enemy distance in metres for Range Advantage; distinct from shot distance",
    )
    parser.add_argument("--aiming", action="store_true")
    parser.add_argument("--heavy-attack", action="store_true")
    parser.add_argument("--combo-tier", type=int, default=0)
    parser.add_argument("--victim-status-count", type=int, default=0)
    parser.add_argument(
        "--condition", action="append", default=[], type=_int_assignment, metavar="KEY=STACKS"
    )
    parser.add_argument("--level", type=int)
    parser.add_argument("--armour-strip", type=float, default=0.0)
    parser.add_argument(
        "--elemental-armour-strip",
        type=float,
        default=0.0,
        help="explicit snapshot of elemental armour reduction; does not model status timing",
    )
    parser.add_argument(
        "--hit-location",
        choices=("body", "head"),
        default="body",
        help="direct-hit location; head consumes target hitProxies when exported",
    )
    parser.add_argument(
        "--steel-path",
        action="store_true",
        help="apply the 2.5x Steel Path defense multiplier; level remains explicit",
    )
    parser.add_argument(
        "--forced-proc", action="append", default=[], type=_float_assignment, metavar="DT_TYPE=COUNT"
    )
    parser.add_argument("--compact", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        export_dir = args.export_dir or _latest_export_dir()
        if args.riven_request is not None:
            try:
                request = json.loads(args.riven_request)
            except json.JSONDecodeError as exc:
                raise SimulationError(f"invalid riven request JSON: {exc}") from exc
            from .optimizer import analyze_riven_request

            result = analyze_riven_request(export_dir, request)
        else:
            if not args.weapon or not args.enemy:
                raise SimulationError(
                    "--weapon and --enemy are required unless --riven-request is used"
                )
            result = simulate(
                export_dir,
                weapon=args.weapon,
                kitgun_parts=args.kitgun_part,
                enemy=args.enemy,
                mods=args.mod,
                fire_mode=args.fire_mode,
                scenario=Scenario(
                    aiming=args.aiming,
                    heavy_attack=args.heavy_attack,
                    combo_tier=args.combo_tier,
                    victim_status_count=args.victim_status_count,
                    conditional_stacks=dict(args.condition),
                    distance=args.distance,
                    cloaked=args.cloaked,
                    nearest_enemy_distance=args.nearest_enemy_distance,
                ),
                level=args.level,
                armour_strip=args.armour_strip,
                elemental_armour_strip=args.elemental_armour_strip,
                steel_path=args.steel_path,
                hit_location=args.hit_location,
                forced_procs=dict(args.forced_proc),
            )
    except (SimulationError, TypeError, ValueError) as exc:
        error = {"error": str(exc)}
        if isinstance(exc, SimulationError) and exc.candidates:
            error["candidates"] = exc.candidates
        print(json.dumps(error, ensure_ascii=False), file=sys.stderr)
        return 2
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
