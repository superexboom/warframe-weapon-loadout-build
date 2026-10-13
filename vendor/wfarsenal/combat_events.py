"""Deterministic single-target combat event primitives.

This module owns event identity/order only.  Damage formulae stay in
``damage.py``.  The first integrated route is a direct-fire ledger used to
prove that one attack instance cannot kill a target generation and then reuse
its remaining pellets/components against the respawned generation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import itertools
from typing import Any, Iterable, Mapping


PHASE_ATTACK = 10
PHASE_HIT = 20
PHASE_DEATH = 30
PHASE_TRIGGER = 40


@dataclass(order=True, frozen=True)
class CombatEvent:
    time: float
    phase: int
    sequence: int
    attack_instance_id: int = field(compare=False)
    component_id: str = field(compare=False)
    source_id: str = field(compare=False)
    target_id: str = field(compare=False)
    target_generation: int = field(compare=False)
    event_type: str = field(compare=False)
    payload: Mapping[str, Any] = field(compare=False, default_factory=dict)


class EventQueue:
    def __init__(self) -> None:
        self._heap: list[CombatEvent] = []
        self._sequence = itertools.count()

    def push(
        self,
        *,
        time: float,
        phase: int,
        attack_instance_id: int,
        component_id: str,
        source_id: str,
        target_id: str,
        target_generation: int,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
    ) -> CombatEvent:
        event = CombatEvent(
            time=float(time),
            phase=int(phase),
            sequence=next(self._sequence),
            attack_instance_id=int(attack_instance_id),
            component_id=str(component_id),
            source_id=str(source_id),
            target_id=str(target_id),
            target_generation=int(target_generation),
            event_type=str(event_type),
            payload=dict(payload or {}),
        )
        heapq.heappush(self._heap, event)
        return event

    def pop(self) -> CombatEvent:
        return heapq.heappop(self._heap)

    def __bool__(self) -> bool:
        return bool(self._heap)


def direct_fire_ledger(
    *,
    attacks_per_second: float,
    window_seconds: float,
    target_ehp: float,
    component_damage: Iterable[tuple[str, float]],
    source_id: str = "weapon",
    target_id: str = "target",
    collect_trace: bool = True,
) -> dict[str, Any]:
    """Replay deterministic direct attacks against instant-respawn targets.

    All components of an attack capture the target generation at fire time.
    If an earlier component kills that generation, later components from the
    same attack are recorded as stale and cannot retarget the respawn.
    """
    rate = max(float(attacks_per_second), 0.0)
    window = max(float(window_seconds), 0.0)
    ehp = max(float(target_ehp), 0.0)
    components = [(str(name), max(float(damage), 0.0)) for name, damage in component_damage]
    if rate <= 0.0 or window <= 0.0 or ehp <= 0.0 or not components:
        return {
            "model": "direct-event-ledger-v1",
            "attacks": 0,
            "kills": 0,
            "killsPerMinute": 0.0,
            "firstKillTime": None,
            "staleComponents": 0,
            "targetGeneration": 0,
            "traceCollected": bool(collect_trace),
            "trace": [],
        }

    if len(components) == 1 and not collect_trace:
        return _single_component_ledger(rate, window, ehp, components[0][1])
    queue = EventQueue()
    period = 1.0 / rate
    attack_id = 0
    fire_time = 0.0
    while fire_time < window - 1e-12:
        queue.push(
            time=fire_time,
            phase=PHASE_ATTACK,
            attack_instance_id=attack_id,
            component_id="attack",
            source_id=source_id,
            target_id=target_id,
            target_generation=-1,
            event_type="attack",
            payload={"components": components},
        )
        attack_id += 1
        fire_time = attack_id * period

    health = ehp
    kills = 0
    stale = 0
    generation = 0
    first_kill_time: float | None = None
    trace: list[dict[str, Any]] = []
    while queue:
        event = queue.pop()
        if event.event_type == "attack":
            captured_generation = generation
            for component_id, damage in event.payload.get("components") or ():
                queue.push(
                    time=event.time,
                    phase=PHASE_HIT,
                    attack_instance_id=event.attack_instance_id,
                    component_id=str(component_id),
                    source_id=event.source_id,
                    target_id=event.target_id,
                    target_generation=captured_generation,
                    event_type="hit",
                    payload={"damage": float(damage)},
                )
            continue
        if event.target_generation != generation:
            stale += 1
            if collect_trace:
                trace.append(
                    {
                        "time": event.time,
                        "attackInstanceId": event.attack_instance_id,
                        "componentId": event.component_id,
                        "targetGeneration": event.target_generation,
                        "eventType": "stale-hit",
                    }
                )
            continue
        damage = max(float(event.payload.get("damage") or 0.0), 0.0)
        applied = min(health, damage)
        health -= applied
        if collect_trace:
            trace.append(
                {
                    "time": event.time,
                    "attackInstanceId": event.attack_instance_id,
                    "componentId": event.component_id,
                    "targetGeneration": generation,
                    "eventType": "hit",
                    "appliedDamage": applied,
                }
            )
        if health <= 1e-12:
            kills += 1
            if first_kill_time is None:
                first_kill_time = event.time
            generation += 1
            health = ehp
            if collect_trace:
                trace.append(
                    {
                        "time": event.time,
                        "attackInstanceId": event.attack_instance_id,
                        "componentId": event.component_id,
                        "targetGeneration": generation - 1,
                        "eventType": "death",
                    }
                )
    return {
        "model": "direct-event-ledger-v1",
        "attacks": attack_id,
        "kills": kills,
        "killsPerMinute": kills * (60.0 / window),
        "firstKillTime": first_kill_time,
        "staleComponents": stale,
        "targetGeneration": generation,
        "remainingHealth": health,
        "traceCollected": bool(collect_trace),
        "trace": trace,
    }


def _single_component_ledger(rate: float, window: float, ehp: float, damage: float) -> dict[str, Any]:
    """direct_fire_ledger for one component without a trace.

    Each attack's single hit is the next event after the attack itself (same
    time, later phase; attacks are strictly increasing in time), so no hit can
    be stale and the queue reduces to this loop with the same arithmetic.
    """
    period = 1.0 / rate
    attacks = 0
    fire_time = 0.0
    while fire_time < window - 1e-12:
        attacks += 1
        fire_time = attacks * period
    damage = max(float(damage or 0.0), 0.0)
    health = ehp
    kills = generation = 0
    first_kill_time: float | None = None
    for attack in range(attacks):
        applied = min(health, damage)
        health -= applied
        if health <= 1e-12:
            kills += 1
            if first_kill_time is None:
                first_kill_time = float(attack * period) if attack else 0.0
            generation += 1
            health = ehp
    return {
        "model": "direct-event-ledger-v1",
        "attacks": attacks,
        "kills": kills,
        "killsPerMinute": kills * (60.0 / window),
        "firstKillTime": first_kill_time,
        "staleComponents": 0,
        "targetGeneration": generation,
        "remainingHealth": health,
        "traceCollected": False,
        "trace": [],
    }
