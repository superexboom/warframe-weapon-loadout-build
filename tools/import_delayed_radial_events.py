"""Import the source identities whose delayed EmbedDeath AGC producer is audited.

This admits generic hit/critical notifications only. It does not infer GunCO,
headshots, damage numbers, script cooldowns, or projectile multishot topology.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from import_companion_projectile_sequences import AuditedPackages, CLIENT_SHA256, PACKAGE_SHA256

ROOT=Path(__file__).resolve().parents[1]
SOURCES=(
 '/Lotus/Weapons/Tenno/Pistols/TnYareliPistol/TnYareliBoltoProj',
 '/Lotus/Weapons/Tenno/Pistols/PrimeKompressa/PrimeKompressaBoltoProj',
 '/Lotus/Weapons/Tenno/Pistols/TnGuandoPistol/TnGuandoPistolProjectile',
 '/Lotus/Weapons/Tenno/Pistols/PrimeZakti/PrimeZaktiProjectile',
)
NATIVE_CLASS='/Lotus/Types/Weapon/BoltoProjectile'

def extract(packages,client,build):
 if hashlib.sha256(client.read_bytes()).hexdigest()!=CLIENT_SHA256:
  raise ValueError('client changed; re-audit authoritative AGC routing')
 if packages.sha256!=PACKAGE_SHA256:
  raise ValueError('Packages.bin changed; re-audit producer identities')
 rows={}
 for path in SOURCES:
  raw=packages.resolve(path)
  chain=[];current=path
  while current and current not in chain:
   chain.append(current);current=packages.entities.get(current,('',None))[0]
  if NATIVE_CLASS not in chain:
   raise ValueError(f'{path}: expected native Bolto producer')
  if raw.get('Embed')!=1 or raw.get('ExplodeOnLifeExpired',0) or raw.get('ExplodeOnImpact',0):
   raise ValueError(f'{path}: lifecycle changed')
  payload=raw.get('EmbedDeathAttack') or {}
  delay=raw.get('EmbedTime') or []
  if payload.get('Amount',0)<=0 or len(delay)!=2 or min(delay)<=0:
   raise ValueError(f'{path}: expected nonzero delayed EmbedDeath payload')
  rows[path]=[dict(nativeClass=NATIVE_CLASS,nativeField='EmbedDeathAttack',nativeDelayRange=delay,
                  genericHit=True,genericCriticalHit=True,headHit=False,enervate=False,
                  semantics='per-damage-packet-after-damage-before-victim-retirement',
                  componentOverrides=dict(takes_victim_crit=True,directRecipientHitType='DHT_PROJECTILE'))]
 return dict(schemaVersion=2,buildLabel=build,
             sources=dict(clientSha256=CLIENT_SHA256,packagesBinSha256=PACKAGE_SHA256,
                          deathCallback='0x140163a60',authorityReceiver='0x140d40ee0',
                          authorityFinish='0x1412dd467',injuryProducer='0x141375130',
                          notifyProducer='0x1416a6090',challengeBridge='0x14179b840'),
             delayedRadialProducers=rows)

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True)
 ap.add_argument('--build-label',required=True);ap.add_argument('--output',type=Path,default=ROOT/'data/mechanics/damage-event-producers.json')
 args=ap.parse_args();payload=extract(AuditedPackages(args.packages_bin),args.client_exe,args.build_label)
 if args.output.exists():
  previous=json.loads(args.output.read_bytes())
  if previous.get('schemaVersion')!=2 or previous.get('sources')!=payload['sources']:
   raise ValueError('existing producer audit uses another schema/source; retain it and re-audit explicitly')
  # This importer owns four delayed identities, not the later independent
  # contact/field/child audits in the same registry.
  merged=previous['delayedRadialProducers']
  for path,rows in payload['delayedRadialProducers'].items():
   by_field={(r['nativeField'],r.get('nativeRoute')):r for r in merged.get(path,[])}
   for row in rows:
    key=(row['nativeField'],row.get('nativeRoute'))
    by_field[key]={**by_field.get(key,{}),**row}
   merged[path]=list(by_field.values())
  payload['delayedRadialProducers']=merged
 args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(dict(producers=len(payload['delayedRadialProducers']),output=str(args.output))))
if __name__=='__main__':main()
