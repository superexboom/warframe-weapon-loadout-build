"""Merge one model version's audit shards; reject mixed or unversioned evidence."""
from __future__ import annotations
import argparse
import json
from collections import Counter
from pathlib import Path


def merge_runs(inputs):
    rows_by_path={}; sources=[]; expected=set(); fingerprint=None
    for root in inputs:
        root=Path(root); manifest=root/'meta.json'
        if not manifest.is_file():
            raise ValueError(f'missing version manifest: {root}')
        meta=json.loads(manifest.read_text(encoding='utf-8'))
        version=meta.get('fingerprint')
        if not isinstance(version,str) or not version:
            raise ValueError(f'missing model fingerprint: {root}')
        if fingerprint is not None and version!=fingerprint:
            raise ValueError(f'mixed model fingerprints: {root}')
        fingerprint=version
        planned=meta.get('weapons')
        if not isinstance(planned,list) or not all(isinstance(p,str) and p for p in planned):
            raise ValueError(f'missing weapon inventory: {root}')
        expected.update(planned)
        sources.append(dict(path=str(root),state=meta.get('state'),fingerprint=version))
        path=root/'results.json'
        # A freshly started shard legitimately has a manifest but no results.
        data=json.loads(path.read_text(encoding='utf-8')) if path.is_file() else []
        if not isinstance(data,list):
            raise ValueError(f'invalid result list: {root}')
        for row in data:
            if not isinstance(row,dict) or row.get('fingerprint')!=version or row.get('path') not in planned:
                raise ValueError(f'row does not belong to this version/inventory: {root}')
            key=row['path']
            if key in rows_by_path and rows_by_path[key]!=row:
                raise ValueError(f'conflicting duplicate weapon: {key}')
            rows_by_path[key]=row
    rows=sorted(rows_by_path.values(),key=lambda r:(str(r.get('slot')),str(r.get('nameEn')),r['path']))
    attempts=[a for r in rows for a in r.get('attempts',[])]
    successful=[a for a in attempts if a.get('ok')]
    structural=[a for a in attempts if a.get('status') in ('catalog-absent','abstract-modular-placeholder','mode-metric-unavailable')]
    engine=[a for a in attempts if a.get('status') not in ('replay-matched','catalog-absent','abstract-modular-placeholder','mode-metric-unavailable')]
    summary=dict(fingerprint=fingerprint,expectedWeapons=len(expected),weapons=len(rows),
        missingWeapons=sorted(expected-rows_by_path.keys()),
        weaponOk=sum(bool(r.get('ok')) for r in rows),weaponFailed=sum(not r.get('ok') for r in rows),
        attempts=len(attempts),attemptsOk=len(successful),attemptsFailed=len(attempts)-len(successful),
        structuralGaps=len(structural),engineFailures=len(engine),
        structuralGapKinds=Counter(a.get('status') for a in structural).most_common(),
        manualReplayChecked=sum(a.get('manualKpm') is not None for a in successful),
        manualReplayPassed=sum(bool(a.get('autoManualPassed')) for a in successful if a.get('manualKpm') is not None),
        manualReplayFailed=sum(not a.get('autoManualPassed') for a in successful if a.get('manualKpm') is not None),
        manualReplayErrors=sum(bool(a.get('manualError')) for a in successful),
        manualReplayMissing=sum(a.get('manualKpm') is None and not a.get('manualError') for a in successful),
        invalidLoadouts=sum('loadout-over-capacity' in a.get('manualUnsupported',[]) for a in successful),
        verifiedRunWeapons=sum(bool(r.get('replayComplete')) for r in rows),
        externalComparison='not-performed-by-this-audit',
        unsupported=Counter(x for a in successful for x in a.get('unsupported',[])).most_common(),
        manualUnsupported=Counter(x for a in successful for x in a.get('manualUnsupported',[])).most_common(),
        sources=sources)
    summary['allLocalReplayComplete']=bool(expected) and len(rows)==len(expected) and all(r.get('replayComplete') for r in rows) and all(s['state']=='complete' for s in sources)
    return dict(summary=summary,rows=rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('inputs',nargs='+',type=Path)
    args=ap.parse_args()
    try:result=merge_runs(args.inputs)
    except (ValueError,KeyError,TypeError) as exc:ap.error(str(exc))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False))


if __name__=='__main__':main()
