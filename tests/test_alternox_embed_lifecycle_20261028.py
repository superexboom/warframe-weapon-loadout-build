"""Alternox native attachment clock: immediate tick +1s; terminal blast once."""
from dataclasses import replace
from copy import deepcopy
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



def test_ordered_clock_contract_for_both_native_payloads(monkeypatch):
    # Two distinct source payloads; one manual tie and one natural expiry.
    monkeypatch.setattr(native_replay,"ENABLED",False)
    manual=run("Alternox",5.,5.12)
    assert manual['directWindow']==pytest.approx(49.999999+6*50+100)
    assert manual['manualDetonation']['events'][0]['time']==pytest.approx(5.1125)
    natural=run("Alternox Prime",20.,10.12)
    assert natural['directWindow']==pytest.approx(69.999999+11*70+140)
    assert natural['manualDetonation']['events'][0]['time']==pytest.approx(10.1125)
    assert run("Alternox",5.,5.01)['manualDetonation']['pendingMines']==1.
    assert getattr(native_replay.wfcore,'ALT_EMBEDDED_LIFECYCLE',0)>=2
    monkeypatch.setattr(native_replay,"ENABLED",True)
    monkeypatch.setattr(native_replay,"SHADOW",True)
    before=native_replay.STATS['native']
    run("Alternox Prime",20.,10.12,timeline=False)
    assert native_replay.STATS['native']>before


def test_fractional_batch_order_and_real_arcane_live_callback(monkeypatch):
    monkeypatch.setattr(native_replay,"ENABLED",False)
    result=run("Alternox",0.,.3,multishot=2.2)
    assert result['directWindow']==pytest.approx(2.2*(49.999999+50+100))
    events=result['manualDetonation']['events']
    assert [e['time'] for e in events]==pytest.approx([.1125,.162500001,.212500002])
    assert [e['expectedMines'] for e in events]==pytest.approx([1,1,.2])
    assert 'alternox-multishot-active-cap-unresolved' not in result['unsupported']
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Alternox')
    arcane=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Arcane Acceleration')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[
        ModEffect('WEAPON_CRIT_CHANCE','SET',1.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
        ModEffect('WEAPON_FIRE_ITERATIONS','SET',2.2)],scenario=Scenario(trigger_policy='emergent',detonation_delay_seconds=.5)),[],[(arcane,5,None)])
    stats,_=combat['resolve']('selected',{})
    assert stats._embedded[0].delayed_radial_hit_event
    assert callable(stats._embedded[0]._live_hit_refresh)
    value=combat_replay._reference_trajectory(stats,dict(health=1e12,armour=0.,shield=0.,overguard=0.,baseLevel=1),
        attacks_per_second=stats.fire_rate,window_seconds=.7,combat=combat,
        trigger_sources=combat['trigger_sources'],collect_timeline=True)
    # Direct, initial field, terminal event each notify; complete first batch.
    assert next(iter(value['timeline'][-1]['triggerStacks'].values()))>1-(1-.30000001)**2
    # Controlled source metadata: first direct forces Cold, each attached
    # packet forces Electricity. This isolates contact-time CO between slots.
    controlled=deepcopy(weapon)
    controlled['fireModes'][1]['damage']['forcedProcs']=['PT_CHILLED']
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
        ModEffect('WEAPON_FIRE_ITERATIONS','SET',2.2),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.5)]
    co=prepare(dict(weapon=controlled,fire_mode=1,effects=effects,
        scenario=Scenario(trigger_policy='emergent',detonation_delay_seconds=.5)),[],[])
    original=co['resolve']
    def forced_field(*args):
        direct,blast=original(*args)
        # Copy callback output as well; the production callback retains CC/CD.
        field=direct._embedded[0]
        out=deepcopy(direct)
        part=deepcopy(field);part.native_forced_procs={'DT_ELECTRICITY':1.}
        refresh=part._live_hit_refresh
        def field_refresh(stacks,live):
            refreshed=deepcopy(refresh(stacks,live));refreshed.native_forced_procs={'DT_ELECTRICITY':1.}
            return refreshed
        part._live_hit_refresh=field_refresh
        out._embedded=(part,*direct._embedded[1:])
        return out,blast
    co['resolve']=forced_field
    co_stats,_=forced_field('selected',{})
    # Direct slot1=50, field1=75 after Cold, direct/field2=100 after
    # Cold+Electricity, fractional final slot=(100+100)*.2:365 total.
    co_result=combat_replay._reference_trajectory(co_stats,
        dict(health=1e12,armour=0.,shield=0.,overguard=0.,baseLevel=1),
        attacks_per_second=co_stats.fire_rate,window_seconds=.1,combat=co,collect_timeline=True)
    assert co_result['directWindow']==pytest.approx(365.,abs=1e-4)
    assert getattr(native_replay.wfcore,'ALT_EMBEDDED_LIFECYCLE',0)>=2
    monkeypatch.setattr(native_replay,"ENABLED",True)
    monkeypatch.setattr(native_replay,"SHADOW",True)
    before=native_replay.STATS['native']
    run("Alternox",0.,.3,multishot=2.2,timeline=False)
    combat_replay.replay(stats,dict(health=1e12,armour=0.,shield=0.,overguard=0.,baseLevel=1),
        attacks_per_second=stats.fire_rate,window_seconds=.7,combat=combat,
        trigger_sources=combat['trigger_sources'],collect_timeline=False)
    compact=combat_replay.replay(co_stats,dict(health=1e12,armour=0.,shield=0.,overguard=0.,baseLevel=1),
        attacks_per_second=co_stats.fire_rate,window_seconds=.1,combat=co,collect_timeline=False)
    assert compact['directWindow']==pytest.approx(co_result['directWindow'])
    assert native_replay.STATS['native']>=before+3


def test_original_victim_retirement_and_legacy_capability_gate(monkeypatch):
    monkeypatch.setattr(native_replay,"ENABLED",False)
    for health in (25.,75.):
        result=run("Alternox",5.,.1,multishot=2.2,health=health)
        assert result['killEvents']==1
        assert result['totalWindowDamage']==health
        assert result['manualDetonation']['pendingMines']==0.
        assert result['manualDetonation']['detonations']==0
    monkeypatch.setattr(native_replay,"wfcore",SimpleNamespace(ABI=1,NATIVE_TYPE_QUANTIZATION=1,ALT_EMBEDDED_LIFECYCLE=1))
    monkeypatch.setattr(native_replay,"ENABLED",True)
    assert not native_replay.supported(None,dict(collect_timeline=False,
        combat={"resolve":lambda:None,"manualDetonation":{"impactThenEmbed":True}}))
