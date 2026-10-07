from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.combat_replay import replay
import itertools
import random
from wfarsenal.proc_probability import HeatChains,StatusPresence,no_status_probability,capped_stack_add,stack_alive,CappedPool,_arrival_kernel
from wfarsenal.beam_ramp import BeamRamp
from tests.test_combat_replay import stats,target,run


@pytest.mark.parametrize('kind',['on-headshot','on-hit','on-kill','on-headshot-kill'])
def test_magazine_refills_never_refill_active_incarnon_charge_pool(kind):
    base=stats(status_chance=0.,magazine=20.,fire_rate=10.)
    inc=replace(base,magazine=3.)
    def combat(restore):
        return dict(cycle={'hits':1.,'pool':3.,'enterSeconds':.1,'exitSeconds':.1},
            resolve=lambda form,*args:(base if form=='base' else inc,None),
            selectedIncarnon=False,magazineRestore=restore)
    plain=run(base,target(1.),combat=combat(None),headshot_chance=1.,window_seconds=2.)
    boosted=run(base,target(1.),combat=combat(dict(kind=kind,fraction=1.,chance=1.)),headshot_chance=1.,window_seconds=2.)
    assert boosted['transforms']==plain['transforms']>1
    assert boosted['shots']==plain['shots']
    assert boosted['killsPerMinute']==plain['killsPerMinute']


def test_fractional_expected_heat_is_not_a_guaranteed_strip_clock():
    heat=HeatChains()
    heat.add(0.,.9,.1,0.,6.,1.)
    assert heat.strip(2.)==pytest.approx(.05)
    heat=HeatChains();heat.add(0.,.5,.5,0.,6.,1.);heat.add(1.,.5,.5,0.,6.,1.)
    assert heat.strip(2.)==pytest.approx(.5*.5+.25*.3)


def test_fractional_heat_proc_does_not_refresh_every_world():
    # A 50% proc at 5 s refreshes the 0 s stack only in the worlds it lands.
    heat=HeatChains()
    heat.add(0.,.5,.5,0.,6.,1.);heat.add(5.,.5,.5,0.,6.,1.)
    heat.expire(7.)
    assert heat.count()==pytest.approx(.5*(1+.5))
    assert heat.alive()==pytest.approx(.5)
    heat.expire(11.5)
    assert not heat.active() and heat.count()==0.


def test_heat_chains_match_world_enumeration():
    rng=random.Random(7)
    times=sorted(rng.uniform(0,20) for _ in range(9))
    chances=[rng.uniform(.05,.9) for _ in times]
    seeds=[rng.uniform(1,3) for _ in times]
    heat=HeatChains()
    for t,c,v in zip(times,chances,seeds):heat.add(t,1-c,c,c*v,6.,1.)
    probe=times[-1]+2.5
    heat.expire(probe)
    count=seed=alive=0.
    for hits in itertools.product((0,1),repeat=len(times)):
        weight=1.;stacks=total=0.;last=None
        for t,c,v,h in zip(times,chances,seeds,hits):
            weight*=c if h else 1-c
            if not h:continue
            if last is None or t-last>6.:stacks=total=0.
            stacks+=1;total+=v;last=t
        if last is not None and probe-last<=6.:
            count+=weight*stacks;seed+=weight*total;alive+=weight
    assert heat.count()==pytest.approx(count)
    assert heat.seed()==pytest.approx(seed)
    assert heat.alive()==pytest.approx(alive)


@pytest.mark.parametrize('seed',range(12))
def test_incremental_heat_strip_equals_direct_sum(seed):
    rng=random.Random(seed);heat=HeatChains()
    grid=(None,.25,.5)[seed%3]
    pick=lambda hi:(round(rng.uniform(0,hi)/grid)*grid if grid else rng.uniform(0,hi))
    events=sorted([(pick(30),1) for _ in range(80)]+[(pick(40),0) for _ in range(200)])
    for t,kind in events:
        heat.expire(t)
        if kind:
            scale=rng.choice([1.,1.,.5])
            heat.add(t,0. if rng.random()<.05 else rng.uniform(.3,1),rng.uniform(0,1.5),1.,rng.choice([6.,3.])*scale,scale)
        else:
            assert heat.strip(t)==pytest.approx(heat.strip_full(t),abs=1e-12)


def test_capped_stacks_survive_by_probability_and_reduce_to_trimming_when_certain():
    items=[]
    for i in range(5):capped_stack_add(items,0.,1.,{'id':i},cap=3)
    assert [x['id'] for x in items if stack_alive(x)>0]==[2,3,4]
    chances=[.3,.8,.5,.6,.9];cap=2
    items=[]
    for i,c in enumerate(chances):capped_stack_add(items,1-c,c,{'id':i},cap=cap)
    alive={x['id']:x['count']*stack_alive(x) if 'count' in x else c*stack_alive(x) for x,c in ((x,chances[x['id']]) for x in items)}
    for i,c in enumerate(chances):
        exact=0.
        for hits in itertools.product((0,1),repeat=len(chances)):
            w=1.
            for h,q in zip(hits,chances):w*=q if h else 1-q
            if hits[i] and sum(hits[i+1:])<cap:exact+=w
        assert alive.get(i,0.)==pytest.approx(exact),i


@pytest.mark.parametrize('seed',range(8))
def test_capped_pool_is_exact_min_of_window_arrivals(seed):
    rng=random.Random(seed);cap=rng.choice([3,5,10]);pool=CappedPool(cap)
    arrivals=[];t=0.
    for step in range(40):
        t+=rng.uniform(0,.6)
        pool.expire(t)
        if rng.random()<.7:
            p=1. if rng.random()<.2 else rng.uniform(.1,1.)
            n=p*rng.choice([1.,1.,1.6,2.3])
            pool.add(t+4.,1-p,n);arrivals.append((t+4.,_arrival_kernel(1-p,n,99)))
            continue
        live=[k for end,k in arrivals if end>=t-1e-9]
        present=mean=0.
        for outcome in itertools.product(*live):
            w=1.;stacks=0
            for shift,weight in outcome:w*=weight;stacks+=shift
            present+=w*(stacks>=1);mean+=w*min(stacks,cap)
        got=pool.stats()
        assert got[0]==pytest.approx(present,abs=1e-12)
        assert got[1]==pytest.approx(mean,abs=1e-12)


def test_viral_first_stack_is_not_an_expected_count():
    pool=CappedPool(10)
    pool.add(6.,.5,.5);pool.add(6.,.5,.5)  # two coin flips: N in {0,1,2}
    present,mean=pool.stats()
    assert (present,mean)==(pytest.approx(.75),pytest.approx(1.))
    assert 1+.75*present+.25*mean==pytest.approx(.25*1+.5*2+.25*2.25)  # not 1 + E[N] = 2


def test_no_status_probability_respects_rolls_multishot_and_guaranteed_procs():
    st=stats(damage_types={'DT_FIRE':1.,'DT_VIRAL':1.},status_chance=.5,multishot=1.)
    assert no_status_probability(st,'DT_FIRE')==pytest.approx(.75)
    st=replace(st,multishot=2.)
    assert no_status_probability(st,'DT_FIRE')==pytest.approx(.75**2)
    st=replace(st,status_chance=1.,damage_types={'DT_FIRE':1.})
    assert no_status_probability(st,'DT_FIRE')==0.
    assert no_status_probability(replace(st,status_chance=0.),'DT_FIRE',{'DT_FIRE':1.})==0.


def test_co_presence_is_probability_and_expires_independently():
    presence=StatusPresence()
    presence.add(1.,.9);presence.add(2.,.9)
    assert presence.probability(.5)==pytest.approx(.19)
    assert presence.probability(1.5)==pytest.approx(.1)
    presence.add(2.,0.)
    assert presence.probability(1.6)==1.
    assert presence.probability(2.1)==pytest.approx(0.,abs=1e-12)


def test_beam_ramp_and_idle_decay_do_not_change_proc_count():
    beam=BeamRamp()
    values=[beam.tick(i*.1,.1) for i in range(8)]
    assert values[0]==.2 and values[6]==pytest.approx(1.)
    assert beam.tick(4.,.1)==.2
    st=stats(continuous=True)
    plain=run(st,window_seconds=1.,combat={'resolve':lambda *a:(st,None)})
    ramped=run(st,window_seconds=1.,combat={'resolve':lambda *a:(st,None),'beamRampFloors':{'selected':.2}})
    assert ramped['directWindow']<plain['directWindow']
    assert ramped['procCounts']==plain['procCounts']


@pytest.mark.parametrize('name',['Furis','MK1-Furis'])
def test_furis_incarnon_has_merged_beam_semantics_with_empty_native_trigger(name):
    from wfarsenal.damage import apply_mods
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    assert not apply_mods(w,[],fire_mode=0).continuous
    assert apply_mods(w,[],fire_mode=1).continuous


@pytest.mark.parametrize('name,floor',[('Amprex',.3),('Ignis Wraith',.35),('Kuva Nukor',.3),('Phantasma Prime',.15)])
def test_beam_floor_uses_exact_audited_weapon_profile(name,floor):
    from wfarsenal.manual_combat import prepare
    from wfarsenal.damage import Scenario
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    combat=prepare(dict(weapon=w,fire_mode=0,scenario=Scenario(),effects=[]),[],[])
    assert combat['beamRampFloors']['selected']==floor


@pytest.mark.parametrize('dtype,expected',[('DT_ELECTRICITY',0.),('DT_GAS',0.),('DT_FIRE',0.),('DT_POISON',0.)])
def test_dot_kills_never_trigger_weakpoint_kill_buffs(dtype,expected):
    # WFSim pellet.rs weakpoint_kill: only a direct weak-point hit that kills.
    st=stats(damage_types={dtype:1.},status_chance=1.,dot_base_damage=100.,fire_rate=.1)
    source=dict(id='weak-kill',label='Weakpoint kill',kind='on-headshot-kill',maxStacks=3.,perEvent=1.,duration=24.)
    result=run(st,target(15.),headshot_chance=1.,window_seconds=1.1,trigger_sources=[source])
    assert result['killEvents']==1
    assert result['triggerSeries'][0]['series'][-1]==expected


def test_target_status_gate_uses_probability_instead_of_any_fractional_stack():
    st=stats(damage_types={'DT_ELECTRICITY':1.},status_chance=.1,fire_rate=10.)
    source=dict(id='shock-hit',label='Shock gated hit',kind='on-hit',maxStacks=3.,
                perEvent=.4,duration=2.,victimProcType='DT_ELECTRICITY')
    result=run(st,target(),window_seconds=.11,time_step=.05,trigger_sources=[source],
               combat={'resolve':lambda *a:(st,None)})
    assert result['shots']==2
    assert result['triggerSeries'][0]['series'][-1]==pytest.approx(.04)


def test_magnetic_break_electricity_is_visible_to_target_status_gate():
    st=stats(damage_types={'DT_MAGNETIC':100.},status_chance=1.,fire_rate=10.)
    source=dict(id='shock-hit',label='Shock gated hit',kind='on-hit',maxStacks=3.,
                perEvent=1.,duration=2.,victimProcType='DT_ELECTRICITY')
    result=run(st,{**target(),'overguard':250.},window_seconds=.6,trigger_sources=[source],
               combat={'resolve':lambda *a:(st,None)})
    assert result['magneticBreaks']
    assert result['triggerSeries'][0]['series'][-1]>0


def test_crit_spread_is_per_roll_tier_variance():
    from wfarsenal.proc_probability import crit_cv2
    st=stats(crit_chance=.5,crit_multiplier=2.)
    assert crit_cv2(st,0.)==pytest.approx(.25/2.25)
    assert crit_cv2(replace(st,multishot=2.),0.)==pytest.approx(.25/2.25/2)
    assert crit_cv2(replace(st,multishot=2.,continuous=True),0.)==pytest.approx(.25/2.25)
    assert crit_cv2(replace(st,crit_chance=1.),0.)==0.


def test_kill_attribution_spans_exact_crossing_to_damage_share():
    from wfarsenal.proc_probability import KillAttribution
    def attribution(direct_cv2,dot_cv2):
        a=KillAttribution(1.)
        for i in range(40):
            t=i*.1
            a.add(t,0.,10.,direct_cv2,1.,True)  # weak direct hit
            if i%10==9:a.add(t,0.,100.,dot_cv2,0.)  # one DoT lump per second
        return a
    # Zero spread keeps the expected path's killer.
    assert attribution(0.,0.).weak(3.9,60.)==0.
    # A lump far wider than the spread keeps killing almost every time.
    assert attribution(.01,.01).weak(3.9,60.)<.05
    # A wide spread with equal variance rates tends to the damage-flow share;
    # the lumpier source (more variance per second) takes more crossings.
    assert attribution(40.,4.).weak(3.9,60.)==pytest.approx(.5,abs=.05)
    assert attribution(40.,40.).weak(3.9,60.)<attribution(40.,4.).weak(3.9,60.)


def test_expected_crossing_time_is_continuous_across_a_shots_to_kill_step():
    from wfarsenal.proc_probability import KillAttribution
    def expected_kill_time(health, cv2=.3):
        a, dealt, t = KillAttribution(1., interval=1.), 0., 0.
        while True:  # one 100-damage hit per second until the expected path kills
            a.add(t, 0., 100., cv2, 0.)
            if dealt + 100. >= health:
                return t + a.crossing(t, health - dealt)[1]
            dealt += 100.; t += 1.
    # Health 200 dies on hit 2 (t=1), health 200.01 on hit 3 (t=2): one step
    # on the expected path, a continuous expected kill time once hits vary.
    below, above = expected_kill_time(199.99), expected_kill_time(200.01)
    assert above - below < .05
    assert expected_kill_time(150.) < below < expected_kill_time(250.)
    # Zero spread keeps the expected path's kill time.
    assert expected_kill_time(199.99, 0.) == 1. and expected_kill_time(200.01, 0.) == 2.


def test_kill_before_a_reload_does_not_move_the_next_life():
    # Beam hits until the magazine empties at 5.21 s, burn lumps at 5.25 and
    # 6.25 s, fire resumes at 6.3 s. Whichever lump kills, the next target is
    # first hit at 6.3 s: the renewal shift is ~0 on both sides of the step.
    from wfarsenal.proc_probability import KillAttribution
    def shift(kill_at_second_lump):
        a = KillAttribution(1., interval=.04)
        for i in range(24):
            a.add(4.29 + .04 * i, 0., 10., .3, 0., True)
        a.add(5.25, 0., 1000., .01, 0.)
        if kill_at_second_lump:
            a.add(6.25, 0., 1000., .01, 0.)
            return a.crossing(6.25, 1., resume=6.3)[1]
        return a.crossing(5.25, 999., resume=6.3)[1]
    assert abs(shift(True)) < .05 and abs(shift(False)) < .05


def test_uncertain_weakpoint_kill_feedback_branches_deterministically():
    st=stats(damage_types={'DT_FIRE':100.,'DT_IMPACT':100.},crit_chance=.5,crit_multiplier=3.,
             status_chance=1.,fire_rate=2.,dot_base_damage=300.)
    source=dict(id='dead',label='Deadhead',kind='on-headshot-kill',maxStacks=3.,perEvent=1.,duration=24.)
    def go(sources):
        return run(st,target(1500.),headshot_chance=1.,window_seconds=10.,trigger_sources=sources)
    first,again=go([deepcopy(source)]),go([deepcopy(source)])
    assert first['killBranches']['count']==16
    assert first['killsPerMinute']==again['killsPerMinute']
    assert 0<first['weakpointKillEvents']<first['killEvents']
    assert len(first['timeline'])==len(go([])['timeline'])
    assert 'killBranches' not in go([])
