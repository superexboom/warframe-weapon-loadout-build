"""Recheck saved automatic builds without rewriting their original provenance."""
import argparse
import json
import math
from pathlib import Path

from audit_optimizer_events import app, evaluate_payload


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('audit',type=Path)
    ap.add_argument('output',type=Path)
    args=ap.parse_args()
    if args.output.exists():
        ap.error('choose a new evidence file')
    app._disable_analysis_statics_persistence()
    original=json.loads(args.audit.read_text(encoding='utf-8'))
    rows=[]
    for weapon in original:
        for attempt in weapon['attempts']:
            if not attempt.get('autoManualPassed'):
                continue
            result=evaluate_payload(attempt['manualRequest'])
            passed=math.isclose(result['manual'],result['optimizer'],rel_tol=1e-9,abs_tol=1e-9)
            passed=passed and math.isclose(result['manual'],attempt['objectiveScore'],rel_tol=1e-9,abs_tol=1e-9)
            rows.append(dict(name=weapon['nameEn'],mode=attempt['fireMode'],passed=passed,
                             originalFingerprint=weapon['fingerprint'],automatic=attempt['objectiveScore'],**result))
    data=dict(inputFingerprint=app._analysis_inputs_fingerprint(),cases=rows,
              passed=sum(r['passed'] for r in rows),total=len(rows),source=str(args.audit))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"{data['passed']}/{data['total']} exact saved builds matched")
    return int(data['passed']!=data['total'])


if __name__=='__main__':
    raise SystemExit(main())
