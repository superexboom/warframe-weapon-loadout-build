"""Turn the flattened Packages.bin dump into compact, self-contained datasets.

Only what a build/damage simulator needs is kept: player weapons, warframes, mods,
Arcanes, and enemy defences. Everything else (recipes, cosmetics, drop tables, world
state) is left to the public APIs that already serve it well.

Entry point is :func:`export_all`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from wfarsenal import packages
from wfarsenal.damage import (
    SUPPORTED_OPERATIONS,
    SUPPORTED_SCENARIO_MODIFIERS,
    SUPPORTED_WEAPON_UPGRADE_TYPES,
)
from wfarsenal.localization import (
    LocalizationCatalog,
    apply_localizations,
    normalize_catalogs,
    normalize_language_key,
)
from wfarsenal.packages import PackageIndex
from wfarsenal.runtime_adapters import resolve_projectile_runtime_adapters

# Preserve the core export's four-stat support contract; the full frame engine
# consumes the richer generated sidecar independently.
SUPPORTED_WARFRAME_UPGRADE_TYPES = frozenset({
    "AVATAR_ABILITY_STRENGTH", "AVATAR_ABILITY_DURATION",
    "AVATAR_ABILITY_RANGE", "AVATAR_ABILITY_EFFICIENCY",
})

SCHEMA_VERSION = 3

# StoreItems is the authoritative list of what a player can actually own and equip;
# scanning /Lotus/Weapons directly also picks up NPC and prop variants.
WEAPON_CATEGORIES = {
    "LongGuns": "primary",
    "Pistols": "secondary",
    "Melee": "melee",
    "SpaceGuns": "arch_gun",
    "SpaceMelee": "arch_melee",
    "SentinelWeapons": "companion",
    "OperatorAmps": "amp",
}
SUIT_CATEGORIES = {"Suits": "warframe", "MechSuits": "necramech"}

# Physical/elemental damage keys as they appear in AttackData and DamagePercent blocks.
DAMAGE_TYPES = (
    "DT_IMPACT",
    "DT_PUNCTURE",
    "DT_SLASH",
    "DT_FIRE",
    "DT_FREEZE",
    "DT_ELECTRICITY",
    "DT_POISON",
    "DT_EXPLOSION",
    "DT_RADIATION",
    "DT_GAS",
    "DT_MAGNETIC",
    "DT_VIRAL",
    "DT_CORROSIVE",
    "DT_RADIANT",
    "DT_SENTIENT",
    "DT_CINEMATIC",
    "DT_SHIELD_DRAIN",
    "DT_HEALTH_DRAIN",
    "DT_ENERGY_DRAIN",
    "DT_FINISHER",
)

# Rank count comes from FusionLimit, not rarity: Serration is UNCOMMON but ranks to 10,
# while plenty of RARE cards stop at 3. Both scales are the same QA_* enum with
# different numbers behind each name, calibrated against 1334 mods of known
# BaseDrain/MaxRank in the community wiki table.
MAX_RANK_BY_FUSION_LIMIT = {
    "QA_VERY_HIGH": 10,
    "QA_HIGH": 5,
    "QA_MEDIUM": 3,
    "QA_LOW": 0,
    "QA_NONE": 0,
}
DRAIN_BY_ENUM = {
    "QA_VERY_HIGH": 10,
    "QA_HIGH": 6,
    "QA_MEDIUM": 4,
    "QA_LOW": 2,
    "QA_NONE": 0,
}
# Neither field is always present. When absent, stances cap at rank 3 where every other
# card caps at 5, and drain magnitude falls back to 2.
DEFAULT_MAX_RANK = 5
STANCE_MAX_RANK = 3
DEFAULT_ABSENT_DRAIN = 2


def export_all(
    build_dir: str | Path,
    out_dir: str | Path,
    *,
    catalogs: Mapping[str, LocalizationCatalog] | None = None,
) -> dict[str, int]:
    """Write the four datasets for one build and return per-file record counts.

    Localization is optional. When catalogs are supplied, localized display names are
    added alongside the legacy internal ``name`` field; callers that omit catalogs get
    the previous record shape.
    """
    build_dir = Path(build_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalogs = normalize_catalogs(catalogs or {})

    index = packages.load(build_dir)
    store = _collect_store_items(index)

    datasets = {
        "weapons": extract_weapons(index, store),
        "warframes": extract_warframes(index, store),
        "mods": extract_mods(index),
        "arcanes": extract_arcanes(index, store),
        "enemies": extract_enemies(index),
    }
    if catalogs:
        datasets = {
            name: [apply_localizations(record, catalogs) for record in records]
            for name, records in datasets.items()
        }

    build_label = build_dir.name
    provenance = _export_provenance(build_dir, catalogs)
    counts: dict[str, int] = {}
    for name, records in datasets.items():
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "buildLabel": build_label,
            "count": len(records),
            "provenance": provenance,
            "data": records,
        }
        path = out_dir / f"{name}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1, sort_keys=True)
        counts[name] = len(records)

    # Keep wall-clock metadata out of the four deterministic datasets. The manifest is
    # operational metadata and may change between otherwise byte-identical exports.
    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "buildLabel": build_label,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "counts": counts,
        "provenance": provenance,
    }
    with (out_dir / "manifest.json").open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1, sort_keys=True)

    return counts


# -- store item index ----------------------------------------------------------------


def _collect_store_items(index: PackageIndex) -> dict[str, dict[str, Any]]:
    """Map ``TypeName`` to its StoreItem attributes.

    StoreItems carry the player-facing metadata (category, market visibility, mastery
    requirement) that the underlying type object lacks.
    """
    by_type: dict[str, dict[str, Any]] = {}
    for path in index.iter_paths("Lotus/StoreItems"):
        obj = index.resolve(path)
        type_name = obj.get("TypeName")
        if not isinstance(type_name, str) or not type_name:
            continue
        # Prefer the first entry seen; duplicates are skins/bundles pointing at the
        # same underlying type.
        by_type.setdefault(packages.normalize(type_name), obj)
    return by_type


# -- weapons -------------------------------------------------------------------------


def extract_weapons(
    index: PackageIndex, store: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract every player-equippable weapon with its stats inlined."""
    records = []
    for type_name, item in store.items():
        weapon = index.resolve(type_name)
        if not weapon:
            continue
        category = item.get("ProductCategory") or weapon.get("ProductCategory", "")
        slot = WEAPON_CATEGORIES.get(category)
        if not slot:
            continue
        records.append(_build_weapon(index, type_name, slot, item, weapon))
    records.sort(key=lambda r: r["path"])
    return records


def _build_weapon(
    index: PackageIndex,
    path: str,
    slot: str,
    item: dict[str, Any],
    weapon: dict[str, Any],
) -> dict[str, Any]:
    modes = _extract_fire_modes(index, path, weapon)
    # Archguns (SpaceGuns) carry two parallel behaviour sets: ``Behaviors`` is
    # the Archwing/space loadout while ``HeavyBehaviors`` is the ground "Heavy
    # Weapon" loadout players actually use in atmosphere.  Ground data is the
    # only surface this catalog serves, so export those modes instead of the
    # space ones and record which set produced them.
    ground_source: str | None = None
    if slot == "arch_gun":
        ground = _extract_archgun_ground_modes(index, path, weapon)
        if ground:
            modes, ground_source = ground
    incarnon = _extract_incarnon_evolutions(index, path, weapon)
    if incarnon:
        behavior_source = ground_source or 'Behaviors'
        behavior_rows = weapon.get(behavior_source) or []
        for mode in modes:
            position = mode.get('index')
            entry = behavior_rows[position] if isinstance(position,int) and position < len(behavior_rows) else {}
            fire = _sub_behaviour(entry, 'fire:') or {}
            mode['isIncarnonForm'] = bool(fire.get('ConsumesChargesForFire'))
    variant_type = item.get("VariantType") or weapon.get("VariantType")
    record = {
        "path": path,
        "ancestry": index.ancestry(path),
        "name": _basename(path),
        "slot": slot,
        "productCategory": item.get("ProductCategory") or weapon.get("ProductCategory"),
        "nameTag": weapon.get("LocalizeTag") or item.get("LocalizeTag"),
        "descTag": weapon.get("LocalizeDescTag") or item.get("LocalizeDescTag"),
        "masteryReq": item.get("RequiredLevel", 0),
        "maxRank": weapon.get("LevelCap") or item.get("LevelCap") or 30,
        "polarities": weapon.get("ArtifactSlots") or [],
        "gripType": weapon.get("GripType") or item.get("GripType"),
        "omegaAttenuation": weapon.get("OmegaAttenuation"),
        # Modular Kitguns expose a separate primary-slot disposition on the
        # component record. Keep it alongside the historical field so callers
        # can choose the slot without guessing from names.
        "primaryOmegaAttenuation": (
            weapon.get("PrimaryOmegaAttenuation")
            if weapon.get("PrimaryOmegaAttenuation") is not None
            else weapon.get("PrimeOmegaAttenuation")
        ),
        "magazineSize": (
            weapon.get("HeavyAmmoClipSize") or weapon.get("AmmoClipSize")
            if slot == "arch_gun"
            # An unserialized clip is the engine default (damage.NATIVE_DEFAULT_CLIP).
            else weapon.get("AmmoClipSize", 6 if slot in ("primary", "secondary") else None)
        ),
        "defaultModTemplate": weapon.get("DefaultModTemplate"),
        "compatTags": weapon.get("CompatibilityTags") or [],
        "variantType": variant_type,
        "isIncarnon": bool(incarnon),
        "fireModes": modes,
    }
    if slot == "arch_gun":
        # Reserve-ammo pool for the ground (Heavy Weapon) loadout.  The engine
        # stores it only on the weapon root, not on any behaviour, so surface it
        # next to the magazine size the way the in-game panel shows both.
        record["ammoMax"] = weapon.get("HeavyAmmoCapacity")
        if ground_source:
            record["fireModeSource"] = ground_source
    if slot in {"melee", "arch_melee"}:
        heavy = _extract_heavy_attack(index, path, weapon, modes)
        if heavy:
            record["heavyAttack"] = heavy
    if incarnon:
        record["incarnon"] = incarnon
    innate = _extract_innate_elements(
        index, path, weapon, variant_type=variant_type
    )
    # Keep the legacy shape byte-for-byte for ordinary weapons.  Variant weapons
    # with an account-selected element still get explicit candidates when the
    # package cannot carry the selected value.
    record.update(innate)
    return record


ARCHGUN_GROUND_MODE_PREFIX = "Heavy"


def _extract_archgun_ground_modes(
    index: PackageIndex, weapon_path: str, weapon: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], str] | None:
    """Extract an archgun's GROUND (Heavy Weapon) fire modes.

    Returns ``(modes, source_label)`` or ``None`` when neither behaviour list
    yields a usable mode.  ``HeavyBehaviors`` is the authoritative ground set;
    a few entries fall back to the shared ``Behaviors`` list when the ground
    override only changes ammo/reload and reuses the space fire logic.

    Modes mirror :func:`_extract_fire_modes` output with one ground-specific
    filter: behaviour entries with no ammo cost and no trigger tag are the
    weapon's animation/dry-fire click (generic ``WeaponStateBehavior``), not a
    real attack, and are dropped so the catalog never offers a damage-less
    default mode.  Genuine zero-ammo alternate fires (Mausolon's charged shot)
    carry a trigger tag and survive the filter.
    """
    for field, label in (("HeavyBehaviors", "HeavyBehaviors"), ("Behaviors", "Behaviors")):
        behaviours = weapon.get(field)
        if not isinstance(behaviours, list):
            continue
        modes = _flatten_behaviours(index, weapon_path, behaviours)
        modes = [mode for mode in modes if mode.get("ammoCost") or mode.get("trigger")]
        if any((mode.get("damage") or {}).get("types") for mode in modes):
            return modes, label
    return None


def _flatten_behaviours(
    index: PackageIndex, weapon_path: str, behaviours: list[Any]
) -> list[dict[str, Any]]:
    """Flatten one ``Behaviors``-shaped list into compact fire modes.

    Shared by the ordinary (space) extraction and the archgun ground extraction
    so both emit the identical mode schema.
    """
    modes = []
    for position, entry in enumerate(behaviours):
        if not isinstance(entry, dict):
            continue
        fire = _sub_behaviour(entry, "fire:")
        state = _sub_behaviour(entry, "state:")
        impact = _sub_behaviour(entry, "impact:")
        if fire is None and state is None:
            continue

        mode: dict[str, Any] = {"index": position}
        if (entry.get('fire:Type') == '/EE/Types/Game/WeaponMeleeRadiusFireBehavior'
                and entry.get('state:Type') == '/EE/Types/Game/WeaponMeleeRadiusStateBehavior'):
            mode['behaviorKind'] = 'auxiliary-melee'

        if state:
            mode["trigger"] = state.get("LocTag")
            mode["fireRate"] = _per_second(state.get("fireRate"))
            mode["fireRateRaw"] = state.get("fireRate")
            mode["reloadTime"] = state.get("reloadTime")
            mode["isAlternateFire"] = bool(state.get("IsAlternateFire"))
            # ── F16/pipelineGaps[chargetime-case-bug]（审计修复）──────────
            # 原始字段拼写是 ChargeTime（大写 C）；旧代码读 chargeTime，
            # 全部蓄力武器的 compact 导出 chargeTime=null。
            mode["chargeTime"] = state.get("ChargeTime", state.get("chargeTime"))
        if fire:
            charged = fire.get('chargedProjectileType')
            if isinstance(charged,str) and charged:
                fire = {**fire,'projectileType':charged}
                mode['chargedProjectile'] = True
            mode["multishot"] = fire.get("fireIterations", 1)
            mode["ammoCost"] = fire.get("ammoRequirement")
            mode["ammoType"] = fire.get("ammoType")
        projectile_name=(fire or {}).get('projectileType')
        charge_delegate=(not projectile_name or bool(_resolve_weapon_reference(index,weapon_path,projectile_name)[1].get('DealDamageThroughImpactBehavior')))
        if (state and mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerCharge' and charge_delegate
                and isinstance(state.get('DamageMultiplier'),(int,float)) and state['DamageMultiplier']>1):
            mode['chargeDamageMultiplier']=state['DamageMultiplier']
        mode["damage"] = _resolve_damage(
            index, weapon_path, fire or {}, impact or {}
        )
        projectile_layer = _extract_projectile_events(
            index, weapon_path, fire or {}
        )
        if projectile_layer:
            mode.update(projectile_layer)
            # Sequence weapons such as Arbucep intentionally leave projectileType
            # empty. Keep the historical per-iteration damage contract usable while
            # the event layer carries every individual projectile and explosion.
            if mode["damage"] is None:
                mode["damage"] = _sequence_average_damage(
                    projectile_layer["projectileEvents"],
                    int(fire.get("fireIterations") or 1) if fire else 1,
                )

        if impact:
            # Hitscan weapons lose damage past a range band; projectiles do not.
            falloff = impact.get("damageFallOff")
            if isinstance(falloff, list) and falloff:
                mode["falloffRange"] = falloff
                mode["falloffMinDamage"] = impact.get("damageFallOffMinDamage")
            if impact.get("tracePunctureDepth") is not None:
                mode["puncture"] = impact.get("tracePunctureDepth")

        modes.append(mode)
    return modes


def _extract_incarnon_evolutions(
    index: PackageIndex, weapon_path: str, weapon: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Export selectable Incarnon branches without pretending scripts are static."""
    evolutions = weapon.get("Evolutions")
    if not isinstance(evolutions, list) or not evolutions:
        return None

    tiers: list[dict[str, Any]] = []
    for tier_number, evolution in enumerate(evolutions, start=1):
        if not isinstance(evolution, Mapping):
            continue
        powerups = evolution.get("Powerups")
        if not isinstance(powerups, list):
            powerups = []
        branches = [
            _build_incarnon_branch(
                index, weapon_path, tier_number, branch_number, powerup
            )
            for branch_number, powerup in enumerate(powerups, start=1)
            if isinstance(powerup, Mapping)
        ]
        tiers.append(
            {
                "tier": tier_number,
                "challenge": evolution.get("Challenge"),
                "complication": evolution.get("Complication"),
                "selectable": len(branches) > 1,
                "branches": branches,
            }
        )
    return {"adapter": weapon.get("EvolutionReq"), "tiers": tiers}


def _build_incarnon_branch(
    index: PackageIndex,
    weapon_path: str,
    tier_number: int,
    branch_number: int,
    powerup: Mapping[str, Any],
) -> dict[str, Any]:
    references = _string_list(powerup.get("Upgrades"))
    sources: list[dict[str, Any]] = []
    effects: list[dict[str, Any]] = []
    conditional_effects: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    runtime_scripts: list[dict[str, Any]] = []

    for reference in references:
        resolved, obj = _resolve_weapon_reference(index, weapon_path, reference)
        if not obj:
            unresolved.append(
                {
                    "field": "Upgrades",
                    "value": reference,
                    "resolvedPath": resolved,
                    "reason": "notFound",
                }
            )
            continue

        source_effects = [
            {**_build_effect(upgrade), "sourcePath": resolved}
            for upgrade in obj.get("Upgrades") or ()
            if isinstance(upgrade, dict)
        ]
        # ── SubUpgrades（灵化进化子词条）提取修复 ───────────────────────
        # 主进化文件（如 BoltorEvoTier1B）通过 SubUpgrades: ["...SubMod"]
        # 挂接条件性子词条（「装填前每秒 +2 伤害」「弹药效率」等）。旧导出
        # 只遍历 Upgrades——子词条全部丢失，UI 描述不完整、模拟器少算
        # 词条。SubMod 带条件元数据（UpgradeChance/UpgradeDuration/
        # MaxConditionalStacks），一并导出供模拟器按事件语义处理。
        for sub_ref in _string_list(obj.get("SubUpgrades")):
            sub_resolved, sub_obj = _resolve_weapon_reference(
                index, resolved, sub_ref
            )
            if not sub_obj:
                unresolved.append(
                    {
                        "field": "SubUpgrades",
                        "value": sub_ref,
                        "resolvedPath": sub_resolved,
                        "reason": "notFound",
                    }
                )
                continue
            sub_effects = [
                {
                    **_build_effect(upgrade),
                    "sourcePath": sub_resolved,
                    "isSubUpgrade": True,
                    **(
                        {
                            key: sub_obj[key]
                            for key in (
                                "UpgradeChance",
                                "UpgradeDuration",
                                "MaxConditionalStacks",
                            )
                            if key in sub_obj
                        }
                    ),
                }
                for upgrade in sub_obj.get("Upgrades") or ()
                if isinstance(upgrade, dict)
            ]
            source_effects.extend(sub_effects)
            sub_scripts = _runtime_scripts(sub_obj)
            if sub_scripts:
                runtime_scripts.append({"sourcePath": sub_resolved, **sub_scripts})
        # ─────────────────────────────────────────────────────────────
        source_conditionals, source_unresolved = _conditional_effects(
            index, resolved, obj
        )
        scripts = _runtime_scripts(obj)
        effects.extend(source_effects)
        conditional_effects.extend(source_conditionals)
        unresolved.extend(source_unresolved)
        if scripts:
            runtime_scripts.append({"sourcePath": resolved, **scripts})

        source: dict[str, Any] = {
            "path": resolved,
            "nameTag": obj.get("LocalizeTag"),
            "descTag": obj.get("LocalizeDescTag"),
            "icon": obj.get("Icon"),
        }
        if source_effects:
            source["effects"] = source_effects
        if source_conditionals:
            source["conditionalEffects"] = source_conditionals
        if scripts:
            source["runtimeScripts"] = scripts
        if source_unresolved:
            source["unresolvedReferences"] = source_unresolved
        sources.append(source)

    unsupported_effects = [
        effect
        for effect in effects
        if "weapon" not in effect.get("supportedBy", ())
    ]
    complete = not (
        unsupported_effects
        or conditional_effects
        or runtime_scripts
        or unresolved
        or not sources
    )
    first = sources[0] if sources else {}
    branch: dict[str, Any] = {
        "id": f"{tier_number}-{branch_number}",
        "index": branch_number,
        "path": first.get("path"),
        "nameTag": first.get("nameTag"),
        "descTag": first.get("descTag"),
        "upgradePaths": [source["path"] for source in sources],
        "effects": effects,
        "conditionalEffects": conditional_effects,
        "runtimeScripts": runtime_scripts,
        "unresolvedReferences": unresolved,
        "support": {
            "complete": complete,
            "staticEffects": len(effects) - len(unsupported_effects),
            "unsupportedEffects": len(unsupported_effects),
        },
        "sources": sources,
    }
    return branch


_INNATE_UPGRADE_TYPE = "WEAPON_PERCENT_BASE_INNATE_DAMAGE_ADDED"
_INNATE_CANDIDATE_TAGS = {
    "InnateElectricityDamage": "DT_ELECTRICITY",
    "InnateFreezeDamage": "DT_FREEZE",
    "InnateHeatDamage": "DT_FIRE",
    "InnateImpactDamage": "DT_IMPACT",
    "InnateMagDamage": "DT_MAGNETIC",
    "InnateRadDamage": "DT_RADIATION",
    "InnateToxinDamage": "DT_POISON",
}
_BASE_INNATE_TYPES = ("DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON")
_RANDOM_INNATE_TYPES = (
    "DT_ELECTRICITY",
    "DT_FIRE",
    "DT_FREEZE",
    "DT_IMPACT",
    "DT_MAGNETIC",
    "DT_POISON",
    "DT_RADIATION",
)
_TENET_RANDOM_INNATE_PATHS = {
    "/Lotus/Weapons/Corpus/LongGuns/CrpBriefcaseLauncher/CrpBriefcaseLauncher",
    "/Lotus/Weapons/Corpus/Pistols/CrpBriefcaseAkimbo/CrpBriefcaseAkimboPistol",
    "/Lotus/Weapons/Corpus/Pistols/CrpIgniterPistol/CrpIgniterPistol",
}
_LEGACY_KUVA_RANDOM_INNATE_PATHS = {
    "/Lotus/Weapons/Grineer/Bows/GrnBow/GrnBowWeapon",
    "/Lotus/Weapons/Grineer/HeavyWeapons/GrnHeavyGrenadeLauncher",
    "/Lotus/Weapons/Grineer/LongGuns/GrnKuvaLichRifle/GrnKuvaLichRifleWeapon",
    "/Lotus/Weapons/Grineer/Melee/GrnKuvaLichScythe/GrnKuvaLichScytheWeapon",
}


def _extract_innate_elements(
    index: PackageIndex,
    weapon_path: str,
    weapon: Mapping[str, Any],
    *,
    variant_type: str | None = None,
) -> dict[str, Any]:
    """Extract concrete innate damage and unresolved runtime candidates.

    Kuva/Coda random buffs are selected on an owned item, not in Packages.bin.  Do
    not invent one: export the possible damage types and let the simulator fail
    closed until an account/loadout snapshot supplies ``innateElements``.
    """
    refs: list[tuple[str, dict[str, Any]]] = []
    for reference in _string_list(weapon.get("DefaultUpgrades")):
        resolved, obj = _resolve_weapon_reference(index, weapon_path, reference)
        if obj:
            refs.append((resolved, obj))
    candidates: set[str] = set()
    sources: list[dict[str, Any]] = []
    elements: list[dict[str, Any]] = []

    # Valence weapons select the element on the owned weapon.  Most Tenet guns
    # only expose VT_KUVA; older records expose neither the shared slotted upgrade
    # nor that variant flag, so retain their explicit package paths.
    random_innate_family = (
        "/kuvalich/" in weapon_path.lower()
        or variant_type == "VT_KUVA"
        or weapon_path in _TENET_RANDOM_INNATE_PATHS
        or weapon_path in _LEGACY_KUVA_RANDOM_INNATE_PATHS
    )
    if random_innate_family:
        candidates.update(_RANDOM_INNATE_TYPES)

    slotted = weapon.get("DefaultSlottedUpgrades")
    if isinstance(slotted, list):
        for slot in slotted:
            if not isinstance(slot, Mapping):
                continue
            item_type = slot.get("ItemType")
            if isinstance(item_type, str) and item_type:
                resolved, obj = _resolve_weapon_reference(index, weapon_path, item_type)
                if obj:
                    refs.append((resolved, obj))
            tags = slot.get("RandomUpgradeBuffTags")
            for tag in _string_list(tags):
                damage_type = _INNATE_CANDIDATE_TAGS.get(tag)
                if damage_type:
                    candidates.add(damage_type)
            if tags:
                sources.append(
                    {
                        "path": item_type if isinstance(item_type, str) else None,
                        "kind": "random-upgrade",
                        "tags": [tag for tag in _string_list(tags) if tag],
                    }
                )

    for source_path, source in refs:
        # The shared Kuva/Tenet/Coda random card contains one upgrade for every
        # possible element.  Those are candidates, not simultaneous damage; the
        # owned weapon's valence record is required to select exactly one.
        random_source = "InnateDamageRandomMod" in source_path or bool(
            source.get("UpgradeEntries")
        )
        if random_source:
            for entry in source.get("UpgradeEntries") or ():
                if not isinstance(entry, Mapping):
                    continue
                damage_type = _INNATE_CANDIDATE_TAGS.get(entry.get("Tag"))
                if damage_type:
                    candidates.add(damage_type)
            continue
        for upgrade in _iter_upgrade_dicts(source):
            if upgrade.get("UpgradeType") != _INNATE_UPGRADE_TYPE:
                continue
            damage_type = upgrade.get("DamageType")
            value = upgrade.get("Value")
            if (
                isinstance(damage_type, str)
                and damage_type != "DT_ANY"
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                elements.append(
                    {
                        "damageType": damage_type,
                        "value": float(value),
                        "source": source_path,
                    }
                )
            elif isinstance(damage_type, str) and damage_type != "DT_ANY":
                candidates.add(damage_type)

        # RandomUpgradeBuffTags can live on the referenced random upgrade object.
        for entry in source.get("UpgradeEntries") or ():
            if not isinstance(entry, Mapping):
                continue
            tag = entry.get("Tag")
            damage_type = _INNATE_CANDIDATE_TAGS.get(tag)
            if damage_type:
                candidates.add(damage_type)

    # Keep the synthetic family provenance only when Packages.bin did not expose
    # an explicit random-upgrade source.  Existing Tenet/Kuva records already carry
    # that source through DefaultSlottedUpgrades; appending another one needlessly
    # changes otherwise identical exports.
    if random_innate_family and not any(
        source.get("path")
        == "/Lotus/Weapons/Grineer/KuvaLich/Upgrades/InnateDamageRandomMod"
        for source in sources
    ):
        sources.append(
            {
                "path": "/Lotus/Weapons/Grineer/KuvaLich/Upgrades/InnateDamageRandomMod",
                "kind": "random-upgrade",
                "tags": list(_RANDOM_INNATE_TYPES),
            }
        )

    result: dict[str, Any] = {}
    if elements:
        result["innateElements"] = elements
    if candidates:
        result["innateElementCandidates"] = sorted(candidates)
    if sources:
        result["innateElementSources"] = sources
    return result


def _resolve_weapon_reference(
    index: PackageIndex, owner_path: str, reference: str
) -> tuple[str, dict[str, Any]]:
    """Resolve a DefaultUpgrades/DefaultSlottedUpgrades reference."""
    if reference.startswith("/"):
        resolved = packages.normalize(reference)
        return resolved, index.resolve(resolved)
    owner = packages.normalize(owner_path)
    candidates = [
        packages.normalize(str(PurePosixPath(path).parent / reference))
        for path in index.ancestry(owner)
    ]
    for resolved in dict.fromkeys(candidates):
        obj = index.resolve(resolved)
        if obj:
            return resolved, obj
    return candidates[0], {}


def _iter_upgrade_dicts(value: Any) -> Iterable[dict[str, Any]]:
    """Yield nested upgrade records without interpreting unrelated fields."""
    if isinstance(value, Mapping):
        if isinstance(value.get("UpgradeType"), str):
            yield dict(value)
        for child in value.values():
            yield from _iter_upgrade_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_upgrade_dicts(child)


def _extract_fire_modes(
    index: PackageIndex, weapon_path: str, weapon: dict[str, Any]
) -> list[dict[str, Any]]:
    """Flatten each Behaviors entry into one fire mode with damage resolved.

    A behaviour entry bundles several sub-behaviours under namespaced keys
    (``fire:``, ``state:``, ``impact:``). Timing lives on the state behaviour while
    damage lives either inline on the fire behaviour or on a referenced projectile.
    """
    behaviours = weapon.get("Behaviors")
    if not isinstance(behaviours, list):
        return []
    return _flatten_behaviours(index, weapon_path, behaviours)


def _sub_behaviour(entry: dict[str, Any], prefix: str) -> dict[str, Any] | None:
    """Return the payload of the ``prefix``-namespaced sub-behaviour, if present.

    Keys look like ``fire:Type`` (the class path) alongside
    ``fire:WeaponProjectileFireBehavior`` (the attributes). The class name varies by
    weapon, so match on the prefix and take the dict value.
    """
    for key, value in entry.items():
        if key.startswith(prefix) and key != f"{prefix}Type" and isinstance(value, dict):
            return value
    return None


def _extract_heavy_attack(
    index: PackageIndex,
    weapon_path: str,
    weapon: Mapping[str, Any],
    modes: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Export the default ground-heavy route and its direct-damage components."""
    tree_ref = weapon.get("MeleeTreeType")
    if not isinstance(tree_ref, str) or not tree_ref:
        return None
    tree_path, tree = _resolve_weapon_reference(index, weapon_path, tree_ref)
    equipped = tree.get("EquippedAttackSets") if tree else None
    attack_set_ref = (
        equipped.get("CC_GROUND_HEAVY") if isinstance(equipped, Mapping) else None
    )
    if not isinstance(attack_set_ref, str) or not attack_set_ref:
        return None
    attack_set_path, attack_set = _resolve_weapon_reference(
        index, tree_path, attack_set_ref
    )
    if not attack_set:
        return None

    attacks: list[dict[str, Any]] = []
    for attack_ref in attack_set.get("Attacks") or ():
        if not isinstance(attack_ref, str) or not attack_ref:
            continue
        attack_path, attack = _resolve_weapon_reference(
            index, attack_set_path, attack_ref
        )
        if not attack:
            continue
        properties = _heavy_properties(attack.get("AttackProperties"))
        per_swing = []
        for position, raw in enumerate(attack.get("PerSwingOverrides") or (), start=1):
            if not isinstance(raw, Mapping):
                continue
            per_swing.append(
                {
                    "index": position,
                    "override": bool(raw.get("overrideAttackProperties")),
                    "properties": _heavy_properties(raw.get("attackProperties")),
                }
            )
        attacks.append(
            {
                "path": attack_path,
                "action": attack.get("AttackAction"),
                "extraAction": attack.get("ExtraAction"),
                "properties": properties,
                "perSwing": per_swing,
            }
        )

    state = next(
        (
            value
            for entry in weapon.get("Behaviors") or ()
            if isinstance(entry, Mapping)
            for key, value in entry.items()
            if key.startswith("state:")
            and key != "state:Type"
            and isinstance(value, Mapping)
            and isinstance(value.get("ComboData"), Mapping)
        ),
        {},
    )
    combo = state.get("ComboData") if isinstance(state, Mapping) else {}
    result: dict[str, Any] = {
        "comboContext": "CC_GROUND_HEAVY",
        "meleeTree": tree_path,
        "attackSet": attack_set_path,
        "defaultAttackIndex": 0,
        "chargeTime": combo.get("HeavyMeleeChargeTime")
        if isinstance(combo, Mapping)
        else None,
        "chargeDuration": state.get("ChargeDuration")
        if isinstance(state, Mapping)
        else None,
        "tapTime": state.get("TapTime") if isinstance(state, Mapping) else None,
        "disableTime": state.get("MeleeDisableTime")
        if isinstance(state, Mapping)
        else None,
        "timingSource": "ComboData.HeavyMeleeChargeTime",
        "timingApproximation": True,
        "attacks": attacks,
    }

    recall = _heavy_recall_variants(index, weapon_path, weapon)
    if recall:
        result["kind"] = "projectileRecall"
        result["variants"] = recall
        selected = next(
            (variant for variant in recall if variant["id"] == "turbo"), recall[0]
        )
        result["defaultVariant"] = selected["id"]
        result["components"] = selected["components"]
    else:
        projectile = _heavy_projectile_components(index, weapon_path, weapon, attacks)
        if projectile:
            result["kind"] = "projectile"
            result["components"] = projectile
        else:
            base_damage = modes[0].get("damage") if modes else None
            components = _heavy_melee_components(base_damage, attacks)
            result["kind"] = "melee"
            result["components"] = components

    components = result.get("components") or []
    partial = result.get("kind") == "projectileRecall"
    result["support"] = {
        "complete": bool(attacks and components) and not partial,
        "level": (
            "partial"
            if partial
            else ("complete" if attacks and components else "unsupported")
        ),
        "singleDamage": bool(components),
        "timing": "charge-and-disable" if result.get("chargeTime") is not None else "unavailable",
    }
    return result


def _heavy_properties(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    result: dict[str, Any] = {}
    for source, target in (
        ("BaseDamageAtten", "baseDamageMultiplier"),
        ("ProcChanceAtten", "procChanceMultiplier"),
        ("ComboHitsToAdd", "comboHits"),
        ("Slam", "slam"),
    ):
        if raw.get(source) is not None:
            result[target] = raw[source]
    if isinstance(raw.get("DamagePctAtten"), Mapping):
        result["damageTypeMultipliers"] = {
            key: value
            for key, value in raw["DamagePctAtten"].items()
            if key in DAMAGE_TYPES and isinstance(value, (int, float))
        }
    if raw.get("ExtraProcs"):
        result["forcedProcs"] = raw["ExtraProcs"]
    return result


def _heavy_melee_components(
    base_damage: Any, attacks: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    if not isinstance(base_damage, Mapping) or not base_damage.get("types") or not attacks:
        return []
    attack = attacks[0]
    top = attack.get("properties")
    top = top if isinstance(top, Mapping) else {}
    swings = attack.get("perSwing")
    swings = swings if isinstance(swings, list) and swings else [None]
    components = []
    for position, raw in enumerate(swings, start=1):
        override = isinstance(raw, Mapping) and bool(raw.get("override"))
        child = raw.get("properties") if isinstance(raw, Mapping) else None
        properties = child if override and isinstance(child, Mapping) else top
        components.append(
            _scaled_heavy_component(
                base_damage,
                properties,
                component_id=f"attack-1-swing-{position}",
                kind="melee",
                source=attack.get("AttackAction"),
            )
        )
    return components


def _scaled_heavy_component(
    damage: Mapping[str, Any],
    properties: Mapping[str, Any],
    *,
    component_id: str,
    kind: str,
    source: Any,
    count: int | float = 1,
) -> dict[str, Any]:
    multiplier_value = _first_number(
        dict(properties), "BaseDamageAtten", "baseDamageMultiplier"
    )
    multiplier = 1.0 if multiplier_value is None else multiplier_value
    type_multipliers = properties.get("DamagePctAtten") or properties.get(
        "damageTypeMultipliers"
    )
    type_multipliers = type_multipliers if isinstance(type_multipliers, Mapping) else {}
    types = {
        damage_type: float(amount)
        * multiplier
        * float(type_multipliers.get(damage_type, 1.0))
        for damage_type, amount in (damage.get("types") or {}).items()
        if isinstance(amount, (int, float))
    }
    total = sum(types.values())
    proc_multiplier_value = _first_number(
        dict(properties), "ProcChanceAtten", "procChanceMultiplier"
    )
    proc_multiplier = 1.0 if proc_multiplier_value is None else proc_multiplier_value
    block = {
        "total": total,
        "types": types,
        "shares": {
            damage_type: value / total for damage_type, value in types.items()
        }
        if total
        else {},
        "critChance": damage.get("critChance", 0.0),
        "critMultiplier": damage.get("critMultiplier", 1.0),
        "procChance": float(damage.get("procChance") or 0.0) * proc_multiplier,
    }
    forced = list(dict.fromkeys(
        [
            *(damage.get("forcedProcs") or ()),
            *(properties.get("ExtraProcs") or properties.get("forcedProcs") or ()),
        ]
    ))
    component = {
        "id": component_id,
        "kind": kind,
        "source": source,
        "count": count,
        "damage": block,
    }
    if forced:
        component["forcedProcs"] = forced
    return component


def _heavy_projectile_components(
    index: PackageIndex,
    weapon_path: str,
    weapon: Mapping[str, Any],
    attacks: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve GunBladeStateBehavior's heavy projectile/trace when present."""
    behaviours = weapon.get("Behaviors")
    if not isinstance(behaviours, list) or not any(
        isinstance(entry, Mapping)
        and any(key.startswith("state:GunBladeStateBehavior") for key in entry)
        for entry in behaviours
    ):
        return []
    properties = attacks[0].get("properties") if attacks else {}
    properties = properties if isinstance(properties, Mapping) else {}
    if not properties.get("baseDamageMultiplier") and attacks:
        swings = attacks[0].get("perSwing") or ()
        for raw in swings:
            child = raw.get("properties") if isinstance(raw, Mapping) else None
            if isinstance(child, Mapping) and child.get("baseDamageMultiplier"):
                properties = {
                    **properties,
                    "baseDamageMultiplier": child["baseDamageMultiplier"],
                }
                break
    for position, entry in enumerate(behaviours):
        if not isinstance(entry, dict):
            continue
        fire = _sub_behaviour(entry, "fire:") or {}
        impact = _sub_behaviour(entry, "impact:") or {}
        damage = _resolve_damage(index, weapon_path, fire, impact)
        inline = impact.get("AttackData") if isinstance(impact, Mapping) else None
        projectile = fire.get("projectileType")
        if not damage or not damage.get("types") or not (
            (isinstance(projectile, str) and projectile)
            or (isinstance(inline, Mapping) and inline.get("HitType") == "DHT_PROJECTILE")
        ):
            continue
        return [
            _scaled_heavy_component(
                damage,
                properties,
                component_id="projectile",
                kind="projectile",
                source=damage.get("projectile") or f"behavior-{position}",
                count=fire.get("fireIterations") or 1,
            )
        ]
    return []


def _heavy_recall_variants(
    index: PackageIndex, weapon_path: str, weapon: Mapping[str, Any]
) -> list[dict[str, Any]]:
    variants: list[dict[str, Any]] = []
    for entry in weapon.get("Behaviors") or ():
        if not isinstance(entry, dict):
            continue
        fire = _sub_behaviour(entry, "fire:") or {}
        for field, variant_id in (
            ("projectileType", "normal"),
            ("TurboProjectileType", "turbo"),
        ):
            reference = fire.get(field)
            if not isinstance(reference, str) or not reference:
                continue
            projectile_path, projectile = _resolve_weapon_reference(
                index, weapon_path, reference
            )
            recall_multiplier = _first_number(projectile, "HeavyRecallDamageAtten")
            explosive = projectile.get("ExplosiveAttack")
            if recall_multiplier is None or not isinstance(explosive, Mapping):
                continue
            components: list[dict[str, Any]] = []
            direct = _attack_data(projectile)
            if direct and direct.get("types"):
                components.append(
                    {
                        "id": f"{variant_id}-direct",
                        "kind": "projectileDirect",
                        "source": projectile_path,
                        "count": fire.get("fireIterations") or 1,
                        "damage": direct,
                        **(
                            {"forcedProcs": direct["forcedProcs"]}
                            if direct.get("forcedProcs")
                            else {}
                        ),
                    }
                )
            explosion_source = dict(explosive)
            default_blast = (
                not any(explosion_source.get(key) for key in DAMAGE_TYPES)
                and not explosion_source.get("Type")
            )
            if default_blast:
                explosion_source["Type"] = "DT_EXPLOSION"
            explosion = _damage_block(
                explosion_source, amount_key="Amount", proc_key="ProcChance"
            )
            explosion["types"] = {
                key: value * recall_multiplier
                for key, value in explosion["types"].items()
            }
            explosion["total"] = sum(explosion["types"].values())
            explosion["critChance"] = _first_number(
                projectile, "CriticalChance", "criticalHitChance"
            ) or 0.0
            explosion["critMultiplier"] = _first_number(
                projectile, "CriticalMultiplier", "criticalHitDamageMultiplier"
            ) or 1.0
            if default_blast:
                explosion["damageTypeSource"] = "glaive-default"
            forced = list(dict.fromkeys(
                [
                    *(explosive.get("ForcedProcs") or ()),
                    *(projectile.get("HeavyRecallProcs") or ()),
                ]
            ))
            recall = {
                "id": f"{variant_id}-heavy-recall",
                "kind": "heavyRecall",
                "source": projectile_path,
                "count": 1,
                "damage": explosion,
                "radius": projectile.get("DamageRadius"),
                "falloff": projectile.get("ExplosionFallOff"),
                "recallMultiplier": recall_multiplier,
            }
            if forced:
                recall["forcedProcs"] = forced
            components.append(recall)
            variants.append(
                {"id": variant_id, "projectile": projectile_path, "components": components}
            )
    return list({variant["id"]: variant for variant in variants}.values())


def _resolve_damage(
    index: PackageIndex,
    weapon_path: str,
    fire: dict[str, Any],
    impact: dict[str, Any],
) -> dict[str, Any] | None:
    """Pull damage numbers from a behaviour, following a projectile if needed.

    Three shapes exist, and they must be tried in this order:

    1. A referenced ``projectileType`` -- for projectile weapons this holds the real
       numbers. Their impact behaviour also carries an ``AttackData``, but it is an
       inherited placeholder (Boltor's reads 8 damage against the projectile's 25), so
       checking impact first would silently export the wrong value.
    2. The impact behaviour -- where hitscan weapons keep their damage, spelling crit
       stats ``criticalHitChance``/``criticalHitDamageMultiplier``.
    3. The fire behaviour itself, used by a few weapons.
    """
    projectile = fire.get("projectileType")
    if isinstance(projectile, str) and projectile:
        projectile_path, proj = _resolve_weapon_reference(
            index, weapon_path, projectile
        )
        data = _attack_data(proj)
        inline = _attack_data(impact)
        if data:
            # Generic projectile parents can own the authoritative total/crit
            # while the weapon impact owns only the physical damage shares.
            if not data.get("types") and inline and inline.get("shares"):
                data["shares"] = dict(inline["shares"])
                data["types"] = {
                    damage_type: round(data["total"] * share, 6)
                    for damage_type, share in data["shares"].items()
                }
            data["projectile"] = projectile_path
            data["flightSpeed"] = proj.get("KinematicInitialSpeed")
            components = _projectile_damage_components(proj)
            if components:
                data["components"] = components
                data["radial"] = components[0]
            return data
        # A zero-contact projectile can delegate its actual direct hit to the
        # weapon impact behavior (Sonicor). Do not replace authoritative nonzero
        # projectile data such as Boltor's with an inherited impact placeholder.
        # A true flag is inherited by mines/goo too; their weapon impacts are
        # placeholders. Until additional delegates are proven, authorize only
        # the exact Sonicor weapon/projectile pair audited against the raw dump.
        if (weapon_path == '/Lotus/Weapons/Corpus/Pistols/CrpAirPistol/CrpAirPistolArray'
                and projectile_path == '/Lotus/Weapons/Corpus/Pistols/CrpAirPistol/CrpAirPistolProjectile'
                and proj.get('DealDamageThroughImpactBehavior')
                and isinstance(proj.get('AttackData'), Mapping)
                and proj['AttackData'].get('Amount') == 0 and inline):
            inline['source'] = 'ImpactBehavior'
            inline['projectile'] = projectile_path
            inline['flightSpeed'] = proj.get('KinematicInitialSpeed')
            components = _projectile_damage_components(proj)
            if components:
                inline['components'] = components
                inline['radial'] = components[0]
            return inline
        components = _projectile_damage_components(proj)
        if components:
            primary = components[0]
            # Exact native Talons pair: zero contact damage, manually detonated
            # embedded mines. Keep the airborne 120 blast as evidence, not as
            # an additional hit on top of the embedded 250 blast.
            if (weapon_path == '/Lotus/Weapons/Tenno/ThrowingWeapons/U18ThrowingKnives/U18throwingknives'
                    and projectile_path == weapon_path + 'Projectile'
                    and (proj.get('AttackData') or {}).get('Amount') == 0
                    and proj.get('Embed') == 1):
                embedded = next((c for c in components if c['source'] == 'EmbedDeathAttack'
                                 and c.get('types') == {'DT_EXPLOSION': 250.0}), None)
                if embedded is not None:
                    primary = embedded
            data = dict(primary)
            data["projectile"] = projectile_path
            data["flightSpeed"] = proj.get("KinematicInitialSpeed")
            data["critChance"] = _first_number(
                proj, "CriticalChance", "criticalHitChance"
            ) or 0.0
            data["critMultiplier"] = _first_number(
                proj, "CriticalMultiplier", "criticalHitDamageMultiplier"
            ) or 1.0
            data["components"] = components
            data["radial"] = primary
            return data

    for source in (impact, fire):
        inline = _attack_data(source)
        if inline:
            # ── F16/pipelineGaps[hitscan-radial-dropped]（审计修复）─────
            # RadialOnMiss hitscan 武器（Opticor 类）把径向伤害直接放在
            # impact 块的 RadialDamage 字段里；旧实现只从 projectileType
            # 分支读取径向（_projectile_damage_components），impact 级的
            # 内联径向被静默丢弃（约 65 把武器）。现在同口径提取并挂到
            # components/radial，模拟器与 sidecar 都能看见缺口。
            radial_components = _projectile_damage_components(source)
            if radial_components:
                inline["components"] = radial_components
                inline["radial"] = radial_components[0]
            return inline
    return None


def _projectile_radial_damage(projectile: Mapping[str, Any]) -> dict[str, Any] | None:
    components = _projectile_damage_components(projectile)
    return components[0] if components else None


def _projectile_damage_components(projectile: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Normalize secondary projectile attacks without pretending they are one hit.

    The compact simulator currently evaluates only the primary ``AttackData``.
    Keeping named components in the export makes omitted explosions/stacking
    damage observable and gives a later timeline evaluator an authoritative input.
    """
    components: list[dict[str, Any]] = []
    radial = projectile.get("RadialDamage")
    if isinstance(radial, Mapping) and radial.get("baseAmount"):
        block = _damage_block(
            dict(radial), amount_key="baseAmount", proc_key="baseProcChance"
        )
        block["radius"] = radial.get("radius")
        block["falloff"] = radial.get("fallOff")
        block["source"] = "RadialDamage"
        if radial.get("ForcedProcs"):
            block["forcedProcs"] = radial["ForcedProcs"]
        components.append(block)
    for field in ("ExplosiveAttack", "EmbedDeathAttack", "StackingAttack"):
        attack = projectile.get(field)
        if not isinstance(attack, Mapping) or not attack.get("Amount"):
            continue
        block = _damage_block(
            dict(attack), amount_key="Amount", proc_key="ProcChance"
        )
        block["radius"] = projectile.get("DamageRadius")
        block["falloff"] = projectile.get("ExplosionFallOff")
        block["source"] = field
        if attack.get("ForcedProcs"):
            block["forcedProcs"] = attack["ForcedProcs"]
        components.append(block)
    return components


def _extract_projectile_events(
    index: PackageIndex, weapon_path: str, fire: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Expose complex projectile damage as events without assuming a timeline.

    Only mechanisms whose static shape is useful today are emitted: ordered
    projectile sequences, bounded projectile stacks, and script-backed radial
    multipliers. Ordinary direct/explosive projectiles retain the legacy compact
    representation until their trigger semantics are known.
    """
    sequence = fire.get("projectileSequenceList")
    advance = bool(fire.get("advanceProjectileSequenceOnFire"))
    iterations = int(fire.get("fireIterations") or 1)
    references: list[tuple[int | None, str]] = []
    layer_kind = "projectile"
    # A sequence is only promoted when it is the actual multi-projectile source.
    # Many ordinary weapons carry cosmetic/alternate sequence lists alongside a
    # real ``projectileType``; flattening those would invent extra hits.
    if (
        advance
        and not fire.get("projectileType")
        and iterations > 1
        and isinstance(sequence, list)
        and len(sequence) > 1
    ):
        names = [value for value in sequence if isinstance(value, str) and value]
        if not names:
            return None
        references = [(ordinal, names[ordinal % len(names)]) for ordinal in range(iterations)]
        layer_kind = "sequence"
    else:
        reference = fire.get("projectileType")
        if not isinstance(reference, str) or not reference:
            return None
        path, projectile = _resolve_weapon_reference(index, weapon_path, reference)
        if not _is_complex_projectile(projectile):
            return None
        references = [(None, path)]

    events: list[dict[str, Any]] = []
    scripts: list[dict[str, Any]] = []
    runtime_adapters: list[dict[str, Any]] = []
    derived_events: list[dict[str, Any]] = []
    state: dict[str, Any] = {"kind": layer_kind, "baseIterations": iterations}
    for ordinal, reference in references:
        projectile_path, projectile = _resolve_weapon_reference(
            index, weapon_path, reference
        )
        if not projectile:
            events.append(
                {
                    "id": f"sequence:{ordinal}:unresolved",
                    "kind": "unresolvedProjectile",
                    "projectile": projectile_path,
                    "countRange": [1, 1],
                    "aggregate": False,
                    "support": "unsupported",
                    "unsupported": ["projectile-reference-unresolved"],
                }
            )
            continue

        current_scripts = _projectile_scripts(projectile)
        scripts.extend(current_scripts)
        for adapter in resolve_projectile_runtime_adapters(projectile, projectile_path):
            _merge_projectile_runtime_adapter(runtime_adapters, adapter)
            derived_events.extend(
                _projectile_runtime_derived_events(
                    adapter,
                    projectile_path,
                    ordinal=ordinal,
                )
            )
        events.extend(
            _events_for_projectile(
                projectile_path,
                projectile,
                ordinal=ordinal,
                stacked=layer_kind != "sequence",
            )
        )
        for raw, key in (
            (projectile.get("MaxProjectileStack"), "maxStack"),
            (projectile.get("AttachSpecialAtThisStack"), "attachSpecialAtStack"),
            (projectile.get("StackedMaxLife"), "stackedMaxLife"),
            (projectile.get("ResetMaxLifeOnStack"), "resetMaxLifeOnStack"),
            (projectile.get("MaxBounces"), "maxBounces"),
            (projectile.get("MaxReflections"), "maxReflections"),
        ):
            if raw is not None:
                state[key] = raw

    if not events:
        return None
    unsupported = sorted(
        {
            reason
            for event in events
            for reason in event.get("unsupported", ())
        }
        | ({"projectile-runtime-script"} if scripts else set())
        | {
            reason
            for adapter in runtime_adapters
            for reason in adapter.get("unsupported", ())
        }
        | {
            reason
            for event in derived_events
            for reason in event.get("unsupported", ())
        }
    )
    status = "exact" if not unsupported else "partial"
    return {
        "projectileEvents": events,
        "projectileEventState": state,
        "projectileEventSupport": {
            "status": status,
            "unsupported": unsupported,
            "scripts": scripts,
            "runtimeAdapters": runtime_adapters,
        },
        "projectileDerivedEvents": derived_events,
    }


def _is_complex_projectile(projectile: Mapping[str, Any]) -> bool:
    return bool(
        (isinstance(projectile.get("MaxProjectileStack"), (int, float))
         and projectile.get("MaxProjectileStack", 0) > 1)
        or _script_radial_parameters(projectile)
    )


def _events_for_projectile(
    projectile_path: str,
    projectile: Mapping[str, Any],
    *,
    ordinal: int | None,
    stacked: bool,
) -> list[dict[str, Any]]:
    prefix = f"sequence:{ordinal}" if ordinal is not None else "projectile"
    events: list[dict[str, Any]] = []
    attack = _attack_data(dict(projectile))
    if attack:
        events.append(
            _projectile_event(
                f"{prefix}:impact",
                "impact",
                "fire",
                projectile_path,
                attack,
                count_range=(1, 1),
            )
        )

    max_stack = int(projectile.get("MaxProjectileStack") or 1)
    component_specs = (
        ("ExplosiveAttack", "explosion", "detonation", (1, 1), True),
        ("EmbedDeathAttack", "embedDeath", "embed-death", (0, 1), True),
        (
            "StackingAttack",
            "stack",
            "projectile-stack",
            (0, max(max_stack - 1, 0)),
            True,
        ),
    )
    for field, kind, trigger, count_range, aggregate in component_specs:
        source = projectile.get(field)
        if not isinstance(source, Mapping) or not source.get("Amount"):
            continue
        damage = _damage_block(dict(source), amount_key="Amount", proc_key="ProcChance")
        damage["critChance"] = _first_number(
            dict(projectile), "CriticalChance", "criticalHitChance"
        ) or 0.0
        damage["critMultiplier"] = _first_number(
            dict(projectile), "CriticalMultiplier", "criticalHitDamageMultiplier"
        ) or 1.0
        damage["source"] = field
        damage["radius"] = (
            projectile.get("EmbedDamageRadius")
            if field == "EmbedDeathAttack"
            else projectile.get("DamageRadius")
        )
        damage["falloff"] = projectile.get("ExplosionFallOff")
        event = _projectile_event(
            f"{prefix}:{kind}",
            kind,
            trigger,
            projectile_path,
            damage,
            count_range=count_range,
            aggregate=aggregate,
            support="exact" if count_range[0] == count_range[1] else "partial",
        )
        events.append(event)

    stacking_damage = projectile.get("StackingDamage")
    if stacked and isinstance(stacking_damage, list) and stacking_damage:
        events.append(
            {
                "id": f"{prefix}:stackCurve",
                "kind": "stackDamageCurve",
                "trigger": "projectile-stack",
                "projectile": projectile_path,
                "countRange": [0, max(max_stack - 1, 0)],
                "damageRange": list(stacking_damage),
                "range": projectile.get("StackingDamageRange"),
                "aggregate": False,
                "support": "unsupported",
                "unsupported": ["stacking-damage-curve-unresolved"],
            }
        )

    radial = _script_radial_parameters(projectile)
    if radial:
        events.append(
            {
                "id": f"{prefix}:scriptRadial",
                "kind": "scriptRadial",
                "trigger": "projectile-death",
                "projectile": projectile_path,
                "baseSource": radial.get('baseSource','ExplosiveAttack'),
                **({'conditionText':radial['conditionText']} if radial.get('conditionText') else {}),
                "countRange": [0, 1],
                "multipliers": radial["multipliers"],
                "multiplierRange": [
                    min(radial["multipliers"]),
                    max(radial["multipliers"]),
                ],
                "radius": radial["radius"],
                # The Lua may replace rather than add to the ordinary death attack.
                "aggregate": False,
                "support": "partial",
                "unsupported": ["script-radial-transition-unverified"],
            }
        )
    return events


def _projectile_event(
    event_id: str,
    kind: str,
    trigger: str,
    projectile_path: str,
    damage: Mapping[str, Any],
    *,
    count_range: tuple[int, int],
    aggregate: bool = True,
    support: str = "exact",
) -> dict[str, Any]:
    return {
        "id": event_id,
        "kind": kind,
        "trigger": trigger,
        "projectile": projectile_path,
        "damage": dict(damage),
        "countRange": list(count_range),
        "aggregate": aggregate,
        "support": support,
    }


def _script_radial_parameters(projectile: Mapping[str, Any]) -> dict[str, Any] | None:
    for field in ("OnProjectileDeathScript", "ScriptInstance"):
        script = projectile.get(field)
        if not isinstance(script, Mapping):
            continue
        values = script.get("_radialDmgPct")
        if not isinstance(values, list) or not values:
            continue
        multipliers = [
            float(value)
            for value in values
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if multipliers:
            result = {"multipliers": multipliers, "radius": script.get("_radialRadius")}
            if (str(script.get('Script') or '').endswith('/InfCrpShockSwarm.lua')
                    and script.get('Function') == 'OnOrbDestroyed'):
                result.update(baseSource='shieldDamageData',conditionText='Equip Buried Debts; when the orb is destroyed, explode using its absorbed projectile damage and the augment rank multiplier.')
            return result
    return None


def _projectile_scripts(projectile: Mapping[str, Any]) -> list[dict[str, Any]]:
    scripts: list[dict[str, Any]] = []
    for event in (
        "OnProjectileStartScript",
        "OnProjectileContactScript",
        "OnProjectileDeathScript",
        "OnProjectileStackedScript",
        "OnProjectileStoppedScript",
        "OnGlaiveImpactScript",
        "ScriptInstance",
    ):
        raw = projectile.get(event)
        if not isinstance(raw, Mapping) or not raw.get("Script"):
            continue
        scripts.append(
            {
                "event": event,
                "script": raw.get("Script"),
                "function": raw.get("Function"),
                "params": {
                    key: value for key, value in raw.items() if str(key).startswith("_")
                },
            }
        )
    return scripts


def _merge_projectile_runtime_adapter(
    adapters: list[dict[str, Any]], adapter: Mapping[str, Any]
) -> None:
    """Deduplicate sequence-level adapters while retaining all source projectiles."""
    key = str(adapter.get("key") or "")
    functions = tuple(adapter.get("functions") or ())
    parameters = json.dumps(
        adapter.get("parameters") or {}, ensure_ascii=False, sort_keys=True
    )
    for existing in adapters:
        if (
            existing.get("key") == key
            and tuple(existing.get("functions") or ()) == functions
            and json.dumps(
                existing.get("parameters") or {}, ensure_ascii=False, sort_keys=True
            )
            == parameters
        ):
            projectile = adapter.get("projectile")
            if projectile:
                projectiles = existing.setdefault("projectiles", [])
                if projectile not in projectiles:
                    projectiles.append(projectile)
            return
    copied = dict(adapter)
    if adapter.get("projectile"):
        copied["projectiles"] = [adapter["projectile"]]
    adapters.append(copied)


def _projectile_runtime_derived_events(
    adapter: Mapping[str, Any], projectile_path: str, *, ordinal: int | None
) -> list[dict[str, Any]]:
    prefix = f"sequence:{ordinal}" if ordinal is not None else "projectile"
    result: list[dict[str, Any]] = []
    for transition in adapter.get("transitions") or ():
        if not isinstance(transition, Mapping):
            continue
        transition_id = str(transition.get("id") or "transition")
        event: dict[str, Any] = {
            key: value
            for key, value in transition.items()
            if key not in {"id", "unsupported"}
        }
        event.update(
            {
                "id": f"{prefix}:runtime:{adapter.get('key')}:{transition_id}",
                "projectile": projectile_path,
                "runtimeAdapter": adapter.get("key"),
                "transitionId": transition_id,
                "aggregate": False,
                "unsupported": list(transition.get("unsupported") or ()),
            }
        )
        result.append(event)
    return result


def _sequence_average_damage(
    events: Sequence[Mapping[str, Any]], iterations: int
) -> dict[str, Any] | None:
    impacts = [
        event.get("damage")
        for event in events
        if event.get("kind") == "impact" and isinstance(event.get("damage"), Mapping)
    ]
    if not impacts or iterations <= 0:
        return None
    types: dict[str, float] = {}
    for damage in impacts:
        for damage_type, amount in (damage.get("types") or {}).items():
            types[str(damage_type)] = types.get(str(damage_type), 0.0) + float(amount)
    types = {key: round(value / iterations, 6) for key, value in types.items()}
    total = sum(types.values())
    result: dict[str, Any] = {
        "total": total,
        "types": types,
        "shares": {key: round(value / total, 6) for key, value in types.items()} if total else {},
        "procChance": sum(float(damage.get("procChance") or 0.0) for damage in impacts)
        / iterations,
        "critChance": sum(float(damage.get("critChance") or 0.0) for damage in impacts)
        / iterations,
        "critMultiplier": sum(
            float(damage.get("critMultiplier") or 1.0) for damage in impacts
        )
        / iterations,
        "projectileSequence": [event.get("projectile") for event in events if event.get("kind") == "impact"],
    }
    components_by_source: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("kind") == "impact" or not isinstance(event.get("damage"), Mapping):
            continue
        damage = event["damage"]
        source = str(damage.get("source") or event.get("kind") or "projectile")
        component = components_by_source.setdefault(
            source,
            {
                "procChance": 0.0,
                "types": {},
                "critChance": 0.0,
                "critMultiplier": 0.0,
                "source": source,
                "radius": damage.get("radius"),
                "falloff": damage.get("falloff"),
                "countRange": [0, 0],
            },
        )
        component["procChance"] += float(damage.get("procChance") or 0.0)
        component["critChance"] += float(damage.get("critChance") or 0.0)
        component["critMultiplier"] += float(damage.get("critMultiplier") or 1.0)
        for damage_type, amount in (damage.get("types") or {}).items():
            component["types"][damage_type] = component["types"].get(damage_type, 0.0) + float(amount)
        count = event.get("countRange") or [0, 0]
        component["countRange"][0] += int(count[0] or 0)
        component["countRange"][1] += int(count[1] or 0)
    components: list[dict[str, Any]] = []
    for component in components_by_source.values():
        component["types"] = {
            key: round(value / iterations, 6)
            for key, value in component["types"].items()
        }
        component["total"] = sum(component["types"].values())
        component["shares"] = {
            key: round(value / component["total"], 6)
            for key, value in component["types"].items()
        } if component["total"] else {}
        component["procChance"] /= iterations
        component["critChance"] /= iterations
        component["critMultiplier"] /= iterations
        components.append(component)
    if components:
        result["components"] = components
    return result


def _attack_data(obj: dict[str, Any]) -> dict[str, Any] | None:
    """Build a damage block from an object's AttackData plus its critical stats.

    Crit stats are named differently on impact behaviours than on projectiles, so both
    spellings are accepted.
    """
    attack = obj.get("AttackData")
    if not isinstance(attack, dict) or not attack.get("Amount"):
        return None
    block = _damage_block(attack, amount_key="Amount", proc_key="ProcChance")
    block["critChance"] = _first_number(obj, "CriticalChance", "criticalHitChance") or 0.0
    block["critMultiplier"] = (
        _first_number(obj, "CriticalMultiplier", "criticalHitDamageMultiplier") or 1.0
    )
    if attack.get("ForcedProcs"):
        block["forcedProcs"] = attack["ForcedProcs"]
    return block


def _first_number(obj: dict[str, Any], *keys: str) -> float | None:
    """Return the first key present in ``obj`` holding a number."""
    for key in keys:
        value = obj.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _damage_block(
    source: dict[str, Any], *, amount_key: str, proc_key: str
) -> dict[str, Any]:
    """Normalize a damage struct into total plus per-type absolute and share values.

    Two encodings coexist. Most objects store per-type *fractions* of ``Amount``
    (Boltor: 25 with DT_PUNCTURE 0.8). Newer ones store absolute per-type damage that
    sums to ``Amount`` (Electroprod: 128 with DT_IMPACT 52, DT_ELECTRICITY 76). The
    ``UseNewFormat`` flag does not reliably distinguish them -- both appear with the
    flag absent -- so the magnitude of the values decides: a fraction cannot exceed 1.

    Both representations are emitted so consumers never re-derive them, and neither has
    to know which encoding the source used.
    """
    total = float(source.get(amount_key) or 0.0)
    explicit_type = source.get("Type")
    # Guided projectile children inherit stale physical DT_* fields from their
    # generic parent while carrying the authoritative legacy ``Type`` + ``Amount``
    # pair (Arbucep is the current example). Limit this override to the explicit
    # legacy marker so ordinary absolute-format blocks keep their existing rules.
    if source.get("UseNewFormat") == 0 and explicit_type in DAMAGE_TYPES:
        raw = {explicit_type: 1.0}
    else:
        raw = {
            dt: float(source[dt])
            for dt in DAMAGE_TYPES
            if isinstance(source.get(dt), (int, float)) and source[dt]
        }
    # Beam/impact records often use one ``Type`` plus ``Amount`` instead of
    # repeating a one-valued DT_* share.  Losing that type turns a real weapon
    # into an apparently damage-less mode.
    if not raw and isinstance(explicit_type, str) and explicit_type in DAMAGE_TYPES:
        raw = {explicit_type: 1.0}

    source_total = total
    if any(value > 1.0 for value in raw.values()):
        # Absolute encoding. Derive shares from the per-type sum rather than from
        # ``Amount``: the two disagree on a handful of weapons, and the per-type values
        # are what the game actually applies.
        absolute = raw
        divisor = sum(raw.values()) or total or 1.0
        shares = {dt: value / divisor for dt, value in raw.items()}
        # A few current-build records retain a stale/rounded ``Amount`` while their
        # absolute DT_* fields are authoritative (for example Sagek Prime: 26 vs
        # 6.3+8.5+12=26.8). Keep the source value for audit, but expose a coherent
        # effective total so consumers never see types whose sum exceeds ``total``.
        total = sum(absolute.values()) or total
    else:
        shares = raw
        absolute = {dt: round(total * share, 6) for dt, share in raw.items()}

    result = {
        "total": total,
        "procChance": source.get(proc_key, 0.0),
        "shares": {dt: round(share, 6) for dt, share in shares.items()},
        "types": absolute,
    }
    if source_total != total:
        result["sourceTotal"] = source_total
    return result


def _per_second(fire_rate: Any) -> float | None:
    """Convert the engine's fire rate unit to shots per second.

    The engine stores rounds per minute-ish ticks; dividing by 60 reproduces the
    figure the in-game arsenal shows (Boltor: 525 -> 8.75/s).
    """
    if isinstance(fire_rate, (int, float)) and fire_rate:
        return round(fire_rate / 60.0, 6)
    return None


# -- warframes -----------------------------------------------------------------------


def extract_warframes(
    index: PackageIndex, store: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    """Extract warframes and necramechs with base defences and abilities."""
    records = []
    for type_name, item in store.items():
        suit = index.resolve(type_name)
        if not suit:
            continue
        category = item.get("ProductCategory") or suit.get("ProductCategory", "")
        kind = SUIT_CATEGORIES.get(category)
        if not kind:
            continue
        records.append(
            {
                "path": type_name,
                "name": _basename(type_name),
                "kind": kind,
                "nameTag": suit.get("LocalizeTag") or item.get("LocalizeTag"),
                "descTag": suit.get("LocalizeDescTag") or item.get("LocalizeDescTag"),
                "masteryReq": item.get("RequiredLevel", 0),
                "health": suit.get("MaxHealthOverride"),
                "shield": suit.get("MaxShieldOverride"),
                "armour": suit.get("ArmourRatingOverride"),
                # Energy and sprint speed are not stored on suit types at all -- the
                # engine applies global defaults and only a handful of frames override
                # them elsewhere. Emitting None here would look like missing data, so
                # the fields are omitted; consumers should assume the game defaults.
                "stamina": suit.get("MaxStaminaOverride"),
                "polarities": suit.get("ArtifactSlots") or [],
                "abilities": _ability_paths(suit),
                "passiveTag": suit.get("PassiveAbilityLocTag"),
            }
        )
    records.sort(key=lambda r: r["path"])
    return records


def _ability_paths(suit: dict[str, Any]) -> list[str]:
    """Return the ability type paths a suit grants, in slot order."""
    raw = suit.get("AbilityTypes")
    if not isinstance(raw, list):
        return []
    paths = []
    for entry in raw:
        if isinstance(entry, str):
            paths.append(entry)
        elif isinstance(entry, dict):
            value = entry.get("AbilityType") or entry.get("Type")
            if isinstance(value, str):
                paths.append(value)
    return paths


# -- mods ----------------------------------------------------------------------------


def extract_arcanes(
    index: PackageIndex, store: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Extract player-owned Arcanes with explicit trigger and stack metadata."""
    prefix = "/Lotus/Upgrades/CosmeticEnhancers/"
    records: list[dict[str, Any]] = []
    for path in sorted(store):
        if not path.startswith(prefix):
            continue
        obj = index.resolve(path)
        upgrades = obj.get("Upgrades")
        own_effects = (
            [
                {**_build_effect(upgrade), "sourcePath": path}
                for upgrade in upgrades
                if isinstance(upgrade, dict)
            ]
            if isinstance(upgrades, list)
            else []
        )
        conditions = _string_list(obj.get("ConditionalUpgrades"))
        conditional_effects, unresolved = _conditional_effects(index, path, obj)
        effects = (
            own_effects
            if not conditions and obj.get("ApplyUpgradesByDefault", 1) != 0
            else []
        )
        extra_effects = [
            {
                **_build_effect(upgrade),
                "sourcePath": path,
                "unlockRank": MAX_RANK_BY_FUSION_LIMIT.get(
                    obj.get("ExtraUpgradeFusionLevel"), _max_rank(path, obj)
                ),
                "scalesWithRank": False,
            }
            for upgrade in obj.get("ExtraUpgrades") or ()
            if isinstance(upgrade, dict)
        ]
        all_effects = effects + extra_effects + [
            effect
            for conditional in conditional_effects
            for effect in conditional.get("effects", ())
        ]
        runtime_scripts = _runtime_scripts(obj)
        conditional_runtime = any(
            conditional.get("runtimeScripts") for conditional in conditional_effects
        )
        weapon_effects = [
            effect for effect in all_effects if "weapon" in effect.get("supportedBy", ())
        ]
        record: dict[str, Any] = {
            "path": path,
            "name": _basename(path),
            "nameTag": obj.get("LocalizeTag") or store[path].get("LocalizeTag"),
            "descTag": obj.get("LocalizeDescTag"),
            "rarity": obj.get("Rarity"),
            "icon": obj.get("Icon"),
            "maxRank": _max_rank(path, obj),
            "compatibility": obj.get("ItemCompatibility"),
            "effects": effects,
            "conditionalEffects": conditional_effects,
            "extraEffects": extra_effects,
            "trigger": {
                "conditionTag": obj.get("ConditionTag"),
                "conditions": conditions,
                "chance": obj.get("UpgradeChance"),
                "duration": obj.get("UpgradeDuration"),
                "durationScalesWithRank": obj.get("DurationScalesWithRank"),
                "maxStacks": obj.get("MaxConditionalStacks"),
                "stackMode": obj.get("StackMode"),
                "applyUpgradesByDefault": obj.get("ApplyUpgradesByDefault"),
            },
            "support": {
                "weaponEffects": len(weapon_effects),
                "totalEffects": len(all_effects),
                "manualState": bool(weapon_effects),
                "complete": bool(all_effects)
                and len(weapon_effects) == len(all_effects)
                and not runtime_scripts
                and not conditional_runtime
                and not unresolved,
            },
        }
        if runtime_scripts:
            record["runtimeScripts"] = runtime_scripts
        if unresolved:
            record["unresolvedReferences"] = unresolved
        records.append(record)
    return records


def extract_mods(index: PackageIndex) -> list[dict[str, Any]]:
    """Extract every mod with its per-rank effects and support flag."""
    paths = list(index.iter_paths("Lotus/Upgrades/Mods"))
    sub_upgrade_targets: set[str] = set()
    for path in paths:
        for reference in _string_list(index.resolve(path).get("SubUpgrades")):
            resolved, child = _resolve_sub_upgrade(index, path, reference)
            if child:
                sub_upgrade_targets.add(resolved)

    records = []
    for path in paths:
        obj = index.resolve(path)
        upgrades = obj.get("Upgrades")
        own_effects = (
            [_build_effect(u) for u in upgrades if isinstance(u, dict)]
            if isinstance(upgrades, list)
            else []
        )

        runtime_scripts = _runtime_scripts(obj)
        conditional_effects, unresolved = _conditional_effects(index, path, obj)
        # Some real cards are only a shell around SubUpgrades (for example Velox's
        # Nightwave augment), so an empty top-level Upgrades list is not sufficient to
        # discard them. Pure script classes without either shape remain outside this
        # compact player-mod export, matching the previous scope.
        if not own_effects and not _string_list(obj.get("SubUpgrades")):
            continue
        effects = [] if _string_list(obj.get("ConditionalUpgrades")) else own_effects
        all_effects = effects + [
            effect
            for conditional in conditional_effects
            for effect in conditional["effects"]
        ]
        conditional_runtime = any(
            conditional.get("runtimeScripts") for conditional in conditional_effects
        )
        support = {
            consumer: (
                bool(all_effects)
                and all(consumer in effect["supportedBy"] for effect in all_effects)
                and not runtime_scripts
                and not conditional_runtime
                and not unresolved
            )
            for consumer in ("weapon", "warframe")
        }
        is_sub_upgrade = packages.normalize(path) in sub_upgrade_targets
        selectable = _is_player_selectable_mod(
            obj, is_sub_upgrade=is_sub_upgrade
        ) and "/Quests/" not in path

        record: dict[str, Any] = {
            "path": path,
            "modFamily": _mod_family(index, path),
            "name": _basename(path),
            "nameTag": obj.get("LocalizeTag"),
            "rarity": obj.get("Rarity"),
            "polarity": obj.get("ArtifactPolarity"),
            "baseDrain": _base_drain(path, obj),
            "baseDrainEnum": obj.get("BaseDrain"),
            "maxRank": _max_rank(path, obj),
            "compatibility": obj.get("ItemCompatibility"),
            "compatibilityTags": _string_list(obj.get("CompatibilityTags")),
            "incompatibilityTags": _string_list(obj.get("IncompatibilityTags")),
            "isAugment": bool(obj.get("IsAugment")),
            "selectable": selectable,
            "isSubUpgrade": is_sub_upgrade,
            "effects": effects,
            "conditionalEffects": conditional_effects,
            "support": support,
            "supported": any(support.values()),
        }
        # Preserve the package-level set contract.  The simulator/UI can then
        # apply an explicitly selected number of pieces without inferring it
        # from localized names or file paths.
        mod_set = obj.get("ModSet")
        if not mod_set and obj.get("NumUpgradesInSet") is not None:
            mod_set = _basename(path)
        if mod_set:
            record["modSet"] = mod_set
        if isinstance(obj.get("ModSetValues"), list):
            record["modSetValues"] = obj["ModSetValues"]
        if "BuffSet" in obj:
            record["buffSet"] = bool(obj.get("BuffSet"))
        if obj.get("NumUpgradesInSet") is not None:
            record["setPieces"] = obj["NumUpgradesInSet"]
        if obj.get("ModSetIcon"):
            record["modSetIcon"] = obj["ModSetIcon"]
        if "ApplyUpgradesByDefault" in obj:
            record["applyUpgradesByDefault"] = obj["ApplyUpgradesByDefault"]
        if runtime_scripts:
            record["runtimeScripts"] = runtime_scripts
        if unresolved:
            record["unresolvedReferences"] = unresolved
        records.append(record)
    records.sort(key=lambda r: r["path"])
    return records


def _mod_family(index: PackageIndex, path: str) -> str:
    """Return the base Mod ancestor used by the game for variant exclusivity."""
    family = packages.normalize(path)
    for ancestor in index.ancestry(path):
        if ancestor.startswith("/Lotus/Upgrades/Mods/"):
            family = ancestor
    return family


def _is_player_selectable_mod(
    obj: dict[str, Any], *, is_sub_upgrade: bool = False
) -> bool:
    """Whether an upgrade object represents a card the player can equip.

    ``CodexSecret`` and ``TradeCapability`` are deliberately not gates here: real
    Primed/Expert cards commonly carry ``CodexSecret=1`` and ``RO_NEVER``.  A card
    exposed to the player's Mod UI consistently has a display-name key, equipment
    compatibility, and card art. Director auras, encounter modifiers, set-bonus
    shells, and SubUpgrade implementation details lack at least one of those fields.
    """
    return (
        not is_sub_upgrade
        and not bool(obj.get("ExcludeFromCodex"))
        and bool(obj.get("LocalizeTag"))
        and bool(obj.get("ItemCompatibility"))
        and bool(obj.get("Icon"))
    )


def _is_stance(path: str) -> bool:
    """True for melee stance cards, which cap at rank 3 and grant capacity.

    Stances live under several unrelated trees -- player melee trees, PvP variants, and
    companion beast stances -- with no shared field marking them, so the path is the
    only reliable signal.
    """
    return "MeleeTree" in path or "Stance" in path


def _is_aura(path: str) -> bool:
    """True for warframe auras and Railjack matrices, which grant capacity."""
    return "Aura" in path or path.rsplit("/", 1)[-1].endswith("Matrix")


def _max_rank(path: str, obj: dict[str, Any]) -> int:
    limit = obj.get("FusionLimit")
    if limit in MAX_RANK_BY_FUSION_LIMIT:
        return MAX_RANK_BY_FUSION_LIMIT[limit]
    return STANCE_MAX_RANK if _is_stance(path) else DEFAULT_MAX_RANK


def _base_drain(path: str, obj: dict[str, Any]) -> int:
    """Return the rank-0 capacity cost, negative for cards that grant capacity.

    The enum carries only the magnitude: Steel Charge is ``QA_MEDIUM`` like Point
    Strike, but being an aura it reads -4 where Point Strike reads +4. Drain then moves
    one point per rank in whichever direction the sign points.
    """
    magnitude = DRAIN_BY_ENUM.get(obj.get("BaseDrain"), DEFAULT_ABSENT_DRAIN)
    if _is_stance(path) or _is_aura(path):
        return -magnitude
    return magnitude


def _build_effect(upgrade: dict[str, Any]) -> dict[str, Any]:
    """Normalize one entry of a mod's Upgrades list."""
    upgrade_type = upgrade.get("UpgradeType", "NONE")
    operation = upgrade.get("OperationType") or "ADD"

    supported_by = []
    if (
        operation in SUPPORTED_OPERATIONS
        and upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES
        and _weapon_qualifiers_supported(upgrade)
    ):
        supported_by.append("weapon")
    if (
        operation in SUPPORTED_OPERATIONS
        and upgrade_type in SUPPORTED_WARFRAME_UPGRADE_TYPES
    ):
        supported_by.append("warframe")

    effect: dict[str, Any] = {
        "upgradeType": upgrade_type,
        "operation": operation,
        # Value is the per-rank increment; rank 0 already includes one step.
        "valuePerRank": upgrade.get("Value"),
        "damageType": upgrade.get("DamageType"),
        "supportedBy": supported_by,
        "supported": bool(supported_by),
    }
    if upgrade.get("LocTag"):
        effect["locTag"] = upgrade["LocTag"]
        for source, target in (
            ("DisplayAsPercent", "displayAsPercent"),
            ("DisplayAsMultiplier", "displayAsMultiplier"),
            ("ReverseValueSymbol", "reverseValueSymbol"),
        ):
            if source in upgrade:
                effect[target] = upgrade[source]

    localization_script = upgrade.get("LocKeyWordScript")
    if isinstance(localization_script, dict) and any(localization_script.values()):
        # This script formats the card description; it is not the runtime effect.
        effect["localizationScript"] = localization_script

    for source, target in _EFFECT_QUALIFIERS.items():
        if source in upgrade:
            effect[target] = upgrade[source]
    return effect


_EFFECT_QUALIFIERS = {
    "SymbolFilter": "symbolFilter",
    "ValidType": "validType",
    "InvalidModifiers": "invalidModifiers",
    "ValidModifiers": "validModifiers",
    "ValidProcTypes": "validProcTypes",
    "ValidPostures": "validPostures",
    "AutoType": "autoType",
    "CheckTypeOnInstall": "checkTypeOnInstall",
}


def _weapon_qualifiers_supported(upgrade: Mapping[str, Any]) -> bool:
    if _string_list(upgrade.get("ValidProcTypes")):
        return False
    if _string_list(upgrade.get("ValidPostures")):
        return False
    modifiers = _string_list(upgrade.get("ValidModifiers")) + _string_list(
        upgrade.get("InvalidModifiers")
    )
    return all(modifier in SUPPORTED_SCENARIO_MODIFIERS for modifier in modifiers)

_RUNTIME_SCRIPTS = {
    "Script": "apply",
    "UnappliedScript": "unapply",
    "OnEnterAuraScript": "onEnterAura",
    "OnExitAuraScript": "onExitAura",
}


def _runtime_scripts(obj: dict[str, Any]) -> dict[str, Any]:
    """Return actual runtime hooks, separate from description localization scripts."""
    return {
        target: obj[source]
        for source, target in _RUNTIME_SCRIPTS.items()
        if source in obj and obj[source]
    }


def _string_list(value: Any) -> list[str]:
    """Normalize a string-or-list reference field without inventing invalid values."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _resolve_reference(owner_path: str, reference: str) -> str:
    """Resolve a relative package reference next to the object that owns it."""
    if reference.startswith("/"):
        return packages.normalize(reference)
    owner = PurePosixPath(packages.normalize(owner_path))
    return packages.normalize(str(owner.parent / reference))


def _resolve_sub_upgrade(
    index: PackageIndex, owner_path: str, reference: str
) -> tuple[str, dict[str, Any]]:
    """Resolve a SubUpgrades reference, including one inherited from an ancestor.

    Relative references are relative to the object that declared the field. The
    flattened object does not retain that provenance, so try the derived type and each
    ancestor in order. This matters for Beginner/Expert variants inheriting a sibling
    sub-upgrade from their base card.
    """
    if reference.startswith("/"):
        resolved = packages.normalize(reference)
        return resolved, index.resolve(resolved)

    candidates = [_resolve_reference(path, reference) for path in index.ancestry(owner_path)]
    for resolved in dict.fromkeys(candidates):
        child = index.resolve(resolved)
        if child:
            return resolved, child
    return candidates[0], {}


def _conditional_effects(
    index: PackageIndex, path: str, obj: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Resolve a card's own condition and recursively attached sub-upgrades."""
    effects: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []
    visited: set[str] = set()

    def add(source_path: str, source: dict[str, Any], *, force: bool = False) -> None:
        source_path = packages.normalize(source_path)
        if source_path in visited:
            unresolved.append(
                {
                    "field": "SubUpgrades",
                    "value": source_path,
                    "resolvedPath": source_path,
                    "reason": "cycle",
                }
            )
            return
        visited.add(source_path)

        conditions = _string_list(source.get("ConditionalUpgrades"))
        source_upgrades = source.get("Upgrades")
        built = (
            [_build_effect(item) for item in source_upgrades if isinstance(item, dict)]
            if isinstance(source_upgrades, list)
            else []
        )
        scripts = _runtime_scripts(source)
        if force or conditions:
            entry: dict[str, Any] = {
                "sourcePath": source_path,
                "conditionTag": source.get("ConditionTag"),
                "conditions": conditions,
                "duration": source.get("UpgradeDuration"),
                "maxStacks": source.get("MaxConditionalStacks"),
                "stackMode": source.get("StackMode"),
                "effects": built,
            }
            if "ApplyUpgradesByDefault" in source:
                entry["applyUpgradesByDefault"] = source["ApplyUpgradesByDefault"]
            if source.get("IsInfinite"):
                # The buff holds until its condition resets; UpgradeDuration
                # is then not a lifetime (Boar Reified Bane, Lato 2-2).
                entry["isInfinite"] = True
            if scripts:
                entry["runtimeScripts"] = scripts
            effects.append(entry)

        for reference in _string_list(source.get("SubUpgrades")):
            resolved, child = _resolve_sub_upgrade(index, source_path, reference)
            if not child:
                unresolved.append(
                    {
                        "field": "SubUpgrades",
                        "value": reference,
                        "resolvedPath": resolved,
                        "reason": "notFound",
                    }
                )
                continue
            add(resolved, child, force=True)

    add(path, obj)
    return effects, unresolved


# -- enemies -------------------------------------------------------------------------


RESISTANCE_TABLE_PATH = "/Lotus/Types/Game/ResistanceTables/ProdResistanceTable"


def _enemy_avatar_base_levels(index: PackageIndex) -> dict[str, tuple[float, ...]]:
    """Return BaseLevel candidates keyed by the avatar spawned by an agent.

    Enemy health is stored on avatars, while ``BaseLevel`` and ``AvatarTypes`` live
    on their agent objects.  Keep every observed value: the rare shared avatar with
    conflicting agent levels must remain explicit instead of silently picking one.
    """
    levels: dict[str, set[float]] = {}
    for agent_path in index.iter_paths("Lotus/Types/Enemies"):
        agent = index.resolve(agent_path)
        base_level = agent.get("BaseLevel")
        if (
            not isinstance(base_level, (int, float))
            or isinstance(base_level, bool)
            or base_level < 0
        ):
            continue

        # AvatarTypes can be inherited and each relative reference is relative to
        # the ancestor that declared it, not necessarily the derived agent.
        references: dict[str, tuple[str, str]] = {}
        for ancestor in reversed(index.ancestry(agent_path)):
            raw = index.get(ancestor) or {}
            avatar_types = raw.get("AvatarTypes")
            if not isinstance(avatar_types, dict):
                continue
            for kind, reference in avatar_types.items():
                if isinstance(kind, str) and isinstance(reference, str) and reference:
                    references[kind] = (ancestor, reference)

        for owner, reference in references.values():
            avatar_path = _resolve_reference(owner, reference)
            levels.setdefault(avatar_path, set()).add(float(base_level))

    return {path: tuple(sorted(values)) for path, values in levels.items()}


def _enemy_hit_proxies(
    index: PackageIndex, controller_path: str, controller: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Flatten a damage controller's hit proxies without guessing multipliers.

    ``HitProxies`` is often inherited, while relative ``Type`` references are
    relative to the controller object that declared the list.  Keep both the
    reference path and the raw proxy fields so the damage engine can distinguish
    a head weakpoint from an ordinary body hit.
    """
    owner = controller_path
    entries: Any = controller.get("HitProxies")
    for ancestor in index.ancestry(controller_path):
        raw = index.get(ancestor)
        if isinstance(raw, Mapping) and "HitProxies" in raw:
            owner = ancestor
            entries = raw.get("HitProxies")
            break
    if not isinstance(entries, list):
        return []

    fields = (
        ("Part", "part"),
        ("DamageAtten", "damageAtten"),
        ("CriticalChance", "criticalChance"),
        ("CriticalMultiplier", "criticalMultiplier"),
        ("Weakness", "weakness"),
        ("DamageMultipliers", "damageMultipliers"),
    )
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        reference = entry.get("Type")
        if not isinstance(reference, str) or not reference:
            continue
        proxy_path = _resolve_reference(owner, reference)
        proxy = index.resolve(proxy_path)
        item: dict[str, Any] = {
            "bone": entry.get("BoneName") or "",
            "type": proxy_path,
        }
        for source, target in fields:
            value = proxy.get(source)
            if value is not None:
                item[target] = value
        result.append(item)
    return result


def extract_enemies(index: PackageIndex) -> list[dict[str, Any]]:
    """Extract enemy defensive profiles needed for damage-reduction maths.

    Health and shields live on the enemy entity, but armour and the resistance
    keywords that drive type-vs-type multipliers live on its damage controller, so both
    objects are merged into one record.
    """
    records = []
    resistance_table = index.resolve(RESISTANCE_TABLE_PATH)
    avatar_base_levels = _enemy_avatar_base_levels(index)
    for path in index.iter_paths("Lotus/Types/Enemies"):
        obj = index.resolve(path)
        health = obj.get("MaxHealth")
        if not isinstance(health, (int, float)) or not health:
            continue

        faction_resistance = obj.get("FactionResistanceKeyword")
        base_level_candidates = avatar_base_levels.get(path, ())
        record: dict[str, Any] = {
            "path": path,
            "name": _basename(path),
            "nameTag": obj.get("LocTag"),
            "health": health,
            "shield": obj.get("MaxShield") or 0,
            "baseLevel": (
                base_level_candidates[0] if len(base_level_candidates) == 1 else None
            ),
            "faction": obj.get("Faction"),
            "factionResistance": faction_resistance,
            "critMultiplier": obj.get("CriticalMultiplier"),
            "armour": 0,
        }
        if len(base_level_candidates) > 1:
            record["baseLevelCandidates"] = list(base_level_candidates)
        modifiers = resistance_table.get(faction_resistance)
        if isinstance(modifiers, dict):
            # ProdResistanceTable stores weakness as a negative resistance and
            # resistance as a positive value. Consumers need a direct damage delta:
            # -0.5 in the raw table therefore becomes +0.5 damage.
            record["factionDamageModifiers"] = {
                damage_type: -float(value)
                for damage_type, value in sorted(modifiers.items())
                if damage_type.startswith("DT_") and isinstance(value, (int, float))
            }

        controller_path = obj.get("DamageControllerType")
        if isinstance(controller_path, str) and controller_path:
            controller = index.resolve(controller_path)
            record["damageController"] = packages.normalize(controller_path)
            record["armour"] = controller.get("ArmourRating") or 0
            # RK_* keywords select the row in the damage-type resistance table
            # (e.g. RK_CLONED_FLESH takes +25% from slash).
            record["healthType"] = controller.get("HealthResistanceKeyword")
            record["shieldType"] = controller.get("ShieldResistanceKeyword")
            record["armourType"] = controller.get("ArmourResistanceKeyword")
            record["usesNpcArmourCurve"] = bool(controller.get("UseNPCArmourCalculation"))
            hit_proxies = _enemy_hit_proxies(index, controller_path, controller)
            if hit_proxies:
                record["hitProxies"] = hit_proxies
            # Entities may raise shields on the controller instead of the entity.
            if not record["shield"] and controller.get("MaxShield"):
                record["shield"] = controller["MaxShield"]

        records.append(record)
    records.sort(key=lambda r: r["path"])
    return records


# -- export provenance / CLI --------------------------------------------------------


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _export_provenance(
    build_dir: Path, catalogs: Mapping[str, LocalizationCatalog]
) -> dict[str, Any]:
    packages_bin = build_dir / "Packages.bin"
    return {
        "packagesBin": {
            "source": "Packages.bin",
            "hash": _file_sha256(packages_bin),
        },
        "localizationCatalogs": {
            language: catalog.metadata
            for language, catalog in sorted(catalogs.items())
        },
    }


def load_locale_specs(specs: Sequence[str]) -> dict[str, LocalizationCatalog]:
    catalogs: dict[str, LocalizationCatalog] = {}
    for spec in specs:
        language, separator, raw_path = spec.partition("=")
        language = language.strip()
        raw_path = raw_path.strip()
        if not separator or not language or not raw_path:
            raise ValueError(f"invalid --locale {spec!r}; expected LANGUAGE=PATH")
        language = normalize_language_key(language)
        if language in catalogs:
            raise ValueError(f"duplicate --locale language: {language}")

        path = Path(raw_path)
        version = path.parent.name if path.parent.parent.name == "versions" else None
        catalogs[language] = LocalizationCatalog.from_file(path, version=version)
    return catalogs


# Backward-compatible internal name used by existing callers/tests.
_load_locale_specs = load_locale_specs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_dir", help="data/raw/<BuildLabel> directory")
    parser.add_argument("out_dir", help="directory for the four compact JSON exports")
    parser.add_argument(
        "--locale",
        action="append",
        default=[],
        metavar="LANGUAGE=PATH",
        help="version-pinned UTF-8 WPEP/simple JSON catalog; may be repeated",
    )
    args = parser.parse_args(argv)
    try:
        catalogs = load_locale_specs(args.locale)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    counts = export_all(args.build_dir, args.out_dir, catalogs=catalogs)
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


# -- helpers -------------------------------------------------------------------------


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _iter_dicts(values: Iterable[Any]) -> Iterable[dict[str, Any]]:
    return (v for v in values if isinstance(v, dict))


if __name__ == "__main__":
    raise SystemExit(main())
