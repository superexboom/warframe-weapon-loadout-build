"""Live build-page requests that a newer one replaced (2026-10-12).

The page re-solves on every edit and tags each request with
{liveChannel, liveSeq}. A request replaced while it queued for the engine
never starts (409 superseded), and a running optimizer search stops at its
next heartbeat instead of finishing for nobody.
"""
import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import app
from wfarsenal import search_session
from wfarsenal.search_session import CANCEL, SearchCancelled

BOLTOR = next(w for w in app.EXPORTS["weapons"] if w.get("nameEn") == "Boltor Prime")


def test_newer_sequence_supersedes_older():
    first = app._live_superseded({"liveChannel": "test:a", "liveSeq": 1})
    assert first() is False
    second = app._live_superseded({"liveChannel": "test:a", "liveSeq": 2})
    assert first() is True and second() is False
    late = app._live_superseded({"liveChannel": "test:a", "liveSeq": 1})
    assert late() is True and second() is False
    other = app._live_superseded({"liveChannel": "test:b", "liveSeq": 1})
    assert other() is False
    assert app._live_superseded({"liveSeq": 3}) is None
    assert app._live_superseded({"liveChannel": "x", "liveSeq": True}) is None


def test_heartbeat_stops_a_cancelled_search():
    token = CANCEL.set(lambda: True)
    try:
        with pytest.raises(SearchCancelled):
            search_session.heartbeat(1)
    finally:
        CANCEL.reset(token)
    search_session.heartbeat(1)  # no live request: never cancelled


def test_running_auto_build_stops_once_superseded():
    calls = {"n": 0}

    def superseded():
        calls["n"] += 1
        return calls["n"] > 3

    payload = dict(weapon=BOLTOR["path"], fireMode=0, mode="auto", mods=[], slotCount=8, level=160, profile="fast",
                   metric="sustainedDps", damageModel="panel", enemy=app._BENCHMARK_ENEMY_PATH)
    token = CANCEL.set(superseded)
    started = time.monotonic()
    try:
        with pytest.raises(SearchCancelled):
            app.build_weapon_payload(payload)
    finally:
        CANCEL.reset(token)
    assert time.monotonic() - started < 20
    assert not app.ANALYZE_LOCK.locked()


def _post(url, payload, out, key):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            out[key] = (response.status, json.load(response))
    except urllib.error.HTTPError as error:
        out[key] = (error.code, json.load(error))


def test_queued_request_replaced_by_a_newer_one_is_skipped():
    server = app.create_server(port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/api/simulate"
    base = dict(weapon=BOLTOR["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH, level=160, liveChannel="test:http")
    out = {}
    try:
        app.ANALYZE_LOCK.acquire()
        try:
            older = threading.Thread(target=_post, args=(url, dict(base, liveSeq=1), out, "older"))
            older.start()
            for _ in range(200):
                if app._LIVE_SEQ.get("test:http") == 1:
                    break
                time.sleep(0.02)
            newer = threading.Thread(target=_post, args=(url, dict(base, liveSeq=2), out, "newer"))
            newer.start()
            for _ in range(200):
                if app._LIVE_SEQ.get("test:http") == 2:
                    break
                time.sleep(0.02)
        finally:
            app.ANALYZE_LOCK.release()
        older.join(60)
        newer.join(60)
    finally:
        server.shutdown()
    assert out["older"][0] == 409 and out["older"][1]["error"]["code"] == "superseded"
    assert out["newer"][0] == 200 and out["newer"][1]["benchmarkTimeline"]["killsPerMinute"] > 0


def test_identical_build_requests_reuse_the_answer(monkeypatch):
    calls = []

    def build(payload, **_kwargs):
        calls.append(payload)
        return {"build": {"objectiveScore": 1.5, "mods": [{"path": "x"}]}}

    monkeypatch.setattr(app, "build_weapon_payload", build)
    monkeypatch.setattr(app, "_BUILD_RESULTS", app.OrderedDict())
    payload = {"weapon": BOLTOR["path"], "mode": "auto", "profile": "fast", "liveChannel": "p:build", "liveSeq": 1}
    first = app.build_weapon_route(payload)
    first["build"]["objectiveScore"] = 0  # callers may mutate their copy
    again = app.build_weapon_route(dict(payload, liveSeq=7))
    assert again == {"build": {"objectiveScore": 1.5, "mods": [{"path": "x"}]}} and len(calls) == 1
    app.build_weapon_route(dict(payload, profile="standard"))
    assert len(calls) == 2


def test_a_running_analysis_lets_a_waiting_build_request_in():
    from app import SEARCH_YIELD

    order = []
    app.ANALYZE_LOCK.acquire()  # the analysis, between two evaluations
    app._ANALYSIS_ACTIVE.set()
    token = SEARCH_YIELD.set(app._hand_engine_to_waiting)
    try:
        def build_page():
            with app._engine_lock():
                order.append("build page")

        waiting = threading.Thread(target=build_page)
        waiting.start()
        for _ in range(250):
            if app._ENGINE_WAITING:
                break
            time.sleep(0.02)
        with pytest.raises(app.SimulationError, match="正在计算其他请求"):
            with app._interactive_analysis_gate():
                pass  # a second analysis is refused even while the first hands over
        search_session.heartbeat(1)
        order.append("analysis resumed")
        waiting.join(10)
    finally:
        SEARCH_YIELD.reset(token)
        app._ANALYSIS_ACTIVE.clear()
        app.ANALYZE_LOCK.release()
    assert order == ["build page", "analysis resumed"]


def test_mod_gains_on_the_pool_match_serial(monkeypatch):
    mods = {}
    for row in app.EXPORTS["mods"]:
        mods.setdefault(row.get("nameEn"), row["path"])
    names = ["Serration", "Split Chamber", "Point Strike", "Vital Sense", "Infected Clip", "Cryo Rounds", "Heavy Caliber"]
    candidates = [mods[n] for n in ("Hammer Shot", "Hellfire", "Stormbringer", "Bladed Rounds", "Argon Scope", "Wildfire")]
    payload = dict(weapon=BOLTOR["path"], mods=[dict(path=mods[n], slot=i) for i, n in enumerate(names)], level=160,
                   enemy=app._BENCHMARK_ENEMY_PATH, metric="killsPerMinute", candidates=candidates, targetSlot=7)
    monkeypatch.setattr(app, "_MOD_GAINS_CACHE", {})
    pooled = app.mod_gains_payload(payload)
    monkeypatch.setattr(app, "_MOD_GAINS_CACHE", {})
    monkeypatch.setenv("WF_ANALYZER_SERIAL", "1")
    serial = app.mod_gains_payload(payload)
    assert pooled == serial
    assert sum(row["gainPercent"] is not None for row in pooled["gains"].values()) >= 5
