from pathlib import Path
import sys,os,json
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));os.environ['WF_ANALYZER_SERIAL']='1'
import app
from wfarsenal import optimizer as o,native_replay as n,search_combat
from wfarsenal.damage import Scenario,ModEffect
from tools.gpu_bake.backend import DirectBatch
core=n.wfcore;original=core.trajectory
rows=[]
def capture(config,helper):
    try:
        stream,hp,window=core.direct_bake_stream(config,helper)
        rows.append((stream,hp,window))
        print('compiled stream',len(stream),hp,window)
    except core.NativeUnsupported as e:print('rejected',e)
    return original(config,helper)
core.trajectory=capture
for status in (False,True):
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Lato')
    weapon=o._select_fire_mode(weapon,0,weapon_type='pistol')[0]
    if not status:weapon=dict(weapon,procChance=0.)
    scenario=Scenario(trigger_policy='emergent')
    effects=[] if status else [ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',-1.)]
    stats=o.apply_mods(weapon,effects,scenario=scenario)
    print('stats',stats.status_chance,stats.victim_low_health_multiplier)
    o._bind_combat_inputs(stats,weapon,(),effects,scenario)
    context=dict(target=dict(health=3000.,shield=0.,overguard=0.,armour=200.,baseLevel=1),level=1,windowSeconds=30.,headshotChance=0.)
    result=search_combat.window(stats,context,score_only=True)
    print('reference',result)
    if rows:
        predicted=DirectBatch.cpu(rows[-1:])[0]
        print('stream score',predicted)
        assert predicted==(result['killsPerMinute'],result['windowDps'],result['totalWindowDamage'])
        rows.clear()
