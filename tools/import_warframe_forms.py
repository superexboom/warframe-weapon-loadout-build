"""Build independently moddable Warframe forms from frozen client data.

The ordinary Warframe collector only walks a playable suit's four abilities.
Sevagoth's Shadow has a second suit, four different abilities, its own artifact
slots and its own MOD/Arcane loadout.  This focused importer preserves those
records without turning them into standalone entries in the frame picker.

Example (paths are the ones in .local/pipeline-inputs.json):
    python tools/import_warframe_forms.py \
      --raw ../WF_Rever/wf-arsenal/data/raw/2026.08.13.13.24/packages \
      --localization ../WF_Rever/research/wf-arsenal-external-sources/work/warframe-languages-bin-data/zh.json \
      --localization-en ../WF_Rever/research/wf-arsenal-external-sources/work/warframe-languages-bin-data/en.json \
      --items ../WF_Rever/research/wf-arsenal-external-sources/work/warframe-items/data \
      --art-root ../黑猫4.0-5.0/dist/icon/OfficialWarframe \
      --wiki ../WarframeWikiKnowledgeRunner/rollback-cleaning-20260829-014123/work/cleaned \
      --download-missing
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from typing import Any, Mapping
from urllib.parse import unquote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import generate_warframe_data as generator  # noqa: E402

OUTPUT = ROOT / "data" / "mechanics" / "warframe-forms.json"
WRAITH = "/Lotus/Powersuits/Wraith"
REAPER_ABILITIES = (
    ("ReaperGraspAbility", "Embrace"),
    ("ReaperHarvestAbility", "Consume"),
    ("ReaperWailAbility", "Death's Harvest"),
    ("ReaperWraithAbility", "Reunite"),
)
# Overframe's media mirror returns its generic placeholder for these four
# abilities. Use the actual official-Wiki icons instead of accepting a valid
# HTTP response whose pixels are only that placeholder.
WIKI_ABILITY_ICONS = {
    "ReaperGraspAbility": "https://wiki.warframe.com/images/EmbraceIcon%28xWhite%29.png",
    "ReaperHarvestAbility": "https://wiki.warframe.com/images/ConsumeIcon%28xWhite%29.png",
    "ReaperWailAbility": "https://wiki.warframe.com/images/Death%27sHarvestIcon%28xWhite%29.png",
    "ReaperWraithAbility": "https://wiki.warframe.com/images/ReuniteIcon%28xWhite%29.png",
}
ABILITY_LABEL_ZH = {
    "ReaperGraspAbility": {"range_0": "范围", "duration_1": "持续时间"},
    "ReaperHarvestAbility": {
        "range_2": "锁定范围",
        "untargeted_dash_range_3": "未锁定冲刺范围",
        "passive_hitpoint_damage_sp_hp_4": "被动生命/护盾伤害",
        "wiki_misc_confusion_duration_0": "混乱持续时间",
    },
    "ReaperWailAbility": {
        "damage_vulnerability_1": "易伤加成",
        "range_2": "范围",
        "death_well_gain_per_enemy_4": "每个敌人死亡之井充能",
    },
    "ReaperWraithAbility": {"wiki_misc_teleport_range_0": "重聚传送范围"},
}
FORM_SPECS = (
    {
        "path": f"{WRAITH}/Reaper",
        "parent": f"{WRAITH}/Wraith",
        "baseSuit": f"{WRAITH}/ReaperBaseSuit",
        "panelStore": f"{WRAITH}/Reaper",
        "nameSuit": f"{WRAITH}/ReaperBaseSuit",
        "portrait": "/Lotus/Interface/Icons/StoreIcons/Weapons/ExaltedWeapons/WraithReaper.png",
        "exaltedWeapons": [f"{WRAITH}/ReaperMeleeWeapon"],
        "overframe": "https://overframe.gg/items/arsenal/5443/",
    },
    {
        "path": f"{WRAITH}/SevagothShadowPrime",
        "parent": f"{WRAITH}/SevagothPrime",
        "baseSuit": f"{WRAITH}/ReaperBaseSuit",
        # Prime inherits the ordinary Shadow's base panel and supplies its own
        # ArtifactSlots / icon.  Only the parent Warframe's panel is different.
        "panelStore": f"{WRAITH}/Reaper",
        "nameSuit": f"{WRAITH}/SevagothShadowPrime",
        "portrait": "/Lotus/Interface/Icons/StoreIcons/Weapons/ExaltedWeapons/SevagothShadowPrime.png",
        "exaltedWeapons": [f"{WRAITH}/SevagothShadowPrimeClawsWeapon"],
    },
)


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, help="Extracted packages/ directory for the frozen build")
    parser.add_argument("--localization", type=Path, help="Simplified Chinese Languages.bin JSON")
    parser.add_argument("--localization-en", type=Path, help="English Languages.bin JSON")
    parser.add_argument("--items", type=Path, help="warframe-items data/ directory (for image fallback)")
    parser.add_argument("--art-root", type=Path, help="Official Lotus/... image tree")
    parser.add_argument("--wiki", type=Path, help="Frozen official-Wiki page snapshot")
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "warframe_build_data.json")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--download-missing", action="store_true", help="Fetch only missing icons from Overframe's public media mirror")
    parser.add_argument("--check", action="store_true", help="Validate the existing output without rewriting it")
    return parser.parse_args()


def raw_path(root: Path, unique_name: str) -> Path:
    return root.joinpath(*PurePosixPath(unique_name.lstrip("/")).parts).with_suffix(".json")


def raw_json(root: Path, unique_name: str) -> dict[str, Any]:
    path = raw_path(root, unique_name)
    if not path.is_file():
        raise RuntimeError(f"required package record is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def localized(table: Mapping[str, Any], tag: Any, fallback: str = "") -> str:
    return str(table.get(str(tag or "")) or fallback).strip()


def polarities(slots: list[Any]) -> dict[str, Any]:
    if len(slots) < 10:
        raise RuntimeError("alternate form has an incomplete ArtifactSlots vector")
    def polarity(value: Any) -> str | None:
        value = str(value or "")
        return None if value in {"", "AP_UNIVERSAL", "AP_NONE"} else value
    return {
        "aura": polarity(slots[8]),
        "exilus": polarity(slots[9]),
        "normal": [polarity(value) for value in slots[:8]],
    }


def growth(payload: Mapping[str, Any]) -> dict[str, float]:
    aliases = generator.STAT_ALIASES
    result: dict[str, float] = {}
    for upgrade in payload.get("LevelUpgrades") or ():
        if upgrade.get("OperationType") != "ADD_BASE":
            continue
        stat = aliases.get(str(upgrade.get("UpgradeType") or ""))
        value = upgrade.get("Value")
        if stat and isinstance(value, (int, float)) and not isinstance(value, bool):
            result[stat] = result.get(stat, 0.0) + float(value)
    return result


def copy_asset(
    icon_path: str,
    target_dir: Path,
    *,
    items: Path,
    art_root: Path | None,
    download_missing: bool,
    missing: list[str],
) -> str | None:
    name = Path(icon_path).name
    candidates = [items / "img" / name]
    if art_root is not None:
        candidates.insert(0, art_root.joinpath(*PurePosixPath(icon_path.lstrip("/")).parts))
    for source in candidates:
        if source.is_file():
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / name
            target.write_bytes(source.read_bytes())
            return "/" + target.relative_to(ROOT / "frontend").as_posix()
    if download_missing:
        url = "https://media.overframe.gg/v2/512x" + icon_path + ".webp"
        try:
            request = Request(url, headers={"User-Agent": "WF-Riven-Portable alternate-form data importer"})
            with urlopen(request, timeout=45) as response:
                content = response.read()
            if not content.startswith(b"RIFF") or b"WEBP" not in content[:16]:
                raise RuntimeError("response is not a WebP image")
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / (name + ".webp")
            target.write_bytes(content)
            return "/" + target.relative_to(ROOT / "frontend").as_posix()
        except Exception as exc:  # retain a visible data gap instead of a broken image path
            missing.append(f"{url}: {exc}")
    else:
        missing.append(icon_path)
    return None


def download_wiki_icon(url: str, target: Path, missing: list[str]) -> str | None:
    try:
        request = Request(url, headers={"User-Agent": "WF-Riven-Portable alternate-form data importer"})
        with urlopen(request, timeout=45) as response:
            content = response.read()
        if not content.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("response is not a PNG image")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return "/" + target.relative_to(ROOT / "frontend").as_posix()
    except Exception as exc:
        missing.append(f"{url}: {exc}")
        return None


def build_ability(
    leaf: str,
    english_name: str,
    slot: int,
    *,
    raw_root: Path,
    zh: Mapping[str, Any],
    en: Mapping[str, Any],
    wiki: generator.WikiAbilityIndex,
    meta: Mapping[str, Any],
    items: Path,
    art_root: Path | None,
    download_missing: bool,
    missing: list[str],
) -> dict[str, Any]:
    unique_name = f"{WRAITH}/Abilities/{leaf}"
    raw = raw_json(raw_root, unique_name)
    store_name = "/Lotus/StoreItems" + unique_name.removeprefix("/Lotus")
    # Some Shadow abilities only exist in the gameplay package and have no
    # separate StoreItems record; their own localization tags are complete.
    store = raw_json(raw_root, store_name) if raw_path(raw_root, store_name).is_file() else {}
    name_tag = store.get("LocalizeTag") or raw.get("LocalizeTag")
    desc_tag = store.get("LocalizeDescTag") or raw.get("LocalizeDescTag")
    item = {
        "uniqueName": unique_name,
        "name": localized(en, name_tag, english_name),
        "description": localized(en, desc_tag),
        "imageName": Path(str(raw.get("Icon") or "")).name,
    }
    scalars, support, evidence, unresolved = generator.ability_data(raw_root, unique_name, item["name"], wiki)
    scalars, scalar_groups = generator._merge_overframe_fields(unique_name, scalars, item["name"])
    # A generic label such as "damage" can make Overframe's fuzzy matcher
    # consume an unrelated audited row. Re-append only genuinely absent
    # audited fields and normalize their rank vector for the runtime engine.
    audited = []
    for row in generator._documented_ability_scalars(unique_name):
        row = deepcopy(row)
        if not row.get("rankValues") and row.get("values"):
            row["rankValues"] = list(row["values"])
        audited.append(row)
    scalars = generator.merge_ability_fields(scalars, audited)
    for row in scalars:
        if not row.get("rankValues") and row.get("values"):
            row["rankValues"] = list(row["values"])
        label_zh = ABILITY_LABEL_ZH.get(leaf, {}).get(str(row.get("id") or ""))
        if label_zh:
            row["labelZh"] = label_zh
    overframe_evidence = generator.overframe_ability_evidence(unique_name)
    if overframe_evidence:
        evidence.append(overframe_evidence)
    page = generator.ability_wiki_page(item["name"], unique_name, wiki)
    energy_cost = generator._merge_overframe_energy_cost(generator.ability_energy_cost(raw_root, unique_name, page), scalars)
    wiki_icon_target = ROOT / "frontend" / "assets" / "warframes" / "abilities" / unquote(WIKI_ABILITY_ICONS.get(leaf, "x").rsplit("/", 1)[-1])
    if leaf in WIKI_ABILITY_ICONS and download_missing:
        icon = download_wiki_icon(WIKI_ABILITY_ICONS[leaf], wiki_icon_target, missing)
    elif leaf in WIKI_ABILITY_ICONS and wiki_icon_target.is_file():
        # prepare() starts by copying the current runtime assets. Reuse these
        # already-reviewed icons so rebuilding a snapshot needs no network.
        icon = "/" + wiki_icon_target.relative_to(ROOT / "frontend").as_posix()
    else:
        icon = copy_asset(
            str(raw.get("Icon") or ""),
            ROOT / "frontend" / "assets" / "warframes" / "abilities",
            items=items,
            art_root=art_root,
            download_missing=download_missing,
            missing=missing,
        )
    return {
        "id": unique_name,
        "path": unique_name,
        "slot": slot,
        "nameEn": item["name"],
        "nameZh": localized(zh, name_tag, item["name"]),
        "description": localized(zh, desc_tag, item["description"]),
        "descriptionEn": item["description"],
        "nameTag": name_tag,
        "descriptionTag": desc_tag,
        "iconAsset": icon,
        "energyCost": energy_cost,
        "scalars": scalars,
        "scalarGroups": scalar_groups,
        "supportLevel": support,
        "sourceEvidence": evidence,
        "unresolvedFields": unresolved,
        "validForCalculation": bool(scalars),
        **generator.provenance(dict(meta)),
    }


def build_form(
    spec: Mapping[str, Any],
    *,
    raw_root: Path,
    zh: Mapping[str, Any],
    en: Mapping[str, Any],
    wiki: generator.WikiAbilityIndex,
    meta: Mapping[str, Any],
    items: Path,
    art_root: Path | None,
    download_missing: bool,
    missing: list[str],
) -> dict[str, Any]:
    path = str(spec["path"])
    store = raw_json(raw_root, path)
    base_suit_path = str(spec["baseSuit"])
    base_suit = raw_json(raw_root, base_suit_path)
    panel_store = raw_json(raw_root, str(spec["panelStore"]))
    name_suit = raw_json(raw_root, str(spec["nameSuit"]))
    rank_growth = growth(base_suit)
    # PlayerPowerSuit's implicit resource pool is 100.  All other values are
    # explicit package overrides; the ordinary Shadow's resulting rank-30
    # panel is cross-checked against Overframe below.
    base = {
        "health": float(panel_store.get("MaxHealthOverride") or base_suit.get("MaxHealthOverride") or 100),
        "shield": float(base_suit.get("MaxShieldOverride") or 100),
        "armor": float(base_suit.get("ArmourRatingOverride") or 105),
        "energy": float(base_suit.get("MaxEnergy") or 100),
        "sprint": float(store.get("MovementSpeedMultiplier") or 1),
    }
    rank30 = {key: round(value + float(rank_growth.get(key, 0)), 6) for key, value in base.items()}
    slots = polarities(list(store.get("ArtifactSlots") or []))
    abilities = [
        build_ability(
            leaf,
            english_name,
            slot,
            raw_root=raw_root,
            zh=zh,
            en=en,
            wiki=wiki,
            meta=meta,
            items=items,
            art_root=art_root,
            download_missing=download_missing,
            missing=missing,
        )
        for slot, (leaf, english_name) in enumerate(REAPER_ABILITIES)
    ]
    portrait = copy_asset(
        str(spec["portrait"] or store.get("Icon") or ""),
        ROOT / "frontend" / "assets" / "warframes" / "portraits",
        items=items,
        art_root=art_root,
        download_missing=download_missing,
        missing=missing,
    )
    name_tag = name_suit.get("LocalizeTag") or base_suit.get("LocalizeTag")
    desc_tag = name_suit.get("LocalizeDescTag") or base_suit.get("LocalizeDescTag")
    name_en = localized(en, name_tag, "Sevagoth's Shadow")
    return {
        "id": path,
        "path": path,
        "parentFrameId": spec["parent"],
        "parentAbilitySlot": 3,
        "isAlternateForm": True,
        "formKind": "shadow",
        "formLabelEn": "Shadow",
        "formLabelZh": "幽影",
        "nameEn": name_en,
        "nameZh": localized(zh, name_tag, name_en),
        "description": localized(zh, desc_tag),
        "descriptionEn": localized(en, desc_tag),
        "basePanel": base,
        "rank30Panel": rank30,
        "rankGrowth": rank_growth,
        "rankGrowthSource": base_suit_path + " LevelUpgrades",
        "slotPolarities": slots,
        "slotPolaritySource": path + " ArtifactSlots",
        "auraPolarity": slots["aura"],
        "exilusPolarity": slots["exilus"],
        "abilities": abilities,
        "passive": "",
        "passiveEn": "",
        "portraitAsset": portrait,
        "iconAsset": portrait,
        "masteryReq": 0,
        "inheritance": {
            "shardsFromParent": True,
            "invigorationFromParent": True,
            "helminth": False,
        },
        "exaltedWeapons": list(spec.get("exaltedWeapons") or ()),
        "sourceEvidence": [
            {"kind": "packages", "path": path},
            {"kind": "packages", "path": base_suit_path},
            *([{"kind": "overframe", "url": spec["overframe"]}] if spec.get("overframe") else []),
            {"kind": "wiki", "url": "https://wiki.warframe.com/w/Exalted_Shadow"},
        ],
        **generator.provenance(dict(meta)),
    }


def validate(payload: Mapping[str, Any]) -> None:
    forms = payload.get("forms") or ()
    if len(forms) != 2:
        raise RuntimeError(f"expected Sevagoth Shadow and Shadow Prime, got {len(forms)} forms")
    for form in forms:
        if len(form.get("abilities") or ()) != 4:
            raise RuntimeError(f"{form.get('path')} does not have four Shadow abilities")
        if len(form.get("slotPolarities", {}).get("normal") or ()) != 8:
            raise RuntimeError(f"{form.get('path')} has incomplete polarities")
        consume = form["abilities"][1]
        radiation = next((row for row in consume["scalars"] if row.get("id") == "radiation_damage"), None)
        life_steal = next((row for row in consume["scalars"] if row.get("id") == "life_steal_1"), None)
        if not radiation or radiation.get("rankValues") != [1000, 1500, 2000, 2500] or radiation.get("scale") != "strength":
            raise RuntimeError("Consume's complete Strength-scaled Radiation vector was not generated")
        if not life_steal or life_steal.get("rankValues") != [10, 15, 20, 25]:
            raise RuntimeError("Consume's Life Steal rank vector was not preserved")
    normal = forms[0]["rank30Panel"]
    expected = {"health": 370, "shield": 185, "armor": 475, "energy": 150, "sprint": 1.1}
    if any(abs(float(normal[key]) - value) > 1e-6 for key, value in expected.items()):
        raise RuntimeError(f"ordinary Shadow panel disagrees with Overframe/client evidence: {normal}")


def main() -> int:
    options = args()
    if options.check:
        validate(json.loads(options.output.read_text(encoding="utf-8-sig")))
        print(f"OK: {options.output}")
        return 0
    required = ("raw", "localization", "localization_en", "items", "wiki")
    missing_args = [f"--{name.replace('_', '-')}" for name in required if getattr(options, name) is None]
    if missing_args:
        raise RuntimeError("missing required generation arguments: " + ", ".join(missing_args))
    catalog = json.loads(options.catalog.read_text(encoding="utf-8-sig"))
    build_label = str(catalog["buildLabel"])
    zh = json.loads(options.localization.read_text(encoding="utf-8-sig"))
    en = json.loads(options.localization_en.read_text(encoding="utf-8-sig"))
    wiki = generator.WikiAbilityIndex(options.wiki)
    meta = {
        "buildLabel": build_label,
        "sourceUrl": "frozen://packages + frozen://overframe-abilitystats + frozen://wiki",
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "parserHash": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "localizationHash": hashlib.sha256(options.localization.read_bytes()).hexdigest(),
        "localizationSource": "input://languages-zh + input://languages-en",
    }
    missing: list[str] = []
    forms = [
        build_form(
            spec,
            raw_root=options.raw,
            zh=zh,
            en=en,
            wiki=wiki,
            meta=meta,
            items=options.items,
            art_root=options.art_root,
            download_missing=options.download_missing,
            missing=missing,
        )
        for spec in FORM_SPECS
    ]
    payload = {
        "schemaVersion": 1,
        "buildLabel": build_label,
        "generatedAtUtc": meta["fetchedAt"],
        "forms": forms,
        "audit": {"missingAssets": sorted(set(missing))},
    }
    validate(payload)
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(options.output), "forms": [row["nameEn"] for row in forms], "missingAssets": sorted(set(missing))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
