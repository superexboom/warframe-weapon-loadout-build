"""Small fixed-build ablations against the pinned WFSim runtime."""
from copy import deepcopy
import json
import argparse
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import local_replay,BATCH_JS


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    folder=args.output
    if folder.exists():parser.error('choose a new evidence directory')
    folder.mkdir(parents=True)
    inputs=json.loads((ROOT/'.local/reports/riven-recommendation-20261004/heat-duration/comparison.json').read_text(encoding='utf-8'))['rows']
    requests=[];rows=[]
    for original in inputs:
        if original['roll']!=.9:continue
        for variant in ['original','fixed-incarnon','no-arcanes','no-conditional-mods','no-condition-overload']:
            payload=deepcopy(original['payload']);ref=deepcopy(original['referenceRequest'])
            if variant=='fixed-incarnon':
                # Current WFSim registers only base/cycle as play modes.
                # The fixed form is selected through form, and a short window
                # keeps its pseudo-reload policy outside this comparison.
                ref.pop('mode',None);ref['form']='incarnon';ref['duration']=5.
                payload['scenario']['incarnonCycle']=False
            if variant=='no-arcanes':payload['arcanes']=[];ref['arcane']=[]
            if variant in ['no-conditional-mods','no-condition-overload']:
                selected={'galvanized_shot'} if variant=='no-condition-overload' else {'galvanized_shot','galvanized_scope','galvanized_crosshairs','bladed_rounds','galvanized_diffusion'}
                remove_slots={i for i,m in enumerate(ref['mods']) if m in selected}
                payload['mods']=[m for m in payload['mods'] if m['slot'] not in remove_slots]
                ref['mods']=[m for m in ref['mods'] if m not in selected]
            result=local_replay(payload,duration=float(ref['duration']))
            rows.append(dict(weapon=original['weapon'],variant=variant,payload=payload,local=result))
            requests.append(ref)
    (folder/'ablation-requests.json').write_text(json.dumps(requests),encoding='utf-8')
    (folder/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(folder/'batch.mjs'),str(ROOT/'.local/wfsim-live-20261004'),str(folder/'ablation-requests.json'),str(folder/'ablation-responses.json')],check=True)
    responses=json.loads((folder/'ablation-responses.json').read_text())
    for row,ref in zip(rows,responses):
        row['reference']=ref
        row['referenceKpm']=ref['score']*60/ref['duration']
        row['localKpm']=row['local']['replay']['killsPerMinute']
        print(row['weapon'],row['variant'],round(row['localKpm'],3),round(row['referenceKpm'],3),
              'shots',row['local']['replay']['shots'],ref['shots'],flush=True)
    (folder/'ablations.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
