"""Bind transformed firearm modes to native charge-resource consumption."""
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
from wfarsenal.extract import _sub_behaviour
from tools.refresh_spread_talons import preserve_lines


def refresh(packages,export):
    index = PackageIndex(packages,json.loads((packages.parent/'parents.json').read_bytes()))
    before = export.read_bytes()
    payload = json.loads(before)
    changes,rows = [],[]
    for weapon in payload['data']:
        if not weapon.get('isIncarnon'):
            continue
        old = deepcopy(weapon)
        raw = index.resolve(weapon['path'])
        behaviors = raw.get(weapon.get('fireModeSource') or 'Behaviors') or []
        for mode in weapon.get('fireModes') or []:
            position = mode.get('index',0)
            fire = _sub_behaviour(behaviors[position],'fire:') or {} if position<len(behaviors) else {}
            mode['isIncarnonForm'] = bool(fire.get('ConsumesChargesForFire'))
        if old!=weapon:
            changes.append((old,weapon))
        rows.append(dict(weapon=weapon['path'],forms=[m['isIncarnonForm'] for m in weapon['fireModes']]))
    text = before.decode('utf-8').replace('\r\n','\n')
    for old,new in changes:
        serialize = lambda value: json.dumps(value,ensure_ascii=False,sort_keys=True,indent=1).replace('\n','\n  ')
        previous = serialize(old)
        if text.count(previous)!=1:
            raise ValueError('ambiguous weapon record: '+old['path'])
        text = text.replace(previous,serialize(new),1)
    export.write_bytes(preserve_lines(before,text.encode('utf-8')))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    rows = refresh(args.packages,args.export)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print('mode identity records:',len(rows))


if __name__=='__main__':
    main()
