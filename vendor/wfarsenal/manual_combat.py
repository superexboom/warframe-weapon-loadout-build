from __future__ import annotations

import json
import math
import sys
from copy import copy, deepcopy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def reference():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return json.loads(
        (root / "data/mechanics/combat-reference.json").read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def infinite_condition_sources():
    """Native IsInfinite buffs (tools/import_infinite_conditions.py)."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    try:
        return frozenset(json.loads((root / "data/mechanics/infinite-conditions.json").read_text(encoding="utf-8"))["sources"])
    except (OSError, ValueError, KeyError):
        return frozenset()


def condition_kind(condition):
    if condition.get('nativeEvent'):
        return condition['nativeEvent']['kind']
    names = {
        str(x).rsplit("/", 1)[-1].lower() for x in condition.get("conditions") or []
    }
    if not names:
        names = {str(condition.get("conditionTag") or "").rsplit("/", 1)[-1].lower()}
    exact = {
        "onreloadfromemptyclipcondition": "on-reload-empty",
        "onreloadarchgunfromemptyclipcondition": "on-reload-empty-complete",
        "onreloadfromemptycondition_description": "on-reload-empty",
        "burstononbursthit": "on-burst-hit",
        "onweakpointhitcondition": "on-headshot",
        "onheadshotcondition": "on-headshot",
        "onheadshotriflecondition": "on-headshot",
        "onheadshotpistolcondition": "on-headshot",
        "onheadshotpistolnoabilityweaponscondition": "on-headshot",
        "evopistolonheadshotcondition": "on-headshot",
        "evopistolonheadshotconditionb": "on-headshot",
        "onpistolheadshotkillcondition": "on-headshot-kill",
        "onpistolheadshotkillnojetpistolcondition": "on-headshot-kill",
        "onheadshotkillanysourcecondition": "on-headshot-kill",
        "onheadshotkillcondition": "on-headshot-kill",
        "onkillheadshotriflecondition": "on-headshot-kill",
        "onkillheadshotpistolcondition": "on-headshot-kill",
        "onkillcondition": "on-kill",
        "onkillriflecondition": "on-kill",
        "onpistolkillcondition": "on-kill",
        "onshotgunkillcondition": "on-kill",
        "onprimarykillcondition": "on-primary-kill",
        "onmeleekillanysourcecondition": "on-melee-kill",
        "onmeleekillcondition": "on-melee-kill",
        "oncritcondition": "on-crit",
        "oncriticalhitcondition": "on-crit",
        "onhitcondition": "on-hit",
        "onreloadcondition": "on-reload",
        "onreloadshotguncondition": "on-reload-complete",
        "onreloadriflecondition": "on-reload-complete",
        "onreloadpistolcondition": "on-reload-complete",
        "onheatproccondition": "proc-DT_FIRE",
        "oncoldproccondition": "proc-DT_FREEZE",
        "ontoxinproccondition": "proc-DT_POISON",
        "onelectricityproccondition": "proc-DT_ELECTRICITY",
        "onproccondition": "on-proc",
        "onstatusprocallcondition": "on-proc",
        "evopistolonnocritorproccondition": "on-noncrit-no-proc",
        "onshotgunclosekillcondition": "on-close-kill",
        "evoonshieldbreakcondition": "on-self-shield-broken",
        "onoverguardbrokencondition": "on-self-overguard-broken",
    }
    return next((exact[x] for x in names if x in exact), None)


EVENT_CONDITION_TEXT = {
    'on-reload-empty': '弹匣打空后开始换弹时触发。',
    'on-reload-empty-complete': '弹匣打空后完成换弹时触发。',
    'on-burst-hit': '一轮连射全部命中时触发。',
    'on-headshot': '命中头部弱点时触发。',
    'on-headshot-kill': '头部弱点命中造成击杀时触发。',
    'on-kill': '击杀时触发。',
    'on-primary-kill': '主武器击杀时触发。',
    'on-melee-kill': '近战击杀时触发。',
    'on-crit': '暴击命中时触发。',
    'on-hit': '命中时触发。',
    'on-reload': '开始换弹时触发。',
    'on-reload-complete': '完成换弹时触发。',
    'proc-DT_FIRE': '施加火焰异常时触发。',
    'proc-DT_FREEZE': '施加冰冻异常时触发。',
    'proc-DT_POISON': '施加毒素异常时触发。',
    'proc-DT_ELECTRICITY': '施加电击异常时触发。',
    'on-proc': '施加异常状态时触发。',
    'on-noncrit-no-proc': '伤害实例既未暴击、也未施加异常状态时触发。',
    'on-close-kill': '击杀距离不超过 5 米的目标时触发。',
    'on-overguard-broken': '目标超宏被击破时触发。',
    'on-self-shield-broken': '玩家自身护盾被击破时触发。',
    'on-self-overguard-broken': '玩家自身超宏被击破时触发。',
    'on-self-shield-hit': '玩家自身护盾受到伤害时触发。',
    'on-fire': '扣动扳机射击时触发。',
    'on-punchthrough': '同次射击穿透并命中后续目标时触发。',
}


def modeled_event_kinds(record, rank):
    # Empty starting stacks are valid only for replay-supported conditions.
    from .damage import ModEffect
    from .runtime_adapters import verified_crux_condition

    crux = verified_crux_condition(record)
    conditions = [crux] if crux else record.get('conditionalEffects') or []
    kinds = []
    for condition in conditions:
        kind = condition_kind(condition)
        effects = condition.get('effects') or []
        if not kind or not effects or condition.get('runtimeScripts'):
            return ()
        if not all(ModEffect.from_export(effect, rank).supported for effect in effects):
            return ()
        kinds.append(kind)
    return tuple(kinds)


class _NoVariant(Exception):
    pass


def live_variant(template, live_types, count_ceiling):
    """``template`` (resolved at ``count_ceiling`` live types) at ``live_types``.

    Mirrors the resolver's ``replace(e, value=e.value*live_types/count_ceiling)``
    on every CO effect; None when some CO-dependent object has no CoSpec.
    """
    from .damage import co_variant, with_value
    memo = {}

    def vary(obj):
        if obj is None:
            return None
        key = id(obj)
        if key in memo:
            return memo[key]
        out = obj
        if obj.co_bucket:
            spec = getattr(obj, '_co_spec', None)
            if spec is None:
                raise _NoVariant
            scaled = [with_value(e, e.value*live_types/count_ceiling) for e in obj.co_bucket]
            out = co_variant(obj, spec, scaled)
        lingering = getattr(obj, '_lingering', None)
        if lingering:
            part = vary(lingering[0])
            if part is not lingering[0]:
                out = out if out is not obj else copy(obj)
                out._lingering = (part, *lingering[1:])
        extra = getattr(obj, '_additional_radials', None)
        if extra:
            parts = tuple(vary(part) for part in extra)
            if any(a is not b for a, b in zip(parts, extra)):
                out = out if out is not obj else copy(obj)
                out._additional_radials = parts
        stackable = getattr(obj, '_stackable', None)
        if stackable:
            config, parts = stackable
            varied = {name: vary(part) for name, part in parts.items()}
            if any(varied[name] is not part for name, part in parts.items()):
                out = out if out is not obj else copy(obj)
                out._stackable = (config, varied)
        memo[key] = out
        return out

    try:
        st, radial = template
        return vary(st), vary(radial)
    except _NoVariant:
        return None


def prepare(
    engine,
    mod_records,
    arcane_records,
    *,
    cycle_enabled=False,
    assumed=False,
    incarnon_choices=None,
    affinity_target=None,
    level=1,
    eximus=False,
    resolve_cache=None,
):
    """``resolve_cache`` shares resolved stats across prepares of one loadout.

    ``resolve`` depends only on the engine inputs, records and the cycle /
    trigger / Incarnon options; the target, level and Eximus flag feed only
    affinity. Callers pass one cache per bound loadout (search_combat.bind).
    """
    from .damage import ModEffect, ModEffectList, ModdedStats, apply_mods, apply_mods_spec, co_variant, scenario_with, with_value
    from .runtime_adapters import latron_puncture_strip,incarnon_condition_rows
    from .runtime_adapters import ammo_restore_configuration

    weapon = engine["weapon"]
    scenario = engine["scenario"]
    mode_index = engine["fire_mode"]
    from .runtime_adapters import mq_augment_multiplier
    mq_augment = next((value for row,rank,_ in mod_records
                       if (value:=mq_augment_multiplier(row,rank)) is not None),None)
    original = list(engine["effects"])
    from .enervate import configuration, PATH as ENERVATE_PATH, IGNORED_ALT
    enervate = None
    status_arcanes = {}
    from .status_arcanes import configuration as status_configuration
    sources = []
    dynamic = []
    form_dynamic = []
    actor_effects = []
    excluded = set()
    notes = []
    branches = []
    from .runtime_adapters import verified_crux_condition, verified_incarnon_condition, verified_torid_field_duration
    for tier in (weapon.get("incarnon") or {}).get("tiers") or []:
        number = tier.get("tier")
        wanted = (incarnon_choices or {}).get("tier" + str(number)) or (
            incarnon_choices or {}
        ).get(str(number))
        branches.extend(b for b in tier.get("branches") or [] if b.get("id") == wanted or (number==1 and any(
            verified_incarnon_condition(b,c) for c in b.get('conditionalEffects') or ())))
    field_duration = next((spec for b in branches if (spec := verified_torid_field_duration(b))), None)
    from .runtime_adapters import miter_charge_aoe
    miter_aoe=next((spec for b in branches if (spec:=miter_charge_aoe(b))),None)
    from .runtime_adapters import double_tap_configuration
    double_tap=next((spec for record,rank,_ in mod_records if (spec:=double_tap_configuration(record,rank))),None)
    from .sniper import combo_spec
    # Imported once per call, not per record: the loop below runs for every
    # MOD, Arcane and Incarnon branch of every replayed loadout.
    from .runtime_adapters import (compression_configuration, onos_crits_for_hits, reserve_ammo_refund,
                                   passive_incarnon_condition, self_break_forced, self_break_condition,
                                   incarnon_actor_stacks)
    from .arcane_runtime import configuration as runtime_arcane
    sniper_combo=combo_spec(weapon)

    # Final Fusillade / equivalent Incarnon terms are read from the base form's
    # last magazine pull. Keep this as an event gate; never fold it into the
    # panel's permanent multishot value. Incarnon charge-pool forms do not use
    # the gate even when the same evolution id is shared.
    last_round_multishot = 0.0
    for branch in branches:
        for term in branch.get('effects') or ():
            if (term.get('upgradeType') == 'WEAPON_LAST_MULTISHOT'
                    and isinstance(term.get('valuePerRank'), (int, float))
                    and not isinstance(term.get('valuePerRank'), bool)):
                last_round_multishot += float(term['valuePerRank'])

    replaced_terms = set()
    for record, rank, override in [
        *mod_records,
        *arcane_records,
        *[(b, 0, None) for b in branches],
    ]:
        if double_tap_configuration(record,rank):
            continue
        if miter_charge_aoe(record):
            continue
        if compression_configuration(record, rank):
            # The ADS adapter owns this exact runtime record and its children.
            continue
        if runtime_arcane(record, rank):
            # arcane_runtime rebuilt the script; its static terms (or the live
            # Cold / frozen fields) already carry the state.
            continue
        status_spec = status_configuration(record, rank)
        if status_spec:
            uptime = (override or {}).get('uptime', 1.0)
            if override is not None and override.get('stacks') == 0:
                uptime = 0.0
            status_arcanes[status_spec['kind']] = {**status_spec, 'uptime': uptime}
            continue
        spec = configuration(record, rank)
        if spec:
            enervate = {**spec, 'uptime': (override or {}).get('uptime', 1.0),
                        'ignoreSelected': weapon.get('path') == IGNORED_ALT and mode_index > 0}
            if (override or {}).get('stacks') is not None:
                enervate['fixedStacks'] = override['stacks']
            if assumed and 'fixedStacks' not in enervate:
                notes.append('enervate-has-no-maximum-using-events')
            continue
        crux = verified_crux_condition(record)
        if crux:
            record = {**record, "conditionalEffects": [crux]}
        condition_rows = []
        if onos_crits_for_hits(record):
            continue
        if reserve_ammo_refund(record):
            notes.append('reserve-ammo-infinite-refund-does-not-change-magazine-or-damage')
            continue
        if latron_puncture_strip(record):
            continue
        if ammo_restore_configuration(record):
            continue
        for raw_condition in incarnon_condition_rows(record):
            raw_names = {str(x).rsplit("/", 1)[-1].casefold() for x in raw_condition.get("conditions") or ()}
            if 'evoonshieldbreakcondition' in raw_names and 'onoverguardbrokencondition' in raw_names:
                # Either break grants the one buff; forced, it is held once.
                gates = ('EvoOnShieldBreakCondition',) if self_break_forced(scenario) else ('EvoOnShieldBreakCondition', 'OnOverguardBrokenCondition')
                for gate in gates:
                    native_kind='on-shield-broken' if gate=='EvoOnShieldBreakCondition' else 'on-overguard-broken'
                    condition_rows.append({**raw_condition,'conditions':[gate],
                                           'nativeEvent':{'kind':native_kind,'actorOnly':True,'requiredCount':1,'resetOn':[]}})
            else:
                condition_rows.append(raw_condition)
        for ci, condition in enumerate(condition_rows):
            verified = verified_incarnon_condition(record, condition)
            if verified:
                condition = verified
            if condition.get('isInfinite') or condition.get('sourcePath') in infinite_condition_sources():
                # Held until the condition resets; UpgradeDuration is no lifetime.
                condition = {**condition, 'duration': 0, 'hold': True}
            if condition.get('nativeEvent'):
                native=condition['nativeEvent']
                merged=[*(condition.get('resetOn') or []),*(native.get('resetOn') or [])]
                condition={**condition,'resetOn':[x for x in ('on-reload','on-transform','on-holster','on-body-hit') if x in merged]}
            if condition.get('equipmentGate'):
                if not incarnon_actor_stacks({'actorGate':condition['equipmentGate']},scenario,weapon):
                    continue
            # The two audited Deadly Efficiency cards scale their 1.5-second
            # base duration by rank. The raw event is specifically reload from
            # an empty Arch-gun; keep unrelated reload cards unchanged.
            if (record.get("path") in {
                "/Lotus/Upgrades/Mods/Archwing/Rifle/ArchwingDamageAfterReloadMod",
                "/Lotus/Upgrades/Mods/Archwing/Rifle/PrimedArchwingDamageOnReloadMod",
            } and condition_kind(condition) == "on-reload-empty-complete"
                    and condition.get("duration") == 1.5):
                condition = {**condition, "duration": 1.5 * (rank + 1)}
            if record.get('path') in ('/Lotus/Upgrades/Mods/Rifle/Event/CritChanceWhileAimingRifleSPMod', '/Lotus/Upgrades/Mods/Pistol/Event/CritChanceWhileAimingPistolSPMod') and condition.get('maxStacks') == 5:
                condition = {**condition, 'stackMode': 'per-stack'}
            if (record.get('path') in (
                '/Lotus/Upgrades/Mods/Shotgun/Event/FireRateWhileAimingShotgunMod',
                '/Lotus/Upgrades/Mods/Rifle/Event/FireRateWhileAimingRifleMod',
                '/Lotus/Upgrades/Mods/Pistol/Event/FireRateWhileAimingPistolMod')
                and condition.get('duration') == 1.5):
                condition = {**condition, 'duration':1.5*(rank+1)}
            if condition.get("runtimeScripts"):
                source = str(condition.get("sourcePath") or record["path"])
                if not ("Burston" in source and "Tier1ASubMod" in source):
                    notes.append(source + ":runtime-condition-unmodeled")
                continue
            if not condition.get('effects'):
                continue
            # Empty child blocks may repeat permanent effects or the terminal
            # magazine gate handled by resolve; neither needs an event source.
            if (not condition.get('conditions') and not condition.get('conditionTag')
                    and not any(condition.get(k) for k in ('actorGate','formGate','eventKind','nativeEvent'))):
                continue
            source = condition.get("sourcePath") or record["path"]
            effects = [
                ModEffect.from_export(
                    e,
                    rank,
                    source_path=source,
                    condition_tag=condition.get("conditionTag"),
                )
                for e in condition.get("effects") or []
            ]
            if not condition.get('effects') or passive_incarnon_condition(condition):
                # Passive blocks stay in the static effects (optimizer._branch_effects).
                continue
            if condition.get('actorGate'):
                effects = [e for e in effects if e.supported]
            if not effects:
                continue
            kinds = [condition.get('eventKind') or condition_kind(condition)]
            kinds = [k for k in kinds if k]
            if (not kinds and not condition.get('actorGate') and not condition.get('formGate')
                    and override is not None and (override.get('stacks') is not None or override.get('uptime') is not None)):
                # A trigger the replay cannot simulate (taking damage, wall
                # latch, ability heat procs...) but forced or fixed by the
                # user: the static card already holds that state, keep it.
                notes.append(str(source) + ":event-condition-fixed-by-user")
                continue
            replaced_terms.update(
                (source, e.upgrade_type, e.operation, e.damage_type) for e in effects
            )
            if condition.get('actorGate'):
                stacks = incarnon_actor_stacks(condition,scenario,weapon)
                if stacks>0:
                    actor_effects.extend(with_value(e, e.value*stacks) for e in effects)
                continue
            if condition.get('formGate'):
                form_dynamic.append(effects)
                continue
            if not kinds:
                notes.append(str(source) + ":event-condition-unmodeled")
                continue
            if (
                any("PM_AIM" in e.valid_modifiers for e in effects)
                and not scenario.aiming
            ):
                continue
            excluded.add(source)
            cap = float(condition.get("maxStacks") or 1.0)
            forced = (override or {}).get("stacks")
            uptime = (override or {}).get('uptime')
            fixed = forced is not None or uptime is not None or (self_break_condition(condition) and self_break_forced(scenario)) or (assumed and not condition.get('energyGate') and not condition.get('toggleOn')
                      and not any(k.startswith('on-self-') or k in {'on-equip-from-primary','on-warframe-ability','on-three-enemy-punchthrough','on-onos-damage-condition'} for k in kinds))
            initial = min(max(float(forced), 0.0), cap) if forced is not None else (cap if fixed else 0.0)
            if condition.get('initialStateKey') and not fixed:
                initial=min(cap,scenario.combat_state.get(condition['initialStateKey'],0))
            if condition.get('energyGate') and not fixed:
                initial = min(cap,math.floor(scenario.combat_state.get('energySpent',0)/condition['energyGate']))
            if uptime is not None:
                initial *= min(max(float(uptime), 0.0), 1.0)
            for kind_index, kind in enumerate(kinds):
                key = source + ":" + str(ci) + ":" + str(kind_index)
                sources.append(
                    dict(
                        id=key,
                        hold=bool(condition.get('hold')),
                        resetOn=list(condition.get('resetOn') or []),
                        toggleOn=condition.get('toggleOn'),
                        victimProcType=(condition.get('nativeEvent') or {}).get('victimProcType'),
                        requiredCount=condition.get('requiredCount',(condition.get('nativeEvent') or {}).get('requiredCount',1)),
                        requiredTime=condition.get('requiredTime',(condition.get('nativeEvent') or {}).get('requiredTime')),
                        actorOnly=bool((condition.get('nativeEvent') or {}).get('actorOnly')),
                        conditionText=condition.get('conditionText') or EVENT_CONDITION_TEXT.get(kind, kind),
                        simulationMode='fixed' if fixed else 'events',
                        label=record.get("nameZh")
                        or record.get("nameEn")
                        or ("灵化 " + str(record.get("id")) if record.get("id") else key),
                        kind=kind,
                        maxStacks=cap,
                        duration=(
                            0.0
                            if fixed
                            else float(condition.get("duration") or 0.0)
                        ),
                        perEvent=(
                            0.0
                            if fixed
                            else float(
                                condition.get(
                                    "chance",
                                    (record.get("trigger") or {}).get("chance", 1.0),
                                )
                                or 0.0
                            )
                        ),
                        initialStacks=initial,
                        initialDuration=float(condition.get('duration') or 0.) if condition.get('energyGate') and not fixed else 0.,
                        energyThreshold=condition.get('energyGate'),
                        minimumConsecutive=condition.get('minimumConsecutive'),
                        decay=(
                            "lose_one_and_reset"
                            if condition.get("stackMode") == "SM_DECAY"
                            else (
                                "per-stack"
                                if condition.get("stackMode") == "per-stack"
                                and not fixed
                                else "reset"
                            )
                        ),
                    )
                )
                dynamic.append((key, effects))
    # Melee hit schedule (melee_sequence): combo-tier conditions (Blood Rush,
    # Weeping Wounds, ...) follow the replay's live combo counter instead of
    # the static scenario tier. Each cap gets its own stack key.
    from .melee_sequence import build_schedule
    melee = None
    combo_tier_keys = {}
    if weapon.get("slot") in ("melee", "arch_melee") and mode_index == 0 and not weapon.get("isIncarnonForm"):
        state = scenario.combat_state
        melee = build_schedule(weapon, state.get("meleeRoute"), stance=state.get("meleeStance"),
                               combo=state.get("meleeCombo"), target_distance=state.get("meleeTargetDistance"))
    if melee:
        notes.extend(melee["notes"])
        for record, rank, _ in [*mod_records, *arcane_records]:
            for condition in record.get("conditionalEffects") or ():
                if not any(str(c).endswith("/OnComboTierCondition") for c in condition.get("conditions") or ()):
                    continue
                cap = int(condition.get("maxStacks") or 12)
                source = condition.get("sourcePath") or record.get("path")
                terms = [ModEffect.from_export(e, rank, stacks=1, source_path=source,
                                               condition_tag=condition.get("conditionTag"))
                         for e in condition.get("effects") or ()]
                if not terms:
                    continue
                key = f"__comboTier:{cap}"
                combo_tier_keys[key] = cap
                dynamic.append((key, terms))
                notes[:] = [n for n in notes if n != str(source) + ":event-condition-unmodeled"]
                replaced_terms.update((source, e.upgrade_type, e.operation, e.damage_type) for e in terms)
    # Only conditional terms are replaced. Permanent rank unlocks remain active.
    static = [
        e
        for e in original
        if (e.source_path, e.upgrade_type, e.operation, e.damage_type)
        not in replaced_terms and not (enervate and e.source_path == ENERVATE_PATH)
    ]
    ref = reference()
    native_trigger = ref.get('nativeTriggers', {}).get(weapon.get('path'))
    if native_trigger:
        sources.append({**native_trigger, 'initialStacks': 1.0 if assumed else 0.0, 'duration': 0.0 if assumed else native_trigger['duration'], 'perEvent': 0.0 if assumed else native_trigger.get('perEvent', 1.0), 'decay': 'reset'})
        dynamic.append((native_trigger['id'], [ModEffect(e['upgradeType'], e['operation'], e['value'], damage_type=e.get('damageType'), source_path=native_trigger['source']) for e in native_trigger['effects']]))
    profile = ref["incarnon"].get(weapon.get("path"))
    modes = weapon["fireModes"]
    from .event_profiles import base_profile, native_burst, reloads_after_every_shot
    base_attack = base_profile({**weapon, 'isIncarnonForm': False, '__selectedFireMode__': 0}, 0)
    if modes[0].get('trigger')=='/Lotus/Language/Menu/Loadout_TriggerSemiAutoFireOnUp':
        # Press/release pairs keep the native per-shot timer. No assumed
        # release speed or extra shots are granted by treating them as a pair.
        base_attack={**base_attack,'burst':{'count':2,'delay_seconds':1./float(modes[0]['fireRate'])}}
    selected_attack = base_profile(weapon, mode_index)
    onos_sequence = selected_attack.get('onosCharge')
    from .runtime_adapters import onos_crits_for_hits
    onos_crit = next((q for b in branches if (q:=onos_crits_for_hits(b))),None)
    if selected_attack:
        notes.extend(selected_attack.get('unmodeled') or [])
        minimum=(selected_attack.get('radial') or {}).get('armingDistance')
        if minimum is not None and scenario.distance is None:
            notes.append('radial-arming-distance-assumed-armed')
    cycle = (
        profile
        if cycle_enabled and weapon.get("isIncarnonForm") and profile and len(modes) > 1
        else None
    )
    if cycle_enabled and weapon.get("isIncarnonForm") and not cycle:
        notes.append("incarnon-cycle-data-unavailable")
    from .event_profiles import kill_charge_cycle
    if not cycle and (kill_cycle := kill_charge_cycle(weapon, mode_index)):
        # A kill-charged alternate cannot fire on its own: replay the primary
        # until its kills fill the gauge, then the alternate (Trumna grenade).
        cycle = kill_cycle
    if (
        profile
        and profile.get("radial")
        and (cycle_enabled or weapon.get('isIncarnonForm'))
        and profile.get("referenceId")
        not in ("burston_incarnon", "burston_prime_incarnon")
        and not any(p.get('radial') for p in (ref.get('auditedAttacks',{}).get(weapon.get('path'),{}).get('modes',{}).values()))
    ):
        notes.append(profile["referenceId"] + ":radial-payload-unmodeled")
    if any(
        "Require" in str(c.get("runtimeScripts")) and not verified_incarnon_condition(b,c)
        for b in branches
        for c in b.get("conditionalEffects") or []
    ):
        notes.append("frame-state-conditional-evolution-unmodeled")
    mapped = {
        "heat": "DT_FIRE",
        "toxin": "DT_POISON",
        "electricity": "DT_ELECTRICITY",
        "cold": "DT_FREEZE",
        "impact": "DT_IMPACT",
        "puncture": "DT_PUNCTURE",
        "slash": "DT_SLASH",
        "blast": "DT_EXPLOSION",
        "gas": "DT_GAS",
        "radiation": "DT_RADIATION",
        "viral": "DT_VIRAL",
        "corrosive": "DT_CORROSIVE",
        "magnetic": "DT_MAGNETIC",
    }

    form_weapons = {}

    def resolve(form, stacks, live_types=0, last_round=False):
        fx = ModEffectList([*static,*actor_effects])
        for key, terms in dynamic:
            n = stacks.get(key, 0.0)
            if n > 0:
                fx.extend(with_value(e, (1.0 + (e.value - 1.0) * n) if e.operation == 'MULTIPLY' else e.value * n) for e in terms)
        # Public Scenario requires an integer count. Scale the linear CO
        # coefficient to represent expected presence without rounding it up.
        count_ceiling = int(math.ceil(live_types))
        if count_ceiling and live_types != count_ceiling:
            fx = ModEffectList(with_value(e, e.value*live_types/count_ceiling)
                               if e.upgrade_type == 'WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE'
                               else e for e in fx)
        idx = 0 if form == "base" else mode_index
        onos_power = bool(stacks.get('__onosPower'))
        if onos_sequence and form!='base':
            idx = 2 if onos_power else 1
            if onos_power and onos_crit:
                n = min(onos_crit['maximum'],stacks.get('__onosHits',0.))
                fx.extend(ModEffect(kind,'STACKING_MULTIPLY',onos_crit['perHit']*n)
                          for kind in ('WEAPON_CRIT_CHANCE','WEAPON_CRIT_DAMAGE'))
        # One record per form and mode (only read and copied below).
        wp = form_weapons.get((form != "base", idx))
        if wp is None:
            wp = {
                **weapon,
                "isIncarnonForm": form != "base" and weapon.get("isIncarnonForm", False),
            }
            wp = {**wp, '__selectedFireMode__': idx}
            form_weapons[(form != "base", idx)] = wp
        if wp.get('isIncarnonForm'):
            for terms in form_dynamic:
                fx.extend(terms)
        if last_round and last_round_multishot and form != 'incarnon' and not wp.get('isIncarnonForm'):
            fx.append(ModEffect('WEAPON_FIRE_ITERATIONS', 'ADD', last_round_multishot,
                                source_path='incarnon:last-round-multishot'))
        st, spec = apply_mods_spec(
            wp,
            fx,
            fire_mode=idx,
            scenario=scenario_with(
                scenario, incarnon_cycle=False, victim_status_count=count_ceiling,
                heavy_attack=bool(stacks.get('__heavy')) or scenario.heavy_attack,
            ),
        )
        st._co_spec = spec
        if onos_sequence and form!='base':
            st._charge_pool_cost = onos_sequence['powerCost'] if onos_power else 1.
            st.continuous = not onos_power
            if not onos_power:
                factor = 1.+(onos_sequence['rampMaximum']-1.)*min(1.,stacks.get('__onosBeamSeconds',0.)/onos_sequence['rampSeconds'])
                st.damage_types = {k:v*factor for k,v in st.damage_types.items()}
                if st.dot_base_damage is not None:
                    st.dot_base_damage *= factor
        radial = None
        # Explicit radial payload exists independently of direct damage.
        r = profile.get("radial") if profile and wp.get("isIncarnonForm") else None
        if (
            r
            and r.get("damage")
            and profile.get("referenceId")
            in ("burston_incarnon", "burston_prime_incarnon")
        ):
            rm = deepcopy(modes[idx])
            rm["damage"] = {
                **rm["damage"],
                "types": {mapped[k]: v for k, v in r["damage"].items()},
                "forcedProcs": [],
            }
            radial, radial_spec = apply_mods_spec(
                {**wp, "fireModes": [rm]},
                fx,
                scenario=replace(scenario, incarnon_cycle=False, victim_status_count=0),
            )
            radial = replace(
                radial,
                radial_only=True,
                multishot=1.0,
                weakpoint_damage_bonus=0.0,
                weakpoint_crit_chance_bonus=0.0,
                weakpoint_crit_chance_relative=0.0,
                headshot_bonus_multiplier=1.0,
            )
            radial._co_spec = radial_spec
        extra = base_profile(wp, idx)
        from .event_profiles import perfect_release
        extra, _ = perfect_release(extra, modes[idx], scenario.combat_state)
        stackable = extra.get('stackable')
        if stackable:
            if stackable.get('chargedStacks'):
                rounds = min(float(stackable['maxStack']),max(1.,st.magazine))
                stackable = {**stackable,'initialStack':rounds}
                st.ammo_cost *= rounds
            parts = {}
            for name in ('embed','explosion','merge','singularity','child'):
                component = stackable.get(name)
                if not component:
                    continue
                rm = deepcopy(modes[idx])
                rm.update(falloffRange=[0,0],falloffMinDamage=1,continuous=False,multishot=1.)
                rm['damage'] = {**rm['damage'],'types':component['damage'],
                                'critChance':component['critChance'],'critMultiplier':component['critMultiplier'],
                                'procChance':component['statusChance'],'forcedProcs':component.get('forcedProcs') or []}
                part_fx = fx if component.get('takesConditionOverload') else [e for e in fx if e.upgrade_type!='WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE']
                part, part_spec = apply_mods_spec({**wp,'fireModes':[rm]},part_fx,scenario=replace(scenario,incarnon_cycle=False,victim_status_count=count_ceiling))
                part = replace(part,radial_only=True,multishot=1.,weakpoint_damage_bonus=0.,
                               weakpoint_crit_chance_bonus=0.,weakpoint_crit_chance_relative=0.,headshot_bonus_multiplier=1.)
                if name=='singularity':
                    part = replace(part,crit_chance=0.,crit_multiplier=1.,noncrit_damage_multiplier=1.)
                part._co_spec = part_spec
                parts[name] = part
            if stackable.get('kind')=='mq' and mq_augment is not None:
                amount = scenario.combat_state.get('orbAbsorbedDamage')
                dtype = scenario.combat_state.get('orbAbsorbedDamageType')
                vector = dict(scenario.combat_state.get('orbAbsorbedDamageTypes') or ())
                if not vector and amount is not None and dtype:
                    vector = {dtype:amount}
                if vector:
                    multiplier = mq_augment
                    part = ModdedStats(damage_types={key:value*multiplier for key,value in vector.items()},crit_chance=0.,crit_multiplier=1.,
                                       status_chance=0.,multishot=1.,fire_rate=0.,magazine=0.,reload_time=0.,radial_only=True)
                    part._fixed_radial = True
                    parts['orbRadial'] = part
            st._stackable = (stackable,parts)
        components = () if extra.get('pureRadial') else (extra.get('radials') or [extra.get('radial') or extra.get('lingering')])
        # Cluster bomblets (tools/import_cluster_submunitions.py): each child
        # lands its own hit and explosion, ``count`` per shell.
        components = [*components, *(dict(cluster[key], count=cluster['count'])
                                     for cluster in extra.get('clusters') or () for key in ('radial', 'direct'))]
        radial_parts = []
        for component in components:
            if component and component.get('requiresOnosRadialHit') and not scenario.combat_state.get('onosRadialHit'):
                component = None
            if (component and component.get('armingDistance') is not None
                    and scenario.distance is not None
                    and scenario.distance < component['armingDistance']):
                component = None
            if component and component.get('damage'):
                rm = deepcopy(modes[idx])
                rm['__radialPart__'] = True
                # This part detonates at the aimed target; shot flight distance is
                # not distance from the explosion centre.
                rm['falloffRange'] = [0, 0]
                rm['falloffMinDamage'] = 1
                rm['damage'] = {
                    **rm['damage'], 'types': {mapped.get(k,k): v for k, v in component['damage'].items()},
                    'forcedProcs': list(component.get('forcedProcs') or [])+[proc for element, proc in [('electricity', 'PT_ELECTROCUTION'), ('cold', 'PT_CHILLED')] if element in component.get('forced_procs', [])],
                    'critChance': component.get('crit_chance', rm['damage'].get('critChance')),
                    'critMultiplier': component.get('crit_multiplier', rm['damage'].get('critMultiplier')),
                    'procChance': (component['status_chance'] * float(rm.get('multishot') or 1) if component.get('status_chance') is not None else rm['damage'].get('procChance')),
                }
                part_fx = fx if component.get('takes_condition_overload') else ModEffectList(e for e in fx if e.upgrade_type != 'WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE')
                if not (extra.get('radial') or extra.get('radials')):
                    # A lingering field has its own native base damage: flat
                    # "+N base damage" belongs to the shot (WFSim Torid: field
                    # ticks 40 x crit with Plentiful Mayhem's +31 base). The
                    # pool-multishot +60% follows each generated grenade into
                    # its field, so it stays.
                    part_fx = ModEffectList(e for e in part_fx
                                            if not (e.upgrade_type == 'WEAPON_DAMAGE_AMOUNT' and e.operation == 'ADD_BASE'))
                part, part_spec = apply_mods_spec({**wp, 'fireModes': [rm], '__compressionProfile__': extra.get('compression'),
                                   **({'__coProfile__': component['coProfile']} if component.get('coProfile') else {})},
                                  part_fx, scenario=replace(scenario, incarnon_cycle=False, victim_status_count=count_ceiling))
                part = replace(part, radial_only=True, weakpoint_damage_bonus=0.0, weakpoint_crit_chance_bonus=0.0, weakpoint_crit_chance_relative=0.0, headshot_bonus_multiplier=1.0)
                if component.get('takes_multishot') is False:
                    part = replace(part, multishot=1.0)
                if component.get('count'):
                    part = replace(part, multishot=part.multishot * float(component['count']))
                part._co_spec = part_spec
                if component.get('impact_delay_seconds') is not None:
                    part._impact_delay = float(component['impact_delay_seconds'])
                if component.get('headOnly'):
                    part._head_only = True
                if extra.get('radial') or extra.get('radials'):
                    radial_parts.append(part)
                else:
                    st._lingering = (part, component['tick_rate'], component['duration_seconds'])
        if radial_parts:
            radial = radial_parts[0]
            radial._additional_radials = tuple(radial_parts[1:])
        if extra.get('requiresFullAmmo'):
            st._requires_full_ammo = True
        if extra.get('primaryDelaySeconds') is not None:
            st._primary_delay_seconds = float(extra['primaryDelaySeconds'])
        if extra.get('charge'):
            scales = extra['charge'].get('scalesWithFireRate', wp.get('slot') != 'arch_gun')
            fire_scaling = max(st.fire_rate / float(modes[idx]['fireRate']),1e-9) if scales else 1.
            st._charge_time = extra['charge']['seconds'] / (fire_scaling*st.charge_rate_multiplier)
        if extra.get('bow'):
            st._bow_draw = extra['drawSeconds'] / (max(st.fire_rate / float(modes[idx]['fireRate']), 1e-9)*st.charge_rate_multiplier)
        if miter_aoe and idx==0 and not wp.get('isIncarnonForm'):
            rm=deepcopy(modes[idx])
            rm.update(falloffRange=[0,0],falloffMinDamage=1)
            rm['damage']={**rm['damage'],'types':{'DT_EXPLOSION':miter_aoe['damage']},'forcedProcs':[]}
            radial,radial_spec=apply_mods_spec({**wp,'fireModes':[rm]},[e for e in fx if e.upgrade_type!='WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE'],
                             scenario=replace(scenario,incarnon_cycle=False,victim_status_count=0))
            radial=replace(radial,radial_only=True,weakpoint_damage_bonus=0.,weakpoint_crit_chance_bonus=0.,
                           weakpoint_crit_chance_relative=0.,bodyshot_crit_multiplier=1.,headshot_bonus_multiplier=1.)
            radial._co_spec=radial_spec
            st.charge_seconds+=miter_aoe['holdSeconds']
            st._charge_time=getattr(st,'_charge_time',st.charge_seconds-miter_aoe['holdSeconds'])+miter_aoe['holdSeconds']
        return st, radial

    syndrome = None
    for record, rank, _ in mod_records:
        sid = ref["mods"].get(record["path"])
        if not sid:
            continue
        power = sum(
            float(e.get("valuePerRank") or 0) * (rank + 1)
            for e in record.get("effects") or []
            if e.get("upgradeType") == "WEAPON_SYNDICATE_POWER"
        )
        if power > 0:
            syndrome = dict(
                id=sid,
                damageType=mapped[ref["syndicates"][sid]["element"]],
                affinityToFill=1000 / power,
            )
    if not syndrome:
        sid = ref.get("nativeSyndicates", {}).get(weapon["path"])
        if sid:
            syndrome = dict(
                id=sid,
                damageType=mapped[ref["syndicates"][sid]["element"]],
                affinityToFill=1000.0,
            )
    enemy = affinity_target or {}
    base_affinity = enemy.get("affinity")
    if base_affinity is None:
        base_affinity = ref["enemyAffinity"].get(
            str(enemy.get("nameEn") or enemy.get("name") or "").casefold()
        )
    affinity = (
        math.floor(
            float(base_affinity)
            * ((3.0 if eximus else 1.0) + 0.1425 * math.sqrt(max(level or 1, 1)))
        )
        * 0.5
        if base_affinity is not None
        else None
    )
    from .beam_ramp import floor_for
    exact = resolve

    def resolve(form, stacks, live_types=0, last_round=False):
        # A fractional live status count scales only the CO bucket. Resolve
        # the whole count it rounds up to once, then redo the CO tail of each
        # stats object (damage.co_variant) instead of every apply_mods.
        count_ceiling = int(math.ceil(live_types))
        if count_ceiling and live_types != count_ceiling and not onos_sequence:
            template = cached(form, stacks, count_ceiling, last_round)
            varied = live_variant(template, live_types, count_ceiling)
            if varied is not None:
                return varied
        return exact(form, stacks, live_types, last_round)

    def cached(form, stacks, live_types, last_round):
        if resolve_cache is None:
            return resolve(form, stacks, live_types, last_round)
        key = (form, tuple(sorted(stacks.items())), live_types, last_round)
        if key not in resolve_cache:
            resolve_cache[key] = resolve(form, stacks, live_types, last_round)
        return resolve_cache[key]

    entry = cached if resolve_cache is not None else resolve
    return dict(
        resolve=entry,
        melee=melee,
        comboTierKeys=combo_tier_keys,
        beamRampFloors={
            'base':floor_for(base_attack if base_attack.get('source') else ref.get('coProfiles',{}).get(weapon.get('path'),{}).get('0',{})),
            'selected':floor_for(selected_attack if selected_attack.get('source') else ref.get('coProfiles',{}).get(weapon.get('path'),{}).get(str(mode_index),{}))},
        enervate=enervate,
        **status_arcanes,
        cycle=cycle,
        onosCharge=onos_sequence,
        doubleTap=double_tap,
        sniperCombo=sniper_combo,
        onosCrits=onos_crit,
        punctureArmorStrip=next((v for b in branches if (v:=latron_puncture_strip(b))),0.),
        magazineRestore=next((v for b in branches if (v:=ammo_restore_configuration(b))),None),
        refillMagazineGrowth=any(c.get('refillMagazineGrowth') for b in branches for c in incarnon_condition_rows(b)),
        syndicate=syndrome,
        affinityPerKill=affinity,
        trigger_sources=sources,
        unsupported=notes,
        lastBurst=any(
            "Burston" in str(b.get("path")) and str(b.get("id")) == "2-1"
            for b in branches
        ),
        multishotLocked=any(e.upgrade_type == "RUNTIME_LOCK_MULTISHOT" for e in static),
        conditionOverload=any(
            e.upgrade_type in {"WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE","WEAPON_CRIT_UNDER_PROC_THRESHOLD_MAX"} for e in [*original, *(term for _, terms in dynamic for term in terms)]
        ),
        baseBurst=((base_attack.get("burst") or (profile.get("burst") if profile else None)) if cycle
                   else None if weapon.get("isIncarnonForm") else (base_attack if mode_index == 0 else selected_attack).get("burst")),
        baseFireRate=modes[0 if cycle else mode_index].get("fireRate"),
        incarnonBurst=(selected_attack.get("burst") or native_burst(weapon, mode_index)) if weapon.get("isIncarnonForm") else None,
        incarnonFireRate=modes[mode_index].get("fireRate"),
        energySpendPerSecond=float(scenario.combat_state.get('energySpendPerSecond') or 0.),
        projectileState={**dict(scenario.combat_state),'mqAugmentEquipped':mq_augment is not None},
        selectedIncarnon=bool(weapon.get("isIncarnonForm")) and not cycle,
        weaponSlot=weapon.get("slot"),
        spool=base_attack.get("spool") if mode_index == 0 and not weapon.get("isIncarnonForm") else None,
        fireRateSpool=base_attack.get("fireRateSpool") if mode_index == 0 and not weapon.get("isIncarnonForm") else None,
        # The battery belongs to the weapon: every non-Incarnon mode draws
        # from (and regenerates) the same magazine.
        battery=selected_attack.get("battery"),
        lastRoundMultishot=last_round_multishot,
        fieldDurationOnEmptyReload=field_duration,
        distance=scenario.distance,
        manualDetonation=({**selected_attack['manualDetonation'],
                           'delaySeconds':scenario.detonation_delay_seconds,
                           'batchSize':scenario.detonation_batch_size}
                          if selected_attack.get('manualDetonation') else None),
        # combatState.infiniteAmmo (Bot preset): the magazine never runs dry,
        # so there are no reloads, recharges or reload-triggered effects.
        infiniteAmmo=bool(scenario.combat_state.get('infiniteAmmo')),
        reloadAfterEveryShot=(not weapon.get("isIncarnonForm") and not cycle
                              and reloads_after_every_shot(weapon, mode_index)),
        shellReload=({'start': base_attack['reloadStart'], 'perShell': base_attack['reloadPerShell'],
                      'end': base_attack['reloadEnd'], 'modeSwitchLoadsShell': base_attack.get('modeSwitchLoadsShell', True)}
                     if base_attack.get('reloadPerShell') is not None else None),
    )
