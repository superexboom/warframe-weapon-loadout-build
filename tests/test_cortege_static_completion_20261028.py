"""Cortege native charge gate and per-projectile payload, static audit 2026-10-28."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
import app
from wfarsenal.damage import ModEffect, Scenario
from wfarsenal.manual_combat import prepare, reference
from wfarsenal.combat_replay import replay
from wfarsenal import native_replay
from tools import import_kill_charged_alts as importer
from tools.import_native_cortege import UNMODELED

ROOT = Path(__file__).resolve().parents[1]
PATH = importer.CORTEGE


def weapon():
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path'] == PATH))


def combat(pellets=None):
    effects = [ModEffect('WEAPON_CRIT_CHANCE', 'SET', 0.),
               ModEffect('WEAPON_PROC_CHANCE', 'SET', 0.)]
    if pellets is not None:
        effects.append(ModEffect('WEAPON_FIRE_ITERATIONS', 'SET', pellets))
    return prepare(dict(weapon=weapon(), fire_mode=1, effects=effects, scenario=Scenario()), [], [])


def enemy(health=1e12):
    return dict(health=health, shield=0., overguard=0., armour=0., baseLevel=1)


def test_export_already_carries_heavy_three_iterations_and_distinct_primary():
    row = weapon()
    assert row['fireModeSource'] == 'HeavyBehaviors'
    assert row['fireModes'][0]['damage']['types'] == {'DT_FIRE':180.}
    assert row['fireModes'][0]['multishot'] == 1
    assert row['fireModes'][1]['damage']['types'] == {'DT_IMPACT':20.}
    assert row['fireModes'][1]['multishot'] == 3
    fight = combat()
    primary, primary_radial = fight['resolve']('base', {}, 0)
    direct, radial = fight['resolve']('selected', {}, 0)
    assert primary.total_damage == 180. and primary.multishot == 1.
    assert primary_radial is None
    assert direct.total_damage == 20. and direct.multishot == 3.
    assert radial.damage_types == {'DT_FIRE':2000.} and radial.multishot == 3.
    assert not radial._additional_radials
    assert not getattr(direct, '_lingering', None)


@pytest.mark.parametrize('pellets,expected', [(1.,2020.), (3.,6060.)])
def test_python_independent_one_trigger_payload_has_one_explosion_per_projectile(pellets, expected, monkeypatch):
    monkeypatch.setattr(native_replay, 'ENABLED', False)
    fight = combat(pellets)
    fight = {**fight, 'cycle':None}
    direct, _ = fight['resolve']('selected', {}, 0)
    result = replay(direct, enemy(), attacks_per_second=direct.fire_rate,
                    window_seconds=.001, combat=fight, collect_timeline=False)
    assert result['shots'] == 1
    assert result['directWindow'] == pytest.approx(expected)


def test_charge_profile_keeps_zero_consume_and_proven_max_source():
    payload = json.loads((ROOT/'data/mechanics/kill-charge-profiles.json').read_text(encoding='utf-8'))
    spec = payload['weapons'][PATH]
    assert spec['killsPerUse'] == 5 and spec['shotsPerGauge'] == 1
    assert spec['native']['NumChargesToConsume'] == 0
    assert spec['native']['RequireFullCharges'] == 1
    assert spec['native']['MaxCharges'] is None
    assert spec['native']['effectiveMaxCharges'] == 5
    assert spec['native']['zeroConsumptionMeans'] == 'consume-all-current-charges'
    assert spec['source']['defaultMaxAddress'] == '0x140bf8f9b'
    assert len(spec['source']['clientSha256']) == len(spec['nativeSha256']) == 64
    assert not any(x['name'] == 'Cortege' for x in payload['skipped'])
    assert any(x['name'] == 'Battacor' for x in payload['skipped'])


class Package:
    def __init__(self, native): self.native = native
    def resolve(self, path): return self.native
    def _path_to_file(self, path): return Path('/nonexistent/cortege-source.json')
    def ancestry(self, path): return [row['path'] for row in importer.PROVEN_DEFAULT_MAX_CHARGES[PATH]['ancestrySources']]


def charge_native(**overrides):
    fire = {'fire:WeaponProjectileFireBehavior':{'ConsumesChargesForFire':1}}
    return dict(AddCharges=[{'Conditions':['PRIMARY_KILL'], 'NumCharges':1}],
                ConsumeChargeConditions=['SECONDARY_FIRE'], NumChargesToConsume=0,
                RequireFullCharges=1, HeavyBehaviors=[{},fire]) | overrides


@pytest.fixture
def default_proof(monkeypatch, tmp_path):
    # Synthetic fixture exercises the full hash/ancestry admission path, using
    # real bytes rather than trusting a supplied string as EXE provenance.
    image = tmp_path/'audited.exe'
    image.write_bytes(b'audited-native-fixture')
    proof = deepcopy(importer.PROVEN_DEFAULT_MAX_CHARGES[PATH])
    proof['clientSha256'] = hashlib.sha256(image.read_bytes()).hexdigest()
    monkeypatch.setitem(importer.PROVEN_DEFAULT_MAX_CHARGES, PATH, proof)
    hashes = {row['path']:row['sha256'] for row in proof['ancestrySources']}
    monkeypatch.setattr(importer, 'raw_source_sha', lambda pkg,path: hashes.get(path))
    return image, hashes


def test_importer_reads_modern_addcharges_and_hash_gated_default(default_proof):
    image, hashes = default_proof
    spec, reason = importer.build_profile(Package(charge_native()), weapon(), native_image=image)
    assert not reason and spec['killsPerUse'] == 5 and spec['shotsPerGauge'] == 1
    assert spec['native']['effectiveMaxCharges'] == 5
    assert spec['source']['ancestrySources'] == importer.PROVEN_DEFAULT_MAX_CHARGES[PATH]['ancestrySources']


@pytest.mark.parametrize('changed', [PATH, '/Lotus/Weapons/Tenno/Archwing/Primary/ArchGun',
                                     '/Lotus/Types/Game/LotusWeapon'])
def test_native_default_rejects_change_anywhere_in_raw_ancestry(default_proof, changed):
    image, hashes = default_proof
    hashes[changed] = 'changed-source'
    spec, reason = importer.build_profile(Package(charge_native()), weapon(), native_image=image)
    assert spec is None and 'proven' in reason


@pytest.mark.parametrize('image_state', ['missing', 'changed', 'not-supplied'])
def test_native_default_rejects_unverified_executable(default_proof, image_state):
    image, _ = default_proof
    if image_state == 'missing':
        image.unlink()
    elif image_state == 'changed':
        image.write_bytes(b'new-client-retaining-old-resource-row')
    else:
        image = None
    spec, reason = importer.build_profile(Package(charge_native()), weapon(), native_image=image)
    assert spec is None and 'proven' in reason


def test_native_default_rejects_changed_parent_chain(default_proof, monkeypatch):
    image, _ = default_proof
    pkg = Package(charge_native())
    monkeypatch.setattr(pkg, 'ancestry', lambda path: [PATH, '/NewParent'])
    spec, reason = importer.build_profile(pkg, weapon(), native_image=image)
    assert spec is None and 'proven' in reason


def test_importer_zero_consume_battacor_and_other_no_full_gate_stay_unresolved(monkeypatch):
    monkeypatch.setattr(importer, 'raw_source_sha', lambda pkg,path: importer.CORTEGE_RAW_SHA)
    row = {**weapon(), 'path':'/Battacor', 'nameEn':'Battacor'}
    spec, reason = importer.build_profile(Package(charge_native(RequireFullCharges=0)), row)
    assert spec is None and 'unresolved' in reason
    spec, reason = importer.build_profile(Package(charge_native()), row)
    assert spec is None and 'proven' in reason


def test_importer_explicit_full_gauge_uses_max_not_zero_and_selected_heavy_bank():
    native = charge_native(MaxCharges=10)
    native['AddCharges'][0]['NumCharges'] = 3
    native['Behaviors'] = []  # Space bank must not override HeavyBehaviors.
    spec, reason = importer.build_profile(Package(native), weapon())
    assert not reason and spec['killsPerUse'] == 4 and spec['shotsPerGauge'] == 1


def test_importer_legacy_positive_consumption_preserved():
    native = dict(AddChargeConditions=['PRIMARY_KILL'], NumChargesToAdd=1,
                  ConsumeChargeConditions=['SECONDARY_FIRE'], NumChargesToConsume=5,
                  Behaviors=[{}, {'fire:WeaponFireBehavior':{'ConsumesChargesForFire':1}}])
    row = dict(path='/Mausolon',nameEn='Mausolon',slot='primary',fireModes=[{'index':0},{'index':1}])
    spec, reason = importer.build_profile(Package(native), row)
    assert not reason and spec['killsPerUse'] == 5 and spec['shotsPerGauge'] == 1


def test_python_actual_cycle_charges_only_on_kills_and_spends_one_alt_use(monkeypatch):
    monkeypatch.setattr(native_replay, 'ENABLED', False)
    fight = combat()
    assert fight['cycle'] == dict(hits=5.,pool=1.,enterSeconds=0.,exitSeconds=0.,chargeOn='kills',killCharged=True)
    direct, _ = fight['resolve']('base', {}, 0)
    no_kills = replay(direct, enemy(), attacks_per_second=direct.fire_rate, window_seconds=1.,
                      combat=fight, collect_timeline=True)
    assert no_kills['transforms'] == 0
    result = replay(direct, enemy(10.), attacks_per_second=direct.fire_rate, window_seconds=.8,
                    combat=fight, collect_timeline=True)
    assert result['transforms'] == 1 and result['shots'] == 6
    assert result['directWindow'] == pytest.approx(60.)  # 5 primary kills + one alternate kill; capped actual target damage.
    assert result['timeline'][0]['form'] == 'base'
    assert result['timeline'][0]['gauge'] == 3.
    assert any(t['form']=='incarnon' and t['ammo']==0. for t in result['timeline'])


def test_cortege_partial_reasons_are_field_specific_and_survive_actual_cycle():
    fight = combat()
    assert set(UNMODELED) <= set(fight['unsupported'])
    assert not any('full-charge-gate' in key or 'explosion-and-lingering' in key for key in fight['unsupported'])
    selected = reference()['auditedAttacks'][PATH]['modes']['1']
    assert selected['radials'][0]['exclusiveAlternatives'] == ['ExplosiveAttack']
    assert 'count' not in selected['radials'][0]


@pytest.mark.parametrize('health,seconds', [(10.,.8), (1000.,30.), (1e12,1.)])
def test_native_shadow_matches_real_cortege_kill_cycle(health,seconds,monkeypatch):
    if native_replay.wfcore is None:
        pytest.skip('native core unavailable')
    monkeypatch.setattr(native_replay, 'ENABLED', True)
    monkeypatch.setattr(native_replay, 'SHADOW', True)
    native_replay.STATS.update(native=0,fallback=0)
    fight = combat()
    direct, _ = fight['resolve']('base', {}, 0)
    result = replay(direct, enemy(health), attacks_per_second=direct.fire_rate, window_seconds=seconds,
                    combat=fight, collect_timeline=False)
    assert native_replay.STATS['native'] == 1 and native_replay.STATS['fallback'] == 0
    assert set(UNMODELED) <= set(result['unsupported'])
    assert (result['transforms'] > 0) == (health < 1e12)
