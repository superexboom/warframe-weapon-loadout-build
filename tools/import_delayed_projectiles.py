"""Import verified isolated Stug embed expiry and Simulor orb expiry clocks."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex


def refresh(packages: Path, export: Path, reference: Path) -> list:
    from tools.refresh_spread_talons import patch_json_bytes, preserve_lines
    pkg = PackageIndex(packages, json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    original = reference.read_bytes()
    data = json.loads(original)
    exported_bytes = export.read_bytes()
    exported = json.loads(exported_bytes)
    rows = []
    for weapon in exported['data']:
        name = weapon.get('nameEn')
        if name not in {'Stug','Simulor','Synoid Simulor','Mutalist Quanta'}:
            continue
        before = deepcopy(weapon)
        for index, mode in enumerate(weapon.get('fireModes') or []):
            damage = mode.get('damage') or {}
            if name == 'Mutalist Quanta':
                for event in mode.get('projectileEvents') or []:
                    if event.get('kind') == 'scriptRadial':
                        event.update(baseSource='shieldDamageData', conditionText='Equip Buried Debts; when the orb is destroyed, explode using its absorbed projectile damage and the augment rank multiplier.')
                continue
            projectile = damage['projectile']
            raw = pkg.resolve(projectile)
            if name == 'Stug':
                if raw.get('EmbedTime') != [1.5,1.5] or raw.get('Embed') != 1:
                    raise ValueError('Stug embed clock changed')
                expected = 200. if index == 2 else 75.
                if damage.get('types') != {'DT_CORROSIVE':expected}:
                    raise ValueError('Stug explosion identity changed')
                delay = 1.5
                notes = ['stug-projectile-stack-lifecycle-unmodeled', 'stug-embed-ticks-unmodeled']
                if index == 2:
                    notes += ['stug-bouncing-child-contact-unmodeled']
                if index == 1:
                    notes += ['stug-full-charge-stack-unmodeled']
            else:
                if raw.get('MaxLife') != 1 or damage.get('source') != 'ExplosiveAttack':
                    raise ValueError('Simulor isolated orb clock changed')
                expected = 240. if name == 'Synoid Simulor' else 200.
                if damage.get('types') != {'DT_MAGNETIC':expected}:
                    raise ValueError('Simulor explosion identity changed')
                delay = 1.
                notes = ['orb-merging-and-singularity-unmodeled','orb-multishot-merging-economy-unmodeled']
            source = pkg._path_to_file(projectile)
            if not source.is_file():
                source = source.with_suffix('.txt')
            profile = dict(name=name, projectile=projectile, directTotal=expected,
                           primaryDelaySeconds=delay, allowIncarnon=index==2 and name=='Stug',
                           scope='isolated projectile at the aimed target; native expiry clock; merging and derived children excluded',
                           nativeSources=[dict(path=projectile,sha256=hashlib.sha256(source.read_bytes()).hexdigest())],
                           sourceBuild=packages.parent.name, unmodeled=notes)
            current = data.setdefault('auditedAttacks',{}).setdefault(weapon['path'],{})
            if index:
                current.setdefault('modes',{})[str(index)] = profile
            else:
                current.update(profile)
            rows.append(dict(name=name,mode=index,profile=profile))
        if weapon != before:
            exported_bytes = patch_json_bytes(exported_bytes,before,weapon)
    reference.write_bytes(preserve_lines(original,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode()))
    export.write_bytes(exported_bytes)
    return rows


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--reference',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    ap.add_argument('--evidence',type=Path,required=True)
    args=ap.parse_args()
    if args.evidence.exists():
        ap.error('choose a new evidence file')
    sys.path.insert(0,str(ROOT))
    rows=refresh(args.packages,args.export,args.reference)
    args.evidence.parent.mkdir(parents=True,exist_ok=True)
    args.evidence.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('verified delayed projectile modes:',len(rows))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
