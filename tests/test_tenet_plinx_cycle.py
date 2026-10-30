"""Tenet Plinx source gates and distinct damage/count/countdown contracts."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
from tools import import_tenet_plinx_cycle as imp
from tools.import_native_secondary_payloads import merge_patch

@pytest.fixture
def source(monkeypatch):
    data=json.loads((Path(__file__).parent/'fixtures/tenet_plinx_source.json').read_text())
    objects={imp.WEAPON:data['weapon'],imp.PROJECTILE:data['projectile'],
             **{a:{'OnEnter':deepcopy(data['events'])} for a in imp.ATTACHMENTS}}
    class Packages:
        def resolve(self,p): return deepcopy(objects[p])
        def locate(self,owner,ref): return ref if ref.startswith('/') else owner.rsplit('/',1)[0]+'/'+ref
    monkeypatch.setattr(imp,'source_rows',lambda pkg,paths:[])
    return Packages(), objects, {'path':imp.WEAPON}

def test_full_clip_scales_damage_and_consumption_not_projectile_count(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row)
    c=out['enginePatchContract'];assert c['reuseBattery'] and not c['reuseChargeVolley']
    charge=c['charge'];assert charge['rawProjectiles']==1 and charge['damageScale']=='ammoAtChargeStart'
    assert charge['requiresFullClip'] and charge['consumesLoadedCapacity']
    assert charge['consumptionPhase']=='charge-progress' and not charge['usesNormalFireAmmo']
    assert not charge['clipSizeScalesDuration']
    assert c['payload']['deathPacketSelection']=='exclusive-embedded-flag'
    assert c['payload']['embeddedDeath']['damage']=={'radiation':100.}
    assert c['payload']['unembeddedDeathAlternative']['damage']=={'radiation':500.}
    assert c['battery']['activeCountdownMustBeSeparateState']
    assert c['battery']['configuredDelaySetterResetsCountdown'] is False
    assert c['battery']['luaAltOrder']==['setAmmo0','setConfiguredEmptyDelay3']
    assert {e['activeMode'] for e in c['battery']['attachmentEvents']}=={0,1}

def test_unresolved_clock_cannot_silently_enter_scoring(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row)
    assert out['weapons']=={} and out['pending'][0]['defaultScoringExcluded']
    base={'auditedAttacks':{'preserved':1}}
    assert merge_patch(base,out)==base

@pytest.mark.parametrize('category,field,value',[
 ('weapon','BatteryRegenRate',30),('weapon','NotifyAttachmentState',0),
 ('state','UseClipWhileCharging',0),('state','ChargeRequireFullClip',0),
 ('state','ClipSizeAffectsChargeTime',1),('state','MaxDamageMultiplier',1),
 ('fire','fireIterations',10),('fire','UseAmmo',1),('fire','AttenuateForCharge',1),
 ('projectile','EmbedTime',[1,1]),('projectile','DamageRadius',7),
 ('direct','Amount',500),('embedded','Amount',500),('unembedded','Amount',100)])
def test_rejects_native_mechanism_drift(source,category,field,value):
    pkg,objects,row=source
    w,p=objects[imp.WEAPON],objects[imp.PROJECTILE]
    target={'weapon':w,'projectile':p,'state':w['Behaviors'][1]['state:WeaponChargedStateBehavior'],
      'fire':w['Behaviors'][1]['fire:LotusWeaponProjectileFireBehavior'],
      'direct':p['AttackData'],'embedded':p['EmbedDeathAttack'],'unembedded':p['ExplosiveAttack']}[category]
    target[field]=value
    with pytest.raises(ValueError):imp.build_contract(pkg,row)

@pytest.mark.parametrize('field,value',[('activeBehaviorIndexIgnoreList',[0,1]),('state','WS_CHARGE'),('matchTransitionState',1)])
def test_rejects_script_event_routing_drift(source,field,value):
    pkg,objects,row=source;objects[imp.ATTACHMENTS[0]]['OnEnter'][0][field]=value
    with pytest.raises(ValueError):imp.build_contract(pkg,row)


def test_operational_radial_retains_source_ragdoll_and_normalized_falloff(source):
    pkg,_,row=source;patch=imp.build_contract(pkg,row)['operationalPatch']
    radial=patch['weapons'][imp.WEAPON]['modes']['1']['radial']
    assert radial['forcedProcs']==['PT_RAGDOLL']
    assert radial['radius_m']==6. and radial['falloff_reduction']==.40000001
    assert 'falloff' not in radial
