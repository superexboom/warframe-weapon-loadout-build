"""Collect completed projectile-round artifacts with exact byte hashes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence directory')
    sources={
        'auto-results.json':'.local/reports/projectile-extra-auto-20260930/results.json',
        'auto-meta.json':'.local/reports/projectile-extra-auto-20260930/meta.json',
        'current-parity.json':'.local/reports/projectile-delivery-parity-20260930.json',
        'reference-comparison.json':'.local/reports/projectile-extra-reference-final-20260930/comparison.json',
        'reference-distance-probe.json':'.local/reports/projectile-reference-distance-probe-20260930/summary.json',
        'native-stackable.json':'.local/research/cases/wf-projectile-lifecycle-20260930/evidence/native-stackable-verified.json',
        'native-delay-profiles.json':'.local/research/cases/wf-projectile-lifecycle-20260930/evidence/delayed-import.json',
        'talons-mobile.png':'.local/research/cases/wf-projectile-lifecycle-20260930/evidence/talons-mobile-final.png',
    }
    ir=ROOT/'.local/research/cases/wf-projectile-lifecycle-20260930/work/ir-final'
    for path in ir.glob('*.json'):
        sources['ir/'+path.name]=str(path.relative_to(ROOT))
    acceptance=ROOT/'.local/reports/riven-acceptance-v11-20260930'
    for path in acceptance.glob('[0-9][0-9]-*.json'):
        row=json.loads(path.read_text(encoding='utf-8'))
        if row.get('passed'):
            sources['analysis/'+path.name]=str(path.relative_to(ROOT))
    args.output.mkdir(parents=True)
    entries=[]
    for relative,source in sources.items():
        path=ROOT/source
        destination=args.output/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,destination)
        entries.append(dict(path=relative,source=source,size=destination.stat().st_size,
                            sha256=hashlib.sha256(destination.read_bytes()).hexdigest()))
    manifest=dict(createdAt=datetime.now(timezone.utc).isoformat(),
                  sourceCommit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  contract='Exact artifacts; original tool fingerprints and failures are preserved; no full-bake completion claim.',
                  files=entries)
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('hashed artifacts:',len(entries))


if __name__=='__main__':
    main()
