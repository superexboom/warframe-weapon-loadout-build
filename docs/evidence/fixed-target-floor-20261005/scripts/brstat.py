import json, glob, sys, statistics as st
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from wsstat_lib import spearman
rows = []
for f in sorted(glob.glob(str(Path(sys.argv[1]) / 'br/br-?.json'))): rows += json.load(open(f))
rows = [r for r in rows if r['branches']['64']['branchedShare'] > 0]
print('cases with branching', len(rows))
print(f"{'branches':8s} {'ms/replay':>9s} {'xb16':>5s} | {'KPM err mean/max %':>18s} | {'value err mean/max pp':>21s} | {'rho min':>7s} {'top3':>5s}")
t16 = st.mean(r['branches']['16']['msPerReplay'] for r in rows)
for n in ('64', '16', '8', '4', '2', '0'):
    ke = [abs(r['branches'][n]['kpm'] / r['branches']['64']['kpm'] - 1) * 100 for r in rows]
    ve = [abs(r['branches'][n]['values'][c] - r['branches']['64']['values'][c]) * 100 for r in rows for c in r['branches']['64']['values']]
    rho = [spearman(r['branches'][n]['values'], r['branches']['64']['values']) for r in rows]
    top = st.mean(len(set(sorted(r['branches'][n]['values'], key=lambda c: -r['branches'][n]['values'][c])[:3]) &
                      set(sorted(r['branches']['64']['values'], key=lambda c: -r['branches']['64']['values'][c])[:3])) / 3 for r in rows)
    t = st.mean(r['branches'][n]['msPerReplay'] for r in rows)
    print(f"{n:8s} {t:9.0f} {t / t16:5.2f} | {st.mean(ke):8.2f} / {max(ke):6.2f} | {st.mean(ve):9.2f} / {max(ve):7.2f} | {min(rho):7.2f} {top:5.2f}")
print('worst value errors at 4 branches:')
w = sorted(((abs(r['branches']['4']['values'][c] - r['branches']['64']['values'][c]) * 100, r['weapon'], r['hs'], c,
             r['branches']['64']['values'][c] * 100, r['branches']['16']['values'][c] * 100, r['branches']['4']['values'][c] * 100, r['branches']['0']['values'][c] * 100)
            for r in rows for c in r['branches']['64']['values']), reverse=True)[:8]
for x in w: print('  %.1fpp %s hs%.2f %s  b64 %+.1f b16 %+.1f b4 %+.1f b0 %+.1f' % x)
