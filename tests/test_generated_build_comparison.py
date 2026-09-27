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
    assert q['mode']=='charged' and q['evolutions']==[]
    assert q['target_at']==[0,10]
    with pytest.raises(ValueError,match='unmapped evolution'):
        reference_request({**p,'incarnonChoices':{'tier2':'2-1'}},weapons,{}, {},10)
