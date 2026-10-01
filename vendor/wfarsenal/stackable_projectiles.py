"""Stackable projectile clocks for an explicitly chosen common impact point."""
from __future__ import annotations

from dataclasses import dataclass, replace
import math


@dataclass
class Group:
    id: int
    profile: dict
    parts: dict
    generation: int
    stacks: float
    weight: float
    expires: float
    token: int = 0
    singularity: bool = False
    alive: bool = True


class StackableProjectiles:
    def __init__(self, state, push, deliver, trace=None):
        self.state, self.push, self.deliver = state, push, deliver
        self.trace = trace
        self.groups = {}
        self.active = None
        self.sequence = 0
        self.shots = 0
        self.stats = dict(deployed=0.,merged=0.,explosions=0,singularities=0,childProjectiles=0)

    def record(self, time, kind, group, **values):
        if self.trace is not None:
            self.trace.append(dict(time=time,kind=kind,group=group.id,stacks=group.stacks,
                                   targetGeneration=group.generation,**values))

    def schedule(self, time, action, group):
        self.push(time,'stackable-life',(group.id,group.token,action),group.generation)

    def hit(self, group, kind, time, scale=1., weight=None):
        part = group.parts.get(kind)
        if part is None:
            return
        if scale!=1.:
            part = replace(part,damage_types={k:v*scale for k,v in part.damage_types.items()},
                           dot_base_damage=part.dot_base_damage*scale if part.dot_base_damage is not None else None)
        part = replace(part,multishot=group.weight if weight is None else weight)
        self.deliver(part,time)
        self.record(time,kind,group,damageScale=scale,hitWeight=part.multishot)

    def create(self, time, profile, parts, generation, stacks=1., weight=1.):
        self.sequence += 1
        lifetime = profile['embedSeconds'] if profile['kind']=='stug' else profile['maxLife']
        group = Group(self.sequence,profile,parts,generation,stacks,weight,time+lifetime)
        self.groups[group.id] = group
        self.schedule(group.expires,'explode',group)
        if profile['kind']=='stug':
            self.hit(group,'embed',time,stacks)
            self.schedule(time+profile['embedInterval'],'embed',group)
        self.record(time,'deploy',group)
        return group

    def merge(self, time, group, amount):
        profile = group.profile
        previous = group.stacks
        if previous>=profile['maxStack']:
            self.record(time,'absorbed-at-cap',group,incoming=amount)
            return
        group.stacks = min(profile['maxStack'],previous+amount)
        added = group.stacks-previous
        self.stats['merged'] += added*group.weight
        self.record(time,'merge',group,addedStacks=added)
        if profile['kind'] in {'simulor','mq'} and added>0:
            low, high = profile['mergeDamage']
            native = sum(profile['merge']['damage'].values())
            override = low+(high-low)*added/profile['maxStack']
            scale = override/native if override>0 and native else 1.
            self.hit(group,'merge',time,scale)
            if profile['kind']=='simulor' and not group.singularity and group.stacks>=profile['attachAtStack']:
                group.singularity = True
                self.stats['singularities'] += 1
                self.record(time,'singularity-created',group)
                self.schedule(time+profile['singularity']['interval'],'singularity',group)
        if profile['resetLifeOnStack']:
            group.expires = time+profile['stackedLife']
            group.token += 1
            self.schedule(group.expires,'explode',group)
            if group.singularity:
                self.schedule(time+profile['singularity']['interval'],'singularity',group)
        if profile['kind']=='stug' and group.stacks>=profile['maxStack']:
            self.explode(time,group)

    def deploy(self, time, active, generation):
        profile, parts = active._stackable
        quantity = max(float(active.multishot),0.)
        self.stats['deployed'] += quantity
        self.shots += 1
        isolated = self.state.get('projectileMode')=='isolated'
        # Fractional multishot is an expected deployment mass. Each full
        # projectile remains a real merge event; isolated fractions keep a
        # weighted independent lifecycle instead of rounding to a free orb.
        full = int(quantity)
        fractions = [1.]*full + ([quantity-full] if quantity-full>1e-9 else [])
        for weight in fractions:
            group = self.groups.get(self.active)
            if (isolated or group is None or not group.alive or group.generation!=generation
                    or group.profile['kind']!=profile['kind']):
                initial = profile.get('initialStack',1.)
                group = self.create(time,profile,parts,generation,initial if isolated else initial*weight,weight if isolated else 1.)
                self.active = group.id
            else:
                self.merge(time,group,weight*profile.get('initialStack',1.))
        batch = self.state.get('detonateAfterShots')
        if profile['kind']=='simulor' and self.state.get('projectileMode')=='manual' and batch and self.shots>=batch:
            self.shots = 0
            wait = self.state.get('detonationWaitSeconds',0.)
            for group in tuple(self.groups.values()):
                if group.alive and group.generation==generation:
                    self.schedule(time+wait,'manual',group)
            return wait
        return 0.

    def explode(self,time,group):
        if not group.alive:
            return
        group.alive = False
        self.stats['explosions'] += 1
        self.hit(group,'explosion',time,group.stacks)
        profile = group.profile
        if profile.get('child'):
            count = min(profile['childMaxCount'],max(profile['childMinCount'],math.ceil(
                profile['childMaxCount']*group.stacks/profile['maxStack'])))
            self.stats['childProjectiles'] += count
            self.record(time,'children-created',group,count=count)
            hits = min(count,int(self.state.get('stugChildHits',0)))
            bounces = min(profile['childBounceCount'],int(self.state.get('stugBounceHits',0)))
            interval = self.state.get('stugBounceDelaySeconds',0.)
            lifetime = min(profile['childLife'],self.state.get('stugChildDetonateSeconds',profile['childLife']))
            for n in range(bounces):
                if (n+1)*interval<lifetime:
                    self.push(time+(n+1)*interval,'stackable-child',(group.id,1.,hits),group.generation)
            self.push(time+lifetime,'stackable-child',
                      (group.id,profile['childDeathMultiplier'],hits),group.generation)
        if profile.get('kind')=='mq' and self.state.get('mqAugmentEquipped'):
            if group.parts.get('orbRadial') is not None:
                self.hit(group,'orbRadial',time)
            else:
                self.record(time,'orb-radial-unresolved',group)
        if self.active==group.id:
            self.active = None

    def event(self,time,payload,child=False):
        identity,token,action = payload
        group = self.groups.get(identity)
        if group is None:
            return
        if child:
            if action:
                self.hit(group,'child',time,token,weight=action*group.weight)
            return
        if not group.alive or token!=group.token:
            return
        if action in {'explode','manual'}:
            self.explode(time,group)
        elif action=='embed' and time<group.expires:
            self.hit(group,'embed',time,group.stacks)
            self.schedule(time+group.profile['embedInterval'],'embed',group)
        elif action=='singularity' and time<group.expires:
            interval = group.profile['singularity']['interval']
            self.hit(group,'singularity',time,interval)
            self.schedule(time+interval,'singularity',group)
