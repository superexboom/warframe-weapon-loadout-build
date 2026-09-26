"""Merge resumable non-melee audit shard outputs into one coverage report."""
from __future__ import annotations
import argparse, json
from collections import Counter
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,required=True); ap.add_argument("inputs",nargs="+",type=Path)
    args=ap.parse_args(); rows_by_path={}; sources=[]
    for root in args.inputs:
        path=root/"results.json"
        if not path.is_file(): continue
        data=json.loads(path.read_text(encoding="utf-8")); sources.append(str(root))
        for row in data if isinstance(data,list) else []:
            if isinstance(row,dict) and row.get("path"): rows_by_path[str(row["path"])] = row
    rows=sorted(rows_by_path.values(),key=lambda r:(str(r.get("slot")),str(r.get("nameEn")),str(r.get("path"))))
    attempts=[a for r in rows for a in (r.get("attempts") or [])]
    successful=[a for a in attempts if a.get("ok")]
    summary={"weapons":len(rows),"weaponOk":sum(bool(r.get("ok")) for r in rows),"weaponFailed":sum(not bool(r.get("ok")) for r in rows),"attempts":len(attempts),"attemptsOk":len(successful),"attemptsFailed":len(attempts)-len(successful),"manualReplayChecked":sum(a.get("manualKpm") is not None for a in successful),"manualReplayPassed":sum(bool(a.get("autoManualPassed")) for a in successful if a.get("manualKpm") is not None),"manualReplayFailed":sum(not bool(a.get("autoManualPassed")) for a in successful if a.get("manualKpm") is not None),"unsupported":Counter(x for a in successful for x in (a.get("unsupported") or [])).most_common(),"manualUnsupported":Counter(x for a in successful for x in (a.get("manualUnsupported") or [])).most_common(),"sources":sources}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({"summary":summary,"rows":rows},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
if __name__=="__main__": main()
