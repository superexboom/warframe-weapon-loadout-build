from __future__ import annotations

import argparse
import json
import posixpath
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "data" / "warframe_build_data.json"

REQUIRED_QUERY_TOKENS = (
    "GetAbilityUpgradeLevelInfo",
    "AbilityLevelQueryParms",
    "Label",
    "Value",
    "Modded",
)
OPTIONAL_QUERY_TOKENS = (
    "ValueUnit",
    "ValueIcon",
    "SmallerIsBetter",
    "NpcEvaluateAbility",
)

# These four records only override Umbra presentation/behaviour fields. Their
# ability implementation is inherited from the matching Excalibur ability.
UMBRA_ALIASES = {
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraSlashDashNewAbility":
        "/Lotus/Powersuits/Excalibur/Abilities/SlashDashNewAbility",
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraRadialRoarAbility":
        "/Lotus/Powersuits/Excalibur/Abilities/RadialBlindAbility",
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraRadialJavelinAbility":
        "/Lotus/Powersuits/Excalibur/Abilities/RadialJavelinAbility",
    "/Lotus/Powersuits/Excalibur/Abilities/UmbraSwordOfDoomAbility":
        "/Lotus/Powersuits/Excalibur/Abilities/SwordOfDoomAbility",
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _package_path(root: Path, ability_id: str) -> Path:
    return root / f"{ability_id.lstrip('/')}.json"


def _script_path(ability_id: str, reference: str) -> str:
    reference = reference.replace("\\", "/")
    if reference.startswith("/"):
        return "/" + posixpath.normpath(reference).lstrip("/")
    owner = posixpath.dirname(ability_id)
    return "/" + posixpath.normpath(posixpath.join(owner, reference)).lstrip("/")


def _direct_script(package: dict[str, Any]) -> str | None:
    script = package.get("Script")
    if not isinstance(script, dict):
        return None
    reference = script.get("Script")
    return reference if isinstance(reference, str) and reference else None


def _read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data) or shift > 35:
            raise ValueError("invalid Luau varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7


def _luau_strings(path: Path) -> tuple[int, int, set[str]]:
    data = path.read_bytes()
    if len(data) < 3:
        raise ValueError("Luau body is truncated")
    version, type_version = data[0], data[1]
    count, offset = _read_varint(data, 2)
    strings: set[str] = set()
    for _ in range(count):
        length, offset = _read_varint(data, offset)
        end = offset + length
        if end > len(data):
            raise ValueError("Luau string table is truncated")
        strings.add(data[offset:end].decode("utf-8", errors="replace"))
        offset = end
    return version, type_version, strings


def _font_index(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in root.rglob("*.lua_B"):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("Debug/"):
            relative = relative[len("Debug/") :]
        internal = "/" + relative.removesuffix("_B").lstrip("/")
        result.setdefault(internal.casefold(), path)
    return result


def _unique_abilities(payload: dict[str, Any]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    for row in payload.get("abilities") or []:
        ability_id = str(row.get("id") or row.get("path") or "")
        if not ability_id:
            continue
        current = selected.get(ability_id)
        if current is None or len(row.get("scalars") or ()) > len(current.get("scalars") or ()):
            selected[ability_id] = row
    return [selected[key] for key in sorted(selected)]


def audit(catalog_path: Path, packages_root: Path, font_root: Path) -> dict[str, Any]:
    catalog = _load_json(catalog_path)
    abilities = _unique_abilities(catalog)
    font_files = _font_index(font_root)
    source_kinds: Counter[str] = Counter()
    for ability in abilities:
        source_kinds.update(
            str(field.get("sourceKind") or "unknown")
            for field in ability.get("scalars") or ()
            if isinstance(field, dict)
        )

    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    script_cache: dict[str, tuple[int, int, set[str]] | Exception] = {}
    direct_count = 0
    aliases: list[dict[str, Any]] = []

    for ability in abilities:
        ability_id = str(ability.get("id") or ability.get("path"))
        package_path = _package_path(packages_root, ability_id)
        package: dict[str, Any] = {}
        if package_path.is_file():
            loaded = _load_json(package_path)
            package = loaded if isinstance(loaded, dict) else {}
        else:
            errors.append(f"package missing: {ability_id}")

        reference = _direct_script(package)
        alias_of = None
        resolution = "direct"
        if reference:
            direct_count += 1
            script_path = _script_path(ability_id, reference)
        else:
            alias_of = UMBRA_ALIASES.get(ability_id)
            resolution = "umbra-alias" if alias_of else "unresolved"
            script_path = ""
            if alias_of:
                alias_package_path = _package_path(packages_root, alias_of)
                alias_package = _load_json(alias_package_path) if alias_package_path.is_file() else {}
                alias_reference = _direct_script(alias_package) if isinstance(alias_package, dict) else None
                if alias_reference:
                    script_path = _script_path(alias_of, alias_reference)
                else:
                    errors.append(f"Umbra alias script missing: {ability_id} -> {alias_of}")
            else:
                errors.append(f"ability has no direct script or known alias: {ability_id}")

        script_file = font_files.get(script_path.casefold()) if script_path else None
        token_state: dict[str, bool] = {}
        header = None
        if script_path and script_file is None:
            errors.append(f"Font script missing: {script_path} ({ability_id})")
        elif script_file is not None:
            cached = script_cache.get(script_path)
            if cached is None:
                try:
                    cached = _luau_strings(script_file)
                except (OSError, ValueError) as exc:
                    cached = exc
                script_cache[script_path] = cached
            if isinstance(cached, Exception):
                errors.append(f"Luau string table invalid: {script_path}: {cached}")
            else:
                version, type_version, strings = cached
                header = {"version": version, "typeVersion": type_version}
                token_state = {
                    token: token in strings
                    for token in (*REQUIRED_QUERY_TOKENS, *OPTIONAL_QUERY_TOKENS)
                }
                missing = [token for token in REQUIRED_QUERY_TOKENS if not token_state[token]]
                if missing:
                    errors.append(f"query tokens missing: {script_path}: {', '.join(missing)}")

        field_sources = Counter(
            str(field.get("sourceKind") or "unknown")
            for field in ability.get("scalars") or ()
            if isinstance(field, dict)
        )
        row: dict[str, Any] = {
            "abilityId": ability_id,
            "nameEn": ability.get("nameEn") or "",
            "resolution": resolution,
            "scriptPath": script_path or None,
            "scriptFile": str(script_file) if script_file else None,
            "scriptHeader": header,
            "queryTokens": token_state,
            "currentFieldSources": dict(sorted(field_sources.items())),
        }
        if alias_of:
            row["aliasOf"] = alias_of
            aliases.append({
                "abilityId": ability_id,
                "aliasOf": alias_of,
                "scriptPath": script_path or None,
            })
        rows.append(row)

    mapped = [row for row in rows if row["scriptFile"]]
    unique_script_paths = sorted({str(row["scriptPath"]) for row in rows if row["scriptPath"]})
    token_coverage = {}
    for token in (*REQUIRED_QUERY_TOKENS, *OPTIONAL_QUERY_TOKENS):
        matching_abilities = [row for row in mapped if row["queryTokens"].get(token)]
        token_coverage[token] = {
            "abilities": len(matching_abilities),
            "directAbilities": sum(row["resolution"] == "direct" for row in matching_abilities),
            "uniqueScripts": len({row["scriptPath"] for row in matching_abilities}),
        }

    header_versions = Counter(
        f"{entry[0]}/{entry[1]}"
        for entry in script_cache.values()
        if isinstance(entry, tuple)
    )
    summary = {
        "catalogRows": len(catalog.get("abilities") or []),
        "uniqueAbilities": len(abilities),
        "packageFilesFound": sum(_package_path(packages_root, row["abilityId"]).is_file() for row in rows),
        "directScriptAbilities": direct_count,
        "umbraAliasAbilities": len(aliases),
        "mappedAbilities": len(mapped),
        "uniqueScripts": len(unique_script_paths),
        "availableUniqueScripts": len({row["scriptPath"] for row in mapped}),
        "fontExportScripts": len(font_files),
    }
    expected = {
        "uniqueAbilities": 267,
        "directScriptAbilities": 263,
        "umbraAliasAbilities": 4,
        "mappedAbilities": 267,
        "uniqueScripts": 260,
        "availableUniqueScripts": 260,
    }
    for key, value in expected.items():
        if summary[key] != value:
            errors.append(f"coverage changed: {key}={summary[key]}, expected {value}")

    return {
        "schemaVersion": 1,
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "status": "ready" if not errors else "incomplete",
        "inputs": {
            "catalog": str(catalog_path),
            "packagesRoot": str(packages_root),
            "fontRoot": str(font_root),
            "buildLabel": catalog.get("buildLabel"),
        },
        "summary": summary,
        "umbraAliases": aliases,
        "queryTokenCoverage": token_coverage,
        "scriptHeaderVersions": dict(sorted(header_versions.items())),
        "currentFieldSources": dict(sorted(source_kinds.items())),
        "abilities": rows,
        "errors": errors,
    }


def _default_packages_root() -> Path | None:
    lock_path = ROOT / "data" / "source-lock.json"
    if not lock_path.is_file():
        return None
    lock = _load_json(lock_path)
    source = next((row for row in lock.get("sources") or [] if row.get("id") == "packages"), None)
    if not source or not source.get("path"):
        return None
    path = Path(str(source["path"]))
    if not path.is_absolute():
        path = ROOT / path
    return path.parent / "packages" if path.name.casefold() == "packages.bin" else path


def _self_test() -> None:
    base_id = "/Lotus/Powersuits/Excalibur/Abilities/SlashDashNewAbility"
    alias_id = "/Lotus/Powersuits/Excalibur/Abilities/UmbraSlashDashNewAbility"
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        catalog = root / "catalog.json"
        packages = root / "packages"
        font = root / "font"
        package_file = _package_path(packages, base_id)
        package_file.parent.mkdir(parents=True)
        package_file.write_text(json.dumps({"Script": {"Script": "SlashDashNew.lua"}}), encoding="utf-8")
        alias_file = _package_path(packages, alias_id)
        alias_file.parent.mkdir(parents=True, exist_ok=True)
        alias_file.write_text("{}", encoding="utf-8")
        catalog.write_text(json.dumps({"abilities": [
            {"id": base_id, "scalars": [{"sourceKind": "overframe-abilitystats"}]},
            {"id": alias_id, "scalars": [{"sourceKind": "wiki-audited"}]},
        ]}), encoding="utf-8")
        body = bytearray((9, 3))
        strings = (*REQUIRED_QUERY_TOKENS, *OPTIONAL_QUERY_TOKENS)
        body.append(len(strings))
        for token in strings:
            encoded = token.encode()
            body.append(len(encoded))
            body.extend(encoded)
        script_file = font / "Debug" / "Lotus" / "Powersuits" / "Excalibur" / "Abilities" / "SlashDashNew.lua_B"
        script_file.parent.mkdir(parents=True)
        script_file.write_bytes(body)
        report = audit(catalog, packages, font)
        assert report["summary"]["uniqueAbilities"] == 2
        assert report["summary"]["directScriptAbilities"] == 1
        assert report["summary"]["umbraAliasAbilities"] == 1
        assert report["summary"]["uniqueScripts"] == 1
        assert report["queryTokenCoverage"]["GetAbilityUpgradeLevelInfo"]["abilities"] == 2
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Warframe ability-to-Luau source coverage")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--packages-root", type=Path, default=_default_packages_root())
    parser.add_argument("--font-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if args.packages_root is None or args.font_root is None:
        parser.error("--packages-root and --font-root are required when no default is available")
    report = audit(args.catalog.resolve(), args.packages_root.resolve(), args.font_root.resolve())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = report["summary"]
    print(f"status: {report['status']}")
    print(
        f"abilities: {summary['mappedAbilities']}/{summary['uniqueAbilities']} mapped "
        f"({summary['directScriptAbilities']} direct + {summary['umbraAliasAbilities']} Umbra aliases)"
    )
    print(f"scripts: {summary['availableUniqueScripts']}/{summary['uniqueScripts']} unique files")
    for token, coverage in report["queryTokenCoverage"].items():
        print(f"token {token}: {coverage['abilities']}/{summary['mappedAbilities']} abilities")
    print("field sources: " + ", ".join(f"{key}={value}" for key, value in report["currentFieldSources"].items()))
    for error in report["errors"]:
        print(f"ERROR: {error}")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
