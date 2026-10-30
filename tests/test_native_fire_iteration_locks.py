"""Native emission locks apply to actual selected modes and both MOD engines."""
from types import SimpleNamespace
import pytest
import app
from wfarsenal import damage,mods_native
from wfarsenal.damage import ModEffect,Scenario
from tools.import_native_fire_iteration_locks import updates,FIRE
from tools import import_native_fire_iteration_locks as importer

GRIMOIRE='/Lotus/Weapons/Tenno/Grimoire/TnGrimoire'


def test_selected_mode_and_independent_preview_keep_native_count(monkeypatch):
    from wfarsenal.projectile_events import _event_weapon
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==GRIMOIRE)
    fx=[ModEffect('WEAPON_FIRE_ITERATIONS','STACKING_MULTIPLY',2.)]
    monkeypatch.setattr(mods_native,'SHADOW',True)
    assert damage.apply_mods(weapon,fx,fire_mode=0).multishot==3.
    selected=app.optimizer._select_fire_mode(weapon,1,weapon_type='pistol')[0]
    assert damage.apply_mods(selected,fx,fire_mode=0).multishot==1.
    part=_event_weapon(weapon,weapon['fireModes'][1],weapon['fireModes'][1]['damage'])
    assert damage.apply_mods(part,fx).multishot==1.


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


def test_extraction_preserves_source_emission_lock(monkeypatch):
    from wfarsenal import extract
    monkeypatch.setattr(extract,'_resolve_damage',lambda *_:dict(types={'DT_IMPACT':10.},total=10.))
    monkeypatch.setattr(extract,'_native_event_declarations',lambda *_:{})
    monkeypatch.setattr(extract,'_extract_projectile_events',lambda *_:{})
    entry={'fire:Type':FIRE,'fire:LotusWeaponProjectileFireBehavior':dict(IgnoreFireIterations=1,fireIterations=1)}
    modes=extract._extract_fire_modes(None,'/fixture',{'Behaviors':[entry]})
    assert modes[0]['nativeIgnoreFireIterations'] is True
