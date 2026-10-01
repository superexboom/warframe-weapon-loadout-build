"""Validate published cache identity, coverage, contexts and numeric payloads."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
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


def mode_identity(context):
    weapon=context.get('weapon')
    mode=context.get('fireMode')
    if not isinstance(weapon,str) or not weapon or type(mode) is not int or mode<0:
        return None
    return context.get('profile'),weapon,mode


def validate(cache,inputs,version,reports,*,expected_entries=None):
    errors=[]
    if cache.get('inputs')!=inputs:
        errors.append('cache-input-fingerprint-mismatch')
    if cache.get('cacheVersion')!=version:
        errors.append('cache-contract-version-mismatch')
    entries=cache.get('entries') or {}
    if not isinstance(entries,dict):
        return dict(passed=False,inputs=inputs,cacheVersion=version,entries=0,
                    coverage={},scoreStatuses={},errors=errors+['invalid-entries'])
    coverage=Counter()
    covered_modes={profile:set() for profile in reports}
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
        if not isinstance(context,dict):
            errors.append('invalid-cache-key:'+key)
            continue
        profile=context.get('profile')
        if profile in reports:
            identity=mode_identity(context)
            if identity is None:
                errors.append('invalid-mode-identity:'+key)
            else:
                covered_modes[profile].add(identity)
            if not value.get('contextHash') or not isinstance(value.get('evaluationTarget'),dict):
                errors.append('missing-evaluation-context:'+key)
            elif not isinstance(value['contextHash'],str) or not re.fullmatch(r'[0-9a-f]{20}',value['contextHash']):
                errors.append('invalid-context-hash:'+key)
        statuses[value.get('scoreStatus','missing')]+=1
        errors.extend('nonfinite:'+key+p for p in nonfinite(value))
        errors.extend('nonfinite-key:'+key+p for p in nonfinite(context))
    coverage.update({profile:len(modes) for profile,modes in covered_modes.items()})
    if expected_entries is not None:
        expected_modes={profile:set() for profile in reports}
        for key,source in expected_entries.items():
            context=json.loads(key)
            identity=mode_identity(context)
            if identity is None or context.get('profile') not in reports:
                errors.append('invalid-source-mode:'+key)
                continue
            expected_modes[context['profile']].add(identity)
            published=entries.get(key)
            if not isinstance(published,dict):
                errors.append('missing-published-context:'+key)
                continue
            if published.get('contextHash')!=source.get('contextHash'):
                errors.append('source-context-hash-mismatch:'+key)
            if published.get('evaluationTarget')!=source.get('evaluationTarget'):
                errors.append('source-evaluation-target-mismatch:'+key)
        for profile,modes in expected_modes.items():
            missing=modes-covered_modes[profile]
            if missing:
                errors.append(profile+':missing-expected-modes')
            if len(modes)!=reports[profile].get('expectedShards'):
                errors.append(profile+':source-mode-count-mismatch')
    for profile,report in reports.items():
        if report.get('inputs')!=inputs or report.get('cacheVersion')!=version:
            errors.append(profile+':report-identity-mismatch')
        if report.get('status')!='complete' or report.get('failures'):
            errors.append(profile+':not-completely-published')
        if coverage[profile]<report.get('expectedShards',1):
            errors.append(profile+':missing-covered-modes')
    return dict(passed=not errors,inputs=inputs,cacheVersion=version,entries=len(entries),
                coverage=dict(coverage),scoreStatuses=dict(statuses),errors=errors,
                verifiedSourceContexts=len(expected_entries) if expected_entries is not None else None)


def expected_shard_entries(app,inputs,version,profiles):
    # Use the bake's catalog and selectable-mode policy, not a count of arbitrary
    # cache contexts. Current shards are the source for the published hash/target.
    spec=importlib.util.spec_from_file_location('completion_bake',ROOT/'tools/bake-analysis-statics.py')
    bake=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bake)
    entries={}
    errors=[]
    for weapon in bake._catalog_weapons():
        raw=app.optimizer.resolve_record(app.EXPORTS['weapons'],weapon['path'],kind='weapon')
        for mode in bake._supported_bake_modes(raw):
            tag=hashlib.sha1(f"{weapon['path']}#{mode}".encode()).hexdigest()[:12]
            for profile in profiles:
                path=bake.SHARD_ROOT/f'riven-statics-shards-{profile}'/(tag+'.json')
                try:
                    shard=json.loads(path.read_bytes())
                except (OSError,ValueError) as exc:
                    errors.append(f'{profile}:unreadable-current-shard:{tag}:{type(exc).__name__}')
                    continue
                if (not isinstance(shard,dict) or shard.get('inputs')!=inputs
                        or shard.get('cacheVersion')!=version or shard.get('profile')!=profile
                        or shard.get('schemaVersion')!=bake.SHARD_SCHEMA_VERSION):
                    errors.append(f'{profile}:shard-identity-mismatch:{tag}')
                    continue
                source=shard.get('entries')
                matched=False
                if isinstance(source,dict):
                    for key,value in source.items():
                        try:
                            context=json.loads(key)
                        except (TypeError,ValueError):
                            continue
                        if (isinstance(context,dict) and isinstance(value,dict)
                                and mode_identity(context)==(profile,weapon['path'],mode)):
                            entries[key]=value
                            matched=True
                if not matched:
                    errors.append(f'{profile}:shard-mode-context-missing:{tag}')
    return entries,errors


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bake',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import app
    path=app.ANALYSIS_STATICS_CACHE_PATH
    raw=path.read_bytes()
    reports={p:json.loads((args.bake/(p+'.json')).read_bytes()) for p in ('fast','standard')}
    inputs=app._analysis_inputs_fingerprint()
    expected,source_errors=expected_shard_entries(app,inputs,app.ANALYSIS_STATICS_CACHE_VERSION,reports)
    result=validate(json.loads(raw),inputs,app.ANALYSIS_STATICS_CACHE_VERSION,reports,
                    expected_entries=expected)
    result['errors'].extend(source_errors)
    result['passed']=not result['errors']
    result.update(cachePath=str(path),cacheSha256=hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return int(not result['passed'])


if __name__=='__main__':
    raise SystemExit(main())
