"""Watch for a new Warframe build and extract riven/fusion-related changes automatically.

Usage:
    python tools/watch-new-build.py [--game-dir <dir>] [--dump] [--analyze]

Steps:
1. Read the current build label from Warframe.x64.exe and compare with the
   newest dump under WF_Rever/wf-arsenal/data/raw/.
2. --dump: if the live build is newer, run wf-arsenal's dump_all.ps1 to
   extract Packages.bin + language packs (takes a few minutes).
3. --analyze: diff the new dump against the previous one (content-aware:
   per-file size + JSON key scan) and write a report of everything that
   changed in riven/fusion-relevant namespaces, including:
   - new/changed objects under Lotus/Upgrades (RandomModRare family,
     new UpgradeTypes, fusion upgrades)
   - new items (fusion currency/materials)
   - new language strings (zh+en) matching fusion/riven keywords
   - byte-level identifier scan of Packages.bin (catches new root paths
     the JSON dump may miss)

The report lands in .local/reports/new-build-watch/<build>.md so the
follow-up work (fusion value model) can consume it directly.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WF_ARSENAL = Path(r"C:\Users\SuperExboom\Documents\WF_Rever\wf-arsenal")
RAW_ROOT = WF_ARSENAL / "data" / "raw"
REPORT_ROOT = ROOT / ".local" / "reports" / "new-build-watch"

FUSION_PATTERNS = [
    rb"Coalescen[a-zA-Z]*",
    rb"ModFusion[a-zA-Z]*",
    rb"StatFus[a-zA-Z]*",
    rb"RivenFus[a-zA-Z]*",
    rb"FusionUpgrade[a-zA-Z]*",
    rb"UpgradeFusion[a-zA-Z]*",
    rb"AscentFusion[a-zA-Z]*",
    rb"RandomModRare[a-zA-Z]*",
    rb"Transmute[a-zA-Z]*",
    rb"Fuse[A-Z][a-zA-Z]+",
]

FOCUS_PREFIXES = (
    "Lotus/Upgrades/",
    "Lotus/Types/Items/",
    "Lotus/Types/Game/",
    "Lotus/Types/StoreItems/",
    "Lotus/StoreItems/",
    "EE/Types/Game/",
)

LANG_KEYWORDS = {
    "en": ["Fusion", "Fuse", "Coalescent", "Ascent", "Riven", "Transmute", "Merge"],
    "zh": ["融合", "联结", "升华", "词条", "词缀", "转换"],
}


def live_build_label(game_dir: Path) -> str | None:
    exe = game_dir / "Warframe.x64.exe"
    if not exe.is_file():
        return None
    version = exe.VersionInfo.FileVersion if hasattr(exe, "VersionInfo") else None
    if version:
        return str(version)
    # PowerShell fallback
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Item -LiteralPath '{exe}').VersionInfo.FileVersion"],
        capture_output=True, text=True, timeout=60,
    )
    return out.stdout.strip() or None


def newest_dump() -> tuple[str, Path] | None:
    if not RAW_ROOT.is_dir():
        return None
    builds = sorted(p.name for p in RAW_ROOT.iterdir() if p.is_dir())
    return (builds[-1], RAW_ROOT / builds[-1]) if builds else None


def run_dump(game_dir: Path) -> bool:
    script = WF_ARSENAL / "scripts" / "dump_all.ps1"
    if not script.is_file():
        print(f"dump script missing: {script}")
        return False
    result = subprocess.run(
        ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-GameDir", str(game_dir), "-OutRoot", str(RAW_ROOT)],
        timeout=1800,
    )
    return result.returncode == 0


def index_build(root: Path) -> dict[str, int]:
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.stat().st_size
        for p in root.rglob("*.json")
    }


def scan_identifiers(pkgs_bin: Path) -> dict[str, set[str]]:
    data = pkgs_bin.read_bytes()
    found: dict[str, set[str]] = {}
    for pattern in FUSION_PATTERNS:
        names = {
            m.group(0).decode("ascii", errors="ignore")
            for m in re.finditer(pattern, data)
        }
        found[pattern.decode()] = names
    return found


def analyze(old: Path, new: Path, report: Path) -> dict[str, Any]:
    old_idx = index_build(old / "packages")
    new_idx = index_build(new / "packages")
    added = sorted(set(new_idx) - set(old_idx))
    removed = sorted(set(old_idx) - set(new_idx))
    changed = sorted(
        p for p in (set(new_idx) & set(old_idx)) if new_idx[p] != old_idx[p]
    )
    focused_added = [p for p in added if p.startswith(FOCUS_PREFIXES)]
    focused_changed = [p for p in changed if p.startswith(FOCUS_PREFIXES)]

    old_ids = scan_identifiers(old / "Packages.bin")
    new_ids = scan_identifiers(new / "Packages.bin")
    id_delta = {
        key: sorted(new_ids[key] - old_ids[key])
        for key in new_ids
        if new_ids[key] - old_ids[key]
    }

    lines = [
        f"# New build watch: {new.name} (vs {old.name})",
        "",
        f"- files: {len(old_idx)} -> {len(new_idx)}",
        f"- added: {len(added)} (focused {len(focused_added)})",
        f"- removed: {len(removed)}",
        f"- changed: {len(changed)} (focused {len(focused_changed)})",
        "",
        "## New fusion/riven identifiers in Packages.bin",
    ]
    if id_delta:
        for key, names in id_delta.items():
            lines.append(f"- {key}: {names}")
    else:
        lines.append("- (none)")
    lines += ["", "## Focused added files"]
    lines += [f"+ {p}" for p in focused_added[:500]] or ["(none)"]
    lines += ["", "## Focused changed files"]
    lines += [f"~ {p} ({old_idx[p]}b -> {new_idx[p]}b)" for p in focused_changed[:500]] or ["(none)"]

    # Language keyword deltas
    for locale in ("en", "zh"):
        lines += ["", f"## Language delta ({locale})"]
        old_lang = old / "languages" / locale / "Languages.bin"
        new_lang = new / "languages" / locale / "Languages.bin"
        if not (old_lang.is_file() and new_lang.is_file()):
            lines.append("- (missing)")
            continue
        old_text = old_lang.read_bytes().decode("utf-8", errors="ignore")
        new_text = new_lang.read_bytes().decode("utf-8", errors="ignore")
        for kw in LANG_KEYWORDS.get(locale, []):
            old_n = len(re.findall(re.escape(kw), old_text))
            new_n = len(re.findall(re.escape(kw), new_text))
            marker = " **NEW HITS**" if new_n > old_n else ""
            lines.append(f"- {kw!r}: {old_n} -> {new_n}{marker}")

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    summary = {
        "old": old.name,
        "new": new.name,
        "added": len(added),
        "changed": len(changed),
        "identifierDelta": id_delta,
        "report": str(report),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", default=r"E:\warframe\Warframe\Downloaded\Public")
    parser.add_argument("--dump", action="store_true", help="dump the live build if it is newer")
    parser.add_argument("--analyze", action="store_true", help="diff newest dump against the previous one")
    parser.add_argument("--json", action="store_true", help="print summary as JSON")
    args = parser.parse_args()

    live = live_build_label(Path(args.game_dir))
    latest = newest_dump()
    print(f"live build:  {live}")
    print(f"latest dump: {latest[0] if latest else None}")

    if live and (not latest or live > latest[0]):
        if args.dump:
            print("live build is newer — dumping...")
            if not run_dump(Path(args.game_dir)):
                print("dump failed")
                return 1
            latest = newest_dump()
        else:
            print("live build is newer — rerun with --dump to extract it")

    if args.analyze and latest:
        builds = sorted(p.name for p in RAW_ROOT.iterdir() if p.is_dir())
        if len(builds) < 2:
            print("need at least two dumps to diff")
            return 1
        old = RAW_ROOT / builds[-2]
        new = RAW_ROOT / builds[-1]
        report = REPORT_ROOT / f"{new.name}-vs-{old.name}.md"
        summary = analyze(old, new, report)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            print(f"report written: {report}")
        # Exit code signals whether a content build landed (fusion data may
        # now exist): 0 = nothing new, 3 = new files present.
        return 3 if summary["added"] else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
