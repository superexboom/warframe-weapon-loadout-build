from dataclasses import replace
from copy import deepcopy

import pytest
import app
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.event_profiles import base_profile
from wfarsenal.projectile_events import evaluate_projectile_events
from tests.test_combat_replay import target


@pytest.mark.parametrize('name,mode,delay,amount',[
    ('Stug',0,1.5,75.),('Stug',1,1.5,75.),('Stug',2,1.5,200.),
    ('Simulor',0,1.,200.),('Synoid Simulor',0,1.,240.),
])
def test_isolated_expiry_has_no_early_hit_and_no_duplicate_death_blast(name,mode,delay,amount):
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name))
    if mode==2:
        w['isIncarnonForm']=True
    c=prepare(dict(weapon=w,fire_mode=mode,effects=[],scenario=Scenario(trigger_policy='emergent')),[],[])
    st,_=c['resolve']('selected',{})
    assert getattr(st,'_primary_delay_seconds')==delay
    st=replace(st,crit_chance=0.,status_chance=0.,fire_rate=.1)
    st._primary_delay_seconds=delay
    c['resolve']=lambda *args:(st,None)
    before=replay(st,target(),attacks_per_second=.1,window_seconds=delay-.01,combat=c)
    after=replay(st,target(),attacks_per_second=.1,window_seconds=delay+.01,combat=c)
    assert before['shots']==1 and before['totalWindowDamage']==0.
    assert not before['procCounts']
    assert after['directWindow']==pytest.approx(amount)
    assert after['delayedAttackEvents']==1


def test_expired_embedded_projectile_does_not_follow_a_replaced_target():
    from tests.test_combat_replay import stats
    st=stats(damage_types={'DT_CORROSIVE':75.},status_chance=0.,fire_rate=2.,radial_only=True)
    st._primary_delay_seconds=1.5
    c={'resolve':lambda *args:(st,None)}
    result=replay(st,target(75.),attacks_per_second=2.,window_seconds=2.51,combat=c)
    assert result['killEvents']==1
    assert result['totalWindowDamage']==75.


def test_mutalist_augment_preview_does_not_multiply_the_toxin_explosion():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Mutalist Quanta')
    result=evaluate_projectile_events(w,[],fire_mode=1)
    event=next(e for e in result['events'] if e['kind']=='scriptRadial')
    assert event['baseSource']=='shieldDamageData'
    assert 'Buried Debts' in event['conditionText']
    assert 'perOccurrenceRange' not in event
    assert 'script-radial-base-unresolved' in result['unsupported']


def test_delay_profile_rejects_a_different_projectile_identity():
    w=deepcopy(next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Stug'))
    w['fireModes'][0]['damage']['projectile']='/other'
    assert not base_profile(w)


def test_another_radial_script_does_not_inherit_mutalist_shield_damage_semantics():
    from wfarsenal.extract import _script_radial_parameters
    result=_script_radial_parameters({'OnProjectileDeathScript':{
        'Script':'/Lotus/Scripts/Other.lua','Function':'OnOrbDestroyed',
        '_radialDmgPct':[.5,1.], '_radialRadius':15.}})
    assert result=={'multipliers':[.5,1.], 'radius':15.}
