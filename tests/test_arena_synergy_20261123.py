"""Stage 4: 3D Arena mechanics fixes, Warframe survivability & enemy AI spatial attacks,
Robotic vs Beast companion AI & Bond synergies, and non-invasive replay visuals/telemetry.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))

import app  # noqa: E402
from wfarsenal import arena_combat, companion_loadout, damage as dm  # noqa: E402
from wfarsenal.arena import Actor, World  # noqa: E402
from wfarsenal.arena_actors import (  # noqa: E402
    DEFAULT_EXCALIBUR_PORTRAIT,
    WarframeArenaState,
    cold_slow_multiplier,
)
from wfarsenal.arena_scene import ArenaScene, distance  # noqa: E402

NAUTILUS_PRIME = "/Lotus/Types/Sentinels/SentinelPowersuits/NautilusPrimeSentinelPowerSuit"
DIRIGA = "/Lotus/Types/Sentinels/SentinelPowersuits/ArcDronePowerSuit"
ADARZA_KAVAT = "/Lotus/Types/Game/CatbrowPet/MirrorCatbrowPetPowerSuit"
ASSAULT_MODE = "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack"
CALCULATED_SHOT = "/Lotus/Types/Sentinels/SentinelPrecepts/HeadShot"
ARC_COIL = "/Lotus/Types/Sentinels/SentinelPrecepts/ArcCoil"
CALCULATED_REDIRECTION = "/Lotus/Upgrades/Mods/Sentinel/SentinelShieldMaxMod"
TENACIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TenaciousPartner"
REINFORCED_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/AlacrityField"
CONTAGIOUS_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Proliferation"
MANIFOLD_BOND = "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/CompoundingLaceration"
CATS_EYE = "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowCatsEyePrecept"
ADARZA_CLAWS = "/Lotus/Types/Friendly/Pets/BeastWeapons/AdarzaPetWeapon"
BITE = "/Lotus/Upgrades/Mods/Sentinel/Kubrow/KubrowCritMod"
VERGLAS_PRIME = "/Lotus/Types/Sentinels/SentinelWeapons/SentinelFreezeRayPrimeRifle"
SHIVERING_CONTAGION = "/Lotus/Upgrades/Mods/Rifle/WeaponSpreadFreezeProcsMod"


def _weapon_by_en(name_en: str, *, min_modes: int = 1) -> dict:
    return next(
        w
        for w in app.CATALOG["weapons"]
        if w.get("nameEn") == name_en
        and w.get("available") is not False
        and not w.get("isExalted")
        and len(w.get("fireModes") or ()) >= min_modes
    )


def _mod_by_en(name_en: str) -> dict:
    candidates = [
        m
        for m in app.EXPORTS["mods"]
        if m.get("nameEn") == name_en
        and m["path"] in app.MANUAL_MODS_BY_PATH
        and "/Beginner/" not in m["path"]
    ]
    if not candidates:
        raise KeyError(name_en)
    return max(candidates, key=lambda r: int(r.get("maxRank") or 0))


def _arcane_by_en(name_en: str) -> dict:
    return next(a for a in app.EXPORTS["arcanes"] if a.get("nameEn") == name_en)


def _wf_mod_by_en(name_en: str, *, slot_kind: str | None = None) -> dict:
    candidates = []
    for row in app.WARFRAME_ENGINE.mods:
        if row.get("nameEn") != name_en or "/Beginner/" in str(row.get("path") or ""):
            continue
        if slot_kind and str(row.get("slotKind") or "").casefold() != slot_kind.casefold():
            continue
        candidates.append(row)
    return max(candidates, key=lambda r: int(r.get("maxRank") or 0))


def _wf_arcane_by_en(name_en: str) -> dict:
    return next(row for row in app.WARFRAME_ENGINE.arcanes if row.get("nameEn") == name_en)


def _flat_open_scene(*, spawn_positions: list[tuple[float, float, float]] | None = None) -> ArenaScene:
    spawns = spawn_positions or [(0.0, 0.0, 10.0), (2.5, 0.0, 10.5)]
    nodes = [(0.0, 0.0, 0.0), *spawns]
    portals = [
        {"fromFace": 0, "toFace": i, "portal": (sp[0] * 0.5, 0.0, sp[2] * 0.5)}
        for i, sp in enumerate(spawns, start=1)
    ]
    raw = {
        "nav": {
            "nodePositions": nodes,
            "nativePortals": portals,
            "componentOfFace": [0] * len(nodes),
        },
        "start": {"face": 0, "position": (0.0, 0.0, 0.0)},
        "spawns": [{"face": i, "accepted": True} for i in range(1, len(nodes))],
        "focusRegion": {"faces": list(range(len(nodes)))},
        "collision": {
            "vertices": [(-30.0, 0.0, -30.0), (30.0, 0.0, -30.0), (30.0, 0.0, 30.0), (-30.0, 0.0, 30.0)],
            "triangles": [(0, 1, 2), (0, 2, 3)],
        },
    }
    return ArenaScene(raw, native=False)


def _base_loadout(weapon_en: str = "Braton Prime", **extra) -> dict:
    w = _weapon_by_en(weapon_en)
    serration = _mod_by_en("Serration")
    base = {
        "weapon": w["path"],
        "fireMode": 0,
        "mods": [{"path": serration["path"], "rank": serration["maxRank"], "slot": 0}],
        "arcanes": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 60,
        "steelPath": False,
        "headshotChance": 0.0,
        "triggerPolicy": "emergent",
    }
    base.update(extra)
    return base


def test_arena_neutral_determinism_excalibur_visuals_and_enemy_icons():
    bramma = _weapon_by_en("Kuva Bramma")
    names = [
        "Serration",
        "Split Chamber",
        "Point Strike",
        "Vital Sense",
        "Infected Clip",
        "Cryo Rounds",
        "Heavy Caliber",
    ]
    mods = []
    pols = []
    for idx, n in enumerate(names):
        rec = _mod_by_en(n)
        mods.append({"path": rec["path"], "rank": rec["maxRank"], "slot": idx})
        pols.append(rec.get("polarity"))
    pols.append(None)

    loadout = {
        "weapon": bramma["path"],
        "fireMode": 0,
        "mods": mods,
        "slotPolarities": pols,
        "innateElement": "DT_FIRE",
        "steelPath": True,
        "level": 160,
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "triggerPolicy": "emergent",
    }
    scenario = {
        "seconds": 30.0,
        "wallSeconds": 60.0,
        "level": 160,
        "enemy": app._BENCHMARK_ENEMY_PATH,
    }
    ctx1 = app._arena_context({"loadout": loadout, "scenario": scenario})
    ctx1["warframeContext"] = None
    ctx1["companionContext"] = None
    res1 = World(ctx1).run()

    ctx2 = app._arena_context({"loadout": loadout, "scenario": scenario})
    res2 = World(ctx2).run()

    # Exact replay & eventHash determinism on neutral 30s Kuva Bramma benchmark
    assert res1["stats"]["eventHash"] == res2["stats"]["eventHash"]
    assert res1["replay"] == res2["replay"]
    assert "synergy" not in res1

    # Visuals contract when Warframe & Companion calculations are disabled
    vis = res1["visuals"]
    assert vis["warframe"]["enabled"] is False
    assert vis["warframe"]["frameId"] == "Excalibur"
    assert vis["warframe"]["portraitAsset"] == DEFAULT_EXCALIBUR_PORTRAIT
    assert vis["companion"] is None
    assert app._BENCHMARK_ENEMY_PATH in vis["enemyIcons"]
    assert str(vis["enemyIcons"][app._BENCHMARK_ENEMY_PATH]).startswith("/assets/enemies/")
    assert len(vis["actorSnapshots"]) >= 2
    t0, rows0 = vis["actorSnapshots"][0]
    assert isinstance(t0, float) and isinstance(rows0, list)
    if rows0:
        assert len(rows0[0]) == 5  # [actorId, hpRatio, shieldRatio, ogRatio, statusCount]


def test_arena_special_launch_grimoire_and_quanta_do_not_leak_committed(monkeypatch):
    scene = _flat_open_scene(spawn_positions=[(0.0, 0.0, 8.0)])
    monkeypatch.setattr("wfarsenal.arena.load_scene", lambda _: scene)

    cases = [
        ("Grimoire", {"grimoireStrategy": "single-occupant", "grimoireExpiryDistance": 0.0}),
        ("Quanta Vandal", {"quantaStrategy": "shoot"}),
    ]
    for weapon_name, combat_state in cases:
        w = _weapon_by_en(weapon_name, min_modes=2)
        loadout = {
            "weapon": w["path"],
            "fireMode": 1,
            "mods": [],
            "arcanes": [],
            "combatState": combat_state,
            "enemy": app._BENCHMARK_ENEMY_PATH,
            "level": 50,
            "steelPath": False,
            "headshotChance": 0.0,
            "triggerPolicy": "emergent",
        }
        ctx = app._arena_context(
            {
                "loadout": loadout,
                "scenario": {
                    "enemy": app._BENCHMARK_ENEMY_PATH,
                    "level": 50,
                    "enemies": 2,
                    "waves": 1,
                    "seconds": 2.5,
                    "droneEvery": 0,
                    "headshots": False,
                },
            }
        )
        world = World(ctx)
        res = world.run()
        assert res["stats"]["shots"] > 0, weapon_name
        assert world.committed == {}, f"{weapon_name} leaked committed shot entries: {world.committed}"


def test_arena_cold_stacks_slow_enemy_movement_and_overguard_cap(monkeypatch):
    assert cold_slow_multiplier(0.0, 0.0) == pytest.approx(1.0)
    assert cold_slow_multiplier(1.0, 0.0) == pytest.approx(0.50)
    assert cold_slow_multiplier(5.0, 0.0) == pytest.approx(0.30)
    assert cold_slow_multiplier(9.0, 0.0) == pytest.approx(0.10)
    # Overguard caps Cold at 4 stacks = 65% slow -> 0.35x speed multiplier
    assert cold_slow_multiplier(9.0, 1000.0) == pytest.approx(0.35)

    scene = _flat_open_scene(spawn_positions=[(0.0, 0.0, 12.0)])
    enemy_rec = next(e for e in app.EXPORTS["enemies"] if e["path"] == app._BENCHMARK_ENEMY_PATH)
    dummy_st = dm.ModdedStats(
        damage_types={"DT_IMPACT": 10.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=0.0,
        multishot=1.0,
        fire_rate=1.0,
        magazine=10.0,
        reload_time=1.0,
    )
    monkeypatch.setattr(
        arena_combat,
        "prepare",
        lambda *a, **k: {"resolve": lambda *args: (dummy_st, None), "trigger_sources": []},
    )

    def _measure_step(cold_stacks: float, overguard: float) -> float:
        world = World.__new__(World)
        world.scene = scene
        world.c = {"movement": "parkour", "npcShortGap": False}
        world.t = 0.0
        world.stats = {"crowdWaitSeconds": 0.0, "failedPathPlans": 0, "npcShortGaps": 0}
        world.replay = {"player": [], "moves": []}
        world.motion_cache = {}
        world.flows = {}
        world.fallback = {}
        actor = Actor(1, 1, (0.0, 0.0, 12.0))
        actor.tape = {"path": []}
        actor.edge = {
            "points": [(0.0, 0.0, 12.0), (0.0, 0.0, 0.0)],
            "index": 1,
            "node": 0,
            "speed": 4.0,
            "kind": "walk",
            "source_nav_faces": (),
        }
        world.live = [actor]
        world.actors = {1: actor}
        combat = arena_combat.ArenaCombat({})
        v = combat.add_target(1, enemy_rec, 50, actor.pos)
        v.pools[0] = overguard
        if cold_stacks > 0:
            from collections import deque

            v.states["DT_FREEZE"] = deque([(6.0, cold_stacks)])
        world.combat = combat
        world.move_actor(actor, 0.5, 0.0)
        return distance((0.0, 0.0, 12.0), actor.pos)

    d0 = _measure_step(0.0, 0.0)
    d1 = _measure_step(1.0, 0.0)
    d9 = _measure_step(9.0, 0.0)
    d9_og = _measure_step(9.0, 5000.0)
    assert d0 == pytest.approx(2.0)
    assert d1 == pytest.approx(1.0)
    assert d9 == pytest.approx(0.2)
    assert d9_og == pytest.approx(0.7)


def test_arena_combat_estimate_extra_hits_and_energy_spend_expiry_fix(monkeypatch):
    enemy_rec = {
        "path": "/Test/Dummy",
        "health": 10000.0,
        "armour": 0.0,
        "shield": 0.0,
        "overguard": 0.0,
        "level": 1,
        "faction": "",
        "factionResistance": "RK_NEUTRAL",
    }
    base_st = dm.ModdedStats(
        damage_types={"DT_IMPACT": 100.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=0.0,
        multishot=1.0,
        fire_rate=2.0,
        magazine=10.0,
        reload_time=1.0,
        dot_base_damage=100.0,
    )
    with_extra = replace(base_st, extra_hits=(("DT_VOID", 0.50, False),))

    monkeypatch.setattr(
        arena_combat,
        "prepare",
        lambda *a, **k: {"resolve": lambda *args: (base_st, None), "trigger_sources": []},
    )
    c_plain = arena_combat.ArenaCombat({})
    c_plain.add_target("v", enemy_rec)
    s_plain = c_plain.prepare_shot(0.0, False, "v")
    est_plain = c_plain.estimate(s_plain, "v")

    monkeypatch.setattr(
        arena_combat,
        "prepare",
        lambda *a, **k: {"resolve": lambda *args: (with_extra, None), "trigger_sources": []},
    )
    c_extra = arena_combat.ArenaCombat({})
    v_extra = c_extra.add_target("v", enemy_rec)
    s_extra = c_extra.prepare_shot(0.0, False, "v")
    est_extra = c_extra.estimate(s_extra, "v")
    assert est_extra == pytest.approx(est_plain * 1.50)

    # Confirm actual _take matches estimate with extra_hits
    c_extra.hit(s_extra, "v", t=0.0)
    c_extra.finish_shot(s_extra, 0.0)
    assert (10000.0 - v_extra.health) == pytest.approx(est_extra)

    # Bug 1.4: periodic energySpendPerSecond updates expiries for per-stack / union decay
    energy_sources = [
        {
            "id": "molt_aug",
            "kind": "energy",
            "maxStacks": 10.0,
            "duration": 8.0,
            "decay": "per-stack",
            "perEvent": 1.0,
            "energyThreshold": 10.0,
        }
    ]
    monkeypatch.setattr(
        arena_combat,
        "prepare",
        lambda *a, **k: {
            "resolve": lambda *args: (base_st, None),
            "trigger_sources": energy_sources,
            "energySpendPerSecond": 10.0,
        },
    )
    c_energy = arena_combat.ArenaCombat({})
    for step_t in (1.0, 2.0, 3.0, 4.0, 5.0):
        c_energy.advance(step_t)
    assert c_energy.sources[0]["stacks"] == pytest.approx(5.0)
    assert len(c_energy.sources[0]["expiries"]) == 5

    # Bug 1.5 & 1.6: deduplicated World._diagnose + optional enemyShieldRecharge & vip_status_cap
    w_dummy = World.__new__(World)
    w_dummy.diagnostics = ["init"]
    for _ in range(50):
        w_dummy._diagnose("repeated warning")
    assert w_dummy.diagnostics == ["init", "repeated warning"]

    shield_enemy = {
        **enemy_rec,
        "shield": 1000.0,
        "health": 1000.0,
    }
    c_rech = arena_combat.ArenaCombat({}, common_options={"enemy_shield_recharge": True, "vip_status_cap": True})
    v_boss = c_rech.add_target("boss", shield_enemy, boss=True)
    assert v_boss.vip_cap == 4
    c_rech._take(v_boss, {"DT_IMPACT": 400.0}, 0.0, "direct")
    sh_after_hit = v_boss.shield
    assert sh_after_hit < 1000.0
    c_rech._clean(v_boss, 3.5)
    assert v_boss.shield > sh_after_hit


def test_arena_warframe_survivability_shield_gate_adaptation_and_avenger(monkeypatch):
    # 1. Direct TennoDamageController unit checks on WarframeArenaState
    volt = next(f for f in app.WARFRAME_ENGINE.frames if f.get("nameEn") == "Volt")
    adapt = next(
        r
        for r in app.WARFRAME_ENGINE.mods
        if r.get("path") == "/Lotus/Upgrades/Mods/Warframe/AvatarResistanceOnDamageMod"
    )
    combat_disc = _wf_mod_by_en("Combat Discipline", slot_kind="aura")
    avenger = _wf_arcane_by_en("Arcane Avenger")
    guardian = _wf_arcane_by_en("Arcane Guardian")

    wf_calc = app.WARFRAME_ENGINE.calculate(
        {
            "frameId": volt["id"],
            "aura": {"path": combat_disc["path"], "rank": combat_disc["maxRank"]},
            "mods": [{"path": adapt["path"], "rank": adapt["maxRank"]}],
            "arcanes": [
                {"path": avenger["path"], "rank": 5},
                {"path": guardian["path"], "rank": 5},
            ],
        }
    )
    wf_state = WarframeArenaState(wf_calc, {}, seed=12345)
    init_sh = wf_state.shield
    init_hp = wf_state.health
    assert init_sh > 0.0 and wf_state.has_adaptation and wf_state.avenger_equipped

    # 50% innate Tenno Shield DR: 100 raw Impact -> 50 shield damage
    dmg1 = wf_state.take_enemy_hit(0.1, {"DT_IMPACT": 100.0})
    assert dmg1 == pytest.approx(50.0)
    assert wf_state.shield == pytest.approx(init_sh - 50.0)
    assert wf_state.max_adaptation_dr(0.1) == pytest.approx(0.10)

    # Massive non-Toxin hit breaks remaining shield with ZERO bleedthrough to Health & triggers shield gate
    wf_state.take_enemy_hit(0.2, {"DT_SLASH": 50000.0})
    assert wf_state.shield == pytest.approx(0.0)
    assert wf_state.health == pytest.approx(init_hp)
    assert wf_state.shield_breaks == 1
    assert wf_state.shield_gates_triggered == 1

    # Hit inside shield-gate invulnerability window deals 0 damage
    gated_dmg = wf_state.take_enemy_hit(0.3, {"DT_PUNCTURE": 10000.0})
    assert gated_dmg == pytest.approx(0.0)
    assert wf_state.health == pytest.approx(init_hp)

    # Combat Discipline triggers on player kill and floors HP at 2
    wf_state.on_player_kill(0.4)
    assert wf_state.combat_discipline_triggers == 1
    assert wf_state.health < init_hp

    # 2. Full 3D Arena World integration: Enemy AI attacks Warframe, triggers Arcane Avenger & Guardian + Bulwark
    scene = _flat_open_scene(
        spawn_positions=[(0.0, 0.0, 7.0), (1.8, 0.0, 7.5), (-1.8, 0.0, 7.5), (0.0, 0.0, 9.0)]
    )
    monkeypatch.setattr("wfarsenal.arena.load_scene", lambda _: scene)
    grineer_lancer = next(
        e["path"]
        for e in app.MANUAL_ENEMIES
        if e.get("faction") == "Grineer" and e.get("complete") is not False and not e.get("statusImmune")
    )
    bulwark = _arcane_by_en("Primary Bulwark")
    loadout = _base_loadout(
        "Braton Prime",
        enemy=grineer_lancer,
        level=80,
        arcanes=[{"path": bulwark["path"], "rank": 5}],
    )
    wf_high_armor = deepcopy(wf_calc)
    wf_high_armor["finalPanel"]["armor"] = 600.0  # +900 Guardian => 1500 (>1000 for Primary Bulwark!)
    scenario = {
        "enemy": grineer_lancer,
        "level": 80,
        "enemies": 16,
        "spawnBatch": 4,
        "spawnEvery": 0.4,
        "waves": 1,
        "seconds": 8.0,
        "droneEvery": 0,
    }
    ctx_neutral = app._arena_context({"loadout": loadout, "scenario": deepcopy(scenario)})
    res_neutral = World(ctx_neutral).run()

    ctx_wf = app._arena_context({"loadout": loadout, "scenario": deepcopy(scenario)})
    ctx_wf["warframeContext"] = wf_high_armor
    world_wf = World(ctx_wf)
    res_wf = world_wf.run()

    wf_stats = res_wf["synergy"]["warframeStats"]
    assert wf_stats["hitsTaken"] > 0
    assert wf_stats["damageTaken"] > 0.0
    assert res_wf["visuals"]["warframe"]["enabled"] is True
    assert len(res_wf["visuals"]["warframe"]["frames"]) >= 2
    assert len(res_wf["visuals"]["enemyShots"]) > 0
    assert wf_stats["avengerUptimeRatio"] > 0.0
    # Arcane Avenger (+45% flat crit) + Guardian/Bulwark boost player direct damage over neutral!
    assert res_wf["stats"]["directDamage"] > res_neutral["stats"]["directDamage"]


def test_arena_warframe_immortal_benchmark_vs_strict_survival(monkeypatch):
    scene = _flat_open_scene(spawn_positions=[(0.0, 0.0, 5.0), (1.5, 0.0, 5.0), (-1.5, 0.0, 5.0)])
    monkeypatch.setattr("wfarsenal.arena.load_scene", lambda _: scene)
    grineer_enemy = next(
        e["path"]
        for e in app.MANUAL_ENEMIES
        if e.get("faction") == "Grineer" and e.get("complete") is not False
    )
    fragile_wf = {
        "frame": {"id": "FragileTest", "nameEn": "Excalibur", "nameZh": "Excalibur", "portraitAsset": DEFAULT_EXCALIBUR_PORTRAIT},
        "finalPanel": {"health": 50.0, "shield": 0.0, "armor": 0.0, "energy": 100.0},
        "survivability": {"shieldGateSeconds": 0.0, "shieldRechargeRate": 0.0},
        "weaponBridge": {"arcanes": []},
        "immortalBenchmark": True,
    }
    loadout = _base_loadout("Braton Prime", mods=[], enemy=grineer_enemy, level=200)
    base_sc = {
        "enemy": grineer_enemy,
        "level": 200,
        "enemies": 8,
        "spawnBatch": 3,
        "spawnEvery": 0.4,
        "waves": 1,
        "seconds": 5.0,
        "droneEvery": 0,
    }

    # 1. Immortal benchmark (default): records downedCount & continues full benchmark window
    ctx_imm = app._arena_context({"loadout": loadout, "scenario": deepcopy(base_sc)})
    ctx_imm["warframeContext"] = deepcopy(fragile_wf)
    res_imm = World(ctx_imm).run()
    assert res_imm["synergy"]["warframeStats"]["downedCount"] >= 1
    assert res_imm["synergy"]["warframeStats"]["firstDownedAt"] is not None
    assert res_imm["reason"] != "warframe_downed"
    assert res_imm["stats"]["seconds"] == pytest.approx(5.0)

    # 2. Strict survival: terminates run immediately on lethal hit with reason == "warframe_downed"
    ctx_strict = app._arena_context(
        {"loadout": loadout, "scenario": {**deepcopy(base_sc), "strictSurvival": True}}
    )
    ctx_strict["warframeContext"] = deepcopy(fragile_wf)
    res_strict = World(ctx_strict).run()
    assert res_strict["status"] == "limited"
    assert res_strict["reason"] == "warframe_downed"
    assert res_strict["synergy"]["warframeStats"]["downedCount"] == 1
    assert res_strict["stats"]["seconds"] < 5.0


def test_arena_beast_companion_passive_bonds_never_attacks(monkeypatch):
    scene = _flat_open_scene(spawn_positions=[(0.0, 0.0, 8.0), (2.0, 0.0, 8.5)])
    monkeypatch.setattr("wfarsenal.arena.load_scene", lambda _: scene)

    point_strike = _mod_by_en("Point Strike")
    loadout = _base_loadout(
        "Braton Prime",
        mods=[{"path": point_strike["path"], "rank": point_strike["maxRank"], "slot": 0}],
        level=80,
    )
    sc = {
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 80,
        "enemies": 2,
        "waves": 1,
        "seconds": 3.0,
        "droneEvery": 0,
    }
    ctx_neutral = app._arena_context({"loadout": loadout, "scenario": deepcopy(sc)})
    res_neutral = World(ctx_neutral).run()

    beast_eval = companion_loadout.evaluate_companion(
        {
            "path": ADARZA_KAVAT,
            "mods": [
                {"path": TENACIOUS_BOND, "rank": 5, "slot": 0},
                {"path": CATS_EYE, "rank": 3, "slot": 1},
            ],
        },
        {
            "path": ADARZA_CLAWS,
            "mods": [{"path": BITE, "rank": 10, "slot": 0}],
        },
        exports=app.EXPORTS,
    )
    assert beast_eval["playerBridge"]["tenaciousBond"]["active"] is True
    assert beast_eval["attackProfile"]["arenaActiveAttack"] is False

    ctx_beast = app._arena_context({"loadout": loadout, "scenario": deepcopy(sc)})
    ctx_beast["companionContext"] = {"evaluation": beast_eval, "weaponRecord": None}
    res_beast = World(ctx_beast).run()

    comp_stats = res_beast["synergy"]["companionStats"]
    comp_vis = res_beast["visuals"]["companion"]
    assert comp_stats["shots"] == 0
    assert comp_stats["hits"] == 0
    assert comp_stats["tenaciousActive"] is True
    assert comp_vis["enabled"] is True
    assert comp_vis["category"] == "beast"
    assert comp_vis["canAttack"] is False
    assert comp_vis["arenaActiveAttack"] is False
    assert len(comp_vis["frames"]) >= 2
    # Tenacious Bond (+1.2x final crit damage) + Cat's Eye (+60% flat crit) boost player damage!
    assert res_beast["stats"]["directDamage"] > res_neutral["stats"]["directDamage"]


def test_arena_sentinel_without_attack_precept_and_robotic_active_synergies(monkeypatch):
    scene = _flat_open_scene(
        spawn_positions=[(0.0, 0.0, 10.0), (1.8, 0.0, 10.2), (-1.8, 0.0, 10.2), (0.5, 0.0, 11.5)]
    )
    monkeypatch.setattr("wfarsenal.arena.load_scene", lambda _: scene)

    frostbite = _arcane_by_en("Primary Frostbite")
    galv_apt = _mod_by_en("Galvanized Aptitude")
    loadout = _base_loadout(
        "Braton Prime",
        mods=[{"path": galv_apt["path"], "rank": galv_apt["maxRank"], "slot": 0}],
        arcanes=[{"path": frostbite["path"], "rank": 5}],
        level=80,
    )
    sc = {
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 80,
        "enemies": 8,
        "spawnBatch": 2,
        "spawnEvery": 0.5,
        "waves": 1,
        "seconds": 9.5,
        "droneEvery": 0,
    }

    # 1. Sentinel WITHOUT Assault Mode: canAttack == False and shots == 0
    passive_sentinel_eval = companion_loadout.evaluate_companion(
        {
            "path": NAUTILUS_PRIME,
            "mods": [{"path": CALCULATED_REDIRECTION, "rank": 10, "slot": 0}],
        },
        {"path": VERGLAS_PRIME, "mods": []},
        exports=app.EXPORTS,
    )
    assert passive_sentinel_eval["attackProfile"]["canAttack"] is False
    ctx_no_precept = app._arena_context({"loadout": loadout, "scenario": deepcopy(sc)})
    ctx_no_precept["companionContext"] = {"evaluation": passive_sentinel_eval}
    res_no_precept = World(ctx_no_precept).run()
    assert res_no_precept["visuals"]["companion"]["canAttack"] is False
    assert res_no_precept["synergy"]["companionStats"]["shots"] == 0

    # 2. Active Robotic Companion: Nautilus Prime + Assault Mode + Verglas Prime + Shivering Contagion + Reinforced Bond
    rime_rounds = _mod_by_en("Rime Rounds")
    split_chamber = _mod_by_en("Split Chamber")
    active_sentinel_eval = companion_loadout.evaluate_companion(
        {
            "path": NAUTILUS_PRIME,
            "mods": [
                {"path": ASSAULT_MODE, "rank": 5, "slot": 0},
                {"path": CALCULATED_REDIRECTION, "rank": 8, "slot": 1},
                {"path": REINFORCED_BOND, "rank": 5, "slot": 2},
                {"path": CONTAGIOUS_BOND, "rank": 5, "slot": 3},
            ],
        },
        {
            "path": VERGLAS_PRIME,
            "mods": [
                {"path": SHIVERING_CONTAGION, "rank": 5, "slot": 0},
                {"path": rime_rounds["path"], "rank": rime_rounds["maxRank"], "slot": 1},
                {"path": split_chamber["path"], "rank": split_chamber["maxRank"], "slot": 2},
            ],
        },
        exports=app.EXPORTS,
    )
    assert active_sentinel_eval["attackProfile"]["canAttack"] is True
    assert active_sentinel_eval["attackProfile"]["effectiveMaxRange"] == pytest.approx(24.0)

    ctx_robot = app._arena_context({"loadout": loadout, "scenario": deepcopy(sc)})
    ctx_robot["companionContext"] = {"evaluation": active_sentinel_eval}
    world_robot = World(ctx_robot)
    res_robot = world_robot.run()

    cstats = res_robot["synergy"]["companionStats"]
    cvis = res_robot["visuals"]["companion"]
    assert cvis["canAttack"] is True
    assert cvis["effectiveMaxRange"] == pytest.approx(24.0)
    assert cstats["shots"] > 0
    assert cstats["hits"] > 0
    assert cstats["directDamage"] > 0.0
    assert cstats["procsApplied"].get("DT_FREEZE", 0.0) > 0.0
    assert len(cvis["shots"]) > 0

    # Companion Cold procs fed player's Primary Frostbite stacks AND boosted player damage!
    frostbite_sources = [q for q in world_robot.combat.sources if q["kind"] == "proc-DT_FREEZE"]
    assert frostbite_sources and frostbite_sources[0]["stacks"] > 0.0
    assert res_robot["stats"]["directDamage"] > res_no_precept["stats"]["directDamage"]

    # Reinforced Bond: player reload granted companion overshield -> >= 1200 shield+overshield!
    assert world_robot.companion.overshield > 0.0
    assert cstats["reinforcedUptimeRatio"] > 0.0

    # 3. Diriga + Arc Coil + Manifold Bond + Contagious Bond low-level multi-target check
    arc_coil_rec = next(
        m for m in companion_loadout.catalog()["bodyMods"] if m.get("nameEn") == "Arc Coil"
    )
    malignant = _mod_by_en("Malignant Force")
    thermite = _mod_by_en("Thermite Rounds")
    diriga_eval = companion_loadout.evaluate_companion(
        {
            "path": DIRIGA,
            "mods": [
                {"path": CALCULATED_SHOT, "rank": 5, "slot": 0},
                {"path": arc_coil_rec["path"], "rank": int(arc_coil_rec.get("maxRank") or 5), "slot": 1},
                {"path": MANIFOLD_BOND, "rank": 5, "slot": 2},
                {"path": CONTAGIOUS_BOND, "rank": 5, "slot": 3},
            ],
        },
        {
            "path": VERGLAS_PRIME,
            "mods": [
                {"path": malignant["path"], "rank": malignant["maxRank"], "slot": 0},
                {"path": thermite["path"], "rank": thermite["maxRank"], "slot": 1},
                {"path": _mod_by_en("Serration")["path"], "rank": 10, "slot": 2},
            ],
        },
        exports=app.EXPORTS,
    )
    grineer_mob = next(
        e["path"]
        for e in app.MANUAL_ENEMIES
        if e.get("faction") == "Grineer"
        and e.get("complete") is not False
        and not e.get("statusImmune")
        and (e.get("overguard") or 0) == 0
    )
    low_sc = {
        **deepcopy(sc),
        "enemy": grineer_mob,
        "level": 5,
        "enemies": 6,
        "spawnBatch": 4,
        "seconds": 4.0,
    }
    weak_loadout = _base_loadout("Lato", mods=[], enemy=grineer_mob, level=5)
    ctx_diriga = app._arena_context({"loadout": weak_loadout, "scenario": low_sc})
    ctx_diriga["companionContext"] = {"evaluation": diriga_eval}
    world_diriga = World(ctx_diriga)
    monkeypatch.setattr(world_diriga, "choose", lambda: None)  # ensure all kills come from companion!
    res_diriga = world_diriga.run()
    dstats = res_diriga["synergy"]["companionStats"]
    assert dstats["manifoldTriggers"] >= 1
    assert dstats["kills"] >= 1
    assert dstats["contagiousSpreads"] >= 1
