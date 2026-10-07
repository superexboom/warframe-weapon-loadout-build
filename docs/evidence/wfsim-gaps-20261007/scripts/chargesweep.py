"""Native charge times (data/mechanics/charge-profiles.json) for modes that had no audited charge, vs WFSim.

Each local (path, mode) is matched to a WFSim spec by internal path (alt-fire
specs through ``inherits``), alt flag and direct total. Alt forms are sent as
mode 'alternate' and checked by the apl; Incarnon weapons are skipped; Kuva /
Tenet / Coda send heat 60 % valence to both engines.
"""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'vendor'))
import yaml, app
from tools.compare_archgun_board_builds import registry
from wfarsenal.event_profiles import _mode_profile
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods')
specs = {}
for f in (WF / 'data/weapons').rglob('*.yaml'):
    s = yaml.safe_load(f.read_text(encoding='utf-8'))
    if isinstance(s, dict) and s.get('id'): specs[s['id']] = s
def internal(s): return s.get('internal_name') or (specs.get(s.get('inherits')) or {}).get('internal_name')
charge = json.loads((ROOT / 'data/mechanics/charge-profiles.json').read_text())['weapons']
by_path = {w['path']: w for w in app.EXPORTS['weapons']}
BASE = dict(rifle=['serration', 'split_chamber', 'vital_sense', 'point_strike'], pistol=['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker'],
            shotgun=['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread'])
calls, rows = [], []
for path, record in charge.items():
    w = by_path.get(path)
    if not w or w.get('isIncarnon') or w.get('slot') not in ('primary', 'secondary'):
        continue
    for index in record['modes']:
        mode = int(index)
        if _mode_profile({**w, '__selectedFireMode__': mode}, mode).get('charge'):
            continue  # audited before today
        m = w['fireModes'][mode]; total = sum((m['damage'].get('types') or {}).values()); alt = bool(m.get('isAlternateFire'))
        cands = [sid for sid, s in specs.items() if internal(s) == path and (s.get('form') == 'alt_fire') == alt
                 and abs(sum(float(v) for v in ((s.get('attack') or {}).get('damage') or {}).values()) - total) < .5]
        if len(cands) != 1:
            print('unmatched', w['nameEn'], mode, cands); continue
        sid = cands[0]; s = specs[sid]; pools = s.get('mod_pools') or (specs.get(s.get('inherits')) or {}).get('mod_pools') or []
        kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools else 'pistol'
        alternate = s.get('form') == 'alt_fire' and not s.get('default_form')
        wf_weapon, wf_mode = (s.get('transform_group') or s.get('inherits'), 'alternate') if alternate else (sid, 'base')
        valence = sid.split('_')[0] in ('kuva', 'tenet', 'coda')
        for label, names in (('bare', []), ('build', BASE[kind])):
            if label == 'build' and alternate: continue
            names = [n for n in names if n in mods]
            mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
            payload = dict(weapon=path, fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True, headshotChance=0.,
                           aiming='sniper' in pools, triggerPolicy='emergent', slotPolarities=[None] * 8, combatState=dict(selfShieldBreakForced=False))
            if valence: payload.update(innateElement='DT_FIRE', innateElementValue=.6)
            bt = app.simulate_manual_payload(payload)['benchmarkTimeline']
            rows.append((sid, mode, label, alternate, record['modes'][index]['seconds'], bt['killsPerMinute'], bt['shots']))
            q = dict(weapon=wf_weapon, mode=wf_mode, mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                     headshot_pct=0, aiming='sniper' in pools, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False,
                     eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])
            if valence: q.update(valence_element='heat', valence_bonus=.6)
            calls.append(['/api/simulate', q])
inp = S / 'ch-req.json'; out = S / 'ch-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
result = []
for (sid, mode, label, alternate, seconds, local, shots), x in zip(rows, json.loads(out.read_text(encoding='utf-8'))):
    if alternate and 'alt_fire' not in x.get('apl', []):
        print(f"{sid:22s} {label:6s} wfsim did not fire the alternate mode"); continue
    if not x.get('score'):
        print(f"{sid:22s} {label:6s} wfsim error {str(x)[:120]}"); continue
    ref = x['score'] * 2; err = (local / ref - 1) * 100
    result.append(dict(weapon=sid, mode=mode, build=label, chargeSeconds=seconds, wfsim=ref, local=local, err=err, shots=[shots, x['shots']]))
    print(f"{sid:22s} m{mode} {label:6s} charge {seconds:.3g}s shots {shots}/{x['shots']} wfsim {ref:8.4f} local {local:8.4f} ({err:+6.1f}%)", flush=True)
json.dump(result, open(S / 'chargesweep.json', 'w'), indent=1)
