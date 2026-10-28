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


def test_mausolon_heavy_alt_has_its_ground_radial_not_space_values():
    fight,direct,radial=parts('Mausolon',1)
    assert direct.total_damage==pytest.approx(1500.)
    assert radial.damage_types=={'DT_FIRE':4500.}
    assert radial.status_chance==pytest.approx(.5)
    assert radial.crit_chance==pytest.approx(.5)
    assert fight['cycle']['killCharged']
    assert fight['cycle']['hits']==5


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
