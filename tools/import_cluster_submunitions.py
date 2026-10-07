"""Import cluster submunitions (Zarr / Kuva Zarr / Kuva Bramma / Kulstar bomblets).

A native projectile with NumClusterProjectiles > 0 releases that many child
projectiles (ClusterProjectiles, a sibling record). Each child lands its own
direct hit (AttackData) and explosion (ExplosiveAttack) with its own crit and
status. Both are added to the audited attack as ``clusters`` and replayed as
extra radial-only parts fired ``count`` times per shell (no weak point).

Three sources must agree, otherwise the weapon is skipped with a reason:
the export mode (projectile identity), the native child record (count,
amounts, type, radius) and the pinned WFSim ``attack.cluster`` block (count,
direct and radial totals). Crit is taken from the native child when present
and status from the reference, as tools/import_projectile_components.py does
for the shell's explosion; every disagreement is recorded. WFSim does not
multiply the shell's explosion by multishot; the bomblets follow the shell.

Condition Overload: the wiki catalog row WFSim quotes as unmodelled
(``cluster_bomblet_co``: "name | attack | Projectile | unmodded | actual CO
bonus at +100% | relative | rule") gives the bomblet's projectile hit its own
rule; with ``Adding`` the bonus per +100% is the parent's value, i.e. a CO
base fraction of actual / unmodded. The bomblet explosion has no row and
takes none (as in WFSim).
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'tools'))
from wfarsenal.packages import PackageIndex
from import_projectile_components import DT, close


def part(name, raw, child, reference, differences, multishot):
    amount = float(raw.get('Amount') or 0)
    damage = reference.get('damage') or {}
    if len(damage) != 1 or not close(amount, sum(float(v) for v in damage.values())):
        raise ValueError(f'{name}: native {amount:g} differs from reference {damage}')
    element = next(iter(damage))
    if raw.get('Type') is not None and DT.get(element) != raw['Type']:
        raise ValueError(f'{name}: native type {raw["Type"]} differs from reference {element}')
    crit = (child.get('CriticalChance'), child.get('CriticalMultiplier'))
    if None in crit:
        crit = (reference.get('crit_chance'), reference.get('crit_multiplier'))
        differences.append(f'{name}: crit from reference (native omitted)')
    elif reference.get('crit_chance') is not None and not close(crit[0], reference['crit_chance'], .05):
        differences.append(f"{name}: crit native {crit[0]:.4g}/{crit[1]:.4g} vs reference "
                           f"{reference['crit_chance']}/{reference.get('crit_multiplier')}")
    status = reference.get('status_chance')
    if raw.get('ProcChance') is None:
        differences.append(f'{name}: native status omitted; reference {status} used')
    elif not close(float(raw['ProcChance']) / multishot, status, .15):
        differences.append(f"{name}: status native {raw['ProcChance']} vs reference {status}; reference used")
    return dict(damage={element: amount}, crit_chance=float(crit[0]), crit_multiplier=float(crit[1]), status_chance=float(status),
                takes_multishot=False, nativeField=name, damageTypeSource='native-explicit' if raw.get('Type') else 'reference-confirmed-native-default')


def main():
    import yaml
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages', type=Path, required=True)
    ap.add_argument('--wfsim', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/combat-reference.json')
    ap.add_argument('--evidence', type=Path, required=True)
    a = ap.parse_args()
    if a.evidence.exists():
        ap.error('preserve previous evidence; use a new file')
    pkg = PackageIndex(a.packages, json.loads((a.packages.parent / 'parents.json').read_text(encoding='utf-8-sig')))
    reference = {}
    for file in sorted((a.wfsim / 'data/weapons').rglob('*.yaml')):
        spec = yaml.safe_load(file.read_text(encoding='utf-8'))
        if isinstance(spec, dict) and spec.get('internal_name') and (spec.get('attack') or {}).get('cluster'):
            reference[spec['internal_name']] = (file, spec)
    payload = json.loads(a.output.read_text(encoding='utf-8'))
    audited = payload['auditedAttacks']
    added, skipped = [], []
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        for index, mode in enumerate(row.get('fireModes') or []):
            projectile = (mode.get('damage') or {}).get('projectile')
            native = pkg.resolve(projectile) if projectile else None
            if not native or not native.get('NumClusterProjectiles'):
                continue
            name = row['nameEn']
            try:
                if row['path'] not in reference:
                    raise ValueError('no pinned reference cluster block')
                file, spec = reference[row['path']]
                cluster = spec['attack']['cluster']
                child_path = projectile.rsplit('/', 1)[0] + '/' + native['ClusterProjectiles']
                child = pkg.resolve(child_path)
                if not child:
                    raise ValueError('native child projectile missing')
                count = int(native['NumClusterProjectiles'])
                if count != int(cluster['count']):
                    raise ValueError(f"native count {count} differs from reference {cluster['count']}")
                entry = audited.get(row['path'], {})
                entry = entry.get('modes', {}).get(str(index), {}) if index else entry
                if not (entry.get('radial') or entry.get('radials')):
                    raise ValueError('shell explosion not audited')
                differences = []
                multishot = float(mode.get('multishot') or 1)
                direct = part('AttackData', child.get('AttackData') or {}, child,
                              dict(cluster, damage=cluster['damage']), differences, multishot)
                radial = part('ExplosiveAttack', child.get('ExplosiveAttack') or {}, child, cluster['radial'], differences, multishot)
                co_row = next((u.get('row') for u in spec.get('unmodeled') or () if isinstance(u, dict)
                            and u.get('reason') == 'cluster_bomblet_co'), None)
                if co_row:
                    cells = [c.strip() for c in co_row.split('|')]
                    unmodded, actual, rule = float(cells[3]), float(cells[4]), cells[6].split()[0].lower()
                    if not close(unmodded, sum(direct['damage'].values())):
                        raise ValueError(f'CO catalog row {unmodded:g} differs from the bomblet hit')
                    if rule != 'adding':
                        raise ValueError(f'CO catalog rule {cells[6]!r} not supported')
                    direct.update(takes_condition_overload=True, coProfile=dict(
                        behavior='additive_with_base_damage', baseFraction=actual / unmodded, excludeFlatSources=[],
                        source='wiki CO catalog via WFSim unmodelled row', row=co_row))
                else:
                    differences.append('no CO catalog row: bomblets take no Condition Overload')
                radial.update(radius_m=float(child.get('DamageRadius', cluster['radial'].get('radius_m'))),
                              falloff_start_m=float(cluster['radial'].get('falloff_start_m', 0.)),
                              falloff_reduction=float(child.get('ExplosionFallOff', cluster['radial'].get('falloff_reduction', 0.))))
                sources = []
                for path in (projectile, child_path):
                    f = pkg._path_to_file(path)
                    f = f if f.is_file() else f.with_suffix('.txt')
                    if f.is_file():
                        sources.append(dict(path=path, sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
                clusters = [dict(count=count, direct=direct, radial=radial, nativeChild=child_path, nativeSources=sources,
                                 reference=file.relative_to(a.wfsim).as_posix(), referenceSha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                                 **({'referenceDifferences': differences} if differences else {}))]
            except (ValueError, KeyError, TypeError) as e:
                skipped.append(dict(weapon=name, mode=index, reason=str(e)))
                continue
            entry['clusters'] = clusters
            if entry.get('unmodeled'):
                entry['unmodeled'] = [u for u in entry['unmodeled'] if u != 'cluster-submunitions-unmodeled']
                if not entry['unmodeled']:
                    entry.pop('unmodeled')
            added.append(dict(weapon=name, path=row['path'], mode=index, clusters=clusters))
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    a.evidence.parent.mkdir(parents=True, exist_ok=True)
    a.evidence.write_text(json.dumps(dict(added=added, skipped=skipped), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('added', len(added), 'skipped', len(skipped))
    for x in added:
        c = x['clusters'][0]
        print(' ', x['weapon'], c['count'], 'x', c['direct']['damage'], '+', c['radial']['damage'], c.get('referenceDifferences'))
    for x in skipped:
        print('  skip', x)


if __name__ == '__main__':
    main()
