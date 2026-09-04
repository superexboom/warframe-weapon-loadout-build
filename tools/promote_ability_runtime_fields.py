from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from diff_ability_runtime_fields import build_diff, load


ROOT = Path(__file__).resolve().parents[1]


def _ability_rows(catalog: dict[str, Any], ability_id: str) -> list[dict[str, Any]]:
    return [
        row for row in catalog.get("abilities") or ()
        if isinstance(row, dict) and str(row.get("id") or row.get("path") or "") == ability_id
    ]


def _source_kind(field: dict[str, Any]) -> str:
    values = field.get("valueSources") or ()
    if "wiki-snapshot" in values:
        return "wiki-snapshot"
    if "catalog-energy-cost" in values:
        return "packages-derived"
    if any(value in values for value in ("query-interpreter", "static-dataflow", "query-capture")):
        return "game-font-luau"
    return "unknown"


def promote(
    catalog: dict[str, Any],
    runtime: dict[str, Any],
    *,
    sidecar_sha256: str | None = None,
) -> tuple[dict[str, Any], dict[str, int]]:
    if catalog.get("buildLabel") != runtime.get("buildLabel"):
        raise ValueError(f"build mismatch: {catalog.get('buildLabel')} != {runtime.get('buildLabel')}")
    diff = build_diff(catalog, runtime)
    runtime_by_id = {str(row.get("abilityId") or ""): row for row in runtime.get("abilities") or ()}
    promoted = 0
    disagreements = 0
    skipped = 0
    for ability_diff in diff.get("abilities") or ():
        ability_id = str(ability_diff.get("abilityId") or "")
        runtime_row = runtime_by_id.get(ability_id) or {}
        runtime_fields = runtime_row.get("resolvedFields") or []
        catalog_rows = _ability_rows(catalog, ability_id)
        if not catalog_rows:
            skipped += len(ability_diff.get("fields") or [])
            continue
        for index, field_diff in enumerate(ability_diff.get("fields") or ()):
            if index >= len(runtime_fields):
                skipped += 1
                continue
            runtime_field = runtime_fields[index]
            values = runtime_field.get("rankValues")
            confidence = str(runtime_field.get("confidence") or "unresolved")
            match = field_diff.get("match") or {}
            catalog_id = match.get("catalogFieldId")
            if (
                not catalog_id
                or confidence not in {"cross-checked", "single-source"}
                or not isinstance(values, list)
                or not values
                or not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values)
                or runtime_field.get("catalogFallback")
            ):
                skipped += 1
                continue
            changed_any = False
            for catalog_row in catalog_rows:
                for scalar in catalog_row.get("scalars") or ():
                    if not isinstance(scalar, dict) or scalar.get("id") != catalog_id:
                        continue
                    old_values = scalar.get("rankValues")
                    if isinstance(old_values, list) and old_values != values:
                        scalar["catalogRankValues"] = copy.deepcopy(old_values)
                        scalar["catalogSourceKind"] = scalar.get("sourceKind")
                        scalar["catalogDisagreement"] = "runtime-value-replaces-frozen-catalog-vector"
                        disagreements += 1
                    scalar["rankValues"] = copy.deepcopy(values)
                    scalar["rankCount"] = len(values)
                    scalar["base"] = values[-1]
                    scalar["runtimeValueSource"] = _source_kind(runtime_field)
                    scalar["runtimeConfidence"] = confidence
                    scalar["runtimeValueSources"] = copy.deepcopy(runtime_field.get("valueSources") or [])
                    if runtime_field.get("sourceEvidence"):
                        scalar["runtimeSourceEvidence"] = copy.deepcopy(runtime_field["sourceEvidence"])
                    changed_any = True
            if changed_any:
                promoted += 1
            else:
                skipped += 1
    result = copy.deepcopy(catalog)
    provenance = result.setdefault("provenance", {})
    provenance["abilityRuntimePromotion"] = {
        "sidecarBuild": runtime.get("buildLabel"),
        "sidecarSha256": sidecar_sha256,
        "decoderRevision": runtime.get("decoderRevision"),
        "promotionParserSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "promotedFields": promoted,
        "catalogDisagreements": disagreements,
        "unresolvedFields": runtime.get("summary", {}).get("resolvedConfidence", {}).get("unresolved", 0),
        "policy": "verified runtime/Wiki values replace only uniquely matched catalog vectors; unresolved fields stay fail-closed",
    }
    result["abilityRuntimePromotion"] = provenance["abilityRuntimePromotion"]
    return result, {
        "promotedFields": promoted,
        "catalogDisagreements": disagreements,
        "skippedFields": skipped,
        "runtimeNumericFields": sum(bool(field.get("rankValues")) for row in runtime.get("abilities") or () for field in row.get("resolvedFields") or ()),
    }


def self_test() -> None:
    catalog = {
        "buildLabel": "test",
        "abilities": [{"id": "/A", "scalars": [{"id": "damage_0", "labelEn": "Damage", "rankValues": [1, 1, 1, 1], "sourceKind": "overframe-abilitystats"}]}],
    }
    runtime = {
        "buildLabel": "test",
        "decoderRevision": "rev",
        "summary": {"resolvedConfidence": {"unresolved": 0}},
        "abilities": [{"abilityId": "/A", "resolvedFields": [{"labelEn": "Damage", "rankValues": [2, 3, 4, 5], "confidence": "cross-checked", "valueSources": ["query-interpreter"]}]}],
        "scripts": [],
    }
    result, counts = promote(catalog, runtime)
    scalar = result["abilities"][0]["scalars"][0]
    assert scalar["rankValues"] == [2, 3, 4, 5]
    assert scalar["runtimeValueSource"] == "game-font-luau"
    assert counts["promotedFields"] == 1
    print("self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote verified offline ability vectors into the frozen Warframe catalog")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "warframe_build_data.json")
    parser.add_argument("--runtime", type=Path, default=ROOT / "data" / "ability_runtime_fields.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.output:
        parser.error("--output is required")
    result, counts = promote(
        load(args.catalog),
        load(args.runtime),
        sidecar_sha256=hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), **counts}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
