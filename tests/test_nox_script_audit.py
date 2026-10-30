"""Nox prototype audit cannot contaminate ordinary Grakata or add a fake field."""
from copy import deepcopy
import pytest
from tools.import_nox_script_audit import audit,merge,WEAPON,PROJECTILE,TRIGGER,SCRIPT,WARNINGS

class Packages:
    def __init__(self):
        self.rows={WEAPON:{'MarketMode':'MM_HIDDEN'},PROJECTILE:{'Embed':1,'EmbedTime':[2,4],
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
    assert not any(k in joined['auditedAttacks'][WEAPON] for k in ['radial','radials','lingering','periodicTriggers'])
    assert merge(joined,ev)==joined


def test_changed_trigger_damage_cannot_reuse_nondamaging_contract(monkeypatch):
    import tools.import_nox_script_audit as module
    monkeypatch.setattr(module,'source_rows',lambda *_:[])
    p=Packages();p.rows[TRIGGER]['AttackData']={'Amount':3}
    with pytest.raises(ValueError,match='nondamaging'):audit(p)


def test_production_exact_path_surfaces_unresolved_clock_without_fabricated_payload():
    import app
    from wfarsenal.manual_combat import prepare
    from wfarsenal.damage import Scenario
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==WEAPON)
    fight=prepare(dict(weapon=weapon,fire_mode=0,effects=[],scenario=Scenario()),[],[])
    assert set(WARNINGS).issubset(fight['unsupported'])
    stats,radial=fight['resolve']('selected',{},0.)
    assert radial is None and not hasattr(stats,'_finite_fields') and not hasattr(stats,'_source_owned_fields')
