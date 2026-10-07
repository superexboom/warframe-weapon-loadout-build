import json, sys
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import registry, exact_record
WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weapons = registry(WF / 'data/weapons')
weapon = exact_record(weapons['torid'], app.EXPORTS['weapons'])
for names in ([], ['split_chamber']):
    paths = [exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in names]
    p = dict(weapon=weapon['path'], fireMode=0, mods=[dict(path=q, rank=None, slot=k) for k, q in enumerate(paths)], arcanes=[], headshotChance=0,
             incarnonChoices=json.loads(sys.argv[1]), aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8,
             enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True)
    r = app.simulate_manual_payload(p)
    bt = r['benchmarkTimeline']
    pts = bt["points"]; d=sum(p["directDps"] for p in pts)*.25; o=sum(p["dotDps"] for p in pts)*.25; print(names, round(bt["totalWindowDamage"]), "direct+field", round(d), "dot", round(o))
