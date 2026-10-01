"""Expand exact native evolution runtime children omitted by compact exports."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _build_effect
from tools.refresh_spread_talons import preserve_lines


def refresh(packages,export):
    index = PackageIndex(packages,json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    before = export.read_bytes()
    payload = json.loads(before)
    replacements, evidence = [], []
    for weapon in payload['data']:
        original = deepcopy(weapon)
        for tier in (weapon.get('incarnon') or {}).get('tiers') or []:
            for branch in tier['branches']:
                raw = index.resolve(branch['path'])
                script = raw.get('Script') or raw.get('ApplyScript') or {}
                # Root Script fields vary; take the already resolved apply
                # record as the identity, then recover child effects from raw.
                from wfarsenal.incarnon_conditions import script_entries
                for script in list(script_entries(branch.get('runtimeScripts'))):
                    if (script.get('Script')=='/Lotus/Scripts/Mods/RequireEnemyCount.lua'
                            and script.get('Function')=='StartMod' and not branch.get('conditionalEffects')):
                        condition=dict(sourcePath=branch['path'],conditionTag=None,conditions=[],duration=None,
                                       maxStacks=script.get('_maxStacks'),runtimeScripts={'apply':script},
                                       effects=deepcopy(branch.get('effects') or []))
                        branch['conditionalEffects']=[condition]
                        evidence.append(dict(name=weapon['nameEn'],id=branch['id'],kind='nearby-enemy-count',condition=condition))
                    if script.get('Script')=='/Lotus/Scripts/Mods/WeaponEquipBuffs.lua' and script.get('Function')=='StartMod' and not branch.get('conditionalEffects'):
                        duration=raw.get('UpgradeDuration')
                        condition=dict(sourcePath=branch['path'],conditionTag=raw.get('ConditionTag'),conditions=[],duration=duration,
                                       maxStacks=1,runtimeScripts={'apply':script},effects=deepcopy(branch.get('effects') or []))
                        branch['conditionalEffects']=[condition]
                        evidence.append(dict(name=weapon['nameEn'],id=branch['id'],kind='equip-buff',condition=condition))
                    if script.get('Script')=='/Lotus/Scripts/Mods/NoEnemiesInRangeBuff.lua' and script.get('Function')=='ApplyUpgrade' and not branch.get('conditionalEffects'):
                        if len(script.get('_values') or [])==len(script.get('_rangeRequired') or [])==1:
                            condition=dict(sourcePath=branch['path']+'/RuntimeNoNearbyEnemy',conditionTag=None,conditions=[],duration=None,maxStacks=1,
                                           runtimeScripts={'apply':script},effects=[dict(upgradeType=script['_upgradeType'],operation=script['_operation'],valuePerRank=script['_values'][0])])
                            branch['conditionalEffects']=[condition]
                            evidence.append(dict(name=weapon['nameEn'],id=branch['id'],kind='no-nearby-enemy',condition=condition))
                    if (script.get('Script')=='/Lotus/Upgrades/Mods/ModOnAimGlideOrSlide.lua'
                            and script.get('Function')=='ModApplied'
                            and script.get('_upgradeType')=='WEAPON_AMMO_CONSUME_RATE'
                            and script.get('_stackingMode')=='ADD' and script.get('_mustMatchWeapon')==1):
                        condition = dict(sourcePath=branch['path'],conditionTag=None,conditions=[],duration=None,maxStacks=1,
                            runtimeScripts={'apply':script},effects=[dict(upgradeType=script['_upgradeType'],
                            operation=script['_stackingMode'],valuePerRank=script['_value'])])
                        if condition not in branch.setdefault('conditionalEffects',[]):
                            branch['conditionalEffects'].append(condition)
                            evidence.append(dict(name=weapon['nameEn'],id=branch['id'],kind='gliding-sliding-ammo',condition=condition))
                for condition in branch.get('conditionalEffects') or []:
                    apply = (condition.get('runtimeScripts') or {}).get('apply') or {}
                    if raw.get('UpgradeChance') is not None:
                        condition['chance']=raw['UpgradeChance']
                    if apply.get('Script')=='/Lotus/Scripts/Mods/NoEnemiesInRangeBuff.lua':
                        condition['sourcePath']=branch['path']+'/RuntimeNoNearbyEnemy'
                    if apply.get('Script')!='/Lotus/Scripts/Mods/OnSelectiveSlotEquipped.lua':
                        continue
                    extras = []
                    for child in apply.get('_extraMods') or []:
                        path = str(Path(condition['sourcePath']).parent/child).replace('\\','/')
                        native = index.resolve(path)
                        if not native or not native.get('Upgrades'):
                            raise ValueError('missing native extra mod: '+path)
                        extras.append(dict(sourcePath=path,effects=[_build_effect(e) for e in native['Upgrades']],
                            conditions=native.get('ConditionalUpgrades') or [],maxStacks=native.get('MaxConditionalStacks'),
                            duration=0 if native.get('IsInfinite') else native.get('UpgradeDuration'),
                            nativeInfinite=bool(native.get('IsInfinite'))))
                    if extras:
                        condition['runtimeExtraMods'] = extras
                        evidence.append(dict(name=weapon['nameEn'],id=branch['id'],kind='equipment-children',children=extras))
        if original!=weapon:
            replacements.append((original,weapon))
    text = before.decode('utf-8').replace('\r\n','\n')
    for old,new in replacements:
        serialize = lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,indent=1).replace('\n','\n  ')
        previous = serialize(old)
        if text.count(previous)!=1:
            raise ValueError('ambiguous weapon record: '+old['path'])
        text = text.replace(previous,serialize(new),1)
    export.write_bytes(preserve_lines(before,text.encode('utf-8')))
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence path')
    result = refresh(args.packages,args.export)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('restored runtime links:',len(result))


if __name__=='__main__':
    main()
