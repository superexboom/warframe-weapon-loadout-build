"""Human-readable trigger provenance, without pretending to execute arbitrary Lua."""

from pathlib import PurePosixPath
import re

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
    "OnStatusProcALLCondition": "施加任意异常状态（DoT 跳伤不触发）",
    "EvoPistolOnHeadshotCondition": "直击头部（范围伤害不触发）",
    "EvoPistolOnHeadshotConditionB": "直击头部（范围伤害不触发）",
    "EvoPistolOnNoCritOrProcCondition": "伤害实例既未暴击、也未施加异常状态",
    "MeleeAltModeCondition": "灵化近战形态激活期间",
    "OnMeleeAltFireCondition": "灵化近战形态激活期间",
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
        elif isinstance(value.get("unapply"), dict):
            yield from script_entries(value["unapply"])


def clean_text(text):
    text = re.sub(r'<[^>]*>', '', str(text or '')).replace('\\n', '\n')
    return ' '.join(text.split())


def describe(condition, strings=None):
    strings = strings or {}
    parts = []
    if condition.get('conditionText'):
        return clean_text(condition['conditionText'])
    native=condition.get('nativeEvent') or {}
    if native:
        from .manual_combat import EVENT_CONDITION_TEXT
        actor_labels={'on-shield-broken':'玩家自身护盾被击破时触发。','on-overguard-broken':'玩家自身超宏被击破时触发。',
                      'on-shield-hit':'玩家自身护盾受到伤害时触发。'}
        text=(actor_labels.get(native['kind']) if native.get('actorOnly') else None) or EVENT_CONDITION_TEXT.get(native['kind'])
        if text:
            if native.get('requiredCount',1)>1:
                text+=f"每 {native['requiredCount']} 次满足事件获得一层。"
            return text
    actor = condition.get('actorGate') or condition.get('equipmentGate') or {}
    labels = {'frameArmor':'战甲护甲','energyPool':'最大能量','sprintMultiplier':'冲刺速度',
              'overshields':'过载护盾','channeling':'持续消耗能量的技能','incarnonMeleeActive':'近战灵化已激活',
              'aimGliding':'瞄准滑翔','sliding':'滑行'}
    if actor.get('kind')=='minimum':
        return labels.get(actor['key'],actor['key'])+f"达到 {actor['minimum']:g}"
    if actor.get('kind')=='boolean':
        return labels.get(actor['key'],actor['key'])+'期间'
    if actor.get('kind')=='anyBoolean':
        return '或'.join(labels.get(key,key) for key in actor['keys'])+'期间'
    if actor.get('kind')=='enemies':
        return f"{actor['radius']:g} 米内每 {actor['per']:g} 名敌人一层，上限 {actor['maximum']:g}"
    if actor.get('kind')=='equipment':
        names = {'/Lotus/Weapons/Tenno/Bows/StalkerBow':'恐惧','/Lotus/Weapons/Tenno/ThrowingWeapons/StalkerKunai':'绝望',
                 '/Lotus/Weapons/Tenno/Melee/Scythe/StalkerScytheWeapon':'憎恨'}
        slots = {'LONG_GUN_SLOT':'主武器','PISTOL_SLOT':'副武器','MELEE_SLOT':'近战武器'}
        parts = ["装备 "+'、'.join(names.get(p,p.rsplit('/',1)[-1]) for p in actor['required'])] if actor['required'] else []
        parts.extend(slots.get(p,p)+'空槽' for p in actor['empty'])
        return '；'.join(parts)
    if condition.get('energyGate'):
        return f"每消耗 {condition['energyGate']:g} 能量增加一层"
    tag = str(condition.get("conditionTag") or "")
    unresolved = []
    for raw in [*(condition.get("conditions") or []), tag]:
        if not raw:
            continue
        name = str(raw).rsplit("/", 1)[-1]
        text = CONDITIONS.get(name)
        if not text:
            unresolved.append(name)
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
            "FirstAttackAfterEquip.lua": "切换到此武器后的首次攻击",
            "ModOnAimGlideOrSlide.lua": "瞄准滑翔或滑行期间",
            "UnlockAltMelee.lua": "灵化近战形态激活期间",
            "ZarimanTonfaWeapon.lua": "灵化近战形态激活期间",
            "ZarimanDagger.lua": "灵化近战形态激活期间",
            "EntratiWristGunIncarnonReplenishAmmoOnKill.lua": f'武器击杀后补充 {script.get("_replenishAmount","?")} 发备用弹药；触发概率由原生条件控制',
            "EntratiFistClawIncarnonSpeedPerCombo.lua": f'每连击倍率提供 {100*float(script.get("_speedPerComboTier",0)):.1f}% 速度',
        }
        text = descriptions.get(name)
        if name in {'UnlockAltMelee.lua', 'ZarimanTonfaWeapon.lua', 'ZarimanDagger.lua'} and script.get('Function') != 'OnActivateVoidMode':
            text = None
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
    if not parts:
        localized = clean_text(strings.get(tag))
        if localized and '|' not in localized:
            parts.append(localized)
        else:
            from .manual_combat import condition_kind, EVENT_CONDITION_TEXT
            text = EVENT_CONDITION_TEXT.get(condition_kind(condition))
            if text:
                parts.append(text.rstrip('。'))
            elif unresolved:
                parts.append('触发条件尚未解析：' + '、'.join(dict.fromkeys(unresolved)))
    return "；".join(parts) or "未导出触发条件（不能视为常驻）"
