from __future__ import annotations

import json
import math
import sys
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def reference():
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return json.loads(
        (root / "data/mechanics/combat-reference.json").read_text(encoding="utf-8")
    )


def condition_kind(condition):
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
        "onpistolheadshotkillcondition": "on-headshot-kill",
        "onheadshotkillanysourcecondition": "on-headshot-kill",
        "onheadshotkillcondition": "on-headshot-kill",
        "onkillheadshotriflecondition": "on-headshot-kill",
        "onkillheadshotpistolcondition": "on-headshot-kill",
        "onkillcondition": "on-kill",
        "onkillriflecondition": "on-kill",
        "onpistolkillcondition": "on-kill",
        "onprimarykillcondition": "on-primary-kill",
        "onmeleekillanysourcecondition": "on-melee-kill",
        "onmeleekillcondition": "on-melee-kill",
        "oncritcondition": "on-crit",
        "oncriticalhitcondition": "on-crit",
        "onhitcondition": "on-hit",
        "onreloadcondition": "on-reload",
        "onheatproccondition": "proc-DT_FIRE",
        "oncoldproccondition": "proc-DT_FREEZE",
        "ontoxinproccondition": "proc-DT_POISON",
        "onelectricityproccondition": "proc-DT_ELECTRICITY",
        "onproccondition": "on-proc",
        "onshotgunclosekillcondition": "on-close-kill",
    }
    return next((exact[x] for x in names if x in exact), None)


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
):
    from .damage import ModEffect, ModEffectList, apply_mods

    weapon = engine["weapon"]
    scenario = engine["scenario"]
    mode_index = engine["fire_mode"]
    original = list(engine["effects"])
    from .enervate import configuration, PATH as ENERVATE_PATH, IGNORED_ALT
    enervate = None
    sources = []
    dynamic = []
    excluded = set()
    notes = []
    branches = []
    for tier in (weapon.get("incarnon") or {}).get("tiers") or []:
        number = tier.get("tier")
        wanted = (incarnon_choices or {}).get("tier" + str(number)) or (
            incarnon_choices or {}
        ).get(str(number))
        branches.extend(b for b in tier.get("branches") or [] if b.get("id") == wanted)
    from .runtime_adapters import verified_crux_condition

    replaced_terms = set()
    for record, rank, override in [
        *mod_records,
        *arcane_records,
        *[(b, 0, None) for b in branches],
    ]:
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
        for ci, condition in enumerate(record.get("conditionalEffects") or []):
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
            if condition.get("runtimeScripts"):
                source = str(condition.get("sourcePath") or record["path"])
                if not ("Burston" in source and "Tier1ASubMod" in source):
                    notes.append(source + ":runtime-condition-unmodeled")
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
            if not effects:
                continue
            replaced_terms.update(
                (source, e.upgrade_type, e.operation, e.damage_type) for e in effects
            )
            kind = condition_kind(condition)
            if not kind:
                notes.append(str(source) + ":event-condition-unmodeled")
                continue
            if (
                any("PM_AIM" in e.valid_modifiers for e in effects)
                and not scenario.aiming
            ):
                continue
            excluded.add(source)
            key = source + ":" + str(ci)
            cap = float(condition.get("maxStacks") or 1.0)
            forced = (override or {}).get("stacks")
            uptime = (override or {}).get('uptime')
            fixed = forced is not None or uptime is not None or assumed
            initial = min(max(float(forced), 0.0), cap) if forced is not None else (cap if fixed else 0.0)
            if uptime is not None:
                initial *= min(max(float(uptime), 0.0), 1.0)
            sources.append(
                dict(
                    id=key,
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
    from .event_profiles import base_profile
    base_attack = base_profile({**weapon, 'isIncarnonForm': False, '__selectedFireMode__': 0}, 0)
    cycle = (
        profile
        if cycle_enabled and weapon.get("isIncarnonForm") and profile and len(modes) > 1
        else None
    )
    if cycle_enabled and weapon.get("isIncarnonForm") and not cycle:
        notes.append("incarnon-cycle-data-unavailable")
    if (
        profile
        and profile.get("radial")
        and profile.get("referenceId")
        not in ("burston_incarnon", "burston_prime_incarnon")
    ):
        notes.append(profile["referenceId"] + ":radial-payload-unmodeled")
    if any(
        "Require" in str(c.get("runtimeScripts"))
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

    def resolve(form, stacks, live_types=0):
        fx = ModEffectList(static)
        for key, terms in dynamic:
            n = stacks.get(key, 0.0)
            if n > 0:
                fx.extend(replace(e, value=(1.0 + (e.value - 1.0) * n) if e.operation == 'MULTIPLY' else e.value * n) for e in terms)
        idx = 0 if form == "base" else mode_index
        wp = {
            **weapon,
            "isIncarnonForm": form != "base" and weapon.get("isIncarnonForm", False),
        }
        wp = {**wp, '__selectedFireMode__': idx}
        st = apply_mods(
            wp,
            fx,
            fire_mode=idx,
            scenario=replace(
                scenario, incarnon_cycle=False, victim_status_count=live_types
            ),
        )
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
            }
            radial = apply_mods(
                {**wp, "fireModes": [rm]},
                fx,
                scenario=replace(scenario, incarnon_cycle=False, victim_status_count=0),
            )
            radial = replace(
                radial,
                multishot=1.0,
                weakpoint_damage_bonus=0.0,
                weakpoint_crit_chance_bonus=0.0,
                weakpoint_crit_chance_relative=0.0,
                headshot_bonus_multiplier=1.0,
            )
        extra = base_attack if idx == 0 and not wp.get('isIncarnonForm') else {}
        component = extra.get('radial') or extra.get('lingering')
        if component and component.get('damage'):
            rm = deepcopy(modes[idx])
            rm['damage'] = {
                **rm['damage'], 'types': {mapped[k]: v for k, v in component['damage'].items()},
                'critChance': component.get('crit_chance', rm['damage'].get('critChance')),
                'critMultiplier': component.get('crit_multiplier', rm['damage'].get('critMultiplier')),
                'procChance': component.get('status_chance', rm['damage'].get('procChance')),
            }
            part_fx = fx if component.get('takes_condition_overload') else ModEffectList(e for e in fx if e.upgrade_type != 'WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE')
            part = apply_mods({**wp, 'fireModes': [rm]}, part_fx, scenario=replace(scenario, incarnon_cycle=False, victim_status_count=live_types))
            part = replace(part, weakpoint_damage_bonus=0.0, weakpoint_crit_chance_bonus=0.0, weakpoint_crit_chance_relative=0.0, headshot_bonus_multiplier=1.0)
            if component.get('takes_multishot') is False:
                part = replace(part, multishot=1.0)
            if extra.get('radial'):
                radial = part
            else:
                st._lingering = (part, component['tick_rate'], component['duration_seconds'])
        if extra.get('bow'):
            st._bow_draw = extra['drawSeconds'] / max(st.fire_rate / float(modes[idx]['fireRate']), 1e-9)
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
    return dict(
        resolve=resolve,
        enervate=enervate,
        cycle=cycle,
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
            e.upgrade_type == "WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE" for e in [*original, *(term for _, terms in dynamic for term in terms)]
        ),
        baseBurst=(base_attack.get("burst") or (profile.get("burst") if profile else None)) if mode_index == 0 or cycle else None,
        baseFireRate=modes[0].get("fireRate"),
        baseMode=mode_index == 0,
        selectedIncarnon=bool(weapon.get("isIncarnonForm")) and not cycle,
        weaponSlot=weapon.get("slot"),
        battery=base_attack.get("battery") if mode_index == 0 and not weapon.get("isIncarnonForm") else None,
        distance=scenario.distance,
    )
