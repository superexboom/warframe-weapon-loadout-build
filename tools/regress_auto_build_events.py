from pathlib import Path
import sys,json,time,traceback,argparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
def main():
    app._disable_analysis_statics_persistence()
    ap=argparse.ArgumentParser(description='Compare actual automatic builds to manual event replay')
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--full',action='store_true',help='Use eight slots instead of two')
    ap.add_argument('--archguns',action='store_true',help='Audit ground Arch-guns with primary/secondary Arcanes')
    ap.add_argument('--community',action='store_true',help='Audit newly sampled ranged weapons with their relevant arcanes')
    ap.add_argument('--enervate',action='store_true',help='Use Secondary Enervate in the Arch-gun regression')
    ap.add_argument('--weapons',nargs='+',help='Restrict the named regression weapons')
    args=ap.parse_args()
    out=args.output
    if out.exists(): ap.error('output exists; preserve earlier evidence')
    out.parent.mkdir(parents=True,exist_ok=True)
    rows=[]
    names=['Braton Prime','Burston Prime','Torid','Felarx','Mausolon','Nataruk','Lex Prime','Nikana Prime']
    if args.archguns:names=['Imperator Vandal','Mausolon','Kuva Grattler','Larkspur Prime','Cyngas','Morgha']
    if args.community:names=['Ignis Wraith','Amprex','Kuva Nukor','Tenet Cycron','Baza Prime','Trumna Prime']
    if args.enervate and not args.archguns: ap.error('--enervate requires --archguns')
    if args.weapons:
     if not set(args.weapons)<=set(names):ap.error('unknown regression weapon')
     names=args.weapons
    for name in names:
     w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
     mode=1 if name in ['Burston Prime','Torid'] else 0
     p=dict(weapon=w['path'],fireMode=mode,metric='attackDps' if name=='Nikana Prime' else 'sustainedDps',profile='fast',slotCount=8,maxFill=8 if args.full else 2,minFill=7 if args.full else 2,mods=[],enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=0.5,aiming=True,incarnonCycle=mode==1,triggerPolicy='emergent',externalBuffs=[{'id':'roar','value':0.5}])
     if name=='Burston Prime':p['riven']={'slot':3,'polarity':'AP_ATTACK','stats':[{'code':'1','value':100,'negative':False},{'code':'3','value':91.008,'negative':True}]}
     if name in ['Braton Prime','Burston Prime']:
      arc=next(a for a in app.MANUAL_ARCANES if a.get('nameEn')=='Primary Merciless')
      p['arcanes']=[{'path':arc['path'],'rank':5}]
     if args.archguns:
      p['arcanes']=[{'path':next(a['path'] for a in app.MANUAL_ARCANES if a.get('nameEn')==n),'rank':5} for n in ['Primary Crux','Secondary Enervate' if args.enervate else 'Cascadia Flare']]
      p['externalBuffs']=[]
      p['headshotChance']=1
      if name=='Kuva Grattler':p.update(innateElement='DT_MAGNETIC',innateElementValue=0.6)
     if args.community:
      arcane='Secondary Enervate' if name in ['Kuva Nukor','Tenet Cycron'] else 'Primary Crux'
      p['arcanes']=[{'path':next(a['path'] for a in app.MANUAL_ARCANES if a.get('nameEn')==arcane),'rank':5}]
      p['externalBuffs']=[]
      p['headshotChance']=1
      if name in ['Kuva Nukor','Tenet Cycron']:p.update(innateElement='DT_MAGNETIC',innateElementValue=.6)
     t=time.perf_counter();row=dict(name=name,request=p)
     try:
      res=app.build_weapon_payload(p);build=res['build']
      mods=[{'path':m['path'],'rank':m['rank'],'slot':m.get('slot',i)} for i,m in enumerate(build['mods'])]
      manual={**p,'mods':mods,'incarnonChoices':res['incarnonChoices'],'exilus':res.get('exilus')}
      if build.get('riven'):manual['riven']=build['riven']
      slots=[None]*8
      for m in build['mods']:slots[m.get('slot',build['mods'].index(m))]=m.get('polarity') or app.MANUAL_MODS_BY_PATH[m['path']].get('polarity')
      if manual.get('riven'):slots[manual['riven']['slot']]=manual['riven']['polarity']
      manual['slotPolarities']=slots
      mr=app.simulate_manual_payload(manual)
      a=build['objectiveScore'];b=mr['benchmarkTimeline']['killsPerMinute']
      row.update(automatic=a,manual=b,delta=a-b,passed=abs(a-b)<max(1e-7,abs(b)*1e-8),build=build,manualRequest=manual,unsupported=res['unsupported'],model=res['scoringModel'])
     except Exception as e:row.update(error=str(e),traceback=traceback.format_exc(),passed=False)
     row['seconds']=time.perf_counter()-t;rows.append(row)
     out.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
     print(name,row.get('automatic'),row.get('manual'),row.get('delta'),row.get('error'),row['seconds'],flush=True)

    if any(not row.get('passed') for row in rows):raise SystemExit(1)

if __name__ == '__main__':
    main()
