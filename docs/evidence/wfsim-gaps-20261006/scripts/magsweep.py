"""Weapons whose clip is the unserialized engine default (6): local (old 0 / new 6) vs WFSim."""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import damage
from tools.compare_archgun_board_builds import registry, exact_record
from tools.validate_hunter_munitions import reference_evolutions
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons'); evolutions = registry(WF / 'data/evolutions')
RIFLE = ['serration', 'split_chamber', 'vital_sense', 'point_strike', 'heavy_caliber']
PISTOL = ['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker', 'lethal_torrent']
SHOTGUN = ['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread']
calls, rows = [], []
for wid in sys.argv[2].split(','):
    spec = weps[wid]; pools = spec.get('mod_pools') or []
    kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools else 'pistol'
    rec = exact_record(spec, app.EXPORTS['weapons'])
    direct = sum(float(x) for x in ((spec.get('attack') or {}).get('damage') or {}).values())
    mode = next((i for i, m in enumerate(rec['fireModes']) if abs(sum(((m.get('damage') or {}).get('types') or {}).values()) - direct) < .5), 0)
    for label, names in (('bare', []), ('build', {'rifle': RIFLE, 'pistol': PISTOL, 'shotgun': SHOTGUN}[kind])):
        names = [n for n in names if n in mods]
        mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
        payload = dict(weapon=rec['path'], fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=0., aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8, scenario=dict(distance=.5),
                       combatState=dict(selfShieldBreakForced=False))  # WFSim: own shield break out of scope
        res = {}
        for tag, clip in (('old', 0.), ('new', 6.)):
            damage.NATIVE_DEFAULT_CLIP = clip
            r = app.simulate_manual_payload(payload)
            res[tag] = (r['benchmarkTimeline']['killsPerMinute'], r['benchmarkTimeline']['shots'], r['benchmarkTimeline']['reloads'])
        route = r.get('incarnonChoices') or {}
        evo = reference_evolutions(rec, wid, route, evolutions) if route else []
        rows.append((wid, label, mode, route, res))
        calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=evo, evolutions_as_given=True, enemy='thrax_centurion',
                      level=170, steel_path=True, headshot_pct=0, aiming=False, duration=30., runs=200, seed=12648430, infinite_ammo=True,
                      ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'mag-req.json'; out = S / 'mag-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for (wid, label, mode, route, res), x in zip(rows, json.load(open(out))):
    ref = x['score'] * 2; c = x['combatants'][0]
    print(f"{wid:11s} {label:5s} m{mode} {json.dumps(route) if route else '':40s} wfsim {ref:7.3f} shots {c['shots']:4d}/{c.get('reloads')} | "
          + ' | '.join(f"{k} {v[0]:7.3f} ({(v[0]/ref-1)*100:+6.1f}%) {v[1]}/{v[2]}" for k, v in res.items()), flush=True)
