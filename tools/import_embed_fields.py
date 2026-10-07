"""Import embedded damage fields (Pox, Coda Pox, Mutalist Cernos clouds).

A native projectile with Embed = 1 and an ``EmbedAttack`` that has an Amount
keeps damaging around where it stuck for ``EmbedTime`` seconds (radius
``EmbedDamageRadius``, falloff ``EmbedFallOff``). It is replayed as the
existing ``lingering`` field (as Torid's audited cloud).

Three sources must agree, otherwise the weapon is skipped with a reason: the
export mode (projectile identity, direct total), the native EmbedAttack
(amount and type) and the pinned WFSim ``attack.lingering`` block (damage).
The native record carries no tick interval, so ``tick_rate`` and the status
chance come from the reference (as the explosion importers do); amount, type,
duration, radius, falloff and forced procs are native. Differences are kept.
Existing audited entries keep their keys; only ``lingering`` is added.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT / 'tools'))
from wfarsenal.packages import PackageIndex
from import_projectile_components import DT, close


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
    exported = {w['path']: w for w in json.loads(a.export.read_text(encoding='utf-8'))['data']}
    payload = json.loads(a.output.read_text(encoding='utf-8'))
    audited = payload['auditedAttacks']
    added, skipped = [], []
    for file in sorted((a.wfsim / 'data/weapons').rglob('*.yaml')):
        spec = yaml.safe_load(file.read_text(encoding='utf-8'))
        attack = (spec or {}).get('attack') or {} if isinstance(spec, dict) else {}
        field = attack.get('lingering')
        if not isinstance(field, dict) or not spec.get('internal_name'):
            continue
        try:
            row = exported.get(spec['internal_name'])
            if not row:
                raise ValueError('no export record')
            direct = sum(float(v) for v in (attack.get('damage') or {}).values())
            modes = [i for i, m in enumerate(row.get('fireModes') or [])
                     if close(sum((m.get('damage') or {}).get('types', {}).values()) or -1, direct)]
            if len(modes) != 1:
                raise ValueError(f'{len(modes)} export modes match the direct total {direct:g}')
            index = modes[0]
            current = audited.get(row['path'], {})
            current = current.get('modes', {}).get(str(index), {}) if index else current
            if current.get('lingering'):
                continue
            projectile = (row['fireModes'][index].get('damage') or {}).get('projectile')
            native = pkg.resolve(projectile) if projectile else None
            raw = (native or {}).get('EmbedAttack') or {}
            if not native or not native.get('Embed') or not float(raw.get('Amount') or 0):
                raise ValueError('native projectile has no damaging EmbedAttack')
            reference = field.get('damage') or {}
            if len(reference) != 1 or DT.get(next(iter(reference))) != raw.get('Type') \
                    or not close(float(raw['Amount']), sum(float(v) for v in reference.values())):
                raise ValueError(f"native EmbedAttack {raw.get('Amount')} {raw.get('Type')} differs from reference {reference}")
            times = [float(t) for t in native.get('EmbedTime') or []]
            if not times:
                raise ValueError('native EmbedTime absent')
            duration = (min(times) + max(times)) / 2
            differences = []
            if not close(duration, float(field.get('duration_seconds', duration))):
                differences.append(f"duration native {duration:g}s vs reference {field.get('duration_seconds')}s; native used")
            status = float(field.get('status_chance', raw.get('ProcChance') or 0.))
            if raw.get('ProcChance') is not None and not close(float(raw['ProcChance']), status, .05):
                differences.append(f"status native {raw['ProcChance']} vs reference {status}; reference used")
            crit = (native.get('CriticalChance'), native.get('CriticalMultiplier'))
            if None in crit:
                crit = (field.get('crit_chance', attack.get('crit_chance')), field.get('crit_multiplier', attack.get('crit_multiplier')))
            component = dict(damage={next(iter(reference)): float(raw['Amount'])}, tick_rate=float(field['tick_rate']),
                             duration_seconds=duration, radius_m=float(native.get('EmbedDamageRadius', field.get('radius_m', 0.))),
                             falloff_start_m=0., falloff_reduction=float(native.get('EmbedFallOff', field.get('falloff_reduction', 0.))),
                             crit_chance=float(crit[0]), crit_multiplier=float(crit[1]), status_chance=status,
                             forcedProcs=list(raw.get('ForcedProcs') or []), stacking=field.get('stacking', 'stack'),
                             takes_condition_overload=bool(field.get('takes_condition_overload', False)),
                             nativeSource=projectile, nativeField='EmbedAttack', tickRateSource='reference (native has no interval)')
            sources = []
            for path in (row['path'], projectile):
                f = pkg._path_to_file(path)
                f = f if f.is_file() else f.with_suffix('.txt')
                if f.is_file():
                    sources.append(dict(path=path, sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
            entry = dict(lingering=component, lingeringSource=dict(reference=file.relative_to(a.wfsim).as_posix(),
                         referenceSha256=hashlib.sha256(file.read_bytes()).hexdigest(), nativeSources=sources,
                         generatedBy='tools/import_embed_fields.py', **({'referenceDifferences': differences} if differences else {})))
        except (ValueError, KeyError, TypeError) as e:
            skipped.append(dict(weapon=spec['id'], reason=str(e)))
            continue
        target = audited.setdefault(row['path'], {})
        if index:
            target = target.setdefault('modes', {}).setdefault(str(index), {})
        target.update(entry)
        target.setdefault('name', row['nameEn'])
        target.setdefault('directTotal', round(direct, 6))
        target.setdefault('projectile', projectile)
        added.append(dict(weapon=spec['id'], path=row['path'], mode=index, entry=entry))
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    a.evidence.parent.mkdir(parents=True, exist_ok=True)
    a.evidence.write_text(json.dumps(dict(added=added, skipped=skipped), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('added', len(added), 'skipped', len(skipped))
    for x in added:
        c = x['entry']['lingering']
        print(' ', x['weapon'], x['mode'], c['damage'], f"{c['duration_seconds']:g}s @ {c['tick_rate']:g}/s r{c['radius_m']:g}",
              x['entry']['lingeringSource'].get('referenceDifferences'))
    for x in skipped:
        print('  skip', x)


if __name__ == '__main__':
    main()
