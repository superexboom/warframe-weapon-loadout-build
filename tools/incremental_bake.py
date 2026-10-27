"""Conservative per-weapon reuse across data-only bake revisions.

Capture a validated cache with `save`, then `restore` before the next bake.
Only immutable artifacts with identical shared runtime/data dependencies and
identical fully hydrated weapon records are reused. Engine, MOD, enemy, arcane,
modular-part, policy or unknown dependency changes invalidate all entries.
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
SCHEMA = 1


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes((json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode())
    tmp.replace(path)


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
    # Include optional native code and all engine modules, even if an older
    # global fingerprint omitted one. No code-change reuse is inferred.
    engine = Path(app.optimizer.__file__).resolve().parent
    for path in engine.iterdir():
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
    shared = {}
    for path, raw in paths.items():
        # Fully hydrated rows below include inheritance, mode overrides,
        # Incarnon patches and runtime catalog policy for each weapon.
        if path == weapons_path:
            document = json.loads(raw)
            shared["weapons-header"] = digest({k:v for k,v in document.items() if k not in ("data", "count")})
            continue
        name = path.name
        # Preserve distinct same-name files instead of silently overwriting.
        rel = str(path.relative_to(app.ROOT)) if path.is_relative_to(app.ROOT) else str(path)
        if path.suffix == ".py":
            raw = raw.replace(b"\r\n", b"\n")
        shared[rel.replace("\\", "/")] = hashlib.sha256(raw).hexdigest()
    catalog = app.CATALOG_WEAPONS_BY_PATH
    records = {str(w["path"]): digest({"weapon": w, "catalog": catalog.get(w["path"])})
               for w in app.EXPORTS["weapons"] if w.get("path")}
    return {"schema": SCHEMA, "inputs": inputs, "cacheVersion": app.ANALYSIS_STATICS_CACHE_VERSION,
            "buildLabel": app.EXPORTS["buildLabel"], "stances": app._stances_fingerprint(),
            "shared": shared, "records": records}


def select(previous, current, entries):
    """Fail closed: every reused context must resolve to an unchanged record."""
    if any(previous.get(k) != current.get(k) for k in ("schema", "cacheVersion", "buildLabel", "stances", "shared")):
        return {}, "shared-dependencies-changed"
    retained = {}
    for key, entry in entries.items():
        try:
            context = json.loads(key)
            identity = context["weapon"].split("#", 1)[0]
        except (ValueError, TypeError, KeyError, AttributeError):
            continue
        old = previous.get("records", {}).get(identity)
        if old and old == current.get("records", {}).get(identity) and isinstance(entry, dict):
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
                    if (shard.get("schemaVersion") != 3 or shard.get("inputs") != current["inputs"]
                            or shard.get("cacheVersion") != current["cacheVersion"] or shard.get("profile") != profile):
                        continue
                    keys = list(shard.get("entries", {}))
                    if keys and all(k in entries and entries[k] == shard["entries"][k] for k in keys):
                        groups.append({"profile": profile, "file": path.name, "keys": keys})
            body["shards"] = groups
        identity = digest(body)
        atomic(args.store / "objects" / (identity + ".json"), body)
        atomic(args.store / "latest.json", {"object": identity})
        report = {"saved": len(entries), "object": identity, "inputs": current["inputs"]}
    else:
        pointer = json.loads((args.store / "latest.json").read_bytes())
        identity = pointer["object"]
        if not isinstance(identity, str) or len(identity) != 64 or any(c not in "0123456789abcdef" for c in identity):
            raise ValueError("invalid cache object identity")
        body = json.loads((args.store / "objects" / (identity + ".json")).read_bytes())
        if digest(body) != identity:
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
                atomic(path, {"schemaVersion": 3, "cacheVersion": current["cacheVersion"],
                              "inputs": current["inputs"], "profile": profile,
                              "entries": {k:retained[k] for k in keys}})
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
