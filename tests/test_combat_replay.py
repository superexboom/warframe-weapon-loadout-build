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
    # Even a weak packet pays the local minimum before its own element;
    # status damage scales the stored seed, never the initial 1.
    weak = replace(st, dot_base_damage=.1, proc_damage_multiplier=4., dot_elemental_multipliers={dtype: 2.})
    assert run(weak, window_seconds=.5, collect_timeline=False)['dotWindow'] == pytest.approx(2.)
    assert run(replace(weak,dot_base_damage=2.), window_seconds=.5, collect_timeline=False)['dotWindow'] == pytest.approx(9.)


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


    # A weak packet arriving after a strong landing changes the entire group's floor.
    pile = ProcPile(10, radial=True)
    pile.add(0., 6., [(1., 1, .3, .5, 2., False)])
    pile.add(0., 1., [(1., 1, .3, .5, 3., True)])
    assert pile.moments(0.) == pytest.approx((3.3, 3.3, 2., 1.))
    assert pile.moments(1.) == pytest.approx((3., 3., 1., 1.))
    pile.reset()
    for _ in range(2):
        pile.add(0., 6., [(.5, 0, 0., 0., 1., False), (.5, 1, .4, .5, 2., False)])
    # Exactly one success pays 2; two successes pay 2.6; zero pays nothing.
    assert pile.moments(0.) == pytest.approx((1.65, 0., 1., .75))


def test_blast_fuse_scales_with_duration_and_ten_stacks_detonate(monkeypatch):
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

    from wfarsenal import arena_combat
    from wfarsenal.arena import World
    monkeypatch.setattr(arena_combat, 'prepare', lambda *a, **k: dict(resolve=lambda *args:(st,None)))
    world=World.__new__(World); combat=world.combat=arena_combat.ArenaCombat({})
    world.scene=SimpleNamespace(visible=lambda origin, end: end[0]>=0)
    world.live=[]; combat.blast_recipients=world.blast_recipients
    for key,x in [('host',0),('near',1),('edge',5.3),('far',5.6),('wall',-2),('aura',2)]:
        v=combat.add_target(key,target(2000 if key=='host' else 10000),position=(x,0,0))
        v.protected=key=='aura'; v.status_immune=key=='edge'
        world.live.append(SimpleNamespace(id=key,pos=v.position,drone=False,dead=False))
    def fire(t):
        shot=combat.prepare_shot(t,False,'host');combat.hit(shot,'host');combat.finish_shot(shot)
    fire(0.);combat.advance(.5)
    assert combat.targets['host'].damage==pytest.approx(130.) and combat.blast_neighbour_damage==0.
    assert 'DT_EXPLOSION' not in combat.targets['host'].presence
    st=replace(st,status_chance=10.,proc_duration_multiplier=1.)
    fire(1.)
    assert combat.targets['host'].damage==pytest.approx(530.)  # original host gets no 5m hit
    assert 'DT_EXPLOSION' not in combat.targets['host'].presence
    assert [combat.targets[k].damage for k in ('near','edge')]==pytest.approx([3000.,3000.])
    st=replace(st,status_chance=1.);fire(2.)
    st=replace(st,status_chance=0.,damage_types={'DT_IMPACT':3000.});fire(3.);combat.advance(6.)
    assert [combat.targets[k].damage for k in ('near','edge','far','wall','aura')]==pytest.approx([3300.,3300.,0.,0.,0.])
    assert not combat.targets['near'].presence and not combat.targets['host'].blasts


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

    # Event delivery must retain base ammo rules and independent victim state.
    def configured(st, sources=(), **contract):
        monkeypatch.setattr(arena, 'prepare', lambda *a, **k: dict(
            resolve=lambda *args:(st,None), trigger_sources=sources, **contract))
        combat=arena.ArenaCombat({}, common_options={"delivery_kinds":["lingering"]})
        for name in ('a','b','c'): combat.add_target(name,target(1e8))
        return combat
    direct=stats(damage_types={'DT_PUNCTURE':100.},status_chance=3.,magazine=10.,fire_rate=4.)
    for selected,expected in [(False,10.),(True,9.)]:
        combat=configured(direct, selectedIncarnon=selected,
                          magazineRestore=dict(kind='on-headshot',fraction=1.))
        shot=combat.prepare_shot(0.);combat.hit(shot,'a',head=True);combat.finish_shot(shot)
        assert combat.ammo==expected  # base head refill never refills Incarnon charge
    combat=configured(direct, punctureArmorStrip=.2, magazineRestore=dict(
        kind='on-hit',victimProcType='DT_ELECTRICITY',amount=1.,chance=.4,oncePerShot=True))
    for name in ('a','b'):
        combat.targets[name].presence['DT_ELECTRICITY']=arena.StatusPresence()
        combat.targets[name].presence['DT_ELECTRICITY'].add(6.,0.)
    shot=combat.prepare_shot(0.);combat.hit(shot,'a');combat.hit(shot,'b');combat.finish_shot(shot)
    assert combat.ammo==pytest.approx(9.4)  # once per shot, not per collateral target
    combat.advance(12.);combat._clean(combat.targets['a'],12.)
    assert combat.targets['a'].puncture_strip==.2 and combat.targets['c'].puncture_strip==0.
    assert combat._count(combat.targets['a'],'DT_PUNCTURE',12.)==0.  # strip survives expiry
    sources=[dict(id='pierce',kind='on-three-enemy-punchthrough',maxStacks=1.,perEvent=1.),
             dict(id='heads',kind='on-consecutive-headshot',minimumConsecutive=2,maxStacks=4.,perEvent=1.)]
    combat=configured(direct,sources)
    shot=combat.prepare_shot(0.);combat.fire_shot(shot)
    for t,name in enumerate(('a','a','b','c')):
        when=t*.01
        combat.begin_impact(shot,when);combat.hit(shot,name,head=True,t=when)
        combat.finish_impact(shot,when,retire=False)
    assert [q['stacks'] for q in combat.sources]==[1.,2.]  # repeated target is not a new pierce
    shot=combat.prepare_shot(.25);combat.hit(shot,'a');combat.finish_shot(shot)
    assert combat.sources[1]['stacks']==0.

    # Full-burst gates wait for every actual projectile, including late/missing hits.
    burst_sources=[dict(id=kind,kind=kind,maxStacks=4.,perEvent=1.)
                   for kind in ('on-burst-hit','on-burst-headshot')]
    combat=configured(direct,burst_sources,baseBurst=dict(count=2,delay_seconds=.3),baseFireRate=2.)
    first=combat.prepare_shot(0.);combat.fire_shot(first)
    assert first.interval==pytest.approx(.15)  # fire-rate scales intra-burst delay
    second=combat.prepare_shot(.15);combat.fire_shot(second)
    assert second.interval==pytest.approx(.25)
    combat.begin_impact(second,.2);combat.hit(second,'a',head=True,t=.2);combat.finish_impact(second,.2)
    assert all(q['stacks']==0. for q in combat.sources)
    combat.begin_impact(first,.3);combat.hit(first,'a',head=True,t=.3);combat.finish_impact(first,.3)
    assert [q['stacks'] for q in combat.sources]==[1.,1.]
    first=combat.prepare_shot(.4);combat.finish_shot(first)  # an entire round misses
    second=combat.prepare_shot(.55);combat.hit(second,'a',head=True);combat.finish_shot(second)
    assert [q['stacks'] for q in combat.sources]==[1.,1.]
    first=combat.prepare_shot(.8);combat.hit(first,'a');combat.finish_shot(first)
    second=combat.prepare_shot(.95);combat.hit(second,'a',head=True);combat.finish_shot(second)
    assert [q['stacks'] for q in combat.sources]==[2.,1.]  # body breaks full-burst headshots
    combat=configured(replace(direct,magazine=3.),burst_sources,
                      baseBurst=dict(count=2,remainingClip=True,ignoreFireRate=True,delay_seconds=.3),baseFireRate=2.)
    for when in (0.,.3,.6):
        shot=combat.prepare_shot(when);combat.hit(shot,'a',head=True);combat.finish_shot(shot)
        assert shot.burst_state['size']==3
        assert shot.interval==pytest.approx(.25 if when==.6 else .3)
    assert combat.sources[0]['stacks']==1.
    assert combat.prepare_shot(.85) is None and combat.sources[0]['stacks']==0.  # reload resets burst-hit
    combat=configured(direct,selectedIncarnon=True,baseBurst=dict(count=2,delay_seconds=.3),
                      incarnonBurst=dict(count=3,delay_seconds=.1),incarnonFireRate=4.)
    assert combat.prepare_shot(0.).burst_state['size']==3  # selected form uses its own burst
    combat=configured(direct,baseBurst=dict(count=4,delay_seconds=0.))
    from wfarsenal.arena import World
    world=World.__new__(World);world.combat=combat;world.t=0.;launched=[]
    def fire_one(aim):
        shot=combat.prepare_shot(world.t);combat.fire_shot(shot);launched.append(shot)
    world._fire_one=fire_one;world.fire({})
    assert len(launched)==4 and [s.time for s in launched]==[0.]*4 and combat.ammo==6.

    # Empty-reload Torid duration is consumed once at launch, even for a miss.
    cloud=replace(direct,radial_only=True)
    field=replace(direct,magazine=1.)
    field._lingering=(cloud,2.,4.)
    combat=configured(field,fieldDurationOnEmptyReload=dict(multiplier=2.))
    shot=combat.prepare_shot(0.);combat.finish_shot(shot)
    assert combat.prepare_shot(.25) is None
    combat.advance(1.25)
    shot=combat.prepare_shot(1.25);assert shot.field_duration_multiplier==1.
    combat.fire_shot(shot);assert shot.field_duration_multiplier==2. and not combat.field_duration_ready
    from wfarsenal.arena import World
    world=World.__new__(World);world.combat=combat;world.t=1.25;world.replay={};world.actors={}
    world.events=[];world.sequence=0;world.diagnostics=[]
    assert world._place_lifecycle(shot,{'lifecycleProfile':{}},(0.,0.,0.),[],(0.,0.,0.))
    assert next(iter(world.entities.values()))['end']==pytest.approx(9.25)

    # Conditional spatial effects use fire-time stacks; old projectiles stay frozen.
    from wfarsenal.damage import Scenario, ModEffect
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Felarx'))
    engine=dict(weapon=weapon,fire_mode=0,effects=[ModEffect('WEAPON_RANGE','ADD',7.)],scenario=Scenario())
    monkeypatch.undo()  # use the actual prepare contract for the exported Felarx toggle
    range_source=dict(path='/test/range',conditionalEffects=[dict(eventKind='on-hit',maxStacks=2,duration=1.,
                      effects=[dict(upgradeType='WEAPON_RANGE',operation='ADD',valuePerRank=5.)])])
    combat=arena.ArenaCombat(engine,[(range_source,0,None)],incarnon_choices={'tier3':'3-1'})
    world.combat=combat;world.context={'engine':engine};world.c={'rangeAssumption':100.};world.shot_geometry={}
    old=combat.preview(0.);before=world.geometry(old)
    combat._signal('on-reload-complete',0.)
    after=world.geometry(combat.preview(0.))
    assert abs(after['puncture']-before['puncture'])==pytest.approx(4.)
    assert world.geometry(old)==before and after['range']==pytest.approx(107.)
    combat._signal('on-hit',0.)
    assert world.geometry(combat.preview(0.))['range']==pytest.approx(112.)
    combat.advance(1.)
    assert world.geometry(combat.preview(1.))['range']==pytest.approx(107.)


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
    if dtype == 'DT_ELECTRICITY':
        # Break damage is its own body packet. Only its forced proc is blocked
        # by Electricity immunity, and it cannot retarget after the host dies.
        magnetic = arena.ArenaCombat({})
        for id, immune in (('live', []), ('immune', ['DT_ELECTRICITY']), ('retired', [])):
            victim = magnetic.add_target(id, dict(target(1000.), shield=1000., statusImmunities=immune))
            victim.pooled['DT_MAGNETIC'].add(6., 0., 10.)
            magnetic._take(victim, {'DT_IMPACT': 1000. / 4.25}, 0., 'direct', stats=st)
            assert victim.shield == 0 and victim.health == pytest.approx(950.)
            assert ('DT_ELECTRICITY' in victim.presence) == (not immune)
        magnetic._take(magnetic.targets['retired'], {'DT_IMPACT': 2000.}, 0., 'direct', stats=st)
        fresh = magnetic.add_target('new', target(1000.))
        magnetic.advance(1.)
        assert magnetic.targets['live'].health == pytest.approx(950. - 2 * 25.5)
        assert magnetic.targets['immune'].health == pytest.approx(950.)
        assert fresh.damage == 0. and not fresh.presence


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
    # Smaller IDs cannot cross a stationary larger-ID body either.
    blocker.id=2
    walker.pos=before;walker.edge={"points":[before,(2.,0.,0.)],"index":1,"node":0,"speed":3.6,"kind":"walk"}
    world.move_actor(walker,.1,1.)
    assert distance(walker.pos,blocker.pos)>=distance(before,blocker.pos)-1e-6
    blocker.id=0
    # Millimetre event steps must not keep a crowd wait below the .8s yield
    # threshold while the actor has made no meaningful progress.
    walker.pos=before;walker.crowd_progress_position=before;walker.crowd_progress_since=0.
    walker.crowd_blocked_seconds=0.;walker.crowd_retry_after=100.
    world.move_actor(walker,.01,.9)
    assert walker.crowd_blocked_seconds>=.8
    # Source surface walks use the same grounded, collision-checked retreat.
    walker.pos=before;walker.edge={"points":[before,(2.,0.,0.)],"index":1,"node":0,"speed":3.6,"kind":"source-surface-walk"}
    walker.crowd_retry_after=0.
    assert world._yield_crowded_edge(walker,2.)
    assert all(world._crowd_segment_clear(walker,a,b)
               for a,b in zip(walker.edge["points"],walker.edge["points"][1:]))
    walker.drone=True
    walker.pos=before;walker.edge={"points":[before,(2.,0.,0.)],"index":1,"node":0,"speed":5.,"kind":"walk"}
    assert world._yield_crowded_edge(walker,3.)
    walker.drone=False
    # A yielded actor with an empty route still recovers the forward source
    # corridor from the shared flow, rather than returning to its old portal.
    from wfarsenal.arena_scene import Edge
    forward=Edge(0,1,((0.,0.,0.),(.5,0.,1.)),"walk",1.,True,1.,1.,key="forward")
    world.flows={"enemy":SimpleNamespace(d=[1.,0.],prev=[1,-1],edges=[forward,None],reverse=True)}
    walker.pos=before;walker.route=[]
    walker.edge={"points":[before,(2.,0.,0.)],"index":1,"node":0,"speed":3.6,"kind":"walk"}
    assert world._yield_crowded_edge(walker,4.) and walker.edge["node"]==1
    walker.pos=before;walker.route=[]
    walker.edge={"points":[before,before],"index":1,"node":0,"speed":3.6,"kind":"walk"}
    assert world._yield_crowded_edge(walker,4.5,clear_landing=before)
    assert distance(walker.edge["points"][-1],before)>=.75
    assert all(world._crowd_segment_clear(walker,a,b)
               for a,b in zip(walker.edge["points"],walker.edge["points"][1:]))
    world.flows={}
    # A tightly packed door merge needs only a .2m tangent step. Resuming
    # behind that step would restore the same two-actor standstill.
    walker.pos=(0.,0.,0.);walker.route=[];blocker.pos=(-.06,0.,-.597)
    walker.edge={"points":[walker.pos,(.1,0.,-.03),(.2,0.,-.06),(.3,0.,-.09)],
                 "index":1,"node":0,"speed":3.6,"kind":"door"}
    assert world._yield_crowded_edge(walker,5.)
    assert walker.edge["points"][-1]==(.3,0.,-.09)
    assert all(p[0] >= -.001 for p in walker.edge["points"])
    assert (.1,0.,-.03) not in walker.edge["points"]
    blocker.pos=(1.,0.,0.)
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
    # A visible drone can still be blocked by a protected actor in the muzzle.
    # An unsuccessful scored shot must allow repositioning despite clear LOS.
    world.player.route=[];world.aim_blocked=True
    world.scene.visible=lambda origin,target:True
    world.plan()
    assert world.player.route==[vantage_edge]
    # A nearby drone on the SAME reachable node must not keep the shooter
    # inside a protected body's muzzle. Verify actual contacts from the new node.
    world.scene.nodes=((0.,0.,0.),(2.,0.,0.),(3.,0.,0.))
    world.scene.raycast=lambda *a,**k:None
    drone=Actor(3,0,(.6,0.,0.),drone=True);cover=Actor(4,0,(0.,0.,0.))
    world.live=[drone,cover];world.player.route=[]
    world.combat.targets={3:SimpleNamespace(protected=False,record={}),
                          4:SimpleNamespace(protected=True,record={"hitProxies":[{"part":"HEAD"}]})}
    world.combat.preview=lambda t:SimpleNamespace(radials=())
    world.geometry=lambda shot:dict(range=100.,traceRadius=0.,puncture=0.,
                                    infinitePuncture=False,ignoresAvatars=False,projectile=True)
    world.plan()
    assert world.player.route==[vantage_edge] and world.stats["firingPositionPlans"]==3
    # A source-island target keeps its cleanup route despite other nearby
    # targets; reaching the endpoint must allow damage to that exact target.
    isolated=Actor(9,2,(30.,0.,0.),unreachable=True);isolated.staging_since=0.
    world.live=[isolated];world.t=2.;world.player.route=[]
    world.combat.targets={9:SimpleNamespace(protected=False,frozen_until=-1.)}
    world.combat.preview=lambda t:object()
    world._can_fire_from=lambda p,s,*,target_id=None:p[0]>=1. and target_id==9
    assert world._plan_staged_target() and world.player.route==[vantage_edge]
    assert world.staging_target_id==9
    assert world._plan_staged_target() and world.player.route==[vantage_edge]
    # Two different airborne arcs through the same corridor must not start
    # together and block each other halfway across. Release follows completion.
    crossing=Edge(0,1,((0.,0.,0.),(1.,.45,0.),(2.,0.,0.)),"npc-short-gap",1.,False,1.,2.,key="air")
    first=Actor(6,0,(1.,.45,0.),edge={"kind":"bullet-jump","node":1,"points":crossing.points},drone=True)
    queued=Actor(7,0,(0.,0.,0.),route=[crossing],tape={"path":[]})
    world.live=[first,queued];world.stats["crowdWaitSeconds"]=0.;world.c["npcShortGap"]=True
    assert world.move_actor(queued,.1,0.)==0. and queued.route==[crossing]
    assert queued.edge is None and queued.pos==(0.,0.,0.)
    # Ground arrivals must also respect the in-flight landing reservation.
    ground_arrival=Edge(0,1,((0.,0.,0.),(2.,0.,0.)),"walk",1.,True,1.,2.,key="ground")
    queued.route=[ground_arrival]
    assert world.move_actor(queued,.1,.1)==0. and queued.route==[ground_arrival]
    assert queued.edge is None and queued.pos==(0.,0.,0.)


def test_arena_source_door_query_channels():
    from wfarsenal.arena_scene import ArenaScene

    floor = [[-5., 0., -5.], [5., 0., -5.], [5., 0., 5.], [-5., 0., 5.]]
    wall = [[2., 0., -5.], [2., 3., -5.], [2., 3., 5.], [2., 0., 5.]]
    raw = {"nav": {"nodePositions": [[0., 0., -2.], [0., 0., 2.]],
                   "nativePortals": []}, "start": {"face": 0, "position": [0., 0., -2.]},
           "collision": {"vertices": floor + wall,
                         "triangles": [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]]}}
    link = {"from": 0, "to": 1, "points": raw["nav"]["nodePositions"],
            "kind": "door", "seconds": 4 / 6, "enemy": True,
            "enemySeconds": 4 / 3.6, "source": {"type": "joined-source-npcdoorhint"}}
    doors = {"doors": [{"id": "source-door", "aperture": {
        "origin": [0., 0., 0.], "normal": [0., 0., 1.], "right": [1., 0., 0.],
        "up": [0., 1., 0.], "halfWidth": 1., "height": 3.}}], "links": [link]}
    opened = ArenaScene(raw, native=False, doors=doors)
    closed = opened.with_door_sight("closed")
    assert opened.path(0, 1, "enemy")[0].kind == "door"
    searches=opened.metrics["pathSearches"]
    assert opened.path(0, 1, "enemy")[0].kind=="door"
    assert opened.metrics["pathSearches"]==searches
    closed.disabled.add("0:1:door")
    assert closed.path(0,1,"enemy")==[] and opened.path(0,1,"enemy")
    closed.disabled.clear()
    assert closed.path(0,1,"enemy")[0].kind=="door"
    assert closed.check_motion(link["points"], ground_step=True)["clear"]
    assert opened.visible((0., 1., -2.), (0., 1., 2.))
    assert not closed.visible((0., 1., -2.), (0., 1., 2.))
    assert closed.raycast((0., 1., -2.), (0., 0., 1.), 4.).source["doorId"] == "source-door"
    assert closed.all_hits((0., 1., -2.), (0., 0., 1.), 4.)[0].triangle == -1
    assert closed.visible((1.5, 1., -2.), (1.5, 1., 2.))  # finite aperture only
    assert not opened.visible((1.5, 1., 0.), (3., 1., 0.))  # ordinary wall remains
    closed.disabled.add("job-local")
    assert not opened.disabled and opened.door_sight == "open"
    ground = {"support": {"vertices": [[x, .2, z] for x, _, z in floor],
                          "triangles": [[0, 1, 2], [0, 2, 3]],
                          "triangleSources": [{"sourceMesh": "verified-source-floor"}] * 2}}
    supported = ArenaScene(raw, native=False, doors=doors, ground=ground)
    assert supported.ground_support((0., 0., -2.)).position == pytest.approx((0., .2, -2.))
    gap={**link,"kind":"npc-short-gap","enemy":False}
    jumping=ArenaScene(raw,native=False,npc_gaps={"links":[gap]})
    assert not jumping.path(0,1,"enemy") and not jumping.path(0,1,"player")
    assert jumping.path(0,1,"enemy-gap")[0].kind=="npc-short-gap"
    # Source-admitted steep NAV remains valid for its own walk; a nearby
    # CSG face must never inherit that exemption or have its normal rewritten.
    slope=[[x,1.75*z,z] for x,_,z in floor]
    steep={**raw,"nav":{**raw["nav"],"vertices":slope,"triangles":[[0,1,2],[0,2,3]]},
           "collision":{"vertices":wall+slope,"triangles":[[0,1,2],[0,2,3],[4,5,6],[4,6,7]]}}
    slope_scene=ArenaScene(steep,native=False)
    foot=slope_scene.ground_support((0.,0.,0.))
    assert foot.normal[1]<.5 and slope_scene.source_nav_support(foot,{0,1})
    assert not slope_scene.source_nav_support(foot,set())
    wall_hit=slope_scene.raycast((0.,2.,0.),(1.,0.,0.),3.)
    assert not slope_scene.source_nav_support(wall_hit,{0,1})


def test_defense_schedule_cumulative_merge_quotas_and_cap_shortfall():
    from wfarsenal.arena import World, normalize_scenario
    from wfarsenal.arena_spawns import (defense_tier, defense_wave_parameters,
                                        defense_enemy_level, build_defense_schedule)

    assert [defense_tier(w) for w in (1, 2, 3, 5, 6, 12, 15, 100)] == [0, 0, 1, 1, 2, 4, 5, 5]
    assert defense_enemy_level(20, 160, arbitration=True) == 171
    assert defense_enemy_level(5, 10, max_level=20) == 15
    # Native float32 multiplication lands exactly on integral22; Python
    # double with a rounded2.2f would incorrectly ceil it to23.
    params = defense_wave_parameters(1, 4, 30)
    assert (params["maxAlive"], params["requestedTotal"]) == (29, 61)
    assert defense_wave_parameters(1, 4, 30, arbitration=True)["requestedTotal"] == 49
    assert defense_wave_parameters(2, 1, 30)["requestedTotal"] == 22
    # Same agent unlocked in another tier adds its source weight and cap;
    # the schedule does not replace all previous tiers with the latest one.
    pool = [dict(agent="A", tier=0, probability=1, maxSimultaneous=2, xp=10),
            dict(agent="A", tier=1, probability=2, maxSimultaneous=1, xp=10),
            dict(agent="B", tier=0, probability=3, maxSimultaneous=0, xp=100)]
    before = deepcopy(pool)
    result = build_defense_schedule(pool, 12, 4, lambda: 0.5)
    assert result["scheduledTotal"] == 12
    assert result["counts"] == {"A": 6, "B": 6}
    merged = next(row for row in result["quotas"] if row["agent"] == "A")
    assert merged["tiers"] == [0, 1] and merged["maxSimultaneous"] == 3
    assert pool == before

    # A symbol group's source tiers disappear in P14. Different source
    # weights affect the combined quota, while member selection is uniform.
    symbol_pool = [dict(agent="A", tier=0, probability=9, maxSimultaneous=2, xp=10, mergeSymbol="s"),
                   dict(agent="B", tier=1, probability=1, maxSimultaneous=1, xp=10, mergeSymbol="s")]
    values = iter([0.5] + [v for member in (0.9, 0.1, 0.9, 0.1)
                           for v in (member, 0.0, 0.0, 0.0, 0.0)])
    result = build_defense_schedule(symbol_pool, 4, 2, lambda: next(values))
    assert len(result["quotas"]) == 1
    assert result["counts"] == {"A": 2, "B": 2}
    assert result["quotas"][0]["maxSimultaneous"] == 2

    # Positive caps can shrink a wave; no synthetic fill-to-N is allowed.
    result = build_defense_schedule(pool[:1], 12, 8, lambda: 0.5)
    assert result["scheduledTotal"] == 3
    assert result["spacing"] == [4]
    assert result["requestedTotal"] == 12

    # Boss rows append after regular sorting and displace early ordinary rows;
    # a low-XP boss must not be sorted back into those trimmed early slots.
    bosses = [dict(agent="Boss", tier=9, probability=0.01, maxSimultaneous=2,
                   xp=1, eximusXp=1)]
    before = deepcopy(bosses)
    result = build_defense_schedule(pool[2:], 6, 4, lambda: 0.5, boss_entries=bosses)
    assert result["scheduledTotal"] == 6 and result["trimmed"] == 2
    assert result["counts"] == {"B": 4, "Boss": 2}
    assert result["bossCount"] == 2
    assert all(row["scheduledBoss"] and row["scheduledEximus"]
               for row in result["entries"][-2:])
    assert result["bossQuota"]["tiers"] == [9] and bosses == before

    world = World.__new__(World)
    world.c = normalize_scenario({"spawnProfile": "defense", "level": 30, "waveWait": None})
    assert world.c["waveWait"] == 6
    assert normalize_scenario({"spawnProfile": "arbitration"})["waveWait"] == 3
    assert normalize_scenario({"spawnProfile": "defense", "waveWait": 3})["waveWait"] == 3
    world.t, world.wave, world.boss_spawn_wave = 0.0, 2, 0
    world.interception, world.source_spawns = False, True
    world.replay, world.diagnostics = {"waves": []}, []
    world.spec_entries = world.raw_spec_entries = pool[:1] + bosses
    world.spawn_random = lambda: 0.5
    world.start_wave()
    wave = world.replay["waves"][0]
    assert (wave["requestedTotal"], wave["targetCount"], wave["rushCount"]) == (23, 6, 1)


    from wfarsenal.arena_spawns import interception_parameters, interception_enemy_level
    low = interception_parameters(1, 1, 0, .5, 30, 40)
    high = interception_parameters(3, 4, 1, .5, 30, 40)
    middle = interception_parameters(1, 2, .5, .5, 30, 40)
    assert (low["stage"], low["tier"], low["maxAlive"], low["initialCount"]) == (2, 0, 7, 0)
    assert (high["stage"], high["tier"], high["maxAlive"], high["minSquad"], high["defaultDelay"]) == (3, 2, 29, 4, 1)
    assert (middle["stage"], middle["minSquad"], middle["maxSquad"], middle["defaultDelay"]) == (3, 3, 4, 3)
    assert interception_enemy_level(2, 30, 0) == 36


def test_arbitration_drone_opportunities_keep_ordinary_quota_and_respect_cap(monkeypatch):
    from types import SimpleNamespace
    from wfarsenal.arena import World, Actor, DRONE

    world=World.__new__(World)
    world.c={"spawnProfile":"arbitration","squadSize":1,"directorHardCap":40};world.t=0.
    world.drone_timer_reset=0.;world.drone_force=False;world.generated=7
    anchor=Actor(0,0,(0.,0.,0.));world.live=[anchor]
    world.enemies={DRONE:{"path":DRONE}};world.stats={}
    world.scene=SimpleNamespace(nodes=((0.,0.,0.),(2.,0.,0.),(-2.,0.,0.)),
                                check_motion=lambda *a,**k:{"clear":True})
    def spawn(enemy,point,*,drone=False):
        actor=Actor(len(world.live),point["face"],world.scene.nodes[point["face"]],drone,tape={})
        world.live.append(actor)
        return actor
    world._spawn_actor=spawn;world.spawn_random=lambda:.9
    world.arbitration_drone(anchor)
    assert world.live==[anchor]  # timer==0 is not the strict expired condition
    world.t=.25;world.arbitration_drone(anchor)
    assert len(world.live)==2 and world.live[0] is anchor and world.generated==7
    assert world.drone_timer_reset==30.25 and world.live[1].tape["spawnAnchor"]==0
    world.spawn_random=lambda:.1;world.t=1.;world.arbitration_drone(anchor)
    assert len(world.live)==2 and world.drone_timer_reset==30.25  # one-person cap
    world.live.pop();world.arbitration_drone(anchor)
    assert len(world.live)==2 and world.drone_timer_reset==31.  #20% remains active during timer

    # Spawn callbacks upgrade the template: +400% health, unchanged shields,
    # status immunity. Hits remain valid but cannot trigger proc-based arcanes.
    from wfarsenal import arena_combat
    st=stats(damage_types={"DT_IMPACT":10.},status_chance=3.,magazine=20.)
    monkeypatch.setattr(arena_combat,"prepare",lambda *a,**k:dict(
        resolve=lambda *args:(st,None),trigger_sources=[dict(
            id="proc",kind="on-proc",maxStacks=99,duration=10.,perEvent=1.)],
        empowered=dict(damage=1000.,uptime=1.)))
    world.combat=arena_combat.ArenaCombat({})
    world.actors={};world.live=[];world.replay={"actors":[]};world.wave_level=1
    world.stats={};world.t=0.;world.diagnostics=[]
    enemy={**target(35.),"path":DRONE,"shield":50.}
    actor=World._spawn_actor(world,enemy,{"face":0},drone=True)
    victim=world.combat.targets[actor.id]
    assert victim.full==[0.,50.,175.] and victim.defenses["health"]==175.
    assert actor.tape["statusImmune"] and actor.tape["healthMultiplier"]==5.
    shot=world.combat.prepare_shot(0.,False,actor.id)
    world.combat.hit(shot,actor.id);world.combat.finish_shot(shot)
    assert 0. < victim.shield < 50. and victim.health==175.
    assert not victim.presence and world.combat.sources[0]["stacks"]==0.
    assert world.combat.empowered_count==0.
    source=dict(agent="source-hover",tier=0,resolvedAvatarPath="ordinary-hover",
                movement=dict(profile="hover",smallHoverCompatible=True))
    flyer=World._spawn_actor(world,{**target(35.),"path":"ordinary-hover"},{"face":1},source=source)
    assert flyer.aerial and not flyer.drone
    assert world.combat.targets[flyer.id].health==35. and not world.combat.targets[flyer.id].status_immune

    # Death blast retains player source but no weapon, so it cannot grant a
    # weapon on-kill buff. A second drone still protects ordinary recipients.
    from wfarsenal.arena_combat import ArenaCombat
    monkeypatch.setattr(arena_combat,"prepare",lambda *a,**k:dict(
        resolve=lambda *args:(st,None),trigger_sources=[dict(
            id="kill",kind="on-kill",maxStacks=9,duration=10.,perEvent=1.)]))
    world.combat=ArenaCombat({});world.actors={};world.live=[]
    world.replay={"actors":[],"combat":[],"kills":[]};world.c["seed"]=1
    world.stats=dict(kills=0,droneKills=0,vitusExpected=0.,vitusSample=0)
    world.scene.visible=lambda *args:True
    first=World._spawn_actor(world,enemy,{"face":0},drone=True)
    second=World._spawn_actor(world,enemy,{"face":1},drone=True)
    ordinary=World._spawn_actor(world,{**target(1e5),"path":"ordinary"},{"face":2})
    world.protection()
    world.combat.drone_explosion(first.id,1e6,0.)
    world.drain()
    assert first.dead and not second.dead and world.stats["droneKills"]==1
    assert world.combat.targets[ordinary.id].health==1e5
    assert world.combat.sources[0]["stacks"]==0.
    # Nearby drone already damaged: a finite death chain unprotects the survivor.
    world.combat.targets[second.id].pools=[0.,0.,10.]
    third=World._spawn_actor(world,enemy,{"face":0},drone=True)
    world.combat.drone_explosion(third.id,1e6,0.)
    world.drain()
    assert second.dead and third.dead and world.stats["droneKills"]==3
    assert world.stats["vitusExpected"]==pytest.approx(.18)
    assert world.combat.targets[ordinary.id].health<1e5
    assert len([e for e in world.replay["combat"] if e["kind"]=="drone-explosion"])==3
    assert world.combat.sources[0]["stacks"]==0.

    # Planning in the spawn turn must see the aura, including for existing actors.
    world.c.update(seconds=1., wallSeconds=10.)
    world.cancelled=lambda:False
    world.start_wave=lambda:None
    world.wave_pending=False;world.wave_target=9;world.events=[]
    world.next_spawn=world.next_plan=0.;world.next_drone_maintenance=1.
    world.spawn=lambda:World._spawn_actor(world,enemy,{"face":0},drone=True)

    class PlanReached(Exception):
        pass

    def check_plan():
        assert world.combat.protected_ids=={ordinary.id}
        raise PlanReached

    world.plan=check_plan
    with pytest.raises(PlanReached):
        world.run()


def test_interception_squad_gate_keeps_delay_and_allows_soft_cap_overshoot():
    from wfarsenal.arena import World, Actor, normalize_scenario

    world = World.__new__(World)
    world.c = normalize_scenario({"spawnProfile": "interception", "level": 30, "seed": 1})
    world.t, world.wave = 0.0, 0
    world.interception = world.source_spawns = True
    world.spec_entries = [dict(agent="a", tier=0, probability=1., maxSimultaneous=0, resolvedAvatarPath="enemy")]
    world.replay, world.diagnostics = {"waves": []}, []
    world.start_wave()
    assert (world.squad_delay, world.next_spawn) == (0.0, 0.0)
    world.t = 30.0
    world.start_wave()
    assert (world.squad_delay, world.next_spawn) == (6.0, 36.0)

    world.c.update(squadSize=4, missionDifficulty=1.)
    world.start_wave()
    world.t, world.generated, world.initial_squad = 0., 26, 0
    world.stats={"spawnQueued":0,"peakAlive":0};world.spawn_random=lambda:.99
    world.scene=SimpleNamespace(nodes=tuple((i*2.,0.,0.) for i in range(40)))
    world.spawn_points=[{"face":i} for i in range(40)]
    world.live=[Actor(i,i,world.scene.nodes[i],tape={"sourceAgent":"a"}) for i in range(25)]
    world.actors={a.id:a for a in world.live}
    world.enemy={"path":"enemy"};world.enemies={"enemy":world.enemy}
    def spawn(enemy,point,**kw):
        actor=Actor(len(world.actors),point["face"],world.scene.nodes[point["face"]],tape={"sourceAgent":"a"})
        world.live.append(actor);world.actors[actor.id]=actor
        return actor
    world._spawn_actor=spawn;world.arbitration_drone=lambda anchor:None
    world.spawn()
    assert len(world.live)==30 and world.generated==31  # gate25+4<=29 permits all5
    def unexpected_draw():
        pytest.fail("a rejected replenishment must not consume a squad draw")

    world.spawn_random = unexpected_draw
    world.squad_delay=2.;world.t=2.;world.spawn()
    assert len(world.live)==30 and world.next_spawn==4. and world.squad_delay==2.
