"""Restore native localization metadata without rebuilding combat records."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor'))
sys.path.insert(0, str(ROOT))
from wfarsenal.extract import _build_effect
from wfarsenal.packages import PackageIndex


def refresh(packages: Path, export: Path) -> dict:
    index = PackageIndex(packages, json.loads((packages.parent / 'parents.json').read_text(encoding='utf-8-sig')))
    original = export.read_bytes()
    payload = json.loads(original)
    replacements = []
    sources = {}
    skipped = []
    updated = 0

    def restore(effects, source_path):
        nonlocal updated
        native = [_build_effect(row) for row in index.resolve(source_path).get('Upgrades') or [] if isinstance(row, dict)]
        # Repeated NONE placeholders have different prose; order is meaningful.
        identity = lambda row: tuple(row.get(k) for k in ('upgradeType', 'operation', 'valuePerRank', 'damageType'))
        if len(effects) != len(native) or [identity(e) for e in effects] != [identity(e) for e in native]:
            skipped.append(source_path)
            return
        path = index._path_to_file(source_path)
        if not path.is_file():
            path = path.with_suffix('.txt')
        if path.is_file():
            sources[source_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        for effect, raw in zip(effects, native):
            for key in ('locTag', 'displayAsPercent', 'displayAsMultiplier', 'reverseValueSymbol', 'localizationScript'):
                if key in raw and effect.get(key) != raw[key]:
                    effect[key] = deepcopy(raw[key])
                    updated += 1

    for weapon in payload['data']:
        if not weapon.get('incarnon'):
            continue
        before = deepcopy(weapon)
        for tier in weapon['incarnon'].get('tiers') or []:
            for branch in tier.get('branches') or []:
                blocks = [branch, *(branch.get('sources') or [])]
                for block in blocks:
                    groups = {}
                    for effect in block.get('effects') or []:
                        path = effect.get('sourcePath') or branch.get('path')
                        groups.setdefault(path, []).append(effect)
                    for path, effects in groups.items():
                        restore(effects, path)
                    for condition in block.get('conditionalEffects') or []:
                        restore(condition.get('effects') or [], condition.get('sourcePath') or branch.get('path'))
        if weapon != before:
            replacements.append((before, weapon))
    # Replace only changed structured records. Avoid line-ending churn in the
    # surrounding snapshot and retain the file's existing serialization style.
    candidate = original.decode('utf-8').replace('\r\n', '\n')
    for before, after in replacements:
        old = json.dumps(before, ensure_ascii=False, indent=1, sort_keys=True).replace('\n', '\n  ')
        new = json.dumps(after, ensure_ascii=False, indent=1, sort_keys=True).replace('\n', '\n  ')
        if candidate.count(old) != 1:
            raise ValueError('export record layout ambiguous: ' + before['path'])
        candidate = candidate.replace(old, new, 1)
    from tools.refresh_spread_talons import preserve_lines
    export.write_bytes(preserve_lines(original, candidate.encode('utf-8')))
    return dict(sourceBuild=packages.parent.name, updatedWeapons=len(replacements), updatedFields=updated,
                nativeSources=sources, skippedSources=sorted(set(skipped)),
                beforeSha256=hashlib.sha256(original).hexdigest(), afterSha256=hashlib.sha256(export.read_bytes()).hexdigest())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packages', type=Path, required=True)
    parser.add_argument('--export', type=Path, default=ROOT / 'data/export/2026.08.13.13.24/weapons.json')
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.evidence.exists():
        parser.error('choose a new evidence path')
    result = refresh(args.packages, args.export)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ('updatedWeapons', 'updatedFields', 'skippedSources')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
