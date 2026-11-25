"""Build data/mechanics/ability-rotation-specs.json from client package & animation extracts.

Combines:
1. Per-Warframe InitialEnergy (spawn base energy) for all Warframes and alternate forms from Packages.bin_H.
2. Client-extracted baseCastTimeSec (.fbx_H + Attribs.Rate + Luau PlayAnim) across Warframe & Helminth abilities.
3. Audited 57 buff/augment/energy rotation specs (cost, duration, drain, cast time, recastability, one-handed flags).
4. Authoritative Orb Drop, Orb Conversion, Mod, Companion Bond, Arcane, and Archon Shard economy rules.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = Path(r"C:\Users\SuperExboom\.gemini\antigravity\brain\e0731e82-3e4e-43a7-be41-9137e15fb91e\scratch")
PKG_BIN = SCRATCH / "pkg_live" / "Debug" / "Packages.bin_H"
ANIM_OUT = SCRATCH / "anim_raw"
CLI = Path(
    r"C:\Users\SuperExboom\Documents\WF_Rever\work\warframe-public-export-plus-gen"
    r"\extras\Warframe-Exporter-CLI_Windows.exe"
)
CACHE = Path(r"E:\warframe\Warframe\Downloaded\Public\Cache.Windows")

sys.path.insert(0, str(ROOT / "vendor"))
sys.path.insert(0, str(ROOT / "tools"))


def _norm_path(p: str | None) -> str:
    return str(p or "").strip().replace("\\", "/").rstrip("/")


def main() -> None:
    from import_melee_mechanics import Packages, anim_duration, anim_entity

    wb = json.loads((ROOT / "data/warframe_build_data.json").read_text(encoding="utf-8-sig"))
    forms_path = ROOT / "data/mechanics/warframe-forms.json"
    forms_data = json.loads(forms_path.read_text(encoding="utf-8-sig")) if forms_path.is_file() else {"forms": []}
    syn = json.loads((ROOT / "data/mechanics/warframe-synergy.json").read_text(encoding="utf-8-sig"))
    scratch_specs = json.loads((SCRATCH / "ability_rotation_specs.json").read_text(encoding="utf-8"))

    pkg = Packages(PKG_BIN)

    # 1. Extract InitialEnergy for every Warframe and alternate form
    suit_initial_energy: dict[str, float] = {}
    full_spawn_energy_frames: list[str] = []

    all_suits = [*(wb.get("warframes") or ()), *(forms_data.get("forms") or ())]
    for wf in all_suits:
        if not isinstance(wf, dict):
            continue
        wpath = _norm_path(wf.get("path") or wf.get("id"))
        if not wpath:
            continue
        init_e = 50.0
        if pkg.exists(wpath):
            res = pkg.resolve(wpath)
            if "InitialEnergy" in res and isinstance(res["InitialEnergy"], (int, float)):
                init_e = float(res["InitialEnergy"])
        # Lavos / Hildryn families always have 0 energy pool
        lower_p = wpath.casefold()
        if "/alchemist/" in lower_p or "/shieldmaiden/" in lower_p:
            init_e = 0.0
        if "/priest/" in lower_p:
            full_spawn_energy_frames.append(wpath)
        suit_initial_energy[wpath] = init_e

    # 2. Extract baseCastTimeSec across ALL abilities in warframe_build_data.json + helminth + forms
    all_ability_paths: dict[str, dict[str, Any]] = {}
    for wf in all_suits:
        for ab in wf.get("abilities") or ():
            if isinstance(ab, dict) and ab.get("path"):
                all_ability_paths[_norm_path(ab["path"])] = ab
    for hm in wb.get("helminth") or ():
        if isinstance(hm, dict) and hm.get("path"):
            all_ability_paths.setdefault(_norm_path(hm["path"]), hm)

    anim_candidates_by_ab: dict[str, list[str]] = {}
    needed_anims: set[str] = set()
    for apath in sorted(all_ability_paths):
        if not pkg.exists(apath):
            continue
        try:
            res = pkg.resolve(apath)
        except Exception:
            res = {}
        cands: list[str] = []
        sc = res.get("Script")
        if isinstance(sc, dict):
            # Prefer explicit _activateAnim / _activateStartAnim / _castAnim keys first
            preferred_keys = (
                "_activateAnim",
                "_activateStartAnim",
                "_castAnim",
                "_yinActivateAnim",
                "_yangActivateAnim",
                "_hotAnim",
                "_coldAnim",
            )
            for k in preferred_keys:
                v = sc.get(k)
                if isinstance(v, str) and v and ("/Animations/" in v or v.endswith(".fbx")):
                    ent = anim_entity(pkg, v) or (v if v.endswith(".fbx") else v + "_anim.fbx")
                    if ent not in cands:
                        cands.append(ent)
            for k, v in sc.items():
                if isinstance(v, str) and v and ("/Animations/" in v or v.endswith(".fbx")):
                    if any(bad in k.lower() for bad in ("loop", "idle", "deactivate", "end", "victim", "death", "hit")):
                        continue
                    ent = anim_entity(pkg, v) or (v if v.endswith(".fbx") else v + "_anim.fbx")
                    if ent not in cands:
                        cands.append(ent)
        ro = res.get("ResourceOverrides")
        if isinstance(ro, list):
            for item in ro:
                if isinstance(item, dict):
                    r = item.get("Resource", "")
                    if isinstance(r, str) and ("/Animations/" in r or r.endswith(".fbx")):
                        if any(bad in r.lower() for bad in ("loop", "idle", "deactivate", "victim")):
                            continue
                        ent = anim_entity(pkg, r) or (r if r.endswith(".fbx") else r + "_anim.fbx")
                        if ent not in cands:
                            cands.append(ent)
        anim_candidates_by_ab[apath] = cands
        needed_anims.update(cands)

    anim_debug_root = ANIM_OUT / "Debug"

    def _ensure_anim_hdr(anim_path: str) -> tuple[str, bool]:
        hdr = anim_debug_root / (anim_path.lstrip("/") + "_H")
        if hdr.is_file():
            return anim_path, True
        if not CLI.is_file() or not CACHE.is_dir():
            return anim_path, False
        for pkg_name in ("AnimRetarget", "Misc"):
            subprocess.run(
                [
                    str(CLI),
                    "--write-raw",
                    "--game",
                    "Warframe",
                    "--cache-dir",
                    str(CACHE),
                    "--package",
                    pkg_name,
                    "--internal-path",
                    anim_path,
                    "--output-path",
                    str(ANIM_OUT),
                ],
                capture_output=True,
                timeout=45,
            )
            if hdr.is_file():
                return anim_path, True
        return anim_path, False

    missing_hdrs = sorted(a for a in needed_anims if not (anim_debug_root / (a.lstrip("/") + "_H")).is_file())
    if missing_hdrs:
        print(f"Extracting {len(missing_hdrs)} remaining ability .fbx_H headers...")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(_ensure_anim_hdr, missing_hdrs))

    def _effective_anim_sec(anim_path: str) -> float | None:
        hdr = anim_debug_root / (anim_path.lstrip("/") + "_H")
        raw_dur = anim_duration(anim_debug_root, anim_path) if hdr.is_file() else None
        if raw_dur is None or raw_dur <= 0:
            return None
        rate_mult = 1.0
        if pkg.exists(anim_path):
            try:
                ent = pkg.resolve(anim_path)
                att = ent.get("Attribs") if isinstance(ent.get("Attribs"), dict) else ent
                if isinstance(att.get("Rate"), (int, float)) and float(att["Rate"]) > 0:
                    rate_mult = float(att["Rate"])
            except Exception:
                pass
        return round(float(raw_dur) / rate_mult, 4)

    audited_by_path: dict[str, dict[str, Any]] = {}
    audited_by_id: dict[str, dict[str, Any]] = {}
    for row in scratch_specs.get("abilities") or ():
        ap = _norm_path(row.get("abilityPath"))
        if ap and row.get("category") != "weapon_augment":
            audited_by_path[ap] = row
        elif ap and ap not in audited_by_path:
            audited_by_path[ap] = row
        audited_by_id[str(row["id"])] = row

    # Map synergy abilities & helminthIds & augments cleanly
    syn_abilities_by_path = {_norm_path(s["abilityPath"]): s for s in (syn.get("abilities") or ()) if s.get("abilityPath")}
    syn_augments_by_id = {str(a["id"]): a for a in (syn.get("augments") or ()) if a.get("id")}

    # All-ability cast time lookup (by normalized abilityPath)
    ability_cast_times: dict[str, dict[str, Any]] = {}
    for apath in sorted(all_ability_paths):
        if apath in audited_by_path and audited_by_path[apath].get("baseCastTimeSec") is not None:
            au = audited_by_path[apath]
            ability_cast_times[apath] = {
                "baseCastTimeSec": round(float(au["baseCastTimeSec"]), 4),
                "oneHandedNonBlocking": bool(au.get("oneHandedNonBlocking", False)),
                "recastableWhileActive": bool(au.get("recastableWhileActive", True)),
                "source": "audited_client_fbx_luau",
            }
            continue
        cands = anim_candidates_by_ab.get(apath) or []
        chosen_dur = None
        for c in cands:
            d = _effective_anim_sec(c)
            if d is not None and 0.05 <= d <= 6.0:
                chosen_dur = d
                break
        if chosen_dur is not None:
            ability_cast_times[apath] = {
                "baseCastTimeSec": chosen_dur,
                "oneHandedNonBlocking": False,
                "recastableWhileActive": True,
                "source": "client_fbx_header",
            }

    # Build enriched rotation specs for all 57 audited entries + passive augments + helminth aliases
    rotation_specs: dict[str, dict[str, Any]] = {}

    SPECIAL_ENERGY_EFFECTS: dict[str, dict[str, Any]] = {
        "/Lotus/Powersuits/Devourer/Abilities/DevourerConsumeAbility": {
            "nourishEnergyMultiplierBase": 1.0,
            "nourishHelminthMultiplierBase": 0.6,
        },
        "/Lotus/Powersuits/Gyre/Abilities/GyreEnergizedAbility": {
            "passiveEnergyRegenBase": 1.5,
            "scalesWithStrength": True,
            "killExtendSec": 3.0,
            "maxDurationBaseSec": 60.0,
        },
        "/Lotus/Powersuits/Hoplite/Abilities/HopliteRallyAbility": {
            "passiveEnergyRegenBase": 3.0,
            "scalesWithStrength": True,
        },
        "/Lotus/Powersuits/Nokko/Abilities/NokkoPowerShroomAbility": {
            "pulseEnergyBase": 15.0,
            "helminthPulseEnergyBase": 10.0,
            "pulseIntervalSec": 5.0,
            "scalesWithStrength": True,
        },
        "/Lotus/Powersuits/Odalisk/Abilities/OdaliskDispensaryAbility": {
            "dispensaryCycleSec": 5.0,
            "dispensaryInitialDelaySec": 3.0,
            "dispensaryHealthOrbAmount": 100.0,
            "dispensaryEnergyOrbAmount": 25.0,
            "extraDropChanceBase": 0.25,
        },
        "/Lotus/Powersuits/Werewolf/Abilities/WerewolfLeapAbility": {
            "meleeKillHealthOrbChance": 1.0,
            "helminthMeleeKillHealthOrbChance": 0.5,
            "headshotKillEnergyOrbChance": 1.0,
            "helminthHeadshotKillEnergyOrbChance": 0.5,
        },
        "/Lotus/Powersuits/Geode/Abilities/GeodeShardsAbility": {
            "killHealthOrbChance": 0.50,
            "helminthKillHealthOrbChance": 0.25,
            "killEnergyOrbChance": 0.20,
            "helminthKillEnergyOrbChance": 0.10,
        },
        "/Lotus/Powersuits/Trinity/Abilities/EnergyVampireAbility": {
            "totalPulseEnergyBase": 100.0,
            "scalesWithStrength": True,
        },
        "/Lotus/Powersuits/Runner/Abilities/RunnerRedlineAbility": {
            "castingSpeedBonusBase": 0.50,
            "castingSpeedScalesWithDuration": True,
        },
        "/Lotus/Powersuits/PowersuitAbilities/HelminthStrengthAbility": {
            "nextCastStrengthBonus": 0.50,
        },
    }

    for row in scratch_specs.get("abilities") or ():
        rid = str(row["id"])
        ap = _norm_path(row.get("abilityPath"))
        syn_spec = syn_abilities_by_path.get(ap) or {}
        aug_spec = syn_augments_by_id.get(rid) or {}

        is_channeled = bool(row.get("isChanneled", False))
        drain_sec = float(row.get("energyDrainPerSec") or 0.0)
        # Equinox Provoke has 0/s drain and does NOT call PreventEnergyGain
        prevents_regen = bool(is_channeled and drain_sec > 0.0)

        spec_entry: dict[str, Any] = {
            "id": rid,
            "category": row.get("category"),
            "abilityPath": ap,
            "modPath": aug_spec.get("modPath"),
            "slot": (int(row["slot"]) - 1) if isinstance(row.get("slot"), int) and row["slot"] >= 1 else None,
            "nameZh": row.get("nameZh") or "",
            "nameEn": row.get("nameEn") or rid,
            "isHelminthSubsumable": bool(row.get("isHelminthSubsumable")),
            "baseEnergyCost": float(row.get("baseEnergyCost") or 0.0),
            "isChanneled": is_channeled,
            "energyDrainPerSec": drain_sec,
            "maxEnemiesDrain": row.get("maxEnemiesDrain"),
            "energyDrainPerAbilityCast": float(row.get("energyDrainPerAbilityCast") or 0.0),
            "preventsPassiveEnergyRegen": prevents_regen,
            "baseDurationSec": float(row["baseDurationSec"]) if row.get("baseDurationSec") is not None else None,
            "helminthBaseDurationSec": float(row["helminthBaseDurationSec"]) if row.get("helminthBaseDurationSec") is not None else None,
            "augmentBuffDurationSec": float(row["augmentBuffDurationSec"]) if row.get("augmentBuffDurationSec") is not None else None,
            "invulnerabilityDurationSec": float(row["invulnerabilityDurationSec"]) if row.get("invulnerabilityDurationSec") is not None else None,
            "bonusSecPer100Shields": float(row["bonusSecPer100Shields"]) if row.get("bonusSecPer100Shields") is not None else None,
            "killExtendSec": float(row["killExtendSec"]) if row.get("killExtendSec") is not None else None,
            "cooldownSec": float(row["cooldownSec"]) if row.get("cooldownSec") is not None else None,
            "baseCastTimeSec": round(float(row.get("baseCastTimeSec") or 0.0), 4),
            "oneHandedNonBlocking": bool(row.get("oneHandedNonBlocking", False)),
            "recastableWhileActive": bool(row.get("recastableWhileActive", True)),
            "notes": row.get("notes") or "",
        }
        if ap in SPECIAL_ENERGY_EFFECTS:
            spec_entry["specialEconomy"] = SPECIAL_ENERGY_EFFECTS[ap]

        rotation_specs[rid] = spec_entry

        # Register Helminth ID alias (e.g. roar-helminth, nourish-helminth, eclipse-helminth)
        helm_id = syn_spec.get("helminthId")
        if not helm_id and ap == "/Lotus/Powersuits/Choir/Abilities/ChoirEyesAbility":
            helm_id = "ophanim-eyes-helminth"
        if not helm_id and ap == "/Lotus/Powersuits/Temple/Abilities/TempleShredAbility":
            helm_id = "overdrive-helminth"
        if helm_id and str(helm_id) not in rotation_specs:
            helm_entry = dict(spec_entry)
            helm_entry["id"] = str(helm_id)
            helm_entry["isHelminthVariant"] = True
            if helm_entry.get("helminthBaseDurationSec") is not None:
                helm_entry["baseDurationSec"] = helm_entry["helminthBaseDurationSec"]
            rotation_specs[str(helm_id)] = helm_entry

    # Add the 2 passive augments (valence-formation, biting-frost) explicitly
    rotation_specs["valence-formation"] = {
        "id": "valence-formation",
        "category": "passive_weapon_augment",
        "abilityPath": None,
        "modPath": "/Lotus/Powersuits/Alchemist/AlchemistPassiveAugmentCard",
        "slot": 0,
        "nameZh": "价键连接",
        "nameEn": "Valence Formation",
        "isHelminthSubsumable": False,
        "baseEnergyCost": 0.0,
        "isChanneled": False,
        "energyDrainPerSec": 0.0,
        "preventsPassiveEnergyRegen": False,
        "baseDurationSec": 20.0,
        " scalesDuration": False,
        "fixedDuration": True,
        "cooldownSec": 8.0,
        "baseCastTimeSec": 0.70,
        "oneHandedNonBlocking": False,
        "recastableWhileActive": True,
        "notes": "Lavos 任意技能施放后赋予 20s 固定持续时间的 200% 元素附加伤害与保底异常（Lavos 使用技能冷却而非蓝量）",
    }
    rotation_specs["biting-frost"] = {
        "id": "biting-frost",
        "category": "passive_weapon_augment",
        "abilityPath": None,
        "modPath": "/Lotus/Powersuits/Frost/FrostPassiveAugmentCard",
        "slot": None,
        "nameZh": "刺骨寒霜",
        "nameEn": "Biting Frost",
        "isHelminthSubsumable": False,
        "baseEnergyCost": 0.0,
        "isChanneled": False,
        "energyDrainPerSec": 0.0,
        "preventsPassiveEnergyRegen": False,
        "baseDurationSec": None,
        "baseCastTimeSec": 0.0,
        "oneHandedNonBlocking": True,
        "recastableWhileActive": False,
        "passiveAlwaysOn": True,
        "notes": "被动强化：对冰冻敌人永久生效，无需施放动作与能量消耗",
    }

    orb_economy_rules = {
        "pickups": {
            "smallEnergyOrb": 25.0,
            "largeEnergyOrb": 50.0,
            "healthOrb": 50.0,
            "empoweredHealthOrb": 100.0,
            "universalOrbSmall": {"energy": 25.0, "health": 25.0},
            "universalOrbLarge": {"energy": 50.0, "health": 50.0},
        },
        "enemyDrops": {
            "normalEnemyEnergyOrbChance": 0.10,
            "normalEnemyHealthOrbChance": 0.0,
            "eximusGuaranteedHealthOrbs": 2,
            "eximusGuaranteedEnergyOrbs": 1,
            "eximusAlsoRollsNormalDrop": True,
        },
        "spawnEnergy": {
            "defaultSuitInitialEnergy": 50.0,
            "unusedCapacityMultiplier": 5.0,
            "preparationPath": "/Lotus/Upgrades/Mods/Warframe/AvatarSpawnEnergyMod",
            "preparationBeginnerPath": "/Lotus/Upgrades/Mods/Warframe/Beginner/AvatarSpawnEnergyModBeginner",
            "amberSpawnShardBaseLeaf": "ArchonCrystalUpgradeWarframeStartingEnergy",
            "amberSpawnShardNormal": 0.30,
            "amberSpawnShardTau": 0.45,
        },
        "mods": {
            "equilibriumPath": "/Lotus/Upgrades/Mods/Warframe/AvatarPickupBonusMod",
            "equilibriumBeginnerPath": "/Lotus/Upgrades/Mods/Warframe/Beginner/AvatarPickupBonusModBeginner",
            "energyConversionPath": "/Lotus/Upgrades/Mods/Warframe/EnergyPickupGivesStrengthMod",
            "healthConversionPath": "/Lotus/Upgrades/Tau/HealthPickupGivesArmourMax",
            "energyNexusPath": "/Lotus/Upgrades/Mods/Warframe/AvatarEnergyRegenMod",
            "energySiphonPath": "/Lotus/Upgrades/Mods/Aura/PlayerEnergyRegenAuraMod",
            "dreamersBondPath": "/Lotus/Upgrades/Mods/Aura/PlayerEnergyHealthRegenAuraMod",
            "archonFlowPath": "/Lotus/Upgrades/Mods/Warframe/Kahl/KahlAvatarPowerMaxMod",
            "archonStretchPath": "/Lotus/Upgrades/Mods/Warframe/Kahl/KahlAvatarAbilityRangeMod",
            "ragePath": "/Lotus/Upgrades/Mods/Warframe/AvatarConvertDamageToEnergyMod",
            "hunterAdrenalinePath": "/Lotus/Upgrades/Mods/Sets/Hunter/WarframeHunterAdrenalineMod",
        },
        "companionMods": {
            "synthDeconstructPath": "/Lotus/Upgrades/Mods/Sets/Synth/SentinelSynthDeconstructMod",
            "synthFiberPath": "/Lotus/Upgrades/Mods/Sets/Synth/SentinelSynthFibersMod",
            "duplexBondPath": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/VoidClone",
            "mysticBondPath": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/PreyDrive",
            "seismicBondPath": "/Lotus/Types/Sentinels/SentinelPrecepts/VoidBond/BondedExaltation",
        },
        "arcanes": {
            "arcaneEnergizePath": "/Lotus/Upgrades/CosmeticEnhancers/Utility/GolemArcaneRadialEnergyOnEnergyPickup",
            "arcaneSteadfastPath": "/Lotus/Upgrades/CosmeticEnhancers/Utility/NoCostCastChanceOnCast",
            "arcanePulsePath": "/Lotus/Upgrades/CosmeticEnhancers/Utility/RadialHealOnHealthPickup",
            "arcaneBlessingPath": "/Lotus/Upgrades/CosmeticEnhancers/Defensive/IncreaseMaxHealthOnHealthPickup",
            "moltReconstructPath": "/Lotus/Upgrades/CosmeticEnhancers/Utility/HealAlliesOnEnergySpent",
            "moltEfficiencyPath": "/Lotus/Upgrades/CosmeticEnhancers/Zariman/WarframeOnShieldUptimePowerDuration",
            "moltAugmentedPath": "/Lotus/Upgrades/CosmeticEnhancers/Offensive/PowerStrengthOnKill",
            "arcaneUniversalFalloutPath": "/Lotus/Upgrades/CosmeticEnhancers/Utility/AbilityRadiationProcsCreateUniversalOrbsOnKill",
        },
        "shards": {
            "amberEnergyOrbLeaf": "ArchonCrystalUpgradeWarframeGlobeEffectEnergy",
            "amberEnergyOrbNormal": 0.50,
            "amberEnergyOrbTau": 0.75,
            "amberHealthOrbLeaf": "ArchonCrystalUpgradeWarframeGlobeEffectHealth",
            "amberHealthOrbNormal": 1.00,
            "amberHealthOrbTau": 1.50,
            "violetEquilibriumLeaf": "ArchonCrystalUpgradeEquilibrium",
            "violetEquilibriumNormal": 0.20,
            "violetEquilibriumTau": 0.30,
        },
    }

    out_path = ROOT / "data/mechanics/ability-rotation-specs.json"
    existing_policies: dict[str, Any] = {}
    if out_path.is_file():
        try:
            existing_policies = dict(json.loads(out_path.read_text(encoding="utf-8")).get("abilityPolicies") or {})
        except Exception:
            existing_policies = {}
    if "metamorphosis" in rotation_specs:
        rotation_specs["metamorphosis"]["rotationExcluded"] = True
        rotation_specs["metamorphosis"]["excludedReason"] = "excluded_form_switch"
    if "fractured-blast" in rotation_specs and rotation_specs["fractured-blast"].get("baseDurationSec") is None:
        rotation_specs["fractured-blast"]["baseDurationSec"] = 12.0
        rotation_specs["fractured-blast"]["fixedDuration"] = True

    payload = {
        "schemaVersion": 1,
        "buildLabel": wb.get("buildLabel"),
        "suitInitialEnergy": suit_initial_energy,
        "fullSpawnEnergyFrames": sorted(set(full_spawn_energy_frames)),
        "abilityCastTimes": ability_cast_times,
        "rotationAbilities": rotation_specs,
        "abilityPolicies": existing_policies,
        "orbEconomyRules": orb_economy_rules,
    }

    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote {out_path}: "
        f"suits={len(suit_initial_energy)}, "
        f"allAbilityCastTimes={len(ability_cast_times)}/{len(all_ability_paths)}, "
        f"rotationAbilities={len(rotation_specs)}"
    )


if __name__ == "__main__":
    main()
