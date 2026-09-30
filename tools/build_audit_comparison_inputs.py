"""Convert successful catalog audit modes to exact fixed-build comparisons."""
import argparse
import json
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('audit',type=Path)
    ap.add_argument('output',type=Path)
    args=ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence file')
    rows=json.loads(args.audit.read_text(encoding='utf-8'))
    result=[dict(name=f"{r['nameEn']} mode {a['fireMode']}",manualRequest=a['manualRequest'],
                 automatic=a['objectiveScore'],inputFingerprint=r.get('fingerprint'))
            for r in rows for a in r['attempts'] if a.get('autoManualPassed')]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('exact loadouts:',len(result))


if __name__=='__main__':
    main()
