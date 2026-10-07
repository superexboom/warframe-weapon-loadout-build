"""Incarnon weapons vs WFSim with the local route sent as explicit evolutions."""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry, exact_record
from tools.validate_hunter_munitions import reference_evolutions
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weapons = registry(WF / 'data/weapons'); evolutions = registry(WF / 'data/evolutions')
RIFLE = ['serration', 'split_chamber', 'point_strike', 'vital_sense', 'hammer_shot', 'primed_cryo_rounds', 'infected_clip']
PISTOL = ['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker', 'lethal_torrent', 'deep_freeze', 'pathogen_rounds']
CASES = {'torid': RIFLE, 'vectis_prime': RIFLE, 'dual_toxocyst': PISTOL}
rows, calls = [], []
for wid, names in CASES.items():
    names = [n for n in names if n in mods]
    weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
    paths = [exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in names]
    for hs in (0, 100):
        manual = dict(weapon=weapon['path'], fireMode=0, mods=[dict(path=p, rank=None, slot=i) for i, p in enumerate(paths)], arcanes=[],
                      headshotChance=hs / 100, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8,
                      enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True)
        result = app.simulate_manual_payload(manual)
        choices = result.get('incarnonChoices') or {}
        evo = reference_evolutions(weapon, wid, choices, evolutions)
        rows.append(dict(weapon=wid, hs=hs, local=result['benchmarkTimeline']['killsPerMinute'], localShots=result['benchmarkTimeline']['shots'], choices=choices, evolutions=evo))
        calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=evo, evolutions_as_given=True, enemy='thrax_centurion',
                      level=170, steel_path=True, headshot_pct=hs, aiming=True, duration=30., runs=200, seed=12648430, infinite_ammo=True,
                      ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'inc-req.json'; out = S / 'inc-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for r, x in zip(rows, json.load(open(out))):
    r['wfsim'] = x['score'] * 2 if 'score' in x else None; r['wfsimShots'] = x.get('shots')
    print(f"{r['weapon']:14s} hs{r['hs']:3d} local {r['local']:7.2f} wfsim {r['wfsim'] or 0:7.2f} ratio {r['local']/max(r['wfsim'] or 1e-9,1e-9):.2f} shots {r['localShots']}/{r['wfsimShots']} evo {r['evolutions']}")
json.dump(rows, open(S / 'incval.json', 'w'), indent=1)
