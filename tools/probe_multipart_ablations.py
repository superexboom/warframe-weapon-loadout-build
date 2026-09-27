"""Ablate saved builds without changing the reference or claiming a new search."""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.compare_generated_builds import reference_request, exact_index, reference_identity_matches
from tools.compare_archgun_board_builds import registry, BATCH_JS


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wfsim', type=Path, required=True)
    ap.add_argument('--builds', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--names', nargs='+', required=True, help='exact saved case labels')
    ap.add_argument('--runs', type=int, default=1000)
    a = ap.parse_args()
    if a.output.exists() or a.runs < 1:
        ap.error('use a new output directory and positive runs')
    inputs = json.loads(a.builds.read_text(encoding='utf-8'))
    missing = set(a.names) - {r['name'] for r in inputs}
    if missing: ap.error('unknown case labels: ' + ', '.join(sorted(missing)))
    weapons = exact_index(registry(a.wfsim/'data/weapons'))
    mods = exact_index(registry(a.wfsim/'data/mods'))
    arcs = exact_index(registry(a.wfsim/'data/arcanes'))
    rows = []; requests = []
    app._disable_analysis_statics_persistence()
    for row in inputs:
        if row['name'] not in a.names: continue
        for variant in ['original', 'body', 'no-acuity', 'no-spread-penalty']:
            p = {**row['manualRequest']}
            if variant == 'body': p['headshotChance'] = 0.
            if variant.startswith('no-'):
                names = ['Primary Acuity','Pistol Acuity'] if variant == 'no-acuity' else ['Heavy Caliber','Magnum Force']
                p['mods'] = [m for m in p['mods'] if app.MANUAL_MODS_BY_PATH[m['path']]['nameEn'] not in names]
            q, _ = reference_request(p, weapons, mods, arcs, a.runs)
            local = app.simulate_manual_payload(p)['benchmarkTimeline']
            rows.append(dict(name=row['name'], variant=variant, manualKpm=local['killsPerMinute'],
                localShots=local['shots'], request=q, manualRequest=p))
            requests.append(q)
    a.output.mkdir(parents=True)
    def save(name, value):
        (a.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    save('requests.json', requests)
    (a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    failed = False
    for row, response in zip(rows,json.loads((a.output/'responses.json').read_text(encoding='utf-8')),strict=True):
        if not response.get('ok') or not reference_identity_matches(response,row['request']):
            row['referenceError'] = response; failed = True; continue
        kpm = response['score']*60/response['duration']
        row.update(referenceKpm=kpm,deltaPercent=(row['manualKpm']/kpm-1)*100 if kpm else None,referenceShots=response['shots'])
        print(row['name'],row['variant'],row['deltaPercent'],flush=True)
    save('summary.json',dict(cases=rows,localFingerprint=app._analysis_inputs_fingerprint(),
        sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),
        contract='Fixed-build ablations; changing one input family, no new optimizer search'))
    if failed: raise SystemExit(1)

if __name__ == '__main__': main()
