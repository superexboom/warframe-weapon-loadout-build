"""Scourge contact55 production-route acceptance under explicit reload cycle."""
from copy import deepcopy
import pytest
import app
from wfarsenal import manual_combat,native_replay,combat_replay
from wfarsenal.damage import ModEffect,Scenario
from tools import import_scourge_contact_radial as imp
from tools.import_native_secondary_payloads import merge_patch
from pathlib import Path
from types import SimpleNamespace
import json
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def source():
    data=json.loads((ROOT/'tests/fixtures/scourge_prime_source.json').read_bytes());objects={imp.WEAPON:data['weapon'],imp.PROJECTILE:data['projectile']};parents={r['path']:r['parent'] for r in data['sources']}
    class Packages:
        entities={p:(a,SimpleNamespace(attr=None)) for p,a in parents.items()}
        def parent(self,p):return parents.get(p)
        def resolve(self,p):return deepcopy(objects[p])
        def locate(self,owner,ref):return ref if ref.startswith('/') else owner.rsplit('/',1)[0]+'/'+ref
    row=next(r for r in json.loads((ROOT/'data/export/2026.08.13.13.24/weapons.json').read_bytes())['data'] if r['path']==imp.WEAPON)
    return Packages(),objects,row


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


def test_actual_contact_route_keeps_charge_reload_and_one_spear(source,monkeypatch):
    pkg,_,row=source;payload=merge_patch(manual_combat.reference(),imp.build_patch(pkg,row))
    monkeypatch.setattr(manual_combat,'reference',lambda:payload)
    monkeypatch.setattr(native_replay,'ENABLED',True);monkeypatch.setattr(native_replay,'SHADOW',True)
    w=next(w for w in app.EXPORTS['weapons'] if w['path']==imp.WEAPON)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    fight=manual_combat.prepare(dict(weapon=deepcopy(w),fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=fight['resolve']('selected',{},0.);before=native_replay.STATS['native']
    def replay(window):
        return combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False)
    prior=replay(3.1);after=replay(3.3)
    assert prior['shots']==prior['reloads']==1
    assert after['shots']==2 and after['reloads']==1
    assert after['totalWindowDamage']==pytest.approx(2*355.,rel=1e-7)
    assert 'scourge-prime-throw-reload-rethrow-input-policy-idealized' in after['unsupported']
    assert native_replay.STATS['native']>before
