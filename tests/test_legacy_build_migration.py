import json
import subprocess
import threading
import urllib.request
from pathlib import Path
import pytest
import app

OLD='/Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert'
BASE='/Lotus/Upgrades/Mods/Rifle/WeaponToxinDamageMod'


def test_restore_migrates_only_known_cards_silently(tmp_path):
    source=app.ROOT/'frontend/build-config-migrations.js'
    fixture=tmp_path/'catalog.json'
    fixture.write_text(json.dumps(app.CATALOG['legacyModReplacements']),encoding='utf-8')
    script=tmp_path/'check.cjs'
    script.write_text(r"""
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const ctx={};vm.createContext(ctx);vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),ctx);
const rules=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));
const old='/Lotus/Upgrades/Mods/Rifle/Expert/WeaponToxinDamageModExpert';
const base='/Lotus/Upgrades/Mods/Rifle/WeaponToxinDamageMod';
const original={weapon:'/weapon',mods:[{path:old,rank:10,slot:2}],riven:{stats:[{code:'D',value:123}]},formaSlots:{2:'AP_ATTACK'},incarnonChoices:{tier2:'2-1'},arcanes:[{path:'/arcane',rank:5}]};
const pristine=JSON.stringify(original);
const r=ctx.migrateLegacyBuildConfig(original,rules);
assert.equal(JSON.stringify(original),pristine);
assert.equal(r.config.mods[0].path,base);assert.equal(r.config.mods[0].rank,5);assert.equal(r.config.mods[0].slot,2);
assert.equal(JSON.stringify(r.changes[0].from),JSON.stringify(original.mods[0]));
assert.equal(Object.hasOwn(r.config,'legacyModMigrations'),false);
const stale=ctx.migrateLegacyBuildConfig({...JSON.parse(JSON.stringify(r.config)),legacyModMigrations:[{field:'mods'}]},rules);
assert.equal(stale.changes.length,0);assert.equal(Object.hasOwn(stale.config,'legacyModMigrations'),false);
for(const k of ['riven','formaSlots','incarnonChoices','arcanes']) assert.equal(JSON.stringify(r.config[k]),JSON.stringify(original[k]));
assert.equal(ctx.migrateLegacyBuildConfig(JSON.parse(JSON.stringify(r.config)),rules).changes.length,0);
for (const rank of [0,2,5]) assert.equal(ctx.migrateLegacyBuildConfig({mods:[{path:old,rank}]},rules).config.mods[0].rank,rank);
for (const rank of [-1,1.5,'10',true]) assert.equal(ctx.migrateLegacyBuildConfig({mods:[{path:old,rank}]},rules).changes.length,0);
const unknown={mods:[{path:'/unknown/Expert',rank:10},{path:base,rank:10}]};assert.equal(ctx.migrateLegacyBuildConfig(unknown,rules).config,unknown);
assert.equal(ctx.migrateLegacyBuildConfig(original,{}).config,original);
const constraints=ctx.migrateLegacyBuildConfig({requiredMods:[old,base],forbiddenMods:[old],exilus:{path:old,rank:10}},rules).config;
assert.equal(JSON.stringify(constraints.requiredMods),JSON.stringify([base]));assert.equal(constraints.forbiddenMods[0],base);assert.equal(constraints.exilus.rank,5);
const all=Object.entries(rules).map(([path])=>({path,rank:10}));
const every=ctx.migrateLegacyBuildConfig({mods:all},rules);
assert.equal(every.changes.length,all.length);
for(let i=0;i<all.length;i++){assert.equal(every.config.mods[i].path,rules[all[i].path].path);assert.equal(every.config.mods[i].rank,rules[all[i].path].maxRank);}
process.stdout.write(JSON.stringify(r.config));
""",encoding='utf-8')
    result=subprocess.run(['node',str(script),str(source),str(fixture)],capture_output=True,text=True,encoding='utf-8',check=True)
    config=json.loads(result.stdout)
    assert app._manual_normalize_mods(config['mods'],8)==[dict(path=BASE,rank=5,slot=2)]
    # Direct API requests must still reject the nonexistent card and excess rank.
    with pytest.raises(app.SimulationError,match='unreleased tier variant'):
        app._manual_normalize_mods([dict(path=OLD,rank=10)],8)
    with pytest.raises(app.SimulationError,match='exceeds maxRank'):
        app._manual_normalize_mods([dict(path=BASE,rank=10)],8)


def test_http_serves_migration_and_enemy_images_without_external_downloads():
    server=app.create_server('127.0.0.1',0)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    root='http://127.0.0.1:'+str(server.server_port)
    try:
        with urllib.request.urlopen(root+'/api/catalog',timeout=10) as response:catalog=json.load(response)
        assert catalog['legacyModReplacements'][OLD]['path']==BASE
        for url,token in [('/build-config-migrations.js',b'migrateLegacyBuildConfig'),('/enemy-images.js',b'createEnemyThumbnail'),('/',b'/build-config-migrations.js')]:
            with urllib.request.urlopen(root+url,timeout=10) as response:assert token in response.read()
        image=next(row['imageAsset'] for row in catalog['enemies'] if row.get('imageAsset'))
        with urllib.request.urlopen(root+image,timeout=10) as response:
            assert response.headers['Content-Type'].startswith('image/')
            assert response.read().startswith(bytes.fromhex('89504e470d0a1a0a'))
    finally:
        server.shutdown();server.server_close();worker.join(timeout=5)
