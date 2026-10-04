"""Recheck only the captured discrepancy cases, preserving exact requests."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import local_replay


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new output file')
    source=json.loads(args.input.read_text(encoding='utf-8'))
    app._disable_analysis_statics_persistence()
    rows=[]
    for row in source['rows']:
        current=local_replay(row['payload'],duration=30.)
        ref=row['reference'];reference=ref['score']*60/ref['duration']
        new=current['replay']['killsPerMinute']
        manual=app.simulate_manual_payload(row['payload'])['benchmarkTimeline']['killsPerMinute']
        assert abs(new-manual)<=1e-8*max(new,1)
        rows.append(dict(weapon=row['weapon'],roll=row['roll'],payload=row['payload'],
                         oldKpm=row['localKpm'],kpm=new,manualKpm=manual,referenceKpm=reference,
                         differencePercent=(new/reference-1)*100 if reference else None,
                         local=current,reference=ref,referenceRequest=row['referenceRequest']))
        print(row['weapon'],row['roll'],round(row['localKpm'],4),round(new,4),round(reference,4),flush=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(dict(engineFingerprint=app.ANALYSIS_STATICS_RUNTIME_INPUTS,
        runtime=source['runtime'],source=source['source'],rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
