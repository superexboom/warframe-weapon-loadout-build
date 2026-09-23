"""Regressions for the Incarnon SubUpgrade pipeline fix (2026-09-23).

The raw evolution files attach conditional sub-perks via SubUpgrades
(e.g. BoltorEvoTier1B -> BoltorEvoTier1BSubMod with the reload-stacking
damage + ammo efficiency). The compact export dropped them entirely:
the UI showed incomplete descriptions (the Boltor 2-2 wrong-description
report) and the simulator never saw the sub-perk effects.

These tests validate the extract-side fix and the simulator-side gate.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

RAW = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\wf-arsenal\data\raw"
    r"\2026.08.19.11.06\packages"
)


class SubUpgradeDataTests(unittest.TestCase):
    def test_boltor_tier1b_has_sub_upgrade_reference(self) -> None:
        """The raw Boltor Evo Tier1B carries a SubUpgrades reference."""
        data = json.loads(
            (RAW / "Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions"
             / "BoltorEvoTier1B.json").read_text(encoding="utf-8")
        )
        subs = data.get("SubUpgrades")
        self.assertIsNotNone(subs)
        self.assertIn("BoltorEvoTier1BSubMod", subs)

    def test_submod_carries_conditional_metadata(self) -> None:
        """The SubMod file has UpgradeChance/Duration/MaxConditionalStacks —
        the gate metadata the simulator needs to treat it as conditional."""
        data = json.loads(
            (RAW / "Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions"
             / "BoltorEvoTier1BSubMod.json").read_text(encoding="utf-8")
        )
        # The reload-stacking damage sub-perk and the ammo-efficiency perk.
        types = {u.get("UpgradeType") for u in data.get("Upgrades") or ()}
        self.assertIn("WEAPON_DAMAGE_AMOUNT", types)
        self.assertIn("WEAPON_AMMO_CONSUME_RATE", types)
        for key in ("UpgradeChance", "UpgradeDuration", "MaxConditionalStacks"):
            self.assertIn(key, data, f"SubMod missing gate metadata {key}")

    def test_extract_branch_includes_sub_upgrade_effects(self) -> None:
        """_build_incarnon_branch now resolves SubUpgrades and emits the
        sub-perk effects with isSubUpgrade + gate metadata."""
        from wfarsenal.extract import _build_incarnon_branch
        from wfarsenal.packages import PackageIndex

        index = PackageIndex(RAW)
        powerup = {"Upgrades": ["/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/BoltorEvoTier1B"]}
        branch = _build_incarnon_branch(index, "/Lotus/Weapons/Tenno/LongGuns/PrimeBoltor/PrimeBoltor", 2, 2, powerup)
        effects = branch.get("effects") or []
        sub_effects = [e for e in effects if e.get("isSubUpgrade")]
        self.assertTrue(
            sub_effects,
            "SubUpgrade effects must be extracted (BoltorEvoTier1B -> SubMod)",
        )
        # The reload-stacking damage sub-perk carries the gate metadata.
        damage_subs = [
            e for e in sub_effects
            if e.get("upgradeType") == "WEAPON_DAMAGE_AMOUNT"
        ]
        self.assertTrue(damage_subs)
        for eff in damage_subs:
            self.assertIn("UpgradeChance", eff)
            self.assertIn("UpgradeDuration", eff)


class SubUpgradeSimulatorGateTests(unittest.TestCase):
    def test_branch_effects_excludes_conditional_sub_upgrades(self) -> None:
        """_branch_effects must NOT treat SubUpgrade perks as unconditional:
        they are event-gated (reload-stacking, chance-based) and would
        inflate the panel if常驻."""
        from wfarsenal.optimizer import _branch_effects

        branch = {
            "id": "2-2",
            "path": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/BoltorEvoTier1B",
            "effects": [
                {  # main perk: flat damage — unconditional, kept
                    "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                    "operation": "ADD_BASE",
                    "valuePerRank": 165,
                    "damageType": "DT_ANY",
                },
                {  # gated sub perk: reload-stacking damage — conditional, excluded
                    "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                    "operation": "ADD_BASE",
                    "valuePerRank": 2,
                    "damageType": "DT_ANY",
                    "isSubUpgrade": True,
                    "UpgradeChance": 1.0,
                    "UpgradeDuration": 5.0,
                    "MaxConditionalStacks": 3,
                    "sourcePath": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/BoltorEvoTier1BSubMod",
                },
                {  # unconditional sub perk (no gate) — kept as常驻
                    "upgradeType": "WEAPON_SPREAD",
                    "operation": "STACKING_MULTIPLY",
                    "valuePerRank": -0.4,
                    "damageType": "DT_ANY",
                    "isSubUpgrade": True,
                    "sourcePath": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/BoltorEvoTier1ASubMod",
                },
            ],
        }
        effects, unsupported = _branch_effects(branch)
        # Main perk + unconditional sub survive.
        types = [e.upgrade_type for e in effects]
        self.assertEqual(len(effects), 2)
        self.assertIn("WEAPON_DAMAGE_AMOUNT", types)
        self.assertIn("WEAPON_SPREAD", types)
        # The gated sub perk is fail-closed with a diagnostic.
        self.assertTrue(
            any("sub-upgrade-conditional-excluded" in u for u in unsupported),
            f"sub-upgrade exclusion diagnostic missing: {unsupported}",
        )

    def test_branch_trigger_specs_merge_submod_effects(self) -> None:
        """_branch_trigger_specs produces one trigger source per SubMod
        (damage + ammo-efficiency share one stack), with damagePerStack."""
        from wfarsenal.optimizer import _branch_trigger_specs

        branch = {
            "id": "2-2",
            "effects": [
                {
                    "upgradeType": "WEAPON_DAMAGE_AMOUNT",
                    "operation": "ADD_BASE",
                    "valuePerRank": 2,
                    "isSubUpgrade": True,
                    "UpgradeChance": 1.0,
                    "UpgradeDuration": 5.0,
                    "MaxConditionalStacks": 3,
                    "sourcePath": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/PrimeBoltorEvoTier1BSubMod",
                },
                {
                    "upgradeType": "WEAPON_AMMO_CONSUME_RATE",
                    "operation": "STACKING_MULTIPLY",
                    "valuePerRank": -0.2,
                    "isSubUpgrade": True,
                    "UpgradeChance": 1.0,
                    "UpgradeDuration": 5.0,
                    "MaxConditionalStacks": 3,
                    "sourcePath": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/PrimeBoltorEvoTier1BSubMod",
                },
                {  # unconditional sub — no trigger
                    "upgradeType": "WEAPON_SPREAD",
                    "operation": "STACKING_MULTIPLY",
                    "valuePerRank": -0.4,
                    "isSubUpgrade": True,
                    "sourcePath": "/Lotus/Weapons/Tenno/Rifle/BoltorIncarnonEvolutions/BoltorEvoTier1ASubMod",
                },
            ],
        }
        specs = _branch_trigger_specs(branch)
        self.assertEqual(len(specs), 1, "one SubMod = one trigger source")
        spec = specs[0]
        self.assertEqual(spec["kind"], "on-hit")
        self.assertEqual(spec["maxStacks"], 3.0)
        self.assertEqual(spec["duration"], 5.0)
        self.assertAlmostEqual(spec["damagePerStack"], 2.0)
        self.assertIn("灵化", spec["label"])

    def test_incarnon_card_carries_trigger_specs(self) -> None:
        """_incarnon_card attaches the merged trigger specs to the card."""
        import app
        from wfarsenal import optimizer as opt

        weapon = opt.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/LongGuns/PrimeBoltor/PrimeBoltor",
            kind="weapon",
        )
        card, choices, unsupported, _policy = opt._incarnon_card(
            weapon,
            {"tier2": "2-2"},
            scenario=opt._scenario("killsPerMinute"),
            metric="killsPerMinute",
            policy=app.EXPORTS.get("incarnonDefaults"),
            build_label=app.EXPORTS["buildLabel"],
        )
        self.assertIsNotNone(card)
        specs = list(getattr(card, "trigger_specs", ()) or ())
        self.assertTrue(specs, "Boltor 2-2 must carry its SubMod trigger spec")
        self.assertEqual(len(specs), 1)
        self.assertAlmostEqual(specs[0]["damagePerStack"], 2.0)

    def test_ui_description_renders_sub_upgrade_gate(self) -> None:
        """_incarnon_effect_text annotates conditional sub-perks."""
        import app

        text = app._incarnon_effect_text({
            "upgradeType": "WEAPON_DAMAGE_AMOUNT",
            "operation": "ADD_BASE",
            "valuePerRank": 2,
            "isSubUpgrade": True,
            "UpgradeChance": 1.0,
            "UpgradeDuration": 2.0,
            "MaxConditionalStacks": 20,
        })
        self.assertIn("条件", text)
        self.assertIn("不计入", text)


if __name__ == "__main__":
    unittest.main()
