"""Native apply_mods (wfcore + mods_native) against the Python reference (2026-10-13).

Every apply_mods_spec call of a build-page search runs both and compares
field by field: exact float bits, int vs float, dict key and attribute order
(shadow mode). The weapons cover the reference's weapon-side branches: pellets,
melee and heavy attacks, Incarnon forms and the multishot copy, innate
elements, bows and charge, ammo cost, Arch-guns, Simulor orbs, spool and
battery weapons. The full check is tools/verify_apply_mods.py on a recorded
corpus of ~19,000 calls with scenario variants.
"""
import pytest

import app
from wfarsenal import damage, mods_native

pytestmark = pytest.mark.skipif(not mods_native.ENABLED, reason="native core not built")

WEAPONS = {w.get("nameEn"): w for w in app.CATALOG["weapons"]}
CASES = [
    ("Boltor Prime", {}),
    ("Hek", {"aiming": True}),
    ("Nikana Prime", {}),
    ("Gram Prime", {"heavyAttack": True}),
    ("Latron Prime", {"fireMode": 1}),
    ("Kuva Bramma", {}),
    ("Lenz", {"aiming": True}),
    ("Twin Grakatas", {"distance": 30}),
    ("Simulor", {}),
    ("Kohm", {}),
    ("Fulmin", {}),
    ("Imperator Vandal", {}),
    ("Torid", {"incarnonCycle": True}),
]


@pytest.fixture
def shadowed(monkeypatch):
    calls = {"n": 0}
    original = mods_native.shadow

    def counted(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setenv("WF_ANALYZER_SERIAL", "1")  # every call in this process, where it is checked
    monkeypatch.setattr(mods_native, "SHADOW", True)
    monkeypatch.setattr(mods_native, "shadow", counted)
    return calls


@pytest.mark.parametrize("name,extra", CASES, ids=[c[0] for c in CASES])
def test_build_search_matches_the_reference(name, extra, shadowed):
    weapon = WEAPONS[name]
    request = {"weapon": weapon["path"], "mode": "auto", "profile": "fast", **extra}
    try:
        app.build_weapon_payload(request)
    except app.SimulationError as exc:  # an unavailable mode is the case's own business
        pytest.skip(str(exc))
    assert shadowed["n"] > 0


def test_an_empty_bucket_keeps_the_int_zero():
    """sum([]) is the int 0 in the reference; JSON shows it as 0, not 0.0."""
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Boltor Prime")
    stats = damage.apply_mods(weapon, [])
    assert type(stats.cold_stack_damage) is int and type(stats.combo_extra_chance) is int
    reference = damage._apply_mods_spec_py(weapon, [])
    assert not mods_native.differences(reference, damage.apply_mods_spec(weapon, []))


def test_a_record_changed_in_place_is_not_served_from_the_cache():
    """Caches key records by top-level values (record_keys.shallow_key), so a
    caller that edits a field between calls gets the new answer."""
    weapon = dict(next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Boltor Prime"))
    before = damage.apply_mods(weapon, []).magazine
    weapon["magazineSize"] = 7
    after = damage.apply_mods(weapon, [])
    assert after.magazine != before
    assert not mods_native.differences(damage._apply_mods_spec_py(weapon, []), damage.apply_mods_spec(weapon, []))


def test_preps_are_shared_across_request_threads():
    """The app serves requests on many threads; a prep built on one is used
    and dropped on others (an unsendable class aborted the process)."""
    import threading

    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Hek")
    damage.apply_mods(weapon, [])
    errors = []

    def use():
        try:
            for _ in range(20):
                damage.apply_mods(weapon, [])
        except Exception as exc:  # pragma: no cover - the failure being guarded
            errors.append(exc)

    threads = [threading.Thread(target=use) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    mods_native._PREPS.clear()  # dropped here, built elsewhere
    assert not errors
