"""Opticor: charged hitscan explosion (chargeDamageMultiplier) vs WFSim; Opticor Vandal as the audited control.

Reads the import evidence (WFSim id -> local fire mode). Alt-fire forms are
requested as mode 'alternate' of their transform group (checked by the apl);
Incarnon weapons are skipped (local auto-routes evolutions); Kuva / Tenet /
Coda weapons send heat 60 % valence to both engines.
"""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
added = [dict(weapon=w, mode=0, path=weps[w]['internal_name']) for w in ('opticor', 'opticor_vandal')]
BASE = dict(rifle=['serration', 'split_chamber', 'vital_sense', 'point_strike'], pistol=['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker'],
            shotgun=['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread'])
by_path = {w['path']: w for w in (app.EXPORTS['weapons'].values() if isinstance(app.EXPORTS['weapons'], dict) else app.EXPORTS['weapons'])}
calls, rows = [], []
for item in added:
    wid, mode, path = item['weapon'], item['mode'], item['path']
    spec = weps[wid]; rec = by_path[path]
    if rec.get('isIncarnon'):
        print('skip incarnon', wid); continue
    pools = spec.get('mod_pools') or (weps.get(spec.get('inherits')) or {}).get('mod_pools') or []
    kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools or 'primary' in pools else 'pistol' if 'pistol' in pools or 'secondary' in pools else None
    alternate = spec.get('form') == 'alt_fire' and not spec.get('default_form')
    wf_weapon, wf_mode = (spec.get('transform_group') or spec.get('inherits'), 'alternate') if alternate else (wid, 'base')
    valence = wid.split('_')[0] in ('kuva', 'tenet', 'coda')
    aiming = 'sniper' in pools
    for label, names in (('bare', []), ('build', BASE.get(kind, []))):
        if label == 'build' and (not kind or alternate):
            continue  # WFSim does not keep the alternate action with mods
        names = [n for n in names if n in mods]
        mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
        payload = dict(weapon=path, fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=0., aiming=aiming, triggerPolicy='emergent', slotPolarities=[None] * 8, combatState=dict(selfShieldBreakForced=False))
        if valence: payload.update(innateElement='DT_FIRE', innateElementValue=.6)
        try:
            bt = app.simulate_manual_payload(payload)['benchmarkTimeline']
        except Exception as e:
            print('local error', wid, e); continue
        rows.append((wid, mode, label, alternate, bt['killsPerMinute'], bt.get('unsupported')))
        q = dict(weapon=wf_weapon, mode=wf_mode, mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                 headshot_pct=0, aiming=aiming, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                 assume_max=False, player_at=[0, 0], target_at=[0, .5])
        if valence: q.update(valence_element='heat', valence_bonus=.6)
        calls.append(['/api/simulate', q])
inp = S / 'op-req.json'; out = S / 'op-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
result = []
for (wid, mode, label, alternate, local, notes), x in zip(rows, json.loads(out.read_text(encoding='utf-8'))):
    if alternate and 'alt_fire' not in x.get('apl', []):
        print(f"{wid:24s} {label:6s} wfsim did not fire the alternate mode {x.get('apl')}"); continue
    if not x.get('ok', True) or not x.get('score'):
        print(f"{wid:24s} {label:6s} wfsim error {str(x)[:120]}"); continue
    ref = x['score'] * 2; err = (local / ref - 1) * 100
    result.append(dict(weapon=wid, mode=mode, build=label, wfsim=ref, se=x['score_se'] * 2, local=local, err=err, unmodeled=weps[wid].get('unmodeled')))
    print(f"{wid:24s} m{mode} {label:6s} wfsim {ref:8.4f} +-{x['score_se']*2/ref*100:4.1f}% local {local:8.4f} ({err:+6.1f}%)", flush=True)
import statistics as st
v = [abs(r['err']) for r in result]
print('mean |err|', round(st.mean(v), 2), 'median', round(st.median(v), 2), 'max', round(max(v), 1))
json.dump(result, open(S / 'opticorsweep.json', 'w'), indent=1)
