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


class _ZeroAreaNavFace(ValueError):
    """Only a valid source edge ring whose vertices are exactly collinear."""

    def __init__(self, source_face, ring):
        self.source_face = source_face
        self.ring = list(ring)
        super().__init__(f"NAV polygon {source_face}: exact collinear zero-area ring")


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
        # Newell cancellation alone may also mean a self-crossing polygon.
        # Quarantine only exact collinearity, not tiny valid triangles, bowties
        # or arbitrary invalid source faces. Source coordinates stay unchanged.
        anchor = points[0]
        direction = next(
            (_sub(point, anchor) for point in points[1:] if point != anchor), None
        )
        if direction is not None and all(
            _cross(direction, _sub(point, anchor)) == (0.0, 0.0, 0.0)
            for point in points
        ):
            raise _ZeroAreaNavFace(source_face, ring)
        raise ValueError(
            f"NAV polygon {source_face}: zero/cancelled area, not exact collinearity"
        )
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
    quarantined_faces = []
    quarantined_ids = set()
    for f in range(source_count):
        try:
            ring, split, error = _triangulate_nav_polygon(vertices, faces[f], f)
        except _ZeroAreaNavFace as exc:
            ring, split, error = exc.ring, [], 0.0
            quarantined_ids.add(f)
            quarantined_faces.append(
                {
                    "sourceFace": f,
                    "vertexIds": list(ring),
                    "positions": [list(vertices[k]) for k in ring],
                    "sourceEdges": [list(edge) for edge in faces[f]],
                    "reason": "exact-collinear-zero-area-source-ring",
                    "qualification": "isolated without moving source vertices or replacing incident portals",
                }
            )
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

    excluded_portals = []
    quarantined_neighbor_faces = set()
    # Shared edge records contain exact source vertex IDs.
    for a, c, f, g, tag in struct.iter_unpack(
        "<5H", nav_b.read_bytes()[nverts * 12 : end]
    ):
        if g == 65535:
            continue
        edge = tuple(sorted((a, c)))
        if f in quarantined_ids or g in quarantined_ids:
            excluded_portals.append(
                {
                    "sourceFaces": [f, g],
                    "vertexIds": list(edge),
                    "reason": "incident-to-quarantined-zero-area-face",
                }
            )
            quarantined_neighbor_faces.update(expanded.get(f, []))
            quarantined_neighbor_faces.update(expanded.get(g, []))
            continue
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
    if not nfaces:
        raise ValueError("NAV contains no nonquarantined faces")
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
            if face in quarantined_neighbor_faces:
                continue
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
            options = best.setdefault(key, [])
            options.append((length, fa, fb, pa, pb))
            options.sort(
                key=lambda candidate: (candidate[0], candidate[1], candidate[2])
            )
            del options[8:]
    step_links = []
    accepted_component_pairs = set()
    for pair, options in best.items():
        for candidate_rank, (length, fa, fb, pa, pb) in enumerate(options):
            if pair in accepted_component_pairs:
                break
            raw_points = [nodes[fa], pa, pb, nodes[fb]]
            supported, valid = [], True
            for aa, bb in zip(raw_points, raw_points[1:]):
                sample_count = max(2, int(math.dist(aa, bb) / 0.12) + 1)
                for k in range(sample_count):
                    ratio = k / sample_count
                    foot = tuple(aa[i] * (1 - ratio) + bb[i] * ratio for i in range(3))
                    hit = bvh.raycast(
                        (foot[0], foot[1] + 0.5, foot[2]), (0, -1, 0), 1.1
                    )
                    if not hit:
                        valid = False
                        break
                    point = hit.position
                    if supported and abs(point[1] - supported[-1][1]) > 0.5:
                        valid = False
                        break
                    if supported:
                        last = supported[-1]
                        for dx, dz in (
                            (0, 0),
                            (0.2, 0),
                            (-0.2, 0),
                            (0, 0.2),
                            (0, -0.2),
                        ):
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
                accepted_component_pairs.add(pair)
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
                                "candidateRank": candidate_rank,
                                "boundedCandidateCount": len(options),
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
            if fa in quarantined_neighbor_faces or fb in quarantined_neighbor_faces:
                continue
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
            "sourceFaceToTriangles": [expanded[f] for f in range(source_count)],
            "quarantinedSourceFaces": quarantined_faces,
            "excludedSourcePortals": excluded_portals,
            "quarantineDerivedLinkExcludedFaces": sorted(quarantined_neighbor_faces),
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
                "quarantinedSourceFaces": quarantined_faces,
                "excludedSourcePortalCount": len(excluded_portals),
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


def _read_visual_level(source: Path, tile_path: str):
    """Read exact LEVEL212 instances for visual completion, independent of NAV."""
    import struct

    name = tile_path.rsplit("/", 1)[-1]
    header = next((source / "raw-level").glob(f"**/{name}.level_H"))
    body = next((source / "raw-level").glob(f"**/{name}.level_B"))
    h, b = header.read_bytes(), body.read_bytes()
    reader = _TileReader(h, 16)
    reader.strings()
    reader.u32()
    version = reader.u32()
    if version != 212:
        raise ValueError(f"unsupported visual LEVEL {version}")
    reader.strings()
    reader.strings()
    reader.strings()
    for _ in range(reader.u32()):
        reader.string()
        reader.string()
        reader.u32()
        reader.u32()
    if reader.u32() != 0:
        raise ValueError("unexpected level prefix")
    count = reader.u32()
    entities = []
    for index in range(count):
        offset = reader.pos
        typ = reader.string()
        values = struct.unpack_from("<7f", h, reader.pos)
        reader.pos += 28
        scope = reader.string()
        mesh_index, unknown = reader.u32(), reader.u32()
        entities.append(
            {
                "id": index,
                "type": typ,
                "position": list(values[:3]),
                "quaternion": list(values[3:]),
                "scope": scope,
                "headerOffset": offset,
            }
        )
    lens = struct.unpack_from("<" + "I" * count, b)
    offset = count * 4
    for entity, length in zip(entities, lens):
        entity["attributes"] = (
            b[offset : offset + length + 1].rstrip(b"\0").decode("utf8")
        )
        entity["bodyOffset"] = offset
        offset += length + 1
    if offset != len(b):
        raise ValueError("visual level body not fully consumed")
    return entities, {
        "levelHeaderSha256": sha(header),
        "levelBodySha256": sha(body),
        "levelEntities": count,
        "levelHeaderTailBytes": len(h) - reader.pos,
        "levelBodyFullyConsumed": True,
    }


def _decode_visual_glb(path: Path, source_path: str):
    """Reverse exporter static-Z mirror; preserve groups without invented UVs."""
    import struct

    data = path.read_bytes()
    size = struct.unpack_from("<I", data, 12)[0]
    doc, binary = json.loads(data[20 : 20 + size]), data[28 + size :]
    if doc.get("skins") or any(
        any(
            key in node
            for key in ("matrix", "translation", "rotation", "scale", "skin")
        )
        for node in doc.get("nodes", [])
    ):
        return None, "rigged-or-node-transformed-mesh-unassembled"

    def access(index):
        accessor = doc["accessors"][index]
        view = doc["bufferViews"][accessor["bufferView"]]
        width = {"SCALAR": 1, "VEC3": 3}[accessor["type"]]
        code = {5126: "f", 5123: "H", 5125: "I"}[accessor["componentType"]]
        offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        stride = view.get("byteStride", struct.calcsize("<" + code) * width)
        return [
            struct.unpack_from("<" + code * width, binary, offset + i * stride)
            for i in range(accessor["count"])
        ]

    vertices, indices, groups, unique = [], [], [], {}
    for mesh in doc.get("meshes", []):
        for primitive in mesh["primitives"]:
            if primitive.get("mode", 4) != 4:
                return None, "non-triangle-primitive"
            points = access(primitive["attributes"]["POSITION"])
            remap = []
            for x, y, z in points:
                point = (round(x, 5), round(y, 5), round(-z, 5))
                if point not in unique:
                    unique[point] = len(vertices) // 3
                    vertices.extend(point)
                remap.append(unique[point])
            raw = [row[0] for row in access(primitive["indices"])]
            start = len(indices)
            for k in range(0, len(raw), 3):
                indices.extend((remap[raw[k]], remap[raw[k + 2]], remap[raw[k + 1]]))
            mat = doc.get("materials", [{}])[primitive.get("material", 0)]
            groups.append(
                {
                    "start": start,
                    "count": len(raw),
                    "sourceMaterialPath": mat.get("extras", {}).get(
                        "FullPath", mat.get("name", "unknown")
                    ),
                }
            )
    if not indices:
        return None, "no-triangle-geometry"
    return {
        "path": source_path,
        "positions": vertices,
        "indices": indices,
        "groups": groups,
        "sha256": sha(path),
        "triangleCount": len(indices) // 3,
        "vertexCount": len(vertices) // 3,
        "bounds": [
            [min(vertices[i::3]) for i in range(3)],
            [max(vertices[i::3]) for i in range(3)],
        ],
        "category": (
            "csg"
            if source_path.endswith("_c.fbx")
            else (
                "structure"
                if source_path.endswith(".tmesh")
                or re.search(
                    r"Structural|Floor|Wall|Stair|Ramp|Platform|Catwalk|_a\.fbx$",
                    source_path,
                    re.I,
                )
                else "prop"
            )
        ),
        "qualification": "actual referenced static mesh; source XYZ; inverse exporter Z mirror and winding; positions quantized1e-5",
    }, None


def _inspect_renderless_mesh(header: Path, body: Path):
    """Read known source header counts, without turning collision into visuals."""
    import struct

    data = header.read_bytes()
    reader = _TileReader(data, 16)
    reader.strings()
    reader.u32()
    version = reader.u32()
    if version not in (102, 109, 112):
        return None
    resource_start = reader.pos
    reader.pos += 0x30
    first, second = reader.u32(), reader.u32()
    if (first == 8 or second == 8) if version == 102 else (first & 8 or second & 8):
        reader.pos += 2
    reader.string()
    reader.pos += 0x28 + 32
    count_offset = reader.pos
    vertices, indices, morphs, bones = (reader.u32() for _ in range(4))
    if vertices or indices:
        return None
    payload = body.read_bytes()
    return {
        "kind": "source-zero-render-geometry",
        "resourceVersion": version,
        "resourcePayloadOffset": resource_start,
        "renderCountOffset": count_offset,
        "renderVertices": vertices,
        "renderIndices": indices,
        "morphCount": morphs,
        "boneCount": bones,
        "headerSha256": sha(header),
        "bodySha256": sha(body),
        "bodyBytes": len(payload),
        "bodyMagicHex": payload[:16].hex(),
        "physxConvexMagic": payload.startswith(b"NXS\x01CVXM"),
        "qualification": "source render vertex/index counts are both zero under upstream model102/109/112 header layout; retained physics/body data is not a visible surface or alternate render LOD",
    }


def complete_visual_maps(
    case_root: Path,
    cache_dir: Path,
    exporter: Path,
    packages_bin: Path,
    output: Path,
    *,
    map_ids=None,
):
    """Complete exact external LEVEL Mesh references; never modify NAV/collision.

    Shared per-resource extraction cache and instance-level omissions make this
    reusable for every imported map. Catalog updates are restricted to the
    visual-map asset entry; live metadata maintained by other owners is reread.
    """
    import subprocess
    from collections import Counter
    from import_melee_mechanics import Packages

    package = Packages(packages_bin)
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    workspace = case_root / "work/geometry/complete-visuals"
    workspace.mkdir(parents=True, exist_ok=True)
    shared = workspace / "assets"
    shared.mkdir(exist_ok=True)
    index_path = workspace / "export-index.json"
    export_index = (
        json.loads(index_path.read_text(encoding="utf8")) if index_path.exists() else {}
    )
    decoded, defaults, results = {}, {}, []
    for map_id, entry in catalog["maps"].items():
        if map_ids and map_id not in map_ids:
            continue
        tile = entry["sourceTile"]
        name = tile.rsplit("/", 1)[-1]
        source = (
            case_root
            / "work/geometry"
            / ("galleon" if name == "GrnDefenceTwo" else "map-coverage/" + name)
        )
        if name == "ObjDefense01":
            source = case_root / "work/geometry"
        entities, provenance = _read_visual_level(source, tile)
        prior_asset = entry["assets"]["visual-map"]
        old = json.loads(gzip.decompress((output / prior_asset["file"]).read_bytes()))
        metadata = dict(old.get("metadata", {}))
        meshes, instances, materials, matids, meshids, omissions = (
            [],
            [],
            [],
            {},
            {},
            [],
        )

        def material(path):
            if path not in matids:
                color = "#64727b"
                if re.search(r"Floor|Catwalk|Platform|Stair", path, re.I):
                    color = "#6d756d"
                elif re.search(r"Wall|Panel|InteriorKit", path, re.I):
                    color = "#657783"
                elif re.search(r"Metal|Iron|Steel|Rust", path, re.I):
                    color = "#787872"
                elif re.search(r"Dark|Black|DkGray", path, re.I):
                    color = "#3b4650"
                elif re.search(r"Light|Emissive", path, re.I):
                    color = "#97b7c5"
                elif re.search(r"Grineer|Gln|Gof", path, re.I):
                    color = "#777565"
                matids[path] = len(materials)
                materials.append(
                    {
                        "id": len(materials),
                        "sourcePath": path,
                        "color": color,
                        "qualification": "source material identity with simplified untextured color",
                    }
                )
            return matids[path]

        # Keep original shared-mesh IDs stable: the separate collision candidate
        # sidecar can refer to those IDs even though simulation collision is not
        # changed by this visual-only pass. New shared meshes append afterwards.
        original_file = (
            (case_root / "output/arena-demo/visual-map.json")
            if name == "ObjDefense01"
            else source / "prepared/visual-map.json"
        )
        original_visual = (
            json.loads(original_file.read_text(encoding="utf8"))
            if original_file.exists()
            else old
        )
        for original_mesh in original_visual.get("meshes", []):
            seeded = dict(original_mesh)
            seeded["id"] = len(meshes)
            seeded["groups"] = []
            for group in original_mesh["groups"]:
                path = (
                    group.get("sourceMaterialPath")
                    or original_visual["materials"][group["materialId"]]["sourcePath"]
                )
                seeded["groups"].append(
                    dict(group, sourceMaterialPath=path, materialId=material(path))
                )
            positions = seeded["positions"]
            seeded["bounds"] = [
                [min(positions[i::3]) for i in range(3)],
                [max(positions[i::3]) for i in range(3)],
            ]
            seeded["category"] = (
                "csg"
                if seeded["path"].endswith("_c.fbx")
                else (
                    "structure"
                    if re.search(
                        r"Structural|Floor|Wall|Stair|Ramp|Platform|Catwalk|_a\.fbx$",
                        seeded["path"],
                        re.I,
                    )
                    else "prop"
                )
            )
            meshids[seeded["path"]] = seeded["id"]
            meshes.append(seeded)
        explicit_count = inherited_count = eligible = 0
        for entity in entities:
            raw, typ = entity["attributes"], entity["type"]
            if typ not in defaults:
                # A true source parse error must stop the import. Falling back
                # to {} would silently lose inherited Mesh-bearing instances.
                defaults[typ] = package.resolve(typ) if package.exists(typ) else {}
            base = defaults[typ]
            match = re.search(r"^Mesh=(.*)$", raw, re.M)
            reference = match[1].strip('"') if match else base.get("Mesh")
            if not isinstance(reference, str) or not reference:
                continue
            explicit_count += bool(match)
            inherited_count += not bool(match)
            if reference.startswith("/"):
                path = reference
            elif match:
                path = (
                    tile + "/" + reference
                    if not reference.startswith(name + "/")
                    else tile.rsplit("/", 1)[0] + "/" + reference
                )
            else:
                # Mesh references inherited from a type belong to that type's
                # declaring directory, not the map tile or instance scope.
                owner = typ
                seen = set()
                while owner and owner not in seen:
                    seen.add(owner)
                    own = package.own(owner)
                    if "Mesh" in own:
                        break
                    owner = package.parent(owner)
                path = owner.rsplit("/", 1)[0] + "/" + reference if owner else ""
            reason = None
            if re.search(r"^Attached=1$", raw, re.M) or (
                not re.search(r"^Attached=", raw, re.M) and base.get("Attached")
            ):
                reason = "attached-parent-local-transform-unresolved"
            elif re.search(r"^StartHidden=1$", raw, re.M) or (
                not re.search(r"^StartHidden=", raw, re.M) and base.get("StartHidden")
            ):
                reason = "authored-start-hidden"
            elif (
                typ.endswith("/Mover")
                or "/Characters/" in typ
                or "/Fx/" in typ
                or ("/Fx/" in path and not re.search(r"IceFloorMesh", path))
            ):
                reason = "dynamic-mover-character-or-effect"
            elif path == "/EE/Objects/FogVolumeSphere.lwo":
                reason = "source-fog-volume-not-visible-floor-geometry"
            elif re.search(r"/Decals/|/Water/|/Skybox/", path, re.I):
                reason = "decal-water-sky-needs-source-transparency-material"
            elif not path.startswith("/") or not path.endswith(
                (".fbx", ".obj", ".tmesh")
            ):
                reason = "unsupported-or-unresolved-mesh-reference"
            if reason:
                omissions.append(
                    {
                        "entityId": entity["id"],
                        "type": typ,
                        "sourceMesh": path,
                        "reason": reason,
                    }
                )
                continue
            eligible += 1
            if path not in decoded:
                # Reuse source tile exports when exact original path matches.
                existing = (
                    source / "models" / (path.lstrip("/").rsplit(".", 1)[0] + ".glb")
                )
                if existing.exists():
                    file = existing
                else:
                    file = shared / (path.lstrip("/").rsplit(".", 1)[0] + ".glb")
                    if not file.exists() and path not in export_index:
                        args = [
                            str(exporter),
                            "--game",
                            "Warframe",
                            "--cache-dir",
                            str(cache_dir),
                            "--extract-models",
                            "--package",
                            "Misc",
                            "--internal-path",
                            path,
                            "--output-path",
                            str(shared),
                        ]
                        run = subprocess.run(
                            args,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=60,
                        )
                        log = workspace / "export.log"
                        with log.open("ab") as stream:
                            stream.write(
                                ("\nRESOURCE " + path + "\n").encode() + run.stdout
                            )
                        export_index[path] = {
                            "returncode": run.returncode,
                            "file": str(file),
                            "exists": file.exists(),
                        }
                        index_path.write_text(
                            json.dumps(export_index, indent=2), encoding="utf8"
                        )
                if file.exists():
                    try:
                        decoded[path] = _decode_visual_glb(file, path)
                    except Exception as exc:
                        decoded[path] = (
                            None,
                            "mesh-decode-failed:" + type(exc).__name__ + ":" + str(exc),
                        )
                else:
                    raw_cache = workspace / "raw-format-cache"
                    header = raw_cache / (path.lstrip("/") + "_H")
                    body = raw_cache / (path.lstrip("/") + "_B")
                    if (
                        not header.exists()
                        and (raw_cache / "Debug" / (path.lstrip("/") + "_H")).exists()
                    ):
                        header = raw_cache / "Debug" / (path.lstrip("/") + "_H")
                        body = raw_cache / "Debug" / (path.lstrip("/") + "_B")
                    if not header.exists():
                        command = [
                            str(exporter),
                            "--game",
                            "Warframe",
                            "--cache-dir",
                            str(cache_dir),
                            "--write-raw",
                            "--package",
                            "Misc",
                            "--internal-path",
                            path,
                            "--output-path",
                            str(raw_cache),
                        ]
                        run = subprocess.run(
                            command,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            timeout=60,
                        )
                        with (workspace / "export.log").open("ab") as stream:
                            stream.write(
                                ("\nRAW FORMAT " + path + "\n").encode() + run.stdout
                            )
                    # Exporter raw output inserts Debug before the source path.
                    if not header.exists():
                        header = raw_cache / "Debug" / (path.lstrip("/") + "_H")
                        body = raw_cache / "Debug" / (path.lstrip("/") + "_B")
                    inspection = (
                        _inspect_renderless_mesh(header, body)
                        if header.exists() and body.exists()
                        else None
                    )
                    if inspection:
                        export_index.setdefault(path, {})["rawInspection"] = inspection
                        index_path.write_text(
                            json.dumps(export_index, indent=2), encoding="utf8"
                        )
                    decoded[path] = (
                        None,
                        (
                            "source-zero-render-geometry"
                            if inspection
                            else "referenced-resource-export-failed"
                        ),
                    )
            mesh, error = decoded[path]
            if mesh is None:
                omissions.append(
                    {
                        "entityId": entity["id"],
                        "type": typ,
                        "sourceMesh": path,
                        "reason": error,
                    }
                )
                continue
            if path not in meshids:
                item = dict(mesh)
                item["id"] = len(meshes)
                item["groups"] = [
                    dict(g, materialId=material(g["sourceMaterialPath"]))
                    for g in mesh["groups"]
                ]
                meshids[path] = item["id"]
                meshes.append(item)
            scale_match = re.search(r"^MeshScale=(.+)$", raw, re.M)
            scale = (
                float(scale_match[1])
                if scale_match
                else float(base.get("MeshScale", 1.0))
            )
            if (
                not math.isfinite(scale)
                or scale <= 0
                or abs(sum(x * x for x in entity["quaternion"]) - 1) > 1e-3
            ):
                omissions.append(
                    {
                        "entityId": entity["id"],
                        "sourceMesh": path,
                        "reason": "invalid-scale-or-quaternion",
                    }
                )
                continue
            override = re.search(r"^OverrideMaterial=\{([^}]+)\}", raw, re.M)
            overrides = (
                [material(x.strip()) for x in override[1].split(",")]
                if override
                else None
            )
            instance_index = re.search(r"^Instance=(\d+)$", raw, re.M)
            instances.append(
                {
                    "entityId": entity["id"],
                    "meshId": meshids[path],
                    "name": entity["scope"]
                    + typ.rsplit("/", 1)[-1]
                    + (instance_index[1] if instance_index else "?"),
                    "position": entity["position"],
                    "quaternion": entity["quaternion"],
                    "scale": scale,
                    "scaleSource": (
                        "explicit-instance"
                        if scale_match
                        else (
                            "inherited-type"
                            if "MeshScale" in base
                            else "exporter-default1"
                        )
                    ),
                    "materialOverrides": overrides,
                    "qualification": "exact absolute source-level instance; external shared Mesh resolved by full path; no extra prefab transform",
                }
            )
        report = {
            "parserVersion": PARSER_VERSION + "/complete-static-visual-v1",
            "sourceTile": tile,
            **provenance,
            "packagesSha256": sha(packages_bin),
            "previousInstances": len(old.get("instances", [])),
            "meshBearingEntities": explicit_count + inherited_count,
            "explicitMeshInstances": explicit_count,
            "inheritedMeshInstances": inherited_count,
            "eligibleStaticInstances": eligible,
            "assembledInstances": len(instances),
            "assembledMeshAssets": len(meshes),
            "sourceMeshTriangles": sum(m["triangleCount"] for m in meshes),
            "instancedTriangles": sum(
                meshes[x["meshId"]]["triangleCount"] for x in instances
            ),
            "omittedInstances": len(omissions),
            "omittedByReason": dict(Counter(x["reason"] for x in omissions)),
            "externalInstances": sum(
                not meshes[x["meshId"]]["path"].startswith(tile + "/")
                for x in instances
            ),
            "floorStairPlatformInstances": sum(
                bool(
                    re.search(
                        r"Floor|Stair|Ramp|Platform|Catwalk",
                        meshes[x["meshId"]]["path"],
                        re.I,
                    )
                )
                for x in instances
            ),
            "qualification": "full explicit/inherited static Mesh references attempted; rendered real source geometry only; source omissions listed; no NAV rendering used as replacement floor; simulation NAV and collision unmodified",
        }
        world_min, world_max = [math.inf] * 3, [-math.inf] * 3
        for instance in instances:
            bounds = meshes[instance["meshId"]]["bounds"]
            for corner in range(8):
                point = transform(
                    [bounds[(corner >> i) & 1][i] for i in range(3)], instance
                )
                for i in range(3):
                    world_min[i] = min(world_min[i], point[i])
                    world_max[i] = max(world_max[i], point[i])
        report["worldBounds"] = [world_min, world_max]
        report["originalInstances"] = len(original_visual.get("instances", []))
        report["stableOriginalMeshIds"] = len(original_visual.get("meshes", []))
        report["usedMeshAssets"] = len({instance["meshId"] for instance in instances})
        metadata["worldBounds"] = [world_min, world_max]
        report["terrainInstances"] = sum(
            meshes[x["meshId"]]["path"].endswith(".tmesh") for x in instances
        )
        report["missingMeshInstances"] = sum(
            x["reason"]
            in (
                "referenced-resource-export-failed",
                "unsupported-or-unresolved-mesh-reference",
            )
            or x["reason"].startswith("mesh-decode-failed")
            for x in omissions
        )
        report["unsupportedRiggedMeshInstances"] = sum(
            x["reason"] == "rigged-or-node-transformed-mesh-unassembled"
            for x in omissions
        )
        report["excludedSourceStateInstances"] = (
            len(omissions)
            - report["missingMeshInstances"]
            - report["unsupportedRiggedMeshInstances"]
        )
        report["sourceZeroRenderInstances"] = sum(
            x["reason"] == "source-zero-render-geometry" for x in omissions
        )
        report["sourceFogVolumeInstances"] = sum(
            x["reason"] == "source-fog-volume-not-visible-floor-geometry"
            for x in omissions
        )
        metadata["visualCoverage"] = report
        metadata["visualCompletion"] = report
        value = {
            "schema": "arena-visual-map/v1",
            "metadata": metadata,
            "meshes": meshes,
            "materials": materials,
            "instances": instances,
        }
        raw = compact(value)
        target = output / prior_asset["file"]
        target.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
        newmeta = {
            "file": target.name,
            "sha256": sha(target),
            "jsonSha256": hashlib.sha256(raw).hexdigest(),
            "compressedBytes": target.stat().st_size,
            "jsonBytes": len(raw),
        }
        # Reread just before write: other owners may update names/source metadata.
        latest = json.loads((output / "catalog.json").read_text(encoding="utf8"))
        latest["maps"][map_id]["assets"]["visual-map"] = newmeta
        (output / "catalog.json").write_text(
            json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
        evidence = case_root / "evidence/geometry"
        evidence.mkdir(exist_ok=True)
        (evidence / (map_id + "-visual-completion.json")).write_text(
            json.dumps(
                {"summary": report, "asset": newmeta, "omissions": omissions},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf8",
        )
        results.append(dict(mapId=map_id, **report))
        print(
            json.dumps(
                {
                    "mapId": map_id,
                    "before": report["previousInstances"],
                    "after": len(instances),
                    "omitted": len(omissions),
                    "meshes": len(meshes),
                    "floorInstances": report["floorStairPlatformInstances"],
                    "compressedBytes": newmeta["compressedBytes"],
                }
            ),
            flush=True,
        )
    (case_root / "evidence/geometry/visual-completion-summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    return results


def audit_visual_support(output: Path, case_root: Path, *, map_ids=None):
    """Bounded visual-only floor support samples; never uses NAV as geometry."""
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    results = []

    def rotate(point, quaternion):
        u = quaternion[:3]
        a = _cross(u, point)
        b = _cross(u, a)
        return tuple(point[i] + 2 * (quaternion[3] * a[i] + b[i]) for i in range(3))

    for map_id, entry in catalog["maps"].items():
        if map_ids and map_id not in map_ids:
            continue
        visual = json.loads(
            gzip.decompress(
                (output / entry["assets"]["visual-map"]["file"]).read_bytes()
            )
        )
        scene = json.loads(
            gzip.decompress((output / entry["assets"]["scene"]["file"]).read_bytes())
        )
        meshes = visual["meshes"]
        trees = {}
        bounds = []
        for instance in visual["instances"]:
            mesh = meshes[instance["meshId"]]
            bb = mesh.get("bounds")
            if not bb:
                vs = mesh["positions"]
                bb = [
                    [min(vs[i::3]) for i in range(3)],
                    [max(vs[i::3]) for i in range(3)],
                ]
            corners = [
                transform([bb[(k >> i) & 1][i] for i in range(3)], instance)
                for k in range(8)
            ]
            bounds.append(
                (
                    instance,
                    [min(p[i] for p in corners) for i in range(3)],
                    [max(p[i] for p in corners) for i in range(3)],
                )
            )
        nodes = scene["nav"]["nodePositions"]
        count = min(96, len(nodes))
        ids = sorted(
            {int(i * (len(nodes) - 1) / max(1, count - 1)) for i in range(count)}
        )
        matches = []
        missing = []
        for face in ids:
            point = nodes[face]
            origin = (point[0], point[1] + 0.3, point[2])
            hits = []
            for instance, lo, hi in bounds:
                if not (
                    lo[0] - 1e-5 <= point[0] <= hi[0] + 1e-5
                    and lo[2] - 1e-5 <= point[2] <= hi[2] + 1e-5
                    and hi[1] >= point[1] - 1.5
                    and lo[1] <= origin[1]
                ):
                    continue
                mid = instance["meshId"]
                if mid not in trees:
                    m = meshes[mid]
                    v = m["positions"]
                    ix = m["indices"]
                    trees[mid] = TriangleBVH(
                        [v[k : k + 3] for k in range(0, len(v), 3)],
                        [ix[k : k + 3] for k in range(0, len(ix), 3)],
                        native=True,
                    )
                q = instance["quaternion"]
                inverse = (-q[0], -q[1], -q[2], q[3])
                scale = instance["scale"]
                local_origin = tuple(
                    v / scale
                    for v in rotate(_sub(origin, instance["position"]), inverse)
                )
                local_direction = rotate((0, -1, 0), inverse)
                hit = trees[mid].raycast(local_origin, local_direction, 1.8 / scale)
                if hit and abs(rotate(hit.normal, q)[1]) >= 0.4:
                    pos = transform(hit.position, instance)
                    hits.append(
                        {
                            "entityId": instance["entityId"],
                            "sourceMesh": meshes[mid]["path"],
                            "heightDifference": round(point[1] - pos[1], 5),
                            "position": pos,
                        }
                    )
            if hits:
                matches.append(
                    {
                        "navFace": face,
                        "navPoint": point,
                        "support": min(hits, key=lambda h: abs(h["heightDifference"])),
                    }
                )
            else:
                missing.append({"navFace": face, "position": point})
        record = {
            "mapId": map_id,
            "sampledNavFaces": len(ids),
            "realVisualSupportHits": len(matches),
            "noVisualSupportInWindow": len(missing),
            "supportWindow": {"aboveNav": 0.3, "belowNav": 1.5},
            "qualification": "bounded real visual mesh floor ray samples; NAV used only as sample positions, never a visual floor surrogate; unmatched samples retained, not a global completeness proof",
            "matches": matches,
            "missing": missing,
        }
        results.append(record)
        print(
            json.dumps(
                {k: v for k, v in record.items() if k not in ("matches", "missing")}
            ),
            flush=True,
        )
    target = case_root / "evidence/geometry/visual-floor-support-audit.json"
    target.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf8"
    )
    return results


def import_source_doors(
    case_root: Path, packages_bin: Path, output: Path, *, map_ids=None
):
    """Join exact NpcDoorHint/Mover/trigger source groups into qualified portals.

    A mesh name alone never grants passage. Doors require exact NpcDoorHint,
    same authored prefab scope, two paired Mover leaves with explicit keys,
    DoorTrigger tag and dimensions, and a static frame mesh. Every emitted
    crossing is tested against existing collision without ignoring any wall.
    """
    from collections import defaultdict, Counter
    from import_melee_mechanics import Packages
    from wfarsenal.arena_scene import ArenaScene

    package = Packages(packages_bin)
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    existing_sidecar = output / "door-geometry.json.gz"
    maps = (
        json.loads(gzip.decompress(existing_sidecar.read_bytes())).get("maps", {})
        if existing_sidecar.exists()
        else {}
    )

    def rotate(point, q):
        a = _cross(q[:3], point)
        b = _cross(q[:3], a)
        return tuple(point[i] + 2 * (q[3] * a[i] + b[i]) for i in range(3))

    def local(point, entity):
        q = entity["quaternion"]
        return rotate(_sub(point, entity["position"]), (-q[0], -q[1], -q[2], q[3]))

    def values(raw, key):
        found = re.search(r"^" + re.escape(key) + r"=\{([^}]+)\}", raw, re.M)
        return [float(x) for x in found[1].split(",")] if found else None

    for map_id, entry in catalog["maps"].items():
        if map_ids and map_id not in map_ids:
            continue
        tile = entry["sourceTile"]
        name = tile.rsplit("/", 1)[-1]
        source = (
            case_root
            / "work/geometry"
            / ("galleon" if name == "GrnDefenceTwo" else "map-coverage/" + name)
        )
        if name == "ObjDefense01":
            source = case_root / "work/geometry"
        entities, provenance = _read_visual_level(source, tile)
        by_scope = defaultdict(list)
        for entity in entities:
            by_scope[entity["scope"]].append(entity)
        raw = json.loads(
            gzip.decompress((output / entry["assets"]["scene"]["file"]).read_bytes())
        )
        navigation = json.loads(
            gzip.decompress(
                (output / entry["assets"]["navigation"]["file"]).read_bytes()
            )
        )
        scene = ArenaScene(raw, navigation, map_id=map_id)
        visual = json.loads(
            gzip.decompress(
                (output / entry["assets"]["visual-map"]["file"]).read_bytes()
            )
        )
        visual_by_entity = {i["entityId"]: i for i in visual["instances"]}
        doors, links, rejected = [], [], []
        for hint in entities:
            if hint["type"] != "/EE/Types/Npc/NpcDoorHint":
                continue
            group = by_scope[hint["scope"]]
            movers = [
                e
                for e in group
                if e["type"] == "/EE/Types/Engine/Mover"
                and re.search(r"^MoverKeys=\{", e["attributes"], re.M)
            ]
            trigger = next(
                (
                    e
                    for e in group
                    if re.search(r"^Tag=DoorTrigger$", e["attributes"], re.M)
                ),
                None,
            )
            frames = [
                e
                for e in group
                if e["type"]
                in ("/EE/Types/Engine/Decoration", "/EE/Types/Alias/Decoration")
                and "DoorFrame" in e["attributes"]
            ]
            attached_leaves = [
                entity
                for entity in group
                if re.search(r"^Attached=1$", entity["attributes"], re.M)
                and re.search(r"^AttachParent=Mover\d+$", entity["attributes"], re.M)
            ]
            thin_triggers = []
            for entity in group:
                if (
                    entity["type"] != "/EE/Types/Game/MultiAvatarTrigger"
                    or entity is trigger
                ):
                    continue
                raw_dims = values(entity["attributes"], "Dimensions")
                dims = None
                if raw_dims and len(raw_dims) == 3:
                    corners = [
                        local(transform((x, y, z), dict(entity, scale=1.0)), hint)
                        for x in (-raw_dims[0] / 2, raw_dims[0] / 2)
                        for y in (-raw_dims[1] / 2, raw_dims[1] / 2)
                        for z in (-raw_dims[2] / 2, raw_dims[2] / 2)
                    ]
                    dims = [
                        max(p[i] for p in corners) - min(p[i] for p in corners)
                        for i in range(3)
                    ]
                    # Existing templates serialize the trigger Dimensions
                    # in their authored door axes; other prefabs rotate the
                    # trigger90deg. Preserve the explicit narrow descriptor,
                    # using transformed extents only when it is not narrow.
                    if 0.05 <= raw_dims[2] <= 1.0:
                        dims = raw_dims
                if (
                    dims
                    and len(dims) == 3
                    and 1.8 <= dims[1] <= 8
                    and 0.05 <= dims[2] <= 1.0
                    and math.dist(entity["position"], hint["position"]) <= 6
                ):
                    thin_triggers.append((entity, dims))
            threshold = (
                min(thin_triggers, key=lambda item: item[1][2])
                if thin_triggers
                else None
            )
            if (
                len(movers) < 2
                or trigger is None
                or not (frames or (len(attached_leaves) >= 2 and threshold))
            ):
                rejected.append(
                    {
                        "entityId": hint["id"],
                        "scope": hint["scope"],
                        "reason": "insufficient joined DoorHint/MoverKeys/DoorTrigger/frame evidence",
                    }
                )
                continue
            dimensions = values(trigger["attributes"], "Dimensions")
            width_match = re.search(r"^Width=([^\n]+)$", hint["attributes"], re.M)
            width = (
                float(width_match[1])
                if width_match
                else package.resolve(hint["type"]).get("Width")
            )
            if not width and threshold:
                width = threshold[1][0]
            if not width or not dimensions or len(dimensions) != 3 or dimensions[1] < 2:
                rejected.append(
                    {
                        "entityId": hint["id"],
                        "reason": "missing explicit width or usable trigger dimensions",
                    }
                )
                continue
            # Source Width is used conservatively as FULL traversable width;
            # only inner2.0m is opened for the wider6m source trigger/frame.
            half_width = min(float(width) * 0.5, dimensions[0] * 0.5)
            height = min(3.0, dimensions[1])
            normal = rotate((0.0, 0.0, 1.0), hint["quaternion"])
            right = rotate((1.0, 0.0, 0.0), hint["quaternion"])
            up = rotate((0.0, 1.0, 0.0), hint["quaternion"])
            icons = [
                entity
                for entity in group
                if entity["type"] == "/Lotus/Fx/Gameplay/DoorIcons/DoorIconPlaneGrineer"
            ]
            depths = [
                abs(
                    sum(
                        (entity["position"][i] - hint["position"][i]) * normal[i]
                        for i in range(3)
                    )
                )
                for entity in icons
            ]
            # A confirmed door's threshold is wider than its thin detection
            # trigger on some templates. Bound the abstract default-open
            # transition by actual transformed source frame vertices AND the
            # tagged trigger, never by arbitrary nearby empty space.
            frame_depths, frame_sources = [], []
            for frame in frames:
                instance = visual_by_entity.get(frame["id"])
                if instance is None:
                    continue
                mesh = visual["meshes"][instance["meshId"]]
                positions = mesh["positions"]
                projected = [
                    local(transform(positions[k : k + 3], instance), hint)[2]
                    for k in range(0, len(positions), 3)
                ]
                frame_depths.extend(projected)
                frame_sources.append(
                    {
                        "entityId": frame["id"],
                        "mesh": mesh["path"],
                        "meshSha256": mesh["sha256"],
                        "normalBounds": [min(projected), max(projected)],
                    }
                )
            trigger_corners = [
                local(transform((x, y, z), dict(trigger, scale=1.0)), hint)
                for x in (-dimensions[0] / 2, dimensions[0] / 2)
                for y in (-dimensions[1] / 2, dimensions[1] / 2)
                for z in (-dimensions[2] / 2, dimensions[2] / 2)
            ]
            frame_transition_bounds = None
            if frame_depths:
                low = max(min(frame_depths), min(p[2] for p in trigger_corners))
                high = min(max(frame_depths), max(p[2] for p in trigger_corners))
                if low < -0.15 and high > 0.15:
                    frame_transition_bounds = (low, high)
            if depths and all(0.2 <= depth <= 0.45 for depth in depths):
                half_depth = 0.45
                depth_basis = (
                    "paired source door icon planes at normal offsets within .45"
                )
            elif threshold:
                half_depth = threshold[1][2] * 0.5 + 0.05
                depth_basis = "exact same-scope narrow MultiAvatarTrigger Dimensions depth/2 + .05"
            elif frame_transition_bounds:
                half_depth = max(abs(v) for v in frame_transition_bounds)
                depth_basis = "actual source frame normal bounds intersected with oriented DoorTrigger bounds"
            else:
                rejected.append(
                    {
                        "entityId": hint["id"],
                        "reason": "no bounded source leaf/threshold depth for this subtype",
                        "iconDepths": depths,
                    }
                )
                continue
            transition_bounds = frame_transition_bounds or (-half_depth, half_depth)
            door_id = map_id + ":source-door:" + str(hint["id"])
            sides = [[], []]
            for face, point in enumerate(scene.nodes):
                pt = local(point, hint)
                if (
                    abs(pt[0]) <= half_width - 0.15
                    and abs(pt[1]) <= 0.65
                    and 0.15 < abs(pt[2]) <= 2.5
                ):
                    sides[pt[2] > 0].append((sum(x * x for x in pt), face, pt))
            sides = [sorted(side)[:5] for side in sides]
            emitted = 0
            failed = []
            for _, a, la in sides[0]:
                for _, b, lb in sides[1]:
                    start, end = scene.nodes[a], scene.nodes[b]
                    if abs(start[1] - end[1]) > 0.45:
                        continue
                    count = max(3, int(math.dist(start, end) / 0.1) + 1)
                    points = []
                    okay = True
                    support_gaps = []
                    for index in range(count + 1):
                        t = index / count
                        expected = tuple(
                            start[i] * (1 - t) + end[i] * t for i in range(3)
                        )
                        pt = local(expected, hint)
                        trigger_point = local(expected, trigger)
                        if (
                            abs(pt[0]) > half_width - 0.1
                            or abs(pt[1]) > 0.65
                            or any(
                                abs(trigger_point[i]) > dimensions[i] * 0.5 + 1e-4
                                for i in range(3)
                            )
                        ):
                            okay = False
                            break
                        hit = scene.ground_support(
                            expected, max_drop=0.4, max_rise=0.25
                        )
                        if hit is None:
                            # User-authorized abstract open door threshold:
                            # supported NAV endpoints cross the confirmed door
                            # once, within real frame/trigger normal bounds.
                            # Missing middle NAV/proxy support is recorded;
                            # no floor or collision exemption is synthesized.
                            if not (
                                transition_bounds[0] <= pt[2] <= transition_bounds[1]
                            ) or index in (0, count):
                                okay = False
                                break
                            support_gaps.append(
                                {"sample": index, "position": expected, "local": pt}
                            )
                            foot = expected
                        elif (
                            abs(hit.position[1] - expected[1]) > 0.3
                            or abs(hit.normal[1]) < 0.5
                        ):
                            okay = False
                            break
                        else:
                            foot = tuple(hit.position)
                        if points and abs(points[-1][1] - foot[1]) > 0.3:
                            okay = False
                            break
                        points.append(foot)
                    if not okay:
                        failed.append(
                            {
                                "fromFace": a,
                                "toFace": b,
                                "reason": "door corridor lacked actual proxy ground support/width/step bound",
                            }
                        )
                        continue
                    motion = scene.check_motion(points, ground_step=True)
                    if not motion["clear"]:
                        failed.append(
                            {
                                "fromFace": a,
                                "toFace": b,
                                "reason": "nonignored source collision blocks body crossing",
                                "hit": motion.get("hit"),
                            }
                        )
                        continue
                    length = sum(math.dist(x, y) for x, y in zip(points, points[1:]))
                    for u, v, pts in ((a, b, points), (b, a, points[::-1])):
                        links.append(
                            {
                                "doorId": door_id,
                                "from": u,
                                "to": v,
                                "kind": "door",
                                "points": pts,
                                "thresholdSupportGaps": support_gaps,
                                "thresholdPolicy": "user-authorized source-confirmed open door transition; unsupported middle samples bounded by actual source frame and oriented DoorTrigger (else declared leaf slab); two supported NAV endpoints; single plane crossing; original body collision checked; no added floors",
                                "seconds": length / 6.0,
                                "enemy": True,
                                "enemySeconds": length / 3.6,
                                "source": {
                                    "type": "joined-source-npcdoorhint",
                                    "entityId": hint["id"],
                                    "scope": hint["scope"],
                                    "qualification": "exact authored door scope + actual two-sided source NAV; ground/body checked without suppressing any collision; custom default-open state, not recovered animation",
                                },
                            }
                        )
                    emitted += 2
                    if emitted >= 6:
                        break
                if emitted >= 6:
                    break
            center = tuple(hint["position"][i] + up[i] * height * 0.5 for i in range(3))
            corners = [
                tuple(
                    hint["position"][i] + right[i] * x + up[i] * y + normal[i] * z
                    for i in range(3)
                )
                for x in (-half_width, half_width)
                for y in (0, height)
                for z in (-half_depth, half_depth)
            ]
            keys = [e for e in group if e["type"] == "/EE/Types/Engine/MoverKey"]
            doors.append(
                {
                    "id": door_id,
                    "sourceEntityId": hint["id"],
                    "sourceScope": hint["scope"],
                    "sourceType": hint["type"],
                    "sourcePosition": hint["position"],
                    "sourceQuaternion": hint["quaternion"],
                    "sourceDoorStatus": (
                        re.search(r"^DoorStatus=([^\n]+)", hint["attributes"], re.M)[1]
                        if re.search(r"^DoorStatus=([^\n]+)", hint["attributes"], re.M)
                        else None
                    ),
                    "movementDefault": "open",
                    "sightDefault": "open",
                    "aperture": {
                        "origin": hint["position"],
                        "center": center,
                        "right": right,
                        "up": up,
                        "normal": normal,
                        "halfWidth": half_width,
                        "height": height,
                        "halfDepth": half_depth,
                        "halfDepthSource": depth_basis,
                        "transitionNormalBounds": transition_bounds,
                        "transitionBoundsSources": frame_sources,
                        "transitionPolicy": "abstract confirmed open door threshold, not recovered source animation or synthesized floor",
                        "aabb": [
                            [min(p[i] for p in corners) for i in range(3)],
                            [max(p[i] for p in corners) for i in range(3)],
                        ],
                        "qualification": "conservative source Width full-width corridor, trigger height clipped3; finite plane only, do not exempt surrounding wall or arbitrary AABB volume",
                    },
                    "sourceThresholdTrigger": (
                        {
                            "entityId": threshold[0]["id"],
                            "dimensions": values(
                                threshold[0]["attributes"], "Dimensions"
                            ),
                            "dimensionsInDoorAxes": threshold[1],
                            "quaternion": threshold[0]["quaternion"],
                            "position": threshold[0]["position"],
                        }
                        if threshold
                        else None
                    ),
                    "sourceAttachedLeafEntityIds": [
                        entity["id"] for entity in attached_leaves
                    ],
                    "sourceTrigger": {
                        "entityId": trigger["id"],
                        "position": trigger["position"],
                        "dimensions": dimensions,
                        "attributes": trigger["attributes"],
                    },
                    "sourceMovers": [
                        {
                            "entityId": e["id"],
                            "position": e["position"],
                            "quaternion": e["quaternion"],
                            "attributes": e["attributes"],
                        }
                        for e in movers
                    ],
                    "sourceMoverKeys": [
                        {
                            "entityId": e["id"],
                            "position": e["position"],
                            "attributes": e["attributes"],
                        }
                        for e in keys
                    ],
                    "sourceFrames": [
                        {
                            "entityId": e["id"],
                            "position": e["position"],
                            "quaternion": e["quaternion"],
                            "attributes": e["attributes"],
                        }
                        for e in frames
                    ],
                    "movementCollisionExemptions": [],
                    "ordinaryWallsRemainSolid": True,
                    "sideFaces": [[x[1] for x in side] for side in sides],
                    "emittedDirectedLinks": emitted,
                    "rejectedCrossings": failed,
                    "qualification": "confirmed authored door entity join; movement opens only emitted checked portal routes; optional closed LOS may intersect finite source plane; no source-wall blanket ignore",
                }
            )
        visual_ids = set()
        visual = json.loads(
            gzip.decompress(
                (output / entry["assets"]["visual-map"]["file"]).read_bytes()
            )
        )
        visual_ids = {instance["entityId"] for instance in visual["instances"]}
        for door in doors:
            door["leafEntityIds"] = [
                entity["entityId"] for entity in door["sourceMovers"]
            ] + door.get("sourceAttachedLeafEntityIds", [])
            door["frameEntityIds"] = [
                entity["entityId"] for entity in door["sourceFrames"]
            ]
            door["visualLeafEntityIds"] = [
                ident for ident in door["leafEntityIds"] if ident in visual_ids
            ]
            door["visualLeafPolicy"] = (
                "default-open hides only these exact source leaf entities; current dynamic leaves absent from static visuals need no hide; never hide frameEntityIds"
            )
            aperture = door["aperture"]
            aperture["planeConstant"] = -sum(
                aperture["normal"][i] * aperture["center"][i] for i in range(3)
            )
            icons = [
                entity
                for entity in by_scope[door["sourceScope"]]
                if entity["type"] == "/Lotus/Fx/Gameplay/DoorIcons/DoorIconPlaneGrineer"
            ]
            door["sourceDoorIcons"] = [
                {"entityId": entity["id"], "position": entity["position"]}
                for entity in icons
            ]
        # Reachability comparison under source-qualified door links.
        before = scene.search(scene.start["face"], "enemy", True)
        for link in links:
            scene._add(
                link["from"],
                link["to"],
                link["points"],
                link["kind"],
                link["seconds"],
                True,
                link["enemySeconds"],
                link["source"],
            )
        after = scene.search(scene.start["face"], "enemy", True)
        candidates = [s for s in scene.spawns if s.get("accepted")]
        summary = {
            "hintCount": sum(
                e["type"] == "/EE/Types/Npc/NpcDoorHint" for e in entities
            ),
            "confirmedDoors": len(doors),
            "doorsWithUsableLinks": sum(d["emittedDirectedLinks"] > 0 for d in doors),
            "directedDoorLinks": len(links),
            "candidateSpawns": len(candidates),
            "enemyCanReachStartBefore": sum(
                math.isfinite(before.d[s["face"]]) for s in candidates
            ),
            "enemyCanReachStartAfter": sum(
                math.isfinite(after.d[s["face"]]) for s in candidates
            ),
            "ordinaryWallsIgnored": False,
        }
        maps[map_id] = {
            "sourceTile": tile,
            **provenance,
            "doors": doors,
            "links": links,
            "rejectedHints": rejected,
            "summary": summary,
        }
        print(json.dumps({"mapId": map_id, **summary}), flush=True)
    value = {
        "schema": "arena-source-doors/v1",
        "parserVersion": PARSER_VERSION + "/source-doors-v2",
        "packagesSha256": sha(packages_bin),
        "policy": {
            "doorMovement": "open",
            "doorSight": "open",
            "version": "confirmed-open-threshold-v2",
            "thresholdSupport": "user-authorized abstract default-open door transition: supported source NAV endpoints, step bound, single door-plane crossing, actual frame normal extent intersected with oriented tagged trigger; missing middle proxy floor recorded, never synthesized",
            "qualification": "scenario default state; source runtime animation/lockdown not simulated; all body crossings checked against ordinary original wall collision; finite confirmed door only, never names or mapwide wall exemption",
        },
        "maps": maps,
    }
    target = output / "door-geometry.json.gz"
    raw = compact(value)
    target.write_bytes(gzip.compress(raw, compresslevel=9, mtime=0))
    latest = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    latest["doorGeometry"] = {
        "file": target.name,
        "schema": value["schema"],
        "sha256": sha(target),
        "jsonSha256": hashlib.sha256(raw).hexdigest(),
        "compressedBytes": target.stat().st_size,
        "jsonBytes": len(raw),
        "maps": {key: record["summary"] for key, record in maps.items()},
        "mapSummaries": {key: record["summary"] for key, record in maps.items()},
    }
    (output / "catalog.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    (case_root / "evidence/geometry/source-door-geometry.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8"
    )
    return value


def _supported_surface_route(scene, support, start, end, *, max_nodes=6000):
    """Bounded local A* on actual source floor layers, not an interpolated bridge.

    The grid only proposes XZ positions; each foot height is an exact ray hit.
    Distinct floor layers remain distinct nodes. Every edge checks <=.45 step,
    source slope, original body collision and source-floor overhead rails.
    """
    import heapq

    lower = [min(start[i], end[i]) - 1.0 for i in range(3)]
    upper = [max(start[i], end[i]) + 1.0 for i in range(3)]
    pitch = 0.16
    cells, locations, positions, witnesses = {}, {}, {-1: start, -2: end}, {}
    for ix in range(int((upper[0] - lower[0]) / pitch) + 1):
        for iz in range(int((upper[2] - lower[2]) / pitch) + 1):
            origin = (lower[0] + ix * pitch, upper[1], lower[2] + iz * pitch)
            rows = []
            for bvh, kind in ((support, "visual"), (scene.collision, "base")):
                for hit in bvh.all_hits(origin, (0, -1, 0), upper[1] - lower[1]):
                    if abs(hit.normal[1]) < 0.55 or any(
                        abs(point[1] - hit.position[1]) < 0.03 for point, _ in rows
                    ):
                        continue
                    rows.append((hit.position, (kind, hit.triangle)))
            cells[ix, iz] = []
            for point, source in rows:
                node = len(locations)
                locations[node] = (ix, iz)
                positions[node], witnesses[node] = point, source
                cells[ix, iz].append(node)
    if len(locations) > max_nodes:
        return None, {
            "reason": "bounded surface grid exceeded",
            "nodes": len(locations),
        }

    def neighbours(node):
        point = positions[node]
        ix, iz = locations.get(
            node,
            (
                round((point[0] - lower[0]) / pitch),
                round((point[2] - lower[2]) / pitch),
            ),
        )
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for other in cells.get((ix + dx, iz + dz), ()):
                    if other != node and abs(positions[other][1] - point[1]) <= 0.45:
                        yield other
        if (
            node >= 0
            and math.dist(point, end) < 0.35
            and abs(point[1] - end[1]) <= 0.45
        ):
            yield -2

    queue, distances, previous = [(math.dist(start, end), 0.0, -1)], {-1: 0.0}, {}
    visited = 0
    while queue:
        _, cost, node = heapq.heappop(queue)
        if cost != distances[node]:
            continue
        if node == -2:
            order = [-2]
            while order[-1] != -1:
                order.append(previous[order[-1]])
            order.reverse()
            return ([positions[k] for k in order], [witnesses.get(k) for k in order]), {
                "visited": visited,
                "gridNodes": len(locations),
                "pitch": pitch,
                "maxLocalStep": 0.45,
                "normalYMinimum": 0.55,
            }
        visited += 1
        for other in neighbours(node):
            a, b = positions[node], positions[other]
            if not scene.check_motion((a, b), ground_step=True)["clear"]:
                continue
            blocked = False
            direction = (b[0] - a[0], 0, b[2] - a[2])
            length = math.hypot(direction[0], direction[2])
            if length > 1e-5:
                for dx, dz in ((0, 0), (0.22, 0), (-0.22, 0), (0, 0.22), (0, -0.22)):
                    for height in (0.5, 1.0, 1.65):
                        if support.raycast(
                            (a[0] + dx, max(a[1], b[1]) + height, a[2] + dz),
                            direction,
                            length - 1e-4,
                        ):
                            blocked = True
                            break
                    if blocked:
                        break
            if blocked:
                continue
            distance = cost + math.dist(a, b)
            if distance < distances.get(other, math.inf):
                distances[other], previous[other] = distance, node
                heapq.heappush(queue, (distance + math.dist(b, end), distance, other))
    return None, {
        "reason": "no source-supported collision-clear surface route",
        "visited": visited,
    }


def import_visual_ground_links(
    case_root, packages_bin, output, *, map_ids=None, surface_faces=None
):
    """Recover short boundary transitions using exact static floor/stair mesh support.

    Adds no synthetic plane, never broadens movement thresholds. Output is a
    separate qualified support/candidate-link sidecar; base NAV/BSP unchanged.
    """
    from collections import defaultdict, Counter
    from import_melee_mechanics import Packages

    package = Packages(packages_bin)
    catalog = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    previous_path = output / "visual-ground-geometry.json.gz"
    records = (
        json.loads(gzip.decompress(previous_path.read_bytes())).get("maps", {})
        if previous_path.exists()
        else {}
    )
    for map_id, entry in catalog["maps"].items():
        if map_ids and map_id not in map_ids:
            continue
        tile = entry["sourceTile"]
        name = tile.rsplit("/", 1)[-1]
        source = (
            case_root
            / "work/geometry"
            / ("galleon" if name == "GrnDefenceTwo" else "map-coverage/" + name)
        )
        if name == "ObjDefense01":
            source = case_root / "work/geometry"
        entities, _ = _read_visual_level(source, tile)
        byid = {e["id"]: e for e in entities}
        # Rebuild without the previous ground sidecar so rerunning does not
        # erase old routes merely because they already merged the components.
        from wfarsenal.arena_scene import ArenaScene, load_asset, load_source_doors

        scene = ArenaScene(
            load_asset(map_id, "scene"),
            load_asset(map_id, "navigation"),
            map_id=map_id,
            doors=load_source_doors(map_id),
        )
        components = scene.movement_components("enemy")
        visual = json.loads(
            gzip.decompress(
                (output / entry["assets"]["visual-map"]["file"]).read_bytes()
            )
        )
        vertices, triangles, sources = [], [], []
        for inst in visual["instances"]:
            mesh = visual["meshes"][inst["meshId"]]
            path = mesh["path"]
            architectural = path.startswith(tile + "/") and path.endswith("_a.fbx")
            if not (
                architectural
                or re.search(r"Floor|Stair|Catwalk|Ramp|Platform|Walkway", path, re.I)
            ) or re.search(r"Railing|Cover|Decal|Light|Door|Water", path, re.I):
                continue
            entity = byid.get(inst["entityId"])
            if not entity:
                continue
            override = re.search(r"^PhysicsBehavior=(.*)$", entity["attributes"], re.M)
            physics = (
                override[1].strip('"')
                if override
                else (
                    package.resolve(entity["type"]).get("PhysicsBehavior")
                    if package.exists(entity["type"])
                    else None
                )
            )
            if physics != "/EE/Types/Physics/Static":
                continue
            points = [
                transform(mesh["positions"][i : i + 3], inst)
                for i in range(0, len(mesh["positions"]), 3)
            ]
            for i in range(0, len(mesh["indices"]), 3):
                ids = mesh["indices"][i : i + 3]
                a, b, c = (points[k] for k in ids)
                normal = _cross(_sub(b, a), _sub(c, a))
                length = math.sqrt(_dot(normal, normal))
                if length < 1e-6 or abs(normal[1]) / length < 0.55:
                    continue
                offset = len(vertices)
                vertices.extend((a, b, c))
                triangles.append([offset, offset + 1, offset + 2])
                sources.append(
                    {
                        "entityId": inst["entityId"],
                        "sourceMesh": path,
                        "sourceMeshSha256": mesh["sha256"],
                        "sourceTriangle": i // 3,
                    }
                )
        support = TriangleBVH(vertices, triangles, native=True)
        V = scene.raw["nav"]["vertices"]
        T = scene.raw["nav"]["triangles"]
        counts = Counter(
            tuple(sorted((a, b)))
            for t in T
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))
        )
        boundary = []
        for f, t in enumerate(T):
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                if counts[tuple(sorted((a, b)))] == 1:
                    pt = tuple(
                        (V[a][i] + V[b][i]) * 0.475 + scene.nodes[f][i] * 0.05
                        for i in range(3)
                    )
                    boundary.append((f, pt))
        candidates = defaultdict(list)
        for index, (a, pa) in enumerate(boundary):
            for b, pb in boundary[index + 1 :]:
                if (
                    components[a] == components[b]
                    or abs(pa[1] - pb[1]) > 0.65
                    or math.hypot(pa[0] - pb[0], pa[2] - pb[2]) > 2.0
                ):
                    continue
                key = tuple(sorted((components[a], components[b])))
                rows = candidates[key]
                rows.append((math.dist(pa, pb), a, b, pa, pb))
                rows.sort(key=lambda r: (r[0], r[1], r[2]))
                del rows[16:]
        links = []
        failures = Counter()
        for key, rows in candidates.items():
            for rank, (_, a, b, pa, pb) in enumerate(rows):
                baseline = [scene.nodes[a], pa, pb, scene.nodes[b]]
                points = []
                witness = []
                valid = True
                for start, end in zip(baseline, baseline[1:]):
                    n = max(2, int(math.dist(start, end) / 0.12) + 1)
                    for index in range(n):
                        t = index / n
                        expected = tuple(
                            start[i] * (1 - t) + end[i] * t for i in range(3)
                        )
                        origin = (expected[0], expected[1] + 0.5, expected[2])
                        old = scene.collision.raycast(origin, (0, -1, 0), 1.1)
                        extra = support.raycast(origin, (0, -1, 0), 1.1)
                        options = [
                            (hit, kind)
                            for hit, kind in ((old, "base"), (extra, "visual"))
                            if hit and abs(hit.position[1] - expected[1]) <= 0.6
                        ]
                        if not options:
                            failures["no-source-support"] += 1
                            valid = False
                            break
                        hit, kind = min(
                            options,
                            key=lambda row: abs(row[0].position[1] - expected[1]),
                        )
                        if points and abs(hit.position[1] - points[-1][1]) > 0.5:
                            failures["source-step-too-high"] += 1
                            valid = False
                            break
                        points.append(hit.position)
                        if kind == "visual":
                            witness.append(
                                {"sample": len(points) - 1, **sources[hit.triangle]}
                            )
                    if not valid:
                        break
                if not valid:
                    continue
                points.append(scene.nodes[b])
                if not scene.check_motion(points, ground_step=True)["clear"]:
                    failures["base-wall-body-blocked"] += 1
                    continue
                bodyclear = True
                for aa, bb in zip(points, points[1:]):
                    for dx, dz in ((0, 0), (0.2, 0), (-0.2, 0), (0, 0.2), (0, -0.2)):
                        for h in (0.5, 1.0, 1.65):
                            y = max(aa[1], bb[1]) + h
                            direction = (bb[0] - aa[0], 0, bb[2] - aa[2])
                            dist = math.sqrt(_dot(direction, direction))
                            if dist > 1e-5 and support.raycast(
                                (aa[0] + dx, y, aa[2] + dz), direction, dist - 1e-4
                            ):
                                bodyclear = False
                                break
                        if not bodyclear:
                            break
                    if not bodyclear:
                        break
                if not bodyclear:
                    failures["source-floor-overhead-blocked"] += 1
                    continue
                if not witness:
                    failures["no-new-visual-support-used"] += 1
                    continue
                # Retain small exact source support triangle footprints for the
                # admitted path, not all eligible visual floors as new solids.
                used_triangles = []
                for index, tri_source in enumerate(sources):
                    if any(
                        tri_source["entityId"] == item["entityId"]
                        and tri_source["sourceTriangle"] == item["sourceTriangle"]
                        for item in witness
                    ):
                        used_triangles.append(index)
                length = sum(math.dist(x, y) for x, y in zip(points, points[1:]))
                for u, v, pts in ((a, b, points), (b, a, points[::-1])):
                    links.append(
                        {
                            "from": u,
                            "to": v,
                            "kind": "source-floor-step",
                            "points": pts,
                            "seconds": length / 6.0,
                            "enemy": True,
                            "enemySeconds": length / 3.6,
                            "source": {
                                "type": "actual-static-visual-floor-supported-boundary",
                                "candidateRank": rank,
                                "supportTriangleIds": used_triangles,
                                "supportWitness": witness,
                                "qualification": "thresholds unchanged: <=2horizontal,.65endpoint height,.5localstep; exact visual floor support plus original wall collision; not recovered game offmesh",
                            },
                        }
                    )
                break
        surface_audit = []
        if surface_faces:
            # Surface queries must see this pass's admitted short floor links:
            # their merged components determine which exits remain missing.
            for link in links:
                scene._add(
                    link["from"],
                    link["to"],
                    link["points"],
                    link["kind"],
                    link["seconds"],
                    True,
                    link["enemySeconds"],
                    link["source"],
                )
            scene._movement_component_cache = None
            components = scene.movement_components("enemy")
            selected = {components[face] for face in surface_faces}
            options = {}
            for edges in scene.graph:
                for edge in edges:
                    a, b = edge.from_node, edge.to_node
                    if (
                        edge.enemy
                        or components[a] == components[b]
                        or not ({components[a], components[b]} & selected)
                    ):
                        continue
                    start, end = scene.nodes[a], scene.nodes[b]
                    if (
                        math.hypot(start[0] - end[0], start[2] - end[2]) > 6
                        or abs(start[1] - end[1]) > 6
                    ):
                        continue
                    key = tuple(sorted((components[a], components[b])))
                    row = (math.dist(start, end), min(a, b), max(a, b))
                    rows = options.setdefault(key, [])
                    if row not in rows:
                        rows.append(row)
                        rows.sort()
                        del rows[4:]
            for key, (_, a, b) in (
                (key, row) for key, rows in sorted(options.items()) for row in rows
            ):
                result, audit = _supported_surface_route(
                    scene, support, scene.nodes[a], scene.nodes[b]
                )
                surface_audit.append(dict(audit, fromFace=a, toFace=b))
                if result is None:
                    continue
                points, hits = result
                used = sorted({hit[1] for hit in hits if hit and hit[0] == "visual"})
                if not used:
                    continue
                witness = [
                    {"sample": i, **sources[hit[1]]}
                    for i, hit in enumerate(hits)
                    if hit and hit[0] == "visual"
                ]
                length = sum(math.dist(x, y) for x, y in zip(points, points[1:]))
                for u, v, pts in ((a, b, points), (b, a, points[::-1])):
                    links.append(
                        {
                            "from": u,
                            "to": v,
                            "kind": "source-surface-walk",
                            "points": pts,
                            "seconds": length / 6,
                            "enemy": True,
                            "enemySeconds": length / 3.6,
                            "source": {
                                "type": "actual-static-surface-route",
                                "supportTriangleIds": used,
                                "supportWitness": witness,
                                "routeAudit": audit,
                                "qualification": "bounded local search on exact source visual architecture/floor and original NAV support; per-edge step <=.45; original collision and overhead rails checked; no jump, synthetic floor or collision exemption",
                            },
                        }
                    )
        records[map_id] = {
            "surfaceRouteAudit": surface_audit,
            "support": {
                "vertices": vertices,
                "triangles": triangles,
                "triangleSources": sources,
                "qualification": "exact upward-facing qualified static floor/stair/catwalk triangles only; not arbitrary prop solidity",
            },
            "links": links,
            "failures": dict(failures),
            "summary": {
                "sourceFloorTriangles": len(triangles),
                "directedGroundLinks": len(links),
                "componentPairsTried": len(candidates),
            },
        }
        print(
            json.dumps(
                {
                    "mapId": map_id,
                    **records[map_id]["summary"],
                    "failures": dict(failures),
                }
            ),
            flush=True,
        )
    value = {
        "schema": "arena-source-ground/v1",
        "packagesSha256": sha(packages_bin),
        "maps": records,
    }
    # Compact support payload to only exact triangles witnessed by accepted links.
    for record in records.values():
        full = record["support"]
        used = sorted(
            {
                index
                for link in record["links"]
                for index in link["source"]["supportTriangleIds"]
            }
        )
        compact_vertices = []
        compact_triangles = []
        compact_sources = []
        remap = {old: new for new, old in enumerate(used)}
        for old in used:
            tri = full["triangles"][old]
            offset = len(compact_vertices)
            compact_vertices.extend(full["vertices"][k] for k in tri)
            compact_triangles.append([offset, offset + 1, offset + 2])
            compact_sources.append(full["triangleSources"][old])
        for link in record["links"]:
            link["source"]["supportTriangleIds"] = [
                remap[index] for index in link["source"]["supportTriangleIds"]
            ]
        record["support"] = {
            "vertices": compact_vertices,
            "triangles": compact_triangles,
            "triangleSources": compact_sources,
            "qualification": "exact source floor triangles witnessed by accepted traversals only; no broad solid-prop conversion",
        }
        record["summary"]["admittedSupportTriangles"] = len(compact_triangles)
    target = output / "visual-ground-geometry.json.gz"
    raw = compact(value)
    target.write_bytes(gzip.compress(raw, mtime=0))
    latest = json.loads((output / "catalog.json").read_text(encoding="utf8"))
    latest["groundGeometry"] = {
        "file": target.name,
        "sha256": sha(target),
        "jsonSha256": hashlib.sha256(raw).hexdigest(),
        "compressedBytes": target.stat().st_size,
        "jsonBytes": len(raw),
    }
    (output / "catalog.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    (case_root / "evidence/geometry/source-visual-ground-geometry.json").write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf8"
    )
    return value


def import_enemy_specs(
    specs_path: Path,
    packages_path: Path,
    output: Path,
    *,
    candidate_nodes: Path | None = None,
    enemies_path: Path | None = None,
    mission_coverage: Path | None = None,
):
    """Resolve explicit selected mission groups through STANDARD Agent Avatars.

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
    coverage = (
        json.loads(mission_coverage.read_text(encoding="utf-8"))
        if mission_coverage
        else None
    )
    explicit_paths = set()
    scope_by_path = {}
    if coverage:
        for node in coverage["nodes"]:
            for path in node.get("enemySpecPaths", []):
                explicit_paths.add(path)
                scope_by_path[path] = scope_by_path.get(path, False) or node.get(
                    "inScope", True
                )

    legacy_paths = {
        row["path"]
        for row in specs
        if "Defense" in row["path"].rsplit("/", 1)[-1]
        or "Interception" in row["path"].rsplit("/", 1)[-1]
    }
    selected_paths = legacy_paths | explicit_paths
    # Re-read all selected groups from this current package. The historical
    # extracted list chooses only legacy optional groups, never supplies stats.
    specs = []
    source_unsupported = []
    for path in sorted(selected_paths):
        try:
            fields = package.resolve(path)
            enemies = fields.get("Enemies", [])
            if not isinstance(enemies, list):
                raise ValueError("Enemies is not a source list")
            specs.append(
                dict(
                    path=path,
                    parent=package.parent(path),
                    enemies=enemies,
                    count=len(enemies),
                    probability_sum=sum(
                        float(e.get("probability", 0.0)) for e in enemies
                    ),
                    tiers=sorted({e.get("tier", 0) for e in enemies}),
                    source_fields=fields,
                    scope_included=scope_by_path.get(path, True),
                )
            )
        except Exception as exc:
            source_unsupported.append(
                dict(
                    path=path,
                    reason="group-source-parse-error:" + type(exc).__name__,
                    detail=str(exc),
                )
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
                "killXpReward": package.resolve(resolved).get("KillXPReward", 50) if resolved else None,
                "killXpSource": ("Packages-Avatar-inheritance" if resolved and "KillXPReward" in package.resolve(resolved)
                                 else "native-template-XP-default50" if resolved else None),
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
            "xp": standard.get("killXpReward"),
            "eximusXp": variants.get("EXIMUS", {}).get("killXpReward"),
        }
        memo[agent] = value
        return value

    for spec in specs:
        path = spec["path"]
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
        if coverage:
            candidates = [
                dict(
                    node=n["nodeId"],
                    name=n["nodeName"],
                    planet=n["planet"],
                    planetZh=n["planetZh"],
                    missionType=n["missionType"],
                    mapIds=n["mapIds"],
                    sourceFields=[
                        r["field"]
                        for r in n["enemySpecEvidence"]["references"]
                        if r["path"] == path
                    ],
                    links=[n["sourceProc"], path],
                    basis="exact-current-MissionInfo-resource-fields",
                    offset=n["evidence"]["nodeOffset"],
                )
                for n in coverage["nodes"]
                if path in n.get("enemySpecPaths", [])
            ]
        entries = []
        for index, raw in enumerate(spec["enemies"]):
            agent = raw.get("agent") if isinstance(raw, dict) else None
            resolved = (
                avatars(agent)
                if isinstance(agent, str) and agent.startswith("/Lotus/Types/Enemies/")
                else dict(
                    resolvedAvatarPath=None,
                    presentInFrozenEnemies=False,
                    resolutionStatus="nonstandard-or-nested-agent-unsupported",
                    resolutionError="nonstandard-or-nested-agent-unsupported",
                    agentInheritanceChain=[],
                    avatarVariants={},
                )
            )
            entry = dict(raw, rowIndex=index, **resolved)
            entry["runnable"] = bool(
                entry["resolvedAvatarPath"]
                and entry["presentInFrozenEnemies"]
                and not entry["resolutionError"]
                and spec["scope_included"]
            )
            entry["availabilityStatus"] = (
                "aerial-group-excluded-from-ground-scope"
                if not spec["scope_included"]
                else (
                    "exact-frozen-avatar"
                    if entry["runnable"]
                    else (
                        "current-avatar-not-in-frozen-catalog"
                        if entry["resolvedAvatarPath"]
                        and not entry["presentInFrozenEnemies"]
                        else entry["resolutionStatus"]
                    )
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
                "parent": spec["parent"],
                "scopeIncluded": spec["scope_included"],
                "selectionStatus": (
                    "node-reference-confirmed"
                    if path in explicit_paths
                    else "legacy-optional-workload-source"
                ),
                "runnable": any(
                    e["runnable"] and float(e.get("probability", 0)) > 0
                    for e in entries
                ),
                "sourceFields": spec["source_fields"],
                "sourceStatus": (
                    "aerial-excluded"
                    if not spec["scope_included"]
                    else (
                        "event-resources-no-ordinary-enemies"
                        if not entries and spec["source_fields"].get("EventResources")
                        else (
                            "ordinary-enemies-with-special-fields"
                            if any(
                                spec["source_fields"].get(k)
                                for k in ("AdvancedAiDirectorSpawns", "NpcEncounters")
                            )
                            else "ordinary-enemies"
                        )
                    )
                ),
                "unsupportedReason": (
                    "aerial-group-excluded-from-ground-scope"
                    if not spec["scope_included"]
                    else (
                        "event-resources-have-no-ordinary-ground-Enemies-list"
                        if not entries and spec["source_fields"].get("EventResources")
                        else None
                    )
                ),
                "unsupportedSourceFields": {
                    k: "retained-not-flattened-into-ground-enemies"
                    for k in (
                        "EventResources",
                        "AdvancedAiDirectorSpawns",
                        "NpcEncounters",
                    )
                    if spec["source_fields"].get(k)
                },
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
        "parserVersion": PARSER_VERSION + "/enemy-specs-v3-source-xp",
        "currentAgentSourceBuild": "2026.10.28.09.54",
        "frozenEnemyBuild": (
            frozen.get("buildLabel") if isinstance(frozen, dict) else None
        ),
        "sources": [
            {"file": str(path.name), "bytes": path.stat().st_size, "sha256": sha(path)}
            for path in inputs
        ]
        + (
            [
                {
                    "file": "mission-node-enemySpec-reference-subset",
                    "bytes": len(
                        compact(
                            [
                                {
                                    "nodeId": n["nodeId"],
                                    "inScope": n.get("inScope", True),
                                    "enemySpecPaths": n.get("enemySpecPaths", []),
                                    "enemySpecEvidence": n.get("enemySpecEvidence", {}),
                                }
                                for n in coverage["nodes"]
                            ]
                        )
                    ),
                    "sha256": hashlib.sha256(
                        compact(
                            [
                                {
                                    "nodeId": n["nodeId"],
                                    "inScope": n.get("inScope", True),
                                    "enemySpecPaths": n.get("enemySpecPaths", []),
                                    "enemySpecEvidence": n.get("enemySpecEvidence", {}),
                                }
                                for n in coverage["nodes"]
                            ]
                        )
                    ).hexdigest(),
                }
            ]
            if coverage
            else []
        ),
        "qualification": [
            "Raw source tier/probability/maxSimultaneous/weaponOverrides/mergeSymbol preserved unchanged.",
            "STANDARD AvatarTypes/AvatarType resolved through explicit current Packages inheritance; no approximate Avatar substitution.",
            "Current Agent source and older frozen damage catalog are separate versions; exact path existence does not prove stat parity.",
            "Optional scenario rule: normalize positive runnable weights within a user-selected tier only; this is NOT native observed spawn frequency.",
            "Template XP uses current Avatar inheritance or native default50 confirmed from the current LotusNpcAvatar constructor and P16 XP getter; live-context multipliers are not applied.",
            "mapCandidates use exact MissionInfo enemySpec/extraEnemySpec fields when mission coverage is supplied; never infer a group from shared tile geometry.",
            "EventResources/AdvancedAiDirectorSpawns/NpcEncounters remain explicit special-source metadata; they are not flattened into ordinary ground enemies.",
        ],
        "excludedSpecs": excluded,
        "unsupportedSpecs": source_unsupported,
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
    parser.add_argument("--audit-visual-support", action="store_true")
    parser.add_argument("--source-ground", action="store_true")
    parser.add_argument("--source-doors", action="store_true")
    parser.add_argument("--ground-surface-face", type=int, action="append")
    parser.add_argument("--complete-visuals", action="store_true")
    parser.add_argument("--case-root", type=Path)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--visual-map-id", action="append")
    parser.add_argument("--raw-tile-dir", type=Path)
    parser.add_argument("--tile-path")
    parser.add_argument("--prepared-source", type=Path)
    parser.add_argument("--proc-file", type=Path)
    parser.add_argument("--enemy-specs-source", type=Path)
    parser.add_argument("--packages-bin", type=Path)
    parser.add_argument("--candidate-nodes", type=Path)
    parser.add_argument("--enemies", type=Path)
    parser.add_argument("--enemy-specs-only", action="store_true")
    parser.add_argument("--mission-coverage", type=Path)
    args = parser.parse_args()
    if args.source_ground:
        if not args.case_root or not args.packages_bin:
            parser.error("--source-ground requires --case-root --packages-bin")
        import_visual_ground_links(
            args.case_root,
            args.packages_bin,
            args.output,
            map_ids=args.visual_map_id,
            surface_faces=args.ground_surface_face,
        )
        return
    if args.source_doors:
        if not args.case_root or not args.packages_bin:
            parser.error("--source-doors requires --case-root --packages-bin")
        import_source_doors(
            args.case_root, args.packages_bin, args.output, map_ids=args.visual_map_id
        )
        return
    if args.audit_visual_support:
        if not args.case_root:
            parser.error("--audit-visual-support requires --case-root")
        audit_visual_support(args.output, args.case_root, map_ids=args.visual_map_id)
        return
    if args.complete_visuals:
        if not all((args.case_root, args.cache_dir, args.exporter, args.packages_bin)):
            parser.error(
                "--complete-visuals requires --case-root --cache-dir --exporter --packages-bin"
            )
        complete_visual_maps(
            args.case_root,
            args.cache_dir,
            args.exporter,
            args.packages_bin,
            args.output,
            map_ids=args.visual_map_id,
        )
        return
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
            mission_coverage=args.mission_coverage,
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
