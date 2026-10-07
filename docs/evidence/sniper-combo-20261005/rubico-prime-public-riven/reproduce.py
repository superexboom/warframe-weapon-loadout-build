import sys, json
from pathlib import Path
sys.path.insert(0,'.')
import app
from tools.audit_riven_board_builds import wfsim
from tools.compare_archgun_board_builds import registry, exact_record, public_riven_spec, resolved_riven_payload
from tools.validate_sniper_mechanics import fight, local
import wfarsenal.sniper as sn
app._disable_analysis_statics_persistence()
W=Path(r'C:/Users/SuperExboom/Documents/WF-Riven-Portable/.local/wfsim-live-20261004')
out=Path(sys.argv[1]); out.mkdir(parents=True)
board=json.loads(Path('.local/wfsim-board-index.json').read_text(encoding='utf-8'))
mods=registry(W/'data/mods'); weapons=registry(W/'data/weapons')
row=next(r for r in board['rubico_prime'] if r.get('riven') and r.get('benchmark')=='standard_single_target')
weapon=exact_record(weapons['rubico_prime'],app.EXPORTS['weapons'])
spec=public_riven_spec(row)
kind=app.optimizer._weapon_type(None,app.optimizer.resolve_record(app.EXPORTS['weapons'],weapon['path'],kind='weapon'))
plain=[m for m in row['mods'] if m!='riven']
riven=resolved_riven_payload(spec,wfsim(W,out,'riven',[['/api/riven',dict(weapon='rubico_prime',**spec)]])[0],len(plain),kind)
lm=[dict(path=(p:=exact_record(mods[m],app.EXPORTS['mods'])['path']),rank=app.MANUAL_MODS_BY_PATH[p]['maxRank'],slot=i) for i,m in enumerate(plain)]
calls=[];res=[]
for level in (170,9999):
    on=local(weapon['path'],lm,riven,level,0)['kpm']
    real=sn.reference; sn.reference=lambda:{'weapons':{}}
    off=local(weapon['path'],lm,riven,level,0)['kpm']; sn.reference=real
    res.append((level,off,on)); calls.append(['/api/simulate',fight('rubico_prime',plain+['riven:board'],level,0,100,spec)])
for (level,off,on),ref in zip(res,wfsim(W,out,'simulate',calls)):
    print(f'L{level}: local before {off:.3f}  after {on:.3f}  wfsim {ref["score"]*60/ref["duration"]:.3f}')
print(row['mods'], spec)
