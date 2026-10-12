"""Fill in Narin (internal Duelist) in the warframe sidecar.

Narin shipped with Update 44 (2026-09-23), after the pinned 2026.08.13 build.
The row added from the 2026.09.22 engine dump had placeholder names, relative
ability paths, no ability numbers, no art and a mis-mapped polarity list.

Sources, by field:
- client Packages.bin (2026.10.08 cache): ArtifactSlots, MaxEnergy and
  LevelUpgrades (+100 health / shield / energy), ability LocalizeTag /
  LocalizeDescTag / UniquePowerIdentifier, EnergyRequiredToActivate (50 / 75),
  the Neote Helminth recipe; icons extracted from the client Texture cache
  (pass --icons-root);
- Overframe db/items + db/abilities (2026-10-01 build): English ability names
  and which ability is subsumable (Neote). Its ability-stats table has no
  Narin rows yet, and its ArtifactSlots differ from the client's -- the client
  and the wiki agree, so the client wins;
- official wiki ability infoboxes (wiki.warframe.com, read 2026-10-12): every
  ability number below, energy costs, English descriptions and passive;
- warframe.com/zh-hans/game/warframes/narin: Chinese ability names and
  descriptions, frame description.

The passive's Cold bonus is set inside DuelistPassive.lua (it reuses Cyte-09's
elemental-ammo upgrade); no source states the number, so it is described but
not modelled. Neote's Helminth variant has its own description tag whose text
is not available; the row carries the base description, marked text-only.

Usage:
    python tools/supplement_narin.py [--icons-root <extracted Lotus/Interface/Icons>]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIDECAR = ROOT / "data" / "warframe_build_data.json"
ASSETS = ROOT / "frontend" / "assets" / "warframes"
FRAME = "/Lotus/Powersuits/Duelist/Duelist"
ABILITY_ROOT = "/Lotus/Powersuits/Duelist/Abilities/"
SOURCE_URL = ("raw://client-cache/2026.10.08 Packages.bin + https://wiki.warframe.com/w/Narin"
              " + https://www.warframe.com/zh-hans/game/warframes/narin + overframe db/items 2026-10-01")
MODIFIERS = {
    "strength": "AVATAR_ABILITY_STRENGTH",
    "duration": "AVATAR_ABILITY_DURATION",
    "range": "AVATAR_ABILITY_RANGE",
    "efficiency": "AVATAR_ABILITY_EFFICIENCY",
    "none": "NONE",
}

# (key, English label, Chinese label, values by rank, unit, scale)
ABILITIES = [
    dict(
        internal="DuelistThrustAbility", wiki="Neote", nameZh="寒霜疾剑", icon="NarinThrust", power="DUELIST_THRUST",
        tag="DuelistAbilityThrust", cost=25, subsumable=True,
        descriptionEn=("Lunge with Narin's ice rapier Neote, inflicting <DT_FREEZE_COLOR> Cold Damage and <DT_FREEZE_COLOR> Cold "
                       "and <DT_PUNCTURE_COLOR> Puncture Status Effect on foes directly ahead of her.\n\nGain Ice for each enemy hit."),
        description="挥舞 Narin 的细剑寒霜疾剑进行突刺，对正前方敌人造成冰冻伤害以及冰冻和穿刺异常状态。\n\n每击中一个敌人可获得冰能量。",
        stats=[
            ("cold_damage_per_hit", "Cold Damage Per Hit", "每击冰冻伤害", [250, 300, 350, 400], "", "strength"),
            ("hits", "Hits", "命中次数", [5], "", "none"),
            ("total_cold_damage", "Total Cold Damage", "冰冻总伤害", [1250, 1500, 1750, 2000], "", "strength"),
            ("range", "Range", "范围", [9, 10, 11, 12], "m", "range"),
            ("cold_status_per_hit", "Cold Status Per Hit", "每击冰冻异常", [2], "", "none"),
            ("puncture_status_per_hit", "Puncture Status Per Hit", "每击穿刺异常", [1], "", "none"),
            ("ice_per_cast", "Ice Per Cast", "每次施放获得冰能量", [7], "%", "none"),
            ("ice_per_hit", "Ice Per Hit", "每次命中获得冰能量", [0.5], "%", "none"),
        ],
        unresolved=["cone_angle"],
    ),
    dict(
        internal="DuelistRiposteAbility", wiki="Naraemagi", nameZh="冰翎御盾", icon="NarinRiposte", power="DUELIST_RIPOSTE",
        tag="DuelistAbilityRiposte", cost=50,
        descriptionEn=("Recover Shields by absorbing <DT_FREEZE_COLOR> Cold Status Effect from nearby enemies. Gain Overguard if at "
                       "full Shields.\n\nGain Ice for each enemy hit."),
        description="通过吸收附近敌人施加的冰冻异常状态来恢复护盾。如果护盾已满，则获得超宏防护。\n\n每击中一个敌人可获得冰能量。",
        stats=[
            ("shield_per_cold_status", "Shields Restored / Overguard Per Cold Status", "每层冰冻恢复护盾 / 超宏防护", [40, 50, 60, 75], "", "strength"),
            ("overguard_cap", "Overguard Cap", "超宏防护上限", [9000, 11000, 13000, 15000], "", "strength"),
            ("range", "Range", "范围", [10, 12, 13, 14], "m", "range"),
            ("ice_per_cast", "Ice Per Cast", "每次施放获得冰能量", [5], "%", "none"),
            ("ice_per_hit", "Ice Per Hit", "每次命中获得冰能量", [1], "%", "none"),
        ],
        unresolved=[],
    ),
    dict(
        internal="DuelistLeapAbility", wiki="Hakchum", nameZh="鹤影舞坠", icon="NarinLeap", power="DUELIST_LEAP",
        tag="DuelistAbilityLeap", cost=75,
        descriptionEn=("Tap to leap into the air, tap again to land at target location. Applies <DT_FREEZE_COLOR> Cold Damage "
                       "Vulnerability and Status Effect in a large radius upon landing.\n\nGain Ice for each enemy hit."),
        description="轻按可跃向空中，再次轻按即可落在目标位置。落地时，对大范围内的敌人施加冰冻伤害易伤和异常状态效果。\n\n每击中一个敌人可获得冰能量。",
        stats=[
            ("cold_landing_damage", "Cold Landing Damage", "落地冰冻伤害", [400, 600, 800, 1000], "", "strength"),
            ("cold_damage_per_second", "Cold Damage Per Second", "冰暴每秒冰冻伤害", [100], "", "strength"),
            ("cold_vulnerability", "Cold Damage Vulnerability", "冰冻伤害易伤", [120, 130, 140, 150], "%", "strength"),
            ("storm_radius", "Storm Radius", "冰暴半径", [7, 8, 9, 10], "m", "range"),
            ("storm_duration", "Storm Duration", "冰暴持续时间", [15], "s", "duration"),
            ("flight_duration", "Maximum Flight Duration", "最长滞空时间", [3], "s", "none"),
            ("cold_status_on_landing", "Cold Status On Landing", "落地冰冻异常", [6], "", "none"),
            ("cold_status_per_second", "Cold Status Per Second", "每秒冰冻异常", [1], "", "none"),
            ("ice_per_hit", "Ice Per Hit", "每次命中获得冰能量", [1], "%", "none"),
        ],
        unresolved=[],
    ),
    dict(
        internal="DuelistBladeDanceAbility", wiki="Nurinarim", nameZh="降灵旋刃", icon="NarinBladeDance", power="DUELIST_DANCE",
        tag="DuelistAbilityBladedance", cost=25,
        descriptionEn=("Requires full Ice to cast. An ancestral spirit descends upon Narin and she begins sword dancing for "
                       "continuous nearby damage. Press Attack to launch shattering icy slashes that deplete Armor and Shields. "
                       "Hitting Frozen enemies causes them to explode, dealing massive radial <DT_FREEZE_COLOR> Cold Damage. "
                       "Attacks on Marked Targets cost no Ice and do more damage."),
        description=("需要满冰能量才能施放。先祖之灵降临在 Narin 身上，她随即开始剑舞，对周围敌人造成持续伤害。按下攻击键即可发射粉碎性的冰刃斩击，"
                     "削弱其护甲和护盾。击中被冻结的敌人会使其爆炸，造成大范围冰冻伤害。攻击被标记的目标不消耗冰能量，并造成更高伤害。"),
        stats=[
            ("cold_radial_damage", "Ice Aura Cold Damage Per Second", "冰霜光环每秒冰冻伤害", [200, 300, 400, 500], "", "strength"),
            ("icy_slash_damage", "Icy Slash Cold Damage", "冰刃斩击冰冻伤害", [12500, 15000, 17500, 20000], "", "strength"),
            ("explosion_damage", "Frozen Explosion Cold Damage", "冻结爆炸冰冻伤害", [6250, 7500, 8750, 10000], "", "strength"),
            ("shield_armor_reduction", "Shield And Armor Reduction Per Cold Status", "每层冰冻削减护盾与护甲", [2, 3, 4, 5], "%", "strength"),
            ("aura_radius", "Ice Aura Radius", "冰霜光环半径", [6, 7, 7, 8], "m", "range"),
            ("explosion_range", "Frozen Explosion Range", "冻结爆炸范围", [7, 8, 9, 10], "m", "range"),
            ("max_duration", "Maximum Duration", "最长持续时间", [20], "s", "duration"),
            ("marked_target_multiplier", "Damage On Marked Target", "被标记目标伤害倍率", [2], "x", "none"),
            ("radial_status_chance", "Radial Status Chance", "光环触发几率", [200], "%", "none"),
            ("ice_per_unmarked_slash", "Ice Cost Per Unmarked Slash", "未标记斩击冰能量消耗", [2], "%", "none"),
            ("slash_travel", "Icy Slash Travel Distance", "冰刃斩击射程", [60], "m", "none"),
            ("targeting_radius", "Targeting Radius", "标记半径", [50], "m", "none"),
            ("targeting_duration", "Targeting Duration", "标记时间", [3], "s", "none"),
        ],
        unresolved=[],
    ),
]
PASSIVE_EN = ("Each stack of Cold Status Effect on enemies increase chance to spawn Sangodae pickup by 1%, granting Extra Cold "
              "Damage on Primary and Secondary weapons for 10s. Narin also gains Cold Damage for her abilities.")
# No official Chinese passive text is published outside the client's language
# package; this is a translation of the wiki text above.
PASSIVE_ZH = ("敌人身上每层冰冻异常状态使 Sangodae 拾取物的生成几率提高 1%，拾取后 10 秒内主要武器和次要武器获得额外冰冻伤害。"
              "Narin 的技能也获得冰冻伤害。")
DESCRIPTION_EN = ("Narin descends in swirling eddies, her blade keen and deadly as an icy wind, and she wields ice to defend as "
                  "deftly as her swift rapier strikes.")
DESCRIPTION_ZH = "Narin 如旋涡般降临，她的利刃锋利无比，如同凛冽的寒风。她能巧妙地运用冰霜防御，如同她迅捷的细剑攻击一般。"


def scalar(order: int, key: str, en: str, zh: str, ranks: list[float], unit: str, scale: str) -> dict:
    final = ranks[-1]
    return {
        "id": f"{key}_{order}", "label": en, "labelEn": en, "labelZh": zh,
        "valueTemplate": "{}" + unit, "valueKeys": ["val1"], "parts": {"val1": final}, "values": [final],
        "rankCount": len(ranks), "base": final, "unit": unit, "scale": scale, "modifier": MODIFIERS[scale],
        "group": None, "variant": None, "displayOrder": order, "isStatic": scale == "none",
        "isEnergy": key == "energy_cost", "sourceKind": "wiki", "rankValues": list(ranks),
    }


def ability_row(slot: int, spec: dict, fetched: str) -> dict:
    path = ABILITY_ROOT + spec["internal"]
    rows = [scalar(0, "energy_cost", "Energy Cost", "能量消耗", [spec["cost"]] * 4, "", "efficiency")]
    rows += [scalar(i + 1, *stat) for i, stat in enumerate(spec["stats"])]
    wiki = f"https://wiki.warframe.com/w/{spec['wiki']}"
    return {
        "id": path, "path": path, "slot": slot, "canonicalId": path, "canonicalSource": path,
        "postBuildSupplement": "Update 44 (2026-09-23)",
        "nameEn": spec["wiki"], "nameZh": spec["nameZh"],
        "description": spec["description"], "descriptionEn": spec["descriptionEn"],
        "nameTag": f"/Lotus/Language/Iceblade/{spec['tag']}Name", "descriptionTag": f"/Lotus/Language/Iceblade/{spec['tag']}Desc",
        "iconAsset": f"/assets/warframes/abilities/{spec['icon']}.png",
        "energyCost": {"activation": spec["cost"], "resource": "energy", "sourceKind": "wiki"},
        "scalars": rows, "scalarGroups": [],
        "supportLevel": "partial" if spec["unresolved"] else "full", "unresolvedFields": list(spec["unresolved"]),
        "validForCalculation": True,
        "sourceEvidence": [
            {"kind": "wiki", "url": wiki, "title": spec["wiki"]},
            {"kind": "packages", "path": path, "available": True, "uniquePowerIdentifier": spec["power"],
             "build": "client-cache 2026.10.08"},
            {"kind": "official-site", "url": "https://www.warframe.com/zh-hans/game/warframes/narin", "field": "nameZh/description"},
        ],
        "sourceRevision": "client 2026.10.08 + wiki 2026-10-12", "sourceUrl": wiki, "fetchedAt": fetched,
        "officialExportVersion": None, "parserHash": None, "localizationHash": None,
        "localizationSource": "warframe.com/zh-hans (official)",
    }


def copy_icons(icons_root: Path) -> list[str]:
    from PIL import Image

    written = []
    (ASSETS / "abilities").mkdir(parents=True, exist_ok=True)
    for spec in ABILITIES:
        source = icons_root / "Abilities" / f"{spec['icon']}.png"
        image = Image.open(source).convert("RGBA").resize((128, 128), Image.LANCZOS)
        target = ASSETS / "abilities" / f"{spec['icon']}.png"
        image.save(target, optimize=True)
        written.append(str(target.relative_to(ROOT)))
    portrait = Image.open(icons_root / "StoreIcons" / "Warframes" / "Narin.png").convert("RGBA")
    target = ASSETS / "portraits" / "Narin.png"
    portrait.save(target, optimize=True)
    written.append(str(target.relative_to(ROOT)))
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--icons-root", type=Path, help="extracted client Lotus/Interface/Icons folder")
    args = parser.parse_args()
    fetched = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = json.loads(SIDECAR.read_text(encoding="utf-8-sig"))
    frame = next(row for row in data["warframes"] if row["path"] == FRAME)
    abilities = [ability_row(slot, spec, fetched) for slot, spec in enumerate(ABILITIES)]
    frame.pop("_source", None)
    frame.update({
        "nameEn": "Narin", "nameZh": "Narin",
        "description": DESCRIPTION_ZH, "descriptionEn": DESCRIPTION_EN,
        "passive": PASSIVE_ZH, "passiveEn": PASSIVE_EN, "passiveSource": "wiki (en); zh translated",
        "portraitAsset": "/assets/warframes/portraits/Narin.png", "iconAsset": "/assets/warframes/portraits/Narin.png",
        # Client ArtifactSlots [U,U,U,DEFENSE,U,U,U,ATTACK,TACTIC,U,U,U]: slots
        # 0-7 normal, 8 aura, 9 exilus (Ash/Rhino map the same way). The wiki
        # agrees: Naramon aura, Vazarin + Madurai slots, no exilus polarity.
        "slotPolarities": {"aura": "AP_TACTIC", "exilus": None,
                           "normal": [None, None, None, "AP_DEFENSE", None, None, None, "AP_ATTACK"]},
        "auraPolarity": "AP_TACTIC", "exilusPolarity": None,
        "slotPolaritySource": "client Packages.bin 2026.10.08 ArtifactSlots",
        "basePanel": {"health": 270.0, "shield": 550.0, "armor": 165.0, "energy": 200.0, "sprint": 1.1},
        "rank30Panel": {"health": 370.0, "shield": 650.0, "armor": 165.0, "energy": 300.0, "sprint": 1.1},
        "rankGrowth": {"health": 100, "shield": 100, "energy": 100},
        "rankGrowthSource": FRAME + " LevelUpgrades (client 2026.10.08)",
        "abilities": abilities,
        "sourceRevision": "client 2026.10.08", "sourceUrl": SOURCE_URL, "fetchedAt": fetched,
        "provenance": {"addedFrom": "engine-dump-2026.09.22.16.46", "completedBy": "tools/supplement_narin.py"},
    })
    by_path = {row["path"]: index for index, row in enumerate(data["abilities"])}
    for row in abilities:
        if row["path"] in by_path:
            data["abilities"][by_path[row["path"]]] = row
        else:
            data["abilities"].append(row)
    neote = abilities[0]
    helminth = {
        "id": neote["path"], "path": neote["path"], "recipePath": "/Lotus/Types/Recipes/AbilityOverrides/DuelistThrustBlueprint",
        "originFrame": FRAME, "kind": "subsumed", "nameEn": "DuelistThrust", "nameZh": neote["nameZh"],
        "description": neote["description"], "nameTag": neote["nameTag"], "descriptionTag": neote["descriptionTag"],
        "iconAsset": neote["iconAsset"], "energyCost": neote["energyCost"], "scalars": neote["scalars"], "scalarGroups": [],
        "supportLevel": neote["supportLevel"], "unresolvedFields": neote["unresolvedFields"], "scalarSource": "inherited",
        "altered": {}, "alteredDescription": neote["description"], "alteredSupportLevel": "text-only",
        "validForCalculation": True, "sourceEvidence": neote["sourceEvidence"], "sourceRevision": neote["sourceRevision"],
        "sourceUrl": neote["sourceUrl"], "fetchedAt": fetched, "officialExportVersion": None, "parserHash": None,
        "localizationHash": None, "localizationSource": neote["localizationSource"],
    }
    existing = next((i for i, row in enumerate(data["helminth"]) if row["path"] == helminth["path"]), None)
    if existing is None:
        data["helminth"].append(helminth)
    else:
        data["helminth"][existing] = helminth
    data.setdefault("counts", {})["abilities"] = len(data["abilities"])
    data["counts"]["helminth"] = len(data["helminth"])
    # The sidecar's own format (1-space indent, CRLF, no trailing newline): an
    # unchanged file round-trips byte for byte, so the diff is only Narin.
    SIDECAR.write_bytes(json.dumps(data, ensure_ascii=False, indent=1).replace("\n", "\r\n").encode("utf-8"))
    print(f"Narin: {len(abilities)} abilities, {sum(len(a['scalars']) for a in abilities)} scalars; "
          f"abilities {len(data['abilities'])}, helminth {len(data['helminth'])}")
    if args.icons_root:
        for path in copy_icons(args.icons_root):
            print("wrote", path)


if __name__ == "__main__":
    main()
