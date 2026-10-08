from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace
import pytest
import app
from wfarsenal.damage import ModdedStats, mod_effects, arcane_effects, apply_mods
from wfarsenal.combat_replay import replay
from wfarsenal.runtime_adapters import resolve_runtime_adapter, verified_crux_condition


def target(hp=1e8, **kw):
    return dict(
        health=hp,
        armour=0,
        shield=0,
        overguard=0,
        level=1,
        faction="",
        factionResistance="RK_NEUTRAL",
        **kw
    )


def stats(**kw):
    args = dict(
        damage_types={"DT_FIRE": 100.0},
        crit_chance=0.0,
        crit_multiplier=2.0,
        status_chance=1.0,
        multishot=1.0,
        fire_rate=10.0,
        magazine=100.0,
        reload_time=1.0,
        dot_base_damage=100.0,
    )
    args.update(kw)
    return ModdedStats(**args)


def run(st=None, tg=None, **kw):
    st = st or stats()
    args = dict(
        attacks_per_second=st.fire_rate, window_seconds=3.0, level=1, time_step=0.1
    )
    args.update(kw)
    return replay(st, tg or target(), **args)


def guard_replay_progress(monkeypatch):
    queue=replay.__globals__['heapq']
    original=queue.heappop
    last_time=None
    repeated=0
    def pop(heap):
        nonlocal last_time,repeated
        event=original(heap)
        repeated=repeated+1 if event[0]==last_time else 0
        last_time=event[0]
        assert repeated<100, 'events repeated without advancing simulation time'
        return event
    monkeypatch.setitem(replay.__globals__,'heapq',SimpleNamespace(heappop=pop,heappush=queue.heappush))


def test_negative_duration_refresh_still_ticks_and_stacks():
    r = run(stats(proc_duration_multiplier=0.08992))
    assert r["dotWindow"] > 0
    assert max(p["stacks"]["heat"] for p in r["timeline"]) > 20
    assert all(p["dotDps"] == 0 for p in r["timeline"] if p["time"] < 1.0)
    assert max(p["heatArmourStrip"] for p in r["timeline"]) == 0.5


def test_short_slow_procs_expire_without_ticks():
    r = run(stats(proc_duration_multiplier=0.08992, fire_rate=1.0))
    assert r["dotWindow"] == 0
    assert max(p["stacks"]["heat"] for p in r["timeline"]) <= 1


def test_zero_duration_has_no_heat_or_strip():
    r = run(stats(proc_duration_multiplier=0.0))
    assert r["dotWindow"] == 0
    assert all(
        p["heatArmourStrip"] == 0 and p["stacks"]["heat"] == 0 for p in r["timeline"]
    )


def test_heat_strip_uses_duration_scaled_clock():
    tg = target()
    tg["armour"] = 2700
    r = run(stats(proc_duration_multiplier=0.5), tg)
    p = next(p for p in r["timeline"] if p["time"] == 1.0)
    assert p["heatArmourStrip"] == 0.5
    assert p["armour"] == 1350


def test_sampling_does_not_change_damage_or_kills():
    a = run(time_step=0.1)
    b = run(time_step=0.25)
    assert a["totalWindowDamage"] == pytest.approx(b["totalWindowDamage"])
    assert a["killsInWindow"] == pytest.approx(b["killsInWindow"])


def test_no_overkill_or_old_dot_leaks_to_next_target():
    r = run(tg=target(1.0), window_seconds=2.0)
    assert r["shots"] == r["killEvents"] == 20
    assert r["dotWindow"] == 0


def test_toxin_can_kill_with_shield_remaining():
    tg = target(10.0)
    tg["shield"] = 100000
    r = run(
        stats(damage_types={"DT_POISON": 100.0}, status_chance=0),
        tg,
        window_seconds=0.1,
    )
    assert r["killEvents"] == 1
    assert r["directWindow"] == 10.0


def test_cycle_requires_head_hits_and_spends_actual_pool():
    base = stats(fire_rate=10.0, magazine=45.0)
    inc = replace(base, magazine=600.0)
    combat = {
        "cycle": {"hits": 20.0, "pool": 600.0, "enterSeconds": 2.0, "exitSeconds": 1.0},
        "resolve": lambda form, stacks, live: (base if form == "base" else inc, None),
    }
    a = run(base, combat=combat, window_seconds=5.0, headshot_chance=0.0)
    b = run(base, combat=combat, window_seconds=5.0, headshot_chance=1.0)
    assert a["transforms"] == 0
    assert b["transforms"] == 1
    assert b["timeline"][-1]["ammo"] == pytest.approx(590.0)


@pytest.mark.parametrize(
    "sid,dtype",
    [
        ("truth", "DT_GAS"),
        ("justice", "DT_EXPLOSION"),
        ("purity", "DT_CORROSIVE"),
        ("entropy", "DT_MAGNETIC"),
        ("blight", "DT_VIRAL"),
        ("sequence", "DT_RADIATION"),
    ],
)
def test_syndicate_threshold_and_no_cooldown_banking(sid, dtype):
    st = stats(
        damage_types={"DT_IMPACT": 100.0},
        status_chance=0.0,
        fire_rate=1.0,
        magazine=10000.0,
    )
    combat = {
        "resolve": lambda *args: (st, None),
        "syndicate": {"id": sid, "damageType": dtype, "affinityToFill": 1000},
        "affinityPerKill": 500.0,
    }
    r = run(st, target(1.0), combat=combat, window_seconds=34.0)
    times = [e["time"] for e in r["syndicateEvents"]]
    assert times == [1.0, 32.0]


def test_acuity_script_mutation_stays_unsupported():
    path = "/Lotus/Upgrades/Mods/Rifle/WeaponWeakpointCriticalChanceMod"
    raw = deepcopy(app.optimizer.resolve_record(app.EXPORTS["mods"], path, kind="mod"))
    assert resolve_runtime_adapter(raw, 10) is not None
    raw["runtimeScripts"]["apply"]["Function"] = "UnknownFunction"
    fx = mod_effects(raw, rank=10)
    assert not fx and any("runtime-script" in s for s in fx.skipped)


def test_verified_crux_rank_and_ammo_effect_are_dynamic():
    path = "/Lotus/Upgrades/CosmeticEnhancers/Offensive/StatusAndAmmoEfficiencyOnWeakpointHit"
    raw = app.optimizer.resolve_record(app.EXPORTS["arcanes"], path, kind="arcane")
    assert verified_crux_condition(raw)
    fx = arcane_effects(raw, rank=5, stacks=10)
    assert next(
        e.value for e in fx if e.upgrade_type == "WEAPON_PROC_CHANCE"
    ) == pytest.approx(3.0)
    assert next(
        e.value for e in fx if e.upgrade_type == "WEAPON_AMMO_CONSUME_RATE"
    ) == pytest.approx(-0.6)
    bad = deepcopy(raw)
    bad["runtimeScripts"]["apply"]["_maxStacks"] = 100
    assert verified_crux_condition(bad) is None


def test_replay_stats_roundtrip_preserves_zero_and_weakpoint_fields():
    from dataclasses import asdict

    st = stats(
        proc_duration_multiplier=0.0,
        weakpoint_damage_bonus=4.5,
        weakpoint_crit_chance_relative=3.5,
        base_crit_chance=0.28,
    )
    got = app._benchmark_timeline_stats(asdict(st))
    assert got.proc_duration_multiplier == 0.0
    assert got.weakpoint_damage_bonus == 4.5
    assert got.weakpoint_crit_chance_relative == 3.5
    assert got.base_crit_chance == 0.28


def test_heat_optimizer_uses_event_kernel_not_continuous_flow():
    from wfarsenal.damage import windowed_status_damage

    st = stats(proc_duration_multiplier=0.08992)
    direct = run(st)
    scored = windowed_status_damage(
        st,
        target(),
        attacks_per_second=st.fire_rate,
        window_seconds=3.0,
        level=1,
        time_step=0.25,
    )
    assert scored["model"] == "event-expected-v3"
    assert scored["dotWindow"] == pytest.approx(direct["dotWindow"])


def test_incoming_damage_is_not_outgoing_hit():
    from wfarsenal.manual_combat import condition_kind

    assert condition_kind({"conditions": ["OnDamageCondition"]}) is None
    assert condition_kind({"conditions": ["OnMeleeKillCondition"]}) == "on-melee-kill"


def test_galvanized_scope_aiming_changes_actual_replay():
    p = {
        "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
        "fireMode": 0,
        "mods": [
            {
                "path": "/Lotus/Upgrades/Mods/Rifle/Event/CritChanceWhileAimingRifleSPMod",
                "rank": 10,
            }
        ],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 170,
        "steelPath": True,
        "headshotChance": 1.0,
        "aiming": False,
    }
    a = app.simulate_manual_payload(p)["benchmarkTimeline"]
    b = app.simulate_manual_payload({**p, "aiming": True})["benchmarkTimeline"]
    assert b["killsPerMinute"] > a["killsPerMinute"]
    assert any(
        s["kind"] == "on-headshot" and s["avgStacks"] > 0 for s in b["triggerSeries"]
    )


def test_boltor_stacks_on_kills_not_hits():
    p = {
        "weapon": "/Lotus/Weapons/Tenno/LongGuns/PrimeBoltor/PrimeBoltor",
        "fireMode": 1,
        "mods": [],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 9999,
        "steelPath": True,
        "headshotChance": 0.0,
        "incarnonChoices": {"tier2": "2-2"},
        "triggerPolicy": "emergent",
    }
    b = app.simulate_manual_payload(p)["benchmarkTimeline"]
    rows = [
        s
        for s in b["triggerSeries"]
        if s["id"].startswith("/Lotus/Weapons/") and "Tier1BSubMod" in s["id"]
    ]
    assert rows and all(s["kind"] == "on-kill" and s["avgStacks"] == 0 for s in rows)


@pytest.mark.parametrize("dtype", ["DT_ELECTRICITY", "DT_GAS"])
def test_immediate_dot_survives_short_positive_duration(dtype):
    st = stats(
        damage_types={dtype: 100.0}, fire_rate=1.0, proc_duration_multiplier=0.01
    )
    r = run(st, window_seconds=0.5)
    assert r["dotWindow"] == pytest.approx(50.0)


def test_gas_discards_oldest_damage_instances_at_ten():
    st = stats(damage_types={"DT_GAS": 100.0}, fire_rate=100.0, status_chance=1.0)
    r = run(st, window_seconds=2.0)
    # 200 immediate procs plus at most ten retained one-second ticks.
    assert r["dotWindow"] <= 210 * 50.0 + 1e-6


def test_blast_fuse_scales_with_duration_and_ten_stacks_detonate():
    st = stats(
        damage_types={"DT_EXPLOSION": 100.0},
        fire_rate=1.0,
        proc_duration_multiplier=0.1,
    )
    r = run(st, window_seconds=0.5)
    assert r["nonDotWindow"] == pytest.approx(30.0)
    fast = run(
        replace(st, fire_rate=100.0, proc_duration_multiplier=1.0), window_seconds=0.15
    )
    assert fast["nonDotWindow"] == pytest.approx(300.0)


def test_selected_incarnon_ignores_ammo_efficiency():
    st = stats(magazine=600.0, ammo_cost=0.4)
    combat = {"resolve": lambda *args: (st, None), "selectedIncarnon": True}
    r = run(st, combat=combat, window_seconds=1.0)
    assert r["timeline"][-1]["ammo"] == 590.0


@pytest.mark.parametrize('reload_time,shots', [(0.,5),(1.,4)])
def test_selected_incarnon_pool_refills_without_base_shell_reload(monkeypatch,reload_time,shots):
    guard_replay_progress(monkeypatch)
    st=stats(fire_rate=1.,magazine=2.,reload_time=reload_time,status_chance=0.)
    def resolve(*args):
        return st,None
    combat={'resolve':resolve,'selectedIncarnon':True,
            'shellReload':{'start':.8,'perShell':.4,'end':.5,'modeSwitchLoadsShell':True}}
    result=run(st,combat=combat,window_seconds=5.)
    reference=run(st,combat={'resolve':resolve,'selectedIncarnon':True},window_seconds=5.)
    assert result['shots']==reference['shots']==shots
    assert result['totalWindowDamage']==pytest.approx(reference['totalWindowDamage'])
    assert result['reloadShellEvents']==[]
    assert result['timeline'][-1]['ammo']==reference['timeline'][-1]['ammo']


def test_mod_gain_cache_changes_with_ads():
    path = "/Lotus/Upgrades/Mods/Rifle/Event/CritChanceWhileAimingRifleSPMod"
    p = {
        "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
        "mods": [{"path": path, "rank": 10}],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 170,
        "steelPath": True,
        "headshotChance": 1.0,
        "aiming": False,
        "mode": "equipped",
        "candidates": [path],
    }
    app._MOD_GAINS_CACHE.clear()
    a = app.mod_gains_payload(p)
    b = app.mod_gains_payload({**p, "aiming": True})
    assert b["gains"][path] != a["gains"][path]


def test_fusion_availability_does_not_depend_on_recipe_presence():
    from wfarsenal.riven_fusion import available_codes

    data = deepcopy(app.EXPORTS["rivenTemplates"])
    data["fusionRecipes"] = []
    for kind in ("rifle", "shotgun", "pistol"):
        assert len(available_codes(data, kind)) == 14
    assert len(available_codes(data, "archgun")) == 13
    assert "HR" not in available_codes(data, "archgun")
    # 2026.10.08: melee also rolls status damage, the six combined elements and
    # the three new factions.
    assert available_codes(data, "melee") == {"HD", "HC", "PA", "SL", "SD", "GA", "CO", "VI", "RA", "BL", "MA", "FO", "FT", "FS"}


def test_inactive_ads_mod_has_zero_gain_with_trigger_arcane():
    path = "/Lotus/Upgrades/Mods/Rifle/Event/CritChanceWhileAimingRifleSPMod"
    p = {
        "weapon": "/Lotus/Weapons/Tenno/Rifle/BratonPrime",
        "mods": [{"path": path, "rank": 10}],
        "exilus": {
            "path": "/Lotus/Upgrades/Mods/Sets/Vigilante/PrimaryVigilanteSuppliesMod",
            "rank": 5,
        },
        "arcanes": [
            {
                "path": "/Lotus/Upgrades/CosmeticEnhancers/Offensive/PrimaryDamageOnNoMelee",
                "rank": 5,
            }
        ],
        "enemy": app._BENCHMARK_ENEMY_PATH,
        "level": 170,
        "steelPath": True,
        "headshotChance": 1.0,
        "aiming": False,
        "mode": "equipped",
        "candidates": [path],
    }
    assert app.mod_gains_payload(p)["gains"][path]["gainPercent"] == 0.0


def test_crux_refreshes_whole_pile_until_last_hit_expiry():
    path='/Lotus/Upgrades/CosmeticEnhancers/Offensive/StatusAndAmmoEfficiencyOnWeakpointHit'
    rec=app.optimizer.resolve_record(app.EXPORTS['arcanes'],path,kind='arcane')
    assert verified_crux_condition(rec)['stackMode']=='reset'
    st=stats(status_chance=0,magazine=3,fire_rate=1,reload_time=15)
    source=dict(id='crux',label='crux',kind='on-headshot',duration=10,maxStacks=10,perEvent=1)
    combat=dict(resolve=lambda *a:(st,None))
    r=run(st,combat=combat,trigger_sources=[source],headshot_chance=1,window_seconds=14)
    assert next(p for p in r['timeline'] if p['time']==11.5)['triggerStacks']['crux']==3
    assert next(p for p in r['timeline'] if p['time']==12)['triggerStacks']['crux']==0


def test_puncture_buff_is_live_and_applies_after_hit():
    st=stats(damage_types={'DT_PUNCTURE':100},crit_chance=0,fire_rate=1,status_chance=1)
    r=run(st,window_seconds=3,time_step=.5)
    assert r['timeline'][0]['stepDamage']==100
    assert r['directWindow']==pytest.approx(100+105+110)
    assert r['timeline'][-1]['punctureCritChance']==pytest.approx(.15)


def test_cold_freezes_thaws_and_overguard_caps_without_freezing():
    st=stats(damage_types={'DT_FREEZE':100},fire_rate=10,crit_chance=1,status_chance=1)
    r=run(st,window_seconds=5)
    frozen=next(p for p in r['timeline'] if p['frozen'])
    assert frozen['stacks']['cold']==10 and frozen['coldCritDamage']==1
    assert all(p['stacks']['cold']==10 for p in r['timeline'] if p['frozen'])
    assert any(not p['frozen'] and p['time']>3.9 for p in r['timeline'])
    over=run(st,{**target(),'overguard':1e12},window_seconds=5)
    assert all(p['stacks']['cold']<=4 and not p['frozen'] for p in over['timeline'])
    assert over['timeline'][-1]['coldCritDamage']==pytest.approx(.25)


def test_heat_new_proc_keeps_stronger_decay_tail():
    st=stats(fire_rate=.4,proc_duration_multiplier=1/3)
    r=run(st,window_seconds=3,time_step=.1)
    at=next(p for p in r['timeline'] if p['time']==2.6)
    assert at['stacks']['heat']==1
    assert at['heatArmourStrip']==.4
