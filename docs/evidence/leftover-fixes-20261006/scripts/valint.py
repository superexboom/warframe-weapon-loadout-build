"""Validate the hardness-integrated score on re-optimized baselines.
- nodes: baseline body hits per kill N (hs 0), via a one-life replay
- 3-node Gauss-Legendre geometric mean vs a 9-node reference
- single-target (middle node) vs integrated: smoothness of a damage-line sweep"""
import json, sys, os, glob, time, math
from pathlib import Path
import numpy as np
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op, combat_replay as cr
STATE = dict(scale=1.0)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
REC = dict(curve=None)
otraj = cr._trajectory
def traj(*a, **k):
    if REC['curve'] is not None:
        k['life_curve'] = []; REC['curve'].append(k['life_curve'])
    return otraj(*a, **k)
cr._trajectory = traj
CODES = ['0', '1', '2', 'D', 'S', 'R', '4', '6', '7', 'CO', 'VI', 'W', 'Y', 'L', 'F']
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
S = Path(sys.argv[1]); names = set(sys.argv[3].split(','))
builds = []
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r and r['weapon'] in names: builds.append(r)
def run(rec, mods, hs, scale, riven=None, window=30.):
    STATE['scale'] = scale; app._BENCHMARK_WINDOW_SECONDS = window
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
             headshotChance=hs, aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8)
    if riven: p['riven'] = dict(stats=riven)
    return app.simulate_manual_payload(p)['benchmarkTimeline']
def gl(n):
    x, w = np.polynomial.legendre.leggauss(n)
    lo, hi = math.log(1.), math.log(20.)
    return [(math.exp((lo + hi) / 2 + xi * (hi - lo) / 2), wi / 2) for xi, wi in zip(x, w)]
def hit_scales(rec, mods, times):
    REC['curve'] = []
    bt = run(rec, mods, 0., 1e9, window=max(times) + 2.)
    curve = max(REC['curve'], key=len); REC['curve'] = None
    unit = bt['targetTotalEhp'] / 1e9
    curve.sort(key=lambda e: e[0]); start = curve[0][0]
    out = []
    for T in times:
        rows = [e for e in curve if e[0] - start <= T + 1e-9]
        d = sum(e[1] for e in rows); out.append((d / unit, min(.5, math.sqrt(sum(e[2] for e in rows)) / d if d else 0.)))
    return out
def gm(rec, mods, hs, nodes, riven=None):
    def node_kpm(s, sp):
        pts = (s * (1 - sp), s * (1 + sp)) if sp > 0 else (s,)
        return sum(run(rec, mods, hs, p, riven)['killsPerMinute'] for p in pts) / len(pts)
    return math.exp(sum(w * math.log(max(node_kpm(s, sp), 1e-12)) for (s, sp), w in nodes))
out = []
for b in builds:
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == b['weapon'])
    mods = []
    for slot, nm in enumerate(b['mods']):
        m_ = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m_: mods.append(dict(path=m_['path'], rank=m_.get('maxRank') or 0, slot=slot))
    hs = b['hs']
    kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], rec['path'], kind='weapon'))
    bases = op.RIVEN_BASE_VALUES[kind]
    factor = float(rec.get('omegaAttenuation') or 1.) * op.theoretical_structure_scale(3, False) * op._structure_full_roll_factor()
    g3, g9 = gl(3), gl(9)
    s3 = hit_scales(rec, mods, [n for n, _ in g3]); s9 = hit_scales(rec, mods, [n for n, _ in g9])
    n3 = [(s, w) for s, (_, w) in zip(s3, g3)]; n9 = [(s, w) for s, (_, w) in zip(s9, g9)]
    center = [((s3[1][0], 0.), 1.)]
    n3_flat = [((s[0], 0.), w) for s, w in n3]
    res = dict(weapon=b['weapon'], hs=hs, nodes3=s3, values={})
    t0 = time.perf_counter()
    for label, nodes in (('center', center), ('gl3', n3), ('gl9', n9)):
        base = gm(rec, mods, hs, nodes)
        vals = {c: gm(rec, mods, hs, nodes, [dict(code=c, value=bases[c] * factor, negative=False)]) / base - 1
                for c in CODES if c in bases and not (c in ('W', 'Y') and hs == 0)}
        res['values'][label] = vals
    # smoothness sweep: damage line 40..160 in 25 steps
    sweep = {}
    for label, nodes in (('center', center), ('gl3', n3), ('gl9', n9), ('gl3flat', n3_flat)):
        base = gm(rec, mods, hs, nodes)
        sweep[label] = [gm(rec, mods, hs, nodes, [dict(code='D', value=v, negative=False)]) / base - 1 for v in np.linspace(40, 160, 25)]
    res['sweep'] = sweep
    res['seconds'] = time.perf_counter() - t0
    out.append(res)
    def rough(series):  # largest single step as a share of the whole rise (1/24 = perfectly even)
        d = np.diff(series); return float(np.abs(d).max() / max(np.abs(d).sum(), 1e-12))
    print(f"{b['weapon']:16s} hs{hs:.1f} nodes {[(round(x,3),round(y,3)) for x,y in s3]} roughness c/3/9 "
          f"{rough(sweep['center']):.2f}/{rough(sweep['gl3']):.2f}/{rough(sweep['gl9']):.2f}", flush=True)
json.dump(out, open(sys.argv[2], 'w'), indent=1)
