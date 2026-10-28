"""Identity and evidence-boundary regression checks for secondary payload audit."""
from copy import deepcopy
import json

import pytest

from tools.audit_secondary_payload_coverage import SECONDARY_RUNTIME_FLAGS, audit, main


def sample(*, path="/weapon", source=None, types=None, probe_flag=None):
    probe = {flag: flag == probe_flag for flag in SECONDARY_RUNTIME_FLAGS}
    mode = dict(mode=0, nativeMode=5, status="evaluable", gaps=[],
                declaredDamageComponents=[dict(source="ExplosiveAttack", amount=73, types=types or {})],
                runtime=[probe])
    coverage = dict(rows=[dict(path=path, name="Shared label", slot="primary", modes=[mode])])
    exports = [dict(path=path, nameEn="Shared label", fireModes=[dict(index=5, damage=dict(source=source, total=15))])]
    return coverage, exports


@pytest.mark.parametrize("source", ["ExplosiveAttack", "EmbedDeathAttack", "RadialDamage", "StackingAttack"])
def test_main_damage_already_secondary_is_excluded_without_adding_other_branches(source):
    coverage, exports = sample(source=source)
    result = audit(coverage, exports)
    assert not result["candidates"]
    assert len(result["mainPayloadAlreadySecondary"]) == 1


def test_positive_amount_with_empty_types_is_candidate_not_proven_bug():
    coverage, exports = sample()
    result = audit(coverage, exports)
    row = result["candidates"][0]
    assert row["positiveComponents"][0]["types"] == {}
    assert "not a proven gameplay bug" in row["interpretation"]
    assert result["summary"]["candidateModes"] == 1


@pytest.mark.parametrize("flag", SECONDARY_RUNTIME_FLAGS)
def test_secondary_runtime_presence_is_only_presence_not_calibration(flag):
    coverage, exports = sample(probe_flag=flag)
    result = audit(coverage, exports)
    assert not result["candidates"]
    assert len(result["secondaryRuntimePresent"]) == 1
    assert "presence-only" in result["secondaryRuntimePresent"][0]["interpretation"]
    assert not any(key in result["summary"] for key in ("covered", "calibrated", "coveredModes"))


def test_same_name_different_paths_and_native_indices_do_not_merge():
    first, first_exports = sample(path="/ordinary-grakata")
    second, second_exports = sample(path="/nox-player")
    first["rows"].extend(second["rows"])
    result = audit(first, first_exports + second_exports)
    assert {(row["path"], row["mode"]) for row in result["candidates"]} == {
        ("/ordinary-grakata", 0), ("/nox-player", 0),
    }
    assert all(row["nativeMode"] == 5 for row in result["candidates"])
    assert result["summary"]["candidateWeaponRecords"] == 2


@pytest.mark.parametrize("location", ["error", "prepareError", "preparedError", "runtime-error"])
def test_preparation_error_is_separate_even_when_runtime_presence_exists(location):
    coverage, exports = sample(probe_flag="hasRadial")
    mode = coverage["rows"][0]["modes"][0]
    if location == "runtime-error":
        mode["runtime"][0]["error"] = "preparation failed"
    else:
        mode[location] = "preparation failed"
    result = audit(coverage, exports)
    assert len(result["preparationErrors"]) == 1
    assert not result["candidates"] and not result["secondaryRuntimePresent"]


@pytest.mark.parametrize("target", ["coverage-path", "coverage-mode", "exports-path"])
def test_duplicate_identities_are_rejected(target):
    coverage, exports = sample()
    if target == "coverage-path":
        coverage["rows"].append(deepcopy(coverage["rows"][0]))
    elif target == "coverage-mode":
        coverage["rows"][0]["modes"].append(deepcopy(coverage["rows"][0]["modes"][0]))
    else:
        exports.append(deepcopy(exports[0]))
    with pytest.raises(ValueError, match="duplicate"):
        audit(coverage, exports)


def test_missing_or_partial_runtime_cannot_be_reported_as_absence():
    coverage, exports = sample()
    coverage["rows"][0]["modes"][0]["runtime"] = [{"hasRadial": False}]
    result = audit(coverage, exports)
    assert len(result["runtimeUnobserved"]) == 1 and not result["candidates"]


def test_missing_exact_path_join_is_separate_without_name_fallback():
    coverage, exports = sample(path="/nox-player")
    exports[0]["path"] = "/ordinary-grakata"
    result = audit(coverage, exports)
    assert len(result["missingExportJoins"]) == 1 and not result["candidates"]


@pytest.mark.parametrize("wrapper", ["array", "data", "weapons"])
def test_frozen_and_runtime_export_wrappers(wrapper):
    coverage, exports = sample()
    payload = exports if wrapper == "array" else {wrapper: exports}
    assert audit(coverage, payload)["summary"]["candidateModes"] == 1


@pytest.mark.parametrize("amount", [0, -1, None, True])
def test_only_finite_positive_numeric_declarations_are_candidates(amount):
    coverage, exports = sample()
    coverage["rows"][0]["modes"][0]["declaredDamageComponents"][0]["amount"] = amount
    result = audit(coverage, exports)
    assert not result["candidates"]
    assert result["summary"]["noPositiveSecondaryDeclarationModes"] == 1


def test_cli_writes_provenance_and_refuses_to_overwrite(tmp_path, capsys):
    coverage, exports = sample()
    coverage_path, exports_path, output = (tmp_path/name for name in ("coverage.json", "exports.json", "result.json"))
    coverage_path.write_text(json.dumps(coverage), encoding="utf8")
    exports_path.write_text(json.dumps({"weapons": exports}), encoding="utf8")
    args = ["--coverage", str(coverage_path), "--exports", str(exports_path), "--output", str(output)]
    assert main(args) == 0
    result = json.loads(output.read_text(encoding="utf8"))
    assert len(result["inputs"]["exports"]["sha256"]) == 64
    before = output.read_bytes()
    with pytest.raises(SystemExit):
        main(args)
    assert output.read_bytes() == before
