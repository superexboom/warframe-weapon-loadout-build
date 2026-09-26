"""Prepare immutable data snapshots and activate them with one atomic pointer."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_sources import active_build, dataset_root, load_source_lock, validate_build
from audit_data_pipeline import audit

REQUIRED_INPUTS = {
    "rawRoot", "languages", "fontRoot", "wikiSnapshot", "warframeItems", "modIndex",
    "weaponIndex", "enemyExport", "artRoot", "completeArtRoot", "menuIcons", "umbraForma",
    "companionMods", "modframeRoot", "zaws",
}
OPTIONAL_INPUTS = {"incarnonDefaults", "overframeSchema", "stanceTable"}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            handle.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_config(path: Path) -> tuple[str, dict[str, Path]]:
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ValueError("input config must have schemaVersion 1")
    build = validate_build(str(payload.get("build") or ""))
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        raise ValueError("input config must contain an inputs object")
    missing = REQUIRED_INPUTS - inputs.keys()
    unknown = inputs.keys() - REQUIRED_INPUTS - OPTIONAL_INPUTS
    if missing or unknown:
        raise ValueError(f"input keys: missing={sorted(missing)}, unknown={sorted(unknown)}")
    resolved = {}
    for key, value in inputs.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"input {key} must be a non-empty path")
        resolved[key] = (path.resolve().parent / value).resolve()
    return build, resolved


def source_paths(inputs: dict[str, Path]) -> dict[str, Path]:
    return {
        "packages": inputs["rawRoot"] / "Packages.bin",
        "languages-en": inputs["languages"] / "en.json",
        "languages-zh": inputs["languages"] / "zh.json",
        "warframe-items": inputs["warframeItems"],
        "wiki-abilities": inputs["wikiSnapshot"],
        "blackcat-mods": inputs["modIndex"],
        "blackcat-weapons": inputs["weaponIndex"],
        "public-export-plus-enemies": inputs["enemyExport"],
        "official-companion-assets": inputs["companionMods"],
    }


def preflight(build: str, inputs: dict[str, Path]) -> None:
    required = list(inputs.values()) + [
        inputs["rawRoot"] / "Packages.bin", inputs["rawRoot"] / "packages" / "Lotus",
        inputs["rawRoot"] / "dump.json", inputs["languages"] / "en.json", inputs["languages"] / "zh.json",
        *(inputs["warframeItems"] / "json" / name for name in ("Mods.json", "Warframes.json", "Arcanes.json", "i18n.json")),
        inputs["warframeItems"] / "img",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise ValueError("missing inputs:\n" + "\n".join(missing))
    if inputs["rawRoot"].name != build or read_json(inputs["rawRoot"] / "dump.json").get("buildLabel") != build:
        raise ValueError("rawRoot directory name and dump.json buildLabel must match config build")
    for key in ("zaws", "incarnonDefaults"):
        if key in inputs:
            payload = read_json(inputs[key])
            if (payload.get("buildLabel") or payload.get("gameBuild")) != build:
                raise ValueError(f"{key} must be explicitly reviewed for build {build}")
    if not next(inputs["fontRoot"].rglob("*.lua_B"), None) or not next(inputs["fontRoot"].rglob("*.lua_H"), None):
        raise ValueError("fontRoot must contain paired .lua_B and .lua_H exports")


def copy_runtime(root: Path, destination: Path, *, include_export: bool = True, snapshot: Path | None = None) -> None:
    lock = load_source_lock(snapshot or root)
    content = snapshot if snapshot is not None else dataset_root(root, lock)
    if (content / "snapshot.json").is_file() and not lock.get("snapshotId"):
        lock["snapshotId"] = sha256(content / "snapshot.json")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copytree(content / "data", destination / "data", ignore=shutil.ignore_patterns("snapshots", "export", "cache"))
    # Mechanics metadata ships with the engine, independently of a game snapshot.
    mechanics = root / 'data/mechanics'
    if mechanics.is_dir():
        shutil.copytree(mechanics, destination / 'data/mechanics', dirs_exist_ok=True)
    if include_export:
        build = validate_build(str(lock["activeBuild"]))
        shutil.copytree(content / "data" / "export" / build, destination / "data" / "export" / build)
    shutil.copytree(root / "frontend", destination / "frontend", ignore=shutil.ignore_patterns("assets"))
    shutil.copytree(content / "frontend" / "assets", destination / "frontend" / "assets")
    lock.pop("snapshotRoot", None)
    write_json(destination / "data" / "source-lock.json", lock)


def payload_hashes(root: Path) -> dict[str, str]:
    result = {}
    for directory in (root / "data", root / "frontend" / "assets"):
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"snapshot may not contain symlinks: {path}")
            if path.is_file():
                result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def verify_snapshot(root: Path) -> dict[str, Any]:
    record = read_json(root / "snapshot.json")
    if record.get("schemaVersion") != 1 or record.get("status") != "ready":
        raise ValueError("snapshot has not passed validation")
    lock = load_source_lock(root)
    if lock.get("snapshotRoot") or record.get("build") != lock["activeBuild"]:
        raise ValueError("snapshot build or layout mismatch")
    if not record.get("files") or payload_hashes(root) != record["files"]:
        raise ValueError("snapshot files changed after validation")
    check_frozen(root)
    return record


def check_frozen(root: Path, *, lock: dict[str, Any] | None = None) -> dict[str, Any]:
    lock = lock if lock is not None else load_source_lock(root)
    report = audit(str(lock["activeBuild"]), root=root, lock_override=lock)
    if report["errors"]:
        raise ValueError("frozen validation failed:\n" + "\n".join(report["errors"]))
    return report


def run_stage(stage: Path, script: str, *arguments: Any) -> None:
    print(f"Running {script}", flush=True)
    logs = stage / ".local" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    bootstrap = (
        "import runpy,sys; from pathlib import Path; root=Path(sys.argv[1]); "
        "sys.path[:0]=[str(root),str(root/'vendor'),str(root/'tools')]; "
        "sys.argv=sys.argv[2:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    env = dict(os.environ)
    env.pop("WF_RIVEN_BUILD", None)
    with (logs / (Path(script).stem + ".log")).open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [sys.executable, "-I", "-c", bootstrap, str(stage), str(stage / script), *map(str, arguments)],
            cwd=stage, env=env, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, timeout=1800,
        )
    if result.returncode:
        raise RuntimeError(f"{script} failed ({result.returncode}); see {log.name}")


def prepare(root: Path, config: Path) -> Path:
    build, inputs = load_config(config)
    preflight(build, inputs)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stage = root / ".local" / "pipeline" / f"{build}-{stamp}-{uuid4().hex[:8]}"
    print(f"Stage: {stage}", flush=True)
    copy_runtime(root, stage, include_export=False)
    for path in root.glob("*.py"):
        shutil.copy2(path, stage / path.name)
    for name in ("tools", "vendor"):
        shutil.copytree(root / name, stage / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("README.md", "README.en.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(root / name, stage / name)
    lock = load_source_lock(stage)
    lock["activeBuild"] = build
    lock["snapshotId"] = stage.name
    write_json(stage / "data" / "source-lock.json", lock)
    export = stage / "data" / "export" / build
    export.mkdir(parents=True)
    for key, name in (("zaws", "zaws.json"), ("incarnonDefaults", "incarnon_defaults.json")):
        if key in inputs:
            shutil.copy2(inputs[key], export / name)
    for key, name in (("overframeSchema", "overframe_abilitystats.json"), ("stanceTable", "sources/wiki/stance_data_2026-08-23.lua")):
        if key in inputs:
            shutil.copy2(inputs[key], stage / "data" / name)
    sources = source_paths(inputs)
    initial_hashes = {key: sha256(path) for key, path in sources.items() if path.is_file()}
    raw = inputs["rawRoot"] / "packages"
    languages = inputs["languages"]
    items = inputs["warframeItems"]
    run_stage(stage, "vendor/wfarsenal/extract.py", inputs["rawRoot"], export,
              "--locale", f"en={languages / 'en.json'}", "--locale", f"zh={languages / 'zh.json'}")
    run_stage(stage, "tools/generate_kitguns.py", "--raw-root", inputs["rawRoot"], "--build-label", build,
              "--localization", inputs["weaponIndex"], "--output", export / "kitguns.json")
    run_stage(stage, "tools/generate_riven_templates.py", "--build", build, "--raw-packages", raw,
              "--localization", languages / "zh.json", "--weapons", export / "weapons.json", "--output", export / "riven_templates.json")
    run_stage(stage, "tools/refresh_riven_fusion.py", "--raw-packages", raw,
              "--output", export / "riven_templates.json")
    run_stage(stage, "sync_enemy_overrides.py", "--export-dir", export, "--raw", inputs["enemyExport"], "--output", export / "enemy_overrides.json")
    run_stage(stage, "sync_incarnon_strings.py", "--build", build, "--export-dir", export, "--localization", languages / "zh.json")
    run_stage(stage, "generate_game_data.py", "--build", build, "--export-dir", export, "--raw-packages", raw,
              "--output-dir", stage / "data", "--rabbit-mods", inputs["modIndex"], "--rabbit-weapons", inputs["weaponIndex"],
              "--warframe-items", items / "json/Mods.json", "--item-i18n", items / "json/i18n.json", "--languages", languages)
    catalog = stage / "data/warframe_build_data.json"
    runtime = stage / "data/ability_runtime_fields.json"
    run_stage(stage, "generate_warframe_data.py", "--build", build, "--export-dir", export, "--raw", raw, "--items", items,
              "--localization", languages / "zh.json", "--wiki", inputs["wikiSnapshot"], "--rabbit-assets", inputs["artRoot"],
              "--rabbit-mods", inputs["modIndex"], "--output", catalog)
    run_stage(stage, "tools/extract_ability_luau_ir.py", "--catalog", catalog, "--packages-root", raw, "--font-root", inputs["fontRoot"],
              "--localization-en", languages / "en.json", "--localization-zh", languages / "zh.json", "--wiki", inputs["wikiSnapshot"], "--output", runtime)
    run_stage(stage, "tools/diff_ability_runtime_fields.py", "--catalog", catalog, "--runtime", runtime, "--output", stage / "data/ability_runtime_diff.json")
    run_stage(stage, "tools/promote_ability_runtime_fields.py", "--catalog", catalog, "--runtime", runtime, "--output", catalog)
    run_stage(stage, "tools/bake_archon_frames.py")
    run_stage(stage, "sync_mod_assets.py", "--export-dir", export, "--mod-index", inputs["modIndex"], "--art-root", inputs["artRoot"],
              "--complete-art-root", inputs["completeArtRoot"], "--menu-icons", inputs["menuIcons"], "--umbra-forma", inputs["umbraForma"],
              "--companion-mods", inputs["companionMods"], "--warframe-items", items, "--warframe-items-img", items / "img",
              "--i18n", items / "json/i18n.json", "--lang", languages / "zh.json", "--modframe-root", inputs["modframeRoot"],
              "--arcanes", export / "arcanes.json")
    run_stage(stage, "tools/repair_content_assets.py", "--official-art", inputs["completeArtRoot"],
              "--items", items, "--packages", raw, "--export", export,
              "--report", stage / ".local/content-assets-repair.json")
    if initial_hashes != {key: sha256(sources[key]) for key in initial_hashes}:
        raise ValueError("source files changed during generation; prepare from immutable inputs")
    for source in lock["sources"]:
        path = sources.get(source["id"]) if source.get("input") else stage / source["path"].replace("{build}", build)
        if source.get("input"):
            source.pop("revision", None)
            source.pop("pageCount", None)
        if path is not None and path.is_file():
            source["sha256"] = sha256(path)
        if "pinnedBuild" in source:
            source["pinnedBuild"] = build
        if source.get("parser"):
            source["parserSha256"] = sha256(stage / source["parser"])
    lock["overframeExclusiveData"] = [
        {"dataset": item["dataset"]} for item in lock.get("overframeExclusiveData", [])
    ]
    write_json(stage / "data/source-lock.json", lock)
    report = audit(build, root=stage, source_paths=sources)
    write_json(stage / ".local/source-audit.json", report)
    if report["errors"]:
        raise ValueError("candidate audit failed:\n" + "\n".join(report["errors"]))
    run_stage(stage, "tools/check_runtime.py")
    write_json(stage / "snapshot.json", {"schemaVersion": 1, "status": "ready", "build": build, "files": payload_hashes(stage)})
    print(f"Prepared: {stage}", flush=True)
    return stage


@contextmanager
def activation_lock(root: Path):
    path = root / ".local/pipeline/activation.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def switch_lock(root: Path, target: dict[str, Any]) -> Path:
    check_frozen(root, lock=target)
    backup = root / ".local/pipeline/backups" / f"{uuid4().hex}.json"
    write_json(backup, load_source_lock(root))
    write_json(root / "data/source-lock.json", target)
    return backup


def activate(root: Path, snapshot: Path) -> Path:
    snapshot = snapshot.resolve()
    record = verify_snapshot(snapshot)
    with activation_lock(root):
        identifier = f"{validate_build(record['build'])}-{uuid4().hex[:12]}"
        installed = root / "data/snapshots" / identifier
        installed.mkdir(parents=True, exist_ok=False)
        shutil.copytree(snapshot / "data", installed / "data")
        shutil.copytree(snapshot / "frontend/assets", installed / "frontend/assets")
        shutil.copy2(snapshot / "snapshot.json", installed / "snapshot.json")
        verify_snapshot(installed)
        target = load_source_lock(installed)
        target["snapshotRoot"] = installed.relative_to(root).as_posix()
        backup = switch_lock(root, target)
    print(f"Activated: {identifier}\nRollback file: {backup}\nRestart the application to load this snapshot.")
    return backup


def rollback(root: Path, backup: Path) -> Path:
    backup = backup.resolve()
    if not backup.is_relative_to((root / ".local/pipeline/backups").resolve()):
        raise ValueError("rollback file must be under .local/pipeline/backups")
    target = read_json(backup)
    with activation_lock(root):
        if target.get("snapshotRoot"):
            verify_snapshot(dataset_root(root, target))
        undo = switch_lock(root, target)
    print(f"Restored: {target['activeBuild']}\nUndo file: {undo}\nRestart the application to load this snapshot.")
    return undo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate bundled outputs; no original inputs required")
    check.add_argument("--sources", type=Path, metavar="CONFIG", help="also validate original sources using this input config")
    prepare_cmd = commands.add_parser("prepare", help="generate and validate a candidate without activation")
    prepare_cmd.add_argument("--config", type=Path, required=True)
    commands.add_parser("activate").add_argument("snapshot", type=Path)
    commands.add_parser("rollback").add_argument("backup", type=Path)
    bundle_cmd = commands.add_parser("bundle", help="stage only the selected runtime data and assets")
    bundle_cmd.add_argument("destination", type=Path)
    bundle_cmd.add_argument("--snapshot", type=Path, help="package a validated candidate without activating it")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command == "prepare":
            prepare(root, args.config)
        elif args.command == "activate":
            activate(root, args.snapshot)
        elif args.command == "rollback":
            rollback(root, args.backup)
        elif args.command == "bundle":
            lock = load_source_lock(root)
            if args.snapshot:
                verify_snapshot(args.snapshot.resolve())
            elif lock.get("snapshotRoot"):
                verify_snapshot(dataset_root(root, lock))
            else:
                check_frozen(root)
            copy_runtime(root, args.destination.resolve(), snapshot=args.snapshot.resolve() if args.snapshot else None)
            print(f"Bundled runtime: {args.destination.resolve()}")
        else:
            lock = load_source_lock(root)
            if lock.get("snapshotRoot"):
                verify_snapshot(dataset_root(root, lock))
            sources = None
            if args.sources:
                build, inputs = load_config(args.sources)
                if build != active_build(root):
                    raise ValueError("source config build differs from active build")
                sources = source_paths(inputs)
            report = audit(active_build(root), root=root, source_paths=sources)
            print(json.dumps({"build": report["build"], "scope": report["scope"], "status": report["status"], "errors": report["errors"]}, indent=2))
            return 1 if report["errors"] else 0
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
