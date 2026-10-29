"""Find positive secondary declarations absent from bounded runtime probes.

This is a structural candidate audit, not gameplay calibration. Join identities
are weapon path and exported mode position; displayed names never identify rows.
The CLI reads JSON only and refuses to overwrite an existing output.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

SECONDARY_RUNTIME_FLAGS = (
    "hasRadial", "hasLingering", "hasEmbedded", "hasStackable", "hasSequence",
    "hasPhysicalProjectileLanes", "hasSourceOwnedFields",
)
SECONDARY_MAIN_SOURCES = frozenset((
    "ExplosiveAttack", "EmbedDeathAttack", "RadialDamage", "StackingAttack",
))


def _rows(payload: Any, keys: tuple[str, ...], label: str) -> list[dict]:
    if isinstance(payload, dict):
        candidates = [payload[key] for key in keys if key in payload]
        if len(candidates) != 1:
            raise ValueError(f"{label}: expected exactly one of {keys}")
        payload = candidates[0]
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise ValueError(f"{label}: expected an array of objects")
    return payload


def _index(rows: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for row in rows:
        path = row.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(f"{label}: missing weapon path")
        if path in result:
            raise ValueError(f"{label}: duplicate weapon path {path}")
        result[path] = row
    return result


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def audit(coverage: Any, exports: Any) -> dict:
    """Inspect frozen probes; never import the application or run simulation."""
    coverage_rows = _rows(coverage, ("rows",), "coverage")
    export_rows = _rows(exports, ("weapons", "data"), "exports")
    _index(coverage_rows, "coverage")
    export_index = _index(export_rows, "exports")
    for path, row in export_index.items():
        modes = row.get("fireModes", [])
        if not isinstance(modes, list) or any(not isinstance(mode, dict) for mode in modes):
            raise ValueError(f"exports: {path} fireModes must be an array of objects")
    result = {key: [] for key in (
        "candidates", "secondaryRuntimePresent", "mainPayloadAlreadySecondary",
        "preparationErrors", "missingExportJoins", "runtimeUnobserved",
        "noPositiveSecondaryDeclarations", "nonEvaluableModes",
    )}
    mode_count = positive_count = 0
    for weapon in coverage_rows:
        path = weapon["path"]
        modes = weapon.get("modes", [])
        if not isinstance(modes, list):
            raise ValueError(f"coverage: {path} modes must be an array")
        seen = set()
        for mode in modes:
            if not isinstance(mode, dict):
                raise ValueError(f"coverage: {path} mode must be an object")
            position = mode.get("mode")
            if not isinstance(position, int) or isinstance(position, bool) or position < 0:
                raise ValueError(f"coverage: {path} requires non-negative integer mode identity")
            if position in seen:
                raise ValueError(f"coverage: duplicate path/mode {path}:{position}")
            seen.add(position)
            mode_count += 1
            row = dict(path=path, mode=position, name=weapon.get("name"),
                       slot=weapon.get("slot"), nativeMode=mode.get("nativeMode"),
                       baselineGaps=deepcopy(mode.get("gaps") or []))
            runtime = mode.get("runtime")
            if runtime is not None and (not isinstance(runtime, list) or any(not isinstance(probe, dict) for probe in runtime)):
                raise ValueError(f"coverage: {path}:{position} runtime must be an array of probe objects")
            errors = [mode[key] for key in ("error", "prepareError", "preparedError", "preparationError") if mode.get(key)]
            errors.extend(probe[key] for probe in (runtime or []) for key in ("error", "prepareError", "preparedError", "preparationError") if probe.get(key))
            if errors or mode.get("status") in {"prepare-error", "preparation-error"}:
                row["errors"] = deepcopy(errors)
                row["runtime"] = deepcopy(runtime or [])
                result["preparationErrors"].append(row)
                continue
            if mode.get("status") != "evaluable":
                row["status"] = mode.get("status")
                result["nonEvaluableModes"].append(row)
                continue
            declared = mode.get("declaredDamageComponents") or []
            if not isinstance(declared, list) or any(not isinstance(part, dict) for part in declared):
                raise ValueError(f"coverage: {path}:{position} invalid declaredDamageComponents")
            positive = [deepcopy(part) for part in declared if _positive(part.get("amount"))]
            if not positive:
                result["noPositiveSecondaryDeclarations"].append(row)
                continue
            positive_count += 1
            row["positiveComponents"] = positive  # Empty types remains evidence.
            exported = export_index.get(path)
            export_modes = (exported or {}).get("fireModes") or []
            if exported is None or position >= len(export_modes):
                result["missingExportJoins"].append(row)
                continue
            damage = export_modes[position].get("damage") or {}
            if not isinstance(damage, dict):
                raise ValueError(f"exports: {path}:{position} damage must be an object")
            row["mainDamage"] = {key: deepcopy(damage.get(key)) for key in ("source", "total", "types")}
            row["selectedProjectile"] = damage.get("projectile")
            row["componentKinds"] = deepcopy(mode.get("componentKinds") or [])
            row["runtime"] = deepcopy(runtime or [])
            row["clusterBoundary"] = "Child multiplicity, inheritance and alternate destruction paths are not inferred from parent components."
            if any(any(probe.get(key) for key in SECONDARY_RUNTIME_FLAGS) for probe in (runtime or [])):
                row["interpretation"] = "secondary-runtime-presence-only; correctness and completeness unverified"
                result["secondaryRuntimePresent"].append(row)
            elif damage.get("source") in SECONDARY_MAIN_SOURCES:
                row["interpretation"] = "main payload already selects a secondary source; other declarations may be alternative branches, not additive hits"
                result["mainPayloadAlreadySecondary"].append(row)
            elif not runtime or any(not all(key in probe for key in SECONDARY_RUNTIME_FLAGS) for probe in runtime):
                row["interpretation"] = "missing bounded probe evidence; cannot infer absent secondary runtime"
                result["runtimeUnobserved"].append(row)
            else:
                row["interpretation"] = "structural candidate, not a proven gameplay bug; activation, defaults, timing and consumers need audit"
                result["candidates"].append(row)
    result["schemaVersion"] = 1
    result["scope"] = "positive-secondary-declarations-versus-runtime-presence"
    result["summary"] = dict(
        weaponRecords=len(coverage_rows), explicitModes=mode_count,
        positiveSecondaryDeclarationModes=positive_count,
        candidateModes=len(result["candidates"]),
        candidateWeaponRecords=len({row["path"] for row in result["candidates"]}),
        candidateModesWithoutBaselineWarning=sum(not row["baselineGaps"] for row in result["candidates"]),
        secondaryRuntimePresentModes=len(result["secondaryRuntimePresent"]),
        mainPayloadAlreadySecondaryModes=len(result["mainPayloadAlreadySecondary"]),
        preparationErrorModes=len(result["preparationErrors"]),
        missingExportJoins=len(result["missingExportJoins"]),
        runtimeUnobservedModes=len(result["runtimeUnobserved"]),
        noPositiveSecondaryDeclarationModes=len(result["noPositiveSecondaryDeclarations"]),
        nonEvaluableModes=len(result["nonEvaluableModes"]),
    )
    result["limitations"] = [
        "A positive inherited payload may be inactive or an alternate destruction path.",
        "Secondary runtime presence does not establish gameplay correctness or complete coverage.",
        "Names are labels only; identity is exact path and exported mode position, not native mode index.",
        "Modes with preparation errors or absent probes are not treated as absent secondary runtime.",
    ]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--exports", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("output already exists; preserve evidence and choose a new file")
    try:
        result = audit(json.loads(args.coverage.read_text(encoding="utf-8-sig")),
                       json.loads(args.exports.read_text(encoding="utf-8-sig")))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    result["inputs"] = {key: dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                        for key, path in (("coverage", args.coverage), ("exports", args.exports))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
