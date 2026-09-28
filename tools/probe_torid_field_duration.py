"""Separate Torid field-duration events from target-pool nonlinearities using fixed builds."""
from __future__ import annotations
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import app
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.compare_generated_builds import reference_request,exact_index,reference_identity_matches
from tools.compare_archgun_board_builds import registry,BATCH_JS
TORID='/Lotus/Weapons/ClanTech/Bio/BioWeapon'

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ('builds','wfsim','output'):ap.add_argument('--'+name,type=Path,required=True)
    a=ap.parse_args()
    if a.output.exists():ap.error('preserve previous evidence; use a new output directory')
    rows=json.loads(a.builds.read_bytes())
    p=next(r['manualRequest'] for r in rows if r['manualRequest']['weapon']==TORID and r['manualRequest']['fireMode']==0)
    if p.get('arcanes') or p.get('incarnonCycle'):ap.error('probe requires non-cycle base build without arcanes')
    wi=exact_index(registry(a.wfsim/'data/weapons'));mi=exact_index(registry(a.wfsim/'data/mods'));ai=exact_index(registry(a.wfsim/'data/arcanes'))
    q,_=reference_request(p,wi,mi,ai,1000)
    ctx=app._manual_resolve_sim_context(p);common=ctx['common'];engine={}
    app.simulate(**common,hit_location='body',passive_effects=ctx['build_passives'](None)['passive_effects'],engine_context_sink=engine)
    mods=[(app.optimizer.resolve_record(app.EXPORTS['mods'],m['path'],kind='mod'),m['rank'],None) for m in common['mods']]
    # The second target retains status mechanics but cannot reach a pool break.
    custom=dict(id='audit_pool',name='Audit pool',synthetic=True,scaling_faction='unaffiliated',stats=dict(base_level=1,health=1e12,shield=0,armor=0,overguard=1e12),body_parts=[dict(name='body',multiplier=1,is_head=False,crit_bonus=False)])
    outcomes=[];requests=[]
    for neutral in (False,True):
        target=dict(health=1e12,shield=0,armour=0,overguard=1e12,baseLevel=1,faction='',factionResistance='RK_NEUTRAL') if neutral else app.MANUAL_ENEMIES_BY_PATH[p['enemy']]
        level=1 if neutral else p['level'];steel=False if neutral else p['steelPath']
        for enabled in (True,False):
            c=prepare(engine,mods,[],incarnon_choices=p['incarnonChoices'],affinity_target=target,level=level)
            if not enabled:c['fieldDurationOnEmptyReload']=None
            st,_=c['resolve']('selected',{})
            result=replay(st,target,combat=c,trigger_sources=c['trigger_sources'],attacks_per_second=st.sustained_attack_rate,window_seconds=30,level=level,steel_path=steel,headshot_chance=0)
            req={**q,'evolutions':[e for e in q['evolutions'] if enabled or e!='torid_renewed_horror']}
            if neutral:req.update(enemy='audit_pool',custom_enemies=[custom],level=1,steel_path=False)
            requests.append(req)
            outcomes.append(dict(target='neutral-unbroken-overguard' if neutral else 'original-thrax',enabled=enabled,local={k:result[k] for k in ('killsPerMinute','shots','reloads','totalWindowDamage','directWindow','dotWindow','procCounts')},referenceRequest=req))
    a.output.mkdir(parents=True)
    def save(name,obj):(a.output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    save('requests.json',requests);(a.output/'batch.mjs').write_text(BATCH_JS,encoding='utf-8')
    subprocess.run(['node',str(a.output/'batch.mjs'),str(a.wfsim),str(a.output/'requests.json'),str(a.output/'responses.json')],check=True)
    for row,response in zip(outcomes,json.loads((a.output/'responses.json').read_bytes()),strict=True):
        if not response.get('ok') or not reference_identity_matches(response,row['referenceRequest']):raise ValueError(response)
        row['reference']={k:response.get(k) for k in ('score','score_se','dps','shots','reloads','field_ticks','damage_sources','panel','procs','target')}
        row['damageDeltaPercent']=(row['local']['totalWindowDamage']/(response['dps']*response['duration'])-1)*100
        print(row['target'],row['enabled'],'delta',row['damageDeltaPercent'],'shots',row['local']['shots'],response['shots'],flush=True)
    release=json.loads((a.wfsim/'site/release.json').read_bytes())
    save('summary.json',dict(cases=outcomes,manualRequest=p,localFingerprint=app._analysis_inputs_fingerprint(),sourceCommit=subprocess.check_output(['git','-C',str(a.wfsim),'rev-parse','HEAD'],text=True).strip(),release=release,wasmSha256=hashlib.sha256((a.wfsim/'site/pkg'/('wfsim_wasm_bg.'+release['wasm']+'.wasm')).read_bytes()).hexdigest(),contract='Fixed-build diagnostic: disable only Renewed Horror on both engines; neutral target prevents pool transitions. Not a new automatic build or a game measurement.'))
if __name__=='__main__':main()
