"""Import exact Quanta contact-cube attacks; shooting/merging cubes stays deferred."""
from __future__ import annotations
import argparse,json,hashlib,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _extract_fire_modes
SPECS=(('Quanta','quanta_cube','/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifleProjectile'),
       ('Quanta Vandal','quanta_vandal_cube','/Lotus/Weapons/Corpus/LongGuns/CrpShockRifle/CrpShockRifleProjectile'),
       ('Tenet Quanta','tenet_quanta_cube','/Lotus/Weapons/Corpus/BoardExec/Primary/CrpBEQuanta/CrpBEQuantaProjectile'))

def import_profiles(packages,reference,exported,payload):
    import yaml
    pkg=PackageIndex(packages,json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    rows={w['nameEn']:w for w in exported['data']};changes=[]
    for name,ref_id,projectile in SPECS:
        w=rows[name];m=w['fireModes'][1];raw=pkg.resolve(projectile)
        behavior=pkg.resolve(w['path'])['Behaviors'][1]
        fire=next(v for k,v in behavior.items() if k.startswith('fire:') and isinstance(v,dict))
        if fire.get('ConsumePartialAmmo')!=0 or fire.get('ammoRequirement')!=10:
            raise ValueError('Quanta ammo gate changed: '+name)
        direct = 180. if name=='Tenet Quanta' else 100.
        if (m.get('ammoCost')!=10 or m.get('trigger')!='/Lotus/Language/Menu/Loadout_TriggerSemiAuto'
                or m['damage'].get('projectile')!=projectile or m['damage']['types']!={'DT_ELECTRICITY':direct}):
            raise ValueError('Quanta mode identity changed: '+name)
        if (raw.get('Embed') or raw.get('BounceOnAvatars')!=0 or raw.get('MaxLife')!=9
                or raw.get('DamageRadius')!=.5 or raw.get('AttackData',{}).get('Amount')!=direct
                or raw['AttackData'].get('Type')!='DT_ELECTRICITY'):
            raise ValueError('Quanta contact lifecycle changed: '+name)
        blast=raw['ExplosiveAttack']
        if (blast.get('Amount')!=150 or blast.get('Type')!='DT_EXPLOSION'
                or blast.get('HitType')!='DHT_RADIAL' or blast.get('ForcedProcs')
                or abs(blast.get('ProcChance',0)-.26)>1e-6):
            raise ValueError('Quanta contact blast changed: '+name)
        src=reference/'data/weapons/primary'/(ref_id+'.yaml');spec=yaml.safe_load(src.read_text(encoding='utf-8'))
        atk=spec['attack'];r=atk['radial']
        if atk['damage']!={'electricity':direct} or r['damage']!={'blast':150} or r['radius_m']!=.5 or r['falloff_reduction']!=0:
            raise ValueError('Quanta reference identity changed: '+name)
        native_sources=[]
        for path in (w['path'],projectile):
            f=pkg._path_to_file(path)
            if not f.is_file():f=f.with_suffix('.txt')
            native_sources.append(dict(path=path,sha256=hashlib.sha256(f.read_bytes()).hexdigest()))
        entry=dict(name=name,referenceId=ref_id,source=src.relative_to(reference).as_posix(),sourceSha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                   nativeSources=native_sources,packageBuild=packages.parent.name,projectile=projectile,directTotal=direct,ammoCost=10,requiresFullAmmo=True,
                   scope=f'Alternate cube collides with the aimed target: one {direct:g} Electricity direct hit and one 150 Blast contact explosion.',
                   radials=[dict(damage={'blast':150.},crit_chance=raw['CriticalChance'],crit_multiplier=raw['CriticalMultiplier'],
                                 status_chance=blast['ProcChance'],forced_procs=[],takes_multishot=True,takes_condition_overload=False,impact_delay_seconds=0.)],
                   compression={**atk['compression'],'radius':.5,'takesRadiusMods':True},
                   unmodeled=['quanta-player-shot-detonation-unmodeled','quanta-idle-detonation-unmodeled','quanta-cube-chain-unmodeled'])
        payload.setdefault('auditedAttacks',{}).setdefault(w['path'],{}).setdefault('modes',{})['1']=entry
        # The inherited gun-butt action is not an alternate ranged attack.
        extracted=_extract_fire_modes(pkg,w['path'],pkg.resolve(w['path']))
        aux=[i for i,r in enumerate(extracted) if r.get('behaviorKind')=='auxiliary-melee']
        changes.append(dict(name=name,path=w['path'],profile=entry,auxiliaryModes=aux))
    return changes

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--packages',type=Path,required=True);ap.add_argument('--wfsim',type=Path,required=True)
    ap.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output',type=Path,default=ROOT/'data/mechanics/combat-reference.json');ap.add_argument('--evidence',type=Path,required=True)
    a=ap.parse_args()
    if a.evidence.exists():ap.error('choose a new evidence path')
    sys.path.insert(0,str(ROOT));from tools.refresh_spread_talons import preserve_lines,patch_json_bytes
    raw=a.output.read_bytes();payload=json.loads(raw);exp=a.export.read_bytes();exported=json.loads(exp)
    changes=import_profiles(a.packages,a.wfsim,exported,payload)
    from copy import deepcopy
    for change in changes:
        w=next(w for w in exported['data'] if w['path']==change['path']);before=deepcopy(w)
        for i in change['auxiliaryModes']:w['fireModes'][i]['behaviorKind']='auxiliary-melee'
        if before!=w:exp=patch_json_bytes(exp,before,w)
    a.output.write_bytes(preserve_lines(raw,(json.dumps(payload,ensure_ascii=False,indent=2)+chr(10)).encode('utf-8')))
    a.export.write_bytes(exp);a.evidence.parent.mkdir(parents=True,exist_ok=True)
    a.evidence.write_text(json.dumps(dict(sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),cases=changes),ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    print('Audited Quanta contact modes:',len(changes))
if __name__=='__main__':main()
