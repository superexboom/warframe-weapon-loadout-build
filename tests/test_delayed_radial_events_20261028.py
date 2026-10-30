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

@pytest.mark.parametrize('name,delay', [('Lenz',1.4125),('Sporothrix',1.01249998)])
def test_embedded_death_uses_final_type_and_post_embed_native_delay(monkeypatch,name,delay):
    s,r,c=bound(name,critical=1.)
    parts=[r,*getattr(r,'_additional_radials',())]
    delayed=parts[-1]
    delayed.crit_chance=1.;delayed.status_chance=0.;delayed.native_forced_procs={}
    assert delayed._impact_delay==pytest.approx(delay)
    assert c['delayedRadialEvents'] and delayed.delayed_radial_hit_event and delayed.radial_victim_crit
    raw,_=run(monkeypatch,s,c,window=delay+.001)
    # Actual source callbacks retain ordinary event qualification at late delivery.
    assert raw['sourceStacks'][0]==pytest.approx(1.+len(parts))


def test_unrelated_source_is_not_admitted_by_radial_shape():
    path,rows=next(iter(producers.producers().items()));row=rows[0]
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
    # Explicit recipient is PROJECTILE2 after +c24 overwrite: one Puncture
    # grants .05 crit, but never a head notification.
    assert raw['sourceStacks']==pytest.approx([2.,.05,0.,0.,1.,1.])


def test_radial_crit_uses_full_victim_without_body_part_multiplier(monkeypatch):
    s,r,c=bound('Zakti')
    s.damage_types={k:0. for k in s.damage_types}
    r.victim_full_crit_chance=1.
    r.bodyshot_crit_multiplier=.5
    raw,_=run(monkeypatch,s,c)
    assert raw['sourceStacks']==pytest.approx([2.,1.,0.,0.,0.])


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


def test_pox_attached_ticks_use_live_co_and_notify_once_per_tick(monkeypatch):
    from wfarsenal.damage import ModEffect
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Pox')
    effects=[ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',1.),
             ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)]
    c=prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=Scenario()),[],[])
    s,_=c['resolve']('selected',{},0.)
    s.fire_rate=.001;s.native_forced_procs={'DT_PUNCTURE':1.}
    part,rate,duration=s._lingering
    assert (rate,duration)==(1.,5.)
    assert part.delayed_radial_hit_event and not part.radial_victim_crit
    assert part.total_damage==20.  # launch had no victim statuses
    c['resolve']=lambda *_:(s,None)
    raw,ref=run(monkeypatch,s,c,window=1.001)
    # The contact applies Puncture before immediate/1s ticks. Each tick uses
    # its native 20 + parent-query 50 CO basis; no duplicate area hit on host.
    assert ref['directWindow']==pytest.approx(50.+2*(20.+50.))
    assert raw['sourceStacks']==pytest.approx([3.,0.,0.,0.,0.])

    # Real Galvanized Shot stacks expire during a surviving host's field. The
    # next tick must refresh the CO source bucket as well as victim statuses.
    from wfarsenal.damage import mod_effects
    mod=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Galvanized Shot')
    scenario=Scenario(trigger_policy='emergent')
    fx=[*mod_effects(mod,mod['maxRank'],scenario),*effects[1:]]
    fight=prepare(dict(weapon=weapon,fire_mode=0,effects=fx,scenario=scenario),[(mod,mod['maxRank'],{})],[])
    q=fight['trigger_sources'][0];q.update(initialStacks=1.,initialDuration=.5)
    launched,_=fight['resolve']('selected',{q['id']:1.},0.)
    launched.fire_rate=.001;launched.native_forced_procs={'DT_PUNCTURE':1.}
    coefficient=launched._lingering[0].co_bucket[0].value
    fight['resolve']=lambda *_:(launched,None)
    _,expired=run(monkeypatch,launched,fight,window=1.001,trigger_sources=[q,*sources()])
    assert expired['directWindow']==pytest.approx(50.+20.+50.*coefficient+20.)

    # Ordinary source damage is live too; the retained projectile crit bucket
    # is distinct. A real Secondary Merciless stack ends before the 1s tick.
    arcane=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Secondary Merciless')
    fight=prepare(dict(weapon=weapon,fire_mode=0,effects=effects[1:],scenario=scenario),[],[(arcane,5,{})])
    q=fight['trigger_sources'][0];q.update(initialStacks=1.,initialDuration=.5)
    launched,_=fight['resolve']('selected',{q['id']:1.},0.)
    launched.fire_rate=.001
    field=launched._lingering[0]
    retained=field.crit_chance
    refreshed=field._live_hit_refresh({q['id']:0.},0.)
    assert field.total_damage>refreshed.total_damage==20.
    assert refreshed.crit_chance==retained
    expected=launched.total_damage+field.total_damage+20.
    fight['resolve']=lambda *_:(launched,None)
    _,expired=run(monkeypatch,launched,fight,window=1.001,trigger_sources=[q,*sources()])
    assert expired['directWindow']==pytest.approx(expected)

    crosshairs=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Galvanized Crosshairs')
    aiming=Scenario(trigger_policy='emergent',aiming=True)
    fight=prepare(dict(weapon=weapon,fire_mode=0,effects=mod_effects(crosshairs,crosshairs['maxRank'],aiming),
        scenario=aiming),[(crosshairs,crosshairs['maxRank'],{})],[])
    active={q['id']:1. for q in fight['trigger_sources']};inactive={key:0. for key in active}
    fired,_=fight['resolve']('selected',active,0.);fresh,_=fight['resolve']('selected',inactive,0.)
    old_field=fired._lingering[0]
    assert old_field.crit_chance>fresh._lingering[0].crit_chance
    assert old_field._live_hit_refresh(inactive,0.).crit_chance==old_field.crit_chance


def test_attached_shiver_uses_native_parent_base_and_forced_matches_live(monkeypatch):
    from wfarsenal.damage import ModEffect,arcane_effects
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Pox')
    arcane=next(a for a in app.EXPORTS['arcanes'] if a['nameEn']=='Secondary Shiver')
    ordinary=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
              ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.4),
              ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)]
    def setup(override):
        sc=Scenario(trigger_policy='emergent')
        fx=[*ordinary,*arcane_effects(arcane,5,**override)]
        c=prepare(dict(weapon=weapon,fire_mode=0,effects=fx,scenario=sc),[],[(arcane,5,override)])
        st,_=c['resolve']('selected',{},0.);st.fire_rate=.001
        st.native_forced_procs={'DT_FREEZE':1.}
        c['resolve']=lambda *_:(st,None)
        return st,c
    # Pox's current field is40 after +100% ordinary damage. Native+818 adds
    # both CO and one Cold stack from parent50:40+50*(.4+.45)=82.5.
    st,c=setup({});raw,result=run(monkeypatch,st,c,window=.01)
    assert result['directWindow']==pytest.approx(100.+82.5)
    fixed,c=setup({'stacks':1,'uptime':1.})
    raw,forced=run(monkeypatch,fixed,c,window=.01)
    # Specified Cold also buffs the initial parent shot; the field's bracket
    # remains82.5, not raw20*.45 nor post-modified40*.45.
    assert forced['directWindow']-fixed.total_damage==pytest.approx(82.5)
