"""2026-10-16 (Bot bake): wiki Riven weights, fusion-crowded shortlists, reload maluses."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from wfarsenal import optimizer as o


# ── fusion-crowded recommendation shortlist ───────────────────────────────

@pytest.mark.parametrize("profile", ["fast", "standard", "deep"])
def test_fusion_crowded_top_eight_still_yields_a_legal_three_stat_card(profile):
    # Seven fusion stats outrank every ordinary stat: the top eight holds one
    # ordinary stat, so no legal (one-fusion) three-stat card without top-up.
    codes = sorted(o._FUSION_LINE_CODES)[:7] + ["1", "D", "K"]
    lines = [o._RivenLine(code, code, 1, 1, 1, False, "", SimpleNamespace(supported=True)) for code in codes]
    scores = {code: 100 - index for index, code in enumerate(codes)}

    def fit(weapon, base, card, **kwargs):
        return SimpleNamespace(score=10 + sum(scores[line.code] for line in card.riven_lines))

    with patch.object(o, "_best_fixed", side_effect=fit), patch("wfarsenal.parallel.get_pool", return_value=None):
        result, _, tiers = o._recommend_positive({}, SimpleNamespace(cards=()), lines, 3,
                                                 scenario=SimpleNamespace(conditional_stacks={}),
                                                 metric="killsPerMinute", profile=profile)
    assert [line.code for line in result if line.code in o._FUSION_LINE_CODES] == [codes[0]]
    assert sorted(line.code for line in result if line.code not in o._FUSION_LINE_CODES) == ["1", "D"]
    assert tiers


# ── reload speed of -100% or below ────────────────────────────────────────

def _archgun(name):
    import app
    record = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)
    return o._select_fire_mode(record, 0, weapon_type=o._weapon_type(None, record))[0]


@pytest.mark.parametrize("malus,expected", [(90.0, 20.0), (100.0, None), (103.0, None)])
def test_reload_speed_at_or_below_minus_100_percent_never_finishes(malus, expected):
    from wfarsenal import damage, mods_native
    weapon = _archgun("Phaedra")  # base reload 2 s; 3+1 Riven malus up to 103%
    effects = [o._effect_from_code("F", malus, negative=True, source="riven:test")]
    reload_time = damage.apply_mods(weapon, effects).reload_time
    assert reload_time == pytest.approx(expected) if expected else reload_time == damage.RELOAD_NEVER_SECONDS
    if mods_native.ENABLED:
        assert not mods_native.differences(damage._apply_mods_spec_py(weapon, effects),
                                           damage.apply_mods_spec(weapon, effects))


@pytest.mark.parametrize("engine", ["python", "native"])
def test_replay_with_a_never_finishing_reload_ends_after_one_magazine(engine, monkeypatch):
    # A negative reload time sent the replay clock backwards: the 30 s window
    # never closed and the trajectory grew to GBs (Dual Decurion / Phaedra bake).
    from wfarsenal import native_replay
    from wfarsenal.combat_replay import replay
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    if engine == "python":
        monkeypatch.setattr(native_replay, "ENABLED", False)
    elif not native_replay.ENABLED:
        pytest.skip("native core not built")
    weapon = _archgun("Phaedra")
    effects = [o._effect_from_code("F", 103.0, negative=True, source="riven:test")]
    combat = prepare(dict(weapon=weapon, fire_mode=0, effects=effects, scenario=Scenario(trigger_policy="emergent")), [], [])
    stats, _ = combat["resolve"]("selected", {})
    target = dict(health=1e12, shield=0, armour=0, overguard=0, baseLevel=1, faction="")
    event = replay(stats, target, attacks_per_second=stats.sustained_attack_rate, window_seconds=30, combat=combat)
    assert event["shots"] == pytest.approx(stats.magazine)
