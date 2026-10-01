"""Resume real analysis acceptance, then bake fast/standard with coverage gates."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
MAX_BAKE_WORKERS=8


def limited_workers(value) -> int:
    count=int(value)
    if count<1:
        raise ValueError('workers must be positive')
    return min(count,MAX_BAKE_WORKERS)


def write(path: Path, value: dict) -> None:
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temporary.replace(path)


def stop_child(child) -> None:
    import psutil
    try:
        processes=psutil.Process(child.pid).children(recursive=True)
        processes.append(psutil.Process(child.pid))
    except psutil.NoSuchProcess:
        return
    for process in reversed(processes):
        try:
            process.terminate()
        except psutil.NoSuchProcess:
            pass
    _,remaining=psutil.wait_procs(processes,timeout=5)
    for process in remaining:
        try:
            process.kill()
        except psutil.NoSuchProcess:
            pass


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--acceptance',type=Path,required=True)
    ap.add_argument('--workers',type=limited_workers,default=4,help='Parallel workers, capped at 8')
    args=ap.parse_args()
    import app
    inputs=app._analysis_inputs_fingerprint()
    args.output.mkdir(parents=True,exist_ok=True)
    status=dict(status='running',pid=os.getpid(),inputs=inputs,startedAt=datetime.now(timezone.utc).isoformat(),
                phases=[],cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION)
    status_file=args.output/'status.json'
    write(status_file,status)
    env={**os.environ,'WF_ANALYZER_SERIAL':'1','PYTHONUNBUFFERED':'1'}
    commands=[('analysis-acceptance',[sys.executable,'-u','tools/audit_riven_analysis_context.py','--output',str(args.acceptance)])]
    for profile in ('fast','standard'):
        commands.append((profile,[sys.executable,'-u','tools/bake-analysis-statics.py','--profile',profile,
                                 '--workers',str(args.workers),'--fire-modes','--report',str(args.output/(profile+'.json'))]))
    for phase,command in commands:
        entry=dict(phase=phase,status='running',command=command,startedAt=datetime.now(timezone.utc).isoformat())
        status['phases'].append(entry)
        for attempt in range(1,4):
            if phase!='analysis-acceptance':
                command[command.index('--workers')+1]=str(max(1,args.workers//attempt))
            entry['attempt']=attempt
            with (args.output/(phase+'.log')).open('ab') as log:
                child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                entry['childPid']=child.pid
                write(status_file,status)
                while child.poll() is None:
                    if app._analysis_inputs_fingerprint()!=inputs:
                        stop_child(child)
                        entry['status']='inputs-changed'
                        status['status']='failed-inputs-changed'
                        write(status_file,status)
                        return 1
                    time.sleep(5)
                entry['exitCode']=child.returncode
            if child.returncode==0:
                break
            if phase=='analysis-acceptance':
                break
        entry['finishedAt']=datetime.now(timezone.utc).isoformat()
        if entry['exitCode']!=0:
            entry['status']='failed'
            status['status']='failed'
            write(status_file,status)
            return 1
        entry['status']='complete'
        write(status_file,status)
    cache=json.loads(app.ANALYSIS_STATICS_CACHE_PATH.read_text(encoding='utf-8'))
    coverage={profile:sum(isinstance(value,dict) and json.loads(key).get('profile')==profile
                          for key,value in cache['entries'].items()) for profile in ('fast','standard')}
    reports={profile:json.loads((args.output/(profile+'.json')).read_text(encoding='utf-8'))
             for profile in ('fast','standard')}
    passed=(cache['inputs']==inputs and cache['cacheVersion']==app.ANALYSIS_STATICS_CACHE_VERSION
            and all(r['status']=='complete' and not r['failures'] for r in reports.values())
            and all(coverage[p]>=reports[p]['expectedShards'] for p in coverage)
            and all(value.get('contextHash') for value in cache['entries'].values() if isinstance(value,dict)))
    status.update(status='complete' if passed else 'failed-coverage',finishedAt=datetime.now(timezone.utc).isoformat(),
                  cachePath=str(app.ANALYSIS_STATICS_CACHE_PATH),coverage=coverage)
    write(status_file,status)
    return int(not passed)


if __name__=='__main__':
    raise SystemExit(main())
