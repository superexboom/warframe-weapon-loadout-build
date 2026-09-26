from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app


def write_json(path, value):
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + chr(10),
        encoding="utf-8",
        newline=chr(10),
    )


def main():
    parser = argparse.ArgumentParser(
        description="Replay an exported build across explicit ADS, Archimedea and Incarnon-cycle contexts."
    )
    parser.add_argument("build", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=30.0)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error(
            "output directory must be empty; preserve previous experiment results"
        )
    args.output.mkdir(parents=True, exist_ok=True)
    saved = json.loads(args.build.read_text(encoding="utf-8-sig"))
    config = copy.deepcopy(saved.get("config", saved))
    if config.get("weaponArcane"):
        config["arcanes"] = [config["weaponArcane"]]
    config["triggerPolicy"] = "emergent"
    enhancements = config.get("enemyEnhancements") or {
        "eximus": bool(config.get("enemyEximus")),
        "empowered": bool(config.get("enemyEmpowered")),
        "playerCount": config.get("enemyPlayerCount", 1),
        "archimedea": bool(config.get("enemyArchimedea")),
    }
    if isinstance(config.get("formaSlots"), dict):
        config["slotPolarities"] = [config["formaSlots"].get(str(i)) for i in range(8)]
    app._disable_analysis_statics_persistence()
    rows = []
    cases = [
        (bool(enhancements.get("archimedea")), False, True),
        (False, False, True),
        (False, True, True),
        (False, False, False),
    ]
    for index, (arch, aim, cycle) in enumerate(dict.fromkeys(cases)):
        payload = copy.deepcopy(config)
        payload.update(enemyArchimedea=arch, aiming=aim, incarnonCycle=cycle)
        payload["enemyEnhancements"] = {**enhancements, "archimedea": arch}
        payload["benchmarkTarget"] = {
            "enemy": payload["enemy"],
            "level": payload.get("level", 1),
            "steelPath": bool(payload.get("steelPath")),
            "windowSeconds": args.seconds,
            "headshotChance": payload.get("headshotChance", 0),
            "enemyEnhancements": payload["enemyEnhancements"],
        }
        result = app.simulate_manual_payload(payload)
        replay = result["benchmarkTimeline"]
        write_json(args.output / f"case-{index}-request.json", payload)
        write_json(args.output / f"case-{index}-response.json", result)
        points = replay.get("points") or []
        rows.append(
            {
                "archimedea": arch,
                "aiming": aim,
                "cycle": cycle,
                "kpm": replay["killsPerMinute"],
                "ehp": replay["targetTotalEhp"],
                "shots": replay["shots"],
                "transforms": replay["transforms"],
                "heatMax": max((x["stacks"]["heat"] for x in points), default=0),
                "heatStripMax": max((x["heatArmourStrip"] for x in points), default=0),
                "syndicate": replay["syndicateEvents"],
                "unsupported": replay.get("unsupported"),
            }
        )
    write_json(
        args.output / "comparison.json",
        {
            "inputSha256": hashlib.sha256(args.build.read_bytes()).hexdigest(),
            "engineFingerprint": app._analysis_inputs_fingerprint(),
            "seconds": args.seconds,
            "cases": rows,
        },
    )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
