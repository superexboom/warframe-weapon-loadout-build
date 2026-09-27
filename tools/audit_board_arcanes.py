from pathlib import Path
import argparse,hashlib,json,math,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from tools.compare_archgun_board_builds import BATCH_JS,registry,exact_record,local_replay

def main():
    ap=argparse.ArgumentParser(description='Swap every reference-compatible arcane onto a fixed public build; preserve unsupported rows.')
    ap.add_argument('--wfsim',type=Path,required=True);ap.add_argument('--comparison',type=Path,nargs='+',required=True)
    ap.add_argument('--weapons',nargs='+');ap.add_argument('--output',type=Path,required=True);ap.add_argument('--runs',type=int,default=250)
    a=ap.parse_args()
    if a.output.exists():ap.error('output exists; preserve evidence')
    if a.runs<1:ap.error('runs must be positive')
    a.output.mkdir(parents=True);app._disable_analysis_statics_persistence()
    def save(name,data):
        (a.output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    save('empty.json',{})
    subprocess.run(['node',str(ROOT/'tools/run_reference_wasm.mjs'),str(a.wfsim),'/api/meta',str(a.output/'empty.json'),str(a.output/'meta.json')],check=True)
    meta=json.loads((a.output/'meta.json').read_text(encoding='utf-8'));wm={w['id']:w for w in meta['weapons']}
    arcanes=registry(a.wfsim/'data/arcanes');selected={}
    for f in a.comparison:
        for c in json.loads(f.read_text(encoding='utf-8'))['cases']:
            if not a.weapons or c['weapon'] in a.weapons:selected.setdefault(c['weapon'],c)
    if a.weapons and set(a.weapons)-selected.keys():ap.error('requested weapon missing from inputs')
    rows=[];requests=[]
    for wid,c in selected.items():
        w=app.optimizer.resolve_record(app.EXPORTS['weapons'],c['manualPayload']['weapon'],kind='weapon')
        for aid in ['none',*wm[wid]['arcanes']]:
            q={**c['referenceRequest'],'arcane':[] if aid=='none' else [aid],'runs':a.runs}
            p={**c['manualPayload'],'arcanes':[]}
            row=dict(id=wid+'--'+aid,weapon=wid,arcane=aid,boardRowIndex=c['boardRowIndex'],request=q,manualRequest=p,
                     buildCatalogBlockers=c.get('catalogBlockers',[]),status='pending')
            try:
                if aid!='none':
                    r=exact_record(arcanes[aid],app.EXPORTS['arcanes'])
                    p['arcanes']=[dict(path=r['path'],rank=r['maxRank'])]
                    row['localArcanePath']=r['path']
                    row['nativeCompatible']=app.optimizer._arcane_matches_weapon(r,w)
                    if not row['nativeCompatible']:raise ValueError('native-compatibility-mismatch')
                    if r['path'] not in app.MANUAL_ARCANES_BY_PATH:raise ValueError('arcane-not-in-production-catalog')
                local=local_replay(p,duration=q['duration'])
                ev=local['replay'];row.update(localKpm=ev['killsPerMinute'],localUnsupported=local['unsupported'],
                    replayUnsupported=ev['unsupported'],localSkipped=local['skipped'],status='compared-partial')
                if not c.get('catalogBlockers'):
                    manual=app.simulate_manual_payload(p)
                    row['manualKpm']=manual['benchmarkTimeline']['killsPerMinute']
                    row['manualMatchesKernel']=math.isclose(row['manualKpm'],row['localKpm'],rel_tol=1e-9,abs_tol=1e-9)
                    row['manualUnsupported']=manual.get('unsupported',[])
            except (ValueError,KeyError,app.SimulationError) as e:row.update(status='local-unavailable',localError=str(e))
            rows.append(row);requests.append(q)
        print(wid,len(wm[wid]['arcanes'])+1,'arcane cases',flush=True)
        save('progress.json',rows)
    save('requests.json',requests);(a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    refs=json.loads((a.output/'responses.json').read_text(encoding='utf-8'));baselines={}
    for row,ref in zip(rows,refs,strict=True):
        if ref.get('ok'):
            row.update(referenceKpm=ref['score']*60/ref['duration'],referenceKpmSe=ref.get('score_se',0)*60/ref['duration'])
            if row.get('localKpm') is not None:row['deltaPercent']=100*(row['localKpm']/row['referenceKpm']-1) if row['referenceKpm'] else None
        else:row.update(status='reference-error',referenceError=ref)
        if row['arcane']=='none':baselines[row['weapon']]=row
    for row in rows:
        b=baselines[row['weapon']]
        for k in ('local','reference'):
            if row.get(k+'Kpm') is not None and b.get(k+'Kpm'):row[k+'GainPercent']=100*(row[k+'Kpm']/b[k+'Kpm']-1)
    release=json.loads((a.wfsim/'site/release.json').read_text(encoding='utf-8'))
    save('comparison.json',dict(localInputFingerprint=app._analysis_inputs_fingerprint(),
        toolSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        inputs=[dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in a.comparison],
        sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),release=release,
        wasmSha256=hashlib.sha256((a.wfsim/'site/pkg'/('wfsim_wasm_bg.'+release['wasm']+'.wasm')).read_bytes()).hexdigest(),
        cases=rows,contract='One fixed public build per weapon, swap every reference-listed weapon arcane independently at max rank; external/combo/frame-gated mechanics remain explicitly unresolved. No universal acceptance claim.'))
    print(json.dumps(dict(cases=len(rows),localUnavailable=sum(r['status']=='local-unavailable' for r in rows),referenceErrors=sum(r['status']=='reference-error' for r in rows),manualMismatches=[r['id'] for r in rows if r.get('manualMatchesKernel') is False]),ensure_ascii=False))
if __name__=='__main__':main()
