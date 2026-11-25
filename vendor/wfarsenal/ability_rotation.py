"""Warframe Realistic Ability Rotation & Orb Economy Simulator.

Implements deterministic, client-verified Warframe buff ability rotation:
- Strict 1 -> 2 -> 3 -> 4 slot priority casting serialization
- Client .fbx_H + Luau PlayAnim cast durations scaled by AVATAR_CASTING_SPEED
- Weapon firing lock while casting (技能施放期间武器不攻击)
- Energy gate & vacuum period (缺蓝真空期) until passive regen or orb pickup
- Full-map Health / Energy Orb drop & pickup loop:
  Normal enemy 10% 25E orb, Eximus guaranteed 2x 50HP + 1x 25E orbs,
  Synth Deconstruct, Synth Fiber, Equilibrium, Violet/Amber Archon Shards,
  Nourish (native 1+1.0*Str / Helminth 1+0.6*Str), Arcane Energize,
  Arcane Steadfast, Mystic Bond, Duplex Bond, Seismic Bond, Energy Conversion,
  Health Conversion, Arcane Blessing, Arcane Pulse, Molt Reconstruct,
  Molt Efficiency, Molt Augmented (strength snapshotting on recast),
  Brief Respite / Augur shield conversion, Rage / Hunter Adrenaline.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

EPS = 1e-9


def _det_random(seed: int, index: int, stream: int = 73) -> float:
    x = (int(seed) ^ ((int(index) + 1) * 0x9E3779B1) ^ ((int(stream) + 1) * 0x85EBCA6B)) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967296.0


def _path_token(val: Any) -> str:
    return str(val or "").strip().replace("\\", "/").rstrip("/").casefold()


def parse_rotation_config(wf_source: Mapping[str, Any] | None) -> dict[str, Any]:
    """Normalize optional warframeLink.abilityRotation configuration."""
    if not isinstance(wf_source, Mapping):
        return {"enabled": False, "allowOneHandedFiring": False, "castOrder": [], "arbucepEmpowered": False}
    arbucep = bool(wf_source.get("arbucepEmpowered", False))
    raw = wf_source.get("abilityRotation")
    if isinstance(raw, bool):
        return {"enabled": raw, "allowOneHandedFiring": False, "castOrder": [], "arbucepEmpowered": arbucep}
    if isinstance(raw, Mapping):
        raw_order = raw.get("castOrder")
        cast_order = (
            [str(x).strip() for x in raw_order if str(x).strip()]
            if isinstance(raw_order, (list, tuple))
            else []
        )
        return {
            "enabled": bool(raw.get("enabled", False)),
            "allowOneHandedFiring": bool(raw.get("allowOneHandedFiring", False)),
            "castOrder": cast_order,
            "arbucepEmpowered": bool(raw.get("arbucepEmpowered", arbucep)),
        }
    return {"enabled": False, "allowOneHandedFiring": False, "castOrder": [], "arbucepEmpowered": arbucep}


def _extract_companion_economy(comp_eval: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(comp_eval, Mapping):
        return {
            "synthDeconstructChance": 0.0,
            "synthFiberEquipped": False,
            "mysticBondRequiredCasts": 0,
            "duplexBondOrbChance": 0.0,
            "seismicBondPerStack": 0.0,
            "companionPreceptInterval": 0.0,
            "triggersArchonStretch": False,
            "canAssistDamage": False,
        }
    slots = comp_eval.get("slots") or ()
    synth_dec = 0.0
    synth_fib = False
    mystic_req = 0
    duplex_orb = 0.0
    seismic_per = 0.0
    for sl in slots:
        if not isinstance(sl, Mapping):
            continue
        pt = _path_token(sl.get("path") or sl.get("id"))
        rank = max(0, int(sl.get("rank") or 0))
        if pt.endswith("sentinelsynthdeconstructmod"):
            synth_dec = min(0.25, (0.25 / 6.0) * (rank + 1))
        elif pt.endswith("sentinelsynthfibersmod"):
            synth_fib = True
        elif pt.endswith("/voidbond/preydrive"):
            req_table = (10, 9, 8, 7, 6, 5)
            mystic_req = req_table[min(rank, len(req_table) - 1)]
        elif pt.endswith("/voidbond/voidclone"):
            duplex_orb = min(0.50, (0.50 / 6.0) * (rank + 1))
        elif pt.endswith("/voidbond/bondedexaltation"):
            seismic_per = 0.005 * (rank + 1)

    attack_prof = comp_eval.get("attackProfile") if isinstance(comp_eval.get("attackProfile"), Mapping) else {}
    precepts = attack_prof.get("offensivePrecepts") or ()
    precept_rates = 0.0
    has_elec_precept = False
    for p in precepts:
        if isinstance(p, Mapping):
            cd = float(p.get("cooldown") or 0.0)
            if cd > 0.0:
                precept_rates += 1.0 / cd
            if p.get("damageType") == "DT_ELECTRICITY" or "DT_ELECTRICITY" in (p.get("manifoldStatusTypes") or ()):
                has_elec_precept = True

    # Beast cooldown precepts (e.g. Viral Quills ~4s, Panzer spores) also trigger Mystic Bond & Synth Deconstruct!
    comp_meta = comp_eval.get("companion") if isinstance(comp_eval.get("companion"), Mapping) else {}
    is_beast = str(comp_meta.get("category") or "") == "beast"
    if is_beast and precept_rates <= 0.0:
        precept_rates = 1.0 / 6.0  # Conservative beast precept cadence (~6s)

    can_assist = bool(attack_prof.get("canAttack")) or precept_rates > 0.0
    precept_interval = (1.0 / precept_rates) if precept_rates > 1e-6 else 0.0

    return {
        "synthDeconstructChance": round(synth_dec, 6),
        "synthFiberEquipped": synth_fib,
        "mysticBondRequiredCasts": mystic_req,
        "duplexBondOrbChance": round(duplex_orb, 6),
        "seismicBondPerStack": round(seismic_per, 6),
        "companionPreceptInterval": round(precept_interval, 4),
        "triggersArchonStretch": has_elec_precept,
        "canAssistDamage": can_assist,
    }


class _RotationSlotItem:
    """One physical Warframe ability cast unit (co-slot ability + augments share a cast)."""

    __slots__ = (
        "slot_order",
        "slot_index",
        "primary_id",
        "member_ids",
        "ability_path",
        "name_zh",
        "name_en",
        "is_helminth",
        "resource",
        "base_cost",
        "base_drain",
        "max_enemies_drain",
        "is_channeled",
        "prevents_regen",
        "base_duration",
        "invuln_duration",
        "fixed_duration",
        "bonus_sec_per_100_shields",
        "kill_extend_sec",
        "cooldown_sec",
        "base_cast_time",
        "one_handed",
        "recastable",
        "nominal_slot_strength",
        "uncond_slot_strength",
        "special",
        "active",
        "active_until",
        "cycle_until",
        "cooldown_until",
        "snap_strength",
        "first_cast_strength",
        "casts",
        "active_seconds",
        "vacuum_seconds",
        "unaffordable",
    )

    def __init__(
        self,
        *,
        slot_order: tuple[int, int],
        slot_index: int | None,
        primary_id: str,
        member_ids: list[str],
        ability_path: str | None,
        name_zh: str,
        name_en: str,
        is_helminth: bool,
        rspec: Mapping[str, Any],
        nominal_slot_strength: float,
        uncond_slot_strength: float,
    ) -> None:
        self.slot_order = slot_order
        self.slot_index = slot_index
        self.primary_id = primary_id
        self.member_ids = member_ids
        self.ability_path = ability_path
        self.name_zh = name_zh
        self.name_en = name_en
        self.is_helminth = is_helminth
        self.resource = str(rspec.get("resource") or "energy")
        self.base_cost = max(0.0, float(rspec.get("baseEnergyCost") or 0.0))
        self.base_drain = max(0.0, float(rspec.get("baseDrainPerSec") or 0.0))
        self.max_enemies_drain = int(rspec["maxEnemiesDrain"]) if rspec.get("maxEnemiesDrain") is not None else None
        self.is_channeled = bool(rspec.get("isChanneled", False))
        self.prevents_regen = bool(rspec.get("preventsPassiveEnergyRegen", False))
        self.base_duration = float(rspec["baseDurationSec"]) if rspec.get("baseDurationSec") is not None else None
        self.invuln_duration = float(rspec.get("invulnerabilityDurationSec") or 0.0)
        self.fixed_duration = bool(rspec.get("fixedDuration", False))
        self.bonus_sec_per_100_shields = (
            float(rspec["bonusSecPer100Shields"]) if rspec.get("bonusSecPer100Shields") is not None else 0.0
        )
        self.kill_extend_sec = float(rspec.get("killExtendSec") or 0.0)
        self.cooldown_sec = float(rspec.get("cooldownSec") or 0.0)
        self.base_cast_time = max(0.0, float(rspec.get("baseCastTimeSec") or 0.0))
        self.one_handed = bool(rspec.get("oneHandedNonBlocking", False))
        self.recastable = bool(rspec.get("recastableWhileActive", True))
        self.nominal_slot_strength = max(0.01, float(nominal_slot_strength))
        self.uncond_slot_strength = max(0.01, float(uncond_slot_strength))
        self.special = dict(rspec["specialEconomy"]) if isinstance(rspec.get("specialEconomy"), Mapping) else {}

        self.active = False
        self.active_until = -math.inf
        self.cycle_until = -math.inf
        self.cooldown_until = -math.inf
        self.snap_strength = self.uncond_slot_strength
        self.first_cast_strength: float | None = None
        self.casts = 0
        self.active_seconds = 0.0
        self.vacuum_seconds = 0.0
        self.unaffordable = False

    def is_buff_active(self, t: float) -> bool:
        if not self.active:
            return False
        if self.is_channeled or self.base_duration is None:
            return True
        return t < self.active_until - EPS

    def needs_recast(self, t: float) -> bool:
        if self.unaffordable:
            return False
        if t < self.cooldown_until - EPS:
            return False
        if self.is_channeled or self.base_duration is None:
            return not self.active
        # Covenant cannot be recast until both invuln + crit buff cycle end
        gate_end = max(self.active_until, self.cycle_until)
        return t >= gate_end - EPS


class WarframeRotationSimulator:
    """Deterministic event-driven Warframe ability rotation & orb economy state machine."""

    def __init__(
        self,
        warframe_result: Mapping[str, Any],
        *,
        uncond_warframe_result: Mapping[str, Any] | None = None,
        active_ability_ids: Sequence[str] = (),
        companion_eval: Mapping[str, Any] | None = None,
        rotation_config: Mapping[str, Any] | None = None,
        seed: int = 1,
        on_shield_restore: Callable[[float], None] | None = None,
        on_health_restore: Callable[[float, float], None] | None = None,
    ) -> None:
        cfg = rotation_config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.allow_one_handed_firing = bool(cfg.get("allowOneHandedFiring", False))
        raw_co = cfg.get("castOrder")
        self.cast_order: list[str] = (
            [str(x).strip() for x in raw_co if str(x).strip()]
            if isinstance(raw_co, (list, tuple))
            else []
        )
        self.seed = int(seed)
        self._rng_idx = 0
        self._on_shield_restore = on_shield_restore
        self._on_health_restore = on_health_restore

        wb = warframe_result.get("weaponBridge") or {}
        panel = wb.get("panel") or warframe_result.get("finalPanel") or {}
        surv = wb.get("survivability") or warframe_result.get("survivability") or {}
        econ = wb.get("energyEconomy") or {}

        uncond_wb = (uncond_warframe_result or {}).get("weaponBridge") or {}
        uncond_panel = uncond_wb.get("panel") or (uncond_warframe_result or {}).get("finalPanel") or panel

        self.max_energy = max(0.0, float(econ.get("maxEnergy") if econ.get("maxEnergy") is not None else (panel.get("energy") or 0.0)))
        self.spawn_energy = min(
            self.max_energy,
            max(0.0, float(econ.get("spawnEnergy") if econ.get("spawnEnergy") is not None else self.max_energy)),
        )
        self.energy = self.spawn_energy

        self.max_health = max(1.0, float(panel.get("health") or 300.0))
        self.health = self.max_health
        self.max_shield = max(0.0, float(panel.get("shield") or 0.0))
        self.shield = self.max_shield
        self.max_overshield = 1200.0 if (self.max_shield > 0.0 and not surv.get("catalyzingShields")) else 0.0
        self.overshield = 0.0
        self.energy_to_shield_ratio = max(0.0, float(surv.get("energyToShieldRatio") or 0.0))

        self.nominal_strength = float(panel.get("abilityStrength") or 1.0)
        self.nominal_four_strength = float(panel.get("abilityFourStrength") or self.nominal_strength)
        self.uncond_strength = float(uncond_panel.get("abilityStrength") or self.nominal_strength)
        self.uncond_four_strength = float(uncond_panel.get("abilityFourStrength") or self.uncond_strength)

        self.nominal_duration = max(0.01, float(panel.get("abilityDuration") or 1.0))
        self.uncond_duration = max(0.01, float(uncond_panel.get("abilityDuration") or self.nominal_duration))

        self.base_eff = float(panel.get("abilityEfficiency") or 1.0)
        self.base_uncapped_eff = float(panel.get("uncappedAbilityEfficiency") or self.base_eff)
        self.base_casting_speed_bonus = float(econ.get("castingSpeedBonus") or panel.get("castingSpeed") or 0.0)

        self.passive_energy_regen = max(0.0, float(econ.get("passiveEnergyRegen") or 0.0))
        self.archon_stretch_regen = max(0.0, float(econ.get("archonStretchRegen") or 0.0))
        self.equilibrium_ratio = max(0.0, float(econ.get("equilibriumRatio") or 0.0))
        self.amber_energy_orb_bonus = max(0.0, float(econ.get("amberEnergyOrbBonus") or 0.0))
        self.amber_health_orb_bonus = max(0.0, float(econ.get("amberHealthOrbBonus") or 0.0))
        self.energy_conversion_bonus = max(0.0, float(econ.get("energyConversionBonus") or 0.0))
        self.health_conversion_armor = max(0.0, float(econ.get("healthConversionArmorPerStack") or 0.0))
        self.rage_ratio = max(0.0, float(econ.get("rageDamageToEnergyRatio") or 0.0))

        # Subtract conditional Energy Conversion / Molt Augmented from uncond_strength if uncond_warframe_result wasn't passed
        self.molt_augmented_cfg = econ.get("moltAugmented") if isinstance(econ.get("moltAugmented"), Mapping) else None
        self.molt_efficiency_cfg = econ.get("moltEfficiency") if isinstance(econ.get("moltEfficiency"), Mapping) else None
        self.energize_cfg = econ.get("arcaneEnergize") if isinstance(econ.get("arcaneEnergize"), Mapping) else None
        self.steadfast_cfg = econ.get("arcaneSteadfast") if isinstance(econ.get("arcaneSteadfast"), Mapping) else None
        self.pulse_cfg = econ.get("arcanePulse") if isinstance(econ.get("arcanePulse"), Mapping) else None
        self.blessing_cfg = econ.get("arcaneBlessing") if isinstance(econ.get("arcaneBlessing"), Mapping) else None
        self.reconstruct_cfg = econ.get("moltReconstruct") if isinstance(econ.get("moltReconstruct"), Mapping) else None
        self.universal_fallout_cfg = econ.get("arcaneUniversalFallout") if isinstance(econ.get("arcaneUniversalFallout"), Mapping) else None

        self.arbucep_empowered = bool(cfg.get("arbucepEmpowered", econ.get("arbucepEmpowered", False)))
        self.brightbonnet_mushrooms = max(1, min(2, int(cfg.get("brightbonnetMushrooms") or (2 if self.arbucep_empowered else 1))))
        self.inner_might_cooldown = max(0.0, float(econ.get("focusInnerMightCooldownSec") or 0.0))
        self.inner_might_ready = self.inner_might_cooldown > 0.0
        self.inner_might_next_at = math.inf
        self.inner_might_procs = 0
        self.focus_energy_pulse_bonus = max(0.0, float(econ.get("focusEnergyPulseBonus") or 0.0))
        self.focus_kill_energy_orb_chance = max(0.0, float(econ.get("focusKillEnergyOrbChance") or 0.0))
        self.focus_firing_duty_multiplier = max(0.5, min(1.0, float(econ.get("focusFiringDutyMultiplier") or 1.0)))
        self.squad_nourish_multiplier = max(1.0, float(econ.get("squadNourishMultiplier") or 1.0))
        self.squad_brightbonnet_eps = max(0.0, float(econ.get("squadBrightbonnetEnergyPerSec") or 0.0))
        self.squad_kill_energy_orb_chance = max(0.0, float(econ.get("squadKillEnergyOrbChance") or 0.0))
        self.squad_kill_health_orb_chance = max(0.0, float(econ.get("squadKillHealthOrbChance") or 0.0))
        self.squad_triggers_archon_stretch = bool(econ.get("squadTriggersArchonStretch", False))

        if uncond_warframe_result is None:
            cond_str_deduct = self.energy_conversion_bonus
            if self.molt_augmented_cfg:
                cond_str_deduct += float(self.molt_augmented_cfg["strengthPerKill"]) * float(self.molt_augmented_cfg["maxStacks"])
            if cond_str_deduct > 0.0:
                self.uncond_strength = max(0.1, self.nominal_strength - cond_str_deduct)
                self.uncond_four_strength = max(0.1, self.nominal_four_strength - cond_str_deduct)
            if self.molt_efficiency_cfg and self.max_shield > 0.0:
                self.uncond_duration = max(0.05, self.nominal_duration - float(self.molt_efficiency_cfg["maxDurationBonus"]))

        self.comp_econ = _extract_companion_economy(companion_eval)

        # Dynamic runtime states
        self.t = 0.0
        self.kills = 0
        self.molt_augmented_stacks = 0
        self.molt_efficiency_bonus = 0.0
        self.energy_conversion_armed = False
        self.empower_armed = False
        self.health_conversion_stacks = 0
        self.blessing_stacks = 0
        self.free_cast_charges = 0
        self.mystic_precept_counter = 0
        self.next_companion_precept_at = (
            float(self.comp_econ["companionPreceptInterval"])
            if float(self.comp_econ["companionPreceptInterval"]) > 0.0
            else math.inf
        )
        self.archon_stretch_until = math.inf if (self.squad_triggers_archon_stretch and self.archon_stretch_regen > 0.0) else -math.inf
        self.energize_cd_until = -math.inf
        self.pulse_cd_until = -math.inf
        self.duplex_energy_accum = 0.0
        self.duplex_clone_expiries: list[float] = []
        self.seismic_stacks = 0
        self.seismic_until = -math.inf
        self.active_enemies_near = 4

        # Casting state
        self.casting_item: _RotationSlotItem | None = None
        self.casting_free_used = False
        self.cast_start = -math.inf
        self.cast_until = -math.inf
        self.weapon_locked_until = -math.inf
        self.external_channel_active = False

        # Periodic ability economy timers
        self.dispensary_next_at = math.inf
        self.brightbonnet_next_at = math.inf
        self.ev_next_at = math.inf

        # Telemetry counters
        self.total_casts = 0
        self.free_casts_used = 0
        self.steadfast_procs = 0
        self.energize_procs = 0
        self.pulse_procs = 0
        self.energy_orbs_picked = 0
        self.health_orbs_picked = 0
        self.total_energy_spent = 0.0
        self.total_energy_gained = 0.0
        self.equilibrium_energy_from_health = 0.0
        self.equilibrium_health_from_energy = 0.0
        self.weapon_cast_pause_seconds = 0.0
        self.channel_starved_count = 0

        # Build custom-ordered (default 1 -> 2 -> 3 -> 4) eligible non-damaging rotation items
        self.always_on_ids: set[str] = set()
        self.excluded_ids: set[str] = set()
        self.item_by_ability_id: dict[str, _RotationSlotItem] = {}
        self.items: list[_RotationSlotItem] = []
        self._build_items(wb, active_ability_ids)

        # Start initial casts at t = 0.0!
        if self.enabled and self.items:
            self._try_start_next_cast(0.0)

    def _rng(self, stream: int = 73) -> float:
        val = _det_random(self.seed, self._rng_idx, stream)
        self._rng_idx += 1
        return val

    def _item_needs_cast(self, item: _RotationSlotItem, t: float) -> bool:
        if "nextCastStrengthBonus" in item.special:
            if item.unaffordable or self.empower_armed:
                return False
            return any(
                other is not item
                and "nextCastStrengthBonus" not in other.special
                and other.needs_recast(t)
                for other in self.items
            )
        return item.needs_recast(t)

    def _build_items(self, wb: Mapping[str, Any], active_ability_ids: Sequence[str]) -> None:
        wanted = {str(x).strip() for x in (active_ability_ids or ()) if str(x).strip()}
        avail = wb.get("availableAbilities") or ()
        slot_abilities = (wb.get("energyEconomy") or {}).get("slotAbilities") or ()
        slot_by_idx: dict[int, Mapping[str, Any]] = {
            int(sa["slot"]): sa
            for sa in slot_abilities
            if isinstance(sa, Mapping) and isinstance(sa.get("slot"), int)
        }
        grouped: dict[tuple[Any, ...], dict[str, Any]] = {}

        for idx, ab in enumerate(avail):
            if not isinstance(ab, Mapping):
                continue
            ab_id = str(ab.get("id") or "")
            ab_path = str(ab.get("abilityPath") or "")
            mod_path = str(ab.get("modPath") or "")
            slot_raw = ab.get("slot")
            slot_idx = int(slot_raw) if isinstance(slot_raw, int) and 0 <= int(slot_raw) <= 3 else None
            slot_token = f"slot-{slot_idx + 1}" if slot_idx is not None else ""
            is_passive_aug = bool(ab.get("isAugment") and not ab_path)
            rspec = ab.get("rotationSpec") if isinstance(ab.get("rotationSpec"), Mapping) else {}
            slot_meta = slot_by_idx.get(slot_idx) if slot_idx is not None else None
            if rspec.get("rotationEligible") is False or (slot_meta and slot_meta.get("rotationEligible") is False):
                if ab_id:
                    self.excluded_ids.add(ab_id)
                continue
            if not ({ab_id, ab_path, mod_path, slot_token} & wanted):
                if not is_passive_aug:
                    continue
            if rspec.get("passiveAlwaysOn"):
                self.always_on_ids.add(ab_id)
                continue
            # Group co-slot ability + its own augment into one physical slot cast
            gkey = ("slot", slot_idx, _path_token(ab_path)) if (slot_idx is not None and ab_path) else ("id", ab_id)
            if gkey not in grouped:
                grouped[gkey] = {
                    "order": (slot_idx if slot_idx is not None else 4, idx),
                    "slot_idx": slot_idx,
                    "primary_id": ab_id,
                    "member_ids": [ab_id, *([slot_token] if slot_token else [])],
                    "ability_path": ab_path or None,
                    "name_zh": str(ab.get("nameZh") or ab.get("nameEn") or ab_id),
                    "name_en": str(ab.get("nameEn") or ab_id),
                    "is_helminth": bool(ab.get("isHelminth")),
                    "rspec": dict(rspec),
                }
            else:
                g = grouped[gkey]
                if ab_id not in g["member_ids"]:
                    g["member_ids"].append(ab_id)
                # Prefer base ability name & base duration unless only augment has a timed buff duration
                if not ab.get("isAugment"):
                    g["primary_id"] = ab_id
                    g["name_zh"] = str(ab.get("nameZh") or g["name_zh"])
                    g["name_en"] = str(ab.get("nameEn") or g["name_en"])
                if g["rspec"].get("baseDurationSec") is None and rspec.get("baseDurationSec") is not None:
                    g["rspec"]["baseDurationSec"] = rspec["baseDurationSec"]

        # Admit any eligible non-damaging slotAbilities requested in activeAbilities (survivability, CC, debuff, energy)
        for sa in slot_abilities:
            if not isinstance(sa, Mapping):
                continue
            sa_id = str(sa.get("id") or "")
            sa_path = str(sa.get("abilityPath") or "")
            slot_idx = int(sa.get("slot") or 0)
            slot_token = f"slot-{slot_idx + 1}"
            if sa.get("rotationEligible") is False:
                if sa_id:
                    self.excluded_ids.add(sa_id)
                self.excluded_ids.add(slot_token)
                continue
            if not ({sa_id, sa_path, slot_token} & wanted):
                continue
            gkey = ("slot", slot_idx, _path_token(sa_path))
            if gkey in grouped:
                if sa_id and sa_id not in grouped[gkey]["member_ids"]:
                    grouped[gkey]["member_ids"].append(sa_id)
                continue
            grouped[gkey] = {
                "order": (slot_idx, 100 + slot_idx),
                "slot_idx": slot_idx,
                "primary_id": sa_id or slot_token,
                "member_ids": list(dict.fromkeys([x for x in (sa_id, slot_token) if x])),
                "ability_path": sa_path or None,
                "name_zh": str(sa.get("nameZh") or sa.get("nameEn") or sa_id),
                "name_en": str(sa.get("nameEn") or sa_id),
                "is_helminth": bool(sa.get("isHelminth")),
                "rspec": dict(sa),
            }

        order_rank: dict[str, int] = {}
        for pos, tok in enumerate(self.cast_order):
            order_rank.setdefault(tok, pos)
            order_rank.setdefault(_path_token(tok), pos)

        def _sort_key(g: Mapping[str, Any]) -> tuple[int, int, int, int]:
            candidates = [
                str(g.get("primary_id") or ""),
                *(str(m) for m in (g.get("member_ids") or ())),
                str(g.get("ability_path") or ""),
                _path_token(g.get("ability_path")),
            ]
            best_pos: int | None = None
            for c in candidates:
                if c and c in order_rank:
                    p = order_rank[c]
                    best_pos = p if best_pos is None else min(best_pos, p)
            ord_tup = g["order"]
            if best_pos is not None:
                return (0, best_pos, int(ord_tup[0]), int(ord_tup[1]))
            return (1, int(ord_tup[0]), int(ord_tup[0]), int(ord_tup[1]))

        for g in sorted(grouped.values(), key=_sort_key):
            s_idx = g["slot_idx"]
            nom_str = self.nominal_four_strength if s_idx == 3 else self.nominal_strength
            unc_str = self.uncond_four_strength if s_idx == 3 else self.uncond_strength
            item = _RotationSlotItem(
                slot_order=g["order"],
                slot_index=s_idx,
                primary_id=g["primary_id"],
                member_ids=g["member_ids"],
                ability_path=g["ability_path"],
                name_zh=g["name_zh"],
                name_en=g["name_en"],
                is_helminth=g["is_helminth"],
                rspec=g["rspec"],
                nominal_slot_strength=nom_str,
                uncond_slot_strength=unc_str,
            )
            self.items.append(item)
            for mid in item.member_ids:
                self.item_by_ability_id[mid] = item

    def current_efficiency(self, t: float) -> tuple[float, float]:
        seismic_bonus = (
            self.seismic_stacks * float(self.comp_econ["seismicBondPerStack"])
            if t < self.seismic_until - EPS
            else 0.0
        )
        uncapped = self.base_uncapped_eff + seismic_bonus
        capped = min(1.75, max(0.0, uncapped))
        return capped, uncapped

    def effective_activation_cost(self, item: _RotationSlotItem, t: float) -> float:
        if item.resource not in {"energy", "shield"} or item.base_cost <= 0.0:
            return 0.0
        capped_eff, _ = self.current_efficiency(t)
        return item.base_cost * max(0.25, 2.0 - capped_eff)

    def effective_drain_per_sec(self, item: _RotationSlotItem, t: float) -> float:
        if not item.is_channeled or item.base_drain <= 0.0 or item.resource not in {"energy", "shield"}:
            return 0.0
        _, uncapped_eff = self.current_efficiency(t)
        dur = max(0.01, self.uncond_duration + self.molt_efficiency_bonus)
        per_unit = item.base_drain * max(0.25, (2.0 - uncapped_eff) / dur)
        if item.max_enemies_drain is not None:
            enemies = max(0, min(int(item.max_enemies_drain), int(self.active_enemies_near)))
            return per_unit * enemies
        return per_unit

    def current_nourish_multiplier(self, t: float) -> float:
        mult = self.squad_nourish_multiplier
        for item in self.items:
            if not item.is_buff_active(t):
                continue
            sp = item.special
            if "nourishEnergyMultiplierBase" in sp:
                base_m = float(sp["nourishHelminthMultiplierBase"] if item.is_helminth else sp["nourishEnergyMultiplierBase"])
                mult = max(mult, 1.0 + base_m * item.snap_strength)
        return mult

    def current_casting_speed_multiplier(self, t: float) -> float:
        bonus = self.base_casting_speed_bonus
        for item in self.items:
            if item.is_buff_active(t) and "castingSpeedBonusBase" in item.special:
                dur_mult = self.uncond_duration + self.molt_efficiency_bonus
                bonus += float(item.special["castingSpeedBonusBase"]) * (
                    dur_mult if item.special.get("castingSpeedScalesWithDuration") else 1.0
                )
        return max(0.1, 1.0 + bonus)

    def current_passive_regen_rate(self, t: float) -> float:
        if self.external_channel_active or any(it.is_buff_active(t) and it.prevents_regen for it in self.items):
            return 0.0
        rate = self.passive_energy_regen
        if self.archon_stretch_regen > 0.0 and t < self.archon_stretch_until - EPS:
            rate += self.archon_stretch_regen
        for item in self.items:
            if item.is_buff_active(t) and "passiveEnergyRegenBase" in item.special:
                base_r = float(item.special["passiveEnergyRegenBase"])
                rate += base_r * (item.snap_strength if item.special.get("scalesWithStrength") else 1.0)
        return rate * self.current_nourish_multiplier(t)

    def is_casting(self, t: float) -> bool:
        return self.casting_item is not None and t < self.cast_until - EPS

    def is_weapon_locked(self, t: float) -> bool:
        return self.enabled and t < self.weapon_locked_until - EPS

    def ability_strength_ratio(self, ability_id: str, t: float) -> float:
        if not self.enabled:
            return 1.0
        if ability_id in self.excluded_ids:
            return 0.0
        if ability_id in self.always_on_ids:
            return 1.0
        item = self.item_by_ability_id.get(ability_id)
        if item is None:
            return 1.0
        if not item.is_buff_active(t):
            return 0.0
        return max(0.0, item.snap_strength / max(0.01, item.nominal_slot_strength))

    def _finish_current_cast(self, finish_t: float) -> None:
        item = self.casting_item
        if item is None:
            return
        self.casting_item = None
        molt_aug_bonus = 0.0
        if self.molt_augmented_cfg:
            molt_aug_bonus = self.molt_augmented_stacks * float(self.molt_augmented_cfg["strengthPerKill"])
        ec_bonus = self.energy_conversion_bonus if self.energy_conversion_armed else 0.0
        emp_bonus = 0.50 if self.empower_armed else 0.0

        snap_str = item.uncond_slot_strength + molt_aug_bonus + ec_bonus + emp_bonus
        if "nextCastStrengthBonus" in item.special:
            self.empower_armed = True
            self.energy_conversion_armed = False
        else:
            if self.energy_conversion_armed:
                self.energy_conversion_armed = False
            if self.empower_armed:
                self.empower_armed = False
                for emp_it in self.items:
                    if "nextCastStrengthBonus" in emp_it.special:
                        emp_it.active = False
                        emp_it.active_until = finish_t

        # Penance preserves first-cast strength snapshot when refreshed while active; fresh cast updates it
        if item.bonus_sec_per_100_shields > 0.0 and item.first_cast_strength is not None and item.active:
            item.snap_strength = item.first_cast_strength
        else:
            item.snap_strength = snap_str
            item.first_cast_strength = snap_str

        dur_mult = 1.0 if item.fixed_duration else max(0.05, self.uncond_duration + self.molt_efficiency_bonus)
        item.active = True
        item.casts += 1
        self.total_casts += 1

        if item.cooldown_sec > 0.0 and item.resource == "cooldown":
            item.cooldown_until = finish_t + item.cooldown_sec

        if item.is_channeled or item.base_duration is None:
            item.active_until = math.inf
            item.cycle_until = math.inf
        else:
            eff_dur = item.base_duration * dur_mult
            if item.bonus_sec_per_100_shields > 0.0:
                sacrificed = self.shield + self.overshield
                self.shield = 0.0
                self.overshield = 0.0
                eff_dur = min(120.0, eff_dur + (sacrificed / 100.0) * item.bonus_sec_per_100_shields * dur_mult)
            item.active_until = finish_t + eff_dur
            item.cycle_until = finish_t + (eff_dur + item.invuln_duration * dur_mult)

        # Schedule periodic economy effects if applicable
        if "dispensaryCycleSec" in item.special:
            self.dispensary_next_at = finish_t + float(item.special.get("dispensaryInitialDelaySec", 3.0))
        if "pulseIntervalSec" in item.special:
            # NokkoPowerShroom.lua fires an immediate pulse on spawn, then every 2.8571s (1.3333s when Arbucep empowered)
            base_p = float(item.special["helminthPulseEnergyBase"] if item.is_helminth else item.special["pulseEnergyBase"])
            init_gain = base_p * item.snap_strength * self.brightbonnet_mushrooms * self.current_nourish_multiplier(finish_t)
            self._gain_energy(init_gain)
            bb_iv = (
                float(item.special.get("empoweredPulseIntervalSec", 1.3333))
                if self.arbucep_empowered
                else float(item.special["pulseIntervalSec"])
            )
            self.brightbonnet_next_at = finish_t + bb_iv
        if "totalPulseEnergyBase" in item.special:
            gain = float(item.special["totalPulseEnergyBase"]) * item.snap_strength * self.current_nourish_multiplier(finish_t)
            self._gain_energy(gain)

        # Shock Trooper / Conductive Sphere / Volt Speed / Electric Shield / Gyre abilities trigger Archon Stretch
        if self.archon_stretch_regen > 0.0 and any(
            tok in (item.primary_id or "") for tok in ("shock", "volt", "electric", "conductive", "cathode")
        ):
            self.archon_stretch_until = finish_t + 5.0

    def _gain_energy(self, amount: float) -> float:
        if amount <= 0.0 or self.max_energy <= 0.0:
            return 0.0
        before = self.energy
        self.energy = min(self.max_energy, self.energy + amount)
        actual = max(0.0, self.energy - before)
        self.total_energy_gained += actual
        return actual

    def _spend_energy(self, amount: float, t: float) -> None:
        if amount <= 0.0:
            return
        self.energy = max(0.0, self.energy - amount)
        self.total_energy_spent += amount
        if self.energy_to_shield_ratio > 0.0 and self.max_shield > 0.0:
            sh_gain = amount * self.energy_to_shield_ratio
            room = max(0.0, self.max_shield - self.shield)
            to_sh = min(room, sh_gain)
            self.shield += to_sh
            rem = sh_gain - to_sh
            if rem > 0.0 and self.max_overshield > 0.0:
                self.overshield = min(self.max_overshield, self.overshield + rem)
            if self._on_shield_restore is not None:
                self._on_shield_restore(sh_gain)
        if self.reconstruct_cfg:
            hp_gain = amount * float(self.reconstruct_cfg["healPerEnergy"])
            self.health = min(self.max_health, self.health + hp_gain)
            if self._on_health_restore is not None:
                self._on_health_restore(hp_gain, 0.0)
        if float(self.comp_econ["duplexBondOrbChance"]) > 0.0:
            self.duplex_energy_accum += amount
            self.duplex_clone_expiries = [ex for ex in self.duplex_clone_expiries if ex > t + EPS]
            while self.duplex_energy_accum >= 100.0 - EPS:
                self.duplex_energy_accum -= 100.0
                if len(self.duplex_clone_expiries) < 3:
                    self.duplex_clone_expiries.append(t + 30.0)
                else:
                    self.duplex_clone_expiries.sort()
                    self.duplex_clone_expiries[0] = t + 30.0

    def _try_start_next_cast(self, t: float) -> None:
        if not self.enabled or self.is_casting(t):
            return
        for item in self.items:
            if not self._item_needs_cast(item, t):
                continue
            eff_cost = self.effective_activation_cost(item, t)
            # For channeled abilities, require at least activation + 0.5s of drain to prevent 0s rapid flicker
            min_required = eff_cost + (0.5 * self.effective_drain_per_sec(item, t) if item.is_channeled else 0.0)

            used_free = False
            if item.resource == "energy":
                if self.inner_might_ready and eff_cost > 0.0:
                    used_free = True
                    self.inner_might_ready = False
                    self.inner_might_next_at = t + self.inner_might_cooldown
                    self.free_casts_used += 1
                    self.inner_might_procs += 1
                elif self.free_cast_charges > 0 and eff_cost > 0.0:
                    used_free = True
                    self.free_cast_charges -= 1
                    self.free_casts_used += 1
                elif min_required > self.max_energy + EPS:
                    # Permanently exceeds max energy capacity — mark unaffordable so lower-priority slots are not deadlocked!
                    item.unaffordable = True
                    continue
                elif self.energy + EPS < min_required:
                    # Strict 1 -> 2 -> 3 -> 4 priority: wait in vacuum period until orbs/regen supply enough energy!
                    return
                else:
                    self._spend_energy(eff_cost, t)
                    if self.steadfast_cfg and eff_cost > 0.0:
                        if self._rng(79) < float(self.steadfast_cfg["chance"]):
                            self.free_cast_charges = int(self.steadfast_cfg["freeCasts"])
                            self.steadfast_procs += 1
            elif item.resource == "shield":
                if self.inner_might_ready and eff_cost > 0.0:
                    used_free = True
                    self.inner_might_ready = False
                    self.inner_might_next_at = t + self.inner_might_cooldown
                    self.free_casts_used += 1
                    self.inner_might_procs += 1
                else:
                    avail_sh = self.shield + self.overshield
                    if eff_cost > self.max_shield + self.max_overshield + EPS:
                        item.unaffordable = True
                        continue
                    if avail_sh + EPS < eff_cost:
                        return
                    from_os = min(self.overshield, eff_cost)
                    self.overshield -= from_os
                    self.shield = max(0.0, self.shield - (eff_cost - from_os))

            cast_dur = (
                item.base_cast_time / self.current_casting_speed_multiplier(t)
                if item.base_cast_time > 0.0
                else 0.0
            )
            self.casting_item = item
            self.casting_free_used = used_free
            self.cast_start = t
            self.cast_until = t + cast_dur
            if cast_dur > 0.0 and not (item.one_handed and self.allow_one_handed_firing):
                self.weapon_locked_until = max(self.weapon_locked_until, self.cast_until)
            if cast_dur <= EPS:
                self._finish_current_cast(t)
                # Continue loop so a 0.0s instant ability (e.g. Volt Speed) immediately chains to the next slot!
                continue
            return

    def _advance_segment(self, target_t: float) -> None:
        dt = target_t - self.t
        if dt <= 0.0:
            return
        t0 = self.t

        # Track active / vacuum / weapon-lock seconds over [t0, target_t]
        if self.weapon_locked_until > t0:
            self.weapon_cast_pause_seconds += max(0.0, min(target_t, self.weapon_locked_until) - t0)

        any_channeled = False
        total_drain_rate = 0.0
        for item in self.items:
            if item.is_buff_active(t0):
                end_active = min(target_t, item.active_until)
                up_dt = max(0.0, end_active - t0)
                item.active_seconds += up_dt
                item.vacuum_seconds += max(0.0, target_t - end_active)
                if item.is_channeled:
                    any_channeled = True
                    total_drain_rate += self.effective_drain_per_sec(item, t0)
            else:
                item.vacuum_seconds += dt

        # Molt Efficiency ramp while shield > 0
        if self.molt_efficiency_cfg and self.max_shield > 0.0:
            if self.shield + self.overshield > EPS:
                self.molt_efficiency_bonus = min(
                    float(self.molt_efficiency_cfg["maxDurationBonus"]),
                    self.molt_efficiency_bonus + float(self.molt_efficiency_cfg["ratePerSec"]) * dt,
                )
            else:
                self.molt_efficiency_bonus = 0.0

        # Seismic Bond stacks while channeled ability active & companion assists
        if any_channeled and float(self.comp_econ["seismicBondPerStack"]) > 0.0 and self.comp_econ["canAssistDamage"]:
            self.seismic_stacks = min(10, self.seismic_stacks + max(1, int(dt * 2.0)))
            self.seismic_until = target_t + 12.0

        # Energy delta: passive regen + channel-bypassing Squad Brightbonnet minus channeled drain
        regen_rate = self.current_passive_regen_rate(t0)
        if self.squad_brightbonnet_eps > 0.0:
            regen_rate += self.squad_brightbonnet_eps * self.current_nourish_multiplier(t0)
        net_rate = regen_rate - total_drain_rate
        if net_rate > 0.0:
            self._gain_energy(net_rate * dt)
        elif net_rate < 0.0:
            drain_amt = (-net_rate) * dt
            if self.energy + EPS < drain_amt:
                # Channeled ability starved out of energy!
                spent = self.energy
                self._spend_energy(spent, target_t)
                for item in self.items:
                    if item.is_channeled and item.active:
                        item.active = False
                        item.active_until = target_t
                self.channel_starved_count += 1
            else:
                self._spend_energy(drain_amt, target_t)

        self.t = target_t

        # Expire timed buffs that ended at target_t
        for item in self.items:
            if item.active and not item.is_channeled and item.base_duration is not None and self.t >= item.active_until - EPS:
                item.active = False

        # Periodic companion precept triggers (Mystic Bond + Archon Stretch)
        while self.t >= self.next_companion_precept_at - EPS:
            interval = float(self.comp_econ["companionPreceptInterval"])
            if interval <= 0.0:
                self.next_companion_precept_at = math.inf
                break
            self.on_companion_precept(self.next_companion_precept_at, electric=bool(self.comp_econ["triggersArchonStretch"]))
            self.next_companion_precept_at += interval

        # Dispensary periodic orb drops
        if self.t >= self.dispensary_next_at - EPS:
            disp_item = next((it for it in self.items if "dispensaryCycleSec" in it.special and it.is_buff_active(self.t)), None)
            if disp_item is not None:
                extra_p = min(1.0, float(disp_item.special.get("extraDropChanceBase", 0.25)) * disp_item.snap_strength)
                mult_cnt = 2 if self._rng(83) < extra_p else 1
                for _ in range(mult_cnt):
                    self._pickup_health_orb(100.0, self.t)
                    self._pickup_energy_orb(25.0, self.t)
                self.dispensary_next_at = self.t + float(disp_item.special["dispensaryCycleSec"])
            else:
                self.dispensary_next_at = math.inf

        # Brightbonnet periodic energy pulse (bypasses channeled regen lock via PowerPool:AddEnergy)
        if self.t >= self.brightbonnet_next_at - EPS:
            bb_item = next((it for it in self.items if "pulseIntervalSec" in it.special and it.is_buff_active(self.t)), None)
            if bb_item is not None:
                base_p = float(bb_item.special["helminthPulseEnergyBase"] if bb_item.is_helminth else bb_item.special["pulseEnergyBase"])
                gain = base_p * bb_item.snap_strength * self.brightbonnet_mushrooms * self.current_nourish_multiplier(self.t)
                self._gain_energy(gain)
                bb_iv = (
                    float(bb_item.special.get("empoweredPulseIntervalSec", 1.3333))
                    if self.arbucep_empowered
                    else float(bb_item.special["pulseIntervalSec"])
                )
                self.brightbonnet_next_at = self.t + bb_iv
            else:
                self.brightbonnet_next_at = math.inf

        # Zenurik Inner Might periodic free cast recharge
        if self.t >= self.inner_might_next_at - EPS:
            self.inner_might_ready = True
            self.inner_might_next_at = math.inf

        # Finish cast if due
        if self.casting_item is not None and self.t >= self.cast_until - EPS:
            self._finish_current_cast(self.t)

        # Start next needed cast if ready
        self._try_start_next_cast(self.t)

    def advance(self, target_t: float) -> None:
        """Advance state machine accurately across all intermediate internal transition points up to target_t."""
        target_t = float(target_t)
        if not self.enabled or target_t <= self.t + EPS:
            self.t = max(self.t, target_t)
            return
        guard = 0
        while self.t < target_t - EPS and guard < 512:
            guard += 1
            nxt = min(target_t, self.next_event_time(self.t))
            if nxt <= self.t + 1e-7:
                nxt = min(target_t, self.t + 1e-4)
            self._advance_segment(nxt)

    def next_event_time(self, now_t: float | None = None) -> float:
        t = self.t if now_t is None else float(now_t)
        if not self.enabled:
            return math.inf
        candidates: list[float] = [
            self.dispensary_next_at,
            self.brightbonnet_next_at,
            self.inner_might_next_at,
            self.next_companion_precept_at,
        ]
        if self.casting_item is not None and self.cast_until > t + EPS:
            candidates.append(self.cast_until)
        if self.weapon_locked_until > t + EPS:
            candidates.append(self.weapon_locked_until)

        total_drain = 0.0
        first_waiting: _RotationSlotItem | None = None
        for item in self.items:
            if item.active and not item.is_channeled and item.active_until > t + EPS:
                candidates.append(item.active_until)
            if item.cycle_until > t + EPS and item.cycle_until > item.active_until + EPS:
                candidates.append(item.cycle_until)
            if item.cooldown_until > t + EPS:
                candidates.append(item.cooldown_until)
            if item.is_buff_active(t) and item.is_channeled:
                total_drain += self.effective_drain_per_sec(item, t)
            if first_waiting is None and self._item_needs_cast(item, t):
                first_waiting = item

        regen_rate = self.current_passive_regen_rate(t)
        if self.squad_brightbonnet_eps > 0.0:
            regen_rate += self.squad_brightbonnet_eps * self.current_nourish_multiplier(t)
        net_rate = regen_rate - total_drain
        if net_rate < -EPS and self.energy > EPS:
            candidates.append(t + self.energy / (-net_rate))
        elif first_waiting is not None and self.casting_item is None and first_waiting.resource == "energy":
            req = self.effective_activation_cost(first_waiting, t)
            if first_waiting.is_channeled:
                req += 0.5 * self.effective_drain_per_sec(first_waiting, t)
            if self.energy + EPS < req <= self.max_energy + EPS and net_rate > EPS:
                candidates.append(t + (req - self.energy) / net_rate)

        valid = [c for c in candidates if c > t + EPS]
        return min(valid) if valid else math.inf

    def _pickup_energy_orb(self, base_energy: float, t: float) -> bool:
        want_energy = self.energy < self.max_energy - 1e-6
        want_eq_hp = self.equilibrium_ratio > 0.0 and self.health < self.max_health - 1e-6
        want_ec = self.energy_conversion_bonus > 0.0 and not self.energy_conversion_armed
        if not (want_energy or want_eq_hp or want_ec):
            return False

        self.energy_orbs_picked += 1
        nourish_m = self.current_nourish_multiplier(t)
        direct_e = base_energy * (1.0 + self.amber_energy_orb_bonus) * (1.0 + self.focus_energy_pulse_bonus) * nourish_m
        self._gain_energy(direct_e)

        if self.equilibrium_ratio > 0.0:
            conv_hp = float(math.floor(base_energy * self.equilibrium_ratio + 1e-9))
            if conv_hp > 0.0:
                self.health = min(self.max_health, self.health + conv_hp)
                self.equilibrium_health_from_energy += conv_hp
                if self._on_health_restore is not None:
                    self._on_health_restore(conv_hp, 0.0)

        if self.energy_conversion_bonus > 0.0:
            self.energy_conversion_armed = True

        if self.energize_cfg and t >= self.energize_cd_until - EPS:
            if self._rng(89) < float(self.energize_cfg["chance"]):
                ez_gain = float(self.energize_cfg["energy"]) * nourish_m
                self._gain_energy(ez_gain)
                self.energize_cd_until = t + float(self.energize_cfg["cooldown"])
                self.energize_procs += 1
        return True

    def _pickup_health_orb(self, base_hp: float, t: float) -> bool:
        want_hp = self.health < self.max_health - 1e-6
        want_eq_e = self.equilibrium_ratio > 0.0 and self.energy < self.max_energy - 1e-6
        want_blessing = bool(self.blessing_cfg and self.blessing_stacks < int(self.blessing_cfg["maxStacks"]))
        want_hc = self.health_conversion_armor > 0.0 and self.health_conversion_stacks < 3
        want_synth = bool(self.comp_econ["synthFiberEquipped"])
        if not (want_hp or want_eq_e or want_blessing or want_hc or want_synth):
            return False

        self.health_orbs_picked += 1
        max_hp_delta = 0.0
        if want_blessing and self.blessing_cfg:
            self.blessing_stacks += 1
            max_hp_delta = float(self.blessing_cfg["hpPerOrb"])
            self.max_health += max_hp_delta

        direct_hp = base_hp * (1.0 + self.amber_health_orb_bonus)
        self.health = min(self.max_health, self.health + direct_hp + max_hp_delta)

        pulse_hp = 0.0
        if self.pulse_cfg and t >= self.pulse_cd_until - EPS:
            if self._rng(97) < float(self.pulse_cfg["chance"]):
                pulse_hp = float(self.pulse_cfg["heal"])
                self.health = min(self.max_health, self.health + pulse_hp)
                self.pulse_cd_until = t + float(self.pulse_cfg["cooldown"])
                self.pulse_procs += 1

        if self._on_health_restore is not None:
            self._on_health_restore(direct_hp + pulse_hp + max_hp_delta, max_hp_delta)

        if self.health_conversion_armor > 0.0:
            self.health_conversion_stacks = min(3, self.health_conversion_stacks + 1)

        # Client rule: Amber Health Orb bonus does NOT amplify Equilibrium converted energy; Nourish DOES!
        if self.equilibrium_ratio > 0.0:
            nourish_m = self.current_nourish_multiplier(t)
            conv_e = float(math.floor(base_hp * self.equilibrium_ratio + 1e-9)) * nourish_m
            if conv_e > 0.0:
                self._gain_energy(conv_e)
                self.equilibrium_energy_from_health += conv_e
        return True

    def on_companion_precept(self, t: float, *, electric: bool = False) -> None:
        if not self.enabled:
            return
        if electric and self.archon_stretch_regen > 0.0:
            self.archon_stretch_until = max(self.archon_stretch_until, float(t) + 5.0)
        req = int(self.comp_econ["mysticBondRequiredCasts"])
        if req > 0:
            self.mystic_precept_counter += 1
            if self.mystic_precept_counter >= req:
                self.mystic_precept_counter = 0
                self.free_cast_charges = max(self.free_cast_charges, 1)
                self._try_start_next_cast(float(t))

    def on_health_damage_taken(self, hp_damage: float, t: float) -> None:
        if not self.enabled or hp_damage <= 0.0:
            return
        if self.health_conversion_stacks > 0:
            self.health_conversion_stacks = max(0, self.health_conversion_stacks - 1)
        if self.rage_ratio > 0.0:
            gain = hp_damage * self.rage_ratio * self.current_nourish_multiplier(float(t))
            self._gain_energy(gain)
            self._try_start_next_cast(float(t))

    def on_enemy_kill(
        self,
        t: float,
        *,
        is_eximus: bool = False,
        companion_damaged: bool | None = None,
        headshot: bool = False,
        is_melee: bool = False,
        radiation_stacks: int = 0,
    ) -> None:
        if not self.enabled:
            return
        t = float(t)
        self.advance(t)
        self.kills += 1
        if self.molt_augmented_cfg:
            self.molt_augmented_stacks = min(int(self.molt_augmented_cfg["maxStacks"]), self.kills)

        # Cathode Grace kill extension
        for item in self.items:
            if item.kill_extend_sec > 0.0 and item.is_buff_active(t):
                dur_mult = max(0.05, self.uncond_duration + self.molt_efficiency_bonus)
                cap_sec = float(item.special.get("maxDurationBaseSec", 60.0)) * dur_mult
                item.active_until = min(t + cap_sec, item.active_until + item.kill_extend_sec)

        comp_hit = bool(self.comp_econ["canAssistDamage"]) if companion_damaged is None else bool(companion_damaged)

        # 1. Eximus guaranteed 2x Health Orb (50 HP) + 1x Small Energy Orb (25 Energy)
        if is_eximus:
            self._pickup_health_orb(50.0, t)
            self._pickup_health_orb(50.0, t)
            self._pickup_energy_orb(25.0, t)

        # 2. Normal enemy DROP_POWERUP (~10% Small Energy Orb = 25 Energy; Eximus also rolls its drop table)
        if self._rng(101) < 0.10:
            self._pickup_energy_orb(25.0, t)

        # 3. Companion Synth Deconstruct (25% Health Orb on assisted kill)
        synth_p = float(self.comp_econ["synthDeconstructChance"])
        if synth_p > 0.0 and comp_hit and self._rng(103) < synth_p:
            self._pickup_health_orb(50.0, t)

        # 4. Companion Duplex Bond clones (clones assist kills and drop 25E Energy Orbs at 50% rate)
        if self.duplex_clone_expiries:
            self.duplex_clone_expiries = [ex for ex in self.duplex_clone_expiries if ex > t + EPS]
            active_clones = len(self.duplex_clone_expiries)
            if active_clones > 0:
                clone_orb_p = min(0.50, 0.15 * active_clones * float(self.comp_econ["duplexBondOrbChance"]) / 0.50)
                if self._rng(107) < clone_orb_p:
                    self._pickup_energy_orb(25.0, t)

        # 5. Active ability kill-orb bonuses (Lycath's Hunt / Fractured Blast)
        for item in self.items:
            if not item.is_buff_active(t):
                continue
            sp = item.special
            if "meleeKillHealthOrbChance" in sp and is_melee:
                p_hp = float(sp["helminthMeleeKillHealthOrbChance"] if item.is_helminth else sp["meleeKillHealthOrbChance"])
                if self._rng(109) < p_hp:
                    self._pickup_health_orb(50.0, t)
            if "headshotKillEnergyOrbChance" in sp and headshot:
                p_en = float(sp["helminthHeadshotKillEnergyOrbChance"] if item.is_helminth else sp["headshotKillEnergyOrbChance"])
                if self._rng(113) < p_en:
                    self._pickup_energy_orb(25.0, t)
            if "killHealthOrbChance" in sp:
                p_hp2 = float(sp["helminthKillHealthOrbChance"] if item.is_helminth else sp["killHealthOrbChance"])
                p_en2 = float(sp["helminthKillEnergyOrbChance"] if item.is_helminth else sp["killEnergyOrbChance"])
                if self._rng(127) < p_hp2:
                    self._pickup_health_orb(50.0, t)
                if self._rng(131) < p_en2:
                    self._pickup_energy_orb(25.0, t)

        # 6. Squad / Focus / Arcane Universal Fallout kill orb drops
        extra_e_orb_p = min(1.0, self.squad_kill_energy_orb_chance + self.focus_kill_energy_orb_chance)
        if extra_e_orb_p > 0.0 and self._rng(139) < extra_e_orb_p:
            self._pickup_energy_orb(25.0, t)
        if self.squad_kill_health_orb_chance > 0.0 and self._rng(149) < self.squad_kill_health_orb_chance:
            self._pickup_health_orb(50.0, t)
        if self.universal_fallout_cfg and radiation_stacks > 0:
            uf_p = min(1.0, float(self.universal_fallout_cfg["chancePerRadStack"]) * min(10, int(radiation_stacks)))
            if uf_p > 0.0 and self._rng(151) < uf_p:
                self._pickup_health_orb(100.0, t)
                self._pickup_energy_orb(25.0, t)

        # Immediately check if newly picked-up orbs end an energy vacuum period!
        self._try_start_next_cast(t)

    def summary_payload(self, total_seconds: float | None = None) -> dict[str, Any]:
        end_t = float(self.t if total_seconds is None else max(self.t, float(total_seconds)))
        if end_t > self.t + EPS:
            self.advance(end_t)
        denom = max(EPS, end_t)
        raw_firing_duty = max(0.0, min(1.0, 1.0 - self.weapon_cast_pause_seconds / denom)) if end_t > EPS else 1.0
        firing_duty = round(raw_firing_duty * self.focus_firing_duty_multiplier, 6)

        abilities_report: list[dict[str, Any]] = []
        uptime_sum = 0.0
        for item in self.items:
            up_ratio = min(1.0, item.active_seconds / denom) if end_t > EPS else (1.0 if item.active else 0.0)
            vac_sec = max(0.0, end_t - item.active_seconds) if end_t > EPS else 0.0
            str_ratio = item.snap_strength / max(0.01, item.nominal_slot_strength)
            eff_cost = self.effective_activation_cost(item, end_t)
            cast_sec = (
                item.base_cast_time / self.current_casting_speed_multiplier(end_t)
                if item.base_cast_time > 0.0
                else 0.0
            )
            dur_mult = 1.0 if item.fixed_duration else max(0.05, self.uncond_duration + self.molt_efficiency_bonus)
            uptime_sum += up_ratio
            abilities_report.append({
                "id": item.primary_id,
                "memberIds": list(item.member_ids),
                "slot": (item.slot_index + 1) if item.slot_index is not None else None,
                "nameZh": item.name_zh,
                "nameEn": item.name_en,
                "casts": item.casts,
                "activationCost": round(eff_cost, 2),
                "drainPerSec": round(self.effective_drain_per_sec(item, end_t), 3),
                "castTimeSec": round(cast_sec, 3),
                "durationSec": round(item.base_duration * dur_mult, 2) if item.base_duration is not None else None,
                "uptimeRatio": round(up_ratio, 6),
                "vacuumSeconds": round(vac_sec, 3),
                "snapshottedStrength": round(item.snap_strength, 4),
                "effectiveMultiplierRatio": round(up_ratio * str_ratio, 6),
                "unaffordable": item.unaffordable,
            })

        mean_uptime = (uptime_sum / len(abilities_report)) if abilities_report else 1.0
        total_vacuum = max((r["vacuumSeconds"] for r in abilities_report), default=0.0)
        return {
            "enabled": self.enabled,
            "windowSeconds": round(end_t, 3),
            "spawnEnergy": round(self.spawn_energy, 2),
            "finalEnergy": round(self.energy, 2),
            "maxEnergy": round(self.max_energy, 2),
            "totalEnergySpent": round(self.total_energy_spent, 2),
            "totalEnergyGained": round(self.total_energy_gained, 2),
            "equilibriumEnergyFromHealth": round(self.equilibrium_energy_from_health, 2),
            "equilibriumHealthFromEnergy": round(self.equilibrium_health_from_energy, 2),
            "totalCasts": self.total_casts,
            "freeCastsUsed": self.free_casts_used,
            "innerMightProcs": self.inner_might_procs,
            "arbucepEmpowered": self.arbucep_empowered,
            "steadfastProcs": self.steadfast_procs,
            "energizeProcs": self.energize_procs,
            "energyOrbsPicked": self.energy_orbs_picked,
            "healthOrbsPicked": self.health_orbs_picked,
            "blessingBonusHealth": round(self.blessing_stacks * float((self.blessing_cfg or {}).get("hpPerOrb") or 0.0), 1),
            "healthConversionArmor": round(self.health_conversion_stacks * self.health_conversion_armor, 1),
            "moltAugmentedStacks": self.molt_augmented_stacks,
            "weaponCastPauseSeconds": round(self.weapon_cast_pause_seconds, 3),
            "firingDutyCycle": round(firing_duty, 6),
            "meanUptimeRatio": round(mean_uptime, 6),
            "maxVacuumSeconds": round(total_vacuum, 3),
            "channelStarvedCount": self.channel_starved_count,
            "castOrder": [it.primary_id for it in self.items],
            "castOrderSlots": [(it.slot_index + 1) for it in self.items if it.slot_index is not None],
            "excludedIds": sorted(self.excluded_ids),
            "abilities": abilities_report,
        }


def simulate_1d_ability_rotation(
    *,
    warframe_result: Mapping[str, Any],
    uncond_warframe_result: Mapping[str, Any] | None = None,
    active_ability_ids: Sequence[str] = (),
    companion_eval: Mapping[str, Any] | None = None,
    rotation_config: Mapping[str, Any] | None = None,
    window_seconds: float = 30.0,
    kills_per_second: float = 0.5,
    incoming_health_dps: float = 0.0,
    shield_uptime: float = 1.0,
    eximus: bool = False,
    headshot_chance: float = 0.0,
    is_melee: bool = False,
    seed: int = 1,
) -> dict[str, Any]:
    """Run deterministic 1D rotation over window_seconds with discrete kill & orb events."""
    win = max(1.0, float(window_seconds or 30.0))
    sim = WarframeRotationSimulator(
        warframe_result,
        uncond_warframe_result=uncond_warframe_result,
        active_ability_ids=active_ability_ids,
        companion_eval=companion_eval,
        rotation_config=rotation_config,
        seed=seed,
    )
    if shield_uptime <= 0.05:
        sim.shield = 0.0

    kps = max(0.0, float(kills_per_second))
    kill_interval = (1.0 / kps) if kps > 1e-6 else math.inf
    next_kill = kill_interval
    next_dmg_tick = 1.0 if incoming_health_dps > 0.0 else math.inf

    while sim.t < win - EPS:
        nxt = min(win, next_kill, next_dmg_tick, sim.next_event_time(sim.t))
        if nxt <= sim.t + 1e-7:
            nxt = min(win, sim.t + 0.05)
        sim.advance(nxt)
        if sim.t >= next_dmg_tick - EPS and sim.t < win + EPS:
            # Slightly drain health so Health Orbs & Rage / Equilibrium interact realistically under incoming fire
            dmg = incoming_health_dps * 1.0
            sim.health = max(1.0, sim.health - dmg)
            sim.on_health_damage_taken(dmg, sim.t)
            next_dmg_tick += 1.0
        while sim.t >= next_kill - EPS and next_kill <= win + EPS:
            is_hs = headshot_chance > 0.0 and sim._rng(137) < headshot_chance
            sim.on_enemy_kill(
                next_kill,
                is_eximus=eximus,
                headshot=is_hs,
                is_melee=is_melee,
            )
            next_kill += kill_interval

    report = sim.summary_payload(win)
    multipliers: dict[str, float] = {aid: 1.0 for aid in sim.always_on_ids}
    for eid in sim.excluded_ids:
        multipliers[str(eid)] = 0.0
    for row in report["abilities"]:
        mult = float(row["effectiveMultiplierRatio"])
        for mid in row["memberIds"]:
            multipliers[str(mid)] = mult
    report["abilityMultipliers"] = multipliers
    return report
