from pathlib import Path
import argparse,hashlib,json,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import BATCH_JS
from wfarsenal.damage import apply_mods,damage_against

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--wfsim',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():ap.error('output exists; preserve evidence')
    a.output.mkdir(parents=True)
    def save(name,data):
        (a.output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    enemy=dict(id='radial_head_probe',name='Radial head probe',synthetic=True,scaling_faction='unaffiliated',
      stats=dict(base_level=1,health=1e12,shield=0,armor=0,overguard=0),
      body_parts=[dict(name='body',multiplier=1,is_head=False,crit_bonus=False),
                  dict(name='head',multiplier=3,is_head=True,crit_bonus=True)],
      status_immunities=['impact','puncture','slash','heat','cold','electricity','toxin','gas','corrosive','viral','radiation','blast','magnetic','void','tau'])
    target=dict(health=1e12,armour=0,shield=0,overguard=0,baseLevel=1,faction='',headshotMultiplier=3.)
    rows=[];requests=[]
    for wid,name in [('castanas','Castanas'),('sancti_castanas','Sancti Castanas')]:
        w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
        st=apply_mods(w,[])
        row=dict(id=wid,path=w['path'],source=w['fireModes'][0]['damage']['source'],radialOnly=st.radial_only,
            localBodyPerShot=damage_against(st,target,hit_location='body')['perShot'],
            localHeadPerShot=damage_against(st,target,hit_location='head')['perShot'])
        for head in (0,100):
            requests.append(dict(weapon=wid,mode='base',mods=[],arcane=[],evolutions=[],evolutions_as_given=True,
                duration=10,runs=1000,headshot_pct=head,enemy=enemy['id'],custom_enemies=[enemy],level=1,
                steel_path=False,eximus=False,seed=12648430,infinite_ammo=True,aiming=False,assume_max=False,
                frenzy=False,ammo_drops=False,player_at=[0,0],target_at=[0,.5]))
        rows.append(row)
    save('requests.json',requests);(a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    responses=json.loads((a.output/'responses.json').read_text(encoding='utf-8'))
    for i,row in enumerate(rows):
        b,h=responses[2*i:2*i+2]
        assert b['ok'] and h['ok'],(b,h)
        row.update(referenceBodyDps=b['dps'],referenceHeadDps=h['dps'],referenceRatio=h['dps']/b['dps'],
            referenceBodyDpsSe=b.get('dps_se'),referenceHeadDpsSe=h.get('dps_se'),bodyShots=b['shots'],headShots=h['shots'])
    release=json.loads((a.wfsim/'site/release.json').read_text(encoding='utf-8'))
    sources=[]
    for row in rows:
        f=a.wfsim/'data/weapons/secondary'/str(row['id']+'.yaml')
        sources.append(dict(path=f.relative_to(a.wfsim).as_posix(),sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    save('summary.json',dict(sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),
        release=release,wasmSha256=hashlib.sha256((a.wfsim/'site/pkg'/('wfsim_wasm_bg.'+release['wasm']+'.wasm')).read_bytes()).hexdigest(),
        localInputFingerprint=app._analysis_inputs_fingerprint(),sources=sources,cases=rows,
        contract='No mods, no status damage, same neutral target and seed; ONLY headshot percentage changes. Compare within-engine ratios, not total KPM across native modes.'))
    print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
