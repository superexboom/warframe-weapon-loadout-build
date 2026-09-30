import pytest
from tools.compare_generated_builds import exact_index, ranked_card, reference_request

def test_reference_mapping_never_substitutes_same_named_variant():
    index=exact_index({'a':{'id':'a','internal_name':'/released','name':'Same','max_rank':5}})
    with pytest.raises(ValueError,match='exact reference path'):
        ranked_card({'path':'/expert','rank':10},index)
    with pytest.raises(ValueError,match='rank differs'):
        ranked_card({'path':'/released','rank':10},index)
    assert ranked_card({'path':'/released','rank':3},index)=='a@3'
    assert ranked_card({'path':'/released','rank':5},index)=='a'

def test_ambiguous_exact_identity_is_not_resolved_by_name():
    index=exact_index({'a':{'id':'a','internal_name':'/x','max_rank':5},'b':{'id':'b','internal_name':'/x','max_rank':5}})
    with pytest.raises(ValueError,match='ambiguous'):
        ranked_card({'path':'/x','rank':5},index)

def test_charged_default_form_is_preserved_and_evolution_never_guessed():
    weapons={'/bow':[{'id':'bow','form':'charged','default_form':True}]}
    p=dict(weapon='/bow',fireMode=0,mods=[],arcanes=[],level=9999,steelPath=True,headshotChance=1,aiming=True,scenario={'distance':10})
    q,_=reference_request(p,weapons,{}, {}, 10)
    assert q['mode']=='base' and q['evolutions']==[]
    assert q['target_at']==[0,10]
    with pytest.raises(ValueError,match='unmapped evolution'):
        reference_request({**p,'incarnonChoices':{'tier2':'2-1'}},weapons,{}, {},10)


def test_stahlta_alt_uses_only_audited_reference_form():
    p=dict(weapon='/stahlta',fireMode=1,mods=[],arcanes=[],level=9999,steelPath=True,
           headshotChance=1,aiming=True,scenario={'distance':10})
    weapons={'/stahlta':[{'id':'stahlta','form':'base','default_form':True}]}
    q,_=reference_request(p,weapons,{}, {},10)
    assert q['weapon']=='stahlta' and q['mode']=='alternate'
    with pytest.raises(ValueError,match='unmapped exact weapon form'):
        reference_request({**p,'fireMode':2},weapons,{}, {},10)


def test_reference_response_must_identify_requested_weapon():
    from tools.compare_generated_builds import reference_identity_matches
    q={'weapon':'stahlta'}
    assert reference_identity_matches({'combatants':[{'id':'wielder','weapon':'stahlta'}]},q)
    assert not reference_identity_matches({'combatants':[{'id':'wielder','weapon':'arbucep'}]},q)
    assert not reference_identity_matches({},q)


def test_reference_stahlta_alternate_must_actually_fire_the_charged_form():
    from tools.compare_generated_builds import reference_identity_matches
    q={'weapon':'stahlta','mode':'alternate'}
    result={'combatants':[{'id':'wielder','weapon':'stahlta'}],'apl':['reload,if=!can_fire','base']}
    assert not reference_identity_matches(result,q)
    result['apl'][-1]='charged'
    assert reference_identity_matches(result,q)


def test_torid_base_evolution_mapping_does_not_claim_cycle_or_form_parity():
    weapons={'/torid':[{'id':'torid','form':'base','default_form':True}]}
    p=dict(weapon='/torid',fireMode=0,mods=[],arcanes=[],level=9999,steelPath=True,headshotChance=0,aiming=True,scenario={'distance':10},incarnonChoices={'tier2':'2-1','tier3':'3-2','tier4':'4-2'})
    q,_=reference_request(p,weapons,{}, {},1000)
    assert q['evolutions']==['torid_final_fusillade','torid_renewed_horror','torid_survivors_edge']
    with pytest.raises(ValueError,match='unmapped external, riven or cycle'):
        reference_request({**p,'incarnonCycle':True},weapons,{}, {},1000)
    with pytest.raises(ValueError,match='unmapped exact weapon form'):
        reference_request({**p,'fireMode':1},weapons,{}, {},1000)


@pytest.mark.parametrize('name',['quanta','quanta_vandal','tenet_quanta'])
def test_quanta_alternate_is_validated_as_cube_not_beam(name):
    from tools.compare_generated_builds import reference_identity_matches
    p=dict(weapon='/q',fireMode=1,mods=[],level=9999,steelPath=True,headshotChance=0,aiming=True,scenario={'distance':.5})
    q,_=reference_request(p,{'/q':[{'id':name,'default_form':True}]},{},{},50)
    assert q['weapon']==name and q['mode']=='alternate'
    r={'combatants':[{'id':'wielder','weapon':name}],'apl':['shoot']}
    assert not reference_identity_matches(r,q)
    r['apl']=['alt_fire'];assert reference_identity_matches(r,q)


def test_reference_progenitor_never_silently_falls_back_to_its_own_default():
    from tools.compare_generated_builds import resolved_reference_payload
    p=dict(weapon='/tenet',fireMode=0,mods=[],level=9999,steelPath=True,headshotChance=0,aiming=True,scenario={'distance':.5})
    weapons={'/tenet':[{'id':'tenet_quanta','default_form':True,'valence':{'min':.25,'max':.6}}]}
    with pytest.raises(ValueError,match='progenitor'):reference_request(p,weapons,{},{},10)
    q=resolved_reference_payload(p,{'innateElement':{'damageType':'DT_FIRE','value':.6}})
    req,_=reference_request(q,weapons,{},{},10)
    assert req['valence_element']=='heat' and req['valence_bonus']==.6
    assert 'innateElement' not in p


def test_fulmin_native_mode_zero_maps_to_semi_auto_and_mode_one_to_automatic():
    from tools.compare_generated_builds import reference_identity_matches
    p=dict(weapon='/fulmin',mods=[],level=9999,steelPath=True,headshotChance=1.,aiming=True)
    weapons={'/fulmin':[{'id':'fulmin_prime','default_form':True}]}
    semi,_=reference_request({**p,'fireMode':0},weapons,{},{},10)
    auto,_=reference_request({**p,'fireMode':1},weapons,{},{},10)
    assert semi['mode']=='alternate' and auto['mode']=='base'
    reply={'combatants':[{'id':'wielder','weapon':'fulmin_prime'}],'apl':['shoot']}
    assert not reference_identity_matches(reply,semi)
    reply['apl']=['semi_auto']
    assert reference_identity_matches(reply,semi)


def test_manual_detonation_cadence_is_not_silently_dropped_in_reference():
    with pytest.raises(ValueError,match='manual detonation'):
        reference_request(dict(weapon='/talons',scenario={'detonationDelaySeconds':.5}),{},{},{},10)
