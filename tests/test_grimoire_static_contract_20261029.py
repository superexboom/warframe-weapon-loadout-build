"""Grimoire source metadata and generic-merge boundary; runtime coverage is tested separately."""
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

def test_contract_separates_source_metadata_from_unconditional_damage(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row)
    assert out['weapons']=={} and len(out['pending'])==1
    p=out['pending'][0];assert p['candidateOnly'] and p['defaultScoringExcluded']
    part=p['sourcePayload'];assert part['expiry']['lifetimeSecondsFromLaunch']==6.
    assert part['expiry']['delaySecondsFromImpact'] is None
    assert part['chain']['spawnedOrbs']==1
    assert part['chain']['dedupScope']=='one target-selection attack, reset next attack'
    assert part['chain']['nominalAmount']==280.
    assert not part['contact']['damageSubmitted']
    assert part['contact']['damage']=={'electricity':350.} and part['expiry']['damage']=={'electricity':250.}
    current=out['sourceContracts'][imp.WEAPON]['1']
    assert current['noDirectContact'] and current['grimoireSourceContract']['spawnedOrbs']==1
    assert 'scheduler once gate is essential' in p['evidence']['duplicateExpiryCounterfactual']
    assert set(p['unmodeled'])==set(imp.BOUNDS)

    before={'auditedAttacks':{imp.WEAPON:{'modes':{'1':{'keep':1}}},'/other':{'keep':2}},'keep':3}
    assert merge_patch(before,imp.build_contract(pkg,row))==before

def test_changed_native_chain_clock_is_rejected(source):
    pkg,objects,row=source;objects[imp.PROJECTILE]['TimeBetweenAttacks']=.5
    with pytest.raises(ValueError):imp.build_contract(pkg,row)

def test_native_source_value_cannot_replace_expiry_payload(source):
    pkg,objects,row=source;objects[imp.PROJECTILE]['ExplosiveAttack']['Amount']=350
    with pytest.raises(ValueError,match='packet'):imp.build_contract(pkg,row)
