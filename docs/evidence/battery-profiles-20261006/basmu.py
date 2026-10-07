import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import event_profiles as ep
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods')
path = next(w['path'] for w in app.EXPORTS['weapons'] if w['nameEn'] == 'Basmu')
orig = ep.battery_profiles; native = dict(orig()); none = {k: v for k, v in native.items() if k != path}
calls, rows = [], []
for names in ([], ['serration', 'split_chamber', 'vital_sense', 'point_strike', 'heavy_caliber', 'hammer_shot']):
    mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
    for mode, wid in ((0, 'basmu'), (1, 'basmu')):
        res = {}
        for label, table in (('native', native), ('export-reload', none)):
            ep.battery_profiles = lambda table=table: table
            bt = app.simulate_manual_payload(dict(weapon=path, fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                                                  headshotChance=0., aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8))['benchmarkTimeline']
            res[label] = (bt['killsPerMinute'], bt['shots'], bt['reloads'])
        ep.battery_profiles = orig
        rows.append((names, mode, res))
        calls.append(['/api/simulate', dict(weapon=wid, mode='base' if mode == 0 else sys.argv[2], mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                      headshot_pct=0, aiming=False, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                      assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'basmu-req.json'; out = S / 'basmu-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for (names, mode, res), x in zip(rows, json.load(open(out))):
    ref = x.get('score', 0) * 2 if isinstance(x, dict) else float('nan')
    print(f"{'build' if names else 'bare':5s} m{mode} wfsim {ref:7.3f} {x.get('error','') if isinstance(x,dict) else x} | " + ' | '.join(f"{k} {v[0]:7.3f} ({(v[0]/ref-1)*100 if ref else 0:+5.1f}%) shots {v[1]} reloads {v[2]}" for k, v in res.items()))
