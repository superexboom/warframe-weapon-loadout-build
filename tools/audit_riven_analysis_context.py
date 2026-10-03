"""Run real Riven searches and replay their exact returned slot order."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app


def request_for(name: str, scenario: dict) -> dict:
    raw=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    wt=app.CATALOG_WEAPONS_BY_PATH[raw['path']]['weaponType']
    disposition=float(raw.get('omegaAttenuation') or 1.)
    bases=app.RIVEN_BASE_VALUES[wt]
    stats=[dict(code=c,value=abs(bases[c]*disposition*.94690625),negative=False) for c in ('D','S','0')]
    stats.append(dict(code='3',value=abs(bases['3']*disposition*.757525),negative=True))
    return dict(weapon=raw['path'],disposition=disposition,stats=stats,profile='fast',
                scenario=scenario,benchmarkTarget=dict(enemy=app._BENCHMARK_ENEMY_PATH,
                    level=9999,steelPath=True,eximus=True,windowSeconds=30.,
                    headshotChance=float(scenario.get('headshotChance',0.))))


def cycle_coverage_passed(name,request,replays):
    required=(name=='Felarx' and request.get('scenario',{}).get('incarnonCycle')
              and request.get('scenario',{}).get('headshotChance',0.)>0.)
    return not required or (request.get('benchmarkTarget',{}).get('headshotChance',0.)>0.
                           and all((replays.get(key) or {}).get('transforms',0)>0
                                   for key in ('baseline','actual','optimal')))


def case_reusable(row,request,inputs):
    return (row.get('inputFingerprint')==inputs and row.get('passed')
            and row.get('request')==request
            and cycle_coverage_passed(row.get('name'),request,row.get('replays') or {}))


def replay_returned(request: dict, result: dict, build: dict) -> dict:
    target=result['evaluationTarget']
    payload={**request,'fireMode':result['fireMode'],'incarnonChoices':result['incarnonChoices'],
             'mods':[dict(path=m['path'],rank=m['rank'],slot=m['slot']) for m in build['mods']],
             'enemy':target['enemyPath'],'level':target['level'],'steelPath':target['steelPath'],
             'enemyEnhancements':target['enemyEnhancements'],'armourStrip':target['armourStrip'],
             'elementalArmourStrip':target['elementalArmourStrip'],'headshotChance':target['headshotChance'],
             'slotPolarities':[None]*8,'metric':'killsPerMinute'}
    payload.pop('stats',None)
    payload.pop('benchmarkTarget',None)
    for mod in build['mods']:
        payload['slotPolarities'][mod['slot']]=app.MANUAL_MODS_BY_PATH[mod['path']].get('polarity')
    if build.get('riven'):
        payload['riven']=build['riven']
        payload['slotPolarities'][build['riven']['slot']]='AP_ATTACK'
    if build.get('exilus'):
        payload['exilus']={k:build['exilus'][k] for k in ('path','rank')}
    innate=result.get('innateElement')
    if innate:
        payload.update(innateElement=innate['damageType'],innateElementValue=innate['value'])
    manual=app.simulate_manual_payload(payload)
    timeline=manual['benchmarkTimeline']
    score=timeline['killsPerMinute']
    expected=build['objectiveScore']
    dps_matches = (build.get('scoringMetric') != 'windowedDps' or math.isclose(
        timeline['windowDps'],build['scoringScore'],rel_tol=1e-8,abs_tol=1e-8))
    return dict(request=payload,objectiveScore=expected,manualKpm=score,
                manualWindowDps=timeline.get('windowDps'), scoringScore=build.get('scoringScore'),
                passed=math.isclose(score,expected,rel_tol=1e-8,abs_tol=1e-8) and dps_matches,
                unsupported=manual.get('unsupported'),shots=timeline['shots'],
                transforms=timeline['transforms'],rivenSlot=(build.get('riven') or {}).get('slot'),
                targetTotalEhp=timeline['targetTotalEhp'],
                manualDetonation=timeline.get('manualDetonation'))


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--limit',type=int)
    ap.add_argument('--extra-weapons',action='store_true',help='Include the additional repaired Incarnon families')
    ap.add_argument('--weapons',nargs='+',help='Run explicit weapon names instead of the default suite')
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    app._disable_analysis_statics_persistence()
    os.environ['WF_ANALYZER_SERIAL']='1'
    cases=[('Torid',{}),('Torid',{'incarnonCycle':True,'distance':10.,'aiming':True}),
           ('Talons',{'detonationDelaySeconds':.5,'detonationBatchSize':2}),
           ('Fulmin Prime',{'distance':10.,'aiming':True}),('Arca Plasmor',{'distance':10.}),
           ('Dera Vandal',{'distance':10.}),('Scourge Prime',{'distance':10.})]
    if args.extra_weapons:
        cases += [('Miter',{}),('Laetum',{}),('Strun Prime',{}),('Zylok Prime',{}),
                  ('Sicarus Prime',{'headshotChance':0.}),('Gorgon',{}),('Synoid Gammacor',{}),
                  ('Dual Toxocyst',{'combatState':{'abilityUses':20,'energyPool':300}})]
        cases += [('Felarx',{}),('Felarx',{'incarnonCycle':True,'headshotChance':1.})]
    if args.limit:
        cases=cases[:args.limit]
    if args.weapons:
        cases=[(name,{}) for name in args.weapons]
    summary=[]
    for index,(name,scenario) in enumerate(cases):
        tag=f'{index:02d}-{name.replace(" ","-").lower()}'
        output=args.output/(tag+'.json')
        request=request_for(name,scenario)
        if output.exists():
            row=json.loads(output.read_text(encoding='utf-8'))
            if case_reusable(row,request,app._analysis_inputs_fingerprint()):
                summary.append(row)
                continue
            ap.error('existing case has another context or failure; choose a new output')
        started=time.perf_counter()
        row=dict(name=name,request=request,inputFingerprint=app._analysis_inputs_fingerprint())
        print('search',tag,flush=True)
        try:
            result=app.analyze_payload(request)
            row['analysis']=result
            row['replays']={key:replay_returned(request,result,result[key]) for key in ('baseline','actual','optimal')}
            row['passed']=all(r['passed'] for r in row['replays'].values())
            row['cycleCoveragePassed']=cycle_coverage_passed(name,request,row['replays'])
            row['passed']=row['passed'] and row['cycleCoveragePassed']
            if not scenario:
                warm=app.analyze_payload(request)
                row['warmAnalysis']=warm
                row['warmReplays']={key:replay_returned(request,warm,warm[key]) for key in ('baseline','actual','optimal')}
                row['passed']=row['passed'] and all(r['passed'] for r in row['warmReplays'].values())
                row['warmContextMatches']=warm['contextHash']==result['contextHash']
                if warm['evaluationTarget']==result['evaluationTarget'] and warm['evaluationScenario']==result['evaluationScenario']:
                    row['passed']=row['passed'] and row['warmContextMatches']
        except Exception as exc:
            row.update(passed=False,error=f'{type(exc).__name__}: {exc}')
        row['elapsedSeconds']=time.perf_counter()-started
        output.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        summary.append(row)
        (args.output/'summary.json').write_text(json.dumps([
            {k:r.get(k) for k in ('name','passed','inputFingerprint','elapsedSeconds','error')}
            for r in summary],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(tag,row['passed'],row.get('error'),round(row['elapsedSeconds'],2),flush=True)
    return int(any(not r['passed'] for r in summary))


if __name__=='__main__':
    raise SystemExit(main())
