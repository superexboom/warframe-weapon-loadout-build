from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_sources import active_build, load_source_lock, provenance_path, resolve_source_path  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _parser_hash(path: Path) -> str:
    return _sha256(path)


def _rows(payload: Any) -> list[Any]:
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload["data"]
    return payload if isinstance(payload, list) else []


def audit(build: str) -> dict[str, Any]:
    lock = load_source_lock(ROOT)
    errors: list[str] = []
    warnings: list[str] = []
    source_rows = []
    for source in lock.get("sources") or []:
        path = resolve_source_path(str(source["path"]), root=ROOT, build=build)
        exists = path.exists()
        row = {
            "id": source["id"],
            "kind": source["kind"],
            "path": provenance_path(path),
            "required": bool(source.get("required")),
            "exists": exists,
        }
        expected_hash = source.get("sha256")
        hash_is_for_build = not source.get("pinnedBuild") or source.get("pinnedBuild") == build
        if exists and path.is_file() and expected_hash and build == lock["activeBuild"] and hash_is_for_build:
            row["sha256"] = _sha256(path)
            row["hashMatches"] = row["sha256"].casefold() == str(expected_hash).casefold()
            if not row["hashMatches"]:
                errors.append(f"source hash changed: {source['id']}")
        if not exists and source.get("required"):
            errors.append(f"required source missing: {source['id']} -> {path}")
        source_rows.append(row)

    export_root = ROOT / "data" / "export" / build
    output_specs = {
        "weapons": (export_root / "weapons.json", True),
        "warframes": (export_root / "warframes.json", True),
        "mods": (export_root / "mods.json", True),
        "enemies": (export_root / "enemies.json", True),
        "arcanes": (export_root / "arcanes.json", True),
        "kitguns": (export_root / "kitguns.json", True),
        "zaws": (export_root / "zaws.json", True),
        "rivenTemplates": (export_root / "riven_templates.json", True),
        "enemyOverrides": (export_root / "enemy_overrides.json", True),
        "incarnonDefaults": (export_root / "incarnon_defaults.json", False),
        "incarnonStrings": (export_root / "incarnon_strings.json", True),
        "stances": (ROOT / "data" / "stances.json", True),
        "utilityMods": (ROOT / "data" / "utility_mods.json", True),
        "exaltedWeapons": (ROOT / "data" / "exalted_weapons.json", True),
        "warframeBuildData": (ROOT / "data" / "warframe_build_data.json", True),
        "abilityRuntimeFields": (ROOT / "data" / "ability_runtime_fields.json", True),
        "abilityRuntimeDiff": (ROOT / "data" / "ability_runtime_diff.json", True),
        "modAssets": (ROOT / "frontend" / "assets" / "mods" / "index.json", True),
    }
    output_rows = []
    for name, (path, required) in output_specs.items():
        row: dict[str, Any] = {"id": name, "path": provenance_path(path), "required": required, "exists": path.is_file()}
        if not path.is_file():
            (errors if required else warnings).append(f"{'output missing' if required else 'optional output missing'}: {name} -> {path}")
            output_rows.append(row)
            continue
        payload = _load(path)
        label = payload.get("buildLabel") or payload.get("gameBuild") if isinstance(payload, dict) else None
        row["buildLabel"] = label
        data = payload.get("data") if isinstance(payload, dict) else None
        row["count"] = len(data) if isinstance(data, (list, dict)) else len(_rows(payload))
        if isinstance(payload, dict) and payload.get("missingTags"):
            warnings.append(f"{name} missing localized tags: {len(payload['missingTags'])}")
        if isinstance(payload, dict) and isinstance(payload.get("counts"), dict):
            row["counts"] = payload["counts"]
        if label and label != build:
            errors.append(f"output build mismatch: {name}={label}, expected {build}")
        output_rows.append(row)

    overframe_path = ROOT / "data" / "overframe_abilitystats.json"
    overframe = _load(overframe_path) if overframe_path.is_file() else {}
    warframe_path = ROOT / "data" / "warframe_build_data.json"
    warframe = _load(warframe_path) if warframe_path.is_file() else {}
    unique_abilities = {row["id"]: row for row in warframe.get("abilities") or [] if row.get("id")}
    ability_fields = [field for row in unique_abilities.values() for field in row.get("scalars") or []]
    field_sources = Counter(str(field.get("sourceKind") or "unknown") for field in ability_fields)
    runtime_path = ROOT / "data" / "ability_runtime_fields.json"
    runtime = _load(runtime_path) if runtime_path.is_file() else {}
    runtime_summary = runtime.get("summary") if isinstance(runtime, dict) else {}
    parser_path = ROOT / "tools" / "extract_ability_luau_ir.py"
    parser_hash = _parser_hash(parser_path) if parser_path.is_file() else None
    runtime_scripts = runtime.get("scripts") if isinstance(runtime, dict) else []
    runtime_delegated_scripts = runtime.get("delegatedScripts") if isinstance(runtime, dict) else []
    runtime_all_scripts = [
        row for row in [*(runtime_scripts if isinstance(runtime_scripts, list) else []), *(runtime_delegated_scripts if isinstance(runtime_delegated_scripts, list) else [])]
        if isinstance(row, dict)
    ]
    runtime_abilities = runtime.get("abilities") if isinstance(runtime, dict) else []
    runtime_ability_fields = [
        field
        for row in runtime_abilities
        if isinstance(row, dict)
        for field in row.get("resolvedFields") or []
        if isinstance(field, dict)
    ]
    runtime_wiki_fields = [
        field
        for row in runtime_abilities
        if isinstance(row, dict) and row.get("delegatedSource") == "wiki-snapshot"
        for field in row.get("resolvedFields") or []
        if isinstance(field, dict)
    ]
    runtime_wiki_matched_fields = [
        field for field in runtime_ability_fields if field.get("wikiMatch")
    ]
    runtime_catalog_fallback_fields = [
        field for field in runtime_ability_fields if field.get("catalogFallback")
    ]
    runtime_schema_rows = sum(
        len(row.get("querySchema") or [])
        for row in runtime_all_scripts
        if isinstance(row, dict)
    )
    runtime_numeric_fields = sum(bool(field.get("rankValues")) for field in runtime_ability_fields)
    runtime_resolved_rows = len(runtime_ability_fields)
    runtime_confidence = Counter(str(field.get("confidence") or "unresolved") for field in runtime_ability_fields)
    runtime_coverage = {
        "stage": runtime.get("stage") if isinstance(runtime, dict) else None,
        "status": runtime.get("status") if isinstance(runtime, dict) else None,
        "buildLabel": runtime.get("buildLabel") if isinstance(runtime, dict) else None,
        "abilities": len(runtime_abilities),
        "mappedAbilities": sum(row.get("status") == "wire-ir" for row in runtime_abilities if isinstance(row, dict)),
        "uniqueScripts": len(runtime_scripts),
        "pairedScripts": sum(bool(row.get("headerFile")) for row in runtime_scripts if isinstance(row, dict)),
        "delegatedScripts": len(runtime_delegated_scripts) if isinstance(runtime_delegated_scripts, list) else 0,
        "delegatedPairedScripts": sum(bool(row.get("headerFile")) for row in runtime_delegated_scripts if isinstance(row, dict)),
        "wikiFallbackAbilities": sum(row.get("delegatedSource") == "wiki-snapshot" for row in runtime_abilities if isinstance(row, dict)),
        "wikiFallbackFields": len(runtime_wiki_fields),
        "wikiMatchedFields": len(runtime_wiki_matched_fields),
        "catalogFallbackFields": len(runtime_catalog_fallback_fields),
        "querySchemaRows": runtime_schema_rows,
        "resolvedFieldRows": runtime_resolved_rows,
        "resolvedConfidence": dict(sorted(runtime_confidence.items())),
        "numericFieldsRecovered": runtime_numeric_fields,
        "parserHash": parser_hash,
        "scriptResolvedFieldRows": sum(
            len(row.get("resolvedFields") or [])
            for row in runtime_all_scripts
            if isinstance(row, dict)
        ),
        "scriptResolvedConfidence": dict(sorted(Counter(
            str(field.get("confidence") or "unresolved")
            for row in runtime_all_scripts
            if isinstance(row, dict)
            for field in row.get("resolvedFields") or []
            if isinstance(field, dict)
        ).items())),
        "scriptNumericFieldsRecovered": sum(
            bool(field.get("rankValues"))
            for row in runtime_all_scripts
            if isinstance(row, dict)
            for field in row.get("resolvedFields") or []
            if isinstance(field, dict)
        ),
    }
    if runtime:
        if runtime_coverage["buildLabel"] != build:
            errors.append(f"ability runtime sidecar build mismatch: {runtime_coverage['buildLabel']} != {build}")
        if runtime_coverage["abilities"] != len(unique_abilities):
            errors.append(f"ability runtime sidecar ability count mismatch: {runtime_coverage['abilities']} != {len(unique_abilities)}")
        expected_scripts = runtime_summary.get("uniqueScripts") if isinstance(runtime_summary, dict) else None
        if expected_scripts != runtime_coverage["uniqueScripts"]:
            errors.append("ability runtime sidecar script summary mismatch")
        if runtime_summary.get("pairedScripts") != runtime_coverage["pairedScripts"] or runtime_coverage["pairedScripts"] != runtime_coverage["uniqueScripts"]:
            errors.append("ability runtime sidecar B/H pairing is incomplete")
        if runtime_summary.get("delegatedScripts") != runtime_coverage["delegatedScripts"] or runtime_summary.get("delegatedPairedScripts") != runtime_coverage["delegatedPairedScripts"]:
            errors.append("ability runtime sidecar delegated script summary mismatch")
        if runtime_summary.get("wikiFallbackAbilities") != runtime_coverage["wikiFallbackAbilities"] or runtime_summary.get("wikiFallbackFields") != runtime_coverage["wikiFallbackFields"]:
            errors.append("ability runtime sidecar Wiki fallback summary mismatch")
        if runtime_summary.get("wikiMatchedFields") != runtime_coverage["wikiMatchedFields"]:
            errors.append("ability runtime sidecar Wiki match summary mismatch")
        if runtime_summary.get("catalogFallbackFields") != runtime_coverage["catalogFallbackFields"]:
            errors.append("ability runtime sidecar catalog fallback summary mismatch")
        if runtime_summary.get("querySchemaRows") != runtime_schema_rows:
            errors.append("ability runtime sidecar schema row summary mismatch")
        if runtime_summary.get("resolvedFieldRows") != runtime_resolved_rows:
            errors.append("ability runtime sidecar resolved row summary mismatch")
        if runtime_summary.get("resolvedConfidence") != dict(sorted(runtime_confidence.items())):
            errors.append("ability runtime sidecar confidence summary mismatch")
        if runtime_summary.get("numericFieldsRecovered") != runtime_numeric_fields:
            errors.append("ability runtime sidecar numeric field summary mismatch")
        if runtime.get("decoderRevision") != parser_hash:
            errors.append("ability runtime sidecar parser hash mismatch")
        diff_parser = ROOT / "tools" / "diff_ability_runtime_fields.py"
        expected_diff_parser = _sha256(diff_parser) if diff_parser.is_file() else None
        diff_lock = next((source for source in lock.get("sources") or [] if source.get("id") == "game-font-luau-ability-diff"), {})
        if diff_lock.get("parserSha256") and diff_lock.get("parserSha256") != expected_diff_parser:
            errors.append("ability runtime diff parser hash changed")
        required_tokens = runtime_summary.get("requiredTokenCoverage") if isinstance(runtime_summary, dict) else {}
        if any(value != runtime_coverage["uniqueScripts"] for value in required_tokens.values()):
            errors.append("ability runtime sidecar query token coverage is incomplete")
    runtime_diff_path = ROOT / "data" / "ability_runtime_diff.json"
    runtime_diff = _load(runtime_diff_path) if runtime_diff_path.is_file() else {}
    runtime_diff_summary = runtime_diff.get("summary") if isinstance(runtime_diff, dict) else {}
    if runtime_diff:
        if runtime_diff.get("buildLabel") != build:
            errors.append(f"ability runtime diff build mismatch: {runtime_diff.get('buildLabel')} != {build}")
        if runtime_diff_summary.get("abilities") != len(unique_abilities):
            errors.append("ability runtime diff ability count mismatch")
    promotion = warframe.get("provenance", {}).get("abilityRuntimePromotion") if isinstance(warframe, dict) else None
    if not isinstance(promotion, dict):
        errors.append("warframe catalog has no ability runtime promotion provenance")
    elif promotion.get("sidecarBuild") != build:
        errors.append("warframe catalog promotion build mismatch")
    elif promotion.get("decoderRevision") != (runtime.get("decoderRevision") if isinstance(runtime, dict) else None):
        errors.append("warframe catalog promotion decoder mismatch")
    elif promotion.get("sidecarSha256") != (_sha256(runtime_path) if runtime_path.is_file() else None):
        errors.append("warframe catalog promotion sidecar hash mismatch")
    else:
        promotion_parser = ROOT / "tools" / "promote_ability_runtime_fields.py"
        if promotion.get("promotionParserSha256") != (_sha256(promotion_parser) if promotion_parser.is_file() else None):
            errors.append("warframe catalog promotion parser hash mismatch")
    incarnon_path = export_root / "incarnon_defaults.json"
    incarnon = _load(incarnon_path) if incarnon_path.is_file() else {}
    strategies = incarnon.get("strategies") or {}
    weapons_path = export_root / "weapons.json"
    weapons = _rows(_load(weapons_path)) if weapons_path.is_file() else []
    dispositions = sum(
        isinstance(row.get("omegaAttenuation"), (int, float)) and row["omegaAttenuation"] > 0
        for row in weapons
    )
    templates_path = export_root / "riven_templates.json"
    templates = _load(templates_path) if templates_path.is_file() else {}
    manual = list(lock.get("manualReview") or [])
    if manual:
        warnings.extend(f"manual review: {item}" for item in manual)
    return {
        "schemaVersion": 1,
        "build": build,
        "activeBuild": active_build(ROOT),
        "status": "ready" if not errors else "invalid",
        "sources": source_rows,
        "outputs": output_rows,
        "coverage": {
            "weaponDispositions": {"positive": dispositions, "weapons": len(weapons)},
            "rivenTemplates": templates.get("counts") or {},
            "overframe": {
                "exclusiveDatasets": lock.get("overframeExclusiveData") or [],
                "abilityKeys": len(overframe),
                "rawAbilityFields": sum(len(value) for value in overframe.values() if isinstance(value, list)),
                "matchedUniqueAbilities": sum(
                    any(item.get("kind") == "overframe-abilitystats" for item in row.get("sourceEvidence") or [])
                    for row in unique_abilities.values()
                ),
                "finalAbilityFieldsBySource": dict(sorted(field_sources.items())),
                "incarnonStrategies": len(strategies),
                "incarnonBuildReferences": sum(len(row.get("builds") or []) for row in strategies.values()),
            },
            "abilityRuntime": runtime_coverage,
            "abilityRuntimeDiff": runtime_diff_summary,
        },
        "errors": errors,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit the frozen data pipeline and source lock")
    parser.add_argument("--build", default=active_build(ROOT))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = audit(args.build)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"build: {report['build']} ({report['status']})")
    print(f"sources: {sum(row['exists'] for row in report['sources'])}/{len(report['sources'])}")
    required_outputs = [row for row in report["outputs"] if row["required"]]
    print(f"outputs: {sum(row['exists'] for row in required_outputs)}/{len(required_outputs)} required")
    overframe = report["coverage"]["overframe"]
    print(
        "Overframe-only: "
        f"ability schema {overframe['matchedUniqueAbilities']} abilities / "
        f"{overframe['finalAbilityFieldsBySource'].get('overframe-abilitystats', 0)} final fields; "
        f"Incarnon defaults {overframe['incarnonStrategies']} routes"
    )
    runtime = report["coverage"]["abilityRuntime"]
    print(
        "Ability runtime sidecar: "
        f"{runtime['buildLabel']} / {runtime['mappedAbilities']} abilities / "
        f"{runtime['uniqueScripts']} scripts / {runtime['querySchemaRows']} schema rows / "
        f"{runtime['resolvedFieldRows']} resolved rows / {runtime['numericFieldsRecovered']} numeric fields"
    )
    diff = report["coverage"].get("abilityRuntimeDiff") or {}
    if diff:
        print(
            "Ability runtime diff: "
            f"{diff.get('runtimeFieldRows', 0)} rows / "
            f"{diff.get('value.agree', 0)} agree / "
            f"{diff.get('value.differ', 0)} differ / "
            f"{diff.get('catalogOnlyFields', 0)} catalog-only"
        )
    for error in report["errors"]:
        print(f"ERROR: {error}")
    return 1 if args.strict and report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
