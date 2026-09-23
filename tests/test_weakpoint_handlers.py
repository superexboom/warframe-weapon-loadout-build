"""Weakpoint-family riven stat handlers (2026.09.22 fusion update).

Engine adjudication (weakpoint-multiplier-re.json):
- WEAPON_DAMAGE_WEAKPOINT: conditional bucket, independent multiplicative
  bracket from the part multiplier: damage x DamageAtten x (1 + bonus),
  gated on the hit's weakpoint flag. No effect on weakpoint-less targets.
- WEAPON_CRIT_CHANCE_WEAKPOINT: additive with WEAPON_CRIT_CHANCE into the
  same roll, gated on weakpoint hits.
- WEAPON_PROC_DAMAGE: same bucket as the existing status-DoT multiplier.
- New compound elements: same pre-coalesce elemental bucket.
- New factions: GAMEPLAY_FACTION_DAMAGE with Orokin/Techrot/Scaldra filters.
"""
from __future__ import annotations

import unittest

import app
from wfarsenal.damage import apply_mods, damage_against


def _weapon():
    optimizer = app.optimizer
    weapon = optimizer.resolve_record(
        app.EXPORTS["weapons"],
        "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
        kind="weapon",
    )
    weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
    return weapon


def _weakpoint_target():
    return {
        "health": 100000.0, "shield": 0.0, "overguard": 0.0, "armour": 0.0,
        "faction": "", "healthType": "RK_FLESH", "armourType": "RK_NONE",
        "shieldType": "RK_NONE", "factionResistance": "RK_NEUTRAL",
        # headshot proxy: damageAtten>1 marks weakpoint hits
        "hitProxies": [
            {"part": "head", "damageAtten": 2.0, "criticalMultiplier": 2.0},
        ],
    }


def _flat_target():
    return {
        "health": 100000.0, "shield": 0.0, "overguard": 0.0, "armour": 0.0,
        "faction": "", "healthType": "RK_FLESH", "armourType": "RK_NONE",
        "shieldType": "RK_NONE", "factionResistance": "RK_NEUTRAL",
    }


class WeakpointHandlerTests(unittest.TestCase):
    def test_damage_weakpoint_scales_only_weakpoint_hits(self) -> None:
        weapon = _weapon()
        scenario = app.optimizer._scenario("killsPerMinute")
        base = apply_mods(weapon, app.optimizer.ModEffectList(), scenario=scenario)
        boosted = apply_mods(
            weapon,
            app.optimizer.synthetic_riven_effects(
                [{"code": "__weakpoint_damage__", "value": 0.0}]  # placeholder
            ),
            scenario=scenario,
        ) if False else None
        # Direct ModEffect route (the riven rules table gains the codes later;
        # verify the handler via synthetic upgrade-type effects).
        from wfarsenal.damage import ModEffect

        wp_effects = app.optimizer.ModEffectList([
            ModEffect(
                upgrade_type="WEAPON_DAMAGE_WEAKPOINT",
                operation="STACKING_MULTIPLY",
                value=1.0,  # +100% on weakpoint hits
            ),
        ])
        boosted = apply_mods(weapon, wp_effects, scenario=scenario)
        self.assertAlmostEqual(boosted.weakpoint_damage_bonus, 1.0)

        flat = damage_against(boosted, _flat_target(), level=1)
        weak = damage_against(boosted, _weakpoint_target(), hit_location="head", level=1)
        base_flat = damage_against(base, _flat_target(), level=1)
        base_weak = damage_against(base, _weakpoint_target(), hit_location="head", level=1)
        # No weakpoint: no gain.
        self.assertAlmostEqual(
            flat["perShot"] / base_flat["perShot"], 1.0, delta=1e-6
        )
        # Weakpoint target: +100% multiplicative on top of the part multiplier.
        self.assertAlmostEqual(
            weak["perShot"] / base_weak["perShot"], 2.0, delta=1e-6
        )

    def test_crit_chance_weakpoint_adds_on_weakpoint_hits(self) -> None:
        weapon = _weapon()
        scenario = app.optimizer._scenario("killsPerMinute")
        from wfarsenal.damage import ModEffect

        wp_effects = app.optimizer.ModEffectList([
            ModEffect(
                upgrade_type="WEAPON_CRIT_CHANCE_WEAKPOINT",
                operation="ADD",
                value=0.5,
            ),
        ])
        boosted = apply_mods(weapon, wp_effects, scenario=scenario)
        self.assertAlmostEqual(boosted.weakpoint_crit_chance_bonus, 0.5)

        weak = damage_against(boosted, _weakpoint_target(), hit_location="head", level=1)
        base = apply_mods(weapon, app.optimizer.ModEffectList(), scenario=scenario)
        base_weak = damage_against(base, _weakpoint_target(), hit_location="head", level=1)
        # Braton crit 0.30 -> 0.80 on weakpoint hits: crit-avg must rise.
        self.assertGreater(weak["perShot"], base_weak["perShot"] * 1.01)
        # Flat target: unchanged.
        flat = damage_against(boosted, _flat_target(), level=1)
        base_flat = damage_against(base, _flat_target(), level=1)
        self.assertAlmostEqual(
            flat["perShot"] / base_flat["perShot"], 1.0, delta=1e-6
        )

    def test_proc_damage_uses_existing_bucket(self) -> None:
        weapon = _weapon()
        scenario = app.optimizer._scenario("killsPerMinute")
        from wfarsenal.damage import ModEffect

        effects = app.optimizer.ModEffectList([
            ModEffect(
                upgrade_type="WEAPON_PROC_DAMAGE",
                operation="STACKING_MULTIPLY",
                value=0.9,
            ),
        ])
        boosted = apply_mods(weapon, effects, scenario=scenario)
        self.assertAlmostEqual(boosted.proc_damage_multiplier, 1.9)

    def test_faction_damage_new_filters(self) -> None:
        weapon = _weapon()
        scenario = app.optimizer._scenario("killsPerMinute")
        from wfarsenal.damage import ModEffect

        effects = app.optimizer.ModEffectList([
            ModEffect(
                upgrade_type="GAMEPLAY_FACTION_DAMAGE",
                operation="STACKING_MULTIPLY",
                value=0.45,
                symbol_filter="Orokin",
            ),
        ])
        boosted = apply_mods(weapon, effects, scenario=scenario)
        self.assertAlmostEqual(
            boosted.faction_damage_multipliers.get("Orokin"), 1.45
        )


if __name__ == "__main__":
    unittest.main()
