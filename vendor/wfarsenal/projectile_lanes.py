"""Physical projectile lane contracts; cadence and actual packet counts stay separate."""
from __future__ import annotations
import math
from copy import deepcopy

GOLDEN=(5**.5-1)/2
FRACTIONAL_DIAGNOSTIC='projectile-lanes-fractional-count-16-stratified-trajectories-approximation'

def profile(attack):
    value=attack.get('projectileLanes') if isinstance(attack,dict) else None
    if not value:return None
    lanes=value.get('lanes') or []
    if value.get('kind')!='cyclic-physical-projectile' or not lanes or value.get('length')!=len(lanes):
        raise ValueError('invalid physical projectile lane contract')
    if value.get('extraPolicy')!='continue-sequence':raise ValueError('unsupported extra projectile selector')
    for lane in lanes:
        if not lane.get('direct',{}).get('types') or not lane.get('radial',{}).get('damage'):
            raise ValueError('lane lacks independent direct/radial packet')
    return value

def count(total,shot,offset=.5):
    """Native floor+Bernoulli with deterministic per-trajectory stratified uniforms."""
    if not math.isfinite(total) or total<0:raise ValueError('invalid physical projectile count')
    whole=math.floor(total);fraction=total-whole
    return whole+int(fraction>((float(offset)+int(shot)*GOLDEN)%1))

def plan(config,phase,total,shot=0,offset=.5):
    number=count(total,shot,offset);length=config['length']
    return tuple((int(phase)+i)%length for i in range(number)),(int(phase)+number)%length

def lane_mode(mode,lane):
    value=deepcopy(mode);packet=lane['direct'];amount=sum(packet['types'].values())
    value.pop('multishotCopy',None)
    value['damage']={**value.get('damage',{}),**deepcopy(packet),'total':amount,
        'shares':{k:v/amount for k,v in packet['types'].items()} if amount else {}}
    # Keep raw native iterations for status normalization. Resolver later sets
    # final per-physical-projectile multishot1, after modded shot count is read.
    return value


def merge_life_curves(curves):
    """Mean cumulative damage and total variance of whole lane trajectories.

    Preserve phase/count covariance: summing16curves would multiply damage,
    while simply averaging per-packet variances would discard count uncertainty.
    Variance increments may be negative when paths converge; their cumulative
    sum is the nonnegative variance of cumulative damage at that timestamp.
    """
    if not curves:return []
    from collections import defaultdict
    events=defaultdict(list)
    for branch,curve in enumerate(curves):
        for t,damage,variance,_source in curve:
            events[t].append((branch,damage,variance))
    damage=[0.]*len(curves);variance=[0.]*len(curves);result=[]
    before_mean=before_variance=0.
    for t,rows in sorted(events.items()):
        for branch,hit,spread in rows:
            damage[branch]+=hit;variance[branch]+=spread
        mean=sum(damage)/len(curves)
        total_variance=sum(v+(d-mean)**2 for d,v in zip(damage,variance))/len(curves)
        result.append((t,mean-before_mean,total_variance-before_variance,'projectile-lane-branches'))
        before_mean,before_variance=mean,total_variance
    return result
