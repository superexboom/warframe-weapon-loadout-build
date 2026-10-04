"""Compare sniper Shot Combo Counter + scope bonus against WFSim /api/simulate.

Fixed crit builds, body shots, no arcanes, ADS, Thrax Centurion at each level.
Local numbers come from the production manual path (simulate_manual_payload),
and again with sniper profiles disabled to show what the mechanic is worth.

Reference runner, one of:
  --wfsim-runtime DIR  captured runtime (site/release.json + site/pkg WASM), run with node
  --driver BIN         native binary: BIN /api/simulate INPUT.json OUTPUT.json
A new --output directory is required per run; source checkouts stay read-only.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import BATCH_JS, exact_record, public_evolutions, registry

CRIT_BUILD = ['serration', 'split_chamber', 'vital_sense', 'point_strike',
              'hammer_shot', 'heavy_caliber', 'infected_clip', 'high_voltage']
# The manual path always applies an Incarnon route, so pin the same one on both
# sides (these are the local community defaults for the Vectis Prime).
VECTIS_PRIME_EVOLUTIONS = ['vectis_prime_evo1_incarnon_form', 'vectis_prime_lone_enforcer',
                           'vectis_prime_marksmans_hand', 'vectis_prime_critical_parallel']
# Heat DoT: the combo must reach the hit and not the status payload.
HEAT_BUILD = ['serration', 'split_chamber', 'vital_sense', 'point_strike',
              'hammer_shot', 'heavy_caliber', 'hellfire', 'thermite_rounds']
CASES = [
    ('rubico_prime', CRIT_BUILD, True, []),
    ('rubico_prime', HEAT_BUILD, True, []),
    ('rubico_prime', HEAT_BUILD, False, []),
    ('vectis_prime', CRIT_BUILD, True, VECTIS_PRIME_EVOLUTIONS),
    ('lanka', CRIT_BUILD, True, []),
    ('vulkar_wraith', CRIT_BUILD, True, []),
    # Hip fire: neither engine has a counter or a scope bonus.
    ('rubico_prime', CRIT_BUILD, False, []),
    ('lanka', CRIT_BUILD, False, []),
]


def local_kpm(payload, *, disable_sniper=False):
    from wfarsenal import sniper_combo
    original = sniper_combo.profiles
    if disable_sniper:
        sniper_combo.profiles = lambda: {}
    try:
        result = app.simulate_manual_payload(payload)
    finally:
        sniper_combo.profiles = original
    timeline = result['benchmarkTimeline']
    stats = result.get('moddedStats') or {}
    return dict(kpm=timeline['killsPerMinute'], shots=timeline.get('shots'),
                critChance=stats.get('critChance'), critMultiplier=stats.get('critMultiplier'),
                sniperCombo={k: v for k, v in (timeline.get('sniperCombo') or {}).items() if k != 'events'} or None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wfsim', type=Path, required=True, help='WFSim source checkout (data/ YAML)')
    runner = parser.add_mutually_exclusive_group(required=True)
    runner.add_argument('--wfsim-runtime', type=Path)
    runner.add_argument('--driver', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--levels', type=int, nargs='+', default=[9999, 170])
    parser.add_argument('--runs', type=int, default=400)
    parser.add_argument('--duration', type=float, default=30.0)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output exists; preserve previous evidence')
    args.output.mkdir(parents=True)
    mods = registry(args.wfsim / 'data/mods')
    weapons = registry(args.wfsim / 'data/weapons')
    evolutions = registry(args.wfsim / 'data/evolutions')
    cases, requests = [], []
    for level in args.levels:
        for wid, build, aiming, evolution_ids in CASES:
            weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
            cards = [exact_record(mods[m], app.EXPORTS['mods']) for m in build]
            payload = dict(weapon=weapon['path'], fireMode=0,
                           mods=[dict(path=c['path'], rank=c['maxRank'], slot=i) for i, c in enumerate(cards)],
                           arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH, level=level, steelPath=True,
                           headshotChance=0.0, aiming=aiming, triggerPolicy='emergent',
                           slotPolarities=[c.get('polarity') for c in cards])
            choices, _ = public_evolutions(weapon, wid, evolution_ids, evolutions)
            if choices:
                payload['incarnonChoices'] = choices
            requests.append(dict(weapon=wid, mode='base', mods=build, arcane=[], evolutions=evolution_ids,
                                 evolutions_as_given=True, enemy='thrax_centurion', level=level,
                                 steel_path=True, headshot_pct=0, aiming=aiming, duration=args.duration,
                                 runs=args.runs, seed=12648430, infinite_ammo=True, ammo_drops=False,
                                 spectral_form=False, eximus=False, assume_max=False, frenzy=False,
                                 player_at=[0, 0], target_at=[0, 0.5]))
            cases.append(dict(weapon=wid, build='heat' if build is HEAT_BUILD else 'crit',
                              level=level, aiming=aiming, payload=payload,
                              local=local_kpm(payload), localWithoutSniper=local_kpm(payload, disable_sniper=True)))
    request_file, response_file = args.output / 'requests.json', args.output / 'responses.json'
    request_file.write_text(json.dumps(requests, indent=2), encoding='utf-8')
    if args.driver:
        subprocess.run([str(args.driver), '/api/simulate', str(request_file), str(response_file)], check=True)
        reference = dict(runner='native-driver', driver=str(args.driver))
    else:
        (args.output / 'batch.mjs').write_text(BATCH_JS, encoding='utf-8')
        subprocess.run(['node', str(args.output / 'batch.mjs'), str(args.wfsim_runtime),
                        str(request_file), str(response_file)], check=True)
        reference = dict(runner='wasm', release=json.loads(
            (args.wfsim_runtime / 'site/release.json').read_text(encoding='utf-8')))
    commit = subprocess.run(['git', '-C', str(args.wfsim), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True).stdout.strip() or None
    for case, ref in zip(cases, json.loads(response_file.read_text(encoding='utf-8')), strict=True):
        if not ref.get('ok'):
            case['referenceError'] = ref
            continue
        kpm = ref['score'] * 60 / ref['duration']
        se = ref.get('score_se', 0.0) * 60 / ref['duration']
        panel = ref['panel']
        case.update(referenceKpm=kpm, referenceKpmSe=se,
                    referencePanel=dict(critChance=panel['crit_chance'], critMultiplier=panel['crit_damage']),
                    deltaPercent=100 * (case['local']['kpm'] / kpm - 1) if kpm else None,
                    deltaWithoutSniperPercent=100 * (case['localWithoutSniper']['kpm'] / kpm - 1) if kpm else None,
                    panelMatches=all(math.isclose(case['local'][k], panel[v], rel_tol=1e-3) for k, v in
                                     (('critChance', 'crit_chance'), ('critMultiplier', 'crit_damage'))))
        print(f"{case['weapon']:13} {case['build']:4} L{case['level']:<5} ads={case['aiming']!s:5} local {case['local']['kpm']:8.4f} "
              f"(no sniper {case['localWithoutSniper']['kpm']:8.4f})  wfsim {kpm:8.4f} ±{se:.4f}  "
              f"delta {case['deltaPercent']:+.2f}%  panel={case['panelMatches']}", flush=True)
    (args.output / 'comparison.json').write_text(json.dumps(dict(
        sourceCommit=commit, reference=reference, runs=args.runs, duration=args.duration, seed=12648430,
        contract='Thrax Centurion, Steel Path, body shots, no arcanes, single target, infinite reserve ammo',
        cases=cases), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
