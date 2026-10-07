"""Incarnon forms with explosions: local selected Incarnon mode vs WFSim mode 'incarnon', per tier-2 option."""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal.event_profiles import is_incarnon_mode
from tools.compare_archgun_board_builds import registry, exact_record
from tools.validate_hunter_munitions import reference_evolutions
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
weapons = registry(WF / 'data/weapons'); evolutions = registry(WF / 'data/evolutions')
rows, calls = [], []
for wid in sys.argv[2].split(','):
    rec = exact_record(weapons[wid], app.EXPORTS['weapons'])
    mode = next(i for i in range(len(rec['fireModes'])) if is_incarnon_mode(rec, i))
    t2 = next(t for t in rec['incarnon']['tiers'] if t['tier'] == 2)
    for b in t2['branches']:
        route = {'tier2': b['id']}
        payload = dict(weapon=rec['path'], fireMode=mode, mods=[], arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=1., aiming=True, triggerPolicy='emergent', slotPolarities=[None] * 8, scenario=dict(distance=.5, incarnonCycle=True),
                       incarnonChoices=route, combatState=dict(selfShieldBreakForced=False))
        r = app.simulate_manual_payload(payload)
        bt = r['benchmarkTimeline']
        evo = [e for e in (f'{wid}_evo1_incarnon_form',) if e in evolutions] + reference_evolutions(rec, wid, r.get('incarnonChoices') or route, evolutions)
        rows.append((wid, b['id'], r.get('incarnonChoices'), bt['killsPerMinute'], bt['shots'], bt['totalWindowDamage']))
        calls.append(['/api/simulate', dict(weapon=wid, mode='incarnon', mods=[], arcane=[], evolutions=evo, evolutions_as_given=True, enemy='thrax_centurion',
                      level=170, steel_path=True, headshot_pct=100, aiming=True, duration=30., runs=200, seed=12648430, infinite_ammo=True,
                      ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'incf-req.json'; out = S / 'incf-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for (wid, b, route, k, shots, dmg), x in zip(rows, json.load(open(out))):
    if 'score' not in x: print(wid, b, 'wfsim error', str(x)[:120]); continue
    ref = x['score'] * 2; wd = sum(s['dmg'] for s in x['damage_sources'])
    src = {s['source']: round(s['dmg']) for s in x['damage_sources']}
    print(f"{wid:16s} {b} local {k:7.3f} wfsim {ref:7.3f} ({(k/ref-1)*100:+6.1f}%) shots {shots}/{x['shots']} tf {x.get('transforms')} dmg {dmg:9.0f}/{wd:9.0f} {src}", flush=True)
