"""Confirmed native radial payloads omitted by earlier import filters."""
from copy import deepcopy
import pytest
import app
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay


def parts(name,mode):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name))
    fight=prepare(dict(weapon=weapon,fire_mode=mode,effects=[],scenario=Scenario()),[],[])
    direct,radial=fight['resolve']('selected',{},0)
    return fight,direct,radial


def test_mausolon_heavy_alt_has_its_ground_radial_not_space_values(monkeypatch):
    fight,direct,radial=parts('Mausolon',1)
    assert direct.total_damage==pytest.approx(1500.)
    assert radial.damage_types=={'DT_FIRE':4500.}
    assert radial.status_chance==pytest.approx(.5)
    assert radial.crit_chance==pytest.approx(.5)
    assert fight['cycle']['killCharged']
    assert fight['cycle']['hits']==5
    assert fight['cycle']['damageScale']==5.
    from wfarsenal.damage import ModEffect
    from wfarsenal.event_profiles import base_profile
    w=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Mausolon')
    fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
        ModEffect('WEAPON_FIRE_ITERATIONS','SET',3.),ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.5)]
    primary=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=Scenario()),[],[])
    st,part=primary['resolve']('selected',{},1.)
    assert part.total_damage==234.  # 72*2 + source180*.5
    assert part.multishot==3. and part.delayed_radial_hit_event and not part.radial_victim_crit
    alt=prepare(dict(weapon=w,fire_mode=1,effects=fx,scenario=Scenario()),[],[])
    assert alt['resolve']('selected',{},1.)[1].total_damage==9750.  # 4500*2 + source1500*.5
    assert base_profile(w,0)['radials'][0]['nativeRoute']!=base_profile(w,1)['radials'][0]['nativeRoute']
    primary['resolve']=lambda *_:(st,part)
    sources=[dict(id='hit',label='hit',kind='on-hit',maxStacks=100.,duration=10.,perEvent=1.)]
    monkeypatch.setattr(native_replay,'ENABLED',True);monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    reference=replay(st,target,attacks_per_second=.001,window_seconds=.01,combat=primary,trigger_sources=sources,collect_timeline=True)
    result=replay(st,target,attacks_per_second=.001,window_seconds=.01,combat=primary,trigger_sources=sources,collect_timeline=False)
    assert result['directWindow']==pytest.approx(reference['directWindow'])
    assert reference['triggerSeries'][0]['series'][-1]==6.  # three rays and three radial packets
    assert native_replay.STATS['native']>before
    # Five controlled primary kills exercise the real unlock cycle. Alt raw
    #1500/4500 stay unscaled in preparation; only the shot pays state factor5.
    from copy import copy
    cycle=prepare(dict(weapon=w,fire_mode=1,effects=fx[:3],scenario=Scenario()),[],[])
    original=cycle['resolve']
    def resolve(form,*args):
        direct,radial=original(form,*args);direct=copy(direct);direct.fire_rate=2.
        direct._charge_time=0.;direct.multishot=1. if form=='base' else 3.
        if form=='base':
            direct.damage_types={'DT_IMPACT':2e8};direct.dot_base_damage=2e8
            radial=None
        return direct,radial
    cycle['resolve']=resolve;cycle['baseFireRate']=cycle['incarnonFireRate']=2.
    base,_=resolve('base',{},0.)
    result=replay(base,{**target,'health':1e8},attacks_per_second=2.,window_seconds=2.501,
        combat=cycle,collect_timeline=False)
    assert result['shots']==6 and result['killEvents']==5
    assert result['directWindow']==pytest.approx(5e8+90000.)


def test_riot_embedded_and_ordinary_death_are_one_immediate_explosion():
    fight,direct,radial=parts('Riot-848',0)
    assert direct.damage_types=={'DT_PUNCTURE':12.}
    assert radial.damage_types=={'DT_EXPLOSION':48.}
    assert getattr(radial,'_impact_delay',0.)==0.
    assert not getattr(radial,'_additional_radials',[])
    assert radial.radial_only


@pytest.mark.parametrize('native',[False,True])
def test_riot_zero_delay_hit_applies_60_base_damage_once(native,monkeypatch):
    monkeypatch.setattr(native_replay,'ENABLED',native)
    if native and native_replay.wfcore is None:pytest.skip('native core unavailable')
    fight,direct,_=parts('Riot-848',0)
    enemy=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    result=replay(direct,enemy,attacks_per_second=direct.fire_rate,window_seconds=.001,
                  combat=fight,collect_timeline=False)
    # 2.2 is serialized to the nearest 32/4095 step (282).
    expected=(12.+48.)*(1.+.25999999*(282.*32./4095.-1.))
    assert result['directWindow']==pytest.approx(expected)
    assert result['shots']==1
