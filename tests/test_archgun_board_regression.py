from copy import deepcopy
import pytest
import app
from wfarsenal.damage import Scenario, ModEffect, apply_mods, arcane_effects
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload

def raw(group,name):
    return next(x for x in app.EXPORTS[group] if x.get('nameEn')==name)

def wp(name,mode=0):
    w=raw('weapons',name)
    return app.optimizer._select_fire_mode(w,mode,weapon_type=app.optimizer._weapon_type(None,w))[0]

def neutral():
    return dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1,faction='')

def test_archgun_arcane_pool_and_inner_type_gate_agree():
    w=wp('Imperator Vandal');flare=raw('arcanes','Cascadia Flare')
    crux=raw('arcanes','Primary Crux')
    assert app.optimizer._arcane_matches_weapon(raw('arcanes','Cascadia Overcharge'),w)
    card,states,errors=app.optimizer._arcane_card(app.EXPORTS['arcanes'],[
        dict(query=flare['path'],rank=5,stacks=40),dict(query=crux['path'],rank=5,stacks=10)],w)
    assert not any('incompatible' in x for x in errors)
    st=apply_mods(w,card.effects)
    assert st.total_damage==pytest.approx(apply_mods(w,[]).total_damage*5.8)
    assert not app.optimizer._arcane_matches_weapon(flare,wp('Braton Prime'))
    assert not app.optimizer._arcane_matches_weapon(raw('arcanes','Melee Influence'),w)
    # The broad pool exception must not admit ordinary pistol MODs or an
    # unrelated weapon-specific branch carried by an otherwise legal Arcane.
    for source,valid in [(raw('mods','Magnetized Cycle')['path'],flare['compatibility']),
                         (flare['path'],'/Lotus/Weapons/Tenno/Pistol/Pistol')]:
        effect=ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',5,source_path=source,valid_type=valid)
        assert apply_mods(w,[effect]).total_damage==apply_mods(w,[]).total_damage

def test_progenitor_damage_is_element_and_dot_base_before_coalescing():
    w=wp('Kuva Grattler');w={**w,'innateElements':[{'damageType':'DT_MAGNETIC','value':0.6}]}
    st=apply_mods(w,[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',1,damage_type='DT_FIRE')])
    assert st.damage_types['DT_FIRE']==pytest.approx(224,abs=.001)
    assert st.damage_types['DT_MAGNETIC']==pytest.approx(84,abs=.001)
    assert st.dot_base_damage==pytest.approx(224,abs=.001)
    assert st.total_damage==pytest.approx(448,abs=.001)

@pytest.mark.parametrize('name,rank,duration',[('Deadly Efficiency',5,9),('Primed Deadly Efficiency',10,16.5)])
def test_deadly_efficiency_starts_after_empty_reload_completes(name,rank,duration):
    w=deepcopy(wp('Fluctus'));w['magazineSize']=5
    w['fireModes'][0]['fireRate']=5;w['fireModes'][0]['reloadTime']=2
    mod=raw('mods',name);sc=Scenario(trigger_policy='emergent')
    fx=[ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    st=apply_mods(w,fx,scenario=sc)
    combat=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[(mod,rank,None)],[])
    q=combat['trigger_sources'][0]
    assert q['duration']==duration
    result=replay(st,neutral(),attacks_per_second=5,window_seconds=4,combat=combat,trigger_sources=combat['trigger_sources'])
    assert result['reloads']==1
    assert all(p['triggerStacks'][q['id']]==0 for p in result['timeline'] if p['time']<3)
    assert any(p['triggerStacks'][q['id']]==1 for p in result['timeline'] if p['time']>3)
    active,_=combat['resolve']('selected',{q['id']:1})
    assert active.total_damage/st.total_damage==pytest.approx(1+0.2*(rank+1))

@pytest.mark.parametrize('name,burst,radial',[('Cyngas',3,False),('Morgha',2,True),('Grattler',None,True),('Kuva Grattler',None,True)])
def test_archgun_discrete_attacks_have_expected_damage_and_cadence(name,burst,radial):
    w=wp(name);sc=Scenario(trigger_policy='emergent');fx=[ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    combat=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[],[])
    st,part=combat['resolve']('selected',{})
    assert bool(part)==radial
    assert (combat['baseBurst'] or {}).get('count')==burst
    event=replay(st,neutral(),attacks_per_second=st.sustained_attack_rate,window_seconds=1,combat=combat)
    if radial:assert event['totalWindowDamage']>st.average_hit*event['shots']
    if burst:assert event['shots']>st.fire_rate

@pytest.mark.parametrize('name,mode',[('Imperator Vandal',0),('Kuva Grattler',0),('Morgha',0),('Larkspur Prime',1)])
def test_manual_and_optimizer_share_archgun_arcanes(name,mode):
    mods=[raw('mods',n) for n in ['Magma Chamber','Primed Dual Rounds','Primed Deadly Efficiency']]
    p=dict(weapon=wp(name)['path'],fireMode=mode,mods=[dict(path=m['path'],rank=m['maxRank'],slot=i) for i,m in enumerate(mods)],
        arcanes=[dict(path=raw('arcanes',n)['path'],rank=5) for n in ['Primary Crux','Cascadia Flare']],
        enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    if name=='Kuva Grattler':p.update(innateElement='DT_MAGNETIC',innateElementValue=0.6)
    result=evaluate_payload(p)
    assert result['optimizer']==pytest.approx(result['manual'],rel=1e-9)
    with_flare=app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
    without=app.simulate_manual_payload({**p,'arcanes':p['arcanes'][:1]})['benchmarkTimeline']['killsPerMinute']
    assert with_flare>without

def test_archgun_arcane_contribution_uses_same_replay():
    m=raw('mods','Magma Chamber');a=raw('arcanes','Cascadia Flare')
    p=dict(weapon=wp('Imperator Vandal')['path'],mods=[dict(path=m['path'],rank=m['maxRank'],slot=0)],
        arcanes=[dict(path=a['path'],rank=5)],enemy=app._BENCHMARK_ENEMY_PATH,level=9999,
        steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    key='__arcane__:'+a['path']
    gain=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    expected=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gain['gains'][key]['value']==pytest.approx(expected,abs=.001)
    assert gain['baseValue']>expected


def test_released_archgun_cards_reach_manual_and_optimizer_without_unlocking_placeholders():
    from wfarsenal.catalog_releases import released_mod_catalog, RELEASED_ARCHGUN_MODS
    candidates,_=app.optimizer._candidate_mods(app.EXPORTS,wp('Imperator Vandal'),Scenario())
    keys={c.key for c in candidates}
    for path in RELEASED_ARCHGUN_MODS:
        assert path in app.MANUAL_MODS_BY_PATH
        assert path in keys
        card=deepcopy(next(m for m in app.EXPORTS['mods'] if m['path']==path))
        card['selectable']=False
        assert released_mod_catalog([card])[0]['selectable'] is True
        assert card['selectable'] is False
        for field,value in [('path',path+'Unreleased'),('nameEn','dev'),('effects',[]),('isSubUpgrade',True)]:
            assert released_mod_catalog([{**card,field:value}])[0]['selectable'] is False
    electric=raw('mods','Primed Electrified Barrel')
    assert electric['selectable'] is False
    assert electric['path'] not in app.MANUAL_MODS_BY_PATH
    assert electric['path'] not in keys


def _community_cases():
    import json
    from pathlib import Path
    fixture=Path(__file__).parent/'fixtures'/'archgun_board_20260926.json'
    return [c for c in json.loads(fixture.read_text(encoding='utf-8'))['cases'] if c['uiImportable']]


@pytest.mark.parametrize('case',_community_cases(),ids=lambda c:c['id'])
def test_frozen_community_builds_use_the_same_manual_and_search_evaluator(case):
    result=evaluate_payload(case['manualPayload'])
    assert result['manual']>0
    assert result['optimizer']==pytest.approx(result['manual'],rel=1e-9)
    # These builds deliberately retain known reference residuals. Equality
    # here proves input acceptance and evaluator parity, not WFSim parity.
