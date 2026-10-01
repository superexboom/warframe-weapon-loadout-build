"""Inventory inherited native conditions behind firearm evolutions."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _resolve_weapon_reference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence file')
    index=PackageIndex(args.packages,json.loads((args.packages.parent/'parents.json').read_bytes()))
    weapons=json.loads(args.export.read_bytes())['data']
    rows=[]
    for weapon in weapons:
        if weapon.get('slot') not in {'primary','secondary'}:
            continue
        for tier in (weapon.get('incarnon') or {}).get('tiers') or []:
            for branch in tier.get('branches') or []:
                for condition in branch.get('conditionalEffects') or []:
                    for name in condition.get('conditions') or []:
                        try:
                            path,obj=_resolve_weapon_reference(index,branch['path'],name)
                        except (ValueError,OSError) as exc:
                            rows.append(dict(weapon=weapon['path'],name=weapon['nameEn'],branch=branch['id'],reference=name,
                                             path=name,error=str(exc),native={},ancestry=[]))
                            continue
                        source=index._path_to_file(path)
                        if not source.is_file():
                            source=source.with_suffix('.txt')
                        rows.append(dict(weapon=weapon['path'],name=weapon['nameEn'],branch=branch['id'],reference=name,path=path,
                                         ancestry=index.ancestry(path),native=obj,
                                         sha256=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else None))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('condition rows',len(rows),'unique',len({r['path'] for r in rows}))


if __name__=='__main__':
    main()
