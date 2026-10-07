import json, glob, sys
from pathlib import Path
S = Path(sys.argv[1])
cases = {}
for f in glob.glob(str(S / 'at/*.json')):
    d = json.load(open(f, encoding='utf-8')); r = d['response']
    rec = [s['code'] for t in r.get('recommendedPositiveTiers') or [] for s in t['stats']]
    cases.setdefault((d['weapon'], d['hs']), {})[d['mode']] = dict(
        seconds=d['seconds'], scale=(r.get('targetCalibration') or {}).get('healthScale'), gain=r.get('actualGain'),
        details={x['code']: x.get('delta') for x in r.get('details') or []}, rec=rec,
        kpm=((r.get('actual') or {}).get('benchmarkKpm') or (r.get('actual') or {}).get('killsPerMinute')))
for (w, hs), modes in sorted(cases.items()):
    cur = modes.get('cur')
    print(f"{w} hs{hs}")
    for m in ('cur', 'f20', 'f10', 'w10'):
        x = modes.get(m)
        if not x: continue
        ratio = x['seconds'] / cur['seconds'] if cur else float('nan')
        det = ' '.join(f"{c}:{v:+.0f}" for c, v in x['details'].items() if v is not None)
        g = x['gain'] if not isinstance(x['gain'], dict) else x['gain'].get('value', x['gain'])
        print(f"  {m:4s} {x['seconds']:6.1f}s x{ratio:4.2f} scale {x['scale']:.3f} gain {g if not isinstance(g, float) else round(g, 1)} | {det} | rec {','.join(x['rec'][:6])}")
