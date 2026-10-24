"""Import battery (regenerating magazine) profiles from the game packages.

A battery weapon has no reload: after the last shot it waits
BatteryRegenDelayFromEmpty (falling back to BatteryRegenDelay) and refills
at BatteryRegenRate rounds per second. Under the replay's fire-until-empty
policy that is an empty-magazine reload of delay + magazine / rate, which
the exported ReloadTime does not describe (Fulmin Prime: 3 s exported,
0.7 + 80 / 40 = 2.7 s native).

Membership: many native records carry BatteryRegenRate without being
battery weapons (bows, kitguns reload normally), and the native BATTERY
compatibility tag is also on Arch-guns, Amps and the one-round Nataruk, whose
refill is not this (Imperator Vandal would be 0.25 + 300 / 75 = 4.25 s against
an export reload of 2 s that matches WFSim). The set is the pinned WFSim
battery list plus primaries / secondaries that carry the native tag and a
regen rate with a magazine above one round (adds Basmu: 2 + 21 / 42 = 2.5 s,
the wiki full reload WFSim uses as a plain reload). Values
come from the resolved native record (parents applied); WFSim's numbers are
used only when the native record has none, and are recorded beside every
entry as a cross-check (its Fulmin Prime copies the ordinary Fulmin's
30/s, 1 s; native is 40/s, 0.7 s).
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
from wfarsenal.packages import load


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--build-dir', type=Path, required=True, help='raw build dir with Packages.bin and packages/')
    ap.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    ap.add_argument('--wfsim', type=Path, required=True, help='pinned WFSim checkout (battery membership)')
    ap.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/battery-profiles.json')
    a = ap.parse_args()
    pkg = load(a.build_dir)
    reference = {}
    if True:
        import yaml
        for file in sorted((a.wfsim / 'data/weapons').rglob('*.yaml')):
            spec = yaml.safe_load(file.read_text(encoding='utf-8'))
            if isinstance(spec, dict) and spec.get('battery') and spec.get('internal_name'):
                reference[spec['internal_name']] = dict(id=spec['id'], battery=spec['battery'],
                                                        source=file.relative_to(a.wfsim).as_posix())
    weapons = json.loads(a.export.read_text(encoding='utf-8'))['data']
    out = {}
    for row in weapons:
        ref = reference.get(row['path'])
        native = pkg.resolve(row['path']) or {}
        tagged = ('BATTERY' in (row.get('compatTags') or []) and row.get('slot') in ('primary', 'secondary')
                  and native.get('BatteryRegenRate') is not None and float(native.get('AmmoClipSize') or 0) > 1)
        if not ref and not tagged:
            continue
        b = ref['battery'] if ref else {}
        # Per field: native when the record carries it, else WFSim (a missing
        # native field is a class default the dump does not contain, not 0).
        fields = dict(regenPerSecond=('BatteryRegenRate', b.get('regen_per_second')),
                      delayPartialSeconds=('BatteryRegenDelay', b.get('delay_partial_seconds', b.get('delay_empty_seconds'))),
                      delayEmptySeconds=('BatteryRegenDelayFromEmpty', None))
        values, source = {}, {}
        for key, (native_key, fallback) in fields.items():
            if native.get(native_key) is not None:
                values[key], source[key] = float(native[native_key]), 'native'
            elif key == 'delayEmptySeconds' and native.get('BatteryRegenDelay') is not None:
                values[key], source[key] = float(native['BatteryRegenDelay']), 'native-BatteryRegenDelay'
            else:
                fallback = b.get('delay_empty_seconds') if key == 'delayEmptySeconds' else fallback
                values[key], source[key] = float(fallback or 0.0), 'wfsim-native-absent' if ref else 'absent'
        rate, empty, partial = values['regenPerSecond'], values['delayEmptySeconds'], values['delayPartialSeconds']
        entry = dict(name=row.get('nameEn'), membership=[m for m, on in (('wfsim', ref), ('native-tag', tagged)) if on], valueSource=source, regenPerSecond=rate, delayEmptySeconds=empty, delayPartialSeconds=partial,
                     nativeMagazine=native.get('AmmoClipSize'), exportReloadTimes=[m.get('reloadTime') for m in row.get('fireModes') or []])
        if b.get('empty_animation_seconds') is not None:
            # A measured reload animation on an empty battery (WFSim M121, Haalvu): see damage.py.
            entry['emptyAnimationSeconds'] = float(b['empty_animation_seconds'])
            entry['emptyAnimationSource'] = 'WFSim ' + ref['source']
        own = pkg._path_to_file(row['path'])
        if own.is_file():
            entry['nativeSha256'] = hashlib.sha256(own.read_bytes()).hexdigest()
        if ref:
            entry['wfsim'] = dict(id=ref['id'], source=ref['source'], regenPerSecond=b.get('regen_per_second'),
                                  delayEmptySeconds=b.get('delay_empty_seconds'))
            if (abs(float(b.get('regen_per_second') or 0) - rate) > 1e-6
                    or abs(float(b.get('delay_empty_seconds') or 0) - empty) > 1e-6):
                entry['wfsimDiffers'] = True
        out[row['path']] = entry
    payload = dict(schemaVersion=1, packageBuild=a.build_dir.name, generatedBy='tools/import_battery_profiles.py',
                   semantics='empty-magazine refill = delayEmptySeconds / reload speed + magazine / regenPerSecond; '
                             'with emptyAnimationSeconds: max(emptyAnimationSeconds / reload speed, delayPartialSeconds + magazine / regenPerSecond)',
                   weapons=out)
    a.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(len(out), 'battery weapons;', sum(1 for e in out.values() if e.get('wfsimDiffers')), 'differ from WFSim')
    for path, e in out.items():
        print(f"  {e['name']:24s} {e['regenPerSecond']:g}/s empty {e['delayEmptySeconds']:g}s partial {e['delayPartialSeconds']:g}s"
              f" export reload {e['exportReloadTimes']} {'WFSIM DIFFERS ' + str(e['wfsim']) if e.get('wfsimDiffers') else ''}")


if __name__ == '__main__':
    main()
