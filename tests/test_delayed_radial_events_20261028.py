"""Source-bound delayed damage notifications; original-byte evidence in trigger-routing."""
from copy import copy,deepcopy
import pytest
import app
from wfarsenal import delayed_radial_events as producers,native_replay
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay


def bound(name,critical=0.,delay=None,distance=None):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    combat=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario(distance=distance)),[],[])
    s,r=combat['resolve']('selected',{})
    def tune(st):
        out=copy(st)
        out.crit_chance=critical;out.status_chance=0.;out.multishot=1.;out.fire_rate=.001
        out.native_forced_procs={};out.independent_proc_chances={}
        return out
    s,r=tune(s),tune(r) if r is not None else None
    if delay is not None:r._impact_delay=delay
    combat['resolve']=lambda *_:(s,r)
    return s,r,combat

def target(health=1e8):
    return dict(health=health,armour=0.,shield=0.,overguard=0.,baseLevel=1,
                hitProxies=[dict(part='HEAD',damageAtten=3.,criticalMultiplier=2.)])

def sources():
    return [dict(id=k,label=k,kind=k,duration=100.,maxStacks=100.,perEvent=1.)
            for k in ['on-hit','on-crit','on-headshot','on-headshot-kill','on-kill']]

def run(monkeypatch,s,c,health=1e8,head=0.,window=2.,trigger_sources=None):
    monkeypatch.setattr(native_replay,'SHADOW',True)
    raw=[];original=native_replay.wfcore.trajectory
    def observe(*args):
        out=original(*args);raw.append(out);return out
    monkeypatch.setattr(native_replay.wfcore,'trajectory',observe)
    kw=dict(trigger_sources=trigger_sources or sources(),attacks_per_second=.001,window_seconds=window,headshot_chance=head)
    result=replay(s,target(health),combat=deepcopy(c),collect_timeline=False,**kw)
    reference=replay(s,target(health),combat=deepcopy(c),collect_timeline=True,**kw)
    assert raw,'must enter current native core'
    assert result['killsPerMinute']==pytest.approx(reference['killsPerMinute'])
    return raw[-1],reference

@pytest.mark.parametrize('name',['Zakti','Acceltra'])
def test_packet_notifies_generic_hit_and_crit_without_radial_head(monkeypatch,name):
    critical=.5
    s,r,c=bound(name,critical)
    assert c['delayedRadialEvents'] and r.delayed_radial_hit_event and not s.delayed_radial_hit_event
    raw,ref=run(monkeypatch,s,c)
    assert raw['sourceStacks']==pytest.approx([2.,critical*2,0.,0.,0.])
    assert ref['triggerSeries'][0]['series'][-1]==2.

def test_radial_has_no_head_hit_even_when_direct_is_head(monkeypatch):
    name='Kompressa'
    s,r,c=bound(name,1.)
    raw,_=run(monkeypatch,s,c,head=1.)
    assert raw['sourceStacks']==pytest.approx([2.,2.,1.,0.,0.])

def test_lethal_delayed_packet_notifies_once_before_victim_reset(monkeypatch):
    s,r,c=bound('Zakti')
    raw,_=run(monkeypatch,s,c,health=70.)
    assert raw['sourceStacks']==pytest.approx([2.,0.,0.,0.,1.])
    assert raw['kills']==1

def test_target_dead_from_base_hit_discards_attached_radial(monkeypatch):
    s,r,c=bound('Zakti')
    raw,_=run(monkeypatch,s,c,health=10.)
    assert raw['sourceStacks']==pytest.approx([1.,0.,0.,0.,1.])
    assert raw['kills']==1

def test_status_kill_before_radial_does_not_add_generic_or_weakpoint_hit(monkeypatch):
    s,r,c=bound('Zakti')
    s.damage_types={'DT_POISON':30.};s.native_forced_procs={'DT_POISON':1.}
    raw,_=run(monkeypatch,s,c,health=40.,head=0.,window=2.5)
    assert raw['kills']==1
    assert raw['totals'][1]>0
    assert raw['dotByType']['DT_POISON']>0
    assert raw['sourceStacks']==pytest.approx([1.,0.,0.,0.,1.])

@pytest.mark.parametrize('name',['Lenz','Sporothrix'])
def test_unclosed_delayed_producers_stay_unadmitted(name):
    w=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    s,r=c['resolve']('selected',{})
    assert not c['delayedRadialEvents']
    assert all(not p.delayed_radial_hit_event for p in [r,*getattr(r,'_additional_radials',())])

def test_unrelated_source_is_not_admitted_by_radial_shape():
    path,row=next(iter(producers.producers().items()))
    component=dict(nativeSource=path,nativeField=row['nativeField'],impact_delay_seconds=sum(row['nativeDelayRange'])/2)
    assert producers.admitted(component)
    component['nativeSource']='/unknown'
    assert not producers.admitted(component)


def test_old_native_core_is_rejected(monkeypatch):
    s,r,c=bound('Zakti')
    monkeypatch.setattr(native_replay.wfcore,'DELAYED_RADIAL_EVENTS',1)
    assert not native_replay.supported(s,dict(collect_timeline=False,combat=c))
    assert not native_replay.supported(r,dict(collect_timeline=False,combat=dict(resolve=c['resolve'])))


def test_delayed_lethal_packet_sees_old_victims_current_status(monkeypatch):
    s,r,c=bound('Zakti')
    s.native_forced_procs={'DT_PUNCTURE':1.}
    qs=sources()+[dict(id='gated',label='gated',kind='on-hit',victimProcType='DT_PUNCTURE',duration=100.,maxStacks=100.,perEvent=1.)]
    raw,_=run(monkeypatch,s,c,health=70.,trigger_sources=qs)
    assert raw['sourceStacks']==pytest.approx([2.,0.,0.,0.,1.,1.])


def test_radial_crit_uses_full_victim_and_body_multiplier(monkeypatch):
    s,r,c=bound('Zakti')
    s.damage_types={k:0. for k in s.damage_types}
    r.victim_full_crit_chance=1.
    r.bodyshot_crit_multiplier=.5
    raw,_=run(monkeypatch,s,c)
    assert raw['sourceStacks']==pytest.approx([2.,.5,0.,0.,0.])


def test_zero_damage_delayed_packet_does_not_notify(monkeypatch):
    s,r,c=bound('Zakti')
    r.damage_types={k:0. for k in r.damage_types}
    raw,_=run(monkeypatch,s,c)
    assert raw['sourceStacks']==pytest.approx([1.,0.,0.,0.,0.])


@pytest.mark.parametrize('name,arcane_name', [('Zakti','Arcane Velocity'),('Acceltra','Arcane Acceleration')])
def test_real_arcane_can_start_from_audited_radial_crit(monkeypatch,name,arcane_name):
    # Keep the exported Arcane condition/chance/effects. Isolate an initial
    # noncritical contact and critical later packet to prove the actual buff
    # consumer receives the newly admitted notification, not only a counter.
    from wfarsenal.damage import ModEffect
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    arcane=next(a for a in app.EXPORTS['arcanes'] if a['nameEn']==arcane_name)
    fight=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),
                  [],[(arcane,5,{})])
    resolver=fight['resolve']
    def resolve(form,stacks,*args):
        direct,radial=resolver(form,stacks,*args)
        direct=copy(direct);radial=copy(radial)
        direct.fire_rate=.001;direct.crit_chance=0.;radial.crit_chance=1.
        for part in (direct,radial):
            part.status_chance=0.;part.multishot=1.;part.native_forced_procs={}
            part.independent_proc_chances={}
        return direct,radial
    fight['resolve']=resolve;stats,_=resolve('selected',{},0.)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    result=replay(stats,target(),combat=fight,trigger_sources=fight['trigger_sources'],
                  attacks_per_second=.001,window_seconds=2.,collect_timeline=True)
    series=[row for row in result['triggerSeries'] if arcane['path'] in row['id']]
    assert series and max(series[0]['series'])>0
    assert result['shots']==1


def test_unarmed_acceltra_has_no_radial_notification(monkeypatch):
    s,r,c=bound('Acceltra',critical=1.,distance=5.)
    assert r is None
    raw,_=run(monkeypatch,s,c)
    assert raw['sourceStacks']==pytest.approx([1.,1.,0.,0.,0.])
