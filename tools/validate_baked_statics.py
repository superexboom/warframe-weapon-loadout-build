"""Validate published cache identity, coverage, contexts and numeric payloads."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def nonfinite(value,path=''):
    if isinstance(value,float) and not math.isfinite(value):
        yield path
    elif isinstance(value,dict):
        for key,item in value.items():
            yield from nonfinite(item,path+'/'+str(key))
    elif isinstance(value,list):
        for index,item in enumerate(value):
            yield from nonfinite(item,path+'/'+str(index))


def validate(cache,inputs,version,reports):
    errors=[]
    if cache.get('inputs')!=inputs:
        errors.append('cache-input-fingerprint-mismatch')
    if cache.get('cacheVersion')!=version:
        errors.append('cache-contract-version-mismatch')
    entries=cache.get('entries') or {}
    coverage=Counter()
    statuses=Counter()
    for key,value in entries.items():
        if not isinstance(value,dict):
            errors.append('invalid-entry:'+key)
            continue
        try:
            context=json.loads(key)
        except (TypeError,ValueError):
            errors.append('invalid-cache-key:'+key)
            continue
        profile=context.get('profile')
        if profile in reports:
            coverage[profile]+=1
            if not value.get('contextHash') or not isinstance(value.get('evaluationTarget'),dict):
                errors.append('missing-evaluation-context:'+key)
        statuses[value.get('scoreStatus','missing')]+=1
        errors.extend('nonfinite:'+key+p for p in nonfinite(value))
    for profile,report in reports.items():
        if report.get('inputs')!=inputs or report.get('cacheVersion')!=version:
            errors.append(profile+':report-identity-mismatch')
        if report.get('status')!='complete' or report.get('failures'):
            errors.append(profile+':not-completely-published')
        if coverage[profile]<report.get('expectedShards',1):
            errors.append(profile+':missing-covered-modes')
    return dict(passed=not errors,inputs=inputs,cacheVersion=version,entries=len(entries),
                coverage=dict(coverage),scoreStatuses=dict(statuses),errors=errors)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bake',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import app
    path=app.ANALYSIS_STATICS_CACHE_PATH
    raw=path.read_bytes()
    reports={p:json.loads((args.bake/(p+'.json')).read_bytes()) for p in ('fast','standard')}
    result=validate(json.loads(raw),app._analysis_inputs_fingerprint(),app.ANALYSIS_STATICS_CACHE_VERSION,reports)
    result.update(cachePath=str(path),cacheSha256=hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return int(not result['passed'])


if __name__=='__main__':
    raise SystemExit(main())
