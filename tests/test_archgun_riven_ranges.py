"""Archgun faction trait survives the template-to-input-to-effect contract."""
import pytest
import app
from wfarsenal.damage import apply_mods,damage_against
from tests.test_riven_disposition_20261023 import _engine_request


def screenshot_card():
    return dict(disposition=1.2,profile='fast',stats=[
        dict(code='S',value=72.2,negative=False),dict(code='VI',value=106.9,negative=False),
        dict(code='D',value=109.5,negative=False),dict(code='I',value=40.,negative=True)])


@pytest.mark.parametrize('name',[w['nameEn'] for w in app.CATALOG['weapons']
                                 if w.get('weaponType')=='archgun' and w.get('available') and w.get('analysisAvailable')])
def test_archgun_screenshot_card_reaches_solver_with_negative_faction_intact(name):
    weapon=next(w for w in app.CATALOG['weapons'] if w.get('nameEn')==name)
    request=_engine_request(dict(screenshot_card(),weapon=weapon['path']))
    line=next(s for s in request['stats'] if s['code']=='I')
    assert line['value']==40. and line['negative'] is True
    assert line['low']<40.<line['high']
    assert next(s for s in request['stats'] if s['code']=='VI')['value']==106.9


@pytest.mark.parametrize('code',['C','G','I'])
def test_archgun_faction_traits_have_native_templates_and_card_faces(code):
    templates=app.EXPORTS['rivenTemplates']
    rows=list(app.optimizer._template_stats(templates,'archgun'))
    stat=next(row for row in rows if row[0]==code)[2]
    assert stat['canBeBuff'] and stat['canBeCurse']
    assert app.optimizer._template_bases(templates,'archgun')[code]==pytest.approx(45.,abs=1e-5)
    assert app.optimizer.riven_card_faces(templates,'archgun')[code]['prefix']


def test_infested_curse_reduces_infested_damage_instead_of_being_discarded():
    weapon=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Corvas')
    effect=app.optimizer._effect_from_code('I',40.,negative=True,source='regression')
    plain=apply_mods(weapon,[]);curse=apply_mods(weapon,[effect])
    enemy=dict(health=1e8,armour=0,shield=0,overguard=0,baseLevel=1,faction='Infestation')
    assert damage_against(curse,enemy)['perHit']/damage_against(plain,enemy)['perHit']==pytest.approx(.6)
    enemy['faction']='Grineer'
    assert damage_against(curse,enemy)['perHit']==damage_against(plain,enemy)['perHit']


def test_invalid_faction_roll_is_still_rejected():
    weapon=next(w for w in app.CATALOG['weapons'] if w.get('nameEn')=='Corvas')
    payload=dict(screenshot_card(),weapon=weapon['path']);payload['stats'][-1]['value']=90.
    with pytest.raises(app.SimulationError,match='outside'):_engine_request(payload)
