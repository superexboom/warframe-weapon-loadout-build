from __future__ import annotations

import unittest

import app
from wfarsenal.combat_events import direct_fire_ledger


class ContinuousKillLedgerTests(unittest.TestCase):
    def test_one_attack_per_second_cannot_create_extra_kills(self) -> None:
        result = direct_fire_ledger(
            attacks_per_second=1.0,
            window_seconds=30.0,
            target_ehp=100.0,
            component_damage=[("direct", 1_000_000.0)],
        )
        self.assertEqual(result["attacks"], 30)
        self.assertEqual(result["kills"], 30)
        self.assertEqual(result["killsPerMinute"], 60.0)

    def test_components_from_one_attack_do_not_retarget_respawn(self) -> None:
        result = direct_fire_ledger(
            attacks_per_second=1.0,
            window_seconds=3.0,
            target_ehp=100.0,
            component_damage=[("pellet-1", 100.0), ("pellet-2", 100.0)],
        )
        self.assertEqual(result["attacks"], 3)
        self.assertEqual(result["kills"], 3)
        self.assertEqual(result["staleComponents"], 3)

    def test_step_does_not_cap_kills_or_carry_overkill(self) -> None:
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        stats = optimizer.apply_mods(
            weapon,
            optimizer.ModEffectList(),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        target = {
            "health": 1.0,
            "shield": 0.0,
            "overguard": 0.0,
            "armour": 0.0,
            "faction": "",
            "healthType": "RK_FLESH",
            "armourType": "RK_NONE",
            "shieldType": "RK_NONE",
            "factionResistance": "RK_NEUTRAL",
        }
        result = optimizer.windowed_status_damage(
            stats,
            target,
            attacks_per_second=stats.sustained_attack_rate,
            window_seconds=2.0,
            level=1,
            time_step=0.25,
            collect_timeline=False,
        )
        self.assertGreater(result["maxKillsPerStep"], 1)
        self.assertGreater(result["killsPerMinute"], 240.0)
        self.assertAlmostEqual(
            result["totalWindowDamage"],
            result["killsInWindow"] * result["targetTotalEhp"],
            delta=1e-5,
        )
        self.assertTrue(result["continuousKillEvents"])
        self.assertEqual(
            result["directEventLedger"]["status"],
            "settled-authoritative",
        )
        self.assertGreaterEqual(result["directEventLedger"]["attacks"], 1)
        # F01: the main loop now settles direct attacks as discrete events on
        # the same schedule the ledger replays; the event model version
        # reflects that (no longer a "diagnostic-only" side ledger).
        self.assertEqual(result["eventModel"], "hybrid-event-settled-v2")

    def test_real_window_path_exposes_direct_attack_ledger(self) -> None:
        optimizer = app.optimizer
        weapon = optimizer.resolve_record(
            app.EXPORTS["weapons"],
            "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
            kind="weapon",
        )
        weapon, _ = optimizer._select_fire_mode(weapon, 0, weapon_type="rifle")
        stats = optimizer.apply_mods(
            weapon,
            optimizer.ModEffectList(),
            scenario=optimizer._scenario("killsPerMinute"),
        )
        target = {
            "health": 1.0,
            "shield": 0.0,
            "overguard": 0.0,
            "armour": 0.0,
            "faction": "",
            "healthType": "RK_FLESH",
            "armourType": "RK_NONE",
            "shieldType": "RK_NONE",
            "factionResistance": "RK_NEUTRAL",
        }
        result = optimizer.windowed_status_damage(
            stats,
            target,
            attacks_per_second=1.0,
            window_seconds=30.0,
            level=1,
            time_step=0.25,
            collect_timeline=False,
        )
        ledger = result["directEventLedger"]
        self.assertEqual(ledger["attacks"], 30)
        self.assertEqual(ledger["kills"], 30)
        self.assertEqual(ledger["killsPerMinute"], 60.0)
        self.assertEqual(result["eventModel"], "hybrid-event-settled-v2")
        # F01: with status procs present the DoT channel adds damage, but the
        # direct-attack-supported kill count must stay bounded by the ledger's
        # attack count plus the DoT-supported kills (no phantom overkill).
        self.assertLessEqual(result["killEvents"], ledger["attacks"] + 60)


class ContextContractTests(unittest.TestCase):
    def test_context_hash_is_canonical(self) -> None:
        optimizer = app.optimizer
        left = {"b": 2, "a": [1, {"z": True}]}
        right = {"a": [1, {"z": True}], "b": 2}
        self.assertEqual(
            optimizer._evaluation_context_hash(left),
            optimizer._evaluation_context_hash(right),
        )

    def test_innate_elements_are_part_of_static_key(self) -> None:
        optimizer = app.optimizer
        common = {
            "enemy": "/target",
            "level": 170,
            "steelPath": True,
            "eximus": True,
            "windowSeconds": 30,
        }
        fire = optimizer._statics_cache_key(
            "/weapon",
            [{"damageType": "DT_FIRE", "value": 0.6}],
            0,
            "",
            "standard",
            1.0,
            60,
            "killsPerMinute",
            common,
        )
        toxin = optimizer._statics_cache_key(
            "/weapon",
            [{"damageType": "DT_POISON", "value": 0.6}],
            0,
            "",
            "standard",
            1.0,
            60,
            "killsPerMinute",
            common,
        )
        self.assertNotEqual(fire, toxin)

    def test_status_mod_gain_uses_status_ledger(self) -> None:
        app._MOD_GAINS_CACHE.clear()
        payload = {
            "weapon": "/Lotus/Weapons/Tenno/Pistols/PrimeLex/PrimeLex",
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 170,
            "steelPath": True,
            "mods": [
                {
                    "path": "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponStatusChanceModExpert",
                    "rank": 10,
                    "slot": 0,
                },
                {
                    "path": "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponToxinDamageModExpert",
                    "rank": 10,
                    "slot": 1,
                },
                {
                    "path": "/Lotus/Upgrades/Mods/Pistol/Expert/WeaponFireIterationsModExpert",
                    "rank": 10,
                    "slot": 2,
                },
            ],
            "candidates": [
                "/Lotus/Upgrades/Mods/Pistol/PistolStatusDamageDuoMod"
            ],
            "targetSlot": 3,
            "metric": "sustainedDps",
        }
        result = app.mod_gains_payload(payload)
        gain = result["gains"][payload["candidates"][0]]
        self.assertGreater(gain["gainPercent"], 0.0)
        self.assertGreater(gain["value"], gain["baseValue"])

    def test_double_tap_is_visible_but_fail_closed(self) -> None:
        path = "/Lotus/Upgrades/Mods/PvPMods/Rifle/MoreDamageonTripleTapRifleMod"
        self.assertIn(path, app.MANUAL_MODS_BY_PATH)
        result = app.mod_gains_payload(
            {
                "weapon": "/Lotus/Weapons/Tenno/Rifle/LatronPrime",
                "enemy": app._BENCHMARK_ENEMY_PATH,
                "mods": [],
                "candidates": [path],
            }
        )
        gain = result["gains"][path]
        self.assertIsNone(gain["gainPercent"])
        self.assertEqual(gain["reason"], "event-mechanic-unmodeled")


if __name__ == "__main__":
    unittest.main()
