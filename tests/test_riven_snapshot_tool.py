"""Regression for the riven-snapshot collector (companion-API path)."""
from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

import app


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "collect_riven_snapshot",
        Path(app.__file__).parent / "tools" / "collect-riven-snapshot.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RivenSnapshotTests(unittest.TestCase):
    def test_extract_rivens_and_fusion_items(self) -> None:
        module = _load_module()
        inventory = {
            "RawUpgrades": [
                {
                    "ItemType": "/Lotus/Upgrades/Mods/Rifle/RandomModRare",
                    "UpgradeFingerprint": json.dumps(
                        {"buffs": [{"code": "D", "value": 200.5}], "curses": []}
                    ),
                    "ItemId": {"$oid": "abc123"},
                },
                {
                    "ItemType": "/Lotus/Upgrades/Mods/Rifle/WeaponDamageMod",
                    "ItemCount": 4,
                },
            ],
            "Upgrades": [],
            "MiscItems": [
                {"ItemType": "/Lotus/Types/Items/MiscItems/RivenFragment", "ItemCount": 7},
                {"ItemType": "/Lotus/Types/Items/MiscItems/ArgonCrystal", "ItemCount": 2},
            ],
            "FusionPoints": 1000,
        }
        snapshot = module.extract(inventory)
        self.assertEqual(snapshot["rivenCount"], 1)
        riven = snapshot["rivens"][0]
        self.assertEqual(riven["itemId"], "abc123")
        self.assertEqual(riven["fingerprint"]["buffs"][0]["value"], 200.5)
        self.assertFalse(riven["equipped"])
        # Fusion-relevant items picked up (RivenFragment), irrelevant ones not.
        self.assertEqual(len(snapshot["fusionItems"]), 1)
        self.assertIn("RivenFragment", snapshot["fusionItems"][0]["ItemType"])
        # FusionPoints is a legacy Endo key; it is surfaced but distinguished.
        self.assertIn("FusionPoints", snapshot["fusionKeys"])

    def test_riven_regex_matches_families(self) -> None:
        module = _load_module()
        for path in (
            "/Lotus/Upgrades/Mods/Rifle/RandomModRare",
            "/Lotus/Upgrades/Mods/Pistol/RandomModRare",
            "/Lotus/Upgrades/Mods/Melee/RandomModRare",
        ):
            self.assertIsNotNone(module.RIVEN_RE.search(path), path)
        for path in (
            "/Lotus/Upgrades/Mods/Rifle/WeaponDamageMod",
            "/Lotus/Upgrades/Mods/Warframe/AvatarHealthMaxMod",
        ):
            self.assertIsNone(module.RIVEN_RE.search(path), path)


if __name__ == "__main__":
    unittest.main()
