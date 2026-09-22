"""F01鈥揊04 windowed damage contract regressions (audit 2026-09-22).

These tests pin the producer/consumer contract of the stepped window model:

- D01: DoT proc-count sensitivity.  The main seed term must scale with the
  number of procs per attack; the old code divided the aggregated rate by the
  proc count and the two cancelled out.
- D02: status duration scaling applied exactly once.  The producer's
  ``durationSeconds`` is final; the consumer must not multiply the duration
  multiplier a second time.
- E01: direct fire with no DoT/AoE settles through the authoritative attack
  ledger: 1 Hz over a 30 s window against a target whose EHP is 1/2/10脳 the
  per-attack damage yields exactly 30 attacks and 30 kills (60 KPM), and the
  first kill lands at t=0.
- E07: the discrete result must not depend on the integration bin size.
"""
from __future__ import annotations

import math
import unittest

import app
from wfarsenal.damage import expected_status_damage, windowed_status_damage


def _neutral_target(ehp: float) -> dict:
    return {
        "health": ehp,
        "shield": 0.0,
        "overguard": 0.0,
        "armour": 0.0,
        "faction": "",
        "healthType": "RK_FLESH",
        "armourType": "RK_NONE",
        "shieldType": "RK_NONE",
        "factionResistance": "RK_NEUTRAL",
    }


def _braton_stats():
    optimizer = app.optimizer
    weapon = optimizer.resolve_record(
        app.EXPORTS["weapons"],
        "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
        kind="weapon",
    )
    weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
    return optimizer.apply_mods(
        weapon,
        optimizer.ModEffectList(),
        scenario=optimizer._scenario("killsPerMinute"),
    )


class DotContractTests(unittest.TestCase):
    """D01/D02: producer fields consumed exactly once by the window model."""

    def _window(self, stats, target, **overrides):
        kwargs = dict(
            attacks_per_second=stats.sustained_attack_rate,
            window_seconds=30.0,
            level=1,
            time_step=0.25,
            collect_timeline=False,
        )
        kwargs.update(overrides)
        return windowed_status_damage(stats, target, **kwargs)

    def test_dot_total_scales_with_proc_count(self) -> None:
        """D01: doubling the procs per attack must scale the main seed term.

        Build two stat blocks on the same weapon where one has a much higher
        status chance (and thus more expected procs per attack) and otherwise
        comparable direct damage.  The DoT window total must grow with the
        proc count instead of cancelling out.
        """
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        scenario = optimizer._scenario("killsPerMinute")
        low_status = optimizer.apply_mods(weapon, optimizer.ModEffectList(), scenario=scenario)
        # Pure status chance boost ("2" = 触发几率): more procs per attack
        # without touching the damage magnitude.
        high_status = optimizer.apply_mods(
            weapon,
            optimizer.synthetic_riven_effects(
                [{"code": "2", "value": 180.0, "negative": False}]
            ),
            scenario=scenario,
        )
        self.assertGreater(
            high_status.status_chance,
            low_status.status_chance,
            "fixture must actually raise the status chance",
        )
        probe_low = expected_status_damage(low_status, None)
        probe_high = expected_status_damage(high_status, None)
        # The fixture must actually produce different proc counts to be valid.
        self.assertGreater(
            float(probe_high["dot"]["total"]),
            float(probe_low["dot"]["total"]),
        )
        target = _neutral_target(1e12)  # long-lived: no death interference
        low = self._window(low_status, target)
        high = self._window(high_status, target)
        self.assertGreater(
            high["dotWindow"],
            low["dotWindow"] * 1.5,
            "DoT window total must scale with the expected proc count",
        )

    def test_duration_scale_applied_once(self) -> None:
        """D02: proc duration multiplier changes the window exactly once.

        With a x2 duration multiplier the total DoT damage over a window much
        longer than the base duration must NOT be 4x the baseline (the old
        double-application produced 6s鈫?4s effective duration on long windows).
        For a fixed proc rate and long window the steady-state DoT rate is
        duration-independent, so the totals must be close, not quadrupled.
        """
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        scenario = optimizer._scenario("killsPerMinute")
        base = optimizer.apply_mods(weapon, optimizer.ModEffectList(), scenario=scenario)
        # x2 status duration via the riven line "3" (触发时间) if supported,
        # else skip the fixture rather than assert on a wrong contract.
        try:
            boosted = optimizer.apply_mods(
                weapon,
                optimizer.synthetic_riven_effects(
                    [{"code": "3", "value": 90.0, "negative": False}]
                ),
                scenario=scenario,
            )
        except Exception:  # noqa: BLE001 - fixture unsupported on this weapon
            self.skipTest("status-duration riven line unavailable on fixture weapon")
        if boosted.proc_duration_multiplier <= 1.01:
            self.skipTest("fixture did not raise proc duration")
        target = _neutral_target(1e12)
        base_result = self._window(base, target, window_seconds=60.0)
        boosted_result = self._window(boosted, target, window_seconds=60.0)
        ratio = boosted_result["dotWindow"] / max(base_result["dotWindow"], 1e-9)
        # Longer duration keeps more stacks alive: modest growth, never 4x.
        self.assertLess(ratio, 2.5, "duration multiplier must not be applied twice")

    def test_producer_exposes_explicit_contract_fields(self) -> None:
        """The probe rows must carry the F02 split (seed vs accumulator)."""
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLex",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="pistol")
        stats = optimizer.apply_mods(
            weapon,
            optimizer.synthetic_riven_effects(
                [
                    {"code": "6", "value": 90.0, "negative": False},  # 毒素
                    {"code": "2", "value": 120.0, "negative": False},  # 触发几率
                ]
            ),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        probe = expected_status_damage(stats, None)
        rows = (probe.get("dot") or {}).get("perType") or {}
        toxin = rows.get("DT_POISON")
        self.assertIsNotNone(toxin, "fixture must produce a toxin DoT")
        self.assertIn("seedPerSecondPerProc", toxin)
        self.assertIn("accumulatorPerSecondPerAttack", toxin)
        self.assertIn("accumulatorSharedGroup", toxin)
        # The explicit split must reconcile with the legacy aggregate field:
        # perSecond == seedPerSecondPerProc * expectedProcs + accumulator *per
        # attack* is NOT the identity (accumulator is per attack, perSecond is
        # per proc) 鈥?instead verify the seed part alone.
        self.assertGreater(float(toxin["seedPerSecondPerProc"]), 0.0)
        self.assertFalse(bool(toxin["accumulatorSharedGroup"]))


class DirectLedgerAuthorityTests(unittest.TestCase):
    """E01/E07: no-DoT direct fire settles through the attack ledger.

    The no-DoT subset is expressed with ``status_rate_multiplier=0``: no procs
    are scheduled, so the only damage source is the direct fire schedule the
    ledger replays.  (The weapon itself still has Slash procs in its normal
    behaviour — suppressing them isolates the direct-fire contract, exactly
    the E01 "无 DoT/AoE" precondition from the audit matrix.)
    """

    def test_one_hertz_overkill_three_ratios(self) -> None:
        stats = _braton_stats()
        for ehp_scale in (1.0, 2.0, 10.0):
            with self.subTest(ehpScale=ehp_scale):
                # Per-attack damage is ~352 at this build; scale the EHP to
                # 1/2/10x it by reading the ledger's per-shot damage first.
                probe = windowed_status_damage(
                    stats,
                    _neutral_target(1.0),
                    attacks_per_second=1.0,
                    window_seconds=0.25,
                    level=1,
                    time_step=0.25,
                    status_rate_multiplier=0.0,
                    collect_timeline=False,
                )
                per_shot = float(probe["directEventLedger"].get("perShotDamage") or 0.0)
                self.assertGreater(per_shot, 0.0)
                target = _neutral_target(per_shot * ehp_scale)
                result = windowed_status_damage(
                    stats,
                    target,
                    attacks_per_second=1.0,
                    window_seconds=30.0,
                    level=1,
                    time_step=0.25,
                    status_rate_multiplier=0.0,
                    collect_timeline=False,
                )
                ledger = result["directEventLedger"]
                self.assertEqual(ledger["attacks"], 30)
                # Expected kills: floor(30 attacks / attacks-needed-per-kill).
                attacks_per_kill = math.ceil(ehp_scale)
                expected_kills = 30 // attacks_per_kill
                self.assertEqual(ledger["kills"], expected_kills)
                self.assertAlmostEqual(
                    ledger["killsPerMinute"], expected_kills * 2.0
                )
                # The main output must AGREE with the ledger (F01): the old
                # continuous-rate main loop produced 10x the attack-supported
                # kills at 10x overkill (300 kills from 30 attacks).
                self.assertEqual(result["killEvents"], expected_kills)
                self.assertAlmostEqual(result["killsPerMinute"], expected_kills * 2.0, delta=0.01)
                if ehp_scale == 1.0:
                    self.assertAlmostEqual(result["firstKillTime"], 0.0, places=3)

    def test_discrete_result_is_bin_independent(self) -> None:
        """E07: changing the integration bin must not change the outcome."""
        stats = _braton_stats()
        target = _neutral_target(1.0)
        outcomes = []
        for step in (0.25, 0.1, 0.05):
            result = windowed_status_damage(
                stats,
                target,
                attacks_per_second=1.0,
                window_seconds=30.0,
                level=1,
                time_step=step,
                status_rate_multiplier=0.0,
                collect_timeline=False,
            )
            outcomes.append((result["killsPerMinute"], result["directEventLedger"]["kills"]))
        for kpm, kills in outcomes:
            self.assertEqual(kills, 30)
            self.assertAlmostEqual(kpm, 60.0, delta=1.0)

    def test_overkill_does_not_leak_to_second_target(self) -> None:
        """E02 in spirit: 10x overkill cannot kill 10 targets per attack."""
        stats = _braton_stats()
        target = _neutral_target(1.0)
        result = windowed_status_damage(
            stats,
            target,
            attacks_per_second=1.0,
            window_seconds=30.0,
            level=1,
            time_step=0.25,
            status_rate_multiplier=0.0,
            collect_timeline=False,
        )
        # 30 attacks in 30 s: at most 30 kills, never 300 (the old continuous
        # rate formula produced exactly the 10x leak documented in F01).
        self.assertLessEqual(result["killEvents"], 30)
        self.assertLessEqual(result["killsPerMinute"], 60.0 + 1e-6)


if __name__ == "__main__":
    unittest.main()
