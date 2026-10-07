import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry, exact_record
from tools.validate_hunter_munitions import reference_evolutions
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weapons = registry(WF / 'data/weapons'); evolutions = registry(WF / 'data/evolutions')
HS = int(sys.argv[6]) if len(sys.argv) > 6 else 0
wid = sys.argv[2]; route = json.loads(sys.argv[3]); level = int(sys.argv[5]) if len(sys.argv) > 5 else 170
weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
evo = reference_evolutions(weapon, wid, route, evolutions)
builds = [b.split(',') if b else [] for b in sys.argv[4].split(';')]
rows, calls = [], []
for names in builds:
    paths = [exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in names]
    p = dict(weapon=weapon['path'], fireMode=0, mods=[dict(path=q, rank=None, slot=k) for k, q in enumerate(paths)], arcanes=[], headshotChance=HS/100,
             incarnonChoices=route, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8,
             enemy=app._BENCHMARK_ENEMY_PATH, level=level, steelPath=True)
    bt = app.simulate_manual_payload(p)['benchmarkTimeline']
    rows.append(dict(names=names, local=bt['killsPerMinute'], dmg=bt['totalWindowDamage']))
    calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=evo, evolutions_as_given=True, enemy='thrax_centurion',
                  level=level, steel_path=True, headshot_pct=HS, aiming=True, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False,
                  eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'ms-req.json'; out = S / 'ms-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for r, x in zip(rows, json.load(open(out))):
    w = x['score'] * 2; wd = sum(s['dmg'] for s in x['damage_sources'])
    src = {s['source']: round(s['dmg'] / wd * 100) for s in x['damage_sources']}
    print(f"{','.join(r['names']) or 'bare':45s} kpm local/wfsim {r['local']:7.3f}/{w:7.3f} ({r['local']/max(w,1e-9):.2f})  dmg {r['dmg']:9.0f}/{wd:9.0f} ({r['dmg']/max(wd,1):.2f}) {src}")
