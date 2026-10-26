"""Parent shots, radial components and bomblets keep separate hit semantics."""
from dataclasses import replace
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario, damage_against, expected_status_damage
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay

NAMES=['Kuva Zarr','Zarr','Kuva Bramma','Kulstar','Kuva Tonkor','Tonkor','Kuva Ogris',
       'Akarius Prime','Sonicor','Lenz','Prisma Lenz','Stahlta','Zhuge Prime','Acceltra Prime']


def parts(name,multishot=1.,weak=False):
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')==name)
    mode=1 if name=='Stahlta' else 0
    effects=[ModEffect('WEAPON_FIRE_ITERATIONS','SET',multishot)]
    if weak:effects += [ModEffect('WEAPON_DAMAGE_WEAKPOINT','STACKING_MULTIPLY',3.5),
                       ModEffect('WEAPON_CRIT_CHANCE_WEAKPOINT','STACKING_MULTIPLY',3.5),
                       ModEffect('WEAPON_HEADSHOT_MULTIPLIER','STACKING_MULTIPLY',.3)]
    combat=prepare(dict(weapon=w,fire_mode=mode,effects=effects,scenario=Scenario(trigger_policy='emergent',distance=10.)),[],[])
    st,radial=combat['resolve']('selected',{})
    return combat,st,(radial,*getattr(radial,'_additional_radials',())) if radial else ()


def target():
    return dict(health=1e12,armour=0,shield=0,overguard=0,baseLevel=1,headshotMultiplier=3.)


@pytest.mark.parametrize('name',NAMES)
def test_explosions_and_children_follow_projectile_count_and_ignore_weakpoint_bonuses(name):
    _,_,base=parts(name);_,_,multi=parts(name,2.5);_,_,weak=parts(name,2.5,True)
    assert base and len(base)==len(multi)==len(weak)
    for a,b,c in zip(base,multi,weak):
        assert a.radial_only and b.radial_only and c.radial_only
        assert b.multishot==pytest.approx(a.multishot*2.5)
        assert damage_against(b,target(),hit_location='head')['perShot']==damage_against(b,target())['perShot']
        assert damage_against(c,target(),hit_location='head')['perShot']==damage_against(b,target())['perShot']
        assert expected_status_damage(c,target(),hit_location='head')==expected_status_damage(b,target())


@pytest.mark.parametrize('name',['Kuva Zarr','Kuva Bramma','Kulstar','Lenz','Stahlta'])
def test_isolated_radial_cannot_earn_headshot_hits_or_headshot_kills(name,monkeypatch):
    _,_,components=parts(name,2.5,True)
    for part in components:
        sources=[dict(id=kind,label=kind,kind=kind,duration=20.,maxStacks=3.,perEvent=1.)
                 for kind in ['on-headshot','on-headshot-kill']]
        combat=dict(resolve=lambda *a:(part,None))
        monkeypatch.setattr(native_replay,'SHADOW',True)
        r=replay(part,dict(target(),health=1.),combat=combat,trigger_sources=sources,
                 attacks_per_second=4.,window_seconds=1.,headshot_chance=1.,collect_timeline=False)
        assert r['weakpointKillEvents']==0
        assert all(row['avgStacks']==0 for row in r['triggerSeries'])


def test_acuity_lock_reduces_zarr_explosion_and_child_count():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Kuva Zarr')
    mod=next(m for m in app.MANUAL_MODS if m.get('nameEn')=='Primary Acuity')
    raw=app.optimizer.resolve_record(app.EXPORTS['mods'],mod['path'],kind='mod')
    from wfarsenal.damage import mod_effects
    fx=[ModEffect('WEAPON_FIRE_ITERATIONS','ADD',2.)]
    sc=Scenario(trigger_policy='emergent')
    counts=[]
    for effects in [fx,[*fx,*mod_effects(raw,mod['maxRank'],sc)]]:
        c=prepare(dict(weapon=w,fire_mode=0,effects=effects,scenario=sc),[],[])
        st,rad=c['resolve']('selected',{})
        counts.append([st.multishot,*[p.multishot for p in (rad,*rad._additional_radials)]])
    assert counts==[[3.,3.,9.,9.],[1.,1.,3.,3.]]
