"""Compare data/mechanics/melee-mechanics.json stance combos with the wiki table.

data/stances.json (wiki) lists per stance combo the total multiplier, hit count
and duration at 1.0 attack speed. Combo kinds map to contexts:
Neutral = CC_GROUND, Forward = CC_GROUND_BRANCH_A, Forward Block =
CC_GROUND_BRANCH_B, Block = CC_GROUND_BRANCH_C.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from wfarsenal.melee_sequence import attack_hits  # noqa: E402

KIND = {"Neutral": "CC_GROUND", "Forward": "CC_GROUND_BRANCH_A",
        "Forward Block": "CC_GROUND_BRANCH_B", "Block": "CC_GROUND_BRANCH_C"}


def compare(mechanics, stances, weapons=()):
    rows = []
    for stance in stances["stances"]:
        tree = mechanics["trees"].get(stance["path"])
        # Slam events inside combos use the weapon's Slams[]; any weapon of the
        # stance's class stands in (the wiki table is per stance, not weapon).
        sample = next((w["path"] for w in weapons if stance["compatTag"] in (w.get("compatTags") or ())
                       and w["path"] in mechanics["weapons"]), None)
        slams = {row["event"]: row for row in (mechanics["weapons"][sample]["slams"] if sample else ())}
        for combo in stance["combos"]:
            attacks = (tree or {}).get("contexts", {}).get(KIND.get(combo["kind"], ""))
            if not attacks:
                rows.append(dict(stance=stance["nameEn"], kind=combo["kind"], status="no-context"))
                continue
            total = hits = duration = 0.0
            for path in attacks:
                attack = mechanics["attacks"][path]
                swings = attack_hits(attack, slams)
                total += sum(h["atten"] for h in swings)
                hits += len(swings)
                duration += attack["duration"] or 0.0
            rows.append(dict(
                stance=stance["nameEn"], kind=combo["kind"], status="ok",
                total=(round(total, 4), combo["totalMultiplier"]), hits=(int(hits), combo["hitCount"]),
                duration=(round(duration, 3), combo.get("duration")),
            ))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mechanics", type=Path, default=ROOT / "data/mechanics/melee-mechanics.json")
    parser.add_argument("--stances", type=Path, default=ROOT / "data/stances.json")
    parser.add_argument("--show", type=int, default=30)
    args = parser.parse_args()
    weapons = json.loads((ROOT / "data/export/2026.08.13.13.24/weapons.json").read_text(encoding="utf-8"))["data"]
    rows = compare(json.loads(args.mechanics.read_text(encoding="utf-8")),
                   json.loads(args.stances.read_text(encoding="utf-8")), weapons)
    counts = collections.Counter()
    bad = []
    for row in rows:
        if row["status"] != "ok":
            counts[row["status"]] += 1
            continue
        total_ok = abs(row["total"][0] - row["total"][1]) < 1e-6
        hits_ok = row["hits"][0] == row["hits"][1]
        counts[("total", total_ok)] += 1
        counts[("hits", hits_ok)] += 1
        ours, wiki = row["duration"]
        if wiki:
            counts[("duration within 10%", abs(ours / wiki - 1) <= 0.10)] += 1
        if not (total_ok and hits_ok):
            bad.append(row)
    for key, value in sorted(counts.items(), key=str):
        print(key, value)
    for row in bad[: args.show]:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
