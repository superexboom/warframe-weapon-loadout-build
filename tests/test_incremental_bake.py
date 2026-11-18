import json
from copy import deepcopy
from pathlib import Path

import app
from tools.incremental_bake import SCHEMA, SHARD_SCHEMA, inventory, qualified_shard, select, shard_proof


def snapshot():
    return dict(schema=SCHEMA, cacheVersion=26, buildLabel="b", stances="s",
                shared={"optimizer.py":"same","mods.json":"same"},
                records={"/A":"a", "/A#HeavyBlade":"blade", "/B":"b"}, inputs="old")


def entries():
    return {json.dumps(dict(weapon=w, profile="deep")): {"counts":{"2":{},"3":{}}}
            for w in ("/A", "/A#HeavyBlade", "/A#HeavyBlade#strength=125#cast=1.5", "/B",
                      "/A#/part1+/part2+/part3", "/A#unknown", "/missing")}


def test_native_mode_change_keeps_unrelated_weapon_across_scenarios(monkeypatch):
    path = app.ROOT / "data/mechanics/burst-profiles.json"
    raw = path.read_bytes()
    doc = json.loads(raw)
    changed = next(p for p, r in doc["weapons"].items() if r["name"] == "Hind")
    unchanged = next(p for p, r in doc["weapons"].items() if r["name"] == "Quartakk")
    assert doc["weapons"][changed]["modes"]["0"]["count"] == 5
    old = inventory(app)
    doc["weapons"][changed]["modes"]["0"]["count"] = 6
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda f: json.dumps(doc).encode() if f == path else original_read(f))
    current = inventory(app)
    assert current["inputs"] != old["inputs"]
    assert current["shared"] == old["shared"]
    assert {p for p, h in old["records"].items() if current["records"][p] != h} == {changed}
    values = {json.dumps(dict(weapon=p, fireMode=mode, profile="deep", headshotChance=aim)):
              {"score": 123.456, "counts": {"3": {"fatal": ["3"]}}}
              for p in (changed, unchanged) for mode, aim in ((0, 0.0), (1, 0.5))}
    kept, reason = select(old, current, values)
    assert len(kept) == 2 and all(json.loads(k)["weapon"] == unchanged and v is values[k] for k, v in kept.items())
    assert reason == "verified-record-dependencies"
    # An unbound or renamed row has no proof of single-weapon ownership.
    doc["weapons"][changed + "Typo"] = doc["weapons"].pop(changed)
    assert not select(old, inventory(app), values)[0]


def test_shared_inputs_and_old_inventory_versions_drop_every_entry():
    old = snapshot()
    for name in ("optimizer.py", "mods.json", "enemies.json", "kitguns.json", "zaws.json", "wfcore.pyd"):
        current = deepcopy(old)
        current["shared"][name] = "changed"
        assert select(old, current, entries()) == ({}, "shared-dependencies-changed")
    legacy = {**old, "schema": SCHEMA - 1}
    assert not select(legacy, old, entries())[0]
    assert not select(legacy, legacy, entries())[0]


def test_context_identity_distinguishes_named_forms_from_assembly_suffixes():
    old = snapshot()
    current = deepcopy(old)
    del current["records"]["/A#HeavyBlade"]
    current["records"]["/B"] = "updated"
    values = {**entries(), "bad-json": {}, '{"weapon":null}': {}}
    kept, _ = select(old, current, values)
    assert {json.loads(k)["weapon"] for k in kept} == {"/A", "/A#/part1+/part2+/part3"}


def test_resume_needs_every_requested_structure_and_its_original_result():
    key = json.dumps(dict(weapon='/A', profile='deep', fireMode=0))
    entries = {key: {'counts': {'3': {'recommended': ['0', 'D', 'S']}}}}
    proof = ('shared', 'weapon')
    shard = dict(schemaVersion=SHARD_SCHEMA, cacheVersion=26, profile='deep', entries=entries,
                 dependencies=shard_proof(*proof, entries))
    assert qualified_shard(shard, 'deep', '/A', 0, (3,), 26, proof)
    assert not qualified_shard(shard, 'deep', '/A', 0, (3, 2), 26, proof)
    entries[key]['counts']['3']['recommended'].reverse()
    assert not qualified_shard(shard, 'deep', '/A', 0, (3,), 26, proof)
