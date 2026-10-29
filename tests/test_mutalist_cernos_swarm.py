"""Swarm field guards preserve the independent arrow embed and explicit coverage."""
from copy import deepcopy
import pytest
from tools.import_mutalist_cernos_swarm import (WEAPON,PROJECTILE,EMBED,TRIGGER,SCRIPT,profile,candidate_merge)


class Packages:
    def __init__(self):
        self.rows={WEAPON:{'Behaviors':[{'impact:LotusWeaponImpactBehavior':{'DamageUpgradeTypes':['WEAPON_DAMAGE_AMOUNT']}}]},PROJECTILE:dict(EmbedEffect=EMBED,EmbedTime=[10,10]),
            EMBED:dict(ScriptInstance=dict(Script=SCRIPT,Function='OnProjectileStopped',_damageTriggerType=TRIGGER)),
            TRIGGER:dict(DamageOnEnter=1,DamageOverTimeInterval=.5,DamageDuration=2,
                         DamageSource='PLAYER_AVATAR',DamageAttachedParent=0,
                         AttackData=dict(Type='DT_POISON',Amount=3,ProcChance=1,
                                         ForcedProcs=['PT_POISONED'],HitType='DHT_PROJECTILE'))}
    def resolve(self,path):return self.rows[path]


def row():
    return dict(path=WEAPON,fireModes=[dict(damage=dict(projectile=PROJECTILE,types={'DT_IMPACT':369.,'DT_PUNCTURE':20.5,'DT_SLASH':20.5}))])


def test_native_trigger_duration_does_not_expand_into_guessed_contact_count():
    result=profile(Packages(),row());contact=result['periodicTriggers'][0]
    assert contact['damage']=={'toxin':3.}
    assert contact['countPolicy']=='one-current-weapon-field-per-covered-target'
    assert contact['interval_seconds']==.5 and contact['tick_rate']==2.
    assert contact['damageOnEnter'] is True
    assert contact['status_chance']==1. and contact['forcedProcs']==['PT_POISONED']
    assert contact['admission']=='source-projectile-embed-with-centered-target-coverage'
    assert contact['defaultEnabled'] is True
    assert contact['coverageModel']=='inherit-enclosing-centered-target-assumption'
    assert contact['maxConcurrentFieldsPerSource']==1
    assert contact['sourceModifierAllowlist']==['weapon-base-damage','ordinary-weapon-elements']
    assert contact['duration_seconds']==10. and 'count' not in contact
    assert contact['sourceUpgradeRouting']=='projectile-creator-weapon'
    assert contact['takes_weapon_base_damage'] is True
    assert contact['takes_weapon_elements'] is True
    assert contact['takes_parent_crit'] is False
    assert contact['takes_parent_status_chance'] is False
    assert contact['payloadMultishotMultiplier'] is False


@pytest.mark.parametrize('field,value',[('DamageOnEnter',0),('DamageOverTimeInterval',1.),('DamageSource','SELF')])
def test_source_drift_refuses_reusing_native_contact_contract(field,value):
    packages=Packages();packages.rows[TRIGGER][field]=value
    with pytest.raises(ValueError,match='trigger contract'):
        profile(packages,row())


def test_candidate_merge_preserves_existing_embed_and_unrelated_audits():
    before={'auditedAttacks':{WEAPON:dict(directTotal=409.999997,projectile=PROJECTILE,
          lingering=dict(damage={'toxin':5.},tick_rate=1.,duration_seconds=10.)),
          '/unrelated':{'marker':True}}}
    saved=deepcopy(before);entry=profile(Packages(),row());merged=candidate_merge(before,entry)
    assert before==saved
    assert merged['auditedAttacks'][WEAPON]['lingering']==saved['auditedAttacks'][WEAPON]['lingering']
    assert merged['auditedAttacks']['/unrelated']=={'marker':True}
    assert candidate_merge(merged,entry)==merged


def test_changed_weapon_upgrade_categories_reject_profile():
    packages=Packages();packages.rows[WEAPON]['Behaviors'][0]['impact:LotusWeaponImpactBehavior']['DamageUpgradeTypes']=[]
    with pytest.raises(ValueError,match='upgrade context'):
        profile(packages,row())


def test_field_clock_does_not_use_damage_duration_as_lifetime_or_assume_ms_count():
    field=profile(Packages(),row())['periodicTriggers'][0]
    assert field['clockPolicy']=='decrement-dt-single-dispatch-reset-interval-no-catch-up'
    assert field['lifetimePolicy']=='source-arrow-owner-expiry-or-replacement-no-DamageDuration-cutoff'
    assert field['sourceOwnerLifetimeAfterEmbed_seconds']==10.
    assert field['expiresWithSourceOwner'] is True
    assert 'ownerCleanup' in profile(Packages(),row())['source']
    assert field['multiplicityPolicy']=='not-inferred-from-weapon-fire-iterations'
    assert field['duration_seconds']==10. and 'count' not in field
    assert field['first_periodic_delay_seconds']==0.
    assert field['damageOnEnterSeparateFromFirstPeriodic'] is True
    assert field['refreshPolicy']=='replace-entity-and-reset-timer-not-extend-existing-clock'
