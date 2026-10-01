"""Decode the remaining exact runtime scripts with the verified client map."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from audit_weapon_luau import decode, render

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    '/Lotus/Weapons/Thanotech/EntratiWristGun/WristGunIncarnonEvolutions/WristGunIncarnonSubUpgrades/EntratiWristGunIncarnonDamageForPunchthrough.lua',
    '/Lotus/Upgrades/Evolutions/Shotgun/EvoShotgunAmmoEffOnPunchthrough.lua',
    '/Lotus/Weapons/Tenno/Pistols/ConclaveLeverPistol/ZylokIncarnonEvolutions/ZylokOnBurstHeadShot.lua',
    '/Lotus/Types/Challenges/EvolvingWeaponUpgrades.lua',
    '/Lotus/Scripts/WeaponAttachments/ZarimanHeavyRifle.lua',
    '/Lotus/Weapons/Grineer/LongGuns/GrineerSawbladeGun/MiterIncarnonEvolutions/ProjectileIndexOnExtraCharge.lua',
    '/Lotus/Upgrades/CosmeticEnhancers/Utility/OnWarframeAbilityCondition.lua',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--opcode-map', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('choose a new evidence directory')
    args.output.mkdir(parents=True)
    spec = importlib.util.spec_from_file_location('raw_extract', ROOT/'tools/luau-extract.py')
    exporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    mapping = {int(k): tuple(v) for k, v in json.loads(args.opcode_map.read_bytes())['mapping'].items()}
    records = []
    for internal in SCRIPTS:
        body = exporter.OUT_RAW/'Debug'/(internal.lstrip('/')+'_B')
        body = body if body.is_file() else exporter.extract(internal)
        if not body:
            records.append(dict(path=internal, status='not-extracted'))
            print('missing', internal, flush=True)
            continue
        decoded = decode(body, mapping)
        name = body.name.removesuffix('.lua_B')
        (args.output/(name+'.json')).write_text(json.dumps(decoded, indent=2)+'\n', encoding='utf-8')
        (args.output/(name+'.txt')).write_text(render(decoded), encoding='utf-8')
        unknown = sum(len(p['unknownPcs']) for p in decoded['protos'])
        jumps = sum(len(p['invalidJumpPcs']) for p in decoded['protos'])
        records.append(dict(path=internal, sha256=decoded['sha256'], unknown=unknown, invalidJumps=jumps))
        print(name, decoded['sha256'], 'unknown=', unknown, 'invalidJumps=', jumps, flush=True)
    (args.output/'manifest.json').write_text(json.dumps(records, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
