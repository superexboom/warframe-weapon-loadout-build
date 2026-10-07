"""Full standard Riven analysis wall time under window/target modes (one process per case)."""
import json, sys, os, time
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
from wfarsenal import optimizer as op
app._disable_analysis_statics_persistence()
out, name, hs, mode = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
MODES = {'cur': (30., 3., 120), 'f10': (10., 3., 120), 'f20': (20., 3., 120), 'w10': (10., 2., 0), 'w20': (20., 4., 0), 'w30k5': (30., 6., 0)}
window, ttk, floor = MODES[mode]
app._BENCHMARK_WINDOW_SECONDS = window; op.FIXED_TARGET_TTK_SECONDS = ttk; op.FIXED_TARGET_MIN_LEVEL = floor
weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
stats = {'Burston Prime': [('W', 287.5, False), ('6', 115., False), ('1', 153.3, False), ('3', 91., True)],
         'Vectis Prime': [('W', 231.9, False), ('0', 154.6, False), ('1', 123.7, False), ('L', 41.2, True)],
         'Amprex': [('0', None, False), ('1', None, False), ('S', None, False), ('Z', None, True)],
         'Kompressa Prime': [('D', None, False), ('CO', None, False), ('S', None, False), ('Z', None, True)]}[name]
kind = op._weapon_type(None, op.resolve_record(app.EXPORTS['weapons'], weapon['path'], kind='weapon'))
disp = float(weapon['omegaAttenuation'])
stats = [(c, v if v is not None else round(op.RIVEN_BASE_VALUES[kind][c] * disp * op.theoretical_structure_scale(3, True, negative=n), 1), n) for c, v, n in stats]
request = dict(weapon=weapon['path'], disposition=float(weapon['omegaAttenuation']), profile='standard', headshotChance=hs,
               stats=[dict(code=c, value=v, negative=n) for c, v, n in stats],
               benchmarkTarget=dict(enemy=app._BENCHMARK_ENEMY_PATH, level=app._BENCHMARK_LEVEL, steelPath=True, eximus=False,
                                    enemyEnhancements=dict(app._BENCHMARK_ENHANCEMENTS), windowSeconds=window, armourStrip=0.0, headshotChance=hs))
t = time.perf_counter(); r = app.analyze_payload(request); el = time.perf_counter() - t
json.dump(dict(weapon=name, hs=hs, mode=mode, seconds=el, window=window, response=r), open(out, 'w', encoding='utf-8'), ensure_ascii=False, default=str)
print(name, hs, mode, round(el, 1), flush=True)
