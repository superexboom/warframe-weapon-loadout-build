"""Native/Python parity on repaired projectile clocks and sniper rules."""
from copy import deepcopy
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay
from tests.test_combat_replay import target
from tests.test_stackable_projectiles import setup


@pytest.fixture
def shadow(monkeypatch):
    core=pytest.importorskip('wfarsenal.wfcore')
    assert getattr(core,'STUG_IDEAL_DETONATION',0)
    assert getattr(core,'SNIPER_COMBO_STATUS',0)
    assert getattr(core,'PERSISTENT_RADIALS',0)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    native_replay.STATS.update(native=0,fallback=0)
    return native_replay.STATS


@pytest.mark.parametrize('mode,multishot,hp',[(0,3.9,1e9),(1,1.,1e9),(2,3.,1e9),(2,5.,1e9),(2,6.,1000.),(2,50.,1e9)])
def test_stug_default_children_and_atomic_blobs_match_native(shadow,mode,multishot,hp):
    stats,combat=setup('Stug',mode=mode,multishot=multishot)
    result=replay(stats,target(hp),attacks_per_second=stats.fire_rate,window_seconds=8.,
                  combat=combat,collect_timeline=False,headshot_chance=1.)
    assert result['projectileLifecycle']['explosions']>0
    assert shadow['native']==1


@pytest.mark.parametrize('cycle,hp',[(False,1.),(False,1e9),(True,1e5)])
def test_vectis_independent_orbs_and_combo_status_match_native(shadow,cycle,hp):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Vectis Prime'))
    weapon['isIncarnonForm']=True
    fx=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','ADD',.9,damage_type='DT_FIRE'),
        ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.8)]
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=fx,scenario=Scenario(aiming=True,incarnon_cycle=cycle)),
                   [],[],cycle_enabled=cycle)
    stats,_=combat['resolve']('selected',{},0)
    result=replay(stats,target(hp),attacks_per_second=stats.fire_rate,window_seconds=12.,
                  combat=combat,collect_timeline=False,headshot_chance=1.)
    assert result['delayedAttackEvents']>0
    assert shadow['native']==1


def test_old_native_library_falls_back_for_repaired_stug(monkeypatch):
    stats,combat=setup('Stug',mode=2)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'wfcore',object())
    assert not native_replay.supported(stats,dict(combat=combat,collect_timeline=False))
