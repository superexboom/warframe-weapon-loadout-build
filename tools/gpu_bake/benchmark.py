"""Compare fixed-loadout replays, with optional real status-prefix tables."""
import argparse,ctypes as c,json,os,sys,time,subprocess,random,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
os.environ.update(WF_ANALYZER_SERIAL='1',WF_CONCURRENT_SEARCHES='1',
                  WF_ANALYSIS_STATICS_CACHE_PATH=str(ROOT/'.local/gpu-unused.json'))
import app
from wfarsenal import optimizer as o,native_replay as n,search_combat
from wfarsenal.damage import Scenario,ModEffect
from wfarsenal.simulator import _mod_matches_weapon
from tools.gpu_bake.backend import DirectBatch

POOL_SEED = 20261118
POOL_LIMIT = 512
from tools.gpu_bake.pool_tables import STEPS as POOL_STEPS
SCORE_FIELDS = ('killsPerMinute', 'windowDps', 'totalWindowDamage')
POOL_TARGET = dict(target=dict(health=30000., shield=4000., overguard=0., armour=200., baseLevel=1),
                   level=1, windowSeconds=30., headshotChance=0.)
ELEMENT_MODS = {
    'rifle': dict(cold='Rime Rounds', toxin='Malignant Force', electric='High Voltage'),
    'shotgun': dict(cold='Frigid Blast', toxin='Toxic Barrage', electric='Shell Shock'),
    'pistol': dict(cold='Frostbite', toxin='Pistol Pestilence', electric='Jolt'),
}
ELEMENT_PAIRS = (
    ('DT_VIRAL', 'cold', 'toxin'), ('DT_CORROSIVE', 'electric', 'toxin'),
    ('DT_MAGNETIC', 'cold', 'electric'),
)


def _pool_stats(weapon, cards, effects, scenario):
    probe = o.apply_mods(weapon, effects, scenario=scenario)
    derived = o.scenario_with(scenario, victim_status_count=o.expected_victim_status_count(probe))
    stats = o.apply_mods(weapon, effects, scenario=derived)
    o._bind_combat_inputs(stats, weapon, cards, effects, derived)
    return stats


def _pool_cases():
    weapons = sorted((w for w in app.CATALOG['weapons']
                      if w.get('available') and w.get('analysisAvailable')
                      and w.get('slot') in ('primary', 'secondary')), key=lambda w: w['path'])
    random.Random(POOL_SEED).shuffle(weapons)
    mod_names = {name for family in ELEMENT_MODS.values() for name in family.values()}
    mods = {name: [] for name in mod_names}
    for row in app.EXPORTS['mods']:
        if row.get('nameEn') in mods and row.get('selectable') is True and row.get('compatibility'):
            mods[row['nameEn']].append(row)
    cases, used = [], set()
    scenario = Scenario(trigger_policy='emergent')
    for row in weapons:
        if row['path'] in used:
            continue
        raw = o.resolve_record(app.EXPORTS['weapons'], row['path'], kind='weapon')
        family = o._weapon_type(None, raw)
        modes = [i for i, mode in enumerate(raw.get('fireModes') or ()) if isinstance(mode.get('damage'), dict)]
        if not modes:
            continue
        mode = modes[-1] if raw.get('isIncarnon') else modes[0]
        weapon = o._select_fire_mode(raw, mode, weapon_type=family)[0]
        element, *pair = ELEMENT_PAIRS[len(cases) % len(ELEMENT_PAIRS)]
        families = sorted(ELEMENT_MODS, key=lambda name: name != family)
        cards = tuple(next((o._mod_card(mod, scenario) for name in families
                            for mod in mods[ELEMENT_MODS[name][kind]] if _mod_matches_weapon(mod, raw)),
                           None) for kind in pair)
        if not all(cards):
            continue
        effects = o._effects(cards, scenario)
        stats = _pool_stats(weapon, cards, effects, scenario)
        if stats.status_chance <= 0 or stats.damage_types.get(element, 0.) <= 0:
            continue
        info = dict(weapon=row['nameEn'], path=row['path'], mode=mode, element=element,
                    mods=[card.key for card in cards])
        cases.append((info, (weapon, cards, effects, scenario)))
        used.add(row['path'])
        if len(cases) == 100:
            break
    return cases


def _pool_sweep(cases, after_replay=None):
    core = n.wfcore
    counter = n.STATS.copy()
    before = core.bake_pool_stats()
    started = time.perf_counter()
    scores = []
    for _info, prepared in cases:
        search_combat._REPLAYS.clear()
        result = {}
        try:
            stats = _pool_stats(*prepared)
            score = search_combat.window(stats, POOL_TARGET, score_only=True)
            result['scores'] = tuple(float(score[field]) for field in SCORE_FIELDS)
        except Exception as exc:
            result['error'] = f'{type(exc).__name__}: {exc}'
        if after_replay is not None:
            after_replay()
        scores.append(result)
    elapsed = time.perf_counter() - started
    after = core.bake_pool_stats()
    return scores, dict(sweepSeconds=elapsed, nativeCalls=n.STATS['native'] - counter['native'],
                        nativeFallbacks=n.STATS['fallback'] - counter['fallback'],
                        hits=after['hits'] - before['hits'], misses=after['misses'] - before['misses'],
                        installedKeys=after['keys'])


def _pool_diff(expected, actual):
    if 'error' in expected or 'error' in actual:
        return dict(exact=False, error=actual.get('error') or expected['error'])
    left, right = expected['scores'], actual['scores']
    return dict(exact=struct.pack('<3d', *left) == struct.pack('<3d', *right),
                delta=[b - a for a, b in zip(left, right)])


def _table_difference(expected, actual, keys):
    if len(expected) != len(actual):
        return dict(expectedBytes=len(expected), actualBytes=len(actual))
    for i, (a, b) in enumerate(zip(expected, actual)):
        if a != b:
            word, column = divmod(i // 8, 11)
            key, row = divmod(word, POOL_STEPS)
            offset = i - i % 8
            return dict(keyIndex=key, key=keys[key], step=row + 1, stack=column,
                        cpuBits=expected[offset:offset + 8].hex(), gpuBits=actual[offset:offset + 8].hex())
    return None


def _run_pool_prefixes(args):
    core = n.wfcore
    if not n.ENABLED or n.SHADOW or not hasattr(core, 'bake_pool_capture'):
        raise SystemExit('A current native build with replay enabled and shadow disabled is required')
    started = time.perf_counter()
    cases = _pool_cases()
    setup = time.perf_counter() - started
    observed = {}
    saturated = 0

    def collect():
        nonlocal saturated
        keys = core.bake_pool_pending()
        saturated += len(keys) == POOL_LIMIT
        for key in keys:
            observed.setdefault(struct.pack('<2d', *key), key)

    result = dict(scope='30-second fixed-loadout combat replays; not full optimizer bakes', seed=POOL_SEED,
                  engineFingerprint=app._analysis_inputs_fingerprint(), cases=len(cases),
                  target=POOL_TARGET, scoreFields=SCORE_FIELDS, maxInstalledKeys=POOL_LIMIT,
                  steps=POOL_STEPS, setupSeconds=setup)
    core.bake_pool_stop()
    try:
        # Capture warms the same prepared metadata as each following sweep, but
        # is not used as the off baseline. Every sweep still performs replays.
        core.bake_pool_capture(POOL_LIMIT)
        _, result['capture'] = _pool_sweep(cases, collect)
        core.bake_pool_stop()
        baseline, result['off'] = _pool_sweep(cases)
        keys = list(observed.values())[:POOL_LIMIT]
        result.update(distinctObservedKeys=len(observed), keysTimed=len(keys), captureSaturatedFights=saturated)
        start = time.perf_counter()
        expected = core.bake_pool_reference(keys, POOL_STEPS)
        rust_build = time.perf_counter() - start
        start = time.perf_counter()
        core.bake_pool_install(keys, POOL_STEPS, expected)
        rust_install = time.perf_counter() - start
        rust, result['rust'] = _pool_sweep(cases)
        result['rust'].update(buildSeconds=rust_build, installSeconds=rust_install,
                              totalSeconds=rust_build + rust_install + result['rust']['sweepSeconds'])
        core.bake_pool_stop()
        cuda = None
        result['cuda'] = gpu = {}
        try:
            from tools.gpu_bake.pool_tables import PoolDevice
            start = time.perf_counter()
            with PoolDevice(args.nvrtc_dir) as device:
                gpu.update(device=device.name, startupSeconds=time.perf_counter() - start)
                start = time.perf_counter()
                data = device.build(keys, POOL_STEPS)
                gpu['buildSeconds'] = time.perf_counter() - start
            start = time.perf_counter()
            gpu['tableExact'] = data == expected
            gpu['verifySeconds'] = time.perf_counter() - start
            if gpu['tableExact']:
                start = time.perf_counter()
                core.bake_pool_install(keys, POOL_STEPS, data)
                gpu['installSeconds'] = time.perf_counter() - start
                cuda, metrics = _pool_sweep(cases)
                gpu.update(metrics)
                gpu['totalSeconds'] = sum(gpu[field] for field in
                    ('startupSeconds', 'buildSeconds', 'verifySeconds', 'installSeconds', 'sweepSeconds')) + rust_build
            else:
                gpu['tableDifference'] = _table_difference(expected, data, keys)
        except Exception as exc:
            gpu['error'] = f'{type(exc).__name__}: {exc}'
        result['rows'] = [dict(info, off=off, rust=_pool_diff(off, rust[i]),
                               cuda=_pool_diff(off, cuda[i]) if cuda is not None else None)
                          for i, ((info, _), off) in enumerate(zip(cases, baseline))]
        result['exactReplays'] = {kind: sum(row[kind] is not None and row[kind]['exact'] for row in result['rows'])
                                  for kind in ('rust', 'cuda')}
        result['passed'] = (len(cases) == 100 and bool(keys) and bool(gpu.get('tableExact'))
                            and gpu.get('hits', 0) > 0 and result['rust']['hits'] > 0
                            and all(count == len(cases) for count in result['exactReplays'].values()))
    finally:
        core.bake_pool_stop()
        search_combat._REPLAYS.clear()
    (args.output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')) + '\n',
                                              encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, ensure_ascii=False))
    return 0 if result['passed'] else 1


ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--nvrtc-dir', type=Path, required=True)
ap.add_argument('--output', type=Path, required=True)
ap.add_argument('--pool-prefixes', action='store_true', help='Benchmark real capped-status prefix tables')
args = ap.parse_args()
args.output.mkdir(parents=True,exist_ok=True)
if args.pool_prefixes:
    raise SystemExit(_run_pool_prefixes(args))
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
