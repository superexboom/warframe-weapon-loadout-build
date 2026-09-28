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
        spread_hit_probability,
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
    old_heat_strip = (0.0, -1.0, 1.0)
    frozen_until = -1.0
    frozen_scale = 1.0
    heap = []
    seq = 0
    gen = 0
    kills = 0
    attacks = 0
    initial_spread = None
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
    reloads = 0
    recharges = 0
    last_fire_time = -math.inf
    spool_shots = 0
    spool_trace = []
    burst_round = 0
    field_duration = combat.get('fieldDurationOnEmptyReload')
    field_duration_ready = False
    field_duration_used = 0
    field_events = []
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
            n = min(4, int((t - heat["start"] + 1e-9) / max(0.5 * heat["scale"], 1e-9)))
            up=(0.0, 0.15, 0.30, 0.40, 0.50)[max(0, n)]
        value, ended, scale = old_heat_strip
        if ended < 0:
            return up
        n = int(max(0.0, t - ended) / max(1.5 * scale, 1e-9))
        descending = [v for v in (0.5, 0.4, 0.3, 0.15, 0.0) if v <= value + 1e-9]
        return max(up,descending[min(n, len(descending) - 1)])

    def clean(t):
        nonlocal old_heat_strip, frozen_until
        if frozen_until >= 0 and t >= frozen_until - 1e-9:
            states['DT_FREEZE']=deque([(frozen_until+6*frozen_scale,3.0)])
            frozen_until=-1.0
        while gas_procs and gas_procs[0]["end"] < t - 1e-9:
            gas_procs.popleft()
        for rows in states.values():
            while rows and rows[0][0] < t - 1e-9:
                rows.popleft()
        if heat["count"] and heat["end"] < t - 1e-9:
            old_heat_strip = (heat_strip(heat["end"]), heat["end"], heat["scale"])
            heat["count"] = heat["seed"] = 0.0
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
            armour_base * (1 - elemental_armour_strip) * (1 - cs) * (1 - heat_strip(t))
        )

    def vulnerability(n):
        return 1.0 + n if n < 1 else min(2.0 + 0.25 * (n - 1), 4.25)

    def signal(kind, t, weight=1.0):
        for q in sources:
            if kind in q.get('resetOn', ()) and q['perEvent'] != 0:
                q['stacks'] = 0.0
                q['expires'] = math.inf
                q['expiries'] = []
            if q.get("kind") != kind:
                continue
            delta = weight * q["perEvent"]
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

    def die(t, weak_kill=False, weapon_kill=True):
        nonlocal kills, gen, first_kill, last_kill, min_interval, affinity, old_heat_strip, frozen_until
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
        frozen_until=-1.0
        gas_procs.clear()
        blast_procs.clear()
        heat.update(count=0.0, seed=0.0, end=-1.0, token=heat["token"] + 1)
        old_heat_strip = (0.0, -1.0, 1.0)
        signal("on-kill", t)
        slot = str(combat.get("weaponSlot") or "").lower()
        if "longgun" in slot or slot in ("primary", "rifle"):
            signal("on-primary-kill", t)
        if "melee" in slot:
            signal("on-melee-kill", t)
        distance = combat.get("distance")
        if distance is not None and distance <= 5.0:
            signal("on-close-kill", t)
        if weak_kill:
            signal("on-headshot-kill", t, head)
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
        states.setdefault('DT_ELECTRICITY', deque()).append((t + 6, 1.0))
        proc_counts['DT_ELECTRICITY'] = proc_counts.get('DT_ELECTRICITY', 0) + 1
        for tick in range(6):
            push(t + tick, 'dot', ('DT_ELECTRICITY', per_tick, t + 6), gen)

    def take(vector, t, source, weak_kill=False):
        # Spend one attack fraction across pools. Shield bypass acts in parallel.
        # Residual damage never leaks to the next target.
        nonlocal fortifier_damage, fortifier_stolen, self_overguard
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
            (sum(-math.expm1(-count(k)) for k in set(states) | {'DT_FIRE'}) if encumber
             else sum(count(k) > 0 for k in states) + int(heat["count"] > 0))
            if combat.get("conditionOverload") or stats.co_bucket
            else 0
        )
        last_round = bool(combat.get('lastRound'))
        key = (form, tuple(q["stacks"] for q in sources), live_types, last_round)
        if key not in model_cache:
            resolver = combat.get("resolve")
            if resolver:
                try:
                    model_cache[key] = resolver(
                        form, {q["id"]: q["stacks"] for q in sources}, live_types, last_round
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
            rows[dtype] = {
                **r,
                "seedPerSecondPerProc": r["seedPerSecondPerProc"] * (1 - aim)
                + hr["seedPerSecondPerProc"] * aim,
            }
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
        hit_probability = spread_hit_probability(st, combat.get('distance'))
        if hit_probability < 1.0:
            vector = {k: v * hit_probability for k, v in vector.items()}
            procs = {k: v * hit_probability for k, v in procs.items()}
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
        puncture,cold=live_crit()
        if st.radial_only:puncture=0.0
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
                view.crit_multiplier=st.crit_multiplier+cold
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
            p=(1-aim)*big_crit_probability(cc,st.double_crit_chance)
            p+=aim*big_crit_probability(cc+weak,st.double_crit_chance)
            landing = spread_hit_probability(st, combat.get('distance'))
            probabilities[stacks]=any_probability(p * landing,1.0 if st.continuous else st.multishot)
        gain=not (combat['enervate'].get('ignoreSelected') and form != 'base')
        enervate.advance(t,probabilities,gain=gain)

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
        nonlocal frozen_until,frozen_scale,encumber_time,encumber_remaining,encumber_expected,cryogenic_expected
        generation = gen
        _, procs, rows, non = data if data is not None else packet(st, aim)
        if encumber and allow_encumber and status_rate_multiplier > 0:
            from .status_arcanes import STATUS_POOL, encumber_roll
            if abs(t - encumber_time) > 1e-9:
                encumber_time=t;encumber_remaining=1.0
            landing = spread_hit_probability(st, combat.get('distance'))
            probability, merged_seed=encumber_roll(st, encumber['chance'], forced_procs, hit_probability=landing)
            weight=encumber_remaining*probability*encumber.get('uptime',1.0)
            encumber_remaining*=1-probability*encumber.get('uptime',1.0)
            if weight > 0:
                encumber_expected+=weight
                if collect_timeline:encumber_events.append(dict(time=t,expected=weight))
                key=(id(st),aim)
                if key not in encumber_views:
                    probe=replace(st,status_chance=0.0,continuous=False,multishot=1.0,
                                  independent_proc_chances={k:1.0 for k in STATUS_POOL},
                                  impact_proc_conversions={})
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
            if dtype == "DT_FIRE" and row:
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
        if kind == "heat":
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
                )
        elif kind == 'delayed-radial':
            part = payload
            radial_packet = packet(part, 0.0)
            if not take(radial_packet[0], t, 'direct'):
                add_procs(part, 0.0, t, radial_packet)
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
                if dtype in ("DT_GAS", "DT_POISON"):
                    for j in (range(6) if dtype == "DT_GAS" else range(1, 7)):
                        push(t + j, "dot", (dtype, 500.5, t + 6.0), gen)
        elif kind == "transform":
            form = payload
            signal('on-transform', t)
            transforms += 1
            first_round = True
            burst_round = 0
            active, _ = model(t)
            ammo = cycle["pool"] if form == "incarnon" else active.magazine
            if form == "base":
                gauge = 0.0
            push(t, "fire")
        elif kind == "reload-complete":
            if field_duration:
                field_duration_ready = True
            signal("on-reload-complete", t)
            signal("on-reload-empty-complete", t)
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
            if cycle and form == "base" and gauge >= cycle["hits"] - 1e-9:
                push(t + cycle["enterSeconds"], "transform", "incarnon")
                continue
            battery = combat.get('battery')
            if battery and math.isfinite(last_fire_time):
                delay = battery['delayEmptySeconds'] if ammo <= 1e-9 else battery['delayPartialSeconds']
                ammo = min(active.magazine, ammo + max(0, t - last_fire_time - delay) * battery['regenPerSecond'])
            if ammo <= 1e-9 and active.magazine > 0.0 and combat:
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
                    # Fractional ammo overdraw remains owed after a reload.
                    ammo += active.magazine
                    signal("on-reload-empty", t)
                    signal("on-reload", t)
                    for q in sources:
                        if q.get("kind") == "on-burst-hit":
                            q["stacks"] = 0.0
                    active, _ = model(t)
                    reload_time = active.reload_time
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
                    push(t + reload_time, "reload-complete")
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
            field_duration_boost = field_duration_ready
            field_duration_ready = False  # A shot consumes it, even when that shot kills.
            landing = spread_hit_probability(active, combat.get('distance'))
            if initial_spread is None and active.spread_min_deg is not None:
                initial_spread = dict(
                    model='uniform-native-min-angle',geometry='pinned-reference-ray-circle',
                    centreDistanceM=combat.get('distance'),bodyRadiusM=.25,
                    initialMinDeg=active.spread_min_deg,initialMaxDeg=active.spread_max_deg,
                    initialHitProbability=landing)
            hit_count = (1.0 if active.continuous else active.multishot) * landing
            shot_puncture=0.0 if active.radial_only else live_crit()[0]
            aim = 0.0 if active.radial_only else head
            direct_packet = packet(active, aim)
            vector, _, _, _ = direct_packet
            died = take(
                {k: v * damage_rate_multiplier for k, v in vector.items()},
                t,
                "direct",
                not active.radial_only,
            )
            if not died:
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
            radial_parts = (radial, *getattr(radial, '_additional_radials', ())) if radial else ()
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
            if (form == "base" or combat.get("baseMode")) and burst_round == 2:
                signal("on-burst-hit", t)
            enervate_hit(active,t,shot_puncture,aim)
            signal('on-fire', t)
            signal("on-hit", t, hit_count)
            signal("on-headshot", t, aim * hit_count)
            signal(
                "on-crit",
                t,
                min(
                    active.crit_chance
                    + aim
                    * (
                        active.weakpoint_crit_chance_bonus
                        + active.base_crit_chance
                        * active.weakpoint_crit_chance_relative
                    ),
                    1.0,
                )
                * hit_count,
            )
            if cycle and form == "base" and not active.radial_only:
                gauge = min(cycle["hits"], gauge + (1.0 if cycle.get('chargeOn') == 'direct_hits' else head) * active.multishot * landing)
            if combat:
                ammo -= (
                    1.0
                    if form == "incarnon" or combat.get("selectedIncarnon")
                    else (1.0 if hasattr(active, '_bow_draw') and active.ammo_cost == 0 else max(active.ammo_cost, 0.0))
                )
            burst = (
                combat.get("baseBurst")
                if (form == "base" or combat.get("baseMode"))
                else None
            )
            delay = getattr(active, '_bow_draw', 1.0 / speed + getattr(active, '_charge_time', 0.0))
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
            timeline.append(point)
            last_totals = totals.copy()
            for q in sources:
                q["series"].append(q["stacks"])
    score = kills + (1 - sum(pools) / ehp if ehp else 0.0)
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
        'spread': initial_spread,
        'fieldDuration': ({**field_duration, 'boostedShots':field_duration_used,
                           'ready':field_duration_ready, 'events':field_events} if field_duration else None),
        "shots": attacks,
        "reloads": reloads,
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
                      'events':encumber_events,'typeCount':13,'coPresence':'poisson-occupancy'} if encumber else None),
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
        ] + list(combat.get('spatialLimitations') or []) + (['spool-linear-rate-from-raw-max-shots','spool-idle-threshold-reset-no-partial-decay'] if combat.get('spool') else [])
          + (ASSUMPTIONS if enervate else [])
          + (['encumber-poisson-status-presence','encumber-single-target-expected-procs'] if encumber else [])
          + (['cryogenic-single-target-expected-procs-no-neighbor-burst'] if cryogenic else [])
          + (['empowered-grouped-expected-instances','empowered-derived-script-procs-excluded'] if empowered else [])
          + (['fortifier-raw-multiply-r5-x8-reference-x9-conflict','fortifier-player-overguard-no-incoming-damage'] if fortifier else []),
    }
