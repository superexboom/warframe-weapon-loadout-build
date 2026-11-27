from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

import numpy as np
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "vendor") not in sys.path:
    sys.path.insert(0, str(ROOT / "vendor"))

from tools import slim_portable_bundle as slim
from wfarsenal import arena_scene


def _unpack_wfvm_like_js(buf: bytes) -> dict:
    assert buf[:4] == b"WFVM"
    version, header_len = struct.unpack_from("<II", buf, 4)
    assert version == 1
    data = json.loads(buf[12 : 12 + header_len].decode("utf-8"))
    offset = (12 + header_len + 3) & ~3
    for mesh in data["meshes"]:
        assert offset % 4 == 0
        v_floats = mesh["vertexCount"] * 3
        mesh["positions"] = np.frombuffer(buf, dtype="<f4", count=v_floats, offset=offset)
        offset += v_floats * 4
        i_count = mesh["indexCount"]
        if mesh["indexBits"] == 16:
            mesh["indices"] = np.frombuffer(buf, dtype="<u2", count=i_count, offset=offset)
            offset = (offset + i_count * 2 + 3) & ~3
        else:
            assert offset % 4 == 0
            mesh["indices"] = np.frombuffer(buf, dtype="<u4", count=i_count, offset=offset)
            offset += i_count * 4
    assert offset == len(buf)
    return data


def test_refuses_source_checkout_in_place():
    with pytest.raises(ValueError, match="separately staged"):
        slim.slim_bundle(ROOT, root=ROOT)


def test_visual_map_binary_compacts_dead_and_duplicate_vertices_losslessly():
    # Vertices 0 and 4 are unused; vertices 1 and 5 are exact duplicates
    positions = [
        999.0, 999.0, 999.0,  # 0 unused
        1.25, -2.5, 3.75,     # 1 used
        4.0, 5.0, 6.0,        # 2 used
        7.0, 8.0, -9.5,       # 3 used
        888.0, 888.0, 888.0,  # 4 unused
        1.25, -2.5, 3.75,     # 5 duplicate of 1
    ]
    indices = [1, 2, 3, 5, 3, 2]
    payload = {
        "schema": "arena-visual-map/v1",
        "metadata": {"mapId": "test"},
        "materials": [{"id": 0, "color": "#888888", "sourcePath": "/M"}],
        "instances": [{"entityId": 1, "meshId": 0, "position": [0, 0, 0], "quaternion": [0, 0, 0, 1], "scale": 1}],
        "meshes": [{
            "id": 0,
            "path": "/Mesh.fbx",
            "positions": positions,
            "indices": indices,
            "groups": [{"start": 0, "count": 6, "materialId": 0}],
            "triangleCount": 2,
        }],
    }
    packed = slim.pack_visual_map_binary(payload)
    decoded = _unpack_wfvm_like_js(packed)
    mesh = decoded["meshes"][0]
    assert mesh["vertexCount"] == 3
    assert mesh["indexCount"] == 6
    assert mesh["indexBits"] == 16

    orig_pos = np.asarray(positions, dtype=np.float32).reshape(-1, 3)
    dec_pos = mesh["positions"].reshape(-1, 3)
    orig_tris = orig_pos[np.asarray(indices)]
    dec_tris = dec_pos[mesh["indices"]]
    np.testing.assert_array_equal(orig_tris, dec_tris)


def test_navigation_binary_roundtrip_is_bit_exact_on_real_corpus_ship():
    nav_gz = (ROOT / "data/arena/corpus-ship-defense.navigation.json.gz").read_bytes()
    orig = json.loads(gzip.decompress(nav_gz))
    packed = slim.pack_navigation_binary(orig)
    assert packed is not None
    comp_gz = gzip.compress(packed, compresslevel=9)
    assert len(comp_gz) < len(nav_gz) * 0.20
    restored = arena_scene._unpack_navigation_bin(packed)
    assert restored == orig

    non_exact = {"schema": 1, "links": [{"from": 0, "to": 1, "kind": "walk", "seconds": 1.0, "points": [[0.123456789, 0.0, 1.0], [1.0, 0.0, 1.0]]}]}
    assert slim.pack_navigation_binary(non_exact) is None


def test_end_to_end_slim_bundle_on_staged_fixture(tmp_path):
    dest = tmp_path / "staged"
    build = "2026.08.13.13.24"
    (dest / "data/export" / build).mkdir(parents=True)
    (dest / "data/mechanics").mkdir(parents=True)
    (dest / "data/arena").mkdir(parents=True)
    (dest / "frontend/assets/mods/art/Rifle").mkdir(parents=True)
    (dest / "frontend/assets/companions/mods").mkdir(parents=True)
    (dest / "frontend/assets/warframes/mods").mkdir(parents=True)
    (dest / "frontend/assets/weapons").mkdir(parents=True)
    (dest / "frontend/assets/enemies/art/Lotus/Interface").mkdir(parents=True)
    (dest / "frontend/assets/riven").mkdir(parents=True)

    (dest / "data/source-lock.json").write_text(json.dumps({"activeBuild": build}), encoding="utf-8")
    (dest / "data/portable-runtime.json").write_text(json.dumps({"buildLabel": build}), encoding="utf-8")
    (dest / "frontend/index.html").write_text(
        '<!doctype html><html><head><script src="/enemy-images.js" defer></script>'
        '<script src="/app.js?v=1" defer></script></head><body></body></html>',
        encoding="utf-8",
    )

    # 1. Card art fixture
    rng = np.random.default_rng(42)
    rgba = rng.integers(0, 256, size=(64, 64, 4), dtype=np.uint8)
    rgba[:32, :, 3] = 0
    rgba[32:, :, 3] = 255
    card_stem = dest / "frontend/assets/mods/art/Rifle/TestMod"
    Image.fromarray(rgba, "RGBA").save(card_stem.with_suffix(".png"))
    Image.fromarray(rgba[:, :, :3], "RGB").save(card_stem.with_suffix(".bg.jpg"), quality=90)
    Image.fromarray(rgba, "RGBA").save(card_stem.with_suffix(".fg.png"))

    # 2. Legacy dead dir + duplicate/orphan weapons
    (dest / "frontend/assets/warframes/mods/Old.jpg").write_bytes(b"legacy" * 500)
    w_img = Image.fromarray(rng.integers(0, 256, size=(128, 128, 4), dtype=np.uint8), "RGBA")
    buf_w = dest / "frontend/assets/weapons/BratonPrime.png"
    w_img.save(buf_w)
    (dest / "frontend/assets/weapons/DuplicateBraton.png").write_bytes(buf_w.read_bytes())
    (dest / "frontend/assets/weapons/OrphanUnused.png").write_bytes(buf_w.read_bytes())
    (dest / "data/export" / build / "weapons.json").write_text(
        json.dumps({"data": [
            {"path": "/Lotus/Weapons/Tenno/Rifle/BratonPrime", "nameEn": "Braton Prime"},
            {"path": "/Lotus/Weapons/Tenno/Rifle/DuplicateBraton", "nameEn": "Duplicate Braton"},
        ]}),
        encoding="utf-8",
    )

    # 3. Protected riven transition + quantizable enemy icon
    grad = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (64, 1))
    omega_path = dest / "frontend/assets/riven/omega-transition.png"
    Image.fromarray(np.dstack([grad, grad, grad, np.full_like(grad, 255)]), "RGBA").save(omega_path)
    omega_before = omega_path.read_bytes()

    enemy_png = dest / "frontend/assets/enemies/art/Lotus/Interface/Lancer.png"
    # Rich gradient + flat regions > 4 KiB that quantizes cleanly to < 88%
    y, x = np.mgrid[0:256, 0:256]
    e_rgba = np.dstack([
        ((x * 3 + y) % 256).astype(np.uint8),
        ((x + y * 2) % 256).astype(np.uint8),
        ((x ^ y) % 256).astype(np.uint8),
        np.where(x > 40, 255, 0).astype(np.uint8),
    ])
    Image.fromarray(e_rgba, "RGBA").save(enemy_png, compress_level=1)

    # 4. Arena fixture
    scene_gz = gzip.compress(json.dumps({
        "schema": "arena-scene/v1",
        "metadata": {},
        "nav": {"nodePositions": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], "nativePortals": [], "vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], "triangles": [[0, 1, 2]]},
        "collision": {"vertices": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], "triangles": [[0, 1, 2]]},
        "spawns": [],
        "start": {"face": 0, "position": [0.0, 0.0, 0.0]},
    }).encode("utf-8"))
    nav_gz = gzip.compress(json.dumps({"schema": 1, "policy": {}, "links": []}).encode("utf-8"))
    vm_gz = gzip.compress(json.dumps({
        "schema": "arena-visual-map/v1",
        "metadata": {},
        "materials": [],
        "instances": [],
        "meshes": [{"id": 0, "positions": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 9.0, 9.0, 9.0], "indices": [0, 1, 2], "groups": []}],
    }).encode("utf-8"))
    (dest / "data/arena/test-map.scene.json.gz").write_bytes(scene_gz)
    (dest / "data/arena/test-map.navigation.json.gz").write_bytes(nav_gz)
    (dest / "data/arena/test-map.visual-map.json.gz").write_bytes(vm_gz)
    (dest / "data/arena/catalog.json").write_text(json.dumps({
        "schema": "arena-catalog/v1",
        "defaultMap": "test-map",
        "maps": {
            "test-map": {
                "id": "test-map",
                "assets": {
                    "scene": {"file": "test-map.scene.json.gz", "sha256": hashlib.sha256(scene_gz).hexdigest(), "compressedBytes": len(scene_gz)},
                    "navigation": {"file": "test-map.navigation.json.gz", "sha256": hashlib.sha256(nav_gz).hexdigest(), "compressedBytes": len(nav_gz)},
                    "visual-map": {"file": "test-map.visual-map.json.gz", "sha256": hashlib.sha256(vm_gz).hexdigest(), "compressedBytes": len(vm_gz)},
                },
            }
        },
    }), encoding="utf-8")

    summary = slim.slim_bundle(dest, root=ROOT, workers=2)
    assert summary["slimProfile"] == "tier2"
    assert summary["cardsConverted"] == 1
    assert summary["stagedBytesSaved"] > 0

    # Card layers converted, originals deleted
    assert not card_stem.with_suffix(".png").exists()
    assert not card_stem.with_suffix(".bg.jpg").exists()
    assert not card_stem.with_suffix(".fg.png").exists()
    assert card_stem.with_suffix(".bg.webp").is_file()
    assert card_stem.with_suffix(".mask.png").is_file()
    mask_im = Image.open(card_stem.with_suffix(".mask.png"))
    assert mask_im.mode == "LA"

    # Dead warframes/mods removed, duplicate/orphan weapons pruned
    assert not (dest / "frontend/assets/warframes/mods").exists()
    kept_weapons = sorted(p.name for p in (dest / "frontend/assets/weapons").glob("*.png"))
    assert kept_weapons == ["BratonPrime.png"]

    # Protected transition untouched
    assert omega_path.read_bytes() == omega_before

    # Bundle profile wired into index.html
    html = (dest / "frontend/index.html").read_text(encoding="utf-8")
    assert html.index('/assets/bundle-profile.js') < html.index('/app.js')
    profile_text = (dest / "frontend/assets/bundle-profile.js").read_text(encoding="utf-8")
    profile_json = json.loads(profile_text.removeprefix("window.__WF_BUNDLE_PROFILE__ = ").rstrip(";\n"))
    assert profile_json["weaponIconMap"]["/Lotus/Weapons/Tenno/Rifle/DuplicateBraton"] == "BratonPrime.png"

    # Arena visual-map converted to binary and served as octet-stream + gzip
    assert not (dest / "data/arena/test-map.visual-map.json.gz").exists()
    assert (dest / "data/arena/test-map.visual-map.bin.gz").is_file()
    body, media, enc = arena_scene.asset_bytes("test-map", "visual-map.json", root=dest)
    assert media == "application/octet-stream"
    assert enc == "gzip"
    decoded_vm = _unpack_wfvm_like_js(gzip.decompress(body))
    assert decoded_vm["meshes"][0]["vertexCount"] == 3
    loaded_scene = arena_scene.load_scene("test-map", root=dest, native=False)
    assert len(loaded_scene.points) == 2
