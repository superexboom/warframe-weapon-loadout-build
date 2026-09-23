"""Collect the account inventory via the official companion protocol and
extract everything riven/fusion-related from it.

This reuses the existing login_capture infrastructure (official mobile-app
endpoints, the account's own session) — no hooks, no memory access, no
client modification. The game is launched through Steam by auto_collect,
the read-only inventory endpoint is queried once, and the game exits.

Usage:
    python tools/collect-riven-snapshot.py [--skip-collect]

Steps:
1. --skip-collect omitted: invoke the companion collector
   (login_capture.py --once inventory) to refresh output/inventory.json.
2. Parse the inventory and extract:
   - every Riven (RandomMod*) in RawUpgrades/Upgrades with its full
     UpgradeFingerprint (per-stat upgradeType/value/polarity);
   - fusion-related currencies/materials if present (MiscItems whose names
     match fusion keywords, new item paths);
   - a per-weapon-type summary (how many rivens per family).
3. Diff against the previous snapshot (.local/reports/riven-snapshots/)
   and report NEW items — the moment fusion lands, the fused riven's
     fingerprint and any new currency show up here.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPANION = Path(r"C:\Users\SuperExboom\Documents\WF_Rever\warframe-companion-5.3.5.0")
INVENTORY = COMPANION / "output" / "inventory.json"
SNAPSHOT_DIR = ROOT / ".local" / "reports" / "riven-snapshots"

FUSION_KEYWORDS = ("fusion", "fuse", "coalescent", "ascent", "riven")
RIVEN_RE = re.compile(r"/Lotus/Upgrades/Mods/(?:[^/]+/)*RandomMod", re.IGNORECASE)


def collect() -> bool:
    script = COMPANION / "scripts" / "login_capture.py"
    if not script.is_file():
        print(f"collector missing: {script}")
        return False
    result = subprocess.run(
        [sys.executable, str(script), "--once", "inventory"],
        cwd=str(COMPANION),
        timeout=900,
    )
    return result.returncode == 0


def parse_fingerprint(raw: str) -> dict | None:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def extract(inventory: dict) -> dict:
    rivens = []
    seen_ids: set[str] = set()
    for section in ("Upgrades", "RawUpgrades"):
        for item in inventory.get(section) or []:
            item_type = str(item.get("ItemType") or "")
            if not RIVEN_RE.search(item_type):
                continue
            item_id = ""
            raw_id = item.get("ItemId")
            if isinstance(raw_id, dict):
                item_id = str(raw_id.get("$oid") or "")
            key = item_id or f"{item_type}#{len(seen_ids)}"
            if key in seen_ids:
                continue
            seen_ids.add(key)
            fingerprint = parse_fingerprint(str(item.get("UpgradeFingerprint") or ""))
            rivens.append(
                {
                    "itemId": item_id,
                    "itemType": item_type,
                    "fingerprint": fingerprint,
                    "equipped": section == "Upgrades",
                }
            )
    # Fusion-relevant misc items: currencies/materials with fusion keywords.
    fusion_items = []
    for item in inventory.get("MiscItems") or []:
        item_type = str(item.get("ItemType") or "")
        if any(kw in item_type.lower() for kw in FUSION_KEYWORDS):
            fusion_items.append(item)
    # Any inventory top-level key that smells new/fusion-like.
    fusion_keys = [
        key for key in inventory
        if isinstance(key, str) and any(kw in key.lower() for kw in FUSION_KEYWORDS)
    ]
    return {
        "collectedAt": datetime.now(timezone.utc).isoformat(),
        "rivenCount": len(rivens),
        "rivens": rivens,
        "fusionItems": fusion_items,
        "fusionKeys": fusion_keys,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-collect", action="store_true",
                        help="parse the existing inventory.json without collecting")
    args = parser.parse_args()

    if not args.skip_collect:
        print("collecting inventory via companion API (launches the game)...")
        if not collect():
            print("collection failed — falling back to the existing snapshot")
    if not INVENTORY.is_file():
        print(f"no inventory snapshot at {INVENTORY}")
        return 1

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    snapshot = extract(inventory)

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SNAPSHOT_DIR / f"riven-snapshot-{stamp}.json"
    out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    # Diff against the newest previous snapshot.
    previous = sorted(
        p for p in SNAPSHOT_DIR.glob("riven-snapshot-*.json") if p != out
    )
    summary = {
        "rivens": snapshot["rivenCount"],
        "fusionItems": len(snapshot["fusionItems"]),
        "fusionKeys": snapshot["fusionKeys"],
        "snapshot": str(out),
    }
    if previous:
        try:
            old = json.loads(previous[-1].read_text(encoding="utf-8"))
            old_ids = {r["itemId"] for r in old.get("rivens") or []}
            new_rivens = [r for r in snapshot["rivens"] if r["itemId"] not in old_ids]
            old_fusion = {i.get("ItemType") for i in old.get("fusionItems") or []}
            new_fusion = [
                i for i in snapshot["fusionItems"]
                if i.get("ItemType") not in old_fusion
            ]
            summary["newRivens"] = len(new_rivens)
            summary["newFusionItems"] = new_fusion
            print(f"diff vs {previous[-1].name}: +{len(new_rivens)} rivens, "
                  f"+{len(new_fusion)} fusion items")
        except (OSError, json.JSONDecodeError) as exc:
            print(f"(diff skipped: {exc})")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
