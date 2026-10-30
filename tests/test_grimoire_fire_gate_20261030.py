"""Grimoire exact identity and source drift rejection for native overheat gate."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
from tools import import_grimoire_fire_gate as imp

@pytest.fixture
def source():
    state=dict(InstantOverheat=1,OverheatStyle='OS_PLATEAU',OverheatTime=45,ReduceOverheatAmount=1,OverheatCooldownModifier=1)
    weapon=dict(Behaviors=[{}, {'state:Type':imp.STATE,'state:LotusFireAndToggleStateBehavior':state,'fire:LotusWeaponProjectileFireBehavior':dict(IgnoreFireIterations=1,fireIterations=1)}],AddingChargesReducesOverheat=1,MaxCharges=0,AddCharges=[dict(Conditions=['PRIMARY_DIRECT_HIT'],NumCharges=1)])
    objects={imp.WEAPON:weapon,imp.STATE:{}}
    class Packages:
        entities={p:('',SimpleNamespace(attr=None)) for p in objects}
        def parent(self,p):return ''
        def resolve(self,p):return deepcopy(objects[p])
    return Packages(),weapon,dict(path=imp.WEAPON,fireModes=[{},dict(damage=dict(projectile=imp.PROJECTILE))])

def test_gate_keeps_spatial_payloads_excluded(source):
    pkg,_,row=source;out=imp.build_contract(pkg,row);m=out['weapons'][imp.WEAPON]['1'];g=m['nativeFireGate']
    assert m['nativeFireCooldownSeconds']==45 and g['initiallyReady'] and not g['affectedByFireRate']
    assert g['primaryHitRecoverySeconds']==1 and not g['primaryRecoveryEnabledInSingleMode']
    assert 'radialDamage' not in m and 'sourcePayloads' not in m


def test_selected_alt_gate_ignores_fire_rate_and_multishot(monkeypatch):
    import app
    from wfarsenal import manual_combat, native_replay, combat_replay
    from wfarsenal.damage import ModEffect, Scenario
    from wfarsenal.event_profiles import base_profile
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==imp.WEAPON)
    assert base_profile(weapon,1)['nativeFireCooldownSeconds']==45.
    assert not base_profile(weapon,0).get('nativeFireCooldownSeconds')
    monkeypatch.setattr(native_replay,'ENABLED',True)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
             ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',2.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    fight=manual_combat.prepare(dict(weapon=deepcopy(weapon),fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=fight['resolve']('selected',{},0.)
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    def replay(window):
        return combat_replay.replay(stats,target,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False)
    before=native_replay.STATS['native']
    first=replay(44.9); second=replay(45.1)
    assert first['shots']==1 and second['shots']==2
    assert stats.multishot==1.
    assert native_replay.STATS['native']>before
