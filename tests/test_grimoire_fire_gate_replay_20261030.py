"""Actual Grimoire selected-mode replay acceptance for the native45s overheat gate."""
from copy import deepcopy
import pytest
import app
from wfarsenal import manual_combat,native_replay,combat_replay
from wfarsenal.damage import ModEffect,Scenario
from wfarsenal.event_profiles import base_profile

PATH='/Lotus/Weapons/Tenno/Grimoire/TnGrimoire'
TARGET=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)

def weapon():return next(w for w in app.EXPORTS['weapons'] if w['path']==PATH)

@pytest.fixture
def isolated_gate(monkeypatch):
    payload=deepcopy(manual_combat.reference());entry=payload.setdefault('auditedAttacks',{}).setdefault(PATH,{}).setdefault('modes',{}).setdefault('1',{})
    entry['nativeFireCooldownSeconds']=45.
    monkeypatch.setattr(manual_combat,'reference',lambda:payload)

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('bonus',[0.,2.])
@pytest.mark.parametrize('window,expected',[(4.,1),(44.9,1),(45.1,2),(90.1,3)])
def test_real_selected_alt_obeys45s_despite_fire_rate(isolated_gate,monkeypatch,native,bonus,window,expected):
    monkeypatch.setattr(native_replay,'ENABLED',native)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',bonus)]
    fight=manual_combat.prepare(dict(weapon=deepcopy(weapon()),fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=fight['resolve']('selected',{},0.);before=native_replay.STATS['native']
    result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False)
    if native:assert native_replay.STATS['native']>before,'native path must actually execute'
    assert result['shots']==expected


def test_production_exact_mode_has_gate_and_primary_does_not():
    assert base_profile(weapon(),1)['nativeFireCooldownSeconds']==45.
    assert not base_profile(weapon(),0).get('nativeFireCooldownSeconds')
