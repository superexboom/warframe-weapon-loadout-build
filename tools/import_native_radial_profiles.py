"""Import four audited projectile lifecycles without refreshing unrelated profiles."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from copy import deepcopy
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import PackageIndex

# Exact exported mode and projectile pair; this is not a generic parent fallback.
SPECS = (
    ('Ogris', 'ogris', 0, '/Lotus/Weapons/ClanTech/Chemical/RocketProjectile', 100., [('ExplosiveAttack', 'blast', 600., 0.)]),
    ('Lenz', 'lenz', 0, '/Lotus/Weapons/Corpus/Bow/Longbow/CrpBowArrow', 50., [('ExplosiveAttack', 'cold', 10., 0.), ('EmbedDeathAttack', 'blast', 660., 1.3)]),
    ('Prisma Lenz', 'prisma_lenz', 0, '/Lotus/Weapons/Corpus/Bow/Longbow/PrismaLenz/PrismaLenzArrow', 56., [('ExplosiveAttack', 'cold', 10., 0.), ('EmbedDeathAttack', 'blast', 740., 1.3)]),
    ('Stahlta', 'stahlta_charged', 1, '/Lotus/Weapons/Corpus/LongGuns/CrpRubanRifle/CrpRubanRifleProj', 600., [('EmbedDeathAttack', 'radiation', 1200., .36000001)]),
)
DT = {'blast': 'DT_EXPLOSION', 'cold': 'DT_FREEZE', 'radiation': 'DT_RADIATION'}


def import_profiles(packages: Path, reference: Path, exported: dict, payload: dict):
    import yaml
    pkg = PackageIndex(packages, json.loads((packages.parent / 'parents.json').read_text(encoding='utf-8-sig')))
    commit = subprocess.check_output(['git', '-C', str(reference), 'rev-parse', 'HEAD'], text=True).strip()
    records = {w['nameEn']: w for w in exported['data']}
    changes = []
    for name, key, mode_index, projectile, direct, parts in SPECS:
        row = records[name]; mode = row['fireModes'][mode_index]
        if mode['damage'].get('projectile') != projectile or abs(sum(mode['damage']['types'].values()) - direct) > .02:
            raise ValueError('exported mode identity changed: ' + name)
        src = reference / 'data/weapons/primary' / (key + '.yaml')
        spec = yaml.safe_load(src.read_text(encoding='utf-8')); attack = spec['attack']
        native = pkg.resolve(projectile)
        if abs(float(native['AttackData']['Amount']) - direct) > .02:
            raise ValueError('native direct attack changed: ' + name)
        embedded = any(field == 'EmbedDeathAttack' for field, *_ in parts)
        if embedded and native.get('Embed') != 1 or not embedded and native.get('Embed'):
            raise ValueError('native lifecycle changed: ' + name)
        radials = []
        for field, element, amount, delay in parts:
            raw = native[field]
            if abs(float(raw.get('Amount', 0)) - amount) > .0001 or raw.get('Type') not in (None, DT[element]):
                raise ValueError('native radial attack changed: ' + name)
            # Missing Type is an omitted native default. Only accept Blast when
            # the independent reference explicitly gives the identical amount.
            if raw.get('Type') is None and attack['radial']['damage'] != {element: amount}:
                raise ValueError('unverified omitted radial type: ' + name)
            if field == 'EmbedDeathAttack' and any(abs(float(t) - delay) > 1e-6 for t in native.get('EmbedTime', [])):
                raise ValueError('native embed delay changed: ' + name)
            if field == 'EmbedDeathAttack' and len(native.get('EmbedTime', [])) != 2:
                raise ValueError('native embed delay absent: ' + name)
            radials.append(dict(damage={element: amount}, radius_m=native['DamageRadius'],
                falloff_start_m=0., falloff_reduction=native['ExplosionFallOff'],
                crit_chance=native['CriticalChance'], crit_multiplier=native['CriticalMultiplier'],
                status_chance=raw.get('ProcChance', 0.) / float(mode.get('multishot') or 1),
                forced_procs=['cold'] if 'PT_CHILLED' in raw.get('ForcedProcs', []) else [],
                takes_multishot=True, takes_blast_radius_mods=True, impact_delay_seconds=delay,
                nativeSource=projectile, nativeField=field,
                damageTypeSource='native-explicit' if raw.get('Type') else 'reference-confirmed-native-default',
                multishotSource='one radial event per spawned projectile',
                referenceTakesMultishot=attack['radial'].get('takes_multishot', True)))
        source_paths = [row['path'], projectile]
        ancestor = pkg.parents.get(projectile)
        while ancestor and ancestor not in source_paths:
            source_paths.append(ancestor); ancestor = pkg.parents.get(ancestor)
        sources = []
        for path in source_paths:
            f = pkg._path_to_file(path)
            if not f.is_file(): f = f.with_suffix('.txt')
            if f.is_file(): sources.append(dict(path=path, sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        entry = dict(name=name, source=src.relative_to(reference).as_posix(),
            sourceCommit=commit, sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
            directTotal=direct, fireMode=mode_index, projectile=projectile,
            scope='direct-hit target at explosion centre; native ordered radial events',
            radials=radials, packageBuild=packages.parent.name, nativeSources=sources,
            compression={**attack['compression'], 'radius':native['DamageRadius'], 'takesRadiusMods':True})
        behavior = pkg.resolve(row['path'])['Behaviors'][mode_index]
        states = [v for k,v in behavior.items() if k.startswith('state:') and isinstance(v,dict)]
        if len(states) != 1 or states[0].get('ChargeModifier') != 'WEAPON_FIRE_RATE':
            raise ValueError('native charge modifier changed: ' + name)
        charge = float(states[0]['ChargeTime'])
        expected_charge = {'Ogris': .3, 'Lenz': 1.2, 'Prisma Lenz': .8, 'Stahlta': 1.6}[name]
        if abs(charge - expected_charge) > 1e-6:
            raise ValueError('native charge duration changed: ' + name)
        entry['chargeEvidence'] = dict(nativeSeconds=charge, referenceSeconds=attack['charge_seconds'],
            nativeSource=row['path'], nativeField=f'Behaviors[{mode_index}].state.ChargeTime')
        if abs(charge - attack['charge_seconds']) > 1e-6:
            entry['referenceDifferences'] = ['native-charge-duration-differs-from-reference']
        if spec.get('class') == 'bow':
            entry.update(bow=True, drawSeconds=charge)
        else:
            entry['charge'] = dict(seconds=charge, cadence='draw-then-rate', modifier='WEAPON_FIRE_RATE',
                nativeSource=row['path'], nativeField=f'Behaviors[{mode_index}].state.ChargeTime',
                cadenceSource='reference engine/src/fight/melee.rs seconds_to_next_shot')
        before = deepcopy(payload['auditedAttacks'].get(row['path']))
        if mode_index:
            payload['auditedAttacks'].setdefault(row['path'], {}).setdefault('modes', {})[str(mode_index)] = entry
        else: payload['auditedAttacks'][row['path']] = entry
        changes.append(dict(name=name, mode=mode_index, before=before, after=entry))
    return changes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages', type=Path, required=True)
    ap.add_argument('--wfsim', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT/'data/mechanics/combat-reference.json')
    ap.add_argument('--evidence', type=Path, required=True)
    a = ap.parse_args()
    if a.evidence.exists(): ap.error('preserve previous evidence; use a new file')
    payload = json.loads(a.output.read_text(encoding='utf-8'))
    changes = import_profiles(a.packages, a.wfsim, json.loads(a.export.read_text(encoding='utf-8')), payload)
    a.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    a.evidence.parent.mkdir(parents=True,exist_ok=True)
    a.evidence.write_text(json.dumps(changes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('audited projectile modes:',len(changes))

if __name__ == '__main__': main()
