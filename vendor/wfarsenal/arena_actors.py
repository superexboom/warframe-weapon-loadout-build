"""3D Arena Warframe survivability, Enemy AI spatial attacks, and Companion AI director.

Keeps neutral Arena runs (warframeContext=None and companionContext=None) 100%
untouched so existing replay eventHashes remain bit-identical.
"""

from __future__ import annotations

from collections import deque
from copy import copy
from functools import lru_cache
import gzip
import importlib.util
import json
import math
from typing import Any, Callable, Mapping

from . import ability_rotation
from . import arcane_runtime
from . import companion_loadout
from . import damage as dm
from .arena_combat import ArenaCombat, CappedPool, EPS, DURATIONS, StatusPresence
from .arena_scene import ROOT, distance

DEFAULT_EXCALIBUR_PORTRAIT = "/assets/warframes/portraits/Excalibur.png"

ARCANE_AVENGER_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/CritChanceOnDamage"
ARCANE_GUARDIAN_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/ArmourOnDamage"
ARCANE_GRACE_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/HealthRegenOnDamage"
ARCANE_AEGIS_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/GolemArcaneShieldRegenOnDamage"
ARCANE_BARRIER_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Defensive/InstantShieldOnDamage"
MOLT_EFFICIENCY_PATH = "/Lotus/Upgrades/CosmeticEnhancers/Zariman/WarframeOnShieldUptimePowerDuration"

FORCED_PROC_TO_DAMAGE_TYPE = {
    "PT_ELECTROCUTION": "DT_ELECTRICITY",
    "PT_IMMOLATION": "DT_FIRE",
    "PT_CHILLED": "DT_FREEZE",
    "PT_POISONED": "DT_POISON",
    "PT_BLEEDING": "DT_SLASH",
    "PT_MAGNETIZED": "DT_MAGNETIC",
    "PT_INFECTED": "DT_VIRAL",
    "PT_CAUSTIC_BURN": "DT_CORROSIVE",
    "PT_RADIATION": "DT_RADIATION",
    "PT_ASPHYXIATION": "DT_GAS",
    "PT_FLASHBANG": "DT_EXPLOSION",
}


def _add_y(p: tuple[float, float, float], dy: float) -> tuple[float, float, float]:
    return (p[0], p[1] + dy, p[2])


def _mix(a: tuple[float, float, float], b: tuple[float, float, float], k: float) -> tuple[float, float, float]:
    return (
        a[0] + (b[0] - a[0]) * k,
        a[1] + (b[1] - a[1]) * k,
        a[2] + (b[2] - a[2]) * k,
    )


def _lerp(lo: float, hi: float, u: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, u))


def _det_random(seed: int, index: int, stream: int) -> float:
    x = (seed ^ ((index + 1) * 0x9E3779B1) ^ ((stream + 1) * 0x85EBCA6B)) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967296.0


def _path_token(val: Any) -> str:
    return str(val or "").strip().replace("\\", "/").rstrip("/").casefold()


@lru_cache(maxsize=1)
def enemy_attacks_data() -> dict[str, Any]:
    path = ROOT / "data/arena/enemy-attacks.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _enemy_visual_catalog() -> Any:
    try:
        from enemy_assets import EnemyVisualCatalog  # type: ignore

        return EnemyVisualCatalog(ROOT)
    except ImportError:
        spec_path = ROOT / "enemy_assets.py"
        if not spec_path.is_file():
            return None
        spec = importlib.util.spec_from_file_location("_arena_enemy_assets", spec_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.EnemyVisualCatalog(ROOT)


def resolve_enemy_icon(enemy_path: str, explicit_map: Mapping[str, Any] | None = None) -> str | None:
    if isinstance(explicit_map, Mapping) and enemy_path in explicit_map:
        val = explicit_map.get(enemy_path)
        if isinstance(val, str) and val:
            return val
        if isinstance(val, Mapping) and isinstance(val.get("imageAsset"), str):
            return val["imageAsset"]
    cat = _enemy_visual_catalog()
    if cat is None:
        return None
    info = cat.get(enemy_path)
    return info.get("imageAsset") if isinstance(info, Mapping) else None


def cold_slow_multiplier(cold_stacks: float, overguard: float) -> float:
    """Warframe Cold (DT_FREEZE) 1..9 stack movement/attack speed multiplier.

    0 stacks -> 1.0 (no slow).
    1..9 stacks -> slow_frac = 0.50 + 0.05 * (min(stacks, cap) - 1),
    where cap = 4 (65% slow) while Overguard > 0, else 9 (90% slow).
    """
    if cold_stacks < 1.0 - 1e-6:
        return 1.0
    cap = 4.0 if overguard > EPS else 9.0
    eff = min(float(cold_stacks), cap)
    slow_frac = 0.50 + 0.05 * (eff - 1.0)
    return max(0.10, 1.0 - slow_frac)


def _eval_aim_graph(graph: Mapping[str, Any], dist: float) -> float:
    xs = graph.get("distance") or [0.0, 30.0]
    ys = graph.get("accuracy") or [1.0, 0.0]
    if not xs or not ys:
        return 1.0
    if dist <= float(xs[0]):
        return float(ys[0])
    for i in range(len(xs) - 1):
        x0, x1 = float(xs[i]), float(xs[i + 1])
        y0, y1 = float(ys[i]), float(ys[i + 1])
        if dist <= x1:
            if x1 - x0 <= 1e-9:
                return y1
            return y0 + (y1 - y0) * ((dist - x0) / (x1 - x0))
    return float(ys[-1])


def _eval_level_accuracy(table: list[Mapping[str, Any]], level: int) -> float:
    for row in table:
        if level <= int(row.get("maxLevel", 75)):
            return float(row.get("scale", 1.0))
    return float(table[-1].get("scale", 1.0)) if table else 1.0


def _eval_damage_curve(curves: Mapping[str, Any], curve_name: str, level: int, base_level: int = 1) -> float:
    diff = max(0.0, float(level) - float(base_level))
    if diff <= 0.0:
        return 1.0
    spec = curves.get(curve_name) or curves.get("scurve") or {}
    if spec.get("kind") == "power":
        mult = float(spec.get("multiplier", 0.015))
        exp = float(spec.get("exponent", 1.55))
        return 1.0 + mult * (diff ** exp)
    b0, b1 = (spec.get("blendRange") or [1.0, 25.0])[:2]
    low_m = float(spec.get("lowMultiplier", 0.015))
    low_e = float(spec.get("lowExponent", 1.75))
    high_m = float(spec.get("highMultiplier", 0.0075))
    high_e = float(spec.get("highExponent", 1.55))
    low_val = 1.0 + low_m * (diff ** low_e)
    high_val = 1.0 + high_m * (diff ** high_e)
    x = min(1.0, max(0.0, (diff - float(b0)) / max(1e-9, float(b1) - float(b0))))
    smooth = x * x * (3.0 - 2.0 * x)
    return (1.0 - smooth) * low_val + smooth * high_val


class WarframeArenaState:
    """TennoDamageController survivability & on-damaged Warframe arcanes in 3D Arena."""

    def __init__(self, warframe_context: Mapping[str, Any], scenario: Mapping[str, Any], seed: int):
        self.raw = warframe_context
        self.seed = int(seed)
        self._rng_index = 0

        frame = warframe_context.get("frame") or (warframe_context.get("weaponBridge") or {}).get("frame") or {}
        panel = warframe_context.get("finalPanel") or (warframe_context.get("weaponBridge") or {}).get("panel") or {}
        surv = warframe_context.get("survivability") or (warframe_context.get("weaponBridge") or {}).get("survivability") or {}

        self.frame_id = str(frame.get("id") or frame.get("path") or "Excalibur")
        self.name_en = str(frame.get("nameEn") or self.frame_id)
        self.name_zh = str(frame.get("nameZh") or self.name_en)
        self.portrait_asset = str(frame.get("portraitAsset") or frame.get("iconAsset") or DEFAULT_EXCALIBUR_PORTRAIT)

        strict_survival = bool(scenario.get("strictSurvival", False))
        raw_immortal = warframe_context.get("immortalBenchmark", True)
        self.immortal_benchmark = bool(raw_immortal) and not strict_survival
        self.terminated = False

        self.arcane_persistence = bool(surv.get("arcanePersistence", False))
        self.catalyzing_shields = bool(surv.get("catalyzingShields", False))
        self.max_health = max(1.0, float(panel.get("health") or 300.0))
        self.health = self.max_health
        self.max_shield = 0.0 if self.arcane_persistence else max(0.0, float(panel.get("shield") or 0.0))
        self.shield = self.max_shield
        self.peak_shield = self.max_shield
        self.max_overshield = 1200.0 if self.max_shield > 0.0 else 0.0
        self.overshield = min(self.max_overshield, max(0.0, float(warframe_context.get("initialOvershield") or 0.0)))
        self.overguard = max(0.0, float(warframe_context.get("initialOverguard") or 0.0))
        self.base_armor = max(0.0, float(panel.get("armor") if panel.get("armor") is not None else (panel.get("armour") or 0.0)))
        self.max_energy = max(0.0, float(panel.get("energy") or 100.0))
        self.energy = self.max_energy
        self.passive_health_regen = max(0.0, float(panel.get("healthRegen") or 0.0))

        self.shield_gate_full_seconds = float(
            surv.get("shieldGateSeconds")
            or (1.33 if self.catalyzing_shields else (0.33 + 2.17 * (min(1.0, self.max_shield / 1150.0) ** 0.65) if self.max_shield > 0 else 0.0))
        )
        self.shield_recharge_rate = float(
            surv.get("shieldRechargeRate")
            if surv.get("shieldRechargeRate") is not None
            else ((15.0 + 0.05 * self.max_shield) if self.max_shield > 0 else 0.0)
        )
        self.delay_partial = float(surv.get("shieldRechargeDelay") or 1.0)
        self.delay_depleted = float(surv.get("shieldDepletedDelay") or 4.0)
        self.damage_cap_per_second: float | None = (
            float(surv["damageCapPerSecond"]) if surv.get("damageCapPerSecond") is not None else None
        )
        self.self_damage_on_kill = max(0.0, float(surv.get("selfDamageOnKill") or 0.0))
        self.has_adaptation = bool(surv.get("hasAdaptation", False))
        self.adaptation_max_dr = float(surv.get("adaptationMaxDr") or (0.90 if self.has_adaptation else 0.0))
        self.has_rolling_guard = bool(surv.get("hasRollingGuard", False))
        self.status_immune = bool(surv.get("statusImmune", False))

        # Parse equipped Warframe arcanes across weaponBridge.arcanes / arcanes / selected.arcanes
        arcane_ranks: dict[str, int] = {}
        bridge_arcanes = (warframe_context.get("weaponBridge") or {}).get("arcanes") or ()
        for item in bridge_arcanes:
            if isinstance(item, Mapping) and item.get("path"):
                arcane_ranks[_path_token(item["path"])] = int(item.get("rank", 5))
        for item in warframe_context.get("arcanes") or ():
            if isinstance(item, Mapping) and item.get("path"):
                arcane_ranks.setdefault(_path_token(item["path"]), int(item.get("rank", 5)))
            elif isinstance(item, str) and item:
                arcane_ranks.setdefault(_path_token(item), 5)
        for item in (warframe_context.get("selected") or {}).get("arcanes") or ():
            if isinstance(item, str) and item:
                arcane_ranks.setdefault(_path_token(item), 5)

        def _find_arcane(*tokens: str) -> int | None:
            for tok in tokens:
                pt = _path_token(tok)
                if pt in arcane_ranks:
                    return arcane_ranks[pt]
                for k, r in arcane_ranks.items():
                    if k.endswith("/" + pt) or k == pt:
                        return r
            return None

        av_rank = _find_arcane(ARCANE_AVENGER_PATH, "critchanceondamage", "arcane_avenger")
        self.avenger_equipped = av_rank is not None
        self.avenger_chance = 0.035 * ((av_rank or 0) + 1) if self.avenger_equipped else 0.0
        self.avenger_crit_bonus = 0.075 * ((av_rank or 0) + 1) if self.avenger_equipped else 0.0
        self.avenger_duration = 2.0 * ((av_rank or 0) + 1) if self.avenger_equipped else 0.0
        self.avenger_until = -math.inf
        self.avenger_active_seconds = 0.0

        gd_rank = _find_arcane(ARCANE_GUARDIAN_PATH, "armourondamage", "arcane_guardian")
        self.guardian_equipped = gd_rank is not None
        self.guardian_chance = 0.025 * ((gd_rank or 0) + 1) if self.guardian_equipped else 0.0
        self.guardian_armor_bonus = 150.0 * ((gd_rank or 0) + 1) if self.guardian_equipped else 0.0
        self.guardian_duration = 20.0 if self.guardian_equipped else 0.0
        self.guardian_until = -math.inf
        self.guardian_active_seconds = 0.0

        gr_rank = _find_arcane(ARCANE_GRACE_PATH, "healthregenondamage", "arcane_grace")
        self.grace_equipped = gr_rank is not None
        self.grace_chance = 0.015 * ((gr_rank or 0) + 1) if self.grace_equipped else 0.0
        self.grace_pct_per_sec = 0.01 * ((gr_rank or 0) + 1) if self.grace_equipped else 0.0
        self.grace_duration = 1.5 * ((gr_rank or 0) + 1) if self.grace_equipped else 0.0
        self.grace_until = -math.inf

        ae_rank = _find_arcane(ARCANE_AEGIS_PATH, "golemarcaneshieldregenondamage", "arcane_aegis")
        self.aegis_equipped = ae_rank is not None
        self.aegis_chance = 0.03 if self.aegis_equipped else 0.0
        self.aegis_pct_per_sec = 0.05 * ((ae_rank or 0) + 1) if self.aegis_equipped else 0.0
        self.aegis_duration = 2.0 * ((ae_rank or 0) + 1) if self.aegis_equipped else 0.0
        self.aegis_until = -math.inf

        ba_rank = _find_arcane(ARCANE_BARRIER_PATH, "instantshieldondamage", "arcane_barrier")
        self.barrier_equipped = ba_rank is not None
        self.barrier_chance = 0.01 * ((ba_rank or 0) + 1) if self.barrier_equipped else 0.0
        self.barrier_cd_until = -math.inf

        me_rank = _find_arcane(MOLT_EFFICIENCY_PATH, "warframeonshielduptimepowerduration", "molt_efficiency")
        self.molt_efficiency_equipped = me_rank is not None and self.max_shield > 0.0
        self.molt_efficiency_rate = 0.06 if self.molt_efficiency_equipped else 0.0
        self.molt_efficiency_max = 0.06 * ((me_rank or 0) + 1) if self.molt_efficiency_equipped else 0.0
        self.molt_efficiency_bonus = 0.0

        self.shield_depleted = self.max_shield > 0.0 and self.shield <= EPS
        self.last_damaged_at = -math.inf
        self.last_step_t = 0.0
        self.invuln_until = -math.inf
        self.rolling_guard_cd_until = -math.inf
        self.adaptation_stacks: dict[str, tuple[int, float]] = {}
        self._persistence_window_start = 0.0
        self._persistence_damage_in_window = 0.0
        self._synced_fortifier_og = 0.0

        # Optional Warframe Realistic Ability Rotation & Orb Economy
        self.ability_ranges: list[dict[str, Any]] = list(
            warframe_context.get("abilityRanges") or ()
        )
        self.nuke_preview: Mapping[str, Any] | None = (
            warframe_context.get("nukePreview")
            if isinstance(warframe_context.get("nukePreview"), Mapping)
            else None
        )
        self.dynamic_ability_effects: list[dict[str, Any]] = list(
            warframe_context.get("dynamicAbilityEffects") or ()
        )
        rot_cfg = dict(ability_rotation.parse_rotation_config(warframe_context))
        if scenario.get("arbucepEmpowered") is not None:
            rot_cfg["arbucepEmpowered"] = bool(scenario.get("arbucepEmpowered"))
        if scenario.get("combatStyle") in ("hybrid_nuke", "ability_only"):
            rot_cfg["enabled"] = True
        self.rotation: ability_rotation.WarframeRotationSimulator | None = None
        if rot_cfg.get("enabled"):
            self.rotation = ability_rotation.WarframeRotationSimulator(
                warframe_context,
                uncond_warframe_result=warframe_context.get("uncondWarframeResult"),
                active_ability_ids=warframe_context.get("activeAbilities") or (),
                companion_eval=warframe_context.get("companionEval"),
                rotation_config=rot_cfg,
                seed=self.seed,
                on_shield_restore=self._on_rotation_shield_restore,
                on_health_restore=self._on_rotation_health_restore,
            )
            comp_eval_raw = warframe_context.get("companionEval")
            if isinstance(comp_eval_raw, Mapping) and str((comp_eval_raw.get("companion") or {}).get("category") or "") != "beast":
                # Robotic precepts in 3D Arena fire spatially via CompanionArenaDirector._step_precepts
                self.rotation.next_companion_precept_at = math.inf
            self.energy = self.rotation.energy

        # Telemetry & Synergy counters
        self.damage_taken = 0.0
        self.hits_taken = 0
        self.evaded_hits = 0
        self.shield_breaks = 0
        self.shield_gates_triggered = 0
        self.downed_count = 0
        self.first_downed_at: float | None = None
        self.combat_discipline_triggers = 0
        self.frames: list[list[Any]] = []
        self.record_frame(0.0)

    def _on_rotation_shield_restore(self, amount: float) -> None:
        if amount <= 0.0 or self.max_shield <= 0.0 or self.arcane_persistence or self.terminated:
            return
        room = max(0.0, self.max_shield - self.shield)
        to_sh = min(room, amount)
        self.shield += to_sh
        self.peak_shield = max(self.peak_shield, self.shield)
        if self.shield > EPS:
            self.shield_depleted = False
        rem = amount - to_sh
        if rem > 0.0 and self.max_overshield > 0.0:
            self.overshield = min(self.max_overshield, self.overshield + rem)

    def _on_rotation_health_restore(self, heal_amount: float, max_hp_delta: float) -> None:
        if self.terminated:
            return
        if max_hp_delta > 0.0:
            self.max_health += max_hp_delta
        if heal_amount > 0.0:
            self.health = min(self.max_health, self.health + heal_amount)

    def _rng(self) -> float:
        val = _det_random(self.seed, self._rng_index, 31)
        self._rng_index += 1
        return val

    def is_avenger_active(self, t: float) -> bool:
        return self.avenger_equipped and t < self.avenger_until - 1e-9

    def is_guardian_active(self, t: float) -> bool:
        return self.guardian_equipped and t < self.guardian_until - 1e-9

    def current_armor(self, t: float) -> float:
        hc_bonus = (
            self.rotation.health_conversion_stacks * self.rotation.health_conversion_armor
            if self.rotation is not None
            else 0.0
        )
        return self.base_armor + hc_bonus + (self.guardian_armor_bonus if self.is_guardian_active(t) else 0.0)

    def is_weapon_locked(self, t: float) -> bool:
        return self.rotation is not None and self.rotation.is_weapon_locked(t)

    def weapon_locked_until(self) -> float:
        return self.rotation.weapon_locked_until if self.rotation is not None else -math.inf

    def next_event_time(self) -> float:
        return self.rotation.next_event_time() if self.rotation is not None else math.inf

    def on_companion_precept(self, t: float, *, electric: bool = False) -> None:
        if self.rotation is not None and not self.terminated:
            self.advance(t)
            self.rotation.on_companion_precept(t, electric=electric)
            self.energy = self.rotation.energy

    def on_enemy_kill_orbs(
        self,
        t: float,
        *,
        is_eximus: bool = False,
        companion_damaged: bool | None = None,
        headshot: bool = False,
    ) -> None:
        if self.rotation is not None and not self.terminated:
            self.advance(t)
            self.rotation.on_enemy_kill(
                t,
                is_eximus=is_eximus,
                companion_damaged=companion_damaged,
                headshot=headshot,
            )
            self.energy = self.rotation.energy

    def max_adaptation_dr(self, t: float) -> float:
        if not self.has_adaptation or not self.adaptation_stacks:
            return 0.0
        best = 0
        for stacks, exp in self.adaptation_stacks.values():
            if exp > t:
                best = max(best, stacks)
        return min(self.adaptation_max_dr, best * 0.10)

    def advance(self, t: float, combat: ArenaCombat | None = None) -> None:
        t = float(t)
        dt = t - self.last_step_t
        if dt > 0.0:
            if self.avenger_until > self.last_step_t:
                self.avenger_active_seconds += max(0.0, min(t, self.avenger_until) - self.last_step_t)
            if self.guardian_until > self.last_step_t:
                self.guardian_active_seconds += max(0.0, min(t, self.guardian_until) - self.last_step_t)

            # Health regeneration (passive + Arcane Grace)
            hp_regen = self.passive_health_regen
            if self.grace_equipped and t < self.grace_until:
                hp_regen += self.grace_pct_per_sec * self.max_health
            if hp_regen > 0.0 and self.health < self.max_health and not self.terminated:
                self.health = min(self.max_health, self.health + hp_regen * dt)

            # Molt Efficiency ramp while shield > 0
            if self.molt_efficiency_equipped:
                if self.shield + self.overshield > EPS:
                    self.molt_efficiency_bonus = min(
                        self.molt_efficiency_max,
                        self.molt_efficiency_bonus + self.molt_efficiency_rate * dt,
                    )
                else:
                    self.molt_efficiency_bonus = 0.0

            # Tenno Shield Recharge
            if self.max_shield > 0.0 and self.shield < self.max_shield and not self.arcane_persistence and not self.terminated:
                if self.aegis_equipped and t < self.aegis_until:
                    rate = self.shield_recharge_rate + self.aegis_pct_per_sec * self.max_shield
                    self.shield = min(self.max_shield, self.shield + rate * dt)
                    self.peak_shield = max(self.peak_shield, self.shield)
                    if self.shield > EPS:
                        self.shield_depleted = False
                else:
                    delay = self.delay_depleted if self.shield_depleted else self.delay_partial
                    ready = self.last_damaged_at + delay
                    if t > ready:
                        active_dt = min(dt, t - max(self.last_step_t, ready))
                        if active_dt > 0.0:
                            self.shield = min(self.max_shield, self.shield + self.shield_recharge_rate * active_dt)
                            self.peak_shield = max(self.peak_shield, self.shield)
                            if self.shield > EPS:
                                self.shield_depleted = False

            self.last_step_t = t

        if self.rotation is not None and not self.terminated:
            self.rotation.health = self.health
            self.rotation.max_health = self.max_health
            self.rotation.shield = self.shield
            self.rotation.overshield = self.overshield
            self.rotation.molt_efficiency_bonus = self.molt_efficiency_bonus
            self.rotation.advance(t)
            self.energy = self.rotation.energy

        if combat is not None and combat.self_overguard > self._synced_fortifier_og + EPS:
            gain = combat.self_overguard - self._synced_fortifier_og
            self._synced_fortifier_og = combat.self_overguard
            self.overguard = min(15000.0, self.overguard + gain)

    def _roll_on_damaged_arcanes(self, t: float, *, sh_dmg: float, hp_dmg: float) -> None:
        if self.avenger_equipped and self._rng() < self.avenger_chance:
            self.avenger_until = t + self.avenger_duration
        if self.guardian_equipped and self._rng() < self.guardian_chance:
            self.guardian_until = t + self.guardian_duration
        if hp_dmg > 0.0 and self.grace_equipped and self._rng() < self.grace_chance:
            self.grace_until = t + self.grace_duration
        if sh_dmg > 0.0:
            if self.aegis_equipped and self._rng() < self.aegis_chance:
                self.aegis_until = t + self.aegis_duration
            if self.barrier_equipped and t >= self.barrier_cd_until and self._rng() < self.barrier_chance:
                self.shield = self.max_shield
                self.peak_shield = self.max_shield
                self.shield_depleted = False
                self.barrier_cd_until = t + 6.0

    def on_player_kill(self, t: float, combat: ArenaCombat | None = None) -> None:
        if self.self_damage_on_kill <= 0.0 or self.terminated:
            return
        self.advance(t, combat)
        if self.overguard > EPS:
            return
        loss = min(max(0.0, self.health - 2.0), self.self_damage_on_kill)
        self.health = max(2.0, self.health - self.self_damage_on_kill)
        self.damage_taken += loss
        self.combat_discipline_triggers += 1
        self._roll_on_damaged_arcanes(t, sh_dmg=0.0, hp_dmg=max(loss, 1e-6))

    def take_enemy_hit(
        self,
        t: float,
        damage_vector: Mapping[str, float],
        *,
        combat: ArenaCombat | None = None,
        dodge_mult: float = 1.0,
    ) -> float:
        if self.terminated:
            return 0.0
        if combat is not None:
            t = max(float(t), float(getattr(combat, "t", t)))
        self.advance(t, combat)
        self.hits_taken += 1

        # Shield-gate / Overguard-gate / Rolling Guard invulnerability window:
        # 0 pool damage and invulnerable hits do NOT trigger OnDamageCondition.
        if t < self.invuln_until - 1e-9:
            return 0.0

        if self.has_adaptation:
            self.adaptation_stacks = {
                dt: (cnt, exp) for dt, (cnt, exp) in self.adaptation_stacks.items() if exp > t
            }
            vec = {
                dt: amt * dodge_mult * (1.0 - min(self.adaptation_max_dr, (self.adaptation_stacks.get(dt, (0, 0.0))[0]) * 0.10))
                for dt, amt in damage_vector.items()
                if amt > 0.0
            }
            if damage_vector:
                dom_dt = max(damage_vector, key=lambda k: damage_vector[k])
                if damage_vector[dom_dt] > 0.0:
                    prev_cnt = self.adaptation_stacks.get(dom_dt, (0, 0.0))[0]
                    self.adaptation_stacks[dom_dt] = (min(9, prev_cnt + 1), t + 20.0)
        else:
            vec = {dt: amt * dodge_mult for dt, amt in damage_vector.items() if amt > 0.0}

        total_raw = sum(vec.values())
        if total_raw <= EPS:
            return 0.0

        og_dmg = 0.0
        sh_dmg = 0.0
        hp_dmg = 0.0

        # 1. Overguard pool (0.5s gate on break, blocks Toxin too while active)
        if self.overguard > EPS:
            if total_raw < self.overguard - EPS:
                self.overguard -= total_raw
                og_dmg = total_raw
            else:
                og_dmg = self.overguard
                self.overguard = 0.0
                self.invuln_until = max(self.invuln_until, t + 0.50)
                if combat is not None:
                    combat.actor_event("on-self-overguard-broken", t)
            vec = {}

        # 2. Overshield + Shield pool (50% innate Tenno Shield DR; Toxin bypasses to Health)
        if vec and (self.shield + self.overshield > EPS):
            toxin_raw = vec.get("DT_POISON", 0.0)
            non_toxin_raw = sum(v for k, v in vec.items() if k != "DT_POISON")
            eff_sh = non_toxin_raw * 0.50
            if eff_sh > EPS:
                self.last_damaged_at = t
                if combat is not None:
                    combat.actor_event("on-self-shield-hit", t)
                avail_sh = self.overshield + self.shield
                if eff_sh < avail_sh - EPS:
                    take_os = min(self.overshield, eff_sh)
                    self.overshield -= take_os
                    self.shield = max(0.0, self.shield - (eff_sh - take_os))
                    sh_dmg = eff_sh
                else:
                    sh_dmg = avail_sh
                    had_shield = self.shield > EPS
                    self.overshield = 0.0
                    self.shield = 0.0
                    self.shield_depleted = True
                    self.molt_efficiency_bonus = 0.0
                    if had_shield:
                        self.shield_breaks += 1
                        self.shield_gates_triggered += 1
                        if self.catalyzing_shields:
                            ratio = min(1.0, self.peak_shield / max(1e-6, self.max_shield))
                            gate_dur = max(0.33, self.shield_gate_full_seconds * ratio)
                        else:
                            gate_dur = 0.33 + 2.17 * (min(1.0, self.peak_shield / 1150.0) ** 0.65)
                        self.peak_shield = 0.0
                        self.invuln_until = max(self.invuln_until, t + gate_dur)
                        if combat is not None:
                            combat.actor_event("on-self-shield-broken", t)
                        if self.has_rolling_guard and t >= self.rolling_guard_cd_until:
                            self.invuln_until = max(self.invuln_until, t + 3.0)
                            self.rolling_guard_cd_until = t + 7.0
                        self.record_frame(t)
            vec = {"DT_POISON": toxin_raw} if toxin_raw > EPS else {}

        # 3. Health pool (Armor DR + Arcane Persistence cap)
        if vec:
            raw_hp = sum(vec.values())
            if raw_hp > EPS:
                self.last_damaged_at = t
                dyn_armor = self.current_armor(t)
                armor_mult = 300.0 / (300.0 + max(0.0, dyn_armor))
                eff_hp = raw_hp * armor_mult
                if self.damage_cap_per_second is not None and dyn_armor > 700.0:
                    if t - self._persistence_window_start >= 1.0:
                        self._persistence_window_start = t
                        self._persistence_damage_in_window = 0.0
                    room = max(0.0, self.damage_cap_per_second - self._persistence_damage_in_window)
                    eff_hp = min(eff_hp, room)
                    self._persistence_damage_in_window += eff_hp
                hp_dmg = eff_hp
                self.health -= eff_hp
                if self.rotation is not None and hp_dmg > EPS:
                    self.rotation.health = max(0.0, self.health)
                    self.rotation.on_health_damage_taken(hp_dmg, t)
                    self.energy = self.rotation.energy

        applied = og_dmg + sh_dmg + hp_dmg
        self.damage_taken += applied
        if applied > EPS:
            self._roll_on_damaged_arcanes(t, sh_dmg=sh_dmg, hp_dmg=hp_dmg)

        if self.health <= EPS:
            self.downed_count += 1
            if self.first_downed_at is None:
                self.first_downed_at = round(t, 6)
            if self.immortal_benchmark:
                self.health = self.max_health
                self.shield = self.max_shield
                self.peak_shield = self.max_shield
                self.shield_depleted = False
                self.invuln_until = max(self.invuln_until, t + 1.5)
                self.record_frame(t)
            else:
                self.health = 0.0
                self.terminated = True
                self.record_frame(t)

        return applied

    def record_frame(self, t: float) -> None:
        row = [
            round(float(t), 4),
            round(max(0.0, self.health), 2),
            round(max(0.0, self.shield), 2),
            round(max(0.0, self.overshield), 2),
            round(max(0.0, self.overguard), 2),
            1 if self.is_avenger_active(t) else 0,
            round(self.max_adaptation_dr(t), 2),
            round(max(0.0, self.energy), 1),
            1 if (self.rotation is not None and self.rotation.is_casting(t)) else 0,
        ]
        if self.frames and abs(self.frames[-1][0] - row[0]) < 1e-5:
            self.frames[-1] = row
        else:
            self.frames.append(row)

    def avenger_uptime_ratio(self, total_t: float) -> float:
        if total_t <= EPS:
            return 0.0
        return min(1.0, self.avenger_active_seconds / total_t)

    def guardian_uptime_ratio(self, total_t: float) -> float:
        if total_t <= EPS:
            return 0.0
        return min(1.0, self.guardian_active_seconds / total_t)

    def stats_payload(self, total_t: float) -> dict[str, Any]:
        self.advance(total_t)
        return {
            "damageTaken": round(self.damage_taken, 3),
            "hitsTaken": self.hits_taken,
            "evadedHits": self.evaded_hits,
            "shieldBreaks": self.shield_breaks,
            "shieldGatesTriggered": self.shield_gates_triggered,
            "downedCount": self.downed_count,
            "firstDownedAt": self.first_downed_at,
            "avengerUptimeRatio": round(self.avenger_uptime_ratio(total_t), 6),
            "guardianUptimeRatio": round(self.guardian_uptime_ratio(total_t), 6),
            "combatDisciplineTriggers": self.combat_discipline_triggers,
            "abilityRotation": (
                self.rotation.summary_payload(total_t) if self.rotation is not None else None
            ),
        }

    def visuals_payload(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "frameId": self.frame_id,
            "nameZh": self.name_zh,
            "nameEn": self.name_en,
            "portraitAsset": self.portrait_asset or DEFAULT_EXCALIBUR_PORTRAIT,
            "maxHealth": round(self.max_health, 2),
            "maxShield": round(self.max_shield, 2),
            "maxOvershield": int(round(self.max_overshield or 1200)),
            "maxEnergy": round(self.max_energy, 2),
            "armor": round(self.base_armor, 2),
            "abilityRotationEnabled": self.rotation is not None,
            "abilityRanges": self.ability_ranges,
            "frames": self.frames,
        }


class EnemyAttackDirector:
    """Native NPC weapon/melee spatial attacks from data/arena/enemy-attacks.json.gz."""

    def __init__(self, seed: int):
        self.seed = int(seed)
        self.data = enemy_attacks_data()
        self.curves = self.data.get("levelCurves") or {}
        self.aim_graphs = self.data.get("aimGraphs") or {}
        self.level_acc_table = self.data.get("levelAccuracyScale") or []
        self.acc_mods = self.data.get("npcAccuracyMods") or {}
        self.eximus_mult = float(self.data.get("eximusDamageMultiplier", 1.2))
        self.states: dict[int, dict[str, Any]] = {}
        self.pending_projectiles: list[tuple[float, dict[str, float]]] = []
        self.visual_shots: list[list[float]] = []

    def _rng(self, actor_id: int, state: dict[str, Any]) -> float:
        idx = state["rng_idx"]
        state["rng_idx"] = idx + 1
        return _det_random(self.seed, actor_id * 4099 + idx, 53)

    def register_actor(self, actor: Any, enemy_record: Mapping[str, Any], level: int, t: float) -> None:
        if actor.drone:
            return
        avatar_path = str(enemy_record.get("path") or "")
        agent_path = str((actor.tape or {}).get("sourceAgent") or "")
        faction = str(enemy_record.get("faction") or "Grineer")
        enemies_db = self.data.get("enemies") or {}
        fallbacks = self.data.get("factionFallbacks") or {}
        prof = (
            enemies_db.get(avatar_path)
            or enemies_db.get(agent_path)
            or fallbacks.get(faction)
            or fallbacks.get("Grineer")
        )
        if not isinstance(prof, Mapping) or prof.get("mode") == "none":
            return
        base_dmg = float(prof.get("baseDamage") or 0.0)
        fire_rate = float(prof.get("fireRate") or 0.0)
        if base_dmg <= 0.0 or fire_rate <= 0.0:
            return

        base_level = int(enemy_record.get("baseLevel") or 1)
        curve_mult = _eval_damage_curve(self.curves, str(prof.get("damageCurve") or "scurve"), level, base_level=base_level)
        if (actor.tape or {}).get("eximus"):
            curve_mult *= self.eximus_mult
        scaled_dmg = base_dmg * curve_mult
        raw_types = prof.get("damageTypes") or {"DT_IMPACT": 1.0}
        dmg_vec = {str(dt): scaled_dmg * float(w) for dt, w in raw_types.items() if float(w) > 0.0}

        st: dict[str, Any] = {
            "profile": prof,
            "level": int(level),
            "damageVector": dmg_vec,
            "rng_idx": 0,
            "ammo": int(prof.get("clipSize") or 0),
        }
        r0 = self._rng(actor.id, st)
        r1 = self._rng(actor.id, st)
        r2 = self._rng(actor.id, st)
        att_seg = prof.get("attackSegment") or [1.5, 3.0]
        bt = prof.get("burstTime") or [0.0, 0.0]
        st["ready_at"] = t + 0.10 + 0.35 * r0
        st["segment_end"] = st["ready_at"] + _lerp(float(att_seg[0]), float(att_seg[1]), r1)
        st["burst_end"] = (
            st["ready_at"] + _lerp(float(bt[0]), float(bt[1]), r2) if float(bt[1]) > 0.0 else math.inf
        )
        self.states[actor.id] = st

    def _player_evasion_multiplier(self, player: Any) -> float:
        edge = getattr(player, "edge", None)
        if not edge:
            return 1.0
        kind = edge.get("kind") or ""
        mult = 1.0
        if kind in ("bullet-jump", "drop", "jump-down"):
            mult *= max(0.05, 1.0 - float(self.acc_mods.get("dodgeAirAdjust", 0.60)))
        spd = float(edge.get("speed") or 0.0)
        v_range = self.acc_mods.get("velocityRange") or [8.25, 12.0]
        v0, v1 = float(v_range[0]), float(v_range[1])
        v_max = float(self.acc_mods.get("velocityMaxAdjust", 0.50))
        if spd > v0:
            frac = min(1.0, (spd - v0) / max(1e-6, v1 - v0))
            mult *= max(0.10, 1.0 - v_max * frac)
        elif spd > 1.0:
            mult *= 0.88
        return mult

    def step(self, world: Any, wf_state: WarframeArenaState, t: float) -> None:
        if wf_state.terminated:
            return
        wf_state.advance(t, world.combat)

        # 1. Deliver due in-flight enemy projectiles
        if self.pending_projectiles:
            remaining = []
            for arrive_t, vec in self.pending_projectiles:
                if arrive_t <= t + EPS:
                    wf_state.take_enemy_hit(t, vec, combat=world.combat)
                    if wf_state.terminated:
                        return
                else:
                    remaining.append((arrive_t, vec))
            self.pending_projectiles = remaining

        if not world.live:
            return

        wf_chest = _add_y(world.player.pos, 1.15)
        evasion = self._player_evasion_multiplier(world.player)

        for actor in world.live:
            if actor.dead or actor.drone:
                continue
            st = self.states.get(actor.id)
            if st is None or t < st["ready_at"] - EPS:
                continue
            victim_state = world.combat.targets.get(actor.id)
            if victim_state is None or not victim_state.alive or victim_state.frozen_until > t:
                continue

            prof = st["profile"]
            mode = prof.get("mode", "ranged")
            eff_range = float(prof.get("meleeRange") or 2.5) if mode == "melee" else float(prof.get("maxRange") or 40.0)
            enemy_eye = _add_y(actor.pos, 1.45)
            dist = distance(enemy_eye, wf_chest)
            if dist > eff_range:
                continue

            # Segment & reload & burst pause gates before paying raycast or after visibility check
            if t >= st["segment_end"]:
                wait_seg = prof.get("waitSegment") or [0.5, 1.5]
                att_seg = prof.get("attackSegment") or [1.5, 3.0]
                wait_d = _lerp(float(wait_seg[0]), float(wait_seg[1]), self._rng(actor.id, st))
                st["ready_at"] = t + max(0.1, wait_d)
                st["segment_end"] = st["ready_at"] + _lerp(float(att_seg[0]), float(att_seg[1]), self._rng(actor.id, st))
                continue

            clip_size = int(prof.get("clipSize") or 0)
            if mode == "ranged" and clip_size > 0 and st["ammo"] <= 0:
                st["ammo"] = clip_size
                st["ready_at"] = t + max(0.2, float(prof.get("reloadTime") or 2.0))
                continue

            bp = prof.get("burstPauseTime") or [0.0, 0.0]
            bt = prof.get("burstTime") or [0.0, 0.0]
            if float(bt[1]) > 0.0 and t >= st["burst_end"]:
                pause_d = _lerp(float(bp[0]), float(bp[1]), self._rng(actor.id, st))
                st["ready_at"] = t + max(0.05, pause_d)
                st["burst_end"] = st["ready_at"] + _lerp(float(bt[0]), float(bt[1]), self._rng(actor.id, st))
                continue

            if not world.scene.visible(enemy_eye, wf_chest):
                st["ready_at"] = t + 0.20
                continue

            # Fire attack!
            if mode == "ranged" and clip_size > 0:
                st["ammo"] -= 1
            cold_cnt = world.combat._count(victim_state, "DT_FREEZE", t)
            rate_slow = cold_slow_multiplier(cold_cnt, victim_state.overguard)
            fire_rate = max(0.05, float(prof.get("fireRate") or 1.0) * rate_slow)
            st["ready_at"] = t + (1.0 / fire_rate)

            bhc = prof.get("baseHitChance") or [0.65, 1.0]
            base_hc = _lerp(float(bhc[0]), float(bhc[1]), self._rng(actor.id, st))
            lvl_acc = _eval_level_accuracy(self.level_acc_table, st["level"])
            graph = self.aim_graphs.get(str(prof.get("aimGraph") or "medium")) or {}
            aim_acc = 1.0 if (mode == "melee" and dist <= eff_range) else _eval_aim_graph(graph, dist)
            hit_prob = max(0.0, min(1.0, base_hc * lvl_acc * aim_acc * evasion))

            puncture_cnt = victim_state.pooled["DT_PUNCTURE"].stats()[1]
            punc_mult = 1.0
            if puncture_cnt > EPS:
                red = 0.40 * puncture_cnt if puncture_cnt < 1.0 else min(0.80, 0.40 + 0.10 * (puncture_cnt - 1.0))
                punc_mult = max(0.20, 1.0 - red)

            hit_landed = self._rng(actor.id, st) <= hit_prob
            if len(self.visual_shots) < 2000:
                self.visual_shots.append([
                    round(t, 4),
                    round(enemy_eye[0], 3),
                    round(enemy_eye[1], 3),
                    round(enemy_eye[2], 3),
                    round(wf_chest[0], 3),
                    round(wf_chest[1], 3),
                    round(wf_chest[2], 3),
                    1 if hit_landed else 0,
                ])

            if not hit_landed:
                wf_state.evaded_hits += 1
                continue

            vec = (
                {dt: amt * punc_mult for dt, amt in st["damageVector"].items()}
                if punc_mult != 1.0
                else st["damageVector"]
            )
            proj_spd = float(prof.get("projectileSpeed") or 0.0)
            flight_dt = (dist / proj_spd) if (mode == "ranged" and proj_spd > 0.0) else 0.0
            if flight_dt <= 0.05:
                wf_state.take_enemy_hit(t, vec, combat=world.combat)
                if wf_state.terminated:
                    return
            else:
                self.pending_projectiles.append((t + flight_dt, dict(vec)))


class CompanionArenaDirector:
    """Robotic & Beast Companion spatial follower, targeting, shooting, and Bond synergies."""

    def __init__(
        self,
        companion_context: Mapping[str, Any],
        world_context: Mapping[str, Any],
        player_combat: ArenaCombat,
        player_start_pos: tuple[float, float, float],
        seed: int,
    ):
        self.raw = companion_context
        self.seed = int(seed)
        self._rng_idx = 0

        evaluation = companion_context.get("evaluation") or companion_context
        self.evaluation = evaluation
        comp_meta = evaluation.get("companion") or {}
        stats_meta = evaluation.get("stats") or {}
        self.weapon_meta = evaluation.get("weapon")
        self.player_bridge = evaluation.get("playerBridge") or {}
        self.attack_profile = evaluation.get("attackProfile") or {}

        self.category = str(comp_meta.get("category") or self.attack_profile.get("category") or "robotic")
        self.kind = str(comp_meta.get("kind") or "sentinel")
        self.name_en = str(comp_meta.get("nameEn") or "")
        self.name_zh = str(comp_meta.get("nameZh") or self.name_en)
        self.portrait_asset = comp_meta.get("portraitAsset")
        self.weapon_name_zh = (
            (self.weapon_meta.get("nameZh") or self.weapon_meta.get("nameEn"))
            if isinstance(self.weapon_meta, Mapping)
            else None
        )
        self.weapon_asset = (
            (self.weapon_meta.get("portraitAsset") or self.weapon_meta.get("iconAsset"))
            if isinstance(self.weapon_meta, Mapping)
            else None
        )

        # Strictly honor Beast passive rule: Beasts NEVER actively attack in 3D Arena!
        if self.category == "beast":
            self.can_attack = False
            self.arena_active_attack = False
        else:
            self.can_attack = bool(self.attack_profile.get("canAttack", False))
            self.arena_active_attack = bool(self.attack_profile.get("arenaActiveAttack", self.can_attack)) and self.can_attack

        self.attack_mode = str(self.attack_profile.get("attackMode") or "none")
        self.engage_range = float(self.attack_profile.get("engageRange") or 0.0)
        self.sustain_range = float(self.attack_profile.get("sustainRange") or self.engage_range)
        self.effective_max_range = float(self.attack_profile.get("effectiveMaxRange") or (self.engage_range if self.can_attack else 0.0))
        self.ai_profile = self.attack_profile.get("aiProfile") or {}
        if self.ai_profile.get("onlyFireWithinRange") and isinstance(self.ai_profile.get("traceDistance"), (int, float)):
            self.sustain_range = min(self.sustain_range, float(self.ai_profile["traceDistance"]))

        self.shivering_equipped = bool(self.attack_profile.get("shiveringContagionEquipped", False))
        self.shivering_ratio = 1.0
        self.clone_multiplier = max(1, int(self.attack_profile.get("cloneMultiplier") or 1))
        self.artax_retarget_unchilled = bool(self.ai_profile.get("artaxRetargetUnchilled", False))
        self.max_active_projectiles = self.ai_profile.get("maxActiveProjectiles")
        self.retaliatory_only = bool((self.attack_profile.get("attackPrecept") or {}).get("retaliatoryOnly", False))

        # Companion Shield & Overshield (for Reinforced Bond)
        sh_block = stats_meta.get("shield") or {}
        self.max_shield = max(0.0, float(sh_block.get("modded") if isinstance(sh_block, Mapping) else sh_block or 0.0))
        self.shield = self.max_shield
        self.overshield_cap = max(0.0, float(stats_meta.get("overshieldCap") or (1200.0 if self.max_shield > 0 else 0.0)))
        self.overshield = 0.0

        # Bond states
        self.tenacious_bond = self.player_bridge.get("tenaciousBond") or {}
        self.tenacious_active = bool(self.tenacious_bond.get("active", False))
        self.reinforced_bond = self.player_bridge.get("reinforcedBond") or {}
        self.reinforced_equipped = bool(self.reinforced_bond.get("equipped", False))
        self.reinforced_reload_os = float(self.reinforced_bond.get("reloadOvershield") or 0.0)
        # Card bonus is +60% at R5 (+10% * (rank + 1)) even when staticActive is False initially
        rb_rank = int(self.reinforced_bond.get("rank", 5))
        self.reinforced_card_bonus = (
            float(self.reinforced_bond.get("fireRateBonus") or 0.0)
            if float(self.reinforced_bond.get("fireRateBonus") or 0.0) > 0.0
            else (0.10 * (rb_rank + 1) if self.reinforced_equipped else 0.0)
        )
        self.reinforced_active_seconds = 0.0
        self._last_step_t = 0.0

        self.contagious_bond = self.player_bridge.get("contagiousBond") or {}
        self.contagious_equipped = bool(self.contagious_bond.get("equipped", False))
        self.contagious_ratio = float(self.contagious_bond.get("spreadRatio") or 0.0)
        self.contagious_radius = float(self.contagious_bond.get("spreadRadius") or 9.0)

        self.manifold_bond = self.player_bridge.get("manifoldBond") or {}
        self.manifold_equipped = bool(self.manifold_bond.get("equipped", False))
        self.manifold_threshold = float(self.manifold_bond.get("uniqueStatusThreshold") or 3.0)
        self.manifold_cdr = float(self.manifold_bond.get("cooldownReduction") or 3.0)
        self.manifold_status_types = list(self.manifold_bond.get("preceptStatusTypes") or ())

        self.vicious_bond = self.player_bridge.get("viciousBond") or {}
        self.vicious_strip = (
            float(self.vicious_bond.get("armorStrip") or 0.0)
            if self.vicious_bond.get("equipped")
            else 0.0
        )

        # Cat's Eye dynamic buff state (when Beast Kavat has Cat's Eye equipped)
        self.cats_eye_bonus = 0.0
        self.cats_eye_duration = 10.0
        self.cats_eye_cooldown = 20.0
        for sl in evaluation.get("slots") or ():
            if isinstance(sl, Mapping) and sl.get("path") == companion_loadout.CATS_EYE_PATH:
                r = int(sl.get("rank", 3))
                self.cats_eye_bonus = 0.15 * (r + 1)
                self.cats_eye_cooldown = [30.0, 26.7, 23.3, 20.0][min(r, 3)]

        # Offensive Precept runtime trackers (for Robotic precepts & Manifold Bond)
        self.precepts: list[dict[str, Any]] = []
        if self.category == "robotic":
            for p in self.attack_profile.get("offensivePrecepts") or ():
                if not isinstance(p, Mapping):
                    continue
                cd = float(p.get("cooldown") or 10.0)
                rng = float(p.get("attackRange") or p.get("radius") or 15.0)
                if cd > 0.0 and rng > 0.0:
                    self.precepts.append({
                        **p,
                        "cooldown": cd,
                        "attackRange": rng,
                        "ready_at": 0.5,
                    })

        # Positioning state
        self.forward = (0.0, 1.0)
        self._last_player_pos = tuple(player_start_pos)
        self._breadcrumbs: deque[tuple[float, float, float]] = deque([tuple(player_start_pos)], maxlen=32)
        self.pos = self._compute_follow_pos(player_start_pos)

        # Targeting & Burst cadence state
        self.current_target_id: int | None = None
        self.next_retarget_at = 0.0
        self.burst_until = math.inf
        self.pause_until = 0.0
        bt = self.ai_profile.get("burstTime") or [0.0, 0.0]
        if float(bt[1]) > 0.0:
            self.burst_until = _lerp(float(bt[0]), float(bt[1]), self._rng())
        self.active_glaive_returns: list[float] = []
        self._in_shivering_spread = False

        # Telemetry & Stats
        self.shots = 0
        self.hits = 0
        self.kills = 0
        self.procs_applied: dict[str, float] = {}
        self.contagious_spreads = 0
        self.manifold_triggers = 0
        self.frames: list[list[float]] = []
        self.shot_visuals: list[list[float]] = []

        # Build companion ArenaCombat shooter if robotic & canAttack
        self.shooter: ArenaCombat | None = None
        self.shooter_radial_radius = 0.0
        self.shooter_radial_falloff = 0.0
        if self.can_attack and isinstance(self.weapon_meta, Mapping):
            self.shooter = self._build_shooter(companion_context, world_context, player_combat)

        self.record_frame(0.0)

    def _rng(self) -> float:
        val = _det_random(self.seed, self._rng_idx, 41)
        self._rng_idx += 1
        return val

    def _build_shooter(
        self,
        companion_context: Mapping[str, Any],
        world_context: Mapping[str, Any],
        player_combat: ArenaCombat,
    ) -> ArenaCombat | None:
        wpath = str(self.weapon_meta.get("path") or "")
        if not wpath:
            return None

        exp = companion_loadout._default_exports()
        weapons_cat = exp.get("weapons") or ()
        mods_cat = exp.get("mods") or ()

        weapon_record = companion_context.get("weaponRecord")
        if weapon_record is None:
            if wpath.casefold() in companion_loadout.MOA_MELEE_WEAPON_ALIASES:
                he_rank = 5
                for sl in self.evaluation.get("slots") or ():
                    if isinstance(sl, Mapping) and sl.get("path") == companion_loadout.HARD_ENGAGE_PATH:
                        he_rank = int(sl.get("rank", 5))
                weapon_record = companion_loadout._moa_melee_weapon_record(he_rank)
            else:
                weapon_record = companion_loadout.resolve_record(weapons_cat, wpath, kind="weapon")

        raw_mod_records = companion_context.get("weaponModRecords")
        mod_records: list[tuple[Mapping[str, Any], int, Any]] = []
        if raw_mod_records is not None:
            for entry in raw_mod_records:
                if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                    rec = entry[0]
                    if isinstance(rec, str):
                        rec = companion_loadout.resolve_record(mods_cat, rec, kind="mod")
                    rk = int(entry[1])
                    ov = entry[2] if len(entry) >= 3 else None
                    mod_records.append((rec, rk, ov))
                elif isinstance(entry, Mapping) and entry.get("path") and entry["path"] != "__riven__":
                    rec = companion_loadout.resolve_record(mods_cat, entry["path"], kind="mod")
                    rk = int(entry.get("rank", rec.get("maxRank") or 0))
                    mod_records.append((rec, rk, None))
        else:
            for sl in self.weapon_meta.get("slots") or ():
                if isinstance(sl, Mapping) and sl.get("path") and sl["path"] != "__riven__":
                    rec = companion_loadout.resolve_record(mods_cat, sl["path"], kind="mod")
                    rk = int(sl.get("rank", rec.get("maxRank") or 0))
                    mod_records.append((rec, rk, None))

        for rec, rk, _ in mod_records:
            if rec.get("path") == companion_loadout.SHIVERING_CONTAGION_PATH:
                self.shivering_equipped = True
                self.shivering_ratio = min(1.0, 0.167 * (rk + 1))

        comp_scenario = dm.Scenario(
            aiming=False,
            trigger_policy="emergent",
            combat_state={"companion": True, "companionPlayerStacks": False},
        )
        effects = dm.ModEffectList()
        for rec, rk, _ in mod_records:
            effects.extend(dm.mod_effects(rec, rk, comp_scenario))

        riven_info = self.weapon_meta.get("riven")
        if isinstance(riven_info, Mapping) and isinstance(riven_info.get("effects"), list):
            effects.extend(companion_loadout._deserialize_effects(riven_info["effects"]))

        body_fx = companion_loadout.companion_weapon_mod_effects(self.evaluation)
        for eff in body_fx:
            if eff.runtime_kind == "sentinel-fired-up":
                eff = dm.ModEffect(
                    eff.upgrade_type,
                    eff.operation,
                    eff.value,
                    damage_type=eff.damage_type,
                    source_path="sentinel:" + companion_loadout.FIRED_UP_PATH,
                    runtime_kind=eff.runtime_kind,
                    runtime_chance=eff.runtime_chance,
                    runtime_threshold=eff.runtime_threshold,
                    runtime_multiplier=eff.runtime_multiplier,
                )
            effects.append(eff)

        sim_opts = dict(companion_context.get("weaponSimOptions") or {})
        base_common = dict(world_context.get("common_options") or {})
        comp_options = {
            k: base_common[k]
            for k in ("level", "armour_strip", "elemental_armour_strip", "steel_path", "enemy_enhancements")
            if k in base_common
        }
        comp_options.update(sim_opts)
        comp_options["assumed"] = False
        comp_options["delivery_kinds"] = [
            "lingering",
            "stackable",
            "sourceOwned",
            "finiteField",
            "ownedEmbed",
            "embedded",
            "projectileSequence",
            "melee",
        ]

        comp_engine = {
            "weapon": weapon_record,
            "fire_mode": 0,
            "effects": effects,
            "scenario": comp_scenario,
        }
        shooter = ArenaCombat(comp_engine, mod_records, (), comp_options, None, False)
        shooter.targets = player_combat.targets
        shooter.capture_kill_statuses = True

        # Check radial explosion radius (e.g. Helstrum micro-missiles)
        from .event_profiles import base_profile

        prof0 = base_profile(weapon_record, 0)
        rads = list(prof0.get("radials") or ([prof0["radial"]] if prof0.get("radial") else ()))
        if rads:
            self.shooter_radial_radius = float(rads[0].get("radius_m") or rads[0].get("radius") or 0.0)
            self.shooter_radial_falloff = float(rads[0].get("falloff_reduction") or rads[0].get("falloff") or 0.0)

        def _on_proc(v: Any, dtype: str, count: float, t: float) -> None:
            if count <= 0.0:
                return
            self.procs_applied[dtype] = self.procs_applied.get(dtype, 0.0) + count
            if dtype in ("DT_FREEZE", "DT_FIRE"):
                player_combat.on_companion_proc(dtype, t, count)
            if dtype == "DT_FREEZE" and self.shivering_equipped and not self._in_shivering_spread:
                self._spread_shivering_cold(v, count * self.shivering_ratio, t, player_combat)

        shooter.on_proc_applied = _on_proc
        return shooter

    def _spread_shivering_cold(
        self, origin_victim: Any, cold_count: float, t: float, player_combat: ArenaCombat
    ) -> None:
        if cold_count <= EPS or self.shooter is None or self.shooter.nearby is None:
            return
        self._in_shivering_spread = True
        try:
            st, _ = self.shooter._resolve(origin_victim)
            for nid in dict.fromkeys(self.shooter.nearby(origin_victim.id, 6.0, t)):
                nb = self.shooter.targets.get(nid)
                if nb is None or not nb.alive or nb.protected or nb.status_immune:
                    continue
                self.shooter._clean(nb, t)
                self.shooter._procs(
                    nb,
                    st,
                    False,
                    t,
                    ({}, {"DT_FREEZE": cold_count}, {}, {}),
                    1.0,
                    "selected",
                    False,
                )
        finally:
            self._in_shivering_spread = False

    def is_reinforced_active(self, _t: float) -> bool:
        return self.reinforced_equipped and (self.shield + self.overshield >= 1200.0 - 1e-6)

    def is_cats_eye_active(self, t: float) -> bool:
        if self.cats_eye_bonus <= 0.0 or self.cats_eye_cooldown <= 0.0:
            return False
        phase = float(t) % self.cats_eye_cooldown
        return phase < self.cats_eye_duration

    def on_player_reload(self, t: float) -> None:
        self._advance_uptime(t)
        if self.reinforced_equipped and self.max_shield > 0.0 and self.reinforced_reload_os > 0.0:
            self.overshield = min(self.overshield_cap, self.overshield + self.reinforced_reload_os)
            self.record_frame(t)

    def on_any_kill(self, victim: Any, t: float) -> None:
        if not self.manifold_equipped or not self.precepts:
            return
        unique_statuses = sum(p.probability(t) for p in victim.presence.values())
        if unique_statuses >= self.manifold_threshold - 1e-6:
            for p in self.precepts:
                p["ready_at"] = max(t, p["ready_at"] - self.manifold_cdr)

    def _handle_contagious_kill(self, kill_event: Mapping[str, Any], world: Any, player_combat: ArenaCombat) -> None:
        if not self.contagious_equipped or self.contagious_ratio <= 0.0:
            return
        active = kill_event.get("activeStatuses") or {}
        if not active:
            return
        vid = kill_event["targetId"]
        when = float(kill_event["time"])
        victim = player_combat.targets.get(vid)
        if victim is None:
            return
        origin = victim.position
        neighbours = [
            a.id
            for a in world.live
            if not a.dead
            and a.id != vid
            and distance(a.pos, origin) <= self.contagious_radius
            and world.scene.visible(_add_y(origin, 0.85), _add_y(a.pos, 0.85))
        ]
        if not neighbours:
            return

        # Cap total spread stacks to 100 per Contagious Bond rule
        spread_counts: dict[str, float] = {}
        raw_sum = 0.0
        for dt, cnt in active.items():
            amt = float(cnt) * self.contagious_ratio
            if amt > EPS:
                spread_counts[dt] = amt
                raw_sum += amt
        if raw_sum <= EPS:
            return
        if raw_sum > 100.0:
            scale = 100.0 / raw_sum
            spread_counts = {dt: amt * scale for dt, amt in spread_counts.items()}

        heat_seed = float(kill_event.get("heatSeed") or 0.0) * self.contagious_ratio
        for nid in neighbours:
            nb = player_combat.targets.get(nid)
            if nb is None or not nb.alive or nb.protected or nb.status_immune:
                continue
            player_combat._clean(nb, when)
            self._apply_direct_status_stacks(nb, spread_counts, when, player_combat, heat_seed=heat_seed)
            self.contagious_spreads += 1

    def _apply_direct_status_stacks(
        self,
        nb: Any,
        stacks_by_type: Mapping[str, float],
        t: float,
        player_combat: ArenaCombat,
        *,
        heat_seed: float = 10.0,
    ) -> None:
        owner = self.shooter or player_combat
        for dt, cnt in stacks_by_type.items():
            if cnt <= EPS:
                continue
            if dt == "DT_RADIATION" and dm.devourer_blocks_radiation(nb.record):
                continue
            dur = DURATIONS.get(dt, 6.0)
            absent = max(0.0, 1.0 - min(1.0, cnt))
            nb.presence.setdefault(dt, StatusPresence()).add(t + dur, absent)
            self.procs_applied[dt] = self.procs_applied.get(dt, 0.0) + cnt
            if dt in ("DT_FREEZE", "DT_FIRE"):
                player_combat.on_companion_proc(dt, t, cnt)

            if dt == "DT_FIRE":
                if not nb.heat.active():
                    nb.heat_token += 1
                    owner._push(t + 1.0, "heat", nb, nb.heat_token)
                nb.heat.add(t, absent, cnt, max(1.0, heat_seed), dur, 1.0)
            elif dt == "DT_SENTIENT":
                if dt not in nb.pooled:
                    nb.pooled[dt] = CappedPool(float(nb.vip_cap) if nb.vip_cap else 10.0)
                nb.pooled[dt].add(t + dur, absent, cnt)
            elif dt in nb.pooled:
                nb.pooled[dt].add(t + dur, absent, cnt)
            else:
                st_q = nb.states.setdefault(dt, deque())
                st_q.append((t + dur, cnt))
                if dt == "DT_FREEZE":
                    cap = float(nb.vip_cap) if nb.vip_cap else (4.0 if nb.overguard > 0 else 10.0)
                    excess = sum(n for _, n in st_q) - cap
                    while st_q and excess > EPS:
                        end_t, n = st_q.popleft()
                        rem = min(n, excess)
                        excess -= rem
                        if n > rem:
                            st_q.appendleft((end_t, n - rem))
                    if not nb.vip_cap and nb.overguard <= EPS and sum(n for _, n in st_q) >= 10.0 - EPS:
                        nb.frozen_until = t + 3.0
                        nb.frozen_scale = 1.0

    def _compute_follow_pos(self, player_pos: tuple[float, float, float]) -> tuple[float, float, float]:
        fx, fz = self.forward
        rx, rz = fz, -fx
        if self.kind == "sentinel":
            return (
                player_pos[0] + rx * (-0.45) + fx * (-0.35),
                player_pos[1] + 1.85,
                player_pos[2] + rz * (-0.45) + fz * (-0.35),
            )
        # Ground follower (MOA / Hound / Beast): 2.0m behind along player's breadcrumb trail
        if len(self._breadcrumbs) >= 2:
            acc = 0.0
            cur = player_pos
            for prev in reversed(self._breadcrumbs):
                seg = distance(cur, prev)
                if acc + seg >= 2.0 and seg > EPS:
                    k = (2.0 - acc) / seg
                    pt = _mix(cur, prev, k)
                    if abs(pt[1] - player_pos[1]) > 2.5:
                        pt = (pt[0], player_pos[1], pt[2])
                    return pt
                acc += seg
                cur = prev
        return (
            player_pos[0] - fx * 2.0 + rx * 0.45,
            player_pos[1],
            player_pos[2] - fz * 2.0 + rz * 0.45,
        )

    def _advance_uptime(self, t: float) -> None:
        dt = float(t) - self._last_step_t
        if dt > 0.0:
            if self.is_reinforced_active(self._last_step_t):
                self.reinforced_active_seconds += dt
            self._last_step_t = float(t)

    def update_position(self, world: Any, dt: float) -> None:
        ppos = tuple(world.player.pos)
        dx = ppos[0] - self._last_player_pos[0]
        dz = ppos[2] - self._last_player_pos[2]
        horiz = math.hypot(dx, dz)
        if horiz > 0.05:
            self.forward = (dx / horiz, dz / horiz)
            if distance(ppos, self._breadcrumbs[-1]) >= 0.4:
                self._breadcrumbs.append(ppos)
            self._last_player_pos = ppos

        follow = self._compute_follow_pos(ppos)
        if self.kind == "sentinel" or not self.can_attack or self.attack_mode != "melee":
            self.pos = follow
            return

        # Robotic Melee (Hound / MOA Hard Engage): lunge toward engaged target within range
        tgt = world.actors.get(self.current_target_id) if self.current_target_id is not None else None
        if (
            tgt is not None
            and not tgt.dead
            and distance(ppos, tgt.pos) <= self.effective_max_range
            and world.scene.visible(_add_y(ppos, 1.1), _add_y(tgt.pos, 0.85))
        ):
            d_to_tgt = distance(self.pos, tgt.pos)
            goal = _mix(tgt.pos, ppos, min(1.0, 1.2 / max(1.2, distance(tgt.pos, ppos))))
            step_len = min(d_to_tgt, 12.0 * max(0.0, dt))
            d_goal = distance(self.pos, goal)
            self.pos = _mix(self.pos, goal, min(1.0, step_len / max(EPS, d_goal))) if d_goal > EPS else goal
        else:
            d_back = distance(self.pos, follow)
            if d_back > EPS:
                self.pos = _mix(self.pos, follow, min(1.0, (12.0 * max(0.0, dt)) / d_back))

    def _origin(self) -> tuple[float, float, float]:
        return self.pos if self.kind == "sentinel" else _add_y(self.pos, 0.90)

    def _select_target(self, world: Any, t: float) -> Any | None:
        origin = self._origin()
        ref_pos = world.player.pos if self.attack_mode == "melee" else origin
        visible_candidates = []
        for actor in world.live:
            if actor.dead:
                continue
            v = world.combat.targets[actor.id]
            if v.protected or not v.alive:
                continue
            aim = _add_y(actor.pos, 0.85)
            d = distance(ref_pos, actor.pos)
            if d <= self.effective_max_range and world.scene.visible(origin, aim):
                cold_cnt = world.combat._count(v, "DT_FREEZE", t) if self.artax_retarget_unchilled else 0.0
                visible_candidates.append((actor, d, cold_cnt))

        if not visible_candidates:
            self.current_target_id = None
            return None

        # Artax priority: prefer unchilled targets (< 1 Cold stack)
        if self.artax_retarget_unchilled:
            unchilled = [row for row in visible_candidates if row[2] < 1.0 - 1e-6]
            if unchilled:
                best = min(unchilled, key=lambda r: (r[1], r[0].id))[0]
                self.current_target_id = best.id
                self.next_retarget_at = t + 1.0
                return best

        # 1.0s target hysteresis: keep current target while alive, visible, & within sustainRange
        # unless a new candidate is > 4.0m closer!
        if self.current_target_id is not None:
            cur = world.actors.get(self.current_target_id)
            if cur is not None and not cur.dead:
                cv = world.combat.targets[cur.id]
                cur_d = distance(ref_pos, cur.pos)
                if cv.alive and not cv.protected and cur_d <= self.sustain_range and world.scene.visible(origin, _add_y(cur.pos, 0.85)):
                    nearest_actor, nearest_d, _ = min(visible_candidates, key=lambda r: (r[1], r[0].id))
                    if t < self.next_retarget_at - EPS and nearest_d >= cur_d - 4.0:
                        return cur
                    if nearest_d >= cur_d - 0.5:
                        self.next_retarget_at = t + 1.0
                        return cur

        best_actor = min(visible_candidates, key=lambda r: (r[1], r[0].id))[0]
        self.current_target_id = best_actor.id
        self.next_retarget_at = t + 1.0
        return best_actor

    def _step_precepts(
        self,
        world: Any,
        player_combat: ArenaCombat,
        wf_state: WarframeArenaState | None,
        t: float,
    ) -> None:
        if not self.precepts or not world.live:
            return
        origin = self._origin()
        owner = self.shooter or player_combat
        for p in self.precepts:
            if t < p["ready_at"] - EPS:
                continue
            rng = float(p["attackRange"])
            max_t = int(p.get("maxTargets") or 8)
            in_range = [
                a
                for a in world.live
                if not a.dead
                and not player_combat.targets[a.id].protected
                and distance(origin, a.pos) <= rng
                and world.scene.visible(origin, _add_y(a.pos, 0.85))
            ]
            if not in_range:
                continue
            in_range.sort(key=lambda a: (distance(origin, a.pos), a.id))
            chosen = in_range[:max_t]
            p["ready_at"] = t + float(p["cooldown"])

            p_dmg = float(p.get("damage") or 0.0)
            p_dt = p.get("damageType")
            forced_proc = FORCED_PROC_TO_DAMAGE_TYPE.get(str(p.get("forcedProc") or ""), p_dt)
            if wf_state is not None:
                wf_state.on_companion_precept(
                    t,
                    electric=(p_dt == "DT_ELECTRICITY" or forced_proc == "DT_ELECTRICITY"),
                )
            manifold_map = {dt: 1.0 for dt in self.manifold_status_types} if self.manifold_equipped else {}
            if forced_proc:
                manifold_map[forced_proc] = max(manifold_map.get(forced_proc, 0.0), 1.0)

            for actor in chosen:
                v = player_combat.targets[actor.id]
                if not v.alive or v.protected:
                    continue
                owner._clean(v, t)
                if p_dmg > 0.0 and p_dt:
                    owner._take(v, {str(p_dt): p_dmg}, t, "arcane")
                if v.alive and not v.status_immune and manifold_map:
                    self._apply_direct_status_stacks(v, manifold_map, t, player_combat, heat_seed=max(10.0, p_dmg * 0.5))
            if self.manifold_equipped and self.manifold_status_types:
                self.manifold_triggers += 1
            self.drain_shooter(world, player_combat)

    def drain_shooter(self, world: Any, player_combat: ArenaCombat) -> None:
        if self.shooter is None:
            return
        pending = list(self.shooter.drain_events())
        while pending:
            for ev in pending:
                if ev.get("kind") != "kill":
                    continue
                actor = world.actors.get(ev["targetId"])
                if actor is None or actor.dead:
                    continue
                actor.dead = True
                when = float(ev["time"])
                world.record(actor, when)
                actor.tape.update(
                    death=round(when, 6),
                    deathPosition=list(actor.pos),
                    deathSource="companion:" + str(ev.get("source") or "direct"),
                )
                world.stats["kills"] += 1
                world.last_kill = when
                world.replay["kills"].append([round(when, 6), actor.id, *actor.pos])
                self.kills += 1
                v = player_combat.targets[actor.id]
                self.on_any_kill(v, when)
                if getattr(world, "wf_state", None) is not None and not actor.drone:
                    world.wf_state.on_enemy_kill_orbs(
                        when,
                        is_eximus=bool(actor.tape.get("eximus")),
                        companion_damaged=True,
                    )
                self._handle_contagious_kill(ev, world, player_combat)
                if actor.drone:
                    world.stats["droneKills"] += 1
                    world.stats["vitusExpected"] = world.stats["droneKills"] * 0.06
                    if _det_random(world.c["seed"], actor.id, 3) < 0.06:
                        world.stats["vitusSample"] += 1
                    world.live = [a for a in world.live if not a.dead]
                    world.protection()
                    amount = v.defenses["health"]
                    before = player_combat.drone_explosion_damage
                    d_origin = _add_y(actor.pos, 0.85)
                    for recipient in world.live:
                        factor = max(0.0, 1.0 - world.distance_to_body(d_origin, recipient) / 20.0)
                        if factor > 0.0:
                            player_combat.drone_explosion(recipient.id, amount * factor, when)
                    world.replay["combat"].append(dict(
                        kind="drone-explosion",
                        time=round(when, 6),
                        sourceActor=actor.id,
                        attacker="companion",
                        weapon=None,
                        position=list(actor.pos),
                        radius=20.0,
                        baseAmount=amount,
                        damage=player_combat.drone_explosion_damage - before,
                        forcedProc="PT_KNOCKED_DOWN",
                        checkForCover=False,
                        falloff="linear-to-zero-at20m",
                    ))
                    world.drain()
            world.live = [a for a in world.live if not a.dead]
            pending = list(self.shooter.drain_events())

    def step(
        self,
        world: Any,
        player_combat: ArenaCombat,
        wf_state: WarframeArenaState | None,
        t: float,
    ) -> None:
        self._advance_uptime(t)
        if self.shooter is not None:
            if self.shooter.nearby is None:
                self.shooter.nearby = world.nearby
                self.shooter.blast_recipients = world.blast_recipients
            self.shooter.protected_ids = player_combat.protected_ids
            if t > self.shooter.time + EPS:
                evs = self.shooter.advance(t)
                self.shooter._events.extend(evs)
                self.drain_shooter(world, player_combat)

        if self.category == "beast":
            return

        self._step_precepts(world, player_combat, wf_state, t)

        if not self.can_attack or self.shooter is None or not world.live:
            return
        if self.retaliatory_only and wf_state is not None and wf_state.hits_taken == 0:
            return

        # Deconstructor 3-glaive active flight gate
        if self.max_active_projectiles is not None:
            self.active_glaive_returns = [rt for rt in self.active_glaive_returns if rt > t + EPS]
            if len(self.active_glaive_returns) >= int(self.max_active_projectiles):
                return

        # AI burst/pause duty cycle
        bt = self.ai_profile.get("burstTime") or [0.0, 0.0]
        bp = self.ai_profile.get("burstPauseTime") or [0.0, 0.0]
        if t < self.pause_until - EPS:
            return
        if float(bt[1]) > 0.0 and float(bp[1]) > 0.0 and t >= self.burst_until - EPS:
            pause_d = _lerp(float(bp[0]), float(bp[1]), self._rng())
            self.pause_until = t + pause_d
            self.burst_until = self.pause_until + _lerp(float(bt[0]), float(bt[1]), self._rng())
            return

        if t < self.shooter.next_attack_time(t) - EPS:
            return

        target_actor = self._select_target(world, t)
        if target_actor is None:
            return

        origin = self._origin()
        aim_pt = _add_y(target_actor.pos, 0.85)
        dist = distance(origin, aim_pt)
        if self.attack_mode == "melee" and self.kind != "sentinel" and distance(self.pos, target_actor.pos) > 3.2:
            return

        for _ in range(self.clone_multiplier):
            if target_actor.dead:
                target_actor = self._select_target(world, t)
                if target_actor is None:
                    break
                aim_pt = _add_y(target_actor.pos, 0.85)
                dist = distance(origin, aim_pt)

            shot = self.shooter.prepare_shot(t, head=False, target_id=target_actor.id)
            self.drain_shooter(world, player_combat)
            if shot is None:
                break

            self.shooter.fire_shot(shot, t)
            self.shots += 1
            if self.max_active_projectiles is not None:
                flight_back = max(0.25, 2.0 * dist / 36.0)
                self.active_glaive_returns.append(t + flight_back)

            if len(self.shot_visuals) < 2500:
                self.shot_visuals.append([
                    round(t, 4),
                    round(origin[0], 3),
                    round(origin[1], 3),
                    round(origin[2], 3),
                    round(aim_pt[0], 3),
                    round(aim_pt[1], 3),
                    round(aim_pt[2], 3),
                ])

            self.shooter.begin_impact(shot, t)
            self.shooter.hit(shot, target_actor.id, 0, head=False, distance=dist, radial_scale=1.0, t=t)
            self.hits += 1
            if self.vicious_strip > 0.0 and self.attack_mode == "melee":
                v_obj = player_combat.targets[target_actor.id]
                v_obj.vicious_strip = min(1.0, v_obj.vicious_strip + self.vicious_strip)

            if shot.radials and self.shooter_radial_radius > 0.0:
                r = self.shooter_radial_radius
                for other in list(world.live):
                    if other.dead:
                        continue
                    d_aoe = distance(_add_y(other.pos, 0.85), aim_pt)
                    if d_aoe <= r and world.scene.visible(aim_pt, _add_y(other.pos, 0.85)):
                        scale = max(0.0, 1.0 - self.shooter_radial_falloff * (d_aoe / max(EPS, r)))
                        self.shooter.hit(shot, other.id, 1, head=False, distance=dist, radial_scale=scale, t=t)

            self.shooter.finish_impact(shot, t, retire=True)
            self.drain_shooter(world, player_combat)

            if self.clone_multiplier > 1:
                self.shooter._ready = t

    def next_event_time(self) -> float:
        if self.shooter is None:
            return math.inf
        return self.shooter.next_event_time()

    def record_frame(self, t: float) -> None:
        row = [
            round(float(t), 4),
            round(self.pos[0], 3),
            round(self.pos[1], 3),
            round(self.pos[2], 3),
            round(self.shield, 1),
            round(self.overshield, 1),
        ]
        if self.frames and abs(self.frames[-1][0] - row[0]) < 1e-5:
            self.frames[-1] = row
        else:
            self.frames.append(row)

    def reinforced_uptime_ratio(self, total_t: float) -> float:
        if total_t <= EPS:
            return 1.0 if self.is_reinforced_active(0.0) else 0.0
        return min(1.0, self.reinforced_active_seconds / total_t)

    def stats_payload(self, total_t: float) -> dict[str, Any]:
        self._advance_uptime(total_t)
        direct_dmg = self.shooter.direct_damage + self.shooter.arcane_damage if self.shooter else 0.0
        dot_dmg = self.shooter.dot_damage if self.shooter else 0.0
        return {
            "shots": self.shots,
            "hits": self.hits,
            "directDamage": round(direct_dmg, 3),
            "dotDamage": round(dot_dmg, 3),
            "kills": self.kills,
            "procsApplied": {k: round(v, 4) for k, v in self.procs_applied.items() if v > 0.0},
            "contagiousSpreads": self.contagious_spreads,
            "manifoldTriggers": self.manifold_triggers,
            "reinforcedUptimeRatio": round(self.reinforced_uptime_ratio(total_t), 6),
            "tenaciousActive": bool(self.tenacious_active),
        }

    def visuals_payload(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "category": self.category,
            "kind": self.kind,
            "nameZh": self.name_zh,
            "nameEn": self.name_en,
            "weaponNameZh": self.weapon_name_zh,
            "portraitAsset": self.portrait_asset,
            "weaponAsset": self.weapon_asset,
            "canAttack": self.can_attack,
            "arenaActiveAttack": self.arena_active_attack,
            "engageRange": round(self.engage_range, 3),
            "effectiveMaxRange": round(self.effective_max_range, 3),
            "frames": self.frames,
            "shots": self.shot_visuals,
        }


def build_dynamic_synergy_sources(
    wf_state: WarframeArenaState | None,
    comp_preview_eval: Mapping[str, Any] | None,
    arcane_records: tuple[Any, ...],
    engine_effects: Any,
    state_holder: dict[str, Any],
) -> tuple[list[tuple[dict[str, Any], int, None]], Callable[[float], dict[str, float]]]:
    """Construct dynamic trigger sources & live stack provider for player ArenaCombat."""
    dyn_records: list[tuple[dict[str, Any], int, None]] = []
    evaluators: list[tuple[str, Callable[[float], float]]] = []
    existing_sources = {getattr(e, "source_path", None) for e in (engine_effects or ())}

    def _add_dyn(
        source_path: str,
        event_kind: str,
        label: str,
        max_stacks: float,
        effects_list: list[dict[str, Any]],
        fn: Callable[[float], float],
    ) -> None:
        key = f"{source_path}:0:0"
        rec = {
            "path": source_path,
            "nameEn": label,
            "nameZh": label,
            "conditionalEffects": [
                {
                    "sourcePath": source_path,
                    "eventKind": event_kind,
                    "maxStacks": max_stacks,
                    "duration": 0.0,
                    "hold": True,
                    "chance": 0.0,
                    "effects": effects_list,
                }
            ],
        }
        dyn_records.append((rec, 0, None))
        evaluators.append((key, fn))

    if wf_state is not None:
        if wf_state.rotation is not None and wf_state.dynamic_ability_effects:
            for d_ab in wf_state.dynamic_ability_effects:
                d_id = str(d_ab.get("id") or "")
                d_src = str(d_ab.get("sourcePath") or f"warframe:{d_id}")
                d_lbl = str(d_ab.get("nameZh") or d_id)
                d_fx = list(d_ab.get("effects") or ())
                if d_id and d_fx:
                    _add_dyn(
                        d_src,
                        f"__arena_wf_ab_{d_id}",
                        d_lbl,
                        6.0,
                        d_fx,
                        lambda t, aid=d_id: wf_state.rotation.ability_strength_ratio(aid, t) if wf_state.rotation else 1.0,
                    )

        if wf_state.avenger_equipped and wf_state.avenger_crit_bonus > 0.0:
            _add_dyn(
                ARCANE_AVENGER_PATH,
                "__arena_wf_avenger",
                "Arcane Avenger",
                1.0,
                [{"upgradeType": "WEAPON_CRIT_CHANCE", "operation": "ADD", "valuePerRank": wf_state.avenger_crit_bonus}],
                lambda t: 1.0 if wf_state.is_avenger_active(t) else 0.0,
            )

        for record, rank, override in arcane_records:
            apath = str(record.get("path") or "")
            if isinstance(override, Mapping) and (override.get("forced") is True or override.get("stacks") is not None):
                continue
            if apath == arcane_runtime.BULWARK:
                spec = arcane_runtime.configuration(record, rank)
                if spec:
                    unit_fx = spec["build"](1, 1.0)[0]
                    cap = float(spec["maxStacks"] or 500)
                    _add_dyn(
                        apath,
                        "__arena_wf_bulwark",
                        "Primary Bulwark",
                        cap,
                        [{"upgradeType": unit_fx.upgrade_type, "operation": unit_fx.operation, "valuePerRank": unit_fx.value}],
                        lambda t, c=cap: min(c, float(max(0, int(math.floor(wf_state.current_armor(t) - 1000.0 + 1e-9))))),
                    )
            elif apath == arcane_runtime.CASCADIA_OVERCHARGE:
                spec = arcane_runtime.configuration(record, rank)
                if spec:
                    unit_fx = spec["build"](1, 1.0)[0]
                    _add_dyn(
                        apath,
                        "__arena_wf_cascadia_overcharge",
                        "Cascadia Overcharge",
                        1.0,
                        [{"upgradeType": unit_fx.upgrade_type, "operation": unit_fx.operation, "valuePerRank": unit_fx.value}],
                        lambda _t: 1.0 if wf_state.overshield > EPS else 0.0,
                    )
            elif apath == arcane_runtime.RETALIATION:
                spec = arcane_runtime.configuration(record, rank)
                if spec:
                    unit_fx = spec["build"](1, 1.0)[0]
                    cap = float(spec["maxStacks"] or 84)
                    _add_dyn(
                        apath,
                        "__arena_wf_retaliation",
                        "Melee Retaliation",
                        cap,
                        [{"upgradeType": unit_fx.upgrade_type, "operation": unit_fx.operation, "valuePerRank": unit_fx.value}],
                        lambda _t, c=cap: min(c, float(max(0, int(math.floor((wf_state.shield + 0.5 * wf_state.overshield) / 200.0 + 1e-9))))),
                    )

    if comp_preview_eval is not None:
        pb = comp_preview_eval.get("playerBridge") or {}
        tb = pb.get("tenaciousBond") or {}
        if tb.get("active") and float(tb.get("finalCritDamageBonus") or 0.0) > 0.0:
            if companion_loadout.TENACIOUS_BOND_PATH not in existing_sources:
                _add_dyn(
                    companion_loadout.TENACIOUS_BOND_PATH,
                    "__arena_comp_tenacious",
                    "Tenacious Bond",
                    1.0,
                    [{"upgradeType": "RUNTIME_FINAL_CRIT_DAMAGE", "operation": "ADD", "valuePerRank": float(tb["finalCritDamageBonus"])}],
                    lambda _t: 1.0,
                )

        rb = pb.get("reinforcedBond") or {}
        if rb.get("equipped"):
            rb_rank = int(rb.get("rank", 5))
            rb_bonus = float(rb.get("fireRateBonus") or 0.0) or (0.10 * (rb_rank + 1))
            if rb_bonus > 0.0:
                _add_dyn(
                    companion_loadout.REINFORCED_BOND_PATH,
                    "__arena_comp_reinforced",
                    "Reinforced Bond",
                    1.0,
                    [{"upgradeType": "WEAPON_FIRE_RATE", "operation": "STACKING_MULTIPLY", "valuePerRank": rb_bonus}],
                    lambda t: 1.0 if (state_holder.get("comp") and state_holder["comp"].is_reinforced_active(t)) else 0.0,
                )

        # Cat's Eye dynamic cycle when not already statically injected
        if companion_loadout.CATS_EYE_PATH not in existing_sources:
            for sl in comp_preview_eval.get("slots") or ():
                if isinstance(sl, Mapping) and sl.get("path") == companion_loadout.CATS_EYE_PATH:
                    ce_bonus = 0.15 * (int(sl.get("rank", 3)) + 1)
                    _add_dyn(
                        companion_loadout.CATS_EYE_PATH,
                        "__arena_comp_cats_eye",
                        "Cat's Eye",
                        1.0,
                        [{"upgradeType": "WEAPON_CRIT_CHANCE", "operation": "ADD", "valuePerRank": ce_bonus}],
                        lambda t: 1.0 if (state_holder.get("comp") and state_holder["comp"].is_cats_eye_active(t)) else 0.0,
                    )
                    break

    def _provider(t: float) -> dict[str, float]:
        return {k: fn(t) for k, fn in evaluators}

    return dyn_records, _provider
