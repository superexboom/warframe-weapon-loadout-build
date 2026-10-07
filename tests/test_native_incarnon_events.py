from copy import deepcopy
from dataclasses import replace

import pytest
import app
from wfarsenal.damage import Scenario,ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def weapon(name):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name))


def test_defender_shield_break_does_not_follow_enemy_shield_break():
    # Event timeline mode (the default forces the Warframe-side break).
    for state,expected in [({'selfShieldBreakForced':False},0),({'selfShieldBreakForced':False,'selfShieldBreakAt':.1},1)]:
        combat=prepare(dict(weapon=weapon('Atomos'),fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent',combat_state=state)),
                       [],[],incarnon_choices={'tier2':'2-2'})
        assert combat['trigger_sources'][0]['kind']=='on-shield-broken'
        stats,_=combat['resolve']('selected',{},0)
        enemy={**target(1e12),'shield':1.}
        result=replay(stats,enemy,attacks_per_second=stats.fire_rate,window_seconds=1.,combat=combat,trigger_sources=combat['trigger_sources'])
        assert max(result['triggerSeries'][0]['series'])==expected


def test_native_puncture_proc_condition_is_not_generic_hit():
    combat=prepare(dict(weapon=weapon('Latron Prime'),fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),
                   [],[],incarnon_choices={'tier2':'2-1'})
    assert combat['trigger_sources'][0]['kind']=='proc-DT_PUNCTURE'
    assert combat['trigger_sources'][0]['maxStacks']==4


def test_latron_strip_counts_bullets_not_proc_stacks_and_survives_proc_expiry():
    combat=prepare(dict(weapon=weapon('Latron Prime'),fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),
                   [],[],incarnon_choices={'tier4':'4-1'})
    assert combat['punctureArmorStrip']==.2
    original=combat['resolve']
    def resolve(*args):
        stats,_=original(*args)
        return replace(stats,damage_types={'DT_PUNCTURE':100.},fire_rate=.05,magazine=100.,multishot=1.,status_chance=3.,crit_chance=0.),None
    combat['resolve']=resolve
    stats,_=resolve('selected',{},0)
    result=replay(stats,{**target(1e12),'armour':1000.},attacks_per_second=.05,window_seconds=15.,combat=combat)
    points=result['timeline']
    assert points[1]['punctureArmourStrip']==pytest.approx(.2)
    assert next(p for p in points if p['time']>=12.)['armour']==pytest.approx(800.)
    assert points[-1]['punctureArmourStrip']==pytest.approx(.2)
    assert points[-1]['stacks']['puncture']==0


def test_felarx_reload_toggle_alternates_after_complete_reload():
    combat=prepare(dict(weapon=weapon('Felarx'),fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent',distance=25.)),
                   [],[],incarnon_choices={'tier3':'3-1'})
    source=combat['trigger_sources'][0]
    assert source['toggleOn']=='on-reload-complete'
    slow,_=combat['resolve']('selected',{},0)
    fast,_=combat['resolve']('selected',{source['id']:1},0)
    assert fast.falloff_multiplier>slow.falloff_multiplier
    assert slow.projectile_speed_multiplier==1 and fast.projectile_speed_multiplier==2


def test_onos_auto_fallback_uses_event_effects_to_select_blast_perk():
    selected,_=app.optimizer._select_fire_mode(weapon('Onos'),2,weapon_type='pistol')
    _,choices,notes,_=app.optimizer._incarnon_card(selected,None,scenario=Scenario(),metric='killsPerMinute')
    assert choices['tier5']=='5-2'
    assert 'incarnon-tier5-auto-selected-event-objective' in notes
