"""Narin (internal Duelist) completed in the warframe sidecar (2026-10-12).

Names from the official Chinese page, numbers from the wiki infoboxes,
polarities / growth / icons from the 2026.10.08 client; Neote is subsumable.
Hand-added rows and a few frames' rank-30 panels now match the client.
"""
import pytest

import app

CATALOG = app.WARFRAME_CATALOG
FRAMES = {row["path"]: row for row in CATALOG["warframes"]}
NARIN = FRAMES["/Lotus/Powersuits/Duelist/Duelist"]


def test_narin_names_panel_and_polarities():
    assert NARIN["nameEn"] == "Narin" and NARIN["nameZh"] == "Narin"
    assert NARIN["rank30Panel"] == {"health": 370.0, "shield": 650.0, "armor": 165.0, "energy": 300.0, "sprint": 1.1}
    # Naramon aura, Vazarin + Madurai slots, no exilus polarity (client and wiki agree).
    assert NARIN["slotPolarities"] == {"aura": "AP_TACTIC", "exilus": None,
                                      "normal": [None, None, None, "AP_DEFENSE", None, None, None, "AP_ATTACK"]}
    assert (app.ROOT / "frontend" / NARIN["portraitAsset"].lstrip("/")).is_file()
    assert "Sangodae" in NARIN["passiveEn"] and NARIN["passive"]


def test_narin_abilities_have_numbers_and_art():
    abilities = NARIN["abilities"]
    assert [a["nameZh"] for a in abilities] == ["寒霜疾剑", "冰翎御盾", "鹤影舞坠", "降灵旋刃"]
    assert [a["nameEn"] for a in abilities] == ["Neote", "Naraemagi", "Hakchum", "Nurinarim"]
    assert [a["energyCost"]["activation"] for a in abilities] == [25, 50, 75, 25]
    for ability in abilities:
        assert ability["path"].startswith("/Lotus/Powersuits/Duelist/Abilities/")
        assert len(ability["scalars"]) >= 5 and ability["description"] and ability["descriptionEn"]
        assert (app.ROOT / "frontend" / ability["iconAsset"].lstrip("/")).is_file()
    landing = next(s for s in abilities[2]["scalars"] if s["id"].startswith("cold_landing_damage"))
    assert landing["rankValues"] == [400, 600, 800, 1000] and landing["modifier"] == "AVATAR_ABILITY_STRENGTH"
    catalog_paths = {row["path"] for row in CATALOG["abilities"]}
    assert all(ability["path"] in catalog_paths for ability in abilities)
    assert any(row["path"].endswith("DuelistThrustAbility") for row in CATALOG["helminth"])


def test_strength_scales_narin_abilities():
    intensify = next(m for m in CATALOG["mods"] if m.get("nameEn") == "Intensify")
    normal = [{"id": intensify.get("id") or intensify["path"], "rank": intensify["maxRank"]}] + [None] * 7
    result = app.WARFRAME_ENGINE.calculate({"frameId": NARIN["path"], "normalMods": normal})
    neote = result["abilityScalars"][0]
    per_hit = next(s for s in neote["scalars"] if s["id"].startswith("cold_damage_per_hit"))
    assert per_hit["value"] == pytest.approx(520)


@pytest.mark.parametrize("name, rank30", [("Yareli", (370, 555, 300)), ("Sevagoth", (None, 335, None))])
def test_rank30_panels_follow_the_client(name, rank30):
    frame = next(row for row in CATALOG["warframes"] if row["nameEn"] == name)
    for stat, value in zip(("health", "shield", "energy"), rank30):
        if value is not None:
            assert frame["rank30Panel"][stat] == pytest.approx(value)


def test_hakchum_cold_vulnerability_multiplies_only_pure_cold():
    row = next(r for r in app.CATALOG["buildOptions"]["externalBuffs"] if r["id"] == "hakchum")
    assert row["label"] == "Narin · 鹤影舞坠"
    mods = {}
    for mod in app.EXPORTS["mods"]:
        mods.setdefault(mod.get("nameEn"), mod["path"])
    boltor = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Boltor Prime")
    base = dict(weapon=boltor["path"], mods=[dict(path=mods["Cryo Rounds"], slot=0)], enemy=app._BENCHMARK_ENEMY_PATH,
                level=170, steelPath=True)
    plain = app.simulate_manual_payload(base)["moddedStats"]["damage_types"]
    storm = app.simulate_manual_payload(dict(base, externalBuffs=[{"id": "hakchum"}]))["moddedStats"]["damage_types"]
    assert storm["DT_FREEZE"] == pytest.approx(plain["DT_FREEZE"] * 2.5)
    assert storm["DT_PUNCTURE"] == pytest.approx(plain["DT_PUNCTURE"])
