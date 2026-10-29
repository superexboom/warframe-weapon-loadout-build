from copy import deepcopy
import pytest
from tools.import_mandonel_field import WEAPON,TRIGGER,AW_TRIGGER,profile,candidate_merge

class Packages:
 def __init__(self):
  def field(amount,radius):return dict(AttackData=dict(Type="DT_RADIATION",Amount=amount,ProcChance=.34999999,HitType="DHT_DOT"),ScriptInstance=dict(Script="TnConcreteArchgun.lua",Function="Destroy",_lifetime=7),Shape="VES_CAPSULE",Radius=radius,DamageOnEnter=1,DamageOverTimeInterval=.2,DamageSource="PLAYER_AVATAR",DamageAttachedParent=0)
  self.rows={TRIGGER:field(50,1.1),AW_TRIGGER:field(25,3),WEAPON:{"HeavyBehaviors":[{}, {"impact:RadialOnMissImpactBehavior":dict(OnHitScriptEnabled=1,OnHitScript=dict(Script="TnConcreteArchgun.lua",Function="OnHit",_damageTriggerType="TnConcreteArchgunAltFireDamageHeavyTrigger",_lifetime=10))}]}}
 def resolve(self,path):return self.rows[path]

def row():return dict(path=WEAPON,fireModes=[{},dict(damage=dict(total=1800.))])

def test_field_has_own_lifetime_and_no_parent_weapon_scaling():
 f=profile(Packages(),row())["periodicTriggers"][0]
 assert f["damage"]=={"radiation":50.} and f["duration_seconds"]==7.
 assert f["interval_seconds"]==.2 and f["status_chance"]==.34999999
 assert f["crit_chance"]==0. and f["forcedProcs"]==[]
 assert f["takes_weapon_base_damage"] is False and f["takes_weapon_elements"] is False
 assert f["takes_parent_crit"] is False and f["takes_parent_status_chance"] is False
 assert f["sourceModifierAllowlist"]==[] and f["payloadMultishotMultiplier"] is False
 assert f["defaultEnabled"] is True

def test_enter_first_periodic_and_renewed_fields_are_independent():
 f=profile(Packages(),row())["periodicTriggers"][0]
 assert f["damageOnEnterSeparateFromFirstPeriodic"] is True
 assert f["first_periodic_delay_seconds"]==0.
 assert f["refreshPolicy"]=="independent-finite-fields-no-source-replacement"
 assert f["countPolicy"]=="one-field-per-coalesced-OnHit-segment"

@pytest.mark.parametrize("key,value",[("DamageOverTimeInterval",.5),("DamageSource","SELF"),("Radius",3)])
def test_trigger_drift_rejects_stale_contract(key,value):
 p=Packages();p.rows[TRIGGER][key]=value
 with pytest.raises(ValueError,match="field contract"):profile(p,row())

def test_destroy_instance_drift_does_not_reuse_onhit_lifetime():
 p=Packages();p.rows[TRIGGER]["ScriptInstance"]["_lifetime"]=10
 with pytest.raises(ValueError,match="field contract"):profile(p,row())

def test_merge_attaches_only_charged_mode_and_preserves_current_profile():
 before={"auditedAttacks":{WEAPON:dict(directTotal=180.,projectile="/test/TnConcreteArchgunHeavyProjectile",charge={"seconds":1.5}),"/other":{"keep":True}}}
 saved=deepcopy(before);result=candidate_merge(before,profile(Packages(),row()))
 assert before==saved and result["auditedAttacks"][WEAPON]["directTotal"]==180.
 assert result["auditedAttacks"][WEAPON]["modes"]["1"]["directTotal"]==1800.
 assert result["auditedAttacks"]["/other"]=={"keep":True}
 assert candidate_merge(result,profile(Packages(),row()))==result


def test_production_selected_mode_resolver_reads_preserved_field_profile(monkeypatch):
 import sys
 from pathlib import Path
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"vendor"))
 from wfarsenal import event_profiles,manual_combat
 before={"auditedAttacks":{WEAPON:dict(directTotal=180.,projectile="/test/TnConcreteArchgunHeavyProjectile",modes={"1":dict(directTotal=1800.,existingMetadata={"keep":True},unmodeled=["existing-warning"]),"2":{"keep":True}})}}
 result=candidate_merge(before,profile(Packages(),row()))
 monkeypatch.setattr(manual_combat,"reference",lambda:result)
 weapon=dict(path=WEAPON,__selectedFireMode__=1,fireModes=[dict(damage=dict(types={"DT_RADIATION":1800.}),chargeTime=0)])
 selected=event_profiles.base_profile(weapon,0)
 assert selected["periodicTriggers"][0]["nativeSource"]==TRIGGER
 assert selected["existingMetadata"]=={"keep":True}
 assert selected["unmodeled"][0]=="existing-warning"
 assert result["auditedAttacks"][WEAPON]["modes"]["2"]=={"keep":True}
 assert "modeProfiles" not in result["auditedAttacks"][WEAPON]
