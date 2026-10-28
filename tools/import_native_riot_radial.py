"""Recover Riot-848's zero-delay embedded-death radial from native fields.

No reference score or damage default is guessed. Native ancestry must provide an
explicit Blast type and the ordinary explosion must agree in amount/status.
"""
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex
WEAPON='/Lotus/Weapons/Tenno/Pistols/1999EntHybridPistolWeapon/1999EntHybridPistolWeapon'
PROJECTILE='/Lotus/Weapons/Tenno/Pistols/1999EntHybridPistolWeapon/1999EntHybridPistolProjectile'


def profile(pkg):
    native=pkg.resolve(PROJECTILE)
    attack=native.get('AttackData') or {};death=native.get('EmbedDeathAttack') or {}
    blast=native.get('ExplosiveAttack') or {}
    if (native.get('Embed')!=1 or native.get('EmbedTime')!=[0,0] or death.get('Type')!='DT_EXPLOSION'
        or death.get('Amount')!=48 or blast.get('Amount')!=48
        or death.get('ProcChance')!=blast.get('ProcChance')
        or attack.get('Type')!='DT_PUNCTURE' or attack.get('Amount')!=12):
        raise ValueError('Riot embedded projectile contract changed')
    sources=[]
    for path in pkg.ancestry(PROJECTILE):
        file=pkg._path_to_file(path)
        if not file.exists():file=file.with_suffix('.txt')
        if file.exists():sources.append(dict(path=path,sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    return dict(name='Riot-848',directTotal=12.,fireMode=0,projectile=PROJECTILE,
        scope='single-target direct impact plus one immediate embedded-death explosion; alternate death fields are not summed',
        radials=[dict(damage={'blast':float(death['Amount'])},radius_m=float(native['DamageRadius']),
            falloff_start_m=0.,falloff_reduction=float(native['ExplosionFallOff']),
            crit_chance=float(native['CriticalChance']),crit_multiplier=float(native['CriticalMultiplier']),
            status_chance=float(death['ProcChance']),takes_multishot=True,takes_blast_radius_mods=True,
            impact_delay_seconds=0.,nativeSource=PROJECTILE,nativeField='EmbedDeathAttack',
            damageTypeSource='native-inherited-explicit',exclusiveAlternatives=['ExplosiveAttack'])],
        nativeSources=sources,generatedBy='tools/import_native_riot_radial.py')


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--packages',type=Path,required=True)
    ap.add_argument('--parents',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();pkg=PackageIndex(args.packages,json.loads(args.parents.read_bytes()))
    result=profile(pkg);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':main()
