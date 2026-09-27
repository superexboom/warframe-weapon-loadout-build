"""Run resumable automatic-build smoke/replay coverage for all non-melee weapons."""
from __future__ import annotations
import argparse, hashlib, json, os, subprocess, sys, time, traceback
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app

def dump(path, value):
    temporary=path.with_name(path.name+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    os.replace(temporary,path)

def ranged_companion(w):
    return (str(w.get('slot') or '').casefold() == 'companion'
            and '/Lotus/Types/Game/LotusMeleeWeapon' not in (w.get('ancestry') or []))

def weapon_rows():
    for w in app.EXPORTS.get("weapons") or ():
        if not isinstance(w,dict): continue
        path=str(w.get("path") or "")
        slot=str(w.get("slot") or "").casefold()
        if path and slot in {"primary","secondary","arch_gun","amp"}:
            yield w

def run_identity(profile):
    inputs=app._analysis_inputs_fingerprint()
    tool=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return dict(schema=2,inputs=inputs,toolSha256=tool,profile=profile,
                contract='event-kpm; all explicit modes; matched manual replay; no external parity claim')

def attempt_status(a):
    if not a.get('ok'):
        error=str(a.get('error') or '')
        if 'not in the portable Riven catalog' in error:
            return 'catalog-absent'
        if 'weapon has no fire modes' in error:
            return 'abstract-modular-placeholder'
        if 'metric' in error and 'unavailable' in error:
            return 'mode-metric-unavailable'
        return 'generation-failed'
    if a.get('manualError'):return 'manual-error'
    if a.get('manualKpm') is None:return 'manual-missing'
    if 'loadout-over-capacity' in (a.get('manualUnsupported') or []):return 'invalid-loadout'
    return 'replay-matched' if a.get('autoManualPassed') else 'replay-mismatch'


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--weapons",nargs="+",help="restrict by exact English name or internal path")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--profile",choices=("fast","standard","deep"),default="fast")
    ap.add_argument("--force",action="store_true")
    ap.add_argument("--start",type=int,default=0,help="zero-based start in the selected weapon list")
    ap.add_argument("--include-companions",action="store_true",help="include companion weapon slots")
    ap.add_argument("--shard",type=int,default=0,help="shard index when --shards is used")
    ap.add_argument("--shards",type=int,default=1,help="number of deterministic shards")
    args=ap.parse_args()
    if args.start < 0 or args.shards < 1 or not 0 <= args.shard < args.shards:
        ap.error("invalid start/shard bounds")
    args.output.mkdir(parents=True,exist_ok=True)
    result_path=args.output/"results.json"
    if result_path.exists():
        rows=json.loads(result_path.read_text(encoding="utf-8"))
        if not isinstance(rows,list): rows=[]
    else: rows=[]
    identity=run_identity(args.profile)
    fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    if rows and not args.force and any(r.get('fingerprint') != fingerprint for r in rows):
        ap.error('existing results use another model/contract; choose a new output or explicitly --force')
    done={r.get('path') for r in rows if r.get('replayComplete') and r.get('fingerprint') == fingerprint}
    weapons=list(weapon_rows())
    if args.include_companions:
        companions=[w for w in app.EXPORTS.get("weapons") or () if isinstance(w,dict) and str(w.get("path") or "") and ranged_companion(w)]
        weapons.extend(companions)
    if args.weapons:
        selected=set(args.weapons)
        found={k for w in weapons for k in (w['path'],w.get('nameEn')) if k in selected}
        if selected-found:ap.error('unknown weapons: '+', '.join(sorted(selected-found)))
        weapons=[w for w in weapons if w['path'] in selected or w.get('nameEn') in selected]
    if args.shards > 1:
        weapons=weapons[args.shard::args.shards]
    if args.start:
        weapons=weapons[args.start:]
    if args.limit>0: weapons=weapons[:args.limit]
    meta=dict(recordedAt=datetime.now(timezone.utc).isoformat(),identity=identity,
        fingerprint=fingerprint,state='running',pid=os.getpid(),
        sourceCommit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        weaponCount=len(weapons),weapons=[w['path'] for w in weapons],
        shard=args.shard,shards=args.shards,start=args.start,exportDir=str(app.EXPORT_DIR))
    dump(args.output/'meta.json',meta)
    app._disable_analysis_statics_persistence()
    for index,w in enumerate(weapons,1):
        path=w["path"]
        if path in done and not args.force: continue
        t=time.perf_counter()
        row={"fingerprint":fingerprint,"path":path,"nameEn":w.get("nameEn"),"slot":w.get("slot"),"isIncarnon":bool(w.get("isIncarnon") or w.get("incarnon")),"startedAt":datetime.now(timezone.utc).isoformat()}
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
                    manual_payload=dict(payload)
                    manual_payload["enemy"]=app._BENCHMARK_ENEMY_PATH
                    manual_payload["level"]=9999
                    manual_payload["steelPath"]=True
                    manual_payload["triggerPolicy"]="emergent"
                    manual_payload["mods"]=[{"path":m.get("path"),"rank":m.get("rank",0),"slot":m.get("slot",i)} for i,m in enumerate(b.get("mods") or [])]
                    manual_payload["incarnonChoices"]=built.get("incarnonChoices") or {}
                    if b.get("riven"):
                        manual_payload["riven"]=b["riven"]
                    if b.get("exilus"):
                        manual_payload["exilus"]=b["exilus"]
                    slots=[None]*8
                    for i,m in enumerate(b.get("mods") or []):
                        slot=int(m.get("slot",i))
                        if 0 <= slot < len(slots):
                            slots[slot]=m.get("polarity") or app.MANUAL_MODS_BY_PATH[m["path"]].get("polarity")
                    if b.get("riven") and isinstance(b["riven"],dict):
                        slot=int(b["riven"].get("slot",len(slots)-1))
                        if 0 <= slot < len(slots): slots[slot]=b["riven"].get("polarity")
                    manual_payload["slotPolarities"]=slots
                    manual_kpm=None; manual_error=None; manual_unsupported=[]
                    try:
                        manual=app.simulate_manual_payload(manual_payload)
                        manual_kpm=(manual.get("benchmarkTimeline") or {}).get("killsPerMinute")
                        manual_unsupported=manual.get("unsupported") or []
                    except Exception as exc:
                        manual_error=f"{type(exc).__name__}: {exc}"
                    auto_score=b.get("objectiveScore")
                    delta=(float(auto_score)-float(manual_kpm)) if auto_score is not None and manual_kpm is not None else None
                    attempts.append({"fireMode":mode,"ok":True,"request":payload,"manualRequest":manual_payload,"mods":[m.get("path") for m in b.get("mods") or []],"objectiveScore":auto_score,"manualKpm":manual_kpm,"autoManualDelta":delta,"autoManualPassed":(abs(delta) <= max(1e-7,abs(float(manual_kpm))*1e-8) if delta is not None else False),"manualError":manual_error,"manualUnsupported":manual_unsupported,"unsupported":built.get("unsupported") or [],"skipped":built.get("skipped") or [],"build":b})
                except Exception as exc:
                    attempts.append({"fireMode":mode,"ok":False,"error":f"{type(exc).__name__}: {exc}"})
            row["attempts"]=attempts
            for attempt in attempts:attempt['status']=attempt_status(attempt)
            row['ok']=bool(attempts) and all(a.get('ok') for a in attempts)
            row['replayComplete']=bool(attempts) and all(a['status']=='replay-matched' for a in attempts)
        except Exception as exc:
            row["ok"]=False; row["error"]=f"{type(exc).__name__}: {exc}"; row["traceback"]=traceback.format_exc()
        row["seconds"]=round(time.perf_counter()-t,3)
        rows=[r for r in rows if not (isinstance(r,dict) and r.get("path")==path)]
        rows.append(row); dump(result_path,rows)
        print(f"[{index}/{len(weapons)}] {row.get('nameEn')} modes={len(row.get('attempts') or [])} ok={row.get('ok')} sec={row['seconds']}",flush=True)
    meta.update(state='complete',finishedAt=datetime.now(timezone.utc).isoformat(),
        replayComplete=sum(bool(r.get('replayComplete')) for r in rows))
    dump(args.output/'meta.json',meta)
    print(json.dumps({"rows":len(rows),"ok":sum(bool(r.get("ok")) for r in rows),"failed":sum(not bool(r.get("ok")) for r in rows)},ensure_ascii=False))
if __name__=="__main__": main()
