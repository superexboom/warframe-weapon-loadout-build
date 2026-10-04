"""Raw-data adapters: build 2026.09.22.16.46; Encumber pool: WFSim b98b3d4.
Fortifier follows raw MULTIPLY (R5 x8), not reference YAML inferred x9.
"""
from __future__ import annotations
import math
ENCUMBER = '/Lotus/Upgrades/CosmeticEnhancers/Utility/ExtraProcOnProc'
FORTIFIER = '/Lotus/Upgrades/CosmeticEnhancers/Offensive/OverguardSteal'
CRYOGENIC = '/Lotus/Upgrades/CosmeticEnhancers/Offensive/SecondaryColdOnPuncture'
EMPOWERED = '/Lotus/Upgrades/CosmeticEnhancers/Zariman/SecondaryOnStatusProcBonusDamage'
STATUS_POOL = ('DT_IMPACT','DT_PUNCTURE','DT_SLASH','DT_FIRE','DT_FREEZE',
               'DT_ELECTRICITY','DT_POISON','DT_EXPLOSION','DT_CORROSIVE',
               'DT_MAGNETIC','DT_VIRAL','DT_GAS','DT_RADIATION')

def configuration(record, rank):
    if isinstance(rank,bool) or not isinstance(rank,int) or not 0 <= rank <= 5:return None
    if record.get('path') == ENCUMBER:
        fx=record.get('effects') or []
        if (len(fx)==1 and fx[0].get('upgradeType')=='WEAPON_PROC_ON_PROC_CHANCE'
            and fx[0].get('operation')=='ADD'
            and math.isclose(float(fx[0].get('valuePerRank',0)),.04,abs_tol=1e-8)):
            return dict(kind='encumber',chance=.04*(rank+1))
    if record.get('path') == CRYOGENIC:
        script=(record.get('runtimeScripts') or {}).get('apply',{})
        expected={'Script':'AoeOnCondition.lua','Function':'ApplyUpgrade',
                  '_radiusBase':10,'_radiusPerLevel':1,'_damageBase':0,'_damagePerLevel':0,
                  '_damageProcTypes':['DT_FREEZE'],'_numDamageProcsToSpreadAtLevel':[1,1,2,2,3,3]}
        conditions=record.get('conditionalEffects') or []
        if (all(script.get(k)==v for k,v in expected.items()) and len(conditions)==1
                and conditions[0].get('conditions')==['OnPunctureProcCondition']):
            return dict(kind='cryogenic',coldStacks=expected['_numDamageProcsToSpreadAtLevel'][rank],radius=10+rank)
    if record.get('path') == EMPOWERED:
        script=(record.get('runtimeScripts') or {}).get('apply',{})
        conditions=record.get('conditionalEffects') or []
        values=[250,350,450,550,650,750]
        if (script.get('Script')=='SecondaryOnStatusProcBonusDamage.lua'
                and script.get('Function')=='ModApplied' and script.get('_damageAmounts')==values
                and len(conditions)==1 and conditions[0].get('conditions')==[
                    '/Lotus/Upgrades/CosmeticEnhancers/Offensive/OnStatusProcALLCondition']):
            return dict(kind='empowered',damage=values[rank])
    if record.get('path') == FORTIFIER:
        script=(record.get('runtimeScripts') or {}).get('apply',{})
        fx=record.get('extraEffects') or []
        if (script.get('Script')=='OverguardLifesteal.lua'
            and script.get('Function')=='ApplyUpgrade'
            and math.isclose(float(script.get('_overguardSteal',0)),.01,abs_tol=1e-8)
            and script.get('_overguardLimit')==15000
            and len(fx)==1 and fx[0].get('upgradeType')=='WEAPON_DAMAGE_AMOUNT_TO_OVERGUARD'
            and fx[0].get('operation')=='MULTIPLY' and fx[0].get('valuePerRank')==3):
            return dict(kind='fortifier',multiplier=3.+rank,steal=.01,cap=15000.)
    return None

def encumber_roll(stats,chance,forced_procs=None,*,aim=0.):
    """One-success probability and conditional beam seed, over integer rolls.
    Extra statuses never feed back into their own trigger.
    """
    m=max(float(stats.multishot),0.);low=math.floor(m);frac=m-low
    q_ind=1.
    for dtype,p in stats.independent_proc_chances.items():
        if dtype in STATUS_POOL:q_ind*=1-min(max(float(p),0.),1.)
    for dtype,n in stats.native_forced_procs.items():
        if dtype in STATUS_POOL:q_ind*=1-min(max(float(n),0.),1.)
    # Hunter Munitions pushes its Slash before Encumber reads the pellet.
    from .proc_probability import crit_proc_probability
    for dtype in getattr(stats,'crit_proc_chances',None) or ():
        if dtype in STATUS_POOL:q_ind*=1-crit_proc_probability(stats,dtype,forced_procs,aim)
    forced=min(sum(max(float(n),0.) for k,n in (forced_procs or {}).items() if k in STATUS_POOL),1.)
    sc=max(float(stats.status_chance),0.) if any(stats.damage_types.get(k,0)>0 for k in STATUS_POOL) else 0.
    probability=seed=0.
    for pellets,weight in ((low,1-frac),(low+1,frac)):
        if pellets<=0 or weight<=0:continue
        if stats.continuous:
            source=1-(1-min(sc*pellets,1.))*q_ind*(1-forced)
            p=chance*source;merged=pellets
        else:
            source=1-(1-min(sc,1.))*q_ind
            p=1-(1-chance*source)**pellets
            p=1-(1-p)*(1-chance*forced*(1-source))
            merged=1.
        probability+=weight*p;seed+=weight*p*merged
    return probability,seed/probability if probability else 1.
