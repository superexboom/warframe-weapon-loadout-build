"""Re-optimized baselines on the floor: kills/30 s, shots per kill, at each headshot rate."""
import json, sys, os, glob
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
FLOOR = op._health_scale_floor(app._benchmark_target_context())
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= FLOOR; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
S = Path(sys.argv[1]); rows = []
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r: rows.append(r)
old = {}
for h in ('0', '0.5', '1'):
    for r in json.load(open(S / f'floor-hs{h}.json', encoding='utf-8'))['rows']:
        if r['fireMode'] == 0: old[(r['weapon'], float(h))] = r['kills']
out = []
for r in rows:
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == r['weapon'])
    mm = []
    for slot, nm in enumerate(r['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mm.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    res = dict(weapon=r['weapon'], hs=r['hs'], mods=r['mods'], oldKills30=old.get((r['weapon'], r['hs'])))
    for w in (30., 240.):
        app._BENCHMARK_WINDOW_SECONDS = w
        p = dict(weapon=rec['path'], fireMode=0, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                 headshotChance=r['hs'], aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
        bt = app.simulate_manual_payload(p)['benchmarkTimeline']
        res[f'kills{w:.0f}'] = bt['killsInWindow']; res[f'shots{w:.0f}'] = bt['shots']
    res['shotsPerKill'] = res['shots240'] / max(res['kills240'], 1e-9)
    out.append(res)
out.sort(key=lambda r: (r['weapon'], r['hs']))
print(f"{'weapon':16s} hs   old30   new30   new240  shots/kill  ttk(s)")
for r in out:
    print(f"{r['weapon']:16s} {r['hs']:.1f} {r['oldKills30'] if r['oldKills30'] is not None else float('nan'):7.2f} {r['kills30']:7.2f} {r['kills240']:8.1f} {r['shotsPerKill']:10.1f} {240/max(r['kills240'],1e-9):7.1f}")
json.dump(out, open(S / 'ro-summary.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
