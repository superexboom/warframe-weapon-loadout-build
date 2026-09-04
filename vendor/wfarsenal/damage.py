"""Damage model for modded weapons.

Multiplier semantics come straight from the extracted data -- each mod effect names its
own ``OperationType``, so the stacking rules are read rather than guessed:

``STACKING_MULTIPLY``
    Bonuses pool additively and apply once against the base: ``base * (1 + sum)``.
    This covers most cards ("+165% Damage").
``MULTIPLY``
    A genuinely separate multiplicative factor, applied after the pooled bonus.
``ADD`` / ``ADD_BASE``
    Flat addition, to the modded value and to the base respectively.
``SET`` / ``SET_BASE``
    Override.

Element combining order is likewise data-driven:
``WEAPON_PERCENT_BASE_DAMAGE_ADDED`` participates in combining, while
``WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE`` is added afterwards and stays
uncombined -- the ``POST_COALESCE`` suffix names the phase boundary explicitly.

Enemy interaction follows the current faction-resistance model introduced in Update
36.  New exports embed the matching row from ``ProdResistanceTable`` in each target;
the small table below only keeps older exports and hand-built test records usable.
Health, shield and armour classes no longer add their pre-Update-36 type modifiers.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence

from .runtime_adapters import RuntimeAdapter, resolve_runtime_adapter

# -- constants not present in the extracted data --------------------------------------

# Elemental pairs and their compound result. Combining is order-sensitive in game: the
# earliest-installed mod picks its partner first, which is why callers pass mods in
# slot order.
ELEMENT_COMBINATIONS: dict[frozenset[str], str] = {
    frozenset({"DT_FIRE", "DT_FREEZE"}): "DT_EXPLOSION",  # Blast
    frozenset({"DT_FIRE", "DT_ELECTRICITY"}): "DT_RADIATION",
    frozenset({"DT_FIRE", "DT_POISON"}): "DT_GAS",
    frozenset({"DT_FREEZE", "DT_ELECTRICITY"}): "DT_MAGNETIC",
    frozenset({"DT_FREEZE", "DT_POISON"}): "DT_VIRAL",
    frozenset({"DT_ELECTRICITY", "DT_POISON"}): "DT_CORROSIVE",
}
BASE_ELEMENTS = ("DT_FIRE", "DT_FREEZE", "DT_ELECTRICITY", "DT_POISON")
PHYSICAL_TYPES = ("DT_IMPACT", "DT_PUNCTURE", "DT_SLASH")
# Extra innate elements on Kuva/Tenet/Coda weapons are applied after ordinary
# elemental mods.  This order is the game's fixed native-element priority.
INNATE_ELEMENT_ORDER = {
    "DT_FIRE": 0,
    "DT_FREEZE": 1,
    "DT_ELECTRICITY": 2,
    "DT_POISON": 3,
}

# Hit locations are deliberately a small, explicit API.  The current frozen
# export does not yet emit hit proxies for every NPC, so callers must not get a
# guessed ``2x`` headshot when the source data is absent.
HIT_LOCATIONS = frozenset({"body", "head"})
_HIT_PROXY_LABEL_KEYS = (
    "part",
    "location",
    "hitLocation",
    "hit_location",
    "name",
    "type",
    "tag",
    "id",
)
_HIT_PROXY_MULTIPLIER_KEYS = (
    "damageAtten",
    "damage_atten",
    "damageMultiplier",
    "damage_multiplier",
    "multiplier",
    "headshotMultiplier",
    "headMultiplier",
    "weakpointMultiplier",
    "weakPointMultiplier",
    "damageScale",
    "damage_scale",
    "scale",
    "value",
)
_HIT_PROXY_ALIASES = {
    "head": frozenset({"head", "headshot", "head_hit", "headshot_hit", "weakpoint", "weak_point"}),
    "body": frozenset({"body", "torso", "body_hit", "default"}),
}

# Fallback for pre-schema-v2 targets.  Values are *damage multiplier deltas* obtained
# by negating the current build's ProdResistanceTable values: +0.5 means 1.5x damage,
# -0.5 means 0.5x.  ``target["factionDamageModifiers"]`` is authoritative when present.
FACTION_DAMAGE_DELTAS: dict[str, dict[str, float]] = {
    "RK_CORPUS_AMALGAM_FACTION": {
        "DT_ELECTRICITY": 0.5,
        "DT_EXPLOSION": -0.5,
        "DT_MAGNETIC": 0.5,
    },
    "RK_CORPUS_FACTION": {"DT_MAGNETIC": 0.5, "DT_PUNCTURE": 0.5},
    "RK_GRINEER_FACTION": {"DT_CORROSIVE": 0.5, "DT_IMPACT": 0.5},
    "RK_GRINEER_KUVA_FACTION": {
        "DT_CORROSIVE": 0.5,
        "DT_FIRE": -0.5,
        "DT_IMPACT": 0.5,
    },
    "RK_INFESTED_DEIMOS_FACTION": {
        "DT_EXPLOSION": 0.5,
        "DT_GAS": 0.5,
        "DT_VIRAL": -0.5,
    },
    "RK_INFESTED_FACTION": {"DT_FIRE": 0.5, "DT_SLASH": 0.5},
    "RK_LASRIA_FACTION": {
        "DT_CORROSIVE": 0.5,
        "DT_GAS": -0.5,
        "DT_IMPACT": 0.5,
    },
    "RK_MITW_FACTION": {
        "DT_ELECTRICITY": 0.5,
        "DT_RADIATION": 0.5,
        "DT_VIRAL": -0.5,
    },
    "RK_NARMER_FACTION": {
        "DT_MAGNETIC": -0.5,
        "DT_POISON": 0.5,
        "DT_SLASH": 0.5,
    },
    "RK_OROKIN_EMPIRE_FACTION": {
        "DT_ELECTRICITY": 0.5,
        "DT_IMPACT": 0.5,
        "DT_RADIATION": -0.5,
    },
    "RK_OROKIN_FACTION": {
        "DT_PUNCTURE": 0.5,
        "DT_RADIATION": -0.5,
        "DT_VIRAL": 0.5,
    },
    "RK_PROTOINFESTED_FACTION": {
        "DT_FREEZE": -0.5,
        "DT_GAS": 0.5,
        "DT_MAGNETIC": 0.5,
    },
    "RK_SENTIENT_FACTION": {
        "DT_CORROSIVE": -0.5,
        "DT_FREEZE": 0.5,
        "DT_RADIATION": 0.5,
    },
    "RK_ZARIMAN_FACTION": {"DT_RADIANT": 0.5},
}

# Current LotusGameRules.json / ProdResistanceTable.json constants.
ARMOUR_CLAMP_MIN = 200.0
ARMOUR_CLAMP_MAX = 2700.0
ARMOUR_MAX_REDUCTION = 0.9
STEEL_PATH_DEFENSE_MULTIPLIER = 2.5

# Exact Update-36-era attenuation curves from the current LotusDifficultyTable and
# its SubFactionDifficultyTables.  Tuple order is low multiplier/exponent followed
# by the blended high multiplier/exponent; the transition is smooth from delta 70
# through 80.  Missing faction rows deliberately use the base table.
DEFAULT_HEALTH_SCALING = (0.015, 2.0, 10.7332, 0.5)
DEFAULT_SHIELD_SCALING = (0.02, 1.75, 1.6, 0.75)
ARMOUR_SCALING = (0.005, 1.75, 0.4, 0.75)
FACTION_HEALTH_SCALING: dict[str, tuple[float, float, float, float]] = {
    "RK_GRINEER_FACTION": (0.015, 2.12, 10.7332, 0.72),
    "RK_GRINEER_KUVA_FACTION": (0.015, 2.12, 10.7332, 0.72),
    "RK_CORPUS_FACTION": (0.015, 2.12, 13.4165, 0.55),
    "RK_CORPUS_AMALGAM_FACTION": (0.015, 2.12, 13.4165, 0.55),
    "RK_INFESTED_FACTION": (0.0225, 2.12, 16.0998, 0.72),
    "RK_INFESTED_DEIMOS_FACTION": (0.0225, 2.12, 16.0998, 0.72),
    "RK_OROKIN_FACTION": (0.015, 2.1, 10.7332, 0.685),
    "RK_OROKIN_EMPIRE_FACTION": (0.015, 2.1, 10.7332, 0.685),
    "RK_LASRIA_FACTION": (0.015, 2.12, 10.7332, 0.72),
    "RK_PROTOINFESTED_FACTION": (0.02, 2.12, 15.0998, 0.7),
}
FACTION_SHIELD_SCALING: dict[str, tuple[float, float, float, float]] = {
    "RK_CORPUS_FACTION": (0.02, 1.76, 2.0, 0.76),
    "RK_CORPUS_AMALGAM_FACTION": (0.02, 1.76, 2.0, 0.76),
    "RK_OROKIN_FACTION": (0.02, 1.75, 2.0, 0.75),
    "RK_OROKIN_EMPIRE_FACTION": (0.02, 1.75, 2.0, 0.75),
    "RK_PROTOINFESTED_FACTION": (0.02, 1.76, 3.5, 0.76),
}
DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES = frozenset(
    {"DT_CINEMATIC", "DT_HEALTH_DRAIN", "DT_FINISHER"}
)
DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES = frozenset({"DT_POISON", "DT_HEALTH_DRAIN"})


def _float32(value: float) -> float:
    """Apply the game's documented f32 rounding at formula boundaries."""
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _enemy_enhancement_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    if options is None:
        return {
            "eximus": False,
            "archimedea": False,
            "empowered": False,
            "playerCount": None,
            "magneticStacks": 0,
        }
    if not isinstance(options, Mapping):
        raise TypeError("enemy_enhancements must be an object")
    for key in ("eximus", "archimedea", "empowered"):
        if key in options and not isinstance(options[key], bool):
            raise TypeError(f"enemy_enhancements.{key} must be boolean")
    result = {
        "eximus": options.get("eximus", False),
        "archimedea": options.get("archimedea", False),
        "empowered": options.get("empowered", False),
        "playerCount": options.get("playerCount"),
        "magneticStacks": options.get("magneticStacks", 0),
    }
    if result["playerCount"] is not None:
        if isinstance(result["playerCount"], bool) or not isinstance(result["playerCount"], int) or not 1 <= result["playerCount"] <= 4:
            raise ValueError("enemy_enhancements.playerCount must be an integer from 1 to 4")
    elif result["empowered"]:
        result["playerCount"] = 1
    stacks = result["magneticStacks"]
    if isinstance(stacks, bool) or not isinstance(stacks, int) or not 0 <= stacks <= 10:
        raise ValueError("enemy_enhancements.magneticStacks must be an integer from 0 to 10")
    if not result["empowered"]:
        result["playerCount"] = None
    return result

# Damage-over-time coefficients recovered from the current injury definitions.  The
# duration is deliberately treated as a continuous expected-value multiplier: this
# API reports the complete damage caused by one attack's expected procs, not a
# frame-by-frame status-stack simulation.
DOT_DAMAGE_COEFFICIENTS: dict[str, float] = {
    "DT_SLASH": 0.35,
    "DT_FIRE": 0.5,
    "DT_POISON": 0.5,
    "DT_ELECTRICITY": 0.5,
    "DT_GAS": 0.5,
}
DOT_BASE_DURATION_SECONDS = 6.0
BLAST_DAMAGE_COEFFICIENT = 0.3
BLAST_DELAY_SECONDS = 1.5
BLAST_AOE_MULTIPLIER = 3.0

# One source of truth for effects this reducer actually consumes.  The exporter may
# carry an older ``supported`` flag, but the evaluator must not silently trust it:
# support changes when a handler is added or removed here.
WEAPON_EFFECT_HANDLERS: dict[str, str] = {
    "WEAPON_DAMAGE_AMOUNT": "base_damage",
    "WEAPON_MELEE_DAMAGE": "base_damage",
    "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE": "status_condition_damage",
    "WEAPON_PERCENT_BASE_DAMAGE_ADDED": "element_pre_coalesce",
    "WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE": "element_post_coalesce",
    "WEAPON_CRIT_CHANCE": "crit_chance",
    "WEAPON_CRIT_DAMAGE": "crit_multiplier",
    # Vigilante set bonus: a chance to promote an already rolled critical hit by
    # one tier.  This is kept separate from crit chance; treating it as crit chance
    # incorrectly turns non-critical hits into critical hits.
    "WEAPON_DOUBLE_CRIT_CHANCE": "double_crit_chance",
    "WEAPON_PROC_CHANCE": "status_chance",
    "WEAPON_FIRE_ITERATIONS": "multishot",
    "WEAPON_FIRE_RATE": "fire_rate",
    "WEAPON_CLIP_MAX": "magazine",
    "WEAPON_RELOAD_SPEED": "reload_time",
    "WEAPON_SPREAD": "spread_multiplier",
    "WEAPON_RECOIL": "recoil_multiplier",
    "WEAPON_AMMO_MAX": "ammo_max_multiplier",
    "WEAPON_HEADSHOT_MULTIPLIER": "headshot_bonus_multiplier",
    "WEAPON_PROC_DAMAGE": "proc_damage_multiplier",
    "WEAPON_PROC_TIME": "proc_duration_multiplier",
    "WEAPON_MELEE_COMBO_INITIAL_BONUS": "initial_combo",
    "WEAPON_MELEE_COMBO_DURATION_BONUS": "combo_duration",
    "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY": "heavy_attack_efficiency",
    "GAMEPLAY_FACTION_DAMAGE": "faction_damage_multipliers",
    "WEAPON_NOCRIT_DAMAGE": "noncrit_damage_multiplier",
    # 膛室家族（蓄力装填 / 膛室 Prime）：弹匣第一发的最终伤害乘区。单发口径
    # 直接乘算；循环口径按弹匣折算（第一发多造成 bonus × 单发伤害）。
    "WEAPON_INIT_DAMAGE_MOD": "first_shot_damage",
}
SUPPORTED_WEAPON_UPGRADE_TYPES = frozenset(WEAPON_EFFECT_HANDLERS)
MELEE_COMBO_UPGRADE_TYPES = frozenset(
    {
        "WEAPON_MELEE_COMBO_INITIAL_BONUS",
        "WEAPON_MELEE_COMBO_DURATION_BONUS",
        "WEAPON_MELEE_COMBO_USAGE_EFFICIENCY",
    }
)
MELEE_SLOTS = frozenset({"melee", "arch_melee", "space_melee", "archmelee", "spacemelee"})

# The melee combo counter decays after five seconds without a hit.  Mods named
# WEAPON_MELEE_COMBO_DURATION_BONUS act on that base, including negative
# STACKING_MULTIPLY values, so retaining only an additive bonus would be wrong.
BASE_MELEE_COMBO_DURATION = 5.0
SUPPORTED_OPERATIONS = frozenset(
    {"STACKING_MULTIPLY", "MULTIPLY", "ADD", "ADD_BASE", "SET", "SET_BASE"}
)
SUPPORTED_SCENARIO_MODIFIERS = frozenset({"PM_AIM", "PM_HEAVY_MELEE"})
RUNTIME_UPGRADE_TYPES = frozenset(
    {"RUNTIME_IMPACT_PROC_CONVERSION", "RUNTIME_INDEPENDENT_PROC"}
)
DEFERRED_WEAPON_REASON_CODES = {
    "WEAPON_DAMAGE_CONVERSION": "damage-conversion-phase-unverified",
    "WEAPON_DAMAGE_TYPE_BIAS": "damage-type-bias-phase-unverified",
    "WEAPON_MULTISHOT": "no-observed-raw-sample",
}


@dataclass(frozen=True)
class Scenario:
    """Explicit combat state used by conditional effects and qualifiers.

    Conditions are never guessed. ``conditional_stacks`` must name a condition by
    its exported ``sourcePath`` or ``conditionTag`` before its effects are enabled.
    ``combo_tier`` is the number of tiers above the base 1x counter (0 through 11),
    while ``victim_status_count`` counts distinct proc types, not individual stacks.
    ``distance`` is optional.  When omitted, ranged falloff is not applied; when
    supplied it must be a finite, non-negative distance in the fire mode's units.
    """

    aiming: bool = False
    heavy_attack: bool = False
    combo_tier: int = 0
    victim_status_count: int = 0
    conditional_stacks: Mapping[str, int] = field(default_factory=dict)
    distance: float | None = None
    cloaked: bool = False
    nearest_enemy_distance: float | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.aiming, bool)
            or not isinstance(self.heavy_attack, bool)
            or not isinstance(self.cloaked, bool)
        ):
            raise TypeError("aiming, heavy_attack and cloaked must be booleans")
        _require_int("combo_tier", self.combo_tier, maximum=11)
        _require_int("victim_status_count", self.victim_status_count)
        if self.distance is not None:
            object.__setattr__(
                self,
                "distance",
                _require_nonnegative_finite("distance", self.distance),
            )
        if self.nearest_enemy_distance is not None:
            object.__setattr__(
                self,
                "nearest_enemy_distance",
                _require_nonnegative_finite(
                    "nearest_enemy_distance", self.nearest_enemy_distance
                ),
            )
        if not isinstance(self.conditional_stacks, Mapping):
            raise TypeError("conditional_stacks must be a mapping")

        stacks: dict[str, int] = {}
        for key, value in self.conditional_stacks.items():
            if not isinstance(key, str) or not key:
                raise TypeError("conditional stack keys must be non-empty strings")
            stacks[key] = _require_int(f"conditional_stacks[{key!r}]", value)
        object.__setattr__(self, "conditional_stacks", MappingProxyType(stacks))


@dataclass(frozen=True)
class ModEffect:
    """One normalized effect from an exported mod, at a chosen rank."""

    upgrade_type: str
    operation: str
    value: float
    damage_type: str | None = None
    symbol_filter: str | None = None
    supported: bool = True
    valid_type: str | None = None
    valid_modifiers: tuple[str, ...] = ()
    invalid_modifiers: tuple[str, ...] = ()
    valid_proc_types: tuple[str, ...] = ()
    valid_postures: tuple[str, ...] = ()
    auto_type: int | bool | None = None
    check_type_on_install: int | bool | None = None
    source_path: str | None = None
    condition_tag: str | None = None
    # Synthetic runtime markers populated only by exact Lua-backed adapters.
    runtime_kind: str | None = None
    runtime_damage_type: str | None = None
    runtime_chance: float | None = None
    runtime_threshold: float | None = None
    runtime_multiplier: float = 1.0

    @classmethod
    def from_export(
        cls,
        effect: Mapping[str, Any],
        rank: int,
        *,
        stacks: int = 1,
        source_path: str | None = None,
        condition_tag: str | None = None,
    ) -> "ModEffect":
        """Scale an exported effect to ``rank``.

        ``valuePerRank`` is the increment per rank and rank 0 already includes one
        step, so a rank-*n* card is worth ``value * (n + 1)``.
        """
        rank = _require_int("rank", rank)
        stacks = _require_int("stacks", stacks)
        per_rank = effect.get("valuePerRank") or 0.0
        upgrade_type = effect.get("upgradeType") or "NONE"
        return cls(
            upgrade_type=upgrade_type,
            operation=effect.get("operation") or "ADD",
            value=float(per_rank) * (rank + 1) * stacks,
            damage_type=effect.get("damageType"),
            symbol_filter=effect.get("symbolFilter") or None,
            supported=upgrade_type in SUPPORTED_WEAPON_UPGRADE_TYPES,
            valid_type=effect.get("validType") or None,
            valid_modifiers=_string_tuple(effect.get("validModifiers")),
            invalid_modifiers=_string_tuple(effect.get("invalidModifiers")),
            valid_proc_types=_string_tuple(effect.get("validProcTypes")),
            valid_postures=_string_tuple(effect.get("validPostures")),
            auto_type=effect.get("autoType"),
            check_type_on_install=effect.get("checkTypeOnInstall"),
            source_path=source_path,
            condition_tag=condition_tag,
        )


class ModEffectList(list[ModEffect]):
    """Active effects plus fail-closed diagnostics that survive into ``apply_mods``."""

    def __init__(
        self, effects: Iterable[ModEffect] = (), *, skipped: Iterable[str] = ()
    ) -> None:
        super().__init__(effects)
        self.skipped = list(skipped)


def mod_effects(
    mod: Mapping[str, Any],
    rank: int | None = None,
    scenario: Scenario | None = None,
) -> ModEffectList:
    """Return every effect of an exported ``mod`` scaled to ``rank``.

    Prefer this over :meth:`ModEffect.from_export` when you have the whole mod record:
    a bare effect carries no rank ceiling, so over-ranking a card would silently
    inflate the result (a rank-9 Split Chamber would read +90% multishot as +150%).
    ``rank`` defaults to the card's maximum.
    """
    max_rank = mod.get("maxRank")
    if max_rank is not None:
        max_rank = _require_int("maxRank", max_rank)
    if rank is None:
        rank = max_rank if max_rank is not None else 0
    rank = _require_int("rank", rank)
    if max_rank is not None and rank > max_rank:
        raise ValueError(
            f"{mod.get('name', '?')} ranks to {max_rank}, got rank {rank}"
        )
    scenario = scenario or Scenario()
    source_path = mod.get("path") or None
    runtime_scripts = mod.get("runtimeScripts") or {}
    adapter = resolve_runtime_adapter(mod, rank) if runtime_scripts else None
    if runtime_scripts and adapter is None:
        return ModEffectList(
            skipped=[f"{source_path or '?'}: unsupported[runtime-script]"]
        )

    # Range Advantage and Spectral Serration carry a placeholder NONE/conditional
    # effect in the export.  Their adapter emits a normal damage effect only when
    # the explicit scenario condition is active; never leave the placeholder as an
    # unconditional bonus.  Prototype retains its normal elemental effect.
    raw_effects = mod.get("effects") or ()
    if adapter is not None and adapter.kind in {"range_damage", "cloak_damage"}:
        raw_effects = ()
    elif adapter is not None and adapter.kind == "impact_conversion":
        # Current records contain only a NONE placeholder.  Keep any future
        # structured effects instead of dropping them if the game begins exporting
        # a normal component alongside the conversion script.
        raw_effects = tuple(
            effect
            for effect in raw_effects
            if isinstance(effect, Mapping) and effect.get("upgradeType") != "NONE"
        )
    effects = ModEffectList(
        ModEffect.from_export(effect, rank, source_path=source_path)
        for effect in raw_effects
    )

    if adapter is not None:
        if adapter.kind == "impact_conversion":
            effects.append(
                ModEffect(
                    upgrade_type="RUNTIME_IMPACT_PROC_CONVERSION",
                    operation="ADD",
                    value=float(adapter.chance or 0.0),
                    damage_type=adapter.damage_type,
                    supported=True,
                    source_path=source_path,
                    runtime_kind=adapter.kind,
                    runtime_damage_type=adapter.damage_type,
                    runtime_chance=adapter.chance,
                    runtime_threshold=adapter.fire_rate_threshold,
                    runtime_multiplier=adapter.fire_rate_multiplier,
                )
            )
        elif adapter.kind == "independent_proc":
            effects.append(
                ModEffect(
                    upgrade_type="RUNTIME_INDEPENDENT_PROC",
                    operation="ADD",
                    value=float(adapter.chance or 0.0),
                    damage_type=adapter.damage_type,
                    supported=True,
                    source_path=source_path,
                    runtime_kind=adapter.kind,
                    runtime_damage_type=adapter.damage_type,
                    runtime_chance=adapter.chance,
                )
            )
        elif adapter.kind == "range_damage":
            required = float(adapter.range_required or 0.0)
            nearest = scenario.nearest_enemy_distance
            if nearest is None:
                effects.skipped.append(
                    f"{source_path or '?'}: runtime[range-advantage] "
                    "requires nearest_enemy_distance"
                )
            elif nearest >= required:
                effects.append(
                    ModEffect(
                        upgrade_type="WEAPON_DAMAGE_AMOUNT",
                        operation="STACKING_MULTIPLY",
                        value=float(adapter.damage_bonus or 0.0),
                        damage_type="DT_ANY",
                        supported=True,
                        source_path=source_path,
                        condition_tag="range-advantage",
                    )
                )
            else:
                effects.skipped.append(
                    f"{source_path or '?'}: runtime[range-advantage] inactive "
                    f"nearest_enemy_distance<{required:g}"
                )
        elif adapter.kind == "cloak_damage":
            if scenario.cloaked:
                effects.append(
                    ModEffect(
                        upgrade_type="WEAPON_DAMAGE_AMOUNT",
                        operation="STACKING_MULTIPLY",
                        value=float(adapter.damage_bonus or 0.0),
                        damage_type="DT_ANY",
                        supported=True,
                        source_path=source_path,
                        condition_tag="PM_CLOAK",
                    )
                )
            else:
                effects.skipped.append(
                    f"{source_path or '?'}: requires modifier PM_CLOAK"
                )

    for conditional in mod.get("conditionalEffects") or ():
        if not isinstance(conditional, Mapping):
            continue
        condition_source = conditional.get("sourcePath") or None
        condition_tag = conditional.get("conditionTag") or None
        if conditional.get("runtimeScripts"):
            effects.skipped.append(
                f"{condition_source or condition_tag or '?'}: "
                "unsupported[runtime-script]"
            )
            continue
        requested = _condition_stacks(
            scenario.conditional_stacks, condition_source, condition_tag
        )
        if requested is None and _is_combo_tier_condition(conditional):
            requested = scenario.combo_tier
        if requested is None:
            effects.skipped.append(
                f"condition not specified: {condition_source or condition_tag or '?'}"
            )
            continue

        maximum = conditional.get("maxStacks")
        limit = _require_int("maxStacks", maximum) if maximum is not None else 1
        if not limit:
            limit = 1
        stacks = min(requested, limit)
        if not stacks:
            continue
        effects.extend(
            ModEffect.from_export(
                effect,
                rank,
                stacks=stacks,
                source_path=condition_source,
                condition_tag=condition_tag,
            )
            for effect in (conditional.get("effects") or ())
        )
    return effects


def arcane_effects(
    arcane: Mapping[str, Any],
    rank: int | None = None,
    *,
    stacks: int = 0,
    uptime: float = 1.0,
) -> ModEffectList:
    """Expand one Arcane for an explicit trigger state.

    Trigger probability is deliberately not guessed. ``stacks=0`` means inactive;
    callers may provide a measured/assumed ``uptime`` for a steady-state estimate.
    """
    max_rank = arcane.get("maxRank")
    if max_rank is not None:
        max_rank = _require_int("maxRank", max_rank)
    if rank is None:
        rank = max_rank if max_rank is not None else 0
    rank = _require_int("rank", rank)
    stacks = _require_int("stacks", stacks)
    uptime = _require_nonnegative_finite("uptime", uptime)
    if uptime > 1.0:
        raise ValueError(f"uptime must not exceed 1, got {uptime}")
    if max_rank is not None and rank > max_rank:
        raise ValueError(
            f"{arcane.get('name', '?')} ranks to {max_rank}, got rank {rank}"
        )

    source_path = arcane.get("path") or None
    if arcane.get("runtimeScripts"):
        return ModEffectList(
            skipped=[f"{source_path or '?'}: unsupported[runtime-script]"]
        )

    result = ModEffectList(
        ModEffect.from_export(effect, rank, source_path=source_path)
        for effect in (arcane.get("effects") or ())
    )
    for effect in arcane.get("extraEffects") or ():
        if not isinstance(effect, Mapping):
            continue
        unlock_rank = _require_int("unlockRank", effect.get("unlockRank", 0))
        if rank < unlock_rank:
            continue
        effect_rank = rank if effect.get("scalesWithRank") else 0
        result.append(
            ModEffect.from_export(effect, effect_rank, source_path=source_path)
        )

    for conditional in arcane.get("conditionalEffects") or ():
        if not isinstance(conditional, Mapping):
            continue
        condition_source = conditional.get("sourcePath") or source_path
        condition_tag = conditional.get("conditionTag") or None
        if conditional.get("runtimeScripts"):
            result.skipped.append(
                f"{condition_source or condition_tag or '?'}: "
                "unsupported[runtime-script]"
            )
            continue
        maximum = conditional.get("maxStacks")
        limit = _require_int("maxStacks", maximum) if maximum is not None else 1
        active_stacks = min(stacks, limit or 1)
        if not active_stacks:
            continue
        result.extend(
            _scale_effect(
                ModEffect.from_export(
                    effect,
                    rank,
                    stacks=active_stacks,
                    source_path=condition_source,
                    condition_tag=condition_tag,
                ),
                uptime,
            )
            for effect in (conditional.get("effects") or ())
        )
    return result


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value else ()
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str) and item)
    return ()


def _require_int(name: str, value: Any, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {value!r}")
    if value < 0:
        raise ValueError(f"{name} must not be negative, got {value}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name} must not exceed {maximum}, got {value}")
    return value


def _require_nonnegative_finite(name: str, value: Any) -> float:
    """Validate a numeric distance/quantity without accepting booleans or NaN."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a finite non-negative number, got {value!r}")
    converted = float(value)
    if not math.isfinite(converted) or converted < 0.0:
        raise ValueError(f"{name} must be a finite non-negative number, got {value!r}")
    return converted


def _condition_stacks(
    stacks: Mapping[str, int], source_path: str | None, condition_tag: str | None
) -> int | None:
    for key in (source_path, condition_tag):
        if key and key in stacks:
            return stacks[key]
    return None


def _is_combo_tier_condition(conditional: Mapping[str, Any]) -> bool:
    return any(
        isinstance(condition, str) and condition.endswith("/OnComboTierCondition")
        for condition in (conditional.get("conditions") or ())
    )


@dataclass
class ModdedStats:
    """A weapon's stats after mods, before any target is considered."""

    damage_types: dict[str, float]
    crit_chance: float
    crit_multiplier: float
    status_chance: float
    multishot: float
    fire_rate: float
    magazine: float
    reload_time: float
    spread_multiplier: float = 1.0
    recoil_multiplier: float = 1.0
    ammo_max_multiplier: float = 1.0
    headshot_bonus_multiplier: float = 1.0
    proc_damage_multiplier: float = 1.0
    proc_duration_multiplier: float = 1.0
    status_condition_damage_multiplier: float = 1.0
    initial_combo: float = 0.0
    combo_duration: float = BASE_MELEE_COMBO_DURATION
    heavy_attack_efficiency: float = 0.0
    faction_damage_multipliers: dict[str, float] = field(default_factory=dict)
    noncrit_damage_multiplier: float = 1.0
    unsupported: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    # Optional extensions are kept after the historical fields so positional
    # construction of ModdedStats remains source-compatible.
    falloff_multiplier: float = 1.0
    dot_base_damage: float | None = None
    dot_elemental_multipliers: dict[str, float] = field(default_factory=dict)
    # Expected counts generated by selected verified Lua-backed mods.  Values are
    # per eligible impact proc / damaging event, not ordinary status chance.
    impact_proc_conversions: dict[str, list[dict[str, float]]] = field(
        default_factory=dict
    )
    independent_proc_chances: dict[str, float] = field(default_factory=dict)
    innate_damage_types: dict[str, float] = field(default_factory=dict)
    innate_element_candidates: tuple[str, ...] = ()
    # Populated only for an exported single heavy attack. ``heavy_damage`` is
    # expected direct damage (crit averaged); component ``damage`` stays non-crit.
    heavy_damage: float | None = None
    heavy_components: list[dict[str, Any]] = field(default_factory=list)
    double_crit_chance: float = 0.0
    # 膛室家族首发伤害加成（最终伤害乘区，只作用于弹匣第一发）。
    first_shot_damage_bonus: float = 0.0

    @property
    def total_damage(self) -> float:
        return sum(self.damage_types.values())

    @property
    def burst_dps(self) -> float:
        """Damage per second while the trigger is held, ignoring reloads."""
        return (
            self.total_damage
            * self.multishot
            * self.fire_rate
            * self.falloff_multiplier
        )

    @property
    def sustained_dps(self) -> float:
        """Damage per second including reload downtime.

        首发伤害加成折算进弹匣循环：一个循环里第一发多造成
        ``bonus × 单发面板``，等效 shots + bonus 发普通射击。
        """
        if not self.magazine or not self.fire_rate:
            return self.burst_dps
        shots = self.magazine + self.first_shot_damage_bonus
        firing = self.magazine / self.fire_rate
        cycle = firing + (self.reload_time or 0.0)
        return (
            self.total_damage
            * self.multishot
            * shots
            * self.falloff_multiplier
            / cycle
            if cycle
            else 0.0
        )

    @property
    def first_shot_hit(self) -> float:
        """弹匣第一发的单发期望伤害（暴击平均化后乘首发加成）。"""
        return self.average_hit * (1.0 + self.first_shot_damage_bonus)

    @property
    def sustained_attack_rate(self) -> float:
        """Trigger pulls per second including reload downtime."""
        if not self.magazine or not self.fire_rate:
            return max(float(self.fire_rate), 0.0)
        cycle = self.magazine / self.fire_rate + (self.reload_time or 0.0)
        return max(float(self.magazine / cycle), 0.0) if cycle else 0.0

    @property
    def average_hit(self) -> float:
        """Expected damage of one hit, averaging crits in.

        Crit chance above 100% guarantees the lower tier and rolls for the next, so a
        chance of 2.5 means every hit is at least a red crit.
        """
        return (
            self.total_damage
            * effective_hit_multiplier(
                self.crit_chance,
                self.crit_multiplier,
                self.noncrit_damage_multiplier,
                double_crit_chance=self.double_crit_chance,
            )
            * self.falloff_multiplier
        )


def effective_crit_multiplier(chance: float, multiplier: float) -> float:
    """Return the average damage multiplier from critical hits.

    Each whole 100% of crit chance guarantees one more crit tier. Tier *n* multiplies
    by ``1 + n * (multiplier - 1)``.
    """
    if multiplier <= 1.0 or chance <= 0.0:
        return 1.0
    guaranteed = int(chance)
    remainder = chance - guaranteed
    low = 1.0 + guaranteed * (multiplier - 1.0)
    high = 1.0 + (guaranteed + 1) * (multiplier - 1.0)
    return low * (1.0 - remainder) + high * remainder


def effective_hit_multiplier(
    crit_chance: float,
    crit_multiplier: float,
    noncrit_damage_multiplier: float = 1.0,
    critical_multiplier_factor: float = 1.0,
    *,
    double_crit_chance: float = 0.0,
) -> float:
    """Return average hit scaling including non-critical and proxy-crit bonuses.

    ``critical_multiplier_factor`` is applied only to the critical branch.  It is
    used for enemy hit-proxy ``criticalMultiplier`` and defaults to one for all
    historical callers.
    """
    if (
        isinstance(critical_multiplier_factor, bool)
        or not isinstance(critical_multiplier_factor, (int, float))
        or not math.isfinite(float(critical_multiplier_factor))
        or critical_multiplier_factor < 0.0
    ):
        raise ValueError("critical_multiplier_factor must be a finite non-negative number")
    if (
        isinstance(double_crit_chance, bool)
        or not isinstance(double_crit_chance, (int, float))
        or not math.isfinite(float(double_crit_chance))
        or double_crit_chance < 0.0
    ):
        raise ValueError("double_crit_chance must be a finite non-negative number")
    crit = effective_crit_multiplier(
        crit_chance, crit_multiplier * float(critical_multiplier_factor)
    )
    # A Vigilante promotion is only rolled for hits that already crit.  For a
    # fractional crit chance that is ``crit_chance`` of hits; at 100%+ every hit
    # is critical.  One extra tier contributes (critMultiplier - 1) on average.
    promotion = (
        min(max(float(crit_chance), 0.0), 1.0)
        * min(float(double_crit_chance), 1.0)
        * max(crit_multiplier * float(critical_multiplier_factor) - 1.0, 0.0)
    )
    noncrit_chance = max(1.0 - crit_chance, 0.0)
    noncrit_bonus = max(noncrit_damage_multiplier - 1.0, 0.0)
    return crit + promotion + noncrit_chance * noncrit_bonus


# -- mod application ------------------------------------------------------------------


def apply_mods(
    weapon: Mapping[str, Any],
    effects: Iterable[ModEffect],
    *,
    fire_mode: int = 0,
    scenario: Scenario | None = None,
) -> ModdedStats:
    """Compute a weapon's modded stats.

    Args:
        weapon: A record from ``weapons.json``.
        effects: Mod effects already scaled to their ranks.
        fire_mode: Index into the weapon's ``fireModes``.

    Raises:
        ValueError: If the weapon has no usable fire mode or damage data.
    """
    scenario = scenario or Scenario()
    effect_list = ModEffectList(
        list(effects), skipped=getattr(effects, "skipped", ())
    )
    heavy = weapon.get("heavyAttack")
    if scenario.heavy_attack and isinstance(heavy, Mapping):
        components = heavy.get("components")
        if isinstance(components, list) and components:
            return _apply_heavy_components(
                weapon, effect_list, components, scenario=scenario
            )

    modes = weapon.get("fireModes") or []
    if fire_mode >= len(modes):
        raise ValueError(
            f"{weapon.get('name')} has {len(modes)} fire modes; index {fire_mode} "
            "is out of range"
        )
    mode = modes[fire_mode]
    base = (mode.get("damage") or {}).get("types")
    if not base:
        raise ValueError(f"{weapon.get('name')} fire mode {fire_mode} has no damage data")

    skipped = list(effect_list.skipped)
    effects = list(effect_list)
    unsupported: set[str] = set()
    weapon_types = {
        str(path).rstrip("/")
        for path in (*tuple(weapon.get("ancestry") or ()), weapon.get("path"))
        if path
    }

    applicable: list[ModEffect] = []
    for effect in effects:
        if not effect.supported or (
            effect.upgrade_type not in SUPPORTED_WEAPON_UPGRADE_TYPES
            and effect.upgrade_type not in RUNTIME_UPGRADE_TYPES
        ):
            unsupported.add(effect.upgrade_type)
            code = DEFERRED_WEAPON_REASON_CODES.get(effect.upgrade_type, "no-handler")
            source = effect.source_path or effect.upgrade_type
            skipped.append(f"{source}: unsupported[{code}]")
            continue
        # validType selects a weapon-specific branch inside the same mod.
        if effect.valid_type and effect.valid_type.rstrip("/") not in weapon_types:
            continue
        reason = _qualifier_rejection(effect, weapon, scenario)
        if reason:
            skipped.append(reason)
        else:
            applicable.append(effect)

    buckets = _bucket(applicable)
    impact_proc_conversions: dict[str, list[dict[str, float]]] = {}
    for effect in buckets["RUNTIME_IMPACT_PROC_CONVERSION"]:
        dtype = effect.runtime_damage_type or effect.damage_type
        chance = effect.runtime_chance
        threshold = effect.runtime_threshold
        multiplier = effect.runtime_multiplier
        if not dtype or chance is None:
            skipped.append(
                f"{effect.source_path or '?'}: unsupported[runtime-parameter]"
            )
            unsupported.add(effect.upgrade_type)
            continue
        impact_proc_conversions.setdefault(dtype, []).append(
            {
                "chance": float(chance),
                "fireRateThreshold": float(threshold)
                if threshold is not None
                else math.inf,
                "fireRateMultiplier": float(multiplier),
            }
        )
    independent_proc_chances: dict[str, float] = {}
    for effect in buckets["RUNTIME_INDEPENDENT_PROC"]:
        dtype = effect.runtime_damage_type or effect.damage_type
        chance = effect.runtime_chance
        if not dtype or chance is None:
            skipped.append(
                f"{effect.source_path or '?'}: unsupported[runtime-parameter]"
            )
            unsupported.add(effect.upgrade_type)
            continue
        independent_proc_chances[dtype] = (
            independent_proc_chances.get(dtype, 0.0) + float(chance)
        )
    faction_groups: dict[str, list[ModEffect]] = {}
    for effect in buckets["GAMEPLAY_FACTION_DAMAGE"]:
        faction_groups.setdefault(effect.symbol_filter or "", []).append(effect)
    # Empty symbol-filter effects (Roar-style "all factions" buffs) apply to
    # every target and combine multiplicatively with faction-specific rows;
    # consumers multiply the "" row with the target-faction row.
    all_factions = _combine(1.0, faction_groups.pop("", []))
    faction_damage_multipliers = {
        faction: _combine(1.0, faction_effects)
        for faction, faction_effects in faction_groups.items()
    }
    if all_factions != 1.0:
        faction_damage_multipliers[""] = all_factions

    # Base damage scales as one pooled multiplier, then any separate factors.
    status_damage_effects = [
        _scale_effect(effect, scenario.victim_status_count)
        for effect in buckets["WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"]
    ]
    damage_scale = _combine(
        1.0, buckets["WEAPON_DAMAGE_AMOUNT"] + status_damage_effects
    )
    if weapon.get("slot") in MELEE_SLOTS:
        damage_scale = _combine(
            damage_scale,
            buckets["WEAPON_MELEE_DAMAGE"],
            base_value=damage_scale,
        )

    scaled_base = {dtype: amount * damage_scale for dtype, amount in base.items()}
    base_total = sum(base.values())

    damage_types = _apply_elements(
        scaled_base,
        base_total=base_total * damage_scale,
        pre=buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED"],
        post=buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"],
    )
    innate_entries, innate_candidates = _read_innate_elements(weapon)
    if innate_candidates and not innate_entries:
        unsupported.add("innate-element-instance-required")
        skipped.append(
            f"{weapon.get('path') or weapon.get('name') or '?'}: "
            "unsupported[innate-element-instance-required]"
        )
    if innate_entries:
        damage_types = _apply_innate_elements(
            damage_types, base_total=base_total * damage_scale, entries=innate_entries
        )
    falloff_multiplier = _falloff_multiplier(mode, base_total, scenario.distance)

    damage = mode["damage"]
    if damage.get("components"):
        # Secondary explosions/stacking attacks need a hit timeline; the compact
        # evaluator intentionally scores only the exported primary hit.
        unsupported.add("projectile-component-damage-unapplied")
        skipped.append(
            f"{weapon.get('path') or weapon.get('name') or '?'}: "
            "unsupported[projectile-component-damage-unapplied]"
        )
    return ModdedStats(
        damage_types=damage_types,
        crit_chance=_combine(damage.get("critChance", 0.0), buckets["WEAPON_CRIT_CHANCE"]),
        crit_multiplier=_combine(
            damage.get("critMultiplier", 1.0), buckets["WEAPON_CRIT_DAMAGE"]
        ),
        status_chance=_combine(damage.get("procChance", 0.0), buckets["WEAPON_PROC_CHANCE"]),
        multishot=_combine(
            float(mode.get("multishot") or 1), buckets["WEAPON_FIRE_ITERATIONS"]
        ),
        fire_rate=_combine(mode.get("fireRate") or 0.0, buckets["WEAPON_FIRE_RATE"]),
        magazine=_combine(
            float(weapon.get("magazineSize") or 0), buckets["WEAPON_CLIP_MAX"]
        ),
        # A reload *speed* bonus shortens the reload, so it divides rather than scales.
        reload_time=_divide(
            mode.get("reloadTime") or 0.0, buckets["WEAPON_RELOAD_SPEED"]
        ),
        # The compact weapon export does not yet carry native spread, recoil or
        # reserve-ammo bases.  These fields therefore expose the exact relative
        # transform rather than fabricating an absolute stat.
        spread_multiplier=_combine(1.0, buckets["WEAPON_SPREAD"]),
        recoil_multiplier=_combine(1.0, buckets["WEAPON_RECOIL"]),
        ammo_max_multiplier=_combine(1.0, buckets["WEAPON_AMMO_MAX"]),
        headshot_bonus_multiplier=_combine(
            1.0, buckets["WEAPON_HEADSHOT_MULTIPLIER"]
        ),
        proc_damage_multiplier=_combine(1.0, buckets["WEAPON_PROC_DAMAGE"]),
        proc_duration_multiplier=_combine(1.0, buckets["WEAPON_PROC_TIME"]),
        status_condition_damage_multiplier=_combine(1.0, status_damage_effects),
        initial_combo=_combine(0.0, buckets["WEAPON_MELEE_COMBO_INITIAL_BONUS"]),
        combo_duration=_combine(
            BASE_MELEE_COMBO_DURATION if weapon.get("slot") in MELEE_SLOTS else 0.0,
            buckets["WEAPON_MELEE_COMBO_DURATION_BONUS"],
        ),
        heavy_attack_efficiency=_combine(
            0.0, buckets["WEAPON_MELEE_COMBO_USAGE_EFFICIENCY"]
        ),
        faction_damage_multipliers=faction_damage_multipliers,
        noncrit_damage_multiplier=_combine(1.0, buckets["WEAPON_NOCRIT_DAMAGE"]),
        # The export calls this a percent-like multiplier (STACKING_MULTIPLY in
        # synthetic records, ADD in the Vigilante shell).  Accumulate from 1x and
        # convert back to a probability so both operation types work.
        double_crit_chance=max(
            _combine(1.0, buckets["WEAPON_DOUBLE_CRIT_CHANCE"]) - 1.0,
            0.0,
        ),
        # 首发加成是 STACKING_MULTIPLY 口径：从 1 累积再减回（同 double_crit_chance），
        # 否则基值 0 的乘算区恒为 0。
        first_shot_damage_bonus=max(
            _combine(1.0, buckets["WEAPON_INIT_DAMAGE_MOD"]) - 1.0,
            0.0,
        ),
        falloff_multiplier=falloff_multiplier,
        dot_base_damage=sum(scaled_base.values()),
        dot_elemental_multipliers=_dot_elemental_multipliers(
            buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED"],
            buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"],
        ),
        impact_proc_conversions=impact_proc_conversions,
        independent_proc_chances=independent_proc_chances,
        innate_damage_types={
            dtype: base_total * damage_scale * value
            for dtype, value in innate_entries
        },
        innate_element_candidates=tuple(innate_candidates),
        unsupported=sorted(unsupported),
        skipped=list(dict.fromkeys(skipped)),
    )


def _apply_heavy_components(
    weapon: Mapping[str, Any],
    effects: ModEffectList,
    components: Sequence[Mapping[str, Any]],
    *,
    scenario: Scenario,
) -> ModdedStats:
    """Apply the ordinary reducer to each exported heavy hit, then sum one attack."""
    evaluated: list[tuple[Mapping[str, Any], ModdedStats]] = []
    for component in components:
        damage = component.get("damage")
        if not isinstance(damage, Mapping) or not damage.get("types"):
            continue
        count = component.get("count", 1)
        if (
            isinstance(count, bool)
            or not isinstance(count, (int, float))
            or not math.isfinite(float(count))
            or float(count) <= 0
        ):
            continue
        component_damage = {
            key: value
            for key, value in damage.items()
            if key not in {"components", "radial"}
        }
        synthetic = {
            **weapon,
            "fireModes": [
                {
                    "damage": component_damage,
                    "multishot": float(count),
                    "fireRate": 0.0,
                    "reloadTime": 0.0,
                }
            ],
        }
        synthetic.pop("heavyAttack", None)
        evaluated.append(
            (component, apply_mods(synthetic, effects, scenario=scenario))
        )
    if not evaluated:
        raise ValueError(f"{weapon.get('name')} heavy attack has no damage data")

    damage_types: dict[str, float] = {}
    heavy_components: list[dict[str, Any]] = []
    expected_total = 0.0
    unsupported: set[str] = set()
    skipped: list[str] = []
    for component, stats in evaluated:
        count = stats.multishot
        types = {
            damage_type: amount * count
            for damage_type, amount in stats.damage_types.items()
        }
        for damage_type, amount in types.items():
            damage_types[damage_type] = damage_types.get(damage_type, 0.0) + amount
        expected = stats.average_hit * count
        expected_total += expected
        total = sum(types.values())
        payload = {
            "id": component.get("id"),
            "kind": component.get("kind"),
            "source": component.get("source"),
            "count": count,
            "damage": {
                "total": total,
                "types": types,
                "shares": {
                    damage_type: amount / total
                    for damage_type, amount in types.items()
                }
                if total
                else {},
                "critChance": stats.crit_chance,
                "critMultiplier": stats.crit_multiplier,
                "doubleCritChance": stats.double_crit_chance,
                "procChance": stats.status_chance,
            },
            "expectedDamage": expected,
        }
        for key in (
            "forcedProcs",
            "radius",
            "falloff",
            "recallMultiplier",
        ):
            if component.get(key) is not None:
                payload[key] = component[key]
        heavy_components.append(payload)
        unsupported.update(stats.unsupported)
        skipped.extend(stats.skipped)

    first = evaluated[0][1]
    return replace(
        first,
        damage_types=damage_types,
        # Preserve the first hit's historical crit/status view for callers that
        # inspect ModdedStats directly; heavyDamage uses per-component expectations.
        crit_chance=first.crit_chance,
        crit_multiplier=first.crit_multiplier,
        status_chance=first.status_chance,
        multishot=1.0,
        fire_rate=0.0,
        magazine=0.0,
        reload_time=0.0,
        falloff_multiplier=1.0,
        heavy_damage=expected_total,
        heavy_components=heavy_components,
        unsupported=sorted(unsupported),
        skipped=list(dict.fromkeys(skipped)),
    )


def _scale_effect(effect: ModEffect, multiplier: int | float) -> ModEffect:
    """Return ``effect`` scaled by explicit combat state, preserving qualifiers."""
    return replace(effect, value=effect.value * multiplier)


def _qualifier_rejection(
    effect: ModEffect, weapon: Mapping[str, Any], scenario: Scenario
) -> str | None:
    source = effect.source_path or effect.upgrade_type
    if effect.operation not in SUPPORTED_OPERATIONS:
        return f"{source}: cannot evaluate operation {effect.operation}"
    if effect.symbol_filter and effect.upgrade_type != "GAMEPLAY_FACTION_DAMAGE":
        return f"{source}: cannot evaluate symbol filter {effect.symbol_filter}"
    # Empty symbol-filter faction damage means "all factions" (Roar-style
    # external buffs); it flows into the "" row of faction_damage_multipliers.
    slot = weapon.get("slot")
    if effect.upgrade_type in MELEE_COMBO_UPGRADE_TYPES and slot not in MELEE_SLOTS:
        return f"{source}: requires a melee weapon"
    if effect.upgrade_type == "WEAPON_MELEE_DAMAGE" and slot not in MELEE_SLOTS:
        return f"{source}: requires a melee or arch-melee weapon"
    active = {
        "PM_AIM": scenario.aiming,
        "PM_HEAVY_MELEE": scenario.heavy_attack,
    }
    for modifier in effect.valid_modifiers:
        state = active.get(modifier)
        if state is None:
            return f"{source}: cannot evaluate valid modifier {modifier}"
        if not state:
            return f"{source}: requires modifier {modifier}"
    for modifier in effect.invalid_modifiers:
        state = active.get(modifier)
        if state is None:
            return f"{source}: cannot evaluate invalid modifier {modifier}"
        if state:
            return f"{source}: excludes modifier {modifier}"

    if effect.valid_proc_types:
        return f"{source}: cannot evaluate proc type {','.join(effect.valid_proc_types)}"
    if effect.valid_postures:
        return f"{source}: cannot evaluate posture {','.join(effect.valid_postures)}"
    return None


def _bucket(effects: Iterable[ModEffect]) -> dict[str, list[ModEffect]]:
    """Group effects by upgrade type, defaulting missing keys to empty lists."""
    grouped: dict[str, list[ModEffect]] = {}
    for effect in effects:
        grouped.setdefault(effect.upgrade_type, []).append(effect)

    class _Defaulting(dict):
        def __missing__(self, key: str) -> list[ModEffect]:
            return []

    return _Defaulting(grouped)


def _combine(
    base: float, effects: list[ModEffect], *, base_value: float | None = None
) -> float:
    """Apply one upgrade type's effects to ``base`` per their operations.

    ``base_value`` overrides what ADD_BASE/SET_BASE act on, for the rare case where the
    unmodded figure differs from the value being accumulated.
    """
    if not effects:
        return base

    origin = base if base_value is None else base_value
    additive = 0.0
    factors = 1.0
    flat = 0.0
    override: float | None = None

    for effect in effects:
        op = effect.operation
        if op == "STACKING_MULTIPLY":
            additive += effect.value
        elif op == "MULTIPLY":
            factors *= effect.value
        elif op == "ADD":
            flat += effect.value
        elif op == "ADD_BASE":
            origin += effect.value
        elif op in ("SET", "SET_BASE"):
            override = effect.value

    if override is not None:
        return override
    return (origin * (1.0 + additive) * factors) + flat


def _divide(base: float, effects: list[ModEffect]) -> float:
    """Apply speed-style bonuses that shorten a duration."""
    if not base or not effects:
        return base
    scale = _combine(1.0, effects)
    return base / scale if scale else base


def _falloff_multiplier(
    mode: Mapping[str, Any], base_total: float, distance: float | None
) -> float:
    """Return exact linear ranged falloff for one fire mode.

    ``falloffMinDamage`` is an absolute unmodded damage value at the end range, not
    a percentage.  Converting it with the mode's unmodded ``base_total`` preserves
    the same falloff ratio after mods without changing :attr:`ModdedStats.total_damage`.
    Missing or degenerate source fields fail open to 1.0 rather than inventing a
    range.
    """
    if distance is None or base_total <= 0:
        return 1.0
    ranges = mode.get("falloffRange")
    minimum = mode.get("falloffMinDamage")
    if not isinstance(ranges, (list, tuple)) or len(ranges) < 2:
        return 1.0
    try:
        start = _require_nonnegative_finite("falloff start", ranges[0])
        end = _require_nonnegative_finite("falloff end", ranges[1])
        minimum = _require_nonnegative_finite("falloffMinDamage", minimum)
    except (TypeError, ValueError):
        return 1.0
    if end <= start:
        return 1.0
    final = minimum / base_total
    if distance <= start:
        return 1.0
    if distance >= end:
        return final
    progress = (distance - start) / (end - start)
    return 1.0 + (final - 1.0) * progress


def _dot_elemental_multipliers(
    pre: list[ModEffect], post: list[ModEffect]
) -> dict[str, float]:
    """Return elemental multipliers used by damaging status effects.

    Heat, Toxin and Electricity use their own installed elemental bonus.  Gas uses
    the shared additive Heat+Toxin pool (``1 + heat + toxin``), not the product of
    the two elemental multipliers.  Slash has no matching elemental bonus.
    """
    typed: dict[str, list[ModEffect]] = {}
    for effect in (*pre, *post):
        if effect.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY"}:
            typed.setdefault(effect.damage_type, []).append(effect)

    heat = max(_combine(1.0, typed.get("DT_FIRE", [])), 0.0)
    toxin = max(_combine(1.0, typed.get("DT_POISON", [])), 0.0)
    electricity = max(_combine(1.0, typed.get("DT_ELECTRICITY", [])), 0.0)
    return {
        "DT_SLASH": 1.0,
        "DT_FIRE": heat,
        "DT_POISON": toxin,
        "DT_ELECTRICITY": electricity,
        "DT_GAS": max(heat + toxin - 1.0, 0.0),
    }


def _apply_elements(
    scaled_base: dict[str, float],
    *,
    base_total: float,
    pre: list[ModEffect],
    post: list[ModEffect],
) -> dict[str, float]:
    """Add elemental and physical bonuses, combining base elements where they pair.

    Elemental bonuses are percentages of total base damage; physical bonuses scale
    only their matching base component. Base elements combine pairwise in mod order;
    physical and already-compound types never combine. ``post`` bonuses are applied
    after combining and stay separate.
    """
    result = dict(scaled_base)
    added: dict[str, float] = {}
    order: list[str] = []

    for effect in pre:
        dtype = effect.damage_type
        if not dtype or dtype == "DT_ANY":
            # An untyped percentage raises every existing type proportionally.
            for key in list(result):
                result[key] += scaled_base.get(key, 0.0) * effect.value
            continue
        if dtype not in added:
            order.append(dtype)
        bonus_base = (
            scaled_base.get(dtype, 0.0) if dtype in PHYSICAL_TYPES else base_total
        )
        added[dtype] = added.get(dtype, 0.0) + bonus_base * effect.value

    # Physical bonuses land directly on their own type.
    for dtype in list(added):
        if dtype in PHYSICAL_TYPES:
            result[dtype] = max(0.0, result.get(dtype, 0.0) + added.pop(dtype))
            order.remove(dtype)

    # Native base elements combine after installed elemental mods. A matching
    # mod pulls that native damage forward to the mod's existing position.
    for dtype in BASE_ELEMENTS:
        amount = result.pop(dtype, 0.0)
        if not amount:
            continue
        if dtype not in added:
            order.append(dtype)
        added[dtype] = added.get(dtype, 0.0) + amount

    _coalesce(added, order, result)

    for effect in post:
        dtype = effect.damage_type
        if not dtype or dtype == "DT_ANY":
            for key in list(result):
                result[key] += scaled_base.get(key, 0.0) * effect.value
        else:
            bonus_base = (
                scaled_base.get(dtype, 0.0) if dtype in PHYSICAL_TYPES else base_total
            )
            result[dtype] = result.get(dtype, 0.0) + bonus_base * effect.value

    return {k: v for k, v in result.items() if v}


def _coalesce(
    added: dict[str, float], order: list[str], result: dict[str, float]
) -> None:
    """Pair base elements in install order and fold the results into ``result``."""
    pending = [d for d in order if d in added]

    used: set[int] = set()
    for i, first in enumerate(pending):
        if i in used or first not in BASE_ELEMENTS:
            continue
        for j in range(i + 1, len(pending)):
            if j in used:
                continue
            second = pending[j]
            if second not in BASE_ELEMENTS:
                continue
            compound = ELEMENT_COMBINATIONS.get(frozenset({first, second}))
            if compound:
                result[compound] = (
                    result.get(compound, 0.0) + added[first] + added[second]
                )
                used.update({i, j})
                break

    for i, dtype in enumerate(pending):
        if i not in used:
            result[dtype] = result.get(dtype, 0.0) + added[dtype]


def _read_innate_elements(
    weapon: Mapping[str, Any],
) -> tuple[list[tuple[str, float]], tuple[str, ...]]:
    """Read concrete native elements without guessing random Kuva/Tenet rolls."""
    entries: list[tuple[str, float]] = []
    raw = weapon.get("innateElements")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            dtype = item.get("damageType")
            value = item.get("value")
            if (
                isinstance(dtype, str)
                and dtype
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and float(value) >= 0.0
            ):
                entries.append((dtype, float(value)))
    candidates = weapon.get("innateElementCandidates")
    candidate_values = tuple(
        sorted(
            {
                value
                for value in (candidates if isinstance(candidates, (list, tuple)) else ())
                if isinstance(value, str) and value
            }
        )
    )
    entries.sort(key=lambda item: (INNATE_ELEMENT_ORDER.get(item[0], 99), item[0]))
    return entries, candidate_values


def _apply_innate_elements(
    damage_types: Mapping[str, float],
    *,
    base_total: float,
    entries: Iterable[tuple[str, float]],
) -> dict[str, float]:
    """Append native damage after ordinary mod coalescing.

    Existing compound damage is never split.  A simple native element may consume one
    remaining simple element, which models the Kuva/Tenet/Coda native combination
    phase while keeping unknown/random instances fail-closed.
    """
    result = dict(damage_types)
    for dtype, fraction in entries:
        amount = base_total * fraction
        if not dtype or amount == 0.0:
            continue
        if dtype in BASE_ELEMENTS:
            partner = next(
                (
                    candidate
                    for candidate in BASE_ELEMENTS
                    if candidate != dtype
                    and result.get(candidate, 0.0) != 0.0
                    and frozenset({dtype, candidate}) in ELEMENT_COMBINATIONS
                ),
                None,
            )
            if partner is not None:
                partner_amount = result.pop(partner)
                compound = ELEMENT_COMBINATIONS[frozenset({dtype, partner})]
                result[compound] = result.get(compound, 0.0) + partner_amount + amount
                continue
        result[dtype] = result.get(dtype, 0.0) + amount
    return {key: value for key, value in result.items() if value}


# -- target interaction ---------------------------------------------------------------


def _normalise_hit_location(value: str | None) -> str:
    """Validate and canonicalise a direct-hit location.

    ``None`` retains the historical body-hit behaviour.  Aliases are accepted at
    this boundary so the Go bridge and older callers can use ``headshot`` without
    changing the JSON schema.
    """
    if value is None:
        return "body"
    if not isinstance(value, str):
        raise TypeError("hit_location must be 'body' or 'head'")
    normalized = value.strip().casefold().replace("-", "_")
    if normalized in {"body", "torso", "body_hit"}:
        return "body"
    if normalized in {"head", "headshot", "head_hit", "headshot_hit", "weakpoint", "weak_point"}:
        return "head"
    raise ValueError(f"hit_location must be 'body' or 'head', got {value!r}")


def _finite_hit_value(value: Any, *, allow_zero: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    converted = float(value)
    if not math.isfinite(converted) or converted < 0.0 or (not allow_zero and converted == 0.0):
        return None
    return converted


def _mapping_value(value: Mapping[str, Any], *keys: str) -> Any:
    wanted = {key.casefold().replace("_", "") for key in keys}
    for actual, candidate in value.items():
        if str(actual).casefold().replace("_", "") in wanted:
            return candidate
    return None


def _mapping_has(value: Mapping[str, Any], *keys: str) -> bool:
    wanted = {key.casefold().replace("_", "") for key in keys}
    return any(str(actual).casefold().replace("_", "") in wanted for actual in value)


def _proxy_label(value: Mapping[str, Any]) -> str:
    for key in _HIT_PROXY_LABEL_KEYS:
        candidate = _mapping_value(value, key)
        if isinstance(candidate, str) and candidate:
            return candidate.strip().casefold().replace("-", "_").replace(" ", "_")
    return ""


def _proxy_multiplier(value: Mapping[str, Any]) -> float | None:
    for key in _HIT_PROXY_MULTIPLIER_KEYS:
        candidate = _finite_hit_value(_mapping_value(value, key), allow_zero=True)
        if candidate is not None:
            return candidate
    # A compact mapping such as {"head": 2.0} is a useful compatibility form.
    if len(value) == 1:
        return _finite_hit_value(next(iter(value.values())), allow_zero=True)
    return None


def _find_hit_proxy(value: Any, location: str) -> Mapping[str, Any] | None:
    """Find one hit-proxy record in mapping/list representations."""
    aliases = _HIT_PROXY_ALIASES[location]
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized_key = str(key).strip().casefold().replace("-", "_").replace(" ", "_")
            if normalized_key in aliases:
                if isinstance(nested, Mapping):
                    # A keyed compatibility fixture can still carry an explicit
                    # Part value. Do not let a misleading HEAD key override it.
                    part = _mapping_value(nested, "part")
                    if (
                        location == "head"
                        and isinstance(part, str)
                        and part.strip().casefold().replace("-", "_").replace(" ", "_")
                        not in aliases
                    ):
                        continue
                    return nested
                if _finite_hit_value(nested, allow_zero=True) is not None:
                    return {"damageMultiplier": nested}
        label = _proxy_label(value)
        if label in aliases or any(alias in label for alias in aliases if alias):
            return value
        for nested in value.values():
            found = _find_hit_proxy(nested, location)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found = _find_hit_proxy(nested, location)
            if found is not None:
                return found
    return None


def _hit_location_info(
    target: Mapping[str, Any],
    hit_location: str | None,
) -> tuple[str, float, float, list[str], dict[str, float]]:
    """Return direct/critical proxy multipliers and explicit limitations.

    WPEP's hit-proxy records use ``damageAtten`` for the direct body-part factor,
    ``criticalMultiplier`` for the critical branch only, and ``criticalChance`` as
    metadata.  A HEAD part carries the game's fixed 1.5x headshot factor on top of
    ``damageAtten``.  We intentionally do not apply ``criticalChance`` here because
    the current engine has no verified weakpoint-critical chance model.
    """
    location = _normalise_hit_location(hit_location)
    if location == "body":
        return location, 1.0, 1.0, [], {}

    raw = None
    for key in ("hitProxies", "hitProxy", "weakpoints", "weakPoints"):
        if key in target:
            raw = target.get(key)
            break
    proxy = _find_hit_proxy(raw, location) if raw is not None else None
    # Accept compact top-level fields emitted by older hand-built fixtures.
    if proxy is None:
        for key in ("headshotMultiplier", "headMultiplier"):
            value = _finite_hit_value(target.get(key), allow_zero=True)
            if value is not None:
                proxy = {"damageMultiplier": value}
                break
    if proxy is None:
        reason = "hit-location-head-invalid" if raw is not None else "hit-location-head-unavailable"
        return location, 1.0, 1.0, [reason], {}

    raw_atten = _mapping_value(proxy, "damageAtten", "damage_atten")
    atten = _finite_hit_value(raw_atten, allow_zero=True)
    atten_is_part_factor = atten is not None
    if atten is None:
        atten = _finite_hit_value(
            _mapping_value(proxy, "damageMultiplier", "multiplier"), allow_zero=True
        )
    if atten is None and not _mapping_has(proxy, "damageAtten", "damage_atten"):
        # WPEP omits DamageAtten when the proxy has no extra attenuation; the
        # native body-part factor is therefore 1.0, not an unknown multiplier.
        atten = 1.0
        atten_is_part_factor = True
    if atten is None:
        atten = _proxy_multiplier(proxy)
    if atten is None:
        return location, 1.0, 1.0, ["hit-location-head-invalid"], {}

    unsupported: list[str] = []
    if _mapping_has(proxy, "damageMultipliers", "damage_multipliers"):
        # These per-damage-type proxy overrides are exported, but the compact
        # simulator does not apply them yet. Surface the limitation explicitly.
        unsupported.append("hit-location-damage-multipliers-unapplied")

    critical = None
    for key in ("criticalMultiplier", "critical_multiplier"):
        critical = _finite_hit_value(_mapping_value(proxy, key), allow_zero=True)
        if critical is not None:
            break
    critical = 1.0 if critical is None else critical
    # Raw WPEP DamageAtten is the body-part factor; the game adds the fixed 1.5x
    # headshot factor for a real HEAD proxy. Compact hand-built ``damageMultiplier``
    # fixtures are already normalized and must not receive that factor twice.
    direct = atten * 1.5 if atten_is_part_factor else atten
    metadata: dict[str, float] = {
        "weakpointMultiplier": direct,
        "headcritMultiplier": critical,
    }
    chance = _finite_hit_value(_mapping_value(proxy, "criticalChance"), allow_zero=True)
    if chance is not None:
        metadata["headcritChance"] = chance
    return location, direct, critical, unsupported, metadata


def _eximus_pool_base(base: float, level: float, *, has_shield_or_armour: bool) -> float:
    """Apply the Wiki's level-dependent Eximus base-health curve."""
    coefficient = 0.25 if has_shield_or_armour else 0.375
    if level <= 15:
        scale = 1.0
    elif level <= 25:
        scale = 1.0 + 0.025 * (level - 15.0)
    elif level <= 35:
        scale = 1.25 + 0.125 * (level - 25.0)
    elif level <= 50:
        scale = 2.5 + (2.0 / 15.0) * (level - 35.0)
    elif level <= 100:
        scale = 4.5 + 0.03 * (level - 50.0)
    else:
        scale = 6.0
    return max(base * 1.1, coefficient * (base + 900.0) * scale)


def _eximus_shield_base(base: float, level: float) -> float:
    """Apply the Wiki's level-dependent Eximus base-shield curve."""
    if level <= 15:
        scale = 1.1
    elif level <= 25:
        scale = max(1.1, 1.0 + 0.025 * (level - 15.0))
    elif level <= 35:
        scale = max(1.1, 1.25 + 0.125 * (level - 25.0))
    elif level <= 50:
        scale = max(1.1, 2.5 + (2.0 / 15.0) * (level - 35.0))
    elif level <= 100:
        scale = max(1.1, 4.5 + 0.03 * (level - 50.0))
    else:
        scale = max(1.1, 6.0)
    return base * scale


def _overguard_level_multiplier(level: float) -> float:
    """Evaluate the Eximus/Overguard absolute-level f32 smoothstep curve."""
    level = max(float(level), 1.0)
    f1 = _float32(1.0 + 0.0015 * (level - 1.0) ** 4.0)
    f2 = _float32(1.0 + 260.0 * (level - 1.0) ** 0.9)
    if level <= 45.0:
        blend = 0.0
    elif level >= 50.0:
        blend = 1.0
    else:
        position = _float32((level - 45.0) / 5.0)
        blend = _float32(3.0 * position * position - 2.0 * position * position * position)
    return _float32(f1 + _float32(_float32(f2 - f1) * blend))


def _magnetic_defense_multiplier(magnetic_stacks: int) -> float:
    """Return the sourced Magnetic multiplier shared by Shield and Overguard."""
    return min(2.0 + 0.25 * (magnetic_stacks - 1), 4.25) if magnetic_stacks else 1.0


def _overguard_damage_multiplier(dtype: str, magnetic_stacks: int) -> float:
    return (1.5 if dtype in {"DT_RADIANT", "DT_VOID"} else 1.0) * _magnetic_defense_multiplier(magnetic_stacks)


def _supports_standard_eximus_formula(target: Mapping[str, Any]) -> bool:
    """Exclude Wiki-documented Eximus variants with their own health formulas."""
    identity = " ".join(
        str(target.get(key) or "")
        for key in ("path", "name", "nameEn", "nameZh", "nameInternal")
    ).casefold()
    return not any(token in identity for token in ("prosecutor", "warden", "archwing"))


def enemy_defenses(
    target: Mapping[str, Any],
    *,
    level: int | None = None,
    steel_path: bool = False,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return level-scaled defensive pools for one ordinary enemy.

    ``level`` is the final enemy level selected by the caller.  Steel Path applies
    the current 2.5x health/shield modifier; armor stays at its normal curve.  It
    does not silently add 100 levels; callers pass the displayed final level.
    Missing or ambiguous base-level data, Overguard and damage attenuation are
    surfaced through ``unsupported`` rather than approximated.
    """
    if not isinstance(steel_path, bool):
        raise TypeError("steel_path must be a boolean")
    if not isinstance(armour_strip, (int, float)) or isinstance(armour_strip, bool):
        raise TypeError("armour_strip must be a number between 0 and 1")
    armour_strip = float(armour_strip)
    if not math.isfinite(armour_strip) or not 0.0 <= armour_strip <= 1.0:
        raise ValueError(f"armour_strip must be between 0 and 1, got {armour_strip}")
    if not isinstance(elemental_armour_strip, (int, float)) or isinstance(elemental_armour_strip, bool):
        raise TypeError("elemental_armour_strip must be a number between 0 and 1")
    elemental_armour_strip = float(elemental_armour_strip)
    if not math.isfinite(elemental_armour_strip) or not 0.0 <= elemental_armour_strip <= 1.0:
        raise ValueError(
            f"elemental_armour_strip must be between 0 and 1, got {elemental_armour_strip}"
        )
    if level is not None:
        level = _require_int("level", level)
    enhancements = _enemy_enhancement_options(enemy_enhancements)

    unsupported: set[str] = set()
    health = _enemy_pool(target, "health", required=True, unsupported=unsupported)
    shield = _enemy_pool(target, "shield", required=False, unsupported=unsupported)
    base_level = _enemy_base_level(target, level, unsupported)
    faction = str(target.get("factionResistance") or "")

    enhancement_level = float(level if level is not None else (base_level if base_level is not None else 1.0))
    standard_eximus = enhancements["eximus"] and _supports_standard_eximus_formula(target)
    if enhancements["eximus"] and not standard_eximus:
        unsupported.add("eximus-special-variant")
    if standard_eximus:
        has_shield_or_armour = shield > 0.0 or bool(target.get("armour"))
        health = _eximus_pool_base(
            health,
            enhancement_level,
            has_shield_or_armour=has_shield_or_armour,
        )
        if shield > 0.0:
            shield = _eximus_shield_base(shield, enhancement_level)

    if level is not None and base_level is not None:
        health *= _level_curve_multiplier(
            max(level - base_level, 0.0),
            FACTION_HEALTH_SCALING.get(faction, DEFAULT_HEALTH_SCALING),
        )
        shield *= _level_curve_multiplier(
            max(level - base_level, 0.0),
            FACTION_SHIELD_SCALING.get(faction, DEFAULT_SHIELD_SCALING),
        )

    path_multiplier = STEEL_PATH_DEFENSE_MULTIPLIER if steel_path else 1.0
    shield_multiplier = path_multiplier
    armour_multiplier = 1.0
    health *= path_multiplier
    shield *= shield_multiplier
    # Current Wiki data separates Steel Path health/shield bonuses from armor;
    # applying 2.5x to armor overstates mitigation and makes faction comparisons
    # wrong.  Keep the explicit multiplier here for future sourced variants.
    armour = _scaled_armour(target, level, multiplier=1.0)
    armour *= 1.0 - armour_strip
    armour *= 1.0 - elemental_armour_strip

    overguard = target.get("overguard")
    if isinstance(overguard, (int, float)) and not isinstance(overguard, bool) and overguard:
        overguard = float(overguard)
    else:
        overguard = 0.0
    if standard_eximus:
        overguard = max(overguard, 12.0 * _overguard_level_multiplier(enhancement_level))
    elif target.get("hasOverguard"):
        unsupported.add("enemy-overguard")
    empowerment_multiplier = 1.0
    if enhancements["empowered"]:
        empowerment_multiplier = 2.0 + 0.5 * float(enhancements["playerCount"] or 1)
        health *= empowerment_multiplier
        shield *= empowerment_multiplier
    if enhancements["archimedea"]:
        overguard += health * 0.5
    if any(
        target.get(key)
        for key in (
            "damageAttenuation",
            "hasDamageAttenuation",
            "dynamicDamageResistance",
        )
    ):
        unsupported.add("enemy-damage-attenuation")
    declared = target.get("unsupportedDefenses")
    if isinstance(declared, (list, tuple, set, frozenset)):
        unsupported.update(str(value) for value in declared if value)

    return {
        "level": level,
        "baseLevel": base_level,
        "steelPath": steel_path,
        "steelPathMultiplier": path_multiplier,
        "steelPathShieldMultiplier": shield_multiplier,
        "steelPathArmorMultiplier": armour_multiplier,
        "health": health,
        "shield": shield,
        "armour": armour,
        "armourReduction": _armour_reduction(armour) if armour else 0.0,
        "elementalArmourStrip": elemental_armour_strip,
        "overguard": overguard,
        "overguardMultiplier": _overguard_level_multiplier(enhancement_level) if standard_eximus else 0.0,
        "magneticStacks": enhancements["magneticStacks"],
        "empoweredMultiplier": empowerment_multiplier,
        "enhancements": enhancements,
        "unsupported": sorted(unsupported),
    }


def damage_against(
    stats: ModdedStats,
    target: Mapping[str, Any],
    *,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    hit_location: str | None = None,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute expected per-hit damage against one enemy record.

    Args:
        stats: Modded weapon stats.
        target: A record from ``enemies.json``.
        level: Enemy level, used to scale health and armour above its base level.
        armour_strip: Fraction of armour removed, 0.0 to 1.0.
        hit_location: ``body`` (default) or ``head``.  Head hits consume the
            target's exported ``hitProxies`` multiplier; missing proxies fail closed
            to the historical body baseline and are listed in ``unsupported``.

    Returns:
        Breakdown with keys ``health``, ``shield``, ``armourReduction`` and
        ``perType``.
    """
    defenses = enemy_defenses(
        target,
        level=level,
        steel_path=steel_path,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        enemy_enhancements=enemy_enhancements,
    )
    location, hit_multiplier, hit_critical_multiplier, hit_unsupported, hit_metadata = _hit_location_info(
        target, hit_location
    )
    armour = defenses["armour"]
    overguard = float(defenses.get("overguard") or 0.0)
    magnetic_stacks = int(defenses.get("magneticStacks") or 0)
    faction_deltas = _faction_damage_deltas(target)
    armour_bypass = _damage_type_set(
        target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
    )
    shield_bypass = _damage_type_set(
        target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
    )

    per_type: dict[str, float] = {}
    for dtype, amount in stats.damage_types.items():
        if overguard > 0.0:
            value = _overguard_damage_multiplier(dtype, magnetic_stacks)
        else:
            value = _target_damage_multiplier(
                dtype,
                target,
                armour=armour,
                faction_deltas=faction_deltas,
                armour_bypass=armour_bypass,
                shield_bypass=shield_bypass,
            )
            if defenses["shield"] > 0.0 and dtype not in shield_bypass:
                value *= _magnetic_defense_multiplier(magnetic_stacks)
        value *= amount
        per_type[dtype] = value * stats.falloff_multiplier

    # All-factions buffs (Roar-style, empty symbol filter) stack with the
    # target-faction-specific row; an empty faction must not double-apply
    # the all-factions row.
    target_faction = str(target.get("faction") or "")
    faction_multiplier = stats.faction_damage_multipliers.get("", 1.0)
    if target_faction:
        faction_multiplier *= stats.faction_damage_multipliers.get(target_faction, 1.0)
    if faction_multiplier != 1.0:
        per_type = {
            damage_type: amount * faction_multiplier
            for damage_type, amount in per_type.items()
        }
    if hit_multiplier != 1.0:
        per_type = {
            damage_type: amount * hit_multiplier
            for damage_type, amount in per_type.items()
        }
    raw = sum(per_type.values()) * effective_hit_multiplier(
        stats.crit_chance,
        stats.crit_multiplier,
        stats.noncrit_damage_multiplier,
        hit_critical_multiplier,
        double_crit_chance=stats.double_crit_chance,
    )
    return {
        "perType": per_type,
        "perHit": raw,
        "perShot": raw * stats.multishot,
        # 膛室家族首发加成：弹匣第一发对目标的单发期望伤害。
        "firstShot": raw * stats.multishot * (1.0 + stats.first_shot_damage_bonus),
        "dps": raw * stats.multishot * stats.fire_rate,
        "factionMultiplier": faction_multiplier,
        "falloffMultiplier": stats.falloff_multiplier,
        "health": defenses["health"],
        "shield": defenses["shield"],
        "overguard": overguard,
        "magneticDefenseMultiplier": _magnetic_defense_multiplier(magnetic_stacks),
        "overguardDamageMultiplier": _magnetic_defense_multiplier(magnetic_stacks),
        "armour": armour,
        "armourReduction": _armour_reduction(armour) if armour else 0.0,
        "hitLocation": location,
        "hitMultiplier": hit_multiplier,
        **hit_metadata,
        "unsupported": sorted({*defenses["unsupported"], *hit_unsupported}),
    }


def enemy_kill_metrics(
    stats: ModdedStats,
    target: Mapping[str, Any],
    *,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    hit_location: str | None = None,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Estimate direct-hit EHP, trigger pulls, ammunition and TTK.

    Overguard is removed before shield/health. Shield-bypassing damage is applied to
    health while ordinary damage removes the shield. Once shields are exhausted,
    all direct damage is evaluated against health and armour. The result excludes
    status timelines, shield regeneration/gating and special attenuation. A head hit
    consumes an exported ``hitProxies`` multiplier; absent data is surfaced as
    unsupported rather than guessed.
    """
    defenses = enemy_defenses(
        target,
        level=level,
        steel_path=steel_path,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        enemy_enhancements=enemy_enhancements,
    )
    location, hit_multiplier, hit_critical_multiplier, hit_unsupported, hit_metadata = _hit_location_info(
        target, hit_location
    )
    unsupported = [*defenses["unsupported"], *hit_unsupported]
    pool_damage = _direct_damage_by_pool(
        stats,
        target,
        defenses["armour"],
        hit_multiplier=hit_multiplier,
        hit_critical_multiplier=hit_critical_multiplier,
        shield=defenses["shield"],
        overguard=defenses.get("overguard", 0.0),
        magnetic_stacks=int(defenses.get("magneticStacks") or 0),
    )

    trigger_equivalents: float | None = None
    if not unsupported:
        trigger_equivalents = _trigger_equivalents_to_kill(
            defenses["health"],
            defenses["shield"],
            defenses.get("overguard", 0.0),
            pool_damage["overguardPerTrigger"],
            pool_damage["shieldPerTrigger"],
            pool_damage["healthBypassPerTrigger"],
            pool_damage["healthAfterShieldPerTrigger"],
        )

    ammo_required: int | None = None
    burst_ttk: float | None = None
    sustained_ttk: float | None = None
    effective_health: float | None = None
    if trigger_equivalents is not None and math.isfinite(trigger_equivalents):
        # 首发加成：第一发多造成 bonus × 单发期望，等效少打 bonus 发；
        # 首发超杀时下限 1 发（目标存活就必须至少开一枪）。
        effective_triggers = trigger_equivalents
        if stats.first_shot_damage_bonus > 0:
            effective_triggers = max(trigger_equivalents - stats.first_shot_damage_bonus, 1e-9)
        ammo_required = math.ceil(max(effective_triggers - 1e-12, 0.0))
        target_faction = str(target.get("faction") or "")
        faction_multiplier = stats.faction_damage_multipliers.get("", 1.0)
        if target_faction:
            faction_multiplier *= stats.faction_damage_multipliers.get(target_faction, 1.0)
        raw_per_trigger = (
            stats.total_damage
            * effective_hit_multiplier(
                stats.crit_chance,
                stats.crit_multiplier,
                stats.noncrit_damage_multiplier,
                hit_critical_multiplier,
                double_crit_chance=stats.double_crit_chance,
            )
            * stats.falloff_multiplier
            * faction_multiplier
            * stats.multishot
            * hit_multiplier
        )
        effective_health = trigger_equivalents * raw_per_trigger
        if ammo_required == 0:
            burst_ttk = sustained_ttk = 0.0
        elif stats.fire_rate > 0:
            burst_ttk = (ammo_required - 1) / stats.fire_rate
            magazine = max(int(math.floor(stats.magazine)), 1)
            reloads = (ammo_required - 1) // magazine
            sustained_ttk = burst_ttk + reloads * max(stats.reload_time, 0.0)

    return {
        "supported": not unsupported,
        "defenses": defenses,
        "directDamage": pool_damage,
        "effectiveHealth": effective_health,
        "continuousTriggerPulls": trigger_equivalents,
        "ammoRequired": ammo_required,
        "burstTtkSeconds": burst_ttk,
        "sustainedTtkSeconds": sustained_ttk,
        "killableByDirectHits": (
            trigger_equivalents is not None and math.isfinite(trigger_equivalents)
        ),
        "hitLocation": location,
        "hitMultiplier": hit_multiplier,
        **hit_metadata,
        "unsupported": sorted(set(unsupported)),
        "assumptions": [
            "direct-hit-only",
            "final-enemy-level-is-explicit",
            "no-shield-regeneration-gating-or-overflow",
        ]
        + (["elemental-armour-strip-is-explicit-snapshot"] if elemental_armour_strip else [])
        + (["head-hit-proxy-multiplier-applied"] if location == "head" and not hit_unsupported else []),
    }


def expected_status_procs(
    stats: ModdedStats,
    *,
    forced_procs: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Return expected status-proc counts for one attack.

    Random procs are ``status_chance * multishot`` and are distributed by the final
    damage-type weights.  ``forced_procs`` is intentionally an explicit mapping of
    output damage type to expected count; no ``PT_*``/``DT_*`` name conversion is
    guessed from weapon metadata.  This keeps forced effects such as custom Lua
    attacks fail-closed until their mapping is verified.
    """
    chance = max(float(stats.status_chance), 0.0)
    shots = max(float(stats.multishot), 0.0)
    random_total = chance * shots
    weights = {
        dtype: max(float(amount), 0.0)
        for dtype, amount in stats.damage_types.items()
        if isinstance(dtype, str) and isinstance(amount, (int, float))
    }
    total_weight = sum(weights.values())
    result: dict[str, float] = {}
    if random_total and total_weight:
        result.update(
            {
                dtype: random_total * amount / total_weight
                for dtype, amount in weights.items()
                if amount
            }
        )

    # Verified Lua-backed impact conversion cards (Hemorrhage, Internal Bleeding,
    # Magnetic Welt).  Their chance is conditional on an Impact status proc and is
    # independent of the final damage-type weighting.  The raw script's 2.5 value is
    # the fire-rate threshold; the game doubles the conversion chance below it.
    impact_statuses = result.get("DT_IMPACT", 0.0)
    if impact_statuses:
        for dtype, adapters in stats.impact_proc_conversions.items():
            for adapter in adapters:
                conversion = float(adapter.get("chance", 0.0))
                threshold = float(adapter.get("fireRateThreshold", math.inf))
                multiplier = float(adapter.get("fireRateMultiplier", 1.0))
                if stats.fire_rate < threshold:
                    conversion *= multiplier
                result[dtype] = result.get(dtype, 0.0) + impact_statuses * conversion

    # IndependentStatusProcOnDamage is not a normal weighted status proc.  It is a
    # separate chance per damaging event, so expose it as its own expected count.
    for dtype, proc_chance in stats.independent_proc_chances.items():
        result[dtype] = result.get(dtype, 0.0) + shots * max(float(proc_chance), 0.0)

    if forced_procs is not None:
        if not isinstance(forced_procs, Mapping):
            raise TypeError("forced_procs must be a mapping of damage type to count")
        for dtype, count in forced_procs.items():
            if not isinstance(dtype, str) or not dtype:
                raise TypeError("forced_procs keys must be non-empty strings")
            result[dtype] = result.get(dtype, 0.0) + _require_nonnegative_finite(
                f"forced_procs[{dtype!r}]", count
            )
    return {dtype: value for dtype, value in result.items() if value}


def expected_victim_status_count(
    stats: ModdedStats,
    *,
    forced_procs: Mapping[str, float] | None = None,
) -> int:
    """Distinct proc types a sustained build can keep applying."""
    return sum(
        1
        for value in expected_status_procs(stats, forced_procs=forced_procs).values()
        if value > 0.0
    )


def expected_dot_damage(
    stats: ModdedStats,
    target: Mapping[str, Any] | None = None,
    *,
    forced_procs: Mapping[str, float] | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    hit_location: str | None = None,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the complete expected DoT damage caused by one attack.

    The breakdown is per proc type and includes expected proc count, duration,
    elemental bonus, target multiplier, per-second damage and total damage.  Slash,
    Heat, Toxin, Electricity and Gas use the current 0.35/0.5 coefficients and a
    six-second base duration.  Faction damage mods double-dip for DoT (one factor in
    the proc's base damage and one in its target interaction), while target faction
    resistance, armour, shield bypass and ranged falloff are applied explicitly.

    This is a single-attack expected-value helper.  It does not model Gas's capped
    ten-stack steady state, status refresh timing, or other Lua-driven interactions.
    """
    target = target or {}
    defenses = enemy_defenses(
        target,
        level=level,
        steel_path=steel_path,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        enemy_enhancements=enemy_enhancements,
    )
    location, hit_multiplier, hit_critical_multiplier, hit_unsupported, hit_metadata = _hit_location_info(
        target, hit_location
    )
    armour = defenses["armour"]
    overguard = float(defenses.get("overguard") or 0.0)
    magnetic_stacks = int(defenses.get("magneticStacks") or 0)
    faction_deltas = _faction_damage_deltas(target)
    armour_bypass = _damage_type_set(
        target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
    )
    shield_bypass = _damage_type_set(
        target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
    )
    procs = expected_status_procs(stats, forced_procs=forced_procs)
    dot_base = (
        stats.dot_base_damage
        if stats.dot_base_damage is not None
        else stats.total_damage
    )
    dot_base = max(float(dot_base), 0.0)
    duration = DOT_BASE_DURATION_SECONDS * max(float(stats.proc_duration_multiplier), 0.0)
    crit = effective_hit_multiplier(
        stats.crit_chance,
        stats.crit_multiplier,
        stats.noncrit_damage_multiplier,
        hit_critical_multiplier,
        double_crit_chance=stats.double_crit_chance,
    )
    proc_damage = max(float(stats.proc_damage_multiplier), 0.0)
    target_faction = str(target.get("faction") or "")
    faction_mod = stats.faction_damage_multipliers.get("", 1.0)
    if target_faction:
        faction_mod *= stats.faction_damage_multipliers.get(target_faction, 1.0)

    breakdown: dict[str, dict[str, float]] = {}
    total = 0.0
    for dtype, coefficient in DOT_DAMAGE_COEFFICIENTS.items():
        count = procs.get(dtype, 0.0)
        if not count:
            continue
        # Bleed is surfaced to callers as the Slash proc that caused it, but the
        # current injury definition deals DT_CINEMATIC damage.  Using DT_SLASH here
        # would incorrectly inherit faction-wide Slash weakness/resistance.
        interaction_type = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
        if overguard > 0.0:
            target_multiplier = _overguard_damage_multiplier(interaction_type, magnetic_stacks)
        else:
            target_multiplier = _target_damage_multiplier(
                interaction_type,
                target,
                armour=armour,
                faction_deltas=faction_deltas,
                armour_bypass=armour_bypass,
                shield_bypass=shield_bypass,
            )
            if defenses["shield"] > 0.0 and interaction_type not in shield_bypass:
                target_multiplier *= _magnetic_defense_multiplier(magnetic_stacks)
        elemental = stats.dot_elemental_multipliers.get(dtype, 1.0)
        per_second = (
            coefficient
            * dot_base
            * max(float(elemental), 0.0)
            * crit
            * proc_damage
            * stats.falloff_multiplier
            * hit_multiplier
            * target_multiplier
            * max(float(faction_mod), 0.0) ** 2
        )
        damage = per_second * duration
        expected = damage * count
        breakdown[dtype] = {
            "expectedProcs": count,
            "coefficient": coefficient,
            "durationSeconds": duration,
            "elementalMultiplier": max(float(elemental), 0.0),
            "critMultiplier": crit,
            "targetMultiplier": target_multiplier,
            "perSecond": per_second,
            "perProc": damage,
            "expectedDamage": expected,
        }
        total += expected

    return {
        "perType": breakdown,
        "total": total,
        "expectedProcs": procs,
        "durationSeconds": duration,
        "falloffMultiplier": stats.falloff_multiplier,
        "factionMultiplier": faction_mod,
        "armour": armour,
        "armourReduction": _armour_reduction(armour) if armour else 0.0,
        "elementalArmourStrip": elemental_armour_strip,
        "overguard": overguard,
        "hitLocation": location,
        "hitMultiplier": hit_multiplier,
        **hit_metadata,
        "unsupported": sorted({*defenses["unsupported"], *hit_unsupported}),
    }


def expected_status_damage(
    stats: ModdedStats,
    target: Mapping[str, Any] | None = None,
    *,
    forced_procs: Mapping[str, float] | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    hit_location: str | None = None,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return all currently modelled damaging status effects from one attack.

    The existing five DoTs remain authoritative through :func:`expected_dot_damage`.
    Blast is a delayed non-DoT hit per proc: 30% of modded base damage, unaffected
    by elemental bonuses. Its 3x area component is exposed only as ``aoePotential``
    and is deliberately excluded from the single-target total.
    """
    target = target or {}
    dot = expected_dot_damage(
        stats,
        target,
        forced_procs=forced_procs,
        level=level,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        steel_path=steel_path,
        hit_location=hit_location,
        enemy_enhancements=enemy_enhancements,
    )
    procs = dot["expectedProcs"]
    blast_count = procs.get("DT_EXPLOSION", 0.0)
    breakdown: dict[str, dict[str, float]] = {}
    non_dot_total = 0.0
    aoe_potential = 0.0
    unsupported = set(dot.get("unsupported", ()))

    if blast_count:
        defenses = enemy_defenses(
            target,
            level=level,
            steel_path=steel_path,
            armour_strip=armour_strip,
            elemental_armour_strip=elemental_armour_strip,
            enemy_enhancements=enemy_enhancements,
        )
        (
            location,
            hit_multiplier,
            hit_critical_multiplier,
            hit_unsupported,
            _hit_metadata,
        ) = _hit_location_info(target, hit_location)
        armour = defenses["armour"]
        overguard = float(defenses.get("overguard") or 0.0)
        magnetic_stacks = int(defenses.get("magneticStacks") or 0)
        faction_deltas = _faction_damage_deltas(target)
        armour_bypass = _damage_type_set(
            target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
        )
        shield_bypass = _damage_type_set(
            target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
        )
        if overguard > 0.0:
            target_multiplier = _overguard_damage_multiplier(
                "DT_EXPLOSION", magnetic_stacks
            )
        else:
            target_multiplier = _target_damage_multiplier(
                "DT_EXPLOSION",
                target,
                armour=armour,
                faction_deltas=faction_deltas,
                armour_bypass=armour_bypass,
                shield_bypass=shield_bypass,
            )
            if defenses["shield"] > 0.0 and "DT_EXPLOSION" not in shield_bypass:
                target_multiplier *= _magnetic_defense_multiplier(magnetic_stacks)

        crit = effective_hit_multiplier(
            stats.crit_chance,
            stats.crit_multiplier,
            stats.noncrit_damage_multiplier,
            hit_critical_multiplier,
            double_crit_chance=stats.double_crit_chance,
        )
        proc_damage = max(float(stats.proc_damage_multiplier), 0.0)
        faction_mod = stats.faction_damage_multipliers.get("", 1.0)
        target_faction = str(target.get("faction") or "")
        if target_faction:
            faction_mod *= stats.faction_damage_multipliers.get(target_faction, 1.0)
        modded_base = (
            stats.dot_base_damage
            if stats.dot_base_damage is not None
            else stats.total_damage
        )
        modded_base = max(float(modded_base), 0.0)
        per_proc = (
            BLAST_DAMAGE_COEFFICIENT
            * modded_base
            * crit
            * proc_damage
            * stats.falloff_multiplier
            * hit_multiplier
            * target_multiplier
            * max(float(faction_mod), 0.0) ** 2
        )
        expected = per_proc * blast_count
        aoe_potential = expected * BLAST_AOE_MULTIPLIER
        breakdown["DT_EXPLOSION"] = {
            "expectedProcs": blast_count,
            "coefficient": BLAST_DAMAGE_COEFFICIENT,
            "delaySeconds": BLAST_DELAY_SECONDS,
            "baseDamage": modded_base,
            "elementalMultiplier": 1.0,
            "critMultiplier": crit,
            "statusDamageMultiplier": proc_damage,
            "factionMultiplier": faction_mod,
            "hitMultiplier": hit_multiplier,
            "targetMultiplier": target_multiplier,
            "perProc": per_proc,
            "expectedDamage": expected,
            "aoeMultiplier": BLAST_AOE_MULTIPLIER,
            "aoePotential": aoe_potential,
        }
        non_dot_total = expected
        unsupported.update(defenses["unsupported"])
        unsupported.update(hit_unsupported)

    non_dot = {
        "perType": breakdown,
        "total": non_dot_total,
        "aoePotential": aoe_potential,
    }
    return {
        "dot": dot,
        "nonDot": non_dot,
        "dotTotal": dot["total"],
        "nonDotTotal": non_dot_total,
        "total": dot["total"] + non_dot_total,
        "expectedProcs": procs,
        "aoePotential": aoe_potential,
        "unsupported": sorted(unsupported),
    }


def sustained_status_damage(
    stats: ModdedStats,
    target: Mapping[str, Any] | None = None,
    *,
    attacks_per_second: float,
    status_rate_multiplier: float = 1.0,
    damage_rate_multiplier: float = 1.0,
    forced_procs: Mapping[str, float] | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    hit_location: str | None = None,
    enemy_enhancements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Steady-state direct plus damaging and damage-amplifying statuses.

    Stack counts use proc-rate times the exported status duration, capped by
    the in-game maximum. Viral/Magnetic vulnerability, Corrosive/Heat armor
    reduction, Cold critical damage and Puncture flat critical chance are then
    applied once to the sustained snapshot. Crowd control is intentionally not
    assigned fake damage.
    """
    target = target or {}
    rate = max(float(attacks_per_second), 0.0)
    proc_rate = rate * max(float(status_rate_multiplier), 0.0)
    damage_rate = rate * max(float(damage_rate_multiplier), 0.0)
    # 膛室家族（Primed Chamber / 蓄力装填）的首发伤害加成摊入稳态平均：
    # 每个弹匣循环第一发多造成 bonus×单发伤害，等效每发平均伤害
    # ×(1 + bonus/弹匣)，与 ModdedStats.sustained_dps 的折算口径一致。
    magazine = max(float(getattr(stats, "magazine", 0.0) or 0.0), 0.0)
    first_shot_bonus = max(
        float(getattr(stats, "first_shot_damage_bonus", 0.0) or 0.0), 0.0
    )
    if magazine > 0.0 and first_shot_bonus > 0.0 and damage_rate > 0.0:
        damage_rate *= 1.0 + first_shot_bonus / magazine
    probe = expected_status_damage(
        stats,
        target,
        forced_procs=forced_procs,
        level=level,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        steel_path=steel_path,
        hit_location=hit_location,
        enemy_enhancements=enemy_enhancements,
    )
    procs = probe["expectedProcs"]

    duration_scale = max(float(stats.proc_duration_multiplier), 0.0)

    def stacks(dtype: str, duration: float, cap: float) -> float:
        return min(
            max(float(procs.get(dtype) or 0.0) * proc_rate * duration * duration_scale, 0.0),
            cap,
        )

    stack_counts = {
        "viral": stacks("DT_VIRAL", 6.0, 10.0),
        "corrosive": stacks("DT_CORROSIVE", 8.0, 10.0),
        "magnetic": stacks("DT_MAGNETIC", 6.0, 10.0),
        "cold": stacks("DT_FREEZE", 6.0, 10.0),
        "puncture": stacks("DT_PUNCTURE", 10.0, 5.0),
        "heat": stacks("DT_FIRE", 6.0, 1.0),
    }

    def vulnerability(count: float) -> float:
        if count <= 0.0:
            return 1.0
        if count < 1.0:
            return 1.0 + count
        return min(2.0 + 0.25 * (count - 1.0), 4.25)

    corrosive_count = stack_counts["corrosive"]
    corrosive_strip = (
        0.26 * corrosive_count
        if corrosive_count < 1.0
        else min(0.26 + 0.06 * (corrosive_count - 1.0), 0.8)
    )
    heat_strip = 0.5 * stack_counts["heat"]
    combined_elemental_strip = 1.0 - (
        (1.0 - elemental_armour_strip)
        * (1.0 - corrosive_strip)
        * (1.0 - heat_strip)
    )
    cold_count = stack_counts["cold"]
    cold_proc_rate = float(procs.get("DT_FREEZE") or 0.0) * proc_rate
    cold_freeze_uptime = 0.0
    if cold_count >= 10.0 and cold_proc_rate > 0.0:
        freeze_duration = 3.0 * duration_scale
        rebuild_duration = 7.0 / cold_proc_rate
        cold_freeze_uptime = (
            freeze_duration / (freeze_duration + rebuild_duration)
            if freeze_duration > 0.0
            else 0.0
        )
        cold_crit = 0.35 * (1.0 - cold_freeze_uptime) + cold_freeze_uptime
    else:
        cold_crit = (
            0.1 * cold_count
            if cold_count < 1.0
            else min(0.1 + 0.05 * (cold_count - 1.0), 0.5)
        )
    puncture_crit = min(0.05 * stack_counts["puncture"], 0.25)
    adjusted_stats = replace(
        stats,
        crit_chance=max(float(stats.crit_chance) + puncture_crit, 0.0),
        crit_multiplier=max(float(stats.crit_multiplier) + cold_crit, 1.0),
    )
    kwargs = {
        "level": level,
        "armour_strip": armour_strip,
        "elemental_armour_strip": combined_elemental_strip,
        "steel_path": steel_path,
        "hit_location": hit_location,
        "enemy_enhancements": enemy_enhancements,
    }
    direct = damage_against(adjusted_stats, target, **kwargs)
    baseline_direct = damage_against(
        stats,
        target,
        level=level,
        armour_strip=armour_strip,
        elemental_armour_strip=elemental_armour_strip,
        steel_path=steel_path,
        hit_location=hit_location,
        enemy_enhancements=enemy_enhancements,
    )
    status = expected_status_damage(
        adjusted_stats, target, forced_procs=forced_procs, **kwargs
    )
    defenses = enemy_defenses(target, **{
        key: value for key, value in kwargs.items() if key != "hit_location"
    })
    active_pool = "overguard" if defenses["overguard"] > 0 else (
        "shield" if defenses["shield"] > 0 else "health"
    )
    viral_multiplier = vulnerability(stack_counts["viral"])
    existing_magnetic = int((enemy_enhancements or {}).get("magneticStacks") or 0)
    combined_magnetic = min(existing_magnetic + stack_counts["magnetic"], 10.0)
    magnetic_multiplier = vulnerability(combined_magnetic) / vulnerability(float(existing_magnetic))
    vulnerability_multiplier = viral_multiplier if active_pool == "health" else magnetic_multiplier
    shield_bypass = _damage_type_set(
        target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
    )

    def pool_multiplier(dtype: str) -> float:
        if defenses["overguard"] > 0.0:
            return magnetic_multiplier
        if defenses["shield"] > 0.0 and dtype not in shield_bypass:
            return magnetic_multiplier
        return viral_multiplier

    per_type = direct.get("perType") or {}
    direct_total = sum(float(value) for value in per_type.values())
    weighted_direct = sum(
        float(value) * pool_multiplier(str(dtype)) for dtype, value in per_type.items()
    )
    direct_dps = (
        float(direct.get("perShot") or 0.0)
        * (weighted_direct / direct_total if direct_total > 0.0 else 1.0)
        * damage_rate
    )
    baseline_direct_dps = float(baseline_direct.get("perShot") or 0.0) * damage_rate
    status_direct_bonus_dps = max(direct_dps - baseline_direct_dps, 0.0)
    dot_by_type: dict[str, float] = {}
    for dtype, row in ((status.get("dot") or {}).get("perType") or {}).items():
        expected_procs = max(float(row.get("expectedProcs") or 0.0), 0.0)
        interaction_type = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
        damage_multiplier = pool_multiplier(interaction_type)
        if dtype == "DT_GAS":
            active_procs = min(
                expected_procs * proc_rate * float(row.get("durationSeconds") or 0.0),
                10.0,
            )
            average_hit_multiplier = (
                max(float(damage_rate_multiplier), 0.0)
                / max(float(status_rate_multiplier), 0.0)
                if status_rate_multiplier
                else 0.0
            )
            value = float(row.get("perSecond") or 0.0) * active_procs * average_hit_multiplier
        else:
            value = float(row.get("expectedDamage") or 0.0) * damage_rate
        dot_by_type[dtype] = value * damage_multiplier
    dot_dps = sum(dot_by_type.values())
    non_dot_by_type = {
        dtype: float(row.get("expectedDamage") or 0.0)
        * damage_rate
        * pool_multiplier(str(dtype))
        for dtype, row in ((status.get("nonDot") or {}).get("perType") or {}).items()
    }
    proc_non_dot_dps = sum(non_dot_by_type.values())
    non_dot_dps = proc_non_dot_dps + status_direct_bonus_dps
    status_dps = dot_dps + non_dot_dps
    magnetic_break_pool = float(defenses.get(active_pool) or 0.0) if active_pool != "health" else 0.0
    magnetic_break_potential = magnetic_break_pool * 0.03 * combined_magnetic
    ramp_times = []
    for dtype, count in (
        ("DT_VIRAL", stack_counts["viral"]),
        ("DT_CORROSIVE", stack_counts["corrosive"]),
        ("DT_MAGNETIC", stack_counts["magnetic"]),
        ("DT_FREEZE", stack_counts["cold"]),
        ("DT_PUNCTURE", stack_counts["puncture"]),
        ("DT_FIRE", stack_counts["heat"]),
    ):
        per_second = float(procs.get(dtype) or 0.0) * proc_rate
        if count > 0.0 and per_second > 0.0:
            ramp_times.append(count / per_second)
    if status.get("dotTotal"):
        ramp_times.append(DOT_BASE_DURATION_SECONDS * duration_scale)
    if status.get("nonDotTotal"):
        ramp_times.append(BLAST_DELAY_SECONDS)
    steady_state_seconds = max(ramp_times, default=0.0)
    return {
        "model": "steady-status-rate",
        "attacksPerSecond": rate,
        "statusEventsPerSecond": proc_rate,
        "damageRateMultiplier": max(float(damage_rate_multiplier), 0.0),
        "statusRateMultiplier": max(float(status_rate_multiplier), 0.0),
        "steadyStateSeconds": steady_state_seconds,
        "stacks": stack_counts,
        "activePool": active_pool,
        "vulnerabilityMultiplier": vulnerability_multiplier,
        "viralDamageMultiplier": viral_multiplier,
        "magneticDamageMultiplier": magnetic_multiplier,
        "corrosiveArmourStrip": corrosive_strip,
        "heatArmourStrip": heat_strip,
        "elementalArmourStrip": combined_elemental_strip,
        "coldCriticalDamageBonus": cold_crit,
        "coldFreezeUptime": cold_freeze_uptime,
        "punctureCriticalChanceBonus": puncture_crit,
        "directDps": direct_dps,
        "baselineDirectDps": baseline_direct_dps,
        "statusDirectBonusDps": status_direct_bonus_dps,
        "dotDps": dot_dps,
        "dotByType": dot_by_type,
        "nonDotDps": non_dot_dps,
        "procNonDotDps": proc_non_dot_dps,
        "nonDotByType": non_dot_by_type,
        "statusDps": status_dps,
        # directDps already contains the status-amplified direct hit; only add
        # independent DoT/proc damage here to avoid counting that bonus twice.
        "totalDps": direct_dps + dot_dps + proc_non_dot_dps,
        "magneticBreakPotential": magnetic_break_potential,
        "perAttack": status,
        "unsupported": sorted(set(direct.get("unsupported") or ()) | set(status.get("unsupported") or ())),
    }


def _direct_damage_by_pool(
    stats: ModdedStats,
    target: Mapping[str, Any],
    armour: float,
    *,
    hit_multiplier: float = 1.0,
    hit_critical_multiplier: float = 1.0,
    shield: float = 0.0,
    overguard: float = 0.0,
    magnetic_stacks: int = 0,
) -> dict[str, float]:
    """Split one trigger's expected direct damage across overguard/shield/health."""
    faction_deltas = _faction_damage_deltas(target)
    armour_bypass = _damage_type_set(
        target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
    )
    shield_bypass = _damage_type_set(
        target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
    )
    common = (
        effective_hit_multiplier(
            stats.crit_chance,
            stats.crit_multiplier,
            stats.noncrit_damage_multiplier,
            hit_critical_multiplier,
            double_crit_chance=stats.double_crit_chance,
        )
        * stats.falloff_multiplier
        * stats.faction_damage_multipliers.get(str(target.get("faction") or ""), 1.0)
        * stats.multishot
        * hit_multiplier
    )
    shield_damage = 0.0
    health_bypass = 0.0
    health_after_shield = 0.0
    overguard_damage = 0.0
    has_shield = shield > 0.0
    for dtype, amount in stats.damage_types.items():
        faction = max(0.0, 1.0 + faction_deltas.get(dtype, 0.0))
        raw = amount * faction * common
        if overguard > 0.0:
            overguard_damage += amount * common * _overguard_damage_multiplier(dtype, magnetic_stacks)
        health = raw
        if armour and dtype not in armour_bypass:
            health *= 1.0 - _armour_reduction(armour)
        if dtype in shield_bypass:
            health_bypass += health
        elif has_shield:
            shield_damage += raw * _magnetic_defense_multiplier(magnetic_stacks)
            health_after_shield += health
        else:
            health_after_shield += health
    return {
        "overguardPerTrigger": overguard_damage,
        "shieldPerTrigger": shield_damage,
        "healthBypassPerTrigger": health_bypass,
        "healthAfterShieldPerTrigger": health_bypass + health_after_shield,
    }


def _trigger_equivalents_to_kill(
    health: float,
    shield: float,
    overguard: float,
    overguard_damage: float,
    shield_damage: float,
    health_bypass_damage: float,
    health_after_shield_damage: float,
) -> float:
    """Return continuous expected trigger pulls, preserving shield bypass."""
    if health <= 0:
        return 0.0
    pulls = 0.0
    if overguard > 0:
        if overguard_damage <= 0:
            return math.inf
        pulls = overguard / overguard_damage
    if shield <= 0:
        return pulls + (
            health / health_after_shield_damage
            if health_after_shield_damage > 0
            else math.inf
        )
    if shield_damage <= 0:
        return pulls + (
            health / health_bypass_damage if health_bypass_damage > 0 else math.inf
        )

    to_break_shield = shield / shield_damage
    if health_bypass_damage > 0:
        to_kill_through_shield = health / health_bypass_damage
        if to_kill_through_shield <= to_break_shield:
            return pulls + to_kill_through_shield
    remaining_health = max(health - health_bypass_damage * to_break_shield, 0.0)
    if remaining_health == 0:
        return pulls + to_break_shield
    if health_after_shield_damage <= 0:
        return math.inf
    return pulls + to_break_shield + remaining_health / health_after_shield_damage


def _target_damage_multiplier(
    dtype: str,
    target: Mapping[str, Any],
    *,
    armour: float,
    faction_deltas: Mapping[str, float],
    armour_bypass: frozenset[str] | set[str],
    shield_bypass: frozenset[str] | set[str],
) -> float:
    """Return target resistance/defense multiplier for one damage type."""
    value = max(0.0, 1.0 + faction_deltas.get(dtype, 0.0))
    shielded = bool(target.get("shield"))
    hits_health = not shielded or dtype in shield_bypass
    if hits_health and armour and dtype not in armour_bypass:
        value *= 1.0 - _armour_reduction(armour)
    return value


def _faction_damage_deltas(target: Mapping[str, Any]) -> Mapping[str, float]:
    """Return current faction-wide damage deltas for ``target``.

    Schema-v2 targets carry the exact current-build row.  Older exports can still use
    their stable ``factionResistance`` keyword; unknown/neutral targets deliberately
    receive no guessed modifier.
    """
    embedded = target.get("factionDamageModifiers")
    if embedded is None:  # compatibility with the short-lived draft field name
        embedded = target.get("factionModifiers")
    if isinstance(embedded, Mapping):
        return {
            str(dtype): float(value)
            for dtype, value in embedded.items()
            if isinstance(dtype, str)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        }
    keyword = target.get("factionResistance")
    if not isinstance(keyword, str):
        return {}
    return FACTION_DAMAGE_DELTAS.get(keyword, {})


def _damage_type_set(value: Any, fallback: frozenset[str]) -> frozenset[str]:
    if isinstance(value, (list, tuple, set, frozenset)):
        return frozenset(item for item in value if isinstance(item, str))
    return fallback


def _armour_reduction(armour: float) -> float:
    """Return Update 36 damage reduction for already-stripped armour.

    The level-scaled source armour is clamped before strip.  Partial strip may then
    leave less than the 200 source minimum, so this final curve only clamps to the
    physical 0..2700 range: ``0.9 * sqrt(armour / 2700)``.
    """
    if armour <= 0:
        return 0.0
    effective = min(float(armour), ARMOUR_CLAMP_MAX)
    return ARMOUR_MAX_REDUCTION * math.sqrt(effective / ARMOUR_CLAMP_MAX)


def _enemy_pool(
    target: Mapping[str, Any],
    key: str,
    *,
    required: bool,
    unsupported: set[str],
) -> float:
    value = target.get(key, 0.0)
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        unsupported.add(f"enemy-{key}-invalid")
        return 0.0
    if required and value <= 0:
        unsupported.add(f"enemy-{key}-missing")
    return float(value)


def _enemy_base_level(
    target: Mapping[str, Any], level: int | None, unsupported: set[str]
) -> float | None:
    base = target.get("baseLevel")
    if isinstance(base, (int, float)) and not isinstance(base, bool) and base >= 0:
        return float(base)
    if level is None:
        return None
    candidates = target.get("baseLevelCandidates")
    if isinstance(candidates, (list, tuple)) and len(candidates) > 1:
        unsupported.add("enemy-base-level-ambiguous")
    else:
        unsupported.add("enemy-base-level-missing")
    return None


def _scaled_armour(
    target: Mapping[str, Any], level: int | None, *, multiplier: float = 1.0
) -> float:
    """Scale and clamp base armour before any armour strip is applied."""
    base = target.get("armour") or 0.0
    if not isinstance(base, (int, float)) or isinstance(base, bool) or base <= 0:
        return 0.0
    scale = 1.0
    if target.get("usesNpcArmourCurve") is not False:
        scale = _level_scale(target, level)
    return min(
        max(float(base) * scale * multiplier, ARMOUR_CLAMP_MIN),
        ARMOUR_CLAMP_MAX,
    )


def _level_scale(target: Mapping[str, Any], level: int | None) -> float:
    """Return the current NPC armour scaling factor above the base level."""
    base = target.get("baseLevel")
    if level is None or not isinstance(base, (int, float)) or level <= base:
        return 1.0
    return _level_curve_multiplier(level - base, ARMOUR_SCALING)


def _level_curve_multiplier(
    delta: float, curve: tuple[float, float, float, float]
) -> float:
    """Evaluate one two-power attenuation curve with the game's smooth blend."""
    if delta <= 0:
        return 1.0
    low_multiplier, low_exponent, high_multiplier, high_exponent = curve
    low = low_multiplier * delta**low_exponent
    high = high_multiplier * delta**high_exponent
    if delta < 70:
        transition = 0.0
    elif delta > 80:
        transition = 1.0
    else:
        position = (delta - 70.0) / 10.0
        transition = 3.0 * position**2 - 2.0 * position**3
    return 1.0 + low + (high - low) * transition
