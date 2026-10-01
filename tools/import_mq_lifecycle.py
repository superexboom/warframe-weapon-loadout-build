"""Import the native Mutalist Quanta orb stack and shield-damage transition."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'));sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from tools.refresh_spread_talons import preserve_lines

def main():
    p=argparse.ArgumentParser();p.add_argument('--packages',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json');p.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json');a=p.parse_args()
    if a.evidence.exists(): p.error('choose a new evidence path')
    index=PackageIndex(a.packages,json.loads((a.packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    raw=index.resolve('/Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmStackProjectile')
    source=a.packages/'Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmStackProjectile.txt'
    payload=json.loads(a.reference.read_bytes()); before=a.reference.read_bytes()
    weapon_path='/Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmRifle'
    entry=payload.setdefault('auditedAttacks',{}).setdefault(weapon_path,{}).setdefault('modes',{}).setdefault('1',{})
    def comp(block):
        return {'damage':{block['Type']:float(block['Amount'])},'critChance':.05,'critMultiplier':1.5,'statusChance':float(block.get('ProcChance') or 0),'forcedProcs':block.get('ForcedProcs') or []}
    profile={'kind':'mq','maxStack':int(raw.get('MaxProjectileStack',3)),'initialStack':1,'resetLifeOnStack':bool(raw.get('ResetMaxLifeOnStack')),'stackedLife':float(raw.get('MaxLife',10)),'maxLife':float(raw.get('MaxLife',10)),'attachAtStack':int(raw.get('AttachSpecialAtThisStack') or 3),'stackHitProxyDamage':True,'explosion':comp(raw['ExplosiveAttack']),'merge':comp(raw['StackingAttack']),'mergeDamage':raw.get('StackingDamageRange',[1,6]),'orbRadial':comp(raw['ExplosiveAttack']),'orbRadialBase':float(raw['ExplosiveAttack']['Amount']),'orbMultipliers':[.5,.8,1.1,1.4,1.7,2.], 'nativeSources':[{'path':'/Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmStackProjectile','sha256':hashlib.sha256(source.read_bytes()).hexdigest()},{'path':'/Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmShieldProxy','sha256':hashlib.sha256((a.packages/'Lotus/Weapons/Infested/LongGuns/InfCrpShockSwarm/InfCrpShockSwarmShieldProxy.txt').read_bytes()).hexdigest()}]}
    entry['stackable']=profile;entry['unmodeled']=[x for x in entry.get('unmodeled') or [] if x!='mutalist-quanta-orb-runtime-unmodeled']
    profile['mergeDamage']=[0.,0.]
    profile.pop('orbRadial',None)
    profile.pop('orbRadialBase',None)
    a.reference.write_bytes(preserve_lines(before,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    out={'weapon':weapon_path,'profile':profile,'evidence':'native shieldDamageData -> orb death radial; requires combatState.orbAbsorbedDamage'}
    a.evidence.parent.mkdir(parents=True,exist_ok=True);a.evidence.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('imported mq lifecycle')
if __name__=='__main__': main()
