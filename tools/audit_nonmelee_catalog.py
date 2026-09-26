"""Run resumable automatic-build smoke/replay coverage for all non-melee weapons."""
from __future__ import annotations
import argparse, hashlib, json, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app

def dump(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def weapon_rows():
    for w in app.EXPORTS.get("weapons") or ():
        if not isinstance(w,dict): continue
        path=str(w.get("path") or "")
        slot=str(w.get("slot") or "").casefold()
        if path and slot in {"primary","secondary","arch_gun","amp"}:
            yield w

def key(w):
    return hashlib.sha256(str(w["path"]).encode()).hexdigest()[:16]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--profile",choices=("fast","standard","deep"),default="fast")
    ap.add_argument("--force",action="store_true")
    args=ap.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    result_path=args.output/"results.json"
    if result_path.exists():
        rows=json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(rows,list): rows=[]
    else: rows=[]
    done={r.get("path") for r in rows if isinstance(r,dict) and r.get("path")}
    weapons=list(weapon_rows())
    if args.limit>0: weapons=weapons[:args.limit]
    app._disable_analysis_statics_persistence()
    for index,w in enumerate(weapons,1):
        path=w["path"]
        if path in done and not args.force: continue
        t=time.perf_counter()
        row={"path":path,"nameEn":w.get("nameEn"),"slot":w.get("slot"),"isIncarnon":bool(w.get("isIncarnon") or w.get("incarnon")),"startedAt":datetime.now(timezone.utc).isoformat()}
        try:
            modes=w.get("fireModes") or [{}]
            mode_indices=list(range(len(modes)))
            # 先审所有显式模式；灵化形态至少用真实循环口径。
            attempts=[]
            for mode in mode_indices:
                payload={"weapon":path,"fireMode":mode,"metric":"killsPerMinute","incarnonCycle":row["isIncarnon"],"aiming":True,"headshotChance":1.0,"steelPath":True,"level":9999,"profile":args.profile}
                try:
                    built=app.build_weapon_payload(payload)
                    b=built.get("build") or {}
                    attempts.append({"fireMode":mode,"ok":True,"mods":[m.get("path") for m in b.get("mods") or []],"objectiveScore":b.get("objectiveScore"),"unsupported":built.get("unsupported") or [],"skipped":built.get("skipped") or [],"build":b})
                except Exception as exc:
                    attempts.append({"fireMode":mode,"ok":False,"error":f"{type(exc).__name__}: {exc}"})
            row["attempts"]=attempts
            row["ok"]=any(a.get("ok") for a in attempts)
        except Exception as exc:
            row["ok"]=False; row["error"]=f"{type(exc).__name__}: {exc}"; row["traceback"]=traceback.format_exc()
        row["seconds"]=round(time.perf_counter()-t,3)
        rows=[r for r in rows if not (isinstance(r,dict) and r.get("path")==path)]
        rows.append(row); dump(result_path,rows)
        print(f"[{index}/{len(weapons)}] {row.get('nameEn')} modes={len(row.get('attempts') or [])} ok={row.get('ok')} sec={row['seconds']}",flush=True)
    dump(args.output/"meta.json",{"recordedAt":datetime.now(timezone.utc).isoformat(),"profile":args.profile,"weaponCount":len(weapons),"exportDir":str(app.EXPORT_DIR),"contract":"non-melee primary/secondary/arch_gun/amp; KPM event objective; all explicit fire modes; incarnonCycle for incarnon weapons"})
    print(json.dumps({"rows":len(rows),"ok":sum(bool(r.get("ok")) for r in rows),"failed":sum(not bool(r.get("ok")) for r in rows)},ensure_ascii=False))
if __name__=="__main__": main()
