"""Bot preset experiment: fixed viral, 50% weakpoint; trigger policy / infinite ammo variants.

Per (weapon, variant) in its own process: fast-profile analysis fills an in-memory
statics cache (timed = cold bake cost), then every card runs in ultra (timed =
per-request cost on a warm cache).
"""
import json, os, sys, time
from concurrent.futures import ProcessPoolExecutor, as_completed

ROOT = r"C:\Users\SuperExboom\Documents\WF-Riven-Portable"
WEAPONS = ["Torid", "Rubico Prime", "Dual Toxocyst", "Imperator Vandal", "Soma Prime", "Burston Prime"]
VARIANTS = {
    "A": dict(triggerPolicy="emergent", combatState={}),
    "B": dict(triggerPolicy="assumed_max", combatState={}),
    "C": dict(triggerPolicy="emergent", combatState={"infiniteAmmo": True}),
    "D": dict(triggerPolicy="assumed_max", combatState={"infiniteAmmo": True}),
}
CARDS = [("0", "1", "S"), ("2", "4", "S"), ("D", "1", "R"), ("W", "1")]


def run(weapon_name, variant):
    os.chdir(ROOT); sys.path.insert(0, ROOT)
    os.environ["WF_ANALYZER_SERIAL"] = "1"
    import app
    app._disable_analysis_statics_persistence()
    app.ANALYSIS_STATICS_CACHE.clear()
    w = next(x for x in app.CATALOG["weapons"] if x.get("nameEn") == weapon_name)
    wtype = app.optimizer._weapon_type(None, w)
    bases = app.RIVEN_BASE_VALUES[wtype]
    dispo = float(w.get("disposition") or 1.0)
    preset = VARIANTS[variant]

    def payload(codes, profile):
        n = len(codes); mult = 0.757525 if n == 3 else 1.0
        stats = [dict(code=c, value=round(bases[c] * dispo * mult, 1), negative=False) for c in codes]
        return dict(weapon=w["path"], disposition=dispo, stats=stats, profile=profile, headshotChance=0.5,
                    elementTarget="viral", scenario=dict(preset), _cacheScenario=True)

    out = dict(weapon=weapon_name, variant=variant, type=wtype, dispo=dispo, cards=[])
    t = time.perf_counter()
    r = app.analyze_payload(payload(CARDS[0], "fast"))
    out["fastSeconds"] = time.perf_counter() - t
    out["fastKpm"] = r["actual"]["objectiveScore"]
    for codes in CARDS:
        if any(c not in bases for c in codes):
            continue
        try:
            t = time.perf_counter()
            r = app.analyze_payload(payload(codes, "ultra"))
            dt = time.perf_counter() - t
        except Exception as exc:  # noqa: BLE001
            out["cards"].append(dict(codes=codes, error=str(exc)[:300])); continue
        out["cards"].append(dict(
            codes=codes, seconds=dt, gain=r["actualGain"],
            baseKpm=r["baseline"]["objectiveScore"], kpm=r["actual"]["objectiveScore"],
            details={d["code"]: d.get("delta") for d in r["details"]},
            recommended=r["recommendedPositive"], negative=r["recommendedNegative"],
            mods=[m.get("nameEn") or m.get("path") for m in (r["actual"].get("mods") or [])],
            damageTypes=sorted((r["actual"].get("damageTypes") or {}).keys()),
            unsupported=[u for u in r["unsupported"] if "ultra" in u or "element" in u]))
    return out


if __name__ == "__main__":
    dest = sys.argv[1]
    jobs = [(w, v) for w in WEAPONS for v in VARIANTS]
    with ProcessPoolExecutor(max_workers=8) as pool, open(dest, "w", encoding="utf-8") as fh:
        futures = {pool.submit(run, w, v): (w, v) for w, v in jobs}
        for f in as_completed(futures):
            try:
                row = f.result()
            except Exception as exc:  # noqa: BLE001
                row = dict(job=futures[f], error=repr(exc)[:500])
            fh.write(json.dumps(row, ensure_ascii=False) + "\n"); fh.flush()
            print(futures[f], "done", flush=True)
