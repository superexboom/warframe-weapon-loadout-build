"""Import kill-charged alternate fires (Trumna grenade, Sepulcrum, Higasa, Morgha, Mausolon, Cortege).

The weapon's charge system (the one Incarnon gauges use) is native:
``AddCharges`` (or legacy ``AddChargeConditions``) says what earns charges,
``NumCharges`` (legacy ``NumChargesToAdd``) how many
(default 1), ``ConsumeChargeConditions`` SECONDARY_FIRE that the alternate
fire spends ``NumChargesToConsume`` per shot; zero consumes all charges when
``RequireFullCharges`` establishes a proven positive full gauge. (``RequireFullCharges`` /
``MaxCharges``: Higasa needs its full 100 at 7 per kill). For the kill
conditions (PRIMARY_KILL, DEFAULT_BEHAVIOR_KILL) the alternate fire cannot be
fired on its own: it fires once per ``killsPerUse`` primary kills. The
replay runs it as a cycle (primary until the gauge is full, switch with the
alternate behaviour's ``ModeSwitchTime`` - 1 s on Trumna, 0 elsewhere -
fire, switch back with the primary's). Modes are matched by behaviour
position (export ``fireModes[i].index``).
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from wfarsenal.packages import load
from wfarsenal.extract import _sub_behaviour
from tools.import_projectile_components import exported_behaviours

KILL_CONDITIONS = {'PRIMARY_KILL', 'DEFAULT_BEHAVIOR_KILL'}


CORTEGE = '/Lotus/Weapons/Tenno/Archwing/Primary/ThanoTechArchGun/ThanoTechArchGun'
CORTEGE_RAW_SHA = 'dcc64234db4a416585f825e5f7ec98e0a7da813fdaaac1872d6162533fd78b18'
# These are properties of the preserved EXE, not universal inferred defaults.
PROVEN_DEFAULT_MAX_CHARGES = {
    CORTEGE: dict(value=5, nativeSha256=CORTEGE_RAW_SHA,
        packageBuild='2026.10.22.13.12',
        packageSha256='00ca82217ae21bafb31133165b8e3ea098c048783c14958fdfe23f76288bfa06',
        clientSha256='eec0dbd7078cd6e1f2402fc953ec2741e87a6fb2658ec288be195aac75a1e76d',
        defaultMaxAddress='0x140bf8f9b', maxRegistrationAddress='0x14102c567',
        fullGateFunction='0x140b169c0', consumeAllFunction='0x141377080',
        descriptorNameOffset=8,
        ancestrySources=[
            dict(path=CORTEGE, sha256=CORTEGE_RAW_SHA),
            dict(path='/Lotus/Weapons/Tenno/Archwing/Primary/ArchGun',
                 sha256='cc06e93ed07418ffeb897430531ce364815d2088a237b3486319eca4d0f4e356'),
            dict(path='/Lotus/Types/Game/LotusWeapon',
                 sha256='4e4ff3b358962ff188c9bf130961eb1814eec7c47858234dd6f8b746f4dd9881')]),
}


def raw_source_sha(pkg, path):
    own = pkg._path_to_file(path)
    if not own.is_file():
        own = own.with_suffix('.txt')
    return hashlib.sha256(own.read_bytes()).hexdigest() if own.is_file() else None


def verified_default_max(pkg, path, native_image=None):
    """Admit a native constructor default only for its exact EXE and raw ancestry.

    A child file surviving a game update does not prove unchanged inherited
    properties or unchanged native defaults. Missing provenance fails closed.
    """
    proof = PROVEN_DEFAULT_MAX_CHARGES.get(path)
    if not proof or native_image is None:
        return None
    image = Path(native_image)
    if not image.is_file() or hashlib.sha256(image.read_bytes()).hexdigest() != proof['clientSha256']:
        return None
    sources = proof['ancestrySources']
    if pkg.ancestry(path) != [row['path'] for row in sources]:
        return None
    if any(raw_source_sha(pkg, row['path']) != row['sha256'] for row in sources):
        return None
    return proof


def build_profile(pkg, row, *, native_image=None):
    """Return (profile, skip reason), preserving zero-consumption full gates."""
    native = pkg.resolve(row['path']) or {}
    charge_rows = native.get('AddCharges')
    if isinstance(charge_rows, list) and charge_rows:
        qualifying = [r for r in charge_rows if isinstance(r, dict)
                      and set(r.get('Conditions') or []) & KILL_CONDITIONS]
        if not qualifying:
            return None, None
        if len(qualifying) != 1:
            return None, 'ambiguous kill-charge sources'
        add_on = set(qualifying[0].get('Conditions') or [])
        add = float(qualifying[0].get('NumCharges', 1))
    else:
        add_on = set(native.get('AddChargeConditions') or [])
        add = float(native.get('NumChargesToAdd', 1))
    if not add_on & KILL_CONDITIONS or 'SECONDARY_FIRE' not in (native.get('ConsumeChargeConditions') or []):
        return None, None
    if add <= 0 or not math.isfinite(add):
        return None, 'non-positive or non-finite charges per kill'
    consume = float(native.get('NumChargesToConsume') or 0)
    full = bool(native.get('RequireFullCharges'))
    maximum = native.get('MaxCharges')
    proof = None
    if full and maximum is None:
        proof = verified_default_max(pkg, row['path'], native_image)
        if proof:
            maximum = proof['value']
    if consume <= 0 and not (consume == 0 and full and maximum is not None and float(maximum) > 0):
        return None, 'zero consumption without a proven full-charge gate; shot scaling remains unresolved'
    maximum = float(maximum if maximum is not None else consume)
    if not math.isfinite(maximum) or maximum <= 0 or not math.isfinite(consume):
        return None, 'invalid maximum or consumption'
    if full and maximum < consume:
        return None, 'full gauge cannot cover consumption'
    behaviours = exported_behaviours(native, row)
    alt = [i for i, b in enumerate(behaviours) if isinstance(b, dict)
           and (_sub_behaviour(b, 'fire:') or {}).get('ConsumesChargesForFire')]
    modes = row.get('fireModes') or []
    if len(alt) != 1:
        return None, f'{len(alt)} charge-consuming behaviours'
    alt_modes = [i for i, m in enumerate(modes) if m.get('index', i) == alt[0]]
    primary_modes = [i for i, m in enumerate(modes) if m.get('index', i) == 0]
    if len(alt_modes) != 1 or primary_modes != [0]:
        return None, 'alternate / primary mode not matched'
    alt_state = _sub_behaviour(behaviours[alt[0]], 'state:') or {}
    primary_state = _sub_behaviour(behaviours[0], 'state:') or {}
    required = maximum if full else consume
    entry = dict(name=row['nameEn'], altMode=alt_modes[0], primaryMode=0,
        killsPerUse=math.ceil(required / add - 1e-9),
        shotsPerGauge=1 if full else max(1, int(maximum // consume)),
        switchInSeconds=float(alt_state.get('ModeSwitchTime') or 0.),
        switchOutSeconds=float(primary_state.get('ModeSwitchTime') or 0.),
        native=dict(AddChargeConditions=sorted(add_on), NumChargesToAdd=add,
            NumChargesToConsume=consume, MaxCharges=native.get('MaxCharges'),
            RequireFullCharges=native.get('RequireFullCharges')))
    audited_mode_sources=('/Lotus/Weapons/Corpus/LongGuns/CrpSentExperimentRifle/CrpSentExperimentRifle', '/Lotus/Weapons/Tenno/Archwing/Primary/ThanoTechArchGun/ThanoTechArchGun', '/Lotus/Weapons/Tenno/Archwing/Primary/ThanoTechArchLongGun/ThanoTechLongGun', '/Lotus/Weapons/Tenno/Archwing/Primary/ThanoTechGrenadeLaunch/ThanoTechGrenadeLauncher', '/Lotus/Weapons/Tenno/LongGuns/Gunbrella/ShrineMaidenGunbrellaWeapon', '/Lotus/Weapons/Tenno/LongGuns/PrimeTrumna/PrimeTrumnaWeapon', '/Lotus/Weapons/Thanotech/ThanoPistol/ThanotechPistol', '/Lotus/Weapons/Thanotech/ThanoRifle/ThanotechRifle')
    if row['path'] in audited_mode_sources and add_on=={'PRIMARY_KILL'}:
        entry['sourceModeKillChargeTrue']=True
    sha = raw_source_sha(pkg, row['path'])
    if sha:
        entry['nativeSha256'] = sha
    if proof:
        entry['native']['effectiveMaxCharges'] = maximum
        entry['native']['zeroConsumptionMeans'] = 'consume-all-current-charges'
        entry['source'] = dict(proof)
    return entry, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--native-image', type=Path, help='matching audited EXE required for omitted native MaxCharges defaults')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/kill-charge-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    out, skipped = {}, []
    for row in json.loads(a.export.read_text(encoding='utf-8'))['data']:
        entry, reason = build_profile(pkg, row, native_image=a.native_image)
        if entry:
            out[row['path']] = entry
        elif reason:
            skipped.append(dict(name=row['nameEn'], reason=reason))
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_kill_charged_alts.py',
        semantics='the alternate mode fires shotsPerGauge shots per killsPerUse primary-fire kills; selecting it '
                  'replays the primary + alternate cycle', weapons=out, skipped=skipped)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'kill-charged alternates;', len(skipped), 'skipped')
    for e in out.values():
        print(f"  {e['name']:14s} mode {e['altMode']}: {e['killsPerUse']} kills -> {e['shotsPerGauge']} shot")
    for row in skipped:
        print('  skip', row)


if __name__ == '__main__':
    main()
