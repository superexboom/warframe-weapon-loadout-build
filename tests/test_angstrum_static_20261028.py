"""Pinned native Angstrum packet and full-charge profile admission."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pytest
import app
from tools import import_native_angstrum as importer
from wfarsenal.damage import Scenario, quantize_base_crit_damage
from wfarsenal.manual_combat import prepare, reference

ROOT = Path(__file__).resolve().parents[1]


def weapon(path):
    return deepcopy(next(w for w in app.EXPORTS['weapons'] if w['path'] == path))


@pytest.mark.parametrize('path,seconds,cc,cd,proc', [
    (importer.WEAPONS[0], .5, .16, 2., .22),
    (importer.WEAPONS[1], .2, .18000001, 2.2, .10000000149011612)])
def test_single_projectile_profile_and_preparation(path, seconds, cc, cd, proc):
    spec = reference()['auditedAttacks'][path]
    assert spec['fireMode'] == 0 and spec['behaviourSource'] == 'Behaviors[0]'
    assert spec['chargeVolley'] == importer.CHARGE_VOLLEY
    assert spec['charge']['seconds'] == seconds
    assert spec['source']['clientSha256'] == importer.CLIENT_SHA
    assert spec['packageSha256'] == importer.PACKAGE_SHA
    assert {source['path']:source['sha256'] for source in spec['nativeSources']} == {
        source:importer.RAW_SHA[source] for source in dict.fromkeys(
            importer.CHAINS[path]+importer.CHAINS[spec['projectile']])}
    assert 'angstrum-single-rocket-explosion-unmodeled' not in spec['unmodeled']
    radial = spec['radials'][0]
    assert radial['damage'] == {'blast':250.}
    assert radial['crit_chance'] == cc and radial['crit_multiplier'] == cd
    assert radial['status_chance'] == proc
    fight = prepare(dict(weapon=weapon(path), fire_mode=0, effects=[], scenario=Scenario()), [], [])
    direct, part = fight['resolve']('selected', {}, 0)
    assert fight['chargeVolley']
    assert direct._charge_volley == importer.CHARGE_VOLLEY
    assert direct._charge_time == pytest.approx(seconds)
    assert direct.damage_types == {'DT_EXPLOSION':200.} and direct.multishot == 1.
    assert part.damage_types == {'DT_EXPLOSION':250.} and part.multishot == 1.
    assert part.crit_chance == pytest.approx(cc)
    assert part.crit_multiplier == pytest.approx(quantize_base_crit_damage(cd))
    assert part.status_chance == pytest.approx(proc)


@pytest.mark.parametrize('path', importer.WEAPONS)
def test_charge_volley_does_not_leak_into_incarnon(path):
    fight = prepare(dict(weapon=weapon(path), fire_mode=1, effects=[], scenario=Scenario()), [], [])
    active, radial = fight['resolve']('selected', {}, 0)
    assert not getattr(active, '_charge_volley', None)
    assert not any(x.startswith('angstrum-') for x in fight['unsupported'])


@pytest.fixture
def sources(tmp_path, monkeypatch):
    """Exercise actual file SHA validation with synthetic but complete raw ancestry."""
    from wfarsenal.packages import PackageIndex
    from tools.import_kill_charged_alts import raw_source_sha
    roots = {path:{} for path, sha in importer.RAW_SHA.items() if sha is not None}
    for ordinal, path in enumerate(importer.WEAPONS):
        roots[path] = dict(MaxCharges=120, Behaviors=[{
            'fire:WeaponProjectileFireBehavior':dict(fireIterations=1, ammoRequirement=1,
                AttenuateForCharge=0, AttenuateFireIterationsForCharge=1,
                ConsumesChargesForFire=0, ConsumeRemainingClip=0),
            'state:WeaponChargedStateBehavior':dict(ClipSizeAffectsChargeTime=1,
                UseClipSizeAsDamageMultiplier=1, UseClipWhileCharging=0,
                ApplyNumChargesToDamageMultiplier=1, MinChargeRatio=1,
                MinDamageMultiplier=.001, MaxDamageMultiplier=0, DamageMultiplier=1,
                AutoFireWhenChargeCompleted=1, ChargeTime=.5 if ordinal==0 else .2,
                ChargeModifier='WEAPON_FIRE_RATE')}, {}])
        roots[importer.PROJECTILES[ordinal]] = dict(AttackData=dict(Amount=200,
            Type='DT_EXPLOSION', ProcChance=.22 if ordinal==0 else .25999999),
            ExplosiveAttack=dict(Amount=250, **({'ProcChance':.22} if ordinal==0 else {})),
            DealDamageThroughImpactBehavior=1, DamageRadius=3.5999999,
            ExplosionFallOff=.40000001, CriticalChance=.16 if ordinal==0 else .18000001,
            CriticalMultiplier=2. if ordinal==0 else 2.2)
    for path, value in roots.items():
        file = tmp_path/(path.lstrip('/')+'.json')
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps(value), encoding='utf-8')
    parents = {a:b for chain in importer.CHAINS.values() for a,b in zip(chain,chain[1:])}
    pkg = PackageIndex(tmp_path, parents)
    monkeypatch.setattr(importer, 'RAW_SHA', {path:raw_source_sha(pkg,path) for path in importer.RAW_SHA})
    image = tmp_path/'client.exe'; image.write_bytes(b'audited-client-fixture')
    raw = tmp_path/'Packages.bin'; raw.write_bytes(b'audited-packages-fixture')
    monkeypatch.setattr(importer, 'CLIENT_SHA', hashlib.sha256(image.read_bytes()).hexdigest())
    monkeypatch.setattr(importer, 'PACKAGE_SHA', hashlib.sha256(raw.read_bytes()).hexdigest())
    return pkg, image, raw


@pytest.mark.parametrize('path', importer.WEAPONS)
def test_importer_reproduces_full_profile_with_pinned_inputs(sources, path):
    pkg, image, raw = sources
    spec = importer.profile(pkg, weapon(path), native_image=image, raw_package=raw)
    assert spec['chargeVolley'] == importer.CHARGE_VOLLEY
    assert spec['radials'][0]['damage'] == {'blast':250.}


@pytest.mark.parametrize('changed', sorted(importer.RAW_SHA))
def test_importer_rejects_changed_source_anywhere_in_complete_ancestry(sources, changed):
    pkg, image, raw = sources
    file = pkg._path_to_file(changed)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('{"changed":1}', encoding='utf-8')
    affected = next(path for path, projectile in zip(importer.WEAPONS, importer.PROJECTILES)
                    if changed in importer.CHAINS[path]+importer.CHAINS[projectile])
    with pytest.raises(ValueError, match='raw source changed'):
        importer.profile(pkg, weapon(affected), native_image=image, raw_package=raw)


@pytest.mark.parametrize('target', ['image', 'package', 'parents', 'mode'])
def test_importer_rejects_wrong_binary_chain_and_incarnon_mode(sources, target):
    pkg, image, raw = sources
    row = weapon(importer.WEAPONS[0])
    if target=='image': image.write_bytes(b'changed-client')
    elif target=='package': raw.write_bytes(b'changed-packages')
    elif target=='parents': pkg.parents[importer.WEAPONS[0]]='/UnknownParent'
    else: row['fireModes'][0]['index']=1
    with pytest.raises(ValueError):
        importer.profile(pkg, row, native_image=image, raw_package=raw)


def test_importer_only_updates_two_weapons_and_preserves_unrelated_and_modes(sources):
    pkg, image, raw = sources
    payload = dict(auditedAttacks={'/Unrelated':{'x':1}, importer.WEAPONS[0]:{
        'modes':{'1':{'projectile':'incarnon-preserved'}}}}, other={'preserved':True})
    importer.import_profiles(pkg, [weapon(path) for path in importer.WEAPONS], payload,
                             native_image=image, raw_package=raw)
    assert payload['auditedAttacks']['/Unrelated']=={'x':1}
    assert payload['auditedAttacks'][importer.WEAPONS[0]]['modes']['1']=={'projectile':'incarnon-preserved'}
    assert payload['other']=={'preserved':True}


def test_manual_api_reports_completed_charge_volley_events():
    result=app.simulate_manual_payload(dict(weapon=importer.WEAPONS[0],fireMode=0,
        enemy=app._BENCHMARK_ENEMY_PATH,level=1,mods=[],windowSeconds=1.501))
    volley=result['benchmarkTimeline']['chargeVolley']
    assert volley['policy']=='full-magazine'
    assert len(volley['events'])==1
    assert volley['events'][0]['time']==1.5
    assert volley['events'][0]['loadedRounds']==3.
    assert volley['events'][0]['ammoCost']==3.


@pytest.mark.parametrize('path',importer.WEAPONS)
@pytest.mark.parametrize('loaded',[1.,3.])
def test_native_charge_branch_vetoes_last_multishot_even_when_one_round_remains(path,loaded):
    row=weapon(path)
    # Exercise the native veto explicitly; today's Angstrum evolution list has
    # no such term. A future/injected term must not bypass the branch contract.
    row['incarnon']={'tiers':[{'tier':2,'branches':[{'id':'2-1','effects':[
        {'upgradeType':'WEAPON_LAST_MULTISHOT','operation':'ADD','valuePerRank':3.}]}]}]}
    fight=prepare(dict(weapon=row,fire_mode=0,effects=[],scenario=Scenario()),[],[],incarnon_choices={'tier2':'2-1'})
    normal,radial=fight['resolve']('selected',{'__chargeVolleyRounds':loaded},0,last_round=True)
    assert normal.multishot==loaded and radial.multishot==loaded
