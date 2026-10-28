"""Import ordinary Angstrum rockets from the exact audited Packages/EXE pair.

The profile stores single-projectile base amounts. Replay owns charge projectile
count and per-projectile damage scale; preparation must not bake either into stats.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _sub_behaviour
from tools.import_projectile_components import exported_behaviours
from tools.import_kill_charged_alts import raw_source_sha

BASE = '/Lotus/Weapons/Corpus/Pistols/CrpHandRL/'
WEAPONS = (BASE + 'CorpusHandRocketLauncher', BASE + 'PrismaAngstrum')
PROJECTILES = (BASE + 'CorpusHandRocketProjectile', BASE + 'PrismaAngstrumRocketProjectile')
CLIENT_SHA = 'eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d'
PACKAGE_SHA = '00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06'
CHAINS = {
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketLauncher": [
        "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketLauncher",
        "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistolOther",
        "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistol",
        "/Lotus/Weapons/Tenno/Pistol/LotusPistol"
    ],
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrum": [
        "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrum",
        "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketLauncher",
        "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistolOther",
        "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistol",
        "/Lotus/Weapons/Tenno/Pistol/LotusPistol"
    ],
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketProjectile": [
        "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketProjectile",
        "/Lotus/Types/Weapons/GunProjectile",
        "/EE/Types/Engine/Projectile"
    ],
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrumRocketProjectile": [
        "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrumRocketProjectile",
        "/Lotus/Types/Weapons/GunProjectile",
        "/EE/Types/Engine/Projectile"
    ]
}
RAW_SHA = {
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketLauncher": "416665491c0a882456daf78beb9359006ab4f5246f15eba4b304fe9f354309c6",
    "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistolOther": "73e0eab4999729eda5678d251ed6e3fa02f7671393a952008e018fc81723ab5a",
    "/Lotus/Weapons/Tenno/Pistol/LotusSinglePistol": "411b62316f5f598f161d3c5c31f175ad4c69d16ac1477264e1cd16a4825e0c49",
    "/Lotus/Weapons/Tenno/Pistol/LotusPistol": "8a33fca13412feda28b5ff02479f2ec445edbf76da6faf73f2d3f0eeea3bf614",
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrum": "9fef678a59f3991e71d8fda7270a0fef9aed47f4b7a147e0230ac7f504ad7418",
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/CorpusHandRocketProjectile": "ee1c169d09edad93cb4b425fec1895312154598197da5ced2d6c13dd2ea40f5a",
    "/Lotus/Types/Weapons/GunProjectile": None,
    "/EE/Types/Engine/Projectile": "8b5fe36bc4e7e28d621d2b59a52648b98d1ca7738ca0fb4d85436ecd03548d2e",
    "/Lotus/Weapons/Corpus/Pistols/CrpHandRL/PrismaAngstrumRocketProjectile": "1bc2b3f1c2508a743ae2cce251022620093cf94d9613cfab93266b9e6a47298f"
}
CHARGE_VOLLEY = dict(policy='full-magazine', damageScale='loaded-rounds',
                    minimumProjectiles=1, rawFireIterations=1)
UNMODELED = ['angstrum-full-charge-ideal-projectile-coverage',
             'angstrum-charge-release-and-flight-timing-unverified',
             'angstrum-charge-completion-buff-snapshot-boundary-unverified',
             'angstrum-ammo-efficiency-integer-accounting-unverified']


def _verified_file(path, expected, label):
    if path is None or not Path(path).is_file() or hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
        raise ValueError('Angstrum ' + label + ' does not match native audit')


def profile(pkg, row, *, native_image=None, raw_package=None):
    """Fail closed on changed ancestry, raw bytes, mode, or native-default source."""
    path = row['path']
    if path not in WEAPONS:
        raise ValueError('not an audited Angstrum weapon')
    ordinal = WEAPONS.index(path)
    projectile_path = PROJECTILES[ordinal]
    _verified_file(native_image, CLIENT_SHA, 'EXE')
    _verified_file(raw_package, PACKAGE_SHA, 'Packages.bin')
    sources = []
    for source in dict.fromkeys(CHAINS[path] + CHAINS[projectile_path]):
        if raw_source_sha(pkg, source) != RAW_SHA[source]:
            raise ValueError('Angstrum raw source changed: ' + source)
        sources.append(dict(path=source, sha256=RAW_SHA[source],
                            **({'attributeRecord':False} if RAW_SHA[source] is None else {})))
    if any(pkg.ancestry(source) != CHAINS[source] for source in (path, projectile_path)):
        raise ValueError('Angstrum parent chain changed')
    native = pkg.resolve(path)
    behaviors = exported_behaviours(native, row)
    modes = row.get('fireModes') or []
    if (row.get('slot') != 'secondary' or row.get('isIncarnonForm')
            or row.get('fireModeSource', 'Behaviors') != 'Behaviors'
            or not behaviors or len(modes) < 2 or modes[0].get('index') != 0
            or modes[0].get('isIncarnonForm') or modes[0].get('multishot') != 1
            or modes[0].get('damage', {}).get('projectile') != projectile_path
            or modes[0].get('damage', {}).get('types') != {'DT_EXPLOSION':200.}):
        raise ValueError('Angstrum ordinary mode0 identity changed')
    fire = _sub_behaviour(behaviors[0], 'fire:') or {}
    state = _sub_behaviour(behaviors[0], 'state:') or {}
    expected_fire = dict(fireIterations=1, ammoRequirement=1, AttenuateForCharge=0,
                         AttenuateFireIterationsForCharge=1, ConsumesChargesForFire=0,
                         ConsumeRemainingClip=0)
    expected_state = dict(ClipSizeAffectsChargeTime=1, UseClipSizeAsDamageMultiplier=1,
                          UseClipWhileCharging=0, ApplyNumChargesToDamageMultiplier=1,
                          MinChargeRatio=1, MinDamageMultiplier=.001, MaxDamageMultiplier=0,
                          DamageMultiplier=1, AutoFireWhenChargeCompleted=1,
                          ChargeTime=(.5 if ordinal == 0 else .2), ChargeModifier='WEAPON_FIRE_RATE')
    if (native.get('MaxCharges') != 120
            or any(fire.get(key) != value for key, value in expected_fire.items())
            or any(state.get(key) != value for key, value in expected_state.items())):
        raise ValueError('Angstrum full-charge gate or iteration contract changed')
    projectile = pkg.resolve(projectile_path)
    attack = projectile.get('AttackData') or {}
    blast = projectile.get('ExplosiveAttack') or {}
    expected_proc = .22 if ordinal == 0 else .25999999
    if (attack.get('Amount') != 200 or attack.get('Type') != 'DT_EXPLOSION'
            or attack.get('ProcChance') != expected_proc or blast.get('Amount') != 250
            or blast.get('Type') is not None
            or blast.get('ProcChance') != (.22 if ordinal == 0 else None)
            or projectile.get('DealDamageThroughImpactBehavior') != 1):
        raise ValueError('Angstrum projectile packet contract changed')
    return dict(name=row['nameEn'], directTotal=200., fireMode=0,
        projectile=projectile_path, behaviourSource='Behaviors[0]',
        scope='ordinary mode0 full magazine; amounts per projectile before charge scale; separate direct and radial packets',
        charge=dict(seconds=float(state['ChargeTime']), cadence='draw-then-rate',
                    modifier='WEAPON_FIRE_RATE', scalesWithFireRate=True,
                    nativeField='Behaviors[0].state.ChargeTime', nativeSource=path),
        chargeVolley=dict(CHARGE_VOLLEY),
        radials=[dict(damage={'blast':250.}, radius_m=float(projectile['DamageRadius']),
            falloff_start_m=0., falloff_reduction=float(projectile['ExplosionFallOff']),
            crit_chance=float(projectile['CriticalChance']),
            crit_multiplier=float(projectile['CriticalMultiplier']),
            status_chance=.22 if ordinal == 0 else .10000000149011612,
            takes_multishot=True, takes_blast_radius_mods=True, impact_delay_seconds=0.,
            nativeSource=projectile_path, nativeField='ExplosiveAttack',
            damageTypeSource='native-constructor-DT_EXPLOSION',
            statusSource='native-explicit' if ordinal == 0 else 'native-constructor-ProcChance-0.1',
            statusDenominatorSource='native-raw-fireIterations=1')],
        unmodeled=list(UNMODELED), nativeSources=sources,
        generatedBy='tools/import_native_angstrum.py', packageBuild='2026.10.22.13.12',
        packageSha256=PACKAGE_SHA, source=dict(clientSha256=CLIENT_SHA,
            descriptorNameOffset=8, maxCharges=120, chargeGate='0x14015efb0',
            projectileScaleStore='0x1403c4cef', directScaleConsumer='0x1416377a4',
            radialScaleConsumer='0x141234a7a', radialTypeDefault='0x140fba662',
            radialStatusDefault='0x1400e8080', radialPacketProcCopy='0x140508ee7',
            rawIterationGetter='0x1404728b0', statusNormalization='0x141586f50'))


def import_profiles(pkg, rows, payload, *, native_image, raw_package):
    by_path = {row['path']:row for row in rows}
    entries = {path:profile(pkg, by_path[path], native_image=native_image, raw_package=raw_package)
               for path in WEAPONS}
    for path, entry in entries.items():
        prior = payload.setdefault('auditedAttacks', {}).get(path, {})
        payload['auditedAttacks'][path] = {**deepcopy(prior), **entry}
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--native-image', type=Path, required=True)
    parser.add_argument('--raw-package', type=Path, required=True)
    parser.add_argument('--export', type=Path, default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--output', type=Path, default=ROOT/'data/mechanics/combat-reference.json')
    args = parser.parse_args()
    pkg = PackageIndex(args.packages, json.loads(args.parents.read_text(encoding='utf-8-sig')))
    payload = json.loads(args.output.read_text(encoding='utf-8'))
    import_profiles(pkg, json.loads(args.export.read_text(encoding='utf-8'))['data'], payload,
                    native_image=args.native_image, raw_package=args.raw_package)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print('audited ordinary Angstrum modes: 2')


if __name__ == '__main__':
    main()
