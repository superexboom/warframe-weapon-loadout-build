"""Grimoire source contract stays evidence-only until launch/recipient clocks exist."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tools import import_grimoire_static_contract as imp
from tools.import_native_secondary_payloads import merge_patch

@pytest.fixture
def source():
    projectile=dict(MaxLife=6,ExplodeOnLifeExpired=1,DamageRadius=6,ExplosionFallOff=.80000001,
        BounceOnAvatars=0,StopOnAvatars=0,KinematicMovement=1,KinematicInitialSpeed=6,KinematicMinSpeed=1.75,KinematicMaxSpeed=6,KinematicPostCollisionsSpeedFactor=.25,
        MaxTargetsPerAttack=3,MaxChainDepth=2,MaxArcs=2,DirectHitChainLength=8,ArcLength=8,ChainDamageMultiplier=.80000001,TimeBetweenAttacks=1,
        CriticalChance=.2,CriticalMultiplier=2,AttackData=dict(Type='DT_ELECTRICITY',Amount=350,ProcChance=.25999999,ForcedProcs=['PT_ELECTROCUTION']),
        ExplosiveAttack=dict(Type='DT_ELECTRICITY',Amount=250,ProcChance=.25999999))
    weapon={'Behaviors':[{}, {'fire:Fire':dict(IgnoreFireIterations=1,fireIterations=1)}]}
    objects={imp.PROJECTILE:projectile,imp.WEAPON:weapon};parents={imp.PROJECTILE:'/EE/Types/Game/PlayerChainingProjectile',imp.WEAPON:'', '/EE/Types/Game/PlayerChainingProjectile':''}
    class Packages:
        entities={p:(v,SimpleNamespace(attr=None)) for p,v in parents.items()}
        def parent(self,p):return parents[p]
        def resolve(self,p):return deepcopy(objects[p])
    row=dict(path=imp.WEAPON,fireModes=[{},dict(damage=dict(projectile=imp.PROJECTILE,types={'DT_ELECTRICITY':350.}))])
    return Packages(),objects,row

def test_contract_has_no_admitted_mode_or_impact_delay(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row)
    assert out['weapons']=={} and len(out['pending'])==1
    p=out['pending'][0];assert p['candidateOnly'] and p['defaultScoringExcluded']
    part=p['sourcePayload'];assert part['expiry']['lifetimeSecondsFromLaunch']==6.
    assert part['expiry']['delaySecondsFromImpact'] is None
    assert part['chain']['spawnedOrbs']==1
    assert part['chain']['dedupScope']=='one target-selection attack, reset next attack'
    assert part['chain']['nominalAmount']==280.
    assert part['contact']['damage']=={'electricity':350.} and part['expiry']['damage']=={'electricity':250.}
    assert 'scheduler once gate is essential' in p['evidence']['duplicateExpiryCounterfactual']
    assert set(p['unmodeled'])==set(imp.BOUNDS)

def test_evidence_cannot_be_merged_into_scoring_by_generic_merger(source):
    pkg,_,row=source;before={'auditedAttacks':{imp.WEAPON:{'modes':{'1':{'keep':1}}},'/other':{'keep':2}},'keep':3}
    assert merge_patch(before,imp.build_contract(pkg,row))==before

@pytest.mark.parametrize('field,value',[('TimeBetweenAttacks',.5),('ChainDamageMultiplier',1.),('MaxLife',7),('ExplodeOnLifeExpired',0),
    ('ExplodeOnImpact',1),('Embed',1),('MaxLifeVariance',1.),('StopOnAvatars',1),('BounceOnAvatars',1),('MaxTargetsPerAttack',4),('MaxChainDepth',3),('KinematicInitialSpeed',10)])
def test_changed_native_chain_or_expiry_signature_rejected(source,field,value):
    pkg,objects,row=source;objects[imp.PROJECTILE][field]=value
    with pytest.raises(ValueError):imp.build_contract(pkg,row)

@pytest.mark.parametrize('field,value',[('IgnoreFireIterations',0),('fireIterations',2)])
def test_changed_orb_spawn_contract_rejected(source,field,value):
    pkg,objects,row=source;objects[imp.WEAPON]['Behaviors'][1]['fire:Fire'][field]=value
    with pytest.raises(ValueError,match='orb-count'):imp.build_contract(pkg,row)

@pytest.mark.parametrize('field,amount',[('AttackData',250),('ExplosiveAttack',350)])
def test_native_contact_and_expiry_cannot_be_swapped(source,field,amount):
    pkg,objects,row=source;objects[imp.PROJECTILE][field]['Amount']=amount
    with pytest.raises(ValueError,match='packet'):imp.build_contract(pkg,row)
