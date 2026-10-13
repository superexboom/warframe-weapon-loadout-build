"""Native apply_mods vs the Python reference on recorded real calls.

    python tools/verify_apply_mods.py capture <dir> [--shard i --shards n]
    python tools/verify_apply_mods.py verify <dir> [--variants] [--limit N]

``capture`` records apply_mods_spec inputs (weapon, effects, fire mode,
scenario) from build-page searches and manual simulations of every catalog
weapon, the Incarnon modes (constant and cycle), aimed guns and four Riven
analyses; at most 30 distinct calls per run, weapons stored once. Run shards
in parallel processes for speed.

``verify`` runs both implementations on each record (and with ``--variants``
on scenario variants: aim, live status counts, distance, Incarnon cycle,
heavy attack, Simulor orbs, no perfect charge) and reports every difference
(exact float bits, number types, key and attribute order). Use it after any
change to damage.apply_mods_spec or native/wfcore/src/mods.rs.
"""
from __future__ import annotations

import argparse
import collections
import glob
import hashlib
import json
import os
import pickle
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def capture(out_dir: Path, shard: int, shards: int) -> None:
    os.environ.setdefault("WF_ANALYSIS_STATICS_CACHE_PATH", tempfile.mkdtemp() + "/s.json")
    os.environ.update(WF_SEARCH_NO_DEADLINE="1", WF_ENGINE_WORKERS="1")
    sys.path.insert(0, str(ROOT))
    import app
    from wfarsenal import damage

    original = damage.apply_mods_spec
    weapons, records, seen = {}, [], set()
    state = {"count": 0, "kept": 0, "name": "", "cap": 30}

    def recording(weapon, effects, *, fire_mode=0, scenario=None):
        state["count"] += 1
        n = state["count"]
        if state["kept"] < state["cap"] and (n <= 15 or n % 7 == 0):
            effect_list = list(effects)
            skipped = list(getattr(effects, "skipped", ()))
            wkey = hashlib.blake2b(pickle.dumps(weapon, 5), digest_size=16).hexdigest()
            key = hashlib.blake2b(pickle.dumps((wkey, effect_list, skipped, fire_mode, scenario), 5)).digest()
            if key not in seen:
                seen.add(key)
                weapons.setdefault(wkey, weapon)
                records.append((state["name"], wkey, effect_list, skipped, fire_mode, scenario))
                state["kept"] += 1
            effects = damage.ModEffectList(effect_list, skipped=skipped)
        return original(weapon, effects, fire_mode=fire_mode, scenario=scenario)

    damage.apply_mods_spec = recording
    jobs = []
    for w in sorted(app.CATALOG["weapons"], key=lambda w: w["path"]):
        jobs.append((w, "build", {}))
        jobs.append((w, "sim", {}))
        for index, mode in enumerate(w.get("fireModes") or []):
            if mode.get("isIncarnonForm"):
                jobs.append((w, "build", {"fireMode": index}))
                jobs.append((w, "build", {"fireMode": index, "incarnonCycle": True}))
        if w.get("slot") in ("primary", "secondary"):
            jobs.append((w, "build", {"aiming": True}))
    by_name = {x.get("nameEn"): x for x in app.CATALOG["weapons"]}
    for name, family, codes in (("Lato", "pistol", "D,1"), ("Hek", "shotgun", "D,0"),
                                ("Soma Prime", "rifle", "0,1"), ("Nikana Prime", "melee", "K,0")):
        jobs.append((by_name[name], "analyze", {"family": family, "codes": codes.split(",")}))
    jobs = jobs[shard::shards]
    started = time.time()
    for i, (w, kind, extra) in enumerate(jobs):
        state.update(count=0, kept=0, name=f"{w.get('nameEn')} {kind} {json.dumps(extra)}",
                     cap=300 if kind == "analyze" else 30)
        try:
            if kind == "build":
                app.build_weapon_route({"weapon": w["path"], "mode": "auto", "profile": "fast", **extra})
            elif kind == "sim":
                app.simulate_manual_payload(dict(weapon=w["path"], mods=[], enemy=app._BENCHMARK_ENEMY_PATH,
                                                 level=170, steelPath=True))
            else:
                d = float(w["disposition"])
                bases = app.RIVEN_BASE_VALUES[extra["family"]]
                app.analyze_payload(dict(weapon=w["path"], disposition=d, profile="fast",
                                         stats=[dict(code=c, value=bases[c] * d, negative=False) for c in extra["codes"]]))
        except Exception as exc:  # an unavailable weapon or mode records nothing
            print("skip", w.get("nameEn"), kind, type(exc).__name__, str(exc)[:80], flush=True)
        if i % 50 == 0:
            print(f"shard {shard}: {i}/{len(jobs)} runs, {len(records)} calls, {time.time() - started:.0f}s", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"shard{shard}.pkl", "wb") as handle:
        pickle.dump({"weapons": weapons, "records": records}, handle, protocol=5)
    print(f"shard {shard}: {len(records)} calls, {len(weapons)} weapon records")


def _variants(scenario, enabled):
    yield "as recorded", scenario
    if not enabled:
        return
    state = dict(scenario.combat_state)
    yield "aim", replace(scenario, aiming=not scenario.aiming)
    for n in (0, 2, 5):
        if n != scenario.victim_status_count:
            yield f"{n} live statuses", replace(scenario, victim_status_count=n)
    yield "distance", replace(scenario, distance=25.0 if scenario.distance is None else None)
    yield "far", replace(scenario, distance=60.0)
    yield "cycle", replace(scenario, incarnon_cycle=not scenario.incarnon_cycle)
    yield "heavy", replace(scenario, heavy_attack=not scenario.heavy_attack)
    yield "orbs", replace(scenario, combat_state={**state, "orbPasses": 2, "orbStacks": 3, "orbSpecialShield": True})
    yield "one orb", replace(scenario, combat_state={**state, "orbPasses": 1})
    yield "no perfect charge", replace(scenario, combat_state={**state, "perfectCharge": False})


def verify(directory: Path, variants: bool, limit: int | None) -> int:
    sys.path.insert(0, str(ROOT / "vendor"))
    from wfarsenal import damage, mods_native

    if not mods_native.ENABLED:
        print("native apply_mods is not available (build it with tools/build_native.py)")
        return 2
    weapons, records = {}, []
    for path in sorted(glob.glob(str(directory / "*.pkl"))):
        with open(path, "rb") as handle:
            data = pickle.load(handle)
        weapons.update(data["weapons"])
        records.extend(data["records"])
    records = records[:limit] if limit else records
    mismatched, examples, errors = collections.Counter(), {}, collections.Counter()
    total = 0
    spent = {"reference": 0.0, "native": 0.0}
    for name, wkey, effects, skipped, fire_mode, scenario in records:
        weapon = weapons[wkey]
        for label, variant in _variants(scenario, variants):
            total += 1
            outcomes = {}
            for kind, fn in (("reference", damage._apply_mods_spec_py), ("native", damage.apply_mods_spec)):
                started = time.perf_counter()
                try:
                    outcomes[kind] = (fn(weapon, damage.ModEffectList(effects, skipped=skipped),
                                         fire_mode=fire_mode, scenario=variant), None)
                except Exception as exc:
                    outcomes[kind] = (None, f"{type(exc).__name__}: {exc}")
                spent[kind] += time.perf_counter() - started
            (ref, ref_error), (nat, nat_error) = outcomes["reference"], outcomes["native"]
            if ref_error or nat_error:
                if ref_error != nat_error:
                    mismatched["exception"] += 1
                    examples.setdefault("exception", (name, label, ref_error, nat_error))
                else:
                    errors[ref_error[:60]] += 1
                continue
            diff = mods_native.differences(ref, nat)
            if diff:
                key = diff[0][0].split("[")[0]
                mismatched[key] += 1
                examples.setdefault(key, (name, label, diff))
    print(f"{total} calls on {len(records)} records, {sum(mismatched.values())} differ; "
          f"reference {spent['reference'] * 1e6 / max(total, 1):.1f} us, native {spent['native'] * 1e6 / max(total, 1):.1f} us per call")
    if errors:
        print("raised identically:", dict(errors.most_common(5)))
    for key, count in mismatched.most_common(20):
        print(f"  {count:6d} {key}: {examples[key]}")
    return 1 if mismatched else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("dir", type=Path)
    cap.add_argument("--shard", type=int, default=0)
    cap.add_argument("--shards", type=int, default=1)
    ver = sub.add_parser("verify")
    ver.add_argument("dir", type=Path)
    ver.add_argument("--variants", action="store_true")
    ver.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.command == "capture":
        capture(args.dir, args.shard, args.shards)
        return 0
    return verify(args.dir, args.variants, args.limit)


if __name__ == "__main__":
    raise SystemExit(main())
