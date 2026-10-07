import json,glob,sys,time
from pathlib import Path
ROOT=Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable');sys.path.insert(0,str(ROOT))
import app
import wfarsenal.damage as dm
app._disable_analysis_statics_persistence()
SCALE=app.optimizer._health_scale_floor(app._benchmark_target_context())
orig=dm.enemy_defenses
def ed(*a,**k):
    r=dict(orig(*a,**k));r['health']*=SCALE;r['overguard']=0.;return r
dm.enemy_defenses=ed
rows=[]
BYPATH={m['path']:m for m in app.EXPORTS['mods']}
files=sorted(glob.glob(str(ROOT/'.local/cache/riven-statics-archive-dcac3a99a2808ca8-v22-20261001/standard/*.json')))
t0=time.time()
for i,f in enumerate(files):
    d=json.load(open(f,encoding='utf-8'))
    for k,v in d['entries'].items():
        if not k.startswith('{'):continue
        kk=json.loads(k);w=app.CATALOG_WEAPONS_BY_PATH.get(kk['weapon'])
        rec=next((x for x in app.EXPORTS['weapons'] if x['path']==kk['weapon']),None)
        name=(rec or {}).get('nameEn') or kk['weapon']
        mods=[]
        for slot,p in enumerate(v.get('baselineCards') or []):
            m=app.MANUAL_MODS_BY_PATH.get(p)
            if m is None:
                name=(BYPATH.get(p) or {}).get('nameEn')
                m=next((x for x in app.MANUAL_MODS if x.get('nameEn')==name and rec and app.optimizer._mod_matches_weapon(BYPATH[x['path']],rec)),None)
            if m:mods.append(dict(path=m['path'],rank=m.get('maxRank') or 0,slot=slot))
        p=dict(weapon=kk['weapon'],fireMode=kk['fireMode'],mods=mods,arcanes=[],enemy=app._BENCHMARK_ENEMY_PATH,level=170,steelPath=True,headshotChance=float(sys.argv[2]),aiming=True,triggerPolicy='emergent',scenario=dict(distance=.5))
        try:
            bt=app.simulate_manual_payload(p)['benchmarkTimeline'];kills=bt['killsInWindow'];err=None
        except Exception as e:kills=None;err=str(e)[:120]
        rows.append(dict(weapon=name,path=kk['weapon'],fireMode=kk['fireMode'],slot=(rec or {}).get('slot'),kills=kills,error=err,mods=len(mods)))
    if i%50==0:print(i,len(files),round(time.time()-t0),flush=True)
json.dump(dict(scale=SCALE,headshotChance=float(sys.argv[2]),rows=rows),open(sys.argv[1],'w',encoding='utf-8'),ensure_ascii=False,indent=1)
print('done',len(rows))
