from copy import deepcopy
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import Scenario,ModEffect,damage_against
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal.event_profiles import base_profile
from tests.test_combat_replay import target
from tools.audit_optimizer_events import evaluate_payload

def weapon(name):return next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
def combat(name,effects=()):
    w=weapon(name);c=prepare(dict(weapon=w,fire_mode=1,effects=effects,scenario=Scenario(trigger_policy='emergent')),[],[])
    return c,*c['resolve']('selected',{})

@pytest.mark.parametrize('name,direct,sc',[('Quanta',100,.26),('Quanta Vandal',100,.26),('Tenet Quanta',180,1.)])
def test_native_direct_and_contact_explosion_keep_their_own_damage_and_status(name,direct,sc):
    c,st,part=combat(name)
    assert st.total_damage==pytest.approx(direct) and st.status_chance==pytest.approx(sc)
    assert st.ammo_cost==10 and not st.radial_only
    assert part.total_damage==pytest.approx(150) and part.status_chance==pytest.approx(.26)
    assert part.radial_only and not part.native_forced_procs
    assert not getattr(part,'_additional_radials',())
    assert 'quanta-player-shot-detonation-unmodeled' in c['unsupported']
    assert not base_profile(weapon(name),0).get('radials')

@pytest.mark.parametrize('name',['Quanta','Quanta Vandal','Tenet Quanta'])
@pytest.mark.parametrize('multishot',[0,1.2])
def test_one_pull_pays_ten_ammo_and_hits_once_plus_one_blast_per_projectile(name,multishot):
    c,st,part=combat(name,[ModEffect('WEAPON_CRIT_CHANCE','SET',0),ModEffect('WEAPON_PROC_CHANCE','SET',0),ModEffect('WEAPON_FIRE_ITERATIONS','ADD',multishot)])
    r=replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=.1)
    assert r['shots']==1
    assert r['directWindow']==pytest.approx((st.total_damage+150)*(1+multishot))
    assert r['timeline'][-1]['ammo']==st.magazine-10
    assert r['procCounts']=={}

@pytest.mark.parametrize('name',['Quanta','Quanta Vandal','Tenet Quanta'])
def test_cube_profile_checks_mode_projectile_damage_and_ammo_identity(name):
    w=weapon(name);selected,_=app.optimizer._select_fire_mode(w,1,weapon_type='rifle')
    assert base_profile(selected)['radials']==base_profile(w,1)['radials']
    for key,value in [('projectile','/unknown'),('types',{'DT_ELECTRICITY':999.})]:
        changed=deepcopy(selected);changed['fireModes'][0]['damage'][key]=value;assert not base_profile(changed)
    changed=deepcopy(selected);changed['fireModes'][0]['ammoCost']=1;assert not base_profile(changed)

@pytest.mark.parametrize('name',['Quanta','Quanta Vandal'])
def test_radial_is_not_a_second_headshot_and_inherited_melee_is_not_a_ranged_mode(name):
    c,st,part=combat(name)
    assert damage_against(part,target(),hit_location='head')['perShot']==damage_against(part,target(),hit_location='body')['perShot']
    with pytest.raises(app.SimulationError,match='auxiliary melee'):
        app.optimizer._select_fire_mode(weapon(name),2,weapon_type='rifle')

@pytest.mark.parametrize('name',['Quanta','Quanta Vandal','Tenet Quanta'])
def test_shared_manual_optimizer_and_contribution_with_equipped_riven(name):
    m=next(m for m in app.MANUAL_MODS if m.get('nameEn')=='Serration')
    p=dict(weapon=weapon(name)['path'],fireMode=1,metric='killsPerMinute',mods=[dict(path=m['path'],rank=m['maxRank'],slot=0)],
           riven=dict(slot=1,polarity='AP_ATTACK',stats=[dict(code='1',value=100,negative=False)]),slotPolarities=[m['polarity'],'AP_ATTACK']+[None]*6,
           enemy=app._BENCHMARK_ENEMY_PATH,level=9999,steelPath=True,headshotChance=.5,aiming=True,scenario={'distance':.5},triggerPolicy='emergent')
    if name=='Tenet Quanta':p.update(innateElement='DT_MAGNETIC',innateElementValue=.6)
    r=evaluate_payload(p);assert r['manual']==pytest.approx(r['optimizer'],rel=1e-9)
    gains=app.mod_gains_payload({**p,'mode':'equipped','candidates':['__riven__']})
    without=app.simulate_manual_payload({**p,'riven':None})['benchmarkTimeline']['killsPerMinute']
    assert gains['gains']['__riven__']['value']==pytest.approx(without,abs=.001)
    assert not any(x=='projectile-component-damage-unapplied' for x in r['manualUnsupported'])


def test_cube_cannot_fire_with_two_rounds_left_or_gain_empty_reload_trigger():
    w=deepcopy(weapon('Quanta'));w['magazineSize']=12
    c=prepare(dict(weapon=w,fire_mode=1,effects=[],scenario=Scenario()),[],[])
    st,_=c['resolve']('selected',{})
    sources=[dict(id=k,label=k,kind=k,maxStacks=100,duration=30) for k in ('on-reload','on-reload-empty','on-reload-complete','on-reload-empty-complete')]
    r=replay(st,target(),combat=c,trigger_sources=sources,attacks_per_second=st.fire_rate,window_seconds=2.6)
    assert r['shots']==2 and r['reloads']==2
    sample=r['timeline'][-1]
    assert sample['triggerStacks']['on-reload-empty']==0
    assert sample['triggerStacks']['on-reload-empty-complete']==0
    assert sample['triggerStacks']['on-reload-complete']==1
    assert sample['ammo']==12


def test_cube_magazine_bonus_uses_full_ammo_gate_instead_of_fractional_debt():
    c,st,part=combat('Quanta',[ModEffect('WEAPON_CLIP_MAX','STACKING_MULTIPLY',.2)])
    assert st.magazine==72
    r=replay(st,target(),combat=c,attacks_per_second=st.fire_rate,window_seconds=30)
    assert r['shots']==56


def test_quanta_compression_and_progenitor_reach_each_attack_without_duplication():
    from wfarsenal.damage import arcane_effects
    arc=next(a for a in app.EXPORTS['arcanes'] if a['path']=='/Lotus/Upgrades/CosmeticEnhancers/Utility/ConvergeRadialAttackOnAim')
    def run(aim):
        w=weapon('Quanta');c=prepare(dict(weapon=w,fire_mode=1,effects=arcane_effects(arc,5),scenario=Scenario(aiming=aim)),[],[(arc,5,{})])
        return c['resolve']('selected',{})
    st,part=run(True);plain,blast=run(False)
    assert st.total_damage==pytest.approx(plain.total_damage*1.4)
    assert part.total_damage==pytest.approx(blast.total_damage*1.4)
    assert st.ammo_cost==pytest.approx(10*(1-.055*.4))
    assert getattr(st,'_requires_full_ammo',False)
