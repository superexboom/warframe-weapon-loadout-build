from dataclasses import replace

import pytest
import app
from wfarsenal import optimizer as o
from wfarsenal.damage import Scenario


def test_returned_riven_slot_preserves_element_order_on_manual_replay():
    w=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Tenora Prime')
    w,_=o._select_fire_mode(w,0,weapon_type='rifle')
    sc=Scenario(trigger_policy='emergent')
    names=['Hellfire','Cryo Rounds','Serration']
    cards=tuple(o._mod_card(next(m for m in app.EXPORTS['mods'] if m.get('nameEn')==name
                                 and m.get('path') in app.MANUAL_MODS_BY_PATH),sc) for name in names)
    riven=o._card_from_lines(o._wire_lines([{'code':'6','value':90.,'negative':False}])[0])
    target=next(e for e in app.EXPORTS['enemies'] if e['path']==app._BENCHMARK_ENEMY_PATH)
    context=dict(target=target,level=9999,steel_path=True,enemy_enhancements={},windowSeconds=30.,headshotChance=0.)
    outcome=o._evaluate(w,cards,riven,scenario=sc,metric='killsPerMinute',target_context=context,capacity_limit=60,slot_limit=8)
    assert outcome is not None
    # Pin a non-terminal legal slot, so this fails if the wire simply appends it.
    outcome=replace(outcome,riven_index=0)
    build=o._build_payload(w,outcome,riven)
    assert build['riven']['slot']==0
    assert [m['slot'] for m in build['mods']]==[1,2,3]
    ordered=[riven,*cards]
    fx=o._effects(ordered,sc)
    stats=o.apply_mods(w,fx,scenario=sc)
    payload=dict(weapon=w['path'],fireMode=0,metric='killsPerMinute',riven=build['riven'],
                 mods=[dict(path=m['path'],rank=m['rank'],slot=m['slot']) for m in build['mods']],
                 enemy=target['path'],level=9999,steelPath=True,triggerPolicy='emergent')
    manual=app.simulate_manual_payload(payload)
    assert manual['moddedStats']['damageTypes']==pytest.approx(stats.damage_types)
