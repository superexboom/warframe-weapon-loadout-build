from copy import deepcopy
from collections import Counter
import random
import pytest
import app
from wfarsenal.enervate import configuration, EnervateState, any_big_probability, big_crit_probability, PATH
from wfarsenal.damage import Scenario, ModEffect, ModEffectList, apply_mods, arcane_effects
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tools.audit_optimizer_events import evaluate_payload


def record():return next(a for a in app.EXPORTS['arcanes'] if a['path']==PATH)

def cfg(rank=5,**kw):return {**configuration(record(),rank),**kw}

def run(chance=.1,rank=5,rate=10,duration=3,**kw):
    state=EnervateState(cfg(rank,**kw))
    for i in range(int(rate*duration)):
        state.advance(i/rate,{s:any_big_probability(chance+s*.1,1) for s in state.marginal()})
    return state


def test_adapter_rejects_drift():
    raw=deepcopy(record());raw['runtimeScripts']['apply']['_critChanceBase']=.2
    assert configuration(raw,5) is None
    assert configuration(record(),True) is None
    assert configuration({**record(),'path':PATH+'Dev'},5) is None


@pytest.mark.parametrize('rank',range(6))
def test_reset_threshold_and_rank_independent_flat_bonus(rank):
    state=EnervateState(cfg(rank))
    for i in range(rank):state.advance(i*.1,{s:1 for s in state.marginal()})
    assert state.snapshot()['stacks']==rank
    state.advance(rank*.1,{s:1 for s in state.marginal()})
    assert state.states=={(0,0):1}
    assert state.resets==1


def test_rate_limit_no_timeout_and_no_synthetic_stack_cap():
    state=EnervateState(cfg())
    for i in range(3000):state.advance(i/300)
    assert state.hits==300
    assert state.snapshot()['stacks']==300
    state.advance(1000)
    assert state.snapshot()['stacks']==301


def test_multishot_uses_probability_of_any_big_crit_in_group():
    assert any_big_probability(1.5,2.5)==pytest.approx(1-.5**2*.75)
    assert any_big_probability(1.5,2.5)!=pytest.approx(1-.5**2.5)
    assert big_crit_probability(.5,1)==.5
    assert big_crit_probability(1.5,.5)==.75
    state=EnervateState(cfg(0));state.advance(0,{0:.75})
    assert state.states=={(1,0):.25,(0,0):.75}


def test_joint_distribution_matches_independent_seeded_simulation():
    expected=run(chance=.1,rank=5,rate=10,duration=4)
    rng=random.Random(12648430);counts=Counter();resets=0
    for _ in range(30000):
        stacks=big=0
        for _ in range(40):
            orange=rng.random()<min(1,max(0,.1+.1*stacks-1))
            stacks+=1
            if orange:
                big+=1
                if big==6:stacks=big=0;resets+=1
        counts[(stacks,big)]+=1
    assert sum(expected.states.values())==pytest.approx(1,abs=1e-12)
    assert expected.snapshot()['stacks']==pytest.approx(sum(s*n for (s,_),n in counts.items())/30000,abs=.08)
    assert expected.resets==pytest.approx(resets/30000,abs=.02)


def test_negative_crit_and_fixed_zero_coverage():
    state=run(chance=-2,rank=0,rate=10,duration=2)
    assert state.snapshot()['stacks']==20
    assert state.resets==0
    frozen=run(fixedStacks=12,uptime=0)
    assert frozen.damage_marginal()=={0:1}
    assert frozen.hits==0


def weapon():
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Lato'))
    w['magazineSize']=1000;w['fireModes'][0]['fireRate']=10
    return w


def execute(equip=True,override=None,duration=3):
    w=weapon();fx=ModEffectList([ModEffect('WEAPON_PROC_CHANCE','SET',0)])
    scene=Scenario(trigger_policy='emergent')
    st=apply_mods(w,fx,scenario=scene)
    combat=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=scene),[],[(record(),5,override)] if equip else [])
    target=dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1,faction='')
    return replay(st,target,attacks_per_second=10,window_seconds=duration,combat=combat,trigger_sources=combat['trigger_sources'])


def test_replay_builds_after_first_hit_and_contributes():
    off=execute(False);on=execute()
    assert on['totalWindowDamage']>off['totalWindowDamage']
    assert on['shots']==off['shots']
    assert on['enervate']['resets']>0
    assert on['timeline'][0]['enervate']['acceptedHits']>0
    assert not any('CritOnHit' in s or PATH in s for s in on['unsupported'])
    assert execute(duration=.09)['totalWindowDamage']==pytest.approx(execute(False,duration=.09)['totalWindowDamage'])
    assert execute(override={'uptime':0})['totalWindowDamage']==pytest.approx(off['totalWindowDamage'])
    assert execute(override={'stacks':0})['totalWindowDamage']==pytest.approx(off['totalWindowDamage'])


def test_explicit_stacks_are_flat_not_relative_or_rank_scaled():
    w=weapon()
    for rank in range(6):
        base=apply_mods(w,[]);boosted=apply_mods(w,arcane_effects(record(),rank,stacks=7))
        assert boosted.crit_chance-base.crit_chance==pytest.approx(.7)


def test_catalog_does_not_claim_fake_ten_seconds_or_hundred_stack_limit():
    row=app.MANUAL_ARCANES_BY_PATH[PATH]
    assert row['trigger']['duration'] is None and row['trigger']['maxStacks'] is None
    assert row['eventModel']=='enervate-joint-probability'


def test_manual_search_and_removal_contribution():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Prisma Dual Decurions')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=PATH,rank=5)],enemy=app._BENCHMARK_ENEMY_PATH,
           level=9999,steelPath=True,headshotChance=1,aiming=True,triggerPolicy='emergent')
    scores=evaluate_payload(p)
    assert scores['optimizer']==pytest.approx(scores['manual'],rel=1e-9)
    off=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert scores['manual']>off
    result=app.mod_gains_payload({**p,'mode':'equipped','candidates':['__arcane__:'+PATH]})
    assert result['gains']['__arcane__:'+PATH]['value']==pytest.approx(off,abs=.001)


def test_probability_damage_integral_matches_monte_carlo():
    state=EnervateState(cfg());predicted=0.0;shots=40
    for i in range(shots):
        predicted+=sum(p*(1+max(0,.1+s*.1)*2) for s,p in state.marginal().items())
        state.advance(i*.1,{s:any_big_probability(.1+s*.1,1) for s in state.marginal()})
    rng=random.Random(7182);total=0
    for _ in range(20000):
        stacks=big=0
        for _ in range(shots):
            cc=.1+.1*stacks;tier=int(cc)+(rng.random()<cc-int(cc))
            total+=1+tier*2;stacks+=1
            if tier>=2:
                big+=1
                if big==6:stacks=big=0
    assert predicted==pytest.approx(total/20000,rel=.003)


def test_alt_ignored_gain_still_allows_big_crit_consumption():
    state=EnervateState(cfg(0));state.advance(0)
    state.advance(.1,{1:1},gain=False)
    assert state.states=={(1,0):1}


def test_crit_seed_promotion_matches_direct_expectation():
    from wfarsenal.damage import crit_tier_seed_distribution,effective_hit_multiplier
    for chance in [-2,0,.4,1,1.7,3.2]:
        for noncrit in [1,12]:
            pairs=crit_tier_seed_distribution(chance,2.5,noncrit,2,double_crit_chance=.4)
            assert sum(p for p,_ in pairs)==pytest.approx(1)
            assert sum(p*d for p,d in pairs)==pytest.approx(effective_hit_multiplier(chance,2.5,noncrit,2,double_crit_chance=.4))


def test_sampling_step_does_not_change_enervate_damage():
    w=weapon();sc=Scenario(trigger_policy='emergent');fx=ModEffectList([ModEffect('WEAPON_PROC_CHANCE','SET',0)])
    st=apply_mods(w,fx,scenario=sc);c=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[],[(record(),5,None)])
    target=dict(health=1e12,armour=0,shield=0,overguard=0,baseLevel=1,faction='')
    rows=[replay(st,target,combat=c,attacks_per_second=10,window_seconds=5,time_step=step) for step in [.01,.25,.7]]
    assert rows[0]['totalWindowDamage']==pytest.approx(rows[1]['totalWindowDamage'])
    assert rows[1]['totalWindowDamage']==pytest.approx(rows[2]['totalWindowDamage'])
    assert rows[0]['enervate']['uptime']>0
