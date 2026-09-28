"""Audit real eight-slot builds for the remaining-event round, including Torid cycles."""
from __future__ import annotations
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new evidence file')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    app._disable_analysis_statics_persistence();rows=[]
    cases=[('Torid',0,False),('Torid',1,True),('Tysis',0,False),('Tenora Prime',0,False),('Hema',0,False),('Quanta Vandal',0,False)]
    for name,mode,cycle in cases:
        w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
        p=dict(weapon=w['path'],fireMode=mode,incarnonCycle=cycle,metric='killsPerMinute',profile='fast',slotCount=8,
               level=9999,steelPath=True,aiming=True,headshotChance=0. if name=='Torid' else 1.,
               enemy=app._BENCHMARK_ENEMY_PATH,scenario={'distance':10.},triggerPolicy='emergent')
        if name=='Torid':p['incarnonChoices']={'tier2':'2-1','tier3':'3-2','tier4':'4-2'}
        row=dict(name=name+(' cycle' if cycle else ' base'),request=p,inputFingerprint=app._analysis_inputs_fingerprint())
        start=time.perf_counter()
        try:
            built=app.build_weapon_payload(p);b=built['build']
            manual={**p,'mods':[dict(path=m['path'],rank=m['rank'],slot=m.get('slot',i)) for i,m in enumerate(b['mods'])],
                    'incarnonChoices':built.get('incarnonChoices') or {},'slotPolarities':[None]*8}
            if b.get('exilus'):manual['exilus']=b['exilus']
            for i,m in enumerate(b['mods']):manual['slotPolarities'][m.get('slot',i)]=m.get('polarity') or app.MANUAL_MODS_BY_PATH[m['path']].get('polarity')
            r=app.simulate_manual_payload(manual);timeline=r['benchmarkTimeline']
            auto=b['objectiveScore'];score=timeline['killsPerMinute']
            row.update(build=b,automatic=auto,manual=score,manualRequest=manual,
                       passed=abs(auto-score)<=max(1e-7,abs(score)*1e-8),unsupported=r.get('unsupported'),
                       shots=timeline['shots'],reloads=timeline['reloads'],transforms=timeline['transforms'],fieldDuration=timeline.get('fieldDuration'))
        except Exception as e:row.update(passed=False,error=type(e).__name__+': '+str(e))
        row['seconds']=time.perf_counter()-start;rows.append(row)
        args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
        print(row['name'],row.get('automatic'),row.get('manual'),row.get('error'),round(row['seconds'],2),flush=True)
    if any(not r['passed'] for r in rows):raise SystemExit(1)
if __name__=='__main__':main()
