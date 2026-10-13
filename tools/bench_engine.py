"""Engine timing and exact-output regression harness (Portable).

    python tools/bench_engine.py run  <out.json> [--cases a,b] [--workers N]
    python tools/bench_engine.py compare <before.json> <after.json>

Every case runs in a fresh process with an empty statics cache and the
interactive search budget off (WF_SEARCH_NO_DEADLINE=1), so its output depends
only on the engine. ``compare`` reports cases whose output digest changed and
the wall / CPU time of both runs. CPU time is the case's whole process tree,
so other load on the machine does not count; wall time does.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# name -> (kind, arguments). Analyses use two positive stats at the catalog
# disposition; "fast" keeps one case near a minute.
CASES = {
    "analyze-lato-fast": ("analyze", {"weapon": "Lato", "family": "pistol", "codes": ["D", "1"], "profile": "fast"}),
    "analyze-hek-fast": ("analyze", {"weapon": "Hek", "family": "shotgun", "codes": ["D", "0"], "profile": "fast"}),
    "analyze-soma-standard": ("analyze", {"weapon": "Soma Prime", "family": "rifle", "codes": ["0", "1"], "profile": "standard"}),
    "analyze-nikana-fast": ("analyze", {"weapon": "Nikana Prime", "family": "melee", "codes": ["K", "0"], "profile": "fast"}),
    "build-boltor-fast": ("build", {"weapon": "Boltor Prime", "profile": "fast"}),
    "simulate-set": ("simulate", {"weapons": ["Boltor Prime", "Lex Prime", "Hek", "Nikana Prime", "Paris Prime"]}),
    "mod-gains-boltor": ("gains", {"weapon": "Boltor Prime"}),
}
DEFAULT_CASES = list(CASES)

CHILD = r'''
import json, sys, time
sys.path.insert(0, sys.argv[1])
import app
kind, args, out = sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
weapons = {w.get("nameEn"): w for w in app.CATALOG["weapons"]}

def analyze(a):
    w = weapons[a["weapon"]]
    bases = app.RIVEN_BASE_VALUES[a["family"]]
    d = float(w["disposition"])
    return app.analyze_payload(dict(weapon=w["path"], disposition=d, profile=a["profile"],
        stats=[dict(code=c, value=bases[c] * d, negative=False) for c in a["codes"]]))

def build(a):
    return app.build_weapon_route({"weapon": weapons[a["weapon"]]["path"], "mode": "auto", "profile": a["profile"]})

def simulate(a):
    return [app.simulate_manual_payload(dict(weapon=weapons[n]["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH,
            level=170, steelPath=True)) for n in a["weapons"]]

def gains(a):
    mods = {}
    for row in app.EXPORTS["mods"]:
        mods.setdefault(row.get("nameEn"), row["path"])
    names = ["Serration", "Split Chamber", "Point Strike", "Vital Sense", "Infected Clip", "Cryo Rounds", "Heavy Caliber"]
    picks = ["Hammer Shot", "Hellfire", "Stormbringer", "Bladed Rounds", "Argon Scope", "Wildfire", "Malignant Force",
             "High Voltage", "Rime Rounds", "Thermite Rounds", "Galvanized Chamber", "Galvanized Aptitude",
             "Primed Cryo Rounds", "Critical Delay", "Vile Acceleration", "Speed Trigger", "Primed Bane of Grineer",
             "Rifle Elementalist", "Shred", "Fanged Fusillade", "Primed Shred", "Gilded Truth", "Hunter Munitions"]
    candidates = [mods[n] for n in picks if n in mods]
    return app.mod_gains_payload(dict(weapon=weapons[a["weapon"]]["path"], mods=[dict(path=mods[n], slot=i)
            for i, n in enumerate(names)], level=160, enemy=app._BENCHMARK_ENEMY_PATH, metric="killsPerMinute",
            candidates=candidates, targetSlot=7))

start = time.perf_counter()
result = {"analyze": analyze, "build": build, "simulate": simulate, "gains": gains}[kind](args)
seconds = time.perf_counter() - start
json.dump({"seconds": seconds, "result": result}, open(out, "w", encoding="utf-8"), ensure_ascii=False,
          sort_keys=True, default=str)
'''

# Wall-clock bookkeeping that is not part of the engine's answer.
VOLATILE = {"elapsedSeconds", "budgetSeconds", "responseCache", "qualityCacheHit", "work", "searchWork",
            "exportDir", "engineFingerprint"}


def _strip(value):
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def _tree_cpu(proc) -> float:
    import psutil
    total = 0.0
    for item in [proc, *proc.children(recursive=True)]:
        try:
            t = item.cpu_times()
            total += t.user + t.system
        except psutil.Error:
            pass
    return total


def run_case(name: str, workers: int | None, keep: Path | None = None) -> dict:
    import psutil
    kind, args = CASES[name]
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", WF_SEARCH_NO_DEADLINE="1",
                   WF_ANALYSIS_STATICS_CACHE_PATH=str(Path(tmp) / "statics.json"))
        if workers is not None:
            env["WF_ENGINE_WORKERS"] = str(workers)
        out = Path(tmp) / "out.json"
        child = subprocess.Popen([sys.executable, "-c", CHILD, str(ROOT), kind, json.dumps(args), str(out)],
                                 cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                 text=True, encoding="utf-8", errors="replace")
        proc = psutil.Process(child.pid)
        peak = [0.0]
        last = [0.0]
        stop = threading.Event()

        def sample():
            while not stop.wait(0.25):
                try:
                    last[0] = max(last[0], _tree_cpu(proc))
                    rss = sum(p.memory_info().rss for p in [proc, *proc.children(recursive=True)])
                    peak[0] = max(peak[0], rss)
                except psutil.Error:
                    pass

        sampler = threading.Thread(target=sample, daemon=True)
        sampler.start()
        _out, err = child.communicate()
        stop.set()
        sampler.join()
        if child.returncode:
            raise SystemExit(f"{name} failed:\n{err[-4000:]}")
        data = json.loads(out.read_text(encoding="utf-8"))
    body = json.dumps(_strip(data["result"]), ensure_ascii=False, sort_keys=True, default=str)
    if keep is not None:
        keep.mkdir(parents=True, exist_ok=True)
        (keep / f"{name}.json").write_text(body, encoding="utf-8")
    return {"seconds": round(data["seconds"], 2), "cpuSeconds": round(last[0], 1),
            "peakMemoryMB": round(peak[0] / 2**20), "digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "bytes": len(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("out", type=Path)
    run.add_argument("--cases", default=",".join(DEFAULT_CASES))
    run.add_argument("--workers", type=int)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("before", type=Path)
    cmp_.add_argument("after", type=Path)
    args = parser.parse_args()
    if args.command == "run":
        results = {}
        for name in [c for c in args.cases.split(",") if c]:
            results[name] = run_case(name, args.workers, args.out.with_suffix(".outputs"))
            print(name, json.dumps(results[name]), flush=True)
            args.out.write_text(json.dumps(results, indent=1, sort_keys=True), encoding="utf-8")
        return 0
    before = json.loads(args.before.read_text(encoding="utf-8"))
    after = json.loads(args.after.read_text(encoding="utf-8"))
    changed = 0
    for name in sorted(set(before) & set(after)):
        b, a = before[name], after[name]
        same = b["digest"] == a["digest"]
        changed += not same
        print(f"{name:26s} {'same' if same else 'CHANGED':7s} wall {b['seconds']:8.1f} -> {a['seconds']:8.1f} s"
              f"  cpu {b['cpuSeconds']:8.1f} -> {a['cpuSeconds']:8.1f} s  mem {b['peakMemoryMB']} -> {a['peakMemoryMB']} MB")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
