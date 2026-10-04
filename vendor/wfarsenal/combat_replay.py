from __future__ import annotations

import heapq
import math
from collections import deque
from dataclasses import replace
from copy import copy


def replay(
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
):
    # Expected proc counts; attack/tick/resource clocks are discrete.
    # Mechanics: WFSim 69e6a139, data/debuffs/ignite.yaml and syndicates/.
    from .damage import (
        enemy_defenses,
        expected_status_damage,
        damage_against_cached_armour,
        _hit_location_info,
        _faction_damage_deltas,
        _damage_type_set,
        DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
        DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES,
        _armour_reduction,
        direct_fire_ledger,
    )

    combat = combat or {}
    from .consecutive_hits import ConsecutiveHits
    tap_spec=combat.get('doubleTap')
    tap=ConsecutiveHits(tap_spec['perHit'],tap_spec['maximum'],tap_spec['duration']) if tap_spec else None
    tap_events=[]
    from .enervate import EnervateState, big_crit_probability, any_probability, ASSUMPTIONS
    enervate = EnervateState(combat['enervate']) if combat.get('enervate') else None
    target = target or {}
    window = max(float(window_seconds), 0.0)
    step = max(0.01, float(time_step))
    head = min(1.0, max(0.0, float(headshot_chance)))
    rate = max(0.0, float(attacks_per_second))
    defenses = enemy_defenses(
        target,
        level=level,
        armour_strip=armour_strip,
        steel_path=steel_path,
        enemy_enhancements=enemy_enhancements,
    )
    full = [float(defenses.get(k) or 0.0) for k in ("overguard", "shield", "health")]
    pools = full.copy()
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
    )
    locations = {}
    for location in ("body", "head"):
        _, hm, hcm, _, _ = _hit_location_info(target, location)
        locations[location] = {
            **cache,
            "hit_multiplier": hm,
            "hit_critical_multiplier": hcm,
        }
    names = {
        "DT_FIRE": "heat",
        "DT_VIRAL": "viral",
        "DT_CORROSIVE": "corrosive",
        "DT_MAGNETIC": "magnetic",
        "DT_FREEZE": "cold",
        "DT_PUNCTURE": "puncture",
    }
    durations = {
        "DT_VIRAL": 6.0,
        "DT_CORROSIVE": 8.0,
        "DT_MAGNETIC": 6.0,
        "DT_FREEZE": 6.0,
        "DT_PUNCTURE": 10.0,
    }
    caps = {
        "DT_VIRAL": 10.0,
        "DT_CORROSIVE": 10.0,
        "DT_MAGNETIC": 10.0,
        "DT_FREEZE": 10.0,
        "DT_PUNCTURE": 5.0,
        "DT_GAS": 10.0,
    }
    states = {}
    gas_procs = deque()
    blast_procs = deque()
    heat = dict(count=0.0, seed=0.0, acc=0.0, start=0.0, end=-1.0, scale=1.0, token=0)
    from .proc_probability import FirstProcClock, StatusPresence, no_status_probability
    heat_clock=FirstProcClock()
    presence={}
    from .beam_ramp import BeamRamp
    beam_ramp=BeamRamp()
    old_heat_strip = ({}, -1.0, 1.0)
    puncture_strip = 0.
    frozen_until = -1.0
    frozen_scale = 1.0
    heap = []
    seq = 0
    gen = 0
    kills = 0
    weak_kill_events = 0.
    attacks = 0
    stale = 0
    first_kill = None
    last_kill = None
    min_interval = None
    totals = dict(direct=0.0, dot=0.0, nonDot=0.0, syndicate=0.0, arcane=0.0)
    proc_counts = {}
    dot_by_type = {}
    magnetic_breaks = []
    fortifier = combat.get('fortifier')
    fortifier_damage = fortifier_stolen = 0.0
    self_overguard = 0.0
    empowered = combat.get('empowered')
    empowered_count = 0.0
    empowered_by_type = {}
    cryogenic = combat.get('cryogenic')
    cryogenic_expected = 0.0
    encumber = combat.get('encumber')
    if encumber and encumber.get('uptime',1.0) == 0:encumber=None
    encumber_time = -math.inf
    encumber_remaining = 1.0
    encumber_expected = 0.0
    encumber_events = []
    encumber_views = {}
    last_totals = totals.copy()
    timeline = []
    averaged = {k: 0.0 for k in names.values()}
    sources = []
    for src in trigger_sources or []:
        q = dict(src)
        q.update(stacks=float(q.get("initialStacks", 0)), expires=math.inf, series=[])
        if q.get('initialDuration') and q['stacks']:
            q['expires'] = float(q['initialDuration'])
        q.setdefault("maxStacks", 1.0)
        q.setdefault("duration", 0.0)
        q.setdefault("perEvent", 1.0)
        q.setdefault("decay", "reset")
        sources.append(q)
    cycle = combat.get("cycle")
    form = "base" if cycle else "selected"
    gauge = 0.0
    transforms = 0
    ammo = stats.magazine
    pending_magazine_restore = 0.0
    shot_in_progress = False
    onos_condition_hits = 0.0
    reloads = 0
    shell_reload = combat.get('shellReload')
    reload_shell_events = []
    mode_switch_shells_owed = 0.0
    recharges = 0
    last_fire_time = -math.inf
    spool_shots = 0
    spool_trace = []
    burst_round = 0
    burst_head_probability = 1.0
    field_duration = combat.get('fieldDurationOnEmptyReload')
    field_duration_ready = False
    field_duration_used = 0
    field_events = []
    manual_detonation = combat.get('manualDetonation')
    pending_mines = []
    pending_throws = 0
    waiting_mines = 0.0
    detonation_count = 0
    detonation_events = []
    delayed_attack_count = 0
    projectile_events = [] if collect_timeline else None
    projectiles = None
    onos = combat.get('onosCharge')
    onos_ticks = 0
    onos_hits = 0.
    onos_start = 0.
    onos_events = []
    first_round = True
    model_cache = {}
    combat['lastRound'] = False
    syndrome = combat.get("syndicate")
    affinity = 0.0
    syndicate_ready = 0.0
    syndicate_events = []
    unsupported = list(combat.get("unsupported") or [])
    if syndrome and not combat.get("affinityPerKill"):
        unsupported.append("syndicate-affinity-unavailable")

    def push(t, kind, payload=None, generation=None):
        nonlocal seq
        if t < window + 1e-9:
            seq += 1
            heapq.heappush(heap, (max(0.0, t), seq, kind, payload, generation))

    def queue_mines(t):
        nonlocal pending_mines, pending_throws, waiting_mines
        batch = pending_mines
        pending_mines = []
        pending_throws = 0
        waiting_mines += sum(part.multishot for part, _ in batch)
        push(t + manual_detonation['delaySeconds'], 'manual-detonation', batch)

    def deliver_projectile(part,t):
        result = packet(part,0.)
        if not take(result[0],t,'direct'):
            add_procs(part,0.,t,result)
        noncrit_no_proc_hit(part,0.,t)

    def count(dtype):
        if dtype == "DT_FIRE":
            return heat["count"]
        if dtype == 'DT_FREEZE' and frozen_until > current_time:
            return 10.0
        if dtype == "DT_GAS":
            return sum(p["count"] for p in gas_procs) + sum(
                x[1] for x in states.get(dtype, ())
            )
        if dtype == "DT_EXPLOSION":
            return sum(p["count"] for p in blast_procs)
        cap = 4.0 if dtype == 'DT_FREEZE' and pools[0] > 0 else caps.get(dtype,math.inf)
        return min(sum(x[1] for x in states.get(dtype, ())),cap)

    def heat_strip(t):
        up=0.0
        if heat["count"]:
            up=heat_clock.strip(t,heat['scale'])
        distribution, ended, scale = old_heat_strip
        if ended < 0:
            return up
        n = int(max(0.0, t - ended) / max(1.5 * scale, 1e-9))
        down=0.
        for value,weight in distribution.items():
            descending = [v for v in (0.5, 0.4, 0.3, 0.15, 0.0) if v <= value + 1e-9]
            down+=weight*descending[min(n,len(descending)-1)]
        return max(up,down)

    def clean(t):
        nonlocal old_heat_strip, frozen_until,heat_clock
        if frozen_until >= 0 and t >= frozen_until - 1e-9:
            states['DT_FREEZE']=deque([(frozen_until+6*frozen_scale,3.0)])
            presence.setdefault('DT_FREEZE',StatusPresence()).add(frozen_until+6*frozen_scale,0.)
            frozen_until=-1.0
        while gas_procs and gas_procs[0]["end"] < t - 1e-9:
            gas_procs.popleft()
        for rows in states.values():
            while rows and rows[0][0] < t - 1e-9:
                rows.popleft()
        if heat["count"] and heat["end"] < t - 1e-9:
            old_heat_strip = (heat_clock.distribution(heat["end"],heat['scale']), heat["end"], heat["scale"])
            heat["count"] = heat["seed"] = 0.0
            heat_clock=FirstProcClock()
            heat["token"] += 1
        for q in sources:
            if q["duration"] and q["stacks"] and t >= q["expires"]:
                if q["decay"] == "lose_one_and_reset":
                    missed = 1 + int((t - q["expires"]) / q["duration"])
                    q["stacks"] = max(0.0, q["stacks"] - missed)
                    q["expires"] += missed * q["duration"]
                elif q.get("decay") != "per-stack":
                    q["stacks"] = 0.0
            if q.get("decay") == "per-stack":
                q["expiries"] = [x for x in q.get("expiries", []) if x[0] > t]
                q["stacks"] = sum(x[1] for x in q["expiries"])

    def armour(t):
        c = count("DT_CORROSIVE")
        cs = 0.26 * c if c < 1 else min(0.26 + 0.06 * (c - 1), 0.8)
        return (
            armour_base * (1 - elemental_armour_strip) * (1 - cs) * (1 - heat_strip(t)) * (1-puncture_strip)
        )

    def vulnerability(n):
        return 1.0 + n if n < 1 else min(2.0 + 0.25 * (n - 1), 4.25)

    def signal(kind, t, weight=1.0):
        for q in sources:
            if q.get('actorOnly') and not combat.get('_actorSignal'):
                continue
            if q.get('toggleOn')==kind and q['perEvent']!=0:
                q['stacks'] = 1.-q['stacks']
                q['expires'] = math.inf
                continue
            gate_probability=(combat.get('victimProcTypesBeforeHit',{}).get(q['victimProcType'],0.)
                              if q.get('victimProcType') else 1.)
            if not gate_probability:
                continue
            if kind in q.get('resetOn', ()) and q['perEvent'] != 0:
                q['stacks'] = 0.0
                q['expires'] = math.inf
                q['expiries'] = []
                q['progress'] = deque()
            if q.get("kind") != kind:
                continue
            required=max(q.get('requiredCount',1),1)
            if required>1:
                progress=q.setdefault('progress',deque())
                if q.get('requiredTime'):
                    while progress and progress[0][0]<t-q['requiredTime']:
                        progress.popleft()
                progress.append((t,weight*gate_probability))
                completed=math.floor((sum(n for _,n in progress)+1e-9)/required)
                consumed=completed*required
                while consumed>1e-9 and progress:
                    when,n=progress.popleft()
                    if n>consumed:
                        progress.appendleft((when,n-consumed))
                    consumed-=n
                delta=completed*q['perEvent']
            else:
                delta=weight*gate_probability*q['perEvent']
            if delta <= 0:
                continue
            if q.get("decay") == "per-stack":
                q.setdefault("expiries", []).append((t + q["duration"], delta))
                excess = sum(x[1] for x in q["expiries"]) - q["maxStacks"]
                while excess > 1e-9 and q["expiries"]:
                    end, n = q["expiries"][0]
                    removed = min(n, excess)
                    excess -= removed
                    if removed >= n:
                        q["expiries"].pop(0)
                    else:
                        q["expiries"][0] = (end, n - removed)
            q["stacks"] = min(q["maxStacks"], q["stacks"] + delta)
            q["expires"] = t + q["duration"] if q["duration"] else math.inf

    def consecutive_heads(t,probability):
        for q in sources:
            if q['kind']!='on-consecutive-headshot' or q['perEvent']==0:
                continue
            minimum = int(q.get('minimumConsecutive') or 1)
            cap = minimum+int(q['maxStacks'])-1
            before = q.get('runDistribution',{0:1.})
            after = {0:1.-probability}
            for run,weight in before.items():
                n = min(run+1,cap)
                after[n] = after.get(n,0.)+weight*probability
            q['runDistribution'] = after
            q['stacks'] = sum(max(run-minimum+1,0)*weight for run,weight in after.items())
            q['expires'] = math.inf

    def die(t, weak_kill=False, weapon_kill=True):
        nonlocal kills, gen, first_kill, last_kill, min_interval, affinity, old_heat_strip, frozen_until, puncture_strip, ammo, pending_magazine_restore,heat_clock,weak_kill_events
        kills += 1
        gen += 1
        if first_kill is None:
            first_kill = t
        if last_kill is not None:
            min_interval = (
                t - last_kill
                if min_interval is None
                else min(min_interval, t - last_kill)
            )
        last_kill = t
        pools[:] = full
        states.clear()
        presence.clear()
        frozen_until=-1.0
        gas_procs.clear()
        blast_procs.clear()
        heat.update(count=0.0, seed=0.0, end=-1.0, token=heat["token"] + 1)
        heat_clock=FirstProcClock()
        old_heat_strip = ({}, -1.0, 1.0)
        puncture_strip = 0.
        signal("on-kill", t)
        slot = str(combat.get("weaponSlot") or "").lower()
        if "longgun" in slot or slot in ("primary", "rifle"):
            signal("on-primary-kill", t)
        if "melee" in slot:
            signal("on-melee-kill", t)
        distance = combat.get("distance")
        if distance is not None and distance <= 5.0:
            signal("on-close-kill", t)
        weak_probability=(head if weak_kill else 0.) if isinstance(weak_kill,bool) else min(1.,max(0.,weak_kill))
        if weak_probability:
            weak_kill_events += weak_probability
            signal("on-headshot-kill", t, weak_probability)
        restore=combat.get('magazineRestore')
        if (weapon_kill and restore and restore['kind'] in {'on-kill','on-headshot-kill'}
                and (form=='base' or (not cycle and not combat.get('selectedIncarnon')))):
            chance=restore.get('chance',1.)*(weak_probability if restore['kind']=='on-headshot-kill' else 1.)*restore.get('fraction',0.)
            if shot_in_progress:
                pending_magazine_restore=1.-(1.-pending_magazine_restore)*(1.-chance)
            else:
                ammo+=max(0.,model(t)[0].magazine-ammo)*chance
        if syndrome and weapon_kill and t >= syndicate_ready:
            affinity += float(combat.get("affinityPerKill") or 0.0)
            if affinity >= syndrome["affinityToFill"]:
                push(t, "syndicate")

    def magnetic_break(t, pool_index):
        stacks = min(count('DT_MAGNETIC'), 10.0)
        if stacks <= 0:
            return
        # Pinned WFSim engine contract: target-pool fraction, six immediate/1s
        # ticks, status-damage multiplier squared; no weapon base/crit/element.
        multiplier = max(model(t)[0].proc_damage_multiplier, 0.0)
        per_tick = full[pool_index] * .03 * stacks * multiplier ** 2 / 6
        magnetic_breaks.append(dict(time=t, pool=('overguard', 'shield')[pool_index],
                                    stacks=stacks, seedPerTick=per_tick, targetGeneration=gen))
        probability=presence['DT_MAGNETIC'].probability(t) if 'DT_MAGNETIC' in presence else 1.
        states.setdefault('DT_ELECTRICITY', deque()).append((t + 6, probability))
        presence.setdefault('DT_ELECTRICITY',StatusPresence()).add(t+6,1.-probability)
        proc_counts['DT_ELECTRICITY'] = proc_counts.get('DT_ELECTRICITY', 0) + probability
        for tick in range(6):
            push(t + tick, 'dot', ('DT_ELECTRICITY', per_tick, t + 6), gen)

    def take(vector, t, source, weak_kill=False):
        # Spend one attack fraction across pools. Shield bypass acts in parallel.
        # Residual damage never leaks to the next target.
        nonlocal fortifier_damage, fortifier_stolen, self_overguard, onos_hits
        if (onos and combat.get('onosCrits') and form!='base' and onos_ticks<onos['alignmentShots']
                and source in {'dot','nonDot'} and any(v>0 for v in vector.values())):
            onos_hits = min(50.,onos_hits+1.)
        left = 1.0
        applied = 0.0

        def health_value(dtype, raw):
            mult = max(
                0.0, 1.0 + cache["faction_deltas"].get(dtype, 0.0)
            ) * vulnerability(count("DT_VIRAL"))
            if dtype not in cache["armour_bypass"]:
                mult *= 1.0 - _armour_reduction(armour(t))
            return raw * mult

        if pools[0] > 0.0:
            value = sum(
                raw * (1.5 if k in ("DT_VOID", "DT_RADIANT") else 1.0)
                for k, raw in vector.items()
            ) * vulnerability(count("DT_MAGNETIC"))
            if fortifier and source != 'syndicate':
                value *= 1.0 + (fortifier['multiplier'] - 1.0) * fortifier.get('uptime', 1.0)
            if value <= 0.0:
                return False
            fraction = min(left, pools[0] / value)
            drain = value * fraction
            pools[0] = max(0.0, pools[0] - drain)
            if fortifier and source != 'syndicate':
                fortifier_damage += drain
                stolen = drain * fortifier['steal'] * fortifier.get('uptime', 1.0)
                fortifier_stolen += stolen
                self_overguard = min(fortifier['cap'], self_overguard + stolen)
            applied += drain
            left -= fraction
            if pools[0] <= 1e-9:
                pools[0] = 0.0  # Retire the pool before a same-timestamp event can break it again.
                magnetic_break(t, 0)
                signal('on-overguard-broken', t)
        if left > 0.0 and pools[1] > 0.0:
            shield = sum(
                raw * max(0.0, 1.0 + cache["faction_deltas"].get(k, 0.0))
                for k, raw in vector.items()
                if k not in cache["shield_bypass"]
            ) * vulnerability(count("DT_MAGNETIC"))
            bypass = sum(
                health_value(k, raw)
                for k, raw in vector.items()
                if k in cache["shield_bypass"]
            )
            fraction = min(
                left,
                pools[1] / shield if shield > 0 else math.inf,
                pools[2] / bypass if bypass > 0 else math.inf,
            )
            a = min(pools[1], shield * fraction)
            b = min(pools[2], bypass * fraction)
            pools[1] -= a
            pools[2] -= b
            applied += a + b
            left -= fraction
            if pools[1] <= 1e-9:
                pools[1] = 0.0
                magnetic_break(t, 1)
                signal('on-shield-broken', t)
        if left > 0.0 and pools[1] <= 1e-9 and pools[2] > 0.0:
            value = sum(health_value(k, raw) for k, raw in vector.items())
            drain = min(pools[2], value * left)
            pools[2] -= drain
            applied += drain
        totals[source] += applied
        if source == 'dot' and len(vector) == 1:
            dtype=next(iter(vector));dot_by_type[dtype]=dot_by_type.get(dtype,0.0)+applied
        if ehp > 0.0 and pools[0] <= 1e-7 and pools[2] <= 1e-7:
            die(t, weak_kill, source != "syndicate")
            return True
        return False

    def model(t):
        live_types = (
            sum(p.probability(t) for p in presence.values())
            if combat.get("conditionOverload") or stats.co_bucket
            else 0
        )
        last_round = bool(combat.get('lastRound'))
        onos_values = {'__onosPower':bool(onos and onos_ticks>=onos['alignmentShots']),
                       '__onosHits':onos_hits,
                       '__onosBeamSeconds':round(min(onos['rampSeconds'],max(0.,t-onos_start)),6) if onos else 0.}
        key = (form, tuple(q["stacks"] for q in sources), live_types, last_round,
               tuple(onos_values.values()) if onos and form!='base' else ())
        if key not in model_cache:
            resolver = combat.get("resolve")
            if resolver:
                try:
                    model_cache[key] = resolver(
                        form, {**{q["id"]: q["stacks"] for q in sources},**onos_values}, live_types, last_round
                    )
                except TypeError as exc:
                    # Test/custom resolvers from older callers use the original
                    # three-argument contract. Preserve that contract unless
                    # the resolver explicitly accepts the new gate.
                    if last_round and 'positional' not in str(exc) and 'argument' not in str(exc):
                        raise
                    model_cache[key] = resolver(
                        form, {q["id"]: q["stacks"] for q in sources}, live_types
                    )
            elif stats.co_bucket:
                from .damage import _combine, _scale_effect

                assumed = _combine(
                    1.0,
                    [_scale_effect(e, stats.co_assumed_count) for e in stats.co_bucket],
                )
                live = _combine(
                    1.0, [_scale_effect(e, live_types) for e in stats.co_bucket]
                )
                ratio = live / assumed if assumed else 1.0
                model_cache[key] = (
                    replace(
                        stats,
                        damage_types={
                            k: v * ratio for k, v in stats.damage_types.items()
                        },
                    ),
                    None,
                )
            else:
                model_cache[key] = (stats, None)
        return model_cache[key]

    bare_def = {**defenses, "armour": 0.0, "overguard": 0.0, "shield": 0.0}
    probes = {}

    def attack_data(st, aim):
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
            seed = r["seedPerSecondPerProc"] * (1 - aim) + hr["seedPerSecondPerProc"] * aim
            # Crit-conditioned procs (Hunter Munitions) are likelier on the
            # weak point, so the per-proc seed averages over procs, not hits.
            count = r["expectedProcs"] * (1 - aim) + hr["expectedProcs"] * aim
            if hr["expectedProcs"] != r["expectedProcs"] and count > 0:
                seed = (r["expectedProcs"] * r["seedPerSecondPerProc"] * (1 - aim)
                        + hr["expectedProcs"] * hr["seedPerSecondPerProc"] * aim) / count
            rows[dtype] = {**r, "seedPerSecondPerProc": seed}
        procs = {
            k: (1 - aim) * b["expectedProcs"].get(k, 0.0)
            + aim * h["expectedProcs"].get(k, 0.0)
            for k in set(b["expectedProcs"]) | set(h["expectedProcs"])
        }
        non = {}
        for k, row in b.get("nonDot", {}).get("perType", {}).items():
            hr = h.get("nonDot", {}).get("perType", {}).get(k, row)
            non[k] = {
                **row,
                "perProc": row["perProc"] * (1 - aim) + hr["perProc"] * aim,
            }
        result = (vector, procs, rows, non)
        probes[key] = (
            st,
            result,
        )  # Retain temporary burst stats to prevent recycled ids.
        return result

    crit_views = {}
    current_time=0.0

    def live_crit():
        cold=count('DT_FREEZE')
        cd=1.0 if frozen_until>current_time else (.1*cold if cold<1 else .1+.05*(cold-1))
        return .05*count('DT_PUNCTURE'),cd

    def packet(st, aim):
        if getattr(st,'_fixed_radial',False):
            return attack_data(st,0.)
        puncture,cold=live_crit()
        if st.radial_only:puncture=0.0
        undamaged = abs(pools[1]-full[1])<1e-7 and abs(pools[2]-full[2])<1e-7
        if undamaged and (st.victim_full_crit_chance or st.victim_full_crit_damage):
            st = replace(st,crit_chance=st.crit_chance+st.victim_full_crit_chance,
                         crit_multiplier=st.crit_multiplier+st.victim_full_crit_damage)
        if full[2]>0 and pools[2]<full[2]*.5 and st.victim_low_health_multiplier!=1.:
            st = replace(st,damage_types={k:v*st.victim_low_health_multiplier for k,v in st.damage_types.items()})
        if not enervate and not puncture and not cold:
            return attack_data(st, aim)
        vector, procs, rows, non = {}, {}, {}, {}
        seed_sums, non_sums = {}, {}
        weights=enervate.damage_marginal() if enervate else {0:1.0}
        for stacks, weight in weights.items():
            key=(id(st), stacks, puncture, cold)
            if key not in crit_views:
                view=copy(st)
                view.crit_chance=max(0.0,st.crit_chance + stacks*.1 + puncture)
                view.crit_multiplier=(st.low_crit_damage_base + (st.low_crit_damage_bonus
                    if view.crit_chance<st.low_crit_threshold else 0.)
                    if st.low_crit_threshold is not None else st.crit_multiplier)+cold
                crit_views[key]=(st,view)
            v,p,r,n=attack_data(crit_views[key][1],aim)
            for k,value in v.items():vector[k]=vector.get(k,0.0)+weight*value
            for k,value in p.items():procs[k]=procs.get(k,0.0)+weight*value
            for k,row in r.items():
                rows[k]=dict(row)
                seed_sums[k]=seed_sums.get(k,0.0)+weight*p.get(k,0)*row['seedPerSecondPerProc']
            for k,row in n.items():
                non[k]=dict(row)
                non_sums[k]=non_sums.get(k,0.0)+weight*p.get(k,0)*row['perProc']
        for k,row in rows.items():row['seedPerSecondPerProc']=seed_sums[k]/procs[k] if procs[k] else 0.0
        for k,row in non.items():row['perProc']=non_sums[k]/procs[k] if procs[k] else 0.0
        return vector,procs,rows,non

    def enervate_hit(st,t,puncture,aim):
        if (not enervate or st.multishot<=0
                or (combat['enervate'].get('ignoreSelected') and form != 'base')):
            return
        weak=st.weakpoint_crit_chance_bonus+st.base_crit_chance*st.weakpoint_crit_chance_relative
        probabilities={}
        for stacks in enervate.marginal():
            cc=max(0.0,st.crit_chance+stacks*.1+puncture)
            # The direct pellet rolls aggregate one grouped Hit. The radial
            # part and status ticks do not masquerade as extra direct pellets.
            p=(1-aim)*big_crit_probability(cc*st.bodyshot_crit_multiplier,st.double_crit_chance)
            p+=aim*big_crit_probability(cc+weak,st.double_crit_chance)
            probabilities[stacks]=any_probability(p,1.0 if st.continuous else st.multishot)
        gain=not (combat['enervate'].get('ignoreSelected') and form != 'base')
        enervate.advance(t,probabilities,gain=gain)

    def noncrit_no_proc_hit(st, aim, t):
        # The native NoProcs/CriticalHit=T_NO gate applies per damage instance,
        # independently to direct and radial parts. It never arms from DoT ticks.
        if not any(q.get('kind') == 'on-noncrit-no-proc' for q in sources):
            return
        puncture = 0.0 if st.radial_only else live_crit()[0]
        weak = st.weakpoint_crit_chance_bonus + st.base_crit_chance * st.weakpoint_crit_chance_relative
        marginal = enervate.damage_marginal() if enervate else {0: 1.0}
        noncrit = 0.0
        for stacks, weight in marginal.items():
            cc = max(0.0, st.crit_chance + stacks * .1 + puncture)
            noncrit += weight * ((1-aim) * max(0.0, 1-cc*st.bodyshot_crit_multiplier) + aim * max(0.0, 1-cc-weak))
        no_proc = max(0.0, 1-st.status_chance)
        for chance in st.independent_proc_chances.values():
            no_proc *= max(0.0, 1-chance)
        for count_per_projectile in (*st.native_forced_procs.values(), *(forced_procs or {}).values()):
            no_proc *= max(0.0, 1-count_per_projectile)
        instances = 1.0 if st.continuous else st.multishot
        signal('on-noncrit-no-proc', t, instances * noncrit * no_proc)

    def empowered_hit(st, dtype, n, t, weapon_status):
        nonlocal empowered_count
        from .status_arcanes import STATUS_POOL
        # Native OnStatusProcALLCondition ignores script/link/DoT sources.
        # Derived Encumber/Cryogenic statuses do not re-enter this weapon hook.
        if not empowered or not weapon_status or dtype not in STATUS_POOL:
            return False
        n *= empowered.get('uptime', 1.0)
        if n <= 0:
            return False
        faction = st.faction_damage_multipliers.get('', 1.0)
        if cache['target_faction']:
            faction *= st.faction_damage_multipliers.get(cache['target_faction'], 1.0)
        empowered_count += n
        before = totals['arcane']
        died = take({dtype:n * empowered['damage'] * faction}, t, 'arcane')
        empowered_by_type[dtype] = empowered_by_type.get(dtype, 0.0) + totals['arcane'] - before
        return died

    def add_procs(st, aim, t, data=None, allow_encumber=True):
        nonlocal frozen_until,frozen_scale,encumber_time,encumber_remaining,encumber_expected,cryogenic_expected,puncture_strip
        generation = gen
        _, procs, rows, non = data if data is not None else packet(st, aim)
        if combat.get('punctureArmorStrip') and not st.radial_only and allow_encumber:
            from .damage import expected_status_procs
            forced=st.native_forced_procs.get('DT_PUNCTURE',0.)+(forced_procs or {}).get('DT_PUNCTURE',0.)
            if forced:
                probability=1.
            else:
                status=max(0.,st.status_chance)
                share=expected_status_procs(st).get('DT_PUNCTURE',0.)/max(status*st.multishot,1e-9)
                share=min(1.,max(0.,share))
                whole=math.floor(status)
                probability=1.-(1.-share)**whole*(1.-(status-whole)*share)
            bullets=1. if st.continuous else st.multishot
            puncture_strip=min(1.,puncture_strip+combat['punctureArmorStrip']*bullets*probability)
        if encumber and allow_encumber and status_rate_multiplier > 0:
            from .status_arcanes import STATUS_POOL, encumber_roll
            if abs(t - encumber_time) > 1e-9:
                encumber_time=t;encumber_remaining=1.0
            probability, merged_seed=encumber_roll(st, encumber['chance'], forced_procs, aim=aim)
            weight=encumber_remaining*probability*encumber.get('uptime',1.0)
            encumber_remaining*=1-probability*encumber.get('uptime',1.0)
            if weight > 0:
                encumber_expected+=weight
                if collect_timeline:encumber_events.append(dict(time=t,expected=weight))
                key=(id(st),aim)
                if key not in encumber_views:
                    probe=replace(st,status_chance=0.0,continuous=False,multishot=1.0,
                                  independent_proc_chances={k:1.0 for k in STATUS_POOL},
                                  impact_proc_conversions={},crit_proc_chances={})
                    encumber_views[key]=(st,probe)
                _,_,extra_rows,extra_non=packet(encumber_views[key][1],aim)
                extra_rows={k:{**r,'seedPerSecondPerProc':r['seedPerSecondPerProc']*merged_seed} for k,r in extra_rows.items()}
                extra_non={k:{**r,'perProc':r['perProc']*merged_seed} for k,r in extra_non.items()}
                add_procs(st,aim,t,({},dict.fromkeys(STATUS_POOL,weight/len(STATUS_POOL)),extra_rows,extra_non),False)
        if gen != generation:
            return  # A derived status hit killed the original target.
        scale = max(st.proc_duration_multiplier, 0.0)
        # Stable ordering for grouped expected instances, independent of hash seed.
        proc_items = sorted(procs.items()) if empowered else procs.items()
        for dtype, n in proc_items:
            n *= max(status_rate_multiplier, 0.0)
            if n <= 0.0 or dtype == 'DT_FREEZE' and frozen_until > t:
                continue
            proc_counts[dtype]=proc_counts.get(dtype,0.0)+n
            signal("proc-" + dtype, t, n)
            signal("on-proc", t, n)
            if scale <= 0.0:
                if empowered_hit(st, dtype, n, t, allow_encumber):
                    return
                continue
            row = rows.get(dtype)
            duration = (
                row["durationSeconds"] if row else durations.get(dtype, 6.0) * scale
            )
            if duration <= 0.0:
                if empowered_hit(st, dtype, n, t, allow_encumber):
                    return
                continue
            absence=no_status_probability(st,dtype,forced_procs,aim=aim)**max(status_rate_multiplier,0.)
            # Explicit derived event packets can supply procs independently
            # of this weapon's natural distribution.
            if absence>=1. and n>0.:absence=1.-min(n,1.)
            if not allow_encumber:
                absence=max(absence,1.-min(n,1.))
            presence.setdefault(dtype,StatusPresence()).add(t+duration,absence)
            if dtype == "DT_FIRE" and row:
                heat_clock.add(t,1.-absence)
                if not heat["count"]:
                    heat.update(start=t, scale=scale, token=heat["token"] + 1)
                    push(t + 1.0, "heat", heat["token"], gen)
                heat["count"] += n
                heat["seed"] += n * row["seedPerSecondPerProc"]
                heat["acc"] = row["accumulatorPerSecondPerAttack"]
                heat["end"] = t + duration
            else:
                states.setdefault(dtype, deque()).append((t + duration, n))
                if dtype in caps and dtype != 'DT_GAS':
                    cap=4.0 if dtype=='DT_FREEZE' and pools[0]>0 else caps[dtype]
                    excess=sum(q[1] for q in states[dtype])-cap
                    while excess>1e-9 and states[dtype]:
                        end,number=states[dtype].popleft();remove=min(number,excess)
                        if number>remove:states[dtype].appendleft((end,number-remove))
                        excess-=remove
                if dtype=='DT_FREEZE' and count(dtype)>=10-1e-9 and pools[0]<=0:
                    frozen_until=t+3*scale;frozen_scale=scale
                if row:
                    immediate = dtype in ("DT_GAS", "DT_ELECTRICITY")
                    ticks = (
                        range(0, max(1, int(math.ceil(duration - 1e-9))))
                        if immediate
                        else range(1, int(math.floor(duration + 1e-9)) + 1)
                    )
                    per = row["seedPerSecondPerProc"]
                    if not row["accumulatorSharedGroup"]:
                        per += row["coefficient"]
                    instance = {
                        "dtype": dtype,
                        "per": per,
                        "count": n,
                        "end": t + duration,
                        "weakpointChance": aim if dtype in {'DT_ELECTRICITY','DT_GAS'} else 0.,
                    }
                    if dtype == "DT_GAS":
                        states[dtype].pop()
                        gas_procs.append(instance)
                        excess = sum(p["count"] for p in gas_procs) - 10.0
                        for p in gas_procs:
                            if excess <= 0:
                                break
                            removed = min(p["count"], excess)
                            p["count"] -= removed
                            excess -= removed
                    for j in ticks:
                        push(t + j, "independent-dot", instance, gen)
                elif dtype in non:
                    states[dtype].pop()
                    instance = {
                        "count": n,
                        "per": non[dtype]["perProc"],
                        "end": t + 1.5 * scale,
                    }
                    blast_procs.append(instance)
                    push(instance["end"], "blast", instance, gen)
                    if sum(p["count"] for p in blast_procs) >= 10.0:
                        push(t, "blast-all", None, gen)

            if empowered_hit(st, dtype, n, t, allow_encumber):
                return

        # The derived Cold application is not elemental damage or a status-
        # chance modifier. The ordinary status path owns duration, Overguard's
        # four-stack limit and the freeze cycle. It cannot trigger itself.
        if cryogenic:
            extra_cold = max(procs.get('DT_PUNCTURE', 0.0), 0.0) * cryogenic['coldStacks'] * cryogenic.get('uptime', 1.0)
            if extra_cold > 0:
                before = proc_counts.get('DT_FREEZE', 0.0)
                add_procs(st, aim, t, ({}, {'DT_FREEZE':extra_cold}, {}, {}), False)
                cryogenic_expected += proc_counts.get('DT_FREEZE', 0.0) - before

    if combat:
        ammo = model(0.0)[0].magazine
    push(0.0, "fire")
    state=combat.get('projectileState') or {}
    for key,kind in [('selfShieldBreak','on-shield-broken'),('selfOverguardBreak','on-overguard-broken'),('selfShieldHit','on-shield-hit'),('equipFromPrimary','on-equip-from-primary'),('abilityUse','on-warframe-ability')]:
        if key+'At' in state:
            first=state[key+'At']
            interval=state.get(key+'Interval',0.)
            total=int(max(0.,window-first)/interval)+1 if interval>0 else 1
            for i in range(min(total,10000)):
                push(first+i*interval,'actor-event',kind)
    energy_rate = float(combat.get('energySpendPerSecond') or 0.)
    for q in sources:
        if q.get('energyThreshold') and energy_rate>0:
            interval = q['energyThreshold']/energy_rate
            for n in range(1,int(window/interval)+1):
                push(n*interval,'energy-spent',q)
    if collect_timeline:
        for i in range(1, int(math.ceil(window / step)) + 1):
            push(min(i * step, window), "sample")
    sample_time = 0.0
    last_kills = 0
    max_per_step = 0
    while heap:
        t, _, kind, payload, event_gen = heapq.heappop(heap)
        current_time=t
        clean(t)
        if event_gen is not None and event_gen != gen:
            continue
        if kind in {'stackable-life','stackable-child'}:
            projectiles.event(t,payload,child=kind=='stackable-child')
        elif kind == 'energy-spent':
            q = payload
            q['stacks'] = min(q['maxStacks'],q['stacks']+q['perEvent'])
            q['expires'] = t+q['duration'] if q['duration'] else math.inf
        elif kind == "heat":
            if heat["count"] and payload == heat["token"] and t <= heat["end"] + 1e-9:
                token = heat["token"]
                generation = gen
                take({"DT_FIRE": heat["seed"] + heat["acc"]}, t, "dot")
                if gen == generation:
                    push(t + 1.0, "heat", token, gen)
        elif kind in ("blast", "blast-all"):
            affected = list(blast_procs) if kind == "blast-all" else [payload]
            value = sum(p["count"] * p["per"] for p in affected)
            for p in affected:
                p["count"] = 0.0
            while blast_procs and not blast_procs[0]["count"]:
                blast_procs.popleft()
            if value:
                take({"DT_EXPLOSION": value}, t, "nonDot")
                # Only natural expiration is an Enervate hit; the 10-stack
                # detonation is not. Counts remain the replay's expected procs.
                if enervate and kind == 'blast':enervate.advance(t)
        elif kind == "independent-dot":
            if payload["count"] > 0 and t <= payload["end"] + 1e-9:
                dtype = payload["dtype"]
                take(
                    {
                        "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype: payload[
                            "count"
                        ]
                        * payload["per"]
                    },
                    t,
                    "dot",
                    payload.get('weakpointChance',0.),
                )
        elif kind == 'delayed-radial':
            part = payload
            delayed_attack_count += 1
            radial_packet = packet(part, 0.0)
            if not take(radial_packet[0], t, 'direct'):
                add_procs(part, 0.0, t, radial_packet)
            noncrit_no_proc_hit(part, 0.0, t)
        elif kind == 'delayed-attack':
            part, aim = payload
            delayed_attack_count += 1
            direct_packet = packet(part, aim)
            if not take({k:v*damage_rate_multiplier for k,v in direct_packet[0].items()}, t, 'direct', not part.radial_only):
                add_procs(part, aim, t, direct_packet)
            enervate_hit(part, t, 0. if part.radial_only else live_crit()[0], aim)
            signal('on-hit', t, part.multishot)
            signal('on-headshot', t, aim*part.multishot)
            signal('on-crit', t, min(part.crit_chance,1.)*part.multishot)
            noncrit_no_proc_hit(part, aim, t)
        elif kind == 'manual-detonation':
            detonation_count += 1
            before = totals['direct']
            mines = sum(part.multishot for part, _ in payload)
            waiting_mines = max(0., waiting_mines-mines)
            discarded = 0.0
            for part, generation in payload:
                if generation != gen:
                    stale += 1
                    discarded += part.multishot
                    continue
                radial_packet = packet(part, 0.)
                if not take(radial_packet[0], t, 'direct'):
                    add_procs(part, 0., t, radial_packet)
                enervate_hit(part, t, 0., 0.)
                signal('on-hit', t, part.multishot)
                signal('on-crit', t, min(part.crit_chance, 1.) * part.multishot)
            if collect_timeline:
                detonation_events.append(dict(time=t, expectedMines=mines,
                                              staleMines=discarded, damage=totals['direct']-before))
        elif kind == 'lingering':
            part = payload
            vec, _, _, _ = attack_data(part, 0.0)
            if not take(vec, t, 'direct'):
                add_procs(part, 0.0, t)
        elif kind == "dot":
            dtype, value, end = payload
            if t <= end + 1e-9:
                take(
                    {"DT_CINEMATIC" if dtype == "DT_SLASH" else dtype: value}, t, "dot"
                )
        elif kind == "syndicate":
            if (
                not syndrome
                or t < syndicate_ready
                or affinity < syndrome["affinityToFill"]
            ):
                continue
            affinity = 0.0
            syndicate_ready = t + 30.0
            before = totals["syndicate"]
            died = take({syndrome["damageType"]: 1000.0}, t, "syndicate")
            syndicate_events.append(
                {
                    "time": t,
                    "id": syndrome["id"],
                    "damage": totals["syndicate"] - before,
                }
            )
            if not died and syndrome["id"] != "justice":
                dtype = syndrome["damageType"]
                duration = (
                    8.0
                    if dtype == "DT_CORROSIVE"
                    else (12.0 if dtype == "DT_RADIATION" else 6.0)
                )
                states.setdefault(dtype, deque()).append((t + duration, 1.0))
                presence.setdefault(dtype,StatusPresence()).add(t+duration,0.)
                if dtype in ("DT_GAS", "DT_POISON"):
                    for j in (range(6) if dtype == "DT_GAS" else range(1, 7)):
                        push(t + j, "dot", (dtype, 500.5, t + 6.0), gen)
        elif kind=='actor-event':
            combat['_actorSignal']=True
            signal(payload,t)
            combat['_actorSignal']=False
        elif kind == "transform":
            if tap:
                tap.swap(t)
            form = payload
            if onos:
                onos_ticks,onos_hits,onos_start = 0,0.,t
            signal('on-transform', t)
            transforms += 1
            first_round = True
            burst_round = 0
            active, _ = model(t)
            if shell_reload and shell_reload.get('modeSwitchLoadsShell'):
                loaded = min(1., mode_switch_shells_owed) if form == 'incarnon' else mode_switch_shells_owed
                if loaded > 0:
                    signal('on-shell-reloaded', t, loaded)
                    reload_shell_events.append(dict(time=t, rounds=loaded, source='mode-switch', form=form))
                    mode_switch_shells_owed -= loaded
            ammo = cycle["pool"] if form == "incarnon" else active.magazine
            if form == "base":
                gauge = 0.0
            push(t, "fire")
        elif kind == 'reload-shell':
            amount, limit = payload
            ammo = min(limit, ammo + amount)
            signal('on-shell-reloaded', t, amount)
            reload_shell_events.append(dict(time=t, rounds=amount, source='reload', form=form))
        elif kind == "reload-complete":
            if field_duration and payload:
                field_duration_ready = True
            old_magazine=model(t)[0].magazine
            signal("on-reload-complete", t)
            if payload:
                signal("on-reload-empty-complete", t)
            if combat.get('refillMagazineGrowth'):
                grown=model(t)[0].magazine
                ammo=min(grown,ammo+max(0.,grown-old_magazine))
            push(t, "fire")
        elif kind == "fire":
            if t >= window - 1e-9 or rate <= 0.0:
                continue
            active, radial = model(t)
            # The gate is read before paying this shot's ammo. Incarnon charge
            # pools and zero-cost abstract events never use magazine semantics.
            magazine_form = form == 'base' or (not cycle and not combat.get('selectedIncarnon'))
            last_round = bool(combat and magazine_form and active.magazine > 0 and ammo > 0
                              and ammo <= max(active.ammo_cost, 1.0) + 1e-9)
            combat['lastRound'] = last_round
            active, radial = model(t)
            speed = active.fire_rate if combat else rate
            if speed <= 0.0:
                continue
            if manual_detonation:
                # A player detonates the existing batch before another throw
                # could exceed the native eight-projectile deployment limit.
                pending_mines = [(part, g) for part, g in pending_mines if g == gen]
                if not pending_mines:
                    pending_throws = 0
                if pending_mines and sum(part.multishot for part, _ in pending_mines) + active.multishot > manual_detonation['maxProjectiles'] + 1e-9:
                    queue_mines(t)
                    push(t + max(manual_detonation['delaySeconds'], 1./speed), 'fire')
                    continue
            if cycle and form == "base" and gauge >= cycle["hits"] - 1e-9:
                if shell_reload:
                    mode_switch_shells_owed = max(0., math.ceil(active.magazine - max(ammo, 0.) - 1e-9))
                push(t + cycle["enterSeconds"], "transform", "incarnon")
                continue
            battery = combat.get('battery')
            if battery and math.isfinite(last_fire_time):
                delay = battery['delayEmptySeconds'] if ammo <= 1e-9 else battery['delayPartialSeconds']
                ammo = min(active.magazine, ammo + max(0, t - last_fire_time - delay) * battery['regenPerSecond'])
            insufficient_ammo = getattr(active, '_requires_full_ammo', False) and ammo + 1e-9 < max(active.ammo_cost, 0.0)
            if (ammo <= 1e-9 or insufficient_ammo) and active.magazine > 0.0 and combat:
                if cycle and form == "incarnon":
                    push(t + cycle["exitSeconds"], "transform", "base")
                else:
                    if battery:
                        recharges += 1
                        ammo = active.magazine
                        push(t + active.reload_time, 'fire')
                        continue
                    reloads += 1
                    first_round = True
                    burst_round = 0
                    # Fractional ammo overdraw remains owed; a partial reload
                    # fills to capacity and cannot bank its remaining rounds.
                    was_empty = ammo <= 1e-9
                    before_reload_ammo = ammo
                    # Fixed Incarnon pools do not run the base shell-loading loop.
                    if not (shell_reload and magazine_form):
                        ammo = active.magazine + min(ammo, 0.0)
                    if was_empty:
                        signal("on-reload-empty", t)
                    signal("on-reload", t)
                    for q in sources:
                        if q.get("kind") == "on-burst-hit":
                            q["stacks"] = 0.0
                    active, _ = model(t)
                    reload_time = active.reload_time
                    if shell_reload and magazine_form:
                        target_ammo = active.magazine + min(before_reload_ammo, 0.)
                        missing = max(0., target_ammo - before_reload_ammo)
                        total_rounds = int(math.ceil(missing - 1e-9))
                        raw_full_time = shell_reload['start'] + shell_reload['perShell'] * active.magazine + shell_reload['end']
                        speed_scale = reload_time / raw_full_time if raw_full_time > 0 else 1.
                        # Load each round at its native loop boundary. The end
                        # animation still blocks firing after the last round.
                        for i in range(total_rounds):
                            amount = min(1., max(0., missing-i))
                            push(t + (shell_reload['start'] + shell_reload['perShell'] * (i+1)) * speed_scale,
                                 'reload-shell', (amount, target_ammo))
                        reload_time = (shell_reload['start'] + shell_reload['perShell'] * total_rounds + shell_reload['end']) * speed_scale
                    for q in sources:
                        if (
                            q.get("kind") in ("on-reload-empty", "on-reload")
                            and not q["duration"]
                        ):
                            q["stacks"] = (
                                q["initialStacks"] if q["perEvent"] == 0 else 0.0
                            )
                    if combat.get('spool') and reload_time >= combat['spool']['spindown']:
                        spool_shots=0
                    push(t + reload_time, "reload-complete", was_empty)
                continue
            spool=combat.get('spool')
            if spool:
                # Holding the trigger through a slow cadence is not idle.
                # Only the separately scheduled reload can reset the spool.
                pellets=min(spool['maximum'],spool['initial']+spool_shots)
                speed*=spool['rateStart']+(1-spool['rateStart'])*min(spool_shots/spool['rateShots'],1.)
                active=replace(active,multishot=active.multishot*pellets/spool['maximum'],
                               status_chance=active.status_chance*spool['maximum']/pellets,
                               ammo_cost=active.ammo_cost*math.ceil(pellets/spool['ammoDivisor'])/math.ceil(spool['maximum']/spool['ammoDivisor']))
                if collect_timeline:spool_trace.append(dict(time=t,pellets=pellets,fireRate=speed,ammoCost=active.ammo_cost))
                spool_shots+=1
            attacks += 1
            shot_in_progress = True
            if tap:
                incarnon_form=form=='incarnon' or combat.get('selectedIncarnon')
                tap_hits=active.multishot*(2. if incarnon_form and radial else 1.)
                factor=tap.shot(t,tap_hits)
                if not incarnon_form:
                    active=replace(active,damage_types={k:v*factor for k,v in active.damage_types.items()},
                                   dot_base_damage=active.dot_base_damage*factor if active.dot_base_damage is not None else None)
                if radial:
                    radial=replace(radial,damage_types={k:v*factor for k,v in radial.damage_types.items()},
                                   dot_base_damage=radial.dot_base_damage*factor if radial.dot_base_damage is not None else None)
                if collect_timeline:
                    tap_events.append(dict(time=t,hits=tap.hits,multiplier=factor,form=form,radialOnly=bool(incarnon_form)))
            last_fire_time = t
            generation = gen
            if (
                combat.get("lastBurst")
                and form == "base"
                and ammo <= 3
                and not combat.get("multishotLocked")
            ):
                active = replace(active, multishot=active.multishot * 6.0)
            if first_round and active.first_shot_damage_bonus:
                active = copy(active)
                factor = 1.0 + active.first_shot_damage_bonus
                active.damage_types = {k: v * factor for k,v in active.damage_types.items()}
                if active.dot_base_damage is not None:
                    active.dot_base_damage *= factor
            first_round = False
            if (active.ammo_pool_multishot_cost and (form=='incarnon' or combat.get('selectedIncarnon'))
                    and ammo<1.+active.ammo_pool_multishot_cost):
                afforded = max(ammo-1.,0.)
                normal = 1.+active.ammo_pool_multishot_cost
                factor = 1.+active.ammo_pool_damage_bonus
                previous = 1.+active.ammo_pool_multishot_cost*factor
                reduced = 1.+afforded*factor
                if active.continuous:
                    active = replace(active,multishot=reduced,ammo_pool_multishot_cost=afforded)
                else:
                    adjustment = (reduced/(1.+afforded))/(previous/normal)
                    active = replace(active,multishot=1.+afforded,ammo_pool_multishot_cost=afforded,
                                     damage_types={k:v*adjustment for k,v in active.damage_types.items()},
                                     dot_base_damage=active.dot_base_damage*adjustment if active.dot_base_damage is not None else None)
            field_duration_boost = field_duration_ready
            field_duration_ready = False  # A shot consumes it, even when that shot kills.
            hit_count = (1.0 if active.continuous else max(active.multishot,0.0))
            combat['victimProcTypesBeforeHit'] = {dtype:p.probability(t) for dtype,p in presence.items()}
            shot_puncture=0.0 if active.radial_only else live_crit()[0]
            aim = 0.0 if active.radial_only else head
            primary_delay = getattr(active, '_primary_delay_seconds', 0.)
            stackable = getattr(active,'_stackable',None)
            projectile_wait = 0.
            if stackable:
                if projectiles is None:
                    from .stackable_projectiles import StackableProjectiles
                    projectiles = StackableProjectiles(combat.get('projectileState') or {},push,deliver_projectile,projectile_events)
                projectile_wait = projectiles.deploy(t,active,generation)
                died = gen!=generation
            elif manual_detonation:
                if active.multishot > manual_detonation['maxProjectiles']:
                    unsupported.append('talons-single-throw-deployment-overflow-unmodeled')
                    active = replace(active, multishot=float(manual_detonation['maxProjectiles']))
                pending_mines.append((copy(active), generation))
                pending_throws += 1
                died = False
            elif primary_delay:
                push(t + primary_delay, 'delayed-attack', (copy(active), aim), generation)
                died = False
            else:
                direct_packet = packet(active, aim)
                vector, _, _, _ = direct_packet
                ramp = beam_ramp.tick(t,1./speed,(combat.get('beamRampFloors') or {}).get(
                    'base' if form=='base' else 'selected',.2)) if active.continuous and combat.get('beamRampFloors') else 1.
                died = take(
                {k: v * damage_rate_multiplier * ramp for k, v in vector.items()},
                t,
                "direct",
                not active.radial_only,
                )
                noncrit_no_proc_hit(active, aim, t)
            if not died and not manual_detonation and not primary_delay and not stackable:
                add_procs(active, aim, t, direct_packet)
                field = getattr(active, '_lingering', None)
                if field and gen == generation:
                    part, tick_rate, duration = field
                    boosted = bool(field_duration_boost and magazine_form)
                    if boosted:
                        duration *= field_duration['multiplier']
                        field_duration_used += 1
                    if field_duration and collect_timeline:
                        field_events.append(dict(time=t,form=form,durationSeconds=duration,
                                                 multiplier=field_duration['multiplier'] if boosted else 1.))
                    for tick in range(int(math.ceil(duration * tick_rate - 1e-9))):
                        push(t + tick / tick_rate, 'lingering', part, gen)
            radial_parts = (radial, *getattr(radial, '_additional_radials', ())) if radial and not stackable else ()
            for part in radial_parts:
                if gen != generation:
                    stale += 1
                    continue
                delay = max(0.0, getattr(part, '_impact_delay', 0.0))
                if delay:
                    push(t + delay, 'delayed-radial', part, generation)
                else:
                    radial_packet = packet(part, 0.0)
                    if not take(radial_packet[0], t, "direct"):
                        add_procs(part, 0.0, t, radial_packet)
                    noncrit_no_proc_hit(part, 0.0, t)
            if hit_count > 0 and (form == "base" or combat.get("baseMode")) and combat.get('baseBurst') and burst_round==int(combat['baseBurst']['count'])-1:
                signal("on-burst-hit", t)
            if (form=='base' or combat.get('baseMode')) and combat.get('baseBurst'):
                burst_head_probability*=1.-(1.-aim)**hit_count
                if burst_round==int(combat['baseBurst']['count'])-1:
                    signal('on-burst-headshot',t,burst_head_probability)
                    burst_head_probability=1.
            if not manual_detonation and not primary_delay and not stackable:
                enervate_hit(active,t,shot_puncture,aim)
            signal('on-fire', t)
            through=(combat.get('projectileState') or {}).get('punchthroughTargets',0)
            if through:
                signal('on-punchthrough',t,through)
                if form=='base' or not combat.get('selectedIncarnon'):
                    signal('on-onos-damage-condition',t)
                if through>=2:
                    signal('on-three-enemy-punchthrough',t)
            if onos and (form=='incarnon' or combat.get('selectedIncarnon')) and onos_ticks>=onos['alignmentShots']:
                onos_condition_hits+=hit_count
                completed=math.floor(onos_condition_hits/2.)
                onos_condition_hits-=completed*2.
                if completed:
                    signal('on-onos-damage-condition',t,completed)
            if not manual_detonation and not primary_delay and not stackable:
                signal("on-hit", t, hit_count)
                if aim<1.:
                    signal('on-body-hit',t,(1.-aim)*hit_count)
                signal("on-headshot", t, aim * hit_count)
                consecutive_heads(t,aim)
                signal(
                "on-crit",
                t,
                min(
                    (1.-aim)*min(max(active.crit_chance*active.bodyshot_crit_multiplier,0.),1.)+aim*min(max(active.crit_chance
                    + (
                        active.weakpoint_crit_chance_bonus
                        + active.base_crit_chance
                        * active.weakpoint_crit_chance_relative
                    ),0.),1.),
                    1.0,
                )
                * hit_count,
                )
            if cycle and form == "base" and not active.radial_only:
                gauge = min(cycle["hits"], gauge + (1.0 if cycle.get('chargeOn') == 'direct_hits' else head)
                            * active.multishot * active.incarnon_charge_multiplier)
            if combat:
                ammo -= (
                    getattr(active,'_charge_pool_cost',1.) + active.ammo_pool_multishot_cost
                    if form == "incarnon" or combat.get("selectedIncarnon")
                    else (1.0 if hasattr(active, '_bow_draw') and active.ammo_cost == 0 else max(active.ammo_cost, 0.0))
                )
                restore=combat.get('magazineRestore')
                if restore and restore['kind'] in {'on-headshot','on-hit'} and magazine_form:
                    eligible=not restore.get('victimProcType') or combat.get('victimProcTypesBeforeHit',{}).get(restore['victimProcType'])
                    if eligible:
                        probability=1.-(1.-aim)**hit_count if restore['kind']=='on-headshot' else 1.
                        events=1. if restore.get('oncePerShot') else hit_count
                        restored=(max(0.,active.magazine-ammo)*restore.get('fraction',0.)+restore.get('amount',0.)*events)*probability*restore.get('chance',1.)*float(eligible)
                        ammo=min(active.magazine,ammo+restored)
                if pending_magazine_restore:
                    ammo+=max(0.,active.magazine-ammo)*pending_magazine_restore
                    pending_magazine_restore=0.
                shot_in_progress=False
            burst = (
                combat.get("baseBurst")
                if (form == "base" or combat.get("baseMode"))
                else None
            )
            delay = getattr(active, '_bow_draw', 1.0 / speed + getattr(active, '_charge_time', 0.0))
            if onos and form!='base':
                power = onos_ticks>=onos['alignmentShots']
                if collect_timeline:
                    onos_events.append(dict(time=t,kind='power' if power else 'beam',critStacks=onos_hits,
                                            ammoCost=getattr(active,'_charge_pool_cost',1.),critChance=active.crit_chance))
                if power:
                    onos_ticks,onos_hits = 0,0.
                    delay = onos['postFireSeconds']
                    onos_start = t+delay
                else:
                    onos_ticks += 1
                    if combat.get('onosCrits'):
                        onos_hits = min(50.,onos_hits+hit_count)
            delay += projectile_wait
            if delay == 0 and ammo > 0:
                delay = active.reload_time or 1.0 / speed
            if burst:
                burst_round += 1
                if burst_round < int(burst["count"]) and ammo > 0:
                    delay = float(burst["delay_seconds"]) / max(
                        1.0, speed / float(combat["baseFireRate"])
                    )
                else:
                    burst_round = 0
            if manual_detonation and (pending_throws >= manual_detonation['batchSize'] or ammo <= 1e-9):
                queue_mines(t)
                delay = max(delay, manual_detonation['delaySeconds'])
            push(t + delay, "fire")
        elif kind == "sample":
            dt = t - sample_time
            sample_time = t
            max_per_step = max(max_per_step, kills - last_kills)
            last_kills = kills
            stacks = {name: round(count(dtype), 3) for dtype, name in names.items()}
            for k, v in stacks.items():
                averaged[k] += v * dt
            point = {
                "time": round(t, 6),
                "pool": (
                    "overguard"
                    if pools[0] > 0
                    else ("shield" if pools[1] > 0 else "health")
                ),
                "overguard": pools[0],
                "shield": pools[1],
                "health": pools[2],
                "stacks": stacks,
                "armour": armour(t),
                "heatArmourStrip": heat_strip(t),
                'punctureArmourStrip':puncture_strip,
                "heatSeedPerTick": heat['seed'],
                "punctureCritChance": live_crit()[0],
                "coldCritDamage": live_crit()[1],
                "frozen": frozen_until>t,
                "totalArmourStrip": 1 - armour(t) / armour_base if armour_base else 0.0,
                "generation": gen,
                "form": form,
                "ammo": ammo,
                "gauge": gauge,
                "fieldDurationReady": field_duration_ready,
                "shots": attacks,
                "directDps": (
                    (totals["direct"] + totals["arcane"] - last_totals["direct"] - last_totals["arcane"]) / dt if dt else 0.0
                ),
                "dotDps": (totals["dot"] - last_totals["dot"]) / dt if dt else 0.0,
                "stepDamage": sum(totals.values()) - sum(last_totals.values()),
                "syndicatePoints": affinity,
                "triggerStacks": {q["id"]: q["stacks"] for q in sources},
            }
            if enervate:
                point['enervate']=enervate.snapshot()
                point['triggerStacks'][enervate.config['id']]=point['enervate']['stacks']
                enervate.sample()
            if manual_detonation:
                point['deployedMines'] = sum(part.multishot for part, _ in pending_mines) + waiting_mines
            timeline.append(point)
            last_totals = totals.copy()
            for q in sources:
                q["series"].append(q["stacks"])
    score = kills + (1 - sum(pools) / ehp if ehp else 0.0)
    random_damage=(any(abs(v-round(v))>1e-9 for v in (stats.crit_chance,stats.multishot,stats.status_chance))
                   or stats.status_chance>0 and sum(v>0 for v in stats.damage_types.values())>1)
    if (random_damage and head==1. and kills>=3 and weak_kill_events==0. and totals['direct']>0 and totals['dot']>0
            and any(q['kind']=='on-headshot-kill' and q['perEvent']>0 for q in sources)):
        unsupported.append('weakpoint-kill-feedback-unmodeled-variance')
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
    return {
        "model": "event-expected-v3",
        "eventModel": "target-generation-events-v3",
        "windowSeconds": window,
        "timeStep": step,
        "attacksPerSecond": attacks / window if window else 0.0,
        "statusEventsPerSecond": rate * status_rate_multiplier,
        "timeline": timeline,
        "averagedStacks": {
            k: v / window if window else 0.0 for k, v in averaged.items()
        },
        "steadyStacks": timeline[-1]["stacks"] if timeline else {},
        "killsPerMinute": score * 60 / window if window else 0.0,
        "killsInWindow": score,
        "killEvents": kills,
        "weakpointKillEvents": weak_kill_events,
        "targetGeneration": gen,
        "targetTotalEhp": ehp,
        "directWindow": totals["direct"],
        "dotWindow": totals["dot"],
        "arcaneWindow": totals["arcane"],
        "dotByType": dot_by_type,
        "procCounts": proc_counts,
        "nonDotWindow": totals["nonDot"],
        "syndicateWindow": totals["syndicate"],
        "syndicateEvents": syndicate_events,
        "totalWindowDamage": sum(totals.values()),
        "windowDps": sum(totals.values()) / window if window else 0.0,
        "firstKillTime": first_kill,
        "minKillInterval": min_interval,
        "maxKillsPerStep": max_per_step,
        "staleComponents": stale,
        'fieldDuration': ({**field_duration, 'boostedShots':field_duration_used,
                           'ready':field_duration_ready, 'events':field_events} if field_duration else None),
        'manualDetonation': ({**manual_detonation, 'detonations':detonation_count,
                              'pendingMines':sum(part.multishot for part, _ in pending_mines)+waiting_mines,
                              'events':detonation_events} if manual_detonation else None),
        'delayedAttackEvents': delayed_attack_count,
        'projectileEvents': projectile_events or [],
        'projectileLifecycle': projectiles.stats if projectiles else {},
        'onosSequence': {'events':onos_events,'alignmentShots':onos['alignmentShots'],'powerCost':onos['powerCost']} if onos else None,
        'doubleTap':{'events':tap_events,'maximum':tap.maximum,'duration':tap.duration} if tap else None,
        "shots": attacks,
        "reloads": reloads,
        'reloadShellEvents': reload_shell_events,
        "recharges": recharges,
        'spoolTrace':spool_trace,
        "transforms": transforms,
        "directEventLedger": ledger,
        "emergent": {"onKillStacks": "events" if sources else "panel-assumed-max"},
        "enervate": enervate.summary() if enervate else None,
        "magneticBreaks": magnetic_breaks,
        'fortifier': ({'multiplier':fortifier['multiplier'],'overguardDamage':fortifier_damage,
                       'stolenTotal':fortifier_stolen,'selfOverguard':self_overguard,
                       'cap':fortifier['cap'],'selfDamageModeled':False} if fortifier else None),
        'encumber': ({'chance':encumber['chance'],'expectedExtraProcs':encumber_expected,
                      'events':encumber_events,'typeCount':13,'coPresence':'per-application-occurrence'} if encumber else None),
        'empowered': ({'damagePerStatus':empowered['damage'], 'expectedInstances':empowered_count,
                       'windowDamage':totals['arcane'], 'damageByType':empowered_by_type,
                       'sourcePolicy':'weapon-status-only-no-script-link-dot-recursion'} if empowered else None),
        'cryogenic': ({'coldStacksPerPuncture':cryogenic['coldStacks'],
                       'radiusMeters':cryogenic['radius'],
                       'expectedColdApplications':cryogenic_expected,
                       'neighborTargetsModeled':False} if cryogenic else None),
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
        "limitations": [
            "expected-proc-counts-not-Monte-Carlo",
            "single-target",
            "non-heat-stacking-procs-expected",
            "fractional-proc-refresh-approximates-uptime",
            "single-target-syndicate-no-player-buffs",
            "magnetic-break-six-ticks-pinned-reference-contract",
            'spread-hit-loss-not-modeled',
        ] + (['spool-linear-rate-from-raw-max-shots','spool-idle-threshold-reset-no-partial-decay'] if combat.get('spool') else [])
          + (['talons-expected-projectile-capacity','manual-detonation-explicit-player-cadence'] if manual_detonation else [])
          + (['onos-native-alignment-shots-held-rate-and-postfire-cadence','onos-radial-target-coverage-explicit'] if onos else [])
          + (ASSUMPTIONS if enervate else [])
          + (['encumber-poisson-status-presence','encumber-single-target-expected-procs'] if encumber else [])
          + (['cryogenic-single-target-expected-procs-no-neighbor-burst'] if cryogenic else [])
          + (['empowered-grouped-expected-instances','empowered-derived-script-procs-excluded'] if empowered else [])
          + (['fortifier-raw-multiply-r5-x8-reference-x9-conflict','fortifier-player-overguard-no-incoming-damage'] if fortifier else []),
    }
