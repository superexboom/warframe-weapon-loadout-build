"""Same build (7 mods, no riven), same target (Thrax 170 SP, innate Overguard, no aim, 50% head):
search evaluator vs manual replay vs WFSim."""
import json, sys, os, subprocess
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
from tools.compare_archgun_board_builds import registry
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')
wfmod = {r.get('internal_name'): k for k, r in mods.items()}; wfwep = {r.get('internal_name'): k for k, r in weps.items()}
app._disable_analysis_statics_persistence()
rows = json.load(open(S / 'coarse2.json', encoding='utf-8'))
cases, calls = [], []
for r in rows:
    rec = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == r['weapon'])
    if rec['path'] not in wfwep: continue
    for label in ('bot', 'portable'):
        b = r['builds'][label]
        if b.get('error') or not all(p in wfmod for p in b['paths']): continue
        key = (r['weapon'], tuple(sorted(b['paths'])))
        if key in {c['key'] for c in cases}: continue
        mm = [dict(path=p, rank=(app.MANUAL_MODS_BY_PATH.get(p) or {}).get('maxRank') or 0, slot=i) for i, p in enumerate(b['paths'])]
        man = app.simulate_manual_payload(dict(weapon=rec['path'], fireMode=0, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170,
              steelPath=True, headshotChance=.5, aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8))['benchmarkTimeline']['killsPerMinute']
        try:
            se = app.build_weapon_payload(dict(weapon=rec['path'], fireMode=0, metric='killsPerMinute', headshotChance=.5, profile='fast', slotCount=7,
                  requiredMods=b['paths'], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True, enemyEnhancements=dict(eximus=False)))['build']
            search = se.get('objectiveScore'); changed = sorted(m['path'] for m in se['mods']) != sorted(b['paths'])
        except Exception as e:
            search, changed = None, str(e)[:80]
        cases.append(dict(key=key, weapon=r['weapon'], label=label, card=','.join(s['code'] for s in r['stats']), mods=b['mods'], manual=man, search=search, changed=changed))
        calls.append(['/api/simulate', dict(weapon=wfwep[rec['path']], mode='base', mods=[wfmod[p] for p in b['paths']], arcane=[], evolutions=[],
                      enemy='thrax_centurion', level=170, steel_path=True, headshot_pct=50, aiming=False, duration=30., runs=200, seed=12648430,
                      infinite_ammo=True, ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5])])
inp = S / 'tp-req.json'; out = S / 'tp-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
for c, x in zip(cases, json.load(open(out))):
    c['wfsim'] = x['score'] * 2 if 'score' in x else None
    print(f"{c['weapon']:16s} {c['label']:8s} (from card {c['card']:9s}) search {c['search'] if c['search'] is None else round(c['search'],2)} manual {c['manual']:.2f} wfsim {c['wfsim'] if c['wfsim'] is None else round(c['wfsim'],2)} {'CHANGED' if c['changed'] else ''}")
    print('      ', c['mods'])
json.dump(cases, open(S / 'tripath.json', 'w'), indent=1, default=str)
