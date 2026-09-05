from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from data_sources import active_build, export_dir as active_export_dir, provenance_path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    build = active_build(ROOT)
    parser = argparse.ArgumentParser(description="Freeze Incarnon and trigger text from the international Languages.bin dump")
    parser.add_argument("--build", default=build)
    parser.add_argument("--export-dir", type=Path)
    parser.add_argument(
        "--localization",
        type=Path,
        required=True,
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    export_dir = args.export_dir or active_export_dir(ROOT, args.build)
    output = args.output or export_dir / "incarnon_strings.json"
    weapons_payload = json.loads((export_dir / "weapons.json").read_text(encoding="utf-8-sig"))
    if weapons_payload.get("buildLabel") != args.build:
        raise SystemExit(f"weapon export build mismatch: {weapons_payload.get('buildLabel')} != {args.build}")
    translations = json.loads(args.localization.read_text(encoding="utf-8-sig"))
    tags = {
            str(value)
            for weapon in weapons_payload["data"]
            for tier in (weapon.get("incarnon") or {}).get("tiers", [])
            for branch in tier.get("branches", [])
            for value in (
                branch.get("nameTag"),
                *(effect.get("conditionTag") for effect in branch.get("conditionalEffects", [])),
            )
            if value
        }
    for name in ("mods", "arcanes"):
        payload = json.loads((export_dir / f"{name}.json").read_text(encoding="utf-8-sig"))
        if payload.get("buildLabel") != args.build:
            raise SystemExit(f"{name} export build mismatch: {payload.get('buildLabel')} != {args.build}")
        for row in payload.get("data") or ():
            trigger = row.get("trigger") if isinstance(row.get("trigger"), dict) else {}
            if trigger.get("conditionTag"):
                tags.add(str(trigger["conditionTag"]))
            for conditional in row.get("conditionalEffects") or ():
                if isinstance(conditional, dict) and conditional.get("conditionTag"):
                    tags.add(str(conditional["conditionTag"]))
    tags = sorted(tags)
    missing = [tag for tag in tags if tag not in translations]
    output.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "gameBuild": args.build,
                "source": "international-client Languages.bin zh",
                "sourcePath": provenance_path(args.localization),
                "sourceSha256": hashlib.sha256(args.localization.read_bytes()).hexdigest(),
                "data": {tag: translations[tag] for tag in tags if tag in translations},
                "missingTags": missing,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {len(tags) - len(missing)} strings to {output} (missing: {len(missing)})")


if __name__ == "__main__":
    main()
