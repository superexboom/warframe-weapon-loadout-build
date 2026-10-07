"""Kill-feedback branch count accuracy: baseline + Galvanized Scope/Crosshairs (+ Galvanized Aptitude where legal),
floor target, 30 s, headshot 0.25/0.5/0.75. Reference = 64 branches; 0 = expected value without branching."""
import json, sys, os, glob, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op, combat_replay as cr
app._disable_analysis_statics_persistence()
FLOOR = op._health_scale_floor(app._benchmark_target_context())
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= FLOOR; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
CODES = ['0', '1', '2', 'D', 'S', 'R', '4', '6', '7', 'CO', 'VI', 'W', 'Y', 'L', 'F']
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
FEED = ['Galvanized Scope', 'Galvanized Crosshairs']
S = Path(sys.argv[1]); names = set(sys.argv[3].split(','))
builds = {}
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r and r['weapon'] in names and r['hs'] == .5: builds[r['weapon']] = r
merges = dict(n=0)
om = cr._merge_branches
def merge(runs): merges['n'] += 1; return om(runs)
cr._merge_branches = merge
def run(rec, mods, hs, riven=None):
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
             headshotChance=hs, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
    if riven: p['riven'] = dict(stats=riven)
    return app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
out = []
for name, b in builds.items():
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == name)
    mods = []
    for slot, nm in enumerate(b['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    feed = next((x for x in app.MANUAL_MODS if x.get('nameEn') in FEED and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
    if not feed or any(m['path'] == feed['path'] for m in mods):
        print('skip', name, 'no feedback mod'); continue
    mods = mods[:7] + [dict(path=feed['path'], rank=feed.get('maxRank') or 0, slot=7)] if len(mods) >= 8 else mods + [dict(path=feed['path'], rank=feed.get('maxRank') or 0, slot=len(mods))]
    kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], rec['path'], kind='weapon'))
    bases = op.RIVEN_BASE_VALUES[kind]
    factor = float(rec.get('omegaAttenuation') or 1.) * op.theoretical_structure_scale(3, False) * op._structure_full_roll_factor()
    for hs in (.25, .5, .75):
        res = dict(weapon=name, hs=hs, feedback=feed.get('nameEn'), branches={})
        for n in (64, 16, 8, 4, 2, 0):
            cr.KILL_BRANCHES = n if n else 16
            cr.KILL_BRANCH_MARGIN = .05 if n else 2.  # 0: never branch (expected-value trajectory)
            merges['n'] = 0; t = time.perf_counter()
            k0 = run(rec, mods, hs)
            vals = {c: run(rec, mods, hs, [dict(code=c, value=bases[c] * factor, negative=False)]) / k0 - 1 for c in CODES if c in bases}
            res['branches'][n] = dict(kpm=k0, values=vals, msPerReplay=1000 * (time.perf_counter() - t) / (len(vals) + 1), branchedShare=merges['n'] / (len(vals) + 1))
        out.append(res)
        br = res['branches']
        print(f"{name:16s} hs{hs:.2f} {feed.get('nameEn')[:14]:14s} branched {br[64]['branchedShare']:.2f} " +
              ' '.join(f"b{n}:{br[n]['kpm']:.3f}/{br[n]['msPerReplay']:.0f}ms" for n in (64, 16, 4, 2, 0)), flush=True)
json.dump(out, open(sys.argv[2], 'w', encoding='utf-8'), indent=1)
