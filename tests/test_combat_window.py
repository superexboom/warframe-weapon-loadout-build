"""Search, replay and contribution requests use the same explicit duration."""
import pytest
import app


def payload(**extra):
    weapon = next(w for w in app.CATALOG['weapons'] if w.get('nameEn') == 'Braton Prime')
    mod = next(m for m in app.EXPORTS['mods'] if m.get('nameEn') == 'Serration' and m['path'] in app.MANUAL_MODS_BY_PATH)
    return dict(weapon=weapon['path'], fireMode=0, mode='auto', profile='fast',
                mods=[dict(path=mod['path'], rank=mod['maxRank'], slot=0)],
                enemy=app._BENCHMARK_ENEMY_PATH, level=170, steelPath=True,
                headshotChance=0., triggerPolicy='emergent', **extra)


@pytest.mark.parametrize('seconds', [1., 30., 180.])
def test_fixed_build_search_and_manual_replay_share_the_requested_window(seconds):
    p = payload(windowSeconds=seconds)
    build = app.build_weapon_payload(p, fixed_mods=p['mods'])
    manual = app.simulate_manual_payload(dict(p, incarnonChoices=build['incarnonChoices']))
    assert build['evaluationContext']['windowSeconds'] == seconds
    assert manual['benchmarkTimeline']['windowSeconds'] == seconds
    assert build['build']['objectiveScore'] == pytest.approx(manual['benchmarkTimeline']['killsPerMinute'], rel=1e-12)


@pytest.mark.parametrize('value', [True, False, 0, -1, 601, float('inf'), float('nan'), '180'])
def test_invalid_windows_are_rejected(value):
    with pytest.raises(app.SimulationError, match='windowSeconds'):
        app._manual_resolve_sim_context(payload(windowSeconds=value))


def test_existing_requests_keep_the_thirty_second_window():
    assert app._manual_resolve_sim_context(payload())['window_seconds'] == 30.


def test_arena_world_uses_explicit_slots_and_ends_without_mutating_the_request(monkeypatch):
    from copy import deepcopy
    from wfarsenal.arena import World
    from wfarsenal.arena_scene import ArenaScene
    p=payload(); p.update(level=1, steelPath=False, headshotChance=0.)
    original=deepcopy(p)
    raw=dict(nav=dict(nodePositions=[(0,0,0),(0,0,3)],nativePortals=[dict(fromFace=0,toFace=1,portal=(0,0,1.5))],componentOfFace=[0,0]),
        start=dict(face=0,position=(0,0,0)),spawns=[dict(face=1,accepted=True)],focusRegion=dict(faces=[0,1]),
        collision=dict(vertices=[(-5,0,-5),(5,0,-5),(5,0,5),(-5,0,5)],triangles=[(0,1,2),(0,2,3)]))
    scene=ArenaScene(raw,native=False)
    monkeypatch.setattr('wfarsenal.arena.load_scene',lambda _:scene)
    context=app._arena_context(dict(loadout=p,scenario=dict(enemy=p['enemy'],level=1,enemies=1,waves=1,seconds=2,droneEvery=0)))
    world=World(context); result=world.run()
    assert p==original and result['loadout']['mods']==p['mods']
    assert result['stats']['shots']>0 and result['replay']['actors']
    assert result['stats']['seconds']<=2 and result['status'] in ('completed','time_limit')
    again=World(context).run()
    assert result['stats']['eventHash']==again['stats']['eventHash']

    # Continuous real damage keeps a durable target active beyond the no-kill
    # window, while an actor that cannot attack still hits the progress fuse.
    slow_context=app._arena_context(dict(loadout=p,scenario=dict(
        enemy=p['enemy'],level=170,enemies=1,waves=1,seconds=2,noKill=1,droneEvery=0)))
    slow=World(slow_context); progress=slow.run()
    assert progress['status']=='time_limit' and progress['stats']['kills']==0
    assert progress['stats']['directDamage']>0 and slow.last_damage>1.
    blocked=World(slow_context);monkeypatch.setattr(blocked,'choose',lambda:None)
    stalled=blocked.run()
    assert stalled['status']=='limited' and stalled['stats']['seconds']==pytest.approx(1.)

    # The only visible target can lie beyond sixteen nearer occluded enemies.
    # Movement sees it and holds position, so the shooting shortlist must too.
    from types import SimpleNamespace as NS
    world.live = [NS(id=i, pos=(float(i + 1), 0., 0.)) for i in range(17)]
    shot = NS(physical_lanes=())
    world.combat = NS(preview=lambda _: shot, estimate=lambda *args: 200.,
                     targets={i: NS(protected=False, pools=(100.,)) for i in range(17)})
    monkeypatch.setattr(world, 'geometry', lambda _: dict(range=100.))
    monkeypatch.setattr(world, 'aimpoint', lambda actor: (actor.pos, False))
    monkeypatch.setattr(world.scene, 'visible', lambda origin, point: point[0] == 17.)
    monkeypatch.setattr(world, 'radial_specs', lambda _: [])
    monkeypatch.setattr(world, 'recipients', lambda packet, origin, point, geometry, **kw:
                        ([(world.live[-1], 0, False, 1., 17.)], point))
    assert world.choose()['point'] == (17., 0., 0.)
