"""100 real default-mode replays plus 100 explicit zero-status admission fixtures.
Reports actual eligibility and complete CPU replay timings; never fabricates
production coverage from modified fixtures or treats a microkernel as a bake.
"""
import argparse,ctypes as c,json,os,sys,time,hashlib,subprocess,random
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
os.environ.update(WF_ANALYZER_SERIAL='1',WF_ANALYSIS_STATICS_CACHE_PATH=str(ROOT/'.local/gpu-unused.json'))
import app
from wfarsenal import optimizer as o,native_replay as n,search_combat
from wfarsenal.damage import Scenario,ModEffect
from tools.gpu_bake.backend import DirectBatch
ap=argparse.ArgumentParser();ap.add_argument('--nvrtc-dir',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
core=n.wfcore;original=core.trajectory
captured=[];reject=[];prepare=[]
def capture(config,helper):
 started=time.perf_counter()
 try:captured.append(core.direct_bake_stream(config,helper))
 except core.NativeUnsupported as exc:reject.append(str(exc))
 prepare.append(time.perf_counter()-started)
 return original(config,helper)
core.trajectory=capture
weapons=[w for w in app.CATALOG['weapons'] if w.get('available') and w.get('analysisAvailable') and w.get('slot') in ('primary','secondary')]
random.Random(20261028).shuffle(weapons);weapons=weapons[:100]
rows=[];real_streams=[];fixture_streams=[];exact=0
for fixture in (False,True):
 for i,w in enumerate(weapons):
  raw=o.resolve_record(app.EXPORTS['weapons'],w['path'],kind='weapon');family=o._weapon_type(None,raw)
  modes=[j for j,m in enumerate(raw.get('fireModes') or ()) if isinstance(m.get('damage'),dict)]
  mode=modes[-1] if raw.get('isIncarnon') and len(modes)>1 else modes[0]
  weapon=o._select_fire_mode(raw,mode,weapon_type=family)[0]
  effects=[ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',-1.)] if fixture else []
  scenario=Scenario(trigger_policy='emergent');stats=o.apply_mods(weapon,effects,scenario=scenario)
  o._bind_combat_inputs(stats,weapon,(),effects,scenario)
  context=dict(target=dict(health=3000.,shield=0.,overguard=0.,armour=200.,baseLevel=1),level=1,windowSeconds=30.,headshotChance=0.)
  captured.clear();reject.clear();prepare.clear();search_combat._REPLAYS.clear()
  started=time.perf_counter()
  try:
   result=search_combat.window(stats,context,score_only=True)
   elapsed=time.perf_counter()-started
   if captured:
    predicted=DirectBatch.cpu(captured)[0]
    expected=tuple(result[k] for k in ('killsPerMinute','windowDps','totalWindowDamage'))
    assert predicted==expected,(w['nameEn'],predicted,expected)
    exact+=1;(fixture_streams if fixture else real_streams).append(captured[0])
   rows.append(dict(weapon=w['nameEn'],path=w['path'],fixtureZeroStatus=fixture,eligible=bool(captured),
                    cpuReplaySeconds=max(0.,elapsed-sum(prepare)),prepareSeconds=sum(prepare),reasons=list(reject)))
  except Exception as exc:
   rows.append(dict(weapon=w['nameEn'],fixtureZeroStatus=fixture,error=str(exc)))
  if (i+1)%10==0:print(('fixture' if fixture else 'real'),i+1,flush=True)
# Compile optimized CPU interpreter; compare GPU to that alternative too.
exe=args.output/'direct-cpu.dll'
subprocess.run(['rustc','--crate-type','cdylib','-O',str(ROOT/'tools/gpu_bake/direct_cpu.rs'),'-o',str(exe)],check=True)
lib=c.CDLL(str(exe));lib.direct_batch.argtypes=[c.c_void_p]*6+[c.c_size_t]
def native_cpu(rows):
 flat=[];offsets=[];lens=[]
 for events,_,_ in rows:offsets.append(len(flat));lens.append(len(events));flat.extend(events)
 arrays=[(c.c_double*max(1,len(flat)))(*flat),(c.c_int*len(rows))(*offsets),(c.c_int*len(rows))(*lens),
         (c.c_double*len(rows))(*[r[1] for r in rows]),(c.c_double*len(rows))(*[r[2] for r in rows])]
 out=(c.c_double*(len(rows)*3))();lib.direct_batch(*arrays,out,len(rows))
 return [tuple(out[i*3:i*3+3]) for i in range(len(rows))]
probes=[]
with DirectBatch(args.nvrtc_dir) as gpu:
 for label,source in [('real',real_streams),('zero-status-fixture',fixture_streams)]:
  if not source:continue
  for count in (len(source),100,1024,8192):
   batch=[source[i%len(source)] for i in range(count)]
   expected=DirectBatch.cpu(batch);assert native_cpu(batch)==expected
   probe=gpu.probe(batch,repeats=5,cpu_reference=native_cpu)
   probes.append(dict(label=label,count=count,**probe))
 result=dict(device=gpu.cuda.name,architecture=gpu.cuda.arch,realScenarios=100,
  realEligible=len(real_streams),fixtureEligible=len(fixture_streams),exactCPUReplayMatches=exact,
  rows=rows,probes=probes,scope='whole fixed direct replays, not complete loadout searches',
  engineFingerprint=app._analysis_inputs_fingerprint())
(args.output/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','probes')},ensure_ascii=False))
for p in probes:print(p['label'],p['count'],p['gain'],p['admitted'])
