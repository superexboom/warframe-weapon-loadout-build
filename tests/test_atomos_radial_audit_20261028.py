"""Atomos Incarnon: one 100 Impact hit and one native 450 Blast explosion."""
import json
from copy import deepcopy
import pytest
import app
from wfarsenal.damage import Scenario,ModEffect,damage_against
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay
from tools.import_projectile_components import candidates,build_entry


def combat(effects=()):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Atomos'))
    weapon['isIncarnonForm']=True
    fight=prepare(dict(weapon=weapon,fire_mode=1,effects=list(effects),scenario=Scenario()),[],[])
    direct,radial=fight['resolve']('selected',{},0)
    return fight,direct,radial


def test_native_radial_is_not_omitted_or_double_counted_as_embed_death():
    fight,direct,radial=combat()
    assert direct.total_damage==pytest.approx(100.)
    assert radial.total_damage==pytest.approx(450.)
    assert radial.damage_types=={'DT_EXPLOSION':450.}
    assert radial.status_chance==pytest.approx(.41)
    assert radial.crit_chance==pytest.approx(.18)
    assert radial.crit_multiplier==pytest.approx(384.*32./4095.)
    assert radial.radial_only
    assert not getattr(radial,'_additional_radials',[])
    assert not any('radial-payload-unmodeled' in x for x in fight['unsupported'])


def test_explosion_inherits_multishot_but_not_weakpoint_damage():
    _,_,base=combat()
    _,_,multi=combat([ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.2)])
    assert multi.multishot/base.multishot==pytest.approx(2.2)
    enemy=dict(health=1e12,armour=0,shield=0,overguard=0,baseLevel=1,
               hitProxies=[dict(part='HEAD',damageAtten=3.,criticalMultiplier=2.)])
    assert damage_against(base,enemy,hit_location='head')['perShot']==damage_against(base,enemy)['perShot']


@pytest.mark.parametrize('native',[False,True])
def test_one_unmodded_shot_contains_independently_computed_direct_and_radial(native,monkeypatch):
    monkeypatch.setattr(native_replay,'ENABLED',native)
    if native and native_replay.wfcore is None:pytest.skip('native core unavailable')
    fight,direct,radial=combat()
    enemy=dict(health=1e12,armour=0,shield=0,overguard=0,baseLevel=1)
    result=replay(direct,enemy,attacks_per_second=direct.fire_rate,window_seconds=.001,
                  combat=fight,collect_timeline=False)
    # Independent scalar native payload: 100+450, 18% crit; native
    # 12-bit base multiplier serialization rounds x3 to 384 * 32/4095.
    assert result['directWindow']==pytest.approx((100.+450.)*(1.+.18000001*(384.*32./4095.-1.)))
    assert result['shots']==1


@pytest.mark.parametrize('form',['incarnon','charged','uncharged','alt_fire'])
def test_importer_resolves_subform_identity_from_transforms_from(tmp_path,form):
    folder=tmp_path/'data/weapons/secondary';folder.mkdir(parents=True)
    (folder/'base.yaml').write_text('id: base\ninternal_name: /weapon\n')
    (folder/'evo.yaml').write_text('id: evo\nform: '+form+'\ntransforms_from: base\nattack:\n  radial:\n    damage: {blast: 450}\n')
    rows=list(candidates(tmp_path))
    assert len(rows)==1 and rows[0][1]['internal_name']=='/weapon'


def test_imported_incarnon_radial_is_admitted_in_incarnon_mode(tmp_path):
    class Packages:
        def resolve(self,path):
            if path=='/projectile':return dict(ExplosiveAttack=dict(Amount=450.,ProcChance=.41),
                CriticalChance=.18,CriticalMultiplier=3,DamageRadius=7.9,ExplosionFallOff=.8)
            return {}
        def _path_to_file(self,path):return tmp_path/(path.lstrip('/')+'.json')
    source=tmp_path/'form.yaml';source.write_text('fixture')
    row=dict(path='/weapon',nameEn='Example',fireModes=[dict(index=0,isIncarnonForm=True,multishot=1,
        damage=dict(types={'DT_IMPACT':100.},projectile='/projectile'))])
    radial=dict(damage={'blast':450},status_chance=.41)
    entry=build_entry(source,{'form':'incarnon'},{},radial,row,0,Packages(),tmp_path)
    assert entry['allowIncarnon'] is True
    assert entry['radials'][0]['damage']=={'blast':450.}
