import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import event_profiles as ep
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
data = {p: v for p, v in json.load(open(ROOT / 'data/mechanics/battery-profiles.json', encoding='utf-8'))['weapons'].items() if v.get('wfsim')}
native = dict(ep.battery_profiles())
wfs = {p: dict(regenPerSecond=float(v['wfsim']['regenPerSecond']), delayEmptySeconds=float(v['wfsim']['delayEmptySeconds']),
               delayPartialSeconds=float(v['wfsim']['delayEmptySeconds'])) for p, v in data.items()}
BUILDS = {'rifle': ['serration', 'split_chamber', 'vital_sense', 'point_strike', 'heavy_caliber', 'hammer_shot'],
          'pistol': ['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker', 'lethal_torrent'],
          'shotgun': ['point_blank', 'hells_chamber', 'blunderbuss', 'ravage', 'vicious_spread']}
orig = ep.battery_profiles
calls, rows = [], []
for path, v in data.items():
    rec = next(w for w in app.EXPORTS['weapons'] if w['path'] == path)
    wid = v['wfsim']['id']; spec = weps[wid]; pools = spec.get('mod_pools') or []
    kind = 'rifle' if 'rifle' in pools else 'pistol' if 'pistol' in pools else 'shotgun'
    names = [n for n in BUILDS[kind] if n in mods]
    paths = [mods[n]['internal_name'] for n in names]
    mm = [dict(path=p, rank=(app.MANUAL_MODS_BY_PATH.get(p) or {}).get('maxRank') or 0, slot=i) for i, p in enumerate(paths)]
    direct = sum(float(x) for x in ((spec.get('attack') or {}).get('damage') or {}).values())
    mode = next((i for i, m in enumerate(rec['fireModes']) if abs(sum(((m.get('damage') or {}).get('types') or {}).values()) - direct) < .5), 0)
    res = {}
    for label, table in (('wfsimBattery', wfs), ('native', native), ('none', {})):
        ep.battery_profiles = lambda table=table: table
        try:
            bt = app.simulate_manual_payload(dict(weapon=path, fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                                                  headshotChance=0., aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8))['benchmarkTimeline']
            res[label] = (bt['killsPerMinute'], bt['shots'])
        except Exception as e:
            res[label] = (float('nan'), str(e)[:60])
    ep.battery_profiles = orig
    rows.append((v['name'], mode, res))
    calls.append(['/api/simulate', dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                  headshot_pct=0, aiming=False, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                  assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'bat-req.json'; out = S / 'bat-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
result = []
for (n, mode, res), x in zip(rows, json.load(open(out))):
    ref = x.get('score', 0) * 2
    result.append(dict(weapon=n, mode=mode, wfsim=ref, shotsWfsim=x.get('shots') or x.get('stats', {}).get('shots') if isinstance(x, dict) else None, local={k: v for k, v in res.items()}))
    print(f"{n:14s} m{mode} wfsim {ref:7.2f} | " + ' | '.join(f"{k} {v[0]:7.2f} ({(v[0] / ref - 1) * 100 if ref else 0:+5.1f}%) shots {v[1]}" for k, v in res.items()))
json.dump(result, open(S / 'batval.json', 'w'), indent=1)
