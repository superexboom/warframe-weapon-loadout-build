"""Cryotra draft: native known Cold ticks, no fabricated missing mechanics."""
from copy import deepcopy
import pytest
import app
from wfarsenal import manual_combat, native_replay, combat_replay
from wfarsenal.damage import Scenario,ModEffect
from tools.import_cryotra_field import build_draft,WEAPON,PROJECTILE


class Package:
    def __init__(self):
        self.weapon=dict(Behaviors=[{'fire:ProjectileFireBehavior':dict(projectileType='CryoxionProjectile',fireIterations=1,IgnoreFireIterations=0)}])
        self.projectile=dict(Embed=1,EmbedAttack=dict(Type='DT_FREEZE',Amount=20.,ProcChance=.30000001),
            EmbedTime=[5.,5.],EmbedDamageRadius=1.5,EmbedFallOff=.69999999,
            CriticalChance=.1,CriticalMultiplier=1.75,AttackData=dict(ForcedProcs=['PT_CHILLED']))
    def resolve(self,path):return self.weapon if path==WEAPON else self.projectile
    def _path_to_file(self,path):return app.ROOT/'.local/not-used-for-cryotra-draft-tests'/path.lstrip('/')


def draft():
    row=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    clock=dict(clientBuild='fixture',clientSha256='fixture',
        tick=dict(function='0x140297cf0',repeatSchedule='scheduler(delay=1.0f)'),
        embedEntry=dict(immediateCall='embed -> 0x140297cf0'))
    return build_draft(Package(),row,clock)


def test_draft_preserves_fire_cadence_and_adds_native_identity_and_direct_proc():
    data=draft();row=data['weapon'];source=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    assert row['fireModes'][0]['fireRate']==source['fireModes'][0]['fireRate']
    assert row['fireModes'][0]['damage']['projectile']==PROJECTILE
    assert row['fireModes'][0]['damage']['forcedProcs']==['PT_CHILLED']
    field=data['entry']['lingering']
    assert field['damage']=={'cold':20.} and field['tick_rate']==1. and field['duration_seconds']==5.
    assert field['status_chance']==.30000001 and field['radius_m']==1.5
    assert all('unverified' in value for value in data['entry']['unmodeled'])


@pytest.mark.parametrize('native',[False,True])
def test_draft_one_living_target_receives_five_immediate_one_second_ticks(native,monkeypatch):
    if native and native_replay.wfcore is None:pytest.skip('native core unavailable')
    data=draft();weapon=data['weapon'];weapon['fireModes'][0]['fireRate']=.01
    refs=deepcopy(manual_combat.reference());refs.setdefault('auditedAttacks',{})[WEAPON]=data['entry']
    monkeypatch.setattr(manual_combat,'reference',lambda:refs)
    effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.)]
    combat=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=Scenario()),[],[])
    stats,radial=combat['resolve']('selected',{})
    assert radial is None
    assert stats.native_forced_procs=={'DT_FREEZE':1.}
    part,rate,duration=stats._lingering
    assert part.damage_types=={'DT_FREEZE':20.}
    assert (rate,duration)==(1.,5.)
    run=native_replay.trajectory if native else combat_replay._reference_trajectory
    result=run(stats,dict(health=1e12,shield=0.,armour=0.,baseLevel=1),attacks_per_second=stats.sustained_attack_rate,
        combat=combat,trigger_sources=[],window_seconds=4.5,collect_timeline=False)
    assert result['shots']==1
    assert result['directWindow']==pytest.approx(10.+5.*20.)
    assert set(data['entry']['unmodeled'])<=set(result['unsupported'])


def test_draft_rejects_changed_native_payload_instead_of_guessing():
    pkg=Package();pkg.projectile['EmbedTime']=[4.,6.]
    row=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    with pytest.raises(ValueError,match='field changed'):build_draft(pkg,row,{})



def test_shipped_cryotra_model_has_verified_payload_and_keeps_remaining_limits():
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    combat=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    stats,_=combat['resolve']('selected',{})
    assert stats.native_forced_procs=={'DT_FREEZE':1.}
    field,rate,duration=stats._lingering
    assert field.damage_types=={'DT_FREEZE':20.}
    assert (rate,duration)==(1.,5.)
    assert 'cryotra-cold-field-unmodeled' not in combat['unsupported']
    assert 'cryotra-field-host-death-and-spatial-persistence-unverified' in combat['unsupported']
