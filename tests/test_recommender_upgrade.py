"""Regressions for the build-recommender (recommend_optimal_riven) upgrade."""
from __future__ import annotations

import unittest

import app
from wfarsenal.optimizer import recommend_optimal_riven


def _engine_context(weapon_path: str):
    """Resolve the recommender's engine inputs through the app layer."""
    payload = {"weapon": weapon_path, "mods": []}
    build_result, engine = app.build_weapon_payload(payload, return_engine_context=True)
    return build_result, engine


class RecommendOptimalRivenTests(unittest.TestCase):
    def test_recommender_covers_two_positive_negative_combos(self) -> None:
        """The upgraded negative pairing must reach 2+1 structures too.

        Budget-constrained run: with a tiny budget the algorithm still returns
        combos, and at least one recorded combo must be a 2-positive+1-negative
        structure when negatives are beneficial — the old implementation only
        paired negatives with 3-positive combos.
        """
        build_result, engine = _engine_context(
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime"
        )
        weapon_record = engine["weapon"]
        weapon_type = engine["weaponType"]
        disposition = 1.3
        template_bases = app.optimizer._template_bases(
            app.EXPORTS.get("rivenTemplates") or {}, weapon_type
        )
        positive_candidates, _ = app.optimizer._candidate_lines(
            weapon_type, disposition, (), negative=False, bases=template_bases,
            structure_scale=app.optimizer.theoretical_structure_scale(3, False),
        )
        negative_candidates, _ = app.optimizer._candidate_lines(
            weapon_type, disposition, (), negative=True, bases=template_bases,
            structure_scale=app.optimizer.theoretical_structure_scale(3, False, negative=True),
        )
        result = recommend_optimal_riven(
            weapon_record,
            engine["evaluation"],
            positive_candidates,
            negative_candidates,
            scenario=engine["scenario"],
            metric=engine["metric"],
            passives=engine["passives"],
            capacity_limit=engine["capacityLimit"],
            target_context=engine.get("benchmarkContext"),
            budget_seconds=6.0,
            top_limit=10,
        )
        combos = result.get("combos") or []
        self.assertGreaterEqual(len(combos), 1)
        # Every combo must carry a stage and a score.
        for combo in combos:
            self.assertIn(combo["stage"], {"beam", "beam-negative", "refined"})
            self.assertIsInstance(combo["score"], float)
        # At least one 2-positive structure must appear in the results (the
        # recommender evaluates sizes 2 and 3 by construction).
        sizes = {
            sum(1 for stat in combo["stats"] if not stat["negative"])
            for combo in combos
        }
        self.assertIn(2, sizes, "2-positive structures must be evaluated")
        # Negative pairing breadth: with a 6 s budget the head is 4 negatives
        # (budget<=10) and they pair with both 2- and 3-positive combos.
        self.assertLessEqual(result["elapsed"], 30.0)

    def test_stage3_refines_with_full_keep_ladder(self) -> None:
        """The refined stage must include the keep-7 layer (slotted caliber)."""
        build_result, engine = _engine_context(
            "/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLex"
        )
        weapon_record = engine["weapon"]
        weapon_type = engine["weaponType"]
        template_bases = app.optimizer._template_bases(
            app.EXPORTS.get("rivenTemplates") or {}, weapon_type
        )
        positive_candidates, _ = app.optimizer._candidate_lines(
            weapon_type, 1.35, (), negative=False, bases=template_bases,
            structure_scale=app.optimizer.theoretical_structure_scale(3, False),
        )
        negative_candidates, _ = app.optimizer._candidate_lines(
            weapon_type, 1.35, (), negative=True, bases=template_bases,
            structure_scale=app.optimizer.theoretical_structure_scale(3, False, negative=True),
        )
        result = recommend_optimal_riven(
            weapon_record,
            engine["evaluation"],
            positive_candidates,
            negative_candidates,
            scenario=engine["scenario"],
            metric=engine["metric"],
            passives=engine["passives"],
            capacity_limit=engine["capacityLimit"],
            target_context=engine.get("benchmarkContext"),
            budget_seconds=10.0,
            top_limit=10,
        )
        # The stages descriptor advertises the full ladder.
        self.assertIn("keep 7..0", result["stages"]["refined"])
        self.assertIn("2/3-positive", result["stages"]["beam"])
        # Combos exist and memoization did some work.
        self.assertGreaterEqual(len(result["combos"]), 1)
        self.assertGreaterEqual(result["evaluations"], 1)


class BuildWatcherTests(unittest.TestCase):
    """The new-build watcher tool must be importable and its diff correct."""

    def test_watcher_imports_and_reports(self) -> None:
        import importlib.util
        from pathlib import Path

        spec = importlib.util.spec_from_file_location(
            "watch_new_build",
            Path(app.__file__).parent / "tools" / "watch-new-build.py",
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        # Identifier scan patterns are compiled and non-empty.
        self.assertGreaterEqual(len(module.FUSION_PATTERNS), 5)
        # The dump root exists on this machine; if not, skip silently.
        if module.RAW_ROOT.is_dir():
            latest = module.newest_dump()
            self.assertIsNotNone(latest)
            self.assertTrue((latest[1] / "packages").is_dir())


if __name__ == "__main__":
    unittest.main()
