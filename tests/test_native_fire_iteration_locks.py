"""Native emission locks apply to actual selected modes and both MOD engines."""
from copy import deepcopy
from types import SimpleNamespace
import pytest
import app
from wfarsenal import damage,mods_native,manual_combat,native_replay,combat_replay
from wfarsenal.damage import ModEffect,Scenario
from tools.import_native_fire_iteration_locks import updates,FIRE
from tools import import_native_fire_iteration_locks as importer

TARGET=dict(health=1e12,shield=0.,overguard=0.,armour=0.,baseLevel=1)
GRIMOIRE='/Lotus/Weapons/Tenno/Grimoire/TnGrimoire'


def current_rows():
    return [(w,i) for w in app.EXPORTS['weapons'] for i,m in enumerate(w.get('fireModes') or []) if m.get('nativeIgnoreFireIterations')]


@pytest.mark.parametrize('bonus',[-1.,0.,2.])
def test_all_admitted_native_modes_keep_raw_count_in_python_and_native(bonus,monkeypatch):
    rows=current_rows();assert len(rows)==13
    for weapon,mode in rows:
        effects=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',bonus)]
        reference=damage._apply_mods_spec_py(weapon,effects,fire_mode=mode,scenario=Scenario())
        assert reference[0].multishot==float(weapon['fireModes'][mode]['multishot'])
        if not getattr(mods_native.wfcore,'NATIVE_FIRE_ITERATION_LOCK',0):pytest.skip('native count lock build needed')
        monkeypatch.setattr(mods_native,'SHADOW',True)
        actual=damage.apply_mods_spec(weapon,effects,fire_mode=mode,scenario=Scenario())
        assert not mods_native.differences(reference,actual),(weapon['path'],mode)


def test_ordinary_primary_remains_multishot_scalable_and_selected_mode_preserves_lock():
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==GRIMOIRE)
    fx=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    assert damage.apply_mods(weapon,fx,fire_mode=0).multishot==3.
    selected=app.optimizer._select_fire_mode(weapon,1,weapon_type='pistol')[0]
    assert selected['fireModes'][0]['nativeIgnoreFireIterations']
    assert damage.apply_mods(selected,fx,fire_mode=0).multishot==1.


@pytest.mark.parametrize('native',[False,True])
def test_real_grimoire_alt_single_pull_does_not_gain_extra_orbs_from_multishot(monkeypatch,native):
    monkeypatch.setattr(native_replay,'ENABLED',native)
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==GRIMOIRE)
    results=[]
    for bonus in [0.,2.]:
        fx=[ModEffect('WEAPON_CRIT_CHANCE','SET',0.),ModEffect('WEAPON_PROC_CHANCE','SET',0.),ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',bonus)]
        fight=manual_combat.prepare(dict(weapon=deepcopy(weapon),fire_mode=1,effects=fx,scenario=Scenario()),[],[])
        stats,_=fight['resolve']('selected',{},0.);before=native_replay.STATS['native']
        result=combat_replay.replay(stats,TARGET,attacks_per_second=stats.fire_rate,window_seconds=.01,combat=fight,collect_timeline=False)
        if native:assert native_replay.STATS['native']>before
        results.append(result)
    assert results[0]['shots']==results[1]['shots']==1
    assert results[0]['totalWindowDamage']==results[1]['totalWindowDamage']


def test_old_native_mod_core_falls_back_for_locked_mode(monkeypatch):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==GRIMOIRE)
    monkeypatch.setattr(mods_native,'wfcore',SimpleNamespace())
    with pytest.raises(mods_native.Unsupported,match='updated core'):
        mods_native._build(weapon,1,Scenario())


class Packages:
    def __init__(self):
        self.raw={'Behaviors':[{'fire:Type':FIRE,'fire:LotusWeaponProjectileFireBehavior':dict(IgnoreFireIterations=1,fireIterations=1,projectileType='p',chargedProjectileType='',AttenuateForCharge=0,AttenuateFireIterationsForCharge=0)}]}
    def resolve(self,path):return self.raw
    def locate(self,owner,path):return '/weapon/'+path


def test_importer_joins_exact_projectile_and_defers_missing_damage(monkeypatch):
    monkeypatch.setattr(importer,'source_rows',lambda *_:[])
    row=dict(path='/weapon',slot='primary',fireModes=[dict(index=0,multishot=1,damage=dict(types={'DT_IMPACT':2.},projectile='/weapon/p'))])
    changes,deferred=updates(Packages(),[row]);assert not deferred
    assert changes[0]['after']['fireModes'][0]['nativeIgnoreFireIterations'] is True
    assert 'nativeIgnoreFireIterations' not in row['fireModes'][0]
    row['fireModes'][0]['damage']=None
    changes,deferred=updates(Packages(),[row]);assert not changes and len(deferred)==1


@pytest.mark.parametrize('change',[dict(projectileType='other'),dict(fireIterations=2),dict(AttenuateFireIterationsForCharge=1)])
def test_changed_source_identity_or_charge_count_rejected(monkeypatch,change):
    monkeypatch.setattr(importer,'source_rows',lambda *_:[])
    packages=Packages();packages.raw['Behaviors'][0]['fire:LotusWeaponProjectileFireBehavior'].update(change)
    row=dict(path='/weapon',slot='primary',fireModes=[dict(index=0,multishot=1,damage=dict(types={'DT_IMPACT':2.},projectile='/weapon/p'))])
    with pytest.raises(ValueError):updates(packages,[row])


@pytest.mark.parametrize('flag,fire_type,expected',[(1,FIRE,True),(0,FIRE,False),(1,'/EE/Types/Game/WeaponFireBehavior',False)])
def test_future_extraction_retains_only_proven_projectile_count_flag(monkeypatch,flag,fire_type,expected):
    from wfarsenal import extract
    monkeypatch.setattr(extract,'_resolve_damage',lambda *_:dict(types={'DT_IMPACT':10.},total=10.))
    monkeypatch.setattr(extract,'_native_event_declarations',lambda *_:{})
    monkeypatch.setattr(extract,'_extract_projectile_events',lambda *_:{})
    entry={'fire:Type':fire_type,'fire:LotusWeaponProjectileFireBehavior':dict(IgnoreFireIterations=flag,fireIterations=1)}
    modes=extract._extract_fire_modes(None,'/fixture',{'Behaviors':[entry]})
    assert bool(modes[0].get('nativeIgnoreFireIterations')) is expected


def test_independent_projectile_preview_preserves_emission_lock():
    from wfarsenal.projectile_events import _event_weapon
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==GRIMOIRE)
    mode=weapon['fireModes'][1]
    part=_event_weapon(weapon,mode,mode['damage'])
    assert part['fireModes'][0]['nativeIgnoreFireIterations']
    stats=damage.apply_mods(part,[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)])
    assert stats.multishot==1.
