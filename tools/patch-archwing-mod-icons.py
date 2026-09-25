"""Inject the Icon field into the archwing mods' export rows and copy
their card art from the 2D assets package into frontend/assets/mods/art/
(mirroring the game path, the convention the existing mod art follows)."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(r"C:\Users\SuperExboom\Documents\WF-Riven-Portable")
OLD = Path(r"C:\Users\SuperExboom\Documents\WF_Rever\wf-arsenal\data\raw\2026.08.19.11.06\packages")
PKG = Path(
    r"C:\Users\SuperExboom\Documents\黑猫4.0-5.0\dist"
    r"\warframe-2d-assets-20260816-build-2026.08.13.13.24"
    r"\WRData\icon\OfficialWarframe"
)
MODS_JSON = REPO / "data" / "export" / "2026.08.13.13.24" / "mods.json"
ART = REPO / "frontend" / "assets" / "mods" / "art"

payload = json.loads(MODS_JSON.read_text(encoding="utf-8"))
rows = payload["data"]

patched = 0
art_copied = 0
art_missing = []
for row in rows:
    compat = str(row.get("compatibility") or "")
    if "/Archwing/" not in compat:
        continue
    if row.get("icon"):
        continue
    # resolve from the raw dump
    rp = OLD / (str(row.get("path") or "").lstrip("/") + ".json")
    if not rp.is_file():
        continue
    try:
        raw = json.loads(rp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    icon = raw.get("Icon")
    if not icon:
        continue
    row["icon"] = icon
    patched += 1
    # copy the art
    src = PKG / str(icon).lstrip("/")
    if src.is_file():
        dest = ART / str(icon).lstrip("/")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copyfile(src, dest)
            art_copied += 1
    else:
        art_missing.append((row.get("nameEn"), icon))

payload["data"] = rows
tmp = MODS_JSON.with_suffix(".json.tmp")
tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
tmp.replace(MODS_JSON)
print(f"patched icon field: {patched} archwing mods")
print(f"art copied: {art_copied}")
print(f"art missing from package: {len(art_missing)}")
for name, icon in art_missing[:10]:
    print(f"  {name}: {icon}")
