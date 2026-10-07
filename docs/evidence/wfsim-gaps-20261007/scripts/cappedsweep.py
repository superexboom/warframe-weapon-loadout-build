"""Capped Viral / Corrosive / Magnetic: exact stack pool (current local) vs WFSim.

The first run (cappedsweep-old.txt) also carried the pre-2026-10-07 trim; Incarnon
weapons were dropped (local auto-routes evolutions) and Kuva/Tenet need valence.
"""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import proc_probability as pp
from tools.compare_archgun_board_builds import registry, exact_record
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')


BASE = dict(rifle=['serration', 'split_chamber', 'vital_sense', 'point_strike'], pistol=['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker'],
            shotgun=['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread'])
ELEMS = dict(rifle=dict(toxin=['infected_clip', 'malignant_force'], cold=['cryo_rounds', 'rime_rounds'], elec=['stormbringer', 'high_voltage']),
             pistol=dict(toxin=['pathogen_rounds', 'pistol_pestilence'], cold=['deep_freeze', 'frostbite'], elec=['convulsion', 'jolt']),
             shotgun=dict(toxin=['contagious_spread', 'toxic_barrage'], cold=['chilling_grasp', 'frigid_blast'], elec=['charged_shell', 'shell_shock']))
COMBOS = dict(viral=('cold', 'toxin'), corrosive=('elec', 'toxin'), magnetic=('cold', 'elec'))
CASES = ['rubico_prime', 'athodai', 'plinx', 'hek', 'tigris_prime', 'steflos', 'grakata', 'hind', 'kohm', 'tenora', 'acceltra', 'quartakk',
         'baza_prime', 'afentis', 'akstiletto_prime', 'kompressa_prime', 'supra_vandal', 'cedo']
calls, rows = [], []
for wid in CASES:
    spec = weps[wid]; pools = spec.get('mod_pools') or []
    kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools else 'pistol'
    rec = exact_record(spec, app.EXPORTS['weapons'])
    direct = sum(float(x) for x in ((spec.get('attack') or {}).get('damage') or {}).values())
    mode = next((i for i, m in enumerate(rec['fireModes']) if abs(sum(((m.get('damage') or {}).get('types') or {}).values()) - direct) < .5), 0)
    aiming = 'sniper' in pools
    for combo, (a, b) in COMBOS.items():
        names = BASE[kind] + [ELEMS[kind][a][0], ELEMS[kind][b][0], ELEMS[kind][a][1], ELEMS[kind][b][1]]
        names = [n for n in names if n in mods]
        mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
        payload = dict(weapon=rec['path'], fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=0., aiming=aiming, triggerPolicy='emergent', slotPolarities=[None] * 8, combatState=dict(selfShieldBreakForced=False))
        res = dict(new=app.simulate_manual_payload(payload)['benchmarkTimeline']['killsPerMinute'])
        rows.append((wid, combo, res))
        q = dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                 headshot_pct=0, aiming=aiming, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                 assume_max=False, player_at=[0, 0], target_at=[0, .5])
        calls.append(['/api/simulate', q])
inp = S / 'cs-req.json'; out = S / 'cs-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
result = []
for (wid, combo, res), x in zip(rows, json.loads(out.read_text(encoding='utf-8'))):
    ref = x['score'] * 2
    e = {k: (v / ref - 1) * 100 for k, v in res.items()}
    result.append(dict(weapon=wid, combo=combo, wfsim=ref, se=x['score_se'] * 2, virusStacks=x.get('virus_stacks'), **res, errNew=e['new']))
    print(f"{wid:16s} {combo:10s} wfsim {ref:8.3f} +-{x['score_se']*2/ref*100:4.1f}% local {res['new']:8.3f} ({e['new']:+6.1f}%)", flush=True)
import statistics as st
for k in ('errNew',):
    v = [abs(r[k]) for r in result]
    print(k, 'mean |err|', round(st.mean(v), 2), 'median', round(st.median(v), 2), 'max', round(max(v), 1))
json.dump(result, open(S / 'cappedsweep.json', 'w'), indent=1)
