"""Inventory live ranged-model gaps without equating parity or silence to calibration.

One identity is an exported weapon path plus explicit mode index. Counts never
claim full game correctness: a native resource citation is not consumer proof,
and reference-only records are kept distinct from raw-data evidence.
"""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RANGED_SLOTS={'primary','secondary','arch_gun'}
GAP=re.compile(r'unmodeled|unverified|unresolved|unavailable|not-modeled|not-implemented|unapplied|unknown|approximate|idealized|ideal-projectile|boundary|order-fixed',re.I)
CONTEXT_GAPS={'syndicate-affinity-unavailable'}
NATIVE_KEYS={'nativeSources','nativeSha256','nativeField','packageSha256','packagesSha256','packagesBinSha256','nativeSource','clientSha256','rawSources','rawSha256'}


def source_kinds(value):
    kinds=set()
    def visit(obj):
        if isinstance(obj,dict):
            if any(k in obj and obj[k] for k in NATIVE_KEYS):kinds.add('native-static-declared')
            for key,v in obj.items():
                # A primary profile retains sibling mode records. Their sources
                # cannot certify the currently selected mode's mechanism.
                if key == 'modes':
                    continue
                if key in ('source','referenceSource','referenceId','sourceId','reference') and isinstance(v,str):
                    if v.endswith(('.yaml','.yml')) or 'wfsim' in v.lower():kinds.add('community-reference-declared')
                visit(v)
        elif isinstance(obj,list):
            for item in obj:visit(item)
    visit(value)
    return sorted(kinds)


def mode_status(mode):
    if mode.get('behaviorKind')=='auxiliary-melee':return 'auxiliary-melee-excluded'
    damage=mode.get('damage')
    if not isinstance(damage,dict):return 'missing-damage-data'
    if sum(float(v or 0.) for v in (damage.get('types') or {}).values())<=0:return 'no-positive-direct-payload'
    return 'evaluable'


def summarize(rows):
    expected=[(r['path'],m['mode']) for r in rows for m in r['modes']]
    if len(set(expected))!=len(expected):raise ValueError('duplicate weapon/mode identities')
    modes=[m for r in rows for m in r['modes'] if m['status']=='evaluable']
    by_reason={}
    for r in rows:
        for m in r['modes']:
            for reason in m.get('gaps',[]):
                by_reason.setdefault(reason,{'weapons':set(),'modes':0})['weapons'].add(r['path'])
                by_reason[reason]['modes']+=1
    reasons=[dict(reason=k,weapons=len(v['weapons']),modes=v['modes']) for k,v in by_reason.items()]
    reasons.sort(key=lambda r:(-r['weapons'],r['reason']))
    return dict(weaponRecords=len(rows),weaponRecordsWithNoModes=sum(not r['modes'] for r in rows),explicitModes=len(expected),evaluableModes=len(modes),
        excludedOrMissing=dict(Counter(m['status'] for r in rows for m in r['modes'] if m['status']!='evaluable')),
        weaponsWithExplicitGaps=sum(any(m.get('gaps') for m in r['modes']) for r in rows),
        evaluableModesWithExplicitGaps=sum(bool(m.get('gaps')) for m in modes),
        modesWithNoReportedGap=sum(not m.get('gaps') and not m.get('error') for m in modes),
        nativeStaticSpecialEvidenceModes=sum('native-static-declared' in m.get('sourceKinds',[]) for m in modes),
        referenceOnlySpecialEvidenceModes=sum(m.get('sourceKinds')==['community-reference-declared'] for m in modes),
        modesWithCOReference=sum('community-reference-declared' in m.get('coSourceKinds',[]) for m in modes),
        contextRequiredModes=sum(bool(m.get('contextRequirements')) for r in rows for m in r['modes']),
        prepareErrors=sum(bool(m.get('error')) for r in rows for m in r['modes']),
        fullGameplayCalibration='not-established-by-this-inventory',reasons=reasons)


def inventory(include_companions=False):
    import app
    from wfarsenal import optimizer as opt,event_profiles as ep
    from wfarsenal.manual_combat import prepare,reference
    from wfarsenal.damage import Scenario,ModEffect
    from wfarsenal.combat_replay import replay
    refs=reference();rows=[]
    for weapon in app.EXPORTS['weapons']:
        slot=weapon.get('slot')
        if slot not in RANGED_SLOTS and not (include_companions and slot=='companion'):continue
        row=dict(path=weapon['path'],name=weapon.get('nameEn'),nameZh=weapon.get('nameZh'),slot=slot,modes=[])
        for index,mode in enumerate(weapon.get('fireModes') or []):
            item=dict(mode=index,nativeMode=mode.get('index',index),status=mode_status(mode),incarnon=bool(mode.get('isIncarnonForm')))
            if item['status']!='evaluable':row['modes'].append(item);continue
            try:
                selected=opt._select_fire_mode(weapon,index,weapon_type=opt._weapon_type(None,weapon))[0]
                profile=ep.base_profile(selected,0)
                co=ep.co_profile(selected,0)
                kinds=source_kinds(profile)
                inc=refs.get('incarnon',{}).get(weapon['path'],{}) if item['incarnon'] else {}
                kinds=sorted(set(kinds)|set(source_kinds(inc)))
                item.update(sourceKinds=kinds,coSourceKinds=source_kinds(co),
                    componentKinds=sorted(k for k in ('radial','radials','lingering','embedded','clusters','stackable','charge','chargeVolley','burst','battery','manualDetonation') if profile.get(k)),
                    ignoreHeadshotBonus=ep.ignores_headshot_bonus(selected,0),nativeProjectile=(mode.get('damage') or {}).get('projectile'),
                    declaredDamageComponents=[dict(kind=c.get('kind'),source=c.get('source'),amount=c.get('total'),types=c.get('types')) for c in (mode.get('damage') or {}).get('components',[]) if isinstance(c,dict)])
                gaps=set();notes=set();details=[]
                for assumed,probe in ((False,False),(True,False),(False,True)):
                    effects=([ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2),
                              ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',.6)] if probe else [])
                    fight=prepare(dict(weapon=weapon,fire_mode=index,effects=effects,scenario=Scenario(trigger_policy='assumed_max' if assumed else 'emergent')),[],[],assumed=assumed)
                    stats,radial=fight['resolve']('selected',{},0.)
                    notes.update(fight.get('unsupported') or [])
                    runtime=replay(stats,dict(health=3000.,shield=0.,overguard=0.,armour=200.,baseLevel=1),
                        attacks_per_second=stats.fire_rate,window_seconds=4.,combat=fight,
                        trigger_sources=fight['trigger_sources'],collect_timeline=False,headshot_chance=1. if probe else 0.,score_only=True)
                    notes.update(runtime.get('unsupported') or [])
                    details.append(dict(assumedMax=assumed,multishotProbe=probe,hasRadial=radial is not None,hasLingering=bool(getattr(stats,'_lingering',None)),
                        hasEmbedded=bool(getattr(stats,'_embedded',None)),hasStackable=bool(getattr(stats,'_stackable',None)),
                        hasSequence=bool(fight.get('projectileSequence')),triggerKinds=sorted({s['kind'] for s in fight.get('trigger_sources',[]) if s.get('kind')})))
                gaps={n for n in notes if GAP.search(n) and n not in CONTEXT_GAPS}
                item.update(contextRequirements=sorted(notes & CONTEXT_GAPS),gaps=sorted(gaps),notes=sorted(notes),runtime=details)
            except Exception as exc:item.update(error=type(exc).__name__+': '+str(exc),gaps=['audit-preparation-error'])
            row['modes'].append(item)
        rows.append(row)
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--include-companions',action='store_true')
    args=parser.parse_args()
    if args.output.exists():parser.error('choose a new evidence file')
    os.environ['WF_ANALYZER_SERIAL']='1'
    os.environ['WF_ANALYSIS_STATICS_CACHE_PATH']=str(args.output.with_suffix('.isolated-cache.json').resolve())
    sys.path.insert(0,str(ROOT));import app
    app._disable_analysis_statics_persistence();app._refresh_analysis_statics_cache_if_newer=lambda:None
    identity=app._analysis_inputs_fingerprint()
    rows=inventory(args.include_companions)
    result=dict(schemaVersion=1,scope='ranged-exported-model-coverage-not-gameplay-correctness',
        identity={'sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  'inputs':identity,'toolSha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
        includesCompanions=args.include_companions,rows=rows,summary=summarize(rows),
        inputsStable=identity==app._analysis_inputs_fingerprint(),
        interpretation=['No warning does not establish correct modeling.','Native static evidence declares a source; final modifier/trigger consumer proof is a separate axis.',
            'Three bounded 4s replay probes cover both trigger policies and a multishot/headshot probe, not every MOD/Arcane/Incarnon route combination.','Weapon variants and explicit modes count separately; components and reasons overlap.'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
    return int(not result['inputsStable'] or result['summary']['prepareErrors']>0)


if __name__=='__main__':raise SystemExit(main())
