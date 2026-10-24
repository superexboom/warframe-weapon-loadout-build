"""Import weapon innate passives (DefaultUpgrades) the export does not carry.

    python tools/import_weapon_passives.py --scan .local/research/update-2026.10.24/passives.json

The scan (.local/research/update-2026.10.24/scan_passives.py over a live
Packages.bin) resolves every exported weapon's DefaultUpgrades with their
parents. The export only keeps WEAPON_INNATE_UPGRADE elements from them, so a
passive such as Kuva Chakkhurr's +50% headshot damage never reached the
engine. Every upgrade is either modelled here or listed under ``excluded`` with
the reason.

A modelled upgrade keeps its package terms verbatim (Value at rank 0,
operation, damage type, aim and body-part gates). One that is on by default
becomes ``effects``; one with ApplyUpgradesByDefault 0 becomes a
``conditionalEffects`` row naming the replay event that grants it, with its
UpgradeDuration, MaxConditionalStacks, UpgradeChance and StackMode.
CanReproc 0 (the buff cannot be renewed while it runs) becomes ``noRefresh``.
ValidType is dropped: the upgrade sits on its own weapon. Terms the engine
does not score (movement, recoil, gore) are listed per record in ``ignored``.

Existing entries (Gotva Prime ``superCritOnStatus``) are kept.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor"))
from wfarsenal.damage import SUPPORTED_WEAPON_UPGRADE_TYPES  # noqa: E402

# Upgrade (basename) -> how the replay grants it. ``events``: replay signal
# kinds, one conditional row each; ``fireModes``: modes the passive belongs to.
MODELLED = {
    "GremlinColdMod": {},                           # Artax: +20% Cold, post-combination
    "GrnKuvaLichRifleInnateUpgrade": {},            # Kuva Chakkhurr: +50% headshot, additive bracket
    "InfestedRifleInnateUpgrade": {},               # (Coda) Synapse: +20% headshot
    "CernosPrimeInnateMod": {},                     # Cernos Prime: x1.5 headshot, MULTIPLY (own bracket)
    "PrimeDaikyuInnateMod": {},                     # Daikyu Prime: +250% weak-point crit chance
    "AK47WeaponInnateMod": {},                      # AX-52: aimed headshot +400% crit, hip-fire -75% ammo use
    "TnAlchemistShotgunInnateMod": {"fireModes": [0]},   # Cedo: +60% per status (primary fire, ValidType)
    "PrimeCedoWeaponInnateMod": {"fireModes": [0]},      # Cedo Prime
    "GrnDrillScytheInnateUpgrade": {},              # Galariak Prime: +10% final crit chance per status type
    "GrnSharbolaInnateUpgrade": {"typedProcTime": True},   # Slaytra: +100% Bleed duration (ValidProcTypes PT_BLEEDING)
    "TnChoirBowInnateUpgrade": {"typedProcTime": True},    # Evensong: +2 Puncture stacks on its victim (7 at most)
    "TnOdaliskAmmoEfficiencyMod": {},               # Velox: 20% ammo efficiency
    "PrimeVeloxAmmoEfficiencyMod": {},              # Velox Prime
    "TNWQuestTempParacesisSentientFactionDamage": {},   # The New War quest Paracesis only: +60% vs Sentient
    "CrpIgniterPistolInnateMod": {"events": ["on-headshot"]},          # Tenet Spirex reload
    "ScopeGunInnateMod": {"events": ["on-hit"]},                        # Arca Scisco (OnHitPistolNoDots)
    "InfTipedoProcMeleeMod": {"events": ["on-proc"]},                   # Lesion (OnAnyProc)
    "DualVicissInnateMod": {"events": ["proc-DT_GAS"]},                 # Dual Viciss
    "PrimeMagnusInnateUpgrade": {"events": ["on-hit"]},                 # (Ak)Magnus Prime 4% infinite ammo
    "TnQuadSniperInnateMod": {"events": ["on-burst-headshot", "on-headshot-kill"]},  # Perigale (4-round burst)
    "ZhugePrimeReloadFromEmptyMod": {"events": ["on-reload-empty"]},
    "InfBeamPistolReloadFromEmptyMod": {"events": ["on-reload-empty"]},     # Catabolyst -20%
    "CodaCatabolystReloadFromEmptyMod": {"events": ["on-reload-empty"]},
    "TnOdaliskReloadFromEmptyMod": {"events": ["on-reload-empty"]},         # Velox +50%
    "PrimeVeloxReloadFromEmptyMod": {"events": ["on-reload-empty"]},
    "GarudaCrossbowInnateUpgrade": {"events": ["on-headshot-kill"]},        # Nagantaka
    "TnTurbineInnateMod": {"events": ["on-headshot-kill"], "fireModes": [0]},    # Athodai (PistolPrimaryFire...)
    "PrimeAthodaiInnateMod": {"events": ["on-headshot-kill"], "fireModes": [0]},
    # Knell: 3 x (+0.5 crit damage, +20% status). The +0.5 lands on the
    # finished multiplier, `2 x (1 + Crit Damage Mods) + 0.5 x Stacks` (wiki;
    # WFSim notes death_knell_weakpoint_stacks), not the base an ADD feeds.
    "TnPriestPistolInnateModB": {"events": ["on-headshot"],
                                 "remap": {"WEAPON_CRIT_DAMAGE": "RUNTIME_FINAL_CRIT_DAMAGE"}},
    "EntSphereHammerInnateMod": {"events": ["on-melee-heavy-hit"]},         # Ekhein: OnMeleeHeavyHit
    # Amanata (ShrineMaidenNaginata.lua RollRandomUpgrade): a die rolled on
    # equip and every 30 hits replaces the buff, so one face is always up;
    # each face weighs 1/6 and the sixth holds every term. Expected terms, so
    # products between them (crit x status on the sixth face) read low.
    "ShrineMaidenNaginataInnateMod": {"dieAverage": True},
    # Tonkkatt (GrnChainSawTonfa.lua OnApplied): each combo tier gained adds
    # _damageBonusPerStack Heat for 15 s; the cap of 30 is the text's (the
    # record has no MaxConditionalStacks). OnComboReset clears it.
    "GrnChainSawTonfaPassiveDescUpgrade": {
        "events": ["on-combo-tier-increase"], "resetOn": ["on-combo-tier-reset"], "maxStacks": 30,
        "scriptEffects": lambda script: [{"upgradeType": "WEAPON_PERCENT_BASE_DAMAGE_ADDED", "operation": "ADD",
                                          "valuePerRank": script["_damageBonusPerStack"], "damageType": "DT_FIRE"}]},
    # Vinquibus (UpgradeOnRifleHeadshot.lua): each half buffs the OTHER slot.
    # Held permanently on (user, 2026-10-24: the swap that feeds them is not
    # simulated). Ferocity, melee kills -> +100% rifle ammo efficiency, is
    # infinite ammo, the 2026-10-24 client's SET 0; Precision, rifle
    # headshots -> +250% melee damage (wiki), joins the melee damage bucket.
    "TnBayonetMeleeKillBuff": {"alwaysOn": True, "target": "/Lotus/Weapons/Tenno/Bayonet/TnBayonetRifleWeapon",
                               "scriptEffects": lambda script: [{"upgradeType": "WEAPON_AMMO_CONSUME_RATE",
                                                                 "operation": "SET", "valuePerRank": 0}]},
    "TnBayonetRifleHeadshotBuff": {"alwaysOn": True, "target": "/Lotus/Weapons/Tenno/Bayonet/TnBayonetMeleeWeapon",
                                   "scriptEffects": lambda script: [{"upgradeType": "WEAPON_MELEE_DAMAGE",
                                                                     "operation": "STACKING_MULTIPLY",
                                                                     "valuePerRank": script["_damageBonuses"][0]}]},
    # Reconifex (TnBeltFedRifle.lua OnPerfectReload), every reload perfect
    # (user, 2026-10-24): the reload ends at the window's opening,
    # PerfectReloadRange[0] of it (0.22 x 5 s, the wiki's "1 s"), and the
    # magazine it loads fires Heat rounds, the same ElementalAmmo upgrade as
    # Cyte-09's Resupply: a _baseBuffValue Extra Hit with its status forced.
    "TnBeltFedRifleInnateUpgrade": {"perfectReload": True, "events": ["on-reload-complete"],
                                    "scriptEffects": lambda script: [{"upgradeType": "RUNTIME_EXTRA_HIT", "operation": "ADD",
                                                                      "valuePerRank": script["_baseBuffValue"],
                                                                      "damageType": "DT_FIRE", "runtimeChance": 1.0}]},
    # Venato Prime (ProcsOnHit.lua ApplyProcs, _procCount 1 PT_SENTIENT): each
    # status it applies also applies Tau. Tau is Status Chance Vulnerability,
    # +10% status chance received per stack, 10 at most, each stack its own
    # 8 s, the oldest replaced (wiki Damage/Tau_Damage); forced procs gain
    # nothing, which a status-chance MULTIPLY honours.
    "PrimeVentoProcOnProcUpgrade": {"events": ["on-proc"], "maxStacks": 10, "duration": 8, "stackMode": "per-stack",
                                    "scriptEffects": lambda script: [{"upgradeType": "WEAPON_PROC_CHANCE",
                                                                      "operation": "MULTIPLY", "valuePerRank": 1.1}]},
    # Pennant (TnRailjackGreatKatanaWeapon.lua OnBuffApplied): a heavy-attack
    # kill grants _speedBonus attack speed for _baseDuration plus
    # _durationPerComboMultiplier a combo multiplier above 1x (the text's
    # "up to 46 s" at 12x); CanReproc 0.
    "TnRailJackGreatKatanaInnateUpgrade": {
        "events": ["on-melee-heavy-kill"],
        "scriptCondition": lambda script: {"duration": script["_baseDuration"],
                                           "durationPerTier": script["_durationPerComboMultiplier"]},
        "scriptEffects": lambda script: [{"upgradeType": "WEAPON_FIRE_RATE", "operation": script["_speedBonusOp"],
                                          "valuePerRank": script["_speedBonus"]}]},
    # Dorrclave (TnDagathBladeWhip.lua): _numKillsToTrigger kills arm the
    # next _numAttacks attacks with its terms (+100% status chance, flat:
    # "always a status"); the falloff term is a multi-target one.
    "TnDagathBladeWhipInnateMod": {
        "events": ["on-melee-kill"],
        "scriptCondition": lambda script: {"requiredCount": script["_numKillsToTrigger"],
                                           "charges": script["_numAttacks"], "consumeOn": "on-melee-attack"}},
    # Arca Titron (CorpusHammerWeapon.lua): a melee kill adds a stack (5,
    # infinite) of +250% damage to aerial attacks (SymbolFilter CC_AIR), all
    # spent by the next slam; kills during a slam count for the next one. A
    # route without slams never gets it; +2 m radius has no second target.
    "CorpusHammerWeaponInnateMod": {
        "events": ["on-melee-kill"], "airOnly": True, "ignore": ["WEAPON_EXPLOSION_RADIUS"],
        "scriptCondition": lambda script: {"meleeRoutes": ["slam", "slamBullet"],
                                           "lockOn": "on-melee-slam-start", "consumeOn": "on-melee-slam"}},
    # Enkaus (TnInkRifle.lua), every target ink-stained (the Vinquibus rule,
    # user 2026-10-24: a state the sim cannot feed is held on; one alt-fire
    # stains an 8 m area for 20 s): primary fire on it spends no ammo (wiki:
    # "consumes no ammo and restores 0.33 ammo per enemy hit") and it
    # dissolves below 35% health (the text's figure; the script holds none).
    "TnInkRifleWeaponPassiveDescUpgrade": {
        "alwaysOn": True, "fireModes": [0], "executeBelowHealth": 0.35,
        "scriptEffects": lambda script: [{"upgradeType": "WEAPON_AMMO_CONSUME_RATE", "operation": "SET",
                                          "valuePerRank": 0}]},
    # No ConditionalUpgrades of its own: the weapon script grants it beside
    # ModB (its text: 100% ammo efficiency for 2 s after a headshot; WFSim
    # weakpoint_stacks.infinite_ammo).
    "TnPriestPistolInnateMod": {"events": ["on-headshot"]},
}

# Script passives read off their parameters into a weapon-level rule.
SCRIPTED = {
    # GrnOrokinPistol.lua OnHit: a critical hit arms the next shot with
    # _chanceToAddBuff; an armed shot's status chance is SET to _procChance
    # (the weapon text: "when it crits, its next shot has a chance to greatly
    # increase status chance"). Gotva Prime's superCritOnStatus mirrored.
    "GrnOrokinPistolInnateUpgrade": lambda script: {"superStatusOnCrit": {
        "chance": script["_chanceToAddBuff"], "statusChance": script["_procChance"]}},
}

ALREADY = {
    "GrnOrokinRifleInnateUpgrade": "superCritOnStatus in this file (Gotva Prime)",
    "FireRateOnHeadshotPistolMod": "combat-reference.json nativeTriggers dual-toxocyst-frenzy",
    "NokkoArchGunInnateMod": "runtime_adapters (Arbucep multishot-to-damage)",
    "Vesper77InnateUpgrade": "sniper-mechanics.json zoom effects (aimed +40% crit damage)",
    "GrnChainSawTonfaComboResetUpgrade": "the resetOn of GrnChainSawTonfaPassiveDescUpgrade (OnComboReset)",
    "ShrineMaidenNaginataInnateModB": "the equip roll of ShrineMaidenNaginataInnateMod's die (same faces, one average)",
}

REASONS = {
    "1999InfShotgunInnateMod": "granted by a Mercy kill",
    "1999InfSporePistolInnateMod": "x1.5 on spore-marked enemies (WEAPON_MARKED_DAMAGE_AMOUNT); spores come from other kills",
    "1999InfSPorePistolOnKillUpgrade": "spore spread on kill (other enemies)",
    "SpiderWhipInnateUpgrade": "explosion on kill (other enemies)",
    "CrpBriefcase2HKatanaInnateUpgrade": "parry angle",
    "TnBayonetMeleeAttackBuff": "melee actions charging the rifle's next shot (_damageBonuses 0.5..3): no text, the wiki names no such mechanic",
    "TnBayonetRifleConsumeAmmoBuff": "the rifle-shot half of TnBayonetMeleeAttackBuff (same undocumented mechanic)",
    "TnChoirBowAuraMod": "ally aura on kill",
    "TnChoirScytheAuraMod": "ally aura on kill",
    "TnChoirKunaiAuraMod": "ally aura on hit",
    "InnateShrineMaidenAssistMod": "shield on assist",
    "TnGrimoireInnateUpgrade": "ammo pickup script",
    "InfestedKogakeUpgrade": "life steal and health",
    "EvoDaggerVoidFinisherBuff": "damage taken",
    "RVDarkDaggerInnateUpgrade": "enemy detection range",
    "UmbraAbilityCastUpgrade": "ability-cast script",
    "SMSydonSpecialUpgrade": "blinding script",
    "NLMagistarLifeStrikeAOEMod": "healing script",
    "CreateSpectreOnKill": "spectre on kill",
    "DaxDuviriTwoHandKatanaInnateMod": "combo on slam script",
    "ExaltedBookInnateUpdate": "tome slots",
    "CrpLaserPistolVandalInnateMod": "ricochet",
    "ThrowingHammerInnateMod": "throw reflection",
}


def basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def term(raw: dict) -> dict:
    out = {"upgradeType": raw["UpgradeType"], "operation": raw.get("OperationType") or "ADD",
           "valuePerRank": raw.get("Value", 0)}
    if raw.get("DamageType") and raw["DamageType"] != "DT_ANY":
        out["damageType"] = raw["DamageType"]
    for key, field in (("SymbolFilter", "symbolFilter"), ("ValidModifiers", "validModifiers"),
                       ("InvalidModifiers", "invalidModifiers"), ("ValidPostures", "validPostures"),
                       ("ValidProcTypes", "validProcTypes")):
        if raw.get(key):
            out[field] = raw[key]
    return out


def record(row: dict, spec: dict, zh_names: dict) -> dict:
    fields = row.get("fields") or {}
    terms, ignored = [], []
    for raw in row["effects"]:
        kind = raw.get("UpgradeType")
        if kind in (None, "NONE", "WEAPON_INNATE_UPGRADE"):
            continue
        out_term = term(raw)
        if kind in (spec.get("remap") or {}):
            out_term = {**out_term, "upgradeType": spec["remap"][kind], "packageUpgradeType": kind}
        (terms if kind in SUPPORTED_WEAPON_UPGRADE_TYPES else ignored).append(out_term)
    # nameEn / nameZh label the replay's trigger rows like a mod's.
    out = {"path": row["upgrade"], "name": basename(row["upgrade"]), "nameEn": row["weapon"] + " passive",
           "nameZh": (zh_names.get(row["weaponPath"]) or row["weapon"]) + "·固有被动"}
    if spec.get("fireModes"):
        out["fireModes"] = spec["fireModes"]
    if spec.get("executeBelowHealth"):
        out["executeBelowHealth"] = spec["executeBelowHealth"]
    if spec.get("typedProcTime"):
        # One status type's duration or stack cap (ValidProcTypes), keyed by
        # its damage type: RUNTIME_TYPED_PROC_TIME / RUNTIME_TYPED_PROC_MAX_STACK.
        typed_types = {"WEAPON_PROC_TIME": "RUNTIME_TYPED_PROC_TIME", "WEAPON_PROC_MAX_STACK": "RUNTIME_TYPED_PROC_MAX_STACK"}
        terms = [{"upgradeType": typed_types[raw["UpgradeType"]], "operation": raw.get("OperationType"),
                  "valuePerRank": raw.get("Value", 0), "damageType": PROC_DAMAGE_TYPES[proc],
                  "packageUpgradeType": raw["UpgradeType"]}
                 for raw in row["effects"] if raw.get("UpgradeType") in typed_types and raw.get("ValidProcTypes")
                 for proc in raw["ValidProcTypes"]]
    if spec.get("scriptEffects"):
        terms = spec["scriptEffects"](row.get("script") or {})
    if spec.get("ignore"):
        ignored += [t for t in terms if t["upgradeType"] in spec["ignore"]]
        terms = [t for t in terms if t["upgradeType"] not in spec["ignore"]]
    if spec.get("airOnly"):
        # Aerial attacks only: the condition's meleeRoutes gate stands in.
        terms = [{k: v for k, v in t.items() if not (k == "symbolFilter" and v == "CC_AIR")} for t in terms]
    if spec.get("dieAverage"):
        faces = row.get("randomUpgrades") or []
        merged: dict = {}
        for face in faces:
            for raw in face["effects"]:
                t = term(raw)
                key = (t["upgradeType"], t["operation"], t.get("damageType"))
                held = merged.setdefault(key, {**t, "valuePerRank": 0.0})
                held["valuePerRank"] += t["valuePerRank"] / len(faces)
        terms = [t for t in merged.values() if t["upgradeType"] in SUPPORTED_WEAPON_UPGRADE_TYPES]
        ignored = [t for t in merged.values() if t["upgradeType"] not in SUPPORTED_WEAPON_UPGRADE_TYPES]
    if spec.get("perfectReload"):
        window = (row.get("perfectReload") or {}).get("range")
        if not window:
            raise SystemExit(f"{row['upgrade']}: perfect reload without a PerfectReloadRange")
        out["effects"] = [{"upgradeType": "WEAPON_RELOAD_TIME", "operation": "MULTIPLY", "valuePerRank": window[0]}]
        out["perfectReloadRange"] = window
    if spec.get("events"):
        cond = {"duration": 0 if spec.get("perfectReload") else spec.get("duration") or row.get("duration") or 0, "maxStacks": spec.get("maxStacks") or row.get("maxStacks") or 1,
                "chance": row.get("chance") if row.get("chance") is not None else 1, "effects": terms}
        if fields.get("StackMode") == "SM_DECAY":
            cond["stackMode"] = "SM_DECAY"
        if spec.get("stackMode"):
            cond["stackMode"] = spec["stackMode"]
        if fields.get("CanReproc") == 0:
            cond["noRefresh"] = True
        if spec.get("resetOn"):
            cond["resetOn"] = spec["resetOn"]
        if spec.get("scriptCondition"):
            cond.update(spec["scriptCondition"](row.get("script") or {}))
        if row.get("desc"):
            cond["conditionText"] = re.sub(r"<[^>]+>", "", row["desc"]).strip()
        out["conditionalEffects"] = [{**cond, "sourcePath": row["upgrade"], "eventKind": event,
                                      "conditions": row.get("conditions") or []}
                                     for event in spec["events"]]
    else:
        if not (spec.get("dieAverage") or spec.get("alwaysOn")) and (
                fields.get("ApplyUpgradesByDefault") == 0 or row.get("conditions")):
            raise SystemExit(f"{row['upgrade']}: conditional upgrade listed without an event")
        out["effects"] = terms
    if ignored:
        out["ignored"] = [t["upgradeType"] for t in ignored]
    if row.get("desc"):
        out["descZh"] = row["desc"].strip()
    return out


def reason(row: dict) -> str:
    name = basename(row["upgrade"])
    if name in ALREADY:
        return "modelled elsewhere: " + ALREADY[name]
    if name in REASONS:
        return REASONS[name]
    script = row.get("script") or {}
    frame = next((v for k, v in script.items() if str(k).endswith(("_frameType", "FrameType"))), None)
    if frame:
        return "signature bonus while its Warframe holds it (" + str(frame) + ")"
    if str(script.get("Function") or "").startswith("Upgrade") and "MeleeTree" in name:
        return "Exalted ability melee tree script"
    kinds = {e.get("UpgradeType") for e in row["effects"]} - {None, "NONE", "WEAPON_INNATE_UPGRADE"}
    if kinds and not kinds & SUPPORTED_WEAPON_UPGRADE_TYPES:
        return "no scored term (" + ", ".join(sorted(kinds)) + ")"
    if kinds <= {"WEAPON_RELOAD_SPEED"} and any(e.get("ValidPostures") for e in row["effects"]):
        return "sprinting only (ValidPostures RUN)"
    if script:
        return "script " + basename(str(script.get("Script") or "")) + " not modelled"
    raise SystemExit(f"{row['upgrade']}: no reason recorded for leaving it out")


# A status type (ValidProcTypes) -> its damage type, for one type's duration.
PROC_DAMAGE_TYPES = {"PT_BLEEDING": "DT_SLASH", "PT_IMMOLATION": "DT_FIRE", "PT_POISONED": "DT_POISON",
                     "PT_ELECTROCUTION": "DT_ELECTRICITY", "PT_CHILLED": "DT_FREEZE", "PT_ASPHYXIATION": "DT_GAS",
                     "PT_RAD_TOX": "DT_RADIATION", "PT_MAGNETIZED": "DT_MAGNETIC", "PT_INFECTED": "DT_VIRAL",
                     "PT_CAUSTIC_BURN": "DT_CORROSIVE", "PT_FRAILTY": "DT_PUNCTURE", "PT_KNOCKBACK": "DT_IMPACT"}

RELOAD_KINDS = {"_emptyReloadProjectileType": "empty", "_quickReloadProjectileType": "partial"}


def reload_projectiles(row: dict) -> dict:
    """InfBeamPistol.lua's reload grenade: one projectile a reload, the big one
    from empty. Contact and blast apply separately; the blast takes no
    headshot and, DisableExplosionRadiusUpgrades, no radius mods."""
    out = {"count": row.get("count") or 1, "unusedStats": row.get("unusedStats") or [],
           # When in the reload it lands is unmeasured; WFSim (catabolyst.yaml
           # unmodeled) reads the page's "thrown mid-reload" as halfway.
           "landsAt": 0.5}
    for key, kind in RELOAD_KINDS.items():
        p = (row.get("projectiles") or {}).get(key)
        if not p:
            continue
        hit, blast = p["AttackData"], p["ExplosiveAttack"]
        out[kind] = {
            "path": p["path"],
            "contact": {"damage": {hit["Type"]: hit["Amount"]}, "critChance": p["CriticalChance"],
                        "critMultiplier": p["CriticalMultiplier"], "procChance": hit["ProcChance"]},
            "explosion": {"damage": {blast["Type"]: blast["Amount"]}, "critChance": p["CriticalChance"],
                          "critMultiplier": p["CriticalMultiplier"], "procChance": blast["ProcChance"],
                          "radius": p["DamageRadius"], "falloff": p["ExplosionFallOff"],
                          "radiusMods": not p.get("DisableExplosionRadiusUpgrades")},
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scan", type=Path, required=True)
    ap.add_argument("--export", type=Path, default=ROOT / "data/export/2026.08.13.13.24/weapons.json")
    ap.add_argument("--reload", type=Path, help="scan's reload-projectiles.json (default: beside --scan)")
    ap.add_argument("--packages-sha256", default="00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06")
    ap.add_argument("--output", type=Path, default=ROOT / "data/mechanics/weapon-passives.json")
    a = ap.parse_args()
    rows = json.loads(a.scan.read_text(encoding="utf-8"))
    exported = json.loads(a.export.read_text(encoding="utf-8"))["data"]
    zh_names = {w["path"]: w.get("nameZh") for w in exported}
    names = {w["path"]: w.get("nameEn") for w in exported}
    data = json.loads(a.output.read_text(encoding="utf-8"))
    weapons = data["weapons"]
    for entry in weapons.values():
        entry.pop("innate", None)
        entry.pop("reloadProjectiles", None)
    reload_path = a.reload or a.scan.with_name("reload-projectiles.json")
    for path, row in json.loads(reload_path.read_text(encoding="utf-8")).items():
        weapons.setdefault(path, {"name": row["weapon"]})["reloadProjectiles"] = reload_projectiles(row)
    excluded, used = {}, set()
    for row in rows:
        name = basename(row["upgrade"])
        if name in SCRIPTED:
            used.add(name)
            entry = weapons.setdefault(row["weaponPath"], {"name": row["weapon"]})
            entry.update(SCRIPTED[name](row["script"]))
            entry["source" if "source" not in entry else "scriptSource"] = (
                f"Packages.bin {a.packages_sha256[:8]} {name}: Script {row['script'].get('Script')}")
            continue
        if name in MODELLED:
            used.add(name)
            target = MODELLED[name].get("target") or row["weaponPath"]
            entry = weapons.setdefault(target, {"name": names.get(target, row["weapon"])})
            entry.setdefault("innate", []).append(record(row, MODELLED[name], zh_names))
            continue
        why = reason(row)
        excluded.setdefault(row["upgrade"], {"reason": why, "weapons": []})["weapons"].append(row["weapon"])
    missing = (set(MODELLED) | set(SCRIPTED)) - used
    if missing:
        raise SystemExit(f"modelled upgrades not in the scan: {sorted(missing)}")
    data["description"] = (
        "Weapon passives the export does not carry (the weapon's DefaultUpgrades; tools/import_weapon_passives.py). "
        "innate: export-shaped records, `effects` always on, `conditionalEffects` granted by the named replay event "
        "(noRefresh: CanReproc 0, not renewed while running); `fireModes` limits a record to those modes. "
        "superCritOnStatus: a pellet that applies a status arms the next pellet with probability `chance`; that "
        "pellet's crit chance is SET to `critChance`, replacing every other crit bonus. superStatusOnCrit: the same "
        "with a critical hit arming a SET status chance. excluded: every other "
        "DefaultUpgrade of an exported weapon and why it is left out. reloadProjectiles: the grenade a reload "
        "throws (Catabolyst), `empty` / `partial` by the magazine's state, contact and blast as separate hits.")
    data["innateSource"] = {"packagesBin": a.packages_sha256, "scan": "scan_passives.py (DefaultUpgrades, parents merged)"}
    data["weapons"] = dict(sorted(weapons.items()))
    data["excluded"] = dict(sorted(excluded.items()))
    a.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    modelled = sum(len(e.get("innate") or ()) for e in weapons.values())
    print(f"{modelled} modelled records on {sum(1 for e in weapons.values() if e.get('innate'))} weapons, "
          f"{len(excluded)} upgrades excluded")


if __name__ == "__main__":
    main()
