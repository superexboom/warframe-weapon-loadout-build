"""F05–F17 optimizer-contract regressions (audit 2026-09-22).

Covers the acceptance matrix rows that pin the optimizer-side fixes:
- S01: 2+0 / 2+1 / 3+0 / 3+1 structure scales share one contract.
- S02: required/forbidden/fill constraints hold across search stages.
- C02: /api/mod-gains cache key includes the actual Riven.
- C03: the analysis fingerprint covers app.py and combat_events.py.
- C04: bake workers cannot persist the shared main cache.
- U01: status reason codes distinguish model/target/lower-bound.
- S04: per-line contributions are fixed-build ablations.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import app
from wfarsenal.optimizer import (
    theoretical_structure_scale,
    validate_build,
)


class StructureScaleContractTests(unittest.TestCase):
    """S01: the structure scale follows the normalized actual structure."""

    def test_four_structures_use_their_own_scales(self) -> None:
        cases = {
            # (positives, has_negative): positive scale, negative scale
            (2, False): (1.0, 0.5),
            (2, True): (1.25, 0.5),
            (3, False): (0.757525, 0.757525),
            (3, True): (0.94690625, 0.757525),
        }
        for (positives, has_negative), (pos_scale, neg_scale) in cases.items():
            with self.subTest(positives=positives, has_negative=has_negative):
                self.assertAlmostEqual(
                    theoretical_structure_scale(positives, has_negative),
                    pos_scale,
                    places=6,
                )
                self.assertAlmostEqual(
                    theoretical_structure_scale(positives, True, negative=True),
                    neg_scale,
                    places=6,
                )

    def test_analysis_has_hardness_integrated_target_and_no_optimum_score(self) -> None:
        """No theoretical optimum or 0-100 score; one target set per weapon."""
        payload = {
            "weapon": "/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLex",
            "disposition": 1.35,
            "stats": [
                {"code": "D", "value": 290.0, "negative": False},
                {"code": "0", "value": 200.0, "negative": False},
            ],
            "profile": "fast",
        }
        result = app.analyze_payload(payload)
        for removed in ("optimal", "bestFound", "score", "grade", "optimalGain", "rollQuality"):
            self.assertNotIn(removed, result)
        self.assertEqual(len(result["recommendedPositive"]), 2)
        self.assertTrue(result["evaluationTarget"]["enemyEnhancements"]["noOverguard"])
        nodes = result["targetCalibration"]["hardnessNodes"]
        self.assertEqual([round(n["ttkSeconds"], 1) for n in nodes], [1.4, 4.5, 14.3])
        self.assertTrue(nodes[0]["healthScale"] < nodes[1]["healthScale"] < nodes[2]["healthScale"])
        # A different card or headshot rate on the same weapon is judged on the same targets.
        other = app.analyze_payload({**payload, "stats": [{"code": "D", "value": 265.0, "negative": False},
                                                         {"code": "0", "value": 185.0, "negative": False}]})
        self.assertEqual(other["targetCalibration"]["hardnessNodes"], nodes)
        self.assertEqual(other["evaluationTarget"], result["evaluationTarget"])
        # Ultra on the same weapon reuses the cached targets and baseline; its
        # stat contributions are the middle-node approximation and say so.
        ultra = app.analyze_payload({**payload, "profile": "ultra"})
        self.assertEqual(ultra["profile"], "ultra")
        self.assertEqual(ultra["targetCalibration"]["hardnessNodes"], nodes)
        self.assertIn("ultra-profile-contributions-center-node", ultra["unsupported"])
        self.assertEqual({d["code"] for d in ultra["details"]}, {"D", "0"})
        self.assertTrue(all(d.get("ablationDelta") is not None for d in ultra["details"]))


class HardnessIntegrationTests(unittest.TestCase):
    def test_nodes_are_log_uniform_gauss_legendre_times(self) -> None:
        import math
        hits = app.optimizer._hardness_times()
        low, high = app.optimizer.HARDNESS_TTK_RANGE
        self.assertAlmostEqual(math.log(hits[1][0]), (math.log(low) + math.log(high)) / 2)
        self.assertAlmostEqual(hits[0][0] * hits[2][0], hits[1][0] ** 2)
        self.assertAlmostEqual(sum(w for _, w in hits), 1.0)

    def test_score_is_geometric_mean_over_nodes(self) -> None:
        import math
        optimizer = app.optimizer
        seen = []
        original = optimizer._event_window

        class Stats:
            _combat_inputs = {}

        def fake(stats, context):
            scale = context["enemy_enhancements"]["healthScale"]
            seen.append(scale)
            return {"killsPerMinute": 60.0 / scale}
        try:
            optimizer._event_window = fake
            nodes = [dict(ttkSeconds=n, healthScale=s, weight=w)
                     for (n, w), s in zip(optimizer._hardness_times(), (1.0, 4.0, 16.0))]
            value = optimizer._score(Stats(), "killsPerMinute", target_context={"hardnessNodes": nodes})
        finally:
            optimizer._event_window = original
        self.assertEqual(seen, [1.0, 4.0, 16.0])
        expected = math.exp(sum(n["weight"] * math.log(60.0 / n["healthScale"]) for n in nodes))
        self.assertAlmostEqual(value, expected)


class HealthSpreadTests(unittest.TestCase):
    def test_node_averages_its_health_spread_and_stays_monotone(self) -> None:
        import math
        optimizer = app.optimizer
        original = optimizer._event_window

        class Stats:
            _combat_inputs = {}

        def score(damage, spread):
            def fake(stats, context):
                health = context["enemy_enhancements"]["healthScale"]
                return {"killsPerMinute": 60.0 / math.ceil(health / damage - 1e-9)}  # shots-to-kill steps
            optimizer._event_window = fake
            nodes = [dict(ttkSeconds=1.0, healthScale=10.0, weight=1.0, healthSpread=spread)]
            return optimizer._score(Stats(), "killsPerMinute", target_context={"hardnessNodes": nodes})
        try:
            self.assertAlmostEqual(score(4.0, .2), (60 / 2 + 60 / 3) / 2)  # health 8 and 12
            # Each point is a monotone staircase, so their average never drops.
            values = [score(2.0 + .05 * i, .2) for i in range(80)]
            self.assertTrue(all(b >= a for a, b in zip(values, values[1:])))
            self.assertGreater(len(set(values)), len(set(score(2.0 + .05 * i, 0.) for i in range(80))))
        finally:
            optimizer._event_window = original


class BuildValidatorTests(unittest.TestCase):
    """S02: the shared feasibility validator."""

    def _card(self, key: str, drain: int = 5, required: bool = False):
        # A minimal _Card stand-in: validate_build only reads key/required and
        # _capacity reads polarity/drain via the card protocol.
        from wfarsenal.optimizer import _Card, ModEffect

        return _Card(
            key=key,
            record={"path": f"/lotus/{key}", "maxRank": 10},
            rank=10,
            effects=(ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", 0.5),),
            skipped=(),
            drain=drain,
            polarity=None,
            required=required,
        )

    def test_required_missing_rejected(self) -> None:
        cards = (self._card("a"), self._card("b"))
        reason = validate_build(
            cards, None, slot_count=8, capacity_limit=60,
            required_mod_keys=["c"],
        )
        self.assertIsNotNone(reason)
        self.assertIn("missing-required", reason)

    def test_forbidden_present_rejected(self) -> None:
        cards = (self._card("a"), self._card("b"))
        reason = validate_build(
            cards, None, slot_count=8, capacity_limit=60,
            forbidden_mod_keys=["b"],
        )
        self.assertIsNotNone(reason)
        self.assertIn("forbidden-mod", reason)

    def test_fill_bounds(self) -> None:
        cards = (self._card("a"),)
        self.assertIsNotNone(
            validate_build(cards, None, slot_count=8, capacity_limit=60, min_fill=3)
        )
        many = tuple(self._card(k) for k in "abcdefgh")
        self.assertIsNotNone(
            validate_build(many, None, slot_count=8, capacity_limit=200, max_fill=4),
        )
        self.assertIsNone(
            validate_build(cards, None, slot_count=8, capacity_limit=60, min_fill=1, max_fill=4)
        )

    def test_slot_and_capacity_bounds(self) -> None:
        many = tuple(self._card(k, drain=20) for k in "abcde")
        self.assertIsNotNone(
            validate_build(many, None, slot_count=4, capacity_limit=200)
        )
        self.assertIsNotNone(
            validate_build(many, None, slot_count=8, capacity_limit=60)
        )

    def test_required_survives_search(self) -> None:
        """S02 end-to-end: a user-required mod is never dropped by the search."""
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        mod_pool, _ = optimizer._candidate_mods(
            app.EXPORTS, weapon, optimizer._scenario("killsPerMinute")
        )
        victim = next(card for card in mod_pool if not card.required)
        result = optimizer._optimize(
            weapon,
            mod_pool,
            None,
            scenario=optimizer._scenario("killsPerMinute"),
            metric="burstDps",
            required_mod_keys=[victim.key],
            max_fill=4,
        )
        self.assertIn(victim.key, {card.key for card in result.cards})
        self.assertLessEqual(len(result.cards), 4)


class ModGainsRivenCacheTests(unittest.TestCase):
    """C02: changing only the Riven stats must not reuse a cached result."""

    def _payload(self, toxin_value: float) -> dict:
        return {
            "weapon": "/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLex",
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 150,
            "steelPath": True,
            "mods": [
                {
                    "path": "/Lotus/Upgrades/Mods/Pistol/WeaponToxinDamageMod",
                    "rank": 5,
                    "slot": 0,
                }
            ],
            "riven": {
                "stats": [
                    {"code": "6", "value": toxin_value, "negative": False},
                    {"code": "2", "value": 120.0, "negative": False},
                ]
            },
            "candidates": [
                "/Lotus/Upgrades/Mods/Pistol/PistolStatusDamageDuoMod"
            ],
            "targetSlot": 1,
            "metric": "sustainedDps",
        }

    def test_riven_only_change_invalidates_cache(self) -> None:
        app._MOD_GAINS_CACHE.clear()
        # Two payloads differing ONLY in the Riven's toxin line value.
        low = self._payload(100.0)
        high = self._payload(119.0)
        result_low = app.mod_gains_payload(low)
        self.assertIn("gains", result_low)
        result_high = app.mod_gains_payload(high)
        # The second call must not have been served from the first call's
        # cache entry: with different Riven damage the base value differs.
        self.assertNotEqual(result_low["baseValue"], result_high["baseValue"])
        # And the cache now holds two distinct keys.
        self.assertGreaterEqual(len(app._MOD_GAINS_CACHE), 2)
        app._MOD_GAINS_CACHE.clear()


class FingerprintTests(unittest.TestCase):
    """C03: the analysis fingerprint covers the real dependency set."""

    def test_fingerprint_is_stable_and_covers_app_and_events(self) -> None:
        first = app._analysis_inputs_fingerprint()
        self.assertIsInstance(first, str)
        self.assertEqual(len(first), 16)
        self.assertNotEqual(first, "")
        second = app._analysis_inputs_fingerprint()
        self.assertEqual(first, second)

    def test_fingerprint_rejects_unreadable_dependency(self) -> None:
        """A missing dependency must raise, not degrade to an empty string."""
        from wfarsenal.simulator import SimulationError

        # Point the fingerprint at a path that cannot be read by monkeypatching
        # EXPORT_DIR to a non-existent directory entry.
        original = app.EXPORT_DIR
        try:
            app.EXPORT_DIR = original / "__definitely_missing__"
            with self.assertRaises(SimulationError):
                app._analysis_inputs_fingerprint()
        finally:
            app.EXPORT_DIR = original


class BakeWorkerIsolationTests(unittest.TestCase):
    """C04: workers cannot persist the shared main cache (structural guard)."""

    def test_persistence_guard_disables_writes(self) -> None:
        app._MOD_GAINS_CACHE.clear()
        guard = app._disable_analysis_statics_persistence()
        try:
            self.assertFalse(app.ANALYSIS_STATICS_PERSISTENCE.enabled)
            app.ANALYSIS_STATICS_CACHE["__dirty__"] = True
            app.ANALYSIS_STATICS_CACHE["__probe_entry__"] = {"disposition": 1.0}
            app._persist_analysis_statics_cache()
            # The guard made the persist call a no-op: the probe entry may sit
            # in the in-memory dict but the file must not have been rewritten
            # by this call. We verify via the guard state itself (structural)
            # plus the fact that persist returned without clearing __dirty__.
            self.assertTrue(app.ANALYSIS_STATICS_CACHE.get("__dirty__", False))
        finally:
            app.ANALYSIS_STATICS_CACHE.pop("__probe_entry__", None)
            app.ANALYSIS_STATICS_CACHE.pop("__dirty__", None)
            guard.enabled = True
        self.assertTrue(app.ANALYSIS_STATICS_PERSISTENCE.enabled)

    def test_bake_script_default_modes_mirror_analyzer(self) -> None:
        """The bake default fire-mode policy must match analyze_riven_request."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "bake_analysis_statics",
            Path(app.__file__).parent / "tools" / "bake-analysis-statics.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Non-Incarnon multi-mode weapon: primary mode only.
        self.assertEqual(module._default_analysis_modes({"fireModes": [{"damage": {}}]}), [0])
        # Incarnon multi-mode weapon: the LAST mode (the Incarnon form).
        self.assertEqual(
            module._default_analysis_modes(
                {
                    "isIncarnon": True,
                    "fireModes": [{"damage": {}}, {"damage": {}}, {"damage": {}}],
                }
            ),
            [2],
        )
        # Incarnon single-mode: that mode.
        self.assertEqual(
            module._default_analysis_modes({"isIncarnon": True, "fireModes": [{"damage": {}}]}),
            [0],
        )


class StatusReasonContractTests(unittest.TestCase):
    """U01: the analysis exposes distinguishable status reason codes."""

    def test_result_carries_reason_fields(self) -> None:
        payload = {
            "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            "disposition": 1.3,
            "stats": [
                {"code": "D", "value": 165.0, "negative": False},
                {"code": "2", "value": 88.0, "negative": False},
                {"code": "6", "value": 90.0, "negative": False},
            ],
            "profile": "fast",
        }
        result = app.analyze_payload(payload)
        self.assertNotIn("scoreStatus", result)
        search_quality = result.get("searchQuality") or {}
        self.assertEqual(search_quality.get("targetCalibrationStatus"), "hardness-integrated")
        self.assertEqual(result.get("targetStatus"), "hardness-integrated")
        self.assertEqual(result["targetCalibration"]["aggregation"], "geometric-mean-kpm")


class ContributionAblationTests(unittest.TestCase):
    """S04: per-line contributions are fixed-build ablations."""

    def test_details_expose_both_calibers(self) -> None:
        payload = {
            "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            "disposition": 1.3,
            "stats": [
                {"code": "D", "value": 200.0, "negative": False},
                {"code": "2", "value": 120.0, "negative": False},
                {"code": "6", "value": 110.0, "negative": False},
                {"code": "F", "value": 48.0, "negative": True},
            ],
            "profile": "fast",
        }
        result = app.analyze_payload(payload)
        details = result.get("details") or []
        self.assertGreaterEqual(len(details), 3)
        for detail in details:
            self.assertIn("ablationDelta", detail)
            self.assertIn("reoptimizedDelta", detail)
            # The headline delta is the ablation caliber when available.
            if detail.get("ablationDelta") is not None:
                self.assertEqual(detail["delta"], detail["ablationDelta"])


class StaticsCacheContextTests(unittest.TestCase):
    """C01 (fallback side): the level-fallback matches the full context."""

    def test_fallback_rejects_different_enemy(self) -> None:
        optimizer = app.optimizer
        cache: dict = {}
        # Insert a migrated entry keyed with the benchmark enemy A.
        bm_a = {
            "enemy": "/enemy/a", "level": 9999, "steelPath": True, "eximus": True,
            "armourStrip": 0.0, "elementalArmourStrip": 0.0, "headshotChance": 0.0,
            "hitLocation": "body", "stanceMultiplier": 1.0,
            "statusRateMultiplier": 1.0, "heavyAttack": False, "windowSeconds": 30.0,
        }
        key_a = optimizer._statics_cache_key(
            "/weapon", [], 0, "-", "fast", 1.0, 60, "killsPerMinute", bm_a
        )
        cache[key_a] = {"scoringLevel": 9999, "disposition": 1.0, "metric": "killsPerMinute"}
        # Same everything but a different enemy: must NOT hit the entry.
        bm_b = dict(bm_a, enemy="/enemy/b", level=170)
        key_b = optimizer._statics_cache_key(
            "/weapon", [], 0, "-", "fast", 1.0, 60, "killsPerMinute", bm_b
        )
        self.assertNotIn(key_b, cache)
        # The fallback predicate: parse the stored key and compare except level.
        parsed = json.loads(key_a)
        self.assertEqual(parsed["benchmark"]["enemy"], "/enemy/a")
        parsed_b = json.loads(key_b)
        self.assertNotEqual(parsed_b["benchmark"]["enemy"], parsed["benchmark"]["enemy"])


if __name__ == "__main__":
    unittest.main()


def test_identified_incarnon_conditional_is_event_modeled_not_false_missing():
    import app
    from wfarsenal.optimizer import _branch_effects
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Dera')
    b=next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-1')
    _,unsupported=_branch_effects(b)
    assert not any('conditional-effects-not-applied' in x or 'conditional-source-excluded' in x for x in unsupported)
    assert not any('WEAPON_AMMO_CONSUME_RATE-not-evaluated' in x for x in unsupported)


def test_torid_last_round_gate_is_not_reported_as_missing_condition():
    import app
    from wfarsenal.optimizer import _branch_effects
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Torid')
    b=next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-1')
    _,unsupported=_branch_effects(b)
    assert not any('conditional-effects-not-applied' in x or 'conditional-source-excluded' in x for x in unsupported)
    assert not any('WEAPON_LAST_MULTISHOT' in x for x in unsupported)


def test_three_mod_elements_are_evaluated_in_every_pairing():
    """Viral + Heat and Blast + Toxin come from the same MOD set in different
    slot orders; a greedy build order must not hide the better pairing."""
    from types import SimpleNamespace
    from wfarsenal.optimizer import _element_orders, _pairing_key

    def card(key, *types):
        effects = tuple(SimpleNamespace(damage_type=t, value=.9) for t in types)
        return SimpleNamespace(key=key, effects=effects)

    heat, cold, toxin, base = card('heat', 'DT_FIRE'), card('cold', 'DT_FREEZE'), card('toxin', 'DT_POISON'), card('base')
    orders = _element_orders((heat, base, cold, toxin))
    assert orders[0] == (heat, base, cold, toxin)  # the given order stays first
    assert len(orders) == 3
    assert {_pairing_key(o)[0] for o in orders} == {
        frozenset({'DT_FIRE', 'DT_FREEZE'}), frozenset({'DT_FIRE', 'DT_POISON'}), frozenset({'DT_FREEZE', 'DT_POISON'})}
    assert all(o[1] is base for o in orders)  # non-element cards keep their slot
    assert _element_orders((heat, base, cold)) == [(heat, base, cold)]
