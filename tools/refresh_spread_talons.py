"""Refresh verified cadence and Talons. Historical CLI name; spread is deferred."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from copy import deepcopy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'vendor'))
from wfarsenal.packages import PackageIndex
from wfarsenal.extract import _extract_fire_modes
NAMES=('Baza Prime','Akstiletto Prime','Supra Vandal','Karak Wraith','Viper Wraith','Tiberon','Bolto','Hema')
TALONS='/Lotus/Weapons/Tenno/ThrowingWeapons/U18ThrowingKnives/U18throwingknives'

def patch_json_bytes(original, before, after):
    # Keep unmodified lines (including historical mixed endings) byte-identical.
    text=original.decode('utf-8').replace('\r\n','\n')
    a=json.dumps(before,ensure_ascii=False,indent=1,sort_keys=True).replace('\n','\n'+' '*2)
    b=json.dumps(after,ensure_ascii=False,indent=1,sort_keys=True).replace('\n','\n'+' '*2)
    if text.count(a)!=1:raise ValueError('export record layout ambiguous')
    candidate=text.replace(a,b,1).encode('utf-8')
    return preserve_lines(original,candidate)

def preserve_lines(original,candidate):
    import difflib
    old=original.splitlines(keepends=True);new=candidate.splitlines(keepends=True)
    endings=bytes([13,10])
    matcher=difflib.SequenceMatcher(None,[l.rstrip(endings) for l in old],[l.rstrip(endings) for l in new],autojunk=False)
    return b''.join(b''.join(old[i:j] if tag=='equal' else new[k:l]) for tag,i,j,k,l in matcher.get_opcodes())

def refresh(packages, ref, export, output, *, update_export=True):
    import yaml
    pkg=PackageIndex(packages,json.loads((packages.parent/'parents.json').read_text(encoding='utf-8-sig')))
    def source(path):
        p=pkg._path_to_file(path)
        if not p.is_file():p=p.with_suffix('.txt')
        return dict(path=path,sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    original=export.read_bytes();weapons=json.loads(original)['data']
    original_profile=output.read_bytes()
    payload=json.loads(original_profile)
    records={row['nameEn']:row for row in weapons}
    reference={}
    for p in (ref/'data/weapons').rglob('*.yaml'):
        spec=yaml.safe_load(p.read_text(encoding='utf-8'))
        if isinstance(spec,dict) and spec.get('internal_name'):
            reference.setdefault(spec['internal_name'],[]).append((p,spec))
    evidence=[]
    payload.pop('spreadProfiles', None)
    profiles=payload.setdefault('cadenceProfiles',{})
    for name in NAMES:
        w=records[name];raw=pkg.resolve(w['path']);b=raw['Behaviors'][0]
        f=next(v for k,v in b.items() if k.startswith('fire:') and isinstance(v,dict))
        candidates=[(p,x) for p,x in reference.get(w['path'],[]) if x.get('default_form') or x.get('form','base')=='base']
        if len(candidates)!=1:raise ValueError('ambiguous reference: '+name)
        path,spec=candidates[0];atk=spec['attack']
        if atk.get('radial') or atk.get('lingering') or atk.get('beam') or atk.get('cluster'):
            raise ValueError('not an audited single-hit weapon: '+name)
        total=sum(w['fireModes'][0]['damage']['types'].values())
        if abs(total-sum(atk['damage'].values()))>.02:raise ValueError('base vector mismatch: '+name)
        entry=dict(directTotal=total,referenceId=spec['id'],fireMode=0,sourceBuild=packages.parent.name,
                   nativeSources=[source(w['path'])],referenceSource=path.relative_to(ref).as_posix(),
                   referenceSha256=hashlib.sha256(path.read_bytes()).hexdigest())
        if name in ('Tiberon','Hema'):
            expected_delay = .06 if name=='Tiberon' else .1
            state=b.get('state:WeaponBurstStateBehavior') or {}
            burst=atk.get('burst') or {}
            if (state.get('NumShots')!=3 or state.get('IgnoreFireRate')!=0
                    or state.get('ConsumeAmmoOncePerBurst')!=0
                    or abs(float(state.get('BurstDelay',0))-expected_delay)>1e-8
                    or burst.get('count')!=3 or burst.get('delay_seconds')!=expected_delay):
                raise ValueError(name+' burst contract changed')
            entry['burst']=dict(count=3,delay_seconds=float(state['BurstDelay']))
        if name=='Hema':entry['unmodeled']=['hema-player-health-cost-not-modeled']
        if entry.get('burst'):profiles[w['path']]=entry
        before=deepcopy(w)
        extracted=_extract_fire_modes(pkg,w['path'],raw)
        if len(extracted)!=len(w['fireModes']):raise ValueError('mode inventory changed: '+name)
        for old,new in zip(w['fireModes'],extracted,strict=True):
            if new.get('behaviorKind')=='auxiliary-melee':old['behaviorKind']='auxiliary-melee'
        if update_export and before!=w:original=patch_json_bytes(original,before,w)
        evidence.append(dict(name=name,profile=entry))
    w=records['Talons'];before=deepcopy(w)
    raw=pkg.resolve(TALONS);modes=_extract_fire_modes(pkg,TALONS,raw)
    if (modes[0]['damage'].get('source')!='EmbedDeathAttack'
            or modes[0]['damage']['types']!={'DT_EXPLOSION':250.0}):
        raise ValueError('Talons native contract mismatch')
    candidates=[(p,x) for p,x in reference[TALONS] if x.get('default_form') or x.get('form','base')=='base']
    if len(candidates)!=1:raise ValueError('ambiguous Talons reference')
    p,spec=candidates[0]
    if modes[0]['damage']['procChance']!=0:
        raise ValueError('Talons native status now present; review calibrated fallback')
    if spec['attack']['status_chance']!=.1 or spec['attack']['forced_procs']!=['puncture']:
        raise ValueError('Talons reference contract changed')
    # Native attack does not serialize its natural SC. Keep the missing raw
    # value and the reference fallback provenance separate and visible.
    modes[0]['damage'].update(nativeProcChance=modes[0]['damage']['procChance'],procChance=.1,
        procChanceSource='pinned-reference-talons-status-chance')
    for old,new in zip(w['fireModes'],modes,strict=True):
        old['damage']=new['damage']
        if new.get('behaviorKind'):old['behaviorKind']=new['behaviorKind']
    if update_export and before!=w:original=patch_json_bytes(original,before,w)
    # No radial child: the primary attack is the explosion itself.
    payload['auditedAttacks'][TALONS]=dict(name='Talons',directTotal=250.,pureRadial=True,statusChanceFallback=.1,
        scope='single-target embedded mine, immediate manual detonation after each throw',
        source=p.relative_to(ref).as_posix(),sourceSha256=hashlib.sha256(p.read_bytes()).hexdigest(),
        nativeSources=[source(TALONS),source(TALONS+'Projectile')],sourceBuild=packages.parent.name,
        unmodeled=['talons-manual-detonation-timing-assumed','talons-multishot-spatial-hit-loss-unmodeled',
                   'talons-natural-status-reference-calibrated'])
    evidence.append(dict(name='Talons',before=before,after=w,profile=payload['auditedAttacks'][TALONS]))
    rendered=(json.dumps(payload,ensure_ascii=False,indent=2)+chr(10)).encode('utf-8')
    output.write_bytes(preserve_lines(original_profile,rendered))
    if update_export:export.write_bytes(original)
    return dict(packageBuild=packages.parent.name,sourceCommit=subprocess.check_output(['git','-C',str(ref),'rev-parse','HEAD'],text=True).strip(),
                cases=evidence)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--packages',type=Path,required=True);p.add_argument('--wfsim',type=Path,required=True)
    p.add_argument('--export',type=Path,default=ROOT/'data/export/2026.08.13.13.24/weapons.json')
    p.add_argument('--output',type=Path,default=ROOT/'data/mechanics/combat-reference.json')
    p.add_argument('--evidence',type=Path,required=True)
    a=p.parse_args()
    if a.evidence.exists():p.error('preserve prior evidence; choose a new path')
    evidence=refresh(a.packages,a.wfsim,a.export,a.output)
    a.evidence.parent.mkdir(parents=True,exist_ok=True)
    a.evidence.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('refreshed native cadence / Talons cases:',len(evidence['cases']))
if __name__=='__main__':main()
