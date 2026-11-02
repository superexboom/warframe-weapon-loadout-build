"""Nox prototype audit cannot contaminate ordinary Grakata or add a fake field."""
from copy import deepcopy
import pytest
from tools.import_nox_script_audit import audit,merge,WEAPON,PROJECTILE,TRIGGER,SCRIPT,WARNINGS

class Packages:
    def __init__(self):
        self.rows={WEAPON:{'MarketMode':'MM_HIDDEN'},PROJECTILE:{'Embed':1,'EmbedTime':[2,4],'DamageRadius':.75,
            'AttackData':{'Amount':30},'EmbedAttack':{'Amount':3},'EmbedDeathAttack':{'Amount':30,'HitType':'DHT_PROJECTILE'},
            'OnProjectileStoppedScript':{'Script':SCRIPT,'Function':'OnStop','_growthTriggerType':TRIGGER,'_projectileDamageRadius':1.5}},
            TRIGGER:{'PhysicsBehavior':'/EE/Types/Physics/KinematicTrigger','Radius':1.5,'Scripts':[{'Script':{'Script':SCRIPT,'Function':'OnOverlap'}}]}}
    def resolve(self,path):return self.rows[path]


def test_overlap_trigger_is_not_promoted_to_damage_and_unrelated_modes_stay_intact(monkeypatch):
    import tools.import_nox_script_audit as module
    monkeypatch.setattr(module,'source_rows',lambda *_:[])
    ev=audit(Packages());source={'auditedAttacks':{'/ordinary-grakata':{'radials':[{'damage':{'toxin':99}}]}}};original=deepcopy(source)
    joined=merge(source,ev)
    assert source==original and joined['auditedAttacks']['/ordinary-grakata']==original['auditedAttacks']['/ordinary-grakata']
    assert ev['nonDamageTrigger']['hasAttackData'] is False
    assert ev['avatarBranch']['type']=='Avatar'
    assert ev['avatarBranch']['createsGrowthTrigger'] is False
    assert ev['avatarBranch']['liveHostRadius']==.75
    tick=ev['stableAvatarTickContract']
    assert tick['embedDamageRadius']==0. and tick['damageHitType']==7
    assert tick['damage']=={'toxin':3.} and tick['takesConditionOverload'] is False
    assert tick['genericHit'] is True and tick['genericCriticalHit'] is True
    policy=ev['stableAvatarProfile']
    assert sum(policy['attachedTicks']['tickSurvivalWeights'])==3.5
    assert policy['radial']['impact_delay_seconds']==3.1125
    assert policy['radial']['radius_m']==.75 and policy['radial']['takes_condition_overload'] is False
    assert 'script-raw0-loop-backedge-not-independently-decoded' not in ev['unresolved']
    assert 'same-victim-overlap-and-host-class-branch' not in ev['unresolved']
    assert not any(k in joined['auditedAttacks'][WEAPON] for k in ['radial','radials','lingering','periodicTriggers'])
    assert merge(joined,ev)==joined
    assert joined['auditedAttacks'][WEAPON]['noxAvatarLifecycle']==policy
    assert not set(WARNINGS).intersection(joined['auditedAttacks'][WEAPON]['unmodeled'])


def test_changed_trigger_damage_cannot_reuse_nondamaging_contract(monkeypatch):
    import tools.import_nox_script_audit as module
    monkeypatch.setattr(module,'source_rows',lambda *_:[])
    p=Packages();p.rows[TRIGGER]['AttackData']={'Amount':3}
    with pytest.raises(ValueError,match='nondamaging'):audit(p)


def test_stable_avatar_independent_projectiles_ticks_death_and_ordinary_grakata(monkeypatch):
    import app
    from wfarsenal import manual_combat,combat_replay,native_replay
    from wfarsenal.damage import Scenario,ModEffect
    import tools.import_nox_script_audit as module
    monkeypatch.setattr(module,'source_rows',lambda *_:[])
    policy=audit(Packages())['stableAvatarProfile']
    assert manual_combat.reference()['auditedAttacks'][WEAPON]['noxAvatarLifecycle']==policy
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    target=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    def prepare(ms=1.,slow=True,extra=()):
        effects=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),
            ModEffect('WEAPON_FIRE_ITERATIONS','SET',ms),*extra]
        if slow:effects.append(ModEffect('WEAPON_FIRE_RATE','SET',.1))
        fight=manual_combat.prepare(dict(weapon=weapon,fire_mode=0,effects=effects,scenario=Scenario()),[],[])
        stats,radial=fight['resolve']('selected',{},0.)
        assert radial is None and len(stats._nox_projectile)==2
        assert stats._nox_projectile[0].radial_victim_crit is False
        return fight,stats
    def replay(fight,stats,window=3.2,health=None):
        return combat_replay.replay(stats,{**target,**({'health':health} if health is not None else {})},
            attacks_per_second=stats.fire_rate,window_seconds=window,combat=fight,
            trigger_sources=[dict(id='hits',label='hits',kind='on-hit',maxStacks=10000.,perEvent=1.,duration=100.,initialStacks=0.,decay='reset')],
            collect_timeline=True)
    monkeypatch.setattr(native_replay,'ENABLED',False)
    fight,stats=prepare()
    direct=stats.total_damage
    for window,bonus in ((.01,3.),(3.01,10.5),(3.2,40.5)):
        result=replay(fight,stats,window)
        assert result['shots']==1
        assert result['directWindow']==pytest.approx(direct+bonus)
    result=replay(fight,stats)
    assert result['triggerSeries'][0]['series'][-1]==pytest.approx(5.5)
    fight,stats=prepare(2.5)
    assert replay(fight,stats)['directWindow']==pytest.approx((direct+40.5)*2.5)
    fight,stats=prepare(extra=(ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.),))
    assert replay(fight,stats)['directWindow']==pytest.approx(2.*(direct+40.5))
    fight,stats=prepare(extra=(ModEffect('WEAPON_INIT_DAMAGE_MOD','STACKING_MULTIPLY',1.),))
    assert replay(fight,stats,.01)['directWindow']==pytest.approx(63.)
    fight,stats=prepare(2.)
    killed=replay(fight,stats,health=1.)
    assert killed['directWindow']==pytest.approx(killed['shots'])
    assert killed['staleComponents']>0
    fight,stats=prepare(slow=False)
    overlapping=replay(fight,stats,2.1)
    assert overlapping['shots']>1
    assert overlapping['directWindow']>overlapping['shots']*(direct+3.)
    ordinary=next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Grakata' and w['path']!=WEAPON)
    plain=manual_combat.prepare(dict(weapon=ordinary,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    plainstats,_=plain['resolve']('selected',{},0.)
    assert not hasattr(plainstats,'_nox_projectile') and not plain.get('noxAvatarLifecycle')
    fight,stats=prepare(2.5,extra=(ModEffect('WEAPON_INIT_DAMAGE_MOD','STACKING_MULTIPLY',1.),))
    expected=replay(fight,stats)
    assert expected['directWindow']==pytest.approx((60.+40.5)*2.5)
    assert getattr(native_replay.wfcore,'NOX_AVATAR_LIFECYCLE',0)==1
    monkeypatch.setattr(native_replay,'ENABLED',True)
    before=native_replay.STATS['native']
    actual=combat_replay.replay(stats,target,attacks_per_second=stats.fire_rate,window_seconds=3.2,combat=fight,collect_timeline=False)
    assert native_replay.STATS['native']>before
    for key in ('directWindow','dotWindow','totalWindowDamage','shots','staleComponents'):
        assert actual[key]==pytest.approx(expected[key])
    with monkeypatch.context() as old_core:
        old_core.setattr(native_replay.wfcore,'NOX_AVATAR_LIFECYCLE',0)
        assert not native_replay.supported(stats,dict(combat=fight))
