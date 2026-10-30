"""Scourge contact55 production-route acceptance under explicit reload cycle."""
from copy import deepcopy
import pytest
import app
from wfarsenal import manual_combat,native_replay,combat_replay
from wfarsenal.damage import ModEffect,Scenario
from tools import import_scourge_contact_radial as imp
from tools.import_native_secondary_payloads import merge_patch
from tests.test_scourge_contact_contract_20261029 import source

TARGET=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)

def test_source_builds_main55_and_only_one_spear(source):
    pkg,_,row=source;out=imp.build_patch(pkg,row);entry=out['weapons'][imp.WEAPON]['1'];r=entry['radials'][0]
    assert out['pending']==[] and r['damage']=={'corrosive':55.} and r['impact_delay_seconds']==0.
    assert r['emissionContract']['packetsPerPhysicalThrow']==r['emissionContract']['physicalThrowsPerFire']==1
    assert entry['nativeSpearThrowCycle']['reloadBaseSeconds']==2.2
    assert not entry['nativeSpearThrowCycle']['oldSpearLifetimeWaitRequired']
    assert 'scourge-prime-throw-reload-rethrow-input-policy-idealized' in entry['unmodeled']
    assert 'candidateOnly' not in entry
    assert 'Projectile+1589' in entry['nativeEvidence']['destructionFieldBinding']
    assert 'embedded8e1' in entry['nativeEvidence']['maxEnforcement']
    assert '141050add' in entry['nativeEvidence']['removal']
    assert 'remote queue receiver ordering not emulated' in entry['nativeEvidence']['removal']

@pytest.mark.parametrize('field,value',[('reloadTime',1.5),('fireRate',120),('IsAlternateFire',0)])
def test_cadence_drift_rejected(source,field,value):
    pkg,objects,row=source;objects[imp.WEAPON]['Behaviors'][1]['state:LotusSpearGunStateBehavior'][field]=value
    with pytest.raises(ValueError,match='cadence'):imp.build_patch(pkg,row)

@pytest.mark.parametrize('native',[False,True])
@pytest.mark.parametrize('msbonus',[0.,2.])
@pytest.mark.parametrize('window,expected,reloads',[(1.1,1,1),(3.1,1,1),(3.3,2,1),(10.,4,3)])
def test_actual_single_contact55_route_keeps_charge_reload_and_one_spear(source,monkeypatch,native,msbonus,window,expected,reloads):
    pkg,_,row=source;payload=merge_patch(manual_combat.reference(),imp.build_patch(pkg,row))
    monkeypatch.setattr(manual_combat,'reference',lambda:payload);monkeypatch.setattr(native_replay,'ENABLED',native)
    w=next(w for w in app.EXPORTS['weapons'] if w['path']==imp.WEAPON)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',msbonus)]
    fight=manual_combat.prepare(dict(weapon=deepcopy(w),fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=fight['resolve']('selected',{},0.);before=native_replay.STATS['native']
    result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False)
    if native:assert native_replay.STATS['native']>before,'requires actual native path'
    assert result['shots']==expected
    assert result['reloads']==reloads
    assert result['totalWindowDamage']==pytest.approx(expected*355.,rel=1e-7)
    assert 'scourge-prime-throw-reload-rethrow-input-policy-idealized' in result['unsupported']
