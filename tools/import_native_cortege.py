"""Import Cortege's preserved ground projectile payload without its unresolved firefield.

Fire iterations already live in exported mode.multishot; this component is per
projectile. ExplosiveAttack and EmbedDeathAttack are alternative death sources.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _sub_behaviour
from tools.import_kill_charged_alts import CORTEGE, raw_source_sha, verified_default_max
from tools.import_projectile_components import exported_behaviours

PROJECTILE = CORTEGE.rsplit('/', 1)[0] + '/AltFireHeavyProjectile'
UNMODELED = ['cortege-firefield-mod-routing-unverified',
             'cortege-firefield-spatial-overlap-unverified',
             'cortege-firefield-clock-boundary-unverified']


def profile(pkg, row, *, native_image=None):
    native = pkg.resolve(CORTEGE)
    behaviors = exported_behaviours(native, row)
    if len(behaviors) < 2:
        raise ValueError('Cortege ground behaviors unavailable')
    fire = _sub_behaviour(behaviors[1], 'fire:') or {}
    modes = row.get('fireModes') or []
    if (row.get('fireModeSource') != 'HeavyBehaviors' or len(modes) != 2
            or modes[1].get('index') != 1 or modes[1].get('multishot') != 3
            or fire.get('fireIterations') != 3 or not fire.get('ConsumesChargesForFire')
            or fire.get('projectileType') not in ('AltFireHeavyProjectile', PROJECTILE)):
        raise ValueError('Cortege ground mode / fire iteration contract changed')
    projectile = pkg.resolve(PROJECTILE)
    attack = projectile.get('AttackData') or {}
    death = projectile.get('EmbedDeathAttack') or {}
    blast = projectile.get('ExplosiveAttack') or {}
    if (attack.get('Type') != 'DT_IMPACT' or attack.get('Amount') != 20
            or death.get('Type') != 'DT_FIRE' or death.get('Amount') != 2000
            or blast.get('Amount') != death.get('Amount')
            or blast.get('ProcChance') != death.get('ProcChance')
            or projectile.get('EmbedTime') != [0, 0]):
        raise ValueError('Cortege projectile death contract changed')
    proof = verified_default_max(pkg, CORTEGE, native_image)
    if not proof:
        raise ValueError('Cortege EXE and complete raw weapon ancestry must match native audit')
    proof = dict(proof)
    sources = [dict(path=path, sha256=raw_source_sha(pkg, path))
               for path in (CORTEGE, PROJECTILE, PROJECTILE.rsplit('/', 1)[0] + '/AltFireProjectile')]
    if any(not source['sha256'] for source in sources):
        raise ValueError('Cortege raw projectile ancestry unavailable')
    return dict(name='Cortege', directTotal=20., fireMode=1, projectile=PROJECTILE,
        scope='ground heavy mode; per projectile direct impact plus one alternative death explosion; '
              'exported multishot already carries three fire iterations; primary-kill charge cycle; '
              'firefield omitted pending mod routing and spatial clock contract',
        radials=[dict(damage={'heat':float(death['Amount'])},
            radius_m=float(projectile['DamageRadius']), falloff_start_m=0.,
            falloff_reduction=float(projectile['ExplosionFallOff']),
            crit_chance=float(projectile['CriticalChance']),
            crit_multiplier=float(projectile['CriticalMultiplier']),
            status_chance=float(death['ProcChance']), takes_multishot=True,
            takes_blast_radius_mods=True, impact_delay_seconds=0., nativeSource=PROJECTILE,
            nativeField='EmbedDeathAttack', damageTypeSource='native-inherited-explicit',
            exclusiveAlternatives=['ExplosiveAttack'])], unmodeled=list(UNMODELED),
        nativeSources=sources, generatedBy='tools/import_native_cortege.py',
        packageBuild=proof['packageBuild'], packageSha256=proof['packageSha256'],
        behaviourSource='HeavyBehaviors[1]', source={**proof,
            'projectileDeathScriptSha256':'35dc689324bd96ca125913066a71fa5a1a266fce6c25a156f8793647cd14278a',
            'fireIterationsSource':'HeavyBehaviors[1].fire.fireIterations=3; export mode.multishot=3 already carries it',
            'firefieldAmountRouting':'SpawnElementTrigger P1 pc126-133 overrides Element.AttackData.Amount from projectile query baseAmount',
            'firefieldClock':'DamageTick default1 at 0x1408c279b; immediate contact 0x1416c5768; cache strict lastTime+tick<now at 0x140755840-84c after damage attempts'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--parents', type=Path, required=True)
    parser.add_argument('--export', type=Path, required=True)
    parser.add_argument('--native-image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    pkg = PackageIndex(args.packages, json.loads(args.parents.read_bytes()))
    row = next(row for row in json.loads(args.export.read_bytes())['data'] if row['path'] == CORTEGE)
    args.output.write_text(json.dumps(profile(pkg, row, native_image=args.native_image), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
