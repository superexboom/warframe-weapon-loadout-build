import json, glob, sys, statistics as st
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from wsstat_lib import spearman
rows = []
for f in sorted(glob.glob(str(Path(sys.argv[1]) / 'vi/vi-?.json'))): rows += json.load(open(f))
print('cases', len(rows))
def rough(series):  # largest single step as a share of the whole rise (1/24 = perfectly even)
    d = np.diff(series); return float(np.abs(d).max() / max(np.abs(d).sum(), 1e-12))
def steps(series, tol=.1):  # increments below 10% of an even step (flat stretches of a staircase)
    d = np.diff(series); flat = np.abs(d) < tol * max(np.abs(d).sum(), 1e-12) / len(d)
    return int(flat.sum())
print(f"{'vs gl9':8s} {'MAE pp':>7s} {'p90 pp':>7s} {'max pp':>7s} {'rho med':>7s} {'rho min':>7s} {'top3':>5s} | {'rough med':>9s} {'flat steps med':>14s}")
for c in ('center', 'gl3', 'gl9'):
    err = [abs(r['values'][c][k] - r['values']['gl9'][k]) * 100 for r in rows for k in r['values']['gl9']]
    rho = [spearman(r['values'][c], r['values']['gl9']) for r in rows]
    top = st.mean(len(set(sorted(r['values'][c], key=lambda k: -r['values'][c][k])[:3]) &
                      set(sorted(r['values']['gl9'], key=lambda k: -r['values']['gl9'][k])[:3])) / 3 for r in rows)
    ro = [rough(r['sweep'][c]) for r in rows]; sp = [steps(r['sweep'][c]) for r in rows]
    print(f"{c:8s} {st.mean(err):7.2f} {np.percentile(err, 90):7.2f} {max(err):7.2f} {st.median(rho):7.2f} {min(rho):7.2f} {top:5.2f} | {st.median(ro):9.2f} {st.median(sp):14.0f}")
print('\nworst sweeps (single target roughness):')
for r in sorted(rows, key=lambda r: -rough(r['sweep']['center']))[:6]:
    print(f"  {r['weapon']:16s} hs{r['hs']:.1f} rough center/gl3/gl9 {rough(r['sweep']['center']):.2f}/{rough(r['sweep']['gl3']):.2f}/{rough(r['sweep']['gl9']):.2f}"
          f"  D sweep center {[round(x*100) for x in r['sweep']['center'][::4]]} gl3 {[round(x*100) for x in r['sweep']['gl3'][::4]]}")
by = {(r['weapon'], r['hs']): r for r in rows}
print('\nhs0 vs hs1 stat ranking (rho, excl W/Y):')
for c in ('center', 'gl3'):
    v = [spearman(by[(w, 0.)]['values'][c], {k: x for k, x in by[(w, 1.)]['values'][c].items() if k not in 'WY'})
         for w in {r['weapon'] for r in rows} if (w, 0.) in by and (w, 1.) in by]
    print(f"  {c}: median {st.median(v):.2f} min {min(v):.2f}")
print('\nW/Y rank among positives at hs1 (gl3):', [(r['weapon'], sorted(r['values']['gl3'], key=lambda k: -r['values']['gl3'][k]).index('W') + 1,
       sorted(r['values']['gl3'], key=lambda k: -r['values']['gl3'][k]).index('Y') + 1) for r in rows if r['hs'] == 1.][:20])
