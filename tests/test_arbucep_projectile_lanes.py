"""Arbucep physical six-lane selection, packet normalization and replay parity."""
from copy import deepcopy
import pytest

from wfarsenal.damage import Scenario, ModEffect
from wfarsenal import manual_combat, combat_replay, native_replay
from wfarsenal.projectile_lanes import profile, plan, count, FRACTIONAL_DIAGNOSTIC

PATH='/Lotus/Weapons/Tenno/Archwing/Primary/NokkoArchGun/NokkoArchGun'
TYPES=('DT_EXPLOSION','DT_CORROSIVE','DT_GAS','DT_MAGNETIC','DT_RADIATION','DT_VIRAL')


def lane_contract():
    return dict(kind='cyclic-physical-projectile',length=6,rawFireIterations=6,extraPolicy='continue-sequence',initialPhase=0,
        lanes=[dict(index=i,projectile=f'/test/{i}',direct=dict(types={dtype:32.},procChance=2.0940001,
                    forcedProcs=[],critChance=.1,critMultiplier=2.9000001,projectile=f'/test/{i}'),
                radial=dict(damage={dtype:228.},status_chance=2.0940001/6,crit_chance=.1,crit_multiplier=2.9000001,
                    takes_multishot=False,takes_condition_overload=False,impact_delay_seconds=0.)) for i,dtype in enumerate(TYPES)])


@pytest.fixture
def prepare(monkeypatch):
    import app
    reference=deepcopy(manual_combat.reference())
    reference.setdefault('auditedAttacks',{})[PATH]=dict(
        name='Arbucep',fireMode=0,projectileLanes=lane_contract(),unmodeled=['arbucep-geometry-idealized','arbucep-packet-condition-overload-neutral-pending-routing','arbucep-packet-weakpoint-events-neutral-pending-routing'])
    monkeypatch.setattr(manual_combat,'reference',lambda:reference)
    original=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==PATH))
    def make(total=6.,effects=(),magazine=None,neutral=True):
        weapon=deepcopy(original)
        if magazine is not None:weapon['magazineSize']=magazine;weapon['fireModes'][0]['magazineSize']=magazine
        fx=[ModEffect('WEAPON_FIRE_ITERATIONS','SET',total),*effects]
        if neutral:fx.extend([ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)])
        fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=fx,scenario=Scenario()),[],[])
        stats,_=fight['resolve']('selected',{},0.)
        return fight,stats
    return make


def run(prepare,total=6.,health=1e12,window=.01,collect=True,**kwargs):
    fight,stats=prepare(total,**kwargs)
    result=combat_replay.replay(stats,dict(health=health,shield=0.,overguard=0.,armour=0.,baseLevel=1),
        attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,trigger_sources=fight['trigger_sources'],collect_timeline=collect)
    return result,fight,stats


@pytest.mark.parametrize('total',[6,7])
def test_plan_integer_sequence_has_no_multishot_override(total):
    lanes=lane_contract();phase=0
    for shot in range(3):
        indices,phase=plan(lanes,phase,total,shot)
        assert indices==tuple((shot*total+i)%6 for i in range(total))
        assert phase==((shot+1)*total)%6


def test_fractional_count_stratifies_legal_spawns_without_fractional_phase():
    rows=[plan(lane_contract(),0,7.25,0,(i+.5)/16) for i in range(16)]
    assert [len(indices) for indices,_ in rows].count(8)==4
    assert [len(indices) for indices,_ in rows].count(7)==12
    assert all(phase==len(indices)%6 for indices,phase in rows)


def test_individual_lane_resolver_normalizes_status_and_multishot_once(prepare):
    fight,base=prepare(13.,neutral=False)
    assert base.multishot==13.
    for i,dtype in enumerate(TYPES):
        direct,radial=fight['resolve']('selected',{'__physicalProjectileIndex':i},0.)
        assert direct.damage_types=={dtype:32.}
        assert radial.damage_types=={dtype:228.}
        assert direct.multishot==radial.multishot==1.
        assert direct.status_chance==pytest.approx(2.0940001/6)
        assert radial.status_chance==pytest.approx(2.0940001/6)
        assert direct.crit_chance==radial.crit_chance==.1
        assert direct.ignore_headshot_bonus and radial.radial_only


@pytest.mark.parametrize('total',[6,7])
def test_integer_pull_emits_each_lane_once_per_actual_projectile(prepare,total):
    result,_,_=run(prepare,total)
    assert result['shots']==1
    assert result['directWindow']==pytest.approx(total*260.)
    assert [v['lane'] for v in result['physicalProjectileTrace']]==[i%6 for i in range(total)]
    assert result['physicalProjectilePhase']==total%6


def test_killing_packet_discards_same_pull_remainder_but_advances_all_emitted(prepare):
    result,_,_=run(prepare,7.,health=1.,window=1.)
    assert result['killEvents']==result['shots']
    assert result['staleComponents']==6*result['shots']
    assert [v['lane'] for v in result['physicalProjectileTrace']]==[i%6 for i in range(result['shots'])]
    assert result['physicalProjectilePhase']==result['shots']%6


def test_fractional_replay_operational_and_explicitly_approximate(prepare):
    result,_,_=run(prepare,7.25)
    assert result['directWindow']==pytest.approx(7.25*260.)
    assert result['projectileLaneBranches']['count']==16
    assert FRACTIONAL_DIAGNOSTIC in result['unsupported']
    assert FRACTIONAL_DIAGNOSTIC in result['limitations']
    assert 'weakpoint-kill-feedback-stratified-branches' not in result['limitations']


@pytest.mark.parametrize('total',[6.,7.,7.25])
def test_python_native_replay_parity(prepare,monkeypatch,total):
    if not getattr(native_replay.wfcore,'PHYSICAL_PROJECTILE_LANES',0):pytest.skip('build native core first')
    monkeypatch.setattr(native_replay,'ENABLED',False)
    expected,_,_=run(prepare,total,window=1.,collect=False)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    before=native_replay.STATS['native']
    actual,_,_=run(prepare,total,window=1.,collect=False)
    assert native_replay.STATS['native']>before
    for key in ('shots','directWindow','dotWindow','totalWindowDamage','killsPerMinute','staleComponents','physicalProjectilePhase'):
        assert actual[key]==pytest.approx(expected[key],abs=1e-9),key


def test_mod_coalescence_is_per_lane_before_status_weighting(prepare):
    fx=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.6,damage_type='DT_FREEZE'),
        ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.6,damage_type='DT_ELECTRICITY')]
    fight,_=prepare(6.,effects=fx,neutral=False)
    for i,dtype in enumerate(TYPES):
        direct,radial=fight['resolve']('selected',{'__physicalProjectileIndex':i},0.)
        expected={dtype:32.};expected['DT_MAGNETIC']=expected.get('DT_MAGNETIC',0.)+32.*1.2
        radial_expected={dtype:228.};radial_expected['DT_MAGNETIC']=radial_expected.get('DT_MAGNETIC',0.)+228.*1.2
        assert direct.damage_types==pytest.approx(expected)
        assert radial.damage_types==pytest.approx(radial_expected)
        assert len(direct.damage_types)==(1 if dtype=='DT_MAGNETIC' else 2)


def test_sequence_persists_through_reload_and_on_fire_is_once(prepare):
    fight,stats=prepare(7.,magazine=1)
    source=dict(id='pull',label='pull',kind='on-fire',maxStacks=100.,perEvent=1.,duration=100.,initialStacks=0.,decay='reset')
    result=combat_replay.replay(stats,dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1),
        attacks_per_second=stats.fire_rate,window_seconds=6.,combat=fight,trigger_sources=[source],collect_timeline=True)
    assert result['reloads']>=1 and result['shots']>=2
    assert len(result['physicalProjectileTrace'])==7*result['shots']
    assert [v['lane'] for v in result['physicalProjectileTrace']]==[i%6 for i in range(7*result['shots'])]
    assert result['physicalProjectilePhase']==result['shots']%6
    assert result['triggerSeries'][0]['series'][-1]==result['shots']


@pytest.mark.parametrize('health',[1.,500.,1e12])
def test_native_shadow_full_result_including_phase_and_status(prepare,monkeypatch,health):
    if not getattr(native_replay.wfcore,'PHYSICAL_PROJECTILE_LANES',0):pytest.skip('build native core first')
    monkeypatch.setattr(native_replay,'SHADOW',True)
    monkeypatch.setattr(native_replay,'ENABLED',True)
    run(prepare,7.25,health=health,window=3.,collect=False,neutral=False,
        effects=[ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.6,damage_type='DT_FIRE'),
                 ModEffect('WEAPON_INIT_DAMAGE_MOD','STACKING_MULTIPLY',1.)])


def test_first_round_damage_applies_each_direct_lane_once(prepare):
    result,_,_=run(prepare,6.,effects=[ModEffect('WEAPON_INIT_DAMAGE_MOD','STACKING_MULTIPLY',1.)])
    assert result['directWindow']==pytest.approx(6.*(64.+228.))


def test_fractional_trajectory_keeps_representative_phase_discrete(prepare):
    result,_,_=run(prepare,7.25,window=1.)
    assert isinstance(result['physicalProjectilePhase'],int)
    assert all(isinstance(v['lane'],int) for v in result['physicalProjectileTrace'])
    assert all(isinstance(v,int) for v in result['projectileLaneBranches']['phaseByBranch'])


def test_hash_pinned_importer_recovers_six_packets_and_rejects_source_drift():
    from types import SimpleNamespace
    from tools import import_arbucep_projectile_lanes as importer
    lanes=lane_contract()['lanes']
    selector=dict(fireIterations=6,projectileType='',chargedProjectileType='',advanceProjectileSequenceOnFire=1,
        MultiShotProjectileType='NokkoArchGunGuidedBlastProj',MultiShotChargedProjectileType='',
        projectileSequenceList=[lane['projectile'] for lane in lanes])
    objects={PATH:{'HeavyBehaviors':[{'fire:LotusWeaponProjectileFireBehavior':selector}]}}
    for lane in lanes:
        dtype=next(iter(lane['direct']['types']))
        objects[lane['projectile']]=dict(AttackData=dict(Amount=32,Type=dtype,ProcChance=2.0940001),
            ExplosiveAttack=dict(Amount=228,Type=dtype,ProcChance=2.0940001),DamageRadius=4,
            CriticalChance=.1,CriticalMultiplier=2.9000001)
    class Packages:
        entities={path:(None,SimpleNamespace(attr=None)) for path in objects}
        def resolve(self,path):return objects[path]
        def locate(self,owner,ref):return ref
        def parent(self,path):return ''
    pkg=Packages()
    patch=importer.extract(pkg);entry=patch['weapons'][PATH]['0']
    assert entry['packageSha256']=='00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06'
    assert [next(iter(lane['direct']['types'])) for lane in entry['projectileLanes']['lanes']]==list(TYPES)
    assert len(entry['nativeSources'])==7
    selector['projectileType']='other'
    with pytest.raises(ValueError,match='selector'):importer.extract(pkg)
    selector['projectileType']=''
    objects[lanes[0]['projectile']]['ExplosiveAttack']['Amount']=999
    with pytest.raises(ValueError,match='packet'):importer.extract(pkg)


def test_real_lane_source_retains_independent_co_and_native_event_contract():
    import app
    from wfarsenal.damage import co_variant
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==PATH)
    fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=[
        ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),
        ModEffect('WEAPON_DAMAGE_IF_VICTIM_PROC_ACTIVE','STACKING_MULTIPLY',.8),
        ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)],
        scenario=Scenario()),[],[])
    direct,radial=fight['resolve']('selected',{'__physicalProjectileIndex':0},0.)
    assert direct.total_damage==pytest.approx(64.)
    contact_spec=deepcopy(direct._co_spec);contact_spec.victim_status_count=1
    assert co_variant(direct,contact_spec,direct.co_bucket).total_damage==pytest.approx(64.*1.8)
    assert radial.total_damage==pytest.approx(456.)
    radial_spec=deepcopy(radial._co_spec);radial_spec.victim_status_count=1
    assert co_variant(radial,radial_spec,radial.co_bucket).total_damage==pytest.approx(456.)
    assert direct._co_spec.gunco_independent
    assert direct.delayed_radial_hit_event and radial.delayed_radial_hit_event
    assert radial.radial_victim_crit and direct.ignore_headshot_bonus
