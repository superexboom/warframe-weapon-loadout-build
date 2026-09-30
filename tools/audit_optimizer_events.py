"""Reproduce manual/optimizer event parity across weapon and scenario families."""
from __future__ import annotations
import argparse, json, sys, time, traceback
from pathlib import Path
from dataclasses import replace
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
o = app.optimizer
NAMES = ["Braton Prime", "Soma Prime", "Latron Prime", "Burston Prime", "Boltor Prime", "Ignis Wraith", "Amprex", "Boar Prime", "Kuva Brakk", "Twin Grakatas", "Lato", "Lex Prime", "Torid", "Paris Prime", "Opticor Vandal", "Dual Toxocyst", "Nataruk", "Cinta", "Laetum", "Phenmor", "Felarx", "Kuva Hek", "Corvas Prime", "Mausolon", "Nikana Prime", "Glaive Prime"]

def evaluate_payload(p):
    ctx = app._manual_resolve_sim_context(p)
    common = ctx["common"]
    sc = common['scenario']
    w, _ = o._select_fire_mode(ctx["weapon_record"], common["fire_mode"], weapon_type=ctx["weapon"]["weaponType"])
    if common.get("weapon_override"):
        w = {**w, **common["weapon_override"]}
    shells = o._set_shells(app.EXPORTS["mods"])
    cards = []
    for row in common["mods"]:
        m = o.resolve_record(app.EXPORTS["mods"], row["path"], kind="mod")
        rank = row.get("rank", m.get("maxRank") or 0)
        c = o._mod_card(m, sc, allow_empty=True, set_shell=shells.get(o._set_key(m.get("modSet"))))
        cards.append(replace(c, rank=rank, effects=tuple(o.mod_effects(m, rank, o._steady_state_scenario([m],sc)))))
    arcs = [{"query":r["path"], **{k:v for k,v in r.items() if k != "path"}} for r in ctx["validated_arcanes"]]
    ac,_,_ = o._arcane_card(app.EXPORTS["arcanes"], arcs, w)
    pa = o._merge_passives(ctx["incarnon_card"], ac)
    extra = app._external_buff_effects(p.get("externalBuffs"))
    if extra: pa = o._merge_passives(pa, o._Card("__external__",None,0,tuple(extra),(),0,None))
    rv = o._card_from_lines(o._wire_lines(p["riven"]["stats"])[0]) if p.get("riven") else None
    enemy = common.get("enemy_override") or o.resolve_record(app.EXPORTS["enemies"],common["enemy"],kind="enemy")
    context = {"target":enemy, "level":common["level"], "steel_path":common["steel_path"], "enemy_enhancements":common["enemy_enhancements"], "windowSeconds":30.0, "headshotChance":ctx["headshot_chance"], "armour_strip":common["armour_strip"], "elemental_armour_strip":common["elemental_armour_strip"], "statusRateMultiplier":common["status_rate_multiplier"], "stanceMultiplier":common["damage_rate_multiplier"], "forcedProcs":common["forced_procs"]}
    # Preserve user slot order for parity; _evaluate also searches legal Riven insertion order.
    ordered = list(cards)
    if rv: ordered.insert(int(p["riven"].get("slot",len(ordered))),rv)
    fx = o._effects(([pa] if pa else [])+ordered,sc)
    st = o.apply_mods(w,fx,scenario=sc)
    o._bind_combat_inputs(st,w,ordered,fx,sc,pa)
    score = o._score(st,"killsPerMinute",target_context=context)
    manual = app.simulate_manual_payload(p)
    replay = manual["benchmarkTimeline"]
    event = o._event_window(st,context)
    return {"manual":replay["killsPerMinute"],"optimizer":score,"delta":score-replay["killsPerMinute"],"shots":event["shots"],"transforms":event["transforms"],"unsupported":event["unsupported"],"manualUnsupported":manual.get("unsupported"),"context":{k:v for k,v in context.items() if k!="target"}}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--output",type=Path,required=True);args=ap.parse_args()
    if args.output.exists():ap.error("output exists; preserve earlier evidence")
    args.output.parent.mkdir(parents=True,exist_ok=True)
    app._disable_analysis_statics_persistence()
    rows=[]
    for name in NAMES:
        raw=next(w for w in app.EXPORTS["weapons"] if w.get("nameEn")==name and (name!="Lato" or w["path"]=="/Lotus/Weapons/Tenno/Pistol/Pistol"))
        for mode in sorted(set([0,len(raw["fireModes"])-1])):
            w,_=o._select_fire_mode(raw,mode,weapon_type=o._weapon_type(None,raw))
            pool,_=o._candidate_mods(app.EXPORTS,w,o._scenario("killsPerMinute"))
            wanted=["Serration","Hornet Strike","Point Blank","Rubedo-Lined Barrel","Pressure Point","Speed Trigger","Gunslinger","Shotgun Barrage","Automatic Trigger","Fury","Thermite Rounds","Scorch","Scattering Inferno","Magma Chamber","Volcanic Edge"]
            choices=[]
            for n in wanted:
                matches=[c for c in pool if c.record.get("nameEn")==n and c.record.get("path") in app.MANUAL_MODS_BY_PATH]
                if matches: choices.append(max(matches,key=lambda c:c.drain))
            for aim,cycle,negative in [(False,False,False),(True,mode>0 and bool(raw.get("isIncarnon")),True)]:
                p={"weapon":raw["path"],"fireMode":mode,"mods":[{"path":c.record["path"],"rank":c.rank,"slot":i} for i,c in enumerate(choices[:3])],"enemy":app._BENCHMARK_ENEMY_PATH,"level":9999,"steelPath":True,"headshotChance":1.0 if aim else 0.0,"aiming":aim,"incarnonCycle":cycle,"triggerPolicy":"emergent","slotPolarities":[c.polarity for c in choices[:3]]+[None]*5}
                if negative:p["riven"]={"slot":len(choices[:3]),"stats":[{"code":"1","value":100,"negative":False},{"code":"3","value":91.008,"negative":True}]}
                if "Kuva" in name:p.update(innateElement="DT_IMPACT",innateElementValue=0.25)
                t=time.perf_counter();row={"name":name,"mode":mode,"request":p}
                try:row.update(evaluate_payload(p));row["passed"]=abs(row["delta"])<=max(1e-7,abs(row["manual"])*1e-8)
                except Exception as e:row.update(error=str(e),traceback=traceback.format_exc(),passed=False)
                row["seconds"]=time.perf_counter()-t;rows.append(row)
                print(name,mode,aim,cycle,row.get("delta"),row.get("error"),flush=True)
                args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+chr(10),encoding="utf-8")
    print(json.dumps({"cases":len(rows),"passed":sum(r["passed"] for r in rows)},ensure_ascii=False))

if __name__=="__main__":main()
