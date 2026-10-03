"""Profile targeted user Riven requests without publishing cache changes."""
from __future__ import annotations

import argparse
import cProfile
import json
import os
from pathlib import Path
import pstats
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weapon',choices=['vectis','burston'],required=True)
    parser.add_argument('--profile',choices=['fast','standard'],default='standard')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repeat',type=int,default=1)
    parser.add_argument('--cprofile',action='store_true')
    parser.add_argument('--parallel',action='store_true')
    parser.add_argument('--headshots',type=float,default=0.)
    parser.add_argument('--reported-card',action='store_true')
    args=parser.parse_args()
    if args.output.exists():
        parser.error('choose a new output directory')
    if not args.parallel:
        os.environ['WF_ANALYZER_SERIAL']='1'
    else:
        os.environ.pop('WF_ANALYZER_SERIAL',None)
    import app
    app._disable_analysis_statics_persistence()
    names={'vectis':'Vectis Prime','burston':'Burston Prime'}
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==names[args.weapon])
    values=([('W',231.9,False),('0',154.6,False),('1',123.7,False),('L',41.2,True)]
            if args.weapon=='vectis' else
            [('W',287.5,False),('6',115.,False),('1',153.3,False),('3',91.,True)])
    if args.reported_card and args.weapon=='burston':
        values=[('W',313.2,False),('6',125.2,False),('1',163.8,False),('3',91.,True)]
    request=dict(weapon=weapon['path'],disposition=float(weapon['omegaAttenuation']),
                 stats=[dict(code=c,value=v,negative=n) for c,v,n in values],profile=args.profile,
                 headshotChance=args.headshots)
    args.output.mkdir(parents=True)
    (args.output/'request.json').write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    summaries=[]
    for index in range(args.repeat):
        stages=[]
        started=time.perf_counter()
        report_stage=app._report_analysis_progress
        request['progressToken']='probe-'+args.weapon+'-'+str(index)
        def stage(token,name):
            elapsed=time.perf_counter()-started
            stages.append(dict(stage=name,elapsedSeconds=elapsed))
            (args.output/(f'run-{index}-stages.json')).write_text(json.dumps(stages,indent=2)+'\n',encoding='utf-8')
            print(json.dumps(stages[-1]),flush=True)
            return report_stage(token,name)
        app._report_analysis_progress=stage
        profiler=cProfile.Profile() if args.cprofile else None
        try:
            if profiler:
                profiler.enable()
            result=app.analyze_payload(request)
        finally:
            if profiler:
                profiler.disable()
            app._report_analysis_progress=report_stage
            if profiler:
                profiler.dump_stats(str(args.output/(f'run-{index}.prof')))
                with (args.output/(f'run-{index}-profile.txt')).open('w',encoding='utf-8') as stream:
                    pstats.Stats(profiler,stream=stream).sort_stats('cumulative').print_stats(45)
        elapsed=time.perf_counter()-started
        (args.output/(f'run-{index}-response.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        summaries.append(dict(elapsedSeconds=elapsed,inputs=app.ANALYSIS_STATICS_RUNTIME_INPUTS,
                              metric=result.get('metric'),scoreMetric=result.get('scoreMetric'),
                              searchQuality=result.get('searchQuality'),details=result.get('details'),
                              target=result.get('evaluationTarget'),stages=stages))
        (args.output/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(dict(run=index,elapsedSeconds=elapsed)),flush=True)
    from wfarsenal.parallel import shutdown_pool
    shutdown_pool()


if __name__=='__main__':
    main()
