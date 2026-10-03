from copy import deepcopy
from dataclasses import replace
import math

import pytest
import app
from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario


def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)


def card(name,scenario):
    mod=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==name and not m.get('catalogExclusion'))
    return o._mod_card(mod,scenario,allow_empty=True)


@pytest.mark.parametrize('name,codes,negative',[
    ('Braton Prime',('D','0','1'),'H'),('Nikana Prime',('K','0','1'),'X'),
    ('Nikana Prime',('K','0','1'),'E')])
def test_neutral_curse_is_scored_with_real_structure_bonus(name,codes,negative):
    w=weapon(name);s=Scenario();wt=o._weapon_type(None,w)
    pos,_=o._candidate_lines(wt,1.,(),negative=False,structure_scale=o.theoretical_structure_scale(3,False))
    neg,_=o._candidate_lines(wt,1.,(),negative=True,structure_scale=o.theoretical_structure_scale(3,False,negative=True))
    baseline=o._evaluate(w,(),None,scenario=s,metric='sustainedDps')
    result=o.recommend_optimal_riven(w,baseline,[l for l in pos if l.code in codes],
        [l for l in neg if l.code==negative],scenario=s,metric='sustainedDps',budget_seconds=1.,top_limit=20)
    assert set(result['structuresEvaluated'])=={'2+0','2+1','3+0','3+1'}
    for n in (2,3):
        cursed=[r for r in result['combos'] if r['structure']==f'{n}+1']
        assert cursed
        for row in cursed:
            assert any(l['code']==negative and l['negative'] for l in row['stats'])
            positives={l['code'] for l in row['stats'] if not l['negative']}
            clean=next(r for r in result['combos'] if r['structure']==f'{n}+0' and {l['code'] for l in r['stats']}==positives)
            for line in row['stats']:
                if not line['negative']:
                    original=next(l for l in clean['stats'] if l['code']==line['code'])
                    assert line['value']==pytest.approx(original['value']*1.25)
            assert row['score']>clean['score']


def test_equipped_mods_and_ranks_reach_recommender_and_arcanes_change_score():
    w=weapon('Braton Prime');s=Scenario(trigger_policy='assumed_max')
    mod=card('Serration',s)
    arc=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Primary Merciless')
    request=dict(weapon=w['path'],mods=[dict(path=mod.key,rank=3,slot=0)],profile='fast',
        enemy=app._BENCHMARK_ENEMY_PATH,level=170,steelPath=True,triggerPolicy='assumed_max')
    plain,plain_engine=app.build_weapon_payload(request,return_engine_context=True,fixed_mods=request['mods'])
    armed={**request,'arcanes':[dict(path=arc['path'],rank=arc['maxRank'])]}
    buffed,engine=app.build_weapon_payload(armed,return_engine_context=True,fixed_mods=armed['mods'])
    assert [c.key for c in engine['evaluation'].cards]==[mod.key]
    assert engine['evaluation'].cards[0].rank==3
    assert engine['passives'].event_arcanes
    assert engine['evaluation'].score>plain_engine['evaluation'].score


def test_known_mod_condition_is_full_in_assumed_context():
    from wfarsenal.manual_combat import prepare
    w=weapon('Braton Prime');s=Scenario(trigger_policy='assumed_max',aiming=True)
    mod=card('Galvanized Chamber',s)
    combat=prepare(dict(weapon=w,fire_mode=0,scenario=s,effects=o._effects([mod],s)),
                   [(mod.record,mod.rank,None)],[],assumed=True)
    assert combat['trigger_sources']
    assert all(q['initialStacks']==q['maxStacks'] for q in combat['trigger_sources'])


def test_duration_variants_have_distinct_effects_and_legal_values():
    from wfarsenal.riven_recommendation import negative_rolls
    lines,_=o._candidate_lines('rifle',1.35,(),negative=True,
        structure_scale=o.theoretical_structure_scale(3,True,negative=True))
    duration=next(l for l in lines if l.code=='3')
    rolls=list(negative_rolls([duration]))
    assert len(rolls)==5
    assert rolls[0].value<100<rolls[-1].value
    assert any(line.value==99.9 for line in rolls)
    for line in rolls:
        assert duration.high*.89/1.089-1e-9<=line.value<=duration.high
        assert line.effect.value==pytest.approx(-line.value/100)


def test_incarnon_percent_symbol_keeps_additive_value():
    for kind in ('WEAPON_CRIT_CHANCE','WEAPON_PROC_CHANCE'):
        text=app._incarnon_effect_text(dict(upgradeType=kind,operation='ADD_BASE',value=.18))
        assert '+18%' in text
        assert '百分点' not in text


def test_arcane_path_wire_is_accepted_by_analysis_shared_adapter():
    w=weapon('Braton Prime')
    arc=next(a for a in app.EXPORTS['arcanes'] if a.get('nameEn')=='Primary Merciless')
    a,_,_=o._arcane_card(app.EXPORTS['arcanes'],[dict(path=arc['path'],rank=arc['maxRank'])],w)
    b,_,_=o._arcane_card(app.EXPORTS['arcanes'],[dict(query=arc['path'],rank=arc['maxRank'])],w)
    assert a.effects==b.effects
    assert a.event_arcanes[0][:2]==b.event_arcanes[0][:2]
    assert {k:v for k,v in a.event_arcanes[0][2].items() if k not in ('path','query')}=={k:v for k,v in b.event_arcanes[0][2].items() if k not in ('path','query')}


def test_negative_multishot_cannot_create_negative_projectiles_or_crash_burst():
    from wfarsenal.damage import ModEffect,apply_mods
    from wfarsenal.combat_replay import replay
    w=weapon('Burston Prime')
    stats=apply_mods(w,[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',-2.)])
    assert stats.multishot==0.
    result=replay(stats,dict(health=1e8,shield=0.,armour=0.,overguard=0.,baseLevel=1),
        attacks_per_second=stats.fire_rate,window_seconds=1.,headshot_chance=1.,
        combat={'baseMode':True,'baseFireRate':stats.fire_rate,'baseBurst':{'count':3,'delay_seconds':.05}})
    assert math.isfinite(result['killsPerMinute'])
    assert result['killsPerMinute']==0.


def test_float_noise_does_not_prefer_damaging_curse_on_kill_plateau():
    from wfarsenal.riven_recommendation import result_rank
    neutral=dict(score=12.,tieBreakScore=331880.89041748026,neutralNegative=True)
    harmful=dict(score=12.,tieBreakScore=331880.8904174803,neutralNegative=False)
    assert sorted([harmful,neutral],key=result_rank)[0] is neutral
    useful=dict(score=13.,tieBreakScore=331880.8904174803,neutralNegative=False)
    assert sorted([neutral,useful],key=result_rank)[0] is useful
