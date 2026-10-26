"""Secondary Enervate: joint probability state, not a timed average buff.

Raw CritOnHit parameters identify the adapter. Discrete grouped-hit semantics
and a 1/30s minimum interval are explicit calibration assumptions; they are
not claimed as a game capture. Damage uses the PRE-hit distribution.
"""
from __future__ import annotations
from collections import defaultdict
from collections.abc import Mapping
import math

PATH = '/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryCritOnHit'
IGNORED_ALT = '/Lotus/Weapons/Tenno/Pistols/SundialGun/SundialPistol'
ASSUMPTIONS = ['enervate-grouped-hit-any-big-crit', 'enervate-gain-then-reset-after-damage',
               'enervate-minimum-interval-30hz', 'enervate-state-target-correlation-expected',
               'enervate-blast-hit-probability-with-cooldown-branches']


def configuration(record, rank):
    if record.get('path') != PATH or type(rank) is not int or not 0 <= rank <= 5:
        return None
    script = (record.get('runtimeScripts') or {}).get('apply', {})
    constants = {'_critChanceBase': .1, '_critChancePerLevel': 0,
                 '_numTieredCritsToResetBase': 1, '_numTieredCritToResetPerLevel': 1,
                 '_resetCritTier': 1}
    if (script.get('Script') != 'CritOnHit.lua' or script.get('Function') != 'OnHit'
            or any(script.get(k) != v for k,v in constants.items())
            or script.get('_ignoreAltFireWeapons') != [IGNORED_ALT]):
        return None
    return dict(id=PATH, label=record.get('nameZh') or 'Secondary Enervate',
                rank=rank, resetAfter=rank+1, flatPerStack=.1, minInterval=1/30)


def big_crit_probability(chance, promotion=0):
    """Tier >=2, including one-tier promotion of an already critical hit."""
    chance=max(0.0,chance);promotion=min(1.0,max(0.0,promotion))
    return min(1.0,max(0.0,chance-1)) + min(1.0,max(0.0,chance),max(0.0,2-chance))*promotion


def any_big_probability(chance, pellets, promotion=0):
    """Integer pellets plus one Bernoulli fractional pellet, never x**fraction."""
    p=big_crit_probability(chance,promotion)
    return any_probability(p,pellets)


def any_probability(p,pellets):
    n=max(0.0,pellets);whole=int(n)
    return 1-(1-p)**whole*(1-(n-whole)*p)


class EnervateState:
    def __init__(self, config):
        self.config=config
        self.last=-math.inf
        self.hits=0
        self.resets=0.0
        self.series=[]
        self.uptimes=[]
        self.fixed=config.get('fixedStacks')
        self.uptime=min(1.0,max(0.0,config.get('uptime',1.0)))
        self.states={(0,0):1.0}
        self._timed_states=None
        if self.fixed is not None:
            value=max(0.0,float(self.fixed));lo=int(value);frac=value-lo
            self.states={(lo,0):1-frac}
            if frac:self.states[(lo+1,0)]=frac

    def marginal(self):
        out=defaultdict(float)
        for (s,_),p in self.states.items():out[s]+=p
        return dict(out)

    def damage_marginal(self):
        weights={s:p*self.uptime for s,p in self.marginal().items()}
        weights[0]=weights.get(0,0)+1-self.uptime
        return {s:p for s,p in weights.items() if p>0}

    def advance(self,t,probabilities=None,*,gain=True,event_probability=1.0):
        event_probability=min(1.0,max(0.0,float(event_probability)))
        if not event_probability:
            return
        if event_probability < 1.0 or self._timed_states is not None:
            return self._advance_probabilistic(t,probabilities,gain,event_probability)
        if (not gain or self.fixed is not None or self.uptime==0
                or t-self.last<self.config['minInterval']-1e-9):
            return
        self.last=t;self.hits+=1
        following=defaultdict(float)
        for (s,b),mass in self.states.items():
            prob=min(1.0,max(0.0,(probabilities or {}).get(s,0.0)))
            following[(s+int(gain),b)]+=mass*(1-prob)
            if b+1>=self.config['resetAfter']:
                following[(0,0)]+=mass*prob;self.resets+=mass*prob
            else:following[(s+int(gain),b+1)]+=mass*prob
        self.states={k:v for k,v in following.items() if v>0}

    def _advance_probabilistic(self,t,probabilities,gain,event_probability):
        """A fractional proc is a possible hit, not a certain cooldown reset.

        Keep the cooldown clock coupled to each branch. Eligible old clocks
        are equivalent for every future event and collapse to -inf, bounding
        the history without dropping probability mass.
        """
        if not gain or self.fixed is not None or self.uptime==0:
            return
        states=self._timed_states
        if states is None:
            states={(s,b,self.last):mass for (s,b),mass in self.states.items()}
        following=defaultdict(float)
        for (s,b,last),mass in states.items():
            if t-last<self.config['minInterval']-1e-9:
                following[(s,b,last)]+=mass
                continue
            following[(s,b,-math.inf)]+=mass*(1-event_probability)
            accepted=mass*event_probability
            self.hits+=accepted
            probability=min(1.0,max(0.0,(probabilities or {}).get(s,0.0)))
            following[(s+1,b,t)]+=accepted*(1-probability)
            if b+1>=self.config['resetAfter']:
                following[(0,0,t)]+=accepted*probability
                self.resets+=accepted*probability
            else:
                following[(s+1,b+1,t)]+=accepted*probability
        self._timed_states={k:v for k,v in following.items() if v>0}
        totals=defaultdict(float)
        for (s,b,_),mass in self._timed_states.items():totals[s,b]+=mass
        self.states=dict(totals)
        self.last=max((key[2] for key in self._timed_states),default=-math.inf)

    def snapshot(self):
        return dict(stacks=sum(s*p for s,p in self.damage_marginal().items()),
                    bigCrits=sum(b*p for (_,b),p in self.states.items()),
                    resets=self.resets,acceptedHits=self.hits,
                    probabilityMass=sum(self.states.values()),states=len(self.states))

    def sample(self):
        self.series.append(self.snapshot()['stacks'])
        self.uptimes.append(1-self.damage_marginal().get(0,0.0))

    def summary(self):
        return {**self.config,**self.snapshot(), 'kind':'enervate', 'maxStacks':None,
                'duration':None,'series':self.series,
                'avgStacks':sum(self.series)/len(self.series) if self.series else 0,
                'uptime':sum(self.uptimes)/len(self.uptimes) if self.uptimes else 0,
                'mode':'explicit-fixed' if self.fixed is not None else 'joint-probability-events',
                'assumptions':ASSUMPTIONS}
