from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import Scenario, ModEffect, apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.runtime_adapters import verified_stug_condition

def build_combat(mode=0, extra=()):
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Stug'))
    w['isIncarnonForm']=mode==2
    branches=[b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id'] in ('2-1','4-3')]
    fx=list(extra)
    for b in branches:fx.extend(app.optimizer._branch_effects(b)[0])
    return prepare(dict(weapon=w,fire_mode=mode,scenario=Scenario(trigger_policy='emergent'),effects=fx),[],[],
                   incarnon_choices={'tier2':'2-1','tier4':'4-3'})

def test_stug_firing_stack_joins_percentage_bucket_once():
    c=build_combat(extra=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2)])
    q=c['trigger_sources'][0]
    assert q['kind']=='on-fire' and q['maxStacks']==10
    assert q['resetOn']==['on-reload','on-transform']
    a,_=c['resolve']('selected',{},0)
    b,_=c['resolve']('selected',{q['id']:10},0)
    assert a.multishot==pytest.approx(2.2)
    assert b.multishot==pytest.approx(2.7)
    assert not any('event-condition-unmodeled' in n for n in c['unsupported'])

def test_stug_status_perk_only_doubles_in_incarnon():
    base=build_combat();inc=build_combat(2)
    st,_=base['resolve']('selected',{},0)
    incst,_=inc['resolve']('selected',{},0)
    returned,_=inc['resolve']('base',{},0)
    # Native explosion SC is 0 in base, .2 transformed; perk grants .2 + form-only .2.
    assert st.status_chance==pytest.approx(.2)
    assert incst.status_chance==pytest.approx(.6)
    assert returned.status_chance==pytest.approx(.2)

def test_unrelated_or_changed_stug_signature_is_not_adapted():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Stug')
    b=next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-1')
    q=b['conditionalEffects'][0]
    assert verified_stug_condition(b,q)
    assert verified_stug_condition({**b,'path':'/unrelated'},q) is None
    wrong=deepcopy(q);wrong['effects'][0]['valuePerRank']=.1
    assert verified_stug_condition(b,wrong) is None

def test_firing_is_per_trigger_pull_and_reload_resets_before_next_shot():
    c=build_combat();q=c['trigger_sources'][0];observed=[]
    original=c['resolve']
    def resolve(form,stacks,live):
        observed.append(stacks.get(q['id'],0))
        st,_=original(form,stacks,live)
        return replace(st,fire_rate=1,magazine=2,reload_time=.5,status_chance=0,crit_chance=0),None
    c['resolve']=resolve
    first,_=resolve('selected',{},0)
    r=replay(first,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
        attacks_per_second=1,window_seconds=4,combat=c,trigger_sources=c['trigger_sources'])
    assert r['shots']==4 and r['reloads']==1
    assert r['directWindow']==pytest.approx(first.total_damage*(1+1.05+1+1.05))
    assert max(observed)<=2

def test_transform_resets_firing_stacks_in_both_directions():
    c=build_combat(2);q=c['trigger_sources'][0];observed=[];original=c['resolve']
    def resolve(form,stacks,live):
        observed.append((form,stacks.get(q['id'],0)))
        st,_=original(form,stacks,live)
        return replace(st,fire_rate=2,magazine=20,status_chance=0,crit_chance=0,radial_only=False),None
    c['resolve']=resolve;c['cycle']=dict(hits=1,pool=1,enterSeconds=.1,exitSeconds=.1,chargeOn='direct_hits')
    first,_=resolve('base',{},0)
    r=replay(first,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
        attacks_per_second=2,window_seconds=2.5,combat=c,trigger_sources=c['trigger_sources'])
    assert r['transforms']>=2
    assert ('incarnon',0) in observed and ('base',0) in observed


def test_stug_trigger_description_survives_actual_manual_replay():
    c=build_combat();q=c['trigger_sources'][0]
    st,_=c['resolve']('selected',{},0)
    r=replay(st,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
        attacks_per_second=st.fire_rate,window_seconds=1.0,combat=c,
        trigger_sources=c['trigger_sources'])
    shown=r['triggerSeries'][0]
    assert shown['conditionText']==q['conditionText']
    assert '每次开火' in shown['conditionText'] and '换弹' in shown['conditionText']
    assert shown['resetOn']==['on-reload','on-transform']
    assert shown['simulationMode']=='events'
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Stug')
    b=next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-1')
    assert app.optimizer._branch_trigger_specs(b)[0]['conditionText']==shown['conditionText']


def test_dera_incarnon_on_kill_ammo_efficiency_replays_as_event():
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Dera')
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier2':'2-1'})
    q=c['trigger_sources'][0]
    base,_=c['resolve']('selected',{},0);live,_=c['resolve']('selected',{q['id']:4},0)
    assert q['kind']=='on-kill' and q['maxStacks']==4 and q['duration']==5
    assert base.ammo_cost==1 and live.ammo_cost==pytest.approx(.2)


def test_torid_final_fusillade_adds_flat_multishot_only_on_base_last_round():
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Torid')
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier2':'2-1'})
    base,_=c['resolve']('base',{},0,False)
    last,_=c['resolve']('base',{},0,True)
    inc,_=c['resolve']('incarnon',{},0,True)
    assert c['lastRoundMultishot']==pytest.approx(3)
    assert last.multishot==pytest.approx(base.multishot+3)
    inc_base,_=c['resolve']('incarnon',{},0,False)
    assert inc.multishot==pytest.approx(inc_base.multishot)


def test_torid_last_round_gate_enters_replay_before_ammo_payment():
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Torid')
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier2':'2-1'})
    st,_=c['resolve']('base',{},0,False)
    observed=[]; original=c['resolve']
    def resolve(form,stacks,live,last_round=False):
        observed.append(bool(last_round))
        st,_=original(form,stacks,live,last_round)
        return replace(st,fire_rate=1,magazine=3,reload_time=.1,status_chance=0,crit_chance=0),None
    c['resolve']=resolve
    st=replace(st,fire_rate=1,magazine=3,reload_time=.1,status_chance=0,crit_chance=0)
    replay(st,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
           attacks_per_second=1,window_seconds=3.2,combat=c,trigger_sources=c['trigger_sources'])
    # The resolver cache elides repeated false-gate calls; the only second
    # invocation is the first last-round state.
    assert observed==[False,True]


def test_cestra_overguard_break_evolution_uses_shared_event_signal():
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Cestra')
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier2':'2-1'})
    assert not any('conditional-effects-not-applied' in x for x in c['unsupported'])
    assert {q['kind'] for q in c['trigger_sources']} == {'on-shield-broken','on-overguard-broken'}
    q=next(q for q in c['trigger_sources'] if q['kind']=='on-overguard-broken')
    base,_=c['resolve']('selected',{},0);live,_=c['resolve']('selected',{q['id']:1},0)
    assert q['duration']==6
    assert live.crit_multiplier > base.crit_multiplier
    seen=[];original=c['resolve']
    def resolve(form,stacks,live_types=0,last_round=False):
        seen.append(stacks.get(q['id'],0))
        return original(form,stacks,live_types,last_round)
    c['resolve']=resolve
    st,_=original('selected',{},0)
    replay(st,dict(health=1e12,shield=0,armour=0,overguard=10,baseLevel=1),
           attacks_per_second=st.fire_rate,window_seconds=.5,combat=c,trigger_sources=c['trigger_sources'])
    assert any(x>0 for x in seen)
