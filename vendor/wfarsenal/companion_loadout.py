"""Unified Companion Body + Modular Parts + Beast Claws + Synergy Evaluator.

Evaluates all 41 Warframe companions (17 Sentinels, 4 MOAs, 3 Hounds, 17 Beasts),
their modular assemblies (MOA Core/Gyro/Bracket, Hound Core/Bracket/Stabilizer,
Predasite/Vulpaphyla Mutagen/Antigen), paired Robotic Companion Weapons and
Beast Claws, Bond/Link/Set/Buff precept bridges to the player's Warframe and
weapons, and active 1D/3D status-priming profiles.

Data source: ``data/mechanics/companions-catalog.json``.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping, Sequence

from .damage import (
    BASE_ELEMENTS,
    DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
    DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES,
    DOT_BASE_DURATION_SECONDS,
    DOT_DAMAGE_COEFFICIENTS,
    ELEMENT_COMBINATIONS,
    PHYSICAL_TYPES,
    ModEffect,
    ModEffectList,
    ModdedStats,
    Scenario,
    _apply_elements,
    _armour_reduction,
    _faction_damage_deltas,
    _status_weights,
    apply_mods,
    damage_against,
    effective_hit_multiplier,
    enemy_defenses,
    expected_status_damage,
    expected_status_procs,
    mod_effects,
    proc_duration_scale,
    proc_stack_cap,
)
from .simulator import (
    SimulationError,
    _buff_set_multiplier,
    _effective_set_pieces,
    _mod_matches_weapon,
    _set_key,
    _set_shell_effects,
    _set_shells,
    _steady_state_scenario,
    load_exports,
    resolve_record,
)

BODY_SLOT_COUNT = 10
CLAW_NORMAL_SLOT_COUNT = 8
CLAW_POSTURE_SLOT_INDEX = 8
CLAW_TOTAL_SLOT_COUNT = 9
ROBOTIC_WEAPON_SLOT_COUNT = 8

BASE_CAPACITY = 30
REACTOR_CAPACITY = 60
COMPANION_OVERSHIELD_BASE_CAP = 1200.0
REINFORCED_BOND_SHIELD_THRESHOLD = 1200.0
TENACIOUS_BOND_CRIT_THRESHOLD = 0.50
DEFAULT_TARGET_ENEMY_PATH = "/Lotus/Types/Enemies/Orokin/OrokinHeavyFemaleAvatar"
DEFAULT_TARGET_LEVEL = 170
DEFAULT_TARGET_STEEL_PATH = True

NEUTRAL_WARFRAME_PANEL = {
    "health": 300.0,
    "shield": 300.0,
    "armor": 100.0,
}

FORMA_POLARITIES = frozenset({
    "AP_UNIVERSAL",
    "AP_ATTACK",
    "AP_DEFENSE",
    "AP_TACTIC",
    "AP_POWER",
    "AP_WARD",
    "AP_PRECEPT",
    "AP_UMBRA",
    "AP_ANY",
})

POLARITY_ALIASES = {
    "AP_ATTACK": "AP_ATTACK",
    "MADURAI": "AP_ATTACK",
    "AP_DEFENSE": "AP_DEFENSE",
    "VAZARIN": "AP_DEFENSE",
    "AP_TACTIC": "AP_TACTIC",
    "NARAMON": "AP_TACTIC",
    "AP_PRECEPT": "AP_PRECEPT",
    "AP_PENJAGA": "AP_PRECEPT",
    "PENJAGA": "AP_PRECEPT",
    "AP_POWER": "AP_POWER",
    "ZENURIK": "AP_POWER",
    "AP_WARD": "AP_WARD",
    "UNAIRU": "AP_WARD",
    "AP_UMBRA": "AP_UMBRA",
    "UMBRA": "AP_UMBRA",
    "AP_ANY": "AP_ANY",
    "OMNI": "AP_ANY",
    "AP_UNIVERSAL": "AP_UNIVERSAL",
    "UNIVERSAL": "AP_UNIVERSAL",
    "AP_NONE": "AP_UNIVERSAL",
    "NONE": "AP_UNIVERSAL",
}

COMPOUND_ELEMENTS = frozenset(ELEMENT_COMBINATIONS.values())
ALL_CONVERTIBLE_ELEMENTS = frozenset(BASE_ELEMENTS) | COMPOUND_ELEMENTS

FIRED_UP_PATH = "/Lotus/Upgrades/Mods/Sentinel/SentinelOverheatDamageMod"
ASTRAL_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum"
MOMENTOUS_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/EximusHunter"
TENACIOUS_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TenaciousPartner"
REINFORCED_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/AlacrityField"
MANIFOLD_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/CompoundingLaceration"
CONTAGIOUS_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Proliferation"
VICIOUS_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BoneSplitter"
MYSTIC_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PreyDrive"
TANDEM_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TandemTactics"
DUPLEX_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidClone"
SEISMIC_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BondedExaltation"
AERIAL_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Copilot"
RESTORATIVE_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/MutualNourishment"
COVERT_BOND_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PredatoryResponse"

HARD_ENGAGE_PATH = "/Lotus/Upgrades/Mods/Sentinel/Moa/MoaMeleeMod"
MOA_MELEE_WEAPON_PATH = "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/MoaPetMeleeWeapon"
MOA_MELEE_WEAPON_ALIASES = frozenset({
    MOA_MELEE_WEAPON_PATH.casefold(),
    "/lotus/types/friendly/pets/moapets/moapetmeleeweapon",
    "moapetmeleeweapon",
})
SHIVERING_CONTAGION_PATH = "/Lotus/Upgrades/Mods/Rifle/WeaponSpreadFreezeProcsMod"
CATS_EYE_PATH = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowCatsEyePrecept"
AMBUSH_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/GhostAugmentCard"
ANABOLIC_POLLINATION_PATH = "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorBuffSporesPrecept"
CHARM_PATH = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowLuckPrecept"
SHIELD_CHARGER_PATH = "/Lotus/Types/Sentinels/SentinelPrecepts/Events/CorpusArena/ShieldAuraPrecept"
SHARPENED_CLAWS_PATH = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowShredPrecept"
TEK_ENHANCE_PATH = "/Lotus/Upgrades/Mods/Sets/Tek/KavatTekEnhanceMod"

DECONSTRUCTOR_PATHS = frozenset({
    "/Lotus/Types/Sentinels/SentinelWeapons/SentGlaiveWeapon",
    "/Lotus/Types/Sentinels/SentinelWeapons/DeconstructorPrime/PrimeHeliosGlaiveWeapon",
})
HOUND_MELEE_PATHS = frozenset({
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeapon",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIP",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIS",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponPS",
})
HOUND_OFFENSIVE_PRECEPTS = frozenset({
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetTeslaShotPrecept",     # Synergized Prospectus
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetMegaLaserPrecept",     # Focused Prospectus
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetPhotonStrikePrecept",  # Aerial Prospectus
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetDisarmPulsePrecept",   # Repo Audit
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetStealEximusPrecept",   # Null Audit
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetAntiMeleePrecept",     # Equilibrium Audit
})

BODY_STAT_UPGRADES = {
    "AVATAR_HEALTH_MAX": "health",
    "AVATAR_SHIELD_MAX": "shield",
    "AVATAR_ARMOUR": "armor",
    "AVATAR_SHIELD_RECHARGE_RATE": "shieldRecharge",
    "AVATAR_SHIELD_RECHARGE_DELAY": "shieldDelay",
}
LINK_STAT_UPGRADES = {
    "AVATAR_SENTINEL_HEALTH_LINK": "health",
    "AVATAR_SENTINEL_SHIELD_LINK": "shield",
    "AVATAR_SENTINEL_ARMOUR_LINK": "armor",
}

CLAW_PHYSICAL_CONVERSIONS = {
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/BeastBruteConditioningMod": "DT_IMPACT",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/BeastDisablingConditioningMod": "DT_PUNCTURE",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/BeastPrecisionConditioningMod": "DT_SLASH",
}
CLAW_ELEMENTAL_CONVERSIONS = {
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowHeatConversionMod": "DT_FIRE",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowColdConversionMod": "DT_FREEZE",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowElectricConversionMod": "DT_ELECTRICITY",
    "/Lotus/Upgrades/Mods/Sentinel/Kubrow/BeastWeapon/KubrowToxicConversionMod": "DT_POISON",
}

# Steady-state status durations and victim stack caps (matching damage.py).
STATUS_PRIMING_RULES: dict[str, tuple[float, float]] = {
    "DT_VIRAL": (6.0, 10.0),
    "DT_CORROSIVE": (8.0, 10.0),
    "DT_MAGNETIC": (6.0, 10.0),
    "DT_FREEZE": (6.0, 10.0),
    "DT_PUNCTURE": (10.0, 5.0),
    "DT_IMPACT": (6.0, 5.0),
    "DT_FIRE": (6.0, math.inf),
    "DT_ELECTRICITY": (6.0, math.inf),
    "DT_POISON": (6.0, math.inf),
    "DT_SLASH": (6.0, math.inf),
    "DT_GAS": (6.0, 10.0),
    "DT_RADIATION": (12.0, 10.0),
    "DT_EXPLOSION": (1.5, 10.0),
    "DT_RADIANT": (3.0, 1.0),
    "DT_SENTIENT": (8.0, 10.0),
}

MODULAR_SLOT_PLURAL = {
    "model": "models",
    "core": "cores",
    "gyro": "gyros",
    "bracket": "brackets",
    "stabilizer": "stabilizers",
    "mutagen": "mutagens",
    "antigen": "antigens",
}
MODULAR_ALLOWED_SLOTS: dict[str, frozenset[str]] = {
    "moa": frozenset({"model", "core", "gyro", "bracket"}),
    "hound": frozenset({"model", "core", "bracket", "stabilizer"}),
    "vulpaphyla": frozenset({"mutagen", "antigen"}),
    "predasite": frozenset({"mutagen", "antigen"}),
}


def _runtime_root() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    if (base / "data/mechanics/companions-catalog.json").is_file():
        return base
    env_root = os.environ.get("WF_RIVEN_ROOT")
    if env_root:
        cand = Path(env_root).resolve()
        if (cand / "data/mechanics/companions-catalog.json").is_file():
            return cand
    return base


@lru_cache(maxsize=1)
def _raw_catalog() -> dict[str, Any]:
    path = _runtime_root() / "data/mechanics/companions-catalog.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SimulationError(f"missing companion catalog: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SimulationError(f"invalid companion catalog {path}: {exc}") from exc
    if not isinstance(payload, Mapping) or payload.get("schemaVersion") != 1:
        raise SimulationError("unsupported companions-catalog.json schemaVersion")
    return payload


def _build_companion_weapons(
    exports: Mapping[str, Any] | None = None,
    catalog_weapons: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    from . import optimizer

    raw_ai = _raw_catalog().get("weaponAiProfiles") or {}
    exp = exports if exports is not None else _default_exports()
    exp_by_path = {
        str(w["path"]): w
        for w in (exp.get("weapons") or ())
        if isinstance(w, Mapping) and w.get("path")
    }
    source_rows = (
        [r for r in catalog_weapons if isinstance(r, Mapping) and str(r.get("slot") or "") == "companion"]
        if catalog_weapons is not None
        else [w for w in (exp.get("weapons") or ()) if isinstance(w, Mapping) and str(w.get("slot") or "") == "companion"]
    )
    out: list[dict[str, Any]] = []
    for row in source_rows:
        wpath = str(row.get("path") or "")
        if not wpath:
            continue
        is_virtual = wpath.casefold() in MOA_MELEE_WEAPON_ALIASES
        exp_row = exp_by_path.get(wpath, row)
        raw_disp = row.get("omegaAttenuation")
        if raw_disp is None:
            raw_disp = row.get("disposition")
        if raw_disp is None:
            raw_disp = exp_row.get("omegaAttenuation")
        disp = 0.0 if is_virtual else float(raw_disp if raw_disp is not None else 1.0)
        legacy_disp = (
            0.0
            if is_virtual
            else float(
                exp_row.get("legacyOmegaAttenuation")
                if exp_row.get("legacyOmegaAttenuation") is not None
                else disp
            )
        )
        rtype = None if is_virtual else str(optimizer._riven_type(None, exp_row))
        ai_prof = raw_ai.get(wpath) if isinstance(raw_ai.get(wpath), Mapping) else {}
        enriched = dict(row)
        enriched.setdefault("slot", "companion")
        enriched.setdefault("weaponType", "companion")
        enriched.setdefault("available", True)
        enriched.setdefault("buildAvailable", True)
        if ai_prof.get("portraitAsset") and not enriched.get("portraitAsset"):
            enriched["portraitAsset"] = ai_prof["portraitAsset"]
        enriched["disposition"] = disp
        enriched["omegaAttenuation"] = disp
        enriched["legacyDisposition"] = legacy_disp
        enriched["rivenType"] = rtype
        enriched["isVirtualMoaMelee"] = bool(is_virtual)
        out.append(enriched)
    if not any(item.get("isVirtualMoaMelee") for item in out):
        moa_rec = _moa_melee_weapon_record(5)
        moa_ai = raw_ai.get(MOA_MELEE_WEAPON_PATH) if isinstance(raw_ai.get(MOA_MELEE_WEAPON_PATH), Mapping) else {}
        moa_rec["weaponType"] = "companion"
        moa_rec["available"] = True
        moa_rec["buildAvailable"] = True
        if moa_ai.get("portraitAsset"):
            moa_rec["portraitAsset"] = moa_ai["portraitAsset"]
        moa_rec["disposition"] = 0.0
        moa_rec["omegaAttenuation"] = 0.0
        moa_rec["legacyDisposition"] = 0.0
        moa_rec["rivenType"] = None
        moa_rec["isVirtualMoaMelee"] = True
        out.append(moa_rec)
    return out


@lru_cache(maxsize=1)
def catalog() -> dict[str, Any]:
    """Return the UI-ready static companion catalog."""
    raw = _raw_catalog()
    comp_weapons = _build_companion_weapons()
    return {
        "schemaVersion": raw["schemaVersion"],
        "buildLabel": raw["buildLabel"],
        "frozenExportBuild": raw.get("frozenExportBuild"),
        "capacity": dict(raw["capacity"]),
        "counts": dict(raw["counts"]),
        "companions": list(raw["companions"]),
        "modularParts": raw["modularParts"],
        "beastClaws": list(raw["beastClaws"]),
        "clawMods": list(raw["clawMods"]),
        "bodyMods": list(raw["bodyMods"]),
        "weaponAiProfiles": dict(raw["weaponAiProfiles"]),
        "companionWeapons": comp_weapons,
        "weapons": comp_weapons,
    }


def get_companion_catalog(
    exports: Mapping[str, Any] | None = None,
    *,
    catalog_weapons: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the companion catalog including enriched ``companionWeapons`` Riven metadata."""
    if exports is None and catalog_weapons is None:
        return catalog()
    base = dict(catalog())
    comp_weapons = _build_companion_weapons(exports=exports, catalog_weapons=catalog_weapons)
    base["companionWeapons"] = comp_weapons
    base["weapons"] = comp_weapons
    return base


@lru_cache(maxsize=1)
def _indices() -> dict[str, Any]:
    raw = _raw_catalog()
    companions_by_key: dict[str, Mapping[str, Any]] = {}
    for comp in raw["companions"]:
        companions_by_key[comp["path"]] = comp
        companions_by_key[comp["path"].casefold()] = comp
        companions_by_key[comp["id"].casefold()] = comp
        companions_by_key[comp["nameEn"].casefold()] = comp
        if comp.get("nameZh"):
            companions_by_key[comp["nameZh"].casefold()] = comp

    parts_by_family_slot: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for family, slots in raw["modularParts"].items():
        for slot_name, plural in MODULAR_SLOT_PLURAL.items():
            rows = slots.get(plural) or ()
            if not rows:
                continue
            bucket: dict[str, Mapping[str, Any]] = {}
            for part in rows:
                bucket[part["path"]] = part
                bucket[part["path"].casefold()] = part
                bucket[part["id"].casefold()] = part
                bucket[part["nameEn"].casefold()] = part
            parts_by_family_slot[(family, slot_name)] = bucket

    claws_by_key: dict[str, Mapping[str, Any]] = {}
    for claw in raw["beastClaws"]:
        claws_by_key[claw["path"]] = claw
        claws_by_key[claw["path"].casefold()] = claw
        claws_by_key[claw["id"].casefold()] = claw
        claws_by_key[claw["nameEn"].casefold()] = claw

    claw_mods_by_key: dict[str, Mapping[str, Any]] = {}
    for mod in raw["clawMods"]:
        claw_mods_by_key[mod["path"]] = mod
        claw_mods_by_key[mod["path"].casefold()] = mod
        claw_mods_by_key[mod["id"].casefold()] = mod
        claw_mods_by_key[mod["nameEn"].casefold()] = mod

    body_mods_by_key: dict[str, Mapping[str, Any]] = {}
    for mod in raw["bodyMods"]:
        body_mods_by_key[mod["path"]] = mod
        body_mods_by_key[mod["path"].casefold()] = mod
        body_mods_by_key[mod["id"].casefold()] = mod
        body_mods_by_key[mod["nameEn"].casefold()] = mod

    return {
        "companions": companions_by_key,
        "parts": parts_by_family_slot,
        "claws": claws_by_key,
        "clawMods": claw_mods_by_key,
        "bodyMods": body_mods_by_key,
        "aiProfiles": raw["weaponAiProfiles"],
    }


@lru_cache(maxsize=1)
def _default_exports() -> dict[str, Any]:
    root = _runtime_root()
    lock_path = root / "data/source-lock.json"
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
        snap = lock.get("snapshotRoot")
        droot = (root / snap).resolve() if snap else root
        build = str(lock.get("activeBuild") or _raw_catalog().get("frozenExportBuild") or "")
        exp = droot / "data/export" / build
        if exp.is_dir():
            return load_exports(exp)
    fallback_build = str(_raw_catalog().get("frozenExportBuild") or "2026.08.13.13.24")
    return load_exports(root / "data/export" / fallback_build)


def _finite_float(value: Any, label: str, *, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SimulationError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise SimulationError(f"{label} must be a finite number")
    return result


def _normalize_polarity_override(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SimulationError(f"{label} must be a polarity string or null")
    token = POLARITY_ALIASES.get(value.strip().upper())
    if token is None or token not in FORMA_POLARITIES:
        raise SimulationError(f"{label} is not a recognized polarity: {value!r}")
    return token


def _resolve_slot_polarities(
    native_slots: Sequence[str | None],
    overrides: Any,
    *,
    slot_count: int,
    label: str,
) -> tuple[list[str | None], int]:
    base = [None if p in (None, "AP_UNIVERSAL", "") else p for p in native_slots[:slot_count]]
    while len(base) < slot_count:
        base.append(None)
    if overrides is None:
        return list(base), 0
    if not isinstance(overrides, (list, tuple)) or len(overrides) > slot_count:
        raise SimulationError(f"{label} must be an array of at most {slot_count} entries")
    resolved = list(base)
    for idx, raw in enumerate(overrides):
        if raw is None:
            continue
        pol = _normalize_polarity_override(raw, f"{label}[{idx}]")
        resolved[idx] = None if pol == "AP_UNIVERSAL" else pol
    forma_count = sum(1 for a, b in zip(resolved, base) if a != b)
    return resolved, forma_count


def _normal_slot_drain(base_drain: int, rank: int, mod_polarity: str | None, slot_polarity: str | None) -> tuple[int, str]:
    raw = int(base_drain) + int(rank)
    mod_pol = None if mod_polarity in (None, "", "AP_UNIVERSAL") else mod_polarity
    slot_pol = None if slot_polarity in (None, "", "AP_UNIVERSAL") else slot_polarity
    if not mod_pol or not slot_pol:
        return raw, "unpolarized"
    if mod_pol == slot_pol or (slot_pol == "AP_ANY" and mod_pol != "AP_UMBRA") or (mod_pol == "AP_ANY" and slot_pol != "AP_UMBRA"):
        return math.ceil(raw / 2), "matched"
    return math.ceil(raw * 1.25), "mismatched"


def _posture_slot_grant(base_drain: int, rank: int, mod_polarity: str | None, slot_polarity: str | None) -> tuple[int, str]:
    raw = abs(int(base_drain)) + int(rank)
    mod_pol = None if mod_polarity in (None, "", "AP_UNIVERSAL") else mod_polarity
    slot_pol = None if slot_polarity in (None, "", "AP_UNIVERSAL") else slot_polarity
    if not mod_pol or not slot_pol:
        return raw, "unpolarized"
    if mod_pol == slot_pol or (slot_pol == "AP_ANY" and mod_pol != "AP_UMBRA") or (mod_pol == "AP_ANY" and slot_pol != "AP_UMBRA"):
        return raw * 2, "matched"
    return math.floor(raw * 0.8), "mismatched"


def _upgrade_value_at_rank(upgrade: Mapping[str, Any], rank: int) -> float:
    rank_values = upgrade.get("rankValues")
    if isinstance(rank_values, Sequence) and 0 <= rank < len(rank_values):
        return float(rank_values[rank])
    return float(upgrade.get("value") or 0.0) * (rank + 1)


def _script_params(mod: Mapping[str, Any], function: str) -> Mapping[str, Any]:
    for block in mod.get("scripts") or ():
        if block.get("function") == function and isinstance(block.get("params"), Mapping):
            return block["params"]
    return {}


def _canonical_mod_family(mod: Mapping[str, Any]) -> str:
    explicit = str(mod.get("modFamily") or mod.get("family") or "").strip().casefold()
    mpath = str(mod.get("path") or "").strip().casefold()
    try:
        from .mod_families import canonical_mod_family  # type: ignore[import-not-found]
    except ImportError:
        canonical_mod_family = None
    if canonical_mod_family is not None:
        try:
            resolved = canonical_mod_family(mod)
        except TypeError:
            resolved = canonical_mod_family(mod.get("path") or "")
        if resolved:
            norm = str(resolved).strip().casefold()
            if norm and (norm != mpath or not explicit):
                return norm
    if explicit:
        return explicit
    return str(mod.get("nameTag") or mpath).strip().casefold()


def _serialize_effect(effect: ModEffect) -> dict[str, Any]:
    out: dict[str, Any] = {
        "upgradeType": effect.upgrade_type,
        "operation": effect.operation,
        "value": effect.value,
    }
    if effect.damage_type:
        out["damageType"] = effect.damage_type
    if effect.symbol_filter:
        out["symbolFilter"] = effect.symbol_filter
    if effect.source_path:
        out["sourcePath"] = effect.source_path
    if effect.runtime_kind:
        out["runtimeKind"] = effect.runtime_kind
    if effect.runtime_chance is not None:
        out["runtimeChance"] = effect.runtime_chance
    if effect.runtime_threshold is not None:
        out["runtimeThreshold"] = effect.runtime_threshold
    if effect.runtime_multiplier is not None:
        out["runtimeMultiplier"] = effect.runtime_multiplier
    return out


def _deserialize_effects(specs: Sequence[Mapping[str, Any]]) -> ModEffectList:
    return ModEffectList([
        ModEffect(
            upgrade_type=str(spec["upgradeType"]),
            operation=str(spec["operation"]),
            value=float(spec["value"]),
            damage_type=spec.get("damageType"),
            symbol_filter=spec.get("symbolFilter"),
            source_path=spec.get("sourcePath"),
            runtime_kind=spec.get("runtimeKind"),
            runtime_chance=spec.get("runtimeChance"),
            runtime_threshold=spec.get("runtimeThreshold"),
            runtime_multiplier=spec.get("runtimeMultiplier"),
        )
        for spec in specs
    ])


def player_weapon_mod_effects(evaluation_or_bridge: Mapping[str, Any]) -> ModEffectList:
    """Convert ``playerBridge.playerWeaponEffects`` into an engine ``ModEffectList``."""
    bridge = (
        evaluation_or_bridge["playerBridge"]
        if isinstance(evaluation_or_bridge.get("playerBridge"), Mapping)
        else evaluation_or_bridge
    )
    return _deserialize_effects(bridge.get("playerWeaponEffects") or ())


def companion_weapon_mod_effects(evaluation: Mapping[str, Any]) -> ModEffectList:
    """Convert body-to-companion-weapon effects into an engine ``ModEffectList``."""
    return _deserialize_effects(evaluation.get("weaponEffects") or ())


def _resolve_companion(query: Any) -> Mapping[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise SimulationError("companion.path must be a non-empty string")
    idx = _indices()["companions"]
    key = query.strip()
    comp = idx.get(key) or idx.get(key.casefold())
    if comp is None:
        raise SimulationError(f"unknown companion: {query!r}")
    return comp


def _assemble_body(
    companion: Mapping[str, Any],
    raw_parts: Any,
    *,
    gilded: bool,
) -> dict[str, Any]:
    kind = str(companion["kind"])
    family = kind if kind in MODULAR_ALLOWED_SLOTS else None
    if raw_parts is not None and not isinstance(raw_parts, Mapping):
        raise SimulationError("companion.parts must be an object or null")
    asked = dict(raw_parts or {})

    if family is None:
        non_null = {k: v for k, v in asked.items() if v is not None}
        if non_null:
            raise SimulationError(f"{companion['nameEn']} is not a modular companion and accepts no parts")
        return {
            "family": None,
            "gilded": True,
            "parts": {},
            "base": dict(companion["stats"]),
            "partPercentBonus": {"health": 0.0, "shield": 0.0, "armor": 0.0},
            "nativePolarities": list(companion["polarities"][:BODY_SLOT_COUNT]),
            "resistances": [],
            "unlockedPrecepts": list(companion.get("defaultPrecepts") or ()),
        }

    allowed_slots = MODULAR_ALLOWED_SLOTS[family]
    unknown_slots = set(asked) - allowed_slots
    if unknown_slots:
        raise SimulationError(
            f"invalid modular part slot(s) for {companion['nameEn']}: {sorted(unknown_slots)}"
        )

    part_index = _indices()["parts"]
    defaults = dict(companion.get("defaultParts") or {})
    selected_parts: dict[str, Mapping[str, Any]] = {}

    if family in {"moa", "hound"}:
        model_bucket = part_index[(family, "model")]
        own_model = model_bucket.get(companion["path"]) or model_bucket.get(companion["id"].casefold())
        if asked.get("model") is not None:
            q = str(asked["model"]).strip()
            picked_model = model_bucket.get(q) or model_bucket.get(q.casefold())
            if picked_model is None:
                raise SimulationError(f"unknown {family} model part: {asked['model']!r}")
            if own_model is not None and picked_model["path"] != own_model["path"]:
                raise SimulationError(
                    f"companion.parts.model {picked_model['nameEn']} does not match host {companion['nameEn']}"
                )
            selected_parts["model"] = picked_model
        elif own_model is not None:
            selected_parts["model"] = own_model

    for slot in sorted(allowed_slots - {"model"}):
        raw_val = asked.get(slot, defaults.get(slot))
        if raw_val is None:
            continue
        if not isinstance(raw_val, str) or not raw_val.strip():
            raise SimulationError(f"companion.parts.{slot} must be a non-empty string or null")
        bucket = part_index.get((family, slot)) or {}
        part = bucket.get(raw_val.strip()) or bucket.get(raw_val.strip().casefold())
        if part is None:
            raise SimulationError(f"{raw_val!r} is not a valid {slot} part for {companion['nameEn']}")
        selected_parts[slot] = part

    base = {k: float(companion["stats"][k]) for k in ("health", "shield", "armor")}
    base_mod = {"health": 0.0, "shield": 0.0, "armor": 0.0}
    part_pct = {"health": 0.0, "shield": 0.0, "armor": 0.0}
    native_polarities = list(companion["polarities"][:BODY_SLOT_COUNT])
    while len(native_polarities) < BODY_SLOT_COUNT:
        native_polarities.append(None)
    resistances: list[dict[str, Any]] = []
    unlocked_precepts: list[str] = []

    slot_order = ("model", "core", "gyro", "bracket", "stabilizer", "mutagen", "antigen")
    for slot in slot_order:
        part = selected_parts.get(slot)
        if part is None:
            continue
        if isinstance(part.get("baseStats"), Mapping):
            for stat in ("health", "shield", "armor"):
                if part["baseStats"].get(stat) is not None:
                    base[stat] = float(part["baseStats"][stat])
        bonus_src = part.get("bonus") if gilded else part.get("ungildedBonus")
        if isinstance(bonus_src, Mapping):
            target = base_mod if part.get("modifyBase") else part_pct
            for stat in ("health", "shield", "armor"):
                target[stat] += float(bonus_src.get(stat) or 0.0)
        pol = part.get("polarity")
        if pol:
            try:
                empty_idx = native_polarities.index(None)
                native_polarities[empty_idx] = pol
            except ValueError:
                pass
        for r in part.get("resistances") or ():
            resistances.append(dict(r))
        for p_path in part.get("preceptPaths") or ():
            if p_path not in unlocked_precepts:
                unlocked_precepts.append(p_path)

    for default_precept in companion.get("defaultPrecepts") or ():
        if family == "hound" and default_precept in HOUND_OFFENSIVE_PRECEPTS:
            continue
        if default_precept not in unlocked_precepts:
            unlocked_precepts.append(default_precept)

    assembled_base = {
        stat: base[stat] * (1.0 + base_mod[stat])
        for stat in ("health", "shield", "armor")
    }

    return {
        "family": family,
        "gilded": gilded,
        "parts": {
            slot: {
                "id": part["id"],
                "path": part["path"],
                "nameEn": part["nameEn"],
                "nameZh": part["nameZh"],
                "modifyBase": part["modifyBase"],
                "baseStats": part["baseStats"],
                "bonus": dict(part.get("bonus") or {}),
                "ungildedBonus": dict(part.get("ungildedBonus") or {}),
                "polarity": part.get("polarity"),
                "preceptPaths": list(part.get("preceptPaths") or ()),
                "resistances": [dict(r) for r in part.get("resistances") or ()],
            }
            for slot, part in selected_parts.items()
        },
        "base": assembled_base,
        "partPercentBonus": part_pct,
        "nativePolarities": native_polarities,
        "resistances": resistances,
        "unlockedPrecepts": unlocked_precepts,
    }


def _body_mod_compatible(companion: Mapping[str, Any], mod: Mapping[str, Any]) -> bool:
    compat = mod.get("compat") or {}
    blocked_kinds = compat.get("blockedKinds") or ()
    if companion["kind"] in blocked_kinds:
        return False
    blocked_paths = compat.get("blockedPaths") or ()
    if companion["path"] in blocked_paths:
        return False
    owner_paths = compat.get("ownerPaths")
    if owner_paths is not None:
        return companion["path"] in owner_paths
    compat_kind = compat.get("compatKind") or "all"
    if compat_kind == "all":
        return True
    if compat_kind == "robotic":
        return companion["category"] == "robotic"
    if compat_kind == "beast":
        return companion["category"] == "beast"
    if compat_kind == "sentinel":
        return companion["kind"] == "sentinel"
    if compat_kind == "moa":
        return companion["kind"] == "moa"
    if compat_kind == "hound":
        return companion["kind"] == "hound"
    if compat_kind == "kavat":
        return companion["kind"] in {"kavat", "vulpaphyla"}
    if compat_kind == "kubrow":
        return companion["kind"] in {"kubrow", "predasite", "charger"}
    return False


def _parse_body_mods(
    companion: Mapping[str, Any],
    raw_mods: Any,
) -> list[tuple[Mapping[str, Any], int, int]]:
    if raw_mods is None:
        return []
    if not isinstance(raw_mods, list) or len(raw_mods) > BODY_SLOT_COUNT:
        raise SimulationError(f"companion.mods must be an array of at most {BODY_SLOT_COUNT} entries")
    body_mods_idx = _indices()["bodyMods"]
    selected: list[tuple[Mapping[str, Any], int, int]] = []
    seen_paths: set[str] = set()
    seen_slots: set[int] = set()
    seen_families: dict[str, str] = {}
    moa_precept_count = 0

    for idx, entry in enumerate(raw_mods):
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise SimulationError(f"companion.mods[{idx}] must be an object")
        query = str(entry.get("path") or entry.get("id") or "").strip()
        if not query:
            raise SimulationError(f"companion.mods[{idx}].path must be a non-empty string")
        mod = body_mods_idx.get(query) or body_mods_idx.get(query.casefold())
        if mod is None:
            raise SimulationError(f"companion.mods[{idx}] is not a known companion body MOD: {query!r}")
        if not _body_mod_compatible(companion, mod):
            raise SimulationError(
                f"{mod['nameEn']} ({mod['nameZh']}) is not compatible with {companion['nameEn']}"
            )
        if mod["path"] in seen_paths:
            raise SimulationError(f"duplicate companion MOD: {mod['nameEn']}")
        seen_paths.add(mod["path"])

        family = _canonical_mod_family(mod)
        if family:
            if family in seen_families:
                raise SimulationError(
                    f"mutually exclusive companion MOD family {family!r}: "
                    f"{mod['nameEn']} conflicts with {seen_families[family]}"
                )
            seen_families[family] = mod["nameEn"]

        if mod.get("isPrecept") and (mod.get("compat") or {}).get("compatKind") == "moa":
            moa_precept_count += 1
            if moa_precept_count > 2:
                raise SimulationError("MOA companions can equip at most 2 MOA model precepts")

        max_rank = int(mod["maxRank"])
        rank = entry.get("rank", max_rank)
        if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= max_rank:
            raise SimulationError(f"companion.mods[{idx}].rank must be an integer in 0..{max_rank}")
        slot = entry.get("slot", idx)
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < BODY_SLOT_COUNT:
            raise SimulationError(f"companion.mods[{idx}].slot must be an integer in 0..{BODY_SLOT_COUNT - 1}")
        if slot in seen_slots:
            raise SimulationError(f"companion slot {slot} is assigned more than once")
        seen_slots.add(slot)
        selected.append((mod, rank, slot))

    selected.sort(key=lambda item: item[2])
    return selected


def _body_to_weapon_effects(
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    options: Mapping[str, Any],
    warnings: list[str],
) -> ModEffectList:
    effects = ModEffectList()
    for mod, rank, _slot in body_mods:
        levels = rank + 1
        path = mod["path"]
        source = f"companion:{path}"
        if path == FIRED_UP_PATH and options.get("firedUp", True) is not False:
            params = _script_params(mod, "OnHit")
            cap = float(params.get("_maxDamagePctPerLevel") or 0.0) * levels
            per_hit = float(params.get("_damagePctPerHitPerLevel") or 0.0) * levels
            duration = float(params.get("_duration") or 0.0)
            if min(cap, per_hit, duration) <= 0.0:
                warnings.append("sentinel-fired-up-script-parameters-unavailable")
                continue
            effects.append(
                ModEffect(
                    "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
                    "STACKING_MULTIPLY",
                    cap,
                    damage_type="DT_FIRE",
                    source_path=source,
                    runtime_kind="sentinel-fired-up",
                    runtime_chance=per_hit,
                    runtime_threshold=duration,
                    runtime_multiplier=cap,
                )
            )
        elif path == ASTRAL_BOND_PATH and options.get("astralBond") is True:
            params = _script_params(mod, "ApplyUpgrade")
            dmg_bonus = (
                float(params.get("_damagePctPerRank")) * levels
                if params.get("_damagePctPerRank") is not None
                else float(mod["bondSpec"]["companionDamageBonusByRank"][rank])
            )
            void_bonus = (
                float(params.get("_voidDamagePctPerRank")) * levels
                if params.get("_voidDamagePctPerRank") is not None
                else float(mod["bondSpec"]["companionVoidDamageByRank"][rank])
            )
            effects.append(
                ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", dmg_bonus, source_path=source)
            )
            effects.append(
                ModEffect(
                    "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE",
                    "STACKING_MULTIPLY",
                    void_bonus,
                    damage_type="DT_RADIANT",
                    source_path=source,
                )
            )
        elif path == MOMENTOUS_BOND_PATH and options.get("momentousElement") in BASE_ELEMENTS:
            params = _script_params(mod, "ApplyEximusHunter")
            elem_bonus = (
                float(params.get("_bonusDamagePerRank")) * levels
                if params.get("_bonusDamagePerRank") is not None
                else float(mod["bondSpec"]["companionElementalBonusByRank"][rank])
            )
            effects.append(
                ModEffect(
                    "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
                    "STACKING_MULTIPLY",
                    elem_bonus,
                    damage_type=str(options["momentousElement"]),
                    source_path=source,
                )
            )
    return effects


def _clamp_modded_stats(stats: ModdedStats) -> ModdedStats:
    return replace(
        stats,
        crit_chance=max(0.0, float(stats.crit_chance)),
        crit_multiplier=max(1.0, float(stats.crit_multiplier)),
        status_chance=max(0.0, float(stats.status_chance)),
        multishot=max(0.0, float(stats.multishot)),
        fire_rate=max(0.0, float(stats.fire_rate)),
    )


def _build_damage_composition(
    shot_damage_types: Mapping[str, float],
    proc_weight_map: Mapping[str, float],
    procs_per_shot: Mapping[str, float],
    procs_per_sec: Mapping[str, float],
) -> list[dict[str, Any]]:
    pos_items = [(str(dt), float(val)) for dt, val in shot_damage_types.items() if float(val) > 0.0]
    if not pos_items:
        return []
    pos_items.sort(key=lambda item: (-item[1], item[0]))
    total_dmg = sum(v for _, v in pos_items)
    total_pw = sum(max(0.0, float(proc_weight_map.get(dt, 0.0))) for dt, _ in pos_items)
    rows: list[dict[str, Any]] = []
    for dt, val in pos_items:
        share = (val / total_dmg) if total_dmg > 0.0 else 0.0
        p_share = (max(0.0, float(proc_weight_map.get(dt, 0.0))) / total_pw) if total_pw > 0.0 else share
        rows.append({
            "damageType": dt,
            "damage": round(val, 3),
            "share": round(share, 6),
            "procWeight": round(p_share, 6),
            "procsPerShot": round(float(procs_per_shot.get(dt, 0.0)), 4),
            "procsPerSecond": round(float(procs_per_sec.get(dt, 0.0)), 4),
        })
    if rows and total_dmg > 0.0:
        share_diff = round(1.0 - sum(r["share"] for r in rows), 6)
        if abs(share_diff) <= 5e-6 and share_diff != 0.0:
            rows[0]["share"] = round(rows[0]["share"] + share_diff, 6)
        pw_diff = round(1.0 - sum(r["procWeight"] for r in rows), 6)
        if abs(pw_diff) <= 5e-6 and pw_diff != 0.0:
            rows[0]["procWeight"] = round(rows[0]["procWeight"] + pw_diff, 6)
    return rows


def _build_radial_composition(radial_damage_types: Mapping[str, float] | None) -> list[dict[str, Any]]:
    if not radial_damage_types:
        return []
    pos_items = [(str(dt), float(val)) for dt, val in radial_damage_types.items() if float(val) > 0.0]
    if not pos_items:
        return []
    pos_items.sort(key=lambda item: (-item[1], item[0]))
    total_dmg = sum(v for _, v in pos_items)
    rows = [
        {
            "damageType": dt,
            "damage": round(val, 3),
            "share": round((val / total_dmg) if total_dmg > 0.0 else 0.0, 6),
        }
        for dt, val in pos_items
    ]
    if rows and total_dmg > 0.0:
        share_diff = round(1.0 - sum(r["share"] for r in rows), 6)
        if abs(share_diff) <= 5e-6 and share_diff != 0.0:
            rows[0]["share"] = round(rows[0]["share"] + share_diff, 6)
    return rows


def _evaluate_beast_claws(
    companion: Mapping[str, Any],
    claw: Mapping[str, Any],
    weapon_config: Mapping[str, Any],
    *,
    reactor: bool,
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    body_weapon_effects: ModEffectList,
    primary_weapon_stats: Mapping[str, Any] | None,
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if companion["category"] != "beast" or claw["breedPath"] != companion["path"]:
        raise SimulationError(f"{claw['nameEn']} cannot be equipped on {companion['nameEn']}")

    claw_mods_idx = _indices()["clawMods"]
    raw_mods = weapon_config.get("mods") or []
    if not isinstance(raw_mods, list):
        raise SimulationError("weapon.mods must be an array")
    raw_posture = weapon_config.get("posture")
    if raw_posture is not None and not isinstance(raw_posture, Mapping):
        raise SimulationError("weapon.posture must be an object or null")

    polarities_override = weapon_config.get("slotPolarities")
    if polarities_override is None:
        polarities_override = weapon_config.get("polarities")
    slot_polarities, forma_count = _resolve_slot_polarities(
        claw["polarities"],
        polarities_override,
        slot_count=CLAW_TOTAL_SLOT_COUNT,
        label="weapon.slotPolarities",
    )

    normal_entries: list[tuple[Mapping[str, Any], int, int]] = []
    posture_entry: tuple[Mapping[str, Any], int] | None = None
    seen_paths: set[str] = set()
    seen_slots: set[int] = set()
    seen_families: dict[str, str] = {}

    if raw_posture is not None:
        p_query = str(raw_posture.get("path") or raw_posture.get("id") or "").strip()
        if not p_query:
            raise SimulationError("weapon.posture.path must be a non-empty string")
        p_mod = claw_mods_idx.get(p_query) or claw_mods_idx.get(p_query.casefold())
        if p_mod is None or not p_mod.get("isPosture"):
            raise SimulationError(f"weapon.posture is not a valid Beast Claw posture MOD: {p_query!r}")
        p_max = int(p_mod["maxRank"])
        p_rank = raw_posture.get("rank", p_max)
        if isinstance(p_rank, bool) or not isinstance(p_rank, int) or not 0 <= p_rank <= p_max:
            raise SimulationError(f"weapon.posture.rank must be an integer in 0..{p_max}")
        posture_entry = (p_mod, p_rank)
        seen_paths.add(p_mod["path"])
        seen_families[_canonical_mod_family(p_mod)] = p_mod["nameEn"]

    for idx, entry in enumerate(raw_mods):
        if entry is None:
            continue
        if not isinstance(entry, Mapping):
            raise SimulationError(f"weapon.mods[{idx}] must be an object")
        query = str(entry.get("path") or entry.get("id") or "").strip()
        if not query:
            raise SimulationError(f"weapon.mods[{idx}].path must be a non-empty string")
        mod = claw_mods_idx.get(query) or claw_mods_idx.get(query.casefold())
        if mod is None:
            raise SimulationError(f"weapon.mods[{idx}] is not a Beast Claw MOD: {query!r}")

        allowed_weapons = (mod.get("compat") or {}).get("weaponPaths")
        if allowed_weapons is not None and claw["path"] not in allowed_weapons:
            raise SimulationError(f"{mod['nameEn']} is not compatible with {claw['nameEn']}")
        if mod["path"] in seen_paths:
            raise SimulationError(f"duplicate Beast Claw MOD: {mod['nameEn']}")
        seen_paths.add(mod["path"])

        family = _canonical_mod_family(mod)
        if family:
            if family in seen_families:
                raise SimulationError(
                    f"mutually exclusive Beast Claw MOD family {family!r}: "
                    f"{mod['nameEn']} conflicts with {seen_families[family]}"
                )
            seen_families[family] = mod["nameEn"]

        max_rank = int(mod["maxRank"])
        rank = entry.get("rank", max_rank)
        if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= max_rank:
            raise SimulationError(f"weapon.mods[{idx}].rank must be an integer in 0..{max_rank}")
        default_slot = CLAW_POSTURE_SLOT_INDEX if mod.get("isPosture") else idx
        slot = entry.get("slot", default_slot)
        if isinstance(slot, bool) or not isinstance(slot, int):
            raise SimulationError(f"weapon.mods[{idx}].slot must be an integer")

        if mod.get("isPosture"):
            if slot != CLAW_POSTURE_SLOT_INDEX:
                raise SimulationError(f"Posture MOD {mod['nameEn']} must be placed in posture slot {CLAW_POSTURE_SLOT_INDEX}")
            posture_entry = (mod, rank)
        else:
            if not 0 <= slot < CLAW_NORMAL_SLOT_COUNT:
                raise SimulationError(f"weapon.mods[{idx}].slot must be in 0..{CLAW_NORMAL_SLOT_COUNT - 1}")
            if slot in seen_slots:
                raise SimulationError(f"Beast Claw slot {slot} is assigned more than once")
            seen_slots.add(slot)
            normal_entries.append((mod, rank, slot))

    if len(normal_entries) > CLAW_NORMAL_SLOT_COUNT:
        raise SimulationError(f"Beast Claws have at most {CLAW_NORMAL_SLOT_COUNT} normal slots")
    normal_entries.sort(key=lambda item: item[2])

    weapon_reactor = weapon_config.get("reactor", reactor)
    if not isinstance(weapon_reactor, bool):
        raise SimulationError("weapon.reactor must be a boolean")
    base_cap = REACTOR_CAPACITY if weapon_reactor else BASE_CAPACITY

    posture_info = None
    posture_grant = 0
    if posture_entry is not None:
        p_mod, p_rank = posture_entry
        posture_grant, p_rel = _posture_slot_grant(
            p_mod["baseDrain"], p_rank, p_mod.get("polarity"), slot_polarities[CLAW_POSTURE_SLOT_INDEX]
        )
        posture_info = {
            "path": p_mod["path"],
            "id": p_mod["id"],
            "nameEn": p_mod["nameEn"],
            "nameZh": p_mod["nameZh"],
            "rank": p_rank,
            "grant": posture_grant,
            "slotPolarity": slot_polarities[CLAW_POSTURE_SLOT_INDEX],
            "polarityRelation": p_rel,
        }

    used_capacity = 0
    slot_assignments: list[dict[str, Any]] = []
    claw_set_entries: list[dict[str, Any]] = []

    base_dmg_pct = 0.0
    cc_pct = 0.0
    cd_pct = 0.0
    sc_pct = 0.0
    proc_dur_pct = 0.0
    proc_dmg_pct = 0.0
    co_bonus = 0.0
    noncrit_bonus = 0.0
    hunter_synergy_ratio = 0.0
    mecha_overdrive_ratio = 0.0
    extra_targets = 0.0
    range_add_m = 0.0
    overguard_dmg_bonus = 0.0
    attack_speed_pct = 0.0
    magnetic_strike_chance = 0.0
    forced_procs: dict[str, float] = {}
    dot_elem_bonuses: dict[str, float] = {}
    physical_conversion: str | None = None
    elemental_conversion: str | None = None
    conversion_post_element: tuple[str, float] | None = None
    pre_element_effects: list[ModEffect] = []
    post_element_effects: list[ModEffect] = []

    if posture_entry is not None:
        p_mod, p_rank = posture_entry
        levels = p_rank + 1
        if p_mod["id"] == "persistent_posture":
            pre_element_effects.append(
                ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", 0.10 * levels, damage_type="DT_IMPACT")
            )
        elif p_mod["id"] == "frenzied_posture":
            proc_dur_pct += 0.20 * levels
        elif p_mod["id"] == "protector_posture":
            forced_procs["DT_PUNCTURE"] = forced_procs.get("DT_PUNCTURE", 0.0) + 1.0 * levels
        elif p_mod["id"] == "assassin_posture":
            overguard_dmg_bonus += 0.75 * levels

    for mod, rank, slot in normal_entries:
        drain, rel = _normal_slot_drain(mod["baseDrain"], rank, mod.get("polarity"), slot_polarities[slot])
        used_capacity += drain
        slot_assignments.append({
            "slot": slot,
            "path": mod["path"],
            "id": mod["id"],
            "nameEn": mod["nameEn"],
            "rank": rank,
            "drain": drain,
            "slotPolarity": slot_polarities[slot],
            "polarityRelation": rel,
        })
        if mod.get("setId"):
            claw_set_entries.append({
                "path": mod["path"],
                "setId": mod["setId"],
                "source": "companion_weapon",
            })

        path = mod["path"]
        if mod["id"] == "bell_ringer":
            forced_procs["DT_IMPACT"] = forced_procs.get("DT_IMPACT", 0.0) + 1.0 * (rank + 1)
        elif mod["id"] == "magnetic_strike":
            magnetic_strike_chance += 0.25 * (rank + 1)

        if path in CLAW_PHYSICAL_CONVERSIONS:
            physical_conversion = CLAW_PHYSICAL_CONVERSIONS[path]
        if path in CLAW_ELEMENTAL_CONVERSIONS:
            elemental_conversion = CLAW_ELEMENTAL_CONVERSIONS[path]

        for upg in mod.get("upgrades") or ():
            utype = upg["type"]
            val = _upgrade_value_at_rank(upg, rank)
            dtype = upg.get("damageType") or "DT_ANY"
            if utype in {"WEAPON_MELEE_DAMAGE", "WEAPON_DAMAGE_AMOUNT"}:
                base_dmg_pct += val
            elif utype == "WEAPON_CRIT_CHANCE":
                cc_pct += val
            elif utype == "WEAPON_CRIT_DAMAGE":
                cd_pct += val
            elif utype == "WEAPON_PROC_CHANCE":
                sc_pct += val
            elif utype == "WEAPON_PROC_TIME":
                proc_dur_pct += val
            elif utype == "WEAPON_PROC_DAMAGE":
                proc_dmg_pct += val
            elif utype == "WEAPON_FIRE_RATE":
                attack_speed_pct += val
            elif utype == "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE":
                co_bonus += val
            elif utype == "WEAPON_NOCRIT_DAMAGE":
                noncrit_bonus += val
            elif utype == "AVATAR_SENTINEL_CRIT_LINK":
                hunter_synergy_ratio += val
            elif utype == "AVATAR_SENTINEL_STATUS_LINK":
                mecha_overdrive_ratio += val
            elif utype == "WEAPON_TARGET_AMOUNT":
                extra_targets += val
            elif utype == "WEAPON_RANGE":
                range_add_m += val
            elif utype in {"WEAPON_PERCENT_BASE_DAMAGE_ADDED", "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"}:
                if dtype in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                    dot_elem_bonuses[dtype] = dot_elem_bonuses.get(dtype, 0.0) + val
                if path in CLAW_ELEMENTAL_CONVERSIONS:
                    conversion_post_element = (CLAW_ELEMENTAL_CONVERSIONS[path], val)
                elif utype == "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE":
                    post_element_effects.append(
                        ModEffect(utype, "STACKING_MULTIPLY", val, damage_type=dtype, source_path=path)
                    )
                else:
                    pre_element_effects.append(
                        ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", val, damage_type=dtype, source_path=path)
                    )

    for eff in body_weapon_effects:
        if eff.upgrade_type in {"WEAPON_DAMAGE_AMOUNT", "WEAPON_MELEE_DAMAGE"}:
            base_dmg_pct += eff.value
        elif eff.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED":
            if eff.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                dot_elem_bonuses[eff.damage_type] = dot_elem_bonuses.get(eff.damage_type, 0.0) + eff.value
            pre_element_effects.append(eff)
        elif eff.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE":
            if eff.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                dot_elem_bonuses[eff.damage_type] = dot_elem_bonuses.get(eff.damage_type, 0.0) + eff.value
            post_element_effects.append(eff)

    raw_base_types = {str(k): float(v) for k, v in claw["damageTypes"].items() if float(v) > 0.0}
    if physical_conversion is not None:
        phys_sum = sum(raw_base_types.pop(pt, 0.0) for pt in PHYSICAL_TYPES)
        if phys_sum > 0.0:
            raw_base_types[physical_conversion] = raw_base_types.get(physical_conversion, 0.0) + phys_sum

    dmg_scale = max(0.0, 1.0 + base_dmg_pct)
    scaled_base = {dt: amt * dmg_scale for dt, amt in raw_base_types.items()}
    scaled_total = sum(scaled_base.values())

    combined = _apply_elements(
        scaled_base,
        base_total=scaled_total,
        pre=pre_element_effects,
        post=[],
    )
    if elemental_conversion is not None:
        elem_sum = sum(combined.pop(dt, 0.0) for dt in list(combined) if dt in ALL_CONVERTIBLE_ELEMENTS)
        if elem_sum > 0.0:
            combined[elemental_conversion] = combined.get(elemental_conversion, 0.0) + elem_sum
        if conversion_post_element is not None:
            conv_dt, conv_val = conversion_post_element
            combined[conv_dt] = combined.get(conv_dt, 0.0) + scaled_total * conv_val

    for eff in post_element_effects:
        if eff.damage_type and eff.damage_type != "DT_ANY":
            combined[eff.damage_type] = combined.get(eff.damage_type, 0.0) + scaled_total * eff.value

    damage_types = {dt: round(val, 6) for dt, val in combined.items() if val > 0.0}
    total_damage = round(sum(damage_types.values()), 6)

    primary_cc = 0.0
    primary_sc = 0.0
    if isinstance(primary_weapon_stats, Mapping):
        primary_cc = _finite_float(
            primary_weapon_stats.get("critChance", primary_weapon_stats.get("crit_chance")),
            "primary_weapon_stats.critChance",
        )
        primary_sc = _finite_float(
            primary_weapon_stats.get("statusChance", primary_weapon_stats.get("status_chance")),
            "primary_weapon_stats.statusChance",
        )
    elif (hunter_synergy_ratio > 0.0 or mecha_overdrive_ratio > 0.0):
        warnings.append(
            "companion-primary-link-without-primary-stats: Hunter Synergy / Mecha Overdrive equipped without primary_weapon_stats"
        )

    modded_cc = max(0.0, float(claw["critChance"]) * (1.0 + cc_pct) + hunter_synergy_ratio * max(0.0, primary_cc))
    modded_cd = max(1.0, float(claw["critMultiplier"]) * (1.0 + cd_pct))
    modded_sc = max(0.0, float(claw["statusChance"]) * (1.0 + sc_pct) + mecha_overdrive_ratio * max(0.0, primary_sc))
    attack_speed = max(0.0, float(claw["attackSpeed"]) * (1.0 + attack_speed_pct))
    proc_dur_mult = max(0.0, 1.0 + proc_dur_pct)
    proc_dmg_mult = max(0.0, 1.0 + proc_dmg_pct)
    noncrit_mult = 1.0 + max(0.0, noncrit_bonus)

    vicious_strip = 0.0
    sharpened_strip = 0.0
    for b_mod, b_rank, _ in body_mods:
        if b_mod["path"] == VICIOUS_BOND_PATH:
            vicious_strip = float(b_mod["bondSpec"]["armorStripFractionByRank"][b_rank])
        elif b_mod["path"] == SHARPENED_CLAWS_PATH:
            sharpened_strip = min(1.0, 0.30 * (b_rank + 1))
    armor_strip_on_hit = min(1.0, vicious_strip + sharpened_strip)

    expected_procs: dict[str, float] = {}
    if total_damage > 0.0 and modded_sc > 0.0:
        for dt, amt in damage_types.items():
            expected_procs[dt] = modded_sc * (amt / total_damage)
    for dt, cnt in forced_procs.items():
        expected_procs[dt] = expected_procs.get(dt, 0.0) + cnt
    if magnetic_strike_chance > 0.0 and expected_procs.get("DT_IMPACT", 0.0) > 0.0:
        expected_procs["DT_MAGNETIC"] = expected_procs.get("DT_MAGNETIC", 0.0) + (
            expected_procs["DT_IMPACT"] * min(1.0, magnetic_strike_chance)
        )

    sustained_procs_per_sec = {
        dt: cnt * attack_speed
        for dt, cnt in expected_procs.items()
        if cnt > 0.0 and attack_speed > 0.0
    }

    hit_mult = effective_hit_multiplier(modded_cc, modded_cd, noncrit_mult)
    average_hit = sum(combined.values()) * hit_mult
    burst_dps = average_hit * attack_speed
    sustained_dps = burst_dps

    claw_dot_elems = {
        "DT_SLASH": 1.0,
        "DT_FIRE": max(0.0, 1.0 + dot_elem_bonuses.get("DT_FIRE", 0.0)),
        "DT_POISON": max(0.0, 1.0 + dot_elem_bonuses.get("DT_POISON", 0.0)),
        "DT_ELECTRICITY": max(0.0, 1.0 + dot_elem_bonuses.get("DT_ELECTRICITY", 0.0)),
        "DT_GAS": max(0.0, 1.0 + dot_elem_bonuses.get("DT_GAS", 0.0)),
    }
    claw_modded_stats = ModdedStats(
        damage_types={dt: float(val) for dt, val in combined.items() if val > 0.0},
        crit_chance=modded_cc,
        crit_multiplier=modded_cd,
        status_chance=modded_sc,
        multishot=1.0,
        fire_rate=attack_speed,
        magazine=0.0,
        reload_time=0.0,
        proc_damage_multiplier=proc_dmg_mult,
        proc_duration_multiplier=proc_dur_mult,
        noncrit_damage_multiplier=noncrit_mult,
        dot_base_damage=scaled_total,
        dot_elemental_multipliers=claw_dot_elems,
    )
    extra_forced: dict[str, float] = dict(forced_procs)
    if magnetic_strike_chance > 0.0 and expected_procs.get("DT_IMPACT", 0.0) > 0.0:
        extra_forced["DT_MAGNETIC"] = extra_forced.get("DT_MAGNETIC", 0.0) + (
            expected_procs["DT_IMPACT"] * min(1.0, magnetic_strike_chance)
        )
    neutral_status = expected_status_damage(claw_modded_stats, {}, forced_procs=extra_forced or None, level=1)
    dot_dps = float(neutral_status["total"]) * attack_speed
    total_sustained_dps = round(sustained_dps + dot_dps, 3)

    damage_composition = _build_damage_composition(
        damage_types,
        damage_types,
        expected_procs,
        sustained_procs_per_sec,
    )

    total_cap = base_cap + posture_grant
    if used_capacity > total_cap:
        warnings.append(f"beast-claw-capacity-exceeded: {used_capacity}/{total_cap}")

    return (
        {
            "kind": "beast_claws",
            "path": claw["path"],
            "id": claw["id"],
            "nameEn": claw["nameEn"],
            "nameZh": claw["nameZh"],
            "portraitAsset": claw["portraitAsset"],
            "disposition": 0.0,
            "rivenType": None,
            "damageTypes": damage_types,
            "radialDamageTypes": None,
            "positiveDamageTypes": sorted(damage_types.keys()),
            "totalDamage": total_damage,
            "directTotalDamage": total_damage,
            "perProjectileDamage": total_damage,
            "averageHit": round(average_hit, 3),
            "burstDps": round(burst_dps, 3),
            "sustainedDps": round(sustained_dps, 3),
            "dotDps": round(dot_dps, 3),
            "totalSustainedDps": total_sustained_dps,
            "statusDamageMultiplier": round(proc_dmg_mult, 6),
            "factionMultipliers": {},
            "damageComposition": damage_composition,
            "radialComposition": [],
            "critChance": round(modded_cc, 6),
            "critMultiplier": round(modded_cd, 6),
            "statusChance": round(modded_sc, 6),
            "multishot": 1.0,
            "attackSpeed": round(attack_speed, 6),
            "fireRate": round(attack_speed, 6),
            "sustainedShotsPerSecond": round(attack_speed, 6),
            "reloadTime": 0.0,
            "magazine": None,
            "meleeRadius": float(claw["meleeRadius"]) + range_add_m,
            "additionalTargets": int(round(extra_targets)),
            "procDurationMultiplier": round(proc_dur_mult, 6),
            "procDamageMultiplier": round(proc_dmg_mult, 6),
            "conditionOverloadBonus": round(co_bonus, 6),
            "nonCritDamageBonus": round(noncrit_bonus, 6),
            "overguardDamageBonus": round(overguard_dmg_bonus, 6),
            "hunterSynergyBonus": round(hunter_synergy_ratio * max(0.0, primary_cc), 6),
            "mechaOverdriveBonus": round(mecha_overdrive_ratio * max(0.0, primary_sc), 6),
            "armorStripOnHit": round(armor_strip_on_hit, 6),
            "armorStripSources": {
                "viciousBond": round(vicious_strip, 6),
                "sharpenedClaws": round(sharpened_strip, 6),
            },
            "expectedProcsPerShot": {k: round(v, 6) for k, v in expected_procs.items() if v > 0.0},
            "sustainedProcsPerSecond": {k: round(v, 6) for k, v in sustained_procs_per_sec.items() if v > 0.0},
            "zoomMultiplier": 1.0,
            "rangeLimit": float(claw["meleeRadius"]) + range_add_m,
            "capacity": {
                "base": base_cap,
                "postureGain": posture_grant,
                "used": used_capacity,
                "total": total_cap,
                "remaining": total_cap - used_capacity,
                "valid": used_capacity <= total_cap,
                "reactor": weapon_reactor,
            },
            "slots": slot_assignments,
            "posture": posture_info,
            "slotPolarities": slot_polarities,
            "formaCount": forma_count,
            "riven": None,
            "_moddedStats": claw_modded_stats,
            "_procsPerShot": expected_procs,
            "_sustainedShotsPerSecond": attack_speed,
            "_statLanes": [(claw_modded_stats, 1.0, extra_forced or None)],
            "_clawBaseScale": dmg_scale,
            "_clawCoBonus": co_bonus,
        },
        claw_set_entries,
    )


def _moa_melee_weapon_record(hard_engage_rank: int) -> dict[str, Any]:
    dmg = 15.0 * (hard_engage_rank + 1)
    return {
        "path": MOA_MELEE_WEAPON_PATH,
        "name": "MoaPetMeleeWeapon",
        "nameInternal": "MoaPetMeleeWeapon",
        "nameEn": "Hard Engage",
        "nameZh": "强力接战",
        "slot": "companion",
        "productCategory": "SentinelWeapons",
        "ancestry": [
            MOA_MELEE_WEAPON_PATH,
            "/Lotus/Weapons/Tenno/Melee/PlayerMeleeWeapon",
            "/Lotus/Types/Game/LotusMeleeWeapon",
        ],
        "compatTags": ["SENTINEL_WEAPON"],
        "polarities": ["AP_UNIVERSAL"] * 8,
        "magazineSize": None,
        "omegaAttenuation": 1.0,
        "fireModes": [
            {
                "index": 0,
                "isAlternateFire": False,
                "fireRate": 1.0,
                "fireRateRaw": 60,
                "multishot": 1,
                "reloadTime": 0.0,
                "ammoCost": 0,
                "trigger": "",
                "falloffRange": [0, 0],
                "falloffMinDamage": 1,
                "damage": {
                    "total": dmg,
                    "types": {"DT_IMPACT": dmg},
                    "shares": {"DT_IMPACT": 1.0},
                    "critChance": 0.0,
                    "critMultiplier": 2.0,
                    "procChance": 0.2,
                },
            }
        ],
    }


_FRIENDLY_RIVEN_STATS: dict[str, tuple[str, str, str, str | None, str | None, str, float]] = {
    "critchance": ("0", "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "crit_chance": ("0", "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "cc": ("0", "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "critmultiplier": ("1", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "crit_multiplier": ("1", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "critdamage": ("1", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "crit_damage": ("1", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "cd": ("1", "WEAPON_CRIT_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "statuschance": ("2", "WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "status_chance": ("2", "WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "proc_chance": ("2", "WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "sc": ("2", "WEAPON_PROC_CHANCE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "statusduration": ("3", "WEAPON_PROC_TIME", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "status_duration": ("3", "WEAPON_PROC_TIME", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "proc_duration": ("3", "WEAPON_PROC_TIME", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "proc_time": ("3", "WEAPON_PROC_TIME", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "statusdamage": ("SD", "WEAPON_PROC_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "status_damage": ("SD", "WEAPON_PROC_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "procdamage": ("SD", "WEAPON_PROC_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "proc_damage": ("SD", "WEAPON_PROC_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "damage": ("D", "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "basedamage": ("D", "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "base_damage": ("D", "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "meleedamage": ("K", "WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "melee_damage": ("K", "WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "multishot": ("S", "WEAPON_FIRE_ITERATIONS", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "firerate": ("R", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "fire_rate": ("R", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "attackspeed": ("J", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "attack_speed": ("J", "WEAPON_FIRE_RATE", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "reloadspeed": ("F", "WEAPON_RELOAD_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "reload_speed": ("F", "WEAPON_RELOAD_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "reload": ("F", "WEAPON_RELOAD_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "magazine": ("L", "WEAPON_CLIP_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "magazine_capacity": ("L", "WEAPON_CLIP_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "clip_size": ("L", "WEAPON_CLIP_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "ammomax": ("M", "WEAPON_AMMO_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "ammo_max": ("M", "WEAPON_AMMO_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "ammo_maximum": ("M", "WEAPON_AMMO_MAX", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "heat": ("4", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FIRE", None, "percent", 1.0),
    "fire": ("4", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FIRE", None, "percent", 1.0),
    "cold": ("5", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FREEZE", None, "percent", 1.0),
    "freeze": ("5", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FREEZE", None, "percent", 1.0),
    "ice": ("5", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_FREEZE", None, "percent", 1.0),
    "toxin": ("6", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_POISON", None, "percent", 1.0),
    "poison": ("6", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_POISON", None, "percent", 1.0),
    "electricity": ("7", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_ELECTRICITY", None, "percent", 1.0),
    "electric": ("7", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_ELECTRICITY", None, "percent", 1.0),
    "impact": ("8", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_IMPACT", None, "percent", 1.0),
    "puncture": ("9", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_PUNCTURE", None, "percent", 1.0),
    "slash": ("A", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_SLASH", None, "percent", 1.0),
    "gas": ("GA", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_GAS", None, "percent", 1.0),
    "corrosive": ("CO", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_CORROSIVE", None, "percent", 1.0),
    "viral": ("VI", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_VIRAL", None, "percent", 1.0),
    "radiation": ("RA", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_RADIATION", None, "percent", 1.0),
    "blast": ("BL", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_EXPLOSION", None, "percent", 1.0),
    "explosion": ("BL", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_EXPLOSION", None, "percent", 1.0),
    "magnetic": ("MA", "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", "DT_MAGNETIC", None, "percent", 1.0),
    "damage_vs_corpus": ("C", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Corpus", "percent", 1.0),
    "damagevscorpus": ("C", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Corpus", "percent", 1.0),
    "corpus": ("C", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Corpus", "percent", 1.0),
    "bane_of_corpus": ("C", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Corpus", "percent", 1.0),
    "damage_vs_grineer": ("G", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Grineer", "percent", 1.0),
    "damagevsgrineer": ("G", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Grineer", "percent", 1.0),
    "grineer": ("G", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Grineer", "percent", 1.0),
    "bane_of_grineer": ("G", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Grineer", "percent", 1.0),
    "damage_vs_infested": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "damagevsinfested": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "damage_vs_infestation": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "infested": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "infestation": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "bane_of_infested": ("I", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Infestation", "percent", 1.0),
    "damage_vs_orokin": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "damagevsorokin": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "damage_vs_corrupted": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "orokin": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "corrupted": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "bane_of_orokin": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "bane_of_corrupted": ("FO", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Orokin", "percent", 1.0),
    "damage_vs_techrot": ("FT", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Techrot", "percent", 1.0),
    "damagevstechrot": ("FT", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Techrot", "percent", 1.0),
    "techrot": ("FT", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Techrot", "percent", 1.0),
    "damage_vs_scaldra": ("FS", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Scaldra", "percent", 1.0),
    "damagevsscaldra": ("FS", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Scaldra", "percent", 1.0),
    "scaldra": ("FS", "GAMEPLAY_FACTION_DAMAGE", "STACKING_MULTIPLY", None, "Scaldra", "percent", 1.0),
    "zoom": ("H", "WEAPON_ZOOM", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "range": ("T", "WEAPON_RANGE", "ADD", None, None, "flat", 1.0),
    "melee_range": ("T", "WEAPON_RANGE", "ADD", None, None, "flat", 1.0),
    "punch_through": ("P", "WEAPON_PUNCTURE_DEPTH", "ADD", None, None, "flat", 1.0),
    "punchthrough": ("P", "WEAPON_PUNCTURE_DEPTH", "ADD", None, None, "flat", 1.0),
    "projectile_speed": ("V", "WEAPON_PROJECTILE_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "projectilespeed": ("V", "WEAPON_PROJECTILE_SPEED", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "recoil": ("Z", "WEAPON_RECOIL", "STACKING_MULTIPLY", None, None, "percent", -1.0),
    "weapon_recoil": ("Z", "WEAPON_RECOIL", "STACKING_MULTIPLY", None, None, "percent", -1.0),
    "initial_combo": ("B", "WEAPON_MELEE_COMBO_INITIAL_BONUS", "ADD", None, None, "flat", 1.0),
    "initialcombo": ("B", "WEAPON_MELEE_COMBO_INITIAL_BONUS", "ADD", None, None, "flat", 1.0),
    "combo_duration": ("N", "WEAPON_MELEE_COMBO_DURATION_BONUS", "ADD", None, None, "flat", 1.0),
    "comboduration": ("N", "WEAPON_MELEE_COMBO_DURATION_BONUS", "ADD", None, None, "flat", 1.0),
    "heavy_attack_efficiency": ("U", "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY", "ADD", None, None, "percent", 1.0),
    "heavy_efficiency": ("U", "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY", "ADD", None, None, "percent", 1.0),
    "weakpoint_damage": ("W", "WEAPON_DAMAGE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "weakpointdamage": ("W", "WEAPON_DAMAGE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "weakpoint_crit_chance": ("Y", "WEAPON_CRIT_CHANCE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "weakpointcritchance": ("Y", "WEAPON_CRIT_CHANCE_WEAKPOINT", "STACKING_MULTIPLY", None, None, "percent", 1.0),
    "ammo_efficiency": ("AE", "WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", None, None, "percent", -1.0),
    "ammoefficiency": ("AE", "WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", None, None, "percent", -1.0),
}


def _stat_record_from_effect(effect: ModEffect, rules: Mapping[str, Any]) -> dict[str, Any]:
    src = str(effect.source_path or "")
    if src.startswith("riven:"):
        cand_code = src.split(":", 1)[1].strip().upper()
        if cand_code in rules:
            rule = rules[cand_code]
            unit = str(rule[5])
            direction = float(rule[6])
            neg = (effect.value * direction) < 0.0
            disp_val = abs(float(effect.value)) * (100.0 if unit == "percent" else 1.0)
            return {"code": cand_code, "value": round(disp_val, 6), "negative": bool(neg)}
    for code, rule in rules.items():
        _lbl, ut, op, dt, sf, unit, direction, *_ = rule
        if ut == effect.upgrade_type and (dt or None) == (effect.damage_type or None) and (sf or None) == (effect.symbol_filter or None):
            neg = (effect.value * float(direction)) < 0.0
            disp_val = abs(float(effect.value)) * (100.0 if unit == "percent" else 1.0)
            return {"code": code, "value": round(disp_val, 6), "negative": bool(neg)}
    return {
        "code": effect.upgrade_type,
        "value": round(abs(float(effect.value)) * 100.0, 6),
        "negative": float(effect.value) < 0.0,
    }


def _parse_robotic_riven(
    raw_riven: Any,
    used_slots: set[int],
) -> tuple[dict[str, Any], ModEffectList, float, float, float]:
    from . import optimizer

    if not isinstance(raw_riven, Mapping):
        raise SimulationError("weapon.riven must be an object or null")

    raw_stats = raw_riven.get("stats")
    if isinstance(raw_stats, Mapping):
        raw_stats = [{"code": str(k), "value": v} for k, v in raw_stats.items()]
    riven_effects = ModEffectList()
    normalized_stat_rows: list[dict[str, Any]] = []
    zoom_bonus = 0.0
    range_flat = 0.0
    range_pct = 0.0

    if isinstance(raw_stats, list):
        has_codes = any(isinstance(s, Mapping) and s.get("code") for s in raw_stats)
        if has_codes:
            cleaned_wire: list[dict[str, Any]] = []
            for idx, s in enumerate(raw_stats):
                if not isinstance(s, Mapping):
                    raise SimulationError(f"weapon.riven.stats[{idx}] must be an object")
                code = str(s.get("code") or "").strip().upper()
                if not code:
                    raise SimulationError(f"weapon.riven.stats[{idx}].code must be a non-empty string")
                if code not in optimizer.RIVEN_RULES:
                    mapped_by_name = _FRIENDLY_RIVEN_STATS.get(code.casefold())
                    if mapped_by_name is not None:
                        code = mapped_by_name[0]
                    else:
                        raise SimulationError(f"unknown riven stat code {code!r}")
                raw_v = _finite_float(s.get("value"), f"weapon.riven.stats[{idx}].value")
                neg_flag = bool(s.get("negative", False)) or (raw_v < 0.0)
                abs_v = abs(raw_v)
                entry_copy = dict(s)
                entry_copy["code"] = code
                entry_copy["value"] = abs_v
                entry_copy["negative"] = neg_flag
                cleaned_wire.append(entry_copy)
            try:
                lines, _reasons = optimizer._wire_lines(cleaned_wire)
                raw_line_effects = [line.effect for line in lines if line.effect is not None]
                normalized_stat_rows = [
                    {"code": line.code, "value": round(float(line.value), 6), "negative": bool(line.negative)}
                    for line in lines
                ]
            except SimulationError as exc:
                if "cannot be rolled as negative" not in str(exc):
                    raise
                raw_line_effects = list(optimizer.synthetic_riven_effects(cleaned_wire))
                normalized_stat_rows = [
                    {"code": row["code"], "value": round(float(row["value"]), 6), "negative": bool(row["negative"])}
                    for row in cleaned_wire
                ]
        else:
            normalized_stats = []
            for idx, s in enumerate(raw_stats):
                if isinstance(s, Mapping) and not s.get("upgradeType") and not s.get("upgrade_type") and s.get("stat"):
                    raw_key = str(s["stat"]).strip()
                    key = raw_key.casefold()
                    if key in _FRIENDLY_RIVEN_STATS:
                        code, ut, op, dt, sf, unit, direction = _FRIENDLY_RIVEN_STATS[key]
                        raw_v = _finite_float(s.get("value"), f"weapon.riven.stats[{idx}].value")
                        is_pct_input = str(s.get("unit") or "").strip().casefold() == "percent"
                        eff_val = (raw_v / 100.0) if (is_pct_input and unit == "percent") else raw_v
                        if s.get("negative") is True and eff_val > 0.0:
                            eff_val = -eff_val * direction
                        normalized_stats.append({
                            "upgradeType": ut,
                            "operation": op,
                            "damageType": dt,
                            "symbolFilter": sf,
                            "value": eff_val,
                            "sourcePath": f"riven:{code}",
                        })
                        disp_v = abs(eff_val) * (100.0 if unit == "percent" else 1.0)
                        normalized_stat_rows.append({
                            "code": code,
                            "value": round(disp_v, 6),
                            "negative": bool((eff_val * direction) < 0.0),
                        })
                    elif raw_key.upper() in optimizer.RIVEN_RULES:
                        code = raw_key.upper()
                        raw_v = _finite_float(s.get("value"), f"weapon.riven.stats[{idx}].value")
                        neg_flag = bool(s.get("negative", False)) or (raw_v < 0.0)
                        normalized_stats.append({
                            "code": code,
                            "value": abs(raw_v),
                            "negative": neg_flag,
                        })
                        normalized_stat_rows.append({
                            "code": code,
                            "value": round(abs(raw_v), 6),
                            "negative": neg_flag,
                        })
                    else:
                        raise SimulationError(f"unknown riven stat {s['stat']!r}")
                else:
                    normalized_stats.append(s)
            raw_line_effects = list(optimizer.synthetic_riven_effects(normalized_stats))
            if not normalized_stat_rows:
                normalized_stat_rows = [_stat_record_from_effect(e, optimizer.RIVEN_RULES) for e in raw_line_effects]
    else:
        synthesized = []
        for k, v in raw_riven.items():
            if k in {"slot", "rank", "polarity", "baseDrain", "stats", "effects", "lockSlot"}:
                continue
            key = str(k).strip().casefold()
            mapped = _FRIENDLY_RIVEN_STATS.get(key)
            if mapped is not None:
                code, ut, op, dt, sf, unit, direction = mapped
                num_v = _finite_float(v, f"weapon.riven.{k}")
                synthesized.append({
                    "upgradeType": ut,
                    "operation": op,
                    "damageType": dt,
                    "symbolFilter": sf,
                    "value": num_v,
                    "sourcePath": f"riven:{code}",
                })
                disp_v = abs(num_v) * (100.0 if unit == "percent" else 1.0)
                normalized_stat_rows.append({
                    "code": code,
                    "value": round(disp_v, 6),
                    "negative": bool((num_v * direction) < 0.0),
                })
            elif str(k).strip().upper() in optimizer.RIVEN_RULES:
                code = str(k).strip().upper()
                num_v = _finite_float(v, f"weapon.riven.{k}")
                neg_flag = num_v < 0.0
                synthesized.append({
                    "code": code,
                    "value": abs(num_v),
                    "negative": neg_flag,
                })
                normalized_stat_rows.append({
                    "code": code,
                    "value": round(abs(num_v), 6),
                    "negative": neg_flag,
                })
            else:
                raise SimulationError(f"unknown riven field {k!r}")
        if isinstance(raw_riven.get("effects"), list):
            synthesized.extend(raw_riven["effects"])
        if not synthesized:
            raise SimulationError("weapon.riven must declare stats")
        raw_line_effects = list(optimizer.synthetic_riven_effects(synthesized))
        if not normalized_stat_rows:
            normalized_stat_rows = [_stat_record_from_effect(e, optimizer.RIVEN_RULES) for e in raw_line_effects]

    # Reverse base-element order inside one Riven card per Warframe combining priority.
    elem_indices = [
        i for i, eff in enumerate(raw_line_effects)
        if eff.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED" and eff.damage_type in BASE_ELEMENTS
    ]
    if len(elem_indices) > 1:
        reversed_elems = [raw_line_effects[i] for i in reversed(elem_indices)]
        for idx_pos, target_idx in enumerate(elem_indices):
            raw_line_effects[target_idx] = reversed_elems[idx_pos]

    for eff in raw_line_effects:
        if eff.upgrade_type == "WEAPON_ZOOM":
            zoom_bonus += eff.value
        elif eff.upgrade_type == "WEAPON_RANGE":
            if eff.operation == "ADD":
                range_flat += eff.value
            else:
                range_pct += eff.value
        riven_effects.append(eff)

    rank = raw_riven.get("rank", 8)
    if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= 8:
        raise SimulationError("weapon.riven.rank must be an integer in 0..8")
    base_drain = int(raw_riven.get("baseDrain", 10))
    polarity = _normalize_polarity_override(raw_riven.get("polarity") or "AP_ATTACK", "weapon.riven.polarity")

    slot = raw_riven.get("slot")
    if slot is None:
        slot = next((s for s in range(ROBOTIC_WEAPON_SLOT_COUNT) if s not in used_slots), None)
        if slot is None:
            raise SimulationError("no free weapon slot available for Riven MOD")
    if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < ROBOTIC_WEAPON_SLOT_COUNT:
        raise SimulationError(f"weapon.riven.slot must be in 0..{ROBOTIC_WEAPON_SLOT_COUNT - 1}")
    if slot in used_slots:
        raise SimulationError(f"weapon slot {slot} is assigned to both a MOD and a Riven")

    return (
        {
            "slot": slot,
            "rank": rank,
            "baseDrain": base_drain,
            "polarity": polarity,
            "stats": normalized_stat_rows,
            "effects": [_serialize_effect(e) for e in riven_effects],
        },
        riven_effects,
        zoom_bonus,
        range_flat,
        range_pct,
    )


def _evaluate_robotic_weapon(
    companion: Mapping[str, Any],
    weapon_config: Mapping[str, Any],
    *,
    reactor: bool,
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    body_weapon_effects: ModEffectList,
    exports: Mapping[str, Any] | None,
    warnings: list[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if companion["category"] != "robotic":
        raise SimulationError(f"{companion['nameEn']} cannot equip a robotic companion weapon")

    raw_path = str(weapon_config.get("path") or companion.get("defaultWeaponPath") or "").strip()
    if not raw_path:
        raise SimulationError("weapon.path must be a non-empty string")

    hard_engage = next((item for item in body_mods if item[0]["path"] == HARD_ENGAGE_PATH), None)
    exp = exports if exports is not None else _default_exports()
    mods_catalog = exp.get("mods") or ()
    weapons_catalog = exp.get("weapons") or ()

    if raw_path.casefold() in MOA_MELEE_WEAPON_ALIASES:
        if companion["kind"] != "moa" or hard_engage is None:
            raise SimulationError("MoaPetMeleeWeapon requires a MOA companion with Hard Engage equipped")
        weapon_record: Mapping[str, Any] = _moa_melee_weapon_record(hard_engage[1])
    else:
        weapon_record = resolve_record(weapons_catalog, raw_path, kind="weapon")
        if weapon_record.get("slot") != "companion":
            raise SimulationError(f"{weapon_record.get('nameEn') or raw_path} is not a robotic companion weapon")

    wpath = str(weapon_record["path"])
    incompat = set(companion.get("incompatibleWeapons") or ())
    ancestry_paths = {wpath, *(str(a) for a in weapon_record.get("ancestry") or () if a)}
    if ancestry_paths & incompat:
        raise SimulationError(f"{companion['nameEn']} cannot equip {weapon_record.get('nameEn') or wpath}")

    if wpath in DECONSTRUCTOR_PATHS and "deconstructor" not in (companion.get("allowedWeaponCategories") or ()):
        raise SimulationError(f"{weapon_record.get('nameEn')} can only be equipped on Helios / Helios Prime")
    if wpath in HOUND_MELEE_PATHS and companion["kind"] != "hound":
        raise SimulationError(f"{weapon_record.get('nameEn')} can only be equipped on a Hound")
    if companion["kind"] == "hound" and wpath not in HOUND_MELEE_PATHS:
        raise SimulationError(f"{companion['nameEn']} can only equip Hound melee weapons (Akaten/Batoten/Lacerten)")

    polarities_override = weapon_config.get("slotPolarities")
    if polarities_override is None:
        polarities_override = weapon_config.get("polarities")
    slot_polarities, forma_count = _resolve_slot_polarities(
        weapon_record.get("polarities") or [None] * ROBOTIC_WEAPON_SLOT_COUNT,
        polarities_override,
        slot_count=ROBOTIC_WEAPON_SLOT_COUNT,
        label="weapon.slotPolarities",
    )

    raw_mods = weapon_config.get("mods") or []
    if not isinstance(raw_mods, list) or len(raw_mods) > ROBOTIC_WEAPON_SLOT_COUNT:
        raise SimulationError(f"weapon.mods must be an array of at most {ROBOTIC_WEAPON_SLOT_COUNT} entries")

    companion_player_stacks = weapon_config.get("companionPlayerStacks", False)
    if not isinstance(companion_player_stacks, bool):
        raise SimulationError("weapon.companionPlayerStacks must be a boolean")

    parsed_mods: list[tuple[Mapping[str, Any], int, int]] = []
    seen_paths: set[str] = set()
    seen_slots: set[int] = set()
    seen_families: dict[str, str] = {}

    for idx, item in enumerate(raw_mods):
        if item is None:
            continue
        if not isinstance(item, Mapping):
            raise SimulationError(f"weapon.mods[{idx}] must be an object")
        query = str(item.get("path") or item.get("query") or "").strip()
        if not query:
            raise SimulationError(f"weapon.mods[{idx}].path must be a non-empty string")
        mod = resolve_record(mods_catalog, query, kind="mod")
        if not _mod_matches_weapon(mod, weapon_record):
            raise SimulationError(
                f"{mod.get('nameEn') or query} is not compatible with {weapon_record.get('nameEn') or wpath}"
            )
        # Defense-in-depth for Update 30.5: Deconstructor & Hound melee cannot use Gladiator mods.
        if (wpath in DECONSTRUCTOR_PATHS or wpath in HOUND_MELEE_PATHS) and mod.get("modSet") == "GladiatorSetMod":
            raise SimulationError("Gladiator set MODs cannot be equipped on robotic melee weapons (Update 30.5)")

        mpath = str(mod["path"])
        if mpath in seen_paths:
            raise SimulationError(f"duplicate weapon MOD: {mod.get('nameEn') or mpath}")
        seen_paths.add(mpath)

        fam = _canonical_mod_family(mod)
        if fam in seen_families:
            raise SimulationError(
                f"mutually exclusive weapon MOD family: {mod.get('nameEn') or mpath} conflicts with {seen_families[fam]}"
            )
        seen_families[fam] = str(mod.get("nameEn") or mpath)

        max_rank = int(mod.get("maxRank") or 0)
        rank = item.get("rank", max_rank)
        if isinstance(rank, bool) or not isinstance(rank, int) or not 0 <= rank <= max_rank:
            raise SimulationError(f"weapon.mods[{idx}].rank must be an integer in 0..{max_rank}")
        slot = item.get("slot", idx)
        if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < ROBOTIC_WEAPON_SLOT_COUNT:
            raise SimulationError(f"weapon.mods[{idx}].slot must be an integer in 0..{ROBOTIC_WEAPON_SLOT_COUNT - 1}")
        if slot in seen_slots:
            raise SimulationError(f"weapon slot {slot} is assigned more than once")
        seen_slots.add(slot)
        parsed_mods.append((mod, rank, slot))

    riven_info = None
    riven_slot_effects: tuple[int, ModEffectList] | None = None
    zoom_bonus = 0.0
    range_flat = 0.0
    range_pct = 0.0
    if weapon_config.get("riven") is not None:
        riven_info, r_effs, r_zoom, r_flat, r_pct = _parse_robotic_riven(weapon_config["riven"], seen_slots)
        seen_slots.add(riven_info["slot"])
        riven_slot_effects = (riven_info["slot"], r_effs)
        zoom_bonus += r_zoom
        range_flat += r_flat
        range_pct += r_pct

    base_scenario = Scenario(
        aiming=False,
        trigger_policy="assumed_max",
        combat_state={"companion": True, "companionPlayerStacks": companion_player_stacks},
    )
    steady_scenario = _steady_state_scenario([m for m, _, _ in parsed_mods], base_scenario)

    shells = _set_shells(mods_catalog)
    set_counts_on_weapon = Counter(
        _set_key(m.get("modSet")) for m, _, _ in parsed_mods if m.get("modSet")
    )

    # Assemble slot-ordered effects so Riven + elemental mods combine in exact slot order.
    slot_items: list[tuple[int, str, Any]] = [(slot, "mod", (mod, rank)) for mod, rank, slot in parsed_mods]
    if riven_slot_effects is not None:
        slot_items.append((riven_slot_effects[0], "riven", riven_slot_effects[1]))
    slot_items.sort(key=lambda t: t[0])

    weapon_reactor = weapon_config.get("reactor", reactor)
    if not isinstance(weapon_reactor, bool):
        raise SimulationError("weapon.reactor must be a boolean")
    capacity_limit = REACTOR_CAPACITY if weapon_reactor else BASE_CAPACITY
    used_capacity = 0
    slot_assignments: list[dict[str, Any]] = []
    weapon_set_entries: list[dict[str, Any]] = []
    all_effects = ModEffectList()
    shivering_contagion = False

    for slot, item_kind, payload in slot_items:
        if item_kind == "riven":
            r_drain, r_rel = _normal_slot_drain(
                riven_info["baseDrain"],
                riven_info["rank"],
                riven_info["polarity"],
                slot_polarities[slot],
            )
            used_capacity += r_drain
            riven_info["drain"] = r_drain
            riven_info["slotPolarity"] = slot_polarities[slot]
            riven_info["polarityRelation"] = r_rel
            slot_assignments.append({
                "slot": slot,
                "path": "__riven__",
                "nameEn": "Riven Mod",
                "rank": riven_info["rank"],
                "drain": r_drain,
                "slotPolarity": slot_polarities[slot],
                "polarityRelation": r_rel,
            })
            all_effects.extend(payload)
            continue

        mod, rank = payload
        mpath = str(mod["path"])
        if mpath == SHIVERING_CONTAGION_PATH:
            shivering_contagion = True

        drain, rel = _normal_slot_drain(
            int(mod.get("baseDrain") or 0),
            rank,
            mod.get("polarity"),
            slot_polarities[slot],
        )
        used_capacity += drain
        slot_assignments.append({
            "slot": slot,
            "path": mpath,
            "nameEn": mod.get("nameEn"),
            "rank": rank,
            "drain": drain,
            "slotPolarity": slot_polarities[slot],
            "polarityRelation": rel,
        })

        raw_set_id = mod.get("modSet")
        if raw_set_id and not (
            (wpath in DECONSTRUCTOR_PATHS or wpath in HOUND_MELEE_PATHS) and raw_set_id == "GladiatorSetMod"
        ):
            weapon_set_entries.append({
                "path": mpath,
                "setId": str(raw_set_id),
                "source": "companion_weapon",
            })

        for raw_eff in mod.get("effects") or ():
            ut = raw_eff.get("upgradeType")
            val_per_rank = float(raw_eff.get("valuePerRank") or 0.0) * (rank + 1)
            if ut == "WEAPON_ZOOM":
                zoom_bonus += val_per_rank
            elif ut == "WEAPON_RANGE":
                if raw_eff.get("operation") == "ADD":
                    range_flat += val_per_rank
                else:
                    range_pct += val_per_rank

        set_key = _set_key(raw_set_id)
        shell = shells.get(set_key) if set_key else None
        pieces, _ = _effective_set_pieces(mod, selected_count=set_counts_on_weapon.get(set_key, 0), shell=shell)
        buff_mult = _buff_set_multiplier(mod, pieces) if shell and shell.get("buffSet") else 1.0
        expanded = mod_effects(mod, rank, steady_scenario)
        for eff in expanded:
            if buff_mult != 1.0:
                eff = ModEffect(
                    upgrade_type=eff.upgrade_type,
                    operation=eff.operation,
                    value=eff.value * buff_mult,
                    damage_type=eff.damage_type,
                    symbol_filter=eff.symbol_filter,
                    supported=eff.supported,
                    source_path=eff.source_path,
                    runtime_kind=eff.runtime_kind,
                    runtime_chance=eff.runtime_chance,
                    runtime_threshold=eff.runtime_threshold,
                    runtime_multiplier=eff.runtime_multiplier,
                )
            all_effects.append(eff)

    for set_key, count in set_counts_on_weapon.items():
        shell = shells.get(set_key)
        if shell is not None and not shell.get("buffSet"):
            pieces = min(count, int(shell.get("setPieces") or count))
            all_effects.extend(_set_shell_effects(shell, pieces, steady_scenario))

    # Body-to-weapon effects (Fired Up, Astral Bond, Momentous Bond) combine after installed mods.
    all_effects.extend(body_weapon_effects)

    from . import optimizer

    stats = _clamp_modded_stats(apply_mods(weapon_record, all_effects, fire_mode=0, scenario=steady_scenario))
    mode0 = (weapon_record.get("fireModes") or [{}])[0]
    mode0_dmg = mode0.get("damage") or {}

    # Expected procs per shot & direct damage lanes (including Deconstructor's 3-projectile sequence).
    seq_lanes = mode0_dmg.get("sequenceDamage")
    all_positive_damage_types: set[str] = {dt for dt, amt in stats.damage_types.items() if amt > 0.0}
    stat_lanes: list[tuple[ModdedStats, float, Mapping[str, float] | None]] = []
    if isinstance(seq_lanes, list) and len(seq_lanes) > 1:
        n_lanes = float(len(seq_lanes))
        lane_procs_acc: dict[str, float] = {}
        shot_damage_types: dict[str, float] = {}
        proc_weight_map: dict[str, float] = {}
        direct_avg_hit = 0.0
        per_shot_dot = 0.0
        for lane in seq_lanes:
            lane_weapon = {**weapon_record, "fireModes": [{**mode0, "damage": lane}]}
            lane_stats = _clamp_modded_stats(apply_mods(lane_weapon, all_effects, fire_mode=0, scenario=steady_scenario))
            stat_lanes.append((lane_stats, 1.0 / n_lanes, None))
            all_positive_damage_types.update(dt for dt, amt in lane_stats.damage_types.items() if amt > 0.0)
            for dt, amt in lane_stats.damage_types.items():
                if amt > 0.0:
                    shot_damage_types[dt] = shot_damage_types.get(dt, 0.0) + (amt * lane_stats.multishot) / n_lanes
            for dt, w in _status_weights(lane_stats).items():
                if w > 0.0:
                    proc_weight_map[dt] = proc_weight_map.get(dt, 0.0) + w / n_lanes
            for dt, cnt in expected_status_procs(lane_stats, hit_location="body").items():
                lane_procs_acc[dt] = lane_procs_acc.get(dt, 0.0) + cnt / n_lanes
            l_hit_mult = effective_hit_multiplier(
                lane_stats.crit_chance,
                lane_stats.crit_multiplier,
                lane_stats.noncrit_damage_multiplier,
                double_crit_chance=lane_stats.double_crit_chance,
            )
            direct_avg_hit += (lane_stats.total_damage * lane_stats.multishot * l_hit_mult * lane_stats.falloff_multiplier) / n_lanes
            per_shot_dot += float(expected_status_damage(lane_stats, {}, level=1)["total"]) / n_lanes
        procs_per_shot = lane_procs_acc
    else:
        stat_lanes.append((stats, 1.0, None))
        shot_damage_types = {dt: val * stats.multishot for dt, val in stats.damage_types.items() if val > 0.0}
        proc_weight_map = _status_weights(stats)
        procs_per_shot = dict(expected_status_procs(stats, hit_location="body"))
        direct_hit_mult = effective_hit_multiplier(
            stats.crit_chance,
            stats.crit_multiplier,
            stats.noncrit_damage_multiplier,
            double_crit_chance=stats.double_crit_chance,
        )
        direct_avg_hit = stats.total_damage * stats.multishot * direct_hit_mult * stats.falloff_multiplier
        per_shot_dot = float(expected_status_damage(stats, {}, level=1)["total"])

    radial_dmg = mode0_dmg.get("radial")
    radial_stats = None
    radial_shot_types: dict[str, float] | None = None
    radial_avg_hit = 0.0
    if isinstance(radial_dmg, Mapping) and radial_dmg.get("types"):
        radial_weapon = {
            **weapon_record,
            "fireModes": [
                {
                    **mode0,
                    "damage": {
                        "types": dict(radial_dmg["types"]),
                        "shares": dict(radial_dmg.get("shares") or {}),
                        "total": float(radial_dmg.get("total") or sum(radial_dmg["types"].values())),
                        "critChance": float(radial_dmg.get("critChance", mode0_dmg.get("critChance", 0.0))),
                        "critMultiplier": float(radial_dmg.get("critMultiplier", mode0_dmg.get("critMultiplier", 1.5))),
                        "procChance": float(radial_dmg.get("procChance", mode0_dmg.get("procChance", 0.0))),
                    },
                }
            ],
        }
        radial_stats = _clamp_modded_stats(apply_mods(radial_weapon, all_effects, fire_mode=0, scenario=steady_scenario))
        stat_lanes.append((radial_stats, 1.0, None))
        radial_shot_types = {dt: val * radial_stats.multishot for dt, val in radial_stats.damage_types.items() if val > 0.0}
        all_positive_damage_types.update(dt for dt, amt in radial_stats.damage_types.items() if amt > 0.0)
        for dt, cnt in expected_status_procs(radial_stats, hit_location="body").items():
            procs_per_shot[dt] = procs_per_shot.get(dt, 0.0) + cnt
        r_hit_mult = effective_hit_multiplier(
            radial_stats.crit_chance,
            radial_stats.crit_multiplier,
            radial_stats.noncrit_damage_multiplier,
            double_crit_chance=radial_stats.double_crit_chance,
        )
        radial_avg_hit = radial_stats.total_damage * radial_stats.multishot * r_hit_mult * radial_stats.falloff_multiplier
        per_shot_dot += float(expected_status_damage(radial_stats, {}, level=1)["total"])

    # Burst cadence (e.g. Helstrum 4 homing missiles/burst, Burst Laser 3-5 rounds/burst).
    burst_count = int(mode0.get("burstCount") or 1)
    burst_delay = float(mode0.get("burstDelay") or 0.0)
    if burst_count > 1 and stats.fire_rate > 0:
        base_fr = max(float(mode0.get("fireRate") or stats.fire_rate), 1e-9)
        fr_scale = max(stats.fire_rate / base_fr, 1e-9)
        burst_span = (burst_count - 1) * (burst_delay / fr_scale) + (1.0 / stats.fire_rate)
        effective_fire_rate = burst_count / burst_span if burst_span > 0 else 0.0
        if stats.magazine and stats.magazine > 0:
            bursts_per_mag = max(float(stats.magazine) / burst_count, 1.0)
            cycle = bursts_per_mag * burst_span + float(stats.reload_time or 0.0)
            sustained_shots_per_sec = float(stats.magazine) / cycle if cycle > 0 else 0.0
        else:
            sustained_shots_per_sec = effective_fire_rate
    else:
        effective_fire_rate = (
            (1.0 / stats.trigger_interval)
            if stats.trigger_interval > 0 and math.isfinite(stats.trigger_interval)
            else float(stats.fire_rate)
        )
        sustained_shots_per_sec = float(stats.sustained_attack_rate)

    sustained_procs_per_sec = {
        dt: cnt * sustained_shots_per_sec
        for dt, cnt in procs_per_shot.items()
        if cnt > 0.0 and sustained_shots_per_sec > 0.0
    }

    direct_total_damage = sum(shot_damage_types.values())
    radial_total_damage = sum(radial_shot_types.values()) if radial_shot_types else 0.0
    total_shot_damage = direct_total_damage + radial_total_damage
    average_hit = direct_avg_hit + radial_avg_hit
    burst_dps = average_hit * effective_fire_rate
    first_shot_factor = (
        1.0 + float(stats.first_shot_damage_bonus) / float(stats.magazine)
        if stats.magazine and stats.magazine > 0 and stats.first_shot_damage_bonus > 0
        else 1.0
    )
    sustained_dps = average_hit * first_shot_factor * sustained_shots_per_sec
    dot_dps = per_shot_dot * sustained_shots_per_sec
    total_sustained_dps = round(sustained_dps + dot_dps, 3)

    is_virtual_moa = wpath == MOA_MELEE_WEAPON_PATH
    raw_disp = weapon_record.get("omegaAttenuation")
    if raw_disp is None:
        raw_disp = weapon_record.get("disposition")
    disposition = 0.0 if is_virtual_moa else float(raw_disp if raw_disp is not None else 1.0)
    riven_type = None if is_virtual_moa else str(optimizer._riven_type(None, weapon_record))
    status_dmg_mult = max(0.0, float(stats.proc_damage_multiplier))
    faction_multipliers = {
        str(fac): round(float(mult), 6)
        for fac, mult in stats.faction_damage_multipliers.items()
        if abs(float(mult) - 1.0) > 1e-9
    }

    damage_composition = _build_damage_composition(
        shot_damage_types,
        proc_weight_map,
        procs_per_shot,
        sustained_procs_per_sec,
    )
    radial_composition = _build_radial_composition(radial_shot_types)

    zoom_multiplier = max(0.0, 1.0 + zoom_bonus)
    ai_profile = _indices()["aiProfiles"].get(wpath)
    base_trace = ai_profile.get("traceDistance") if isinstance(ai_profile, Mapping) else None
    range_limit: float | None = None
    if isinstance(base_trace, (int, float)) and ai_profile and ai_profile.get("onlyFireWithinRange"):
        range_limit = max(0.0, (float(base_trace) + range_flat) * (1.0 + range_pct))
    elif wpath in DECONSTRUCTOR_PATHS:
        range_limit = max(0.0, (10.0 + range_flat) * (1.0 + range_pct))
    elif wpath in HOUND_MELEE_PATHS:
        range_limit = max(0.0, (25.0 + range_flat) * (1.0 + range_pct))
    elif wpath == MOA_MELEE_WEAPON_PATH:
        range_limit = max(0.0, (10.0 + range_flat) * (1.0 + range_pct))

    vicious_strip = 0.0
    for b_mod, b_rank, _ in body_mods:
        if b_mod["path"] == VICIOUS_BOND_PATH:
            vicious_strip = float(b_mod["bondSpec"]["armorStripFractionByRank"][b_rank])

    is_melee_weapon = wpath in HOUND_MELEE_PATHS or wpath in DECONSTRUCTOR_PATHS or wpath == MOA_MELEE_WEAPON_PATH
    if used_capacity > capacity_limit:
        warnings.append(f"robotic-weapon-capacity-exceeded: {used_capacity}/{capacity_limit}")

    return (
        {
            "kind": "robotic_weapon",
            "path": wpath,
            "nameEn": weapon_record.get("nameEn"),
            "nameZh": weapon_record.get("nameZh"),
            "portraitAsset": (ai_profile or {}).get("portraitAsset"),
            "disposition": round(disposition, 6),
            "rivenType": riven_type,
            "damageTypes": {dt: round(val, 6) for dt, val in shot_damage_types.items() if val > 0.0},
            "perProjectileDamageTypes": {dt: round(val, 6) for dt, val in stats.damage_types.items() if val > 0.0},
            "radialDamageTypes": (
                {dt: round(val, 6) for dt, val in radial_shot_types.items() if val > 0.0}
                if radial_shot_types is not None
                else None
            ),
            "positiveDamageTypes": sorted(all_positive_damage_types),
            "totalDamage": round(total_shot_damage, 6),
            "directTotalDamage": round(direct_total_damage, 6),
            "perProjectileDamage": round(stats.total_damage, 6),
            "averageHit": round(average_hit, 3),
            "burstDps": round(burst_dps, 3),
            "sustainedDps": round(sustained_dps, 3),
            "dotDps": round(dot_dps, 3),
            "totalSustainedDps": total_sustained_dps,
            "statusDamageMultiplier": round(status_dmg_mult, 6),
            "factionMultipliers": faction_multipliers,
            "damageComposition": damage_composition,
            "radialComposition": radial_composition,
            "critChance": round(float(stats.crit_chance), 6),
            "critMultiplier": round(float(stats.crit_multiplier), 6),
            "statusChance": round(float(stats.status_chance), 6),
            "multishot": round(float(stats.multishot), 6),
            "fireRate": round(float(stats.fire_rate), 6),
            "attackSpeed": round(float(stats.fire_rate), 6),
            "reloadTime": round(float(stats.reload_time or 0.0), 6),
            "magazine": round(float(stats.magazine), 6) if stats.magazine else None,
            "sustainedShotsPerSecond": round(sustained_shots_per_sec, 6),
            "expectedProcsPerShot": {dt: round(v, 6) for dt, v in procs_per_shot.items() if v > 0.0},
            "sustainedProcsPerSecond": {dt: round(v, 6) for dt, v in sustained_procs_per_sec.items() if v > 0.0},
            "zoomMultiplier": round(zoom_multiplier, 6),
            "rangeLimit": round(range_limit, 6) if range_limit is not None else None,
            "rangeFlatBonus": round(range_flat, 6),
            "rangePercentBonus": round(range_pct, 6),
            "shiveringContagionEquipped": shivering_contagion,
            "armorStripOnHit": round(vicious_strip if is_melee_weapon else 0.0, 6),
            "capacity": {
                "used": used_capacity,
                "total": capacity_limit,
                "remaining": capacity_limit - used_capacity,
                "valid": used_capacity <= capacity_limit,
                "reactor": weapon_reactor,
            },
            "slots": slot_assignments,
            "slotPolarities": slot_polarities,
            "formaCount": forma_count,
            "riven": riven_info,
            "_moddedStats": stats,
            "_procsPerShot": procs_per_shot,
            "_sustainedShotsPerSecond": sustained_shots_per_sec,
            "_statLanes": stat_lanes,
        },
        weapon_set_entries,
    )


def _build_attack_and_priming(
    companion: Mapping[str, Any],
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    weapon_result: dict[str, Any] | None,
    manifold_status_types: Sequence[str],
    duplex_active_clones: int,
    warnings: list[str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if companion["category"] == "beast":
        return (
            {
                "category": "beast",
                "arenaActiveAttack": False,
                "canAttack": False,
                "attackMode": "passive_only",
                "engageRange": 0.0,
                "sustainRange": 0.0,
                "effectiveMaxRange": 0.0,
                "attackPrecept": None,
                "offensivePrecepts": [],
                "aiProfile": None,
                "shiveringContagionEquipped": False,
                "cloneMultiplier": 1,
            },
            {
                "active": False,
                "effectiveShotsPerSecond": 0.0,
                "steadyPrimingStacks": {},
                "primedStatusTypes": [],
                "expectedDistinctStatusCount": 0.0,
                "coldProcsPerSecond": 0.0,
                "heatProcsPerSecond": 0.0,
            },
        )

    kind = str(companion["kind"])
    has_weapon = weapon_result is not None
    zoom_mult = float(weapon_result["zoomMultiplier"]) if weapon_result else 1.0
    range_flat = float(weapon_result.get("rangeFlatBonus") or 0.0) if weapon_result else 0.0
    range_pct = float(weapon_result.get("rangePercentBonus") or 0.0) if weapon_result else 0.0
    shivering_equipped = bool(weapon_result and weapon_result.get("shiveringContagionEquipped"))

    can_attack = False
    attack_mode = "none"
    engage_range = 0.0
    sustain_range = 0.0
    attack_precept_info: dict[str, Any] | None = None
    offensive_precepts: list[dict[str, Any]] = []

    for mod, rank, slot in body_mods:
        pspec = mod.get("preceptSpec")
        if not isinstance(pspec, Mapping):
            continue
        if pspec.get("damageType") or pspec.get("forcedProc") or mod["path"] in HOUND_OFFENSIVE_PRECEPTS:
            offensive_precepts.append({
                "path": mod["path"],
                "id": mod["id"],
                "nameEn": mod["nameEn"],
                "slot": slot,
                "rank": rank,
                "attackRange": pspec.get("attackRange"),
                "cooldown": pspec.get("cooldown"),
                "damage": pspec.get("damage"),
                "damageType": pspec.get("damageType"),
                "forcedProc": pspec.get("forcedProc"),
                "radius": pspec.get("radius"),
                "manifoldStatusTypes": list(manifold_status_types),
            })

    if kind == "sentinel":
        equipped_attack = [
            (mod, rank, slot)
            for mod, rank, slot in body_mods
            if isinstance(mod.get("preceptSpec"), Mapping) and mod["preceptSpec"].get("isAttackPrecept")
        ]
        if not equipped_attack:
            warnings.append(
                "sentinel-no-attack-precept: Sentinel has no attack precept equipped; weapon will not fire"
            )
        elif has_weapon:
            can_attack = True
            mod, rank, slot = equipped_attack[0]
            pspec = mod["preceptSpec"]
            if pspec.get("usesMeleeRange"):
                attack_mode = "melee"
                base_rng = float(pspec.get("attackRange") or 10.0)
                engage_range = max(0.0, (base_rng + range_flat) * (1.0 + range_pct))
                sustain_range = engage_range
            else:
                attack_mode = "ranged"
                by_rank = pspec.get("attackRangeByRank")
                if isinstance(by_rank, Sequence) and 0 <= rank < len(by_rank):
                    base_at_rank = float(by_rank[rank])
                else:
                    max_r = max(int(mod.get("maxRank") or 1), 1)
                    full_rng = float(pspec.get("attackRange") or 30.0)
                    base_at_rank = (full_rng * 0.5) * (1.0 + rank / max_r)
                engage_range = base_at_rank * zoom_mult
                sustain_base = max(base_at_rank, float(pspec.get("sustainRange") or base_at_rank))
                sustain_range = sustain_base * zoom_mult
            attack_precept_info = {
                "path": mod["path"],
                "id": mod["id"],
                "nameEn": mod["nameEn"],
                "rank": rank,
                "slot": slot,
                "retaliatoryOnly": bool(pspec.get("retaliatoryOnly")),
            }
    elif kind == "moa":
        hard_engage = next((item for item in body_mods if item[0]["path"] == HARD_ENGAGE_PATH), None)
        if has_weapon:
            can_attack = True
            if hard_engage is not None:
                attack_mode = "melee"
                engage_range = max(0.0, (10.0 + range_flat) * (1.0 + range_pct))
                sustain_range = engage_range
                attack_precept_info = {
                    "path": HARD_ENGAGE_PATH,
                    "id": hard_engage[0]["id"],
                    "nameEn": hard_engage[0]["nameEn"],
                    "rank": hard_engage[1],
                    "slot": hard_engage[2],
                    "retaliatoryOnly": False,
                }
            else:
                attack_mode = "ranged"
                engage_range = 70.0 * zoom_mult
                sustain_range = engage_range
    elif kind == "hound":
        if has_weapon:
            can_attack = True
            attack_mode = "melee"
            engage_range = max(0.0, (25.0 + range_flat) * (1.0 + range_pct))
            sustain_range = engage_range

    raw_ai = _indices()["aiProfiles"].get(weapon_result["path"]) if weapon_result else None
    ai_duty_cycle = 1.0
    ai_summary: dict[str, Any] | None = None
    effective_max_range = engage_range if can_attack else 0.0

    if isinstance(raw_ai, Mapping):
        bt = raw_ai.get("burstTime") or [0.0, 0.0]
        bp = raw_ai.get("burstPauseTime") or [0.0, 0.0]
        mean_burst = (float(bt[0]) + float(bt[1])) * 0.5
        mean_pause = (float(bp[0]) + float(bp[1])) * 0.5
        if mean_burst > 0.0 and mean_pause > 0.0:
            ai_duty_cycle = mean_burst / (mean_burst + mean_pause)
        only_within = bool(raw_ai.get("onlyFireWithinRange"))
        trace_dist = weapon_result.get("rangeLimit") if weapon_result else raw_ai.get("traceDistance")
        if can_attack and only_within and isinstance(trace_dist, (int, float)):
            effective_max_range = min(engage_range, float(trace_dist))
        ai_summary = {
            "firingType": raw_ai.get("firingType"),
            "burstTime": list(bt),
            "burstPauseTime": list(bp),
            "aiDutyCycle": round(ai_duty_cycle, 6),
            "onlyFireWithinRange": only_within,
            "traceDistance": trace_dist,
            "desiredAttackRange": list(raw_ai.get("desiredAttackRange") or ()),
            "aimAtPart": raw_ai.get("aimAtPart", "TORSO"),
            "continuousAim": bool(raw_ai.get("continuousAim")),
            "artaxRetargetUnchilled": bool(raw_ai.get("artaxRetargetUnchilled")),
            "maxActiveProjectiles": raw_ai.get("maxActiveProjectiles"),
            "effectiveMaxRange": round(effective_max_range, 6),
            "shiveringContagionEquipped": shivering_equipped,
        }
    elif weapon_result is not None:
        ai_summary = {
            "firingType": "FT_NORMAL",
            "burstTime": [0.0, 0.0],
            "burstPauseTime": [0.0, 0.0],
            "aiDutyCycle": 1.0,
            "onlyFireWithinRange": False,
            "traceDistance": weapon_result.get("rangeLimit"),
            "desiredAttackRange": [5.0, effective_max_range or 10.0],
            "aimAtPart": "TORSO",
            "continuousAim": True,
            "artaxRetargetUnchilled": False,
            "maxActiveProjectiles": None,
            "effectiveMaxRange": round(effective_max_range, 6),
            "shiveringContagionEquipped": shivering_equipped,
        }

    clone_multiplier = 1 + max(0, duplex_active_clones)
    steady_stacks: dict[str, float] = {}
    effective_shots_per_sec = 0.0
    cold_procs_per_sec = 0.0
    heat_procs_per_sec = 0.0

    if can_attack and weapon_result is not None:
        raw_stats = weapon_result["_moddedStats"]
        procs_per_shot: Mapping[str, float] = weapon_result["_procsPerShot"]
        sustained_shots = float(weapon_result["_sustainedShotsPerSecond"])
        # Note: Duplex Bond clones deal weapon damage without triggering statuses/arcanes on their own precepts,
        # wait — wiki Duplex Bond: "Clones cannot use Companion abilities, and kills do not trigger Duplex Bond,
        # but clones fire copies of the companion weapon." Keep cloneMultiplier in attackProfile; base weapon rate
        # drives conservative 1x priming unless duplexClones > 0 scales weapon shots.
        effective_shots_per_sec = sustained_shots * ai_duty_cycle * clone_multiplier
        for dtype, per_shot in procs_per_shot.items():
            if per_shot <= 0.0 or effective_shots_per_sec <= 0.0:
                continue
            rate = per_shot * effective_shots_per_sec
            if dtype == "DT_FREEZE":
                cold_procs_per_sec = rate
            elif dtype == "DT_FIRE":
                heat_procs_per_sec = rate
            base_dur, base_cap = STATUS_PRIMING_RULES.get(dtype, (6.0, 10.0))
            dur_scale = proc_duration_scale(raw_stats, dtype)
            cap = proc_stack_cap(raw_stats, dtype, base_cap) if math.isfinite(base_cap) else math.inf
            expected_active = min(rate * base_dur * dur_scale, cap)
            if expected_active > 0.0:
                steady_stacks[dtype] = round(expected_active, 6)

    primed_types = [dt for dt, cnt in steady_stacks.items() if cnt > 0.0]
    distinct_count = sum(min(1.0, cnt) for cnt in steady_stacks.values())

    return (
        {
            "category": "robotic",
            "arenaActiveAttack": can_attack,
            "canAttack": can_attack,
            "attackMode": attack_mode,
            "engageRange": round(engage_range, 6),
            "sustainRange": round(sustain_range, 6),
            "effectiveMaxRange": round(effective_max_range, 6),
            "attackPrecept": attack_precept_info,
            "offensivePrecepts": offensive_precepts,
            "aiProfile": ai_summary,
            "shiveringContagionEquipped": shivering_equipped,
            "cloneMultiplier": clone_multiplier,
        },
        {
            "active": can_attack and bool(steady_stacks),
            "effectiveShotsPerSecond": round(effective_shots_per_sec, 6),
            "steadyPrimingStacks": steady_stacks,
            "primedStatusTypes": primed_types,
            "expectedDistinctStatusCount": round(distinct_count, 6),
            "coldProcsPerSecond": round(cold_procs_per_sec, 6),
            "heatProcsPerSecond": round(heat_procs_per_sec, 6),
        },
    )


@lru_cache(maxsize=8)
def _cached_default_enemy(build_label: str) -> Mapping[str, Any]:
    exp = _default_exports()
    return resolve_record(exp.get("enemies") or (), DEFAULT_TARGET_ENEMY_PATH, kind="enemy")


@lru_cache(maxsize=1)
def _cached_warframe_engine() -> Any:
    from .warframe import WarframeEngine, load_warframe_catalog

    wf_cat = load_warframe_catalog(
        _runtime_root() / "data/mechanics/warframe-builds.json",
        fallback=_default_exports(),
    )
    return WarframeEngine(wf_cat)


_ENEMY_PATH_INDEX_CACHE: dict[int, tuple[Any, dict[str, Mapping[str, Any]]]] = {}


def _fast_resolve_enemy(enemies_seq: Sequence[Mapping[str, Any]], query: str) -> Mapping[str, Any]:
    seq_id = id(enemies_seq)
    cached = _ENEMY_PATH_INDEX_CACHE.get(seq_id)
    if cached is None or cached[0] is not enemies_seq:
        if len(_ENEMY_PATH_INDEX_CACHE) >= 4:
            _ENEMY_PATH_INDEX_CACHE.clear()
        by_path = {str(rec["path"]): rec for rec in enemies_seq if isinstance(rec, Mapping) and rec.get("path")}
        _ENEMY_PATH_INDEX_CACHE[seq_id] = (enemies_seq, by_path)
    else:
        by_path = cached[1]
    exact = by_path.get(query)
    if exact is not None:
        return exact
    return resolve_record(enemies_seq, query, kind="enemy")


def _resolve_target_spec(
    target_config: Mapping[str, Any] | None,
    exports: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], int, bool]:
    if target_config is not None and not isinstance(target_config, Mapping):
        raise SimulationError("target_config must be an object or null")
    cfg = target_config or {}
    enemy_query = str(cfg.get("enemy") or cfg.get("path") or DEFAULT_TARGET_ENEMY_PATH).strip()
    level = cfg.get("level", DEFAULT_TARGET_LEVEL)
    if isinstance(level, bool) or not isinstance(level, int) or level < 1:
        raise SimulationError("target.level must be a positive integer")
    steel_path = cfg.get("steelPath", DEFAULT_TARGET_STEEL_PATH)
    if not isinstance(steel_path, bool):
        raise SimulationError("target.steelPath must be a boolean")

    exp = exports if exports is not None else _default_exports()
    enemies_seq = exp.get("enemies") or ()
    enemy_record = _fast_resolve_enemy(enemies_seq, enemy_query)
    return enemy_record, level, steel_path


def _vulnerability_multiplier(count: float) -> float:
    if count <= 0.0:
        return 1.0
    if count < 1.0:
        return 1.0 + count
    return min(2.0 + 0.25 * (count - 1.0), 4.25)


def _compute_target_evaluation(
    weapon_result: Mapping[str, Any],
    priming_stacks: Mapping[str, float],
    *,
    target_config: Mapping[str, Any] | None,
    exports: Mapping[str, Any] | None,
) -> dict[str, Any]:
    enemy_record, level, steel_path = _resolve_target_spec(target_config, exports)
    main_stats: ModdedStats = weapon_result["_moddedStats"]
    stat_lanes: Sequence[tuple[ModdedStats, float, Mapping[str, float] | None]] = weapon_result["_statLanes"]
    sustained_shots = float(weapon_result["_sustainedShotsPerSecond"])

    if priming_stacks:
        steady_stacks = {str(k): float(v) for k, v in priming_stacks.items() if float(v) > 0.0}
    else:
        steady_stacks = {}
        for dtype, rate in (weapon_result.get("sustainedProcsPerSecond") or {}).items():
            r_val = float(rate or 0.0)
            if r_val <= 0.0:
                continue
            base_dur, base_cap = STATUS_PRIMING_RULES.get(dtype, (6.0, 10.0))
            dur_scale = proc_duration_scale(main_stats, dtype)
            cap = proc_stack_cap(main_stats, dtype, base_cap) if math.isfinite(base_cap) else math.inf
            active_cnt = min(r_val * base_dur * dur_scale, cap)
            if active_cnt > 0.0:
                steady_stacks[str(dtype)] = active_cnt

    corr_cap = proc_stack_cap(main_stats, "DT_CORROSIVE", 10.0)
    corr_cnt = min(float(steady_stacks.get("DT_CORROSIVE") or 0.0), corr_cap)
    corr_strip = (0.26 * corr_cnt) if corr_cnt < 1.0 else min(0.26 + 0.06 * (corr_cnt - 1.0), 1.0)
    heat_cnt = min(float(steady_stacks.get("DT_FIRE") or 0.0), 1.0)
    heat_strip = 0.50 * heat_cnt
    elemental_strip = 1.0 - (1.0 - corr_strip) * (1.0 - heat_strip)

    on_hit_strip = min(1.0, max(0.0, float(weapon_result.get("armorStripOnHit") or 0.0)))
    steady_armor_strip = 1.0 - (1.0 - on_hit_strip) * (1.0 - elemental_strip)

    viral_cnt = min(float(steady_stacks.get("DT_VIRAL") or 0.0), 10.0)
    steady_viral_mult = _vulnerability_multiplier(viral_cnt)
    mag_cnt = min(float(steady_stacks.get("DT_MAGNETIC") or 0.0), 10.0)
    mag_stacks_int = min(10, int(round(mag_cnt)))
    punc_cap = proc_stack_cap(main_stats, "DT_PUNCTURE", 5.0)
    punc_crit = 0.05 * min(float(steady_stacks.get("DT_PUNCTURE") or 0.0), punc_cap)
    cold_cnt = min(float(steady_stacks.get("DT_FREEZE") or 0.0), 10.0)
    cold_crit = (
        1.0
        if cold_cnt >= 10.0
        else (0.1 * cold_cnt if cold_cnt < 1.0 else min(0.1 + 0.05 * (cold_cnt - 1.0), 0.5))
    )

    claw_co_bonus = float(weapon_result.get("_clawCoBonus") or 0.0)
    claw_base_scale = float(weapon_result.get("_clawBaseScale") or 1.0)
    distinct_statuses = sum(min(1.0, v) for v in steady_stacks.values() if v > 0.0)
    claw_co_mult = (
        (claw_base_scale + claw_co_bonus * distinct_statuses) / claw_base_scale
        if claw_co_bonus > 0.0 and distinct_statuses > 0.0 and claw_base_scale > 0.0
        else 1.0
    )

    defenses = enemy_defenses(
        enemy_record,
        level=level,
        steel_path=steel_path,
        armour_strip=on_hit_strip,
        elemental_armour_strip=elemental_strip,
        enemy_enhancements={"magneticStacks": mag_stacks_int},
    )
    has_overguard = float(defenses.get("overguard") or 0.0) > 0.0
    has_shield = float(defenses.get("shield") or 0.0) > 0.0
    raw_bypass = enemy_record.get("shieldBypassDamageTypes")
    shield_bypass = set(raw_bypass) if isinstance(raw_bypass, (list, tuple, set, frozenset)) else DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES

    def _dot_pool_mult(dtype: str) -> float:
        if has_overguard:
            return 1.0
        if has_shield and dtype not in shield_bypass:
            return 1.0
        return steady_viral_mult

    per_shot_direct = 0.0
    per_shot_dot = 0.0
    priming_without_corr = {k: v for k, v in steady_stacks.items() if k != "DT_CORROSIVE"}
    priming_enh = {"primingStacks": priming_without_corr} if priming_without_corr else None
    dot_enh = {"magneticStacks": mag_stacks_int} if mag_stacks_int > 0 else None

    for lane_stats, lane_weight, lane_forced in stat_lanes:
        direct_res = damage_against(
            lane_stats,
            enemy_record,
            level=level,
            steel_path=steel_path,
            armour_strip=on_hit_strip,
            elemental_armour_strip=elemental_strip,
            hit_location="body",
            enemy_enhancements=priming_enh,
        )
        lane_direct = float(direct_res.get("perShot") or 0.0) * claw_co_mult
        first_bonus = float(getattr(lane_stats, "first_shot_damage_bonus", 0.0) or 0.0)
        mag_sz = float(getattr(lane_stats, "magazine", 0.0) or 0.0)
        fs_factor = (1.0 + first_bonus / mag_sz) if (mag_sz > 0.0 and first_bonus > 0.0) else 1.0
        per_shot_direct += lane_direct * fs_factor * lane_weight

        adj_lane = replace(
            lane_stats,
            crit_chance=max(0.0, float(lane_stats.crit_chance) + punc_crit),
            crit_multiplier=max(1.0, float(lane_stats.crit_multiplier) + cold_crit),
        )
        status_res = expected_status_damage(
            adj_lane,
            enemy_record,
            forced_procs=lane_forced,
            level=level,
            steel_path=steel_path,
            armour_strip=on_hit_strip,
            elemental_armour_strip=elemental_strip,
            hit_location="body",
            enemy_enhancements=dot_enh,
        )
        lane_dot = 0.0
        for dtype, row in ((status_res.get("dot") or {}).get("perType") or {}).items():
            interaction = "DT_CINEMATIC" if dtype == "DT_SLASH" else str(dtype)
            lane_dot += float(row.get("expectedDamage") or 0.0) * _dot_pool_mult(interaction)
        for dtype, row in ((status_res.get("nonDot") or {}).get("perType") or {}).items():
            lane_dot += float(row.get("expectedDamage") or 0.0) * _dot_pool_mult(str(dtype))
        per_shot_dot += lane_dot * lane_weight

    sustained_direct_dps = per_shot_direct * sustained_shots
    sustained_dot_dps = per_shot_dot * sustained_shots
    total_target_dps = sustained_direct_dps + sustained_dot_dps

    return {
        "enemyPath": str(enemy_record.get("path") or ""),
        "enemyNameZh": enemy_record.get("nameZh") or enemy_record.get("nameEn") or "",
        "enemyNameEn": enemy_record.get("nameEn") or enemy_record.get("name") or "",
        "level": int(level),
        "steelPath": bool(steel_path),
        "perShotDirect": round(per_shot_direct, 3),
        "sustainedDirectDps": round(sustained_direct_dps, 3),
        "sustainedDotDps": round(sustained_dot_dps, 3),
        "totalTargetDps": round(total_target_dps, 3),
        "steadyArmorStrip": round(steady_armor_strip, 6),
        "steadyViralMultiplier": round(steady_viral_mult, 6),
    }


def evaluate_companion(
    companion_config: Mapping[str, Any],
    weapon_config: Mapping[str, Any] | None = None,
    *,
    warframe_panel: Mapping[str, Any] | None = None,
    primary_weapon_stats: Mapping[str, Any] | None = None,
    target_config: Mapping[str, Any] | None = None,
    exports: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate a complete Companion + Modular Parts + Weapon/Claws + Synergy loadout."""
    if not isinstance(companion_config, Mapping):
        raise SimulationError("companion_config must be an object")
    if weapon_config is not None and not isinstance(weapon_config, Mapping):
        raise SimulationError("weapon_config must be an object or null")
    if warframe_panel is not None and not isinstance(warframe_panel, Mapping):
        raise SimulationError("warframe_panel must be an object or null")
    if primary_weapon_stats is not None and not isinstance(primary_weapon_stats, Mapping):
        raise SimulationError("primary_weapon_stats must be an object or null")
    if target_config is not None and not isinstance(target_config, Mapping):
        raise SimulationError("target_config must be an object or null")

    companion = _resolve_companion(companion_config.get("path") or companion_config.get("id"))
    options = companion_config.get("options") or {}
    if not isinstance(options, Mapping):
        raise SimulationError("companion_config.options must be an object")

    reactor = companion_config.get("reactor", True)
    if not isinstance(reactor, bool):
        raise SimulationError("companion_config.reactor must be a boolean")
    gilded = companion_config.get("gilded", options.get("gilded", True))
    if not isinstance(gilded, bool):
        raise SimulationError("companion_config.gilded must be a boolean")

    cats_eye_mode = str(options.get("catsEyeMode", "average")).strip().lower()
    if cats_eye_mode not in {"average", "active", "off"}:
        raise SimulationError("options.catsEyeMode must be 'average', 'active', or 'off'")

    momentous_elem = options.get("momentousElement")
    if momentous_elem is not None and momentous_elem != "" and momentous_elem not in BASE_ELEMENTS:
        raise SimulationError(f"options.momentousElement must be one of {BASE_ELEMENTS} or null")

    duplex_clones_opt = options.get("duplexClones", 0)
    if isinstance(duplex_clones_opt, bool) or not isinstance(duplex_clones_opt, int) or not 0 <= duplex_clones_opt <= 3:
        raise SimulationError("options.duplexClones must be an integer in 0..3")

    warnings: list[str] = []
    assembly = _assemble_body(companion, companion_config.get("parts"), gilded=gilded)
    slot_polarities, body_forma_count = _resolve_slot_polarities(
        assembly["nativePolarities"],
        companion_config.get("polarities") if "polarities" in companion_config else companion_config.get("slotPolarities"),
        slot_count=BODY_SLOT_COUNT,
        label="companion.polarities",
    )

    body_mods = _parse_body_mods(companion, companion_config.get("mods"))
    body_by_path = {mod["path"]: (mod, rank, slot) for mod, rank, slot in body_mods}

    capacity_total = REACTOR_CAPACITY if reactor else BASE_CAPACITY
    used_capacity = 0
    body_slots_out: list[dict[str, Any]] = []
    body_set_entries: list[dict[str, Any]] = []

    pct_bonus = {
        "health": float(assembly["partPercentBonus"]["health"]),
        "shield": float(assembly["partPercentBonus"]["shield"]),
        "armor": float(assembly["partPercentBonus"]["armor"]),
        "shieldRecharge": 0.0,
        "shieldDelay": 0.0,
    }
    link_ratios = {"health": 0.0, "shield": 0.0, "armor": 0.0}
    overshield_cap_add = 0.0
    tek_enhance_bonus = 0.0

    for mod, rank, slot in body_mods:
        drain, rel = _normal_slot_drain(mod["baseDrain"], rank, mod.get("polarity"), slot_polarities[slot])
        used_capacity += drain
        body_slots_out.append({
            "slot": slot,
            "path": mod["path"],
            "id": mod["id"],
            "nameEn": mod["nameEn"],
            "rank": rank,
            "drain": drain,
            "slotPolarity": slot_polarities[slot],
            "polarityRelation": rel,
        })
        if mod.get("setId"):
            body_set_entries.append({
                "path": mod["path"],
                "setId": mod["setId"],
                "source": "companion",
            })
        if mod["path"] == TEK_ENHANCE_PATH:
            for upg in mod.get("upgrades") or ():
                if upg["type"] == "AVATAR_ABILITY_DURATION":
                    tek_enhance_bonus += _upgrade_value_at_rank(upg, rank)

        for upg in mod.get("upgrades") or ():
            utype = upg["type"]
            val = _upgrade_value_at_rank(upg, rank)
            if utype in BODY_STAT_UPGRADES and upg.get("operation") == "STACKING_MULTIPLY":
                pct_bonus[BODY_STAT_UPGRADES[utype]] += val
            elif utype in LINK_STAT_UPGRADES:
                link_ratios[LINK_STAT_UPGRADES[utype]] += val
            elif utype == "AVATAR_OVERSHIELD_MAX" and upg.get("operation") == "ADD":
                overshield_cap_add += val

    if used_capacity > capacity_total:
        warnings.append(f"companion-capacity-exceeded: {used_capacity}/{capacity_total}")
        if options.get("enforceCapacity") is True:
            raise SimulationError(f"companion MOD capacity exceeded: {used_capacity}/{capacity_total}")

    any_link_equipped = any(v > 0.0 for v in link_ratios.values())
    resolved_wf_panel = dict(NEUTRAL_WARFRAME_PANEL)
    if warframe_panel is not None:
        inner = warframe_panel.get("finalPanel") if isinstance(warframe_panel.get("finalPanel"), Mapping) else warframe_panel
        for stat in ("health", "shield", "armor"):
            raw_v = inner.get(stat)
            if raw_v is None and stat == "armor":
                raw_v = inner.get("armour")
            if raw_v is not None:
                resolved_wf_panel[stat] = max(0.0, _finite_float(raw_v, f"warframe_panel.{stat}"))
    elif any_link_equipped:
        warnings.append(
            "companion-link-mod-without-warframe: Link MOD equipped without a linked Warframe panel; "
            "falling back to neutral Warframe stats (300 health / 300 shield / 100 armor)"
        )

    body_stats: dict[str, Any] = {}
    for stat in ("health", "shield", "armor"):
        b_val = float(assembly["base"][stat])
        unmodded_val = b_val * (1.0 + float(assembly["partPercentBonus"][stat]))
        link_add = link_ratios[stat] * resolved_wf_panel[stat]
        modded_val = max(0.0, b_val * (1.0 + pct_bonus[stat]) + link_add)
        body_stats[stat] = {
            "base": round(b_val, 6),
            "unmodded": round(unmodded_val, 6),
            "modded": round(modded_val, 6),
            "percentBonus": round(pct_bonus[stat], 6),
            "linkBonus": round(link_add, 6),
        }

    modded_shield = float(body_stats["shield"]["modded"])
    overshield_cap = (COMPANION_OVERSHIELD_BASE_CAP + overshield_cap_add) if modded_shield > 0.0 else 0.0
    if modded_shield > 0.0:
        base_recharge = 15.0 + 0.05 * modded_shield
        modded_recharge = base_recharge * max(0.0, 1.0 + pct_bonus["shieldRecharge"])
        delay_mult = max(0.2, 1.0 + pct_bonus["shieldDelay"])
        base_delay = 4.0
        modded_delay = base_delay * delay_mult
        partial_delay = 1.0 * delay_mult
    else:
        base_recharge = 0.0
        modded_recharge = 0.0
        base_delay = 0.0
        modded_delay = 0.0
        partial_delay = 0.0

    body_stats["overshieldCap"] = round(overshield_cap, 6)
    body_stats["shieldRecharge"] = {
        "base": round(base_recharge, 6),
        "modded": round(modded_recharge, 6),
        "bonus": round(pct_bonus["shieldRecharge"], 6),
    }
    body_stats["shieldDelay"] = {
        "base": round(base_delay, 6),
        "modded": round(modded_delay, 6),
        "partialDelay": round(partial_delay, 6),
        "bonus": round(pct_bonus["shieldDelay"], 6),
    }

    body_weapon_effects = _body_to_weapon_effects(body_mods, options, warnings)

    # Evaluate paired weapon or Beast Claws.
    weapon_result: dict[str, Any] | None = None
    weapon_set_entries: list[dict[str, Any]] = []
    claws_idx = _indices()["claws"]

    effective_weapon_cfg = weapon_config
    if effective_weapon_cfg is None and companion["category"] == "beast":
        effective_weapon_cfg = {"path": companion["defaultWeaponPath"]}

    if effective_weapon_cfg is not None:
        w_query = str(effective_weapon_cfg.get("path") or companion.get("defaultWeaponPath") or "").strip()
        claw_match = claws_idx.get(w_query) or claws_idx.get(w_query.casefold())
        if claw_match is not None:
            weapon_result, weapon_set_entries = _evaluate_beast_claws(
                companion,
                claw_match,
                effective_weapon_cfg,
                reactor=reactor,
                body_mods=body_mods,
                body_weapon_effects=body_weapon_effects,
                primary_weapon_stats=primary_weapon_stats,
                warnings=warnings,
            )
            if options.get("enforceCapacity") is True and not weapon_result["capacity"]["valid"]:
                raise SimulationError("Beast Claw MOD capacity exceeded")
        else:
            if companion["category"] == "beast":
                raise SimulationError(f"{companion['nameEn']} can only equip its breed Beast Claws")
            weapon_result, weapon_set_entries = _evaluate_robotic_weapon(
                companion,
                effective_weapon_cfg,
                reactor=reactor,
                body_mods=body_mods,
                body_weapon_effects=body_weapon_effects,
                exports=exports,
                warnings=warnings,
            )
            if options.get("enforceCapacity") is True and not weapon_result["capacity"]["valid"]:
                raise SimulationError("robotic weapon MOD capacity exceeded")

    # Build Player Synergy Bridge (14 Bonds + Buff Precepts + Cross-Entity Set Mods).
    player_effects = ModEffectList()
    companion_cc = float(weapon_result["critChance"]) if weapon_result is not None else 0.0

    # 1. Tenacious Bond (> 50% companion weapon/claw crit chance)
    tb_row = body_by_path.get(TENACIOUS_BOND_PATH)
    tb_equipped = tb_row is not None
    tb_rank = tb_row[1] if tb_row else 0
    tb_active = tb_equipped and round(companion_cc, 8) > TENACIOUS_BOND_CRIT_THRESHOLD
    tb_bonus = float(tb_row[0]["bondSpec"]["playerFinalCritDamageByRank"][tb_rank]) if tb_active else 0.0
    if tb_active:
        player_effects.append(
            ModEffect("RUNTIME_FINAL_CRIT_DAMAGE", "ADD", tb_bonus, source_path=TENACIOUS_BOND_PATH)
        )
    tenacious_bond = {
        "equipped": tb_equipped,
        "rank": tb_rank,
        "companionCritChance": round(companion_cc, 6),
        "threshold": TENACIOUS_BOND_CRIT_THRESHOLD,
        "active": tb_active,
        "finalCritDamageBonus": round(tb_bonus, 6),
        "headshotRecoveryReduction": (
            float(tb_row[0]["bondSpec"]["headshotRecoveryReductionByRank"][tb_rank]) if tb_equipped else 0.0
        ),
    }

    # 2. Reinforced Bond (>= 1200 max shield or Overshield via player reloads)
    rb_row = body_by_path.get(REINFORCED_BOND_PATH)
    rb_equipped = rb_row is not None
    rb_rank = rb_row[1] if rb_row else 0
    rb_static_active = rb_equipped and (modded_shield >= REINFORCED_BOND_SHIELD_THRESHOLD - 1e-6)
    rb_reload_os = float(rb_row[0]["bondSpec"]["reloadOvershieldGrantByRank"][rb_rank]) if rb_equipped else 0.0
    rb_card_bonus = float(rb_row[0]["bondSpec"]["playerFireRateBonusByRank"][rb_rank]) if rb_equipped else 0.0
    if not rb_equipped or modded_shield <= 0.0:
        rb_reloads_needed: int | None = None
        rb_fire_rate_bonus = 0.0
    elif rb_static_active:
        rb_reloads_needed = 0
        rb_fire_rate_bonus = rb_card_bonus
    elif modded_shield + overshield_cap >= REINFORCED_BOND_SHIELD_THRESHOLD - 1e-6 and rb_reload_os > 0.0:
        rb_reloads_needed = math.ceil((REINFORCED_BOND_SHIELD_THRESHOLD - modded_shield) / rb_reload_os)
        rb_fire_rate_bonus = rb_card_bonus
    else:
        rb_reloads_needed = None
        rb_fire_rate_bonus = 0.0

    rb_apply_static = rb_static_active or (
        rb_equipped and modded_shield > 0.0 and options.get("reinforcedBondAssumeOvershield") is True
    )
    if rb_apply_static and rb_card_bonus > 0.0:
        player_effects.append(
            ModEffect("WEAPON_FIRE_RATE", "STACKING_MULTIPLY", rb_card_bonus, source_path=REINFORCED_BOND_PATH)
        )
    reinforced_bond = {
        "equipped": rb_equipped,
        "rank": rb_rank,
        "companionMaxShield": round(modded_shield, 6),
        "threshold": REINFORCED_BOND_SHIELD_THRESHOLD,
        "staticActive": rb_static_active,
        "reloadOvershield": round(rb_reload_os, 6),
        "reloadsNeededForThreshold": rb_reloads_needed,
        "fireRateBonus": round(rb_fire_rate_bonus, 6),
        "staticFireRateBonus": round(rb_card_bonus if rb_static_active else 0.0, 6),
    }

    # 3. Manifold Bond
    mb_row = body_by_path.get(MANIFOLD_BOND_PATH)
    mb_equipped = mb_row is not None
    mb_rank = mb_row[1] if mb_row else 0
    if mb_equipped and companion["category"] == "robotic" and weapon_result is not None:
        mb_status_types = list(
            weapon_result.get("positiveDamageTypes")
            or [dt for dt, amt in weapon_result["damageTypes"].items() if amt > 0.0]
        )
    else:
        mb_status_types = []
    manifold_bond = {
        "equipped": mb_equipped,
        "rank": mb_rank,
        "uniqueStatusThreshold": (
            float(mb_row[0]["bondSpec"]["uniqueStatusesRequiredByRank"][mb_rank]) if mb_equipped else 0.0
        ),
        "cooldownReduction": (
            float(mb_row[0]["bondSpec"]["cooldownReductionByRank"][mb_rank]) if mb_equipped else 0.0
        ),
        "preceptStatusTypes": mb_status_types,
    }

    # 4. Contagious Bond
    cb_row = body_by_path.get(CONTAGIOUS_BOND_PATH)
    cb_equipped = cb_row is not None
    cb_rank = cb_row[1] if cb_row else 0
    contagious_bond = {
        "equipped": cb_equipped,
        "rank": cb_rank,
        "spreadRatio": float(cb_row[0]["bondSpec"]["statusSpreadFractionByRank"][cb_rank]) if cb_equipped else 0.0,
        "spreadRadius": float(cb_row[0]["bondSpec"]["radiusByRank"][cb_rank]) if cb_equipped else 0.0,
        "maxStacks": 100,
    }

    # 5. Vicious Bond
    vb_row = body_by_path.get(VICIOUS_BOND_PATH)
    vb_equipped = vb_row is not None
    vb_rank = vb_row[1] if vb_row else 0
    vicious_bond = {
        "equipped": vb_equipped,
        "rank": vb_rank,
        "armorStrip": float(vb_row[0]["bondSpec"]["armorStripFractionByRank"][vb_rank]) if vb_equipped else 0.0,
        "radiusOnAbilityMarked": float(vb_row[0]["bondSpec"]["spreadRadiusByRank"][vb_rank]) if vb_equipped else 0.0,
    }

    # 6. Tandem Bond
    tdb_row = body_by_path.get(TANDEM_BOND_PATH)
    tdb_equipped = tdb_row is not None
    tdb_rank = tdb_row[1] if tdb_row else 0
    tandem_bond = {
        "equipped": tdb_equipped,
        "rank": tdb_rank,
        "comboGainPerHit": float(tdb_row[0]["bondSpec"]["comboGainPerHitByRank"][tdb_rank]) if tdb_equipped else 0.0,
        "heavyAttackBonusPerComboMult": (
            float(tdb_row[0]["bondSpec"]["heavyAttackCompanionMeleeBonusPerComboMultByRank"][tdb_rank])
            if tdb_equipped
            else 0.0
        ),
        "duration": 30.0 if tdb_equipped else 0.0,
    }

    # 7. Duplex Bond
    dpb_row = body_by_path.get(DUPLEX_BOND_PATH)
    dpb_equipped = dpb_row is not None
    dpb_rank = dpb_row[1] if dpb_row else 0
    duplex_active_clones = duplex_clones_opt if dpb_equipped else 0
    duplex_bond = {
        "equipped": dpb_equipped,
        "rank": dpb_rank,
        "energySpentThreshold": 100.0,
        "maxClones": 3,
        "activeClones": duplex_active_clones,
        "cloneDuration": float(dpb_row[0]["bondSpec"]["cloneDurationByRank"][dpb_rank]) if dpb_equipped else 0.0,
        "energyOrbDropChance": (
            float(dpb_row[0]["bondSpec"]["energyOrbDropChanceByRank"][dpb_rank]) if dpb_equipped else 0.0
        ),
    }

    # 8. Mystic Bond
    myb_row = body_by_path.get(MYSTIC_BOND_PATH)
    myb_equipped = myb_row is not None
    myb_rank = myb_row[1] if myb_row else 0
    mystic_bond = {
        "equipped": myb_equipped,
        "rank": myb_rank,
        "requiredCooldownCasts": (
            int(myb_row[0]["bondSpec"]["requiredCooldownCastsByRank"][myb_rank]) if myb_equipped else 0
        ),
        "freeAbilityCastsGranted": 1 if myb_equipped else 0,
    }

    # 9. Seismic Bond
    sb_row = body_by_path.get(SEISMIC_BOND_PATH)
    sb_equipped = sb_row is not None
    sb_rank = sb_row[1] if sb_row else 0
    seismic_bond = {
        "equipped": sb_equipped,
        "rank": sb_rank,
        "shockwaveRadius": 4.0 if sb_equipped else 0.0,
        "shockwaveDamageShare": (
            float(sb_row[0]["bondSpec"]["shockwaveDamageShareByRank"][sb_rank]) if sb_equipped else 0.0
        ),
        "abilityEfficiencyPerStack": (
            float(sb_row[0]["bondSpec"]["abilityEfficiencyPerStackByRank"][sb_rank]) if sb_equipped else 0.0
        ),
        "maxStacks": 10,
        "duration": float(sb_row[0]["bondSpec"]["durationByRank"][sb_rank]) if sb_equipped else 0.0,
    }

    # 10. Aerial Bond
    ab_row = body_by_path.get(AERIAL_BOND_PATH)
    ab_equipped = ab_row is not None
    ab_rank = ab_row[1] if ab_row else 0
    aerial_bond = {
        "equipped": ab_equipped,
        "rank": ab_rank,
        "airKillRecoveryReduction": (
            float(ab_row[0]["bondSpec"]["airKillRecoveryReductionByRank"][ab_rank]) if ab_equipped else 0.0
        ),
        "headshotAirKillRecoveryReduction": (
            float(ab_row[0]["bondSpec"]["headshotAirKillRecoveryReductionByRank"][ab_rank]) if ab_equipped else 0.0
        ),
        "coldFieldMaxSlow": float(ab_row[0]["bondSpec"]["coldFieldMaxSlowByRank"][ab_rank]) if ab_equipped else 0.0,
        "coldFieldMaxRadius": float(ab_row[0]["bondSpec"]["coldFieldMaxRadiusByRank"][ab_rank]) if ab_equipped else 0.0,
        "lingerDuration": 3.0 if ab_equipped else 0.0,
    }

    # 11. Restorative Bond
    rsb_row = body_by_path.get(RESTORATIVE_BOND_PATH)
    rsb_equipped = rsb_row is not None
    rsb_rank = rsb_row[1] if rsb_row else 0
    restorative_bond = {
        "equipped": rsb_equipped,
        "rank": rsb_rank,
        "bonusHealthPerOrb": float(rsb_row[0]["bondSpec"]["bonusHealthPerOrbByRank"][rsb_rank]) if rsb_equipped else 0.0,
        "recoveryReductionPerOrb": (
            float(rsb_row[0]["bondSpec"]["recoveryReductionPerOrbByRank"][rsb_rank]) if rsb_equipped else 0.0
        ),
    }

    # 12. Covert Bond
    cvb_row = body_by_path.get(COVERT_BOND_PATH)
    cvb_equipped = cvb_row is not None
    cvb_rank = cvb_row[1] if cvb_row else 0
    covert_bond = {
        "equipped": cvb_equipped,
        "rank": cvb_rank,
        "stealthDuration": float(cvb_row[0]["bondSpec"]["stealthDurationByRank"][cvb_rank]) if cvb_equipped else 0.0,
        "maxStealthDuration": 60.0,
    }

    # 13. Momentous Bond
    mmb_row = body_by_path.get(MOMENTOUS_BOND_PATH)
    mmb_equipped = mmb_row is not None
    mmb_rank = mmb_row[1] if mmb_row else 0
    momentous_bond = {
        "equipped": mmb_equipped,
        "rank": mmb_rank,
        "activeElement": momentous_elem if (mmb_equipped and momentous_elem in BASE_ELEMENTS) else None,
        "companionElementalBonus": (
            float(mmb_row[0]["bondSpec"]["companionElementalBonusByRank"][mmb_rank]) if mmb_equipped else 0.0
        ),
        "duration": 30.0 if mmb_equipped else 0.0,
        "recoveryReduction": float(mmb_row[0]["bondSpec"]["recoveryReductionByRank"][mmb_rank]) if mmb_equipped else 0.0,
    }

    # 14. Astral Bond
    asb_row = body_by_path.get(ASTRAL_BOND_PATH)
    asb_equipped = asb_row is not None
    asb_rank = asb_row[1] if asb_row else 0
    astral_bond = {
        "equipped": asb_equipped,
        "rank": asb_rank,
        "active": bool(asb_equipped and options.get("astralBond") is True),
        "companionDamageBonus": (
            float(asb_row[0]["bondSpec"]["companionDamageBonusByRank"][asb_rank]) if asb_equipped else 0.0
        ),
        "companionVoidDamageBonus": (
            float(asb_row[0]["bondSpec"]["companionVoidDamageByRank"][asb_rank]) if asb_equipped else 0.0
        ),
        "operatorEfficiencyBonus": (
            float(asb_row[0]["bondSpec"]["operatorEfficiencyByRank"][asb_rank]) if asb_equipped else 0.0
        ),
        "damageDuration": 10.0 if asb_equipped else 0.0,
        "efficiencyDuration": 5.0 if asb_equipped else 0.0,
    }

    # Buff Precepts: Cat's Eye, Ambush, Anabolic Pollination, Charm, Shield Charger.
    ce_row = body_by_path.get(CATS_EYE_PATH)
    ce_equipped = ce_row is not None
    ce_rank = ce_row[1] if ce_row else 0
    if ce_equipped:
        ce_pspec = ce_row[0]["preceptSpec"]
        ce_buff = ce_pspec["playerBuff"]
        ce_raw_crit = float(ce_buff["valueByRank"][ce_rank])
        ce_duration = float(ce_buff["duration"]) * (1.0 + tek_enhance_bonus)
        ce_cooldown = float(ce_pspec["cooldownByRank"][ce_rank])
        if cats_eye_mode == "active":
            ce_uptime = 1.0
        elif cats_eye_mode == "off":
            ce_uptime = 0.0
        else:
            ce_uptime = min(1.0, ce_duration / ce_cooldown)
        ce_effective = ce_raw_crit * ce_uptime
        if ce_effective > 0.0:
            player_effects.append(
                ModEffect("WEAPON_CRIT_CHANCE", "ADD", ce_effective, source_path=CATS_EYE_PATH)
            )
    else:
        ce_raw_crit = 0.0
        ce_duration = 0.0
        ce_cooldown = 0.0
        ce_uptime = 0.0
        ce_effective = 0.0

    amb_row = body_by_path.get(AMBUSH_PATH)
    amb_equipped = amb_row is not None
    amb_rank = amb_row[1] if amb_row else 0
    amb_active = bool(amb_equipped and options.get("ambushActive") is True)
    amb_max_bonus = float(amb_row[0]["preceptSpec"]["playerBuff"]["valueByRank"][amb_rank]) if amb_equipped else 0.0
    amb_effective = amb_max_bonus if amb_active else 0.0
    if amb_active and amb_effective > 0.0:
        player_effects.append(
            ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", amb_effective, source_path=AMBUSH_PATH)
        )

    ap_row = body_by_path.get(ANABOLIC_POLLINATION_PATH)
    ap_equipped = ap_row is not None
    ap_rank = ap_row[1] if ap_row else 0
    ap_active = bool(ap_equipped and options.get("anabolicPollinationActive") is True)
    ap_bonus = 0.25 * (ap_rank + 1) if ap_equipped else 0.0
    if ap_active and ap_bonus > 0.0:
        player_effects.append(
            ModEffect(
                "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
                "STACKING_MULTIPLY",
                ap_bonus,
                damage_type="DT_POISON",
                source_path=ANABOLIC_POLLINATION_PATH,
            )
        )

    charm_row = body_by_path.get(CHARM_PATH)
    sc_row = body_by_path.get(SHIELD_CHARGER_PATH)

    # Cross-entity Set Mod collection (deduplicated by path).
    set_mod_paths: list[dict[str, str]] = []
    seen_set_paths: set[str] = set()
    for entry in (*body_set_entries, *weapon_set_entries):
        if entry["path"] not in seen_set_paths:
            seen_set_paths.add(entry["path"])
            set_mod_paths.append(entry)
    set_piece_counts = dict(Counter(entry["setId"] for entry in set_mod_paths))

    attack_profile, priming_summary = _build_attack_and_priming(
        companion,
        body_mods,
        weapon_result,
        manifold_bond["preceptStatusTypes"],
        duplex_active_clones,
        warnings,
    )

    if weapon_result is not None:
        effective_target_cfg = (
            target_config
            if target_config is not None
            else (
                effective_weapon_cfg.get("target")
                if isinstance(effective_weapon_cfg, Mapping) and isinstance(effective_weapon_cfg.get("target"), Mapping)
                else None
            )
        )
        weapon_result["targetEvaluation"] = _compute_target_evaluation(
            weapon_result,
            priming_summary["steadyPrimingStacks"],
            target_config=effective_target_cfg,
            exports=exports,
        )
        weapon_result = {k: v for k, v in weapon_result.items() if not k.startswith("_")}

    return {
        "companion": {
            "path": companion["path"],
            "id": companion["id"],
            "nameEn": companion["nameEn"],
            "nameZh": companion["nameZh"],
            "kind": companion["kind"],
            "category": companion["category"],
            "prime": companion["prime"],
            "portraitAsset": companion["portraitAsset"],
        },
        "assembly": {
            "family": assembly["family"],
            "gilded": assembly["gilded"],
            "parts": assembly["parts"],
            "resistances": assembly["resistances"],
            "unlockedPrecepts": assembly["unlockedPrecepts"],
        },
        "stats": body_stats,
        "capacity": {
            "used": used_capacity,
            "total": capacity_total,
            "remaining": capacity_total - used_capacity,
            "valid": used_capacity <= capacity_total,
            "reactor": reactor,
        },
        "slots": body_slots_out,
        "slotPolarities": slot_polarities,
        "nativePolarities": assembly["nativePolarities"],
        "formaCount": body_forma_count,
        "weaponEffects": [_serialize_effect(e) for e in body_weapon_effects],
        "weapon": weapon_result,
        "playerBridge": {
            "playerWeaponEffects": [_serialize_effect(e) for e in player_effects],
            "tenaciousBond": tenacious_bond,
            "reinforcedBond": reinforced_bond,
            "manifoldBond": manifold_bond,
            "contagiousBond": contagious_bond,
            "viciousBond": vicious_bond,
            "tandemBond": tandem_bond,
            "duplexBond": duplex_bond,
            "mysticBond": mystic_bond,
            "seismicBond": seismic_bond,
            "aerialBond": aerial_bond,
            "restorativeBond": restorative_bond,
            "covertBond": covert_bond,
            "momentousBond": momentous_bond,
            "astralBond": astral_bond,
            "buffPrecepts": {
                "catsEye": {
                    "equipped": ce_equipped,
                    "rank": ce_rank,
                    "mode": cats_eye_mode,
                    "flatCritBonus": round(ce_raw_crit, 6),
                    "effectiveCritBonus": round(ce_effective, 6),
                    "duration": round(ce_duration, 6),
                    "cooldown": round(ce_cooldown, 6),
                    "uptime": round(ce_uptime, 6),
                },
                "ambush": {
                    "equipped": amb_equipped,
                    "rank": amb_rank,
                    "active": amb_active,
                    "weaponDamageBonus": round(amb_effective, 6),
                    "maxWeaponDamageBonus": round(amb_max_bonus, 6),
                    "duration": 3.0 if amb_equipped else 0.0,
                },
                "anabolicPollination": {
                    "equipped": ap_equipped,
                    "rank": ap_rank,
                    "active": ap_active,
                    "toxinDamageBonus": round(ap_bonus if ap_active else 0.0, 6),
                    "maxToxinDamageBonus": round(ap_bonus, 6),
                    "duration": 15.0 if ap_equipped else 0.0,
                },
                "charm": {
                    "equipped": charm_row is not None,
                    "rank": charm_row[1] if charm_row else 0,
                },
                "shieldCharger": {
                    "equipped": sc_row is not None,
                    "rank": sc_row[1] if sc_row else 0,
                    "frameShieldMaxBonus": 0.10 * (sc_row[1] + 1) if sc_row else 0.0,
                    "frameShieldRechargeBonus": 0.10 * (sc_row[1] + 1) if sc_row else 0.0,
                    "duration": 5.0 + 1.0 * sc_row[1] if sc_row else 0.0,
                },
            },
            "setModPaths": set_mod_paths,
            "setPieceCounts": set_piece_counts,
            "vigilanteCritEnhanceChance": round(0.05 * set_piece_counts.get("VigilanteSetMod", 0), 6),
        },
        "attackProfile": attack_profile,
        "primingSummary": priming_summary,
        "warnings": warnings,
    }


_COMPANION_ELEMENT_TARGETS: dict[str, str] = {
    "heat": "DT_FIRE",
    "cold": "DT_FREEZE",
    "electricity": "DT_ELECTRICITY",
    "toxin": "DT_POISON",
    "blast": "DT_EXPLOSION",
    "radiation": "DT_RADIATION",
    "gas": "DT_GAS",
    "magnetic": "DT_MAGNETIC",
    "viral": "DT_VIRAL",
    "corrosive": "DT_CORROSIVE",
}
_COMPOUND_COMPONENT_PARTS: dict[str, tuple[str, str]] = {
    "DT_EXPLOSION": ("DT_FIRE", "DT_FREEZE"),
    "DT_RADIATION": ("DT_FIRE", "DT_ELECTRICITY"),
    "DT_GAS": ("DT_FIRE", "DT_POISON"),
    "DT_MAGNETIC": ("DT_FREEZE", "DT_ELECTRICITY"),
    "DT_VIRAL": ("DT_FREEZE", "DT_POISON"),
    "DT_CORROSIVE": ("DT_ELECTRICITY", "DT_POISON"),
}
_OPTIMIZE_GOALS = frozenset({"dps", "singleHit", "statusPriming", "tenaciousBond"})


def _resolve_element_target(raw_elem: Any) -> str | None:
    if raw_elem is None or raw_elem == "":
        return None
    if not isinstance(raw_elem, str):
        raise SimulationError("elementTarget must be a string or null")
    clean = raw_elem.strip()
    if not clean:
        return None
    low = clean.casefold()
    if low in _COMPANION_ELEMENT_TARGETS:
        return _COMPANION_ELEMENT_TARGETS[low]
    up = clean.upper()
    if up in ALL_CONVERTIBLE_ELEMENTS or up in PHYSICAL_TYPES:
        return up
    raise SimulationError(
        f"elementTarget must be empty or one of {sorted(_COMPANION_ELEMENT_TARGETS)}, got {raw_elem!r}"
    )


@lru_cache(maxsize=32)
def _cached_claw_packed_pool(claw_path: str) -> tuple[tuple[Any, ...], ...]:
    raw_cat = _raw_catalog()
    normal_pool: list[dict[str, Any]] = []
    for mod in raw_cat["clawMods"]:
        if mod.get("isPosture"):
            continue
        allowed_weapons = (mod.get("compat") or {}).get("weaponPaths")
        if allowed_weapons is not None and claw_path not in allowed_weapons:
            continue
        rank = int(mod["maxRank"])
        raw_drain = int(mod["baseDrain"]) + rank
        pol = mod.get("polarity")
        polar_drain = math.ceil(raw_drain / 2) if pol and pol not in ("", "AP_UNIVERSAL") else raw_drain
        path = str(mod["path"])
        fam = _canonical_mod_family(mod)

        b_dmg = cc = cd = sc = p_dur = p_dmg = atk = co = nc = hs = mo = rng = 0.0
        pre_e: list[ModEffect] = []
        post_e: list[ModEffect] = []
        conv_post: tuple[str, float] | None = None
        d_elems: dict[str, float] = {}
        base_elems_list: list[str] = []

        for upg in mod.get("upgrades") or ():
            ut = upg["type"]
            val = _upgrade_value_at_rank(upg, rank)
            dt = upg.get("damageType") or "DT_ANY"
            if ut in {"WEAPON_MELEE_DAMAGE", "WEAPON_DAMAGE_AMOUNT"}:
                b_dmg += val
            elif ut == "WEAPON_CRIT_CHANCE":
                cc += val
            elif ut == "WEAPON_CRIT_DAMAGE":
                cd += val
            elif ut == "WEAPON_PROC_CHANCE":
                sc += val
            elif ut == "WEAPON_PROC_TIME":
                p_dur += val
            elif ut == "WEAPON_PROC_DAMAGE":
                p_dmg += val
            elif ut == "WEAPON_FIRE_RATE":
                atk += val
            elif ut == "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE":
                co += val
            elif ut == "WEAPON_NOCRIT_DAMAGE":
                nc += val
            elif ut == "AVATAR_SENTINEL_CRIT_LINK":
                hs += val
            elif ut == "AVATAR_SENTINEL_STATUS_LINK":
                mo += val
            elif ut == "WEAPON_RANGE":
                rng += val
            elif ut in {"WEAPON_PERCENT_BASE_DAMAGE_ADDED", "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"}:
                if dt in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                    d_elems[dt] = d_elems.get(dt, 0.0) + val
                if path in CLAW_ELEMENTAL_CONVERSIONS:
                    conv_post = (CLAW_ELEMENTAL_CONVERSIONS[path], val)
                elif ut == "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE":
                    post_e.append(ModEffect(ut, "STACKING_MULTIPLY", val, damage_type=dt, source_path=path))
                else:
                    if dt in BASE_ELEMENTS:
                        base_elems_list.append(dt)
                    pre_e.append(ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", val, damage_type=dt, source_path=path))

        normal_pool.append({
            "mod": mod,
            "rank": rank,
            "path": path,
            "id": mod["id"],
            "family": fam,
            "raw_drain": raw_drain,
            "polar_drain": polar_drain,
            "polarity": pol,
            "base_elems": tuple(base_elems_list),
            "b_dmg": b_dmg,
            "cc": cc,
            "cd": cd,
            "sc": sc,
            "p_dur": p_dur,
            "p_dmg": p_dmg,
            "atk": atk,
            "co": co,
            "nc": nc,
            "hs": hs,
            "mo": mo,
            "rng": rng,
            "forced_imp": (1.0 * (rank + 1)) if mod["id"] == "bell_ringer" else 0.0,
            "mag_strike": (0.25 * (rank + 1)) if mod["id"] == "magnetic_strike" else 0.0,
            "phys_conv": CLAW_PHYSICAL_CONVERSIONS.get(path),
            "elem_conv": CLAW_ELEMENTAL_CONVERSIONS.get(path),
            "conv_post": conv_post,
            "pre_e": tuple(pre_e),
            "post_e": tuple(post_e),
            "d_elems": d_elems,
        })

    fam_bit_map: dict[str, int] = {}
    packed: list[tuple[Any, ...]] = []
    for idx, it in enumerate(normal_pool):
        fam = it["family"]
        f_idx = fam_bit_map.setdefault(fam, len(fam_bit_map))
        path_bit = 1 << idx
        conflict_mask = path_bit | (1 << (32 + f_idx))
        elem_tok = it["base_elems"] or ((it["elem_conv"],) if it["elem_conv"] else ())
        has_elem_eff = bool(it["pre_e"] or it["post_e"])
        de = it["d_elems"]
        packed.append((
            it,
            conflict_mask,
            path_bit,
            int(it["polar_drain"]),
            elem_tok,
            has_elem_eff,
            it["path"],
            float(it["b_dmg"]),
            float(it["cc"]),
            float(it["cd"]),
            float(it["sc"]),
            float(it["p_dur"]),
            float(it["p_dmg"]),
            float(it["atk"]),
            float(it["co"]),
            float(it["nc"]),
            float(it["hs"]),
            float(it["mo"]),
            float(it["forced_imp"]),
            float(it["mag_strike"]),
            it["phys_conv"],
            it["elem_conv"],
            it["conv_post"],
            float(de.get("DT_FIRE", 0.0)),
            float(de.get("DT_POISON", 0.0)),
            float(de.get("DT_ELECTRICITY", 0.0)),
            float(de.get("DT_GAS", 0.0)),
        ))
    return tuple(packed)


_PERSISTENT_POSTURE_EFFECTS = {
    lvls: ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", 0.10 * lvls, damage_type="DT_IMPACT")
    for lvls in range(1, 8)
}


def _optimize_beast_claws(
    companion: Mapping[str, Any],
    claw: Mapping[str, Any],
    *,
    companion_cfg: Mapping[str, Any],
    weapon_cfg: Mapping[str, Any],
    weapon_reactor: bool,
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    body_weapon_effects: ModEffectList,
    warframe_panel: Mapping[str, Any] | None,
    primary_weapon_stats: Mapping[str, Any] | None,
    goal: str,
    required_damage_type: str | None,
    target_cfg: Mapping[str, Any] | None,
    exports: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from . import optimizer

    raw_cat = _raw_catalog()
    claw_mods_idx = _indices()["clawMods"]
    base_cap = REACTOR_CAPACITY if weapon_reactor else BASE_CAPACITY

    raw_posture = weapon_cfg.get("posture")
    lock_posture = bool(weapon_cfg.get("lockPosture") or weapon_cfg.get("postureLocked"))
    if isinstance(raw_posture, Mapping) and lock_posture:
        p_query = str(raw_posture.get("path") or raw_posture.get("id") or "").strip()
        p_mod = claw_mods_idx.get(p_query) or claw_mods_idx.get(p_query.casefold())
        if p_mod is None or not p_mod.get("isPosture"):
            raise SimulationError(f"weapon.posture is not a valid Beast Claw posture MOD: {p_query!r}")
        p_rank = int(raw_posture.get("rank", p_mod["maxRank"]))
        posture_candidates = [(p_mod, p_rank)]
    else:
        # Evaluate distinct mechanical postures (frenzied, protector, persistent, assassin, balanced).
        seen_posture_ids: set[str] = set()
        posture_candidates = []
        for m in raw_cat["clawMods"]:
            if m.get("isPosture") and m["id"] not in {"elusive_posture"} and m["id"] not in seen_posture_ids:
                seen_posture_ids.add(m["id"])
                posture_candidates.append((m, int(m["maxRank"])))

    primary_cc = 0.0
    primary_sc = 0.0
    if isinstance(primary_weapon_stats, Mapping):
        primary_cc = max(
            0.0,
            _finite_float(
                primary_weapon_stats.get("critChance", primary_weapon_stats.get("crit_chance")),
                "primary_weapon_stats.critChance",
            ),
        )
        primary_sc = max(
            0.0,
            _finite_float(
                primary_weapon_stats.get("statusChance", primary_weapon_stats.get("status_chance")),
                "primary_weapon_stats.statusChance",
            ),
        )

    vicious_strip = 0.0
    sharpened_strip = 0.0
    for b_mod, b_rank, _ in body_mods:
        if b_mod["path"] == VICIOUS_BOND_PATH:
            vicious_strip = float(b_mod["bondSpec"]["armorStripFractionByRank"][b_rank])
        elif b_mod["path"] == SHARPENED_CLAWS_PATH:
            sharpened_strip = min(1.0, 0.30 * (b_rank + 1))
    on_hit_strip = min(1.0, vicious_strip + sharpened_strip)

    enemy_record, target_level, target_sp = _resolve_target_spec(target_cfg, exports)
    base_defenses = enemy_defenses(
        enemy_record,
        level=target_level,
        steel_path=target_sp,
        armour_strip=on_hit_strip,
        elemental_armour_strip=0.0,
    )
    base_armour_after_onhit = float(base_defenses.get("armour") or 0.0)
    base_armour_mit = (1.0 - _armour_reduction(base_armour_after_onhit)) if base_armour_after_onhit > 0.0 else 1.0
    target_shield = float(base_defenses.get("shield") or 0.0)
    target_overguard = float(base_defenses.get("overguard") or 0.0)
    faction_deltas = _faction_damage_deltas(enemy_record)
    raw_ab = enemy_record.get("armourBypassDamageTypes")
    armour_bypass = set(raw_ab) if isinstance(raw_ab, (list, tuple, set, frozenset)) else DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
    raw_sb = enemy_record.get("shieldBypassDamageTypes")
    shield_bypass = set(raw_sb) if isinstance(raw_sb, (list, tuple, set, frozenset)) else DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES

    body_base_dmg = 0.0
    body_pre_effs: list[ModEffect] = []
    body_post_effs: list[ModEffect] = []
    body_dot_elems: dict[str, float] = {}
    for eff in body_weapon_effects:
        if eff.upgrade_type in {"WEAPON_DAMAGE_AMOUNT", "WEAPON_MELEE_DAMAGE"}:
            body_base_dmg += eff.value
        elif eff.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED":
            if eff.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                body_dot_elems[eff.damage_type] = body_dot_elems.get(eff.damage_type, 0.0) + eff.value
            body_pre_effs.append(eff)
        elif eff.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE":
            if eff.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
                body_dot_elems[eff.damage_type] = body_dot_elems.get(eff.damage_type, 0.0) + eff.value
            body_post_effs.append(eff)

    packed_pool = _cached_claw_packed_pool(str(claw["path"]))
    claw_base_types = {str(k): float(v) for k, v in claw["damageTypes"].items() if float(v) > 0.0}
    claw_raw_total = sum(claw_base_types.values())
    claw_cc0 = float(claw["critChance"])
    claw_cd0 = float(claw["critMultiplier"])
    claw_sc0 = float(claw["statusChance"])
    claw_as0 = float(claw["attackSpeed"])

    persistent_eff_cache = _PERSISTENT_POSTURE_EFFECTS
    elem_shape_cache: dict[tuple[Any, ...], tuple[tuple[tuple[str, float, float, bool, bool], ...], frozenset[str], float]] = {}
    f_mult_cache: dict[str, float] = {}

    def _f_mult(dt: str) -> float:
        v = f_mult_cache.get(dt)
        if v is None:
            v = max(0.0, 1.0 + float(faction_deltas.get(dt, 0.0)))
            f_mult_cache[dt] = v
        return v

    dot_inter_info = tuple(
        (
            dt,
            float(coeff),
            _f_mult("DT_CINEMATIC" if dt == "DT_SLASH" else dt),
            ("DT_CINEMATIC" if dt == "DT_SLASH" else dt) in armour_bypass,
            ("DT_CINEMATIC" if dt == "DT_SLASH" else dt) in shield_bypass,
        )
        for dt, coeff in DOT_DAMAGE_COEFFICIENTS.items()
    )

    def _unscaled_claw_rows(
        persistent_lvls: int,
        phys_conv: str | None,
        elem_conv: str | None,
        conv_post: tuple[str, float] | None,
        elem_item_paths: tuple[str, ...],
        items: tuple[dict[str, Any], ...],
    ) -> tuple[tuple[tuple[str, float, float, bool, bool], ...], frozenset[str], float]:
        cache_key = (persistent_lvls, phys_conv, elem_conv, conv_post, elem_item_paths)
        cached = elem_shape_cache.get(cache_key)
        if cached is not None:
            return cached
        pre_list: list[ModEffect] = []
        post_list: list[ModEffect] = []
        if persistent_lvls > 0:
            pre_list.append(persistent_eff_cache[persistent_lvls])
        for it in items:
            if it["pre_e"]:
                pre_list.extend(it["pre_e"])
            if it["post_e"]:
                post_list.extend(it["post_e"])
        if body_pre_effs:
            pre_list.extend(body_pre_effs)
        if body_post_effs:
            post_list.extend(body_post_effs)

        raw_bt = dict(claw_base_types)
        if phys_conv is not None:
            ps = sum(raw_bt.pop(pt, 0.0) for pt in PHYSICAL_TYPES)
            if ps > 0.0:
                raw_bt[phys_conv] = raw_bt.get(phys_conv, 0.0) + ps

        combined = _apply_elements(raw_bt, base_total=claw_raw_total, pre=pre_list, post=[])
        if elem_conv is not None:
            es = sum(combined.pop(dt, 0.0) for dt in list(combined) if dt in ALL_CONVERTIBLE_ELEMENTS)
            if es > 0.0:
                combined[elem_conv] = combined.get(elem_conv, 0.0) + es
            if conv_post is not None:
                combined[conv_post[0]] = combined.get(conv_post[0], 0.0) + claw_raw_total * conv_post[1]
        for eff in post_list:
            if eff.damage_type and eff.damage_type != "DT_ANY":
                combined[eff.damage_type] = combined.get(eff.damage_type, 0.0) + claw_raw_total * eff.value

        rows = tuple(
            (dt, float(val), _f_mult(dt), dt in armour_bypass, dt in shield_bypass)
            for dt, val in combined.items()
            if val > 0.0
        )
        res_pack = (rows, frozenset(r[0] for r in rows), sum(r[1] for r in rows))
        elem_shape_cache[cache_key] = res_pack
        return res_pack

    body_d_fire = float(body_dot_elems.get("DT_FIRE", 0.0))
    body_d_pois = float(body_dot_elems.get("DT_POISON", 0.0))
    body_d_elec = float(body_dot_elems.get("DT_ELECTRICITY", 0.0))
    body_d_gas = float(body_dot_elems.get("DT_GAS", 0.0))
    init_acc = (
        float(body_base_dmg),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        None,
        None,
        None,
        body_d_fire,
        body_d_pois,
        body_d_elec,
        body_d_gas,
        (),
    )

    def _score_claw_acc(
        acc: tuple[Any, ...],
        items: tuple[dict[str, Any], ...],
        p_mod: Mapping[str, Any],
        p_rank: int,
    ) -> tuple[float, frozenset[str]]:
        (
            b_dmg,
            cc,
            cd,
            sc,
            p_dur,
            p_dmg,
            atk,
            co,
            nc,
            hs,
            mo,
            f_imp,
            mag_str,
            phys_conv,
            elem_conv,
            conv_post,
            d_fire,
            d_pois,
            d_elec,
            d_gas,
            elem_paths,
        ) = acc

        p_lvls = p_rank + 1
        pid = p_mod["id"]
        persistent_lvls = 0
        f_punc = 0.0
        og_bonus = 0.0
        if pid == "persistent_posture":
            persistent_lvls = p_lvls
        elif pid == "frenzied_posture":
            p_dur += 0.20 * p_lvls
        elif pid == "protector_posture":
            f_punc = 1.0 * p_lvls
        elif pid == "assassin_posture":
            og_bonus = 0.75 * p_lvls

        dmg_scale = 1.0 + b_dmg if b_dmg > -1.0 else 0.0
        scaled_total = claw_raw_total * dmg_scale
        unscaled_rows, raw_pos_set, raw_unscaled_tot = _unscaled_claw_rows(
            persistent_lvls, phys_conv, elem_conv, conv_post, elem_paths, items
        )
        unscaled_tot = raw_unscaled_tot if dmg_scale > 0.0 else 0.0
        tot_dmg = unscaled_tot * dmg_scale
        pos_set = raw_pos_set if dmg_scale > 0.0 else frozenset()

        mod_cc = claw_cc0 * (1.0 + cc) + hs * primary_cc
        if mod_cc < 0.0:
            mod_cc = 0.0
        mod_cd = claw_cd0 * (1.0 + cd)
        if mod_cd < 1.0:
            mod_cd = 1.0
        mod_sc = claw_sc0 * (1.0 + sc) + mo * primary_sc
        if mod_sc < 0.0:
            mod_sc = 0.0
        a_spd = claw_as0 * (1.0 + atk)
        if a_spd < 0.0:
            a_spd = 0.0
        dur_mult = 1.0 + p_dur if p_dur > -1.0 else 0.0
        sdmg_mult = 1.0 + p_dmg if p_dmg > -1.0 else 0.0
        nc_bonus = nc if nc > 0.0 else 0.0

        inv_u = (mod_sc / unscaled_tot) if (unscaled_tot > 0.0 and mod_sc > 0.0) else 0.0
        total_procs_sec = 0.0
        unique_procs = 0
        distinct_st = 0.0
        corr_cnt = heat_cnt = viral_cnt = mag_cnt = punc_cnt = cold_cnt = 0.0
        p_slash = p_fire = p_pois = p_elec = p_gas = 0.0
        seen_punc = seen_imp = seen_mag = False
        imp_proc_val = 0.0
        mag_proc_base = 0.0

        for r_dt, r_uval, _rfm, _rab, _rsb in unscaled_rows:
            cnt = r_uval * inv_u
            if r_dt == "DT_PUNCTURE":
                seen_punc = True
                cnt += f_punc
            elif r_dt == "DT_IMPACT":
                seen_imp = True
                cnt += f_imp
                imp_proc_val = cnt
            elif r_dt == "DT_MAGNETIC":
                seen_mag = True
                mag_proc_base = cnt
                continue
            if cnt <= 0.0:
                continue
            if r_dt == "DT_SLASH":
                p_slash = cnt
            elif r_dt == "DT_FIRE":
                p_fire = cnt
            elif r_dt == "DT_POISON":
                p_pois = cnt
            elif r_dt == "DT_ELECTRICITY":
                p_elec = cnt
            elif r_dt == "DT_GAS":
                p_gas = cnt
            if a_spd > 0.0:
                r_val = cnt * a_spd
                total_procs_sec += r_val
                unique_procs += 1
                b_dur, b_cap = STATUS_PRIMING_RULES.get(r_dt, (6.0, 10.0))
                st_cnt = r_val * b_dur * dur_mult
                if st_cnt > b_cap:
                    st_cnt = b_cap
                distinct_st += 1.0 if st_cnt >= 1.0 else st_cnt
                if r_dt == "DT_CORROSIVE":
                    corr_cnt = st_cnt
                elif r_dt == "DT_FIRE":
                    heat_cnt = st_cnt
                elif r_dt == "DT_VIRAL":
                    viral_cnt = st_cnt
                elif r_dt == "DT_PUNCTURE":
                    punc_cnt = st_cnt
                elif r_dt == "DT_FREEZE":
                    cold_cnt = st_cnt

        if not seen_punc and f_punc > 0.0 and a_spd > 0.0:
            r_val = f_punc * a_spd
            total_procs_sec += r_val
            unique_procs += 1
            st_cnt = r_val * 6.0 * dur_mult
            punc_cnt = 5.0 if st_cnt > 5.0 else st_cnt
            distinct_st += 1.0 if punc_cnt >= 1.0 else punc_cnt
        if not seen_imp and f_imp > 0.0:
            imp_proc_val = f_imp
            if a_spd > 0.0:
                r_val = f_imp * a_spd
                total_procs_sec += r_val
                unique_procs += 1
                st_cnt = r_val * 1.0 * dur_mult
                distinct_st += 1.0 if st_cnt >= 1.0 else st_cnt
        tot_mag_proc = mag_proc_base + (imp_proc_val * (1.0 if mag_str > 1.0 else mag_str) if (mag_str > 0.0 and imp_proc_val > 0.0) else 0.0)
        if tot_mag_proc > 0.0 and a_spd > 0.0:
            r_val = tot_mag_proc * a_spd
            total_procs_sec += r_val
            unique_procs += 1
            st_cnt = r_val * 6.0 * dur_mult
            mag_cnt = 10.0 if st_cnt > 10.0 else st_cnt
            distinct_st += 1.0 if mag_cnt >= 1.0 else mag_cnt

        if corr_cnt <= 0.0 and heat_cnt <= 0.0:
            armour_mit = base_armour_mit
        else:
            corr_c = 10.0 if corr_cnt > 10.0 else corr_cnt
            corr_strip = (0.26 * corr_c) if corr_c < 1.0 else min(0.26 + 0.06 * (corr_c - 1.0), 1.0)
            heat_strip = 0.50 * (1.0 if heat_cnt > 1.0 else heat_cnt)
            live_armour = base_armour_after_onhit * (1.0 - corr_strip) * (1.0 - heat_strip)
            armour_mit = (1.0 - _armour_reduction(live_armour)) if live_armour > 0.0 else 1.0

        viral_mult = 1.0 if viral_cnt <= 0.0 else (1.0 + viral_cnt if viral_cnt < 1.0 else min(2.0 + 0.25 * (viral_cnt - 1.0), 4.25))
        mag_mult = 1.0 if mag_cnt <= 0.0 else (1.0 + mag_cnt if mag_cnt < 1.0 else min(2.0 + 0.25 * (mag_cnt - 1.0), 4.25))
        punc_crit = 0.05 * (5.0 if punc_cnt > 5.0 else punc_cnt)
        cold_c = 10.0 if cold_cnt > 10.0 else cold_cnt
        cold_crit = 1.0 if cold_c >= 10.0 else (0.1 * cold_c if cold_c < 1.0 else min(0.1 + 0.05 * (cold_c - 1.0), 0.5))

        eff_cc = mod_cc + punc_crit
        eff_cd = mod_cd + cold_crit
        eff_hit_mult = 1.0 + eff_cc * (eff_cd - 1.0) + (1.0 - eff_cc if eff_cc < 1.0 else 0.0) * nc_bonus
        panel_hit_mult = 1.0 + mod_cc * (mod_cd - 1.0) + (1.0 - mod_cc if mod_cc < 1.0 else 0.0) * nc_bonus
        avg_hit = tot_dmg * panel_hit_mult

        co_mult = ((dmg_scale + co * distinct_st) / dmg_scale) if (co > 0.0 and distinct_st > 0.0 and dmg_scale > 0.0) else 1.0

        direct_shot_target = 0.0
        if dmg_scale > 0.0:
            for _dt, u_val, fm, is_ab, is_sb in unscaled_rows:
                amt = u_val * dmg_scale
                if target_overguard > 0.0:
                    t_mult = mag_mult * (1.0 + og_bonus)
                elif target_shield > 0.0 and not is_sb:
                    t_mult = fm * mag_mult
                else:
                    t_mult = fm * (1.0 if is_ab else armour_mit) * viral_mult
                direct_shot_target += amt * t_mult
            direct_shot_target *= eff_hit_mult * co_mult

        dot_shot_target = 0.0
        duration_s = DOT_BASE_DURATION_SECONDS * dur_mult
        base_dot_scale = scaled_total * sdmg_mult * eff_hit_mult * duration_s
        if base_dot_scale > 0.0 and (p_slash > 0.0 or p_fire > 0.0 or p_pois > 0.0 or p_elec > 0.0 or p_gas > 0.0):
            for dt, coeff, fm, is_ab, is_sb in dot_inter_info:
                if dt == "DT_SLASH":
                    cnt = p_slash
                    el_f = 1.0
                elif dt == "DT_FIRE":
                    cnt = p_fire
                    el_f = 1.0 + d_fire if d_fire > -1.0 else 0.0
                elif dt == "DT_POISON":
                    cnt = p_pois
                    el_f = 1.0 + d_pois if d_pois > -1.0 else 0.0
                elif dt == "DT_ELECTRICITY":
                    cnt = p_elec
                    el_f = 1.0 + d_elec if d_elec > -1.0 else 0.0
                else:
                    cnt = p_gas
                    el_f = 1.0 + d_gas if d_gas > -1.0 else 0.0
                if cnt <= 0.0:
                    continue
                if target_overguard > 0.0:
                    t_mult = mag_mult
                elif target_shield > 0.0 and not is_sb:
                    t_mult = fm * mag_mult
                else:
                    t_mult = fm * (1.0 if is_ab else armour_mit) * viral_mult
                dot_shot_target += cnt * coeff * el_f * base_dot_scale * t_mult

        target_dps = (direct_shot_target + dot_shot_target) * a_spd

        if goal == "singleHit":
            sc_val = avg_hit + 0.01 * direct_shot_target
        elif goal == "statusPriming":
            sc_val = total_procs_sec * (1.0 + 0.25 * unique_procs) + 1e-4 * target_dps
        elif goal == "tenaciousBond":
            tb_tier = 1.0e12 if round(mod_cc, 8) > TENACIOUS_BOND_CRIT_THRESHOLD else min(mod_cc, TENACIOUS_BOND_CRIT_THRESHOLD) * 1.0e9
            sc_val = tb_tier + target_dps + 50.0 * total_procs_sec
        else:
            sc_val = target_dps

        if required_damage_type is not None and required_damage_type not in pos_set:
            req_parts = _COMPOUND_COMPONENT_PARTS.get(required_damage_type, (required_damage_type,))
            partial_hits = sum(1 for pt in req_parts if pt in pos_set or any(pt in it["base_elems"] for it in items))
            sc_val = sc_val * 1e-6 + partial_hits * 1e-2

        return sc_val, pos_set

    beam_width = 40
    best_valid: tuple[float, tuple[dict[str, Any], ...], Mapping[str, Any], int] | None = None

    posture_limits = [
        (p_mod, p_rank, base_cap + (abs(int(p_mod["baseDrain"])) + p_rank) * 2)
        for p_mod, p_rank in posture_candidates
    ]
    ref_p_mod, ref_p_rank, _ = posture_limits[0]
    max_cap_limit = max(lim for _, _, lim in posture_limits)

    for p_mod, p_rank, _p_lim in posture_limits:
        p_sc, p_pos = _score_claw_acc(init_acc, (), p_mod, p_rank)
        if required_damage_type is None or required_damage_type in p_pos:
            if best_valid is None or p_sc > best_valid[0]:
                best_valid = (p_sc, (), p_mod, p_rank)

    init_score, _ = _score_claw_acc(init_acc, (), ref_p_mod, ref_p_rank)
    beam: list[tuple[float, tuple[dict[str, Any], ...], int, int, tuple[str, ...], tuple[Any, ...]]] = [
        (init_score, (), 0, 0, (), init_acc)
    ]

    for _step in range(CLAW_NORMAL_SLOT_COUNT):
        nxt_map: dict[tuple[int, tuple[str, ...]], tuple[float, tuple[dict[str, Any], ...], int, int, tuple[str, ...], tuple[Any, ...], frozenset[str]]] = {}
        for _sc, cur_items, cur_mask, used_polar, cur_esig, cur_acc in beam:
            (
                a_bdmg, a_cc, a_cd, a_sc, a_pdur, a_pdmg, a_atk, a_co, a_nc,
                a_hs, a_mo, a_fimp, a_mag, a_pconv, a_econv, a_cpost,
                a_dfire, a_dpois, a_delec, a_dgas, a_epaths,
            ) = cur_acc
            for (
                c_it, c_cmask, c_pbit, c_pdrain, c_etok, c_helem, c_path,
                c_bdmg, c_cc, c_cd, c_sc, c_pdur, c_pdmg, c_atk, c_co, c_nc,
                c_hs, c_mo, c_fimp, c_mag, c_pconv, c_econv, c_cpost,
                c_dfire, c_dpois, c_delec, c_dgas,
            ) in packed_pool:
                if cur_mask & c_cmask:
                    continue
                new_polar = used_polar + c_pdrain
                if new_polar > max_cap_limit:
                    continue
                new_mask = cur_mask | c_cmask
                new_esig = cur_esig + c_etok if c_etok else cur_esig
                dedup_key = (new_mask & 0xFFFFFFFF, new_esig)
                if dedup_key in nxt_map:
                    continue
                new_items = (*cur_items, c_it)
                new_acc = (
                    a_bdmg + c_bdmg,
                    a_cc + c_cc,
                    a_cd + c_cd,
                    a_sc + c_sc,
                    a_pdur + c_pdur,
                    a_pdmg + c_pdmg,
                    a_atk + c_atk,
                    a_co + c_co,
                    a_nc + c_nc,
                    a_hs + c_hs,
                    a_mo + c_mo,
                    a_fimp + c_fimp,
                    a_mag + c_mag,
                    c_pconv if c_pconv is not None else a_pconv,
                    c_econv if c_econv is not None else a_econv,
                    c_cpost if c_cpost is not None else a_cpost,
                    a_dfire + c_dfire,
                    a_dpois + c_dpois,
                    a_delec + c_delec,
                    a_dgas + c_dgas,
                    (*a_epaths, c_path) if c_helem else a_epaths,
                )
                cand_score, cand_pos = _score_claw_acc(new_acc, new_items, ref_p_mod, ref_p_rank)
                nxt_map[dedup_key] = (
                    cand_score,
                    new_items,
                    new_mask,
                    new_polar,
                    new_esig,
                    new_acc,
                    cand_pos,
                )

        if not nxt_map:
            break

        ranked = sorted(nxt_map.values(), key=lambda row: -row[0])
        for row in ranked[:4]:
            r_items = row[1]
            r_polar = row[3]
            r_acc = row[5]
            for p_mod, p_rank, p_lim in posture_limits:
                if r_polar > p_lim:
                    continue
                if p_mod is ref_p_mod and p_rank == ref_p_rank:
                    p_sc, p_pos = row[0], row[6]
                else:
                    p_sc, p_pos = _score_claw_acc(r_acc, r_items, p_mod, p_rank)
                if required_damage_type is None or required_damage_type in p_pos:
                    if best_valid is None or p_sc > best_valid[0]:
                        best_valid = (p_sc, r_items, p_mod, p_rank)

        kept: list[tuple[float, tuple[dict[str, Any], ...], int, int, tuple[str, ...], tuple[Any, ...]]] = []
        seen_ids: set[int] = set()
        for row in ranked[:beam_width]:
            kept.append(row[:6])
            seen_ids.add(id(row))
        niche_counts: dict[tuple[str, ...], int] = {}
        niche_added = 0
        for row in ranked[beam_width:]:
            if niche_added >= 2:
                break
            sig = tuple(sorted(dt for dt in row[6] if dt not in PHYSICAL_TYPES))
            if niche_counts.get(sig, 0) < 1 and id(row) not in seen_ids:
                niche_counts[sig] = 1
                kept.append(row[:6])
                seen_ids.add(id(row))
                niche_added += 1
        beam = kept

    if best_valid is None:
        raise SimulationError(
            f"{claw['nameEn']} cannot produce required damage type {required_damage_type}"
        )

    _best_score, chosen_items, chosen_p_mod, chosen_p_rank = best_valid

    native_normal = [
        None if p in (None, "", "AP_UNIVERSAL") else str(p)
        for p in list(claw["polarities"])[:CLAW_NORMAL_SLOT_COUNT]
    ]
    while len(native_normal) < CLAW_NORMAL_SLOT_COUNT:
        native_normal.append(None)
    native_posture = (
        None
        if len(claw["polarities"]) <= CLAW_POSTURE_SLOT_INDEX
        or claw["polarities"][CLAW_POSTURE_SLOT_INDEX] in (None, "", "AP_UNIVERSAL")
        else str(claw["polarities"][CLAW_POSTURE_SLOT_INDEX])
    )

    p_pol = None if chosen_p_mod.get("polarity") in (None, "", "AP_UNIVERSAL") else str(chosen_p_mod["polarity"])
    unformed_grant, _ = _posture_slot_grant(chosen_p_mod["baseDrain"], chosen_p_rank, p_pol, native_posture)
    matched_grant, _ = _posture_slot_grant(chosen_p_mod["baseDrain"], chosen_p_rank, p_pol, p_pol)

    forma_items = [
        optimizer.FormaItem(
            origin=idx,
            polarity=None if it["polarity"] in (None, "", "AP_UNIVERSAL") else str(it["polarity"]),
            drain=int(it["raw_drain"]),
            elemental=bool(it["base_elems"]),
            fixed=False,
        )
        for idx, it in enumerate(chosen_items)
    ]
    if p_pol and matched_grant > unformed_grant:
        posture_extras = [[(0, 0, -unformed_grant), (1, 0, -matched_grant)]]
        plan = optimizer.forma_plan(native_normal, forma_items, limit=base_cap, extras=posture_extras)
        posture_formed = bool(plan["extras"] and plan["extras"][0] == 1 and p_pol)
    elif sum(1 for fi in forma_items if fi.elemental) <= 1 and len(forma_items) <= CLAW_NORMAL_SLOT_COUNT:
        # Exact minimal-Forma matching when <= 1 elemental mod (no relative ordering constraint):
        cap_goal = base_cap + unformed_grant
        rem_items = list(range(len(forma_items)))
        placement_fast: list[int | None] = [None] * CLAW_NORMAL_SLOT_COUNT
        forma_fast: list[str | None] = [None] * CLAW_NORMAL_SLOT_COUNT
        # 1) Match highest-saving items onto native polarized slots first.
        pol_slots = [j for j, sp in enumerate(native_normal) if sp is not None]
        for j in pol_slots:
            sp = native_normal[j]
            matching = [
                i for i in rem_items
                if forma_items[i].polarity == sp or sp == "AP_ANY"
            ]
            if matching:
                best_i = max(matching, key=lambda i: forma_items[i].drain - math.ceil(forma_items[i].drain / 2))
                placement_fast[j] = best_i
                rem_items.remove(best_i)
        # 2) Find exact minimum k Forma over remaining unmatched items across empty_pol + empty_unpol.
        empty_unpol = [j for j in range(CLAW_NORMAL_SLOT_COUNT) if placement_fast[j] is None and native_normal[j] is None]
        empty_pol = [j for j in range(CLAW_NORMAL_SLOT_COUNT) if placement_fast[j] is None and native_normal[j] is not None]
        matched_cost = sum(
            math.ceil(forma_items[placement_fast[j]].drain / 2) if forma_items[placement_fast[j]].polarity is not None else forma_items[placement_fast[j]].drain
            for j in range(CLAW_NORMAL_SLOT_COUNT)
            if placement_fast[j] is not None
        )
        # Sort unmatched items by Forma savings descending, tie-breaking by largest drain.
        rem_sorted = sorted(
            rem_items,
            key=lambda i: (
                -(forma_items[i].drain - math.ceil(forma_items[i].drain / 2)) if forma_items[i].polarity is not None else 0,
                -forma_items[i].drain,
            ),
        )
        solved_fast = False
        for k_forma in range(len(rem_sorted) + 1):
            forma_group = rem_sorted[:k_forma]
            unforma_group = rem_sorted[k_forma:]
            # Place Forma'd items on empty_pol first (eliminating mismatch slots), then empty_unpol.
            forma_target_slots = (empty_pol + empty_unpol)[:k_forma]
            rem_pol_slots = empty_pol[min(k_forma, len(empty_pol)) :]
            rem_unpol_slots = empty_unpol[max(0, k_forma - len(empty_pol)) :]
            # Put largest-drain un-Forma'd items on None slots, leaving only smallest drains on leftover rem_pol_slots.
            unforma_by_mismatch = sorted(
                unforma_group,
                key=lambda i: -(int(round(forma_items[i].drain * 1.25)) - forma_items[i].drain) if forma_items[i].polarity is not None else 0,
            )
            on_unpol = unforma_by_mismatch[: len(rem_unpol_slots)]
            on_mismatched_pol = unforma_by_mismatch[len(rem_unpol_slots) :]
            tot_c = (
                matched_cost
                + sum(
                    math.ceil(forma_items[i].drain / 2) if forma_items[i].polarity is not None else forma_items[i].drain
                    for i in forma_group
                )
                + sum(forma_items[i].drain for i in on_unpol)
                + sum(
                    int(round(forma_items[i].drain * 1.25)) if forma_items[i].polarity is not None else forma_items[i].drain
                    for i in on_mismatched_pol
                )
            )
            if tot_c <= cap_goal:
                for sj, ii in zip(forma_target_slots, forma_group):
                    placement_fast[sj] = ii
                    forma_fast[sj] = forma_items[ii].polarity if forma_items[ii].polarity is not None else "AP_UNIVERSAL"
                for sj, ii in zip(rem_unpol_slots, on_unpol):
                    placement_fast[sj] = ii
                for sj, ii in zip(rem_pol_slots, on_mismatched_pol):
                    placement_fast[sj] = ii
                solved_fast = True
                break
        if solved_fast:
            plan = {"placement": placement_fast, "forma": forma_fast, "extras": ()}
        else:
            plan = optimizer.forma_plan(native_normal, forma_items, limit=cap_goal)
        posture_formed = False
    else:
        plan = optimizer.forma_plan(native_normal, forma_items, limit=base_cap + unformed_grant)
        posture_formed = False
    final_normal_polarities = [
        plan["forma"][j] if plan["forma"][j] is not None else native_normal[j]
        for j in range(CLAW_NORMAL_SLOT_COUNT)
    ]
    final_posture_polarity = p_pol if posture_formed else native_posture
    final_slot_polarities = [*final_normal_polarities, final_posture_polarity]

    final_mods: list[dict[str, Any]] = []
    for slot_j, item_idx in enumerate(plan["placement"]):
        if item_idx is not None:
            it = chosen_items[item_idx]
            final_mods.append({
                "path": it["path"],
                "rank": int(it["rank"]),
                "slot": slot_j,
            })
    final_posture = {
        "path": str(chosen_p_mod["path"]),
        "rank": int(chosen_p_rank),
    }

    eval_weapon_cfg = {
        "path": str(claw["path"]),
        "reactor": weapon_reactor,
        "mods": final_mods,
        "posture": final_posture,
        "slotPolarities": final_slot_polarities,
    }
    evaluation = evaluate_companion(
        companion_cfg,
        eval_weapon_cfg,
        warframe_panel=warframe_panel,
        primary_weapon_stats=primary_weapon_stats,
        target_config=target_cfg,
        exports=exports,
    )
    return {
        "weaponPath": str(claw["path"]),
        "goal": goal,
        "mods": final_mods,
        "posture": final_posture,
        "riven": None,
        "slotPolarities": final_slot_polarities,
        "formaCount": evaluation["weapon"]["formaCount"],
        "evaluation": evaluation,
    }


def _optimize_robotic_weapon(
    companion: Mapping[str, Any],
    weapon_record: Mapping[str, Any],
    *,
    companion_cfg: Mapping[str, Any],
    weapon_cfg: Mapping[str, Any],
    weapon_reactor: bool,
    companion_player_stacks: bool,
    body_mods: Sequence[tuple[Mapping[str, Any], int, int]],
    body_weapon_effects: ModEffectList,
    warframe_panel: Mapping[str, Any] | None,
    primary_weapon_stats: Mapping[str, Any] | None,
    goal: str,
    required_damage_type: str | None,
    target_cfg: Mapping[str, Any] | None,
    exports: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from . import optimizer

    exp = exports if exports is not None else _default_exports()
    wpath = str(weapon_record["path"])

    incompat = set(companion.get("incompatibleWeapons") or ())
    ancestry_paths = {wpath, *(str(a) for a in weapon_record.get("ancestry") or () if a)}
    if ancestry_paths & incompat:
        raise SimulationError(f"{companion['nameEn']} cannot equip {weapon_record.get('nameEn') or wpath}")
    if wpath in DECONSTRUCTOR_PATHS and "deconstructor" not in (companion.get("allowedWeaponCategories") or ()):
        raise SimulationError(f"{weapon_record.get('nameEn')} can only be equipped on Helios / Helios Prime")
    if wpath in HOUND_MELEE_PATHS and companion["kind"] != "hound":
        raise SimulationError(f"{weapon_record.get('nameEn')} can only be equipped on a Hound")
    if companion["kind"] == "hound" and wpath not in HOUND_MELEE_PATHS:
        raise SimulationError(f"{companion['nameEn']} can only equip Hound melee weapons (Akaten/Batoten/Lacerten)")

    capacity_limit = REACTOR_CAPACITY if weapon_reactor else BASE_CAPACITY
    base_scenario = Scenario(
        aiming=False,
        trigger_policy="assumed_max",
        combat_state={"companion": True, "companionPlayerStacks": companion_player_stacks},
    )

    raw_riven = weapon_cfg.get("riven")
    riven_info = None
    riven_effects = ModEffectList()
    riven_card: Any = None
    riven_has_base_elem = False
    riven_lock_slot = False
    if raw_riven is not None:
        riven_info, riven_effects, _, _, _ = _parse_robotic_riven(raw_riven, set())
        riven_lock_slot = bool(raw_riven.get("lockSlot")) and isinstance(raw_riven.get("slot"), int)
        riven_has_base_elem = any(
            e.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED" and e.damage_type in BASE_ELEMENTS
            for e in riven_effects
        )
        riven_raw_drain = int(riven_info["baseDrain"]) + int(riven_info["rank"])
        riven_card = optimizer._Card(
            key="__riven__",
            record=None,
            rank=int(riven_info["rank"]),
            effects=tuple(riven_effects),
            skipped=(),
            drain=riven_raw_drain,
            polarity=riven_info["polarity"],
        )

    body_passive_card = (
        optimizer._Card(
            key="__companion_body__",
            record=None,
            rank=0,
            effects=tuple(body_weapon_effects),
            skipped=(),
            drain=0,
            polarity=None,
        )
        if body_weapon_effects
        else None
    )

    block_gladiator = wpath in DECONSTRUCTOR_PATHS or wpath in HOUND_MELEE_PATHS
    raw_candidates, _ = optimizer._candidate_mods(exp, weapon_record, base_scenario)
    candidates = [
        card
        for card in raw_candidates
        if not card.required
        and card.record is not None
        and not (block_gladiator and card.record.get("modSet") == "GladiatorSetMod")
    ]

    vicious_strip = 0.0
    for b_mod, b_rank, _ in body_mods:
        if b_mod["path"] == VICIOUS_BOND_PATH:
            vicious_strip = float(b_mod["bondSpec"]["armorStripFractionByRank"][b_rank])
    is_melee_weapon = wpath in HOUND_MELEE_PATHS or wpath in DECONSTRUCTOR_PATHS or wpath == MOA_MELEE_WEAPON_PATH
    on_hit_strip = vicious_strip if is_melee_weapon else 0.0

    enemy_record, target_level, target_sp = _resolve_target_spec(target_cfg, exports)
    target_context = {
        "target": enemy_record,
        "level": target_level,
        "armour_strip": on_hit_strip,
        "elemental_armour_strip": 0.0,
        "steel_path": target_sp,
        "enemy_enhancements": {},
        "hit_location": "body",
        "stanceMultiplier": 1.0,
        "statusRateMultiplier": 1.0,
    }

    ordered_items: list[tuple[str, Any]] = []

    if goal in {"dps", "singleHit"}:
        metric = "statusSustainedDps" if goal == "dps" else "shotDamage"
        forbidden_keys: set[str] = set()
        ev = None
        for _attempt in range(4):
            ev = optimizer.optimize_for_element(
                weapon_record,
                candidates,
                riven_card,
                scenario=base_scenario,
                metric=metric,
                passives=body_passive_card,
                slot_count=ROBOTIC_WEAPON_SLOT_COUNT,
                capacity_limit=capacity_limit,
                required_damage_type=required_damage_type,
                target_context=target_context if goal == "dps" else None,
                profile="fast",
                element_niches=2,
                forbidden_mod_keys=forbidden_keys or None,
            )
            seen_fams: dict[str, str] = {}
            dup_key: str | None = None
            for c in ev.cards:
                if c.record is not None:
                    cfam = _canonical_mod_family(c.record)
                    if cfam in seen_fams:
                        dup_key = c.key
                        break
                    seen_fams[cfam] = c.key
            if dup_key is None:
                break
            forbidden_keys.add(dup_key)

        assert ev is not None
        cards_list = list(ev.cards)
        ordered_items = [("mod", c) for c in cards_list]
        if riven_card is not None:
            r_idx = ev.riven_index if isinstance(ev.riven_index, int) and 0 <= ev.riven_index <= len(ordered_items) else len(ordered_items)
            ordered_items.insert(r_idx, ("riven", riven_card))
    else:
        # Clean, fast beam search for statusPriming and tenaciousBond!
        mode0 = (weapon_record.get("fireModes") or [{}])[0]
        mode0_dmg = mode0.get("damage") or {}
        radial_dmg = mode0_dmg.get("radial")
        radial_weapon = (
            {
                **weapon_record,
                "fireModes": [
                    {
                        **mode0,
                        "damage": {
                            "types": dict(radial_dmg["types"]),
                            "shares": dict(radial_dmg.get("shares") or {}),
                            "total": float(radial_dmg.get("total") or sum(radial_dmg["types"].values())),
                            "critChance": float(radial_dmg.get("critChance", mode0_dmg.get("critChance", 0.0))),
                            "critMultiplier": float(radial_dmg.get("critMultiplier", mode0_dmg.get("critMultiplier", 1.5))),
                            "procChance": float(radial_dmg.get("procChance", mode0_dmg.get("procChance", 0.0))),
                        },
                    }
                ],
            }
            if isinstance(radial_dmg, Mapping) and radial_dmg.get("types")
            else None
        )
        burst_count = int(mode0.get("burstCount") or 1)
        burst_delay = float(mode0.get("burstDelay") or 0.0)
        shells = _set_shells(exp.get("mods") or ())

        riven_polar_cost = (
            math.ceil(riven_card.drain / 2)
            if riven_card is not None and riven_card.polarity and riven_card.polarity not in ("", "AP_UNIVERSAL")
            else (riven_card.drain if riven_card is not None else 0)
        )
        if riven_polar_cost > capacity_limit:
            raise SimulationError("Riven drain exceeds weapon MOD capacity")
        normal_slot_budget = ROBOTIC_WEAPON_SLOT_COUNT - (1 if riven_card is not None else 0)

        cand_entries: list[dict[str, Any]] = []
        for card in candidates:
            assert card.record is not None
            pol = card.polarity
            polar_cost = math.ceil(card.drain / 2) if pol and pol not in ("", "AP_UNIVERSAL") else card.drain
            base_elems = tuple(
                e.damage_type
                for e in card.effects
                if e.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED" and e.damage_type in BASE_ELEMENTS
            )
            cand_entries.append({
                "card": card,
                "key": card.key,
                "family": _canonical_mod_family(card.record),
                "polar_cost": polar_cost,
                "base_elems": base_elems,
                "set_key": _set_key(card.record.get("modSet")),
            })

        def _score_robotic_cards(chosen_cards: tuple[Any, ...], r_pos: int | None) -> tuple[float, set[str]]:
            has_any_set = any(c.record is not None and c.record.get("modSet") for c in chosen_cards)
            if has_any_set:
                mods_only = [c.record for c in chosen_cards if c.record is not None]
                st_scen = _steady_state_scenario(mods_only, base_scenario)
                set_cnts: Counter[str] | None = Counter(_set_key(m.get("modSet")) for m in mods_only if m.get("modSet"))
            else:
                st_scen = base_scenario
                set_cnts = None

            effs = ModEffectList()
            ins = r_pos if (riven_card is not None and r_pos is not None and 0 <= r_pos <= len(chosen_cards)) else (0 if riven_card is not None else -1)
            for idx_c, obj in enumerate(chosen_cards):
                if idx_c == ins:
                    effs.extend(riven_effects)
                rec = obj.record
                sk = _set_key(rec.get("modSet")) if (set_cnts is not None and rec is not None) else None
                if sk and set_cnts is not None:
                    sh = shells.get(sk)
                    pcs, _ = _effective_set_pieces(rec, selected_count=set_cnts.get(sk, 0), shell=sh)
                    b_mult = _buff_set_multiplier(rec, pcs) if sh and sh.get("buffSet") else 1.0
                    for ef in mod_effects(rec, obj.rank, st_scen):
                        if b_mult != 1.0:
                            ef = replace(ef, value=ef.value * b_mult)
                        effs.append(ef)
                else:
                    effs.extend(obj.effects)
            if ins == len(chosen_cards):
                effs.extend(riven_effects)
            if set_cnts is not None:
                for sk, cnt in set_cnts.items():
                    sh = shells.get(sk)
                    if sh is not None and not sh.get("buffSet"):
                        effs.extend(_set_shell_effects(sh, min(cnt, int(sh.get("setPieces") or cnt)), st_scen))
            if body_weapon_effects:
                effs.extend(body_weapon_effects)

            st = _clamp_modded_stats(apply_mods(weapon_record, effs, fire_mode=0, scenario=st_scen))
            pos_dtypes = {dt for dt, amt in st.damage_types.items() if amt > 0.0}
            pps = dict(expected_status_procs(st, hit_location="body"))
            r_st = None
            if radial_weapon is not None:
                r_st = _clamp_modded_stats(apply_mods(radial_weapon, effs, fire_mode=0, scenario=st_scen))
                pos_dtypes.update(dt for dt, amt in r_st.damage_types.items() if amt > 0.0)
                for dt, cnt in expected_status_procs(r_st, hit_location="body").items():
                    pps[dt] = pps.get(dt, 0.0) + cnt

            if burst_count > 1 and st.fire_rate > 0:
                base_fr = max(float(mode0.get("fireRate") or st.fire_rate), 1e-9)
                fr_scale = max(st.fire_rate / base_fr, 1e-9)
                b_span = (burst_count - 1) * (burst_delay / fr_scale) + (1.0 / st.fire_rate)
                if st.magazine and st.magazine > 0:
                    cyc = max(float(st.magazine) / burst_count, 1.0) * b_span + float(st.reload_time or 0.0)
                    sps = float(st.magazine) / cyc if cyc > 0 else 0.0
                else:
                    sps = burst_count / b_span if b_span > 0 else 0.0
            else:
                sps = float(st.sustained_attack_rate)

            total_procs_sec = sum(v for v in pps.values() if v > 0.0) * sps
            unique_st = sum(1 for v in pps.values() if v > 0.0)

            hit_m = effective_hit_multiplier(
                st.crit_chance, st.crit_multiplier, st.noncrit_damage_multiplier, double_crit_chance=st.double_crit_chance
            )
            avg_h = st.total_damage * st.multishot * hit_m * st.falloff_multiplier
            if r_st is not None:
                rh_m = effective_hit_multiplier(
                    r_st.crit_chance, r_st.crit_multiplier, r_st.noncrit_damage_multiplier, double_crit_chance=r_st.double_crit_chance
                )
                avg_h += r_st.total_damage * r_st.multishot * rh_m * r_st.falloff_multiplier
            approx_dps = (avg_h + float(expected_status_damage(st, {}, level=1)["total"])) * sps

            if goal == "statusPriming":
                val = total_procs_sec * (1.0 + 0.25 * unique_st) + 1e-4 * approx_dps
            else:
                tb_tier = (
                    1.0e12
                    if round(st.crit_chance, 8) > TENACIOUS_BOND_CRIT_THRESHOLD
                    else min(st.crit_chance, TENACIOUS_BOND_CRIT_THRESHOLD) * 1.0e9
                )
                val = tb_tier + approx_dps + 50.0 * total_procs_sec

            if required_damage_type is not None and required_damage_type not in pos_dtypes:
                req_parts = _COMPOUND_COMPONENT_PARTS.get(required_damage_type, (required_damage_type,))
                partial = sum(1 for pt in req_parts if pt in pos_dtypes)
                val = val * 1e-6 + partial * 1e-2

            return val, pos_dtypes

        # Pre-filter top 28 relevant candidates for beam speed when pool is huge (~160 mods).
        scored_single: list[tuple[float, dict[str, Any]]] = []
        req_parts_set = set(_COMPOUND_COMPONENT_PARTS.get(required_damage_type, (required_damage_type,))) if required_damage_type else set()
        for ce in cand_entries:
            if riven_polar_cost + ce["polar_cost"] > capacity_limit:
                continue
            s1, _ = _score_robotic_cards((ce["card"],), 0 if riven_card is not None else None)
            has_req_elem = bool(req_parts_set & set(ce["base_elems"])) or any(
                e.damage_type == required_damage_type for e in ce["card"].effects
            )
            boost = 1e15 if has_req_elem else 0.0
            scored_single.append((s1 + boost, ce))
        scored_single.sort(key=lambda pair: -pair[0])
        active_pool = [pair[1] for pair in scored_single[:28]]

        beam_w = 18
        init_r_pos = 0 if riven_card is not None else None
        init_sc, init_dtypes = _score_robotic_cards((), init_r_pos)
        best_rob: tuple[float, tuple[Any, ...], int | None] | None = None
        if required_damage_type is None or required_damage_type in init_dtypes:
            best_rob = (init_sc, (), init_r_pos)

        r_beam: list[tuple[float, tuple[Any, ...], int | None, frozenset[str], frozenset[str], int]] = [
            (init_sc, (), init_r_pos, frozenset(), frozenset(), riven_polar_cost)
        ]

        for _step in range(normal_slot_budget):
            nxt_rob: dict[tuple[frozenset[str], tuple[str, ...], int | None], tuple[float, tuple[Any, ...], int | None, frozenset[str], frozenset[str], int, set[str]]] = {}
            for _sc, cur_cards, cur_rpos, u_keys, u_fams, u_polar in r_beam:
                for ce in active_pool:
                    if ce["key"] in u_keys or ce["family"] in u_fams:
                        continue
                    n_polar = u_polar + ce["polar_cost"]
                    if n_polar > capacity_limit:
                        continue
                    n_cards = (*cur_cards, ce["card"])
                    elem_sig = tuple(
                        e.damage_type
                        for c in n_cards
                        for e in c.effects
                        if e.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED" and e.damage_type in BASE_ELEMENTS
                    )
                    r_positions = (
                        (
                            [min(int(riven_info["slot"]), len(n_cards))]
                            if (riven_lock_slot and riven_info is not None)
                            else (list(range(len(n_cards) + 1)) if riven_has_base_elem else [0])
                        )
                        if riven_card is not None
                        else [None]
                    )
                    for try_rpos in r_positions:
                        dkey = (u_keys | {ce["key"]}, elem_sig, try_rpos)
                        if dkey in nxt_rob:
                            continue
                        c_sc, c_dt = _score_robotic_cards(n_cards, try_rpos)
                        nxt_rob[dkey] = (
                            c_sc,
                            n_cards,
                            try_rpos,
                            u_keys | {ce["key"]},
                            u_fams | {ce["family"]},
                            n_polar,
                            c_dt,
                        )
                        if required_damage_type is None or required_damage_type in c_dt:
                            if best_rob is None or c_sc > best_rob[0]:
                                best_rob = (c_sc, n_cards, try_rpos)

            if not nxt_rob:
                break
            ranked_rob = sorted(nxt_rob.values(), key=lambda row: -row[0])
            kept_rob: list[tuple[float, tuple[Any, ...], int | None, frozenset[str], frozenset[str], int]] = []
            seen_rob: set[int] = set()
            for row in ranked_rob[:beam_w]:
                kept_rob.append(row[:6])
                seen_rob.add(id(row))
            niche_rob: dict[tuple[str, ...], int] = {}
            niche_added_rob = 0
            for row in ranked_rob[beam_w:]:
                if niche_added_rob >= 8:
                    break
                sig = tuple(sorted(dt for dt in row[6] if dt not in PHYSICAL_TYPES))
                if niche_rob.get(sig, 0) < 2 and id(row) not in seen_rob:
                    niche_rob[sig] = niche_rob.get(sig, 0) + 1
                    kept_rob.append(row[:6])
                    seen_rob.add(id(row))
                    niche_added_rob += 1
            r_beam = kept_rob

        if best_rob is None:
            raise SimulationError(
                f"{weapon_record.get('nameEn') or wpath} cannot produce required damage type {required_damage_type}"
            )
        _, win_cards, win_rpos = best_rob
        ordered_items = [("mod", c) for c in win_cards]
        if riven_card is not None:
            ins_idx = win_rpos if win_rpos is not None and 0 <= win_rpos <= len(ordered_items) else 0
            ordered_items.insert(ins_idx, ("riven", riven_card))

    if riven_card is not None and riven_lock_slot and riven_info is not None:
        # Ensure locked Riven sits at its exact requested slot index.
        locked_idx = int(riven_info["slot"])
        non_riven = [pair for pair in ordered_items if pair[0] != "riven"]
        locked_pos = min(locked_idx, len(non_riven))
        non_riven.insert(locked_pos, ("riven", riven_card))
        ordered_items = non_riven

    native_slots = [
        None if p in (None, "", "AP_UNIVERSAL") else str(p)
        for p in list(weapon_record.get("polarities") or ())[:ROBOTIC_WEAPON_SLOT_COUNT]
    ]
    while len(native_slots) < ROBOTIC_WEAPON_SLOT_COUNT:
        native_slots.append(None)

    forma_items: list[Any] = []
    for idx, (kind_tag, card_obj) in enumerate(ordered_items[:ROBOTIC_WEAPON_SLOT_COUNT]):
        if kind_tag == "riven":
            origin_slot = int(riven_info["slot"]) if (riven_lock_slot and riven_info is not None) else idx
            forma_items.append(
                optimizer.FormaItem(
                    origin=origin_slot,
                    polarity=None if card_obj.polarity in (None, "", "AP_UNIVERSAL") else str(card_obj.polarity),
                    drain=int(card_obj.drain),
                    elemental=riven_has_base_elem,
                    fixed=riven_lock_slot,
                )
            )
        else:
            has_elem = any(
                e.upgrade_type == "WEAPON_PERCENT_BASE_DAMAGE_ADDED" and e.damage_type in BASE_ELEMENTS
                for e in card_obj.effects
            )
            forma_items.append(
                optimizer.FormaItem(
                    origin=idx,
                    polarity=None if card_obj.polarity in (None, "", "AP_UNIVERSAL") else str(card_obj.polarity),
                    drain=int(card_obj.drain),
                    elemental=has_elem,
                    fixed=False,
                )
            )

    plan = optimizer.forma_plan(native_slots, forma_items, limit=capacity_limit)
    final_slot_polarities = [
        plan["forma"][j] if plan["forma"][j] is not None else native_slots[j]
        for j in range(ROBOTIC_WEAPON_SLOT_COUNT)
    ]

    final_mods: list[dict[str, Any]] = []
    final_riven_out: dict[str, Any] | None = None
    for slot_j, item_idx in enumerate(plan["placement"]):
        if item_idx is None:
            continue
        kind_tag, card_obj = ordered_items[item_idx]
        if kind_tag == "riven" and riven_info is not None:
            final_riven_out = {
                "slot": slot_j,
                "rank": int(riven_info["rank"]),
                "baseDrain": int(riven_info["baseDrain"]),
                "polarity": riven_info["polarity"],
                "stats": list(riven_info["stats"]),
            }
        elif card_obj.record is not None:
            final_mods.append({
                "path": str(card_obj.record["path"]),
                "rank": int(card_obj.rank),
                "slot": slot_j,
            })

    eval_weapon_cfg: dict[str, Any] = {
        "path": wpath,
        "reactor": weapon_reactor,
        "companionPlayerStacks": companion_player_stacks,
        "mods": final_mods,
        "slotPolarities": final_slot_polarities,
    }
    if final_riven_out is not None:
        eval_weapon_cfg["riven"] = final_riven_out

    evaluation = evaluate_companion(
        companion_cfg,
        eval_weapon_cfg,
        warframe_panel=warframe_panel,
        primary_weapon_stats=primary_weapon_stats,
        target_config=target_cfg,
        exports=exports,
    )
    return {
        "weaponPath": wpath,
        "goal": goal,
        "mods": final_mods,
        "posture": None,
        "riven": evaluation["weapon"]["riven"],
        "slotPolarities": final_slot_polarities,
        "formaCount": evaluation["weapon"]["formaCount"],
        "evaluation": evaluation,
    }


def optimize_companion_weapon(
    payload: Mapping[str, Any],
    exports: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Automatically build the optimal MOD + minimal-Forma loadout for a Companion Weapon or Beast Claws."""
    if not isinstance(payload, Mapping):
        raise SimulationError("payload must be an object")

    raw_comp = payload.get("companion")
    if isinstance(raw_comp, Mapping):
        companion_cfg = dict(raw_comp)
    else:
        companion_cfg = {
            k: v
            for k, v in payload.items()
            if k in {"path", "id", "parts", "reactor", "gilded", "mods", "polarities", "slotPolarities", "options"}
        }
    companion = _resolve_companion(companion_cfg.get("path") or companion_cfg.get("id"))

    raw_weap = payload.get("weapon") if "weapon" in payload else payload.get("companionWeapon")
    if raw_weap is None:
        weapon_cfg: dict[str, Any] = {}
    elif isinstance(raw_weap, Mapping):
        weapon_cfg = dict(raw_weap)
    else:
        raise SimulationError("weapon must be an object or null")

    goal = str(payload.get("goal") or "dps").strip()
    if goal not in _OPTIMIZE_GOALS:
        raise SimulationError(f"goal must be one of {sorted(_OPTIMIZE_GOALS)}, got {goal!r}")

    required_damage_type = _resolve_element_target(payload.get("elementTarget", payload.get("element")))

    target_cfg: Mapping[str, Any] | None = None
    if payload.get("target") is not None:
        if not isinstance(payload.get("target"), Mapping):
            raise SimulationError("target must be an object or null")
        target_cfg = payload["target"]
    elif weapon_cfg.get("target") is not None:
        if not isinstance(weapon_cfg.get("target"), Mapping):
            raise SimulationError("weapon.target must be an object or null")
        target_cfg = weapon_cfg["target"]

    warframe_panel: Mapping[str, Any] | None = None
    if isinstance(payload.get("warframePanel"), Mapping):
        warframe_panel = payload["warframePanel"]
    elif isinstance(payload.get("warframeLink"), Mapping):
        wfl = payload["warframeLink"]
        if wfl.get("enabled") is not False and (wfl.get("config") or wfl.get("frameId") or wfl.get("id") or wfl.get("path")):
            from . import synergy as _synergy_mod

            wf_cfg = _synergy_mod._normalize_warframe_config(wfl)
            wf_res = _cached_warframe_engine().calculate(wf_cfg)
            warframe_panel = wf_res["weaponBridge"]["panel"]

    primary_stats = payload.get("primaryWeaponStats")
    if primary_stats is not None and not isinstance(primary_stats, Mapping):
        raise SimulationError("primaryWeaponStats must be an object or null")

    comp_reactor = companion_cfg.get("reactor", True)
    if not isinstance(comp_reactor, bool):
        raise SimulationError("companion.reactor must be a boolean")
    weapon_reactor = weapon_cfg.get("reactor", comp_reactor)
    if not isinstance(weapon_reactor, bool):
        raise SimulationError("weapon.reactor must be a boolean")

    companion_player_stacks = weapon_cfg.get("companionPlayerStacks", payload.get("companionPlayerStacks", False))
    if not isinstance(companion_player_stacks, bool):
        raise SimulationError("weapon.companionPlayerStacks must be a boolean")

    options = companion_cfg.get("options") or {}
    if not isinstance(options, Mapping):
        raise SimulationError("companion.options must be an object")
    body_mods = _parse_body_mods(companion, companion_cfg.get("mods"))
    body_weapon_effects = _body_to_weapon_effects(body_mods, options, [])

    hard_engage = next((item for item in body_mods if item[0]["path"] == HARD_ENGAGE_PATH), None)
    w_query = str(weapon_cfg.get("path") or companion.get("defaultWeaponPath") or "").strip()
    if companion["kind"] == "moa" and hard_engage is not None and not weapon_cfg.get("path"):
        w_query = MOA_MELEE_WEAPON_PATH
    if not w_query:
        raise SimulationError("weapon.path must be a non-empty string")

    claws_idx = _indices()["claws"]
    claw_match = claws_idx.get(w_query) or claws_idx.get(w_query.casefold())
    if claw_match is not None:
        return _optimize_beast_claws(
            companion,
            claw_match,
            companion_cfg=companion_cfg,
            weapon_cfg=weapon_cfg,
            weapon_reactor=weapon_reactor,
            body_mods=body_mods,
            body_weapon_effects=body_weapon_effects,
            warframe_panel=warframe_panel,
            primary_weapon_stats=primary_stats,
            goal=goal,
            required_damage_type=required_damage_type,
            target_cfg=target_cfg,
            exports=exports,
        )

    if companion["category"] == "beast":
        raise SimulationError(f"{companion['nameEn']} can only equip its breed Beast Claws")

    exp = exports if exports is not None else _default_exports()
    if w_query.casefold() in MOA_MELEE_WEAPON_ALIASES:
        if companion["kind"] != "moa" or hard_engage is None:
            raise SimulationError("MoaPetMeleeWeapon requires a MOA companion with Hard Engage equipped")
        weapon_record: Mapping[str, Any] = _moa_melee_weapon_record(hard_engage[1])
    else:
        weapon_record = resolve_record(exp.get("weapons") or (), w_query, kind="weapon")
        if weapon_record.get("slot") != "companion":
            raise SimulationError(f"{weapon_record.get('nameEn') or w_query} is not a robotic companion weapon")

    return _optimize_robotic_weapon(
        companion,
        weapon_record,
        companion_cfg=companion_cfg,
        weapon_cfg=weapon_cfg,
        weapon_reactor=weapon_reactor,
        companion_player_stacks=companion_player_stacks,
        body_mods=body_mods,
        body_weapon_effects=body_weapon_effects,
        warframe_panel=warframe_panel,
        primary_weapon_stats=primary_stats,
        goal=goal,
        required_damage_type=required_damage_type,
        target_cfg=target_cfg,
        exports=exports,
    )


__all__ = [
    "catalog",
    "get_companion_catalog",
    "evaluate_companion",
    "optimize_companion_weapon",
    "player_weapon_mod_effects",
    "companion_weapon_mod_effects",
]
