"""Arcane slots (2026-10-12).

- Official text reads as lines: no literal "\\n", colour tags or doubled
  revive lines.
- Frame Arcanes are offered only where a weapon effect lands (Fury: melee,
  Precision: secondaries, Arachne: guns); one kept from another weapon is
  ignored with a note instead of failing the request.
- "强制触发" on a trigger the replay cannot simulate (taking damage, wall
  latch, ability heat procs) now reaches the replay; it used to be dropped.
- Runtime-script cards are rebuilt from verified script parameters
  (arcane_runtime): Bulwark / Overcharge / Retaliation follow the combat
  state, Shiver reads live Cold stacks, forcing takes the maximum.
"""
import pytest

import app
from wfarsenal import arcane_runtime, optimizer

WEAPONS = {w.get("nameEn"): w for w in app.EXPORTS["weapons"]}
ROWS = {row["nameEn"]: row for row in app.MANUAL_ARCANES}
RECORDS = {row["nameEn"]: row for row in app.EXPORTS["arcanes"] if row.get("equipmentType")}


def _run(weapon, arcanes=(), state=None):
    payload = dict(weapon=WEAPONS[weapon]["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170,
                   steelPath=True, arcanes=list(arcanes))
    if state:
        payload["combatState"] = state
    return app.simulate_manual_payload(payload)


def _arcane(name, **state):
    return {"path": ROWS[name]["path"], "rank": ROWS[name]["maxRank"], **state}


def _window(result):
    return result["benchmarkTimeline"]["windowDps"]


def test_descriptions_are_clean_lines():
    for row in app.MANUAL_ARCANES:
        text = row["description"] + "".join(line for level in row["effectsZhByRank"] for line in level)
        assert "\\n" not in text and "<DT_" not in text, row["nameEn"]
        assert row["nameZh"] == row["nameZh"].strip()
        for level in row["effectsZhByRank"]:
            assert len(level) == len(set(level)), row["nameEn"]
    assert ROWS["Arcane Avenger"]["description"].split("\n")[0] == "受到伤害时："


@pytest.mark.parametrize("weapon, allowed, refused", [
    ("Lex Prime", {"Arcane Precision", "Arcane Awakening", "Arcane Velocity", "Arcane Avenger", "Arcane Arachne"},
     {"Arcane Fury", "Arcane Blade Charger", "Arcane Primary Charger", "Arcane Rise", "Arcane Strike", "Arcane Tempo"}),
    ("Nikana Prime", {"Arcane Fury", "Arcane Strike", "Arcane Blade Charger", "Arcane Avenger"},
     {"Arcane Arachne", "Arcane Precision", "Arcane Rage"}),
    ("Hek", {"Arcane Tempo", "Arcane Rage", "Arcane Primary Charger", "Arcane Arachne"},
     {"Arcane Acceleration", "Arcane Momentum", "Arcane Velocity", "Arcane Fury"}),
])
def test_frame_arcanes_follow_the_weapon(weapon, allowed, refused):
    record = optimizer.resolve_record(app.EXPORTS["weapons"], WEAPONS[weapon]["path"], kind="weapon")
    for name in allowed:
        assert optimizer._arcane_matches_weapon(RECORDS[name], record), name
    for name in refused:
        assert not optimizer._arcane_matches_weapon(RECORDS[name], record), name


def test_frame_arcane_from_another_weapon_is_ignored_with_a_note():
    result = _run("Lex Prime", [_arcane("Arcane Fury")])
    assert any(note.startswith("arcane-not-for-this-weapon:") for note in result["unsupported"])
    assert _window(result) == pytest.approx(_window(_run("Lex Prime")))


@pytest.mark.parametrize("name, stacks", [("Arcane Avenger", 1), ("Arcane Hot Shot", 50), ("Arcane Arachne", 1)])
def test_forcing_an_unsimulated_trigger_reaches_the_replay(name, stacks):
    plain = _window(_run("Lex Prime"))
    assert _window(_run("Lex Prime", [_arcane(name)])) == pytest.approx(plain)
    assert _window(_run("Lex Prime", [_arcane(name, stacks=stacks, uptime=1)])) > plain * 1.3


def test_cross_weapon_kill_trigger_is_inactive_by_default():
    plain = _run("Rubico Prime")["moddedStats"]["damage_types"]
    charged = _run("Rubico Prime", [_arcane("Arcane Primary Charger")])["moddedStats"]["damage_types"]
    assert sum(charged.values()) == pytest.approx(sum(plain.values()))


def test_runtime_cards_follow_combat_state_or_force():
    total = lambda result: sum(result["moddedStats"]["damage_types"].values())  # noqa: E731
    plain = total(_run("Rubico Prime"))
    # 1300 armour: 300 points over 1000 at +1% each.
    assert total(_run("Rubico Prime", [_arcane("Primary Bulwark")], {"frameArmor": 1300})) == pytest.approx(plain * 4.0)
    assert total(_run("Rubico Prime", [_arcane("Primary Bulwark", stacks=500, uptime=1)])) == pytest.approx(plain * 6.0)
    multishot = _run("Rubico Prime")["moddedStats"]["multishot"]
    charged = _run("Rubico Prime", [_arcane("Primary Overcharge")], {"energyPool": 500})["moddedStats"]["multishot"]
    assert charged == pytest.approx(multishot * (1 + 500 * 0.0035))
    assert ROWS["Primary Bulwark"]["stateControls"]["stacks"] is None  # follows the input, no stack stepper


def test_shiver_reads_live_cold_stacks_and_forces_ten():
    plain = _run("Lex Prime")
    forced = _run("Lex Prime", [_arcane("Secondary Shiver", stacks=10, uptime=1)])
    ratio = sum(forced["moddedStats"]["damage_types"].values()) / sum(plain["moddedStats"]["damage_types"].values())
    assert ratio == pytest.approx(1 + 10 * 0.45)
    live = _run("Lex Prime", [_arcane("Secondary Shiver")])["moddedStats"]
    assert live["cold_stack_damage"] == pytest.approx(0.45)


def test_adapters_refuse_changed_scripts():
    record = RECORDS["Primary Bulwark"]
    assert arcane_runtime.configuration(record, 5)
    changed = {**record, "runtimeScripts": {"apply": {**record["runtimeScripts"]["apply"], "_maxStacks": 600}}}
    assert arcane_runtime.configuration(changed, 5) is None


def test_event_cards_offer_no_force_and_unmodelled_say_why():
    assert ROWS["Secondary Encumber"]["stateControls"]["force"] is False
    assert ROWS["Secondary Enervate"]["stateControls"]["force"] is False
    assert "溅射" in ROWS["Secondary Irradiate"]["stateControls"]["note"]
    assert ROWS["Arcane Avenger"]["stateControls"]["model"] == "manual"


def test_crepuscular_counts_once():
    buff = [{"id": "arcane-crepuscular"}]
    crit = lambda **kw: app.simulate_manual_payload(dict(  # noqa: E731
        weapon=WEAPONS["Lex Prime"]["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
        **kw))["moddedStats"]["crit_multiplier"]
    plain = crit()
    both = crit(arcanes=[_arcane("Arcane Crepuscular", stacks=1, uptime=1)], externalBuffs=buff)
    assert both == pytest.approx(plain + 3.0)
    assert crit(externalBuffs=buff) == pytest.approx(both)


def test_new_cards_are_listed():
    for name in ("Arcane Crepuscular", "Theorem Demulcent", "Arcane Pistoleer", "Akimbo Slip Shot",
                 "Exodia Triumph", "Exodia Valor", "Melee Retaliation", "Secondary Shiver"):
        assert name in ROWS, name
