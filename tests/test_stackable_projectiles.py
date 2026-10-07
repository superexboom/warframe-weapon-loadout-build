from copy import deepcopy
from dataclasses import replace

import pytest
import app
from wfarsenal.damage import Scenario, ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def setup(name, *, mode=0, state=None, rate=None, multishot=1.):
    weapon = deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name))
    if mode==2:
        weapon['isIncarnonForm'] = True
    effects = [ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
               ModEffect('WEAPON_FIRE_ITERATIONS','SET',multishot)]
    combat = prepare(dict(weapon=weapon,fire_mode=mode,effects=effects,
                          scenario=Scenario(trigger_policy='emergent',combat_state=state or {})),[],[])
    original = combat['resolve']
    def resolve(*args):
        stats, radial = original(*args)
        if rate is not None:
            view = replace(stats,fire_rate=rate,magazine=1000.)
            view._stackable = stats._stackable
            stats = view
        return stats,radial
    combat['resolve'] = resolve
    stats,_ = resolve('selected',{},0)
    return stats,combat


def run(name, window, **options):
    stats,combat = setup(name,**options)
    return replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=window,combat=combat)


def test_stug_stacks_refresh_the_blob_life_until_the_tenth_detonates_it():
    # Native EmbedTime 1.5 after the blob sticks; every new stack refreshes it
    # (GooGun.lua OnProjectileStacked, wiki Stug), so a 4/s stream reaches 10.
    result = run('Stug',2.26,rate=4.)
    events = result['projectileEvents']
    explosion = next(e for e in events if e['kind']=='explosion')
    assert explosion['time']==2.25 and explosion['stacks']==10
    embeds = [e for e in events if e['kind']=='embed' and e['group']==1]
    assert [e['time'] for e in embeds]==[0.,1.,2.]
    assert result['projectileLifecycle']['explosions']==1


def test_stug_blob_expires_when_stacks_arrive_slower_than_its_life():
    result = run('Stug',4.01,rate=.5)
    explosions = [e for e in result['projectileEvents'] if e['kind']=='explosion']
    assert [(e['time'],e['stacks']) for e in explosions]==[(1.5,1),(3.5,1)]


def test_stug_multishot_reaches_cap_and_detonates_without_resetting_fuse():
    result = run('Stug',1.01,rate=4.,multishot=2.)
    explosions = [e for e in result['projectileEvents'] if e['kind']=='explosion']
    assert len(explosions)==1 and explosions[0]['time']==1.
    assert explosions[0]['stacks']==10


def test_stug_isolated_mode_retains_each_projectiles_delay_and_no_merges():
    result = run('Stug',1.51,rate=.1,multishot=2.,state={'projectileMode':'isolated'})
    assert result['projectileLifecycle']['merged']==0
    assert result['projectileLifecycle']['explosions']==2
    assert result['directWindow']==pytest.approx(2*(4+4+75))


def test_simulor_merge_curve_and_time_scaled_singularity_are_separate_events():
    result = run('Simulor',1.26,rate=3.)
    assert result['projectileLifecycle']['merged']==3
    assert result['projectileLifecycle']['singularities']==1
    assert result['projectileLifecycle']['explosions']==0
    assert result['directWindow']==pytest.approx(3*100+200*.25)
    assert not result['procCounts']


def test_full_simulor_group_cannot_gain_extra_stacks_or_reset_lifetime():
    result = run('Simulor',2.01,rate=3.)
    assert result['projectileLifecycle']['singularities']==1
    assert result['projectileLifecycle']['merged']==3
    assert any(e['kind']=='absorbed-at-cap' for e in result['projectileEvents'])


def test_simulor_isolated_and_manual_detonation_have_different_damage_clocks():
    isolated = run('Simulor',1.01,rate=.1,state={'projectileMode':'isolated'})
    assert isolated['projectileLifecycle']['explosions']==1
    assert isolated['directWindow']==pytest.approx(200.)
    manual = run('Simulor',1.51,rate=3.,state={'projectileMode':'manual','detonateAfterShots':4,'detonationWaitSeconds':.5})
    explosions = [e for e in manual['projectileEvents'] if e['kind']=='explosion']
    assert len(explosions)==1 and explosions[0]['time']==1.5
    assert explosions[0]['damageScale']==4.
    assert manual['shots']==4


def test_stug_incarnon_children_obey_count_bounces_and_death_multiplier():
    state = {'stugChildHits':2,'stugBounceHits':2,'stugBounceDelaySeconds':.1}
    result = run('Stug',5.51,mode=2,rate=.1,state=state)
    children = [e for e in result['projectileEvents'] if e['kind']=='child']
    assert len(children)==3
    assert [e['time'] for e in children]==pytest.approx([1.6,1.7,5.5])
    assert [e['damageScale'] for e in children]==[1.,1.,2.5]
    assert result['projectileLifecycle']['childProjectiles']==2
    empty = run('Stug',5.51,mode=2,rate=.1)
    assert not any(e['kind']=='child' for e in empty['projectileEvents'])
    assert result['directWindow']-empty['directWindow']==pytest.approx(200.*2*(1+1+2.5))


def test_stug_child_early_death_cancels_later_bounce_hits():
    result=run('Stug',2.11,mode=2,rate=.1,state={'stugChildHits':2,'stugBounceHits':2,
                                             'stugBounceDelaySeconds':.5,'stugChildDetonateSeconds':.6})
    events=[e for e in result['projectileEvents'] if e['kind']=='child']
    assert [(e['time'],e['damageScale']) for e in events]==pytest.approx([(2.,1.),(2.1,2.5)])


def test_stug_full_charge_consumes_ten_rounds_and_keeps_initial_embed_fuse():
    stats,combat = setup('Stug',mode=1)
    assert stats.ammo_cost==10
    assert stats._stackable[0]['initialStack']==10
    result = replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=1.51,combat=combat)
    explosions = [e for e in result['projectileEvents'] if e['kind']=='explosion']
    assert len(explosions)==1 and explosions[0]['time']==1.5
    assert explosions[0]['damageScale']==10
    assert result['shots']==1


def test_stug_full_charge_is_limited_by_modded_magazine():
    weapon = deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Stug'))
    effects=[ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',-.75)]
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=Scenario()),[],[])
    stats,_=combat['resolve']('selected',{},0)
    assert stats.magazine==5 and stats.ammo_cost==5
    assert stats._stackable[0]['initialStack']==5
