"""2026-10-21: the build page can drop faction (bane) mods from auto builds."""
from __future__ import annotations

import app

SOMA = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Soma Prime")


def _build(**extra):
    payload = dict(weapon=SOMA["path"], mode="auto", profile="fast", metric="killsPerMinute",
                   enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True, **extra)
    result = app.build_weapon_payload(payload)
    return {mod["path"] for mod in result["build"]["mods"]}, result


def _notes(result):
    return [note for note in result["build"].get("skipped", []) + result.get("skipped", []) if "optimizer-scope" in note]


def test_exclude_faction_mods_drops_bane_candidates_but_keeps_required():
    bane = next(m["path"] for m in app.MANUAL_MODS if m["path"] in app.FACTION_DAMAGE_MOD_PATHS
                and m.get("nameEn") == "Primed Bane of Grineer")
    paths, result = _build(excludeFactionMods=True)
    assert not paths & app.FACTION_DAMAGE_MOD_PATHS
    assert any("屏蔽派系歧视卡" in note for note in _notes(result))
    paths, _ = _build(excludeFactionMods=True, requiredMods=[bane])
    assert bane in paths and len(paths & app.FACTION_DAMAGE_MOD_PATHS) == 1
