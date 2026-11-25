"""3D Arena Defense Map Nuke Director (`hybrid_nuke` & `ability_only`).

Executes client-verified Warframe multi-step nuke & state-driven combos in 3D space:
- Enforces Arbitration Drone immunity (`actor.drone` and `target.protected` are immune to Warframe abilities).
- Respects cover/LoS per ability (`radial_ignore_cover` vs `radial_los` / static cover checks).
- Consumes energy and locks weapon firing during cast animations via `WarframeRotationSimulator`
  (including Zenurik `Inner Might` 60s free casts and `Brightbonnet + Arbucep` channel-bypassing pulses).
- Mirage `2 Explosive Legerdemain` (`HarlequinObjectChange.lua`):
  - Requires enemy kills first to drop eligible Health/Energy Orbs & non-heavy Ammo boxes
    (excluding Heavy Ammo & Universal Orbs per `_pickupExplosionPickupType`).
  - Event-driven `2 Sleight of Hand` conversion (`40m * Range` ignore LoS) into proximity gems with
    built-in `60.0s` fixed lifetime (`Function #63` `LOADK 60`), recast timer refresh, cross-wave
    persistence, and `15.0m` fixed-radius detonation checking static cover LoS (`checkForCover=true,
    staticCoverOnly=true`) with `100%` forced elemental procs.
- State/event-driven loops (no naive timer recasting) for Gyre `3+4` kill-extension + `Cathode Current`,
  Saryn `1+4` spore infection/spread/decay + 4x Miasma, Volt `4` Tesla cross-arcs (`0` lone-target damage
  for 4.5s so gun cleans stragglers), Mirage `3+4` per-hit Prism ramp, Gara `4->1` dynamic ring expansion +
  `2 Splinter Storm` accumulation, Khora `4+1` cross-wave Strangledome + `Accumulating Whipclaw`,
  Equinox `4` cross-wave Maim pool + exact `1 - d/R` falloff, Dante `3x2->4` Tragedy condense,
  Sevagoth `2->1` True HP chain, Gauss `Thermal Sunder`, Ember `4` per-target energy cap + Fire Rings,
  Nezha `4` Impale->Slam condense, Frost `4` pre-hit armor strip + death shatter, Mag `4`, and Nokko `2+4`
  bouncing Sporespring.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from .arena_combat import EPS
from .arena_scene import distance


def _add_y(p: tuple[float, float, float], dy: float) -> tuple[float, float, float]:
    return (p[0], p[1] + dy, p[2])


def _det_rand(seed: int, a: int, b: int = 0) -> float:
    x = (int(seed) ^ ((int(a) + 1) * 0x9E3779B1) ^ ((int(b) + 1) * 0x85EBCA6B)) & 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    return ((x ^ (x >> 16)) & 0xFFFFFFFF) / 4294967296.0


class ArenaNukeDirector:
    """Spatial Warframe ability nuke state machine for 3D Arena."""

    MAX_RECORDED_PULSES = 600
    LEGERDEMAIN_GEM_LIFETIME = 60.0
    LEGERDEMAIN_BLAST_RADIUS = 15.0
    LEGERDEMAIN_TRIGGER_RADIUS = 3.20
    PRESENT_JEWEL_LIFETIME = 20.0
    PRESENT_WEAK_MULTIPLIER = 0.50
    PRESENT_CLONE_OFFSET_M = 6.0

    def __init__(
        self,
        warframe_context: Mapping[str, Any],
        wf_state: Any,
        scenario: Mapping[str, Any],
        seed: int,
    ):
        self.raw = warframe_context
        self.wf_state = wf_state
        self.scenario = scenario
        self.seed = int(seed)
        self.combat_style = str(scenario.get("combatStyle") or "weapon_only")

        nuke = warframe_context.get("nukePreview") if isinstance(warframe_context.get("nukePreview"), Mapping) else {}
        self.nuke = dict(nuke)
        self.setup_id = str(nuke.get("setupId") or "generic_radial")
        self.title_zh = str(nuke.get("titleZh") or wf_state.name_zh)
        self.primary_radius = max(4.0, float(nuke.get("primaryRadiusM") or 18.0))
        self.ignores_los = bool(nuke.get("ignoresLoS", True))
        self.combo_sec = max(0.35, float(nuke.get("comboTimingSec") or 1.2))
        self.combo_energy = max(0.0, float(nuke.get("comboEnergyCost") or 50.0))
        self.armor_strip = max(0.0, min(1.0, float(nuke.get("effectiveArmorStrip") or 0.0)))
        self.direct_per_combo = max(0.0, float(nuke.get("directDamagePerCombo") or 1500.0))
        self.dot_per_combo = max(0.0, float(nuke.get("dotDamagePerCombo") or 0.0))
        self.true_hp_pct = max(0.0, float(nuke.get("trueHpPercentPerCombo") or 0.0))

        panel = warframe_context.get("finalPanel") or (warframe_context.get("weaponBridge") or {}).get("panel") or {}
        self.strength = max(0.1, float(panel.get("abilityStrength") or panel.get("strength") or 1.0))
        self.duration = max(0.1, float(panel.get("abilityDuration") or panel.get("duration") or 1.0))
        self.efficiency = min(1.75, float(panel.get("abilityEfficiency") or panel.get("efficiency") or 1.0))
        self.range_mult = max(0.34, float(panel.get("abilityRange") or panel.get("range") or 1.0))

        wb = warframe_context.get("weaponBridge") or {}
        econ = wb.get("energyEconomy") or {}
        cs_bonus = float(econ.get("castingSpeedBonus") or panel.get("castingSpeed") or 0.0)
        self.cast_speed_mult = max(0.25, float(econ.get("castingSpeedMultiplier") or (1.0 + cs_bonus)))

        sq = nuke.get("squadBuffs") if isinstance(nuke.get("squadBuffs"), Mapping) else (wb.get("squadBuffSummary") or {})
        self.roar_bonus = max(0.0, float(sq.get("roarBonus") or 0.0))
        self.vuln_mult = max(1.0, float(sq.get("abilityVulnerabilityMultiplier") or 1.0))
        self.status_dmg_vuln = max(0.0, float(sq.get("abilityStatusDamageVulnerability") or 0.0))

        # Remove squad buffs already baked into preview numbers when re-applying via apply_ability_hit
        baked_div = max(1e-6, (1.0 + self.roar_bonus) * self.vuln_mult)
        self.unbuffed_direct = self.direct_per_combo / baked_div

        # Ability range lookup by slot (1..4)
        self.slot_radii: dict[int, float] = {}
        for row in warframe_context.get("abilityRanges") or ():
            if isinstance(row, Mapping) and row.get("slot") and row.get("moddedRadiusM"):
                self.slot_radii[int(row["slot"])] = float(row["moddedRadiusM"])

        slot_abs = econ.get("slotAbilities") or ()
        has_eclipse = any(
            isinstance(sa, Mapping) and "eclipse" in str(sa.get("id") or sa.get("nameEn") or "").casefold()
            for sa in slot_abs
        )
        self.has_splinter_storm = any(
            isinstance(sa, Mapping) and "splinter" in str(sa.get("id") or sa.get("nameEn") or "").casefold()
            for sa in slot_abs
        )
        ab_scalars = warframe_context.get("abilityScalars") or ()
        self.has_hall_of_mirrors_slot = any(
            isinstance(ab, Mapping) and "illusionability" in str(ab.get("path") or ab.get("id") or "").casefold()
            for ab in ab_scalars
        ) or any(
            isinstance(sa, Mapping) and ("illusion" in str(sa.get("id") or sa.get("abilityPath") or "").casefold() or "mirror" in str(sa.get("nameEn") or "").casefold())
            for sa in slot_abs
        )
        self.has_legerdemain_augment = bool(nuke.get("hasLegerdemainAugment", False))
        self.radius_summary_zh = str(nuke.get("radiusSummaryZh") or "")

        # Live combo state machine variables
        self.next_action_at = 0.20
        self._last_t = 0.0
        self._last_player_pos: tuple[float, float, float] | None = None
        self.phase = 0
        self.casts_executed = 0
        self.energy_spent = 0.0
        self.inner_might_saves = 0
        self.starved_waits = 0
        self.pulses: list[list[float]] = []
        self.pending_kill_reactions: list[tuple[str, tuple[float, float, float], float]] = []

        # 1. Mirage Sleight of Hand (`1+2` Primary + 4 Hall of Mirrors Mini-Jewels + `Explosive Legerdemain` 60s Gems)
        self.hom_until = -math.inf
        self.present_jewels: list[dict[str, Any]] = []
        self.next_jewel_check = math.inf
        self.main_jewels_conjured = 0
        self.clone_mini_jewels_conjured = 0
        self.jewels_detonated = 0
        self.ground_pickups: list[dict[str, Any]] = []
        self.legerdemain_gems: list[dict[str, Any]] = []
        self.next_gem_check = math.inf
        self.last_legerdemain_cast_t = -math.inf
        self.pickups_dropped = 0
        self.gems_converted = 0
        self.gems_refreshed = 0
        self.gems_detonated = 0

        # 2. Mirage Prism (`HarlequinPrism`)
        self.prism_until = -math.inf
        self.prism_next_tick = math.inf
        self.prism_last_drain_t = 0.0
        self.prism_hits = 0
        self.prism_ramp_rate = 0.50 if has_eclipse else 0.25

        # 3. Equinox Day Maim
        self.maim_active = False
        self.maim_pool = 0.0
        self.maim_last_drain_t = 0.0
        self.maim_bled_ids: set[int] = set()

        # 4. Mesa Peacemaker
        self.mesa_active = False
        self.mesa_shots_fired = 0
        self.mesa_last_drain_t = 0.0

        # 5. Gara Mass Vitrify + Shattered Lash + Splinter Storm
        self.vitrified_ids: set[int] = set()
        self.splinter_storm_dps = 0.0
        self.splinter_until = -math.inf
        self.splinter_next_tick = math.inf

        # 6. Khora Strangledome + Accumulating Whipclaw
        self.dome_until = -math.inf
        self.dome_pos: tuple[float, float, float] | None = None
        self.accum_whip_stacks = 0
        self.accum_whip_until = -math.inf
        self.has_accum_whip = bool(nuke.get("hasAccumulatingWhipclaw")) or "积聚长鞭" in self.title_zh

        # 7. Gyre Cathode Grace + Rotorswell + Cathode Current
        self.grace_until = -math.inf
        self.grace_last_regen_t = 0.0
        self.rotorswell_until = -math.inf
        self.rotorswell_next_arc = math.inf
        self.cathode_cd_until = -math.inf
        self.gyre_kill_extensions = 0

        # 8. Saryn Spores + Miasma
        self.spored_ids: set[int] = set()
        self.miasma_until = -math.inf
        self.spores_damage = 100.0 * self.strength
        self.spores_next_tick = 1.0 if self.setup_id == "saryn_spores_miasma" else math.inf

        # 9. Volt Discharge Tesla coils
        self.stunned_until: dict[int, tuple[float, float]] = {}
        self.volt_next_tick = math.inf

        # 10. Ember Inferno Fire Rings
        self.fire_ring_until: dict[int, float] = {}
        self.ember_next_tick = math.inf

        # 11. Nezha Divine Retribution
        self.speared_ids: set[int] = set()

        # 12. Frost Avalanche freeze shatter
        self.frozen_by_avalanche: set[int] = set()

        # 13. Nokko Brightbonnet + Sporespring bounces
        self.brightbonnet_until = -math.inf
        self.sporespring_bounces_left = 0
        self.sporespring_pos: tuple[float, float, float] | None = None
        self.sporespring_next_bounce = math.inf

    def next_event_time(self) -> float:
        cand = [self.next_action_at]
        if self.pending_kill_reactions:
            cand.append(self._last_t + 0.02)
        for timer in (
            self.next_gem_check,
            self.next_jewel_check,
            self.prism_next_tick,
            self.rotorswell_next_arc,
            self.spores_next_tick,
            self.volt_next_tick,
            self.splinter_next_tick,
            self.ember_next_tick,
            self.sporespring_next_bounce,
        ):
            if timer < math.inf:
                cand.append(timer)
        return min(cand)

    def _eff_cost(self, base_cost: float) -> float:
        return max(0.25 * base_cost, base_cost * (2.0 - self.efficiency))

    def _chan_drain_per_sec(self, base_drain: float) -> float:
        factor = max(0.25, (2.0 - self.efficiency) / max(0.10, self.duration))
        return base_drain * factor

    def _try_spend_cast(self, t: float, base_cost: float, cast_sec: float, *, speed_cap: float | None = None) -> bool:
        """Consume energy (or Zenurik Inner Might free cast) and lock weapon during cast."""
        cost = self._eff_cost(base_cost)
        rot = self.wf_state.rotation if self.wf_state is not None else None
        cs = min(self.cast_speed_mult, speed_cap) if speed_cap is not None else self.cast_speed_mult
        dur = max(0.15, cast_sec / max(0.25, cs))

        if rot is not None:
            self.wf_state.advance(t)
            if rot.inner_might_ready and cost > 0.0:
                rot.inner_might_ready = False
                rot.inner_might_next_at = t + rot.inner_might_cooldown
                rot.inner_might_procs += 1
                rot.free_casts_used += 1
                self.inner_might_saves += 1
                actual_cost = 0.0
            elif rot.energy + EPS < cost:
                self.starved_waits += 1
                return False
            else:
                rot._spend_energy(cost, t)
                actual_cost = cost
            rot.cast_until = max(rot.cast_until, t + dur)
            rot.weapon_locked_until = max(rot.weapon_locked_until, t + dur)
            rot.total_casts += 1
            self.wf_state.energy = rot.energy
        else:
            if self.wf_state.energy + EPS < cost:
                self.starved_waits += 1
                return False
            self.wf_state.energy = max(0.0, self.wf_state.energy - cost)
            actual_cost = cost

        self.casts_executed += 1
        self.energy_spent += actual_cost
        return True

    def _drain_channel(self, t: float, last_t: float, base_drain_per_sec: float) -> tuple[bool, float]:
        dt = max(0.0, t - last_t)
        if dt <= EPS:
            return True, t
        need = self._chan_drain_per_sec(base_drain_per_sec) * dt
        rot = self.wf_state.rotation if self.wf_state is not None else None
        if rot is not None:
            self.wf_state.advance(t)
            if rot.energy + EPS < need:
                rot.external_channel_active = False
                return False, t
            rot._spend_energy(need, t)
            rot.external_channel_active = True
            self.wf_state.energy = rot.energy
        else:
            if self.wf_state.energy + EPS < need:
                return False, t
            self.wf_state.energy = max(0.0, self.wf_state.energy - need)
        self.energy_spent += need
        return True, t

    def _notify_electric_ability_hit(self, t: float) -> None:
        rot = self.wf_state.rotation if self.wf_state is not None else None
        if rot is not None and getattr(rot, "archon_stretch_regen", 0.0) > 0.0:
            rot.archon_stretch_until = max(rot.archon_stretch_until, t + 5.0)

    def _eligible_targets(
        self,
        world: Any,
        origin: tuple[float, float, float],
        radius: float,
        *,
        require_los: bool,
        eye_offset: float = 1.35,
    ) -> list[Any]:
        eye = _add_y(origin, eye_offset)
        out = []
        for actor in list(world.live):
            if actor.dead or actor.drone:
                continue
            v = world.combat.targets.get(actor.id)
            if v is None or not v.alive or v.protected:
                continue
            d = distance(origin, actor.pos)
            if d > radius:
                continue
            if require_los and not world.scene.visible(eye, _add_y(actor.pos, 0.85)):
                continue
            out.append(actor)
        return out

    def _record_pulse(
        self,
        t: float,
        pos: tuple[float, float, float],
        slot: int,
        radius_m: float,
        dur_sec: float,
        hits: int,
    ) -> None:
        if len(self.pulses) >= self.MAX_RECORDED_PULSES:
            return
        self.pulses.append([
            round(float(t), 3),
            round(float(pos[0]), 2),
            round(float(pos[1]), 2),
            round(float(pos[2]), 2),
            int(slot),
            round(float(radius_m), 2),
            round(float(dur_sec), 2),
            int(hits),
        ])

    def _spawn_pickup(self, base_pos: tuple[float, float, float], dtype: str, t: float, idx: int) -> None:
        if len(self.ground_pickups) >= 96:
            self.ground_pickups.pop(0)
        ang = _det_rand(self.seed, int(t * 1000) + idx, 91 + idx) * (2.0 * math.pi)
        rad = 0.25 + 0.45 * _det_rand(self.seed, int(t * 1000) + idx, 131 + idx)
        pos = (
            base_pos[0] + math.cos(ang) * rad,
            base_pos[1],
            base_pos[2] + math.sin(ang) * rad,
        )
        self.ground_pickups.append({"pos": pos, "dtype": dtype, "spawned_at": t})
        self.pickups_dropped += 1

    def on_enemy_killed(self, actor: Any, victim: Any, t: float) -> None:
        """Handle kill-driven nuke mechanics (Legerdemain drops, Maim pool, Gyre extension, Saryn spread, Frost shatter)."""
        if actor.drone or self.wf_state is None:
            return
        self._last_t = max(self._last_t, t)
        sid = self.setup_id

        # 1. Mirage Explosive Legerdemain: spawn eligible orbs & non-heavy ammo boxes on death ONLY when augment is equipped!
        if sid == "mirage_legerdemain":
            if not self.has_legerdemain_augment:
                return
            tape = actor.tape or {}
            is_eximus = bool(tape.get("eximus"))
            energy_fullish = self.wf_state.energy >= max(25.0, self.wf_state.max_energy - 25.0)
            hp_fullish = self.wf_state.health >= max(10.0, self.wf_state.max_health - 5.0)
            if is_eximus:
                # Eximus guarantees 2 Health Orbs + 1 Energy Orb + 1 non-heavy Primary/Secondary Ammo box
                # (Heavy ammo & Universal orbs excluded per HarlequinObjectChangeHelper._pickupExplosionPickupType)
                self._spawn_pickup(actor.pos, "DT_FREEZE", t, actor.id * 4 + 1)
                self._spawn_pickup(actor.pos, "DT_FIRE", t, actor.id * 4 + 2)
                if hp_fullish:
                    self._spawn_pickup(actor.pos, "DT_FIRE", t, actor.id * 4 + 3)
                if energy_fullish:
                    self._spawn_pickup(actor.pos, "DT_ELECTRICITY", t, actor.id * 4 + 4)
            else:
                # Non-heavy Primary/Secondary Ammo box (~32% combined rifle/pistol/shotgun/sniper drop rate)
                if _det_rand(self.seed, actor.id, 11) < 0.32:
                    self._spawn_pickup(actor.pos, "DT_FREEZE", t, actor.id * 4 + 1)
                # Energy Orb stays on ground when pool is topped off or excess drops
                rot = self.wf_state.rotation
                bonus_e = float(getattr(rot, "bonus_energy_orb_chance", 0.0)) if rot is not None else 0.0
                if _det_rand(self.seed, actor.id, 12) < (0.10 + bonus_e) and (
                    energy_fullish or _det_rand(self.seed, actor.id, 15) < 0.50
                ):
                    self._spawn_pickup(actor.pos, "DT_ELECTRICITY", t, actor.id * 4 + 2)
                # Health Orb stays on ground when HP is full
                bonus_h = float(getattr(rot, "bonus_health_orb_chance", 0.0)) if rot is not None else 0.0
                if _det_rand(self.seed, actor.id, 13) < (0.05 + bonus_h) and hp_fullish:
                    self._spawn_pickup(actor.pos, "DT_FIRE", t, actor.id * 4 + 3)
            return

        # 2. Equinox Day Maim: accumulate 75% of (MaxShield + MaxHealth) within Maim aura
        if sid == "equinox_day_maim" and self.maim_active:
            ppos = self._last_player_pos
            if ppos is None or distance(ppos, actor.pos) <= self.primary_radius + 1.0:
                max_sh = float(victim.full[1]) if len(victim.full) > 1 else 0.0
                max_hp = float(victim.full[2]) if len(victim.full) > 2 else 0.0
                self.maim_pool += 0.75 * (max_sh + max_hp)
            return

        # 3. Gyre Cathode Grace + Rotorswell: extend durations on kill without recasting + queue Cathode Current arc!
        if sid == "gyre_rotorswell":
            rot = self.wf_state.rotation
            rot_grace = next(
                (it for it in (getattr(rot, "items", None) or ()) if "cathode" in str(getattr(it, "primary_id", "")).casefold()),
                None,
            )
            if rot_grace is not None and rot_grace.active_until > t + EPS:
                self.grace_until = max(self.grace_until, rot_grace.active_until)
            extended = False
            if t < self.grace_until - EPS:
                self.grace_until = min(t + 60.0, self.grace_until + 3.0 * self.duration)
                if rot_grace is not None:
                    rot_grace.active_until = self.grace_until
                extended = True
            if t < self.rotorswell_until - EPS:
                self.rotorswell_until = min(t + 40.0, self.rotorswell_until + 2.0 * self.duration)
                extended = True
                if t >= self.cathode_cd_until - EPS:
                    self.cathode_cd_until = t + 0.35
                    self.pending_kill_reactions.append(("cathode_current", tuple(actor.pos), t))
            if extended:
                self.gyre_kill_extensions += 1
            return

        # 4. Saryn Spores: spread 16m * Range (ignoring LoS) when an infected enemy dies!
        if sid == "saryn_spores_miasma":
            if actor.id in self.spored_ids:
                self.spored_ids.discard(actor.id)
                death_src = str((actor.tape or {}).get("deathSource") or "")
                # Non-Spores kills (weapon, Miasma) or any kill while Miasma sickened spreads Spores!
                if t < self.miasma_until + EPS or death_src != "ability-direct-spores":
                    self.pending_kill_reactions.append(("spore_spread", tuple(actor.pos), t))
            return

        # 5. Frost Avalanche: frozen enemy death shatters in 4.5m * Range
        if sid == "frost_avalanche" and actor.id in self.frozen_by_avalanche:
            self.frozen_by_avalanche.discard(actor.id)
            self.pending_kill_reactions.append(("frost_shatter", tuple(actor.pos), t))

    def flush_kill_reactions(self, world: Any, t: float) -> None:
        if not self.pending_kill_reactions:
            return
        queued = list(self.pending_kill_reactions)
        self.pending_kill_reactions.clear()
        for kind, pos, when in queued:
            now_t = max(t, when)
            if kind == "cathode_current":
                rad = max(6.0, 10.0 * self.range_mult)
                neighbors = self._eligible_targets(world, pos, rad, require_los=True, eye_offset=0.85)
                if neighbors:
                    arc_dmg = 1500.0 * self.strength * (1.0 + 0.50 * self.strength)
                    for nb in neighbors[:6]:
                        world.combat.apply_ability_hit(
                            nb.id,
                            {"DT_ELECTRICITY": arc_dmg},
                            now_t,
                            forced_procs={"DT_ELECTRICITY": 1.0},
                            roar_bonus=self.roar_bonus,
                            vuln_mult=self.vuln_mult,
                            status_dmg_vuln=self.status_dmg_vuln,
                        )
                    self._notify_electric_ability_hit(now_t)
                    self._record_pulse(now_t, pos, 3, rad, 0.35, min(6, len(neighbors)))
            elif kind == "spore_spread":
                spread_rad = max(6.0, 16.0 * self.range_mult)
                for nb in self._eligible_targets(world, pos, spread_rad, require_los=False):
                    self.spored_ids.add(nb.id)
            elif kind == "frost_shatter":
                shatter_rad = max(3.0, 4.5 * self.range_mult)
                neighbors = self._eligible_targets(world, pos, shatter_rad, require_los=True, eye_offset=0.85)
                for nb in neighbors:
                    world.combat.apply_ability_hit(
                        nb.id,
                        {"DT_FREEZE": 400.0 * self.strength},
                        now_t,
                        forced_procs={"DT_FREEZE": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                    )

    def step_intermission(self, world: Any, t: float) -> None:
        """Maintain cross-wave persistent objects (Mirage 60s gems, Mesa channel pause) between waves."""
        if self.wf_state is None or self.wf_state.terminated:
            return
        self._last_t = t
        ppos = tuple(world.player.pos)
        self._last_player_pos = ppos

        # Pause Mesa's high-drain Peacemaker during empty wave intermissions
        if self.mesa_active:
            self.mesa_active = False
            if self.wf_state.rotation is not None:
                self.wf_state.rotation.external_channel_active = False

        if self.setup_id == "mirage_legerdemain":
            self._step_present_jewels(world, t)
            if self.has_legerdemain_augment:
                self._step_legerdemain_gems(world, t)
                if t >= self.next_action_at - EPS:
                    conv_rad = 40.0 * self.range_mult
                    eligible = [p for p in self.ground_pickups if distance(ppos, p["pos"]) <= conv_rad]
                    gems_near = [g for g in self.legerdemain_gems if distance(ppos, g["pos"]) <= conv_rad]
                    needs_refresh = bool(gems_near) and min(g["expires_at"] - t for g in gems_near) <= 8.0
                    if eligible or needs_refresh:
                        self._cast_sleight_of_hand(world, ppos, t, conv_rad, eligible, gems_near)
                    else:
                        self.next_action_at = t + 0.50
            else:
                self.next_action_at = max(self.next_action_at, t + 0.50)

    def step(self, world: Any, t: float) -> None:
        if self.wf_state is None or self.wf_state.terminated:
            return
        self._last_t = t
        ppos = tuple(world.player.pos)
        self._last_player_pos = ppos

        self.flush_kill_reactions(world, t)
        self._step_autonomous_auras(world, ppos, t)

        if t < self.next_action_at - EPS:
            return
        if not world.live:
            if self.setup_id == "mirage_legerdemain":
                self.step_intermission(world, t)
            else:
                self.next_action_at = t + 0.25
            return

        sid = self.setup_id
        if sid == "mirage_legerdemain":
            self._step_mirage_legerdemain(world, ppos, t)
        elif sid == "mirage_prism":
            self._step_mirage_prism(world, ppos, t)
        elif sid == "equinox_day_maim":
            self._step_equinox_maim(world, ppos, t)
        elif sid == "mesa_peacemaker":
            self._step_mesa_peacemaker(world, ppos, t)
        elif sid == "gara_shatter_storm":
            self._step_gara_combo(world, ppos, t)
        elif sid == "dante_tragedy":
            self._step_dante_tragedy(world, ppos, t)
        elif sid == "khora_whipclaw":
            self._step_khora_whipclaw(world, ppos, t)
        elif sid == "sevagoth_sow_reap":
            self._step_sevagoth_combo(world, ppos, t)
        elif sid == "thermal_sunder_nuke":
            self._step_thermal_sunder(world, ppos, t)
        elif sid == "gyre_rotorswell":
            self._step_gyre_rotorswell(world, ppos, t)
        elif sid == "saryn_spores_miasma":
            self._step_saryn_combo(world, ppos, t)
        elif sid == "volt_discharge":
            self._step_volt_discharge(world, ppos, t)
        elif sid == "ember_inferno":
            self._step_ember_inferno(world, ppos, t)
        elif sid == "nezha_divine_retribution":
            self._step_nezha_retribution(world, ppos, t)
        elif sid == "nokko_sporespring":
            self._step_nokko_sporespring(world, ppos, t)
        else:
            self._step_radial_nuke(world, ppos, t)

    def _step_legerdemain_gems(self, world: Any, t: float) -> None:
        if self.ground_pickups:
            self.ground_pickups = [p for p in self.ground_pickups if t - p["spawned_at"] <= 120.0]
        if not self.legerdemain_gems:
            self.next_gem_check = math.inf
            return
        if t < self.next_gem_check - EPS:
            return

        remaining_gems: list[dict[str, Any]] = []
        for gem in self.legerdemain_gems:
            gpos = gem["pos"]
            gem_eye = _add_y(gpos, 0.45)
            expired = t >= gem["expires_at"] - EPS
            tripped = expired
            if not tripped and world.live:
                for actor in world.live:
                    if actor.dead or actor.drone:
                        continue
                    v = world.combat.targets.get(actor.id)
                    if v is None or not v.alive or v.protected:
                        continue
                    if distance(gpos, actor.pos) <= self.LEGERDEMAIN_TRIGGER_RADIUS and world.scene.visible(
                        gem_eye, _add_y(actor.pos, 0.85)
                    ):
                        tripped = True
                        break
            if not tripped:
                remaining_gems.append(gem)
                continue

            # Detonate gem: 15.0m fixed radius, static cover LoS (`checkForCover=true, staticCoverOnly=true`),
            # linear falloff `1 - d/15`, `1000 * Strength` base damage, 100% forced status proc!
            hits = 0
            dtype = gem["dtype"]
            for actor in list(world.live):
                if actor.dead or actor.drone:
                    continue
                v = world.combat.targets.get(actor.id)
                if v is None or not v.alive or v.protected:
                    continue
                d = distance(gpos, actor.pos)
                if d > self.LEGERDEMAIN_BLAST_RADIUS:
                    continue
                if not world.scene.visible(gem_eye, _add_y(actor.pos, 0.85)):
                    continue
                falloff = max(0.05, 1.0 - d / self.LEGERDEMAIN_BLAST_RADIUS)
                dmg = 1000.0 * self.strength * falloff
                world.combat.apply_ability_hit(
                    actor.id,
                    {dtype: dmg},
                    t,
                    forced_procs={dtype: 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )
                hits += 1
            if dtype == "DT_ELECTRICITY" and hits > 0:
                self._notify_electric_ability_hit(t)
            if hits > 0 or not expired:
                self._record_pulse(t, gpos, 2, self.LEGERDEMAIN_BLAST_RADIUS, 0.55, hits)
            self.gems_detonated += 1

        self.legerdemain_gems = remaining_gems
        self.next_gem_check = (t + 0.15) if self.legerdemain_gems else math.inf

    def _is_hall_of_mirrors_active(self, t: float) -> bool:
        if not self.has_hall_of_mirrors_slot:
            return False
        rot = self.wf_state.rotation if self.wf_state is not None else None
        if rot is not None:
            rot_hom = next(
                (
                    it
                    for it in (getattr(rot, "items", None) or ())
                    if "illusion" in str(getattr(it, "primary_id", "")).casefold()
                    or "mirror" in str(getattr(it, "name_en", "")).casefold()
                    or getattr(it, "slot_index", None) == 0
                ),
                None,
            )
            if rot_hom is not None and rot_hom.active_until > t + EPS:
                self.hom_until = max(self.hom_until, rot_hom.active_until)
                return True
        return t < self.hom_until - EPS

    def _step_present_jewels(self, world: Any, t: float) -> None:
        """Tick Mirage 2 Sleight of Hand Primary Jewel + 4 Hall of Mirrors Clone Mini-Jewels (packageWeakMultiplier=0.5)."""
        if not self.present_jewels:
            self.next_jewel_check = math.inf
            return
        if t < self.next_jewel_check - EPS:
            return

        remaining: list[dict[str, Any]] = []
        for jw in self.present_jewels:
            if t >= jw["expires_at"] - EPS:
                continue
            jpos = jw["pos"]
            jeye = _add_y(jpos, 0.45)
            charm_r = float(jw["charm_r"])
            blast_r = float(jw["blast_r"])
            dmg_base = float(jw["damage"])

            tripped = False
            if world.live:
                for actor in world.live:
                    if actor.dead or actor.drone:
                        continue
                    v = world.combat.targets.get(actor.id)
                    if v is None or not v.alive or v.protected:
                        continue
                    d = distance(jpos, actor.pos)
                    # Immediate touch at <=2.2m, or lured touch after >=0.45s inside charm radius with sightline
                    if d <= 2.20 and world.scene.visible(jeye, _add_y(actor.pos, 0.85)):
                        tripped = True
                        break
                    if (
                        t - jw["spawned_at"] >= 0.45
                        and d <= min(charm_r, 5.50 if not jw["weak"] else 3.80)
                        and world.scene.visible(jeye, _add_y(actor.pos, 0.85))
                    ):
                        tripped = True
                        break

            if not tripped:
                remaining.append(jw)
                continue

            hits = 0
            for actor in list(world.live):
                if actor.dead or actor.drone:
                    continue
                v = world.combat.targets.get(actor.id)
                if v is None or not v.alive or v.protected:
                    continue
                d = distance(jpos, actor.pos)
                if d > blast_r or not world.scene.visible(jeye, _add_y(actor.pos, 0.85)):
                    continue
                falloff = max(0.20, 1.0 - 0.50 * (d / max(1.0, blast_r)))
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_EXPLOSION": dmg_base * falloff},
                    t,
                    forced_procs={"DT_EXPLOSION": 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )
                hits += 1
            if hits > 0:
                self._record_pulse(t, jpos, 2, blast_r, 0.45, hits)
            self.jewels_detonated += 1

        self.present_jewels = remaining
        self.next_jewel_check = (t + 0.15) if self.present_jewels else math.inf

    def _conjure_present_jewels(self, world: Any, ppos: tuple[float, float, float], t: float) -> int:
        """Spawn 1 Primary Jewel + (if 1 Hall of Mirrors is active) 4 Clone Mini-Jewels at 6.0m with 50% effectiveness."""
        vis_targets = self._eligible_targets(world, ppos, 60.0, require_los=True)
        if vis_targets:
            vis_targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
            anchor = tuple(vis_targets[0].pos)
        else:
            all_t = self._eligible_targets(world, ppos, 60.0, require_los=False)
            if all_t:
                all_t.sort(key=lambda a: (distance(ppos, a.pos), a.id))
                anchor = tuple(all_t[0].pos)
            else:
                anchor = ppos

        # Recasting Sleight of Hand replaces previous un-detonated MiragePresentDeco jewels
        self.present_jewels = [
            {
                "pos": anchor,
                "weak": False,
                "damage": 200.0 * self.strength,
                "blast_r": 8.0 * self.range_mult,
                "charm_r": 12.0 * self.range_mult,
                "spawned_at": t,
                "expires_at": t + self.PRESENT_JEWEL_LIFETIME,
            }
        ]
        self.main_jewels_conjured += 1
        conjured = 1

        if self._is_hall_of_mirrors_active(t):
            wm = self.PRESENT_WEAK_MULTIPLIER
            base_ang = _det_rand(self.seed, int(t * 100) + self.casts_executed, 211) * (0.5 * math.pi)
            ray_start = _add_y(anchor, 0.50)
            for idx in range(4):
                ang = base_ang + idx * (0.5 * math.pi)
                dx, dz = math.cos(ang), math.sin(ang)
                hit = world.scene.raycast(ray_start, (dx, 0.0, dz), self.PRESENT_CLONE_OFFSET_M)
                dist_use = max(0.8, hit.distance - 0.35) if hit is not None else self.PRESENT_CLONE_OFFSET_M
                cpos = (anchor[0] + dx * dist_use, anchor[1], anchor[2] + dz * dist_use)
                self.present_jewels.append(
                    {
                        "pos": cpos,
                        "weak": True,
                        "damage": 200.0 * self.strength * wm,
                        "blast_r": 8.0 * self.range_mult * wm,
                        "charm_r": 12.0 * self.range_mult * wm,
                        "spawned_at": t,
                        "expires_at": t + self.PRESENT_JEWEL_LIFETIME,
                    }
                )
            self.clone_mini_jewels_conjured += 4
            conjured += 4

        self.next_jewel_check = min(self.next_jewel_check, t + 0.12)
        return conjured

    def _cast_sleight_of_hand(
        self,
        world: Any,
        ppos: tuple[float, float, float],
        t: float,
        conv_rad: float,
        eligible: list[dict[str, Any]],
        gems_near: list[dict[str, Any]],
    ) -> bool:
        if not self._try_spend_cast(t, 50.0, 0.80):
            self.next_action_at = t + 0.35
            return False

        conjured = self._conjure_present_jewels(world, ppos, t)

        if self.has_legerdemain_augment:
            exp = t + self.LEGERDEMAIN_GEM_LIFETIME
            # Recasting Sleight of Hand detaches & re-attaches HarlequinObjectChangeHelper, refreshing 60s lifetime!
            for g in gems_near:
                g["expires_at"] = exp
            self.gems_refreshed += len(gems_near)

            converted_ids = {id(p) for p in eligible}
            self.ground_pickups = [p for p in self.ground_pickups if id(p) not in converted_ids]
            for p in eligible:
                if len(self.legerdemain_gems) >= 96:
                    self.legerdemain_gems.pop(0)
                self.legerdemain_gems.append({"pos": p["pos"], "dtype": p["dtype"], "expires_at": exp})
            self.gems_converted += len(eligible)
            if self.legerdemain_gems:
                self.next_gem_check = min(self.next_gem_check, t + 0.10)

        self.last_legerdemain_cast_t = t
        vis_r = min(conv_rad, 45.0) if self.has_legerdemain_augment else max(4.0, 8.0 * self.range_mult)
        self._record_pulse(t, ppos, 2, vis_r, 0.45, len(eligible) + len(gems_near) + conjured)
        self.next_action_at = t + max(0.35, 0.80 / self.cast_speed_mult)
        return True

    def _step_mirage_legerdemain(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        # Maintain 1 Hall of Mirrors (if Slot 1 is retained and not already cast by rotation) so 2 spawns +4 mini-jewels!
        if self.has_hall_of_mirrors_slot and not self._is_hall_of_mirrors_active(t):
            rot = self.wf_state.rotation if self.wf_state is not None else None
            rot_has_hom = any(
                getattr(it, "slot_index", None) == 0 or "illusion" in str(getattr(it, "primary_id", "")).casefold()
                for it in (getattr(rot, "items", None) or ())
            )
            if not rot_has_hom and self._try_spend_cast(t, 25.0, 0.73):
                self.hom_until = t + 25.0 * self.duration
                self._record_pulse(t, ppos, 1, 6.0, 0.40, 4)
                self.next_action_at = t + max(0.30, 0.73 / self.cast_speed_mult)
                return

        conv_rad = 40.0 * self.range_mult
        if self.has_legerdemain_augment:
            eligible = [p for p in self.ground_pickups if distance(ppos, p["pos"]) <= conv_rad]
            gems_near = [g for g in self.legerdemain_gems if distance(ppos, g["pos"]) <= conv_rad]
            needs_refresh = bool(gems_near) and min(g["expires_at"] - t for g in gems_near) <= 6.0
            needs_convert = len(eligible) >= 3 or (
                len(eligible) >= 1 and (len(self.legerdemain_gems) < 3 or t - self.last_legerdemain_cast_t >= 3.0)
            )
            # In pure ability_only when 0 gems & 0 pickups exist yet, conjure 1+4 Jewels on visible enemies to score first kills!
            needs_jewel_bootstrap = (
                self.combat_style == "ability_only"
                and not self.legerdemain_gems
                and not self.ground_pickups
                and not self.present_jewels
                and bool(self._eligible_targets(world, ppos, 55.0, require_los=True))
            )
            if needs_refresh or needs_convert or needs_jewel_bootstrap:
                self._cast_sleight_of_hand(world, ppos, t, conv_rad, eligible, gems_near)
                return
            self.next_action_at = t + 0.25
            return

        # Without Explosive Legerdemain augment: conjure 1 Primary + 4 Hall of Mirrors Mini-Jewels whenever previous jewels popped!
        if not self.present_jewels and self._eligible_targets(world, ppos, 55.0, require_los=True):
            self._cast_sleight_of_hand(world, ppos, t, conv_rad, [], [])
            return
        self.next_action_at = t + 0.30

    def _step_autonomous_auras(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        # 0. Mirage Sleight of Hand 1+2 Jewels + Explosive Legerdemain 60s proximity gems
        if self.setup_id == "mirage_legerdemain":
            if self.present_jewels:
                self._step_present_jewels(world, t)
            if self.legerdemain_gems:
                self._step_legerdemain_gems(world, t)

        # 1. Mirage Prism 0.5s laser ticks + 10/s channel drain + per-hit damage ramp
        if t < self.prism_until - EPS and t >= self.prism_next_tick - EPS:
            ok, self.prism_last_drain_t = self._drain_channel(t, self.prism_last_drain_t, 10.0)
            if not ok:
                self.prism_until = -math.inf
                self.prism_next_tick = math.inf
            else:
                rad = self.slot_radii.get(4, self.primary_radius)
                targets = self._eligible_targets(world, ppos, rad, require_los=True)
                targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
                ramp = 1.0 + self.prism_ramp_rate * min(40, self.prism_hits)
                tick_dmg = 250.0 * self.strength * ramp
                hits = 0
                for actor in targets[:20]:
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_RADIATION": tick_dmg},
                        t,
                        forced_procs={"DT_RADIATION": 0.35},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                    hits += 1
                self.prism_hits += hits
                if hits > 0:
                    self._record_pulse(t, ppos, 4, rad, 0.40, hits)
                self.prism_next_tick = t + 0.50 if t + 0.50 < self.prism_until else math.inf
        elif t >= self.prism_until - EPS and self.prism_next_tick < math.inf:
            self.prism_next_tick = math.inf
            if self.wf_state.rotation is not None and not self.maim_active and not self.mesa_active:
                self.wf_state.rotation.external_channel_active = False

        # 2. Gyre Cathode Grace passive energy regen (1.5/s * Strength) + Rotorswell 1.0s electric discharges
        if self.setup_id == "gyre_rotorswell" and t < self.grace_until - EPS:
            rot = self.wf_state.rotation
            has_rot_grace = any(
                "cathode" in str(getattr(it, "primary_id", "")).casefold()
                for it in (getattr(rot, "items", None) or ())
            )
            dt_g = max(0.0, t - self.grace_last_regen_t)
            if dt_g > EPS and not has_rot_grace:
                gain = 1.5 * self.strength * dt_g
                if rot is not None:
                    rot.energy = min(rot.max_energy, rot.energy + gain)
                    self.wf_state.energy = rot.energy
                else:
                    self.wf_state.energy = min(self.wf_state.max_energy, self.wf_state.energy + gain)
            self.grace_last_regen_t = t
        if t < self.rotorswell_until - EPS and t >= self.rotorswell_next_arc - EPS:
            rad = self.primary_radius
            targets = self._eligible_targets(world, ppos, rad, require_los=False)
            crit_factor = 1.0 + min(2.5, 0.50 * self.strength)
            arc_dmg = 1200.0 * self.strength * crit_factor
            hits = 0
            for actor in targets[:12]:
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_ELECTRICITY": arc_dmg},
                    t,
                    forced_procs={"DT_ELECTRICITY": 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )
                hits += 1
            if hits > 0:
                self._notify_electric_ability_hit(t)
                self._record_pulse(t, ppos, 4, rad, 0.35, hits)
            self.rotorswell_next_arc = t + 1.0 if t + 1.0 < self.rotorswell_until else math.inf

        # 3. Saryn Spores 1.0s corrosive ticks on infected targets + decay when 0 infected
        if self.setup_id == "saryn_spores_miasma" and t >= self.spores_next_tick - EPS:
            live_by_id = {
                a.id: a
                for a in world.live
                if not a.dead and not a.drone and world.combat.targets.get(a.id) and not world.combat.targets[a.id].protected
            }
            self.spored_ids &= set(live_by_id.keys())
            if self.spored_ids:
                self.spores_damage = min(100000.0, self.spores_damage + 2.0 * self.strength * min(7, len(self.spored_ids)))
                for aid in list(self.spored_ids):
                    actor = live_by_id.get(aid)
                    if actor is None:
                        continue
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_CORROSIVE": self.spores_damage},
                        t,
                        forced_procs={"DT_CORROSIVE": 0.50},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
            else:
                # Spores decay when no enemies are currently infected
                self.spores_damage = max(100.0 * self.strength, self.spores_damage * 0.85)
            self.spores_next_tick = t + 1.0

        # 4. Volt Discharge 0.5s Tesla coil neighbor cross-arcs (0 damage to lone targets for first 4.5s!)
        if self.setup_id == "volt_discharge" and t >= self.volt_next_tick - EPS:
            coil_rad = 8.0 * self.range_mult
            live_coils: list[tuple[Any, float]] = []
            for aid, (cast_t, end_t) in list(self.stunned_until.items()):
                if t >= end_t - EPS:
                    del self.stunned_until[aid]
                    continue
                actor = world.actors.get(aid)
                v = world.combat.targets.get(aid)
                if actor is None or actor.dead or actor.drone or v is None or not v.alive or v.protected:
                    del self.stunned_until[aid]
                    continue
                live_coils.append((actor, cast_t))
            if live_coils:
                all_elig = self._eligible_targets(world, ppos, self.primary_radius + coil_rad, require_los=False)
                hits = 0
                for actor, cast_t in live_coils:
                    neighbors = sum(
                        1 for other in all_elig if other.id != actor.id and distance(actor.pos, other.pos) <= coil_rad
                    )
                    if neighbors > 0:
                        tick_dmg = neighbors * 600.0 * self.strength
                    elif t - cast_t >= 4.5:
                        tick_dmg = 600.0 * self.strength
                    else:
                        continue
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_ELECTRICITY": tick_dmg},
                        t,
                        forced_procs={"DT_ELECTRICITY": 0.50},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                    hits += 1
                if hits > 0:
                    self._notify_electric_ability_hit(t)
                self.volt_next_tick = t + 0.50
            else:
                self.volt_next_tick = math.inf

        # 5. Gara Splinter Storm 1.0s contact shred around Warframe
        if self.setup_id == "gara_shatter_storm" and t < self.splinter_until - EPS and t >= self.splinter_next_tick - EPS:
            if self.splinter_storm_dps > 0.0:
                storm_rad = max(2.5, 2.5 * self.range_mult)
                for actor in self._eligible_targets(world, ppos, storm_rad, require_los=True):
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_SLASH": self.splinter_storm_dps},
                        t,
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                    )
            self.splinter_next_tick = t + 1.0 if t + 1.0 < self.splinter_until else math.inf

        # 6. Ember Inferno 1.0s lingering Fire Rings
        if self.setup_id == "ember_inferno" and t >= self.ember_next_tick - EPS:
            active_rings = 0
            for aid, end_t in list(self.fire_ring_until.items()):
                if t >= end_t - EPS:
                    del self.fire_ring_until[aid]
                    continue
                actor = world.actors.get(aid)
                v = world.combat.targets.get(aid)
                if actor is None or actor.dead or actor.drone or v is None or not v.alive or v.protected:
                    del self.fire_ring_until[aid]
                    continue
                active_rings += 1
                world.combat.apply_ability_hit(
                    aid,
                    {"DT_FIRE": 700.0 * self.strength},
                    t,
                    forced_procs={"DT_FIRE": 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )
            self.ember_next_tick = (t + 1.0) if active_rings > 0 else math.inf

        # 7. Nokko Sporespring bounces (up to 3 bounces across enemy clusters)
        if self.setup_id == "nokko_sporespring" and self.sporespring_bounces_left > 0 and t >= self.sporespring_next_bounce - EPS:
            origin = self.sporespring_pos or ppos
            bounce_rad = max(6.0, 12.0 * self.range_mult)
            candidates = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
            if candidates:
                candidates.sort(key=lambda a: (distance(origin, a.pos), a.id))
                anchor = candidates[0]
                self.sporespring_pos = tuple(anchor.pos)
                hits = 0
                bounce_dmg = max(600.0, self.unbuffed_direct * 0.42)
                for actor in candidates:
                    if distance(anchor.pos, actor.pos) <= bounce_rad:
                        world.combat.apply_ability_hit(
                            actor.id,
                            {"DT_GAS": bounce_dmg * 0.65, "DT_POISON": bounce_dmg * 0.35},
                            t,
                            forced_procs={"DT_POISON": 1.0, "DT_GAS": 1.0},
                            roar_bonus=self.roar_bonus,
                            vuln_mult=self.vuln_mult,
                            status_dmg_vuln=self.status_dmg_vuln,
                        )
                        hits += 1
                self._record_pulse(t, anchor.pos, 4, bounce_rad, 0.45, hits)
            self.sporespring_bounces_left -= 1
            self.sporespring_next_bounce = (t + 0.45) if self.sporespring_bounces_left > 0 else math.inf

    def _step_equinox_maim(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        if not self.maim_active:
            if self._try_spend_cast(t, 50.0, 0.85):
                self.maim_active = True
                self.maim_pool = 0.0
                self.maim_bled_ids.clear()
                self.maim_last_drain_t = t
                targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
                slash_hit = 150.0 * self.strength
                for actor in targets:
                    self.maim_bled_ids.add(actor.id)
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_SLASH": slash_hit},
                        t,
                        forced_procs={"DT_SLASH": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.55, len(targets))
                self.next_action_at = t + max(0.35, 0.85 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40
            return

        ok, self.maim_last_drain_t = self._drain_channel(t, self.maim_last_drain_t, 3.5)
        if not ok:
            self.maim_active = False
            self.next_action_at = t + 0.50
            return

        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        slash_hit = 150.0 * self.strength
        for actor in targets:
            if actor.id not in self.maim_bled_ids:
                self.maim_bled_ids.add(actor.id)
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_SLASH": slash_hit},
                    t,
                    forced_procs={"DT_SLASH": 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )

        # Detonate Maim using exact client linear falloff `1 - d / R` when pool wipes >=60% of live unprotected targets
        if targets and self.maim_pool > 100.0:
            killable = 0
            for actor in targets:
                v = world.combat.targets[actor.id]
                d = distance(ppos, actor.pos)
                falloff = max(0.05, 1.0 - d / max(1.0, self.primary_radius))
                eff = self.maim_pool * falloff * (1.0 + self.roar_bonus) * self.vuln_mult
                rem = v.overguard + v.shield + v.health / max(0.12, world.combat._armour_factor(v, t))
                if eff >= rem:
                    killable += 1
            if killable >= max(1, math.ceil(len(targets) * 0.60)) or killable >= 4:
                hits = 0
                for actor in targets:
                    d = distance(ppos, actor.pos)
                    falloff = max(0.05, 1.0 - d / max(1.0, self.primary_radius))
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_SLASH": self.maim_pool * falloff},
                        t,
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                    )
                    hits += 1
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.75, hits)
                self.maim_active = False
                self.maim_pool = 0.0
                if self.wf_state.rotation is not None:
                    self.wf_state.rotation.external_channel_active = False
                self.next_action_at = t + max(0.30, 0.55 / self.cast_speed_mult)
                return

        self.next_action_at = t + 0.25

    def _step_mesa_peacemaker(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        if self.combat_style == "hybrid_nuke":
            eye = _add_y(ppos, 1.55)
            has_visible_drone = any(
                a.drone and not a.dead and world.scene.visible(eye, _add_y(a.pos, 0.85))
                for a in world.live
            )
            if has_visible_drone:
                if self.mesa_active:
                    self.mesa_active = False
                    if self.wf_state.rotation is not None:
                        self.wf_state.rotation.external_channel_active = False
                self.next_action_at = t + 0.30
                return

        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=True)
        if not targets:
            if self.mesa_active:
                ok, self.mesa_last_drain_t = self._drain_channel(t, self.mesa_last_drain_t, 15.0)
                if not ok:
                    self.mesa_active = False
            self.next_action_at = t + 0.20
            return

        if not self.mesa_active:
            if not self._try_spend_cast(t, 25.0, 0.35):
                self.next_action_at = t + 0.35
                return
            self.mesa_active = True
            self.mesa_shots_fired = 0
            self.mesa_last_drain_t = t

        ok, self.mesa_last_drain_t = self._drain_channel(t, self.mesa_last_drain_t, 15.0)
        if not ok:
            self.mesa_active = False
            self.next_action_at = t + 0.40
            return

        ex = self.nuke.get("exaltedStats") or {}
        shots_per_sec = max(6.0, float(ex.get("maxShotsPerSec") or 22.0))
        burst_dt = 0.20
        burst_shots = max(1, int(round(shots_per_sec * burst_dt)))
        single_shot_dmg = max(150.0, self.unbuffed_direct / max(1.0, shots_per_sec))

        targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
        hits = 0
        for i in range(burst_shots):
            live_now = [a for a in targets if not a.dead and world.combat.targets[a.id].alive]
            if not live_now:
                break
            actor = live_now[i % len(live_now)]
            ramp = min(2.5, 1.0 + 0.075 * self.mesa_shots_fired)
            self.mesa_shots_fired += 1
            world.combat.apply_ability_hit(
                actor.id,
                {"DT_IMPACT": single_shot_dmg * 0.25 * ramp, "DT_FIRE": single_shot_dmg * 0.75 * ramp},
                t,
                forced_procs={"DT_FIRE": 0.45, "DT_VIRAL": 0.25},
                roar_bonus=self.roar_bonus,
                vuln_mult=self.vuln_mult,
                status_dmg_vuln=self.status_dmg_vuln,
            )
            hits += 1
        if hits > 0 and (len(self.pulses) == 0 or t - self.pulses[-1][0] >= 0.80):
            self._record_pulse(t, ppos, 4, min(self.primary_radius, 28.0), 0.35, hits)
        if self.wf_state.rotation is not None:
            self.wf_state.rotation.weapon_locked_until = max(self.wf_state.rotation.weapon_locked_until, t + burst_dt)
        self.next_action_at = t + burst_dt

    def _step_gara_combo(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self.phase == 0:
            # Weave Splinter Storm (2) ONLY after opening 4->1 or when energy comfortably covers 2 + 4 + 1
            # (never burn opening Zenurik Inner Might on 2 when 4 costs 116 energy with Blind Rage!)
            cur_energy = float(self.wf_state.energy) if self.wf_state is not None else 0.0
            full_combo_cost = self._eff_cost(50.0) + self._eff_cost(75.0) + self._eff_cost(25.0)
            if (
                self.has_splinter_storm
                and self.casts_executed >= 2
                and t >= self.splinter_until - EPS
                and cur_energy >= full_combo_cost
                and self._try_spend_cast(t, 50.0, 0.60)
            ):
                self.splinter_until = t + 22.0 * self.duration
                self.splinter_next_tick = t + 1.0
                self.next_action_at = t + max(0.30, 0.60 / self.cast_speed_mult)
                return

            # Cast Mass Vitrify (4) with dynamic ring expansion sized to live enemy distance
            max_d = max(distance(ppos, a.pos) for a in targets)
            base_r4 = max(4.0, 2.0 * self.range_mult)
            exp_rate = max(1.5, (9.0 / 3.0) * self.range_mult)
            needed_ring = max(base_r4, max_d - 12.0 * self.range_mult)
            exp_sec = max(0.35, min(1.60, 3.0 * self.duration, (needed_ring - base_r4) / exp_rate))
            if self._try_spend_cast(t, 75.0, 0.75 + exp_sec):
                self.phase = 1
                ring_rad = min(11.0 * self.range_mult, base_r4 + exp_rate * exp_sec)
                self.vitrified_ids = {a.id for a in targets if distance(ppos, a.pos) <= ring_rad + 2.5}
                if t < self.splinter_until - EPS:
                    self.splinter_until = t + 22.0 * self.duration
                self._record_pulse(t, ppos, 4, ring_rad, 0.85, len(targets))
                self.next_action_at = t + max(0.45, (0.75 + exp_sec) / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40
        else:
            # Cast Shattered Lash (1) -> shatter ring, ignore cover radial nuke + accumulate 50% into Splinter Storm!
            if self._try_spend_cast(t, 25.0, 0.75):
                self.phase = 0
                hits = 0
                for actor in targets:
                    vitrify_vuln = 1.5 if (not self.vitrified_ids or actor.id in self.vitrified_ids) else 1.25
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_PUNCTURE": self.unbuffed_direct * 0.5, "DT_CORROSIVE": self.unbuffed_direct * 0.5},
                        t,
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult * vitrify_vuln,
                    )
                    hits += 1
                self.vitrified_ids.clear()
                if t < self.splinter_until - EPS:
                    self.splinter_storm_dps = min(5_000_000.0, self.splinter_storm_dps + 0.50 * self.unbuffed_direct)
                self._record_pulse(t, ppos, 1, self.primary_radius, 0.75, hits)
                self.next_action_at = t + max(0.40, 0.80 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.35

    def _step_dante_tragedy(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        if self.phase < 2:
            rad3 = self.slot_radii.get(3, self.primary_radius * 0.7)
            targets = self._eligible_targets(world, ppos, rad3, require_los=True)
            if not targets:
                self.next_action_at = t + 0.25
                return
            if self._try_spend_cast(t, 50.0, 0.55):
                self.phase += 1
                verse_dmg = max(500.0, self.unbuffed_direct * 0.14)
                for actor in targets:
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_SLASH": verse_dmg},
                        t,
                        forced_procs={"DT_SLASH": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                self._record_pulse(t, ppos, 3, rad3, 0.45, len(targets))
                self.next_action_at = t + max(0.30, 0.55 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40
        else:
            targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
            if self._try_spend_cast(t, 100.0, 0.90):
                self.phase = 0
                tragedy_direct = max(1500.0, self.unbuffed_direct * 0.35)
                condense_mult = 3.0 * self.strength
                for actor in targets:
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_SLASH": tragedy_direct},
                        t,
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        condense_dots_mult=condense_mult,
                    )
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.80, len(targets))
                self.next_action_at = t + max(0.45, 0.95 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40

    def _step_khora_whipclaw(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        if t >= self.accum_whip_until - EPS and self.accum_whip_stacks > 0:
            self.accum_whip_stacks = max(0, self.accum_whip_stacks - 1)
            self.accum_whip_until = t + 10.0

        if t >= self.dome_until - EPS:
            if self._try_spend_cast(t, 100.0, 1.0):
                self.dome_until = t + 20.0 * self.duration
                self.dome_pos = ppos
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.70, 0)
                self.next_action_at = t + max(0.40, 1.0 / self.cast_speed_mult)
                return

        cast_range = max(10.0, 10.0 * self.range_mult)
        targets = self._eligible_targets(world, ppos, max(cast_range, self.primary_radius), require_los=True)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self._try_spend_cast(t, 25.0, 0.55):
            targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
            primary = targets[0]
            whip_rad = self.slot_radii.get(1, min(10.0, 5.0 * self.range_mult))
            dome_origin = self.dome_pos or ppos
            dome_rad = max(10.0, 10.0 * self.range_mult)

            # Scale dynamically with live Accumulating Whipclaw stacks (preview bakes 10 stacks if equipped)
            stack_scale = (
                (1.0 + 0.35 * self.accum_whip_stacks) / 4.5 if self.has_accum_whip else 1.0
            )
            direct_hits = 0
            hits = 0
            for actor in self._eligible_targets(world, dome_origin, max(self.primary_radius, dome_rad + whip_rad), require_los=False):
                in_whip = distance(primary.pos, actor.pos) <= whip_rad and world.scene.visible(
                    _add_y(primary.pos, 0.85), _add_y(actor.pos, 0.85)
                )
                in_dome = t < self.dome_until - EPS and distance(dome_origin, actor.pos) <= dome_rad
                if not in_whip and not in_dome:
                    continue
                if in_whip:
                    direct_hits += 1
                share = 1.0 if in_whip else 0.50
                dmg = self.unbuffed_direct * stack_scale * share
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_SLASH": dmg * 0.55, "DT_CORROSIVE": dmg * 0.45},
                    t,
                    forced_procs={"DT_SLASH": 0.60 * share},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult * (2.0 if in_dome else 1.0),
                    status_dmg_vuln=self.status_dmg_vuln,
                )
                hits += 1
            if self.has_accum_whip and direct_hits >= 3:
                self.accum_whip_stacks = min(10, self.accum_whip_stacks + 1)
                self.accum_whip_until = t + 10.0
            self._record_pulse(t, primary.pos, 1, whip_rad, 0.50, hits)
            self.next_action_at = t + max(0.35, 0.65 / self.cast_speed_mult)
        else:
            self.next_action_at = t + 0.35

    def _step_sevagoth_combo(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self.phase == 0:
            if self._try_spend_cast(t, 50.0, 0.70):
                self.phase = 1
                self._record_pulse(t, ppos, 2, self.primary_radius, 0.55, len(targets))
                self.next_action_at = t + max(0.35, 0.70 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40
        else:
            if self._try_spend_cast(t, 25.0, 0.75):
                self.phase = 0
                reap_vuln = 1.0 + 0.50 * self.strength
                pct = max(0.25, self.true_hp_pct)
                for actor in targets:
                    v = world.combat.targets[actor.id]
                    true_dmg = max(500.0, v.health * pct)
                    blast_dmg = 1000.0 * self.strength
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_CINEMATIC": true_dmg, "DT_EXPLOSION": blast_dmg},
                        t,
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult * reap_vuln,
                    )
                self._record_pulse(t, ppos, 1, self.primary_radius, 0.75, len(targets))
                self.next_action_at = t + max(0.45, 0.80 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40

    def _step_mirage_prism(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        if t < self.prism_until - EPS:
            self.next_action_at = min(self.prism_until, t + 0.50)
            return
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=True)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self._try_spend_cast(t, 50.0, 1.15):
            dur = max(2.5, 4.0 * self.duration)
            self.prism_until = t + dur
            self.prism_last_drain_t = t
            self.prism_hits = 0
            self.prism_next_tick = t + 0.25
            self._record_pulse(t, ppos, 4, self.primary_radius, 0.65, len(targets))
            self.next_action_at = self.prism_until
        else:
            self.next_action_at = t + 0.40

    def _step_thermal_sunder(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self.phase < 2:
            if self._try_spend_cast(t, 50.0, 0.55):
                self.phase += 1
                heat_hit = max(350.0, self.unbuffed_direct * 0.28) * (2.0 if self.phase == 2 else 1.0)
                for actor in targets:
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_FIRE": heat_hit},
                        t,
                        forced_procs={"DT_FIRE": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                self._record_pulse(t, ppos, 3, self.primary_radius, 0.50, len(targets))
                self.next_action_at = t + max(0.30, 0.55 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.35
        else:
            if self._try_spend_cast(t, 50.0, 0.55):
                self.phase = 0
                for actor in targets:
                    if self.armor_strip > 0.0:
                        world.combat.strip_target_armor(actor.id, self.armor_strip)
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_EXPLOSION": max(600.0, self.unbuffed_direct * 0.45)},
                        t,
                        forced_procs={"DT_FREEZE": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        condense_dots_mult=1.0,
                    )
                self._record_pulse(t, ppos, 3, self.primary_radius, 0.65, len(targets))
                self.next_action_at = t + max(0.35, 0.65 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.35

    def _step_gyre_rotorswell(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Maintain Gyre 3 Cathode Grace + 4 Rotorswell ONLY when expired; kills extend both up to 60s/40s!"""
        rot = self.wf_state.rotation
        rot_grace = next(
            (it for it in (getattr(rot, "items", None) or ()) if "cathode" in str(getattr(it, "primary_id", "")).casefold()),
            None,
        )
        if rot_grace is not None and rot_grace.active_until > t + EPS:
            self.grace_until = max(self.grace_until, rot_grace.active_until)

        if t >= self.grace_until - EPS:
            if rot_grace is None:
                if self._try_spend_cast(t, 75.0, 0.65):
                    self.grace_until = t + 8.0 * self.duration
                    self.grace_last_regen_t = t
                    self._record_pulse(t, ppos, 3, max(8.0, 10.0 * self.range_mult), 0.50, 0)
                    self.next_action_at = t + max(0.30, 0.65 / self.cast_speed_mult)
                    return
                self.next_action_at = t + 0.35
                return

        if t >= self.rotorswell_until - EPS:
            targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
            if not targets:
                self.next_action_at = t + 0.25
                return
            if self._try_spend_cast(t, 100.0, 0.95):
                self.rotorswell_until = t + 12.0 * self.duration
                self.rotorswell_next_arc = t + 0.25
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.65, len(targets))
                self.next_action_at = t + max(0.45, 0.95 / self.cast_speed_mult)
            else:
                self.next_action_at = t + 0.40
            return

        # Both 3 & 4 are active: do NOT spam-recast! Autonomous rotor arcs + weapon crits + kill extensions drive clear.
        self.next_action_at = min(self.grace_until, self.rotorswell_until, t + 0.50)

    def _step_saryn_combo(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """State-driven Saryn 1 Spores infection/spread + 4 Miasma 4x Viral multiplier on infected targets."""
        live_elig = self._eligible_targets(world, ppos, max(self.primary_radius, 60.0 * self.range_mult), require_los=False)
        if not live_elig:
            self.next_action_at = t + 0.25
            return
        live_ids = {a.id for a in live_elig}
        self.spored_ids &= live_ids

        # Step 1: Seed 1 Spores (requires LoS, 60m * Range) ONLY when 0 live enemies are currently infected!
        if not self.spored_ids:
            vis_targets = self._eligible_targets(world, ppos, 60.0 * self.range_mult, require_los=True)
            if vis_targets:
                if self._try_spend_cast(t, 25.0, 0.70):
                    vis_targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
                    seed_actor = vis_targets[0]
                    self.spored_ids.add(seed_actor.id)
                    self._record_pulse(t, seed_actor.pos, 1, 16.0 * self.range_mult, 0.45, 1)
                    self.next_action_at = t + max(0.35, 0.70 / self.cast_speed_mult)
                else:
                    self.next_action_at = t + 0.35
                return

        # Step 2: Cast 4 Miasma (20m * Range, ignores LoS) when Miasma expired or >=4 infected enemies ready to pop
        miasma_targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        infected_in_miasma = sum(1 for a in miasma_targets if a.id in self.spored_ids)
        should_miasma = bool(miasma_targets) and (
            t >= self.miasma_until - EPS or infected_in_miasma >= 4
        )
        if should_miasma:
            if self._try_spend_cast(t, 75.0, 1.30):
                self.miasma_until = t + max(3.0, 6.0 * self.duration)
                base_miasma = 300.0 * self.strength * max(1.0, self.duration)
                for actor in miasma_targets:
                    mult = 4.0 if actor.id in self.spored_ids else 1.0
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_VIRAL": base_miasma * mult},
                        t,
                        forced_procs={"DT_VIRAL": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.75, len(miasma_targets))
                self.next_action_at = t + max(0.80, 1.30 / self.cast_speed_mult + 1.20)
            else:
                self.next_action_at = t + 0.40
            return

        self.next_action_at = t + 0.35

    def _step_volt_discharge(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Cast 4 Discharge on packs; let Tesla coils cross-arc packs while gun cleans lone stragglers."""
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.next_action_at = t + 0.25
            return
        unstunned = [a for a in targets if t >= self.stunned_until.get(a.id, (0.0, -math.inf))[1] - EPS]
        min_pack = 1 if (self.combat_style == "ability_only" and not self.stunned_until) else 3
        if len(unstunned) < min_pack:
            self.next_action_at = t + 0.30
            return
        if self._try_spend_cast(t, 100.0, 1.65):
            dur = max(3.0, 6.0 * self.duration)
            for actor in targets:
                self.stunned_until[actor.id] = (t, t + dur)
            self.volt_next_tick = min(self.volt_next_tick, t + 0.50)
            self._notify_electric_ability_hit(t)
            self._record_pulse(t, ppos, 4, self.primary_radius, 0.75, len(targets))
            self.next_action_at = t + max(0.80, 1.65 / self.cast_speed_mult + 0.50)
        else:
            self.next_action_at = t + 0.40

    def _step_ember_inferno(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Ember 3 Fire Blast armor strip + 4 Inferno (camera/LoS check, 10*min(10,N) energy cap, lingering Fire Rings)."""
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=True)
        if not targets:
            self.next_action_at = t + 0.25
            return
        unringed = [a for a in targets if t >= self.fire_ring_until.get(a.id, -math.inf) - EPS]
        if not unringed and len(targets) < 4:
            self.next_action_at = t + 0.40
            return

        # Strip armor with 3 Fire Blast first if armored enemies are present
        if self.armor_strip > 0.0:
            needs_strip = any(world.combat.targets[a.id].defenses.get("armour", 0.0) > 25.0 for a in targets)
            if needs_strip and self._try_spend_cast(t, 50.0, 0.65):
                for actor in targets:
                    world.combat.strip_target_armor(actor.id, self.armor_strip)
                self._record_pulse(t, ppos, 3, self.primary_radius, 0.45, len(targets))
                self.next_action_at = t + max(0.30, 0.65 / self.cast_speed_mult)
                return

        hit_list = unringed if unringed else targets
        dyn_base_cost = 10.0 * min(10, max(1, len(hit_list)))
        if self._try_spend_cast(t, dyn_base_cost, 0.90):
            ring_dur = max(5.0, 15.0 * self.duration)
            meteor_dmg = 2500.0 * self.strength
            for actor in hit_list:
                self.fire_ring_until[actor.id] = t + ring_dur
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_FIRE": meteor_dmg * 0.70, "DT_IMPACT": meteor_dmg * 0.30},
                    t,
                    forced_procs={"DT_FIRE": 2.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                )
            self.ember_next_tick = min(self.ember_next_tick, t + 1.0)
            self._record_pulse(t, ppos, 4, self.primary_radius, 0.70, len(hit_list))
            self.next_action_at = t + max(0.60, 0.90 / self.cast_speed_mult + 0.50)
        else:
            self.next_action_at = t + 0.40

    def _step_nezha_retribution(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Nezha 4 Divine Retribution: Phase 0 Impale -> spread status -> Phase 1 Spear Slam DoT condense."""
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.phase = 0
            self.speared_ids.clear()
            self.next_action_at = t + 0.25
            return
        if self.phase == 0:
            if self._try_spend_cast(t, 100.0, 0.85):
                self.phase = 1
                self.speared_ids = {a.id for a in targets}
                impale_dmg = 600.0 * self.strength
                for actor in targets:
                    world.combat.apply_ability_hit(
                        actor.id,
                        {"DT_PUNCTURE": impale_dmg * 0.4, "DT_SLASH": impale_dmg * 0.6},
                        t,
                        forced_procs={"DT_SLASH": 2.0, "DT_FIRE": 1.0},
                        roar_bonus=self.roar_bonus,
                        vuln_mult=self.vuln_mult,
                        status_dmg_vuln=self.status_dmg_vuln,
                    )
                self._record_pulse(t, ppos, 4, self.primary_radius, 0.60, len(targets))
                # Short window for weapon status priming in hybrid_nuke before Slam condense!
                self.next_action_at = t + max(0.45, 0.85 / self.cast_speed_mult + 0.35)
            else:
                self.next_action_at = t + 0.40
        else:
            self.phase = 0
            slam_targets = [a for a in targets if a.id in self.speared_ids] or targets
            slam_dmg = 600.0 * self.strength
            condense = 1.5 * self.strength
            for actor in slam_targets:
                world.combat.apply_ability_hit(
                    actor.id,
                    {"DT_IMPACT": slam_dmg},
                    t,
                    forced_procs={"DT_SLASH": 1.0},
                    roar_bonus=self.roar_bonus,
                    vuln_mult=self.vuln_mult,
                    status_dmg_vuln=self.status_dmg_vuln,
                    condense_dots_mult=condense,
                )
            self.speared_ids.clear()
            self._record_pulse(t, ppos, 4, self.primary_radius, 0.65, len(slam_targets))
            self.next_action_at = t + max(0.55, 0.70 / self.cast_speed_mult)

    def _step_nokko_sporespring(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Nokko 4 Sporespring multi-bounce mushroom spore nuke (2 Brightbonnet is already maintained by rotation!)."""
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=False)
        if not targets:
            self.next_action_at = t + 0.25
            return
        if self.sporespring_bounces_left > 0:
            self.next_action_at = t + 0.35
            return
        if self._try_spend_cast(t, 100.0, 0.85):
            targets.sort(key=lambda a: (distance(ppos, a.pos), a.id))
            first = targets[0]
            self.sporespring_pos = tuple(first.pos)
            self.sporespring_bounces_left = 3
            self.sporespring_next_bounce = t + 0.15
            self.next_action_at = t + max(1.45, 0.85 / self.cast_speed_mult + 1.25)
        else:
            self.next_action_at = t + 0.40

    def _step_radial_nuke(self, world: Any, ppos: tuple[float, float, float], t: float) -> None:
        """Handles Frost Avalanche (4), Mag Crush (4), and generic radial nukes."""
        targets = self._eligible_targets(world, ppos, self.primary_radius, require_los=not self.ignores_los)
        if not targets:
            self.next_action_at = t + 0.25
            return

        speed_cap = 1.5 if self.setup_id == "frost_avalanche" else None
        cast_sec = 1.85 if self.setup_id == "frost_avalanche" else self.combo_sec
        if not self._try_spend_cast(t, 100.0, cast_sec, speed_cap=speed_cap):
            self.next_action_at = t + 0.40
            return

        dtype = "DT_EXPLOSION"
        procs: dict[str, float] = {}
        if self.setup_id == "frost_avalanche":
            dtype = "DT_FREEZE"
            procs = {"DT_FREEZE": 6.0}
        elif self.setup_id == "mag_crush":
            dtype = "DT_MAGNETIC"
            procs = {"DT_MAGNETIC": 1.0}

        for actor in targets:
            # Strip armor BEFORE applying hit damage (Frost Avalanche / Fracturing Crush client order)
            if self.armor_strip > 0.0:
                world.combat.strip_target_armor(actor.id, self.armor_strip)
            if self.setup_id == "frost_avalanche":
                self.frozen_by_avalanche.add(actor.id)
            world.combat.apply_ability_hit(
                actor.id,
                {dtype: self.unbuffed_direct},
                t,
                forced_procs=procs,
                roar_bonus=self.roar_bonus,
                vuln_mult=self.vuln_mult,
                status_dmg_vuln=self.status_dmg_vuln,
            )

        self._record_pulse(t, ppos, 4, self.primary_radius, 0.75, len(targets))
        eff_cs = min(self.cast_speed_mult, speed_cap) if speed_cap is not None else self.cast_speed_mult
        cooldown = max(1.1, cast_sec / max(0.25, eff_cs) + 0.55)
        self.next_action_at = t + cooldown

    def summary_payload(self, combat: Any) -> dict[str, Any]:
        total_kills = max(0, int(combat.kills))
        ab_kills = max(0, int(combat.ability_kills))
        wp_kills = max(0, int(combat.weapon_kills))
        payload: dict[str, Any] = {
            "setupId": self.setup_id,
            "titleZh": self.title_zh,
            "combatStyle": self.combat_style,
            "primaryRadiusM": round(self.primary_radius, 2),
            "ignoresLoS": self.ignores_los,
            "castsExecuted": self.casts_executed,
            "energySpent": round(self.energy_spent, 1),
            "innerMightFreeCasts": self.inner_might_saves,
            "starvedWaits": self.starved_waits,
            "abilityKills": ab_kills,
            "weaponKills": wp_kills,
            "abilityKillShare": round(ab_kills / total_kills, 4) if total_kills > 0 else 0.0,
            "abilityDirectDamage": round(combat.ability_direct_damage, 1),
            "abilityDotDamage": round(combat.ability_dot_damage, 1),
            "pulseCount": len(self.pulses),
        }
        if self.radius_summary_zh:
            payload["radiusSummaryZh"] = self.radius_summary_zh
        if self.setup_id == "mirage_legerdemain":
            payload.update(
                hasLegerdemainAugment=self.has_legerdemain_augment,
                hasHallOfMirrorsSynergy=self.has_hall_of_mirrors_slot,
                mainJewelsConjured=self.main_jewels_conjured,
                cloneMiniJewelsConjured=self.clone_mini_jewels_conjured,
                jewelsDetonated=self.jewels_detonated,
                pickupsDropped=self.pickups_dropped,
                legerdemainGemsConverted=self.gems_converted,
                legerdemainGemsRefreshed=self.gems_refreshed,
                legerdemainGemsDetonated=self.gems_detonated,
                legerdemainGemsActive=len(self.legerdemain_gems),
            )
        elif self.setup_id == "gyre_rotorswell":
            payload["gyreKillExtensions"] = self.gyre_kill_extensions
        return payload
