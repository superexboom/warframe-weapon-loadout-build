"""Breakpoint check: KPM vs target level (110..130) in both engines for re-optimized baselines."""
import json, sys, os, subprocess, glob
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
from wfarsenal import optimizer as op
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
wfmod = {r.get('internal_name'): k for k, r in mods.items()}
wfwep = {r.get('internal_name'): k for k, r in weps.items()}
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
want = [tuple(x.split('@')) for x in sys.argv[2].split(',')]
rows = []
for f in sorted(glob.glob(str(S / 'ro-?.log'))):
    for l in open(f, encoding='utf-8'):
        try: r = json.loads(l)
        except Exception: continue
        if 'mods' in r and (r['weapon'], str(r['hs'])) in want: rows.append(r)
LEVELS = [0., .25, .5, .75, 1.]  # headshot rates at level 120
calls, meta = [], []
for r in rows:
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == r['weapon'])
    mm = []
    for slot, nm in enumerate(r['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mm.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    dropped = [m['path'].rsplit('/',1)[-1] for m in mm if m['path'] not in wfmod]
    mm = [m for m in mm if m['path'] in wfmod]
    local = []
    for L in LEVELS:
        p = dict(weapon=rec['path'], fireMode=0, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=120, steelPath=True,
                 headshotChance=L, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
        local.append(app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute'])
    meta.append(dict(weapon=r['weapon'], hs=r['hs'], mods=r['mods'], dropped=dropped, local=local))
    for L in LEVELS:
        calls.append(['/api/simulate', dict(weapon=wfwep[rec['path']], mode='base', mods=[wfmod[m['path']] for m in mm], arcane=[], evolutions=[],
                      enemy='thrax_centurion', level=120, steel_path=True, headshot_pct=int(L * 100), aiming=True, duration=30., runs=200,
                      seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'hs-req.json'; out = S / 'hs-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
resp = json.load(open(out)); i = 0
for m in meta:
    m['wfsim'] = []
    for L in LEVELS:
        x = resp[i]; i += 1
        m['wfsim'].append(x['score'] * 60 / x['duration'] if 'score' in x else None)
    print(f"{m['weapon']} hs{m['hs']} dropped {m['dropped']}")
    print('  lvl  ' + ' '.join(f'{L:6.2f}' for L in LEVELS))
    print('  local' + ' '.join(f'{v:6.2f}' for v in m['local']))
    print('  wfsim' + ' '.join(f'{v:6.2f}' if v is not None else '  err ' for v in m['wfsim']))
json.dump(meta, open(S / 'hs-sweep.json', 'w'), indent=1)
