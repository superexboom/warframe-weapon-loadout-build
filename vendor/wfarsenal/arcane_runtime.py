"""Arcanes whose effect lives in a runtime script, rebuilt from its parameters.

The client exports these cards with a Lua script instead of plain upgrades, so
the generic path skipped them ("runtime-script") and forcing them did nothing.
Each adapter checks the script name and its parameters first; a client update
that changes either drops the card back to "not modelled" rather than using
stale numbers. Values and stacking follow the wiki and WFSim
(data/arcanes, data/warframe_arcanes).

A spec describes one rank:

- ``build(stacks, uptime)`` returns the effects for that state;
- ``maxStacks`` is the stack ceiling at that rank (``None``: no stacks);
- ``default`` says how the build page derives the state when nothing is
  forced: ``("combat", key, above, per)`` counts a combat-state number,
  ``("flag", keys)`` reads combat-state switches, ``("headshot",)`` uses the
  weak-point share, ``("live",)`` is read per hit by the replay, ``None`` is a
  player action the replay does not simulate (inactive until forced);
- ``force`` whether "强制触发" (maximum, always on) means anything;
- ``stackLabel`` / ``note`` are shown next to the card.

``supplement`` also restores ordinary cards the export flagged unsupported
(Arcane Pistoleer, Exodia Triumph / Valor) and the weapon scope of frame
Arcanes whose export says "any weapon" while the card reads otherwise
(Arcane Arachne: primary and secondary, not melee).
"""
from __future__ import annotations

import math
from typing import Any, Mapping

from .damage import ModEffect

ROOT = "/Lotus/Upgrades/CosmeticEnhancers/"
SHIVER = ROOT + "Offensive/SecondaryExtraDamagePerFreezeStack"
CAREEN = ROOT + "Utility/FreezeEnemiesOnRoll"
RETALIATION = ROOT + "Offensive/MeleeDamageForActiveShields"
BULWARK = ROOT + "Offensive/DamageForBonusArmour"
OVERCHARGE = ROOT + "Offensive/MultishotForMaxEnergy"
CASCADIA_OVERCHARGE = ROOT + "Zariman/SecondaryOnOvershieldCritChance"
KINSHIP = ROOT + "Offensive/SecondaryCritChancePerBuff"
OUTBURST = ROOT + "Offensive/MultishotForCombo"
EXPOSURE = ROOT + "Offensive/CorrosiveMeleePerAbilityCast"
SHARPSHOT = ROOT + "Offensive/LongbowDamageOnHeadshot"
CREPUSCULAR = ROOT + "Utility/AbilityStrengthAndCritDamageWhenInvisible"
DEMULCENT = ROOT + "Offensive/WeaponDamageOnResidualContact"
SLIP_SHOT = ROOT + "Offensive/AmmoEfficiencyOnSliding"
PISTOLEER = ROOT + "Offensive/AmmoEfficiencyOnPistolHeadshot"
EXODIA_TRIUMPH = ROOT + "Offensive/StatusChannelingDamage"
EXODIA_VALOR = ROOT + "Offensive/CritChannelingDamage"
ARACHNE = ROOT + "Utility/GolemArcaneBonusDamageOnWallLatch"

LONG_GUN = "/Lotus/Weapons/Tenno/LotusLongGun"
PISTOL = "/Lotus/Weapons/Tenno/Pistol/LotusPistol"
MELEE_ONLY_TYPES = frozenset({"WEAPON_MELEE_DAMAGE"})

# Frame-slot cards whose exported effect has no validType although the card
# names its weapons (wiki: Arachne "does not apply to regular melee attacks").
SCOPE_OVERRIDES = {
    ARACHNE: ((LONG_GUN, False), (PISTOL, False)),
    PISTOLEER: ((PISTOL, False),),
}
# Ordinary upgrades the export marked unsupported (effect count 0).
SUPPORT_FIXES = {PISTOLEER: 1, EXODIA_TRIUMPH: 1, EXODIA_VALOR: 1}


def _close(value: Any, expected: float, tolerance: float = 1e-5) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and abs(float(value) - expected) <= tolerance)


def _ranked(values: Any, rank: int) -> float | None:
    if not isinstance(values, list) or not values:
        return None
    value = values[min(rank, len(values) - 1)]
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _script(record: Mapping[str, Any], name: str, *, conditional: int | None = None) -> Mapping[str, Any] | None:
    """The ``apply`` script entry named ``name`` (top level or one condition)."""
    owner: Any = record
    if conditional is not None:
        conditions = record.get("conditionalEffects") or []
        owner = conditions[conditional] if len(conditions) > conditional else {}
    scripts = owner.get("runtimeScripts") if isinstance(owner, Mapping) else None
    apply = scripts.get("apply") if isinstance(scripts, Mapping) else None
    if isinstance(apply, Mapping) and str(apply.get("Script") or "").rsplit("/", 1)[-1] == name:
        return apply
    return None


def _effect(upgrade: str, operation: str, value: float, path: str, **extra: Any) -> ModEffect:
    return ModEffect(upgrade, operation, value, source_path=path, **extra)


def _spec(build, *, max_stacks: int | None, default, force: bool, label: str, note: str) -> dict[str, Any]:
    return dict(build=build, maxStacks=max_stacks, default=default, force=force, stackLabel=label, note=note)


def _capped(per: float, cap: float) -> int:
    return int(math.ceil(cap / per - 1e-9))


def configuration(record: Mapping[str, Any], rank: int) -> dict[str, Any] | None:
    path = str(record.get("path") or "")
    adapter = _ADAPTERS.get(path)
    return adapter(record, int(rank), path) if adapter else None


def _shiver(record, rank, path):
    effects = record.get("effects") or []
    if (record.get("runtimeScripts") or len(effects) != 1
            or effects[0].get("upgradeType") != "WEAPON_DAMAGE_PER_ACTIVE_PROC_STACK_ON_VICTIM"
            or not _close(effects[0].get("valuePerRank"), 0.075)):
        return None
    per = 0.075 * (rank + 1)
    # Joins the base-damage bracket like Condition Overload, once per Cold
    # stack on the target (cap 10). Unforced, the replay reads the live count.
    return _spec(lambda stacks, uptime: [_effect("RUNTIME_COLD_STACK_DAMAGE", "ADD", per, path,
                                                 runtime_chance=float(stacks) * uptime)],
                 max_stacks=10, default=("live",), force=True, label="冰冻层数",
                 note=f"目标每层冰冻异常 +{per * 100:g}% 伤害（与膛线同区相加，最多 10 层）；默认按解算中目标的实时冰冻层数。")


def _careen(record, rank, path):
    apply = _script(record, "ApplyStatusToEnemiesOnRoll.lua", conditional=1)
    if not apply or apply.get("_bonusDamageProcCount") != 10 or not _close(apply.get("_damageToApplyBase"), 0.25) \
            or not _close(apply.get("_damageToApplyPerLevel"), 0.25):
        return None
    bonus = 0.25 + 0.25 * rank
    return _spec(lambda stacks, uptime: [_effect("RUNTIME_FROZEN_DAMAGE", "ADD", bonus, path,
                                                 runtime_chance=float(min(stacks, 1)) * uptime)],
                 max_stacks=1, default=("live",), force=True, label="",
                 note=f"对冻结（10 层冰冻）的敌人近战伤害 ×{1 + bonus:g}；默认只在解算中目标被冻结时生效，翻滚施加冰冻未模拟。")


def _retaliation(record, rank, path):
    apply = _script(record, "MeleeDamageForActiveShields.lua")
    if not apply or apply.get("_shieldsToGetBonus") != 200 or not _close(apply.get("_meleeDamageLimit"), 4.2) \
            or not _close(apply.get("_meleeDamagePerBonus"), 0.05) or not _close(apply.get("_meleeDamageStepPerFusionLevel"), 0.05):
        return None
    per, cap = 0.05 + 0.05 * rank, 4.2
    return _spec(lambda stacks, uptime: [_effect("WEAPON_MELEE_DAMAGE", "STACKING_MULTIPLY", min(stacks * per, cap) * uptime, path)],
                 max_stacks=_capped(per, cap), default=("combat", "frameShield", 0.0, 200.0), force=True, label="每 200 护盾",
                 note=f"当前每 200 护盾 +{per * 100:g}% 近战伤害，上限 +{cap * 100:g}%；默认按上方「战甲护盾」，过载护盾按半数计入未模拟。")


def _bulwark(record, rank, path):
    apply = _script(record, "GiveStatForStat.lua")
    if not apply or apply.get("_haveStatType") != "AVATAR_ARMOUR" or apply.get("_giveStatType") != "WEAPON_DAMAGE_AMOUNT" \
            or apply.get("_haveStatThresholdMin") != 1000 or apply.get("_maxStacks") != 500 \
            or not _close(apply.get("_giveStatIncreaseBase"), 0.005) or not _close(apply.get("_giveStatIncreasePerLevel"), 0.001):
        return None
    per = 0.005 + 0.001 * rank
    return _spec(lambda stacks, uptime: [_effect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", min(stacks, 500) * per * uptime, path)],
                 max_stacks=500, default=("combat", "frameArmor", 1000.0, 1.0), force=True, label="超过 1000 的护甲",
                 note=f"护甲超过 1000 的部分每点 +{per * 100:g}% 伤害，上限 +{per * 500 * 100:g}%；默认按上方「战甲护甲」。")


def _overcharge(record, rank, path):
    apply = _script(record, "GiveStatForStat.lua")
    if not apply or apply.get("_haveStatType") != "AVATAR_POWER_MAX" or apply.get("_giveStatType") != "WEAPON_FIRE_ITERATIONS" \
            or not _close(apply.get("_giveStatIncreaseBase"), 0.0035) or not _close(apply.get("_giveStatCapBase"), 1.0) \
            or not _close(apply.get("_giveStatCapPerLevel"), 0.5) or not _close(apply.get("_haveStatThresholdMin"), 0.9):
        return None
    per, cap = 0.0035, 1.0 + 0.5 * rank
    return _spec(lambda stacks, uptime: [_effect("WEAPON_FIRE_ITERATIONS", "STACKING_MULTIPLY", min(stacks * per, cap) * uptime, path)],
                 max_stacks=_capped(per, cap), default=("combat", "energyPool", 0.0, 1.0), force=True, label="最大能量",
                 note=f"能量不低于 90% 时，每点最大能量 +{per * 100:g}% 多重射击，上限 +{cap * 100:g}%；默认按上方「最大能量」并视为能量保持在 90% 以上。")


def _cascadia_overcharge(record, rank, path):
    apply = _script(record, "SecondaryOnOvershieldCritChance.lua")
    bonus = _ranked(apply.get("_bonuses"), rank) if apply else None
    if bonus is None or apply.get("_upgradeType") != "WEAPON_CRIT_CHANCE" or not _close(_ranked(apply.get("_bonuses"), 5), 3.0):
        return None
    return _spec(lambda stacks, uptime: [_effect("WEAPON_CRIT_CHANCE", "ADD", bonus * min(stacks, 1) * uptime, path)],
                 max_stacks=1, default=("flag", ("overshields",)), force=True, label="",
                 note=f"有过载护盾时 +{bonus * 100:g}% 暴击几率；默认按上方「过载护盾」开关。")


def _kinship(record, rank, path):
    apply = _script(record, "UpgradePerAllyBuff.lua")
    if not apply or apply.get("_upgradeType") != "WEAPON_CRIT_CHANCE" or apply.get("_operationType") != "STACKING_MULTIPLY" \
            or not _close(apply.get("_baseValue"), 0.0334) or not _close(apply.get("_rankValue"), 0.0334):
        return None
    per = 0.0334 * (rank + 1)
    return _spec(lambda stacks, uptime: [_effect("WEAPON_CRIT_CHANCE", "STACKING_MULTIPLY", stacks * per * uptime, path)],
                 max_stacks=10, default=None, force=False, label="友方增益数",
                 note=f"自身每个来自队友战甲的增益 +{per * 100:.2f}% 暴击几率；队友增益数无法推导，用「限定层数」填写。")


def _outburst(record, rank, path):
    apply = _script(record, "MultishotForCombo.lua")
    per = _ranked(apply.get("_valuesPerCombo"), rank) if apply else None
    if per is None or apply.get("_upgradeType") != "WEAPON_CRIT_DAMAGE" or apply.get("_secondaryUpgradeType") != "WEAPON_CRIT_CHANCE" \
            or apply.get("_operationType") != "STACKING_MULTIPLY" or not _close(_ranked(apply.get("_valuesPerCombo"), 5), 0.2):
        return None
    return _spec(lambda stacks, uptime: [_effect(kind, "STACKING_MULTIPLY", stacks * per * uptime, path)
                                         for kind in ("WEAPON_CRIT_CHANCE", "WEAPON_CRIT_DAMAGE")],
                 max_stacks=12, default=None, force=True, label="消耗的连击倍率",
                 note=f"切到次要武器时每消耗 1 倍近战连击倍率 +{per * 100:g}% 暴击几率与暴击伤害，持续 30 秒；切换动作未模拟，强制按 12 倍。")


def _exposure(record, rank, path):
    apply = _script(record, "CorrosiveMeleePerAbilityCast.lua")
    if not apply or apply.get("_damageUpgradeType") != "DT_CORROSIVE" or apply.get("_upgradeType") != "WEAPON_PERCENT_BASE_DAMAGE_ADDED" \
            or not _close(apply.get("_buffHardLimit"), 2.4) or not _close(apply.get("_buffStepPerCast"), 0.1) \
            or not _close(apply.get("_buffStepPerFusionLevel"), 0.1):
        return None
    per, cap = 0.1 + 0.1 * rank, 2.4
    return _spec(lambda stacks, uptime: [_effect("WEAPON_PERCENT_BASE_DAMAGE_ADDED", "ADD", min(stacks * per, cap) * uptime, path,
                                                 damage_type="DT_CORROSIVE")],
                 max_stacks=_capped(per, cap), default=None, force=True, label="施放技能次数",
                 note=f"每次施放战甲技能近战 +{per * 100:g}% 腐蚀伤害，持续 25 秒，上限 +{cap * 100:g}%；施放技能未模拟。")


def _sharpshot(record, rank, path):
    apply = _script(record, "BonusDamageForNextShot.lua")
    bonus = _ranked(apply.get("_damageBonuses"), rank) if apply else None
    if bonus is None or not _close(_ranked(apply.get("_damageBonuses"), 5), 3.0):
        return None
    # Wiki: [(1 + Serration) x (1 + Sharpshot)] + Galvanized Aptitude.
    return _spec(lambda stacks, uptime: [_effect("RUNTIME_NEXT_SHOT_DAMAGE", "ADD", bonus * min(stacks, 1) * uptime, path)],
                 max_stacks=1, default=("headshot",), force=True, label="",
                 note=f"弱点命中后下一发 +{bonus * 100:g}% 伤害（乘在膛线之外，不乘电导类加成）；默认按弱点命中率。")


def _crepuscular(record, rank, path):
    apply = _script(record, "GiveStatsWhileInvisible.lua")
    if not apply or apply.get("_giveStatTwoType") != "AVATAR_CRIT_DAMAGE" or apply.get("_giveStatTwoOperation") != "ADD" \
            or not _close(apply.get("_giveStatTwoIncreaseBase"), 0.5) or not _close(apply.get("_giveStatTwoIncreasePerLevel"), 0.5):
        return None
    value = 0.5 + 0.5 * rank
    return _spec(lambda stacks, uptime: [_effect("RUNTIME_FINAL_CRIT_DAMAGE", "ADD", value * min(stacks, 1) * uptime, path)],
                 max_stacks=1, default=None, force=True, label="",
                 note=f"隐形期间最终暴击倍率 +{value:g}；隐形未模拟，强制即视为全程隐形。")


def _demulcent(record, rank, path):
    effects = record.get("effects") or []
    script = (effects[0].get("localizationScript") or {}) if len(effects) == 1 else {}
    per = _ranked(script.get("_upgradePct"), rank)
    if (per is None or str(script.get("Script") or "").rsplit("/", 1)[-1] != "ResidualTrigger.lua"
            or script.get("_maxStacks") != 15 or not _close(_ranked(script.get("_upgradePct"), 5), 0.12)):
        return None
    return _spec(lambda stacks, uptime: [_effect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", min(stacks, 15) * per * uptime, path)],
                 max_stacks=15, default=None, force=True, label="层数",
                 note=f"站在残差赋能区域内每秒 +{per * 100:g}% 武器伤害，最多 15 层，离开后保留 20 秒；残差区域未模拟。")


def _slip_shot(record, rank, path):
    apply = _script(record, "AmmoEfficiencyOnSliding.lua")
    value = _ranked(apply.get("_ammoEfficiencyIncreaseLevels"), rank) if apply else None
    if value is None or not _close(_ranked(apply.get("_ammoEfficiencyIncreaseLevels"), 5), 0.65):
        return None
    return _spec(lambda stacks, uptime: [_effect("WEAPON_AMMO_CONSUME_RATE", "STACKING_MULTIPLY", -value * min(stacks, 1) * uptime, path)],
                 max_stacks=1, default=("flag", ("sliding", "aimGliding")), force=True, label="",
                 note=f"滑行或瞄准滑翔时双枪弹药效率 +{value * 100:g}%；默认按上方「滑行 / 瞄准滑翔」。")


_ADAPTERS = {
    SHIVER: _shiver, CAREEN: _careen, RETALIATION: _retaliation, BULWARK: _bulwark, OVERCHARGE: _overcharge,
    CASCADIA_OVERCHARGE: _cascadia_overcharge, KINSHIP: _kinship, OUTBURST: _outburst, EXPOSURE: _exposure,
    SHARPSHOT: _sharpshot, CREPUSCULAR: _crepuscular, DEMULCENT: _demulcent, SLIP_SHOT: _slip_shot,
}


def default_state(spec: Mapping[str, Any], combat_state: Mapping[str, Any], headshot_chance: float) -> tuple[int, float]:
    """(stacks, uptime) the build page uses when the card is not forced."""
    default = spec.get("default")
    cap = spec.get("maxStacks") or 1
    if not default or default[0] == "live":
        return 0, 1.0
    if default[0] == "headshot":
        return 1, min(max(float(headshot_chance), 0.0), 1.0)
    if default[0] == "flag":
        return int(any(combat_state.get(key) is True for key in default[1])), 1.0
    _kind, key, above, per = default
    value = combat_state.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 0, 1.0
    return min(cap, max(0, int(math.floor((float(value) - above) / per + 1e-9)))), 1.0


def supplement(record: Mapping[str, Any]) -> Mapping[str, Any]:
    """Mark adapted / repaired cards as weapon-relevant for the manual slots."""
    path = str(record.get("path") or "")
    count = SUPPORT_FIXES.get(path) or (1 if path in _ADAPTERS else 0)
    if not count:
        return record
    support = dict(record.get("support") or {})
    support.update(manualState=True, weaponEffects=max(int(support.get("weaponEffects") or 0), count),
                   runtimeAdapter=path in _ADAPTERS)
    return {**record, "support": support}


def weapon_scopes(record: Mapping[str, Any]) -> list[tuple[str, bool]]:
    """(validType or "", melee only) of every weapon effect a card carries."""
    path = str(record.get("path") or "")
    if path in SCOPE_OVERRIDES:
        return list(SCOPE_OVERRIDES[path])
    scopes = []
    blocks = [record.get("effects") or []] + [c.get("effects") or [] for c in record.get("conditionalEffects") or ()
                                              if isinstance(c, Mapping)]
    for block in blocks:
        for effect in block:
            kind = str(effect.get("upgradeType") or "")
            if not kind.startswith("WEAPON_") and not kind.startswith("RUNTIME_"):
                continue
            scope = (str(effect.get("validType") or "").rstrip("/"), kind in MELEE_ONLY_TYPES)
            if scope not in scopes:
                scopes.append(scope)
    if not scopes and path in _ADAPTERS:
        scopes.append(("", path in (CAREEN, RETALIATION, EXPOSURE)))
    return scopes


def scope_applies(scopes: list[tuple[str, bool]], weapon: Mapping[str, Any]) -> bool:
    from .damage import MELEE_SLOTS, archgun_arcane_type_applies
    ancestry = {str(p).rstrip("/") for p in (*tuple(weapon.get("ancestry") or ()), weapon.get("path")) if p}
    melee = weapon.get("slot") in MELEE_SLOTS
    for valid, melee_only in scopes:
        if melee_only and not melee:
            continue
        if not valid or valid in ancestry or archgun_arcane_type_applies(weapon, ROOT, valid):
            return True
    return False
