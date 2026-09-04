from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def normalized(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def vector(field: dict[str, Any]) -> list[int | float] | None:
    values = field.get("rankValues")
    if isinstance(values, list) and values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return values
    values = field.get("values")
    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], (int, float)) and not isinstance(values[0], bool):
        return values * 4
    return None


def same_vector(left: list[int | float], right: list[int | float]) -> bool:
    if len(left) == 1 and len(right) == 4:
        left = left * 4
    if len(right) == 1 and len(left) == 4:
        right = right * 4
    return len(left) == len(right) and all(
        math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
        for a, b in zip(left, right)
    )


def unique_abilities(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result = {}
    for row in catalog.get("abilities") or []:
        ability_id = str(row.get("id") or row.get("path") or "")
        current = result.get(ability_id)
        if ability_id and (current is None or len(row.get("scalars") or ()) > len(current.get("scalars") or ())):
            result[ability_id] = row
    return result


def build_diff(catalog: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    catalog_abilities = unique_abilities(catalog)
    scripts = {row["scriptPath"]: row for row in runtime.get("scripts") or []}
    summary: Counter[str] = Counter()
    field_sources: Counter[str] = Counter()
    ability_diffs = []

    for mapping in runtime.get("abilities") or []:
        ability_id = str(mapping.get("abilityId") or "")
        catalog_row = catalog_abilities.get(ability_id, {})
        catalog_fields = [field for field in catalog_row.get("scalars") or [] if isinstance(field, dict)]
        runtime_fields = mapping.get("resolvedFields") or scripts.get(mapping.get("scriptPath"), {}).get("resolvedFields") or []
        used: set[int] = set()
        rows = []
        for runtime_field in runtime_fields:
            runtime_vector = vector(runtime_field)
            label = normalized(runtime_field.get("labelEn"))
            exact = [
                index for index, field in enumerate(catalog_fields)
                if index not in used and normalized(field.get("labelEn") or field.get("label") or field.get("id")) == label
            ]
            method = None
            candidates = exact
            if len(exact) == 1:
                method = "exact-label"
            elif not exact and runtime_vector:
                candidates = [
                    index for index, field in enumerate(catalog_fields)
                    if index not in used
                    and vector(field)
                    and same_vector(runtime_vector, vector(field) or [])
                    and (
                        runtime_field.get("modifier") in {None, "none"}
                        or field.get("scale") == runtime_field.get("modifier")
                    )
                ]
                if len(candidates) == 1:
                    method = "rank-vector"

            match = None
            if method and len(candidates) == 1:
                index = candidates[0]
                used.add(index)
                catalog_field = catalog_fields[index]
                catalog_vector = vector(catalog_field)
                if runtime_vector and catalog_vector:
                    value_status = "agree" if same_vector(runtime_vector, catalog_vector) else "differ"
                elif runtime_vector:
                    value_status = "catalog-missing-vector"
                else:
                    value_status = "runtime-unresolved"
                modifier = runtime_field.get("modifier") or "none"
                modifier_status = (
                    "not-applicable" if modifier == "none"
                    else "agree" if catalog_field.get("scale") == modifier
                    else "differ"
                )
                match = {
                    "method": method,
                    "catalogFieldId": catalog_field.get("id"),
                    "catalogLabelEn": catalog_field.get("labelEn") or catalog_field.get("label"),
                    "catalogSourceKind": catalog_field.get("sourceKind"),
                    "catalogRankValues": catalog_vector,
                    "valueStatus": value_status,
                    "modifierStatus": modifier_status,
                }
                summary[f"value.{value_status}"] += 1
                summary[f"modifier.{modifier_status}"] += 1
                summary[f"match.{method}"] += 1
                field_sources[str(catalog_field.get("sourceKind") or "unknown")] += 1
            else:
                status = "ambiguous" if len(candidates) > 1 else "runtime-only"
                summary[f"match.{status}"] += 1
                match = {"method": status, "candidateCount": len(candidates)}

            confidence = str(runtime_field.get("confidence") or "unresolved")
            summary[f"runtime.{confidence}"] += 1
            rows.append({
                "labelKey": runtime_field.get("labelKey"),
                "labelEn": runtime_field.get("labelEn"),
                "labelZh": runtime_field.get("labelZh"),
                "rankValues": runtime_vector,
                "modifier": runtime_field.get("modifier"),
                "confidence": confidence,
                "valueSources": runtime_field.get("valueSources"),
                "sourceEvidence": runtime_field.get("sourceEvidence"),
                "modifierEvidence": runtime_field.get("modifierEvidence"),
                "catalogFallback": runtime_field.get("catalogFallback"),
                "wikiMatch": runtime_field.get("wikiMatch"),
                "wikiDisagreement": runtime_field.get("wikiDisagreement"),
                "candidates": runtime_field.get("candidates"),
                "match": match,
            })

        catalog_only = [
            {
                "id": field.get("id"),
                "labelEn": field.get("labelEn") or field.get("label"),
                "labelZh": field.get("labelZh"),
                "rankValues": vector(field),
                "sourceKind": field.get("sourceKind"),
            }
            for index, field in enumerate(catalog_fields)
            if index not in used
        ]
        summary["catalogOnlyFields"] += len(catalog_only)
        summary["runtimeFieldRows"] += len(rows)
        summary["abilities"] += 1
        ability_diffs.append({
            "abilityId": ability_id,
            "nameEn": catalog_row.get("nameEn") or mapping.get("nameEn"),
            "scriptPath": mapping.get("scriptPath"),
            "queryFieldsStatus": mapping.get("queryStatus") or scripts.get(mapping.get("scriptPath"), {}).get("queryFieldsStatus"),
            "fields": rows,
            "catalogOnlyFields": catalog_only,
        })

    return {
        "schemaVersion": 1,
        "status": "ready",
        "buildLabel": runtime.get("buildLabel"),
        "inputs": {
            "catalogBuildLabel": catalog.get("buildLabel"),
            "runtimeDecoderRevision": runtime.get("decoderRevision"),
        },
        "summary": {**dict(sorted(summary.items())), "matchedCatalogFieldSources": dict(sorted(field_sources.items()))},
        "abilities": ability_diffs,
    }


def self_test() -> None:
    catalog = {"buildLabel": "test", "abilities": [{
        "id": "/A",
        "scalars": [{"id": "damage", "labelEn": "Damage", "rankValues": [1, 2, 3, 4], "scale": "strength", "sourceKind": "test"}],
    }]}
    runtime = {
        "buildLabel": "test",
        "decoderRevision": "x",
        "abilities": [{"abilityId": "/A", "scriptPath": "/A.lua"}],
        "scripts": [{"scriptPath": "/A.lua", "queryFieldsStatus": "decoded", "resolvedFields": [{
            "labelKey": "/DAMAGE", "labelEn": "Damage", "labelZh": "伤害", "rankValues": [1, 2, 3, 4],
            "modifier": "strength", "confidence": "cross-checked",
        }]}],
    }
    result = build_diff(catalog, runtime)
    assert result["summary"]["match.exact-label"] == 1
    assert result["summary"]["value.agree"] == 1
    assert result["summary"]["modifier.agree"] == 1
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare offline Warframe ability query fields with the frozen catalog")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "warframe_build_data.json")
    parser.add_argument("--runtime", type=Path, default=ROOT / "data" / "ability_runtime_fields.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    result = build_diff(load(args.catalog), load(args.runtime))
    if result["buildLabel"] != result["inputs"]["catalogBuildLabel"]:
        raise RuntimeError(f"build mismatch: {result['buildLabel']} != {result['inputs']['catalogBuildLabel']}")
    if not args.output:
        parser.error("--output is required")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **result["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
