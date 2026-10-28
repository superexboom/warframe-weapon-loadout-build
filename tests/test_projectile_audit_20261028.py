"""Regression at the independent preview/lifecycle boundary; not game proof."""
from copy import deepcopy
from dataclasses import replace

import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, damage_against
from wfarsenal.manual_combat import prepare
from wfarsenal.projectile_events import evaluate_projectile_events


def stug():
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Stug")


def enemy():
    return dict(health=1e12, armour=0., shield=0., baseLevel=1,
                hitProxies=[dict(part="HEAD", damageAtten=2., criticalMultiplier=2.)])


def test_stug_parent_death_fields_are_alternatives_not_two_explosions():
    result = evaluate_projectile_events(stug(), [], fire_mode=2)
    total = result["totals"]["moddedDamage"]
    assert total == dict(known=200., minimum=200., maximum=200.)
    explosion = next(e for e in result["events"] if e["kind"] == "explosion")
    embedded = next(e for e in result["events"] if e["kind"] == "embedDeath")
    assert explosion["aggregate"] is True
    assert embedded["aggregate"] is False and embedded["alternativeOf"] == explosion["id"]
    assert embedded["id"] in result["excluded"]


@pytest.mark.parametrize("head", [False, True])
def test_stug_preview_uses_audited_area_direct_parent_and_excludes_gunco(head):
    weapon = stug()
    effects = [ModEffect("WEAPON_DAMAGE_AMOUNT", "ADD_BASE", 300.),
               ModEffect("WEAPON_HEADSHOT_MULTIPLIER", "ADD", .3),
               ModEffect("WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE", "STACKING_MULTIPLY", 1.2),
               ModEffect("WEAPON_DAMAGE_BODY_PART", "STACKING_MULTIPLY", 3.5, symbol_filter="HEAD")]
    scenario = Scenario(victim_status_count=3)
    where = "head" if head else "body"
    preview = evaluate_projectile_events(weapon, effects, fire_mode=2, scenario=scenario,
                                         target=enemy(), hit_location=where)
    main = next(e for e in preview["events"] if e["kind"] == "explosion")
    # Independent route: the timeline constructs its own native-backed part.
    combat = prepare(dict(weapon={**weapon, "isIncarnonForm": True}, fire_mode=2,
                          effects=effects, scenario=scenario), [], [])
    stats, _ = combat["resolve"]("selected", {}, 3)
    part = stats._stackable[1]["explosion"]
    assert main["hitClassification"] == "area-direct"
    assert main["perOccurrence"]["targetPerHit"] == damage_against(part, enemy(), hit_location=where)["perHit"]
    assert main["perOccurrence"]["moddedDamage"] == 500.
    assert all(p.radial_only for key,p in stats._stackable[1].items() if key != "explosion")


def test_changed_parent_projectile_cannot_inherit_stug_exception():
    weapon = deepcopy(stug())
    weapon["fireModes"][2]["damage"]["projectile"] = "/unverified/projectile"
    result = evaluate_projectile_events(weapon, [], fire_mode=2)
    assert all("hitClassification" not in row for row in result["events"])
    assert result["totals"]["moddedDamage"]["maximum"] == 400.


def test_unknown_embed_death_payload_is_not_assumed_to_be_same_parent_blast():
    weapon = deepcopy(stug())
    raw = next(e for e in weapon["fireModes"][2]["projectileEvents"] if e["kind"] == "embedDeath")
    raw["damage"]["types"] = {"DT_CORROSIVE": 300.}
    raw["damage"]["total"] = 300.
    result = evaluate_projectile_events(weapon, [], fire_mode=2)
    embedded = next(e for e in result["events"] if e["kind"] == "embedDeath")
    assert embedded["aggregate"] is True
    assert "alternativeOf" not in embedded


def test_stug_zero_crit_head_bracket_is_independent_of_head_location_damage():
    effects = [ModEffect("WEAPON_CRIT_CHANCE", "SET", 0.),
               ModEffect("WEAPON_DAMAGE_AMOUNT", "ADD_BASE", 300.),
               ModEffect("WEAPON_HEADSHOT_MULTIPLIER", "ADD", .3)]
    def amount(where):
        result = evaluate_projectile_events(stug(), effects, fire_mode=2,
                                            target=enemy(), hit_location=where)
        return next(e for e in result["events"] if e["kind"] == "explosion")["perOccurrence"]["targetPerHit"]
    # Native main200 + evolution-style flat300; head bonus1.3, not the
    # target's ordinary location multiplier2. Child damage isn't in this row.
    assert amount("body") == 500.
    assert amount("head") == 650.


def test_child_payload_cannot_inherit_parent_classification_from_equal_damage():
    weapon = deepcopy(stug())
    mode = weapon["fireModes"][2]
    child = deepcopy(next(e for e in mode["projectileEvents"] if e["kind"] == "explosion"))
    child.update(id="child:explosion", projectile="/unverified/child")
    mode["projectileEvents"].append(child)
    result = evaluate_projectile_events(weapon, [], fire_mode=2)
    row = next(e for e in result["events"] if e["id"] == "child:explosion")
    assert "hitClassification" not in row
