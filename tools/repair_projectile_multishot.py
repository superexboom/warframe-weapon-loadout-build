"""Repair per-projectile explosion counts against pinned native package records.

An explosion owned by a spawned projectile happens once for each projectile.
This is different from hitscan impact RadialDamage/MultiShotBuffsRadialDamage.
Only verified matching native amounts are repaired; hitscan and missing records
are recorded, never inferred from a weapon's display name.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import load


def repair_profiles(payload, weapons, package):
    by_path={w['path']:w for w in weapons};changed=[];skipped=[]
    def repair(component, path, fields, label):
        if component.get('takes_multishot') is not False:return
        native=package.resolve(path) if path else None
        if not native:
            skipped.append(dict(label=label,reason='no native projectile',path=path));return
        amount=sum(float(v) for v in component.get('damage',{}).values())
        matched=[field for field in fields if isinstance(native.get(field),dict)
                 and abs(float(native[field].get('Amount',-1))-amount)<=max(.001,amount*1e-5)]
        if not matched:
            skipped.append(dict(label=label,reason='no matching native attack amount',path=path));return
        # Some projectiles carry identical contact and embed-death attacks.
        # Both belong to the same instance and therefore share this count.
        field=matched[0]
        # A weapon-level RadialDamage is not a projectile's own attack.
        if field not in {'ExplosiveAttack','EmbedDeathAttack','AttackData'}:
            skipped.append(dict(label=label,reason='hitscan impact contract',path=path));return
        component.update(takes_multishot=True,referenceTakesMultishot=False,
                         multishotSource='one native attack per spawned projectile',nativeSource=path,nativeField=field)
        source=package._path_to_file(path)
        if source.is_file():component['nativeMultishotSourceSha256']=hashlib.sha256(source.read_bytes()).hexdigest()
        changed.append(dict(label=label,path=path,field=field,matchedFields=matched,amount=amount))
    for path,entry in payload['auditedAttacks'].items():
        weapon=by_path.get(path,{})
        for mode,spec in [('0',entry),*entry.get('modes',{}).items()]:
            modes=weapon.get('fireModes',[]);index=int(mode)
            exported=modes[index] if index<len(modes) else {}
            projectile=spec.get('projectile') or exported.get('damage',{}).get('projectile')
            for part in [spec.get('radial'),*spec.get('radials',[])]:
                if not part:continue
                source=part.get('nativeSource') or projectile
                if source==path or part.get('nativeField')=='RadialDamage':
                    if part.get('takes_multishot') is False:skipped.append(dict(label=f'{path}:{mode}',reason='hitscan impact contract',path=source))
                    continue
                repair(part,source,[part['nativeField']] if part.get('nativeField') else ['ExplosiveAttack','EmbedDeathAttack'],f'{path}:{mode}:radial')
            for cluster in spec.get('clusters',[]):
                for kind,field in [('direct','AttackData'),('radial','ExplosiveAttack')]:
                    repair(cluster[kind],cluster.get('nativeChild'),[field],f'{path}:{mode}:child-{kind}')
    return dict(changed=changed,skipped=skipped)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True)
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--weapons',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--write',action='store_true')
    args=parser.parse_args();payload=json.loads(args.reference.read_text(encoding='utf-8'))
    result=repair_profiles(payload,json.loads(args.weapons.read_text(encoding='utf-8'))['data'],load(args.build_dir))
    result['build']=args.build_dir.name
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    if args.write:args.reference.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(changed=len(result['changed']),skipped=result['skipped'])))


if __name__=='__main__':main()
