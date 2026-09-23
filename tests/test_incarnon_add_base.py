"""Regression: the Incarnon evolution ADD_BASE damage bonus must add flat
base damage, not multiply the scale (the 385x panel explosion)."""
from __future__ import annotations

import unittest

import app


class IncarnonAddBaseTests(unittest.TestCase):
    def test_vectis_incarnon_panel_stays_sane(self) -> None:
        """The Prime Vectis Incarnon mode with its Tier1B evolution (+150
        base damage ADD_BASE) must stay in the hundreds, not tens of
        thousands."""
        optimizer = app.optimizer
        weapon_record = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/LongGuns/PrimeVectis/PrimeVectisRifle",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(
            weapon_record, 1, weapon_type="rifle"
        )
        # The default incarnon evolution card set (includes Tier1B +150).
        incarnon_card, _choices, _unsupported, _policy = optimizer._incarnon_card(
            weapon, None,
            scenario=optimizer._scenario("killsPerMinute"),
            metric="killsPerMinute",
            policy=app.EXPORTS.get("incarnonDefaults"),
            build_label=app.EXPORTS["buildLabel"],
        )
        stats = optimizer.apply_mods(
            weapon,
            optimizer._effects([incarnon_card], optimizer._scenario("killsPerMinute")),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        # Base 150 + 150 flat = 300; sanity bound well below the 57,780
        # explosion and above the raw 150.
        self.assertLess(stats.total_damage, 2000)
        self.assertGreater(stats.total_damage, 250)
        # The damage scale path: with no other damage mods the scale is 1.0,
        # so the panel equals base + flat = 300 (distributed over DT_FREEZE).
        self.assertAlmostEqual(stats.total_damage, 300.0, delta=30.0)

    def test_serration_still_scales_add_base_pool(self) -> None:
        """A percentage damage mod (Serration) multiplies the flat-augmented
        base: (150 + 150) x 2.65 = 795."""
        optimizer = app.optimizer
        weapon_record = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/LongGuns/PrimeVectis/PrimeVectisRifle",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(
            weapon_record, 1, weapon_type="rifle"
        )
        incarnon_card, _a, _b, _c = optimizer._incarnon_card(
            weapon, None,
            scenario=optimizer._scenario("killsPerMinute"),
            metric="killsPerMinute",
            policy=app.EXPORTS.get("incarnonDefaults"),
            build_label=app.EXPORTS["buildLabel"],
        )
        serration = app.MANUAL_MODS_BY_PATH.get(
            "/Lotus/Upgrades/Mods/Rifle/WeaponDamageAmountMod"
        )
        from wfarsenal.damage import mod_effects
        effects = optimizer._effects(
            [incarnon_card], optimizer._scenario("killsPerMinute")
        )
        effects.extend(mod_effects(serration, rank=10))
        stats = optimizer.apply_mods(
            weapon, effects, scenario=optimizer._scenario("killsPerMinute")
        )
        # 300 x (1 + 1.65) = 795
        self.assertAlmostEqual(stats.total_damage, 795.0, delta=60.0)


if __name__ == "__main__":
    unittest.main()
