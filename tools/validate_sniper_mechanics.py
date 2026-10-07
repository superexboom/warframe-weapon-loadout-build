"""Compare sniper Shot Combo / zoom handling with pinned WFSim.

Per weapon: an unmodded build, a fixed crit build and the top public board
row (base form; its Riven resolved through WFSim /api/riven). The local
manual path always routes Incarnon tiers, so an Incarnon weapon runs every
build with that public row's evolutions in both engines.
Each is scored by both engines on Thrax Centurion Steel Path, aiming, no
arcanes, at every requested level and hit location. The first hits of the
unmodded build are also read from WFSim /api/log, so the per-hit combo and
crit factors can be compared directly with the local combo events.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.audit_riven_board_builds import wfsim
from tools.compare_archgun_board_builds import (registry, exact_record, public_riven_spec,
                                                resolved_riven_payload, public_evolutions, dump)

CRIT_BUILD = ['serration', 'split_chamber', 'vital_sense', 'point_strike', 'heavy_caliber', 'hammer_shot',
              'primed_cryo_rounds', 'infected_clip']
SEED = 12648430


def fight(wid, mods, level, head, runs, spec=None, evolutions=()):
    return dict(weapon=wid, mode='base', mods=mods, arcane=[], evolutions=list(evolutions),
                evolutions_as_given=bool(evolutions), enemy='thrax_centurion', level=level,
                steel_path=True, headshot_pct=head, aiming=True, duration=30., runs=runs, seed=SEED,
                infinite_ammo=True, ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0],
                target_at=[0, .5], rivens=[dict(id='board', spec=spec)] if spec else [])


def local(path, mods, riven, level, head, choices=None):
    payload = dict(weapon=path, fireMode=0, mods=mods, riven=riven, arcanes=[], headshotChance=head / 100.,
                   incarnonChoices=choices or {},
                   aiming=True, triggerPolicy='emergent', scenario=dict(distance=0.5), slotPolarities=[None] * 8,
                   enemy=app._BENCHMARK_ENEMY_PATH, level=level, steelPath=True)
    result = app.simulate_manual_payload(payload)
    timeline = result['benchmarkTimeline']
    combo = timeline.get('sniperCombo') or {}
    return dict(kpm=timeline['killsPerMinute'], critMultiplier=(result.get('moddedStats') or {}).get('critMultiplier'),
                comboFirst=[round(e['multiplier'], 4) for e in (combo.get('events') or [])[:12]])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wfsim', type=Path, required=True, help='pinned checkout with data/ and site/')
    p.add_argument('--weapons', nargs='+', default=['rubico_prime', 'vectis_prime', 'lanka', 'vulkar_wraith'])
    p.add_argument('--levels', nargs='+', type=int, default=[170, 9999])
    p.add_argument('--heads', nargs='+', type=int, default=[0, 100])
    p.add_argument('--runs', type=int, default=100)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error('choose a new evidence directory')
    a.output.mkdir(parents=True)
    app._disable_analysis_statics_persistence()
    board = json.loads((ROOT / '.local/wfsim-board-index.json').read_text(encoding='utf-8'))
    mods = registry(a.wfsim / 'data/mods'); weapons = registry(a.wfsim / 'data/weapons')
    # WFSim names some evolution icons 'Incarnon<Name>' where the package says '<Name>'.
    evolutions = {k: {**v, 'icon': str(v.get('icon') or '').removeprefix('Incarnon')}
                  for k, v in registry(a.wfsim / 'data/evolutions').items()}
    path_of = lambda mid: exact_record(mods[mid], app.EXPORTS['mods'])['path']
    rank_of = lambda path: app.MANUAL_MODS_BY_PATH[path]['maxRank']
    cases = []
    for wid in a.weapons:
        weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
        incarnon = bool((weapon.get('incarnon') or {}).get('tiers'))
        rows = [r for r in board.get(wid, []) if r.get('benchmark') == 'standard_single_target'
                and r.get('mode') == 'base' and not r.get('valence') and bool(r.get('evolutions')) == incarnon]
        row = max(rows, key=lambda r: r['score']) if rows else None
        evo = list(row.get('evolutions') or []) if row else []
        choices = public_evolutions(weapon, wid, evo, evolutions)[0] if evo else {}
        common = dict(weapon=wid, path=weapon['path'], evolutions=evo, choices=choices)
        cases.append(dict(common, build='bare', mods=[]))
        cases.append(dict(common, build='crit', mods=CRIT_BUILD))
        if row:
            cases.append(dict(common, build='board', row=row,
                              mods=[m for m in row['mods'] if m != 'riven'],
                              spec=public_riven_spec(row) if row.get('riven') else None))
    with_riven = [c for c in cases if c.get('spec')]
    for case, resolved in zip(with_riven, wfsim(a.wfsim, a.output, 'riven',
                                                [['/api/riven', dict(weapon=c['weapon'], **c['spec'])] for c in with_riven])):
        kind = app.optimizer._weapon_type(None, app.optimizer.resolve_record(app.EXPORTS['weapons'], case['path'], kind='weapon'))
        case['riven'] = resolved_riven_payload(case['spec'], resolved, len(case['mods']), kind)
    calls, rows = [], []
    for case in cases:
        local_mods = [dict(path=path_of(m), rank=rank_of(path_of(m)), slot=i) for i, m in enumerate(case['mods'])]
        wf_mods = list(case['mods']) + (['riven:board'] if case.get('spec') else [])
        for level in a.levels:
            for head in a.heads:
                row = dict(weapon=case['weapon'], build=case['build'], level=level, headshotPct=head,
                           mods=case['mods'], riven=case.get('riven'))
                row['local'] = local(case['path'], local_mods, case.get('riven'), level, head, case['choices'])
                row['evolutions'] = case['evolutions']
                calls.append(['/api/simulate', fight(case['weapon'], wf_mods, level, head, a.runs, case.get('spec'),
                                                     case['evolutions'])])
                rows.append(row)
                print(case['weapon'], case['build'], level, head, 'local', round(row['local']['kpm'], 3), flush=True)
    for row, ref in zip(rows, wfsim(a.wfsim, a.output, 'simulate', calls)):
        row['wfsimKpm'] = ref['score'] * 60 / ref['duration'] if ref.get('ok', True) and 'score' in ref else None
        row['wfsimRun'] = ref.get('run')
        row['wfsimError'] = None if row['wfsimKpm'] is not None else str(ref)[:300]
    # Per-hit factors: the median run of the unmodded body-shot fight at the lowest level.
    probes = [r for r in rows if r['build'] == 'bare' and r['headshotPct'] == 0 and r['level'] == min(a.levels)]
    logs = wfsim(a.wfsim, a.output, 'log', [['/api/log', dict(fight(r['weapon'], [], r['level'], 0, a.runs,
                                                                        evolutions=r['evolutions']),
                                                                  run=r['wfsimRun'], limit=40)] for r in probes])
    for row, log in zip(probes, logs):
        row['wfsimLog'] = log
    dump(a.output / 'rows.json', rows)
    for r in rows:
        wk = r['wfsimKpm']
        print(f"{r['weapon']:14s} {r['build']:5s} L{r['level']:<5d} head{r['headshotPct']:>3d}  "
              f"local {r['local']['kpm']:9.3f}  wfsim {wk if wk is not None else float('nan'):9.3f}  "
              f"ratio {r['local']['kpm'] / wk if wk else float('nan'):6.3f}")


if __name__ == '__main__':
    main()
