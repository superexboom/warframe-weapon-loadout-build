"""Import sniper Shot Combo Counter and scope bonuses from a pinned WFSim checkout.

The game export (data/export/*/weapons.json) carries neither the combo minimum,
the combo decay period nor any zoom-level bonus, so these rows are taken from
WFSim's weapon YAML with explicit provenance: repository commit, source file and
its SHA-256 per weapon. Output is ``data/mechanics/sniper-profiles.json``; the
WFSim checkout is read-only.

    python tools/import_sniper_profiles.py --wfsim PATH/TO/wfsim
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'magenie33/wfsim'
# WFSim engine/src/model/weapon.rs `combo_seconds_default`: "All sniper rifles
# have a 2 second combo duration, with the exception of the Lanka".
DEFAULT_COMBO_SECONDS = 2.0
SCOPE_KEYS = {
    'crit_multiplier': 'critMultiplier',
    'crit_chance': 'critChance',
    'crit_chance_post_mod': 'critChancePostMod',
    'headshot_damage': 'headshotDamage',
}


def load_weapons(wfsim: Path):
    rows, files = {}, {}
    for path in sorted((wfsim / 'data/weapons').rglob('*.yaml')):
        row = yaml.safe_load(path.read_text(encoding='utf-8'))
        if isinstance(row, dict) and row.get('id'):
            rows[row['id']] = row
            files[row['id']] = path
    return rows, files


def resolved(rows, key, seen=()):
    row = rows.get(key, {})
    if key in seen or not row.get('inherits'):
        return row
    return {**resolved(rows, row['inherits'], (*seen, key)), **row}


def profiles(wfsim: Path, commit: str, export_paths: set[str]):
    rows, files = load_weapons(wfsim)
    out = {}
    for key in sorted(rows):
        row = resolved(rows, key)
        combo, scope = row.get('sniper_combo'), row.get('scope')
        if not combo and not scope:
            continue
        path = row.get('internal_name')
        if not path:
            raise ValueError(f'{key}: sniper data without internal_name')
        if path not in export_paths:
            raise ValueError(f'{key}: {path} is not in the weapon export')
        entry = {
            'referenceId': key,
            'referenceCommit': commit,
            'referenceSource': files[key].relative_to(wfsim).as_posix(),
            'referenceSha256': hashlib.sha256(files[key].read_bytes()).hexdigest(),
        }
        if combo:
            minimum = combo.get('min')
            if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
                raise ValueError(f'{key}: invalid sniper_combo.min')
            seconds = float(combo.get('seconds', DEFAULT_COMBO_SECONDS))
            if seconds <= 0:
                raise ValueError(f'{key}: invalid sniper_combo.seconds')
            entry['sniperCombo'] = {'min': minimum, 'seconds': seconds}
        if scope:
            unknown = set(scope) - {'magnification', *SCOPE_KEYS}
            if unknown:
                raise ValueError(f'{key}: unknown scope fields {sorted(unknown)}')
            entry['scope'] = {
                'magnification': scope.get('magnification'),
                **{SCOPE_KEYS[k]: float(scope.get(k) or 0.0) for k in SCOPE_KEYS},
            }
        if path in out:
            # Another form of the same native weapon (lanka_uncharged inherits
            # lanka). The export has one record per path, so the data must agree.
            first = out[path]
            if any(first.get(k) != entry.get(k) for k in ('sniperCombo', 'scope')):
                raise ValueError(f'{key}: conflicts with {first["referenceId"]} on {path}')
            first.setdefault('referenceAliases', []).append(key)
            continue
        out[path] = entry
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wfsim', type=Path, required=True, help='WFSim git checkout (read-only)')
    parser.add_argument('--commit', help='Source commit when --wfsim is not a git checkout')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/mechanics/sniper-profiles.json')
    parser.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    args = parser.parse_args()
    commit = args.commit or subprocess.check_output(
        ['git', '-C', str(args.wfsim), 'rev-parse', 'HEAD'], text=True).strip()
    export = json.loads(args.export.read_text(encoding='utf-8'))
    weapons = export['data'] if isinstance(export, dict) else export
    found = profiles(args.wfsim, commit, {w['path'] for w in weapons if w.get('path')})
    document = {
        'source': {'repository': REPOSITORY, 'commit': commit,
                   'reason': 'game export has no sniper combo or zoom-bonus fields'},
        'weapons': found,
    }
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{len(found)} sniper profiles from {REPOSITORY}@{commit}')


if __name__ == '__main__':
    main()
