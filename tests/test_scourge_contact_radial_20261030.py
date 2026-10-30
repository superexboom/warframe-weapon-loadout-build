"""Scourge ordered contact55/owned embed50 under explicit reload cycle."""
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
    tick=entry['attachedTicks']
    assert tick['damage']=={'DT_IMPACT':35.,'DT_PUNCTURE':5.,'DT_SLASH':10.}
    assert tick['tick_rate']==1. and tick['duration_seconds']==10.
    assert tick['nativeSource']==imp.PROJECTILE and tick['nativeField']=='EmbedAttack'
    assert tick['status_chance']==.050000001 and tick['crit_chance']==.1 and tick['crit_multiplier']==2.
    assert tick['sourceDestroyOnNextFire'] and tick['sourceHitType']=='DHT_DOT' and tick['excludesTypedFlat']
    assert not tick['takes_condition_overload'] and not tick['takes_victim_crit'] and not tick['takes_multishot']
    assert tick['genericHitEvent'] and tick['genericCritEvent']
    assert 'scourge-prime-stopped-embedded-script-payload-unmodeled' not in entry['unmodeled']
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
    def replay(window,curve=None):
        return combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,collect_timeline=False,life_curve=curve)
    curve=[]
    prior=replay(3.1,curve);after=replay(3.3)
    assert prior['shots']==prior['reloads']==1
    assert after['shots']==2 and after['reloads']==1
    # Existing damage quantization puts independent50's70/10/20 shares
    # at22/32,3/32,6/32:48.4375 effective before target modifiers.
    tick_damage=48.4375
    assert [event[0] for event in curve]==pytest.approx([0.,0.,0.,1.,2.,3.])
    assert [event[1] for event in curve]==pytest.approx([300.,55.,tick_damage,tick_damage,tick_damage,tick_damage],rel=1e-7)
    # Native source is unique: first throw hits300,55,50 then ticks1/2/3;
    # next explicit throw at3.2 cancels the old delegate before its4.0 tick.
    assert prior['totalWindowDamage']==pytest.approx(355.+4*tick_damage,rel=1e-7)
    assert after['totalWindowDamage']==pytest.approx(2*355.+5*tick_damage,rel=1e-7)
    assert replay(4.1)['totalWindowDamage']==pytest.approx(after['totalWindowDamage'],rel=1e-7)
    assert replay(4.3)['totalWindowDamage']==pytest.approx(after['totalWindowDamage']+tick_damage,rel=1e-7)
    # A host surviving300 but killed by55 cannot receive the immediate50,
    # nor may that packet migrate to the next scoring generation.
    short=combat_replay.replay(stats,{**TARGET,'health':320.},attacks_per_second=stats.fire_rate,
        window_seconds=.1,combat=fight,collect_timeline=False)
    assert short['totalWindowDamage']==pytest.approx(320.,rel=1e-7)
    assert short['killEvents']==1
    assert 'scourge-prime-throw-reload-rethrow-input-policy-idealized' in after['unsupported']
    assert native_replay.STATS['native']>before


def test_native_fraction_quantization_ties_round_up_and_keep_source_loss(monkeypatch):
    from wfarsenal.damage import ModdedStats,quantize_damage_vector,quantize_base_crit_damage
    # Exact fractions from one original-byte140dc9010 packet control. These
    # are arithmetic contracts, not a claim that a current catalog roll hit a tie.
    assert quantize_base_crit_damage(256.5*32/4095)==pytest.approx(257.*32/4095)
    vector={'DT_IMPACT':.015625,'DT_PUNCTURE':.046875,'DT_SLASH':.640625}
    assert quantize_damage_vector(vector,1.)=={'DT_IMPACT':.03125,'DT_PUNCTURE':.0625,'DT_SLASH':.65625}
    st=ModdedStats(damage_types=vector,crit_chance=0.,crit_multiplier=1.,status_chance=0.,
        multishot=1.,fire_rate=.001,magazine=10.,reload_time=1.,dot_base_damage=1.)
    fight={'resolve':lambda *_:(st,None)}
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    result=combat_replay.replay(st,TARGET,attacks_per_second=.001,window_seconds=.01,combat=fight,collect_timeline=False)
    assert result['directWindow']==.75 and native_replay.STATS['native']>before
