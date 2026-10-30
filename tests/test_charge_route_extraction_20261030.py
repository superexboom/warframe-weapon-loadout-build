"""Swapping charge output states cannot be imported as free independent shots."""
from copy import deepcopy
import pytest
from wfarsenal import extract


def behaviors():
    return [{'state:Type':'/Lotus/Types/Game/LotusSwappingChargedStateBehavior','state:LotusSwappingChargedStateBehavior':dict(ChargeTime=1.5,MinChargeRatio=0,SwapOnFire=1,SwapAfterFire=0,ChargedBehavior=1,CacheFullCharge=0,fireRate=180,LocTag='/Lotus/Language/Menu/Loadout_TriggerCharge')},
            {'state:Type':'/EE/Types/Game/WeaponChargeBeamStateBehavior','state:WeaponChargeBeamStateBehavior':dict(ChargeTime=0,fireRate=120,LocTag='/Lotus/Language/Menu/Loadout_TriggerCharge')}]


def test_extraction_separates_local_state_time_from_effective_release_charge(monkeypatch):
    monkeypatch.setattr(extract,'_resolve_damage',lambda *_:dict(types={'DT_IMPACT':10.}))
    monkeypatch.setattr(extract,'_native_event_declarations',lambda *_:{})
    monkeypatch.setattr(extract,'_extract_projectile_events',lambda *_:{})
    states=behaviors();before=deepcopy(states)
    modes=extract._extract_fire_modes(None,'/fixture',{'Behaviors':states})
    assert states==before
    assert [m['chargeTime'] for m in modes]==[0.,1.5]
    assert [m['nativeLocalChargeTime'] for m in modes]==[1.5,0]
    assert [m['nativeChargeSourceBehavior'] for m in modes]==[0,0]
    assert [m['index'] for m in modes]==[0,1]


@pytest.mark.parametrize('change',[{'SwapOnFire':0},{'SwapAfterFire':1},{'MinChargeRatio':1},{'CacheFullCharge':1},{'ChargedBehavior':True},{'ChargedBehavior':0},{'ChargedBehavior':2}])
def test_other_swap_cancel_and_cached_shapes_are_not_reinterpreted(change):
    states=behaviors();states[0]['state:LotusSwappingChargedStateBehavior'].update(change)
    assert extract._swapping_charge_routes(states)=={}


def test_independently_charged_target_does_not_inherit_another_charge():
    states=behaviors();states[1]['state:WeaponChargeBeamStateBehavior']['ChargeTime']=.5
    assert extract._swapping_charge_routes(states)=={}
