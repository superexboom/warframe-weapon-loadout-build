"""Catalog-wide local-vs-WFSim differential for guns: bare and a fixed 4-MOD build.

    python tools/wfsim_sweep.py --wfsim .local/wfsim-git --output DIR [--runs 200] [--only id,id]

Every WFSim gun with an exact local record (same internal path) runs in both
engines on the benchmark (Thrax Centurion Lv170 Steel Path, 30 s, no
headshots, emergent triggers, infinite ammo): the local manual simulation and
the WASM shipped in the given WFSim checkout. Incarnon weapons are left out
(local routes evolutions on its own; see compare_generated_builds for exact
routes), Kuva / Tenet / Coda weapons send the same valence (heat 60 %) to
both. Rows are sorted by |delta| into DIR/sweep.txt and DIR/sweep.json, with
both requests kept so any row can be replayed.

Known non-model differences are not filtered out: read
.local/wfsim-git/data/unmodelled/reasons.yaml and the comparison notes before
calling a row a local error.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUILDS = dict(rifle=["serration", "split_chamber", "vital_sense", "point_strike"],
              pistol=["hornet_strike", "barrel_diffusion", "primed_pistol_gambit", "target_cracker"],
              shotgun=["point_blank", "hells_chamber", "blunderbuss", "vicious_spread"])
BATCH_JS = r"""import fs from 'node:fs'; import path from 'node:path';
const [repo,input,output]=process.argv.slice(2);
const rel=JSON.parse(fs.readFileSync(path.join(repo,'site/release.json'),'utf8'));
const base=path.join(repo,'site/pkg');
const engine=new Function(fs.readFileSync(path.join(base,'wfsim_wasm.'+rel.wasm+'.js'),'utf8')+';return wasm_bindgen;')();
engine.initSync({module:fs.readFileSync(path.join(base,'wfsim_wasm_bg.'+rel.wasm+'.wasm'))});
const rows=JSON.parse(fs.readFileSync(input,'utf8'));
fs.writeFileSync(output,JSON.stringify(rows.map(([api,p])=>JSON.parse(engine.api(api,JSON.stringify(p))))));
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--wfsim", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    import app
    from tools.compare_archgun_board_builds import exact_record, registry
    from wfarsenal import parallel

    app._disable_analysis_statics_persistence()
    weapons = registry(args.wfsim / "data/weapons")
    mods = registry(args.wfsim / "data/mods")
    only = {x for x in args.only.split(",") if x}
    cases, calls = [], []
    skipped: dict[str, list[str]] = {}
    for wid, spec in sorted(weapons.items()):
        if only and wid not in only:
            continue
        pools = spec.get("mod_pools") or (weapons.get(spec.get("transform_group") or "") or {}).get("mod_pools") or []
        if "melee" in pools or not any(p in pools for p in ("rifle", "primary", "shotgun", "pistol", "secondary", "sniper", "bow")):
            continue
        try:
            rec = exact_record(spec, app.EXPORTS["weapons"])
        except ValueError:
            skipped.setdefault("no exact local record", []).append(wid)
            continue
        if rec.get("isIncarnon") or (rec.get("incarnon") or {}).get("tiers"):
            skipped.setdefault("incarnon", []).append(wid)
            continue
        if not (app.CATALOG_WEAPONS_BY_PATH.get(rec["path"]) or {}).get("available"):
            skipped.setdefault("local catalog unavailable", []).append(wid)
            continue
        kind = "shotgun" if "shotgun" in pools else "rifle" if any(p in pools for p in ("rifle", "primary", "sniper", "bow")) else "pistol"
        modes = rec.get("fireModes") or []
        alternate = spec.get("form") == "alt_fire" and not spec.get("default_form")
        if alternate:
            mode = next((i for i in range(1, len(modes))), None)
        else:
            direct = sum(float(x) for x in ((spec.get("attack") or {}).get("damage") or {}).values())
            mode = next((i for i, m in enumerate(modes)
                         if abs(sum(((m.get("damage") or {}).get("types") or {}).values()) - direct) < .5), 0)
        if mode is None:
            skipped.setdefault("no local alternate mode", []).append(wid)
            continue
        aiming = "sniper" in pools
        valence = wid.split("_")[0] in ("kuva", "tenet", "coda")
        wf_weapon, wf_mode = (spec["transform_group"], "alternate") if alternate else (wid, "base")
        for label, names in (("bare", []), ("build", BUILDS[kind])):
            names = [n for n in names if n in mods]
            local_mods = [dict(path=mods[n]["internal_name"],
                               rank=(app.MANUAL_MODS_BY_PATH.get(mods[n]["internal_name"]) or {}).get("maxRank") or 0, slot=i)
                          for i, n in enumerate(names)]
            payload = dict(weapon=rec["path"], fireMode=mode, mods=local_mods, arcanes=[], enemy=app._BENCHMARK_ENEMY_PATH,
                           level=170, steelPath=True, headshotChance=0., aiming=aiming, triggerPolicy="emergent",
                           slotPolarities=[None] * 8, combatState=dict(selfShieldBreakForced=False))
            if valence:
                payload.update(innateElement="DT_FIRE", innateElementValue=.6)
            request = dict(weapon=wf_weapon, mode=wf_mode, mods=names, arcane=[], evolutions=[], enemy="thrax_centurion",
                           level=170, steel_path=True, headshot_pct=0, aiming=aiming, duration=30., runs=args.runs,
                           seed=12648430, infinite_ammo=True, ammo_drops=False, eximus=False, assume_max=False,
                           player_at=[0, 0], target_at=[0, .5])
            if valence:
                request.update(valence_element="heat", valence_bonus=.6)
            try:
                result = app.simulate_manual_payload(payload)
                local = result["benchmarkTimeline"]["killsPerMinute"]
            except Exception as exc:  # noqa: BLE001 - a row, not a crash
                skipped.setdefault("local error", []).append(f"{wid} {label}: {str(exc)[:80]}")
                continue
            cases.append(dict(weapon=wid, name=rec.get("nameEn"), path=rec["path"], mode=mode, build=label, alternate=alternate,
                              local=local, localUnsupported=list(result.get("unsupported") or []),
                              wfsimUnmodelled=[(item.get("reason") if isinstance(item, dict) else str(item)[:60])
                                               for item in spec.get("unmodeled") or spec.get("unmodelled") or []],
                              payload=payload, request=request))
            calls.append(["/api/simulate", request])
    requests_path = args.output / "requests.json"
    responses_path = args.output / "responses.json"
    requests_path.write_text(json.dumps(calls), encoding="utf-8")
    batch = args.output / "batch.mjs"
    batch.write_text(BATCH_JS, encoding="utf-8")
    subprocess.run(["node", str(batch), str(args.wfsim), str(requests_path), str(responses_path)], check=True)
    rows = []
    for case, ref in zip(cases, json.loads(responses_path.read_text(encoding="utf-8")), strict=True):
        if case["alternate"] and "alt_fire" not in (ref.get("apl") or []):
            case["referenceError"] = "WFSim did not fire the alternate mode"
        elif not ref.get("ok", True) or not ref.get("score"):
            case["referenceError"] = str(ref)[:200]
        else:
            wfsim = ref["score"] * 60 / ref["duration"]
            case.update(wfsim=wfsim, wfsimSe=ref.get("score_se", 0) * 60 / ref["duration"],
                        delta=(case["local"] / wfsim - 1) * 100 if wfsim else None)
        rows.append(case)
    good = sorted((r for r in rows if r.get("delta") is not None), key=lambda r: -abs(r["delta"]))
    lines = [f"{r['weapon']:28} m{r['mode']} {r['build']:5} wfsim {r['wfsim']:9.4f} +-{(r['wfsimSe'] / r['wfsim'] * 100):4.1f}% "
             f"local {r['local']:9.4f} ({r['delta']:+7.1f}%)"
             + (f"  [wfsim: {' | '.join(map(str, r['wfsimUnmodelled']))}]" if r["wfsimUnmodelled"] else "")
             for r in good]
    values = [abs(r["delta"]) for r in good]
    if values:
        lines.append(f"cases {len(values)}  mean |delta| {statistics.mean(values):.2f}%  median {statistics.median(values):.2f}%  "
                     f"within 5% {sum(v <= 5 for v in values)}  over 20% {sum(v > 20 for v in values)}")
    for reason, items in skipped.items():
        lines.append(f"skipped ({reason}): {len(items)}")
    lines.extend(f"reference error {r['weapon']} {r['build']}: {r['referenceError']}" for r in rows if r.get("referenceError"))
    (args.output / "sweep.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (args.output / "sweep.json").write_text(json.dumps(dict(
        wfsimCommit=subprocess.check_output(["git", "-C", str(args.wfsim), "rev-parse", "HEAD"], text=True).strip(),
        release=json.loads((args.wfsim / "site/release.json").read_text(encoding="utf-8")),
        localInputFingerprint=app._analysis_inputs_fingerprint(), cases=rows, skipped=skipped),
        ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines[-12:]))
    parallel.shutdown_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
