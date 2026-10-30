"""Scourge55 native contract stays separate from unresolved throw cadence."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from tools import import_scourge_contact_contract as imp
from tools.import_native_secondary_payloads import merge_patch
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def source():
    data=json.loads((ROOT/'tests/fixtures/scourge_prime_source.json').read_bytes());objects={imp.WEAPON:data['weapon'],imp.PROJECTILE:data['projectile']};parents={r['path']:r['parent'] for r in data['sources']}
    class Packages:
        entities={p:(a,SimpleNamespace(attr=None)) for p,a in parents.items()}
        def parent(self,p):return parents.get(p)
        def resolve(self,p):return deepcopy(objects[p])
        def locate(self,owner,ref):return ref if ref.startswith('/') else owner.rsplit('/',1)[0]+'/'+ref
    row=next(r for r in json.loads((ROOT/'data/export/2026.08.13.13.24/weapons.json').read_bytes())['data'] if r['path']==imp.WEAPON)
    return Packages(),objects,row

def test_contact55_is_single_physical_spear_evidence_not_cadence_admission(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row);assert out['weapons']=={};pending=out['pending'][0]
    assert pending['defaultScoringExcluded'] and pending['candidateOnly']
    radial=pending['sourcePayload']['radial'];assert radial['damage']=={'corrosive':55.}
    assert radial['physicalThrowsPerFire']==radial['packetsPerPhysicalThrow']==1
    assert radial['scalarMultishotAllowed'] is False
    assert radial['delayFromAcceptedContactSeconds']==0.
    assert pending['sourcePayload']['nativeThrowState']['MaxNumProjectiles']==1
    assert pending['sourcePayload']['nativeThrowState']['ReloadAfterEveryShot']==1

def test_generic_merge_cannot_admit_pending55(source):
    pkg,_,row=source;before={'auditedAttacks':{imp.WEAPON:{'keep':1}},'other':2}
    assert merge_patch(before,imp.build_contract(pkg,row))==before

@pytest.mark.parametrize('field,value',[('CanExplodeOnContact',1),('ExplodeOnImpact',0),('ExplodeOnLifeExpired',1),('StopOnAvatars',0),('SetLifeOnImpact',0),('ScriptsPreventDestruction',0),('EmbedTime',[1,1]),('DamageRadius',8)])
def test_rejects_contact_or_embed_lifecycle_drift(source,field,value):
    pkg,objects,row=source;objects[imp.PROJECTILE][field]=value
    with pytest.raises(ValueError):imp.build_contract(pkg,row)

@pytest.mark.parametrize('field,value',[('TrackProjectiles',0),('MaxNumProjectiles',2),('DestroyActiveProjectiles',0),('ReloadAfterEveryShot',0),('DetonateOnSwapToPrimary',0),('HideAttachAndDisableWeapon',0)])
def test_rejects_throw_state_drift(source,field,value):
    pkg,objects,row=source;state=next(v for k,v in objects[imp.WEAPON]['Behaviors'][1].items() if k.startswith('state:') and isinstance(v,dict));state[field]=value
    with pytest.raises(ValueError,match='state'):imp.build_contract(pkg,row)
