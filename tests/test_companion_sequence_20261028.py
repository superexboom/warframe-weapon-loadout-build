"""Deconstructor per-launch IPS lanes proved by build2026.10.22.13.12.

Raw list and native select-before-increment loop are independently recorded in
companion-followthrough/sequence-contract.json. These regression assertions keep
the exact lanes; they do not average IPS or claim bounce/return timing fidelity.
"""
from copy import deepcopy
import json

import pytest

import app
from wfarsenal import companion, combat_replay, native_replay
from wfarsenal.damage import ModEffect, Scenario, apply_mods
from wfarsenal.manual_combat import prepare


def _weapon(name):
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)


def _prepare(name, effects=()):
    weapon = _weapon(name)
    scenario = Scenario(trigger_policy="emergent", combat_state={"companion": True})
    combat = prepare(dict(weapon=weapon, fire_mode=0, effects=list(effects), scenario=scenario), [], [])
    return weapon, scenario, combat


@pytest.mark.parametrize("name,amount", [("Deconstructor",130.),("Deconstructor Prime",160.)])
def test_audited_package_data_keeps_three_distinct_launch_lanes(name, amount):
    sequence = companion.projectile_sequence(_weapon(name))
    assert sequence["initialIndex"] == 0
    assert sequence["length"] == 3
    assert sequence["advanceOn"] == "projectile-spawn"
    assert sequence["admission"] == "single-projectile-launch"
    assert [lane["damageTypes"] for lane in sequence["lanes"]] == [
        {"DT_IMPACT":amount}, {"DT_PUNCTURE":amount}, {"DT_SLASH":amount}]
    assert [lane["procChance"] for lane in sequence["lanes"]] == [.25,.25,.25]
    assert [next(suffix for suffix in ("Front","Rear","Mid") if lane["projectile"].endswith(suffix))
            for lane in sequence["lanes"]] == ["Front","Rear","Mid"]
    assert sequence["sourceFields"]["maxActiveProjectiles"] == 3


def test_sequence_lookup_respects_selected_mode_and_returns_an_isolated_profile():
    weapon = _weapon("Deconstructor")
    sequence = companion.projectile_sequence(weapon)
    sequence["lanes"][0]["damageTypes"]["DT_IMPACT"] = -1
    assert companion.projectile_sequence(weapon)["lanes"][0]["damageTypes"] == {"DT_IMPACT":130.}
    assert companion.projectile_sequence({**weapon,"__selectedFireMode__":1}) is None
    assert companion.projectile_sequence(_weapon("Deth Machine Rifle")) is None


@pytest.mark.parametrize("name,amount", [("Deconstructor",130.),("Deconstructor Prime",160.)])
def test_resolver_selects_source_ips_before_applying_typed_and_elemental_mods(name, amount):
    effects = [ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED","ADD",.9,damage_type="DT_SLASH"),
               ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED","ADD",.9,damage_type="DT_FIRE")]
    weapon, _, combat = _prepare(name, effects)
    source_before = deepcopy(weapon)
    expected = [{"DT_IMPACT":amount,"DT_FIRE":amount*.9},
                {"DT_PUNCTURE":amount,"DT_FIRE":amount*.9},
                {"DT_SLASH":amount*1.9,"DT_FIRE":amount*.9}]
    # Changing phase back and forth must not alias the prepared record cache.
    for index in (0,1,2,0,2,1):
        stats, radial = combat["resolve"]("selected",{"__projectileSequenceIndex":index},0)
        assert stats.damage_types == pytest.approx(expected[index])
        assert stats.status_chance == .25
        assert radial is None
    assert weapon == source_before
    assert "companion-projectile-damage-sequence-unmodeled" not in combat["unsupported"]
    assert {"companion-projectile-bounce-return-timing-unverified",
            "companion-active-projectile-refire-limit-unmodeled"}.issubset(combat["unsupported"])


def test_importer_validates_literal_source_lanes_with_a_local_fixture():
    from tools.import_companion_projectile_sequences import weapon_sequence, WEAPONS, PACKAGE_SHA256, CLIENT_SHA256
    raw = {
        "Behaviors": [{
            "fire:GlaiveProjectileFireBehavior": {
                "advanceProjectileSequenceOnFire":1,"chargedProjectileSequenceList":[],
                "projectileSequenceList":["Front","Rear","Mid"],"fireIterations":1},
            "state:WeaponGrenadeStateBehavior": {
                "TrackProjectiles":1,"MaxNumProjectiles":3,"ResetRefireWhenActiveProjectiles":1}}]}
    parts = {
        "Front":{"AttackData":{"Type":"DT_IMPACT","Amount":130,"ProcChance":.25},"DealDamageThroughImpactBehavior":1},
        "Rear":{"AttackData":{"Type":"DT_PUNCTURE","Amount":130,"ProcChance":.25},"DealDamageThroughImpactBehavior":1},
        "Mid":{"AttackData":{"Type":"DT_SLASH","Amount":130,"ProcChance":.25},"DealDamageThroughImpactBehavior":1}}

    class LocalPackages:
        def resolve(self,path):
            return raw if path == WEAPONS[0] else parts[path]
        def locate(self,owner,name):
            return name if name in parts else None

    imported = weapon_sequence(LocalPackages(),WEAPONS[0])
    assert [row["damageTypes"] for row in imported["lanes"]] == [
        {"DT_IMPACT":130.},{"DT_PUNCTURE":130.},{"DT_SLASH":130.}]
    sources = companion.projectile_sequence_reference()["sources"]
    assert sources["packagesBinSha256"] == PACKAGE_SHA256
    assert sources["clientSha256"] == CLIENT_SHA256
    parts["Rear"]["AttackData"]["Type"] = "DT_IMPACT"
    with pytest.raises(ValueError,match="audited IPS order changed"):
        weapon_sequence(LocalPackages(),WEAPONS[0])


@pytest.mark.parametrize("native", [False,True])
@pytest.mark.parametrize("name,damage", [("Deconstructor",1040.),("Deconstructor Prime",1280.)])
def test_replay_runs_distinct_ips_phases_without_averaging(native,name,damage,monkeypatch):
    if native and not getattr(native_replay.wfcore,"COMPANION_PROJECTILE_SEQUENCE",0):
        pytest.skip("native core lacks projectile sequence phase support")
    weapon, scenario, combat = _prepare(name, [ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED","ADD",1.,damage_type="DT_SLASH")])
    original = combat["resolve"]
    phases = []

    def resolve(form,stacks,live_types,*args):
        from dataclasses import replace
        phases.append(int(stacks.get("__projectileSequenceIndex",0)))
        part, radial = original(form,stacks,live_types,*args)
        return replace(part,status_chance=0.),radial

    combat["resolve"] = resolve
    stats = apply_mods(weapon,[ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED","ADD",1.,damage_type="DT_SLASH")],scenario=scenario)
    from dataclasses import replace
    stats = replace(stats,status_chance=0.)
    monkeypatch.setattr(native_replay,"ENABLED",native)
    before = native_replay.STATS["native"]
    target = dict(health=1e12,shield=0.,armour=0.,overguard=0.,baseLevel=1,
                  healthType="",armourType="",shieldType="",damageController="custom",
                  hitProxies=[{"bone":"GAME_C1_SPINE1","damageAtten":1.}])
    # Six launches at0,.75,1.5,2.25,3,3.75 pay2*(1+1+2)*base.
    # A wrongly static Impact-only lane would pay6*base instead.
    result = combat_replay.replay(stats,target,attacks_per_second=stats.sustained_attack_rate,
                                 window_seconds=4.,combat=combat,trigger_sources=[],
                                 collect_timeline=not native,headshot_chance=0.)
    assert {0,1,2}.issubset(phases)
    assert result["shots"] == 6
    if native:
        assert native_replay.STATS["native"] > before
    assert result["totalWindowDamage"] == pytest.approx(damage)


def test_old_native_core_without_sequence_feature_falls_back(monkeypatch):
    from types import SimpleNamespace
    weapon, scenario, combat = _prepare("Deconstructor")
    stats = apply_mods(weapon,[],scenario=scenario)
    monkeypatch.setattr(native_replay,"ENABLED",True)
    monkeypatch.setattr(native_replay,"wfcore",SimpleNamespace())
    assert not native_replay.supported(stats,{"combat":combat,"collect_timeline":False})


@pytest.mark.parametrize("native", [False,True])
def test_target_death_does_not_reset_sequence_phase(native,monkeypatch):
    from dataclasses import replace
    if native and not getattr(native_replay.wfcore,"COMPANION_PROJECTILE_SEQUENCE",0):
        pytest.skip("native core lacks projectile sequence phase support")
    weapon,scenario,combat = _prepare("Deconstructor",[
        ModEffect("WEAPON_PERCENT_BASE_DAMAGE_ADDED","ADD",1.,damage_type="DT_SLASH")])
    original = combat["resolve"]
    def resolve(*args):
        part,radial = original(*args)
        return replace(part,status_chance=0.),radial
    combat["resolve"] = resolve
    stats = replace(apply_mods(weapon,[],scenario=scenario),status_chance=0.)
    monkeypatch.setattr(native_replay,"ENABLED",native)
    before = native_replay.STATS["native"]
    target = dict(health=260.,shield=0.,armour=0.,overguard=0.,baseLevel=1,
                  healthType="",armourType="",shieldType="",damageController="custom")
    result = combat_replay.replay(stats,target,attacks_per_second=stats.sustained_attack_rate,
                                 window_seconds=4.,combat=combat,trigger_sources=[],
                                 collect_timeline=not native,headshot_chance=0.)
    # I130/P130 kill body1; S260 kills body2; then identical second cycle.
    # Reset-on-death would keep producing I/P and yield only3kills/780damage.
    assert result["shots"] == 6
    assert result["killEvents"] == 4
    assert result["totalWindowDamage"] == pytest.approx(1040.)
    if native:
        assert native_replay.STATS["native"] > before


@pytest.mark.parametrize("native", [False,True])
def test_slash_lane_can_create_bleed_after_source_selection(native,monkeypatch):
    from dataclasses import replace
    if native and not getattr(native_replay.wfcore,"COMPANION_PROJECTILE_SEQUENCE",0):
        pytest.skip("native core lacks projectile sequence phase support")
    weapon,scenario,combat = _prepare("Deconstructor")
    original = combat["resolve"]
    def resolve(*args):
        part,radial = original(*args)
        return replace(part,status_chance=1.),radial
    combat["resolve"] = resolve
    stats = replace(apply_mods(weapon,[],scenario=scenario),status_chance=1.)
    monkeypatch.setattr(native_replay,"ENABLED",native)
    before = native_replay.STATS["native"]
    target = dict(health=1e9,shield=0.,armour=0.,overguard=0.,baseLevel=1,
                  healthType="",armourType="",shieldType="",damageController="custom")
    result = combat_replay.replay(stats,target,attacks_per_second=stats.sustained_attack_rate,
                                 window_seconds=3.1,combat=combat,trigger_sources=[],
                                 collect_timeline=not native,headshot_chance=0.)
    assert result["procCounts"].get("DT_SLASH",0.) > 0.
    assert result["dotWindow"] > 0.
    if native:
        assert native_replay.STATS["native"] > before


def test_each_lane_carries_its_native_projectile_identity_into_mod_application(monkeypatch):
    from wfarsenal import damage
    original = damage.apply_mods_spec
    identities = []
    def capture(record, *args, **kwargs):
        index = kwargs.get('fire_mode',0)
        identities.append(record['fireModes'][index]['damage'].get('projectile'))
        return original(record,*args,**kwargs)
    monkeypatch.setattr(damage,'apply_mods_spec',capture)
    _,_,combat=_prepare('Deconstructor')
    for phase in range(3):
        combat['resolve']('selected',{'__projectileSequenceIndex':phase},0)
    expected=[lane['projectile'] for lane in combat['projectileSequence']['lanes']]
    assert identities == expected
