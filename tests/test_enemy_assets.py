from __future__ import annotations
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from enemy_assets import EnemyVisualCatalog
from tools.sync_visual_assets import canonical_icon, resolve_icon, safe, validate

ICON = '/Lotus/Interface/Icons/Npcs/TestAvatar.png'
URL = '/assets/enemies/art' + ICON
ENEMY = '/Lotus/Types/Enemies/TestAvatar'

class EnemyAssetsTest(unittest.TestCase):
    def test_local_identity_and_missing_image(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / 'frontend' / URL.lstrip('/')
            image.parent.mkdir(parents=True)
            Image.new('RGBA', (2, 3)).save(image)
            manifest = root / 'frontend/assets/enemies/index.json'
            manifest.write_text(json.dumps({'schemaVersion': 1, 'enemies': {ENEMY: {'asset': URL, 'status': 'exact'}}}), encoding='utf-8')
            catalog = EnemyVisualCatalog(root)
            self.assertEqual(catalog.get(ENEMY)['imageAsset'], URL)
            self.assertIsNone(catalog.get('/unknown')['imageAsset'])
            image.unlink()
            self.assertEqual(catalog.get(ENEMY)['imageStatus'], 'file-missing')

    def test_invalid_manifest_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / 'frontend/assets/enemies/index.json'
            manifest.parent.mkdir(parents=True)
            for value in ('{broken', '[]', '{"schemaVersion": 9}'):
                manifest.write_text(value, encoding='utf-8')
                self.assertIsNone(EnemyVisualCatalog(root).get(ENEMY)['imageAsset'])
            for asset in (URL + '?x', URL + '%00', '/assets/enemies/art/../secret.png', 'https://example.test/a.png'):
                manifest.write_text(json.dumps({'schemaVersion': 1, 'enemies': {ENEMY: {'asset': asset}}}), encoding='utf-8')
                self.assertIsNone(EnemyVisualCatalog(root).get(ENEMY)['imageAsset'])
            self.assertIsNone(canonical_icon('/Lotus/Interface/../secret.png'))
            with self.assertRaises(ValueError):
                safe(root, '/Lotus/Interface/../secret.png')

    def test_native_icon_inheritance_and_explicit_nil(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = '/Lotus/Types/Enemies/BaseAvatar'
            parent = root / ('packages' + base + '.txt')
            parent.parent.mkdir(parents=True)
            parent.write_text('Icon=' + ICON, encoding='utf-8')
            result = resolve_icon(root, {ENEMY: base}, ENEMY)
            self.assertEqual(result['icon'], ICON)
            self.assertEqual(result['iconSourceType'], base)
            self.assertTrue(result['inherited'])
            child = root / ('packages' + ENEMY + '.txt')
            child.write_text('Icon=NIL', encoding='utf-8')
            self.assertIsNone(resolve_icon(root, {ENEMY: base}, ENEMY)['icon'])
            child.unlink(); parent.unlink()
            self.assertIsNone(resolve_icon(root, {ENEMY: base, base: ENEMY}, ENEMY)['icon'])

    def test_full_image_decode_and_rgb_alpha_preservation(self):
        output = io.BytesIO()
        Image.new('RGBA', (3, 5), (100, 120, 130, 0)).save(output, format='PNG')
        raw = output.getvalue()
        result = validate(raw)
        self.assertEqual((result['width'], result['height'], result['mode']), (3, 5, 'RGBA'))
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.getpixel((0, 0)), (100, 120, 130, 0))
        with self.assertRaises((ValueError, OSError)):
            validate(b'not an image')
        with self.assertRaises((ValueError, OSError)):
            validate(raw[:30])

def test_bundled_enemy_manifest_images_match_hashes_and_decode():
    import hashlib
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'frontend/assets/enemies/index.json').read_bytes())
    catalog=EnemyVisualCatalog(root)
    unique={}
    for path,row in manifest['enemies'].items():
        if row.get('asset'):
            resolved=catalog.get(path)
            assert resolved['imageAsset']==row['asset']
            assert row['status'] in ('exact','inherited')
            unique[row['asset']]=row['sha256']
        else:
            assert catalog.get(path)['imageAsset'] is None
    assert unique
    for asset,digest in unique.items():
        p=root/'frontend'/asset.lstrip('/')
        assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,asset
        with Image.open(p) as image:
            image.load()
            assert image.width>0 and image.height>0

if __name__ == '__main__':
    unittest.main()
