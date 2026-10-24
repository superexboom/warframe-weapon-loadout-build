"""Compare exported base attacks to a pinned reference without guessing forms."""
from __future__ import annotations
import argparse,json,sys,subprocess,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from tools.audit_optimizer_events import NAMES
from wfarsenal.damage import Scenario

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--wfsim",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);args=ap.parse_args()
    if args.output.exists():ap.error("output exists")
    args.output.mkdir(parents=True)
    app._disable_analysis_statics_persistence()
    commit=subprocess.check_output(["git","-C",str(args.wfsim),"rev-parse","HEAD"],text=True).strip()
    meta=args.output/"meta.json"
    blank=args.output/"empty.json";blank.write_text("{}")
    subprocess.run(["node",str(ROOT/"tools/run_reference_wasm.mjs"),str(args.wfsim),"/api/meta",str(blank),str(meta)],check=True,stdout=subprocess.DEVNULL)
    raw=json.loads(meta.read_text(encoding="utf-8"));(args.output/"meta-keys.json").write_text(json.dumps(list(raw)))
    # Stable explicit forms match the frozen export's quick/uncharged vector.
    ids={n:n.lower().replace(" ","_") for n in NAMES}
    ids["Nataruk"]="nataruk_perfect"
    known_ids={w["id"] for w in raw["weapons"]}
    local_target=dict(path="audit-neutral",nameEn="Neutral",health=1e12,armour=0,shield=0,overguard=0,baseLevel=1,faction="",statusImmunities=["DT_IMPACT","DT_PUNCTURE","DT_SLASH","DT_FIRE","DT_FREEZE","DT_ELECTRICITY","DT_POISON","DT_GAS","DT_CORROSIVE","DT_VIRAL","DT_RADIATION","DT_EXPLOSION","DT_MAGNETIC"])
    enemy=dict(id="audit_neutral",name="Audit neutral",synthetic=True,scaling_faction="unaffiliated",stats=dict(base_level=1,health=1e12,shield=0,armor=0,overguard=0),body_parts=[dict(name="body",multiplier=1,is_head=False,crit_bonus=False)],status_immunities=["impact","puncture","slash","heat","cold","electricity","toxin","gas","corrosive","viral","radiation","blast","magnetic","void","tau"])
    # Engine doesn't yet expose immunity in the shared replay: zero status via an explicit local stat override; reference uses immune target.
    rows=[];reqs=[]
    for name in NAMES:
        w=next(w for w in app.EXPORTS["weapons"] if w.get("nameEn")==name and (name!="Lato" or w["path"]=="/Lotus/Weapons/Tenno/Pistol/Pistol"))
        if app.optimizer._weapon_type(None,w)=="melee":continue
        if "Kuva" in name:w={**w,"innateElements":[dict(damageType="DT_IMPACT",value=0.25)]}
        w,_=app.optimizer._select_fire_mode(w,0,weapon_type=app.optimizer._weapon_type(None,w))
        from wfarsenal.damage import ModEffect
        fx=[ModEffect("WEAPON_PROC_CHANCE","SET",0.0)]
        st=app.optimizer.apply_mods(w,fx,scenario=Scenario())
        app.optimizer._bind_combat_inputs(st,w,[],fx,Scenario(trigger_policy="emergent"),None)
        ctx=dict(target=local_target,level=1,windowSeconds=30,headshotChance=0)
        ev=app.optimizer._event_window(st,ctx)
        row=dict(name=name,id=ids[name],weapon=w["path"],localPanel=st.total_damage,localRate=st.fire_rate,localDps=ev["windowDps"],localShots=ev["shots"],localReloads=ev["reloads"],unsupported=ev["unsupported"])
        assert ids[name] in known_ids, ids[name]
        req=dict(weapon=ids[name],form="base",evolutions_as_given=True,mods=[],evolutions=[],arcane=[],duration=30,runs=200,headshot_pct=0,enemy=enemy["id"],custom_enemies=[enemy],level=1,steel_path=False,eximus=False,seed=12648430,infinite_ammo=True,aiming=False,assume_max=False,frenzy=False,buffs={},player_at=[0,0],target_at=[0,0.5])
        if name == 'Paris Prime': req['evolutions'] = ['paris_prime_evo1_incarnon_form']
        if name == 'Dual Toxocyst': req.pop('buffs', None)
        if "Kuva" in name:req.update(valence_element="impact",valence_bonus=0.25)
        row["request"]=req;rows.append(row);reqs.append(req)
    inp=args.output/"cases-input.json";inp.write_text(json.dumps(reqs),encoding="utf-8")
    runner=args.output/"batch.mjs"
    runner.write_text("import fs from 'node:fs'; import path from 'node:path'; const [repo,input,output]=process.argv.slice(2); const rel=JSON.parse(fs.readFileSync(path.join(repo,'site/release.json'),'utf8')); const base=path.join(repo,'site/pkg'); const engine=new Function(fs.readFileSync(path.join(base,'wfsim_wasm.'+rel.wasm+'.js'),'utf8')+';return wasm_bindgen;')(); engine.initSync({module:fs.readFileSync(path.join(base,'wfsim_wasm_bg.'+rel.wasm+'.wasm'))}); for(const pack of rel.packs||[]){const err=engine.install_data_bytes(new Uint8Array(fs.readFileSync(path.join(base,pack))));if(err)throw new Error(pack+': '+err);} const rows=JSON.parse(fs.readFileSync(input,'utf8')).map(p=> JSON.parse(engine.api('/api/simulate',JSON.stringify(p)))); fs.writeFileSync(output,JSON.stringify(rows,null,2));",encoding="utf-8")
    out=args.output/"reference-responses.json"
    subprocess.run(["node",str(runner),str(args.wfsim),str(inp),str(out)],check=True)
    results=json.loads(out.read_text(encoding="utf-8"))
    for row,ref in zip(rows,results):
        if not ref.get("ok"):row["referenceError"]=ref
        else:
            actual=ref.get("combatants",[{}])[0].get("weapon")
            assert actual == row["id"], (row["id"], actual)
            row.update(referencePanel=ref["panel"]["total"],referenceRate=ref["panel"]["fire_rate"],referenceDps=ref["dps"],referenceDpsSe=ref["dps_se"],referenceShots=ref["shots"],referenceReloads=ref["reloads"],deltaPercent=100*(row["localDps"]/ref["dps"]-1) if ref["dps"] else None)
        if row.get('referencePanel') is not None:
            row['panelMatches'] = abs(row['localPanel'] - row['referencePanel']) <= 0.02
            row['comparable'] = row['panelMatches']
        print(row["name"],round(row["localDps"],3),round(row.get("referenceDps",0),3),row.get("deltaPercent"),row.get("referenceError"),flush=True)
    (args.output/"comparison.json").write_text(json.dumps(dict(sourceCommit=commit,release=json.loads((args.wfsim/"site/release.json").read_text(encoding="utf-8")),cases=rows),ensure_ascii=False,indent=2)+chr(10),encoding="utf-8")

if __name__=="__main__":main()

