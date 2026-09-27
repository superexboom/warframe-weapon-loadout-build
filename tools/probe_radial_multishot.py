"""Compare the reference's own damage gain from multishot on native projectiles."""
from pathlib import Path
import argparse,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import BATCH_JS

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wfsim',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():ap.error('new evidence directory required')
    a.output.mkdir(parents=True)
    def save(name,obj):(a.output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    foe=dict(id='radial_multishot_probe',name='Neutral multishot probe',synthetic=True,scaling_faction='unaffiliated',
        stats=dict(base_level=1,health=1e12,shield=0,armor=0,overguard=0),
        body_parts=[dict(name='body',multiplier=1,is_head=False,crit_bonus=False)],
        status_immunities=['impact','puncture','slash','heat','cold','electricity','toxin','gas','corrosive','viral','radiation','blast','magnetic','void','tau'])
    requests=[];rows=[]
    for wid,name in [('kompressa','Kompressa'),('cyanex','Cyanex')]:
        w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
        for extra in [False,True]:
            requests.append(dict(weapon=wid,mode='base',mods=['barrel_diffusion'] if extra else [],arcane=[],
                evolutions=[],evolutions_as_given=True,enemy=foe['id'],custom_enemies=[foe],level=1,
                steel_path=False,headshot_pct=0,aiming=False,duration=10,runs=2000,seed=12648430,
                infinite_ammo=True,ammo_drops=False,assume_max=False,player_at=[0,0],target_at=[0,.01]))
        rows.append(dict(weapon=wid,nativePath=w['path'],nativeProjectiles=w['fireModes'][0]['multishot'],
            expectedProjectileRatio=2.2,scope='Same body target, no status or external buffs; only +120% multishot changes'))
    save('requests.json',requests);(a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    results=json.loads((a.output/'responses.json').read_text(encoding='utf-8'))
    for i,row in enumerate(rows):
        b,m=results[i*2:i*2+2]
        assert b['ok'] and m['ok'],(b,m)
        row.update(referenceBaseDps=b['dps'],referenceMultishotDps=m['dps'],ratio=m['dps']/b['dps'],
            baseShots=b['shots'],moddedShots=m['shots'],basePellets=b['pellets'],moddedPellets=m['pellets'],
            baseDpsSe=b.get('dps_se'),moddedDpsSe=m.get('dps_se'))
    release=json.loads((a.wfsim/'site/release.json').read_text(encoding='utf-8'))
    save('summary.json',dict(cases=rows,release=release,sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),
        wasmSha256=hashlib.sha256((a.wfsim/'site/pkg'/('wfsim_wasm_bg.'+release['wasm']+'.wasm')).read_bytes()).hexdigest(),
        localFingerprint=app._analysis_inputs_fingerprint(),contract='Within-reference ratio experiment. Native projectile copies inherit the same radial attack; game runtime measurement not yet performed.'))
    print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
