"""Probability of no application, beside the expected number of procs."""
import math
import heapq


def no_status_probability(stats, damage_type, forced=None, aim=0.):
    weights={k:max(float(v),0.) for k,v in stats.damage_types.items()}
    total=sum(weights.values())
    share=weights.get(damage_type,0.)/total if total else 0.
    chance=max(float(stats.status_chance),0.)
    multishot=max(float(stats.multishot),0.)
    forced_per=stats.native_forced_procs.get(damage_type,0.)
    independent=max(float(stats.independent_proc_chances.get(damage_type,0.)),0.)
    on_crit=crit_proc_probability(stats,damage_type,forced,aim)
    def zero_rolls(chance):
        whole=math.floor(chance)
        return (1-share)**whole*(1-(chance-whole)*share)
    def zero_for_pellets(pellets):
        if pellets<=0:return 1.
        instances=1 if stats.continuous else pellets
        natural=zero_rolls(chance*pellets) if stats.continuous else zero_rolls(chance)**pellets
        return natural*(1-min(1.,forced_per))**instances*(1-min(1.,independent))**instances*(1-on_crit)**instances
    whole=math.floor(multishot);fraction=multishot-whole
    zero=(1-fraction)*zero_for_pellets(whole)+fraction*zero_for_pellets(whole+1)
    extra=max(float((forced or {}).get(damage_type,0.)),0.)
    return min(1.,max(0.,zero*(1-min(1.,extra))))


def crit_proc_probability(stats, damage_type, forced=None, aim=0.):
    """Per-instance Hunter Munitions chance, mixed over body and weak point."""
    from .damage import crit_proc_probabilities
    if not getattr(stats,'crit_proc_chances',None):
        return 0.
    aim=min(max(float(aim),0.),1.)
    body=crit_proc_probabilities(stats,forced_procs=forced).get(damage_type,0.)
    head=crit_proc_probabilities(stats,weakpoint=True,forced_procs=forced).get(damage_type,0.) if aim else 0.
    return (1-aim)*body+aim*head


class FirstProcClock:
    """First-arrival probabilities during one expected active Heat episode.

    A fractional expected proc is not a guaranteed first application. Each
    cohort starts its own strip clock; proc counts still carry DoT magnitude.
    Refresh/expiry remains the replay's expected entity lifetime.
    """
    def __init__(self):
        self.missing=1.
        self.cohorts=[]
        self.mature=0.

    def add(self,time,probability):
        weight=self.missing*min(1.,max(0.,probability))
        if weight>1e-14:self.cohorts.append((time,weight))
        self.missing-=weight

    def distribution(self,time,scale):
        values=(0.,.15,.30,.40,.50)
        result={.5:self.mature}
        pending=[]
        interval=max(.5*scale,1e-9)
        for born,weight in self.cohorts:
            step=max(0,min(4,int((time-born+1e-9)/interval)))
            result[values[step]]=result.get(values[step],0.)+weight
            if step==4:self.mature+=weight
            else:pending.append((born,weight))
        self.cohorts=pending
        return result

    def strip(self,time,scale):
        return sum(value*weight for value,weight in self.distribution(time,scale).items())


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
