"""Probability of no application, beside the expected number of procs."""
import bisect
import math
import heapq
from collections import deque


def crit_proc_instance_probability(stats, damage_type, aim=0.):
    """Per-instance crit-conditioned proc chance, mixed over body/head aim."""
    if damage_type not in stats.crit_proc_chances:return 0.
    from .damage import crit_proc_probability
    return ((1.-aim)*crit_proc_probability(stats,damage_type,'body')
            +aim*crit_proc_probability(stats,damage_type,'head'))


def no_status_probability(stats, damage_type, forced=None, aim=0.):
    weights={k:max(float(v),0.) for k,v in stats.damage_types.items()}
    total=sum(weights.values())
    share=weights.get(damage_type,0.)/total if total else 0.
    chance=max(float(stats.status_chance),0.)
    multishot=max(float(stats.multishot),0.)
    forced_per=stats.native_forced_procs.get(damage_type,0.)
    independent=max(float(stats.independent_proc_chances.get(damage_type,0.)),0.)
    independent=1-(1-min(1.,independent))*(1-crit_proc_instance_probability(stats,damage_type,aim))
    def zero_rolls(chance):
        whole=math.floor(chance)
        return (1-share)**whole*(1-(chance-whole)*share)
    def zero_for_pellets(pellets):
        if pellets<=0:return 1.
        instances=1 if stats.continuous else pellets
        natural=zero_rolls(chance*pellets) if stats.continuous else zero_rolls(chance)**pellets
        return natural*(1-min(1.,forced_per))**instances*(1-min(1.,independent))**instances
    whole=math.floor(multishot);fraction=multishot-whole
    zero=(1-fraction)*zero_for_pellets(whole)+fraction*zero_for_pellets(whole+1)
    extra=max(float((forced or {}).get(damage_type,0.)),0.)
    return min(1.,max(0.,zero*(1-min(1.,extra))))


HEAT_RAMP=(0.,.15,.30,.40,.50)
HEAT_DECAY=(.5,.4,.3,.15,0.)


def _ramp_index(age,scale):
    return max(0,min(4,int((age+1e-9)/max(.5*scale,1e-9))))


def _decay_steps(level):
    return [v for v in HEAT_DECAY if v<=level+1e-9]


def _decay_index(age,scale,steps):
    return min(int(max(0.,age)/max(1.5*scale,1e-9)),len(steps)-1)


def heat_ramp(age,scale):
    return HEAT_RAMP[_ramp_index(age,scale)]


def heat_decay(level,age,scale):
    steps=_decay_steps(level)
    return steps[_decay_index(age,scale,steps)]


class HeatChains:
    """Expected Heat under refresh-all semantics.

    A real proc refreshes every stack; a chain dies when no proc lands within
    the duration. A fractional expected proc is not a refresh: worlds are
    split by the time of their last real proc. Each proc (absence a, expected
    count n) scales the existing split by a and opens an entry holding the
    p = 1 - a worlds it hits, which carry the surviving stacks plus n; an
    entry expires duration after its proc. Totals still grow by n per proc;
    only expiry differs from refreshing on every fractional proc.

    Armour strip: live worlds ramp by chain start (0.5 s steps), ended worlds
    decay from their level (1.5 s steps), and a restarted world keeps the
    stronger of its decay tail and the new ramp (the tail is held at its
    restart value; a restarted chain cannot end inside the 2-step ramp).
    Entry weights are stored divided by the running product of absences.

    The strip only moves at a world's ramp / decay step: a proc moves ended
    worlds into restarted ones at their current level and an expiry moves
    live worlds into ended ones at theirs. It is kept incrementally on a
    queue of those steps (``strip_full`` is the direct sum it must equal).
    Dead items: [end, scale, {level: weight}, {level: step}, {level: steps}, cleared].
    Restart items: [start, scale, {level: weight}, ramp step].
    """
    def __init__(self):
        self.reset()

    def reset(self):
        self.g=1.
        self.entries=[]
        self.serial=0
        self.weight=self.stacks=self.seeds=0.
        self.young={}
        self.mature=0.
        self.dead=deque()
        self.boost=deque()
        self.scale=1.
        self._clear_incremental(-math.inf)

    def _clear_incremental(self,t):
        self._t=t
        self._events=[]
        self._sequence=0
        self._young_index={}
        self._dead_levels={}
        self._up=self._down=self._tail=0.

    def active(self):
        return bool(self.entries)

    def alive(self):
        return max(0.,self.weight*self.g)

    def count(self):
        return max(0.,self.stacks*self.g)

    def seed(self):
        return max(0.,self.seeds*self.g)

    # incremental strip bookkeeping
    def _push(self,time,kind,item,index):
        self._sequence+=1
        heapq.heappush(self._events,(time,self._sequence,kind,item,index))

    def _schedule_young(self,start):
        index=self._young_index.get(start,0)
        if index<4:
            self._push(start+(index+1)*.5*self.scale,'young',start,index+1)

    def _schedule_dead(self,item,level):
        n=item[3][level]
        if n<len(item[4][level])-1:
            self._push(item[0]+(n+1)*1.5*item[1],'dead',item,level)

    def _schedule_boost(self,item):
        if item[3]<4 and any(level>HEAT_RAMP[item[3]] for level in item[2]):
            self._push(item[0]+(item[3]+1)*.5*item[1],'boost',item,item[3]+1)

    def _due(self,kind,item,index,t):
        if kind=='young':
            return _ramp_index(t-item,self.scale)>=index
        if kind=='dead':
            return _decay_index(t-item[0],item[1],item[4][index])>item[3][index]
        return _ramp_index(t-item[0],item[1])>=index

    def _advance(self,t):
        if t<self._t-1e-9:
            self._rebuild(t)
            return
        retry=[]
        while self._events and self._events[0][0]<=t+1e-7:
            event=heapq.heappop(self._events)
            _,_,kind,item,index=event
            if event[0]>t-1e-7 and not self._due(kind,item,index,t):
                retry.append(event)
                continue
            if kind=='young':
                if item in self.young and self._young_index.get(item,0)<index:
                    old=self._young_index.get(item,0)
                    self._up+=self.young[item]*self.g*(HEAT_RAMP[index]-HEAT_RAMP[old])
                    self._young_index[item]=index
                    self._schedule_young(item)
            elif kind=='dead':
                if item[2].get(index) and not item[5]:
                    steps=item[4][index];n=item[3][index]
                    old,new=steps[n],steps[n+1]
                    w=item[2][index]
                    self._down+=w*(new-old)
                    self._dead_levels[old]=self._dead_levels.get(old,0.)-w
                    if new>0.:self._dead_levels[new]=self._dead_levels.get(new,0.)+w
                    item[3][index]=n+1
                    self._schedule_dead(item,index)
            else:
                old=item[3]
                self._tail+=sum(w*(max(0.,level-HEAT_RAMP[index])-max(0.,level-HEAT_RAMP[old])) for level,w in item[2].items())
                item[3]=index
                self._schedule_boost(item)
        for event in retry:heapq.heappush(self._events,event)
        self._t=max(self._t,t)

    def _rebuild(self,t):
        self._clear_incremental(t)
        g=self.g
        for start,w in self.young.items():
            index=_ramp_index(t-start,self.scale)
            self._young_index[start]=index
            self._up+=w*g*HEAT_RAMP[index]
            self._schedule_young(start)
        self._up+=self.mature*g*.5
        for item in self.dead:
            if item[5]:continue
            for level,w in item[2].items():
                steps=item[4][level];n=_decay_index(t-item[0],item[1],steps)
                item[3][level]=n
                self._down+=w*steps[n]
                if steps[n]>0.:self._dead_levels[steps[n]]=self._dead_levels.get(steps[n],0.)+w
                self._schedule_dead(item,level)
        for item in self.boost:
            item[3]=_ramp_index(t-item[0],item[1])
            self._tail+=sum(w*max(0.,level-HEAT_RAMP[item[3]]) for level,w in item[2].items())
            self._schedule_boost(item)

    # state changes
    def expire(self,t):
        while self.entries and self.entries[0][0]<t-1e-9:
            self._advance(self.entries[0][0])
            end,_,weight,stacks,seeds,young,mature,scale=heapq.heappop(self.entries)
            g=self.g
            self.weight-=weight;self.stacks-=stacks;self.seeds-=seeds;self.mature-=mature
            self._up-=mature*g*.5
            levels={.5:mature} if mature else {}
            for start,w in young.items():
                if start in self.young:
                    self.young[start]-=w
                    self._up-=w*g*HEAT_RAMP[self._young_index.get(start,0)]
                else:
                    self.mature-=w
                    self._up-=w*g*.5
                level=heat_ramp(end-start,scale)
                levels[level]=levels.get(level,0.)+w
            levels={level:w for level,w in levels.items() if level>0. and w>0.}
            if levels:
                item=[end,scale,levels,{level:0 for level in levels},{level:_decay_steps(level) for level in levels},False]
                self.dead.append(item)
                for level,w in levels.items():
                    self._down+=w*level
                    self._dead_levels[level]=self._dead_levels.get(level,0.)+w
                    self._schedule_dead(item,level)
        if not self.entries:
            self.weight=self.stacks=self.seeds=self.mature=0.
            self.young.clear();self._young_index.clear();self._up=0.
        while self.dead and t-self.dead[0][0]>=6*self.dead[0][1]-1e-9:
            self.dead.popleft()
        while self.boost and t-self.boost[0][0]>=2*self.boost[0][1]-1e-9:
            self.boost.popleft()

    def add(self,t,absence,n,seed,duration,scale):
        self.expire(t)
        a=min(1.,max(0.,absence));p=1.-a
        if p<=0.:return
        self._advance(t)
        g=self.g
        for start in [k for k in self.young if t-k>=2*self.scale-1e-9]:
            self.mature+=self.young.pop(start)
            self._young_index.pop(start,None)
        # Ended worlds this proc hits restart holding their current decay.
        tail={level:p*w*g for level,w in self._dead_levels.items() if level>0. and w>0.}
        if tail:
            item=[t,scale,tail,0]
            self.boost.append(item)
            self._tail+=sum(level*w for level,w in tail.items())
            self._schedule_boost(item)
        alive=self.weight*g
        young={k:p*v*g for k,v in self.young.items()}
        young[t]=young.get(t,0.)+p*max(0.,1.-alive)
        values=[p,p*self.stacks*g+n,p*self.seeds*g+seed,young,p*self.mature*g]
        if a<=0.:
            self.entries=[];self.weight=self.stacks=self.seeds=self.mature=0.
            for item in self.dead:item[5]=True
            self.young={};self.dead.clear();self.g=1.
            self._down=0.;self._dead_levels={}
        else:
            self.g=g*a
        q=self.g
        weight,stacks,seeds,young,mature=values[0]/q,values[1]/q,values[2]/q,{k:v/q for k,v in values[3].items()},values[4]/q
        self.serial+=1
        heapq.heappush(self.entries,(t+duration,self.serial,weight,stacks,seeds,young,mature,scale))
        self.weight+=weight;self.stacks+=stacks;self.seeds+=seeds;self.mature+=mature
        for k,v in young.items():self.young[k]=self.young.get(k,0.)+v
        if scale!=self.scale:
            self.scale=scale
            self._rebuild(t)
        elif t not in self._young_index:
            self._young_index[t]=0
            self._schedule_young(t)
        if self.g<1e-100:self._normalize()

    def _normalize(self):
        q=self.g
        self.entries=[(e[0],e[1],e[2]*q,e[3]*q,e[4]*q,{k:v*q for k,v in e[5].items()},e[6]*q,e[7]) for e in self.entries]
        heapq.heapify(self.entries)
        self.weight*=q;self.stacks*=q;self.seeds*=q;self.mature*=q
        self.young={k:v*q for k,v in self.young.items()}
        for item in self.dead:
            for level in item[2]:item[2][level]*=q
        self.g=1.
        self._rebuild(self._t)

    def strip(self,t):
        self._advance(t)
        return min(.5,max(0.,self._up+self._down*self.g+self._tail))

    def strip_full(self,t):
        """Direct sum over every world (reference for the incremental strip)."""
        g=self.g
        up=sum(w*heat_ramp(t-start,self.scale) for start,w in self.young.items())*g+self.mature*g*.5
        down=sum(w*heat_decay(level,t-item[0],item[1]) for item in self.dead if not item[5] for level,w in item[2].items())*g
        tail=sum(w*max(0.,level-heat_ramp(t-item[0],item[1])) for item in self.boost for level,w in item[2].items())
        return min(.5,max(0.,up+down+tail))


def capped_stack_add(items, absence, count, instance, cap=10):
    """Add one application to a capped pool that drops the oldest stack.

    Each instance keeps the distribution of how many newer stacks arrived
    (index k), alive while k stays below its limit. A fractional expected
    application is not a certain one: with p = 1 - absence it adds count / p
    stacks (split between the neighbouring integers), else none. Certain
    single procs reduce to trimming the oldest. Gas lifetimes under the cap
    are random, so ticks scale by survival instead of a fixed trim.
    """
    p = min(1., max(0., 1. - absence))
    if p <= 0. or count <= 0.:
        return False
    size = count / p
    low = int(math.floor(size + 1e-9))
    frac = max(0., size - low)
    shifts = [(0, 1. - p)] if p < 1. else []
    if low and frac < 1. - 1e-9:
        shifts.append((low, p * (1. - frac)))
    if frac > 1e-9:
        shifts.append((low + 1, p * frac))
    for item in items:
        dist = item['dist']
        limit = len(dist)
        new = [0.] * limit
        for shift, weight in shifts:
            if weight <= 0.:
                continue
            for k in range(limit - shift):
                new[k + shift] += weight * dist[k]
        item['dist'] = new
    items[:] = [item for item in items if sum(item['dist']) > 1e-9]
    instance['dist'] = [1.] + [0.] * max(0, cap - int(math.ceil(size - 1e-9)))
    items.append(instance)
    return True


def stack_alive(instance):
    dist = instance.get('dist')
    return 1. if dist is None else sum(dist)


def _arrival_kernel(absence, count, cap):
    """Stacks one application adds: none w.p. absence, else count / p split
    between the neighbouring integers (the same split as capped_stack_add)."""
    p = min(1., max(0., 1. - absence))
    if p <= 0. or count <= 0.:
        return None
    size = count / p
    low = int(math.floor(size + 1e-9))
    frac = max(0., size - low)
    kernel = {}
    for shift, weight in ((0, 1. - p), (low, p * (1. - frac)), (low + 1, p * frac)):
        if weight > 0.:
            kernel[min(shift, cap)] = kernel.get(min(shift, cap), 0.) + weight
    return tuple(kernel.items())


def _fold(dist, kernel, cap):
    out = [0.] * (cap + 1)
    for shift, weight in kernel:
        for k, value in enumerate(dist):
            if value:
                out[min(k + shift, cap)] += weight * value
    return out


class CappedPool:
    """Exact live stacks of a replace-oldest pool with independent durations.

    With one duration, expiry follows arrival order and the live count is
    min(N, cap), N the stacks that arrived within the duration. The window's
    distribution of min(N, cap) is kept on a two-stack queue of truncated
    convolutions (min(a + b, cap) is associative), so an arrival, an expiry
    and a query are O(cap) / amortised O(cap) / O(cap^2). An expected count
    put into a nonlinear effect (Viral's first stack doubles, later ones add
    25 %) overstates it by Jensen's inequality; P(N >= 1) and E[min(N, cap)]
    give the exact expectation of every first-stack-plus-linear effect.
    Expiry is checked at the queue front, so a shorter later duration waits
    for the older stack ahead of it.
    """
    def __init__(self, cap):
        self.cap = int(cap)
        self.reset()

    def reset(self):
        self.front = []  # oldest last: (end, kernel, aggregate of it and newer front items)
        self.back = []
        self.back_dist = [1.] + [0.] * self.cap
        self._dist = self._stats = None
        self.version = getattr(self, 'version', 0) + 1

    def __bool__(self):
        return bool(self.front or self.back)

    def add(self, end, absence, count):
        kernel = _arrival_kernel(absence, count, self.cap)
        if kernel is None:
            return False
        self.back.append((end, kernel))
        self.back_dist = _fold(self.back_dist, kernel, self.cap)
        self._dist = self._stats = None
        self.version += 1
        return True

    def _transfer(self):
        dist = [1.] + [0.] * self.cap
        while self.back:
            end, kernel = self.back.pop()
            dist = _fold(dist, kernel, self.cap)
            self.front.append((end, kernel, dist))
        self.back_dist = [1.] + [0.] * self.cap

    def expire(self, t):
        while True:
            if not self.front:
                if not self.back or self.back[0][0] >= t - 1e-9:
                    return
                self._transfer()
            if self.front[-1][0] >= t - 1e-9:
                return
            self.front.pop()
            self._dist = self._stats = None
            self.version += 1

    def distribution(self):
        """P(min(N, cap) = k) for k = 0..cap."""
        if self._dist is None:
            b = self.back_dist
            if not self.front:
                self._dist = list(b)
            else:
                cap = self.cap
                out = [0.] * (cap + 1)
                for i, x in enumerate(self.front[-1][2]):
                    if x:
                        for j, y in enumerate(b):
                            if y:
                                out[min(i + j, cap)] += x * y
                self._dist = out
        return self._dist

    def stats(self):
        """(P(N >= 1), E[min(N, cap)])."""
        if self._stats is None:
            dist = self.distribution()
            self._stats = (1. - dist[0], sum(k * v for k, v in enumerate(dist)))
        return self._stats


class StatusPresence:
    """P(at least one unexpired application), not E[count] > 0."""
    def __init__(self):
        self.events=[]
        self.log_absence=0.
        self.certain=0
        self.serial=0

    def add(self,expiry,absence):
        if absence>=1.:return
        value=math.log(absence) if absence>0. else None
        self.serial+=1
        heapq.heappush(self.events,(expiry,self.serial,value))
        if value is None:self.certain+=1
        else:self.log_absence+=value

    def probability(self,time):
        while self.events and self.events[0][0]<time-1e-9:
            _,_,value=heapq.heappop(self.events)
            if value is None:self.certain-=1
            else:self.log_absence-=value
        return 1. if self.certain else -math.expm1(min(self.log_absence,0.))


DOT_TICK_SECONDS=1.


def crit_cv2(stats,aim):
    """Squared coefficient of variation of one direct damage instance.

    Crit tiers are the dominant per-hit spread. Multishot pellets roll
    independently; a merged beam tick rolls once.
    """
    cm=max(float(stats.crit_multiplier),1.)-1.
    weak=stats.weakpoint_crit_chance_bonus+stats.base_crit_chance*stats.weakpoint_crit_chance_relative
    mean=square=0.
    for weight,chance in ((1.-aim,stats.crit_chance*stats.bodyshot_crit_multiplier),(aim,stats.crit_chance+weak)):
        if weight<=0.:continue
        chance=max(0.,chance);f=chance-math.floor(chance)
        m=1.+chance*cm
        mean+=weight*m;square+=weight*(m*m+f*(1.-f)*cm*cm)
    if mean<=0.:return 0.
    pellets=1. if stats.continuous else max(float(stats.multishot),1.)
    return max(0.,square/(mean*mean)-1.)/pellets


class KillAttribution:
    """P(weak-point kill) from where random damage would cross zero health.

    The expected replay crosses zero at one deterministic event. Each damage
    event carries its own variance (crit tiers, Poisson proc counts); their
    sum spreads the remaining health before death. Event i is the killing
    blow with P(remaining after i <= 0 < remaining before i) under a normal
    spread. The last DoT tick period is extended periodically for kills the
    expected path did not reach. Zero spread is the exact crossing; a wide
    spread tends to each source's share of the damage flow.
    """
    def __init__(self,period,horizon=3,limit=4096,interval=None):
        self.period=period
        self.interval=interval or period  # attack interval: spacing of a lone event
        self.horizon=horizon
        self.rows=deque(maxlen=limit)
        self.reset()

    def reset(self):
        self.rows.clear()
        self.health_variance=0.
        self.earlier=[0.,0.,math.inf,-math.inf]  # variance, damage, first, last

    def add(self,time,earlier,health,cv2,weak,direct=False):
        cv2=max(0.,cv2)
        if earlier>0.:
            e=self.earlier
            e[0]+=earlier*earlier*cv2;e[1]+=earlier;e[2]=min(e[2],time);e[3]=max(e[3],time)
        if health>0.:
            self.health_variance+=health*health*cv2
            # Variance of the cumulative damage up to and including this event.
            self.rows.append((time,health,weak,self.health_variance,health*health*cv2,direct))

    def weak(self,time,remaining):
        return self.crossing(time,remaining)[0]

    def crossing(self,time,remaining,resume=None):
        """(P(weak-point kill), renewal shift) for a kill at ``time``.

        ``remaining`` is the expected health just before the killing event;
        ``resume`` is when the weapon lands its next direct hit (after a
        reload, say), if known.
        Event k has killed by then with P(noise_k >= expected health after k),
        noise_k being the spread of the cumulative damage up to k (its own
        variance, not the total's: a late lump must not widen earlier
        crossings). The renewal shift is E[next target's first hit] minus the
        expected path's; it smooths shots-to-kill steps (near a breakpoint the
        chance that an earlier event already killed rises continuously) and
        is zero when a reload decides when the next life starts.
        """
        if not self.rows:return 0.,0.
        recent=[r for r in self.rows if r[0]>time-self.period+1e-9]  # One period: (t-W, t].
        offset=0.
        variance_e,damage_e,first,last=self.earlier
        if damage_e>0. and variance_e>0.:
            # An earlier pool's spread shifts when health starts taking damage.
            rate_e=damage_e/max(last-first,self.period)
            rate_h=sum(r[1] for r in recent)/self.period
            offset=variance_e*(rate_h/rate_e)**2
        if self.health_variance+offset<=0.:return self.rows[-1][2],0.
        def dead(after,variance):  # P(cumulative noise >= expected health after the event)
            sigma=math.sqrt(max(variance+offset,1e-300))
            return .5*math.erfc(after/sigma/math.sqrt(2.))
        # (time, P(dead by then), weak) for events around the crossing.
        events=[]
        after=remaining-self.rows[-1][1]
        for when,damage,w,variance,_,_ in reversed(self.rows):
            if after>8.*math.sqrt(variance+offset):break
            events.append((when,dead(after,variance),w))
            after+=damage
        events.reverse()
        # The recent events repeat at their own cadence (a short life may span
        # less than the attribution period), each adding its own variance.
        # Direct hits cannot land before the weapon fires again: a reload
        # delays them, DoT ticks keep their clock.
        times=[r[0] for r in recent]
        gap=(times[-1]-times[0])/(len(times)-1) if len(times)>1 else self.interval
        cycle_length=times[-1]-times[0]+gap
        delay=max(0.,resume-(time+gap)) if resume is not None else 0.
        future=sorted((when+cycle*cycle_length+(delay if direct else 0.),damage,w,own,direct)
                      for cycle in range(1,self.horizon+1)
                      for when,damage,w,_,own,direct in recent)
        after=remaining-self.rows[-1][1]
        variance=self.health_variance
        for when,damage,w,own,_ in future:
            after-=damage;variance+=own
            events.append((when,dead(after,variance),w))
        # The next target takes its first damage at the first direct hit after
        # the kill, so a kill moves the following lives by the change in that
        # time, not by the change in the kill time itself (a kill just before a
        # reload saves nothing).
        hits=sorted({r[0] for r in self.rows if r[5]}|{f[0] for f in future if f[4]}
                    |({resume} if resume is not None else set()))
        def next_hit(when):
            index=bisect.bisect_right(hits,when+1e-9)
            return hits[index] if index<len(hits) else when+gap
        total=weak=start=0.;reached=0.
        for when,probability,w in events:
            probability=max(probability,reached)  # cumulative: dead stays dead
            p=probability-reached;reached=probability
            total+=p;weak+=p*w;start+=p*next_hit(when)
        if total<=0.:return self.rows[-1][2],0.
        return min(1.,max(0.,weak/total)),start/total-next_hit(time)
