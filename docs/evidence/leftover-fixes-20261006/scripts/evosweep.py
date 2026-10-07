import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry, exact_record
from tools.validate_hunter_munitions import reference_evolutions
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weapons = registry(WF / 'data/weapons'); evolutions = registry(WF / 'data/evolutions')
wid = sys.argv[2]; names = sys.argv[3].split(','); base = json.loads(sys.argv[4])
weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
paths = [exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in names]
tiers = {t['tier']: [b['id'] for b in t['branches']] for t in weapon['incarnon']['tiers'] if t['tier'] > 1}
variants = [dict(base)]
for tier, ids in tiers.items():
    for b in ids:
        v = dict(base, **{f'tier{tier}': b})
        if v not in variants: variants.append(v)
rows, calls = [], []
for v in variants:
    try: evo = reference_evolutions(weapon, wid, v, evolutions)
    except ValueError as e: print('skip', v, e); continue
    p = dict(weapon=weapon['path'], fireMode=0, mods=[dict(path=q, rank=None, slot=k) for k, q in enumerate(paths)], arcanes=[], headshotChance=0,
             incarnonChoices=v, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8,
             enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True)
    r = app.simulate_manual_payload(p)
    rows.append(dict(v=v, evo=evo, local=r['benchmarkTimeline']['killsPerMinute'], got=r.get('incarnonChoices')))
    calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=evo, evolutions_as_given=True, enemy='thrax_centurion',
                  level=170, steel_path=True, headshot_pct=0, aiming=True, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False,
                  eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'evo-req.json'; out = S / 'evo-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for r, x in zip(rows, json.load(open(out))):
    w = x['score'] * 2
    print(f"{json.dumps(r['v']):60s} local {r['local']:6.2f} wfsim {w:6.2f} ratio {r['local']/w:.2f} {'(route changed '+json.dumps(r['got'])+')' if r['got']!=r['v'] else ''} {r['evo']}")
