from __future__ import annotations
import argparse, hashlib, json, math, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from tools.compare_archgun_board_builds import BATCH_JS, registry, ELEMENTS

# Audited from StugEvoTier1A/2B/3C + their exported effects and WFSim YAML.
# Explicit mapping: no name-based substitutions or implicit reference defaults.
EVOLUTIONS = {'stug': {'tier2': {'2-1': 'stug_blazing_barrel'},
    'tier3': {'3-2': 'stug_swift_deliverance'},
    'tier4': {'4-3': 'stug_elemental_dominance'}}}

def exact_index(records):
    result = {}
    for row in records.values():
        path = row.get('internal_name')
        if path:
            result.setdefault(path, []).append(row)
    return result

def ranked_card(item, index):
    rows = index.get(item['path'], [])
    if len(rows) != 1:
        raise ValueError('missing or ambiguous exact reference path: ' + item['path'])
    row = rows[0]
    rank = item['rank']
    if not isinstance(rank, int) or not 0 <= rank <= row['max_rank']:
        raise ValueError('reference rank differs: ' + item['path'])
    return row['id'] if rank == row['max_rank'] else row['id'] + '@' + str(rank)

def reference_request(payload, weapons, mods, arcanes, runs):
    rows = weapons.get(payload['weapon'], [])
    rows = [w for w in rows if w.get('default_form') or w.get('form', 'base') == 'base']
    if len(rows) != 1 or payload.get('fireMode', 0) != 0:
        raise ValueError('unmapped exact weapon form')
    weapon = rows[0]
    if payload.get('externalBuffs') or payload.get('riven') or payload.get('incarnonCycle'):
        raise ValueError('unmapped external, riven or cycle state')
    evolution_ids = []
    choices = payload.get('incarnonChoices') or {}
    if choices:
        mapping = EVOLUTIONS.get(weapon['id'], {})
        for tier, pick in sorted(choices.items()):
            if pick not in mapping.get(tier, {}):
                raise ValueError('unmapped evolution ' + str((weapon['id'], tier, pick)))
            evolution_ids.append(mapping[tier][pick])
    q = dict(weapon=weapon['id'], mode=weapon.get('form', 'base'),
        mods=[ranked_card(m, mods) for m in sorted(payload['mods'], key=lambda m: m['slot'])],
        arcane=[ranked_card(a, arcanes) for a in payload.get('arcanes', [])],
        evolutions=evolution_ids, evolutions_as_given=True, enemy='thrax_centurion',
        level=payload['level'], steel_path=payload['steelPath'],
        headshot_pct=payload['headshotChance'] * 100, aiming=payload['aiming'],
        duration=30, runs=runs, seed=12648430, infinite_ammo=True, ammo_drops=False,
        spectral_form=False, eximus=False, assume_max=False, frenzy=False,
        player_at=[0, 0], target_at=[0, app._scenario_input(payload, 'distance')])
    if payload.get('exilus'):
        q['mods'].append(ranked_card(payload['exilus'], mods))
    if payload.get('innateElement'):
        q.update(valence_element={v: k for k, v in ELEMENTS.items()}[payload['innateElement']],
                 valence_bonus=payload['innateElementValue'])
    return q, weapon.get('unmodeled', [])

def main():
    ap=argparse.ArgumentParser(description='Replay exact automatic builds against frozen WFSim; unmapped inputs fail closed.')
    ap.add_argument('--wfsim', type=Path, required=True)
    ap.add_argument('--builds', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--runs', type=int, default=500)
    a=ap.parse_args()
    if a.output.exists() or a.runs < 1:ap.error('new output directory and positive runs required')
    a.output.mkdir(parents=True);app._disable_analysis_statics_persistence()
    weapons=exact_index(registry(a.wfsim/'data/weapons'))
    mods=exact_index(registry(a.wfsim/'data/mods'))
    arcs=exact_index(registry(a.wfsim/'data/arcanes'))
    def save(name, obj):(a.output/name).write_text(json.dumps(obj, ensure_ascii=False, indent=2)+chr(10), encoding='utf-8')
    inputs=json.loads(a.builds.read_text(encoding='utf-8'));rows=[];pending=[];requests=[]
    for row in inputs:
        c=dict(name=row['name'], automaticKpm=row.get('automatic'), originalFingerprint=row.get('inputFingerprint'))
        rows.append(c)
        try:
            payload=row['manualRequest'];q,limits=reference_request(payload,weapons,mods,arcs,a.runs)
            manual=app.simulate_manual_payload(payload)
            kpm=manual['benchmarkTimeline']['killsPerMinute']
            c.update(request=q, manualRequest=payload, manualKpm=kpm, localUnsupported=manual.get('unsupported', []),
                referenceLimitations=limits, currentManualMatchesAutomatic=math.isclose(kpm,row['automatic'],rel_tol=1e-9,abs_tol=1e-9))
            pending.append(c);requests.append(q)
        except (ValueError, KeyError, app.SimulationError) as e:c['mappingError']=str(e)
    save('requests.json',requests);(a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    for c,ref in zip(pending,json.loads((a.output/'responses.json').read_text(encoding='utf-8')),strict=True):
        if not ref.get('ok'):c['referenceError']=ref;continue
        kpm=ref['score']*60/ref['duration']
        c.update(referenceKpm=kpm,referenceKpmSe=ref.get('score_se',0)*60/ref['duration'],
            deltaPercent=(c['manualKpm']/kpm-1)*100 if kpm else None)
        print(c['name'],c['manualKpm'],kpm,c['deltaPercent'],flush=True)
    rel=json.loads((a.wfsim/'site/release.json').read_text(encoding='utf-8'))
    save('comparison.json',dict(cases=rows,localInputFingerprint=app._analysis_inputs_fingerprint(),
        sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),
        release=rel,wasmSha256=hashlib.sha256((a.wfsim/'site/pkg'/('wfsim_wasm_bg.'+rel['wasm']+'.wasm')).read_bytes()).hexdigest(),
        buildInputSha256=hashlib.sha256(a.builds.read_bytes()).hexdigest(),toolSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        contract='Actual automatic builds, exact internal paths and ranks, explicit evolutions; 30s Thrax, level/Steel Path/aim/headshot chance/distance from each saved request. Partial mechanics remain recorded, not accepted as parity.'))
    if any(c.get('mappingError') or c.get('referenceError') or not c.get('currentManualMatchesAutomatic') for c in rows):
        print(json.dumps([{k:c.get(k) for k in ('name','mappingError','referenceError')} for c in rows if c.get('mappingError') or c.get('referenceError')],ensure_ascii=False))
        raise SystemExit(1)

if __name__=='__main__':main()
