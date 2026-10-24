"""Can our optimizer build around a public WFSim Riven as well as WFSim does?

For each weapon's top public single-target board row with a Riven:
- public*: the board's mods minus weak-point specialised cards; our optimizer
  fills only the freed slots.
- ours: our optimizer fills every slot around the same Riven.
Both are scored in both engines with body shots, no arcanes, no exilus, on the
board target (Thrax Centurion Steel Path, level 9999 unless --level). If WFSim prefers public* the
selection is wrong; the local scores tell a search miss (local agrees with
WFSim) from a model error (local prefers ours).
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import (registry, exact_record, public_riven_spec,
                                                resolved_riven_payload, dump)

BATCH_JS = """import fs from 'node:fs'; import path from 'node:path';
const [repo,input,output]=process.argv.slice(2);
const rel=JSON.parse(fs.readFileSync(path.join(repo,'site/release.json'),'utf8'));
const base=path.join(repo,'site/pkg');
const engine=new Function(fs.readFileSync(path.join(base,'wfsim_wasm.'+rel.wasm+'.js'),'utf8')+';return wasm_bindgen;')();
engine.initSync({module:fs.readFileSync(path.join(base,'wfsim_wasm_bg.'+rel.wasm+'.wasm'))});
// Since 2026-10-17 the game data ships as packs the engine is handed before its first call.
for(const pack of rel.packs||[]){const err=engine.install_data_bytes(new Uint8Array(fs.readFileSync(path.join(base,pack))));if(err)throw new Error(pack+': '+err);}
const rows=JSON.parse(fs.readFileSync(input,'utf8'));
fs.writeFileSync(output,JSON.stringify(rows.map(([api,p])=>JSON.parse(engine.api(api,JSON.stringify(p))))),{flag:'wx'});
"""
TARGET = dict(enemy=app._BENCHMARK_ENEMY_PATH, level=9999, steelPath=True)


def weak_point_specialised(record):
    """Effect-level rule: weak-point/headshot stats or headshot conditions."""
    rows = [e.get('upgradeType') for e in record.get('effects') or []]
    for c in record.get('conditionalEffects') or []:
        rows += list(c.get('conditions') or []) + [e.get('upgradeType') for e in c.get('effects') or []]
    text = json.dumps(rows).upper()
    return any(k in text for k in ('WEAKPOINT', 'HEADSHOT', 'HEAD_SHOT'))


def wfsim(repo, folder, name, calls):
    (folder / f'{name}.mjs').write_text(BATCH_JS, encoding='utf-8')
    dump(folder / f'{name}-requests.json', calls)
    subprocess.run(['node', str(folder / f'{name}.mjs'), str(repo), str(folder / f'{name}-requests.json'),
                    str(folder / f'{name}-responses.json')], check=True)
    return json.loads((folder / f'{name}-responses.json').read_text(encoding='utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wfsim', type=Path, required=True, help='pinned checkout with data/ and site/')
    p.add_argument('--weapons', nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--profile', default='standard')
    p.add_argument('--runs', type=int, default=100)
    p.add_argument('--level', type=int, default=9999, help='9999 is the board target; lower levels let on-kill mods work')
    args = p.parse_args()
    TARGET['level'] = args.level
    if args.output.exists():
        p.error('choose a new evidence directory')
    args.output.mkdir(parents=True)
    app._disable_analysis_statics_persistence()
    board = json.loads((ROOT / '.local/wfsim-board-index.json').read_text(encoding='utf-8'))
    mods = registry(args.wfsim / 'data/mods'); weapons = registry(args.wfsim / 'data/weapons')
    wfsim_id = {row.get('internal_name'): mid for mid, row in mods.items() if row.get('internal_name')}
    weak = sorted(m['path'] for m in app.EXPORTS['mods'] if m['path'] in app.MANUAL_MODS_BY_PATH and weak_point_specialised(m))
    cases, skips = [], []
    for wid in args.weapons:
        rows = [r for r in board.get(wid, []) if r.get('benchmark') == 'standard_single_target' and r.get('riven')]
        rows = [r for r in rows if r.get('mode') == 'base' and not r.get('evolutions') and not r.get('valence')]
        if not rows:
            skips.append(dict(weapon=wid, reason='no base-form riven row without evolutions/valence')); continue
        row = max(rows, key=lambda r: r['score'])
        try:
            weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
            spec = public_riven_spec(row)
            cases.append(dict(weapon=wid, path=weapon['path'], name=weapon['nameEn'], row=row, spec=spec,
                              publicMods=[exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in row['mods'] if m != 'riven']))
        except (ValueError, KeyError) as e:
            skips.append(dict(weapon=wid, reason=str(e)))
    rivens = wfsim(args.wfsim, args.output, 'riven', [['/api/riven', dict(weapon=c['weapon'], **c['spec'])] for c in cases])
    for case, resolved in zip(cases, rivens):
        kind = app.optimizer._weapon_type(None, app.optimizer.resolve_record(app.EXPORTS['weapons'], case['path'], kind='weapon'))
        try:
            case['riven'] = resolved_riven_payload(case['spec'], resolved, 0, kind)
        except ValueError as e:
            case['skip'] = str(e)
    scenario = dict(aiming=True, triggerPolicy='emergent', distance=0.5)
    for case in cases:
        if case.get('skip'):
            continue
        base = dict(weapon=case['path'], fireMode=0, metric='killsPerMinute', headshotChance=0.0, scenario=scenario,
                    profile=args.profile, slotCount=8, forbiddenMods=weak, riven=dict(case['riven']), **TARGET)
        kept = [m for m in case['publicMods'] if m not in weak]
        case['removedWeakPoint'] = [m for m in case['publicMods'] if m in weak]
        for label, extra in (('public', dict(requiredMods=kept)), ('ours', {})):
            try:
                build = app.build_weapon_payload({**base, **extra})['build']
                case[label] = dict(mods=[dict(path=m['path'], rank=m['rank'], slot=m['slot']) for m in build['mods']],
                                   riven=build['riven'])
            except (app.SimulationError, KeyError, ValueError) as e:
                case[label] = dict(error=str(e))
        print(case['weapon'], 'built', flush=True)
    calls, slots = [], []
    for case in cases:
        for label in ('public', 'ours'):
            build = case.get(label) or {}
            if 'mods' not in build:
                continue
            manual = dict(weapon=case['path'], fireMode=0, mods=build['mods'], riven=build['riven'], arcanes=[],
                          headshotChance=0.0, aiming=True, triggerPolicy='emergent', scenario=dict(distance=0.5),
                          slotPolarities=[None] * 8, **TARGET)
            build['localKpm'] = app.simulate_manual_payload(manual)['benchmarkTimeline']['killsPerMinute']
            ids = ['riven:board' if i == build['riven']['slot'] else None for i in range(8)]
            for m in build['mods']:
                ids[m['slot']] = wfsim_id[m['path']]
            build['wfsimMods'] = [x for x in ids if x]
            calls.append(['/api/simulate', dict(weapon=case['weapon'], mode='base', mods=build['wfsimMods'], arcane=[],
                          evolutions=[], enemy='thrax_centurion', level=args.level, steel_path=True, headshot_pct=0,
                          aiming=True, duration=30., runs=args.runs, seed=12648430, infinite_ammo=True,
                          ammo_drops=False, eximus=False, assume_max=False, player_at=[0, 0], target_at=[0, .5],
                          rivens=[dict(id='board', spec=case['spec'])])])
            slots.append(build)
    for build, ref in zip(slots, wfsim(args.wfsim, args.output, 'simulate', calls)):
        build['wfsimKpm'] = ref['score'] * 60 / ref['duration'] if ref.get('ok', True) and 'score' in ref else None
        build['wfsimError'] = None if build['wfsimKpm'] is not None else str(ref)[:300]
    names = {m['path']: m.get('nameEn') for m in app.EXPORTS['mods']}
    for case in cases:
        pub, own = case.get('public') or {}, case.get('ours') or {}
        if 'localKpm' in pub and 'localKpm' in own:
            print(f"{case['weapon']:16s} WFSim public*/ours {pub.get('wfsimKpm') or 0:8.2f}/{own.get('wfsimKpm') or 0:8.2f}"
                  f"  local {pub['localKpm']:8.2f}/{own['localKpm']:8.2f}")
            print('   public*', [names.get(m['path']) for m in pub['mods']])
            print('   ours   ', [names.get(m['path']) for m in own['mods']])
    dump(args.output / 'cases.json', dict(cases=cases, skips=skips, weakPointExcluded=weak))
    print('skips', skips)


if __name__ == '__main__':
    main()
