"""Build the unified Companion static catalog and copy missing companion assets.

Outputs:
  - data/mechanics/companions-catalog.json
  - frontend/assets/companions/** (clean 1:1 companion/claw portraits & missing mod/part icons)

Authoritative sources:
  1. Client Packages.bin_H (2026.10.28.09.54)
  2. Official DE localization tables (en.json / zh.json) + warframe-items Mods/Pets/Sentinels/i18n
  3. WF-Riven-Portable data/mechanics/sentinels.json & data/export/2026.08.13.13.24/{mods,weapons}.json
  4. wfsim-layout/data/{companions, companion_parts.yaml, companion_mods, weapons/beast_claws, mods/beast_claws}
  5. OfficialWarframe local icon export tree
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "tools"))

from build_mod_families import compute_mod_family, load_directory_hierarchy  # noqa: E402
from packages_bin import PackagesBin  # noqa: E402
from split_mod_art import split_one  # noqa: E402
from wfarsenal.ee import parse_ee  # noqa: E402
from wfarsenal.extract import _base_drain, _max_rank  # noqa: E402

SCHEMA_VERSION = 1

DEFAULT_PACKAGES = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\research\arbitration-arena-20261116\artifacts\original\Debug\Packages.bin_H"
)
DEFAULT_LANG_DIR = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\research\wf-arsenal-external-sources\work\warframe-languages-bin-data"
)
DEFAULT_ITEMS_DIR = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\research\wf-arsenal-external-sources\work\warframe-items\data"
)
DEFAULT_WFSIM_DATA = Path(r"C:\Users\SuperExboom\Documents\wfsim-layout\data")
DEFAULT_OFFICIAL_ICONS = Path(r"C:\Users\SuperExboom\Documents\黑猫4.0-5.0\dist\icon\OfficialWarframe")
DEFAULT_EXTRA_ICONS = Path(r"C:\Users\SuperExboom\Documents\黑猫4.0-5.0\.tmp\texture-test-icons")

EXPORT_BUILD = "2026.08.13.13.24"
PACKAGES_BUILD = "2026.10.28.09.54"

POLARITY_FROM_WFSIM = {
    "madurai": "AP_ATTACK",
    "vazarin": "AP_DEFENSE",
    "naramon": "AP_TACTIC",
    "penjaga": "AP_PRECEPT",
    "zenurik": "AP_POWER",
    "unairu": "AP_WARD",
    "umbra": "AP_UMBRA",
    "universal": None,
}
POLARITY_FROM_PKG = {
    "AP_ATTACK": "AP_ATTACK",
    "AP_DEFENSE": "AP_DEFENSE",
    "AP_TACTIC": "AP_TACTIC",
    "AP_PRECEPT": "AP_PRECEPT",
    "AP_PENJAGA": "AP_PRECEPT",
    "AP_POWER": "AP_POWER",
    "AP_WARD": "AP_WARD",
    "AP_UMBRA": "AP_UMBRA",
    "AP_ANY": "AP_ANY",
    "AP_UNIVERSAL": None,
    "None": None,
    "": None,
}

WFSIM_DAMAGE_MAP = {
    "impact": "DT_IMPACT",
    "puncture": "DT_PUNCTURE",
    "slash": "DT_SLASH",
    "heat": "DT_FIRE",
    "cold": "DT_FREEZE",
    "electricity": "DT_ELECTRICITY",
    "toxin": "DT_POISON",
    "blast": "DT_EXPLOSION",
    "radiation": "DT_RADIATION",
    "gas": "DT_GAS",
    "magnetic": "DT_MAGNETIC",
    "viral": "DT_VIRAL",
    "corrosive": "DT_CORROSIVE",
    "void": "DT_RADIANT",
    "tau": "DT_SENTIENT",
    "true": "DT_FINISHER",
}

PKG_DAMAGE_KEYS = (
    "DT_IMPACT",
    "DT_PUNCTURE",
    "DT_SLASH",
    "DT_FIRE",
    "DT_FREEZE",
    "DT_ELECTRICITY",
    "DT_POISON",
    "DT_EXPLOSION",
    "DT_RADIATION",
    "DT_GAS",
    "DT_MAGNETIC",
    "DT_VIRAL",
    "DT_CORROSIVE",
    "DT_RADIANT",
    "DT_SENTIENT",
    "DT_FINISHER",
)


class SmartPackages:
    """Packages.bin_H reader with relative parent resolution and deep dict merge."""

    def __init__(self, path: Path):
        reader = PackagesBin(path)
        self._reader = reader
        self.entities = {entity.path: entity for entity in reader.iter_entities()}
        all_entities, parent_by_path, sha256 = load_directory_hierarchy(path)
        self._all_entities = all_entities
        self._parent_by_path = parent_by_path
        self.sha256 = sha256
        self._own: dict[str, dict[str, Any]] = {}
        self._resolved: dict[str, dict[str, Any]] = {}

    def exists(self, path: str) -> bool:
        return path in self.entities

    def parent(self, path: str) -> str | None:
        return self._parent_by_path.get(path)

    def mod_family(self, path: str) -> str:
        return compute_mod_family(path, self._parent_by_path, self._all_entities)

    def ancestry(self, path: str) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        cur: str | None = path
        while cur and cur not in seen and cur in self.entities:
            seen.add(cur)
            out.append(cur)
            cur = self.parent(cur)
        return out

    def own(self, path: str) -> dict[str, Any]:
        if path in self._own:
            return self._own[path]
        entity = self.entities.get(path)
        if not entity or entity.attr is None:
            self._own[path] = {}
            return {}
        text = self._reader.decompress(entity).decode("utf-8", "replace").replace("\x00", "")
        cleaned = "\n".join(line for line in text.splitlines() if line.strip())
        try:
            parsed = parse_ee(cleaned)
        except Exception:
            parsed = {}
        self._own[path] = parsed if isinstance(parsed, dict) else {}
        return self._own[path]

    def resolve(self, path: str) -> dict[str, Any]:
        if path in self._resolved:
            return self._resolved[path]
        merged: dict[str, Any] = {}
        for anc in reversed(self.ancestry(path)):
            _merge_into(merged, self.own(anc))
        self._resolved[path] = merged
        return merged

    def locate(self, owner: str, ref: str | None) -> str | None:
        if not ref or not isinstance(ref, str):
            return None
        if ref.startswith("/"):
            return ref if ref in self.entities else None
        for anc in self.ancestry(owner):
            folder = anc.rsplit("/", 1)[0]
            while folder:
                cand = f"{folder}/{ref}"
                if cand in self.entities:
                    return cand
                if "/" not in folder.lstrip("/"):
                    break
                folder = folder.rsplit("/", 1)[0]
        return None


def _merge_into(dst: dict[str, Any], src: dict[str, Any]) -> None:
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge_into(dst[key], value)
        else:
            dst[key] = deepcopy(value)


def _round_float(val: Any, digits: int = 6) -> float:
    return round(float(val), digits)


def _norm_polarity(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s in POLARITY_FROM_PKG:
        return POLARITY_FROM_PKG[s]
    low = s.lower()
    if low in POLARITY_FROM_WFSIM:
        return POLARITY_FROM_WFSIM[low]
    return None


def _norm_slots_10(raw_slots: list[Any] | None, fallback_wfsim: list[str] | None = None) -> list[str | None]:
    if raw_slots and len(raw_slots) >= 8:
        slots = [_norm_polarity(x) for x in raw_slots[:10]]
        while len(slots) < 10:
            slots.append(None)
        return slots
    slots = [_norm_polarity(x) for x in (fallback_wfsim or ())]
    while len(slots) < 10:
        slots.append(None)
    return slots[:10]


def _clean_text(s: str | None) -> str | None:
    if not s:
        return None
    out = re.sub(r"<[^>]+>", "", str(s)).strip()
    return out or None


class Localizer:
    def __init__(self, lang_dir: Path, items_dir: Path):
        self.en = json.loads((lang_dir / "en.json").read_text(encoding="utf-8"))
        self.zh = json.loads((lang_dir / "zh.json").read_text(encoding="utf-8"))
        self.i18n = json.loads((items_dir / "json/i18n.json").read_text(encoding="utf-8"))
        self.items_mods = {
            r["uniqueName"]: r for r in json.loads((items_dir / "json/Mods.json").read_text(encoding="utf-8"))
        }
        self.items_pets = {
            r["uniqueName"]: r for r in json.loads((items_dir / "json/Pets.json").read_text(encoding="utf-8"))
        }
        self.items_sentinels = {
            r["uniqueName"]: r for r in json.loads((items_dir / "json/Sentinels.json").read_text(encoding="utf-8"))
        }

    def tag(self, loc_tag: str | None) -> tuple[str | None, str | None]:
        if not loc_tag:
            return None, None
        en = self.en.get(loc_tag)
        zh = self.zh.get(loc_tag)
        if isinstance(en, dict):
            en = en.get("value")
        if isinstance(zh, dict):
            zh = zh.get("value")
        return _clean_text(en), _clean_text(zh)

    def names(self, path: str, loc_tag: str | None, fallback_en: str | None = None) -> tuple[str, str]:
        en_tag, zh_tag = self.tag(loc_tag)
        item = self.items_mods.get(path) or self.items_pets.get(path) or self.items_sentinels.get(path) or {}
        zh_i18n = ((self.i18n.get(path) or {}).get("zh") or {}).get("name")
        en = en_tag or _clean_text(item.get("name")) or fallback_en or path.rsplit("/", 1)[-1]
        zh = zh_tag or _clean_text(zh_i18n) or en
        return en, zh


class AssetManager:
    def __init__(self, root: Path, official_icons: Path, extra_icons: Path, items_dir: Path):
        self.root = root
        self.frontend = root / "frontend"
        self.companions_dir = self.frontend / "assets" / "companions"
        self.companions_dir.mkdir(parents=True, exist_ok=True)
        self.official = official_icons
        self.extra = extra_icons
        self.items_img = items_dir / "img"
        mod_index_path = self.frontend / "assets" / "mods" / "index.json"
        self.existing_mod_assets = (
            json.loads(mod_index_path.read_text(encoding="utf-8")).get("mods", {})
            if mod_index_path.is_file()
            else {}
        )
        sentinels_path = root / "data" / "mechanics" / "sentinels.json"
        self.sentinel_data = json.loads(sentinels_path.read_text(encoding="utf-8"))
        self.sentinel_mod_art = {m["path"]: m.get("art") for m in self.sentinel_data.get("mods", [])}

    def find_source_icon(self, icon_path: str | None, fallback_img_name: str | None = None) -> Path | None:
        if icon_path:
            rel = icon_path.lstrip("/")
            for base in (self.official, self.extra):
                cand = base / rel
                if cand.is_file() and cand.stat().st_size > 0:
                    return cand
            name = Path(icon_path).name
            cand_item = self.items_img / name
            if cand_item.is_file() and cand_item.stat().st_size > 0:
                return cand_item
        if fallback_img_name:
            cand_item = self.items_img / fallback_img_name
            if cand_item.is_file() and cand_item.stat().st_size > 0:
                return cand_item
        return None

    def copy_companion_portrait(self, icon_path: str | None, dest_filename: str | None = None) -> str:
        src = self.find_source_icon(icon_path)
        if src is None:
            raise FileNotFoundError(f"Missing official icon source for companion portrait: {icon_path}")
        filename = dest_filename or src.name
        dest = self.companions_dir / filename
        if not dest.is_file() or dest.stat().st_size == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return f"/assets/companions/{filename}"

    def copy_part_icon(self, icon_path: str | None) -> str | None:
        src = self.find_source_icon(icon_path)
        if src is None:
            return None
        dest = self.companions_dir / "parts" / src.name
        if not dest.is_file() or dest.stat().st_size == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        return f"/assets/companions/parts/{src.name}"

    def resolve_weapon_portrait(self, weapon_path: str, icon_path: str | None) -> str:
        if icon_path:
            name = Path(icon_path).name
            existing = self.frontend / "assets" / "weapons" / name
            if existing.is_file() and existing.stat().st_size > 0:
                return f"/assets/weapons/{name}"
        stem = weapon_path.rsplit("/", 1)[-1]
        existing_stem = self.frontend / "assets" / "weapons" / f"{stem}.png"
        if existing_stem.is_file() and existing_stem.stat().st_size > 0:
            return f"/assets/weapons/{stem}.png"
        return self.copy_companion_portrait(icon_path, f"{stem}.png")

    def resolve_mod_art(self, mod_path: str, icon_path: str | None, fallback_img_name: str | None = None) -> str:
        existing = (self.existing_mod_assets.get(mod_path) or {}).get("art") or self.sentinel_mod_art.get(mod_path)
        if existing:
            file_path = self.frontend / existing.lstrip("/")
            if file_path.is_file() and file_path.stat().st_size > 0:
                return existing
        src = self.find_source_icon(icon_path, fallback_img_name)
        if src is None:
            raise FileNotFoundError(f"Missing mod art icon for {mod_path} (icon={icon_path})")
        rel = icon_path.lstrip("/") if icon_path else f"mods/{src.name}"
        dest = self.companions_dir / "mods" / rel
        if not dest.is_file() or dest.stat().st_size == 0:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
        if dest.suffix.lower() == ".png":
            bg = dest.with_suffix(".bg.jpg")
            fg = dest.with_suffix(".fg.png")
            if not (bg.is_file() and fg.is_file()):
                split_one(dest)
        return "/" + dest.relative_to(self.frontend).as_posix()

    def verify_asset(self, asset_url: str | None, context: str) -> None:
        if not asset_url or not asset_url.startswith("/assets/"):
            raise ValueError(f"{context}: invalid asset URL {asset_url!r}")
        file_path = self.frontend / asset_url.lstrip("/")
        if not file_path.is_file() or file_path.stat().st_size == 0:
            raise FileNotFoundError(f"{context}: asset missing or empty on disk -> {file_path}")


# Breed -> Beast Claw internal_name mapping
BEAST_BREED_TO_CLAW = {
    "/Lotus/Types/Game/CatbrowPet/MirrorCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/AdarzaPetWeapon",
    "/Lotus/Types/Game/CatbrowPet/CheshireCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/SmeetaPetWeapon",
    "/Lotus/Types/Game/CatbrowPet/VampireCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/VascaPetWeapon",
    "/Lotus/Powersuits/Khora/Kavat/KhoraKavatPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/VenariPetWeapon",
    "/Lotus/Powersuits/Khora/Kavat/KhoraPrimeKavatPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/VenariPrimePetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/ArmoredInfestedCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/PanzerVulpaphylaPetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/VulpineInfestedCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/SlyVulpaphylaPetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/HornedInfestedCatbrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/CrescentVulpaphylaPetWeapon",
    "/Lotus/Types/Game/KubrowPet/RetrieverKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/ChesaPetWeapon",
    "/Lotus/Types/Game/KubrowPet/FurtiveKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/HurasPetWeapon",
    "/Lotus/Types/Game/KubrowPet/GuardKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/RaksaPetWeapon",
    "/Lotus/Types/Game/KubrowPet/AdventurerKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/SahasaPetWeapon",
    "/Lotus/Types/Game/KubrowPet/HunterKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/SunikaPetWeapon",
    "/Lotus/Types/Game/KubrowPet/ChargerKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/HelminthPetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/MedjayPredatorKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/MedjayPredasitePetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/PharaohPredatorKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/PharaohPredasitePetWeapon",
    "/Lotus/Types/Friendly/Pets/CreaturePets/VizierPredatorKubrowPetPowerSuit": "/Lotus/Types/Friendly/Pets/BeastWeapons/VizierPredasitePetWeapon",
}
CLAW_TO_BREED = {v: k for k, v in BEAST_BREED_TO_CLAW.items()}

MOA_MODELS = [
    {
        "id": "oloro_moa",
        "path": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetHeadOloro",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/CryoxionWeapon",
        "portraitName": "MoaOloro.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetEngineThricore",
            "gyro": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetPayloadCryoxion",
            "bracket": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetLegA",
        },
    },
    {
        "id": "lambeo_moa",
        "path": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetHeadLambeo",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/TazronWeapon",
        "portraitName": "MoaLambeo.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetEngineKrisys",
            "gyro": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetPayloadAegron",
            "bracket": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetLegB",
        },
    },
    {
        "id": "para_moa",
        "path": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetHeadPara",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/HextraWeapon",
        "portraitName": "MoaPara.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetEngineArcotek",
            "gyro": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetPayloadMunitron",
            "bracket": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetLegC",
        },
    },
    {
        "id": "nychus_moa",
        "path": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetHeadMelee",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetComponents/ThermocorMoaWeapon",
        "portraitName": "MoaNychus.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MeleeMoaPetEngine",
            "gyro": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MeleeMoaPetPayload",
            "bracket": "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetParts/MoaPetLegMelee",
        },
    },
]

HOUND_MODELS = [
    {
        "id": "bhaira_hound",
        "path": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartHeadB",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIS",
        "portraitName": "HoundBhaira.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartBodyB",
            "bracket": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartLegsB",
            "stabilizer": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartTailB",
        },
    },
    {
        "id": "dorma_hound",
        "path": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartHeadA",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIP",
        "portraitName": "HoundDorma.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartBodyA",
            "bracket": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartLegsA",
            "stabilizer": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartTailA",
        },
    },
    {
        "id": "hec_hound",
        "path": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartHeadC",
        "defaultWeaponPath": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponPS",
        "portraitName": "HoundHec.png",
        "defaultParts": {
            "core": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartBodyC",
            "bracket": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartLegsC",
            "stabilizer": "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetParts/ZanukaPetPartTailC",
        },
    },
]

HOUND_MELEE_PATHS = [
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeapon",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIP",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponIS",
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetMeleeWeaponPS",
]
DECONSTRUCTOR_PATHS = [
    "/Lotus/Types/Sentinels/SentinelWeapons/SentGlaiveWeapon",
    "/Lotus/Types/Sentinels/SentinelWeapons/DeconstructorPrime/PrimeHeliosGlaiveWeapon",
]

BOND_SPECS: dict[str, dict[str, Any]] = {
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TenaciousPartner": {
        "id": "tenacious_bond",
        "trigger": "companion_crit_chance_over_threshold",
        "companionCritChanceThreshold": 0.50,
        "playerFinalCritDamagePerRank": 0.20,
        "playerFinalCritDamageByRank": [0.20, 0.40, 0.60, 0.80, 1.00, 1.20],
        "playerFinalCritDamageMax": 1.20,
        "headshotRecoveryReductionByRank": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "headshotRecoveryReductionMax": 3.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/AlacrityField": {
        "id": "reinforced_bond",
        "trigger": "companion_shield_at_or_above_threshold",
        "companionShieldThreshold": 1200.0,
        "playerFireRateBonusPerRank": 0.10,
        "playerFireRateBonusByRank": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60],
        "playerFireRateBonusMax": 0.60,
        "reloadOvershieldGrantByRank": [25.0, 50.0, 75.0, 100.0, 125.0, 150.0],
        "reloadOvershieldGrantMax": 150.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/CompoundingLaceration": {
        "id": "manifold_bond",
        "trigger": "kill_enemy_with_unique_statuses",
        "appliesWeaponStatusesToPrecepts": True,
        "uniqueStatusesRequiredByRank": [6, 5, 5, 4, 4, 3],
        "uniqueStatusesRequiredMax": 3,
        "cooldownReductionByRank": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "cooldownReductionMax": 3.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/EximusHunter": {
        "id": "momentous_bond",
        "trigger": "eximus_kill",
        "companionElementalBonusByRank": [0.20, 0.40, 0.60, 0.80, 1.00, 1.20],
        "companionElementalBonusMax": 1.20,
        "duration": 30.0,
        "recoveryReductionByRank": [3.0, 6.0, 9.0, 12.0, 15.0, 18.0],
        "recoveryReductionMax": 18.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidVinculum": {
        "id": "astral_bond",
        "trigger": "operator_or_drifter_damage",
        "companionDamageBonusByRank": [0.10, 0.20, 0.30, 0.40, 0.50, 0.60],
        "companionDamageBonusMax": 0.60,
        "companionVoidDamageByRank": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        "companionVoidDamageMax": 0.30,
        "damageDuration": 10.0,
        "operatorEfficiencyByRank": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        "operatorEfficiencyMax": 0.30,
        "efficiencyDuration": 5.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Proliferation": {
        "id": "contagious_bond",
        "trigger": "companion_kill_status_afflicted",
        "statusSpreadFractionByRank": [0.0833, 0.1666, 0.25, 0.3332, 0.4165, 0.50],
        "statusSpreadFractionMax": 0.50,
        "radiusByRank": [1.5, 3.0, 4.5, 6.0, 7.5, 9.0],
        "radiusMax": 9.0,
        "maxStacks": 100,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BoneSplitter": {
        "id": "vicious_bond",
        "trigger": "companion_melee_hit",
        "armorStripFractionByRank": [0.025, 0.05, 0.075, 0.10, 0.125, 0.15],
        "armorStripFractionMax": 0.15,
        "spreadRadiusByRank": [1.5, 3.0, 4.5, 6.0, 7.5, 9.0],
        "spreadRadiusMax": 9.0,
        "abilityDamagedSpreadWindow": 10.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PreyDrive": {
        "id": "mystic_bond",
        "trigger": "companion_cooldown_ability_casts",
        "requiredCooldownCastsByRank": [10, 9, 8, 7, 6, 5],
        "requiredCooldownCastsMax": 5,
        "freeAbilityCastsGranted": 1,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/TandemTactics": {
        "id": "tandem_bond",
        "trigger": "companion_melee_hit_and_player_heavy_attack",
        "comboGainPerHitByRank": [1, 2, 3, 4, 5, 6],
        "comboGainPerHitMax": 6,
        "heavyAttackCompanionMeleeBonusPerComboMultByRank": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        "heavyAttackCompanionMeleeBonusPerComboMultMax": 0.30,
        "duration": 30.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidClone": {
        "id": "duplex_bond",
        "trigger": "player_energy_spent",
        "energySpentThreshold": 100.0,
        "maxClones": 3,
        "cloneDurationByRank": [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
        "cloneDurationMax": 30.0,
        "energyOrbDropChanceByRank": [0.0834, 0.1668, 0.2502, 0.3336, 0.417, 0.50],
        "energyOrbDropChanceMax": 0.50,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BondedExaltation": {
        "id": "seismic_bond",
        "trigger": "channeled_ability_companion_damage",
        "shockwaveRadius": 4.0,
        "shockwaveDamageShareByRank": [0.05, 0.10, 0.15, 0.20, 0.25, 0.30],
        "shockwaveDamageShareMax": 0.30,
        "abilityEfficiencyPerStackByRank": [0.005, 0.01, 0.015, 0.02, 0.025, 0.03],
        "abilityEfficiencyPerStackMax": 0.03,
        "maxStacks": 10,
        "durationByRank": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
        "durationMax": 12.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/Copilot": {
        "id": "aerial_bond",
        "trigger": "player_airborne",
        "airKillRecoveryReductionByRank": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "airKillRecoveryReductionMax": 3.0,
        "headshotAirKillRecoveryReductionByRank": [1.5, 3.0, 4.5, 6.0, 7.5, 9.0],
        "headshotAirKillRecoveryReductionMax": 9.0,
        "coldFieldMaxSlowByRank": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],
        "coldFieldMaxSlowMax": 0.35,
        "coldFieldMaxRadiusByRank": [2.5, 4.0, 5.5, 7.0, 8.5, 10.0],
        "coldFieldMaxRadiusMax": 10.0,
        "lingerDuration": 3.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/MutualNourishment": {
        "id": "restorative_bond",
        "trigger": "health_orb_pickup",
        "bonusHealthPerOrbByRank": [10.0, 20.0, 30.0, 40.0, 50.0, 60.0],
        "bonusHealthPerOrbMax": 60.0,
        "recoveryReductionPerOrbByRank": [0.5, 1.0, 1.5, 2.0, 2.5, 3.0],
        "recoveryReductionPerOrbMax": 3.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PredatoryResponse": {
        "id": "covert_bond",
        "trigger": "finisher_or_mercy_kill",
        "stealthDurationByRank": [1.7, 3.3, 5.0, 6.7, 8.3, 10.0],
        "stealthDurationMax": 10.0,
        "maxStealthDuration": 60.0,
    },
}

CURATED_PRECEPT_SPECS: dict[str, dict[str, Any]] = {
    "/Lotus/Types/Sentinels/SentinelPrecepts/SentinelAttack": {
        "isAttackPrecept": True,
        "attackRange": 30.0,
        "attackRangeByRank": [17.5, 20.0, 22.5, 25.0, 27.5, 30.0],
        "sustainRange": 30.0,
        "cooldown": 0.0,
        "requiresLineOfSight": True,
        "usesWeaponZoom": False,
        "usesMeleeRange": False,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/HeadShot": {
        "isAttackPrecept": True,
        "attackRange": 70.0,
        "attackRangeByRank": [40.0, 46.0, 52.0, 58.0, 64.0, 70.0],
        "sustainRange": 70.0,
        "cooldown": 0.0,
        "requiresLineOfSight": True,
        "usesWeaponZoom": True,
        "usesMeleeRange": False,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/Thumper": {
        "isAttackPrecept": True,
        "attackRange": 60.0,
        "attackRangeByRank": [35.0, 40.0, 45.0, 50.0, 55.0, 60.0],
        "sustainRange": 60.0,
        "cooldown": 0.0,
        "requiresLineOfSight": True,
        "usesWeaponZoom": False,
        "usesMeleeRange": False,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/ThrowGlaivePrecept": {
        "isAttackPrecept": True,
        "attackRange": 10.0,
        "sustainRange": 10.0,
        "cooldown": 0.0,
        "requiresLineOfSight": True,
        "usesWeaponZoom": False,
        "usesMeleeRange": True,
        "maxTargets": 3,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/Revenge": {
        "isAttackPrecept": True,
        "attackRange": 10.0,
        "attackRangeByRank": [5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
        "sustainRange": 10.0,
        "cooldown": 0.0,
        "requiresLineOfSight": True,
        "retaliatoryOnly": True,
        "usesWeaponZoom": False,
        "usesMeleeRange": False,
    },
    "/Lotus/Upgrades/Mods/Sentinel/Moa/MoaMeleeMod": {
        "isAttackPrecept": True,
        "attackRange": 10.0,
        "sustainRange": 10.0,
        "cooldown": 0.0,
        "usesWeaponZoom": False,
        "usesMeleeRange": True,
        "damage": 90.0,
        "damageType": "DT_IMPACT",
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/ArcTrap": {
        "isAttackPrecept": False,
        "attackRange": 10.0,
        "sustainRange": 10.0,
        "cooldown": 1.0,
        "damage": 100.0,
        "damageType": "DT_ELECTRICITY",
        "procChance": 0.10,
        "forcedProc": "PT_ELECTROCUTION",
        "radius": 10.0,
        "maxTargets": 7,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/TaserStun": {
        "isAttackPrecept": False,
        "attackRange": 15.0,
        "sustainRange": 15.0,
        "cooldown": 5.0,
        "damage": 50.0,
        "damageType": "DT_ELECTRICITY",
        "procChance": 1.0,
        "forcedProc": "PT_ELECTROCUTION",
        "maxTargets": 1,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/GatherEnemies": {
        "isAttackPrecept": False,
        "attackRange": 30.0,
        "attackRangeByRank": [5.0, 10.0, 15.0, 20.0, 25.0, 30.0],
        "sustainRange": 30.0,
        "cooldown": 15.0,
        "radius": 30.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/Vaporize": {
        "isAttackPrecept": False,
        "attackRange": 30.0,
        "sustainRange": 30.0,
        "cooldown": 10.0,
        "damage": 600.0,
        "damageType": "DT_RADIATION",
        "maxTargets": 1,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/CoolantLeak": {
        "isAttackPrecept": False,
        "attackRange": 10.0,
        "cooldown": 10.0,
        "damageType": "DT_FREEZE",
        "procChance": 1.0,
        "forcedProc": "PT_CHILLED",
        "forcedProcStacks": 3,
        "radius": 10.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/CrowdDispersion": {
        "isAttackPrecept": False,
        "attackRange": 10.0,
        "cooldown": 15.0,
        "damage": 10.0,
        "damageType": "DT_MAGNETIC",
        "procChance": 1.0,
        "forcedProc": "PT_MAGNETIZED",
        "radius": 10.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/ProcAbsorb": {
        "isAttackPrecept": False,
        "cooldown": 5.0,
        "cooldownByRank": [15.0, 13.0, 11.0, 9.0, 7.0, 5.0],
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/Ghost": {
        "isAttackPrecept": False,
        "attackRange": 24.0,
        "cooldown": 8.0,
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/GhostAugmentCard": {
        "isAttackPrecept": False,
        "cooldown": 8.0,
        "playerBuff": {
            "kind": "weapon_damage",
            "upgradeType": "WEAPON_DAMAGE_AMOUNT",
            "operation": "STACKING_MULTIPLY",
            "value": 2.40,
            "valueByRank": [0.60, 1.20, 1.80, 2.40],
            "duration": 3.0,
            "trigger": "on_ghost_broken",
        },
    },
    "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowCatsEyePrecept": {
        "isAttackPrecept": False,
        "cooldown": 20.0,
        "cooldownByRank": [30.0, 26.7, 23.3, 20.0],
        "radius": 25.0,
        "playerBuff": {
            "kind": "flat_crit_chance",
            "upgradeType": "WEAPON_CRIT_CHANCE",
            "operation": "ADD",
            "value": 0.60,
            "valueByRank": [0.15, 0.30, 0.45, 0.60],
            "duration": 10.0,
            "cooldown": 20.0,
            "averageUptime": 0.50,
        },
    },
    "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowLuckPrecept": {
        "isAttackPrecept": False,
        "cooldown": 27.0,
        "procChance": 0.40,
        "playerBuff": {
            "kind": "smeeta_charm",
            "setCritChance": 2.0,
            "critDuration": 30.0,
            "instantReload": True,
            "chance": 0.40,
            "interval": 27.0,
        },
    },
    "/Lotus/Types/Friendly/Pets/CatbrowPetPrecepts/CatbrowShredPrecept": {
        "isAttackPrecept": False,
        "attackRange": 10.0,
        "cooldown": 8.0,
        "damage": 3.0,
        "armorStrip": 1.20,
    },
    "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedKavatViralQuillsPrecept": {
        "isAttackPrecept": False,
        "attackRange": 20.0,
        "sustainRange": 20.0,
        "cooldown": 4.0,
        "damage": 60.0,
        "damageType": "DT_VIRAL",
        "procChance": 0.40,
        "forcedProc": "PT_INFECTED",
        "maxTargets": 6,
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetTeslaShotPrecept": {
        "isAttackPrecept": False,
        "attackRange": 30.0,
        "sustainRange": 30.0,
        "cooldown": 10.0,
        "damage": 300.0,
        "damageType": "DT_ELECTRICITY",
        "procChance": 1.0,
        "forcedProc": "PT_ELECTROCUTION",
        "radius": 10.0,
        "maxTargets": 8,
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetPhotonStrikePrecept": {
        "isAttackPrecept": False,
        "attackRange": 27.0,
        "sustainRange": 27.0,
        "cooldown": 10.0,
        "damage": 1200.0,
        "damageType": "DT_EXPLOSION",
        "procChance": 1.0,
        "forcedProc": "PT_KNOCKBACK",
        "radius": 7.0,
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetMegaLaserPrecept": {
        "isAttackPrecept": False,
        "attackRange": 40.0,
        "sustainRange": 40.0,
        "cooldown": 10.0,
        "damage": 900.0,
        "damageType": "DT_FIRE",
        "procChance": 1.0,
        "forcedProc": "PT_IMMOLATION",
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetDisarmPulsePrecept": {
        "isAttackPrecept": False,
        "attackRange": 30.0,
        "cooldown": 20.0,
        "damageType": "DT_MAGNETIC",
        "procChance": 1.0,
        "forcedProc": "PT_MAGNETIZED",
        "radius": 30.0,
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetStealEximusPrecept": {
        "isAttackPrecept": False,
        "attackRange": 25.0,
        "cooldown": 20.0,
        "overguardStrip": 0.50,
    },
    "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPrecepts/ZanukaPetAntiMeleePrecept": {
        "isAttackPrecept": False,
        "attackRange": 15.0,
        "cooldown": 15.0,
        "damage": 300.0,
        "radius": 15.0,
    },
    "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorBuffSporesPrecept": {
        "isAttackPrecept": False,
        "cooldown": 20.0,
        "radius": 6.0,
        "playerBuff": {
            "kind": "elemental_damage",
            "damageType": "DT_POISON",
            "upgradeType": "WEAPON_PERCENT_BASE_DAMAGE_ADDED",
            "operation": "STACKING_MULTIPLY",
            "value": 1.00,
            "duration": 15.0,
        },
    },
    "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorSpitAcidPrecept": {
        "isAttackPrecept": False,
        "attackRange": 7.5,
        "cooldown": 4.0,
        "damage": 120.0,
        "damageType": "DT_CORROSIVE",
        "procChance": 1.0,
        "forcedProc": "PT_CAUSTIC_BURN",
    },
    "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorSpitParasitePrecept": {
        "isAttackPrecept": False,
        "attackRange": 15.0,
        "cooldown": 4.0,
        "damage": 20.0,
        "damageType": "DT_VIRAL",
        "radius": 5.0,
    },
    "/Lotus/Types/Friendly/Pets/CreaturePets/CreaturePrecepts/InfestedPredatorInfectiousBitePrecept": {
        "isAttackPrecept": False,
        "attackRange": 5.0,
        "cooldown": 6.0,
        "damageType": "DT_VIRAL",
        "procChance": 1.0,
        "forcedProc": "PT_INFECTED",
    },
    "/Lotus/Types/Sentinels/SentinelPrecepts/Events/CorpusArena/ShieldAuraPrecept": {
        "isAttackPrecept": False,
        "cooldown": 20.0,
        "playerBuff": {
            "kind": "frame_shield_bonus",
            "shieldMaxBonus": 0.60,
            "shieldRechargeBonus": 0.60,
            "duration": 10.0,
        },
    },
}

LINK_UPGRADE_TYPES = {
    "AVATAR_SENTINEL_HEALTH_LINK",
    "AVATAR_SENTINEL_SHIELD_LINK",
    "AVATAR_SENTINEL_ARMOUR_LINK",
}


def build_companions(
    pkgs: SmartPackages,
    loc: Localizer,
    assets: AssetManager,
    wfsim_data: Path,
    companion_weapons: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    """Build all 41 playable companions (17 Sentinels + 4 MOAs + 3 Hounds + 17 Beasts)."""
    companions: list[dict[str, Any]] = []
    ancestry_by_path: dict[str, set[str]] = {}
    all_claw_paths = sorted(BEAST_BREED_TO_CLAW.values())
    all_robotic_weapon_paths = sorted(w["path"] for w in companion_weapons)

    # 1. 17 Sentinels
    wfsim_companions = {
        yaml.safe_load(f.read_text(encoding="utf-8")).get("internal_name"): yaml.safe_load(f.read_text(encoding="utf-8"))
        for f in sorted((wfsim_data / "companions").glob("*.yaml"))
    }
    for sent in assets.sentinel_data["sentinels"]:
        path = sent["path"]
        wdoc = wfsim_companions.get(path) or {}
        pkg_row = pkgs.resolve(path)
        en, zh = loc.names(path, pkg_row.get("LocalizeTag"), sent.get("nameEn"))
        zh = sent.get("nameZh") or zh
        stats_doc = wdoc.get("stats") or {}
        health = float(pkg_row.get("MaxHealthOverride") or stats_doc.get("health") or sent["health"])
        shield = float(pkg_row.get("MaxShieldOverride") or stats_doc.get("shield") or sent["shield"])
        armor = float(pkg_row.get("ArmourRatingOverride") or stats_doc.get("armor") or sent["armor"])
        default_weapon = sent["defaultWeapon"]
        is_helios = default_weapon in DECONSTRUCTOR_PATHS
        incompat = sorted(
            set(sent.get("incompatibleWeapons") or ())
            | set(HOUND_MELEE_PATHS)
            | set(all_claw_paths)
            | (set() if is_helios else set(DECONSTRUCTOR_PATHS))
        )
        portrait = sent["portrait"]
        assets.verify_asset(portrait, f"sentinel {en}")
        companions.append(
            {
                "path": path,
                "id": wdoc.get("id") or en.lower().replace(" ", "_"),
                "nameEn": en,
                "nameZh": zh,
                "kind": "sentinel",
                "category": "robotic",
                "prime": bool(sent.get("prime")),
                "stats": {"health": health, "shield": shield, "armor": armor},
                "polarities": _norm_slots_10(pkg_row.get("ArtifactSlots") or sent.get("slots"), wdoc.get("polarities")),
                "defaultWeaponPath": default_weapon,
                "weaponCategory": "deconstructor" if is_helios else "sentinel_gun",
                "allowedWeaponCategories": ["sentinel_gun", "deconstructor"] if is_helios else ["sentinel_gun"],
                "incompatibleWeapons": incompat,
                "defaultPrecepts": list(sent.get("defaultPrecepts") or ()),
                "portraitAsset": portrait,
                "innateAttack": None,
            }
        )
        ancestry_by_path[path] = set(pkgs.ancestry(path)) | {
            "SentinelPowerSuit",
            "/Lotus/Types/Game/SentinelPowerSuit",
            "/Lotus/Types/Game/Pets/RoboticPetPowerSuit",
            "/Lotus/Types/Sentinels/SentinelPowerSuit",
        }

    # 2. 4 MOAs (by Head/Model)
    moa_suit_path = "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetPowerSuit"
    moa_suit = pkgs.resolve(moa_suit_path)
    moa_wdoc = wfsim_companions.get(moa_suit_path) or {}
    moa_slots = _norm_slots_10(moa_suit.get("ArtifactSlots"), moa_wdoc.get("polarities"))
    moa_incompat = sorted(set(DECONSTRUCTOR_PATHS) | set(HOUND_MELEE_PATHS) | set(all_claw_paths))
    for model in MOA_MODELS:
        head_path = model["path"]
        head_row = pkgs.resolve(head_path)
        en, zh = loc.names(head_path, head_row.get("LocalizeTag"))
        precepts = [
            u["ItemType"] for u in head_row.get("DefaultSlottedUpgrades") or () if u.get("ItemType")
        ]
        if "/Lotus/Types/Sentinels/SentinelPrecepts/UniversalVacuum" not in precepts:
            precepts.append("/Lotus/Types/Sentinels/SentinelPrecepts/UniversalVacuum")
        portrait = assets.copy_companion_portrait(head_row.get("Icon"), model["portraitName"])
        assets.verify_asset(portrait, f"MOA {en}")
        companions.append(
            {
                "path": head_path,
                "powersuitPath": moa_suit_path,
                "id": model["id"],
                "nameEn": en,
                "nameZh": zh,
                "kind": "moa",
                "category": "robotic",
                "prime": False,
                "stats": {"health": 350.0, "shield": 350.0, "armor": 350.0},
                "defaultParts": model["defaultParts"],
                "polarities": list(moa_slots),
                "defaultWeaponPath": model["defaultWeaponPath"],
                "weaponCategory": "sentinel_gun",
                "allowedWeaponCategories": ["sentinel_gun"],
                "incompatibleWeapons": moa_incompat,
                "defaultPrecepts": precepts,
                "portraitAsset": portrait,
                "innateAttack": {
                    "mode": "ranged",
                    "range": 70.0,
                    "attackSegment": [5.0, 10.0],
                    "waitSegment": [0.0, 1.0],
                },
            }
        )
        ancestry_by_path[head_path] = set(pkgs.ancestry(moa_suit_path)) | {
            head_path,
            "SentinelPowerSuit",
            "/Lotus/Types/Game/SentinelPowerSuit",
            "/Lotus/Types/Game/Pets/RoboticPetPowerSuit",
        }

    # 3. 3 Hounds (by Model)
    hound_suit_path = "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPowerSuit"
    hound_suit = pkgs.resolve(hound_suit_path)
    hound_wdoc = wfsim_companions.get(hound_suit_path) or {}
    hound_slots = _norm_slots_10(hound_suit.get("ArtifactSlots"), hound_wdoc.get("polarities"))
    hound_incompat = sorted(
        (set(all_robotic_weapon_paths) - set(HOUND_MELEE_PATHS)) | set(all_claw_paths)
    )
    for model in HOUND_MODELS:
        head_path = model["path"]
        head_row = pkgs.resolve(head_path)
        core_row = pkgs.resolve(model["defaultParts"]["core"])
        en, zh = loc.names(head_path, head_row.get("LocalizeTag"))
        precepts = [
            u["ItemType"] for u in head_row.get("DefaultSlottedUpgrades") or () if u.get("ItemType")
        ]
        for slot_key in ("bracket", "stabilizer"):
            part_row = pkgs.resolve(model["defaultParts"][slot_key])
            for u in part_row.get("DefaultSlottedUpgrades") or ():
                if u.get("ItemType") and u["ItemType"] not in precepts:
                    precepts.append(u["ItemType"])
        if "/Lotus/Types/Sentinels/SentinelPrecepts/UniversalVacuum" not in precepts:
            precepts.append("/Lotus/Types/Sentinels/SentinelPrecepts/UniversalVacuum")
        portrait = assets.copy_companion_portrait(head_row.get("Icon"), model["portraitName"])
        assets.verify_asset(portrait, f"Hound {en}")
        companions.append(
            {
                "path": head_path,
                "powersuitPath": hound_suit_path,
                "id": model["id"],
                "nameEn": en,
                "nameZh": zh,
                "kind": "hound",
                "category": "robotic",
                "prime": False,
                "stats": {
                    "health": float(core_row.get("BaseHealth") or 350.0),
                    "shield": float(core_row.get("BaseShields") or 350.0),
                    "armor": float(core_row.get("BaseArmor") or 350.0),
                },
                "defaultParts": model["defaultParts"],
                "polarities": list(hound_slots),
                "defaultWeaponPath": model["defaultWeaponPath"],
                "weaponCategory": "hound_melee",
                "allowedWeaponCategories": ["hound_melee"],
                "incompatibleWeapons": hound_incompat,
                "defaultPrecepts": precepts,
                "portraitAsset": portrait,
                "innateAttack": {"mode": "melee", "range": 25.0},
            }
        )
        ancestry_by_path[head_path] = set(pkgs.ancestry(hound_suit_path)) | {
            head_path,
            "SentinelPowerSuit",
            "/Lotus/Types/Game/SentinelPowerSuit",
            "/Lotus/Types/Game/Pets/RoboticPetPowerSuit",
        }

    # 4. 17 Beasts
    for breed_path, claw_path in BEAST_BREED_TO_CLAW.items():
        wdoc = wfsim_companions[breed_path]
        pkg_row = pkgs.resolve(breed_path)
        en, zh = loc.names(breed_path, pkg_row.get("LocalizeTag"), wdoc.get("name"))
        raw_kind = str(wdoc.get("kind") or "")
        kind = "charger" if raw_kind == "helminth" else raw_kind
        wstats = wdoc.get("stats") or {}
        health = float(pkg_row.get("MaxHealthOverride") or pkg_row.get("BaseHealth") or wstats.get("health") or 0.0)
        shield_raw = pkg_row.get("MaxShieldOverride")
        if shield_raw is None:
            shield_raw = wstats.get("shield", 0.0)
        shield = float(shield_raw or 0.0)
        armor = float(pkg_row.get("ArmourRatingOverride") or pkg_row.get("BaseArmor") or wstats.get("armor") or 300.0)
        precepts = [
            u["ItemType"] for u in pkg_row.get("DefaultSlottedUpgrades") or () if u.get("ItemType")
        ]
        portrait = assets.copy_companion_portrait(pkg_row.get("Icon"))
        assets.verify_asset(portrait, f"Beast {en}")
        incompat = sorted((set(all_claw_paths) - {claw_path}) | set(all_robotic_weapon_paths))
        companions.append(
            {
                "path": breed_path,
                "id": wdoc["id"],
                "nameEn": en,
                "nameZh": zh,
                "kind": kind,
                "category": "beast",
                "prime": "Prime" in en,
                "stats": {"health": health, "shield": shield, "armor": armor},
                "polarities": _norm_slots_10(pkg_row.get("ArtifactSlots"), wdoc.get("polarities")),
                "defaultWeaponPath": claw_path,
                "weaponCategory": "beast_claws",
                "allowedWeaponCategories": ["beast_claws"],
                "incompatibleWeapons": incompat,
                "defaultPrecepts": precepts,
                "portraitAsset": portrait,
                "innateAttack": {"mode": "passive_only"},
            }
        )
        ancestry_by_path[breed_path] = set(pkgs.ancestry(breed_path)) | {
            "SentinelPowerSuit",
            "/Lotus/Types/Game/SentinelPowerSuit",
            "/Lotus/Types/Game/Pets/PetPowerSuit",
        }

    return companions, ancestry_by_path


def build_modular_parts(pkgs: SmartPackages, loc: Localizer, assets: AssetManager, wfsim_data: Path) -> dict[str, Any]:
    raw_parts = yaml.safe_load((wfsim_data / "companion_parts.yaml").read_text(encoding="utf-8"))["parts"]
    out: dict[str, Any] = {
        "moa": {"models": [], "cores": [], "gyros": [], "brackets": []},
        "hound": {"models": [], "cores": [], "brackets": [], "stabilizers": []},
        "vulpaphyla": {"mutagens": [], "antigens": []},
        "predasite": {"mutagens": [], "antigens": []},
    }
    slot_plural = {
        "model": "models",
        "core": "cores",
        "gyro": "gyros",
        "bracket": "brackets",
        "stabilizer": "stabilizers",
        "mutagen": "mutagens",
        "antigen": "antigens",
    }
    for part in raw_parts:
        path = part["internal_name"]
        pkg_row = pkgs.resolve(path)
        en, zh = loc.names(path, pkg_row.get("LocalizeTag"), part.get("name"))
        family = part["family"]
        slot = part["slot"]
        precept_paths = [
            u["ItemType"] for u in pkg_row.get("DefaultSlottedUpgrades") or () if u.get("ItemType")
        ]
        if pkg_row.get("PayloadPrecept") and pkg_row["PayloadPrecept"] not in precept_paths:
            precept_paths.append(pkg_row["PayloadPrecept"])
        resistances = [
            {
                "damageType": u.get("DamageType"),
                "operation": u.get("OperationType"),
                "value": _round_float(u.get("Value", 1.0)),
            }
            for u in pkg_row.get("Upgrades") or ()
            if u.get("UpgradeType") == "AVATAR_DAMAGE_TAKEN"
        ]
        icon_asset = assets.copy_part_icon(pkg_row.get("Icon"))
        if icon_asset:
            assets.verify_asset(icon_asset, f"part {en}")
        entry: dict[str, Any] = {
            "id": part["id"],
            "path": path,
            "nameEn": en,
            "nameZh": zh,
            "family": family,
            "slot": slot,
            "modifyBase": bool(part.get("modify_base", False)),
            "baseStats": part.get("base"),
            "bonus": part.get("bonus") or {},
            "ungildedBonus": part.get("ungilded_bonus") or {},
            "polarity": _norm_polarity(pkg_row.get("OverridePolarity") or part.get("polarity")),
            "preceptPath": precept_paths[0] if len(precept_paths) == 1 else None,
            "preceptPaths": precept_paths,
            "payloadWeaponPath": pkg_row.get("PayloadWeapon"),
            "resistances": resistances,
            "iconAsset": icon_asset,
        }
        out[family][slot_plural[slot]].append(entry)
    return out


def build_beast_claws(
    pkgs: SmartPackages, loc: Localizer, assets: AssetManager, wfsim_data: Path
) -> tuple[list[dict[str, Any]], dict[str, set[str]]]:
    claws: list[dict[str, Any]] = []
    claw_ancestry: dict[str, set[str]] = {}
    claw_portrait = assets.copy_companion_portrait(
        "/Lotus/Interface/Icons/GeneticLab/BeastClaws.png", "BeastClaws.png"
    )
    assets.verify_asset(claw_portrait, "BeastClaws.png")

    for f in sorted((wfsim_data / "weapons/beast_claws").glob("*.yaml")):
        wdoc = yaml.safe_load(f.read_text(encoding="utf-8"))
        path = wdoc["internal_name"]
        pkg_row = pkgs.resolve(path)
        en, zh = loc.names(path, pkg_row.get("LocalizeTag"), wdoc.get("name"))
        beh = (pkg_row.get("Behaviors") or [{}])[0]
        imp = next((v for k, v in beh.items() if k.startswith("impact:") and isinstance(v, dict)), {})
        ad = imp.get("AttackData") or {}

        dmg_types: dict[str, float] = {}
        w_attack = wdoc.get("attack") or {}
        for wk, wv in (w_attack.get("damage") or {}).items():
            dt = WFSIM_DAMAGE_MAP[wk]
            dmg_types[dt] = _round_float(wv)
        total_damage = _round_float(ad.get("Amount") or sum(dmg_types.values()))
        # Cross-check sum matches native Amount
        if abs(sum(dmg_types.values()) - total_damage) > 1e-3:
            raw_dt = {dt: float(ad[dt]) for dt in PKG_DAMAGE_KEYS if isinstance(ad.get(dt), (int, float)) and ad[dt]}
            if raw_dt:
                wsum = sum(raw_dt.values()) or 1.0
                dmg_types = {dt: _round_float(total_damage * v / wsum) for dt, v in raw_dt.items()}

        raw_slots = pkg_row.get("ArtifactSlots") or []
        normal_polarities = [_norm_polarity(s) for s in raw_slots[:8]]
        while len(normal_polarities) < 8:
            normal_polarities.append(None)
        posture_polarity = _norm_polarity(raw_slots[8]) if len(raw_slots) > 8 else "AP_PRECEPT"

        claws.append(
            {
                "path": path,
                "id": wdoc["id"],
                "breedPath": CLAW_TO_BREED[path],
                "nameEn": en,
                "nameZh": zh,
                "damageTypes": dmg_types,
                "totalDamage": total_damage,
                "critChance": _round_float(imp.get("criticalHitChance") or w_attack.get("crit_chance") or 0.0),
                "critMultiplier": _round_float(
                    imp.get("criticalHitDamageMultiplier") or w_attack.get("crit_multiplier") or 1.5
                ),
                "statusChance": _round_float(ad.get("ProcChance") or w_attack.get("status_chance") or 0.0),
                "attackSpeed": _round_float(w_attack.get("fire_rate") or 1.0),
                "assumedRefireSeconds": _round_float(
                    ((w_attack.get("refire") or {}).get("assumed_seconds")) or 1.0
                ),
                "meleeRadius": _round_float(((w_attack.get("melee_radius") or {}).get("radius_m")) or 1.0),
                "polarities": [*normal_polarities, posture_polarity],
                "posturePolarity": posture_polarity,
                "portraitAsset": claw_portrait,
            }
        )
        claw_ancestry[path] = set(pkgs.ancestry(path))

    return claws, claw_ancestry


def _extract_upgrades(pkg_row: dict[str, Any], max_rank: int) -> list[dict[str, Any]]:
    upgrades: list[dict[str, Any]] = []
    for u in pkg_row.get("Upgrades") or ():
        utype = u.get("UpgradeType")
        if utype in (None, "", "NONE"):
            continue
        raw_val = float(u.get("Value") or 0.0)
        if utype in LINK_UPGRADE_TYPES and max_rank == 10 and abs(raw_val * 11 - 1.25) < 0.01:
            # Native Link Health/Shield/Armor round each rank to whole percentage points (+125% at rank 10).
            val_per_level = 1.25 / 11.0
            rank_vals = [round(raw_val * (r + 1) * 100.0) / 100.0 for r in range(max_rank + 1)]
            rank_vals[-1] = 1.25
            max_val = 1.25
        else:
            val_per_level = _round_float(raw_val, 8)
            rank_vals = [_round_float(raw_val * (r + 1), 6) for r in range(max_rank + 1)]
            max_val = rank_vals[-1]
        upgrades.append(
            {
                "type": utype,
                "operation": u.get("OperationType"),
                "value": _round_float(val_per_level, 8),
                "maxValue": max_val,
                "rankValues": rank_vals,
                "damageType": u.get("DamageType") or "DT_ANY",
            }
        )
    return upgrades


def _extract_scripts(pkg_row: dict[str, Any]) -> list[dict[str, Any]]:
    ability = pkg_row.get("Ability") or {}
    blocks = [event.get("scriptInstance") or {} for event in ability.get("AbilityEvents") or ()]
    blocks.append(ability.get("Script") or {})
    blocks.extend(extra.get("scriptInstance") or {} for extra in ability.get("SecondaryScripts") or ())
    blocks.append(pkg_row.get("Script") or {})
    for u in pkg_row.get("Upgrades") or ():
        if isinstance(u.get("LocKeyWordScript"), dict):
            blocks.append(u["LocKeyWordScript"])
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        params = {
            k: (_round_float(v) if isinstance(v, float) else v)
            for k, v in block.items()
            if k.startswith("_")
            and (
                (isinstance(v, (int, float)) and not isinstance(v, bool))
                or (isinstance(v, list) and v and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v))
            )
        }
        key = (str(block.get("Function") or ""), str(block.get("Script") or ""))
        if params and key not in seen:
            seen.add(key)
            out.append({"function": key[0], "script": key[1], "params": params})
    return out


def _build_precept_spec(
    path: str, pkg_row: dict[str, Any], scripts: list[dict[str, Any]], level_stats_en: list[str]
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "isAttackPrecept": False,
        "attackRange": None,
        "sustainRange": None,
        "cooldown": None,
        "usesWeaponZoom": False,
        "usesMeleeRange": False,
        "damage": None,
        "damageType": None,
        "procChance": None,
        "forcedProc": None,
        "radius": None,
        "maxTargets": None,
        "playerBuff": None,
    }
    ability = pkg_row.get("Ability") or {}
    cd = ability.get("CooldownDuration")
    if isinstance(cd, (int, float)) and cd > 0:
        spec["cooldown"] = _round_float(cd)

    merged_params: dict[str, Any] = {}
    for b in scripts:
        merged_params.update(b["params"])

    for rkey in ("_maxDistance", "_maxRange", "_range", "_searchDistance"):
        val = merged_params.get(rkey)
        if isinstance(val, (int, float)) and val > 0 and spec["attackRange"] is None:
            spec["attackRange"] = _round_float(val)
        elif isinstance(val, list) and val and spec["attackRange"] is None:
            spec["attackRange"] = _round_float(val[-1])

    if level_stats_en:
        max_line = level_stats_en[-1]
        if spec["cooldown"] is None:
            m_cd = re.search(r"(\d+(?:\.\d+)?)s\s*cooldown|cooldown:\s*(\d+(?:\.\d+)?)s|every\s*(\d+(?:\.\d+)?)s", max_line, re.I)
            if m_cd:
                spec["cooldown"] = float(next(g for g in m_cd.groups() if g is not None))
        if spec["attackRange"] is None:
            m_rng = re.search(r"within\s+(\d+(?:\.\d+)?)m", max_line, re.I)
            if m_rng:
                spec["attackRange"] = float(m_rng.group(1))
        if spec["radius"] is None:
            m_rad = re.search(r"(\d+(?:\.\d+)?)m\s+radius|in\s+a\s+(\d+(?:\.\d+)?)m", max_line, re.I)
            if m_rad:
                spec["radius"] = float(next(g for g in m_rad.groups() if g is not None))

    if path in CURATED_PRECEPT_SPECS:
        spec.update(CURATED_PRECEPT_SPECS[path])
    if spec["sustainRange"] is None and spec["attackRange"] is not None:
        spec["sustainRange"] = spec["attackRange"]
    if merged_params:
        spec["scriptParams"] = merged_params
    return spec


def build_mods(
    pkgs: SmartPackages,
    loc: Localizer,
    assets: AssetManager,
    wfsim_data: Path,
    companions: list[dict[str, Any]],
    ancestry_by_companion: dict[str, set[str]],
    claw_ancestry: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build clawMods (30 entries) and bodyMods (135+ entries)."""
    wfsim_entries: dict[str, dict[str, Any]] = {}
    for folder in ("mods/beast_claws", "companion_mods"):
        for f in sorted((wfsim_data / folder).glob("*.yaml")):
            d = yaml.safe_load(f.read_text(encoding="utf-8"))
            wfsim_entries[d["internal_name"]] = d

    # Include any mod in sentinels.json not already in wfsim_entries
    for sm in assets.sentinel_data.get("mods", []):
        if sm["path"] not in wfsim_entries:
            wfsim_entries[sm["path"]] = {"id": sm["path"].rsplit("/", 1)[-1].lower(), "internal_name": sm["path"]}

    all_claw_ancestors = set().union(*claw_ancestry.values())
    sentinel_paths = sorted(c["path"] for c in companions if c["kind"] == "sentinel")

    claw_mods: list[dict[str, Any]] = []
    body_mods: list[dict[str, Any]] = []

    for path, wdoc in sorted(wfsim_entries.items()):
        if not pkgs.exists(path):
            continue
        pkg_row = pkgs.resolve(path)
        en, zh = loc.names(path, pkg_row.get("LocalizeTag"), wdoc.get("name"))
        item = loc.items_mods.get(path) or {}
        zh_i18n = (loc.i18n.get(path) or {}).get("zh") or {}
        level_en = [" ".join(lvl.get("stats") or ()) for lvl in item.get("levelStats") or ()]
        level_zh = [" ".join(lvl.get("stats") or ()) for lvl in zh_i18n.get("levelStats") or ()]

        polarity = _norm_polarity(pkg_row.get("ArtifactPolarity") or wdoc.get("polarity") or item.get("polarity"))
        base_drain = int(wdoc.get("base_drain") if wdoc.get("base_drain") is not None else _base_drain(path, pkg_row))
        max_rank = int(wdoc.get("max_rank") if wdoc.get("max_rank") is not None else _max_rank(path, pkg_row))
        rarity = str(pkg_row.get("Rarity") or wdoc.get("rarity") or "COMMON").upper()
        set_id = pkg_row.get("ModSet") or None
        family = pkgs.mod_family(path)
        upgrades = _extract_upgrades(pkg_row, max_rank)
        scripts = _extract_scripts(pkg_row)
        art_asset = assets.resolve_mod_art(path, pkg_row.get("Icon"), item.get("imageName"))
        assets.verify_asset(art_asset, f"mod {en}")

        ic = str(pkg_row.get("ItemCompatibility") or "")
        if ic in all_claw_ancestors:
            is_posture = "/Stances/" in path or wdoc.get("family") == "beast_posture"
            matching_claws = sorted(cp for cp, anc in claw_ancestry.items() if ic in anc)
            if ic == "/Lotus/Types/Friendly/Pets/BeastPetMeleeWeaponBase":
                compat_kind = "all_beast_claws"
            elif ic == "/Lotus/Types/Friendly/Pets/CatbrowPetMeleeWeapon":
                compat_kind = "kavat_claws"
            elif ic == "/Lotus/Types/Friendly/Pets/KubrowPetMeleeWeapon":
                compat_kind = "kubrow_claws"
            else:
                compat_kind = "breed_exclusive_claws"
            claw_mods.append(
                {
                    "path": path,
                    "id": wdoc.get("id") or en.lower().replace(" ", "_"),
                    "nameEn": en,
                    "nameZh": zh,
                    "rarity": rarity,
                    "polarity": polarity,
                    "baseDrain": base_drain,
                    "maxRank": max_rank,
                    "isPosture": is_posture,
                    "family": family,
                    "setId": set_id,
                    "compat": {
                        "compatKind": compat_kind,
                        "itemCompatibility": ic,
                        "weaponPaths": None if compat_kind == "all_beast_claws" else matching_claws,
                    },
                    "upgrades": upgrades,
                    "scripts": scripts,
                    "levelStatsEn": level_en,
                    "levelStatsZh": level_zh,
                    "artAsset": art_asset,
                }
            )
            continue

        # Body mod compatibility classification
        anc = pkgs.ancestry(path)
        is_precept = bool(
            wdoc.get("precept")
            or "/Lotus/Types/Game/SentinelPrecept" in anc
            or "/VoidBond/" in path
            or path.endswith("Precept")
        )
        owners = sorted(cp for cp, canc in ancestry_by_companion.items() if ic in canc)
        is_link_mod = any(u["type"] in LINK_UPGRADE_TYPES for u in upgrades)

        if ic in ("SentinelPowerSuit", "/Lotus/Types/Game/SentinelPowerSuit"):
            compat_kind = "all"
            owner_paths = None
        elif ic == "/Lotus/Types/Game/Pets/RoboticPetPowerSuit":
            compat_kind = "robotic"
            owner_paths = None
        elif ic == "/Lotus/Types/Sentinels/SentinelPowerSuit":
            compat_kind = "sentinel"
            owner_paths = None
        elif ic == "/Lotus/Types/Game/Pets/PetPowerSuit":
            compat_kind = "beast"
            owner_paths = None
        elif ic == "/Lotus/Types/Friendly/Pets/MoaPets/MoaPetPowerSuit":
            compat_kind = "moa"
            owner_paths = None
        elif ic == "/Lotus/Types/Friendly/Pets/ZanukaPets/ZanukaPetPowerSuit":
            compat_kind = "hound"
            owner_paths = None
        elif ic == "/Lotus/Types/Game/CatbrowPet/CatbrowPetPowerSuit":
            compat_kind = "kavat"
            owner_paths = owners
        elif ic == "/Lotus/Types/Game/KubrowPet/KubrowPetPowerSuit":
            compat_kind = "kubrow"
            owner_paths = owners
        else:
            owner_kinds = {c["kind"] for c in companions if c["path"] in owners}
            if owner_kinds <= {"sentinel"}:
                compat_kind = "sentinel"
            elif owner_kinds <= {"kavat", "vulpaphyla"}:
                compat_kind = "kavat" if owner_kinds == {"kavat"} else "beast"
            elif owner_kinds <= {"kubrow", "predasite", "charger"}:
                compat_kind = "kubrow" if owner_kinds == {"kubrow"} else "beast"
            elif owner_kinds <= {"moa"}:
                compat_kind = "moa"
            elif owner_kinds <= {"hound"}:
                compat_kind = "hound"
            else:
                compat_kind = "all"
            owner_paths = owners

        bond_spec = BOND_SPECS.get(path)
        precept_spec = (
            _build_precept_spec(path, pkg_row, scripts, level_en)
            if (is_precept and bond_spec is None)
            else None
        )

        body_mods.append(
            {
                "path": path,
                "id": wdoc.get("id") or en.lower().replace(" ", "_").replace("'", ""),
                "nameEn": en,
                "nameZh": zh,
                "rarity": rarity,
                "polarity": polarity,
                "baseDrain": base_drain,
                "maxRank": max_rank,
                "family": family,
                "isPrecept": is_precept,
                "isBond": bond_spec is not None,
                "setId": set_id,
                "compat": {
                    "compatKind": compat_kind,
                    "itemCompatibility": ic,
                    "ownerPaths": owner_paths,
                    "blockedPaths": sentinel_paths if is_link_mod else None,
                    "blockedKinds": ["sentinel"] if is_link_mod else None,
                },
                "upgrades": upgrades,
                "scripts": scripts,
                "bondSpec": bond_spec,
                "preceptSpec": precept_spec,
                "levelStatsEn": level_en,
                "levelStatsZh": level_zh,
                "artAsset": art_asset,
            }
        )

    claw_mods.sort(key=lambda m: (not m["isPosture"], m["nameEn"]))
    body_mods.sort(key=lambda m: m["nameEn"])
    return claw_mods, body_mods


def build_weapon_ai_profiles(
    pkgs: SmartPackages, assets: AssetManager, companion_weapons: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    profiles: dict[str, dict[str, Any]] = {}
    for weapon in sorted(companion_weapons, key=lambda w: w["path"]):
        path = weapon["path"]
        pkg_row = pkgs.resolve(path)
        beh = (pkg_row.get("Behaviors") or [{}])[0]
        fire_type = str(beh.get("fire:Type") or "")
        fire = next((v for k, v in beh.items() if k.startswith("fire:") and isinstance(v, dict)), {})
        state = next((v for k, v in beh.items() if k.startswith("state:") and isinstance(v, dict)), {})
        ai = fire.get("AiUsageInfo") or {}
        prefs = ai.get("preferences") or {}
        fp = prefs.get("firingPreferences") or {}

        bt = fp.get("burstTime") or [0.0, 0.0]
        bp = fp.get("burstPauseTime") or [0.0, 0.0]
        des_range = ai.get("desiredAttackRange") or [5.0, 25.0]
        trace_dist = fire.get("traceDistance")
        max_proj = int(state.get("MaxNumProjectiles") or 0)
        default_upgrades = list(pkg_row.get("DefaultUpgrades") or ())
        artax_retarget = "/Lotus/Upgrades/Mods/Sentinel/GremlinColdMod" in default_upgrades

        if path in DECONSTRUCTOR_PATHS:
            category = "deconstructor"
        elif path in HOUND_MELEE_PATHS:
            category = "hound_melee"
        else:
            category = "sentinel_gun"

        portrait = assets.resolve_weapon_portrait(path, pkg_row.get("Icon"))
        assets.verify_asset(portrait, f"companion weapon {weapon.get('nameEn')}")

        profiles[path] = {
            "path": path,
            "nameEn": weapon.get("nameEn"),
            "nameZh": weapon.get("nameZh"),
            "weaponCategory": category,
            "nativeFireBehavior": fire_type,
            "firingType": fp.get("firingType") or "FT_NORMAL",
            "burstTime": [_round_float(bt[0]), _round_float(bt[1])],
            "burstPauseTime": [_round_float(bp[0]), _round_float(bp[1])],
            "onlyFireWithinRange": bool(prefs.get("onlyFireWithinRangeMultiplier")),
            "traceDistance": _round_float(trace_dist) if isinstance(trace_dist, (int, float)) else None,
            "desiredAttackRange": [_round_float(des_range[0]), _round_float(des_range[1])],
            "aimAtPart": str(prefs.get("aimAtPart") or "TORSO"),
            "continuousAim": bool(prefs.get("continuousAim")),
            "artaxRetargetUnchilled": artax_retarget,
            "maxActiveProjectiles": max_proj if max_proj > 0 else None,
            "portraitAsset": portrait,
        }
    return profiles


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    parser.add_argument("--lang-dir", type=Path, default=DEFAULT_LANG_DIR)
    parser.add_argument("--items-dir", type=Path, default=DEFAULT_ITEMS_DIR)
    parser.add_argument("--wfsim-data", type=Path, default=DEFAULT_WFSIM_DATA)
    parser.add_argument("--official-icons", type=Path, default=DEFAULT_OFFICIAL_ICONS)
    parser.add_argument("--extra-icons", type=Path, default=DEFAULT_EXTRA_ICONS)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "mechanics" / "companions-catalog.json")
    args = parser.parse_args()

    pkgs = SmartPackages(args.packages)
    loc = Localizer(args.lang_dir, args.items_dir)
    assets = AssetManager(ROOT, args.official_icons, args.extra_icons, args.items_dir)

    weapons_export = json.loads(
        (ROOT / "data" / "export" / EXPORT_BUILD / "weapons.json").read_text(encoding="utf-8")
    )["data"]
    companion_weapons = [w for w in weapons_export if w.get("slot") == "companion"]

    companions, ancestry_by_companion = build_companions(
        pkgs, loc, assets, args.wfsim_data, companion_weapons
    )
    modular_parts = build_modular_parts(pkgs, loc, assets, args.wfsim_data)
    beast_claws, claw_ancestry = build_beast_claws(pkgs, loc, assets, args.wfsim_data)
    claw_mods, body_mods = build_mods(
        pkgs, loc, assets, args.wfsim_data, companions, ancestry_by_companion, claw_ancestry
    )
    weapon_ai_profiles = build_weapon_ai_profiles(pkgs, assets, companion_weapons)

    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "buildLabel": PACKAGES_BUILD,
        "frozenExportBuild": EXPORT_BUILD,
        "packagesSha256": pkgs.sha256,
        "capacity": {
            "base": 30,
            "reactor": 60,
            "slots": 10,
            "clawSlots": 8,
            "clawPostureSlot": 8,
        },
        "counts": {
            "companions": len(companions),
            "beastClaws": len(beast_claws),
            "clawMods": len(claw_mods),
            "bodyMods": len(body_mods),
            "bondMods": sum(1 for m in body_mods if m["isBond"]),
            "weaponAiProfiles": len(weapon_ai_profiles),
        },
        "companions": companions,
        "modularParts": modular_parts,
        "beastClaws": beast_claws,
        "clawMods": claw_mods,
        "bodyMods": body_mods,
        "weaponAiProfiles": weapon_ai_profiles,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(payload["counts"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
