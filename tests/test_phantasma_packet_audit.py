"""Keep Phantasma payload omissions visible without fabricating trigger rights."""
import pytest
from tools.import_phantasma_packet_audit import audit, PAIRS, WARNINGS


class Packages:
    def resolve(self, projectile):
        return {"AttackData": {"Amount": 15, "Type": "DT_IMPACT"},
                "ExplosiveAttack": {"Amount": 73, "Type": "DT_RADIATION", "HitType": "DHT_PROJECTILE"}}


def test_packet_type_and_head_suppression_do_not_grant_co_or_head_events():
    result = audit(Packages(), PAIRS[0][1])
    assert result["sourceHitType"] == "DHT_PROJECTILE"
    assert result["headDamageSuppression"]
    assert "head-crit-and-head-kill-qualification" in result["unresolved"]
    assert "takes_condition_overload" not in result and "area_direct" not in result


def test_full_clip_parent_and_explicit_child_overlap_keep_independent_counts_and_scales():
    import math
    import app
    from wfarsenal.damage import Scenario, ModEffect
    from wfarsenal.manual_combat import prepare
    weapon = next(w for w in app.EXPORTS['weapons'] if w['path'] == PAIRS[1][0])
    default = prepare(dict(weapon=weapon, fire_mode=1, effects=[], scenario=Scenario()), [], [])
    direct, radial = default['resolve']('selected', {}, 0.)
    assert direct.damage_types == {'DT_IMPACT': 165.}
    assert radial.damage_types == {'DT_RADIATION': 803.}
    assert direct.ammo_cost == direct.magazine == 11.
    assert math.isclose(direct._charge_time, .090899996 * 11, abs_tol=1e-7)
    assert direct.reload_time > 0 and not getattr(radial, '_additional_radials', ())
    assert 'phantasma-child-overlap-off-until-explicit-geometry-policy' in default['unsupported']
    assert not set(WARNINGS) & set(default['unsupported'])
    assert radial.radial_victim_crit and radial.delayed_radial_hit_event and not radial.area_direct
    effects = [ModEffect('WEAPON_FIRE_ITERATIONS', 'ADD', 1.2),
               ModEffect('WEAPON_CHARGE_RATE', 'ADD', 1.),
               ModEffect('WEAPON_CRIT_CHANCE', 'SET', 0.), ModEffect('WEAPON_PROC_CHANCE', 'SET', 0.)]
    scenario = Scenario(combat_state=dict(phantasmaChildOverlap='ideal-contact', phantasmaChildArrivalSeconds=.9))
    combat = prepare(dict(weapon=weapon, fire_mode=1, effects=effects, scenario=scenario), [], [])
    charged, parent = combat['resolve']('selected', {}, 0.)
    children = parent._additional_radials
    assert math.isclose(charged._charge_time, direct._charge_time / 2., abs_tol=1e-7)
    assert charged.ammo_cost == 11. and charged.multishot == 2.2
    assert [p.damage_types for p in children] == (
        [{'DT_IMPACT': 3.}, {'DT_RADIATION': 18.}]*5 +
        [{'DT_IMPACT': 6.}, {'DT_RADIATION': 36.}]*3)
    assert [round(p.multishot, 7) for p in children] == [1.]*14 + [.4,.4]
    assert all(p._impact_delay == .9 and not getattr(p, '_body_only', False) and p.delayed_radial_hit_event and p.radial_victim_crit for p in children)
    assert 'phantasma-child-ideal-contact-and-arrival-time-assumed' in combat['unsupported']
    co_fight = prepare(dict(weapon=weapon, fire_mode=1,
        effects=[*effects, ModEffect('WEAPON_DAMAGE_AMOUNT', 'ADD', 1.),
                 ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE', 'ADD', .8)], scenario=scenario), [], [])
    _, co_parent = co_fight['resolve']('selected', {}, 1.)
    co_children = co_parent._additional_radials
    assert co_children[0].total_damage == pytest.approx(3. * 2. * 1.8)
    assert co_children[1].total_damage == pytest.approx(18. * 2.)
    from wfarsenal.combat_replay import replay
    target = dict(health=1e12, shield=0., overguard=0., armour=0., baseLevel=1)
    kw = dict(attacks_per_second=charged.fire_rate, combat=combat, collect_timeline=True, headshot_chance=1.)
    before = replay(charged, target, window_seconds=charged._charge_time + .89, **kw)
    after = replay(charged, target, window_seconds=charged._charge_time + .91, **kw)
    assert before['shots'] == after['shots'] == 1
    assert after['directWindow'] - before['directWindow'] == pytest.approx(
        sum(p.total_damage * p.multishot for p in children))
    curve = []
    replay(charged, {**target, 'health':before['directWindow']+10.},
           window_seconds=charged._charge_time+.91, life_curve=curve, **kw)
    arrivals = [event[1] for event in curve if abs(event[0]-charged._charge_time-.9)<1e-7]
    assert arrivals == pytest.approx([3.,18.])  # First child's blast kills before child2 contact.


def test_phantasma_area_packet_retains_cold_crit_without_head_bonus(monkeypatch):
    from copy import copy
    import app
    from wfarsenal import native_replay,mods_native
    from wfarsenal.damage import Scenario,mod_effects,damage_against
    from wfarsenal.manual_combat import prepare
    from wfarsenal.combat_replay import replay
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==PAIRS[1][0])
    cold=next(m for m in app.EXPORTS['mods'] if m.get('nameEn')=='Frigid Blast')
    monkeypatch.setattr(mods_native,'SHADOW',True)
    scenario=Scenario(trigger_policy='emergent')
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=mod_effects(cold,cold['maxRank'],scenario),scenario=scenario),[],[])
    base_resolve=combat['resolve'];stats,radial=base_resolve('selected',{},0.)
    victim=dict(health=1e9,armour=0.,shield=0.,overguard=0.,baseLevel=1,headshotMultiplier=3.)
    assert radial.radial_only and radial.radial_victim_crit and not radial.area_direct
    assert damage_against(radial,victim,hit_location='head')['perShot']==damage_against(radial,victim)['perShot']
    monkeypatch.setattr(native_replay,'SHADOW',True)
    before=native_replay.STATS['native']
    kw=dict(attacks_per_second=stats.fire_rate,window_seconds=4.,collect_timeline=False)
    actual=replay(stats,victim,combat=combat,**kw)
    assert native_replay.STATS['native']>before and actual['procCounts']['DT_FREEZE']>0
    def old_radial_rule(*args):
        direct,part=base_resolve(*args);part=copy(part);part.radial_victim_crit=False
        return direct,part
    control=replay(stats,victim,combat={**combat,'resolve':old_radial_rule},**kw)
    assert actual['totalWindowDamage']>control['totalWindowDamage']
    monkeypatch.setattr(native_replay.wfcore,'RADIAL_VICTIM_CRIT',0)
    assert not native_replay.supported(stats,dict(combat=combat,collect_timeline=False))
