"""Extract and disassemble Luau scripts from Warframe's Font cache package —
the static reverse-engineering path for game mechanics that are not in the
data export (script-driven behaviors: Double Tap, embed conditions, alt-fire
unlocks, fusion handlers when they ship).

Provenance: the 'Font' package in Cache.Windows carries the compiled Luau
bytecode chunks (5300+ scripts). Warframe-Exporter-CLI --write-raw extracts
them by internal path; the .lua_B body is a Luau bytecode chunk loadable by
the nightcap_luau_dump disassembler (WF_Rever/research/nightcap-luau-dump).

Usage:
    python tools/luau-extract.py --list                       # all TOC names
    python tools/luau-extract.py --extract /Lotus/Scripts/WeaponAttachments/BioGrenade.lua
    python tools/luau-extract.py --extract ... --disassemble  # + run nightcap
    python tools/luau-extract.py --search BioGrenade          # find paths by keyword
    python tools/luau-extract.py --extract-dir /Lotus/Scripts/Mods --disassemble

Outputs land under .local/research/luau-raw (bytecode) and
.local/research/luau-disasm (disassembly, UTF-8).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_RAW = ROOT / ".local" / "research" / "luau-raw"
OUT_DISASM = ROOT / ".local" / "research" / "luau-disasm"

CLI = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\work\warframe-public-export-plus-gen"
    r"\extras\Warframe-Exporter-CLI_Windows.exe"
)
CACHE = Path(r"E:\warframe\Warframe\Downloaded\Public\Cache.Windows")
TOC = CACHE / "B.Font.toc"
DUMP = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\research\nightcap-luau-dump\build"
    r"\nightcap_luau_dump.exe"
)


def toc_names() -> list[str]:
    """Every .lua script name the Font TOC carries (basename form)."""
    data = TOC.read_bytes()
    names = sorted({m.group(0).decode("ascii") for m in re.finditer(rb"[A-Za-z0-9_/.-]{3,80}\.lua", data)})
    return names


def known_roots() -> list[str]:
    return [
        "/Lotus/Scripts/",
        "/Lotus/Scripts/Mods/",
        "/Lotus/Scripts/WeaponAttachments/",
        "/Lotus/Scripts/Libs/",
        "/Lotus/Scripts/Challenges/",
        "/Lotus/Scripts/Generators/",
        "/Lotus/Scripts/ChallengeRooms/",
        "/Lotus/Scripts/Venus/",
        "/Lotus/Upgrades/CosmeticEnhancers/Offensive/",
        "/Lotus/PowersuitAbilities/",
        # Script references in ability/weapon package records are resolved
        # relative to their owner package, not necessarily /Lotus/Scripts/.
        # Keep the known game families here so basename extraction remains
        # useful for newly introduced script-driven content.
        "/Lotus/Powersuits/Duelist/",
        "/Lotus/Powersuits/Duelist/Abilities/",
        "/Lotus/Weapons/Tenno/Bows/DuelistBow/",
        "/Lotus/Weapons/Tenno/Pistols/DuelistPistols/",
        "/Lotus/Weapons/Tenno/Pistols/DuelistPistols/Abilities/",
        "/Lotus/Characters/Tenno/Accessory/Ephemeras/DuelistSpiritEphemera/",
    ]


def extract(internal: str) -> Path | None:
    result = subprocess.run(
        [str(CLI), "--write-raw", "--game", "Warframe", "--cache-dir", str(CACHE),
         "--package", "Font", "--internal-path", internal, "--output-path", str(OUT_RAW)],
        capture_output=True, timeout=180,
    )
    if result.returncode != 0:
        return None
    # The exporter writes Debug/<internal path without leading slash>_B/_H.
    rel = internal.lstrip("/")
    body = OUT_RAW / "Debug" / (rel + "_B")
    return body if body.is_file() else None


def disassemble(body: Path) -> Path | None:
    if not DUMP.is_file():
        print(f"disassembler missing: {DUMP}", file=sys.stderr)
        return None
    out = OUT_DISASM / (body.name.removesuffix(".lua_B") + ".disasm.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    # The dumper writes wide-char (UTF-16) output; redirect to a file first
    # (preserves raw bytes) then convert, matching the proven manual flow.
    raw_out = out.with_suffix(".utf16.tmp")
    with raw_out.open("wb") as handle:
        result = subprocess.run(
            [str(DUMP), str(body)], stdout=handle, stderr=subprocess.DEVNULL, timeout=120
        )
    if result.returncode != 0:
        raw_out.unlink(missing_ok=True)
        return None
    raw = raw_out.read_bytes()
    # The dumper writes UTF-16-LE with a BOM (FF FE); handle both cases.
    if raw.startswith(b"\xff\xfe"):
        text = raw[2:].decode("utf-16-le", errors="ignore")
    elif len(raw) >= 2 and raw[1] == 0:
        text = raw.decode("utf-16-le", errors="ignore")
    else:
        text = raw.decode("utf-8", errors="ignore")
    out.write_text(text, encoding="utf-8")
    raw_out.unlink(missing_ok=True)
    return out


def try_resolve(script_name: str) -> list[str]:
    """Reconstruct candidate internal paths from a TOC basename."""
    if script_name.startswith("/"):
        return [script_name]
    base = script_name.rsplit("/", 1)[-1]
    return [root + base for root in known_roots()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list", action="store_true", help="print all TOC script names")
    group.add_argument("--search", metavar="KEYWORD", help="find scripts by keyword")
    group.add_argument("--extract", metavar="PATH", help="extract one script (internal path or basename)")
    group.add_argument("--extract-dir", metavar="PREFIX", help="extract every TOC script under a path prefix")
    parser.add_argument("--disassemble", action="store_true", help="also disassemble extracted bytecode")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    if args.list:
        for name in toc_names():
            print(name)
        return 0

    if args.search:
        kw = args.search.lower()
        matches = [n for n in toc_names() if kw in n.lower()]
        if args.json:
            print(json.dumps(matches))
        else:
            for m in matches:
                print(m)
        return 0

    if args.extract:
        candidates = try_resolve(args.extract)
        for candidate in candidates:
            body = extract(candidate)
            if body is None:
                continue
            print(f"extracted: {body}")
            if args.disassemble:
                dis = disassemble(body)
                if dis:
                    print(f"disassembled: {dis}")
            return 0
        print(f"not found in Font package: {args.extract}", file=sys.stderr)
        return 1

    if args.extract_dir:
        prefix = args.extract_dir.rstrip("/") + "/"
        names = [n for n in toc_names() if n.lower().startswith(prefix.lower())]
        # TOC names may be basenames; also try directory-style matching.
        ok = fail = 0
        report = []
        for name in names:
            for candidate in try_resolve(name):
                body = extract(candidate)
                if body is None:
                    continue
                ok += 1
                report.append(str(body))
                if args.disassemble:
                    disassemble(body)
                break
            else:
                fail += 1
        print(f"extracted {ok}, failed {fail}")
        if args.json:
            print(json.dumps(report))
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
