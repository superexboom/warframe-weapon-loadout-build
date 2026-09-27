"""Refresh delegated direct impacts in a staged/current export, with provenance."""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _extract_fire_modes


def refresh(packages, export, names):
    index=PackageIndex(packages)
    parents=packages.parent/'parents.json'
    if parents.is_file():index.parents=json.loads(parents.read_text(encoding='utf-8-sig'))
    path=export/'weapons.json'
    original=path.read_bytes()
    doc=json.loads(original)
    changes=[]
    text=original.decode("utf-8").replace(chr(13)+chr(10),chr(10))
    for row in doc['data']:
        if row.get('nameEn') not in names:continue
        modes=_extract_fire_modes(index,row['path'],index.resolve(row['path']))
        for i,(old,new) in enumerate(zip(row.get('fireModes') or [],modes,strict=True)):
            damage=new.get('damage') or {}
            if damage.get('source')!='ImpactBehavior' or damage==old.get('damage'):continue
            if (old.get('damage') or {}).get('source') not in ('ExplosiveAttack','ImpactBehavior'):
                raise ValueError('unexpected previous damage source: '+row['path'])
            sources=[]
            for rawpath in [row['path'],damage['projectile']]:
                f=packages/(rawpath.lstrip('/')+'.txt')
                if not f.is_file():f=f.with_suffix('.json')
                sources.append(dict(path=rawpath,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
            changes.append(dict(path=row['path'],name=row['nameEn'],mode=i,
                before=old.get('damage'),after=damage,packageBuild=packages.parent.name,sources=sources))
            # Preserve unrelated records, mixed historical layout and byte endings.
            before=json.dumps(old['damage'],ensure_ascii=False,indent=1,sort_keys=True).replace(chr(10),chr(10)+' '*5)
            after=json.dumps(damage,ensure_ascii=False,indent=1,sort_keys=True).replace(chr(10),chr(10)+' '*5)
            if text.count(before)!=1:raise ValueError('damage block layout is ambiguous; use a staged export')
            text=text.replace(before,after,1)
            old['damage']=damage
    if changes:
        path.write_bytes(text.replace(chr(10),chr(13)+chr(10)).encode() if b'\r\n' in original else text.encode())
    return changes


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages',type=Path,required=True)
    ap.add_argument('--export',type=Path,required=True)
    ap.add_argument('--names',nargs='+',default=['Sonicor'])
    ap.add_argument('--evidence',type=Path,required=True)
    a=ap.parse_args()
    if a.evidence.exists():ap.error('evidence exists; preserve previous evidence')
    changes=refresh(a.packages,a.export,set(a.names))
    a.evidence.parent.mkdir(parents=True,exist_ok=True)
    a.evidence.write_text(json.dumps(changes,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    print('refreshed impacts:',len(changes))
if __name__=='__main__':main()
