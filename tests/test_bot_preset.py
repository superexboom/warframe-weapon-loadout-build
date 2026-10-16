"""Engine switches used by the Bot preset (2026-10-08).

- spliced (fusion) traits use the server bases (wiki), not the client template:
  a pistol Weakpoint Damage roll of 310% at disposition 1.35 needs base 225;
- ultra with a fixed element runs only that element's seed (it used to index an
  empty result list);
- a preset scenario may be cached under its own key;
- combatState.infiniteAmmo removes reloads (measured, not used by the Bot).
"""
from tests.test_stackable_projectiles import setup
from tests.test_combat_replay import target
import app
from wfarsenal import optimizer
from wfarsenal.combat_replay import replay


def test_fusion_bases_follow_server_rolls_for_every_gun_type():
    for family in ("rifle", "shotgun", "pistol", "archgun"):
        bases = app.RIVEN_BASE_VALUES[family]
        assert (bases["W"], bases["Y"], bases["AE"], bases["MA"], bases["VI"], bases["FO"]) == (225.0, 247.5, 45.0, 90.0, 90.0, 45.0)
    assert "HR" not in optimizer.FUSION_SERVER_BASES["archgun"]
    _nominal, low, high = optimizer.riven_stat_window(app.RIVEN_BASE_VALUES["pistol"]["W"], 1.35, 2, 0)
    assert low <= 310 <= high
    assert abs(app.RIVEN_BASE_VALUES["melee"]["PA"] - 8.1) < 1e-9 and abs(app.RIVEN_BASE_VALUES["melee"]["HD"] - 119.7) < 1e-9


def test_ultra_with_fixed_viral_runs_the_viral_seed():
    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == "Lato")
    bases = app.RIVEN_BASE_VALUES["pistol"]
    disposition = float(weapon["disposition"])
    result = app.analyze_payload(dict(
        weapon=weapon["path"], disposition=disposition, profile="ultra", elementTarget="viral", headshotChance=0.5,
        stats=[dict(code=c, value=bases[c] * disposition, negative=False) for c in ("D", "1")]))
    assert result["actual"]["mods"]
    assert result["actualGain"] == result["actualGain"]  # finite, no crash


def test_preset_scenario_has_its_own_cache_key():
    common = ("/w", (), 0, "viral", "fast", 1.0, 60, "killsPerMinute")
    plain = optimizer._statics_cache_key(*common, {"enemy": "/e"})
    preset = optimizer._statics_cache_key(*common, {"enemy": "/e", "scenario": {"triggerPolicy": "assumed_max"}})
    assert plain != preset and "scenario" not in plain


def test_infinite_ammo_removes_reloads():
    def reloads(state):
        stats, combat = setup("Rubico Prime", state=state)
        return replay(stats, target(1e12), attacks_per_second=stats.fire_rate, window_seconds=30, combat=combat)["reloads"]
    assert reloads({}) > 0
    assert reloads({"infiniteAmmo": True}) == 0


def test_ultra_reads_the_entry_baked_at_the_catalog_disposition():
    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == "Lato")
    bases = app.RIVEN_BASE_VALUES["pistol"]
    catalog = float(weapon["disposition"])
    card = lambda d: [dict(code=c, value=bases[c] * d, negative=False) for c in ("D", "1")]
    common = dict(weapon=weapon["path"], elementTarget="viral", headshotChance=0.5)
    app.analyze_payload(dict(common, disposition=catalog, profile="fast", stats=card(catalog)))
    other = round(catalog + 0.1, 2)
    miss = app.analyze_payload(dict(common, disposition=other, profile="ultra", stats=card(other)))
    hit = app.analyze_payload(dict(common, disposition=other, profile="ultra", stats=card(other), _cacheDisposition=catalog))
    assert "ultra-profile-baseline-approximate" in miss["unsupported"]
    assert "ultra-profile-baseline-approximate" not in hit["unsupported"]
    assert any(item.startswith("cache: ") for item in hit["skipped"])
