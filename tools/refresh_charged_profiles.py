"""Bind restored charge projectile identities to native charge cadence profiles."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
sys.path.insert(0,str(ROOT))
from tools.refresh_spread_talons import preserve_lines


def refresh(export,reference):
    weapons = json.loads(export.read_bytes())['data']
    before = reference.read_bytes()
    payload = json.loads(before)
    rows = []
    for weapon in weapons:
        for i,mode in enumerate(weapon.get('fireModes') or []):
            if not mode.get('chargedProjectile') and not (mode.get('chargeTime') and mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerCharge'):
                continue
            modes = payload.setdefault('auditedAttacks',{}).setdefault(weapon['path'],{})
            entry = modes if i==0 else modes.setdefault('modes',{}).setdefault(str(i),{})
            entry['directTotal'] = sum((mode.get('damage') or {}).get('types',{}).values())
            entry['projectile'] = mode['damage'].get('projectile')
            entry['allowIncarnon'] = bool(mode.get('isIncarnonForm'))
            seconds = mode.get('chargeTime')
            if seconds and mode.get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerCharge':
                bow = any('Bow' in name or 'Hunting' in name for name in weapon.get('ancestry') or ())
                if bow:
                    entry.update(bow=True,drawSeconds=float(seconds))
                    entry.pop('charge',None)
                else:
                    entry['charge'] = dict(seconds=float(seconds),source='native-ChargeTime')
            rows.append(dict(name=weapon['nameEn'],mode=i,profile=deepcopy(entry)))
    reference.write_bytes(preserve_lines(before,(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    parser.add_argument('--evidence',type=Path,required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence file')
    result = refresh(args.export,args.reference)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('charge profiles:',len(result))


if __name__=='__main__':
    main()
