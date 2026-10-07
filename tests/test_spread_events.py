from copy import deepcopy
from dataclasses import replace
import json,math
from pathlib import Path
import pytest
import app
from wfarsenal.damage import ModEffect,Scenario,apply_mods
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.event_profiles import base_profile
from tests.test_combat_replay import stats,target
from tools.audit_optimizer_events import evaluate_payload

def weapon(name):
    return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)


def test_deferred_math_retained_but_not_referenced_by_production():
    from wfarsenal.deferred_spread import spread_hit_probability,resolved_angles
    st=stats(spread_min_deg=10)
    assert spread_hit_probability(st,10)==pytest.approx(math.degrees(math.asin(.25/9.75))/10)
    from wfarsenal.deferred_spread import encumber_roll_with_misses
    assert encumber_roll_with_misses(stats(multishot=2,status_chance=1),.24,hit_probability=.5)[0]==pytest.approx(1-(1-.12)**2)
    profiles=json.loads((app.ROOT/'data/mechanics/deferred-spread-profiles.json').read_bytes())['profiles']
    profile=profiles[weapon('Baza Prime')['path']]
    assert resolved_angles(profile,[ModEffect('WEAPON_SPREAD','ADD',2)],aiming=True)==(3.,3.5)

@pytest.mark.parametrize('name',['Baza Prime','Akstiletto Prime','Supra Vandal','Hema'])
@pytest.mark.parametrize('aiming',[False,True])
def test_spread_only_effects_do_not_change_replay_damage_procs_or_triggers(name,aiming):
    sc=Scenario(aiming=aiming,distance=10,trigger_policy='emergent');w=weapon(name)
    def run(effects):
        c=prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=sc),[],[])
        st,_=c['resolve']('selected',{})
        assert st.spread_min_deg is None and st.spread_max_deg is None
        return replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=4,headshot_chance=1)
    a=run([]);b=run([ModEffect('WEAPON_SPREAD','ADD',50),ModEffect('WEAPON_SPREAD','STACKING_MULTIPLY',5)])
    for key in ('totalWindowDamage','procCounts','shots','reloads','killsPerMinute'):assert a[key]==b[key]
    assert 'spread' not in b and 'spread-hit-loss-not-modeled' in b['limitations']

def test_even_injected_old_geometry_fields_do_not_thin_events():
    st=stats(fire_rate=2);kw=dict(attacks_per_second=2,window_seconds=3,combat={'distance':100})
    a=replay(st,target(),**kw);b=replay(replace(st,spread_min_deg=80,spread_max_deg=90),target(),**kw)
    assert a['totalWindowDamage']==b['totalWindowDamage'] and a['procCounts']==b['procCounts']

@pytest.mark.parametrize('name,card',[('Baza Prime','Heavy Caliber'),('Akstiletto Prime','Magnum Force')])
def test_manual_optimizer_contribution_share_non_spread_model(name,card):
    m=next(m for m in app.MANUAL_MODS if m.get('nameEn')==card)
    p=dict(weapon=weapon(name)['path'],fireMode=0,metric='killsPerMinute',mods=[dict(path=m['path'],rank=m['maxRank'],slot=0)],
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=1,aiming=True,scenario={'distance':10},triggerPolicy='emergent')
    r=evaluate_payload(p);assert r['manual']==pytest.approx(r['optimizer'],rel=1e-10)
    g=app.mod_gains_payload({**p,'mode':'equipped','candidates':[m['path']]})
    without=app.simulate_manual_payload({**p,'mods':[]})['benchmarkTimeline']['killsPerMinute']
    assert g['gains'][m['path']]['value']==pytest.approx(without,abs=.001)
    assert 'spread' not in app.simulate_manual_payload(p)['benchmarkTimeline']


def test_tiberon_native_three_round_clock_is_used():
    w=weapon('Tiberon');c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=Scenario(distance=10,aiming=True)),[],[])
    st,_=c['resolve']('selected',{})
    assert c['baseBurst']['count']==3
    assert c['baseBurst']['delay_seconds']==pytest.approx(.06)
    st=replace(st,crit_chance=0,status_chance=0,fire_rate=20/3)
    c['resolve']=lambda *a:(st,None)
    r=replay(st,target(),attacks_per_second=20/3,window_seconds=.269,combat=c)
    assert r['shots']==3
    r=replay(st,target(),attacks_per_second=20/3,window_seconds=.271,combat=c)
    assert r['shots']==4
    c['baseBurst']=None
    flat=replay(st,target(),attacks_per_second=20/3,window_seconds=.271,combat=c)
    assert flat['shots']==2


@pytest.mark.parametrize('rate_bonus,edge',[(0,.4),(1,.2)])
def test_hema_native_burst_has_three_paid_rounds_before_next_pull(rate_bonus,edge):
    w=weapon('Hema');sc=Scenario(aiming=True,distance=10)
    fx=[ModEffect('WEAPON_FIRE_RATE','STACKING_MULTIPLY',rate_bonus),ModEffect('WEAPON_CRIT_CHANCE','SET',0),ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    c=prepare(dict(weapon=w,fire_mode=0,effects=fx,scenario=sc),[],[])
    st,_=c['resolve']('selected',{})
    assert c['baseBurst']=={'count':3,'delay_seconds':.1}
    assert st.spread_min_deg is None and st.spread_max_deg is None
    before=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=edge-.001,combat=c)
    after=replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=edge+.001,combat=c)
    assert before['shots']==3 and after['shots']==4
    assert before['timeline'][-1]['ammo']==st.magazine-3
    assert 'hema-player-health-cost-not-modeled' in after['unsupported']

def test_hema_burst_is_the_mode_state_not_the_damage_identity():
    # Native WeaponBurstStateBehavior belongs to the fire mode's state: a
    # different damage vector keeps it, a different trigger / pull rate does not.
    w=deepcopy(weapon('Hema'));w['fireModes'][0]['damage']['types']={'DT_VIRAL':52.}
    assert base_profile(w)=={'burst':{'count':3,'delay_seconds':.1}}
    w['fireModes'][0]['fireRate']=4.
    assert not base_profile(w)


def test_native_bursts_follow_their_own_mode_and_incarnon_form():
    from wfarsenal.event_profiles import native_burst
    assert native_burst(weapon('Hind'),0)=={'count':5,'delay_seconds':.12}
    assert native_burst(weapon('Hind'),1) is None
    assert native_burst(weapon('Quartakk'),0)=={'count':4,'delay_seconds':0.}
    sybaris=weapon('Sybaris Prime')
    assert native_burst(sybaris,0)['count']==2 and native_burst(sybaris,1)['count']==4
    assert native_burst(weapon('Burston'),1) is None  # automatic Incarnon form


def _burst_replay(name,mode,window):
    w=weapon(name);sc=Scenario(aiming=False,distance=10)
    fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0),ModEffect('WEAPON_PROC_CHANCE','SET',0)]
    c=prepare(dict(weapon=w,fire_mode=mode,effects=fx,scenario=sc),[],[])
    st,_=c['resolve']('selected',{})
    return c,st,replay(st,target(),attacks_per_second=st.fire_rate,window_seconds=window,combat=c)


def test_quartakk_pull_fires_its_four_barrels_together():
    # Native NumShots 4, BurstDelay 0: one pull is four paid rounds at once.
    c,st,r=_burst_replay('Quartakk',0,1./st_rate('Quartakk')-.001)
    assert c['baseBurst']=={'count':4,'delay_seconds':0.}
    assert r['shots']==4 and r['timeline'][-1]['ammo']==st.magazine-4


def test_remaining_clip_burst_empties_the_magazine_in_one_pull():
    # Cyanex burst mode: BurstRemainingClip = 1, 11 rounds 0.08 s apart.
    c,st,r=_burst_replay('Cyanex',1,10*.08+.001)
    assert c['baseBurst']['remainingClip'] and st.magazine==11
    assert r['shots']==11


def st_rate(name):
    return weapon(name)['fireModes'][0]['fireRate']


def test_zarr_bomblets_are_replayed_with_their_own_hit_and_explosion():
    # Native NumClusterProjectiles 6 x GrnCannonClusterMiniProjectile:
    # AttackData 15 Impact + ExplosiveAttack 50 (tools/import_cluster_submunitions.py).
    w=weapon('Zarr');sc=Scenario(aiming=False,distance=10)
    c=prepare(dict(weapon=w,fire_mode=0,effects=[],scenario=sc),[],[])
    st,radial=c['resolve']('selected',{})
    parts=[radial,*getattr(radial,'_additional_radials',())]
    bomblets=[p for p in parts if p.multishot==6.]
    assert len(parts)==3 and len(bomblets)==2
    assert sorted(round(sum(p.damage_types.values()),6) for p in bomblets)==[15.,50.]
    assert 'cluster-submunitions-unmodeled' not in (c.get('unsupported') or [])


def test_zarr_bomblet_hit_takes_condition_overload_on_the_parent_value():
    # Wiki CO catalog: "Zarr | Cannon Child Bomb | Projectile | 15 | 25 | 167% | Adding":
    # the bomblet hit gains what the 25-damage shell gains per +100%; its explosion takes none.
    def parts(effects):
        c=prepare(dict(weapon=weapon('Zarr'),fire_mode=0,effects=effects,scenario=Scenario(aiming=False,distance=10)),[],[])
        st,radial=c['resolve']('selected',{},2)
        hit=next(p for p in radial._additional_radials if 'DT_IMPACT' in p.damage_types)
        blast=next(p for p in radial._additional_radials if 'DT_EXPLOSION' in p.damage_types)
        return sum(st.damage_types.values()),sum(hit.damage_types.values()),sum(blast.damage_types.values())
    shell0,hit0,blast0=parts([])
    shell1,hit1,blast1=parts([ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',1.)])
    assert (shell0,hit0)==(25.,15.) and shell1>shell0
    assert hit1-hit0==pytest.approx(shell1-shell0)  # 15-damage bomblet, 25-damage shell, same gain
    assert blast1==pytest.approx(blast0)


def test_native_charge_fills_unaudited_modes_and_keeps_its_modifier():
    # tools/import_charge_profiles.py: the pinned export has chargeTime=null.
    assert base_profile(weapon('Ferrox'),0)['charge']=={'seconds':.5,'source':'native-ChargeTime','scalesWithFireRate':True}
    phantasma=weapon('Phantasma')
    charge=base_profile({**phantasma,'__selectedFireMode__':1},1)['charge']
    assert charge['scalesWithFireRate'] is False  # ChargeModifier WEAPON_CHARGE_RATE
    # An audited charge keeps its seconds and gains the native modifier.
    assert base_profile(weapon('Opticor Vandal'),0)['charge']['scalesWithFireRate'] is True


def test_hitscan_explosion_and_embed_field_come_from_native_records():
    trumna=base_profile(weapon('Trumna'),0)
    assert trumna['radials'][0]['damage']=={'heat':50.} and trumna['radials'][0]['nativeField']=='RadialDamage'
    cloud=base_profile(weapon('Mutalist Cernos'),0)['lingering']
    assert cloud['damage']=={'toxin':5.} and cloud['duration_seconds']==10. and cloud['forcedProcs']==['PT_POISONED']
    assert base_profile(weapon('Pox'),0)['lingering']['duration_seconds']==5.  # native EmbedTime, WFSim 4


def _local(name, mode, seconds=30, level=170, mods=()):
    from tools.compare_archgun_board_builds import local_replay
    p=dict(weapon=weapon(name)['path'],fireMode=mode,mods=list(mods),arcanes=[],enemy=app._BENCHMARK_ENEMY_PATH,level=level,
           steelPath=level>=100,headshotChance=0.,aiming=False,triggerPolicy='emergent',slotPolarities=[None]*8)
    return local_replay(p,duration=seconds)['replay']


def test_spear_throw_reloads_after_every_shot():
    # Static analysis: LotusSpearGunStateBehavior post-shot -> state 8 / reload event
    # with the weapon's reload duration (tools/import_reload_after_shot.py).
    from wfarsenal.event_profiles import reloads_after_every_shot
    assert reloads_after_every_shot(weapon('Scourge'),1) and not reloads_after_every_shot(weapon('Scourge'),0)
    ev=_local('Scourge',1)
    assert ev['shots']==ev['reloads']==9  # 1 s wind-up + 2.5 s reload per throw


def test_kill_charged_alternate_fires_once_per_five_primary_kills():
    from wfarsenal.event_profiles import kill_charge_cycle
    assert kill_charge_cycle(weapon('Trumna'),1)=={'hits':5.,'pool':1.,'enterSeconds':1.,'exitSeconds':0.,'chargeOn':'kills','killCharged':True}
    assert kill_charge_cycle(weapon('Trumna'),0) is None
    ev=_local('Trumna',1,seconds=60,level=10)
    assert ev['transforms']>0 and ev['transforms']<=2*ev['killEvents']/5+2


def test_remote_mine_blast_waits_for_detonation_and_counts_once():
    from wfarsenal.event_profiles import base_profile
    aegrit=base_profile(weapon('Aegrit'),0)
    assert aegrit['manualDetonation']=={'maxProjectiles':4} and aegrit['radials'][0]['damage']=={'blast':797.}
    ev=_local('Aegrit',0)
    assert ev['manualDetonation']['detonations']==ev['shots']


def test_cold_crit_damage_skips_area_damage():
    # wiki Cold / Puncture: neither crit bonus applies to Area of Effect damage.
    import wfarsenal.combat_replay as module
    assert 'if st.radial_only:puncture=cold=0.0' in Path(module.__file__).read_text(encoding='utf-8')
