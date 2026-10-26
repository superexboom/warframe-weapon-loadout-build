"""Compare Riven insertion canonicalization with independent slot enumeration."""
from itertools import permutations
from types import SimpleNamespace
import pytest
from wfarsenal import optimizer as o
from wfarsenal.damage import ModEffect, Scenario


def card(name, element):
    return o._Card(name, None, 0, (ModEffect('WEAPON_PERCENT_BASE_DAMAGE_ADDED','STACKING_MULTIPLY',.6,damage_type=element),), (), 0, None)


def independent_pairing(items):
    elements = list(dict.fromkeys(e.damage_type for c in items for e in c.effects))
    return frozenset(elements[:2]), frozenset(elements[2:])


@pytest.mark.parametrize('ordinary,riven', [
    (['DT_FIRE','DT_FREEZE'], 'DT_POISON'),
    (['DT_FIRE','DT_FREEZE','DT_ELECTRICITY'], 'DT_POISON'),
    (['DT_FIRE','DT_FREEZE','DT_ELECTRICITY','DT_POISON'], 'DT_FREEZE'),
])
def test_every_legal_pairing_with_riven_is_covered(ordinary,riven):
    mods=tuple(card(str(i),element) for i,element in enumerate(ordinary));rv=card('riven',riven)
    reference={independent_pairing(layout) for layout in permutations((*mods,rv))}
    actual=set()
    for position in range(len(mods)+1):
        for ordered in o._element_orders(mods,anchor=(position,rv)):
            actual.add(independent_pairing((*ordered[:position],rv,*ordered[position:])))
    assert actual == reference


def test_fixed_riven_slot_retains_pairings_hidden_by_mod_only_deduplication():
    mods=tuple(card(str(i),e) for i,e in enumerate(['DT_FIRE','DT_FREEZE','DT_ELECTRICITY']))
    rv=card('riven','DT_POISON');position=1
    reference={independent_pairing((layout[0],rv,*layout[1:])) for layout in permutations(mods)}
    actual={independent_pairing((layout[0],rv,*layout[1:])) for layout in o._element_orders(mods,anchor=(position,rv))}
    assert actual==reference and len(actual)==3
