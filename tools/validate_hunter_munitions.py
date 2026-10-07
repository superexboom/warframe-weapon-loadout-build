"""Hunter Munitions delta: local replay vs pinned WFSim /api/simulate.

Each case is scored twice in both engines, the same mods with and without
Hunter Munitions (rank 5), body shots, no arcanes, no Riven, on Steel Path
Thrax Centurion. The local and WFSim gain ratios should agree; the absolute
baselines are reported alongside so a model error is not mistaken for an HM
error.

A weapon with an Incarnon Genesis is always simulated locally with one route
(the community default policy). The same route is sent to WFSim as explicit
evolutions; WFSim's plain ``evolutions: []`` is the weapon without them.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.audit_riven_board_builds import BATCH_JS
from tools.compare_archgun_board_builds import registry, exact_record, dump, ELEMENTS

HM = 'hunter_munitions'
BASE_MODS = ['serration', 'split_chamber', 'point_strike', 'vital_sense', 'hammer_shot']
CASES = {wid: BASE_MODS for wid in ('baza_prime', 'stahlta', 'stradavar_prime', 'prisma_gorgon', 'burston_prime', 'soma_prime')}
SHOTGUN_MODS = ['point_blank', 'hells_chamber', 'blunderbuss', 'ravage']
CASES.update(coda_bubonico=SHOTGUN_MODS)


def icon_key(value):
    # WFSim spells some evolution icons with an "Incarnon" prefix the packages lack.
    return str(value or '').rsplit('/', 1)[-1].replace('(xWhite)', '').casefold().removeprefix('incarnon')


PINNED_WFSIM = ROOT / '.local/wfsim-live-20261004'


def wfsim_zh_names(wfsim=PINNED_WFSIM):
    """WFSim's Chinese evolution names, matched against the game's (Laetum's
    icons use a separate "Evolution..." naming that never matches)."""
    import yaml
    path = Path(wfsim) / 'data/i18n/zh/evolutions.yaml'
    if not path.is_file():
        return {}
    names = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        key, sep, value = line.strip().partition(': ')
        if sep and key and value and not value.startswith('"') and key not in names:
            names[key] = value.strip()
    return names


def reference_evolutions(weapon, wid, choices, definitions, zh_names=None):
    """Local tier choices to WFSim evolution ids by unique weapon/tier/icon identity.

    The inverse of compare_archgun_board_builds.public_evolutions; an unmapped or
    ambiguous route is an error, never a silent drop.
    """
    tiers = {t.get('tier'): t for t in (weapon.get('incarnon') or {}).get('tiers') or []}
    ids = []
    for key, pick in sorted((choices or {}).items()):
        tier = int(str(key).removeprefix('tier'))
        branch = [b for b in (tiers.get(tier) or {}).get('branches') or [] if b.get('id') == pick]
        if len(branch) != 1:
            raise ValueError(f'unknown local evolution {wid} {key}={pick}')
        icons = {icon_key(s.get('icon')) for s in branch[0].get('sources') or [] if s.get('icon')}
        same_tier = [eid for eid, row in definitions.items() if row.get('weapon') == wid and row.get('tier') == tier]
        matches = [eid for eid in same_tier if icon_key(definitions[eid].get('icon')) in icons]
        if not matches and same_tier:
            # Unmatched icon naming (Laetum): the game's Chinese name.
            local_name = app.INCARNON_STRINGS.get(branch[0].get('nameTag'))
            names = wfsim_zh_names() if zh_names is None else zh_names
            matches = [eid for eid in same_tier if local_name and names.get(eid) == local_name]
        if len(matches) > 1:
            # Shared or absent icon: tell the branches apart by their effect magnitudes.
            local = {round(abs(float(e.get('valuePerRank') or 0)), 6)
                     for e in (branch[0].get('effects') or []) + [x for c in branch[0].get('conditionalEffects') or [] for x in c.get('effects') or []]}
            matches = [eid for eid in matches
                       if {round(abs(float(e.get('value') or 0)), 6) for e in definitions[eid].get('effects') or []
                           if isinstance(e.get('value'), (int, float))} <= local]
        if len(matches) != 1:
            raise ValueError(f'unmapped or ambiguous evolution {wid} {key}={pick}: {matches}')
        ids.append(matches[0])
    return ids


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wfsim', type=Path, required=True, help='pinned checkout with data/ and site/')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--weapons', nargs='*', default=list(CASES))
    p.add_argument('--level', type=int, default=170)
    p.add_argument('--runs', type=int, default=100)
    p.add_argument('--duration', type=float, default=30.)
    args = p.parse_args()
    if args.output.exists():
        p.error('choose a new evidence directory')
    args.output.mkdir(parents=True)
    app._disable_analysis_statics_persistence()
    mods = registry(args.wfsim / 'data/mods'); weapons = registry(args.wfsim / 'data/weapons')
    evolutions = registry(args.wfsim / 'data/evolutions')
    rows, calls = [], []
    for wid in args.weapons:
        weapon = exact_record(weapons[wid], app.EXPORTS['weapons'])
        mode = 0
        for with_hm in (False, True):
            ids = CASES.get(wid, BASE_MODS) + ([HM] if with_hm else [])
            paths = [exact_record(mods[m], app.EXPORTS['mods'])['path'] for m in ids]
            manual = dict(weapon=weapon['path'], fireMode=mode,
                          mods=[dict(path=path, rank=None, slot=i) for i, path in enumerate(paths)],
                          arcanes=[], headshotChance=0.0, aiming=True, triggerPolicy='emergent',
                          scenario=dict(distance=0.5), slotPolarities=[None] * 8,
                          enemy=app._BENCHMARK_ENEMY_PATH, level=args.level, steelPath=True,
                          combatState=dict(selfShieldBreakForced=False))  # WFSim: out of scope
            row = dict(weapon=wid, weaponPath=weapon['path'], fireMode=mode, hunterMunitions=with_hm,
                       mods=ids, modPaths=paths)
            try:
                result = app.simulate_manual_payload(manual)
            except app.SimulationError as e:
                row['localError'] = str(e)
            else:
                timeline = result['benchmarkTimeline']
                row.update(localDps=timeline['windowDps'], localKpm=timeline['killsPerMinute'],
                           localSlashProcs=result['statusProcs'].get('DT_SLASH'),
                           incarnonChoices=result.get('incarnonChoices') or {},
                           innateElement=result.get('innateElement'),
                           skipped=[s for s in result.get('skipped') or [] if 'Hunter' in s])
            row['evolutions'] = reference_evolutions(weapon, wid, row.get('incarnonChoices'), evolutions)
            rows.append(row)
            request = dict(weapon=wid, mode='base', mods=ids, arcane=[],
                           evolutions=row['evolutions'], evolutions_as_given=True, enemy='thrax_centurion', level=args.level, steel_path=True,
                           headshot_pct=0, aiming=True, duration=args.duration, runs=args.runs,
                           seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False,
                           assume_max=False, player_at=[0, 0], target_at=[0, .5])
            innate = row.get('innateElement')
            if weapons[wid].get('valence') and isinstance(innate, dict) and innate.get('damageType'):
                # The local resolved progenitor element, never the reference default.
                request.update(valence_element={v: k for k, v in ELEMENTS.items()}[innate['damageType']],
                               valence_bonus=innate['value'])
            calls.append(['/api/simulate', request])
    (args.output / 'simulate.mjs').write_text(BATCH_JS, encoding='utf-8')
    dump(args.output / 'simulate-requests.json', calls)
    subprocess.run(['node', str(args.output / 'simulate.mjs'), str(args.wfsim),
                    str(args.output / 'simulate-requests.json'), str(args.output / 'simulate-responses.json')],
                   check=True)
    refs = json.loads((args.output / 'simulate-responses.json').read_text(encoding='utf-8'))
    for row, ref in zip(rows, refs):
        if not ref.get('ok', True) or 'dps' not in ref:
            row['wfsimError'] = str(ref)[:300]
            continue
        row['wfsimDps'] = ref['dps']
        row['wfsimKpm'] = ref['score'] * 60 / ref['duration']
        row['wfsimSlashDot'] = sum(s['dmg'] for s in ref['damage_sources'] if s['source'] == 'Slash')
    print(f"{'weapon':20s} {'local dps':>10s} {'wfsim dps':>10s} {'base ratio':>10s}  "
          f"{'local HM gain':>13s} {'wfsim HM gain':>13s}")
    summary = []
    for base, hm in zip(rows[::2], rows[1::2]):
        if any(k not in r for r in (base, hm) for k in ('wfsimDps', 'localDps')):
            print(base['weapon'], 'error', [r.get(k) for r in (base, hm) for k in ('wfsimError', 'localError')],
                  'base local/wfsim', base.get('localDps'), base.get('wfsimDps'), 'hm wfsim', hm.get('wfsimDps'))
            continue
        item = dict(weapon=base['weapon'],
                    baselineRatio=base['localDps'] / base['wfsimDps'],
                    localGain=hm['localDps'] / base['localDps'],
                    wfsimGain=hm['wfsimDps'] / base['wfsimDps'],
                    localKpmGain=hm['localKpm'] / base['localKpm'] if base['localKpm'] else None,
                    wfsimKpmGain=hm['wfsimKpm'] / base['wfsimKpm'] if base['wfsimKpm'] else None)
        summary.append(item)
        print(f"{base['weapon']:20s} {base['localDps']:10.0f} {base['wfsimDps']:10.0f} "
              f"{item['baselineRatio']:10.3f}  {item['localGain']:13.3f} {item['wfsimGain']:13.3f}")
    dump(args.output / 'cases.json', dict(level=args.level, runs=args.runs, duration=args.duration,
                                         rows=rows, summary=summary))


if __name__ == '__main__':
    main()
