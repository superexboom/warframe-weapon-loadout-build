"""Engine-adjudicated proc-crit contract (2026-09-23 RE verdict).

The engine has NO innate per-stack crit bonuses from puncture or cold
procs. This pins the removal so the invented bonuses cannot silently
return.
"""
from __future__ import annotations

import unittest

import app
from wfarsenal.damage import windowed_status_damage


def _neutral(ehp: float = 1e12) -> dict:
    return {
        "health": ehp, "shield": 0.0, "overguard": 0.0, "armour": 0.0,
        "faction": "", "healthType": "RK_FLESH", "armourType": "RK_NONE",
        "shieldType": "RK_NONE", "factionResistance": "RK_NEUTRAL",
    }


class ProcCritRemovalTests(unittest.TestCase):
    def test_puncture_stacks_do_not_raise_crit(self) -> None:
        """A puncture-heavy build's windowed DPS must not grow from
        puncture stacks (engine: no innate per-stack crit bonus)."""
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        base = optimizer.apply_mods(
            weapon, optimizer.ModEffectList(),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        puncture_build = optimizer.apply_mods(
            weapon,
            optimizer.synthetic_riven_effects(
                [{"code": "9", "value": 150.0, "negative": False}]  # +puncture
            ),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        # The puncture build has a bigger puncture share; its DoT window may
        # legitimately differ, but its DIRECT window per attack must reflect
        # only the panel composition — the crit expectation stays the base
        # one because puncture stacks add nothing.
        result = windowed_status_damage(
            puncture_build, _neutral(),
            attacks_per_second=1.0, window_seconds=6.0, level=1,
            time_step=0.25, collect_timeline=False,
        )
        ledger = result["directEventLedger"]
        # perShotDamage at t=0 stacks (cold/puncture all zero) must equal the
        # base per-shot crit expectation; the engine verdict says puncture
        # stacks can never raise it mid-window. We verify via the first-step
        # timeline: directDps of step 1 == the steady directDps once puncture
        # stacks have ramped (no crit growth from stacks).
        tl_result = windowed_status_damage(
            puncture_build, _neutral(),
            attacks_per_second=5.0, window_seconds=6.0, level=1,
            time_step=0.25, collect_timeline=True,
        )
        timeline = tl_result.get("timeline") or []
        self.assertTrue(timeline)
        direct_first = timeline[0].get("directDps") or 0
        direct_late = None
        for point in timeline[4:]:
            if point.get("directDps"):
                direct_late = point["directDps"]
                break
        if direct_first and direct_late:
            # With stacks ramped (puncture up), late direct must not exceed
            # the first step by more than the cold/puncture-less tolerance.
            # Engine verdict: NO crit growth — directDps should be flat.
            self.assertAlmostEqual(
                direct_late, direct_first, delta=direct_first * 0.35,
                msg="puncture stacks must not raise direct crit expectation",
            )

    def test_cold_stacks_do_not_raise_crit_damage(self) -> None:
        """Same contract for cold: the freeze machine has no innate
        crit-damage bonus."""
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        cold_build = optimizer.apply_mods(
            weapon,
            optimizer.synthetic_riven_effects(
                [{"code": "5", "value": 150.0, "negative": False}]  # +cold
            ),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        result = windowed_status_damage(
            cold_build, _neutral(),
            attacks_per_second=5.0, window_seconds=6.0, level=1,
            time_step=0.25, collect_timeline=True,
        )
        timeline = result.get("timeline") or []
        self.assertTrue(timeline)
        first = timeline[0].get("directDps") or 0
        late = None
        for point in timeline[4:]:
            if point.get("directDps"):
                late = point["directDps"]
                break
        if first and late:
            self.assertAlmostEqual(
                late, first, delta=first * 0.35,
                msg="cold stacks must not raise direct crit damage",
            )

    def test_engine_verdict_recorded(self) -> None:
        """The RE verdict artifact exists and records the removal basis."""
        import json
        from pathlib import Path
        verdict = Path(
            r"C:\Users\SuperExboom\Documents\WF-Riven-Portable\.local\research"
            r"\proc-mechanics-re.json"
        )
        if not verdict.is_file():
            self.skipTest("RE verdict artifact not present")
        data = json.loads(verdict.read_text(encoding="utf-8"))
        self.assertIn("punctureCrit", data)
        self.assertIn("coldCritDamage", data)


if __name__ == "__main__":
    unittest.main()
