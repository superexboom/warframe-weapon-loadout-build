"""Conservative per-weapon reuse across data-only bake revisions.

Capture a validated cache with `save`, then `restore` before the next bake.
Only immutable artifacts with identical shared runtime/data dependencies and
identical fully hydrated weapon records and audited native mode rows are
reused. Engine, MOD, enemy, arcane, modular-part, policy or unknown dependency
changes invalidate all entries.
Never change the live engine's fingerprint policy or skip its normal bake checks.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 2
SHARD_SCHEMA = 4

# event_profiles._mode_entry is the only runtime route for these tables. It
# looks up the selected weapon's exact path and then checks its mode metadata.
_NATIVE_MODE_SIDECARS = frozenset(("burst-profiles.json", "charge-profiles.json", "reload-after-shot.json"))
# These four modules are imported only by the optional arena HTTP endpoints.
# Any new module (or arena module read by the scoring fingerprint) stays shared.
_ARENA_ONLY = {'arena.py', 'arena_combat.py', 'arena_scene.py', 'arena_spawns.py'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def ordered_digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes((json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False) + "\n").encode())
    tmp.replace(path)


def _producer_identity(current):
    # The job driver owns defaults such as selecting variants and constructing
    # a request. A changed producer cannot certify shards of its predecessor.
    producers = [hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                 for p in (Path(__file__), ROOT / 'tools/bake-analysis-statics.py')]
    return digest([SCHEMA, current['cacheVersion'], current['buildLabel'], current['stances'], current['shared'], producers])


def bake_inventory(app):
    current = inventory(app)
    return current['inputs'], _producer_identity(current), current['records']


def shard_proof(shared, owner, entries):
    # Preserve the original entry/key order: some tie breaks depend on order.
    return {'shared': shared, 'weapon': owner, 'entries': ordered_digest(entries)}


def qualified_shard(payload, profile, weapon, mode, counts, cache_version, proof=None):
    if not isinstance(payload, dict) or (payload.get('schemaVersion'), payload.get('cacheVersion'), payload.get('profile')) != (SHARD_SCHEMA, cache_version, profile):
        return False
    entries = payload.get('entries')
    if not isinstance(entries, dict) or not entries:
        return False
    for key, value in entries.items():
        try:
            context = json.loads(key)
            if (context['weapon'], context['fireMode'], context['profile']) != (weapon, mode, profile):
                return False
            for n in counts:
                bundle = value['counts'][str(n)]
                if not isinstance(bundle['recommended'], list) or len(bundle['recommended']) != n:
                    return False
        except (KeyError, TypeError, ValueError):
            return False
    if proof is None:  # Legacy Bot adapter never reuses shards across input revisions.
        return True
    try:
        return payload.get('dependencies') == shard_proof(*proof, entries)
    except ValueError:  # A nonfinite cached number cannot have a valid digest.
        return False


def _unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate JSON members")
    return result


def _native_mode_rows(raw, weapons):
    """Keep unknown layouts and owners in the shared fingerprint."""
    try:
        document = json.loads(raw, object_pairs_hook=_unique_object)
        if type(document.get("schemaVersion")) is not int or document["schemaVersion"] != 1:
            return None
        rows = document["weapons"]
        if not isinstance(rows, dict) or not all(
            path in weapons and isinstance(row, dict) and isinstance(row.get("modes"), dict)
            and all(i.isascii() and i.isdecimal() and str(int(i)) == i and isinstance(mode, dict)
                    for i, mode in row["modes"].items())
            for path, row in rows.items()
        ):
            return None
        return digest({k: v for k, v in document.items() if k != "weapons"}), rows
    except (AttributeError, ValueError, KeyError):
        return None


def inventory(app):
    """Observe the existing identity reader instead of maintaining a second list."""
    paths = {}
    read = Path.read_bytes
    def observed(path):
        raw = read(path)
        paths[path.resolve()] = raw
        return raw
    Path.read_bytes = observed
    try:
        inputs = app._analysis_inputs_fingerprint()
    finally:
        Path.read_bytes = read
    fingerprint_paths = set(paths)
    # Include optional native code and all engine modules, even if an older
    # global fingerprint omitted one. No code-change reuse is inferred.
    engine = Path(app.optimizer.__file__).resolve().parent
    for path in engine.iterdir():
        if path.name in _ARENA_ONLY and path.resolve() not in fingerprint_paths:
            continue
        if path.suffix in (".py", ".pyd", ".so"):
            paths[path.resolve()] = read(path)
    for name in ("data_sources.py", "enemy_assets.py"):
        path = Path(app.__file__).with_name(name).resolve()
        paths[path] = read(path)
    # Cover runtime sidecars even when an older global fingerprint omitted
    # them. Generated cache/progress/route documents are outputs, not rules.
    outputs = {"riven-analysis-statics.json", "riven-analysis-statics.progress.json",
               "bot-incarnon-routes.json", "portable-runtime.json"}
    data_dirs = {app.ROOT / "data", app.ROOT / "data/mechanics", app.EXPORT_DIR,
                 app.DATASET_ROOT / "data", app.DATASET_ROOT / "data/mechanics"}
    for directory in data_dirs:
        for path in directory.glob("*.json"):
            if path.name not in outputs:
                paths[path.resolve()] = read(path)
    weapons_path = (app.EXPORT_DIR / "weapons.json").resolve()
    catalog = app.CATALOG_WEAPONS_BY_PATH
    records = {str(w["path"]): {"weapon": w, "catalog": catalog.get(w["path"])}
               for w in app.EXPORTS["weapons"] if w.get("path")}
    # Runtime loaders read next to the code, independently of an active export
    # snapshot. A same-named file in another root remains a shared dependency.
    code_sidecars = (engine.parents[1] / "data/mechanics").resolve()
    portable_sidecars = (app.ROOT / "data/mechanics").resolve()
    app_source = Path(app.__file__).resolve()
    # Older Bot bundles fingerprint their complete app.py and do not ship
    # Portable's arena projection. Use their raw source as they do.
    projection = None
    if (engine / 'cache_identity.py').is_file():
        from wfarsenal.cache_identity import score_source_bytes as projection
    shared = {}
    # The same installed binary can run in reference mode, or with selected
    # native stages disabled. Those modes must not cross-reuse each other's work.
    from wfarsenal import mods_native, native_replay, status_native
    shared['native-scoring-modes'] = [bool(native_replay.ENABLED), bool(mods_native.ENABLED),
                                      bool(status_native.ENABLED), bool(native_replay.ENABLED and native_replay.HEALTH_BATCH)]
    for path, raw in paths.items():
        # Keep both the runtime row and the source row: app caches the former
        # on import, so an on-disk edit must still change a repeated inventory.
        if path == weapons_path:
            document = json.loads(raw)
            shared["weapons-header"] = digest({k:v for k,v in document.items() if k not in ("data", "count")})
            seen = set()
            for row in document["data"]:
                owner = row.get("path") if isinstance(row, dict) else None
                if not isinstance(owner, str) or owner in seen or owner not in records:
                    break  # Treat ambiguous export membership as shared.
                seen.add(owner)
                records[owner]["export"] = row
            else:
                continue
        # Preserve distinct same-name files instead of silently overwriting.
        rel = path.relative_to(app.ROOT).as_posix() if path.is_relative_to(app.ROOT) else path.as_posix()
        if (path in fingerprint_paths and path.parent == code_sidecars == portable_sidecars
                and path.name in _NATIVE_MODE_SIDECARS):
            dependency = _native_mode_rows(raw, records)
            if dependency is not None:
                shared[rel], rows = dependency
                for owner, row in rows.items():
                    records[owner].setdefault("sidecars", {})[rel] = row
                continue
        if path == app_source and projection is not None:
            raw = projection('app.py', raw, app.ROOT)
        if path.suffix == ".py":
            raw = raw.replace(b"\r\n", b"\n")
        shared[rel] = hashlib.sha256(raw).hexdigest()
    return {"schema": SCHEMA, "inputs": inputs, "cacheVersion": app.ANALYSIS_STATICS_CACHE_VERSION,
            "buildLabel": app.EXPORTS["buildLabel"], "stances": app._stances_fingerprint(),
            "shared": shared, "records": {path: ordered_digest(row) for path, row in records.items()}}


def _context_weapon(identity, known):
    # Dark Split-Sword has a genuine '#' in each form's path. Consult both
    # inventories so an obsolete actual path cannot masquerade as a base row.
    while identity not in known:
        identity, separator, suffix = identity.rpartition("#")
        if not separator or not (suffix.startswith(("strength=", "cast=")) or (
            len(parts := suffix.split("+")) == 3 and all(p.startswith("/") for p in parts)
        )):
            return None
    return identity


def select(previous, current, entries):
    """Fail closed: every reused context must resolve to an unchanged record."""
    if (previous.get("schema") != SCHEMA or current.get("schema") != SCHEMA
            or any(previous.get(k) != current.get(k) for k in ("cacheVersion", "buildLabel", "stances", "shared"))):
        return {}, "shared-dependencies-changed"
    old_records, new_records = previous.get("records", {}), current.get("records", {})
    known = old_records.keys() | new_records.keys()
    retained = {}
    for key, entry in entries.items():
        try:
            context = json.loads(key)
            weapon = context["weapon"]
            if not isinstance(weapon, str):
                continue
            identity = _context_weapon(weapon, known)
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        old = old_records.get(identity)
        if old and old == new_records.get(identity) and isinstance(entry, dict):
            retained[key] = entry
    return retained, "verified-record-dependencies"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("save", "restore"))
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--bot-bundle", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--runtime-root", type=Path, help="Explicit isolated Portable runtime for validation")
    parser.add_argument("--shard-dir", type=Path, help="Restore verified Portable contexts as resumable shards")
    args = parser.parse_args()
    if args.bot_bundle:
        bundle = args.bot_bundle.resolve()
        os.environ["WF_RIVEN_ROOT"] = str(bundle)
        os.environ["WF_ANALYSIS_STATICS_CACHE_PATH"] = str(bundle / "data/riven-analysis-statics.json")
        sys.path.insert(0, str(bundle / "src"))
        import bot_riven
        app = bot_riven.app
    else:
        runtime = (args.runtime_root or ROOT).resolve()
        if args.runtime_root:
            os.environ["WF_RIVEN_ROOT"] = str(runtime)
            os.environ["WF_ANALYSIS_STATICS_CACHE_PATH"] = str(runtime / ".local/cache/riven-analysis-statics.json")
        sys.path.insert(0, str(runtime))
        import app
    current = inventory(app)
    producer = _producer_identity(current) if args.shard_dir and not args.bot_bundle else None
    cache_path = Path(app.ANALYSIS_STATICS_CACHE_PATH)
    if args.action == "save":
        cache = json.loads(cache_path.read_bytes())
        if any(cache.get(k) != current[k] for k in ("inputs", "cacheVersion", "buildLabel", "stances")):
            raise ValueError("cannot archive an outdated cache")
        entries = cache.get("entries")
        if not isinstance(entries, dict) or not entries:
            raise ValueError("cannot archive an empty cache")
        body = {"inventory": current, "entries": entries}
        if args.bot_bundle:
            route_path = bundle / "data/bot-incarnon-routes.json"
            if route_path.is_file():
                routes = json.loads(route_path.read_bytes())
                if routes.get("inputs") == current["inputs"]:
                    body["routes"] = routes
        if args.shard_dir and not args.bot_bundle:
            groups = []
            for profile in ("fast", "standard", "deep"):
                for path in (args.shard_dir / ("riven-statics-shards-" + profile)).glob("*.json"):
                    shard = json.loads(path.read_bytes())
                    if not isinstance(shard, dict) or shard.get('inputs') != current['inputs']:
                        continue
                    keys = list(shard.get("entries", {}))
                    if not keys or not all(k in entries and entries[k] == shard['entries'][k] for k in keys):
                        continue
                    context = json.loads(keys[0])
                    path_id, mode = context['weapon'], context['fireMode']
                    if path_id in current['records'] and qualified_shard(shard, profile, path_id, mode, (3,), current['cacheVersion'], (producer, current['records'][path_id])):
                        groups.append({'profile': profile, 'file': path.name, 'keys': keys, 'dependencies': shard['dependencies']})
            body["shards"] = groups
        identity = ordered_digest(body)
        atomic(args.store / "objects" / (identity + ".json"), body)
        atomic(args.store / "latest.json", {"object": identity})
        report = {"saved": len(entries), "object": identity, "inputs": current["inputs"]}
    else:
        pointer = json.loads((args.store / "latest.json").read_bytes())
        identity = pointer["object"]
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("invalid cache object identity")
        body = json.loads((args.store / "objects" / (identity + ".json")).read_bytes())
        archive_hash = ordered_digest if body['inventory'].get('schema') == SCHEMA else digest
        if archive_hash(body) != identity:
            raise ValueError("cache object hash mismatch")
        retained, reason = select(body["inventory"], current, body["entries"])
        # Current entries win, and existing cache is kept byte-for-byte as
        # an immutable backup before replacing it with verified reuse.
        loaded = app._load_analysis_statics_cache()
        merged = {**retained, **{k:v for k,v in loaded.items() if isinstance(v, dict)}}
        if retained:
            if inventory(app) != current:
                raise ValueError("inputs changed during reuse validation")
            if cache_path.exists():
                raw = cache_path.read_bytes()
                backup = args.store / "backups" / (hashlib.sha256(raw).hexdigest() + ".json")
                backup.parent.mkdir(parents=True, exist_ok=True)
                if not backup.exists(): backup.write_bytes(raw)
            atomic(cache_path, {**{k:current[k] for k in ("inputs", "cacheVersion", "buildLabel", "stances")},
                                "entries": merged})
        shard_count = 0
        if args.shard_dir and not args.bot_bundle:
            # Only restore previously validated bake shards. Arbitrary user
            # contexts in a main cache must never satisfy a default bake task.
            for group in body.get("shards", []):
                keys = group["keys"]
                profile, name = group["profile"], group["file"]
                if (profile not in ("fast", "standard", "deep") or Path(name).name != name
                        or not keys or not all(k in retained for k in keys)):
                    continue
                path = args.shard_dir / ("riven-statics-shards-" + profile) / name
                context = json.loads(keys[0])
                path_id, mode = context['weapon'], context['fireMode']
                shard = dict(schemaVersion=SHARD_SCHEMA, cacheVersion=current['cacheVersion'], inputs=current['inputs'],
                             profile=profile, entries={k: retained[k] for k in keys}, dependencies=group.get('dependencies'))
                if path_id not in current['records'] or not qualified_shard(shard, profile, path_id, mode, (3,), current['cacheVersion'], (producer, current['records'][path_id])):
                    continue
                atomic(path, shard)
                shard_count += 1
        route_count = 0
        if retained and args.bot_bundle and body.get("routes"):
            old_routes = body["routes"]
            reusable = {path:value for path,value in old_routes.get("routes", {}).items()
                        if body["inventory"]["records"].get(path)
                        and body["inventory"]["records"].get(path) == current["records"].get(path)}
            existing_routes = bot_riven._load_routes()
            atomic(bundle / "data/bot-incarnon-routes.json",
                   {**old_routes, "inputs": current["inputs"], "routes": {**reusable, **existing_routes}})
            route_count = len(reusable)
        report = {"reused": len(retained), "archived": len(body["entries"]), "reason": reason,
                  "inputs": current["inputs"], "requiresBakeValidation": True,
                  "portableShards": shard_count, "botRoutes": route_count}
    if args.report: atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
