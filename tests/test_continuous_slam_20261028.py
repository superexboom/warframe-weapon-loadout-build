"""Continuous hammer slams: requested cadence, actual combo, route identity."""
import pytest
import app
from wfarsenal import melee_sequence as ms, native_replay, combat_replay, optimizer
from wfarsenal.damage import Scenario, ModEffect
from wfarsenal.manual_combat import prepare


def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)


@pytest.mark.parametrize('name',['Fragor Prime','Magistar','Arca Titron'])
def test_continuous_slam_is_a_distinct_hammer_route_without_animation_recovery(name):
    schedule=ms.build_schedule(weapon(name),'slamContinuous')
    assert schedule['route']=='slamContinuous'
    assert schedule['slamHeight']==0.
    assert sum(s['anim'] for s in schedule['segments'])==0.
    hit=[s['hit'] for s in schedule['segments'] if s.get('hit')][0]
    assert hit['heavy'] and hit['consumesCombo'] and hit['comboMultiplier']
    assert hit['comboHits']==0.
    for speed in (.5,1.,4.):
        loop=ms.Loop(schedule)
        assert [loop.next(speed)[1] for _ in range(5)]==pytest.approx([.2]*5)
    assert '连续震地' in ms.route_note(schedule)
    assert ms.default_route(weapon(name))=='slamBullet'


def test_nonhammer_cannot_silently_use_the_continuous_hammer_contract():
    with pytest.raises(ValueError,match='requires a hammer'):
        ms.build_schedule(weapon('Nikana Prime'),'slamContinuous')


def test_continuous_slam_keeps_arca_titron_slam_passive_enabled():
    from tests.test_weapon_passives import _melee
    combat,_=_melee('Arca Titron','slamContinuous',False,health=6000.)
    sources=[s for s in combat['trigger_sources'] if 'slamContinuous' in s.get('meleeRoutes',[])]
    assert sources and any(s['perEvent']>0 for s in sources)


def test_route_validation_and_cache_identity_include_continuous_slam():
    assert Scenario(combat_state={'meleeRoute':'slamContinuous'}).combat_state['meleeRoute']=='slamContinuous'
    common=('/w',(),0,'viral','fast',1.,60,'killsPerMinute')
    a=optimizer._statics_cache_key(*common,{'enemy':'/e','melee':{'route':'slamBullet'}})
    b=optimizer._statics_cache_key(*common,{'enemy':'/e','melee':{'route':'slamContinuous'}})
    assert a!=b
