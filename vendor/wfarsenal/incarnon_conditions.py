"""Human-readable trigger provenance, without pretending to execute arbitrary Lua."""

from pathlib import PurePosixPath

CONDITIONS = {
    "OnReloadFromEmptyClipCondition": "弹匣耗尽后装填",
    "OnReloadFromEmptyCondition_Description": "弹匣耗尽后装填",
    "BurstonOnBurstHit": "基础形态一轮三连发全部命中；装填重置",
    "IncarnonFullBurstHitDesc": "基础形态一轮三连发全部命中；装填重置",
    "OnWeakpointHitCondition": "直击弱点（范围伤害和 DoT 不触发）",
    "OnHeadshotCondition": "直击头部",
    "OnHeadshotKillCondition": "直击头部击杀",
    "OnKillCondition": "武器击杀",
    "OnCriticalHitCondition": "暴击命中",
}


def script_entries(value):
    if isinstance(value, list):
        for row in value:
            yield from script_entries(row)
    elif isinstance(value, dict):
        if value.get("Script"):
            yield value
        elif isinstance(value.get("apply"), dict):
            yield from script_entries(value["apply"])


def describe(condition, strings=None):
    strings = strings or {}
    parts = []
    tag = str(condition.get("conditionTag") or "")
    if strings.get(tag):
        parts.append(strings[tag])
    for raw in [tag, *(condition.get("conditions") or [])]:
        if not raw:
            continue
        name = str(raw).rsplit("/", 1)[-1]
        text = CONDITIONS.get(name)
        if not text and not parts:
            text = "触发标识 " + name
        if text and text not in parts:
            parts.append(text)
    scripts = list(script_entries(condition.get("runtimeScripts")))
    for script in scripts:
        name = PurePosixPath(script["Script"]).name
        descriptions = {
            "OnLastBurstCondition.lua": "基础形态弹匣最后一轮连发；多重被敏锐类锁定时无增益",
            "RequireArmor.lua": f'战甲护甲达到 {script.get("_minArmorRequired","未导出")}',
            "RequireEnergyPool.lua": f'战甲能量池达到 {script.get("_minEnergyPoolRequired","未导出")}',
            "RequireOvershields.lua": "拥有过载护盾时",
            "ChannelAbilityMod.lua": "维持持续消耗能量的技能时",
            "RequireEnemyCount.lua": f'{script.get("_enemyRange","?")} 米内每 {script.get("_enemyPerStack",1)} 名敌人一层，上限 {script.get("_maxStacks","?")}',
            "RequireSprintSpeed.lua": f'冲刺速度达到 {script.get("_minSpeedMultiplier","?")}',
            "RequireEnergySpent.lua": f'消耗 {script.get("_energySpentRequired","?")} 能量后',
            "StatIncreaseOnFinisherKill.lua": "处决击杀后",
            "StunOnNeutralComboHit.lua": "站立近战连招命中时",
            "EntratiWristGunIncarnonReplenishAmmoOnKill.lua": f'击杀后 {100*float(script.get("_replenishChance",0)):.1f}% 概率恢复 {script.get("_replenishAmount","?")} 发',
            "EntratiFistClawIncarnonSpeedPerCombo.lua": f'每连击倍率提供 {100*float(script.get("_speedPerComboTier",0)):.1f}% 速度',
        }
        text = descriptions.get(name)
        if name == "OnSelectiveSlotEquipped.lua":
            equipped = [
                str(v).rsplit("/", 1)[-1]
                for k, v in script.items()
                if k.startswith("_equipped") and v
            ]
            text = "装备组合：" + (
                "、".join(equipped)
                or "指定空槽 " + str(script.get("_unequippedSlots", []))
            )
        if text and text not in parts:
            parts.append(text)
        if not text:
            parts.append(
                "脚本入口 "
                + name
                + "::"
                + str(script.get("Function") or "?")
                + "（事件语义尚未验证）"
            )
    return "；".join(parts) or "未导出触发条件（不能视为常驻）"
