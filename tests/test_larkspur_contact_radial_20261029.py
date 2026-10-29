"""Independent contact-death candidate admission and actual model trajectories."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from tools import import_larkspur_contact_radial as importer
from tools.import_native_secondary_payloads import merge_patch
ROOT=Path(__file__).resolve().parents[1]
CASE=ROOT/'.local/delivery/ranged-implementation-20261029/native-payloads'

@pytest.fixture
def source():
    data=json.loads((CASE/'larkspur-resolved-source.json').read_bytes());objects={};parents={}
    for spec in importer.LARKSPUR_SPECS:
        v=data[spec['path']];objects[spec['path']]=v['weapon'];objects[spec['projectile']]=v['projectile']
        parents.update({r['path']:r['parent'] for r in v['sources']})
    class Packages:
        entities={p:(a,SimpleNamespace(attr=None)) for p,a in parents.items()}
        def resolve(self,path):return deepcopy(objects[path])
        def parent(self,path):return parents.get(path)
        def locate(self,owner,ref):
            if not ref:return None
            if ref.startswith('/'):return ref
            return owner.rsplit('/',1)[0]+'/'+ref
    rows=json.loads((ROOT/'data/export/2026.08.13.13.24/weapons.json').read_bytes())['data']
    return Packages(),objects,rows

@pytest.mark.parametrize('spec',importer.LARKSPUR_SPECS,ids=lambda x:x['path'].rsplit('/',1)[-1])
def test_contact_candidate_keeps_native_amount_and_uses_zero_post_hit_delay(source,spec):
    pkg,_,rows=source;row=next(r for r in rows if r['path']==spec['path'])
    entry=importer.make_profile(pkg,row,spec);part=entry['radials'][0]
    assert part['damage']=={'blast':800.,'radiation':800.}
    assert part['impact_delay_seconds']==0. and part['takes_multishot']
    assert part['emissionContract']['packetsPerSpawnedProjectile']==1
    assert part['sourceDamageUpgrade'].startswith('WEAPON_DAMAGE_AMOUNT')
    assert part['crit_multiplier']==2.2 and part['status_chance']==.34
    assert not any('approximated-1s' in x for x in entry['unmodeled'])
    assert 'plan118/11c are not crit proof' in entry['nativeEvidence']['critFields']

@pytest.mark.parametrize('field,value',[('ExplodeOnImpact',1),('ExplodeOnLifeExpired',1),('Embed',1),('MaxLife',2),('MaxLifeVariance',.5),('BounceOnAvatars',1),('DamageUpgradeTypes',[])])
def test_rejects_changed_contact_or_life_contract(source,field,value):
    pkg,objects,rows=source;spec=importer.LARKSPUR_SPECS[0];objects[spec['projectile']][field]=value
    with pytest.raises(ValueError):importer.make_profile(pkg,next(r for r in rows if r['path']==spec['path']),spec)

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('spec',importer.LARKSPUR_SPECS,ids=lambda x:x['path'].rsplit('/',1)[-1])
@pytest.mark.parametrize('multishot',[1.,2.,3.])
def test_real_resolver_and_replay_contact_adds1600_per_projectile_once(source,spec,multishot,native,monkeypatch):
    import app
    from wfarsenal import manual_combat,native_replay
    from wfarsenal.damage import Scenario,ModEffect
    from wfarsenal.combat_replay import replay
    pkg,_,rows=source;patch=importer.build_patch(pkg,rows);joined=merge_patch(manual_combat.reference(),patch)
    monkeypatch.setattr(manual_combat,'reference',lambda:joined);monkeypatch.setattr(native_replay,'ENABLED',native)
    row=deepcopy(next(r for r in app.EXPORTS['weapons'] if r['path']==spec['path']))
    fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_ITERATIONS','SET',multishot)]
    fight=manual_combat.prepare(dict(weapon=row,fire_mode=1,effects=fx,scenario=Scenario()),[],[])
    direct,part=fight['resolve']('selected',{},0.)
    assert direct.total_damage==840. and part.total_damage==1600.
    assert direct.multishot==part.multishot==multishot
    assert part._impact_delay==0.
    native_before=native_replay.STATS['native']
    r=replay(direct,dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1),attacks_per_second=direct.fire_rate,window_seconds=.2,combat=fight,collect_timeline=False)
    assert r['shots']>0
    if native:assert native_replay.STATS['native']>native_before
    # Existing per-type1/32 quantization turns840 direct into866.25;1600 radial is exact.
    assert r['directWindow']==pytest.approx(r['shots']*2466.25*multishot)
    assert set(importer.BOUNDS)<=set(fight['unsupported'])

def test_actual_source_damage_multiplier_applies_once_to_independent_packet(source,monkeypatch):
    import app
    from wfarsenal import manual_combat
    from wfarsenal.damage import Scenario,ModEffect
    pkg,_,rows=source;joined=merge_patch(manual_combat.reference(),importer.build_patch(pkg,rows))
    monkeypatch.setattr(manual_combat,'reference',lambda:joined)
    spec=importer.LARKSPUR_SPECS[0];row=next(r for r in app.EXPORTS['weapons'] if r['path']==spec['path'])
    f=manual_combat.prepare(dict(weapon=row,fire_mode=1,effects=[ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.)],scenario=Scenario()),[],[])
    d,p=f['resolve']('selected',{},0.);assert d.total_damage==1680.;assert p.total_damage==3200.

def test_merge_preserves_other_modes_and_root_fields(source):
    pkg,_,rows=source;spec=importer.LARKSPUR_SPECS[0];p=spec['path']
    before={'auditedAttacks':{p:{'keep':1,'modes':{'0':{'keep':2},'1':{'charge':{'keep':3}}}},'/other':{'keep':4}}}
    after=merge_patch(before,importer.build_patch(pkg,rows))
    assert after['auditedAttacks'][p]['keep']==1
    assert after['auditedAttacks'][p]['modes']['0']=={'keep':2}
    assert after['auditedAttacks'][p]['modes']['1']['charge']=={'keep':3}
    assert after['auditedAttacks']['/other']=={'keep':4}
