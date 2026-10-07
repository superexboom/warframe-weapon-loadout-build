import json, sys, glob, os
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
import wfarsenal.damage as dm
from wfarsenal import optimizer as op
from tools.compare_archgun_board_builds import local_replay
S = Path(sys.argv[1]); name = sys.argv[2]; hs = float(sys.argv[3]); scale = float(sys.argv[4]); values = [float(v) for v in sys.argv[5].split(',')]
STATE = dict(scale=scale)
orig = dm.enemy_defenses
def ed(*a, **k):
    r = dict(orig(*a, **k)); r['health'] *= STATE['scale']; r['overguard'] = 0.; return r
dm.enemy_defenses = ed
BYPATH = {m['path']: m for m in app.EXPORTS['mods']}
b = next(json.loads(l) for f in sorted(glob.glob(str(S / 'ro-?.log'))) for l in open(f, encoding='utf-8') if l.startswith('{') and json.loads(l).get('weapon') == name and json.loads(l).get('hs') == hs and 'mods' in json.loads(l))
rec = next(x for x in app.EXPORTS['weapons'] if x.get('nameEn') == name)
mods = []
for slot, nm in enumerate(b['mods']):
    m = next((x for x in app.MANUAL_MODS if x.get('nameEn') == nm and op._mod_matches_weapon(BYPATH[x['path']], rec)), None)
    if m: mods.append(dict(path=m['path'], rank=m.get('maxRank') or 0, slot=slot))
print(name, b['mods'])
for v in values:
    p = dict(weapon=rec['path'], fireMode=0, mods=mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True, headshotChance=hs,
             aiming=False, triggerPolicy='emergent', slotPolarities=[None] * 8, riven=dict(stats=[dict(code='D', value=v, negative=False)]))
    from wfarsenal import combat_replay as cr, proc_probability as pp
    oc = pp.KillAttribution.crossing
    log = []
    def cx(self, t, remaining, resume=None):
        w, sh = oc(self, t, remaining, resume)
        if len(log) == 1:
            rows = [(round(r[0], 3), round(r[1])) for r in list(self.rows)[-14:]]
            rec_ = [(round(r[0], 3), round(r[1])) for r in self.rows if r[0] > t - self.period + 1e-9]
            print('      kill2 t', t, 'remaining', round(remaining), 'last rows', rows)
            print('      recent', rec_[:20], 'len', len(rec_))
        import math
        log.append((round(t, 3), round(remaining), round(self.rows[-1][1]), round(math.sqrt(self.health_variance)), len(self.rows), round(sh, 3)))
        return w, sh
    pp.KillAttribution.crossing = cx
    keep = {}
    ot = cr._trajectory
    def tr(*a, **k):
        r = ot(*a, **k); keep.setdefault('runs', []).append(r); return r
    cr._trajectory = tr
    app.simulate_manual_payload(p)
    cr._trajectory = ot
    pp.KillAttribution.crossing = oc
    rp = max(keep['runs'], key=lambda r: r.get('windowSeconds') or 0)
    keys = ('killsPerMinute', 'killEvents', 'killTimingShiftSeconds', 'shots', 'reloads', 'weakpointKillEvents', 'firstKillTime', 'minKillInterval', 'totalWindowDamage')
    print(f"D={v:5.1f} " + ' '.join(f"{k}={rp.get(k):.3f}" if isinstance(rp.get(k), float) else f"{k}={rp.get(k)}" for k in keys), 'procs', {k: round(x, 1) for k, x in rp['procCounts'].items()}, 'limit', [l for l in rp.get('limitations', []) if 'branch' in l])
    print('   kills (t, remaining, killerDmg, sigma, rows, shift):', log[-12:])
