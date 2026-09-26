from dataclasses import replace
from copy import deepcopy
from itertools import permutations
import pytest
import app
from wfarsenal.damage import Scenario, ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload

o = app.optimizer

def weapon(name, mode=0):
    w = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
    return o._select_fire_mode(w, mode, weapon_type=o._weapon_type(None, w))[0]

def neutral():
    return dict(health=1e12, shield=0, armour=0, overguard=0, baseLevel=1, faction='', factionResistance='RK_NEUTRAL')

def event(name, mode=0, effects=(), scenario=None, seconds=30):
    sc = scenario or Scenario(trigger_policy='emergent')
    w = weapon(name, mode)
    fx = [ModEffect('WEAPON_PROC_CHANCE', 'SET', 0), *effects]
    st = o.apply_mods(w, fx, scenario=sc)
    o._bind_combat_inputs(st, w, [], fx, sc, None)
    return st, o._event_window(st, dict(target=neutral(), level=1, windowSeconds=seconds, headshotChance=0))

@pytest.mark.parametrize('name,shots', [('Nataruk',50),('Cinta',50),('Paris Prime',43),('Felarx',35)])
def test_audited_cadence(name,shots):
    st, result = event(name)
    assert result['shots'] == shots
    if name == 'Felarx':
        assert st.magazine == 6
        assert st.reload_time == pytest.approx(3.7)
        _, larger = event(name,effects=[ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',1)])
        assert larger['reloads'] < result['reloads']

def test_torid_clouds_stack_and_die_with_target():
    st, r = event('Torid')
    assert r['windowDps'] > 4 * st.sustained_dps
    w=weapon('Torid');fx=[ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    engine=dict(weapon=w,effects=fx,scenario=Scenario(),fire_mode=0)
    combat=prepare(engine,[],[])
    small=replay(st,{**neutral(),'health':1},attacks_per_second=st.sustained_attack_rate,window_seconds=3,combat=combat)
    assert small['killEvents'] == small['shots']

def test_torid_charges_on_body_hits():
    _, r = event('Torid',1,scenario=Scenario(incarnon_cycle=True,trigger_policy='emergent'))
    assert r['transforms'] > 0
    assert 'incarnon-cycle-data-unavailable' not in r['unsupported']

@pytest.mark.parametrize('name', ['Mausolon','Opticor Vandal'])
def test_separate_radial_damage(name):
    st,r = event(name)
    assert r['windowDps'] > 1.25 * st.sustained_dps

def test_first_round_bonus_not_every_round():
    _,bare=event('Braton Prime')
    _,bonus=event('Braton Prime',effects=[ModEffect('WEAPON_INIT_DAMAGE_MOD','STACKING_MULTIPLY',1)])
    ratio=bonus['totalWindowDamage']/bare['totalWindowDamage']
    assert 1 < ratio < 1.05

def test_small_pool_optimizer_ranking_uses_events():
    w=weapon('Braton Prime');sc=Scenario(trigger_policy='emergent')
    cards=[o._Card(key=k,record=None,rank=0,effects=(e,),skipped=(),drain=2,polarity=None) for k,e in [
        ('base',ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1)),
        ('heat',ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',1,damage_type='DT_FIRE')),
        ('rate',ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',1)),
    ]]
    ctx=dict(target=neutral(),level=1,windowSeconds=30,headshotChance=0)
    best=o._optimize(w,cards,None,scenario=sc,metric='killsPerMinute',target_context=ctx,slot_count=2,min_fill=2,max_fill=2,profile='fast')
    all_scores=[o._evaluate(w,p,None,scenario=sc,metric='killsPerMinute',target_context=ctx).score for p in permutations(cards,2)]
    assert best.score == pytest.approx(max(all_scores))
    assert hasattr(best.stats,'_combat_inputs')

@pytest.mark.parametrize('name,mode,cycle',[('Torid',1,True),('Burston Prime',1,True),('Felarx',0,False),('Mausolon',0,False),('Nataruk',0,False)])
def test_public_manual_search_parity(name,mode,cycle):
    w=weapon(name,mode)
    p=dict(weapon=w['path'],fireMode=mode,mods=[],enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0.5,incarnonCycle=cycle,aiming=True,triggerPolicy='emergent')
    r=evaluate_payload(p)
    assert r['optimizer'] == pytest.approx(r['manual'],rel=1e-9,abs=1e-8)

def test_frenzy_starts_only_after_direct_head_hit():
    w=weapon('Dual Toxocyst');sc=Scenario(trigger_policy='emergent')
    st=o.apply_mods(w,[],scenario=sc)
    o._bind_combat_inputs(st,w,[],[],sc,None)
    ctx=dict(target=neutral(),level=1,windowSeconds=5,headshotChance=0)
    body=o._event_window(st,ctx)
    head=o._event_window(st,{**ctx,'headshotChance':1})
    assert head['shots'] > body['shots']
    assert body['shots'] == 5
    assert head['totalWindowDamage'] > 2 * body['totalWindowDamage']

def test_riven_element_order_is_shared():
    w=weapon('Braton Prime')
    mods=[]
    for slot,name in [(0,'Cryo Rounds'),(2,'Stormbringer'),(3,'Hellfire')]:
        m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==name and m['path'] in app.MANUAL_MODS_BY_PATH and m.get('maxRank')==5)
        mods.append(dict(path=m['path'],rank=m['maxRank'],slot=slot))
    p=dict(weapon=w['path'],mods=mods,enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,riven={'slot':1,'polarity':'AP_ATTACK','stats':[{'code':'6','value':100,'negative':False}]})
    r=evaluate_payload(p)
    assert r['optimizer'] == pytest.approx(r['manual'],rel=1e-8)
    before=app.simulate_manual_payload(p)['moddedStats']
    after=app.simulate_manual_payload({**p,'riven':{**p['riven'],'slot':4}})['moddedStats']
    assert before['damageTypes'] != after['damageTypes']

def test_event_mod_and_arcane_ablations_keep_context():
    w=weapon('Burston Prime',1)
    m=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Thermite Rounds' and m['path'] in app.MANUAL_MODS_BY_PATH)
    arc=next(a for a in app.MANUAL_ARCANES if a.get('nameEn')=='Primary Merciless')
    p=dict(weapon=w['path'],fireMode=1,mods=[{'path':m['path'],'rank':3,'slot':0}],enemy=app._BENCHMARK_ENEMY_PATH,level=170,steelPath=True,headshotChance=1,incarnonCycle=True,arcanes=[{'path':arc['path'],'rank':5}],externalBuffs=[{'id':'roar','value':0.5}])
    base=app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
    gain=app.mod_gains_payload({**p,'mode':'equipped','candidates':[m['path'],'__arcane__:'+arc['path']]})
    assert gain['metric']=='killsPerMinute'
    assert gain['baseValue']==pytest.approx(base,abs=0.001)
    for key,change in [(m['path'],{'mods':[]}),('__arcane__:'+arc['path'],{'arcanes':[]})]:
        expected=app.simulate_manual_payload({**p,**change})['benchmarkTimeline']['killsPerMinute']
        assert gain['gains'][key]['value']==pytest.approx(expected,abs=0.001)

@pytest.mark.parametrize('override,assumed,expected', [({'stacks':4,'uptime':0.5},False,2),({'uptime':0},False,0),({},True,12)])
def test_fixed_arcane_policies_do_not_expire_or_grow(override,assumed,expected):
    w=weapon('Braton Prime');sc=Scenario(trigger_policy='assumed_max' if assumed else 'emergent')
    arc=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Primary Merciless')
    combat=prepare(dict(weapon=w,effects=[],scenario=sc,fire_mode=0),[],[(arc,5,override)],assumed=assumed)
    source=next(s for s in combat['trigger_sources'] if 'Rifle' in s['id'] or s['kind']=='on-kill')
    assert source['initialStacks']==pytest.approx(expected)
    assert source['duration']==0
    assert source['perEvent']==0
    st=o.apply_mods(w,[],scenario=sc)
    r=replay(st,neutral(),combat=combat,trigger_sources=combat['trigger_sources'],window_seconds=30,headshot_chance=0,attacks_per_second=st.sustained_attack_rate,level=1)
    assert r['totalWindowDamage'] > 0

def test_native_assumed_max_is_constant():
    w=weapon('Dual Toxocyst');sc=Scenario(trigger_policy='assumed_max')
    c=prepare(dict(weapon=w,effects=[],scenario=sc,fire_mode=0),[],[],assumed=True)
    q=next(q for q in c['trigger_sources'] if 'frenzy' in q['id'].lower())
    assert (q['initialStacks'],q['duration'],q['perEvent'])==(1,0,0)

def test_recommendation_scope_and_special_card_share_replay():
    w=weapon('Braton Prime');sc=Scenario(trigger_policy='emergent')
    pool,_=o._candidate_mods(app.EXPORTS,w,sc)
    cards=[]
    for name in ['Hellfire','Serration','Point Strike','Vital Sense']:
        choices=[c for c in pool if c.record.get('nameEn')==name and c.record['path'] in app.MANUAL_MODS_BY_PATH]
        cards.append(max(choices,key=lambda c:c.drain))
    cards[0]=replace(cards[0],required=True)
    special=next(m for m in app.CATALOG_UTILITY_MODS if m.get('nameEn')=='Vigilante Supplies')
    utility=app._utility_card_at_rank(special,sc,0)
    ctx=dict(target=app.MANUAL_ENEMIES_BY_PATH[app._BENCHMARK_ENEMY_PATH],level=9999,steel_path=True,windowSeconds=30,headshotChance=0)
    passive,choices,_,_=o._incarnon_card(w,None,scenario=sc,metric='killsPerMinute',policy=app.EXPORTS.get('incarnonDefaults'),build_label=app.EXPORTS['buildLabel'])
    baseline=o._evaluate(w,cards,None,scenario=sc,metric='killsPerMinute',passives=passive,target_context=ctx,special_cards=(utility,),special_capacity_cost=2)
    lines=o._wire_lines([{'code':c,'value':100,'negative':False} for c in ['1','2','W']])[0]
    result=o.recommend_optimal_riven(w,baseline,lines,[],scenario=sc,metric='killsPerMinute',passives=passive,target_context=ctx,slot_count=3,min_fill=3,max_fill=3,required_damage_type='DT_FIRE',special_cards=(utility,),special_capacity_cost=2,budget_seconds=1)
    assert result['combos']
    for row in result['combos']:
        b=row['build']
        assert len(b['mods'])==2
        assert any(m['path']==cards[0].record['path'] for m in b['mods'])
        assert b['damageTypes']['DT_FIRE'] > 0
        slots=[None]*8
        for m in b['mods']:slots[m['slot']]=app.MANUAL_MODS_BY_PATH[m['path']]['polarity']
        slots[b['riven']['slot']]='AP_ATTACK'
        payload=dict(weapon=w['path'],incarnonChoices=choices,mods=[{k:m[k] for k in ['path','rank','slot']} for m in b['mods']],riven=b['riven'],slotPolarities=slots,exilus=b['specialMods'][0],enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0)
        manual=app.simulate_manual_payload(payload)
        assert row['score']==pytest.approx(manual['benchmarkTimeline']['killsPerMinute'],rel=1e-8)
    with pytest.raises(o.SimulationError,match='slot/fill'):
        o.recommend_optimal_riven(w,baseline,lines,[],scenario=sc,metric='killsPerMinute',slot_count=1,max_fill=1)
