"""Recovered ordinary Defense schedule rules, WaveDefend.lua (2026.10.28).

P26 451..461 unlocks cumulative tiers. P25 196..439 filters/merges and
allocates quotas; P16 emits XP-sorted rows; P25 496..612 spaces/truncates.
Inputs must already pass resource/faction checks and the caller's tier filter.
Native resource availability, faction overrides, boss cadence and RNG bit parity
are outside this pure scheduling module. This is not an Interception director.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import math
import struct
from typing import Callable, Iterable, Mapping


# Current native VM NUMBER and arithmetic handlers use float32. Round at
# EACH operation, including source constants and native math-return values.
_FLOAT = struct.Struct("<f")


def _f32(value):
    return _FLOAT.unpack(_FLOAT.pack(value))[0]


def _add(a, b):
    return _f32(_f32(a) + _f32(b))


def _sub(a, b):
    return _f32(_f32(a) - _f32(b))


def _mul(a, b):
    return _f32(_f32(a) * _f32(b))


def _div(a, b):
    return _f32(_f32(a) / _f32(b))


def _lerp(a, b, t):
    return _add(_mul(_sub(b, a), t), a)


def defense_tier(wave: int) -> int:
    """Regular tiers <= this value are eligible; boss tiers are separate."""
    if int(wave) != wave or wave < 1:
        raise ValueError("wave must be a positive integer")
    return min(int(wave) // 3, 5)



def defense_enemy_level(wave, start_level, *, max_level=None, arbitration=False):
    """WaveDefend P48 141..182/1483..1529 ordinary spawn level.

    The source reads two Director level endpoints. A one-value scenario uses
    that explicit value for both; pass max_level for a known mission range.
    Main R33=10 is the initial interpolation horizon. Ordinary and Arbitration
    Defense share this expression: Arbitration adds no separate multiplier.
    Special Circle/Duviri overrides and live Director endpoint modifiers are
    outside this function. The result is passed to P26 then P25's spawn call;
    it does not change the saved initial level used for population interpolation.
    """
    if int(wave) != wave or wave < 1:
        raise ValueError("wave must be a positive integer")
    low = _f32(start_level)
    high = low if max_level is None else _f32(max_level)
    if not math.isfinite(low) or not math.isfinite(high) or low < 1 or high < low:
        raise ValueError("level endpoints must be positive and ordered")
    position, horizon = _mul(wave, 90), _mul(10, 90)
    if position <= horizon:
        return math.floor(_lerp(low, high, _div(position, horizon)))
    elapsed = _sub(position, horizon)
    divisor = max(math.ceil(_sub(90, _mul(_div(elapsed, 90), 0.99))), 5)
    return int(_add(high, math.floor(_div(elapsed, divisor))))


def defense_wave_parameters(wave, players, level, *, arbitration=False,
                            max_alive=40, mission_difficulty=0.0,
                            eximus_multiplier=1.0):
    """WaveDefend P26 ordinary branch; level is the mission starting level.

    Current PC Director hard maximum defaults to40; explicit max_alive allows
    verified task overrides. Reserved slots/native actor filtering remain outside
    wave population math. Mission difficulty and leader multiplier remain
    explicit inputs until the selected live MissionInfo is available.
    """
    low, high = (7, 13, 22, 25), (10, 20, 26, 29)
    player_index = min(4, max(1, int(players))) - 1
    ratio = min(_div(level, 30), _f32(1))
    alive = min(int(max_alive), math.floor(_lerp(
        low[player_index], high[player_index], ratio)))
    factor = _lerp(2, 3, _mul(min(int(wave), 10), 0.1))
    requested = math.ceil(_mul(alive, factor))
    if arbitration:
        requested = math.ceil(_mul(requested, 0.8))
    difficulty_offset = math.floor(_lerp(10, 0, mission_difficulty))
    begin, end = _add(difficulty_offset, 2), _add(difficulty_offset, 35)
    chance = (0.0 if wave < begin else _lerp(
        _mul(0.02, eximus_multiplier), _mul(0.15, eximus_multiplier),
        min(_div(_sub(wave, begin), _sub(end, begin)), _f32(1))))
    return dict(tier=defense_tier(wave), requestedTotal=requested,
                maxAlive=alive, eximusProbability=chance,
                rushCount=math.floor(_mul(requested, 0.25)))


def build_defense_schedule(
    entries: Iterable[Mapping], total: int, max_alive: int,
    random_value: Callable[[], float], *, eximus_probability: float = 0.0,
    boss_entries: Iterable[Mapping] | None = None,
) -> dict:
    """Build a schedule from already eligible entries without mutating them.

    Preserve source ``agent`` paths as type identity (native typeName). Supply
    ``xp`` and, optionally, ``eximusXp`` on each entry for native XP ordering;
    absent XP is explicitly qualified and uses 1 solely for neutral ordering.
    ``entries`` in the result are source-compatible rows ready for spawning.
    A zero maxSimultaneous is uncapped; a positive value controls quota and
    schedule spacing. It is not a hard lifetime total for this enemy type.
    ``boss_entries`` is an optional separately filtered exact boss-tier pool;
    the caller owns cadence and LastBossSpawnWave. One uniformly chosen group
    is appended after regular sorting, before spacing and total-N truncation.
    """
    if int(total) != total or total < 0:
        raise ValueError("total must be a nonnegative integer")
    if int(max_alive) != max_alive or max_alive < 1:
        raise ValueError("max_alive must be a positive integer")
    if not math.isfinite(eximus_probability) or not 0 <= eximus_probability <= 1:
        raise ValueError("eximus_probability must be between zero and one")
    total, max_alive = int(total), int(max_alive)
    eximus_probability = _f32(eximus_probability)
    missing_xp = set()

    # Data rows and the supplied random stream are validated by the caller;
    # keep public scalar boundaries above, not repeated checks per spawn.
    def draw():
        return _f32(random_value())

    def symbol_groups(sources):
        result = []
        for source in sources:
            row = deepcopy(dict(source))
            if not row.get("agent") or row.get("runnable") is False:
                continue
            result.append(dict(row=row, probability=_f32(row.get("probability", 0)),
                               cap=_f32(row.get("maxSimultaneous", 0)),
                               members=None, tiers={row.get("tier", 0)}))
        # P14 drops tier, so P17 sees nil == nil across source tiers.
        i = 0
        while i < len(result) - 1:
            group = result[i]
            symbol = group["row"].get("mergeSymbol")
            if symbol:
                for j in range(len(result) - 1, i, -1):
                    other = result[j]
                    if other["row"].get("mergeSymbol") == symbol:
                        if group["members"] is None:
                            group["members"] = [group["row"]]
                        group["members"].append(other["row"])
                        group["probability"] = _add(group["probability"], other["probability"])
                        group["cap"] = max(group["cap"], other["cap"])
                        group["tiers"].update(other["tiers"])
                        result.pop(j)
            i += 1
        return result

    groups = symbol_groups(entries)
    bosses = symbol_groups(boss_entries or ())

    # P25 merges a duplicate into its first later typeName match, scanning
    # backwards. An uncapped duplicate makes the combined type uncapped.
    weight_sum = 0.0
    # P25 pc328..386 traverses from the last source row to the first.
    for group in reversed(groups):
        weight_sum = _add(weight_sum, group["probability"])
    for i in range(len(groups) - 1, -1, -1):
        group = groups[i]
        identity = group["row"].get("typeName") or group["row"]["agent"]
        for other in groups[i + 1:]:
            if (other["row"].get("typeName") or other["row"]["agent"]) == identity:
                other["probability"] = _add(other["probability"], group["probability"])
                other["cap"] = (_add(other["cap"], group["cap"])
                                  if other["cap"] and group["cap"] else 0)
                other["tiers"].update(group["tiers"])
                groups.pop(i)
                break

    schedule, spacing, quotas = [], [], []

    def emit(group, group_index, quota, probability, *, boss=False):
        cap = 0 if boss else group["cap"]
        # P17's first merged member is the representative table itself.
        group["row"]["maxSimultaneous"] = cap
        spacing_index = None
        if cap > 0:
            spacing.append(math.floor(_add(_div(max_alive, cap), 0.5)))
            spacing_index = len(spacing)
        for _ in range(quota):
            members = group["members"]
            member = (members[min(len(members) - 1, math.floor(_mul(draw(), len(members))))]
                      if members else group["row"])
            row = deepcopy(member)
            xp = row.get("xp")
            if xp is None:
                missing_xp.add(row["agent"])
                xp = 1.0
            xp = _f32(xp)
            eximus = (row.get("avatarVariants", {}).get("EXIMUS") or {})
            eximus_available = bool(row.get("eximusXp") or
                                    eximus.get("resolvedAvatarPath"))
            is_eximus = eximus_available and draw() < probability
            if is_eximus:
                elite_xp = row.get("eximusXp")
                if elite_xp is None:
                    missing_xp.add(row["agent"] + ":EXIMUS")
                    elite_xp = xp
                xp = _mul(1.5, elite_xp)
            # P16 multiplies each draw separately, then adds sequentially.
            jitter = 0.0
            for _ in range(4):
                jitter = _add(jitter, _mul(draw(), 0.3))
            row.update(spawnGroup=group_index,
                       spacingIndex=(spacing_index if
                                     member.get("maxSimultaneous", 0) > 0 else None),
                       scheduledBoss=boss, scheduledEximus=bool(is_eximus),
                       sortKey=_add(_f32(math.log10(xp)), jitter))
            schedule.append(row)

    if weight_sum > 0 and total:
        for group_index, group in enumerate(groups):
            quota = math.floor(_add(_div(_mul(total, group["probability"]), weight_sum), draw()))
            cap = group["cap"]
            if cap > 0:
                quota = min(quota, math.floor(_mul(cap, _div(total, max_alive))))
            quotas.append(dict(agent=group["row"]["agent"],
                               mergeSymbol=group["row"].get("mergeSymbol", ""),
                               tiers=sorted(group["tiers"]), probability=group["probability"],
                               maxSimultaneous=cap, quota=quota))
            if quota > 0:
                emit(group, group_index, quota, eximus_probability)

    schedule.sort(key=lambda row: row["sortKey"])
    boss_quota = None
    if bosses and total:
        # P25 pc464..495: uniform group selection, not weighted roulette;
        # append AFTER regular sort. Cap becomes zero only after reading count.
        boss = bosses[min(len(bosses) - 1, math.floor(_mul(draw(), len(bosses))))]
        count = int(boss["cap"]) if boss["cap"] > 0 else 1
        boss_quota = dict(agent=boss["row"]["agent"],
                          mergeSymbol=boss["row"].get("mergeSymbol", ""),
                          tiers=sorted(boss["tiers"]), quota=count)
        emit(boss, len(groups), count, 100.0, boss=True)

    # Direct one-based translation of the forward/backward table.insert
    # operations, including strict bounds and no last-index update on a move.
    for spacing_index, distance in enumerate(spacing, 1):
        last = None
        for k in range(1, len(schedule) + 1):
            if schedule[k - 1]["spacingIndex"] != spacing_index:
                continue
            if last is None or distance <= k - last:
                last = k
            elif k + distance < len(schedule):
                row = schedule.pop(k - 1)
                schedule.insert(k + distance - 1, row)
        last = None
        for k in range(len(schedule), 0, -1):
            if schedule[k - 1]["spacingIndex"] != spacing_index:
                continue
            if last is None or distance <= last - k:
                last = k
            elif k - distance > 0:
                row = schedule.pop(k - 1)
                schedule.insert(k - distance - 1, row)
    trimmed = max(0, len(schedule) - total)
    if trimmed:
        del schedule[:trimmed]
    qualifications = ["native-resource-and-faction-overrides-not-replayed",
                      "native-rng-and-equal-sort-key-order-not-bit-identical",
                      "special-mission-spawns-excluded"]
    if missing_xp:
        qualifications.append("missing-agent-xp-neutral-sort-order")
    actual = Counter(row["agent"] for row in schedule)
    return dict(entries=schedule, requestedTotal=total, scheduledTotal=len(schedule),
                maxAlive=max_alive, probabilitySum=weight_sum, quotas=quotas,
                tiers=sorted({tier for group in groups for tier in group["tiers"]}),
                spacing=spacing, trimmed=trimmed, counts=dict(actual),
                bossQuota=boss_quota,
                bossCount=sum(row["scheduledBoss"] for row in schedule),
                missingXp=sorted(missing_xp), qualifications=qualifications)
