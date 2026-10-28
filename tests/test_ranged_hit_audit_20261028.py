"""Native projectile head flags must survive mode selection and every score path.

Source: current Packages SHA256 00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06.
These are direct-hit projectiles; IgnoreHeadShotBonus is not a radial/event flag.
"""
from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal import event_profiles, mods_native, native_replay, status_native
from wfarsenal.damage import Scenario, damage_against, expected_dot_damage
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay

FLAGGED = [('Paris',1),('Paris Prime',1),('MK1-Paris',1),('Dread',1),
           ('Lex',1),('Lex Prime',1),('Alternox',0),('Steflos',0),('Felarx',1),('Nataruk',0),('Arca Plasmor',0),('Tenet Arca Plasmor',0),
           ('Fulmin',0),('Fulmin Prime',0),('Alternox Prime',0)]


def target():
    return dict(health=1e8,armour=0.,shield=0.,overguard=0.,baseLevel=1,
                hitProxies=[dict(part='HEAD',damageAtten=3.,criticalMultiplier=2.)])


def bound(name,mode):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    combat=prepare(dict(weapon=weapon,fire_mode=mode,effects=[],scenario=Scenario()),[],[])
    stats,_=combat['resolve']('selected',{})
    return weapon,stats,combat


@pytest.mark.parametrize('name,mode',FLAGGED)
def test_native_projectile_flag_reaches_selected_mode_and_preserves_damage_brackets(name,mode,monkeypatch):
    monkeypatch.setattr(mods_native,'SHADOW',True)
    weapon,stats,combat=bound(name,mode)
    assert event_profiles.ignores_headshot_bonus(weapon,mode)
    selected,_=app.optimizer._select_fire_mode(weapon,mode,weapon_type=app.optimizer._weapon_type(None,weapon))
    assert event_profiles.ignores_headshot_bonus(selected,0)
    assert stats.ignore_headshot_bonus and not stats.radial_only
    stats=replace(stats,crit_chance=1.,crit_multiplier=2.)
    body=damage_against(stats,target())['perShot']
    assert damage_against(stats,target(),hit_location='head')['perShot']==body
    acuity=replace(stats,weakpoint_damage_bonus=3.5)
    assert damage_against(acuity,target(),hit_location='head')['perShot']==body
    deadhead=replace(stats,headshot_bonus_multiplier=1.3)
    assert damage_against(deadhead,target(),hit_location='head')['perShot']==pytest.approx(body*1.3)
    weakcrit=replace(stats,weakpoint_crit_chance_bonus=1.)
    assert damage_against(weakcrit,target(),hit_location='head')['perShot']>body


@pytest.mark.parametrize('name,mode',[('Paris',0),('Paris Prime',0),('Dread',0),('Lex',0),('Lex Prime',0),('Felarx',0),('Alternox Prime',1),('Fulmin',1),('Fulmin Prime',1)])
def test_plain_modes_and_explicit_false_do_not_inherit_the_wave_rule(name,mode):
    weapon,stats,_=bound(name,mode)
    assert not event_profiles.ignores_headshot_bonus(weapon,mode)
    assert not stats.ignore_headshot_bonus


def test_classification_follows_component_projectile_not_weapon_name():
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Alternox Prime'))
    assert event_profiles.ignores_headshot_bonus(weapon)  # impact flag wins over projectile false
    weapon['fireModes'][0]['damage']['projectile']='/Lotus/Weapons/Tenno/LongGuns/PrimeAlternox/PrimeAlternoxWaveProjMS'
    assert event_profiles.ignores_headshot_bonus(weapon)
    weapon['fireModes'][0]['damage']['projectile']='/unknown/same-weapon-new-projectile'
    assert not event_profiles.ignores_headshot_bonus(weapon)


@pytest.mark.parametrize('name,mode',FLAGGED)
def test_direct_wave_still_generates_head_hit_events_with_native_parity(name,mode,monkeypatch):
    monkeypatch.setattr(native_replay,'SHADOW',True)
    _,stats,_=bound(name,mode)
    core=native_replay.wfcore
    native_stacks=[]
    original=core.trajectory
    def observed(*args):
        result=original(*args)
        native_stacks.append(list(result['sourceStacks']))
        return result
    monkeypatch.setattr(core,'trajectory',observed)
    sources=[dict(id='head',label='head',kind='on-headshot',duration=20.,maxStacks=3.,perEvent=1.)]
    replay(stats,target(),combat=dict(resolve=lambda *_:(stats,None)),trigger_sources=sources,
           attacks_per_second=3.,window_seconds=1.,headshot_chance=1.,collect_timeline=False)
    # avgStacks is a timeline statistic: collect_timeline=False leaves it zero
    # even for ordinary direct shots. Read the native terminal state instead.
    assert native_stacks and native_stacks[-1][0]>0
    reference=replay(stats,target(),combat=dict(resolve=lambda *_:(stats,None)),trigger_sources=sources,
                     attacks_per_second=3.,window_seconds=1.,headshot_chance=1.,collect_timeline=True)
    assert reference['triggerSeries'][0]['avgStacks']>0


@pytest.mark.parametrize('name,mode',FLAGGED)
def test_native_status_score_retains_exact_projectile_head_semantics(name,mode,monkeypatch):
    monkeypatch.setattr(status_native,'SHADOW',True)
    _,stats,_=bound(name,mode)
    status_native.score(stats,target(),dict(hit_location='head'),status_rate_multiplier=1.,damage_rate_multiplier=1.,total=True)


def test_electric_head_seed_still_receives_deadhead_twice_after_flag_recovery():
    _,stats,_=bound('Alternox',0)
    plain=expected_dot_damage(stats,target(),hit_location='head')['perType']['DT_ELECTRICITY']['seedPerSecondPerProc']
    boosted=expected_dot_damage(replace(stats,headshot_bonus_multiplier=1.3),target(),hit_location='head')['perType']['DT_ELECTRICITY']['seedPerSecondPerProc']
    assert boosted/plain==pytest.approx(1.3**2)


@pytest.mark.parametrize('value',[False,True])
def test_explicit_exported_projectile_flag_does_not_require_weapon_name_mapping(value):
    weapon=dict(fireModes=[dict(damage=dict(projectile='/new-projectile',ignoreHeadshotBonus=value))])
    assert event_profiles.ignores_headshot_bonus(weapon)==value


def test_explicit_false_overrides_legacy_frozen_projectile_rule():
    weapon=dict(fireModes=[dict(damage=dict(projectile='/Lotus/Weapons/Tenno/Pistol/LexAltFireProjectile',
                                          ignoreHeadshotBonus=False))])
    assert not event_profiles.ignores_headshot_bonus(weapon)


@pytest.mark.parametrize('value',[0,1])
def test_extractor_keeps_projectile_flag_separate_from_impact_layer(value):
    from wfarsenal.extract import _resolve_damage
    class Index:
        def resolve(self,path):return dict(AttackData=dict(Amount=100,Type='DT_IMPACT',ProcChance=0),
                                           CriticalChance=0,CriticalMultiplier=1,IgnoreHeadShotBonus=value)
        def exists(self,path):return True
    damage=_resolve_damage(Index(),'/weapon',dict(projectileType='/projectile'),{'IgnoreHeadshotBonus':not value})
    assert damage['ignoreHeadshotBonus'] is bool(value)
    assert damage['impactIgnoreHeadshotBonus'] is bool(not value)


@pytest.mark.parametrize('projectile,impact,expected',[(False,False,False),(False,True,True),(True,False,True),(True,True,True)])
def test_exported_projectile_and_impact_flags_use_native_or_gate(projectile,impact,expected):
    weapon=dict(fireModes=[dict(damage=dict(projectile='/new-projectile',ignoreHeadshotBonus=projectile,
                                          impactIgnoreHeadshotBonus=impact))])
    assert event_profiles.ignores_headshot_bonus(weapon) is expected


def test_explicit_impact_false_clears_legacy_fallback_but_not_projectile_true():
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Alternox Prime'))
    damage=weapon['fireModes'][0]['damage']
    damage.update(ignoreHeadshotBonus=False,impactIgnoreHeadshotBonus=False)
    assert not event_profiles.ignores_headshot_bonus(weapon)
    damage['ignoreHeadshotBonus']=True
    assert event_profiles.ignores_headshot_bonus(weapon)


@pytest.mark.parametrize('derived',['mode','projectile','radial'])
def test_legacy_impact_rule_is_bound_to_actual_direct_mode(derived):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Fulmin'))
    weapon,_=app.optimizer._select_fire_mode(weapon,0,weapon_type='rifle')
    assert event_profiles.ignores_headshot_bonus(weapon)
    if derived=='mode':weapon['__selectedFireMode__']=1
    elif derived=='projectile':weapon['fireModes'][0]['damage']['projectile']='/new/child'
    else:weapon['fireModes'][0]['__radialPart__']=True
    assert not event_profiles.ignores_headshot_bonus(weapon)


@pytest.mark.parametrize('derived',['radial-part','ExplosiveAttack','RadialDamage','EmbedDeathAttack','StackingAttack'])
@pytest.mark.parametrize('projectile,impact',[(False,True),(True,False),(True,True)])
def test_derived_parts_do_not_reuse_explicit_parent_head_flags(derived,projectile,impact):
    # manual_combat starts these components with a copy of the parent's damage
    # dictionary. Even the new explicit fields therefore belong to the parent.
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Fulmin'))
    weapon,_=app.optimizer._select_fire_mode(weapon,0,weapon_type='rifle')
    mode=weapon['fireModes'][0]
    mode['damage'].update(ignoreHeadshotBonus=projectile,impactIgnoreHeadshotBonus=impact)
    assert event_profiles.ignores_headshot_bonus(weapon)
    if derived=='radial-part':mode['__radialPart__']=True
    else:mode['damage']['source']=derived
    assert not event_profiles.ignores_headshot_bonus(weapon)


def test_direct_child_uses_its_own_explicit_flag_without_parent_fallback():
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Fulmin'))
    damage=weapon['fireModes'][0]['damage']
    damage['projectile']='/new/direct-child'
    assert not event_profiles.ignores_headshot_bonus(weapon)
    damage.update(ignoreHeadshotBonus=True,impactIgnoreHeadshotBonus=False)
    assert event_profiles.ignores_headshot_bonus(weapon)
