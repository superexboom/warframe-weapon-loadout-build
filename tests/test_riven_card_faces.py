"""2026-10-20: Riven card faces and names come from the RandomModRare templates.

In game the card art cycles through the Icon of each stat's UpgradeEntry and the
name is built from the stats' prefix/suffix syllables. Every rollable code needs
local art; spliced traits have no syllables.
"""
from __future__ import annotations

from pathlib import Path

import app
from wfarsenal import optimizer as o

ROOT = Path(app.__file__).resolve().parent


def test_every_rollable_code_has_local_card_art():
    for weapon_type, rows in app.CATALOG["statsByType"].items():
        for row in rows:
            assert row["art"], (weapon_type, row["code"])
            assert (ROOT / "frontend" / row["art"].lstrip("/")).is_file()


def test_face_syllables_match_the_wiki_example():
    # wiki: "Boltor Sati-critaata" = Multishot, Critical Chance, Base Damage.
    faces = o.riven_card_faces(app.EXPORTS["rivenTemplates"], "rifle")
    assert (faces["S"]["prefix"], faces["0"]["prefix"], faces["D"]["suffix"]) == ("sati", "crita", "ata")
    assert faces["0"]["icon"].endswith("/Rifle/RifleCritChanceMod.png")
    assert faces["VI"]["prefix"] is None and faces["VI"]["icon"].endswith("/RivenUpgrades/WeaponViralDamage.png")


def test_lenient_identity_covers_multi_upgrade_stats():
    melee = o.riven_card_faces(app.EXPORTS["rivenTemplates"], "melee")
    # Two-upgrade (IPS, slide crit) and shared-rule (attack speed) stats get faces.
    assert {"8", "9", "A", "E", "J"} <= set(melee)
    rifle = o.riven_card_faces(app.EXPORTS["rivenTemplates"], "rifle")
    assert "R" in rifle and "J" not in rifle


def test_hunter_munitions_has_art_and_chinese_text():
    row = next(m for m in app.CATALOG["manualMods"] if m["nameEn"] == "Hunter Munitions")
    assert row["art"].endswith("/Sets/Hunter/HunterMunitions.png")
    art = ROOT / "frontend" / row["art"].lstrip("/")
    assert art.is_file() and art.with_suffix(".bg.jpg").is_file() and art.with_suffix(".fg.png").is_file()
    assert row["effectsZhByRank"][-1] == ["+30% 几率在暴击时造成 <DT_SLASH_COLOR>"]
