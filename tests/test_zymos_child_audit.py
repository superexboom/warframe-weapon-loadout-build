"""Zymos child notices and damage inheritance are independent audit axes."""
from copy import deepcopy
import pytest
from tools.import_zymos_child_audit import child_audit, merge, SCRIPT, WEAPON, PROJECTILE, CARRIER, CHILD, WARNINGS


class Packages:
    def __init__(self):
        self.rows = {
            PROJECTILE: {"ValidEmbedPart": "HEAD",
                "EmbedDeathAttackHitScript": {"Script": SCRIPT, "Function": "OnRadialDamage", "_projectileType": "EmbedDeathKillClusterProj"},
                "OnProjectileDeathScript": {"Script": SCRIPT, "Function": "OnDeath", "_projectileType": "EmbedDeathKillClusterProj"}},
            CARRIER: {"ClusterProjectiles": "EmbedDeathKillGuidedProj", "ClusterSetsChildrenDamageInfo": 1},
            CHILD: {"SendEvents": 0, "DamageUpgradeTypes": [], "CriticalChance": .05, "CriticalMultiplier": 2.3,
                    "ExplosiveAttack": {"Amount": 333, "Type": "DT_POISON", "ProcChance": .3}}}
    def resolve(self, path):
        return self.rows[path]


def test_child_spawn_branches_do_not_become_ten_automatic_hits():
    evidence = child_audit(Packages())
    assert [branch["requestedChildCount"] for branch in evidence["callbackBranches"]] == [5, 5]
    assert evidence["branchCombination"] == "shared-record-consumed-once-do-not-sum"
    assert evidence["status"] == "partial-consumer-audit-no-added-damage"
    assert evidence["childDeclarations"]["SendEvents"] == 0
    assert "status-and-kill-event-consumers" in evidence["unresolved"]
    assert "takes_condition_overload" not in evidence


def test_missing_send_events_is_unknown_and_cannot_reuse_this_audit():
    packages = Packages()
    del packages.rows[CHILD]["SendEvents"]
    with pytest.raises(ValueError, match="declaration contract"):
        child_audit(packages)


def test_merge_preserves_existing_damage_and_is_idempotent():
    reference = {"auditedAttacks": {WEAPON: {"projectile": PROJECTILE, "directTotal": 23.,
        "radials": [{"damage": {"toxin": 61.}}, {"damage": {"toxin": 953.}, "headOnly": True}]}}}
    original = deepcopy(reference)
    merged = merge(reference, child_audit(Packages()))
    assert reference == original
    assert merged["auditedAttacks"][WEAPON]["radials"] == original["auditedAttacks"][WEAPON]["radials"]
    assert merged == merge(merged, child_audit(Packages()))
    assert merged["auditedAttacks"][WEAPON]["unmodeled"] == WARNINGS


def test_current_runtime_surfaces_child_gap_without_inventing_payload():
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("path") == WEAPON)
    fight = prepare(dict(weapon=weapon, fire_mode=0, effects=[], scenario=Scenario()), [], [])
    assert set(WARNINGS).issubset(fight["unsupported"])
    direct, radial = fight["resolve"]("selected", {}, 0.)
    assert direct.total_damage == pytest.approx(23.)
    assert radial.total_damage == pytest.approx(61.)
    assert [p.total_damage for p in radial._additional_radials] == pytest.approx([953.])
