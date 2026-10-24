"""2026-10-21: subsumed abilities use their Helminth numbers (wiki Helminth tab),
and a Helminth ability over the exalted slot removes the exalted weapon."""
import pytest

import app

FRAME = "/Lotus/Powersuits/Excalibur/Excalibur"
ROAR = "/Lotus/Powersuits/Rhino/Abilities/RhinoRoarAbility"


def _replaced(slot, ability, **extra):
    return app.WARFRAME_ENGINE.calculate({"frameId": FRAME, "helminthReplacement": {"slot": slot, "abilityId": ability}, **extra})


def _scalar(result, slot, scalar_id):
    return next(row for row in result["abilityScalars"][slot]["scalars"] if row["id"] == scalar_id)


def test_subsumed_roar_and_nourish_use_helminth_values():
    assert _scalar(_replaced(2, ROAR), 2, "damage_1")["value"] == pytest.approx(30.0)
    nourish = _replaced(2, "/Lotus/Powersuits/Devourer/Abilities/DevourerConsumeAbility")
    assert _scalar(nourish, 2, "viral_damage_buff_5")["value"] == pytest.approx(45.0)
    assert _scalar(nourish, 2, "self_heal_on_cast_2")["value"] == 0
    # Strength still scales the altered number.
    rhino_roar = app.WARFRAME_ENGINE.calculate({"frameId": "/Lotus/Powersuits/Rhino/Rhino"})
    assert _scalar(rhino_roar, 2, "damage_1")["value"] == pytest.approx(50.0)


def test_every_altered_entry_matches_a_helminth_scalar():
    import json
    table = json.loads((app.ROOT / "data/mechanics/helminth-altered.json").read_text(encoding="utf-8"))["abilities"]
    rows = {row["path"]: row for row in app.WARFRAME_CATALOG["helminth"]}
    for path, spec in table.items():
        assert path in rows, path
        ids = {row["id"] for row in rows[path].get("scalars") or ()}
        assert set(spec.get("scalars") or {}) <= ids, path


def test_helminth_over_the_exalted_slot_warns():
    result = app.warframe_calculate_payload({"frameId": FRAME, "helminthReplacement": {"slot": 3, "abilityId": ROAR}})
    energy = result["exalted"][0]["energy"]
    assert energy["kind"] == "replaced" and "无法使用这把显赫武器" in energy["warnings"][0]
