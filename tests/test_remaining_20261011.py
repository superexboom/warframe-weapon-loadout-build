"""Remaining non-measurement items (2026-10-11).

- Zaw parts carry their client paths (zaws.json was frozen with invented
  ones); old selections still resolve, read as a whole by their strike.
- A two-handed Zaw multiplies its damage by the strike's two-handed factor.
- An assembled Zaw swings its strike's one- or two-handed melee tree and
  slams; the Dark Split-Sword forms read their own client entities.
- Fist / sparring punch and kick effects (0 m Slams[]) are not hits.
- Zymos: a headshot embeds and bursts 953 Toxin 1.1 s later.
- Melee Duplicate replays yellow crits; Kuva Grattler's multishot copies
  carry 25% crit / status.
"""
import json

import pytest

import app
from wfarsenal import melee_sequence as ms
from wfarsenal.simulator import is_zaw_assembly, resolve_zaw_record
from wfarsenal.status_arcanes import configuration

ZAWS = app.EXPORTS["zaws"]
NAMES = {table: {row["nameEn"]: path for path, row in ZAWS[table].items()} for table in ("strikes", "grips", "links")}


def _base(name):
    return next(w for w in app.EXPORTS["weapons"] if w["path"].endswith("/" + name))


def _zaw(strike, grip, link="Jai"):
    parts = [NAMES["strikes"][strike], NAMES["grips"][grip], NAMES["links"][link]]
    return resolve_zaw_record(_base("LotusModularWeapon"), parts, ZAWS)


def test_zaw_parts_use_client_paths_and_old_selections_still_resolve():
    assert NAMES["grips"]["Peye"].endswith("/ModularMelee01/Handle/HandleOne")
    assert NAMES["grips"]["Kroostra"].endswith("/ModularMelee01/Handle/HandleSix")
    assert NAMES["links"]["Vargeet Jai II"].endswith("/Balance/BalanceSpeedIICritI")
    assert all(path == row["rivenPath"] for path, row in ZAWS["strikes"].items())
    # The old Peye path (HandleSix) is Kroostra's client path: an old selection
    # is recognised by its strike and read in the old paths as a whole.
    old = [ZAWS["strikes"][NAMES["strikes"]["Balla"]]["legacyPath"], ZAWS["grips"][NAMES["grips"]["Peye"]]["legacyPath"],
           ZAWS["links"][NAMES["links"]["Jai"]]["legacyPath"]]
    record = resolve_zaw_record(_base("LotusModularWeapon"), old, ZAWS)
    assert is_zaw_assembly(old, ZAWS)
    assert record["zawParts"][1] == NAMES["grips"]["Peye"] and record["zawHanded"] == "one"
    assert _zaw("Balla", "Kroostra")["zawHanded"] == "two"


def test_two_handed_zaw_damage_factor():
    strike = ZAWS["strikes"][NAMES["strikes"]["Plague Keewar"]]
    assert strike["twoHandedDamageFactor"] == pytest.approx(0.85)
    two = _zaw("Plague Keewar", "Seekalla")  # -4 grip, -4 link
    one = _zaw("Plague Keewar", "Peye")
    assert two["fireModes"][0]["damage"]["total"] == pytest.approx((306 - 8) * 0.85)
    assert one["fireModes"][0]["damage"]["total"] == pytest.approx(306 - 8)
    assert ZAWS["strikes"][NAMES["strikes"]["Cyath"]]["twoHandedDamageFactor"] == pytest.approx(1.08)


def test_zaw_swings_its_strikes_melee_tree():
    hammer = _zaw("Rabvee", "Shtung")
    machete = _zaw("Rabvee", "Laka")
    assert ms.weapon_row(hammer)["tree"].endswith("/HammerMeleeTree")
    assert ms.weapon_row(machete)["tree"].endswith("/MacheteMeleeTree")
    assert ms.default_route(hammer) == "slamBullet" and ms.default_route(machete) == "combo"
    slam = ms.build_schedule(hammer)
    # One heavy-slam area hit at HeavySlamAoE's x3 (wiki), not the Slams[] row's x5.
    assert slam["route"] == "slamBullet" and slam["segments"][0]["hit"]["atten"] == pytest.approx(3.0)
    stance = app._compatible_stances(machete)[0]
    combo = ms.build_schedule(machete, "combo", stance=stance["path"])
    assert combo["route"] == "combo" and combo["stance"] == stance["path"]


def test_dark_split_sword_forms_read_their_client_entities():
    forms = {w["path"].rsplit("#", 1)[-1]: w for w in app.EXPORTS["weapons"] if "DarkSwordDaggerHybridWeapon#" in w["path"]}
    assert ms.weapon_row(forms["HeavyBlade"])["tree"].endswith("/AxeMeleeTree")
    assert ms.weapon_row(forms["DualSwords"])["tree"].endswith("/DualSwordMeleeTree")
    for form in forms.values():
        stance = app._compatible_stances(form)[0]
        assert ms.build_schedule(form, "combo", stance=stance["path"])["route"] == "combo"


def test_zero_radius_punch_effects_are_not_hits():
    attack = dict(hits=[dict(t=0.3)], events=[dict(t=0.4, event="PunchEffectRight"), dict(t=0.6, event="MeleeSlam")])
    slams = {"PunchEffectRight": dict(event="PunchEffectRight", radius=0.0, attenuation=1.0),
             "MeleeSlam": dict(event="MeleeSlam", radius=5.0, attenuation=1.0)}
    assert [h["kind"] for h in ms.attack_hits(attack, slams)] == ["sweep", "slam"]


def _zymos(headshots):
    payload = dict(weapon="/Lotus/Weapons/Infested/Pistols/InfUzi/InfUziWeapon", mods=[], enemy=app._BENCHMARK_ENEMY_PATH,
                   level=170, steelPath=True, headshotChance=headshots)
    return app.simulate_manual_payload(payload)["benchmarkTimeline"]["killsPerMinute"]


def test_zymos_headshots_embed_and_burst():
    reference = json.loads((app.ROOT / "data/mechanics/combat-reference.json").read_text(encoding="utf-8"))
    radials = reference["auditedAttacks"]["/Lotus/Weapons/Infested/Pistols/InfUzi/InfUziWeapon"]["radials"]
    burst = next(r for r in radials if r.get("headOnly"))
    assert burst["damage"] == {"toxin": 953.0} and burst["impact_delay_seconds"] == pytest.approx(1.1)
    body, half = _zymos(0.0), _zymos(0.5)
    assert half > 3 * body


def test_melee_duplicate_replays_yellow_crits():
    record = next(a for a in app.EXPORTS["arcanes"] if a.get("nameEn") == "Melee Duplicate")
    assert configuration(record, 0)["chance"] == pytest.approx(0.25)
    assert configuration(record, 5)["chance"] == pytest.approx(1.0)
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Nikana Prime")
    mods = [dict(path=next(m["path"] for m in app.EXPORTS["mods"] if m.get("nameEn") == name), slot=i)
            for i, name in enumerate(("Primed Pressure Point", "Organ Shatter"))]
    payload = dict(weapon=weapon["path"], mods=mods, enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                   headshotChance=0.5)
    plain = app.simulate_manual_payload(payload)["benchmarkTimeline"]["killsPerMinute"]
    duplicated = app.simulate_manual_payload(dict(payload, arcanes=[dict(path=record["path"], rank=5)]))
    assert duplicated["benchmarkTimeline"]["killsPerMinute"] > plain * 1.05


def test_kuva_grattler_multishot_copies():
    copy = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Kuva Grattler")["fireModes"][0]["multishotCopy"]
    assert copy["direct"]["critChance"] == pytest.approx(0.25) and copy["radial"]["procChance"] == pytest.approx(0.25)
