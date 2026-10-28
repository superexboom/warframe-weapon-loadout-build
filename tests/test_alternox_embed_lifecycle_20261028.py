"""Alternox native attachment clock: immediate tick +1s; terminal blast once."""
from dataclasses import replace
from types import SimpleNamespace
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal import combat_replay, native_replay


def configured(name="Alternox",delay=5.,multishot=1.,statuses=False):
    weapon=next(w for w in app.EXPORTS["weapons"] if w.get("nameEn")==name)
    fx=[] if statuses else [ModEffect("WEAPON_CRIT_CHANCE","SET",0.),ModEffect("WEAPON_PROC_CHANCE","SET",0.)]
    fx.append(ModEffect("WEAPON_FIRE_ITERATIONS","SET",multishot))
    scenario=Scenario(trigger_policy="emergent",detonation_delay_seconds=delay,detonation_batch_size=1)
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=fx,scenario=scenario),[],[])
    stats,_=combat["resolve"]("selected",{})
    # One projectile within the window, with normal engine damage parts.
    original=combat["resolve"]
    def resolve(*args):
        st,radial=original(*args)
        field=st._embedded
        st=replace(st,fire_rate=.01,magazine=100.)
        st._embedded=field
        return st,radial
    combat["resolve"]=resolve
    stats,_=resolve("selected",{})
    return stats,combat


def run(name,delay,window,*,timeline=True,multishot=1.,statuses=False,health=1e12,head=0.):
    stats,combat=configured(name,delay,multishot,statuses)
    return combat_replay.replay(stats,dict(health=health,armour=0.,shield=0.,overguard=0.,baseLevel=1),
                               attacks_per_second=stats.fire_rate,window_seconds=window,combat=combat,
                               trigger_sources=combat["trigger_sources"],collect_timeline=timeline,headshot_chance=head)


@pytest.mark.parametrize('name,direct,tick,blast',[("Alternox",49.999999,50.,100.),("Alternox Prime",69.999999,70.,140.)])
@pytest.mark.parametrize('delay,window,ticks,dead',[(5.,.1,1,False),(5.,1.01,2,False),(5.,4.99,5,False),
                                                   (5.,5.01,5,True),(20.,9.99,10,False),(20.,10.01,10,True),
                                                   (20.,12.,10,True),(0.,.01,1,True)])
def test_native_embed_damage_and_terminal_clock(name,direct,tick,blast,delay,window,ticks,dead):
    result=run(name,delay,window)
    assert result["shots"]==1
    assert result["directWindow"]==pytest.approx(direct+ticks*tick+(blast if dead else 0.))
    assert result["manualDetonation"]["detonations"]==int(dead)
    assert not result["procCounts"]


@pytest.mark.parametrize('name',["Alternox","Alternox Prime"])
@pytest.mark.parametrize('delay,window',[(0.,3.01),(2.5,4.1),(5.,5.01),(20.,10.01)])
@pytest.mark.parametrize('statuses',[False,True])
def test_python_native_lifecycle_scores_are_exact(name,delay,window,statuses,monkeypatch):
    if not getattr(native_replay.wfcore,"ALT_EMBEDDED_LIFECYCLE",0):pytest.skip('new core required')
    monkeypatch.setattr(native_replay,"SHADOW",True)
    result=run(name,delay,window,timeline=False,statuses=statuses)
    assert result["manualDetonation"]["detonations"]<=1


def test_old_native_core_falls_back_for_embed_lifecycle(monkeypatch):
    monkeypatch.setattr(native_replay,"wfcore",SimpleNamespace(ABI=1))
    monkeypatch.setattr(native_replay,"ENABLED",True)
    assert not native_replay.supported(None,dict(collect_timeline=False,
        combat={"resolve":lambda:None,"manualDetonation":{"impactThenEmbed":True}}))


def test_unresolved_multishot_capacity_is_visible_and_no_phantom_children(monkeypatch):
    monkeypatch.setattr(native_replay,"SHADOW",True)
    result=run("Alternox",5.,6.,timeline=False,multishot=2.)
    assert 'alternox-multishot-active-cap-unresolved' in result['unsupported']
    assert result['directWindow']==pytest.approx(49.999999+5*50.+100.)


def test_unverified_host_death_uses_explicit_conservative_generation_boundary(monkeypatch):
    monkeypatch.setattr(native_replay,"SHADOW",True)
    result=run("Alternox",5.,6.,timeline=False,health=75.)
    assert 'alternox-host-death-lifecycle-unverified' in result['unsupported']
    assert result['killEvents']==1
    assert result['totalWindowDamage']==75.


def test_live_field_is_counted_as_pending_then_released():
    assert run("Alternox",5.,4.99)["manualDetonation"]["pendingMines"]==1.
    assert run("Alternox",5.,5.01)["manualDetonation"]["pendingMines"]==0.


@pytest.mark.parametrize('name',["Alternox","Alternox Prime"])
@pytest.mark.parametrize('delay',[0.,.5,5.,20.])
def test_real_fire_cadence_and_live_status_feedback_native_parity(name,delay,monkeypatch):
    monkeypatch.setattr(native_replay,"SHADOW",True)
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    fx=[ModEffect('WEAPON_FIRE_DAMAGE','ADD',.6,damage_type='DT_FIRE'),
        ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',.6),
        ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2)]
    sc=Scenario(trigger_policy='emergent',detonation_delay_seconds=delay,detonation_batch_size=1)
    combat=prepare(dict(weapon=w,fire_mode=1,effects=fx,scenario=sc),[],[])
    st,_=combat['resolve']('selected',{})
    sources=[dict(id='hit',label='hit',kind='on-hit',duration=8.,maxStacks=8.,perEvent=1.)]
    value=combat_replay.replay(st,dict(health=1200.,armour=200.,shield=800.,overguard=1200.,baseLevel=1),
                              attacks_per_second=st.fire_rate,window_seconds=22.,combat=combat,trigger_sources=sources,
                              collect_timeline=False,headshot_chance=.5)
    assert value['totalWindowDamage']>0


def _acceleration_clipped_replay(multishot, window, *, native, monkeypatch):
    """Compare the chosen clipped-one policy using a real on-crit Arcane."""
    if native and not getattr(native_replay.wfcore, 'ALT_EMBEDDED_LIFECYCLE', 0):
        pytest.skip('new core required')
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Alternox')
    arcane = next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn') == 'Arcane Acceleration')
    effects = [ModEffect('WEAPON_CRIT_CHANCE', 'SET', 1.),
               ModEffect('WEAPON_PROC_CHANCE', 'SET', 0.),
               ModEffect('WEAPON_FIRE_ITERATIONS', 'SET', multishot)]
    scenario = Scenario(trigger_policy='emergent', detonation_delay_seconds=0.,
                        detonation_batch_size=1)
    combat = prepare(dict(weapon=weapon, fire_mode=1, effects=effects, scenario=scenario),
                     [], [(arcane, 5, None)])
    stats, _ = combat['resolve']('selected', {})
    source_id = combat['trigger_sources'][0]['id']
    source_stacks = {}
    if native:
        # The public native trajectory omits trace samples. Inspect the real
        # core's exported final sourceStacks instead of comparing empty series.
        original = native_replay.wfcore.trajectory
        def observed_core(*args, **kwargs):
            result = original(*args, **kwargs)
            source_stacks[source_id] = result['sourceStacks'][0]
            return result
        monkeypatch.setattr(native_replay.wfcore, 'trajectory', observed_core)
    runner = native_replay.trajectory if native else combat_replay._reference_trajectory
    result = runner(stats, dict(health=1e12, armour=0., shield=0., overguard=0., baseLevel=1),
                    attacks_per_second=stats.fire_rate, window_seconds=window, combat=combat,
                    trigger_sources=combat['trigger_sources'], collect_timeline=True)
    if not native:
        source_stacks = result['timeline'][-1]['triggerStacks']
    return result, source_stacks


@pytest.mark.parametrize('native', [False, True], ids=['python', 'native'])
def test_clipped_multishot_preserves_acceleration_trigger_probability(native, monkeypatch):
    with monkeypatch.context() as patch:
        baseline, baseline_stacks = _acceleration_clipped_replay(1., .01, native=native, monkeypatch=patch)
    with monkeypatch.context() as patch:
        clipped, clipped_stacks = _acceleration_clipped_replay(2.2, .01, native=native, monkeypatch=patch)
    assert baseline['shots'] == clipped['shots'] == 1
    assert baseline['directWindow'] == pytest.approx(clipped['directWindow'])
    # One direct crit plus one terminal blast crit, both from one projectile.
    expected = 1. - (1. - .30000001) ** 2
    assert next(iter(baseline_stacks.values())) == pytest.approx(expected)
    assert clipped_stacks == pytest.approx(baseline_stacks)


@pytest.mark.parametrize('native', [False, True], ids=['python', 'native'])
def test_clipped_multishot_preserves_accelerated_cadence_and_damage(native, monkeypatch):
    with monkeypatch.context() as patch:
        baseline, _ = _acceleration_clipped_replay(1., 1.5, native=native, monkeypatch=patch)
    with monkeypatch.context() as patch:
        clipped, _ = _acceleration_clipped_replay(2.2, 1.5, native=native, monkeypatch=patch)
    assert baseline['shots'] == 3
    assert clipped['shots'] == baseline['shots']
    assert clipped['directWindow'] == pytest.approx(baseline['directWindow'])
    assert clipped['totalWindowDamage'] == pytest.approx(baseline['totalWindowDamage'])
    assert 'alternox-multishot-active-cap-unresolved' in clipped['unsupported']


@pytest.mark.parametrize('native', [False, True], ids=['python', 'native'])
@pytest.mark.parametrize('health', [25., 75.], ids=['direct-kill', 'initial-field-kill'])
def test_generation_bound_embed_is_not_pending_after_instant_host_death(native, health):
    if native and not getattr(native_replay.wfcore, 'ALT_EMBEDDED_LIFECYCLE', 0):
        pytest.skip('new core required')
    stats, combat = configured(delay=5., statuses=False)
    runner = native_replay.trajectory if native else combat_replay._reference_trajectory
    result = runner(stats, dict(health=health, armour=0., shield=0., overguard=0., baseLevel=1),
                    attacks_per_second=stats.fire_rate, window_seconds=.1, combat=combat,
                    trigger_sources=combat['trigger_sources'], collect_timeline=False)
    assert result['shots'] == result['killEvents'] == 1
    assert result['totalWindowDamage'] == health
    assert result['manualDetonation']['detonations'] == 0
    # The declared generation-bound policy invalidates this attachment at t0;
    # no later periodic callback is needed to make the live pending count zero.
    assert result['manualDetonation']['pendingMines'] == 0.
