"""Exalted weapons (2026-10-21): catalog, linked frame, ability-scaled damage, energy readout."""
import pytest

import app
from wfarsenal import exalted

ENEMY = app.MANUAL_ENEMIES[0]["path"]
BLADE = "/Lotus/Powersuits/Excalibur/DoomSword"
BLIND_RAGE = "/Lotus/Upgrades/Mods/Warframe/DualStat/CorruptedPowerEfficiencyWarframe"


def _simulate(path, **extra):
    return app.simulate_manual_payload({"weapon": path, "mods": [], "enemy": ENEMY, **extra})


def test_catalog_lists_every_playable_exalted_weapon_without_rivens():
    rows = [w for w in app.CATALOG["weapons"] if w.get("exalted")]
    assert len(rows) == 35
    assert all(not w["analysisAvailable"] for w in rows)
    by_name = {w["nameEn"]: w for w in rows}
    assert by_name["Regulators"]["buildAvailable"]
    assert by_name["Landslide Fists"]["available"]
    assert by_name["Whipclaw"]["exalted"]["tier"] == "cast"
    assert by_name["Exalted Blade"]["exalted"]["frames"][0]["nameEn"] == "Excalibur"


def test_base_damage_takes_the_ability_figure_times_strength():
    plain = _simulate(BLADE)
    assert plain["moddedStats"]["totalDamage"] == pytest.approx(250.0)
    config = {"normalMods": [{"path": BLIND_RAGE, "rank": 10}]}
    raged = _simulate(BLADE, exaltedFrame={"frameId": "/Lotus/Powersuits/Excalibur/Excalibur", "configName": "A", "config": config})
    strength = raged["exalted"]["panel"]["abilityStrength"]
    assert strength == pytest.approx(1.99)
    assert raged["moddedStats"]["totalDamage"] == pytest.approx(250.0 * strength)
    # Blind Rage costs 55% Efficiency: activation and drain rise by 1.55x.
    energy = raged["exalted"]["energy"]
    assert energy["activation"] == pytest.approx(25 * 1.55)
    assert energy["drainPerSecond"] == pytest.approx(2.5 * 1.55)


def test_native_exalted_bonus_keeps_full_multiplier_before_strength():
    result = _simulate("/Lotus/Powersuits/Cowgirl/SlingerPistols")
    # 50 base x (1 + 150% x Strength) x 2.5 full ramp.
    assert result["moddedStats"]["totalDamage"] == pytest.approx(50 * 2.5 * 2.5)
    from wfarsenal.damage import Scenario,apply_mods
    cyte=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Neutralizer')
    strong=exalted.apply_damage_rules(cyte,{'panel':{'abilityStrength':2.}})
    assert strong['exaltedDamageRule']['bonus']==1.5
    value=apply_mods(strong,exalted.weapon_effects(strong),scenario=Scenario())
    assert value.total_damage==pytest.approx(255.*2.5)
    linked=_simulate(cyte['path'],windowSeconds=.1,exaltedFrame={
        'frameId':cyte['exalted']['framePaths'][0],
        'config':{'normalMods':[{'path':BLIND_RAGE,'rank':10}]}})
    assert linked['exalted']['panel']['abilityStrength']==1.99
    assert linked['moddedStats']['totalDamage']==pytest.approx(255.*1.25*1.99)
    lizzie=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Lizzie')
    strong_guitar=exalted.apply_damage_rules(lizzie,{'panel':{'abilityStrength':2.}})
    assert strong_guitar['exaltedDamageRule']['bonus']==1.5
    assert apply_mods(strong_guitar,exalted.weapon_effects(strong_guitar),scenario=Scenario()).total_damage==212.5
    glory=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Glory')
    strong_glory=exalted.apply_damage_rules(glory,{'panel':{'abilityStrength':2.}})
    lane=strong_glory['fireModes'][0]['damage']
    assert lane['source']=='ExplosiveAttack' and lane['total']==300.
    assert len(lane['components'])==1 and lane['components'][0]['total']==300.


def test_cast_weapons_hit_once_per_cast_with_the_ability_combo():
    weapon = next(w for w in app.EXPORTS["weapons"] if w["path"] == "/Lotus/Powersuits/Khora/KhoraWhipclawWeapon")
    record = exalted.apply_damage_rules(weapon, {"panel": {"abilityStrength": 1.0}})
    from wfarsenal import melee_sequence
    schedule = melee_sequence.build_schedule(record, "combo")
    hits = [s["hit"] for s in schedule["segments"]]
    assert schedule["route"] == "cast"
    assert [h["atten"] for h in hits[:3]] == [1.0, 2.0, 3.0]
    assert max(h["atten"] for h in hits) == 12.0
    assert schedule["segments"][0]["fixed"] == pytest.approx(1.1)
    result = _simulate(weapon["path"])
    cast = result["exalted"]["cast"]
    assert cast["fullCombo"] == pytest.approx(cast["firstCast"] * 12)


def test_energy_report_warns_when_the_ability_cannot_start_or_chain():
    weapon = next(w for w in app.EXPORTS["weapons"] if w["path"] == "/Lotus/Powersuits/Khora/KhoraWhipclawWeapon")
    context = {"panel": {"energy": 20.0, "abilityEfficiency": 1.0}, "ability": {"nameZh": "长鞭利爪", "energyCost": {"activation": 25.0}}}
    report = exalted.energy_report(weapon, context)
    assert report["warnings"] and "无法启动" in report["warnings"][0] and "无限能量" in report["warnings"][0]
    context["panel"]["energy"] = 40.0
    report = exalted.energy_report(weapon, context)
    assert report["casts"] == 1 and "无法触发后续连击" in report["warnings"][0]
    blade = next(w for w in app.EXPORTS["weapons"] if w["path"] == BLADE)
    ok = exalted.energy_report(blade, {"panel": {"energy": 150.0}, "ability": {"energyCost": {"activation": 25.0, "drainPerSecond": 2.5}}})
    assert ok["sustainSeconds"] == pytest.approx(50.0) and not ok["warnings"]
    short = exalted.energy_report(blade, {"panel": {"energy": 30.0}, "ability": {"energyCost": {"activation": 25.0, "drainPerSecond": 2.5}}})
    assert "无法维持" in short["warnings"][0]


def test_build_runs_on_an_exalted_weapon():
    result = app.build_weapon_payload({"weapon": BLADE, "profile": "fast"})
    assert result["exalted"]["energy"]["sustainSeconds"] == pytest.approx(50.0)
    assert result["build"]


def test_casting_speed_shortens_cast_type_weapons():
    def cast_for(family, casting_speed):
        weapon = next(w for w in app.EXPORTS["weapons"] if (w.get("exalted") or {}).get("family") == family)
        return exalted.apply_damage_rules(weapon, {"panel": {"castingSpeed": casting_speed}})["exaltedCast"]
    whip = cast_for("Khora", 0.5)  # Natural Talent +50%
    assert whip["castingSpeed"] == pytest.approx(1.5)
    assert whip["seconds"] == pytest.approx([1.1 / 1.5])
    assert cast_for("Khora", 0.0)["seconds"] == pytest.approx([1.1])
    # Blade Storm: only Ash's mark cast speeds up, the clone swing does not.
    assert cast_for("Ninja", 0.5)["seconds"] == pytest.approx([0.5 / 1.5 + 0.5667])


def _warframe_rows():
    engine = app.WARFRAME_ENGINE
    return {m["nameEn"]: m for m in engine.mods}, {a["nameEn"]: a for a in engine.arcanes}


def test_linked_config_supplies_aura_and_frame_arcanes():
    mods, arcanes = _warframe_rows()
    config = {"aura": {"path": mods["Steel Charge"]["path"], "rank": 5},
              "arcanes": [{"path": arcanes["Arcane Fury"]["path"], "rank": 5}, {"path": arcanes["Molt Augmented"]["path"], "rank": 5}]}
    link = {"frameId": "/Lotus/Powersuits/Excalibur/Excalibur", "configName": "A", "config": config}
    linked = _simulate(BLADE, exaltedFrame=link)
    # A Warframe Arcane picked on the weapon page is replaced by the config's.
    picked = _simulate(BLADE, exaltedFrame=link, arcanes=[{"path": arcanes["Arcane Avenger"]["path"], "rank": 5}])
    assert picked["moddedStats"]["totalDamage"] == pytest.approx(linked["moddedStats"]["totalDamage"])
    assert linked["moddedStats"]["totalDamage"] > _simulate(BLADE)["moddedStats"]["totalDamage"] * 1.5
    loadout = linked["exalted"]["loadout"]
    assert loadout["aura"]["counted"] and loadout["aura"]["buff"] == "steel-charge"
    assert [row["counted"] for row in loadout["arcanes"]] == [True, False]  # Molt Augmented: frame-only


def test_exalted_torso_lock_is_independent_from_native_head_damage_suppression(monkeypatch):
    rows = {w["nameEn"]: w for w in app.CATALOG["weapons"] if w.get("exalted")}
    assert rows["Regulators"]["exalted"]["headshotIssue"] and rows["Lizzie"]["exalted"]["headshotIssue"]
    assert not rows["Exalted Blade"]["exalted"]["headshotIssue"]
    body = _simulate("/Lotus/Powersuits/Cowgirl/SlingerPistols")
    head = _simulate("/Lotus/Powersuits/Cowgirl/SlingerPistols", headshotChance=0.8, enemy=app._BENCHMARK_ENEMY_PATH)
    assert head["moddedStats"]["totalDamage"] == pytest.approx(body["moddedStats"]["totalDamage"])
    assert head.get("headshotMix") is None
    assert rows['Regulators']['exalted']['headshotLocked']
    assert not rows['Lizzie']['exalted']['headshotLocked']
    lizzie=_simulate('/Lotus/Powersuits/Temple/ExaltedGuitar',headshotChance=.8,
        enemy=app._BENCHMARK_ENEMY_PATH,windowSeconds=.5)
    assert lizzie['headshotMix']['chance']==.8
    assert lizzie['headshotMix']['head']['perHit']==lizzie['headshotMix']['body']['perHit']
    from wfarsenal import damage,mods_native
    from wfarsenal.damage import ModEffect,Scenario
    monkeypatch.setattr(mods_native,'SHADOW',True)
    noctua=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Noctua')
    fx=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.)]
    normal=damage.apply_mods(noctua,fx,fire_mode=0,scenario=Scenario())
    alt=damage.apply_mods(noctua,fx,fire_mode=1,scenario=Scenario())
    assert normal.multishot==2. and not normal.ignore_headshot_bonus
    assert alt.multishot==1. and alt.ignore_headshot_bonus
    assert alt.ammo_cost==normal.ammo_cost==0.
    assert alt.fire_rate==alt.sustained_attack_rate==1./60.
    from wfarsenal import manual_combat,combat_replay,native_replay
    fight=manual_combat.prepare(dict(weapon=noctua,fire_mode=1,
        effects=[ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',3.)],scenario=Scenario()),[],[])
    st,_=fight['resolve']('selected',{},0.)
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    early=combat_replay.replay(st,target,attacks_per_second=st.fire_rate,window_seconds=59.9,
        combat=fight,collect_timeline=False)
    late=combat_replay.replay(st,target,attacks_per_second=st.fire_rate,window_seconds=60.1,
        combat=fight,collect_timeline=False)
    assert early['shots']==1 and late['shots']==2 and late['reloads']==0
    assert native_replay.STATS['native']>=before+2
    glory=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Glory')
    g=damage.apply_mods(glory,[],scenario=Scenario())
    assert g.ammo_cost==0. and g.sustained_attack_rate==g.fire_rate
    dex=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Dex Pixia')
    assert damage.apply_mods(dex,[],scenario=Scenario()).ammo_cost==1.


def test_warframe_calculate_returns_live_exalted_summary():
    mods, _ = _warframe_rows()
    plain = app.warframe_calculate_payload({"frameId": "/Lotus/Powersuits/Excalibur/Excalibur"})
    raged = app.warframe_calculate_payload({"frameId": "/Lotus/Powersuits/Excalibur/Excalibur",
                                            "normalMods": [{"path": BLIND_RAGE, "rank": 10, "slot": 0}]})
    assert [row["nameEn"] for row in plain["exalted"]] == ["Exalted Blade"]
    assert raged["exalted"][0]["baseDamage"] == pytest.approx(250 * 1.99)
    assert raged["exalted"][0]["energy"]["drainPerSecond"] > plain["exalted"][0]["energy"]["drainPerSecond"]


def test_script_driven_frame_effects_reach_the_panel():
    mods, arcanes = _warframe_rows()
    engine = app.WARFRAME_ENGINE
    frame = "/Lotus/Powersuits/Excalibur/Excalibur"

    def panel(conditionals=True, **extra):
        return engine.calculate({"frameId": frame, "applyConditionals": conditionals, **extra})["finalPanel"]
    archon = [{"path": mods["Archon Intensify"]["path"], "rank": 10, "slot": 0}, {"path": mods["Archon Stretch"]["path"], "rank": 10, "slot": 1}]
    assert panel(False, normalMods=archon)["abilityStrength"] == pytest.approx(1.3)
    triggered = panel(normalMods=archon)
    assert triggered["abilityStrength"] == pytest.approx(1.6)  # +30% after a heal, applied once
    assert triggered["energyRegen"] == pytest.approx(2.0)
    assert panel(False, aura={"path": mods["Power Donation"]["path"], "rank": 5})["abilityStrength"] == pytest.approx(0.7)
    assert panel(arcanes=[{"path": arcanes["Arcane Power Ramp"]["path"], "rank": 5}])["abilityStrength"] == pytest.approx(1.36)


def test_neutralizer_alt_keeps_native_forced_cold_count(monkeypatch):
    from wfarsenal import damage,mods_native,native_replay,combat_replay
    from wfarsenal.damage import Scenario
    from wfarsenal.extract import _projectile_damage_components
    native={'ExplosiveAttack':{'Type':'DT_FREEZE','Amount':20,'ProcChance':0,
        'ForcedProcs':['PT_CHILLED'],'ForcedProcCount':10}}
    component=_projectile_damage_components(native)[0]
    assert component['forcedProcs']==['PT_CHILLED']*10
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Neutralizer')
    assert weapon['fireModes'][1]['damage']['forcedProcs']==component['forcedProcs']
    monkeypatch.setattr(mods_native,'SHADOW',True)
    stats=damage.apply_mods(weapon,[],fire_mode=1,scenario=Scenario())
    assert stats.native_forced_procs=={'DT_FREEZE':10.}
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    result=combat_replay.replay(stats,dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1),
        attacks_per_second=.001,window_seconds=.01,combat={'resolve':lambda *_:(stats,None)},collect_timeline=False)
    assert result['procCounts']['DT_FREEZE']==10.
    assert native_replay.STATS['native']>before


def test_artemis_uses_seven_real_arrows_and_quiver_is_not_a_damage_mode(monkeypatch):
    from wfarsenal import damage,mods_native,optimizer
    from wfarsenal.damage import Scenario,ModEffect
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Artemis Bow')
    scaled=exalted.apply_damage_rules(weapon,{'panel':{'abilityStrength':2.}})
    assert scaled['fireModes'][0]['damage']['projectile'].endswith('/Projectiles/ExaltedArrow')
    monkeypatch.setattr(mods_native,'SHADOW',True)
    stats=damage.apply_mods(scaled,[],scenario=Scenario())
    assert stats.multishot==7. and stats.total_damage==pytest.approx(480.)
    assert stats.crit_chance==.25 and stats.status_chance==pytest.approx(.2)
    assert stats.damage_types==pytest.approx({'DT_IMPACT':67.2,'DT_PUNCTURE':384.,'DT_SLASH':28.8},rel=1e-6)
    modded=damage.apply_mods(scaled,[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.)],scenario=Scenario())
    assert modded.multishot==14. and modded.status_chance==stats.status_chance
    actual=_simulate(weapon['path'],windowSeconds=.1)
    assert actual['moddedStats']['perProjectileDamage']==240.
    assert actual['moddedStats']['totalDamage']==1680.
    selected,_=optimizer._select_fire_mode(weapon,0,weapon_type='rifle')
    assert exalted.apply_damage_rules(selected,{'panel':{'abilityStrength':2.}})['fireModes'][0]==scaled['fireModes'][0]
    catalog=next(w for w in app.CATALOG['weapons'] if w['path']==weapon['path'])
    assert not catalog['fireModes'][1]['available']
    with pytest.raises(app.SimulationError,match='箭袋'):_simulate(weapon['path'],fireMode=1)
    with pytest.raises(app.SimulationError,match='箭袋'):
        app.build_weapon_payload({'weapon':weapon['path'],'fireMode':1,'profile':'fast'})
    augmented=exalted.apply_damage_rules(weapon,{'panel':{'abilityStrength':1.},
        'abilityModPaths':['/Lotus/Powersuits/Ranger/RangerBowAugmentCard']})
    assert 'artemis-concentrated-arrow-not-supported-normal-arrow-policy-used' in damage.apply_mods(augmented,[],scenario=Scenario()).unsupported
