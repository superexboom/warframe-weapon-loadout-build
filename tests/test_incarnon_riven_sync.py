from copy import deepcopy
from dataclasses import replace

import pytest
import app
from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario, ModEffect, apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay


def weapon(name):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name))


def test_fixed_evolution_displays_official_unlock_and_passive():
    tiers = app._incarnon_options(weapon('Torid'))
    assert tiers[0]['tier'] == 1 and tiers[0]['selectable'] is False
    assert '直接命中' in tiers[0]['options'][0]['description']
    assert '毒素光束' in tiers[0]['options'][0]['description']
    dagger = app._incarnon_options(weapon('Ceramic Dagger'))[0]['options'][0]
    assert '6x' in dagger['description'] and '重击发射光谱匕首' in dagger['description']
    assert any('100%' in row['text'] and row['modeled'] is True for row in dagger['details'])


def test_fifth_evolution_and_readable_model_status_are_exposed():
    tiers = app._incarnon_options(weapon('Laetum'))
    assert [t['tier'] for t in tiers] == [1, 2, 3, 4, 5]
    branch = next(b for b in tiers[-1]['options'] if b['id'] == '5-3')
    assert '未暴击' in branch['description'] and '+400%' in branch['description']
    assert '10 秒' in branch['description'] and '3 层' in branch['description']
    assert branch['complete'] is True
    stug = next(b for t in app._incarnon_options(weapon('Stug')) for b in t['options'] if b['id'] == '2-2')
    assert '700' in stug['description'] and '+50%' in stug['description']
    assert all(row['modeled'] is True for row in stug['details'])
    assert any('战斗状态' in row['calculation'] for row in stug['details'])


def test_native_actor_conditions_and_passive_multishot_status_are_not_labeled_unmodeled():
    atomos=next(b for t in app._incarnon_options(weapon('Atomos')) for b in t['options'] if b['id']=='2-2')
    assert any('玩家自身护盾' in row['text'] for row in atomos['details'])
    torid=next(b for t in app._incarnon_options(weapon('Torid')) for b in t['options'] if b['id']=='2-2')
    assert not any('尚未建模' in row['calculation'] for row in torid['details'])


def test_dera_arbitrary_status_condition_changes_live_fire_rate():
    w = weapon('Dera Vandal')
    combat = prepare(dict(weapon=w, fire_mode=0, scenario=Scenario(trigger_policy='emergent'), effects=[]),
                     [], [], incarnon_choices={'tier2': '2-2'})
    source = combat['trigger_sources'][0]
    assert source['kind'] == 'on-proc'
    base, _ = combat['resolve']('selected', {}, 0)
    live, _ = combat['resolve']('selected', {source['id']: 6}, 0)
    assert live.fire_rate == pytest.approx(base.fire_rate * 1.3)


def test_laetum_headshots_change_reload_and_ammo_without_becoming_passive():
    w = weapon('Laetum')
    combat = prepare(dict(weapon=w, fire_mode=0, scenario=Scenario(trigger_policy='emergent'), effects=[]),
                     [], [], incarnon_choices={'tier3': '3-1', 'tier5': '5-2'})
    assert {q['kind'] for q in combat['trigger_sources']} == {'on-headshot'}
    stacks = {q['id']: q['maxStacks'] for q in combat['trigger_sources']}
    base, _ = combat['resolve']('selected', {}, 0)
    live, _ = combat['resolve']('selected', stacks, 0)
    assert live.reload_time < base.reload_time
    assert live.ammo_cost == pytest.approx(base.ammo_cost * .6)


@pytest.mark.parametrize('cc,sc,forced,expected', [(0.,0.,{},2.), (1.,0.,{},0.), (0.,1.,{},0.), (0.,0.,{'DT_IMPACT':1},0.)])
def test_overwhelming_gate_is_per_part_and_respects_crit_status_and_forced_procs(cc, sc, forced, expected):
    w = weapon('Laetum')
    combat = prepare(dict(weapon=w, fire_mode=0, scenario=Scenario(trigger_policy='emergent'), effects=[]),
                     [], [], incarnon_choices={'tier5': '5-3'})
    original = combat['resolve']
    def resolve(form, stacks, live):
        st, _ = original(form, stacks, live)
        st = replace(st, fire_rate=1., magazine=100., crit_chance=cc, status_chance=sc,
                     multishot=1., native_forced_procs={})
        return st, replace(st, radial_only=True)
    combat['resolve'] = resolve
    first, _ = resolve('selected', {}, 0)
    result = replay(first, dict(health=1e12, shield=0, armour=0, overguard=0, baseLevel=1),
                    attacks_per_second=1., window_seconds=.5, time_step=.25,
                    forced_procs=forced, combat=combat, trigger_sources=combat['trigger_sources'])
    assert result['shots'] == 1
    assert result['triggerSeries'][0]['series'][0] == pytest.approx(expected)


@pytest.mark.parametrize('name', ['Laetum', 'Felarx', 'Phenmor'])
def test_devouring_attrition_chance_is_applied_to_noncritical_damage(name):
    w = weapon(name)
    branch = next(b for t in w['incarnon']['tiers'] for b in t['branches']
                  if any(e.get('upgradeType') == 'WEAPON_NOCRIT_CHANCE' for e in b['effects']))
    effects, _ = o._branch_effects(branch)
    st = apply_mods(w, effects, scenario=Scenario())
    assert st.noncrit_damage_multiplier == pytest.approx(11.)
    always = apply_mods(w, [ModEffect('WEAPON_NOCRIT_DAMAGE', 'STACKING_MULTIPLY', 20)], scenario=Scenario())
    assert always.noncrit_damage_multiplier == pytest.approx(21.)


@pytest.mark.parametrize('name,expected', [('Verglas','rifle'),('Sweeper','shotgun'),('Prisma Burst Laser','pistol'),('Deconstructor','melee')])
def test_companion_catalog_does_not_replace_riven_family(name, expected):
    w = weapon(name)
    assert app.CATALOG_WEAPONS_BY_PATH[w['path']]['weaponType'] == 'companion'
    assert o._weapon_type(None, w) == expected


def test_positive_and_negative_permutations_cannot_share_recommendation_memo():
    positive, _ = o._wire_lines([{'code':'D','value':100.,'negative':False},{'code':'S','value':50.,'negative':False},{'code':'0','value':50.,'negative':False}])
    cursed, _ = o._wire_lines([{'code':'D','value':100.,'negative':False},{'code':'S','value':50.,'negative':True},{'code':'0','value':50.,'negative':False}])
    assert o._riven_combo_key(positive) != o._riven_combo_key(cursed)


def test_advanced_riven_values_and_relative_weakpoint_crit_use_native_templates():
    bases = o._template_bases(app.EXPORTS['rivenTemplates'], 'rifle')
    assert bases['VI'] == pytest.approx(90.)
    assert bases['W'] == pytest.approx(225.)
    assert bases['Y'] == pytest.approx(247.5)
    assert app.RIVEN_BASE_VALUES['rifle']['VI'] == bases['VI']
    effect = o._effect_from_code('Y', 100., negative=False, source='riven:Y')
    w = weapon('Laetum')
    base = apply_mods(w, [], scenario=Scenario())
    live = apply_mods(w, [effect], scenario=Scenario())
    assert live.weakpoint_crit_chance_bonus == 0.
    assert live.weakpoint_crit_chance_relative == pytest.approx(1.)
    assert live.crit_chance == base.crit_chance
