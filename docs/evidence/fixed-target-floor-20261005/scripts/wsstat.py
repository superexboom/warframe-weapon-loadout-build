import json, glob, sys, statistics as st
from pathlib import Path
S = Path(sys.argv[1])
rows = []
for f in sorted(glob.glob(str(S / 'ws-?.json'))): rows += json.load(open(f))

def rank(v):
    order = sorted(v, key=lambda c: -v[c]); r = {}
    i = 0
    while i < len(order):  # average ranks for ties
        j = i
        while j + 1 < len(order) and abs(v[order[j + 1]] - v[order[i]]) < 1e-3: j += 1
        for k in range(i, j + 1): r[order[k]] = (i + j) / 2
        i = j + 1
    return r
def spearman(a, b):
    keys = [k for k in a if k in b]
    if len(keys) < 3: return None
    ra, rb = rank({k: a[k] for k in keys}), rank({k: b[k] for k in keys})
    ma, mb = st.mean(ra.values()), st.mean(rb.values())
    num = sum((ra[k] - ma) * (rb[k] - mb) for k in keys)
    den = (sum((ra[k] - ma) ** 2 for k in keys) * sum((rb[k] - mb) ** 2 for k in keys)) ** .5
    return num / den if den else 0.
def top(v, n=3): return set(sorted(v, key=lambda c: -v[c])[:n])
def flat(v):  # share of damage stats with identical value (breakpoint/rate-limited)
    d = [v[c] for c in ('0', '1', 'D', '4', 'CO', 'VI', 'W', 'Y') if c in v]
    return max(sum(abs(x - y) < 1e-3 for y in d) for x in d) / len(d)

configs = list(rows[0]['configs'])
print(f"{'config':8s} {'ms/replay':>9s} {'xref':>6s} {'x30':>5s} | {'rho hs0':>7s} {'rho hs.5':>8s} {'rho hs1':>7s} | {'top3 same':>9s} {'MAE pp':>6s} | {'flat>=75%':>9s} | {'hs1/hs0 health':>14s} {'rho(hs0,hs1)':>12s}")
t30 = st.mean(r['configs']['W30K5']['msPerReplay'] for r in rows)
tref = st.mean(r['configs']['ref']['msPerReplay'] for r in rows)
by = {(r['weapon'], r['hs']): r for r in rows}
for c in configs:
    t = st.mean(r['configs'][c]['msPerReplay'] for r in rows)
    rho = {h: [spearman(r['configs'][c]['values'], r['configs']['ref']['values']) for r in rows if r['hs'] == h] for h in (0., .5, 1.)}
    rho = {h: st.median([x for x in v if x is not None]) for h, v in rho.items()}
    t3 = st.mean(len(top(r['configs'][c]['values']) & top(r['configs']['ref']['values'])) / 3 for r in rows)
    mae = st.median(st.mean(abs(r['configs'][c]['values'][k] - r['configs']['ref']['values'][k]) for k in r['configs']['ref']['values']) * 100 for r in rows)
    fl = sum(flat(r['configs'][c]['values']) >= .75 for r in rows)
    ratio, cross = [], []
    for w in {r['weapon'] for r in rows}:
        a, b = by.get((w, 0.)), by.get((w, 1.))
        if a and b:
            ratio.append(b['configs'][c]['scale'] / a['configs'][c]['scale'])
            cross.append(spearman({k: v for k, v in a['configs'][c]['values'].items()}, {k: v for k, v in b['configs'][c]['values'].items() if k not in ('W', 'Y')}))
    print(f"{c:8s} {t:9.1f} {t / tref:6.2f} {t / t30:5.2f} | {rho[0.]:7.2f} {rho[.5]:8.2f} {rho[1.]:7.2f} | {t3:9.2f} {mae:6.1f} | {fl:4d}/{len(rows)} | {st.median(ratio):14.2f} {st.median(cross):12.2f}")
print()
print('per weapon W10K5 vs W30K5 vs ref rho (hs0/.5/1):')
for w in sorted({r['weapon'] for r in rows}):
    line = []
    for c in ('floor30', 'W10K5', 'W20K5', 'W30K5'):
        line.append(c + ' ' + '/'.join(f"{spearman(by[(w, h)]['configs'][c]['values'], by[(w, h)]['configs']['ref']['values']):.2f}" if (w, h) in by else '-' for h in (0., .5, 1.)))
    print(f"{w:16s} " + '  '.join(line))
