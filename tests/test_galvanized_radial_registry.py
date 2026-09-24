"""Contract: the Galvanized/conditional-damage radial scope registry.

Engine verdict (two RE rounds, galvanized-radial-re.json +
galvanized-radial-whitelist.json, build 2026.09.22.16.46):
- The per-status conditional damage (UpgradeType 259) core gates exclude
  only DoT ticks.
- RADIAL application is per-weapon: the explosion entry routes through
  the weapon's impact behavior (weapon upgrade context → 259 applies)
  only when the projectile carries DealDamageThroughImpactBehavior=1
  (member +0xd99); the generic per-victim radial path reads 259 as zero.
- Whitelist ~40 player weapons (Ogris family, Penta family, glaives,
  Acceltra, ...); Torid / Akarius Prime / Kuva Bramma are blacklisted
  (radial does NOT get the bonus; direct hits do).

This test pins the sidecar registration so the discriminating data and
the simulator contract stay machine-readable.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path


SIDECAR = (
    Path(__file__).resolve().parents[1] / "data" / "weapon_mechanics_overrides.json"
)
GA_PATH = "/Lotus/Upgrades/Mods/Rifle/WeaponStatusChanceSPMod"


class GalvanizedRadialRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = json.loads(SIDECAR.read_text(encoding="utf-8"))
        cls.entry = (cls.doc.get("mods") or {}).get(GA_PATH)

    def test_registry_entry_exists(self) -> None:
        self.assertIsNotNone(
            self.entry, "the galvanized conditional-radial registry entry is missing"
        )
        self.assertEqual(self.entry.get("mechanicId"), "galvanized-conditional-radial-scope")
        self.assertEqual(self.entry.get("status"), "conditional-supported")

    def test_discriminator_fields_recorded(self) -> None:
        engine = self.entry.get("enginePath") or {}
        self.assertIn("0x140e266d0", engine.get("coreFn", ""))
        self.assertIn("0xd99", engine.get("dataFlag", ""))
        self.assertIn(
            "DealDamageThroughImpactBehavior",
            engine.get("dataFlag", ""),
            "the per-weapon data flag must be recorded",
        )
        self.assertIn("0x14148b760", engine.get("radialRouting", ""))

    def test_whitelist_and_blacklist_recorded(self) -> None:
        wl = self.entry.get("radialWhitelist") or {}
        # Whitelist mentions key weapons and the raw list location.
        note = str(wl.get("note") or "")
        for weapon in ("Ogris", "Penta", "Acceltra", "Glaive"):
            self.assertIn(weapon, note, f"whitelist note missing {weapon}")
        blacklist = wl.get("blacklistExamples") or []
        joined = " ".join(str(item) for item in blacklist)
        for weapon in ("Torid", "Akarius", "Bramma"):
            self.assertIn(weapon, joined, f"blacklist examples missing {weapon}")

    def test_simulator_contract_recorded(self) -> None:
        contract = self.entry.get("simulatorContract") or {}
        self.assertIn("dot", contract)
        self.assertIn("radial", contract)
        self.assertIn("optimizerNote", contract)
        # DoT exclusion stays pinned (engine gates DHT_DOT / EProcType).
        self.assertIn("DoT", str(contract.get("dot")))


if __name__ == "__main__":
    unittest.main()
