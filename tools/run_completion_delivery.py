"""Resume frozen acceptance and cache work with one controlled publisher."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.run_riven_acceptance_bake import MAX_BAKE_WORKERS,stop_child,write


def cached_regression(output,inputs,version):
    try:
        previous=json.loads((output/'delivery-status.json').read_bytes())
        row=previous['jobs']['regression']
        suites=list(ET.parse(output/'regression.xml').getroot().iter('testsuite'))
        passed=(previous.get('inputs')==inputs and previous.get('cacheVersion')==version
                and row.get('status')=='complete' and row.get('exitCode')==0
                and suites and sum(int(s.get('tests',0)) for s in suites)>0
                and all(int(s.get('failures',0))==0 and int(s.get('errors',0))==0 for s in suites))
        return {**row,'reused':True} if passed else None
    except (OSError,ValueError,KeyError,TypeError,ET.ParseError):
        return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--acceptance',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='Reuse a passed regression with matching inputs and version')
    parser.add_argument('--allow-full-bake',action='store_true',help='Use only after explicit user authorization for full-roster generation')
    args=parser.parse_args()
    if not args.allow_full_bake:
        parser.error('full-roster delivery requires explicit user authorization and --allow-full-bake')
    import app
    inputs=app._analysis_inputs_fingerprint()
    previous_regression=cached_regression(args.output,inputs,app.ANALYSIS_STATICS_CACHE_VERSION) if args.resume else None
    if args.resume and previous_regression is None:
        parser.error('resume requires a passed regression with matching inputs and cache version')
    args.output.mkdir(parents=True,exist_ok=True)
    status=dict(status='running',pid=os.getpid(),inputs=inputs,cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                startedAt=datetime.now(timezone.utc).isoformat(),workerLimit=MAX_BAKE_WORKERS,jobs={})
    path=args.output/'delivery-status.json'
    env={**os.environ,'WF_ANALYZER_SERIAL':'1','PYTHONUNBUFFERED':'1'}
    children={}
    logs={}

    def launch(name,command):
        logs[name]=(args.output/(name+'-delivery.log')).open('ab')
        children[name]=subprocess.Popen(command,cwd=ROOT,env=env,stdout=logs[name],stderr=subprocess.STDOUT)
        status['jobs'][name]=dict(pid=children[name].pid,command=command,status='running')
        write(path,status)

    def bake(workers):
        # One pool bakes both profiles (a task is one weapon mode, every profile
        # in the same worker), so no profile waits for the other's workers.
        return [sys.executable,'-u','tools/bake-analysis-statics.py','--profile','fast,standard','--workers',str(workers),
                '--fire-modes','--allow-full-bake','--report',str(args.output/'{profile}.json')]

    if previous_regression:
        status['jobs']['regression']=previous_regression
        write(path,status)
    else:
        launch('regression',[sys.executable,'-m','pytest','tests','-q',
                             '--junitxml='+str(args.output/'regression.xml')])
    baking=False
    try:
        while True:
            if app._analysis_inputs_fingerprint()!=inputs:
                status['status']='failed-inputs-changed'
                return 1
            for name,child in list(children.items()):
                if child.poll() is not None and status['jobs'][name]['status']=='running':
                    status['jobs'][name].update(status='complete' if child.returncode==0 else 'failed',exitCode=child.returncode)
                    logs[name].close()
                    write(path,status)
            failed=[name for name,row in status['jobs'].items() if row['status']=='failed']
            if failed:
                status.update(status='failed',failedJobs=failed)
                return 1
            if status['jobs']['regression']['status']=='complete' and not baking:
                launch('acceptance',[sys.executable,'-u','tools/audit_riven_analysis_context.py','--extra-weapons','--output',str(args.acceptance)])
                # Reserve one compute slot for the serial search acceptance.
                from wfarsenal import parallel
                launch('bake',bake(max(1,min(parallel.default_workers(),MAX_BAKE_WORKERS)-1)))
                baking=True
            if not baking:
                time.sleep(5)
                continue
            if all(status['jobs'][name]['status']=='complete' for name in ('regression','acceptance','bake')):
                command=[sys.executable,'tools/validate_baked_statics.py','--bake',str(args.output),
                         '--output',str(args.output/'validation.json')]
                result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True)
                (args.output/'validation.log').write_text(result.stdout+result.stderr,encoding='utf-8')
                rows=json.loads((args.acceptance/'summary.json').read_bytes())
                passed=result.returncode==0 and len(rows)>=17 and all(r.get('passed') and r.get('inputFingerprint')==inputs for r in rows)
                status.update(status='complete' if passed else 'failed-final-validation',acceptanceCases=len(rows),
                              finishedAt=datetime.now(timezone.utc).isoformat())
                return int(not passed)
            time.sleep(5)
    except Exception as exc:
        status.update(status='failed-supervisor',error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        for child in children.values():
            if child.poll() is None:
                stop_child(child)
        for log in logs.values():
            if not log.closed:
                log.close()
        write(path,status)


if __name__=='__main__':
    raise SystemExit(main())
