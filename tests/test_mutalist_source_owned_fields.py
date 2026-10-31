"""Mutalist source-arrow fields: replacement, owner expiry, packet context and native parity."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from wfarsenal import manual_combat,combat_replay,native_replay
from wfarsenal.damage import Scenario,ModEffect
from tools.import_mutalist_cernos_swarm import WEAPON

@pytest.fixture
def prepare(monkeypatch):
    import app
    ref=deepcopy(manual_combat.reference())
    # Inline source contract keeps tests portable; the importer independently
    # validates hash-pinned evidence, source lifetime and callback fields.
    field=dict(damage={'toxin':3.},status_chance=1.,forcedProcs=['PT_POISONED'],crit_chance=0.,crit_multiplier=1.,
        tick_rate=2.,damageOnEnter=True,defaultEnabled=True,expiresWithSourceOwner=True,
        sourceOwnerLifetimeAfterEmbed_seconds=10.)
    ref['auditedAttacks'][WEAPON]['periodicTriggers']=[field]
    monkeypatch.setattr(manual_combat,'reference',lambda:ref)
    original=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON))
    def make(ms=1.,rate=.1,extra=(),magazine=100):
        w=deepcopy(original);w['magazineSize']=magazine;w['fireModes'][0]['magazineSize']=magazine
        fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
            ModEffect('WEAPON_FIRE_ITERATIONS','SET',ms),ModEffect('WEAPON_FIRE_RATE','SET',rate),*extra]
        fight=manual_combat.prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=Scenario()),[],[])
        stats,_=fight['resolve']('selected',{},0.)
        return fight,stats
    return make

def run(prepare,window=10.,health=1e12,enabled=False,**kwargs):
    fight,stats=prepare(**kwargs)
    previous=native_replay.ENABLED
    native_replay.ENABLED=enabled
    try:
        result=combat_replay.replay(stats,dict(health=health,shield=0.,overguard=0.,armour=0.,baseLevel=1),
            attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=not enabled)
    finally:native_replay.ENABLED=previous
    return result,fight,stats


def test_resolver_has_one_owner_and_independent_trigger_mod_context(prepare):
    fight,stats=prepare(ms=7.,extra=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_CRIT_CHANCE','SET',1.),ModEffect('WEAPON_PROC_CHANCE','SET',3.),
        ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.5,damage_type='DT_FIRE')])
    assert not hasattr(stats,'_lingering')
    embed,swarm=stats._source_owned_fields
    assert embed[0].multishot==swarm[0].multishot==1.
    assert swarm[0].crit_chance==0. and swarm[0].status_chance==1.
    assert swarm[0].damage_types=={'DT_GAS':9.}
    assert swarm[1:]==(2.,10.,2)
    assert embed[1:]==(1.,10.,1)

@pytest.mark.parametrize('window,expected',[(.01,[1,2]),(.5,[1,3]),(10.,[10,21])])
def test_enter_and_initial_periodic_are_separate_owner_expiry_excludes_endpoint(prepare,window,expected):
    result,_,_=run(prepare,window=window,rate=.01)
    assert result['shots']==1
    assert result['sourceOwnedFieldPackets']==expected
    assert result['sourceOwnedFieldActivations']==1
    assert all(row['time']<10 for row in result['sourceOwnedFieldTrace'])


def test_multishot_does_not_multiply_fields_or_embed(prepare):
    a,_,_=run(prepare,window=.01,ms=1.)
    b,_,_=run(prepare,window=.01,ms=7.)
    assert a['sourceOwnedFieldPackets']==b['sourceOwnedFieldPackets']==[1,2]
    assert b['directWindow']-11.==pytest.approx(7*(a['directWindow']-11.))


def test_replacement_invalidates_old_owner_callbacks_and_restarts_initial_zero_timer(prepare):
    result,_,_=run(prepare,window=2.1,rate=2.)
    assert result['shots']>=2
    assert result['sourceOwnedFieldActivations']==result['shots']
    trace=result['sourceOwnedFieldTrace']
    # Once token k+1 is active no callback from k can damage afterwards.
    assert [row['token'] for row in trace]==sorted(row['token'] for row in trace)
    assert result['staleComponents']>0
    assert result['sourceOwnedFieldPackets'][1]>=2*result['shots']
    assert result['sourceOwnedFieldPackets'][0]<=2*result['shots']


def test_direct_kill_cancels_old_owner_and_never_installs_field_on_new_generation(prepare):
    result,_,_=run(prepare,window=2.,rate=2.,health=1.)
    assert result['killEvents']==result['shots']
    assert result['sourceOwnedFieldPackets']==[]
    assert result['sourceOwnedFieldActivations']==0


def test_swarm_status_is_own_sc1_and_forced_poison_not_arrow_sc(prepare):
    result,_,_=run(prepare,window=.01)
    # Arrow/old embed proc chance SET0 above; one forced Embed poison and
    # swarm own SC1 + forcedPoison per each of its two packets.
    assert result['procCounts']['DT_POISON']==pytest.approx(5.)


@pytest.mark.parametrize('health,ms,rate,window',[(1e12,1.,.1,10.1),(1e12,7.,2.,2.1),(1.,7.,2.,2.),(450.,1.,.1,4.),(1000.,2.,1.,4.)])
def test_python_native_source_owned_counts_damage_status_and_generation_match(prepare,monkeypatch,health,ms,rate,window):
    if not getattr(native_replay.wfcore,'SOURCE_OWNED_FIELDS',0):pytest.skip('build source owner native core')
    expected,_,_=run(prepare,health=health,ms=ms,rate=rate,window=window,enabled=False)
    actual,_,_=run(prepare,health=health,ms=ms,rate=rate,window=window,enabled=True)
    for key in ['shots','directWindow','dotWindow','totalWindowDamage','killEvents','sourceOwnedFieldPackets','sourceOwnedFieldActivations','staleComponents']:
        assert actual[key]==pytest.approx(expected[key]),key
    assert actual['procCounts']==pytest.approx(expected['procCounts'])


def test_source_fields_requery_live_damage_but_keep_independent_status_and_crit(monkeypatch):
    import app
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    arcane=next(a for a in app.EXPORTS['arcanes'] if a['nameEn']=='Primary Merciless')
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)]
    fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=effects,
        scenario=Scenario(trigger_policy='emergent')),[],[(arcane,5,{})])
    q=fight['trigger_sources'][0];q.update(initialStacks=1.,initialDuration=.5)
    stats,_=fight['resolve']('selected',{q['id']:1.},0.);stats.fire_rate=.001
    embed,swarm=[field[0] for field in stats._source_owned_fields]
    assert 'source-owned-field-upgrades-snapshot-at-embed' not in fight['unsupported']
    assert swarm.crit_chance==0. and swarm.status_chance==1.
    assert swarm._live_hit_refresh({q['id']:0.},0.).total_damage==3.
    assert embed._live_hit_refresh({q['id']:0.},0.).total_damage==5.
    assert embed._live_hit_refresh({q['id']:0.},0.).crit_chance==embed.crit_chance
    # One surviving arrow: initial embed and two initial swarm contacts carry
    # Merciless; the .5s/1s swarm and 1s embed use the expired ordinary bucket.
    # Native IPS proportions quantize .90/.05/.05 to29/32,2/32,2/32.
    expected=stats.total_damage*33/32+embed.total_damage+2*swarm.total_damage+5.+2*3.
    fight['resolve']=lambda *_:(stats,None)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    result=combat_replay.replay(stats,dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1),
        attacks_per_second=.001,window_seconds=1.001,combat=fight,
        trigger_sources=fight['trigger_sources'],collect_timeline=False)
    assert result['directWindow']==pytest.approx(expected)
    assert result['sourceOwnedFieldPackets']==[2,4]
    assert native_replay.STATS['native']>before
    monkeypatch.setattr(native_replay.wfcore,'SOURCE_OWNED_FIELDS',1)
    assert not native_replay.supported(stats,dict(combat=fight,collect_timeline=False))


def test_attached_co_queries_current_charge_phase_and_independent_swarm_stays_separate(prepare,monkeypatch):
    fight,stats=prepare(rate=.1,extra=[ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.5)])
    first=stats._source_owned_fields[0][0]
    charged=first._live_hit_refresh({},1.,True)
    drawing=first._live_hit_refresh({},1.,False)
    assert charged.total_damage==210.  # 5 + .5*current full-charge source410
    assert drawing.total_damage==107.5  # 5 + .5*current normal source205
    assert first._live_hit_refresh({},.5,False).total_damage==56.25
    assert stats._source_owned_fields[1][0]._live_hit_refresh({},1.,False).total_damage==3.
    assert charged.delayed_radial_hit_event and not charged.radial_victim_crit
    # Force one real direct status, so the initial attached query has exactly
    # one type before its own forced Toxin; subsequent query has two types.
    stats.native_forced_procs={'DT_FREEZE':1.}
    fight['resolve']=lambda *_:(stats,None)
    sources=[dict(id='hit',label='hit',kind='on-hit',duration=10.,maxStacks=100.,perEvent=1.)]
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    reference=combat_replay.replay(stats,target,attacks_per_second=stats.fire_rate,window_seconds=1.001,
        combat=fight,trigger_sources=sources,collect_timeline=True)
    result=combat_replay.replay(stats,target,attacks_per_second=stats.fire_rate,window_seconds=1.001,
        combat=fight,trigger_sources=sources,collect_timeline=False)
    assert result['directWindow']==pytest.approx(stats.total_damage*33/32+210.+210.+4*3.)
    assert reference['triggerSeries'][0]['series'][-1]==3.  # direct + two attached ticks
    assert native_replay.STATS['native']>before


@pytest.mark.parametrize('element,expected',[('DT_FIRE',{'DT_GAS':4.8}),('DT_POISON',{'DT_POISON':4.8})])
def test_canonical_ordinary_elements_apply_to_source_trigger(prepare,element,expected):
    fight,stats=prepare(extra=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.6,damage_type=element)])
    assert stats._source_owned_fields[1][0].damage_types==pytest.approx(expected)


def test_unsupported_element_labels_do_not_silently_gain_swarm_only_permissions(prepare):
    alias,element='WEAPON_FIRE_DAMAGE','DT_FIRE'
    from wfarsenal.damage import SUPPORTED_WEAPON_UPGRADE_TYPES,_apply_mods_spec_py
    import app
    assert alias not in SUPPORTED_WEAPON_UPGRADE_TYPES
    w=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    effect=ModEffect(alias,'ADD',.6,damage_type=element)
    direct,_=_apply_mods_spec_py(w,[effect],scenario=Scenario())
    assert alias in direct.unsupported
    _,stats=prepare(extra=[effect])
    assert stats._source_owned_fields[1][0].damage_types=={'DT_POISON':3.}


def test_run_restores_native_enabled_global(prepare):
    before=native_replay.ENABLED
    run(prepare,window=.01,enabled=not before)
    assert native_replay.ENABLED is before



def test_actual_production_manual_scalar_search_and_native_health_batch_agree(monkeypatch):
    import app
    from wfarsenal import search_combat
    from collections import OrderedDict
    from wfarsenal.damage import apply_mods
    # No source/contract monkeypatch: read the actual merged production data.
    entry=manual_combat.reference()['auditedAttacks'][WEAPON]
    assert entry['periodicTriggers'][0]['defaultEnabled']
    assert entry['periodicTriggers'][0]['sourceOwnerLifetimeAfterEmbed_seconds']==10.
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    weapon=app.optimizer._select_fire_mode(weapon,0,weapon_type=app.optimizer._weapon_type(None,weapon))[0]
    scenario=Scenario(trigger_policy='emergent')
    effects=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2),
             ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.6,damage_type='DT_ELECTRICITY'),
             ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.8)]
    stats=apply_mods(weapon,effects,scenario=scenario)
    app.optimizer._bind_combat_inputs(stats,weapon,(),effects,scenario)
    context=dict(target=dict(health=10000.,shield=0.,overguard=0.,armour=100.,baseLevel=1),level=1,windowSeconds=4.,headshotChance=0.)
    contexts=[app.optimizer._with_health_scale(context,scale) for scale in (1.,.3,2.,.3)]
    monkeypatch.setattr(search_combat,'_REPLAYS',OrderedDict())
    monkeypatch.setattr(native_replay,'ENABLED',False)
    expected=[search_combat.window(stats,c,score_only=True) for c in contexts]
    search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
    monkeypatch.setattr(native_replay,'ENABLED',True)
    if not getattr(native_replay.wfcore,'SOURCE_OWNED_FIELDS',0):pytest.skip('native source owner build required')
    before=native_replay.HEALTH_BATCH_STATS['runs']
    batched=search_combat.windows(stats,contexts)
    assert batched is not None and native_replay.HEALTH_BATCH_STATS['runs']==before+4
    for actual,reference in zip(batched,expected):
        assert actual['totalWindowDamage']==pytest.approx(reference['totalWindowDamage'],abs=1e-8)
        assert actual['killsPerMinute']==pytest.approx(reference['killsPerMinute'],abs=1e-8)
    fight=manual_combat.prepare(stats._combat_inputs['engine'],[],[])
    base,_=fight['resolve']('selected',{},0.)
    manual=combat_replay.replay(base,context['target'],attacks_per_second=base.fire_rate,window_seconds=4.,
        level=1,combat=fight,collect_timeline=False)
    assert manual['sourceOwnedFieldActivations']>0
    assert manual['totalWindowDamage']==pytest.approx(expected[0]['totalWindowDamage'],abs=1e-8)
    search_combat._REPLAYS.clear();stats._combat_scores.clear();stats._resolve_cache.clear()
    actual=search_combat.window(stats,context,score_only=True)
    assert actual['totalWindowDamage']==pytest.approx(manual['totalWindowDamage'],abs=1e-8)
