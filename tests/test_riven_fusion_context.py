import json

import app
from wfarsenal.damage import ModEffect, Scenario, apply_mods, damage_against
from wfarsenal.runtime_adapters import resolve_runtime_adapter


def test_weakpoint_fusion_contribution_is_conditioned_on_real_hit_context():
    weapon=next(row for row in app.EXPORTS['weapons'] if row.get('nameEn')=='Vectis Prime')
    target=next(row for row in app.EXPORTS['enemies'] if row.get('path')==app._BENCHMARK_ENEMY_PATH)
    plain=apply_mods(weapon,[],scenario=Scenario())
    fused=apply_mods(weapon,[ModEffect('WEAPON_DAMAGE_WEAKPOINT','STACKING_MULTIPLY',1.)],scenario=Scenario())
    body=damage_against(plain,target,level=170,steel_path=True,enemy_enhancements={'eximus':True},hit_location='body')['perHit']
    body_fused=damage_against(fused,target,level=170,steel_path=True,enemy_enhancements={'eximus':True},hit_location='body')['perHit']
    head=damage_against(plain,target,level=170,steel_path=True,enemy_enhancements={'eximus':True},hit_location='head')['perHit']
    head_fused=damage_against(fused,target,level=170,steel_path=True,enemy_enhancements={'eximus':True},hit_location='head')['perHit']
    assert body_fused==body
    assert head_fused>head


def test_cannonade_catalog_retains_category_description_and_native_lock():
    row=next(row for row in app.CATALOG['manualMods'] if row.get('nameEn')=='Semi-Rifle Cannonade')
    assert row['category']=='damage'
    assert '射速' in row['description']
    assert 'SEMI_AUTO' in row['compatibilityTags']
    exported=next(row for row in app.EXPORTS['mods'] if row.get('nameEn')=='Semi-Rifle Cannonade')
    assert resolve_runtime_adapter(exported,5).kind=='lock_fire_rate'


def test_cache_authorization_contract_is_documented_and_local_only():
    # The bake tool's own help and errors carry the full-roster authorization contract.
    text=open('tools/bake-analysis-statics.py',encoding='utf-8').read()
    assert 'explicit user authorization' in text
    assert 'full-roster' in text and '--allow-full-bake' in text
