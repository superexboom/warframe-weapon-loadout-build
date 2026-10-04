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

from .combat_events import direct_fire_ledger
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

# 已知「普通模式含 radial/field 部件但 Rabbit 2D 导出无数据」的武器清单
# （wiki 交叉核对；wfsim 实测占比见值）。key = 导出 path，value = 部件类别。
# 注意：components=True 的武器（Angstrum/Staticor/Kuva Bramma/Lenz 等）已走
# projectile-component-damage-unapplied 诊断，不在此清单；这里只收「连
# components 字段都没有」的。数据管线升级（wiki Lua 模块源）后清空。
_KNOWN_MULTIPART_PATHS: dict[str, str] = {
    "/Lotus/Weapons/Corpus/LongGuns/CrpBFG/CrpBFG": "radial",  # Opticor（wfsim: radial 占 32%）
    "/Lotus/Weapons/Corpus/LongGuns/CrpBFG/Vandal/VandalCrpBFG": "radial",  # Opticor Vandal
    "/Lotus/Weapons/MachineGun/PistolGrenadeLauncher/PistolGrenadeLauncher": "radial",  # Angstrum 副模式
}


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
    # Hunter Munitions: a critical pellet rolls its own Slash status, outside
    # status chance and damage-type weights (ModdedStats.crit_proc_chances).
    "WEAPON_SLASH_PROC_ON_CRIT_CHANCE": "crit_proc_chance",
    "WEAPON_FIRE_ITERATIONS": "multishot",
    "WEAPON_FIRE_RATE": "fire_rate",
    "WEAPON_CLIP_MAX": "magazine",
    "WEAPON_RELOAD_SPEED": "reload_time",
    "WEAPON_RELOAD_TIME": "reload_time_multiplier",
    "WEAPON_PROJECTILE_SPEED": "projectile_speed",
    "WEAPON_CHARGE_RATE": "charge_rate",
    "WEAPON_AMMO_CONSUME_RATE": "ammo_cost",
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
    "WEAPON_NOCRIT_CHANCE": "noncrit_damage_chance",
    "WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER": "incarnon_charge_multiplier",
    "RUNTIME_INCARNON_STAT_CONVERSION": "incarnon_stat_conversion",
    "WEAPON_LOW_CRIT_VALUE": "low_crit_threshold",
    "WEAPON_LOW_CRIT_DAMAGE": "low_crit_damage",
    "WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX": "anti_proc_crit_threshold",
    "WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS": "anti_proc_crit_bonus",
    "WEAPON_AMMO_POOL_MULTISHOT_DAMAGE": "ammo_pool_multishot_damage",
    "WEAPON_VICTIM_CRIT_CHANCE": "victim_crit_chance",
    "WEAPON_VICTIM_CRIT_DAMAGE": "victim_crit_damage",
    "WEAPON_VICTIM_DAMAGE_AMOUNT": "victim_damage",
    "RUNTIME_MQ_AUGMENT": "event_only",
    "RUNTIME_ONOS_CRITS_FOR_HITS": "event_only",
    "RUNTIME_RESERVE_AMMO_REFUND": "event_only",
    "RUNTIME_RELOAD_PROJECTILE_TOGGLE": "event_only",
    "RUNTIME_PUNCTURE_ARMOR_STRIP": "event_only",
    "RUNTIME_MAGAZINE_RESTORE": "event_only",
    "RUNTIME_MITER_CHARGE_AOE": "event_only",
    "RUNTIME_CONSECUTIVE_HIT_DAMAGE": "event_only",
    # ── 词条融合新词条（2026.09.22，引擎乘区已逆向裁决）──────────────
    # WEAPON_CRIT_CHANCE_WEAKPOINT：与 WEAPON_CRIT_CHANCE 加算进同一次
    # 判定（fn 0x1406dc47e 链 244-248，IsWeakpoint 门控）——引擎侧门控在
    # 伤害事件的 mIsWeakpoint 标志上；面板口径按无瞄准基准的弱命中期望
    # 折算（headshot_chance 加权），与 headshot_bonus_multiplier 同一
    # 折算通道。
    "WEAPON_CRIT_CHANCE_WEAKPOINT": "weakpoint_crit_chance",
    "WEAPON_CRIT_CHANCE_BODY_PART": "bodypart_crit_chance",
    # WEAPON_DAMAGE_WEAKPOINT：条件升级管线（与 IF_VICTIM_PROC_ACTIVE
    # 同系统，enum 266），独立乘区于部位倍率：
    #   伤害 × DamageAtten(部位) × (1 + 弱点加成)
    # 面板口径按弱命中期望折算（同上）。DoT/径向范围静态未决（fail-open
    # 到直击口径，sidecar 登记）。
    "WEAPON_DAMAGE_WEAKPOINT": "weakpoint_damage",
    "RUNTIME_LOCK_MULTISHOT": "multishot_lock",
    "RUNTIME_LOCK_FIRE_RATE": "fire_rate_lock",
    "RUNTIME_PRIMARY_COMPRESSION": "compression",
    "WEAPON_EXPLOSION_RADIUS": "explosion_radius",
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


def _rebuild_scenario(
    aiming: bool,
    heavy_attack: bool,
    combo_tier: int,
    victim_status_count: int,
    conditional_stacks: Mapping[str, int],
    distance: float | None,
    cloaked: bool,
    nearest_enemy_distance: float | None,
    trigger_policy: str,
    incarnon_cycle: bool = False,
    detonation_delay_seconds: float = 0.0,
    detonation_batch_size: int = 1,
    combat_state: Mapping[str, Any] | None = None,
) -> "Scenario":
    """Scenario.__reduce__ 的重建入口（pickle 反序列化路径）。"""
    return Scenario(
        aiming=aiming,
        heavy_attack=heavy_attack,
        combo_tier=combo_tier,
        victim_status_count=victim_status_count,
        conditional_stacks=conditional_stacks,
        distance=distance,
        cloaked=cloaked,
        nearest_enemy_distance=nearest_enemy_distance,
        trigger_policy=trigger_policy,
        incarnon_cycle=incarnon_cycle,
        detonation_delay_seconds=detonation_delay_seconds,
        detonation_batch_size=detonation_batch_size,
        combat_state=combat_state or {},
    )


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
    # 触发类效果策略（wfsim StackPolicy 的移植）：
    #   assumed_max — 面板/优化器口径：on-kill/条件层数恒满（100% 触发）。
    #   emergent    — 战斗口径：层数从零爬升，按触发率/衰减模拟（窗口模型）。
    # 影响三处：mod conditional_stacks、赋能 stacks、灵化 on-kill 进化。
    trigger_policy: str = "assumed_max"
    # 灵化循环口径（2026-09-24 用户口径分离）：
    #   False（默认）— 常驻灵化：灵化形态零装填（170 充能池近似，30s
    #     窗口打不空），紫卡分析维持此口径。
    #   True — 真实循环：灵化形态按「池耗尽 → 回基础形态充能 → 再灵化」
    #     折算可用率（灵化段窗口 × availability；availability 由灵化池
    #     容量与充能时长估计，缺数据时 0.5 并在 unsupported 注记）。
    incarnon_cycle: bool = False
    # Explicit player cadence for remote mines; no spatial hit-loss model.
    detonation_delay_seconds: float = 0.0
    detonation_batch_size: int = 1
    combat_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.aiming, bool)
            or not isinstance(self.heavy_attack, bool)
            or not isinstance(self.cloaked, bool)
        ):
            raise TypeError("aiming, heavy_attack and cloaked must be booleans")
        if not isinstance(self.incarnon_cycle, bool):
            raise TypeError("incarnon_cycle must be a boolean")
        _require_int("combo_tier", self.combo_tier, maximum=11)
        _require_int("victim_status_count", self.victim_status_count)
        object.__setattr__(self, 'detonation_delay_seconds',
                           _require_nonnegative_finite('detonation_delay_seconds', self.detonation_delay_seconds))
        _require_int('detonation_batch_size', self.detonation_batch_size, maximum=8)
        if self.detonation_batch_size == 0:
            raise ValueError('detonation_batch_size must be at least one')
        if self.trigger_policy not in ("assumed_max", "emergent"):
            raise TypeError("trigger_policy must be assumed_max or emergent")
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
        if not isinstance(self.combat_state, Mapping):
            raise TypeError('combatState must be an object')
        numeric = {'frameArmor','energyPool','sprintMultiplier','energySpent','energySpendPerSecond','nearbyRadius','detonationWaitSeconds','stugBounceDelaySeconds','stugChildDetonateSeconds','orbAbsorbedDamage',
                   'selfShieldBreakAt','selfShieldBreakInterval','selfOverguardBreakAt','selfOverguardBreakInterval','selfShieldHitAt','selfShieldHitInterval'}
        numeric |= {'equipFromPrimaryAt','equipFromPrimaryInterval','abilityUseAt','abilityUseInterval'}
        binary = {'overshields','channeling','aimGliding','sliding','incarnonMeleeActive','orbSpecialShield','onosRadialHit'}
        integers = {'nearbyEnemies':1000,'stugBounceHits':2,'stugChildHits':5,'detonateAfterShots':20,'orbPasses':3,'orbStacks':3,'orbRank':6,'punchthroughTargets':100,'abilityUses':100000}
        allowed = numeric | binary | set(integers) | {'projectileMode','equippedWeapons','emptySlots','orbAbsorbedDamageType','orbAbsorbedDamageTypes'}
        if set(self.combat_state) - allowed:
            raise ValueError('combatState has unsupported fields: ' + ', '.join(sorted(set(self.combat_state)-allowed)))
        state = {}
        for key,value in self.combat_state.items():
            if key in numeric:
                state[key] = _require_nonnegative_finite('combatState.'+key,value)
            elif key in binary:
                if not isinstance(value,bool):
                    raise TypeError('combatState.'+key+' must be a boolean')
                state[key] = value
            elif key in integers:
                state[key] = _require_int('combatState.'+key,value,maximum=integers[key])
                if key in {'detonateAfterShots','orbStacks'} and not value:
                    raise ValueError('combatState.'+key+' must be at least one')
            elif key=='projectileMode':
                if value not in {'stacked','isolated','manual'}:
                    raise ValueError('combatState.projectileMode must be stacked, isolated or manual')
                state[key] = value
            elif key=='orbAbsorbedDamageType':
                if value not in {*BASE_ELEMENTS,*PHYSICAL_TYPES,*ELEMENT_COMBINATIONS.values()}:
                    raise ValueError('combatState.orbAbsorbedDamageType must be a native damage type')
                state[key] = value
            elif key=='orbAbsorbedDamageTypes':
                try:
                    vector = dict(value)
                except (TypeError,ValueError):
                    raise TypeError('combatState.orbAbsorbedDamageTypes must be a damage vector') from None
                if not vector or set(vector)-{*BASE_ELEMENTS,*PHYSICAL_TYPES,*ELEMENT_COMBINATIONS.values()}:
                    raise ValueError('combatState.orbAbsorbedDamageTypes must contain native damage types')
                state[key] = tuple(sorted((dtype,_require_nonnegative_finite('combatState.orbAbsorbedDamageTypes.'+dtype,amount)) for dtype,amount in vector.items()))
            else:
                if not isinstance(value,(list,tuple)) or len(value)>3 or any(not isinstance(x,str) or not x for x in value):
                    raise TypeError('combatState.'+key+' must contain up to three strings')
                if key=='emptySlots' and any(x not in {'primary','secondary','melee'} for x in value):
                    raise ValueError('combatState.emptySlots contains an unsupported slot')
                state[key] = tuple(value)
        object.__setattr__(self,'combat_state',MappingProxyType(state))

        stacks: dict[str, int] = {}
        for key, value in self.conditional_stacks.items():
            if not isinstance(key, str) or not key:
                raise TypeError("conditional stack keys must be non-empty strings")
            stacks[key] = _require_int(f"conditional_stacks[{key!r}]", value)
        object.__setattr__(self, "conditional_stacks", MappingProxyType(stacks))

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle 支持：conditional_stacks 的 MappingProxyType 不可序列化
        （多进程 beam 评估的 job 参数），序列化时物化成普通 dict；
        反序列化经 __init__/__post_init__ 重新包成 proxy，语义不变。"""
        return (
            _rebuild_scenario,
            (
                self.aiming,
                self.heavy_attack,
                self.combo_tier,
                self.victim_status_count,
                dict(self.conditional_stacks),
                self.distance,
                self.cloaked,
                self.nearest_enemy_distance,
                self.trigger_policy,
                self.incarnon_cycle,
                self.detonation_delay_seconds,
                self.detonation_batch_size,
                dict(self.combat_state),
            ),
        )


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
    from .runtime_adapters import mq_augment_multiplier
    multiplier = mq_augment_multiplier(mod,rank)
    if multiplier is not None:
        return ModEffectList([ModEffect('RUNTIME_MQ_AUGMENT','ADD',multiplier,source_path=source_path)])
    runtime_scripts = mod.get("runtimeScripts") or {}
    adapter = resolve_runtime_adapter(mod, rank) if runtime_scripts else None
    if runtime_scripts and adapter is None:
        return ModEffectList(skipped=[f'{source_path or "?"}: unsupported[runtime-script]'])

    # Range Advantage and Spectral Serration carry a placeholder NONE/conditional
    # effect in the export.  Their adapter emits a normal damage effect only when
    # the explicit scenario condition is active; never leave the placeholder as an
    # unconditional bonus.  Prototype retains its normal elemental effect.
    raw_effects = mod.get("effects") or ()
    if adapter is not None and adapter.kind in {"range_damage", "cloak_damage","consecutive_hit_damage"}:
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
        if adapter.kind=='consecutive_hit_damage':
            effects.append(ModEffect('RUNTIME_CONSECUTIVE_HIT_DAMAGE','ADD',adapter.damage_bonus,
                                     source_path=source_path,runtime_threshold=adapter.duration))
        if adapter.kind == 'lock_fire_rate':
            effects.append(ModEffect('RUNTIME_LOCK_FIRE_RATE','SET',1.,source_path=source_path))
        if adapter.kind == 'lock_multishot':
            effects.append(ModEffect(
                upgrade_type='RUNTIME_LOCK_MULTISHOT', operation='SET', value=1.0,
                supported=True, source_path=source_path, runtime_kind=adapter.kind,
            ))
        elif adapter.kind == 'impact_conversion':
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

    from .runtime_adapters import compression_configuration
    compression = compression_configuration(arcane, rank)
    if compression:
        return ModEffectList([ModEffect('RUNTIME_PRIMARY_COMPRESSION','ADD',
            compression['damagePerMeter']*uptime,source_path=arcane.get('path'),
            runtime_chance=compression['ammoPerMeter']*uptime)])
    from .status_arcanes import configuration as status_configuration
    if status_configuration(arcane, rank):
        return ModEffectList([])  # Event-only; no fabricated static stat.
    from .enervate import configuration
    if configuration(arcane, rank):
        # Explicit state only; the shared replay owns emergent state/reset.
        return ModEffectList([ModEffect('WEAPON_CRIT_CHANCE', 'ADD', .1*stacks*uptime,
                                        source_path=arcane.get('path'))])
    from .runtime_adapters import verified_crux_condition
    crux = verified_crux_condition(arcane)
    if crux is not None:
        arcane = {**arcane, 'runtimeScripts': {}, 'effects': [], 'conditionalEffects': [crux]}
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
    # Crit-conditioned procs (Hunter Munitions): chance per damaging instance
    # that rolled crit tier >= 1. Counted by expected_status_procs at the hit
    # location's crit chance; the DoT seed reads E[crit multiplier | crit].
    crit_proc_chances: dict[str, float] = field(default_factory=dict)
    innate_damage_types: dict[str, float] = field(default_factory=dict)
    innate_element_candidates: tuple[str, ...] = ()
    # Populated only for an exported single heavy attack. ``heavy_damage`` is
    # expected direct damage (crit averaged); component ``damage`` stays non-crit.
    heavy_damage: float | None = None
    heavy_components: list[dict[str, Any]] = field(default_factory=list)
    double_crit_chance: float = 0.0
    # 膛室家族首发伤害加成（最终伤害乘区，只作用于弹匣第一发）。
    first_shot_damage_bonus: float = 0.0
    # ── 词条融合新词条（弱点家族，2026.09.22）─────────────────────────
    # 弱点伤害加成（WEAPON_DAMAGE_WEAKPOINT，条件乘区：弱点命中时
    # ×(1+bonus)，与部位倍率独立；面板按弱命中期望折算）。
    weakpoint_damage_bonus: float = 0.0
    # 弱点暴击几率加成（WEAPON_CRIT_CHANCE_WEAKPOINT，与基础暴击加算，
    # 弱点命中门控；面板按弱命中期望折算）。
    weakpoint_crit_chance_bonus: float = 0.0
    weakpoint_crit_chance_relative: float = 0.0
    bodyshot_crit_multiplier: float = 1.0
    base_crit_chance: float = 0.0
    # Per-trigger ammo cost in sustained rate（Twin Grakatas 类 ammoCost=2）
    ammo_cost: float = 1.0
    # CO bucket（对触发目标增伤，Galvanized Aptitude 类）：emergent 窗口模型
    # 按每步实际活异常类型数重算。co_assumed_count 记录面板预乘时的层数。
    co_bucket: list[ModEffect] = field(default_factory=list)
    co_assumed_count: float = 0.0
    # Beams merge multishot into one damage/status instance.
    continuous: bool = False
    # An exported explosion has no direct weakpoint impact.
    radial_only: bool = False
    explosion_radius_multiplier: float = 1.0
    # Native forced statuses per projectile; explicit caller forced_procs remain
    # additional per-trigger counts. Never inherit a different component here.
    native_forced_procs: dict[str, float] = field(default_factory=dict)
    incarnon_charge_multiplier: float = 1.0
    low_crit_threshold: float | None = None
    low_crit_damage_base: float | None = None
    low_crit_damage_bonus: float = 0.0
    ammo_pool_multishot_cost: float = 0.0
    ammo_pool_damage_bonus: float = 0.0
    victim_full_crit_chance: float = 0.0
    victim_full_crit_damage: float = 0.0
    victim_low_health_multiplier: float = 1.0
    projectile_speed_multiplier: float = 1.0
    charge_rate_multiplier: float = 1.0
    charge_seconds: float = 0.0
    bow_draw_seconds: float | None = None
    # Inactive compatibility fields for deferred_spread research. Production
    # apply_mods leaves these unset; replay/scoring never consumes them.
    spread_min_deg: float | None = None
    spread_max_deg: float | None = None


    @property
    def total_damage(self) -> float:
        return sum(self.damage_types.values())

    @property
    def trigger_interval(self) -> float:
        if self.bow_draw_seconds is not None:
            return self.bow_draw_seconds
        return (1./self.fire_rate+self.charge_seconds) if self.fire_rate>0 else math.inf

    @property
    def burst_dps(self) -> float:
        """Damage per second while the trigger is held, ignoring reloads."""
        return (
            self.total_damage
            * self.multishot
            * (1./self.trigger_interval if self.trigger_interval>0 else self.fire_rate)
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
        cost=max(self.ammo_cost,0.)
        if cost==0 and self.bow_draw_seconds is not None:
            cost=1.
        if cost==0:
            return self.burst_dps
        shots = self.magazine/cost
        cycle = shots*self.trigger_interval+(self.reload_time or 0.)
        return (
            self.total_damage
            * self.multishot
            * (shots+self.first_shot_damage_bonus)
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
        """Trigger pulls per second including reload downtime.

        ammoCost>1 的模式（Twin Grakatas 类：每扳机耗 2 发弹药）按
        ``triggers_per_mag = magazine / ammoCost`` 折算弹匣——wfsim
        MECHANICS §「Continuous ammo cost」：ammo_cost 乘进弹匣消耗，改变
        reload cadence（wiki Twin Grakatas：120 弹匣 / 2 = 60 扳机/匣，
        wfsim 实测 413 shots / 6 reloads 吻合）。
        """
        if not self.magazine or not self.fire_rate:
            return 1./self.trigger_interval if self.trigger_interval>0 and math.isfinite(self.trigger_interval) else max(float(self.fire_rate),0.)
        ammo_cost = max(float(self.ammo_cost), 0.0)
        if ammo_cost==0 and self.bow_draw_seconds is not None:
            ammo_cost=1.
        if ammo_cost == 0.0:
            return 1./self.trigger_interval if self.trigger_interval>0 else self.fire_rate
        triggers = max(float(self.magazine) / ammo_cost, 0.0)
        if triggers <= 0.0:
            return 0.0
        cycle = triggers*self.trigger_interval+(self.reload_time or 0.)
        return max(float(triggers / cycle), 0.0) if cycle else 0.0

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


def crit_tier_seed_distribution(
    crit_chance: float,
    crit_multiplier: float,
    noncrit_damage_multiplier: float = 1.0,
    critical_multiplier_factor: float = 1.0,
    *, double_crit_chance: float = 0.0,
) -> list[tuple[float, float]]:
    """Per-proc DoT seed distribution by crit tier (wfsim MECHANICS §6).

    Every proc stores the damage snapshot of the hit that caused it — including
    THAT hit's crit tier — and ticks read the seed, not the crit-averaged panel
    (docs/MECHANICS.md §6 "Every DoT has a PARENT"; measured in wfsim via
    a_hunter_munitions_bleed_is_indistinguishable_from_any_other_slash).

    For an EXPECTED-VALUE model the seed distribution is the tier decomposition:
    ``floor(cc)`` guaranteed tiers plus a fractional chance of one more, each
    weighted by its probability.  Averaging the returned (weight, seed_factor)
    pairs reproduces :func:`effective_hit_multiplier` exactly — the split only
    matters downstream, where tier-dependent seeds meet NON-linear per-tick
    amplifiers (live armour strip, viral ramp) and the average of products no
    longer equals the product of averages.
    """
    promoted=_crit_tier_weights(crit_chance,double_crit_chance)
    cd=max(1.0,crit_multiplier*float(critical_multiplier_factor))
    return [(weight, max(1.0,noncrit_damage_multiplier) if tier==0 else 1+tier*(cd-1))
            for tier,weight in sorted(promoted.items()) if weight>0]


def _crit_tier_weights(crit_chance: float, double_crit_chance: float = 0.0) -> dict[int, float]:
    """Probability of each crit tier, Vigilante promotion included."""
    chance=max(float(crit_chance),0.0)
    whole=int(chance);fraction=chance-whole
    promotion=min(1.0,max(0.0,float(double_crit_chance)))
    tiers={whole:1-fraction}
    if fraction:tiers[whole+1]=fraction
    promoted={}
    for tier,weight in tiers.items():
        rate=promotion if tier>0 else 0.0
        promoted[tier]=promoted.get(tier,0.0)+weight*(1-rate)
        if rate:promoted[tier+1]=promoted.get(tier+1,0.0)+weight*rate
    return promoted


def critical_tier_seed_distribution(
    crit_chance: float,
    crit_multiplier: float,
    critical_multiplier_factor: float = 1.0,
    *, double_crit_chance: float = 0.0,
) -> list[tuple[float, float]]:
    """Seed distribution of a proc that only a critical hit can cause.

    Hunter Munitions rolls on crit tier >= 1, so its Slash seed is the tier
    decomposition conditioned on a crit: below 100% crit chance every such
    proc is a yellow crit (or a promoted orange one), never the all-hit
    average that :func:`crit_tier_seed_distribution` gives natural procs.
    """
    tiers={tier:weight for tier,weight in _crit_tier_weights(crit_chance,double_crit_chance).items()
           if tier>0 and weight>0}
    total=sum(tiers.values())
    if total<=0:
        return []
    cd=max(1.0,crit_multiplier*float(critical_multiplier_factor))
    return [(weight/total, 1+tier*(cd-1)) for tier,weight in sorted(tiers.items())]


def location_crit_chance(
    stats: "ModdedStats", *, weakpoint: bool = False, crit_chance_add: float = 0.0
) -> float:
    """Crit chance one damage instance rolls at the body or a weak point.

    Same arithmetic as :func:`_apply_weakpoint_folding` and the Enervate hit
    model: body shots scale by ``WEAPON_CRIT_CHANCE_BODY_PART`` (TORSO), weak
    points add the weak-point crit bonuses, and a radial part strikes no body
    part.
    """
    cc=max(float(stats.crit_chance)+crit_chance_add,0.0)
    if stats.radial_only:
        return cc
    if weakpoint:
        return max(cc+stats.weakpoint_crit_chance_bonus
                   +stats.base_crit_chance*stats.weakpoint_crit_chance_relative,0.0)
    return cc*stats.bodyshot_crit_multiplier


def crit_proc_probabilities(
    stats: "ModdedStats",
    *,
    weakpoint: bool = False,
    forced_procs: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Per-instance probability of each crit-conditioned proc (Hunter Munitions).

    ``chance x P(crit tier >= 1)``, independent of status chance and damage
    weights. WFSim skips the roll when the weapon already forces that status
    (``pellet.rs`` ``slash_on_crit``), so a forced type yields nothing here.
    """
    chances=getattr(stats,'crit_proc_chances',None)  # absent on pre-channel pickles
    if not chances:
        return {}
    crit=min(location_crit_chance(stats,weakpoint=weakpoint),1.0)
    result={}
    for dtype,chance in chances.items():
        if stats.native_forced_procs.get(dtype) or (forced_procs or {}).get(dtype):
            continue
        p=min(max(float(chance),0.0),1.0)*crit
        if p>0:
            result[dtype]=p
    return result


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
    noncrit_chance = min(1.0, max(1.0 - crit_chance, 0.0))
    noncrit_bonus = max(noncrit_damage_multiplier - 1.0, 0.0)
    return crit + promotion + noncrit_chance * noncrit_bonus


# -- mod application ------------------------------------------------------------------


# Ground Arch-guns inherit the primary/secondary Arcane pools, not arbitrary
# weapon-specific or frame qualifiers.
ARCHGUN_ARCANE_TYPES = frozenset({
    "/Lotus/Weapons/Tenno/LotusLongGun",
    "/Lotus/Weapons/Tenno/Pistol/LotusPistol",
})


def archgun_arcane_type_applies(weapon, source_path, valid_type):
    return (
        weapon.get("slot") == "arch_gun"
        and str(source_path or "").startswith("/Lotus/Upgrades/CosmeticEnhancers/")
        and str(valid_type or "").rstrip("/") in ARCHGUN_ARCANE_TYPES
    )


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
    if (mode.get('behaviorKind') == 'auxiliary-melee'
            and weapon.get('slot') in ('primary','secondary','arch_gun')):
        raise ValueError(f"fire mode {fire_mode} is auxiliary melee, outside nonmelee scope")
    from .event_profiles import base_profile, co_profile
    event_profile = base_profile(weapon, fire_mode)
    gunco = co_profile(weapon,fire_mode)
    spool = event_profile.get('spool')
    if spool:
        damage = mode['damage']
        mode = {**mode, 'multishot':spool['maximum'],
                'ammoCost':math.ceil(spool['maximum']/spool['ammoDivisor']),
                'damage':{**damage,'types':{k:v*event_profile['playerDamageMultiplier']
                                          for k,v in damage['types'].items()}}}
        # Absolute raw minimum uses the same units as unscaled damage.
        if mode.get('falloffMinDamage') is not None:
            mode['falloffMinDamage'] *= event_profile['playerDamageMultiplier']
    base = (mode.get("damage") or {}).get("types")
    if base and mode.get('chargeDamageMultiplier'):
        base={k:v*mode['chargeDamageMultiplier'] for k,v in base.items()}
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
        if (effect.valid_type and effect.valid_type.rstrip("/") not in weapon_types
                and not archgun_arcane_type_applies(weapon, effect.source_path, effect.valid_type)):
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
    crit_proc_chances: dict[str, float] = {}
    slash_on_crit = _combine(0.0, buckets["WEAPON_SLASH_PROC_ON_CRIT_CHANCE"])
    if slash_on_crit > 0.0:
        crit_proc_chances["DT_SLASH"] = slash_on_crit
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
    # CO 类（Galvanized Aptitude 等对触发目标增伤）按 scenario.victim_status_count
    # 折算。窗口模型需要按「每步实际活层数」重算 CO —— 把 CO 分量单独记录，
    # windowed_status_damage 用它回退预乘再逐层重算（emergent 语义）。
    status_damage_effects = [
        _scale_effect(effect, scenario.victim_status_count)
        for effect in buckets["WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"]
    ]
    co_effects = list(buckets["WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE"])
    # ── ADD_BASE 语义分离（解算正确性修复）────────────────────────────
    # WEAPON_DAMAGE_AMOUNT 的 ADD_BASE（灵化进化「+N 基础伤害」类词条，
    # 如 PrimeVectisEvoTier1B 的 +150）语义是「往武器基伤上加 N 点平坦
    # 伤害」，随后再吃乘区；不是「基值 1 上的 +N×100% 乘数」。旧实现把
    # 它留在 _combine(1.0, ...) 里：(1+150)×mods → 150×151×2.551 =
    # 57,780（385× 膨胀），直接撑爆搜索候选面板与评分分母。
    # 正确口径：flat_base 先按类型份额摊入 base，再乘 damage_scale。
    damage_flat_base = 0.0
    damage_scale_effects = []
    for effect in buckets["WEAPON_DAMAGE_AMOUNT"]:
        if effect.operation == "ADD_BASE":
            damage_flat_base += effect.value
        else:
            damage_scale_effects.append(effect)
    compression_mult = 1.0
    compression_ammo = 0.0
    compression_profile = weapon.get('__compressionProfile__') or event_profile.get('compression')
    if buckets['RUNTIME_PRIMARY_COMPRESSION'] and scenario.aiming:
        if compression_profile:
            radius = float(compression_profile['radius'])
            if compression_profile.get('takesRadiusMods', True):
                radius = _combine(radius, buckets['WEAPON_EXPLOSION_RADIUS'])
            considered = compression_profile.get('reads_radius_m')
            if considered is None:
                considered = radius * float(compression_profile.get('effectiveness', 1.))
            lost = max(float(considered), 0.) * .8
            bonus = sum(e.value for e in buckets['RUNTIME_PRIMARY_COMPRESSION']) * lost
            compression_ammo = sum(e.runtime_chance or 0. for e in buckets['RUNTIME_PRIMARY_COMPRESSION']) * lost
            if compression_profile.get('stacking') == 'adds':
                damage_scale_effects.append(ModEffect('WEAPON_DAMAGE_AMOUNT','ADD',bonus))
            else:
                compression_mult += bonus
        else:
            unsupported.add('primary-compression-weapon-profile-unverified')
    ordinary_scale = _combine(1.0, damage_scale_effects)
    damage_scale = _combine(1.0, damage_scale_effects + status_damage_effects)
    if gunco and status_damage_effects:
        fraction = gunco['baseFraction']
        excluded_flat = sum(e.value for e in buckets['WEAPON_DAMAGE_AMOUNT'] if e.operation=='ADD_BASE'
                            and e.source_path in gunco['excludeFlatSources'])
        total = sum(base.values())+damage_flat_base
        fraction *= max(total-excluded_flat,0.)/total if total else 0.
        raw_co = _combine(1.,status_damage_effects)-1.
        damage_scale = ordinary_scale*(1.+raw_co*fraction) if gunco['behavior']=='independent' else ordinary_scale+raw_co*fraction
    # Multiplying Compression amplifies the ordinary bucket, not adding GunCO.
    damage_scale += ordinary_scale * (compression_mult - 1.0)
    victim_damage = _combine(1.,buckets['WEAPON_VICTIM_DAMAGE_AMOUNT'])-1.
    original_total = sum(base.values())
    co_fraction = gunco.get('baseFraction',1.)*original_total/max(original_total+damage_flat_base,1e-9)
    victim_low_health_multiplier = 1.
    if victim_damage:
        if gunco.get('behavior')=='independent':
            co_current = _combine(1.,status_damage_effects)
            victim_low_health_multiplier = 1.+victim_damage*co_fraction/max(co_current,1e-9)
        else:
            victim_low_health_multiplier = 1.+victim_damage*co_fraction/max(damage_scale,1e-9)
    if damage_flat_base:
        base_total_unscaled = sum(base.values())
        if base_total_unscaled > 0:
            # 按类型份额摊平（DT_ANY 词条对所有类型等比生效）。
            # 构造新 dict——base 是 mode.damage.types 的引用，不得原地改。
            scale_up = 1.0 + damage_flat_base / base_total_unscaled
            base = {dtype: amount * scale_up for dtype, amount in base.items()}
        # base_total_unscaled == 0（无基伤模式）：flat 无可加权的份额，
        # 维持原状并诊断（不虚构伤害类型）。
    if weapon.get("slot") in MELEE_SLOTS:
        damage_scale = _combine(
            damage_scale,
            buckets["WEAPON_MELEE_DAMAGE"],
            base_value=damage_scale,
        )

    scaled_base = {dtype: amount * damage_scale for dtype, amount in base.items()}
    base_total = sum(base.values())

    innate_entries, innate_candidates = _read_innate_elements(weapon)
    # Progenitor damage belongs to the base used by elemental mods and DoT
    # seeds, although its element joins after the ordered mod coalescing.
    elemental_base_total = base_total * (1.0 + sum(value for _, value in innate_entries))
    damage_types = _apply_elements(
        scaled_base,
        base_total=elemental_base_total * damage_scale,
        pre=buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED"],
        post=buckets["WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE"],
    )
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
    projectile_speed_multiplier = max(0.,_combine(1.,buckets['WEAPON_PROJECTILE_SPEED']))
    falloff_mode = mode
    if projectile_speed_multiplier!=1. and mode.get('falloffRange'):
        falloff_mode = {**mode,'falloffRange':[x*projectile_speed_multiplier for x in mode['falloffRange']]}
    falloff_multiplier = _falloff_multiplier(falloff_mode, base_total, scenario.distance)

    damage = mode["damage"]
    # Audited native profiles are consumed by manual_combat/replay. Their
    # exported component rows are no longer a missing-data warning; unknown
    # component weapons still fail closed in the compact panel path.
    from .event_profiles import base_profile
    event_profile = base_profile(weapon, fire_mode)
    has_replay_profile = bool(event_profile.get('radial') or event_profile.get('radials') or event_profile.get('lingering') or event_profile.get('pureRadial'))
    if damage.get("components") and not has_replay_profile:
        # Secondary explosions/stacking attacks need a hit timeline; the compact
        # evaluator intentionally scores only the exported primary hit.
        unsupported.add("projectile-component-damage-unapplied")
        skipped.append(
            f"{weapon.get('path') or weapon.get('name') or '?'}: "
            "unsupported[projectile-component-damage-unapplied]"
        )
    # ── 已知多部件武器的数据缺口标注（wiki 交叉核对清单）────────────────
    # Rabbit 2D 导出不含普通模式的 radial/field 部件数据（Bramma/Ogris/Lenz
    # 类武器有 components 字段走上面的诊断；Opticor/Torid 类连字段都没有）。
    # 这些武器的「最终伤害」缺 radial/field 部分（wfsim 实测 Opticor radial
    # 占 32%、Torid field 占 78%）——配装排序可用，绝对值偏低。按 wiki
    # 已证实的清单打标，前端与报告可见。
    if _KNOWN_MULTIPART_PATHS.get(str(weapon.get("path") or "")):
        part = _KNOWN_MULTIPART_PATHS[str(weapon.get("path") or "")]
        unsupported.add(f"weapon-radial-or-field-damage-not-in-export-{part}")
        skipped.append(
            f"{weapon.get('path') or weapon.get('name') or '?'}: "
            f"unsupported[radial-or-field-damage-not-in-export:{part}]"
        )
    # ── Shotgun procChance 导出口径还原（wfsim 对齐）────────────────────
    # DE 的导出里，多弹丸模式（霰弹枪）的 damage.procChance 是「每次射击的
    # 期望触发总数」（Hek 0.75 = 10.7% × 7 弹丸），而单弹丸武器的 procChance
    # 就是 per-pellet 几率。下游 expected_status_procs 按 per-pellet ×
    # multishot 计算，若不还原会把霰弹枪的触发期望放大 pellets 倍
    # （实测 Hek 5.25/shot，正确值 0.75/shot；wfsim wiki 口径 10.7%/弹丸）。
    innate_multishot = float(mode.get("multishot") or 1)
    exported_proc = float(damage.get("procChance", 0.0) or 0.0)
    if exported_proc == 0.0 and damage.get('source') == 'EmbedDeathAttack':
        exported_proc = event_profile.get('statusChanceFallback', exported_proc)
    if innate_multishot > 1.0 and exported_proc > 0.0:
        per_pellet_proc = exported_proc / innate_multishot
    else:
        per_pellet_proc = exported_proc
    from .manual_combat import reference
    profile = reference()['incarnon'].get(weapon.get('path')) if weapon.get('isIncarnonForm') else None
    base_magazine = float(weapon.get('magazineSize') or event_profile.get('magazine') or 0)
    magazine = _combine(base_magazine, buckets['WEAPON_CLIP_MAX'])
    # Ammo magazines hold whole rounds; fractional consumption below remains
    # fractional. Quantize to native f32 before truncating so e.g. 40 rounds
    # represented as 39.9999994 do not lose a round to Python precision.
    if base_magazine > 0 and not weapon.get('isIncarnonForm'):
        magazine = float(max(1, math.floor(_float32(magazine))))
    reload_base = mode.get('reloadTime') or 0.0
    if event_profile.get('reloadPerShell') is not None:
        reload_base = event_profile['reloadStart'] + event_profile['reloadPerShell'] * magazine + event_profile['reloadEnd']
    reload_time = _divide(_combine(reload_base,buckets['WEAPON_RELOAD_TIME']), buckets['WEAPON_RELOAD_SPEED'])
    battery = event_profile.get('battery')
    if battery:
        reload_time = _divide(battery['delayEmptySeconds'], buckets['WEAPON_RELOAD_SPEED']) + magazine / battery['regenPerSecond']
    if weapon.get('isIncarnonForm'):
        reload_time = 0.
        if profile and profile.get('pool'):
            magazine = float(profile['pool'])
            if scenario.incarnon_cycle:
                # Panel throughput only; replay schedules charging and both forms.
                reload_time = float(profile['enterSeconds']) + float(profile['exitSeconds'])
        elif scenario.incarnon_cycle:
            unsupported.add('incarnon-cycle-data-unavailable')
    damage = dict(damage)
    for conversion in buckets['RUNTIME_INCARNON_STAT_CONVERSION']:
        if conversion.runtime_kind == 'WEAPON_PROC_CHANCE':
            source_chance = _combine(per_pellet_proc, buckets['WEAPON_PROC_CHANCE'])
            bonus = min(conversion.runtime_threshold, max(0., source_chance) * conversion.value)
            damage['critChance'] = float(damage.get('critChance') or 0.) + bonus
        elif conversion.runtime_kind == 'WEAPON_CRIT_CHANCE':
            source_chance = _combine(damage.get('critChance', 0.), buckets['WEAPON_CRIT_CHANCE'])
            bonus = min(conversion.runtime_threshold, max(0., source_chance) * conversion.value)
            per_pellet_proc += bonus
    crit_chance = _combine(damage.get('critChance',0.),buckets['WEAPON_CRIT_CHANCE'])
    fire_rate=(mode.get('fireRate') or 0.) if buckets['RUNTIME_LOCK_FIRE_RATE'] else _combine(mode.get('fireRate') or 0.,buckets['WEAPON_FIRE_RATE'])
    charge_rate=max(1e-9,_combine(1.,buckets['WEAPON_CHARGE_RATE']))
    charge_fire_scale=1. if weapon.get('slot')=='arch_gun' else max(fire_rate/max(mode.get('fireRate') or 0.,1e-9),1e-9)
    charge_seconds=(event_profile.get('charge') or {}).get('seconds',0.)/(charge_fire_scale*charge_rate)
    bow_draw=event_profile.get('drawSeconds',0.)/(charge_fire_scale*charge_rate) if event_profile.get('bow') else None
    crit_flat, crit_relative = _split_crit_damage_bucket(buckets['WEAPON_CRIT_DAMAGE'])
    crit_base = damage.get('critMultiplier',1.)+sum(e.value for e in crit_flat)
    crit_multiplier = _combine(quantize_base_crit_damage(crit_base),crit_relative)
    anti_threshold = _combine(0.,buckets['WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX'])
    if anti_threshold>0 and scenario.victim_status_count<anti_threshold:
        crit_multiplier += _combine(0.,buckets['WEAPON_CRIT_UNDER_PROC_THRESHOLD_BONUS'])
    low_threshold = _combine(0.,buckets['WEAPON_LOW_CRIT_VALUE']) if buckets['WEAPON_LOW_CRIT_VALUE'] else None
    low_bonus = (_combine(quantize_base_crit_damage(_combine(crit_base,buckets['WEAPON_LOW_CRIT_DAMAGE'])),crit_relative)
                 -_combine(quantize_base_crit_damage(crit_base),crit_relative)) if low_threshold is not None else 0.
    multishot = innate_multishot if buckets['RUNTIME_LOCK_MULTISHOT'] else max(0.0, _combine(innate_multishot,buckets['WEAPON_FIRE_ITERATIONS']))
    from .beam_ramp import is_furis_beam
    continuous = mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerContinous' or is_furis_beam(weapon,mode,fire_mode)
    pool_cost = 0.
    pool_bonus = buckets['WEAPON_AMMO_POOL_MULTISHOT_DAMAGE']
    pool_multiplier = 1.
    if pool_bonus:
        source_base = sum(base.values())
        pool_multiplier = _combine(source_base,pool_bonus)/source_base if source_base else 1.
    if pool_bonus and multishot>1.:
        pool_cost = multishot-1.
        amplified = 1.+(multishot-1.)*pool_multiplier
        if continuous:
            multishot = amplified
        else:
            factor = amplified/multishot
            damage_types = {k:v*factor for k,v in damage_types.items()}
            compression_mult *= factor
    dot_basis = elemental_base_total * _combine(1.0, damage_scale_effects) * compression_mult
    dot_elements = _dot_elemental_multipliers(buckets['WEAPON_PERCENT_BASE_DAMAGE_ADDED'],
                                            buckets['WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE'])
    weapon_crit_chance = crit_chance
    shield_crit_damage_multiplier = 1.
    passes = scenario.combat_state.get('orbPasses',0)
    radial_only = damage.get('source') in ('ExplosiveAttack','RadialDamage','EmbedDeathAttack','StackingAttack')
    if passes and not radial_only and weapon.get('slot') not in MELEE_SLOTS:
        # ShieldInfo is applied after weapon element coalescing. SetCount uses
        # newCount/maxCount for merged orbs; an untouched orb keeps its minimum.
        # The collision list grants critical damage only for its first entry.
        stacks = scenario.combat_state.get('orbStacks',1)
        electric = 1. if stacks==1 else 1.+4.*stacks/3.
        special = scenario.combat_state.get('orbSpecialShield',False)
        shields = passes*(2 if special else 1)
        atten = .66**shields
        electric_bonus = passes*electric
        damage_types = dict(damage_types)
        damage_types['DT_ELECTRICITY'] = damage_types.get('DT_ELECTRICITY',0.)+elemental_base_total*damage_scale*electric_bonus
        if special:
            damage_types['DT_RADIATION'] = damage_types.get('DT_RADIATION',0.)+elemental_base_total*damage_scale*2.*passes
        damage_types = {k:v*atten for k,v in damage_types.items()}
        dot_basis *= atten
        dot_elements['DT_ELECTRICITY'] = dot_elements.get('DT_ELECTRICITY',1.)+electric_bonus
        crit_chance += .25*shields
        crit_multiplier *= 1.25
        low_bonus *= 1.25
        shield_crit_damage_multiplier = 1.25
    return ModdedStats(
        damage_types=damage_types,
        crit_chance=crit_chance,
        # 基础暴伤量化（wfsim §5）：flat CD 先加进基础值 → 量化到 32/4095
        # 步长 → 相对 CD（%）后乘。旧的 _combine 单序列在 flat+relative 混合
        # 时会以错误顺序合并（flat 落在量化之外或之内不定）。
        crit_multiplier=crit_multiplier+(low_bonus if low_threshold is not None and crit_chance<low_threshold else 0.),
        low_crit_threshold=low_threshold,
        low_crit_damage_base=crit_multiplier if low_threshold is not None else None,
        low_crit_damage_bonus=low_bonus,
        ammo_pool_multishot_cost=pool_cost,
        ammo_pool_damage_bonus=pool_multiplier-1. if pool_bonus else 0.,
        victim_full_crit_chance=_combine(damage.get('critChance',0.),[*buckets['WEAPON_CRIT_CHANCE'],
            *[replace(e,upgrade_type='WEAPON_CRIT_CHANCE') for e in buckets['WEAPON_VICTIM_CRIT_CHANCE']]])-weapon_crit_chance,
        victim_full_crit_damage=(_combine(quantize_base_crit_damage(crit_base+sum(e.value for e in buckets['WEAPON_VICTIM_CRIT_DAMAGE'])),crit_relative)
            -_combine(quantize_base_crit_damage(crit_base),crit_relative))*shield_crit_damage_multiplier,
        victim_low_health_multiplier=victim_low_health_multiplier,
        projectile_speed_multiplier=projectile_speed_multiplier,
        charge_rate_multiplier=charge_rate,
        charge_seconds=charge_seconds,
        bow_draw_seconds=bow_draw,
        explosion_radius_multiplier=_combine(1.0, buckets['WEAPON_EXPLOSION_RADIUS']),
        incarnon_charge_multiplier=max(0.0, _combine(1.0, buckets['WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER'])),
        radial_only=radial_only,
        native_forced_procs={dtype: float((damage.get('forcedProcs') or []).count(proc))
            for proc, dtype in [('PT_KNOCKBACK','DT_IMPACT'),('PT_FRAILTY','DT_PUNCTURE'),('PT_BLEEDING','DT_SLASH'),
                ('PT_IMMOLATION','DT_FIRE'),('PT_CHILLED','DT_FREEZE'),('PT_ELECTROCUTION','DT_ELECTRICITY'),
                ('PT_POISONED','DT_POISON'),('PT_FLASHBANG','DT_EXPLOSION'),('PT_RAD_TOX','DT_RADIATION'),
                ('PT_ASPHYXIATION','DT_GAS'),('PT_MAGNETIZED','DT_MAGNETIC'),('PT_INFECTED','DT_VIRAL'),('PT_CAUSTIC_BURN','DT_CORROSIVE')]
            if proc in (damage.get('forcedProcs') or ())},
        continuous=continuous,
        status_chance=_combine(per_pellet_proc, buckets["WEAPON_PROC_CHANCE"]),
        multishot=multishot,
        fire_rate=fire_rate,
        magazine=magazine,
        # 装填时长在上方按灵化口径预计算（reload_time 局部变量）。
        reload_time=reload_time,
        # The compact weapon export does not yet carry native spread, recoil or
        # reserve-ammo bases.  These fields therefore expose the exact relative
        # transform rather than fabricating an absolute stat.
        spread_multiplier=_combine(1.0, buckets["WEAPON_SPREAD"]),
        recoil_multiplier=_combine(1.0, buckets["WEAPON_RECOIL"]),
        ammo_max_multiplier=_combine(1.0, buckets["WEAPON_AMMO_MAX"]),
        # 每扳机弹药消耗（Twin Grakatas 类）：sustained_attack_rate 折算用。
        ammo_cost=max(0.0, _combine(float(mode.get("ammoCost") or 1), buckets["WEAPON_AMMO_CONSUME_RATE"])) * max(0.0, 1.0 - compression_ammo),
        headshot_bonus_multiplier=_combine(
            1.0, buckets["WEAPON_HEADSHOT_MULTIPLIER"]
        ),
        proc_damage_multiplier=_combine(1.0, buckets["WEAPON_PROC_DAMAGE"]),
        proc_duration_multiplier=_combine(1.0, buckets["WEAPON_PROC_TIME"]),
        status_condition_damage_multiplier=_combine(1.0, status_damage_effects),
        # CO（对触发目标增伤）原始效果列表与预乘时的假定层数：窗口模型
        # （windowed_status_damage）用它把 CO 从 damage_types 中剥离，按每步
        # 实际活异常类型数重算（emergent 语义，wfsim M27：高级靶杀不动的
        # 时候镀层 CO 接近无效）。
        co_bucket=list(co_effects),
        co_assumed_count=float(scenario.victim_status_count or 0),
        initial_combo=_combine(0.0, buckets["WEAPON_MELEE_COMBO_INITIAL_BONUS"]),
        combo_duration=_combine(
            BASE_MELEE_COMBO_DURATION if weapon.get("slot") in MELEE_SLOTS else 0.0,
            buckets["WEAPON_MELEE_COMBO_DURATION_BONUS"],
        ),
        heavy_attack_efficiency=_combine(
            0.0, buckets["WEAPON_MELEE_COMBO_USAGE_EFFICIENCY"]
        ),
        faction_damage_multipliers=faction_damage_multipliers,
        noncrit_damage_multiplier=1.0 + max(0.0, _combine(1.0, buckets["WEAPON_NOCRIT_DAMAGE"]) - 1.0) * (
            min(1.0, max(0.0, _combine(0.0, buckets['WEAPON_NOCRIT_CHANCE'])))
            if buckets['WEAPON_NOCRIT_CHANCE'] else 1.0
        ),
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
        # ── 弱点家族词条（2026.09.22 融合新词条，引擎乘区已裁决）─────
        # WEAPON_DAMAGE_WEAKPOINT：STACKING_MULTIPLY 口径（×(1+bonus)），
        # 与部位倍率独立的条件乘区；面板存原始值，弱命中期望折算在
        # average_hit/damage_against 按 headshot_chance 权重进行。
        weakpoint_damage_bonus=max(
            _combine(1.0, buckets["WEAPON_DAMAGE_WEAKPOINT"]) - 1.0,
            0.0,
        ),
        # WEAPON_CRIT_CHANCE_WEAKPOINT：与基础暴击加算（引擎 fn
        # 0x1406dc47e 同链）。STACKING_MULTIPLY 卡（Primary Acuity
        # ×0.318/级）从 1 累乘再减回 1；ADD 卡直接累加。
        weakpoint_crit_chance_bonus=sum(e.value for e in buckets['WEAPON_CRIT_CHANCE_WEAKPOINT'] if e.operation == 'ADD'),
        weakpoint_crit_chance_relative=sum(e.value for e in buckets['WEAPON_CRIT_CHANCE_WEAKPOINT'] if e.operation == 'STACKING_MULTIPLY')
            + sum(e.value for e in buckets['WEAPON_CRIT_CHANCE_BODY_PART'] if e.symbol_filter=='HEAD' and e.operation=='STACKING_MULTIPLY'),
        bodyshot_crit_multiplier=_combine(1.,[e for e in buckets['WEAPON_CRIT_CHANCE_BODY_PART'] if e.symbol_filter=='TORSO']),
        base_crit_chance=_combine(damage.get('critChance', 0.0), [e for e in buckets['WEAPON_CRIT_CHANCE'] if e.operation in ('ADD_BASE', 'SET_BASE')]),
        falloff_multiplier=falloff_multiplier,
        dot_base_damage=dot_basis,
        dot_elemental_multipliers=dot_elements,
        impact_proc_conversions=impact_proc_conversions,
        independent_proc_chances=independent_proc_chances,
        crit_proc_chances=crit_proc_chances,
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
    victim_gate = (effect.upgrade_type in {'WEAPON_VICTIM_CRIT_CHANCE','WEAPON_VICTIM_CRIT_DAMAGE'}
                   and effect.symbol_filter=='VictimFullHealthShield') or (
                   effect.upgrade_type=='WEAPON_VICTIM_DAMAGE_AMOUNT' and effect.symbol_filter=='VictimLessThanHalfHealth')
    bodypart_gate=(effect.upgrade_type=='WEAPON_CRIT_CHANCE_BODY_PART'
                   and effect.symbol_filter in {'TORSO','HEAD','ARM_LEFT','ARM_RIGHT','LEG_LEFT','LEG_RIGHT'})
    if effect.symbol_filter and effect.upgrade_type != "GAMEPLAY_FACTION_DAMAGE" and not victim_gate and not bodypart_gate:
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
        key = effect.upgrade_type
        grouped.setdefault(key, []).append(effect)

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

    Heat, Toxin and Electricity use their own installed elemental bonus. Gas
    accepts only an explicit Gas bonus: component Heat/Toxin mods change its
    direct damage weight, not its status payload. Slash has no elemental bonus.
    """
    typed: dict[str, list[ModEffect]] = {}
    for effect in (*pre, *post):
        if effect.damage_type in {"DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS"}:
            typed.setdefault(effect.damage_type, []).append(effect)

    heat = max(_combine(1.0, typed.get("DT_FIRE", [])), 0.0)
    toxin = max(_combine(1.0, typed.get("DT_POISON", [])), 0.0)
    electricity = max(_combine(1.0, typed.get("DT_ELECTRICITY", [])), 0.0)
    return {
        "DT_SLASH": 1.0,
        "DT_FIRE": heat,
        "DT_POISON": toxin,
        "DT_ELECTRICITY": electricity,
        "DT_GAS": max(_combine(1.0, typed.get("DT_GAS", [])), 0.0),
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
    # f64 全程计算，仅在最外层套一次 f32：级差 (level-1)**0.9 与 260× 的中间
    # f32 截断在 9999 级会偏 1.3%（2^20 网格吸附），wfsim 的参照值
    # （1034893.327 @9999）与 f64 精确值逐位一致，证明引擎侧不逐项 f32。
    f1 = 1.0 + 0.0015 * (level - 1.0) ** 4.0
    f2 = 1.0 + 260.0 * (level - 1.0) ** 0.9
    if level <= 45.0:
        return f1
    if level >= 50.0:
        return f2
    # 45-50 之间的 smoothstep 过渡带：两个分支量级尚可（≤~8635），插值安全。
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
        # 天生超宏（Thrax 家族 15 基础等，wiki Module:Enemies/data）：应用与
        # Eximus 相同的绝对等级曲线缩放（wfsim 实测对齐：15 × mult(9999) =
        # 15,523,399.9）。基础值 0 但带 hasOverguard 标记的保持旧行为
        # （数据缺失 → unsupported）。
        overguard = float(overguard) * _overguard_level_multiplier(
            float(level if level is not None else base_level if base_level is not None else 1.0)
        )
    else:
        overguard = 0.0
    if standard_eximus:
        overguard = max(overguard, 12.0 * _overguard_level_multiplier(enhancement_level))
    elif target.get("hasOverguard") and overguard <= 0.0:
        # 基础超宏缺失（数据没有具体数值）才标注 unsupported；已缩放的
        # 天生超宏（overguard > 0）不再是缺口。
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


def quantize_damage_vector(
    damage_types: Mapping[str, float], modded_base: float
) -> dict[str, float]:
    """Per-hit damage-type quantization (wfsim MEASUREMENTS M57, AGPL-3.0).

    The game serializes a hit as one integer total plus per-type 1/32
    multiples: each type value snaps to ``round(v / (ModdedBase/32))`` units
    of ``ModdedBase/32``.  THE DENOMINATOR IS ``ModdedBase`` — the base
    damage scaled by base-damage mods, elemental portions EXCLUDED — not the
    vector's own total: a non-elemental bonus scales numerator and
    denominator alike and cancels, an elemental one does not (M57: Braton
    Prime base 35 + Gas 63 snaps to 58 units of 35, giving 101.06→98 in the
    measured example when the wrong denominator is used).

    Applied BEFORE crit/type-modifier/faction multipliers — those multiply
    the quantized values (wfsim docs/MECHANICS.md §5 Quantization).
    """
    modded_base = float(modded_base)
    if modded_base <= 0.0:
        return {k: float(v) for k, v in damage_types.items()}
    unit = modded_base / 32.0
    result: dict[str, float] = {}
    for dtype, amount in damage_types.items():
        value = float(amount)
        result[dtype] = round(value / unit) * unit if unit > 0.0 else value
    return result


def quantize_base_crit_damage(cd: float) -> float:
    """Base crit-damage quantization (wfsim MECHANICS §5 Quantization, AGPL-3.0).

    ``quantized_base_cd = round(base_cd × 4095/32) × 32/4095`` — the game
    serializes the base crit multiplier in steps of 32/4095.  FLAT/absolute
    CD bonuses (Incarnon "Critical Parallel" +0.4) must add into the base
    BEFORE quantization; RELATIVE (%) mods (Vital Sense) multiply AFTER.
    """
    step = 32.0 / 4095.0
    return round(float(cd) / step) * step


# 临界：flat CD（ADD/ADD_BASE 操作）与相对 CD（STACKING_MULTIPLY/MULTIPLY）
# 必须在量化前后分层——wfsim §5：「flat/absolute CD bonuses add into base_cd
# BEFORE quantization; relative (%) mods multiply AFTER」。_combine 把两类
# 操作混进一个序列，所以这里先拆桶再按顺序合成。
def _split_crit_damage_bucket(
    effects: Sequence[ModEffect],
) -> tuple[list[ModEffect], list[ModEffect]]:
    flat: list[ModEffect] = []
    relative: list[ModEffect] = []
    for effect in effects:
        if effect.operation in ("ADD", "ADD_BASE"):
            flat.append(effect)
        else:
            relative.append(effect)
    return flat, relative


def damage_against_cached_armour(
    stats: ModdedStats,
    live_armour: float,
    defenses_snapshot: Mapping[str, Any],
    *,
    level: int | None = None,
    steel_path: bool = False,
    enemy_enhancements: Mapping[str, Any] | None = None,
    hit_location: str | None = None,
    target: Mapping[str, Any] | None = None,
    _target_cache: dict[str, Any] | None = None,
    crit_chance_add: float = 0.0,
    crit_multiplier_add: float = 0.0,
) -> dict[str, Any]:
    """Fast-path damage_against with a pre-computed defenses snapshot.

    In the windowed model's step loop the only per-step variable is the LIVE
    armour (corrosive/heat strip); health/shield/overguard/magnetic/eximus
    are constant across the window.  This variant skips the full
    ``enemy_defenses`` re-resolution (606k calls → 1) by accepting the
    pre-computed snapshot and just overriding the armour field.
    ``_target_cache`` optionally carries the target-derived constants
    (hit_multiplier / faction_deltas / bypass sets) so repeated calls for
    the same target skip that resolution too.
    ``crit_chance_add`` / ``crit_multiplier_add`` apply the cold/puncture
    per-step crit adjustments WITHOUT rebuilding the stats dataclass (the
    step loop calls this thousands of times per evaluation).
    """
    target = target if isinstance(target, Mapping) else {}
    magnetic_stacks = int(defenses_snapshot.get("magneticStacks") or 0)
    overguard = float(defenses_snapshot.get("overguard") or 0.0)
    if _target_cache is not None:
        hit_multiplier = _target_cache["hit_multiplier"]
        hit_critical_multiplier = _target_cache["hit_critical_multiplier"]
        faction_deltas = _target_cache["faction_deltas"]
        armour_bypass = _target_cache["armour_bypass"]
        shield_bypass = _target_cache["shield_bypass"]
        target_faction = _target_cache["target_faction"]
    else:
        location, hit_multiplier, hit_critical_multiplier, hit_unsupported, hit_metadata = _hit_location_info(
            target, "body" if stats.radial_only else hit_location
        )
        faction_deltas = _faction_damage_deltas(target)
        armour_bypass = _damage_type_set(
            target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
        )
        shield_bypass = _damage_type_set(
            target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
        )
        target_faction = str(target.get("faction") or "")

    if stats.radial_only:
        hit_multiplier = hit_critical_multiplier = 1.0

    quantized_types = quantize_damage_vector(
        stats.damage_types,
        stats.dot_base_damage
        if stats.dot_base_damage is not None
        else sum(stats.damage_types.values()),
    )

    per_type: dict[str, float] = {}
    shield_value = float(defenses_snapshot.get("shield") or 0.0)
    for dtype, amount in quantized_types.items():
        if overguard > 0.0:
            value = _overguard_damage_multiplier(dtype, magnetic_stacks)
        else:
            value = _target_damage_multiplier(
                dtype,
                target,
                armour=live_armour,
                faction_deltas=faction_deltas,
                armour_bypass=armour_bypass,
                shield_bypass=shield_bypass,
            )
            if shield_value > 0.0 and dtype not in shield_bypass:
                value *= _magnetic_defense_multiplier(magnetic_stacks)
        value *= amount
        per_type[dtype] = value * stats.falloff_multiplier

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
        max(stats.crit_chance + crit_chance_add, 0.0) if crit_chance_add else stats.crit_chance,
        max(stats.crit_multiplier + crit_multiplier_add, 1.0) if crit_multiplier_add else stats.crit_multiplier,
        stats.noncrit_damage_multiplier,
        hit_critical_multiplier,
        double_crit_chance=stats.double_crit_chance,
    )
    raw = _apply_weakpoint_folding(
        raw, stats, hit_multiplier, hit_critical_multiplier,
        crit_chance_add=crit_chance_add, crit_multiplier_add=crit_multiplier_add,
    )
    return {
        "health": float(defenses_snapshot.get("health") or 0.0),
        "shield": shield_value,
        "armour": live_armour,
        "armourReduction": _armour_reduction(live_armour) if live_armour else 0.0,
        "overguard": overguard,
        "perType": per_type,
        "perHit": raw,
        "perShot": raw * max(stats.multishot, 0.0),
        "dps": raw * max(stats.multishot, 0.0) * stats.sustained_attack_rate,
    }


def _is_weakpoint_hit(stats: "ModdedStats", hit_multiplier: float) -> bool:
    return not stats.radial_only and hit_multiplier > 1.0 + 1e-9


def _weakpoint_noncrit_scale(stats: "ModdedStats", hit_multiplier: float) -> float:
    """Weak-point factors that do not depend on the crit roll."""
    if not _is_weakpoint_hit(stats, hit_multiplier):
        return 1.0
    scale = 1.0
    if getattr(stats, "weakpoint_damage_bonus", 0.0) > 0.0:
        scale *= (hit_multiplier + 1.5 * float(stats.weakpoint_damage_bonus)) / hit_multiplier
    return scale * stats.headshot_bonus_multiplier


def _apply_weakpoint_folding(
    raw: float,
    stats: "ModdedStats",
    hit_multiplier: float,
    hit_critical_multiplier: float,
    *,
    crit_chance_add: float = 0.0,
    crit_multiplier_add: float = 0.0,
) -> float:
    # WFSim 69e6a139 MECHANICS weak-point bracket. Prior disassembly only
    # established the gate, not the arithmetic (its openQuestions say so).
    if stats.radial_only:
        return raw
    if not _is_weakpoint_hit(stats, hit_multiplier):
        if stats.bodyshot_crit_multiplier!=1.:
            cc=max(stats.crit_chance+crit_chance_add,0.)
            cd=max(stats.crit_multiplier+crit_multiplier_add,1.)
            original=effective_hit_multiplier(cc,cd,stats.noncrit_damage_multiplier,
                hit_critical_multiplier,double_crit_chance=stats.double_crit_chance)
            modified=effective_hit_multiplier(cc*stats.bodyshot_crit_multiplier,cd,stats.noncrit_damage_multiplier,
                hit_critical_multiplier,double_crit_chance=stats.double_crit_chance)
            raw*=modified/original if original else 1.
        return raw
    raw *= _weakpoint_noncrit_scale(stats, hit_multiplier)
    weak_crit = stats.weakpoint_crit_chance_bonus + stats.base_crit_chance * stats.weakpoint_crit_chance_relative
    if weak_crit != 0.0:
        base_cc = (
            max(stats.crit_chance + crit_chance_add, 0.0)
            if crit_chance_add
            else stats.crit_chance
        )
        base_cd = (
            max(stats.crit_multiplier + crit_multiplier_add, 1.0)
            if crit_multiplier_add
            else stats.crit_multiplier
        )
        base_crit = effective_hit_multiplier(
            base_cc, base_cd, stats.noncrit_damage_multiplier,
            hit_critical_multiplier, double_crit_chance=stats.double_crit_chance,
        )
        boosted_crit = effective_hit_multiplier(
            max(base_cc + weak_crit, 0.0),
            base_cd, stats.noncrit_damage_multiplier,
            hit_critical_multiplier, double_crit_chance=stats.double_crit_chance,
        )
        if base_crit > 0.0:
            raw *= 1.0 + (boosted_crit / base_crit - 1.0)
    return raw


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
        target, "body" if stats.radial_only else hit_location
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

    # Per-hit quantization BEFORE crit/type/faction multipliers (M57): the
    # denominator is ModdedBase (IPS-only scaled base — dot_base_damage), the
    # elemental additions live only in the numerator.  A pure-IPS vector on a
    # 1×-of-base grid snaps back to itself, so unmodded and single-bucket
    # builds are unchanged; only mixed elemental compositions move, by ≤1/32
    # of ModdedBase per type.
    quantized_types = quantize_damage_vector(
        stats.damage_types,
        stats.dot_base_damage
        if stats.dot_base_damage is not None
        else sum(stats.damage_types.values()),
    )

    per_type: dict[str, float] = {}
    for dtype, amount in quantized_types.items():
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
    raw = _apply_weakpoint_folding(
        raw, stats, hit_multiplier, hit_critical_multiplier
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
        target, "body" if stats.radial_only else hit_location
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
    weakpoint: bool = False,
) -> dict[str, float]:
    """Return expected status-proc counts for one attack.

    Random procs are ``status_chance * multishot`` and are distributed by the final
    damage-type weights.  ``forced_procs`` is intentionally an explicit mapping of
    output damage type to expected count; only the small explicitly verified native ``PT_*`` mapping is read
    from weapon metadata.  This keeps forced effects such as custom Lua
    attacks fail-closed until their mapping is verified.

    ``weakpoint`` selects the crit chance that crit-conditioned procs (Hunter
    Munitions) roll at; the default is a body shot.
    """
    chance = max(float(stats.status_chance), 0.0)
    shots = max(float(stats.multishot), 0.0)
    random_total = chance * shots
    if stats.continuous:
        shots = 1.0 if shots > 0 else 0.0
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

    # PT_ELECTROCUTION is verified by the native electric-proc adapter and raw
    # attack ForcedProcs. A zero status chance does not suppress this event.
    for dtype, per_projectile in stats.native_forced_procs.items():
        result[dtype] = result.get(dtype, 0.0) + shots * _require_nonnegative_finite(
            f'native_forced_procs[{dtype!r}]', per_projectile)

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

    # Hunter Munitions: each damaging instance that crits rolls its own proc.
    for dtype, probability in crit_proc_probabilities(
        stats, weakpoint=weakpoint, forced_procs=forced_procs
    ).items():
        result[dtype] = result.get(dtype, 0.0) + shots * probability

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


def _proc_seed_merge_multiplier(stats, dtype, forced_procs=None):
    if not stats.continuous or stats.multishot <= 0:
        return 1.0
    # Conditional seed moment: E[M^2]/E[M] for natural status rolls,
    # E[M] for an independent proc on the single merged beam hit.
    from dataclasses import replace
    low = int(math.floor(stats.multishot))
    fraction = stats.multishot - low
    count = seed = 0.0
    for merged, probability in ((low, 1 - fraction), (low + 1, fraction)):
        if merged <= 0 or probability <= 0:
            continue
        probe = replace(stats, continuous=False, multishot=1.0,
                        status_chance=stats.status_chance * merged,
                        crit_proc_chances={})
        n = expected_status_procs(probe, forced_procs=forced_procs).get(dtype, 0.0)
        count += probability * n
        seed += probability * n * merged
    return seed / count if count else 1.0


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
        target, "body" if stats.radial_only else hit_location
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
    weakpoint = _is_weakpoint_hit(stats, hit_multiplier)
    procs = expected_status_procs(stats, forced_procs=forced_procs, weakpoint=weakpoint)
    # Crit-conditioned procs share their type's row but seed from a crit.
    crit_shots = (1.0 if stats.multishot > 0 else 0.0) if stats.continuous else max(float(stats.multishot), 0.0)
    crit_counts = {
        dtype: crit_shots * probability
        for dtype, probability in crit_proc_probabilities(
            stats, weakpoint=weakpoint, forced_procs=forced_procs
        ).items()
    }
    dot_base = (
        stats.dot_base_damage
        if stats.dot_base_damage is not None
        else stats.total_damage
    )
    dot_base = max(float(dot_base), 0.0)
    duration = DOT_BASE_DURATION_SECONDS * max(float(stats.proc_duration_multiplier), 0.0)
    # ── Per-proc DoT seeds by crit tier (wfsim MECHANICS §6, AGPL-3.0)─────
    # A proc's tick reads the damage snapshot of the hit that CAUSED it —
    # that hit's crit tier included — not the panel's crit-averaged damage.
    # The tier decomposition below reproduces the same average as the old
    # single `crit` factor (pinned by crit_tier_seed_distribution tests), but
    # each tier group keeps its own seed so downstream per-tick amplifiers
    # (live armour strip, viral ramp) see a real distribution instead of an
    # average.  In the linear closed-form path the two agree exactly; the
    # split matters for the stepped windowed model and future per-tick reads.
    seed_tiers = crit_tier_seed_distribution(
        stats.crit_chance,
        stats.crit_multiplier,
        stats.noncrit_damage_multiplier,
        hit_critical_multiplier,
        double_crit_chance=stats.double_crit_chance,
    )
    weak_seed_scale = _apply_weakpoint_folding(1.0, stats, hit_multiplier, hit_critical_multiplier)
    # A crit-only proc rolls at the location's own crit chance, so its tiers
    # already carry the body/weak-point crit bonuses; only the non-crit
    # weak-point factors still apply. A merged beam instance seeds at E[M].
    crit_seed_tiers = critical_tier_seed_distribution(
        location_crit_chance(stats, weakpoint=weakpoint),
        stats.crit_multiplier,
        hit_critical_multiplier,
        double_crit_chance=stats.double_crit_chance,
    ) if crit_counts else []
    crit_location_scale = _weakpoint_noncrit_scale(stats, hit_multiplier)
    crit_merge = max(float(stats.multishot), 0.0) if stats.continuous else 1.0
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
        # Status payload reads weapon modified base, never the Slash share.
        # Physical-type and elemental mods do not amplify Bleed; GunCO is
        # excluded when apply_mods creates dot_base_damage above.
        seed_basis = dot_base
        elemental_factor = (1.0 if dtype in ('DT_SLASH', 'DT_IMPACT', 'DT_PUNCTURE')
                            else max(float(elemental), 0.0))
        # +1 accumulator per tick group (wfsim MEASUREMENTS M58, AGPL-3.0):
        # Heat/Electricity/Gas consolidate into ONE tick group sharing a single
        # +1; Slash and Toxin tick independently so every live stack carries
        # its own.  The +1 scales with the elemental/proc-damage multipliers
        # (it rides the M bracket of the tick formula) but not with crit/base.
        shared_group = dtype in {"DT_FIRE", "DT_ELECTRICITY", "DT_GAS"}
        accumulator = 1.0 if shared_group else min(count, 10.0)
        accumulator_multiplier = max(float(elemental), 0.0) * proc_damage
        # Per-tier seed: each tier's procs tick at their own seed factor.
        # The M58 +1 accumulator rides M (elemental/proc-damage), not the
        # seed, so it is added once per tick group at the averaged tier only
        # in the closed-form path (the stepped model re-derives it per step).
        seed_scale = (
            coefficient
            * seed_basis
            * elemental_factor
            * proc_damage
            * stats.falloff_multiplier
            * hit_multiplier
            * target_multiplier
            * max(float(faction_mod), 0.0) ** 2
        )
        crit_share = min(crit_counts.get(dtype, 0.0) / count, 1.0)
        natural_share = 1.0 - crit_share
        per_second_by_tier = []
        crit_by_tier = []
        if natural_share > 1e-12:
            natural_scale = (
                seed_scale
                * _proc_seed_merge_multiplier(stats, dtype, forced_procs)
                * weak_seed_scale
            )
            for weight, factor in seed_tiers:
                per_second_by_tier.append((natural_share * weight, natural_scale * factor))
                crit_by_tier.append((natural_share * weight, factor))
        if crit_share > 0.0:
            for weight, factor in crit_seed_tiers:
                per_second_by_tier.append(
                    (crit_share * weight, seed_scale * crit_merge * crit_location_scale * factor)
                )
                crit_by_tier.append((crit_share * weight, factor))
        crit = sum(weight * factor for weight, factor in crit_by_tier)
        seed_per_second_no_acc = sum(weight * ps for weight, ps in per_second_by_tier)
        per_second = seed_per_second_no_acc + (accumulator * accumulator_multiplier)
        damage = per_second * duration
        expected = damage * count
        breakdown[dtype] = {
            "expectedProcs": count,
            "coefficient": coefficient,
            "durationSeconds": duration,
            "elementalMultiplier": max(float(elemental), 0.0),
            "critMultiplier": crit,
            # 种子分层明细（供步进模型按 tier 重算 per-tick 放大器）：
            # [(weight, per_second_excl_accumulator)] per crit tier。
            "seedTiers": [
                {"weight": weight, "perSecond": ps} for weight, ps in per_second_by_tier
            ],
            "targetMultiplier": target_multiplier,
            "perSecond": per_second,
            # ── F02/F03（审计修复）显式合同字段 ─────────────────────────
            # 生产者在此一次性声明「单次 proc 的每秒种子伤害」与「+1 累加项
            # 的每秒伤害」，消费端（windowed_status_damage）不再从已聚合的
            # perSecond 反推。注意量纲合同：
            #   seedPerSecondPerProc —— 每个 proc 的每秒种子伤害（不含 +1）。
            #     per_second_by_tier 本身就是 per-proc 口径（不含 count），
            #     这里直接透传，不再除以触发数。
            #   accumulatorPerSecondPerAttack —— 一次攻击产生的全部 +1 累加项
            #     的合计每秒伤害（共享 tick group = 1 份；独立 = 每期望 proc
            #     一份，accumulator 变量已按 count 计）。
            #   durationSeconds 已经是「基础时长 × proc_duration_multiplier」
            #     的最终值（F03：消费端不得再乘一次）。
            "seedPerSecondPerProc": seed_per_second_no_acc,
            "accumulatorPerSecondPerAttack": accumulator * accumulator_multiplier,
            "accumulatorSharedGroup": shared_group,
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
        ) = _hit_location_info(target, "body" if stats.radial_only else hit_location)
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
            * _proc_seed_merge_multiplier(stats, 'DT_EXPLOSION', forced_procs)
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


def _windowed_average_stacks(
    rate_per_second: float, duration: float, cap: float, window: float
) -> float:
    """Time-averaged live stack count over a window starting from zero stacks.

    Stacks accumulate at ``rate_per_second`` and each application lives for
    ``duration`` seconds (steady-state count = rate * duration, capped).  From
    zero the count ramps linearly until it reaches that steady level at
    t_settle = duration (or the window ends first).  The time-average is the
    closed-form integral of that ramp — no per-step simulation needed.
    """
    steady = min(max(rate_per_second * duration, 0.0), cap)
    if steady <= 0.0 or window <= 0.0:
        return 0.0
    t_settle = min(duration, window)
    if t_settle >= window:
        # Never reached steady state inside the window: average of a linear ramp.
        return steady * (window / (2.0 * duration))
    # Ramp for t_settle seconds then hold steady for the remainder.
    ramp_integral = steady * t_settle / 2.0
    return (ramp_integral + steady * (window - t_settle)) / window


def _gas_single_target_dps(
    row: Mapping[str, Any],
    proc_rate: float,
    damage_rate_multiplier: float,
    status_rate_multiplier: float,
) -> float:
    """Single-target Gas cloud contribution per proc-second.

    Gas (Status_Effect / wfsim MECHANICS §6) is a 10-slot cloud on the target:
    procs feed cloud *stacks*, and against a lone target only the cloud's own
    tick counts — not one full expected-proc payload per pellet.  Mirrors the
    steady-state model's Gas handling (active cloud stacks capped at 10, hit
    multiplier averaged by the damage/status rate ratio).
    """
    expected_procs = max(float(row.get("expectedProcs") or 0.0), 0.0)
    per_second = max(float(row.get("perSecond") or 0.0), 0.0)
    duration = max(float(row.get("durationSeconds") or 0.0), 0.0)
    if expected_procs <= 0.0 or per_second <= 0.0 or duration <= 0.0:
        return 0.0
    active_cloud = min(expected_procs * proc_rate * duration, 10.0)
    average_hit_multiplier = (
        max(float(damage_rate_multiplier), 0.0) / max(float(status_rate_multiplier), 0.0)
        if status_rate_multiplier
        else 0.0
    )
    return per_second * active_cloud * average_hit_multiplier


def windowed_status_damage(
    stats: ModdedStats,
    target: Mapping[str, Any] | None = None,
    *,
    attacks_per_second: float,
    window_seconds: float = 5.0,
    headshot_chance: float = 0.0,
    status_rate_multiplier: float = 1.0,
    damage_rate_multiplier: float = 1.0,
    forced_procs: Mapping[str, float] | None = None,
    level: int | None = None,
    armour_strip: float = 0.0,
    elemental_armour_strip: float = 0.0,
    steel_path: bool = False,
    enemy_enhancements: Mapping[str, Any] | None = None,
    time_step: float = 0.25,
    trigger_sources: Sequence[Mapping[str, Any]] | None = None,
    collect_timeline: bool = True,
) -> dict[str, Any]:
    """Startup-aware, pool-transition-aware damage model (stepped).

    Advances the fight from zero stacks in ``time_step`` slices over
    ``window_seconds``.  Each step: live stack levels (viral/magnetic ramp from
    zero, corrosive/heat armour strip grows with the *current* step's stacks),
    the target's current pool (overguard → shield → health as pools drain),
    direct damage per shot with the step's pool amplifier, and DoT damage from
    the cloud mass that is actually alive at that step.

    Source of the corrections vs the earlier closed-form model (all mirrored
    from wfsim MECHANICS.md, AGPL-3.0, see THIRD_PARTY_NOTICES.md):
    - Stack ramp is *observed at each step*, not time-averaged — the first
      second of a fight does not enjoy 8-stack amplifiers it has not built yet.
    - Gas is a 10-slot single cloud against a lone target (§6 DoT table).
    - Each DoT tick group carries a +1 flat accumulator (§5 M58):
      ``tick = (Σ seeds + 1) × C × M`` — only Heat/Electricity/Gas share one
      accumulator (they consolidate); Slash and Toxin carry one per stack.
    - Pool transitions: when the overguard drains mid-window the remainder of
      the window is amplified by *viral on health*, not magnetic — the
      amplifiers are read at tick time, which is the live-pool rule (§6
      snapshot-vs-live boundary).
    - Heat ticks grow with the live armour strip (corrosive/heat) since armour
      mitigation is a tick-time input (§6 boundary rule); Bleed stays armour-
      blind (Cinematic).
    """
    # Heat is a refreshable tick entity, not continuous damage in a time bin.
    # Use the same event kernel as manual replay for Heat-bearing candidates.
    # A stat-only search has no loadout event context: its buffs stay panel-assumed.
    if stats.damage_types.get('DT_FIRE', 0) > 0 and isinstance(target, Mapping) and target.get('health'):
        from .combat_replay import replay
        return replay(
            stats, target, attacks_per_second=attacks_per_second, window_seconds=window_seconds,
            headshot_chance=headshot_chance, status_rate_multiplier=status_rate_multiplier,
            damage_rate_multiplier=damage_rate_multiplier, forced_procs=forced_procs, level=level,
            armour_strip=armour_strip, elemental_armour_strip=elemental_armour_strip,
            steel_path=steel_path, enemy_enhancements=enemy_enhancements, time_step=time_step,
            trigger_sources=trigger_sources, collect_timeline=collect_timeline,
        )
    target = target if isinstance(target, Mapping) else {}
    rate = max(float(attacks_per_second), 0.0)
    proc_rate = rate * max(float(status_rate_multiplier), 0.0)
    damage_rate = rate * max(float(damage_rate_multiplier), 0.0)
    window = max(float(window_seconds), 0.0)
    step = min(max(float(time_step), 0.05), max(window, 0.05))
    # 优化器热路径只需要 KPM/窗口伤害标量：跳过逐步 timeline 字典构造
    # （每步 ~15 个 round() + dict），测量占窗口模型 ~30%。
    emit_timeline = bool(collect_timeline)

    # ── 触发源 emergent 模拟（wfsim BUFFS.md StackPolicy::Emergent）────────
    # trigger_sources 由 app 层打包：每个源描述 {id, label, kind, perEvent,
    # maxStacks, duration, decay}——on-kill/on-hit/on-crit 赋能、镀层 MOD、
    # 灵化 on-kill 进化。emergent 时层数按事件率从零爬升（按 kill 率或
    # 命中率），带 duration 衰减；assumed_max 恒满。每步层数写入 timeline
    # 的 triggerStacks 字段，前端渲染覆盖率折线图。
    trigger_specs: list[dict[str, Any]] = []
    for raw in trigger_sources or ():
        if not isinstance(raw, Mapping):
            continue
        spec = {
            "id": str(raw.get("id") or raw.get("path") or "?"),
            "label": str(raw.get("label") or raw.get("nameZh") or raw.get("nameEn") or raw.get("id") or "?"),
            "kind": str(raw.get("kind") or "on-kill"),
            "perEvent": max(float(raw.get("perEvent") or 1.0), 0.0),
            "maxStacks": max(float(raw.get("maxStacks") or 1.0), 1.0),
            "duration": max(float(raw.get("duration") or 0.0), 0.0),
            "decay": str(raw.get("decay") or "lose_one_and_reset"),
            "currentStacks": 0.0,
            "series": [] if collect_timeline else None,
        }
        # ── 灵化 SubUpgrade 叠层的伤害反馈（事件化建模）─────────────────
        # 带 gate 元数据的条件子词条（如 Boltor 猩红序曲的「+2 伤害/层，
        # 最多 4 层，持续 5s」）从触发事件获得层数后，其伤害分量按
        # 当前层数 × 每层基伤加值折算进直伤乘区。damagePerStackBase 是
        # 每层的基伤**加值**（ADD_BASE 口径）——按步内当前层数线性叠加。
        damage_per_stack = raw.get("damagePerStack")
        if isinstance(damage_per_stack, (int, float)) and not isinstance(damage_per_stack, bool) and damage_per_stack > 0:
            spec["damagePerStack"] = float(damage_per_stack)
            # 叠层伤害的基数：以窗口起点的面板总伤为锚（ADD_BASE 的每层
            # 加值是绝对伤害，不随面板乘区缩放——引擎口径是加到基伤，
            # 但窗口层以「每层加值 / 初始面板」折算成乘数最稳）。
            base_total = max(stats.total_damage, 1e-9)
            spec["stackDamageScalePerStack"] = float(damage_per_stack) / base_total
        trigger_specs.append(spec)

    # CO emergent 重算（wfsim M27：镀层 CO 在杀不动的高级靶上接近无效）。
    # stats.damage_types 已按面板假定层数（victim_status_count）预乘 CO 乘区。
    # 战斗口径下 CO 应读「当前时刻目标身上活着的异常类型数」——把 CO 从伤害
    # 向量中剥离（按假定层数还原基伤乘区），每步按 live type count 重乘。
    co_bucket = list(getattr(stats, "co_bucket", None) or [])
    co_assumed = float(getattr(stats, "co_assumed_count", 0.0) or 0.0)
    if co_bucket and co_assumed > 0:
        assumed_scale = _combine(1.0, [_scale_effect(e, co_assumed) for e in co_bucket])
        if assumed_scale > 1.0:
            stats = replace(
                stats,
                damage_types={
                    dtype: value / assumed_scale
                    for dtype, value in stats.damage_types.items()
                },
                dot_base_damage=(
                    stats.dot_base_damage / assumed_scale
                    if stats.dot_base_damage is not None
                    else None
                ),
            )

    magazine = max(float(getattr(stats, "magazine", 0.0) or 0.0), 0.0)
    first_shot_bonus = max(float(getattr(stats, "first_shot_damage_bonus", 0.0) or 0.0), 0.0)
    if magazine > 0.0 and first_shot_bonus > 0.0 and damage_rate > 0.0:
        damage_rate *= 1.0 + first_shot_bonus / magazine

    target_kwargs = {
        "level": level,
        "armour_strip": armour_strip,
        "steel_path": steel_path,
        "enemy_enhancements": enemy_enhancements,
    }
    probe = expected_status_damage(
        stats, target, forced_procs=forced_procs, **target_kwargs
    )
    head_weight = min(max(float(headshot_chance), 0.0), 1.0)
    def mix(body, head):
        if isinstance(body, Mapping) and isinstance(head, Mapping):
            return {k: mix(v, head.get(k, v)) for k, v in body.items()}
        if isinstance(body, (int, float)) and not isinstance(body, bool) and isinstance(head, (int, float)):
            return body * (1.0 - head_weight) + head * head_weight
        return body
    if head_weight:
        head_probe = expected_status_damage(
            stats, target, forced_procs=forced_procs, hit_location='head', **target_kwargs
        )
        mixed = mix(probe, head_probe)
        # Per-proc seeds average over procs, not hits: crit-conditioned procs
        # (Hunter Munitions) land more often on the higher weak-point crit.
        head_rows = head_probe["dot"]["perType"]
        for dtype, row in mixed["dot"]["perType"].items():
            body_row = probe["dot"]["perType"][dtype]
            head_row = head_rows.get(dtype, body_row)
            if head_row["expectedProcs"] == body_row["expectedProcs"]:
                continue
            weighted = (
                (1.0 - head_weight) * body_row["expectedProcs"] * body_row["seedPerSecondPerProc"]
                + head_weight * head_row["expectedProcs"] * head_row["seedPerSecondPerProc"]
            )
            if row["expectedProcs"] > 0.0:
                row["seedPerSecondPerProc"] = weighted / row["expectedProcs"]
        probe = mixed
    procs = probe["expectedProcs"]
    duration_scale = max(float(stats.proc_duration_multiplier), 0.0)

    # Per-type stack specs: (duration seconds, in-game cap, tick-group shared?).
    # NOTE heat: the cap below only bounds the armour-strip stack count (wiki:
    # heat procs strip up to 50% armour via its own ramp) — heat's DoT tick
    # damage is NOT capped this way: every heat proc both adds a layer AND
    # refreshes every active layer's duration ("Heat Inherit", warframe wiki
    # Heat Damage page, "Heat Inherit" section), so the tick damage grows
    # linearly with the *cumulative* proc count while attacks keep landing
    # (see heat_inherit tracking in the step loop).
    stack_specs = {
        "viral": ("DT_VIRAL", 6.0, 10.0, False),
        "corrosive": ("DT_CORROSIVE", 8.0, 10.0, False),
        "magnetic": ("DT_MAGNETIC", 6.0, 10.0, False),
        "cold": ("DT_FREEZE", 6.0, 10.0, False),
        "puncture": ("DT_PUNCTURE", 10.0, 5.0, False),
        "heat": ("DT_FIRE", 6.0, 1.0, True),
    }

    # live_stacks 的窗口常量预展开：(key, ramp_rate=per_attack×proc_rate,
    # 有效时长, cap)。每步循环直接读平铺元组，不查 dict/不乘 scale。
    _live_stack_constants: list[tuple[str, float, float, float]] = [
        (
            key,
            float(procs.get(_dtype) or 0.0) * proc_rate,
            duration * duration_scale,
            cap,
        )
        for key, (_dtype, duration, cap, _shared) in stack_specs.items()
    ]

    def vulnerability(count: float) -> float:
        if count <= 0.0:
            return 1.0
        if count < 1.0:
            return 1.0 + count
        return min(2.0 + 0.25 * (count - 1.0), 4.25)

    def live_stacks(elapsed: float) -> dict[str, float]:
        """Stack levels alive at ``elapsed`` seconds from a zero start.

        A proc at time u is alive at t while u + duration > t.  With a uniform
        schedule at rate r the live count at t is r·min(t, duration) — capped
        for stacking debuffs (replace-oldest) and uncapped for refresh-style
        ones modelled through their caps anyway.

        NOTE heat: the value returned here (capped by the spec above) feeds the
        armour-strip / CO-type-count reads only.  Heat's DoT tick layers are
        uncapped "Heat Inherit" accumulation tracked separately in the step
        loop (see the heat_inherit state below).
        """
        # ── 性能：per_attack×proc_rate 与有效时长是窗口常量，预展开成
        # 平铺序列；步循环百万次调用不再每步查 dict + 乘 duration_scale。
        levels: dict[str, float] = {}
        for key, ramp_rate, d, cap in _live_stack_constants:
            if ramp_rate <= 0.0 or d <= 0.0:
                levels[key] = 0.0
                continue
            levels[key] = min(ramp_rate * min(elapsed, d), cap)
        return levels

    def corrosive_strip_of(count: float) -> float:
        return (
            0.26 * count
            if count < 1.0
            else min(0.26 + 0.06 * (count - 1.0), 0.8)
        )

    # ── DoT per-type per-proc-second contributions (without pool/strip) ──────
    # ── F02/F03（审计修复）显式合同消费 ─────────────────────────────────
    # 生产者（expected_dot_damage）现在按行输出：
    #   seedPerSecondPerProc        —— 单次 proc 的每秒种子伤害（不含 +1 累加、
    #                                 含 target_multiplier，下方再剥离静态部分）
    #   accumulatorPerSecondPerAttack —— 一次攻击触发的全部 +1 累加项每秒伤害
    #                                 （共享 tick group = 1 份；独立 tick = 每层一份）
    #   accumulatorSharedGroup      —— 是否共享 tick group
    #   durationSeconds             —— 最终时长（已含 proc_duration_multiplier，
    #                                 消费端不再乘第二次：F03）
    # 旧实现 perSeed = perSecondRaw / expectedProcs 把累加项一并除掉，且窗口
    # 再追加一个 flat 累加项，非零触发数在主项中相互抵消（F02 表格的行为）。
    dot_payload: dict[str, dict[str, float]] = {}
    for dtype, row in ((probe.get("dot") or {}).get("perType") or {}).items():
        expected_procs = max(float(row.get("expectedProcs") or 0.0), 0.0)
        # F03：durationSeconds 是生产者给定的最终时长（6 × 倍率），禁止再乘。
        duration = max(float(row.get("durationSeconds") or 0.0), 0.0)
        seed_rate = row.get("seedPerSecondPerProc")
        acc_rate = row.get("accumulatorPerSecondPerAttack")
        if not isinstance(seed_rate, (int, float)) or isinstance(seed_rate, bool):
            # 旧版 probe（无显式合同字段）不进入窗口模型：宁可拒算也不反推。
            continue
        seed_rate = max(float(seed_rate), 0.0)
        if isinstance(acc_rate, (int, float)) and not isinstance(acc_rate, bool):
            acc_rate = max(float(acc_rate), 0.0)
        else:
            acc_rate = 0.0
        shared_group = bool(row.get("accumulatorSharedGroup"))
        if seed_rate <= 0.0 or duration <= 0.0 or expected_procs <= 0.0:
            continue
        # Strip the static target multiplier that expected_dot_damage baked in
        # (faction deltas / armour at t=0 / magnetic at t=0) so the live armour
        # and pool state can be re-applied per step.
        static_target = max(float(row.get("targetMultiplier") or 1.0), 1e-9)
        dot_payload[dtype] = {
            "seedPerProc": seed_rate / static_target,
            "accumulatorRate": acc_rate / static_target,
            "expectedProcs": expected_procs,
            "duration": duration,
            "sharedGroup": shared_group,
        }

    # ── non-DoT procs ride the direct schedule ────────────────────────────────
    non_dot_per_hit: dict[str, float] = {}
    for dtype, row in ((probe.get("nonDot") or {}).get("perType") or {}).items():
        static_target = max(float(row.get("targetMultiplier") or 1.0), 1e-9)
        value = max(float(row.get("expectedDamage") or 0.0), 0.0)
        if value > 0.0:
            non_dot_per_hit[dtype] = value / static_target

    defenses = enemy_defenses(target, **target_kwargs)
    # defenses 快照供步循环的 fast-path damage_against_cached_armour 使用
    # （跳过 60 万次 enemy_defenses 重算）。armour 每步由 live_armour 覆盖。
    defenses_snapshot = dict(defenses)
    # 目标派生常量缓存（hit/faction/bypass）：全窗口不变，算一次。
    _target_cache = {
        "hit_multiplier": 1.0,
        "hit_critical_multiplier": 1.0,
        "faction_deltas": _faction_damage_deltas(target),
        "armour_bypass": _damage_type_set(
            target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
        ),
        "shield_bypass": _damage_type_set(
            target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
        ),
        "target_faction": str(target.get("faction") or ""),
    }
    _loc, _hm, _hcm, _hu, _hmd = _hit_location_info(target, None)
    _target_cache["hit_multiplier"] = _hm
    _target_cache["hit_critical_multiplier"] = _hcm
    head_cache = dict(_target_cache)
    _, hm, hcm, _, _ = _hit_location_info(target, 'head')
    head_cache.update(hit_multiplier=hm, hit_critical_multiplier=hcm)

    def mixed_direct(*args, **kwargs):
        body = damage_against_cached_armour(*args, **kwargs)
        if not head_weight:
            return body
        head = damage_against_cached_armour(*args, **{**kwargs, '_target_cache': head_cache})
        return mix(body, head)

    total_overguard = float(defenses.get("overguard") or 0.0)
    total_shield = float(defenses.get("shield") or 0.0)
    total_health = float(defenses.get("health") or 0.0)
    shield_bypass = _damage_type_set(
        target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
    )
    faction_deltas = _faction_damage_deltas(target)
    armour_base = float(defenses.get("armour") or 0.0)
    existing_magnetic = int((enemy_enhancements or {}).get("magneticStacks") or 0)

    # Track pools as they drain across steps.
    overguard_left = total_overguard
    shield_left = total_shield
    health_left = total_health
    kills_count = 0
    total_ehp_ref = total_overguard + total_shield + total_health
    first_kill_time: float | None = None
    last_kill_time: float | None = None
    min_kill_interval: float | None = None
    max_kills_per_step = 0
    # Ramp clock: resets to zero on every kill (stacks live on the dead body;
    # the fresh target starts with none — wfsim InstantRespawn semantics).
    ramp_elapsed = 0.0
    # ── F01/F04（审计修复）目标代次与 stale 组件计数 ──────────────────
    # generation：目标代次（每次死亡 +1）。目标绑定的状态（DoT 层、Heat
    # Inherit、ramp 时钟）随代次清理；stale_component_count：同次攻击的
    # 组件在目标死亡后无法转杀重生目标的计数（E02 诊断，与 ledger 口径
    # 一致）。
    generation = 0
    stale_component_count = 0

    # ── Heat Inherit 状态（warframe wiki · Heat Damage · "Heat Inherit" 节）─
    # 每个 heat proc 既加一层又刷新所有当前活跃层的持续时间（基础 6s ×
    # 状态持续时间），所有层每秒合并为单一 tick：tick 伤害 = 已累积层数 ×
    # 每层伤害。只要攻击不断档（6s 内持续刷新），层数 = 历史总 proc 数，
    # tick 伤害随层数线性无限增长——没有固定 cap。断档（距最后一次 proc
    # 超过有效时长）则全部层过期，从零重新累积。
    # 注意口径区分：削甲用的 heat 活层（live_strip，上限 50%）仍走
    # live_stacks 的 cap 口径；本状态只喂 DoT tick 伤害（cloud_procs）。
    _heat_rate = float(procs.get("DT_FIRE") or 0.0) * proc_rate  # heat procs/s
    _heat_duration = 6.0 * duration_scale
    heat_inherit_total = 0.0  # 继承中的累计层数（断档/击杀清零）
    heat_inherit_last = 0.0   # 最后一次 heat proc 的绝对时刻

    direct_total = 0.0
    dot_total = 0.0
    non_dot_total = 0.0
    # The stepped window remains the authoritative hybrid model for status/field
    # damage, but direct attacks also get a real attack-instance ledger.  Keeping
    # this next to the production window output makes the attack-count invariant
    # observable at the optimizer entry point instead of only in helper tests.
    # It is deliberately diagnostic until DoT/field events are scheduled against
    # the same target-generation state machine.
    direct_event_ledger: dict[str, Any] = {
        "model": "direct-event-ledger-v1",
        "status": "unavailable",
        "componentModel": "none",
        "limitations": [
            "direct-only-diagnostic",
            "continuous-dot-and-field-events-not-in-ledger",
            "first-shot-and-dynamic-conditionals-not-in-ledger",
        ],
    }
    if total_ehp_ref > 0.0 and rate > 0.0:
        initial_direct = mixed_direct(
            stats,
            armour_base,
            defenses_snapshot,
            level=level,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
            target=target,
            _target_cache=_target_cache,
        )
        per_shot = max(float(initial_direct.get("perShot") or 0.0), 0.0)
        multishot = max(float(getattr(stats, "multishot", 1.0) or 1.0), 1.0)
        rounded_multishot = int(round(multishot))
        if (
            rounded_multishot >= 1
            and rounded_multishot <= 64
            and abs(multishot - rounded_multishot) <= 1e-9
        ):
            pellet_damage = per_shot / rounded_multishot
            components = [
                (f"pellet-{index + 1}", pellet_damage * max(float(damage_rate_multiplier), 0.0))
                for index in range(rounded_multishot)
            ]
            component_model = "integer-multishot-pellets"
        else:
            components = [
                ("expected-shot", per_shot * max(float(damage_rate_multiplier), 0.0))
            ]
            component_model = "aggregated-expected-shot"
        direct_event_ledger = direct_fire_ledger(
            attacks_per_second=rate,
            window_seconds=window,
            target_ehp=total_ehp_ref,
            component_damage=components,
            collect_trace=emit_timeline,
        )
        direct_event_ledger.update(
            {
                # ── F01（审计修复）：主循环与账本共用同一开火调度与组件
                # 口径，账本不再只是诊断——它是同一结算的独立复算（可交叉
                # 验证）。字段名保持 status 以兼容旧消费方。
                "status": "settled-authoritative",
                "componentModel": component_model,
                "perShotDamage": per_shot,
                "multishot": multishot,
                "attackRateSource": "window-attacks-per-second",
            }
        )
    timeline: list[dict[str, Any]] = []
    averaged: dict[str, float] = {k: 0.0 for k in stack_specs}
    steps = 0

    # ── 步循环性能缓存（Boltor 89s → 目标 <20s）─────────────────────────
    # 直伤每步的唯一输入是 (co_scale, pool, live_armour, cold_crit,
    # puncture_crit)：全都不变时复用上一步的 damage_against_cached_armour
    # 结果（数组/字典浅拷贝引用安全——下游只读）。cold/puncture 增量走
    # crit 覆写参数，不再每步 replace() 重建整个 ModdedStats（4.5M 次
    # dataclass 重建 → 0）。quantize 分母（dot_base_damage）也随 co_scale
    # 缓存，避免重复量化。
    _last_direct_key: tuple | None = None
    _last_direct: dict[str, Any] | None = None
    _last_crit_overrides: tuple[float, float] = (0.0, 0.0)
    elapsed = 0.0
    # CO scale 步间缓存（大多数步 co_scale 稳定后跳过 replace）。
    _last_co_scale: list[float] = [-1.0]
    _last_co_stats: list[Any] = [None]
    while elapsed < window - 1e-9:
        dt = min(step, window - elapsed)
        steps += 1
        levels = live_stacks(ramp_elapsed + dt * 0.5)  # midpoint sampling
        # Ramp clock: advanced at the END of the step body (below the event
        # subloop) so kills inside the step can reset it to the post-death
        # remainder first.  A kill resets it in _settle_death.

        # ── Heat Inherit 层数推进（本步区间 [elapsed, elapsed+dt]）──────
        # 步进语义（wiki Heat Damage · "Heat Inherit"）：本步 proc 速率 > 0
        # → 视为持续刷新，累计层 += 速率×dt，并刷新「最后 proc 时刻」；速率
        # == 0 且距最后 proc 超过有效时长（6s×状态持续时间）→ 断档，全部
        # 继承层过期清零（清零后从下一次 proc 重新累积）。击杀清零在下方
        # 泵池循环里（新目标不继承）。
        if _heat_rate > 0.0:
            heat_inherit_total += _heat_rate * dt
            heat_inherit_last = elapsed + dt
        elif (
            heat_inherit_total > 0.0
            and elapsed + dt - heat_inherit_last > _heat_duration
        ):
            heat_inherit_total = 0.0

        # CO emergent：本步目标身上活着的异常「类型数」（wfsim §2 CO
        # counting：distinct TYPES，含隐藏 Lifted/Knockdown；这里数建模
        # 中的六类 + 非 DoT 触发类型，≥0.05 层视为在场）。
        live_type_count = sum(
            1 for value in levels.values() if value >= 0.05
        ) + sum(
            1
            for dtype in non_dot_per_hit
            if (procs.get(dtype) or 0.0) * proc_rate * min(ramp_elapsed, 6.0) >= 0.05
        )
        if co_bucket:
            co_scale = _combine(1.0, [_scale_effect(e, live_type_count) for e in co_bucket])
            # ── 性能：co_scale 与上一步相同（大多数步层数稳定后）时跳过
            # replace。缓存的 _last_co_scale 初始为 -1 强制首步构建。
            if co_scale != _last_co_scale[0]:
                step_stats = replace(
                    stats,
                    damage_types={
                        dtype: value * co_scale
                        for dtype, value in stats.damage_types.items()
                    },
                    dot_base_damage=(
                        stats.dot_base_damage * co_scale
                        if stats.dot_base_damage is not None
                        else None
                    ),
                )
                _last_co_scale[0] = co_scale
                _last_co_stats[0] = step_stats
            else:
                step_stats = _last_co_stats[0]
        else:
            step_stats = stats

        # Live armour: base armour minus the corrosive/heat strip the stacks
        # built so far (heat ticks grow as the strip deepens — live value).
        live_strip = 1.0 - (
            (1.0 - elemental_armour_strip)
            * (1.0 - corrosive_strip_of(levels["corrosive"]))
            * (1.0 - 0.5 * levels["heat"])
        )
        live_armour = armour_base * (1.0 - live_strip)

        viral_mult = vulnerability(levels["viral"])
        combined_magnetic = min(existing_magnetic + levels["magnetic"], 10.0)
        magnetic_mult = vulnerability(combined_magnetic) / vulnerability(float(existing_magnetic))

        # Pool state at this step.
        if overguard_left > 0.0:
            pool = "overguard"
        elif shield_left > 0.0:
            pool = "shield"
        else:
            pool = "health"

        def step_pool_multiplier(dtype: str) -> float:
            if pool == "overguard":
                return magnetic_mult
            if pool == "shield" and dtype not in shield_bypass:
                return magnetic_mult
            return viral_mult

        def step_target_multiplier(dtype: str) -> float:
            interaction = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
            value = max(0.0, 1.0 + faction_deltas.get(interaction, 0.0))
            hits_health = pool != "shield" or interaction in shield_bypass
            # Bleed (Cinematic) is armour-blind; heat/normal ticks read live armour.
            if hits_health and live_armour > 0.0 and interaction not in (
                "DT_CINEMATIC",
            ):
                value *= 1.0 - _armour_reduction(live_armour)
            return value

        # ── 引擎裁决（2026-09-23 proc-mechanics-re.json）：删除穿刺/冰动态暴击 ──
        # 引擎二进制证实：不存在「穿刺每层 +5% 暴击率（上限 25%）」和「冰每层
        # +10% 暴伤（上限 50%）」的内建机制。旧模型把这两个臆造加成作为
        # crit 覆写传给每步直伤，同时虚增暴击频率与暴击档位伤害（对比
        # wfsim 的 KPM 虚高主要来源之一）。
        # 引擎真实语义：
        #   - 对「带任意指定 proc 的目标」加暴击，只通过数据驱动的
        #     WEAPON_CRIT_CHANCE_IF_VICTIM_PROC_ACTIVE 词条实现（平坦值、
        #     非按层），已由 mod 桶按 ValidProcTypes 正常处理。
        #   - 冰（PT_CHILLED）是冻结层机器（mBaseFreezeModifier 等字段，
        #     数值数据驱动未解出）；暴击交互只有 WEAPON_FROZEN_CRIT_*，
        #     当前全部原生内容零使用。
        #   - 无冰内置 CD（proc 门控是乘法免疫检查 fn 0x14170e110）。
        # 窗口层因此不再注入任何 crit 覆写。
        crit_overrides = (0.0, 0.0)
        # Live-pool per-shot direct damage: recompute the target interaction at
        # the step's armour/pool.  damage_against on a synthesized record keeps
        # level scaling identical (armour already level-scaled by defenses).
        # ── 性能关键路径：damage_against 内部会完整重跑 enemy_defenses（等级
        # 缩放/SP/eximus 全套），120 步 × ~5k 次评估 = 60 万次重复。改为步
        # 循环前算一次「无护甲」的 defenses 快照（health/shield/overguard 等
        # 常量），每步只重算护甲乘区（live_armour 已知）。
        # ── 性能第二层：直伤的全部输入 (co_scale, pool, live_armour,
        # crit_overrides) 稳定后（爬层期结束的绝大多数步）完全复用上一步
        # 的结果——Boltor 场景 120 步里 ~95 步命中。
        direct_key = (
            _last_co_scale[0],
            pool,
            live_armour,
            crit_overrides,
        )
        if direct_key == _last_direct_key and _last_direct is not None:
            direct = _last_direct
        else:
            direct = mixed_direct(
                step_stats,
                live_armour,
                defenses_snapshot,
                level=level,
                steel_path=steel_path,
                enemy_enhancements=enemy_enhancements,
                target=target,
                _target_cache=_target_cache,
                crit_chance_add=crit_overrides[0],
                crit_multiplier_add=crit_overrides[1],
            )
            _last_direct_key = direct_key
            _last_direct = direct
        per_type = direct.get("perType") or {}
        per_type_total = sum(float(v) for v in per_type.values()) or 1.0
        weighted = sum(
            float(v) * step_pool_multiplier(str(dt2)) for dt2, v in per_type.items()
        )
        # ── F01（审计修复）：直伤改为离散攻击事件结算 ─────────────────────
        # 旧实现把直伤当连续流：step_direct = perShot × damage_rate × dt，
        # 击杀数 = 伤害/EHP——超杀会泄漏到不存在的目标上（审计反例：1 Hz、
        # 30 秒、10 倍超杀主循环算出 300 杀/600 KPM，物理上限只有 30 杀）。
        # 现在主循环与 direct ledger 共用同一开火调度：本步区间
        # [elapsed, elapsed+dt) 内的第 k 次攻击在 t = k/rate 落地。攻击与
        # DoT 的连续流量在事件子循环里交错结算：攻击时刻把直伤按「组件」
        # 逐个结算（同次攻击的剩余组件在目标死亡后 stale，不能转杀重生
        # 目标，E02；不同攻击实例可以各自击杀重生目标，E03）；两个攻击
        # 时刻之间按 DoT/非DoT 的连续流量推进（DoT tick 本来就是连续的）。
        _multishot = max(float(getattr(stats, "multishot", 1.0) or 1.0), 1.0)
        _rounded_multishot = int(round(_multishot))
        _component_count = (
            _rounded_multishot
            if 1 <= _rounded_multishot <= 64
            and abs(_multishot - _rounded_multishot) <= 1e-9
            else 1
        )
        _per_attack = (
            float(direct.get("perShot") or 0.0)
            * (weighted / per_type_total)
            * max(float(damage_rate_multiplier), 0.0)
        )
        # ── 灵化 SubUpgrade 叠层伤害反馈（事件化）──────────────────────
        # 带伤害分量的触发源（damagePerStack）按「当前步的层数 × 每层
        # 加值」线性放大本步直伤。层数由步末 trigger 推进更新；本步用
        # 的是上一推进后的当前值（事件先发生、增益后生效的保守口径）。
        _stack_damage_scale = 1.0
        for spec in trigger_specs:
            per_stack = spec.get("stackDamageScalePerStack")
            if per_stack and spec["currentStacks"] > 0.0:
                _stack_damage_scale += float(per_stack) * spec["currentStacks"]
        _per_attack *= _stack_damage_scale
        _component_damage = _per_attack / _component_count
        # 本步攻击事件：k 满足 elapsed ≤ k/rate < elapsed+dt（k ≥ 0，首
        # 发 t=0）。注意首个步（elapsed=0）包含 k=0——首杀时刻为 0。
        _first_k = max(0, int(math.ceil(elapsed * rate - 1e-9)))
        _last_k = int(math.ceil((elapsed + dt) * rate - 1e-9)) - 1
        _attack_times = [
            _k / rate
            for _k in range(_first_k, _last_k + 1)
            if _k / rate < window - 1e-12
        ]

        # DoT at this step: cloud mass alive = seeds applied within the last
        # `duration` seconds × their payload, amplified by the live pool/strip.
        # ── F02/F04（审计修复）合同重写 ───────────────────────────────
        # 活跃 proc 数：expectedProcs（每次攻击的期望触发数）× proc_rate
        # （每秒攻击数）× 存活窗口。种子伤害按「每 proc」计价（生产者已拆
        # 分），触发数变化现在正确进入主项。+1 累加项（M58）按 tick group
        # 计价：共享组（Heat/Electricity/Gas）整个云只有一份；独立组
        # （Slash/Toxin）每活跃 proc 一份——不再从聚合值反推，也不重复
        # 计费。窗口存活时间用「本代次的重生时钟」（F04：目标绑定 DoT 不
        # 继承到重生目标）。
        dot_rate = 0.0
        for dtype, payload in dot_payload.items():
            duration = payload["duration"]
            # Cloud mass at t: expected procs whose age < duration.  ramp_elapsed
            # is the current generation's clock (reset on death, F04).
            window_alive = min(ramp_elapsed + dt * 0.5, duration)
            if window_alive <= 0.0:
                continue
            cloud_procs = payload["expectedProcs"] * proc_rate * window_alive
            if dtype == "DT_GAS":
                # Single-target cloud: one 10-slot cloud (see helper docstring).
                cloud_procs = min(cloud_procs, 10.0)
            elif dtype == "DT_FIRE":
                # Heat Inherit（wiki Heat Damage · "Heat Inherit" 节）：每个
                # heat proc 加一层并刷新所有活跃层——只要攻击不断档，tick 用
                # 的层数是「历史累计 proc 数」而不是 6s 活窗口内的数量；断档
                # 清零已在循环顶部的 heat_inherit 推进里处理。tick 伤害随
                # 层数线性无限增长（无固定 cap）。
                cloud_procs = heat_inherit_total
            seed_payload = payload["seedPerProc"]
            # +1 accumulator per tick group (consolidating) or per live proc
            # (independent stacks each carry their own).  accumulatorRate is
            # the producer-declared per-attack rate; shared groups pay it once
            # per cloud, independent groups pay per live proc (already scaled
            # by expectedProcs inside the producer's accumulator count).
            if payload["sharedGroup"]:
                accumulator_rate = payload["accumulatorRate"]
            else:
                # Independent: accumulatorPerSecondPerAttack already counts
                # one +1 per expected proc per attack; live fraction of those
                # procs is cloud_procs / (expectedProcs × proc_rate × duration)
                # ≈ window_alive / duration when the ramp has saturated.
                live_fraction = (
                    cloud_procs
                    / (payload["expectedProcs"] * proc_rate * duration)
                    if payload["expectedProcs"] * proc_rate * duration > 0.0
                    else 0.0
                )
                accumulator_rate = payload["accumulatorRate"] * min(live_fraction, 1.0)
            interaction = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
            live_target = step_target_multiplier(dtype)
            dot_rate += (
                (cloud_procs * seed_payload + accumulator_rate)
                * step_pool_multiplier(interaction)
                * live_target
            )

        # Non-DoT procs ride the direct attack schedule (per attack, not per
        # second): their per-hit value multiplies the attack count.
        non_dot_per_attack = 0.0
        for dtype, value in non_dot_per_hit.items():
            interaction = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
            non_dot_per_attack += (
                value
                * step_pool_multiplier(interaction)
                * step_target_multiplier(interaction)
            )

        # ── 事件子循环：攻击时刻与 DoT 连续流量交错结算 ──────────────────
        # 时间轴：把本步 [elapsed, elapsed+dt) 切成「攻击时刻 + 攻击间隙」。
        # 间隙里 DoT 以 dot_rate 连续流过；攻击时刻直伤按组件离散结算。
        # 死亡（无论来源）即时重生并清理代次状态（F04）。
        step_direct = 0.0
        step_dot = 0.0
        step_non_dot = 0.0
        step_kills = 0
        _cursor = elapsed

        def _settle_death(kill_time: float) -> None:
            """目标死亡 → 即时重生，代次状态清理（F04 合同）。"""
            nonlocal kills_count, first_kill_time, last_kill_time, min_kill_interval
            nonlocal overguard_left, shield_left, health_left
            nonlocal heat_inherit_total, heat_inherit_last, ramp_elapsed
            nonlocal step_kills, generation
            kills_count += 1
            step_kills += 1
            if first_kill_time is None:
                first_kill_time = kill_time
            if last_kill_time is not None:
                interval = kill_time - last_kill_time
                min_kill_interval = (
                    interval
                    if min_kill_interval is None
                    else min(min_kill_interval, interval)
                )
            last_kill_time = kill_time
            overguard_left = total_overguard
            shield_left = total_shield
            health_left = total_health
            # 代次状态：重生目标从零层开始（目标绑定 DoT/Heat Inherit/
            # ramp 时钟不继承）。ramp 时钟推进到「重生时刻到步末」——
            # 下一步的 live_stacks/cloud 以新代次的时间轴计算。
            generation += 1
            heat_inherit_total = 0.0
            heat_inherit_last = 0.0
            ramp_elapsed = max(elapsed + dt - kill_time, 0.0)

        def _apply_continuous(rate_per_second: float, span: float) -> float:
            """间隙内连续流量结算：返回实际入账伤害（不超杀）。"""
            nonlocal overguard_left, shield_left, health_left
            if rate_per_second <= 0.0 or span <= 0.0:
                return 0.0
            damage = rate_per_second * span
            applied = 0.0
            left = damage
            guard = 0
            # 同一步内连续流量最多击穿一次 EHP（跨代次的流量由外层事件
            # 交错逐段结算，不存在一段间隙里杀两个代的物理事件源——
            # DoT 流量对每个代次分别积分）。
            current_ehp = max(overguard_left + shield_left + health_left, 0.0)
            if current_ehp <= 1e-12:
                return 0.0
            applied = min(damage, current_ehp)
            left = applied
            if overguard_left > 0.0:
                drained = min(overguard_left, left)
                overguard_left -= drained
                left -= drained
            if left > 0.0 and shield_left > 0.0:
                drained = min(shield_left, left)
                shield_left -= drained
                left -= drained
            if left > 0.0 and health_left > 0.0:
                drained = min(health_left, left)
                health_left -= drained
                left -= drained
            guard += 1
            if guard > 100:
                return applied
            return applied

        for _fire_time in _attack_times:
            # 攻击时刻前的间隙：DoT 连续流量结算。
            gap = _fire_time - _cursor
            if gap > 1e-12 and dot_rate > 0.0:
                applied = _apply_continuous(dot_rate, gap)
                step_dot += applied
                _pre_death = (
                    overguard_left + shield_left + health_left <= 1e-12
                )
                if _pre_death:
                    _settle_death(_fire_time)
            _cursor = _fire_time
            # 攻击时刻：非DoT proc 的每击值 + 直伤组件离散结算。
            if non_dot_per_attack > 0.0:
                _nd_ehp = max(
                    overguard_left + shield_left + health_left, 0.0
                )
                _nd_applied = min(non_dot_per_attack, _nd_ehp)
                _left = _nd_applied
                if overguard_left > 0.0:
                    _drained = min(overguard_left, _left)
                    overguard_left -= _drained
                    _left -= _drained
                if _left > 0.0 and shield_left > 0.0:
                    _drained = min(shield_left, _left)
                    shield_left -= _drained
                    _left -= _drained
                if _left > 0.0 and health_left > 0.0:
                    _drained = min(health_left, _left)
                    health_left -= _drained
                    _left -= _drained
                step_non_dot += _nd_applied
                if overguard_left + shield_left + health_left <= 1e-12:
                    _settle_death(_fire_time)
            for _comp in range(_component_count):
                _remaining_pools = max(
                    overguard_left + shield_left + health_left, 0.0
                )
                if _remaining_pools <= 1e-12:
                    # 目标已在本攻击的早前组件中死亡：剩余组件 stale，
                    # 不能转杀重生目标（E02 合同，与 ledger 一致）。
                    stale_component_count += 1
                    continue
                _applied = min(_component_damage, _remaining_pools)
                _left = _applied
                if overguard_left > 0.0:
                    _drained = min(overguard_left, _left)
                    overguard_left -= _drained
                    _left -= _drained
                if _left > 0.0 and shield_left > 0.0:
                    _drained = min(shield_left, _left)
                    shield_left -= _drained
                    _left -= _drained
                if _left > 0.0 and health_left > 0.0:
                    _drained = min(health_left, _left)
                    health_left -= _drained
                    _left -= _drained
                step_direct += _applied
                if overguard_left + shield_left + health_left <= 1e-12:
                    # 死亡在攻击时刻即时结算（InstantRespawn）。
                    _settle_death(_fire_time)
        # 步末残余间隙：DoT 连续流量结算。
        gap = elapsed + dt - _cursor
        if gap > 1e-12 and dot_rate > 0.0:
            applied = _apply_continuous(dot_rate, gap)
            step_dot += applied
            if overguard_left + shield_left + health_left <= 1e-12:
                _settle_death(elapsed + dt)
        direct_total += step_direct
        dot_total += step_dot
        non_dot_total += step_non_dot
        max_kills_per_step = max(max_kills_per_step, step_kills)
        # 步末推进 ramp 时钟（本步无击杀时：整步时长累加；有击杀时
        # _settle_death 已把时钟设为「重生时刻到步末」，不再重复加）。
        if step_kills == 0:
            ramp_elapsed += dt

        # ── 触发源层数推进（emergent）──────────────────────────────────
        # on-kill 源按本步期望击杀数（步伤害 / 当前身体 EHP）获得层数；
        # on-hit/on-crit 按攻击数近似（每攻击一次命中）。带 duration 的
        # 衰减线性近似。击杀时 lose_one_and_reset 掉一层并刷新计时。
        _body_ehp = max(total_ehp_ref, 1e-9)
        # This is an *expected event count*, not a boolean.  A 250 ms slice
        # can legitimately contain several deaths now that attacks settle as
        # discrete events; the expectation uses the applied damage (which is
        # generation-capped, so the count cannot exceed attack-supported
        # kills + DoT-supported kills).
        _step_kill_expectation = max(
            (step_direct + step_dot + step_non_dot) / _body_ehp, 0.0
        )
        _attack_count = len(_attack_times)
        for spec in trigger_specs:
            kind = spec["kind"]
            if kind == "on-kill":
                event_rate = _step_kill_expectation
            elif kind in ("on-hit", "on-crit"):
                event_rate = _attack_count
            else:
                event_rate = 0.0
            gained = event_rate * spec["perEvent"]
            spec["currentStacks"] = min(spec["currentStacks"] + gained, spec["maxStacks"])
            if spec["duration"] > 0 and dt > 0:
                decay_fraction = min(dt / spec["duration"], 1.0)
                spec["currentStacks"] = max(spec["currentStacks"] * (1.0 - decay_fraction), 0.0)
            if spec["series"] is not None:
                spec["series"].append(round(spec["currentStacks"], 3))

        for k, v in levels.items():
            averaged[k] += v * dt
        if emit_timeline:
            timeline.append({
                "time": round(elapsed + dt, 4),
                "pool": pool,
                "overguard": round(overguard_left, 2),
                "shield": round(shield_left, 2),
                "health": round(health_left, 2),
                "stacks": {k: round(v, 2) for k, v in levels.items()},
                "triggerStacks": {
                    spec["id"]: round(spec["currentStacks"], 2) for spec in trigger_specs
                } if trigger_specs else None,
                "directDps": round(step_direct / dt, 2) if dt > 0 else 0.0,
                "dotDps": round(step_dot / dt, 2) if dt > 0 else 0.0,
                "stepDamage": round(step_direct + step_dot + step_non_dot, 2),
            })
        elapsed += dt

    if window > 0.0:
        for k in averaged:
            averaged[k] /= window

    total_window = direct_total + dot_total + non_dot_total
    total_ehp = total_overguard + total_shield + total_health
    # Kill score (wfsim UI.md): whole kills plus the fraction of the CURRENT
    # body's pools already drained — grows with the engagement, reported as a
    # per-minute rate (KPM) so different durations stay comparable.
    if total_ehp > 0.0:
        current_body_drained = (
            (total_overguard - overguard_left)
            + (total_shield - shield_left)
            + (total_health - health_left)
        ) / total_ehp
        kills_in_window = kills_count + min(current_body_drained, 1.0)
    else:
        kills_in_window = 0.0
    steady_counts = {
        key: min(
            max(float(procs.get(dtype) or 0.0) * proc_rate * duration * duration_scale, 0.0),
            cap,
        )
        for key, (dtype, duration, cap, _shared) in stack_specs.items()
    }

    return {
        "model": "windowed-stepped",
        "windowSeconds": window,
        "timeStep": step,
        "attacksPerSecond": rate,
        "statusEventsPerSecond": proc_rate,
        "averagedStacks": averaged,
        "steadyStacks": steady_counts,
        # emergent 口径状态：CO（对触发目标增伤）已按每步活异常类型数重算；
        # 触发源（赋能/镀层/灵化 on-kill）按 trigger_sources 参数模拟爬升。
        "emergent": {
            "conditionOverload": "per-step-live-types",
            "onKillStacks": "trigger-sources-simulated" if trigger_specs else "panel-assumed-max",
        },
        # 触发源层数折线（前端覆盖率图）：每个源的 per-step 层数序列。
        "triggerSeries": [
            {
                "id": spec["id"],
                "label": spec["label"],
                "kind": spec["kind"],
                "maxStacks": spec["maxStacks"],
                "series": spec["series"],
                "avgStacks": sum(spec["series"]) / len(spec["series"]) if spec["series"] else 0.0,
                "uptime": (
                    sum(1 for v in spec["series"] if v >= 1.0) / len(spec["series"])
                    if spec["series"]
                    else 0.0
                ),
            }
            for spec in trigger_specs
        ],
        "activePool": "overguard" if total_overguard > 0 else ("shield" if total_shield > 0 else "health"),
        "directWindow": direct_total,
        "dotWindow": dot_total,
        "nonDotWindow": non_dot_total,
        "totalWindowDamage": total_window,
        "windowDps": total_window / window if window > 0.0 else 0.0,
        "targetTotalEhp": total_ehp,
        "killsInWindow": kills_in_window,
        "killsPerMinute": kills_in_window * (60.0 / window) if window > 0.0 else 0.0,
        "killEvents": kills_count,
        "firstKillTime": first_kill_time,
        "minKillInterval": min_kill_interval,
        "maxKillsPerStep": max_kills_per_step,
        "targetGeneration": generation,
        "staleComponents": stale_component_count,
        "continuousKillEvents": True,
        # ── F01（审计修复）：模型版本升级 ──────────────────────────────
        # 主循环直伤现在按离散攻击事件结算（与 direct ledger 同一开火调
        # 度）；DoT 在攻击间隙按连续流量结算，目标代次生命周期完整（F04）。
        # eventModel 从 "hybrid-stepped-with-direct-ledger-diagnostic" 升级
        # 为 "hybrid-event-settled-v2"——直伤不再是「另算一份的诊断账本」。
        "eventModel": "hybrid-event-settled-v2",
        "directEventLedger": direct_event_ledger,
        "timeline": timeline,
        "perAttack": probe,
        "unsupported": sorted(set(probe.get("unsupported") or ())),
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
    if stats.radial_only:
        hit_multiplier = hit_critical_multiplier = 1.0
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
