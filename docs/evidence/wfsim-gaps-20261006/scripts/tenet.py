import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
names = ['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker', 'lethal_torrent']
names = [n for n in names if n in mods]
calls, rows = [], []
for wid in ('tenet_cycron', 'tenet_plinx'):
    path = weps[wid]['internal_name']
    mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
    for el, dt in (('heat', 'DT_FIRE'), ('toxin', 'DT_POISON'), ('impact', 'DT_IMPACT')):
        for b in (b for b in ([], names) ):
            pass
        for build in ([], mm):
            r = app.simulate_manual_payload(dict(weapon=path, fireMode=0, mods=build, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                                                 headshotChance=0., aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8,
                                                 innateElement=dt, innateElementValue=.6))
            bt = r['benchmarkTimeline']
            rows.append((wid, el, bool(build), bt['killsPerMinute'], (bt['shots'], round(bt['totalWindowDamage']))))
            calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names if build else [], arcane=[], evolutions=[], enemy='thrax_centurion', level=170,
                          steel_path=True, headshot_pct=0, aiming=False, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False,
                          eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5], valence_element=el, valence_bonus=.6)])
inp = S / 'tn-req.json'; out = S / 'tn-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for (wid, el, b, k, shots), x in zip(rows, json.load(open(out))):
    ref = x['score'] * 2; ws = (x['combatants'][0]['shots'], round(sum(s['dmg'] for s in x['damage_sources'])))
    print(f"{wid:13s} {el:7s} {'build' if b else 'bare ':5s} local {k:7.3f} wfsim {ref:7.3f} ({(k/ref-1)*100:+5.1f}%) shots {shots}/{ws}")
