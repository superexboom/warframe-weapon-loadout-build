"""Grimoire exact identity and source drift rejection for native overheat gate."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tools import import_grimoire_fire_gate as imp

@pytest.fixture
def source():
    state=dict(InstantOverheat=1,OverheatStyle='OS_PLATEAU',OverheatTime=45,ReduceOverheatAmount=1,OverheatCooldownModifier=1)
    weapon=dict(Behaviors=[{}, {'state:Type':imp.STATE,'state:LotusFireAndToggleStateBehavior':state,'fire:LotusWeaponProjectileFireBehavior':dict(IgnoreFireIterations=1,fireIterations=1)}],AddingChargesReducesOverheat=1,MaxCharges=0,AddCharges=[dict(Conditions=['PRIMARY_DIRECT_HIT'],NumCharges=1)])
    objects={imp.WEAPON:weapon,imp.STATE:{}}
    class Packages:
        entities={p:('',SimpleNamespace(attr=None)) for p in objects}
        def parent(self,p):return ''
        def resolve(self,p):return deepcopy(objects[p])
    return Packages(),weapon,dict(path=imp.WEAPON,fireModes=[{},dict(damage=dict(projectile=imp.PROJECTILE))])

def test_gate_keeps_spatial_payloads_excluded(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row);m=out['weapons'][imp.WEAPON]['1'];g=m['nativeFireGate']
    assert m['nativeFireCooldownSeconds']==45 and g['initiallyReady'] and not g['affectedByFireRate']
    assert g['primaryHitRecoverySeconds']==1 and not g['primaryRecoveryEnabledInSingleMode']
    assert 'radialDamage' not in m and 'sourcePayloads' not in m
    import pickle
    from wfarsenal.damage import Scenario
    assert pickle.dumps(Scenario(combat_state={'grimoireStrategy':'off','grimoireCoverageSeconds':3.,'grimoireExpiryDistance':0.})) == pickle.dumps(Scenario())
    selected=Scenario(combat_state={'grimoireStrategy':'single-occupant'})
    assert dict(selected.combat_state)=={'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':3.}
    assert pickle.dumps(selected)==pickle.dumps(Scenario(combat_state={'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':3.}))
    assert pickle.dumps(selected)!=pickle.dumps(Scenario())



def test_selected_alt_gate_ignores_fire_rate_and_multishot(monkeypatch):
    import app
    from wfarsenal import manual_combat, native_replay, combat_replay
    from wfarsenal.damage import ModEffect, Scenario
    from wfarsenal.event_profiles import base_profile
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==imp.WEAPON)
    assert base_profile(weapon,1)['nativeFireCooldownSeconds']==45.
    assert not base_profile(weapon,0).get('nativeFireCooldownSeconds')
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
             ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',2.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    fight=manual_combat.prepare(dict(weapon=deepcopy(weapon),fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=fight['resolve']('selected',{},0.)
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    def replay(window):
        return combat_replay.replay(stats,target,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False)
    before=native_replay.STATS['native']
    first=replay(44.9); second=replay(45.1)
    assert first['shots']==1 and second['shots']==2
    assert first['directWindow']==second['directWindow']==0.
    assert first['dotWindow']==second['dotWindow']==0.
    assert stats.multishot==1.
    assert native_replay.STATS['native']>before


def test_original_occupant_strategy_has_source_clock_and_selected_mode_identity(monkeypatch):
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.projectile_events import grimoire_strategy
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==imp.WEAPON)
    default=grimoire_strategy(weapon,1,{})
    assert default['noDirectContact'] and default['parts']==[]
    assert default['unsupported']==('grimoire-alt-select-coverage-strategy',)
    state=Scenario(combat_state={'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':3.,'grimoireExpiryDistance':2.}).combat_state
    contract=grimoire_strategy(weapon,1,state)
    selected,_=app.optimizer._select_fire_mode(weapon,1,weapon_type='pistol')
    assert grimoire_strategy(selected,0,state)==contract
    assert grimoire_strategy(weapon,0,state) is None
    changed=deepcopy(selected);changed['fireModes'][0]['damage']['types']={'DT_ELECTRICITY':351.}
    assert grimoire_strategy(changed,0,state) is None
    assert contract['sourceRawAttributesSha256']=='a384ff36bc51b96972d82f317e6258ff1f7bf52b0f1754b082437cdb979401ac'
    assert [p['impact_delay_seconds'] for p in contract['parts']]==[0.,1.,2.,6.]
    chain=contract['parts'][:3];expiry=contract['parts'][3]
    assert all(p['damage']=={'electricity':350.} and p['damageMultiplier']==.80000001 for p in chain)
    assert all(p['nativeHitType']==2 and p['takes_victim_crit'] and p['forcedProcs']==['PT_ELECTROCUTION'] for p in chain)
    assert all(not p['takes_condition_overload'] and p['takes_multishot'] is False and p['originalRecipientOnly'] for p in contract['parts'])
    assert expiry['damage']=={'electricity':250.} and expiry['__expiryDistance']==2.
    assert expiry['nativeHitType']==4 and not expiry['takes_victim_crit'] and expiry['forcedProcs']==[]
    assert grimoire_strategy(weapon,1,{'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':0.})['parts']==[]
    with pytest.raises(ValueError,match='must not exceed 6'):
        Scenario(combat_state={'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':6.1})

    from wfarsenal import manual_combat, combat_replay, native_replay
    from wfarsenal.damage import ModEffect
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
             ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,effects=effects,
        scenario=Scenario(combat_state={'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':6.,'grimoireExpiryDistance':0.})),[],[])
    stats,first=fight['resolve']('selected',{},0.)
    parts=(first,*first._additional_radials)
    assert stats.total_damage==0. and getattr(stats,'_no_enemy_contact',False)
    assert [p.total_damage for p in parts]==pytest.approx([280.]*6+[250.])
    assert all(p.multishot==1. and p.delayed_radial_hit_event for p in parts)
    sources=[dict(id=k,label=k,kind=k,maxStacks=100,duration=30)
             for k in ('on-fire','on-hit','on-crit','on-headshot')]
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    def run(victim,window):
        return combat_replay.replay(stats,victim,combat=fight,trigger_sources=sources,
            attacks_per_second=stats.fire_rate,window_seconds=window,time_step=.1)
    trace=run(target,6.1)
    assert trace['shots']==1 and trace['directWindow']==pytest.approx(1930.)
    final=trace['timeline'][-1]
    assert final['triggerStacks']==pytest.approx({'on-fire':1.,'on-hit':7.,'on-crit':0.,'on-headshot':0.})
    assert all(point['triggerStacks']['on-hit']==6. for point in trace['timeline'] if 5.<point['time']<6.)
    lethal=run({**target,'health':100.},6.1)
    assert lethal['killEvents']==1 and lethal['timeline'][-1]['triggerStacks']['on-hit']==1.
    assert lethal['directWindow']==pytest.approx(100.)
    checked=combat_replay.replay(stats,target,combat=fight,trigger_sources=sources,
        attacks_per_second=stats.fire_rate,window_seconds=6.1,collect_timeline=False)
    checked_lethal=combat_replay.replay(stats,{**target,'health':100.},combat=fight,trigger_sources=sources,
        attacks_per_second=stats.fire_rate,window_seconds=6.1,collect_timeline=False)
    assert checked_lethal['killEvents']==lethal['killEvents'] and checked_lethal['directWindow']==100.
    assert checked['directWindow']==trace['directWindow']
    assert native_replay.STATS['native']>before

    # A subunit native chain budget can suppress chain packets without removing
    # the single physical orb or its separately selected expiry.
    zero=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,effects=[*effects[:2],
        ModEffect('WEAPON_FIRE_ITERATIONS','SET',.2)],scenario=Scenario(combat_state={
        'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':6.})),[],[])
    no_chain,part=zero['resolve']('selected',{},0.)
    assert all(p.multishot==0. for p in (part,*part._additional_radials))
    empty=combat_replay.replay(no_chain,target,combat=zero,trigger_sources=sources,
        attacks_per_second=no_chain.fire_rate,window_seconds=6.1)
    assert empty['directWindow']==0. and empty['timeline'][-1]['triggerStacks']['on-hit']==0.
    assert empty['shots']==1 and empty['timeline'][-1]['triggerStacks']['on-fire']==1.
    budget_native_before=native_replay.STATS['native']
    empty_native=combat_replay.replay(no_chain,target,combat=zero,trigger_sources=sources,
        attacks_per_second=no_chain.fire_rate,window_seconds=6.1,collect_timeline=False)
    assert empty_native['directWindow']==0. and native_replay.STATS['native']>budget_native_before

    # Real Merciless and Crosshairs layers expire before the second chain.
    # Damage refreshes while CC remains the creation-time projectile bucket.
    from wfarsenal.damage import mod_effects
    merciless=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Secondary Merciless')
    crosshairs=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Galvanized Crosshairs')
    scenario=Scenario(trigger_policy='emergent',aiming=True,combat_state={
        'grimoireStrategy':'single-occupant','grimoireCoverageSeconds':2.})
    live=manual_combat.prepare(dict(weapon=weapon,fire_mode=1,
        effects=[*mod_effects(crosshairs,crosshairs['maxRank'],scenario),ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=scenario),[(crosshairs,crosshairs['maxRank'],{})],[(merciless,5,{})])
    active={q['id']:1. for q in live['trigger_sources']}
    for q in live['trigger_sources']:q.update(initialStacks=1.,initialDuration=.5)
    launched,first=live['resolve']('selected',active,0.)
    refreshed=first._live_hit_refresh({key:0. for key in active},0.)
    assert refreshed.total_damage<first.total_damage
    assert refreshed.crit_chance==first.crit_chance
    _,fresh=live['resolve']('selected',{key:0. for key in active},0.)
    assert fresh.crit_chance<first.crit_chance
    live['resolve']=lambda *_:(launched,first)  # One launch; each packet retains its original late-source callback.
    live_trace=combat_replay.replay(launched,target,combat=live,trigger_sources=live['trigger_sources'],
        attacks_per_second=launched.fire_rate,window_seconds=1.1)
    expected=(first.total_damage+refreshed.total_damage)*(1.+first.crit_chance*(first.crit_multiplier-1.))
    assert live_trace['directWindow']==pytest.approx(expected)


    live_native_before=native_replay.STATS['native']
    compact=combat_replay.replay(launched,target,combat=live,trigger_sources=live['trigger_sources'],
        attacks_per_second=launched.fire_rate,window_seconds=1.1,collect_timeline=False)
    assert compact['directWindow']==live_trace['directWindow']
    assert native_replay.STATS['native']>live_native_before
    from tools.audit_optimizer_events import evaluate_payload
    payload=dict(weapon=weapon['path'],fireMode=1,metric='killsPerMinute',mods=[],
        enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0.,
        triggerPolicy='emergent',combatState={'grimoireStrategy':'single-occupant',
        'grimoireCoverageSeconds':6.,'grimoireExpiryDistance':0.})
    evaluated=evaluate_payload(payload)
    assert evaluated['manual']==pytest.approx(evaluated['optimizer'],rel=1e-9)
    default=evaluate_payload({**payload,'combatState':{}})
    assert default['manual']==default['optimizer']==0.

    # Non-window scoring must not fall back to Arsenal350 or bounded event previews.
    selected_scenario=Scenario(combat_state={'grimoireStrategy':'single-occupant',
        'grimoireCoverageSeconds':6.,'grimoireExpiryDistance':0.})
    panel=app.optimizer.apply_mods(selected,effects,scenario=selected_scenario)
    app.optimizer._bind_combat_inputs(panel,selected,(),effects,selected_scenario)
    fake_preview={'totals':{'averageHit':{'minimum':1e9}}}
    assert app.optimizer._score(panel,'shotDamage',fake_preview)==pytest.approx(1930.)
    assert app.optimizer._metrics(panel,fake_preview)['sustainedDps']==pytest.approx(1930./45.)
    assert app.optimizer._score(panel,'burstDps')==pytest.approx(1930./6.)
    empty=app.simulate_manual_payload({**payload,'metric':'shotDamage','combatState':{}})
    assert empty['moddedStats']['totalDamage']==350.  # labelled source preview only
    assert empty['targetDamage']['perShot']==empty['targetDamage']['perHit']==empty['targetDamage']['firstShot']==empty['totalSustainedDps']==0.
    assert app._mod_gains_metric_value(empty,'shotDamage')==0.
    admitted=app.simulate_manual_payload({**payload,'metric':'shotDamage'})
    assert admitted['targetDamage']['perShot']==admitted['grimoireMetrics']['shotDamage']>0.
    assert admitted['grimoireMetrics']['sustainedDps']==pytest.approx(admitted['grimoireMetrics']['shotDamage']/45.)
    hornet=next(m for m in app.MANUAL_MODS if m['nameEn']=='Hornet Strike')
    gain=app.mod_gains_payload({**payload,'metric':'shotDamage','candidates':[hornet['path']],'targetSlot':0})
    assert gain['baseValue']==pytest.approx(admitted['grimoireMetrics']['shotDamage'],abs=.001)
    assert gain['gains'][hornet['path']]['gainPercent']==pytest.approx(220.)
    assert app._mod_gains_metric_value(admitted,'killsPerMinute')==admitted['benchmarkTimeline']['killsPerMinute']>0.
    assert app._mod_gains_metric_value(admitted,'windowedDps')==admitted['benchmarkTimeline']['windowDps']
