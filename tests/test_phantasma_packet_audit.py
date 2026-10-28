"""Keep Phantasma payload omissions visible without fabricating trigger rights."""
from copy import deepcopy
import pytest
from tools.import_phantasma_packet_audit import audit, merge, PAIRS, WARNINGS


class Packages:
    def resolve(self, projectile):
        return {"AttackData": {"Amount": 15, "Type": "DT_IMPACT"},
                "ExplosiveAttack": {"Amount": 73, "Type": "DT_RADIATION", "HitType": "DHT_PROJECTILE"}}


def exports():
    return [{"path": path, "nameEn": path, "fireModes": [{}, {"damage": {
        "projectile": projectile, "types": {"DT_IMPACT": 15.}}}]} for path, projectile in PAIRS]


def test_packet_type_and_head_suppression_do_not_grant_co_or_head_events():
    result = audit(Packages(), PAIRS[0][1])
    assert result["sourceHitType"] == "DHT_PROJECTILE"
    assert result["headDamageSuppression"]
    assert "head-crit-and-head-kill-qualification" in result["unresolved"]
    assert "takes_condition_overload" not in result and "area_direct" not in result


def test_new_runtime_profile_requires_missing_payload_diagnostic_to_be_reaudited():
    source = {"auditedAttacks": {PAIRS[0][0]: {"modes": {"1": {"radials": [{"damage": {"radiation": 73.}}]}}}}}
    with pytest.raises(ValueError, match="runtime packet profile"):
        merge(source, exports(), Packages())


def test_boundary_import_is_idempotent_and_preserves_primary_mode():
    source = {"auditedAttacks": {PAIRS[0][0]: {"directTotal": 90., "mode0-marker": True}}}
    before = deepcopy(source)
    result = merge(source, exports(), Packages())
    assert source == before
    assert result["auditedAttacks"][PAIRS[0][0]]["mode0-marker"] is True
    assert result == merge(result, exports(), Packages())


@pytest.mark.parametrize("path,projectile", PAIRS)
def test_runtime_missing_packet_is_explicit_only_on_alternate(path, projectile):
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("path") == path)
    for mode in (0, 1):
        combat = prepare(dict(weapon=weapon, fire_mode=mode, effects=[], scenario=Scenario()), [], [])
        assert set(WARNINGS).issubset(combat["unsupported"]) == bool(mode)
        if mode == 1:
            direct, radial = combat["resolve"]("selected", {}, 0.)
            assert direct.damage_types == {"DT_IMPACT": 15.}
            assert radial is None  # Explicit unresolved result; never mislabeled fully calibrated.
