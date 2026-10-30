"""Hash-pinned Grimoire alternate overheat gate; independent of orb payload geometry."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools.import_native_secondary_payloads import AuditedPackages,CLIENT_SHA256,PACKAGE_SHA256,source_rows,sha256
ROOT=Path(__file__).resolve().parents[1]
WEAPON='/Lotus/Weapons/Tenno/Grimoire/TnGrimoire'
PROJECTILE='/Lotus/Weapons/Tenno/Grimoire/TnGrimoireAltProj'
STATE='/Lotus/Types/Weapon/LotusFireAndToggleStateBehavior'

def build_contract(pkg,row):
    if row.get('path')!=WEAPON or row['fireModes'][1]['damage'].get('projectile')!=PROJECTILE:
        raise ValueError('Grimoire exact export identity changed')
    w=pkg.resolve(WEAPON);mode=w['Behaviors'][1]
    state=mode.get('state:LotusFireAndToggleStateBehavior')
    if mode.get('state:Type')!=STATE or not isinstance(state,dict):
        raise ValueError('Grimoire native state changed')
    signature=dict(InstantOverheat=1,OverheatStyle='OS_PLATEAU',OverheatTime=45,ReduceOverheatAmount=1,OverheatCooldownModifier=1)
    if any(state.get(k)!=v for k,v in signature.items()):raise ValueError('Grimoire native overheat signature changed')
    if w.get('AddingChargesReducesOverheat')!=1 or w.get('MaxCharges')!=0 or w.get('AddCharges')!=[{'Conditions':['PRIMARY_DIRECT_HIT'],'NumCharges':1}]:
        raise ValueError('Grimoire charge event signature changed')
    fire=mode.get('fire:LotusWeaponProjectileFireBehavior',{})
    if fire.get('IgnoreFireIterations')!=1 or fire.get('fireIterations')!=1:raise ValueError('Grimoire orb count changed')
    evidence=dict(clientSha256=CLIENT_SHA256,packageSha256=PACKAGE_SHA256,nativeSources=source_rows(pkg,[WEAPON,STATE]),
        selectedClass='LotusFireAndToggleStateBehavior table142317618;serializer+50->14013ac50->140655790;update+c0->140aa3a60->140b22dc0;availability+118->140f96270->140a10c10',
        fieldBinding='140655e0e..e77: InstantOverheat+105,OverheatTime+d4,ReduceOverheatAmount+d8;140655e80..:OverheatCooldownModifier+dc;14102c625..642:AddingChargesReducesOverheat+323a',
        arm='140b22e23..e3c accepted firing state + InstantOverheat sets remaining+d0=OverheatTime+d4',
        passive='140b22e9a..f21 subtracts dt*OverheatCooldownModifier+dc from remaining+d0, clamps0 (OS_PLATEAU)',
        ready='actual leaf140a10c10..c29 returns abs(remaining+d0)<=native epsilon; no unwind-boundary inference',
        charge='140fbc71f..77c AddingChargesReducesOverheat loops weapon behaviors via1401f7de0 ->full14022a920;14022a9af..9ba subtracts ReduceOverheatAmount+d8 and clamps0;MaxCharges0 does not bypass this loop',
        eventBoundary='Exact AddCharges PRIMARY_DIRECT_HIT NumCharges1 source; accepted event dispatch count, misses, chain/tick recipients are not assumed to be primary events')
    return dict(schemaVersion=1,kind='native-grimoire-fire-gate',weapons={WEAPON:{'1':dict(nativeFireCooldownSeconds=45.,nativeFireGate=dict(kind='instant-overheat',initiallyReady=True,cooldownSeconds=45.,naturalRecoveryPerSecond=1.,affectedByFireRate=False,primaryHitRecoverySeconds=1.,primaryRecoveryEvent='PRIMARY_DIRECT_HIT',primaryRecoveryEnabledInSingleMode=False),evidence=evidence)}},
        engineContract=dict(singleAlt='first legal shot at0; next launch no earlier than previous launch+45s; obey existing trigger/animation limits as well; do not scale45 by fire-rate',
            primaryAlt='remaining=max(0,remaining-dt); accepted PRIMARY_DIRECT_HIT event reduces remaining by1; launch only at remaining0 then set45; explicit accepted-event scheduling required',
            excluded=['chain280 recipient geometry','expiry250 launch-endpoint overlap','unconditional chain/tick to primary-hit event conversion','primary-alt cycle without accepted primary-hit event interface']))

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages-bin',type=Path,required=True);ap.add_argument('--client-exe',type=Path,required=True);ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():ap.error('choose a new output')
    if sha256(a.client_exe)!=CLIENT_SHA256:raise ValueError('native EXE changed')
    row=next(r for r in json.loads(a.export.read_bytes())['data'] if r['path']==WEAPON)
    out=build_contract(AuditedPackages(a.packages_bin),row);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(out,indent=2)+'\n',encoding='utf-8');print('PASS exact Grimoire 45s independent-alt gate; primary event recovery contract retained')
if __name__=='__main__':main()
