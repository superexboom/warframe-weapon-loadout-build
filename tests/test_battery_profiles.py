"""Battery (regenerating magazine) weapons refill instead of reloading."""
import pytest
import app
from wfarsenal.damage import Scenario, apply_mods
from wfarsenal.event_profiles import battery_profiles
from wfarsenal.manual_combat import prepare

FULMIN_PRIME = '/Lotus/Weapons/Tenno/LongGuns/PrimeFulmin/PrimeFulmin'
BASMU = '/Lotus/Weapons/Sentients/SentRifleNewWar/SentRifleNewWarGun'


def weapon(path):
    return next(w for w in app.EXPORTS['weapons'] if w['path'] == path)


def test_empty_battery_refill_replaces_exported_reload_in_every_mode():
    # Native: 0.7 s delay from empty, 40 rounds/s, 80-round battery. The
    # export's 3 s ReloadTime and WFSim's 30/s, 1 s (the ordinary Fulmin's)
    # both differ.
    battery = battery_profiles()[FULMIN_PRIME]
    assert battery['regenPerSecond'] == 40 and battery['delayEmptySeconds'] == pytest.approx(.7)
    record = weapon(FULMIN_PRIME)
    for mode in range(len(record['fireModes'])):
        stats = apply_mods(record, [], fire_mode=mode, scenario=Scenario())
        assert stats.reload_time == pytest.approx(.7 + stats.magazine / 40)


def test_ordinary_magazine_weapons_keep_their_reload():
    record = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == 'Soma Prime')
    assert record['path'] not in battery_profiles()
    stats = apply_mods(record, [], scenario=Scenario())
    assert stats.reload_time == pytest.approx(record['fireModes'][0]['reloadTime'])


def test_native_battery_tag_adds_basmu_and_every_mode_regenerates():
    # Not in WFSim's battery list; native tag + 42/s after 2 s from empty gives
    # 2 + 21 / 42 = 2.5 s, the wiki full reload WFSim uses as a plain reload.
    battery = battery_profiles()[BASMU]
    record = weapon(BASMU)
    for mode in range(len(record['fireModes'])):
        stats = apply_mods(record, [], fire_mode=mode, scenario=Scenario())
        assert stats.reload_time == pytest.approx(2.5)
        engine = dict(weapon=record, fire_mode=mode, effects=[], scenario=Scenario(trigger_policy='emergent'))
        assert prepare(engine, [], [])['battery'] == battery


def test_battery_tag_alone_does_not_make_archguns_or_bows_batteries():
    names = {weapon(path)['nameEn'] for path in battery_profiles()}
    assert not names & {'Imperator Vandal', 'Larkspur', 'Nataruk', 'Amp'}
