"""Exalted weapons: the frame link, ability-scaled damage and the energy readout.

Exalted weapons are fought like ordinary weapons (tools/extract-exalted-weapons.py
puts them in the export with an ``exalted`` block). What the weapon page adds:

* the linked frame: a Warframe page config (A/B/C) run through the warframe
  engine gives Ability Strength / Efficiency / Duration, max energy / shields
  and the summoning ability's scaled energy cost;
* ability-scaled damage: rows in ``DAMAGE_RULES`` replace or multiply the
  weapon's base damage with the ability's Strength-scaled figure;
* the energy readout. Simulations always run with unlimited energy. The
  readout states how long the weapon lasts / how many casts fit in one full
  energy bar without regeneration, and raises a persistent warning when the
  build could not start the ability or could not chain the next cast.
"""
from __future__ import annotations

import math
from typing import Any, Mapping

# A channelled weapon that empties a full bar faster than this cannot be
# kept up in practice.
SUSTAIN_FLOOR_SECONDS = 3.0
# Combo-type casts (Whipclaw, Landslide...) need at least this many casts in
# one bar to reach the follow-up hits the replay assumes.
CHAIN_CASTS = 2


def meta(weapon: Mapping[str, Any]) -> Mapping[str, Any] | None:
    block = weapon.get("exalted")
    return block if isinstance(block, Mapping) else None


def linked_frame_paths(catalog: Mapping[str, Any], weapon: Mapping[str, Any]) -> list[str]:
    """Map legacy carrier ids to the independently moddable form of a weapon.

    Before alternate forms existed, Shadow Claws pointed at Sevagoth itself.
    Keep that old link as a migration input, but resolve it to the Shadow whose
    own Strength/Aura/Arcanes actually drive the claws. Other exalted weapons
    retain their original carrier unchanged.
    """
    block = meta(weapon) or {}
    weapon_path = str(weapon.get("path") or "")
    forms = [row for row in catalog.get("warframeForms") or () if isinstance(row, Mapping)]
    result: list[str] = []
    for original in block.get("framePaths") or ():
        replacement = next((row for row in forms if str(row.get("parentFrameId") or "") == str(original)
                            and weapon_path in (row.get("exaltedWeapons") or ())), None)
        resolved = str((replacement or {}).get("id") or (replacement or {}).get("path") or original)
        if resolved not in result:
            result.append(resolved)
    return result


# Headshot notes are not all aim restrictions (client Packages.bin):
# Regulators fire through LotusCustomAimFireBehavior (RequiresTarget=1), which
# locks a target and aims at its aimAtPart = TORSO; Lizzie's impact behaviour
# sets IgnoreHeadshotBonus=1.
HEADSHOT_NOTES: dict[str, str] = {
    "Cowgirl": "自动锁定目标并瞄准躯干，无法爆头",
    "Temple": "命中头部没有爆头加成",
}


def headshot_issue(weapon: Mapping[str, Any]) -> str | None:
    return HEADSHOT_NOTES.get(str((meta(weapon) or {}).get("family") or ""))


def locks_headshot_aim(weapon: Mapping[str, Any]) -> bool:
    """Automatic torso targeting is distinct from a head-damage suppression flag."""
    return (meta(weapon) or {}).get('family') == 'Cowgirl'


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def warframe_request(frame_id: str, config: Mapping[str, Any] | None) -> dict[str, Any]:
    """Translate a saved Warframe page config into a warframe engine request."""
    request: dict[str, Any] = {"frameId": frame_id}
    if not isinstance(config, Mapping):
        return request
    for key in ("aura", "exilus"):
        if config.get(key):
            request[key] = config[key]
    request["normalMods"] = [
        {**row, "slot": slot} for slot, row in enumerate(config.get("normalMods") or ()) if isinstance(row, Mapping)
    ]
    if isinstance(config.get("slotPolarities"), Mapping):
        request["slotPolarities"] = config["slotPolarities"]
    request["arcanes"] = [row for row in config.get("arcanes") or () if isinstance(row, Mapping)]
    request["shards"] = [
        {"path": row.get("path"), "tau": bool(row.get("tau"))}
        for row in config.get("shards") or () if isinstance(row, Mapping) and row.get("path")
    ]
    if isinstance(config.get("helminthSlot"), int) and config.get("helminthAbility"):
        request["helminthReplacement"] = {"slot": config["helminthSlot"], "abilityId": config["helminthAbility"]}
    request["invigoration"] = [{"id": value} for value in config.get("invigoration") or () if isinstance(value, str)]
    request["applyConditionals"] = bool(config.get("applyConditionals"))
    return request


def frame_context(engine: Any, weapon: Mapping[str, Any], link: Any) -> dict[str, Any]:
    """Resolve ``exaltedFrame`` ({frameId, config, configName}) for an exalted weapon.

    Without a link the weapon's own frame is used at rank 30 with no MODs.
    """
    block = meta(weapon) or {}
    link = link if isinstance(link, Mapping) else {}
    linked_paths = linked_frame_paths(engine.catalog, weapon)
    original_paths = [str(value) for value in block.get("framePaths") or ()]
    requested = str(link.get("frameId") or "")
    if requested in linked_paths:
        frame_id = requested
    elif requested in original_paths:
        # Legacy saved links used the carrier rather than its second form.
        frame_id = linked_paths[original_paths.index(requested)]
    elif requested:
        raise ValueError(f"frameId is not linked to this exalted weapon: {requested}")
    else:
        frame_id = next(iter(linked_paths), None)
    if not frame_id:
        raise ValueError("exalted weapon has no frame")
    request = warframe_request(str(frame_id), link.get("config"))
    form = engine.form_record(frame_id) if hasattr(engine, "form_record") else None
    if form and isinstance(link.get("parentConfig"), Mapping):
        inherited = warframe_request(str(form.get("parentFrameId")), link.get("parentConfig"))
        # The Shadow owns MODs/Aura/Arcanes, but uses the carrier's shards and
        # Invigoration. Never merge the carrier's Strength/MODs into this build.
        for key in ("shards", "invigoration"):
            request[key] = inherited.get(key) or []
    result = engine.calculate(request)
    return context_from_result(result, weapon, frame_id, link)


def context_from_result(result: Mapping[str, Any], weapon: Mapping[str, Any], frame_id: Any,
                        link: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Frame context from an already calculated Warframe build."""
    block = meta(weapon) or {}
    link = link if isinstance(link, Mapping) else {}
    panel = result.get("finalPanel") or {}
    slot = block.get("abilitySlot")
    ability = None
    if isinstance(slot, int):
        rows = result.get("abilityScalars") or []
        ability = rows[slot] if slot < len(rows) else None
    # A Helminth ability placed over the exalted ability's slot removes the weapon.
    replaced = None
    if ability and (ability.get("recipePath") or ability.get("kind") in {"subsumed", "native"}):
        replaced, ability = ability.get("nameZh") or ability.get("nameEn") or "Helminth 技能", None
    frame = result.get("frame") or {}
    return {
        "abilityReplaced": replaced,
        "frameId": frame.get("id") or frame_id,
        "frameName": frame.get("nameZh") or frame.get("nameEn") or frame_id,
        "parentFrameId": frame.get("parentFrameId"),
        "formKind": frame.get("formKind"),
        "configName": link.get("configName") if isinstance(link.get("configName"), str) else None,
        "configured": isinstance(link.get("config"), Mapping),
        "abilityModPaths": [row['path'] for row in (result.get('capacityBreakdown') or {}).get('assignments',())
                            if row.get('path')],
        "panel": {key: _number(panel.get(key)) for key in (
            "abilityStrength", "abilityDuration", "abilityEfficiency", "abilityRange", "energy", "shield", "castingSpeed")},
        "ability": {
            "slot": slot,
            "nameZh": (ability or {}).get("nameZh"),
            "nameEn": (ability or {}).get("nameEn"),
            "energyCost": dict((ability or {}).get("energyCost") or {}),
            "scalars": list((ability or {}).get("scalars") or ()),
        } if ability else None,
    }


# Per-shot costs the ability table lacks or gets wrong (wiki prose): Neutralize
# 10 per shot, Noctua 2 per shot, Artemis Bow 15 per shot and no drain.
# Base values; Efficiency scales them like the engine's other costs.
ENERGY_OVERRIDES: dict[str, Mapping[str, float]] = {
    "Frumentarius": {"perShot": 10.0},
    "Pagemaster": {"perShot": 2.0},
    "Ranger": {"perShot": 15.0, "drainPerSecond": 0.0},
}


def _scaled_cost(block: Mapping[str, Any], cost: Mapping[str, Any], panel: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(cost)
    override = ENERGY_OVERRIDES.get(str(block.get("family") or ""))
    if override:
        factor = max(0.25, 2.0 - (_number(panel.get("abilityEfficiency")) or 1.0))
        for key, value in override.items():
            out[key] = value * factor
    return out


def energy_report(weapon: Mapping[str, Any], context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Readout for one full bar without regeneration, plus persistent warnings."""
    block = meta(weapon)
    if not block or not context:
        return None
    tier = block.get("tier")
    if tier == "always":
        return {"kind": "free", "lines": ["常驻武器，不消耗能量"], "warnings": []}
    if context.get("abilityReplaced"):
        slot = block.get("abilitySlot")
        where = f"{slot + 1} 号技能" if isinstance(slot, int) else "显赫技能"
        return {"kind": "replaced", "lines": [], "warnings": [
            f"当前战甲配置用 Helminth 的「{context['abilityReplaced']}」替换了 {where}：游戏中无法使用这把显赫武器。"
            "当前结果只按技能强度完成模拟。"]}
    ability = context.get("ability") or {}
    panel = context.get("panel") or {}
    cost = _scaled_cost(block, ability.get("energyCost") or {}, panel)
    resource = str(cost.get("resource") or "energy")
    name = ability.get("nameZh") or ability.get("nameEn") or "技能"
    if resource not in {"energy", "shield"}:
        label = {"restraint": "克制值", "deathWell": "死亡之井"}.get(resource, resource)
        return {"kind": resource, "lines": [f"{name}消耗{label}，不按能量计算续航"], "warnings": []}
    pool = _number(panel.get("shield" if resource == "shield" else "energy")) or 0.0
    unit = "护盾" if resource == "shield" else "能量"
    activation = _number(cost.get("activation")) or 0.0
    drain = _number(cost.get("drainPerSecond")) or 0.0
    # The replay fires Balefire fully charged.
    per_shot = _number(cost.get("chargedShot")) or _number(cost.get("perShot"))
    per_target = _number(cost.get("perTarget"))
    lines: list[str] = [f"{unit}上限 {pool:g}"]
    warnings: list[str] = []
    report: dict[str, Any] = {"kind": resource, "pool": pool, "activation": activation, "drainPerSecond": drain}
    if activation > pool + 1e-9:
        warnings.append(
            f"{unit}上限 {pool:g} 低于{name}的启动消耗 {activation:g}：实际无法启动。"
            "当前结果为完成模拟按无限能量计算。")
    if drain > 0:
        seconds = max(0.0, pool - activation) / drain
        report["sustainSeconds"] = seconds
        lines.append(f"启动 {activation:g} + 每秒 {drain:g}：不回复时可持续 {seconds:.1f} 秒")
        if not warnings and seconds < SUSTAIN_FLOOR_SECONDS:
            warnings.append(
                f"一管{unit}只能维持 {seconds:.1f} 秒：实际无法维持。当前结果为完成模拟按无限能量计算。")
    elif per_shot:
        shots = math.floor(max(0.0, pool - activation) / per_shot)
        report["shots"] = shots
        lines.append(f"启动 {activation:g} + 每发 {per_shot:g}：不回复时可开火 {shots} 次")
        report["perShot"] = per_shot
        if not warnings and shots < 1:
            warnings.append(f"启动后{unit}不够开一发：实际无法维持。当前结果为完成模拟按无限能量计算。")
    elif per_target:
        marks = math.floor(pool / per_target)
        report["marks"] = marks
        lines.append(f"每个标记 {per_target:g}：不回复时可标记 {marks} 个目标")
        if marks < 1:
            warnings.append(f"{unit}不够标记一个目标：实际无法启动。当前结果为完成模拟按无限能量计算。")
    elif activation > 0 and tier != "cast":
        lines.append(f"启动消耗 {activation:g}，之后持续使用不再耗能")
    elif activation > 0:
        factors = CAST_COST_FACTORS.get(str(block.get("family") or "")) or [1.0]
        casts, left = 0, pool
        while casts < 10000 and left + 1e-9 >= activation * factors[casts % len(factors)]:
            left -= activation * factors[casts % len(factors)]
            casts += 1
        report["casts"] = casts
        chain = "（连按第 2 / 3 拳消耗减半 / 四分之一）" if len(factors) > 1 else ""
        lines.append(f"每次施放 {activation:g}{chain}：不回复时可施放 {casts} 次")
        if not warnings and tier == "cast" and casts < CHAIN_CASTS:
            warnings.append(
                f"一管{unit}只够施放 {casts} 次，无法触发后续连击。当前结果为完成模拟按无限能量计算。")
    report["lines"] = lines
    report["warnings"] = warnings
    return report


# (family, slot) -> how the ability's figures enter the weapon. ``base`` lists
# the max-rank base damage per fire mode (scaled by Ability Strength unless
# ``strength`` is False); ``bonus`` is an additive base-damage bonus (like
# Serration) times Strength; ``multiplier`` a separate total multiplier.
# ``source``: "wiki" where the wiki states the Strength rule, "ability-data"
# where only the ability table (data/warframe_build_data.json, Overframe)
# tags the figure as Strength-scaled. Notes: docs/BATCH-2026-10-21-B.md.
DAMAGE_RULES: dict[tuple[str, str], Mapping[str, Any]] = {
    ("Excalibur", "melee"): {"base": [250], "source": "ability-data"},
    ("Berserker", "melee"): {"base": [250], "source": "ability-data"},
    ("MonkeyKing", "melee"): {"base": [300], "source": "ability-data"},
    ("Pacifist", "melee"): {"base": [250], "source": "ability-data"},
    ("Fairy", "melee"): {"base": [200], "source": "native-FairyFlight.lua"},
    ("Fairy", "secondary"): {"base": [160], "source": "native-FairyFlight.lua"},
    ("Ranger", "primary"): {"base": [240], "source": "native-RangerBow.lua"},
    ("Choir", "secondary"): {"base": [150], "source": "native-ChoirErupt.lua"},
    ("Pagemaster", "secondary"): {"base": [250, 2750], "source": "native-PagemasterBook.lua"},
    # 500 per bolt; the engine's charge multiplier makes the full charge 1500.
    ("IronFrame", "secondary"): {"base": [500, 500], "source": "ability-data"},
    ("Wraith", "melee"): {"base": [250], "source": "wiki"},
    ("Khora", "melee"): {"base": [150], "source": "wiki"},
    ("Glass", "melee"): {"base": [400], "types": {"DT_PUNCTURE": 1.0}, "source": "wiki"},
    ("Brawler", "melee"): {"base": [350], "types": {"DT_IMPACT": 1.0}, "source": "wiki"},
    ("Ninja", "melee"): {"base": [1500], "source": "wiki"},
    # Peacemaker: Base x (1 + 150% ramp x bursts/20) x (1 + 1.5 x Strength + mods);
    # the replay holds the ramp full (20 bursts in).
    ("Cowgirl", "secondary"): {"bonus": 1.5, "multiplier": 2.5, "source": "wiki"},
    ("Frumentarius", "primary"): {"bonusMultiplier": 1.25, "source": "native-FrumentariusSniper.lua"},
    ("Temple", "primary"): {"base": [85, 100, 100, 100, 100], "strength": False, "bonusMultiplier": 1.25, "source": "native-TempleGuitar.lua"},
}

# Cast-type weapons: one attack per cast. Seconds per cast come from the cast
# animations (client _H headers, 2026-10-21): Whipclaw CrackStrikeForward
# 1.1 s, Shattered Lash Sweep 0.7 s, Landslide RockPunch A/B/C, Blade Storm
# AshBSCast 0.5 s + one clone swing (DualSword Combo1A/B 0.53 / 0.6 s). Every
# recast within 5 s adds 20 combo points (+1 for the enemy hit) and the cast's
# damage scales 1:1 with the combo multiplier, capped at 12x.
CAST_SECONDS: dict[str, list[float]] = {
    "Khora": [1.1],
    "Glass": [0.7],
    "Brawler": [0.7333, 0.7667, 1.1667],
    "Ninja": [1.0667],
}
# Part of a cast that Casting Speed does not shorten: Blade Storm's clone swing.
CAST_FIXED_SECONDS: dict[str, float] = {"Ninja": 0.5667}
# Landslide's chained 2nd / 3rd punches cost 1/2 and 1/4 (wiki).
CAST_COST_FACTORS: dict[str, list[float]] = {"Brawler": [1.0, 0.5, 0.25]}
CAST_COMBO_POINTS = 21.0
CAST_LOOP_LENGTH = 128


def damage_rule(weapon: Mapping[str, Any]) -> Mapping[str, Any] | None:
    block = meta(weapon) or {}
    return DAMAGE_RULES.get((str(block.get("family") or ""), str(weapon.get("slot") or "")))


def apply_damage_rules(weapon: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Return the weapon record with the ability's damage figures applied."""
    block = meta(weapon) or {}
    rule = damage_rule(weapon)
    out = dict(weapon)
    if block.get('family')=='Cowgirl':
        out['exaltedUnsupported']=['peacemaker-full-ramp-held-at-maximum-startup-approximation']
    elif block.get('family')=='Choir':
        out['exaltedUnsupported']=['glory-secondary-ability-detonation-unmodeled']
    elif block.get('family')=='Temple':
        out['exaltedUnsupported']=['lizzie-ability-charge-resource-cycle-unmodeled']
    if (block.get('family')=='Ranger' and '/Lotus/Powersuits/Ranger/RangerBowAugmentCard'
            in (context.get('abilityModPaths') or ())):
        out['exaltedUnsupported']=['artemis-concentrated-arrow-not-supported-normal-arrow-policy-used']
    if block.get("tier") == "cast" and block.get("family") in CAST_SECONDS:
        # Casting Speed (Natural Talent, Arcane ... ) plays the cast animation
        # faster: seconds / (1 + bonus).
        speed = max(0.1, 1.0 + (_number((context.get("panel") or {}).get("castingSpeed")) or 0.0))
        fixed = CAST_FIXED_SECONDS.get(block["family"], 0.0)
        base = CAST_SECONDS[block["family"]]
        out["exaltedCast"] = {
            "seconds": [round((value - fixed) / speed + fixed, 6) for value in base],
            "baseSeconds": list(base),
            "castingSpeed": round(speed, 6),
            "comboPoints": CAST_COMBO_POINTS,
        }
    if not rule:
        return out
    strength = _number((context.get("panel") or {}).get("abilityStrength")) or 1.0
    scale = strength if rule.get("strength", True) else 1.0
    multiplier = float(rule.get("multiplier") or 1.0)
    bases = list(rule.get("base") or ())
    modes = []
    for position, mode in enumerate(weapon.get("fireModes") or ()):
        if block.get('family')=='Ranger' and mode.get('index',position)==1:
            # RangerBow's equipped callback selects and casts Quiver here;
            # inherited impact8 is not a second Artemis damage source.
            modes.append({**mode,'behaviorKind':'ability-action',
                'unavailableReason':'月神狩弓副操作释放箭袋技能，不是独立伤害射击'})
            continue
        damage = dict(mode.get("damage") or {})
        types = {k: float(v) for k, v in (damage.get("types") or {}).items() if isinstance(v, (int, float))}
        if rule.get("types") or sum(types.values()) <= 0:
            types = dict(rule.get("types") or types)
        total = sum(types.values())
        index = mode.get("index", position)
        target = bases[index] * scale if isinstance(index, int) and index < len(bases) else None
        per = (target / total if target is not None and total > 0 else 1.0) * multiplier
        damage["types"] = {k: v * per for k, v in types.items()}
        damage["total"] = sum(damage["types"].values())
        if block.get('family')=='Choir' and index==0:
            # ChoirErupt writes ExplosiveAttack.Amount(+5c8); contact stays0.
            # The exported primary lane already is this one radial packet.
            damage['components']=[{**part,'types':dict(damage['types']),'total':damage['total']}
                if part.get('source')=='ExplosiveAttack' else part
                for part in damage.get('components',())]
            if damage.get('radial',{}).get('source')=='ExplosiveAttack':
                damage['radial']={**damage['radial'],'types':dict(damage['types']),'total':damage['total']}
        if block.get('family')=='Ranger' and index==0:
            # Equipped callback sets seven arrows; FiredArrow multiplies the
            # source .2 proc chance by7 before native raw-iteration division.
            mode={**mode,'multishot':7}
            damage['procChance']=1.4
        modes.append({**mode, "damage": damage})
    out.update({
        "fireModes": modes,
        "exaltedStrength": round(strength, 6),
        "exaltedDamageRule": {
            "base": bases or None, "strengthScaled": bool(rule.get("strength", True)) and bool(bases),
            "bonus": (float(rule["bonusMultiplier"])*strength-1. if rule.get("bonusMultiplier") is not None
                      else float(rule["bonus"])*strength if rule.get("bonus") else None),
            "multiplier": multiplier if multiplier != 1.0 else None,
            "strength": strength, "source": rule.get("source"),
        },
    })
    return out


def weapon_effects(weapon: Mapping[str, Any]) -> list[Any]:
    """Additive base-damage bonus of the ability (Peacemaker, Neutralize, Exalted Solo)."""
    rule = weapon.get("exaltedDamageRule") if isinstance(weapon.get("exaltedDamageRule"), Mapping) else {}
    bonus = _number(rule.get("bonus"))
    if not bonus:
        return []
    from .damage import ModEffect
    return [ModEffect("WEAPON_DAMAGE_AMOUNT", "STACKING_MULTIPLY", bonus, source_path=f"exalted:{weapon.get('path')}")]


def cast_schedule(weapon: Mapping[str, Any], combo_spec: Mapping[str, Any]) -> dict[str, Any] | None:
    """Melee loop for a cast-type weapon: one hit per cast, combo multiplier per cast."""
    cast = weapon.get("exaltedCast")
    if not isinstance(cast, Mapping):
        return None
    from .melee_sequence import combo_multiplier
    seconds = [float(v) for v in cast.get("seconds") or () if _number(v)]
    if not seconds:
        return None
    points = float(cast.get("comboPoints") or CAST_COMBO_POINTS)
    segments = []
    for k in range(CAST_LOOP_LENGTH):
        segments.append(dict(fixed=seconds[k % len(seconds)], anim=0.0, hit=dict(
            kind="cast", t=0.0, atten=combo_multiplier(combo_spec, points * k), procAtten=1.0, extraProcs=[],
            comboHits=points, damagePct={}, canCrit=True, cast=k)))
    return dict(route="cast", combo=None, segments=segments, label="ability-cast")


def cast_metrics(weapon: Mapping[str, Any], context: Mapping[str, Any] | None, average_hit: Any) -> dict[str, Any] | None:
    """Per-cast damage at the first cast and at the 12x cap, and damage per 100 energy."""
    cast = weapon.get("exaltedCast")
    hit = _number(average_hit)
    if not isinstance(cast, Mapping) or hit is None or not context:
        return None
    family = str((meta(weapon) or {}).get("family") or "")
    cost = _number(((context.get("ability") or {}).get("energyCost") or {}).get("activation")) or 0.0
    factors = CAST_COST_FACTORS.get(family) or [1.0]
    average_cost = cost * sum(factors) / len(factors)
    seconds = [float(v) for v in cast.get("seconds") or ()]
    return {
        "firstCast": hit,
        "fullCombo": hit * 12.0,
        "secondsPerCast": sum(seconds) / len(seconds) if seconds else None,
        "castingSpeed": _number(cast.get("castingSpeed")) or 1.0,
        "averageCost": average_cost,
        "per100Energy": hit * 12.0 * 100.0 / average_cost if average_cost > 0 else None,
    }


def frame_summary(weapon: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    """Live summary for the Warframe page: damage per hit from the ability rule and the energy readout."""
    scaled = apply_damage_rules(weapon, context)
    rule = scaled.get("exaltedDamageRule") or {}
    modes = scaled.get("fireModes") or ()
    hit = _number(((modes[0] if modes else {}).get("damage") or {}).get("total"))
    cast = scaled.get("exaltedCast") or {}
    seconds = [float(v) for v in cast.get("seconds") or ()]
    return {
        "path": weapon.get("path"),
        "baseDamage": hit,
        "strengthScaled": bool(rule.get("strengthScaled")),
        "bonus": rule.get("bonus"),
        "secondsPerCast": sum(seconds) / len(seconds) if seconds else None,
        "energy": energy_report(weapon, context),
        "headshotIssue": headshot_issue(weapon),
    }
