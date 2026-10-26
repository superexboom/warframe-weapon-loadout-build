"""Native Nataruk projectile flag excludes damage bonuses, not hit events."""
from dataclasses import replace
import json
from pathlib import Path
import pytest
import app
from wfarsenal import damage, native_replay, mods_native, combat_replay, status_native
from wfarsenal.damage import Scenario


def stats():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Nataruk')
    return damage.apply_mods(w,[],scenario=Scenario())


def test_native_projectile_flag_preserves_headshot_triggers_but_not_acuity_damage():
    s=stats();assert s.ignore_headshot_bonus
    target=dict(health=1e9,armour=0,shield=0,baseLevel=1,headshotMultiplier=3.)
    body=damage.damage_against(s,target,hit_location='body')['perShot']
    head=damage.damage_against(s,target,hit_location='head')['perShot']
    acuity=damage.damage_against(replace(s,weakpoint_damage_bonus=3.5),target,hit_location='head')['perShot']
    deadhead=damage.damage_against(replace(s,headshot_bonus_multiplier=1.3),target,hit_location='head')['perShot']
    assert head==body and acuity==head
    assert deadhead==pytest.approx(head*1.3)


def test_ordinary_weapon_keeps_target_headshot_bonus():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Braton Prime')
    s=damage.apply_mods(w,[],scenario=Scenario());assert not s.ignore_headshot_bonus
    target=dict(health=1e9,armour=0,shield=0,baseLevel=1,headshotMultiplier=3.)
    assert damage.damage_against(s,target,hit_location='head')['perShot']>damage.damage_against(s,target)['perShot']*2.9


def test_real_nataruk_native_python_panel_and_status_paths_agree(monkeypatch):
    payload=json.loads((Path(__file__).parent/'fixtures/nataruk_headshot.json').read_text(encoding='utf-8'))
    display=app.simulate_manual_payload(payload)['benchmarkTimeline']
    assert 2.<display['killsPerMinute']<2.6  # Previously 16.9079 from missing projectile flag.
    assert display['shots']==58  # Primary Crux still receives weak-point hits.
    original=combat_replay.replay
    monkeypatch.setattr(combat_replay,'replay',lambda *a,**kw:original(*a,**dict(kw,collect_timeline=False)))
    monkeypatch.setattr(native_replay,'SHADOW',True);monkeypatch.setattr(mods_native,'SHADOW',True)
    result=app.simulate_manual_payload(payload)['benchmarkTimeline']
    assert result['killsPerMinute']==display['killsPerMinute']
    assert result['totalWindowDamage']==display['totalWindowDamage']
    s=stats();target=app.MANUAL_ENEMIES_BY_PATH[app._BENCHMARK_ENEMY_PATH]
    monkeypatch.setattr(status_native,'SHADOW',True)
    status_native.score(s,target,dict(level=170,steel_path=True,hit_location='head'),
                        status_rate_multiplier=1.,damage_rate_multiplier=1.,total=True)
