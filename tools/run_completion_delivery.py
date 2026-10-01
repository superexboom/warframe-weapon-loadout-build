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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.run_riven_acceptance_bake import stop_child,write


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--acceptance',type=Path,required=True)
    args=parser.parse_args()
    import app
    inputs=app._analysis_inputs_fingerprint()
    args.output.mkdir(parents=True,exist_ok=True)
    status=dict(status='running',pid=os.getpid(),inputs=inputs,cacheVersion=app.ANALYSIS_STATICS_CACHE_VERSION,
                startedAt=datetime.now(timezone.utc).isoformat(),jobs={})
    path=args.output/'delivery-status.json'
    env={**os.environ,'WF_ANALYZER_SERIAL':'1','PYTHONUNBUFFERED':'1'}
    children={}
    logs={}

    def launch(name,command):
        logs[name]=(args.output/(name+'-delivery.log')).open('ab')
        children[name]=subprocess.Popen(command,cwd=ROOT,env=env,stdout=logs[name],stderr=subprocess.STDOUT)
        status['jobs'][name]=dict(pid=children[name].pid,command=command,status='running')
        write(path,status)

    def bake(profile,workers,shards=False):
        command=[sys.executable,'-u','tools/bake-analysis-statics.py','--profile',profile,'--workers',str(workers),
                 '--fire-modes','--report',str(args.output/(profile+('-shards' if shards else '')+'.json'))]
        return command+(['--shards-only'] if shards else [])

    launch('regression',[sys.executable,'-m','pytest','tests','-q',
                         '--junitxml='+str(args.output/'regression.xml')])
    baking=False
    publishing=False
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
                launch('fast',bake('fast',10))
                launch('standard-shards',bake('standard',6,True))
                baking=True
            if not baking:
                time.sleep(5)
                continue
            if status['jobs']['fast']['status']=='complete' and not publishing:
                child=children['standard-shards']
                if child.poll() is None:
                    stop_child(child)
                    status['jobs']['standard-shards'].update(status='resumed-with-more-workers')
                    logs['standard-shards'].close()
                launch('standard',bake('standard',12))
                publishing=True
            if publishing and all(status['jobs'][name]['status']=='complete' for name in ('regression','acceptance','fast','standard')):
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
