"""Independently moddable Warframe forms (Sevagoth's Shadow), 2026-10-26."""
from __future__ import annotations

import json
import subprocess

import pytest

import app
from wfarsenal import exalted
from wfarsenal.simulator import SimulationError

SHADOW = "/Lotus/Powersuits/Wraith/Reaper"
SHADOW_PRIME = "/Lotus/Powersuits/Wraith/SevagothShadowPrime"
SEVAGOTH = "/Lotus/Powersuits/Wraith/Wraith"
CLAWS = "/Lotus/Powersuits/Wraith/ReaperMeleeWeapon"
BLIND_RAGE = "/Lotus/Upgrades/Mods/Warframe/DualStat/CorruptedPowerEfficiencyWarframe"


def _form(path=SHADOW):
    return next(row for row in app.WARFRAME_CATALOG["warframeForms"] if row["path"] == path)


def _scalar(result, slot, scalar_id):
    return next(row for row in result["abilityScalars"][slot]["scalars"] if row["id"] == scalar_id)


def _weapon(path=CLAWS):
    return next(row for row in app.EXPORTS["weapons"] if row["path"] == path)


def _ability_strength_invigoration():
    return next(
        row for row in app.WARFRAME_ENGINE.invigoration
        if any(effect.get("stat") == "abilityStrength" for effect in row.get("effects") or ())
    )


def test_catalog_has_two_attached_forms_not_standalone_frames():
    assert len(app.WARFRAME_CATALOG["warframeForms"]) == 2
    assert not {SHADOW, SHADOW_PRIME} & {row["path"] for row in app.WARFRAME_CATALOG["warframes"]}
    ordinary = _form()
    prime = _form(SHADOW_PRIME)
    assert ordinary["parentFrameId"] == SEVAGOTH
    assert prime["parentFrameId"] == "/Lotus/Powersuits/Wraith/SevagothPrime"
    expected = {"health": 370, "shield": 185, "armor": 475, "energy": 150, "sprint": 1.1}
    assert ordinary["rank30Panel"] == pytest.approx(expected)
    assert prime["rank30Panel"] == pytest.approx(expected)
    assert ordinary["slotPolarities"]["normal"] == [None, None, None, "AP_ATTACK", None, None, None, "AP_ATTACK"]
    assert prime["slotPolarities"]["normal"] == ["AP_ATTACK", None, None, "AP_ATTACK", "AP_TACTIC", None, None, "AP_DEFENSE"]
    assert ordinary["slotPolarities"]["aura"] == prime["slotPolarities"]["aura"] == "AP_ATTACK"
    for form in (ordinary, prime):
        assert [row["nameEn"] for row in form["abilities"]] == ["Embrace", "Consume", "Death's Harvest", "Reunite"]
        assert form["inheritance"] == {"shardsFromParent": True, "invigorationFromParent": True, "helminth": False}
        for ability in form["abilities"]:
            assert (app.ROOT / "frontend" / ability["iconAsset"].lstrip("/")).is_file(), ability["iconAsset"]
        assert (app.ROOT / "frontend" / form["portraitAsset"].lstrip("/")).is_file()


def test_shadow_ability_vectors_and_strength_efficiency_scaling():
    result = app.WARFRAME_ENGINE.calculate({"frameId": SHADOW})
    assert _scalar(result, 0, "range_0")["values"] == [10, 12, 15, 20]
    assert _scalar(result, 0, "duration_1")["values"] == [5, 6, 7, 8]
    assert _scalar(result, 1, "radiation_damage")["values"] == [1000, 1500, 2000, 2500]
    assert _scalar(result, 1, "life_steal_1")["values"] == [10, 15, 20, 25]
    assert _scalar(result, 1, "range_2")["values"] == [5, 8, 11, 14]
    assert _scalar(result, 2, "damage_vulnerability_1")["values"] == [10, 20, 30, 50]
    assert result["abilityScalars"][1]["energyCost"]["activation"] == 25

    raged = app.WARFRAME_ENGINE.calculate({
        "frameId": SHADOW,
        "normalMods": [{"path": BLIND_RAGE, "rank": 10, "slot": 0}],
    })
    assert raged["finalPanel"]["abilityStrength"] == pytest.approx(1.99)
    assert _scalar(raged, 1, "radiation_damage")["value"] == pytest.approx(2500 * 1.99)
    assert _scalar(raged, 1, "life_steal_1")["value"] == pytest.approx(25 * 1.99)
    assert _scalar(raged, 2, "damage_vulnerability_1")["value"] == pytest.approx(50 * 1.99)
    assert raged["abilityScalars"][1]["energyCost"]["activation"] == pytest.approx(25 * 1.55)


def test_shadow_has_independent_capacity_and_fixed_abilities():
    steel_charge = next(row for row in app.WARFRAME_ENGINE.mods if row["nameEn"] == "Steel Charge")
    result = app.WARFRAME_ENGINE.calculate({"frameId": SHADOW_PRIME, "aura": {"path": steel_charge["path"], "rank": 5}})
    assert result["capacityBreakdown"]["aura"]["polarityRelation"] == "matched"
    assert result["capacityBreakdown"]["limit"] > 60
    with pytest.raises(SimulationError, match="固定技能组"):
        app.WARFRAME_ENGINE.calculate({
            "frameId": SHADOW,
            "helminthReplacement": {"slot": 0, "abilityId": "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility"},
        })
    # Carrier-only Reap/Sow augments must not leak into the Shadow loadout.
    with pytest.raises(SimulationError, match="not compatible"):
        app.WARFRAME_ENGINE.calculate({
            "frameId": SHADOW,
            "normalMods": [{"path": "/Lotus/Powersuits/Wraith/WraithReapAugmentCard", "rank": 5, "slot": 0}],
        })


def test_claws_link_to_shadow_not_the_carrier_and_legacy_links_migrate():
    catalog_row = next(row for row in app.CATALOG["weapons"] if row["path"] == CLAWS)
    assert [row["id"] for row in catalog_row["exalted"]["frames"]] == [SHADOW]
    assert catalog_row["exalted"]["frames"][0]["formKind"] == "shadow"
    assert app.warframe_calculate_payload({"frameId": SEVAGOTH})["exalted"] == []
    assert [row["nameEn"] for row in app.warframe_calculate_payload({"frameId": SHADOW})["exalted"]] == ["Shadow Claws"]
    config = {"normalMods": [{"path": BLIND_RAGE, "rank": 10}]}
    for frame_id in (SHADOW, SEVAGOTH):
        context = exalted.frame_context(app.WARFRAME_ENGINE, _weapon(), {"frameId": frame_id, "config": config})
        assert context["frameId"] == SHADOW
        assert context["panel"]["abilityStrength"] == pytest.approx(1.99)


def test_parent_mods_do_not_leak_but_shards_and_invigoration_are_inherited():
    # A carrier-only Blind Rage must not become a free Shadow MOD.
    context = exalted.frame_context(app.WARFRAME_ENGINE, _weapon(), {
        "frameId": SHADOW,
        "config": {},
        "parentConfig": {"normalMods": [{"path": BLIND_RAGE, "rank": 10}]},
    })
    assert context["panel"]["abilityStrength"] == pytest.approx(1.0)

    shard = next(
        row for row in app.WARFRAME_ENGINE.shards
        if not row["tau"] and any(effect.get("stat") == "abilityStrength" for effect in row.get("effects") or ())
    )
    inherited = {
        "normalMods": [{"path": BLIND_RAGE, "rank": 10}],
        "shards": [{"path": shard["path"], "tau": False}],
        "invigoration": [_ability_strength_invigoration()["path"]],
    }
    context = exalted.frame_context(app.WARFRAME_ENGINE, _weapon(), {
        "frameId": SHADOW,
        "config": {},
        "parentConfig": inherited,
    })
    # +10% shard and the carrier's Invigoration apply; its +99% Blind Rage does not.
    assert context["panel"]["abilityStrength"] > 1.1
    assert context["parentFrameId"] == SEVAGOTH


def _functions(source: str, names: list[str]) -> str:
    chunks = []
    for index, name in enumerate(names):
        start = source.index(f"function {name}(")
        next_starts = [source.find("\nfunction ", start + 1)]
        end = next_starts[0] if next_starts[0] >= 0 else len(source)
        chunks.append(source[start:end])
    return "\n".join(chunks)


def test_frontend_form_switch_preserves_four_independent_configs(tmp_path):
    source = (app.ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
    names = [
        "warframeId", "warframeFormRecords", "activeWarframeRecord", "isAlternateWarframeForm",
        "warframeFormOptions", "warframeStoredConfig", "loadWarframeFormConfigs", "warframeSelection",
        "frameSlotPolarities", "emptyWarframeSnapshot", "captureWarframeConfig", "persistWarframeConfig",
        "selectWarframeFrame", "switchWarframeForm", "switchWarframeConfig",
    ]
    script = tmp_path / "check-forms.cjs"
    script.write_text(
        "const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');\n"
        "const WARFRAME_CONFIG_STORAGE_KEY='test-warframe-store';let warframeRequestId=0;\n"
        "const root='/Lotus/Powersuits/Wraith/Wraith',shadow='/Lotus/Powersuits/Wraith/Reaper';\n"
        "const frame={id:root,path:root,nameEn:'Sevagoth',slotPolarities:{aura:null,exilus:null,normal:Array(8).fill(null)}};\n"
        "const form={id:shadow,path:shadow,parentFrameId:root,isAlternateForm:true,formKind:'shadow',formLabelZh:'幽影',slotPolarities:{aura:'AP_ATTACK',exilus:null,normal:Array(8).fill(null)}};\n"
        "const saved={};\n"
        "const localStorage={getItem:(key)=>saved[key]||null,setItem:(key,value)=>{saved[key]=value}};\n"
        "const state={warframeCatalog:{buildLabel:'test'},warframeBuild:{frame:null,activeForm:'main',activeConfig:'A',store:{},result:null}};\n"
        "const ui={};\n"
        "function warframeRows(key){return key==='warframeForms'?[form]:key==='warframes'?[frame]:[]}\n"
        "function exaltedWarframeStore(){return state.warframeBuild.store}\n"
        "function applyWarframeConfig(config){Object.assign(state.warframeBuild,emptyWarframeSnapshot(activeWarframeRecord()),config||{},{result:null,loadedConfig:config})}\n"
        "function scheduleWarframeCalculation(){}\n"
        + _functions(source, names)
        + "\nselectWarframeFrame(frame);\n"
        + "const build=state.warframeBuild;\n"
        + "build.normalMods[0]={path:'/main-mod',rank:10};persistWarframeConfig();\n"
        + "switchWarframeForm(shadow);\n"
        + "build.normalMods[0]={path:'/shadow-a',rank:10};build.shards=[{path:'/inherited-shard',tau:false}];build.invigoration=['/inherited-invigoration'];persistWarframeConfig();\n"
        + "switchWarframeConfig('B');build.aura={path:'/shadow-b-aura',rank:5};persistWarframeConfig();\n"
        + "switchWarframeConfig('A');assert.equal(build.loadedConfig.normalMods[0].path,'/shadow-a');\n"
        + "switchWarframeForm('main');assert.equal(build.loadedConfig.normalMods[0].path,'/main-mod');\n"
        + "switchWarframeForm(shadow);assert.equal(build.loadedConfig.normalMods[0].path,'/shadow-a');\n"
        + "const stored=JSON.parse(saved[WARFRAME_CONFIG_STORAGE_KEY])[root];\n"
        + "assert.equal(stored.A.normalMods[0].path,'/main-mod');\n"
        + "assert.equal(stored.forms[shadow].A.normalMods[0].path,'/shadow-a');\n"
        + "assert.equal(stored.forms[shadow].B.aura.path,'/shadow-b-aura');\n"
        + "assert.deepEqual(stored.forms[shadow].A.shards,[]);assert.deepEqual(stored.forms[shadow].A.invigoration,[]);\n"
        + "assert.equal(warframeStoredConfig(shadow,'A').parentConfig.normalMods[0].path,'/main-mod');\n"
        + "process.stdout.write(JSON.stringify(stored));\n",
        encoding="utf-8",
    )
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", check=True)
    stored = json.loads(result.stdout)
    assert stored["forms"][SHADOW]["A"]["normalMods"][0]["path"] == "/shadow-a"
