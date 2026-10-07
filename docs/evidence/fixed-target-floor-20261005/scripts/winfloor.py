"""Short windows with softened targets vs a stable long-window reference.
Per re-optimized baseline (weapon x headshot rate):
  ref     : health = max(L120 floor, >=20 shots/kill), window = 40 x TTK
  floor30 : current implementation (max(floor, TTK 3 s), 30 s)
  W{w}K{k}: window w s, health softened so the baseline gets k kills in w
Records single-stat values and wall time per replay."""
import json, sys, os, glob, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
app._disable_analysis_statics_persistence()
FLOOR = op._health_scale_floor(app._benchmark_target_context())
STATE = dict(scale=FLOOR)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
CODES = ['0', '1', '2', 'D', 'S', 'R', '4', '5', '6', '7', 'CO', 'VI', 'W', 'Y', 'SD', 'L', 'F']
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
S = Path(sys.argv[1]); names = set(sys.argv[3].split(','))
builds = []
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r and r['weapon'] in names: builds.append(r)

def run(rec, mods, hs, riven=None):
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
             headshotChance=hs, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
    if riven: p['riven'] = dict(stats=riven)
    return app.simulate_manual_payload(p)['benchmarkTimeline']

def soften(rec, mods, hs, window, kills_wanted, start):
    app._BENCHMARK_WINDOW_SECONDS = window; s = start
    for _ in range(8):
        STATE['scale'] = s; k = run(rec, mods, hs)['killsInWindow']
        if k <= 0: s *= .1; continue
        c = s * k / kills_wanted
        if abs(c / s - 1) < .02: return c
        s = c
    return s


prev = {}
for f in sorted(glob.glob(str(S / 'ws-?.json'))):
    for r in json.load(open(f)): prev[(r['weapon'], r['hs'])] = r
out = []
for b in builds:
    old = prev[(b['weapon'], b['hs'])]
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == b['weapon'])
    mods = []
    for slot, nm in enumerate(b['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    hs = b['hs']
    kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], rec['path'], kind='weapon'))
    bases = op.RIVEN_BASE_VALUES[kind]
    factor = float(rec.get('omegaAttenuation') or 1.) * op.theoretical_structure_scale(3, False) * op._structure_full_roll_factor()
    scale = old['configs']['floor30']['scale']
    for w in (10., 15., 20.):
        STATE['scale'] = scale; app._BENCHMARK_WINDOW_SECONDS = w
        bt = run(rec, mods, hs); k0 = bt['killsPerMinute']
        t = time.perf_counter(); vals = {}
        for c in CODES:
            if c not in bases or (c in ('W', 'Y') and hs == 0): continue
            vals[c] = run(rec, mods, hs, [dict(code=c, value=bases[c] * factor, negative=False)])['killsPerMinute'] / k0 - 1
        old['configs'][f'floor{w:.0f}'] = dict(scale=scale, window=w, kills=bt['killsInWindow'], shotsPerKill=bt['shots'] / max(bt['killsInWindow'], 1e-9),
                                               msPerReplay=1000 * (time.perf_counter() - t) / len(vals), values=vals)
    out.append(old); print(b['weapon'], hs, flush=True)
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1)
