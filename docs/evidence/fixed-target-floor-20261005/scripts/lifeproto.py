"""Event-level one-life estimator vs real multi-kill replay across target health."""
import json, sys, os, glob, time, math, bisect
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op, combat_replay as cr
FLOOR = op._health_scale_floor(app._benchmark_target_context())
STATE = dict(scale=FLOOR)
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
Phi = lambda x: .5 * (1 + math.erf(x / math.sqrt(2)))

def curve_stats(curve):
    curve.sort(key=lambda e: e[0])
    t, m, v, direct = [], [], [], []
    M = V = 0.
    for time_, d, var, src in curve:
        M += d; V += var
        t.append(time_); m.append(M); v.append(V)
        if src == 'direct': direct.append(time_)
    return t, m, v, sorted(set(direct))

def estimate(cs, H, mode, smooth=True):
    t, m, v, direct = cs
    if not direct: return None
    t0 = direct[0]
    span = direct[-1] - t0
    rate = (len(direct) - 1) / span if span > 0 else 1.
    # tail slope for extrapolation
    tail_t = t[-1]; j = bisect.bisect_left(t, tail_t - 20.); slope = (m[-1] - m[j]) / max(t[-1] - t[j], 1e-9)
    prevP = 0.; El = 0.
    for i in range(len(t)):
        if smooth and v[i] > 0:
            P = Phi((m[i] - H) / math.sqrt(v[i]))
        else:
            P = 1. if m[i] >= H else 0.
        P = max(P, prevP)
        p = P - prevP; prevP = P
        if p <= 0: continue
        k = bisect.bisect_right(direct, t[i] + 1e-9)  # hits landed up to the kill
        nxt = direct[k] if k < len(direct) else t[i] + 1. / rate
        if mode == 'time':
            life = nxt - t0
        else:  # stationary: hits until the next one, at the long-run hit rate
            life = (k) / rate
        El += p * life
        if P > 1 - 1e-9: break
    if prevP < 1 - 1e-9:
        tk = t[-1] + (H - m[-1]) / max(slope, 1e-12)
        El += (1 - prevP) * (tk - t0 + 1. / rate if mode == 'time' else (tk - t0) * rate / rate + 1. / rate)
    return 60. / El if El > 0 else None

out = []
for (name, hs), b in builds.items():
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == name)
    mods = []
    for slot, nm in enumerate(b['mods']):
        m_ = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m_: mods.append(dict(path=m_['path'], rank=m_.get('maxRank') or 0, slot=slot))
    STATE['scale'] = 1e6; app._BENCHMARK_WINDOW_SECONDS = 120.; REC['curve'] = []
    t_ = time.perf_counter(); bt = app.simulate_manual_payload(payload(rec, mods, hs))['benchmarkTimeline']; tc = time.perf_counter() - t_
    calls = REC['curve']; REC['curve'] = None
    curve = max(calls, key=len)
    unit = bt['targetTotalEhp'] / 1e6
    cs = curve_stats(curve)
    app._BENCHMARK_WINDOW_SECONDS = 30.
    rows = []
    for f in (1 / 64, 1 / 16, 1 / 4, 1, 4):
        STATE['scale'] = FLOOR * f
        real = app.simulate_manual_payload(payload(rec, mods, hs))['benchmarkTimeline']['killsPerMinute']
        H = FLOOR * f * unit
        rows.append(dict(f=f, real=real, time=estimate(cs, H, 'time'), stationary=estimate(cs, H, 'stationary'),
                         timeStep=estimate(cs, H, 'time', smooth=False)))
    out.append(dict(weapon=name, hs=hs, curveMs=tc * 1000, events=len(curve), rows=rows))
    print(f"{name:16s} hs{hs:.1f} curve {tc*1000:4.0f}ms ev {len(curve):5d} calls {len(calls)} | " + ' '.join(
        f"x{r['f']:g}: {r['real']:.1f}/{r['time']:.1f}/{r['stationary']:.1f}" for r in rows), flush=True)
json.dump(out, open(S / 'lifeproto.json', 'w'), indent=1)
