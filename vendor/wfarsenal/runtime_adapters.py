"""Small, fail-closed adapters for selected PvE Lua-backed mod effects.

The exporter intentionally keeps Lua metadata instead of pretending that every
script is a normal ``ModEffect``.  This module recognises only a handful of
canonical cards whose raw script parameters are sufficient to evaluate the
combat-relevant part offline.  Unknown or malformed scripts return ``None`` and
remain unsupported; no name-only or generic-script inference is performed.
"""

from __future__ import annotations

from copy import deepcopy
import math
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeAdapter:
    """One verified runtime behaviour at a concrete mod rank."""

    key: str
    kind: str
    source_path: str
    rank: int
    # Impact conversion: chance is per eligible Impact status proc and is doubled
    # below ``fire_rate_threshold``.  The output is a normal damage/status type.
    damage_type: str | None = None
    chance: float | None = None
    fire_rate_threshold: float | None = None
    fire_rate_multiplier: float = 2.0
    # Conditional direct damage (Range Advantage) is an additive damage bonus.
    damage_bonus: float | None = None
    range_required: float | None = None
    # IndependentStatusProcOnDamage (Prototype Shock Coils).
    proc_type: str | None = None
    duration: float | None = None
    max_stacks: int | None = None


def resolve_runtime_adapter(
    mod: Mapping[str, Any], rank: int
) -> RuntimeAdapter | None:
    """Return a verified adapter for ``mod`` or ``None``.

    Matching is deliberately anchored to canonical internal/path identifiers and
    the raw parameter values.  This prevents a future card reusing a script name
    with different semantics from being silently treated as one of these cards.
    """

    path = str(mod.get("path") or "")
    internal = str(mod.get("nameInternal") or mod.get("name") or "")
    if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
        return None
    max_rank = mod.get("maxRank")
    if isinstance(max_rank, int) and not isinstance(max_rank, bool) and rank > max_rank:
        return None

    scripts = _apply_scripts(mod.get("runtimeScripts"))
    if not scripts:
        return None
    tap=double_tap_configuration(mod,rank)
    if tap:
        return RuntimeAdapter(key='double-tap',kind='consecutive_hit_damage',source_path=path,rank=rank,
                              damage_bonus=tap['perHit'],duration=tap['duration'],max_stacks=tap['maximum'])

    # Only the three canonical Acuity cards use this stat override contract.
    acuity_paths = {
        '/Lotus/Upgrades/Mods/' + family + '/WeaponWeakpointCriticalChanceMod'
        for family in ('Rifle', 'Pistol', 'Shotgun')
    }
    override = '/Lotus/Upgrades/Mods/WeaponStatOverride/LimitMultishot.lua'
    raw_scripts = mod.get('runtimeScripts') or {}
    if (path in acuity_paths
            and raw_scripts == {
                'apply': {'Function': 'OnApplyUpgrade', 'Script': override},
                'unapply': {'Function': 'OnUnapplyUpgrade', 'Script': override},
            }):
        return RuntimeAdapter(key='acuity', kind='lock_multishot', source_path=path, rank=rank)

    cannonade_paths = {f'/Lotus/Upgrades/Mods/{family}/{family}SemiAutoFantasyMod'
                       for family in ('Rifle', 'Pistol', 'Shotgun')}
    rate_override = '/Lotus/Upgrades/Mods/WeaponStatOverride/LimitFireRate.lua'
    if (path in cannonade_paths and raw_scripts == {
            'apply': {'Function':'OnApplyUpgrade','Script':rate_override},
            'unapply': {'Function':'OnUnapplyUpgrade','Script':rate_override}}):
        return RuntimeAdapter(key='cannonade',kind='lock_fire_rate',source_path=path,rank=rank)

    # Hemorrhage / Internal Bleeding / Magnetic Welt all use the same verified
    # fire-rate check.  The chance table is indexed by the exported rank (rank 5
    # is 35%); the trailing entries are unused generic script values.
    bleed = _bleed_adapter(mod, path, internal, scripts, rank)
    if bleed is not None:
        return bleed

    # Prototype Shock Coils has a normal +electric effect plus one independent
    # 20% electricity proc per damaging event.
    if (
        internal == "NightwaveLasGooPistolAugmentMod"
        and path == "/Lotus/Upgrades/Mods/Pistol/Event/Nightwave/NightwaveLasGooPistolAugmentMod"
    ):
        script = scripts.get("IndependentStatusProcOnDamage.lua")
        if (
            isinstance(script, Mapping)
            and script.get("_procType") == "PT_ELECTROCUTION"
            and _close(script.get("_statusChance"), 0.2)
            and _has_effect(mod, "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "DT_ELECTRICITY", 0.15)
        ):
            return RuntimeAdapter(
                key="prototype-shock-coils",
                kind="independent_proc",
                source_path=path,
                rank=rank,
                damage_type="DT_ELECTRICITY",
                chance=0.2,
                proc_type="PT_ELECTROCUTION",
            )

    # Range Advantage's values are additive damage bonuses (+50% .. +300%) and
    # require no enemy within ten metres.  ``nearest_enemy_distance`` is kept
    # separate from shot distance in Scenario.
    if (
        internal == "NightwaveAkjagaraAugmentMod"
        and path == "/Lotus/Upgrades/Mods/Rifle/Event/Nightwave/NightwaveAkjagaraAugmentMod"
    ):
        script = scripts.get("ProjectileDamageNoEnemiesOverDistance.lua")
        bonuses = _number_tuple(script.get("_damageMultiplier")) if isinstance(script, Mapping) else ()
        ranges = _number_tuple(script.get("_rangeRequired")) if isinstance(script, Mapping) else ()
        if (
            isinstance(script, Mapping)
            and len(bonuses) >= 6
            and len(ranges) >= 1
            and all(_close(a, b) for a, b in zip(bonuses[:6], (0.5, 1, 1.5, 2, 2.5, 3)))
            and _close(ranges[0], 10)
            and _has_effect_script(mod, "ProjectileDamageNoEnemiesOverDistance.lua")
            and rank < len(bonuses)
        ):
            return RuntimeAdapter(
                key="range-advantage",
                kind="range_damage",
                source_path=path,
                rank=rank,
                damage_bonus=bonuses[rank],
                range_required=ranges[0],
            )

    # Spectral Serration is ordinary damage while PM_CLOAK is active; the Lua
    # wrapper only supplies the HUD/invisibility condition.
    if (
        internal == "WeaponDamageAmountInvisibleMod"
        and path == "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountInvisibleMod"
        and _has_effect(mod, "WEAPON_DAMAGE_AMOUNT", "DT_ANY", 0.3, valid_modifier="PM_CLOAK")
        and _has_effect_script(mod, "WeaponDamageAmountInvisibleMod.lua")
    ):
        return RuntimeAdapter(
            key="spectral-serration",
            kind="cloak_damage",
            source_path=path,
            rank=rank,
            damage_bonus=0.3 * (rank + 1),
        )

    return None


def _bleed_adapter(
    mod: Mapping[str, Any],
    path: str,
    internal: str,
    scripts: Mapping[str, Mapping[str, Any]],
    rank: int,
) -> RuntimeAdapter | None:
    canonical: tuple[str, str, str] | None = None
    if (
        internal == "WeaponBleedOnImpactPistolMod"
        and path == "/Lotus/Upgrades/Mods/Pistol/WeaponBleedOnImpactPistolMod"
    ):
        canonical = ("hemorrhage", "DT_SLASH", "WEAPON_SLASH_PROC_ON_IMPACT")
    elif (
        internal == "WeaponBleedOnImpactProcRifleMod"
        and path == "/Lotus/Upgrades/Mods/Rifle/WeaponBleedOnImpactProcRifleMod"
    ):
        canonical = ("internal-bleeding", "DT_SLASH", "WEAPON_SLASH_PROC_ON_IMPACT")
    elif (
        internal == "WeaponMagneticOnImpactShotgunMod"
        and path == "/Lotus/Upgrades/Mods/Shotgun/WeaponMagneticOnImpactShotgunMod"
    ):
        canonical = ("magnetic-welt", "DT_MAGNETIC", "WEAPON_MAGNETIC_PROC_ON_IMPACT")
    if canonical is None:
        return None
    script = scripts.get("BleedOnImpactFireRateCheck.lua")
    if not isinstance(script, Mapping):
        return None
    chances = _number_tuple(script.get("_baseProcChance"))
    if (
        not chances
        or rank >= len(chances)
        or not _close(script.get("_fireRateDoubleBuff"), 2.5)
        or script.get("_modProcType") != canonical[2]
        or not _has_effect_script(mod, "BleedOnImpactFireRateCheck.lua")
    ):
        return None
    # The current card's max rank is 5; retain the raw rank-indexed value and do
    # not extrapolate beyond the table.
    chance = chances[rank]
    if not 0.0 <= chance <= 1.0:
        return None
    return RuntimeAdapter(
        key=canonical[0],
        kind="impact_conversion",
        source_path=path,
        rank=rank,
        damage_type=canonical[1],
        chance=chance,
        fire_rate_threshold=2.5,
        fire_rate_multiplier=2.0,
        proc_type=canonical[2],
    )


def _apply_scripts(value: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Mapping[str, Any]] = {}
    apply = value.get("apply")
    if not isinstance(apply, Mapping):
        return result
    script = str(apply.get("Script") or "")
    if script:
        result[script.replace("\\", "/").rsplit("/", 1)[-1]] = apply
    return result


def _has_effect(
    mod: Mapping[str, Any], upgrade_type: str, damage_type: str, value_per_rank: float,
    *, valid_modifier: str | None = None,
) -> bool:
    for effect in mod.get("effects") or ():
        if not isinstance(effect, Mapping):
            continue
        if effect.get("upgradeType") != upgrade_type or effect.get("damageType") != damage_type:
            continue
        if not _close(effect.get("valuePerRank"), value_per_rank):
            continue
        if valid_modifier is not None and valid_modifier not in (effect.get("validModifiers") or ()):
            continue
        return True
    return False


def _has_effect_script(mod: Mapping[str, Any], basename: str) -> bool:
    top = mod.get("runtimeScripts")
    if isinstance(top, Mapping):
        apply = top.get("apply")
        if isinstance(apply, Mapping) and str(apply.get("Script") or "").replace("\\", "/").endswith(basename):
            return True
    for effect in mod.get("effects") or ():
        if not isinstance(effect, Mapping):
            continue
        for key in ("runtimeScripts", "localizationScript"):
            value = effect.get(key)
            if isinstance(value, Mapping) and str(value.get("Script") or "").replace("\\", "/").endswith(basename):
                return True
    return False


def _number_tuple(value: Any) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return ()
        number = float(item)
        if not math.isfinite(number):
            return ()
        result.append(number)
    return tuple(result)


def _close(value: Any, expected: float, *, tolerance: float = 1e-5) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) and math.isclose(float(value), expected, rel_tol=tolerance, abs_tol=tolerance)


# Projectile scripts are intentionally kept separate from Mod ``runtimeScripts``.
# These adapters only validate an exact script/function/parameter signature.  They
# do not execute Lua and therefore expose the remaining transition uncertainty to
# the event layer instead of folding it into damage totals.
_PROJECTILE_SCRIPT_FIELDS = (
    "OnProjectileStartScript",
    "OnProjectileContactScript",
    "OnProjectileDeathScript",
    "OnProjectileStackedScript",
    "OnProjectileStoppedScript",
    "OnGlaiveImpactScript",
    "ScriptInstance",
)
_RADIAL_MULTIPLIERS = (0.5, 0.8, 1.1, 1.4, 1.7, 2.0)


def resolve_projectile_runtime_adapters(
    projectile: Mapping[str, Any], projectile_path: str | None = None
) -> list[dict[str, Any]]:
    """Return exact, fail-closed adapters for known projectile Lua signatures.

    The returned records are JSON-ready and deliberately split into two layers:
    ``status=exact`` means the script signature and numeric parameters match a
    frozen raw record; each transition may still be ``partial`` when its Lua body
    decides whether to replace, add, or spawn damage.  Callers must keep those
    derived transitions out of safe aggregate damage until the body is verified.
    """
    entries = _projectile_script_entries(projectile)
    if not entries:
        return []
    adapters: list[dict[str, Any]] = []

    quanta = [
        entry
        for entry in entries
        if _script_basename(entry["script"]) == "CrpShockRifle.lua"
        and entry["function"] == "ProjectileEffects"
        and _radial_signature(entry["params"])
    ]
    if quanta:
        params = {
            "_radialDmgPct": list(_number_tuple(quanta[0]["params"].get("_radialDmgPct"))),
            "_radialRadius": float(quanta[0]["params"]["_radialRadius"]),
        }
        if projectile.get("MaxBounces") is not None:
            params["MaxBounces"] = deepcopy(projectile["MaxBounces"])
        adapters.append(
            _projectile_adapter(
                key="quanta-projectile-effects",
                kind="radial_script",
                entries=quanta,
                projectile_path=projectile_path,
                parameters=params,
                transitions=[
                    {
                        "id": "radial-death",
                        "kind": "runtimeRadialTransition",
                        "trigger": "projectile-death",
                        "baseSource": "ExplosiveAttack",
                        "multipliers": list(params["_radialDmgPct"]),
                        "multiplierRange": [
                            min(params["_radialDmgPct"]),
                            max(params["_radialDmgPct"]),
                        ],
                        "radius": params["_radialRadius"],
                        "support": "partial",
                        "unsupported": ["script-radial-transition-unverified"],
                    }
                ],
                unsupported=["script-radial-transition-unverified"],
            )
        )

    mutalist = [
        entry
        for entry in entries
        if _script_basename(entry["script"]) == "InfCrpShockSwarm.lua"
        and entry["function"] == "OnOrbDestroyed"
        and _radial_signature(entry["params"])
    ]
    if mutalist:
        params = {
            "_radialDmgPct": list(_number_tuple(mutalist[0]["params"].get("_radialDmgPct"))),
            "_radialRadius": float(mutalist[0]["params"]["_radialRadius"]),
        }
        for key in ("MaxProjectileStack", "AttachSpecialAtThisStack", "ResetMaxLifeOnStack"):
            if projectile.get(key) is not None:
                params[key] = deepcopy(projectile[key])
        if projectile.get("MaxBounces") is not None:
            params["MaxBounces"] = deepcopy(projectile["MaxBounces"])
        transitions: list[dict[str, Any]] = []
        if isinstance(params.get("MaxProjectileStack"), (int, float)):
            transitions.append(
                {
                    "id": "stack-gate",
                    "kind": "runtimeStackTransition",
                    "trigger": "projectile-stack",
                    "maxStack": params["MaxProjectileStack"],
                    "attachAtStack": params.get("AttachSpecialAtThisStack"),
                    "resetMaxLifeOnStack": bool(params.get("ResetMaxLifeOnStack")),
                    "support": "exact",
                }
            )
        transitions.append(
            {
                "id": "radial-death",
                "kind": "runtimeRadialTransition",
                "trigger": "projectile-death",
                "baseSource": "shieldDamageData",
                "conditionText": "Equip Buried Debts; when the orb is destroyed, explode using its absorbed projectile damage and the augment rank multiplier.",
                "multipliers": list(params["_radialDmgPct"]),
                "multiplierRange": [
                    min(params["_radialDmgPct"]),
                    max(params["_radialDmgPct"]),
                ],
                "radius": params["_radialRadius"],
                "damageDataEvidence": {
                    "baseAmountSource": "shield.baseAmount",
                    "baseAmountFormula": "shield.baseAmount * rankMultiplier",
                    "rankMultiplierSource": "_radialDmgPct",
                    "rankIndex": "min(arbitrationModRank + 1, len(_radialDmgPct))",
                    "rankClamp": [1, len(params["_radialDmgPct"])],
                    "damageTypeProportionsSource": "shield",
                    "damageTypeRange": ["DT_IMPACT", "DT_CORROSIVE"],
                    "radius": params["_radialRadius"],
                    "hostAuthoritative": True,
                    "staticCoverOnly": True,
                },
                "support": "partial",
                "unsupported": ["script-radial-transition-unverified"],
            }
        )
        adapters.append(
            _projectile_adapter(
                key="mutalist-quanta-orb",
                kind="stacked_radial_script",
                entries=mutalist,
                projectile_path=projectile_path,
                parameters=params,
                transitions=transitions,
                unsupported=["script-radial-transition-unverified"],
            )
        )

    stug = [
        entry
        for entry in entries
        if _script_basename(entry["script"]) == "StugIncarnon.lua"
        and entry["function"]
        in {"OnIncarnonProjectileDeath", "OnIncarnonProjectileStack"}
        and _stug_signature(entry["params"])
    ]
    if stug:
        params: dict[str, Any] = {}
        for key in (
            "_deathExplosionMult",
            "_maxExplosiveBounces",
            "_maxSecondaryProjectilesCount",
            "_maxSecondaryProjectilesCountForMirror",
            "_secondaryProjectile",
        ):
            for entry in stug:
                if key in entry["params"] and entry["params"][key] not in (None, ""):
                    params[key] = deepcopy(entry["params"][key])
                    break
        if projectile.get("MaxProjectileStack") is not None:
            params["MaxProjectileStack"] = deepcopy(projectile["MaxProjectileStack"])
        transitions: list[dict[str, Any]] = []
        if any(entry["function"] == "OnIncarnonProjectileDeath" for entry in stug):
            transitions.append(
                {
                    "id": "death-transform",
                    "kind": "runtimeDamageTransform",
                    "trigger": "projectile-death",
                    "baseSource": "ExplosiveAttack",
                    "multiplier": params.get("_deathExplosionMult"),
                    "support": "partial",
                    "unsupported": ["stug-death-transform-unverified"],
                }
            )
            secondary = params.get("_secondaryProjectile")
            count = params.get("_maxSecondaryProjectilesCount")
            bounces = params.get("_maxExplosiveBounces")
            if isinstance(secondary, str) and secondary and isinstance(count, (int, float)):
                transitions.append(
                    {
                        "id": "secondary-spawn",
                        "kind": "runtimeSpawnTransition",
                        "trigger": "projectile-death",
                        "projectile": secondary,
                        "countRange": [0, int(count)],
                        "maxBounces": bounces,
                        "support": "partial",
                        "unsupported": ["stug-secondary-projectile-unresolved"],
                    }
                )
        if any(entry["function"] == "OnIncarnonProjectileStack" for entry in stug):
            transitions.append(
                {
                    "id": "stack-transform",
                    "kind": "runtimeStackTransition",
                    "trigger": "projectile-stack",
                    "maxStack": projectile.get("MaxProjectileStack"),
                    "support": "partial",
                    "unsupported": ["stug-stack-damage-unresolved"],
                }
            )
        adapters.append(
            _projectile_adapter(
                key="stug-incarnon",
                kind="incarnon_stack_script",
                entries=stug,
                projectile_path=projectile_path,
                parameters=params,
                transitions=transitions,
                unsupported=sorted(
                    {
                        reason
                        for transition in transitions
                        for reason in transition.get("unsupported", ())
                    }
                ),
            )
        )

    nokko = [
        entry
        for entry in entries
        if _script_basename(entry["script"]) == "NokkoArchGunInnateMod.lua"
        and entry["function"] in {"OnProjectileStart", "CheckForNokkoMushroomHit"}
    ]
    if nokko:
        params: dict[str, Any] = {}
        for entry in nokko:
            value = entry["params"].get("_scaleDurationAsFunctionOfFireRate")
            if _close(value, 0.75):
                params["_scaleDurationAsFunctionOfFireRate"] = float(value)
                break
        transitions: list[dict[str, Any]] = []
        if any(entry["function"] == "OnProjectileStart" for entry in nokko):
            transitions.append(
                {
                    "id": "flight-duration",
                    "kind": "runtimeStateTransition",
                    "trigger": "projectile-start",
                    "parameter": "_scaleDurationAsFunctionOfFireRate",
                    "value": params.get("_scaleDurationAsFunctionOfFireRate"),
                    "support": "partial",
                    "unsupported": ["nokko-flight-duration-unverified"],
                }
            )
        if any(entry["function"] == "CheckForNokkoMushroomHit" for entry in nokko):
            transitions.append(
                {
                    "id": "mushroom-contact",
                    "kind": "runtimeStateTransition",
                    "trigger": "projectile-contact",
                    "support": "partial",
                    "unsupported": ["nokko-mushroom-state-unresolved"],
                }
            )
        adapters.append(
            _projectile_adapter(
                key="arbucep-innate",
                kind="guided_state_script",
                entries=nokko,
                projectile_path=projectile_path,
                parameters=params,
                transitions=transitions,
                unsupported=sorted(
                    {
                        reason
                        for transition in transitions
                        for reason in transition.get("unsupported", ())
                    }
                ),
            )
        )

    return adapters


def resolve_projectile_runtime_adapter(
    projectile: Mapping[str, Any], projectile_path: str | None = None
) -> dict[str, Any] | None:
    """Compatibility helper returning the first matching projectile adapter."""
    adapters = resolve_projectile_runtime_adapters(projectile, projectile_path)
    return adapters[0] if adapters else None


def _projectile_script_entries(projectile: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for event in _PROJECTILE_SCRIPT_FIELDS:
        raw = projectile.get(event)
        if not isinstance(raw, Mapping):
            continue
        script = str(raw.get("Script") or "").replace("\\", "/")
        function = str(raw.get("Function") or "")
        if not script or not function:
            continue
        entries.append(
            {
                "event": event,
                "script": script,
                "function": function,
                "params": {
                    str(key): deepcopy(value)
                    for key, value in raw.items()
                    if str(key).startswith("_")
                },
            }
        )
    return entries


def _projectile_adapter(
    *,
    key: str,
    kind: str,
    entries: list[dict[str, Any]],
    projectile_path: str | None,
    parameters: Mapping[str, Any],
    transitions: list[dict[str, Any]],
    unsupported: list[str],
) -> dict[str, Any]:
    signatures = [
        {
            "event": entry["event"],
            "script": entry["script"],
            "function": entry["function"],
            "params": deepcopy(entry["params"]),
        }
        for entry in entries
    ]
    result: dict[str, Any] = {
        "key": key,
        "kind": kind,
        "status": "exact",
        "script": signatures[0]["script"],
        "functions": list(dict.fromkeys(item["function"] for item in signatures)),
        "parameters": deepcopy(dict(parameters)),
        "signatures": signatures,
        "transitions": deepcopy(transitions),
        "unsupported": list(dict.fromkeys(unsupported)),
    }
    if projectile_path:
        result["projectile"] = projectile_path
    return result


def _script_basename(script: Any) -> str:
    return str(script or "").replace("\\", "/").rsplit("/", 1)[-1]


def _radial_signature(params: Mapping[str, Any]) -> bool:
    values = _number_tuple(params.get("_radialDmgPct"))
    return len(values) == len(_RADIAL_MULTIPLIERS) and all(
        math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-5)
        for a, b in zip(values, _RADIAL_MULTIPLIERS)
    ) and _close(params.get("_radialRadius"), 15)


def _stug_signature(params: Mapping[str, Any]) -> bool:
    multiplier = params.get("_deathExplosionMult")
    bounces = params.get("_maxExplosiveBounces")
    count = params.get("_maxSecondaryProjectilesCount")
    mirror = params.get("_maxSecondaryProjectilesCountForMirror")
    return (
        _close(multiplier, 2.5)
        and isinstance(bounces, (int, float))
        and not isinstance(bounces, bool)
        and math.isfinite(float(bounces))
        and bounces >= 0
        and isinstance(count, (int, float))
        and not isinstance(count, bool)
        and math.isfinite(float(count))
        and count >= 0
        and isinstance(mirror, (int, float))
        and not isinstance(mirror, bool)
        and math.isfinite(float(mirror))
        and mirror >= 0
    )


def verified_crux_condition(record):
    # Exact raw Lua parameters; unknown scripts still fail closed.
    if record.get('path') != '/Lotus/Upgrades/CosmeticEnhancers/Offensive/StatusAndAmmoEfficiencyOnWeakpointHit':
        return None
    apply = (record.get('runtimeScripts') or {}).get('apply', {})
    expected = {'_ammoEfficiencyBase': -.01, '_ammoEfficiencyPerLevel': -.01,
                '_statusChanceBase': .05, '_statusChancePerLevel': .05,
                '_duration': 10, '_maxStacks': 10}
    if (apply.get('Script') != 'StatusAndAmmoEfficiencyOnWeakpointHit.lua'
            or apply.get('Function') != 'ApplyUpgrade'
            or any(not _close(apply.get(k), v) for k, v in expected.items())):
        return None
    # Relative to each attack part's base chance; the old materialized ADD
    # incorrectly supplied +300 percentage points at max rank/stacks.
    # Rebuild from the verified script, leaving the frozen raw record intact.
    effects = [
        dict(upgradeType='WEAPON_PROC_CHANCE', operation='STACKING_MULTIPLY', valuePerRank=.05),
        dict(upgradeType='WEAPON_AMMO_CONSUME_RATE', operation='STACKING_MULTIPLY', valuePerRank=-.01),
    ]
    return {'sourcePath': record['path'], 'conditionTag': 'OnWeakpointHitCondition',
            'conditions': ['OnWeakpointHitCondition'], 'duration': 10, 'maxStacks': 10,
            'stackMode': 'reset', 'effects': effects}


COMPRESSION_PATH = '/Lotus/Upgrades/CosmeticEnhancers/Utility/ConvergeRadialAttackOnAim'

def compression_configuration(record, rank):
    if (record.get('path') != COMPRESSION_PATH or isinstance(rank,bool)
            or not isinstance(rank,int) or not 0 <= rank <= 5):
        return None
    script=(record.get('runtimeScripts') or {}).get('apply') or {}
    expected={'_damageMultPerMeterLostBase':.5,'_damageMultPerMeterLostPerLevel':.1,
              '_ammoEfficiencyPerMeterLostBase':.03,'_ammoEfficiencyPerMeterLostPerLevel':.005,
              '_explosionRadiusBase':-.8,'_explosionRadiusPerLevel':0.}
    if (str(script.get('Script') or '').rsplit('/',1)[-1] != 'ConvergeRadialAttackOnAim.lua'
            or script.get('Function') != 'OnBehaviorChange'
            or not all(_close(script.get(k),v) for k,v in expected.items())):
        return None
    return dict(damagePerMeter=.5+.1*rank,ammoPerMeter=.03+.005*rank)


STUG_EVOLUTIONS = '/Lotus/Weapons/Grineer/Pistols/GrineerCrossbow/StugIncarnonEvolutions/'
MQ_AUGMENT = '/Lotus/Upgrades/Mods/Rifle/Event/Arbitration/InfCrpShockSwarmRifleArbitrationMod'


def mq_augment_multiplier(record,rank):
    if record.get('path')!=MQ_AUGMENT or not isinstance(rank,int) or isinstance(rank,bool) or not 0<=rank<=5:
        return None
    effects = record.get('effects') or []
    if len(effects)!=1 or effects[0].get('upgradeType')!='NONE' or effects[0].get('valuePerRank')!=0:
        return None
    script = effects[0].get('localizationScript') or {}
    values = script.get('_radialDmgPct') or []
    if (script.get('Script')!='/Lotus/Scripts/WeaponAttachments/InfCrpShockSwarm.lua'
            or script.get('Function')!='GetLocValues' or script.get('_radialRadius')!=15
            or len(values)!=6 or not all(_close(a,b) for a,b in zip(values,(.5,.8,1.1,1.4,1.7,2.)))):
        return None
    return float(values[rank])


def double_tap_configuration(record,rank):
    if (record.get('path')!='/Lotus/Upgrades/Mods/PvPMods/Rifle/MoreDamageonTripleTapRifleMod'
            or record.get('maxRank')!=3 or not isinstance(rank,int) or isinstance(rank,bool) or not 0<=rank<=3):
        return None
    script=(record.get('runtimeScripts') or {}).get('apply') or {}
    if (script.get('Script')=='/Lotus/Upgrades/CosmeticEnhancers/Offensive/BonusDamageOnNextHit.lua'
            and script.get('Function')=='ApplyUpgrade' and _close(script.get('_bonusDamagePercent'),.05)
            and _close(script.get('_multTimeWindow'),.5)):
        per=.05*(rank+1)
        return dict(perHit=per,maximum=int(math.floor(4./per+1e-9)),duration=.5*(rank+1))
    return None


def miter_charge_aoe(record):
    if record.get('path')!='/Lotus/Weapons/Grineer/LongGuns/GrineerSawbladeGun/MiterIncarnonEvolutions/MiterEvoTier3A':
        return None
    from .incarnon_conditions import script_entries
    scripts=list(script_entries(record.get('runtimeScripts')))
    if (len(scripts)==1 and scripts[0].get('Script')=='ProjectileIndexOnExtraCharge.lua'
            and scripts[0].get('Function')=='StartMod'):
        # Native charged projectile supplies Amount=700 and radius=5. The
        # charged state's multiplier supplies 2x; the one-second hold is fixed.
        return dict(damage=700.,radius=5.,holdSeconds=1.)
    return None


def incarnon_stat_conversion(record):
    """Native base-stat conversion, evaluated after the source's MOD bucket."""
    from .incarnon_conditions import script_entries
    scripts = list(script_entries(record.get('runtimeScripts')))
    effects = record.get('effects') or []
    if (record.get('conditionalEffects') or len(scripts) != 1 or len(effects) != 1
            or effects[0].get('upgradeType') != 'NONE' or effects[0].get('valuePerRank') != 0):
        return None
    script = scripts[0]
    if (script.get('Script') != '/Lotus/Scripts/Mods/WeaponAddBaseStatForModdedStat.lua'
            or script.get('Function') != 'OnUpgradeApplied' or script.get('_isDynamic') != 1):
        return None
    source, target = script.get('_sourceModdedStatType'), script.get('_targetBaseStatType')
    if {source, target} != {'WEAPON_CRIT_CHANCE', 'WEAPON_PROC_CHANCE'}:
        return None
    fraction, maximum = script.get('_bonusPercentage'), script.get('_bonusMaxCap')
    if not ((source == 'WEAPON_PROC_CHANCE' and _close(fraction, .25) and _close(maximum, .35))
            or (source == 'WEAPON_CRIT_CHANCE' and _close(fraction, .3) and _close(maximum, .4))):
        return None
    return dict(source=source, target=target, fraction=float(fraction), maximum=float(maximum))


SHIELD_DAMAGE_CONDITION = '/Lotus/Upgrades/CosmeticEnhancers/Defensive/OnShieldDamageCondition'
SELF_BREAK_EVENTS = ('on-shield-broken', 'on-overguard-broken')


def passive_incarnon_condition(condition):
    """A conditional block that is on without its trigger.

    ApplyUpgradesByDefault = 1 (Lex Prime Hoplite Virtue +20), and the
    untagged own-shield-damage gate the game shows as plain "+N Base Damage"
    (Lex Hoplite Virtue +80; wiki: base damage, the shield-break +80 is the
    separate tagged sub-upgrade).
    """
    if condition.get('applyUpgradesByDefault') == 1:
        return True
    return (condition.get('conditions') == [SHIELD_DAMAGE_CONDITION] and not condition.get('conditionTag')
            and not condition.get('runtimeScripts'))


def self_break_condition(condition):
    """Gate on the player's own shield / overguard breaking."""
    from .manual_combat import condition_kind
    kind = condition_kind(condition)
    if kind in ('on-self-shield-broken', 'on-self-overguard-broken'):
        return True
    return bool((condition.get('nativeEvent') or {}).get('actorOnly')) and kind in SELF_BREAK_EVENTS


def self_break_forced(scenario):
    """Own shield / overguard break gates need the Warframe; forced unless the
    user switches to the event timeline (combatState.selfShieldBreakForced)."""
    return scenario.combat_state.get('selfShieldBreakForced', True) is not False


def verified_incarnon_condition(record, condition):
    verified = verified_stug_condition(record, condition)
    if verified:
        return verified
    path = str(record.get('path') or '')
    source = str(condition.get('sourcePath') or '')
    terms = condition.get('effects') or []
    script = (condition.get('runtimeScripts') or {}).get('apply') or {}
    names={str(x).rsplit('/',1)[-1] for x in condition.get('conditions') or []}
    if (path.endswith('/EntratiWristGunEvoTier4B') and len(terms)==1
            and terms[0].get('upgradeType')=='WEAPON_DAMAGE_AMOUNT'
            and _close(terms[0].get('valuePerRank'),2.)
            and names=={'EvoTier4BOnPunchthroughCondition','EvoTier4BOnIncarnonPunchthroughCondition'}):
        return {**condition,'runtimeScripts':{},'eventKind':'on-onos-damage-condition',
                'conditionText':'基础形态穿透命中后续敌人，或灵化爆发攻击累计命中 2 次后：+200% 武器伤害，持续 10 秒。'}
    if 'EvoRifleOnTwoHeadshotsCondition' in names and str(record.get('path') or '').endswith('EvoRifleDamageOnHeadshots'):
        return {**condition,'runtimeScripts':{},'eventKind':'on-headshot','requiredCount':2,'requiredTime':2,'maxStacks':1,
                'conditionText':'2 秒内命中头部 2 次后，爆头伤害增加 50%，持续 8 秒。'}
    if names=={'OnSybarisIncarnonActivatedCondition'} and 'SybarisEvoTier3ASubMod' in source:
        return {**condition,'formGate':True,'runtimeScripts':{}}
    if names=={'RifleOnFullBurstHit'} and 'SybarisEvoTier3B' in source:
        return {**condition,'eventKind':'on-burst-hit','resetOn':['on-reload']}
    if (names=={'OnWarframeOnlyAbilityCondition'} and '/DualToxocystIncarnonEvolutions/' in path
            and len(terms)==1 and terms[0].get('upgradeType')=='WEAPON_FIRE_ITERATIONS'
            and _close(terms[0].get('valuePerRank'),.05) and condition.get('maxStacks')==20):
        return {**condition,'eventKind':'on-warframe-ability','initialStateKey':'abilityUses',
                'conditionText':'玩家施放战甲技能后增加一层多重射击，每层 +5%，最多 20 层；从显式战斗状态读取已施法次数和后续施法时点。'}
    if (names=={'ZylokOnBurstHeadshot'} and '/ZylokIncarnonEvolutions/' in path
            and len(terms)==1 and terms[0].get('upgradeType')=='WEAPON_DAMAGE_AMOUNT'
            and terms[0].get('operation')=='ADD_BASE' and terms[0].get('valuePerRank')==20
            and condition.get('maxStacks')==3):
        return {**condition,'eventKind':'on-burst-headshot','resetOn':['on-reload','on-transform'],
                'conditionText':'基础形态一次按下和松开扳机的两发都爆头后，增加 +20 基础伤害，最多 3 层；换弹、进入或退出灵化形态时清空。'}
    if (script.get('Script')=='/Lotus/Scripts/Mods/ShieldOnCondition.lua' and script.get('Function')=='StartMod'
            and script.get('_shieldAmount')==100 and script.get('_allowOvershields')==1
            and '/SomaIncarnonEvolutions/' in path):
        return {**condition,'runtimeScripts':{},'utilityOnly':True,
                'conditionText':'武器的切割异常跳伤击杀后恢复 100 护盾，允许形成过载护盾；当前伤害基准不模拟玩家受击，所需过载护盾状态由场景输入。'}
    if (names=={'OnHitwithElecPistolCondition'} and '/FurisIncarnonEvolutions/' in path
            and len(terms)==1 and terms[0].get('upgradeType')=='WEAPON_FIRE_ITERATIONS'
            and terms[0].get('operation')=='ADD' and _close(terms[0].get('valuePerRank'),.4)
            and condition.get('maxStacks')==3 and condition.get('duration')==2):
        # The EE challenge is binary-only in this dump; the pinned WFSim
        # Stormburst contract supplies per-stack expiry and the victim gate.
        return {**condition,'eventKind':'on-hit','stackMode':'per-stack',
                'nativeEvent':dict(kind='on-hit',victimProcType='DT_ELECTRICITY',requiredCount=1),
                'conditionText':'命中已经带有电击异常的目标后，额外 +0.4 多重射击，最多 3 层；每层独立持续 2 秒。'}
    if (path=='/Lotus/Upgrades/Evolutions/Shotgun/EvoShotgunAmmoEffOnPunchThrough'
            and names=={'EvoShotgunOnPunchthroughCondition'} and len(terms)==1
            and terms[0].get('upgradeType')=='WEAPON_AMMO_CONSUME_RATE'
            and _close(terms[0].get('valuePerRank'),-.7) and condition.get('duration')==20):
        return {**condition,'eventKind':'on-three-enemy-punchthrough',
                'conditionText':'同一个弹丸穿透并命中 3 名不同敌人后，弹药消耗减少 70%，持续 20 秒；后续目标数需显式设置为至少 2。'}
    if (script.get('Script')=='/Lotus/Scripts/Mods/WeaponEquipBuffs.lua' and script.get('Function')=='StartMod'
            and script.get('_previousWeaponSlot')=='SLOT_2' and condition.get('duration') in {3,4}
            and terms and all(e.get('upgradeType') in {'WEAPON_CRIT_CHANCE','WEAPON_CRIT_DAMAGE'} for e in terms)):
        return {**condition,'runtimeScripts':{},'eventKind':'on-equip-from-primary','resetOn':['on-holster'],
                'conditionText':f"从主武器切换至当前武器后，获得暴击基数加成，持续 {condition['duration']:g} 秒。"}
    if (script.get('Script')=='/Lotus/Scripts/Mods/NoEnemiesInRangeBuff.lua' and script.get('Function')=='ApplyUpgrade'
            and script.get('_upgradeType')=='WEAPON_FIRE_ITERATIONS' and script.get('_operation')=='STACKING_MULTIPLY'
            and script.get('_rangeRequired')==[5] and len(terms)==1):
        return {**condition,'runtimeScripts':{},'actorGate':dict(kind='no-enemies',radius=5.),
                'conditionText':f"5 米内没有敌人时，多重射击增加 {terms[0]['valuePerRank']*100:g}%。"}
    if (script.get('Script')=='/Lotus/Scripts/Mods/RestoreAmmoOnCondition.lua' and script.get('Function')=='StartMod'
            and script.get('_restoreFromAmmoPool')==1 and len(terms)==1
            and terms[0].get('upgradeType')=='WEAPON_CLIP_MAX' and terms[0].get('operation')=='ADD_BASE'
            and _close(terms[0].get('valuePerRank'),script.get('_ammoAmount'))
            and (condition.get('nativeEvent') or {}).get('kind')=='on-reload-empty-complete'):
        return {**condition,'runtimeScripts':{},'refillMagazineGrowth':True}
    if ammo_restore_configuration(record):
        return {**condition,'runtimeScripts':{},'sequenceGate':'ammo-restore',
                'conditionText':'按已验证的命中条件将备用弹药移入弹匣；不恢复灵化充能，也不省略正常装填事件。'}
    if onos_ammo_refund(record):
        return {**condition,'runtimeScripts':{},'sequenceGate':'reserve-ammo',
                'conditionText':'武器击杀后补充 10 发备用弹药；当前采用无限备用弹药口径，不改变弹匣、装填和伤害。'}
    if reserve_ammo_refund(record):
        return {**condition,'runtimeScripts':{},'sequenceGate':'reserve-ammo',
                'conditionText':'穿透命中后续目标时有 20% 概率恢复 10% 备用弹药；无限备用弹药口径下不改变弹匣、装填和伤害。'}
    if latron_puncture_strip(record):
        return {**condition,'runtimeScripts':{},'sequenceGate':'target-armor-strip',
                'conditionText':'每个施加穿刺异常的武器弹丸永久削减目标 20% 初始护甲，同一弹丸多层穿刺只削一次；五次合格弹丸完全削甲。'}
    if (path=='/Lotus/Upgrades/Evolutions/Shotgun/EvoShotgunShellReloadToggle'
            and script=={'Script':'EvoShotgunShellReloadToggle.lua','Function':'ToggleUpgrade'}):
        return {**condition,'runtimeScripts':{},'eventKind':'on-reload-toggle','toggleOn':'on-reload-complete',
                'maxStacks':1,'duration':0,'effects':[dict(upgradeType='WEAPON_PROJECTILE_SPEED',operation='STACKING_MULTIPLY',valuePerRank=1.)],
                'conditionText':'完整装填后在 +4 米穿透和 +100% 投射物速度之间切换；投射物速度作用于衰减距离，穿透不增加单目标伤害。'}
    if onos_crits_for_hits(record):
        return {**condition,'runtimeScripts':{},'sequenceGate':'onos-charge',
                'conditionText':'灵化蓄力阶段命中敌人（含武器异常跳伤）增加一层；每层使最终爆发的暴击率和暴击伤害增加 5%，最多 50 层；进入爆发后清空。'}
    if (path.endswith('/EntratiWristGunEvoTier4A')
            and condition.get('conditions')==['EvoTier4AOnConsecutiveHeadshotCondition']
            and condition.get('maxStacks')==4 and len(terms)==1
            and terms[0].get('upgradeType')=='WEAPON_HEADSHOT_MULTIPLIER'
            and _close(terms[0].get('valuePerRank'),.3)
            and 'EntratiWristGunIncarnonConsecutiveHeadshots.lua' in str(record.get('runtimeScripts'))):
        return {**condition,'runtimeScripts':{},'eventKind':'on-consecutive-headshot','minimumConsecutive':2,
                'conditionText':'连续爆头达到 2 次后，每次增加 +30% 爆头伤害，最多 4 层；身体命中会清空。'}
    felarx = '/Lotus/Upgrades/Evolutions/Shotgun/EvoShotgunShellReloadFireRate'
    if (path == source == felarx
            and condition.get('conditions') == ['EvoShotgunShellReloadCondition']
            and condition.get('maxStacks') == 99 and condition.get('duration') == 1
            and script == {'Script': 'EvoShotgunReloadShellFireRate.lua', 'Function': 'ApplyUpgrade'}
            and len(terms) == 1 and terms[0].get('upgradeType') == 'WEAPON_FIRE_RATE'
            and terms[0].get('operation') == 'STACKING_MULTIPLY'
            and _close(terms[0].get('valuePerRank'), .1)):
        # Native IsInfinite=1; the Challenge emits RELOAD once per shell and
        # resets on PRE_RELOAD/HolsterItem. Duration=1 is not a one-second buff.
        return {**condition, 'runtimeScripts': {}, 'eventKind': 'on-shell-reloaded',
                'duration': 0, 'resetOn': ['on-reload', 'on-holster'],
                'conditionText': '每装入一发弹药获得 +10% 射速，最多 99 层；下一次装填开始或收枪时清空。'}
    from .incarnon_conditions import script_entries
    scripts = list(script_entries(condition.get('runtimeScripts')))
    if len(scripts) != 1:
        return None
    script = scripts[0]
    root = '/Lotus/Scripts/Mods/'
    name = str(script.get('Script') or '')
    if (name=='/Lotus/Upgrades/Mods/ModOnAimGlideOrSlide.lua' and script.get('Function')=='ModApplied'
            and script.get('_mustMatchWeapon')==1 and script.get('_upgradeType')=='WEAPON_AMMO_CONSUME_RATE'
            and script.get('_stackingMode')=='ADD' and len(terms)==1
            and _close(terms[0].get('valuePerRank'),script.get('_value'))):
        return {**condition,'runtimeScripts':{},'actorGate':dict(kind='anyBoolean',keys=['aimGliding','sliding']),
                'conditionText':f"瞄准滑翔或滑行期间：弹药消耗减少 {abs(script['_value'])*100:g}%。"}
    gates = {
        root+'RequireArmor.lua': ('frameArmor','_minArmorRequired'),
        root+'RequireEnergyPool.lua': ('energyPool','_minEnergyPoolRequired'),
        root+'RequireSprintSpeed.lua': ('sprintMultiplier','_minSpeedMultiplier'),
    }
    gate = None
    if name in gates and script.get('Function') == 'StartMod':
        key, parameter = gates[name]
        minimum = script.get(parameter)
        if isinstance(minimum,(int,float)) and not isinstance(minimum,bool) and math.isfinite(minimum) and minimum >= 0:
            gate = dict(kind='minimum', key=key, minimum=float(minimum))
    elif name==root+'RequireEnergySpent.lua' and script.get('Function')=='StartMod':
        required = script.get('_energySpentRequired')
        if isinstance(required,(int,float)) and not isinstance(required,bool) and required>0:
            return {**condition,'runtimeScripts':{},'energyGate':float(required),'eventKind':'on-energy-spent'}
    elif name in {root+'RequireOvershields.lua',root+'ChannelAbilityMod.lua'} and script.get('Function')=='StartMod':
        gate = dict(kind='boolean',key='overshields' if name.endswith('RequireOvershields.lua') else 'channeling')
    elif (name in {root+'UnlockAltMelee.lua','/Lotus/Scripts/WeaponAttachments/ZarimanDagger.lua',
                   '/Lotus/Scripts/WeaponAttachments/ZarimanTonfaWeapon.lua'}
          and script.get('Function')=='OnActivateVoidMode'
          and all(e.get('upgradeType') in {'NONE','WEAPON_MELEE_DAMAGE','WEAPON_RANGE','WEAPON_FIRE_RATE',
                                          'AVATAR_SPRINT_SPEED','AVATAR_PARKOUR_BOOST'} for e in terms)):
        gate = dict(kind='boolean',key='incarnonMeleeActive')
    elif name==root+'RequireEnemyCount.lua' and script.get('Function')=='StartMod':
        radius,per,maximum = (script.get(k) for k in ('_enemyRange','_enemyPerStack','_maxStacks'))
        if all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0 for x in (radius,per,maximum)):
            gate = dict(kind='enemies',radius=float(radius),per=float(per),maximum=float(maximum))
    elif name==root+'OnSelectiveSlotEquipped.lua' and script.get('Function')=='OnUpgradeApplied':
        required = [script[k] for k in ('_equippedRifleWeaponType','_equippedPistolWeaponType','_equippedMeleeWeaponType') if script.get(k)]
        empty = script.get('_unequippedSlots') or []
        if required or empty:
            gate = dict(kind='equipment',required=required,empty=empty)
    if not gate:
        return None
    return {**condition,'runtimeScripts':{},'actorGate':gate}


def onos_crits_for_hits(record):
    if record.get('path')!='/Lotus/Weapons/Thanotech/EntratiWristGun/WristGunIncarnonEvolutions/EntratiWristGunEvoTier4C':
        return None
    conditions = record.get('conditionalEffects') or []
    if len(conditions)!=1:
        return None
    script = (conditions[0].get('runtimeScripts') or {}).get('apply') or {}
    if (script.get('Script')=='EntratiWristGunIncarnonCritsForHits.lua'
            and script.get('Function')=='OnApplySubUpgrade'
            and _close(script.get('_critValuePerTarget'),.05) and script.get('_maxStacks')==50):
        return dict(perHit=.05,maximum=50)
    return None


def onos_ammo_refund(record):
    if record.get('path')!='/Lotus/Weapons/Thanotech/EntratiWristGun/WristGunIncarnonEvolutions/EntratiWristGunEvoTier2C':
        return None
    for condition in record.get('conditionalEffects') or []:
        script=(condition.get('runtimeScripts') or {}).get('apply') or {}
        if (str(script.get('Script') or '').rsplit('/',1)[-1]=='EntratiWristGunIncarnonReplenishAmmoOnKill.lua'
                and script.get('Function')=='OnApplyUpgrade' and script.get('_replenishAmount')==10):
            return dict(amount=10)
    return None


def latron_puncture_strip(record):
    if '/LatronIncarnonEvolutions/' not in str(record.get('path') or ''):
        return None
    for condition in record.get('conditionalEffects') or []:
        script=(condition.get('runtimeScripts') or {}).get('apply') or {}
        if (script.get('Script')=='/Lotus/Upgrades/Boons/Offensive/ReduceArmor.lua'
                and script.get('Function')=='ReduceArmor' and _close(script.get('_armorReduction'),.2)
                and script.get('_operationType')=='STACKING_MULTIPLY'
                and (condition.get('nativeEvent') or {}).get('kind')=='proc-DT_PUNCTURE'):
            return .2
    return None


def ammo_restore_configuration(record):
    for condition in record.get('conditionalEffects') or []:
        script=(condition.get('runtimeScripts') or {}).get('apply') or {}
        event=condition.get('nativeEvent') or {}
        if (record.get('path')=='/Lotus/Upgrades/Evolutions/Rifle/EvoRifleInstantReloadChanceOnHeadshot'
                and script.get('Script')=='/Lotus/Scripts/WeaponAttachments/ZarimanHeavyRifle.lua'
                and script.get('Function')=='GiveInstantReloadOnHeadshotUpgrade'
                and _close(condition.get('chance'),.2)):
            return dict(kind='on-headshot-kill',fraction=1.,chance=.2)
        if (script.get('Script')=='/Lotus/Scripts/Mods/InstantReloadOnCondition.lua' and script.get('Function')=='StartMod'
                and event.get('kind') in {'on-headshot','on-kill'} and _close(script.get('_amountPct'),1.)
                and script.get('_customChance')==1 and not script.get('_customChanceScaleWithLevel')
                and not script.get('_chanceIncrease') and not script.get('_specificAmount')):
            value=dict(kind=event['kind'],fraction=1.)
            if condition.get('chance',1.)!=1.:
                value['chance']=condition['chance']
            return value
        if (script.get('Script')=='/Lotus/Scripts/Mods/RestoreAmmoOnCondition.lua' and script.get('Function')=='StartMod'
                and event.get('victimProcType')=='DT_ELECTRICITY' and script.get('_ammoAmount')==1
                and script.get('_restoreFromAmmoPool')==1):
            if _close(condition.get('chance'),.4):
                return dict(kind='on-hit',victimProcType='DT_ELECTRICITY',amount=1.,chance=.4,oncePerShot=True)
    return None


def reserve_ammo_refund(record):
    value=onos_ammo_refund(record)
    if value:
        return value
    if '/BratonIncarnonEvolutions/' not in str(record.get('path') or ''):
        return None
    for condition in record.get('conditionalEffects') or []:
        script=(condition.get('runtimeScripts') or {}).get('apply') or {}
        if (script.get('Script')=='/Lotus/Scripts/Mods/RestoreAmmoMod.lua'
                and script.get('Function')=='OnUpgradeApplied' and _close(script.get('_ammoRestorePercent'),.1)
                and (condition.get('nativeEvent') or {}).get('kind')=='on-punchthrough'
                and _close(condition.get('chance'),.2)):
            return dict(fraction=.1,chance=.2,kind='on-punchthrough')
    return None


def incarnon_condition_rows(record):
    for raw in record.get('conditionalEffects') or ():
        condition = verified_incarnon_condition(record,raw) or raw
        yield condition
        for child in condition.get('runtimeExtraMods') or ():
            if (condition.get('actorGate') and child.get('conditions')==['DreadOnConsecutiveHit']
                    and child.get('maxStacks')==5 and child.get('nativeInfinite')):
                yield {**child,'runtimeScripts':{},'equipmentGate':condition['actorGate'],
                       'eventKind':'on-hit','resetOn':['on-miss'],
                       'conditionText':'装备绝望和憎恨时，每次命中增加 +10 基础伤害与 +10% 射速，最多 5 层；整次射击未命中时清空。'}


def incarnon_actor_stacks(condition, scenario, weapon=None):
    gate = condition.get('actorGate') or {}
    state = scenario.combat_state
    kind = gate.get('kind')
    if kind=='minimum':
        value = state.get(gate['key'])
        return 1. if value is not None and value>=gate['minimum'] else 0.
    if kind=='no-enemies':
        if scenario.nearest_enemy_distance is not None:
            return float(scenario.nearest_enemy_distance>gate['radius'])
        return float(state.get('nearbyEnemies')==0 and state.get('nearbyRadius',0)>=gate['radius'])
    if kind=='boolean':
        return float(state.get(gate['key']) is True)
    if kind=='anyBoolean':
        return float(any(state.get(key) is True for key in gate['keys']))
    if kind=='enemies':
        if 'nearbyEnemies' not in state or state.get('nearbyRadius',math.inf)>gate['radius']:
            return 0.
        return min(gate['maximum'],math.floor(state['nearbyEnemies']/gate['per']))
    if kind=='equipment':
        if 'equippedWeapons' not in state and gate['required']:
            return 0.
        # Exact native families; the selected weapon may itself be one of the
        # required items. Other gear is an explicit user/account state.
        available = set(state.get('equippedWeapons') or ()) | set((weapon or {}).get('ancestry') or ())
        if (weapon or {}).get('path'):
            available.add(weapon['path'])
        empty_slots = {'LONG_GUN_SLOT':'primary','PISTOL_SLOT':'secondary','MELEE_SLOT':'melee'}
        return float(all(p in available for p in gate['required'])
                     and all(empty_slots.get(s) in state.get('emptySlots',()) for s in gate['empty']))
    return 0.

def verified_stug_condition(record, condition):
    # Source + effect signatures, backed by stug-evolution-conditions.json.
    # NONE=0 is a localization-only reset hint, not a second buff.
    path = str(record.get('path') or '')
    source = str(condition.get('sourcePath') or '')
    terms = condition.get('effects') or []
    actual = [e for e in terms if e.get('upgradeType') != 'NONE']
    if any(e.get('upgradeType') == 'NONE' and e.get('valuePerRank') != 0 for e in terms):
        return None
    if len(actual) != 1 or condition.get('runtimeScripts'):
        return None
    e = actual[0]
    if (path == STUG_EVOLUTIONS + 'StugEvoTier1A'
            and source == path + 'SubMod'
            and condition.get('conditions') == ['PistolOnShootReloadResetCondition']
            and condition.get('maxStacks') == 10
            and condition.get('duration') in (None, 0)
            and e.get('upgradeType') == 'WEAPON_FIRE_ITERATIONS'
            and e.get('operation') == 'STACKING_MULTIPLY'
            and _close(e.get('valuePerRank'), .05)):
        return {**condition, 'effects': actual, 'eventKind': 'on-fire',
                'resetOn': ['on-reload', 'on-transform'],
                'conditionText': '每次开火增加一层；换弹、进入或退出灵化形态时清空。每层 +5% 多重射击，最多 10 层。'}
    if (path == STUG_EVOLUTIONS + 'StugEvoTier3C'
            and source == path + 'SubMod'
            and condition.get('conditions') == ['OnStugIncarnonActivatedCondition']
            and e.get('upgradeType') == 'WEAPON_PROC_CHANCE'
            and e.get('operation') == 'ADD_BASE'
            and _close(e.get('valuePerRank'), .2)):
        return {**condition, 'effects': actual, 'formGate': 'incarnon'}
    return None


TORID_FIELD_DURATION_PATH = '/Lotus/Weapons/ClanTech/Bio/ToridIncarnonEvolutions/ToridEvoTier2B'

def verified_torid_field_duration(record):
    """Exact exported script signature; raw/replay provenance in remaining-events evidence."""
    if (record.get('path') != TORID_FIELD_DURATION_PATH
            or record.get('conditionalEffects') or record.get('unresolvedReferences')):
        return None
    effects = record.get('effects') or []
    if (len(effects) != 1 or effects[0].get('upgradeType') != 'NONE'
            or effects[0].get('operation') != 'ADD' or effects[0].get('valuePerRank') != 0):
        return None
    scripts = record.get('runtimeScripts') or []
    if not isinstance(scripts, list) or len(scripts) != 1:
        return None
    row = scripts[0]
    script = row.get('apply') or {}
    if (row.get('sourcePath') != TORID_FIELD_DURATION_PATH or row.get('unapply')
            or script.get('Script') != '/Lotus/Scripts/Mods/ProjectileEmbedTimeOnCondition.lua'
            or script.get('Function') != 'GiveUpgrade'
            or script.get('_embedDurationMultiplier') != 2
            or script.get('_emissionTimeDelta') != 0):
        return None
    return dict(id='torid-renewed-horror', multiplier=2.,
        conditionText='弹匣打空并完成换弹后，下一次基础形态射击的毒云持续时间翻倍；只消耗一次，不延长异常状态。')
