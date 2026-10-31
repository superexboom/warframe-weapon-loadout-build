"""Import explosion components for every weapon WFSim models with a radial.

Each candidate needs three agreeing sources, otherwise it is skipped with a
reason (fail closed):
- the export weapon (internal path) and the fire mode whose direct total
  matches the reference attack;
- the native projectile record: an ExplosiveAttack/EmbedDeathAttack whose
  Amount equals the reference radial total, its Type (or an omitted native
  default the reference spells out), radius, falloff, crit and embed delay;
- the pinned WFSim YAML radial block (status chance and unresolved fields).
Native projectile-owned attacks repeat per spawned projectile, even when a
reference row says takes_multishot=false. Hitscan impact exceptions keep their
separate MultiShotBuffsRadialDamage contract.
Already audited attacks are never overwritten.

2026-10-07: a native attack with UseNewFormat = 1 spells each type as its own
DT_* amount (Kuva Tonkor 168 puncture / 204 slash / 302 blast), which must
equal the reference split; alt-fire forms (``inherits`` a base spec, e.g.
bubonico_burst) resolve the parent's internal path; several export modes
with the same direct total are told apart by IsAlternateFire, trigger and
whether the mode's projectile carries an explosion component (Kuva Zarr).
A hitscan mode has no projectile: its explosion is the weapon behaviour's
``impact:RadialOnMissImpactBehavior.RadialDamage`` (baseAmount split by
DamagePercent, its own crit / status / radius / fallOff; Trumna, Ferrox).
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import PackageIndex

DT = {'blast': 'DT_EXPLOSION', 'cold': 'DT_FREEZE', 'radiation': 'DT_RADIATION', 'heat': 'DT_FIRE',
      'toxin': 'DT_POISON', 'electricity': 'DT_ELECTRICITY', 'gas': 'DT_GAS', 'viral': 'DT_VIRAL',
      'corrosive': 'DT_CORROSIVE', 'magnetic': 'DT_MAGNETIC', 'impact': 'DT_IMPACT',
      'puncture': 'DT_PUNCTURE', 'slash': 'DT_SLASH', 'void': 'DT_VOID'}
FORCED = {'PT_CHILLED': 'cold', 'PT_ELECTROCUTION': 'electricity'}
FIELDS = ('ExplosiveAttack', 'EmbedDeathAttack', 'RadialDamage')


def apply_native_contract(component):
    """Keep reimports aligned with independently audited exact-source consumers."""
    from wfarsenal.delayed_radial_events import producer,producers
    row=producer(component)
    if row is None and not component.get('nativeRoute'):
        candidates=[r for r in producers().get(component.get('nativeSource'),()) if r['nativeField']==component.get('nativeField')]
        if len(candidates)==1:row=candidates[0]
    if row and row.get('nativeField')==component.get('nativeField'):
        component.update(row.get('componentOverrides') or {})
    return component



_ALTERNOX = {
    '/Lotus/Weapons/Tenno/LongGuns/GyreRifle/GyreRifleWeapon':
        ('/Lotus/Weapons/Tenno/LongGuns/GyreRifle/GyreRifleBoltoAltProj',50.),
    '/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWeapon':
        ('/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxBoltoAltProj',70.),
}


def alternox_profile(pkg, row):
    """Exact ordinary RemoteMine same-emission batch, not a max1 pellet clamp."""
    path=row['path'];projectile,amount=_ALTERNOX[path]
    mode=row['fireModes'][1];native=pkg.resolve(path);p=pkg.resolve(projectile)
    selected=native['Behaviors'][1]
    fire=selected['fire:LotusWeaponProjectileFireBehavior']
    state=selected['state:RemoteMineStateBehavior']
    if (mode['damage'].get('projectile')!=projectile or
            abs(sum(mode['damage']['types'].values())-amount)>.001 or
            pkg.locate(path,fire['projectileType'])!=projectile or
            fire['fireIterations']!=1 or fire['IgnoreFireIterations']!=0 or
            any(state.get(k)!=v for k,v in dict(TrackProjectiles=1,MaxNumProjectiles=1,
                DetonateManually=1,FireDetonatesActiveProjectiles=1,AutoDetonateCapacity=0,
                DestroyDelay=.050000001).items())):
        raise ValueError('Alternox native RemoteMine batch source changed')
    if (p['AttackData']['Amount']!=amount or p['EmbedAttack']['Amount']!=amount or
            p['EmbedDeathAttack']['Amount']!=2*amount or
            p['EmbedAttack']['Type']!='DT_ELECTRICITY' or
            p['EmbedDeathAttack']['Type']!='DT_ELECTRICITY' or
            p.get('DealDamageThroughImpactBehavior')!=1 or p.get('EmbedTime')!=[10,10] or
            p.get('EmbedDamageRadius')!=6):
        raise ValueError('Alternox attached/terminal source changed')
    common=dict(takes_multishot=True,crit_chance=float(p['CriticalChance']),
        crit_multiplier=float(p['CriticalMultiplier']),nativeSource=projectile)
    embedded=dict(**common,damage={'electricity':amount},nativeField='EmbedAttack',
        nativeRoute='attached-target',native_event_delay_seconds=0.,
        status_chance=float(p['EmbedAttack']['ProcChance']),forcedProcs=[],
        tick_rate=1.,duration_seconds=10.,radius_m=6.,takes_condition_overload=True,
        coProfile=dict(behavior='additive',baseFraction=1.,excludeFlatSources=[],
            source='native818 source-mode raw50/70;141300a00 ->14113e250'),
        takes_victim_stack_damage=True,takes_victim_crit=False,liveVictimCO=True)
    terminal=dict(**common,damage={'electricity':2*amount},nativeField='EmbedDeathAttack',
        nativeRoute='embedded-expiry-explicit-host',native_event_delay_seconds=.1125,
        impact_delay_seconds=10.1125,status_chance=float(p['EmbedDeathAttack']['ProcChance']),
        forcedProcs=list(p['EmbedDeathAttack'].get('ForcedProcs') or []),
        radius_m=float(p['DamageRadius']),falloff_start_m=0.,
        falloff_reduction=float(p['ExplosionFallOff']),takes_blast_radius_mods=True,
        takes_condition_overload=False,takes_victim_stack_damage=False,takes_victim_crit=True,
        liveSourceDamageAtImpact=True)
    return dict(name=row['nameEn'],directTotal=sum(mode['damage']['types'].values()),fireMode=1,
        projectile=projectile,embedded=embedded,radials=[terminal],
        manualDetonation=dict(maxProjectiles=1,impactThenEmbed=True,fullEmissionBatch=True,
            destroyIntervalSeconds=float(state['DestroyDelay']),terminalDelaySeconds=.1125,
            naturalExpiryIncludesCoincidentTick=True),
        scope='same-emission MS batch on original recipient; each manual request cancels its own ticks; actual terminal damage follows mean native Die delay',
        unmodeled=['alternox-original-recipient-retirement-and-spatial-coverage-policy',
            'alternox-native-frame-boundary-approximated-by-ideal-phase',
            'alternox-terminal-random-delay-approximated-by-mean',
            'alternox-fractional-multishot-expected-packet-weight-policy'],
        nativeEvidence=dict(clientSha256='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d',
            packagesBinSha256='00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06',
            source='docs/projectile-qualification-20261030/FIELD-LIFECYCLES.md',
            registration='actual RemoteMine1423a3960+328140bad3b0 ->141561250 per physical emission;AutoDetonateCapacity168=0',
            cap='state168140592870 gates later requested0/1, no within-shot clamp',
            manual='3181406d76f0 ->140d87360 ->1412d2510 one request;update140bef530 interval194',
            terminal='418140414330 ->1402e1be0 cancels queued ticks ->14050b8c0 deferred Die[.075,.15)',
            attached='790 da8=1 ->818 ->141300a00 reads packet1bb mode1, rawtemplate50/70; no ordinary source multiplier in callerBase'))

def close(a, b, rel=.01):
    return abs(float(a) - float(b)) <= rel * max(abs(float(a)), abs(float(b)), 1e-9)


def candidates(reference: Path):
    import yaml
    specs = {}
    for file in sorted((reference / 'data/weapons').rglob('*.yaml')):
        spec = yaml.safe_load(file.read_text(encoding='utf-8'))
        if isinstance(spec, dict) and spec.get('id'):
            specs[spec['id']] = (file, spec)
    for file, spec in specs.values():
        if not spec.get('internal_name') and spec.get('form') in ('alt_fire', 'incarnon', 'charged', 'uncharged'):
            parent_id = spec.get('inherits') or spec.get('transforms_from')
            parent = specs.get(parent_id, (None, {}))[1]
            if parent.get('internal_name'):
                spec = {**spec, 'internal_name': parent['internal_name']}
        if not spec.get('internal_name'):
            continue
        attack = spec.get('attack') or {}
        radial = attack.get('radial')
        if isinstance(radial, dict) and isinstance(radial.get('damage'), dict) and radial['damage']:
            yield file, spec, attack, radial


def exported_behaviours(native, row):
    """Use the exact behaviour bank the weapon exporter selected.

    Archguns expose space and ground behaviours in parallel. Mixing a Heavy
    direct hit with a space explosion silently loses one third of its payload.
    Explicit provenance wins; legacy archgun rows choose Heavy when present.
    An explicit missing bank is an import failure, never a fallback to another
    loadout that merely happens to have a radial attack.
    """
    source = row.get('fireModeSource')
    if source is None:
        source = ('HeavyBehaviors' if row.get('slot') == 'arch_gun'
                  and isinstance(native.get('HeavyBehaviors'), list) and native['HeavyBehaviors']
                  else 'Behaviors')
    if source not in ('Behaviors', 'HeavyBehaviors'):
        return []
    selected = native.get(source)
    return selected if isinstance(selected, list) else []


def hitscan_radial(pkg, row, mode):
    """The selected mode's RadialDamage, shaped like a projectile record."""
    weapon = pkg.resolve(row['path']) or {}
    behaviours = exported_behaviours(weapon, row)
    position = mode.get('index')
    if isinstance(position, bool) or not isinstance(position, int) or position < 0 or position >= len(behaviours) or not isinstance(behaviours[position], dict):
        return None
    impact = next((v for k, v in behaviours[position].items() if k.startswith('impact:') and 'RadialOnMiss' in k
                   and isinstance(v, dict)), None)
    radial = (impact or {}).get('RadialDamage') or {}
    amount = float(radial.get('baseAmount') or 0)
    if amount <= 0:
        return None
    attack = {k: amount * float(v) for k, v in (radial.get('DamagePercent') or {}).items() if float(v or 0)}
    attack.update(Amount=amount, UseNewFormat=1, ProcChance=radial.get('baseProcChance'))
    return {'RadialDamage': attack, 'CriticalChance': radial.get('criticalChance'),
            'CriticalMultiplier': radial.get('criticalMultiplier'), 'DamageRadius': radial.get('radius'),
            'ExplosionFallOff': radial.get('fallOff')}


def remote_mine(pkg, row, mode):
    weapon = pkg.resolve(row['path']) or {}
    behaviours = exported_behaviours(weapon, row)
    position = mode.get('index')
    if isinstance(position, bool) or not isinstance(position, int) or position < 0 or position >= len(behaviours) or not isinstance(behaviours[position], dict):
        return None
    state = behaviours[position].get('state:RemoteMineStateBehavior')
    return state if isinstance(state, dict) and state.get('DetonateManually') else None


def build_entry(file, spec, attack, radial, row, mode_index, pkg, reference):
    mode = row['fireModes'][mode_index]
    projectile = (mode.get('damage') or {}).get('projectile')
    if projectile:
        native = pkg.resolve(projectile)
        if not native:
            raise ValueError('native projectile missing')
    else:
        native = hitscan_radial(pkg, row, mode)
        if not native:
            raise ValueError('export mode has no projectile identity and no hitscan RadialDamage')
    native_path = projectile or row['path']
    # The replay copies the mode into its radial part, so a charged mode's
    # chargeDamageMultiplier scales the native explosion too (Opticor 200 x 2
    # = the reference 400); compare and store the unscaled native amounts.
    scale = float(mode.get('chargeDamageMultiplier') or 1)
    reference_damage = {k: float(v) / scale for k, v in radial['damage'].items()}
    total = sum(reference_damage.values())
    matches = [f for f in FIELDS if isinstance(native.get(f), dict) and close(native[f].get('Amount', 0), total)]
    mine = remote_mine(pkg, row, mode)
    if mine and 'EmbedDeathAttack' in matches:
        # A remote mine sticks and is detonated: its embedded death attack
        # is the blast (Talons' audited 250); never both equal fields.
        matches = ['EmbedDeathAttack']
    if len(matches) != 1:
        raise ValueError(f'native radial amount does not uniquely match reference {total:g}')
    field = matches[0]
    raw = native[field]
    elements = list(radial['damage'])
    damage = None
    typed = {k: float(v) for k, v in raw.items() if k.startswith('DT_') and float(v or 0)} if raw.get('UseNewFormat') else {}
    if typed:
        reference_typed = {DT.get(k): v for k, v in reference_damage.items()}
        if set(typed) != set(reference_typed) or any(not close(typed[k], reference_typed[k]) for k in typed):
            raise ValueError('native per-type radial amounts differ from reference')
        damage = {k: typed[DT[k]] for k in radial['damage']}
        type_source = 'native-per-type'
    elif raw.get('Type') == 'DT_PHYSICAL' and elements and set(elements) <= {'impact', 'puncture', 'slash'}:
        # Native "physical" is an Impact/Puncture/Slash split the record does
        # not spell out; take the reference split at the native amount.
        amount = float(raw.get('Amount'))
        damage = {k: v * amount / total for k, v in reference_damage.items()}
        type_source = 'native-physical-reference-split'
    elif raw.get('Type') is not None:
        if len(elements) != 1 or DT.get(elements[0]) != raw['Type']:
            raise ValueError('native radial type differs from reference')
        type_source = 'native-explicit'
    elif len(elements) == 1:
        type_source = 'reference-confirmed-native-default'
    else:
        raise ValueError('native type omitted and reference is mixed')
    delay = 0.
    differences = []
    if field == 'EmbedDeathAttack':
        times = [float(t) for t in native.get('EmbedTime') or []]
        if not times:
            raise ValueError('native embed delay absent')
        delay = (min(times) + max(times)) / 2
        if max(times) - min(times) > 1e-6:
            differences.append(f'embed delay range {min(times):g}-{max(times):g}s; expected midpoint used')
    multishot = float(mode.get('multishot') or 1)
    native_status = float(raw.get('ProcChance', 0.)) / multishot
    status = float(radial.get('status_chance', native_status))
    if not close(native_status, status, .15):
        differences.append(f'status-chance native {native_status:.4g} vs reference {status:.4g}; reference used')
    crit = (native.get('CriticalChance'), native.get('CriticalMultiplier'))
    if None in crit:
        crit = (radial.get('crit_chance'), radial.get('crit_multiplier'))
        if None in crit:
            raise ValueError('radial crit unavailable')
        differences.append('crit from reference (native omitted)')
    elif radial.get('crit_chance') is not None and not close(crit[0], radial['crit_chance'], .05):
        differences.append(f"crit chance native {crit[0]} vs reference {radial['crit_chance']}")
    radius = native.get('DamageRadius', radial.get('radius_m'))
    falloff = native.get('ExplosionFallOff', radial.get('falloff_reduction', 0.))
    forced = sorted({FORCED[p] for p in raw.get('ForcedProcs') or [] if p in FORCED})
    component = dict(
        damage=damage or ({elements[0]: float(raw.get('Amount'))} if len(elements) == 1 else dict(reference_damage)),
        radius_m=radius, falloff_start_m=float(radial.get('falloff_start_m', 0.)), falloff_reduction=falloff,
        crit_chance=float(crit[0]), crit_multiplier=float(crit[1]), status_chance=status,
        forced_procs=forced, takes_multishot=(True if field in ('ExplosiveAttack','EmbedDeathAttack') else bool(radial.get('takes_multishot', True))),
        takes_blast_radius_mods=bool(radial.get('takes_blast_radius_mods', True)),
        impact_delay_seconds=delay, nativeSource=native_path, nativeField=field,
        damageTypeSource=type_source, multishotSource=('one native attack per spawned projectile' if field in ('ExplosiveAttack','EmbedDeathAttack') else 'native hitscan impact contract'),
        referenceTakesMultishot=radial.get('takes_multishot', True))
    apply_native_contract(component)
    sources = []
    for path in dict.fromkeys((row['path'], native_path)):
        f = pkg._path_to_file(path)
        if not f.is_file():
            f = f.with_suffix('.txt')
        if f.is_file():
            sources.append(dict(path=path, sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
    entry = dict(name=row['nameEn'], source=file.relative_to(reference).as_posix(),
                 sha256=hashlib.sha256(file.read_bytes()).hexdigest(),
                 directTotal=round(sum((mode['damage'].get('types') or {}).values()), 6), fireMode=mode_index,
                 projectile=projectile, scope='direct-hit target at explosion centre; native radial event',
                 radials=[component], nativeSources=sources, generatedBy='tools/import_projectile_components.py')
    if mode.get('isIncarnonForm') or spec.get('form') == 'incarnon':
        entry['allowIncarnon'] = True
    if mine:
        entry['manualDetonation'] = dict(maxProjectiles=int(mine.get('MaxNumProjectiles') or 1))
        entry['scope'] = 'single-target embedded remote mines; explicit throw batches and manual detonation delay'
    if differences:
        entry['referenceDifferences'] = differences
    if row['path'] in _ALTERNOX and mode_index==1:
        entry.update(alternox_profile(pkg,row))
    return entry


def main():
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
    for file, spec, attack, radial in candidates(a.wfsim):
        row = exported.get(spec['internal_name'])
        if not row:
            continue
        direct = sum(float(v) for v in (attack.get('damage') or {}).values())
        # A charged mode's direct hit is the export total x chargeDamageMultiplier (Opticor 500 x 2).
        modes = [i for i, m in enumerate(row.get('fireModes') or [])
                 if close((sum((m.get('damage') or {}).get('types', {}).values()) or -1) * float(m.get('chargeDamageMultiplier') or 1), direct)]
        if len(modes) > 1:
            alternate = spec.get('form') == 'alt_fire'
            narrowed = [i for i in modes if bool(row['fireModes'][i].get('isAlternateFire')) == alternate]
            trigger = str(attack.get('trigger') or '').replace('_', '').lower()
            if len(narrowed) > 1 and trigger:
                narrowed = [i for i in narrowed if str(row['fireModes'][i].get('trigger') or '').lower().endswith('trigger' + trigger)]
            modes = narrowed or modes
        if len(modes) > 1:
            modes = [i for i in modes if (row['fireModes'][i].get('damage') or {}).get('components')] or modes
        if len(modes) != 1:
            skipped.append(dict(weapon=spec['id'], reason=f'{len(modes)} export modes match the direct total {direct:g}'))
            continue
        index = modes[0]
        current = audited.get(row['path'], {})
        existing = current.get('modes', {}).get(str(index)) if index else current
        if existing and (existing.get('radials') or existing.get('radial') or existing.get('pureRadial') or existing.get('lingering')):
            continue
        try:
            entry = build_entry(file, spec, attack, radial, row, index, pkg, a.wfsim)
        except (ValueError, KeyError, TypeError) as e:
            skipped.append(dict(weapon=spec['id'], reason=str(e)))
            continue
        if index:
            audited.setdefault(row['path'], {}).setdefault('modes', {})[str(index)] = {**(existing or {}), **entry}
        else:
            audited[row['path']] = {**(existing or {}), **entry}
        added.append(dict(weapon=spec['id'], path=row['path'], mode=index, entry=entry))
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    a.evidence.parent.mkdir(parents=True, exist_ok=True)
    a.evidence.write_text(json.dumps(dict(added=added, skipped=skipped), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('added', len(added), 'skipped', len(skipped))


if __name__ == '__main__':
    main()
