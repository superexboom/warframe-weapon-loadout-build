import json, sys, os
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
app._disable_analysis_statics_persistence()
rows = json.load(open(sys.argv[1], encoding='utf-8'))
for r in rows:
    rec = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == r['weapon'])
    line = []
    for label in ('bot', 'portable'):
        b = r['builds'][label]
        if b.get('error'): line.append(f'{label}: n/a'); continue
        try:
            out = app.build_weapon_payload(dict(weapon=rec['path'], fireMode=0, metric='killsPerMinute', headshotChance=.5, profile='fast',
                     slotCount=8, requiredMods=b['paths'], riven=dict(stats=r['stats']), enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                     enemyEnhancements=dict(eximus=False)))
            bb = out['build']; got = sorted(m['path'] for m in bb['mods'])
            same = got == sorted(b['paths'])
            line.append(f"{label}: search-eval {bb.get('objectiveScore', bb.get('score')):.2f}{'' if same else ' (build changed)'}")
        except Exception as e:
            line.append(f'{label}: error {str(e)[:120]}')
    print(f"{r['weapon']:16s} {','.join(s['code'] for s in r['stats']):10s} manual(no aim) bot/port {r['builds']['bot'].get('portableTarget') or 0:.2f}/{r['builds']['portable']['portableTarget']:.2f} | " + ' | '.join(line), flush=True)
