"""Feasibility: one replay on an unkillable target -> cumulative damage D(t) -> KPM(H) for all H,
vs the real multi-kill 30 s replay at each H."""
import json, sys, os, glob, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
FLOOR = op._health_scale_floor(app._benchmark_target_context())
STATE = dict(scale=FLOOR)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
S = Path(sys.argv[1]); want = [tuple(x.split('@')) for x in sys.argv[2].split(',')]
builds = {}
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r and (r['weapon'], str(r['hs'])) in want: builds[(r['weapon'], r['hs'])] = r
def payload(rec, mods, hs):
    return dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                headshotChance=hs, aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8)
out = []
for (name, hs), b in builds.items():
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == name)
    mods = []
    for slot, nm in enumerate(b['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    # one life on an unkillable target
    STATE['scale'] = 1e6; app._BENCHMARK_WINDOW_SECONDS = 120.
    t = time.perf_counter(); bt = app.simulate_manual_payload(payload(rec, mods, hs))['benchmarkTimeline']; t_curve = time.perf_counter() - t
    H0 = bt['targetTotalEhp']
    pts = [(p['time'], H0 - p['health']) for p in bt['points']]  # cumulative health damage (no shields/OG)
    unit = H0 / 1e6  # health of scale 1
    def ttk(H):
        prev = (0., 0.)
        for tt, d in pts:
            if d >= H:
                return prev[0] + (tt - prev[0]) * (H - prev[1]) / max(d - prev[1], 1e-12)
            prev = (tt, d)
        # extrapolate with the last 20 s slope
        t1, d1 = pts[-1]; t0, d0 = next(p for p in pts if p[0] >= t1 - 20)
        return t1 + (H - d1) / max((d1 - d0) / (t1 - t0), 1e-12)
    app._BENCHMARK_WINDOW_SECONDS = 30.
    rows = []
    for scale in (FLOOR / 64, FLOOR / 16, FLOOR / 4, FLOOR, FLOOR * 4):
        STATE['scale'] = scale
        t = time.perf_counter(); real = app.simulate_manual_payload(payload(rec, mods, hs))['benchmarkTimeline']; t_real = time.perf_counter() - t
        T = ttk(scale * unit)
        pred = 30. / T  # kills in 30 s if every life is the first life
        rows.append(dict(scale=scale, realKills=real['killsInWindow'], predKills=pred, ttk=T))
    out.append(dict(weapon=name, hs=hs, curveSeconds=t_curve, rows=rows))
    print(f"{name:16s} hs{hs:.1f} curve {t_curve*1000:.0f}ms | " + ' '.join(f"x{r['scale']/FLOOR:g}: {r['realKills']:.2f}/{r['predKills']:.2f}" for r in rows), flush=True)
json.dump(out, open(S / 'dcurve.json', 'w'), indent=1)
