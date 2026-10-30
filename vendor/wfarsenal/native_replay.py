"""Dispatch of the event replay to the native core (wfcore.trajectory).

The native loop covers ordinary guns (combat_replay._trajectory's common
path); ``trajectory`` returns None when a replay needs something it does not
cover yet, and the caller runs the Python reference. Results are identical to
the reference bit for bit; ``WF_NATIVE_SHADOW=1`` runs both on every replay and
raises on the first difference, ``WF_NATIVE=0`` turns the native path off.

Stat resolution and the per-hit damage tables stay in Python: ``_Helper``
holds verbatim copies of the reference's ``attack_data`` and crit-view code,
which the native loop calls back.
"""
from __future__ import annotations

import os
from copy import copy

try:  # The library is optional: tools/build_native.py builds it.
    from . import wfcore  # type: ignore
except ImportError:  # pragma: no cover - depends on the build
    wfcore = None

ENABLED = wfcore is not None and os.environ.get("WF_NATIVE", "1") != "0"
HEALTH_BATCH = os.environ.get("WF_NATIVE_HEALTH_BATCH", "1") != "0"
HEALTH_BATCH_STATS = {"batches": 0, "runs": 0}
SHADOW = os.environ.get("WF_NATIVE_SHADOW") == "1"
STATS = {"native": 0, "fallback": 0}

# Combat features the native loop does not cover yet (each falls back).
_UNSUPPORTED_COMBAT = (

)


def supported(stats, options) -> bool:
    if not ENABLED or not getattr(wfcore,"NATIVE_TYPE_QUANTIZATION",0) or options.get("collect_timeline", True):
        return False
    draw = options.get("weak_draw")
    if draw is not None and not callable(getattr(draw, "native_spec", None)):
        return False
    combat = options.get("combat")
    if not combat or not combat.get("resolve"):
        return False
    if ((combat.get('manualDetonation') or {}).get('impactThenEmbed')
            and not getattr(wfcore,'ALT_EMBEDDED_LIFECYCLE',0)):
        return False
    if combat.get('enervate') and not getattr(wfcore, 'ENERVATE_PROBABILISTIC_HITS', 0):
        return False  # Older cores treat every expected Blast proc as a real hit.
    if getattr(stats, 'ignore_headshot_bonus', False) and not getattr(wfcore, 'IGNORE_HEADSHOT_BONUS', 0):
        return False
    if (combat.get('stugIdealDetonation') or getattr(stats, 'area_direct', False)) and not getattr(wfcore, 'STUG_AREA_DIRECT', 0):
        return False
    if (combat.get('sniperCombo') or {}).get('incarnon') and not getattr(wfcore, 'SNIPER_INCARNON_COMBO', 0):
        return False
    if combat.get('persistentRadials') and not getattr(wfcore, 'PERSISTENT_RADIALS', 0):
        return False
    if combat.get('sniperCombo') and not getattr(wfcore, 'SNIPER_COMBO_STATUS', 0):
        return False
    if combat.get('cycle') and not getattr(wfcore, 'RELOAD_SCALED_TRANSFORMS', 0):
        return False
    if (combat.get('cycle') or {}).get('sourceModeKillChargeTrue') and not getattr(wfcore,'SOURCE_MODE_KILL_CHARGE',0):
        return False
    if (combat.get('cycle') or {}).get('chargeBeforeFire') and not getattr(wfcore, 'KILL_CHARGED_WINDUP', 0):
        return False
    if (combat.get('delayedRadialEvents') or getattr(stats, 'delayed_radial_hit_event', False)) and getattr(wfcore, 'DELAYED_RADIAL_EVENTS', 0) < 3:
        return False
    if (combat.get('radialCritStatus') or stats.radial_victim_crit) and not getattr(wfcore, 'RADIAL_VICTIM_CRIT', 0):
        return False
    if combat.get('victimStackParts') and not getattr(wfcore,'RADIAL_VICTIM_STACKS',0):
        return False
    if combat.get('ownedEmbed') and not getattr(wfcore,'SOURCE_OWNED_EMBED',0):
        return False
    if combat.get('grimoireStrategy') and not getattr(wfcore,'GRIMOIRE_SELECTED_COVERAGE',0):
        return False
    if combat.get('zymosChildren') and not getattr(wfcore,'ZYMOS_ORDERED_CHILDREN',0):
        return False
    if combat.get('stugIdealDetonation') and not getattr(wfcore,'STACKABLE_CRITICAL_EVENTS',0):
        return False
    if combat.get('delayedRadialEvents') and not getattr(wfcore,'RADIAL_LIVE_CO',0):
        return False
    if combat.get('quantaStrategy') and not getattr(wfcore,'QUANTA_PAID_PRIMARY',0):
        return False
    if combat.get('nativeFireGate') and not getattr(wfcore, 'NATIVE_FIRE_COOLDOWN', 0):
        return False
    if combat.get('chargeBeforeFire') and not getattr(wfcore, 'ORDINARY_CHARGED_WINDUP', 0):
        return False
    if combat.get('fullClipCharge') and not getattr(wfcore, 'FULL_CLIP_CHARGE_WAIT_POLICY', 0):
        return False
    if combat.get('chargeVolley') and not getattr(wfcore, 'MAGAZINE_CHARGE_VOLLEY', 0):
        return False
    if combat.get('finiteFields') and getattr(wfcore,'NEUTRAL_FINITE_FIELD_SOURCE',0)<2:
        return False
    if combat.get('finiteFields') and not getattr(wfcore,'INDEPENDENT_FINITE_FIELDS',0):
        return False
    if combat.get('sourceOwnedFields') and not getattr(wfcore,'SOURCE_OWNED_FIELDS',0):
        return False
    if combat.get('physicalProjectileLanes') and '_laneStratum' not in combat:
        if abs(stats.multishot-round(stats.multishot))>1e-9 or combat.get('fractionalProjectileLanes'):
            return False  # Health batch must not bypass whole-trajectory stratification.
    if combat.get('physicalProjectileLanes') and not getattr(wfcore,'PHYSICAL_PROJECTILE_LANES',0):
        return False
    if combat.get('projectileSequence') and not getattr(wfcore, 'COMPANION_PROJECTILE_SEQUENCE', 0):
        return False
    if combat.get('melee') and not getattr(wfcore, 'MELEE_INITIAL_COMBO_RECOVERY', 0):
        return False
    if combat.get('cycle') and combat.get('melee'):
        return False  # no melee Incarnon cycle is modelled natively
    return not any(combat.get(key) for key in _UNSUPPORTED_COMBAT)


class _Helper:
    """The reference's per-replay damage tables, called back by the native loop."""

    def __init__(self, target, locations, bare_def, forced_procs, combat=None):
        self.target = target
        self.locations = locations
        self.bare_def = bare_def
        self.forced_procs = forced_procs
        self.probes = {}
        self.crit_views = {}
        self.combat = combat or {}
        melee = self.combat.get('melee')
        self.melee = melee
        self.hits = []
        self._hit_ids = {}
        self._applied = {}

    def melee_segments(self):
        """The route as wfcore walks it (melee_sequence.Loop.next): per segment
        (fixed, anim, charge-scaled, flight-scaled, hit id or None, heavy, combo
        hits, consumes combo, slam phase bits: 1 a slam starts, 2 it ends). Hit
        ids number the hits in the order the loop first reaches them."""
        rows = []
        for segment in self.melee['segments']:
            hit = segment.get('hit')
            if not hit:
                rows.append((segment['fixed'], segment['anim'], bool(segment.get('chargeScaled')),
                             bool(segment.get('flightScaled')), None, False, 0.0, False, 0))
                continue
            key = id(hit)
            if key not in self._hit_ids:
                self._hit_ids[key] = len(self.hits)
                self.hits.append(hit)
            rows.append((segment['fixed'], segment['anim'], bool(segment.get('chargeScaled')),
                         bool(segment.get('flightScaled')), self._hit_ids[key], bool(hit.get('heavy')),
                         float(hit.get('comboHits', 1.0)), bool(hit.get('consumesCombo')),
                         (1 if hit.get('slamStart') else 0) | (2 if hit.get('slamEnd') else 0)))
        return rows

    def stackable_profile(self, profile):
        """A `_stackable` profile flattened to the numbers wfcore's clocks read."""
        merge = (profile.get('merge') or {}).get('damage') or {}
        low, high = profile.get('mergeDamage') or (0.0, 0.0)
        return dict(
            kind={'stug': 0, 'simulor': 1, 'mq': 2}.get(profile.get('kind'), 3),
            embedSeconds=profile.get('embedSeconds') or 0.0, maxLife=profile.get('maxLife') or 0.0,
            embedInterval=profile.get('embedInterval') or 0.0, maxStack=profile.get('maxStack') or 0.0,
            mergeLow=low, mergeHigh=high, mergeNative=sum(merge.values()),
            attachAtStack=profile.get('attachAtStack', float('inf')),
            singularityInterval=(profile.get('singularity') or {}).get('interval') or 0.0,
            resetLifeOnStack=bool(profile.get('resetLifeOnStack')), stackedLife=profile.get('stackedLife') or 0.0,
            initialStack=profile.get('initialStack', 1.), child=bool(profile.get('child')),
            childMaxCount=profile.get('childMaxCount') or 0, childMinCount=profile.get('childMinCount') or 0,
            childBounceCount=profile.get('childBounceCount') or 0, childLife=profile.get('childLife') or 0.0,
            childDeathMultiplier=profile.get('childDeathMultiplier', 1.0),
            childActiveLimit=profile.get('childActiveLimit',70),
        )

    def hit_spec(self, hit_id):
        """What melee_sequence.apply_hit (and Duplicate) read of one hit, for wfcore."""
        from .melee_sequence import _PROC_TYPES
        hit = self.hits[hit_id]
        base_chance, base_multiplier = self.melee['meleeCrit']
        target = hit.get("damageType")
        duplicate = self.combat.get('duplicate')
        return (
            float(hit.get("atten", 1.0)),
            bool(hit.get("slam")),
            bool(hit.get("comboMultiplier")),
            {k: float(v) for k, v in (hit.get("damagePct") or {}).items()},
            target if target and target not in ("DT_PHYSICAL", "DT_ANY") else None,
            float(hit["critChance"]) / float(base_chance) if hit.get("critChance") is not None and base_chance else None,
            (float(hit["critMultiplier"]) / float(base_multiplier)
             if hit.get("critMultiplier") is not None and base_multiplier else None),
            bool(hit.get("canCrit", True)),
            [_PROC_TYPES[p] for p in hit.get("extraProcs") or () if _PROC_TYPES.get(p)],
            float(hit.get("procAtten", 1.0)),
            bool(hit.get("radial")),
            (float(duplicate['chance']), float(duplicate.get('uptime', 1.0)))
            if duplicate and hit.get('canCrit', True) else None,
            bool(hit.get("throw")),
            bool(hit.get("bounce")),
            bool(hit.get("noConditionOverload")),
        )

    def melee_apply(self, active, hit_id, heavy_multiplier):
        """apply_hit plus Melee Duplicate, as the reference's fire event does."""
        key = (id(active), hit_id, heavy_multiplier)
        if key in self._applied:
            return self._applied[key][1]
        from dataclasses import replace
        from .melee_sequence import apply_hit
        hit = self.hits[hit_id]
        result = apply_hit(active, hit, melee_crit=self.melee['meleeCrit'], heavy_multiplier=heavy_multiplier)
        duplicate = self.combat.get('duplicate')
        if duplicate and hit.get('canCrit', True):
            chance = min(max(result.crit_chance, 0.0), 2.0)
            yellow = chance if chance < 1.0 else 2.0 - chance
            factor = 1.0 + duplicate['chance'] * duplicate.get('uptime', 1.0) * yellow
            if factor != 1.0:
                result = replace(result, multishot=result.multishot * factor)
        self._applied[key] = (active, result)
        return result

    def attack_data(self, st, aim):
        from .damage import damage_against_cached_armour, expected_status_damage, faction_bracket
        locations, bare_def, target, forced_procs, probes = (
            self.locations, self.bare_def, self.target, self.forced_procs, self.probes)
        key = (id(st), aim)
        if key in probes:
            return probes[key][1]
        raw_cache = {**locations["body"], "faction_deltas": {}}
        body = damage_against_cached_armour(
            st, 0.0, bare_def, target=target, _target_cache=raw_cache
        )
        hc = {**locations["head"], "faction_deltas": {}}
        hh = (
            damage_against_cached_armour(
                st, 0.0, bare_def, target=target, _target_cache=hc
            )
            if aim
            else body
        )
        total = body["perShot"] * (1 - aim) + hh["perShot"] * aim
        raw_sum = sum(body["perType"].values())
        vector = (
            {k: v * total / raw_sum for k, v in body["perType"].items()}
            if raw_sum
            else {}
        )
        dot_target = {
            "health": 1.0,
            "armour": 0.0,
            "shield": 0.0,
            "faction": target.get("faction", ""),
            "hitProxies": target.get("hitProxies", []),
            "factionResistance": "RK_NEUTRAL",
            "factionBracket": faction_bracket(target),
        }
        b = expected_status_damage(
            st, dot_target, forced_procs=forced_procs, level=1, hit_location="body"
        )
        h = (
            expected_status_damage(
                st, dot_target, forced_procs=forced_procs, level=1, hit_location="head"
            )
            if aim
            else b
        )
        rows = {}
        for dtype, r in b["dot"]["perType"].items():
            hr = h["dot"]["perType"].get(dtype, r)
            rows[dtype] = {
                **r,
                "seedPerSecondPerProc": r["seedPerSecondPerProc"] * (1 - aim)
                + hr["seedPerSecondPerProc"] * aim,
            }
        procs = {
            k: (1 - aim) * b["expectedProcs"].get(k, 0.0)
            + aim * h["expectedProcs"].get(k, 0.0)
            for k in dict.fromkeys([*b["expectedProcs"], *h["expectedProcs"]])
        }
        non = {}
        for k, row in b.get("nonDot", {}).get("perType", {}).items():
            hr = h.get("nonDot", {}).get("perType", {}).get(k, row)
            non[k] = {
                **row,
                "perProc": row["perProc"] * (1 - aim) + hr["perProc"] * aim,
            }
        result = (vector, procs, rows, non)
        probes[key] = (st, result)
        return result

    def packet(self, st, aim, puncture, cold, shiver, frozen):
        """packet()'s crit-view branch (no Enervate), from the reference."""
        crit_views = self.crit_views
        vector, procs, rows, non = {}, {}, {}, {}
        seed_sums, non_sums = {}, {}
        weights = {0: 1.0}
        for stacks, weight in weights.items():
            key = (id(st), stacks, puncture, cold, shiver, frozen)
            if key not in crit_views:
                view = copy(st)
                view.crit_chance = max(0.0, st.crit_chance + stacks * .1 + puncture)
                view.crit_multiplier = (st.low_crit_damage_base + (st.low_crit_damage_bonus
                    if view.crit_chance < st.low_crit_threshold else 0.)
                    if st.low_crit_threshold is not None else st.crit_multiplier) + cold
                if shiver != 1.0 or frozen != 1.0:
                    view.damage_types = {k: v * shiver * frozen for k, v in st.damage_types.items()}
                    if st.dot_base_damage is not None:
                        view.dot_base_damage = st.dot_base_damage * shiver
                crit_views[key] = (st, view)
            v, p, r, n = self.attack_data(crit_views[key][1], aim)
            for k, value in v.items(): vector[k] = vector.get(k, 0.0) + weight * value
            for k, value in p.items(): procs[k] = procs.get(k, 0.0) + weight * value
            for k, row in r.items():
                rows[k] = dict(row)
                seed_sums[k] = seed_sums.get(k, 0.0) + weight * p.get(k, 0) * row['seedPerSecondPerProc']
            for k, row in n.items():
                non[k] = dict(row)
                non_sums[k] = non_sums.get(k, 0.0) + weight * p.get(k, 0) * row['perProc']
        for k, row in rows.items(): row['seedPerSecondPerProc'] = seed_sums[k] / procs[k] if procs[k] else 0.0
        for k, row in non.items(): row['perProc'] = non_sums[k] / procs[k] if procs[k] else 0.0
        return vector, procs, rows, non

    def crit_proc(self, st, damage_type, aim):
        from .proc_probability import crit_proc_instance_probability
        return crit_proc_instance_probability(st, damage_type, aim)

    def first_shot(self, st):
        active = copy(st)
        factor = 1.0 + active.first_shot_damage_bonus
        active.damage_types = {k: v * factor for k, v in active.damage_types.items()}
        if active.dot_base_damage is not None:
            active.dot_base_damage *= factor
        return active


def _target_tables(target, locations):
    """Per-replay target constants of attack_data (see wfcore tables.rs)."""
    from .damage import (enemy_defenses, _hit_location_info, _faction_damage_deltas, _damage_type_set,
                         _target_damage_multiplier, _overguard_damage_multiplier, _magnetic_defense_multiplier,
                         _normalise_hit_location, DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
                         DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES, faction_bracket)
    dot_target = {
        "health": 1.0,
        "armour": 0.0,
        "shield": 0.0,
        "faction": target.get("faction", ""),
        "hitProxies": target.get("hitProxies", []),
        "factionResistance": "RK_NEUTRAL",
        "factionBracket": faction_bracket(target),
    }
    damage = [(locations[name]["hit_multiplier"], locations[name]["hit_critical_multiplier"], name == "head")
              for name in ("body", "head")]
    dot = []
    for name in ("body", "head"):
        location, hm, hcm, _, _ = _hit_location_info(dot_target, name)
        dot.append((hm, hcm, _normalise_hit_location(location) == "head"))
    defenses = enemy_defenses(dot_target, level=1)
    armour = defenses["armour"]
    overguard = float(defenses.get("overguard") or 0.0)
    magnetic_stacks = int(defenses.get("magneticStacks") or 0)
    faction_deltas = _faction_damage_deltas(dot_target)
    armour_bypass = _damage_type_set(dot_target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES)
    shield_bypass = _damage_type_set(dot_target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES)
    multipliers = {}
    for interaction in ("DT_CINEMATIC", "DT_FIRE", "DT_POISON", "DT_ELECTRICITY", "DT_GAS", "DT_EXPLOSION"):
        if overguard > 0.0:
            value = _overguard_damage_multiplier(interaction, magnetic_stacks)
        else:
            value = _target_damage_multiplier(interaction, dot_target, armour=armour, faction_deltas=faction_deltas,
                                              armour_bypass=armour_bypass, shield_bypass=shield_bypass)
            if defenses["shield"] > 0.0 and interaction not in shield_bypass:
                value *= _magnetic_defense_multiplier(magnetic_stacks)
        multipliers[interaction] = value
    return {"damage": damage, "dot": dot, "dotMultiplier": multipliers}


# The target-only part of a replay's setup, by target (record_keys.record_key)
# and level / strip / Steel Path / enhancements; the entry pins the target.
# Nothing changes these objects: the helper copies before it edits a table.
_TARGET_SETUPS: dict = {}


def _target_setup(target, level, armour_strip, steel_path, enemy_enhancements):
    from .damage import (enemy_defenses, _hit_location_info, _faction_damage_deltas, _damage_type_set,
                         faction_bracket, DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES, DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES)
    try:
        options = None if enemy_enhancements is None else tuple(sorted(enemy_enhancements.items()))
        from .record_keys import record_key
        key = (record_key(target), level, armour_strip, steel_path, options)
        hash(key)
    except (AttributeError, TypeError):
        key = None
    hit = _TARGET_SETUPS.get(key) if key is not None else None
    if hit is not None:
        return hit[1]
    defenses = enemy_defenses(
        target,
        level=level,
        armour_strip=armour_strip,
        steel_path=steel_path,
        enemy_enhancements=enemy_enhancements,
    )
    full = [float(defenses.get(k) or 0.0) for k in ("overguard", "shield", "health")]
    ehp = sum(full)
    armour_base = float(defenses.get("armour") or 0.0)
    cache = dict(
        faction_deltas=_faction_damage_deltas(target),
        armour_bypass=_damage_type_set(
            target.get("armourBypassDamageTypes"), DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES
        ),
        shield_bypass=_damage_type_set(
            target.get("shieldBypassDamageTypes"), DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES
        ),
        target_faction=str(target.get("faction") or ""),
        faction_bracket=faction_bracket(target),
    )
    locations = {}
    for location in ("body", "head"):
        _, hm, hcm, _, _ = _hit_location_info(target, location)
        locations[location] = {
            **cache,
            "hit_multiplier": hm,
            "hit_critical_multiplier": hcm,
        }
    bare_def = {**defenses, "armour": 0.0, "overguard": 0.0, "shield": 0.0}
    tables = _target_tables(target, locations)
    result = (defenses, full, ehp, armour_base, cache, locations, bare_def, tables)
    if key is not None:
        if len(_TARGET_SETUPS) >= 256:
            _TARGET_SETUPS.clear()
        from .record_keys import pin
        _TARGET_SETUPS[key] = (pin(target), result)
    return result


def _projectile_state(state):
    mode = state.get('projectileMode')
    return dict(isolated=mode == 'isolated', manual=mode == 'manual',
                detonateAfterShots=state.get('detonateAfterShots') or None,
                detonationWaitSeconds=state.get('detonationWaitSeconds', 0.),
                stugChildHits=int(state.get('stugChildHits', 5)), stugBounceHits=int(state.get('stugBounceHits', 2)),
                stugBounceDelaySeconds=state.get('stugBounceDelaySeconds', 0.),
                stugChildDetonateSeconds=state.get('stugChildDetonateSeconds'),
                mqAugmentEquipped=bool(state.get('mqAugmentEquipped')))


def _cycle_spec(cycle):
    if not cycle:
        return None
    return {key: cycle.get(key) for key in ('hits', 'enterSeconds', 'exitSeconds', 'pool', 'chargeOn', 'killCharged', 'chargeBeforeFire', 'damageScale', 'sourceModeKillChargeTrue')}


def trajectory(
    stats,
    target,
    *,
    attacks_per_second,
    window_seconds=5.0,
    status_rate_multiplier=1.0,
    damage_rate_multiplier=1.0,
    forced_procs=None,
    level=None,
    armour_strip=0.0,
    elemental_armour_strip=0.0,
    steel_path=False,
    enemy_enhancements=None,
    time_step=0.25,
    trigger_sources=None,
    collect_timeline=True,
    headshot_chance=0.0,
    combat=None,
    weak_draw=None,
    life_curve=None,
    score_only=False,
    health_targets=None,
):
    """The native replay, or None when it must fall back to the reference."""
    from .damage import (
        proc_stack_cap,
        enemy_defenses,
        expected_status_damage,
        damage_against_cached_armour,
        _hit_location_info,
        _faction_damage_deltas,
        _damage_type_set,
        DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
        DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES,
        direct_fire_ledger,
    )
    combat = combat or {}
    if health_targets is not None and combat.get('physicalProjectileLanes') and '_laneStratum' not in combat:
        if abs(stats.multishot-round(stats.multishot))>1e-9 or combat.get('fractionalProjectileLanes'):
            return None  # Caller uses scalar replay, which owns16strata.
    melee = combat.get('melee')
    if melee:
        damage_rate_multiplier = 1.0
        status_rate_multiplier = 1.0
    target = target or {}
    window = max(float(window_seconds), 0.0)
    step = max(0.01, float(time_step))
    head = min(1.0, max(0.0, float(headshot_chance)))
    rate = max(0.0, float(attacks_per_second))
    defenses, full, ehp, armour_base, cache, locations, bare_def, tables = _target_setup(
        target, level, armour_strip, steel_path, enemy_enhancements)
    execute = float((combat or {}).get('executeBelow') or 0.0)
    if execute:
        # combat_replay: Enkaus's dissolve leaves only the health above it.
        full = [full[0], full[1], full[2] * (1.0 - execute)]
        ehp = sum(full)
    names = {
        "DT_FIRE": "heat",
        "DT_VIRAL": "viral",
        "DT_CORROSIVE": "corrosive",
        "DT_MAGNETIC": "magnetic",
        "DT_FREEZE": "cold",
        "DT_PUNCTURE": "puncture",
    }
    sources = []
    for src in trigger_sources or []:
        q = dict(src)
        q.update(stacks=float(q.get("initialStacks", 0)), expires=float("inf"), series=[])
        if q.get('initialDuration') and q['stacks']:
            q['expires'] = float(q['initialDuration'])
        q.setdefault("maxStacks", 1.0)
        q.setdefault("duration", 0.0)
        q.setdefault("perEvent", 1.0)
        q.setdefault("decay", "reset")
        sources.append(q)
    extra_hits = tuple(getattr(stats, 'extra_hits', ()) or ())
    extra_scale = 1.0
    if extra_hits:
        extra_scale = stats.faction_damage_multipliers.get('', 1.0)
        if cache['target_faction']:
            extra_scale *= stats.faction_damage_multipliers.get(cache['target_faction'], 1.0)
        extra_scale *= cache['faction_bracket']
        head_part = float(locations['head']['hit_multiplier'] or 1.0)
        extra_scale *= ((1 - head) + head * head_part * head_part) / ((1 - head) + head * head_part)
    unsupported = list(combat.get("unsupported") or [])
    if (combat.get('manualDetonation') or {}).get('impactThenEmbed'):
        unsupported.extend(['alternox-host-death-lifecycle-unverified',
                            'alternox-instant-detonation-order-idealized'])
    syndrome = combat.get("syndicate")
    if syndrome and not combat.get("affinityPerKill"):
        unsupported.append("syndicate-affinity-unavailable")
    state = combat.get('projectileState') or {}
    actor_events = []
    for key, kind in [('selfShieldBreak', 'on-shield-broken'), ('selfOverguardBreak', 'on-overguard-broken'),
                      ('selfShieldHit', 'on-shield-hit'), ('equipFromPrimary', 'on-equip-from-primary'),
                      ('abilityUse', 'on-warframe-ability')]:
        if key + 'At' in state:
            actor_events.append((float(state[key + 'At']), float(state.get(key + 'Interval', 0.)), kind))
    floors = combat.get('beamRampFloors')
    from .status_arcanes import STATUS_POOL
    fortifier = combat.get('fortifier')
    empowered = combat.get('empowered')
    cryogenic = combat.get('cryogenic')
    encumber = combat.get('encumber')
    if encumber and encumber.get('uptime', 1.0) == 0:
        encumber = None
    helper = _Helper(target, locations, bare_def, forced_procs, combat)
    melee_config = None
    if melee:
        spec = melee['comboSpec']
        first = float(spec.get("baseHits") or 20.0)
        melee_config = dict(baseHits=first, tierStep=float(spec.get("tierStep") or first),
                            cap=float(spec.get("cap") or 220.0),
                            baseMultiplier=float(spec.get("baseMultiplier") or 1.0),
                            recoveryPerSecond=float(spec.get('recoveryPerSecond') or 0.),
                            tierKeys=dict(combat.get('comboTierKeys') or {}),
                            segments=helper.melee_segments())
    config = dict(
        stats=stats, resolver=combat['resolve'], window=window, head=head, rate=rate,
        punctureCap=proc_stack_cap(stats, 'DT_PUNCTURE', 5.0),
        statusRateMultiplier=float(status_rate_multiplier), damageRateMultiplier=float(damage_rate_multiplier),
        full=full, ehp=float(ehp), armourBase=armour_base, elementalArmourStrip=float(elemental_armour_strip),
        forcedProcs=dict(forced_procs or {}), factionDeltas=dict(cache['faction_deltas']),
        armourBypass=list(cache['armour_bypass']), shieldBypass=list(cache['shield_bypass']),
        extraHits=[(dtype, float(share)) for dtype, share, _forced in extra_hits], extraScale=float(extra_scale),
        weaponSlot=str(combat.get("weaponSlot") or ""), distance=combat.get("distance"),
        punchthrough=float(state.get('punchthroughTargets', 0) or 0),
        liveTypes=bool(combat.get("conditionOverload") or stats.co_bucket),
        beamFloor=(floors or {}).get('selected', .2) if floors else None,
        burst=(combat.get('incarnonBurst') if combat.get('selectedIncarnon') else combat.get('baseBurst')) or None,
        burstRate=combat.get('incarnonFireRate') if combat.get('selectedIncarnon') else combat.get('baseFireRate'),
        selectedIncarnon=bool(combat.get('selectedIncarnon')),
        cycle=_cycle_spec(combat.get('cycle')),
        manualDetonation=combat.get('manualDetonation') or None,
        lifeCurve=life_curve is not None,
        onosCharge=combat.get('onosCharge') or None, onosCrits=bool(combat.get('onosCrits')),
        projectileState=_projectile_state(combat.get('projectileState') or {}),
        burstBase=combat.get('baseBurst') or None, burstRateBase=combat.get('baseFireRate'),
        burstIncarnon=combat.get('incarnonBurst') or None, burstRateIncarnon=combat.get('incarnonFireRate'),
        beamFloorBase=(floors or {}).get('base', .2) if floors else None,
        lastBurst=bool(combat.get('lastBurst') and not combat.get('multishotLocked')),
        infiniteAmmo=bool(combat.get('infiniteAmmo')),
        victimBefore=dict(combat.get('victimProcTypesBeforeHit') or {}),
        syndicate=dict(syndrome) if syndrome else None,
        targetFaction=cache['target_faction'], factionBracket=cache['faction_bracket'], tables=tables,
        melee=melee_config, projectileSequence=combat.get("projectileSequence"),
        physicalProjectileLanes=combat.get("physicalProjectileLanes"),laneStratum=float(combat.get("_laneStratum",.5)),
        battery=combat.get('battery') or None, spool=combat.get('spool') or None,
        fireRateSpool=combat.get('fireRateSpool') or None, shellReload=combat.get('shellReload') or None,
        sniperCombo=combat.get('sniperCombo') or None, magazineRestore=combat.get('magazineRestore') or None,
        reloadAfterEveryShot=bool(combat.get('reloadAfterEveryShot')),
        refillMagazineGrowth=bool(combat.get('refillMagazineGrowth')),
        affinityPerKill=float(combat.get("affinityPerKill") or 0.0),
        sources=sources, actorEvents=actor_events, energyRate=float(combat.get('energySpendPerSecond') or 0.),
        fortifier=fortifier, empowered=empowered, cryogenic=cryogenic, statusPool=list(STATUS_POOL),
        enervate=combat.get('enervate') or None,
        doubleTap=combat.get('doubleTap') or None,
        fieldDurationOnEmptyReload=combat.get('fieldDurationOnEmptyReload') or None,
        encumber=encumber, punctureArmorStrip=float(combat.get('punctureArmorStrip') or 0.0),
        weakDraw=weak_draw.native_spec() if weak_draw is not None else None,
    )
    try:
        if health_targets is not None:
            targets = []
            for enhancements in health_targets:
                _, pools, _, _, _, _, _, _ = _target_setup(target, level, armour_strip, steel_path, enhancements)
                pools = list(pools)
                if execute:
                    pools[2] *= 1.0 - execute
                targets.append((pools, sum(pools)))
            rows = wfcore.trajectory_health_batch(config, helper, targets)
            STATS["native"] += len(rows)
            HEALTH_BATCH_STATS["batches"] += 1
            HEALTH_BATCH_STATS["runs"] += len(rows)
            return [dict(killsPerMinute=kpm, windowDps=dps, totalWindowDamage=damage,
                         unsupported=[*unsupported, *([('alternox-multishot-active-cap-unresolved' if (combat.get('manualDetonation') or {}).get('impactThenEmbed') else 'talons-single-throw-deployment-overflow-unmodeled')] * overflows)],
                         limitations=[]) for kpm, dps, damage, overflows in rows]
        core = wfcore.trajectory(config, helper)
    except wfcore.NativeUnsupported:
        STATS["fallback"] += 1
        return None
    except wfcore.ReplayRunaway as exc:
        # The reference would run into the same limit, only slower.
        from .simulator import SimulationError
        raise SimulationError(str(exc)) from None
    STATS["native"] += 1
    if weak_draw is not None:
        weak_draw.absorb(core)
    combat['lastRound'] = core["lastRound"]
    if core["attacks"]:
        combat['victimProcTypesBeforeHit'] = core["victimBefore"]
    if core["actorSignalUsed"]:
        combat['_actorSignal'] = False
    for q, stacks in zip(sources, core["sourceStacks"]):
        q["stacks"] = stacks
    pools = core["pools"]
    kills = core["kills"]
    totals = dict(zip(("direct", "dot", "nonDot", "syndicate", "arcane"), core["totals"]))
    averaged = {k: 0.0 for k in names.values()}
    score = kills + (1 - sum(pools) / ehp if ehp else 0.0)
    if score_only and life_curve is None and not collect_timeline:
        unsupported.extend([('alternox-multishot-active-cap-unresolved' if (combat.get('manualDetonation') or {}).get('impactThenEmbed') else 'talons-single-throw-deployment-overflow-unmodeled')] * core["mines"][3])
        return dict(killsPerMinute=score * 60 / window if window else 0.0,
                    windowDps=sum(totals.values()) / window if window else 0.0,
                    totalWindowDamage=sum(totals.values()), unsupported=unsupported, limitations=[])
    initial = damage_against_cached_armour(
        stats, armour_base, defenses, target=target, _target_cache=locations["body"]
    )
    if head:
        h = damage_against_cached_armour(
            stats, armour_base, defenses, target=target, _target_cache=locations["head"]
        )
        initial["perShot"] = initial["perShot"] * (1 - head) + h["perShot"] * head
    ledger = (
        direct_fire_ledger(
            attacks_per_second=rate,
            window_seconds=window,
            target_ehp=ehp,
            component_damage=[
                ("expected-shot", initial["perShot"] * damage_rate_multiplier)
            ],
            collect_trace=False,
        )
        if ehp and rate
        else {}
    )
    ledger.update(status="diagnostic-static-defense", perShotDamage=initial["perShot"])
    attacks = core["attacks"]
    if life_curve is not None:
        sources_named = ("direct", "dot", "nonDot", "syndicate", "arcane")
        life_curve.extend((t, hit, variance, sources_named[source]) for t, hit, variance, source in core["lifeCurve"])
    manual_detonation = combat.get('manualDetonation')
    detonations, pending_mines, waiting_mines, overflows = core["mines"]
    unsupported.extend([('alternox-multishot-active-cap-unresolved' if (combat.get('manualDetonation') or {}).get('impactThenEmbed') else 'talons-single-throw-deployment-overflow-unmodeled')] * overflows)
    enervate = None
    if combat.get('enervate'):
        from .enervate import EnervateState, ASSUMPTIONS
        enervate = EnervateState(combat['enervate'])
        states, enervate.hits, enervate.resets, enervate.last = core["enervate"]
        enervate.states = {(s, b): p for s, b, p in states}
    return {
        "model": "event-expected-v3",
        "eventModel": "target-generation-events-v3",
        "windowSeconds": window,
        "timeStep": step,
        "attacksPerSecond": attacks / window if window else 0.0,
        "statusEventsPerSecond": rate * status_rate_multiplier,
        "timeline": [],
        "averagedStacks": {
            k: v / window if window else 0.0 for k, v in averaged.items()
        },
        "steadyStacks": {},
        "killsPerMinute": score * 60 / window if window else 0.0,
        "killsInWindow": score,
        "killEvents": kills,

        "weakpointKillEvents": core["weakKillEvents"],
        "targetGeneration": core["gen"],
        "targetTotalEhp": ehp,
        "directWindow": totals["direct"],
        "dotWindow": totals["dot"],
        "arcaneWindow": totals["arcane"],
        "dotByType": core["dotByType"],
        "procCounts": core["procCounts"],
        "nonDotWindow": totals["nonDot"],
        "syndicateWindow": totals["syndicate"],
        "syndicateEvents": core["syndicateEvents"],
        "totalWindowDamage": sum(totals.values()),
        "windowDps": sum(totals.values()) / window if window else 0.0,
        "firstKillTime": core["firstKill"],
        "minKillInterval": core["minInterval"],
        "maxKillsPerStep": 0,
        "staleComponents": core["stale"],
        'fieldDuration': ({**combat['fieldDurationOnEmptyReload'], 'boostedShots': core['fieldDuration'][0],
                           'ready': core['fieldDuration'][1], 'events': []}
                          if combat.get('fieldDurationOnEmptyReload') else None),
        'manualDetonation': ({**manual_detonation, 'detonations': detonations,
                              'pendingMines': pending_mines + waiting_mines, 'events': []}
                             if manual_detonation else None),
        'delayedAttackEvents': core['delayedAttackEvents'],
        'projectileEvents': [],
        'fullClipCharge': combat.get('fullClipCharge'),
        'quantaStrategy': combat.get('quantaStrategy'),
        'zymosChildren': combat.get('zymosChildren'),
        'grimoireStrategy':combat.get('grimoireStrategy'),
        'chargeVolley': {'policy':'full-magazine','events':[]} if combat.get('chargeVolley') else None,
        'projectileLifecycle': (dict(zip(('deployed', 'merged', 'explosions', 'singularities', 'childProjectiles'),
                                         core['projectiles'])) if 'projectiles' in core else {}),
        'onosSequence': ({'events': [], 'alignmentShots': combat['onosCharge']['alignmentShots'],
                          'powerCost': combat['onosCharge']['powerCost']} if combat.get('onosCharge') else None),
        'doubleTap': ({'events': [], 'maximum': combat['doubleTap']['maximum'],
                       'duration': combat['doubleTap']['duration']} if combat.get('doubleTap') else None),
        'melee': {'route': melee['route'], 'label': melee.get('label'), 'combo': melee.get('combo'),
                  'stance': melee.get('stance'), 'events': []} if melee else None,
        'sniperCombo': {'events': [], 'minimum': combat['sniperCombo']['min'],
                        'seconds': combat['sniperCombo']['seconds']} if combat.get('sniperCombo') else None,
        "shots": attacks,
        "reloads": core["reloads"],
        'reloadShellEvents': core["reloadShellEvents"],
        "recharges": core["recharges"],
        'spoolTrace': [],
        "transforms": core["transforms"],
        "directEventLedger": ledger,
        "emergent": {"onKillStacks": "events" if sources else "panel-assumed-max"},
        "enervate": enervate.summary() if enervate else None,
        "magneticBreaks": core["magneticBreaks"],
        'fortifier': ({'multiplier': fortifier['multiplier'], 'overguardDamage': core['fortifier'][0],
                       'stolenTotal': core['fortifier'][1], 'selfOverguard': core['fortifier'][2],
                       'cap': fortifier['cap'], 'selfDamageModeled': False} if fortifier else None),
        'encumber': ({'chance': encumber['chance'], 'expectedExtraProcs': core['encumberExpected'],
                      'events': [], 'typeCount': 13, 'coPresence': 'per-application-occurrence'} if encumber else None),
        'empowered': ({'damagePerStatus': empowered['damage'], 'expectedInstances': core['empowered'][0],
                       'windowDamage': totals['arcane'], 'damageByType': core['empowered'][1],
                       'sourcePolicy': 'weapon-status-only-no-script-link-dot-recursion'} if empowered else None),
        'cryogenic': ({'coldStacksPerPuncture': cryogenic['coldStacks'],
                       'radiusMeters': cryogenic['radius'],
                       'expectedColdApplications': core['cryogenicExpected'],
                       'neighborTargetsModeled': False} if cryogenic else None),
        "triggerSeries": [
            {
                **{k: q[k] for k in ("id", "label", "kind", "maxStacks", "series")},
                **{k: q[k] for k in ('conditionText', 'resetOn', 'simulationMode') if k in q},
                "avgStacks": (
                    sum(q["series"]) / len(q["series"]) if q["series"] else 0.0
                ),
                "uptime": (
                    sum(v > 0 for v in q["series"]) / len(q["series"])
                    if q["series"]
                    else 0.0
                ),
            }
            for q in sources
        ] + ([enervate.summary()] if enervate else []),
        "perAttack": expected_status_damage(
            stats,
            target,
            forced_procs=forced_procs,
            level=level,
            armour_strip=armour_strip,
            steel_path=steel_path,
            enemy_enhancements=enemy_enhancements,
        ),
        "continuousKillEvents": True,
        "activePool": "overguard" if full[0] else ("shield" if full[1] else "health"),
        "unsupported": unsupported,
        **({"finiteFieldPackets":core["finiteFieldPackets"],"finiteFieldActivations":core["finiteFieldActivations"],"finiteFieldTrace":[]} if combat.get("finiteFields") else {}),
        **({"sourceOwnedFieldPackets":core["sourceOwnedFieldPackets"],"sourceOwnedFieldActivations":core["sourceOwnedFieldActivations"],"sourceOwnedFieldTrace":[]} if combat.get("sourceOwnedFields") else {}),
        **({"physicalProjectileTrace":[],"physicalProjectilePhase":core["physicalProjectilePhase"]} if combat.get("physicalProjectileLanes") else {}),
        "limitations": [
            "expected-proc-counts-not-Monte-Carlo",
            "single-target",
            "non-heat-stacking-procs-expected",
            "single-target-syndicate-no-player-buffs",
            "magnetic-break-six-ticks-pinned-reference-contract",
            'spread-hit-loss-not-modeled',
        ] + (['spool-linear-rate-from-raw-max-shots','spool-idle-threshold-reset-no-partial-decay'] if combat.get('spool') else [])
          + (['fire-rate-spool-reference-transcribed','fire-rate-spool-resets-on-any-pause'] if combat.get('fireRateSpool') else [])
          + ([('alternox-active-cap-conservative-lower-bound' if manual_detonation.get('impactThenEmbed') else 'talons-expected-projectile-capacity'),'manual-detonation-explicit-player-cadence'] if manual_detonation else [])
          + (['onos-native-alignment-shots-held-rate-and-postfire-cadence','onos-radial-target-coverage-explicit']
             if combat.get('onosCharge') else [])
          + (ASSUMPTIONS if enervate else [])
          + (['encumber-poisson-status-presence','encumber-single-target-expected-procs'] if encumber else [])
          + (['cryogenic-single-target-expected-procs-no-neighbor-burst'] if cryogenic else [])
          + (['empowered-grouped-expected-instances','empowered-derived-script-procs-excluded'] if empowered else [])
          + (['fortifier-raw-multiply-r5-x8-reference-x9-conflict','fortifier-player-overguard-no-incoming-damage'] if fortifier else []),
    }


class ShadowMismatch(AssertionError):
    pass


def _first_difference(a, b, path="result"):
    if isinstance(a, dict) and isinstance(b, dict):
        if list(a) != list(b):
            return f"{path}: keys {list(a)} != {list(b)}"
        for k in a:
            found = _first_difference(a[k], b[k], f"{path}.{k}")
            if found:
                return found
        return None
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        if len(a) != len(b):
            return f"{path}: length {len(a)} != {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            found = _first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return f"{path}: type {type(a).__name__} != {type(b).__name__}"
    if a != a and b != b:  # NaN
        return None
    return None if a == b else f"{path}: {a!r} != {b!r}"


def shadow(stats, target, options, reference):
    """Run the reference and the native loop on copies of the combat state."""
    import copy as _copy
    combat = options.get("combat") or {}
    native_combat = dict(combat)
    native_options = dict(options, combat=native_combat,
                          trigger_sources=_copy.deepcopy(options.get("trigger_sources")))
    if options.get("life_curve") is not None:
        native_options["life_curve"] = []
    draw = options.get("weak_draw")
    if draw is not None:
        native_options["weak_draw"] = _copy.copy(draw)
    native = trajectory(stats, target, **native_options)
    expected = reference(stats, target, **options)
    if native is None:
        return expected
    found = _first_difference(native, expected)
    if not found and draw is not None and vars(native_options["weak_draw"]) != vars(draw):
        found = f"weakDraw: {vars(native_options['weak_draw'])!r} != {vars(draw)!r}"
    if not found and options.get("life_curve") is not None:
        found = _first_difference(native_options["life_curve"], options["life_curve"], "lifeCurve")
    if found:
        raise ShadowMismatch(found)
    return expected
