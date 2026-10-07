"""Native burst cadence (data/mechanics/burst-profiles.json) vs WFSim: bare and a 4-mod build.

Incarnon weapons are left out (local auto-routes evolutions); WFSim alt-fire
ids (cyanex_burst, ...) map to the local mode that carries the native burst and
are requested as mode 'alternate' of their transform group (checked by the apl).
Kuva / Tenet / Coda weapons send the same valence (heat 60 %) to both engines.
"""
import json, sys, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry, exact_record
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
bursts = json.loads((ROOT / 'data/mechanics/burst-profiles.json').read_text())['weapons']
BASE = dict(rifle=['serration', 'split_chamber', 'vital_sense', 'point_strike'], pistol=['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker'],
            shotgun=['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread'])
CASES = sys.argv[2].split(',') if len(sys.argv) > 2 else [
    'hind', 'quartakk', 'harpak', 'kraken', 'tiberon', 'tiberon_prime', 'hema', 'coda_hema', 'paracyst', 'thornbak', 'higasa',
    'akarius', 'akarius_prime', 'akjagara', 'akjagara_prime', 'sepulcrum', 'battacor', 'helstrum', 'multron', 'burst_laser_prime',
    'cyanex_burst', 'nagantaka_burst', 'nagantaka_prime_burst', 'bubonico_burst', 'coda_bubonico_burst', 'kuva_quartakk', 'quatz_burst',
    'haalvu_alt', 'perigale', 'perigale_prime']
calls, rows = [], []
for wid in CASES:
    spec = weps[wid]; pools = spec.get('mod_pools') or []
    kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools or 'primary' in pools else 'pistol'
    rec = exact_record(spec, app.EXPORTS['weapons'])
    if rec.get('isIncarnon'):
        print('skip incarnon', wid); continue
    native = (bursts.get(rec['path']) or {}).get('modes') or {}
    if spec.get('form') == 'alt_fire':
        mode = next((int(k) for k in native if k != '0'), None)
    else:
        direct = sum(float(x) for x in ((spec.get('attack') or {}).get('damage') or {}).values())
        mode = next((i for i, m in enumerate(rec['fireModes']) if abs(sum(((m.get('damage') or {}).get('types') or {}).values()) - direct) < .5), 0)
    if mode is None:
        print('no mode', wid); continue
    aiming = 'sniper' in pools
    alternate = spec.get('form') == 'alt_fire' and not spec.get('default_form')
    wf_weapon, wf_mode = (spec['transform_group'], 'alternate') if alternate else (wid, 'base')
    valence = wid.split('_')[0] in ('kuva', 'tenet', 'coda')
    for label, names in (('bare', []), ('build', BASE[kind])):
        names = [n for n in names if n in mods]
        mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
        payload = dict(weapon=rec['path'], fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=0., aiming=aiming, triggerPolicy='emergent', slotPolarities=[None] * 8, combatState=dict(selfShieldBreakForced=False))
        if valence: payload.update(innateElement='DT_FIRE', innateElementValue=.6)
        try:
            local = app.simulate_manual_payload(payload)['benchmarkTimeline']['killsPerMinute']
        except Exception as e:
            print('local error', wid, e); continue
        rows.append((wid, mode, label, native.get(str(mode)), local))
        q = dict(weapon=wf_weapon, mode=wf_mode, mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170,
                                            steel_path=True, headshot_pct=0, aiming=aiming, duration=30., runs=200, seed=12648430, infinite_ammo=True,
                                            ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])
        if valence: q.update(valence_element='heat', valence_bonus=.6)
        calls.append(['/api/simulate', q])
inp = S / 'bs-req.json'; out = S / 'bs-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
alt_check = lambda wid: weps[wid].get('form') == 'alt_fire'
result = []
for (wid, mode, label, nb, local), x in zip(rows, json.loads(out.read_text(encoding='utf-8'))):
    if alt_check(wid) and 'alt_fire' not in x.get('apl', []):
        print(f"{wid:22s} {label:6s} wfsim did not fire the alternate mode"); continue
    if not x.get('ok', True) or not x.get('score'):
        print(f"{wid:22s} {label:6s} wfsim error {str(x)[:120]}"); continue
    ref = x['score'] * 2; err = (local / ref - 1) * 100
    result.append(dict(weapon=wid, mode=mode, build=label, burst=nb, wfsim=ref, se=x['score_se'] * 2, local=local, err=err, wfsimShots=x.get('shots')))
    print(f"{wid:22s} m{mode} {label:6s} burst {('clip' if nb and nb.get('remainingClip') else nb and nb['count'])!s:>4} wfsim {ref:8.3f} +-{x['score_se']*2/ref*100:4.1f}% local {local:8.3f} ({err:+6.1f}%)", flush=True)
import statistics as st
v = [abs(r['err']) for r in result]
print('mean |err|', round(st.mean(v), 2), 'median', round(st.median(v), 2), 'max', round(max(v), 1))
json.dump(result, open(S / 'burstsweep.json', 'w'), indent=1)
