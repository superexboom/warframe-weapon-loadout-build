"""Battacor native one-charge alt: charge gate and independent radial packet."""
from copy import deepcopy
import json
from pathlib import Path
import pytest
import app
from tools import import_battacor_radial as importer
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.event_profiles import base_profile, kill_charge_cycle
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay

ROOT = Path(__file__).resolve().parents[1]


def weapon():
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path'] == importer.WEAPON))


def combat(pellets=1):
    fx = [ModEffect('WEAPON_CRIT_CHANCE', 'SET', 0.),
          ModEffect('WEAPON_PROC_CHANCE', 'SET', 0.),
          ModEffect('WEAPON_FIRE_ITERATIONS', 'SET', float(pellets))]
    return prepare(dict(weapon=weapon(), fire_mode=1, effects=fx, scenario=Scenario()), [], [])


def enemy(health=1e12):
    return dict(health=health, shield=0., overguard=0., armour=0., baseLevel=1)


def test_native_radial_keeps_its_own_crit_status_and_multishot_contract():
    w = weapon()
    assert not base_profile(w, 0).get('radials')
    profile = base_profile(w, 1)
    radial = profile['radials'][0]
    assert radial['damage'] == {'radiation':208.}
    assert (radial['crit_chance'],radial['crit_multiplier'],radial['status_chance']) == (.2,2.,.5)
    assert radial['takes_multishot'] is True
    assert radial['perPacketTakesMultishot'] is False
    assert 'per-trigger-multiplicity-unverified' not in ' '.join(profile['unmodeled'])
    proof=profile['source']['radialMultiplicity']
    assert proof['observedRayCounts']==proof['observedRadialCounts']==[1,2,3]
    assert proof['perPacketDamage']==208. and proof['perPacketTakesMultishot'] is False
    assert proof['sameVictimAcrossRaysDeduplicated'] is False
    assert radial['conditionOverloadSource'] == 'existing-model-policy-unverified-not-native-proof'
    assert radial['nativeField'] == 'Behaviors[1].impact.RadialDamage'
    assert all(key in profile['unmodeled'] for key in importer.UNMODELED)
    selected,_ = app.optimizer._select_fire_mode(w,1,weapon_type='rifle')
    assert base_profile(selected,0)['radials'] == profile['radials']


@pytest.mark.parametrize('pellets,expected',[(1.,416.),(2.,832.),(3.,1248.)])
def test_native_per_ray_radial_multiplies_packet_count_without_extra_packet_damage_factor(pellets,expected,monkeypatch):
    monkeypatch.setattr(native_replay,'ENABLED',False)
    fight = combat(pellets)
    direct,radial = fight['resolve']('selected',{},0)
    assert direct.multishot == pellets and radial.multishot == pellets
    # Native single radial payload remains 208; multiplicity comes from rays.
    assert radial.damage_types == {'DT_RADIATION':208.}
    result = replay(direct,enemy(),attacks_per_second=direct.fire_rate,
                    window_seconds=.001,combat={**fight,'cycle':None},collect_timeline=False)
    assert result['shots'] == 1
    assert result['directWindow'] == pytest.approx(expected)


def test_cycle_needs_one_primary_kill_and_does_not_assume_a_full_gauge():
    assert kill_charge_cycle(weapon(),0) is None
    assert kill_charge_cycle(weapon(),1) == dict(hits=1.,pool=1.,enterSeconds=0.,exitSeconds=0.,chargeOn='kills',killCharged=True,chargeBeforeFire=True)
    entry=json.loads((ROOT/'data/mechanics/kill-charge-profiles.json').read_bytes())['weapons'][importer.WEAPON]
    assert entry['policy']=='spend-first-primary-kill-charge-immediately'
    assert entry['native']['RequireFullCharges']==0
    assert entry['native']['MaxCharges']==3 and entry['native']['NumChargesToConsume']==0


def test_actual_zero_kill_replay_cannot_fire_the_alt(monkeypatch):
    monkeypatch.setattr(native_replay,'ENABLED',False)
    fight=combat();primary,_=fight['resolve']('base',{},0)
    result=replay(primary,enemy(),attacks_per_second=primary.fire_rate,window_seconds=2.,combat=fight,collect_timeline=True)
    assert result['transforms']==0
    assert result['directWindow']>0
    assert all(row['form']=='base' for row in result['timeline'])


def test_actual_primary_kill_unlocks_alt_and_returns_to_base(monkeypatch):
    monkeypatch.setattr(native_replay,'ENABLED',False)
    fight=combat();primary,_=fight['resolve']('base',{},0)
    result=replay(primary,enemy(10.),attacks_per_second=primary.fire_rate,window_seconds=2.,combat=fight,collect_timeline=True)
    assert result['transforms']>0
    assert result['transforms']<=2*result['killEvents']
    assert any(row['form']=='incarnon' for row in result['timeline'])
    assert all(key in result['unsupported'] for key in importer.UNMODELED)


def test_native_and_python_replay_match_with_independent_radial_and_charge_cycle(monkeypatch):
    monkeypatch.setattr(native_replay,'SHADOW',True)
    fight=combat(3.);primary,_=fight['resolve']('base',{},0)
    result=replay(primary,enemy(100.),attacks_per_second=primary.fire_rate,window_seconds=2.,combat=fight,collect_timeline=False)
    assert result['transforms']>0


def test_sentient_barrage_remains_unsupported():
    row=next(m for m in app.EXPORTS['mods'] if m['path'].endswith('/NightwaveBattacorAugmentMod'))
    assert row['supported'] is False


def test_importer_rejects_an_unproven_native_image(tmp_path):
    image=tmp_path/'Warframe.x64.exe';image.write_bytes(b'new-client')
    with pytest.raises(ValueError,match='identity'):
        importer.verified_sources(None,image)


@pytest.mark.parametrize('changes', [{'DamageMultiplier':2}, {'UseClipSizeAsDamageMultiplier':1}])
def test_importer_rejects_charge_multiplier_routing_drift(changes,monkeypatch):
    # Hold raw-source identity admission open to exercise the semantic check.
    # A changed resource normally fails even earlier on its ancestry hash.
    monkeypatch.setattr(importer,'verified_sources',lambda *_:[])
    state=dict(ApplyNumChargesToDamageMultiplier=1,MinDamageMultiplier=1,MaxDamageMultiplier=3,
               ChargeTime=.40000001,UseClipSizeAsDamageMultiplier=0,DamageMultiplier=1)
    state.update(changes)
    native=dict(MaxCharges=3,NumChargesToConsume=0,AddCharges=[dict(Conditions=['PRIMARY_KILL'],NumCharges=1)],
                ConsumeChargeConditions=['SECONDARY_FIRE'],Behaviors=[{},
                    {'fire:Fire':{'ConsumesChargesForFire':1},'impact:Impact':{},'state:State':state}])
    class Index:
        def resolve(self,path):return native
    with pytest.raises(ValueError,match='minimum-charge contract'):
        importer.profile(Index(),weapon(),native_image=None)


@pytest.mark.parametrize('charges',[1,2,3])
@pytest.mark.parametrize('pellets',[1.,2.,3.])
@pytest.mark.parametrize('native',[False,True])
def test_banked_charge_snapshot_scales_every_radial_packet_once(charges,pellets,native,monkeypatch):
    from copy import copy
    fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),
        ModEffect('WEAPON_PROC_CHANCE','SET',0.),
        ModEffect('WEAPON_FIRE_ITERATIONS','SET',pellets)]
    fight=prepare(dict(weapon=weapon(),fire_mode=1,effects=fx,
        scenario=Scenario(combat_state={'battacorCharges':charges})),[],[])
    original=fight['resolve']
    def resolve(form,*args):
        direct,radial=original(form,*args)
        direct=copy(direct);direct.fire_rate=2.;direct.native_forced_procs={}
        direct.status_chance=0.;direct.crit_chance=0.
        direct._charge_time=.4 if form!='base' else 0.
        if form=='base':
            direct.multishot=1.;direct.damage_types={'DT_IMPACT':20000.}
        else:
            radial=copy(radial);radial.native_forced_procs={}
            radial.status_chance=0.;radial.crit_chance=0.
            assert direct.multishot==radial.multishot==pellets
            assert direct.total_damage==radial.total_damage==208.
        return direct,radial
    fight['resolve']=resolve;fight['baseBurst']=None;fight['incarnonBurst']=None
    fight['baseFireRate']=2.;fight['incarnonFireRate']=2.
    direct,_=resolve('base',{},0.)
    monkeypatch.setattr(native_replay,'ENABLED',native)
    result=replay(direct,enemy(10000.),attacks_per_second=2.,
        window_seconds=charges*.5+.401,combat=fight,collect_timeline=False)
    assert result['shots']==charges+1
    assert result['directWindow']==pytest.approx(charges*10000.+416.*charges*pellets)
