"""Bot proxy-search builds vs Portable fast-analysis builds for the same cards, same replay.
Targets: Portable fixed target (healthScale from the analysis) and the bot probe target (170, no Overguard, unscaled)."""
import json, sys, os, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
app._disable_analysis_statics_persistence()
BOT = Path(r'C:\Users\SuperExboom\Documents\黑猫4.0-5.0\.tmp\riven-backport-research-20261005\mixed-affixes\requests.json')
STATE = dict(scale=1.0)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
cards, seen = [], set()
for x in json.load(open(BOT, encoding='utf-8')):
    r = x['response']; key = json.dumps(r['stats'])
    if key not in seen: seen.add(key); cards.append(r)
out = []
for r in cards:
    rec = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == r['weapon']); wpath = rec['path']
    stats = [dict(code=s['code'], value=s['value'], negative=s['negative']) for s in r['stats']]
    dm.enemy_defenses = orig
    t = time.perf_counter()
    try:
        a = app.analyze_payload(dict(weapon=wpath, disposition=float(rec['omegaAttenuation']), profile='fast', headshotChance=.5, stats=stats))
    except Exception as e:
        print('analysis failed', rec['nameEn'], str(e)[:200]); continue
    seconds = time.perf_counter() - t
    scale = (a.get('targetCalibration') or {}).get('healthScale') or 1.
    port = a['actual']
    builds = {'bot': ([m['path'] for m in r['actual']['mods']], r['actual']['rivenIndex']),
              'portable': ([m['path'] for m in port['mods']], (port.get('riven') or {}).get('slot', len(port['mods'])))}
    res = dict(weapon=rec['nameEn'], stats=stats, portableSeconds=seconds, botSeconds=r['seconds'], healthScale=scale, builds={})
    dm.enemy_defenses = ed
    for label, (paths, rslot) in builds.items():
        slots = [i for i in range(8) if i != rslot]
        mods = [dict(path=p, rank=(app.MANUAL_MODS_BY_PATH.get(p) or {}).get('maxRank') or 0, slot=s) for p, s in zip(paths, slots)]
        row = dict(paths=paths, rivenSlot=rslot, mods=[(app.MANUAL_MODS_BY_PATH.get(p) or {}).get('nameEn', p) for p in paths])
        for tname, s, aim in (('portableTarget', scale, False), ('portableTargetAim', scale, True), ('botTargetAim', 1.0, True)):
            STATE['scale'] = s
            p = dict(weapon=wpath, fireMode=0, mods=mods, riven=dict(stats=stats, slot=rslot), arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH,
                     level=170, steelPath=True, headshotChance=.5, aiming=aim, triggerPolicy='emergent', scenario=dict(distance=.5) if aim else {},
                     slotPolarities=[None] * 8)
            try: row[tname] = app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
            except Exception as e: row[tname] = None; row['error'] = str(e)[:200]
        res['builds'][label] = row
    out.append(res)
    b, p = res['builds']['bot'], res['builds']['portable']
    print(f"{rec['nameEn']:16s} {','.join(s['code'] for s in stats):10s} portable {seconds:5.1f}s bot {r['seconds']:4.1f}s | "
          ' | '.join(f"{t} {b[t] or 0:.2f}/{p[t] or 0:.2f}" for t in ('portableTarget','portableTargetAim','botTargetAim')), flush=True)
json.dump(out, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
