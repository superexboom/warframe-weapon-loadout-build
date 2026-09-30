"""Replay real recommendation/analysis results after Incarnon mechanism changes."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['WF_ANALYZER_SERIAL'] = '1'
import app
from tools.audit_riven_analysis_context import request_for, replay_returned


def legal_riven(result, stats):
    positives = sum(not row['negative'] for row in stats)
    negatives = len(stats) - positives
    if positives not in (2, 3) or negatives > 1:
        return False
    bases = app.RIVEN_BASE_VALUES[result['weaponType']]
    for row in stats:
        nominal = bases[row['code']] * result['disposition'] * app.optimizer.theoretical_structure_scale(
            positives, bool(negatives), negative=row['negative'])
        if not nominal * .89 - .11 <= row['value'] <= nominal * 1.089 + .11:
            return False
    return sum(row['code'] in app.optimizer._FUSION_LINE_CODES for row in stats) <= 1


def replay_combo(request, result, combo):
    target = result['evaluationTarget']
    build = combo['build']
    payload = {**request, 'fireMode': result['fireMode'], 'incarnonChoices': result['incarnonChoices'],
               'scenario': result['evaluationScenario'], 'mods': build['mods'], 'riven': build['riven'],
               'exilus': build.get('exilus'), 'slotPolarities': [None] * 8,
               'enemy': target['path']}
    for row in build['mods']:
        payload['slotPolarities'][row['slot']] = app.MANUAL_MODS_BY_PATH[row['path']].get('polarity')
    payload['slotPolarities'][build['riven']['slot']] = build['riven'].get('polarity') or 'AP_ATTACK'
    if result.get('innateElement'):
        payload.update(innateElement=result['innateElement']['damageType'], innateElementValue=result['innateElement']['value'])
    if not result.get('optimizeWithArcanes', True):
        payload['arcanes'] = []
    manual = app.simulate_manual_payload(payload)
    score = manual['benchmarkTimeline']['killsPerMinute']
    matches = math.isclose(score, combo['score'], rel_tol=1e-8, abs_tol=1e-8)
    return dict(request=payload, manualKpm=score, score=combo['score'], matches=matches,
                legalRiven=legal_riven(result, combo['stats']),
                triggers=manual['benchmarkTimeline']['triggerSeries'], unsupported=manual.get('unsupported'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    parser.add_argument('--analysis', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app._disable_analysis_statics_persistence()
    fingerprint = app._analysis_inputs_fingerprint()
    cases = [
        ('Dera Vandal', 1, {'tier2': '2-2'}, {'incarnonCycle': True, 'distance': 10.}),
        ('Laetum', 1, {'tier5': '5-3'}, {'incarnonCycle': True, 'distance': 10.}),
        ('Felarx', 0, {'tier5': '5-1'}, {'distance': 10.}),
        ('Phenmor', 1, {'tier5': '5-1'}, {'incarnonCycle': True, 'distance': 10.}),
        ('Burston Prime', 1, {'tier2': '2-1', 'tier4': '4-1'}, {'incarnonCycle': True, 'distance': 10.}),
        ('Torid', 1, {'tier2': '2-1', 'tier3': '3-2'}, {'incarnonCycle': True, 'distance': 10.}),
    ]
    summary = []
    for i, (name, mode, choices, scenario) in enumerate(cases[:args.limit]):
        output = args.output / f'{i:02d}-{name.lower().replace(" ", "-")}.json'
        if output.exists():
            saved = json.loads(output.read_text(encoding='utf-8'))
            if saved.get('fingerprint') != fingerprint or not saved.get('passed'):
                parser.error('existing result failed or uses another fingerprint; choose a new output')
            summary.append(saved)
            continue
        raw = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
        request = dict(weapon=raw['path'], fireMode=mode, incarnonChoices=choices, scenario=scenario,
                       metric='killsPerMinute', profile='fast', slotCount=4, minFill=3, maxFill=4,
                       enemy=app._BENCHMARK_ENEMY_PATH, level=9999, steelPath=True,
                       enemyEnhancements={'eximus': True}, headshotChance=.5, budgetSeconds=10., topLimit=3)
        started = time.perf_counter()
        row = dict(name=name, request=request, fingerprint=fingerprint)
        print('recommend', name, flush=True)
        try:
            result = app.recommend_riven_payload(request)
            row['recommendation'] = result
            row['replays'] = [replay_combo(request, result, combo) for combo in result['combos']]
            row['passed'] = bool(row['replays']) and all(r['matches'] and r['legalRiven'] for r in row['replays'])
            if args.analysis:
                analysis_request = request_for(name, scenario)
                analysis_request.update(fireMode=mode, incarnonChoices=choices, slotCount=4, minFill=3, maxFill=4)
                analysis = app.analyze_payload(analysis_request)
                row['analysis'] = analysis
                row['analysisReplays'] = {key: replay_returned(analysis_request, analysis, analysis[key])
                                          for key in ('baseline', 'actual', 'optimal')}
                row['passed'] = row['passed'] and all(r['passed'] for r in row['analysisReplays'].values())
        except Exception as exc:
            row.update(passed=False, error=f'{type(exc).__name__}: {exc}')
        row['elapsedSeconds'] = time.perf_counter() - started
        row['passed'] = row.get('passed', False) and fingerprint == app._analysis_inputs_fingerprint()
        output.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        summary.append(row)
        (args.output / 'summary.json').write_text(json.dumps([
            {k: r.get(k) for k in ('name', 'passed', 'error', 'fingerprint', 'elapsedSeconds')}
            for r in summary], ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(name, row['passed'], row.get('error'), round(row['elapsedSeconds'], 1), flush=True)
    return int(any(not r['passed'] for r in summary))


if __name__ == '__main__':
    raise SystemExit(main())
