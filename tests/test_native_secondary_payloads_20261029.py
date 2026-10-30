"""Native packet admission and in-memory actual resolver/replay regressions."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from tools import import_native_secondary_payloads as importer


def synthetic_sources():
    """Minimal resolved objects for focused admission failures; no game files."""
    objects={};rows=[]
    inverse={'radiation':'DT_RADIATION','corrosive':'DT_CORROSIVE','electricity':'DT_ELECTRICITY',
             'blast':'DT_EXPLOSION','puncture':'DT_PUNCTURE','slash':'DT_SLASH','toxin':'DT_POISON'}
    for spec in importer.SPECS:
        p=spec['projectile'];charged=spec['family']=='efv8'
        fire=dict(fireIterations=1,projectileType='' if charged else p,
                  chargedProjectileType=p if charged else '',MultiShotProjectileType='',MultiShotChargedProjectileType='')
        state=dict(ChargeTime=.09,ChargeModifier='WEAPON_CHARGE_RATE')
        bank='HeavyBehaviors' if spec['family']=='larkspur' else 'Behaviors'
        behavior={'fire:ProjectileFireBehavior':fire,'state:WeaponChargedStateBehavior':state}
        modes=[{} for _ in range(spec['mode']+1)];modes[spec['mode']]=dict(index=spec['mode'],multishot=1,chargedProjectile=charged,
            damage=dict(projectile=p,types={'DT_IMPACT':spec['direct']},total=spec['direct']))
        row=dict(path=spec['path'],nameEn=spec['family'],slot='arch_gun' if bank=='HeavyBehaviors' else 'primary',fireModeSource=bank,fireModes=modes)
        objects[spec['path']]={bank:[{} for _ in range(spec['mode'])]+[behavior]}
        attack=dict(Amount=spec['amount'],ProcChance=.37)
        if len(spec['damage'])==1:attack['Type']=inverse[next(iter(spec['damage']))]
        elif spec['family']=='acceltra':attack.update(Type='DT_PHYSICAL',DT_PUNCTURE=.80000001,DT_SLASH=.19999999)
        else:attack.update(UseNewFormat=1,**{inverse[k]:v for k,v in spec['damage'].items()})
        if spec['family']=='phantasma':attack['HitType']='DHT_PROJECTILE'
        objects[p]=dict(CriticalChance=.03,CriticalMultiplier=1.5,**spec['required'])
        objects[p][spec.get('field','ExplosiveAttack')]=attack
        if spec['family']=='acceltra':objects[p]['AttackData']=dict(Type='DT_IMPACT',Amount=26,ProcChance=.059999999)
        if spec['family']=='phantasma':
            behavior['fire:LotusWeaponProjectileFireBehavior']=behavior.pop('fire:ProjectileFireBehavior')
            fire.update(AttenuateForCharge=1, AttenuateFireIterationsForCharge=0, MultiShotProjectileType=p+'MS')
            state.update(ChargeTime=.090899996, ClipSizeAffectsChargeTime=1, UseClipSizeAsDamageMultiplier=1,
                         UseClipWhileCharging=1, MinChargeRatio=1, AutoFireWhenChargeCompleted=1)
            objects[p].update(ClusterApplyDamageMultiplier=1, ClusterProjectiles=p+'/Mini')
            objects[p+'MS']={**deepcopy(objects[p]), 'ClusterProjectiles':p+'/MiniMS', 'NumClusterProjectiles':2}
            for child, contact, blast in [(p+'/Mini',3,18),(p+'/MiniMS',6,36)]:
                objects[child]=dict(CriticalChance=.03, CriticalMultiplier=1.5,
                    AttackData=dict(Type='DT_IMPACT',Amount=contact,ProcChance=.37),
                    ExplosiveAttack=dict(Type='DT_RADIATION',Amount=blast,ProcChance=.37))
        rows.append(row)
    class Packages:
        def __init__(self):
            self.objects=objects;self.entities={p:(None,SimpleNamespace(attr=None)) for p in objects}
        def resolve(self,path):return deepcopy(self.objects[path])
        def parent(self,path):return ''
        def locate(self,owner,ref):return ref if ref in self.objects else None
    return Packages(),rows


@pytest.mark.parametrize('spec',importer.SPECS,ids=lambda s:s['family']+'-'+s['path'].rsplit('/',1)[-1])
def test_native_profile_preserves_amount_status_count_and_independent_bounds(spec):
    pkg,rows=synthetic_sources();row=next(r for r in rows if r['path']==spec['path'])
    p=importer.profile(pkg,row,spec);part=p['radials'][0]
    assert part['damage']==spec['damage']
    assert part['status_chance']==.37
    assert part['emissionContract']['packetsPerSpawnedProjectile']==1
    assert part['emissionContract']['amountAlreadyIncludesProjectileCount'] is False
    assert part['takes_multishot'] is True and part['takes_condition_overload'] is False
    assert 'area_direct' not in p and 'area_direct' not in part
    assert p['unmodeled'] and p['nativeSources']


@pytest.mark.parametrize('field,value',[('DamageRadius',99),('CriticalChance',None),('ExplodeOnImpact',0)])
def test_changed_native_contract_is_rejected(field,value):
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']=='phantasma')
    pkg.objects[spec['projectile']][field]=value
    with pytest.raises(ValueError):importer.profile(pkg,next(r for r in rows if r['path']==spec['path']),spec)


def test_changed_source_type_or_projectile_identity_is_rejected():
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']=='phantasma')
    pkg.objects[spec['projectile']]['ExplosiveAttack']['Type']='DT_POISON'
    with pytest.raises(ValueError,match='type'):importer.profile(pkg,next(r for r in rows if r['path']==spec['path']),spec)
    next(r for r in rows if r['path']==spec['path'])['fireModes'][1]['damage']['projectile']='/other'
    with pytest.raises(ValueError,match='identity'):importer.profile(pkg,next(r for r in rows if r['path']==spec['path']),spec)


def test_multishot_copy_requires_identical_payload_and_count_is_not_prebaked():
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']=='phantasma');row=next(r for r in rows if r['path']==spec['path']);p=spec['projectile'];copy=p+'MS'
    pkg.objects[spec['path']]['Behaviors'][1]['fire:LotusWeaponProjectileFireBehavior']['MultiShotProjectileType']=copy
    profile=importer.profile(pkg,row,spec)
    assert profile['radials'][0]['damage']=={'radiation':73.}
    pkg.objects[copy]['ExplosiveAttack']['Amount']=99
    with pytest.raises(ValueError,match='copy'):importer.profile(pkg,row,spec)


def test_mode_merge_preserves_unrelated_other_modes_and_charge_fields():
    pkg,rows=synthetic_sources();patch=importer.build_patch(pkg,rows)
    path=next(s for s in importer.SPECS if s['family']=='phantasma')['path']
    before={'other':{'keep':1},'auditedAttacks':{'/unrelated':{'x':2},path:{'root':7,'modes':{'0':{'keep':3},'1':{'existing':4}}}}}
    after=importer.merge_patch(before,patch)
    assert before['auditedAttacks'][path]['modes']['1']=={'existing':4}
    assert after['other']==before['other'] and after['auditedAttacks']['/unrelated']=={'x':2}
    assert after['auditedAttacks'][path]['modes']['0']=={'keep':3}
    assert after['auditedAttacks'][path]['modes']['1']['existing']==4
    assert after['auditedAttacks'][path]['modes']['1']['radials'][0]['damage']=={'radiation':73.}


@pytest.fixture
def runtime(monkeypatch):
    import app
    from wfarsenal import manual_combat
    pkg,rows=synthetic_sources();patch=importer.build_patch(pkg,rows)
    payload=importer.merge_patch(manual_combat.reference(),patch)
    monkeypatch.setattr(manual_combat,'reference',lambda:payload)
    return app,manual_combat,patch


# Actual charged parent/child and replay contracts live in test_phantasma_packet_audit.py.

@pytest.mark.parametrize('spec',[s for s in importer.ADMITTED_SPECS if s['family']!='phantasma'],ids=lambda s:'runtime-'+s['family']+'-'+s['path'].rsplit('/',1)[-1])
def test_actual_prepare_retains_independent_radial_packet_for_all_admitted_modes(runtime,spec):
    app,manual,_=runtime
    from wfarsenal.damage import Scenario
    row=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==spec['path']))
    fight=manual.prepare(dict(weapon=row,fire_mode=spec['mode'],effects=[],scenario=Scenario()),[],[])
    direct,part=fight['resolve']('selected',{},0.)
    assert part is not None
    assert part.total_damage==pytest.approx(sum(spec['damage'].values()))
    assert part.multishot==direct.multishot==1.
    assert getattr(part,'_impact_delay')==pytest.approx(spec['delay'])
    assert part.radial_only and not part.area_direct
    assert set(spec['bounds'])<=set(fight['unsupported'])


def test_unclosed_branch_clock_profiles_are_evidence_only_and_not_merged():
    pkg,rows=synthetic_sources()
    patch=importer.build_patch(pkg,rows)
    assert sum(len(m) for m in patch['weapons'].values())==3
    assert len(patch['pending'])==7
    joined=importer.merge_patch({'auditedAttacks':{}},patch)
    for row in patch['pending']:
        assert row['defaultScoringExcluded'] and row['candidateOnly']
        assert row['path'] not in joined['auditedAttacks']


def test_acceltra_incremental_admission_preserves_previous_three_and_rejects_unknown_families():
    pkg,rows=synthetic_sources();patch=importer.build_patch(pkg,rows,families=['acceltra'])
    spec=next(s for s in importer.SPECS if s['family']=='acceltra')
    assert set(patch['weapons'])=={spec['path']}
    previous={'auditedAttacks':{'/previous-three':{'keep':'exact'}}}
    assert importer.merge_patch(previous,patch)['auditedAttacks']['/previous-three']=={'keep':'exact'}
    entry=patch['weapons'][spec['path']]['0']
    assert entry['nativeDirectCorrection']['damageTypes']=={'DT_IMPACT':26.}
    assert entry['radials'][0]['armingDistance']==6.
    assert entry['radials'][0]['impact_delay_seconds']==0.
    with pytest.raises(ValueError,match='pending'):importer.build_patch(pkg,rows,families=['larkspur'])


@pytest.mark.parametrize('field,value',[('ExplodeOnImpact',1),('ExplodeOnLifeExpired',1),('Embed',1)])
def test_acceltra_changed_death_branch_rejected(field,value):
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']=='acceltra')
    pkg.objects[spec['projectile']][field]=value
    with pytest.raises(ValueError,match='route'):importer.profile(pkg,next(r for r in rows if r['path']==spec['path']),spec)


def test_acceltra_native_direct_or_cosmetic_copy_drift_rejected():
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']=='acceltra');row=next(r for r in rows if r['path']==spec['path'])
    row['fireModes'][0]['damage']['types']={'DT_IMPACT':35.}
    assert importer.profile(pkg,row,spec)['directTotal']==26.
    pkg.objects[spec['projectile']]['AttackData']['Amount']=35
    with pytest.raises(ValueError,match='direct packet'):importer.profile(pkg,row,spec)
    pkg.objects[spec['projectile']]['AttackData']['Amount']=26
    copy=spec['projectile']+'Deluxe';pkg.objects[copy]=deepcopy(pkg.objects[spec['projectile']]);pkg.entities[copy]=(None,SimpleNamespace(attr=None))
    pkg.objects[spec['path']]['Behaviors'][0]['fire:ProjectileFireBehavior']['projectileSequenceList']=[spec['projectile'],copy]
    pkg.objects[copy]['ExplosiveAttack']['Amount']=70
    with pytest.raises(ValueError,match='cosmetic payload'):importer.profile(pkg,row,spec)


@pytest.mark.parametrize('distance,armed',[(0.,False),(5.999,False),(6.,True),(6.001,True),(30.,True)])
def test_actual_acceltra_distance_gate_and_once_per_projectile(runtime,monkeypatch,distance,armed):
    app,manual,_=runtime
    from wfarsenal.damage import Scenario,ModEffect
    pkg,rows=synthetic_sources();patch=importer.build_patch(pkg,rows,families=['acceltra'])
    joined=importer.merge_patch(manual.reference(),patch);monkeypatch.setattr(manual,'reference',lambda:joined)
    spec=next(s for s in importer.SPECS if s['family']=='acceltra')
    row=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path']==spec['path']))
    # Exactly the native source after root removes the historical wiki35 override.
    row['fireModes'][0]['damage'].update(types={'DT_IMPACT':26.},total=26.,shares={'DT_IMPACT':1.},procChance=.059999999)
    effect=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',1.)]
    fight=manual.prepare(dict(weapon=row,fire_mode=0,effects=effect,scenario=Scenario(distance=distance)),[],[])
    direct,part=fight['resolve']('selected',{},0.)
    assert direct.total_damage==26.
    assert (part is not None)==armed
    if part is not None:
        assert part.total_damage==pytest.approx(44.)
        assert part.multishot==direct.multishot==2.
        assert part.radial_only and not part.area_direct
        assert part.headshot_bonus_multiplier==1.
        assert part.status_chance==.37  # synthetic packet's own SC, not direct SC


@pytest.mark.parametrize('family',['phantasma','acceltra'])
def test_merge_preserves_unrelated_warnings_and_retires_only_superseded_phantasma_bounds(family):
    pkg,rows=synthetic_sources();spec=next(s for s in importer.SPECS if s['family']==family)
    patch=importer.build_patch(pkg,rows,families=[family]);path=spec['path'];mode=str(spec['mode'])
    old=['unrelated-timing-warning','phantasma-parent-explosion-and-children-unmodeled',
         'phantasma-explosion-co-and-head-event-routing-unverified','unrelated-timing-warning']
    entry={'unmodeled':old,'unrelated':{'keep':1}}
    prior={'auditedAttacks':{path:entry if mode=='0' else {'modes':{mode:entry}}}}
    after=importer.merge_patch(prior,patch)['auditedAttacks'][path]
    merged=after if mode=='0' else after['modes'][mode]
    assert merged['unmodeled'].count('unrelated-timing-warning')==1
    assert merged['unrelated']=={'keep':1}
    assert prior['auditedAttacks'][path]==(entry if mode=='0' else {'modes':{mode:entry}})
    assert ('phantasma-parent-explosion-and-children-unmodeled' in merged['unmodeled'])==(family!='phantasma')
    assert ('phantasma-explosion-co-and-head-event-routing-unverified' in merged['unmodeled'])==(family!='phantasma')
    retired={'phantasma-cluster-child-payload-unmodeled','phantasma-charge-ammo-scale-and-contact-routing-approximated'} if family=='phantasma' else set()
    assert set(spec['bounds'])-retired<=set(merged['unmodeled'])
