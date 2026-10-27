import json
from copy import deepcopy
from tools.incremental_bake import select, digest


def snapshot():
    return dict(schema=1, cacheVersion=26, buildLabel="b", stances="s",
                shared={"optimizer.py":"same","mods.json":"same"},
                records={"/A":"a", "/B":"b"}, inputs="old")


def entries():
    return {json.dumps(dict(weapon=w, profile="deep")): {"counts":{"2":{},"3":{}}}
            for w in ("/A", "/B", "/A#/part1+/part2+/part3", "/missing")}


def test_one_weapon_change_preserves_unaffected_and_assembled_identity():
    old=snapshot();new=deepcopy(old);new["inputs"]="new";new["records"]["/B"]="changed"
    kept,reason=select(old,new,entries())
    assert {json.loads(k)["weapon"] for k in kept}=={"/A","/A#/part1+/part2+/part3"}
    assert reason=="verified-record-dependencies"


def test_global_engine_or_rules_change_drops_every_entry():
    old=snapshot()
    for key in ("optimizer.py","mods.json","new-runtime-module.py"):
        new=deepcopy(old);new["shared"][key]="changed"
        assert select(old,new,entries())==({},"shared-dependencies-changed")


def test_deleted_unknown_and_malformed_contexts_never_reuse():
    old=snapshot();new=deepcopy(old);del new["records"]["/A"]
    values=entries();values["bad-json"]={};values['{"weapon":null}']={}
    kept,_=select(old,new,values)
    assert {json.loads(k)["weapon"] for k in kept}=={"/B"}


def test_object_identity_detects_nested_output_or_dependency_mutation():
    body=dict(inventory=snapshot(),entries=entries());before=digest(body)
    body["inventory"]["records"]["/A"]="different"
    assert digest(body)!=before


def test_changes_in_common_parts_and_native_library_reject_reuse():
    old=snapshot()
    for filename in ("kitguns.json", "zaws.json", "wfcore.pyd", "bot_riven.py", "bot-policy.json"):
        old["shared"][filename]="old"
        new=deepcopy(old);new["shared"][filename]="new"
        assert not select(old,new,entries())[0]


def test_reused_payload_is_preserved_without_recomputing_or_relabelling_scores():
    old=snapshot();current=deepcopy(old);current["inputs"]="new"
    values=entries();key=json.dumps(dict(weapon="/A",profile="deep"))
    values[key]={"contextHash":"a"*20,"score":123.456,"counts":{"3":{"fatal":["3"],"fatalAbove":{"3":97.3}}}}
    retained,_=select(old,current,values)
    assert retained[key] is values[key]
