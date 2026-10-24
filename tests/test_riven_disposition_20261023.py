"""2026-10-23: Riven disposition is uniform 1.2 for every Riven weapon."""
import pytest

import app


def test_every_riven_weapon_reads_the_uniform_disposition():
    values = {w["disposition"] for w in app.CATALOG["weapons"] if w["disposition"] is not None}
    assert values and all(v == pytest.approx(1.2) for v in values)
    assert all("legacyDisposition" not in w for w in app.CATALOG["weapons"])


def _engine_request(payload):
    """What analyze_payload hands the optimizer."""
    from unittest.mock import patch
    with patch.object(app, "_ANALYSIS_RESULTS", {}), \
            patch.object(app.optimizer, "analyze_riven_request", side_effect=RuntimeError("captured")) as solve:
        with pytest.raises(RuntimeError, match="captured"):
            app.analyze_payload(payload)
    return solve.call_args.args[1]


def test_a_card_read_at_its_own_disposition_is_validated_there_and_projected_once():
    # The Bot's OCR reads a card rolled at an older disposition (1.45): its
    # values are checked in that window and scaled once to the 1.2 target.
    weapon = next(w for w in app.CATALOG["weapons"] if w.get("nameEn") == "Braton Prime")
    bases = app.RIVEN_BASE_VALUES[app.optimizer._riven_type(None, weapon)]
    scale = app.optimizer.theoretical_structure_scale(3, False)
    old = [dict(code=c, value=bases[c] * 1.45 * scale, negative=False) for c in ("D", "1", "0")]
    new = [dict(stat, value=stat["value"] * 1.2 / 1.45) for stat in old]
    with pytest.raises(app.SimulationError, match="outside"):
        app.analyze_payload(dict(weapon=weapon["path"], disposition=1.2, stats=old, profile="fast"))
    projected = _engine_request(dict(weapon=weapon["path"], disposition=1.2, sourceDisposition=1.45, stats=old, profile="fast"))
    plain = _engine_request(dict(weapon=weapon["path"], disposition=1.2, stats=new, profile="fast"))
    assert "sourceDisposition" not in projected and projected["disposition"] == 1.2
    for a, b in zip(projected["stats"], plain["stats"]):
        assert (a["value"], a["low"], a["high"]) == pytest.approx((b["value"], b["low"], b["high"]))
    # Read at its own disposition already, a card passes through untouched.
    same = _engine_request(dict(weapon=weapon["path"], disposition=1.2, sourceDisposition=1.2, stats=new, profile="fast"))
    assert [s["value"] for s in same["stats"]] == [s["value"] for s in new]


def test_riven_template_dispositions_follow():
    rows = [r for t in app.EXPORTS["rivenTemplates"]["templates"] for r in t.get("dispositions") or () if r.get("attenuation")]
    assert rows and all(r["attenuation"] == pytest.approx(1.2) for r in rows)
