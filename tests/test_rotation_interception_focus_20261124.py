"""Regression tests for:
1. Light/Dark mode CSS fixes (checkbox checkmarks & shielded arcane slot backgrounds)
2. 3D Arena non-custom enemy isolation & mission default starting levels
3. 3D Arena Interception total progress bar (1..4 towers / frozen) & 1h/2h durations
4. Warframe Realistic Ability Rotation (1->2->3->4 priority, cast lock, energy vacuum, orb economy)
5. Operator Focus 3.0+ Star-Map catalog, evaluator, and strict framework-only isolation
"""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))

import app  # noqa: E402
from wfarsenal import ability_rotation, arena  # noqa: E402
from wfarsenal.arena import World  # noqa: E402


def _weapon_by_en(name_en: str) -> dict:
    return next(
        w
        for w in app.CATALOG["weapons"]
        if w.get("nameEn") == name_en
        and w.get("available") is not False
        and not w.get("isExalted")
    )


def _mod_by_en(name_en: str) -> dict:
    candidates = [
        m
        for m in app.EXPORTS["mods"]
        if m.get("nameEn") == name_en
        and m["path"] in app.MANUAL_MODS_BY_PATH
        and "/Beginner/" not in m["path"]
    ]
    return max(candidates, key=lambda r: int(r.get("maxRank") or 0))


def _wf_by_en(name_en: str) -> dict:
    return next(
        row
        for row in [*app.WARFRAME_CATALOG["warframes"], *app.WARFRAME_CATALOG["warframeForms"]]
        if row.get("nameEn") == name_en
    )


def _wf_mod_by_en(name_en: str, *, slot_kind: str | None = None) -> dict:
    candidates = []
    wanted = name_en.casefold()
    for row in app.WARFRAME_ENGINE.mods:
        if str(row.get("nameEn") or "").casefold() != wanted or "/Beginner/" in str(row.get("path") or ""):
            continue
        if slot_kind and str(row.get("slotKind") or "").casefold() != slot_kind.casefold():
            continue
        candidates.append(row)
    return max(candidates, key=lambda r: int(r.get("maxRank") or 0))


def _wf_arcane_by_en(name_en: str) -> dict:
    return next(row for row in app.WARFRAME_ENGINE.arcanes if row.get("nameEn") == name_en)


# ── 1. Light/Dark CSS Regression Guards ──────────────────────────────────────

def test_css_light_checkbox_and_dark_shielded_arcane_no_whitewash():
    css = (ROOT / "frontend" / "app.css").read_text(encoding="utf-8")
    assert ".arcane-workbench-slot.is-synergy-shielded" in css
    assert '[data-theme="light"] .arcane-workbench-slot.is-synergy-shielded' in css
    assert '[data-theme="light"] .build-scenario-fold .check-field input:checked::before' in css
    # Ensure synergy / arcane / companion / operator sections (after .synergy-return-bar) never use color-mix()
    synergy_tail = css[css.index(".synergy-return-bar") :]
    assert "color-mix(" not in synergy_tail


# ── 2 & 3. Arena Enemy Isolation, Mission Default Level & Interception ───────

def test_arena_non_custom_enemy_strips_build_page_combat_scenario_flags():
    w = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    polluted_loadout = {
        "weapon": w["path"],
        "fireMode": 0,
        "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 9999,
        "steelPath": True,
        "armourStrip": 0.80,
        "enemyEnhancements": {
            "eximus": True,
            "empowered": True,
            "archimedea": True,
            "playerCount": 4,
        },
    }

    catalog = app.arena_catalog_payload()
    spec = next(s for s in catalog["enemySpecs"] if s.get("selectionEnabled") is not False and s.get("rows"))
    map_id = (spec.get("mapIds") or [catalog["maps"][0]["id"]])[0]
    mission_nodes = spec.get("missions") or [
        m for m in catalog["missionCoverage"]["nodes"]
        if any((p if isinstance(p, str) else p.get("path") or p.get("id")) == spec["id"] for p in (m.get("enemySpecPaths") or ()))
    ]
    base_lv = int((mission_nodes[0].get("minEnemyLevel") if mission_nodes else None) or 30)
    arb_def_level = max(60, base_lv)

    # Non-custom mission spawn profile ("arbitration" = 来源仲裁防御) must ignore weapon build page's SP / Eximus / Empowered / Archimedea / Strip
    ctx_mission = app._arena_context(
        {
            "loadout": polluted_loadout,
            "scenario": {
                "mapId": map_id,
                "spawnProfile": "arbitration",
                "enemySpec": spec["id"],
                "level": arb_def_level,
                "mode": "time",
                "seconds": 30,
            },
        }
    )
    assert ctx_mission["loadout"].get("steelPath") is False
    assert ctx_mission["loadout"].get("armourStrip") == 0.0
    assert ctx_mission["loadout"]["enemyEnhancements"]["eximus"] is False
    assert ctx_mission["loadout"]["enemyEnhancements"]["empowered"] is False
    assert ctx_mission["loadout"]["enemyEnhancements"]["archimedea"] is False
    assert ctx_mission["common_options"]["steel_path"] is False
    assert ctx_mission["common_options"]["armour_strip"] == 0.0
    assert ctx_mission["common_options"]["enemy_enhancements"].get("eximus") is not True

    # Custom + single enemy MUST preserve weapon build page's SP & Eximus flags
    ctx_custom = app._arena_context(
        {
            "loadout": polluted_loadout,
            "scenario": {
                "mapId": map_id,
                "spawnProfile": "custom",
                "enemySpec": "single",
                "level": 160,
                "mode": "time",
                "seconds": 30,
            },
        }
    )
    assert ctx_custom["loadout"].get("steelPath") is True
    assert ctx_custom["loadout"]["enemyEnhancements"]["eximus"] is True
    assert ctx_custom["common_options"]["steel_path"] is True


def test_arena_interception_total_progress_and_1h_2h_budgets():
    # 1h (3600s) and 2h (7200s) scenario normalization
    sc_1h = arena.normalize_scenario({"spawnProfile": "interception", "seconds": 3600, "interceptionTowers": 4})
    sc_2h = arena.normalize_scenario({"spawnProfile": "arbitration_interception", "seconds": 7200, "interceptionTowers": 2})
    sc_hold = arena.normalize_scenario(
        {"spawnProfile": "interception", "mode": "waves", "seconds": 1800, "interceptionTowers": 0, "interceptionProgress": 0.45}
    )
    assert sc_1h["mode"] == "time" and sc_1h["seconds"] == 3600.0 and sc_1h["interceptionTowers"] == 4
    assert sc_2h["mode"] == "time" and sc_2h["seconds"] == 7200.0 and sc_2h["interceptionTowers"] == 2
    # Wave mode is forced to time mode for interception, and towers=0 preserves fixed progress
    assert sc_hold["mode"] == "time" and sc_hold["interceptionTowers"] == 0 and sc_hold["interceptionProgress"] == pytest.approx(0.45)

    # Run a fast Interception round with 4 towers (TerritoryMission 4-tower = 104s capture) over 120s:
    # must complete Round 1 at ~104s without any fixed enemy kill quota and advance into Round 2!
    w = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    split = _mod_by_en("Split Chamber")
    point_strike = _mod_by_en("Point Strike")
    vital_sense = _mod_by_en("Vital Sense")
    catalog = app.arena_catalog_payload()
    spec = next(s for s in catalog["enemySpecs"] if s.get("selectionEnabled") is not False and s.get("rows"))
    map_id = (spec.get("mapIds") or [catalog["maps"][0]["id"]])[0]
    ctx = app._arena_context(
        {
            "loadout": {
                "weapon": w["path"],
                "fireMode": 0,
                "mods": [
                    {"path": serration["path"], "rank": serration["maxRank"], "slot": 0},
                    {"path": split["path"], "rank": split["maxRank"], "slot": 1},
                    {"path": point_strike["path"], "rank": point_strike["maxRank"], "slot": 2},
                    {"path": vital_sense["path"], "rank": vital_sense["maxRank"], "slot": 3},
                ],
                "enemy": app._BENCHMARK_ENEMY_PATH,
                "level": 20,
            },
            "scenario": {
                "mapId": map_id,
                "spawnProfile": "interception",
                "enemySpec": spec["id"],
                "level": 20,
                "mode": "time",
                "seconds": 120,
                "interceptionTowers": 4,
                "waveWait": 2.0,
            },
        }
    )
    res = World(ctx).run()
    assert res["status"] == "time_limit"
    assert res["stats"]["waves"] >= 1
    assert len(res["replay"]["waves"]) >= 2
    assert res["replay"]["waves"][0].get("capturedAt") == pytest.approx(104.0, abs=1.0)


# ── 4. Warframe Channeled Efficiency, Cast Time & Realistic Ability Rotation ─

def test_warframe_channeled_efficiency_spawn_energy_and_cast_speed():
    oraxia = _wf_by_en("Oraxia")
    streamline = _wf_mod_by_en("Streamline")
    fleeting = _wf_mod_by_en("Fleeting Expertise")
    natural_talent = _wf_mod_by_en("Natural Talent")

    # Streamline (+30% eff) + Fleeting Expertise (+60% eff, -60% dur) => 190% raw eff, 40% dur.
    # In-game formula: max(0.25, (2.0 - 1.90) / 0.40) = 0.25x channel drain!
    calc = app.WARFRAME_ENGINE.calculate(
        {
            "frameId": oraxia["path"],
            "normalMods": [
                {"path": streamline["path"], "rank": streamline["maxRank"], "slot": 0},
                {"path": fleeting["path"], "rank": fleeting["maxRank"], "slot": 1},
                {"path": natural_talent["path"], "rank": natural_talent["maxRank"], "slot": 2},
            ],
        }
    )
    assert calc["finalPanel"]["abilityEfficiency"] == pytest.approx(1.75)
    assert calc["finalPanel"]["uncappedAbilityEfficiency"] == pytest.approx(1.90)
    silken = calc["abilityScalars"][3]
    assert silken["energyCost"]["drainPerSecond"] == pytest.approx(silken["energyCost"]["baseDrainPerSecond"] * 0.25)
    # Cast time scales by 1 / (1 + 0.50)
    assert silken["castTime"]["baseSeconds"] > 0
    assert silken["castTime"]["seconds"] == pytest.approx(silken["castTime"]["baseSeconds"] / 1.5, rel=1e-3)

    # Harrow passive: 100% starting energy
    harrow = _wf_by_en("Harrow Prime")
    h_calc = app.WARFRAME_ENGINE.calculate({"frameId": harrow["path"]})
    econ = h_calc["weaponBridge"]["energyEconomy"]
    assert econ["fullSpawnEnergyPassive"] is True
    assert econ["spawnEnergy"] == pytest.approx(h_calc["finalPanel"]["energy"])


def test_rotation_priority_1234_cast_lock_vacuum_and_orb_conversion():
    # Mirage Prime: Hall of Mirrors (slot 0 -> 1技能, 25E) + Eclipse (slot 2 -> 3技能, 25E)
    mirage = _wf_by_en("Mirage Prime")
    m_calc = app.WARFRAME_ENGINE.calculate({"frameId": mirage["path"]})
    sim = ability_rotation.WarframeRotationSimulator(
        m_calc,
        uncond_warframe_result=m_calc,
        active_ability_ids=["hall-of-mirrors", "eclipse"],
        rotation_config={"enabled": True},
        seed=42,
    )
    assert [it.slot_index for it in sim.items] == [0, 2]
    c1 = sim.items[0].base_cast_time / sim.current_casting_speed_multiplier(0.0)
    c3 = sim.items[1].base_cast_time / sim.current_casting_speed_multiplier(0.0)
    assert c1 > 0.4 and c3 > 0.4

    # Advance step-by-step: [0, c1) casts slot 0 (1技能), then [c1, c1+c3) casts slot 2 (3技能)
    sim.advance(0.1)
    assert sim.casting_item is not None and sim.casting_item.primary_id == "hall-of-mirrors"
    assert sim.is_weapon_locked(0.1) is True
    assert sim.ability_strength_ratio("hall-of-mirrors", 0.1) == 0.0
    assert sim.ability_strength_ratio("eclipse", 0.1) == 0.0

    sim.advance(c1 + 0.05)
    assert sim.ability_strength_ratio("hall-of-mirrors", c1 + 0.05) == pytest.approx(1.0)
    assert sim.casting_item is not None and sim.casting_item.primary_id == "eclipse"
    assert sim.is_weapon_locked(c1 + 0.05) is True
    assert sim.ability_strength_ratio("eclipse", c1 + 0.05) == 0.0

    sim.advance(c1 + c3 + 0.05)
    assert sim.is_weapon_locked(c1 + c3 + 0.05) is False
    assert sim.ability_strength_ratio("hall-of-mirrors", c1 + c3 + 0.05) == pytest.approx(1.0)
    assert sim.ability_strength_ratio("eclipse", c1 + c3 + 0.05) == pytest.approx(1.0)

    # Energy vacuum + Equilibrium orb conversion test:
    # Rhino (non-Prime, base InitialEnergy=50) with Flow (+100% max energy -> 250 max),
    # Blind Rage R10 (+99% Str, -55% Eff -> Roar [75 base] costs 116.25 energy!) + Equilibrium R10 (110% HP->Energy).
    rhino = _wf_by_en("Rhino")
    blind_rage = _wf_mod_by_en("Blind Rage")
    equilibrium = _wf_mod_by_en("Equilibrium")
    flow = _wf_mod_by_en("Flow")
    vitality = _wf_mod_by_en("Vitality")
    redirection = _wf_mod_by_en("Redirection")
    r_calc = app.WARFRAME_ENGINE.calculate(
        {
            "frameId": rhino["path"],
            "normalMods": [
                {"path": blind_rage["path"], "rank": blind_rage["maxRank"], "slot": 0},
                {"path": equilibrium["path"], "rank": equilibrium["maxRank"], "slot": 1},
                {"path": flow["path"], "rank": flow["maxRank"], "slot": 2},
                {"path": vitality["path"], "rank": vitality["maxRank"], "slot": 3},
                {"path": redirection["path"], "rank": redirection["maxRank"], "slot": 4},
            ],
        }
    )
    vac_sim = ability_rotation.WarframeRotationSimulator(
        r_calc,
        uncond_warframe_result=r_calc,
        active_ability_ids=["roar"],
        rotation_config={"enabled": True},
        seed=7,
    )
    roar_item = vac_sim.items[0]
    roar_cost = vac_sim.effective_activation_cost(roar_item, 0.0)
    roar_cast = roar_item.base_cast_time / vac_sim.current_casting_speed_multiplier(0.0)
    assert vac_sim.spawn_energy < roar_cost
    # Before any kills, Rhino lacks energy -> enters vacuum period!
    vac_sim.advance(2.0)
    assert vac_sim.ability_strength_ratio("roar", 2.0) == 0.0
    assert vac_sim.total_casts == 0
    assert vac_sim.summary_payload(2.0)["maxVacuumSeconds"] >= 2.0 - 1e-6

    # Eximus kill drops 2x Health Orb (2 * 50 * 1.10 = 110 Energy via Equilibrium) + >=1x Energy Orb (>=25 Energy)!
    vac_sim.on_enemy_kill(2.0, is_eximus=True)
    assert vac_sim.health_orbs_picked >= 2
    assert vac_sim.energy_orbs_picked >= 1
    vac_sim.advance(2.0 + roar_cast + 0.05)
    assert vac_sim.total_casts == 1
    assert vac_sim.ability_strength_ratio("roar", 2.0 + roar_cast + 0.05) == pytest.approx(1.0)


def test_1d_and_3d_arena_warframe_rotation_integration():
    w = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    rhino_p = _wf_by_en("Rhino Prime")
    energize = _wf_arcane_by_en("Arcane Energize")

    base_payload = {
        "weapon": w["path"],
        "fireMode": 0,
        "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 60,
        "warframeLink": {
            "enabled": True,
            "frameId": rhino_p["path"],
            "configName": "A",
            "config": {
                "arcanes": [{"path": energize["path"], "rank": 5}],
            },
            "activeAbilities": ["roar"],
            "abilityRotation": {"enabled": False},
        },
    }
    res_static = app.simulate_manual_payload(base_payload)
    assert res_static["synergySummary"]["warframe"]["abilityRotation"] is None

    rot_payload = {
        **base_payload,
        "warframeLink": {
            **base_payload["warframeLink"],
            "abilityRotation": {"enabled": True},
        },
    }
    res_rot = app.simulate_manual_payload(rot_payload)
    rot_summary = res_rot["synergySummary"]["warframe"]["abilityRotation"]
    assert rot_summary is not None and rot_summary["enabled"] is True
    assert rot_summary["totalCasts"] >= 1
    assert rot_summary["weaponCastPauseSeconds"] > 0
    assert 0.0 < rot_summary["firingDutyCycle"] < 1.0
    # Cast pause reduces sustained DPS slightly vs infinite-uptime zero-cast-time static mode
    assert res_rot["moddedStats"]["sustainedDps"] < res_static["moddedStats"]["sustainedDps"]

    # 3D Arena integration with realistic rotation enabled
    catalog = app.arena_catalog_payload()
    ctx = app._arena_context(
        {
            "loadout": rot_payload,
            "scenario": {
                "mapId": catalog["maps"][0]["id"],
                "spawnProfile": "custom",
                "enemySpec": "single",
                "level": 30,
                "mode": "time",
                "seconds": 15,
                "aliveCap": 6,
                "spawnEvery": 0.5,
            },
        }
    )
    arena_res = World(ctx).run()
    wf_stats = arena_res["synergy"]["warframeStats"]
    wf_rot = wf_stats["abilityRotation"]
    assert wf_rot is not None and wf_rot["enabled"] is True
    assert wf_rot["totalCasts"] >= 1
    assert wf_rot["weaponCastPauseSeconds"] > 0
    assert arena_res["visuals"]["warframe"]["abilityRotationEnabled"] is True
    assert len(arena_res["visuals"]["warframe"]["frames"][0]) >= 9
    # First player weapon shot cannot happen before Roar's initial cast animation finishes!
    first_shot_t = arena_res["replay"]["shots"][0][0]
    assert first_shot_t >= wf_rot["abilities"][0]["castTimeSec"] - 1e-3


# ── 5. Operator Focus 3.0+ Star-Map Catalog & Strict Isolation ───────────────

def test_operator_focus_catalog_evaluation_and_damage_isolation():
    cat = app.operator_catalog_payload()
    assert len(cat["schools"]) == 5
    total_nodes = sum(len(s["nodes"]) for s in cat["schools"])
    way_bounds = [n for s in cat["schools"] for n in s["nodes"] if n.get("isWayBound")]
    tauron_nodes = [n for s in cat["schools"] for n in s.get("ultimateBranchNodes") or ()]
    assert total_nodes == 50
    assert len(tauron_nodes) == 25
    assert len(way_bounds) == 10

    # Verify every iconAsset exists on disk across all 50 standard + 25 Tauron nodes + school emblems
    for s in cat["schools"]:
        icons = s.get("iconAssets") or {}
        for asset_rel in icons.values():
            if asset_rel:
                assert (ROOT / "frontend" / asset_rel.lstrip("/")).is_file(), asset_rel
        for n in [*(s.get("nodes") or ()), *(s.get("ultimateBranchNodes") or ())]:
            assert (ROOT / "frontend" / n["iconAsset"].lstrip("/")).is_file(), n["iconAsset"]

    # Find Zenurik's Way-Bound nodes and Madurai's Phoenix Talons + Void Strike from catalog
    madurai_school = next(s for s in cat["schools"] if s["id"] == "madurai")
    madurai_nodes = {n["nameEn"]: n["id"] for n in madurai_school["nodes"]}
    zenurik_school = next(s for s in cat["schools"] if s["id"] == "zenurik")
    zenurik_wb = next(n for n in zenurik_school["nodes"] if n.get("isWayBound"))

    zen_nodes_cfg = {
        n["id"]: {
            "unlocked": True,
            "rank": n["maxRank"],
            "enabled": True,
            "unbound": bool(n["id"] == zenurik_wb["id"]),
        }
        for n in zenurik_school["nodes"]
    }
    mad_nodes_cfg = {
        n["id"]: {"unlocked": True, "rank": n["maxRank"], "enabled": True}
        for n in madurai_school["nodes"]
    }

    eval_res = app.operator_evaluate_payload(
        {
            "activeSchool": "madurai",
            "schools": {
                "madurai": {"schoolUnlocked": True, "nodes": mad_nodes_cfg},
                "zenurik": {"schoolUnlocked": True, "nodes": zen_nodes_cfg},
            },
            "activeTriggers": {madurai_nodes["Void Strike"]: True},
        }
    )
    assert eval_res["integrationStatus"] == "active_combat_bridge"
    w_buff_ids = {b["id"] for b in eval_res["buffPreview"]["weaponRelevant"]}
    assert madurai_nodes["Phoenix Talons"] in w_buff_ids
    assert madurai_nodes["Void Strike"] in w_buff_ids
    assert any(wb["id"] == zenurik_wb["id"] and wb["unbound"] is True for wb in eval_res["wayBounds"])

    # Strict damage isolation: passing operatorFocus in /api/simulate does NOT alter weapon damage
    w = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    clean = app.simulate_manual_payload(
        {
            "weapon": w["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
        }
    )
    with_op = app.simulate_manual_payload(
        {
            "weapon": w["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 100,
            "operatorFocus": {"activeSchool": "madurai", "activeTriggers": {madurai_nodes["Void Strike"]: True}},
        }
    )
    assert with_op["moddedStats"]["sustainedDps"] == pytest.approx(clean["moddedStats"]["sustainedDps"])
    assert with_op["moddedStats"]["averageHit"] == pytest.approx(clean["moddedStats"]["averageHit"])


def test_helminth_rules_chinese_localization_and_invigoration_catalog():
    cat = app.WARFRAME_CATALOG
    rules = cat.get("helminthRules") or {}
    dmg_buff_paths = set(rules.get("damageBuffAbilityPaths") or ())
    assert "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility" in dmg_buff_paths
    assert "/Lotus/Powersuits/Harlequin/Abilities/LightAbility" in dmg_buff_paths
    assert "/Lotus/Powersuits/BrokenFrame/Abilities/BrokenRotAbility" in dmg_buff_paths

    # Invigorations carry both offensive and utility categories
    invigs = cat.get("invigoration") or []
    assert any(str(i.get("category") or "").casefold() == "offensive" for i in invigs)
    assert any(str(i.get("category") or "").casefold() == "utility" for i in invigs)

    # Mirage replacing slot 3 (4技能 Prism) with Roar while keeping slot 2 (3技能 Eclipse) -> localized Chinese conflict error
    mirage = _wf_by_en("Mirage Prime")
    with pytest.raises(app.SimulationError) as exc_info:
        app.WARFRAME_ENGINE.calculate(
            {
                "frameId": mirage["path"],
                "helminthReplacement": {
                    "slot": 3,
                    "abilityId": "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility",
                },
            }
        )
    msg = str(exc_info.value)
    assert "不允许同时拥有两个伤害增幅技能" in msg
    assert "damage-buff" in msg

    # Replacing slot 2 (3技能 Eclipse itself) with Roar is allowed!
    ok_res = app.WARFRAME_ENGINE.calculate(
        {
            "frameId": mirage["path"],
            "helminthReplacement": {
                "slot": 2,
                "abilityId": "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility",
            },
        }
    )
    assert "roar-helminth" in {a["id"] for a in ok_res["weaponBridge"]["availableAbilities"]}


def test_ability_rotation_exclusions_augment_promotion_and_custom_cast_order():
    eng = app.WARFRAME_ENGINE

    # 1. Equinox slot 1 Metamorphosis -> excluded_form_switch
    equinox = eng.calculate({"frameId": _wf_by_en("Equinox Prime")["path"]})
    eq_slots = equinox["weaponBridge"]["energyEconomy"]["slotAbilities"]
    assert eq_slots[0]["rotationEligible"] is False
    assert eq_slots[0]["excludedReason"] == "excluded_form_switch"
    assert eq_slots[0]["excludedReasonZh"] == "双形态切换剔除"
    eq_rot = ability_rotation.simulate_1d_ability_rotation(
        warframe_result=equinox,
        active_ability_ids=["metamorphosis", "provoke"],
        rotation_config={"enabled": True},
        window_seconds=20.0,
    )
    assert eq_rot["abilityMultipliers"].get("metamorphosis") == 0.0
    assert "metamorphosis" in eq_rot["excludedIds"]

    # 2. Excalibur slot 1 Slash Dash (special exalted) & slot 4 Exalted Blade (exalted), slot 2 Radial Blind eligible
    excal = eng.calculate({"frameId": _wf_by_en("Excalibur")["path"]})
    ex_slots = excal["weaponBridge"]["energyEconomy"]["slotAbilities"]
    assert ex_slots[0]["rotationEligible"] is False and ex_slots[0]["excludedReason"] == "excluded_slot1_special_exalted"
    assert ex_slots[1]["rotationEligible"] is True
    assert ex_slots[2]["rotationEligible"] is False and ex_slots[2]["excludedReason"] == "excluded_pure_damage"
    assert ex_slots[3]["rotationEligible"] is False and ex_slots[3]["excludedReason"] == "excluded_exalted"

    # 3. Khora Whipclaw, Mesa Peacemaker, Sevagoth Exalted Shadow all excluded
    khora = eng.calculate({"frameId": _wf_by_en("Khora Prime")["path"]})
    assert khora["weaponBridge"]["energyEconomy"]["slotAbilities"][0]["rotationEligible"] is False
    mesa = eng.calculate({"frameId": _wf_by_en("Mesa Prime")["path"]})
    assert mesa["weaponBridge"]["energyEconomy"]["slotAbilities"][3]["rotationEligible"] is False
    sev = eng.calculate({"frameId": _wf_by_en("Sevagoth Prime")["path"]})
    assert sev["weaponBridge"]["energyEconomy"]["slotAbilities"][3]["rotationEligible"] is False
    assert sev["weaponBridge"]["energyEconomy"]["slotAbilities"][3]["excludedReason"] == "excluded_form_switch"

    # 4. Volt slot 1 Shock: pure damage excluded without augment, promoted to eligible when Shock Trooper equipped!
    volt_plain = eng.calculate({"frameId": _wf_by_en("Volt Prime")["path"]})
    assert volt_plain["weaponBridge"]["energyEconomy"]["slotAbilities"][0]["rotationEligible"] is False
    shock_trooper = _wf_mod_by_en("Shock Trooper")
    volt_aug = eng.calculate(
        {
            "frameId": _wf_by_en("Volt Prime")["path"],
            "normalMods": [{"path": shock_trooper["path"], "rank": shock_trooper["maxRank"], "slot": 0}],
        }
    )
    v_s0 = volt_aug["weaponBridge"]["energyEconomy"]["slotAbilities"][0]
    assert v_s0["rotationEligible"] is True
    assert v_s0["promotedByAugment"] is not None

    # 5. Mirage Prime: non-weapon-buff slot 2 Sleight of Hand (戏法) eligible, slot 4 Prism excluded, custom opening castOrder!
    mirage_p = eng.calculate({"frameId": _wf_by_en("Mirage Prime")["path"]})
    m_slots = mirage_p["weaponBridge"]["energyEconomy"]["slotAbilities"]
    assert [s["rotationEligible"] for s in m_slots] == [True, True, True, False]
    assert m_slots[3]["excludedReason"] == "excluded_pure_damage"

    sim = ability_rotation.WarframeRotationSimulator(
        mirage_p,
        uncond_warframe_result=mirage_p,
        active_ability_ids=["hall-of-mirrors", "slot-2", "eclipse", "slot-4"],
        rotation_config={"enabled": True, "castOrder": ["eclipse", "slot-2", "hall-of-mirrors"]},
        seed=11,
    )
    # Slot 4 (Prism) is rejected; opening order strictly follows [3] Eclipse -> [2] Sleight of Hand -> [1] Hall of Mirrors!
    assert [it.slot_index for it in sim.items] == [2, 1, 0]
    sim.advance(0.1)
    assert sim.casting_item is not None and sim.casting_item.primary_id == "eclipse"
    c_ec = sim.items[0].base_cast_time
    c_s2 = sim.items[1].base_cast_time
    sim.advance(c_ec + 0.05)
    assert sim.casting_item is not None and sim.casting_item.slot_index == 1
    sim.advance(c_ec + c_s2 + 0.05)
    assert sim.casting_item is not None and sim.casting_item.primary_id == "hall-of-mirrors"


def test_mirage_hall_of_mirrors_clone_restrictions_and_total_eclipse():
    mirage = _wf_by_en("Mirage Prime")
    blind_rage = _wf_mod_by_en("Blind Rage")
    transient = _wf_mod_by_en("Transient Fortitude")
    umbral_int = _wf_mod_by_en("Umbral Intensify")
    hall_aug = _wf_mod_by_en("Hall of Malevolence")
    total_ec = _wf_mod_by_en("Total Eclipse")

    braton = _weapon_by_en("Braton Prime")
    serration = _mod_by_en("Serration")
    galv_chamber = _mod_by_en("Galvanized Chamber")
    galv_apt = _mod_by_en("Galvanized Aptitude")
    deadhead = next(a for a in app.EXPORTS["arcanes"] if a.get("nameEn") == "Primary Deadhead")

    # A. Bare weapon (>=250% Strength, no Eclipse, no Deadhead, no Galvanized, 0% headshot) -> full 2x40%*Str * 1.5!
    high_str_mods = [
        {"path": blind_rage["path"], "rank": blind_rage["maxRank"], "slot": 0},
        {"path": transient["path"], "rank": transient["maxRank"], "slot": 1},
        {"path": umbral_int["path"], "rank": umbral_int["maxRank"], "slot": 2},
        {"path": hall_aug["path"], "rank": hall_aug["maxRank"], "slot": 3},
    ]
    bare_res = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "headshotChance": 0.0,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "config": {"reactor": True, "polarities": ["AP_ATTACK", "AP_ATTACK", "AP_UMBRA", "AP_POWER", None, None, None, None], "normalMods": high_str_mods},
                "activeAbilities": ["hall-of-mirrors"],
                "damageTriggerMode": "off",
            },
        }
    )
    hom_bare = bare_res["synergySummary"]["warframe"]["activeAbilities"][0]["mirageCloneDetail"]
    str_val = bare_res["synergySummary"]["warframe"]["panel"]["abilityStrength"]
    assert str_val >= 2.50
    assert hom_bare["cloneCcScScale"] == pytest.approx(1.0)
    assert hom_bare["dilutionRatio"] == pytest.approx(1.0, rel=1e-3)
    assert hom_bare["effectiveBonus"] == pytest.approx(0.80 * str_val * 1.5, rel=1e-3)

    # B. Realistic stacked weapon (Primary Deadhead + Galv Chamber + Galv Aptitude + unaugmented Eclipse + 50% headshot):
    # Clones do NOT inherit Deadhead, Galvanized stacks, headshots, or unaugmented Eclipse!
    stacked_no_te = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [
                {"path": galv_chamber["path"], "rank": galv_chamber["maxRank"], "slot": 0},
                {"path": galv_apt["path"], "rank": galv_apt["maxRank"], "slot": 1},
            ],
            "arcanes": [{"path": deadhead["path"], "rank": deadhead["maxRank"]}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "headshotChance": 0.5,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "config": {"reactor": True, "polarities": ["AP_ATTACK", "AP_ATTACK", "AP_UMBRA", "AP_POWER", None, None, None, None], "normalMods": high_str_mods},
                "activeAbilities": ["hall-of-mirrors", "eclipse"],
                "damageTriggerMode": "off",
            },
        }
    )
    hom_no_te = next(
        a["mirageCloneDetail"]
        for a in stacked_no_te["synergySummary"]["warframe"]["activeAbilities"]
        if a["id"] == "hall-of-mirrors"
    )
    assert hom_no_te["totalEclipseEquipped"] is False
    assert hom_no_te["dilutionRatio"] < 0.12
    assert hom_no_te["effectiveBonus"] < 0.12 * hom_no_te["rawCloneTotal"]

    # C. Equipping Total Eclipse (全蚀) lets clones inherit Eclipse -> effective clone bonus jumps dramatically!
    with_te_mods = [*high_str_mods, {"path": total_ec["path"], "rank": total_ec["maxRank"], "slot": 4}]
    stacked_with_te = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 0,
            "mods": [
                {"path": galv_chamber["path"], "rank": galv_chamber["maxRank"], "slot": 0},
                {"path": galv_apt["path"], "rank": galv_apt["maxRank"], "slot": 1},
            ],
            "arcanes": [{"path": deadhead["path"], "rank": deadhead["maxRank"]}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "headshotChance": 0.5,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "config": {"reactor": True, "polarities": ["AP_ATTACK", "AP_ATTACK", "AP_UMBRA", "AP_POWER", "AP_POWER", None, None, None], "normalMods": with_te_mods},
                "activeAbilities": ["hall-of-mirrors", "eclipse"],
                "damageTriggerMode": "off",
            },
        }
    )
    hom_with_te = next(
        a["mirageCloneDetail"]
        for a in stacked_with_te["synergySummary"]["warframe"]["activeAbilities"]
        if a["id"] == "hall-of-mirrors"
    )
    assert hom_with_te["totalEclipseEquipped"] is True
    assert hom_with_te["effectiveBonus"] > 4.0 * hom_no_te["effectiveBonus"]

    # D. Zero-clone alt-fires: Grimoire alt-fire (grimoireStrategy) and Trumna alt-fire (fireMode=1) yield 0% clone bonus!
    grimoire = _weapon_by_en("Grimoire")
    grim_alt = app.simulate_manual_payload(
        {
            "weapon": grimoire["path"],
            "fireMode": 0,
            "combatState": {"grimoireStrategy": "single-occupant"},
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "activeAbilities": ["hall-of-mirrors"],
            },
        }
    )
    hom_grim = grim_alt["synergySummary"]["warframe"]["activeAbilities"][0]["mirageCloneDetail"]
    assert hom_grim["effectiveBonus"] == 0.0
    assert hom_grim["restrictedReason"] is not None

    trumna = _weapon_by_en("Trumna Prime")
    trum_alt = app.simulate_manual_payload(
        {
            "weapon": trumna["path"],
            "fireMode": 1,
            "mods": [],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "activeAbilities": ["hall-of-mirrors"],
            },
        }
    )
    hom_trum = trum_alt["synergySummary"]["warframe"]["activeAbilities"][0]["mirageCloneDetail"]
    assert hom_trum["effectiveBonus"] == 0.0
    assert hom_trum["restrictedReason"] is not None

    # E. Incarnon form (fireMode=1 on Braton Prime) also accurately evaluates dilutionRatio < 1.0 (no IndexError on sliced fireModes)!
    inc_res = app.simulate_manual_payload(
        {
            "weapon": braton["path"],
            "fireMode": 1,
            "mods": [],
            "arcanes": [{"path": deadhead["path"], "rank": deadhead["maxRank"]}],
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 160,
            "warframeLink": {
                "enabled": True,
                "frameId": mirage["path"],
                "activeAbilities": ["hall-of-mirrors", "eclipse"],
                "damageTriggerMode": "off",
            },
        }
    )
    hom_inc = next(
        a["mirageCloneDetail"]
        for a in inc_res["synergySummary"]["warframe"]["activeAbilities"]
        if a["id"] == "hall-of-mirrors"
    )
    assert 0.0 < hom_inc["dilutionRatio"] < 0.15
    assert hom_inc["effectiveBonus"] == pytest.approx(hom_inc["rawCloneTotal"] * hom_inc["dilutionRatio"], rel=1e-3)


