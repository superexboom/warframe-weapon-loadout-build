"""Kill-timing smoothing on/off vs WFSim on the captured KPM discrepancy cases."""
import json, sys
from pathlib import Path
ROOT = Path(r'C:\Users\SuperExboom\Documents\WF-Riven-Portable'); sys.path.insert(0, str(ROOT))
import app
from wfarsenal import proc_probability as pp
app._disable_analysis_statics_persistence()
orig = pp.KillAttribution.crossing
rows = []
for f in sys.argv[1:]:
    for row in json.load(open(f, encoding='utf-8'))['rows']:
        ref = row['reference']; reference = ref['score'] * 60 / ref['duration']
        pp.KillAttribution.crossing = orig
        on = app.simulate_manual_payload(row['payload'])['benchmarkTimeline']
        pp.KillAttribution.crossing = lambda self, t, r: (orig(self, t, r)[0], 0.)
        off = app.simulate_manual_payload(row['payload'])['benchmarkTimeline']
        pp.KillAttribution.crossing = orig
        rows.append(dict(weapon=row['weapon'], roll=row.get('roll', row.get('label')), ref=reference, on=on['killsPerMinute'], off=off['killsPerMinute'], shift=on.get('killTimingShiftSeconds') or 0.))
        r = rows[-1]
        print(f"{r['weapon']:22s} {str(r['roll']):10s} ref {reference:8.2f} off {r['off']:8.2f} ({(r['off']/reference-1)*100:+6.1f}%) on {r['on']:8.2f} ({(r['on']/reference-1)*100:+6.1f}%) shift {r['shift']:+.2f}s", flush=True)
import statistics as st
for k in ('off', 'on'):
    e = [abs(r[k] / r['ref'] - 1) * 100 for r in rows if r['ref']]
    print(k, 'mean abs %', round(st.mean(e), 2), 'median', round(st.median(e), 2), 'max', round(max(e), 1))
json.dump(rows, open(Path(__file__).parent / 'smoothwf.json', 'w'), indent=1)
