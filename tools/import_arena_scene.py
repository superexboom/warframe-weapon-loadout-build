"""Import the bounded audited local arena artifacts, never a complete game cache.

No node/numpy/three dependency. Retains original input hashes and only admits
explicit static wall triangles that do not block existing native body portals.
"""

from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vendor"))
from wfarsenal.arena_scene import TriangleBVH, _cross, _sub, _dot

PARSER_VERSION = "portable-arena-import-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def transform(p, instance):
    p = tuple(x * instance["scale"] for x in p)
    q = instance["quaternion"]
    a = _cross(q[:3], p)
    b = _cross(q[:3], a)
    return tuple(
        round(p[i] + 2 * (q[3] * a[i] + b[i]) + instance["position"][i], 5)
        for i in range(3)
    )


def add_static_walls(scene, visual):
    # First qualified batch: regular structural wall panels only. No pillars,
    # props, doors, roofs or guessed bounding boxes. Use exact source triangles.
    selected = []
    for inst in visual["instances"]:
        mesh = visual["meshes"][inst["meshId"]]
        path = mesh["path"]
        if inst.get("physicsBehavior") != "/EE/Types/Physics/Static":
            continue
        if re.search(
            r"(?:CSWallReg|CrpWallBtm|CrpTrenchSPWallStraight)", path
        ) and not re.search(r"Light|Trim|Decal|Banner|DoorStatic", path):
            selected.append((inst, mesh))
    candidate_vertices, candidate_triangles, sources, dedup = [], [], [], {}
    for inst, mesh in selected:
        pos = mesh["positions"]
        points = [transform(pos[k : k + 3], inst) for k in range(0, len(pos), 3)]
        for k in range(0, len(mesh["indices"]), 3):
            t = [points[n] for n in mesh["indices"][k : k + 3]]
            normal = _cross(_sub(t[1], t[0]), _sub(t[2], t[0]))
            area2 = math.sqrt(_dot(normal, normal))
            if area2 < 0.1 or abs(normal[1]) > area2 * 0.25:
                continue
            # Exact source side triangles only; sloped/floor/tiny decorative faces excluded.
            ids = []
            for p in t:
                if p not in dedup:
                    dedup[p] = len(candidate_vertices)
                    candidate_vertices.append(p)
                ids.append(dedup[p])
            candidate_triangles.append(ids)
            sources.append(
                {
                    "type": "qualified-static-visual-wall",
                    "entityId": inst["entityId"],
                    "mesh": mesh["path"],
                    "sourceTriangle": k // 3,
                }
            )
    tree = TriangleBVH(candidate_vertices, candidate_triangles, native=False)
    veto = set()
    # Veto each candidate triangle that blocks an original native route. Recast
    # past the first hit, so overlapping wall layers cannot hide blocked faces.
    nodes = scene["nav"]["nodePositions"]
    casts = 0
    for portal in scene["nav"]["nativePortals"]:
        pts = [nodes[portal["fromFace"]], portal["portal"], nodes[portal["toFace"]]]
        for a, b in zip(pts, pts[1:]):
            for height in (0.5, 1.0, 1.65):
                origin = (a[0], a[1] + height, a[2])
                target = (b[0], b[1] + height, b[2])
                delta = _sub(target, origin)
                length = math.sqrt(_dot(delta, delta))
                if length <= 1e-6:
                    continue
                lower = 1e-4
                while lower < length - 1e-4:
                    casts += 1
                    hit = tree.raycast(origin, delta, length - 1e-4, min_distance=lower)
                    if not hit:
                        break
                    veto.add(hit.triangle)
                    lower = hit.distance + 1e-4
    collision = scene["collision"]
    base_count = len(collision["triangles"])
    base_vertices = len(collision["vertices"])
    collision["vertices"].extend(candidate_vertices)
    collision["triangleSources"] = [
        {"type": "base-csg-or-native-nav-floor", "triangle": k}
        for k in range(base_count)
    ]
    for k, t in enumerate(candidate_triangles):
        if k in veto:
            continue
        collision["triangles"].append([v + base_vertices for v in t])
        collision["triangleSources"].append(sources[k])
    result = {
        "policy": "static regular wall panels, exact near-vertical source triangles area>=0.05; native body-portal blocking triangles vetoed",
        "selectedInstances": len(selected),
        "candidateTriangles": len(candidate_triangles),
        "vetoedTriangles": len(veto),
        "admittedTriangles": len(candidate_triangles) - len(veto),
        "nativeRouteAuditCasts": casts,
        "baseTriangles": base_count,
        "totalTriangles": len(collision["triangles"]),
        "qualification": "conservative qualified visual proxy; not native BSP; no collision from decorative props; source wall triangles conflicting with native paths intentionally omitted",
    }
    collision["staticWallAdmission"] = result
    scene["metadata"]["staticWallAdmission"] = result
    return result


def import_scene(
    source: Path, output: Path, map_id="corpus-ship-defense", *, walls=True
):
    scene_path, nav_path = source / "scene.json", source / "navigation.json"
    scene = json.loads(scene_path.read_text(encoding="utf-8"))
    navigation = json.loads(nav_path.read_text(encoding="utf-8"))
    if navigation.get("sourceSceneSha256") != sha(scene_path):
        raise ValueError("navigation sourceSceneSha256 does not match scene.json")
    inputs = [
        scene_path,
        nav_path,
        source / "visual-map.json",
        source / "visual-map-collision-candidates.json",
    ]
    visual = json.loads(inputs[2].read_text(encoding="utf-8"))
    wall_report = add_static_walls(scene, visual) if walls else {"admittedTriangles": 0}
    output.mkdir(parents=True, exist_ok=True)
    assets = {}
    for name, value in (
        ("scene", scene),
        ("navigation", navigation),
        ("visual-map", visual),
        (
            "visual-map-collision-candidates",
            json.loads(inputs[3].read_text(encoding="utf-8")),
        ),
    ):
        data = compact(value)
        path = output / f"{map_id}.{name}.json.gz"
        path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
        assets[name] = {
            "file": path.name,
            "sha256": sha(path),
            "jsonSha256": hashlib.sha256(data).hexdigest(),
            "compressedBytes": path.stat().st_size,
            "jsonBytes": len(data),
        }
    entry = {
        "id": map_id,
        "name": scene.get("metadata", {}).get(
            "mapName", "Corpus Ship Defense — extracted tile"
        ),
        "sourceTile": scene.get("metadata", {}).get(
            "sourceTile", "/Lotus/Levels/CorpusShipRemastered/ObjDefense01"
        ),
        "gameVersion": scene.get("metadata", {}).get("gameVersion", "2026.10.28.09.54"),
        "parserVersion": PARSER_VERSION,
        "sources": [
            {"file": path.name, "sha256": sha(path), "bytes": path.stat().st_size}
            for path in inputs
        ],
        "assets": assets,
        "staticWallAdmission": wall_report,
        "qualification": [
            "authored tile template, not mission runtime instance",
            "visual/CSG/NAV collision proxy, not authoritative BSP",
            "explicit custom movement policy; ordinary enemies use only admitted enemy links",
            "source resource provenance is retained in scene metadata and per-mesh source SHA256",
        ],
    }
    entry.update(_map_labels(entry["sourceTile"]))
    provenance = source.parents[1] / "evidence/geometry/provenance.json"
    if provenance.exists():
        original = json.loads(provenance.read_text(encoding="utf-8"))
        entry["originalInputs"] = [
            {
                "file": Path(row["path"]).name,
                "sha256": row["sha256"],
                "bytes": row["length"],
            }
            for row in original.get("files", [])
        ]
        entry["sourceRepositoryTrees"] = original.get("sourceTrees", [])
        entry["extractorVersion"] = original.get("extractorVersion")
    catalog_path = output / "catalog.json"
    catalog = (
        json.loads(catalog_path.read_text(encoding="utf-8"))
        if catalog_path.exists()
        else {"schema": 1, "defaultMap": map_id, "maps": {}}
    )
    if scene.get("metadata", {}).get("sharedNodeAliases"):
        entry["sharedNodeAliases"] = scene["metadata"]["sharedNodeAliases"]
    catalog["maps"][map_id] = entry
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return entry


class _TileReader:
    def __init__(self, data, offset=0):
        self.data, self.pos = data, offset

    def u32(self):
        import struct

        value = struct.unpack_from("<I", self.data, self.pos)[0]
        self.pos += 4
        return value

    def string(self):
        length = self.u32()
        if length > 1_000_000 or self.pos + length > len(self.data):
            raise ValueError("invalid tile string")
        value = self.data[self.pos : self.pos + length].decode("utf-8")
        self.pos += length
        return value

    def strings(self):
        return [self.string() for _ in range(self.u32())]


_MAP_LABELS = {
    "ObjDefense01": ("Corpus飞船防御模板", "Corpus", "飞船防御／拦截共享模板"),
    "GrnDefenceTwo": ("Grineer战舰防御模板", "Grineer", "战舰防御／拦截共享模板"),
    "CrpOutpostDefenseOne": ("Corpus前哨站防御模板一", "Corpus", "前哨站防御变体一"),
    "CrpOutpostDefenseTwo": ("Corpus前哨站防御模板二", "Corpus", "前哨站防御变体二"),
    "ShipyardsDefence": ("Grineer船坞防御模板", "Grineer", "船坞防御模板"),
    "GasDefense": ("Corpus燃气城防御模板", "Corpus", "燃气城防御模板"),
    "GrineerOceanDefense02": (
        "Grineer海底实验室防御模板二",
        "Grineer",
        "海底实验室防御变体二",
    ),
    "GrineerOceanDefense03": (
        "Grineer海底实验室防御模板三",
        "Grineer",
        "海底实验室防御变体三",
    ),
}


def _map_labels(tile):
    key = tile.rsplit("/", 1)[-1]
    label, faction, template = _MAP_LABELS.get(key, (key, "unknown", key))
    return {
        "nameZh": label,
        "architectureFaction": faction,
        "templateLabelZh": template,
        "factionQualification": "architecture faction only; mission enemy faction is selected independently",
    }


def _closest_triangle(p, a, b, c):
    ab, ac, ap = _sub(b, a), _sub(c, a), _sub(p, a)
    d1, d2 = _dot(ab, ap), _dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a
    bp = _sub(p, b)
    d3, d4 = _dot(ab, bp), _dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        return tuple(a[i] + ab[i] * d1 / (d1 - d3) for i in range(3))
    cp = _sub(p, c)
    d5, d6 = _dot(ab, cp), _dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        return tuple(a[i] + ac[i] * d2 / (d2 - d6) for i in range(3))
    va = d3 * d6 - d5 * d4
    if va <= 0 and d4 - d3 >= 0 and d5 - d6 >= 0:
        return tuple(
            b[i] + (c[i] - b[i]) * (d4 - d3) / (d4 - d3 + d5 - d6) for i in range(3)
        )
    den = va + vb + vc
    if abs(den) < 1e-14:
        return a
    return tuple(a[i] + ab[i] * vb / den + ac[i] * vc / den for i in range(3))


def _triangulate_nav_polygon(vertices, edges, source_face):
    """Recover one closed source ring and deterministic validated ear clipping.

    No angle/nearest-point ordering: only the native edge incidence determines
    the ring. A small 0.002 source-unit plane error permits resource float noise.
    """
    from collections import defaultdict

    graph = defaultdict(list)
    for a, b in edges:
        if a == b or b in graph[a]:
            raise ValueError(f"NAV polygon {source_face}: repeated/degenerate edge")
        graph[a].append(b)
        graph[b].append(a)
    if len(graph) < 3 or any(len(v) != 2 for v in graph.values()):
        raise ValueError(f"NAV polygon {source_face}: not a degree-two closed ring")
    ring, previous, current = [min(graph)], None, min(graph)
    while True:
        candidates = sorted(v for v in graph[current] if v != previous)
        nxt = candidates[0]
        if nxt == ring[0]:
            break
        if nxt in ring:
            raise ValueError(f"NAV polygon {source_face}: multiple/self-joined rings")
        ring.append(nxt)
        previous, current = current, nxt
    if len(ring) != len(graph) or len(edges) != len(ring):
        raise ValueError(f"NAV polygon {source_face}: disconnected ring")
    points = [vertices[k] for k in ring]
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(points, points[1:] + points[:1]):
        normal[0] += (a[1] - b[1]) * (a[2] + b[2])
        normal[1] += (a[2] - b[2]) * (a[0] + b[0])
        normal[2] += (a[0] - b[0]) * (a[1] + b[1])
    norm = math.sqrt(_dot(normal, normal))
    if norm < 1e-9:
        raise ValueError(f"NAV polygon {source_face}: zero area")
    normal = [v / norm for v in normal]
    plane_error = max(abs(_dot(_sub(p, points[0]), normal)) for p in points)
    if plane_error > 0.002:
        raise ValueError(f"NAV polygon {source_face}: nonplanar error {plane_error}")
    drop = max(range(3), key=lambda i: abs(normal[i]))
    axes = [i for i in range(3) if i != drop]
    coords = {k: (vertices[k][axes[0]], vertices[k][axes[1]]) for k in ring}

    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    signed2 = sum(
        coords[a][0] * coords[b][1] - coords[b][0] * coords[a][1]
        for a, b in zip(ring, ring[1:] + ring[:1])
    )
    sign = 1 if signed2 > 0 else -1
    if abs(signed2) < 1e-9:
        raise ValueError(f"NAV polygon {source_face}: zero projected area")
    # Reject non-adjacent crossing boundary edges before ear clipping.
    for i in range(len(ring)):
        a, b = coords[ring[i]], coords[ring[(i + 1) % len(ring)]]
        for j in range(i + 1, len(ring)):
            if j == i + 1 or (i == 0 and j == len(ring) - 1):
                continue
            c, d = coords[ring[j]], coords[ring[(j + 1) % len(ring)]]
            if (
                orient(a, b, c) * orient(a, b, d) < -1e-16
                and orient(c, d, a) * orient(c, d, b) < -1e-16
            ):
                raise ValueError(f"NAV polygon {source_face}: crossing boundary")

    def positive_normal(triangle):
        a, b, c = (vertices[k] for k in triangle)
        return _dot(_cross(_sub(b, a), _sub(c, a)), normal) > 1e-10

    def clip(remaining):
        if len(remaining) == 3:
            tri = list(remaining)
            return (
                [tri]
                if orient(*(coords[k] for k in tri)) * sign > 1e-10
                and positive_normal(tri)
                else None
            )
        ear_order = sorted(
            range(len(remaining)),
            key=lambda i: -abs(
                orient(
                    coords[remaining[i - 1]],
                    coords[remaining[i]],
                    coords[remaining[(i + 1) % len(remaining)]],
                )
            ),
        )
        for i in ear_order:
            prev, cur, nxt = (
                remaining[i - 1],
                remaining[i],
                remaining[(i + 1) % len(remaining)],
            )
            a, b, c = coords[prev], coords[cur], coords[nxt]
            if orient(a, b, c) * sign <= 1e-10 or not positive_normal([prev, cur, nxt]):
                continue
            if any(
                min(
                    orient(a, b, coords[k]) * sign,
                    orient(b, c, coords[k]) * sign,
                    orient(c, a, coords[k]) * sign,
                )
                >= -1e-10
                for k in remaining
                if k not in (prev, cur, nxt)
            ):
                continue
            rest = clip(remaining[:i] + remaining[i + 1 :])
            if rest is not None:
                return [[prev, cur, nxt]] + rest
        return None

    triangles = clip(list(ring))
    if triangles is None:
        raise ValueError(
            f"NAV polygon {source_face}: no fully validated ear triangulation"
        )
    areas = [orient(*(coords[k] for k in t)) for t in triangles]
    if any(a * sign <= 1e-10 for a in areas) or abs(sum(areas) - signed2) > max(
        1e-6, abs(signed2) * 1e-7
    ):
        raise ValueError(
            f"NAV polygon {source_face}: triangulation orientation/area mismatch"
        )
    for triangle in triangles:
        a, b, c = (vertices[k] for k in triangle)
        triangle_normal = _cross(_sub(b, a), _sub(c, a))
        if _dot(triangle_normal, normal) <= 1e-10:
            raise ValueError(
                f"NAV polygon {source_face}: inconsistent 3D triangle normal"
            )
    from collections import Counter

    actual = Counter(
        tuple(sorted((a, b)))
        for t in triangles
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))
    )
    boundary = {tuple(sorted((a, b))) for a, b in edges}
    if {e for e, n in actual.items() if n == 1} != boundary or any(
        n not in (1, 2) for n in actual.values()
    ):
        raise ValueError(f"NAV polygon {source_face}: triangulation boundary mismatch")
    return ring, triangles, plane_error


def prepare_raw_tile(
    source: Path,
    tile_path: str,
    destination: Path,
    *,
    game_version="2026.10.28.09.54",
    node_evidence: Path | None = None,
    proc_file: Path | None = None,
):
    """Generic NAV77/LEVEL212 + static GLB importer for one audited tile.

    No full-cache extraction or inferred random level assembly. All level mesh
    instance transforms are explicit; only exported tile-local meshes assembled.
    Unknown NAV tail and level header tail remain qualified, not guessed.
    """
    import struct
    from collections import Counter, defaultdict, deque

    name = tile_path.rsplit("/", 1)[-1]
    nav_h = next((source / "raw").glob("**/0.nav_H"))
    nav_b = next((source / "raw").glob("**/0.nav_B"))
    h, b = nav_h.read_bytes(), nav_b.read_bytes()
    reader = _TileReader(h, 16)
    refs = reader.strings()
    flags, version, stamp = reader.u32(), reader.u32(), reader.u32()
    if version != 77:
        raise ValueError(f"unsupported NAV version {version}")
    nverts, nedges, nindices = reader.u32(), reader.u32(), reader.u32()
    # This version's header face count and exact min/max offsets are relative
    # to the common resource header (path string length varies per tile).
    payload = reader.pos - 24
    nfaces = struct.unpack_from("<I", h, payload + 32)[0]
    vertices = [list(v) for v in struct.iter_unpack("<3f", b[: nverts * 12])]
    for axis in range(3):
        assert (
            abs(
                min(v[axis] for v in vertices)
                - struct.unpack_from("<f", h, payload + 60 + axis * 4)[0]
            )
            < 1e-5
        )
        assert (
            abs(
                max(v[axis] for v in vertices)
                - struct.unpack_from("<f", h, payload + 76 + axis * 4)[0]
            )
            < 1e-5
        )
    end = nverts * 12 + nedges * 10
    faces, adjacency, portals = defaultdict(list), [], []
    for a, c, f, g, tag in struct.iter_unpack("<5H", b[nverts * 12 : end]):
        assert (
            a < nverts
            and c < nverts
            and f < nfaces
            and (g < nfaces or g == 65535)
            and tag == 65535
        )
        faces[f].append((a, c))
        if g != 65535:
            faces[g].append((a, c))
            adjacency.append([f, g])
            portals.append(
                {
                    "fromFace": f,
                    "toFace": g,
                    "portal": [
                        (vertices[a][i] + vertices[c][i]) * 0.5 for i in range(3)
                    ],
                }
            )
    # Native polygon IDs are retained in fromFaceMap/sourcePolygons. Expanded
    # triangle IDs are the normal runtime graph IDs; split edges never span
    # different original polygons unless the source shared edge says so.
    source_adjacency, source_portals = adjacency, portals
    source_count = nfaces
    polygons, triangles, from_face_map, plane_errors = [], [], [], []
    expanded = {}
    for f in range(source_count):
        ring, split, error = _triangulate_nav_polygon(vertices, faces[f], f)
        polygons.append(ring)
        plane_errors.append(error)
        expanded[f] = list(range(len(triangles), len(triangles) + len(split)))
        triangles.extend(split)
        from_face_map.extend([f] * len(split))
    source_edges = defaultdict(list)
    for original_face, parts in expanded.items():
        for face in parts:
            t = triangles[face]
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                source_edges[(original_face, tuple(sorted((a, b))))].append(face)
    adjacency, portals = [], []

    def connect(a, b, edge, kind):
        adjacency.append([a, b])
        portals.append(
            {
                "fromFace": a,
                "toFace": b,
                "portal": [
                    (vertices[edge[0]][i] + vertices[edge[1]][i]) * 0.5
                    for i in range(3)
                ],
                "sourceType": kind,
            }
        )

    # Shared edge records contain exact source vertex IDs.
    for a, c, f, g, tag in struct.iter_unpack(
        "<5H", nav_b.read_bytes()[nverts * 12 : end]
    ):
        if g == 65535:
            continue
        edge = tuple(sorted((a, c)))
        one, two = source_edges[(f, edge)], source_edges[(g, edge)]
        if len(one) != 1 or len(two) != 1:
            raise ValueError(
                "native polygon portal did not map to exactly one split triangle per side"
            )
        connect(one[0], two[0], edge, "native-polygon-shared-edge")
    for (original_face, edge), parts in source_edges.items():
        if len(parts) == 2:
            connect(parts[0], parts[1], edge, "validated-source-polygon-internal-split")
    nfaces = len(triangles)
    nodes = [[sum(vertices[k][i] for k in t) / 3 for i in range(3)] for t in triangles]
    graph = defaultdict(set)
    for a, c in adjacency:
        graph[a].add(c)
        graph[c].add(a)
    components, groups = [-1] * nfaces, []
    for f in range(nfaces):
        if components[f] >= 0:
            continue
        group, stack, ci = [], [f], len(groups)
        components[f] = ci
        while stack:
            a = stack.pop()
            group.append(a)
            for c in graph[a]:
                if components[c] < 0:
                    components[c] = ci
                    stack.append(c)
        groups.append(group)
    level_h = next((source / "raw-level").glob(f"**/{name}.level_H"))
    level_b = next((source / "raw-level").glob(f"**/{name}.level_B"))
    lh, lb = level_h.read_bytes(), level_b.read_bytes()
    lr = _TileReader(lh, 16)
    level_refs = lr.strings()
    lf, lv = lr.u32(), lr.u32()
    if lv != 212:
        raise ValueError(f"unsupported LEVEL version {lv}")
    paths, actions, assets = lr.strings(), lr.strings(), lr.strings()
    for _ in range(lr.u32()):
        lr.string()
        lr.string()
        lr.u32()
        lr.u32()
    assert lr.u32() == 0
    count, entities = lr.u32(), []
    for index in range(count):
        typ = lr.string()
        values = struct.unpack_from("<7f", lh, lr.pos)
        lr.pos += 28
        scope, mesh_index, unknown = lr.string(), lr.u32(), lr.u32()
        entities.append(
            {
                "id": index,
                "type": typ,
                "position": values[:3],
                "quaternion": values[3:],
                "scope": scope,
            }
        )
    lens = struct.unpack_from("<" + "I" * count, lb)
    bp = count * 4
    for entity, length in zip(entities, lens):
        entity["attributes"] = lb[bp : bp + length + 1].rstrip(b"\0").decode("utf8")
        bp += length + 1
    assert bp == len(lb)
    mesh_data, materials, material_ids = [], [], {}
    meshes = {}
    for file in sorted((source / "models").glob("**/*.glb")):
        data = file.read_bytes()
        jl = struct.unpack_from("<I", data, 12)[0]
        doc, binary = json.loads(data[20 : 20 + jl]), data[28 + jl :]
        if doc.get("skins") or any(
            any(k in node for k in ("matrix", "translation", "rotation", "scale"))
            for node in doc.get("nodes", [])
        ):
            continue

        def access(index):
            a = doc["accessors"][index]
            view = doc["bufferViews"][a["bufferView"]]
            width = {"SCALAR": 1, "VEC3": 3}[a["type"]]
            code = {5126: "f", 5123: "H", 5125: "I"}[a["componentType"]]
            offset = view.get("byteOffset", 0) + a.get("byteOffset", 0)
            stride = view.get("byteStride", struct.calcsize("<" + code) * width)
            return [
                struct.unpack_from("<" + code * width, binary, offset + i * stride)
                for i in range(a["count"])
            ]

        ps, ids, ranges = [], [], []
        for mesh in doc["meshes"]:
            for prim in mesh["primitives"]:
                points = access(prim["attributes"]["POSITION"])
                indices = [x[0] for x in access(prim["indices"])]
                offset = len(ps) // 3
                for x, y, z in points:
                    ps.extend((round(x, 5), round(y, 5), round(-z, 5)))
                for k in range(0, len(indices), 3):
                    ids.extend(
                        (
                            offset + indices[k],
                            offset + indices[k + 2],
                            offset + indices[k + 1],
                        )
                    )
                mat = doc.get("materials", [{}])[prim.get("material", 0)]
                matpath = mat.get("extras", {}).get(
                    "FullPath", mat.get("name", "unknown")
                )
                if matpath not in material_ids:
                    material_ids[matpath] = len(materials)
                    materials.append(
                        {
                            "id": len(materials),
                            "sourcePath": matpath,
                            "color": "#777565",
                            "qualification": "simplified neutral color; source textures not exported",
                        }
                    )
                ranges.append(
                    {
                        "start": len(ids) - len(indices),
                        "count": len(indices),
                        "materialId": material_ids[matpath],
                    }
                )
        ident = len(mesh_data)
        meshes[file.stem + ".fbx"] = ident
        mesh_data.append(
            {
                "id": ident,
                "path": tile_path + "/" + file.stem + ".fbx",
                "positions": ps,
                "indices": ids,
                "groups": ranges,
                "sha256": sha(file),
                "triangleCount": len(ids) // 3,
            }
        )
    instances, cv, ct, omitted = [], [], [], []
    for entity in entities:
        raw = entity["attributes"]
        match = re.search(r"^Mesh=(.+)$", raw, re.M)
        if not match:
            continue
        reference = match[1]
        filename = reference.rsplit("/", 1)[-1]
        if filename not in meshes or (
            reference.startswith("/") and not reference.startswith(tile_path + "/")
        ):
            continue
        if re.search(r"^(?:Attached|StartHidden)=1$", raw, re.M):
            omitted.append({"entityId": entity["id"], "reason": "attached or hidden"})
            continue
        mid = meshes[filename]
        scale_match = re.search(r"^MeshScale=(.+)$", raw, re.M)
        scale = float(scale_match[1]) if scale_match else 1.0
        inst = {
            "entityId": entity["id"],
            "meshId": mid,
            "position": entity["position"],
            "quaternion": entity["quaternion"],
            "scale": scale,
            "materialOverrides": None,
            "name": entity["scope"] + entity["type"].rsplit("/", 1)[-1],
            "qualification": "exact flattened level XYZ/quaternion, explicit scale or upstream default1",
        }
        instances.append(inst)
        if entity["type"].endswith("/CsgZone"):
            mesh = mesh_data[mid]
            offset = len(cv)
            cv.extend(
                transform(mesh["positions"][i : i + 3], inst)
                for i in range(0, len(mesh["positions"]), 3)
            )
            ct.extend(
                [
                    [offset + k for k in mesh["indices"][i : i + 3]]
                    for i in range(0, len(mesh["indices"]), 3)
                ]
            )
    floor_offset = len(cv)
    cv.extend(vertices)
    ct.extend([[floor_offset + k for k in t] for t in triangles])

    def nearest(p):
        best = (math.inf, -1, None)
        for f, t in enumerate(triangles):
            q = _closest_triangle(p, *(vertices[k] for k in t))
            dist = math.dist(p, q)
            if dist < best[0]:
                best = dist, f, q
        return best

    _, start_face, start_pos = nearest((0.0, 0.0, 0.0))
    component = components[start_face]
    # Bounded ordinary steps between actual face boundaries. Require continuous
    # proxy ground support and body clearance; never nearest-XZ deck shortcuts.
    bvh = TriangleBVH(cv, ct, native=True)
    boundary = []
    incidence = Counter(
        tuple(sorted((a, b)))
        for t in triangles
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))
    )
    for face, t in enumerate(triangles):
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            if incidence[tuple(sorted((a, b)))] == 1:
                midpoint = [(vertices[a][i] + vertices[b][i]) * 0.5 for i in range(3)]
                point = [midpoint[i] * 0.95 + nodes[face][i] * 0.05 for i in range(3)]
                boundary.append((face, point))
    best = {}
    for i, (fa, pa) in enumerate(boundary):
        for fb, pb in boundary[i + 1 :]:
            ca, cb = components[fa], components[fb]
            if (
                ca == cb
                or abs(pa[1] - pb[1]) > 0.65
                or math.hypot(pa[0] - pb[0], pa[2] - pb[2]) > 2.0
            ):
                continue
            key = tuple(sorted((ca, cb)))
            length = math.dist(pa, pb)
            if key not in best or length < best[key][0]:
                best[key] = (length, fa, fb, pa, pb)
    step_links = []
    for length, fa, fb, pa, pb in best.values():
        raw_points = [nodes[fa], pa, pb, nodes[fb]]
        supported, valid = [], True
        for aa, bb in zip(raw_points, raw_points[1:]):
            sample_count = max(2, int(math.dist(aa, bb) / 0.12) + 1)
            for k in range(sample_count):
                ratio = k / sample_count
                foot = tuple(aa[i] * (1 - ratio) + bb[i] * ratio for i in range(3))
                hit = bvh.raycast((foot[0], foot[1] + 0.5, foot[2]), (0, -1, 0), 1.1)
                if not hit:
                    valid = False
                    break
                point = hit.position
                if supported and abs(point[1] - supported[-1][1]) > 0.5:
                    valid = False
                    break
                if supported:
                    last = supported[-1]
                    for dx, dz in ((0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2)):
                        for height in (0.5, 1, 1.65):
                            y = max(point[1], last[1]) + height
                            delta = (point[0] - last[0], 0, point[2] - last[2])
                            dist = math.sqrt(sum(x * x for x in delta))
                            if dist > 1e-5 and bvh.raycast(
                                (last[0] + dx, y, last[2] + dz), delta, dist - 1e-4
                            ):
                                valid = False
                                break
                        if not valid:
                            break
                supported.append(point)
            if not valid:
                break
        if valid:
            supported.append(nodes[fb])
            walklen = sum(math.dist(a, b) for a, b in zip(supported, supported[1:]))
            for u, v, pts in ((fa, fb, supported), (fb, fa, supported[::-1])):
                step_links.append(
                    {
                        "from": u,
                        "to": v,
                        "kind": "step",
                        "points": pts,
                        "seconds": walklen / 6,
                        "enemy": True,
                        "enemySeconds": walklen / 3.6,
                        "source": {
                            "type": "derived-supported-boundary-step",
                            "qualification": "continuous source CSG/NAV proxy support each .12, <=.5 step, body rails .2; not native game bridge",
                        },
                    }
                )
    # Closest-origin landing can be an isolated defense platform. Keep that
    # exact landing, but let player-only bounded arcs leave it. Enemy ground
    # eligibility remains false; no fake ground edges are introduced.
    jump_links = []
    for ca in range(len(groups)):
        for cb in range(ca + 1, len(groups)):
            best_pair = min(
                (
                    (math.dist(nodes[a], nodes[b]), a, b)
                    for a in groups[ca]
                    for b in groups[cb]
                ),
                key=lambda row: row[0],
            )
            length, fa, fb = best_pair
            pa, pb = nodes[fa], nodes[fb]
            if (
                abs(pa[1] - pb[1]) > 8
                or math.hypot(pa[0] - pb[0], pa[2] - pb[2]) > 10
                or length > 12
            ):
                continue
            accepted = None
            for apex in (1.2, 2.5, 4.5):
                pts = [
                    [
                        pa[i] * (1 - t)
                        + pb[i] * t
                        + (4 * apex * t * (1 - t) if i == 1 else 0)
                        for i in range(3)
                    ]
                    for t in [k / 40 for k in range(41)]
                ]
                clear = True
                for aa, bb in zip(pts, pts[1:]):
                    delta = _sub(bb, aa)
                    dist = math.sqrt(_dot(delta, delta))
                    for dx, dz in (
                        (0, 0),
                        (0.22, 0),
                        (-0.22, 0),
                        (0, 0.22),
                        (0, -0.22),
                    ):
                        for height in (0.18, 0.9, 1.65):
                            if bvh.raycast(
                                (aa[0] + dx, aa[1] + height, aa[2] + dz),
                                delta,
                                max(0.0, dist - 1e-4),
                            ):
                                clear = False
                                break
                        if not clear:
                            break
                    if not clear:
                        break
                if clear:
                    accepted = pts
                    break
            if accepted:
                walklen = sum(math.dist(a, b) for a, b in zip(accepted, accepted[1:]))
                for u, v, pts in ((fa, fb, accepted), (fb, fa, accepted[::-1])):
                    jump_links.append(
                        {
                            "from": u,
                            "to": v,
                            "kind": "bullet-jump",
                            "points": pts,
                            "seconds": max(0.3, walklen / 20),
                            "enemy": False,
                            "enemySeconds": None,
                            "source": {
                                "type": "derived-player-only-csg-nav-proxy-arc",
                                "apexAboveLinearBaseline": apex,
                                "qualification": "40 segment continuous body rails .22; player custom trajectory, not native game AI or ordinary enemy jump",
                            },
                        }
                    )
    all_links = step_links + jump_links
    component_graph = defaultdict(set)
    for link in all_links:
        component_a, component_b = components[link["from"]], components[link["to"]]
        component_graph[component_a].add(component_b)
    reachable_components, queue = {component}, [component]
    while queue:
        for c in component_graph[queue.pop()] - reachable_components:
            reachable_components.add(c)
            queue.append(c)
    spawns = []
    for entity in entities:
        if not entity["type"].endswith("/NpcSpawnPoint"):
            continue
        dist, face, pos = nearest(entity["position"])
        match = re.search(r"^Instance=(\d+)$", entity["attributes"], re.M)
        tag = "DefenseAgentSpawn" in entity["attributes"]
        accepted = dist <= 1.5 and components[face] in reachable_components and not tag
        spawns.append(
            {
                "id": entity["id"],
                "name": entity["scope"]
                + "NpcSpawnPoint"
                + (match[1] if match else "?"),
                "position": entity["position"],
                "navPosition": pos,
                "face": face,
                "distanceToNav": dist,
                "accepted": accepted,
                "reason": (
                    "native-connected near-nav authored candidate"
                    if accepted
                    else "outside native start component, distant or friendly defense spawn"
                ),
            }
        )
    source_files = [nav_h, nav_b, level_h, level_b] + ([proc_file] if proc_file else [])
    source_evidence = [
        {"file": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
        for p in source_files
    ]
    aliases = []
    if node_evidence:
        aliases = [
            row
            for row in json.loads(node_evidence.read_text(encoding="utf8"))
            if any(
                (
                    proc_file.name.removesuffix("_H")
                    if proc_file
                    else tile_path.rsplit("/", 1)[-1]
                )
                in link
                for link in row.get("links", [])
            )
        ]
    scene = {
        "schema": "arena-scene-demo/v1",
        "metadata": {
            "sourceTile": tile_path,
            "gameVersion": game_version,
            "mapName": name,
            "parserVersion": PARSER_VERSION + "/raw-nav77-level212-v1",
            "sources": source_evidence,
            "sharedNodeAliases": aliases,
            "qualification": [
                "single authored tile, not full mission instance",
                "alias node evidence is contiguous ordered strings, not current Arbitration roster",
                "native ground portals, bounded supported steps and separately marked player-only arcs; disconnected components retained; ordinary enemies cannot use player arcs",
                "collision is actual CSG visual mesh plus native NAV floor proxy, not authoritative BSP",
                "tile-local baked art meshes use exact level transforms; missing external props remain omitted",
            ],
        },
        "nav": {
            "vertices": vertices,
            "triangles": triangles,
            "nativeAdjacency": adjacency,
            "fromFaceMap": from_face_map,
            "sourcePolygons": polygons,
            "sourcePolygonCount": source_count,
            "polygonTriangulation": {
                "method": "edge-ring-earclip",
                "maxPlaneError": max(plane_errors),
                "planeTolerance": 0.002,
                "areaOrientationAndBoundaryValidated": True,
                "normalConsistencyValidated": True,
            },
            "nodePositions": nodes,
            "nativePortals": portals,
            "componentOfFace": components,
            "componentCount": len(groups),
        },
        "collision": {
            "vertices": cv,
            "triangles": ct,
            "qualification": "source CSG plus NAV floors",
        },
        "spawns": spawns,
        "start": {
            "position": start_pos,
            "face": start_face,
            "component": component,
            "selection": "closest point on all actual NAV triangles to source origin",
        },
        "derivedLinks": [],
        "reachable": {
            "components": sorted(reachable_components),
            "faces": [
                f for f in range(nfaces) if components[f] in reachable_components
            ],
            "acceptedSpawnIds": [p["id"] for p in spawns if p["accepted"]],
            "heightSpan": [
                min(
                    nodes[f][1]
                    for f in range(nfaces)
                    if components[f] in reachable_components
                ),
                max(
                    nodes[f][1]
                    for f in range(nfaces)
                    if components[f] in reachable_components
                ),
            ],
        },
        "diagnostics": {
            "nativeComponents": len(groups),
            "componentSizes": sorted(map(len, groups), reverse=True),
            "navTailBytes": nav_b.stat().st_size - end,
            "levelHeaderTailBytes": len(lh) - lr.pos,
            "levelBodyFullyConsumed": True,
            "entityCount": count,
        },
    }
    scene["metadata"].update(_map_labels(tile_path))
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "scene.json").write_bytes(compact(scene))
    navigation = {
        "schema": 1,
        "sourceSceneSha256": sha(destination / "scene.json"),
        "policy": {
            "playerWalkSpeed": 6,
            "enemySpeed": 3.6,
            "qualification": "native portals, supported ground steps and separate player-only bounded proxy-validated arcs; no guessed native bridge endpoints",
        },
        "links": all_links,
        "stats": {"landmarks": nfaces, "links": len(all_links)},
    }
    (destination / "navigation.json").write_bytes(compact(navigation))
    visual = {
        "schema": "arena-visual-map/v1",
        "metadata": scene["metadata"],
        "meshes": mesh_data,
        "materials": materials,
        "instances": instances,
    }
    (destination / "visual-map.json").write_bytes(compact(visual))
    (destination / "visual-map-collision-candidates.json").write_bytes(
        compact(
            {
                "schema": "arena-visual-collision-candidate/v1",
                "meshSource": "visual-map.json",
                "instances": [],
                "qualification": "no extra art collision admitted; preserve CSG/NAV proxy",
            }
        )
    )
    (destination / "raw-tile-summary.json").write_text(
        json.dumps(
            {
                "map": name,
                "navFaces": nfaces,
                "sourcePolygonCount": source_count,
                "polygonTriangulationMaxPlaneError": max(plane_errors),
                "components": sorted(map(len, groups), reverse=True),
                "start": scene["start"],
                "reachableFaces": len(scene["reachable"]["faces"]),
                "derivedGroundLinks": len(step_links),
                "derivedPlayerJumpLinks": len(jump_links),
                "reachableHeightSpan": scene["reachable"]["heightSpan"],
                "spawns": len(spawns),
                "acceptedSpawns": sum(p["accepted"] for p in spawns),
                "visualMeshes": len(mesh_data),
                "visualInstances": len(instances),
                "collisionTriangles": len(ct),
                "artInstances": sum(
                    "Aggregated" in entity["type"] for entity in entities
                ),
                "omissions": omitted,
                "sources": source_evidence,
                "aliases": aliases,
            },
            indent=2,
        ),
        encoding="utf8",
    )
    return destination


def import_enemy_specs(
    specs_path: Path,
    packages_path: Path,
    output: Path,
    *,
    candidate_nodes: Path | None = None,
    enemies_path: Path | None = None,
):
    """Resolve only explicit defense/interception Agent Avatar fields.

    Relative AvatarTypes references belong to the declaring ancestor, not the
    leaf Agent directory. No name-based Avatar substitutions are permitted.
    """
    from import_melee_mechanics import Packages

    if enemies_path is None:
        from data_sources import export_dir

        enemies_path = export_dir(ROOT) / "enemies.json"
    package = Packages(packages_path)
    frozen = json.loads(enemies_path.read_text(encoding="utf-8"))
    rows = frozen.get("data", []) if isinstance(frozen, dict) else frozen
    enemy_by_path = {row["path"]: row for row in rows}
    specs = json.loads(specs_path.read_text(encoding="utf-8"))
    nodes = (
        json.loads(candidate_nodes.read_text(encoding="utf-8"))
        if candidate_nodes
        else []
    )
    inputs = [specs_path, packages_path, enemies_path] + (
        [candidate_nodes] if candidate_nodes else []
    )
    result = []
    excluded = []
    memo = {}

    def avatars(agent):
        if agent in memo:
            return memo[agent]
        current, chain, seen, declarations, error = agent, [], set(), {}, None
        while current and current not in seen:
            if not package.exists(current):
                error = "agent-or-ancestor-absent-from-current-Packages"
                break
            seen.add(current)
            chain.append(current)
            try:
                own = package.own(current)
            except Exception as exc:
                error = "type-attribute-parse-error:" + type(exc).__name__
                break
            values = own.get("AvatarTypes")
            if isinstance(values, dict):
                for variant, value in values.items():
                    if variant not in declarations:
                        declarations[variant] = (
                            current,
                            "AvatarTypes." + variant,
                            value,
                        )
            if "STANDARD" not in declarations and isinstance(
                own.get("AvatarType"), str
            ):
                declarations["STANDARD"] = (current, "AvatarType", own["AvatarType"])
            current = package.parent(current)
        variants = {}
        for variant, (owner, field, value) in declarations.items():
            resolved = (
                package.locate(owner, value)
                if isinstance(value, str) and value
                else None
            )
            record = enemy_by_path.get(resolved)
            variants[variant] = {
                "declaringType": owner,
                "field": field,
                "rawReference": value,
                "resolvedAvatarPath": resolved,
                "presentInCurrentPackages": bool(resolved),
                "presentInFrozenEnemies": record is not None,
                "frozenEnemyName": (
                    (record.get("nameZh") or record.get("nameEn") or record.get("name"))
                    if record
                    else None
                ),
                "frozenFaction": record.get("faction") if record else None,
            }
        standard = variants.get("STANDARD", {})
        value = {
            "agentInheritanceChain": chain,
            "avatarVariants": variants,
            "resolvedAvatarPath": standard.get("resolvedAvatarPath"),
            "presentInFrozenEnemies": standard.get("presentInFrozenEnemies", False),
            "resolutionStatus": (
                "exact-standard-avatar"
                if standard.get("resolvedAvatarPath")
                else error or "no-explicit-standard-avatar-field"
            ),
            "resolutionError": error,
        }
        memo[agent] = value
        return value

    for spec in specs:
        path = spec["path"]
        if not (
            "Defense" in path.rsplit("/", 1)[-1]
            or "Interception" in path.rsplit("/", 1)[-1]
        ):
            excluded.append(path)
            continue
        candidates = [
            {
                "node": node.get("node"),
                "name": node.get("name"),
                "links": node.get("links", []),
                "basis": node.get("basis"),
                "offset": node.get("offset"),
            }
            for node in nodes
            if path in node.get("links", [])
        ]
        entries = []
        for index, raw in enumerate(spec["enemies"]):
            resolved = avatars(raw["agent"])
            entry = dict(raw, rowIndex=index, **resolved)
            entry["runnable"] = bool(
                entry["resolvedAvatarPath"]
                and entry["presentInFrozenEnemies"]
                and not entry["resolutionError"]
            )
            entry["availabilityStatus"] = (
                "exact-frozen-avatar"
                if entry["runnable"]
                else (
                    "current-avatar-not-in-frozen-catalog"
                    if entry["resolvedAvatarPath"]
                    and not entry["presentInFrozenEnemies"]
                    else entry["resolutionStatus"]
                )
            )
            entries.append(entry)
        tiers = []
        for tier in sorted({row["tier"] for row in entries}):
            members = [row for row in entries if row["tier"] == tier]
            runnable = [
                row
                for row in members
                if row["runnable"] and float(row.get("probability", 0)) > 0
            ]
            tiers.append(
                {
                    "tier": tier,
                    "rawEntryCount": len(members),
                    "runnableEntryCount": len(runnable),
                    "runnableUniqueAvatarCount": len(
                        {row["resolvedAvatarPath"] for row in runnable}
                    ),
                    "rawWeightSum": sum(
                        float(row.get("probability", 0)) for row in members
                    ),
                    "runnableWeightSum": sum(
                        float(row.get("probability", 0)) for row in runnable
                    ),
                }
            )
        result.append(
            {
                "path": path,
                "rawCount": spec.get("count"),
                "rawProbabilitySum": spec.get("probability_sum"),
                "rawTiers": spec.get("tiers"),
                "mapCandidates": candidates,
                "tiers": tiers,
                "enemies": entries,
            }
        )
    payload = {
        "schema": "portable-arena-enemy-specs/v1",
        "parserVersion": PARSER_VERSION + "/enemy-specs-v1",
        "currentAgentSourceBuild": "2026.10.28.09.54",
        "frozenEnemyBuild": (
            frozen.get("buildLabel") if isinstance(frozen, dict) else None
        ),
        "sources": [
            {"file": str(path.name), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in inputs
        ],
        "qualification": [
            "Raw source tier/probability/maxSimultaneous/weaponOverrides/mergeSymbol preserved unchanged.",
            "STANDARD AvatarTypes/AvatarType resolved through explicit current Packages inheritance; no approximate Avatar substitution.",
            "Current Agent source and older frozen damage catalog are separate versions; exact path existence does not prove stat parity.",
            "Optional scenario rule: normalize positive runnable weights within a user-selected tier only; this is NOT native observed spawn frequency.",
            "Raw maxSimultaneous=0 remains zero; runtime meaning is not inferred here.",
            "mapCandidates are ordered-string evidence, not fully decoded solar-map linkage or current Arbitration rotation.",
        ],
        "excludedSpecs": excluded,
        "specs": result,
    }
    output.mkdir(parents=True, exist_ok=True)
    target = output / "enemy-specs.json.gz"
    target.write_bytes(gzip.compress(compact(payload), compresslevel=9, mtime=0))
    return payload, target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="audited arena-demo directory")
    parser.add_argument("--output", type=Path, default=ROOT / "data/arena")
    parser.add_argument("--map-id", default="corpus-ship-defense")
    parser.add_argument("--no-static-walls", action="store_true")
    parser.add_argument("--raw-tile-dir", type=Path)
    parser.add_argument("--tile-path")
    parser.add_argument("--prepared-source", type=Path)
    parser.add_argument("--proc-file", type=Path)
    parser.add_argument("--enemy-specs-source", type=Path)
    parser.add_argument("--packages-bin", type=Path)
    parser.add_argument("--candidate-nodes", type=Path)
    parser.add_argument("--enemies", type=Path)
    parser.add_argument("--enemy-specs-only", action="store_true")
    args = parser.parse_args()
    if args.raw_tile_dir:
        if not args.tile_path or not args.prepared_source:
            parser.error("--raw-tile-dir requires --tile-path and --prepared-source")
        args.source = prepare_raw_tile(
            args.raw_tile_dir,
            args.tile_path,
            args.prepared_source,
            node_evidence=args.candidate_nodes,
            proc_file=args.proc_file,
        )
    if args.enemy_specs_source:
        if not args.packages_bin:
            parser.error("--enemy-specs-source requires --packages-bin")
        payload, path = import_enemy_specs(
            args.enemy_specs_source,
            args.packages_bin,
            args.output,
            candidate_nodes=args.candidate_nodes,
            enemies_path=args.enemies,
        )
        print(
            json.dumps(
                {
                    "enemySpecsFile": str(path),
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                    "tier0": {
                        spec["path"].rsplit("/", 1)[-1]: next(
                            (tier for tier in spec["tiers"] if tier["tier"] == 0), None
                        )
                        for spec in payload["specs"]
                    },
                },
                indent=2,
            )
        )
    if args.enemy_specs_only:
        if not args.enemy_specs_source:
            parser.error("--enemy-specs-only requires --enemy-specs-source")
        return
    if not args.source:
        parser.error("--source is required unless --enemy-specs-only")
    entry = import_scene(
        args.source, args.output, args.map_id, walls=not args.no_static_walls
    )
    print(
        json.dumps(
            {
                "id": entry["id"],
                "assets": entry["assets"],
                "staticWalls": entry["staticWallAdmission"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
