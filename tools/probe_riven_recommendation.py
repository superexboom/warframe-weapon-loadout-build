"""Small explicit equipped-build acceptance; never creates roster caches."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new output file')
    app._disable_analysis_statics_persistence()
    request=json.loads(args.request.read_text(encoding='utf-8'))
    started=time.perf_counter()
    result=app.recommend_riven_payload(request)
    checks=[]
    for combo in result['combos'][:4]:
        build=combo['build']
        payload={**request,'mods':[dict(path=m['path'],rank=m['rank'],slot=m['slot']) for m in build['mods']],
                 'riven':build['riven'],'fireMode':result['fireMode'],'incarnonChoices':result['incarnonChoices'],
                 'triggerPolicy':result['triggerPolicy'], 'scenario':result['evaluationScenario'],
                 'exilus':build.get('exilus'), 'slotPolarities':[None]*8}
        for m in build['mods']:
            payload['slotPolarities'][m['slot']]=app.MANUAL_MODS_BY_PATH[m['path']].get('polarity')
        payload['slotPolarities'][build['riven']['slot']]='AP_ATTACK'
        replay=app.simulate_manual_payload(payload)
        score=replay['benchmarkTimeline']['killsPerMinute'] if result['metric']=='killsPerMinute' else replay['moddedStats'][result['metric']]
        checks.append(dict(structure=combo['structure'],stats=combo['stats'],score=combo['score'],replay=score,
                           passed=abs(score-combo['score'])<=1e-7*max(1,score),payload=payload))
    row=dict(request=request,result=result,replays=checks,elapsedSeconds=time.perf_counter()-started,
             engineFingerprint=app.ANALYSIS_STATICS_RUNTIME_INPUTS,passed=bool(checks) and all(c['passed'] for c in checks))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=row['passed'],elapsed=row['elapsedSeconds'],structures=result['structuresEvaluated'],
        top=[dict(structure=c['structure'],stats=[s['code'] for s in c['stats']],score=c['score']) for c in result['combos'][:4]],
        fusion=result['fusionEvaluated'])))
    assert row['passed']


if __name__=='__main__':main()
