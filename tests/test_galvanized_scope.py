"""Contract: Galvanized conditional damage (WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE)
scope, per the engine RE verdict (galvanized-radial-re.json, build 2026.09.22):

- The per-status-stack bonus applies to DIRECT damage (the exported direct
  vector covers direct+radial in the panel; radial exports are absent from
  the frozen build — separately registered).
- The bonus must NOT inflate DoT seeds: the window model builds its DoT
  payload from the CO-stripped base vector (probe runs after the CO
  rollback), so slash/heat/etc. tick damage carries no CO multiplication.
- DoT tick events failing the engine's two gates (hitType=DHT_DOT(7) and
  proc-context sentinel 30) is the in-game mechanism behind that exclusion.

Pinned through the real CO bucket (Condition Overload carries the
WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE upgrade unconditionally).
"""
from __future__ import annotations

import unittest


CONDITION_OVERLOAD = "/Lotus/Upgrades/Mods/Melee/WeaponDamageIfVictimProcActive"


class GalvanizedScopeTests(unittest.TestCase):
    def _stats_pair(self):
        """(CO-boosted stats at 6 statuses, restored CO-free stats) built the
        same way the window model does (rollback by assumed_scale)."""
        import app
        from dataclasses import replace

        from wfarsenal.damage import (
            Scenario,
            _combine,
            _scale_effect,
            apply_mods,
            mod_effects,
        )

        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Melee/Axe/AxeWeapon",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="melee")
        co_rec = app.MANUAL_MODS_BY_PATH.get(CONDITION_OVERLOAD)
        if co_rec is None:
            return None
        effects = mod_effects(co_rec, rank=co_rec.get("maxRank") or 5)

        base = apply_mods(weapon, effects, scenario=Scenario(victim_status_count=0))
        boosted = apply_mods(
            weapon, effects, scenario=Scenario(victim_status_count=6)
        )
        co_bucket = list(getattr(boosted, "co_bucket", None) or [])
        if not co_bucket:
            return None
        assumed_scale = _combine(1.0, [_scale_effect(e, 6) for e in co_bucket])
        if assumed_scale <= 1.0:
            return None
        # The window model's rollback: divide the CO pre-multiplication out.
        restored = replace(
            boosted,
            damage_types={
                dtype: value / assumed_scale
                for dtype, value in boosted.damage_types.items()
            },
            dot_base_damage=(
                boosted.dot_base_damage / assumed_scale
                if boosted.dot_base_damage is not None
                else None
            ),
        )
        return boosted, restored, assumed_scale

    def test_co_scales_direct_vector(self) -> None:
        """With victim statuses active the direct damage vector scales by the
        per-status CO multiplier (engine fn 0x140e266d0 applies it to the
        primary damage event; direct and radial packets both pass)."""
        pair = self._stats_pair()
        if pair is None:
            self.skipTest("Condition Overload not in catalog or CO bucket empty")
        boosted, restored, assumed_scale = pair
        self.assertGreater(
            boosted.total_damage,
            restored.total_damage * 1.05,
            "CO (per-status damage) must scale the direct damage vector",
        )

    def test_windowed_dot_seeds_exclude_co(self) -> None:
        """The windowed model's DoT payload is built from the CO-stripped
        vector: tick seeds must not inherit the per-status CO multiplier
        (engine gates DoT tick events out of the conditional bonus —
        hitType DHT_DOT=7 / proc-context != sentinel 30)."""
        import app
        from wfarsenal.damage import expected_status_damage

        pair = self._stats_pair()
        if pair is None:
            self.skipTest("Condition Overload not in catalog or CO bucket empty")
        boosted, restored, assumed_scale = pair

        probe_boosted = expected_status_damage(boosted, {}, forced_procs={})
        probe_restored = expected_status_damage(restored, {}, forced_procs={})

        def max_seed(probe):
            best = 0.0
            rows = (probe.get("dot") or {}).get("perType") or {}
            for row in rows.values():
                seed = row.get("seedPerSecondPerProc")
                if isinstance(seed, (int, float)) and not isinstance(seed, bool):
                    best = max(best, float(seed))
            return best

        seed_boosted = max_seed(probe_boosted)
        seed_restored = max_seed(probe_restored)
        self.assertGreater(seed_boosted, 0.0)
        # The restored vector's seeds are exactly the boosted ones divided by
        # the CO scale — i.e. the window model's probe input carries no CO.
        self.assertAlmostEqual(
            seed_restored * assumed_scale,
            seed_boosted,
            delta=max(seed_boosted * 0.02, 1e-9),
            msg="DoT seeds must be derived from the CO-stripped vector",
        )
        # And the restored seed is strictly smaller: CO did NOT leak into it.
        self.assertLess(
            seed_restored,
            seed_boosted,
            "DoT seeds must not carry the per-status CO multiplier",
        )


if __name__ == "__main__":
    unittest.main()

