"""Automatic weapon-Arcane / Incarnon-route choice (build page, 2026-10-14)."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))

from wfarsenal import loadout_search as ls  # noqa: E402


@dataclass
class Ev:
    score: float
    cards: tuple


def _tier_number(value):
    try:
        return int(str(value).replace("tier", ""))
    except ValueError:
        return None


def test_route_choices_enumerates_selectable_tiers():
    weapon = {"incarnon": {"tiers": [
        {"tier": 1, "branches": [{"id": "1-1"}]},
        {"tier": 2, "selectable": True, "branches": [{"id": "2-1"}, {"id": "2-2"}]},
        {"tier": 3, "branches": [{"id": "3-1"}, {"id": "3-2"}, {"id": "3-3"}]},
    ]}}
    routes = ls.route_choices(weapon, _tier_number)
    assert len(routes) == 6
    assert routes[0] == {"tier2": "2-1", "tier3": "3-1"}
    assert ls.route_choices({}, _tier_number) == []


def test_pick_arcane_refines_the_two_best_screens():
    base = Ev(10.0, ("base",))
    choices = [ls.Choice(key=k, data={"path": k}, passives=k) for k in ("A", "B", "C")]
    screens = {"A": 12.0, "B": 11.0, "C": 9.0}
    searched = {"A": 13.0, "B": 15.0, "C": 30.0}
    calls = []

    def screen(cards, passives_list):
        # On a refined build every Arcane screens at what it already found.
        if cards != ("base",):
            return [min(searched[p], 15.0) if p != "C" else 9.0 for p in passives_list]
        return [screens[p] for p in passives_list]

    def search(passives, seed):
        calls.append((passives, seed))
        return Ev(searched[passives], (passives,))

    outcome = ls.pick_arcane(choices, base, screen=screen, search=search)
    assert outcome.choice.key == "B" and outcome.evaluation.score == 15.0
    # C screens below the base, so it is never searched however good it might be.
    assert [p for p, _ in calls] == ["A", "B"]
    assert all(seed == ("base",) for _, seed in calls)
    assert outcome.searches == 2


def test_pick_arcane_keeps_base_when_nothing_screens_better():
    base = Ev(10.0, ("base",))
    choices = [ls.Choice(key="A", data={}, passives="A")]
    outcome = ls.pick_arcane(choices, base, screen=lambda c, p: [9.0], search=lambda p, s: Ev(99.0, ()))
    assert outcome.choice is None and outcome.evaluation is base and outcome.searches == 0


def test_pick_route_finds_a_weapon_changing_branch_and_never_ends_below_default():
    # tier5 '5-1' changes the weapon: it screens badly on the default build
    # but wins once the MODs follow it.
    routes = [{"tier4": a, "tier5": b} for a in ("4-1", "4-2") for b in ("5-1", "5-2")]
    choices = [ls.Choice(key=f"{r['tier4']}/{r['tier5']}", data=r, passives=f"{r['tier4']}/{r['tier5']}")
               for r in routes]
    default = "4-1/5-2"
    true_best = {"4-1/5-1": 30.0, "4-2/5-1": 31.0, "4-1/5-2": 20.0, "4-2/5-2": 20.0}

    def screen(cards, passives_list):
        out = []
        for p in passives_list:
            if cards == ():
                out.append(1.0 if p.endswith("5-2") else 2.0)  # the bare weapon likes 5-1
            elif p.endswith("5-1"):
                out.append(5.0 if cards[0] not in ("4-1/5-1", "4-2/5-1") else true_best[p])
            else:
                out.append(19.0 if p.startswith("4-1") else 19.0)  # 4-x/5-2 equivalent
        return out

    seeds = []

    def scout(passives, seed):
        return Ev(true_best[passives] * 0.9, (passives,))

    def final(passives, seed):
        seeds.append((passives, seed))
        return Ev(true_best[passives], (passives,))

    base = Ev(18.0, (default,))
    outcome = ls.pick_route(choices, default, base, screen=screen, search_fast=scout, search_final=final)
    assert outcome.choice.key == "4-2/5-1" and outcome.evaluation.score == 31.0
    # The default route's final search is the unseeded search the option replaces.
    assert (default, None) in seeds
    assert outcome.evaluation.score >= true_best[default]


def test_pick_route_searches_equivalent_routes_once():
    routes = [{"tier2": a} for a in ("2-1", "2-2", "2-3")]
    choices = [ls.Choice(key=r["tier2"], data=r, passives=r["tier2"]) for r in routes]
    scouted = []

    def screen(cards, passives_list):
        return [10.0 if p != "2-3" else 12.0 for p in passives_list]  # 2-1 == 2-2

    def scout(passives, seed):
        scouted.append(passives)
        return Ev(12.5 if passives == "2-3" else 10.0, (passives,))

    def final(passives, seed):
        return Ev(13.0 if passives == "2-3" else 10.0, (passives,))

    outcome = ls.pick_route(choices, "2-1", Ev(10.0, ("2-1",)), screen=screen, search_fast=scout, search_final=final)
    assert scouted == ["2-3"]  # 2-2 is equivalent to the default 2-1
    assert outcome.choice.key == "2-3" and outcome.evaluation.score == 13.0


def test_pick_route_fixed_is_an_exact_screen():
    choices = [ls.Choice(key=k, data={"tier2": k}, passives=k) for k in ("2-1", "2-2")]
    best, rows = ls.pick_route_fixed(choices, "2-1", ("x",), 10.0,
                                     screen=lambda c, p: [10.0, 11.0])
    assert best.key == "2-2" and rows[0]["key"] == "2-2"
    best, _ = ls.pick_route_fixed(choices, "2-1", ("x",), 10.0, screen=lambda c, p: [10.0, 9.0])
    assert best.key == "2-1"


# ── build page integration ────────────────────────────────────────────────

def _build(name, **extra):
    import app

    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == name)
    return app.build_weapon_payload(dict(weapon=weapon["path"], mode="auto", profile="fast", **extra))


def test_auto_options_are_off_by_default():
    result = _build("Lex Prime")
    assert result["autoLoadout"] is None
    assert not any("optimizer-auto-" in note for note in result["skipped"])


def test_auto_incarnon_never_ends_below_the_chosen_route():
    plain = _build("Lex Prime")
    auto = _build("Lex Prime", autoIncarnon=True)
    info = auto["autoLoadout"]["incarnon"]
    assert info["routes"] == 18 and info["searches"] >= 1
    assert auto["build"]["objectiveScore"] >= plain["build"]["objectiveScore"] - 1e-9
    assert set(auto["incarnonChoices"]) == {"tier2", "tier3", "tier4"}
    assert any(note.startswith("optimizer-auto-incarnon: 自动选择灵化路线") for note in auto["skipped"])


def test_auto_arcane_fills_the_weapon_slot_and_keeps_frame_arcanes():
    import app

    frame = next(row for row in app.MANUAL_ARCANES if row.get("nameEn") == "Arcane Avenger")
    auto = _build("Lex Prime", autoArcane=True, arcanes=[{"path": frame["path"], "rank": frame["maxRank"]}])
    info = auto["autoLoadout"]["arcane"]
    assert info["slots"][0]["candidates"] >= 10
    assert info["score"] >= info["baseScore"]
    chosen = info["chosen"]
    assert len(chosen) == 1 and app.MANUAL_ARCANES_BY_PATH[chosen[0]["path"]]["slotKind"] == "weapon"
    assert chosen[0]["rank"] == app.MANUAL_ARCANES_BY_PATH[chosen[0]["path"]]["maxRank"]
    # The frame Arcane stayed part of the solve.
    assert auto["build"]["objectiveScore"] == info["score"]
