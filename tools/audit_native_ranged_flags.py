"""Read-only, native-source inventory of ranged event and eligibility declarations.

Flags are evidence of declarations, never proof that an event executes or has a
particular combat classification. Consumer audits remain separate.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SLOTS = {"primary", "secondary", "arch_gun"}
FIELD = re.compile(r"headshot|weakpoint|applyon|onhit|onkill|noproc|cancrit|critical|radius|radial|chain|child|embed|explos|attackdata|stack|bounce|forcedproc|hittype|deal.*damage|damage.*through|damagetrigger|projectile|hitentit|detonat|on.*death|fuse|lifespan|duration|attenuat|damageon|reportattack|damagesource|hitcount|hurt|cover|send.?events|script|tick|repeat|interval|upgrade|owner|creator|instigator|damage|proc", re.I)
NODE = re.compile(r"Projectile|DamageTrigger|RadialTrigger|WeaponImpactBehavior|BeamImpactBehavior|WeaponFireBehavior|WeaponStateBehavior")


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def leaves(value: Any, prefix=()):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from leaves(child, (*prefix, key))
    elif isinstance(value, list):
        if not value:
            yield prefix, value
        for index, child in enumerate(value):
            yield from leaves(child, (*prefix, index))
    else:
        yield prefix, value


def field_name(parts) -> str:
    return ".".join(str(part) for part in parts)


def get_at(value, parts):
    try:
        for part in parts:
            value = value[part]
        return True, value
    except (KeyError, IndexError, TypeError):
        return False, None


def ancestry(packages, path):
    result, seen = [], set()
    while path and path not in seen:
        result.append(path)
        seen.add(path)
        path = packages.parent(path)
    return result


def declaration(packages, path, parts):
    # Lists replace atomically; the nearest ancestor providing a containing
    # list is the boundary even when a requested list leaf is absent there.
    for source in ancestry(packages, path):
        own = packages.own(source)
        present, value = get_at(own, parts)
        if present:
            return source
        for index, part in enumerate(parts):
            if isinstance(part, int) and get_at(own, parts[:index])[0]:
                return None
    return None


def relevant_fields(packages, path, value, prefix=(), match_all=False):
    result = []
    for parts, item in leaves(value, prefix):
        if match_all or any(FIELD.search(str(part)) for part in parts if isinstance(part, str)):
            result.append(dict(field=field_name(parts), value=item,
                               declaration=declaration(packages, path, parts)))
    return result


def locate(packages, owner, reference):
    if not isinstance(reference, str) or not reference:
        return None
    if reference.startswith("/"):
        return reference if packages.exists(reference) else None
    for source in ancestry(packages, owner):
        candidate = source.rsplit("/", 1)[0] + "/" + reference
        if packages.exists(candidate):
            return candidate
    return None


def node_kind(packages, path):
    chain = ancestry(packages, path)
    typed = [p for p in chain if p.startswith(("/EE/Types/", "/Lotus/Types/"))]
    # Several native projectile classes (Bolto, Wave, Stackable) have no
    # EE Projectile parent in the package directory; use class roots as well.
    if any(p.endswith(("Projectile", "Glaive")) for p in typed):
        return "projectile"
    if any("DamageTrigger" in p.rsplit("/",1)[-1] for p in typed):
        return "damage-trigger"
    if any(NODE.search(p.rsplit("/",1)[-1]) for p in typed):
        return "behavior"
    if not path.startswith("/Lotus/Sounds/") and any(re.search(r"(?:Spawner|Decoration|ScriptTrigger|Sequencer|HitEffect)$",p) for p in typed):
        return "support"
    return None


def event_node(packages, path):
    return node_kind(packages,path) is not None


def references(packages, owner, value):
    result = []
    for parts, item in leaves(value):
        if not isinstance(item, str) or not item:
            continue
        path = locate(packages, owner, item)
        if path and path != owner and event_node(packages, path):
            result.append(dict(field=field_name(parts), target=path))
    return result


def summarize_fields(records):
    counts = defaultdict(Counter)
    examples = defaultdict(list)
    for record in records:
        # One count per object per field path/value, even if referenced by many weapons.
        for row in record["fields"]:
            key = row["field"]
            value = json.dumps(row["value"], ensure_ascii=False, sort_keys=True)
            counts[key][value] += 1
            if len(examples[key]) < 4:
                examples[key].append(record["path"])
    return {key: dict(present=sum(vals.values()), values=dict(vals), examples=examples[key])
            for key, vals in sorted(counts.items())}


def inventory(packages, exports, slots=SLOTS):
    weapons, nodes = [], {}
    roots, unresolved_exports = [], []
    all_modes = 0
    for weapon in exports:
        if weapon.get("slot") not in slots:
            continue
        path = weapon["path"]
        if not packages.exists(path):
            unresolved_exports.append(dict(path=path, name=weapon.get("nameEn")))
            continue
        raw = packages.resolve(path)
        mode_rows = []
        native_modes = raw.get("Behaviors") or []
        for mode_position, mode in enumerate(weapon.get("fireModes") or []):
            all_modes += 1
            native_index = mode.get("behaviourIndex", mode.get("behaviorIndex", mode.get("index", mode_position)))
            # Exporter's behaviour is the original source-list position. Expanded
            # charged fireModes can share one behaviour; do not index by display order.
            native_index = mode.get("behaviour", native_index)
            if not isinstance(native_index, int):
                native_index = mode.get("index", mode_position)
            native_mode = native_modes[native_index] if isinstance(native_index, int) and 0 <= native_index < len(native_modes) else None
            mode_refs = references(packages, path, native_mode or {})
            damage_projectile = (mode.get("damage") or {}).get("projectile")
            if damage_projectile and packages.exists(damage_projectile):
                mode_refs.append(dict(field="EXPORTS.damage.projectile", target=damage_projectile))
            for ref in mode_refs:
                roots.append((ref["target"], path, mode_position))
            mode_rows.append(dict(mode=mode_position, nativeBehavior=native_index,
                nativeBehaviorPresent=native_mode is not None,
                exportedTrigger=mode.get("trigger"), exportedDamage=mode.get("damage"),
                exportedBeam=mode.get("beam"), exportedEvents=mode.get("projectileEvents"),
                exportedSupport=mode.get("projectileEventSupport"),
                fields=relevant_fields(packages,path,native_mode or {},("Behaviors",native_index),match_all=True),
                references=mode_refs))
        native_mode_rows=[]
        for native_index,native_mode in enumerate(native_modes):
            refs=references(packages,path,native_mode)
            linked_exports=[m["mode"] for m in mode_rows if m["nativeBehavior"]==native_index]
            for ref in refs:
                roots.append((ref["target"],path,linked_exports[0] if linked_exports else None))
            native_mode_rows.append(dict(nativeBehavior=native_index,exportModes=linked_exports,
                fields=relevant_fields(packages,path,native_mode,("Behaviors",native_index),match_all=True),references=refs))
        weapon_refs = references(packages, path, {k:v for k,v in raw.items() if k != "Behaviors"})
        roots.extend((ref["target"], path, None) for ref in weapon_refs)
        weapons.append(dict(path=path, name=weapon.get("nameEn"), slot=weapon["slot"],
                            nativeBehaviorCount=len(native_modes),heavyBehaviorCount=len(raw.get("HeavyBehaviors") or []), exportModeCount=len(mode_rows),
                            fields=relevant_fields(packages,path,{k:v for k,v in raw.items() if k != "Behaviors"}),
                            references=weapon_refs, modes=mode_rows,nativeModes=native_mode_rows))
    queue = deque(roots)
    ownership = defaultdict(set)
    while queue:
        path, weapon_path, mode = queue.popleft()
        owner = (weapon_path, mode)
        if owner in ownership[path]:
            continue
        ownership[path].add(owner)
        if path not in nodes:
            raw = packages.resolve(path)
            refs = references(packages,path,raw)
            nodes[path] = dict(path=path, kind=node_kind(packages,path), ancestry=ancestry(packages,path),
                               fields=relevant_fields(packages,path,raw,match_all=True), references=refs)
        for ref in nodes[path]["references"]:
            queue.append((ref["target"], weapon_path, mode))
    for path, record in nodes.items():
        record["owners"] = [dict(weapon=weapon,mode=mode) for weapon,mode in sorted(ownership[path],key=lambda row:(row[0],-1 if row[1] is None else row[1]))]
    node_rows = [nodes[path] for path in sorted(nodes)]
    projectile_rows = [row for row in node_rows if row["kind"] == "projectile"]
    active_projectiles = {m["exportedDamage"]["projectile"] for w in weapons for m in w["modes"] if (m.get("exportedDamage") or {}).get("projectile")}
    active_rows = [row for row in node_rows if row["path"] in active_projectiles]
    for row in node_rows:
        row["exportedModeOwners"]=[dict(weapon=w["path"],mode=m["mode"]) for w in weapons for m in w["modes"] if (m.get("exportedDamage") or {}).get("projectile")==row["path"]]
    source_paths = set()
    for row in [*weapons, *node_rows]:
        source_paths.update(ancestry(packages,row["path"]))
    sources = []
    for path in sorted(source_paths):
        entity = packages.entities[path][1]
        raw = packages._reader.decompress(entity) if entity.attr is not None else b""
        sources.append(dict(path=path,parent=packages.parent(path),rawLength=len(raw),
                            rawAttributesSha256=hashlib.sha256(raw).hexdigest()))
    distributions = dict(weapon=summarize_fields(weapons),
        mode=summarize_fields([dict(path=w["path"]+":"+str(m["mode"]),fields=m["fields"]) for w in weapons for m in w["modes"]]),
        node=summarize_fields(node_rows), projectile=summarize_fields(projectile_rows),activeExportedProjectile=summarize_fields(active_rows))
    return dict(schemaVersion=1, status="declarations-only-consumers-not-inferred",
        denominators=dict(exportWeapons=len(exports), scopedWeapons=len(weapons),exportModes=all_modes,
            nativeBehaviors=sum(w["nativeBehaviorCount"] for w in weapons),
            heavyBehaviors=sum(w["heavyBehaviorCount"] for w in weapons),
            nativeBehaviorMappedModes=sum(m["nativeBehaviorPresent"] for w in weapons for m in w["modes"]),
            nativeBehaviorsWithoutExport=sum(not m["exportModes"] for w in weapons for m in w["nativeModes"]),
            exportedModesWithProjectile=sum(bool((m.get("exportedDamage") or {}).get("projectile")) for w in weapons for m in w["modes"]),
            distinctExportedProjectiles=len({(m.get("exportedDamage") or {}).get("projectile") for w in weapons for m in w["modes"] if (m.get("exportedDamage") or {}).get("projectile")}),
            referencedNodes=len(node_rows),nodeKinds=dict(Counter(n["kind"] for n in node_rows)),
            referencedDamageNodes=sum(n["kind"] in {"projectile","damage-trigger"} for n in node_rows),referencedProjectiles=len(projectile_rows),
            sourceRecords=len(sources),slots=dict(Counter(w["slot"] for w in weapons))),
        missingWeapons=unresolved_exports, weapons=weapons,nodes=node_rows,
        fieldDistributions=distributions,sources=sources,
        limitations=["No missing native field is treated as false or zero.",
            "Reference closure is an overapproximation of declared reachability, including optional support effects and inactive variants; it is not an active-event denominator.",
            "Inherited and inactive attack declarations do not prove execution.",
            "Projectile references include alternate charged, multishot and PvP declarations; these are counted separately from active exported mode projectiles.",
            "Consumers, Lua content, event eligibility, ownership, kill credit and geometry require separate native/runtime evidence.",
            "Production code and WFSim parity are not correctness evidence."])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages-bin", type=Path, required=True)
    parser.add_argument("--client-exe", type=Path, required=True)
    parser.add_argument("--live-client-exe", type=Path)
    parser.add_argument("--exports",type=Path,help="An explicit current EXPORTS ranged weapon array; otherwise import app under isolated cache settings")
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--slots",nargs="+",default=sorted(SLOTS),choices=sorted(SLOTS|{"companion"}))
    args=parser.parse_args()
    if args.output_dir.exists():
        parser.error("output directory already exists; preserve evidence and choose a new directory")
    sys.path.insert(0,str(ROOT / "tools"))
    from import_companion_projectile_sequences import AuditedPackages,CLIENT_SHA256
    client_hash=sha256(args.client_exe)
    if client_hash != CLIENT_SHA256:
        raise ValueError("Client changed; this reader/audit source pair is not admitted")
    args.output_dir.mkdir(parents=True,exist_ok=False)
    os.environ["WF_ANALYZER_SERIAL"]="1"
    os.environ["WF_EVALUATION_CACHE"]="0"
    os.environ["WF_ANALYSIS_STATICS_CACHE_PATH"]=str(args.output_dir.resolve()/"isolated-cache/analysis.json")
    if args.exports:
        exports=json.loads(args.exports.read_text(encoding="utf-8-sig"))
    else:
        sys.path.insert(0,str(ROOT))
        import app
        app._disable_analysis_statics_persistence()
        app._refresh_analysis_statics_cache_if_newer=lambda:None
        exports=[w for w in app.EXPORTS["weapons"] if w.get("slot") in set(args.slots)]
    if not isinstance(exports,list) or not exports:
        raise ValueError("Expected a non-empty current ranged export array")
    packages=AuditedPackages(args.packages_bin)
    packages.own=lru_cache(maxsize=None)(packages.own)
    result=inventory(packages,exports,set(args.slots))
    current_export_path=args.output_dir/"current-ranged-exports.json"
    if not args.exports or args.exports.resolve()!=current_export_path.resolve():
        current_export_path.write_text(json.dumps(exports,ensure_ascii=False,indent=1)+"\n",encoding="utf-8")
    result["provenance"]=dict(packagesBin=dict(path=str(args.packages_bin.resolve()),sha256=packages.sha256,entityCount=len(packages.entities)),
        client=dict(path=str(args.client_exe.resolve()),sha256=client_hash,buildLabel="2026.10.22.13.12"),
        currentExports=dict(path=str(current_export_path.resolve()),sha256=sha256(current_export_path)),
        auditScript=dict(path=str(Path(__file__).resolve()),sha256=sha256(Path(__file__))))
    if args.live_client_exe:
        live_hash=sha256(args.live_client_exe)
        result["provenance"]["liveClient"]=dict(path=str(args.live_client_exe.resolve()),sha256=live_hash,matchesPreserved=live_hash==client_hash)
    result["requestedFlagCoverage"]={name:dict(exactFields=[k for k in result["fieldDistributions"]["node"] if k.split(".")[-1]==name],
        absentMeaning="not declared in inspected closure; native default/consumer remains unknown") for name in ("IgnoreHeadShotBonus","DealDamageThroughImpactBehavior","ApplyOnHit","ApplyOnKill","NoProc","NoProcs","CanCrit","CriticalHit","ExplosionDirectHitDamageHitType","SendEvents")}
    for name,value in [("inventory.json",result),("field-distributions.json",result["fieldDistributions"]),("source-manifest.json",result["sources"])]:
        (args.output_dir/name).write_text(json.dumps(value,ensure_ascii=False,indent=1)+"\n",encoding="utf-8")
    print(json.dumps(result["denominators"],ensure_ascii=False))


if __name__=="__main__":
    main()
