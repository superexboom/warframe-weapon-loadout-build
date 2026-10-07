"""Re-optimize the no-Riven baseline ON the floor target (no Overguard, level-120 health, body/head mix), then measure kills."""
import json, sys, time, os
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
app._disable_analysis_statics_persistence()
FLOOR = op._health_scale_floor(app._benchmark_target_context())
STATE = dict(scale=FLOOR)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
names = sys.argv[2].split(',')
profile = sys.argv[3] if len(sys.argv) > 3 else 'fast'
rows = []
for name in names:
    rec = next((x for x in app.EXPORTS['weapons'] if x.get('nameEn') == name), None)
    if not rec: print('missing', name); continue
    for hs in (0., .5, 1.):
        t = time.time()
        try:
            b = app.build_weapon_payload(dict(weapon=rec['path'], fireMode=0, metric='killsPerMinute', headshotChance=hs,
                     scenario=dict(aiming=True, triggerPolicy='emergent', distance=.5), profile=profile, slotCount=8,
                     enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True))['build']
            mods = [dict(path=m['path'], rank=m['rank'], slot=m['slot']) for m in b['mods']]
            p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                     headshotChance=hs, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
            bt = app.simulate_manual_payload(p)['benchmarkTimeline']
            row = dict(weapon=name, slot=rec.get('slot'), hs=hs, kills=bt['killsInWindow'], mods=[m.get('nameEn') or m['path'].rsplit('/', 1)[-1] for m in b['mods']], seconds=round(time.time() - t, 1))
        except Exception as e:
            row = dict(weapon=name, hs=hs, error=str(e)[:200])
        rows.append(row); print(json.dumps(row, ensure_ascii=False), flush=True)
json.dump(dict(floor=FLOOR, rows=rows), open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
