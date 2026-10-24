"""Extract exalted (ability-summoned) weapons into the frozen weapons export.

Exalted weapons are ordinary weapon records under ``/Lotus/Powersuits/**``
with ``IsAbilityWeapon = 1``. Player versions are ``MarketMode = MM_HIDDEN``
(templates, NPC copies and the Oraxia / Caliban summons are not). They sit
on the normal weapon bases (PlayerMeleeWeapon, LotusPistol, LotusRifle,
LotusCustomAimWeapon...), so ``extract._build_weapon`` reads them like any
other weapon; the base class picks the slot and with it the MOD pool.

The StoreItems-driven export skips them because they have no store entry.
This tool builds them with the same code path into the sidecar
``exalted_weapons.json`` next to weapons.json (``simulator.load_exports``
appends it to the weapon list), tagging each row with ``exalted``:

* ``framePaths``: suits whose resolved AdditionalItems / SpecialSlotItem
  carry the weapon (the Prime frame gets the Prime weapon);
* ``abilitySlot``: the ability (0-3) that summons or casts it, from the
  table below (packages do not link abilities to their weapon);
* ``tier``: ``weapon`` (fights like a normal weapon), ``strength`` (damage
  also scales with Ability Strength), ``cast`` (one cast = one attack:
  Whipclaw, Shattered Lash, Landslide, Blade Storm) or ``always``
  (Garuda's Talons, no summon).

Usage (repo root):
    python -X utf8 tools/extract-exalted-weapons.py            # write .local/tmp-exalted-merge.json + summary
    python -X utf8 tools/extract-exalted-weapons.py --apply    # write data/export/<build>/exalted_weapons.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "vendor"))

import wfarsenal.extract as extract_mod  # noqa: E402
from wfarsenal import packages as packages_mod  # noqa: E402
from wfarsenal.localization import LocalizationCatalog, apply_localizations  # noqa: E402

DEFAULT_RAW = REPO.parent / "WF_Rever" / "wf-arsenal" / "data" / "raw" / "2026.08.13.13.24"
DEFAULT_LANGUAGES = REPO.parent / "WF_Rever" / "research" / "wf-arsenal-external-sources" / "work" / "warframe-languages-bin-data"
WEAPONS = REPO / "data" / "export" / "2026.08.13.13.24" / "weapons.json"
SIDECAR = WEAPONS.with_name("exalted_weapons.json")
MERGE_FILE = REPO / ".local" / "tmp-exalted-merge.json"

# Suit folder -> (ability slot, tier). Ability slots checked against
# data/warframe_build_data.json ability names (Exalted Blade = 3, Whipclaw = 0...).
FAMILIES: dict[str, tuple[int | None, str]] = {
    "Excalibur": (3, "weapon"),      # Exalted Blade
    "Berserker": (3, "weapon"),      # Hysteria (Valkyr Talons)
    "MonkeyKing": (3, "weapon"),     # Primal Fury (Iron Staff)
    "Pacifist": (3, "weapon"),       # Serene Storm (Desert Wind), Restraint
    "Fairy": (3, "weapon"),          # Razorwing (Dex Pixia / Diwata)
    "Ranger": (3, "weapon"),         # Artemis Bow
    "Frumentarius": (3, "weapon"),   # Neutralize (Cyte-09)
    "Temple": (3, "weapon"),         # Exalted Solo
    "Choir": (3, "weapon"),          # Glory On High (Jade)
    "Pagemaster": (0, "weapon"),     # Noctua (Dante)
    "Cowgirl": (3, "strength"),      # Peacemaker (Regulators)
    "Wraith": (3, "strength"),       # Exalted Shadow (Sevagoth claws), Death Well
    "IronFrame": (0, "strength"),    # Balefire (Hildryn), shields
    "Khora": (0, "cast"),            # Whipclaw
    "Glass": (0, "cast"),            # Shattered Lash
    "Brawler": (0, "cast"),          # Landslide
    "Ninja": (3, "cast"),            # Blade Storm
    "Garuda": (None, "always"),      # Garuda Talons
}

MELEE_BASES = ("/Lotus/Types/Game/LotusMeleeWeapon",)
SECONDARY_BASES = ("/Lotus/Weapons/Tenno/Pistol/LotusPistol", "/Lotus/Types/Weapon/LotusCustomAimWeapon")
PRIMARY_BASES = ("/Lotus/Weapons/Tenno/LotusLongGun", "/Lotus/Weapons/Tenno/Rifle/LotusRifle")


def slot_for(ancestry: list[str]) -> str | None:
    for bases, slot in ((MELEE_BASES, "melee"), (SECONDARY_BASES, "secondary"), (PRIMARY_BASES, "primary")):
        if any(base in ancestry for base in bases):
            return slot
    return None


def suit_items(index: packages_mod.PackageIndex, suit: str) -> set[str]:
    obj = index.resolve(suit)
    names = list(obj.get("AdditionalItems") or ())
    names += [v.get("ItemType") for v in (obj.get("SpecialSlotItem") or {}).values() if isinstance(v, dict)]
    folder = suit.rsplit("/", 1)[0]
    return {n if n.startswith("/") else f"{folder}/{n}" for n in names if isinstance(n, str) and n}


def build(raw: Path, languages: Path) -> list[dict[str, Any]]:
    index = packages_mod.load(raw)
    catalogs = {lang: LocalizationCatalog.from_file(languages / f"{lang}.json") for lang in ("en", "zh")}
    frames = json.loads((REPO / "data" / "warframe_build_data.json").read_text(encoding="utf-8"))["warframes"]
    frame_paths = [f["path"] for f in frames]
    owners: dict[str, list[str]] = {}
    for suit in frame_paths:
        for item in suit_items(index, suit):
            owners.setdefault(item, []).append(suit)
    rows = []
    for path in sorted(index.iter_paths("Lotus/Powersuits")):
        weapon = index.resolve(path)
        if weapon.get("IsAbilityWeapon") != 1 or weapon.get("MarketMode") != "MM_HIDDEN":
            continue
        family = path.split("/")[3]
        if family not in FAMILIES:
            continue
        if not owners.get(path):
            # Not carried by any playable frame (the second Umbra blade copy).
            continue
        ancestry = index.ancestry(path)
        slot = slot_for(ancestry)
        if slot is None:
            print(f"skip {path}: unknown base {ancestry[-2:]}", file=sys.stderr)
            continue
        record = extract_mod._build_weapon(index, path, slot, {"ProductCategory": "SpecialItems"}, weapon)
        record = apply_localizations(record, catalogs)
        if "/Lotus/Types/Weapon/LotusCustomAimWeapon" in ancestry and SECONDARY_BASES[0] not in ancestry:
            # Regulators: a CustomAim weapon that takes secondary MODs in game;
            # pistol MOD compatibility is anchored on LotusPistol.
            record["ancestry"] = [*record["ancestry"], SECONDARY_BASES[0]]
        ability_slot, tier = FAMILIES[family]
        record["exalted"] = {
            "family": family,
            "framePaths": sorted(owners.get(path, ())),
            "abilitySlot": ability_slot,
            "tier": tier,
            "meleeTree": weapon.get("MeleeTreeType") or None,
            "icon": weapon.get("Icon") or None,
        }
        rows.append(record)
    return rows


def apply(rows: list[dict[str, Any]]) -> None:
    payload = {
        "schemaVersion": json.loads(WEAPONS.read_text(encoding="utf-8"))["schemaVersion"],
        "buildLabel": WEAPONS.parent.name,
        "count": len(rows),
        "source": "tools/extract-exalted-weapons.py (packages " + DEFAULT_RAW.name + ")",
        "data": sorted(rows, key=lambda r: r["path"]),
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    SIDECAR.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} exalted rows to {SIDECAR.relative_to(REPO)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--languages", type=Path, default=DEFAULT_LANGUAGES)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and MERGE_FILE.is_file():
        rows = json.loads(MERGE_FILE.read_text(encoding="utf-8"))
    else:
        rows = build(args.raw, args.languages)
        MERGE_FILE.parent.mkdir(parents=True, exist_ok=True)
        MERGE_FILE.write_text(json.dumps(rows, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    for row in rows:
        ex = row["exalted"]
        modes = row.get("fireModes") or []
        dmg = (modes[0].get("damage") or {}) if modes else {}
        print(f"{row['nameZh'] or row['nameEn']:<16} {row['slot']:<9} {ex['tier']:<8} slots={len(row['polarities'])} "
              f"frames={len(ex['framePaths'])} modes={len(modes)} total={dmg.get('total')}")
    if args.apply:
        apply(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
