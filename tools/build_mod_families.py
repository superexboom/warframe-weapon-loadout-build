"""Build authoritative Mod exclusivity families from client Packages.bin_H.

Reproduces the exact Warframe.x64.exe (0x14171CE28 & 0x14118FC40) inheritance
climb over Evolution Engine type definitions:
  1. Resolve relative ``parent`` names by walking upward through parent package
     directories (``resolve_parent_path``).
  2. Climb ``build_ancestry(mod_path, parent_by_path)`` stopping right before
     ``is_generic_mod_base(ancestor)`` (exact match in ``GENERIC_MOD_BASES_EXACT``
     or ``IsA`` inheritance subtree under ``GENERIC_MOD_BASE_SUBTREES``).

Outputs:
  - data/mechanics/mod-families.json
  - Enriches ``modFamily`` on every mod in data/mechanics/sentinels.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from packages_bin import PackagesBin, _u32  # noqa: E402

SCHEMA_VERSION = 1
EXPORT_BUILD = "2026.08.13.13.24"

PACKAGE_CANDIDATES = (
    Path(
        r"C:\Users\SuperExboom\Documents\WF_Rever\research\arbitration-arena-20261116\artifacts\original\Debug\Packages.bin_H"
    ),
    ROOT / "inputs" / "packages" / "Packages.bin_H",
    ROOT / "inputs" / "packages" / "Packages.bin",
    Path(r"E:\warframe\Warframe\Downloaded\Public\Packages.bin_H"),
    Path(r"E:\warframe\Warframe\Downloaded\Public\Packages.bin"),
)

GENERIC_MOD_BASES_EXACT: frozenset[str] = frozenset({
    "/Lotus/Types/Game/LotusArtifactUpgrades/BaseArtifactUpgrade",
    "/Lotus/Types/Game/LotusArtifactUpgrades/BaseAbilityMod",
    "/Lotus/Upgrades/Mods/Melee/Channel/BaseChannelMod",
    "/Lotus/Types/Game/LotusArtifactUpgrade",
    "/Lotus/Types/Game/SentinelPrecept",
    "/Lotus/Types/Game/SentinelPrecept/MoaPetPrecept",
    "/Lotus/Upgrades/Mods/Immortal/ImmortalBaseMod",
    "/Lotus/Upgrades/Mods/DataSpike/Potency/BasePotencyMod",
    "/Lotus/Upgrades/Mods/DataSpike/BaseDataSpikeMod",
    "/Lotus/Upgrades/EmpoweredHeavyMelee/BaseEmpoweredHeavyMeleeMod",
    "/Lotus/Upgrades/Mods/Antiques/BaseAntiqueUpgrade",
    "/Lotus/Types/MeleeTree/MeleeTree",
    "/Lotus/Types/Game/LotusMeleeTree",
    "/Lotus/Types/LotusMeleeTree/LotusMeleeTree",
})

GENERIC_MOD_BASE_SUBTREES: tuple[str, ...] = (
    "/Lotus/Types/Game/BaseCosmeticEnhancer",
    "/Lotus/Upgrades/Mods/Railjack/RailjackBaseMod",
)

EQUIPMENT_ADDITIONAL_BASES: dict[str, list[str]] = {
    "/Lotus/Powersuits/Choir/ChoirBaseSuit": [
        "/Lotus/Types/Game/LotusAuraUpgrade",
        "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestBaseAuraMod",
    ],
    "/Lotus/Powersuits/Choir/Choir": [
        "/Lotus/Types/Game/LotusAuraUpgrade",
        "/Lotus/Upgrades/Mods/Aura/FairyQuest/FairyQuestBaseAuraMod",
    ],
    "/Lotus/Powersuits/Pagemaster/ExaltedBook": [
        "/Lotus/Upgrades/Grimoire/BaseStrikeMod",
        "/Lotus/Upgrades/Grimoire/BaseAuraMod",
    ],
}


def find_packages_bin(explicit: Path | None = None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise FileNotFoundError(f"Packages.bin not found: {explicit}")
        return explicit
    for cand in PACKAGE_CANDIDATES:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        "Could not locate Packages.bin_H / Packages.bin in default locations"
    )


def resolve_parent_path(
    pkg_dir: str, raw_parent: str, all_entities: set[str]
) -> str | None:
    """Resolve an Evolution Engine parent reference by walking upward through folders."""
    if not raw_parent or raw_parent == "None":
        return None
    if raw_parent.startswith("/"):
        if raw_parent == "/Lotus/Types/Sentinels/SentinelPowersuits/SentinelPowerSuit":
            return "/Lotus/Types/Sentinels/SentinelPowerSuit"
        return raw_parent if raw_parent in all_entities else None
    folder = pkg_dir.rstrip("/")
    while True:
        cand = f"{folder}/{raw_parent}" if folder else f"/{raw_parent}"
        if cand == "/Lotus/Types/Sentinels/SentinelPowersuits/SentinelPowerSuit":
            cand = "/Lotus/Types/Sentinels/SentinelPowerSuit"
        if cand in all_entities:
            return cand
        if not folder or "/" not in folder.lstrip("/"):
            cand_root = f"/{raw_parent}"
            return cand_root if cand_root in all_entities else None
        folder = folder.rsplit("/", 1)[0]


def load_directory_hierarchy(
    packages_path: Path,
) -> tuple[set[str], dict[str, str | None], str]:
    """Read all (pkg_dir, entity_path, raw_parent) entries from Packages.bin."""
    pb = PackagesBin(packages_path)
    sha256 = hashlib.sha256(packages_path.read_bytes()).hexdigest()
    d = pb.data
    pos = pb.dir_at
    seen = 0
    raw_records: list[tuple[str, str, str]] = []
    all_entities: set[str] = set()
    while seen < pb.entity_count:
        pkg_len = _u32(d, pos)
        pos += 4
        pkg = str(bytes(d[pos : pos + pkg_len]), "ascii", "replace")
        pos += pkg_len + 1
        children = _u32(d, pos)
        pos += 4
        for _ in range(children):
            if seen >= pb.entity_count:
                break
            name_len = _u32(d, pos)
            pos += 4
            name = str(bytes(d[pos : pos + name_len]), "ascii", "replace")
            pos += name_len + 3
            parent_len = _u32(d, pos)
            pos += 4
            raw_parent = str(bytes(d[pos : pos + parent_len]), "ascii", "replace")
            pos += parent_len
            seen += 1
            full_path = pkg + name
            all_entities.add(full_path)
            raw_records.append((pkg, full_path, raw_parent))

    parent_by_path: dict[str, str | None] = {
        full_path: resolve_parent_path(pkg, raw_parent, all_entities)
        for pkg, full_path, raw_parent in raw_records
    }
    return all_entities, parent_by_path, sha256


def build_ancestry(
    mod_path: str,
    parent_by_path: dict[str, str | None],
    all_entities: set[str] | None = None,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    cur: str | None = mod_path
    while cur and cur not in seen and (all_entities is None or cur in all_entities):
        if cur not in parent_by_path and all_entities is None:
            break
        seen.add(cur)
        out.append(cur)
        cur = parent_by_path.get(cur)
    return out


def is_generic_mod_base(
    ancestor: str,
    parent_by_path: dict[str, str | None],
) -> bool:
    """Exact match against GENERIC_MOD_BASES_EXACT or IsA under GENERIC_MOD_BASE_SUBTREES."""
    if ancestor in GENERIC_MOD_BASES_EXACT:
        return True
    if any(
        ancestor == prefix or ancestor.startswith(prefix + "/")
        for prefix in GENERIC_MOD_BASE_SUBTREES
    ):
        return True
    anc_chain = build_ancestry(ancestor, parent_by_path)
    return any(sub in anc_chain for sub in GENERIC_MOD_BASE_SUBTREES)


def compute_mod_family(
    mod_path: str,
    parent_by_path: dict[str, str | None],
    all_entities: set[str],
) -> str:
    """Climb ancestry from ``mod_path`` and stop right before a generic mod base."""
    chain = build_ancestry(mod_path, parent_by_path, all_entities)
    if not chain:
        return mod_path
    family = chain[0]
    for ancestor in chain[1:]:
        if is_generic_mod_base(ancestor, parent_by_path):
            break
        family = ancestor
    return family


def collect_referenced_mod_paths(
    root: Path,
    all_entities: set[str],
    parent_by_path: dict[str, str | None],
) -> tuple[set[str], list[str]]:
    """Collect every mod path referenced across catalogs plus Grimoire/Tennokai/pkg mods."""
    collected: set[str] = set()
    unreleased_wf_mods: list[str] = []

    wf_path = root / "data" / "warframe_build_data.json"
    if wf_path.is_file():
        wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
        for mod in wf_data.get("mods") or ():
            p = str(mod.get("path") or "").strip()
            if not p:
                continue
            collected.add(p)
            name_en = str(mod.get("nameEn") or "").strip()
            if "/Beginner/" in p or (
                "/Expert/" in p and not name_en.startswith("Primed ")
            ):
                unreleased_wf_mods.append(p)

    export_mods_path = root / "data" / "export" / EXPORT_BUILD / "mods.json"
    if export_mods_path.is_file():
        exp_mods = json.loads(export_mods_path.read_text(encoding="utf-8")).get("data") or ()
        for mod in exp_mods:
            p = str(mod.get("path") or "").strip()
            if p:
                collected.add(p)

    utility_mods_path = root / "data" / "utility_mods.json"
    if utility_mods_path.is_file():
        util_mods = json.loads(utility_mods_path.read_text(encoding="utf-8")).get("mods") or ()
        for mod in util_mods:
            p = str(mod.get("path") or "").strip()
            if p:
                collected.add(p)

    companions_path = root / "data" / "mechanics" / "companions-catalog.json"
    if companions_path.is_file():
        comp_data = json.loads(companions_path.read_text(encoding="utf-8"))
        for key in ("bodyMods", "clawMods"):
            for mod in comp_data.get(key) or ():
                p = str(mod.get("path") or "").strip()
                if p:
                    collected.add(p)

    sentinels_path = root / "data" / "mechanics" / "sentinels.json"
    if sentinels_path.is_file():
        sent_data = json.loads(sentinels_path.read_text(encoding="utf-8"))
        for mod in sent_data.get("mods") or ():
            p = str(mod.get("path") or "").strip()
            if p:
                collected.add(p)

    # Also include all Grimoire Tome mods, Tennokai mods, and any Packages.bin
    # mod inheriting from GENERIC_MOD_BASES_EXACT (excluding StoreItems).
    for entity_path in all_entities:
        if entity_path.startswith("/Lotus/StoreItems/"):
            continue
        if entity_path.startswith(("/Lotus/Upgrades/Grimoire/", "/Lotus/Upgrades/EmpoweredHeavyMelee/")):
            chain = build_ancestry(entity_path, parent_by_path, all_entities)
            if any(anc in GENERIC_MOD_BASES_EXACT for anc in chain):
                collected.add(entity_path)
                continue
        chain = build_ancestry(entity_path, parent_by_path, all_entities)
        if len(chain) > 1 and any(anc in GENERIC_MOD_BASES_EXACT for anc in chain[1:]):
            collected.add(entity_path)

    return collected, sorted(set(unreleased_wf_mods))


def enrich_sentinels_json(sentinels_path: Path, families: dict[str, str]) -> int:
    if not sentinels_path.is_file():
        return 0
    payload = json.loads(sentinels_path.read_text(encoding="utf-8"))
    updated = 0
    for mod in payload.get("mods") or ():
        if not isinstance(mod, dict):
            continue
        p = str(mod.get("path") or "").strip()
        if not p:
            continue
        fam = families.get(p, p)
        if mod.get("modFamily") != fam:
            mod["modFamily"] = fam
            updated += 1
    sentinels_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, default=None)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "mechanics" / "mod-families.json",
    )
    parser.add_argument(
        "--sentinels",
        type=Path,
        default=ROOT / "data" / "mechanics" / "sentinels.json",
    )
    args = parser.parse_args()

    packages_path = find_packages_bin(args.packages)
    all_entities, parent_by_path, sha256 = load_directory_hierarchy(packages_path)
    collected_paths, unreleased_wf_mods = collect_referenced_mod_paths(
        ROOT, all_entities, parent_by_path
    )

    families: dict[str, str] = {}
    for mod_path in sorted(collected_paths):
        families[mod_path] = compute_mod_family(mod_path, parent_by_path, all_entities)

    payload: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "packagesSha256": sha256,
        "counts": {
            "mods": len(families),
            "sharedFamilyMembers": sum(1 for k, v in families.items() if k != v),
            "unreleasedWarframeMods": len(unreleased_wf_mods),
        },
        "equipmentAdditionalBases": EQUIPMENT_ADDITIONAL_BASES,
        "unreleasedWarframeMods": unreleased_wf_mods,
        "families": families,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    sent_updated = enrich_sentinels_json(args.sentinels, families)
    print(
        json.dumps(
            {
                **payload["counts"],
                "sentinelsModsUpdated": sent_updated,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
