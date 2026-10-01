from copy import deepcopy
from dataclasses import replace
import pickle

import pytest
import app
from wfarsenal.damage import Scenario, ModEffect, apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import guard_replay_progress, target


def weapon(name):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name))


def test_incarnon_form_identity_includes_onos_beam_and_excludes_melee_default():
    from wfarsenal.event_profiles import is_incarnon_mode
    assert [is_incarnon_mode(weapon('Onos'),i) for i in range(3)]==[False,True,True]
    assert not is_incarnon_mode(weapon('Innodem'),0)
    assert [is_incarnon_mode(weapon('Stug'),i) for i in range(3)]==[False,False,True]


def test_charge_evolution_is_supported_and_shortens_base_phase():
    w = weapon('Laetum')
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id'] == '4-2')
    effects, unsupported = app.optimizer._branch_effects(branch)
    assert effects and not unsupported
    st = apply_mods(w, effects, scenario=Scenario())
    assert st.incarnon_charge_multiplier == pytest.approx(1.5)
    observed = []
    for choices in ({}, {'tier4':'4-2'}):
        selected = deepcopy(w)
        selected['isIncarnonForm'] = True
        combat = prepare(dict(weapon=selected, fire_mode=1, effects=effects if choices else [],
                              scenario=Scenario(trigger_policy='emergent')),
                         [], [], cycle_enabled=True, incarnon_choices=choices)
        original = combat['resolve']
        states = []
        def resolve(form, stacks, live):
            states.append(form)
            stats, _ = original(form, stacks, live)
            return replace(stats, fire_rate=1., magazine=100., crit_chance=0., status_chance=0., multishot=1.), None
        combat['resolve'] = resolve
        combat['cycle'] = dict(hits=12., pool=100., enterSeconds=.1, exitSeconds=.1)
        first, _ = resolve('base', {}, 0)
        result = replay(first, dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                        attacks_per_second=1., window_seconds=10., headshot_chance=1.,
                        combat=combat, trigger_sources=combat['trigger_sources'])
        observed.append(result['transforms'])
    assert observed == [0, 1]


def test_charge_bonus_does_not_create_body_hit_charge():
    w = weapon('Laetum')
    w['isIncarnonForm'] = True
    effects = [ModEffect('WEAPON_ADD_CHARGE_COUNTER_MULTIPLIER','STACKING_MULTIPLY',.5)]
    combat = prepare(dict(weapon=w,fire_mode=1,effects=effects,scenario=Scenario(trigger_policy='emergent')),
                     [],[],cycle_enabled=True,incarnon_choices={})
    first,_ = combat['resolve']('base',{},0)
    result = replay(first,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=first.fire_rate,window_seconds=15.,headshot_chance=0.,combat=combat)
    assert result['transforms'] == 0


def test_felarx_shells_grant_real_stacks_and_reload_clears_them():
    w = weapon('Felarx')
    combat = prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),
                     [],[],incarnon_choices={'tier3':'3-3'})
    q = combat['trigger_sources'][0]
    assert q['kind'] == 'on-shell-reloaded' and q['duration'] == 0
    assert q['resetOn'] == ['on-reload','on-holster']
    st,_ = combat['resolve']('selected',{},0)
    full,_ = combat['resolve']('selected',{q['id']:6},0)
    assert st.reload_time == pytest.approx(3.7)
    assert full.fire_rate == pytest.approx(st.fire_rate * 1.6)
    result = replay(st,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=st.fire_rate,window_seconds=12.,combat=combat,
                    trigger_sources=combat['trigger_sources'])
    assert result['shots'] == 18
    assert len(result['reloadShellEvents']) == 12
    assert [e['time'] for e in result['reloadShellEvents'][:6]] == pytest.approx([3.2,3.6,4,4.4,4.8,5.2])
    series = result['triggerSeries'][0]['series']
    assert max(series) == 6 and series[-1] == 0


def test_felarx_magazine_size_increases_both_reload_cost_and_stack_grant():
    w = weapon('Felarx')
    combat = prepare(dict(weapon=w,fire_mode=0,effects=[ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',1.)],
                          scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier3':'3-3'})
    st,_ = combat['resolve']('selected',{},0)
    assert st.magazine == 12 and st.reload_time == pytest.approx(6.1)
    result = replay(st,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=st.fire_rate,window_seconds=11.,combat=combat,
                    trigger_sources=combat['trigger_sources'])
    assert len(result['reloadShellEvents']) == 12
    assert max(result['triggerSeries'][0]['series']) == 12


def test_felarx_mode_switch_only_grants_rounds_missing_from_base_magazine():
    w = weapon('Felarx')
    w['isIncarnonForm'] = True
    combat = prepare(dict(weapon=w,fire_mode=1,effects=[],scenario=Scenario(trigger_policy='emergent')),
                     [],[],cycle_enabled=True,incarnon_choices={'tier3':'3-3'})
    combat['cycle'] = dict(hits=2.,pool=1.,enterSeconds=.1,exitSeconds=.1)
    original = combat['resolve']
    def resolve(form,stacks,live):
        st,_ = original(form,stacks,live)
        return replace(st,multishot=1.,fire_rate=1.,magazine=6.,status_chance=0.,crit_chance=0.),None
    combat['resolve'] = resolve
    st,_ = resolve('base',{},0)
    result = replay(st,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=1.,window_seconds=4.5,headshot_chance=1.,combat=combat,
                    trigger_sources=combat['trigger_sources'])
    first_two = result['reloadShellEvents'][:2]
    assert [(e['source'],e['form'],e['rounds']) for e in first_two] == [('mode-switch','incarnon',1.),('mode-switch','base',1.)]
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='3-3')
    assert not app.optimizer._branch_effects(branch)[1]


def test_fixed_felarx_incarnon_runs_beyond_first_charge_pool(monkeypatch):
    guard_replay_progress(monkeypatch)
    w=weapon('Felarx')
    w['isIncarnonForm']=True
    combat=prepare(dict(weapon=w,fire_mode=1,effects=[],scenario=Scenario(trigger_policy='emergent')),
                   [],[],incarnon_choices={'tier3':'3-3'})
    st,_=combat['resolve']('selected',{},0)
    result=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=60.,
                  combat=combat,trigger_sources=combat['trigger_sources'])
    assert result['shots']>st.magazine
    assert result['reloads']>0 and result['transforms']==0
    assert result['reloadShellEvents']==[]


@pytest.mark.parametrize('name,branch_id,source_type,target_type,fraction,cap', [
    ('Dera Vandal','4-2','WEAPON_PROC_CHANCE','WEAPON_CRIT_CHANCE',.25,.35),
    ('Cestra','4-3','WEAPON_CRIT_CHANCE','WEAPON_PROC_CHANCE',.3,.4),
    ('Vectis Prime','4-3','WEAPON_CRIT_CHANCE','WEAPON_PROC_CHANCE',.3,.4),
])
def test_stat_conversion_uses_modded_source_and_updates_target_base(name,branch_id,source_type,target_type,fraction,cap):
    w = weapon(name)
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']==branch_id)
    effects, unsupported = app.optimizer._branch_effects(branch)
    assert not unsupported
    normal = apply_mods(w, [], scenario=Scenario())
    source_base = normal.status_chance if source_type=='WEAPON_PROC_CHANCE' else normal.crit_chance
    target_base = normal.crit_chance if target_type=='WEAPON_CRIT_CHANCE' else normal.status_chance
    mods = [ModEffect(source_type,'STACKING_MULTIPLY',1.),ModEffect(target_type,'STACKING_MULTIPLY',1.)]
    live = apply_mods(w,[*effects,*mods],scenario=Scenario())
    target = live.crit_chance if target_type=='WEAPON_CRIT_CHANCE' else live.status_chance
    assert target == pytest.approx((target_base+min(cap,source_base*2*fraction))*2)
    cap_view = apply_mods(w,[*effects,ModEffect(source_type,'STACKING_MULTIPLY',100.)],scenario=Scenario())
    target = cap_view.crit_chance if target_type=='WEAPON_CRIT_CHANCE' else cap_view.status_chance
    assert target == pytest.approx(target_base+cap)


def test_energy_gate_is_explicit_shared_and_not_applied_twice():
    w = weapon('Stug')
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='2-2')
    effects, _ = app.optimizer._branch_effects(branch)
    views = []
    for energy in (None, 699, 700):
        scenario = Scenario(combat_state={} if energy is None else {'energyPool':energy})
        actor = app.optimizer._incarnon_actor_effects(branch, scenario, w)
        search_view = apply_mods(w, [*effects,*actor], scenario=scenario)
        combat = prepare(dict(weapon=w, fire_mode=0, effects=[*effects,*actor], scenario=scenario),
                         [], [], incarnon_choices={'tier2':'2-2'})
        manual_view, _ = combat['resolve']('selected', {}, 0)
        assert manual_view.explosion_radius_multiplier == pytest.approx(search_view.explosion_radius_multiplier)
        views.append(manual_view.explosion_radius_multiplier)
    assert views == pytest.approx([1.,1.,1.5])


def test_combat_state_roundtrip_and_cache_context_are_distinct():
    supplied = {'energyPool':700,'overshields':True,'equippedWeapons':['/Lotus/Weapons/A'], 'emptySlots':['melee']}
    scenario = Scenario(combat_state=supplied)
    supplied['energyPool'] = 0
    supplied['equippedWeapons'].append('/Lotus/Weapons/B')
    clone = pickle.loads(pickle.dumps(scenario))
    assert clone.combat_state == scenario.combat_state
    assert clone.combat_state['energyPool'] == 700
    assert clone.combat_state['equippedWeapons'] == ('/Lotus/Weapons/A',)
    assert app.optimizer._scenario_context(clone) != app.optimizer._scenario_context(Scenario())
    with pytest.raises(ValueError, match='unsupported fields'):
        Scenario(combat_state={'freeDamage':10})
    with pytest.raises(ValueError):
        Scenario(combat_state={'energyPool':float('nan')})


@pytest.mark.parametrize('name,stat,factor', [('Ceramic Dagger','total_damage',2.),('Praedos','fire_rate',1.4)])
def test_fixed_melee_evolution_requires_explicit_activation(name,stat,factor):
    w = weapon(name)
    observed = []
    for active in (False,True):
        scenario = Scenario(trigger_policy='emergent',combat_state={'incarnonMeleeActive':active})
        fixed = w['incarnon']['tiers'][0]['branches'][0]
        effects = app.optimizer._incarnon_actor_effects(fixed,scenario,w)
        search = apply_mods(w,effects,scenario=scenario)
        combat = prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=scenario),[],[])
        manual,_ = combat['resolve']('selected',{},0)
        assert getattr(manual,stat) == pytest.approx(getattr(search,stat))
        observed.append(getattr(manual,stat))
    assert observed[1] == pytest.approx(observed[0]*factor)


def test_energy_spend_buff_counts_thresholds_and_expires():
    w = weapon('Gammacor')
    scenario = Scenario(trigger_policy='emergent',combat_state={'energySpent':150})
    combat = prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=scenario),[],[],incarnon_choices={'tier2':'2-2'})
    source = combat['trigger_sources'][0]
    assert source['initialStacks']==3 and source['initialDuration']==10
    base,_ = combat['resolve']('selected',{},0)
    full,_ = combat['resolve']('selected',{source['id']:3},0)
    assert full.total_damage-base.total_damage == pytest.approx(15)
    result = replay(base,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=base.fire_rate,window_seconds=11.,combat=combat,trigger_sources=combat['trigger_sources'])
    assert result['triggerSeries'][0]['series'][0]==3
    assert result['triggerSeries'][0]['series'][-1]==0


def test_energy_spending_during_replay_refreshes_known_buff():
    w = weapon('Gammacor')
    scenario = Scenario(trigger_policy='emergent',combat_state={'energySpendPerSecond':25})
    combat = prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=scenario),[],[],incarnon_choices={'tier2':'2-2'})
    base,_ = combat['resolve']('selected',{},0)
    result = replay(base,dict(health=1e12,shield=0,armour=0,overguard=0,baseLevel=1),
                    attacks_per_second=base.fire_rate,window_seconds=11.,combat=combat,trigger_sources=combat['trigger_sources'])
    assert result['triggerSeries'][0]['series'][0]==0
    assert result['triggerSeries'][0]['series'][-1]==4


def test_ammo_efficiency_uses_runtime_value_and_explicit_glide_state():
    w = weapon('Laetum')
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches'] if b['id']=='3-3')
    values = []
    for state in ({},{'aimGliding':True},{'sliding':True}):
        scenario = Scenario(trigger_policy='emergent',combat_state=state)
        effects = app.optimizer._incarnon_actor_effects(branch,scenario,w)
        st = apply_mods(w,effects,scenario=scenario)
        combat = prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=scenario),[],[],incarnon_choices={'tier3':'3-3'})
        live,_ = combat['resolve']('selected',{},0)
        assert live.ammo_cost==pytest.approx(st.ammo_cost)
        values.append(live.ammo_cost)
    assert values==pytest.approx([1.,.4,.4])


def test_onos_consecutive_heads_use_run_distribution_instead_of_fractional_hit_count():
    w = weapon('Onos')
    result = []
    for chance in (0.,.5,1.):
        combat = prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[],incarnon_choices={'tier5':'5-1'})
        original = combat['resolve']
        combat['resolve'] = lambda *args: (replace(original(*args)[0],fire_rate=1.,magazine=100.,crit_chance=0.,status_chance=0.),None)
        st,_ = combat['resolve']('selected',{},0)
        view = replay(st,target(1e12),attacks_per_second=1.,window_seconds=2.1,headshot_chance=chance,
                      combat=combat,trigger_sources=combat['trigger_sources'])
        result.append(view['triggerSeries'][0]['series'][-1])
    assert result==pytest.approx([0.,.375,2.])
