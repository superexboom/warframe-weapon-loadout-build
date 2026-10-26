"""Bounded GPU-bake audit; never writes/publishes the production cache.

inventory: classify structural replay requirements, not a weapon allowlist.
sample: profile exactly one bake task in memory, including both riven structures.
"""
from __future__ import annotations
import argparse,collections,hashlib,importlib.util,json,os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]


def classify(combat):
    reasons=[]
    for key in ('melee','cycle','onosCharge','manualDetonation','fieldDurationOnEmptyReload',
                'enervate','encumber','empowered','cryogenic','magazineRestore','punctureArmorStrip'):
        if combat.get(key):reasons.append(key)
    sources=combat.get('trigger_sources') or []
    if any(q.get('perEvent',0) for q in sources):reasons.append('event-buffs')
    if combat.get('conditionOverload'):reasons.append('live-condition-overload')
    if combat.get('stugIdealDetonation'):reasons.append('stackable-entities')
    if combat.get('persistentRadials'):reasons.append('persistent-projectiles')
    reasons.extend(combat.get('auditShapes') or [])
    # Structural cost tier only; no complete GPU evaluator is installed.
    hard={'melee','cycle','onosCharge','manualDetonation','enervate','encumber',
          'empowered','magazineRestore','stackable-entities','persistent-projectiles','stackable','lingering','clusters'}
    return ('stateful-cpu-first' if hard.intersection(reasons) else
            'finite-buff-preparation-required' if reasons else 'fixed-form-candidate'),sorted(reasons)


def initialize(output):
    output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.update(WF_ANALYZER_SERIAL='1',WF_ENGINE_WORKERS='1',WF_SEARCH_NO_DEADLINE='1',
                      WF_ANALYSIS_STATICS_CACHE_PATH=str(output.with_suffix('.unused-cache.json')))
    sys.path.insert(0,str(ROOT))
    import app
    app._disable_analysis_statics_persistence();app.ANALYSIS_STATICS_CACHE.clear()
    app._refresh_analysis_statics_cache_if_newer=lambda:None
    return app


def bake_module():
    spec=importlib.util.spec_from_file_location('bake_audit_source',ROOT/'tools/bake-analysis-statics.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def inventory(app,args):
    from wfarsenal.manual_combat import prepare
    from wfarsenal.damage import Scenario
    from wfarsenal.event_profiles import base_profile
    bake=bake_module();rows=[]
    old=json.loads(args.historical.read_text(encoding='utf-8')) if args.historical else {}
    for w in bake._catalog_weapons():
        raw=app.optimizer.resolve_record(app.EXPORTS['weapons'],w['path'],kind='weapon')
        mode=bake._default_analysis_modes(raw)[0]
        selected=app.optimizer._select_fire_mode(raw,mode,weapon_type=app.optimizer._weapon_type(None,raw))[0]
        full={**selected,'fireModes':raw['fireModes']}
        sc=app.optimizer._requested_scenario({},'killsPerMinute')
        try:
            combat=prepare(dict(weapon=full,fire_mode=mode,effects=[],scenario=sc),[],[],cycle_enabled=sc.incarnon_cycle)
            tier,reasons=classify(combat);profile=base_profile(full,mode)
            shapes=[k for k in ('radial','radials','lingering','clusters','stackable','beam','battery','burst','charge','compression','spool') if profile.get(k)]
            if any(k in shapes for k in ('stackable','lingering','clusters')):
                tier='stateful-cpu-first';reasons=sorted(set(reasons+shapes))
            oldsec=(old.get('done',{}).get(w['path']) or {}).get('seconds')
            rows.append(dict(path=w['path'],name=w.get('nameEn'),mode=mode,slot=raw.get('slot'),classTier=tier,reasons=reasons,shapes=shapes,historicalWorkerWall=oldsec))
        except Exception as e:rows.append(dict(path=w['path'],name=w.get('nameEn'),mode=mode,classTier='unresolved-cpu',error=str(e)))
    totals=collections.defaultdict(lambda:dict(jobs=0,matchedHistoricalJobs=0,workerWallSeconds=0.))
    for r in rows:
        t=totals[r['classTier']];t['jobs']+=1
        if r.get('historicalWorkerWall') is not None:t['matchedHistoricalJobs']+=1;t['workerWallSeconds']+=r['historicalWorkerWall']
    return dict(kind='structural-upper-bound-not-device-admission',fingerprint=app._analysis_inputs_fingerprint(),totals=dict(totals),jobs=rows,
                historicalFingerprint=old.get('inputs'),historicalSha256=hashlib.sha256(args.historical.read_bytes()).hexdigest() if args.historical else None)


def sample(app,args):
    from wfarsenal import native_replay,mods_native,status_native,search_session,manual_combat,evaluation_cache,optimizer
    bake=bake_module();w=next(w for w in app.CATALOG['weapons'] if w.get('nameEn')==args.weapon)
    raw=optimizer.resolve_record(app.EXPORTS['weapons'],w['path'],kind='weapon');family=optimizer._weapon_type(None,raw)
    mode=bake._default_analysis_modes(raw)[0];core=native_replay.wfcore
    counters=collections.defaultdict(lambda:[0.,0]);features=collections.defaultdict(lambda:[0.,0]);phase='baseline';native_phases=collections.defaultdict(float)
    def wrap(module,name):
        fn=getattr(module,name)
        def observed(*a,**kw):
            nonlocal phase
            parent=phase
            if name in ('_assess_negatives','_recommend_positive','_best_finalist'):phase=name
            start=time.perf_counter()
            try:
                result=fn(*a,**kw)
                if name=='prepare':
                    from wfarsenal.event_profiles import base_profile
                    profile=base_profile(a[0]['weapon'],a[0]['fire_mode'])
                    result['auditShapes']=[k for k in ('stackable','lingering','clusters') if profile.get(k)]
                return result
            finally:
                counters[name][0]+=time.perf_counter()-start;counters[name][1]+=1;phase=parent
        setattr(module,name,observed)
    for module,name in [(manual_combat,'prepare'),(mods_native,'apply'),(status_native,'score'),(optimizer,'_assess_negatives'),(optimizer,'_recommend_positive'),(optimizer,'_best_finalist')]:wrap(module,name)
    orig=native_replay.trajectory
    def observe_native(stats,target,**kw):
        start=time.perf_counter()
        try:return orig(stats,target,**kw)
        finally:
            elapsed=time.perf_counter()-start;tier,reasons=classify(kw.get('combat') or {})
            features[tier][0]+=elapsed;features[tier][1]+=1;native_phases[phase]+=elapsed
            counters['native_adapter'][0]+=elapsed;counters['native_adapter'][1]+=1
    native_replay.trajectory=observe_native
    core.counters(reset=True,enable=True,only=['packet','pooled','heat','presence','no_status','setup'])
    start,cpu=time.perf_counter(),time.process_time();token=search_session.CANCEL.set(lambda:time.perf_counter()-start>args.seconds)
    structures=[];error=None
    try:
        for n in (3,2):
            before=time.perf_counter()
            payload=dict(weapon=w['path'],fireMode=mode,disposition=float(raw.get('omegaAttenuation') or 1.),profile=args.profile,_bakeStaticsOnly=True,stats=bake._trigger_stats(app,family,float(raw.get('omegaAttenuation') or 1.),n))
            response=app.analyze_payload(payload)
            structures.append(dict(positives=n,seconds=time.perf_counter()-before,searchWork=response.get('searchWork')))
    except search_session.SearchCancelled:error='bounded-prefix-timeout'
    except Exception as e:error=repr(e)
    finally:search_session.CANCEL.reset(token)
    result=dict(kind='in-memory-bake-task-profile',weapon=args.weapon,mode=mode,profile=args.profile,completed=error is None,error=error,
                wallSeconds=time.perf_counter()-start,cpuSeconds=time.process_time()-cpu,structures=structures,
                inclusiveTimers=dict(counters),nativeFeatures=dict(features),nativePhases=dict(native_phases),
                nativeCounters=core.counters(reset=True,enable=False),nativeStats=dict(native_replay.STATS),
                evaluationCache=dict(evaluation_cache.STATS),fingerprint=app._analysis_inputs_fingerprint(),
                nativeSha256=hashlib.sha256(Path(core.__file__).read_bytes()).hexdigest(),staticsEntries=len(app.ANALYSIS_STATICS_CACHE))
    # Inclusive timers overlap; totals are not summed to estimate wall time.
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('mode',choices=['inventory','sample'])
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--historical',type=Path)
    ap.add_argument('--weapon');ap.add_argument('--profile',choices=['fast','standard','deep'],default='fast')
    ap.add_argument('--seconds',type=float,default=240.)
    args=ap.parse_args()
    if args.output.exists():ap.error('choose a new output file')
    if args.mode=='sample' and not args.weapon:ap.error('--weapon required')
    app=initialize(args.output);result=inventory(app,args) if args.mode=='inventory' else sample(app,args)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('jobs','inclusiveTimers','structures')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
