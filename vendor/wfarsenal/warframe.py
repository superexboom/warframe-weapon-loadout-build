"""Small, deterministic Warframe build evaluator.

This module deliberately does not share the weapon damage kernel.  Warframes
need slot/capacity validation and panel/ability scaling, but have no target or
kill simulation in the portable app.  The generated sidecar is the source of
truth; the optional export fallback is only useful for catalog discovery when
the sidecar has not been generated yet.
"""

from __future__ import annotations

from collections import Counter
import copy
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .mod_families import (
    authoritative_mod_family,
    canonical_mod_family,
    equipment_additional_bases,
    is_unreleased_warframe_mod,
)
from .simulator import SimulationError


DEFAULT_CAPACITY = 60
NORMAL_SLOT_COUNT = 8
ARCANE_SLOT_COUNT = 2
SHARD_SLOT_COUNT = 5
ABILITY_SLOT_COUNT = 4

PRIMARY_WEAPON_TYPE = "/Lotus/Weapons/Tenno/LotusLongGun"
RIFLE_WEAPON_TYPE = "/Lotus/Weapons/Tenno/Rifle/LotusRifle"
SHOTGUN_WEAPON_TYPE = "/Lotus/Weapons/Tenno/Shotgun/LotusShotgun"
SNIPER_WEAPON_TYPE = "/Lotus/Weapons/Tenno/Rifle/LotusSniperRifle"
SECONDARY_WEAPON_TYPE = "/Lotus/Weapons/Tenno/Pistol/LotusPistol"
MELEE_WEAPON_TYPE = "/Lotus/Types/Game/LotusMeleeWeapon"
GUN_WEAPON_TYPES = [PRIMARY_WEAPON_TYPE, SECONDARY_WEAPON_TYPE]

CATALYZING_SHIELDS_PATH = "/Lotus/Upgrades/Mods/Warframe/DualStat/FixedShieldAndShieldGatingDuration"
BRIEF_RESPITE_PATH = "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestAbilityToShieldsAuraMod"
COMBAT_DISCIPLINE_PATH = "/Lotus/Upgrades/Mods/Aura/WarframeAuraBloodLetterMod"
COACTION_DRIFT_PATH = "/Lotus/Upgrades/Mods/OrokinChallenge/OrokinChallengeModCollaboration"
PRECISION_INTENSIFY_PATH = "/Lotus/Upgrades/Mods/Warframe/AvatarAbilityFourStrengthMod"
ADAPTATION_PATHS = frozenset({
    "/Lotus/Upgrades/Mods/Nemesis/AvatarSentientArmourMod",
    "/Lotus/Upgrades/Mods/Warframe/AvatarResistanceOnDamageMod",
})
ROLLING_GUARD_PATH = "/Lotus/Upgrades/Mods/Warframe/AvatarInvulnOnRollMod"
VIGOROUS_SWAP_PATH = "/Lotus/Upgrades/Mods/Warframe/AvatarHolsterDamageMod"
HOLSTER_AMP_PATH = "/Lotus/Upgrades/Mods/Aura/PlayerHolsterSpeedAuraMod"
SWIFT_MOMENTUM_PATH = "/Lotus/Upgrades/Mods/Aura/WarframeAuraWickedStrikesMod"
EMPOWERED_BLADES_PATH = "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestShieldsToCritAuraMod"
MECHA_EMPOWERED_PATH = "/Lotus/Upgrades/Mods/Sets/Mecha/WarframeAuraMechaEmpowerMod"
TEK_COLLATERAL_PATH = "/Lotus/Upgrades/Mods/Sets/Tek/WarframeTekCollateralMod"

ARCANE_PERSISTENCE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/MaxDPSTakenForArmour"
ARCANE_BELLICOSE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/AbilityStrengthForMaxHealth"
ARCANE_BATTERY_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/MaxEnergyForArmor"
ARCANE_EXPERTISE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/ShieldMaxForAbilityStrength"
MOLT_EFFICIENCY_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Zariman/WarframeOnShieldUptimePowerDuration"
ARCANE_CREPUSCULAR_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Utility/AbilityStrengthAndCritDamageWhenInvisible"
ARCANE_CAMISADO_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/AbilityStrengthOnSummonAttack"
ARCANE_IMPETUS_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Utility/AbilityStatusProcsGiveAbilityStrengthAndEfficiency"
ARCANE_ICE_STORM_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/AbilityPowerOnFreeze"
ARCANE_INTENTION_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Utility/HealthWhileUsingChanneledAbilities"

STATUS_RESIST_INVIG_PATH = "/Lotus/Upgrades/Invigorations/Utility/UtilityInvigorationStatusResistance"

CATALYZING_SHIELD_MULTIPLIERS = (0.80, 0.60, 0.40, 0.20)
CATALYZING_SHIELD_GATE_SECONDS = (0.33, 0.67, 1.00, 1.33)
COMBAT_DISCIPLINE_SELF_DAMAGE = (1.0, 2.0, 4.0, 6.0, 8.0, 10.0)
ARCANE_INTENTION_HP_PER_CHANNEL = (40.0, 80.0, 120.0, 160.0, 200.0, 250.0)

_AURA_UPGRADE_TYPES: dict[str, tuple[str, str]] = {
    "rifle-amp": ("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY"),
    "pistol-amp": ("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY"),
    "shotgun-amp": ("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY"),
    "dead-eye": ("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY"),
    "steel-charge": ("WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY"),
    "worthy-comradery": ("WEAPON_CRIT_CHANCE_WEAKPOINT", "STACKING_MULTIPLY"),
    "ready-steel": ("WEAPON_MELEE_COMBO_INITIAL_BONUS", "ADD"),
    "corrosive-projection": ("ENEMY_ARMOR_REDUCTION", "ADD"),
    "shield-disruption": ("ENEMY_SHIELD_REDUCTION", "ADD"),
}


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
    "AVATAR_HEAL_RATE": "healthRegen",
    "AVATAR_CASTING_SPEED": "castingSpeed",
    "AVATAR_PARKOUR_BOOST": "parkour",
    "AVATAR_PARKOUR_VELOCITY": "parkour",
}

_BASE_STATS = frozenset({"health", "shield", "armor", "energy", "sprint"})
_ABILITY_STATS = frozenset(
    {"abilityStrength", "abilityDuration", "abilityRange", "abilityEfficiency"}
)


def _runtime_mechanics_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base / "data" / "mechanics"


def _mechanics_path(name: str, catalog_path: Path | None = None, *, expected_build: Any = None) -> Path:
    """Resolve an engine-owned mechanics sidecar across live, snapshot, and frozen layouts."""
    primary = _runtime_mechanics_dir() / name
    fallback = (catalog_path.parent / "mechanics" / name) if catalog_path is not None else None
    if fallback is not None and fallback.is_file() and fallback != primary:
        if not primary.is_file():
            return fallback
        if expected_build is not None:
            try:
                fb_label = json.loads(fallback.read_text(encoding="utf-8-sig")).get("buildLabel")
                pr_label = json.loads(primary.read_text(encoding="utf-8-sig")).get("buildLabel")
                if fb_label == expected_build and pr_label != expected_build:
                    return fallback
            except (OSError, UnicodeError, ValueError):
                pass
    return primary if primary.is_file() or fallback is None else fallback


def _load_synergy_sidecar(catalog_path: Path | None = None) -> dict[str, Any]:
    path = _mechanics_path("warframe-synergy.json", catalog_path)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _apply_catalog_repairs(catalog: dict[str, Any], synergy: Mapping[str, Any]) -> None:
    """Apply in-memory display and metadata repairs without mutating frozen disk files."""
    repairs = synergy.get("catalogRepairs")
    if not isinstance(repairs, Mapping):
        return

    shard_repairs = repairs.get("shards") if isinstance(repairs.get("shards"), Mapping) else {}
    if shard_repairs and isinstance(catalog.get("shards"), list):
        repaired_shards: list[Any] = []
        for row in catalog["shards"]:
            if not isinstance(row, Mapping):
                repaired_shards.append(row)
                continue
            patch = shard_repairs.get(str(row.get("path") or ""))
            if isinstance(patch, Mapping):
                updated = copy.deepcopy(dict(row))
                updated.update(copy.deepcopy(dict(patch)))
                repaired_shards.append(updated)
            else:
                repaired_shards.append(row)
        catalog["shards"] = repaired_shards

    invig_repairs = repairs.get("invigoration") if isinstance(repairs.get("invigoration"), Mapping) else {}
    if invig_repairs and isinstance(catalog.get("invigoration"), list):
        repaired_invig: list[Any] = []
        for row in catalog["invigoration"]:
            if not isinstance(row, Mapping):
                repaired_invig.append(row)
                continue
            patch = invig_repairs.get(str(row.get("path") or ""))
            if isinstance(patch, Mapping):
                updated = copy.deepcopy(dict(row))
                updated.update(copy.deepcopy(dict(patch)))
                repaired_invig.append(updated)
            else:
                repaired_invig.append(row)
        catalog["invigoration"] = repaired_invig

    helminth_names = repairs.get("helminthDisplayNamesEn") if isinstance(repairs.get("helminthDisplayNamesEn"), Mapping) else {}
    if helminth_names and isinstance(catalog.get("helminth"), list):
        repaired_helminth: list[Any] = []
        for row in catalog["helminth"]:
            if not isinstance(row, Mapping):
                repaired_helminth.append(row)
                continue
            display_en = helminth_names.get(str(row.get("path") or ""))
            if isinstance(display_en, str) and display_en:
                updated = dict(row)
                updated.setdefault("nameInternal", row.get("nameEn"))
                updated["nameEn"] = display_en
                repaired_helminth.append(updated)
            else:
                repaired_helminth.append(row)
        catalog["helminth"] = repaired_helminth

    per_rank_mods = set(repairs.get("perRankValueMods") or ())
    if per_rank_mods and isinstance(catalog.get("mods"), list):
        repaired_mods: list[Any] = []
        for row in catalog["mods"]:
            if not isinstance(row, Mapping) or str(row.get("path") or "") not in per_rank_mods:
                repaired_mods.append(row)
                continue
            updated = copy.deepcopy(dict(row))
            if int(updated.get("maxRank") or 0) > 0 and isinstance(updated.get("effects"), list):
                for fx in updated["effects"]:
                    if (
                        isinstance(fx, dict)
                        and fx.get("valuePerRank") is None
                        and _number(fx.get("value")) is not None
                        and str(fx.get("upgradeType") or "") not in {"", "NONE", "AVATAR_ABILITY_AUGMENT"}
                    ):
                        fx["valuePerRank"] = fx["value"]
            repaired_mods.append(updated)
        catalog["mods"] = repaired_mods


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
    if value in {"OMNI", "AP_OMNI"}:
        return "AP_ANY"
    return value


def _warframe_slot_drain(raw_drain: int, mod_polarity: Any, slot_polarity: Any) -> tuple[int, str]:
    """Compute Warframe slot drain/aura grant including Omni (AP_ANY) and mismatched aura floor(0.8x)."""
    mod_pol = _polarity(mod_polarity)
    slot_pol = _polarity(slot_polarity)
    if raw_drain < 0:
        grant = abs(int(raw_drain))
        if slot_pol is None or mod_pol is None:
            return -grant, "unpolarized"
        if (
            slot_pol == mod_pol
            or (slot_pol == "AP_ANY" and mod_pol != "AP_UMBRA")
            or (mod_pol == "AP_ANY" and slot_pol != "AP_UMBRA")
        ):
            return -(grant * 2), "matched"
        return -int(math.floor(grant * 0.8)), "mismatched"
    drain = int(raw_drain)
    if slot_pol is None or mod_pol is None:
        return drain, "unpolarized"
    if (
        slot_pol == mod_pol
        or (slot_pol == "AP_ANY" and mod_pol != "AP_UMBRA")
        or (mod_pol == "AP_ANY" and slot_pol != "AP_UMBRA")
    ):
        return int(math.ceil(drain * 0.5)), "matched"
    return int(math.ceil(drain * 1.25)), "mismatched"


def _empty_catalog(status: str, error: str | None = None) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "buildLabel": None,
        "status": status,
        "provenance": {},
        "counts": {"warframes": 0, "warframeForms": 0, "mods": 0, "arcanes": 0, "helminth": 0, "invigoration": 0, "shards": 0},
        "warframes": [],
        "warframeForms": [],
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
            "warframeForms": [],
            "mods": mods,
            "arcanes": arcanes,
            "abilities": [ability for frame in frames for ability in frame.get("abilities") or ()],
            "counts": {"warframes": len(frames), "mods": len(mods), "arcanes": len(arcanes), "helminth": 0, "invigoration": 0, "shards": 0},
            "gaps": ["generated sidecar is missing", "warframe slot polarities are unavailable in the flat export"],
        }
    )
    return result


def load_alternate_forms(catalog: Mapping[str, Any], path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Load independently moddable suits attached to an ordinary Warframe.

    These rows intentionally live outside ``warframes``: a Shadow is a second
    loadout target, not another standalone frame in the picker.  The additive
    mechanics sidecar keeps older frozen catalogs usable and is bundled by the
    same data pipeline as the other runtime rules.
    """
    if not path.is_file():
        return [], []
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [], [f"无法读取战甲第二形态数据：{exc}"]
    if not isinstance(payload, Mapping) or payload.get("schemaVersion") != 1:
        return [], ["战甲第二形态数据的 schemaVersion 不受支持"]
    if payload.get("buildLabel") != catalog.get("buildLabel"):
        return [], [f"战甲第二形态数据版本不匹配：{payload.get('buildLabel')!r} != {catalog.get('buildLabel')!r}"]
    parents = {_row_id(row) for row in catalog.get("warframes") or () if isinstance(row, Mapping)}
    forms: list[dict[str, Any]] = []
    seen: set[str] = set()
    errors: list[str] = []
    for source in payload.get("forms") or ():
        if not isinstance(source, Mapping):
            errors.append("战甲第二形态含非对象记录，已跳过")
            continue
        form_id = _row_id(source)
        parent_id = str(source.get("parentFrameId") or "")
        abilities = source.get("abilities")
        slots = source.get("slotPolarities")
        if not form_id or form_id in seen or parent_id not in parents:
            errors.append(f"战甲第二形态 {form_id or '<missing>'} 的 ID 重复或本体不存在，已跳过")
            continue
        if not isinstance(abilities, list) or len(abilities) != ABILITY_SLOT_COUNT:
            errors.append(f"战甲第二形态 {form_id} 缺少四技能，已跳过")
            continue
        if not isinstance(slots, Mapping) or not isinstance(slots.get("normal"), list) or len(slots["normal"]) != NORMAL_SLOT_COUNT:
            errors.append(f"战甲第二形态 {form_id} 的极性不完整，已跳过")
            continue
        if not isinstance(source.get("rank30Panel"), Mapping) or not isinstance(source.get("basePanel"), Mapping):
            errors.append(f"战甲第二形态 {form_id} 缺少面板，已跳过")
            continue
        seen.add(form_id)
        forms.append(dict(source))
    return forms, errors


def _enrich_warframe_mods(
    rows: Iterable[Any],
    overrides: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    ovr = overrides or {}
    for source in rows:
        if not isinstance(source, Mapping):
            continue
        row = dict(source)
        path = str(row.get("path") or _row_id(row))
        fam = ovr.get(path) or authoritative_mod_family(path, row.get("modFamily"))
        if fam:
            row["modFamily"] = fam
        if is_unreleased_warframe_mod(path):
            row["hiddenFromPicker"] = True
        enriched.append(row)
    return enriched


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
    result.setdefault("warframeForms", [])
    result.setdefault("modSets", {})
    result.setdefault("gaps", [])
    forms_path = _mechanics_path("warframe-forms.json", path, expected_build=result.get("buildLabel"))
    forms, form_gaps = load_alternate_forms(result, forms_path)
    result["warframeForms"] = forms
    result["gaps"] = [*result["gaps"], *form_gaps]
    result["helminth"] = apply_helminth_altered(
        result["helminth"],
        _mechanics_path("helminth-altered.json", path),
    )
    synergy = _load_synergy_sidecar(path)
    if synergy:
        _apply_catalog_repairs(result, synergy)
    ovr = {
        str(k): str(v)
        for k, v in ((synergy or {}).get("modFamilyOverrides") or {}).items()
        if isinstance(k, str) and isinstance(v, str)
    }
    result["mods"] = _enrich_warframe_mods(result.get("mods") or (), ovr)
    result["equipmentAdditionalBases"] = equipment_additional_bases()
    result["_synergy"] = synergy
    result["counts"] = {
        key: len(result.get(key) or ())
        for key in ("warframes", "warframeForms", "mods", "arcanes", "helminth", "invigoration", "shards")
    }
    return result


def _altered_scalar(scalar: Mapping[str, Any], spec: Any) -> dict[str, Any]:
    row = dict(scalar)
    spec = {"values": spec} if isinstance(spec, (list, tuple, int, float)) else dict(spec)
    values = spec.get("values")
    if isinstance(values, (int, float)):
        values = [values] * max(1, len(row.get("rankValues") or ()) or 1)
    if isinstance(values, (list, tuple)) and values:
        row["rankValues"] = list(values)
        row["values"] = [values[-1]]
        row["base"] = values[-1]
        parts = dict(row.get("parts") or {})
        if len(parts) <= 1 or spec.get("valueTemplate"):
            parts = {"val1": values[-1]}
        row["parts"] = parts
    if isinstance(spec.get("parts"), Mapping):
        row["parts"] = dict(spec["parts"])
    if spec.get("valueTemplate"):
        row["valueTemplate"] = spec["valueTemplate"]
        row["valueKeys"] = list(row["parts"])
    row["sourceKind"] = "wiki-helminth"
    return row


def apply_helminth_altered(rows: Sequence[Any], path: Path) -> list[Any]:
    """Subsumed abilities whose Helminth version has different numbers.

    The sidecar copies the original ability's scalars; the wiki's Helminth tab
    gives the altered ones (data/mechanics/helminth-altered.json). They go to
    ``altered.scalars``, which the engine swaps in when the ability is placed.
    """
    try:
        table = json.loads(path.read_text(encoding="utf-8")).get("abilities") or {}
    except (OSError, ValueError):
        return list(rows)
    out = []
    for row in rows:
        spec = table.get(str((row or {}).get("path") or "")) if isinstance(row, Mapping) else None
        if not spec:
            out.append(row)
            continue
        row = dict(row)
        overrides = spec.get("scalars") or {}
        altered = dict(row.get("altered") or {})
        if overrides:
            altered["scalars"] = [
                _altered_scalar(scalar, overrides[scalar.get("id")]) if scalar.get("id") in overrides else dict(scalar)
                for scalar in row.get("scalars") or () if isinstance(scalar, Mapping)
            ]
            row["scalarSource"] = "wiki-altered"
        if spec.get("notes"):
            altered["notes"] = spec["notes"]
        row["altered"] = altered
        out.append(row)
    return out


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
    if len(matches) > 1:
        visible = [row for row in matches if not row.get("hiddenFromPicker")]
        if len(visible) == 1:
            return visible[0]
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


def _rank_pick(values: Any, rank: int) -> float | None:
    if isinstance(values, (list, tuple)):
        return _number(values[min(rank, len(values) - 1)]) if values else None
    return _number(values)


def _script_effect(effect: Mapping[str, Any], rank: int) -> tuple[str, float, str] | None:
    """Panel effect a card's Lua script applies (its numbers sit in localizationScript).

    AddTimedUpgrade (Archon Intensify +30% Strength, Archon Stretch +2 Energy/s),
    AuraSquadPower (Power Donation: the carrier loses Strength),
    UpgradeStackOnAbilityCast (Arcane Power Ramp, full stacks),
    StrengthForOneCast (Molt Vigor).
    """
    script = effect.get("localizationScript")
    if not isinstance(script, Mapping):
        return None
    name = str(script.get("Script") or "").rsplit("/", 1)[-1]
    if name == "AddTimedUpgrade.lua":
        stat = _STAT_ALIASES.get(str(script.get("_upgradeType") or "").upper())
        amount = _number(script.get("_upgradeAmount"))
        if stat is None or amount is None:
            return None
        operation = str(script.get("_upgradeOperationType") or "ADD")
        if "MULTIPLY" in operation and script.get("_upgradeIsPercent"):
            amount /= 100.0
        return stat, amount, operation
    if name == "AuraSquadPower.lua":
        amount = _rank_pick(script.get("_selfReduceAmount"), rank)
        return ("abilityStrength", -amount, "STACKING_MULTIPLY") if amount else None
    if name == "UpgradeStackOnAbilityCast.lua":
        amount = _rank_pick(script.get("_bonuses"), rank)
        stacks = _number(script.get("_maxStacks")) or 1.0
        return ("abilityStrength", amount * stacks, "STACKING_MULTIPLY") if amount else None
    if name == "StrengthForOneCast.lua":
        base = _number(script.get("_baseStrength"))
        per = _number(script.get("_strengthIncreasePerLevel")) or 0.0
        return ("abilityStrength", (base + per * rank) / 100.0, "STACKING_MULTIPLY") if base is not None else None
    return None


# Script effects that apply without a trigger (Power Donation's own Strength cost).
_UNCONDITIONAL_SCRIPTS = frozenset({"AuraSquadPower.lua"})


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
            continue
        script = effect.get("localizationScript")
        scripted = _script_effect(effect, rank) if isinstance(script, Mapping) and str(script.get("Script") or "").rsplit("/", 1)[-1] in _UNCONDITIONAL_SCRIPTS else None
        if scripted:
            yield {"stat": scripted[0], "value": scripted[1] * set_multiplier, "operation": scripted[2], "source": source, "label": scripted[0]}
    if not conditionals:
        return
    condition_rows = card.get("conditionalEffects")
    if isinstance(condition_rows, Mapping):
        condition_rows = [condition_rows]
    seen: set[str] = set()
    for conditional in condition_rows or ():
        if not isinstance(conditional, Mapping):
            continue
        # The export repeats some sub-upgrades verbatim (Archon Intensify and
        # Archon Stretch list theirs twice); the game applies each once.
        key = json.dumps(conditional, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
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
            operation = effect.get("operation") or effect.get("mode") or "ADD"
            if stat is None or value is None or (value == 0 and effect.get("localizationScript")):
                scripted = _script_effect(effect, rank)
                if scripted is None:
                    continue
                stat, value, operation = scripted
            yield {"stat": stat, "value": value * stacks * set_multiplier, "operation": operation, "source": source, "label": effect.get("label") or effect.get("upgradeType") or stat, "conditional": True, "condition": conditional.get("conditionTag") or conditional.get("condition")}


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


def _fmt_pct(value: float) -> str:
    pct = round(value * 100.0, 2)
    return f"{int(pct)}" if float(pct).is_integer() else f"{pct:g}"


class WarframeEngine:
    """Validate and calculate one fixed-rank-30 Warframe build."""

    def __init__(self, catalog: Mapping[str, Any]):
        self.catalog = dict(catalog)
        synergy = self.catalog.get("_synergy")
        if not isinstance(synergy, Mapping) or not synergy:
            synergy = _load_synergy_sidecar()
        self.synergy: dict[str, Any] = dict(synergy)
        self.forms = [row for row in self.catalog.get("warframeForms") or () if isinstance(row, Mapping)]
        self.frames = [
            *[row for row in self.catalog.get("warframes") or () if isinstance(row, Mapping)],
            *self.forms,
        ]
        self.mods = [row for row in self.catalog.get("mods") or () if isinstance(row, Mapping)]
        self.arcanes = [row for row in self.catalog.get("arcanes") or () if isinstance(row, Mapping)]
        self.helminth = [row for row in self.catalog.get("helminth") or () if isinstance(row, Mapping)]
        self.invigoration = [row for row in self.catalog.get("invigoration") or () if isinstance(row, Mapping)]
        self.shards = [row for row in self.catalog.get("shards") or () if isinstance(row, Mapping)]

        repairs = self.synergy.get("catalogRepairs") if isinstance(self.synergy.get("catalogRepairs"), Mapping) else {}
        self.non_self_aura_paths = {_path_token(p) for p in (repairs.get("nonSelfAuraPaths") or ())}
        self.mod_family_overrides: dict[str, str] = {
            str(k): str(v)
            for k, v in (self.synergy.get("modFamilyOverrides") or {}).items()
            if isinstance(k, str) and isinstance(v, str)
        }
        self.mods = _enrich_warframe_mods(self.mods, self.mod_family_overrides)
        self.catalog["mods"] = self.mods
        self.catalog.setdefault("equipmentAdditionalBases", equipment_additional_bases())
        self.augment_ability_map: dict[str, str] = {
            str(k): str(v)
            for k, v in (self.synergy.get("augmentAbilityMap") or {}).items()
            if isinstance(k, str) and isinstance(v, str)
        }
        hrules = self.synergy.get("helminthRules") if isinstance(self.synergy.get("helminthRules"), Mapping) else {}
        self.damage_buff_ability_paths = {_path_token(p) for p in (hrules.get("damageBuffAbilityPaths") or ())}
        self.damage_buff_frame_slot_ability: dict[str, str] = {
            _path_token(k): _path_token(v)
            for k, v in (hrules.get("damageBuffFrameSlotAbility") or {}).items()
            if isinstance(k, str) and isinstance(v, str)
        }

    def _resolve_frame(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        query = payload.get("frameId") or payload.get("frame") or payload.get("warframe")
        if not self.frames:
            raise SimulationError("warframe catalog is unavailable; generate data/warframe_build_data.json first")
        return _resolve(self.frames, query, "frameId")

    def form_record(self, frame_id: Any) -> Mapping[str, Any] | None:
        """Return an alternate-form row for a frame/form id, if it has one."""
        wanted = _token(frame_id)
        return next((row for row in self.forms if _token(_row_id(row)) == wanted), None)

    def _mod_family(self, row: Mapping[str, Any], frame_path: str | None = None) -> str | None:
        path = str(row.get("path") or _row_id(row))
        fallback = self.mod_family_overrides.get(path) or row.get("modFamily")
        fam = canonical_mod_family(path, fallback, equip_path=frame_path)
        return fam or None

    def _mod_compatible(self, row: Mapping[str, Any], frame: Mapping[str, Any], active_ability_paths: set[str]) -> bool:
        path = str(row.get("path") or _row_id(row))
        aug_target = self.augment_ability_map.get(path)
        if aug_target and aug_target != "PASSIVE":
            return _path_token(aug_target) in active_ability_paths
        return _frame_compatible(row, frame)

    def _resolve_mod(
        self,
        value: Any,
        kind: str,
        frame: Mapping[str, Any],
        active_ability_paths: set[str],
    ) -> tuple[Mapping[str, Any], int, int, str]:
        choice = _choice(value, kind)
        if choice is None:
            raise SimulationError(f"{kind} cannot be null here")
        row = _resolve(self.mods, choice.get("path") or choice.get("id") or choice.get("query"), kind)
        slot_kind = str(row.get("slotKind") or row.get("kind") or row.get("compatibility") or "").casefold()
        aliases = {"normal": {"normal", "warframe", "exilus"}, "aura": {"aura"}, "exilus": {"exilus"}}
        if slot_kind not in aliases.get(kind, {kind}):
            raise SimulationError(f"{kind} requires a {kind} MOD")
        if not self._mod_compatible(row, frame, active_ability_paths):
            raise SimulationError(f"{kind} is not compatible with the selected Warframe")
        rank = _rank(row, choice.get("rank"), kind)
        raw, _base = _card_drain(row, rank, slot_kind=slot_kind)
        return row, rank, raw, slot_kind

    def _resolve_helminth(
        self,
        frame: Mapping[str, Any],
        replacement: Any,
        inheritance: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], int | None]:
        native_abilities = [dict(ability) for ability in frame.get("abilities") or () if isinstance(ability, Mapping)]
        if len(native_abilities) > ABILITY_SLOT_COUNT:
            native_abilities = native_abilities[:ABILITY_SLOT_COUNT]
        abilities = [dict(ability) for ability in native_abilities]
        if replacement is None:
            return abilities, None
        if inheritance.get("helminth") is False:
            raise SimulationError("该第二形态使用固定技能组，不能进行 Helminth 替换")
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

        infused_path = _path_token(ability.get("path") or ability.get("id"))
        native_paths = {_path_token(row.get("path") or row.get("id")) for row in native_abilities}
        if infused_path and infused_path in native_paths:
            raise SimulationError("cannot infuse a duplicate ability that the Warframe already possesses")

        if infused_path in self.damage_buff_ability_paths:
            frame_path = _path_token(frame.get("path") or frame.get("id"))
            frame_family = frame_path.rsplit("/", 1)[0] if "/" in frame_path else ""
            required_native = self.damage_buff_frame_slot_ability.get(frame_family)
            if required_native:
                replaced_native = _path_token((native_abilities[slot] if slot < len(native_abilities) else {}).get("path"))
                if replaced_native != required_native:
                    raise SimulationError(
                        "Helminth damage-buff abilities can only replace this Warframe's own damage-buff ability slot"
                    )

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
        return abilities, slot

    def calculate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise SimulationError("warframe request must be a JSON object")
        if self.catalog.get("status") not in {None, "ready"}:
            raise SimulationError("warframe catalog is unavailable; generate the sidecar before calculating")
        if not isinstance(payload.get("applyConditionals", False), bool):
            raise SimulationError("applyConditionals must be a boolean")
        conditionals = bool(payload.get("applyConditionals", False))

        frame = self._resolve_frame(payload)
        frame_path = str(frame.get("path") or _row_id(frame))
        inheritance = frame.get("inheritance") if isinstance(frame.get("inheritance"), Mapping) else {}
        abilities, helminth_slot = self._resolve_helminth(frame, payload.get("helminthReplacement"), inheritance)
        active_ability_paths = {_path_token(row.get("path") or row.get("id")) for row in abilities if isinstance(row, Mapping)}

        aura_pol, exilus_pol, normal_pols = _slot_polarities(frame, payload.get("slotPolarities"))
        selected: list[tuple[Mapping[str, Any], int, int, int | None, str]] = []
        seen: set[str] = set()
        seen_families: dict[str, str] = {}

        def register_mod(row: Mapping[str, Any]) -> str:
            path = _row_id(row)
            if path in seen:
                raise SimulationError("the same MOD cannot occupy more than one Warframe slot")
            fam = self._mod_family(row, frame_path=frame_path)
            if fam is not None:
                fam_key = fam.casefold()
                if fam_key in seen_families:
                    raise SimulationError(
                        f"conflicting modFamily: {path} cannot be equipped together with {seen_families[fam_key]}"
                    )
                seen_families[fam_key] = path
            seen.add(path)
            return path

        aura_row = aura_rank = aura_raw = None
        if payload.get("aura") is not None:
            aura_row, aura_rank, aura_raw, _ = self._resolve_mod(payload.get("aura"), "aura", frame, active_ability_paths)
            register_mod(aura_row)

        exilus_row = exilus_rank = exilus_raw = None
        if payload.get("exilus") is not None:
            exilus_row, exilus_rank, exilus_raw, _ = self._resolve_mod(payload.get("exilus"), "exilus", frame, active_ability_paths)
            register_mod(exilus_row)

        raw_mods = payload.get("normalMods")
        if raw_mods is None:
            raw_mods = payload.get("mods") or []
        if not isinstance(raw_mods, list) or len(raw_mods) > NORMAL_SLOT_COUNT:
            raise SimulationError(f"normalMods must be an array with at most {NORMAL_SLOT_COUNT} entries")
        occupied: set[int] = set()
        for index, item in enumerate(raw_mods):
            if item is None:
                continue
            row, rank, raw, slot_kind = self._resolve_mod(item, "normal", frame, active_ability_paths)
            choice = _choice(item, "normalMods") or {}
            slot = choice.get("slot", index)
            if isinstance(slot, bool) or not isinstance(slot, int) or not 0 <= slot < NORMAL_SLOT_COUNT or slot in occupied:
                raise SimulationError(f"normalMods[{index}] has an invalid or duplicate slot")
            register_mod(row)
            occupied.add(slot)
            selected.append((row, rank, raw, slot, slot_kind))

        if exilus_row is not None:
            selected.append((exilus_row, int(exilus_rank), int(exilus_raw), NORMAL_SLOT_COUNT, "exilus"))

        capacity = DEFAULT_CAPACITY
        aura_assignment = None
        if aura_row is not None:
            adjusted, relation = _warframe_slot_drain(int(aura_raw), aura_row.get("polarity"), aura_pol)
            capacity += -adjusted
            aura_assignment = {
                "path": _row_id(aura_row),
                "rank": aura_rank,
                "rawDrain": aura_raw,
                "drain": adjusted,
                "polarityRelation": relation,
                "slotPolarity": aura_pol,
            }

        assignments: list[dict[str, Any]] = []
        used = 0
        for row, rank, raw, slot, slot_kind in selected:
            slot_pol = exilus_pol if slot == NORMAL_SLOT_COUNT else normal_pols[slot]
            adjusted, relation = _warframe_slot_drain(raw, row.get("polarity"), slot_pol)
            used += adjusted
            assignments.append({
                "path": _row_id(row),
                "slot": slot,
                "rank": rank,
                "rawDrain": raw,
                "drain": adjusted,
                "polarityRelation": relation,
                "slotPolarity": slot_pol,
                "slotKind": slot_kind,
            })

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

        shield_recharge_rate_pct = 0.0
        shield_delay_pct = 0.0

        def add_card(row: Mapping[str, Any], rank: int) -> None:
            nonlocal shield_recharge_rate_pct, shield_delay_pct
            card_path = _row_id(row)
            set_id = _set_id(row)
            multiplier = _set_multiplier(row, set_counts.get(set_id, 0)) if set_id else 1.0
            for raw_fx in (row.get("effects") or ()):
                if not isinstance(raw_fx, Mapping):
                    continue
                ut = str(raw_fx.get("upgradeType") or "").upper()
                if ut == "AVATAR_SHIELD_RECHARGE_RATE":
                    val = _effect_value(raw_fx, rank)
                    if val is not None:
                        shield_recharge_rate_pct += val * multiplier
                elif ut == "AVATAR_SHIELD_RECHARGE_DELAY":
                    val = _effect_value(raw_fx, rank)
                    if val is not None:
                        shield_delay_pct += val * multiplier
            if _path_token(card_path) in self.non_self_aura_paths:
                return
            if _path_token(card_path) == _path_token(ARCANE_ICE_STORM_PATH):
                return
            for effect in _effects(row, rank, conditionals=conditionals, source=card_path, set_multiplier=multiplier):
                _apply_effect(panel, effect, active)

        if aura_row is not None:
            add_card(aura_row, int(aura_rank))
        for row, rank, _raw, _slot, _kind in selected:
            add_card(row, rank)
        for row, rank in arcane_rows:
            add_card(row, rank)
        for row, _ in shard_rows:
            add_card(row, 0)

        invigoration = payload.get("invigoration")
        invigoration_choices = [] if invigoration is None else (invigoration if isinstance(invigoration, list) else [invigoration])
        if len(invigoration_choices) > 2:
            raise SimulationError("invigoration allows at most 2 effects")
        invigoration_categories: set[str] = set()
        selected_invigorations: list[str] = []
        selected_invigoration_rows: list[Mapping[str, Any]] = []
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
            selected_invigoration_rows.append(row)

        arcane_by_path: dict[str, tuple[Mapping[str, Any], int]] = {
            _path_token(_row_id(row)): (row, rank) for row, rank in arcane_rows
        }
        mod_by_path: dict[str, tuple[Mapping[str, Any], int]] = {
            _path_token(_row_id(row)): (row, rank) for row, rank, *_ in selected
        }
        if aura_row is not None:
            mod_by_path[_path_token(_row_id(aura_row))] = (aura_row, int(aura_rank))

        # Explicit conditional Warframe arcanes missing or mis-encoded in raw export.
        if _path_token(ARCANE_INTENTION_PATH) in arcane_by_path:
            int_row, int_rank = arcane_by_path[_path_token(ARCANE_INTENTION_PATH)]
            raw_channels = payload.get("activeChanneledAbilities", payload.get("channeledAbilities"))
            if raw_channels is not None:
                if isinstance(raw_channels, bool) or not isinstance(raw_channels, int) or raw_channels < 0:
                    raise SimulationError("activeChanneledAbilities must be a non-negative integer")
                channels = min(raw_channels, ABILITY_SLOT_COUNT)
            else:
                channels = 1 if conditionals else 0
            if channels > 0:
                hp_add = ARCANE_INTENTION_HP_PER_CHANNEL[min(int_rank, 5)] * channels
                _apply_effect(
                    panel,
                    {
                        "stat": "health",
                        "value": hp_add,
                        "operation": "ADD_BASE",
                        "unit": "flat",
                        "source": _row_id(int_row),
                        "label": "Arcane Intention",
                        "conditional": True,
                        "condition": "whileChanneled",
                    },
                    active,
                )

        if conditionals:
            if _path_token(ARCANE_CREPUSCULAR_PATH) in arcane_by_path:
                cr_row, cr_rank = arcane_by_path[_path_token(ARCANE_CREPUSCULAR_PATH)]
                _apply_effect(
                    panel,
                    {
                        "stat": "abilityStrength",
                        "value": 0.05 * (cr_rank + 1),
                        "operation": "STACKING_MULTIPLY",
                        "source": _row_id(cr_row),
                        "label": "Arcane Crepuscular",
                        "conditional": True,
                        "condition": "whileInvisible",
                    },
                    active,
                )
            if _path_token(ARCANE_CAMISADO_PATH) in arcane_by_path:
                ca_row, ca_rank = arcane_by_path[_path_token(ARCANE_CAMISADO_PATH)]
                _apply_effect(
                    panel,
                    {
                        "stat": "abilityStrength",
                        "value": 0.10 * (ca_rank + 1),
                        "operation": "STACKING_MULTIPLY",
                        "source": _row_id(ca_row),
                        "label": "Arcane Camisado",
                        "conditional": True,
                        "condition": "onSummonAttack",
                    },
                    active,
                )
            if _path_token(ARCANE_IMPETUS_PATH) in arcane_by_path:
                im_row, im_rank = arcane_by_path[_path_token(ARCANE_IMPETUS_PATH)]
                raw_stacks = payload.get("impetusStacks", 13)
                if isinstance(raw_stacks, bool) or not isinstance(raw_stacks, int) or raw_stacks < 0:
                    raise SimulationError("impetusStacks must be a non-negative integer")
                stacks = min(raw_stacks, 13)
                if stacks > 0:
                    _apply_effect(
                        panel,
                        {
                            "stat": "abilityStrength",
                            "value": stacks * 0.01 * (im_rank + 1),
                            "operation": "STACKING_MULTIPLY",
                            "source": _row_id(im_row),
                            "label": "Arcane Impetus",
                            "conditional": True,
                            "condition": "onAbilityStatus",
                        },
                        active,
                    )
                    _apply_effect(
                        panel,
                        {
                            "stat": "abilityEfficiency",
                            "value": stacks * 0.005 * (im_rank + 1),
                            "operation": "STACKING_MULTIPLY",
                            "source": _row_id(im_row),
                            "label": "Arcane Impetus",
                            "conditional": True,
                            "condition": "onAbilityStatus",
                        },
                        active,
                    )
            if _path_token(ARCANE_ICE_STORM_PATH) in arcane_by_path:
                ic_row, ic_rank = arcane_by_path[_path_token(ARCANE_ICE_STORM_PATH)]
                ice_stacks = 10 + 2 * min(ic_rank, 5)
                ice_bonus = 0.02 * ice_stacks
                for ice_stat in ("abilityStrength", "abilityDuration"):
                    _apply_effect(
                        panel,
                        {
                            "stat": ice_stat,
                            "value": ice_bonus,
                            "operation": "STACKING_MULTIPLY",
                            "source": _row_id(ic_row),
                            "label": "Arcane Ice Storm",
                            "conditional": True,
                            "condition": "onFreeze",
                        },
                        active,
                    )

        # Update 34+ Rank-30 stat scaling + ordered conversion passes.
        seed = _panel_seed(frame)
        base_panel = dict(seed)
        final_panel: dict[str, float] = {}

        # Pass 1: Health, Armor, Sprint.
        for stat in ("health", "armor", "sprint"):
            state = panel[stat]
            value = state["set"] if state["set"] is not None else seed[stat] * (1.0 + state["percent"]) + state["flat"]
            final_panel[stat] = round(max(0.0, value), 6)

        # Pass 2: Arcane Bellicose (post-Health -> Ability Strength, before Arcane Expertise).
        if _path_token(ARCANE_BELLICOSE_PATH) in arcane_by_path:
            bel_row, bel_rank = arcane_by_path[_path_token(ARCANE_BELLICOSE_PATH)]
            inc = 0.01 * (bel_rank + 1)
            cap = 0.12 * (bel_rank + 1)
            bel_bonus = min(cap, math.floor(final_panel["health"] / 250.0 * inc * 100.0 + 0.5 + 1e-12) / 100.0)
            if bel_bonus > 0:
                _apply_effect(
                    panel,
                    {
                        "stat": "abilityStrength",
                        "value": bel_bonus,
                        "operation": "STACKING_MULTIPLY",
                        "source": _row_id(bel_row),
                        "label": "Arcane Bellicose",
                    },
                    active,
                )

        # Resolve Strength, Range, Efficiency, and utility panel stats.
        for stat in ("abilityStrength", "abilityRange", "abilityEfficiency", *panel_extras):
            state = panel[stat]
            final_panel[stat] = round(state["flat"] + state["percent"], 6)
        final_panel["abilityStrength"] = round(1.0 + final_panel["abilityStrength"], 6)
        final_panel["abilityRange"] = round(1.0 + final_panel["abilityRange"], 6)
        final_panel["abilityEfficiency"] = round(min(1.75, max(0.0, 1.0 + final_panel["abilityEfficiency"])), 6)

        precision_bonus = 0.0
        if _path_token(PRECISION_INTENSIFY_PATH) in mod_by_path:
            _pi_row, pi_rank = mod_by_path[_path_token(PRECISION_INTENSIFY_PATH)]
            precision_bonus = 0.15 * (pi_rank + 1)
        final_panel["abilityFourStrength"] = round(final_panel["abilityStrength"] + precision_bonus, 6)

        # Pass 3: Arcane Battery (post-Armor -> flat Max Energy, before Violet Shard >500 Energy check).
        if _path_token(ARCANE_BATTERY_PATH) in arcane_by_path and seed["energy"] > 0:
            bat_row, bat_rank = arcane_by_path[_path_token(ARCANE_BATTERY_PATH)]
            bat_energy = min(1000.0, final_panel["armor"] * 0.05 * (bat_rank + 1))
            if bat_energy > 0:
                _apply_effect(
                    panel,
                    {
                        "stat": "energy",
                        "value": bat_energy,
                        "operation": "ADD_BASE",
                        "unit": "flat",
                        "source": _row_id(bat_row),
                        "label": "Arcane Battery",
                    },
                    active,
                )

        energy_state = panel["energy"]
        if energy_state["set"] is not None:
            final_panel["energy"] = round(max(0.0, energy_state["set"]), 6)
        elif seed["energy"] <= 0:
            final_panel["energy"] = 0.0
        else:
            final_panel["energy"] = round(max(0.0, seed["energy"] * (1.0 + energy_state["percent"]) + energy_state["flat"]), 6)

        # Pass 4: Arcane Expertise (post-Strength -> additive % Max Shields, before Catalyzing Shields).
        if _path_token(ARCANE_EXPERTISE_PATH) in arcane_by_path and seed["shield"] > 0:
            exp_row, exp_rank = arcane_by_path[_path_token(ARCANE_EXPERTISE_PATH)]
            exp_pct = max(0.0, final_panel["abilityStrength"] - 1.0) * ((exp_rank + 1) / 6.0)
            if exp_pct > 0:
                _apply_effect(
                    panel,
                    {
                        "stat": "shield",
                        "value": exp_pct,
                        "operation": "STACKING_MULTIPLY",
                        "source": _row_id(exp_row),
                        "label": "Arcane Expertise",
                    },
                    active,
                )

        catalyzing_entry = mod_by_path.get(_path_token(CATALYZING_SHIELDS_PATH))
        catalyzing_rank = catalyzing_entry[1] if catalyzing_entry is not None else None
        persistence_entry = arcane_by_path.get(_path_token(ARCANE_PERSISTENCE_PATH))
        persistence_rank = persistence_entry[1] if persistence_entry is not None else None

        shield_mult = 1.0
        if catalyzing_rank is not None:
            shield_mult *= CATALYZING_SHIELD_MULTIPLIERS[min(catalyzing_rank, 3)]
        if persistence_rank is not None:
            shield_mult = 0.0

        shield_state = panel["shield"]
        if shield_state["set"] is not None:
            raw_shield = shield_state["set"] * shield_mult
        elif seed["shield"] <= 0:
            raw_shield = 0.0
        else:
            raw_shield = (seed["shield"] * (1.0 + shield_state["percent"]) + shield_state["flat"]) * shield_mult
        final_panel["shield"] = round(max(0.0, raw_shield), 6)

        # Pass 5: Molt Efficiency (post-Shield -> Ability Duration when conditional and shields > 0).
        if conditionals and final_panel["shield"] > 0 and _path_token(MOLT_EFFICIENCY_PATH) in arcane_by_path:
            me_row, me_rank = arcane_by_path[_path_token(MOLT_EFFICIENCY_PATH)]
            _apply_effect(
                panel,
                {
                    "stat": "abilityDuration",
                    "value": 0.06 * (me_rank + 1),
                    "operation": "STACKING_MULTIPLY",
                    "source": _row_id(me_row),
                    "label": "Molt Efficiency",
                    "conditional": True,
                    "condition": "whileShieldActive",
                },
                active,
            )

        dur_state = panel["abilityDuration"]
        final_panel["abilityDuration"] = round(1.0 + dur_state["flat"] + dur_state["percent"], 6)

        final_panel["armour"] = final_panel["armor"]
        if final_panel["armor"] > 0:
            final_panel["damageReduction"] = round(final_panel["armor"] / (final_panel["armor"] + 300.0), 6)
            final_panel["ehp"] = round(final_panel["health"] / max(1e-9, 1.0 - final_panel["damageReduction"]), 6)
        else:
            final_panel["damageReduction"] = 0.0
            final_panel["ehp"] = final_panel["health"]

        survivability = self._build_survivability(
            final_panel=final_panel,
            mod_by_path=mod_by_path,
            set_counts=set_counts,
            selected_invigorations=selected_invigorations,
            catalyzing_rank=catalyzing_rank,
            persistence_rank=persistence_rank,
            shield_recharge_rate_pct=shield_recharge_rate_pct,
            shield_delay_pct=shield_delay_pct,
        )
        final_panel.update(survivability)

        def scale_ability(ability: Mapping[str, Any], slot_index: int) -> dict[str, Any]:
            row = dict(ability)
            slot_strength = final_panel["abilityFourStrength"] if slot_index == 3 else final_panel["abilityStrength"]
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
                factor = {
                    "strength": slot_strength,
                    "duration": final_panel["abilityDuration"],
                    "range": final_panel["abilityRange"],
                    "efficiency": max(0.25, 2.0 - final_panel["abilityEfficiency"]),
                    "drain": max(0.25, (2.0 - final_panel["abilityEfficiency"]) / max(0.01, final_panel["abilityDuration"])),
                }.get(scale, 1.0)
                base_values = [float(value) for value in values if _number(value) is not None] if isinstance(values, (list, tuple)) else [float(base)]
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

        ability_scalars = [scale_ability(ability, idx) for idx, ability in enumerate(abilities[:ABILITY_SLOT_COUNT])]
        forma = {"aura": 0, "exilus": 0, "normal": 0}
        source_aura, source_exilus, source_normal = _slot_polarities(frame, None)
        if aura_pol != source_aura:
            forma["aura"] = 1
        if exilus_pol != source_exilus:
            forma["exilus"] = 1
        forma["normal"] = sum(a != b for a, b in zip(normal_pols, source_normal))

        weapon_bridge = self._build_weapon_bridge(
            frame=frame,
            final_panel=final_panel,
            survivability=survivability,
            aura_row=aura_row,
            aura_rank=aura_rank,
            selected=selected,
            mod_by_path=mod_by_path,
            set_counts=set_counts,
            arcane_rows=arcane_rows,
            shard_rows=shard_rows,
            selected_invigoration_rows=selected_invigoration_rows,
            abilities=abilities[:ABILITY_SLOT_COUNT],
            helminth_slot=helminth_slot,
        )

        return {
            "catalogRevision": self.catalog.get("buildLabel"),
            "frame": {key: frame.get(key) for key in ("id", "path", "nameEn", "nameZh", "iconAsset", "portraitAsset", "parentFrameId", "formKind", "formLabelZh", "formLabelEn") if frame.get(key) is not None},
            "inheritance": dict(inheritance),
            "rank": 30,
            "capacityBreakdown": {
                "base": DEFAULT_CAPACITY,
                "auraGain": capacity - DEFAULT_CAPACITY,
                "used": used,
                "limit": capacity,
                "remaining": capacity - used,
                "valid": used <= capacity,
                "assignments": assignments,
                "aura": aura_assignment,
            },
            "formaBreakdown": forma,
            "basePanel": {**base_panel, "armour": base_panel["armor"]},
            "finalPanel": final_panel,
            "survivability": survivability,
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
            "validation": {
                "valid": used <= capacity,
                "errors": ([] if used <= capacity else ["MOD capacity exceeded"]),
                "warnings": list(self.catalog.get("gaps") or ()),
            },
            "selected": {
                "aura": _row_id(aura_row) if aura_row else None,
                "exilus": _row_id(exilus_row) if exilus_row else None,
                "arcanes": [_row_id(row) for row, _ in arcane_rows],
                "shards": [_row_id(row) for row, _ in shard_rows],
                "invigoration": selected_invigorations,
            },
            "weaponBridge": weapon_bridge,
        }

    def _build_survivability(
        self,
        *,
        final_panel: Mapping[str, float],
        mod_by_path: Mapping[str, tuple[Mapping[str, Any], int]],
        set_counts: Mapping[str, int],
        selected_invigorations: Sequence[str],
        catalyzing_rank: int | None,
        persistence_rank: int | None,
        shield_recharge_rate_pct: float,
        shield_delay_pct: float,
    ) -> dict[str, Any]:
        shield = float(final_panel["shield"])
        armor = float(final_panel["armor"])
        if shield <= 0:
            shield_gate_seconds = 0.0
            shield_recharge_rate = 0.0
        else:
            if catalyzing_rank is not None:
                shield_gate_seconds = CATALYZING_SHIELD_GATE_SECONDS[min(catalyzing_rank, 3)]
            else:
                shield_gate_seconds = round(0.33 + 2.17 * (min(1.0, shield / 1150.0) ** 0.65), 6)
            shield_recharge_rate = round((15.0 + 0.05 * shield) * max(0.0, 1.0 + shield_recharge_rate_pct), 6)

        delay_factor = max(0.20, 1.0 + shield_delay_pct)
        shield_recharge_delay = round(1.0 * delay_factor, 6)
        shield_depleted_delay = round(4.0 * delay_factor, 6)

        brief_entry = mod_by_path.get(_path_token(BRIEF_RESPITE_PATH))
        brief_ratio = 0.25 * (brief_entry[1] + 1) if brief_entry is not None else 0.0
        augur_pieces = int(set_counts.get("augursetmod", 0))
        energy_to_shield_ratio = 0.0 if shield <= 0 else round(brief_ratio + 0.40 * augur_pieces, 6)

        cd_entry = mod_by_path.get(_path_token(COMBAT_DISCIPLINE_PATH))
        self_damage_on_kill = COMBAT_DISCIPLINE_SELF_DAMAGE[min(cd_entry[1], 5)] if cd_entry is not None else 0.0

        has_adaptation = any(_path_token(p) in mod_by_path for p in ADAPTATION_PATHS)
        has_rolling_guard = _path_token(ROLLING_GUARD_PATH) in mod_by_path
        status_immune = any(_path_token(inv) == _path_token(STATUS_RESIST_INVIG_PATH) for inv in selected_invigorations)

        damage_cap_per_second: float | None = None
        if persistence_rank is not None and armor > 700.0:
            damage_cap_per_second = float(750 - 50 * min(persistence_rank, 5))

        return {
            "shieldGateSeconds": shield_gate_seconds,
            "shieldRechargeRate": shield_recharge_rate,
            "shieldRechargeDelay": shield_recharge_delay,
            "shieldDepletedDelay": shield_depleted_delay,
            "catalyzingShields": catalyzing_rank is not None,
            "arcanePersistence": persistence_rank is not None,
            "damageCapPerSecond": damage_cap_per_second,
            "energyToShieldRatio": energy_to_shield_ratio,
            "selfDamageOnKill": self_damage_on_kill,
            "hasAdaptation": has_adaptation,
            "adaptationMaxDr": 0.90 if has_adaptation else 0.0,
            "hasRollingGuard": has_rolling_guard,
            "statusImmune": status_immune,
        }

    def _build_weapon_bridge(
        self,
        *,
        frame: Mapping[str, Any],
        final_panel: Mapping[str, Any],
        survivability: Mapping[str, Any],
        aura_row: Mapping[str, Any] | None,
        aura_rank: int | None,
        selected: Sequence[tuple[Mapping[str, Any], int, int, int | None, str]],
        mod_by_path: Mapping[str, tuple[Mapping[str, Any], int]],
        set_counts: Mapping[str, int],
        arcane_rows: Sequence[tuple[Mapping[str, Any], int]],
        shard_rows: Sequence[tuple[Mapping[str, Any], int]],
        selected_invigoration_rows: Sequence[Mapping[str, Any]],
        abilities: Sequence[Mapping[str, Any]],
        helminth_slot: int | None,
    ) -> dict[str, Any]:
        # 1. Frame identity
        frame_bridge = {
            "id": _row_id(frame),
            "path": frame.get("path") or _row_id(frame),
            "nameEn": frame.get("nameEn"),
            "nameZh": frame.get("nameZh"),
            "portraitAsset": frame.get("portraitAsset") or frame.get("iconAsset"),
        }

        # 2. Panel & survivability
        panel_bridge = {
            key: final_panel[key]
            for key in (
                "health",
                "shield",
                "armor",
                "energy",
                "sprint",
                "abilityStrength",
                "abilityDuration",
                "abilityRange",
                "abilityEfficiency",
                "castingSpeed",
                "abilityFourStrength",
                "healthRegen",
                "energyRegen",
            )
        }

        # 3. Shards
        rbp_count = sum(
            1
            for row, _ in shard_rows
            if str(row.get("color") or "").casefold() in {"red", "blue", "purple", "crimson", "azure", "violet"}
        )
        energy_over_500 = float(final_panel["energy"]) > 500.0
        primary_status_chance = 0.0
        secondary_crit_chance = 0.0
        melee_crit_damage = 0.0
        primary_electricity = 0.0
        toxin_status_damage = 0.0
        corrosive_max_stacks_bonus = 0
        topaz_secondary_crit_max = 0.0

        for row, _ in shard_rows:
            leaf = str(row.get("path") or _row_id(row)).rsplit("/", 1)[-1]
            tau = bool(row.get("tau")) or leaf.endswith("Mythic")
            base_leaf = leaf[:-6] if leaf.endswith("Mythic") else leaf
            if base_leaf == "ArchonCrystalUpgradePrimaryStatusChance":
                primary_status_chance += 0.375 if tau else 0.25
            elif base_leaf == "ArchonCrystalUpgradeSecondaryCritChance":
                secondary_crit_chance += 0.375 if tau else 0.25
            elif base_leaf == "ArchonCrystalUpgradeMeleeCritDamage":
                melee_crit_damage += 0.375 if tau else 0.25
            elif base_leaf == "ArchonCrystalUpgradeWarframeCritDamageBoost":
                melee_crit_damage += (0.375 if tau else 0.25) * (2.0 if energy_over_500 else 1.0)
            elif base_leaf == "ArchonCrystalUpgradeWarframeElectricDamage":
                primary_electricity += (0.45 + 0.15 * rbp_count) if tau else (0.30 + 0.10 * rbp_count)
            elif base_leaf == "ArchonCrystalUpgradeWarframeToxinDamage":
                toxin_status_damage += 0.45 if tau else 0.30
            elif base_leaf == "ArchonCrystalUpgradeWarframeCorrosiveStack":
                corrosive_max_stacks_bonus += 3 if tau else 2
            elif base_leaf == "ArchonCrystalUpgradeWeaponCritBoostFromHeat":
                topaz_secondary_crit_max += 0.75 if tau else 0.50

        primary_status_chance = round(primary_status_chance, 6)
        secondary_crit_chance = round(secondary_crit_chance, 6)
        melee_crit_damage = round(melee_crit_damage, 6)
        primary_electricity = round(primary_electricity, 6)
        toxin_status_damage = round(toxin_status_damage, 6)
        topaz_secondary_crit_max = round(topaz_secondary_crit_max, 6)

        shard_effects_spec: list[dict[str, Any]] = []
        shard_summary: list[dict[str, str]] = []
        if primary_status_chance > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_PROC_CHANCE",
                "operation": "STACKING_MULTIPLY",
                "value": primary_status_chance,
                "validTypes": [PRIMARY_WEAPON_TYPE],
                "source": "shard:primaryStatusChance",
            })
            shard_summary.append({"labelZh": "主要武器触发几率", "detailZh": f"+{_fmt_pct(primary_status_chance)}%"})
        if secondary_crit_chance > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_CRIT_CHANCE",
                "operation": "STACKING_MULTIPLY",
                "value": secondary_crit_chance,
                "validTypes": [SECONDARY_WEAPON_TYPE],
                "source": "shard:secondaryCritChance",
            })
            shard_summary.append({"labelZh": "次要武器暴击几率", "detailZh": f"+{_fmt_pct(secondary_crit_chance)}%"})
        if melee_crit_damage > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_CRIT_DAMAGE",
                "operation": "STACKING_MULTIPLY",
                "value": melee_crit_damage,
                "validTypes": [MELEE_WEAPON_TYPE],
                "source": "shard:meleeCritDamage",
            })
            shard_summary.append({"labelZh": "近战暴击伤害", "detailZh": f"+{_fmt_pct(melee_crit_damage)}%"})
        if primary_electricity > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
                "operation": "STACKING_MULTIPLY",
                "value": primary_electricity,
                "damageType": "DT_ELECTRICITY",
                "validTypes": [PRIMARY_WEAPON_TYPE],
                "source": "shard:primaryElectricity",
            })
            shard_summary.append({"labelZh": "主要武器电击伤害", "detailZh": f"+{_fmt_pct(primary_electricity)}%（参与元素复合）"})
        if toxin_status_damage > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_PROC_DAMAGE",
                "operation": "STACKING_MULTIPLY",
                "value": toxin_status_damage,
                "damageType": "DT_POISON",
                "validProcTypes": ["PT_POISON"],
                "source": "shard:toxinStatusDamage",
            })
            shard_summary.append({"labelZh": "毒素异常伤害", "detailZh": f"+{_fmt_pct(toxin_status_damage)}%"})
        if corrosive_max_stacks_bonus > 0:
            shard_effects_spec.append({
                "upgradeType": "RUNTIME_TYPED_PROC_MAX_STACK",
                "operation": "ADD",
                "value": float(corrosive_max_stacks_bonus),
                "damageType": "DT_CORROSIVE",
                "source": "shard:corrosiveMaxStacksBonus",
            })
            shard_summary.append({"labelZh": "腐蚀层数上限", "detailZh": f"+{corrosive_max_stacks_bonus}（最高 {10 + corrosive_max_stacks_bonus} 层）"})
        if topaz_secondary_crit_max > 0:
            shard_effects_spec.append({
                "upgradeType": "WEAPON_CRIT_CHANCE",
                "operation": "STACKING_MULTIPLY",
                "value": topaz_secondary_crit_max,
                "validTypes": [SECONDARY_WEAPON_TYPE],
                "conditional": True,
                "condition": "onHeatStatusKill",
                "source": "shard:topazSecondaryCritMax",
            })
            shard_summary.append({"labelZh": "次要武器火焰击杀暴击上限", "detailZh": f"+{_fmt_pct(topaz_secondary_crit_max)}%（加算）"})

        shards_bridge = {
            "primaryStatusChance": primary_status_chance,
            "secondaryCritChance": secondary_crit_chance,
            "meleeCritDamage": melee_crit_damage,
            "primaryElectricity": primary_electricity,
            "toxinStatusDamage": toxin_status_damage,
            "corrosiveMaxStacksBonus": corrosive_max_stacks_bonus,
            "topazSecondaryCritMax": topaz_secondary_crit_max,
            "topazSecondaryCritMode": "additive",
            "rbpCount": rbp_count,
            "violetMeleeCritDoubled": energy_over_500,
            "effectsSpec": shard_effects_spec,
            "summary": shard_summary,
        }

        # 4. Invigorations
        invig_bonuses = {
            "primaryDamage": 0.0,
            "secondaryDamage": 0.0,
            "meleeDamage": 0.0,
            "primaryCritChance": 0.0,
            "secondaryCritChance": 0.0,
            "meleeCritChance": 0.0,
            "reloadSpeed": 0.0,
        }
        invig_effects_spec: list[dict[str, Any]] = []
        invig_summary: list[dict[str, str]] = []
        invig_table: dict[str, tuple[str, float, str, str, list[str] | None, str]] = {
            "OffensiveInvigorationPrimaryDamage": ("primaryDamage", 2.50, "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", [PRIMARY_WEAPON_TYPE], "主要武器伤害"),
            "OffensiveInvigorationSecondaryDamage": ("secondaryDamage", 2.50, "WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", [SECONDARY_WEAPON_TYPE], "次要武器伤害"),
            "OffensiveInvigorationMeleeDamage": ("meleeDamage", 2.50, "WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", [MELEE_WEAPON_TYPE], "近战伤害"),
            "OffensiveInvigorationPrimaryCritChance": ("primaryCritChance", 2.00, "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", [PRIMARY_WEAPON_TYPE], "主要武器暴击几率"),
            "OffensiveInvigorationSecondaryCritChance": ("secondaryCritChance", 2.00, "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", [SECONDARY_WEAPON_TYPE], "次要武器暴击几率"),
            "OffensiveInvigorationMeleeCritChance": ("meleeCritChance", 2.00, "WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", [MELEE_WEAPON_TYPE], "近战暴击几率"),
            "UtilityInvigorationReloadSpeed": ("reloadSpeed", 0.75, "WEAPON_RELOAD_SPEED", "STACKING_MULTIPLY", GUN_WEAPON_TYPES, "装填速度"),
        }
        for row in selected_invigoration_rows:
            leaf = str(row.get("path") or _row_id(row)).rsplit("/", 1)[-1]
            spec = invig_table.get(leaf)
            if spec is None:
                continue
            field_key, amount, ut, op, vtypes, label_zh = spec
            invig_bonuses[field_key] = round(invig_bonuses[field_key] + amount, 6)
            invig_effects_spec.append({
                "upgradeType": ut,
                "operation": op,
                "value": amount,
                "validTypes": vtypes,
                "source": f"invigoration:{leaf}",
            })
            invig_summary.append({"labelZh": label_zh, "detailZh": f"+{_fmt_pct(amount)}%"})

        invigorations_bridge = {
            **invig_bonuses,
            "effectsSpec": invig_effects_spec,
            "summary": invig_summary,
        }

        # 5. Aura + Coaction Drift
        coaction_entry = mod_by_path.get(_path_token(COACTION_DRIFT_PATH))
        has_coaction_drift = coaction_entry is not None
        coaction_rank = coaction_entry[1] if coaction_entry is not None else None
        # Matches app.py EXTERNAL_BUFFS["coaction-drift"] convention (+30% -> 1.30x at R5).
        coaction_multiplier = round(1.0 + 0.05 * (coaction_rank + 1), 6) if coaction_rank is not None else 1.0
        coaction_self_product = round((1.0 + 0.025 * (coaction_rank + 1)) ** 2, 6) if coaction_rank is not None else 1.0

        auras_meta = self.synergy.get("auras") if isinstance(self.synergy.get("auras"), Mapping) else {}
        aura_path = _row_id(aura_row) if aura_row is not None else None
        aura_spec = auras_meta.get(aura_path) if aura_path else None
        aura_buff_id = str(aura_spec.get("buffId")) if isinstance(aura_spec, Mapping) and aura_spec.get("buffId") else None
        aura_base_val = 0.0
        aura_effective_val = 0.0
        aura_effects_spec: list[dict[str, Any]] = []

        if aura_row is not None and aura_rank is not None and isinstance(aura_spec, Mapping):
            max_rank = max(0, int(aura_row.get("maxRank") or 5))
            rank_ratio = (aura_rank + 1) / float(max_rank + 1)
            aura_base_val = round(float(aura_spec.get("base") or 0.0) * rank_ratio, 6)
            aura_effective_val = round(aura_base_val * coaction_multiplier, 6)
            if aura_buff_id in _AURA_UPGRADE_TYPES:
                ut, op = _AURA_UPGRADE_TYPES[aura_buff_id]
                aura_effects_spec.append({
                    "upgradeType": ut,
                    "operation": op,
                    "value": aura_effective_val,
                    "validTypes": aura_spec.get("validTypes"),
                    "source": f"aura:{aura_buff_id}",
                })

        holster_amp = 0.0
        swift_momentum = None
        empowered_blades = None
        if aura_row is not None and aura_rank is not None:
            aura_token = _path_token(aura_path)
            if aura_token == _path_token(HOLSTER_AMP_PATH):
                holster_amp = round(0.10 * (aura_rank + 1) * coaction_multiplier, 6)
                aura_effects_spec.append({
                    "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                    "operation": "STACKING_MULTIPLY",
                    "value": holster_amp,
                    "validTypes": GUN_WEAPON_TYPES,
                    "conditional": True,
                    "condition": "onEquip",
                    "source": "aura:holster-amp",
                })
            elif aura_token == _path_token(SWIFT_MOMENTUM_PATH):
                wind_up = round(0.05 * (aura_rank + 1) * coaction_multiplier, 6)
                combo_dur = round(1.0 * (aura_rank + 1) * coaction_multiplier, 6)
                swift_momentum = {"heavyWindUpSpeed": wind_up, "comboDuration": combo_dur}
                aura_effects_spec.extend([
                    {
                        "upgradeType": "WEAPON_MELEE_HEAVY_CHARGE_SPEED",
                        "operation": "STACKING_MULTIPLY",
                        "value": wind_up,
                        "validTypes": [MELEE_WEAPON_TYPE],
                        "source": "aura:swift-momentum",
                    },
                    {
                        "upgradeType": "WEAPON_MELEE_COMBO_DURATION_BONUS",
                        "operation": "ADD",
                        "value": combo_dur,
                        "validTypes": [MELEE_WEAPON_TYPE],
                        "source": "aura:swift-momentum",
                    },
                ])
            elif aura_token == _path_token(EMPOWERED_BLADES_PATH):
                heavy_bonus = round(0.10 * (aura_rank + 1) * coaction_multiplier, 6)
                shield_drain = round(15.0 * (aura_rank + 1), 6)
                empowered_blades = {
                    "heavyStatusChance": heavy_bonus,
                    "heavyStatusDamage": heavy_bonus,
                    "shieldDrainPerHit": shield_drain,
                }
                aura_effects_spec.extend([
                    {
                        "upgradeType": "WEAPON_PROC_CHANCE",
                        "operation": "STACKING_MULTIPLY",
                        "value": heavy_bonus,
                        "validTypes": [MELEE_WEAPON_TYPE],
                        "conditional": True,
                        "condition": "PM_HEAVY_MELEE",
                        "source": "aura:empowered-blades",
                    },
                    {
                        "upgradeType": "WEAPON_PROC_DAMAGE",
                        "operation": "STACKING_MULTIPLY",
                        "value": heavy_bonus,
                        "validTypes": [MELEE_WEAPON_TYPE],
                        "conditional": True,
                        "condition": "PM_HEAVY_MELEE",
                        "source": "aura:empowered-blades",
                    },
                ])

        aura_bridge = {
            "path": aura_path,
            "nameEn": aura_row.get("nameEn") if aura_row is not None else None,
            "nameZh": aura_row.get("nameZh") if aura_row is not None else None,
            "rank": aura_rank,
            "maxRank": int(aura_row.get("maxRank") or 0) if aura_row is not None else None,
            "buffId": aura_buff_id,
            "baseValue": aura_base_val,
            "value": aura_effective_val,
            "hasCoactionDrift": has_coaction_drift,
            "coactionMultiplier": coaction_multiplier,
            "coactionSelfProduct": coaction_self_product,
            "holsterAmp": holster_amp,
            "swiftMomentum": swift_momentum,
            "empoweredBlades": empowered_blades,
            "combatDisciplineSelfDamage": float(survivability["selfDamageOnKill"]),
            "effectsSpec": aura_effects_spec,
        }

        # 6. Equipped Warframe Arcanes
        arcanes_meta = self.synergy.get("arcanes") if isinstance(self.synergy.get("arcanes"), Mapping) else {}
        arcanes_bridge: list[dict[str, Any]] = []
        for row, rank in arcane_rows:
            apath = _row_id(row)
            meta = arcanes_meta.get(apath) if isinstance(arcanes_meta.get(apath), Mapping) else {}
            fx_specs: list[dict[str, Any]] = []
            for fx in (meta.get("effects") or ()):
                if not isinstance(fx, Mapping):
                    continue
                if isinstance(fx.get("values"), (list, tuple)) and fx["values"]:
                    per_stack = float(fx["values"][min(rank, len(fx["values"]) - 1)])
                elif _number(fx.get("valuePerRank")) is not None:
                    per_stack = float(fx["valuePerRank"]) * (rank + 1)
                else:
                    per_stack = float(_number(fx.get("value")) or 0.0)
                max_stacks = int(fx.get("maxStacks") or 1)
                entry: dict[str, Any] = {
                    "upgradeType": fx.get("upgradeType"),
                    "operation": fx.get("operation") or "ADD",
                    "value": round(per_stack * max_stacks, 6),
                    "perStackValue": round(per_stack, 6),
                    "maxStacks": max_stacks,
                    "source": apath,
                }
                if fx.get("validType"):
                    entry["validType"] = fx["validType"]
                    entry["validTypes"] = [fx["validType"]]
                elif fx.get("validTypes"):
                    entry["validTypes"] = list(fx["validTypes"])
                fx_specs.append(entry)
            arcanes_bridge.append({
                "path": apath,
                "nameEn": row.get("nameEn"),
                "nameZh": row.get("nameZh"),
                "rank": rank,
                "maxRank": int(row.get("maxRank") or 0),
                "triggerKind": str(meta.get("triggerKind") or "conditional"),
                "weaponRelevant": bool(meta.get("weaponRelevant", False)),
                "effectsSpec": fx_specs,
            })

        # 7. Direct Warframe weapon modBonuses & setModPaths
        vs_entry = mod_by_path.get(_path_token(VIGOROUS_SWAP_PATH))
        vigorous_swap = round(0.15 * (vs_entry[1] + 1), 6) if vs_entry is not None else 0.0
        tek_entry = mod_by_path.get(_path_token(TEK_COLLATERAL_PATH))
        tek_collateral = round(0.25 * (tek_entry[1] + 1), 6) if tek_entry is not None else 0.0
        mecha_entry = mod_by_path.get(_path_token(MECHA_EMPOWERED_PATH))
        mecha_empowered = round(0.25 * (mecha_entry[1] + 1) * coaction_multiplier, 6) if mecha_entry is not None else 0.0
        nira_pieces = int(set_counts.get("nirasetmod", 0))
        nira_slam_bonus = round(1.50 * nira_pieces, 6)

        mod_bonus_effects: list[dict[str, Any]] = []
        mod_bonus_summary: list[dict[str, str]] = []
        if vigorous_swap > 0:
            mod_bonus_effects.append({
                "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                "operation": "STACKING_MULTIPLY",
                "value": vigorous_swap,
                "validTypes": GUN_WEAPON_TYPES,
                "conditional": True,
                "condition": "onEquip",
                "source": VIGOROUS_SWAP_PATH,
            })
            mod_bonus_summary.append({"labelZh": "强力切换", "detailZh": f"+{_fmt_pct(vigorous_swap)}% 伤害（切换后 3 秒）"})
        if holster_amp > 0:
            mod_bonus_effects.append({
                "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                "operation": "STACKING_MULTIPLY",
                "value": holster_amp,
                "validTypes": GUN_WEAPON_TYPES,
                "conditional": True,
                "condition": "onEquip",
                "source": HOLSTER_AMP_PATH,
            })
            mod_bonus_summary.append({"labelZh": "切换增幅", "detailZh": f"+{_fmt_pct(holster_amp)}% 伤害（切换后 3 秒）"})
        if nira_slam_bonus > 0:
            mod_bonus_effects.append({
                "upgradeType": "WEAPON_MELEE_SLAM_DAMAGE_BONUS",
                "operation": "STACKING_MULTIPLY",
                "value": nira_slam_bonus,
                "validTypes": [MELEE_WEAPON_TYPE],
                "source": "set:NiraSetMod",
            })
            mod_bonus_summary.append({"labelZh": "混沌蛇主震地加成", "detailZh": f"+{_fmt_pct(nira_slam_bonus)}% 震地伤害"})
        if tek_collateral > 0:
            mod_bonus_effects.append({
                "upgradeType": "WEAPON_CRIT_DAMAGE",
                "operation": "STACKING_MULTIPLY",
                "value": tek_collateral,
                "conditional": True,
                "condition": "inTekZone",
                "source": TEK_COLLATERAL_PATH,
            })
            mod_bonus_summary.append({"labelZh": "技法连带", "detailZh": f"+{_fmt_pct(tek_collateral)}% 暴击伤害（标记区域内）"})
        if mecha_empowered > 0:
            mod_bonus_effects.append({
                "upgradeType": "RUNTIME_FINAL_DAMAGE",
                "operation": "STACKING_MULTIPLY",
                "value": mecha_empowered,
                "conditional": True,
                "condition": "onMechaMarkedTarget",
                "source": MECHA_EMPOWERED_PATH,
            })
            mod_bonus_summary.append({"labelZh": "机甲强化", "detailZh": f"+{_fmt_pct(mecha_empowered)}% 对标记目标伤害"})

        mod_bonuses_bridge = {
            "vigorousSwap": vigorous_swap,
            "holsterAmp": holster_amp,
            "niraSlamBonus": nira_slam_bonus,
            "tekCollateral": tek_collateral,
            "mechaEmpowered": mecha_empowered,
            "effectsSpec": mod_bonus_effects,
            "summary": mod_bonus_summary,
        }

        set_aliases = self.synergy.get("setModAliases") if isinstance(self.synergy.get("setModAliases"), Mapping) else {}
        installed_mod_cards: list[Mapping[str, Any]] = [
            *([aura_row] if aura_row is not None else []),
            *(row for row, *_ in selected),
        ]
        set_mod_paths: list[dict[str, Any]] = []
        for card in installed_mod_cards:
            raw_set = str(card.get("modSet") or "").strip()
            if not raw_set:
                continue
            alias_set = str(set_aliases.get(raw_set) or raw_set)
            set_mod_paths.append({
                "path": _row_id(card),
                "setId": raw_set,
                "setAlias": alias_set,
                "nameZh": card.get("nameZh") or card.get("nameEn"),
                "nameEn": card.get("nameEn"),
            })

        # 8. Available weapon-affecting abilities & equipped augments on THIS build
        available_abilities = self._build_available_abilities(
            abilities=abilities,
            helminth_slot=helminth_slot,
            final_panel=final_panel,
            mod_by_path=mod_by_path,
        )

        return {
            "frame": frame_bridge,
            "panel": panel_bridge,
            "survivability": dict(survivability),
            "shards": shards_bridge,
            "invigorations": invigorations_bridge,
            "aura": aura_bridge,
            "arcanes": arcanes_bridge,
            "modBonuses": mod_bonuses_bridge,
            "setModPaths": set_mod_paths,
            "availableAbilities": available_abilities,
        }

    def _build_available_abilities(
        self,
        *,
        abilities: Sequence[Mapping[str, Any]],
        helminth_slot: int | None,
        final_panel: Mapping[str, Any],
        mod_by_path: Mapping[str, tuple[Mapping[str, Any], int]],
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        ability_specs = self.synergy.get("abilities") or ()
        augment_specs = self.synergy.get("augments") or ()

        slot_by_ability_path: dict[str, int] = {}
        icon_by_ability_path: dict[str, Any] = {}
        for slot_idx, ability in enumerate(abilities):
            apath = str(ability.get("path") or ability.get("id") or "")
            if not apath:
                continue
            atoken = _path_token(apath)
            slot_by_ability_path[atoken] = slot_idx
            icon_by_ability_path[atoken] = ability.get("iconAsset")
            is_helminth = helminth_slot is not None and slot_idx == helminth_slot
            slot_strength = float(final_panel["abilityFourStrength"] if slot_idx == 3 else final_panel["abilityStrength"])
            duration = float(final_panel["abilityDuration"])

            for spec in ability_specs:
                if not isinstance(spec, Mapping) or _path_token(spec.get("abilityPath")) != atoken:
                    continue
                entry_id = str(spec.get("helminthId") if is_helminth and spec.get("helminthId") else spec.get("id"))
                fx_list: list[dict[str, Any]] = []
                summary_parts: list[str] = []
                for fx in (spec.get("effects") or ()):
                    if not isinstance(fx, Mapping):
                        continue
                    base_val = float(fx.get("helminthBase") if is_helminth and fx.get("helminthBase") is not None else fx.get("base") or 0.0)
                    scale_kind = str(fx.get("scale") or "none").casefold()
                    factor = slot_strength if scale_kind == "strength" else (duration if scale_kind == "duration" else 1.0)
                    resolved = base_val * factor
                    if fx.get("augmentModPath") and _path_token(fx["augmentModPath"]) in mod_by_path:
                        if _number(fx.get("augmentMult")) is not None:
                            resolved *= float(fx["augmentMult"])
                    cap_val = _number(fx.get("cap"))
                    if cap_val is not None:
                        if fx.get("augmentModPath") and _path_token(fx["augmentModPath"]) in mod_by_path and _number(fx.get("augmentCap")) is not None:
                            cap_val = float(fx["augmentCap"])
                        resolved = min(resolved, cap_val)
                    resolved = round(resolved, 6)
                    fx_entry: dict[str, Any] = {
                        "upgradeType": fx.get("upgradeType"),
                        "operation": fx.get("operation") or "STACKING_MULTIPLY",
                        "base": round(base_val, 6),
                        "value": resolved,
                        "scale": scale_kind,
                        "labelZh": fx.get("labelZh"),
                    }
                    for opt_key in (
                        "damageType",
                        "validTypes",
                        "forcedProc",
                        "runtimeChance",
                        "meleeScale",
                        "sniperScale",
                        "bodyPartAgain",
                        "backbeatMultiplier",
                        "doomedMultiplier",
                        "wallLatchMultiplier",
                        "stripsArmor",
                        "stripsShield",
                        "perSecond",
                    ):
                        if fx.get(opt_key) is not None:
                            fx_entry[opt_key] = fx.get(opt_key)
                    fx_list.append(fx_entry)
                    label_zh = str(fx.get("labelZh") or fx.get("upgradeType") or "")
                    if fx.get("operation") == "MULTIPLY":
                        summary_parts.append(f"{label_zh} ×{resolved:g}")
                    else:
                        sign = "+" if resolved >= 0 else ""
                        summary_parts.append(f"{label_zh} {sign}{_fmt_pct(abs(resolved)) if resolved >= 0 else '-' + _fmt_pct(abs(resolved))}%")

                out.append({
                    "id": entry_id,
                    "abilityPath": apath,
                    "modPath": None,
                    "slot": slot_idx,
                    "isHelminth": is_helminth,
                    "isAugment": False,
                    "nameEn": spec.get("nameEn") or ability.get("nameEn"),
                    "nameZh": spec.get("nameZh") or ability.get("nameZh"),
                    "iconAsset": ability.get("iconAsset"),
                    "defaultActive": bool(spec.get("defaultActive", True)),
                    "requiresElementChoice": bool(spec.get("requiresElementChoice", False)),
                    "elementOptions": list(spec.get("elementOptions") or ()),
                    "effectsSpec": fx_list,
                    "summaryZh": " / ".join(summary_parts),
                })

        # Equipped weapon-affecting augments
        for aug in augment_specs:
            if not isinstance(aug, Mapping):
                continue
            mod_path = str(aug.get("modPath") or "")
            mod_entry = mod_by_path.get(_path_token(mod_path))
            if mod_entry is None:
                continue
            mod_row, mod_rank = mod_entry
            target_ability_path = str(aug.get("abilityPath") or "")
            if target_ability_path == "PASSIVE":
                slot_idx = None
                slot_strength = float(final_panel["abilityStrength"])
                icon_asset = mod_row.get("iconAsset") or mod_row.get("art")
            else:
                atoken = _path_token(target_ability_path)
                if atoken not in slot_by_ability_path:
                    continue
                slot_idx = slot_by_ability_path[atoken]
                slot_strength = float(final_panel["abilityFourStrength"] if slot_idx == 3 else final_panel["abilityStrength"])
                icon_asset = mod_row.get("iconAsset") or mod_row.get("art") or icon_by_ability_path.get(atoken)

            duration = float(final_panel["abilityDuration"])
            fx_list = []
            summary_parts = []
            for fx in (aug.get("effects") or ()):
                if not isinstance(fx, Mapping):
                    continue
                rvals = fx.get("rankValues") or ()
                base_val = float(rvals[min(mod_rank, len(rvals) - 1)]) if rvals else float(_number(fx.get("base")) or 0.0)
                scale_kind = str(fx.get("scale") or "none").casefold()
                factor = slot_strength if scale_kind == "strength" else (duration if scale_kind == "duration" else 1.0)
                resolved = round(base_val * factor, 6)
                fx_entry = {
                    "upgradeType": fx.get("upgradeType"),
                    "operation": fx.get("operation") or "STACKING_MULTIPLY",
                    "base": round(base_val, 6),
                    "value": resolved,
                    "scale": scale_kind,
                    "labelZh": fx.get("labelZh"),
                }
                if fx.get("perMeterRankValues"):
                    pm_vals = fx["perMeterRankValues"]
                    pm_base = float(pm_vals[min(mod_rank, len(pm_vals) - 1)])
                    pm_scale = str(fx.get("perMeterScale") or "none").casefold()
                    pm_factor = slot_strength if pm_scale == "strength" else 1.0
                    fx_entry["perMeterValue"] = round(pm_base * pm_factor, 6)
                for opt_key in ("damageType", "validTypes", "forcedProc"):
                    if fx.get(opt_key) is not None:
                        fx_entry[opt_key] = fx.get(opt_key)
                fx_list.append(fx_entry)
                label_zh = str(fx.get("labelZh") or fx.get("upgradeType") or "")
                summary_parts.append(f"{label_zh} +{_fmt_pct(resolved)}%")

            out.append({
                "id": str(aug.get("id")),
                "abilityPath": None if target_ability_path == "PASSIVE" else target_ability_path,
                "modPath": mod_path,
                "slot": slot_idx,
                "isHelminth": slot_idx is not None and helminth_slot is not None and slot_idx == helminth_slot,
                "isAugment": True,
                "rank": mod_rank,
                "maxRank": int(mod_row.get("maxRank") or 0),
                "nameEn": aug.get("nameEn") or mod_row.get("nameEn"),
                "nameZh": aug.get("nameZh") or mod_row.get("nameZh"),
                "iconAsset": icon_asset,
                "defaultActive": bool(aug.get("defaultActive", True)),
                "requiresElementChoice": bool(aug.get("requiresElementChoice", False)),
                "elementOptions": list(aug.get("elementOptions") or ()),
                "effectsSpec": fx_list,
                "summaryZh": " / ".join(summary_parts),
            })

        return out


__all__ = [
    "WarframeEngine",
    "load_warframe_catalog",
    "load_alternate_forms",
    "apply_helminth_altered",
    "DEFAULT_CAPACITY",
    "NORMAL_SLOT_COUNT",
    "ARCANE_SLOT_COUNT",
    "SHARD_SLOT_COUNT",
    "ABILITY_SLOT_COUNT",
]
