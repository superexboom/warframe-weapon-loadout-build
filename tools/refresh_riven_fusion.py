"""Refresh advanced traits from a package snapshot without replacing dispositions.

Usage: python tools/refresh_riven_fusion.py --raw-packages <packages> --output <riven_templates.json>
"""

from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "tools"))
from wfarsenal.ee import parse_ee
from wfarsenal.riven_fusion import TAG_CODES, available_codes
from generate_riven_templates import _upgrade_rows


def refresh(payload, raw_packages, build_label=None):
    templates = payload["templates"]
    raw = {}
    hashes = {}
    for t in templates:
        p = raw_packages / "Lotus/Upgrades/Mods/Randomized" / (t["id"] + ".txt")
        if not p.is_file():
            p = p.with_suffix(".json")
        if not p.is_file():
            raise ValueError(f"missing template {p}")
        body = p.read_bytes()
        hashes[t["id"]] = hashlib.sha256(body).hexdigest()
        raw[t["id"]] = (
            parse_ee(body.decode("utf-8-sig"))
            if p.suffix == ".txt"
            else json.loads(body)
        )
    for t in templates:
        # The application already uses the canonical weapon type for modular
        # Rivens. Record that alias explicitly instead of inventing raw entries.
        source = t["id"]
        if "ModularMelee" in source:
            source = "PlayerMeleeWeaponRandomModRare"
        if "ModularPistol" in source:
            source = "LotusPistolRandomModRare"
        advanced = []
        for entry in raw[source].get("UpgradeEntries") or []:
            if not entry.get("IsAdvancedTrait"):
                continue
            code = TAG_CODES.get(entry.get("Tag"))
            if not code:
                raise ValueError(f'unknown advanced tag {entry.get("Tag")}')
            advanced.append(
                {
                    "tag": entry["Tag"],
                    "code": code,
                    "isAdvancedTrait": True,
                    "fusionOnly": True,
                    "canBeBuff": bool(entry.get("CanBeBuff")),
                    "canBeCurse": False,
                    "rawCanBeCurse": bool(entry.get("CanBeCurse")),
                    "rarity": entry.get("Rarity"),
                    "icon": entry.get("Icon"),
                    "upgrades": _upgrade_rows(entry, {}),
                    "sourceTemplate": source,
                    "sourceSha256": hashes[source],
                }
            )
        t["stats"] = [
            s
            for s in t["stats"]
            if not s.get("isAdvancedTrait") and not s.get("fusionOnly")
        ] + advanced
        t["advancedTraitSource"] = {
            "template": source,
            "sha256": hashes[source],
            "alias": source != t["id"],
        }
    # Since 2026.10.08 every canonical template publishes its own MergeOptions.
    # A template without them falls back to the rifle table (ranged) or the
    # official workshop pairs (melee), as before.
    melee_tags = {
        "WeaponMeleeDamageMod": "K", "WeaponFireRateMod": "J", "ComboDurationMod": "N",
        "WeaponMeleeRangeIncMod": "T", "WeaponMeleeComboEfficiencyMod": "U",
        "WeaponMeleeComboBonusOnHitMod": "O", "WeaponMeleeFactionDamageGrineer": "G",
        "WeaponMeleeFactionDamageCorpus": "C", "WeaponMeleeFactionDamageInfested": "I",
    }
    canonical = {
        "rifle": "LotusRifleRandomModRare", "shotgun": "LotusShotgunRandomModRare",
        "pistol": "LotusPistolRandomModRare", "archgun": "LotusArchgunRandomModRare",
        "melee": "PlayerMeleeWeaponRandomModRare",
    }

    def merge_options(wtype, template):
        rows = []
        for opt in raw[template].get("MergeOptions") or []:
            tags = [opt.get(k) for k in ("ResultTag", "PrimaryIngredient", "SecondaryIngredient")]
            if not all(tags):
                continue
            mapping = dict(TAG_CODES, **melee_tags) if wtype == "melee" else TAG_CODES
            codes = [mapping.get(k) for k in tags]
            if not all(codes):
                raise ValueError(f"unknown recipe tags {tags}")
            rows.append(
                dict(zip(("result", "primary", "secondary"), codes))
                | dict(zip(("resultTag", "primaryTag", "secondaryTag"), tags))
            )
        return rows

    recipes = []
    for wtype, template in canonical.items():
        allowed = available_codes(payload, wtype)
        own = merge_options(wtype, template)
        if own:
            rows, kind, source = own, "raw-merge-options", template
        elif wtype != "melee":
            rows, kind, source = merge_options("rifle", canonical["rifle"]), "shared-ranged-recipe", canonical["rifle"]
        else:
            rows = [dict(result=r, primary=a, secondary=b) for r, a, b in
                    (("HD", "U", "O"), ("HC", "U", "N"), ("PA", "J", "T"), ("SL", "J", "K"))]
            kind, source = "official-workshop-table", None
        for recipe in rows:
            if recipe["result"] in allowed:
                row = dict(recipe, weaponType=wtype, sourceKind=kind)
                if source:
                    row["sourceTemplate"] = source
                recipes.append(row)
    payload["fusionRecipes"] = recipes
    payload["fusionSchema"] = {
        "extractedFrom": build_label or raw_packages.parent.name,
        "availabilitySource": "canonical-template-IsAdvancedTrait",
        "note": "Missing MergeOptions is not evidence of absent traits. Shared ranged pairs require an explicit advanced result in the target template.",
        "templateHashes": hashes,
    }
    payload["counts"]["statEntries"] = sum(len(t["stats"]) for t in templates)
    payload["counts"]["upgradeRows"] = sum(
        len(s.get("upgrades", [])) for t in templates for s in t["stats"]
    )
    return payload


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--raw-packages", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--build-label")
    a = p.parse_args()
    payload = refresh(
        json.loads(a.output.read_text(encoding="utf-8-sig")), a.raw_packages, a.build_label
    )
    a.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + chr(10),
        encoding="utf-8",
        newline=chr(10),
    )
    print(
        {
            t: sorted(available_codes(payload, t))
            for t in ("rifle", "shotgun", "pistol", "archgun", "melee")
        }
    )


if __name__ == "__main__":
    main()
