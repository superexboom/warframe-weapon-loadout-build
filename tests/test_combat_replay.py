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
    assert r["dotWindow"] == pytest.approx(50.5)


def test_gas_discards_oldest_damage_instances_at_ten():
    st = stats(damage_types={"DT_GAS": 100.0}, fire_rate=100.0, status_chance=1.0)
    r = run(st, window_seconds=2.0)
    # One immediate shared tick, then ten retained seeds at t=1 and t=2.
    assert r["dotWindow"] == pytest.approx(50.5 + 2 * 500.5)
    from wfarsenal.proc_probability import ProcPile
    pile = ProcPile(10)
    for source in range(11):
        pile.add(0., 6., [(1., 1, 50., .5, 1., False)], source=source)
    assert pile.tick(0., pile.token)[5] == 1  # The capped-out first seed is not the breaking weapon.


def test_electric_gas_pile_retains_latest_landing_correlation():
    from wfarsenal.proc_probability import ProcPile
    # Pinned M100: the same three applying hits differ only in their order.
    values = []
    for order in ('HHB', 'BHH'):
        pile = ProcPile()
        for mark in order:
            head = mark == 'H'
            pile.add(0., 6., [(1., 1, 1296. if head else 240., 1.5, 1.8 if head else 1., head)])
        values.append(pile.moments(0.)[:2])
    assert values == [(2833.5, 0.), (5100.3, 5100.3)]
    # Mixed success/landing retains both seed and accumulator joint moments.
    pile = ProcPile()
    outcomes = [(0.5, 0, 0., 0., 1., False), (.25, 1, 1., .5, 1., False), (.25, 1, 3., 1.5, 2., True)]
    for _ in range(2):
        pile.add(0., 6., outcomes)
    assert pile.moments(0.) == pytest.approx((4.625, 3.75, 1., .75), rel=1e-12)
    pile = ProcPile(10)
    pile.add(0., 6., [(1., 9, 1., .5, 1., False)])
    pile.add(0., 6., [(0.5, 0, 0., 0., 1., False)] + [
        (.125, n, 3. if head else 1., .5, 2. if head else 1., head)
        for n in (1, 2) for head in (False, True)])
    assert pile.moments(0.) == pytest.approx((14.125, 6.75, 9.5, 1.))


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


def test_arena_shared_shooter_snapshot_and_independent_targets(monkeypatch):
    from wfarsenal import arena_combat as arena
    base = stats(damage_types={'DT_IMPACT': 100.}, status_chance=0., magazine=1., fire_rate=2.)
    radial = replace(base, radial_only=True)
    def resolve(form, stacks, live, last):
        factor = 1. + stacks.get('kill', 0.)
        return replace(base, damage_types={'DT_IMPACT': 100.*factor}), replace(radial, damage_types={'DT_IMPACT':100.*factor})
    monkeypatch.setattr(arena, 'prepare', lambda *a, **k: dict(resolve=resolve, trigger_sources=[dict(id='kill',kind='on-kill',maxStacks=3,duration=1.,perEvent=1.)]))
    session=arena.ArenaCombat({})
    a=session.add_target('a',target(50.)); b=session.add_target('b',target(250.)); untouched=session.add_target('c',target(500.))
    shot=session.prepare_shot(0.,False,'a')
    session.hit(shot,'a'); session.hit(shot,'b','radial')
    assert a.health==0 and b.health==pytest.approx(150.) and untouched.health==500.
    assert session.ammo==1. and session.sources[0]['stacks']==0.
    session.finish_shot(shot)
    assert session.ammo==0. and session.sources[0]['stacks']==1.
    assert [e['targetId'] for e in session.drain_events() if e['kind']=='kill']==['a']
    assert session.prepare_shot(.5,False,'b') is None
    assert session.reloads==1 and session.next_attack_time(.5)==pytest.approx(1.5)
    session.advance(1.5)
    follow=session.prepare_shot(1.5,False,'b')
    assert follow.stats.damage_types['DT_IMPACT']==100.  # shared buff expired during reload
    session.hit(follow,'b'); session.finish_shot(follow)
    assert b.health==pytest.approx(50.) and untouched.health==500.
    # Two projectiles may coexist; impact ordering never pays ammo twice.
    base=replace(base,magazine=3.)
    flying=arena.ArenaCombat({}); victim=flying.add_target('v',target(250.))
    first=flying.prepare_shot(0.,False,'v'); flying.fire_shot(first)
    second=flying.prepare_shot(.5,False,'v'); flying.fire_shot(second)
    assert flying.ammo==1. and flying.shots==2
    planned=flying.preview(.5,'v'); before=(flying.ammo,victim.health,flying.shots)
    assert flying.estimate(planned,'v')==pytest.approx(100.)
    assert before==(flying.ammo,victim.health,flying.shots)
    flying.begin_impact(second,.8); flying.hit(second,'v',t=.8); flying.finish_impact(second,.8)
    flying.begin_impact(first,1.); flying.hit(first,'v',t=1.); flying.finish_impact(first,1.)
    assert victim.health==pytest.approx(50.) and flying.ammo==1.


@pytest.mark.parametrize('dtype', ['DT_ELECTRICITY','DT_GAS'])
def test_arena_independent_proc_clocks_and_neighbour_damage(monkeypatch,dtype):
    from wfarsenal import arena_combat as arena
    st=stats(damage_types={dtype:100.},fire_rate=2.,magazine=4.)
    monkeypatch.setattr(arena,'prepare',lambda *a,**k:dict(resolve=lambda *args:(st,None),trigger_sources=[]))
    session=arena.ArenaCombat({})
    a=session.add_target('a',target(1e6)); b=session.add_target('b',target(1e6)); c=session.add_target('c',target(1e6))
    session.nearby=lambda id,radius,t: ['b'] if id=='a' else []
    shot=session.prepare_shot(0.,False,'a'); session.hit(shot,'a'); session.finish_shot(shot)
    session.advance(2.)
    assert a.damage>100.
    assert (b.damage>0)==(dtype in ('DT_ELECTRICITY','DT_GAS'))
    assert c.damage==0. and not c.presence
    assert not b.presence  # area ticks do not recursively apply source procs
    assert session.shots==1 and session.ammo==3.
    # Chunked stepping must preserve source clocks/latest conditional moments.
    other=arena.ArenaCombat({})
    for id in ('a','b','c'): other.add_target(id,target(1e6))
    other.nearby=session.nearby
    shot=other.prepare_shot(0.,False,'a'); other.hit(shot,'a'); other.finish_shot(shot)
    for t in (.25,.5,.75,1.,1.25,1.5,1.75,2.): other.advance(t)
    assert other.targets['a'].damage==pytest.approx(a.damage)
    assert other.targets['b'].damage==pytest.approx(b.damage)


def test_arena_fixed_actor_and_unreachable_staging_use_ground_graph_cache():
    from types import SimpleNamespace
    from wfarsenal.arena import World, Actor

    calls=[]
    class Scene:
        nodes=((0.,0.,0.),(2.,0.,0.),(3.,0.,0.),(4.,0.,0.),(5.,0.,0.),(.1,0.,0.))
        disabled=set()
        def movement_components(self,profile):return (0,1,1,1,1,0)
        def visible(self,*args):return True
        def search(self,start,profile,reverse=False):
            calls.append((start,profile,reverse))
            return SimpleNamespace(d=[0. if i==start else float('inf') for i in range(6)],
                                   prev=[-1]*6,edges=[None]*6,reverse=reverse)
    world=World.__new__(World)
    world.scene=Scene();world.c={"movement":"fixed"};world.t=0.
    world.player=Actor(-1,0,(0.,0.,0.));world.live=[Actor(1,1,(2.,0.,0.)),Actor(2,2,(3.,0.,0.))]
    world.flow_node=-1;world.flows={};world.fallback={};world.combat=SimpleNamespace(targets={})
    world.plan();count=len(calls)
    world.plan();assert len(calls)==count  # same staging node, no repeated search
    world.player.node=5
    world.plan();assert len(calls)==count+1  # new player flow only, old ground staging flows remain
    world.player.route=[object()];world.player.edge={"invalid":"must never move"}
    assert world.move_actor(world.player,1.,0.)==0.
    assert world.player.pos==(0.,0.,0.) and not world.player.route and world.player.edge is None
    from wfarsenal.arena_scene import ArenaScene, distance
    ground={"nav":{"vertices":[[-5.,0.,-5.],[5.,0.,-5.],[0.,0.,5.]],
                  "triangles":[[0,1,2],[0,1,2]],"nodePositions":[[0.,0.,0.],[.5,0.,1.]],
                  "nativePortals":[{"fromFace":0,"toFace":1,"portal":[.25,0.,.5]}]},
            "collision":{"vertices":[[-5.,0.,-5.],[5.,0.,-5.],[0.,0.,5.]],"triangles":[[0,1,2]]},
            "start":{"face":0,"position":[0.,0.,0.]},"spawns":[]}
    world.scene=ArenaScene(ground,native=False);world.c={"movement":"parkour"}
    blocker=Actor(0,0,(1.,0.,0.));walker=Actor(1,0,(.5,0.,0.))
    walker.tape={"path":[]};walker.edge={"points":[walker.pos,(2.,0.,0.)],"index":1,"node":0,"speed":3.6,"kind":"walk"}
    world.live=[blocker,walker];world.combat=SimpleNamespace(targets={1:SimpleNamespace(frozen_until=-1.)})
    world.stats={"crowdWaitSeconds":0.};world.replay={"player":[]};world.motion_cache={}
    world.record(walker,0.)
    before=walker.pos
    for k in range(8):world.move_actor(walker,.1,k*.1)
    assert world.stats.get("crowdDetours",0)==1 and walker.pos!=before
    assert walker.pos[0]<before[0]  # real supported retreat, not through blocker
    assert 0.<distance(before,walker.pos)<=.36+.00001
    assert distance(walker.pos,blocker.pos)>=distance(before,blocker.pos)
    # If support disappears, a later blocked-edge attempt keeps exact feet/edge.
    walker.pos=before;walker.edge={"points":[before,(2.,0.,0.)],"index":1,"node":0,"speed":3.6,"kind":"walk"}
    original_edge=walker.edge
    world.scene.ground_support=lambda *a,**k:None
    assert not world._yield_crowded_edge(walker,10.)
    assert walker.pos==before and walker.edge is original_edge
    # Disconnected target floor does not forbid a reachable firing vantage.
    from wfarsenal.arena_scene import Edge
    vantage_edge=Edge(0,1,((0.,0.,0.),(1.,0.,0.)),"walk",1.,True,1.,1.,key="vantage")
    result=SimpleNamespace(d=[0.,1.,float("inf")],prev=[-1,0,-1],edges=[None,vantage_edge,None],reverse=False)
    class VantageScene:
        nodes=((0.,0.,0.),(1.,0.,0.),(2.,0.,0.));disabled=set()
        def movement_components(self,profile):return (0,0,1)
        def search(self,*args,**kwargs):return result
        def visible(self,origin,target):return origin[0]>.5
    world.scene=VantageScene();world.c={"movement":"parkour","rangeAssumption":100.};world.t=0.
    world.player=Actor(-1,0,(0.,0.,0.));world.live=[Actor(2,2,(2.,0.,0.))]
    world.flow_node=0;world.flows={"enemy":result};world.fallback={};world.fallback_staging={}
    world.combat=SimpleNamespace(preview=lambda t:None,targets={2:SimpleNamespace(protected=False)})
    world.aimpoint=lambda actor:((actor.pos[0],1.,actor.pos[2]),False)
    world.stats={"failedPathPlans":0}
    world.plan()
    assert world.player.route==[vantage_edge] and world.stats["firingPositionPlans"]==1
