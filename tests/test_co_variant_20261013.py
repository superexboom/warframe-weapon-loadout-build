"""A fractional live status count re-derives only the CO tail of apply_mods.

``damage.co_variant`` (and wfcore's native port of it) must equal a full
``apply_mods`` whose CO effects were scaled by live/ceil, field for field and
bit for bit; the resolver relies on that to skip ~90% of its apply_mods calls.
"""
import random
import struct
from dataclasses import replace

import pytest

import app
from wfarsenal.damage import ModEffect, Scenario, apply_mods, apply_mods_spec, co_variant


def _bits(x):
    return struct.pack("<d", x) if isinstance(x, float) else x


def _same(a, b):
    if isinstance(a, dict):
        assert list(a) == list(b)
        for k in a:
            _same(a[k], b[k])
    elif isinstance(a, (list, tuple)):
        assert type(a) is type(b) and len(a) == len(b)
        for x, y in zip(a, b):
            _same(x, y)
    else:
        assert _bits(a) == _bits(b), (a, b)


POOL = [
    ("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, (0.5, 3.6)),
    ("WEAPON_DAMAGE_AMOUNT", "ADD_BASE", None, (10.0, 150.0)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_FIRE", (0.3, 1.2)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_FREEZE", (0.3, 1.2)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_ELECTRICITY", (0.3, 1.2)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_POISON", (0.3, 1.2)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_SLASH", (0.3, 1.2)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "STACKING_MULTIPLY", "DT_ANY", (0.1, 0.6)),
    ("WEAPON_PERCENT_BASE_DAMAGE_ADDED_POST_COALESCE", "STACKING_MULTIPLY", "DT_ELECTRICITY", (0.2, 0.6)),
    ("WEAPON_FIRE_ITERATIONS", "STACKING_MULTIPLY", None, (0.3, 1.2)),
    ("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", None, (0.5, 2.0)),
    ("WEAPON_VICTIM_DAMAGE_AMOUNT", "STACKING_MULTIPLY", None, (0.1, 0.5)),
]


def _effects(rng):
    out = [ModEffect(t, op, rng.uniform(*span), damage_type=dt)
           for t, op, dt, span in rng.sample(POOL, rng.randint(2, 8))]
    out = [replace(e, symbol_filter="VictimLessThanHalfHealth") if e.upgrade_type == "WEAPON_VICTIM_DAMAGE_AMOUNT" else e
           for e in out]
    for _ in range(rng.randint(1, 2)):
        out.insert(rng.randrange(len(out) + 1),
                   ModEffect("WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE", "STACKING_MULTIPLY", rng.uniform(0.2, 0.8)))
    return out


@pytest.mark.parametrize("name", ["Boltor", "Hek", "Nikana", "Kuva Bramma", "Lato"])
def test_co_variant_matches_apply_mods(name):
    weapon = app.optimizer.resolve_record(
        app.EXPORTS["weapons"], next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == name)["path"], kind="weapon")
    rng = random.Random(name)
    for _ in range(40):
        effects = _effects(rng)
        ceil = rng.randint(1, 6)
        live = ceil - rng.uniform(0.01, 0.99)
        scenario = Scenario(victim_status_count=ceil)
        template, spec = apply_mods_spec(weapon, effects, scenario=scenario)
        scaled = [replace(e, value=e.value*live/ceil) if e.upgrade_type == "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE" else e
                  for e in effects]
        exact = apply_mods(weapon, scaled, scenario=scenario)
        varied = co_variant(template, spec, [replace(e, value=e.value*live/ceil) for e in template.co_bucket])
        assert vars(varied).keys() == vars(exact).keys()
        for key, value in vars(exact).items():
            _same(getattr(varied, key), value)


def test_native_variants_match_reference(monkeypatch):
    """Shadow mode: native replays (deriving CO variants natively) equal Python."""
    pytest.importorskip("wfarsenal.wfcore")
    from wfarsenal import native_replay
    monkeypatch.setattr(native_replay, "SHADOW", True)
    for name in ("Boltor", "Nikana"):
        weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == name)
        native_replay.STATS.update(native=0, fallback=0)
        app.build_weapon_route({"weapon": weapon["path"], "mode": "auto", "profile": "fast"})
        assert native_replay.STATS["native"] > 0
