"""Ground Archgun hits and explosions must use the same native behaviour bank."""
from copy import deepcopy
import pytest
from tools.import_projectile_components import exported_behaviours, hitscan_radial, remote_mine


def behavior(amount):
    return {"impact:RadialOnMissImpactBehavior": {"RadialDamage": dict(baseAmount=amount,
        baseProcChance=.5, DamagePercent={"DT_FIRE":1.}, criticalChance=.5,
        criticalMultiplier=3.5, radius=8., fallOff=.4)}}


class Package:
    def __init__(self, native): self.native = native
    def resolve(self, path): return self.native


def test_mausolon_ground_primary_and_alternate_are_72_and_4500_not_space_values():
    native = dict(Behaviors=[behavior(48.),behavior(3000.)], HeavyBehaviors=[behavior(72.),behavior(4500.)])
    row = dict(path="/Mausolon", slot="arch_gun", fireModeSource="HeavyBehaviors")
    for position, amount in enumerate((72.,4500.)):
        part = hitscan_radial(Package(native), row, dict(index=position))
        assert part["RadialDamage"]["Amount"] == amount
        assert part["RadialDamage"]["DT_FIRE"] == amount
        assert part["CriticalChance"] == .5


def test_explicit_shared_bank_is_preserved_and_non_archguns_never_select_heavy():
    native = dict(Behaviors=[behavior(48.)], HeavyBehaviors=[behavior(72.)])
    for row in (dict(path="/w",slot="primary"),dict(path="/w",slot="arch_gun",fireModeSource="Behaviors")):
        assert hitscan_radial(Package(native),row,dict(index=0))["RadialDamage"]["Amount"] == 48.
    assert hitscan_radial(Package(native),dict(path="/w",slot="arch_gun"),dict(index=0))["RadialDamage"]["Amount"] == 72.


def test_missing_explicit_bank_does_not_fallback_to_wrong_loadout():
    native = dict(Behaviors=[behavior(48.)])
    assert hitscan_radial(Package(native),dict(path="/w",slot="arch_gun",fireModeSource="HeavyBehaviors"),dict(index=0)) is None


@pytest.mark.parametrize("index",[-1,True,2,None])
def test_invalid_raw_mode_position_is_rejected(index):
    assert hitscan_radial(Package(dict(Behaviors=[behavior(1.)])),dict(path="/w"),dict(index=index)) is None


def test_exported_index_is_native_index_not_filtered_mode_list_position():
    native = dict(HeavyBehaviors=[{},behavior(72.),{},behavior(4500.)])
    part = hitscan_radial(Package(native),dict(path="/w",slot="arch_gun",fireModeSource="HeavyBehaviors"),dict(index=3))
    assert part["RadialDamage"]["Amount"] == 4500.


def test_remote_mine_uses_same_selected_bank():
    native = dict(Behaviors=[{}],HeavyBehaviors=[{"state:RemoteMineStateBehavior": {"DetonateManually":True}}])
    assert remote_mine(Package(native),dict(path="/w",slot="arch_gun"),dict(index=0)) == {"DetonateManually":True}
