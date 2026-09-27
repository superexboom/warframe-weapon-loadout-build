import argparse, hashlib, json, yaml, subprocess, sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(
    description="Import pinned combat data; no game or reference files are modified."
)
p.add_argument("--wfsim", type=Path, required=True)
p.add_argument("--packages", type=Path, required=True)
p.add_argument("--output", type=Path, help="Destination directory; defaults to data/mechanics")
a = p.parse_args()
ref = a.wfsim
out = a.output or root / "data/mechanics"
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(root / "vendor"))
from wfarsenal.packages import PackageIndex

pkg = PackageIndex(a.packages)
parents = a.packages.parent / "parents.json"
if parents.is_file():
    pkg.parents = json.loads(parents.read_text(encoding="utf-8-sig"))
files = {}
weapons = {}
syndicates = {}
mods = {}
enemies = {}
for f in (ref / "data/weapons").rglob("*.yaml"):
    x = yaml.safe_load(f.read_text(encoding="utf-8"))
    if isinstance(x, dict) and x.get("id"):
        weapons[x["id"]] = x
        files[x["id"]] = f.relative_to(ref).as_posix()


def resolved(key, seen=()):
    x = weapons.get(key, {})
    if key in seen:
        return {}
    return {**resolved(x["inherits"], (*seen, key)), **x} if x.get("inherits") else x


forms = {}
for key, x in weapons.items():
    if not x.get("gauge_form"):
        continue
    base = resolved(x.get("transforms_from") or x.get("inherits") or "")
    path = base.get("internal_name")
    g = x["gauge_form"]
    gauge = g.get("gauge", {})
    attack = x.get("attack", {})
    # Direct-hit charging is currently audited only for Torid. Importing other
    # charge economies here would silently advertise unvalidated runtime support.
    charge_on = gauge.get('charge_on')
    if not path or (charge_on != 'weakpoint_hits' and not (
        charge_on == 'direct_hits' and path == '/Lotus/Weapons/ClanTech/Bio/BioWeapon'
    )):
        continue
    forms[path] = {
        "pool": gauge.get("max_rounds"),
        "hits": gauge.get("charges_to_fill"),
        "gain": gauge.get("rounds_per_charge"),
        "enterSeconds": g.get("transmute_in_seconds", base.get("reload_seconds")),
        "exitSeconds": g.get("transmute_out_seconds", 1.0),
        "burst": (base.get("attack") or {}).get("burst"),
        "radial": attack.get("radial"),
        "source": files[key],
        "referenceId": key,
    }
    if charge_on != 'weakpoint_hits':
        forms[path]['chargeOn'] = charge_on
for f in (ref / "data/syndicates").glob("*.yaml"):
    x = yaml.safe_load(f.read_text(encoding="utf-8"))
    syndicates[x["id"]] = {
        k: v for k, v in x.items() if k not in ("source", "description")
    }
for f in (ref / "data/mods").rglob("*.yaml"):
    x = yaml.safe_load(f.read_text(encoding="utf-8"))
    if not isinstance(x, dict) or not x.get("internal_name"):
        continue
    for e in x.get("effects", []):
        if e.get("kind") == "syndicate_radial":
            mods[x["internal_name"]] = e["syndicate"]
for f in (ref / "data/enemies").glob("*.yaml"):
    x = yaml.safe_load(f.read_text(encoding="utf-8"))
    if x.get("stats", {}).get("affinity") is not None:
        enemies[x["name"].casefold()] = x["stats"]["affinity"]
# Internal UpgradeObject identities from the actual game package, not name guessing.
objects = {
    name + "Syndicate": sid
    for name, sid in [
        ("Arbiters", "truth"),
        ("SteelMeridian", "justice"),
        ("NewLoka", "purity"),
        ("CephalonSuda", "entropy"),
        ("RedVeil", "blight"),
        ("Perrin", "sequence"),
    ]
}
native = {}
evidence = {}
exports = root / "data/export/2026.08.13.13.24"


def read_rows(name):
    return json.loads((exports / (name + ".json")).read_text(encoding="utf-8"))["data"]


for category, field, dest in [
    ("mods", "Upgrades", mods),
    ("weapons", "LevelUpgrades", native),
]:
    for row in read_rows(category):
        path = row["path"]
        if "/Syndicate" not in path:
            continue
        raw = pkg.resolve(path)
        for upgrade in raw.get(field) or []:
            if (
                not isinstance(upgrade, dict)
                or upgrade.get("UpgradeType") != "WEAPON_SYNDICATE_POWER"
            ):
                continue
            sid = objects.get(
                str(upgrade.get("UpgradeObject") or "").rsplit("/", 1)[-1]
            )
            if sid and float(upgrade.get("Value") or 0) > 0:
                dest[path] = sid
                f = a.packages / (path.lstrip("/") + ".txt")
                if not f.is_file():
                    f = f.with_suffix(".json")
                evidence[path] = {
                    "field": field,
                    "object": upgrade["UpgradeObject"],
                    "value": upgrade["Value"],
                    "sha256": (
                        hashlib.sha256(f.read_bytes()).hexdigest()
                        if f.is_file()
                        else None
                    ),
                }
# Only these attacks have a confirmed match to the frozen export's base vector.
audited = {}
selection = {'Carmine Penta':'carmine_penta', 'Prisma Lenz':'prisma_lenz', 'Tenet Envoy':'tenet_envoy', 'Kompressa':'kompressa', 'Cyanex':'cyanex', 'Simulor':'simulor', 'Synoid Simulor':'synoid_simulor', 'Kuva Ogris':'kuva_ogris', 'Kuva Bramma':'kuva_bramma', 'Penta':'penta', 'Secura Penta':'secura_penta', 'Zarr':'zarr', 'Acceltra Prime':'acceltra_prime', 'Sonicor':'sonicor', 'Felarx':'felarx', 'Torid':'torid', 'Mausolon':'mausolon', 'Opticor Vandal':'opticor_vandal_quick', 'Nataruk':'nataruk', 'Cinta':'cinta', 'Paris Prime':'paris_prime_uncharged', 'Grattler':'grattler', 'Kuva Grattler':'kuva_grattler', 'Morgha':'morgha', 'Cyngas':'cyngas'}
for row in read_rows('weapons'):
    key = selection.get(row.get('nameEn'))
    if not key:
        continue
    spec = resolved(key)
    atk = spec['attack']
    entry = dict(name=row['nameEn'], source=files[key], sha256=hashlib.sha256((ref/files[key]).read_bytes()).hexdigest(), directTotal=sum(atk['damage'].values()), scope='base mode, direct-hit target at centre')
    if key == 'felarx':
        entry.update(magazine=spec['magazine'], reloadStart=spec['reload_start_seconds'], reloadPerShell=spec['reload_per_shell_seconds'], reloadEnd=spec['reload_end_seconds'])
    if spec.get('class') == 'bow':
        entry.update(bow=True, drawSeconds=atk['charge_seconds'])
    if atk.get('burst'): entry['burst'] = atk['burst']
    for component in ('radial','lingering'):
        if atk.get(component): entry[component] = atk[component]
    component=atk.get('radial') or atk.get('lingering') or {}
    if atk.get('compression') and component.get('radius_m'):
        entry['compression']={**atk['compression'],'radius':component['radius_m'],
            'takesRadiusMods':component.get('takes_blast_radius_mods',True)}
    if atk.get('cluster'):entry['unmodeled']=['cluster-submunitions-unmodeled']
    entry['sourceCommit']=subprocess.check_output(['git','-C',str(ref),'rev-parse','HEAD'],text=True).strip()
    if key in ('kompressa','cyanex'):
        mode=row['fireModes'][0]
        projectile=mode['damage']['projectile']
        native_projectile=pkg.resolve(projectile)
        field='EmbedDeathAttack' if key=='kompressa' else 'ExplosiveAttack'
        native_part=native_projectile[field]
        expected=('DT_VIRAL',42.) if key=='kompressa' else ('DT_GAS',41.)
        if native_part.get('Type')!=expected[0] or abs(float(native_part.get('Amount',0))-expected[1])>.001:
            raise ValueError('native secondary radial changed: '+key)
        if key=='cyanex' and (native_projectile.get('Embed') or native_projectile.get('DealExplosionDamageOnImpact')!=1):
            raise ValueError('Cyanex collision/embed contract changed')
        entry['radial'].update(takes_multishot=True,
            status_chance=float(native_part['ProcChance'])/float(mode.get('multishot') or 1),
            nativeSource=projectile,nativeField=field,
            multishotSource='one native radial attack per spawned projectile',
            referenceTakesMultishot=component.get('takes_multishot'))
        sources=[row['path'],projectile]
        if key=='kompressa':
            ms=projectile+'MS';other=pkg.resolve(ms)
            if other.get(field)!=native_part or native_projectile.get('Embed')!=1:
                raise ValueError('Kompressa multishot/embed contract changed')
            delay=native_projectile.get('EmbedTime')
            if not isinstance(delay,list) or len(delay)!=2 or not 0<=delay[0]<=delay[1]:
                raise ValueError('missing native embed delay')
            entry['radial']['impact_delay_seconds']=sum(delay)/2
            entry['radial']['nativeDelayRange']=delay
            entry['unmodeled']=['embed-delay-uniform-approximated-by-mean','spatial-projectile-hit-loss-unmodeled']
            sources.append(ms)
        else:
            entry['unmodeled']=['projectile-homing-and-bounce-target-selection-unmodeled','spatial-projectile-hit-loss-unmodeled']
        entry['nativeSources']=[dict(path=source,sha256=hashlib.sha256((a.packages/(source.lstrip('/')+'.txt')).read_bytes()).hexdigest()) for source in sources]
    if key in ('simulor','synoid_simulor'):
        exported=row['fireModes'][0]['damage']
        if exported.get('source')!='ExplosiveAttack' or abs(sum(exported['types'].values())-sum(component['damage'].values()))>.02:
            raise ValueError('pure radial export changed: '+key)
        entry.update(directTotal=sum(exported['types'].values()),scope='exported base explosion only; no duplicate radial child',
            unmodeled=['orb-merging-and-singularity-unmodeled','orb-multishot-merging-economy-unmodeled'])
        entry['compression'].update(radius=exported['radius'],radiusSource='native exported damage.radius',referenceRadius=component['radius_m'])
        entry.pop('radial',None)
    if key=='acceltra_prime':
        projectile='/Lotus/Weapons/Tenno/LongGuns/PrimeAcceltra/PrimeAcceltraProjectile'
        arming=pkg.resolve(projectile).get('ArmingDistance')
        if isinstance(arming,(int,float)):
            entry['radial']['armingDistance']=arming
            entry['radial']['armingSource']=dict(packageBuild=a.packages.parent.name,path=projectile,nativeValue=arming)
    audited[row['path']] = entry
wp='/Lotus/Weapons/Infested/Pistols/InfVomitGun/InfVomitGunWep'
mp='/Lotus/Weapons/Infested/Pistols/InfVomitGun/FireRateOnHeadshotPistolMod'
cp='/Lotus/Weapons/Infested/Pistols/InfVomitGun/InfVomitGunProcCondition'
m=pkg.resolve(mp); c=pkg.resolve(cp)
native_triggers={}
if c.get('Part') == 'HEAD' and 'DHT_RADIAL' in (c.get('IgnoreHitTypes') or ()) and m.get('UpgradeDuration') == 3:
    artifact=a.packages/(mp.lstrip('/')+'.txt')
    if not artifact.exists(): artifact=artifact.with_suffix('.json')
    native_triggers[wp]=dict(id='dual-toxocyst-frenzy',label='狂躁：直接爆头后 3 秒；射速 x2.5、毒素 +100%、普通弹药消耗 0',kind='on-headshot',duration=3,maxStacks=1,perEvent=1,effects=[dict(upgradeType=x['UpgradeType'],operation=x['OperationType'],value=x['Value'],damageType=x.get('DamageType')) for x in m['Upgrades'] if x['UpgradeType'] in ['WEAPON_FIRE_RATE','WEAPON_AMMO_CONSUME_RATE','WEAPON_PERCENT_BASE_DAMAGE_ADDED']],sourceBuild=a.packages.parent.name,source=mp,conditionSource=cp,sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())

payload = {
    "source": {
        "repository": "magenie33/wfsim",
        "commit": subprocess.check_output(
            ["git", "-C", str(ref), "rev-parse", "HEAD"], text=True
        ).strip(),
    },
    "incarnon": forms,
    "auditedAttacks": audited,
    "nativeTriggers": native_triggers,
    "syndicates": syndicates,
    "mods": mods,
    "nativeSyndicates": native,
    "enemyAffinity": enemies,
    "packageBuild": a.packages.parent.name,
    "packageEvidence": evidence,
}
sys.path.insert(0, str(root))
from tools.import_native_radial_profiles import import_profiles
import_profiles(a.packages, ref, json.loads((exports / "weapons.json").read_text(encoding="utf-8")), payload)
(out / "combat-reference.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2) + chr(10),
    encoding="utf-8",
    newline=chr(10),
)
print(
    "reference:",
    len(forms),
    "forms",
    len(mods),
    "syndicate mods",
    len(native),
    "native",
    len(enemies),
    "affinity",
)
