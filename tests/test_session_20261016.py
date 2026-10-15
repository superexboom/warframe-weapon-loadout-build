"""2026-10-16: wiki weapon priority, WFSim-measured model fixes, combat-judged fatal negatives."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app
from tests.test_combat_replay import run, stats, target
from wfarsenal import native_replay
from wfarsenal.combat_replay import SHIELD_GATE_LEAK
from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario, expected_dot_damage, faction_bracket
from wfarsenal.manual_combat import prepare


def _weapon(name):
    return next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)


# ── wiki over export ──────────────────────────────────────────────────────

@pytest.mark.parametrize("name,multishot,per_beam", [("Phantasma", 6, .222), ("Phantasma Prime", 6, .222), ("Phage", 7, .155)])
def test_wiki_beam_count_wins_over_packages_fire_iterations(name, multishot, per_beam):
    mode = _weapon(name)["fireModes"][0]
    assert mode["multishot"] == multishot
    # The per-beam status chance is kept; the export's per-shot convention scales with the beams.
    assert mode["damage"]["procChance"] == pytest.approx(per_beam * multishot, abs=1e-6)
    assert "multishot" in mode["wikiOverride"]


def test_wiki_alternox_projectile_is_electricity():
    damage = _weapon("Alternox")["fireModes"][0]["damage"]
    assert damage["types"] == {"DT_ELECTRICITY": 62.0}
    assert damage["total"] == 62.0 and damage["shares"] == {"DT_ELECTRICITY": 1.0}
    assert damage["procChance"] == pytest.approx(.3)


@pytest.mark.parametrize("name", ["Attica", "Hikou", "Paris"])
def test_projectile_without_own_proc_chance_uses_the_weapons(name):
    assert _weapon(name)["fireModes"][0]["damage"]["procChance"] > 0


def test_wiki_overrides_apply_in_the_exports_conventions(monkeypatch, tmp_path):
    overrides = tmp_path / "wiki_weapon_overrides.json"
    overrides.write_text('{"weapons": {"/w": {"modes": {"1": {"multishot": 3, "procChance": 0.6, '
                         '"damageTypes": {"DT_ELECTRICITY": 30, "DT_IMPACT": 10}}}}}}', encoding="utf-8")
    monkeypatch.setattr(app, "WIKI_WEAPON_OVERRIDES_PATH", overrides)
    exports = {"weapons": [{"path": "/w", "fireModes": [{"damage": {"total": 5}}, {"multishot": 2, "damage": {"total": 26}}]},
                           {"path": "/other", "fireModes": [{"damage": {"total": 7}}]}]}
    app._apply_wiki_weapon_overrides(exports)
    untouched, mode = exports["weapons"][0]["fireModes"]
    assert untouched == {"damage": {"total": 5}} and exports["weapons"][1]["fireModes"] == [{"damage": {"total": 7}}]
    assert mode["multishot"] == 3 and mode["damage"]["procChance"] == .6
    assert mode["damage"]["total"] == 40 and mode["damage"]["shares"] == {"DT_ELECTRICITY": .75, "DT_IMPACT": .25}
    assert mode["wikiOverride"] == ["multishot", "damage", "procChance"]


# ── Epitaph never reloads (WFSim M114) ────────────────────────────────────

@pytest.mark.parametrize("name,infinite", [("Epitaph", True), ("Epitaph Prime", True), ("Lex", False)])
def test_epitaph_fires_from_the_reserve(name, infinite):
    combat = prepare(dict(weapon=_weapon(name), fire_mode=0, effects=(), scenario=Scenario(distance=10.)), [], [])
    assert combat["infiniteAmmo"] is infinite


# ── replay mechanics, Python reference and native shadow alike ────────────

@pytest.fixture(params=[False, True], ids=["reference", "shadow"])
def engine(request, monkeypatch):
    monkeypatch.setattr(native_replay, "SHADOW", request.param)
    return request.param


def test_blast_pile_drops_the_overflow_of_the_shot_that_fills_it(engine):
    # 4 procs a shot, a 15 s fuse: 4 + 4 + (2 kept of 4) detonate together.
    st = stats(damage_types={"DT_EXPLOSION": 100.0}, fire_rate=1.0, multishot=4.0, proc_duration_multiplier=10.0)
    r = run(st, window_seconds=2.5)
    assert r["shots"] == 3
    assert r["nonDotWindow"] == pytest.approx(10 * 30.0)


def test_shield_gate_passes_five_percent_of_the_breaking_hit(engine):
    st = stats(damage_types={"DT_IMPACT": 500.0}, fire_rate=1.0, status_chance=0.0, dot_base_damage=None)
    body = run(st, dict(target(hp=1000), shield=100), window_seconds=.5)
    assert body["totalWindowDamage"] == pytest.approx(100 + 400 * SHIELD_GATE_LEAK)
    # A direct weakpoint hit bypasses the gate.
    head = run(st, dict(target(hp=1000), shield=100), window_seconds=.5, headshot_chance=1.0)
    assert head["totalWindowDamage"] == pytest.approx(500)


# ── Demolisher faction bracket (WFSim M89) ────────────────────────────────

@pytest.mark.parametrize("target_record,bracket", [
    (dict(path="/Lotus/Types/Enemies/Grineer/Desert/Avatars/DemoDevourerAvatar"), .8),
    (dict(path="/Lotus/Types/Enemies/Corpus/DisruptionCarrusPilotAvatar"), .8),
    (dict(path="/Lotus/Types/Enemies/Corpus/DisruptionShieldDroneAvatar"), 1.),
    (dict(path="/Lotus/Types/Enemies/Corpus/RifleSpacemanAvatar"), 1.),
    (dict(path="/x/DemoDevourerAvatar", factionBracket=1.), 1.),
])
def test_faction_bracket(target_record, bracket):
    assert faction_bracket(target_record) == bracket


def test_demolisher_bracket_squares_into_status_damage():
    st = stats(damage_types={"DT_POISON": 100.0})

    def seed(tg):
        return expected_dot_damage(st, tg)["perType"]["DT_POISON"]["seedPerSecondPerProc"]
    assert seed(dict(target(), factionBracket=.8)) == pytest.approx(seed(target()) * .64, rel=1e-9)


# ── Electricity / Gas ticks land on the struck part (WFSim M100) ──────────

@pytest.mark.parametrize("dtype,extra", [("DT_ELECTRICITY", 2.), ("DT_GAS", 2.), ("DT_POISON", 1.), ("DT_FIRE", 1.)])
def test_electricity_and_gas_ticks_take_headshot_bonuses_again(dtype, extra):
    tg = target(headshotMultiplier=1.5)
    plain = stats(damage_types={dtype: 100.0})
    bonus = stats(damage_types={dtype: 100.0}, headshot_bonus_multiplier=2.0)

    def seed(st, location):
        return expected_dot_damage(st, tg, hit_location=location)["perType"][dtype]["seedPerSecondPerProc"]
    # Every DoT seeds from the head hit (headshot bonuses once); Electricity
    # and Gas ticks also land on the head and take them again.
    assert seed(bonus, "head") / seed(plain, "head") == pytest.approx(2. * extra, rel=1e-9)
    assert seed(bonus, "body") == pytest.approx(seed(plain, "body"))


# ── fatal negatives: decided by combat after the build re-adapts ──────────

def _line(code, label):
    return o._RivenLine(code=code, label=label, value=-.5, low=-.5, high=-.5, negative=True, unit="%", effect=None)


def test_assess_negatives_reoptimizes_suspects_and_keeps_neutral_stats_harmless(monkeypatch):
    lines = {code: _line(code, code) for code in "ABCD"}
    # Fixed build: reference 100; A -10%, B -50%, C (neutral) -60%, D -70%.
    monkeypatch.setattr(o, "_best_fixed_scores", lambda weapon, items, **kw: [100., 90., 50., 40., 30.])
    monkeypatch.setattr(o, "_card_from_lines", lambda lines: tuple(line.code for line in lines))
    re_searched = {(): 100., ("B",): 80., ("D",): 55.}

    def optimize(weapon, pool, riven, **kw):
        return SimpleNamespace(score=re_searched[tuple(code for code in riven if code in "ABCD")])
    monkeypatch.setattr(o, "_optimize", optimize)
    monkeypatch.setattr(o, "proxy_seed_best", lambda weapon, pool, riven, best, **kw: best)
    ranked = [(0., lines[code]) for code in "ABCD"]
    rows = o._assess_negatives(
        {}, [], SimpleNamespace(cards=()), [], ranked, lines, frozenset({"C"}),
        scenario=None, metric="killsPerMinute", passives=None, capacity_limit=60, target_context={}, keep_cap=None)
    by_code = {row["code"]: row for row in rows}
    assert by_code["A"]["reoptimizedDelta"] is None and not by_code["A"]["fatal"]
    assert by_code["B"]["reoptimizedDelta"] == pytest.approx(-.2) and not by_code["B"]["fatal"]
    assert by_code["C"]["neutral"] and by_code["C"]["reoptimizedDelta"] is None and not by_code["C"]["fatal"]
    assert by_code["D"]["reoptimizedDelta"] == pytest.approx(-.45) and by_code["D"]["fatal"]
    assert [row["code"] for row in rows][0] == "C"  # sorted by the loss that decides


def test_assess_negatives_reads_windowed_dps_when_kills_per_minute_saturate(monkeypatch):
    seen = {}

    def fixed(weapon, items, **kw):
        seen["metric"] = kw["metric"]
        return [1.]
    monkeypatch.setattr(o, "_best_fixed_scores", fixed)
    o._assess_negatives({}, [], SimpleNamespace(cards=()), [], [], {}, frozenset(), scenario=None,
                        metric="killsPerMinute", passives=None, capacity_limit=60, target_context={}, keep_cap=None)
    assert seen["metric"] == "windowedDps"


# ── a caller may cache its fixed Incarnon route ───────────────────────────

def test_cached_incarnon_route_joins_the_statics_key():
    def key(benchmark):
        return o._statics_cache_key("/w", None, 0, "viral", "fast", 1.0, 60, "killsPerMinute", benchmark)
    assert key({"enemy": "x"}) != key({"enemy": "x", "incarnon": {"2": "a"}})
    assert key({"enemy": "x", "incarnon": {"2": "a"}}) != key({"enemy": "x", "incarnon": {"2": "b"}})


@pytest.mark.parametrize("dtype,extra", [("DT_ELECTRICITY", 2.), ("DT_POISON", 1.)])
def test_head_ticks_in_the_replay(engine, dtype, extra):
    tg = target(hitProxies=[{"part": "head", "damageAtten": 1.0}])
    plain = run(stats(damage_types={dtype: 100.0}, fire_rate=1.0), tg, headshot_chance=1.0, window_seconds=7.)
    bonus = run(stats(damage_types={dtype: 100.0}, fire_rate=1.0, headshot_bonus_multiplier=2.0), tg,
                headshot_chance=1.0, window_seconds=7.)
    assert bonus["dotWindow"] == pytest.approx(plain["dotWindow"] * 2. * extra, rel=.02)
