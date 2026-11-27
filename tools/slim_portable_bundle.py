"""Slim a staged portable bundle in-place (Tier-2 balanced high-quality profile).

Runs exclusively on an ephemeral PyInstaller staging directory ($packageRoot)
after ``data_pipeline.py bundle`` and ``stage_portable_cache.py`` have completed:
  1. Converts 3-copy card art (X.png + X.bg.jpg + X.fg.png in mods/art,
     stances/art, companions/mods) into X.bg.webp (Q85) + X.mask.png (lossless
     8-bit alpha mask), removing unrequested base PNGs.
  2. Removes unreferenced legacy warframes/mods JPEGs and deduplicates/prunes
     frontend/assets/weapons PNGs while emitting an exact weaponIconMap.
  3. Quantizes remaining 32-bit RGBA PNG icons at original resolution into
     8-bit RGBA palette PNGs (preserving .png paths and skipping icons that do
     not shrink meaningfully).
  4. Compacts 3D arena visual-map.json.gz meshes (removing unreferenced/duplicate
     vertices into 4-byte-aligned Float32 + Uint16/Uint32 WFVM v1 binary) and
     encodes large navigation.json.gz polylines with verified bit-exact 2nd-order
     delta compression (WFNV v1), updating staged data/arena/catalog.json.
  5. Emits /assets/bundle-profile.js and wires it before /app.js in staged
     frontend/index.html.

The git source checkout is never modified.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
from typing import Any

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MASK_LO, MASK_HI = 110.0, 200.0
CARD_WEBP_QUALITY = 85
NAV_FIXED_SCALE = 100000
NAV_MIN_CONVERT_BYTES = 256 * 1024
SKIP_QUANTIZE_REL = frozenset({
    "riven/omega-transition.png",
})


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir_bytes_and_count(directory: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for path in directory.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
            count += 1
    return total, count


def weapon_icon_candidates(weapon_path: str, name_en: str = "") -> list[str]:
    internal = str(weapon_path or "").rsplit("/", 1)[-1]
    name = str(name_en or "")
    raw: list[str] = []
    if internal:
        raw.append(internal)
    if name:
        no_space = name.replace(" ", "")
        raw.extend((
            no_space,
            no_space.replace("'", ""),
            no_space.replace("-", ""),
        ))
    seen: set[str] = set()
    out: list[str] = []
    for pattern in raw:
        if not pattern:
            continue
        mk_alt = re.sub(r"^MK1(?=[A-Z])", "Mk1", pattern)
        for variant in (pattern, mk_alt):
            if not variant or variant in seen:
                continue
            seen.add(variant)
            out.append(f"{variant}.png")
    return out


def _convert_card_group(stem_str: str) -> tuple[int, int]:
    """Convert one card art stem (base .png / .bg.jpg / .fg.png) -> .bg.webp + .mask.png."""
    base_png = Path(f"{stem_str}.png")
    bg_jpg = Path(f"{stem_str}.bg.jpg")
    fg_png = Path(f"{stem_str}.fg.png")
    bg_webp = Path(f"{stem_str}.bg.webp")
    mask_png = Path(f"{stem_str}.mask.png")

    before = sum(p.stat().st_size for p in (base_png, bg_jpg, fg_png) if p.is_file())

    if bg_jpg.is_file():
        bg_img = Image.open(bg_jpg).convert("RGB")
    elif base_png.is_file():
        bg_img = Image.open(base_png).convert("RGB")
    elif fg_png.is_file():
        bg_img = Image.open(fg_png).convert("RGB")
    else:
        return 0, 0

    webp_buf = io.BytesIO()
    bg_img.save(webp_buf, format="WEBP", quality=CARD_WEBP_QUALITY, method=4)
    bg_webp.write_bytes(webp_buf.getvalue())

    if fg_png.is_file():
        alpha = Image.open(fg_png).convert("RGBA").getchannel("A")
    elif base_png.is_file():
        raw_alpha = np.asarray(Image.open(base_png).convert("RGBA").getchannel("A"), dtype=np.float32)
        mask = np.clip((raw_alpha - MASK_LO) / (MASK_HI - MASK_LO), 0.0, 1.0)
        mask = mask * mask * (3.0 - 2.0 * mask)
        alpha = Image.fromarray((mask * 255.0).astype(np.uint8), mode="L")
    else:
        alpha = Image.new("L", bg_img.size, 255)

    la_mask = Image.merge("LA", (Image.new("L", alpha.size, 255), alpha))
    mask_buf = io.BytesIO()
    la_mask.save(mask_buf, format="PNG", optimize=True, compress_level=9)
    mask_png.write_bytes(mask_buf.getvalue())

    for old in (base_png, bg_jpg, fg_png):
        if old.is_file():
            old.unlink()

    after = bg_webp.stat().st_size + mask_png.stat().st_size
    return before, after


def _quantize_png_worker(path_str: str) -> tuple[int, int, bool]:
    path = Path(path_str)
    raw = path.read_bytes()
    orig_len = len(raw)
    if orig_len < 4096:
        return orig_len, orig_len, False
    try:
        im = Image.open(io.BytesIO(raw))
        if im.mode not in ("RGBA", "RGB"):
            return orig_len, orig_len, False
        if im.mode == "RGBA":
            arr = np.array(im, dtype=np.uint8)
            zero_alpha = arr[:, :, 3] == 0
            if np.any(zero_alpha):
                arr[zero_alpha, :3] = 0
            quantized = Image.fromarray(arr, mode="RGBA").quantize(
                colors=256,
                method=Image.Quantize.FASTOCTREE,
            )
        else:
            quantized = im.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        out = io.BytesIO()
        quantized.save(out, format="PNG", optimize=True, compress_level=9)
        new_bytes = out.getvalue()
        if len(new_bytes) < orig_len * 0.88:
            path.write_bytes(new_bytes)
            return orig_len, len(new_bytes), True
    except Exception:
        return orig_len, orig_len, False
    return orig_len, orig_len, False


def pack_visual_map_binary(payload: dict[str, Any]) -> bytes:
    """Pack a visual-map JSON dict into 4-byte-aligned lossless Float32 WFVM v1 binary."""
    meshes_out: list[dict[str, Any]] = []
    binary_chunks: list[bytes] = []

    for mesh in payload.get("meshes") or []:
        pos = np.asarray(mesh.get("positions") or [], dtype=np.float32).reshape(-1, 3)
        idx = np.asarray(mesh.get("indices") or [], dtype=np.uint32)
        if idx.size > 0 and len(pos) > 0:
            used, inv = np.unique(idx, return_inverse=True)
            pos = np.ascontiguousarray(pos[used], dtype="<f4")
            idx = inv.astype(np.uint32)
            # Bit-exact Float32 vertex deduplication within each mesh
            void_view = pos.view(np.dtype((np.void, 12))).ravel()
            _, uniq_idx, inv2 = np.unique(void_view, return_index=True, return_inverse=True)
            order = np.argsort(uniq_idx)
            remap = np.empty_like(order)
            remap[order] = np.arange(len(order))
            pos = np.ascontiguousarray(pos[uniq_idx[order]], dtype="<f4")
            idx = remap[inv2[idx]].astype(np.uint32)
        else:
            pos = np.zeros((0, 3), dtype="<f4")
            idx = np.zeros((0,), dtype=np.uint32)

        v_count = int(len(pos))
        i_count = int(idx.size)
        i_bits = 16 if v_count <= 65535 else 32

        meta = {k: v for k, v in mesh.items() if k not in ("positions", "indices")}
        meta["vertexCount"] = v_count
        meta["indexCount"] = i_count
        meta["indexBits"] = i_bits
        meshes_out.append(meta)

        binary_chunks.append(pos.tobytes())
        if i_bits == 16:
            idx_bytes = idx.astype("<u2").tobytes()
            binary_chunks.append(idx_bytes)
            rem = len(idx_bytes) % 4
            if rem:
                binary_chunks.append(b"\x00" * (4 - rem))
        else:
            binary_chunks.append(idx.astype("<u4").tobytes())

    header_obj = {k: v for k, v in payload.items() if k != "meshes"}
    header_obj["meshes"] = meshes_out
    header_bytes = json.dumps(header_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    pad_len = ((12 + len(header_bytes) + 3) & ~3) - (12 + len(header_bytes))

    out = bytearray()
    out.extend(b"WFVM")
    out.extend(struct.pack("<II", 1, len(header_bytes)))
    out.extend(header_bytes)
    if pad_len:
        out.extend(b"\x00" * pad_len)
    for chunk in binary_chunks:
        out.extend(chunk)
    return bytes(out)


def pack_navigation_binary(payload: dict[str, Any], *, scale: int = NAV_FIXED_SCALE) -> bytes | None:
    """Pack navigation JSON dict into bit-exact 2nd-order delta WFNV v1 binary.

    Returns None if any coordinate is not bit-exact under ``q / float(scale)``.
    """
    scale_f = float(scale)
    kinds: list[str] = []
    kind_to_idx: dict[str, int] = {}
    link_meta: list[list[Any]] = []
    stream = bytearray()
    pack_hdr = struct.Struct("<HB").pack
    pack_3i = struct.Struct("<3i").pack

    for link in payload.get("links") or []:
        pts = link.get("points") or []
        n_pts = len(pts)
        if n_pts > 65535:
            return None
        q_pts: list[tuple[int, int, int]] = []
        for pt in pts:
            qx = int(round(pt[0] * scale_f))
            qy = int(round(pt[1] * scale_f))
            qz = int(round(pt[2] * scale_f))
            if [qx / scale_f, qy / scale_f, qz / scale_f] != pt:
                return None
            q_pts.append((qx, qy, qz))

        kind = str(link["kind"])
        if kind not in kind_to_idx:
            kind_to_idx[kind] = len(kinds)
            kinds.append(kind)

        d2_flat: list[int] = []
        max_abs = 0
        if n_pts >= 3:
            for idx in range(2, n_pts):
                p2 = q_pts[idx]
                p1 = q_pts[idx - 1]
                p0 = q_pts[idx - 2]
                dx2 = p2[0] - 2 * p1[0] + p0[0]
                dy2 = p2[1] - 2 * p1[1] + p0[1]
                dz2 = p2[2] - 2 * p1[2] + p0[2]
                d2_flat.extend((dx2, dy2, dz2))
                a = max(abs(dx2), abs(dy2), abs(dz2))
                if a > max_abs:
                    max_abs = a

        if max_abs <= 127:
            mode = 1
        elif max_abs <= 32767:
            mode = 2
        else:
            mode = 3

        stream.extend(pack_hdr(n_pts, mode))
        if n_pts >= 1:
            stream.extend(pack_3i(*q_pts[0]))
        if n_pts >= 2:
            stream.extend(pack_3i(
                q_pts[1][0] - q_pts[0][0],
                q_pts[1][1] - q_pts[0][1],
                q_pts[1][2] - q_pts[0][2],
            ))
            if d2_flat:
                rem3 = len(d2_flat)
                fmt = f"<{rem3}b" if mode == 1 else (f"<{rem3}h" if mode == 2 else f"<{rem3}i")
                stream.extend(struct.pack(fmt, *d2_flat))

        extra = {
            k: v
            for k, v in link.items()
            if k not in ("from", "to", "kind", "points", "seconds", "enemy", "enemySeconds", "source")
        }
        flags = (
            (1 if link.get("enemy") else 0)
            | (2 if "enemy" in link else 0)
            | (4 if "enemySeconds" in link else 0)
            | (8 if "source" in link else 0)
        )
        link_meta.append([
            link["from"],
            link["to"],
            kind_to_idx[kind],
            link["seconds"],
            flags,
            link.get("enemySeconds"),
            link.get("source"),
            extra if extra else None,
        ])

    header_obj = {k: v for k, v in payload.items() if k != "links"}
    header_obj["kinds"] = kinds
    header_obj["linkMeta"] = link_meta
    header_bytes = json.dumps(header_obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    out = bytearray()
    out.extend(b"WFNV")
    out.extend(struct.pack("<III", 1, scale, len(header_bytes)))
    out.extend(header_bytes)
    out.extend(stream)
    return bytes(out)


def _compact_arena_map_worker(args: tuple[str, str, dict[str, Any]]) -> tuple[str, dict[str, dict[str, Any]], int, int]:
    arena_dir_str, map_id, entry = args
    arena_dir = Path(arena_dir_str)
    updates: dict[str, dict[str, Any]] = {}
    before = 0
    after = 0

    vm_info = (entry.get("assets") or {}).get("visual-map")
    if isinstance(vm_info, dict) and str(vm_info.get("file", "")).endswith(".json.gz"):
        vm_path = arena_dir / vm_info["file"]
        if vm_path.is_file():
            raw_gz = vm_path.read_bytes()
            before += len(raw_gz)
            vm_payload = json.loads(gzip.decompress(raw_gz))
            packed = pack_visual_map_binary(vm_payload)
            comp_gz = gzip.compress(packed, compresslevel=9)
            bin_name = vm_info["file"][: -len(".json.gz")] + ".bin.gz"
            (arena_dir / bin_name).write_bytes(comp_gz)
            vm_path.unlink()
            after += len(comp_gz)
            updates["visual-map"] = {
                **vm_info,
                "file": bin_name,
                "sha256": _sha256_bytes(comp_gz),
                "compressedBytes": len(comp_gz),
            }

    nav_info = (entry.get("assets") or {}).get("navigation")
    if isinstance(nav_info, dict) and str(nav_info.get("file", "")).endswith(".json.gz"):
        nav_path = arena_dir / nav_info["file"]
        if nav_path.is_file() and nav_path.stat().st_size >= NAV_MIN_CONVERT_BYTES:
            if str(arena_dir.parents[1]) not in sys.path:
                sys.path.insert(0, str(arena_dir.parents[1]))
            if str(ROOT / "vendor") not in sys.path:
                sys.path.insert(0, str(ROOT / "vendor"))
            from wfarsenal.arena_scene import _unpack_navigation_bin

            raw_gz = nav_path.read_bytes()
            nav_payload = json.loads(gzip.decompress(raw_gz))
            packed = pack_navigation_binary(nav_payload)
            if packed is not None and _unpack_navigation_bin(packed) == nav_payload:
                comp_gz = gzip.compress(packed, compresslevel=9)
                if len(comp_gz) < len(raw_gz) * 0.85:
                    before += len(raw_gz)
                    bin_name = nav_info["file"][: -len(".json.gz")] + ".bin.gz"
                    (arena_dir / bin_name).write_bytes(comp_gz)
                    nav_path.unlink()
                    after += len(comp_gz)
                    updates["navigation"] = {
                        **nav_info,
                        "file": bin_name,
                        "sha256": _sha256_bytes(comp_gz),
                        "compressedBytes": len(comp_gz),
                    }

    return map_id, updates, before, after


def _collect_weapon_records(destination: Path, build_label: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path_val: Any, name_en_val: Any = "") -> None:
        p_str = str(path_val or "").strip()
        if not p_str or p_str in seen:
            return
        seen.add(p_str)
        records.append((p_str, str(name_en_val or "").strip()))

    export_dir = destination / "data" / "export" / build_label
    weapons_path = export_dir / "weapons.json"
    if weapons_path.is_file():
        payload = json.loads(weapons_path.read_text(encoding="utf-8-sig"))
        for row in payload.get("data", payload) if isinstance(payload, dict) else payload:
            if isinstance(row, dict):
                add(row.get("path"), row.get("nameEn"))

    exalted_path = destination / "data" / "exalted_weapons.json"
    if exalted_path.is_file():
        payload = json.loads(exalted_path.read_text(encoding="utf-8-sig"))
        rows = payload.get("data", payload.get("weapons", payload)) if isinstance(payload, dict) else payload
        if isinstance(rows, dict):
            rows = list(rows.values())
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    add(row.get("path"), row.get("nameEn"))

    comp_path = destination / "data" / "mechanics" / "companions-catalog.json"
    if comp_path.is_file():
        payload = json.loads(comp_path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            for key in ("weapons", "companions"):
                seq = payload.get(key)
                if isinstance(seq, dict):
                    seq = list(seq.values())
                if isinstance(seq, list):
                    for row in seq:
                        if isinstance(row, dict):
                            add(row.get("path"), row.get("nameEn"))

    for modular_name, group_keys in (
        ("kitguns.json", ("barrels", "clips", "handles")),
        ("zaws.json", ("strikes", "grips", "links")),
    ):
        m_path = export_dir / modular_name
        if m_path.is_file():
            payload = json.loads(m_path.read_text(encoding="utf-8-sig"))
            if isinstance(payload, dict):
                for gk in group_keys:
                    seq = payload.get(gk)
                    if isinstance(seq, dict):
                        seq = list(seq.values())
                    if isinstance(seq, list):
                        for row in seq:
                            if isinstance(row, dict):
                                add(row.get("path"), row.get("nameEn"))

    return records


def _slim_weapons_and_dead_dirs(destination: Path, build_label: str) -> dict[str, str]:
    assets_root = destination / "frontend" / "assets"
    legacy_wf_mods = assets_root / "warframes" / "mods"
    if legacy_wf_mods.is_dir():
        shutil.rmtree(legacy_wf_mods)

    weapons_dir = assets_root / "weapons"
    if not weapons_dir.is_dir():
        return {}

    # Scan literal /assets/weapons/<file>.png references in JSON/code so they never 404.
    pinned_files: set[str] = set()
    literal_re = re.compile(r"/assets/weapons/([A-Za-z0-9_.\-]+\.png)")
    for scan_file in destination.rglob("*"):
        if not scan_file.is_file() or scan_file.suffix.lower() not in (".json", ".js", ".mjs", ".html", ".css", ".py"):
            continue
        try:
            text = scan_file.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in literal_re.findall(text):
            if (weapons_dir / match).is_file():
                pinned_files.add(match)

    raw_map: dict[str, str] = {}
    for w_path, w_name_en in _collect_weapon_records(destination, build_label):
        matched = ""
        for cand in weapon_icon_candidates(w_path, w_name_en):
            if (weapons_dir / cand).is_file():
                matched = cand
                break
        raw_map[w_path] = matched

    needed_files = (set(raw_map.values()) - {""}) | pinned_files
    by_hash: dict[str, list[str]] = {}
    for fname in sorted(needed_files):
        fpath = weapons_dir / fname
        if fpath.is_file():
            by_hash.setdefault(_sha256_bytes(fpath.read_bytes()), []).append(fname)

    canonical_remap: dict[str, str] = {}
    keep_files: set[str] = set(pinned_files)
    for group in by_hash.values():
        pinned_in_group = sorted(f for f in group if f in pinned_files)
        canonical = pinned_in_group[0] if pinned_in_group else group[0]
        keep_files.add(canonical)
        for fname in group:
            canonical_remap[fname] = canonical

    weapon_icon_map = {
        w_path: (canonical_remap.get(fname, fname) if fname else "")
        for w_path, fname in sorted(raw_map.items())
    }

    for png in list(weapons_dir.glob("*.png")):
        if png.name not in keep_files:
            png.unlink()

    return weapon_icon_map


def slim_bundle(destination: Path, *, root: Path = ROOT, workers: int | None = None) -> dict[str, Any]:
    root, destination = root.resolve(), destination.resolve()
    if root == destination or not (destination / "data" / "source-lock.json").is_file():
        raise ValueError("destination must be a separately staged runtime with data/source-lock.json")

    max_workers = max(1, min(int(workers or (os.cpu_count() or 4)), 12))
    bytes_before, files_before = _dir_bytes_and_count(destination)

    lock = json.loads((destination / "data" / "source-lock.json").read_text(encoding="utf-8-sig"))
    build_label = str(lock["activeBuild"])

    # 1. Prune dead warframes/mods and deduplicate/prune weapon icons
    weapon_icon_map = _slim_weapons_and_dead_dirs(destination, build_label)

    # 2. Convert 3-copy card art -> .bg.webp + .mask.png
    assets_root = destination / "frontend" / "assets"
    card_dirs = (
        assets_root / "mods" / "art",
        assets_root / "stances" / "art",
        assets_root / "companions" / "mods",
    )
    card_stems: set[str] = set()
    for card_dir in card_dirs:
        if not card_dir.is_dir():
            continue
        for fpath in card_dir.rglob("*"):
            if not fpath.is_file():
                continue
            name = fpath.name
            if name.endswith(".bg.jpg"):
                card_stems.add(str(fpath)[: -len(".bg.jpg")])
            elif name.endswith(".fg.png"):
                card_stems.add(str(fpath)[: -len(".fg.png")])
            elif name.endswith(".png") and not name.endswith(".mask.png"):
                card_stems.add(str(fpath)[: -len(".png")])

    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        card_results = list(pool.map(_convert_card_group, sorted(card_stems), chunksize=16))

        # 3. Quantize remaining 32-bit RGBA PNG icons (original resolution, .png preserved)
        png_targets: list[str] = []
        for png_path in sorted(assets_root.rglob("*.png")):
            if png_path.name.endswith(".mask.png"):
                continue
            rel_posix = png_path.relative_to(assets_root).as_posix()
            if rel_posix in SKIP_QUANTIZE_REL:
                continue
            png_targets.append(str(png_path))
        quant_results = list(pool.map(_quantize_png_worker, png_targets, chunksize=16))

        # 4. Compact 3D arena visual-map.json.gz and large lossless navigation.json.gz
        arena_dir = destination / "data" / "arena"
        arena_catalog_path = arena_dir / "catalog.json"
        arena_saved = 0
        arena_maps_compacted = 0
        if arena_catalog_path.is_file():
            arena_catalog = json.loads(arena_catalog_path.read_text(encoding="utf-8"))
            map_tasks = [
                (str(arena_dir), map_id, entry)
                for map_id, entry in sorted((arena_catalog.get("maps") or {}).items())
                if isinstance(entry, dict)
            ]
            for map_id, updates, a_before, a_after in pool.map(_compact_arena_map_worker, map_tasks, chunksize=1):
                if updates:
                    arena_catalog["maps"][map_id]["assets"].update(updates)
                    arena_saved += (a_before - a_after)
                    arena_maps_compacted += 1
            arena_catalog_path.write_text(
                json.dumps(arena_catalog, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )

    # 5. Write /assets/bundle-profile.js and wire before /app.js in frontend/index.html
    bundle_profile = {
        "version": 1,
        "profile": "tier2",
        "cardMask": True,
        "cardBgExt": ".bg.webp",
        "weaponIconMap": weapon_icon_map,
    }
    profile_js = (
        "window.__WF_BUNDLE_PROFILE__ = "
        + json.dumps(bundle_profile, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
    )
    (assets_root / "bundle-profile.js").write_text(profile_js, encoding="utf-8", newline="\n")

    index_html_path = destination / "frontend" / "index.html"
    index_html = index_html_path.read_text(encoding="utf-8")
    script_tag = '<script src="/assets/bundle-profile.js" defer></script>\n'
    if "/assets/bundle-profile.js" not in index_html:
        marker = '<script src="/app.js'
        if marker not in index_html:
            raise RuntimeError("frontend/index.html missing /app.js script tag")
        index_html = index_html.replace(marker, script_tag + marker, 1)
        index_html_path.write_text(index_html, encoding="utf-8", newline="\n")

    bytes_after, files_after = _dir_bytes_and_count(destination)
    summary = {
        "slimProfile": "tier2",
        "cardsConverted": len(card_results),
        "cardBytesSaved": sum(b - a for b, a in card_results),
        "iconsQuantized": sum(1 for _, _, changed in quant_results if changed),
        "iconBytesSaved": sum(b - a for b, a, _ in quant_results),
        "arenaMapsCompacted": arena_maps_compacted,
        "arenaBytesSaved": arena_saved,
        "stagedBytesBefore": bytes_before,
        "stagedBytesAfter": bytes_after,
        "stagedBytesSaved": bytes_before - bytes_after,
        "stagedFilesBefore": files_before,
        "stagedFilesAfter": files_after,
    }

    runtime_meta_path = destination / "data" / "portable-runtime.json"
    if runtime_meta_path.is_file():
        runtime_meta = json.loads(runtime_meta_path.read_text(encoding="utf-8"))
        runtime_meta.update(summary)
        runtime_meta_path.write_text(json.dumps(runtime_meta, indent=2) + "\n", encoding="utf-8")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args()
    summary = slim_bundle(args.destination, root=args.root, workers=args.workers)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
