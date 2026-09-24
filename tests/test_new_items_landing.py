"""New-item landing regressions (2026.09.22 fusion-update items).

Primary Acuity (Rifle/Pistol), Worthy Comradery (aura) and Primary Crux
(arcane) all predate the handler wiring in the frozen export; these
tests pin their admission and simulation semantics:

- Acuity mods enter the manual catalog (stale supported markers no
  longer filter them) and their two effects land in the weakpoint
  brackets: ADD +0.318/rank damage, STACKING_MULTIPLY x0.318/rank crit.
- The crit-weakpoint STACKING_MULTIPLY bucket composes from 1.0 (a x0
  combination bug would read 0).
- Primary Crux enters the arcane catalog with its stack semantics
  (10 stacks / 10s) and classifies as on-hit (weakpoint-hit trigger).
"""
from __future__ import annotations

import unittest


ACUITY_RIFLE = "/Lotus/Upgrades/Mods/Rifle/WeaponWeakpointCriticalChanceMod"
ACUITY_PISTOL = "/Lotus/Upgrades/Mods/Pistol/WeaponWeakpointCriticalChanceMod"
CRUX = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/StatusAndAmmoEfficiencyOnWeakpointHit"


class NewItemLandingTests(unittest.TestCase):
    def test_acuity_mods_admitted_and_wire_weakpoint_brackets(self) -> None:
        import app
        from wfarsenal.damage import mod_effects

        for path in (ACUITY_RIFLE, ACUITY_PISTOL):
            record = app.MANUAL_MODS_BY_PATH.get(path)
            self.assertIsNotNone(record, f"{path} must be in the manual catalog")
            effects = mod_effects(record, rank=record.get("maxRank") or 10)
            by_type = {e.upgrade_type: e for e in effects}
            self.assertIn("WEAPON_DAMAGE_WEAKPOINT", by_type)
            self.assertIn("WEAPON_CRIT_CHANCE_WEAKPOINT", by_type)
            # rank 10 = 11 steps x 0.318
            self.assertAlmostEqual(by_type["WEAPON_DAMAGE_WEAKPOINT"].value, 3.498, places=3)
            self.assertAlmostEqual(by_type["WEAPON_CRIT_CHANCE_WEAKPOINT"].value, 3.498, places=3)

            weapon = app.optimizer.resolve_record(
                app.EXPORTS["weapons"],
                "/Lotus/Weapons/Tenno/Rifle/BratonPrime"
                if "Rifle" in path else "/Lotus/Weapons/Tenno/Pistol/LatoVandal",
                kind="weapon",
            )
            weapon, _ = app.optimizer._select_fire_mode(
                weapon, 0, weapon_type="rifle" if "Rifle" in path else "pistol"
            )
            stats = app.optimizer.apply_mods(
                weapon, effects, scenario=app.optimizer._scenario("killsPerMinute")
            )
            self.assertAlmostEqual(stats.weakpoint_damage_bonus, 3.498, places=3)
            self.assertAlmostEqual(stats.weakpoint_crit_chance_bonus, 3.498, places=3)

    def test_primary_crux_arcane_admitted_with_stack_semantics(self) -> None:
        import app

        record = app.MANUAL_ARCANES_BY_PATH.get(CRUX)
        self.assertIsNotNone(record, "Primary Crux must be in the arcane catalog")
        self.assertEqual(record.get("maxRank"), 5)
        self.assertEqual(record.get("trigger", {}).get("maxStacks"), 10)
        self.assertEqual(record.get("trigger", {}).get("duration"), 10)

        # Trigger classification: weakpoint-hit conditions classify as
        # on-hit (the hit-rate formula family), not the on-kill default.
        raw = app.optimizer.resolve_record(app.EXPORTS["arcanes"], CRUX, kind="arcane")
        kind = app._manual_arcane_trigger_kind(raw)
        self.assertEqual(kind, "hit")

    def test_weakpoint_trigger_condition_text_falls_back_to_conditions(self) -> None:
        """The Crux trigger carries conditions=[OnWeakpointHitCondition] with
        conditionTag null; the state text must surface the condition so the
        trigger-source classifier sees it."""
        import app

        result = app.simulate_manual_payload({
            "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            "fireMode": 0,
            "metric": "sustainedDps",
            "mods": [],
            "arcanes": [{"path": CRUX, "rank": 5}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 170,
            "steelPath": True,
            "benchmarkTarget": {
                "enemy": app._BENCHMARK_ENEMY_PATH,
                "level": 170,
                "steelPath": True,
                "windowSeconds": 30.0,
            },
        })
        series = (result.get("benchmarkTimeline") or {}).get("triggerSeries") or []
        crux = [s for s in series if s.get("maxStacks") == 10.0]
        self.assertTrue(crux, "Primary Crux stack series must reach the timeline")
        self.assertEqual(crux[0].get("kind"), "on-hit")


if __name__ == "__main__":
    unittest.main()
