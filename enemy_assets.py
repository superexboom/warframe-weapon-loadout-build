from __future__ import annotations
import json
from pathlib import Path

class EnemyVisualCatalog:
    """Local, snapshot-bound image metadata. Never downloads during a request."""
    def __init__(self, dataset_root):
        self.root = Path(dataset_root).resolve()
        try:
            manifest = json.loads((self.root / 'frontend/assets/enemies/index.json').read_text(encoding='utf-8-sig'))
            self.rows = manifest.get('enemies', {}) if manifest.get('schemaVersion') == 1 else {}
        except (OSError, ValueError, AttributeError):
            self.rows = {}
        if not isinstance(self.rows, dict): self.rows = {}

    def get(self, enemy_path):
        row = self.rows.get(enemy_path)
        if not isinstance(row, dict): return dict(imageAsset=None, imageStatus='missing')
        asset = row.get('asset')
        result = dict(imageAsset=None, imageStatus=row.get('status', 'missing'), imageSourceType=row.get('iconSourceType'), imageInherited=bool(row.get('inherited')))
        if not isinstance(asset, str) or not asset.startswith('/assets/enemies/art/Lotus/Interface/'):
            return result
        if any(c in asset for c in (chr(92), '?', '#', '%')) or any(p in ('', '.', '..') for p in asset[1:].split('/')):
            return result
        path = (self.root / 'frontend' / asset[1:]).resolve()
        if not path.is_relative_to(self.root / 'frontend/assets/enemies/art') or not path.is_file():
            result['imageStatus'] = 'file-missing'
            return result
        result['imageAsset'] = asset
        return result