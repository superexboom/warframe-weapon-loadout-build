"""Find the best Kitgun / Zaw assembly per Riven head for the Bot.

    python tools/build_modular_winners.py [--workers 12] [--verify 4]

One winner per Kitgun chamber and slot (primary and secondary carry the same
Riven at different dispositions) and per Zaw strike: 6 x 2 + 11 = 23. The
score is the best no-Riven KPM build at the Bot target (Lv170 Steel Path
benchmark enemy, 50% weak point):

1. screen every grip x loader (Kitgun, 100 per slot) or grip x link (Zaw, 160)
   with one fixed build, the full KPM build of the head's best bare assembly;
2. rebuild the best ``--verify`` screened assemblies with the full KPM build
   optimizer and keep the highest.

Output: data/export/<build>/modular_winners.json (schema 2), bundled into the
Bot by tools/sync_wfarsenal_component.ps1.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 2
WEAKPOINT_RATE = 0.5
LEVEL = 170
ZAW_BASE = "/Lotus/Weapons/Ostron/Melee/LotusModularWeapon"
KITGUN_PRIMARY_BASES = {  # chamber -> primary base class (WF_Rever precompute_modular_winners)
    "Vermisplicer": "Beam", "Gaze": "Beam", "Sporelacer": "Launcher",
    "Catchmoon": "Shotgun", "Tombfinger": "Sniper", "Rattleguts": "",
}
KITGUN_SECONDARY_BASES = {"Vermisplicer": "Beam", "Gaze": "Beam", "Sporelacer": "Shotgun", "Catchmoon": "Shotgun"}

_APP = None


def _app():
    global _APP
    if _APP is None:
        os.environ.setdefault("WF_ANALYZER_SERIAL", "1")
        sys.path[:0] = [str(ROOT), str(ROOT / "vendor")]
        import app  # noqa: PLC0415
        _APP = app
    return _APP


def kitgun_base(slot: str, chamber_name: str) -> str:
    if slot == "secondary":
        return "/Lotus/Weapons/SolarisUnited/Secondary/LotusModularSecondary" + KITGUN_SECONDARY_BASES.get(chamber_name, "")
    return "/Lotus/Weapons/SolarisUnited/Primary/LotusModularPrimary" + KITGUN_PRIMARY_BASES[chamber_name]


def heads(exports: dict[str, Any]) -> list[dict[str, Any]]:
    """Every Riven head with its candidate assemblies."""
    out = []
    kitguns = exports["kitguns"]
    clips = sorted(kitguns["clips"])
    for chamber, barrel in sorted(kitguns["barrels"].items()):
        for slot in ("primary", "secondary"):
            if not barrel.get(f"{slot}Modes"):
                continue
            grips = sorted(p for p, row in kitguns["handles"].items() if row.get("slot") == slot)
            disposition = barrel["omegaAttenuation"] if slot == "secondary" else (
                barrel.get("primaryOmegaAttenuation") or barrel["omegaAttenuation"])
            out.append(dict(family="kitgun", key=chamber, slot=slot, name=barrel, weapon=kitgun_base(slot, barrel["nameEn"]),
                            disposition=float(disposition),
                            assemblies=[[chamber, grip, clip] for grip, clip in itertools.product(grips, clips)]))
    zaws = exports["zaws"]
    for strike_path, strike in sorted(zaws["strikes"].items()):
        out.append(dict(family="zaw", key=strike["rivenPath"], slot="melee", name=strike, weapon=ZAW_BASE,
                        disposition=float(strike["omegaAttenuation"]),
                        assemblies=[[strike_path, grip, link] for grip, link in itertools.product(sorted(zaws["grips"]), sorted(zaws["links"]))]))
    return out


def _target() -> dict[str, Any]:
    app = _app()
    return dict(enemy=app._BENCHMARK_ENEMY_PATH, level=LEVEL, steelPath=True, headshotChance=WEAKPOINT_RATE)


def full_build(task: tuple[str, list[str]]) -> dict[str, Any]:
    """Best no-Riven KPM build of one assembly."""
    weapon, parts = task
    app = _app()
    try:
        result = app.build_weapon_payload(dict(weapon=weapon, kitgunParts=parts, fireMode=0, metric="killsPerMinute",
                                               profile="fast", **_target()))
    except Exception as exc:  # noqa: BLE001 - an assembly the engine cannot build loses
        return dict(parts=parts, kpm=float("-inf"), error=f"{type(exc).__name__}: {exc}"[:200])
    build = result["build"]
    return dict(parts=parts, kpm=float(build["objectiveScore"]),
                mods=[m["path"] for m in build["mods"]], modNames=[m.get("nameZh") or m.get("nameEn") for m in build["mods"]])


def screen(task: tuple[str, list[str], list[str]]) -> tuple[list[str], float]:
    """KPM of one assembly with a fixed build (stances left to the simulator)."""
    weapon, parts, mods = task
    app = _app()
    payload = dict(weapon=weapon, kitgunParts=parts, mods=[dict(path=p, slot=i) for i, p in enumerate(mods)], **_target())
    try:
        return parts, float(app.simulate_manual_payload(payload)["benchmarkTimeline"]["killsPerMinute"])
    except Exception:  # noqa: BLE001 - incompatible assembly / build
        return parts, float("-inf")


def _names(exports, family: str, parts: list[str]) -> list[dict[str, str]]:
    tables = (("barrels", "handles", "clips") if family == "kitgun" else ("strikes", "grips", "links"))
    rows = exports["kitguns" if family == "kitgun" else "zaws"]
    return [dict(path=p, nameEn=rows[t][p].get("nameEn", ""), nameZh=rows[t][p].get("nameZh", "")) for t, p in zip(tables, parts)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) * 3 // 4))
    parser.add_argument("--verify", type=int, default=4, help="screened assemblies per head to rebuild in full")
    parser.add_argument("--only", action="append", default=[], help="limit to heads whose English name matches")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    app = _app()
    exports = app.EXPORTS
    todo = [h for h in heads(exports) if not args.only or h["name"]["nameEn"] in args.only]
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        # 0. Bare screen: the strongest assembly with no mods seeds the build.
        bare = list(pool.map(screen, [(h["weapon"], a, []) for h in todo for a in h["assemblies"]], chunksize=8))
        cursor = 0
        for head in todo:
            rows = bare[cursor:cursor + len(head["assemblies"])]
            cursor += len(rows)
            head["seed"] = max(rows, key=lambda r: r[1])[0]
        seeds = list(pool.map(full_build, [(h["weapon"], h["seed"]) for h in todo]))
        print(f"seed builds done in {time.perf_counter() - started:.0f}s", flush=True)
        # 1. Screen every assembly with its head's seed build.
        tasks = [(h["weapon"], a, seed.get("mods") or []) for h, seed in zip(todo, seeds) for a in h["assemblies"]]
        screened = list(pool.map(screen, tasks, chunksize=8))
        cursor = 0
        verify = []
        for head, seed in zip(todo, seeds):
            rows = screened[cursor:cursor + len(head["assemblies"])]
            cursor += len(rows)
            ranked = [parts for parts, _ in sorted(rows, key=lambda r: -r[1])[:args.verify]]
            head["verify"] = ranked if head["seed"] in ranked else [*ranked, head["seed"]]
            verify += [(head["weapon"], parts) for parts in head["verify"]]
        print(f"screened {len(tasks)} assemblies in {time.perf_counter() - started:.0f}s", flush=True)
        # 2. Full builds of the finalists.
        builds = list(pool.map(full_build, verify))
    cursor = 0
    document: dict[str, Any] = dict(schemaVersion=SCHEMA_VERSION, buildLabel=exports.get("buildLabel"),
                                    target=dict(enemy=app._BENCHMARK_ENEMY_PATH, level=LEVEL, steelPath=True,
                                                weakpointRate=WEAKPOINT_RATE, metric="killsPerMinute", profile="fast"),
                                    method=dict(screen="seed build x every assembly", verified=args.verify),
                                    kitgun={}, zaw={}, aliases={})
    for head in todo:
        rows = builds[cursor:cursor + len(head["verify"])]
        cursor += len(rows)
        best = max(rows, key=lambda r: r["kpm"])
        if best["kpm"] == float("-inf"):
            raise SystemExit(f"no buildable assembly for {head['name']['nameEn']} {head['slot']}: {rows[0].get('error')}")
        candidate = dict(weapon=head["weapon"], slot=head["slot"], disposition=head["disposition"], parts=best["parts"],
                         partNames=_names(exports, head["family"], best["parts"]), kpm=round(best["kpm"], 6),
                         mods=best["modNames"], screened=len(head["assemblies"]), verified=len(head["verify"]))
        name = head["name"]
        entry = document[head["family"]].setdefault(head["key"], dict(nameEn=name.get("nameEn", ""), nameZh=name.get("nameZh", ""),
                                                                      candidates={}))
        entry["candidates"][head["slot"]] = candidate
        for alias in (head["key"], name.get("path"), name.get("nameEn"), name.get("nameZh")):
            if alias and str(alias).strip():
                document["aliases"][str(alias).strip().lower()] = head["key"]
        print(f"{head['family']:6s} {name['nameEn']:15s} {head['slot']:9s} kpm {best['kpm']:9.3f} "
              f"{' / '.join(p['nameEn'] for p in candidate['partNames'])}", flush=True)
    for family in ("kitgun", "zaw"):
        document[family] = dict(sorted(document[family].items()))
    document["aliases"] = dict(sorted(document["aliases"].items()))
    output = args.output or ROOT / "data/export" / str(exports.get("buildLabel")) / "modular_winners.json"
    output.write_text(json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {output} in {time.perf_counter() - started:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
