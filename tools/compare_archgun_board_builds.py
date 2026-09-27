"""Replay complete public ranged builds; record UI blockers separately.
Source checkouts stay read-only. A new evidence directory is required per run.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys, math
from datetime import datetime, timezone
from urllib.request import urlopen, Request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import app, yaml
from wfarsenal.damage import Scenario, ModEffectList, enemy_defenses
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.simulator import _mod_matches_weapon
FORMS={'corvas':{'alternate':0},'corvas_prime':{'alternate':0},'velocitus':{'alternate':0},
       'larkspur':{'base':0,'alternate':1},'larkspur_prime':{'base':0,'alternate':1}}
WEAPONS=('corvas','corvas_prime','mausolon','larkspur','larkspur_prime','imperator',
 'imperator_vandal','grattler','kuva_grattler','fluctus','cyngas','velocitus','morgha',
 'cortege','dual_decurion','prisma_dual_decurions')
ELEMENTS={'impact':'DT_IMPACT','heat':'DT_FIRE','cold':'DT_FREEZE','electricity':'DT_ELECTRICITY',
 'toxin':'DT_POISON','magnetic':'DT_MAGNETIC','radiation':'DT_RADIATION'}
BATCH_JS="""import fs from 'node:fs'; import path from 'node:path';
const [repo,input,output]=process.argv.slice(2);
const rel=JSON.parse(fs.readFileSync(path.join(repo,'site/release.json'),'utf8'));
const base=path.join(repo,'site/pkg');
const engine=new Function(fs.readFileSync(path.join(base,'wfsim_wasm.'+rel.wasm+'.js'),'utf8')+';return wasm_bindgen;')();
engine.initSync({module:fs.readFileSync(path.join(base,'wfsim_wasm_bg.'+rel.wasm+'.wasm'))});
const results=JSON.parse(fs.readFileSync(input,'utf8')).map(p=>JSON.parse(engine.api('/api/simulate',JSON.stringify(p))));
fs.writeFileSync(output,JSON.stringify(results,null,2),{flag:'wx'});
"""
def dump(path,value):
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def registry(root):
 rows={}
 for file in root.rglob('*.yaml'):
  row=yaml.safe_load(file.read_text(encoding='utf-8'))
  if isinstance(row,dict) and row.get('id'):rows[row['id']]=row
 return rows
def exact_record(row,records):
 matches=[r for r in records if r['path']==row.get('internal_name')]
 if not matches:matches=[r for r in records if r.get('nameEn')==row.get('name')]
 if len(matches)!=1:raise ValueError('ambiguous or missing identity: '+str(row.get('id')))
 return matches[0]
def local_replay(payload,*,duration,include_arcanes=True):
 kernel_mods=list(payload['mods'])
 if payload.get('exilus'):kernel_mods.append({**payload['exilus'],'slot':8})
 mods=[(app.optimizer.resolve_record(app.EXPORTS['mods'],m['path'],kind='mod'),m['rank'],None) for m in kernel_mods]
 arcs=[(app.optimizer.resolve_record(app.EXPORTS['arcanes'],a['path'],kind='arcane'),a['rank'],a) for a in payload['arcanes']] if include_arcanes else []
 weapon=app.optimizer.resolve_record(app.EXPORTS['weapons'],payload['weapon'],kind='weapon')
 passive=ModEffectList([])
 if arcs:
  card,_,_,_=app._prepare_manual_arcanes([a for _,_,a in arcs],weapon,headshot_chance=1.0)
  passive=app._manual_passive_effects(card)
 override={'innateElements':[{'damageType':payload['innateElement'],'value':payload['innateElementValue']}]} if payload.get('innateElement') else None
 engine={}
 result=app.simulate(export_dir=app.EXPORT_DIR,weapon=payload['weapon'],mods=kernel_mods,slot_count=9 if payload.get('exilus') else 8,
  fire_mode=payload['fireMode'],enemy=payload['enemy'],level=payload['level'],steel_path=True,
  scenario=Scenario(aiming=True, trigger_policy="emergent", distance=(payload.get("scenario") or {}).get("distance")),weapon_override=override,passive_effects=passive,engine_context_sink=engine)
 stats=app._benchmark_timeline_stats(result['moddedStats'])
 target=app.MANUAL_ENEMIES_BY_PATH[payload['enemy']]
 combat=prepare(engine,mods,arcs,assumed=False,affinity_target=target,level=payload['level'])
 window=replay(stats,target,attacks_per_second=stats.sustained_attack_rate,window_seconds=duration,
  level=payload['level'],steel_path=True,headshot_chance=1,trigger_sources=combat['trigger_sources'],combat=combat)
 initial=combat['resolve']('selected',{q['id']:q.get('initialStacks',0) for q in combat['trigger_sources']},0)
 if isinstance(initial,tuple):initial=initial[0]
 return dict(panel=dict(total=initial.total_damage,critChance=initial.crit_chance,
  critMultiplier=initial.crit_multiplier,fireRate=initial.fire_rate,multishot=initial.multishot,
  statusChance=initial.status_chance),defenses=enemy_defenses(target,level=payload['level'],steel_path=True),
  replay=window,unsupported=result.get('unsupported',[]),skipped=result.get('skipped',[]))
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--wfsim',type=Path,required=True);p.add_argument('--board-dir',type=Path)
 p.add_argument('--fetch',action='store_true',help='Download fresh public board snapshots into output')
 p.add_argument('--without-enervate',action='store_true',help='Synthetic ablation: remove only Secondary Enervate')
 p.add_argument('--allow-partial',action='store_true',help='Keep catalog-blocked/incompatible public rows as explicit offline diagnostics instead of trying the next public build')
 p.add_argument('--output',type=Path,required=True);p.add_argument('--runs',type=int,default=200)
 p.add_argument('--weapons',nargs='+',default=list(WEAPONS),help='Explicit non-melee board IDs; default preserves the archgun audit')
 p.add_argument('--per-weapon',type=int,default=2);p.add_argument('--duration',type=float,default=30)
 args=p.parse_args()
 if args.output.exists():p.error('output exists; preserve previous evidence')
 if not args.fetch and not args.board_dir:p.error('--board-dir or --fetch is required')
 if args.runs<=0 or args.per_weapon<=0 or not 0<args.duration<=180:p.error('invalid bounds')
 args.output.mkdir(parents=True);app._disable_analysis_statics_persistence()
 meta=args.output/'meta.json';dump(args.output/'empty.json',{})
 subprocess.run(['node',str(ROOT/'tools/run_reference_wasm.mjs'),str(args.wfsim),'/api/meta',str(args.output/'empty.json'),str(meta)],check=True)
 metadata=json.loads(meta.read_text(encoding='utf-8'));wm={w['id']:w for w in metadata['weapons']}
 mods=registry(args.wfsim/'data/mods');arcanes=registry(args.wfsim/'data/arcanes')
 weapons=registry(args.wfsim/'data/weapons');cases=[];skips=[];requests=[];sources=[]
 for wid in args.weapons:
  path=(args.output if args.fetch else args.board_dir)/f'wfsim-board-{wid}.json'
  if args.fetch:
   req=Request(f'https://wfsim.app/board/{wid}.json',headers={'User-Agent':'WF-Riven-build-audit/1.0'})
   with urlopen(req,timeout=30) as response:raw=response.read()
   snapshot=json.loads(raw)
   if not isinstance(snapshot,list):raise ValueError(f'invalid board response for {wid}')
   path.write_bytes(raw)
  if not path.is_file():skips.append(dict(weapon=wid,reason='missing-snapshot'));continue
  snapshot=json.loads(path.read_text(encoding='utf-8'));dump(args.output/f'board-{wid}.json',snapshot)
  sources.append(dict(weapon=wid,url=f'https://wfsim.app/board/{wid}.json',sha256=digest(path)))
  forms=FORMS.get(wid,{'base':0})
  rows=[(i,r) for i,r in enumerate(snapshot) if r.get('benchmark')=='standard_single_target' and r.get('mode') in forms and 'riven' not in r.get('mods',[]) and not r.get('riven')]
  rows.sort(key=lambda pair:pair[1]['score'],reverse=True)
  if not rows:skips.append(dict(weapon=wid,reason='no-no-riven-row-in-exported-form'));continue
  accepted=0
  for index,row in rows:
   if accepted >= args.per_weapon:break
   try:
    if row.get('evolutions') or row.get('warframe') or row.get('buffs'):
     raise ValueError('unmapped board evolutions or external buffs')
    weapon=exact_record(weapons[wid],app.EXPORTS['weapons'])
    if str(weapon.get('slot') or '').casefold() == 'melee':
     raise ValueError('melee outside audit contract')
    equipped_arcanes=[a for a in row['arcanes'] if not args.without_enervate or a!='secondary_enervate']
    cards=[exact_record(mods[mid],app.EXPORTS['mods']) for mid in row['mods']]
    arcs=[exact_record(arcanes[aid],app.EXPORTS['arcanes']) for aid in equipped_arcanes]
    payload=dict(weapon=weapon['path'],fireMode=forms[row['mode']],
     mods=[dict(path=m['path'],rank=m['maxRank'],slot=i) for i,m in enumerate(cards)],
     arcanes=[dict(path=a['path'],rank=a['maxRank']) for a in arcs],enemy=app._BENCHMARK_ENEMY_PATH,
     level=9999,steelPath=True,headshotChance=1.0,aiming=True,triggerPolicy='emergent',
     slotPolarities=[m.get('polarity') for m in cards],scenario={'distance':0.5})
    if row.get('exilus'):
     exilus=exact_record(mods[row['exilus']],app.EXPORTS['mods'])
     payload['exilus']=dict(path=exilus['path'],rank=exilus['maxRank'])
    if row.get('valence'):payload.update(innateElement=ELEMENTS[row['valence']],innateElementValue=0.60)
    request=dict(weapon=wid,mode=row['mode'],mods=row['mods'],arcane=equipped_arcanes,evolutions=[],
     evolutions_as_given=True,enemy='thrax_centurion',level=9999,steel_path=True,headshot_pct=100,
     aiming=True,duration=args.duration,runs=args.runs,seed=12648430,infinite_ammo=True,
     class_rules={'archgun':{'infinite_ammo':True}},ammo_drops=False,
     spectral_form=False,eximus=False,assume_max=False,frenzy=False,player_at=[0,0],target_at=[0,0.5])
    if row.get('exilus'):request['mods']=[*row['mods'],row['exilus']]
    if row.get('valence'):request.update(valence_element=row['valence'],valence_bonus=0.60)
    blockers=[m['path'] for m in cards if m['path'] not in app.MANUAL_MODS_BY_PATH]+[a['path'] for a in arcs if a['path'] not in app.MANUAL_ARCANES_BY_PATH]
    if row.get('exilus') and exilus['path'] not in app.UTILITY_MODS_BY_PATH:blockers.append(exilus['path'])
    case=dict(id=f'{wid}-{index}',weapon=wid,name=weapon['nameEn'],boardRowIndex=index,board=row,
     manualPayload=payload,referenceRequest=request,catalogBlockers=blockers,nativeIncompatibleMods=[m['path'] for m in cards if not _mod_matches_weapon(m,weapon)],referenceLimitations=wm[wid].get('unmodeled',[]))
    if not args.allow_partial and (blockers or case['nativeIncompatibleMods']):
     skips.append(dict(weapon=wid,rowIndex=index,reason='catalog-blocked-or-native-incompatible',
                       catalogBlockers=blockers,nativeIncompatibleMods=case['nativeIncompatibleMods']))
     continue
    case['local']=local_replay(payload,duration=args.duration)
    if not blockers and args.duration==30:
     try:
      manual=app.simulate_manual_payload(payload)
      case['manualKpm']=manual['benchmarkTimeline']['killsPerMinute']
      case['manualKernelMatches']=math.isclose(case['manualKpm'],case['local']['replay']['killsPerMinute'],rel_tol=1e-9,abs_tol=1e-9)
     except (ValueError,KeyError,app.SimulationError) as e:
      case['manualError']=str(e)
      case['manualKernelMatches']=False
    cases.append(case);requests.append(request);accepted+=1
    print(case['id'],'local KPM',round(case['local']['replay']['killsPerMinute'],4),'catalogBlockers',len(blockers),flush=True)
   except (ValueError,KeyError,app.SimulationError) as e:skips.append(dict(weapon=wid,rowIndex=index,reason=str(e)))
 dump(args.output/'requests.json',requests);(args.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
 subprocess.run(['node',str(args.output/'batch.mjs'),str(args.wfsim),str(args.output/'requests.json'),str(args.output/'responses.json')],check=True)
 responses=json.loads((args.output/'responses.json').read_text(encoding='utf-8'))
 for case,ref in zip(cases,responses,strict=True):
  case['reference']=ref
  case['comparisonKind']='synthetic-enervate-ablation' if args.without_enervate else 'public-board-build'
  if not ref.get('ok'):case['referenceError']=ref;continue
  kpm=ref['score']*60/ref['duration'];lkpm=case['local']['replay']['killsPerMinute']
  local_panel=case['local']['panel'];reference_panel=ref['panel']
  panel_keys={'total':'total','critChance':'crit_chance','critMultiplier':'crit_damage','fireRate':'fire_rate','multishot':'multishot','statusChance':'status_chance'}
  case['panelDifferences']={k:{'local':local_panel[k],'reference':reference_panel[v]} for k,v in panel_keys.items() if not math.isclose(local_panel[k],reference_panel[v],rel_tol=0.001,abs_tol=1e-5)}
  case['targetMatches']=all(math.isclose(case['local']['defenses'][a],ref['target'][b],rel_tol=1e-8,abs_tol=1e-6) for a,b in [('health','health'),('shield','shield'),('armour','armor'),('overguard','overguard')])
  case['uiImportable']=not case['catalogBlockers'] and not case.get('manualError')
  case['fullBuildComparable']=case['uiImportable'] and not case['nativeIncompatibleMods'] and not case['local'].get('skipped')
  case['panelMatches']=not case['panelDifferences']
  case.update(referenceKpm=kpm,referenceKpmSe=ref.get('score_se',0)*60/ref['duration'],localKpm=lkpm,deltaPercent=100*(lkpm/kpm-1) if kpm else None)
  print(case['id'],round(lkpm,4),round(kpm,4),round(case['deltaPercent'] or 0,2),flush=True)
 release=json.loads((args.wfsim/'site/release.json').read_text(encoding='utf-8'))
 dump(args.output/'comparison.json',dict(sourceCommit=subprocess.check_output(['git','-C',str(args.wfsim),'rev-parse','HEAD'],text=True).strip(),
  localInputFingerprint=app._analysis_inputs_fingerprint(),toolSha256=digest(Path(__file__)),release=release,wasmSha256=digest(args.wfsim/'site/pkg'/f"wfsim_wasm_bg.{release['wasm']}.wasm"),
  duration=args.duration,runs=args.runs,seed=12648430,recordedAt=datetime.now(timezone.utc).isoformat(),ablation=args.without_enervate,sources=sources,cases=cases,skips=skips,
  contract='Lv9999 SP Thrax, headshots, ADS, single target, infinite resupply explicitly set by archgun class rule, timed buffs start at zero. Offline kernel audit when catalogBlockers is nonempty. Board score uses separate 180s contract.'))
 print('cases',len(cases),'skips',skips)
if __name__=='__main__':main()
