import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
wfmod = {r.get('internal_name'): k for k, r in mods.items()}; wfwep = {r.get('internal_name'): k for k, r in weps.items()}
cases = json.load(open(S / 'tripath.json'))
cases = [c for c in cases if c['weapon'] in ('Rubico Prime', 'Fulmin Prime', 'Torid')] if len(sys.argv) < 3 else cases
calls, rows = [], []
for c in cases:
    rec = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == c['weapon'])
    paths = [p for p in c['key'][1]]
    for aim in (False, True):
        mm = [dict(path=p, rank=(app.MANUAL_MODS_BY_PATH.get(p) or {}).get('maxRank') or 0, slot=i) for i, p in enumerate(paths)]
        pl = dict(weapon=rec['path'], fireMode=0, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                  headshotChance=.5, aiming=aim, triggerPolicy='emergent', slotPolarities=[None] * 8)
        if aim: pl['scenario'] = dict(distance=.5)
        bt = app.simulate_manual_payload(pl)['benchmarkTimeline']
        rows.append(dict(weapon=c['weapon'], label=c['label'], aim=aim, local=bt['killsPerMinute'], combo=bool(bt.get('sniperCombo'))))
        calls.append(['/api/simulate', dict(weapon=wfwep[rec['path']], mode='base', mods=[wfmod[p] for p in paths], arcane=[], evolutions=[],
                      enemy='thrax_centurion', level=170, steel_path=True, headshot_pct=50, aiming=aim, duration=30., runs=200, seed=12648430,
                      infinite_ammo=True, ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'ac-req.json'; out = S / 'ac-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for r, x in zip(rows, json.load(open(out))):
    r['wfsim'] = x['score'] * 2
    print(f"{r['weapon']:14s} {r['label']:8s} aim={r['aim']!s:5s} local {r['local']:6.2f} wfsim {r['wfsim']:6.2f} ratio {r['local']/max(r['wfsim'],1e-9):.2f} combo {r['combo']}")
