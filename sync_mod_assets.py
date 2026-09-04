from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from data_sources import export_dir as active_export_dir

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = active_export_dir(ROOT)
OUTPUT_DIR = ROOT / "frontend" / "assets" / "mods"
ASSET_ROOT = ROOT / "frontend" / "assets"
RIVEN_SLOTS = {"primary", "secondary", "melee"}
FRAME_PARTS = (
    "Background",
    "CornerLights",
    "FrameBottom",
    "FrameTop",
    "LowerTab",
    "SideLight",
    "TopRightBacker",
)
RANK_PARTS = ("RankCompleteLine.png", "RankSlotActive.png", "RankSlotEmpty.png")


def _args() -> argparse.Namespace:
    documents = ROOT.parent
    parser = argparse.ArgumentParser(description="Copy the MOD art used by the offline optimizer")
    parser.add_argument("--export-dir", type=Path, default=EXPORT_DIR)
    parser.add_argument(
        "--rabbit-root",
        type=Path,
        default=documents / "\u9ed1\u732b4.0-5.0",
        help="WarframeRabbit checkout containing dist/WRData",
    )
    parser.add_argument(
        "--companion-mods",
        type=Path,
        default=(
            documents
            / "WF_Rever"
            / "warframe-companion-5.3.5.0"
            / "work"
            / "apk"
            / "base"
            / "assets"
            / "Resources"
            / "common"
            / "mods"
        ),
        help="Extracted official Companion common/mods directory",
    )
    parser.add_argument(
        "--warframe-items",
        type=Path,
        default=(
            documents
            / "WF_Rever"
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-items"
            / "data"
        ),
        help="Local warframe-items data directory used only for missing art",
    )
    parser.add_argument(
        "--warframe-items-img",
        type=Path,
        default=(
            documents
            / "WF_Rever"
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-items"
            / "data"
            / "img"
        ),
        help="Local warframe-items transparent arcane icon directory",
    )
    parser.add_argument(
        "--i18n",
        type=Path,
        default=(
            documents
            / "WF_Rever"
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-items"
            / "data"
            / "json"
            / "i18n.json"
        ),
        help="warframe-items i18n.json with per-language levelStats",
    )
    parser.add_argument(
        "--lang",
        type=Path,
        default=(
            documents
            / "WF_Rever"
            / "research"
            / "wf-arsenal-external-sources"
            / "work"
            / "warframe-languages-bin-data"
            / "zh.json"
        ),
        help="Official Languages.bin dump (zh) for set-bonus and condition text",
    )
    parser.add_argument(
        "--modframe-root",
        type=Path,
        default=documents / "\u9ed1\u732b4.0-5.0" / "feature" / "local" / "assets" / "modframe",
        help="Compact MOD frame layer library (Amalgam/Galvanized pieces)",
    )
    parser.add_argument("--stances", type=Path, default=ROOT / "data" / "stances.json")
    parser.add_argument("--utility-mods", type=Path, default=ROOT / "data" / "utility_mods.json")
    parser.add_argument("--arcanes", type=Path, default=EXPORT_DIR / "arcanes.json")
    return parser.parse_args()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# Set-shell localization: modSet id -> language keys carrying the set name and
# bonus description template (|STAT1| style placeholders stay for the UI).
_SET_TEXT_KEYS: dict[str, list[str]] = {
    "AmarSetMod": ["AmarSetBonus", "AmarSetModName"],
    "AshenSetMod": ["AshenSetModName"],
    "AugurSetMod": ["WarframeAugurSetDesc", "AugurSetModName"],
    "BonebladeSetMod": ["BonebladeSetDesc", "BonebladeSetModName"],
    "BorealSetMod": ["BorealSetBonus", "BorealSetModName"],
    "FemurSetMod": ["FemurSetModName"],
    "GladiatorSetMod": ["WarframeGladiatorSetDesc", "MeleeGladiatorSetModName"],
    "HawkSetMod": ["HawkSetPassiveDesc", "HawkSetModName"],
    "HunterSetMod": ["WarframeHunterSetDesc", "HunterSetModName"],
    "MechaSetMod": ["MechaModSetBonus", "MechaSetModName"],
    "NiraSetMod": ["NiraSetBonus", "NiraSetModName"],
    "RaptorSetMod": ["RaptorSetModPassiveDesc", "RaptorSetModName"],
    "SacrificeSetMod": ["SacrificeSetModName"],
    "SpiderSetMod": ["SpiderSetModPassiveDesc", "SpiderSetBonus"],
    "StrainSetMod": ["StrainModSetBonus", "StrainSetModName"],
    "SynthSetMod": ["SynthModSetBonus", "SynthSetModName"],
    "TekSetMod": ["TekModSetBonus", "TekSetModName"],
    "UmbraSetMod": ["WarframeUmbraModSetDesc", "UmbraSetModName"],
    "VigilanteSetMod": ["WarframeVigilanteSetDesc", "VigilanteSetModName"],
}


def _set_text(mod_set: str, lang: dict[str, str]) -> dict[str, str]:
    keys = _SET_TEXT_KEYS.get(mod_set, [])
    out: dict[str, str] = {}
    for key in keys:
        value = lang.get(f"/Lotus/Language/Upgrades/{key}") or lang.get(f"/Lotus/Language/Mods/{key}")
        if value:
            if key.endswith(("SetDesc", "SetBonus", "ModSetBonus", "PassiveDesc")):
                out.setdefault("setDesc", value)
            else:
                out.setdefault("setName", value)
    return out


def _set_stats(shell: dict[str, Any]) -> list[dict[str, Any]]:
    """Numeric summary of a set shell for placeholder substitution.

    Collects per-tier effect values (valuePerRank), stack caps and durations so
    the UI can replace |STAT1| / |STAT2| / |val| style placeholders with real
    numbers straight from the reverse-engineered export.
    """
    stats: list[dict[str, Any]] = []
    for cond in shell.get("conditionalEffects") or ():
        if not isinstance(cond, dict):
            continue
        for effect in cond.get("effects") or ():
            if not isinstance(effect, dict):
                continue
            entry: dict[str, Any] = {
                "upgradeType": effect.get("upgradeType"),
                "value": effect.get("valuePerRank"),
            }
            if isinstance(cond.get("maxStacks"), int):
                entry["maxStacks"] = cond["maxStacks"]
            if isinstance(cond.get("duration"), (int, float)):
                entry["duration"] = cond["duration"]
            stats.append(entry)
    for effect in shell.get("effects") or ():
        if isinstance(effect, dict):
            stats.append({
                "upgradeType": effect.get("upgradeType"),
                "value": effect.get("valuePerRank"),
            })
    return stats


def _safe_source(root: Path, icon: str) -> tuple[Path, PurePosixPath]:
    relative = PurePosixPath(icon.lstrip("/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe icon path: {icon}")
    source = (root / Path(*relative.parts)).resolve()
    source.relative_to(root.resolve())
    return source, relative


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise ValueError(f"not a PNG file: {path}")
    return struct.unpack(">II", header[16:24])


def _copy_checked(source: Path, destination: Path, asset: str, manifest: list[dict[str, Any]]) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    source_size = _png_dimensions(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination_size = _png_dimensions(destination)
    if source_size != destination_size:
        raise ValueError(f"PNG dimensions changed while copying {source} -> {destination}")
    manifest.append(
        {
            "asset": asset,
            "width": destination_size[0],
            "height": destination_size[1],
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        }
    )


def _record_existing(path: Path, asset: str, manifest: list[dict[str, Any]]) -> None:
    """Record a checked-in auxiliary PNG without copying it over itself."""
    if not path.is_file():
        raise FileNotFoundError(path)
    width, height = _png_dimensions(path)
    manifest.append({
        "asset": asset,
        "width": width,
        "height": height,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })


def _rows(payload: Any) -> list[dict[str, Any]]:
    rows = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("expected array payload")
    return rows


def main() -> int:
    args = _args()
    rabbit_data = args.rabbit_root / "dist" / "WRData"
    metadata_path = rabbit_data / "data" / "v2_mods.json"
    art_root = rabbit_data / "icon" / "OfficialWarframe"
    complete_art_root = args.rabbit_root / "dist" / "icon" / "OfficialWarframe"
    items_path = args.warframe_items / "json" / "Mods.json"
    items_art = args.warframe_items / "img"
    for required in (
        metadata_path,
        art_root,
        args.companion_mods,
        items_path,
        items_art,
        args.export_dir,
        complete_art_root,
        args.stances,
        args.utility_mods,
        args.arcanes,
        args.modframe_root,
    ):
        if not required.exists():
            raise SystemExit(f"required source not found: {required}")

    sys.path.insert(0, str(ROOT / "vendor"))
    from wfarsenal.simulator import _mod_matches_weapon, load_exports

    exports = load_exports(args.export_dir)
    weapons = [weapon for weapon in exports["weapons"] if weapon.get("slot") in RIVEN_SLOTS]
    candidates = []
    for mod in exports["mods"]:
        path = str(mod.get("path") or "")
        support = mod.get("support") if isinstance(mod.get("support"), dict) else {}
        if (
            mod.get("selectable") is True
            and "/PvPMods/" not in path
            and any(_mod_matches_weapon(mod, weapon) for weapon in weapons)
        ):
            # Effect-level support is authoritative: Amalgam-style hybrids have
            # support.weapon=false at card level while carrying fully supported
            # weapon effects; unsupported riders become notes, not disqualifiers.
            effects = mod.get("effects") or []
            has_supported = any(
                isinstance(effect, dict)
                and effect.get("supported") is True
                and "weapon" in (effect.get("supportedBy") or [])
                for effect in effects
            )
            # 膛室家族（Primed Chamber / 蓄力装填）：首发伤害引擎已建模，快照
            # supported 标记滞后；与 app.py _manual_mod_rows 同一豁免口径。
            first_shot_chamber = any(
                isinstance(effect, dict)
                and str(effect.get("upgradeType") or "").upper() == "WEAPON_INIT_DAMAGE_MOD"
                for effect in effects
            )
            if support.get("weapon") or has_supported or mod.get("nameEn") == "Primed Reach" or first_shot_chamber:
                candidates.append(mod)

    metadata = {row.get("UniqueName"): row for row in _load(metadata_path)}
    item_metadata = {row.get("uniqueName"): row for row in _load(items_path)}
    i18n = _load(args.i18n) if args.i18n.exists() else {}
    lang = _load(args.lang) if args.lang.exists() else {}
    set_shells = {
        str(mod.get("modSet")): mod
        for mod in exports["mods"]
        if mod.get("modSet") and isinstance(mod.get("setPieces"), int)
    }
    art_output = OUTPUT_DIR / "art"
    frame_output = OUTPUT_DIR / "frame"
    art_output.mkdir(parents=True, exist_ok=True)
    frame_output.mkdir(parents=True, exist_ok=True)

    copied: set[PurePosixPath] = set()
    missing: list[dict[str, str]] = []
    index: dict[str, dict[str, Any]] = {}
    for mod in sorted(candidates, key=lambda row: str(row.get("path") or "")):
        path = str(mod["path"])
        icon = str((metadata.get(path) or {}).get("Icon") or "")
        asset = None
        art_source = None
        if icon:
            source, relative = _safe_source(art_root, icon)
            if source.is_file():
                destination = art_output / Path(*relative.parts)
                if relative not in copied:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
                    copied.add(relative)
                asset = "/assets/mods/art/" + relative.as_posix()
                art_source = "official-export"
        if asset is None:
            image_name = str((item_metadata.get(path) or {}).get("imageName") or "")
            if image_name:
                source, image_relative = _safe_source(items_art, image_name)
                relative = PurePosixPath("WarframeItems") / image_relative
                if source.is_file():
                    destination = art_output / Path(*relative.parts)
                    if relative not in copied:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, destination)
                        copied.add(relative)
                    asset = "/assets/mods/art/" + relative.as_posix()
                    art_source = "warframe-items"
        if asset is None:
            missing.append(
                {
                    "path": path,
                    "nameEn": str(mod.get("nameEn") or ""),
                    "reason": "no local official art mapping",
                }
            )
        rank = int(mod.get("maxRank") or 0)
        unsupported_notes = [
            f"{effect.get('upgradeType')}"
            for effect in (mod.get("effects") or [])
            if isinstance(effect, dict) and effect.get("supported") is False
        ]
        i18n_row = (i18n.get(path) or {}).get("zh") or {}
        level_stats = i18n_row.get("levelStats") or []
        effects_zh = level_stats[-1].get("stats") if level_stats else None
        condition_zh = None
        for cond in mod.get("conditionalEffects") or []:
            if not isinstance(cond, dict):
                continue
            tag = str(cond.get("conditionTag") or "")
            if tag and lang.get(tag):
                condition_zh = lang[tag]
                break
        record = {
            "art": asset,
            "artSource": art_source,
            "nameZh": mod.get("nameZh"),
            "nameEn": mod.get("nameEn"),
            "rarity": mod.get("rarity") or "COMMON",
            "polarity": mod.get("polarity"),
            "maxRank": rank,
            "drain": max(0, int(mod.get("baseDrain") or 0) + rank),
            "description": str((metadata.get(path) or {}).get("Description") or ""),
            "effectsZh": effects_zh,
            "effectsZhByRank": [row.get("stats") or [] for row in level_stats] or None,
            "conditionZh": condition_zh,
            "unsupportedNotes": unsupported_notes or None,
        }
        mod_set = str(mod.get("modSet") or "")
        if mod_set:
            record.update(_set_text(mod_set, lang))
            shell = set_shells.get(mod_set) or {}
            if isinstance(shell.get("setPieces"), int):
                record["setMaxPieces"] = shell["setPieces"]
                stats = _set_stats(shell)
                if stats:
                    record["setStats"] = stats
        index[path] = record

    frame_index: dict[str, dict[str, str]] = {}
    for rarity, stem in {
        "COMMON": "Bronze",
        "UNCOMMON": "Silver",
        "RARE": "Gold",
        "LEGENDARY": "Legendary",
    }.items():
        frame_index[rarity] = {}
        for part in FRAME_PARTS:
            name = f"{stem}{part}.png"
            shutil.copy2(args.companion_mods / name, frame_output / name)
            frame_index[rarity][part[0].lower() + part[1:]] = f"/assets/mods/frame/{name}"

    # The official Companion client composes Rivens from Omega frame pieces,
    # the Legendary background, and two Riven-specific tabs.
    frame_index["RIVEN"] = {}
    for key, name in {
        "background": "LegendaryBackground.png",
        "cornerLights": "OmegaCornerLights.png",
        "equippedLight": "OmegaEquippedLight.png",
        "frameBottom": "OmegaFrameBottom.png",
        "frameTop": "OmegaFrameTop.png",
        "lowerTab": "RivenLowerTab.png",
        "sideLight": "OmegaSideLight.png",
        "topRightBacker": "RivenTopRightBacker.png",
    }.items():
        shutil.copy2(args.companion_mods / name, frame_output / name)
        frame_index["RIVEN"][key] = f"/assets/mods/frame/{name}"
    riven_art = art_root / "Lotus" / "Interface" / "Cards" / "Images" / "OmegaMod.png"
    shutil.copy2(riven_art, frame_output / "OmegaMod.png")
    frame_index["RIVEN"]["art"] = "/assets/mods/frame/OmegaMod.png"

    # Amalgam / Galvanized hybrids keep their proprietary frame art (Overframe
    # parity): own top/bottom pieces, the Amalgam (or Legendary, for Galvanized)
    # background, and Legendary side lights + lower tab.
    variant_sources = (args.companion_mods, args.modframe_root)
    variant_frames = {
        "AMALGAM": {
            "background": "AmalgamBackground.png",
            "frameBottom": "AmalgamFrameBottom.png",
            "frameTop": "AmalgamFrameTop.png",
            "lowerTab": "LegendaryLowerTab.png",
            "sideLight": "LegendarySideLight.png",
        },
        "GALVANIZED": {
            "background": "LegendaryBackground.png",
            "frameBottom": "GalvanizedFrameBottom.png",
            "frameTop": "GalvanizedFrameTop.png",
            "lowerTab": "LegendaryLowerTab.png",
            "sideLight": "LegendarySideLight.png",
        },
    }
    for rarity, parts in variant_frames.items():
        frame_index[rarity] = {}
        for key, name in parts.items():
            source = next((root / name for root in variant_sources if (root / name).is_file()), None)
            if source is None:
                raise SystemExit(f"variant frame part not found: {name}")
            shutil.copy2(source, frame_output / name)
            frame_index[rarity][key] = f"/assets/mods/frame/{name}"

    # Archon MODs use Kahl's procedural Flash frame, not the ordinary
    # Legendary/Prime layer set. ``tools/bake_archon_frames.py`` freezes the
    # game's mask/normal-material chain into these transparent PNGs.
    archon_frames = {
        "background": "ArchonBackgroundHD.png",
        "cornerLights": "ArchonCornerLightsHD.png",
        "frameBottom": "ArchonFrameBottomHD.png",
        "frameTop": "ArchonFrameTopHD.png",
        "lowerTab": "ArchonLowerTabHD.png",
        "sideLight": "ArchonSideLightHD.png",
        "topRightBacker": "ArchonTopRightBackerHD.png",
        "rankActive": "ArchonRankSlotActiveHD.png",
        "rankEmpty": "ArchonRankSlotEmptyHD.png",
        "rankComplete": "ArchonRankCompleteLineHD.png",
    }
    frame_index["ARCHON"] = {}
    for key, name in archon_frames.items():
        source = frame_output / name
        if not source.is_file():
            raise SystemExit(f"baked Archon frame part not found: {source}")
        frame_index["ARCHON"][key] = f"/assets/mods/frame/{name}"

    rank_index = {}
    for name in RANK_PARTS:
        shutil.copy2(args.companion_mods / name, frame_output / name)
        rank_index[Path(name).stem] = f"/assets/mods/frame/{name}"

    auxiliary: list[dict[str, Any]] = []
    stance_payload = _load(args.stances)
    for stance in stance_payload.get("stances") or ():
        icon = str(stance.get("icon") or "")
        if not icon:
            continue
        source, relative = _safe_source(complete_art_root, icon)
        asset = "/assets/stances/art/" + relative.as_posix()
        _copy_checked(source, ASSET_ROOT / "stances" / "art" / Path(*relative.parts), asset, auxiliary)

    utility_payload = _load(args.utility_mods)
    export_mods = {str(mod.get("path") or ""): mod for mod in exports["mods"]}
    for mod in utility_payload.get("mods") or ():
        icon = str(mod.get("icon") or "")
        if not icon:
            continue
        source, relative = _safe_source(complete_art_root, icon)
        asset = "/assets/mods/art/" + relative.as_posix()
        destination = art_output / Path(*relative.parts)
        _copy_checked(source, destination, asset, auxiliary)
        # Dedicated-slot cards use the same game-card renderer.  Give them the
        # same official per-rank language data as ordinary cards.
        path = str(mod.get("path") or "")
        exported = export_mods.get(path, {})
        i18n_row = (i18n.get(path) or {}).get("zh") or {}
        level_stats = i18n_row.get("levelStats") or []
        index[path] = {
            "art": asset,
            "artSource": "official-export",
            "nameZh": mod.get("nameZh") or exported.get("nameZh"),
            "nameEn": mod.get("nameEn") or exported.get("nameEn"),
            "rarity": mod.get("rarity") or exported.get("rarity") or "COMMON",
            "polarity": mod.get("polarity") or exported.get("polarity"),
            "maxRank": int(mod.get("rank") if mod.get("rank") is not None else exported.get("maxRank") or 0),
            "drain": int(mod.get("drain") or 0),
            "description": str(mod.get("description") or (metadata.get(path) or {}).get("Description") or ""),
            "effectsZh": level_stats[-1].get("stats") if level_stats else None,
            "effectsZhByRank": [row.get("stats") or [] for row in level_stats] or None,
            "conditionZh": next((lang.get(str(cond.get("conditionTag") or "")) for cond in mod.get("conditionalEffects") or [] if isinstance(cond, dict) and lang.get(str(cond.get("conditionTag") or ""))), None),
            "unsupportedNotes": None,
        }

    arcane_names: dict[str, str] = {}
    for arcane in _rows(_load(args.arcanes)):
        support = arcane.get("support") if isinstance(arcane.get("support"), dict) else {}
        if not support.get("manualState") or not int(support.get("weaponEffects") or 0):
            continue
        icon = str(arcane.get("icon") or "")
        source, relative = _safe_source(complete_art_root, icon)
        name = relative.name
        transparent = args.warframe_items_img / name
        if transparent.is_file():
            source = transparent
        previous = arcane_names.setdefault(name, icon)
        if previous != icon:
            raise ValueError(f"colliding arcane icon basenames: {previous}, {icon}")
        asset = "/assets/arcanes/" + name
        _copy_checked(source, ASSET_ROOT / "arcanes" / name, asset, auxiliary)

    menu_root = rabbit_data / "icon" / "menu"
    polarity_root = args.companion_mods.parent / "icons" / "polarityIcons"
    special = {
        "/assets/game/slots/CosmeticEnhancer.png": complete_art_root
        / "Lotus/Interface/Icons/Store/CosmeticEnhancer.png",
        "/assets/game/slots/WeaponsArcaneSlotAdapter.png": complete_art_root
        / "Lotus/Interface/Icons/StoreIcons/MiscItems/WeaponsArcaneSlotAdapter.png",
        "/assets/game/slots/IconStance.png": menu_root / "IconStance.png",
        "/assets/game/slots/IconExilus.png": menu_root / "IconExilus.png",
        "/assets/game/slots/IconArcane.png": menu_root / "IconArcane.png",
        "/assets/game/formas/StanceForma.png": complete_art_root
        / "Lotus/Interface/Icons/StoreIcons/Resources/CraftingComponents/StanceForma.png",
        "/assets/game/formas/UmbraForma.png": args.rabbit_root
        / "dist/icon/item/umbra-forma.png",
        "/assets/polarities/umbra.png": polarity_root / "PolarityUmbra.png",
        "/assets/polarities/aura.png": polarity_root / "PolarityAura.png",
    }
    for asset, source in special.items():
        destination = ROOT / "frontend" / asset.removeprefix("/")
        if source.resolve() == destination.resolve():
            _record_existing(destination, asset, auxiliary)
        else:
            _copy_checked(source, destination, asset, auxiliary)
    aura_marker = ROOT / "frontend" / "assets" / "game" / "slots" / "icon-aura.png"
    if aura_marker.is_file():
        _record_existing(aura_marker, "/assets/game/slots/icon-aura.png", auxiliary)
    # Overframe's exact empty-slot outline is not present in the reverse export;
    # keep the checked-in 422x273 outline in the same manifest as official art.
    _record_existing(
        ROOT / "frontend" / "assets" / "arcanes" / "NoArcaneIcon.png",
        "/assets/arcanes/NoArcaneIcon.png",
        auxiliary,
    )

    unique_auxiliary = {row["asset"]: row for row in auxiliary}
    auxiliary_rows = sorted(unique_auxiliary.values(), key=lambda row: row["asset"])
    auxiliary_payload = {
        "schemaVersion": 1,
        "counts": {
            "assets": len(auxiliary_rows),
            "stanceCards": sum(row["asset"].startswith("/assets/stances/") for row in auxiliary_rows),
            "utilityCards": sum(row["asset"].startswith("/assets/mods/art/") for row in auxiliary_rows),
            "arcaneIcons": sum(row["asset"].startswith("/assets/arcanes/") for row in auxiliary_rows),
        },
        "assets": auxiliary_rows,
        "missing": [
            {
                "asset": "ArcaneSlot.png",
                "reason": "no exact local source; WeaponsArcaneSlotAdapter is preserved under its real name",
            }
        ],
    }
    (ASSET_ROOT / "data-assets.json").write_text(
        json.dumps(auxiliary_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    payload = {
        "schemaVersion": 1,
        "buildLabel": exports["buildLabel"],
        "counts": {
            "eligibleMods": len(index),
            "mappedMods": len(index) - len(missing),
            "uniqueArtFiles": len(copied),
            "missingMods": len(missing),
            "effectTextZh": sum(1 for row in index.values() if row.get("effectsZh")),
            "conditionTextZh": sum(1 for row in index.values() if row.get("conditionZh")),
            "setTextZh": sum(1 for row in index.values() if row.get("setDesc") or row.get("setName")),
        },
        "rarityFrames": frame_index,
        "rankAssets": rank_index,
        "mods": index,
        "missing": missing,
    }
    (OUTPUT_DIR / "index.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["counts"], ensure_ascii=False))
    print(json.dumps(auxiliary_payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
