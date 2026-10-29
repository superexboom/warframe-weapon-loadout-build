"""Import Mandonel independent radiation field from current native and Lua consumers."""
from __future__ import annotations
import argparse,hashlib,json,sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"tools")]
from import_companion_projectile_sequences import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256
PREFIX="/Lotus/Weapons/Tenno/Archwing/Primary/TnConcreteArchgun/"
WEAPON=PREFIX+"TnConcreteArchgunWeapon"
TRIGGER=PREFIX+"TnConcreteArchgunAltFireDamageHeavyTrigger"
AW_TRIGGER=PREFIX+"TnConcreteArchgunAltFireDamageTrigger"
SCRIPT=PREFIX+"TnConcreteArchgun.lua"
SCRIPT_SHA256="40beef56fe6efe97c4cd8cd43534b712613383a6161a6a46308e185f7a3ca6f0"
WARNINGS=["mandonel-field-first-enter-update-frame-phase-approximated", "mandonel-on-hit-two-yield-coalescing-simultaneous-shots-unmodeled", "mandonel-field-avatar-special-upgrades-and-event-routing-unverified"]

def profile(packages,row):
 modes=row.get("fireModes") or []
 if row.get("path")!=WEAPON or len(modes)!=2 or modes[1].get("damage",{}).get("total")!=1800.:
  raise ValueError("Mandonel heavy charged mode identity changed")
 weapon=packages.resolve(WEAPON);heavy=packages.resolve(TRIGGER);arch=packages.resolve(AW_TRIGGER)
 impact=weapon["HeavyBehaviors"][1]["impact:RadialOnMissImpactBehavior"]
 callback=impact.get("OnHitScript") or {}
 if (impact.get("OnHitScriptEnabled")!=1 or callback.get("Script")!="TnConcreteArchgun.lua" or callback.get("Function")!="OnHit" or callback.get("_damageTriggerType")!="TnConcreteArchgunAltFireDamageHeavyTrigger"):
  raise ValueError("Mandonel charged field callback changed")
 for trigger,amount,radius in [(heavy,50,1.1),(arch,25,3)]:
  attack=trigger.get("AttackData") or {};destroy=trigger.get("ScriptInstance") or {}
  if (trigger.get("DamageOnEnter")!=1 or trigger.get("DamageOverTimeInterval")!=.2 or trigger.get("DamageSource")!="PLAYER_AVATAR" or trigger.get("DamageAttachedParent")!=0 or trigger.get("Shape")!="VES_CAPSULE" or trigger.get("Radius")!=radius or attack!={"Type":"DT_RADIATION","Amount":amount,"ProcChance":.34999999,"HitType":"DHT_DOT"} or destroy.get("Script")!="TnConcreteArchgun.lua" or destroy.get("Function")!="Destroy" or destroy.get("_lifetime")!=7):
   raise ValueError("Mandonel field contract changed")
 return dict(name="Mandonel",fireMode=1,directTotal=1800.,periodicTriggers=[dict(
  id="mandonel-radiation-field",damage={"radiation":50.},nativeSource=TRIGGER,nativeField="AttackData",
  sourceHitType="DHT_DOT",status_chance=.34999999,forcedProcs=[],crit_chance=0.,crit_multiplier=1.,
  interval_seconds=.2,tick_rate=5.,damageOnEnter=True,damageOnEnterSeparateFromFirstPeriodic=True,
  first_periodic_delay_seconds=0.,firstPeriodicDelayModel="first-authoritative-update-collapsed-to-activation-time",
  duration_seconds=7.,lifetimePolicy="trigger-own-Destroy-script-lifetime7-not-OnHit-caller10",
  activation_event="charged-OnHit-ProcessLastHit-coalesced-segment",activationDelayModel="two-Lua-zero-yields-collapsed-to-hit-time",
  countPolicy="one-field-per-coalesced-OnHit-segment",refreshPolicy="independent-finite-fields-no-source-replacement",
  admission="charged-mode-centered-capsule-target-coverage",defaultEnabled=True,coverageModel="inherit-enclosing-centered-target-assumption",
  damageSource="PLAYER_AVATAR",sourceUpgradeRouting="empty-creator-falls-back-to-self-trigger",
  sourceModifierAllowlist=[],takes_weapon_base_damage=False,takes_weapon_elements=False,
  takes_parent_crit=False,takes_parent_status_chance=False,payloadMultishotMultiplier=False,
  multiplicityPolicy="no-parent-multishot-factor-OnHit-coalescing-controls-field-count",
  radius_m=1.1,expiryBoundary="own-script-region-remove-before-further-field-damage")],unmodeled=list(WARNINGS),source=dict(
  packagesBinSha256=PACKAGE_SHA256,clientSha256=CLIENT_SHA256,script=SCRIPT,scriptSha256=SCRIPT_SHA256,
  spawn="P0 pc84..93 creates damage trigger with fifth creator/progenitor argument only; sixth owner absent; no setter for trigger+0x400 or+0x3f8 in P0",
  progenitor="CreateEntity Lua0x141a2415d fifth argument ->CreateParams+0x18 ->0x141261710 context+8 ->actual trigger slot1f0=0x1403106d0 writes+0x378, not source+0x400",
  emptySource="Entity ctor0x1405299a0 initializes+0x400 empty; trigger ctor does not override; P0 has no source setter; damage0x140e5fd6b..7f falls back to trigger itself",
  sourceClassGate="0x140e5fde3..0x140e5fe36 requires LotusWeapon; self DamageTrigger fails; r14zero skips source weapon base+0xfd and ordinary elements+0x166",
  originalBytes="reproduce_mandonel_source.py preserves25/50with injected weapon multipliers1/2/3, zero weapon callbacks; downstream avatar/faction/target modifiers outside scope",
  clock="actual DamageTrigger vtable0x1421635e0 update141463ae0; initial+0x6c0=0; interval.2 dispatch once/reset/no catchup; DamageOnEnter separate",
  destroy="trigger ScriptInstance Destroy P3 pc6..10 sleeps its lifetime then pc17..22 Region DestroyEntity wrapper141a26380 ->1402201a0 ->140185a50; resolved trigger lifetime7, OnHit caller override10 belongs different script instance",
  coalescing="OnHit P5 pc44..98 records actor-keyed cncrtHitPt and starts ProcessLastHit; P4 yields twice pc0..7, invokes shared P0 once pc35..39, then nils actor keypc51..54; no previous-field destroy",
  archwingVariant=dict(nativeSource=AW_TRIGGER,rawRadiation=25.,radius_m=3.,interval_seconds=.2,duration_seconds=7.)))

def candidate_merge(reference,entry):
 result=deepcopy(reference);current=result["auditedAttacks"].setdefault(WEAPON,{})
 if current.get("directTotal")!=180. or not current.get("projectile","").endswith("TnConcreteArchgunHeavyProjectile"):
  raise ValueError("Mandonel current primary profile changed")
 modes=current.setdefault("modes",{});selected=modes.setdefault("1",{})
 if selected.get("directTotal",1800.)!=1800.:raise ValueError("Mandonel charged profile changed")
 selected.update(directTotal=1800.,periodicTriggers=deepcopy(entry["periodicTriggers"]),fieldSource=deepcopy(entry["source"]))
 selected["unmodeled"]=list(dict.fromkeys([*(selected.get("unmodeled") or []),*entry["unmodeled"]]))
 return result

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--packages-bin",type=Path,required=True);p.add_argument("--client-exe",type=Path,required=True);p.add_argument("--script-body",type=Path,required=True)
 p.add_argument("--export",type=Path,default=ROOT/"data/export/2026.08.13.13.24/weapons.json");p.add_argument("--evidence",type=Path,required=True)
 a=p.parse_args()
 if a.evidence.exists():p.error("preserve evidence; choose a new file")
 for f,sha in [(a.client_exe,CLIENT_SHA256),(a.script_body,SCRIPT_SHA256)]:
  if hashlib.sha256(f.read_bytes()).hexdigest()!=sha:raise ValueError("source identity changed")
 packages=AuditedPackages(a.packages_bin);row=next(w for w in json.loads(a.export.read_bytes())["data"] if w["path"]==WEAPON)
 a.evidence.parent.mkdir(parents=True,exist_ok=True);a.evidence.write_text(json.dumps(profile(packages,row),indent=2)+"\n",encoding="utf-8")
 print("Wrote Mandonel finite radiation field; independent source, no weapon-modifier inheritance")
if __name__=="__main__":main()
