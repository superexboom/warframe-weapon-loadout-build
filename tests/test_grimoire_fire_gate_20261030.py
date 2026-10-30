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

@pytest.mark.parametrize('field,value',[('InstantOverheat',0),('OverheatTime',44),('ReduceOverheatAmount',2),('OverheatCooldownModifier',2),('OverheatStyle','OS_SAWTOOTH')])
def test_state_drift_rejected(source,field,value):
    pkg,w,row=source;w['Behaviors'][1]['state:LotusFireAndToggleStateBehavior'][field]=value
    with pytest.raises(ValueError,match='overheat'):imp.build_contract(pkg,row)

@pytest.mark.parametrize('field,value',[('AddingChargesReducesOverheat',0),('MaxCharges',1),('AddCharges',[dict(Conditions=['SECONDARY_DIRECT_HIT'],NumCharges=1)])])
def test_charge_event_drift_rejected(source,field,value):
    pkg,w,row=source;w[field]=value
    with pytest.raises(ValueError,match='charge event'):imp.build_contract(pkg,row)

def test_doppelganger_cannot_match(source):
    pkg,_,row=source;row['path']='/Lotus/Weapons/Tenno/Grimoire/TnGrimoireDoppelganger'
    with pytest.raises(ValueError,match='identity'):imp.build_contract(pkg,row)
