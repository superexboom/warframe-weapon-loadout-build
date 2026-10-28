"""Raw event lanes survive export without pretending to be trigger eligibility."""
from copy import deepcopy
from wfarsenal.extract import _flatten_behaviours, _damage_block, _projectile_damage_components


class Packages:
    def __init__(self, projectile):
        self.projectile = projectile
    def resolve(self, path):
        return deepcopy(self.projectile) if path == "/game/projectile" else {}
    def ancestry(self, path):
        return [path]


def mode(projectile, impact=None):
    return _flatten_behaviours(Packages(projectile), "/game/weapon", [{
        "fire:WeaponProjectileFireBehavior": {"projectileType": "/game/projectile"},
        "impact:RadialOnMissImpactBehavior": impact or {},
    }])[0]


def test_explicit_false_and_empty_upgrade_list_survive_independently():
    projectile = {"AttackData": {"Amount": 10, "Type": "DT_POISON", "HitType": "DHT_PROJECTILE"},
                  "SendEvents": 0, "DamageUpgradeTypes": [], "IgnoreHeadShotBonus": 1,
                  "DealDamageThroughImpactBehavior": 0}
    result = mode(projectile, {"ApplyRadialDamageOnHit": 0, "ApplyRadialDamageOnMiss": 1,
                              "MultiShotBuffsRadialDamage": 0, "IgnoreHeadshotBonus": 0})
    declarations = result["nativeEventDeclarations"]
    assert declarations["projectile"] == {"path": "/game/projectile", "fields": {
        "SendEvents": 0, "DamageUpgradeTypes": [], "IgnoreHeadShotBonus": 1,
        "DealDamageThroughImpactBehavior": 0}}
    assert declarations["impact"] == {"ApplyRadialDamageOnHit": 0, "ApplyRadialDamageOnMiss": 1,
                                      "MultiShotBuffsRadialDamage": 0, "IgnoreHeadshotBonus": 0}
    assert result["damage"]["types"] == {"DT_POISON": 10.0}
    assert result["damage"]["sourceHitType"] == "DHT_PROJECTILE"
    assert "canTriggerKill" not in declarations and "conditionOverload" not in declarations


def test_absent_fields_stay_unknown_instead_of_false_defaults():
    result = mode({"AttackData": {"Amount": 10, "Type": "DT_POISON"}})
    assert "nativeEventDeclarations" not in result
    assert "sourceHitType" not in result["damage"]


def test_alternate_death_payloads_keep_their_own_hit_type():
    result = _projectile_damage_components({
        "ExplosiveAttack": {"Amount": 73, "Type": "DT_RADIATION", "HitType": "DHT_PROJECTILE"},
        "EmbedDeathAttack": {"Amount": 73, "Type": "DT_RADIATION", "HitType": "DHT_RADIAL"}})
    assert [(part["source"], part["sourceHitType"]) for part in result] == [
        ("ExplosiveAttack", "DHT_PROJECTILE"), ("EmbedDeathAttack", "DHT_RADIAL")]
    assert all("takes_condition_overload" not in part for part in result)


def test_explicit_none_hit_type_is_not_dropped_and_damage_math_is_unchanged():
    raw = {"Amount": 100, "DT_IMPACT": .25, "DT_PUNCTURE": .75, "ProcChance": .2,
           "HitType": "DHT_NONE"}
    result = _damage_block(raw, amount_key="Amount", proc_key="ProcChance")
    assert result["sourceHitType"] == "DHT_NONE"
    assert result["total"] == 100 and result["types"] == {"DT_IMPACT": 25., "DT_PUNCTURE": 75.}
    assert result["procChance"] == .2


def test_damage_less_scripted_mode_still_exposes_event_declarations():
    result = mode({"AttackData": {"Amount": 0}, "SendEvents": 0, "DamageUpgradeTypes": {}})
    assert result["damage"] is None
    assert result["nativeEventDeclarations"]["projectile"]["fields"] == {
        "SendEvents": 0, "DamageUpgradeTypes": {}}


def test_inline_radial_lowercase_hit_type_survives_its_native_schema():
    parts = _projectile_damage_components({"RadialDamage": {"baseAmount": 208.,
        "DT_RADIATION": 208., "baseProcChance": .5, "hitType": "DHT_RADIAL"}})
    assert parts[0]["sourceHitType"] == "DHT_RADIAL"
    assert parts[0]["total"] == 208.
