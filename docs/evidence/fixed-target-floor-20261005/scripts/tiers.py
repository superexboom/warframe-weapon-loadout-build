"""Tier timing on the bot probe cards: ultra cold, fast cold (fills cache), ultra warm, fast warm.
One process per weapon; cards of the same weapon reuse the in-memory cache like a server."""
import json, sys, os, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
import wfarsenal.damage as dm
app._disable_analysis_statics_persistence()
BOT = Path(r'C:\Users\SuperExboom\Documents\黑猫4.0-5.0\.tmp\riven-backport-research-20261005\mixed-affixes\requests.json')
name = sys.argv[2]
cards, seen = [], set()
for x in json.load(open(BOT, encoding='utf-8')):
    r = x['response']; key = json.dumps(r['stats'])
    if r['weapon'] == name and key not in seen: seen.add(key); cards.append([dict(code=s['code'], value=s['value'], negative=s['negative']) for s in r['stats']])
rec = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
orig = dm.enemy_defenses
def kpm(build, stats, scale):
    def ed(*a, **k):
        r = dict(orig(*a, **k)); r['health'] *= scale; r['overguard'] = 0.; return r
    dm.enemy_defenses = ed
    try:
        rslot = (build.get('riven') or {}).get('slot', len(build['mods']))
        slots = [i for i in range(8) if i != rslot]
        mods = [dict(path=m['path'], rank=m.get('rank') or 0, slot=s) for m, s in zip(build['mods'], slots)]
        p = dict(weapon=rec['path'], fireMode=0, mods=mods, riven=dict(stats=stats, slot=rslot), arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH,
                 level=170, steelPath=True, headshotChance=.5, aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8)
        return app.simulate_manual_payload(p)['benchmarkTimeline']['killsPerMinute']
    finally:
        dm.enemy_defenses = orig
out = []
for phase in ('ultra-cold', 'fast-cold', 'ultra-warm', 'fast-warm'):
    profile = phase.split('-')[0]
    for i, stats in enumerate(cards):
        if phase == 'fast-cold' and i > 0: phase_label = 'fast-warm-first'
        else: phase_label = phase
        if phase == 'fast-warm' and i == 0: continue
        if phase.endswith('warm'):
            stats = [dict(st, value=round(st['value'] * .98, 3)) for st in stats]
        t = time.perf_counter()
        r = app.analyze_payload(dict(weapon=rec['path'], disposition=float(rec['omegaAttenuation']), profile=profile, headshotChance=.5, stats=stats))
        el = time.perf_counter() - t
        scale = (r.get('targetCalibration') or {}).get('healthScale') or 1.
        row = dict(weapon=name, card=','.join(s['code'] for s in stats), phase=phase_label, seconds=el, scale=scale,
                   gain=r.get('actualGain'), kpm=kpm(r['actual'], stats, 0.8402764137660713),
                   mods=[m.get('nameEn') or m['path'].rsplit('/', 1)[-1] for m in r['actual']['mods']],
                   details={d['code']: d.get('delta') for d in r.get('details') or []},
                   recommended=[s['code'] for t in r.get('recommendedPositiveTiers') or [] for s in t['stats']],
                   negative=r.get('recommendedNegative'), unsupported=[u for u in r.get('unsupported') or [] if 'ultra' in u])
        out.append(row)
        print(f"{name:16s} {row['card']:9s} {phase_label:16s} {el:6.1f}s kpm@floor {row['kpm']:6.2f} gain {row['gain'] if not isinstance(row['gain'], float) else round(row['gain'],1)} rec {','.join(row['recommended'][:4])} {row['unsupported']}", flush=True)
json.dump(out, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
