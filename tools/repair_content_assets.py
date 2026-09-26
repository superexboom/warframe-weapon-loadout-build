"""Repair catalog card art/layers and rank text from local official assets.

Only missing assets and the selected metadata are written. Original RGB and
alpha channels are preserved; PNG alpha is the game's foreground mask.
"""

from __future__ import annotations
import argparse, hashlib, json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
from split_mod_art import split_one
from wfarsenal.packages import PackageIndex


def load(p):
    return json.loads(p.read_text(encoding="utf-8-sig"))


def write(p, d):
    p.write_text(
        json.dumps(d, ensure_ascii=False, indent=1) + chr(10),
        encoding="utf-8",
        newline=chr(10),
    )


def safe(root, path):
    p = (root / str(path).lstrip("/")).resolve()
    p.relative_to(root.resolve())
    return p


def repair(root, export, official, items, packages):
    index_path = root / "frontend/assets/mods/index.json"
    index = load(index_path)
    mods_path = export / "mods.json"
    mods = load(mods_path)
    arcanes_path = export / "arcanes.json"
    arcanes = load(arcanes_path)
    i18n_path = items / "json/i18n.json"
    i18n = load(i18n_path)
    item_mods = {r["uniqueName"]: r for r in load(items / "json/Mods.json")}
    item_arcanes = {r["uniqueName"]: r for r in load(items / "json/Arcanes.json")}
    pkg = PackageIndex(packages)
    # JSON snapshots have resolved icon fields on parent records. The parent
    # map can be supplied beside packages (new snapshots), otherwise use the
    # game's known same-name Primed/base mod inheritance via item metadata.
    parents = packages.parent / "parents.json"
    if parents.is_file():
        pkg.parents = load(parents)
    report = {
        "arcaneIconsAdded": 0,
        "arcaneDescriptions": 0,
        "archwingMods": 0,
        "modIconsAdded": 0,
        "layersAdded": 0,
        "missing": [],
    }
    for arcane in arcanes["data"]:
        icon = str(arcane.get("icon") or "")
        if "/Arcanes/" in icon:
            dest = root / "frontend/assets/arcanes" / Path(icon).name
            if not dest.is_file():
                source = safe(official, icon)
                if source.is_file():
                    shutil.copy2(source, dest)
                    report["arcaneIconsAdded"] += 1
                else:
                    report["missing"].append(
                        {"kind": "arcane-icon", "path": arcane["path"], "icon": icon}
                    )
        path = arcane["path"]
        item = item_arcanes.get(path, {})
        zh = i18n.get(path, {}).get("zh", {})
        levels = zh.get("levelStats") or []
        if levels and all(r.get("stats") for r in levels):
            arcane["effectsZhByRank"] = [r["stats"] for r in levels]
            arcane["effectsEnByRank"] = [r["stats"] for r in item.get("levelStats", [])]
            arcane["descriptionSource"] = {
                "kind": "frozen-official-localized-levelStats",
                "path": "warframe-items/data/json/i18n.json",
                "sha256": hashlib.sha256(i18n_path.read_bytes()).hexdigest(),
            }
            if item.get("type"):
                arcane["equipmentType"] = item["type"]
            if item.get("rarity"):
                arcane["rarity"] = item["rarity"].upper()
            report["arcaneDescriptions"] += 1
    # New build MODs whose compact export omitted Icon/description fields.
    for mod in mods["data"]:
        path = str(mod.get("path") or "")
        if not any(
            token in path
            for token in (
                "WeaponWeakpointCriticalChanceMod",
                "PlayerWeakpointCriticalChanceAuraMod",
            )
        ):
            continue
        item = item_mods.get(path, {})
        zh = i18n.get(path, {}).get("zh", {})
        image = str(item.get("imageName") or "")
        icon = str(mod.get("icon") or "")
        if not icon and image:
            family = (
                "Auras"
                if "/Aura/" in path
                else ("Pistol" if "/Pistol/" in path else "Rifle")
            )

            stem = Path(image).stem.replace("Mods", "")
            icon = f"/Lotus/Interface/Cards/Images/{family}/{stem}.png"
        if icon:
            dest = safe(root / "frontend/assets/mods/art", icon)
            if not dest.is_file():
                source = safe(official, icon)
                if not source.is_file():
                    source = (
                        ROOT.parent
                        / "黑猫4.0-5.0"
                        / "dist"
                        / "icon"
                        / "OfficialWarframe"
                        / str(icon).lstrip("/")
                    )
                if source.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
                    report["modIconsAdded"] += 1
            if dest.is_file():
                mod["icon"] = icon
        levels = zh.get("levelStats") or item.get("levelStats") or []
        mod["officialLocalization"] = {
            "name": zh.get("name") or item.get("name") or mod.get("nameEn"),
            "levelStats": levels,
            "source": "warframe-items/data/json/i18n.json",
        }
        entry = index["mods"].setdefault(path, {})
        entry.update(
            {
                "art": "/assets/mods/art/" + icon.lstrip("/") if icon else None,
                "artSource": "official-rgb-alpha" if icon else None,
                "nameZh": zh.get("name") or mod.get("nameZh"),
                "nameEn": mod.get("nameEn"),
                "rarity": mod.get("rarity"),
                "polarity": mod.get("polarity"),
                "maxRank": mod.get("maxRank"),
                "drain": int(mod.get("baseDrain") or 0) + int(mod.get("maxRank") or 0),
                "description": levels[-1].get("stats") if levels else [],
                "effectsZh": levels[-1].get("stats") if levels else None,
                "effectsZhByRank": [r.get("stats", []) for r in levels] or None,
                "textSource": "warframe-items/data/json/i18n.json",
            }
        )

    for mod in mods["data"]:
        if "/Archwing/" not in str(mod.get("compatibility", "")):
            continue
        path = mod["path"]
        item = item_mods.get(path, {})
        zh = i18n.get(path, {}).get("zh", {})
        icon = str(mod.get("icon") or pkg.resolve(path).get("Icon") or "")
        if not icon and item.get("imageName"):
            # Official item mapping supplies a concrete card image for records
            # such as Primed Dual Rounds whose export omitted inherited Icon.
            candidates = list(
                (official / "Lotus/Interface/Cards/Images").rglob(
                    Path(item["imageName"]).name
                )
            )
            if len(candidates) == 1:
                icon = "/" + candidates[0].relative_to(official).as_posix()
        if not icon:
            # Resolve actual parent chain from Packages.bin for legacy snapshots.
            if not pkg.parents:
                from wfarsenal.parenttable import iter_entities

                pkg.parents = {
                    e.path: e.parent
                    for e in iter_entities(packages.parent / "Packages.bin")
                }
                pkg._resolved.clear()
            icon = str(pkg.resolve(path).get("Icon") or "")
        if not icon:
            report["missing"].append({"kind": "mod-icon", "path": path})
            continue
        mod["icon"] = icon
        dest = safe(root / "frontend/assets/mods/art", icon)
        if not dest.is_file():
            source = safe(official, icon)
            if source.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
                report["modIconsAdded"] += 1
            else:
                report["missing"].append(
                    {"kind": "mod-art", "path": path, "icon": icon}
                )
                continue
        levels = zh.get("levelStats") or item.get("levelStats") or []
        record = index["mods"].setdefault(path, {})
        record.update(
            {
                "art": "/assets/mods/art/" + icon.lstrip("/"),
                "artSource": "official-rgb-alpha",
                "nameZh": mod.get("nameZh"),
                "nameEn": mod.get("nameEn"),
                "rarity": mod.get("rarity"),
                "polarity": mod.get("polarity"),
                "maxRank": mod.get("maxRank"),
                "drain": int(mod.get("baseDrain") or 0) + int(mod.get("maxRank") or 0),
                "description": zh.get("description") or item.get("description") or "",
                "effectsZh": levels[-1]["stats"] if levels else None,
                "effectsZhByRank": [r.get("stats", []) for r in levels] or None,
                "textSource": "frozen-official-localized-levelStats",
            }
        )
        report["archwingMods"] += 1
        if not levels:
            report["missing"].append({"kind": "mod-text", "path": path})
    # Repair every unpaired local card, not only the newly restored family.
    for category in ("mods", "stances"):
        for src in (root / "frontend/assets" / category / "art").rglob("*.png"):
            if src.stem.endswith((".bg", ".fg")):
                continue
            if (
                not src.with_suffix(".bg.jpg").is_file()
                or not src.with_suffix(".fg.png").is_file()
            ):
                changed, _ = split_one(src)
                report["layersAdded"] += int(changed)
    index["counts"].update(
        eligibleMods=len(index["mods"]),
        mappedMods=sum(bool(m.get("art")) for m in index["mods"].values()),
        effectTextZh=sum(bool(m.get("effectsZh")) for m in index["mods"].values()),
    )
    index["missing"] = [
        r
        for r in index.get("missing", [])
        if not index["mods"].get(r.get("path"), {}).get("art")
    ]
    index["counts"]["missingMods"] = len(index["missing"])
    write(index_path, index)
    write(mods_path, mods)
    write(arcanes_path, arcanes)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--official-art", type=Path, required=True)
    p.add_argument("--items", type=Path, required=True)
    p.add_argument("--packages", type=Path, required=True)
    p.add_argument("--export", type=Path, default=ROOT / "data/export/2026.08.13.13.24")
    p.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".local/reports/content-assets-repair.json",
    )
    a = p.parse_args()
    report = repair(ROOT, a.export, a.official_art, a.items, a.packages)
    a.report.parent.mkdir(parents=True, exist_ok=True)
    write(a.report, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
