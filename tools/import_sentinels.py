"""Robotic sentinels and the MODs they can equip -> data/mechanics/sentinels.json.

    python tools/import_sentinels.py --packages <raw build dir> --items <warframe-items data dir>

Structure comes from Packages.bin: every playable powersuit under
/Lotus/Types/Sentinels/SentinelPowersuits (Base templates and the Death Squad
NPC excluded), its ArtifactSlots polarities, health / shield / armour
overrides, default weapon, IncompatibleWeapons and default precepts. A MOD
belongs to a sentinel when its ItemCompatibility is one of the sentinel's
ancestors (the shared companion / robotic bases, or one sentinel family for
an exclusive precept) and it has a StoreItems entry (sub-upgrades have none).
Per-rank text (EN / ZH) comes from warframe-items Mods.json + i18n.json; the
script parameters of the precepts are kept for the weapon adapters in
wfarsenal/sentinel.py. MOAs, hounds and beasts are out of scope.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
from split_mod_art import split_one  # noqa: E402
from wfarsenal.extract import _base_drain, _max_rank  # noqa: E402
from wfarsenal.packages import load  # noqa: E402

SUITS = "/Lotus/Types/Sentinels/SentinelPowersuits/"
SENTINEL_BASE = "/Lotus/Types/Sentinels/SentinelPowerSuit"
# Companion / robotic bases every sentinel inherits (ItemCompatibility values
# seen on sentinel MODs; "SentinelPowerSuit" bare is the Bond precepts').
SHARED_COMPAT = ("SentinelPowerSuit", "/Lotus/Types/Game/SentinelPowerSuit",
                 "/Lotus/Types/Game/Pets/RoboticPetPowerSuit", SENTINEL_BASE)
MOD_ROOTS = ("Lotus/Upgrades/Mods", "Lotus/Types/Sentinels/SentinelPrecepts")
PRECEPT_PARENT = "/Lotus/Types/Game/SentinelPrecept"
ITEM_POLARITY = {"madurai": "AP_ATTACK", "vazarin": "AP_DEFENSE", "naramon": "AP_TACTIC", "penjaga": "AP_PRECEPT",
                 "zenurik": "AP_POWER", "unairu": "AP_WARD", "umbra": "AP_UMBRA"}
POLARITY = {"AP_ATTACK": "AP_ATTACK", "AP_DEFENSE": "AP_DEFENSE", "AP_TACTIC": "AP_TACTIC",
            "AP_PRECEPT": "AP_PRECEPT", "AP_POWER": "AP_POWER", "AP_WARD": "AP_WARD", "AP_UMBRA": "AP_UMBRA",
            "AP_UNIVERSAL": None}


def chain(packages, path: str) -> list[str]:
    out = [path]
    while path in packages.parents:
        parent = packages.parents[path]
        # Parents are stored relative to the child's folder when bare.
        if not parent.startswith("/"):
            parent = path.rsplit("/", 1)[0] + "/" + parent
        # The powersuits name their shared template ".../SentinelPowersuits/
        # SentinelPowerSuit", which lives one folder up.
        if parent == SUITS + "SentinelPowerSuit":
            parent = SENTINEL_BASE
        if parent in out:
            break
        out.append(parent)
        path = parent
    return out


def script_blocks(row: dict) -> list[dict]:
    """Every script instance with numeric parameters (per-hit, passive, apply)."""
    ability = row.get("Ability") or {}
    blocks = [event.get("scriptInstance") or {} for event in ability.get("AbilityEvents") or ()]
    blocks += [ability.get("Script") or {}]
    blocks += [extra.get("scriptInstance") or {} for extra in ability.get("SecondaryScripts") or ()]
    blocks += [row.get("Script") or {}]
    out = []
    for block in blocks:
        params = {k: v for k, v in block.items() if k.startswith("_") and isinstance(v, (int, float))}
        if params:
            out.append({"function": str(block.get("Function") or ""), "script": str(block.get("Script") or ""), "params": params})
    return out


def copy_art(official: Path, icon: str | None, target: Path, *, split: bool) -> str | None:
    """Copy one official PNG under ``target`` (mirroring its game path); return its URL."""
    if not icon:
        return None
    source = official / icon.lstrip("/")
    if not source.is_file():
        return None
    relative = icon.lstrip("/") if split else Path(icon).name
    dest = target / relative
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    if split and not (dest.with_suffix(".bg.jpg").is_file() and dest.with_suffix(".fg.png").is_file()):
        split_one(dest)
    return "/" + dest.relative_to(ROOT / "frontend").as_posix()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--items", type=Path, required=True, help="warframe-items data directory (json/ inside)")
    parser.add_argument("--official", type=Path, default=ROOT.parent / "黑猫4.0-5.0/dist/icon/OfficialWarframe",
                        help="official 2D export root holding /Lotus/Interface/... PNGs")
    parser.add_argument("--output", type=Path, default=ROOT / "data/mechanics/sentinels.json")
    args = parser.parse_args()
    packages = load(args.packages)
    items = {row["uniqueName"]: row for row in json.loads((args.items / "json/Mods.json").read_text(encoding="utf-8"))}
    sentinels_items = {row["uniqueName"]: row for row in json.loads((args.items / "json/Sentinels.json").read_text(encoding="utf-8"))}
    i18n = json.loads((args.items / "json/i18n.json").read_text(encoding="utf-8"))

    sentinels = []
    for file in sorted((args.packages / "packages" / SUITS.strip("/")).glob("*.json")):
        path = SUITS + file.stem
        if "Base" in file.stem or "DeathSquad" in file.stem:
            continue
        row = packages.resolve(path)
        if path not in sentinels_items:
            continue
        ancestry = chain(packages, path)
        base = packages.resolve(SENTINEL_BASE)
        item = sentinels_items[path]
        sentinels.append(dict(
            path=path, nameEn=item["name"], nameZh=(i18n.get(path) or {}).get("zh", {}).get("name") or item["name"],
            icon=row.get("Icon"), prime="Prime" in item["name"] or "Prisma" in item["name"],
            health=float(row.get("MaxHealthOverride") or item.get("health") or 0),
            shield=float(row.get("MaxShieldOverride") or item.get("shield") or 0),
            armor=float(row.get("ArmourRatingOverride") or base.get("ArmourRatingOverride") or item.get("armor") or 0),
            slots=[POLARITY.get(p, p) for p in (row.get("ArtifactSlots") or base.get("ArtifactSlots") or [])],
            defaultWeapon=row.get("DefaultWeapon"),
            incompatibleWeapons=list(row.get("IncompatibleWeapons") or ()),
            defaultPrecepts=[u["ItemType"] for u in row.get("DefaultSlottedUpgrades") or () if u.get("ItemType")],
            ancestry=ancestry,
        ))
    families = {s["path"]: set(s["ancestry"]) for s in sentinels}

    mods = []
    for root in MOD_ROOTS:
        for file in sorted((args.packages / "packages" / root).rglob("*.json")):
            path = "/" + file.relative_to(args.packages / "packages").as_posix()[:-5]
            try:
                row = packages.resolve(path)
            except Exception:
                continue
            compat = row.get("ItemCompatibility")
            if not compat:
                continue
            shared = compat in SHARED_COMPAT
            exclusive = [s for s, family in families.items() if compat in family]
            if not shared and not exclusive:
                continue
            if not packages.exists("/Lotus/StoreItems" + path[len("/Lotus"):]):
                continue  # sub-upgrade or unreleased
            item = items.get(path)
            if not item:
                continue  # retired / dev precepts (Swift Deth, Warrior, BoomStick ...)
            zh = (i18n.get(path) or {}).get("zh") or {}
            parents = chain(packages, path)
            mods.append(dict(
                path=path, nameEn=item.get("name") or path.rsplit("/", 1)[-1],
                nameZh=zh.get("name") or item.get("name") or path.rsplit("/", 1)[-1],
                kind="precept" if PRECEPT_PARENT in parents else "mod",
                exclusiveTo=None if shared else sorted(exclusive),
                rarity=str(row.get("Rarity") or "COMMON").title(),
                polarity=row.get("ArtifactPolarity") or ITEM_POLARITY.get(str(item.get("polarity") or "")),
                baseDrain=_base_drain(path, row), maxRank=_max_rank(path, row),
                icon=row.get("Icon"), modSet=row.get("ModSet"),
                upgrades=[dict(type=u.get("UpgradeType"), operation=u.get("OperationType"), value=u.get("Value"),
                               damageType=u.get("DamageType"))
                          for u in row.get("Upgrades") or () if u.get("UpgradeType") not in (None, "NONE")],
                scripts=script_blocks(row),
                levelStatsEn=[" ".join(level.get("stats") or ()) for level in item.get("levelStats") or ()],
                levelStatsZh=[" ".join(level.get("stats") or ()) for level in zh.get("levelStats") or ()],
            ))
    for sentinel in sentinels:
        sentinel.pop("ancestry")
        sentinel["portrait"] = copy_art(args.official, sentinel["icon"], ROOT / "frontend/assets/sentinels", split=False)
    for mod in mods:
        mod["art"] = copy_art(args.official, mod["icon"], ROOT / "frontend/assets/mods/art", split=True)
    args.output.write_text(json.dumps({
        "source": f"Packages.bin {args.packages.name} + warframe-items Mods/Sentinels/i18n",
        "sentinels": sentinels, "mods": mods,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(sentinels)} sentinels, {len(mods)} mods ({sum(m['kind'] == 'precept' for m in mods)} precepts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
