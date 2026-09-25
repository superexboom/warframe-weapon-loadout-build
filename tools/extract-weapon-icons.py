"""Extract the missing weapon icons from the official 2D assets package
(same build as the frozen export) into frontend/assets/weapons/.

Mapping: each weapon's StoreIcon path (from the weapon record's 'icon' field
in the export? or from the store item) → the package file. The package
mirrors the game path: Lotus/Interface/Icons/StoreIcons/<category>/<name>.png.

Strategy: for each of the 142 missing weapons, find its icon via
  1. the weapon's Icon/StoreIcon field from the raw dump (old dump resolve),
  2. fallback: search the package's Weapons/ dir by the internal basename.
Copy to frontend/assets/weapons/<InternalBasename>.png (the naming
convention the existing 679 files follow).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(r"C:\Users\SuperExboom\Documents\WF-Riven-Portable")
PKG = Path(
    r"C:\Users\SuperExboom\Documents\黑猫4.0-5.0\dist"
    r"\warframe-2d-assets-20260816-build-2026.08.13.13.24"
    r"\WRData\icon\OfficialWarframe"
)
OLD = Path(r"C:\Users\SuperExboom\Documents\WF_Rever\wf-arsenal\data\raw\2026.08.19.11.06\packages")
PKG_BIN = OLD.parent / "Packages.bin"
ASSETS = REPO / "frontend" / "assets" / "weapons"

sys.path.insert(0, str(REPO / "vendor"))
from wfarsenal.parenttable import iter_entities
from wfarsenal.packages import PackageIndex

parents = {e.path: e.parent for e in iter_entities(PKG_BIN)}
index = PackageIndex(OLD, parents=parents)

rows = json.loads((REPO / "data" / "export" / "2026.08.13.13.24" / "weapons.json").read_text(encoding="utf-8"))["data"]
existing = {p.stem for p in ASSETS.glob("*.png")}


def candidates(r):
    internal = str(r.get("path") or "").rsplit("/", 1)[-1]
    name = str(r.get("nameEn") or "")
    raw = [internal]
    if name:
        raw.extend([name.replace(" ", ""), name.replace(" ", "").replace("'", ""), name.replace(" ", "").replace("-", "")])
    seen = set()
    out = []
    for p in raw:
        fixed = re.sub(r"^MK1(?=[A-Z])", "Mk1", p)
        if fixed not in seen:
            seen.add(fixed)
            out.append(fixed)
    return out


missing = [r for r in rows if not any(c in existing for c in candidates(r))]
print(f"missing weapons: {len(missing)}")

# Build the package index: name -> path (basenames of all PNGs)
pkg_files = {}
for p in PKG.rglob("*.png"):
    pkg_files.setdefault(p.stem, p)
print(f"package PNGs: {len(pkg_files)}")

copied = 0
unresolved = []
for r in missing:
    internal = str(r.get("path") or "").rsplit("/", 1)[-1]
    # 1) resolve the weapon's Icon field from the raw dump (full game path)
    icon_path = None
    obj = index.resolve(str(r.get("path") or ""))
    if isinstance(obj, dict):
        for key in ("StoreIcon", "Icon", "Portrait"):
            v = obj.get(key)
            if isinstance(v, str) and v:
                icon_path = v
                break
    source = None
    if icon_path:
        # game path -> package relative
        rel = icon_path.lstrip("/")
        candidate = PKG / rel
        if candidate.is_file():
            source = candidate
        else:
            stem = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            source = pkg_files.get(stem)
    if source is None:
        # 2) fallback: internal basename in the package
        source = pkg_files.get(internal)
    if source is None:
        # 3) nameEn-based
        name = str(r.get("nameEn") or "")
        for pat in (name.replace(" ", ""), name.replace(" ", "").replace("&", ""), name.replace(" ", "").replace("-", "")):
            if pat and pat in pkg_files:
                source = pkg_files[pat]
                break
    if source is None:
        unresolved.append((str(r.get("nameEn") or ""), internal, icon_path))
        continue
    dest = ASSETS / f"{internal}.png"
    shutil.copyfile(source, dest)
    copied += 1

print(f"copied: {copied}")
print(f"unresolved: {len(unresolved)}")
for name, internal, icon in unresolved[:30]:
    print(f"  {name} (internal {internal}, icon field: {icon})")
