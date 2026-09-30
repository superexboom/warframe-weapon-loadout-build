"""Distance-control reference probe; it never enables local spread calculations."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--comparison',type=Path,required=True)
    ap.add_argument('--runtime',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--distance',type=float,default=.5)
    args=ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence directory')
    args.output.mkdir(parents=True)
    report=json.loads(args.comparison.read_text(encoding='utf-8'))
    selected=[c for c in report['cases'] if c['name'].split(' mode')[0] in
              {'Simulor','Synoid Simulor','Arca Plasmor','Talons'} and c.get('request')]
    rows=[]
    for index,c in enumerate(selected):
        reference={**c['request'],'target_at':[0,args.distance]}
        path=args.output/f'{index}-request.json'
        path.write_text(json.dumps(reference,indent=2)+'\n',encoding='utf-8')
        result_path=args.output/f'{index}-response.json'
        subprocess.run(['node',str(ROOT/'tools/run_reference_wasm.mjs'),str(args.runtime),'/api/simulate',str(path),str(result_path)],check=True)
        local={**c['manualRequest'],'scenario':{**c['manualRequest'].get('scenario',{}),'distance':args.distance}}
        manual=app.simulate_manual_payload(local)
        result=json.loads(result_path.read_text(encoding='utf-8'))
        kpm=result['score']*60/result['duration']
        rows.append(dict(name=c['name'],originalManualKpm=c['manualKpm'],originalReferenceKpm=c.get('referenceKpm'),
                         originalDistance=c['request']['target_at'][1],probeDistance=args.distance,
                         probeManualKpm=manual['benchmarkTimeline']['killsPerMinute'],probeReferenceKpm=kpm,
                         contract='diagnostic distance change; original build, ranks and slots kept; local spread remains disabled'))
    (args.output/'summary.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    main()
