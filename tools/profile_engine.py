"""cProfile one bench case serially (all work in this process).

    python tools/profile_engine.py <case> <out.prof>

Uses the case table of tools/bench_engine.py; WF_ANALYZER_SERIAL=1 keeps the
pool out so the profile sees every evaluation.
"""
import cProfile
import json
import os
import pstats
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    case, out = sys.argv[1], Path(sys.argv[2])
    os.environ.update(WF_ANALYZER_SERIAL="1", WF_SEARCH_NO_DEADLINE="1",
                      WF_ANALYSIS_STATICS_CACHE_PATH=str(Path(tempfile.mkdtemp()) / "statics.json"))
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tools"))
    import bench_engine
    kind, args = bench_engine.CASES[case]
    namespace: dict = {}
    child = bench_engine.CHILD.split("start = time.perf_counter()")[0]
    sys.argv = ["", str(ROOT), kind, json.dumps(args), os.devnull]
    exec(compile(child, "bench_child", "exec"), namespace)
    runner = namespace[kind]
    profiler = cProfile.Profile()
    profiler.enable()
    runner(args)
    profiler.disable()
    profiler.dump_stats(out)
    stats = pstats.Stats(str(out))
    stats.sort_stats("tottime").print_stats(45)
