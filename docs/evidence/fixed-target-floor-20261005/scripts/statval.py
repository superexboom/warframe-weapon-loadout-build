"""Single-stat Riven value on each weapon's archived no-Riven baseline under
several target policies x headshot rates. Value = KPM(baseline+line)/KPM(baseline)-1."""
import json, glob, sys, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
app._disable_analysis_statics_persistence()
FLOOR = op._health_scale_floor(app._benchmark_target_context())
STATE = dict(scale=1.0)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed

WANT = sys.argv[2].split(',')
CODES = ['0', '1', '2', 'D', 'S', 'R', '4', '5', '6', '7', 'CO', 'VI', 'W', 'Y', 'SD', 'L', 'F']
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
base_rows = {}
for f in sorted(glob.glob(str(ROOT / '.local/cache/riven-statics-archive-dcac3a99a2808ca8-v22-20261001/standard/*.json'))):
    for k, v in json.load(open(f, encoding='utf-8'))['entries'].items():
        if not k.startswith('{'): continue
        kk = json.loads(k)
        rec = next((x for x in app.EXPORTS['weapons'] if x['path'] == kk['weapon']), None)
        if rec and rec.get('nameEn') in WANT and kk['fireMode'] == 0:
            mods = []
            for slot, p in enumerate(v.get('baselineCards') or []):
                m = app.MANUAL_MODS_BY_PATH.get(p)
                if m is None:
                    nm = (BYPATH.get(p) or {}).get('nameEn')
                    m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
                if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
            base_rows[rec['nameEn']] = (rec, mods)

def kpm(rec, mods, hs, riven=None):
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170,
             steelPath=True, headshotChance=hs, aiming=True, triggerPolicy='emergent', scenario=dict(distance=.5),
             slotPolarities=[None] * 8)
    if riven: p['riven'] = dict(stats=riven)
    bt = app.simulate_manual_payload(p)['benchmarkTimeline']
    return bt['killsPerMinute'], bt['killsInWindow']

def ttk_scale(rec, mods, hs, ttk, window, start):
    app._BENCHMARK_WINDOW_SECONDS = window; s = start
    for _ in range(6):
        STATE['scale'] = s; _, kills = kpm(rec, mods, hs)
        if kills <= 0: break
        c = s * ttk * kills / window
        if abs(c / s - 1) < .03: return c
        s = c
    return s

out = []
t0 = time.time()
for name in WANT:
    if name not in base_rows: print('missing', name); continue
    rec, mods = base_rows[name]
    kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], rec['path'], kind='weapon'))
    bases = op.RIVEN_BASE_VALUES[kind]
    factor = float(rec.get('omegaAttenuation') or 1.) * op.theoretical_structure_scale(3, False, negative=False) * op._structure_full_roll_factor()
    for hs in (0., .5, 1.):
        s3 = ttk_scale(rec, mods, hs, 3., 30., FLOOR)
        s30 = ttk_scale(rec, mods, hs, 30., 30., FLOOR)
        policies = {'ttk3': (s3, 30.), 'floor': (max(FLOOR, s3), 30.),
                    'cap30': (max(s3, min(FLOOR, s30)), 30.), 'floor240': (max(FLOOR, s3), 240.)}
        for pol, (scale, window) in policies.items():
            STATE['scale'] = scale; app._BENCHMARK_WINDOW_SECONDS = window
            k0, kills = kpm(rec, mods, hs)
            vals = {}
            for c in CODES:
                if c not in bases or (c in ('W', 'Y') and hs == 0): continue
                k, _ = kpm(rec, mods, hs, [dict(code=c, value=bases[c] * factor, negative=False)])
                vals[c] = k / k0 - 1 if k0 > 0 else None
            out.append(dict(weapon=name, hs=hs, policy=pol, scale=scale, window=window, kills=kills, kpm=k0, values=vals))
            top = sorted(((v, c) for c, v in vals.items() if v is not None), reverse=True)[:6]
            print(f"{name:16s} hs{hs:.1f} {pol:8s} scale {scale:.4f} kills {kills:7.2f} | " + ' '.join(f"{c}:{v*100:+.0f}" for v, c in top)
                  + (f" | W:{vals.get('W',0)*100:+.0f} Y:{vals.get('Y',0)*100:+.0f}" if hs else ''), flush=True)
json.dump(dict(floor=FLOOR, rows=out), open(sys.argv[1], 'w', encoding='utf-8'), indent=1)
print('done', round(time.time() - t0))
