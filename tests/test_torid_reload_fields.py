from copy import copy,deepcopy
import pytest
import app
from wfarsenal.damage import Scenario,ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.runtime_adapters import verified_torid_field_duration
from tests.test_combat_replay import target
from tools.audit_optimizer_events import evaluate_payload

def weapon():
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Torid')

def branch():
    return next(b for t in weapon()['incarnon']['tiers'] for b in t['branches'] if b['id']=='3-2')

def combat(mode=0,cycle=False,choices=None):
    w=deepcopy(weapon());w['isIncarnonForm']=mode==1
    return prepare(dict(weapon=w,fire_mode=mode,effects=[],scenario=Scenario(trigger_policy='emergent',incarnon_cycle=cycle)),[],[],cycle_enabled=cycle,incarnon_choices=choices or {'tier3':'3-2'})

def test_raw_signature_controls_event_adapter_and_ui_description():
    b=branch();assert verified_torid_field_duration(b)['multiplier']==2
    assert app.optimizer._branch_effects(b)==([],[])
    ui=next(x for t in app._incarnon_options(weapon()) for x in t['options'] if x['id']=='3-2')
    assert ui['complete'] and not ui['unsupported']
    assert '完成换弹' in ui['description'] and '不延长异常状态' in ui['description']
    last=next(x for t in app._incarnon_options(weapon()) for x in t['options'] if x['id']=='2-1')
    assert last['complete'] and not last['unsupported']
    assert '额外 +3 多重射击' in last['description']
    assert any(row['modeled'] and '灵化弹池不触发' in row['calculation'] for row in last['details'])

@pytest.mark.parametrize('mutate',[
    lambda b:b.update(path='/unknown'),
    lambda b:b['runtimeScripts'][0]['apply'].update(Function='Unknown'),
    lambda b:b['runtimeScripts'][0]['apply'].update(_embedDurationMultiplier=3),
    lambda b:b['runtimeScripts'][0]['apply'].update(_emissionTimeDelta=1),
    lambda b:b['effects'][0].update(valuePerRank=1),
    lambda b:b.update(unresolvedReferences=['/unknown']),
])
def test_changed_signature_remains_unmodeled(mutate):
    b=deepcopy(branch());mutate(b)
    assert verified_torid_field_duration(b) is None
    assert app.optimizer._branch_effects(b)[1]

def simple_combat(enabled=True,ms=1):
    c=combat();base,_=c['resolve']('selected',{})
    st=copy(base);part=copy(base._lingering[0])
    st.fire_rate=1;st.magazine=2;st.reload_time=1;st.crit_chance=st.status_chance=0;st.multishot=ms
    part.crit_chance=part.status_chance=0;part.multishot=ms
    st._lingering=(part,1,10)
    c['resolve']=lambda *a:(st,None)
    if not enabled:c['fieldDurationOnEmptyReload']=None
    return c,st

def test_first_magazine_normal_only_first_shot_after_completed_reload_is_doubled():
    c,st=simple_combat();r=replay(st,target(),combat=c,attacks_per_second=1,window_seconds=5)
    assert r['fieldDuration']['events']==[
        dict(time=0.,form='selected',durationSeconds=10,multiplier=1.),
        dict(time=1.,form='selected',durationSeconds=10,multiplier=1.),
        dict(time=3.,form='selected',durationSeconds=20,multiplier=2.),
        dict(time=4.,form='selected',durationSeconds=10,multiplier=1.)]
    assert r['fieldDuration']['boostedShots']==1
    assert r['shots']==4 and r['reloads']==1

@pytest.mark.parametrize('ms',[1,2.5])
def test_extended_ticks_only_after_normal_expiry_and_multishot_does_not_consume_twice(ms):
    c,st=simple_combat(ms=ms);plain,pst=simple_combat(False,ms)
    short=replay(st,target(),combat=c,attacks_per_second=1,window_seconds=12.9)
    short_plain=replay(pst,target(),combat=plain,attacks_per_second=1,window_seconds=12.9)
    assert short['directWindow']==pytest.approx(short_plain['directWindow'])
    long=replay(st,target(),combat=c,attacks_per_second=1,window_seconds=13.1)
    long_plain=replay(pst,target(),combat=plain,attacks_per_second=1,window_seconds=13.1)
    assert long['directWindow']-long_plain['directWindow']==pytest.approx(40*ms)
    assert long['shots']==long_plain['shots'] and long['reloads']==long_plain['reloads']
    assert long['fieldDuration']['boostedShots']==4

def test_killing_direct_shot_consumes_charge_without_spawning_field_on_next_target():
    c,st=simple_combat();r=replay(st,target(hp=1),combat=c,attacks_per_second=1,window_seconds=4.1)
    assert r['fieldDuration']['boostedShots']==0 and not r['fieldDuration']['ready']
    assert not r['fieldDuration']['events']

def test_selected_incarnon_never_gets_final_fusillade_last_round_bonus():
    c=combat(mode=1,choices={'tier2':'2-1'})
    plain=c['resolve']('selected',{},0,False)[0]
    last=c['resolve']('selected',{},0,True)[0]
    assert plain.multishot==last.multishot

def test_cycle_base_magazine_last_round_is_detected_but_transform_never_arms_reload_field():
    c=combat(mode=1,cycle=True,choices={'tier2':'2-1','tier3':'3-2'})
    c['cycle']={**c['cycle'],'hits':10000}
    original=c['resolve'];seen=[]
    def resolve(form,stacks,live=0,last=False):
        st,rad=original(form,stacks,live,last)
        if form=='base':seen.append((last,st.multishot))
        return st,rad
    c['resolve']=resolve
    st,_=resolve('base',{})
    r=replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=6)
    assert any(last and ms>=4 for last,ms in seen)
    assert r['fieldDuration']['boostedShots']>=1
    c=combat(mode=1,cycle=True);c['cycle']={**c['cycle'],'hits':1,'pool':1}
    st,_=c['resolve']('base',{})
    switched=replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=10)
    assert switched['transforms']>=2 and switched['reloads']==0
    assert switched['fieldDuration']['boostedShots']==0

@pytest.mark.parametrize('mode,cycle',[(0,False),(1,True),(1,False)])
def test_selected_evolution_shared_by_manual_and_search_event_score(mode,cycle):
    w=weapon();p=dict(weapon=w['path'],fireMode=mode,mods=[],incarnonChoices={'tier2':'2-1','tier3':'3-2','tier4':'4-2'},incarnonCycle=cycle,aiming=True,enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0,triggerPolicy='emergent')
    r=evaluate_payload(p)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    manual=app.simulate_manual_payload(p)
    assert manual['benchmarkTimeline']['fieldDuration'] is not None
    assert not any('incarnon-3-2-runtime' in x or 'incarnon-3-2-NONE' in x for x in manual['unsupported'])


@pytest.mark.parametrize('mode,cycle',[(0,False),(1,True)])
def test_riven_candidate_recommendations_use_same_torid_event_context(mode,cycle):
    o=app.optimizer;w=o._select_fire_mode(weapon(),mode,weapon_type='rifle')[0]
    sc=Scenario(aiming=True,incarnon_cycle=cycle,trigger_policy='emergent')
    pool,_=o._candidate_mods(app.EXPORTS,w,sc)
    cards=[next(c for c in pool if c.record.get('nameEn')==name and c.record['path'] in app.MANUAL_MODS_BY_PATH) for name in ('Serration','Point Strike','Vital Sense')]
    choices={'tier2':'2-1','tier3':'3-2','tier4':'4-2'}
    passive,resolved,_,_=o._incarnon_card(w,choices,scenario=sc,metric='killsPerMinute')
    context=dict(target=app.MANUAL_ENEMIES_BY_PATH[app._BENCHMARK_ENEMY_PATH],level=9999,steel_path=True,windowSeconds=30,headshotChance=0)
    baseline=o._evaluate(w,cards,None,scenario=sc,metric='killsPerMinute',passives=passive,target_context=context)
    positive=o._wire_lines([dict(code=k,value=100,negative=False) for k in ('1','2','6')])[0]
    result=o.recommend_optimal_riven(w,baseline,positive,[],scenario=sc,metric='killsPerMinute',passives=passive,target_context=context,slot_count=3,min_fill=3,max_fill=3,budget_seconds=.5)
    assert result['combos']
    for row in result['combos']:
        b=row['build'];mods=[{k:m[k] for k in ('path','rank','slot')} for m in b['mods']]
        slots=[None]*8
        for m in mods:slots[m['slot']]=app.MANUAL_MODS_BY_PATH[m['path']].get('polarity')
        slots[b['riven']['slot']]=b['riven'].get('polarity','AP_ATTACK')
        p=dict(weapon=w['path'],fireMode=mode,incarnonCycle=cycle,aiming=True,incarnonChoices=resolved,mods=mods,riven=b['riven'],slotPolarities=slots,enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0,triggerPolicy='emergent')
        r=app.simulate_manual_payload(p)['benchmarkTimeline']
        assert row['score']==pytest.approx(r['killsPerMinute'],rel=1e-9)
        assert r['fieldDuration'] is not None
        if not cycle:assert r['fieldDuration']['boostedShots']>0


@pytest.mark.parametrize('metric',['killsPerMinute','sustainedDps','attackDps'])
def test_explicit_event_metric_riven_and_mod_contributions_replay_removal(metric):
    mod=next(m for m in app.MANUAL_MODS if m.get('nameEn')=='Serration')
    p=dict(weapon=weapon()['path'],fireMode=0,metric=metric,mods=[dict(path=mod['path'],rank=mod['maxRank'],slot=0)],
           riven=dict(slot=1,polarity='AP_ATTACK',stats=[dict(code='1',value=100,negative=False),dict(code='3',value=91.008,negative=True)]),
           slotPolarities=[mod['polarity'],'AP_ATTACK']+[None]*6,incarnonChoices={'tier2':'2-1','tier3':'3-2','tier4':'4-2'},
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0,aiming=True,triggerPolicy='emergent')
    app._MOD_GAINS_CACHE.clear()
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':['__riven__',mod['path']]})
    base=app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
    assert gains['metric']=='killsPerMinute' and base>0
    assert gains['baseValue']==pytest.approx(base,abs=.001)
    for key,overrides in [('__riven__',{'riven':None}),(mod['path'],{'mods':[]})]:
        value=app.simulate_manual_payload({**p,**overrides})['benchmarkTimeline']['killsPerMinute']
        assert value>0
        assert gains['gains'][key]['value']==pytest.approx(value,abs=.001)


def test_plentiful_mayhem_flat_base_stays_on_grenade_but_pool_bonus_follows_into_field():
    def parts(fx):
        c=prepare(dict(weapon=deepcopy(weapon()),fire_mode=0,effects=fx,scenario=Scenario(trigger_policy='emergent')),[],[])
        st,_=c['resolve']('selected',{});return st,st._lingering[0]
    mayhem=[ModEffect('WEAPON_DAMAGE_AMOUNT','ADD_BASE',31.),ModEffect('WEAPON_AMMO_POOL_MULTISHOT_DAMAGE','STACKING_MULTIPLY',.6)]
    shot,field=parts(mayhem)
    assert shot.total_damage==pytest.approx(131) and field.total_damage==pytest.approx(40)
    # Only the 0.9 generated grenades take +60%, in the shot and in the fields
    # they leave (WFSim torid_plentiful_mayhem: "follows a generated grenade
    # into the CLOUD").
    _,field=parts([*mayhem,ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',.9)])
    assert field.total_damage*field.multishot==pytest.approx(40*(1+.9*1.6))
