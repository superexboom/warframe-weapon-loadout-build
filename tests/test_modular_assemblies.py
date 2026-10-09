"""Kitgun / Zaw assemblies: Riven family, cache identity, dispositions, winners.

- every Kitgun takes the pistol-type Kitgun Riven, primary or secondary;
- an assembly caches under its parts, never under the shared base path;
- Kitgun / Zaw dispositions follow the 2026.10.08 client Rivens;
- modular_winners.json covers 6 chambers x 2 slots and 11 strikes.
"""
import json

import pytest

import app
from wfarsenal import optimizer

EXPORT = app.ROOT / "data/export/2026.08.13.13.24"
WINNERS = EXPORT / "modular_winners.json"


def _base(name):
    return next(w for w in app.EXPORTS["weapons"] if w["path"].endswith("/" + name))


def _kitgun(slot, chamber):
    kitguns = app.EXPORTS["kitguns"]
    barrel = next(p for p, row in kitguns["barrels"].items() if row["nameEn"] == chamber)
    grip = next(p for p, row in sorted(kitguns["handles"].items()) if row["slot"] == slot)
    return [barrel, grip, sorted(kitguns["clips"])[0]]


def test_every_kitgun_takes_the_pistol_riven():
    primary = _base("LotusModularPrimaryShotgun")
    assembled = app.resolve_kitgun_record(primary, _kitgun("primary", "Catchmoon"), app.EXPORTS["kitguns"])
    assert optimizer._riven_type(None, primary) == "pistol"
    assert optimizer._riven_type(None, assembled) == "pistol"
    assert optimizer._weapon_type(None, assembled) != "pistol"  # mechanics keep the primary class
    braton = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Braton Prime")
    assert optimizer._riven_type(None, braton) == "rifle"


def test_assemblies_cache_under_their_parts():
    base = _base("LotusModularWeapon")
    zaws = app.EXPORTS["zaws"]
    grip, link = sorted(zaws["grips"])[0], sorted(zaws["links"])[0]
    one, two = (app.resolve_zaw_record(base, [strike, grip, link], zaws) for strike in sorted(zaws["strikes"])[:2])
    assert optimizer._statics_weapon_identity(base) == base["path"]
    assert optimizer._statics_weapon_identity(one) != optimizer._statics_weapon_identity(two)
    assert optimizer._statics_weapon_identity(one).startswith(base["path"] + "#")


def test_modular_dispositions_follow_the_client_rivens():
    barrels = {row["nameEn"]: row for row in app.EXPORTS["kitguns"]["barrels"].values()}
    assert barrels["Tombfinger"]["omegaAttenuation"] == pytest.approx(0.9)
    assert barrels["Tombfinger"]["primaryOmegaAttenuation"] == pytest.approx(1.0)
    assert barrels["Catchmoon"]["primaryOmegaAttenuation"] == pytest.approx(1.1)
    strikes = {row["nameEn"]: row for row in app.EXPORTS["zaws"]["strikes"].values()}
    assert strikes["Ooltha"]["omegaAttenuation"] == pytest.approx(1.3)
    assert strikes["Ooltha"]["rivenPath"].endswith("/Tip/TipTwo")


def test_modular_winners_cover_every_riven_head():
    winners = json.loads(WINNERS.read_text(encoding="utf-8"))
    assert winners["schemaVersion"] == 2 and winners["buildLabel"] == app.EXPORTS["buildLabel"]
    assert len(winners["kitgun"]) == 6 and len(winners["zaw"]) == 11
    kitguns, zaws = app.EXPORTS["kitguns"], app.EXPORTS["zaws"]
    for chamber, entry in winners["kitgun"].items():
        assert set(entry["candidates"]) == {"primary", "secondary"}
        for slot, candidate in entry["candidates"].items():
            parts = candidate["parts"]
            assert parts[0] == chamber and kitguns["handles"][parts[1]]["slot"] == slot and parts[2] in kitguns["clips"]
            assert candidate["kpm"] > 0
    tips = {row["rivenPath"]: path for path, row in zaws["strikes"].items()}
    for tip, entry in winners["zaw"].items():
        candidate = entry["candidates"]["melee"]
        assert candidate["parts"][0] == tips[tip] and candidate["parts"][1] in zaws["grips"] and candidate["parts"][2] in zaws["links"]
    assert winners["aliases"]["catchmoon"] in winners["kitgun"]
    assert winners["aliases"]["ooltha"] in winners["zaw"]


def test_zaw_assembly_analysis_accepts_melee_fusion_traits():
    base = _base("LotusModularWeapon")
    zaws = app.EXPORTS["zaws"]
    strike = next(p for p, row in zaws["strikes"].items() if row["nameEn"] == "Plague Kripath")
    payload = dict(weapon=base["path"], disposition=zaws["strikes"][strike]["omegaAttenuation"], profile="ultra",
                   kitgunParts=[strike, sorted(zaws["grips"])[0], sorted(zaws["links"])[0]],
                   stats=[dict(code="0", value=115), dict(code="GA", value=58)])
    result = app.analyze_payload(payload)
    assert result["actual"]["objectiveScore"] > 0
