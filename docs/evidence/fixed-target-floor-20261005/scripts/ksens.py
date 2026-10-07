"""How many baseline kills per window make single-stat values stable?
Floor health fixed; window W = n * TTK for n in KS; reference = largest n.
Also: softened health instead (30 s window, health so the baseline gets n kills)."""
import json, glob, sys, os, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
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
CODES = ['0', '1', '2', 'D', 'S', 'R', '4', '5', '6', '7', 'CO', 'VI', 'W', 'Y', 'SD', 'L', 'F']
KS = [1, 2.5, 5, 10, 20, 40]
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
builds = []
for f in sorted(glob.glob(sys.argv[2])):
    for r in json.load(open(f, encoding='utf-8'))['rows']:
        if 'mods' in r: builds.append(r)
def kpm(rec, mods, hs, riven=None):
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
             headshotChance=hs, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5), slotPolarities=[None] * 8)
    if riven: p['riven'] = dict(stats=riven)
    bt = app.simulate_manual_payload(p)['benchmarkTimeline']; return bt['killsPerMinute'], bt['killsInWindow']
out = []
for b in builds:
    rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == b['weapon'])
    mods = []
    for slot, nm in enumerate(b['mods']):
        m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
        if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
    hs = b['hs']
    kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], rec['path'], kind='weapon'))
    bases = op.RIVEN_BASE_VALUES[kind]
    factor = float(rec.get('omegaAttenuation') or 1.) * op.theoretical_structure_scale(3, False) * op._structure_full_roll_factor()
    STATE['scale'] = FLOOR; app._BENCHMARK_WINDOW_SECONDS = 240.
    _, k240 = kpm(rec, mods, hs)
    ttk = 240. / max(k240, 1e-3)
    res = dict(weapon=b['weapon'], hs=hs, ttk=ttk, modsMatched=len(mods), modes={})
    for mode in ('window', 'soften'):
        for n in KS:
            if mode == 'window':
                STATE['scale'] = FLOOR; app._BENCHMARK_WINDOW_SECONDS = max(5., n * ttk)
                if app._BENCHMARK_WINDOW_SECONDS > 4000: continue
            else:
                app._BENCHMARK_WINDOW_SECONDS = 30.; s = FLOOR
                for _ in range(6):
                    STATE['scale'] = s; _, kk = kpm(rec, mods, hs)
                    c = s * kk / n
                    if kk <= 0 or abs(c / s - 1) < .03: break
                    s = c
                STATE['scale'] = s
            k0, kills = kpm(rec, mods, hs)
            vals = {c: kpm(rec, mods, hs, [dict(code=c, value=bases[c] * factor, negative=False)])[0] / k0 - 1
                    for c in CODES if c in bases and not (c in ('W', 'Y') and hs == 0)}
            res['modes'][f'{mode}:{n}'] = dict(window=app._BENCHMARK_WINDOW_SECONDS, scale=STATE['scale'], kills=kills, values=vals)
    out.append(res)
    w = res['modes']
    def fmt(key): v = w.get(key); return '   -   ' if not v else ' '.join(f"{c}{v['values'][c]*100:+.0f}" for c in ('0', 'S', 'CO', 'VI', 'W', 'Y') if c in v['values'])
    print(f"{b['weapon']:16s} hs{hs:.1f} ttk {ttk:6.1f}s", flush=True)
    for key in w: print(f"   {key:10s} W{w[key]['window']:7.0f}s k{w[key]['kills']:6.1f}  {fmt(key)}", flush=True)
json.dump(out, open(sys.argv[1], 'w', encoding='utf-8'), indent=1)
