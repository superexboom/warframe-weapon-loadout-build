from copy import deepcopy

import pytest
import app
from wfarsenal.damage import Scenario,ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target


def setup(choices=None,state=None):
    weapon=deepcopy(next(w for w in app.EXPORTS['weapons'] if w['nameEn']=='Onos'))
    weapon['isIncarnonForm']=True
    combat=prepare(dict(weapon=weapon,fire_mode=2,effects=[],scenario=Scenario(combat_state=state or {})),
                   [],[],incarnon_choices=choices or {})
    stats,_=combat['resolve']('selected',{},0)
    return stats,combat


def test_onos_charge_beam_and_power_shot_use_one_native_charge_pool():
    stats,combat=setup()
    result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=4.76,combat=combat)
    rows=result['onosSequence']['events']
    assert [r['kind'] for r in rows]==['beam']*8+['power','beam']
    assert [r['time'] for r in rows]==pytest.approx([i*.5 for i in range(9)]+[4.75])
    assert rows[8]['ammoCost']==50


def test_onos_crit_stacks_pay_out_on_blast_and_reset_for_next_charge():
    stats,combat=setup({'tier5':'5-3'})
    assert combat['onosCrits']==dict(perHit=.05,maximum=50)
    beam,_=combat['resolve']('selected',{'__onosHits':8},0)
    blast,_=combat['resolve']('selected',{'__onosPower':True,'__onosHits':8},0)
    assert beam.crit_chance==pytest.approx(.14)
    assert blast.crit_chance==pytest.approx(.38*1.4)
    result=replay(stats,target(1e12),attacks_per_second=stats.fire_rate,window_seconds=4.76,combat=combat)
    events=result['onosSequence']['events']
    assert events[8]['critStacks']==8 and events[9]['critStacks']==0


def test_onos_radial_target_coverage_is_explicit_and_does_not_take_multishot():
    _,combat=setup()
    assert combat['resolve']('selected',{'__onosPower':True},0)[1] is None
    _,combat=setup(state={'onosRadialHit':True})
    st,radial=combat['resolve']('selected',{'__onosPower':True},0)
    assert radial.total_damage==pytest.approx(1100.) and radial.multishot==1.
    assert st.total_damage==pytest.approx(2200.)
