import copy
import json
from pathlib import Path

import pytest
import app
from wfarsenal.catalog_releases import (UNRELEASED_TIER_CLONES, RELEASED_ARCHGUN_MODS, released_mod_catalog)

RAW = json.loads((app.EXPORT_DIR / 'mods.json').read_text(encoding='utf-8'))['data']
BY_PATH = {m['path']: m for m in RAW}


def test_every_frozen_tier_clone_is_excluded_without_mutating_export():
    before = copy.deepcopy(RAW)
    catalog = {m['path']: m for m in released_mod_catalog(RAW)}
    assert len(UNRELEASED_TIER_CLONES) == 58
    evidence = json.loads((app.ROOT / 'docs/evidence/radial-round-20260927/expert-catalog-evidence.json').read_text(encoding='utf-8'))
    assert {r['path'] for r in evidence['rows']} == set(UNRELEASED_TIER_CLONES)
    for path, base in UNRELEASED_TIER_CLONES.items():
        assert catalog[path]['selectable'] is False
        assert catalog[path]['catalogExclusion']['basePath'] == base
        assert catalog[path]['effects'] == BY_PATH[path]['effects']
        assert catalog[base]['selectable'] is True
        assert path not in app.MANUAL_MODS_BY_PATH
        assert path not in app.MANUAL_MOD_ALIASES
        assert path not in app.UTILITY_MODS_BY_PATH
    assert RAW == before


@pytest.mark.parametrize('field,value', [
    ('maxRank', 5), ('rarity', 'LEGENDARY'), ('nameTag', '/new/released/name'),
    ('modFamily', '/new/family'), ('compatibility', '/new/weapon'),
])
def test_future_release_metadata_is_not_blindly_blacklisted(field, value):
    path = '/Lotus/Upgrades/Mods/Rifle/Expert/WeaponFireIterationsModExpert'
    card = {**BY_PATH[path], field: value}
    base = BY_PATH[UNRELEASED_TIER_CLONES[path]]
    assert released_mod_catalog([card, base])[0]['selectable'] is True


def test_release_and_codex_flags_do_not_hide_real_primed_cards():
    catalog = {m['path']: m for m in released_mod_catalog(RAW)}
    for path in RELEASED_ARCHGUN_MODS:
        assert catalog[path]['selectable'] is True
        assert path in app.MANUAL_MODS_BY_PATH
    for path in ('/Lotus/Upgrades/Mods/Melee/Expert/WeaponFireRateModExpert',
                 '/Lotus/Upgrades/Mods/Melee/Expert/WeaponToxinDamageModExpert'):
        assert catalog[path]['selectable'] is True
        assert path in app.MANUAL_MODS_BY_PATH


@pytest.mark.parametrize('name', ['Braton Prime', 'Lex Prime', 'Hek', 'Mausolon'])
def test_automatic_candidates_only_use_actual_tier_identity(name):
    weapon = next(w for w in app.EXPORTS['weapons'] if w.get('nameEn') == name)
    pool, _ = app.optimizer._candidate_mods(app.EXPORTS, weapon, app.optimizer._scenario('killsPerMinute'))
    assert pool
    assert not ({c.record['path'] for c in pool} & set(UNRELEASED_TIER_CLONES))


def test_old_invalid_build_errors_instead_of_silently_changing_mod_or_rank():
    path = '/Lotus/Upgrades/Mods/Pistol/Expert/WeaponFireIterationsModExpert'
    with pytest.raises(app.SimulationError, match='unreleased tier variant'):
        app._manual_normalize_mods([{'path': path, 'rank': 10}], 8)
    base = UNRELEASED_TIER_CLONES[path]
    with pytest.raises(app.SimulationError, match='exceeds maxRank 5'):
        app._manual_normalize_mods([{'path': base, 'rank': 10}], 8)
    assert app._manual_normalize_mods([{'path': base, 'rank': 5}], 8)[0] == {'path': base, 'rank': 5}
