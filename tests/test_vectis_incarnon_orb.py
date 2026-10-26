"""2026-10-20: the Vectis Incarnon orb differs on headshots and body shots.

Every shot embeds an orb that hits at once (EmbedAttack). A body shot keeps it
2.5 s for two more hits; a headshot detonates it 0.4 s later as two
simultaneous ExplosiveAttack hits (wiki Vectis Prime, Evolution 1).
"""
from __future__ import annotations

import json

import pytest

import app
from wfarsenal.damage import Scenario, ModEffect
from wfarsenal.manual_combat import prepare
from wfarsenal.combat_replay import replay
from tests.test_combat_replay import target

PRIME = "/Lotus/Weapons/Tenno/LongGuns/PrimeVectis/PrimeVectisRifle"
VECTIS = "/Lotus/Weapons/Tenno/Rifle/TennoSniperRifle"


def parts(path):
    weapon = next(w for w in app.EXPORTS["weapons"] if w["path"] == path)
    combat = prepare(dict(weapon=weapon, fire_mode=1, effects=(), scenario=Scenario(distance=10.)), [], [])
    st, radial = combat["resolve"]("selected", {})
    return combat, st, (radial, *radial._additional_radials)


@pytest.mark.parametrize("path,embed,explosion", [(PRIME, 25.0, 150.0), (VECTIS, 5.0, 5.0)])
def test_reference_carries_embed_ticks_and_headshot_explosion(path, embed, explosion):
    reference = json.loads((app.ROOT / "data/mechanics/combat-reference.json").read_text(encoding="utf-8"))
    radials = reference["auditedAttacks"][path]["modes"]["1"]["radials"]
    assert [(r["hit"], r["damage"]["DT_FREEZE"], r.get("count", 1), r.get("impact_delay_seconds", 0.0)) for r in radials] == [
        ("embed", embed, 1, 0.0), ("embed-body-tick", embed, 1, 1.0), ("embed-body-tick", embed, 1, 2.0),
        ("headshot-explosion", explosion, 2, pytest.approx(0.4)),
    ]
    assert [bool(r.get("bodyOnly")) for r in radials] == [False, True, True, False]
    assert [bool(r.get("headOnly")) for r in radials] == [False, False, False, True]


def test_parts_follow_the_shot_location():
    combat, st, radials = parts(PRIME)
    assert [p.multishot for p in radials] == [1.0, 1.0, 1.0, 2.0]
    assert [getattr(p, "_body_only", False) for p in radials] == [False, True, True, False]
    assert getattr(radials[-1], "_head_only", False)
    combat["resolve"] = lambda *args: (st, radials[0])
    # Delayed parts land only for the share of shots that can carry them.
    def delayed(window, head):
        return replay(st, target(), combat=combat, window_seconds=window, attacks_per_second=0.2,
                      headshot_chance=head)["delayedAttackEvents"]
    # First shot only: the explosion lands at 0.4 s, the body ticks later.
    assert (delayed(0.5, 1.0), delayed(0.5, 0.0)) == (1, 0)
    assert delayed(3.0, 0.5) == delayed(3.0, 1.0) + delayed(3.0, 0.0)
    assert delayed(3.0, 0.0) > 0


@pytest.mark.parametrize('deadhead,expected',[(0.,1484.),(.3,1762.25)])
def test_m117_head_orb_inherits_scope_bracket_without_head_location(deadhead,expected):
    # WFSim owner measurement M117: Inciting Incident, Critical Parallel and
    # Serration. Noncritical embed=596.25; scoped head explosion=1484 each,
    # or 1762.25 with Deadhead's passive bracket, before its kill buff.
    weapon=next(w for w in app.EXPORTS['weapons'] if w['path']==PRIME)
    effects=[ModEffect('WEAPON_DAMAGE_AMOUNT','ADD_BASE',200.),
             ModEffect('WEAPON_DAMAGE_AMOUNT','STACKING_MULTIPLY',1.65),
             ModEffect('WEAPON_HEADSHOT_MULTIPLIER','STACKING_MULTIPLY',deadhead),
             ModEffect('WEAPON_DAMAGE_WEAKPOINT','STACKING_MULTIPLY',3.),
             ModEffect('WEAPON_CRIT_CHANCE_WEAKPOINT','STACKING_MULTIPLY',3.5)]
    combat=prepare(dict(weapon=weapon,fire_mode=1,effects=effects,scenario=Scenario(aiming=True)),[],[])
    _,embed=combat['resolve']('selected',{})
    explosion=embed._additional_radials[-1]
    assert sum(embed.damage_types.values())==pytest.approx(596.25)
    assert sum(explosion.damage_types.values())==pytest.approx(expected)
    assert explosion.radial_only and explosion.multishot==2
    assert explosion.headshot_bonus_multiplier==1.
    assert explosion.weakpoint_damage_bonus==explosion.weakpoint_crit_chance_bonus==0.


def test_killing_direct_hit_still_leaves_its_independent_head_orb():
    combat,st,radials=parts(PRIME)
    # The head callback rejects invulnerable targets, not dead ones. A tiny
    # target dies from the collision; the cloned orb still bursts at 0.4 s.
    combat['resolve']=lambda *args:(st,radials[0])
    head=replay(st,target(1.),combat=combat,window_seconds=.5,attacks_per_second=.2,headshot_chance=1.)
    body=replay(st,target(1.),combat=combat,window_seconds=.5,attacks_per_second=.2,headshot_chance=0.)
    assert head['delayedAttackEvents']==1
    assert body['delayedAttackEvents']==0
    assert head['killsInWindow']>body['killsInWindow']
