"""End-to-end verification suite for:
1. Operator Focus 3.0+ (50 standard + 25 Tauron nodes) combat bridge & Amp-only trap isolation.
2. Squad / External Buffs overhaul (`POST_COALESCE` infusions, Electric Shield 6x/2x CD, Nidus Parasitic Link multiplicative total Ability Strength, Brightbonnet + Arbucep 200%, Nova Speedva/Slowva).
3. 16 Defense Map Nuke setups & Exalted/Pseudo-Exalted bridges (`/api/warframe/calculate`).
4. 3D Arena Steel Path Defense, `objective` anchor, `hybrid_nuke` / `ability_only` Nuke Director, Arbitration Drone ability immunity, and neutral `weapon_only` determinism.
"""

from __future__ import annotations

import pytest

import app
from wfarsenal.arena import World


def _weapon_by_en(name_en: str) -> dict:
    target = name_en.strip().casefold()
    for w in app.EXPORTS["weapons"]:
        if str(w.get("nameEn") or "").strip().casefold() == target:
            return w
    raise KeyError(f"Weapon not found: {name_en}")


def _mod_by_en(name_en: str) -> dict:
    target = name_en.strip().casefold()
    for m in app.EXPORTS["mods"]:
        if str(m.get("nameEn") or "").strip().casefold() == target:
            return m
    raise KeyError(f"Mod not found: {name_en}")


def _frame_by_en(name_en: str) -> dict:
    target = name_en.strip().casefold()
    for rows_key in ("warframes", "warframeForms"):
        for f in app.WARFRAME_CATALOG.get(rows_key) or ():
            if str(f.get("nameEn") or "").strip().casefold() == target:
                return f
    raise KeyError(f"Warframe not found: {name_en}")


def _wf_mod_by_en(name_en: str) -> dict:
    target = name_en.strip().casefold()
    for m in app.WARFRAME_CATALOG.get("mods") or ():
        if str(m.get("nameEn") or "").strip().casefold() == target:
            return m
    raise KeyError(f"Warframe mod not found: {name_en}")


def _full_school_preset(school_id: str, *, include_tauron: bool = False) -> dict:
    cat = app.operator_catalog_payload()
    school = next(s for s in cat["schools"] if s["id"] == school_id)
    nodes_cfg = {
        n["id"]: {"unlocked": True, "rank": n["maxRank"], "enabled": True, "unbound": bool(n.get("isWayBound"))}
        for n in school["nodes"]
    }
    if include_tauron:
        for tn in school.get("ultimateBranchNodes") or ():
            nodes_cfg[tn["id"]] = {"unlocked": True, "rank": tn["maxRank"], "enabled": True}
    return {
        "activeSchool": school_id,
        "schools": {school_id: {"schoolUnlocked": True, "nodes": nodes_cfg}},
        "unboundWayBounds": [n["id"] for n in school["nodes"] if n.get("isWayBound")],
    }


def test_operator_focus_modes_ips_and_amp_trap_isolation():
    braton = _weapon_by_en("Braton Prime")
    ignis = _weapon_by_en("Ignis Wraith")

    base_braton = app.simulate_manual_payload(
        {"weapon": braton["path"], "fireMode": 0, "mods": [], "enemy": app._BENCHMARK_ENEMY_PATH, "level": 100}
    )
    mad_preset = _full_school_preset("madurai", include_tauron=True)

    # 1. Passive mode on IPS weapon: Phoenix Talons (+30% IPS) applies, Void Strike (conditional) does NOT
    passive_braton = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorLink": {**mad_preset, "enabled": True, "triggerMode": "passive"},
        }
    )
    assert passive_braton["moddedStats"]["totalDamage"] == pytest.approx(
        base_braton["moddedStats"]["totalDamage"] * 1.30, rel=1e-3
    )

    # 2. Pure elemental weapon (Ignis Wraith has 0 IPS): Phoenix Talons adds 0 damage, Contamination Wave blocked!
    base_ignis = app.simulate_manual_payload(
        {"weapon": ignis["path"], "fireMode": 0, "mods": [], "enemy": app._BENCHMARK_ENEMY_PATH, "level": 100}
    )
    passive_ignis = app.simulate_manual_payload(
        {
            "weapon": ignis["path"],
            "fireMode": 0,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorLink": {**mad_preset, "enabled": True, "triggerMode": "passive"},
        }
    )
    assert passive_ignis["moddedStats"]["totalDamage"] == pytest.approx(base_ignis["moddedStats"]["totalDamage"], rel=1e-5)

    # 3. Peak mode activates Void Strike (+1000% base damage) -> massive jump over passive!
    peak_ignis = app.simulate_manual_payload(
        {
            "weapon": ignis["path"],
            "fireMode": 0,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorLink": {**mad_preset, "enabled": True, "triggerMode": "peak", "enableTauronStrike": True},
        }
    )
    assert peak_ignis["moddedStats"]["totalDamage"] > base_ignis["moddedStats"]["totalDamage"] * 10.5

    # 4. Naramon heavy preconditions are strictly gated behind enableNaramonPreconditions
    kronen = _weapon_by_en("Kronen Prime")
    nar_preset = _full_school_preset("naramon")
    nar_off = app.simulate_manual_payload(
        {
            "weapon": kronen["path"],
            "fireMode": 0,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorLink": {**nar_preset, "enabled": True, "triggerMode": "peak", "enableNaramonPreconditions": False},
        }
    )
    nar_on = app.simulate_manual_payload(
        {
            "weapon": kronen["path"],
            "fireMode": 0,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorLink": {**nar_preset, "enabled": True, "triggerMode": "peak", "enableNaramonPreconditions": True},
        }
    )
    assert nar_on["moddedStats"]["critChance"] > nar_off["moddedStats"]["critChance"] + 0.10


def test_squad_buffs_post_coalesce_electric_shield_and_parasitic_link_strength():
    braton = _weapon_by_en("Braton Prime")
    hellfire = _mod_by_en("Hellfire")

    # 1. Nourish POST_COALESCE fix: Hellfire (DT_FIRE) + Nourish (DT_VIRAL) must NOT coalesce into DT_GAS!
    sim_nourish = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": hellfire["path"], "rank": hellfire["maxRank"], "slot": 0}],
            "externalBuffs": [{"id": "nourish", "strength": 2.0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
        }
    )
    dtypes = sim_nourish["moddedStats"]["damageTypes"]
    assert dtypes.get("DT_FIRE", 0.0) > 0.0
    assert dtypes.get("DT_VIRAL", 0.0) > 0.0
    assert dtypes.get("DT_GAS", 0.0) == 0.0

    # 2. Volt Electric Shield: 6 shields stack +300% electricity, but Crit Damage multiplies by 2.0x ONCE!
    sim_0_shield = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [],
            "externalBuffs": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
        }
    )
    sim_1_shield = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [],
            "externalBuffs": [{"id": "electric-shield", "count": 1}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
        }
    )
    sim_6_shields = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [],
            "externalBuffs": [{"id": "electric-shield", "count": 6}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
        }
    )
    expected_cd = sim_0_shield["moddedStats"]["critMultiplier"] * 2.0
    assert sim_1_shield["moddedStats"]["critMultiplier"] == pytest.approx(expected_cd, rel=1e-5)
    assert sim_6_shields["moddedStats"]["critMultiplier"] == pytest.approx(expected_cd, rel=1e-5)  # Still 2x, NOT 2^6!
    assert sim_6_shields["moddedStats"]["damageTypes"]["DT_ELECTRICITY"] == pytest.approx(
        sim_1_shield["moddedStats"]["damageTypes"]["DT_ELECTRICITY"] * 6.0, rel=1e-4
    )

    # 3. Nidus Parasitic Link multiplies TOTAL Warframe Ability Strength: (100% + 99% Blind Rage + 44% Transient = 243%) * 1.75!
    mirage = _frame_by_en("Mirage Prime")
    blind_rage = _wf_mod_by_en("Blind Rage")
    transient = _wf_mod_by_en("Transient Fortitude")
    wf_base = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "normalMods": [
                {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 0},
                {"id": transient["id"], "rank": transient["maxRank"], "slot": 1},
            ],
        }
    )
    base_str = wf_base["finalPanel"]["abilityStrength"]  # 1 + 0.99 + 0.55 = 2.54
    wf_linked = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "normalMods": [
                {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 0},
                {"id": transient["id"], "rank": transient["maxRank"], "slot": 1},
            ],
            "externalBuffs": [
                {"id": "peaceful-provocation", "strength": 2.5},  # +80% additive first!
                {"id": "parasitic-link", "strength": 3.0},  # x1.75 total multiplicative after additive!
            ],
        }
    )
    expected_str = (base_str + 0.80) * 1.75
    assert wf_linked["finalPanel"]["abilityStrength"] == pytest.approx(expected_str, rel=1e-3)


def test_defense_nuke_previews_brightbonnet_arbucep_and_prism_guard():
    # 1. Mirage Prime + Prism Guard repair mod + Brightbonnet Helminth + Arbucep 200%
    mirage = _frame_by_en("Mirage Prime")
    prism_guard = _wf_mod_by_en("Prism Guard")
    res_mirage = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "normalMods": [{"id": prism_guard["id"], "rank": prism_guard["maxRank"], "slot": 0}],
            "helminthReplacement": {
                "slot": 1,
                "abilityId": "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility",
            },
            "arbucepEmpowered": True,
        }
    )
    assert res_mirage["defenseNuke"]["supported"] is True
    assert res_mirage["defenseNuke"]["setupId"] == "mirage_prism"
    assert "棱镜护卫" in res_mirage["defenseNuke"]["titleZh"]
    # Self Brightbonnet (20% Helminth) * 200% Arbucep = +40% non-recursive Ability Strength -> 1.40!
    assert res_mirage["finalPanel"]["abilityStrength"] == pytest.approx(1.40, rel=1e-3)
    assert len(res_mirage["abilityRanges"]) >= 2

    # 2. Check flagship setups across Gara, Mesa, Equinox Day, Dante, Sevagoth, Nokko
    expected_setups = [
        ("Gara Prime", "gara_shatter_storm"),
        ("Mesa Prime", "mesa_peacemaker"),
        ("Dante", "dante_tragedy"),
        ("Sevagoth Prime", "sevagoth_sow_reap"),
        ("Nokko", "nokko_sporespring"),
    ]
    for fname, expected_id in expected_setups:
        f = _frame_by_en(fname)
        calc = app.warframe_calculate_payload({"frameId": f["id"]})
        assert calc["defenseNuke"]["supported"] is True
        assert calc["defenseNuke"]["setupId"] == expected_id
        assert calc["defenseNuke"]["normalDefenseWave"]["estimatedWaveClearSec"] > 0
        assert calc["defenseNuke"]["steelPathDefenseWave"]["estimatedWaveClearSec"] > 0

    # 3. Roar double-dip verification on Dante Tragedy Slash DoT
    dante = _frame_by_en("Dante")
    dante_no_roar = app.warframe_calculate_payload({"frameId": dante["id"]})["defenseNuke"]
    dante_roar = app.warframe_calculate_payload(
        {"frameId": dante["id"], "externalBuffs": [{"id": "roar", "strength": 2.0}]}  # +100% Roar -> 2x direct, 4x DoT!
    )["defenseNuke"]
    # Tragedy condenses Slash DoTs, so total damage scales closer to 4x than 2x!
    assert dante_roar["totalDamagePerCombo"] > dante_no_roar["totalDamagePerCombo"] * 3.2


def test_arena_defense_nuke_steel_path_objective_and_drone_immunity():
    braton = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    gara = _frame_by_en("Gara Prime")
    stretch = _wf_mod_by_en("Stretch")
    overextended = _wf_mod_by_en("Overextended")
    blind_rage = _wf_mod_by_en("Blind Rage")

    cat = app.arena_catalog_payload()
    def_spec = next(
        s["id"]
        for s in cat["enemySpecs"]
        if "corpus-ship-defense" in (s.get("mapIds") or ()) and 0 in (s.get("tiers") or ())
    )

    # 1. Neutral weapon_only determinism check
    base_payload = {
        "loadout": {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 60,
        },
        "scenario": {
            "mapId": "corpus-ship-defense",
            "spawnProfile": "custom",
            "enemySpec": "single",
            "mode": "time",
            "seconds": 8.0,
            "enemies": 8,
            "seed": 20261125,
        },
    }
    res_a = World(app._arena_context(base_payload)).run()
    res_b = World(app._arena_context(base_payload)).run()
    assert res_a["stats"]["eventHash"] == res_b["stats"]["eventHash"]
    assert "abilityKills" not in res_a["stats"]

    # 2. Steel Path Defense + Objective Anchor + Gara 4->1 Hybrid Nuke
    wf_link = {
        "enabled": True,
        "frameId": gara["id"],
        "configName": "A",
        "config": {
            "normalMods": [
                {"id": stretch["id"], "rank": stretch["maxRank"], "slot": 0},
                {"id": overextended["id"], "rank": overextended["maxRank"], "slot": 1},
                {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 2},
            ],
            "helminthReplacement": {
                "slot": 2,
                "abilityId": "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility",
            },
        },
        "arbucepEmpowered": True,
    }
    nuke_payload = {
        "loadout": {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "warframeLink": wf_link,
            "operatorLink": {**_full_school_preset("zenurik"), "enabled": True, "triggerMode": "cycle"},
        },
        "scenario": {
            "mapId": "corpus-ship-defense",
            "spawnProfile": "defense",
            "enemySpec": def_spec,
            "steelPath": True,
            "combatStyle": "hybrid_nuke",
            "movement": "objective",
            "arbucepEmpowered": True,
            "mode": "time",
            "seconds": 25.0,
            "level": 130,
            "seed": 20261125,
        },
    }
    ctx_nuke = app._arena_context(nuke_payload)
    assert ctx_nuke["common_options"]["steel_path"] is True
    assert ctx_nuke["scenario"]["squadSize"] == 4
    res_nuke = World(ctx_nuke).run()
    assert res_nuke["stats"]["playerTravelSeconds"] == 0.0
    assert res_nuke["stats"]["abilityKills"] > 0
    assert len(res_nuke["visuals"]["warframe"]["abilityRanges"]) >= 2
    assert len(res_nuke["visuals"]["warframe"]["nukePulses"]) > 0

    # 3. Pure ability_only mode fires 0 weapon shots
    pure_payload = {
        **nuke_payload,
        "scenario": {**nuke_payload["scenario"], "combatStyle": "ability_only", "seconds": 15.0},
    }
    res_pure = World(app._arena_context(pure_payload)).run()
    assert res_pure["stats"]["shots"] == 0
    assert res_pure["stats"]["abilityKills"] > 0

    # 4. Arbitration Defense Drone Immunity: Drones can NEVER die to ability-direct or ability-dot!
    arb_payload = {
        **nuke_payload,
        "scenario": {
            **nuke_payload["scenario"],
            "spawnProfile": "arbitration",
            "combatStyle": "hybrid_nuke",
            "seconds": 25.0,
        },
    }
    res_arb = World(app._arena_context(arb_payload)).run()
    for actor_tape in res_arb["replay"]["actors"]:
        if actor_tape.get("type") == "drone" and actor_tape.get("deathSource"):
            assert actor_tape["deathSource"] not in ("ability-direct", "ability-dot")


def test_optimal_high_ground_vantage_and_mirage_legerdemain_gem_loop():
    from wfarsenal.arena_scene import load_scene

    # 1. Auto-optimal reachable minimal-occlusion high-ground vantage check (zero runtime metric pollution!)
    for map_id, min_elev in [("corpus-ship-defense", 1.0), ("grineer-galleon-defense", 4.0)]:
        sc = load_scene(map_id).with_door_sight("open")
        sc.reset_runtime()
        vp = sc.select_optimal_vantage(enemy_profile="enemy-gap", max_horizontal_radius=20.0, prefer_high_ground=True)
        assert vp["autoSelected"] is True
        assert vp["elevationGainM"] >= min_elev
        assert vp["visibilityRatio"] > vp["objectiveVisibilityRatio"] * 1.45
        # Must not pollute runtime metrics/caches
        assert sc.metrics == {"rays": 0, "blocked": 0, "pathSearches": 0}
        # API endpoint check (`auto: True`)
        api_vp = app.arena_standing_point_payload({"mapId": map_id, "auto": True, "npcShortGap": True})
        assert api_vp["face"] == vp["face"]
        assert api_vp["autoSelected"] is True

    # 2. Mirage Explosive Legerdemain (`爆炸戏法`):
    #    - Preview marks ignoresLoS == False (gem static cover LoS)
    #    - In 3D Arena: weapon kills bootstrap eligible drops -> Mirage casts `2` to convert into 60s gems ->
    #      gems persist across Wave 1 -> Wave 2, refresh when needed, and detonate with static cover LoS!
    mirage = _frame_by_en("Mirage Prime")
    legerdemain = _wf_mod_by_en("Explosive Legerdemain")
    stretch = _wf_mod_by_en("Stretch")
    overextended = _wf_mod_by_en("Overextended")
    blind_rage = _wf_mod_by_en("Blind Rage")

    calc_leger = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "normalMods": [
                {"id": legerdemain["id"], "rank": legerdemain["maxRank"], "slot": 0},
                {"id": stretch["id"], "rank": stretch["maxRank"], "slot": 1},
                {"id": overextended["id"], "rank": overextended["maxRank"], "slot": 2},
                {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 3},
            ],
        }
    )
    assert calc_leger["defenseNuke"]["setupId"] == "mirage_legerdemain"
    assert calc_leger["defenseNuke"]["ignoresLoS"] is False

    ignis = _weapon_by_en("Ignis Wraith")
    serration = _mod_by_en("Serration")
    cat = app.arena_catalog_payload()
    def_spec = next(
        s["id"]
        for s in cat["enemySpecs"]
        if "grineer-galleon-defense" in (s.get("mapIds") or ()) and 0 in (s.get("tiers") or ())
    )

    leger_payload = {
        "loadout": {
            "weapon": ignis["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["id"],
                "configName": "A",
                "config": {
                    "normalMods": [
                        {"id": legerdemain["id"], "rank": legerdemain["maxRank"], "slot": 0},
                        {"id": stretch["id"], "rank": stretch["maxRank"], "slot": 1},
                        {"id": overextended["id"], "rank": overextended["maxRank"], "slot": 2},
                        {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 3},
                    ],
                    "helminthReplacement": {
                        "slot": 3,
                        "abilityId": "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility",
                    },
                },
                "arbucepEmpowered": True,
            },
        },
        "scenario": {
            "mapId": "grineer-galleon-defense",
            "spawnProfile": "defense",
            "enemySpec": def_spec,
            "combatStyle": "hybrid_nuke",
            "movement": "fixed",  # fixedPosition omitted -> auto-selects optimal reachable high ground!
            "arbucepEmpowered": True,
            "mode": "waves",
            "waves": 2,
            "waveWait": 3.0,
            "seconds": 180.0,
            "level": 40,
            "seed": 20261125,
        },
    }
    res_leger = World(app._arena_context(leger_payload)).run()
    vp_used = res_leger["stats"].get("vantagePoint")
    assert vp_used is not None and vp_used["autoSelected"] is True
    assert vp_used["elevationGainM"] >= 4.0
    nuke_sum = res_leger["visuals"]["warframe"]["nukeSummary"]
    assert nuke_sum["setupId"] == "mirage_legerdemain"
    assert nuke_sum["pickupsDropped"] > 0
    assert nuke_sum["legerdemainGemsConverted"] > 0
    assert nuke_sum["legerdemainGemsDetonated"] > 0
    assert res_leger["stats"]["shots"] > 0  # Weapon bootstrapped first drops & cleaned stragglers!

    # 3. Gyre 3+4 kill-extension verification: casts 3 & 4 once, then extends on kills without timer-spamming!
    gyre = _frame_by_en("Gyre")
    braton = _weapon_by_en("Braton Prime")
    streamline = _wf_mod_by_en("Streamline")
    gyre_payload = {
        "loadout": {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "warframeLink": {
                "enabled": True,
                "frameId": gyre["id"],
                "configName": "A",
                "config": {
                    "normalMods": [
                        {"id": stretch["id"], "rank": stretch["maxRank"], "slot": 0},
                        {"id": blind_rage["id"], "rank": blind_rage["maxRank"], "slot": 1},
                        {"id": streamline["id"], "rank": streamline["maxRank"], "slot": 2},
                    ],
                },
            },
            "operatorLink": {**_full_school_preset("zenurik"), "enabled": True, "triggerMode": "cycle"},
        },
        "scenario": {
            "mapId": "corpus-ship-defense",
            "spawnProfile": "custom",
            "enemySpec": "single",
            "droneEvery": 0,
            "combatStyle": "hybrid_nuke",
            "movement": "objective",
            "mode": "time",
            "seconds": 25.0,
            "enemies": 16,
            "level": 25,
            "seed": 20261125,
        },
    }
    res_gyre = World(app._arena_context(gyre_payload)).run()
    gyre_sum = res_gyre["visuals"]["warframe"]["nukeSummary"]
    assert gyre_sum["setupId"] == "gyre_rotorswell"
    assert gyre_sum["gyreKillExtensions"] > 0
    assert gyre_sum["castsExecuted"] <= 4  # Casts 3 & 4 once and extends via kills instead of spamming!


def test_mirage_dual_routes_clone_mini_jewels_and_augment_gate():
    mirage = _frame_by_en("Mirage Prime")
    legerdemain = _wf_mod_by_en("Explosive Legerdemain")
    stretch = _wf_mod_by_en("Stretch")
    braton = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")

    # 1. Mirage exposes BOTH routes (`mirage_legerdemain` and `mirage_prism`) in `availableSetups`
    base_calc = app.warframe_calculate_payload({"frameId": mirage["id"]})
    nuke_base = base_calc["defenseNuke"]
    setup_ids = [r["setupId"] for r in nuke_base["availableSetups"]]
    assert "mirage_legerdemain" in setup_ids
    assert "mirage_prism" in setup_ids
    assert nuke_base["hasMultipleSetups"] is True

    # 2. Explicitly selecting `mirage_legerdemain` WITHOUT `Explosive Legerdemain` equipped:
    #    - Switches to `mirage_legerdemain`
    #    - Flags `hasLegerdemainAugment == False` and `hasHallOfMirrorsSynergy == True`
    #    - Emits a `warn` buildCheck about missing `爆炸戏法` and does NOT claim 40m pickup conversion!
    sleight_no_aug = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "nukeSetupId": "mirage_legerdemain",
            "normalMods": [{"id": stretch["id"], "rank": stretch["maxRank"], "slot": 0}],
        }
    )["defenseNuke"]
    assert sleight_no_aug["setupId"] == "mirage_legerdemain"
    assert sleight_no_aug["hasLegerdemainAugment"] is False
    assert sleight_no_aug["hasHallOfMirrorsSynergy"] is True
    assert any(c["status"] == "warn" and "爆炸戏法" in c["textZh"] for c in sleight_no_aug["buildChecks"])
    assert "拾取转化" not in sleight_no_aug["radiusSummaryZh"]
    assert "镜厅小宝石" in sleight_no_aug["radiusSummaryZh"]

    # 3. Explicitly selecting `mirage_prism` even when `Explosive Legerdemain` IS equipped honors user's choice!
    forced_prism = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "nukeSetupId": "mirage_prism",
            "normalMods": [{"id": legerdemain["id"], "rank": legerdemain["maxRank"], "slot": 0}],
        }
    )["defenseNuke"]
    assert forced_prism["setupId"] == "mirage_prism"

    # 4. Helminth slot validation: replacing Slot 4 (`slot: 3`) disables `mirage_prism` in `availableSetups`!
    helm_slot4 = app.warframe_calculate_payload(
        {
            "frameId": mirage["id"],
            "helminthReplacement": {
                "slot": 3,
                "abilityId": "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility",
            },
        }
    )["defenseNuke"]
    prism_row = next(r for r in helm_slot4["availableSetups"] if r["setupId"] == "mirage_prism")
    assert prism_row["available"] is False
    assert "4" in prism_row["unavailableReasonZh"]
    assert helm_slot4["setupId"] == "mirage_legerdemain"

    # 5. 3D Arena Mirage `1 Hall of Mirrors + 2 Sleight of Hand` synergy:
    #    - With Slot 1 intact & NO `Explosive Legerdemain`: spawns 1 Main Jewel + 4 Clone Mini-Jewels (50% effectiveness), 0 pickup gem conversions!
    arena_1_plus_2 = {
        "loadout": {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["id"],
                "configName": "A",
                "nukeSetupId": "mirage_legerdemain",
                "config": {
                    "normalMods": [{"id": stretch["id"], "rank": stretch["maxRank"], "slot": 0}],
                },
            },
        },
        "scenario": {
            "mapId": "corpus-ship-defense",
            "spawnProfile": "custom",
            "enemySpec": "single",
            "droneEvery": 0,
            "combatStyle": "hybrid_nuke",
            "nukeSetupId": "mirage_legerdemain",
            "movement": "objective",
            "mode": "time",
            "seconds": 16.0,
            "enemies": 12,
            "level": 20,
            "seed": 20261125,
        },
    }
    res_12 = World(app._arena_context(arena_1_plus_2)).run()
    sum_12 = res_12["visuals"]["warframe"]["nukeSummary"]
    assert sum_12["setupId"] == "mirage_legerdemain"
    assert sum_12["hasLegerdemainAugment"] is False
    assert sum_12["hasHallOfMirrorsSynergy"] is True
    assert sum_12["mainJewelsConjured"] >= 1
    assert sum_12["cloneMiniJewelsConjured"] == 4 * sum_12["mainJewelsConjured"]
    assert sum_12["jewelsDetonated"] >= 1
    assert sum_12["legerdemainGemsConverted"] == 0

    #    - With Slot 1 (`slot: 0`) replaced by Helminth: spawns Main Jewel ONLY (`cloneMiniJewelsConjured == 0`)!
    arena_no_hom = {
        **arena_1_plus_2,
        "loadout": {
            **arena_1_plus_2["loadout"],
            "warframeLink": {
                **arena_1_plus_2["loadout"]["warframeLink"],
                "config": {
                    "normalMods": [{"id": stretch["id"], "rank": stretch["maxRank"], "slot": 0}],
                    "helminthReplacement": {
                        "slot": 0,
                        "abilityId": "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility",
                    },
                },
            },
        },
    }
    res_no_hom = World(app._arena_context(arena_no_hom)).run()
    sum_no_hom = res_no_hom["visuals"]["warframe"]["nukeSummary"]
    assert sum_no_hom["hasHallOfMirrorsSynergy"] is False
    assert sum_no_hom["mainJewelsConjured"] >= 1
    assert sum_no_hom["cloneMiniJewelsConjured"] == 0

