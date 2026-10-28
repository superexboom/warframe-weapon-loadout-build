"""Hand-calculated bounded Cortege field examples, independent of the scorer."""
import json
import math

import pytest

from tools.cortege_field_reference import main, reference


@pytest.mark.parametrize("multiplier, expected", [
    (1.0, 2000), (2.0, 4000), (3.0, 6000), (.95, 1900),
    (.99995, 1999), (1.00045, 2000), (.00095, 1), (0.0, 0),
])
def test_hand_calculated_single_contact(multiplier, expected):
    result = reference(base_damage_multiplier=multiplier)
    assert result["field_snapshot_int32"] == expected
    assert result["predefense_heat_amount"] == expected
    assert result["hit_contacts"] == 1
    assert result["supported"] is True


def test_float32_rounding_precedes_truncation():
    # 1999.99998 rounds to binary32 2000 before truncation. Truncating the
    # Python double first would incorrectly yield 1999.
    assert math.trunc(2000 * .99999999) == 1999
    result = reference(base_damage_multiplier=.99999999)
    assert result["query_base_amount_float32"] == 2000.0
    assert result["field_snapshot_int32"] == 2000


def test_scalar_is_applied_after_snapshot_and_contacts_are_explicit():
    # 2000 * 1.00045 -> float32 2000.900024 -> int32 2000.
    # Then known scalar 1.5 and four declared contacts: 2000 * 1.5 * 4.
    result = reference(base_damage_multiplier=1.00045, target_scalar=1.5, hit_contacts=4)
    assert result["field_snapshot_int32"] == 2000
    assert result["predefense_heat_per_contact"] == 3000
    assert result["predefense_heat_amount"] == 12000
    assert reference(base_damage_multiplier=1, hit_contacts=0)["predefense_heat_amount"] == 0


@pytest.mark.parametrize("extra", [
    {"elemental_multiplier": 1.9}, {"critical_chance": .3},
    {"critical_multiplier": 2.4}, {"status_chance": .5},
])
def test_weapon_stats_are_rejected(extra):
    with pytest.raises(TypeError):
        reference(base_damage_multiplier=1, **extra)


@pytest.mark.parametrize("kwargs", [
    {"base_damage_multiplier": -1}, {"base_damage_multiplier": float("nan")},
    {"base_damage_multiplier": float("inf")}, {"base_damage_multiplier": True},
    {"base_damage_multiplier": "1"}, {"base_damage_multiplier": 2 ** 31 / 2000},
    {"base_damage_multiplier": 1e308},
    {"base_damage_multiplier": 1, "hit_contacts": -1},
    {"base_damage_multiplier": 1, "hit_contacts": 1.5},
    {"base_damage_multiplier": 1, "hit_contacts": True},
    {"base_damage_multiplier": 1, "target_scalar": -1},
    {"base_damage_multiplier": 1, "target_scalar": float("inf")},
])
def test_invalid_or_unsupported_numbers_are_rejected(kwargs):
    with pytest.raises(ValueError):
        reference(**kwargs)


def test_cli_is_json_and_declares_provenance_and_limits(capsys):
    assert main(["--base-damage-multiplier", "2", "--hit-contacts", "3"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["predefense_heat_amount"] == 12000
    assert result["source_build"] == "2026.10.22.13.12"
    assert result["source_hashes"]["Warframe.x64.exe"] == "eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d"
    assert all(len(value) == 64 for value in result["source_hashes"].values())
    assert any("not an enabled production" in limit for limit in result["limits"])
    assert any("Status DoT" in limit for limit in result["limits"])
    assert "status_damage" not in result


def test_cli_rejects_weapon_crit_argument(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--base-damage-multiplier", "1", "--critical-chance", ".3"])
    assert exc.value.code == 2
    assert "unrecognized arguments" in capsys.readouterr().err
