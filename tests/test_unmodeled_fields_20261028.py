"""Unresolved damage fields must remain visible instead of false exact scores."""
import pytest
import app
from wfarsenal.damage import Scenario
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay


@pytest.mark.parametrize('name',['Alternox','Alternox Prime'])
def test_alternox_remaining_lifecycle_assumptions_are_reported_by_both_score_paths(name):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=Scenario()),[],[])
    expected={'alternox-host-death-lifecycle-unverified','alternox-same-time-expiry-order-fixed-explosion-first'}
    assert 'alternox-same-time-expiry-order-fixed-explosion-first' in combat['unsupported']
    stats,_=combat['resolve']('selected',{},0)
    enemy=dict(health=1e8,shield=0.,overguard=0.,armour=0.,baseLevel=1)
    for details in (False,True):
        result=replay(stats,enemy,attacks_per_second=stats.fire_rate,window_seconds=.1,
                      combat=combat,collect_timeline=details,score_only=not details)
        assert expected <= set(result['unsupported'])


@pytest.mark.parametrize('name,mode,expected',[
    ('Cortege',1,{'cortege-full-charge-gate-unmodeled','cortege-explosion-and-lingering-field-unmodeled'}),
    ('Angstrum',0,{'angstrum-single-rocket-explosion-unmodeled','angstrum-charge-volley-unmodeled'}),
    ('Prisma Angstrum',0,{'angstrum-single-rocket-explosion-unmodeled','angstrum-charge-volley-unmodeled'}),
    ('Cryotra',0,{'cryotra-field-host-death-and-spatial-persistence-unverified','cryotra-field-overlap-unverified'}),
    ('Deconstructor',0,{'companion-projectile-damage-sequence-unmodeled'})])
def test_partial_weapon_damage_is_visible_to_api_clients_without_timeline_read(name,mode,expected):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    result=app.simulate_manual_payload(dict(weapon=weapon['path'],fireMode=mode,
        enemy=app._BENCHMARK_ENEMY_PATH,level=100,windowSeconds=.1,mods=[]))
    assert expected<=set(result['unsupported'])
    assert expected<=set(result['diagnostics']['unsupported'])



def test_unverified_damage_contract_marks_real_riven_analysis_partial(monkeypatch):
    from wfarsenal import parallel
    monkeypatch.setattr(parallel,'get_pool',lambda:None)
    monkeypatch.setattr(app,'_persist_analysis_statics_cache',lambda:None)
    weapon=next(w for w in app.CATALOG['weapons'] if w['nameEn']=='Cryotra')
    bases=app.RIVEN_BASE_VALUES[app.optimizer._riven_type(None,weapon)]
    result=app.analyze_payload(dict(weapon=weapon['path'],disposition=1.2,profile='ultra',
        stats=[dict(code=c,value=bases[c]*1.2,negative=False) for c in ('D','S')]))
    assert result['modelStatus']=='partial'
    assert 'analysis-model-partial' in result['unsupported']
    assert 'cryotra-field-condition-overload-unverified' in result['unsupported']


@pytest.mark.parametrize('name',['Angstrum','Prisma Angstrum'])
def test_angstrum_ordinary_charge_limits_do_not_leak_into_incarnon(name):
    weapon=next(w for w in app.EXPORTS['weapons'] if w['nameEn']==name)
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=[],scenario=Scenario()),[],[])
    assert not any(reason.startswith('angstrum-') for reason in combat['unsupported'])
