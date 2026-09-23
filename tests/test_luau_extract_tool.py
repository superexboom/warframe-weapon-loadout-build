"""Regression for the Luau bytecode extraction tool (static RE path)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import app


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "luau_extract",
        Path(app.__file__).parent / "tools" / "luau-extract.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LuauExtractToolTests(unittest.TestCase):
    def test_toc_names_available(self) -> None:
        module = _load_module()
        if not module.TOC.is_file():
            self.skipTest("game cache not present on this machine")
        names = module.toc_names()
        self.assertGreater(len(names), 5000)
        # Known scripts must be present (verified earlier by hand).
        self.assertIn("BioGrenade.lua", names)
        self.assertIn("ModFusion.lua", names)

    def test_fusion_scripts_absent_in_current_build(self) -> None:
        """The stat-fusion feature is not in the client yet: no dedicated
        script beyond the legacy Endo ModFusion UI family. This pins the
        finding so the day it lands, this test tells us to look again."""
        module = _load_module()
        if not module.TOC.is_file():
            self.skipTest("game cache not present on this machine")
        names = {n.lower() for n in module.toc_names()}
        legacy_fusion = {
            "modfusion.lua",
            "fusiontreasuremanager.lua",
            "fusionornamentpickup.lua",
            "newplayertutorialmodfusion.lua",
        }
        self.assertTrue(legacy_fusion & names, "legacy Endo fusion scripts expected")
        for kw in ("rivenfusion", "statfusion", "coalescent", "ascentfusion"):
            self.assertFalse(
                any(kw in n for n in names),
                f"new fusion script family appeared in the TOC: rerun analysis!",
            )

    def test_extract_and_disassemble_bio_grenade(self) -> None:
        """End-to-end: extract the Torid grenade script and disassemble it.

        The BioGrenade bytecode exposes OnContact as its single entry point
        (animation-only per the earlier audit); the anim-rate parameter names
        live in the .lua_H header / mod JSON, not in string constants.
        """
        module = _load_module()
        if not module.TOC.is_file() or not module.DUMP.is_file():
            self.skipTest("game cache or disassembler not present")
        body = module.extract("/Lotus/Scripts/WeaponAttachments/BioGrenade.lua")
        self.assertIsNotNone(body)
        self.assertTrue(body.is_file())
        dis = module.disassemble(body)
        self.assertIsNotNone(dis)
        text = dis.read_text(encoding="utf-8")
        self.assertIn("OnContact", text)
        self.assertIn("proto 0", text)

    def test_disassemble_bonus_damage_on_next_hit(self) -> None:
        """The Double Tap script disassembles with its five known functions."""
        module = _load_module()
        if not module.TOC.is_file() or not module.DUMP.is_file():
            self.skipTest("game cache or disassembler not present")
        body = module.extract(
            "/Lotus/Upgrades/CosmeticEnhancers/Offensive/BonusDamageOnNextHit.lua"
        )
        self.assertIsNotNone(body)
        dis = module.disassemble(body)
        self.assertIsNotNone(dis)
        text = dis.read_text(encoding="utf-8")
        for fn in ("ApplyUpgrade", "UnApplyUpgrade", "OnProjectileContact",
                   "HudBuffLoop", "GetModDescriptionInfo"):
            self.assertIn(fn, text)


if __name__ == "__main__":
    unittest.main()
