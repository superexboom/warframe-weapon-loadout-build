"""Compare fixed public builds with legal negative-duration rolls in both engines."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import local_replay, BATCH_JS


def main():
    folder=ROOT/'.local/reports/riven-recommendation-20261004'
    output=folder/'heat-duration'
    output.mkdir(exist_ok=False)
    app._disable_analysis_statics_persistence()
    reference=ROOT/'.local/wfsim-live-20261004'
    cases=json.loads((folder/'public-reference/comparison.json').read_text(encoding='utf-8'))['cases']
    rows=[];requests=[]
    for case in cases:
        # Keep the published MOD order and positive rolls. Change only curse
        # type/value; on the reference API the actual roll is resolved first.
        for duration_roll in (None,.9,1.,1.1):
            ref=deepcopy(case['referenceRequest'])
            spec=ref['rivens'][0]['spec']
            spec['malus']={'id':'zoom' if duration_roll is None else 'status_duration','roll':duration_roll or .9}
            ref.update(duration=30.,runs=100,assume_max=False)
            tag=case['weapon']+'-'+str(duration_roll)
            inp=output/(tag+'-riven-request.json');resolved=output/(tag+'-riven-response.json')
            inp.write_text(json.dumps({'weapon':case['weapon'],**spec}),encoding='utf-8')
            subprocess.run(['node',str(ROOT/'tools/run_reference_wasm.mjs'),str(reference),'/api/riven',str(inp),str(resolved)],check=True)
            from tools.compare_archgun_board_builds import resolved_riven_payload
            payload=deepcopy(case['manualPayload'])
            family=app.optimizer._weapon_type(None,app.optimizer.resolve_record(app.EXPORTS['weapons'],payload['weapon'],kind='weapon'))
            payload['riven']=resolved_riven_payload(spec,json.loads(resolved.read_text(encoding='utf-8')),payload['riven']['slot'],family)
            local=local_replay(payload,duration=30.)
            row=dict(weapon=case['weapon'],roll=duration_roll,payload=payload,referenceRequest=ref,
                     local=local,localKpm=local['replay']['killsPerMinute'])
            rows.append(row);requests.append(ref)
            print(tag,row['localKpm'],flush=True)
    (output/'requests.json').write_text(json.dumps(requests),encoding='utf-8')
    (output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(output/'batch.mjs'),str(reference),str(output/'requests.json'),str(output/'responses.json')],check=True)
    responses=json.loads((output/'responses.json').read_text(encoding='utf-8'))
    for row,result in zip(rows,responses):row['reference']=result
    (output/'comparison.json').write_text(json.dumps(dict(engineFingerprint=app.ANALYSIS_STATICS_RUNTIME_INPUTS,
        source=json.loads((ROOT/'.local/wfsim-source-20261004-api/capture-source.json').read_text()),
        runtime=json.loads((reference/'source.json').read_text()),rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
