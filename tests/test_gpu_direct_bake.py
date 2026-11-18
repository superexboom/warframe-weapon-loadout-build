"""The GPU domain is explicitly bounded; ordinary combat keeps its CPU path."""
from types import SimpleNamespace
import pytest
import app
from wfarsenal import optimizer as o, native_replay as native, search_combat
from wfarsenal.damage import Scenario, ModEffect
from tools.gpu_bake.backend import DirectBatch


def test_invalid_or_unbounded_stream_is_rejected_before_device_work():
    for rows in ([], [([float('nan')],1.,1.)], [([1.],0.,1.)], [([-1.],1.,1.)]):
        with pytest.raises(ValueError):DirectBatch.validate(rows)


def test_cost_rejection_preserves_cpu_result_without_dispatch():
    backend=object.__new__(DirectBatch);backend.policy={};backend.last_decision={}
    backend.probe=lambda rows,**kw:dict(admitted=False,reason='no-gain')
    backend.gpu=lambda rows:pytest.fail('rejected batch must not reach device')
    rows=[([7.,7.,7.],10.,30.)]
    assert backend.score(rows)==DirectBatch.cpu(rows)
    assert backend.last_decision['backend']=='cpu'


def test_direct_stream_health_resets_and_partial_kill():
    assert DirectBatch.cpu([([7.,7.,7.],10.,30.)])==[(3.4,17./30.,17.)]


@pytest.mark.parametrize('status,shield,head',[(False,0.,0.),(True,0.,0.),(False,100.,0.),(False,0.,.5)])
def test_native_stream_matches_full_replay_or_refuses_missing_semantics(monkeypatch,status,shield,head):
    core=native.wfcore
    if not core or not hasattr(core,'direct_bake_stream'):pytest.skip('GPU development core required')
    original=core.trajectory;streams=[];rejected=[]
    def capture(config,helper):
        try:streams.append(core.direct_bake_stream(config,helper))
        except core.NativeUnsupported as exc:rejected.append(str(exc))
        return original(config,helper)
    monkeypatch.setattr(core,'trajectory',capture)
    raw=next(w for w in app.EXPORTS['weapons'] if w.get('nameEn')=='Lato')
    weapon=o._select_fire_mode(raw,0,weapon_type='pistol')[0]
    effects=[] if status else [ModEffect('WEAPON_PROC_CHANCE','STACKING_MULTIPLY',-1.)]
    scenario=Scenario(trigger_policy='emergent');stats=o.apply_mods(weapon,effects,scenario=scenario)
    o._bind_combat_inputs(stats,weapon,(),effects,scenario)
    search_combat._REPLAYS.clear()
    context=dict(target=dict(health=3000.,shield=shield,overguard=0.,armour=200.,baseLevel=1),
                 level=1,windowSeconds=30.,headshotChance=head)
    result=search_combat.window(stats,context,score_only=True)
    if status or shield or head:
        assert rejected and not streams
    else:
        assert streams and not rejected
        assert DirectBatch.cpu(streams)[0]==tuple(result[k] for k in ('killsPerMinute','windowDps','totalWindowDamage'))
