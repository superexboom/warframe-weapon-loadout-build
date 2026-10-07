from copy import deepcopy
from dataclasses import replace
import pytest
import app
from tests.test_combat_replay import stats, target
from wfarsenal.damage import arcane_effects, apply_mods
from wfarsenal.combat_replay import replay
from wfarsenal.status_arcanes import CRYOGENIC, configuration
from tools.audit_optimizer_events import evaluate_payload


def raw():
    return next(a for a in app.EXPORTS['arcanes'] if a['path']==CRYOGENIC)


def run(st, *, rank=5, tg=None, **kwargs):
    return replay(st,tg or target(),attacks_per_second=st.fire_rate,
                  combat={'cryogenic':configuration(raw(),rank)},**kwargs)


@pytest.mark.parametrize('rank,count',list(enumerate([1,1,2,2,3,3])))
def test_non_linear_ranks_and_native_signature(rank,count):
    spec=configuration(raw(),rank)
    assert spec['coldStacks']==count and spec['radius']==10+rank
    bad=deepcopy(raw());bad['runtimeScripts']['apply']['_damageBase']=100
    assert configuration(bad,rank) is None
    bad=deepcopy(raw());bad['conditionalEffects'][0]['conditions']=['OnHitCondition']
    assert configuration(bad,rank) is None
    assert not arcane_effects(raw(),rank=rank)


def test_derived_cold_is_per_puncture_not_per_shot_and_not_elemental_damage():
    st=stats(damage_types={'DT_PUNCTURE':100},status_chance=2,fire_rate=1,crit_chance=0)
    r=run(st,window_seconds=.1)
    assert r['procCounts']['DT_PUNCTURE']==2
    assert r['cryogenic']['expectedColdApplications']==6
    assert r['procCounts']['DT_FREEZE']==6
    assert r['directWindow']==100 and r['dotWindow']==0
    assert r['timeline'][0]['stacks']['cold']==6
    # The per-attack event scale is applied once, not once per derivation.
    scaled=run(st,window_seconds=.1,status_rate_multiplier=.5)
    assert scaled['procCounts']['DT_FREEZE']==3


def test_no_puncture_no_cold_and_forced_puncture_can_trigger():
    st=stats(damage_types={'DT_FIRE':100},status_chance=0,fire_rate=1)
    assert run(st,window_seconds=.1)['cryogenic']['expectedColdApplications']==0
    assert run(st,window_seconds=.1,forced_procs={'DT_PUNCTURE':1})['cryogenic']['expectedColdApplications']==3


def test_cold_uses_duration_overguard_cap_and_freeze_cycle():
    st=stats(damage_types={'DT_PUNCTURE':100},status_chance=1,fire_rate=.01,proc_duration_multiplier=.5)
    r=run(st,window_seconds=4)
    assert r['timeline'][0]['stacks']['cold']==3
    assert r['timeline'][-1]['stacks']['cold']==0
    st=replace(st,status_chance=4,proc_duration_multiplier=1)
    guarded=run(st,tg={**target(),'overguard':1e10},window_seconds=.1)
    assert guarded['timeline'][0]['stacks']['cold']==4
    frozen=run(st,window_seconds=4)
    assert frozen['timeline'][0]['stacks']['cold']==10
    assert frozen['timeline'][-1]['stacks']['cold']==3


def test_next_hit_receives_cold_critical_damage_bonus_and_zero_uptime_disables():
    st=stats(damage_types={'DT_PUNCTURE':100},status_chance=1,fire_rate=1,crit_chance=1)
    a=replay(st,target(),attacks_per_second=1,window_seconds=2)
    b=run(st,window_seconds=2)
    assert b['directWindow']>a['directWindow']
    zero=replay(st,target(),attacks_per_second=1,window_seconds=2,
                combat={'cryogenic':{**configuration(raw(),5),'uptime':0}})
    assert zero['directWindow']==a['directWindow']
    assert zero['procCounts']==a['procCounts']


@pytest.mark.parametrize('name',['Aksomati Prime','Akbolto Prime','Lato','Sonicor'])
def test_manual_optimizer_catalog_and_panel_share_exact_event_model(name):
    entry=app.MANUAL_ARCANES_BY_PATH[CRYOGENIC]
    assert entry['eventModel']=='cryogenic' and '穿刺' in entry['trigger']['conditionZh']
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    p=dict(weapon=w['path'],fireMode=0,mods=[],arcanes=[dict(path=CRYOGENIC,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,
           aiming=True,triggerPolicy='emergent',slotPolarities=[None]*8)
    r=evaluate_payload(p)
    assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    st=apply_mods(w,arcane_effects(raw(),rank=5));plain=apply_mods(w,[])
    assert st.damage_types==plain.damage_types and st.status_chance==plain.status_chance
    assert not any('arcane-state' in x for x in r['manualUnsupported'])


def test_equipped_contribution_removes_real_event_gain():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Akbolto Prime')
    p=dict(weapon=w['path'],mods=[],arcanes=[dict(path=CRYOGENIC,rank=5)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=160,steelPath=True,headshotChance=1,
           aiming=True,triggerPolicy='emergent')
    key='__arcane__:'+CRYOGENIC
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':[key]})
    without=app.simulate_manual_payload({**p,'arcanes':[]})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains'][key]['value']==pytest.approx(without,abs=.001)
    assert gains['baseValue']>without


def test_one_magnetic_break_per_pool_and_target_generation():
    # Real automatic build reproduced two breaks 0 seconds apart: floating
    # subtraction left a tiny positive Overguard pool after the first break.
    import json
    from pathlib import Path
    from tools.compare_archgun_board_builds import local_replay
    p=json.loads((Path(__file__).parent/'fixtures/cryogenic_mag_break_build_20260927.json').read_text(encoding='utf-8'))
    event=local_replay(p,duration=30)['replay']
    breaks=event['magneticBreaks']
    assert breaks
    identities=[(b['targetGeneration'],b['pool']) for b in breaks]
    assert len(identities)==len(set(identities))
    assert len(breaks)<=event['killEvents']+1
    # Each break's Electricity proc is weighted by P(Magnetic present) then.
    assert len(breaks)-.05<event['procCounts']['DT_ELECTRICITY']<=len(breaks)+1e-9
