"""Import Battacor's per-ray native alt radial and selectable kill-charge cycle.

The preserved EXE proves positive-charge availability, consume-all snapshot
scaling for 1/2/3 charges and one radial per accepted ray collision. The default
policy spends its first charge immediately; configured banking selects 2/3.
Sentient Barrage remains unsupported. No WFSim data enters this importer.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor')]
from wfarsenal.packages import PackageIndex
from tools.import_projectile_components import exported_behaviours, hitscan_radial, apply_native_contract

WEAPON = '/Lotus/Weapons/Corpus/LongGuns/CrpSentExperimentRifle/CrpSentExperimentRifle'
CLIENT_SHA = 'eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'
PACKAGE_SHA = '00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06'
SOURCES = [
    (WEAPON, 'a53933a6ad5b6062bd41d9df1a41dea522472f2d506110c2654d764ab9d016b1'),
    ('/Lotus/Weapons/Tenno/Rifle/LotusAssaultRifle', '6cef9d6a035df8cfb6eac8167a0ed7549ef5cca84b704fe31159ae0f927053e5'),
    ('/Lotus/Weapons/Tenno/Rifle/LotusRifle', '14e1c1245d79a8d0cd9a9f5dc201c8f2532bd5d348e4664346b5cff2059640c4'),
    ('/Lotus/Weapons/Tenno/LotusLongGun', '2f8b75d2003df2a86e5376d9a417a3c7741f79fa8dc68d6fe989b8bb244e9cdc'),
    ('/Lotus/Weapons/Tenno/LotusBulletWeapon', 'dbf1c582b143471cf05fef13fc0dd775f3bf29c583a126747db3b966238087f9'),
]
UNMODELED = []
TIMING_UNMODELED = []
SNAPSHOT_PROOF = dict(
    countSnapshot='0x141377160 -> 0x140164110 stores pre-consumption current count as float in active state +0xac; current clears afterward',
    cachedChargeMultiplier='0x140584f1b..0x140584f30: UseClipSizeAsDamageMultiplier=false gives 1+(DamageMultiplier[+0x170]-1)*releaseRatio; raw DamageMultiplier=1 yields 1 at every ratio',
    stateMultiplier='0x1403b99c0: cached state +0x184 times 0x14176c6d0 max(snapshot +0xac,1) while ApplyNumChargesToDamageMultiplier +0xb1 is enabled',
    weaponStateQuery='0x1412d9b00 selects active mode bank +0x58 then state virtual +0x268',
    radialSnapshotConsumer='0x140e921c7..0x140e92204 queries weapon virtual +0x4a0 and +0x4a8',
    directSnapshotConsumer='0x1415ecd9d..0x1415ecdc7 queries identical weapon virtual +0x4a0 and +0x4a8',
    oneChargeDamageFactor=1.0, twoChargeDamageFactor=2.0, threeChargeDamageFactor=3.0,
    zeroChargeGetterMinimumIsPermission=False)


def raw_sha(pkg, path):
    file = pkg._path_to_file(path)
    if not file.is_file():
        file = file.with_suffix('.txt')
    return hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None


def verified_sources(pkg, native_image):
    if native_image is None or not Path(native_image).is_file():
        raise ValueError('matching native EXE required')
    if hashlib.sha256(Path(native_image).read_bytes()).hexdigest() != CLIENT_SHA:
        raise ValueError('native EXE identity changed')
    if pkg.ancestry(WEAPON) != [path for path, _ in SOURCES]:
        raise ValueError('Battacor raw ancestry changed')
    if any(raw_sha(pkg, path) != sha for path, sha in SOURCES):
        raise ValueError('Battacor raw ancestry identity changed')
    return [dict(path=path, sha256=sha) for path, sha in SOURCES]


def _part(behavior, prefix):
    parts = [value for key, value in behavior.items()
             if key.startswith(prefix) and isinstance(value, dict)]
    if len(parts) != 1:
        raise ValueError('ambiguous native ' + prefix)
    return parts[0]


def profile(pkg, row, *, native_image):
    sources = verified_sources(pkg, native_image)
    modes = row.get('fireModes') or []
    if (row.get('path') != WEAPON or len(modes) != 2
            or modes[1].get('index') != 1 or not modes[1].get('isAlternateFire')
            or modes[1].get('ammoCost') != 0
            or modes[1].get('trigger') != '/Lotus/Language/Menu/Loadout_TriggerCharge'
            or modes[1].get('fireRate') != 5.
            or modes[1].get('multishot') != 1
            or modes[1].get('damage', {}).get('projectile')
            or modes[1].get('damage', {}).get('types') != {'DT_RADIATION': 208.}):
        raise ValueError('Battacor exported alt identity changed')
    native = pkg.resolve(WEAPON)
    behaviors = exported_behaviours(native, row)
    if len(behaviors) != 2:
        raise ValueError('Battacor native behavior bank changed')
    fire = _part(behaviors[1], 'fire:')
    impact = _part(behaviors[1], 'impact:')
    state = _part(behaviors[1], 'state:')
    if (native.get('MaxCharges') != 3 or native.get('NumChargesToConsume') != 0
            or native.get('RequireFullCharges', 0) != 0
            or native.get('AddCharges') != [dict(Conditions=['PRIMARY_KILL'], NumCharges=1)]
            or native.get('ConsumeChargeConditions') != ['SECONDARY_FIRE']
            or fire.get('ConsumesChargesForFire') != 1
            or fire.get('IgnoreFireIterations') != 0
            or fire.get('OnlyHitEnitiesOnce') != 1
            or state.get('ApplyNumChargesToDamageMultiplier') != 1
            or state.get('MinDamageMultiplier') != 1 or state.get('MaxDamageMultiplier') != 3
            or state.get('UseClipSizeAsDamageMultiplier') != 0 or state.get('DamageMultiplier') != 1
            or abs(float(state.get('ChargeTime', -1)) - .40000001) > 1e-8):
        raise ValueError('Battacor minimum-charge contract changed')
    if (impact.get('ApplyRadialDamageOnHit') != 1
            or impact.get('ApplyRadialDamageOnMiss') != 1
            or impact.get('MultiShotBuffsRadialDamage') != 0
            or impact.get('RadialDamageUpgradeType') != 'WEAPON_DAMAGE_AMOUNT'
            or impact.get('OnHitScriptEnabled') != 0):
        raise ValueError('Battacor radial routing or augment state changed')
    raw = hitscan_radial(pkg, row, modes[1])
    radial = impact.get('RadialDamage') or {}
    attack = raw['RadialDamage'] if raw else {}
    if (attack.get('Amount') != 208 or attack.get('DT_RADIATION') != 208
            or sum(v for k, v in attack.items() if k.startswith('DT_')) != 208
            or attack.get('ProcChance') != .5
            or raw.get('CriticalChance') != .2 or raw.get('CriticalMultiplier') != 2
            or radial.get('hitType') != 'DHT_RADIAL'
            or radial.get('radius') != 3.4000001 or radial.get('fallOff') != .40000001
            or radial.get('radiusMin') != 0 or radial.get('procs') or radial.get('deathProcs')):
        raise ValueError('Battacor independent radial payload changed')
    proof = dict(clientSha256=CLIENT_SHA, packageSha256=PACKAGE_SHA,
        descriptorNameOffset=8, radialOnHit='0x14140f7c5: impact +0x1e4',
        radialOnMiss='0x14140f7d3: impact +0x1e3',
        radialBuild='0x14140f948 -> 0x140e91ec0',
        multishotBranch='0x140e92204: impact +0x1e2 false skips multiplication at 0x140e92270; this is per-packet damage, not per-trigger count',
        radialMultiplicity=dict(
            fireIterationCount='0x140f75d20 -> fire virtual +0x118 (0x1416a5ed0) queries weapon +0x6e0; integer multishot 1/2/3 yields native count 1/2/3',
            emit='0x140be1db0: both zero-spread and spread loops submit one 0x14185ca50 trace per iteration; callback thunk 0x1406e6d4c -> fire +0x2a8 -> 0x1409b4480 -> 0x140ee5ca0',
            collect='0x140ee5ca0 initializes an empty callback-local hit list; 0x1409c70a1..0x1409c7278 dedups only within that callback and appends original 0xd0-byte collision records',
            dispatch='0x140581be1 -> weapon +0x650 (0x141550e40) -> mode1 impact +0xb8 (0x140fc83e0) -> 0x14139b3b0 per-record loop -> impact +0xf8 (0x14140f600) -> 0x140e91ec0',
            observedRayCounts=[1,2,3], observedRadialCounts=[1,2,3],
            perPacketDamage=208., perPacketTakesMultishot=False,
            sameVictimAcrossRaysDeduplicated=False,
            missScope='accepted non-avatar scene collisions; empty-space no-collision behavior is outside this proof',
            acceptance='all modelled rays connect; scene collision and aim are supplied inputs, original count/emission/collection/dispatch/impact instructions execute'),
        noFullGateDefault='0x140bf8fb8 initializes RequireFullCharges +0x3238 to zero',
        availability='0x140b169c0 -> 0x1418cee00; current +0x3218 and max +0x3220 must be positive',
        consumeAll='0x141377168 zero consumption takes current; returns consumed count and clears current',
        chargeSnapshot=dict(SNAPSHOT_PROOF))
    entry = dict(name='Battacor', fireMode=1, directTotal=208.,
        scope='one-charge base payload; selectable 1/2/3 primary-kill gate scales direct and radial at consumption; no Sentient Barrage',
        radials=[dict(damage={'radiation':208.}, radius_m=radial['radius'],
            falloff_start_m=radial['radiusMin'], falloff_reduction=radial['fallOff'],
            crit_chance=raw['CriticalChance'], crit_multiplier=raw['CriticalMultiplier'],
            status_chance=attack['ProcChance'], forced_procs=[], takes_multishot=True,
            takes_blast_radius_mods=True, impact_delay_seconds=0.,
            nativeSource=WEAPON, nativeField='RadialDamage',
            damageTypeSource='native-per-type', multishotSource='native one 208-damage radial packet per accepted ray collision; MultiShotBuffsRadialDamage=false prevents a second per-packet multishot factor',
            perPacketTakesMultishot=False,
            takes_condition_overload=True,
            coProfile=dict(behavior='additive_with_base_damage',baseFraction=1.,excludeFlatSources=[]),
            conditionOverloadSource='native ray-hit avatar +818 -> 141300a00 -> 14113e250; source208/radial208; shared charge scale')],
        unmodeled=[*UNMODELED, *TIMING_UNMODELED], nativeSources=sources, source=proof,
        packageBuild='2026.10.22.13.12', generatedBy='tools/import_battacor_radial.py')
    for component in entry['radials']:
        apply_native_contract(component)
    cycle = dict(name='Battacor', sourceModeKillChargeTrue=True, altMode=1, primaryMode=0, killsPerUse=1,
        shotsPerGauge=1, chargeBeforeFire=True, switchInSeconds=float(state.get('ModeSwitchTime') or 0),
        switchOutSeconds=float(_part(behaviors[0], 'state:').get('ModeSwitchTime') or 0),
        policy='spend-first-primary-kill-charge-immediately',
        selectableChargeCounts=[1,2,3], configurationKey='battacorCharges',
        native=dict(AddChargeConditions=['PRIMARY_KILL'], NumChargesToAdd=1,
            NumChargesToConsume=0, MaxCharges=3, RequireFullCharges=0,
            zeroConsumptionMeans='consume-all-current-charges', selectedChargeCount=1),
        nativeSha256=SOURCES[0][1], source=proof,
        generatedBy='tools/import_battacor_radial.py')
    return entry, cycle


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages', type=Path, required=True)
    ap.add_argument('--parents', type=Path, required=True)
    ap.add_argument('--native-image', type=Path, required=True)
    ap.add_argument('--export', type=Path, default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT/'data/mechanics/combat-reference.json')
    ap.add_argument('--cycles', type=Path, default=ROOT/'data/mechanics/kill-charge-profiles.json')
    ap.add_argument('--evidence', type=Path, required=True)
    args = ap.parse_args()
    if args.evidence.exists():
        ap.error('choose a new evidence file')
    pkg = PackageIndex(args.packages, json.loads(args.parents.read_bytes()))
    row = next(w for w in json.loads(args.export.read_bytes())['data'] if w['path'] == WEAPON)
    entry, cycle = profile(pkg, row, native_image=args.native_image)
    # Both files already participate in the app input fingerprint.
    # Preserve unrelated entries and existing line endings while adding both records.
    from tools.refresh_spread_talons import preserve_lines
    original = args.output.read_bytes(); payload = json.loads(original)
    before = payload['auditedAttacks'].get(WEAPON)
    after = {**(before or {}), 'modes':{**(before or {}).get('modes', {}), '1':entry}}
    updated = dict(payload['auditedAttacks']); updated[WEAPON] = after
    payload['auditedAttacks'] = updated
    args.output.write_bytes(preserve_lines(original, (json.dumps(payload, ensure_ascii=False, indent=2)+'\n').encode('utf-8')))
    original = args.cycles.read_bytes(); payload = json.loads(original)
    updated = {**payload['weapons'], WEAPON:cycle}
    payload['weapons'] = updated
    args.cycles.write_bytes(preserve_lines(original, (json.dumps(payload, ensure_ascii=False, indent=2)+'\n').encode('utf-8')))
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(dict(profile=entry, cycle=cycle), indent=2)+'\n', encoding='utf-8')
    print('Imported Battacor native alt radial and first-charge immediate-use cycle')


if __name__ == '__main__':
    main()
