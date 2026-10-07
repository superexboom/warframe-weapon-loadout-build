"""Heat chain model: old (any fractional proc refreshes) vs new vs WFSim."""
import json, sys, subprocess, heapq
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import proc_probability as pp
from tools.compare_archgun_board_builds import registry, exact_record
S = Path(sys.argv[1]); WF = ROOT / '.local/wfsim-live-20261004'
mods = registry(WF / 'data/mods'); weps = registry(WF / 'data/weapons')


class Legacy:
    """Pre-2026-10-06 semantics: every expected proc refreshes the episode."""
    def __init__(self): self.reset()
    def reset(self):
        self.n = self.s = 0.; self.end = -1.; self.scale = 1.; self.cohorts = []; self.missing = 1.; self.mature = 0.; self.old = ({}, -1., 1.)
    def active(self): return self.n > 0
    def alive(self): return 1. if self.n > 0 else 0.
    def count(self): return self.n
    def seed(self): return self.s
    def _dist(self, t, scale):
        values = (0., .15, .30, .40, .50); result = {.5: self.mature}; pending = []
        for born, w in self.cohorts:
            step = max(0, min(4, int((t - born + 1e-9) / max(.5 * scale, 1e-9))))
            result[values[step]] = result.get(values[step], 0.) + w
            if step == 4: self.mature += w
            else: pending.append((born, w))
        self.cohorts = pending
        return result
    def expire(self, t):
        if self.n and self.end < t - 1e-9:
            self.old = (self._dist(self.end, self.scale), self.end, self.scale)
            self.n = self.s = 0.; self.cohorts = []; self.missing = 1.; self.mature = 0.
    def add(self, t, absence, n, seed, duration, scale):
        self.expire(t)
        w = self.missing * min(1., max(0., 1 - absence))
        if w > 1e-14: self.cohorts.append((t, w))
        self.missing -= w
        if not self.n: self.scale = scale
        self.n += n; self.s += seed; self.end = t + duration
    def strip(self, t):
        up = sum(v * w for v, w in self._dist(t, self.scale).items()) if self.n else 0.
        dist, ended, scale = self.old
        if ended < 0: return up
        k = int(max(0., t - ended) / max(1.5 * scale, 1e-9)); down = 0.
        for value, w in dist.items():
            desc = [v for v in (.5, .4, .3, .15, 0.) if v <= value + 1e-9]; down += w * desc[min(k, len(desc) - 1)]
        return max(up, down)


NEW = pp.HeatChains
RIFLE = ['serration', 'split_chamber', 'vital_sense', 'point_strike', 'heavy_caliber']
PISTOL = ['hornet_strike', 'barrel_diffusion', 'primed_pistol_gambit', 'target_cracker', 'lethal_torrent']
SHOTGUN = ['point_blank', 'hells_chamber', 'blunderbuss', 'vicious_spread']
CASES = [('athodai', None), ('athodai_prime', None), ('plinx', None), ('tenet_plinx', 'heat'), ('steflos', None), ('trumna', None),
         ('javlok', None), ('ignis', None), ('tenet_spirex', 'heat'),
         ('soma_prime', None), ('rubico_prime', None), ('lex_prime', None), ('hek', None)]
ELEM = {'heat': 'DT_FIRE'}
calls, rows = [], []
for wid, valence in CASES:
    spec = weps[wid]; pools = spec.get('mod_pools') or []
    kind = 'shotgun' if 'shotgun' in pools else 'rifle' if 'rifle' in pools else 'pistol'
    base = {'rifle': RIFLE, 'pistol': PISTOL, 'shotgun': SHOTGUN}[kind]
    heatmod = {'rifle': 'hellfire', 'pistol': 'heated_charge', 'shotgun': 'incendiary_coat'}[kind]
    rec = exact_record(spec, app.EXPORTS['weapons'])
    direct = sum(float(x) for x in ((spec.get('attack') or {}).get('damage') or {}).values())
    mode = next((i for i, m in enumerate(rec['fireModes']) if abs(sum(((m.get('damage') or {}).get('types') or {}).values()) - direct) < .5), 0)
    aiming = 'sniper' in pools
    for label, names in (('bare', []), ('build', base), ('build+heat', base[:-1] + [heatmod])):
        names = [n for n in names if n in mods]
        mm = [dict(path=mods[n]['internal_name'], rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]['internal_name']) or {}).get('maxRank') or 0, slot=i) for i, n in enumerate(names)]
        payload = dict(weapon=rec['path'], fireMode=mode, mods=mm, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                       headshotChance=0., aiming=aiming, triggerPolicy='emergent', slotPolarities=[None] * 8)
        if valence: payload.update(innateElement=ELEM[valence], innateElementValue=.6)
        res = {}
        for tag, cls in (('old', Legacy), ('new', NEW)):
            pp.HeatChains = cls
            bt = app.simulate_manual_payload(payload)['benchmarkTimeline']
            res[tag] = bt['killsPerMinute']
        pp.HeatChains = NEW
        rows.append((wid, label, res))
        q = dict(weapon=wid, mode='base', mods=names, arcane=[], evolutions=[], enemy='thrax_centurion', level=170, steel_path=True,
                 headshot_pct=0, aiming=aiming, duration=30., runs=200, seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                 assume_max=False, player_at=[0, 0], target_at=[0, .5])
        if valence: q.update(valence_element=valence, valence_bonus=.6)
        calls.append(['/api/simulate', q])
inp = S / 'hs2-req.json'; out = S / 'hs2-resp.json'; inp.write_text(json.dumps(calls))
if out.exists(): out.unlink()
subprocess.run(['node', str(S / 'pv.mjs'), str(WF), str(inp), str(out)], check=True)
result = []
for (wid, label, res), x in zip(rows, json.load(open(out))):
    ref = x['score'] * 2
    e = {k: (v / ref - 1) * 100 for k, v in res.items()}
    result.append(dict(weapon=wid, build=label, wfsim=ref, **{k: v for k, v in res.items()}, errOld=e['old'], errNew=e['new']))
    print(f"{wid:20s} {label:10s} wfsim {ref:8.3f} old {res['old']:8.3f} ({e['old']:+6.1f}%) new {res['new']:8.3f} ({e['new']:+6.1f}%)", flush=True)
import statistics as st
for k in ('errOld', 'errNew'):
    v = [abs(r[k]) for r in result]
    print(k, 'mean |err|', round(st.mean(v), 2), 'median', round(st.median(v), 2), 'max', round(max(v), 1))
json.dump(result, open(S / 'heatsweep.json', 'w'), indent=1)
