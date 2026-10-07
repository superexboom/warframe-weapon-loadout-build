"""Full Riven analysis with a given kill-branch count and profile; records stage timings."""
import json, sys, os, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
from wfarsenal import optimizer as op, combat_replay as cr
app._disable_analysis_statics_persistence()
out, name, hs, profile, branches = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4], int(sys.argv[5])
cr.KILL_BRANCHES = branches
weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], weapon['path'], kind='weapon'))
disp = float(weapon['omegaAttenuation'])
card = [('0', False), ('1', False), ('S', False), ('Z', True)]
stats = [dict(code=c, value=round(op.RIVEN_BASE_VALUES[kind][c] * disp * op.theoretical_structure_scale(3, True, negative=n), 1), negative=n) for c, n in card]
request = dict(weapon=weapon['path'], disposition=disp, profile=profile, headshotChance=hs, stats=stats)
calls = dict(n=0, branched=0)
orig_traj, orig_merge = cr._trajectory, cr._merge_branches
def traj(*a, **k):
    calls['n'] += 1; return orig_traj(*a, **k)
def merge(runs):
    calls['branched'] += 1; return orig_merge(runs)
cr._trajectory = traj; cr._merge_branches = merge
stages = []; started = time.perf_counter(); report = app._report_analysis_progress
def stage(token, s):
    stages.append((s, time.perf_counter() - started)); return report(token, s)
app._report_analysis_progress = stage
request['progressToken'] = 'probe'
r = app.analyze_payload(request); el = time.perf_counter() - started
json.dump(dict(weapon=name, hs=hs, profile=profile, branches=branches, seconds=el, trajectories=calls['n'], branchedReplays=calls['branched'],
               stages=stages, response=r), open(out, 'w', encoding='utf-8'), ensure_ascii=False, default=str)
print(name, hs, profile, branches, round(el, 1), calls, flush=True)
