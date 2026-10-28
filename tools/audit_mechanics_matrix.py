"""Bounded catalogue-wide native/reference replay audit, never a correctness oracle.

All declared damaging ranged/companion modes get independent cold-state replays.
Agreement tests Rust migration parity; shared source-mechanic omissions remain
unproven and must be compared with static/game evidence separately.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def cases():
    return [dict(id='body-bare',head=0.,health=3000.,shield=0.,overguard=0.,armour=200.,effects=[]),
            dict(id='head-heat-multi',head=1.,health=3000.,shield=0.,overguard=0.,armour=200.,effects=[
                ('WEAPON_FIRE_DAMAGE','ADD',.6,'DT_FIRE'),('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2,None),
                ('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',.6,None)]),
            dict(id='mixed-corrosive-pools',head=.5,health=3000.,shield=800.,overguard=1200.,armour=2700.,effects=[
                ('WEAPON_ELECTRICITY_DAMAGE','ADD',.6,'DT_ELECTRICITY'),('WEAPON_POISON_DAMAGE','ADD',.6,'DT_POISON'),
                ('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',1.2,None)]),
            dict(id='blast-multi',head=.5,health=1200.,shield=0.,overguard=0.,armour=0.,effects=[
                ('WEAPON_FIRE_DAMAGE','ADD',.6,'DT_FIRE'),('WEAPON_FREEZE_DAMAGE','ADD',.6,'DT_FREEZE'),
                ('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2,None)])]


def evaluate(task):
    path,modes,window=task
    os.environ['WF_ANALYZER_SERIAL']='1'
    import app
    from wfarsenal import optimizer as o,native_replay,mods_native,search_combat
    from wfarsenal.damage import ModEffect,Scenario
    app._disable_analysis_statics_persistence()
    app._refresh_analysis_statics_cache_if_newer=lambda:None
    fingerprint=app._analysis_inputs_fingerprint()
    raw=o.resolve_record(app.EXPORTS['weapons'],path,kind='weapon')
    result=dict(path=path,name=raw.get('nameEn'),fingerprint=fingerprint,modes=[],elapsedSeconds=0.)
    start=time.perf_counter()
    for mode in modes:
        for case in cases():
            row=dict(mode=mode,case=case['id'])
            try:
                values=[]
                for native in (False,True):
                    native_replay.ENABLED=native
                    # Compare the replay engines against the same current mod
                    # preparation; ModsPrep has its own independent parity suite.
                    weapon=o._select_fire_mode(raw,mode,weapon_type=o._weapon_type(None,raw))[0]
                    scenario=Scenario(trigger_policy='emergent',aiming=True)
                    effects=[ModEffect(a,b,c,damage_type=d) for a,b,c,d in case['effects']]
                    stats=o.apply_mods(weapon,effects,scenario=scenario)
                    o._bind_combat_inputs(stats,weapon,(),effects,scenario)
                    target=dict(baseLevel=1,faction='Grineer',health=case['health'],shield=case['shield'],
                                overguard=case['overguard'],armour=case['armour'],
                                hitProxies=[dict(part='HEAD',damageAtten=2.,criticalMultiplier=2.)])
                    context=dict(target=target,level=1,windowSeconds=window,headshotChance=case['head'])
                    search_combat._REPLAYS.clear()
                    began=time.perf_counter();before=native_replay.STATS['native']
                    replay=search_combat.window(stats,context,score_only=True)
                    values.append(dict(seconds=time.perf_counter()-began,
                        nativeUsed=native_replay.STATS['native']>before,
                        scores={k:replay.get(k) for k in ('killsPerMinute','windowDps','totalWindowDamage')},
                        unsupported=replay.get('unsupported') or [],limitations=replay.get('limitations') or []))
                row.update(reference=values[0],native=values[1],passed=values[0]['scores']==values[1]['scores'],
                           nativeUsed=values[1]['nativeUsed'])
            except Exception as exc:
                row.update(passed=False,error=type(exc).__name__+': '+str(exc))
            result['modes'].append(row)
    result['elapsedSeconds']=time.perf_counter()-start
    result['inputsStable']=fingerprint==app._analysis_inputs_fingerprint()
    return result


def summarize(result):
    from collections import Counter
    rows=result['rows']
    actual=sum(len(r.get('modes',[])) for r in rows)
    failed=sum(not m.get('passed',False) for r in rows for m in r.get('modes',[]))
    worker_errors=sum(bool(r.get('error')) for r in rows)
    identity=result['identity']['inputs']
    changed=any(not r.get('inputsStable') or r.get('fingerprint')!=identity for r in rows)
    seen=Counter((r.get('path'),m.get('mode'),m.get('case')) for r in rows for m in r.get('modes',[]))
    expected={tuple(row) for row in result.get('expectedIdentities',[])}
    missing=sorted(expected-set(seen));extra=sorted(set(seen)-expected) if expected else []
    duplicates=[key for key,n in seen.items() if n>1]
    complete=(result['expectedCases']>0 and len(rows)==result['expectedWeapons'] and actual==result['expectedCases']
              and not missing and not extra and not duplicates)
    fallback=sum(not m.get('nativeUsed') for r in rows for m in r.get('modes',[]))
    return dict(weapons=len(rows),cases=actual,failed=failed,workerErrors=worker_errors,
        nativeFallback=fallback,nativeCoverageComplete=fallback==0,
        changedInputs=changed,coverageComplete=complete,missing=missing,extra=extra,duplicates=duplicates,
        passed=complete and not failed and not worker_errors and not changed and not fallback)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--window',type=float,default=4.)
    ap.add_argument('--weapon',action='append')
    ap.add_argument('--limit',type=int)
    args=ap.parse_args()
    if args.output.exists():ap.error('new evidence file required')
    import app
    tasks=[]
    for w in app.EXPORTS['weapons']:
        slot=w.get('slot')
        if slot not in ('primary','secondary','arch_gun','companion'):continue
        if slot=='companion' and '/Lotus/Types/Game/LotusMeleeWeapon' in w.get('ancestry',[]):continue
        if args.weapon and w.get('nameEn') not in args.weapon and w['path'] not in args.weapon:continue
        modes=[i for i,m in enumerate(w.get('fireModes') or []) if isinstance(m.get('damage'),dict)
               and sum(float(v or 0) for v in m['damage'].get('types',{}).values())>0
               and m.get('behaviorKind')!='auxiliary-melee']
        if modes:tasks.append((w['path'],modes,args.window))
    if args.limit:tasks=tasks[:args.limit]
    identity=dict(inputs=app._analysis_inputs_fingerprint(),sourceCommit=__import__('subprocess').check_output(
        ['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),nativeSha256=hashlib.sha256(
        (ROOT/'vendor/wfarsenal/wfcore.pyd').read_bytes()).hexdigest(),toolSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    result=dict(schema=1,scope='native-Python-parity-not-gameplay-validation',identity=identity,
                expectedWeapons=len(tasks),expectedCases=sum(len(t[1])*len(cases()) for t in tasks),
                expectedIdentities=[(path,mode,case['id']) for path,modes,_ in tasks for mode in modes for case in cases()],
                rows=[],complete=False)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    started=time.perf_counter()
    def save():
        result['elapsedSeconds']=time.perf_counter()-started
        tmp=args.output.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(args.output)
    save()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(evaluate,t):t[0] for t in tasks}
        for i,future in enumerate(as_completed(futures),1):
            try:row=future.result()
            except Exception as exc:row=dict(path=futures[future],error=str(exc),modes=[])
            result['rows'].append(row);save()
            failures=sum(not m['passed'] for m in row.get('modes',[]))
            if failures or i%20==0:print(i,len(tasks),row.get('name'),failures,flush=True)
    result['complete']=True
    result['summary']=summarize(result)
    save();print(json.dumps(result['summary']))
    return int(not result['summary']['passed'])


if __name__=='__main__':raise SystemExit(main())
