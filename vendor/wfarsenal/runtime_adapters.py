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
