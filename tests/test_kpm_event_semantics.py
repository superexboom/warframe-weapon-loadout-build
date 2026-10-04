from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.combat_replay import replay
from wfarsenal.proc_probability import FirstProcClock,StatusPresence,no_status_probability
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
    clock=FirstProcClock()
    clock.add(0.,.1)
    assert clock.strip(2.,1.)==pytest.approx(.05)
    clock=FirstProcClock();clock.add(0.,.5);clock.add(1.,.5)
    assert clock.strip(2.,1.)==pytest.approx(.5*.5+.25*.3)


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


@pytest.mark.parametrize('dtype,expected',[('DT_ELECTRICITY',1.),('DT_GAS',1.),('DT_FIRE',0.),('DT_POISON',0.)])
def test_only_head_landing_dots_can_trigger_weakpoint_kill_buffs(dtype,expected):
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
