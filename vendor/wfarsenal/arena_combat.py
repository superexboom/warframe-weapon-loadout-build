"""Incremental arena combat: one shooter and independent victim state.

World owns spatial admission. No single-target shooter replay is run per enemy.
Damage and conditional proc moments reuse damage/proc_probability kernels.
"""

from __future__ import annotations
import heapq
import math
from collections import deque
from copy import copy, deepcopy
from dataclasses import dataclass, field, replace
from typing import Any
from . import damage as dm
from .manual_combat import prepare, reference
from .sniper import ShotCombo
from .consecutive_hits import ConsecutiveHits
from .projectile_lanes import plan as plan_physical_lanes
from .proc_probability import (
    CappedPool,
    HeatChains,
    ProcPile,
    StatusPresence,
    no_status_probability,
    proc_pile_outcomes,
)
from .beam_ramp import BeamRamp
from .enervate import (
    EnervateState,
    big_crit_probability,
    any_probability,
    ASSUMPTIONS as ENERVATE_ASSUMPTIONS,
)
from .status_arcanes import STATUS_POOL, encumber_roll

EPS = 1e-9
DURATIONS = {
    "DT_VIRAL": 6.0,
    "DT_CORROSIVE": 8.0,
    "DT_MAGNETIC": 6.0,
    "DT_FREEZE": 6.0,
    "DT_PUNCTURE": 10.0,
}
CAPS = {"DT_VIRAL": 10, "DT_CORROSIVE": 10, "DT_MAGNETIC": 10, "DT_PUNCTURE": 5}


class UnsupportedArenaCombat(ValueError):
    pass


@dataclass
class ArenaTarget:
    id: Any
    record: dict
    level: int
    position: tuple
    defenses: dict
    pools: list
    full: list
    alive: bool = True
    protected: bool = False
    states: dict = field(default_factory=dict)
    pooled: dict = field(
        default_factory=lambda: {k: CappedPool(v) for k, v in CAPS.items()}
    )
    presence: dict = field(default_factory=dict)
    heat: HeatChains = field(default_factory=HeatChains)
    piles: dict = field(
        default_factory=lambda: {"DT_ELECTRICITY": ProcPile(), "DT_GAS": ProcPile(10)}
    )
    heat_acc: float = 0.0
    heat_token: int = 0
    heat_stats: Any = None
    heat_mode: str = "selected"
    frozen_until: float = -1.0
    frozen_scale: float = 1.0
    blasts: list = field(default_factory=list)
    puncture_strip: float = 0.0
    damage: float = 0.0
    death_time: float | None = None

    @property
    def health(self):
        return self.pools[2]

    @property
    def shield(self):
        return self.pools[1]

    @property
    def overguard(self):
        return self.pools[0]

    def __getitem__(self, name):
        return getattr(self, name)


@dataclass
class ArenaShot:
    id: int
    time: float
    form: str
    stats: Any
    radials: tuple
    stacks: dict
    head: bool
    ammo_cost: float
    interval: float
    beam_scale: float = 1.0
    finished: bool = False
    hits: list = field(default_factory=list)
    pending: list = field(default_factory=list)
    launched: bool = False
    impact_time: float | None = None
    impact_protected: frozenset = frozenset()
    restore_fraction: float = 0.0
    restore_amount: float = 0.0
    contact_targets: set = field(default_factory=set)
    burst_state: dict | None = None
    burst_token: int = 0
    field_duration_multiplier: float = 1.0
    enervate_weights: dict = field(default_factory=lambda: {0: 1.0})
    loaded_rounds: float = 1.0
    charge_seconds: float = 0.0
    external_part: bool = False
    refresh_policy: str = "snapshot"
    contact_factor: float | None = None
    sniper_factor: float | None = None
    physical_lanes: tuple = ()
    phase_after: int | None = None
    lane_index: int | None = None
    source_mode_index: int | None = None
    onos_phase: str | None = None
    victim_gate: dict = field(default_factory=dict)

    @property
    def components(self):
        return (self.stats, *self.radials)

    @property
    def fire_rate(self):
        return 1.0 / self.interval if self.interval else 0.0

    def __getitem__(self, name):
        return getattr(self, name)


class ArenaCombat:
    """Times are absolute seconds. Call finish_shot once after all contacts.

    nearby(id,radius,time) returns ids or ArenaTargets, without the origin.
    hit accepts 'direct', 'radial', an integer component index (0=direct),
    or the exact stats object in shot.components. Positions are world-owned.
    """

    def __init__(
        self,
        engine_context,
        mod_records=(),
        arcane_records=(),
        common_options=None,
        incarnon_choices=None,
        cycle_enabled=False,
    ):
        self.engine = engine_context
        self.options = dict(common_options or {})
        self.combat = prepare(
            engine_context,
            mod_records,
            arcane_records,
            incarnon_choices=incarnon_choices,
            cycle_enabled=cycle_enabled,
            assumed=bool(self.options.get("assumed", False)),
        )
        self.sources = []
        for src in self.combat.get("trigger_sources", ()):
            q = dict(src)
            q.update(
                stacks=float(q.get("initialStacks", 0)),
                expires=math.inf,
                expiries=[],
                progress=deque(),
            )
            if q.get("initialDuration") and q["stacks"]:
                q["expires"] = q["initialDuration"]
            for k, v in [
                ("maxStacks", 1.0),
                ("duration", 0.0),
                ("perEvent", 1.0),
                ("decay", "reset"),
            ]:
                q.setdefault(k, v)
            self.sources.append(q)
        self.targets = {}
        self.nearby = None
        self.protected_ids = None
        self.time = 0.0
        self._packet_cache = {}
        self._direct_cache = {}
        self._model_sources = {}
        self._queue = []
        self._serial = 0
        self._shot_id = 0
        self._active_shot = None
        self._events = []
        self._ready = 0.0
        self._reload = None
        self._transform = None
        self._burst_round = 0
        self._burst_state = None
        self.field_duration_ready = False
        self._last_fire = -math.inf
        self._battery_updated = 0.0
        self._force_reload = False
        self._charge_pending = None
        self._volley_rounds = 1.0
        self.physical_phase = int(
            (self.combat.get("physicalProjectileLanes") or {}).get("initialPhase", 0)
        )
        self.physical_trace = []
        self.onos_ticks = 0
        self.onos_hits = 0.0
        self.onos_start = 0.0
        self.onos_condition_hits = 0.0
        self._victim_gate = {}
        self._actor_signal = False
        self._source_events = []
        self._source_serial = 0
        self.cycle = self.combat.get("cycle")
        self.form = "base" if self.cycle else "selected"
        self.gauge = 0.0
        self.transforms = 0
        self.reloads = 0
        self.shots = 0
        self.kills = 0
        self.total_damage = 0.0
        self.direct_damage = 0.0
        self.dot_damage = 0.0
        self.base_ammo = None
        self.beam = BeamRamp()
        self.sniper_combo = (
            ShotCombo(self.combat["sniperCombo"])
            if self.combat.get("sniperCombo")
            else None
        )
        tap = self.combat.get("doubleTap")
        self.double_tap = (
            ConsecutiveHits(tap["perHit"], tap["maximum"], tap["duration"])
            if tap
            else None
        )
        self.spool_shots = 0
        self.rate_spool_shots = 0
        self.rate_spool_due = 0.0
        self.syndicate_affinity = 0.0
        self.syndicate_ready = 0.0
        self.syndicate_damage = 0.0
        self.syndicate_targets = (
            None  # callback(radius,time): ids around shooter, not dead victim
        )
        self._syndicate_pending = False
        self.enervate = (
            EnervateState(self.combat["enervate"])
            if self.combat.get("enervate")
            else None
        )
        self.arcane_damage = 0.0
        self.fortifier_damage = 0.0
        self.self_overguard = 0.0
        self.empowered_count = 0.0
        self.encumber_expected = 0.0
        self.cryogenic_expected = 0.0
        self._encumber_time = -math.inf
        self._encumber_remaining = 1.0
        self.diagnostics = list(dict.fromkeys(self.combat.get("unsupported") or ()))
        self.unsupported = []
        for k in (
            "melee",
            "manualDetonation",
            "projectileSequence",
            "sourceOwnedFields",
            "finiteFields",
            "ownedEmbed",
            "noxAvatarLifecycle",
            "zymosChildren",
            "quantaStrategy",
            "grimoireStrategy",
        ):
            admitted = set(self.options.get("delivery_kinds") or ())
            admission = {
                "manualDetonation": "manualDetonation",
                "sourceOwnedFields": "sourceOwned",
                "finiteFields": "finiteField",
                "ownedEmbed": "ownedEmbed",
                "noxAvatarLifecycle": "noxAvatarLifecycle",
                "zymosChildren": "zymosChildren",
                "quantaStrategy": "quantaStrategy",
                "grimoireStrategy": "grimoireStrategy",
            }
            if self.combat.get(k) and admission.get(k) not in admitted:
                self.unsupported.append("arena-unsupported-" + k)
        for q in self.sources:
            if q.get("durationPerTier") and not self.combat.get("melee"):
                self.diagnostics.append(
                    "arena-melee-tier-duration-unused-by-ranged-source:" + str(q["id"])
                )
            if q.get("energyThreshold") and not self.combat.get("energySpendPerSecond"):
                self.diagnostics.append("arena-no-energy-spend-events:" + str(q["id"]))
            if q.get("actorOnly") and q.get("kind") not in (
                "on-fire",
                "on-hit",
                "on-kill",
                "on-headshot",
            ):
                self.diagnostics.append(
                    "arena-actor-trigger-only-explicit-combatState:" + str(q["id"])
                )
        actor_state = self.combat.get("projectileState") or {}
        for key, kind in [
            ("selfShieldBreak", "on-shield-broken"),
            ("selfOverguardBreak", "on-overguard-broken"),
            ("selfShieldHit", "on-shield-hit"),
            ("equipFromPrimary", "on-equip-from-primary"),
            ("abilityUse", "on-warframe-ability"),
        ]:
            if key + "At" in actor_state:
                self._source_push(
                    float(actor_state[key + "At"]),
                    "actor",
                    (kind, float(actor_state.get(key + "Interval") or 0.0)),
                )
        rate = float(self.combat.get("energySpendPerSecond") or 0.0)
        if rate > 0:
            for q in self.sources:
                if q.get("energyThreshold"):
                    interval = float(q["energyThreshold"]) / rate
                    if interval > 0:
                        self._source_push(interval, "energy", (q, interval))
        self.diagnostics.extend(self.unsupported)
        if self.enervate:
            self.diagnostics.extend(ENERVATE_ASSUMPTIONS)
        if self.combat.get("shellReload"):
            self.diagnostics.append("arena-shell-reload-uninterrupted-total-clock")
        self.diagnostics.extend(
            [
                "arena-expected-damage-not-discrete-crit-rolls",
                "arena-electric-gas-neighbour-landing-uses-source-pile-moments",
                "arena-mixed-form-heat-last-source-credit",
            ]
        )
        st, _ = self._resolve()
        self.ammo = float(st.magazine)

    def _resolve(self, target=None, stacks=None, last_round=None, form=None):
        live = (
            sum(p.probability(self.time) for p in target.presence.values())
            if target
            else 0.0
        )
        state = (
            dict(stacks)
            if stacks is not None
            else {q["id"]: q["stacks"] for q in self.sources}
        )
        if self.combat.get("onosCharge") and (form or self.form) != "base":
            onos = self.combat["onosCharge"]
            state.setdefault("__onosPower", self.onos_ticks >= onos["alignmentShots"])
            state.setdefault("__onosHits", self.onos_hits)
            state.setdefault(
                "__onosBeamSeconds",
                round(
                    min(onos["rampSeconds"], max(0.0, self.time - self.onos_start)), 6
                ),
            )
        if self._volley_rounds != 1.0 and "__chargeVolleyRounds" not in state:
            state["__chargeVolleyRounds"] = self._volley_rounds
        if last_round is None:
            last_round = self.ammo <= 1.0 + EPS if hasattr(self, "ammo") else False
        st, radial = self.combat["resolve"](form or self.form, state, live, last_round)
        parts = (
            tuple(radial)
            if isinstance(radial, (list, tuple))
            else (
                ()
                if radial is None
                else (radial, *getattr(radial, "_additional_radials", ()))
            )
        )
        for part in (st, *parts):
            part._arena_source_id = id(part)
            self._model_sources[id(part)] = part
        return st, parts

    def add_target(self, id, enemy_record, level=1, position=(0.0, 0.0, 0.0)):
        if id in self.targets:
            raise ValueError("Arena target ids cannot be reused")
        opts = {
            k: self.options[k]
            for k in ("armour_strip", "steel_path", "enemy_enhancements")
            if k in self.options
        }
        defenses = dm.enemy_defenses(enemy_record, level=level, **opts)
        full = [
            float(defenses.get(k) or 0.0) for k in ("overguard", "shield", "health")
        ]
        full[2] *= 1.0 - float(self.combat.get("executeBelow") or 0.0)
        v = ArenaTarget(
            id, dict(enemy_record), level, tuple(position), defenses, full.copy(), full
        )
        self.targets[id] = v
        return v

    def drain_events(self):
        events, self._events = self._events, []
        return events

    def next_event_time(self):
        clocks = [self._queue[0][0]] if self._queue else []
        if self._source_events:
            clocks.append(self._source_events[0][0])
        if self._reload:
            clocks.append(self._reload[0])
        if self._transform:
            clocks.append(self._transform[0])
        if self._charge_pending and self._charge_pending["end"] > self.time + EPS:
            clocks.append(self._charge_pending["end"])
        clocks.extend(
            q["expires"]
            for q in self.sources
            if q["stacks"] and q["expires"] > self.time + EPS
        )
        return min(clocks, default=math.inf)

    def _source_push(self, t, kind, payload):
        self._source_serial += 1
        heapq.heappush(
            self._source_events, (float(t), self._source_serial, kind, payload)
        )

    def actor_event(self, kind, t, weight=1.0):
        """Explicit caller-provided actor event; victim shield breaks are separate."""
        events = self.advance(t)
        self._events.extend(events)
        self._actor_signal = True
        try:
            self._signal(kind, t, weight)
        finally:
            self._actor_signal = False

    def _push(self, t, kind, target, payload):
        self._serial += 1
        heapq.heappush(self._queue, (float(t), self._serial, kind, target.id, payload))

    def _clean_sources(self, t):
        for q in self.sources:
            if q["decay"] in ("per-stack", "union"):
                q["expiries"] = [(end, n) for end, n in q["expiries"] if end > t]
                q["stacks"] = (
                    sum(n for _, n in q["expiries"])
                    if q["decay"] == "per-stack"
                    else 1.0 - math.prod(1.0 - n for _, n in q["expiries"])
                )
            elif q["duration"] and q["stacks"] and t >= q["expires"]:
                if q["decay"] == "lose_one_and_reset":
                    missed = 1 + int((t - q["expires"]) / q["duration"])
                    q["stacks"] = max(0.0, q["stacks"] - missed)
                    q["expires"] += missed * q["duration"]
                else:
                    q["stacks"] = 0.0

    def _signal(self, kind, t, weight=1.0):
        if kind == "on-consecutive-headshot":
            # Same run-distribution contract as combat_replay.consecutive_heads;
            # a body contact must reach this branch even with zero head weight.
            probability = min(1.0, max(0.0, weight))
            for q in self.sources:
                if q["kind"] != kind or not q["perEvent"] or q.get("actorOnly"):
                    continue
                minimum = int(q.get("minimumConsecutive") or 1)
                cap = minimum + int(q["maxStacks"]) - 1
                after = {0: 1.0 - probability}
                for run, value in q.get("runDistribution", {0: 1.0}).items():
                    n = min(run + 1, cap)
                    after[n] = after.get(n, 0.0) + value * probability
                q["runDistribution"] = after
                q["stacks"] = sum(
                    max(n - minimum + 1, 0) * value for n, value in after.items()
                )
                q["expires"] = math.inf
            return
        for q in self.sources:
            if q.get("actorOnly") and not self._actor_signal:
                continue
            if q.get("consumeOn") == kind and q["perEvent"]:
                if q.get("charges"):
                    if q.get("chargesLeft", 0.0) <= EPS:
                        q["stacks"] = 0.0
                    if q["stacks"] > 0:
                        q["chargesLeft"] = q.get("chargesLeft", 0.0) - weight
                else:
                    q["stacks"] = min(q["maxStacks"], q.get("deferred", 0.0))
                    q["deferred"] = 0.0
                    q["locked"] = False
                continue
            if q.get("lockOn") == kind and q["perEvent"]:
                q["locked"] = True
                continue
            gate = (
                self._victim_gate.get(q["victimProcType"], 0.0)
                if q.get("victimProcType")
                else 1.0
            )
            if gate <= 0:
                continue
            if kind in q.get("resetOn", ()) and q["perEvent"]:
                q.update(stacks=0.0, expiries=[], expires=math.inf, progress=deque())
            if q.get("toggleOn") == kind and q["perEvent"]:
                q["stacks"] = 1.0 - q["stacks"]
                continue
            if q["kind"] != kind or q["perEvent"] == 0:
                continue
            required = max(1, q.get("requiredCount", 1))
            if required > 1:
                progress = q["progress"]
                while (
                    progress
                    and q.get("requiredTime")
                    and progress[0][0] < t - q["requiredTime"]
                ):
                    progress.popleft()
                progress.append((t, weight * gate))
                count = math.floor((sum(n for _, n in progress) + EPS) / required)
                consume = count * required
                while progress and consume > EPS:
                    when, n = progress.popleft()
                    if n > consume:
                        progress.appendleft((when, n - consume))
                    consume -= n
                delta = count * q["perEvent"]
            else:
                delta = weight * gate * q["perEvent"]
            if q.get("noRefresh"):
                delta *= max(0.0, 1.0 - q["stacks"] / q["maxStacks"])
            if delta <= 0:
                continue
            if q.get("locked"):
                q["deferred"] = min(q["maxStacks"], q.get("deferred", 0.0) + delta)
                continue
            if q.get("charges"):
                q["chargesLeft"] = q["charges"]
            if q["decay"] == "union":
                p = (
                    min(1.0, delta)
                    if weight <= 1
                    else 1.0 - (1.0 - min(1.0, gate * q["perEvent"])) ** weight
                )
                q["expiries"].append((t + q["duration"], p))
                q["stacks"] = 1.0 - math.prod(1.0 - n for _, n in q["expiries"])
            elif q["decay"] == "per-stack":
                q["expiries"].append((t + q["duration"], delta))
                excess = sum(n for _, n in q["expiries"]) - q["maxStacks"]
                while excess > EPS and q["expiries"]:
                    end, n = q["expiries"].pop(0)
                    remove = min(excess, n)
                    excess -= remove
                    if n > remove:
                        q["expiries"].insert(0, (end, n - remove))
                q["stacks"] = min(q["maxStacks"], q["stacks"] + delta)
            else:
                q["stacks"] = min(q["maxStacks"], q["stacks"] + delta)
            q["expires"] = t + q["duration"] if q["duration"] else math.inf

    def _clean(self, v, t):
        v.heat.expire(t)
        for pool in v.pooled.values():
            pool.expire(t)
        for rows in v.states.values():
            while rows and rows[0][0] < t - EPS:
                rows.popleft()
        if 0 <= v.frozen_until <= t + EPS:
            end = v.frozen_until + 6 * v.frozen_scale
            v.states["DT_FREEZE"] = deque([(end, 3.0)])
            v.presence.setdefault("DT_FREEZE", StatusPresence()).add(end, 0.0)
            v.frozen_until = -1.0

    def advance(self, t):
        t = float(t)
        source_clock = self._source_events[0][0] if self._source_events else math.inf
        shooter_clock = min(
            [x[0] for x in (self._reload, self._transform) if x] + [source_clock],
            default=math.inf,
        )
        if self.time - EPS <= shooter_clock < t - EPS:
            prior = self.advance(shooter_clock)
            self._events.extend(prior)
        if not math.isfinite(t) or t < self.time - EPS:
            raise ValueError("Arena combat clock must be finite and monotonic")
        processed = 0
        while self._queue and self._queue[0][0] <= t:
            when, _, kind, id, payload = heapq.heappop(self._queue)
            self.time = when
            self._clean_sources(when)
            v = self.targets[id]
            self._clean(v, when)
            if kind == "syndicate":
                self._syndicate_burst(when)
                continue
            if not v.alive and not (kind == "pile" and payload[0] == "DT_GAS"):
                continue
            processed += 1
            if processed > 1000000:
                raise RuntimeError("Arena event budget exceeded")
            if kind == "heat":
                if payload != v.heat_token or not v.heat.active():
                    continue
                self._take(
                    v,
                    {"DT_FIRE": v.heat.seed() + v.heat_acc * v.heat.alive()},
                    when,
                    "dot",
                    stats=v.heat_stats,
                    mode=v.heat_mode,
                )
                if v.alive:
                    self._push(when + 1.0, "heat", v, payload)
            elif kind in ("dot", "syndicate-dot"):
                dtype, amount, end, st, mode = payload
                if when <= end + EPS:
                    self._take(
                        v,
                        {dtype: amount},
                        when,
                        "syndicate" if kind == "syndicate-dot" else "dot",
                        stats=st,
                        mode=mode,
                    )
            elif kind == "pile":
                dtype, token = payload
                paid = v.piles[dtype].tick(when, token)
                if paid is None:
                    continue
                amount, weak, count, alive, mode, st, schedule = paid
                ids = [v.id]
                radius = (
                    3.0 if dtype == "DT_ELECTRICITY" else 3.0 + min(count, 10.0) * 0.3
                )
                if self.nearby:
                    ids += [
                        x.id if isinstance(x, ArenaTarget) else x
                        for x in self.nearby(v.id, radius, when)
                    ]
                for other_id in dict.fromkeys(ids):
                    other = self.targets.get(other_id)
                    if other and other.alive:
                        self._clean(other, when)
                        self._take(
                            other,
                            {dtype: amount},
                            when,
                            "dot",
                            head=(weak / amount if amount > 0 else 0.0),
                            stats=st,
                            mode=mode,
                        )
                if schedule:
                    self._push(schedule[0], "pile", v, (dtype, schedule[1]))
            elif kind == "blast":
                if payload["count"] <= 0:
                    continue
                self._take(
                    v,
                    {"DT_EXPLOSION": payload["count"] * payload["per"]},
                    when,
                    "dot",
                    stats=payload["stats"],
                    mode=payload["mode"],
                )
                payload["count"] = 0.0
                if self.enervate:
                    self.enervate.advance(
                        when, event_probability=payload.get("hitProbability", 1.0)
                    )
        while self._source_events and self._source_events[0][0] <= t:
            when, _, kind, payload = heapq.heappop(self._source_events)
            self.time = when
            self._clean_sources(when)
            if kind == "actor":
                event, interval = payload
                self._actor_signal = True
                try:
                    self._signal(event, when)
                finally:
                    self._actor_signal = False
                if interval > 0:
                    self._source_push(when + interval, kind, payload)
            else:
                q, interval = payload
                q["stacks"] = min(q["maxStacks"], q["stacks"] + q["perEvent"])
                q["expires"] = when + q["duration"] if q["duration"] else math.inf
                self._source_push(when + interval, kind, payload)
        self.time = t
        self._clean_sources(t)
        if (
            self.combat.get("battery")
            and not self.combat.get("fullClipCharge")
            and self.form != "incarnon"
        ):
            battery = self.combat["battery"]
            st, _ = self._resolve()
            delay = (
                battery["delayEmptySeconds"]
                if self.ammo <= EPS
                else battery["delayPartialSeconds"]
            )
            start = max(self._battery_updated, self._last_fire + delay)
            if math.isfinite(start):
                self.ammo = min(
                    st.magazine,
                    self.ammo + max(0.0, t - start) * battery["regenPerSecond"],
                )
            self._battery_updated = t
        if self._reload and t >= self._reload[0] - EPS:
            when, empty = self._reload
            self._reload = None
            self._signal("on-reload-complete", when)
            if empty:
                self._signal("on-reload-empty-complete", when)
                if self.combat.get("fieldDurationOnEmptyReload"):
                    self.field_duration_ready = True
            st, _ = self._resolve()
            self.ammo = st.magazine
        if self._transform and t >= self._transform[0] - EPS:
            when, form = self._transform
            self._transform = None
            self.form = form
            st, _ = self._resolve()
            self.ammo = (
                float(self.cycle["pool"])
                if form == "incarnon"
                else min(st.magazine, self.base_ammo or 0.0)
            )
        return self.drain_events()

    def next_attack_time(self, t):
        return max(float(t), self._ready)

    def _transition(self, t, destination, st):
        delay = (
            float(
                self.cycle.get(
                    "enterSeconds" if destination == "incarnon" else "exitSeconds"
                )
                or 0.0
            )
            * st.transform_time_scale
        )
        if destination == "incarnon":
            self.base_ammo = self.ammo
            self.transforms += 1
            self.gauge = 0.0
        if self.double_tap:
            self.double_tap.swap(t)
        if self.combat.get("onosCharge"):
            self.onos_ticks = 0
            self.onos_hits = 0.0
            self.onos_start = t + max(0.0, delay)
        self._burst_round = 0
        self._burst_state = None
        self._signal("on-transform", t)
        self._transform = (t + max(0.0, delay), destination)
        self._ready = self._transform[0]
        self._events.append(
            dict(kind="transform", time=t, form=destination, completes=self._ready)
        )

    def prepare_shot(self, t, head=False, target_id=None):
        events = self.advance(t)
        self._events.extend(events)
        if self.unsupported:
            raise UnsupportedArenaCombat(", ".join(self.unsupported))
        if self._active_shot:
            raise RuntimeError("fire_shot/finish_impact required before another shot")
        if t < self._ready - EPS:
            return None
        v = self.targets.get(target_id)
        if v:
            self._clean(v, t)
        st, radials = self._resolve(v)
        for part in (st, *radials):
            for key in (
                "_stackable",
                "_periodic_fields",
                "_source_owned_fields",
                "_ownedEmbed",
                "_quanta_strategy",
                "_zymos",
                "_owned_embed",
                "_embedded",
                "_lingering",
                "_reload_projectiles",
                "_primary_delay_seconds",
            ):
                admitted = set(self.options.get("delivery_kinds") or ())
                admission = {
                    "_lingering": "lingering",
                    "_stackable": "stackable",
                    "_source_owned_fields": "sourceOwned",
                    "_ownedEmbed": "ownedEmbed",
                    "_owned_embed": "ownedEmbed",
                    "_embedded": "embedded",
                    "_reload_projectiles": "reloadProjectiles",
                    "_quanta_strategy": "quantaStrategy",
                    "_zymos": "zymosChildren",
                }
                stack = getattr(st, "_stackable", None)
                if (
                    key == "_primary_delay_seconds"
                    and "stackable" in admitted
                    and stack
                    and stack[0].get("kind") in ("stug", "simulor", "mq")
                ):
                    continue  # World owns admitted sphere embed/merge/expire clocks.
                if getattr(part, key, None) and admission.get(key) not in admitted:
                    raise UnsupportedArenaCombat("arena-unsupported-component:" + key)
            # Component delay belongs to world impact scheduling, not shooter clocks.
        if (
            self.cycle
            and self.form == "base"
            and self.gauge >= float(self.cycle["hits"]) - EPS
        ):
            self._transition(t, "incarnon", st)
            if self._ready > t + EPS:
                return None
            self.advance(t)
            return self.prepare_shot(t, head, target_id)
        if self.cycle and self.form == "incarnon" and self.ammo <= EPS:
            self._transition(t, "base", st)
            if self._ready > t + EPS:
                return None
            self.advance(t)
            return self.prepare_shot(t, head, target_id)
        st = self._spooled(st, t)
        onos = self.combat.get("onosCharge")
        onos_active = bool(onos and self.form != "base")
        if onos_active:
            self._signal("on-fire-start", t)
        infinite = bool(self.combat.get("infiniteAmmo"))
        cost = (
            getattr(st, "_charge_pool_cost", 1.0) + st.ammo_pool_multishot_cost
            if self.form == "incarnon"
            or self.combat.get("selectedIncarnon")
            or onos_active
            else max(0.0, st.ammo_cost)
        )
        for q in self.sources:
            if q.get("freeAmmo"):
                cost *= max(0.0, 1.0 - min(1.0, q["stacks"]))
        if (
            not infinite
            and st.magazine > 0
            and (self.ammo < cost - EPS or self._force_reload)
        ):
            if (
                self.combat.get("battery")
                and not self.combat.get("fullClipCharge")
                and self.form != "incarnon"
            ):
                b = self.combat["battery"]
                delay = (
                    b["delayEmptySeconds"]
                    if self.ammo <= EPS
                    else b["delayPartialSeconds"]
                )
                regen = float(b["regenPerSecond"])
                if regen <= 0:
                    raise UnsupportedArenaCombat(
                        "arena-battery-nonpositive-regeneration"
                    )
                self._ready = (
                    max(t, self._last_fire + delay) + max(0.0, cost - self.ammo) / regen
                )
                return None
            self.reloads += 1
            self._burst_round = 0
            self._burst_state = None
            for q in self.sources:
                if q["kind"] == "on-burst-hit" and q["perEvent"]:
                    q["stacks"] = 0.0
            if self.ammo <= EPS:
                self._signal("on-reload-empty", t)
            self._signal("on-reload", t)
            self._force_reload = False
            reloaded, _ = self._resolve()
            seconds = reloaded.reload_time
            shell = self.combat.get("shellReload")
            if shell:
                raw = shell["start"] + shell["perShell"] * st.magazine + shell["end"]
                seconds = (
                    shell["start"]
                    + shell["perShell"]
                    * math.ceil(max(0.0, st.magazine - self.ammo) - EPS)
                    + shell["end"]
                ) * (seconds / raw if raw > 0 else 1.0)
            if self.combat.get("spool") and seconds >= self.combat["spool"]["spindown"]:
                self.spool_shots = 0
            self._reload = (t + max(0.001, seconds), self.ammo <= EPS)
            self._ready = self._reload[0]
            self._events.append(dict(kind="reload", time=t, completes=self._ready))
            return None
        loaded = 1.0
        charged_seconds = 0.0
        volley = getattr(st, "_charge_volley", None)
        before_fire = bool(getattr(st, "_charge_before_fire", False))
        if volley or before_fire:
            if self._charge_pending is None:
                loaded = (
                    max(1.0, math.floor(max(0.0, min(self.ammo, st.magazine))))
                    if volley
                    else (
                        st.magazine if getattr(st, "_full_clip_charge", None) else 1.0
                    )
                )
                charged_seconds = (loaded if volley else 1.0) * max(
                    0.0, float(getattr(st, "_charge_time", 0.0))
                )
                self._charge_pending = dict(
                    start=t,
                    end=t + charged_seconds,
                    loaded=loaded,
                    seconds=charged_seconds,
                    form=self.form,
                )
                self._ready = t + charged_seconds
                self._events.append(
                    dict(
                        kind="charge",
                        time=t,
                        completes=self._ready,
                        loadedRounds=loaded,
                    )
                )
                if charged_seconds > EPS:
                    return None
            if t < self._charge_pending["end"] - EPS:
                return None
            loaded = self._charge_pending["loaded"]
            charged_seconds = self._charge_pending["seconds"]
            if volley:
                self._volley_rounds = loaded
                st, radials = self._resolve(v)
                st, radials = self._charge_payload(st, radials, loaded)
                self._volley_rounds = 1.0
                cost = st.ammo_cost
                for q in self.sources:
                    if q.get("freeAmmo"):
                        cost *= max(0.0, 1.0 - min(1.0, q["stacks"]))
            self._charge_pending = None
        if st.fire_rate <= 0:
            raise UnsupportedArenaCombat("arena-nonpositive-fire-rate")
        interval = 1.0 / st.fire_rate
        interval = getattr(
            st,
            "_bow_draw",
            interval
            + (
                0.0
                if before_fire or volley
                else max(0.0, float(getattr(st, "_charge_time", 0.0)))
            ),
        )
        interval = max(
            interval, float(getattr(st, "_native_fire_cooldown_seconds", 0.0))
        )
        base_form = self.form == "base" or (
            self.form == "selected" and not self.combat.get("selectedIncarnon")
        )
        burst = self.combat.get("baseBurst" if base_form else "incarnonBurst")
        if burst:
            if self._burst_round == 0:
                size = (
                    max(1, int(math.ceil(self.ammo / max(cost, EPS) - EPS)))
                    if burst.get("remainingClip") else max(1, int(burst["count"]))
                )
                self._burst_state = dict(size=size, rounds={}, closed=False)
            group = self._burst_state
            self._burst_round += 1
            complete = self._burst_round >= group["size"]
            depleted = not infinite and self.ammo - cost < cost - EPS
            if not complete and not depleted:
                rate = self.combat.get("baseFireRate" if base_form else "incarnonFireRate")
                scale = 1.0 if burst.get("ignoreFireRate") else max(
                    1.0, st.fire_rate / float(rate or st.fire_rate)
                )
                interval = max(0.0, float(burst["delay_seconds"]) / scale)
            else:
                group["closed"] = True
                self._burst_round = 0
        self._shot_id += 1
        shot = ArenaShot(
            self._shot_id,
            t,
            self.form,
            copy(st),
            tuple(copy(x) for x in radials),
            {q["id"]: q["stacks"] for q in self.sources},
            bool(head),
            0.0 if infinite else cost,
            interval,
        )
        if self.combat.get("physicalProjectileLanes"):
            self._attach_physical_lanes(shot, v, preview=False)
        if burst:
            shot.burst_state = group
            group["rounds"][shot.id] = dict(
                hit=False, head=0.0, done=set(), parts=len(shot.physical_lanes) or 1
            )
            for token, lane in enumerate(shot.physical_lanes):
                lane.burst_state = group
                lane.burst_token = token
            if shot.physical_lanes:
                shot.burst_token = -1  # Synchronous parent batches finish all lanes.
        if onos_active:
            shot.onos_phase = (
                "power" if self.onos_ticks >= onos["alignmentShots"] else "beam"
            )
            shot.source_mode_index = 2 if shot.onos_phase == "power" else 1
            shot.stacks.update(
                __onosPower=shot.onos_phase == "power",
                __onosHits=self.onos_hits,
                __onosBeamSeconds=round(
                    min(onos["rampSeconds"], max(0.0, t - self.onos_start)), 6
                ),
            )
        shot.enervate_weights = (
            self.enervate.damage_marginal() if self.enervate else {0: 1.0}
        )
        for lane in shot.physical_lanes:
            lane.enervate_weights = dict(shot.enervate_weights)
        if st.continuous:
            shot.beam_scale = self.beam.tick(
                t,
                interval,
                (self.combat.get("beamRampFloors") or {}).get(self.form, 0.2),
            )
        shot.loaded_rounds = loaded
        shot.charge_seconds = charged_seconds
        if volley:
            shot.stacks["__chargeVolleyRounds"] = loaded
        shot.enervate_weights = (
            self.enervate.damage_marginal() if self.enervate else {0: 1.0}
        )
        self._active_shot = shot
        self.shots += 1
        return shot

    def _component(self, shot, component):
        if component in ("direct", "primary", None):
            return shot.stats
        if component == "radial":
            if not shot.radials:
                raise UnsupportedArenaCombat("arena-no-radial-component")
            return shot.radials[0]
        if isinstance(component, int):
            return shot.components[component]
        if any(component is p for p in shot.components):
            return component
        raise UnsupportedArenaCombat("arena-component-not-in-shot")

    @staticmethod
    def _charge_payload(st, parts, loaded):
        def scale(part):
            out = copy(part)
            out.damage_types = {k: n * loaded for k, n in part.damage_types.items()}
            if out.dot_base_damage is not None:
                out.dot_base_damage *= loaded
            out.ammo_cost *= loaded
            out._charge_time = 0.0
            return out

        return scale(st), tuple(scale(part) for part in parts)

    def _attach_physical_lanes(self, shot, v, preview=False):
        profile = self.combat["physicalProjectileLanes"]
        indices, phase = plan_physical_lanes(
            profile,
            self.physical_phase,
            shot.stats.multishot,
            self.shots,
            float(self.options.get("lane_stratum", 0.5)),
        )
        children = []
        for lane in indices:
            state = {**shot.stacks, "__physicalProjectileIndex": lane}
            direct, radials = self._resolve(v, state, False, shot.form)
            child = ArenaShot(
                shot.id,
                shot.time,
                shot.form,
                copy(direct),
                tuple(copy(p) for p in radials),
                state,
                False,
                0.0,
                shot.interval,
            )
            child.lane_index = lane
            child.source_mode_index = shot.source_mode_index
            child.launched = True
            child.source_lane = profile["lanes"][lane]
            child.physical_profile = profile["lanes"][lane]
            child.enervate_weights = dict(shot.enervate_weights)
            children.append(child)
        shot.physical_lanes = tuple(children)
        shot.phase_after = phase
        if abs(shot.stats.multishot - round(shot.stats.multishot)) > EPS:
            note = "arena-physical-lanes-fractional-count-seeded-trajectory"
            if note not in self.diagnostics:
                self.diagnostics.append(note)

    def hit_lane(
        self,
        parent,
        lane,
        target_id,
        component=0,
        head=False,
        distance=0.0,
        radial_scale=1.0,
        t=None,
    ):
        """Aligned lanes join one parent batch so immediate DoTs follow all contacts.

        With real flight times, world may schedule each prelaunched lane as its
        own begin/hit/finish batch; same-time lanes can use this shared variant.
        """
        t = self.time if t is None else float(t)
        if self._active_shot is not parent:
            raise RuntimeError("Parent impact batch required")
        lane.impact_time = t
        lane.impact_protected = parent.impact_protected
        self._active_shot = lane
        try:
            result = self.hit(
                lane, target_id, component, head, distance, radial_scale, t
            )
        finally:
            self._active_shot = parent
        parent.pending.extend(lane.pending)
        lane.pending.clear()
        parent.restore_amount += lane.restore_amount
        lane.restore_amount = 0.0
        parent.restore_fraction = 1.0 - (1.0 - parent.restore_fraction) * (
            1.0 - lane.restore_fraction
        )
        return result

    def field_parts(self, shot):
        """Prepared delivery packets; world admits only implemented lifecycles."""
        rows = []
        st = shot.stats
        for attribute, kind, refresh in (
            ("_lingering", "lingering", "liveVictimCO"),
            ("_embedded", "embedded", "liveVictimCO"),
            ("_owned_embed", "ownedEmbed", "liveSource"),
        ):
            item = getattr(st, attribute, None)
            if item:
                part, rate, duration = item
                rows.append(
                    dict(
                        kind=kind,
                        part=part,
                        tickRate=float(rate),
                        duration=float(duration),
                        refresh=refresh,
                        slot=0,
                    )
                )
        for attribute, kind in (
            ("_source_owned_fields", "sourceOwned"),
            ("_finite_fields", "finiteField"),
        ):
            for i, item in enumerate(getattr(st, attribute, ())):
                part, rate, duration, damage_on_enter = item
                rows.append(
                    dict(
                        kind=kind,
                        part=part,
                        tickRate=float(rate),
                        duration=float(duration),
                        damageOnEnter=damage_on_enter,
                        slot=i,
                        refresh="liveSource",
                    )
                )
        stack = getattr(st, "_stackable", None)
        if stack:
            rows.append(
                dict(
                    kind="stackable",
                    profile=stack[0],
                    parts=stack[1],
                    slot=0,
                    refresh="snapshot",
                )
            )
        return rows

    def fork_part_shot(self, parent_shot, part, t, refresh="snapshot"):
        """A field tick/child; never pays ammo or advances fire cadence."""
        if refresh not in ("snapshot", "liveVictimCO", "liveSource"):
            raise ValueError("Unknown part refresh policy")
        child = ArenaShot(
            parent_shot.id,
            float(t),
            parent_shot.form,
            copy(part),
            (),
            dict(parent_shot.stacks),
            False,
            0.0,
            0.0,
        )
        child.external_part = True
        child.refresh_policy = refresh
        child.launched = True
        child.enervate_weights = dict(parent_shot.enervate_weights)
        child.onos_phase = parent_shot.onos_phase
        child.source_mode_index = parent_shot.source_mode_index
        return child

    def hit_part(
        self,
        parent_shot,
        part,
        target_id,
        t,
        head=False,
        distance=0.0,
        radial_scale=1.0,
        refresh="snapshot",
    ):
        """Joins an existing world AoE batch, or creates one standalone batch."""
        child = self.fork_part_shot(parent_shot, part, t, refresh)
        batch = self._active_shot
        if batch is not None:
            if batch is not parent_shot or abs((batch.impact_time or 0.0) - t) > EPS:
                raise RuntimeError("Part belongs to another impact batch")
            child.impact_time = float(t)
            child.impact_protected = batch.impact_protected
            self._active_shot = child
            try:
                result = self.hit(child, target_id, 0, head, distance, radial_scale, t)
            finally:
                self._active_shot = batch
            batch.pending.extend(child.pending)
            batch.restore_fraction = 1.0 - (1.0 - batch.restore_fraction) * (
                1.0 - child.restore_fraction
            )
            return result
        self.begin_impact(child, t)
        result = self.hit(child, target_id, 0, head, distance, radial_scale, t)
        self.finish_impact(child, t)
        return result

    def _spooled(self, st, t):
        st = copy(st)
        spool = self.combat.get("spool")
        if spool:
            pellets = min(spool["maximum"], spool["initial"] + self.spool_shots)
            st.fire_rate *= spool["rateStart"] + (1.0 - spool["rateStart"]) * min(
                self.spool_shots / spool["rateShots"], 1.0
            )
            st.multishot *= pellets / spool["maximum"]
            st.status_chance *= spool["maximum"] / pellets
            st.ammo_cost *= math.ceil(pellets / spool["ammoDivisor"]) / math.ceil(
                spool["maximum"] / spool["ammoDivisor"]
            )
        rate = self.combat.get("fireRateSpool") if self.form != "incarnon" else None
        if rate:
            count = 0 if t > self.rate_spool_due + EPS else self.rate_spool_shots
            st.fire_rate *= rate["start"] + (rate["end"] - rate["start"]) * min(
                count / rate["overShots"], 1.0
            )
        return st

    def _contact_factor(self, shot, st, update=False):
        incarnon = shot.form == "incarnon" or self.combat.get("selectedIncarnon")
        factor = 1.0
        if self.double_tap:
            if shot.contact_factor is None:
                tap = self.double_tap if update else copy(self.double_tap)
                hits = shot.stats.multishot * (
                    2.0 if incarnon and shot.radials else 1.0
                )
                value = tap.shot(self.time, hits)
                if update:
                    shot.contact_factor = value
            else:
                value = shot.contact_factor
            if not incarnon or st.radial_only:
                factor *= value
        if (
            self.sniper_combo
            and not shot.stats.radial_only
            and (self.sniper_combo.spec.get("incarnon") or not incarnon)
        ):
            if shot.sniper_factor is None:
                combo = self.sniper_combo if update else copy(self.sniper_combo)
                value = combo.shot(
                    self.time, 1.0 if shot.stats.continuous else shot.stats.multishot
                )
                if update:
                    shot.sniper_factor = value
            else:
                value = shot.sniper_factor
            factor *= value
        return factor

    def _victim_stats(self, shot, v, st, head, distance):
        t = self.time
        if shot.external_part:
            callback = getattr(st, "_live_hit_refresh", None)
            live = sum(p.probability(t) for p in v.presence.values())
            if shot.refresh_policy in ("liveVictimCO", "liveSource"):
                if callback:
                    state = (
                        {q["id"]: q["stacks"] for q in self.sources}
                        if shot.refresh_policy == "liveSource"
                        else shot.stacks
                    )
                    st = callback(state, live)
                elif getattr(st, "_live_co_unit", None) is not None:
                    unit = st._live_co_unit
                    st = dm.co_variant(
                        unit,
                        unit._co_spec,
                        [dm.with_value(e, e.value * live) for e in unit.co_bucket],
                    )
        elif self.combat.get("conditionOverload") or st.co_bucket:
            direct, radials = self._resolve(v, shot.stacks, False, shot.form)
            index = next(i for i, p in enumerate(shot.components) if p is st)
            if self.combat.get("chargeVolley") and shot.loaded_rounds != 1.0:
                direct, radials = self._charge_payload(
                    direct, radials, shot.loaded_rounds
                )
            current = (direct, *radials)[index]
            # Projectile count and fire-time resource shape stay frozen even
            # when the victim-only CO query is refreshed at contact.
            current = copy(current)
            current.multishot = st.multishot
            st = current
        st = copy(st)
        factor = self._contact_factor(shot, st, update=False)
        if factor != 1.0:
            st.damage_types = {k: n * factor for k, n in st.damage_types.items()}
            if st.dot_base_damage is not None:
                st.dot_base_damage *= factor
        aim = bool(head) and (not st.radial_only or st.area_direct)
        cold = self._count(v, "DT_FREEZE", t)
        if not st.radial_only or st.radial_victim_crit:
            st.crit_chance += 0.05 * self._count(v, "DT_PUNCTURE", t)
            st.crit_multiplier += (
                1.0
                if v.frozen_until > t
                else (0.1 * cold if cold < 1 else 0.1 + 0.05 * (cold - 1))
            )
        st._arena_cold_bonus = (
            (
                1.0
                if v.frozen_until > t
                else (0.1 * cold if cold < 1 else 0.1 + 0.05 * (cold - 1))
            )
            if not st.radial_only or st.radial_victim_crit
            else 0.0
        )
        if st.low_crit_threshold is not None:
            st.crit_multiplier = (
                st.low_crit_damage_base
                + (
                    st.low_crit_damage_bonus
                    if st.crit_chance < st.low_crit_threshold
                    else 0.0
                )
                + st._arena_cold_bonus
            )
        if v.shield == v.full[1] and v.health == v.full[2]:
            st.crit_chance += st.victim_full_crit_chance
            st.crit_multiplier += st.victim_full_crit_damage
        if (
            v.full[2]
            and v.health < 0.5 * v.full[2]
            and st.victim_low_health_multiplier != 1.0
        ):
            st.damage_types = {
                k: x * st.victim_low_health_multiplier
                for k, x in st.damage_types.items()
            }
        if st.cold_stack_damage and not st.radial_only and st.base_damage_bracket > 0:
            factor = (
                st.base_damage_bracket + st.cold_stack_damage * min(cold, 10.0)
            ) / st.base_damage_bracket
            st.damage_types = {k: x * factor for k, x in st.damage_types.items()}
            if st.dot_base_damage is not None:
                st.dot_base_damage *= factor
        if cold >= 10 - EPS and not st.radial_only:
            st.damage_types = {
                k: x * st.frozen_damage_multiplier for k, x in st.damage_types.items()
            }
        if not st.radial_only and not shot.external_part:
            modes = self.engine.get("weapon", {}).get("fireModes") or []
            index = (
                shot.source_mode_index
                if shot.source_mode_index is not None
                else (
                    0 if shot.form == "base" else int(self.engine.get("fire_mode", 0))
                )
            )
            if index < len(modes):
                mode = modes[index]
                base = sum((mode.get("damage") or {}).get("types", {}).values())
                st.falloff_multiplier = dm._falloff_multiplier(
                    mode, base, float(distance)
                )
        return st, aim

    def hit(
        self,
        shot,
        target_id,
        component="direct",
        head=False,
        distance=0.0,
        radial_scale=1.0,
        t=None,
    ):
        t = (
            (shot.impact_time if shot.impact_time is not None else shot.time)
            if t is None
            else float(t)
        )
        if shot.finished or shot is not self._active_shot:
            raise ValueError("begin_impact required or shot is no longer active")
        if shot.impact_time is None:
            shot.impact_time = t
        if abs(t - shot.impact_time) > EPS:
            raise ValueError("All contacts in an impact batch must share a timestamp")
        v = self.targets[target_id]
        protected = (
            (target_id in shot.impact_protected) if shot.launched else v.protected
        )
        if not v.alive or protected:
            return dict(damage=0.0, killed=False, protected=protected)
        self._clean(v, t)
        st = self._component(shot, component)
        primary_contact = st is shot.stats
        shot.victim_gate = {dtype: p.probability(t) for dtype, p in v.presence.items()}
        self._victim_gate = shot.victim_gate
        self._contact_factor(shot, st, update=True)
        st, aim = self._victim_stats(shot, v, st, head, distance)
        scale = max(0.0, float(radial_scale)) * max(
            0.0, float(self.options.get("damage_rate_multiplier", 1.0))
        )
        packet = self._mixed_packet(v, st, aim, shot.enervate_weights)
        before = self.total_damage
        shot.current_distance = float(distance)
        self._take(
            v,
            {k: n * scale * shot.beam_scale for k, n in packet[0].items()},
            t,
            "direct",
            head=float(aim),
            stats=st,
            mode=shot.form,
        )
        if v.alive:
            self._procs(v, st, aim, t, packet, scale, shot.form)
        if (
            self.combat.get("onosCharge")
            and shot.onos_phase == "power"
            and not st.radial_only
        ):
            self.onos_condition_hits += 1.0 if st.continuous else max(0.0, st.multishot)
            completed = math.floor(self.onos_condition_hits / 2.0)
            self.onos_condition_hits -= completed * 2.0
            if completed:
                self._defer_signal("on-onos-damage-condition", t, completed)
        if (
            self.combat.get("onosCharge")
            and shot.onos_phase == "beam"
            and self.combat.get("onosCrits")
        ):
            self.onos_hits = min(
                50.0,
                self.onos_hits + (1.0 if st.continuous else max(0.0, st.multishot)),
            )
        if self.enervate and not st.radial_only:
            self._enervate_hit(st, float(aim), t, shot.form)
        shot.hits.append((target_id, float(aim), st, float(distance)))
        count = 1.0 if st.continuous else max(0.0, st.multishot)
        if primary_contact and not st.radial_only and not shot.external_part and count > 0:
            first_contact = target_id not in shot.contact_targets
            shot.contact_targets.add(target_id)
            if first_contact:
                if shot.burst_state is not None:
                    round_state = shot.burst_state["rounds"][shot.id]
                    round_state["hit"] = True
                    round_state["head"] = max(
                        round_state["head"], 1.0 - (1.0 - float(aim)) ** count
                    )
                shot.pending.append(("on-consecutive-headshot", float(aim)))
                if len(shot.contact_targets) > 1:
                    shot.pending.append(("on-punchthrough", 1.0))
                    if shot.form == "base" or not self.combat.get("selectedIncarnon"):
                        shot.pending.append(("on-onos-damage-condition", 1.0))
                if len(shot.contact_targets) == 3:
                    shot.pending.append(("on-three-enemy-punchthrough", 1.0))
            restore = self.combat.get("magazineRestore")
            magazine_form = shot.form == "base" or (
                not self.cycle and not self.combat.get("selectedIncarnon")
            )
            if (
                restore and magazine_form
                and restore.get("kind") in ("on-headshot", "on-hit")
            ):
                gate = (
                    shot.victim_gate.get(restore["victimProcType"], 0.0)
                    if restore.get("victimProcType") else 1.0
                )
                eligible = first_contact or not restore.get("oncePerShot")
                if restore.get("oncePerShot") and getattr(
                    shot, "_hit_restore_used", False
                ):
                    eligible = False
                if eligible and gate > 0:
                    probability = (
                        1.0 - (1.0 - float(aim)) ** count
                        if restore["kind"] == "on-headshot" else 1.0
                    )
                    chance = probability * restore.get("chance", 1.0) * gate
                    shot.restore_fraction = 1.0 - (1.0 - shot.restore_fraction) * (
                        1.0 - restore.get("fraction", 0.0) * chance
                    )
                    shot.restore_amount += (
                        restore.get("amount", 0.0)
                        * (1.0 if restore.get("oncePerShot") else count) * chance
                    )
                    shot._hit_restore_used = True
        weak = (
            st.weakpoint_crit_chance_bonus
            + st.base_crit_chance * st.weakpoint_crit_chance_relative
        )
        critical = sum(
            weight
            * (
                min(1.0, max(0.0, st.crit_chance + stacks * 0.1 + weak))
                if aim
                else min(
                    1.0,
                    max(
                        0.0,
                        (st.crit_chance + stacks * 0.1) * st.bodyshot_crit_multiplier,
                    ),
                )
            )
            for stacks, weight in shot.enervate_weights.items()
        )
        shot.pending.extend(
            [
                ("on-hit", count, dict(shot.victim_gate)),
                ("on-headshot", float(aim) * count, dict(shot.victim_gate)),
                ("on-body-hit", float(not aim) * count, dict(shot.victim_gate)),
                ("on-crit", critical * count, dict(shot.victim_gate)),
            ]
        )
        if any(q.get("kind") == "on-noncrit-no-proc" for q in self.sources):
            no_proc = max(0.0, 1.0 - st.status_chance)
            for chance in st.independent_proc_chances.values():
                no_proc *= max(0.0, 1.0 - chance)
            for forced in (
                *st.native_forced_procs.values(),
                *(self.options.get("forced_procs") or {}).values(),
            ):
                no_proc *= max(0.0, 1.0 - forced)
            shot.pending.append(
                ("on-noncrit-no-proc", count * (1.0 - critical) * no_proc)
            )
        return dict(
            damage=self.total_damage - before, killed=not v.alive, protected=False
        )

    def fire_shot(self, shot, t=None):
        """Launch once; many launched shots may coexist in the world."""
        t = shot.time if t is None else float(t)
        if shot.launched:
            return shot
        if shot.finished:
            raise ValueError("Shot is retired")
        if abs(t - shot.time) > EPS:
            raise ValueError("Launch must use prepared fire time")
        if self.field_duration_ready:
            magazine_form = shot.form == "base" or (
                not self.cycle and not self.combat.get("selectedIncarnon")
            )
            if magazine_form:
                shot.field_duration_multiplier = float(
                    self.combat["fieldDurationOnEmptyReload"]["multiplier"]
                )
            self.field_duration_ready = False
        self.ammo = max(0.0, self.ammo - shot.ammo_cost)
        self._last_fire = t
        self._battery_updated = t
        if self.combat.get("spool"):
            self.spool_shots += 1
        if self.combat.get("fireRateSpool") and shot.form != "incarnon":
            if t > self.rate_spool_due + EPS:
                self.rate_spool_shots = 0
            self.rate_spool_shots += 1
        self.rate_spool_due = t + shot.interval
        self._force_reload = bool(self.combat.get("reloadAfterEveryShot"))
        self._signal("on-fire", t)
        if shot.physical_lanes:
            self.physical_phase = shot.phase_after
            self.physical_trace.append(
                dict(
                    time=t,
                    lanes=[p.lane_index for p in shot.physical_lanes],
                    phaseAfterPull=self.physical_phase,
                )
            )
        onos = self.combat.get("onosCharge")
        if onos and shot.onos_phase:
            if shot.onos_phase == "power":
                self.onos_ticks = 0
                self.onos_hits = 0.0
                shot.interval = onos["postFireSeconds"]
                self.onos_start = t + shot.interval
            else:
                self.onos_ticks += 1
        self._ready = t + shot.interval
        shot.launched = True
        if self._active_shot is shot:
            self._active_shot = None
        return shot

    def begin_impact(self, shot, t):
        events = self.advance(t)
        self._events.extend(events)
        if not shot.launched:
            self.fire_shot(shot)
        if self._active_shot is not None:
            raise RuntimeError("Previous impact batch not finished")
        if (
            shot.finished
            and not self.field_parts(shot)
            and not any(
                self.combat.get(k)
                for k in (
                    "manualDetonation",
                    "noxAvatarLifecycle",
                    "zymosChildren",
                    "quantaStrategy",
                    "grimoireStrategy",
                )
            )
        ):
            raise ValueError("Shot retired")
        shot.impact_time = float(t)
        shot.impact_protected = (
            self.protected_ids
            if self.protected_ids is not None
            else frozenset(
                id for id, v in self.targets.items() if v.alive and v.protected
            )
        )
        self._active_shot = shot
        return shot

    def finish_impact(self, shot, t=None, retire=True):
        t = shot.impact_time if t is None else float(t)
        if shot is not self._active_shot:
            raise ValueError("Foreign impact batch")
        if (
            not shot.external_part
            and self.cycle
            and shot.form == "base"
            and self.cycle.get("chargeOn") != "kills"
        ):
            charge_direct = self.cycle.get("chargeOn") == "direct_hits"
            hits = sum(
                (1.0 if charge_direct else aim)
                * st.multishot
                * st.incarnon_charge_multiplier
                for _, aim, st, _ in shot.hits
                if not st.radial_only
            )
            self.gauge = min(float(self.cycle["hits"]), self.gauge + hits)
        self._victim_gate = shot.victim_gate
        for event in shot.pending:
            kind, weight = event[:2]
            self._victim_gate = event[2] if len(event) > 2 else shot.victim_gate
            self._signal(kind, t, weight)
        self._victim_gate = {}
        if shot.restore_fraction or shot.restore_amount:
            st, _ = self._resolve()
            self.ammo = min(
                st.magazine, self.ammo
                + max(0.0, st.magazine - self.ammo) * shot.restore_fraction
                + shot.restore_amount,
            )
            shot.restore_fraction = shot.restore_amount = 0.0
        group = shot.burst_state
        if retire and group is not None and not group.get("resolved"):
            round_state = group["rounds"][shot.id]
            round_state["done"].update(
                range(round_state["parts"]) if shot.burst_token == -1
                else (shot.burst_token,)
            )
            if group["closed"] and all(
                len(row["done"]) == row["parts"] for row in group["rounds"].values()
            ):
                group["resolved"] = True
                rounds = tuple(group["rounds"].values())
                if len(rounds) == group["size"] and all(row["hit"] for row in rounds):
                    self._signal("on-burst-hit", t)
                    self._signal(
                        "on-burst-headshot", t,
                        math.prod(row["head"] for row in rounds),
                    )
        shot.pending.clear()
        shot.hits.clear()
        shot.finished = bool(retire)
        self._active_shot = None
        events = self.advance(t)
        self._events.extend(events)
        return dict(
            ammo=self.ammo, nextAttackTime=self._ready, form=self.form, gauge=self.gauge
        )

    def finish_shot(self, shot, t=None):
        """Compatibility shortcut for synchronous contacts, one ammo payment."""
        when = shot.time if t is None else float(t)
        self.fire_shot(shot, shot.time)
        self._active_shot = shot
        if shot.impact_time is None:
            shot.impact_time = when
        return self.finish_impact(shot, when)

    def preview(self, t, target_id=None):
        """Read-only shooter snapshot for planning; no clocks advance."""
        if float(t) < self.time - EPS:
            raise ValueError("Preview cannot look backwards")
        probe = copy(self)
        probe.time = float(t)
        probe.sources = deepcopy(self.sources)
        probe._clean_sources(t)
        v = deepcopy(self.targets.get(target_id))
        if v:
            probe._clean(v, t)
        state = {q["id"]: q["stacks"] for q in probe.sources}
        loaded = (
            max(
                1.0,
                math.floor(
                    max(0.0, min(self.ammo, probe._resolve(v, state)[0].magazine))
                ),
            )
            if self.combat.get("chargeVolley")
            else 1.0
        )
        if self.combat.get("chargeVolley"):
            state["__chargeVolleyRounds"] = loaded
        st, parts = probe._resolve(v, state)
        if self.combat.get("chargeVolley"):
            st, parts = probe._charge_payload(st, parts, loaded)
        st = probe._spooled(st, t)
        shot = ArenaShot(
            -1,
            float(t),
            self.form,
            copy(st),
            tuple(copy(x) for x in parts),
            state,
            False,
            0.0,
            1.0 / st.fire_rate if st.fire_rate > 0 else math.inf,
        )
        if self.combat.get("physicalProjectileLanes"):
            self._attach_physical_lanes(shot, v, preview=True)
        if self.combat.get("onosCharge") and self.form != "base":
            shot.onos_phase = (
                "power"
                if self.onos_ticks >= self.combat["onosCharge"]["alignmentShots"]
                else "beam"
            )
            shot.source_mode_index = 2 if shot.onos_phase == "power" else 1
        shot.loaded_rounds = (
            st.magazine if getattr(st, "_full_clip_charge", None) else loaded
        )
        shot.enervate_weights = (
            self.enervate.damage_marginal() if self.enervate else {0: 1.0}
        )
        return shot

    def estimate(
        self,
        shot,
        target_id,
        component="direct",
        head=False,
        scale=1.0,
        distance=0.0,
        radial_scale=None,
    ):
        """Read-only immediate damage; deliberately does not construct proc rows."""
        v = self.targets[target_id]
        if not v.alive or v.protected:
            return 0.0
        st, aim = self._victim_stats(
            shot, v, self._component(shot, component), head, distance
        )
        factor = (
            float(scale if radial_scale is None else radial_scale)
            * shot.beam_scale
            * max(0.0, float(self.options.get("damage_rate_multiplier", 1.0)))
        )
        vector = {}
        for stacks, weight in shot.enervate_weights.items():
            view = self._crit_view(st, stacks)
            for k, n in self._direct_vector(v, view, aim).items():
                vector[k] = vector.get(k, 0.0) + n * factor * weight
        delta = dm._faction_damage_deltas(v.record)
        bypass = dm._damage_type_set(
            v.record.get("shieldBypassDamageTypes"),
            dm.DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES,
        )
        armor_bypass = dm._damage_type_set(
            v.record.get("armourBypassDamageTypes"),
            dm.DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
        )
        armor = self._armour_factor(v, self.time)

        def hv(k, n):
            return (
                n
                * max(0.0, 1.0 + delta.get(k, 0.0))
                * self._vulnerability(v, "DT_VIRAL")
                * (1.0 if k in armor_bypass else armor)
            )

        left = 1.0
        applied = 0.0
        broke = False
        if v.overguard > 0:
            value = sum(
                n * (1.5 if k in ("DT_VOID", "DT_RADIANT") else 1.0)
                for k, n in vector.items()
            ) * self._vulnerability(v, "DT_MAGNETIC")
            if value <= 0:
                return 0.0
            fortifier = self.combat.get("fortifier")
            if fortifier:
                value *= 1.0 + (fortifier["multiplier"] - 1.0) * fortifier.get(
                    "uptime", 1.0
                )
            share = min(left, v.overguard / value)
            applied += value * share
            left -= share
        if left > 0 and v.shield > 0:
            value = sum(
                n * max(0.0, 1.0 + delta.get(k, 0.0))
                for k, n in vector.items()
                if k not in bypass
            ) * self._vulnerability(v, "DT_MAGNETIC")
            leak = sum(hv(k, n) for k, n in vector.items() if k in bypass)
            share = min(
                left,
                v.shield / value if value > 0 else math.inf,
                v.health / leak if leak > 0 else math.inf,
            )
            paid = min(v.shield, value * share)
            hp = min(v.health, leak * share)
            applied += paid + hp
            left -= share
            broke = paid >= v.shield - EPS
            if not broke:
                return applied
            health_left = v.health - hp
        else:
            health_left = v.health
        if left > 0:
            amount = sum(hv(k, n) for k, n in vector.items()) * left
            if broke:
                amount *= float(aim) + (1.0 - float(aim)) * 0.05
            applied += min(health_left, amount)
        return applied

    def _count(self, v, dtype, t):
        if dtype == "DT_FIRE":
            return v.heat.count()
        if dtype == "DT_FREEZE" and v.frozen_until > t:
            return 10.0
        if dtype in v.pooled:
            return v.pooled[dtype].stats()[1]
        if dtype in v.piles:
            return v.piles[dtype].moments(t)[2]
        return sum(n for _, n in v.states.get(dtype, ()))

    def _vulnerability(self, v, dtype):
        present, n = v.pooled[dtype].stats()
        return min(4.25, 1.0 + 0.75 * present + 0.25 * n)

    def _armour_factor(self, v, t):
        base = (
            v.defenses.get("armour", 0.0)
            * (1.0 - float(self.options.get("elemental_armour_strip") or 0.0))
            * (1.0 - v.heat.strip(t))
            * (1.0 - v.puncture_strip)
        )
        return sum(
            weight
            * (
                1.0
                - dm._armour_reduction(
                    base * (1.0 - (0.0 if k == 0 else min(0.26 + 0.06 * (k - 1), 0.8)))
                )
            )
            for k, weight in enumerate(v.pooled["DT_CORROSIVE"].distribution())
            if weight
        )

    def _packet_key(self, v, st, head):
        # A retained source token replaces full dataclass repr on every aim query.
        token = getattr(st, "_arena_source_id", None)
        if token is None:
            token = id(st)
            self._model_sources[token] = st
        return (
            token,
            head,
            tuple(st.damage_types.items()),
            st.crit_chance,
            st.crit_multiplier,
            st.dot_base_damage,
            st.falloff_multiplier,
            st.multishot,
            st.status_chance,
            tuple(st.independent_proc_chances.items()),
            tuple(st.crit_proc_chances.items()),
            tuple(st.impact_proc_conversions),
            v.record.get("faction", ""),
            dm.faction_bracket(v.record),
            id(v.record.get("hitProxies")),
        )

    @staticmethod
    def _crit_view(st, stacks):
        view = copy(st)
        view.crit_chance = max(0.0, st.crit_chance + stacks * 0.1)
        if st.low_crit_threshold is not None:
            view.crit_multiplier = (
                st.low_crit_damage_base
                + (
                    st.low_crit_damage_bonus
                    if view.crit_chance < st.low_crit_threshold
                    else 0.0
                )
                + getattr(st, "_arena_cold_bonus", 0.0)
            )
        return view

    def _enervate_hit(self, st, aim, t, mode):
        if (
            st.multishot <= 0
            or self.combat["enervate"].get("ignoreSelected")
            and mode != "base"
        ):
            return
        weak = (
            st.weakpoint_crit_chance_bonus
            + st.base_crit_chance * st.weakpoint_crit_chance_relative
        )
        probabilities = {}
        for stacks in self.enervate.marginal():
            cc = max(0.0, st.crit_chance + stacks * 0.1)
            p = (1.0 - aim) * big_crit_probability(
                cc * st.bodyshot_crit_multiplier, st.double_crit_chance
            ) + aim * big_crit_probability(cc + weak, st.double_crit_chance)
            probabilities[stacks] = any_probability(
                p, 1.0 if st.continuous else st.multishot
            )
        self.enervate.advance(t, probabilities)

    def _mixed_packet(self, v, st, head, weights):
        if weights == {0: 1.0}:
            return self._packet(v, st, head)
        vector = {}
        procs = {}
        rows = {}
        non = {}
        seeds = {}
        non_sums = {}
        for stacks, weight in weights.items():
            view = self._crit_view(st, stacks)
            values, counts, dots, other = self._packet(v, view, head)
            for k, x in values.items():
                vector[k] = vector.get(k, 0.0) + weight * x
            for k, x in counts.items():
                procs[k] = procs.get(k, 0.0) + weight * x
            for k, row in dots.items():
                branches = rows.get(k, {}).get("landingBranches", [])
                rows[k] = dict(row)
                if "landingBranches" in row:
                    rows[k]["landingBranches"] = branches + [
                        {**b, "weight": b["weight"] * weight}
                        for b in row["landingBranches"]
                    ]
                seeds[k] = (
                    seeds.get(k, 0.0)
                    + weight * counts.get(k, 0.0) * row["seedPerSecondPerProc"]
                )
            for k, row in other.items():
                non[k] = dict(row)
                non_sums[k] = (
                    non_sums.get(k, 0.0) + weight * counts.get(k, 0.0) * row["perProc"]
                )
        for k, row in rows.items():
            row["seedPerSecondPerProc"] = seeds[k] / procs[k] if procs[k] else 0.0
        for k, row in non.items():
            row["perProc"] = non_sums[k] / procs[k] if procs[k] else 0.0
        return vector, procs, rows, non

    def _direct_vector(self, v, st, head):
        key = self._packet_key(v, st, head)
        if key in self._direct_cache:
            return self._direct_cache[key]
        location = "head" if head else "body"
        bare = {**v.defenses, "armour": 0.0, "overguard": 0.0, "shield": 0.0}
        _, hm, hcm, _, _ = dm._hit_location_info(v.record, location)
        cache = dict(
            hit_multiplier=hm,
            hit_critical_multiplier=hcm,
            faction_deltas={},
            armour_bypass=frozenset(),
            shield_bypass=frozenset(),
            target_faction=v.record.get("faction", ""),
        )
        hit = dm.damage_against_cached_armour(
            st, 0.0, bare, target=v.record, _target_cache=cache
        )
        raw = sum(hit["perType"].values())
        vector = (
            {k: n * hit["perShot"] / raw for k, n in hit["perType"].items()}
            if raw
            else {}
        )
        if len(self._direct_cache) >= 4096:
            self._direct_cache.clear()
        self._direct_cache[key] = vector
        return vector

    def _packet(self, v, st, head):
        # Victim defenses are applied at landing, independently of cached seeds.
        key = (
            repr(st),
            head,
            str(v.record.get("faction", "")),
            repr(v.record.get("hitProxies", [])),
            dm.faction_bracket(v.record),
        )
        if key in self._packet_cache:
            return self._packet_cache[key]
        vector = self._direct_vector(v, st, head)
        location = "head" if head else "body"
        neutral = dict(
            health=1.0,
            shield=0.0,
            armour=0.0,
            level=1,
            faction=v.record.get("faction", ""),
            hitProxies=v.record.get("hitProxies", []),
            factionResistance="RK_NEUTRAL",
            factionBracket=dm.faction_bracket(v.record),
        )
        status = dm.expected_status_damage(
            st,
            neutral,
            level=1,
            hit_location=location,
            forced_procs=self.options.get("forced_procs"),
        )
        rows = {k: dict(row) for k, row in status["dot"]["perType"].items()}
        instances = 1.0 if st.continuous else max(st.multishot, 0.0)
        one = replace(st, multishot=st.multishot if st.continuous else 1.0)
        forced = (
            {
                k: n / instances
                for k, n in (self.options.get("forced_procs") or {}).items()
            }
            if instances
            else {}
        )
        for dtype in ("DT_ELECTRICITY", "DT_GAS"):
            if dtype in rows:
                row = rows[dtype]
                row["landingBranches"] = [
                    dict(
                        weight=1.0,
                        procs=status["expectedProcs"].get(dtype, 0.0),
                        seed=row["seedPerSecondPerProc"],
                        accumulator=row["accumulatorPerSecondPerAttack"],
                        landing=row["landingMultiplier"],
                        head=row["landingHead"],
                        weak=row["landingWeakEligible"],
                        aim=float(head),
                        absence=no_status_probability(one, dtype, forced, float(head)),
                    )
                ]
        result = (
            vector,
            status["expectedProcs"],
            rows,
            status.get("nonDot", {}).get("perType", {}),
        )
        if len(self._packet_cache) >= 4096:
            self._packet_cache.clear()
        self._packet_cache[key] = result
        return result

    def _take(self, v, vector, t, source, head=0.0, stats=None, mode=None, extra=False):
        if not v.alive or v.protected:
            return False
        weapon_source = source != "syndicate"
        if (
            self.combat.get("onosCharge")
            and self.combat.get("onosCrits")
            and self.form != "base"
            and self.onos_ticks < self.combat["onosCharge"]["alignmentShots"]
            and source == "dot"
            and any(n > 0 for n in vector.values())
        ):
            self.onos_hits = min(50.0, self.onos_hits + 1.0)
        deltas = dm._faction_damage_deltas(v.record)
        armour_bypass = dm._damage_type_set(
            v.record.get("armourBypassDamageTypes"),
            dm.DEFAULT_ARMOUR_BYPASS_DAMAGE_TYPES,
        )
        shield_bypass = dm._damage_type_set(
            v.record.get("shieldBypassDamageTypes"),
            dm.DEFAULT_SHIELD_BYPASS_DAMAGE_TYPES,
        )

        def health_value(dtype, raw):
            factor = max(0.0, 1.0 + deltas.get(dtype, 0.0)) * self._vulnerability(
                v, "DT_VIRAL"
            )
            if dtype not in armour_bypass:
                factor *= self._armour_factor(v, t)
            return raw * factor

        left, applied, broke = 1.0, 0.0, False
        if v.overguard > 0:
            value = sum(
                x * (1.5 if k in ("DT_VOID", "DT_RADIANT") else 1.0)
                for k, x in vector.items()
            ) * self._vulnerability(v, "DT_MAGNETIC")
            if value <= 0:
                return False
            fortifier = self.combat.get("fortifier") if weapon_source else None
            if fortifier:
                value *= 1.0 + (fortifier["multiplier"] - 1.0) * fortifier.get(
                    "uptime", 1.0
                )
            share = min(left, v.overguard / value)
            drain = value * share
            if fortifier:
                self.fortifier_damage += drain
                self.self_overguard = min(
                    fortifier["cap"],
                    self.self_overguard
                    + drain * fortifier["steal"] * fortifier.get("uptime", 1.0),
                )
            v.pools[0] = max(0.0, v.overguard - drain)
            applied += drain
            left -= share
            if v.overguard <= EPS:
                self._magnetic_break(v, t, 0, stats, mode)
                self._defer_signal("on-overguard-broken", t)
        if left > 0 and v.shield > 0:
            shield = sum(
                x * max(0.0, 1.0 + deltas.get(k, 0.0))
                for k, x in vector.items()
                if k not in shield_bypass
            ) * self._vulnerability(v, "DT_MAGNETIC")
            bypass = sum(
                health_value(k, x) for k, x in vector.items() if k in shield_bypass
            )
            share = min(
                left,
                v.shield / shield if shield > 0 else math.inf,
                v.health / bypass if bypass > 0 else math.inf,
            )
            a, b = min(v.shield, shield * share), min(v.health, bypass * share)
            v.pools[1] = max(0.0, v.shield - a)
            v.pools[2] = max(0.0, v.health - b)
            applied += a + b
            left -= share
            if v.shield <= EPS:
                broke = True
                self._magnetic_break(v, t, 1, stats, mode)
                self._defer_signal("on-shield-broken", t)
        if left > 0 and v.shield <= EPS and v.health > 0:
            value = sum(health_value(k, x) for k, x in vector.items()) * left
            if broke:
                value *= head + (1.0 - head) * 0.05
            drain = min(v.health, value)
            v.pools[2] = max(0.0, v.health - drain)
            applied += drain
        v.damage += applied
        self.total_damage += applied
        if source == "direct":
            self.direct_damage += applied
        elif source == "syndicate":
            self.syndicate_damage += applied
        elif source == "arcane":
            self.arcane_damage += applied
        else:
            self.dot_damage += applied
        if v.health <= EPS and v.overguard <= EPS:
            v.alive = False
            v.death_time = t
            self.kills += 1
            self._events.append(
                dict(
                    kind="kill",
                    target_id=v.id,
                    targetId=v.id,
                    time=t,
                    source=source,
                    headshot=bool(head),
                    position=v.position,
                )
            )
            if weapon_source:
                self._syndicate_kill(v, t)
            for kind, n in (
                [("on-kill", 1.0), ("on-headshot-kill", head)] if weapon_source else []
            ):
                self._defer_signal(kind, t, n)
            if (
                weapon_source
                and self._active_shot is not None
                and getattr(self._active_shot, "current_distance", math.inf) <= 5.0
            ):
                self._defer_signal("on-close-kill", t)
            slot = str(self.combat.get("weaponSlot") or "").lower()
            if weapon_source and ("longgun" in slot or slot in ("primary", "rifle")):
                self._defer_signal("on-primary-kill", t)
            restore = self.combat.get("magazineRestore")
            if (
                weapon_source
                and restore
                and restore.get("kind") in ("on-kill", "on-headshot-kill")
                and (
                    mode == "base"
                    or (not self.cycle and not self.combat.get("selectedIncarnon"))
                )
            ):
                p = (
                    restore.get("chance", 1.0)
                    * restore.get("fraction", 0.0)
                    * (head if restore.get("kind") == "on-headshot-kill" else 1.0)
                )
                if self._active_shot:
                    self._active_shot.restore_fraction = 1.0 - (
                        1.0 - self._active_shot.restore_fraction
                    ) * (1.0 - p)
                else:
                    active, _ = self._resolve()
                    self.ammo += max(0.0, active.magazine - self.ammo) * p
            if (
                weapon_source
                and self.cycle
                and self.cycle.get("chargeOn") == "kills"
                and mode == "base"
            ):
                self.gauge = min(float(self.cycle["hits"]), self.gauge + 1.0)
            v.heat.reset()
            return True
        if source == "direct" and stats is not None and stats.extra_hits and not extra:
            faction = stats.faction_damage_multipliers.get("", 1.0)
            if v.record.get("faction"):
                faction *= stats.faction_damage_multipliers.get(
                    v.record["faction"], 1.0
                )
            faction *= dm.faction_bracket(v.record)
            _, hm, _, _, _ = dm._hit_location_info(v.record, "head" if head else "body")
            for dtype, share, _ in stats.extra_hits:
                if self._take(
                    v,
                    {dtype: sum(vector.values()) * share * faction * hm},
                    t,
                    source,
                    head,
                    stats,
                    mode,
                    extra=True,
                ):
                    return True
        return False

    def _syndicate_kill(self, v, t):
        spec = self.combat.get("syndicate")
        if not spec or t < self.syndicate_ready:
            return
        base = v.record.get("affinity")
        if base is None:
            base = (
                reference()
                .get("enemyAffinity", {})
                .get(
                    str(v.record.get("nameEn") or v.record.get("name") or "").casefold()
                )
            )
        if base is None:
            note = "arena-syndicate-affinity-unavailable"
            if note not in self.diagnostics:
                self.diagnostics.append(note)
            return
        eximus = bool((self.options.get("enemy_enhancements") or {}).get("eximus"))
        self.syndicate_affinity += (
            math.floor(
                float(base)
                * ((3.0 if eximus else 1.0) + 0.1425 * math.sqrt(max(v.level, 1)))
            )
            * 0.5
        )
        if (
            self.syndicate_affinity >= spec["affinityToFill"]
            and not self._syndicate_pending
        ):
            self._syndicate_pending = True
            self._push(t, "syndicate", v, None)

    def _syndicate_burst(self, t):
        self._syndicate_pending = False
        spec = self.combat.get("syndicate")
        if (
            not spec
            or t < self.syndicate_ready
            or self.syndicate_affinity < spec["affinityToFill"]
        ):
            return
        self.syndicate_affinity = 0.0
        self.syndicate_ready = t + 30.0
        config = reference().get("syndicates", {}).get(spec["id"], {})
        radius = float(config.get("radius_m", 25.0))
        dtype = spec["damageType"]
        if self.syndicate_targets is None:
            self._events.append(
                dict(
                    kind="syndicate",
                    time=t,
                    radius=radius,
                    damageType=dtype,
                    requiresWorldTargets=True,
                )
            )
            return
        ids = self.syndicate_targets(radius, t)
        for id in dict.fromkeys(x.id if isinstance(x, ArenaTarget) else x for x in ids):
            v = self.targets.get(id)
            if v is None or not v.alive:
                continue
            self._clean(v, t)
            died = self._take(
                v, {dtype: float(config.get("damage", 1000.0))}, t, "syndicate"
            )
            if died or spec["id"] == "justice":
                continue
            duration = (
                8.0
                if dtype == "DT_CORROSIVE"
                else 12.0 if dtype == "DT_RADIATION" else 6.0
            )
            if dtype in v.pooled:
                v.pooled[dtype].add(t + duration, 0.0, 1.0)
            else:
                v.states.setdefault(dtype, deque()).append((t + duration, 1.0))
            v.presence.setdefault(dtype, StatusPresence()).add(t + duration, 0.0)
            if dtype in ("DT_GAS", "DT_POISON"):
                for j in range(6) if dtype == "DT_GAS" else range(1, 7):
                    self._push(
                        t + j,
                        "syndicate-dot",
                        v,
                        (dtype, 500.5, t + 6.0, None, "incarnon"),
                    )
        self._events.append(
            dict(
                kind="syndicate",
                time=t,
                radius=radius,
                damageType=dtype,
                damage=self.syndicate_damage,
            )
        )

    def _defer_signal(self, kind, t, weight=1.0):
        if weight <= 0:
            return
        if self._active_shot:
            self._active_shot.pending.append((kind, weight, dict(self._victim_gate)))
        else:
            self._signal(kind, t, weight)

    def _magnetic_break(self, v, t, index, st, mode):
        stacks = min(self._count(v, "DT_MAGNETIC", t), 10.0)
        if stacks <= 0 or st is None:
            return
        duration_scale = dm.proc_duration_scale(st, "DT_ELECTRICITY")
        if duration_scale <= 0:
            return
        faction = st.faction_damage_multipliers.get("", 1.0)
        if v.record.get("faction"):
            faction *= st.faction_damage_multipliers.get(v.record["faction"], 1.0)
        faction *= dm.faction_bracket(v.record)
        bracket = max(
            0.0, st.dot_elemental_multipliers.get("DT_ELECTRICITY", 1.0)
        ) * max(0.0, st.proc_damage_multiplier)
        seed = v.full[index] * 0.03 * stacks / 6 * faction**2 * bracket
        probability = v.presence.get("DT_MAGNETIC", StatusPresence()).probability(t)
        outcomes = [
            (1.0 - probability, 0, 0.0, 0.0, 1.0, False),
            (probability, 1, seed, 0.5 * faction * bracket, 1.0, False),
        ]
        v.presence.setdefault("DT_ELECTRICITY", StatusPresence()).add(
            t + 6.0 * duration_scale, 1.0 - probability
        )
        self._defer_signal("proc-DT_ELECTRICITY", t, probability)
        self._defer_signal("on-proc", t, probability)
        schedule = v.piles["DT_ELECTRICITY"].add(
            t, 6.0 * duration_scale, outcomes, mode, st
        )
        if schedule:
            self._push(schedule[0], "pile", v, ("DT_ELECTRICITY", schedule[1]))

    def _empowered_hit(self, v, st, dtype, count, t, natural, mode):
        spec = self.combat.get("empowered")
        if not natural or not spec or dtype not in STATUS_POOL:
            return False
        count *= spec.get("uptime", 1.0)
        if count <= 0:
            return False
        faction = st.faction_damage_multipliers.get("", 1.0)
        if v.record.get("faction"):
            faction *= st.faction_damage_multipliers.get(v.record["faction"], 1.0)
        faction *= dm.faction_bracket(v.record)
        self.empowered_count += count
        return self._take(
            v,
            {dtype: count * spec["damage"] * faction},
            t,
            "arcane",
            stats=st,
            mode=mode,
        )

    def _procs(self, v, st, head, t, packet, scale, mode, natural=True):
        _, procs, rows, non = packet
        rate = max(0.0, float(self.options.get("status_rate_multiplier", 1.0)))
        if natural and self.combat.get("punctureArmorStrip") and not st.radial_only:
            # Each bullet strips once if it applied any Puncture, independently
            # of how many stacks that bullet rolled. Keep the strip on its victim.
            one = replace(st, multishot=st.multishot if st.continuous else 1.0)
            probability = 1.0 - no_status_probability(
                one, "DT_PUNCTURE", self.options.get("forced_procs"), float(head)
            )
            bullets = 1.0 if st.continuous else max(0.0, st.multishot)
            v.puncture_strip = min(
                1.0, v.puncture_strip
                + self.combat["punctureArmorStrip"] * bullets * probability,
            )
        encumber = self.combat.get("encumber")
        if natural and encumber and encumber.get("uptime", 1.0) > 0 and rate > 0:
            if abs(t - self._encumber_time) > EPS:
                self._encumber_time = t
                self._encumber_remaining = 1.0
            probability, merged = encumber_roll(
                st, encumber["chance"], self.options.get("forced_procs"), float(head)
            )
            weight = (
                self._encumber_remaining * probability * encumber.get("uptime", 1.0)
            )
            self._encumber_remaining *= 1.0 - probability * encumber.get("uptime", 1.0)
            if weight > 0:
                self.encumber_expected += weight
                probe = copy(st)
                probe.status_chance = 0.0
                probe.continuous = False
                probe.multishot = 1.0
                probe.independent_proc_chances = {k: 1.0 for k in STATUS_POOL}
                probe.impact_proc_conversions = {}
                probe.crit_proc_chances = {}
                _, _, extra_rows, extra_non = self._packet(v, probe, head)
                extra_rows = {
                    k: {
                        **row,
                        "seedPerSecondPerProc": row["seedPerSecondPerProc"] * merged,
                        **(
                            {
                                "landingBranches": [
                                    {**b, "seed": b["seed"] * merged}
                                    for b in row["landingBranches"]
                                ]
                            }
                            if "landingBranches" in row
                            else {}
                        ),
                    }
                    for k, row in extra_rows.items()
                }
                extra_non = {
                    k: {**row, "perProc": row["perProc"] * merged}
                    for k, row in extra_non.items()
                }
                self._procs(
                    v,
                    st,
                    head,
                    t,
                    (
                        {},
                        dict.fromkeys(STATUS_POOL, weight / len(STATUS_POOL)),
                        extra_rows,
                        extra_non,
                    ),
                    scale,
                    mode,
                    False,
                )
                if not v.alive:
                    return
        proc_items = (
            sorted(procs.items()) if self.combat.get("empowered") else procs.items()
        )
        for dtype, count in proc_items:
            count *= rate
            duration_scale = dm.proc_duration_scale(st, dtype)
            if count <= 0 or dtype == "DT_FREEZE" and v.frozen_until > t:
                continue
            self._defer_signal("proc-" + dtype, t, count)
            self._defer_signal("on-proc", t, count)
            if duration_scale <= 0:
                if self._empowered_hit(v, st, dtype, count, t, natural, mode):
                    return
                continue
            row = rows.get(dtype)
            duration = (
                row["durationSeconds"]
                if row
                else DURATIONS.get(dtype, 6.0) * duration_scale
            )
            if duration <= 0:
                if self._empowered_hit(v, st, dtype, count, t, natural, mode):
                    return
                continue
            absent = (
                no_status_probability(
                    st, dtype, self.options.get("forced_procs"), float(head)
                )
                ** rate
            )
            if absent >= 1.0:
                absent = 1.0 - min(1.0, count)
            if not natural:
                absent = max(absent, 1.0 - min(1.0, count))
            kernels = None
            if dtype in v.piles and row:
                branches = [
                    {
                        **b,
                        "seed": b["seed"] * scale,
                        "accumulator": b["accumulator"] * scale,
                    }
                    for b in row["landingBranches"]
                ]
                kernels = proc_pile_outcomes(st, branches, count)
                absent = math.prod(k.absence() for k in kernels)
            v.presence.setdefault(dtype, StatusPresence()).add(t + duration, absent)
            if dtype == "DT_FIRE" and row:
                if not v.heat.active():
                    v.heat_token += 1
                    self._push(t + 1.0, "heat", v, v.heat_token)
                v.heat.add(
                    t,
                    absent,
                    count,
                    count * row["seedPerSecondPerProc"] * scale,
                    duration,
                    duration_scale,
                )
                v.heat_acc = row["accumulatorPerSecondPerAttack"] * scale
                v.heat_stats = st
                v.heat_mode = mode
            elif dtype in v.pooled:
                v.pooled[dtype].add(t + duration, absent, count)
            elif dtype in v.piles and row:
                for kernel in kernels:
                    schedule = v.piles[dtype].add(t, duration, kernel, mode, st)
                    if schedule:
                        self._push(schedule[0], "pile", v, (dtype, schedule[1]))
            elif dtype in non:
                active = [x for x in v.blasts if x["count"] > 0]
                kept = min(count, max(0.0, 10.0 - sum(x["count"] for x in active)))
                item = dict(
                    count=kept,
                    per=non[dtype]["perProc"] * scale,
                    stats=st,
                    mode=mode,
                    hitProbability=min(
                        kept,
                        1.0
                        - no_status_probability(
                            st, dtype, self.options.get("forced_procs"), float(head)
                        ),
                    ),
                )
                v.blasts.append(item)
                self._push(t + 1.5 * duration_scale, "blast", v, item)
                if sum(x["count"] for x in active) + kept >= 10.0 - EPS:
                    value = sum(x["count"] * x["per"] for x in [*active, item])
                    for x in [*active, item]:
                        x["count"] = 0.0
                    self._take(
                        v, {"DT_EXPLOSION": value}, t, "dot", stats=st, mode=mode
                    )
            else:
                state = v.states.setdefault(dtype, deque())
                state.append((t + duration, count))
                if dtype == "DT_FREEZE":
                    cap = 4.0 if v.overguard > 0 else 10.0
                    excess = sum(n for _, n in state) - cap
                    while state and excess > EPS:
                        end, n = state.popleft()
                        remove = min(n, excess)
                        excess -= remove
                        if n > remove:
                            state.appendleft((end, n - remove))
                    if v.overguard <= EPS and sum(n for _, n in state) >= 10.0 - EPS:
                        v.frozen_until = t + 3 * duration_scale
                        v.frozen_scale = duration_scale
                if row:
                    per = row["seedPerSecondPerProc"]
                    if not row["accumulatorSharedGroup"]:
                        per += row["coefficient"]
                    dtype_tick = "DT_CINEMATIC" if dtype == "DT_SLASH" else dtype
                    for j in range(1, int(math.floor(duration + EPS)) + 1):
                        self._push(
                            t + j,
                            "dot",
                            v,
                            (dtype_tick, count * per * scale, t + duration, st, mode),
                        )
            if not v.alive or self._empowered_hit(
                v, st, dtype, count, t, natural, mode
            ):
                return
        cryogenic = self.combat.get("cryogenic")
        if natural and cryogenic:
            extra = (
                max(procs.get("DT_PUNCTURE", 0.0), 0.0)
                * cryogenic["coldStacks"]
                * cryogenic.get("uptime", 1.0)
            )
            if extra > 0:
                ids = [v.id]
                if self.nearby:
                    ids += [
                        x.id if isinstance(x, ArenaTarget) else x
                        for x in self.nearby(v.id, cryogenic["radius"], t)
                    ]
                for id in dict.fromkeys(ids):
                    other = self.targets.get(id)
                    if other and other.alive and not other.protected:
                        self._clean(other, t)
                        self._procs(
                            other,
                            st,
                            head,
                            t,
                            ({}, {"DT_FREEZE": extra}, {}, {}),
                            scale,
                            mode,
                            False,
                        )
                        self.cryogenic_expected += extra * rate
