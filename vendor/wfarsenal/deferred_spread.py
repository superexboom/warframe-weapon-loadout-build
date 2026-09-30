"""Deferred spread experiment (2026-09-30 user preference).

Not imported by damage, replay, search, or contribution code. Geometry and native
angle reduction are retained for future research, NOT game-measured hit accuracy.
To reconnect: revalidate hitbox/angle semantics and wire all scoring paths together.
"""
from __future__ import annotations
import math
from .damage import ModdedStats, _bucket, _combine


def resolved_angles(profile, effects, *, aiming):
    """Research only: callers must supply already weapon-filtered effects."""
    cone = profile['spreadAim' if aiming else 'spreadHip']
    terms = _bucket(effects)['WEAPON_SPREAD']
    return (max(0., _combine(cone['min_deg'], terms)),
            max(0., _combine(cone['max_deg'], terms)))


def spread_hit_probability(stats: ModdedStats, distance: float | None, *, body_radius: float = 0.25) -> float:
    """Expected one-target landing probability for the aimed spread cone.

    WFSim samples a deviation uniformly from [0, min_deg] and accepts a ray
    crossing the target circle. This is the one-target expectation; crowd
    epicentres and sustained-fire bloom remain outside this scalar API.
    """
    if distance is None or distance <= 0.0 or stats.spread_min_deg is None or stats.spread_min_deg <= 0.0:
        return 1.0
    # min_deg is already resolved with native ADD/relative spread effects.
    effective = float(stats.spread_min_deg)
    if effective <= 0.0:
        return 1.0
    range_to_centre = max(float(distance) - float(body_radius), 0.0)
    if range_to_centre <= 0.0 or range_to_centre <= body_radius:
        return 1.0
    threshold = math.degrees(math.asin(min(1.0, body_radius / range_to_centre)))
    return min(1.0, max(0.0, threshold / effective))



# Prior arcane aggregation experiment, retained only for future geometry work.
from .status_arcanes import STATUS_POOL

def encumber_roll_with_misses(stats,chance,forced_procs=None,*,hit_probability=1.0):
    """One-success probability and conditional beam seed, over integer rolls.
    Extra statuses never feed back into their own trigger.
    """
    landing=min(max(float(hit_probability),0.),1.)
    m=max(float(stats.multishot),0.);low=math.floor(m);frac=m-low
    q_ind=1.
    for dtype,p in stats.independent_proc_chances.items():
        if dtype in STATUS_POOL:q_ind*=1-min(max(float(p),0.),1.)
    for dtype,n in stats.native_forced_procs.items():
        if dtype in STATUS_POOL:q_ind*=1-min(max(float(n),0.),1.)
    forced=min(sum(max(float(n),0.) for k,n in (forced_procs or {}).items() if k in STATUS_POOL),1.)
    sc=max(float(stats.status_chance),0.) if any(stats.damage_types.get(k,0)>0 for k in STATUS_POOL) else 0.
    probability=seed=0.
    for pellets,weight in ((low,1-frac),(low+1,frac)):
        if pellets<=0 or weight<=0:continue
        if stats.continuous:
            source=1-(1-min(sc*pellets,1.))*q_ind*(1-forced)
            p=landing*chance*source;merged=pellets
        else:
            source=1-(1-min(sc,1.))*q_ind
            # Thin individual pellet opportunities before aggregating.
            # Explicit per-trigger forced procs share the first pellet's hit.
            no_first=(1-landing)+landing*(1-chance*source)*(1-chance*forced*(1-source))
            p=1-no_first*(1-landing*chance*source)**(pellets-1)
            merged=1.
        probability+=weight*p;seed+=weight*p*merged
    return probability,seed/probability if probability else 1.
