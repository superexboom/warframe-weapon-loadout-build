"""Review regressions: per-physical-packet victim state and branch life-curve moments."""
from copy import deepcopy
import pytest
from test_arbucep_projectile_lanes import prepare,PATH
from wfarsenal import combat_replay,manual_combat,native_replay
from wfarsenal.projectile_lanes import merge_life_curves

TARGET=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)


def test_branch_life_curve_preserves_mean_and_between_trajectory_count_variance():
    curves=[[(0.,1560.,0.,'direct')]]*8+[[(0.,1820.,0.,'direct')]]*8
    result=merge_life_curves(curves)
    assert sum(v[1] for v in result)==1690.
    assert sum(v[2] for v in result)==16900.


def test_branch_life_curve_keeps_correlated_phase_variance_when_paths_converge():
    result=merge_life_curves([[(0.,1.,2.,'direct'),(1.,3.,4.,'direct')],[(0.,3.,6.,'direct'),(1.,1.,8.,'direct')]])
    assert result[0][1:3]==(2.,5.)  # E[var]4 + between1
    assert sum(v[1] for v in result)==4.
    assert sum(v[2] for v in result)==10.  # cumulative within variances6/14; damage both4


@pytest.mark.parametrize('enabled',[False,True])
def test_fractional_replay_life_curve_has_same_expected_damage_as_score(prepare,monkeypatch,enabled):
    if enabled and not getattr(native_replay.wfcore,'PHYSICAL_PROJECTILE_LANES',0):pytest.skip('native core required')
    monkeypatch.setattr(native_replay,'ENABLED',enabled)
    fight,stats=prepare(6.5);curve=[]
    result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=.01,
        combat=fight,collect_timeline=False,life_curve=curve)
    assert sum(row[1] for row in curve)==pytest.approx(result['totalWindowDamage'])
    assert sum(row[1] for row in curve)==1690.
    assert sum(row[2] for row in curve)==16900.


@pytest.mark.parametrize('enabled',[False,True])
def test_victim_before_snapshot_refreshes_per_physical_packet(prepare,monkeypatch,enabled):
    if enabled and not getattr(native_replay.wfcore,'PHYSICAL_PROJECTILE_LANES',0):pytest.skip('native core required')
    monkeypatch.setattr(native_replay,'ENABLED',enabled)
    # With Cold forced on the first contact, later five contacts have a valid
    # before-hit gate. The first hit cannot gate on the status it just applied.
    reference=manual_combat.reference()
    for lane in reference['auditedAttacks'][PATH]['projectileLanes']['lanes']:
        lane['direct']['forcedProcs']=['PT_CHILLED']
    fight,stats=prepare(6.)
    source=dict(id='cold-gated',label='cold-gated',kind='on-hit',victimProcType='DT_FREEZE',
        maxStacks=100.,perEvent=1.,duration=100.,initialStacks=0.,decay='reset')
    captured=[]
    if enabled:
        original=native_replay.wfcore.trajectory
        def capture(*args):
            core=original(*args);captured.append(core['sourceStacks'][0]);return core
        monkeypatch.setattr(native_replay.wfcore,'trajectory',capture)
    result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=.01,
        combat=fight,trigger_sources=[source],collect_timeline=not enabled)
    assert result['procCounts']['DT_FREEZE']==6.
    assert (captured[-1] if enabled else result['triggerSeries'][0]['series'][-1])==5.
    assert fight['victimProcTypesBeforeHit']['DT_FREEZE']==1.


@pytest.mark.parametrize('total,admitted',[(6.,True),(6.5,False)])
def test_health_batch_does_not_bypass_fractional_whole_trajectory_strata(prepare,monkeypatch,total,admitted):
    monkeypatch.setattr(native_replay,'ENABLED',True)
    if not getattr(native_replay.wfcore,'PHYSICAL_PROJECTILE_LANES',0):pytest.skip('native core required')
    fight,stats=prepare(total)
    options=dict(attacks_per_second=stats.fire_rate,window_seconds=.01,combat=fight,collect_timeline=False,score_only=True)
    assert native_replay.supported(stats,options)==admitted
    if not admitted:
        assert native_replay.trajectory(stats,TARGET,health_targets=[None],**options) is None
        result=combat_replay.replay(stats,TARGET,**options)
        assert result['totalWindowDamage']==1690.
        assert result['projectileLaneBranches']['count']==16
