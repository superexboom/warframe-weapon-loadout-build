"""Game update 2026.10.08 (client Packages.bin after 00:54).

- Riven templates: every type publishes MergeOptions; melee gains status
  damage, the combined elements and the new factions as spliced traits.
- Dual Toxocyst Evolution 3B: +70% base damage became +70% toxin.
- Latron Prime Incarnon wave: projectiles beyond the first use the ordinary
  Latron copy (MultiShotProjectileType), 80 explosion and 32% / 3.0x crit.
"""
import copy

import pytest

import app
from wfarsenal.damage import ModEffect, apply_mods


def _weapon(name):
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)


def test_melee_spliced_traits_and_recipes_come_from_the_templates():
    bases = app.RIVEN_BASE_VALUES["melee"]
    assert (bases["SD"], bases["VI"], bases["FO"], bases["SL"]) == pytest.approx((90.0, 90.0, 45.0, 119.7))
    recipes = app.EXPORTS["rivenTemplates"]["fusionRecipes"]
    melee = {(r["result"], r["primary"], r["secondary"]) for r in recipes if r["weaponType"] == "melee"}
    assert {("SL", "K", "J"), ("HD", "U", "O"), ("VI", "6", "5"), ("SD", "K", "2")} <= melee
    assert {r["sourceKind"] for r in recipes} == {"raw-merge-options"}


def test_dual_toxocyst_neurotoxin_adds_toxin():
    branch = _weapon("Dual Toxocyst")["incarnon"]["tiers"][3]["branches"][1]
    effects = [*branch["effects"], *(e for c in branch["conditionalEffects"] for e in c["effects"])]
    assert {(e["upgradeType"], e["damageType"]) for e in effects} == {("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "DT_POISON")}


def test_latron_prime_incarnon_multishot_copies_are_weaker():
    weapon = _weapon("Latron Prime")
    bare = copy.deepcopy(weapon)
    bare["fireModes"][1].pop("multishotCopy")
    fx = [ModEffect("WEAPON_FIRE_ITERATIONS", "STACKING_MULTIPLY", 1.0)]  # two projectiles
    direct, plain = apply_mods(weapon, fx, fire_mode=1), apply_mods(bare, fx, fire_mode=1)
    assert sum(direct.damage_types.values()) == pytest.approx(sum(plain.damage_types.values()))
    assert direct.crit_chance == pytest.approx((plain.crit_chance + 0.32) / 2, rel=1e-6)
    radial_mode = dict(weapon["fireModes"][1], __radialPart__=True)
    radial = apply_mods({**weapon, "fireModes": [weapon["fireModes"][0], radial_mode]}, fx, fire_mode=1)
    assert sum(radial.damage_types.values()) / sum(plain.damage_types.values()) == pytest.approx((1 + 80 / 140) / 2)
    single = apply_mods(weapon, [], fire_mode=1)
    assert single.crit_chance == pytest.approx(apply_mods(bare, [], fire_mode=1).crit_chance)
