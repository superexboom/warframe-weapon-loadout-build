"""Keep Phantasma payload omissions visible without fabricating trigger rights."""
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


def test_runtime_parent_packet_is_restored_and_remaining_bounds_are_alternate_only():
    path,projectile=PAIRS[1]
    import app
    from wfarsenal.damage import Scenario
    from wfarsenal.manual_combat import prepare
    weapon = next(w for w in app.EXPORTS["weapons"] if w.get("path") == path)
    for mode in (0, 1):
        combat = prepare(dict(weapon=weapon, fire_mode=mode, effects=[], scenario=Scenario()), [], [])
        assert not set(WARNINGS) & set(combat["unsupported"])
        assert ('phantasma-cluster-child-payload-unmodeled' in combat['unsupported']) == bool(mode)
        if mode == 1:
            direct, radial = combat["resolve"]("selected", {}, 0.)
            assert direct.damage_types == {"DT_IMPACT": 15.}
            assert radial.damage_types == {'DT_RADIATION':73.}
            assert 'phantasma-main-explosion-CO-neutral-fallback-unverified' in combat['unsupported']
            assert not radial.area_direct  # Native type2 alone never grants every weakpoint effect.
            assert radial.radial_victim_crit and radial.delayed_radial_hit_event


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
